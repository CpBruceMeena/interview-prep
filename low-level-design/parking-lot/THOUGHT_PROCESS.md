# 🧠 Parking Lot LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design, not just *what* the final code looks like.
> Walk through the mental steps, decision points, and trade-offs you should make.

---

## 📊 Class Diagram

![Class Diagram](parking-lot-class-diagram.drawio)

---

## Table of Contents

1. [Phase 0: Requirements Gathering](#phase-0-requirements-gathering)
2. [Phase 1: Identify the Nouns (Entities)](#phase-1-identify-the-nouns-entities)
3. [Phase 2: Enums — Your First Building Block](#phase-2-enums--your-first-building-block)
4. [Phase 3: Which Classes Need Methods? (dataclass vs `__init__`)](#phase-3-which-classes-need-methods-dataclass-vs-__init__)
5. [Phase 4: Assigning Responsibilities (Which Function Goes Where)](#phase-4-assigning-responsibilities-which-function-goes-where)
6. [Phase 5: Relationships & Composition](#phase-5-relationships--composition)
7. [Phase 6: Polymorphism & Inheritance](#phase-6-polymorphism--inheritance)
8. [Phase 7: Design Patterns — When & Why](#phase-7-design-patterns--when--why)
9. [Phase 8: Review & Refine Checklist](#phase-8-review--refine-checklist)

---

## 📊 Class Diagram

![Class Diagram](parking-lot-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

**Before you write a single line of code, ask these questions:**

| Question | Why It Matters | Example Answer |
|----------|---------------|----------------|
| What vehicle types exist? | Determines your entity hierarchy | Motorcycle, Car, Truck |
| How many floors? | Composition: Lot → Floors → Spots | 2 floors |
| How is pricing calculated? | Determines your Strategy pattern | Hourly rates vary by spot type |
| Is it first-come-first-served or reservation-based? | Affects spot allocation logic | First-come-first-served |
| Do we need a display board? | Adds Observer-like behavior | Yes, show availability |
| Can a vehicle park in any spot? | Creates allocation rules | Motorcycles can use any spot |

**💡 Interview Tip:** Always clarify scope before writing code. It shows you think about the problem before diving into the solution. Say: *"Let me clarify a few things before I start — what vehicle types, how many floors, what pricing model?"*

---

## Phase 1: Identify the Nouns (Entities)

Take the requirements and **circle every noun**. These are your candidate classes.

> *"A parking lot has multiple floors. Each floor has parking spots of different sizes. A vehicle arrives, parks in a spot, gets a ticket, and pays a fee based on how long it stayed."*

**Nouns extracted:**
- Parking Lot
- Floor
- Parking Spot
- Vehicle (Motorcycle, Car, Truck)
- Ticket
- Fee / Payment
- Display Board

**Thought Process:**

> *"I see that 'Parking Lot' contains 'Floors', and 'Floors' contain 'Spots'. That's **composition** — a 'has-a' relationship. 'Vehicle' is a general thing with specific types — that's **inheritance**. 'Ticket' is created when a vehicle parks — that's an **association**."*

**Rule of Thumb:** If a noun has state AND behavior, it's a class. If it only has fixed values, it's likely an Enum. If it's a passive data holder, consider a dataclass.

| Noun | Class or Enum? | Why |
|------|---------------|-----|
| Vehicle Type | Enum | Fixed set of categories (MOTORCYCLE, CAR, TRUCK) |
| Spot Type | Enum | Fixed set of spot sizes |
| Ticket Status | Enum | Fixed lifecycle states (ACTIVE, PAID, LOST) |
| Vehicle | Abstract Class | Has data (license plate) + behavior (get_required_spot_type) |
| Parking Spot | Regular Class | Has state (available/occupied) + behavior (park, vacate) |
| Parking Ticket | Regular Class | Has state + behavior (close/calculate fee) |
| Fee Calculator | Interface/Abstract Class | Multiple implementations (hourly, daily) |

---

## Phase 2: Enums — Your First Building Block

**Always define Enums first.** They are the vocabulary of your system. Every other class will reference them.

```python
from enum import Enum

class VehicleType(Enum):
    MOTORCYCLE = "Motorcycle"
    CAR = "Car"
    TRUCK = "Truck"

class SpotType(Enum):
    MOTORCYCLE = "Motorcycle"
    COMPACT = "Compact"
    LARGE = "Large"

class ParkingTicketStatus(Enum):
    ACTIVE = "Active"
    PAID = "Paid"
    LOST = "Lost"
```

### Thought Process: Why Enums Instead of Strings or Constants?

| Approach | Problem | Why Enums Win |
|----------|---------|---------------|
| Plain strings: `"car"`, `"truck"` | Typo risk: `"cAr"` vs `"car"` | Enums are type-safe, no typos |
| Constants: `CAR = "car"`, `TRUCK = "truck"` | No namespace — they pollute the module | Enums are self-namespaced: `VehicleType.CAR` |
| Booleans: `is_motorcycle=True` | Adding a 4th type breaks everything | Enums scale without breaking existing code |

**💡 Key Insight:** Enums are your **type system within the type system**. They let you write:
```python
def get_allowed_spots(self, vehicle_type: VehicleType) -> set[SpotType]:
```
The type hints tell the reader exactly what values are valid.

---

## Phase 3: Which Classes Need Methods? (dataclass vs `__init__`)

This is one of the most important decisions in LLD. The answer depends on whether the class has **behavior** or is just **passive data**.

### When to Use `@dataclass`

Use `dataclass` when the class is **just a container for data** with minimal or no logic.

```python
from dataclasses import dataclass

@dataclass
class Address:
    street: str
    city: str
    zip_code: str

@dataclass
class RateInfo:
    spot_type: SpotType
    hourly_rate: float
    daily_max: float
```

**Signs you need a dataclass:**
- The class only holds data, no methods (or just `__repr__` / display helpers)
- You want auto-generated `__init__`, `__repr__`, `__eq__`
- The class is used primarily as a return value from another method
- You need to **compare instances** by value, not identity

### When to Use `__init__`

Use regular `__init__` when the class has **actual behavior or business logic**.

```python
class ParkingSpot:
    def __init__(self, spot_id: str, floor: int, spot_type: SpotType):
        self._spot_id = spot_id
        self._floor = floor
        self._spot_type = spot_type
        self._is_available = True
        self._parked_vehicle: Optional[Vehicle] = None

    def park(self, vehicle: Vehicle) -> None:    # Has behavior!
        if not self._is_available:
            raise ValueError("Already occupied")
        self._parked_vehicle = vehicle
        self._is_available = False

    def vacate(self) -> Vehicle:                   # Has behavior!
        ...
```

**Signs you need a regular class with `__init__`:**
- The class has **methods that change its state** (`park()`, `vacate()`, `close()`)
- You want to **encapsulate** internal state (private attributes with `_`)
- You need **properties** to control access (`@property`)
- The class participates in a **design pattern** (Strategy, Observer, etc.)

### Decision Tree

```
Does the class only hold data?
├── YES → Can I use @dataclass?
│   ├── YES → @dataclass (auto __init__, __eq__, __repr__)
│   └── NO  → Simple __init__ (rare)
└── NO  → Does it have behavior?
    ├── YES → Regular class with __init__ + methods
    └── YES → Is it an interface/contract?
        ├── YES → ABC (abstract base class)
        └── YES → Use ABC + @abstractmethod
```

### Applied to Parking Lot

```python
# DATACLASS candidates (passive data):
# - RateInfo (just holds spot type + rates)
# - PaymentInfo (holds payment details, no behavior)

# REGULAR CLASS candidates (has behavior + state):
# - ParkingSpot (park(), vacate()) ← STATE CHANGES
# - ParkingTicket (close()) ← STATE CHANGES
# - ParkingFloor (add_spot(), get_available_spots())
# - ParkingLot (park_vehicle(), unpark_vehicle())

# ABC candidates (contract/interface):
# - Vehicle (abstract, different types)
# - FeeCalculator (abstract, different strategies)
```

---

## Phase 4: Assigning Responsibilities (Which Function Goes Where)

This is **Single Responsibility Principle** in action. For each function you identify, ask: *"Which class owns this?"*

### Step 1: List all behaviors

From the requirements, extract every action:

| Action | Who Does It? | Why? |
|--------|-------------|------|
| Park a vehicle in a spot | `ParkingSpot.park()` | Spot owns its state |
| Vacate a spot | `ParkingSpot.vacate()` | Spot owns its state |
| Find an available spot | `ParkingLot.find_available_spot()` | Lot knows all floors & spots |
| Create a ticket | `TicketManager.create_ticket()` | TicketManager owns ticket lifecycle |
| Calculate fee | `FeeCalculator.calculate_fee()` | FeeCalculator owns pricing logic |
| Close a ticket | `ParkingTicket.close()` | Ticket owns its lifecycle |
| Show available spots | `DisplayBoard.display()` | DisplayBoard owns output formatting |
| Determine allowed spots for a vehicle | `SpotAllocationMapping.get_allowed_spots()` | Mapping owns allocation rules |

### Step 2: Apply the "Why" Test

For each method you're about to write, ask: **"Why does this method belong in this class?"**

```
Method: park_vehicle(vehicle)
Class: ParkingLot
Q: Why does ParkingLot own this?
A: Because ParkingLot orchestrates the full flow: 
   1. Find a spot (uses floors/spots)
   2. Park in the spot (delegates to ParkingSpot.park())
   3. Create a ticket (delegates to TicketManager)
   It's the Facade — the single entry point.

Method: close(fee_calculator)
Class: ParkingTicket
Q: Why does ParkingTicket own this?
A: Because closing a ticket means:
   1. Recording exit time (ticket's own data)
   2. Calculating duration (ticket's own data)
   3. Computing fee (delegates to FeeCalculator)
   4. Updating status (ticket's own state)
   = Everything related to the ticket's lifecycle lives HERE.
```

### Step 3: The "Cohesion" Check

**High cohesion** = a class's methods all work toward a single purpose.

```python
# ✅ GOOD: ParkingSpot — high cohesion
class ParkingSpot:
    def park(self, vehicle)     # related to spot occupancy
    def vacate(self)            # related to spot occupancy
    # BOTH methods are about managing spot state

# ❌ BAD: ParkingSpot — low cohesion
class ParkingSpot:
    def park(self, vehicle)            # spot management
    def calculate_fee(self, duration)  # ❌ fee calculation? Not the spot's job!
    def send_notification(self, msg)   # ❌ notifications? Not the spot's job!
```

**💡 Rule of Thumb:** If you use "and" to describe what a class does, it probably has too many responsibilities. Example:
> *"ParkingSpot manages spot state **and** calculates fees **and** sends notifications"* → ❌ Break it up!

---

## Phase 5: Relationships & Composition

### Has-A vs Is-A

This is the most critical relationship decision you'll make.

**Composition (Has-A):**
```python
class ParkingLot:
    def __init__(self):
        self._floors: List[ParkingFloor] = []  # ParkingLot HAS floors

class ParkingFloor:
    def __init__(self):
        self._spots: Dict[str, ParkingSpot] = {}  # Floor HAS spots
```

**Inheritance (Is-A):**
```python
class Vehicle(ABC):          # Base type
    ...

class Car(Vehicle):          # Car IS-A Vehicle  ✅
class Truck(Vehicle):        # Truck IS-A Vehicle  ✅
```

### Thought Process: Composition vs Inheritance

| Scenario | Decision | Reasoning |
|----------|----------|-----------|
| Floor and Spot | **Composition** | A floor *has* spots. Spots don't exist without a floor. |
| Lot and Floor | **Composition** | A lot *has* floors. Floors don't exist without a lot. |
| Car and Vehicle | **Inheritance** | A car *is a* type of vehicle. Natural hierarchy. |
| FeeCalculator and HourlyFeeCalculator | **Inheritance** | HourlyFeeCalculator *is a* type of FeeCalculator. |

**💡 Key Insight:** If you can say "X IS-A Y", use inheritance. If you can say "X HAS-A Y", use composition. When in doubt, **favor composition**.

### Drawing the Class Diagram

When you draw your class diagram, think about it layer by layer:

```
Layer 1 (Top):          ParkingLot
                           │
Layer 2 (Middle):    ParkingFloor  ─── uses ─── FeeCalculator (interface)
                      │        │                      │
Layer 3 (Bottom):  ParkingSpot  TicketManager    HourlyFeeCalculator  DailyFeeCalculator
                      │
                  Vehicle (abstract)
                      │
               ┌──────┼──────┐
             Car   Truck   Motorcycle
```

**For each arrow, ask:**
- Is this a solid line (composition) or dotted line (dependency)?
- Does the child exist without the parent? (If yes, it's aggregation, not composition)
- Is the dependency one-way? (It should be — avoid circular dependencies!)

---

## Phase 6: Polymorphism & Inheritance

When you have behavior that varies by type, use **polymorphism** instead of conditionals.

### ❌ Bad: Type-checking with if-else

```python
class Vehicle:
    def __init__(self, vehicle_type: str):
        self.type = vehicle_type

# Somewhere in the code:
if vehicle.type == "car":
    spot_type = "compact"
elif vehicle.type == "truck":
    spot_type = "large"
elif vehicle.type == "motorcycle":
    spot_type = "motorcycle"
```

**Problem:** Every time you add a new vehicle type, you have to find and update every `if-elif` chain. This violates the **Open/Closed Principle**.

### ✅ Good: Polymorphism

```python
class Vehicle(ABC):
    @abstractmethod
    def get_required_spot_type(self) -> SpotType:
        pass

class Car(Vehicle):
    def get_required_spot_type(self) -> SpotType:
        return SpotType.COMPACT

class Truck(Vehicle):
    def get_required_spot_type(self) -> SpotType:
        return SpotType.LARGE

# No if-else needed anywhere!
spot_type = vehicle.get_required_spot_type()
```

### Thought Process: When to Use Abstract Classes

Ask yourself: *"Will there be multiple implementations of this behavior?"*

| Question | If YES | If NO |
|----------|--------|-------|
| Multiple fee calculation strategies? | Abstract `FeeCalculator` | Concrete class is fine |
| Multiple vehicle types with different spot requirements? | Abstract `Vehicle` | Single `Vehicle` class with enum |
| Multiple payment methods? | Abstract `PaymentProcessor` | Single `Payment` class |

**💡 Rule of Thumb:** Don't over-abstract. Start with concrete classes, and extract an interface when you actually need a second implementation. Premature abstraction is as bad as no abstraction.

---

## Phase 7: Design Patterns — When & Why

Don't force design patterns. They should emerge naturally from the design problems you encounter.

### Pattern Discovery Process

```
Problem: "I need to create different types of vehicles"
   → Factory Pattern ✅ (VehicleFactory)

Problem: "I need to swap fee calculation strategies at runtime"
   → Strategy Pattern ✅ (FeeCalculator interface)

Problem: "I need a unified interface for the parking lot operations"
   → Facade Pattern ✅ (ParkingLot class)

Problem: "I need to notify the display board when spots change"
   → Observer Pattern ✅ (DisplayBoard listens to spot changes)

Problem: "I need to enforce a lifecycle for tickets"
   → State Pattern ✅ (ACTIVE → PAID → LOST)
```

### When NOT to Use a Pattern

| Pattern | When It's Overkill |
|---------|-------------------|
| **Singleton** | When you only need one instance but it's not critical. Just create one instance. |
| **Factory** | When you have only one vehicle type. Wait until you add a second. |
| **Strategy** | When you have only one pricing model. Add the interface when you need a second. |
| **Observer** | When you have only one subscriber. A direct call is simpler. |

**💡 Rule of Thumb:** **YAGNI — You Ain't Gonna Need It.** Don't add a pattern for a case that doesn't exist yet. Add it *when* you need it.

---

## Phase 8: Review & Refine Checklist

After your first draft, run through this checklist:

### 🔲 SOLID Check

| Principle | Question | Parking Lot Example |
|-----------|----------|-------------------|
| **S**ingle Responsibility | Can each class be described in one sentence? | `ParkingSpot` → "Manages one spot's occupancy state" ✅ |
| **O**pen/Closed | Can I add a new vehicle type without modifying existing classes? | Yes: new enum + new subclass + new mapping entry ✅ |
| **L**iskov Substitution | Can any Vehicle subclass be used wherever Vehicle is expected? | `Car`, `Truck`, `Motorcycle` all implement `get_required_spot_type()` ✅ |
| **I**nterface Segregation | Are my interfaces minimal? | `FeeCalculator` has one method: `calculate_fee(duration, spot_type)` ✅ |
| **D**ependency Inversion | Do high-level classes depend on abstractions? | `ParkingLot` depends on `FeeCalculator` interface, not `HourlyFeeCalculator` ✅ |

### 🔲 Cohesion & Coupling Check

- **High cohesion:** Each class's methods are all about the same thing
- **Low coupling:** Classes interact through clean interfaces, not by accessing each other's internals

```
✅ ParkingSpot.park() → changes _is_available and _parked_vehicle (internal state)
❌ ParkingLot.park_vehicle() → directly accesses ParkingSpot._parked_vehicle (bad coupling!)
```

### 🔲 Encapsulation Check

Ask: *"Are the internal details hidden?"*

```python
# ✅ GOOD: Private attribute with property
class ParkingSpot:
    def __init__(self):
        self._is_available = True  # Private

    @property
    def is_available(self) -> bool:
        return self._is_available  # Read-only access

# ❌ BAD: Public attribute
class ParkingSpot:
    def __init__(self):
        self.is_available = True  # Anyone can set this to False!
        # What if someone sets is_available = False but doesn't park a vehicle?
        # Now the system thinks a spot is occupied when it's not.
```

### 🔲 Naming Check

| Class | Good? | Why |
|-------|-------|-----|
| `ParkingSpot` | ✅ | Clear: it's a spot in the parking lot |
| `SpotAllocationMapping` | ✅ | Clear: it maps vehicle types to allowed spots |
| `VehicleManager` | ❌ | Too vague: manages *what* about vehicles? |
| `ParkingLotManager` | ❌ | Too vague: "Manager" classes often become god classes |
| `ParkingLot` | ✅ | Clear and specific |

**💡 Rule of Thumb:** If you're tempted to name a class `XxxManager` or `XxxUtils`, ask yourself: *"What specific responsibility does this class have?"* If you can't answer in one sentence, split it up.

### 🔲 The "New Feature" Test

Imagine adding a new feature and see how many classes need to change:

> *"Add an ElectricCar vehicle type that needs EV charging spots."*

| Change Needed | Classes Modified |
|--------------|-----------------|
| New enum value | `VehicleType.EV` → add to enum |
| New subclass | `ElectricCar(Vehicle)` → new class |
| New mapping | `SpotAllocationMapping._mapping` → one new entry |
| New spot type (optional) | `SpotType.EV` → add to enum |
| New rate (optional) | `HourlyFeeCalculator._rates` → one new entry |

**Result:** 5 small changes, **zero existing code modified**. That's the Open/Closed Principle working.

---

## Summary: The Complete Thought Process Flow

```
┌─────────────────────────────────────────────────┐
│  1. REQUIREMENTS GATHERING                       │
│     "What are the vehicle types, floors,         │
│      pricing model?"                             │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  2. IDENTIFY NOUNS                              │
│     Circle all nouns → candidate classes        │
│     Circle all adjectives → candidate enums     │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  3. DEFINE ENUMS FIRST                          │
│     The vocabulary of your system               │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  4. CLASSIFY EACH ENTITY                        │
│     ├─ Pure data?        → @dataclass           │
│     ├─ Has behavior?     → Regular __init__     │
│     └─ Has variants?     → ABC + subclasses     │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  5. ASSIGN RESPONSIBILITIES                     │
│     For each function: Which class owns this?   │
│     Check SRP: Can I describe in one sentence?  │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  6. DEFINE RELATIONSHIPS                        │
│     ├─ X HAS-A Y   → composition               │
│     └─ X IS-A Y    → inheritance               │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  7. APPLY DESIGN PATTERNS (if needed)           │
│     Don't force them — let them emerge          │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│  8. REVIEW                                       │
│     ├─ SOLID principles                          │
│     ├─ Cohesion & coupling                       │
│     ├─ Encapsulation                             │
│     └─ "New Feature" test                        │
└─────────────────────────────────────────────────┘
```

---

## Quick Reference Card

| Decision | Rule |
|----------|------|
| **Enum vs String** | Always use Enum for fixed categories |
| **dataclass vs __init__** | Use dataclass for passive data, __init__ for behavior |
| **Inheritance vs Composition** | "IS-A" = inheritance, "HAS-A" = composition |
| **Where to put a method** | The class whose data it primarily uses |
| **Abstract vs Concrete** | Use ABC when you expect multiple implementations |
| **Pattern or not** | Don't add patterns for hypothetical futures |
| **Private or Public** | Default to private (`_`), expose via `@property` |
| **One sentence test** | If you can't describe a class in one sentence, it's doing too much |
