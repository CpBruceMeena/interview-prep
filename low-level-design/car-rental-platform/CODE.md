# Car Rental Platform — Implementation

> Python implementation of the Car Rental Platform with availability-driven design.
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

## 🗄️ Production Database Schema

```sql
-- ============================================================
-- Car Rental Platform - Production Database Schema
-- Database: PostgreSQL 16
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- For exclusion constraint

-- -----------------------------------------------------------
-- 1. VEHICLES
-- -----------------------------------------------------------
CREATE TABLE vehicles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_type VARCHAR(20) NOT NULL 
        CHECK (vehicle_type IN ('HATCHBACK','SEDAN','SUV','LUXURY','VAN','TRUCK')),
    make VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    year INT NOT NULL,
    license_plate VARCHAR(20) UNIQUE NOT NULL,
    fuel_type VARCHAR(20) NOT NULL 
        CHECK (fuel_type IN ('PETROL','DIESEL','ELECTRIC','HYBRID')),
    hourly_rate DECIMAL(8,2) NOT NULL,
    daily_rate DECIMAL(8,2) NOT NULL,
    weekly_rate DECIMAL(8,2),          -- Discounted weekly rate
    monthly_rate DECIMAL(8,2),         -- Discounted monthly rate
    mileage INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'AVAILABLE' 
        CHECK (status IN ('AVAILABLE','RESERVED','RENTED','MAINTENANCE','RETIRED')),
    location VARCHAR(255),             -- Current branch/location
    branch_id UUID,                    -- FK to branches
    seating_capacity INT NOT NULL,
    transmission VARCHAR(20) DEFAULT 'MANUAL' CHECK (transmission IN ('MANUAL','AUTOMATIC')),
    features JSONB DEFAULT '[]',       -- ["GPS", "AC", "Bluetooth", ...]
    image_urls TEXT[],
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_vehicles_type ON vehicles(vehicle_type);
CREATE INDEX idx_vehicles_location ON vehicles(location);
CREATE INDEX idx_vehicles_status ON vehicles(status) WHERE status = 'AVAILABLE';

-- -----------------------------------------------------------
-- 2. CUSTOMERS
-- -----------------------------------------------------------
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    driver_license_number VARCHAR(50) UNIQUE NOT NULL,
    driver_license_expiry DATE NOT NULL,
    date_of_birth DATE,
    address TEXT,
    is_verified BOOLEAN DEFAULT false,
    loyalty_points INT DEFAULT 0,
    membership_tier VARCHAR(20) DEFAULT 'BASIC' 
        CHECK (membership_tier IN ('BASIC','SILVER','GOLD','PLATINUM')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 3. BRANCHES / LOCATIONS
-- -----------------------------------------------------------
CREATE TABLE branches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    address TEXT NOT NULL,
    city VARCHAR(100) NOT NULL,
    latitude DECIMAL(10,7),
    longitude DECIMAL(10,7),
    phone VARCHAR(20),
    opening_time TIME DEFAULT '08:00',
    closing_time TIME DEFAULT '20:00',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 4. RESERVATIONS (Core table with anti-double-booking constraint)
-- -----------------------------------------------------------
CREATE TABLE reservations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id),
    vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    branch_id UUID REFERENCES branches(id),
    pickup_datetime TIMESTAMPTZ NOT NULL,
    return_datetime TIMESTAMPTZ NOT NULL,
    pickup_location VARCHAR(255) NOT NULL,
    dropoff_location VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING','CONFIRMED','IN_PROGRESS','COMPLETED','CANCELLED','NO_SHOW')),
    -- Pricing
    pricing_strategy VARCHAR(50),  -- 'HOURLY', 'DAILY', 'WEEKLY_DISCOUNT'
    hourly_rate DECIMAL(8,2),
    daily_rate DECIMAL(8,2),
    base_amount DECIMAL(10,2),
    discount_amount DECIMAL(10,2) DEFAULT 0,
    tax_amount DECIMAL(10,2) DEFAULT 0,
    total_amount DECIMAL(10,2) NOT NULL,
    additional_services JSONB DEFAULT '[]',  -- [{"name": "GPS", "cost": 5.0}, ...]
    -- Business rules
    idempotency_key VARCHAR(64) UNIQUE,  -- Prevent duplicate bookings
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraint: No overlapping reservations for same vehicle
    CONSTRAINT no_double_booking 
        CHECK (pickup_datetime < return_datetime),
    
    -- Check valid status transitions
    CONSTRAINT valid_status_for_cancel 
        CHECK (status NOT IN ('COMPLETED') OR cancellation_reason IS NULL)
);

-- Exclusion constraint for preventing double-booking at DB level
-- Uses btree_gist extension for efficient range overlap checking
ALTER TABLE reservations ADD CONSTRAINT no_overlapping_booking
EXCLUDE USING gist (
    vehicle_id WITH =,
    tstzrange(pickup_datetime, return_datetime) WITH &&
);

CREATE INDEX idx_reservations_customer ON reservations(customer_id);
CREATE INDEX idx_reservations_vehicle ON reservations(vehicle_id);
CREATE INDEX idx_reservations_status ON reservations(status);
CREATE INDEX idx_reservations_pickup ON reservations(pickup_datetime);
CREATE INDEX idx_reservations_overlap ON reservations(vehicle_id, pickup_datetime, return_datetime);

-- -----------------------------------------------------------
-- 5. AVAILABILITY SLOTS (Materialized for fast lookups)
-- -----------------------------------------------------------
-- This table can be materialized from reservations for O(1) availability checks
CREATE TABLE availability_slots (
    id BIGSERIAL,
    vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    slot_date DATE NOT NULL,
    slot_hour INT NOT NULL CHECK (slot_hour >= 0 AND slot_hour < 24),
    is_booked BOOLEAN DEFAULT false,
    reservation_id UUID REFERENCES reservations(id),
    PRIMARY KEY (vehicle_id, slot_date, slot_hour)
);

-- Partition by month for query performance
CREATE INDEX idx_avail_vehicle_date ON availability_slots(vehicle_id, slot_date);

-- -----------------------------------------------------------
-- 6. MAINTENANCE SCHEDULE
-- -----------------------------------------------------------
CREATE TABLE maintenance_schedule (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    maintenance_type VARCHAR(50) NOT NULL CHECK (maintenance_type IN ('OIL_CHANGE','TIRE','SERVICE','DETAILING','REPAIR')),
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'SCHEDULED' 
        CHECK (status IN ('SCHEDULED','IN_PROGRESS','COMPLETED','CANCELLED')),
    notes TEXT,
    cost DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- Also block reservations during maintenance
    CONSTRAINT no_overlapping_maintenance 
        EXCLUDE USING gist (
            vehicle_id WITH =,
            tstzrange(scheduled_start, scheduled_end) WITH &&
        )
);

-- -----------------------------------------------------------
-- 7. PAYMENTS
-- -----------------------------------------------------------
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reservation_id UUID NOT NULL REFERENCES reservations(id),
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    method VARCHAR(20) NOT NULL CHECK (method IN ('CARD','UPI','WALLET','BANK_TRANSFER')),
    status VARCHAR(20) DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING','AUTHORIZED','CAPTURED','REFUNDED','FAILED')),
    is_pre_authorization BOOLEAN DEFAULT true,
    gateway_transaction_id VARCHAR(255),
    gateway_response JSONB,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- Key Availability Query Examples:
-- -----------------------------------------------------------

-- 1. Check if vehicle is available for a time range (PostgreSQL)
SELECT COUNT(*) = 0 AS is_available
FROM reservations
WHERE vehicle_id = 'uuid-here'
  AND status IN ('CONFIRMED', 'IN_PROGRESS')
  AND tstzrange(pickup_datetime, return_datetime) && 
      tstzrange('2024-01-15 10:00:00', '2024-01-15 16:00:00');

-- 2. Find all available vehicles for a time range
SELECT v.* FROM vehicles v
WHERE v.status = 'AVAILABLE'
  AND NOT EXISTS (
    SELECT 1 FROM reservations r
    WHERE r.vehicle_id = v.id
      AND r.status IN ('CONFIRMED', 'IN_PROGRESS')
      AND tstzrange(r.pickup_datetime, r.return_datetime) && 
          tstzrange('2024-01-15 10:00:00', '2024-01-15 16:00:00')
  )
  AND v.location = 'Bangalore Airport';

-- 3. Get hourly availability for a vehicle on a specific date
SELECT slot_hour, is_booked
FROM availability_slots
WHERE vehicle_id = 'uuid-here'
  AND slot_date = '2024-01-15'
ORDER BY slot_hour;

-- 4. Get weekly availability summary for a vehicle
SELECT slot_date, 
       COUNT(*) FILTER (WHERE NOT is_booked) AS available_hours,
       COUNT(*) FILTER (WHERE is_booked) AS booked_hours
FROM availability_slots
WHERE vehicle_id = 'uuid-here'
  AND slot_date >= CURRENT_DATE
  AND slot_date < CURRENT_DATE + 7
GROUP BY slot_date
ORDER BY slot_date;
```

---

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
