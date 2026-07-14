# Car Rental Platform — Implementation> Python implementation of the Car Rental Platform with availability-driven design.
> Core focus: hourly booking, 7-day lookahead calendar, double-booking prevention, search/display UX.

---

## 🎯 Core Architecture: Availability Calendar
The central data structure is the `AvailabilityCalendar`, which tracks vehicle availability at hourly granularity.

```
Vehicle ──→ AvailabilityCalendar ──→ TimeBlock[]
                  │
                  ├── is_available(vehicle_id, pickup, dropoff) → bool
                  ├── mark_booked(vehicle_id, pickup, dropoff)
                  ├── get_availability_summary(vehicle_id, date) → {available: [9,10,11,...]}
                  └── get_weekly_availability(vehicle_id, start_date) → 7-day calendar
```

### Search Workflow

```
User Search Request
    │
    ├── Search Criteria: pickup datetime, return datetime, vehicle type, location
    │
    ├── 1. AvailabilityCalendar.get_available_vehicles()
    │       └── For each vehicle, check: is_available(vehicle_id, pickup, return)
    │           └── Check all hourly slots between pickup and return are free
    │
    ├── 2. Filter by vehicle type, location (if specified)
    │
    ├── 3. Sort by price/availability/rating
    │
    └── Display results with availability calendar per vehicle
```

### Display to Users

```python
# Weekly availability view for a vehicle
{
    'vehicle_id': 'V1',
    'week_start': '2024-01-15',
    'days': [
        {'date': '2024-01-15', 'day_name': 'Mon',
         'available_hours': [9,10,11,14,15,16],  # Hourly slots
         'total_available': 6,
         'is_fully_booked': False},
        {'date': '2024-01-16', 'day_name': 'Tue',
         'available_hours': [8,9,10,11,12,13,14,15,16,17],
         'total_available': 10,
         'is_fully_booked': False},
        ...
    ]
}
```

---

## 🗄️ Database Schema

The complete production schema for the car rental platform is in [**DB_SCHEMA.md**](DB_SCHEMA.md).
It includes 7 PostgreSQL tables:
- `vehicles`, `customers`, `branches`, `reservations`, `availability_slots`, `maintenance_schedule`, `payments`
- `tstzrange` exclusion constraint for hard double-booking prevention
- btree_gist extension for efficient range overlap checking
- `availability_slots` materialized for O(1) lookups
- Key query examples for availability checks

## 📦 Python Implementation

```python
"""
Car Rental Platform - Low Level Design
-----------------------------------------
Design Principles: SOLID, Strategy Pattern, State Pattern

Core Focus:
  - Identifying when cars are free for booking (hourly/daily granularity)
  - 1-week lookahead availability calendar
  - Efficient search, display, and storage of availability data
  - Prevent double-booking with date-range exclusion constraints
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, date, time
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
import uuid

# --- Key Classes ---

# TimeBlock: Fundamental availability unit (hourly granularity)
# AvailabilityCalendar: Tracks booked slots, provides query/update methods
#   - is_available(vehicle_id, pickup, dropoff) → bool
#   - get_weekly_availability(vehicle_id, start_date) → calendar
# SearchService: Search vehicles with availability + filters
#   - search_available(pickup, dropoff, type, location)
#   - browse_weekly(type, location)
# CarRentalService: Facade, creates reservations with availability checks
#   - create_reservation() validates ALL hourly slots free before booking

# (Full implementation in car_rental.py)
```

---

## ▶️ How to Run

```bash
cd low-level-design/car-rental-platform
python car_rental.py
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Pricing (Hourly/Daily/Discounted) | Interchangeable pricing algorithms |
| **State** | Reservation lifecycle | PENDING → CONFIRMED → IN_PROGRESS → COMPLETED |
| **Facade** | CarRentalService | Unified interface over fleet, search, calendar |
| **Decorator** | WeeklyDiscountPricing | Compose discounts without modifying base pricing |
| **Iterator** | AvailabilityCalendar | Iterate over hourly slots for availability check |
