# 🗄️ Cab Booking Service — Database Schema & Relationships

> **Database:** PostgreSQL 16 with PostGIS extension  
> **Purpose:** Riders, drivers, trips, zones, location history, payments, ratings, surge pricing  
> **Tables:** 9 tables + 2 partitioned tables

---

## 📊 Entity Relationship Diagram (Textual)

```
┌──────────┐     ┌──────────┐     ┌───────────┐
│  riders  │1───N│  trips   │N───1│  drivers  │
└──────────┘     └──────────┘     └───────────┘
                      │                 │
                      │1                │1
                      │                 │
                 ┌────▼────┐      ┌─────▼──────┐
                 │ payments │      │ location_  │
                 └─────────┘      │ history    │
                                  │ (partition)│
                    ┌─────────┐   └─────┬──────┘
                    │  zones  │◄────────┘
                    └────┬────┘
                         │
                    ┌────▼──────┐
                    │ surge_    │
                    │ pricing_  │
                    │ log       │
                    └───────────┘
```

---

## 🏛️ Complete DDL

```sql
-- ============================================================
-- Cab Booking Service - Production Database Schema
-- Database: PostgreSQL 16 with PostGIS extension
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- -----------------------------------------------------------
-- 1. RIDERS
-- -----------------------------------------------------------
CREATE TABLE riders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    rating DECIMAL(2,1) DEFAULT 5.0 CHECK (rating >= 1.0 AND rating <= 5.0),
    total_rides INT DEFAULT 0,
    payment_methods JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_riders_email ON riders(email);
CREATE INDEX idx_riders_phone ON riders(phone);

-- -----------------------------------------------------------
-- 2. DRIVERS
-- -----------------------------------------------------------
CREATE TABLE drivers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    license_number VARCHAR(50) UNIQUE NOT NULL,
    cab_type VARCHAR(20) NOT NULL CHECK (cab_type IN ('MINI','SEDAN','SUV','PREMIUM','AUTO')),
    cab_registration VARCHAR(50) UNIQUE NOT NULL,
    rating DECIMAL(2,1) DEFAULT 5.0 CHECK (rating >= 1.0 AND rating <= 5.0),
    total_rides INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'AVAILABLE'
        CHECK (status IN ('AVAILABLE','BOOKED','ON_TRIP','OFFLINE','MAINTENANCE')),
    current_location GEOGRAPHY(Point, 4326),
    last_location_update TIMESTAMPTZ,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
-- GIST index for fast geo-radius queries (e.g., GEORADIUS equivalent)
CREATE INDEX idx_drivers_location ON drivers USING GIST (current_location);
-- Partial index for real-time available driver lookup
CREATE INDEX idx_drivers_available ON drivers(id) WHERE status = 'AVAILABLE';
CREATE INDEX idx_drivers_cab_type ON drivers(cab_type);

-- -----------------------------------------------------------
-- 3. TRIPS
-- -----------------------------------------------------------
CREATE TABLE trips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rider_id UUID NOT NULL REFERENCES riders(id),
    driver_id UUID REFERENCES drivers(id),
    pickup_location GEOGRAPHY(Point, 4326) NOT NULL,
    dropoff_location GEOGRAPHY(Point, 4326) NOT NULL,
    pickup_address TEXT,
    dropoff_address TEXT,
    status VARCHAR(20) DEFAULT 'REQUESTED'
        CHECK (status IN ('REQUESTED','ACCEPTED','DRIVER_ARRIVED',
                          'STARTED','COMPLETED','CANCELLED')),
    fare_estimate DECIMAL(10,2),
    final_fare DECIMAL(10,2),
    surge_multiplier DECIMAL(3,2) DEFAULT 1.0,
    distance_km DECIMAL(8,2),
    duration_min INT,
    waiting_minutes INT DEFAULT 0,
    payment_method VARCHAR(20) DEFAULT 'CASH',
    payment_status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (payment_status IN ('PENDING','AUTHORIZED','CAPTURED','REFUNDED','FAILED')),
    idempotency_key VARCHAR(64) UNIQUE,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trips_rider ON trips(rider_id);
CREATE INDEX idx_trips_driver ON trips(driver_id);
CREATE INDEX idx_trips_status ON trips(status);
CREATE INDEX idx_trips_requested ON trips(requested_at);

-- -----------------------------------------------------------
-- 4. ZONES (City Partitioning)
-- -----------------------------------------------------------
CREATE TABLE zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    city_id UUID NOT NULL,
    zone_code VARCHAR(10) NOT NULL,
    center GEOGRAPHY(Point, 4326) NOT NULL,
    radius_meters DECIMAL(10,2) NOT NULL DEFAULT 500,
    surge_multiplier DECIMAL(3,2) DEFAULT 1.0,
    driver_count INT DEFAULT 0,
    ride_request_count INT DEFAULT 0,
    last_calculated TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_zones_city ON zones(city_id);
CREATE INDEX idx_zones_center ON zones USING GIST (center);

-- -----------------------------------------------------------
-- 5. GPS LOCATION HISTORY (Partitioned by Month)
-- -----------------------------------------------------------
CREATE TABLE driver_location_history (
    id BIGSERIAL,
    driver_id UUID NOT NULL REFERENCES drivers(id),
    location GEOGRAPHY(Point, 4326) NOT NULL,
    speed_kmh DECIMAL(5,1),
    heading INT,
    accuracy_meters DECIMAL(5,1),
    zone_id UUID REFERENCES zones(id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (driver_id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Monthly partitions (auto-created by cron/partition manager)
CREATE TABLE driver_location_history_202401 PARTITION OF driver_location_history
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE driver_location_history_202402 PARTITION OF driver_location_history
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE INDEX idx_loc_history_recorded ON driver_location_history(recorded_at DESC);

-- -----------------------------------------------------------
-- 6. PAYMENTS
-- -----------------------------------------------------------
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trip_id UUID NOT NULL REFERENCES trips(id),
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    method VARCHAR(20) NOT NULL CHECK (method IN ('CASH','CARD','WALLET','UPI')),
    status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','AUTHORIZED','CAPTURED','REFUNDED','FAILED')),
    gateway_transaction_id VARCHAR(255),
    gateway_response JSONB,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_payments_trip ON payments(trip_id);
CREATE INDEX idx_payments_idempotency ON payments(idempotency_key);

-- -----------------------------------------------------------
-- 7. RIDER_RATINGS
-- -----------------------------------------------------------
CREATE TABLE rider_ratings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trip_id UUID NOT NULL REFERENCES trips(id),
    rider_id UUID NOT NULL REFERENCES riders(id),
    driver_id UUID NOT NULL REFERENCES drivers(id),
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    review TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(trip_id, rider_id, driver_id)
);

-- -----------------------------------------------------------
-- 8. SURGE PRICING LOG (Time-Series)
-- -----------------------------------------------------------
CREATE TABLE surge_pricing_log (
    id BIGSERIAL,
    zone_id UUID NOT NULL REFERENCES zones(id),
    surge_multiplier DECIMAL(3,2) NOT NULL,
    driver_count INT NOT NULL,
    demand_count INT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (zone_id, calculated_at)
);
CREATE INDEX idx_surge_log_calculated ON surge_pricing_log(calculated_at DESC);

-- -----------------------------------------------------------
-- 9. KEY QUERY EXAMPLES
-- -----------------------------------------------------------

-- Geo-Radius Query: Find nearest available drivers within 3km
SELECT d.id, d.name, d.cab_type, d.rating,
       ST_Distance(d.current_location, ST_MakePoint(-73.9857, 40.7484)::geography) / 1000 AS distance_km
FROM drivers d
WHERE d.status = 'AVAILABLE'
  AND ST_DWithin(
      d.current_location,
      ST_MakePoint(-73.9857, 40.7484)::geography,
      3000  -- 3km in meters
  )
ORDER BY distance_km ASC
LIMIT 5;

-- Zone Surge: Current surge multipliers
SELECT z.zone_code, z.surge_multiplier, z.driver_count, z.ride_request_count
FROM zones z
WHERE z.city_id = 'city-uuid'
ORDER BY z.surge_multiplier DESC;

-- Trip History: Active trips in a zone
SELECT t.id, t.status, t.fare_estimate, d.name AS driver_name, r.name AS rider_name
FROM trips t
JOIN drivers d ON t.driver_id = d.id
JOIN riders r ON t.rider_id = r.id
WHERE t.status IN ('REQUESTED', 'ACCEPTED', 'STARTED')
  AND ST_DWithin(t.pickup_location, (SELECT center FROM zones WHERE zone_code = 'Z0000'), 500);
```

---

## 🔑 Redis Schema (Caching Layer)

```ascii
drivers:available              → GEO (sorted set, geohash-encoded)
driver:{id}:status             → STRING (AVAILABLE/ON_TRIP/OFFLINE)
trip:{id}:state                → HASH (full trip state machine)
zone:{id}:surge                → STRING (current surge multiplier)
zone:{id}:driver_count         → STRING (number of available drivers in zone)
zone:{id}:ride_requests        → STRING (ride request count in aggregation window)
```

---

## 📐 Table Relationships Summary

| # | Table | Parent FK | Child References | Key Indexes |
|---|-------|-----------|-----------------|-------------|
| 1 | `riders` | — | `trips(rider_id)`, `rider_ratings(rider_id)` | email, phone |
| 2 | `drivers` | — | `trips(driver_id)`, `driver_location_history(driver_id)`, `rider_ratings(driver_id)` | GIST(location), available(status), cab_type |
| 3 | `trips` | `rider_id → riders`, `driver_id → drivers` | `payments(trip_id)`, `rider_ratings(trip_id)` | rider, driver, status, requested_at |
| 4 | `zones` | `city_id` | `driver_location_history(zone_id)`, `surge_pricing_log(zone_id)` | GIST(center), city |
| 5 | `driver_location_history` | `driver_id → drivers`, `zone_id → zones` | — | (driver_id, recorded_at) PK, recorded_at DESC |
| 6 | `payments` | `trip_id → trips` | — | trip, idempotency_key |
| 7 | `rider_ratings` | `trip_id → trips`, `rider_id → riders`, `driver_id → drivers` | — | UNIQUE(trip, rider, driver) |
| 8 | `surge_pricing_log` | `zone_id → zones` | — | (zone_id, calculated_at) PK |
