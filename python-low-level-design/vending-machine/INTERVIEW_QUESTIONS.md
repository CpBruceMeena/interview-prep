# Vending Machine - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** State machines, money handling, failure paths, payment systems, concurrency

---

## Question 1: State Machine Design
**Interviewer:** *"Design a vending machine that handles the complete purchase flow using state machines."*  

### 🎯 Expected Answer

**State Diagram:**
```
                 select(code)                 enough cash, change OK
  ┌──────┐ ─────────────────────▶ ┌────────────────────┐ ──────────┐
  │ IDLE │                         │  AWAITING_PAYMENT  │           │ dispense,
  │      │ ◀───────────────────── │                    │ ◀─────────┘ commit
  └──┬───┘   cancel / jam: refund  └────────────────────┘  (back to IDLE)
     │  ▲                              card: authorize → dispense → capture
     ▼  │ exit
  ┌────────────────┐
  │ OUT_OF_SERVICE │   entered from any state; refunds an open transaction
  └────────────────┘
```

**State Pattern with a rejecting base class:**
```python
class MachineState(ABC):
    def __init__(self, machine): self.m = machine
    def select(self, code):      raise InvalidStateError(...)
    def insert(self, piece):     raise InvalidStateError(...)
    def pay_by_card(self, tok):  raise InvalidStateError(...)
    def cancel(self):            raise InvalidStateError(...)

class IdleState(MachineState):              # overrides select
class AwaitingPaymentState(MachineState):   # overrides insert, pay_by_card, cancel
class OutOfServiceState(MachineState):      # overrides nothing
```

Each state overrides only what it allows, so adding a state is one class and illegal actions fail loudly by default.

**Why State over if/else?** With `if state == IDLE ... elif ...` in every method, adding `OUT_OF_SERVICE` means editing every method. Honest caveat: with three states and four actions, a transition table is also fine — say so, then pick one.

### ✅ Transition Guards

| Transition | Guard |
|------------|-------|
| IDLE → AWAITING_PAYMENT | Slot exists and quantity > 0 |
| AWAITING → vend | Balance ≥ price **and** change can be made from cash box + escrow |
| AWAITING → IDLE (cancel / jam) | Return exact escrowed pieces; void card hold |
| any → OUT_OF_SERVICE | Refund the open transaction first |

---

## Question 2: Money and Change
**Interviewer:** *"How do you represent money, and how do you make change?"*

**Integer cents.** Floats can't represent 0.10 exactly; comparisons and sums drift. Use integer minor units (or `Decimal`) everywhere; format only at the edge.

**Change-making with a limited supply:**
```python
def make_change(amount: int, available: Mapping[Denomination, int]) -> Optional[Counter]:
    best = {0: Counter()}                         # reachable amount -> fewest coins
    for d in coins_desc(available):
        layer = dict(best)
        for reached, used in best.items():
            for k in range(1, available[d] + 1):
                total = reached + k * d.cents
                if total > amount: break
                cand = used + Counter({d: k})
                if total not in layer or size(cand) < size(layer[total]):
                    layer[total] = cand
        best = layer
    return best.get(amount)                       # None -> can't make change
```

**Why not greedy?** Greedy is optimal for *canonical* systems like USD/EUR with **unlimited** coins. (Canonical doesn't mean "each coin divides the next" — 25 isn't a multiple of 10 — it means greedy happens to be optimal for every amount.) A machine's coin tubes are limited, and then greedy fails even for USD: 30c from one quarter and three dimes. Non-canonical systems (1, 3, 4) break greedy even with unlimited supply.

**When change is impossible:** reject the piece that overpays before accepting it, keep the transaction open, and light "exact change only". Don't vend and then short-change.

---

## Question 3: Payment Integration
**Interviewer:** *"Add card payments."*

```python
class PaymentGateway(ABC):
    def authorize(self, token, amount_cents) -> str: ...   # hold, may decline
    def capture(self, auth_id) -> None: ...
    def void(self, auth_id) -> None: ...
```

Flow: **authorize → dispense → capture**; void on jam. Charging first and refunding on failure means a real charge, a refund that takes days, and fees. Cash and card share the same states; they differ only in how the sale commits. Don't let a customer mix: once cash is in escrow, `pay_by_card` is rejected (or define split tender explicitly).

Follow-ups:
- *Gateway times out during authorize?* Send an idempotency key; on timeout, retry with the same key or query by it. Never authorize twice blind.
- *Machine crashes between dispense and capture?* Journal `AUTHORIZED` and `DISPENSED` to local storage before each step; recover on boot (capture dispensed, void the rest). Uncaptured holds also expire at the issuer.

---

## Question 4: Concurrency & Thread Safety
**Interviewer:** *"Only one person can stand at the machine. Why do you need a lock?"*

Because the keypad isn't the only caller:

1. **Operator/telemetry thread:** restock, cash collection, maintenance mode run while a customer is mid-transaction.
2. **Remote purchases** (app/QR): two buyers can race for the last unit.

One lock per machine, held for each public operation. The race to show:

```python
# Broken: check-then-act across two calls
if vm.stock()["A1"] > 0:      # both buyers see 1
    vm.purchase(...)          # both vend; stock goes to -1
```

`purchase_with_card` does select + pay under one `RLock` acquisition, so the stock check and the decrement are atomic. Test: 16 threads buy from a slot of 3 → exactly 3 succeed, 3 captures, no dangling holds.

**Lock held across a network call?** Yes, deliberately: the machine is a serial device and the call is ~1–2 s. The alternative is reserve → unlock → authorize → relock → commit, which needs a `RESERVED` state and expiry — worth it for a shared resource with many buyers (ticketing), not for one machine.

---

## Question 5: Failure Handling

| Failure | Correct behaviour |
|---------|-------------------|
| Motor jam / drop sensor sees nothing | Cash: return escrow. Card: void. Stock unchanged |
| Can't make change | Reject the overpaying piece; transaction stays open |
| Card declined | Stay in AWAITING_PAYMENT (or reset for app purchase) |
| Customer walks away | Timeout → cancel → return escrow |
| Maintenance mid-transaction | Refund, then go out of service |
| Restock beyond capacity | Reject (`ValueError`), don't silently clamp |
| Power loss | Escrow is physical — returned on boot; journal resolves card holds |

---

## Question 6: Testing Strategy

- **Fake the ports:** `Jammed` dispenser, `FakeGateway` (records holds/captures/voids, declines tokens starting with `declined`).
- **Pure-function tests for `make_change`:** greedy-breaking case, fewest coins, impossible, notes never paid out.
- **Flow tests per path:** exact cash, overpay with change, change from escrow, rejected piece, cancel returns exact pieces, jam refunds, card capture/decline/void, maintenance refund.
- **Accounting invariants:** cash box grows by exactly the price; stock decrements only on a confirmed drop.
- **Concurrency:** many threads racing for the last units → no oversell, no dangling authorizations; restock racing with sales → `final = initial + restocked − sold` and never above capacity.

---

## Question 7: Inventory at Fleet Scale
**Interviewer:** *"Design the inventory system for a vending machine chain."*

- The **machine** is the source of truth for its slots; the cloud is eventually consistent via an append-only event stream (`SOLD`, `RESTOCKED`, `COUNTED`).
- Restock alerts on `quantity <= reorder_level`; route planning from forecasted depletion (see HLD).
- The operator's physical count at restock is authoritative and resets drift (theft, mis-loads).
- Expiry per slot load (not per product), FIFO by loading newer items behind older.

---

## ❌ Common Mistakes

- Money as `float`.
- Greedy change with a limited coin supply; or vending first and discovering "insufficient change" afterwards.
- `cancel()` that zeroes a balance instead of returning the inserted pieces.
- Charging the card before dispensing.
- Decrementing stock before the drop is confirmed.
- States that silently `print` on illegal actions instead of raising — callers (and tests) can't tell anything went wrong.
- Claiming "thread-safe" with a check (`is_available`) and an act (`dispense`) in separate unlocked calls.
- `PaymentStrategy` classes that "process" a payment by printing and returning `True` — no failure path modelled at all.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** clean state machine with typed errors; integer money; correct change-making with limited supply; escrow; cancel/jam refund; a lock that covers check-and-act; tests with fakes.
- **Staff:** drives the design from failure modes (jam, crash between dispense and capture, gateway timeout, lost acks) and the order of operations that keeps money safe; two-phase card payment with idempotency keys and a recovery journal; knows when *not* to add a reservation state; frames fleet inventory as machine-authoritative event streams with idempotent ingestion.
