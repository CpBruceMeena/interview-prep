# Splitwise / Expense Sharing - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Graphs, debt minimization, strategy pattern, financial accuracy

---

## Question 1: Core Design
**Interviewer:** *"Design an expense sharing application like Splitwise with groups, expenses, and balance calculation."*

### 🎯 Expected Answer

**Domain Model:**
```python
class Expense:
    def __init__(self, amount, paid_by, participants, split_type, values=None):
        self._amount = amount
        self._paid_by = paid_by  # User who paid
        self._shares = self._calculate_shares(split_type, values)
    
    def _calculate_shares(self, split_type, values):
        strategy = SplitStrategyFactory.get_strategy(split_type)
        return strategy.calculate_shares(self._amount, self._participants, values)
```

**Strategy Pattern for Split Types — OCP in action:**
```python
class SplitStrategy(ABC):
    @abstractmethod
    def calculate_shares(self, total, participants, values=None): pass

class EqualSplit(SplitStrategy):
    def calculate_shares(self, total, participants, values=None):
        share = round(total / len(participants), 2)
        # Handle rounding: add/subtract 1 cent discrepancy
        shares = {u.user_id: share for u in participants}
        diff = round(total - sum(shares.values()), 2)
        shares[participants[0].user_id] = round(share + diff, 2)
        return shares
```

**Why not a simple enum with if-else?** Because adding a new split type (e.g., `SplitType.RATIO`) means modifying the if-else chain. With Strategy + Factory, you add one class + one registry entry. Zero existing code changes — textbook OCP.

---

## Question 2: Debt Simplification (Minimum Transactions)
**Interviewer:** *"Given balances, find minimum transactions to settle all debts."*

### 🎯 Algorithm Analysis

**This is NP-Hard** (minimum exchange problem = subset sum).

**Greedy Heuristic O(n log n):**
```python
def simplify_debts(balances: Dict[str, float]) -> List[Tuple[str, str, float]]:
    # Sort by balance (most negative = biggest debtor, most positive = biggest creditor)
    debts = sorted(balances.items(), key=lambda x: x[1])
    
    i, j = 0, len(debts) - 1
    transactions = []
    while i < j:
        debtor, debt = debts[i]
        creditor, credit = debts[j]
        
        amount = min(-debt, credit)
        transactions.append((debtor, creditor, round(amount, 2)))
        
        # Update
        debts[i] = (debtor, debt + amount)
        debts[j] = (creditor, credit - amount)
        
        if abs(debts[i][1]) < 0.01: i += 1
        if abs(debts[j][1]) < 0.01: j -= 1
    
    return transactions
```

**Why greedy?** The optimal solution is NP-Hard (reduction from subset sum). Greedy gives near-optimal in O(n log n). In practice, users prefer "Alice pays Bob directly" over "Alice pays Bob, Bob pays Charlie" — even if the latter uses fewer transactions.

**The user experience trumps mathematical optimality.** Splitwise's actual algorithm prioritizes simplicity: minimize the number of people touched, even if it means more transactions.

---

## Question 3: Complex Split Scenarios

| Scenario | Solution |
|----------|----------|
| **Partial participants** | Expense tracks `paid_by` and `participants` separately |
| **Recurring expenses** | `RecurringExpense` wrapper with frequency + next_due |
| **Tax/tip** | Add as `Adjustment` line items before split |
| **Multi-currency** | Store in base currency (USD), convert at current rate |
| **Rounding** | Always assign rounding difference to the payer |

---

## Question 4: Concurrency & Consistency

**Optimistic locking:**
```python
def add_expense(expense_id, expected_version):
    result = db.execute("""
        UPDATE expenses 
        SET amount = ?, version = version + 1
        WHERE expense_id = ? AND version = ?
    """, [amount, expense_id, expected_version])
    
    if result.rows_affected == 0:
        raise ConcurrentModificationError()
```

**Eventual consistency for balances:** Balance calculation is a batch process, not real-time. Calculate on read with memoization, invalidate on write.

---

## Question 5: Settlement & Payment Integration

**Payment Request Flow:**
```python
# Payment gateway integration
class SettlementProcessor:
    def process_settlement(self, from_user, to_user, amount):
        # 1. Create payment request
        payment_request = PaymentGateway.create_request(
            from_user.payment_token,
            to_user.account_id,
            amount,
            "Splitwise settlement"
        )
        # 2. Send notification
        NotificationService.send(from_user, f"Pay {to_user.name} ${amount}")
        # 3. On completion, mark as settled
        if payment_request.status == "COMPLETED":
            self._mark_settled(from_user, to_user, amount)
```

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | SplitStrategy | Equal, exact, percentage, share splits |
| **Factory** | SplitStrategyFactory | Create strategy from type |
| **Observer** | Notifications | Email/SMS on expense added |
| **Facade** | SplitwiseService | Unified interface |
| **Command** | Expense operations | Undo/redo support |
