# Car Rental Platform - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Fleet management, inventory, dynamic pricing, date-range conflicts

---

## Question 1: Core Design
**Interviewer:** *"Design a car rental platform with fleet management, reservations, and billing."*

### 🎯 Expected Answer

**Domain Model:**
```
Vehicle (abstract) ──→ Hatchback, Sedan, SUV, LuxuryCar
Customer ──→ Reservation ──→ Vehicle
                    │
                    ├── Pickup/Return dates
                    ├── Pricing strategy
                    └── Add-ons (insurance, GPS, child seat)
```

**Vehicle Hierarchy (LSP):**
```python
class Vehicle(ABC):
    @abstractmethod
    def vehicle_type(self) -> VehicleType: pass
    @abstractmethod
    def seating_capacity(self) -> int: pass

class SUV(Vehicle):  # Substitutable for Vehicle
    @property
    def vehicle_type(self): return VehicleType.SUV
    @property
    def seating_capacity(self): return 7
```

**Why abstract class instead of enum?**
An `enum VehicleType { HATCHBACK, SEDAN, SUV }` with switch statements violates OCP. Adding `EV` means finding every switch. With polymorphism, you add `class ElectricCar(Vehicle)` — done.

---

## Question 2: Availability & Double-Booking Prevention
**Interviewer:** *"How do you ensure a vehicle isn't double-booked?"*

### 🎯 Answer

**Date-range overlap checking:**
```sql
SELECT COUNT(*) FROM reservations
WHERE vehicle_id = ?
  AND status IN ('CONFIRMED', 'IN_PROGRESS')
  AND pickup_date < ?
  AND return_date > ?;
-- If count > 0, vehicle is booked during that period
```

**Exclusion constraint (PostgreSQL):**
```sql
CREATE EXTENSION btree_gist;
ALTER TABLE reservations ADD CONSTRAINT no_double_booking
EXCLUDE USING gist (
    vehicle_id WITH =,
    daterange(pickup_date, return_date, '[]') WITH &&
);
```

**Optimistic locking with version:**
```python
def reserve(vehicle_id, pickup, return, version):
    updated = db.execute("""
        UPDATE vehicles SET version = version + 1
        WHERE vehicle_id = ? AND version = ?
    """, [vehicle_id, version])
    if updated == 0:
        raise ConcurrentModificationError()
```

---

## Question 3: Dynamic Pricing
**Interviewer:** *"Design a dynamic pricing engine."*

### 🎯 Answer

**Composable pricing with Decorator pattern:**
```python
class BasePricing(RentalPricing):
    def calculate(self, vehicle, days, customer):
        return vehicle.daily_rate * days

class WeeklyDiscount(RentalPricing):
    def __init__(self, base): self._base = base
    def calculate(self, vehicle, days, customer):
        cost = self._base.calculate(vehicle, days, customer)
        if days >= 7: cost *= 0.9
        return cost

class LoyaltyDiscount(RentalPricing):
    def __init__(self, base): self._base = base
    def calculate(self, vehicle, days, customer):
        cost = self._base.calculate(vehicle, days, customer)
        discount = min(0.2, customer.loyalty_points / 1000 * 0.01)
        return cost * (1 - discount)

# Usage: chain decorators
pricing = LoyaltyDiscount(WeeklyDiscount(BasePricing()))
```

---

## Question 4: Fleet Optimization

| Strategy | Implementation |
|----------|---------------|
| **Predictive maintenance** | Schedule based on mileage, not calendar |
| **Vehicle redistribution** | ML predicts demand zones, dispatch empty vehicles |
| **Dynamic fleet sizing** | Add/remove vehicles based on booking velocity |
| **EV charging** | Reserve charging slots between rentals |

---

## Question 5: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Pricing | Interchangeable: standard, weekly, loyalty |
| **State** | Vehicle/Rental status | Lifecycle management |
| **Factory** | Vehicle creation | Config-driven fleet setup |
| **Facade** | CarRentalService | Unified interface |
| **Decorator** | Add-ons | Insurance, GPS, child seat |
