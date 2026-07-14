# Car Rental Platform - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (10+ years)  
> **Evaluation Focus:** Fleet availability management, hourly booking, capacity planning, search architecture, concurrency

---

## Question 1: Core Design — Availability-Driven
**Interviewer:** *"Design a car rental platform where we own the fleet. The core challenge is accurately showing which cars are free for booking — by the hour or by the day — and showing availability for the next week."*

### 🎯 Staff-Level Answer

**Core Domain Model:**
```
Vehicle ──→ AvailabilityCalendar ──→ TimeBlock[] (hourly slots)
    │                                      │
    │                              1-week lookahead
    │                                      │
    └── Reservations ─────→ Booked Slots (exclusion constraint)
```

**Availability Calendar (Hourly Granularity):**
```python
class AvailabilityCalendar:
    """
    Tracks availability at hourly granularity.
    Each day = 24 slots. Booking occupies contiguous slots.
    """
    
    def is_available(self, vehicle_id, pickup, dropoff) -> bool:
        # Check ALL hourly slots between pickup and dropoff
        for slot in self._get_slots(pickup, dropoff):
            if slot in self._booked_slots[vehicle_id]:
                return False
        return True
    
    def get_weekly_availability(self, vehicle_id, start_date):
        # Return 7-day calendar: available hours per day
        return {
            'days': [
                {'date': ..., 'available_hours': [9,10,11,14,15], ...}
                for day in range(7)
            ]
        }
```

**Database Guarantee:**
```sql
ALTER TABLE reservations ADD CONSTRAINT no_overlapping_booking
EXCLUDE USING gist (
    vehicle_id WITH =,
    tstzrange(pickup_datetime, return_datetime) WITH &&
);
```

**Search Response:**
```json
{
  "vehicle": {"make": "Toyota", "model": "Fortuner", "hourly_rate": 12, "daily_rate": 80},
  "estimated_cost": 72.0,
  "weekly_availability": {
    "days": [
      {"date": "Mon", "available_hours": [9,10,11,14,15,16], "total_available": 6},
      {"date": "Tue", "available_hours": [8,9,10,11,12,13,14,15], "total_available": 8}
    ]
  }
}
```

---

## Question 2: Preventing Double-Booking (Deep Dive)
**Interviewer:** *"How do you ensure a vehicle isn't double-booked when two users try to book overlapping times concurrently?"*

### 🎯 Staff-Level Answer

**Four-layer defense:**

| Layer | Mechanism | Guarantee |
|-------|-----------|-----------|
| 1. Application | Optimistic check: `SELECT overlapping reservations COUNT = 0` | Catches 99.9% of conflicts |
| 2. Database | **Exclusion constraint** `tstzrange && tstzrange` | Hard DB guarantee, atomic |
| 3. Idempotency | `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` | Prevents duplicates from retry |
| 4. Isolation | `SERIALIZABLE` transaction isolation | Prevents phantom reads |

**Race condition walkthrough:**

```
Time    User A                           User B
│       BEGIN;                           BEGIN;
│       SELECT overlapping_reservations  SELECT overlapping_reservations
│       → 0 (no conflict)                → 0 (no conflict)
│       INSERT reservation (pending)     
│       COMMIT;                          
│                                        INSERT reservation → CONSTRAINT VIOLATION!
│                                        ROLLBACK;
│                                        → "Vehicle no longer available"
▼
```

**Why SERIALIZABLE?** 
At `REPEATABLE READ`, both `SELECT` queries would see the same snapshot — no rows. Both INSERTs would attempt to write. Without the exclusion constraint, this would succeed (phantom). With `SERIALIZABLE`, the second transaction gets a serialization failure on commit, forcing a retry.

**Exclusion constraint** is the hard guarantee — it catches the conflict at row-write time regardless of isolation level.

---

## Question 3: Hourly Booking Granularity
**Interviewer:** *"Why hourly granularity instead of daily? What are the trade-offs?"*

### 🎯 Answer

| Aspect | Hourly | Daily |
|--------|--------|-------|
| **Utilization** | Higher — gaps between bookings can be filled | Lower — whole day locked even if used for 2 hours |
| **Revenue** | Higher — charge for actual usage | Lower — flat daily rate |
| **Complexity** | Higher — need to track 168 slots/vehicle/week | Lower — 7 slots/vehicle/week |
| **Availability Matrix** | 21 bytes/vehicle/week (24 bits × 7 days) | 7 bytes/vehicle/week |
| **Search latency** | O(N) where N = hours in range | O(1) |
| **User flexibility** | Rent for 3 hours for a meeting | Must rent for full day |

**Decision:** Hourly with daily maximum cap. If hourly cost exceeds daily rate, charge daily rate instead. This gives best of both worlds:
```python
def calculate_cost(vehicle, hours, days):
    hourly = vehicle.hourly_rate * hours
    daily = vehicle.daily_rate * max(1, days)
    return min(hourly, daily)  
    # Wait, that loses revenue. Actually:
    return max(hourly, daily)  # Always charge at least the daily rate
    # Better:
    return max(vehicle.hourly_rate * hours, vehicle.daily_rate * max(1, days))
```

**Staff-level nuance:** 
- **Minimum rental period:** 1 hour. Shorter than that → logistics overhead exceeds revenue.
- **Maximum rental period:** 30 days. Longer → monthly subscription model instead.
- **Round-up policy:** Any started hour is charged as full hour. $0.005 rounding × 100K bookings = $500/month.
- **Grace period:** 15-minute grace on return (no extra charge). After that, full hour charged.

---

## Question 4: Search & Display Architecture
**Interviewer:** *"How would you show 7-day availability data to users efficiently? Design the search and display system."*

### 🎯 Staff-Level Answer

**Data storage strategy:**

```ascii
                        ┌──────────────────────┐
                        │  PostgreSQL            │
                        │  reservations table    │
                        │  (source of truth)     │
                        └────┬─────────────────┘
                             │
                  ┌──────────┴──────────┐
                  │                     │
          ┌───────▼──────┐    ┌────────▼───────┐
          │ ETL Job       │    │ Write-through  │
          │ (every 15 min)│    │ (on booking)   │
          └───────┬──────┘    └────────┬───────┘
                  │                     │
                  └──────────┬──────────┘
                             │
                    ┌────────▼────────┐
                    │  Redis Cache     │
                    │  availability    │
                    │  bitmaps         │
                    │  (7-day, 24-bit) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  API Service     │
                    │  (Go, ~1ms)      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Frontend        │
                    │  (React, grid)   │
                    └─────────────────┘
```

**Availability bitmap encoding:**
```python
# Each vehicle has a 7-day × 24-hour bitmap (168 bits)
# Encoding: 21 bytes per vehicle
# 1 = available, 0 = booked/maintenance

def encode_weekly(vehicle_id, start_date) -> bytes:
    bitmap = 0
    for day_offset in range(7):
        for hour in range(24):
            if is_slot_available(vehicle_id, start_date + day_offset, hour):
                bit_position = day_offset * 24 + hour
                bitmap |= (1 << bit_position)
    return bitmap.to_bytes(21, 'big')  # 168 bits = 21 bytes

def check_availability(bitmap: bytes, pickup_hour, dropoff_hour, day_offset) -> bool:
    mask = 0
    for hour in range(pickup_hour, dropoff_hour):
        bit_position = day_offset * 24 + hour
        mask |= (1 << bit_position)
    return (int.from_bytes(bitmap, 'big') & mask) == mask
```

**API design:**
```python
# Lightweight: just returns bitmap + vehicle metadata
GET /api/fleet/availability?start_date=2024-01-15&location=Bangalore

Response:
{
  "start_date": "2024-01-15",
  "vehicles": [
    {
      "id": "V1",
      "make": "Toyota",
      "model": "Fortuner",
      "type": "SUV",
      "hourly_rate": 12.0,
      "daily_rate": 80.0,
      "location": "Bangalore Airport",
      "weekly_bitmap": "base64encoded_21bytes...",  # 168 bits
      "total_available_hours_week": 45
    }
  ]
}
```

**Frontend rendering:**
- Parse bitmap → generate 7×24 grid
- Color-code: green (available), red (booked), gray (outside branch hours)
- Click an hour → auto-fill pickup time
- Drag across multiple hours → auto-fill return time
- Weekly view: show "available hours per day" summary per vehicle

---

## Question 5: Fleet Management & Maintenance
**Interviewer:** *"How do you handle maintenance scheduling so it doesn't conflict with bookings?"*

### 🎯 Answer

**Maintenance is just another kind of "booking":**
```sql
-- Maintenance also blocks availability
CREATE TABLE maintenance_schedule (
    vehicle_id UUID REFERENCES vehicles(id),
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ NOT NULL,
    type VARCHAR(50),  -- OIL_CHANGE, SERVICE, REPAIR
    
    -- Same exclusion constraint as reservations
    CONSTRAINT no_overlapping_maintenance 
        EXCLUDE USING gist (
            vehicle_id WITH =,
            tstzrange(scheduled_start, scheduled_end) WITH &&
        )
);
```

**Availability query combines both:**
```sql
SELECT v.id, v.make, v.model
FROM vehicles v
WHERE v.status = 'AVAILABLE'
  AND NOT EXISTS (
    SELECT 1 FROM reservations r
    WHERE r.vehicle_id = v.id
      AND r.status IN ('CONFIRMED', 'IN_PROGRESS')
      AND tstzrange(r.pickup_datetime, r.return_datetime) && 
          tstzrange('2024-01-15 10:00', '2024-01-15 14:00')
  )
  AND NOT EXISTS (
    SELECT 1 FROM maintenance_schedule m
    WHERE m.vehicle_id = v.id
      AND m.status IN ('SCHEDULED', 'IN_PROGRESS')
      AND tstzrange(m.scheduled_start, m.scheduled_end) && 
          tstzrange('2024-01-15 10:00', '2024-01-15 14:00')
  );
```

**Predictive maintenance:** Schedule based on mileage (every 5,000km), not calendar. A lightly-used car needs less frequent service.

---

## Question 6: Staff-Level — Fleet Utilization Optimization
**Interviewer:** *"How would you optimize fleet utilization using the availability data?"*

### 🎯 Answer

**Metrics to track:**
```python
utilization = booked_hours / total_available_hours
turnover = total_bookings / fleet_size
revenue_per_vehicle = total_revenue / vehicle_count
idle_time = hours_available_but_not_booked
```

**Optimization strategies:**

| Strategy | Implementation | Impact |
|----------|---------------|--------|
| **Dynamic pricing** | Lower hourly rate for low-demand hours (10AM-2PM weekdays) | +15% utilization |
| **Last-minute discounts** | 20% off for bookings starting within 2 hours | +10% same-day bookings |
| **Vehicle redistribution** | Move underutilized vehicles to high-demand locations | +20% utilization in saturated areas |
| **Maintenance scheduling** | Schedule maintenance during low-demand periods | Minimizes revenue loss |
| **Fleet sizing** | Add vehicles to locations with >80% utilization consistently | Prevents lost revenue |

**Utilization dashboard query:**
```sql
SELECT v.location,
       v.vehicle_type,
       COUNT(DISTINCT v.id) AS fleet_size,
       AVG(r.booked_hours / 24.0 * 100) AS avg_utilization_pct
FROM vehicles v
LEFT JOIN (
    SELECT vehicle_id, 
           SUM(EXTRACT(EPOCH FROM (return_datetime - pickup_datetime))/3600) AS booked_hours
    FROM reservations
    WHERE status IN ('CONFIRMED', 'IN_PROGRESS')
      AND pickup_datetime >= CURRENT_DATE
      AND pickup_datetime < CURRENT_DATE + 7
    GROUP BY vehicle_id
) r ON r.vehicle_id = v.id
GROUP BY v.location, v.vehicle_type
ORDER BY avg_utilization_pct DESC;
```

---

## Question 7: Edge Cases

| Edge Case | Solution |
|-----------|----------|
| **User returns 3 hours late** | Grace period (15 min) → full extra hour charged → if > 2h late, charge full day |
| **Vehicle breakdown during rental** | Swap to nearest available vehicle of same class; later, charge original booking only |
| **No-show** | Charge 50% of booking amount; mark as NO_SHOW; release vehicle after 30 min |
| **One-way rental** | Additional fee covers vehicle repositioning cost |
| **Union in booking** | Pro-rate: one picks up, returns to different location, second picks up same vehicle |
| **Cancellation within 24h** | Charge 100% (no refund). Cancellation > 24h → full refund. |
| **Weather cancellation** | Full refund if government-issued weather advisory in effect |

---

## Question 8: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Pricing (hourly/daily/discounted) | Interchangeable pricing algorithms |
| **State** | Reservation lifecycle | PENDING → CONFIRMED → IN_PROGRESS → COMPLETED |
| **Facade** | CarRentalService | Unified interface over fleet, search, calendar |
| **Decorator** | WeeklyDiscountPricing | Compose discounts without modifying base pricing |
| **Iterator** | AvailabilityCalendar | Iterate over hourly slots for availability check |
| **Template Method** | Booking flow | Consistent create → validate → confirm → notify pipeline |
