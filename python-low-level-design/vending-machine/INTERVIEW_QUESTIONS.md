# Vending Machine - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** State machines, finite automata, payment systems, inventory

---

## Question 1: State Machine Design
**Interviewer:** *"Design a vending machine that handles the complete purchase flow using state machines."*  

### 🎯 Expected Answer

This is a textbook **State Pattern** problem. The vending machine has clearly defined states and transitions.

**State Diagram:**
```
    ┌─────────────────────────────────────────────┐
    │                                             ▼
  ┌──────┐  select  ┌──────────┐  sufficient  ┌──────────┐
  │ Idle │─────────▶│ Waiting  │─────────────▶│  Ready   │
  │      │          │ for $    │               │ to       │
  │      │◀────────│          │◀──────────────│ Dispense │
  └──────┘  cancel  └──────────┘   cancel      └────┬─────┘
        ▲                                            │
        └────────────────────────────────────────────┘
                        dispense
```

**State Pattern Implementation:**
```python
class VendingState(ABC):
    def __init__(self, machine): self._machine = machine
    
    @abstractmethod
    def select_product(self, product_id): pass
    @abstractmethod
    def insert_coin(self, coin): pass
    @abstractmethod
    def insert_note(self, note): pass
    @abstractmethod
    def dispense_product(self): pass
    @abstractmethod
    def cancel_transaction(self): pass

class IdleState(VendingState):
    def select_product(self, product_id):
        # Validate product exists and is in stock
        # Transition to WaitingForMoneyState
        self._machine._state = self._machine._waiting_for_money_state

class WaitingForMoneyState(VendingState):
    def insert_coin(self, coin):
        self._machine._current_balance += coin.value
        if self._machine._current_balance >= self._machine._selected_product.price:
            self._machine._state = self._machine._ready_to_dispense_state

class ReadyToDispenseState(VendingState):
    def dispense_product(self):
        self._machine._inventory.dispense(self._machine._selected_product.product_id)
        self._machine._state = self._machine._idle_state
```

**Why State Pattern over if-else chains?** With `if state == IDLE: ... elif state == WAITING: ...`, adding a new state (e.g., MAINTENANCE) means modifying every method that checks state. With State Pattern, you add one class — OCP satisfied.

### ✅ Edge Cases in State Transitions

| Transition | Guard Condition |
|------------|-----------------|
| **Idle → Waiting** | Product must exist AND be in stock |
| **Waiting → Ready** | `current_balance >= price` |
| **Ready → Idle** | Product dispensed AND change returned |
| **Any → Cancel** | Refund current balance, release selection |
| **Maintenance** | Only with admin key, block all transactions |

---

## Question 2: Inventory Management
**Interviewer:** *"Design the inventory system for a vending machine chain."*

### 🎯 Key Points

- **Per-machine inventory**: `Dict[product_id, (Product, quantity)]`
- **Real-time tracking**: WebSocket updates to central server on each dispense
- **Restock alerts**: Triggered when `quantity <= reorder_level`
- **Expiry management**: Products have `expiry_date`; auto-disable expired items
- **Dynamic pricing**: Lower price for near-expiry items, higher for popular ones

**Reducing waste:** Use FIFO (First In, First Out) ordering for restock — physically place newer items behind older ones.

---

## Question 3: Payment Integration
**Interviewer:** *"How would you support multiple payment methods?"*

### 🎯 Answer

**Strategy Pattern for Payments:**
```python
class PaymentStrategy(ABC):
    @abstractmethod
    def process_payment(self, amount: float) -> bool: pass
    @abstractmethod
    def refund(self, amount: float) -> bool: pass

class CashPayment(PaymentStrategy): ...
class CardPayment(PaymentStrategy): ...
class MobilePayment(PaymentStrategy): ...
```

**Change-making algorithm (Greedy):**
```python
def make_change(amount: float, available: Dict[Coin, int]) -> Dict[Coin, int]:
    change = {}
    for coin in sorted(Coin, key=lambda c: c.value, reverse=True):
        while amount >= coin.value and available.get(coin, 0) > 0:
            change[coin] = change.get(coin, 0) + 1
            available[coin] -= 1
            amount = round(amount - coin.value, 2)
    if amount > 0.01:  # Floating point tolerance
        raise InsufficientChangeError("Can't make exact change")
    return change
```

**Note:** Greedy works for standard coin systems (USD, EUR, INR) because they are "canonical" — larger denominations are multiples of smaller ones. For non-canonical systems (e.g., 1, 3, 4), greedy fails and you need DP.

---

## Question 4: Concurrency & Thread Safety
**Interviewer:** *"How would you handle two people using the same machine?"*

### 🎯 Real Scenario

Modern vending machines have one active interface. But the question tests your understanding of:

1. **Lock the state machine** during active transactions (`threading.Lock`)
2. **Timeout**: If user doesn't insert money within 30 seconds, auto-cancel
3. **Inventory consistency**: Decrement stock in a database transaction or with a lock

---

## Question 5: Maintenance & Reporting

| Feature | Implementation |
|---------|---------------|
| **Sales analytics** | Per-product sales count, peak hours |
| **Low stock alerts** | SMS/email when reorder level hit |
| **Revenue tracking** | Daily/monthly totals by machine |
| **Mechanical issues** | Error codes (coin jam, note jam, temp) |
| **Remote dashboard** | Web UI with real-time machine status |

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **State** | VendingStates | Clean state transitions |
| **Strategy** | PaymentStrategy | Multiple payment methods |
| **Observer** | Display updates | Real-time UI feedback |
| **Facade** | VendingMachine | Unified API over subsystems |
| **Factory** | Product creation | Config-driven inventory setup |
