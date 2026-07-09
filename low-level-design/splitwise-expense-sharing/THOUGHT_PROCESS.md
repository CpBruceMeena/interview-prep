# 🧠 Splitwise / Expense Sharing LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

How are expenses split? (Equal, exact amount, percentage?) Can users organize into groups? How to simplify debts?

## Phase 1: Identify the Nouns

> *"Users in a group share expenses. One person pays, the cost is split among participants. Balances are tracked and can be simplified."*

| Noun | Decision | Why |
|------|----------|-----|
| User | dataclass | Identity class, minimal behavior |
| Group | Regular Class | Contains members + expenses |
| Expense | Regular Class | Has payer, participants, split strategy |
| SplitStrategy | ABC | Strategy for calculating shares |
| BalanceCalculator | Regular (static) | Pure functions for balance computation |
| SplitwiseService | Facade | Main entry point |
| SplitType | Enum | EQUAL, EXACT, PERCENTAGE, SHARE |
| ExpenseCategory | Enum | FOOD, TRAVEL, BILLS, etc. |

## Phase 2: Enums First

```python
class SplitType(Enum):      EQUAL, EXACT, PERCENTAGE, SHARE, ADJUSTMENT
class ExpenseCategory(Enum): FOOD, TRAVEL, ENTERTAINMENT, BILLS, SHOPPING, OTHER
```

## Phase 3: dataclass vs `__init__`

- **`User`**: `@dataclass` — it's a pure data holder (user_id, name, email, phone). No behavior.
- **`Expense`**: Regular — has behavior (calculate shares via strategy)
- **`Group`**: Regular — manages members + expenses
- **`BalanceCalculator`**: Static methods — no instance needed, pure functions
- **`SplitStrategy`**: ABC — each strategy calculates differently

**Key insight:** `User` is a dataclass candidate because it has no behavior — just fields and a hash.

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Calculate shares | `SplitStrategy.calculate_shares()` | Strategy encapsulates split logic |
| Create expense | `SplitwiseService.add_expense()` | Service uses factory + strategy |
| Track group expenses | `Group.add_expense()` | Group holds its expenses |
| Compute net balances | `BalanceCalculator.calculate_balances()` | Pure math function |
| Simplify debts | `BalanceCalculator.simplify_debts()` | Minimizes transactions |
| Get user balance | `SplitwiseService.get_balance()` | Queries across all expenses |

## Phase 5: Strategy Pattern for Splits

```python
class SplitStrategy(ABC):
    def calculate_shares(self, amount, participants, values) -> Dict[str, float]

class EqualSplit(SplitStrategy):       # amount / N
class ExactSplit(SplitStrategy):       # specific amounts per person
class PercentageSplit(SplitStrategy):  # percentage of total
class ShareSplit(SplitStrategy):       # ratio-based (2:3:1)
```

## Phase 6: Balance Simplification Algorithm

The `simplify_debts` method uses a greedy algorithm:
1. Sort balances from most negative (debtor) to most positive (creditor)
2. Match the biggest debtor with the biggest creditor
3. Settle the partial amount
4. Repeat until all debts are settled

This minimizes the number of transactions.

## Phase 7: Handling Rounding Errors

```python
# EqualSplit handles rounding by adding the difference to the first person
share = round(total_amount / len(participants), 2)
total = sum(result.values())
diff = round(total_amount - total, 2)
if diff != 0:
    result[participants[0].user_id] = round(share + diff, 2)
```

This is a real-world detail that interviewers love.

## Phase 8: Quick Checklist

✅ **Strategy Pattern:** Split methods are extensible (add `CustomSplit`)
✅ **SRP:** BalanceCalculator is pure math, Expense tracks data, Service orchestrates
✅ **Encapsulation:** Each expense stores its own shares
✅ **Round-trip accuracy:** Handles penny rounding issues
