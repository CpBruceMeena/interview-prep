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

**✅ Answer:** Make every step either retryable or reversible, and decide the default for each crash point.
1. **Plan:** the ATM checks it can make the amount from its cassettes before asking the bank.
2. **Authorize:** the request carries a unique id (ATM id + sequence / STAN). The issuer holds or debits the funds; a retried request with the same id returns the original response instead of debiting again.
3. **Dispense:** sensors confirm notes presented and taken.
4. **Complete or reverse:** on success the ATM confirms; on a clean failure it sends a **reversal** (ISO 8583 0420 advice), stored on disk and retried until acknowledged, so a reboot cannot lose it.
5. **Ambiguous outcome** (jam mid-dispense, power loss): neither confirm nor reverse blindly. Flag for reconciliation; cassette counters and the reject/purge bin settle it, usually the same day.

In ISO 8583 networks this is typically one financial request (0200) plus a reversal on failure rather than a separate auth/capture, but the guarantees are the same: retries are idempotent and reversals are delivered at least once.

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
1. **At PIN pad:** the encrypting PIN pad builds an ISO 9564 PIN block (format 0 or 4) and encrypts it with a symmetric key, typically DUKPT (unique key per transaction) or a terminal key loaded via remote key injection.
2. **In transit:** each hop (ATM switch, network, issuer) translates the PIN block from one zone key to the next **inside an HSM**; the clear PIN never exists in host memory. Messages also carry a MAC.
3. **At the issuer HSM:** the PIN is verified against a PIN offset (IBM 3624) or PVV (Visa). The database stores the offset/PVV, never the PIN or a plain hash of it (10,000 possible PINs makes any hash trivially reversible).
4. **Attempts:** a durable counter in the card record; block after 3 and instruct the ATM to retain the card. Unblocking requires a branch or a verified channel.

---

## 4. DATA MODEL

```sql
CREATE TABLE accounts (
    id UUID PRIMARY KEY, customer_id UUID, account_type TEXT,
    balance DECIMAL(15,2), held DECIMAL(15,2) DEFAULT 0,   -- available = balance - held (+ limits)
    status TEXT
);
CREATE TABLE cards (
    card_number TEXT PRIMARY KEY, customer_id UUID,
    account_id UUID, pin_offset TEXT, status TEXT,
    failed_attempts INT DEFAULT 0
);
CREATE TABLE transactions (
    id UUID PRIMARY KEY, account_id UUID, type TEXT,
    amount DECIMAL(15,2), balance_after DECIMAL(15,2), created_at TIMESTAMPTZ,
    atm_id TEXT, status TEXT,                          -- PENDING | COMPLETED | REVERSED
    request_id TEXT UNIQUE                             -- ATM id + sequence: retries hit this
);
-- withdrawal = one transaction:
--   INSERT transaction (request_id)   -- conflict -> return stored result
--   UPDATE accounts SET held = held + :amt
--     WHERE id = :id AND balance - held - :floor >= :amt   -- 0 rows -> decline
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Protocol | ISO 8583 | Industry standard for ATM networks |
| PIN security | HSM + encrypted PIN block | PCI DSS compliance, never plaintext |
| Cash mgmt | Per-ATM inventory | Track denominations for optimal dispensing |
| Transaction | Authorize → dispense → confirm/reverse, idempotent by request id | Not a distributed 2PC: the ATM cannot "prepare" a dispense, so failures are compensated with reversals |
| Balance updates | Conditional `UPDATE ... WHERE available >= amt` | No read-modify-write; no optimistic-retry storms on hot accounts |
| Consistency | Strong, single writer per account | Balances are never served from a cache for authorization |

---

## 6. FAILURE MODES & CAPACITY

| Failure | Behaviour |
|---------|-----------|
| Response to ATM lost | ATM retries with the same request id; issuer returns the original result |
| ATM reboots after dispensing, before confirming | Journal on local disk records the dispense; confirmation is replayed on boot |
| Reversal cannot reach the bank | Stored and forwarded until acknowledged; the hold stays until then |
| Issuer down | Switch can run stand-in authorization with conservative limits and queue advices; or decline. A business risk decision |
| Hot account (payroll, merchant) | Row lock held only for the conditional update; no cache in the write path |
| Cash/ledger mismatch | End-of-day reconciliation per ATM: cassette counts vs completed withdrawals |

**Capacity:** 50K transactions/hour at peak is ~14 TPS, small for a single relational primary per region; the hard requirements are latency (< 2 s end to end, dominated by network and HSM hops) and availability (99.999% means about 5 minutes of downtime per year, so active/passive failover with synchronous replication for the ledger). Ledger growth is ~1M rows/day at peak rates, about 0.5 KB each, so ~200 GB/year before indexes; partition by month and archive.

---

## 7. COST (Monthly)

| Component | Cost (10K ATMs) |
|-----------|----------------|
| ATM Controller per ATM | $500/ATM (amortized hardware) |
| ATM Switch + Gateway | $15,000 |
| Core Banking DB | $10,000 |
| HSM (per region) | $5,000 |
| **Total** | **$35,000** (excluding ATM hardware) |
