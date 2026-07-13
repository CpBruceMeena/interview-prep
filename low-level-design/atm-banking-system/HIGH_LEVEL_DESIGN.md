# 🏗️ ATM / Banking System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Financial transactions, security, state machines, cash management

---

## 1. SYSTEM OVERVIEW

**Purpose:** ATM network providing cash withdrawal, deposit, balance inquiry, and fund transfers with high security and reliability.

**Scale:** 10K ATMs, 1M accounts, 50K transactions/hour peak, 99.999% uptime

**Users:** Bank customers, ATM maintenance staff, Bank operations, Fraud investigation team

**Use Cases:** Cash withdrawal, Balance inquiry, PIN change, Fund transfer, Mini statement, Cash/check deposit

**Constraints:** <2s transaction time, PCI DSS compliance, no double-dispense, offline fallback for cash withdrawals

---

## 2. HIGH-LEVEL ARCHITECTURE

```
ATM Terminal (C/C++ on embedded Linux)
  - Card reader, PIN pad, Dispenser, Receipt printer
      │
      │ TCP/SSL (ISO 8583 / HTTPS)
      │
┌─────▼─────────────────────┐
│     ATM Switch / Gateway   │
│  (Kong / Custom)           │
│  - Route to core banking   │
│  - Protocol translation    │
└─────┬─────────────────────┘
      │
┌─────▼────────────────────────────────┐
│     ATM Controller Service (Go)      │
│  - State machine per ATM session     │
│  - Cash management                   │
│  - Transaction logging               │
└─────┬────────────────────────────────┘
      │
┌─────▼──────────┐    ┌───────────────┐
│ Core Banking   │    │ HSM           │
│ System         │    │ (Hardware     │
│ (Mainframe/    │    │  Security     │
│  PostgreSQL)   │    │  Module)      │
└────────────────┘    │ - PIN verify  │
                      │ - Key mgmt    │
                      └───────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/atm-banking-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated ATM Banking Sequence — Insert Card → PIN → Select → Withdraw → Cash + Receipt. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### ATM Controller (Go)
- Session state machine: Idle → CardInserted → PinEntered → Ready → TransactionComplete
- Cash dispenser management (denomination optimization)
- Transaction logging (immutable audit trail)

**🔴 Interview Question:** *"How do you ensure a withdrawal is never double-dispensed?"*

**✅ Answer:** Atomic two-phase protocol:
1. **Pre-dispense:** ATM requests authorization from core banking. Funds are held (not yet deducted).
2. **Dispense:** Cash dispenser physically dispenses notes. Sensors confirm cash taken.
3. **Confirm:** Only after dispense confirmation is the transaction committed to the database.
4. **If dispense fails:** Funds release automatically within 30 seconds. Customer gets receipt showing "transaction failed."

---

### ATM Switch (Gateway)
- ISO 8583 protocol translation
- Route to appropriate core banking system
- Fraud detection (velocity, amount thresholds)

### Hardware Security Module (HSM)
- PIN encryption/decryption (never plaintext outside HSM)
- Key management and rotation
- MAC generation for message integrity

**🔴 Interview Question:** *"How is PIN security handled end-to-end?"*

**✅ Answer:**
1. **At PIN pad:** PIN entered, immediately encrypted with HSM public key
2. **In transit:** Encrypted PIN block (ISO 9564 format 1) over TLS 1.3
3. **At HSM:** Decrypts PIN, verifies against stored PIN offset (not the raw PIN)
4. **Never in plaintext:** PIN is never visible to application code at any point
5. **3-attempt lockout:** After 3 failed PINs, card blocked. Requires bank branch intervention to unblock.

---

## 4. DATA MODEL

```sql
CREATE TABLE accounts (
    id UUID, customer_id UUID, account_type TEXT,
    balance DECIMAL(15,2), status TEXT, version INT
);
CREATE TABLE cards (
    card_number TEXT PRIMARY KEY, customer_id UUID,
    account_id UUID, pin_offset TEXT, status TEXT,
    failed_attempts INT DEFAULT 0
);
CREATE TABLE transactions (
    id UUID, account_id UUID, type TEXT,
    amount DECIMAL(15,2), balance_before DECIMAL(15,2),
    balance_after DECIMAL(15,2), timestamp TIMESTAMP,
    atm_id TEXT, status TEXT
);
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Protocol | ISO 8583 | Industry standard for ATM networks |
| PIN security | HSM + encrypted PIN block | PCI DSS compliance, never plaintext |
| Cash mgmt | Per-ATM inventory | Track denominations for optimal dispensing |
| Transaction | Two-phase commit | Prevent double-dispense |

---

## 6. COST (Monthly)

| Component | Cost (10K ATMs) |
|-----------|----------------|
| ATM Controller per ATM | $500/ATM (amortized hardware) |
| ATM Switch + Gateway | $15,000 |
| Core Banking DB | $10,000 |
| HSM (per region) | $5,000 |
| **Total** | **$35,000** (excluding ATM hardware) |
