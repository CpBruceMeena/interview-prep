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
The `SpotAllocationMapping` class is a separate concern from vehicle management. It derives the allowed spot types from the vehicle's minimum spot and returns them **smallest first**, which is what makes allocation best-fit:

```python
@staticmethod
def get_allowed_spots(vehicle: Vehicle) -> Tuple[SpotType, ...]:
    required = vehicle.get_required_spot_type().size
    return tuple(sorted((t for t in SpotType if t.size >= required),
                        key=lambda t: t.size))
```

Order matters. An earlier version returned a Python `set`, whose iteration order for enums is arbitrary, so a car could land in a LARGE spot while COMPACT spots were free and starve trucks. A new vehicle subclass needs no entry here; a new *rule* (EV-only spots) is a change to this one class.

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

**✅ Solution: Lock-based spot allocation** (this is what `parking_lot.py` does)

```python
def park_vehicle(self, vehicle: Vehicle) -> ParkingTicket:
    with self._lock:  # check-then-act must be one critical section
        if vehicle.license_plate in self._active_by_plate:
            raise VehicleAlreadyParkedError(...)
        spot = self._find_spot_locked(vehicle)
        if spot is None:
            raise ParkingFullError(...)
        self._floor_by_number[spot.floor].occupy(spot, vehicle)
        ticket = self._ticket_manager.create_ticket(spot, vehicle, self._clock())
        self._active_by_plate[vehicle.license_plate] = ticket
        return ticket
```

Note the private `_find_spot_locked`: the public `find_available_spot` also takes the lock, and `threading.Lock` is not re-entrant, so calling the public method from inside the critical section would deadlock. Splitting "public, locks" from "private, assumes lock held" is the standard fix (an `RLock` also works but hides the layering).

**💼 Production-Grade Solution (Distributed):**

In a real system with multiple entry/exit terminals, application-level locks don't work across processes. You'd need:

1. **Pessimistic locking (Database):**
   ```sql
   BEGIN;
   SELECT id FROM parking_spot
   WHERE spot_type = 'COMPACT' AND status = 'AVAILABLE'
   ORDER BY floor_id, spot_number
   LIMIT 1
   FOR UPDATE SKIP LOCKED;          -- concurrent gates get different rows
   UPDATE parking_spot SET status = 'OCCUPIED' WHERE id = :picked;
   INSERT INTO ticket (...) VALUES (...);
   COMMIT;
   ```
   Plain `FOR UPDATE` without `SKIP LOCKED` makes every gate queue on the same "first free" row.

2. **Optimistic locking (Application):**
   ```sql
   UPDATE parking_spots 
   SET status = 'OCCUPIED', version = version + 1
   WHERE spot_id = ? AND status = 'AVAILABLE' AND version = ?
   ```
   Check affected row count — if 0, another transaction beat you.

3. **Redis lock (single instance):**
   ```python
   token = uuid4().hex
   acquired = redis.set(f"lock:spot:{spot_id}", token, nx=True, px=5000)
   # release only if we still own it (Lua compare-and-delete), never a bare DEL
   ```
   `SETNX` has no TTL argument; `SET key val NX PX ms` is the atomic form. A Redis lock is advisory and can expire mid-operation (GC pause), so the DB write still needs its own guard (`WHERE status = 'AVAILABLE'` or a fencing token). For a parking lot the DB alone is enough; Redis locking adds a failure mode without buying throughput you need.

### 🔍 Trade-off Analysis

| Approach | Pros | Cons | When to Use |
|----------|------|------|-------------|
| Threading.Lock | Simple, fast | Single process only | Single-server app |
| DB Pessimistic | Accurate, durable | Lower throughput, deadlock risk | High contention |
| DB Optimistic | Higher throughput | Retry overhead on conflict | Low contention |
| Redis Lock | Distributed, fast | Lock can expire mid-write; still need a DB guard | Rarely; only when the protected resource isn't in a DB |

---

## Question 3: Fee Calculation (Strategy Pattern)
**Interviewer:** *"How would you implement fee calculation that supports different strategies for different customers?"*

### 🎯 Expected Answer

**The Strategy Pattern in action:**

```python
class FeeCalculator(ABC):
    """Interface Segregation: minimal, focused interface"""
    @abstractmethod
    def calculate_fee(self, duration: timedelta, spot_type: SpotType) -> Decimal:
        ...

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

1. **Money type and rounding:** Use `Decimal` (DB: `NUMERIC(10,2)`), never float. Billing *units* round up (2 h 10 m is 3 started hours, `math.ceil(duration / timedelta(hours=1))`); the final currency amount is quantized once, at the end, with an explicit rounding mode.
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
    UNIQUE(floor_id, spot_number)
);
CREATE INDEX idx_spot_type_status ON parking_spot(spot_type, status, floor_id);

CREATE TABLE ticket (
    id BIGINT PRIMARY KEY,
    spot_id BIGINT REFERENCES parking_spot(id),
    vehicle_license VARCHAR(20) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    fee NUMERIC(10,2),
    status VARCHAR(20) DEFAULT 'ACTIVE'
);
-- The DB enforces the invariants the in-memory lock enforces:
CREATE UNIQUE INDEX one_active_ticket_per_spot  ON ticket(spot_id)         WHERE status = 'ACTIVE';
CREATE UNIQUE INDEX one_active_ticket_per_plate ON ticket(vehicle_license) WHERE status = 'ACTIVE';
```

The two partial unique indexes are the staff-level detail: even if application locking has a bug, the database refuses a double-booked spot or a plate parked twice.

**Performance considerations for 10K+ spots:**
- **Size check first:** 10K spots is a tiny table that fits in memory. Even 1,000 entries/hour is well under 1 write/second. Don't reach for sharding or caches to solve load; reach for them only for multi-lot aggregation or availability fan-out to apps.
- **Index strategy:** Composite index on `(spot_type, status, floor_id)` for availability queries
- **Partitioning:** `ticket` grows forever (≈ 10K spots × a few turns/day ≈ 10M+ rows/year); partition by month so old partitions can be archived
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
- **Lot is the consistency boundary.** A spot is only ever claimed in its own lot's DB, so there is no cross-region transaction. Availability shown to apps is a cached, eventually consistent view (a few seconds stale is fine; the gate is the final check).
- **Cross-city bookings** go to the owning region (route by lot id), not via a global write path
- **CQRS pattern** — separate read/write paths to scale availability queries independently

---

## Question 6: Edge Cases
**Interviewer:** *"Walk me through how you'd handle these edge cases."*

| Edge Case | Solution |
|-----------|----------|
| **Lost ticket** | Look up the active session by plate (ANPR or manual), charge fee-so-far + flat penalty (`unpark_lost_ticket`), require ID |
| **Overstay after payment** | Pay-by-plate cameras, automatic fee recalc on exit |
| **System crash mid-parking** | Transaction log replay, barrier manually override-able |
| **Invalid license plate** | Accept any format, validate only on exit payment |
| **Handicap spot reservation** | Separate spot type, shorter grace period, higher fine for misuse |
| **Gate arm malfunction** | Manual override with supervisor auth, offline fallback mode |

---

## Question 7: Design Patterns Inventory

| Pattern | Where | Status in code |
|---------|-------|----------------|
| **Strategy** | `FeeCalculator` | Implemented (`HourlyFeeCalculator`, `DailyFeeCalculator`) |
| **Factory** | `VehicleFactory` | Implemented |
| **Facade** | `ParkingLot` | Implemented; also owns the lock |
| **Decorator** | `FeeCalculator` wrappers (grace period, tax) | Natural extension, not implemented |
| **Observer** | Display boards, analytics | Only worth it with several subscribers; the code's `DisplayBoard` pulls |

**Don't claim Singleton.** A singleton `ParkingLot` makes every test share one lot and blocks running two lots in one process. If someone asks, say "one instance, wired at startup", which is dependency injection, not a singleton. Likewise ticket status is an enum with a guard, not the State pattern.

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

## Question 9: The Follow-ups Interviewers Actually Push On

**"Now add EV charging spots."**
Add `SpotType.EV`, an `ElectricCar` subclass, and a rule in `SpotAllocationMapping`: EVs try EV spots first and fall back to normal ones; non-EVs never take EV spots. Allocation, locking and tickets don't change. Bonus: charge for electricity as a separate fee line, not inside the parking strategy.

**"Two gates call park at the same time and both get the same spot. Fix it."**
The race is between *choosing* and *claiming*. Wrap find + occupy + ticket in one lock (single process) or make the claim conditional in the DB (`UPDATE parking_spot SET status='OCCUPIED' WHERE id=? AND status='AVAILABLE'`, check rowcount = 1). Locking `ParkingSpot.park()` alone does not help.

**"The same exit ticket is scanned twice (retry, double-tap)."**
`unpark_vehicle` takes the lock and `ParkingTicket.close()` rejects a non-ACTIVE ticket, so the second call raises `InvalidTicketError` and nobody is charged twice. In a service, make exit idempotent instead: the client sends an idempotency key and a retry returns the *original* receipt rather than an error.

**"Payment fails after you've computed the fee."**
Don't free the spot or close the ticket until payment succeeds: compute fee → authorize → on success mark PAID and release. On failure the ticket stays ACTIVE and the barrier stays closed. Split `close()` into `quote()` and `settle()` if this is in scope.

**"Add reservations."**
A reservation holds a spot for a time window. In memory: remove the spot from the floor's free index while reserved and re-add on expiry/cancel. In the DB: a GiST exclusion constraint on `(spot_id, tstzrange)` prevents overlaps. Decide whether a reservation guarantees a specific spot or just capacity of a type; capacity is easier to honour and much more efficient.

**"How do you test this?"**
Inject the clock (`ManualClock`) so "2 h 10 m → 3 hours" is an exact assertion with no sleeping. Unit-test best-fit order, full lot, duplicate plate, double unpark, lost ticket, rounding boundaries (exactly 1 h vs 1 h + 1 s). For concurrency, release 100 threads through a `threading.Barrier` against 55 spots and assert exactly 55 tickets, 55 distinct spots, 45 `ParkingFullError`.

**"Performance: the lot has 50,000 spots."**
Scanning all spots per entry is O(N). Keep a free index per (floor, spot type) so a pick is O(floors × types); with a min-heap per type you also get "lowest spot number first" in O(log n).

---

## ⚠️ Common Mistakes

- Using a `set` for allowed spot types, then iterating it: allocation order becomes arbitrary and cars eat truck spots.
- Locking only inside `ParkingSpot.park()`, leaving the find/claim race open.
- Calling a locking public method from inside the lock with a non-reentrant `Lock` (deadlock).
- `float` money and `datetime.now()` hard-coded inside the ticket, which makes fees untestable without `sleep()`.
- Returning `None` and printing on failure, so callers can't distinguish "lot full" from "bad ticket".
- No guard against a ticket being closed twice, or a plate parking twice.
- Declaring `ParkingLot` a Singleton and listing patterns the code doesn't use.
- Jumping to Redis/Kafka/microservices for a workload of under one write per second.

## 🎚️ Senior vs Staff Signal

- **Senior:** clean entities and interfaces, working best-fit allocation, a correct critical section, Decimal money, exceptions, a few targeted tests, and a fee strategy that extends cleanly.
- **Staff:** all of the above, plus: sizes the problem first and says the load is tiny, picks the DB as the source of truth and pushes invariants into it (partial unique indexes, conditional updates), designs idempotent entry/exit for flaky gate hardware, separates fee quote from settlement for payment failures, and explains which patterns they deliberately *didn't* use.

---

## 📊 Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Questions the requirements first. Recognizes trade-offs unprompted. References real production experience. Discusses monitoring, error budgets, SLOs. |
| **4 — Strong** | Solid OOD principles. Knows design patterns. Good class separation. Misses some edge cases. |
| **3 — Competent** | Basic classes work. Knows SOLID but can't articulate why they matter. No real-world production discussion. |
| **2 — Developing** | One big class with if-else chains. No abstraction. Struggles with extensibility. |
| **1 — Needs Growth** | No OOP design. Everything in procedural code. Can't explain trade-offs. |
