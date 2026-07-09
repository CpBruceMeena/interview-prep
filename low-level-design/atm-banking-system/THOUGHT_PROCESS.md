# 🧠 ATM / Banking System LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

What account types? (Savings, Checking, Credit?) What ATM operations? (Withdraw, deposit, transfer, balance inquiry?) Card authentication? PIN validation?

## Phase 1: Identify the Nouns

> *"A bank has accounts of different types. Customers get cards. ATMs authenticate cards and perform banking operations."*

| Noun | Decision | Why |
|------|----------|-----|
| Account | ABC | Abstract — different account types |
| SavingsAccount | Regular | Min balance, monthly withdrawal limit |
| CheckingAccount | Regular | Overdraft limit |
| CreditAccount | Regular | Credit limit, APR, available credit |
| Transaction | Regular | Audit record for every operation |
| Card | Regular | PIN validation, expiry, block status |
| CashDispenser | Regular | Manages denominations |
| BankingService | Facade | Manages accounts, cards, ATM operations |
| ATM | Regular | State machine for ATM sessions |
| ATMState | ABC | State pattern: Idle → PinEntered → Ready |
| AccountType | Enum | SAVINGS, CHECKING, CREDIT, LOAN |
| TransactionType | Enum | DEPOSIT, WITHDRAWAL, TRANSFER, etc. |
| CardType | Enum | DEBIT, CREDIT, ATM |

## Phase 2: Enums First

```python
class AccountType(Enum):     SAVINGS, CHECKING, CREDIT, LOAN
class TransactionType(Enum): DEPOSIT, WITHDRAWAL, TRANSFER, PAYMENT, FEE, INTEREST
class CardType(Enum):        DEBIT, CREDIT, ATM
class TransactionStatus(Enum): PENDING, COMPLETED, FAILED, REVERSED
```

## Phase 3: dataclass vs `__init__`

- **`Account`**: ABC — abstract, subclasses have different rules
- **`SavingsAccount`**: Regular — min balance, interest rate, withdrawal limit
- **`CheckingAccount`**: Regular — overdraft limit
- **`CreditAccount`**: Regular — credit limit, APR, `available_credit` computed
- **`Transaction`**: Regular — auto-generated IDs, timestamp
- **`Card`**: Regular — PIN validation state, block logic
- **`CashDispenser`**: Regular — denomination management

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Validate withdrawal | `Account.can_withdraw()` | Each account type has different rules |
| Deposit money | `Account.deposit()` | Account owns its balance |
| Withdraw money | `Account.withdraw()` | Account validates + updates balance |
| Validate PIN | `Card.validate_pin()` | Card owns PIN + attempts counter |
| Check card expiry | `Card.is_expired()` | Card owns its expiry date |
| Dispense cash | `CashDispenser.dispense()` | Manages denominations |
| Authenticate | `BankingService.authenticate()` | Orchestrates Card → Account |
| State transitions | `ATMState` subclasses | Each state has different allowed actions |

## Phase 5: State Pattern for ATM

The ATM has a clear lifecycle:

```
IDLE → insert_card → PIN_ENTERED → enter_pin → READY → perform_operations
                                                          → eject_card → IDLE
```

Each state has different allowed operations:
- **Idle:** Only insert_card works
- **PinEntered:** Only enter_pin or eject_card
- **Ready:** Only banking operations or eject_card

This eliminates `if state == X` conditionals everywhere.

## Phase 6: Account Hierarchy (LSP)

```python
class Account(ABC):
    @abstractmethod
    def can_withdraw(self, amount: float) -> bool: pass
    def deposit(self, amount) -> Transaction      # Shared logic
    def withdraw(self, amount) -> Transaction     # Uses can_withdraw()

class SavingsAccount(Account):   # can_withdraw: min_balance check + withdrawal limit
class CheckingAccount(Account):  # can_withdraw: overdraft limit check
class CreditAccount(Account):    # can_withdraw: available_credit check
```

`BankingService` treats all accounts uniformly — just calls `account.withdraw()`.

## Phase 7: Cash Dispenser Denominations

```python
class CashDispenser:
    def __init__(self):
        self._denominations = {100: 200, 500: 100, 2000: 20}
    
    def _can_make_amount(self, amount: int) -> bool:
        # Greedy algorithm: try to make amount with available denominations
```

The greedy approach works for standard denominations. This is a real-world detail.

## Phase 8: Quick Checklist

✅ **State Pattern:** ATM states are clean and extensible
✅ **LSP:** All account types are interchangeable
✅ **SRP:** Account holds balance logic, Card holds authentication, Dispenser holds cash
✅ **Encapsulation:** PIN validation, balance changes are through methods
