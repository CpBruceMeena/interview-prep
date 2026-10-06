# Vending Machine — Implementation

> Single-file Python implementation (`vending_machine.py`, stdlib only, 3.10+) with a unittest suite (`test_vending_machine.py`).

---

## ▶️ How to Run

```bash
cd python-low-level-design/vending-machine
python3 vending_machine.py                  # deterministic demo: cash, cancel, change refusal, card, jam
python3 -m unittest test_vending_machine    # 21 tests
```

---

## 🗺️ Map of the Code

| Piece | Type | Responsibility |
|-------|------|----------------|
| `Denomination` | Enum `(cents, is_coin)` | Accepted cash; only coins are paid out as change |
| `Product`, `Slot`, `Inventory` | dataclasses / class | Catalogue, per-slot quantity and capacity |
| `make_change()` | function | Bounded coin change (fewest coins from a limited supply) |
| `CashBox` | class | The machine's own coins and notes (float + takings) |
| `Dispenser` | ABC (port) | Motor + drop sensor; `dispense()` can fail |
| `PaymentGateway` | ABC (port) | `authorize` / `capture` / `void`; `FakeGateway` for tests |
| `MachineState` | base class (State) | `IdleState`, `AwaitingPaymentState`, `OutOfServiceState` |
| `VendingMachine` | facade | Customer API, operator API, the lock, vend/refund internals |
| `Receipt` | frozen dataclass | What was sold, how, paid, change given |

Errors are typed: `InvalidStateError`, `UnknownSlotError`, `SoldOutError`, `ChangeUnavailableError`, `PaymentDeclinedError`, `DispenseFailedError` (all `VendingError`).

---

## 🔑 Key Design Decisions

### 1. Money is integer cents

`0.1 + 0.2 != 0.3` in floating point, so `balance >= price` on floats can refuse a customer who paid exactly. Every amount is an `int` of cents; `fmt()` formats for display only. In production use integer minor units or `Decimal`, never `float`.

### 2. Escrow, then commit

Inserted pieces go into `_escrow` (a `Counter` of denominations), not into the cash box. `cancel()` returns **the exact pieces** inserted — a customer who put in a $1 note gets the note back, not four quarters the machine may not have. Only when the product has dropped does escrow move into the cash box and change come out of it.

### 3. Check change *before* accepting the piece that overpays

`AwaitingPaymentState.insert()`: if the new piece completes payment, compute change from **cash box + escrow + this piece**. If `make_change` returns `None`, raise `ChangeUnavailableError` and hand the piece back; the balance and state are unchanged, so the customer can insert exact money instead. The old version dispensed and then printed "insufficient change" — taking the customer's money.

### 4. Bounded coin change, not greedy

Greedy is optimal for canonical coin systems (USD, EUR) **with unlimited supply**. A machine's supply is limited, and then greedy fails even for USD: 30c from `{QUARTER: 1, DIME: 3}` — greedy takes the quarter and is stuck at 5c. `make_change` is a DP over reachable amounts, adding one denomination at a time with up to `available[d]` copies, keeping the fewest-coin combination per amount. Cost is O(amount/5 × total coins), trivial at vending-machine sizes.

### 5. Card: authorize → dispense → capture

`_vend_card` places a hold, drives the motor, and only **captures** once the drop sensor confirms. On a jam it **voids** the hold. Charging first and refunding on failure is worse: refunds take days and cost fees. A decline in `purchase_with_card` resets the machine to idle; a decline via `pay_by_card` leaves the selection open so the customer can retry or pay cash.

### 6. State pattern, sized to the problem

Three states. The base `MachineState` rejects every action with `InvalidStateError`; each state overrides only what it allows. Vending itself happens inside one locked call, so there is no observable `DISPENSING` state — add one (and a timeout) only if dispense becomes asynchronous, e.g. waiting on a sensor callback.

### 7. Thread-safety

One `RLock` per machine guards state, stock, escrow and cash box. Every public method takes it, so each customer/operator action is atomic. Why it matters even though the keypad is single-user: restock, cash collection and maintenance arrive from an operator/telemetry thread, and `purchase_with_card` serves remote app purchases. `RLock` because `purchase_with_card` composes `select` + `pay_by_card` under one acquisition — that composition is what prevents two remote buyers from both passing the stock check for the last unit.

Trade-off to say out loud: the gateway call runs while the lock is held, so an operator action waits up to the auth latency (~1–2 s). On a single machine that serialisation is the point; the alternative (reserve the unit, release the lock, call the gateway, re-lock to commit) adds a `RESERVED` state and an expiry path for no real gain here.

---

## 🧩 Where to Extend

| Ask | Change |
|-----|--------|
| Mobile/UPI/QR payments | Another `PaymentGateway` implementation; same authorize/capture/void contract |
| Selection timeout | Operator thread calls `cancel()` after N seconds in `AWAITING_PAYMENT` |
| Dynamic pricing / discounts | Price lookup through a `PricingPolicy` at `select()`; record the price on the `Receipt` |
| Exact-change-only light | `make_change(x, cash_box)` for x in common change amounts; light on if any fail |
| Multiple items per transaction | Cart of slots in `AwaitingPaymentState`; change check against the cart total |
| Audit / telemetry | Emit `Receipt` + refund events from the facade to an outbox |
| Crash safety | Journal `AUTHORIZED` / `DISPENSED` before each step (see HLD) |

---

## 📄 Full Source

<!-- source: vending_machine.py -->
```python
"""
Vending Machine - Low Level Design
----------------------------------
Money is integer cents everywhere. Floats can't represent 0.10 exactly, and
"balance >= price" on floats is how machines eat a customer's dime.

Flow:      IDLE --select--> AWAITING_PAYMENT --(enough cash | card ok)--> vend --> IDLE
                                   |--cancel--> refund escrow --> IDLE
           any --enter_maintenance--> OUT_OF_SERVICE (refunds an open transaction)

Key rules (each one is a real failure mode when ignored):
  * Inserted cash sits in ESCROW and is returned as the exact same pieces on
    cancel; it only moves into the cash box once the product has dropped.
  * Before accepting a piece that overpays, the machine checks it can make
    change (bounded coin change, not greedy). If it can't, the piece is
    rejected on the spot instead of taking the money and short-changing.
  * Card: authorize -> dispense -> capture. A failed dispense voids the
    authorization, so the customer is never charged for nothing.
  * A dispenser jam refunds the customer and does not decrement stock.

Thread-safety: one re-entrant lock per machine guards state, stock and cash.
The physical keypad is single-user, but the admin/telemetry thread (restock,
collect cash, maintenance) and remote app purchases run concurrently with it.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional


# --- Money ----------------------------------------------------------------

class Denomination(Enum):
    """Accepted cash: (cents, is_coin). Only coins are paid out as change.
    Values are tuples so DOLLAR_COIN and ONE_NOTE don't become Enum aliases."""
    NICKEL = (5, True)
    DIME = (10, True)
    QUARTER = (25, True)
    DOLLAR_COIN = (100, True)
    ONE_NOTE = (100, False)
    FIVE_NOTE = (500, False)

    def __init__(self, cents: int, is_coin: bool):
        self.cents = cents
        self.is_coin = is_coin


def fmt(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def _sum(pieces: Mapping[Denomination, int]) -> int:
    return sum(d.cents * n for d, n in pieces.items())


# --- Errors ---------------------------------------------------------------

class VendingError(Exception):
    pass


class InvalidStateError(VendingError):
    pass


class UnknownSlotError(VendingError):
    pass


class SoldOutError(VendingError):
    pass


class ChangeUnavailableError(VendingError):
    """Raised when a piece is rejected because change can't be made."""


class PaymentDeclinedError(VendingError):
    pass


class DispenseFailedError(VendingError):
    """The product didn't drop; the customer has been refunded."""


# --- Catalogue & stock ----------------------------------------------------

@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int

    def __post_init__(self):
        if self.price_cents <= 0:
            raise ValueError("price must be positive")


@dataclass
class Slot:
    code: str
    product: Product
    quantity: int
    capacity: int

    def __post_init__(self):
        if not 0 <= self.quantity <= self.capacity:
            raise ValueError(f"slot {self.code}: quantity must be in 0..{self.capacity}")


class Inventory:
    def __init__(self):
        self._slots: dict[str, Slot] = {}

    def add_slot(self, code: str, product: Product, quantity: int, capacity: int = 10) -> None:
        if code in self._slots:
            raise ValueError(f"slot {code} already exists")
        self._slots[code] = Slot(code, product, quantity, capacity)

    def slot(self, code: str) -> Slot:
        try:
            return self._slots[code]
        except KeyError:
            raise UnknownSlotError(code) from None

    def restock(self, code: str, qty: int) -> int:
        slot = self.slot(code)
        if qty <= 0 or slot.quantity + qty > slot.capacity:
            raise ValueError(f"slot {code}: can add 1..{slot.capacity - slot.quantity}")
        slot.quantity += qty
        return slot.quantity

    def snapshot(self) -> dict[str, int]:
        return {code: s.quantity for code, s in self._slots.items()}


# --- Cash box & change making ---------------------------------------------

def make_change(amount: int, available: Mapping[Denomination, int]) -> Optional[Counter]:
    """Fewest coins summing to `amount` using at most available[d] of each.

    Bounded coin change by DP over reachable amounts. Greedy is NOT enough
    here: even with canonical denominations a limited supply breaks it
    (30c from {QUARTER: 1, DIME: 3}: greedy takes the quarter and is stuck,
    three dimes work). O(amount/5 * total coins) for these denominations.
    """
    if amount == 0:
        return Counter()
    best: dict[int, Counter] = {0: Counter()}
    for d in sorted((d for d in available if d.is_coin), key=lambda d: -d.cents):
        layer = dict(best)
        for reached, used in best.items():
            for k in range(1, available[d] + 1):
                total = reached + k * d.cents
                if total > amount:
                    break
                cand = used + Counter({d: k})
                prev = layer.get(total)
                if prev is None or sum(cand.values()) < sum(prev.values()):
                    layer[total] = cand
        best = layer
    return best.get(amount)


class CashBox:
    """Coins/notes the machine owns (change float + takings)."""

    def __init__(self, initial: Optional[Mapping[Denomination, int]] = None):
        self._counts: Counter = Counter(initial or {})

    def deposit(self, pieces: Mapping[Denomination, int]) -> None:
        self._counts.update(pieces)

    def withdraw(self, pieces: Mapping[Denomination, int]) -> None:
        for d, n in pieces.items():
            if self._counts[d] < n:
                raise ValueError(f"cash box has {self._counts[d]} x {d.name}, need {n}")
        self._counts.subtract(pieces)

    def counts(self) -> dict[Denomination, int]:
        return {d: n for d, n in self._counts.items() if n}

    def total(self) -> int:
        return sum(d.cents * n for d, n in self._counts.items())


# --- External hardware / services (ports) ---------------------------------

class Dispenser(ABC):
    @abstractmethod
    def dispense(self, slot_code: str) -> bool:
        """Drive the motor; True iff the drop sensor saw the product fall."""


class ReliableDispenser(Dispenser):
    def dispense(self, slot_code: str) -> bool:
        return True


class PaymentGateway(ABC):
    """Card/mobile payments. Two-phase so we only charge for what dropped."""

    @abstractmethod
    def authorize(self, token: str, amount_cents: int) -> str:
        """Place a hold; returns an auth id. Raises PaymentDeclinedError."""

    @abstractmethod
    def capture(self, auth_id: str) -> None: ...

    @abstractmethod
    def void(self, auth_id: str) -> None: ...


class FakeGateway(PaymentGateway):
    """In-memory gateway: tokens starting with 'declined' are refused."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next = 0
        self.holds: dict[str, int] = {}
        self.captured: dict[str, int] = {}
        self.voided: dict[str, int] = {}

    def authorize(self, token: str, amount_cents: int) -> str:
        if token.startswith("declined"):
            raise PaymentDeclinedError(token)
        with self._lock:
            self._next += 1
            auth_id = f"auth-{self._next}"
            self.holds[auth_id] = amount_cents
            return auth_id

    def capture(self, auth_id: str) -> None:
        with self._lock:
            self.captured[auth_id] = self.holds.pop(auth_id)

    def void(self, auth_id: str) -> None:
        with self._lock:
            self.voided[auth_id] = self.holds.pop(auth_id)


# --- Results --------------------------------------------------------------

class PaymentMethod(Enum):
    CASH = "cash"
    CARD = "card"


@dataclass(frozen=True)
class Receipt:
    slot_code: str
    product: Product
    method: PaymentMethod
    paid_cents: int
    change: dict[Denomination, int] = field(default_factory=dict)

    @property
    def change_cents(self) -> int:
        return _sum(self.change)


# --- States (State pattern) -----------------------------------------------

class MachineState(ABC):
    """Every customer action is rejected unless a state allows it."""
    name: str = "?"

    def __init__(self, machine: VendingMachine):
        self.m = machine

    def select(self, code: str) -> Product:
        raise InvalidStateError(f"can't select in {self.name}")

    def insert(self, piece: Denomination) -> Optional[Receipt]:
        raise InvalidStateError(f"can't insert money in {self.name}")

    def pay_by_card(self, token: str) -> Receipt:
        raise InvalidStateError(f"can't pay in {self.name}")

    def cancel(self) -> dict[Denomination, int]:
        raise InvalidStateError(f"nothing to cancel in {self.name}")


class IdleState(MachineState):
    name = "IDLE"

    def select(self, code: str) -> Product:
        slot = self.m._inventory.slot(code)
        if slot.quantity == 0:
            raise SoldOutError(f"{slot.product.name} ({code}) is sold out")
        self.m._selected = slot
        self.m._set_state(self.m._awaiting)
        return slot.product


class AwaitingPaymentState(MachineState):
    name = "AWAITING_PAYMENT"

    def insert(self, piece: Denomination) -> Optional[Receipt]:
        m = self.m
        price = m._selected.product.price_cents
        balance = m._escrow_total() + piece.cents
        if balance < price:
            m._escrow[piece] += 1
            return None
        # This piece completes payment. Accept it only if we can make change
        # from the cash box plus everything in escrow (including this piece).
        pool = Counter(m._cash.counts())
        pool.update(m._escrow)
        pool[piece] += 1
        change = make_change(balance - price, pool)
        if change is None:
            raise ChangeUnavailableError(
                f"can't make {fmt(balance - price)} change; {piece.name} returned, "
                f"balance still {fmt(m._escrow_total())}")
        m._escrow[piece] += 1
        return m._vend_cash(change)

    def pay_by_card(self, token: str) -> Receipt:
        if self.m._escrow:
            raise InvalidStateError("cash already inserted; finish with cash or cancel")
        return self.m._vend_card(token)

    def cancel(self) -> dict[Denomination, int]:
        return self.m._refund_and_reset()


class OutOfServiceState(MachineState):
    name = "OUT_OF_SERVICE"


# --- Machine (facade) -----------------------------------------------------

class VendingMachine:
    def __init__(self, dispenser: Optional[Dispenser] = None,
                 gateway: Optional[PaymentGateway] = None,
                 change_float: Optional[Mapping[Denomination, int]] = None):
        self._inventory = Inventory()
        self._cash = CashBox(change_float)
        self._dispenser = dispenser or ReliableDispenser()
        self._gateway = gateway or FakeGateway()
        self._lock = threading.RLock()

        self._idle = IdleState(self)
        self._awaiting = AwaitingPaymentState(self)
        self._out_of_service = OutOfServiceState(self)
        self._state: MachineState = self._idle

        self._selected: Optional[Slot] = None
        self._escrow: Counter = Counter()

    # ---- customer API (each call is atomic) ----
    def select(self, code: str) -> Product:
        with self._lock:
            return self._state.select(code)

    def insert(self, piece: Denomination) -> Optional[Receipt]:
        """Returns a Receipt once enough money is in, else None."""
        with self._lock:
            return self._state.insert(piece)

    def pay_by_card(self, token: str) -> Receipt:
        with self._lock:
            return self._state.pay_by_card(token)

    def cancel(self) -> dict[Denomination, int]:
        """Returns the exact pieces inserted."""
        with self._lock:
            return self._state.cancel()

    def purchase_with_card(self, code: str, token: str) -> Receipt:
        """Remote/app purchase: select + pay as one atomic step."""
        with self._lock:
            self.select(code)
            try:
                return self.pay_by_card(token)
            except PaymentDeclinedError:
                self._refund_and_reset()
                raise

    # ---- operator API ----
    def add_slot(self, code: str, product: Product, quantity: int, capacity: int = 10) -> None:
        with self._lock:
            self._inventory.add_slot(code, product, quantity, capacity)

    def restock(self, code: str, qty: int) -> int:
        with self._lock:
            return self._inventory.restock(code, qty)

    def load_change(self, pieces: Mapping[Denomination, int]) -> None:
        with self._lock:
            self._cash.deposit(pieces)

    def collect_cash(self, keep_float: Mapping[Denomination, int]) -> dict[Denomination, int]:
        """Empty the cash box down to `keep_float`; returns what was removed."""
        with self._lock:
            counts = self._cash.counts()
            take = {d: n - keep_float.get(d, 0) for d, n in counts.items()
                    if n > keep_float.get(d, 0)}
            self._cash.withdraw(take)
            return take

    def enter_maintenance(self) -> dict[Denomination, int]:
        """Takes the machine offline; refunds any open transaction."""
        with self._lock:
            refunded = self._refund_and_reset() if self._state is self._awaiting else {}
            self._set_state(self._out_of_service)
            return refunded

    def exit_maintenance(self) -> None:
        with self._lock:
            if self._state is not self._out_of_service:
                raise InvalidStateError("not in maintenance")
            self._set_state(self._idle)

    # ---- queries ----
    @property
    def state(self) -> str:
        return self._state.name

    @property
    def balance_cents(self) -> int:
        with self._lock:
            return self._escrow_total()

    def stock(self) -> dict[str, int]:
        with self._lock:
            return self._inventory.snapshot()

    def cash_total_cents(self) -> int:
        with self._lock:
            return self._cash.total()

    # ---- internals (called with the lock held) ----
    def _set_state(self, state: MachineState) -> None:
        self._state = state

    def _escrow_total(self) -> int:
        return _sum(self._escrow)

    def _refund_and_reset(self) -> dict[Denomination, int]:
        returned = dict(self._escrow)
        self._escrow.clear()
        self._selected = None
        self._set_state(self._idle)
        return returned

    def _drop(self) -> bool:
        return self._dispenser.dispense(self._selected.code)

    def _vend_cash(self, change: Counter) -> Receipt:
        slot = self._selected
        if not self._drop():
            returned = self._refund_and_reset()
            raise DispenseFailedError(
                f"{slot.product.name} did not drop; returned {fmt(_sum(returned))}")
        paid = self._escrow_total()
        # Commit: escrow -> cash box, then pay change out of it. make_change
        # was computed over (cash box + escrow), so the withdraw can't fail.
        self._cash.deposit(self._escrow)
        self._cash.withdraw(change)
        slot.quantity -= 1
        receipt = Receipt(slot.code, slot.product, PaymentMethod.CASH, paid, dict(change))
        self._escrow.clear()
        self._selected = None
        self._set_state(self._idle)
        return receipt

    def _vend_card(self, token: str) -> Receipt:
        slot = self._selected
        price = slot.product.price_cents
        auth_id = self._gateway.authorize(token, price)   # may raise Declined
        if not self._drop():
            self._gateway.void(auth_id)
            self._refund_and_reset()
            raise DispenseFailedError(f"{slot.product.name} did not drop; card not charged")
        slot.quantity -= 1
        self._gateway.capture(auth_id)
        self._selected = None
        self._set_state(self._idle)
        return Receipt(slot.code, slot.product, PaymentMethod.CARD, price)


# --- Demo -----------------------------------------------------------------

def build_demo_machine(dispenser: Optional[Dispenser] = None,
                       gateway: Optional[PaymentGateway] = None) -> VendingMachine:
    vm = VendingMachine(dispenser, gateway,
                        change_float={Denomination.QUARTER: 4, Denomination.DIME: 5,
                                      Denomination.NICKEL: 4})
    vm.add_slot("A1", Product("coke", "Coke", 150), 5)
    vm.add_slot("A2", Product("water", "Water", 100), 1)
    vm.add_slot("B1", Product("chips", "Chips", 125), 5)
    vm.add_slot("C1", Product("gum", "Gum", 65), 5)
    return vm


def demo() -> None:
    def show_change(r: Receipt) -> str:
        parts = ", ".join(f"{n} x {d.name}" for d, n in r.change.items())
        return f"{fmt(r.change_cents)} ({parts})" if parts else "none"

    vm = build_demo_machine()
    D = Denomination
    print("=== Cash purchase with change ===")
    print("  selected:", vm.select("C1").name, "for", fmt(65))
    print("  insert QUARTER ->", vm.insert(D.QUARTER), "balance", fmt(vm.balance_cents))
    r = vm.insert(D.ONE_NOTE)
    print(f"  insert ONE_NOTE -> vended {r.product.name}, paid {fmt(r.paid_cents)}, "
          f"change {show_change(r)}")

    print("\n=== Cancel returns the exact pieces ===")
    vm.select("B1")
    vm.insert(D.DIME)
    vm.insert(D.QUARTER)
    print("  cancel ->", {d.name: n for d, n in vm.cancel().items()}, "state", vm.state)

    print("\n=== Can't make change: the note is rejected, not swallowed ===")
    vm.collect_cash(keep_float={})      # empty the cash box
    vm.select("A1")
    vm.insert(D.ONE_NOTE)
    try:
        vm.insert(D.FIVE_NOTE)
    except ChangeUnavailableError as e:
        print("  rejected:", e)
    r = vm.insert(D.QUARTER) or vm.insert(D.QUARTER)
    print(f"  exact money instead -> vended {r.product.name}, change {show_change(r)}")

    print("\n=== Card purchase (authorize -> dispense -> capture) ===")
    gw = FakeGateway()
    vm = build_demo_machine(gateway=gw)
    r = vm.purchase_with_card("A2", "visa-4242")
    print(f"  vended {r.product.name} by {r.method.value}; captured {gw.captured}")
    try:
        vm.select("A2")
    except SoldOutError as e:
        print("  next select:", e)

    print("\n=== Jammed dispenser: card hold is voided ===")

    class Jammed(Dispenser):
        def dispense(self, slot_code: str) -> bool:
            return False

    gw = FakeGateway()
    vm = build_demo_machine(dispenser=Jammed(), gateway=gw)
    try:
        vm.purchase_with_card("A1", "visa-4242")
    except DispenseFailedError as e:
        print(" ", e, "| voided:", gw.voided, "| stock A1:", vm.stock()["A1"])


if __name__ == "__main__":
    demo()
```
<!-- /source -->
