# 🧠 Car Rental Platform LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

How is availability tracked? (Hourly granularity.) Lookahead period? (7 days.) Double-booking prevention? Pricing models? (Hourly, daily, weekly discounts.)

## Phase 1: Identify the Nouns

> *"Customers browse vehicles by availability. They book a vehicle for specific time windows. The system prevents double-booking."*

| Noun | Decision | Why |
|------|----------|-----|
| Vehicle | Regular Class | Makes/model/type, linked to availability |
| TimeBlock | Regular Class | Fundamental availability unit (hourly) |
| AvailabilityCalendar | Regular Class | Core data structure: tracks booked slots |
| Reservation | Regular Class | Links customer + vehicle + time window |
| PricingStrategy | ABC | Strategy for rental pricing |
| SearchService | Regular | Filters by availability + type + location |
| CarRentalService | Facade | Main entry point |

## Phase 2: Enums First

```python
class VehicleType(Enum):   SEDAN, SUV, HATCHBACK, TRUCK, VAN, LUXURY
class ReservationStatus(Enum): PENDING, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED
```

## Phase 3: dataclass vs `__init__`

- **`Vehicle`**: Regular — has attributes and state
- **`TimeBlock`**: Could be dataclass — passive data (start_time, end_time)
- **`AvailabilityCalendar`**: Regular — core data structure with behavior
- **`Reservation`**: Regular — lifecycle management

## Phase 4: Assigning Responsibilities — Availability is the Star

| Action | Owner | Why |
|--------|-------|-----|
| Check spot availability | `AvailabilityCalendar.is_available()` | Calendar knows all booked slots |
| Mark as booked | `AvailabilityCalendar.mark_booked()` | Calendar updates its state |
| Get availability summary | `AvailabilityCalendar.get_availability_summary()` | Returns available hours for a day |
| Get weekly calendar | `AvailabilityCalendar.get_weekly_availability()` | 7-day lookahead view |
| Search available vehicles | `SearchService.search_available()` | Checks calendar + filters |
| Create booking | `CarRentalService.create_reservation()` | Orchestrates availability check + booking |

## Phase 5: The Core Data Structure

```python
class AvailabilityCalendar:
    def __init__(self):
        self._booked_slots: Dict[str, Set[int]] = {}  # vehicle_id -> set of hour integers
    
    def is_available(self, vehicle_id, pickup, dropoff) -> bool:
        hours = self._get_hours(pickup, dropoff)
        return all(h not in self._booked_slots[vehicle_id] for h in hours)
    
    def mark_booked(self, vehicle_id, pickup, dropoff):
        for h in self._get_hours(pickup, dropoff):
            self._booked_slots[vehicle_id].add(h)
```

**Key insight:** The availability calendar is a `Dict[str, Set[int]]` mapping vehicle IDs to booked hours. This makes O(1) lookups for availability checks.

## Phase 6: Price Composition (Decorator Pattern)

```python
class WeeklyDiscountPricing(PricingStrategy):
    def __init__(self, base: PricingStrategy):
        self._base = base
    def calculate_price(self, ...):
        return self._base.calculate_price(...) * 0.85  # 15% off
```

## Phase 7: Search + Booking Flow

```
1. User searches: pickup=Mon 9am, dropoff=Mon 5pm, type=SUV
2. SearchService checks AvailabilityCalendar for all SUVs
3. Returns available SUVs with their weekly calendar
4. User selects vehicle
5. CarRentalService.create_reservation():
   a. Final availability check (race condition prevention)
   b. Calculate price
   c. Mark slots as booked
   d. Create Reservation
```

## Phase 8: Quick Checklist

✅ **Availability-First Design:** Calendar is the core data structure
✅ **SRP:** Calendar tracks, Search filters, Service orchestrates
✅ **Strategy:** Pricing models are swappable
✅ **Prevention:** Availability check before every booking
✅ **OCP:** New pricing model → new Strategy class
