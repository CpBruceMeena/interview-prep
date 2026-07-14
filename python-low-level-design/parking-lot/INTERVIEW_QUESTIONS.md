# Parking Lot System - Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer with 15+ years experience  
> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** OOD fundamentals, SOLID principles, design patterns, concurrency, trade-off analysis

---

## Question 1: Core Design
**Interviewer:** *"Design a parking lot system that can handle multiple floors, different vehicle types, and spot allocation."*

### 🎯 Expected Answer (Senior/Staff Level)

Let me walk through this systematically using an object-oriented approach grounded in SOLID principles.

**Step 1 — Clarify Scope:**
Before writing any code, I'd clarify: What are the vehicle types? How many floors? What's the pricing model? Do we need to support reservations or is it first-come-first-served? For this design, I'll assume motorcycles, cars, and trucks across a multi-floor lot with hourly billing.

**Step 2 — Class Hierarchy (LSP):**
The core modeling decision is the vehicle hierarchy. Rather than using a single `Vehicle` class with a `type` enum (which violates OCP — adding a new type means modifying conditional logic everywhere), I've made `Vehicle` an abstract base class:

```python
class Vehicle(ABC):
    def __init__(self, license_plate: str, vehicle_type: VehicleType):
        ...
    @abstractmethod
    def get_required_spot_type(self) -> SpotType:
        """Each vehicle knows what spot it needs"""
```

This follows **Liskov Substitution Principle** — any `Vehicle` subclass (Car, Truck, Motorcycle) is fully substitutable for the base class. The caller doesn't need to check instance types.

**Step 3 — Spot Allocation (SRP + OCP):**
The `SpotAllocationMapping` class is a separate concern from vehicle management:

```python
_mapping = {
    VehicleType.MOTORCYCLE: {SpotType.MOTORCYCLE, SpotType.COMPACT, SpotType.LARGE},
    VehicleType.CAR: {SpotType.COMPACT, SpotType.LARGE},
    VehicleType.TRUCK: {SpotType.LARGE},
}
```

This follows **Open/Closed Principle** — adding a new vehicle type like `ElectricCar` means adding a new entry to the mapping dictionary, not modifying existing logic.

**Step 4 — Encapsulation:**
Each `ParkingSpot` encapsulates its own state (available/occupied), and `ParkingFloor` composes spots. This gives us clean separation — spot-level operations don't leak into floor-level logic.

### 🔍 Interviewer's Evaluation Points

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Abstraction** | Candidate doesn't start coding immediately — scopes first |
| **Encapsulation** | Spot state is private, accessed through methods |
| **Polymorphism** | Uses abstract base class, not type-checking |
| **Composition** | Floor has Spots, Lot has Floors |

### 💡 Technical Deep Dive

**Why not a simple VehicleType enum with switch statements?**

Because every `if vehicle_type == TRUCK` scattered across 10 methods violates OCP. When you add `ElectricCar`, you need to find and update all those conditionals. With polymorphism, you add one class and one mapping entry — zero existing code changes.

**Why separate SpotAllocationMapping from Vehicle?**

SRP: A `Vehicle` knows *what* it needs, but *how* spots map to vehicles is a separate business rule. If the parking lot wants to change the mapping (e.g., compact cars can now park in large spots), they change the mapping class, not the vehicle class.

---

## Question 2: Concurrency & Race Conditions
**Interviewer:** *"How would you handle concurrent parking requests in a multi-threaded environment?"*

### 🎯 Expected Answer

**🔴 The Problem:**
Two threads check `is_available` simultaneously, both see `True`, and both park vehicles — double-booking the same spot.

**✅ Solution: Lock-based spot allocation**

```python
import threading

class ParkingLot:
    def __init__(self):
        self._lock = threading.Lock()
    
    def park_vehicle(self, vehicle: Vehicle) -> Optional[ParkingTicket]:
        with self._lock:  # Critical section
            spot = self.find_available_spot(vehicle)
            if not spot:
                return None
            spot.park(vehicle)
            ticket = self._ticket_manager.create_ticket(spot, vehicle)
            return ticket
```

**💼 Production-Grade Solution (Distributed):**

In a real system with multiple entry/exit terminals, application-level locks don't work across processes. You'd need:

1. **Pessimistic locking (Database):**
   ```sql
   BEGIN TRANSACTION;
   SELECT * FROM parking_spots 
   WHERE spot_id = ? AND status = 'AVAILABLE'
   FOR UPDATE;
   UPDATE parking_spots SET status = 'OCCUPIED' WHERE spot_id = ?;
   COMMIT;
   ```

2. **Optimistic locking (Application):**
   ```sql
   UPDATE parking_spots 
   SET status = 'OCCUPIED', version = version + 1
   WHERE spot_id = ? AND status = 'AVAILABLE' AND version = ?
   ```
   Check affected row count — if 0, another transaction beat you.

3. **Redis distributed lock (Redlock algorithm):**
   ```python
   # Acquire lock with TTL
   lock_key = f"lock:spot:{spot_id}"
   acquired = redis.setnx(lock_key, "locked", ttl=5000)  # 5 second TTL
   ```

### 🔍 Trade-off Analysis

| Approach | Pros | Cons | When to Use |
|----------|------|------|-------------|
| Threading.Lock | Simple, fast | Single process only | Single-server app |
| DB Pessimistic | Accurate, durable | Lower throughput, deadlock risk | High contention |
| DB Optimistic | Higher throughput | Retry overhead on conflict | Low contention |
| Redis Lock | Distributed, fast | Complexity, TTL management | Multi-server deployment |

---

## Question 3: Fee Calculation (Strategy Pattern)
**Interviewer:** *"How would you implement fee calculation that supports different strategies for different customers?"*

### 🎯 Expected Answer

**The Strategy Pattern in action:**

```python
class FeeCalculator(ABC):
    """Interface Segregation: minimal, focused interface"""
    @abstractmethod
    def calculate_fee(self, duration_hours: float, spot_type: SpotType) -> float:
        pass

class HourlyFeeCalculator(FeeCalculator): ...
class DailyFeeCalculator(FeeCalculator): ...
class WeekendFeeCalculator(FeeCalculator): ...
```

**Dependency Inversion in practice:**
```python
class ParkingLot:
    def __init__(self, fee_calculator: FeeCalculator):
        # Depends on abstraction, not concrete implementation
        self._fee_calculator = fee_calculator
    
    def set_fee_calculator(self, fee_calculator: FeeCalculator):
        # Strategy can be swapped at runtime
        self._fee_calculator = fee_calculator
```

**Why this matters at scale:**
- New pricing promotions (Black Friday 20% off) → new Strategy class
- VIP customer pricing → can wrap base strategy with discount decorator
- Surge pricing during peak hours → time-based strategy selection

### 💡 Real-world Production Considerations

1. **Fee rounding:** Always round UP, not nearest. $0.005 rounding per transaction across 10M transactions is $50,000 lost.
2. **Grace periods:** Many lots give 15-min grace. Model this as a `FreePeriodDecorator(FeeCalculator)`.
3. **Lost tickets:** Flat fee (e.g., $50) — different concern, handled by a different calculator.
4. **Currency/regional differences:** Some cities have tax on parking — compose with `TaxDecorator(FeeCalculator)`.

---

## Question 4: Database Schema
**Interviewer:** *"Design the database schema for a parking lot handling 10,000+ spots."*

### 🎯 Expected Answer

```sql
-- Core tables

CREATE TABLE parking_lot (
    id BIGINT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    total_spots INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE floor (
    id BIGINT PRIMARY KEY,
    parking_lot_id BIGINT REFERENCES parking_lot(id),
    floor_number INT NOT NULL,
    UNIQUE(parking_lot_id, floor_number)
);

CREATE TABLE parking_spot (
    id BIGINT PRIMARY KEY,
    floor_id BIGINT REFERENCES floor(id),
    spot_number VARCHAR(10) NOT NULL,
    spot_type VARCHAR(20) NOT NULL,  -- MOTORCYCLE, COMPACT, LARGE
    status VARCHAR(20) DEFAULT 'AVAILABLE',
    version INT DEFAULT 1,  -- For optimistic locking
    UNIQUE(floor_id, spot_number),
    INDEX idx_status (status),
    INDEX idx_floor_type (floor_id, spot_type, status)
);

CREATE TABLE ticket (
    id BIGINT PRIMARY KEY,
    spot_id BIGINT REFERENCES parking_spot(id),
    vehicle_license VARCHAR(20) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    fee DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    INDEX idx_status_entry (status, entry_time)
);
```

**Performance considerations for 10K+ spots:**
- **Index strategy:** Composite index on `(spot_type, status)` for availability queries
- **Partitioning:** Partition `ticket` table by month for query performance
- **Caching:** Cache available spot counts in Redis, invalidate on ticket creation
- **Read replicas:** Route availability queries to replicas, writes to primary

---

## Question 5: Multi-City Scale
**Interviewer:** *"How would you design this for a multi-city parking chain?"*

### 🎯 Expected Answer

**Architecture:**
```
┌─────────────────────────────────────────────────┐
│                   API Gateway                     │
├─────────────────────────────────────────────────┤
│      Region Router (geo-routing by city)         │
└──────────┬──────────────┬──────────────────────┘
           │              │
    ┌──────▼──────┐  ┌───▼────────┐
    │ Bangalore    │  │ Mumbai      │
    │ Cluster      │  │ Cluster     │
    │              │  │             │
    │ ┌──────────┐ │  │ ┌─────────┐ │
    │ │ Parking  │ │  │ │ Parking │ │
    │ │ Lot DB   │ │  │ │ Lot DB  │ │
    │ └──────────┘ │  │ └─────────┘ │
    └──────────────┘  └─────────────┘
```

**Key decisions:**
- **Database per city** — data locality, independent failure domains
- **Global Redis cache** for cross-city availability queries (TTL: 30 seconds)
- **Eventual consistency** for cross-city bookings — if City A wants to book in City B, use async messaging
- **CQRS pattern** — separate read/write paths to scale availability queries independently

---

## Question 6: Edge Cases
**Interviewer:** *"Walk me through how you'd handle these edge cases."*

| Edge Case | Solution |
|-----------|----------|
| **Lost ticket** | Charge max daily rate × 24h, need ID verification to exit |
| **Overstay after payment** | Pay-by-plate cameras, automatic fee recalc on exit |
| **System crash mid-parking** | Transaction log replay, barrier manually override-able |
| **Invalid license plate** | Accept any format, validate only on exit payment |
| **Handicap spot reservation** | Separate spot type, shorter grace period, higher fine for misuse |
| **Gate arm malfunction** | Manual override with supervisor auth, offline fallback mode |

---

## Question 7: Design Patterns Inventory

| Pattern | Where | Why |
|---------|-------|-----|
| **Singleton** | ParkingLot | Single entry point for lot operations |
| **Factory** | VehicleFactory | Centralizes vehicle creation |
| **Strategy** | FeeCalculator | Interchangeable pricing algorithms |
| **Observer** | DisplayBoard | Real-time updates when spot status changes |
| **State** | Ticket | ACTIVE → PAID → LOST lifecycle |
| **Facade** | ParkingLot | Unified interface over subsystems |
| **Decorator** | FeeCalculator wrappers | Add seasonal surcharge without modifying core |

---

## Question 8: SOLID Principles Deep Dive

**🔹 Single Responsibility —** Prove it by asking: *"What changes would cause this class to change?"*
- `ParkingSpot` changes only if spot mechanics change (status, parking)
- `TicketManager` changes only if ticketing logic changes
- `FeeCalculator` changes only if pricing rules change

**🔹 Open/Closed —** *"How do I add a new vehicle type?"*
- Add new enum value in `VehicleType`
- Create new `Vehicle` subclass
- Add mapping entry in `SpotAllocationMapping`
- Zero existing code modifications ✅

**🔹 Liskov Substitution —** *"Can I pass any Vehicle to park_vehicle()?"*
- Yes — `Motorcycle`, `Car`, `Truck` all implement `get_required_spot_type()`
- The caller never needs `isinstance()` checks

**🔹 Interface Segregation —** *"Is my FeeCalculator interface minimal?"*
- One method: `calculate_fee(duration, spot_type)` — that's it
- Not polluted with unrelated concerns like payment processing

**🔹 Dependency Inversion —** *"Does ParkingLot depend on concrete FeeCalculator?"*
- No — constructor accepts `FeeCalculator` interface
- Can swap Hourly→Daily→Weekend without changing ParkingLot

---

## 📊 Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Questions the requirements first. Recognizes trade-offs unprompted. References real production experience. Discusses monitoring, error budgets, SLOs. |
| **4 — Strong** | Solid OOD principles. Knows design patterns. Good class separation. Misses some edge cases. |
| **3 — Competent** | Basic classes work. Knows SOLID but can't articulate why they matter. No real-world production discussion. |
| **2 — Developing** | One big class with if-else chains. No abstraction. Struggles with extensibility. |
| **1 — Needs Growth** | No OOP design. Everything in procedural code. Can't explain trade-offs. |
