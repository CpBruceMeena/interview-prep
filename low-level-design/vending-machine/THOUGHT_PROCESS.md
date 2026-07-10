# 🧠 Vending Machine LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![](vending-machine-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What products? What prices? What payment methods (cash/card/mobile)? How does change-making work? What are the machine's states?

## Phase 1: Identify the Nouns

> *"A vending machine displays products. User inserts money, selects a product, and receives it with change."*

| Noun | Decision | Why |
|------|----------|-----|
| Product | Regular Class | Has id, name, price |
| Inventory | Regular Class | Manages product stock levels |
| Coin/Note | Enum | Fixed denominations |
| PaymentStrategy | ABC | Multiple payment methods |
| CashPayment | Regular | Handles coin insertion and change |
| VendingState | ABC | State pattern for machine lifecycle |
| VendingMachine | Facade | Main entry point |

## Phase 2: Enums First

```python
class Coin(Enum):     PENNY=0.01, NICKEL=0.05, DIME=0.10, QUARTER=0.25
class Note(Enum):     ONE=1.0, FIVE=5.0, TEN=10.0, TWENTY=20.0
class PaymentMethod(Enum): CASH, CARD, MOBILE
```

**Note:** Coin and Note are enums with *values* — perfect for currency.

## Phase 3: dataclass vs `__init__`

- **`Product`**: Regular — has attributes but minimal behavior
- **`Inventory`**: Regular — manages dictionary of stock, has behavior (`dispense`, `is_available`)
- **`CashPayment`**: Regular — tracks inserted amount, has behavior
- **`CoinMechanism`**: Regular — handles change-making algorithm

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Select product | `VendingState.select_product()` | State machine controls flow |
| Insert money | `CashPayment.insert_coin()` | Payment strategy owns money |
| Process payment | `PaymentStrategy.process_payment()` | Each payment method differs |
| Dispense product | `Inventory.dispense()` | Inventory owns stock |
| Make change | `CoinMechanism.dispense_change()` | Coin system owns change logic |
| Show messages | `VendingDisplay` | SRP: UI/display separate |

## Phase 5: State Pattern (Critical!)

The vending machine has clear states: **Idle → WaitingForMoney → ReadyToDispense**

```python
class VendingState(ABC):
    def select_product(self, product_id)  # Each state behaves differently
    def insert_coin(self, coin)
    def dispense_product(self)
    def cancel_transaction(self)

class IdleState(VendingState):     # Only select_product works
class WaitingForMoneyState(VendingState):  # Only insert_coin works
class ReadyToDispenseState(VendingState):  # Only dispense works
```

**Why State Pattern?** Without it, you'd have `if state == IDLE: ... elif state == WAITING: ...` scattered everywhere. With it, each state's behavior is encapsulated.

## Phase 6: Strategy Pattern for Payment

```python
class PaymentStrategy(ABC):
    def process_payment(self, amount) -> bool
    def refund(self, amount) -> bool

class CashPayment(PaymentStrategy):  # Handles physical money
class CardPayment(PaymentStrategy):   # Swipe/insert card
class MobilePayment(PaymentStrategy): # UPI/Apple Pay
```

## Phase 7: Quick Checklist

✅ **State Pattern:** Machine lifecycle is clean and extensible
✅ **Strategy Pattern:** Payment methods are swappable
✅ **SRP:** Inventory, Payment, Display, CoinMechanism are all separate
✅ **OCP:** Add a new state or payment method → new class, zero existing changes
