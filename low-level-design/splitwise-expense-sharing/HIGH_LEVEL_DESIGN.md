# 🏗️ Splitwise / Expense Sharing — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Debt graph algorithms, financial accuracy, payment integration

---

## 1. SYSTEM OVERVIEW

**Purpose:** Expense sharing platform where groups track shared expenses and settle debts with minimal transactions.

**Scale:** 10M users, 50M expenses/month, 5M groups active

**Users:** End users (splitting bills), Power users (roommates, trip groups), Admins

**Use Cases:** Add expense (equal/exact/percentage), Split restaurant bills, Settle debts, Trip expense tracking, Monthly recurring bills

**Constraints:** Financial accuracy (no rounding errors to lose money), <500ms balance calculation, eventual consistency for cross-device sync

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Mobile App / Web (React/PWA)
      │
┌─────▼──────┐
│ API Gateway │── Auth (OAuth2) ── Rate Limit
└─────┬──────┘
      │
┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
│ Expense    │  │ Settlement │  │ Notification│
│ Service    │  │ Service    │  │ Service     │
│ (Python)   │  │ (Python)   │  │ (Node.js)   │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
┌─────▼───────────────▼───────────────▼──────┐
│              Message Queue (RabbitMQ)       │
│  - expense.created → notification          │
│  - settlement.due → reminder               │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│              PostgreSQL                       │
│  - Users, Groups, Expenses, Settlements      │
│  - Optimistic locking with version numbers   │
└─────────────────────────────────────────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Expense Service (Python/FastAPI)
- CRUD expenses with split calculation
- Strategy pattern: Equal, Exact, Percentage, Share
- Rounding management (pays rounding difference to payer)

**🔴 Interview Question:** *"How do you handle rounding errors in expense splits?"*

**✅ Answer:** Financial rounding is critical — cumulative errors lose money.
```python
def equal_split(total, participants):
    base = round(total / len(participants), 2)
    shares = {u: base for u in participants}
    diff = round(total - sum(shares.values()), 2)
    # Assign rounding difference to the person who paid
    shares[paid_by] += diff
    return shares
```
This guarantees `sum(shares) == total` always. The slight 1-cent difference goes to the payer — they're the one approving the expense.

---

### Settlement Service (Python)
- Balance calculation (O(G) where G = group expenses)
- Debt simplification (greedy min-transactions, NP-hard optimal)
- Payment request creation

**🔴 Interview Question:** *"What algorithm do you use for debt simplification?"*

**✅ Answer:** The minimum transaction problem is NP-hard (subset sum reduction). I use a **greedy heuristic**:
1. Calculate net balances: `net[user] = paid - owed`
2. Sort by net balance (ascending)
3. Match biggest debtor with biggest creditor, settle as much as possible
4. Repeat until all balances < 1 cent

This gives near-optimal (within 1 transaction of optimal) in O(n log n) time. Splitwise's research shows users prefer clarity over optimality — "Alice pays Bob directly" is preferred even if "Alice pays Bob, Bob pays Charlie" uses fewer transactions.

---

### Notification Service (Node.js)
- Push: Payment reminders, new expenses, settlement confirmations
- Email: Weekly/monthly summaries
- WebSocket: Real-time expense updates within group

---

## 4. DATA MODEL

```sql
CREATE TABLE groups (
    id UUID, name TEXT, created_by UUID, created_at TIMESTAMP
);
CREATE TABLE group_members (
    group_id UUID, user_id UUID, role TEXT DEFAULT 'member'
);
CREATE TABLE expenses (
    id UUID, group_id UUID, description TEXT, amount DECIMAL(12,2),
    paid_by UUID, split_type TEXT, created_at TIMESTAMP
);
CREATE TABLE expense_shares (
    expense_id UUID, user_id UUID, share_amount DECIMAL(12,2)
);
CREATE TABLE settlements (
    id UUID, group_id UUID, from_user UUID, to_user UUID,
    amount DECIMAL(12,2), status TEXT, created_at TIMESTAMP
);
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Currency | Store in base + original | Multi-currency support; show in user's preferred currency |
| Balance calc | Read-time computation | Cached for 30 seconds; recalculated on any new expense |
| Rounding | Assign to payer | Payer approves — fair in practice |
| Settlements | Peer-to-peer | Not a payment processor; generate requests to PayPal/UPI |

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| API Compute | $2,000 |
| PostgreSQL | $1,200 |
| Notifications (SES + Push) | $800 |
| Cache + Queue | $400 |
| **Total** | **$4,400** |
