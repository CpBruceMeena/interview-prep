"""
Splitwise - Expense Sharing System - Low Level Design
-------------------------------------------------------
Patterns: Strategy (split rules, settlement algorithms), Factory (split lookup),
Facade (SplitwiseService).

Money rules (the part interviewers actually probe):
  * Money is Decimal quantized to cents. Floats are rejected at the boundary,
    because 0.1 + 0.2 != 0.3 and balances must sum to exactly zero.
  * Every split is allocated in integer cents with the largest-remainder
    method, so the shares always sum to the expense amount exactly and no
    share is more than one cent away from its exact pro-rata value.
  * The ledger keeps a running net balance per user per group. Invariant:
    the balances in any ledger sum to exactly 0.

Concurrency: one service-wide lock makes every mutation (expense + ledger
update) atomic and every read consistent. Per-group locks are the next step if
contention matters; see HIGH_LEVEL_DESIGN.md.
"""

from __future__ import annotations

import heapq
import itertools
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Dict, List, Mapping, NamedTuple, Optional, Sequence, Union

CENT = Decimal("0.01")
MoneyLike = Union[Decimal, int, str]


def to_money(value: MoneyLike) -> Decimal:
    """Parse a money amount. Rejects floats and sub-cent precision."""
    if isinstance(value, (float, bool)):
        raise TypeError(f"money must be Decimal, int or str, not {type(value).__name__}")
    amount = Decimal(value)
    if not amount.is_finite() or amount != amount.quantize(CENT):
        raise ValueError(f"invalid money amount: {value!r}")
    return amount.quantize(CENT)


def to_cents(amount: Decimal) -> int:
    return int(amount * 100)


def from_cents(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


def allocate(total_cents: int, weights: Sequence[Decimal]) -> List[int]:
    """Split total_cents in proportion to weights (largest-remainder method).

    Exact pro-rata amounts are computed as Fractions, floored, and the leftover
    cents (always fewer than len(weights)) go to the largest fractional
    remainders, ties broken by position. Result sums to total_cents exactly.
    """
    if not weights:
        raise ValueError("need at least one participant")
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(Fraction(w) for w in weights)
    if weight_sum == 0:
        raise ValueError("weights must not all be zero")

    exact = [Fraction(total_cents) * Fraction(w) / weight_sum for w in weights]
    floors = [math.floor(x) for x in exact]
    leftover = total_cents - sum(floors)
    by_remainder = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in by_remainder[:leftover]:
        floors[i] += 1
    return floors


class SplitType(Enum):
    EQUAL = "Equal"
    EXACT = "Exact"
    PERCENTAGE = "Percentage"
    SHARE = "Share"


class ExpenseCategory(Enum):
    FOOD = "Food"
    TRAVEL = "Travel"
    ENTERTAINMENT = "Entertainment"
    BILLS = "Bills"
    SHOPPING = "Shopping"
    OTHER = "Other"


class SplitwiseError(Exception):
    """Base class for domain errors."""


class NotFoundError(SplitwiseError):
    pass


class InvalidSplitError(SplitwiseError, ValueError):
    pass


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    email: str

    def __str__(self) -> str:
        return self.name


# --- Split strategies (Strategy pattern; add a rule = add a class) ---

class SplitStrategy(ABC):
    """Turns (amount, participants, per-participant values) into exact shares."""

    @abstractmethod
    def calculate_shares(self, amount: Decimal, participant_ids: Sequence[str],
                         values: Optional[Sequence[MoneyLike]]) -> Dict[str, Decimal]:
        ...

    @staticmethod
    def _require_values(participant_ids: Sequence[str],
                        values: Optional[Sequence[MoneyLike]]) -> List[Decimal]:
        if values is None or len(values) != len(participant_ids):
            raise InvalidSplitError("need exactly one value per participant")
        if any(isinstance(v, (float, bool)) for v in values):
            raise InvalidSplitError("split values must be Decimal, int or str, not float")
        parsed = [Decimal(v) for v in values]
        if any(v < 0 for v in parsed):
            raise InvalidSplitError("split values must be non-negative")
        return parsed

    @staticmethod
    def _proportional(amount: Decimal, participant_ids: Sequence[str],
                      weights: Sequence[Decimal]) -> Dict[str, Decimal]:
        cents = allocate(to_cents(amount), weights)
        return {uid: from_cents(c) for uid, c in zip(participant_ids, cents)}


class EqualSplit(SplitStrategy):
    def calculate_shares(self, amount, participant_ids, values):
        if values is not None:
            raise InvalidSplitError("equal split takes no values")
        return self._proportional(amount, participant_ids, [Decimal(1)] * len(participant_ids))


class ExactSplit(SplitStrategy):
    def calculate_shares(self, amount, participant_ids, values):
        exact = [to_money(v) for v in self._require_values(participant_ids, values)]
        if sum(exact) != amount:
            raise InvalidSplitError(f"exact amounts sum to {sum(exact)}, expected {amount}")
        return dict(zip(participant_ids, exact))


class PercentageSplit(SplitStrategy):
    def calculate_shares(self, amount, participant_ids, values):
        percents = self._require_values(participant_ids, values)
        if sum(percents) != 100:
            raise InvalidSplitError(f"percentages sum to {sum(percents)}, expected 100")
        return self._proportional(amount, participant_ids, percents)


class ShareSplit(SplitStrategy):
    """Ratio split, e.g. 2:1:1 for a couple and two singles."""

    def calculate_shares(self, amount, participant_ids, values):
        ratios = self._require_values(participant_ids, values)
        if sum(ratios) == 0:
            raise InvalidSplitError("at least one share must be positive")
        return self._proportional(amount, participant_ids, ratios)


class SplitStrategyFactory:
    _strategies: Dict[SplitType, SplitStrategy] = {
        SplitType.EQUAL: EqualSplit(),
        SplitType.EXACT: ExactSplit(),
        SplitType.PERCENTAGE: PercentageSplit(),
        SplitType.SHARE: ShareSplit(),
    }

    @classmethod
    def get(cls, split_type: SplitType) -> SplitStrategy:
        try:
            return cls._strategies[split_type]
        except KeyError:
            raise InvalidSplitError(f"unsupported split type: {split_type}") from None


# --- Ledger entries (immutable once recorded) ---

@dataclass(frozen=True)
class Expense:
    expense_id: str
    description: str
    amount: Decimal
    paid_by: str
    split_type: SplitType
    shares: Mapping[str, Decimal]
    category: ExpenseCategory = ExpenseCategory.OTHER
    group_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if sum(self.shares.values()) != self.amount:
            raise InvalidSplitError("shares must sum to the expense amount")
        object.__setattr__(self, "shares", MappingProxyType(dict(self.shares)))

    def __str__(self) -> str:
        return f"{self.description}: ${self.amount} paid by {self.paid_by}"


@dataclass(frozen=True)
class Payment:
    """A settle-up: from_user hands to_user real money outside the app."""
    payment_id: str
    from_user: str
    to_user: str
    amount: Decimal
    group_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BalanceSheet:
    """Running net balance per user. Positive = is owed, negative = owes.

    Updated incrementally (O(participants) per entry) rather than recomputed
    from all expenses on every read. Not thread-safe on its own; the service
    lock guards it.
    """

    def __init__(self) -> None:
        self._net: Dict[str, Decimal] = {}

    def _add(self, user_id: str, delta: Decimal) -> None:
        value = self._net.get(user_id, Decimal("0.00")) + delta
        if value == 0:
            self._net.pop(user_id, None)
        else:
            self._net[user_id] = value

    def apply_expense(self, expense: Expense, sign: int = 1) -> None:
        self._add(expense.paid_by, sign * expense.amount)
        for user_id, share in expense.shares.items():
            self._add(user_id, -sign * share)

    def apply_payment(self, payment: Payment) -> None:
        self._add(payment.from_user, payment.amount)
        self._add(payment.to_user, -payment.amount)

    def balance_of(self, user_id: str) -> Decimal:
        return self._net.get(user_id, Decimal("0.00"))

    def snapshot(self) -> Dict[str, Decimal]:
        return dict(self._net)


class Group:
    def __init__(self, group_id: str, name: str) -> None:
        self.group_id = group_id
        self.name = name
        self._member_ids: List[str] = []
        self.ledger = BalanceSheet()

    @property
    def member_ids(self) -> List[str]:
        return list(self._member_ids)

    def is_member(self, user_id: str) -> bool:
        return user_id in self._member_ids

    def add_member(self, user_id: str) -> None:
        if user_id not in self._member_ids:
            self._member_ids.append(user_id)

    def remove_member(self, user_id: str) -> None:
        if self.ledger.balance_of(user_id) != 0:
            raise SplitwiseError("cannot remove a member with a non-zero balance")
        self._member_ids.remove(user_id)

    def __str__(self) -> str:
        return f"Group: {self.name} ({len(self._member_ids)} members)"


# --- Settlement ("simplify debts") strategies ---

class Transfer(NamedTuple):
    debtor: str
    creditor: str
    amount: Decimal


class SettlementStrategy(ABC):
    @abstractmethod
    def settle(self, balances: Mapping[str, Decimal]) -> List[Transfer]:
        ...


class GreedySettlement(SettlementStrategy):
    """Repeatedly match the largest debtor with the largest creditor.

    O(n log n). Each transfer zeroes at least one person, so it never needs
    more than n - 1 transfers (n = people with a non-zero balance). It is not
    always minimal: for {A:-8, B:-7, C:-2, D:+9, E:+8} it pairs A with D and
    needs 4 transfers, missing the zero-sum pair (A, E) that allows 3.
    """

    def settle(self, balances: Mapping[str, Decimal]) -> List[Transfer]:
        debtors = [(to_cents(b), uid) for uid, b in balances.items() if b < 0]          # most negative first
        creditors = [(-to_cents(b), uid) for uid, b in balances.items() if b > 0]       # largest first
        if sum(c for c, _ in debtors) + sum(-c for c, _ in creditors) != 0:
            raise ValueError("balances must sum to zero")
        heapq.heapify(debtors)
        heapq.heapify(creditors)
        transfers: List[Transfer] = []
        while debtors and creditors:
            owed, debtor = heapq.heappop(debtors)            # owed < 0
            due, creditor = heapq.heappop(creditors)          # due < 0 (negated)
            cents = min(-owed, -due)
            transfers.append(Transfer(debtor, creditor, from_cents(cents)))
            if owed + cents:
                heapq.heappush(debtors, (owed + cents, debtor))
            if due + cents:
                heapq.heappush(creditors, (due + cents, creditor))
        return transfers


class OptimalSettlement(SettlementStrategy):
    """Minimum number of transfers, exact.

    Minimum transfers = n - k, where k is the largest number of disjoint
    zero-sum subgroups the n non-zero balances can be partitioned into
    (each subgroup of size m settles in m - 1 transfers). Finding k is
    NP-hard, so this is a bitmask DP in O(2^n * n). Above max_people it
    falls back to the greedy heuristic.
    """

    def __init__(self, max_people: int = 12, fallback: Optional[SettlementStrategy] = None):
        self._max_people = max_people
        self._fallback = fallback or GreedySettlement()

    def settle(self, balances: Mapping[str, Decimal]) -> List[Transfer]:
        people = sorted(uid for uid, b in balances.items() if b != 0)
        n = len(people)
        if n > self._max_people:
            return self._fallback.settle(balances)
        cents = [to_cents(balances[uid]) for uid in people]
        if sum(cents) != 0:
            raise ValueError("balances must sum to zero")

        full = (1 << n) - 1
        subset_sum = [0] * (full + 1)
        best = [0] * (full + 1)          # max zero-sum subgroups within mask
        for mask in range(1, full + 1):
            low = (mask & -mask).bit_length() - 1
            subset_sum[mask] = subset_sum[mask & (mask - 1)] + cents[low]
            best[mask] = max(best[mask ^ (1 << i)] for i in range(n) if mask >> i & 1) \
                + (subset_sum[mask] == 0)

        # Walk the DP back to recover one optimal partition into zero-sum subgroups.
        order, mask = [], full
        while mask:
            target = best[mask] - (subset_sum[mask] == 0)
            i = next(i for i in range(n) if mask >> i & 1 and best[mask ^ (1 << i)] == target)
            order.append(i)
            mask ^= 1 << i
        transfers: List[Transfer] = []
        subgroup: Dict[str, Decimal] = {}
        mask = full
        for i in order:
            subgroup[people[i]] = balances[people[i]]
            mask ^= 1 << i
            if mask == 0 or subset_sum[mask] == 0:
                transfers += self._fallback.settle(subgroup)   # m - 1 transfers inside a subgroup
                subgroup = {}
        return transfers


# --- Facade ---

class SplitwiseService:
    """Entry point. Thread-safe: one lock covers every read and write."""

    def __init__(self, settlement: Optional[SettlementStrategy] = None) -> None:
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self._users: Dict[str, User] = {}
        self._groups: Dict[str, Group] = {}
        self._expenses: Dict[str, Expense] = {}
        self._payments: List[Payment] = []
        self._personal = BalanceSheet()       # expenses outside any group
        self._settlement = settlement or GreedySettlement()

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # users & groups

    def add_user(self, name: str, email: str) -> User:
        with self._lock:
            user = User(self._next_id("U"), name, email)
            self._users[user.user_id] = user
            return user

    def get_user(self, user_id: str) -> User:
        with self._lock:
            return self._require_user(user_id)

    def create_group(self, name: str, member_ids: Sequence[str] = ()) -> Group:
        with self._lock:
            for uid in member_ids:
                self._require_user(uid)
            group = Group(self._next_id("G"), name)
            for uid in member_ids:
                group.add_member(uid)
            self._groups[group.group_id] = group
            return group

    def add_member(self, group_id: str, user_id: str) -> None:
        with self._lock:
            self._require_user(user_id)
            self._require_group(group_id).add_member(user_id)

    def remove_member(self, group_id: str, user_id: str) -> None:
        with self._lock:
            self._require_group(group_id).remove_member(user_id)

    # expenses & payments

    def add_expense(self, description: str, amount: MoneyLike, paid_by: str,
                    participant_ids: Sequence[str],
                    split_type: SplitType = SplitType.EQUAL,
                    values: Optional[Sequence[MoneyLike]] = None,
                    group_id: Optional[str] = None,
                    category: ExpenseCategory = ExpenseCategory.OTHER) -> Expense:
        total = to_money(amount)
        if total <= 0:
            raise InvalidSplitError("amount must be positive")
        if not participant_ids:
            raise InvalidSplitError("need at least one participant")
        if len(set(participant_ids)) != len(participant_ids):
            raise InvalidSplitError("duplicate participant")

        with self._lock:
            ledger = self._ledger_for(group_id, [paid_by, *participant_ids])
            shares = SplitStrategyFactory.get(split_type).calculate_shares(
                total, participant_ids, values)
            expense = Expense(self._next_id("E"), description, total, paid_by,
                              split_type, shares, category, group_id)
            self._expenses[expense.expense_id] = expense
            ledger.apply_expense(expense)
            return expense

    def delete_expense(self, expense_id: str) -> None:
        """Reverse an expense's ledger effect (Splitwise lets you undo/edit)."""
        with self._lock:
            expense = self._expenses.pop(expense_id, None)
            if expense is None:
                raise NotFoundError(f"expense {expense_id} not found")
            ledger = self._groups[expense.group_id].ledger if expense.group_id else self._personal
            ledger.apply_expense(expense, sign=-1)

    def record_payment(self, from_user: str, to_user: str, amount: MoneyLike,
                       group_id: Optional[str] = None) -> Payment:
        value = to_money(amount)
        if value <= 0:
            raise InvalidSplitError("payment must be positive")
        if from_user == to_user:
            raise InvalidSplitError("cannot pay yourself")
        with self._lock:
            ledger = self._ledger_for(group_id, [from_user, to_user])
            payment = Payment(self._next_id("P"), from_user, to_user, value, group_id)
            self._payments.append(payment)
            ledger.apply_payment(payment)
            return payment

    # queries

    def get_balance(self, user_id: str) -> Decimal:
        """Net across all groups and personal expenses. Positive = is owed."""
        with self._lock:
            self._require_user(user_id)
            return self._personal.balance_of(user_id) + sum(
                (g.ledger.balance_of(user_id) for g in self._groups.values()), Decimal("0.00"))

    def get_group_balances(self, group_id: str) -> Dict[str, Decimal]:
        with self._lock:
            return self._require_group(group_id).ledger.snapshot()

    def get_settlement_plan(self, group_id: str,
                            strategy: Optional[SettlementStrategy] = None) -> List[Transfer]:
        balances = self.get_group_balances(group_id)   # consistent snapshot, then compute unlocked
        return (strategy or self._settlement).settle(balances)

    # helpers (call with lock held)

    def _require_user(self, user_id: str) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return user

    def _require_group(self, group_id: str) -> Group:
        group = self._groups.get(group_id)
        if group is None:
            raise NotFoundError(f"group {group_id} not found")
        return group

    def _ledger_for(self, group_id: Optional[str], user_ids: Sequence[str]) -> BalanceSheet:
        for uid in user_ids:
            self._require_user(uid)
        if group_id is None:
            return self._personal
        group = self._require_group(group_id)
        outsiders = [uid for uid in user_ids if not group.is_member(uid)]
        if outsiders:
            raise SplitwiseError(f"not members of {group.name}: {outsiders}")
        return group.ledger


# --- Demo ---

def demo() -> None:
    print("=== Splitwise Expense Sharing Demo ===")
    sw = SplitwiseService()
    alice, bob, charlie, diana = (sw.add_user(n, f"{n.lower()}@example.com")
                                  for n in ("Alice", "Bob", "Charlie", "Diana"))
    everyone = [alice.user_id, bob.user_id, charlie.user_id, diana.user_id]
    trip = sw.create_group("Goa Trip", everyone)
    print(f"\nCreated {trip}")

    def name(uid: str) -> str:
        return sw.get_user(uid).name

    print("\n--- Adding expenses ---")
    expenses = [
        sw.add_expense("Dinner", "100.00", alice.user_id, everyone[:3],
                       group_id=trip.group_id, category=ExpenseCategory.FOOD),
        sw.add_expense("Cab", "60.00", bob.user_id, everyone,
                       SplitType.PERCENTAGE, ["40", "20", "20", "20"], trip.group_id),
        sw.add_expense("Hotel", "400.00", charlie.user_id, everyone,
                       SplitType.SHARE, ["2", "1", "1", "0"], trip.group_id),
        sw.add_expense("Drinks", "90.00", diana.user_id, [alice.user_id, diana.user_id],
                       SplitType.EXACT, ["50.00", "40.00"], trip.group_id),
    ]
    for e in expenses:
        shares = ", ".join(f"{name(u)}={s}" for u, s in e.shares.items())
        print(f"  {e.description} ${e.amount} paid by {name(e.paid_by)} [{e.split_type.value}]: {shares}")

    print("\n--- Net balances (Dinner: 100 / 3 -> 33.34 + 33.33 + 33.33) ---")
    balances = sw.get_group_balances(trip.group_id)
    for uid in everyone:
        print(f"  {name(uid)}: {balances.get(uid, Decimal('0.00')):+}")
    assert sum(balances.values()) == 0

    print("\n--- Settlement plan (greedy) ---")
    plan = sw.get_settlement_plan(trip.group_id)
    for t in plan:
        print(f"  {name(t.debtor)} pays {name(t.creditor)} ${t.amount}")

    print("\n--- Settling up ---")
    for t in plan:
        sw.record_payment(t.debtor, t.creditor, t.amount, trip.group_id)
    print(f"  Balances after paying the plan: {sw.get_group_balances(trip.group_id) or 'all settled'}")

    print("\n--- Greedy vs optimal on a tricky case ---")
    tricky = {"A": Decimal("-8"), "B": Decimal("-7"), "C": Decimal("-2"),
              "D": Decimal("9"), "E": Decimal("8")}
    print(f"  balances {dict((k, str(v)) for k, v in tricky.items())}")
    for label, strategy in (("greedy ", GreedySettlement()), ("optimal", OptimalSettlement())):
        transfers = strategy.settle(tricky)
        print(f"  {label}: {len(transfers)} transfers: "
              + ", ".join(f"{t.debtor}->{t.creditor} {t.amount}" for t in transfers))


if __name__ == "__main__":
    demo()
