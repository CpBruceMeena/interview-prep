# Inventory Management System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Overselling under concurrency, reservation vs commit, multi-warehouse allocation, replenishment, traceability

---

## Question 1: Core Design
**Interviewer:** *"Design an inventory management system — products, warehouses, stock levels, orders."*

### 🎯 Expected Answer

```python
@dataclass(frozen=True)
class Product:      sku, name, unit_price: Decimal, reorder_level, reorder_quantity
@dataclass(frozen=True)
class Warehouse:    warehouse_id, name, priority

class InventoryItem:          # one per (sku, warehouse), owns a lock
    on_hand: int              # physically on the shelf
    reserved: int             # promised, not yet shipped
    @property
    def available(self): return self.on_hand - self.reserved

class Reservation:            # order_id, lines[(sku, warehouse, qty)], expires_at, status
class Movement:               # immutable ledger row: type, delta, on_hand_after, reference, at
```

**Why `available = on_hand − reserved`?** It separates "what we physically have" from "what we can still promise". At checkout we `reserve()` (raise `reserved`); nothing physical moves. On payment/shipment we `commit()` (lower both `on_hand` and `reserved`). On cancel or timeout we `release()` (lower `reserved`). Every operation preserves `0 <= reserved <= on_hand`.

---

## Question 2: "Two customers buy the last unit at the same time. What happens?"

### 🎯 Answer

The bug to avoid is check-then-act:

```python
if item.available >= q:      # both threads see 1
    item.reserved += q       # both reserve → oversold
```

The check and the write must be one atomic step. In the LLD that is the item's lock around `reserve()`. In a database it is a **conditional update**, which is atomic per row and needs no version column:

```sql
UPDATE inventory_items
SET reserved = reserved + :q
WHERE sku = :sku AND warehouse_id = :wh
  AND on_hand - reserved >= :q;
-- 0 rows updated => insufficient stock; no retry needed
```

`SELECT ... FOR UPDATE` then `UPDATE` also works but holds the row lock for a round trip. Optimistic locking with a `version` column works too, but under contention on a hot SKU most attempts fail and retry, so the conditional update is the better default. The test `test_no_overselling_under_contention` fires 40 threads at 50 units, 2 each, and asserts exactly 25 succeed.

---

## Question 3: "An order has 3 lines. Two are in stock, one isn't."

### 🎯 Answer

Decide with the interviewer: all-or-nothing (default) or partial with backorder.

All-or-nothing without compensation: lock every candidate item **in a global sorted order**, plan the whole order against the locked snapshot, and only then mutate. The plan raises before anything changes, so there is nothing to roll back. Sorted acquisition prevents the deadlock where order A locks (X, Y) and order B locks (Y, X).

In SQL it is one transaction with one conditional update per line; if any returns 0 rows, roll back. Update rows in a consistent order (by `sku, warehouse_id`) for the same deadlock reason; Postgres will detect a deadlock and abort one transaction, but that is a failure you caused.

---

## Question 4: "Now stock is in several warehouses."

### 🎯 Answer

Allocation becomes a strategy: `allocate(qty, [StockView(warehouse, priority, available)]) -> [(warehouse, qty)] | None`.

- `SingleWarehouseFirstAllocation`: one warehouse that can fill the line, else split. Minimises shipments, which usually dominates cost.
- `GreedySplitAllocation`: fill from the preferred warehouse and spill over.
- Production: score warehouses by distance to the customer, shipping cost, and backlog; keep a per-warehouse safety buffer so one region's demand doesn't drain stock that another region needs.

The strategy is a pure function of an immutable snapshot taken under the locks, so it is testable without threads and cannot accidentally mutate stock.

---

## Question 5: "Customers abandon checkout. Stock is stuck in `reserved`."

### 🎯 Answer

Reservations carry `expires_at` (e.g. 15 minutes). A sweeper calls `expire_reservations()` to release ACTIVE reservations past their TTL. Two subtleties:

1. **The sweeper is periodic**, so `commit()` must check the TTL itself; otherwise a payment arriving 2 seconds after expiry but before the sweep would commit stock that is about to be released.
2. **Commit vs sweeper race:** both take the reservation's lock and re-check status, so exactly one wins. If payment succeeded but the reservation expired, the order flow must try to re-reserve or refund; that is a business decision to name, not hide.

In Redis-backed designs the same idea is a key with a TTL, but key expiry alone does not give stock back to the counter, so you still need a sweeper or keyspace-notification consumer, and keyspace notifications are fire-and-forget (lost if no subscriber is connected).

---

## Question 6: "The client times out and retries reserve. Do we reserve twice?"

### 🎯 Answer

No: `reserve()` is idempotent on `order_id`. A retry with the same lines returns the original reservation; the same `order_id` with different lines raises `IdempotencyConflictError`. A duplicate that arrives while the first is still running gets a conflict (the client retries and then gets the stored result). `commit()` on a COMMITTED reservation and `release()` on a RELEASED/EXPIRED one are no-ops, so those are safe to retry too. In production the idempotency record is a unique constraint on `order_id` in the same transaction as the stock update.

---

## Question 7: Reorder Point Logic
**Interviewer:** *"Design a reorder system that prevents stockouts."*

### 🎯 Answer

Reorder on **inventory position = available + quantity on open POs**, not on on-hand. Using on-hand double-orders (the PO you raised yesterday hasn't arrived yet) and ignores stock already promised.

**Reorder point** with safety stock (fixed lead time, normally distributed daily demand):
```python
safety_stock = z * sigma_daily_demand * math.sqrt(lead_time_days)   # z = 1.645 for 95% cycle service level
reorder_point = avg_daily_demand * lead_time_days + safety_stock
```

**Economic Order Quantity:**
```python
eoq = math.sqrt(2 * annual_demand * cost_per_order / holding_cost_per_unit_per_year)
```

Too little safety stock → stockouts; too much → carrying cost. The z-score sets the probability of not stocking out during one replenishment cycle. The code's `DemandBasedReorderPolicy` is the simpler "days of cover" version (lead + safety days); swapping in the formula above is a new `ReorderPolicy`, not a service change. Demand is computed from `SHIP` movements only; counting transfers as demand is a common bug.

---

## Question 8: Stock Movement & Traceability

Every physical change appends an immutable `Movement(type, delta, on_hand_after, reference, at)`. Because only physical changes are recorded, `sum(delta)` over an item's movements equals its `on_hand`, which is the reconciliation check auditors run. Reservations are tracked separately with their own lifecycle. Timestamps should be UTC and timezone-aware (`datetime.now(timezone.utc)`; `datetime.utcnow()` is deprecated since Python 3.12 and returns a naive datetime).

**FIFO costing** needs receipt layers (qty, unit_cost, received_at), consumed oldest first:
```python
def fifo_cogs(layers, qty_sold):
    cost, remaining = Decimal("0"), qty_sold
    for layer in sorted(layers, key=lambda l: l.received_at):
        take = min(remaining, layer.remaining_qty)
        cost += take * layer.unit_cost
        layer.remaining_qty -= take
        remaining -= take
        if remaining == 0:
            break
    return cost
```

---

## Question 9: Inventory Valuation Methods

| Method | How | Pros | Cons |
|--------|-----|------|------|
| **FIFO** | Oldest cost layers are expensed first | Matches physical flow for most goods; balance-sheet value is close to current cost | When prices rise, COGS is lower so reported profit (and tax) is higher |
| **Weighted average** | Running average cost per unit | Simple, smooths price swings | Lags real cost changes |
| **Standard cost** | Predetermined cost, variances tracked separately | Simple, good for manufacturing | Needs periodic revaluation |

(LIFO is permitted under US GAAP but not IFRS.)

---

## Question 10: Order Fulfillment Pipeline

```python
def place_order(order):
    res = inventory.reserve(order.id, order.lines)        # atomic, all-or-nothing, idempotent
    try:
        payments.charge(order.id, order.total)            # idempotent on order.id too
    except PaymentDeclined:
        inventory.release(res.reservation_id)
        raise
    inventory.commit(res.reservation_id)                  # may raise ReservationExpiredError
```

Two mistakes to avoid: checking availability in one loop and reserving in another (race), and "releasing" the reservation after shipping instead of committing it (that makes the units available again *and* leaves on_hand wrong). If commit fails after a successful charge, refund or re-reserve; in a service this whole flow is a saga driven by events.

---

## 🔁 Follow-ups interviewers push on

**"Add returns."** New `MovementType.RETURN` that increases `on_hand`, ideally into a quarantine/inspection state first: a returned item is not sellable until inspected. Model that as a separate sellable flag or a separate "virtual warehouse".

**"A cycle count finds 5 units where the system says 8, but 7 are reserved."** `adjust_stock` refuses to drop below `reserved` here. In production you accept the count (reality wins), mark 2 units of reservations as short, and trigger re-allocation from another warehouse or a customer notification. Never silently clamp.

**"Make reads fast; the product page shows availability."** Product pages can read a cached, slightly stale `available`. Checkout must go through the authoritative conditional update. Saying which reads may be stale is the senior answer.

**"One SKU (a console launch) gets 50K requests/second."** A single row becomes the bottleneck. Options: split the stock into N sub-buckets (rows) and reserve from a random bucket, falling back to others; or move the hot counter to Redis with an atomic Lua `if available >= q then decr` script and reconcile to the DB asynchronously; or put a queue in front and admit buyers in order. Each trades exactness or latency differently.

**"How do you test this?"** Unit tests for the item arithmetic and each strategy (pure functions). Service tests with a `ManualClock` for TTLs. Concurrency tests with a `threading.Barrier` to line threads up, asserting invariants (no oversell, stock conserved, exactly one winner) rather than timings. In production, a property test that applies random operation sequences and checks `0 <= reserved <= on_hand` and ledger reconciliation after each.

**"What about deadlocks?"** Global lock order (sorted keys) for item locks, and a fixed hierarchy between lock types: reservation lock → item locks → registry/ledger locks. The opposite-transfers test would hang without it.

---

## ⚠️ Common mistakes

- Decrementing `on_hand` at checkout (physical count becomes wrong) or not reserving at all (oversell).
- Check-then-act: reading availability, then updating in a separate step without a lock or conditional update.
- `release_reservation` that clamps with `max(0, ...)`: it hides double-release bugs instead of failing.
- Reservations without identity: a cancel releases "some quantity of SKU X", possibly someone else's.
- Transfers that debit the source and then fail on the destination (stock vanishes); transfers that move units already promised.
- Locking multiple rows/items in arbitrary order (deadlock).
- Reordering on on-hand instead of position (duplicate POs every run).
- Float money for valuation.
- Counting transfers as demand in a demand-based reorder.

---

## 🎯 Senior vs Staff signal

- **Senior:** clean entities, the on_hand / reserved / available split, a correct lock or conditional update for a single SKU, TTL on reservations, working tests including a contention test.
- **Staff:** states the invariant first and shows every operation preserves it; handles multi-line orders all-or-nothing with ordered locking; makes commit vs expiry and client retries explicitly safe; knows when the conditional update beats optimistic locking; names the hot-SKU problem and its options with trade-offs; separates stale-OK reads from authoritative writes; frames checkout + payment + inventory as a saga with clear compensation.

---

## Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `AllocationStrategy`, `ReorderPolicy` | Warehouse choice and replenishment change independently of the service |
| **Facade** | `InventoryService` | Single entry point that owns locking and invariants |
| **State machine** | `ReservationStatus`, `POStatus` | Explicit legal transitions; illegal ones raise |
| **Append-only ledger** | `Movement` | Audit trail and reconciliation |

An Observer for low-stock alerts is a natural addition (`check_reorder` would notify listeners), but it is not in the code.
