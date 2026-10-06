# 🏗️ Car Rental Platform — High-Level Design

> **Target Level:** Senior/Staff Engineer  
> **Focus:** Fleet availability management, hourly booking, capacity planning, search architecture

---

## 1. SYSTEM OVERVIEW

**Purpose:** Car rental platform where we own the fleet. Users book cars by the hour or day. System must show accurate real-time availability for the next 7 days.

**Scale:** 1K vehicles, 50 locations, ~5K bookings/day, 100K members

**Users:** Customers (renters), Branch staff, Fleet managers, Maintenance team

**Use Cases:** Browse fleet availability (7-day view), Search by date/time/location, Book hourly/daily, Start/return rental, Fleet management

**Constraints:** 
- No double-booking (atomic slot reservation)
- <200ms availability check for search
- Support hourly (min 1h) and daily (min 24h) bookings
- Show 7-day lookahead availability per vehicle
- 99.9% uptime, eventual consistency for fleet dashboard

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Web/Mobile App (Customer)       Admin/Fleet Dashboard
      │                                │
      └────────────┬───────────────────┘
                   │
           ┌───────▼───────┐
           │   API Gateway   │
           │ (REST + WebSocket)│
           └───────┬───────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼──────┐ ┌───▼──────┐ ┌───▼──────┐
│ Search   │ │ Booking  │ │ Fleet    │
│ Service  │ │ Service  │ │ Service  │
│ (Go)     │ │ (Go)     │ │ (Python) │
└───┬──────┘ └───┬──────┘ └───┬──────┘
    │            │            │
    └────────────┼────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼───────┐  ┌──────▼──────────┐
│  PostgreSQL   │  │  Redis          │
│ (source of    │  │ (7×24 bitmaps,  │
│  truth, EXCL. │  │  read model)    │
│  constraint)  │  └──────▲──────────┘
└───────┬───────┘         │
        └── outbox/CDC ───┘  (rebuild bitmaps on every block change)
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/car-rental-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Car Rental Sequence — Search → Book → Pickup → Return → Payment. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. AVAILABILITY-CENTRIC DESIGN

### 3.1 Core Problem: When is a car free?

**Key insight:** A vehicle is available for `[T1, T2)` if no *active* block (pending hold, confirmed or in-progress reservation, maintenance — each extended by the turnaround buffer) overlaps it. Two half-open ranges `[a, b)` and `[c, d)` overlap iff `a < d and c < b`.

```
Vehicle V1 timeline:
        Available ────[Booked]───Available────[Booked]───Available
Time:   08:00       10:00  12:00         14:00 16:00 18:00      20:00

Query: Is V1 available for 14:00-16:00?
→ Yes: no overlap with existing bookings
```

**Hourly granularity is a view, not the storage.** Bookings are stored as exact ranges; the 24 hourly cells per day shown in the UI are computed from them (an hour is "free" only if the whole hour is free). Storing rounded slots as the truth either misses real overlaps or wastes inventory.

### 3.2 Search Architecture

```
User Search Request: {pickup: 2024-01-15 10:00, return: 2024-01-15 14:00, type: SUV}
    │
    ├── 1. Query Redis/PostgreSQL cache: available_vehicles:{date}:{hour}
    ├── 2. Filter by availability (check all 4 hourly slots)
    ├── 3. Filter by vehicle type (SUV)
    ├── 4. Filter by location
    ├── 5. Sort by: price → rating → distance
    └── 6. Return results with availability calendar per vehicle
```

**Search Service (Go):**
- Redis cache: `available:{vehicle_id}:{YYYY-MM-DD}:{HH}` → boolean for each hour slot
- Cache TTL: 30 seconds (bounded staleness acceptable for availability display)
- On cache miss: query PostgreSQL `availability_slots` table
- Write-through cache: On booking confirm, invalidate affected cache entries

### 3.3 Booking Workflow

```
1. User selects vehicle + time range (from a possibly stale search result)
2. One transaction at READ COMMITTED, no pre-check:
   a. INSERT reservation (status = 'PENDING', hold_expires_at = now() + 10 min, idempotency_key)
   b. INSERT vehicle_blocks row [pickup, return + turnaround) — the partial EXCLUDE constraint
      `no_overlapping_blocks` rejects any overlap with SQLSTATE 23P01
   c. INSERT outbox row (reservation.held)
   d. COMMIT
3. On 23P01: if the blocker is a lapsed hold, expire it and retry once; else return 409 with
   the next free window and same-class alternatives
4. Customer pays (payment idempotency key = reservation id) → confirm: PENDING → CONFIRMED
   only if the hold is still live (conditional UPDATE ... WHERE status='PENDING' AND hold_expires_at > now())
5. Outbox relay publishes events; bitmap builder refreshes Redis for that vehicle
```

**Isolation level:** READ COMMITTED is enough because the exclusion constraint is checked by the index on insert, regardless of snapshots. A plain `SELECT ... then INSERT` would need `SERIALIZABLE` (SSI aborts one of two conflicting transactions with `40001`, which you must retry) or a `SELECT ... FOR UPDATE` on the vehicle row. The constraint is simpler and can't be bypassed by a code path that forgets the check.

---

## 4. KEY COMPONENTS

### Search Service (Go)
- **Availability Calendar API:** `GET /api/vehicles?pickup=...&return=...&type=...`
- **Weekly Browse API:** `GET /api/fleet/availability?start_date=...` (7-day view)
- **Vehicle Detail API:** `GET /api/vehicles/{id}/availability?date=...` (hourly breakdown)
- Caches pre-computed availability bitmaps in Redis (24 bits per vehicle per day → 3 bytes × 1000 × 7 = 21KB total)

**🔴 Staff-level Question:** *"How do you handle a user searching for vehicles at 2 AM when no branches are open?"*

**✅ Answer:** The availability system is time-agnostic — it checks hourly slots regardless of branch hours. However, the search layer enforces business rules:
```sql
-- Enforce branch operating hours in search (compare in the branch's local time)
SELECT v.* FROM vehicles v
JOIN branches b ON v.branch_id = b.id
WHERE NOT EXISTS (... overlapping active vehicle_blocks ...)
  AND (:pickup AT TIME ZONE b.tz)::time BETWEEN b.opening_time AND b.closing_time
  AND (:return AT TIME ZONE b.tz)::time BETWEEN b.opening_time AND b.closing_time
  -- Or allow after-hours return to a key drop, with an inspection the next morning
```

### Booking Service (Go)
- Creates/confirms/cancels reservations
- Validates availability at booking time (double-check pattern)
- Handles payment pre-authorization
- Manages reservation lifecycle: PENDING → CONFIRMED → IN_PROGRESS → COMPLETED

**🔴 Staff-level Question:** *"How do you prevent race conditions where two users book the same vehicle for overlapping times?"*

**✅ Answer:** Multi-layered approach:
1. **Database exclusion constraint (the guarantee):** one table holds every block (reservations *and* maintenance), constrained only while active:
   ```sql
   ALTER TABLE vehicle_blocks ADD CONSTRAINT no_overlapping_blocks
   EXCLUDE USING gist (
       vehicle_id WITH =,
       tstzrange(block_start, block_end) WITH &&
   ) WHERE (active);
   ```
   Without `WHERE (active)` cancelled bookings block forever; with maintenance in a separate table, bookings could overlap maintenance.
2. **Search-time check is only a hint** for UX; never rely on it.
3. **Idempotency key:** a retried submit returns the existing reservation instead of creating a second hold.
4. **Per-vehicle serialization is the right granularity:** contention is per car, so a global lock or SERIALIZABLE on everything buys nothing.

### Fleet Service (Python)
- Manages vehicle inventory (add/remove/status)
- Maintenance scheduling (blocks availability during service)
- Vehicle redistribution between branches
- Fleet utilization analytics

---

## 5. DATA MODEL

### Core Tables

```sql
-- See DB_SCHEMA.md for the complete DDL

-- Key tables:
vehicles          -- Fleet inventory with hourly/daily rates, location, features
customers         -- User accounts with loyalty program
branches          -- Physical locations with operating hours
reservations      -- Lifecycle, quote, hold expiry, idempotency key
vehicle_blocks    -- Every reservation/maintenance range; partial EXCLUDE constraint lives here
availability_slots -- Derived hourly read model (async, may lag)
maintenance_schedule -- Maintenance jobs (each also writes a vehicle_blocks row)
payments          -- Payment transactions with idempotency
```

### Redis Cache Schema

```ascii
available:{vehicle_id}:{YYYY-MM-DD}:{HH}  → BOOL (1/0)
fleet:available_count:{YYYY-MM-DD}:{HH}   → INT (total available in city)
fleet:weekly_summary:{vehicle_id}         → HASH (7×24 bitmap, 21 bytes)
reservation:{id}:state                    → HASH (current reservation state)
```

---

## 6. SEARCH & DISPLAY UX

### Browse Weekly View (API Response)

```json
{
  "week_start": "2024-01-15",
  "week_end": "2024-01-21",
  "fleet": [
    {
      "vehicle": {
        "id": "V1", "make": "Toyota", "model": "Fortuner",
        "type": "SUV", "hourly_rate": 12.0, "daily_rate": 80.0,
        "location": "Bangalore Airport"
      },
      "weekly_availability": {
        "vehicle_id": "V1",
        "days": [
          {"date": "2024-01-15", "day_name": "Mon",
           "available_hours": [9,10,11,14,15,16],
           "total_available": 6, "is_fully_booked": false},
          {"date": "2024-01-16", "day_name": "Tue",
           "available_hours": [8,9,10,11,12,13,14,15,16,17],
           "total_available": 10, "is_fully_booked": false},
          ...
        ]
      },
      "total_weekly_available_hours": 45
    }
  ]
}
```

### Search Response

```json
{
  "pickup": "2024-01-15T10:00:00",
  "return": "2024-01-15T16:00:00",
  "results": [
    {
      "vehicle": { "id": "V1", "make": "Toyota", "model": "Fortuner", ... },
      "estimated_cost": 72.0,  // 6 hours × $12/hr
      "distance_km": 1.5,
      "rating": 4.8
    }
  ]
}
```

### Frontend Rendering Strategy

| Component | Data Source | Update Frequency |
|-----------|-------------|-----------------|
| Fleet overview (7-day grid) | `GET /api/fleet/availability` | On page load |
| Vehicle detail (hourly slots) | `GET /api/vehicles/{id}/availability?date=` | On date select |
| Search results | `GET /api/vehicles?pickup=...&return=...` | On search |
| Real-time availability changes | WebSocket push | Event-driven (booking confirmed/cancelled) |

---

## 7. STAFF-LEVEL INTERVIEW QUESTIONS

### Q1: "Design an availability system for a car rental fleet where users book by the hour."

**Key design decisions:**
- **Time block granularity:** 1 hour blocks. Longer rentals occupy contiguous blocks.
- **Availability matrix:** Pre-computed 7-day × 24-hour bitmap per vehicle (168 bits = 21 bytes per vehicle)
- **Lookup:** O(1) bitwise pre-filter: with 1 = free, `(bitmap & mask) == mask` for the requested whole hours
- **Update:** rebuild a vehicle's bitmap from its blocks on every block change (event-driven), not by flipping bits in the request path — rebuilding is idempotent, flipping isn't
- **Race condition:** the partial exclusion constraint on `vehicle_blocks` is the guarantee; the bitmap may be stale for a second and that's fine

### Q2: "How would you scale availability queries for 10K vehicles across 200 locations?"

- **Do the arithmetic first:** 10K vehicles × 21 bytes/week ≈ 210 KB of bitmaps; even 30 bookings per car in the horizon is 300K block rows. One Postgres primary handles the writes (a few bookings/second); this is a read-latency problem, not a data-volume one. Don't shard yet
- **CQRS:** writes go to Postgres; search reads Redis bitmaps keyed by `location:{id}` (one `MGET`/pipeline per search) and only touches Postgres for the final booking
- **Event-driven rebuild** of a vehicle's bitmap on each block change, plus a nightly full rebuild that also rolls the 7-day window forward
- **Read replicas** for the detail and admin views; replica lag is fine because booking hits the primary
- **If it ever must shard:** by region/branch, since a booking never spans two vehicles' rows

### Q3: "How do you handle same-day bookings and branch operating hours?"

- **Same-day cutoff:** No bookings within 2 hours of pickup (time for vehicle prep)
- **Branch hours:** Validate pickup/return times against branch operating hours
- **After-hours return:** Drop box + key box at branch; checked next morning
- **Airport branches:** 24/7 operation, higher hourly rate

### Q4: "How would you implement a fleet utilization dashboard?"

**Aggregation queries:**
```sql
-- Utilization per vehicle per day
SELECT v.id, v.make || ' ' || v.model AS vehicle,
       d.date,
       COALESCE(SUM(EXTRACT(EPOCH FROM (r.return_datetime - r.pickup_datetime))/3600), 0) AS booked_hours,
       24 - COALESCE(SUM(EXTRACT(EPOCH FROM (r.return_datetime - r.pickup_datetime))/3600), 0) AS available_hours
FROM vehicles v
CROSS JOIN generate_series(CURRENT_DATE, CURRENT_DATE + 6, '1 day') AS d(date)
LEFT JOIN reservations r ON r.vehicle_id = v.id
    AND r.status IN ('CONFIRMED', 'IN_PROGRESS')
    AND d.date::date = r.pickup_datetime::date
GROUP BY v.id, v.make, v.model, d.date;
-- Caveat: this attributes a whole multi-day rental to its pickup day, so available_hours can go
-- negative. Correct version: intersect each rental with the day,
--   tstzrange(r.pickup_datetime, r.return_datetime) * tstzrange(d.date, d.date + 1)
-- and sum upper(...) - lower(...) (see DB_SCHEMA.md query 5).
```

---

## 7a. FAILURE MODES, IDEMPOTENCY & CONSISTENCY

| Concern | Choice |
|---------|--------|
| Booking consistency | Strong, per vehicle (exclusion constraint on the primary) |
| Search / grid consistency | Eventual (bitmaps rebuilt from events, seconds of lag); booking re-checks |
| Duplicate submits | `reservations.idempotency_key UNIQUE`; retry returns the same hold |
| Payment callbacks | Idempotent on reservation id; confirm is a conditional UPDATE, so webhook + client confirm can both arrive safely |
| Lost events | Transactional outbox; bitmap builder is idempotent (full rebuild per vehicle) |
| Hold never paid | Sweeper deactivates lapsed holds; booking path also expires a lapsed blocker on conflict |
| Late return | Alarm at `return + grace` if not checked in; re-assign the next booking to a same-class car before the customer arrives |
| Branch / region outage | Bookings need the primary; search can serve stale bitmaps read-only |

**Capacity:** ~5K bookings/day ≈ 0.06/s average, maybe 5/s at peak — trivial for one primary. Searches dominate: at 100 searches per booking, ~500K/day ≈ 6/s average, 100+/s peak, all served from Redis. The interesting load is contention on a few popular cars at the airport on Friday evening, which the per-vehicle constraint handles without global locking.

---

## 8. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale | Alternative |
|----------|--------|-----------|-------------|
| **Booking granularity** | Hourly | Supports short rentals, maximizes utilization | Daily-only (simpler, lower utilization) |
| **Availability storage** | Exact ranges (`vehicle_blocks`) | No rounding errors, maps 1:1 to `tstzrange` | Hourly slot rows (simple UNIQUE key, but forces rounding) |
| **Availability reads** | Pre-computed bitmaps (read model) | O(1) pre-filter, 21 bytes/vehicle/week | Live range query (accurate, slower on the browse path) |
| **Race prevention** | Partial exclusion constraint | DB-enforced, no code path can skip it | `SELECT ... FOR UPDATE` on the vehicle row (portable, e.g. MySQL) |
| **Search cache** | Redis | <1ms reads, TTL-based invalidation | In-memory cache (lost on restart) |
| **Pricing model** | Hourly + Daily + Weekly discount | Flexible for all rental durations | Single rate (confusing) |
| **Isolation level** | READ COMMITTED + constraint | Constraint is checked at insert regardless of snapshot | SERIALIZABLE (correct, but every conflict becomes a `40001` retry) |

---

## 9. COST (Monthly)

| Component | Configuration | Cost |
|-----------|--------------|------|
| Search Service (Go) | 4 instances, t3.medium | $400 |
| Booking Service (Go) | 4 instances, t3.medium | $400 |
| Fleet Service (Python) | 2 instances, t3.small | $150 |
| PostgreSQL | db.r6g.large, Multi-AZ, 200GB | $600 |
| Redis Cache | cache.r6g.large, cluster mode | $300 |
| API Gateway + ALB | Per-request pricing | $200 |
| Monitoring (Datadog) | Infrastructure + APM | $250 |
| **Total** | | **$2,300** |
