# Movie Ticket Booking System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)
> **Evaluation Focus:** Concurrency, race conditions, hold expiry, payments, scalability

---

## Question 1: Core Design
**Interviewer:** *"Design a ticket booking system like BookMyShow."*

### 🎯 Expected Answer

**Domain model:**
```
Theatre ─< Screen ─< Seat            (layout: immutable)
Movie ─< Show >─ Screen
Show ─< ShowSeat (status, booking_id, hold_expires_at)   (inventory: per show)
Booking ─< ShowSeat;  Booking ── Payment
```

**Key decision: seat state is per show.** A `Seat` is a position in a screen's layout. A `ShowSeat` is that seat *for one screening*, and only it has a status. Putting status on `Seat` makes every show on the screen share one seat map. That bug was in this repo's earlier version.

**Seat state machine:**
```
AVAILABLE ──hold──▶ HELD(booking, expires_at) ──confirm──▶ BOOKED
    ▲                   │ cancel / expiry                    │ cancel (+refund)
    └───────────────────┴────────────────────────────────────┘
```

**Why a HELD state at all?** Payment takes minutes. Without a hold, two users can both reach the payment page for one seat, and one of them pays for nothing. The hold is a lease: exclusive, and it times out so abandoned checkouts don't lock seats forever.

---

## Question 2: Concurrency & Double-Booking Prevention
**Interviewer:** *"Two users click the same seat at the same moment. Walk me through it."*

### 🎯 Answer (in-process)

Check-and-hold must be one atomic step, so it happens under a lock. With multiple seats per request:

```python
with locked_in_order(seats):            # sorted by seat id
    taken = [s for s in seats if not s.is_free(now)]
    if taken: raise SeatUnavailable(taken)
    for s in seats: s.hold(booking_id, now + ttl)
```

- **Lock granularity:** one lock per show is simplest and correct (a show has a few hundred seats, and contention is only within one show). Per-seat locks let disjoint requests in the same show run in parallel but require **lock ordering**.
- **Lock ordering:** user 1 wants `{A1, A2}`, user 2 wants `{A2, A1}`. Taking locks in request order lets each hold one and wait on the other forever. Every request locks in the same global order (sorted seat id), so a cycle can't form.
- **All-or-nothing:** check every seat before changing any. Never hold some seats and then fail on the rest.

### 🎯 Answer (distributed: many app servers, one database)

The database is the arbiter. One conditional update does check-and-hold atomically:

```sql
UPDATE show_seats
SET status = 'HELD', booking_id = $booking, hold_expires_at = now() + interval '10 minutes',
    version = version + 1
WHERE show_id = $show
  AND seat_id = ANY($seats)
  AND (status = 'AVAILABLE' OR (status = 'HELD' AND hold_expires_at <= now()))
RETURNING seat_id;
-- if fewer rows than requested: ROLLBACK (all-or-nothing)
```

Concurrent multi-row updates can still deadlock in Postgres if they lock rows in different orders (Postgres detects it and aborts one transaction with an error). To avoid that, lock in a fixed order first:

```sql
SELECT seat_id FROM show_seats
WHERE show_id = $show AND seat_id = ANY($seats)
ORDER BY seat_id
FOR UPDATE;            -- same lock order for everyone (add NOWAIT to fail fast)
```

That is exactly `locked_in_order()` from the LLD, expressed as row locks.

**Where Redis fits:** as a **fast pre-filter**, not the source of truth. `SET seat:{show}:{seat} {booking} NX PX 600000` per seat can turn away obviously-taken seats before they reach the DB. Two cautions:
- A Redis lock is a lease. A GC pause or network delay can let it expire while the holder still thinks it owns it, and Redis replication is asynchronous, so a failover can lose a lock. Correctness must come from the DB's conditional update (the `booking_id` on the row works like a fencing token).
- Release with compare-and-delete in Lua (`if GET == me then DEL`). A plain `GET` then `DEL` can delete someone else's lock between the two calls.

A per-show distributed mutex (`SET show:123:lock … NX`) serialises every booking for a show across the fleet. That is a throughput cap, not a safety requirement: row-level conditional updates already serialise only the conflicting seats.

---

## Question 3: Hold Expiry
**Interviewer:** *"How do holds expire? What if the expiry job is down?"*

### 🎯 Answer

- **Lazy expiry is the correctness mechanism.** A held seat whose `hold_expires_at <= now` counts as free in the availability check itself (the `OR` clause above; `ShowSeat.is_free` in code). Expiry is exact to the instant, and it does not depend on a job running.
- **The sweeper is housekeeping:** marks lapsed bookings `EXPIRED`, releases their rows, and refreshes cached seat maps. It must only release seats still held **by that booking** (`WHERE booking_id = $b AND status = 'HELD'`), never seats someone has since re-held.
- **Clocks:** with many app servers, compare against the DB's `now()`, not each server's clock.
- **UX:** show a countdown; optionally extend once when the user enters payment, up to a hard cap.

---

## Question 4: The payment race
**Interviewer:** *"The user's hold expires at 10:00. Their payment succeeds at 10:00:05. Meanwhile someone else held the seat at 10:00:01. What happens?"*

### 🎯 Answer

This is the question that separates a correct design from a demo.

1. **Never hold a lock (or a DB transaction) across the payment call.** It takes seconds and can time out.
2. **Charge idempotently**, keyed by booking id, so retries never double-charge.
3. **Confirm with a conditional write that re-checks ownership and expiry:**
   ```sql
   UPDATE show_seats SET status = 'BOOKED'
   WHERE booking_id = $b AND status = 'HELD' AND hold_expires_at > now();
   -- rows updated == seats in booking → CONFIRMED; else → EXPIRED + refund
   ```
4. In the scenario, the second user's hold changed `booking_id`, so the first user's confirm updates 0 rows. The booking expires and the charge is refunded automatically. The seat is never sold twice.
5. Payment gateways also deliver results asynchronously (webhooks) and sometimes twice. The webhook handler runs the same idempotent confirm, so a duplicate does nothing.

The LLD does exactly this (`pay_and_confirm`), and `test_hold_lapses_during_payment_seat_resold_and_charge_refunded` forces the interleaving.

**Alternative policy:** authorise at payment time and capture only after confirm succeeds; on failure, void the authorisation instead of refunding. That's cheaper and invisible to the user, if the gateway supports auth/capture.

---

## Question 5: Dynamic Pricing
**Interviewer:** *"How would you implement surge pricing for popular shows?"*

### 🎯 Answer

Strategy pattern with composition, `Decimal` money, and **price snapshotting**:

```python
class DemandPricing(PricingStrategy):
    def price(self, base, show, seat):
        fill = show.sold_fraction()
        return base * (Decimal("1.5") if fill > Decimal("0.8") else
                       Decimal("1.2") if fill > Decimal("0.5") else 1)

pricing = CompositePricing(PeakHourPricing(), WeekendPricing(), DemandPricing())
```

- **Snapshot at hold time** (`Booking.line_prices`): the price shown when the user selected seats is the price charged, even if demand pricing moves during checkout.
- **Order of composition matters** when strategies mix multipliers with flat fees; define it explicitly.
- **Round once per line item** (`ROUND_HALF_UP` to paise), then sum. Rounding the total differently from the line items creates 1-paisa mismatches on invoices.
- Never use float for money: `0.1 + 0.2 != 0.3`.

---

## Question 6: Cancellation & Refund

```python
REFUND_TIERS = [            # (min hours before show, refund fraction), checked in order
    (48, Decimal("1.00")),
    (24, Decimal("0.75")),
    (6,  Decimal("0.50")),
    (2,  Decimal("0.25")),
]

def refund_fraction(hours_before: float) -> Decimal:
    for min_hours, fraction in REFUND_TIERS:
        if hours_before >= min_hours:
            return fraction
    return Decimal("0")
```

- Cancel = release seats + `CANCELLED` (under the seat locks) and then refund **outside** the lock. In production, write the refund to an outbox in the same DB transaction so it can't be lost if the process dies after the commit.
- Refunds go through the gateway with their own idempotency key (`refund:{booking_id}`).
- Released seats return to inventory immediately. Bump a version on the show's seat map so caches refresh.

---

## Question 7: Flash sales (100K users, one release)
**Interviewer:** *"Tickets for a blockbuster open at 10:00. What breaks?"*

### 🎯 Answer
- **Hot rows:** everyone wants the same few hundred `show_seats` rows. A DB handles this fine *if* each attempt is one short conditional update; it does not if each attempt holds locks across user think-time or payment.
- **Admission control / virtual waiting room:** admit users to the seat map at the rate the booking path can serve (a token bucket per show). Everyone else waits in a queue with a position. This protects the DB and is fairer than whoever retries fastest.
- **Seat map reads:** serve from a cache refreshed every second or two; stale is fine because the hold is authoritative. Push updates over WebSocket/SSE only for the show being viewed.
- **Per-user limits:** max seats per booking and max concurrent holds per user, to stop bots hoarding inventory with holds they never pay for.
- **Don't queue the writes asynchronously** unless you must: "your booking is pending" for minutes is a worse experience than a fast, honest "seat taken, pick another". Queueing helps most for "best available" allocation, where a single allocator per show can hand out seats without contention.

---

## Question 8: Testing strategy

- **Fake clock:** pin expiry to the second (`9:59` held, `10:00` free).
- **Gateway hook** that advances time and lets another user take the seat *during* `charge()`: deterministic reproduction of the payment race.
- **Contention:** 32 threads, one seat → exactly one hold.
- **Random overlapping multi-seat requests** from 16 threads, with cancels: afterwards every held seat belongs to exactly one active booking and failed requests hold nothing.
- **Deadlock:** opposite-order requests in a loop with a join timeout; remove the `sorted()` and it hangs (verified).
- **Confirm vs cancel race:** run 50 times; seat state, booking state and charges/refunds must agree.
- `sys.setswitchinterval(1e-6)` in concurrency tests makes thread switches frequent enough to expose races.

---

## Question 9: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `PricingStrategy`, `PaymentGateway` | Swappable pricing rules and payment providers |
| **Composite** | `CompositePricing` | Combine pricing rules without a class per combination |
| **Facade** | `BookingService` | One entry point for search, hold, pay, cancel |
| **State machine** | `SeatStatus`, `BookingStatus` | Legal transitions only; checked under locks |

---

## ⚠️ Common mistakes

1. **Seat status on the screen's seat** instead of per show.
2. **Check then act without a lock** (or a non-conditional `UPDATE`).
3. **Locking seats in request order**: deadlocks on overlapping requests.
4. **Partial holds:** holding A1, then failing on A2 and leaving A1 held.
5. **Holding a lock or DB transaction across the payment call.**
6. **Confirming without re-checking ownership and expiry**: the late payer gets a seat someone else now holds.
7. **Holds that only expire if a cron job runs.**
8. **A sweeper that releases by seat id** and frees a seat someone else has re-held.
9. **Float money**, and recomputing the price at payment time instead of snapshotting it.
10. **Redis lock as the source of truth**, released with `GET` then `DEL`.

---

## 🎚️ Senior vs Staff signal

- **Senior:** per-show seat inventory, atomic all-or-nothing holds, lock ordering, expiry, idempotent payment, a conditional SQL update for the distributed case, and tests that prove each.
- **Staff:** names the payment-after-expiry race unprompted and closes it with ownership re-check + refund (or auth/capture); keeps one source of truth (the DB) and treats Redis and queues as load-shedding; designs flash-sale admission control around the real bottleneck (hot rows and think-time, not CPU); separates the read path (stale-tolerant seat maps) from the write path; and states policies (late payment, cancellation tiers, per-user limits) as product decisions with trade-offs, not as code details.
