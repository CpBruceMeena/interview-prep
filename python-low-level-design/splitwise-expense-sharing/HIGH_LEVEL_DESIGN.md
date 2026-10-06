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

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/splitwise-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Splitwise Sequence — Add → Split → Balance Update → Settlement. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Expense Service (Python/FastAPI)
- CRUD expenses with split calculation
- Strategy pattern: Equal, Exact, Percentage, Share
- Rounding: largest-remainder allocation in integer cents

**🔴 Interview Question:** *"How do you handle rounding errors in expense splits?"*

**✅ Answer:** Never use floats, and do the rounding in one place. Allocate in integer cents with the largest-remainder method:
```python
exact    = [Fraction(total_cents) * w / sum(weights) for w in weights]
floors   = [floor(x) for x in exact]
leftover = total_cents - sum(floors)            # always < len(weights)
for i in sorted(range(n), key=lambda i: (-(exact[i] - floors[i]), i))[:leftover]:
    floors[i] += 1
```
This guarantees `sum(shares) == total` and that nobody is more than one cent from their exact share. Pushing the whole difference onto one person (payer or first participant) looks simpler but can produce a negative share: $0.05 split 7 ways rounds every share up to 0.01 (0.07 total), and the −0.02 correction leaves one person owing −0.01. Store amounts as `NUMERIC(12,2)` (or `BIGINT` cents) so the database never reintroduces floats.

---

### Settlement Service (Python)
- Balance reads: O(members) from the materialised `balances` rows
- Debt simplification (greedy min-transactions, NP-hard optimal)
- Payment request creation

**🔴 Interview Question:** *"What algorithm do you use for debt simplification?"*

**✅ Answer:** The minimum is n − k, where n is the number of people with a non-zero balance and k is the largest number of disjoint zero-sum subgroups. Finding k is NP-hard, so:
1. Net balances come from the materialised balance rows (see Data Model).
2. **Greedy:** match the largest debtor with the largest creditor (two heaps), transfer the smaller amount, repeat. O(n log n), at most n − 1 transfers, but not optimal: `{-8, -7, -2, +9, +8}` takes 4 greedy transfers where 3 suffice.
3. **Exact** for small groups: bitmask DP over subsets, O(2ⁿ · n). Most groups have well under 15 active members, so 2ⁿ · n stays in the hundreds of thousands of steps; cap n and fall back to greedy above the cap.

Simplification can make someone pay a person they never shared an expense with, so offer it as an opt-in group setting.

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
    id UUID PRIMARY KEY, group_id UUID, description TEXT, amount DECIMAL(12,2),
    currency CHAR(3), paid_by UUID, split_type TEXT,
    request_id UUID UNIQUE,                 -- client idempotency key
    deleted_at TIMESTAMP, version INT,      -- edits = soft delete + new row
    created_at TIMESTAMP
);
CREATE TABLE expense_shares (
    expense_id UUID, user_id UUID, share_amount DECIMAL(12,2),
    PRIMARY KEY (expense_id, user_id)
);
-- Derived, updated in the same transaction as the expense insert:
-- UPDATE balances SET net = net + :delta WHERE group_id = ? AND user_id = ?
CREATE TABLE balances (
    group_id UUID, user_id UUID, currency CHAR(3), net DECIMAL(14,2),
    PRIMARY KEY (group_id, user_id, currency)
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
| Balance calc | Materialised `balances` rows, updated in the expense transaction | O(participants) per write, O(1) per read; a nightly job recomputes from `expense_shares` and alerts on drift |
| Rounding | Largest remainder in cents | Exact total, nobody more than 1 cent off, never negative |
| Edits | Soft delete + new row | Audit trail; the balance delta is "reverse old, apply new" in one transaction |
| Settlements | Peer-to-peer | Not a payment processor; generate requests to PayPal/UPI |

---

## 6. CONSISTENCY, IDEMPOTENCY & FAILURE MODES

| Concern | Choice |
|---------|--------|
| **Consistency** | Strong within a group: the expense insert, its share rows and the balance deltas commit in one Postgres transaction. Shard by `group_id` so that transaction never crosses shards. Notifications and cross-device sync are eventually consistent (outbox → queue). |
| **Concurrent writes** | Inserts do not conflict. Balance updates use `net = net + :delta`, which row-locks briefly; no read-modify-write in the app. Optimistic `version` checks guard edits to the same expense. |
| **Mobile retries** | Client generates `request_id` per create; `UNIQUE(request_id)` turns a retry into a no-op that returns the original expense. |
| **Lost notifications** | Transactional outbox: the event row is written in the expense transaction, a relay publishes it; consumers are idempotent on event id. |
| **Payment provider timeouts** | Settlement is `PENDING` until the provider confirms; retries reuse the same provider idempotency key; a reconciliation job closes the gap. |
| **Balance drift (bug or bad migration)** | Balances are derived data. Recompute from `expense_shares` + `settlements` per group and compare; the ledger is the source of truth. |
| **Non-group (friend-to-friend) expenses** | Model as an implicit two-person group so the same per-group transaction and sharding rule apply. |

**Capacity (from the numbers in §1):** 50M expenses/month ≈ 20 writes/s average, perhaps 200/s at peak (weekend evenings, month-end rent). Each expense is ~1 KB with ~4 share rows, so ~50 GB/year including indexes. A single well-sized Postgres primary with read replicas handles this comfortably; sharding by `group_id` is a growth plan, not a day-one need.

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| API Compute | $2,000 |
| PostgreSQL | $1,200 |
| Notifications (SES + Push) | $800 |
| Cache + Queue | $400 |
| **Total** | **$4,400** |
