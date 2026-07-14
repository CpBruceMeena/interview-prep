# 🗄️ Car Rental Platform — Database Schema & Relationships

> **Database:** PostgreSQL 16 with btree_gist extension  
> **Purpose:** Fleet management, hourly/daily bookings, availability calendar, payments  
> **Tables:** 7 tables

---

## 📊 Entity Relationship Diagram (Textual)

```
┌──────────────┐     ┌──────────────┐
│   vehicles   │1───N│ reservations │
└──────┬───────┘     └──────┬───────┘
       │                     │1
       │1                    │
       │                ┌────▼───────┐
       │                │  payments  │
       │                └────────────┘
       │1
       │
┌──────▼──────────┐     ┌──────────────────┐
│ maintenance_    │     │ availability_    │
│ schedule        │     │ slots            │
└─────────────────┘     └──────────────────┘

┌──────────────┐     ┌──────────────┐
│  customers   │1───N│ reservations │
└──────────────┘     └──────────────┘

┌──────────────┐
│  branches    │─── locations
└──────────────┘
```

---

## 🏛️ Complete DDL

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
    branch_id UUID REFERENCES branches(id),
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
    -- Pricing breakdown
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
    
    CONSTRAINT no_double_booking CHECK (pickup_datetime < return_datetime)
);

-- Exclusion constraint: THE hard guarantee against double-booking
-- Uses btree_gist extension for efficient range overlap checking
-- https://www.postgresql.org/docs/current/btree-gist.html
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
-- 5. AVAILABILITY SLOTS (Materialized for fast O(1) lookups)
-- -----------------------------------------------------------
CREATE TABLE availability_slots (
    id BIGSERIAL,
    vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    slot_date DATE NOT NULL,
    slot_hour INT NOT NULL CHECK (slot_hour >= 0 AND slot_hour < 24),
    is_booked BOOLEAN DEFAULT false,
    reservation_id UUID REFERENCES reservations(id),
    PRIMARY KEY (vehicle_id, slot_date, slot_hour)
);

CREATE INDEX idx_avail_vehicle_date ON availability_slots(vehicle_id, slot_date);

-- -----------------------------------------------------------
-- 6. MAINTENANCE SCHEDULE
-- -----------------------------------------------------------
CREATE TABLE maintenance_schedule (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    maintenance_type VARCHAR(50) NOT NULL 
        CHECK (maintenance_type IN ('OIL_CHANGE','TIRE','SERVICE','DETAILING','REPAIR')),
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'SCHEDULED' 
        CHECK (status IN ('SCHEDULED','IN_PROGRESS','COMPLETED','CANCELLED')),
    notes TEXT,
    cost DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- Also block reservations during maintenance (same pattern)
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
-- KEY QUERY EXAMPLES
-- -----------------------------------------------------------

-- 1. Check if vehicle is available for a time range
SELECT COUNT(*) = 0 AS is_available
FROM reservations
WHERE vehicle_id = 'uuid-here'
  AND status IN ('CONFIRMED', 'IN_PROGRESS')
  AND tstzrange(pickup_datetime, return_datetime) && 
      tstzrange('2024-01-15 10:00:00', '2024-01-15 16:00:00');

-- 2. Find ALL available vehicles for a time range + location
SELECT v.* FROM vehicles v
WHERE v.status = 'AVAILABLE'
  AND NOT EXISTS (
    SELECT 1 FROM reservations r
    WHERE r.vehicle_id = v.id
      AND r.status IN ('CONFIRMED', 'IN_PROGRESS')
      AND tstzrange(r.pickup_datetime, r.return_datetime) && 
          tstzrange('2024-01-15 10:00:00', '2024-01-15 16:00:00')
  )
  AND NOT EXISTS (
    SELECT 1 FROM maintenance_schedule m
    WHERE m.vehicle_id = v.id
      AND m.status = 'SCHEDULED'
      AND tstzrange(m.scheduled_start, m.scheduled_end) && 
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

-- 5. Fleet utilization report for last 7 days
SELECT v.id, v.make || ' ' || v.model AS vehicle,
       COUNT(r.id) AS total_bookings,
       COALESCE(SUM(EXTRACT(EPOCH FROM (r.return_datetime - r.pickup_datetime))/3600), 0) AS booked_hours,
       ROUND(COALESCE(SUM(EXTRACT(EPOCH FROM (r.return_datetime - r.pickup_datetime))/3600), 0) / 168.0 * 100, 1) AS utilization_pct
FROM vehicles v
LEFT JOIN reservations r ON r.vehicle_id = v.id
    AND r.status IN ('CONFIRMED', 'IN_PROGRESS', 'COMPLETED')
    AND r.pickup_datetime >= CURRENT_DATE - 7
GROUP BY v.id, v.make, v.model
ORDER BY utilization_pct DESC;
```

---

## 🔑 Redis Schema (Caching Layer)

```ascii
available:{vehicle_id}:{YYYY-MM-DD}:{HH}     → BOOL (1=available, 0=booked)
fleet:available:{YYYY-MM-DD}:{HH}             → INT (total available in city)
fleet:weekly_bitmap:{vehicle_id}              → BYTES (21 bytes = 7×24 bits)
reservation:{id}:state                        → HASH (current reservation state)
```

---

## 📐 Table Relationships Summary

| # | Table | Parent FK | Child References | Key Indexes |
|---|-------|-----------|-----------------|-------------|
| 1 | `vehicles` | `branch_id → branches` | `reservations(vehicle_id)`, `availability_slots(vehicle_id)`, `maintenance_schedule(vehicle_id)` | type, location, available(partial) |
| 2 | `customers` | — | `reservations(customer_id)` | email, phone |
| 3 | `branches` | — | `vehicles(branch_id)`, `reservations(branch_id)` | — |
| 4 | `reservations` | `customer_id → customers`, `vehicle_id → vehicles`, `branch_id → branches` | `payments(reservation_id)`, `availability_slots(reservation_id)` | customer, vehicle, status, pickup, (vehicle, tstzrange &&) |
| 5 | `availability_slots` | `vehicle_id → vehicles`, `reservation_id → reservations` | — | (vehicle_id, slot_date) |
| 6 | `maintenance_schedule` | `vehicle_id → vehicles` | — | (vehicle_id, tstzrange &&) |
| 7 | `payments` | `reservation_id → reservations` | — | idempotency_key |
