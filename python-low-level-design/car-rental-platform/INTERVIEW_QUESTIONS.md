# Car Rental Platform - Interview Questions & Answers

> **Target Level:** Senior / Staff Engineer  
> **Evaluation Focus:** Availability modelling, overlap checks, double-booking prevention under concurrency, reservation lifecycle, search at scale

---

## Question 1: Core Design — "When is a car free?"
**Interviewer:** *"Design a car rental platform where we own the fleet. Users book by the hour or the day, and we show availability for the next week."*

### 🎯 Answer

**Domain model:**
```
Vehicle (type, rates, location, physical status)
   └── VehicleSchedule: sorted, non-overlapping [start, end) blocks
           ├── RESERVATION block (+ turnaround buffer, + hold expiry while unpaid)
           └── MAINTENANCE block
Reservation (customer, vehicle, pickup, dropoff, quote, status) ── owns one RESERVATION block
```

**Decisions:**
1. **Exact half-open intervals are the source of truth.** Hourly slots and the 7×24 grid are *derived* views. Rounding stored bookings to slots either misses real overlaps (round down) or wastes inventory (round up).
2. **Overlap test:** `[a, b)` and `[c, d)` overlap iff `a < d and c < b`. With sorted non-overlapping blocks it's one bisect, O(log n).
3. **Reserve = atomic check-and-insert** per vehicle (`try_block` under the vehicle's lock; in Postgres an exclusion constraint).
4. **State machine:** `PENDING (hold, TTL) → CONFIRMED → IN_PROGRESS → COMPLETED`, plus `CANCELLED`, `EXPIRED`.
5. **`VehicleStatus` is physical only** (on the lot / rented). A car booked for Friday is still on the lot today.

**Weekly view response** (projection of the intervals):
```json
{"vehicle_id": "V1", "week_start": "2025-01-13",
 "days": [{"date": "2025-01-14", "day_name": "Tue",
           "available_hours": [0,1,2,3,4,5,6,7,8,9,13,14,15,16,17,18,19,20,21,22,23],
           "total_available": 21, "is_fully_booked": false}]}
```

---

## Question 2: Preventing Double-Booking (Deep Dive)
**Interviewer:** *"Two users book overlapping times on the same car at the same moment. What stops both succeeding?"*

### 🎯 Answer

**The bug to name first:** `SELECT` overlapping rows → 0 → `INSERT`. Both transactions see 0 and both insert. Under Postgres `REPEATABLE READ` (snapshot isolation) this is classic write skew; neither row conflicts with the other at the row level.

**Fixes, best first:**

| Option | How | Notes |
|--------|-----|-------|
| **Exclusion constraint** | `EXCLUDE USING gist (vehicle_id WITH =, block_range WITH &&) WHERE (active)` | The INSERT itself fails (`23P01 exclusion_violation`). Works at READ COMMITTED. Needs `btree_gist` for the `=` on a UUID |
| **Lock the parent row** | `SELECT ... FROM vehicles WHERE id = ? FOR UPDATE`, then check overlaps, then insert | Portable (MySQL too). Serialises bookings *per car*, which is fine: contention is per car |
| **SERIALIZABLE** | Postgres SSI detects the read/write dependency and aborts one transaction at commit | Correct, but you must retry on `40001`, and it's easy to break by reading through a different path |
| **Slot rows + unique key** | One row per (vehicle, hour) with a UNIQUE constraint; insert all slots in one txn | Works anywhere, but forces hourly rounding and N inserts per booking |

**Two details people miss:**
- The constraint must be **partial**: `WHERE (active)` or `WHERE (status IN ('PENDING','CONFIRMED','IN_PROGRESS'))`. Without it a *cancelled* reservation blocks its slot forever.
- Reservations and maintenance must be in **the same constrained table** (e.g. `vehicle_blocks`). Two tables with two separate exclusion constraints don't stop a booking overlapping a maintenance window.

The LLD mirrors the constraint: `AvailabilityCalendar.try_block()` does check-and-insert under the vehicle's lock. Search results are explicitly a hint.

---

## Question 3: "Now add a hold while the customer pays."

### 🎯 Answer

Insert the block immediately in `PENDING` with `hold_expires_at = now + 10 min`. The car is invisible to others while they pay.

- **Confirm** only if the hold is still live; otherwise `EXPIRED` and "please search again". Don't let a late confirm succeed just because nobody else happened to grab the slot, or behaviour depends on timing.
- **Expiry without cron dependence:** in memory, expired holds are purged lazily on the next read/write of that car's schedule (`purge_expired`), and `expire_holds()` sweeps statuses.
- **In Postgres** a constraint predicate can't reference `now()` (must be immutable). So: a sweeper sets `active = false` on lapsed holds every few seconds, and on an exclusion violation the booking path checks whether the blocker is a lapsed hold, expires it with a conditional UPDATE (`... WHERE id=? AND status='PENDING' AND hold_expires_at < now()`), and retries once.
- **Payment idempotency:** the payment call carries the reservation id as the idempotency key; a retried confirm never double-charges.

---

## Question 4: "Add a turnaround buffer between rentals."

### 🎯 Answer

Each reservation blocks `[pickup, dropoff + turnaround)`. Put it in the calendar, not the UI, so search, booking and "next free" all agree. In Postgres store the computed `block_end` column (written by the app) and constrain on `tstzrange(pickup, block_end)`. You can't use `return_datetime + interval '30 min'` inside the constraint because `timestamptz + interval` is only STABLE, not IMMUTABLE.

---

## Question 5: Hourly vs Daily Granularity and Pricing
**Interviewer:** *"Why hourly? How do you price?"*

### 🎯 Answer

| Aspect | Hourly | Daily |
|--------|--------|-------|
| Utilisation | Higher: gaps can be sold | Lower: a 2 h rental burns a day |
| Grid per car per week | 168 cells (21 bytes as a bitmap) | 7 cells |
| Operations | More handovers, more cleaning | Fewer |

Pricing as implemented:
```python
billable = max(1, ceil((dropoff - pickup) / 1h))           # every started hour
hourly   = full_days * daily_rate + min(rest_hours * hourly_rate, daily_rate)   # cap per 24 h
daily    = ceil(billable / 24) * daily_rate
discount = WeeklyDiscountPricing(base)                      # -10% at 7 d, a further -15% at 30 d
```
The cap is a `min`, not a `max`. `max(hourly × h, daily)` would charge a full day for a two-hour rental.

Store the **quote** on the reservation (prices change). On return: charge the quote, or re-price on actual hours if later than the grace period (15 min). Money is `Decimal` / `NUMERIC(10,2)`, never float.

---

## Question 6: Search & Display at Scale
**Interviewer:** *"How do you serve the 7-day availability grid fast?"*

### 🎯 Answer

- **Write path stays simple and correct** (constraint on `vehicle_blocks`).
- **Read model:** a per-vehicle 168-bit bitmap per week (bit `day*24 + hour` = 1 if that full hour is free), stored in Redis (`fleet:weekly_bitmap:{vehicle_id}`). Rebuild it from the vehicle's blocks on every block insert/delete (via outbox/CDC event), plus a periodic full rebuild to heal drift.
- **Query:** "free 10:00–14:00 Tuesday" on the grid is `(bitmap & mask) == mask`. That's a *pre-filter*; partial hours (10:30 starts) and the final decision always go back to the source of truth.
- **Size:** 1K cars × 21 bytes ≈ 21 KB. Even 100K cars is ~2 MB. This is not a scale problem; the point is latency and keeping the DB off the browse path.
- **Staleness:** a user can see a car that was just taken. Acceptable, because booking re-checks atomically and returns `next_free`/alternatives.

```python
def free_for(bitmap: int, day: int, start_hour: int, end_hour: int) -> bool:
    mask = ((1 << (end_hour - start_hour)) - 1) << (day * 24 + start_hour)
    return bitmap & mask == mask
```

---

## Question 7: Maintenance Scheduling

Maintenance is a block of another kind in the same schedule (and the same constrained table). It can't be placed over a booking, and bookings can't be placed over it. Mileage-based service (every N km) is scheduled into the *largest low-demand gap* before the threshold; if no gap exists, the ops tool shows which bookings to move to a same-class car.

---

## Question 8: Failure Handling & Edge Cases

| Scenario | Handling |
|----------|----------|
| Client retries `POST /reservations` after a timeout | `Idempotency-Key` header → `reservations.idempotency_key UNIQUE`; return the existing hold |
| Payment succeeds, confirm call is lost | Payment webhook also confirms (idempotent on reservation id); hold TTL slightly longer than the payment timeout |
| Hold lapses while the payment is in flight | Confirm fails → void the authorisation; never confirm on an expired hold |
| Late return collides with the next booking | Detect at `dropoff + grace` ("car not back"), not at the next pickup; offer the next customer a same-class swap or upgrade, charge the late customer per policy |
| Car breaks down mid-rental | Close the rental early, open a maintenance block, re-book affected future reservations onto same-class cars |
| No-show | At `pickup + 30 min` CONFIRMED → NO_SHOW, release the block, apply the fee |
| DST transition | Store UTC `timestamptz`; days in local time have 23 or 25 hours, so the grid must be built from local midnights, not "24 × hours" |

---

## Question 9: Testing Strategy

- **Overlap edges:** touching intervals allowed; sub-hour overlaps caught on each side; containment both ways.
- **Projection:** a 10:30 booking makes the 10:00 hour unavailable but not 12:00; bitmap bits match `free_hours`.
- **Pricing:** cap at daily, multi-day remainder, discount thresholds, exact `Decimal`s.
- **Lifecycle:** every illegal transition raises; hold expiry with an injected clock; confirmed bookings never expire.
- **Concurrency:** 12 threads on mutually overlapping ranges → exactly 1 winner (repeat 20×); 12 threads on disjoint ranges → all 12 succeed (proves the lock isn't over-broad); confirm-vs-cancel → calendar agrees with the final status.
- **Mutation check:** replace `try_block` with a racy check-then-insert and confirm the concurrency test fails (it does).

---

## Question 10: Design Patterns

| Pattern | Where (in code) |
|---------|-----------------|
| **Strategy** | `RentalPricing` (`HourlyRentalPricing`, `DailyRentalPricing`) |
| **Decorator** | `WeeklyDiscountPricing` wraps any strategy |
| **State machine (table-driven)** | `_TRANSITIONS` + `Reservation.move_to()` |
| **Facade** | `CarRentalService` |
| **CQRS-lite** | Writes go through `try_block`; reads (`SearchService`, hourly grid) are projections |

---

## ⚠️ Common Mistakes

1. SELECT-then-INSERT for availability, or "solving" it with a global lock across all cars.
2. Storing bookings as rounded hour slots, so a 10:00–10:30 booking blocks nothing (or a 10:30 start blocks an hour it shouldn't).
3. Closed intervals: rejecting a 12:00 pickup after an 11:00–12:00 rental.
4. An exclusion constraint without a `WHERE` clause, so cancelled bookings block the car forever.
5. Maintenance in a separate table with its own constraint, so bookings can overlap maintenance.
6. A `RESERVED` vehicle status set at booking time for a rental next week.
7. `max(hourly, daily)` instead of a daily cap; float money; recomputing the price at return from today's rates.
8. Hold expiry that only works if a cron job runs; confirming a hold that has already lapsed.
9. Using `datetime.now()` inside the domain, which makes expiry and "no past bookings" untestable.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** exact interval model with a correct overlap test, atomic check-and-insert, a state machine with holds, Decimal pricing with a daily cap, and tests including a concurrency test. Knows the Postgres exclusion constraint.
- **Staff:** all of that, plus: makes the constraint partial and puts maintenance in the same table; explains why `now()` can't be in the constraint and designs hold expiry around it; separates the correctness path from the cached 7×24 read model and says staleness there is fine; handles late returns *before* they collide; thinks about DST, idempotency across payment callbacks, and which consistency each piece actually needs. Recognises that 1K–100K cars is not a data-volume problem, so doesn't shard Postgres prematurely.
