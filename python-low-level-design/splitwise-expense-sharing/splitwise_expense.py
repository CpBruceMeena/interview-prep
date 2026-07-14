"""
Splitwise - Expense Sharing System - Low Level Design
-------------------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer Pattern
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
import uuid


class SplitType(Enum):
    EQUAL = "Equal"
    EXACT = "Exact"
    PERCENTAGE = "Percentage"
    SHARE = "Share"
    ADJUSTMENT = "Adjustment"


class ExpenseCategory(Enum):
    FOOD = "Food"
    TRAVEL = "Travel"
    ENTERTAINMENT = "Entertainment"
    BILLS = "Bills"
    SHOPPING = "Shopping"
    OTHER = "Other"


@dataclass
class User:
    """Represents a user in the system"""
    user_id: str
    name: str
    email: str
    phone: str = ""

    def __hash__(self) -> int:
        return hash(self.user_id)

    def __str__(self) -> str:
        return self.name


# --- Split Strategy (Strategy Pattern - OCP) ---

class SplitStrategy(ABC):
    """Interface Segregation: Specific to expense splitting"""

    @abstractmethod
    def calculate_shares(self, total_amount: float,
                         participants: List[User],
                         values: Optional[List[float]] = None) -> Dict[str, float]:
        pass


class EqualSplit(SplitStrategy):
    def calculate_shares(self, total_amount: float,
                         participants: List[User],
                         values: Optional[List[float]] = None) -> Dict[str, float]:
        share = round(total_amount / len(participants), 2)
        result = {u.user_id: share for u in participants}
        # Handle rounding difference
        total = sum(result.values())
        diff = round(total_amount - total, 2)
        if diff != 0:
            result[participants[0].user_id] = round(share + diff, 2)
        return result


class ExactSplit(SplitStrategy):
    def calculate_shares(self, total_amount: float,
                         participants: List[User],
                         values: Optional[List[float]] = None) -> Dict[str, float]:
        if not values or len(values) != len(participants):
            raise ValueError("Exact split requires values for each participant")
        if sum(values) != total_amount:
            raise ValueError(f"Exact amounts must sum to {total_amount}")
        return {u.user_id: v for u, v in zip(participants, values)}


class PercentageSplit(SplitStrategy):
    def calculate_shares(self, total_amount: float,
                         participants: List[User],
                         values: Optional[List[float]] = None) -> Dict[str, float]:
        if not values or len(values) != len(participants):
            raise ValueError("Percentage split requires values for each participant")
        if sum(values) != 100.0:
            raise ValueError("Percentages must sum to 100")
        return {u.user_id: round(total_amount * v / 100, 2)
                for u, v in zip(participants, values)}


class ShareSplit(SplitStrategy):
    def calculate_shares(self, total_amount: float,
                         participants: List[User],
                         values: Optional[List[float]] = None) -> Dict[str, float]:
        if not values or len(values) != len(participants):
            raise ValueError("Share split requires values for each participant")
        total_shares = sum(values)
        return {u.user_id: round(total_amount * v / total_shares, 2)
                for u, v in zip(participants, values)}


# --- Split Strategy Factory ---

class SplitStrategyFactory:
    _strategies = {
        SplitType.EQUAL: EqualSplit,
        SplitType.EXACT: ExactSplit,
        SplitType.PERCENTAGE: PercentageSplit,
        SplitType.SHARE: ShareSplit,
    }

    @classmethod
    def get_strategy(cls, split_type: SplitType) -> SplitStrategy:
        strategy_class = cls._strategies.get(split_type)
        if not strategy_class:
            raise ValueError(f"Unknown split type: {split_type}")
        return strategy_class()


# --- Expense (SRP) ---

class Expense:
    """Single Responsibility: Represents an expense"""

    def __init__(self, expense_id: str, description: str, amount: float,
                 paid_by: User, participants: List[User],
                 split_type: SplitType = SplitType.EQUAL,
                 category: ExpenseCategory = ExpenseCategory.OTHER,
                 values: Optional[List[float]] = None,
                 group_id: Optional[str] = None):
        self._expense_id = expense_id
        self._description = description
        self._amount = amount
        self._paid_by = paid_by
        self._participants = participants
        self._split_type = split_type
        self._category = category
        self._group_id = group_id
        self._created_at = datetime.now()

        # Calculate shares
        strategy = SplitStrategyFactory.get_strategy(split_type)
        self._shares = strategy.calculate_shares(amount, participants, values)

        # Record who paid
        self._paid_amounts: Dict[str, float] = {paid_by.user_id: amount}

    @property
    def expense_id(self) -> str:
        return self._expense_id

    @property
    def description(self) -> str:
        return self._description

    @property
    def amount(self) -> float:
        return self._amount

    @property
    def paid_by(self) -> User:
        return self._paid_by

    @property
    def shares(self) -> Dict[str, float]:
        return dict(self._shares)

    def get_share_for_user(self, user_id: str) -> float:
        return self._shares.get(user_id, 0.0)

    def __str__(self) -> str:
        return f"{self._description}: ${self._amount:.2f} paid by {self._paid_by.name}"


# --- Group (SRP) ---

class Group:
    """Single Responsibility: Manages a group of users with shared expenses"""

    def __init__(self, group_id: str, name: str, description: str = ""):
        self._group_id = group_id
        self._name = name
        self._description = description
        self._members: Dict[str, User] = {}
        self._expenses: List[Expense] = []

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def members(self) -> List[User]:
        return list(self._members.values())

    def add_member(self, user: User) -> None:
        self._members[user.user_id] = user

    def remove_member(self, user_id: str) -> None:
        self._members.pop(user_id, None)

    def add_expense(self, expense: Expense) -> None:
        self._expenses.append(expense)

    @property
    def expenses(self) -> List[Expense]:
        return list(self._expenses)

    def __str__(self) -> str:
        return f"Group: {self._name} ({len(self._members)} members)"


# --- Balance Calculator (SRP) ---

class BalanceCalculator:
    """Single Responsibility: Calculates balances between users"""

    @staticmethod
    def calculate_balances(expenses: List[Expense],
                           members: Optional[List[User]] = None) -> Dict[str, float]:
        """Calculate net balance for each user (positive = owed money)"""
        balances: Dict[str, float] = {}

        for expense in expenses:
            # Person who paid is owed money
            payer = expense.paid_by.user_id
            balances[payer] = balances.get(payer, 0) + expense.amount

            # Each participant owes their share
            for user_id, share in expense.shares.items():
                if user_id != payer:
                    balances[user_id] = balances.get(user_id, 0) - share
                elif user_id == payer:
                    balances[payer] = balances.get(payer, 0) - share

        return balances

    @staticmethod
    def simplify_debts(balances: Dict[str, float]) -> List[Tuple[str, str, float]]:
        """Simplifies debts to minimize transactions.
        Uses greedy algorithm to find max creditor and debtor."""
        # Filter out zero balances
        debts = [(uid, amt) for uid, amt in balances.items() if abs(amt) > 0.01]
        debts.sort(key=lambda x: x[1])  # Sort by balance

        transactions: List[Tuple[str, str, float]] = []
        i, j = 0, len(debts) - 1

        while i < j:
            debtor, debt_amt = debts[i]
            creditor, credit_amt = debts[j]

            amount = min(-debt_amt, credit_amt)
            amount = round(amount, 2)

            if amount > 0.01:
                transactions.append((debtor, creditor, amount))

            debts[i] = (debtor, debt_amt + amount)
            debts[j] = (creditor, credit_amt - amount)

            if abs(debts[i][1]) < 0.01:
                i += 1
            if abs(debts[j][1]) < 0.01:
                j -= 1

        return transactions


# --- Splitwise Service (Facade) ---

class SplitwiseService:
    """Facade for the entire expense sharing system"""

    def __init__(self):
        self._users: Dict[str, User] = {}
        self._groups: Dict[str, Group] = {}
        self._expenses: Dict[str, Expense] = {}

    def add_user(self, name: str, email: str, phone: str = "") -> User:
        user_id = f"U-{uuid.uuid4().hex[:6].upper()}"
        user = User(user_id, name, email, phone)
        self._users[user_id] = user
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def create_group(self, name: str, description: str = "",
                     members: Optional[List[User]] = None) -> Group:
        group_id = f"G-{uuid.uuid4().hex[:6].upper()}"
        group = Group(group_id, name, description)
        if members:
            for member in members:
                group.add_member(member)
        self._groups[group_id] = group
        return group

    def get_group(self, group_id: str) -> Optional[Group]:
        return self._groups.get(group_id)

    def add_expense(self, description: str, amount: float,
                    paid_by_user_id: str,
                    participant_ids: List[str],
                    split_type: SplitType = SplitType.EQUAL,
                    category: ExpenseCategory = ExpenseCategory.OTHER,
                    values: Optional[List[float]] = None,
                    group_id: Optional[str] = None) -> Expense:
        paid_by = self._users.get(paid_by_user_id)
        if not paid_by:
            raise ValueError(f"User {paid_by_user_id} not found")

        participants = [self._users[uid] for uid in participant_ids]
        if any(u is None for u in participants):
            raise ValueError("One or more participants not found")

        expense_id = f"E-{uuid.uuid4().hex[:8].upper()}"
        expense = Expense(expense_id, description, amount, paid_by,
                          participants, split_type, category, values, group_id)

        self._expenses[expense_id] = expense

        if group_id and group_id in self._groups:
            self._groups[group_id].add_expense(expense)

        return expense

    def get_balance(self, user_id: str) -> float:
        """Get net balance for a user across all expenses"""
        balance = 0.0
        for expense in self._expenses.values():
            share = expense.get_share_for_user(user_id)
            if expense.paid_by.user_id == user_id:
                balance += expense.amount - share
            else:
                balance -= share
        return round(balance, 2)

    def get_group_balances(self, group_id: str) -> Dict[str, float]:
        """Get balances within a group"""
        group = self._groups.get(group_id)
        if not group:
            return {}
        return BalanceCalculator.calculate_balances(group.expenses)

    def get_simplified_debts(self, group_id: str) -> List[Tuple[str, str, float]]:
        """Get simplified debt settlement plan"""
        balances = self.get_group_balances(group_id)
        return BalanceCalculator.simplify_debts(balances)

    def get_all_balances(self) -> Dict[str, float]:
        return BalanceCalculator.calculate_balances(list(self._expenses.values()))


# --- Demo ---

def demo():
    print("=== Splitwise Expense Sharing Demo ===")
    print("=" * 50)

    splitwise = SplitwiseService()

    # Create users
    alice = splitwise.add_user("Alice", "alice@email.com")
    bob = splitwise.add_user("Bob", "bob@email.com")
    charlie = splitwise.add_user("Charlie", "charlie@email.com")
    diana = splitwise.add_user("Diana", "diana@email.com")

    # Create a group for the trip
    group = splitwise.create_group("Goa Trip 2025", "Summer vacation", [alice, bob, charlie, diana])
    print(f"\nCreated: {group}")

    # Add expenses
    print("\n--- Adding Expenses ---")

    # Dinner - paid by Alice, split equally
    expense1 = splitwise.add_expense(
        "Dinner at Beach Shack", 120.0, alice.user_id,
        [alice.user_id, bob.user_id, charlie.user_id, diana.user_id],
        SplitType.EQUAL, ExpenseCategory.FOOD, group_id=group.group_id
    )
    print(f"  Added: {expense1}")

    # Cab - paid by Bob, split equally
    expense2 = splitwise.add_expense(
        "Airport Cab", 60.0, bob.user_id,
        [alice.user_id, bob.user_id, charlie.user_id, diana.user_id],
        SplitType.EQUAL, ExpenseCategory.TRAVEL, group_id=group.group_id
    )
    print(f"  Added: {expense2}")

    # Hotel - paid by Charlie with exact split
    expense3 = splitwise.add_expense(
        "Hotel Booking", 400.0, charlie.user_id,
        [alice.user_id, bob.user_id, charlie.user_id, diana.user_id],
        SplitType.EXACT, ExpenseCategory.TRAVEL,
        values=[100.0, 100.0, 100.0, 100.0], group_id=group.group_id
    )
    print(f"  Added: {expense3}")

    # Drinks - paid by Diana with shares
    expense4 = splitwise.add_expense(
        "Wine & Drinks", 90.0, diana.user_id,
        [alice.user_id, charlie.user_id, diana.user_id],
        SplitType.EQUAL, ExpenseCategory.ENTERTAINMENT,
        group_id=group.group_id
    )
    print(f"  Added: {expense4}")

    # Show balances
    print("\n--- Individual Balances ---")
    for user in [alice, bob, charlie, diana]:
        balance = splitwise.get_balance(user.user_id)
        status = "is owed" if balance > 0 else "owes"
        print(f"  {user.name}: {status} ${abs(balance):.2f}")

    # Show simplified debts
    print("\n--- Simplified Debt Settlement ---")
    debts = splitwise.get_simplified_debts(group.group_id)
    for debtor_id, creditor_id, amount in debts:
        debtor = splitwise.get_user(debtor_id)
        creditor = splitwise.get_user(creditor_id)
        print(f"  {debtor.name} pays {creditor.name}: ${amount:.2f}")

    # Show balances by name
    print("\n--- Group Balance Summary ---")
    balances = splitwise.get_group_balances(group.group_id)
    for uid, bal in sorted(balances.items(), key=lambda x: x[1], reverse=True):
        user = splitwise.get_user(uid)
        if user:
            print(f"  {user.name}: {'+$' if bal >= 0 else '-$'}{abs(bal):.2f}")


if __name__ == "__main__":
    demo()
