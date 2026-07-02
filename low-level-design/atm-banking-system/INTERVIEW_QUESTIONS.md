# ATM/Banking System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** State machines, security, concurrency, financial transaction integrity

---

## Question 1: Core Design
**Interviewer:** *"Design an ATM system — card authentication, account selection, balance inquiry, withdrawal."*

### 🎯 Expected Answer

**State Machine Design (the heart of this problem):**
```
IDLE → CARD_INSERTED → PIN_ENTERED → READY
  │         │               │           │
  │         └── (wrong PIN ×3) → BLOCKED
  │                                      │
  └─── EJECT_CARD ←──────────────────────┘
```

**State Pattern Implementation:**
```python
class ATMState(ABC):
    @abstractmethod
    def insert_card(self, card_number): pass
    @abstractmethod
    def enter_pin(self, pin): pass
    @abstractmethod
    def check_balance(self): pass
    @abstractmethod
    def withdraw(self, amount): pass
    @abstractmethod
    def eject_card(self): pass

class IdleATMState(ATMState):
    def insert_card(self, card_number):
        self._atm._current_card = card_number
        self._atm._state = self._atm._pin_entered_state

class PinEnteredATMState(ATMState):
    def enter_pin(self, pin):
        account = self._atm._bank.authenticate(self._atm._current_card, pin)
        if account:
            self._atm._current_account = account
            self._atm._state = self._atm._ready_state
        # On failure, track attempts. 3 failures → BLOCKED state.

class ReadyATMState(ATMState):
    def withdraw(self, amount):
        if self._atm._cash_dispenser.can_dispense(amount):
            tx = self._atm._bank.withdraw(self._atm._current_account, amount)
            self._atm._cash_dispenser.dispense(amount)
            return tx
```

**Why State Pattern over if-else?** With `if state == IDLE: ... elif state == PIN_ENTERED:`, adding a new state (e.g., `MAINTENANCE`) requires modifying every method. With State Pattern, add one class — OCP satisfied.

---

## Question 2: Account Types & Transactions
**Interviewer:** *"Handle Savings, Checking, and Credit accounts with different rules."*

### 🎯 Answer

```python
class Account(ABC):
    @abstractmethod
    def can_withdraw(self, amount) -> bool: pass

class SavingsAccount(Account):
    def can_withdraw(self, amount):
        return (self._balance - amount >= self._min_balance 
                and amount <= 50000)  # Daily limit

class CheckingAccount(Account):
    def can_withdraw(self, amount):
        return self._balance - amount >= -self._overdraft_limit  # $1000 OD

class CreditAccount(Account):
    def can_withdraw(self, amount):
        return self.available_credit >= amount
```

**Polymorphism eliminates if-else chains.** Each account type knows its own constraints. The withdrawal logic never checks `account_type == SAVINGS` — it just calls `can_withdraw()`.

---

## Question 3: Security

| Layer | Measure |
|-------|---------|
| **Card** | PIN hashing (bcrypt), 3-attempt lockout, EMV chip |
| **Session** | Auto-eject after 30s inactivity |
| **Transaction** | Daily limits ($500 withdrawal), velocity checks |
| **Network** | End-to-end encryption (TLS 1.3), HSM for PIN blocks |
| **Audit** | Every transaction logged, immutable audit trail |

**PIN verification flow (never transmit raw PIN):**
```python
# ATM encrypts PIN with HSM public key
encrypted_pin = hsm.encrypt(pin, hsm_public_key)
# Bank decrypts and verifies
decrypted_pin = hsm.decrypt(encrypted_pin, hsm_private_key)
# Compare with stored hash
is_valid = bcrypt.checkpw(decrypted_pin, stored_hash)
```

---

## Question 4: Cash Management

**Denomination optimization for dispensing:**
```python
def dispense(self, amount: int):
    notes = {}
    for denom in [2000, 500, 100]:  # INR denominations
        count = min(amount // denom, self._available[denom])
        if count > 0:
            notes[denom] = count
            amount -= count * denom
            self._available[denom] -= count
    if amount > 0:
        raise InsufficientFundsError("Cannot dispense requested amount")
    return notes
```

**Predictive replenishment:** Monitor average daily withdrawal per ATM. Schedule cash refill when predicted to drop below 20% capacity. Use historical patterns (weekends = higher demand).

---

## Question 5: Transaction Processing

**ACID properties for financial transactions:**
```python
def transfer(from_acct, to_acct, amount):
    with db.transaction():  # Atomic
        from_acct.withdraw(amount)  # Checked
        to_acct.deposit(amount)     # Consistent
        
        # Durability: written to WAL before commit
        audit_log.record(from_acct, to_acct, amount, "TRANSFER")
    # On failure, entire transaction rolls back
```

**Daily settlement:** Batch process at EOD — reconcile ATM cash dispensed vs. transaction records. Any discrepancy triggers investigation.

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **State** | ATM states | Clean lifecycle, easy extension |
| **Strategy** | Account types | Different withdrawal rules |
| **Facade** | BankingService | Unified interface |
| **Singleton** | CashDispenser | Single cash inventory per ATM |
| **Factory** | Account creation | Config-driven setup |
| **Chain of Responsibility** | Transaction validation | Fee check → limit check → fraud check → execute |
