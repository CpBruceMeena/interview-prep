# 🍔 Food Delivery — Implementation

> **Python 3.10+, stdlib only.** Run the demo with `python3 food_delivery.py`; run the tests with `python3 -m unittest test_food_delivery` from this directory.

---

## Map of the file

| Section | Key types | What to look at |
|---|---|---|
| Money & errors | `money()`, `FoodDeliveryError` subclasses | `money()` rejects `float`; one exception per failure the caller handles differently |
| State machine | `OrderStatus`, `Actor`, `TRANSITIONS`, `DISPATCHABLE` | Policy as a table: `(from, to) -> allowed actors` |
| Catalogue | `Location`, `MenuItem`, `Restaurant`, `Customer` | `MenuItem.available` models stock-outs |
| Cart | `Cart` | Single-restaurant rule; `replace_cart=True` is the "Start a new cart?" dialog |
| Pricing | `PricingRule` + 6 rules, `PricingEngine`, `PriceBreakdown`, `Coupon` | Ordered chain; each rule appends a line |
| Order | `Order`, `OrderEvent`, `OrderLine` | `transition()` and `attach_partner()` are the only mutators, both under the order's lock |
| Dispatch | `DeliveryPartner`, `PartnerSnapshot`, `AssignmentStrategy`, `NearestAvailableStrategy`, `BatchingStrategy`, `DispatchService` | Rank from snapshots, claim with CAS |
| Ports | `PaymentGateway`, `FakePaymentGateway` | Fake dedups on idempotency key like a real PSP |
| Observers | `OrderObserver`, `NotificationObserver` | Template per status, recipient resolved from the event |
| Facade | `OrderService` | Orchestration, idempotency, side effects after transitions |

---

## Key design decisions

### 1. The transition table is the policy

```python
TRANSITIONS = {
    (PLACED, ACCEPTED):      {RESTAURANT},
    (PLACED, REJECTED):      {RESTAURANT, SYSTEM},
    ...
    (PLACED, CANCELLED):     {CUSTOMER, SYSTEM},
    (ACCEPTED, CANCELLED):   {CUSTOMER, RESTAURANT, SYSTEM},
    (PREPARING, CANCELLED):  {RESTAURANT, SYSTEM},
    (PICKED_UP, CANCELLED):  {SYSTEM},
}
```

`Order.transition(new, actor, actor_id)` checks, under `self._lock`: the edge exists (`InvalidTransitionError`), the actor is allowed (`NotAuthorizedError`), and for `PARTNER` that `actor_id` is the assigned partner. On `CANCELLED`/`REJECTED` it detaches the partner in the same critical section and returns them, so the caller can release them. Changing who may cancel is a one-line data change, reviewable by product.

### 2. Idempotent `place_order` without a global critical section

`OrderService._idem` maps `(customer_id, key)` to an `_IdempotencySlot` (`fingerprint`, `threading.Event`, `order`, `error`). The service lock is held only to look up or insert the slot; pricing and the payment call happen outside it. Waiters block on `slot.done`. On failure the slot is deleted so the client can retry with the same key; on success it stays (in production it would carry a TTL, typically 24 h).

The payment is charged with `f"{customer_id}:{key}"` as *its* idempotency key, so the PSP also dedups.

### 3. Pricing as an ordered chain

```python
PricingEngine.default() = [ItemSubtotalRule(), PackagingFeeRule(), DeliveryFeeRule(),
                           SurgeRule(), CouponRule(), TaxRule()]
```

Each rule reads the `PricingContext` and the lines added so far (`bill.amount_of("DELIVERY")`) and appends its own. Dependencies between rules are therefore positional and visible in one list. `DeliveryFeeRule` charges every *started* km beyond `free_km` (`ROUND_CEILING`); `SurgeRule` scales only the delivery fee; `Coupon.discount_for` caps at `max_discount` and at the food subtotal; `TaxRule` taxes food after discount. Each amount is quantised when added, and the total is the sum of quantised lines, floored at zero.

To extend: a `SmallOrderFeeRule`, a `MembershipFreeDeliveryRule` (adds a negative `DELIVERY` line) or a restaurant-funded discount are new classes inserted at the right position. No existing rule changes.

### 4. Dispatch: rank, then claim

```python
snapshots = [p.snapshot() for p in partners]          # each under the partner's lock
for pid in strategy.rank(order, restaurant, snapshots):
    if not partner.try_claim(order_id, restaurant_id, strategy.max_orders_per_partner):
        continue                                     # lost the race, try the next
    if order.attach_partner(pid):
        return partner
    partner.release(order_id)                        # order cancelled meanwhile
    return None
```

- Strategies are pure ranking functions over immutable `PartnerSnapshot`s, trivially testable.
- `try_claim` is the compare-and-set. It re-checks online, capacity, same restaurant for a batch, and that the batch hasn't left the restaurant (`_picked_up`).
- `attach_partner` closes the cancel-vs-dispatch race: it only succeeds while the order is in `DISPATCHABLE` and unassigned. Either the cancel runs first (attach fails, claim is released) or the attach runs first (cancel sees the partner and releases it). Locks are never nested (partner lock and order lock are taken one after another), so there is no lock-ordering deadlock.
- `BatchingStrategy` puts partners already assigned to the same restaurant (with spare capacity, not yet picked up) first, then falls back to nearest idle. `max_orders_per_partner` flows into the claim, so capacity is enforced at the CAS, not just in the ranking.

### 5. Side effects after the lock

`_move()` runs the transition, then, outside the order lock: releases a detached partner, refunds on `CANCELLED`/`REJECTED`, and publishes the event. Holding a lock across a PSP call or a notification fan-out would turn a slow dependency into lock contention. Ordering is preserved for consumers through `OrderEvent.seq`.

### 6. Price snapshot

`OrderLine` copies `name` and `unit_price` at placement. A restaurant changing its menu price five minutes later must not change an order that is already paid.

---

## Where to extend

| Requirement | Change |
|---|---|
| Auto-reject if the restaurant doesn't accept in 3 min | A scheduler calls `reject(order_id, Actor.SYSTEM)`; it simply loses if the restaurant already accepted (`InvalidTransitionError`) |
| Partner goes offline before pickup | `unassign(order_id, partner_id)`: under the order lock clear `partner_id` if it matches and status < `PICKED_UP`; release the partner; call `dispatch()` |
| Scored assignment (ETA, rating, acceptance rate) | New `AssignmentStrategy.rank`; the claim logic is unchanged |
| Partner must accept the offer | Claim becomes a time-boxed *offer*; on decline/timeout release and try the next ranked partner |
| Cancellation fee after `ACCEPTED` | A `RefundPolicy` strategy computing the refund from `(status_at_cancel, actor)` |
| COD | `PaymentGateway` implementation that records a receivable instead of charging |
| Coupon usage limits | Coupon redemption becomes a conditional increment (`uses < limit`) inside the same idempotent placement |

---

## Tests

`test_food_delivery.py` (28 tests, < 0.1 s) covers: the cart rule; exact pricing including partial-km delivery, surge, coupon cap/min/over-discount; idempotent retry, key conflict, retry after payment failure and **16 concurrent duplicate submissions → one order, one charge**; full happy path; illegal jumps; wrong-partner pickup; per-actor cancel rules with refund and partner release; **concurrent cancel vs start-preparing → exactly one wins**; a deterministic cancel-between-rank-and-claim test; nearest/offline/radius dispatch; **20 concurrent accepts over 5 partners → 5 distinct assignments**; batching up to capacity and closing at pickup; observer ordering and failure isolation.

---

## Full source

<!-- source: food_delivery.py -->
```python
"""
Food Delivery (Swiggy / Zomato / DoorDash) — Low-Level Design
==============================================================

Scope (what an LLD round expects in 60-90 minutes):
  * Restaurants with menus; a cart that can only hold items from ONE restaurant.
  * Order placement that is idempotent on a client-supplied key (a retried
    "Place order" tap must never create two orders or two charges).
  * An explicit order state machine with per-actor rules:
        PLACED -> ACCEPTED -> PREPARING -> READY -> PICKED_UP -> DELIVERED
        PLACED -> REJECTED                      (restaurant / system timeout)
        * -> CANCELLED                          (who may cancel depends on state)
  * Delivery-partner assignment as a Strategy (nearest available; batching as
    an extension) that can never double-assign a partner under concurrency.
  * Decimal pricing built by an ordered chain of rules (fees, surge, coupon, tax).
  * Observer for status notifications.

Patterns: Strategy (assignment), Chain/pipeline (pricing rules), State machine
(transition table), Observer (status events), Facade (OrderService).

Concurrency model:
  * Each Order has its own lock; every transition is check-and-set under it.
  * Each DeliveryPartner has its own lock; claiming is a compare-and-set
    (`try_claim`). Strategies only RANK candidates from a snapshot; the claim
    re-validates, so a stale snapshot can cost a retry but never a double-assign.
  * Idempotency uses an in-flight slot per key, so concurrent duplicates wait for
    the first attempt instead of serialising all order placement behind one lock.
  * Observers are notified AFTER the order lock is released; every event carries
    a per-order sequence number so consumers can drop out-of-order deliveries.

Python 3.10+, stdlib only.
"""

from __future__ import annotations

import itertools
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Iterable, Optional, Sequence

PAISE = Decimal("0.01")


def money(value: Decimal | int | str) -> Decimal:
    """Normalise to 2 dp with half-up rounding. Never construct money from float."""
    if isinstance(value, float):
        raise TypeError("money must not be built from float; pass str/int/Decimal")
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


# ─── Errors ──────────────────────────────────────────────────────────────────

class FoodDeliveryError(Exception):
    """Base class for domain errors."""


class CartError(FoodDeliveryError):
    pass


class DifferentRestaurantError(CartError):
    """Raised when adding an item from a second restaurant to a non-empty cart."""


class ItemUnavailableError(FoodDeliveryError):
    pass


class RestaurantClosedError(FoodDeliveryError):
    pass


class InvalidCouponError(FoodDeliveryError):
    pass


class PaymentFailedError(FoodDeliveryError):
    pass


class IdempotencyConflictError(FoodDeliveryError):
    """Same idempotency key reused with a different request body."""


class InvalidTransitionError(FoodDeliveryError):
    pass


class NotAuthorizedError(FoodDeliveryError):
    pass


class OrderNotFoundError(FoodDeliveryError):
    pass


# ─── Enums ───────────────────────────────────────────────────────────────────

class OrderStatus(Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


class Actor(Enum):
    CUSTOMER = "CUSTOMER"
    RESTAURANT = "RESTAURANT"
    PARTNER = "PARTNER"
    SYSTEM = "SYSTEM"  # timeouts, support agents, ops tooling


class CouponType(Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


# Who may move an order from one state to another. Anything not listed is illegal.
# Cancellation rules encode the business policy:
#   - customer: only before food is being made (PLACED, ACCEPTED)
#   - restaurant: after accepting but before handing over (e.g. ran out of stock)
#   - partner: never cancels an order; they drop it and it is re-dispatched
#   - system/support: any non-terminal state, including after pickup (lost food)
_S, _A = OrderStatus, Actor
TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], frozenset[Actor]] = {
    (_S.PLACED, _S.ACCEPTED): frozenset({_A.RESTAURANT}),
    (_S.PLACED, _S.REJECTED): frozenset({_A.RESTAURANT, _A.SYSTEM}),
    (_S.ACCEPTED, _S.PREPARING): frozenset({_A.RESTAURANT}),
    (_S.PREPARING, _S.READY): frozenset({_A.RESTAURANT}),
    (_S.READY, _S.PICKED_UP): frozenset({_A.PARTNER}),
    (_S.PICKED_UP, _S.DELIVERED): frozenset({_A.PARTNER}),
    (_S.PLACED, _S.CANCELLED): frozenset({_A.CUSTOMER, _A.SYSTEM}),
    (_S.ACCEPTED, _S.CANCELLED): frozenset({_A.CUSTOMER, _A.RESTAURANT, _A.SYSTEM}),
    (_S.PREPARING, _S.CANCELLED): frozenset({_A.RESTAURANT, _A.SYSTEM}),
    (_S.READY, _S.CANCELLED): frozenset({_A.RESTAURANT, _A.SYSTEM}),
    (_S.PICKED_UP, _S.CANCELLED): frozenset({_A.SYSTEM}),
}

# States in which a delivery partner may be attached to the order.
DISPATCHABLE = frozenset({OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.READY})


# ─── Value objects & catalogue ───────────────────────────────────────────────

@dataclass(frozen=True)
class Location:
    lat: float
    lng: float

    def distance_km(self, other: Location) -> float:
        """Great-circle (haversine) distance. Road distance would come from a routing service."""
        r = 6371.0
        p1, p2 = math.radians(self.lat), math.radians(other.lat)
        dp = p2 - p1
        dl = math.radians(other.lng - self.lng)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))


@dataclass
class MenuItem:
    item_id: str
    name: str
    price: Decimal
    available: bool = True

    def __post_init__(self) -> None:
        self.price = money(self.price)
        if self.price <= 0:
            raise ValueError("price must be positive")


class Restaurant:
    def __init__(self, restaurant_id: str, name: str, location: Location,
                 packaging_fee: Decimal | str = "0", is_open: bool = True) -> None:
        self.restaurant_id = restaurant_id
        self.name = name
        self.location = location
        self.packaging_fee = money(packaging_fee)
        self.is_open = is_open
        self._menu: dict[str, MenuItem] = {}

    def add_item(self, item: MenuItem) -> None:
        self._menu[item.item_id] = item

    def item(self, item_id: str) -> MenuItem:
        try:
            return self._menu[item_id]
        except KeyError:
            raise ItemUnavailableError(f"{item_id} is not on {self.name}'s menu") from None

    def set_availability(self, item_id: str, available: bool) -> None:
        self.item(item_id).available = available


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    location: Location


# ─── Cart ────────────────────────────────────────────────────────────────────

class Cart:
    """Client-side-ish draft of an order. One restaurant per cart (the classic rule)."""

    def __init__(self, customer: Customer) -> None:
        self.customer = customer
        self._restaurant: Optional[Restaurant] = None
        self._quantities: dict[str, int] = {}

    @property
    def restaurant(self) -> Optional[Restaurant]:
        return self._restaurant

    @property
    def quantities(self) -> dict[str, int]:
        return dict(self._quantities)

    def add(self, restaurant: Restaurant, item_id: str, qty: int = 1,
            *, replace_cart: bool = False) -> None:
        if qty <= 0:
            raise CartError("quantity must be positive")
        if self._restaurant is not None and self._restaurant is not restaurant:
            if not replace_cart:
                raise DifferentRestaurantError(
                    f"cart holds items from {self._restaurant.name}; "
                    f"clear it or pass replace_cart=True")
            self.clear()
        restaurant.item(item_id)  # validates the item exists
        self._restaurant = restaurant
        self._quantities[item_id] = self._quantities.get(item_id, 0) + qty

    def remove(self, item_id: str, qty: int = 1) -> None:
        current = self._quantities.get(item_id, 0)
        if current == 0:
            raise CartError(f"{item_id} not in cart")
        if qty >= current:
            del self._quantities[item_id]
        else:
            self._quantities[item_id] = current - qty
        if not self._quantities:
            self._restaurant = None

    def clear(self) -> None:
        self._restaurant = None
        self._quantities.clear()

    @property
    def is_empty(self) -> bool:
        return not self._quantities


# ─── Pricing: an ordered chain of rules ──────────────────────────────────────

@dataclass(frozen=True)
class OrderLine:
    """Snapshot of a menu item at order time; later menu price changes don't touch it."""
    item_id: str
    name: str
    unit_price: Decimal
    qty: int

    @property
    def amount(self) -> Decimal:
        return money(self.unit_price * self.qty)


@dataclass(frozen=True)
class Coupon:
    code: str
    kind: CouponType
    value: Decimal                 # percent (e.g. 20) or flat amount
    min_subtotal: Decimal = Decimal("0")
    max_discount: Optional[Decimal] = None

    def discount_for(self, subtotal: Decimal) -> Decimal:
        if subtotal < self.min_subtotal:
            raise InvalidCouponError(
                f"{self.code} needs a subtotal of at least {self.min_subtotal}")
        if self.kind is CouponType.PERCENT:
            raw = subtotal * self.value / Decimal(100)
        else:
            raw = self.value
        if self.max_discount is not None:
            raw = min(raw, self.max_discount)
        return money(min(raw, subtotal))  # never discount more than the food costs


@dataclass(frozen=True)
class PricingContext:
    restaurant: Restaurant
    customer: Customer
    lines: tuple[OrderLine, ...]
    coupon: Optional[Coupon] = None
    surge_multiplier: Decimal = Decimal("1")

    @property
    def subtotal(self) -> Decimal:
        return money(sum((line.amount for line in self.lines), Decimal("0")))

    @property
    def distance_km(self) -> Decimal:
        km = self.restaurant.location.distance_km(self.customer.location)
        return Decimal(str(round(km, 2)))


@dataclass(frozen=True)
class PriceLine:
    code: str
    amount: Decimal  # negative for discounts


@dataclass
class PriceBreakdown:
    lines: list[PriceLine] = field(default_factory=list)

    def add(self, code: str, amount: Decimal) -> None:
        amount = money(amount)
        if amount != 0:
            self.lines.append(PriceLine(code, amount))

    def amount_of(self, code: str) -> Decimal:
        return sum((l.amount for l in self.lines if l.code == code), Decimal("0.00"))

    @property
    def total(self) -> Decimal:
        return money(max(sum((l.amount for l in self.lines), Decimal("0")), Decimal("0")))


class PricingRule(ABC):
    """One step in the price chain. Rules run in order and may read earlier lines."""

    @abstractmethod
    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None: ...


class ItemSubtotalRule(PricingRule):
    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        bill.add("ITEMS", ctx.subtotal)


class PackagingFeeRule(PricingRule):
    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        bill.add("PACKAGING", ctx.restaurant.packaging_fee)


class DeliveryFeeRule(PricingRule):
    """Base fee covers the first `free_km`; each extra km (or part of one) costs `per_km`."""

    def __init__(self, base: str = "25", per_km: str = "8", free_km: int = 2) -> None:
        self.base, self.per_km, self.free_km = money(base), money(per_km), free_km

    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        extra_km = max(Decimal(0), ctx.distance_km - self.free_km)
        billable_km = extra_km.to_integral_value(rounding=ROUND_CEILING)
        bill.add("DELIVERY", self.base + self.per_km * billable_km)


class SurgeRule(PricingRule):
    """Surge scales the delivery fee only, never food. Must run after DeliveryFeeRule."""

    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        if ctx.surge_multiplier > 1:
            bill.add("SURGE", bill.amount_of("DELIVERY") * (ctx.surge_multiplier - 1))


class CouponRule(PricingRule):
    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        if ctx.coupon is not None:
            bill.add("COUPON", -ctx.coupon.discount_for(bill.amount_of("ITEMS")))


class TaxRule(PricingRule):
    """Tax on food after discount (fees are taxed separately in reality; kept simple)."""

    def __init__(self, rate_percent: str = "5") -> None:
        self.rate = Decimal(rate_percent) / Decimal(100)

    def apply(self, ctx: PricingContext, bill: PriceBreakdown) -> None:
        taxable = bill.amount_of("ITEMS") + bill.amount_of("COUPON")
        bill.add("TAX", max(taxable, Decimal(0)) * self.rate)


class PricingEngine:
    def __init__(self, rules: Sequence[PricingRule]) -> None:
        self._rules = list(rules)

    @classmethod
    def default(cls) -> PricingEngine:
        return cls([ItemSubtotalRule(), PackagingFeeRule(), DeliveryFeeRule(),
                    SurgeRule(), CouponRule(), TaxRule()])

    def price(self, ctx: PricingContext) -> PriceBreakdown:
        bill = PriceBreakdown()
        for rule in self._rules:
            rule.apply(ctx, bill)
        return bill


# ─── Order + state machine ───────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderEvent:
    order_id: str
    seq: int                       # per-order, monotonically increasing
    old_status: Optional[OrderStatus]
    new_status: OrderStatus
    actor: Actor
    customer_id: str
    restaurant_id: str
    partner_id: Optional[str]


class Order:
    def __init__(self, order_id: str, customer_id: str, restaurant_id: str,
                 lines: tuple[OrderLine, ...], bill: PriceBreakdown, payment_id: str) -> None:
        self.order_id = order_id
        self.customer_id = customer_id
        self.restaurant_id = restaurant_id
        self.lines = lines
        self.bill = bill
        self.payment_id = payment_id
        self._status = OrderStatus.PLACED
        self._partner_id: Optional[str] = None
        self._seq = 0
        self._history: list[tuple[OrderStatus, Actor]] = [(OrderStatus.PLACED, Actor.CUSTOMER)]
        self._lock = threading.Lock()

    @property
    def status(self) -> OrderStatus:
        return self._status

    @property
    def partner_id(self) -> Optional[str]:
        return self._partner_id

    @property
    def total(self) -> Decimal:
        return self.bill.total

    @property
    def history(self) -> list[tuple[OrderStatus, Actor]]:
        with self._lock:
            return list(self._history)

    def placed_event(self) -> OrderEvent:
        return OrderEvent(self.order_id, 0, None, OrderStatus.PLACED, Actor.CUSTOMER,
                          self.customer_id, self.restaurant_id, None)

    def transition(self, new: OrderStatus, actor: Actor,
                   actor_id: Optional[str] = None) -> tuple[OrderEvent, Optional[str]]:
        """Atomic check-and-set. Returns the event and, on cancellation, the partner
        that was holding the order (so the caller can release them)."""
        with self._lock:
            old = self._status
            allowed = TRANSITIONS.get((old, new))
            if allowed is None:
                raise InvalidTransitionError(f"{self.order_id}: {old.value} -> {new.value}")
            if actor not in allowed:
                raise NotAuthorizedError(
                    f"{actor.value} may not move {self.order_id} {old.value} -> {new.value}")
            if actor is Actor.PARTNER and actor_id != self._partner_id:
                raise NotAuthorizedError(f"partner {actor_id} is not assigned to {self.order_id}")
            released = None
            if new.is_terminal and new is not OrderStatus.DELIVERED:
                released, self._partner_id = self._partner_id, None
            self._status = new
            self._seq += 1
            self._history.append((new, actor))
            event = OrderEvent(self.order_id, self._seq, old, new, actor,
                               self.customer_id, self.restaurant_id,
                               self._partner_id if released is None else released)
            return event, released

    def attach_partner(self, partner_id: str) -> bool:
        """Attach only if still dispatchable and unassigned; guards the cancel/assign race."""
        with self._lock:
            if self._status not in DISPATCHABLE or self._partner_id is not None:
                return False
            self._partner_id = partner_id
            return True


# ─── Delivery partners & assignment strategy ─────────────────────────────────

@dataclass(frozen=True)
class PartnerSnapshot:
    partner_id: str
    location: Location
    online: bool
    active_restaurants: tuple[str, ...]  # one entry per active order
    picked_up: bool

    @property
    def is_idle(self) -> bool:
        return self.online and not self.active_restaurants


class DeliveryPartner:
    """Holds its own lock; `try_claim` is the only way to take on an order."""

    def __init__(self, partner_id: str, name: str, location: Location) -> None:
        self.partner_id = partner_id
        self.name = name
        self._location = location
        self._online = True
        self._active: dict[str, str] = {}  # order_id -> restaurant_id
        self._picked_up = False            # once out of the restaurant, the batch is closed
        self._lock = threading.Lock()

    def snapshot(self) -> PartnerSnapshot:
        with self._lock:
            return PartnerSnapshot(self.partner_id, self._location, self._online,
                                   tuple(self._active.values()), self._picked_up)

    def update_location(self, location: Location) -> None:
        with self._lock:
            self._location = location

    def set_online(self, online: bool) -> None:
        with self._lock:
            self._online = online

    def try_claim(self, order_id: str, restaurant_id: str, max_orders: int) -> bool:
        """Compare-and-set: re-checks everything the strategy saw in its snapshot."""
        with self._lock:
            if not self._online or order_id in self._active:
                return False
            if self._active:
                if (len(self._active) >= max_orders or self._picked_up
                        or any(r != restaurant_id for r in self._active.values())):
                    return False
            self._active[order_id] = restaurant_id
            return True

    def mark_picked_up(self, order_id: str) -> None:
        with self._lock:
            if order_id in self._active:
                self._picked_up = True

    def release(self, order_id: str) -> None:
        with self._lock:
            self._active.pop(order_id, None)
            if not self._active:
                self._picked_up = False

    @property
    def active_orders(self) -> list[str]:
        with self._lock:
            return list(self._active)


class AssignmentStrategy(ABC):
    """Ranks candidates; it never mutates partners. The dispatcher does the claim."""

    max_orders_per_partner: int = 1

    @abstractmethod
    def rank(self, order: Order, restaurant: Restaurant,
             partners: Sequence[PartnerSnapshot]) -> list[str]: ...


class NearestAvailableStrategy(AssignmentStrategy):
    def __init__(self, radius_km: float = 5.0) -> None:
        self.radius_km = radius_km

    def rank(self, order: Order, restaurant: Restaurant,
             partners: Sequence[PartnerSnapshot]) -> list[str]:
        scored = []
        for p in partners:
            if not p.is_idle:
                continue
            d = p.location.distance_km(restaurant.location)
            if d <= self.radius_km:
                scored.append((d, p.partner_id))
        return [pid for _, pid in sorted(scored)]


class BatchingStrategy(AssignmentStrategy):
    """Prefer a partner already heading to the same restaurant (not yet picked up)
    with spare capacity; otherwise fall back to the nearest idle partner."""

    def __init__(self, max_orders: int = 2, radius_km: float = 5.0) -> None:
        self.max_orders_per_partner = max_orders
        self._fallback = NearestAvailableStrategy(radius_km)

    def rank(self, order: Order, restaurant: Restaurant,
             partners: Sequence[PartnerSnapshot]) -> list[str]:
        rid = restaurant.restaurant_id
        batchable = sorted(
            (p.location.distance_km(restaurant.location), p.partner_id)
            for p in partners
            if p.online and p.active_restaurants and not p.picked_up
            and len(p.active_restaurants) < self.max_orders_per_partner
            and all(r == rid for r in p.active_restaurants)
        )
        return [pid for _, pid in batchable] + self._fallback.rank(order, restaurant, partners)


class DispatchService:
    def __init__(self, strategy: AssignmentStrategy) -> None:
        self.strategy = strategy
        self._partners: dict[str, DeliveryPartner] = {}
        self._registry_lock = threading.Lock()

    def register(self, partner: DeliveryPartner) -> None:
        with self._registry_lock:
            self._partners[partner.partner_id] = partner

    def partner(self, partner_id: str) -> DeliveryPartner:
        return self._partners[partner_id]

    def assign(self, order: Order, restaurant: Restaurant) -> Optional[DeliveryPartner]:
        with self._registry_lock:
            partners = list(self._partners.values())
        snapshots = [p.snapshot() for p in partners]
        for pid in self.strategy.rank(order, restaurant, snapshots):
            partner = self._partners[pid]
            if not partner.try_claim(order.order_id, restaurant.restaurant_id,
                                     self.strategy.max_orders_per_partner):
                continue  # lost the race for this partner; try the next one
            if order.attach_partner(pid):
                return partner
            partner.release(order.order_id)  # order was cancelled / already assigned
            return None
        return None


# ─── Payments (port) ─────────────────────────────────────────────────────────

class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, customer_id: str, amount: Decimal, idempotency_key: str) -> str: ...

    @abstractmethod
    def refund(self, payment_id: str, amount: Decimal) -> None: ...


class FakePaymentGateway(PaymentGateway):
    """Dedups on idempotency key, as real PSPs (Stripe, Razorpay) do."""

    def __init__(self, fail_customers: Iterable[str] = ()) -> None:
        self._fail = set(fail_customers)
        self._by_key: dict[str, str] = {}
        self.charges: dict[str, Decimal] = {}
        self.refunds: dict[str, Decimal] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def charge(self, customer_id: str, amount: Decimal, idempotency_key: str) -> str:
        with self._lock:
            if customer_id in self._fail:
                raise PaymentFailedError(f"card declined for {customer_id}")
            if idempotency_key in self._by_key:
                return self._by_key[idempotency_key]
            pid = f"pay-{next(self._ids)}"
            self._by_key[idempotency_key] = pid
            self.charges[pid] = amount
            return pid

    def refund(self, payment_id: str, amount: Decimal) -> None:
        with self._lock:
            self.refunds.setdefault(payment_id, amount)  # idempotent per payment


# ─── Observers ───────────────────────────────────────────────────────────────

class OrderObserver(ABC):
    @abstractmethod
    def on_order_event(self, event: OrderEvent) -> None: ...


class NotificationObserver(OrderObserver):
    """Turns status changes into user-facing messages. In production this publishes
    to a notification service; here it records (recipient, text)."""

    TEMPLATES = {
        OrderStatus.PLACED: ("customer", "Order {id} placed"),
        OrderStatus.ACCEPTED: ("customer", "Restaurant accepted order {id}"),
        OrderStatus.READY: ("partner", "Order {id} is ready for pickup"),
        OrderStatus.PICKED_UP: ("customer", "Order {id} is on the way"),
        OrderStatus.DELIVERED: ("customer", "Order {id} delivered. Enjoy!"),
        OrderStatus.CANCELLED: ("customer", "Order {id} was cancelled; refund initiated"),
        OrderStatus.REJECTED: ("customer", "Restaurant could not take order {id}; refund initiated"),
    }

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def on_order_event(self, event: OrderEvent) -> None:
        template = self.TEMPLATES.get(event.new_status)
        if template is None:
            return
        who, text = template
        recipient = event.customer_id if who == "customer" else event.partner_id
        if recipient is None:
            return
        with self._lock:
            self.sent.append((recipient, text.format(id=event.order_id)))


# ─── Facade ──────────────────────────────────────────────────────────────────

@dataclass
class _IdempotencySlot:
    fingerprint: tuple
    done: threading.Event = field(default_factory=threading.Event)
    order: Optional[Order] = None
    error: Optional[BaseException] = None


class OrderService:
    def __init__(self, dispatch: DispatchService, payments: PaymentGateway,
                 pricing: Optional[PricingEngine] = None) -> None:
        self._dispatch = dispatch
        self._payments = payments
        self._pricing = pricing or PricingEngine.default()
        self._restaurants: dict[str, Restaurant] = {}
        self._coupons: dict[str, Coupon] = {}
        self._orders: dict[str, Order] = {}
        self._observers: list[OrderObserver] = []
        self._idem: dict[tuple[str, str], _IdempotencySlot] = {}
        self._lock = threading.Lock()  # guards the dicts above, never held during I/O
        self._order_ids = itertools.count(1)
        self.surge_multiplier = Decimal("1")

    # -- registration --------------------------------------------------------
    def add_restaurant(self, restaurant: Restaurant) -> None:
        self._restaurants[restaurant.restaurant_id] = restaurant

    def add_coupon(self, coupon: Coupon) -> None:
        self._coupons[coupon.code] = coupon

    def subscribe(self, observer: OrderObserver) -> None:
        self._observers.append(observer)

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError:
            raise OrderNotFoundError(order_id) from None

    # -- quoting & placement -------------------------------------------------
    def quote(self, cart: Cart, coupon_code: Optional[str] = None) -> PriceBreakdown:
        return self._pricing.price(self._pricing_context(cart, coupon_code))

    def place_order(self, cart: Cart, idempotency_key: str,
                    coupon_code: Optional[str] = None) -> Order:
        """Idempotent on (customer, key). A retry with the same body returns the same
        order; a different body under the same key is rejected."""
        if cart.is_empty or cart.restaurant is None:
            raise CartError("cart is empty")
        key = (cart.customer.customer_id, idempotency_key)
        fingerprint = (cart.restaurant.restaurant_id,
                       tuple(sorted(cart.quantities.items())), coupon_code)

        with self._lock:
            slot = self._idem.get(key)
            owner = slot is None
            if owner:
                slot = self._idem[key] = _IdempotencySlot(fingerprint)
        if slot.fingerprint != fingerprint:
            raise IdempotencyConflictError(f"key {idempotency_key} reused with a different cart")
        if not owner:
            slot.done.wait()
            if slot.order is None:
                raise slot.error  # type: ignore[misc]
            return slot.order

        try:
            order = self._create_order(cart, coupon_code, idempotency_key)
        except BaseException as exc:
            slot.error = exc
            with self._lock:
                del self._idem[key]  # failed attempts are retryable with the same key
            slot.done.set()
            raise
        slot.order = order
        slot.done.set()
        self._publish(order.placed_event())
        return order

    def _pricing_context(self, cart: Cart, coupon_code: Optional[str]) -> PricingContext:
        restaurant = cart.restaurant
        assert restaurant is not None
        lines = []
        for item_id, qty in sorted(cart.quantities.items()):
            item = restaurant.item(item_id)
            if not item.available:
                raise ItemUnavailableError(f"{item.name} is out of stock")
            lines.append(OrderLine(item.item_id, item.name, item.price, qty))
        coupon = None
        if coupon_code is not None:
            coupon = self._coupons.get(coupon_code)
            if coupon is None:
                raise InvalidCouponError(f"unknown coupon {coupon_code}")
        return PricingContext(restaurant, cart.customer, tuple(lines), coupon,
                              self.surge_multiplier)

    def _create_order(self, cart: Cart, coupon_code: Optional[str], idem_key: str) -> Order:
        restaurant = cart.restaurant
        assert restaurant is not None
        if not restaurant.is_open:
            raise RestaurantClosedError(restaurant.name)
        ctx = self._pricing_context(cart, coupon_code)
        bill = self._pricing.price(ctx)
        customer_id = cart.customer.customer_id
        payment_id = self._payments.charge(customer_id, bill.total, f"{customer_id}:{idem_key}")
        with self._lock:
            order_id = f"ORD-{next(self._order_ids):04d}"
            order = Order(order_id, customer_id, restaurant.restaurant_id,
                          ctx.lines, bill, payment_id)
            self._orders[order_id] = order
        return order

    # -- restaurant actions --------------------------------------------------
    def accept(self, order_id: str) -> Optional[DeliveryPartner]:
        """Accepting triggers dispatch so the partner travels while food is cooked."""
        self._move(order_id, OrderStatus.ACCEPTED, Actor.RESTAURANT)
        return self.dispatch(order_id)

    def reject(self, order_id: str, actor: Actor = Actor.RESTAURANT) -> None:
        self._move(order_id, OrderStatus.REJECTED, actor)

    def start_preparing(self, order_id: str) -> None:
        self._move(order_id, OrderStatus.PREPARING, Actor.RESTAURANT)

    def mark_ready(self, order_id: str) -> None:
        self._move(order_id, OrderStatus.READY, Actor.RESTAURANT)

    # -- partner actions -----------------------------------------------------
    def pick_up(self, order_id: str, partner_id: str) -> None:
        self._move(order_id, OrderStatus.PICKED_UP, Actor.PARTNER, partner_id)
        self._dispatch.partner(partner_id).mark_picked_up(order_id)

    def deliver(self, order_id: str, partner_id: str) -> None:
        self._move(order_id, OrderStatus.DELIVERED, Actor.PARTNER, partner_id)
        self._dispatch.partner(partner_id).release(order_id)

    # -- cancellation & dispatch --------------------------------------------
    def cancel(self, order_id: str, actor: Actor) -> None:
        self._move(order_id, OrderStatus.CANCELLED, actor)

    def dispatch(self, order_id: str) -> Optional[DeliveryPartner]:
        """Safe to call repeatedly (e.g. a retry loop while no partner is free)."""
        order = self.get(order_id)
        if order.partner_id is not None or order.status not in DISPATCHABLE:
            return None
        return self._dispatch.assign(order, self._restaurants[order.restaurant_id])

    def _move(self, order_id: str, new: OrderStatus, actor: Actor,
              actor_id: Optional[str] = None) -> None:
        order = self.get(order_id)
        event, released_partner = order.transition(new, actor, actor_id)
        # Side effects run after the order lock is released.
        if released_partner is not None:
            self._dispatch.partner(released_partner).release(order_id)
        if new in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            self._payments.refund(order.payment_id, order.total)
        self._publish(event)

    def _publish(self, event: OrderEvent) -> None:
        for observer in list(self._observers):
            try:
                observer.on_order_event(event)
            except Exception:  # one broken observer must not fail the order flow
                pass


# ─── Demo ────────────────────────────────────────────────────────────────────

def build_demo() -> tuple[OrderService, DispatchService, FakePaymentGateway,
                          NotificationObserver, Restaurant, Customer]:
    restaurant = Restaurant("R1", "Biryani House", Location(12.9716, 77.5946), packaging_fee="15")
    restaurant.add_item(MenuItem("I1", "Chicken Biryani", Decimal("249.00")))
    restaurant.add_item(MenuItem("I2", "Raita", Decimal("39.50")))
    customer = Customer("C1", "Asha", Location(12.9900, 77.5946))  # ~2.05 km north

    dispatch = DispatchService(NearestAvailableStrategy(radius_km=5))
    dispatch.register(DeliveryPartner("P1", "Ravi", Location(12.9800, 77.5946)))
    dispatch.register(DeliveryPartner("P2", "Meera", Location(12.9720, 77.5950)))

    payments = FakePaymentGateway()
    service = OrderService(dispatch, payments)
    service.add_restaurant(restaurant)
    service.add_coupon(Coupon("SAVE20", CouponType.PERCENT, Decimal("20"),
                              min_subtotal=Decimal("300"), max_discount=Decimal("100")))
    notifier = NotificationObserver()
    service.subscribe(notifier)
    return service, dispatch, payments, notifier, restaurant, customer


def main() -> None:
    service, dispatch, payments, notifier, restaurant, customer = build_demo()

    cart = Cart(customer)
    cart.add(restaurant, "I1", 2)
    cart.add(restaurant, "I2", 1)

    print("Quote:")
    for line in service.quote(cart, "SAVE20").lines:
        print(f"  {line.code:<10} {line.amount:>8}")

    order = service.place_order(cart, idempotency_key="tap-1", coupon_code="SAVE20")
    retry = service.place_order(cart, idempotency_key="tap-1", coupon_code="SAVE20")
    assert retry is order and len(payments.charges) == 1
    print(f"\nPlaced {order.order_id}, total {order.total} (retry returned same order)")

    partner = service.accept(order.order_id)
    assert partner is not None
    print(f"Assigned partner {partner.partner_id} (nearest to restaurant)")
    service.start_preparing(order.order_id)
    service.mark_ready(order.order_id)
    service.pick_up(order.order_id, partner.partner_id)
    service.deliver(order.order_id, partner.partner_id)
    print(f"Final status: {order.status.value}")

    # A customer may not cancel once food is being prepared.
    cart2 = Cart(customer)
    cart2.add(restaurant, "I2", 1)
    order2 = service.place_order(cart2, idempotency_key="tap-2")
    service.accept(order2.order_id)
    service.start_preparing(order2.order_id)
    try:
        service.cancel(order2.order_id, Actor.CUSTOMER)
    except NotAuthorizedError as exc:
        print(f"Customer cancel refused: {exc}")
    service.cancel(order2.order_id, Actor.RESTAURANT)
    print(f"{order2.order_id} cancelled by restaurant; refunds: {payments.refunds}")
    print(f"Partners idle again: {[dispatch.partner(p).active_orders for p in ('P1', 'P2')]}")

    print("\nNotifications:")
    for recipient, text in notifier.sent:
        print(f"  -> {recipient}: {text}")


if __name__ == "__main__":
    main()
```
<!-- /source -->
