"""
Inventory Management System - Low Level Design
==============================================

Multi-warehouse stock with a two-phase reserve -> commit/release flow.

    on_hand    physical units on the shelf
    reserved   units promised to orders that have not shipped yet
    available  on_hand - reserved   (what we may still promise)

Invariant, per (sku, warehouse), held under that item's lock:
    0 <= reserved <= on_hand

Order flow:
    reserve(order_id, {sku: qty})  -> Reservation (ACTIVE, has a TTL)
    commit(reservation_id)         -> stock leaves the building (on_hand and reserved drop)
    release(reservation_id)        -> order cancelled, units become available again
    expire_reservations()          -> sweeper releases ACTIVE reservations past their TTL

Concurrency model: one lock per InventoryItem. Any operation touching several
items acquires their locks in a global sorted order (sku, warehouse_id), so two
requests can never deadlock and a multi-line reservation is all-or-nothing.

Extension points (ABCs): AllocationStrategy (which warehouse fills a line) and
ReorderPolicy (when and how much to replenish).

Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import itertools
import math
import threading
import time
from abc import ABC, abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

Clock = Callable[[], float]  # seconds since epoch; injectable for tests
SECONDS_PER_DAY = 86_400


# ---------------------------------------------------------------- errors

class InventoryError(Exception):
    """Base class for domain errors."""


class NotFoundError(InventoryError):
    pass


class InsufficientStockError(InventoryError):
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(f"{sku}: requested {requested}, available {available}")
        self.sku, self.requested, self.available = sku, requested, available


class InvalidStateError(InventoryError):
    """An operation is not allowed in the object's current state."""


class ReservationExpiredError(InvalidStateError):
    pass


class IdempotencyConflictError(InventoryError):
    """Same order_id reused with different lines, or a concurrent duplicate is in flight."""


# ---------------------------------------------------------------- enums

class MovementType(Enum):
    RECEIVE = "receive"            # goods in (PO receipt, manual receipt)
    SHIP = "ship"                  # committed reservation leaves the warehouse
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUST = "adjust"              # cycle-count correction, damage, shrinkage


class ReservationStatus(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


class POStatus(Enum):
    OPEN = "open"
    RECEIVED = "received"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------- value objects

@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    unit_price: Decimal
    reorder_level: int = 10       # reorder when inventory position <= this
    reorder_quantity: int = 50    # default / minimum order size


@dataclass(frozen=True)
class Warehouse:
    warehouse_id: str
    name: str
    priority: int = 0             # lower = preferred (e.g. closer to customers, cheaper to ship)


@dataclass(frozen=True)
class Movement:
    """Immutable ledger entry. Only physical changes to on_hand are recorded."""
    movement_id: int
    sku: str
    warehouse_id: str
    type: MovementType
    delta: int                    # signed change to on_hand
    on_hand_after: int
    reference: str
    at: float


@dataclass(frozen=True)
class ReservationLine:
    sku: str
    warehouse_id: str
    quantity: int


@dataclass(frozen=True)
class StockView:
    """What an AllocationStrategy is allowed to see (read under the item locks)."""
    warehouse_id: str
    priority: int
    available: int


# ---------------------------------------------------------------- stock per (sku, warehouse)

class InventoryItem:
    """Stock of one product at one warehouse. All mutators require self.lock to be held."""

    def __init__(self, product: Product, warehouse: Warehouse):
        self.product = product
        self.warehouse = warehouse
        self.lock = threading.Lock()
        self._on_hand = 0
        self._reserved = 0

    @property
    def key(self) -> Tuple[str, str]:
        return (self.product.sku, self.warehouse.warehouse_id)

    @property
    def on_hand(self) -> int:
        return self._on_hand

    @property
    def reserved(self) -> int:
        return self._reserved

    @property
    def available(self) -> int:
        return self._on_hand - self._reserved

    def receive(self, qty: int) -> None:
        self._on_hand += qty

    def correct(self, delta: int) -> None:
        """Cycle-count correction; the caller guarantees on_hand stays >= reserved."""
        if self._on_hand + delta < self._reserved:
            raise InvalidStateError(f"{self.key}: correction would drop on_hand below reserved")
        self._on_hand += delta

    def reserve(self, qty: int) -> None:
        if qty > self.available:
            raise InsufficientStockError(self.product.sku, qty, self.available)
        self._reserved += qty

    def release(self, qty: int) -> None:
        if qty > self._reserved:  # would mean a bookkeeping bug: fail loudly, never clamp
            raise InvalidStateError(f"{self.key}: releasing {qty} but only {self._reserved} reserved")
        self._reserved -= qty

    def ship_reserved(self, qty: int) -> None:
        """Commit: units that were reserved physically leave."""
        if qty > self._reserved:
            raise InvalidStateError(f"{self.key}: shipping {qty} but only {self._reserved} reserved")
        self._reserved -= qty
        self._on_hand -= qty

    def remove_available(self, qty: int) -> None:
        """Take unreserved units (transfer out, write-off). Never touches promised stock."""
        if qty > self.available:
            raise InsufficientStockError(self.product.sku, qty, self.available)
        self._on_hand -= qty

    def __repr__(self) -> str:
        return (f"InventoryItem({self.product.sku}@{self.warehouse.warehouse_id}: "
                f"on_hand={self._on_hand}, reserved={self._reserved})")


# ---------------------------------------------------------------- reservations & POs

@dataclass
class Reservation:
    reservation_id: str
    order_id: str
    lines: Tuple[ReservationLine, ...]
    expires_at: float
    status: ReservationStatus = ReservationStatus.ACTIVE
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def requested(self) -> Dict[str, int]:
        """Lines collapsed back to {sku: qty}; used for idempotency comparison."""
        out: Dict[str, int] = {}
        for line in self.lines:
            out[line.sku] = out.get(line.sku, 0) + line.quantity
        return out


@dataclass
class PurchaseOrder:
    po_id: str
    sku: str
    warehouse_id: str
    quantity: int
    status: POStatus = POStatus.OPEN


# ---------------------------------------------------------------- strategies

class AllocationStrategy(ABC):
    """Decides which warehouses fill a line. Pure function of the snapshot it is given."""

    @abstractmethod
    def allocate(self, qty: int, stock: Sequence[StockView]) -> Optional[List[Tuple[str, int]]]:
        """Return [(warehouse_id, qty), ...] summing to qty, or None if it cannot be filled."""


class GreedySplitAllocation(AllocationStrategy):
    """Fill from the most preferred warehouse first, spilling over to the next."""

    def allocate(self, qty: int, stock: Sequence[StockView]) -> Optional[List[Tuple[str, int]]]:
        plan, remaining = [], qty
        for s in sorted(stock, key=lambda s: (s.priority, s.warehouse_id)):
            take = min(remaining, s.available)
            if take > 0:
                plan.append((s.warehouse_id, take))
                remaining -= take
            if remaining == 0:
                return plan
        return None


class SingleWarehouseFirstAllocation(AllocationStrategy):
    """Prefer one warehouse that can fill the whole line (one shipment); split only if none can."""

    def __init__(self) -> None:
        self._fallback = GreedySplitAllocation()

    def allocate(self, qty: int, stock: Sequence[StockView]) -> Optional[List[Tuple[str, int]]]:
        for s in sorted(stock, key=lambda s: (s.priority, s.warehouse_id)):
            if s.available >= qty:
                return [(s.warehouse_id, qty)]
        return self._fallback.allocate(qty, stock)


@dataclass(frozen=True)
class ReorderContext:
    product: Product
    warehouse_id: str
    position: int                 # available + quantity on open POs
    avg_daily_demand: float       # shipped units / day over the lookback window


class ReorderPolicy(ABC):
    @abstractmethod
    def reorder_quantity(self, ctx: ReorderContext) -> int:
        """Units to order now; 0 means no reorder."""


class FixedReorderPolicy(ReorderPolicy):
    """Classic (s, Q): when position <= reorder_level, order reorder_quantity."""

    def reorder_quantity(self, ctx: ReorderContext) -> int:
        return ctx.product.reorder_quantity if ctx.position <= ctx.product.reorder_level else 0


class DemandBasedReorderPolicy(ReorderPolicy):
    """Reorder point = demand over (lead time + safety days); order enough for cover_days."""

    def __init__(self, lead_time_days: int = 7, safety_days: int = 3, cover_days: int = 14):
        self._lead, self._safety, self._cover = lead_time_days, safety_days, cover_days

    def reorder_quantity(self, ctx: ReorderContext) -> int:
        reorder_point = max(ctx.product.reorder_level,
                            math.ceil(ctx.avg_daily_demand * (self._lead + self._safety)))
        if ctx.position > reorder_point:
            return 0
        target = math.ceil(ctx.avg_daily_demand * self._cover)
        return max(ctx.product.reorder_quantity, target - ctx.position)


# ---------------------------------------------------------------- service

class InventoryService:
    def __init__(self,
                 allocation: Optional[AllocationStrategy] = None,
                 reorder_policy: Optional[ReorderPolicy] = None,
                 reservation_ttl_s: float = 15 * 60,
                 demand_lookback_days: int = 30,
                 clock: Clock = time.time):
        self._allocation = allocation or SingleWarehouseFirstAllocation()
        self._reorder_policy = reorder_policy or FixedReorderPolicy()
        self._ttl = reservation_ttl_s
        self._lookback_days = demand_lookback_days
        self._clock = clock

        # Catalog + item registry. _registry_lock guards these dicts, not item contents.
        self._registry_lock = threading.Lock()
        self._products: Dict[str, Product] = {}
        self._warehouses: Dict[str, Warehouse] = {}
        self._items: Dict[Tuple[str, str], InventoryItem] = {}

        # Reservations. _res_lock guards the dicts; each Reservation has its own lock for transitions.
        self._res_lock = threading.Lock()
        self._reservations: Dict[str, Reservation] = {}
        self._by_order: Dict[str, Reservation] = {}
        self._in_flight_orders: set[str] = set()

        self._po_lock = threading.Lock()
        self._purchase_orders: Dict[str, PurchaseOrder] = {}

        self._ledger_lock = threading.Lock()
        self._ledger: List[Movement] = []   # append-only; in production this is a DB table

        self._ids = itertools.count(1)

    # ---- catalog -------------------------------------------------------

    def add_product(self, product: Product) -> Product:
        if product.unit_price < 0:
            raise ValueError("unit_price must be >= 0")
        with self._registry_lock:
            if product.sku in self._products:
                raise InventoryError(f"duplicate sku {product.sku}")
            self._products[product.sku] = product
        return product

    def add_warehouse(self, warehouse: Warehouse) -> Warehouse:
        with self._registry_lock:
            if warehouse.warehouse_id in self._warehouses:
                raise InventoryError(f"duplicate warehouse {warehouse.warehouse_id}")
            self._warehouses[warehouse.warehouse_id] = warehouse
        return warehouse

    # ---- stock in / out ------------------------------------------------

    def receive_stock(self, sku: str, warehouse_id: str, qty: int, reference: str = "") -> InventoryItem:
        _require_positive(qty)
        item = self._get_or_create_item(sku, warehouse_id)
        with item.lock:
            item.receive(qty)
            self._record(item, MovementType.RECEIVE, qty, reference)
        return item

    def adjust_stock(self, sku: str, warehouse_id: str, counted_on_hand: int, reason: str) -> int:
        """Cycle count: set on_hand to what was physically counted. Returns the delta.

        Refuses to drop below what is already promised; in production this raises an
        incident instead, because those reservations are now oversold.
        """
        if counted_on_hand < 0:
            raise ValueError("counted_on_hand must be >= 0")
        item = self._get_item(sku, warehouse_id)
        with item.lock:
            if counted_on_hand < item.reserved:
                raise InsufficientStockError(sku, item.reserved, counted_on_hand)
            delta = counted_on_hand - item.on_hand
            if delta:
                item.correct(delta)
                self._record(item, MovementType.ADJUST, delta, reason)
            return delta

    def transfer_stock(self, sku: str, from_wh: str, to_wh: str, qty: int) -> None:
        """Atomic move of *available* units. Both items are locked in key order, so either
        both sides change or neither does, and two opposite transfers cannot deadlock."""
        _require_positive(qty)
        if from_wh == to_wh:
            raise ValueError("source and destination are the same warehouse")
        src = self._get_item(sku, from_wh)
        dst = self._get_or_create_item(sku, to_wh)  # validates to_wh before anything moves
        with self._lock_all([src, dst]):
            src.remove_available(qty)
            dst.receive(qty)
            ref = f"transfer {from_wh}->{to_wh}"
            self._record(src, MovementType.TRANSFER_OUT, -qty, ref)
            self._record(dst, MovementType.TRANSFER_IN, qty, ref)

    # ---- reservations: reserve -> commit | release | expire -------------

    def reserve(self, order_id: str, request: Mapping[str, int]) -> Reservation:
        """All-or-nothing reservation of every line, possibly split across warehouses.

        Idempotent on order_id: a retry with the same lines returns the original reservation.
        """
        if not request:
            raise ValueError("empty request")
        for qty in request.values():
            _require_positive(qty)
        wanted = dict(request)

        with self._res_lock:
            existing = self._by_order.get(order_id)
            if existing is not None:
                if existing.requested() != wanted:
                    raise IdempotencyConflictError(f"order {order_id} already reserved with different lines")
                return existing
            if order_id in self._in_flight_orders:
                raise IdempotencyConflictError(f"order {order_id} is already being reserved")
            self._in_flight_orders.add(order_id)

        try:
            items = self._items_for_skus(wanted.keys())
            with self._lock_all(items):
                lines = self._plan(wanted, items)            # raises before any mutation
                by_key = {i.key: i for i in items}
                for line in lines:
                    by_key[(line.sku, line.warehouse_id)].reserve(line.quantity)
                reservation = Reservation(f"RSV-{next(self._ids)}", order_id, tuple(lines),
                                          expires_at=self._clock() + self._ttl)
            with self._res_lock:
                self._reservations[reservation.reservation_id] = reservation
                self._by_order[order_id] = reservation
            return reservation
        finally:
            with self._res_lock:
                self._in_flight_orders.discard(order_id)

    def commit(self, reservation_id: str, reference: str = "") -> Reservation:
        """Order shipped/paid: reserved units physically leave. ACTIVE -> COMMITTED only."""
        res = self._get_reservation(reservation_id)
        with res.lock:
            if res.status is ReservationStatus.COMMITTED:
                return res                                    # idempotent retry
            if res.status is ReservationStatus.ACTIVE and self._clock() >= res.expires_at:
                self._release_locked(res, ReservationStatus.EXPIRED)
            if res.status is ReservationStatus.EXPIRED:
                raise ReservationExpiredError(f"{reservation_id} expired")
            if res.status is not ReservationStatus.ACTIVE:
                raise InvalidStateError(f"{reservation_id} is {res.status.value}")
            items = {l: self._get_item(l.sku, l.warehouse_id) for l in res.lines}
            with self._lock_all(list(items.values())):
                for line, item in items.items():
                    item.ship_reserved(line.quantity)
                    self._record(item, MovementType.SHIP, -line.quantity, reference or res.order_id)
            res.status = ReservationStatus.COMMITTED
            return res

    def release(self, reservation_id: str) -> Reservation:
        """Order cancelled: give units back. Idempotent; refuses to un-ship a committed order."""
        res = self._get_reservation(reservation_id)
        with res.lock:
            if res.status in (ReservationStatus.RELEASED, ReservationStatus.EXPIRED):
                return res
            if res.status is ReservationStatus.COMMITTED:
                raise InvalidStateError(f"{reservation_id} already committed; use a return flow")
            self._release_locked(res, ReservationStatus.RELEASED)
            return res

    def expire_reservations(self) -> List[Reservation]:
        """Sweeper: release ACTIVE reservations whose TTL has passed."""
        now = self._clock()
        with self._res_lock:
            candidates = [r for r in self._reservations.values()
                          if r.status is ReservationStatus.ACTIVE and r.expires_at <= now]
        expired = []
        for res in candidates:
            with res.lock:  # re-check: a commit may have won the race since the snapshot
                if res.status is ReservationStatus.ACTIVE:
                    self._release_locked(res, ReservationStatus.EXPIRED)
                    expired.append(res)
        return expired

    # ---- replenishment ---------------------------------------------------

    def check_reorder(self) -> List[PurchaseOrder]:
        """Raise POs where the policy says so. Open POs count toward the inventory position,
        so calling this repeatedly does not create duplicate orders."""
        created = []
        with self._po_lock:
            for item in self._all_items():
                with item.lock:
                    available = item.available
                sku, wh = item.key
                on_order = sum(po.quantity for po in self._purchase_orders.values()
                               if po.status is POStatus.OPEN and (po.sku, po.warehouse_id) == item.key)
                ctx = ReorderContext(item.product, wh, available + on_order, self._avg_daily_demand(sku, wh))
                qty = self._reorder_policy.reorder_quantity(ctx)
                if qty > 0:
                    po = PurchaseOrder(f"PO-{next(self._ids)}", sku, wh, qty)
                    self._purchase_orders[po.po_id] = po
                    created.append(po)
        return created

    def receive_purchase_order(self, po_id: str) -> PurchaseOrder:
        with self._po_lock:
            po = self._purchase_orders.get(po_id)
            if po is None:
                raise NotFoundError(po_id)
            if po.status is not POStatus.OPEN:
                raise InvalidStateError(f"{po_id} is {po.status.value}")  # no double receipt
            po.status = POStatus.RECEIVED
        self.receive_stock(po.sku, po.warehouse_id, po.quantity, reference=po_id)
        return po

    def cancel_purchase_order(self, po_id: str) -> PurchaseOrder:
        with self._po_lock:
            po = self._purchase_orders.get(po_id)
            if po is None:
                raise NotFoundError(po_id)
            if po.status is not POStatus.OPEN:
                raise InvalidStateError(f"{po_id} is {po.status.value}")
            po.status = POStatus.CANCELLED
            return po

    # ---- queries -----------------------------------------------------------

    def stock(self, sku: str, warehouse_id: str) -> Tuple[int, int, int]:
        """(on_hand, reserved, available), read consistently under the item lock."""
        item = self._get_item(sku, warehouse_id)
        with item.lock:
            return item.on_hand, item.reserved, item.available

    def available(self, sku: str) -> int:
        """Total available across warehouses (each item read under its own lock)."""
        total = 0
        for item in self._items_for_skus([sku]):
            with item.lock:
                total += item.available
        return total

    def inventory_value(self) -> Decimal:
        total = Decimal("0")
        for item in self._all_items():
            with item.lock:
                total += item.product.unit_price * item.on_hand
        return total

    def movements(self, sku: Optional[str] = None) -> List[Movement]:
        with self._ledger_lock:
            return [m for m in self._ledger if sku is None or m.sku == sku]

    # ---- internals -----------------------------------------------------------

    def _plan(self, wanted: Mapping[str, int], items: Sequence[InventoryItem]) -> List[ReservationLine]:
        lines: List[ReservationLine] = []
        for sku, qty in sorted(wanted.items()):
            views = [StockView(i.warehouse.warehouse_id, i.warehouse.priority, i.available)
                     for i in items if i.product.sku == sku]
            plan = self._allocation.allocate(qty, views)
            if plan is None:
                raise InsufficientStockError(sku, qty, sum(v.available for v in views))
            lines.extend(ReservationLine(sku, wh, q) for wh, q in plan)
        return lines

    def _release_locked(self, res: Reservation, final: ReservationStatus) -> None:
        """Caller holds res.lock and has checked res is ACTIVE."""
        items = {l: self._get_item(l.sku, l.warehouse_id) for l in res.lines}
        with self._lock_all(list(items.values())):
            for line, item in items.items():
                item.release(line.quantity)
        res.status = final

    @staticmethod
    def _lock_all(items: Sequence[InventoryItem]) -> ExitStack:
        """Acquire item locks in a single global order (sorted, de-duplicated) to rule out deadlock."""
        stack = ExitStack()
        for item in sorted({i.key: i for i in items}.values(), key=lambda i: i.key):
            stack.enter_context(item.lock)
        return stack

    def _record(self, item: InventoryItem, mtype: MovementType, delta: int, reference: str) -> None:
        with self._ledger_lock:
            self._ledger.append(Movement(next(self._ids), item.product.sku, item.warehouse.warehouse_id,
                                         mtype, delta, item.on_hand, reference, self._clock()))

    def _avg_daily_demand(self, sku: str, warehouse_id: str) -> float:
        since = self._clock() - self._lookback_days * SECONDS_PER_DAY
        with self._ledger_lock:
            shipped = sum(-m.delta for m in self._ledger
                          if m.type is MovementType.SHIP and m.sku == sku
                          and m.warehouse_id == warehouse_id and m.at >= since)
        return shipped / self._lookback_days

    def _get_or_create_item(self, sku: str, warehouse_id: str) -> InventoryItem:
        with self._registry_lock:
            product = self._products.get(sku)
            warehouse = self._warehouses.get(warehouse_id)
            if product is None or warehouse is None:
                raise NotFoundError(f"unknown sku {sku!r} or warehouse {warehouse_id!r}")
            item = self._items.get((sku, warehouse_id))
            if item is None:
                item = self._items[(sku, warehouse_id)] = InventoryItem(product, warehouse)
            return item

    def _get_item(self, sku: str, warehouse_id: str) -> InventoryItem:
        with self._registry_lock:
            item = self._items.get((sku, warehouse_id))
        if item is None:
            raise NotFoundError(f"no stock record for {sku!r} at {warehouse_id!r}")
        return item

    def _items_for_skus(self, skus) -> List[InventoryItem]:
        skus = set(skus)
        with self._registry_lock:
            unknown = skus - self._products.keys()
            if unknown:
                raise NotFoundError(f"unknown sku(s) {sorted(unknown)}")
            return [i for k, i in self._items.items() if k[0] in skus]

    def _all_items(self) -> List[InventoryItem]:
        with self._registry_lock:
            return sorted(self._items.values(), key=lambda i: i.key)

    def _get_reservation(self, reservation_id: str) -> Reservation:
        with self._res_lock:
            res = self._reservations.get(reservation_id)
        if res is None:
            raise NotFoundError(reservation_id)
        return res


def _require_positive(qty: int) -> None:
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        raise ValueError(f"quantity must be a positive int, got {qty!r}")


class ManualClock:
    """Deterministic clock for the demo and tests."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------- demo

def demo() -> None:
    clock = ManualClock()
    inv = InventoryService(reservation_ttl_s=600, clock=clock)

    inv.add_product(Product("LAP-1", "Laptop", Decimal("1200.00"), reorder_level=5, reorder_quantity=20))
    inv.add_product(Product("PHN-1", "Phone", Decimal("799.99"), reorder_level=10, reorder_quantity=30))
    inv.add_warehouse(Warehouse("BLR", "Bangalore", priority=0))
    inv.add_warehouse(Warehouse("CCU", "Kolkata", priority=1))

    inv.receive_stock("LAP-1", "BLR", 8)
    inv.receive_stock("LAP-1", "CCU", 6)
    inv.receive_stock("PHN-1", "BLR", 40)
    print("Laptops available:", inv.available("LAP-1"))                      # 14

    # 1. Multi-line order, laptops split across warehouses because BLR alone has only 8.
    r1 = inv.reserve("order-1", {"LAP-1": 10, "PHN-1": 2})
    print("order-1 lines:", [(l.sku, l.warehouse_id, l.quantity) for l in r1.lines])
    assert inv.reserve("order-1", {"LAP-1": 10, "PHN-1": 2}) is r1          # idempotent retry

    # 2. All-or-nothing: not enough laptops left, nothing gets reserved.
    try:
        inv.reserve("order-2", {"PHN-1": 1, "LAP-1": 5})
    except InsufficientStockError as e:
        print("order-2 rejected:", e)
    assert inv.stock("PHN-1", "BLR") == (40, 2, 38)

    # 3. Commit order-1: on_hand drops, reservation consumed.
    inv.commit(r1.reservation_id)
    print("after commit LAP-1@BLR/CCU:", inv.stock("LAP-1", "BLR"), inv.stock("LAP-1", "CCU"))

    # 4. A reservation that is never paid for expires and gives its stock back.
    r3 = inv.reserve("order-3", {"PHN-1": 5})
    clock.advance(601)
    print("expired:", [r.order_id for r in inv.expire_reservations()], "->", inv.stock("PHN-1", "BLR"))

    # 5. Transfer, then reorder (open POs count toward position, so a second check adds nothing).
    inv.transfer_stock("PHN-1", "BLR", "CCU", 10)
    pos = inv.check_reorder()
    print("POs:", [(p.po_id, p.sku, p.warehouse_id, p.quantity) for p in pos])
    assert inv.check_reorder() == []
    for po in pos:
        inv.receive_purchase_order(po.po_id)

    print("inventory value:", inv.inventory_value())
    print("ledger:", len(inv.movements()), "movements;", r3.status.value)


if __name__ == "__main__":
    demo()
