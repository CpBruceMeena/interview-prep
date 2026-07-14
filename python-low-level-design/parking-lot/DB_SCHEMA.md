# 🗄️ Parking Lot System — Database Schema & Relationships

> **Database:** PostgreSQL 16  
> **Purpose:** Multi-floor parking, spot allocation, ticketing, payments, audit  
> **Tables:** 8 tables

---

## 📊 Entity Relationship Diagram (Textual)

```
┌──────────────┐
│  parking_lot │
└──────┬───────┘
       │1
       │
┌──────▼───────┐
│    floor      │
└──────┬───────┘
       │1
       │
┌──────▼──────────┐     ┌──────────┐
│  parking_spot   │1───N│  ticket  │
└──────┬──────────┘     └────┬─────┘
       │                     │1
       │                     │
       │                ┌────▼─────┐
       │                │ payment  │
       │                └──────────┘
       │
┌──────▼──────────┐     ┌─────────────┐
│  rate_card      │     │ reservation │
└─────────────────┘     └─────────────┘

┌────────────┐
│ audit_log  │ (polymorphic: ticket, spot, payment)
└────────────┘
```

---

## 🏛️ Complete DDL

```sql
-- ============================================================
-- Parking Lot System - Production Database Schema
-- Database: PostgreSQL 16
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------
-- 1. PARKING LOT
-- -----------------------------------------------------------
CREATE TABLE parking_lot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    address TEXT,
    total_floors INT NOT NULL,
    total_spots INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 2. FLOOR
-- -----------------------------------------------------------
CREATE TABLE floor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parking_lot_id UUID NOT NULL REFERENCES parking_lot(id) ON DELETE CASCADE,
    floor_number INT NOT NULL CHECK (floor_number > 0),
    label VARCHAR(50),  -- "B1", "B2", "1", "2", "R" (rooftop)
    UNIQUE(parking_lot_id, floor_number)
);

-- -----------------------------------------------------------
-- 3. PARKING SPOT
-- -----------------------------------------------------------
CREATE TABLE parking_spot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    floor_id UUID NOT NULL REFERENCES floor(id) ON DELETE CASCADE,
    spot_number VARCHAR(10) NOT NULL,
    spot_type VARCHAR(20) NOT NULL 
        CHECK (spot_type IN ('MOTORCYCLE', 'COMPACT', 'LARGE', 'EV', 'HANDICAP')),
    status VARCHAR(20) DEFAULT 'AVAILABLE' 
        CHECK (status IN ('AVAILABLE', 'OCCUPIED', 'RESERVED', 'MAINTENANCE')),
    version INT DEFAULT 1,  -- Optimistic locking
    UNIQUE(floor_id, spot_number)
);

-- Composite index: find available spots by floor and type
CREATE INDEX idx_spot_floor_type_status 
    ON parking_spot(floor_id, spot_type, status);
-- Partial index: fast "is there ANY available spot?" check
CREATE INDEX idx_spot_available 
    ON parking_spot(id) WHERE status = 'AVAILABLE';

-- -----------------------------------------------------------
-- 4. TICKET
-- -----------------------------------------------------------
CREATE TABLE ticket (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spot_id UUID NOT NULL REFERENCES parking_spot(id),
    vehicle_license_plate VARCHAR(20) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMPTZ,
    fee DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'ACTIVE' 
        CHECK (status IN ('ACTIVE', 'PAID', 'LOST')),
    payment_method VARCHAR(20),
    payment_transaction_id VARCHAR(255),
    idempotency_key VARCHAR(64) UNIQUE,  -- Idempotent processing
    version INT DEFAULT 1,  -- Optimistic locking
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ticket_status ON ticket(status) WHERE status = 'ACTIVE';
CREATE INDEX idx_ticket_entry ON ticket(entry_time DESC);
CREATE INDEX idx_ticket_idempotency ON ticket(idempotency_key);

-- -----------------------------------------------------------
-- 5. RATE CARD
-- -----------------------------------------------------------
CREATE TABLE rate_card (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parking_lot_id UUID NOT NULL REFERENCES parking_lot(id),
    spot_type VARCHAR(20) NOT NULL,
    hourly_rate DECIMAL(8,2) NOT NULL,
    daily_max DECIMAL(8,2),
    weekly_rate DECIMAL(8,2),
    grace_period_minutes INT DEFAULT 15,
    is_active BOOLEAN DEFAULT true,
    effective_from DATE NOT NULL,
    effective_to DATE,
    UNIQUE(parking_lot_id, spot_type, effective_from)
);

-- -----------------------------------------------------------
-- 6. PAYMENT
-- -----------------------------------------------------------
CREATE TABLE payment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id UUID NOT NULL REFERENCES ticket(id),
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    method VARCHAR(20) NOT NULL 
        CHECK (method IN ('CASH', 'CARD', 'UPI', 'WALLET', 'SUBSCRIPTION')),
    status VARCHAR(20) DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED')),
    gateway_response JSONB,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 7. RESERVATION (optional, for advance booking)
-- -----------------------------------------------------------
CREATE TABLE reservation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parking_lot_id UUID NOT NULL REFERENCES parking_lot(id),
    spot_id UUID REFERENCES parking_spot(id),  -- NULL if spot not guaranteed
    customer_name VARCHAR(255),
    customer_phone VARCHAR(20),
    vehicle_license_plate VARCHAR(20),
    vehicle_type VARCHAR(20),
    reserved_from TIMESTAMPTZ NOT NULL,
    reserved_to TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'CONFIRMED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
    amount_charged DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- Exclusion constraint prevents overlapping reservations for same spot
    CONSTRAINT no_overlapping_reservation 
        EXCLUDE USING gist (
            spot_id WITH =,
            tstzrange(reserved_from, reserved_to) WITH &&
        )
);

-- -----------------------------------------------------------
-- 8. AUDIT LOG (for compliance and debugging)
-- -----------------------------------------------------------
CREATE TABLE audit_log (
    id BIGSERIAL,
    entity_type VARCHAR(50) NOT NULL,  -- 'ticket', 'spot', 'payment'
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,  -- 'CREATED', 'UPDATED', 'PAID', 'LOST'
    old_values JSONB,
    new_values JSONB,
    performed_by VARCHAR(255),  -- system or user ID
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);

-- -----------------------------------------------------------
-- KEY QUERY EXAMPLES
-- -----------------------------------------------------------

-- Find first available spot (used by entry processor)
SELECT ps.id, ps.spot_number, f.floor_number
FROM parking_spot ps
JOIN floor f ON ps.floor_id = f.id
WHERE ps.status = 'AVAILABLE'
  AND ps.spot_type IN ('COMPACT', 'LARGE')
  AND f.parking_lot_id = 'lot-uuid'
ORDER BY f.floor_number ASC, ps.spot_number ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;  -- Skip already-locked rows for concurrency

-- Calculate revenue by spot type for the current month
SELECT ps.spot_type, 
       COUNT(t.id) AS total_tickets,
       SUM(t.fee) AS total_revenue,
       AVG(t.fee) AS avg_fee
FROM ticket t
JOIN parking_spot ps ON t.spot_id = ps.id
WHERE t.exit_time >= date_trunc('month', CURRENT_DATE)
  AND t.status = 'PAID'
GROUP BY ps.spot_type
ORDER BY total_revenue DESC;
```

---

## 🔑 Redis Schema (Caching Layer)

```ascii
parking:{lot_id}:available_count        → STRING (total available spots)
parking:{lot_id}:floor:{n}:available     → SET (available spot IDs on floor n)
parking:{lot_id}:spot:{id}:status        → STRING (AVAILABLE/OCCUPIED/MAINTENANCE)
parking:{lot_id}:spot:{id}:lock          → STRING (distributed lock, TTL 5s)
```

---

## 📐 Table Relationships Summary

| # | Table | Parent FK | Child References | Key Indexes |
|---|-------|-----------|-----------------|-------------|
| 1 | `parking_lot` | — | `floor(parking_lot_id)`, `rate_card(parking_lot_id)`, `reservation(parking_lot_id)` | — |
| 2 | `floor` | `parking_lot_id → parking_lot` | `parking_spot(floor_id)` | UNIQUE(lot_id, floor_number) |
| 3 | `parking_spot` | `floor_id → floor` | `ticket(spot_id)`, `reservation(spot_id)` | (floor, type, status), available(partial) |
| 4 | `ticket` | `spot_id → parking_spot` | `payment(ticket_id)` | active(partial), entry DESC, idempotency |
| 5 | `rate_card` | `parking_lot_id → parking_lot` | — | UNIQUE(lot, type, effective_from) |
| 6 | `payment` | `ticket_id → ticket` | — | idempotency_key |
| 7 | `reservation` | `parking_lot_id → parking_lot`, `spot_id → parking_spot` | — | EXCLUDE(spot, tstzrange &&) |
| 8 | `audit_log` | polymorphic (entity_type, entity_id) | — | (entity_type, entity_id), created_at DESC |
