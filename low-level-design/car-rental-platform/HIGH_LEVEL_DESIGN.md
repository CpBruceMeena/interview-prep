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
        ┌────────▼────────┐
        │   PostgreSQL +   │
        │  Redis Cache    ││  (Availability) │
  └─────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="https://cpbrucemeena.github.io/interview-prep/assets/videos/car-rental-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Car Rental Sequence — Search → Book → Pickup → Return → Payment. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. AVAILABILITY-CENTRIC DESIGN

### 3.1 Core Problem: When is a car free?

**Key insight:** A vehicle is "available" for a time range `[T1, T2]` if there is no overlapping confirmed reservation or maintenance.

```
Vehicle V1 timeline:
        Available ────[Booked]───Available────[Booked]───Available
Time:   08:00       10:00  12:00         14:00 16:00 18:00      20:00

Query: Is V1 available for 14:00-16:00?
→ Yes: no overlap with existing bookings
```

**Hourly granularity:** Each day is divided into 24 hourly slots. A booking occupies N contiguous slots.

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
1. User selects vehicle + time range
2. Backend validates: is_available(vehicle_id, pickup, return)
3. If available:
   a. Start transaction (PostgreSQL SERIALIZABLE isolation)
   b. INSERT reservation with status = 'PENDING'
   c. EXCLUDE constraint `no_overlapping_booking` prevents race condition
   d. If conflict: rollback, notify user of schedule change
   e. If success: commit, status → 'CONFIRMED'
   f. Invalidate Redis cache for affected time slots
   g. Publish event: reservation.created (for notifications, fleet dashboard)
4. User receives confirmation with pickup instructions
```

**Isolation level:** `SERIALIZABLE` is critical here — two concurrent requests for the same vehicle in the same time slot must fail atomically. PostgreSQL's serializable snapshot isolation (SSI) handles this correctly.

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
-- Enforce branch operating hours in search
SELECT v.* FROM vehicles v
JOIN branches b ON v.branch_id = b.id
WHERE NOT EXISTS (... overlapping reservations ...)
  AND pickup_time >= b.opening_time
  AND return_time <= b.closing_time
  -- Or: if return_time > closing_time, charge overnight fee
```

### Booking Service (Go)
- Creates/confirms/cancels reservations
- Validates availability at booking time (double-check pattern)
- Handles payment pre-authorization
- Manages reservation lifecycle: PENDING → CONFIRMED → IN_PROGRESS → COMPLETED

**🔴 Staff-level Question:** *"How do you prevent race conditions where two users book the same vehicle for overlapping times?"*

**✅ Answer:** Multi-layered approach:
1. **Application-level optimistic check:** Query for overlapping reservations before insert
2. **Database exclusion constraint (hard guarantee):** 
   ```sql
   ALTER TABLE reservations ADD CONSTRAINT no_overlapping_booking
   EXCLUDE USING gist (
       vehicle_id WITH =,
       tstzrange(pickup_datetime, return_datetime) WITH &&
   );
   ```
3. **Idempotency key:** Prevent duplicate submissions (network retry → same idempotency key → no-op)
4. **SERIALIZABLE isolation:** Two concurrent conflicting inserts → one wins, one gets serialization failure

### Fleet Service (Python)
- Manages vehicle inventory (add/remove/status)
- Maintenance scheduling (blocks availability during service)
- Vehicle redistribution between branches
- Fleet utilization analytics

---

## 5. DATA MODEL

### Core Tables

```sql
-- See CODE.md for complete DDL

-- Key tables:
vehicles          -- Fleet inventory with hourly/daily rates, location, features
customers         -- User accounts with loyalty program
branches          -- Physical locations with operating hours
reservations      -- Booking with tstzrange overlap exclusion constraint
availability_slots -- Materialized hourly slots for O(1) lookups
maintenance_schedule -- Maintainence that blocks availability
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
- **Lookup:** O(1) bitwise check `(bitmap & mask) == 0` where mask has bits set for requested hours
- **Update:** On booking, set bits atomically. On cancel, clear bits.
- **Race condition:** PostgreSQL exclusion constraint `tstzrange && tstzrange` provides hard guarantee

### Q2: "How would you scale availability queries for 10K vehicles across 200 locations?"

- **Shard by location:** Each location's fleet data on separate PostgreSQL instance
- **Redis cluster:** Pre-compute availability bitmaps, shard by `location:{id}` 
- **Materialized views:** Refresh every 30 seconds for fleet overview
- **CQRS pattern:** Separate read models (availability) from write models (bookings)
- **Cache warming:** Pre-calculate next 7 days every hour, store in Redis bitmaps

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
```

---

## 8. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale | Alternative |
|----------|--------|-----------|-------------|
| **Booking granularity** | Hourly | Supports short rentals, maximizes utilization | Daily-only (simpler, lower utilization) |
| **Availability data** | Pre-computed bitmaps | O(1) lookup, 21 bytes/vehicle/week | Live query (200ms, accurate) |
| **Race prevention** | Exclusion constraint | Hard DB guarantee, no app bugs possible | Application locks (complex, leaky) |
| **Search cache** | Redis | <1ms reads, TTL-based invalidation | In-memory cache (lost on restart) |
| **Pricing model** | Hourly + Daily + Weekly discount | Flexible for all rental durations | Single rate (confusing) |
| **Isolation level** | SERIALIZABLE | Prevents phantom reads, race-proof | REPEATABLE READ (race window) |

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
