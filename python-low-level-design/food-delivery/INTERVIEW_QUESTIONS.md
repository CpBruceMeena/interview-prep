# Food Delivery - Interview Questions & Answers

> **Target Level:** Senior / Staff Engineer
> **Evaluation Focus:** State machines with actor rules, idempotency, concurrency in assignment, money handling, saga-style orchestration

---

## Question 1: Core design
**Interviewer:** *"Design the order flow for a food delivery app."*

### 🎯 Expected answer

Start from the state machine and the actors, not from classes:

```
PLACED ─► ACCEPTED ─► PREPARING ─► READY ─► PICKED_UP ─► DELIVERED
  │  └─► REJECTED        │            │         │
  └──────────┴───────────┴────────────┴─────────┴──► CANCELLED (rules per actor)
```

Then the seams: `AssignmentStrategy` (dispatch), `PricingRule` chain (fees, surge, coupons, tax), `OrderObserver` (notifications), `PaymentGateway` (port). `OrderService` is a thin facade; `Order` owns its transitions and `DeliveryPartner` owns its capacity.

Key decisions to state: one restaurant per cart; prices snapshotted into `OrderLine`; `Decimal` money; placement idempotent on a client key; partner assigned on accept so travel overlaps cooking.

---

## Question 2: "The user taps Place Order twice / the network retried. What happens?"

### 🎯 Answer

The client generates an idempotency key when the checkout screen opens and sends it with every attempt. Server side, `(customer_id, key)` maps to a slot holding a request fingerprint and the result:

| Situation | Behaviour |
|---|---|
| Retry, same body | Return the original order; no second charge |
| Same key, different body | `409`-style `IdempotencyConflictError` |
| Two requests in flight at once | Second waits for the first (`threading.Event`); in a DB: `INSERT ... ON CONFLICT DO NOTHING` on a unique `(customer_id, key)`, losers poll/read |
| First attempt failed (card declined) | Slot deleted; the same key may be retried |

And the key is passed through to the PSP, so a crash *after* charging but *before* persisting the order is still safe: the retry gets the same `payment_id` back.

**Follow-up: "Why not dedup on (customer, restaurant, items) within 30 s?"** Because a user can legitimately order the same thing twice (office lunch for two people). Content-based dedup guesses intent; a client key states it.

---

## Question 3: "Two orders are accepted at the same moment and both pick the same nearest partner."

### 🎯 Answer

Separate *choosing* from *taking*:

- `strategy.rank()` works on snapshots and may be stale; that's fine.
- `partner.try_claim()` is a compare-and-set under the partner's own lock: it re-checks online, capacity and batch constraints. The loser moves to its next candidate.
- In production: `UPDATE partner SET state='ASSIGNED', order_id=? WHERE id=? AND state='AVAILABLE'` (check rows affected), or a Redis Lua script on the partner hash, or a single-writer dispatch shard per geo cell.

A global lock around "find nearest + assign" is correct but serialises all dispatch in a city. Mention it as the simple first version, then move to CAS.

**Follow-up: "And if the order is cancelled while you're assigning?"** `order.attach_partner()` only succeeds while the order is still dispatchable and unassigned, under the order lock; otherwise the dispatcher releases the claim. Cancel detaches the partner inside the same lock it changes status under. Whichever runs first, the partner ends up free.

---

## Question 4: "Who can cancel, and when?"

### 🎯 Answer

Make it a table, not `if` chains:

| From | Customer | Restaurant | Partner | System / support |
|---|---|---|---|---|
| PLACED | ✅ full refund | (reject instead) | ❌ | ✅ |
| ACCEPTED | ✅ (fee policy optional) | ✅ e.g. stock-out | ❌ | ✅ |
| PREPARING / READY | ❌ | ✅ | ❌ | ✅ |
| PICKED_UP | ❌ | ❌ | ❌ | ✅ (lost/damaged) |

Partners never cancel orders; they unassign and the order is re-dispatched. The refund amount is a separate `RefundPolicy` decision `(state_at_cancel, actor) -> amount`, so product can change it without touching transitions.

---

## Question 5: "Add batching: one partner carries two orders."

### 🎯 Answer

Only from the same restaurant, only before pickup, up to a capacity. That's:

1. `BatchingStrategy.rank`: partners already heading to this restaurant with spare capacity first, then nearest idle.
2. `max_orders_per_partner` passed into `try_claim`, so capacity is enforced at the CAS.
3. `mark_picked_up` closes the batch.

Real systems also bound the detour (second drop-off adds at most N minutes to the first customer's ETA) and wait a few seconds to accumulate a batch; both are strategy concerns. Cross-restaurant batching (pick A, pick B, drop both) is a vehicle-routing problem, solved offline-ish per geo cell every few seconds rather than greedily per order.

---

## Question 6: "Implement pricing. Where do surge and coupons go?"

### 🎯 Answer

An ordered chain of `PricingRule`s, each appending a labelled line. Order is the specification: items → packaging → delivery → surge (reads delivery) → coupon (reads items) → tax (on discounted food). Edge cases the interviewer is listening for:

- `Decimal`, never `float`; quantise per line with half-up and sum quantised lines so the receipt adds up.
- Coupon: min subtotal, percentage cap, never more than the food subtotal; total floored at zero.
- Surge on delivery fee only.
- The quote shown at checkout must equal what's charged: re-price at placement and, if it differs from what the client displayed (send the quoted total), reject with "prices changed" rather than silently charge more.

---

## Question 7: "Notifications are slow and sometimes fail. Does that block the order?"

### 🎯 Answer

No. Observers run after the order lock is released and each is wrapped so one failing subscriber doesn't break the others or the transition. In the service version, the order service writes the status change and an outbox row in one transaction; a relay publishes to Kafka; notification, tracking and analytics consume independently. Events carry a per-order `seq`, so out-of-order delivery is detectable and stale updates are dropped.

---

## Question 8: "Restaurant never responds."

### 🎯 Answer

A delayed job (timer wheel / delay queue / Kafka delay topic) fires at T+3 min and calls `reject(order_id, Actor.SYSTEM)`. If the restaurant accepted meanwhile, the transition fails with `InvalidTransitionError` and the job is a no-op. That's the general pattern: timeouts are just another actor racing on the same CAS-protected state machine. Refund follows from `REJECTED`.

---

## Question 9: "Partner's phone dies after accepting."

### 🎯 Answer

Detect via heartbeat/location silence (e.g. no ping for 60 s while assigned). Before pickup: unassign (clear `partner_id` only if it still matches, under the order lock), release, re-dispatch with that partner excluded. After pickup: no automatic reassignment because the food is with them; escalate to support, who may cancel as `SYSTEM` and re-create the order.

---

## Question 10: "How would you test this?"

### 🎯 Answer

- **Pure units:** each pricing rule with exact `Decimal` expectations; strategies on hand-built snapshots; the transition table exhaustively (every `(from, to, actor)` triple: allowed or which error).
- **Concurrency:** N threads, same idempotency key → one order, one charge; M orders × K partners concurrently → each partner at most `max_orders`; cancel vs start-preparing → exactly one wins.
- **Deterministic interleavings:** inject a strategy that cancels the order inside `rank()` to force the cancel-between-rank-and-claim window, rather than hoping a thread race hits it.
- **Fakes at the ports:** `FakePaymentGateway` with failure injection; recording observer.
- In services: contract tests on events, and a chaos test killing the dispatcher mid-saga.

---

## ⚠️ Common mistakes

- Money as `float`; or rounding only the final total so lines don't sum to it.
- State changes via public setters (`order.status = ...`) scattered across services.
- Check-then-act dispatch: `if partner.available: partner.available = False` without a lock or CAS.
- One global lock around the whole service "for safety".
- Cancel without releasing the partner or without refunding; or refund twice on retried cancels.
- Calling the PSP or notification fan-out while holding the order lock.
- Reading live menu prices when rendering an old order.
- Idempotency keyed only on the key, not scoped per customer, or without a request fingerprint.

---

## 🎚️ Senior vs Staff signal

- **Senior:** clean entities, the state machine with actor rules, strategy for assignment, Decimal pricing, a correct lock or CAS for assignment, idempotent placement, good tests.
- **Staff:** treats timeouts, cancellations and dispatch as concurrent actors on one CAS-protected state machine; separates ranking from claiming; names the cancel-vs-dispatch window and closes it; explains how the in-process design maps to a saga (payment ↔ order ↔ dispatch) with an outbox and compensations; discusses partition-by-geo dispatch and what's lost (cross-cell candidates) and how to recover it; reasons about product policy (cancellation fees, surge on fee not food) as data the business owns.
