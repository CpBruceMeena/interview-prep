"""
ATM / Banking System - Low Level Design
------------------------------------------
Patterns: State (ATM session), Template method (Account.withdrawable),
Facade (Bank), Factory (Bank.open_account).

What this design gets right, and what interviewers probe:
  * Money is Decimal. Floats are rejected.
  * A cash withdrawal is two-phase: the bank AUTHORIZES (places a hold),
    the ATM dispenses, then the bank CAPTURES the hold, or REVERSES it if the
    dispenser fails. The account is never debited for cash that never came out.
  * Every money-moving bank call takes a request_id. A retry with the same id
    returns the original transaction instead of moving money twice.
  * Each account has its own lock; a transfer takes both locks in a fixed
    (account-number) order, so concurrent A->B and B->A cannot deadlock.
  * The ATM is an explicit state machine. A wrong PIN keeps the card; the
    third wrong PIN blocks and retains it; an out-of-service ATM accepts no card.
  * PINs are stored as salted PBKDF2 hashes and compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from math import gcd
from typing import Callable, Dict, List, Optional, Tuple, Union

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MoneyLike = Union[Decimal, int, str]


def to_money(value: MoneyLike) -> Decimal:
    if isinstance(value, (float, bool)):
        raise TypeError(f"money must be Decimal, int or str, not {type(value).__name__}")
    amount = Decimal(value)
    if not amount.is_finite() or amount != amount.quantize(CENT):
        raise ValueError(f"invalid money amount: {value!r}")
    return amount.quantize(CENT)


def positive_money(value: MoneyLike) -> Decimal:
    amount = to_money(value)
    if amount <= 0:
        raise ValueError("amount must be positive")
    return amount


# --- Errors ---

class BankError(Exception):
    pass


class NotFoundError(BankError):
    pass


class InsufficientFundsError(BankError):
    pass


class LimitExceededError(BankError):
    pass


class CardError(BankError):
    """Card unknown, expired or blocked."""


class WrongPinError(CardError):
    def __init__(self, attempts_left: int) -> None:
        super().__init__(f"wrong PIN, {attempts_left} attempt(s) left")
        self.attempts_left = attempts_left


class CardBlockedError(CardError):
    pass


class IdempotencyError(BankError):
    """request_id reused with different parameters, or still in flight."""


class InvalidTransitionError(BankError):
    pass


class DispenseError(Exception):
    """Dispenser cannot make the amount, or the hardware failed."""


class InvalidOperationError(Exception):
    """Operation not allowed in the ATM's current state."""


# --- Accounts ---

class AccountType(Enum):
    SAVINGS = "Savings"
    CHECKING = "Checking"
    CREDIT = "Credit"


class Account(ABC):
    """Balance plus held (authorized, not yet captured) amounts.

    Subclasses differ only in how much may be withdrawn. All mutation goes
    through Bank, which holds `self.lock` while it reads or writes.
    """

    def __init__(self, account_number: str, customer_id: str, balance: Decimal = ZERO) -> None:
        self.account_number = account_number
        self.customer_id = customer_id
        self.lock = threading.Lock()
        self._balance = balance
        self._held = ZERO

    @property
    @abstractmethod
    def account_type(self) -> AccountType:
        ...

    @abstractmethod
    def withdrawable(self) -> Decimal:
        """Largest amount that may leave the account right now."""

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def held(self) -> Decimal:
        return self._held

    # Called by Bank with self.lock held.
    def _require(self, amount: Decimal) -> None:
        if amount > self.withdrawable():
            raise InsufficientFundsError(
                f"{self.account_type.value} {self.account_number}: "
                f"requested {amount}, available {self.withdrawable()}")

    def _hold(self, amount: Decimal) -> None:
        self._require(amount)
        self._held += amount

    def _release_hold(self, amount: Decimal) -> None:
        self._held -= amount

    def _capture_hold(self, amount: Decimal) -> None:
        self._held -= amount
        self._balance -= amount

    def _debit(self, amount: Decimal) -> None:
        self._require(amount)
        self._balance -= amount

    def _credit(self, amount: Decimal) -> None:
        self._balance += amount

    def __str__(self) -> str:
        return f"{self.account_type.value}[{self.account_number}] {self._balance}"


class SavingsAccount(Account):
    def __init__(self, account_number: str, customer_id: str, balance: Decimal = ZERO,
                 min_balance: Decimal = Decimal("500.00")) -> None:
        super().__init__(account_number, customer_id, balance)
        self.min_balance = min_balance

    @property
    def account_type(self) -> AccountType:
        return AccountType.SAVINGS

    def withdrawable(self) -> Decimal:
        return max(ZERO, self._balance - self._held - self.min_balance)


class CheckingAccount(Account):
    def __init__(self, account_number: str, customer_id: str, balance: Decimal = ZERO,
                 overdraft_limit: Decimal = Decimal("1000.00")) -> None:
        super().__init__(account_number, customer_id, balance)
        self.overdraft_limit = overdraft_limit

    @property
    def account_type(self) -> AccountType:
        return AccountType.CHECKING

    def withdrawable(self) -> Decimal:
        return max(ZERO, self._balance - self._held + self.overdraft_limit)


class CreditAccount(Account):
    """Balance is negative when the customer owes money."""

    def __init__(self, account_number: str, customer_id: str,
                 credit_limit: Decimal = Decimal("10000.00")) -> None:
        super().__init__(account_number, customer_id, ZERO)
        self.credit_limit = credit_limit

    @property
    def account_type(self) -> AccountType:
        return AccountType.CREDIT

    def withdrawable(self) -> Decimal:
        return max(ZERO, self.credit_limit + self._balance - self._held)


# --- Transactions ---

class TransactionType(Enum):
    WITHDRAWAL = "Withdrawal"
    DEPOSIT = "Deposit"
    TRANSFER_OUT = "Transfer out"
    TRANSFER_IN = "Transfer in"


class TransactionStatus(Enum):
    PENDING = "Pending"        # authorized, funds held
    COMPLETED = "Completed"
    REVERSED = "Reversed"      # hold released, no money moved


_TRANSITIONS = {
    TransactionStatus.PENDING: {TransactionStatus.COMPLETED, TransactionStatus.REVERSED},
    TransactionStatus.COMPLETED: set(),
    TransactionStatus.REVERSED: set(),
}


@dataclass
class Transaction:
    tx_id: str
    request_id: str
    account_number: str
    tx_type: TransactionType
    amount: Decimal
    status: TransactionStatus
    business_date: date
    card_number: Optional[str] = None
    counterparty: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def move_to(self, status: TransactionStatus) -> None:
        if status not in _TRANSITIONS[self.status]:
            raise InvalidTransitionError(f"{self.tx_id}: {self.status.name} -> {status.name}")
        self.status = status


# --- Cards ---

class Card:
    MAX_PIN_ATTEMPTS = 3
    _PBKDF2_ROUNDS = 10_000      # demo value; real PIN checks happen inside an HSM

    def __init__(self, card_number: str, customer_id: str, account_number: str, pin: str,
                 expiry: date, daily_limit: Decimal) -> None:
        self.card_number = card_number
        self.customer_id = customer_id
        self.account_number = account_number      # default account for this card
        self.expiry = expiry
        self.daily_limit = daily_limit
        self.blocked = False
        self._failed_attempts = 0
        self._salt = os.urandom(16)
        self._pin_hash = self._hash(pin)
        self._lock = threading.Lock()             # the same card can be cloned and used twice

    def _hash(self, pin: str) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), self._salt, self._PBKDF2_ROUNDS)

    def verify_pin(self, pin: str) -> None:
        with self._lock:
            if self.blocked:
                raise CardBlockedError("card is blocked")
            if hmac.compare_digest(self._hash(pin), self._pin_hash):
                self._failed_attempts = 0
                return
            self._failed_attempts += 1
            if self._failed_attempts >= self.MAX_PIN_ATTEMPTS:
                self.blocked = True
                raise CardBlockedError("too many wrong PINs; card blocked")
            raise WrongPinError(self.MAX_PIN_ATTEMPTS - self._failed_attempts)


# --- Bank (facade over accounts, cards and the ledger) ---

_IN_FLIGHT = object()


class Bank:
    def __init__(self, clock: Callable[[], date] = date.today) -> None:
        self._clock = clock
        self._ids = itertools.count(1)
        self._ids_lock = threading.Lock()
        self._registry_lock = threading.Lock()       # guards the three registries below
        self._accounts: Dict[str, Account] = {}
        self._cards: Dict[str, Card] = {}
        self._transactions: Dict[str, Transaction] = {}
        self._requests: Dict[str, object] = {}       # request_id -> (fingerprint, result) | _IN_FLIGHT
        self._requests_lock = threading.Lock()
        self._withdrawn_today: Dict[Tuple[str, date], Decimal] = {}   # (card, day) -> amount
        self._limits_lock = threading.Lock()         # per card, so not covered by an account lock

    def _next_id(self, prefix: str) -> str:
        with self._ids_lock:
            return f"{prefix}{next(self._ids):04d}"

    # setup

    def open_account(self, customer_id: str, account_type: AccountType,
                     initial_deposit: MoneyLike = "0.00", **limits: Decimal) -> Account:
        number = self._next_id("AC")
        initial = to_money(initial_deposit)
        if account_type is AccountType.SAVINGS:
            account: Account = SavingsAccount(number, customer_id, initial, **limits)
        elif account_type is AccountType.CHECKING:
            account = CheckingAccount(number, customer_id, initial, **limits)
        elif account_type is AccountType.CREDIT:
            account = CreditAccount(number, customer_id, **limits)
        else:
            raise BankError(f"unsupported account type {account_type}")
        with self._registry_lock:
            self._accounts[number] = account
        return account

    def issue_card(self, account_number: str, pin: str,
                   daily_limit: MoneyLike = "20000.00", valid_years: int = 5) -> Card:
        account = self._account(account_number)
        today = self._clock()
        first_of_next_month = date(today.year + valid_years + today.month // 12,
                                   today.month % 12 + 1, 1)
        expiry = first_of_next_month - timedelta(days=1)    # valid through end of month
        card = Card(self._next_id("CARD"), account.customer_id, account_number, pin,
                    expiry, to_money(daily_limit))
        with self._registry_lock:
            self._cards[card.card_number] = card
        return card

    # cards & lookups

    def validate_card(self, card_number: str) -> Card:
        with self._registry_lock:
            card = self._cards.get(card_number)
        if card is None:
            raise CardError("unknown card")
        if card.blocked:
            raise CardBlockedError("card is blocked")
        if self._clock() > card.expiry:
            raise CardError("card expired")
        return card

    def verify_pin(self, card_number: str, pin: str) -> Card:
        card = self.validate_card(card_number)
        card.verify_pin(pin)
        return card

    def accounts_of(self, customer_id: str) -> List[Account]:
        with self._registry_lock:
            return [a for a in self._accounts.values() if a.customer_id == customer_id]

    def balance(self, account_number: str) -> Decimal:
        account = self._account(account_number)
        with account.lock:
            return account.balance

    def available(self, account_number: str) -> Decimal:
        account = self._account(account_number)
        with account.lock:
            return account.withdrawable()

    def transaction(self, tx_id: str) -> Transaction:
        with self._registry_lock:
            tx = self._transactions.get(tx_id)
        if tx is None:
            raise NotFoundError(f"unknown transaction {tx_id}")
        return tx

    def statement(self, account_number: str, limit: int = 10) -> List[Transaction]:
        with self._registry_lock:
            txs = [t for t in self._transactions.values() if t.account_number == account_number]
        return txs[-limit:]

    # money movement: phase 1 of a cash withdrawal

    def authorize_withdrawal(self, card_number: str, account_number: str, amount: MoneyLike,
                             request_id: str) -> Transaction:
        """Place a hold. Idempotent on request_id."""
        value = positive_money(amount)

        def run() -> Transaction:
            card = self.validate_card(card_number)
            account = self._account(account_number)
            if account.customer_id != card.customer_id:
                raise CardError("card holder does not own this account")
            key = (card_number, self._clock())
            self._reserve_daily(key, value, card.daily_limit)
            try:
                with account.lock:
                    account._hold(value)
                    return self._record(request_id, account_number, TransactionType.WITHDRAWAL,
                                        value, TransactionStatus.PENDING, card_number=card_number)
            except BaseException:
                self._reserve_daily(key, -value, card.daily_limit)
                raise

        return self._idempotent(request_id, ("withdraw", card_number, account_number, value), run)

    # phase 2: capture after cash is out, or reverse if it never came out

    def capture(self, tx_id: str) -> Transaction:
        """Idempotent: capturing a completed transaction is a no-op."""
        tx = self.transaction(tx_id)
        account = self._account(tx.account_number)
        with account.lock:
            if tx.status is TransactionStatus.COMPLETED:
                return tx
            tx.move_to(TransactionStatus.COMPLETED)
            account._capture_hold(tx.amount)
            return tx

    def reverse(self, tx_id: str) -> Transaction:
        """Idempotent: reversing a reversed transaction is a no-op."""
        tx = self.transaction(tx_id)
        account = self._account(tx.account_number)
        with account.lock:
            if tx.status is TransactionStatus.REVERSED:
                return tx
            tx.move_to(TransactionStatus.REVERSED)
            account._release_hold(tx.amount)
        self._reserve_daily((tx.card_number, tx.business_date), -tx.amount, Decimal("Infinity"))
        return tx

    # single-phase operations

    def deposit(self, account_number: str, amount: MoneyLike, request_id: str) -> Transaction:
        value = positive_money(amount)

        def run() -> Transaction:
            account = self._account(account_number)
            with account.lock:
                account._credit(value)
                return self._record(request_id, account_number, TransactionType.DEPOSIT,
                                    value, TransactionStatus.COMPLETED)

        return self._idempotent(request_id, ("deposit", account_number, value), run)

    def transfer(self, from_number: str, to_number: str, amount: MoneyLike,
                 request_id: str) -> Tuple[Transaction, Transaction]:
        value = positive_money(amount)
        if from_number == to_number:
            raise BankError("cannot transfer to the same account")

        def run() -> Tuple[Transaction, Transaction]:
            source, target = self._account(from_number), self._account(to_number)
            first, second = sorted((source, target), key=lambda a: a.account_number)
            with first.lock, second.lock:          # global lock order: no deadlock
                source._debit(value)
                target._credit(value)
                out = self._record(request_id, from_number, TransactionType.TRANSFER_OUT,
                                   value, TransactionStatus.COMPLETED, counterparty=to_number)
                into = self._record(request_id, to_number, TransactionType.TRANSFER_IN,
                                    value, TransactionStatus.COMPLETED, counterparty=from_number)
                return out, into

        return self._idempotent(request_id, ("transfer", from_number, to_number, value), run)

    # helpers

    def _account(self, account_number: str) -> Account:
        with self._registry_lock:
            account = self._accounts.get(account_number)
        if account is None:
            raise NotFoundError(f"unknown account {account_number}")
        return account

    def _reserve_daily(self, key: Tuple[str, date], delta: Decimal, limit: Decimal) -> None:
        """Atomically add delta to a card's withdrawn-today total, refusing to pass limit."""
        with self._limits_lock:
            used = self._withdrawn_today.get(key, ZERO)
            if delta > 0 and used + delta > limit:
                raise LimitExceededError(f"daily limit {limit}, already withdrawn {used}")
            self._withdrawn_today[key] = used + delta

    def _record(self, request_id: str, account_number: str, tx_type: TransactionType,
                amount: Decimal, status: TransactionStatus, **extra: Optional[str]) -> Transaction:
        tx = Transaction(self._next_id("TX"), request_id, account_number, tx_type, amount,
                         status, self._clock(), **extra)
        with self._registry_lock:
            self._transactions[tx.tx_id] = tx
        return tx

    def _idempotent(self, request_id: str, fingerprint: tuple, run: Callable[[], object]):
        """Claim request_id, run once, remember the result.

        A failed run releases the claim, so a retry is evaluated afresh (a
        decline is not cached). Production keeps these records with a TTL.
        """
        with self._requests_lock:
            existing = self._requests.get(request_id)
            if existing is _IN_FLIGHT:
                raise IdempotencyError(f"request {request_id} is already in flight")
            if existing is not None:
                seen_fingerprint, result = existing
                if seen_fingerprint != fingerprint:
                    raise IdempotencyError(f"request {request_id} reused with different parameters")
                return result
            self._requests[request_id] = _IN_FLIGHT
        try:
            result = run()
        except BaseException:
            with self._requests_lock:
                del self._requests[request_id]
            raise
        with self._requests_lock:
            self._requests[request_id] = (fingerprint, result)
        return result


# --- Cash dispenser ---

class CashDispenser:
    """Notes by denomination. Plans with a bounded min-notes DP, because greedy
    fails on real cassettes: 600 from {500 x1, 200 x3} has an answer (3 x 200)
    that greedy (500 first, then stuck at 100) misses."""

    def __init__(self, notes: Dict[int, int]) -> None:
        self._notes = dict(notes)
        self._lock = threading.Lock()

    @property
    def total(self) -> int:
        return sum(d * n for d, n in self._notes.items())

    def notes(self) -> Dict[int, int]:
        return dict(self._notes)

    def plan(self, amount: int) -> Dict[int, int]:
        """Fewest notes that make `amount` from current stock; DispenseError if impossible."""
        stock = {d: n for d, n in self._notes.items() if n > 0}
        if amount <= 0 or not stock:
            raise DispenseError(f"cannot dispense {amount}")
        unit = 0
        for d in stock:
            unit = gcd(unit, d)
        if amount % unit:
            raise DispenseError(f"{amount} is not a multiple of {unit}")
        target = amount // unit

        best: Dict[int, Dict[int, int]] = {0: {}}          # value in units -> note plan
        for denom, count in sorted(stock.items(), reverse=True):
            step = denom // unit
            nxt = dict(best)
            for value, plan in best.items():
                used = sum(plan.values())
                for k in range(1, count + 1):
                    v = value + k * step
                    if v > target:
                        break
                    if v not in nxt or used + k < sum(nxt[v].values()):
                        nxt[v] = {**plan, denom: k}
            best = nxt
        if target not in best:
            raise DispenseError(f"cannot make {amount} from {stock}")
        return best[target]

    def dispense(self, plan: Dict[int, int]) -> Dict[int, int]:
        with self._lock:
            if any(self._notes.get(d, 0) < n for d, n in plan.items()):
                raise DispenseError("stock changed since planning")
            self._eject(plan)
            for d, n in plan.items():
                self._notes[d] -= n
            return dict(plan)

    def _eject(self, plan: Dict[int, int]) -> None:
        """Hardware hook. Raises DispenseError on a jam."""

    def load(self, notes: Dict[int, int]) -> None:
        with self._lock:
            for d, n in notes.items():
                self._notes[d] = self._notes.get(d, 0) + n


class FlakyDispenser(CashDispenser):
    """Test double: set jam_next to make the next dispense fail before any note moves."""

    jam_next = False

    def _eject(self, plan: Dict[int, int]) -> None:
        if self.jam_next:
            self.jam_next = False
            raise DispenseError("note jam")


# --- ATM (State pattern) ---

class ATMState(ABC):
    """Default: every operation is invalid. Each state overrides what it allows."""

    name = "?"

    def __init__(self, atm: ATM) -> None:
        self.atm = atm

    def _invalid(self, op: str):
        raise InvalidOperationError(f"cannot {op} while {self.name}")

    def insert_card(self, card_number: str) -> None:
        self._invalid("insert card")

    def enter_pin(self, pin: str) -> None:
        self._invalid("enter PIN")

    def select_account(self, account_number: str) -> None:
        self._invalid("select account")

    def balance(self) -> Decimal:
        self._invalid("check balance")

    def withdraw(self, amount: int) -> Dict[int, int]:
        self._invalid("withdraw")

    def deposit(self, amount: MoneyLike) -> Transaction:
        self._invalid("deposit")

    def eject_card(self) -> None:
        self._invalid("eject card")


class IdleState(ATMState):
    name = "IDLE"

    def insert_card(self, card_number: str) -> None:
        self.atm.bank.validate_card(card_number)     # unknown/expired/blocked: stay idle
        self.atm._card = card_number
        self.atm._set_state(self.atm.card_inserted)


class CardInsertedState(ATMState):
    name = "CARD_INSERTED"

    def enter_pin(self, pin: str) -> None:
        try:
            card = self.atm.bank.verify_pin(self.atm._card, pin)
        except CardBlockedError:
            self.atm._retain_card()                   # third strike: keep the card
            raise
        self.atm._account = card.account_number
        self.atm._set_state(self.atm.authenticated)

    def eject_card(self) -> None:
        self.atm._end_session()


class AuthenticatedState(ATMState):
    name = "AUTHENTICATED"

    def select_account(self, account_number: str) -> None:
        card = self.atm.bank.validate_card(self.atm._card)
        owned = {a.account_number for a in self.atm.bank.accounts_of(card.customer_id)}
        if account_number not in owned:
            raise CardError("card holder does not own this account")
        self.atm._account = account_number

    def balance(self) -> Decimal:
        return self.atm.bank.balance(self.atm._account)

    def withdraw(self, amount: int) -> Dict[int, int]:
        atm, bank = self.atm, self.atm.bank
        plan = atm.dispenser.plan(amount)            # 1. can we physically pay this out?
        tx = bank.authorize_withdrawal(atm._card, atm._account, amount, atm._request_id())
        try:
            notes = atm.dispenser.dispense(plan)     # 2. cash out
        except DispenseError:
            bank.reverse(tx.tx_id)                   # 3a. nothing came out: release the hold
            raise
        bank.capture(tx.tx_id)                       # 3b. cash is out: settle
        if atm.dispenser.total == 0:
            atm._out_of_cash = True
        return notes

    def deposit(self, amount: MoneyLike) -> Transaction:
        return self.atm.bank.deposit(self.atm._account, amount, self.atm._request_id())

    def eject_card(self) -> None:
        self.atm._end_session()


class OutOfServiceState(ATMState):
    name = "OUT_OF_SERVICE"


class ATM:
    """One physical ATM: one customer session at a time."""

    def __init__(self, atm_id: str, bank: Bank, dispenser: CashDispenser) -> None:
        self.atm_id = atm_id
        self.bank = bank
        self.dispenser = dispenser
        self.idle = IdleState(self)
        self.card_inserted = CardInsertedState(self)
        self.authenticated = AuthenticatedState(self)
        self.out_of_service = OutOfServiceState(self)
        self._state: ATMState = self.idle if dispenser.total else self.out_of_service
        self._card: Optional[str] = None
        self._account: Optional[str] = None
        self._out_of_cash = False
        self._seq = itertools.count(1)
        self.retained_cards: List[str] = []

    @property
    def state(self) -> str:
        return self._state.name

    def insert_card(self, card_number: str) -> None:
        self._state.insert_card(card_number)

    def enter_pin(self, pin: str) -> None:
        self._state.enter_pin(pin)

    def select_account(self, account_number: str) -> None:
        self._state.select_account(account_number)

    def balance(self) -> Decimal:
        return self._state.balance()

    def withdraw(self, amount: int) -> Dict[int, int]:
        return self._state.withdraw(amount)

    def deposit(self, amount: MoneyLike) -> Transaction:
        return self._state.deposit(amount)

    def eject_card(self) -> None:
        self._state.eject_card()

    # operator actions, only between sessions

    def take_offline(self) -> None:
        if self._state is not self.idle:
            raise InvalidOperationError("finish the customer session first")
        self._set_state(self.out_of_service)

    def restock(self, notes: Dict[int, int]) -> None:
        if self._state not in (self.idle, self.out_of_service):
            raise InvalidOperationError("finish the customer session first")
        self.dispenser.load(notes)
        self._out_of_cash = False
        self._set_state(self.idle)

    # internals used by states

    def _set_state(self, state: ATMState) -> None:
        self._state = state

    def _request_id(self) -> str:
        return f"{self.atm_id}-{next(self._seq)}"

    def _end_session(self) -> None:
        self._card = None
        self._account = None
        self._set_state(self.out_of_service if self._out_of_cash else self.idle)

    def _retain_card(self) -> None:
        self.retained_cards.append(self._card)
        self._end_session()


# --- Demo ---

def demo() -> None:
    print("=== ATM / Banking System ===")
    bank = Bank(clock=lambda: date(2025, 6, 1))
    savings = bank.open_account("CUST1", AccountType.SAVINGS, "5000.00")
    checking = bank.open_account("CUST1", AccountType.CHECKING, "2000.00")
    other = bank.open_account("CUST2", AccountType.SAVINGS, "9000.00")
    card = bank.issue_card(savings.account_number, "1234", daily_limit="3000.00")
    print(f"Accounts: {savings}, {checking}")

    atm = ATM("ATM-MG-ROAD", bank, FlakyDispenser({2000: 2, 500: 1, 200: 10}))

    print("\n--- Session ---")
    atm.insert_card(card.card_number)
    try:
        atm.enter_pin("0000")
    except WrongPinError as e:
        print(f"  {e}; state={atm.state}")
    atm.enter_pin("1234")
    print(f"  authenticated; balance {atm.balance()}")

    notes = atm.withdraw(600)
    print(f"  withdraw 600 -> notes {notes} (greedy would take the 500 and get stuck)")
    print(f"  balance {atm.balance()}, available {bank.available(savings.account_number)} "
          f"(500.00 minimum balance)")

    try:
        atm.withdraw(2500)
    except LimitExceededError as e:
        print(f"  withdraw 2500 refused: {e}")

    try:
        atm.select_account(other.account_number)
    except CardError as e:
        print(f"  select someone else's account refused: {e}")
    atm.select_account(checking.account_number)
    atm.deposit("250.00")
    print(f"  deposited 250.00 to checking -> {bank.balance(checking.account_number)}")

    print("\n--- Dispenser jams: hold is reversed, balance untouched ---")
    atm.dispenser.jam_next = True
    before = bank.balance(checking.account_number)
    try:
        atm.withdraw(400)
    except DispenseError as e:
        last = bank.statement(checking.account_number, 1)[0]
        print(f"  {e}; {last.tx_type.value} {last.amount} is {last.status.name}; "
              f"balance {before} -> {bank.balance(checking.account_number)}")
    atm.eject_card()
    print(f"  card ejected; state={atm.state}")

    print("\n--- Retried transfer (same request id) moves money once ---")
    for _ in range(2):
        out, _into = bank.transfer(savings.account_number, checking.account_number,
                                   "100.00", request_id="mobile-42")
        print(f"  {out.tx_id} {out.tx_type.value} {out.amount}")
    print(f"  savings {bank.balance(savings.account_number)}, "
          f"checking {bank.balance(checking.account_number)}")

    print("\n--- Three wrong PINs ---")
    atm.insert_card(card.card_number)
    for pin in ("1111", "2222", "3333"):
        try:
            atm.enter_pin(pin)
        except CardError as e:
            print(f"  {pin}: {e}")
    print(f"  state={atm.state}, retained={atm.retained_cards}")
    try:
        atm.insert_card(card.card_number)
    except CardBlockedError as e:
        print(f"  reinsert: {e}")


if __name__ == "__main__":
    demo()
