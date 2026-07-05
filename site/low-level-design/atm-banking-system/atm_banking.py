"""
ATM / Banking System - Low Level Design
------------------------------------------
Design Principles: SOLID, Strategy Pattern, State Pattern
"""

from abc import ABC, abstractmethod
from datetime import datetime, date
from enum import Enum
from typing import Dict, List, Optional, Tuple
import uuid


class AccountType(Enum):
    SAVINGS = "Savings"
    CHECKING = "Checking"
    CREDIT = "Credit"
    LOAN = "Loan"


class TransactionType(Enum):
    DEPOSIT = "Deposit"
    WITHDRAWAL = "Withdrawal"
    TRANSFER = "Transfer"
    PAYMENT = "Payment"
    FEE = "Fee"
    INTEREST = "Interest"


class CardType(Enum):
    DEBIT = "Debit"
    CREDIT = "Credit"
    ATM = "ATM"


class TransactionStatus(Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    FAILED = "Failed"
    REVERSED = "Reversed"


# --- Bank Account (SRP) ---

class Account(ABC):
    def __init__(self, account_number: str, customer_id: str,
                 account_type: AccountType, balance: float = 0.0):
        self._account_number = account_number
        self._customer_id = customer_id
        self._account_type = account_type
        self._balance = balance
        self._is_active = True
        self._transactions: List['Transaction'] = []

    @property
    def account_number(self) -> str:
        return self._account_number

    @property
    def customer_id(self) -> str:
        return self._customer_id

    @property
    def account_type(self) -> AccountType:
        return self._account_type

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def is_active(self) -> bool:
        return self._is_active

    @abstractmethod
    def can_withdraw(self, amount: float) -> bool:
        pass

    def deposit(self, amount: float) -> 'Transaction':
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self._balance += amount
        tx = Transaction.generate(self._account_number, TransactionType.DEPOSIT,
                                   amount, self._balance)
        self._transactions.append(tx)
        return tx

    def withdraw(self, amount: float) -> 'Transaction':
        if not self.can_withdraw(amount):
            raise ValueError(f"Insufficient funds or limit exceeded")
        self._balance -= amount
        tx = Transaction.generate(self._account_number, TransactionType.WITHDRAWAL,
                                   -amount, self._balance)
        self._transactions.append(tx)
        return tx

    def add_transaction(self, tx: 'Transaction') -> None:
        self._transactions.append(tx)

    def get_transactions(self, limit: int = 10) -> List['Transaction']:
        return self._transactions[-limit:]

    def __str__(self) -> str:
        return f"{self._account_type.value}[{self._account_number[-4:]}] ${self._balance:.2f}"


class SavingsAccount(Account):
    def __init__(self, account_number: str, customer_id: str,
                 balance: float = 0.0, interest_rate: float = 0.04):
        super().__init__(account_number, customer_id, AccountType.SAVINGS, balance)
        self._interest_rate = interest_rate
        self._min_balance = 500.0
        self._withdrawal_limit = 5  # per month

    @property
    def interest_rate(self) -> float:
        return self._interest_rate

    def can_withdraw(self, amount: float) -> bool:
        return (self._balance - amount >= self._min_balance and
                amount <= 50000.0)

    def apply_interest(self) -> None:
        interest = self._balance * self._interest_rate / 12
        self._balance += interest
        tx = Transaction(self._account_number, TransactionType.INTEREST,
                          interest, self._balance, "Monthly interest")
        self._transactions.append(tx)


class CheckingAccount(Account):
    def __init__(self, account_number: str, customer_id: str,
                 balance: float = 0.0, overdraft_limit: float = 1000.0):
        super().__init__(account_number, customer_id, AccountType.CHECKING, balance)
        self._overdraft_limit = overdraft_limit

    def can_withdraw(self, amount: float) -> bool:
        return self._balance - amount >= -self._overdraft_limit


class CreditAccount(Account):
    def __init__(self, account_number: str, customer_id: str,
                 credit_limit: float = 10000.0, apr: float = 0.24):
        super().__init__(account_number, customer_id, AccountType.CREDIT, 0.0)
        self._credit_limit = credit_limit
        self._apr = apr

    @property
    def credit_limit(self) -> float:
        return self._credit_limit

    @property
    def available_credit(self) -> float:
        return self._credit_limit - abs(self._balance)

    def can_withdraw(self, amount: float) -> bool:
        return self.available_credit >= amount

    def make_payment(self, amount: float) -> 'Transaction':
        # Payments reduce debt (balance is negative for credit)
        self._balance += amount
        tx = Transaction.generate(self._account_number, TransactionType.PAYMENT,
                                   amount, self._balance)
        self._transactions.append(tx)
        return tx


# --- Transaction (SRP) ---

class Transaction:
    def __init__(self, account_number: str, tx_type: TransactionType,
                 amount: float, balance_after: float,
                 description: str = ""):
        self._transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        self._account_number = account_number
        self._tx_type = tx_type
        self._amount = amount
        self._balance_after = balance_after
        self._timestamp = datetime.now()
        self._status = TransactionStatus.COMPLETED
        self._description = description

    @classmethod
    def generate(cls, account_number: str, tx_type: TransactionType,
                  amount: float, balance_after: float) -> 'Transaction':
        return cls(account_number, tx_type, amount, balance_after)

    @property
    def transaction_id(self) -> str:
        return self._transaction_id

    @property
    def tx_type(self) -> TransactionType:
        return self._tx_type

    @property
    def amount(self) -> float:
        return self._amount

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    def __str__(self) -> str:
        return (f"[{self._timestamp:%H:%M}] {self._tx_type.value}: "
                f"${abs(self._amount):.2f} (Balance: ${self._balance_after:.2f})")


# --- Card / ATM Card ---

class Card:
    def __init__(self, card_number: str, pin: str, customer_id: str,
                 account_number: str, card_type: CardType,
                 expiry_date: date, cvv: str):
        self._card_number = card_number
        self._pin = pin
        self._customer_id = customer_id
        self._account_number = account_number
        self._card_type = card_type
        self._expiry = expiry_date
        self._cvv = cvv
        self._failed_attempts = 0
        self._is_blocked = False

    @property
    def card_number(self) -> str:
        return self._card_number

    @property
    def account_number(self) -> str:
        return self._account_number

    @property
    def is_blocked(self) -> bool:
        return self._is_blocked

    def validate_pin(self, entered_pin: str) -> bool:
        if self._is_blocked:
            return False
        if self._pin == entered_pin:
            self._failed_attempts = 0
            return True
        self._failed_attempts += 1
        if self._failed_attempts >= 3:
            self._is_blocked = True
        return False

    def is_expired(self) -> bool:
        return date.today() > self._expiry


# --- Cash Dispenser (SRP) ---

class CashDispenser:
    def __init__(self, initial_cash: float = 100000.0):
        self._available_cash = initial_cash
        self._denominations = {100: 200, 500: 100, 2000: 20}

    def can_dispense(self, amount: float) -> bool:
        return self._available_cash >= amount and self._can_make_amount(int(amount))

    def _can_make_amount(self, amount: int) -> bool:
        remaining = amount
        for denom in sorted(self._denominations.keys(), reverse=True):
            count = min(remaining // denom, self._denominations[denom])
            remaining -= count * denom
        return remaining == 0

    def dispense(self, amount: float) -> Dict[int, int]:
        if not self.can_dispense(amount):
            raise ValueError("Cannot dispense requested amount")

        dispensed = {}
        remaining = int(amount)
        for denom in sorted(self._denominations.keys(), reverse=True):
            count = min(remaining // denom, self._denominations[denom])
            if count > 0:
                dispensed[denom] = count
                self._denominations[denom] -= count
                remaining -= count * denom
                self._available_cash -= count * denom

        return dispensed

    def load_cash(self, amount: float) -> None:
        self._available_cash += amount


# --- Bank Service (Facade) ---

class BankingService:
    def __init__(self):
        self._accounts: Dict[str, Account] = {}
        self._cards: Dict[str, Card] = {}
        self._atm = CashDispenser()

    def create_account(self, customer_id: str, account_type: AccountType,
                       initial_deposit: float = 0.0) -> Account:
        account_number = f"ACC-{uuid.uuid4().hex[:8].upper()}"
        if account_type == AccountType.SAVINGS:
            account = SavingsAccount(account_number, customer_id, initial_deposit)
        elif account_type == AccountType.CHECKING:
            account = CheckingAccount(account_number, customer_id, initial_deposit)
        elif account_type == AccountType.CREDIT:
            account = CreditAccount(account_number, customer_id)
        else:
            raise ValueError(f"Unsupported account type: {account_type}")
        self._accounts[account_number] = account
        return account

    def get_account(self, account_number: str) -> Optional[Account]:
        return self._accounts.get(account_number)

    def issue_card(self, customer_id: str, account_number: str,
                   pin: str, card_type: CardType) -> Card:
        card_number = f"****-****-****-{uuid.uuid4().hex[:4].upper()}"
        expiry = date(date.today().year + 5, date.today().month, 1)
        cvv = str(uuid.uuid4().int)[:3]
        card = Card(card_number, pin, customer_id, account_number,
                     card_type, expiry, cvv)
        self._cards[card_number] = card
        return card

    def authenticate(self, card_number: str, pin: str) -> Optional[Account]:
        card = self._cards.get(card_number)
        if not card:
            print("  Card not found")
            return None
        if card.is_expired():
            print("  Card expired")
            return None
        if not card.validate_pin(pin):
            attempts_left = 3 - card._failed_attempts
            if card.is_blocked:
                print("  ⛔ Card blocked - too many failed attempts")
            else:
                print(f"  Wrong PIN. {max(0, attempts_left)} attempts remaining")
            return None
        return self._accounts.get(card.account_number)

    def withdraw(self, account_number: str, amount: float) -> Optional[Transaction]:
        account = self._accounts.get(account_number)
        if not account:
            return None

        if isinstance(account, CreditAccount):
            tx = account.make_payment(-amount)
        else:
            tx = account.withdraw(amount)

        if isinstance(self._atm, CashDispenser):
            notes = self._atm.dispense(amount)
            print(f"  Dispensed: {', '.join(f'{n}x${c}' for c, n in notes.items())}")

        return tx

    def deposit(self, account_number: str, amount: float) -> Optional[Transaction]:
        account = self._accounts.get(account_number)
        if account:
            return account.deposit(amount)
        return None

    def transfer(self, from_account: str, to_account: str,
                 amount: float) -> List[Transaction]:
        from_acct = self._accounts.get(from_account)
        to_acct = self._accounts.get(to_account)

        if not from_acct or not to_acct:
            raise ValueError("Account not found")

        from_acct.withdraw(amount)
        to_acct.deposit(amount)

        print(f"  Transferred ${amount:.2f} from {from_account[-4:]} to {to_account[-4:]}")
        return [from_acct.get_transactions(1)[0], to_acct.get_transactions(1)[0]]


# --- ATM Machine (State Pattern) ---

class ATMState(ABC):
    def __init__(self, atm: 'ATM'):
        self._atm = atm

    @abstractmethod
    def insert_card(self, card_number: str) -> None: pass

    @abstractmethod
    def enter_pin(self, pin: str) -> None: pass

    @abstractmethod
    def select_account(self, account_number: str) -> None: pass

    @abstractmethod
    def check_balance(self) -> Optional[float]: pass

    @abstractmethod
    def withdraw(self, amount: float) -> bool: pass

    @abstractmethod
    def deposit(self, amount: float) -> bool: pass

    @abstractmethod
    def eject_card(self) -> None: pass


class IdleATMState(ATMState):
    def insert_card(self, card_number: str) -> None:
        self._atm._current_card = card_number
        print("  Card inserted. Please enter PIN.")
        self._atm._state = self._atm.pin_entered_state

    def enter_pin(self, pin: str) -> None: print("  Insert card first")
    def select_account(self, account_number: str) -> None: print("  Insert card first")
    def check_balance(self) -> Optional[float]: print("  Insert card first"); return None
    def withdraw(self, amount: float) -> bool: print("  Insert card first"); return False
    def deposit(self, amount: float) -> bool: print("  Insert card first"); return False
    def eject_card(self) -> None: print("  No card to eject")


class PinEnteredATMState(ATMState):
    def insert_card(self, card_number: str) -> None: print("  Card already inserted")

    def enter_pin(self, pin: str) -> None:
        account = self._atm.bank.authenticate(self._atm._current_card, pin)
        if account:
            self._atm._current_account = account.account_number
            print(f"  ✅ Authenticated. Account: {account}")
            self._atm._state = self._atm.ready_state
        # If failed, stays in same state

    def select_account(self, account_number: str) -> None: print("  Enter PIN first")
    def check_balance(self) -> Optional[float]: print("  Enter PIN first"); return None
    def withdraw(self, amount: float) -> bool: print("  Enter PIN first"); return False
    def deposit(self, amount: float) -> bool: print("  Enter PIN first"); return False
    def eject_card(self) -> None:
        self._atm._current_card = None
        self._atm._state = self._atm.idle_state
        print("  Card ejected")


class ReadyATMState(ATMState):
    def insert_card(self, card_number: str) -> None: print("  Card already inserted")
    def enter_pin(self, pin: str) -> None: print("  Already authenticated")

    def select_account(self, account_number: str) -> None:
        if self._atm.bank.get_account(account_number):
            self._atm._current_account = account_number
            print(f"  Switched to account {account_number[-4:]}")
        else:
            print("  Account not found")

    def check_balance(self) -> Optional[float]:
        account = self._atm.bank.get_account(self._atm._current_account)
        balance = account.balance if account else 0
        print(f"  💰 Balance: ${balance:.2f}")
        return balance

    def withdraw(self, amount: float) -> bool:
        try:
            self._atm.bank.withdraw(self._atm._current_account, amount)
            print(f"  ✅ Withdrawal successful: ${amount:.2f}")
            new_balance = self._atm.bank.get_account(self._atm._current_account).balance
            print(f"  💰 New Balance: ${new_balance:.2f}")
            return True
        except (ValueError, Exception) as e:
            print(f"  ❌ {e}")
            return False

    def deposit(self, amount: float) -> bool:
        tx = self._atm.bank.deposit(self._atm._current_account, amount)
        if tx:
            print(f"  ✅ Deposit successful: ${amount:.2f}")
            return True
        return False

    def eject_card(self) -> None:
        self._atm._current_card = None
        self._atm._current_account = None
        self._atm._state = self._atm.idle_state
        print("  👋 Card ejected. Thank you!")


class ATM:
    def __init__(self, bank: BankingService, location: str = "Downtown"):
        self._bank = bank
        self._location = location

        self._idle_state = IdleATMState(self)
        self._pin_entered_state = PinEnteredATMState(self)
        self._ready_state = ReadyATMState(self)
        self._state = self._idle_state

        self._current_card: Optional[str] = None
        self._current_account: Optional[str] = None

    def insert_card(self, card_number: str) -> None:
        self._state.insert_card(card_number)

    def enter_pin(self, pin: str) -> None:
        self._state.enter_pin(pin)

    def check_balance(self) -> Optional[float]:
        return self._state.check_balance()

    def withdraw(self, amount: float) -> bool:
        return self._state.withdraw(amount)

    def deposit(self, amount: float) -> bool:
        return self._state.deposit(amount)

    def eject_card(self) -> None:
        self._state.eject_card()

    @property
    def bank(self) -> BankingService:
        return self._bank

    @property
    def idle_state(self) -> ATMState:
        return self._idle_state

    @property
    def pin_entered_state(self) -> ATMState:
        return self._pin_entered_state

    @property
    def ready_state(self) -> ATMState:
        return self._ready_state


# --- Demo ---

def demo():
    print("=== ATM / Banking System ===")
    print("=" * 50)

    bank = BankingService()

    # Create accounts
    savings = bank.create_account("CUST001", AccountType.SAVINGS, 5000.0)
    checking = bank.create_account("CUST001", AccountType.CHECKING, 2000.0)
    credit = bank.create_account("CUST001", AccountType.CREDIT)

    print(f"\nAccounts:")
    print(f"  Savings: {savings}")
    print(f"  Checking: {checking}")
    print(f"  Credit: {credit}")

    # Issue card
    card = bank.issue_card("CUST001", savings.account_number, "1234", CardType.DEBIT)
    print(f"\nCard issued: {card.card_number}")

    # ATM Demo
    print("\n--- ATM Session ---")
    atm = ATM(bank, "Bangalore - MG Road")
    atm.insert_card(card.card_number)
    atm.enter_pin("1234")
    atm.check_balance()
    atm.withdraw(1000)
    atm.check_balance()
    atm.deposit(500)
    atm.check_balance()

    # Transfer
    print("\n--- Transfer ---")
    bank.transfer(savings.account_number, checking.account_number, 500.0)

    print(f"\nFinal Balances:")
    print(f"  Savings: ${savings.balance:.2f}")
    print(f"  Checking: ${checking.balance:.2f}")

    atm.eject_card()


if __name__ == "__main__":
    demo()
