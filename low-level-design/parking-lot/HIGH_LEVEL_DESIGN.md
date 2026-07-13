# 🏗️ Parking Lot System — High-Level Design (Production)

> **Target Level:** Senior/Staff Engineer  
> **Focus:** Multi-floor parking, spot allocation, fee calculation, concurrency, resilience

---

## 1. SYSTEM OVERVIEW

**Purpose:** Multi-floor parking facility with automated fee collection and real-time spot allocation.

**Scale:** 10 floors × 500 spots = 5,000 total. Peak: 500 entries/hr, 500 exits/hr. Target 99.99% availability.

**Domain:** Smart mobility infrastructure with distributed entry/exit terminals.

---

## 2. SYSTEM ARCHITECTURE

```
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│ Entry        │          │ Exit         │          │ Admin        │
│ Terminal     │          │ Terminal     │          │ Dashboard    │
│ (Kiosk +     │          │ (Kiosk +     │          │ (Web UI)     │
│  Barrier)    │          │  Barrier)    │          │              │
└──────┬───────┘          └──────┬───────┘          └──────┬───────┘
       │                         │                         │
       └────────────┬────────────┘────────────┬────────────┘
                    │                         │
           ┌────────▼────────┐       ┌────────▼────────┐
           │  API Gateway    │       │  Message Queue  │
           │  (REST/WebSocket)│       │  (RabbitMQ/SQS)│
           └────────┬────────┘       └────────┬────────┘
                    │                         │
    ┌───────────────┼─────────────────────────┘
    │               │                         
┌───▼──────┐  ┌─────▼──────┐          ┌───────▼──────┐
│ Spot     │  │ Fee        │          │ Entry/Exit   │
│ Allocator│  │ Calculator │          │ Processor    │
│ Service  │  │ Service    │          │ (Async)      │
│ (Go)     │  │ (Python)   │          │ (Node.js)    │
└───┬──────┘  └─────┬──────┘          └───────┬──────┘
    │               │                         │
    └───────────────┼─────────────────────────┘
                    │
          ┌─────────▼──────────┐
          │  PostgreSQL (Aurora)││  + Redis Cache     │
  └────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="https://cpbrucemeena.github.io/interview-prep/assets/videos/parking-lot-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Parking Lot Sequence — Entry → Spot Allocation → Ticket → Payment → Exit. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. PARKING FLOW

### Entry Flow
```
1. Driver arrives at entry gate
2. Entry kiosk detects vehicle (ANPR camera)
3. Entry processor:
   a. Check availability (Redis cache hit: ~2ms)
   b. Find nearest available spot (floor-based preference)
   c. Create parking ticket with idempotency key
   d. Open barrier gate
   e. Update spot status → OCCUPIED
   f. Publish event: parking.entry (for analytics/display)
4. Driver parks at assigned spot
```

### Exit Flow
```
1. Driver arrives at exit gate
2. Exit kiosk reads ticket / ANPR lookup
3. Exit processor:
   a. Lookup ticket in PostgreSQL
   b. Calculate fee (base rate + duration + tax)
   c. Process payment (async via queue)
   d. If payment successful → open barrier
   e. Update spot → AVAILABLE
   f. Update ticket → PAID
   g. Publish event: parking.exit
4. Driver exits
```

---

## 4. KEY COMPONENTS & INTERVIEW Q&A

### Spot Allocation Service (Go)
- Finds nearest available spot matching vehicle type
- Maintains availability in Redis (O(1) lookups)
- Handles floor preference (closest floor to entrance fills first)

**🔴 Interview Question:** *"How do you handle concurrent entry requests at multiple gates?"*

**✅ Answer:** Use database-level pessimistic locking with a timeout:
```sql
BEGIN;
SELECT id FROM parking_spots
WHERE floor_id = ? AND status = 'AVAILABLE' AND spot_type = ?
ORDER BY floor_id ASC, id ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;  -- Skip already-locked rows
UPDATE parking_spots SET status = 'OCCUPIED' WHERE id = ?;
COMMIT;
```
`FOR UPDATE SKIP LOCKED` (PostgreSQL 9.5+) allows multiple concurrent entry processors to grab different spots without waiting for each other — essential for high-throughput scenarios.

### Fee Calculation Service (Python)
- Strategy Pattern: `HourlyFeeCalculator`, `DailyFeeCalculator`, `WeekendFeeCalculator`
- Supports promotions via Decorator Pattern
- Rounding: always round UP to avoid revenue loss

**🔴 Interview Question:** *"How would you implement fee calculation with different strategies?"*

**✅ Answer:** Strategy + Decorator pattern:
```python
# Strategy pattern for interchangeable fee logic
fee = HourlyFeeCalculator().calculate(duration, spot_type)

# Decorator pattern for composable add-ons
fee = TaxDecorator(
    WeekdaySurchargeDecorator(
        HourlyFeeCalculator()
    )
).calculate(duration, spot_type)
```

### Entry/Exit Processor (Node.js, Async)
- Processes entry/exit events via message queue
- Handles edge cases: lost tickets, overstay, payment failure
- Publishes events for real-time display boards

---

## 5. DATA MODEL & DB SCHEMA

### PostgreSQL Tables

**parking_lot:**
```sql
CREATE TABLE parking_lot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    address TEXT,
    total_floors INT NOT NULL,
    total_spots INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**floor:**
```sql
CREATE TABLE floor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parking_lot_id UUID NOT NULL REFERENCES parking_lot(id),
    floor_number INT NOT NULL CHECK (floor_number > 0),
    label VARCHAR(50),  -- "B1", "B2", "1", "2", "R"
    UNIQUE(parking_lot_id, floor_number)
);
```

**parking_spot:**
```sql
CREATE TABLE parking_spot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    floor_id UUID NOT NULL REFERENCES floor(id),
    spot_number VARCHAR(10) NOT NULL,
    spot_type VARCHAR(20) NOT NULL CHECK (spot_type IN ('MOTORCYCLE', 'COMPACT', 'LARGE', 'EV', 'HANDICAP')),
    status VARCHAR(20) DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'OCCUPIED', 'RESERVED', 'MAINTENANCE')),
    version INT DEFAULT 1,  -- For optimistic locking
    UNIQUE(floor_id, spot_number)
);

-- Composite index for availability queries
CREATE INDEX idx_spot_floor_type_status ON parking_spot(floor_id, spot_type, status);
-- Partial index for fast available spot lookup
CREATE INDEX idx_spot_available ON parking_spot(id) WHERE status = 'AVAILABLE';
```

**ticket:**
```sql
CREATE TABLE ticket (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spot_id UUID NOT NULL REFERENCES parking_spot(id),
    vehicle_license_plate VARCHAR(20) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMPTZ,
    fee DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAID', 'LOST')),
    payment_method VARCHAR(20),
    payment_transaction_id VARCHAR(255),
    idempotency_key VARCHAR(64) UNIQUE,  -- For idempotent processing
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ticket_status ON ticket(status) WHERE status = 'ACTIVE';
CREATE INDEX idx_ticket_entry ON ticket(entry_time DESC);
CREATE INDEX idx_ticket_idempotency ON ticket(idempotency_key);
```

**rate_card:**
```sql
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
```

**payment:**
```sql
CREATE TABLE payment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id UUID NOT NULL REFERENCES ticket(id),
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    method VARCHAR(20) NOT NULL CHECK (method IN ('CASH', 'CARD', 'UPI', 'WALLET', 'SUBSCRIPTION')),
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED')),
    gateway_response JSONB,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Redis Cache Keys

```ascii
parking:{lot_id}:available_count        → STRING (total available spots)
parking:{lot_id}:floor:{n}:available     → SET (available spot IDs on floor n)
parking:{lot_id}:spot:{id}:status        → STRING (AVAILABLE/OCCUPIED)
parking:{lot_id}:spot:{id}:lock          → STRING (distributed lock, TTL 5s)
```

### Performance Considerations

| Operation | Cache | DB | Latency |
|-----------|-------|----|---------|
| Check availability | Redis `GET available_count` | — | < 1ms |
| Find available spot | Redis `SPOP` from floor set | — | < 1ms |
| Create ticket | — | PostgreSQL INSERT | ~10ms |
| Check ticket on exit | Redis `GET ticket:{id}` | PostgreSQL (cache miss) | < 2ms / ~20ms |
| Calculate fee | — | PostgreSQL rate_card lookup | ~5ms |

---

## 6. CONCURRENCY & EDGE CASES

### Concurrency Handling

| Scenario | Approach | How |
|----------|----------|-----|
| Two gates check same spot simultaneously | `SELECT ... FOR UPDATE SKIP LOCKED` | Each transaction locks a different row |
| Payment timeout | Async queue + DLQ | Payment failed → retry 3x → send to DLQ → manual review |
| Display board updates | Redis Pub/Sub on spot status change | Real-time updates to all boards |
| Lost ticket | Flat fee charge + ID verification | `status = 'LOST'`, charge daily_max × 24h |

### Edge Cases

- **Vehicle leaves without paying:** ANPR at exit captures plate; ticket goes to LOST; fine sent to registered owner
- **System crash mid-parking:** Tickets persisted in PostgreSQL; on restart, active tickets are recovered
- **Grace period:** 15-minute grace for entry-exit without parking; no fee charged
- **Overstay after payment:** Pay-by-plate cameras at exit; re-calculate fee on actual exit time
- **Handicap spot misuse:** Penalty fee + warning to registered vehicle owner

---

## 7. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale | Alternative |
|----------|--------|-----------|-------------|
| Spot allocation | Nearest-available | Minimal driver walking | Even-distribution (balances floor usage) |
| Fee rounding | Always round UP | $0.005 × 10M = $50K/yr revenue protection | Round to nearest (fairer but costly) |
| Locking strategy | `SKIP LOCKED` | High throughput, no deadlocks | `NOWAIT` (fails immediately) or `FOR UPDATE` (blocks) |
| Cache layer | Redis | < 1ms reads, Pub/Sub for real-time | Memcached (faster but no Pub/Sub) |
| Async payments | Message queue | Decoupled, retryable, no blocking | Sync payment (blocks exit gate) |

---

## 8. COST (Monthly Estimate)

| Component | Configuration | Cost |
|-----------|--------------|------|
| Application servers (Go) | 4 instances, t3.medium | $400 |
| PostgreSQL (Aurora) | db.r6g.large, Multi-AZ, 100GB | $500 |
| Redis (ElastiCache) | cache.r6g.large, 1 node | $200 |
| Message Queue (SQS) | 1M requests | $30 |
| Entry/Exit kiosks (IoT) | 10 kiosks × $50 | $500 |
| Monitoring + logging | CloudWatch, Grafana | $100 |
| **Total** | | **$1,730** |
