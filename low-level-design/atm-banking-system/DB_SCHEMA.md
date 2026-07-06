# 🗄️ ATM Banking System — Database Schema & Relationships

> **Database:** PostgreSQL 16  
> **Purpose:** Core banking, ATM network, card management, transactions, cash inventory, fraud detection  
> **Tables:** 10 tables + 2 partitioned tables

---

## 📊 Entity Relationship Diagram (Textual)

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│  customers   │1───N│   accounts   │1───N│  transactions  │
└──────────────┘     └──────────────┘     └────────────────┘
       │                    │
       │                    │1
       │                    │
       │              ┌─────▼──────┐     ┌─────────────────┐
       │              │   cards    │     │  atm_machines   │
       │              └────────────┘     └────────┬────────┘
       │                                          │1
       │                                          │
       │                                     ┌────▼────────┐
       │                                     │  atm_cash_  │
       │                                     │  inventory  │
       │                                     └─────────────┘
       │
┌──────▼──────────┐     ┌──────────────────┐
│  audit_log      │     │  fraud_alerts    │
│  (partitioned)  │     └─────────────────-┘
└─────────────────┘

┌──────────────┐     ┌──────────────┐
│  daily_limits │     │  scheduled_  │
│  (per-account)│     │  payments    │
└──────────────┘     └──────────────┘
```

---

## 🏛️ Complete DDL

```sql
-- ============================================================
-- ATM / Banking System - Production Database Schema
-- Database: PostgreSQL 16
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------
-- 1. CUSTOMERS
-- -----------------------------------------------------------
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    date_of_birth DATE,
    address TEXT,
    govt_id_type VARCHAR(50),          -- 'PASSPORT', 'AADHAAR', 'SSN', 'DRIVERS_LICENSE'
    govt_id_number VARCHAR(100),
    kyc_status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (kyc_status IN ('PENDING', 'VERIFIED', 'REJECTED', 'EXPIRED')),
    kyc_verified_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_phone ON customers(phone);

-- -----------------------------------------------------------
-- 2. ACCOUNTS
-- -----------------------------------------------------------
CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id),
    account_number VARCHAR(20) UNIQUE NOT NULL,
    account_type VARCHAR(20) NOT NULL
        CHECK (account_type IN ('SAVINGS', 'CHECKING', 'CREDIT', 'LOAN', 'FIXED_DEPOSIT')),
    currency VARCHAR(3) DEFAULT 'INR',
    balance DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    available_balance DECIMAL(18,2) NOT NULL DEFAULT 0.00,  -- Balance minus holds
    credit_limit DECIMAL(18,2) DEFAULT 0.00,                -- For credit accounts
    interest_rate DECIMAL(5,4) DEFAULT 0.0000,              -- Annual interest rate
    status VARCHAR(20) DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED', 'DORMANT', 'SUSPENDED')),
    daily_withdrawal_limit DECIMAL(12,2) DEFAULT 50000.00,
    daily_transaction_limit INT DEFAULT 10,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    version INT DEFAULT 1,                                   -- Optimistic locking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT positive_balance CHECK (balance >= 0 OR account_type IN ('CREDIT', 'LOAN'))
);

CREATE INDEX idx_accounts_customer ON accounts(customer_id);
CREATE INDEX idx_accounts_number ON accounts(account_number);
CREATE INDEX idx_accounts_status ON accounts(status) WHERE status = 'ACTIVE';

-- -----------------------------------------------------------
-- 3. CARDS
-- -----------------------------------------------------------
CREATE TABLE cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id),
    account_id UUID NOT NULL REFERENCES accounts(id),
    card_number VARCHAR(19) UNIQUE NOT NULL,        -- Masked: ****-****-****-1234
    card_holder_name VARCHAR(255) NOT NULL,
    card_type VARCHAR(20) NOT NULL
        CHECK (card_type IN ('DEBIT', 'CREDIT', 'ATM', 'PREPAID')),
    network VARCHAR(20) NOT NULL                     -- 'VISA', 'MASTERCARD', 'RUPAY', 'AMEX'
        CHECK (network IN ('VISA', 'MASTERCARD', 'RUPAY', 'AMEX')),
    pin_hash VARCHAR(255) NOT NULL,                  -- Bcrypt hash of PIN
    pin_attempts INT DEFAULT 0,
    pin_blocked BOOLEAN DEFAULT false,
    cvv_hash VARCHAR(255) NOT NULL,
    expiry_date DATE NOT NULL,
    issued_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'BLOCKED', 'EXPIRED', 'LOST', 'STOLEN', 'CANCELLED')),
    daily_withdrawal_limit DECIMAL(12,2) DEFAULT 25000.00,
    daily_transaction_limit INT DEFAULT 5,
    is_contactless BOOLEAN DEFAULT true,
    is_international_enabled BOOLEAN DEFAULT false,
    version INT DEFAULT 1,                          -- Optimistic locking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cards_customer ON cards(customer_id);
CREATE INDEX idx_cards_account ON cards(account_id);
CREATE INDEX idx_cards_status ON cards(status);
CREATE INDEX idx_cards_expiry ON cards(expiry_date) WHERE status = 'ACTIVE';

-- -----------------------------------------------------------
-- 4. ATM MACHINES (defined before transactions which reference it)
-- -----------------------------------------------------------
CREATE TABLE atm_machines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_code VARCHAR(20) UNIQUE NOT NULL,
    location_name VARCHAR(255) NOT NULL,
    address TEXT NOT NULL,
    latitude DECIMAL(10,7),
    longitude DECIMAL(10,7),
    atm_type VARCHAR(20) DEFAULT 'ON_SITE'
        CHECK (atm_type IN ('ON_SITE', 'OFF_SITE', 'MOBILE', 'WHITE_LABEL')),
    status VARCHAR(20) DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'OUT_OF_SERVICE', 'MAINTENANCE', 'OFFLINE', 'RETIRED')),
    software_version VARCHAR(50),
    last_heartbeat TIMESTAMPTZ,
    last_maintenance TIMESTAMPTZ,
    total_cash_loaded DECIMAL(14,2) DEFAULT 0.00,
    total_cash_dispensed DECIMAL(14,2) DEFAULT 0.00,
    transaction_count_today INT DEFAULT 0,
    is_online BOOLEAN DEFAULT false,
    supported_transactions JSONB DEFAULT '["WITHDRAWAL", "BALANCE_ENQUIRY", "MINI_STATEMENT"]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_atm_status ON atm_machines(status) WHERE status IN ('ACTIVE', 'ONLINE');
CREATE INDEX idx_atm_location ON atm_machines(latitude, longitude);

-- -----------------------------------------------------------
-- 5. TRANSACTIONS (Core Ledger - Immutable, Partitioned by month)
-- -----------------------------------------------------------
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    card_id UUID REFERENCES cards(id),               -- NULL if digital/ATM cardless
    transaction_type VARCHAR(30) NOT NULL
        CHECK (transaction_type IN (
            'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'PAYMENT',
            'FEE', 'INTEREST', 'REFUND', 'REVERSAL',
            'ATM_WITHDRAWAL', 'ATM_DEPOSIT', 'POS_PURCHASE',
            'ONLINE_PURCHASE', 'BILL_PAYMENT', 'BALANCE_ENQUIRY',
            'MINI_STATEMENT', 'PIN_CHANGE'
        )),
    amount DECIMAL(18,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'INR',
    balance_before DECIMAL(18,2) NOT NULL,
    balance_after DECIMAL(18,2) NOT NULL,
    description TEXT,
    atm_id UUID REFERENCES atm_machines(id),         -- NULL if not ATM transaction
    reference_number VARCHAR(64) UNIQUE,              -- External reference
    idempotency_key VARCHAR(64) UNIQUE,               -- Idempotent processing
    status VARCHAR(20) DEFAULT 'COMPLETED'
        CHECK (status IN ('PENDING', 'AUTHORIZED', 'COMPLETED', 'FAILED', 'REVERSED', 'DECLINED')),
    failure_reason TEXT,
    reversal_of UUID REFERENCES transactions(id),     -- Link to reversed transaction
    reversal_by UUID REFERENCES transactions(id),     -- Link to reversal transaction
    metadata JSONB DEFAULT '{}',                      -- Flexible: ATM location, POS terminal, IP, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Monthly partitions for transactions
CREATE TABLE transactions_202401 PARTITION OF transactions
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE transactions_202402 PARTITION OF transactions
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE INDEX idx_tx_account ON transactions(account_id);
CREATE INDEX idx_tx_created ON transactions(created_at DESC);
CREATE INDEX idx_tx_type ON transactions(transaction_type);
CREATE INDEX idx_tx_card ON transactions(card_id) WHERE card_id IS NOT NULL;
CREATE INDEX idx_tx_atm ON transactions(atm_id) WHERE atm_id IS NOT NULL;
CREATE INDEX idx_tx_idempotency ON transactions(idempotency_key);
CREATE INDEX idx_tx_status ON transactions(status) WHERE status = 'PENDING';

-- -----------------------------------------------------------
-- 6. ATM CASH INVENTORY (Per-ATM denomination tracking)
-- -----------------------------------------------------------
CREATE TABLE atm_cash_inventory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    atm_id UUID NOT NULL REFERENCES atm_machines(id),
    denomination INT NOT NULL CHECK (denomination IN (10, 20, 50, 100, 200, 500, 2000)),
    count INT NOT NULL DEFAULT 0 CHECK (count >= 0),
    max_capacity INT NOT NULL,                         -- Max notes this cassette can hold
    min_threshold INT NOT NULL DEFAULT 50,             -- Alert when below this
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(atm_id, denomination)
);

CREATE INDEX idx_cash_inventory_atm ON atm_cash_inventory(atm_id);
CREATE INDEX idx_cash_inventory_low ON atm_cash_inventory(atm_id)
    WHERE count <= min_threshold;

-- -----------------------------------------------------------
-- 7. ATM SESSIONS (For audit of ATM usage)
-- -----------------------------------------------------------
CREATE TABLE atm_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    atm_id UUID NOT NULL REFERENCES atm_machines(id),
    card_id UUID REFERENCES cards(id),
    customer_id UUID REFERENCES customers(id),
    session_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_end TIMESTAMPTZ,
    transactions_conducted INT DEFAULT 0,
    total_amount_processed DECIMAL(14,2) DEFAULT 0.00,
    session_status VARCHAR(20) DEFAULT 'ACTIVE'
        CHECK (session_status IN ('ACTIVE', 'COMPLETED', 'TIMEOUT', 'FAILED', 'ABORTED')),
    ip_address INET,
    device_info JSONB                               -- Browser/App info for digital sessions
);

CREATE INDEX idx_sessions_atm ON atm_sessions(atm_id);
CREATE INDEX idx_sessions_customer ON atm_sessions(customer_id);
CREATE INDEX idx_sessions_start ON atm_sessions(session_start DESC);

-- -----------------------------------------------------------
-- 8. EMPLOYEES (defined before fraud_alerts which references it)
-- -----------------------------------------------------------
CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL
        CHECK (role IN ('TELLER', 'MANAGER', 'FRAUD_ANALYST', 'ADMIN', 'AUDITOR', 'MAINTENANCE')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 9. FRAUD ALERTS
-- -----------------------------------------------------------
CREATE TABLE fraud_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID REFERENCES transactions(id),
    card_id UUID REFERENCES cards(id),
    customer_id UUID REFERENCES customers(id),
    alert_type VARCHAR(50) NOT NULL
        CHECK (alert_type IN (
            'HIGH_AMOUNT', 'VELOCITY_CHECK', 'GEOGRAPHIC_ANOMALY',
            'UNUSUAL_HOURS', 'CARD_NOT_PRESENT', 'PIN_ATTEMPTS',
            'DUPLICATE_TRANSACTION', 'STRUCTURING', 'ACCOUNT_TAKEOVER'
        )),
    severity VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    score DECIMAL(5,2),                              -- Risk score 0.00 - 99.99
    rule_name VARCHAR(100),                           -- Which rule triggered
    description TEXT,
    metadata JSONB,                                   -- Transaction details at time of alert
    status VARCHAR(20) DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'INVESTIGATING', 'CONFIRMED', 'FALSE_POSITIVE', 'RESOLVED')),
    reviewed_by UUID REFERENCES employees(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fraud_transaction ON fraud_alerts(transaction_id);
CREATE INDEX idx_fraud_status ON fraud_alerts(status) WHERE status IN ('OPEN', 'INVESTIGATING');
CREATE INDEX idx_fraud_severity ON fraud_alerts(severity, created_at DESC);

-- -----------------------------------------------------------
-- 10. DAILY LIMITS (per-account per-day spending limits)
-- -----------------------------------------------------------
CREATE TABLE daily_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    limit_date DATE NOT NULL DEFAULT CURRENT_DATE,
    withdrawal_amount_today DECIMAL(14,2) DEFAULT 0.00,
    deposit_amount_today DECIMAL(14,2) DEFAULT 0.00,
    transaction_count_today INT DEFAULT 0,
    atm_withdrawal_count INT DEFAULT 0,
    version INT DEFAULT 1,
    UNIQUE(account_id, limit_date)
);

CREATE INDEX idx_daily_limits_account ON daily_limits(account_id, limit_date);

-- -----------------------------------------------------------
-- 11. AUDIT LOG (Partitioned by quarter - Immutable)
-- -----------------------------------------------------------
CREATE TABLE audit_log (
    id BIGSERIAL,
    entity_type VARCHAR(50) NOT NULL,              -- 'account', 'card', 'transaction', 'customer', 'atm'
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,                    -- 'CREATED', 'UPDATED', 'FROZEN', 'PIN_CHANGED', etc.
    old_values JSONB,
    new_values JSONB,
    source VARCHAR(50),                             -- 'ATM', 'MOBILE_APP', 'WEB', 'ADMIN', 'SYSTEM'
    ip_address INET,
    performed_by UUID,                              -- customer_id or employee_id
    correlation_id UUID,                            -- Link related events
    created_at TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE TABLE audit_log_2024_q1 PARTITION OF audit_log
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');
CREATE TABLE audit_log_2024_q2 PARTITION OF audit_log
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');

CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX idx_audit_correlation ON audit_log(correlation_id);

-- -----------------------------------------------------------
-- 12. SCHEDULED PAYMENTS (Future-dated / recurring)
-- -----------------------------------------------------------
CREATE TABLE scheduled_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    payee_name VARCHAR(255) NOT NULL,
    payee_account VARCHAR(50) NOT NULL,
    payee_ifsc VARCHAR(20),                             -- Indian Financial System Code
    amount DECIMAL(14,2) NOT NULL,
    frequency VARCHAR(20) DEFAULT 'ONE_TIME'
        CHECK (frequency IN ('ONE_TIME', 'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY')),
    next_execution DATE NOT NULL,
    end_date DATE,
    max_occurrences INT,
    occurrences_so_far INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED', 'FAILED')),
    last_execution TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scheduled_account ON scheduled_payments(account_id);
CREATE INDEX idx_scheduled_next ON scheduled_payments(next_execution)
    WHERE status = 'ACTIVE';

-- -----------------------------------------------------------
-- KEY QUERY EXAMPLES
-- -----------------------------------------------------------

-- 1. Get a customer's complete financial profile
SELECT c.full_name, c.email, c.kyc_status,
       a.account_number, a.account_type, a.balance, a.available_balance,
       crd.card_number, crd.card_type, crd.status AS card_status
FROM customers c
JOIN accounts a ON a.customer_id = c.id
LEFT JOIN cards crd ON crd.account_id = a.id AND crd.status = 'ACTIVE'
WHERE c.id = 'customer-uuid'
ORDER BY a.account_type;

-- 2. Find ATM with optimal cash for a withdrawal (denomination-aware)
SELECT atm.id, atm.location_name,
       inv.denomination, inv.count, inv.max_capacity,
       (inv.count * inv.denomination) AS cash_value
FROM atm_machines atm
JOIN atm_cash_inventory inv ON inv.atm_id = atm.id
WHERE atm.status = 'ACTIVE'
  AND atm.is_online = true
ORDER BY (inv.count * inv.denomination) DESC;

-- 3. Detect velocity fraud: more than 5 transactions in 10 minutes
SELECT tx.card_id, COUNT(*) AS tx_count,
       MIN(tx.created_at) AS first_tx, MAX(tx.created_at) AS last_tx
FROM transactions tx
WHERE tx.card_id IS NOT NULL
  AND tx.created_at >= NOW() - INTERVAL '10 minutes'
  AND tx.status = 'COMPLETED'
GROUP BY tx.card_id
HAVING COUNT(*) > 5;

-- 4. Calculate daily ATM utilization
SELECT atm_id, COUNT(*) AS session_count,
       SUM(transactions_conducted) AS total_tx,
       SUM(total_amount_processed) AS total_amount
FROM atm_sessions
WHERE session_start >= CURRENT_DATE
GROUP BY atm_id
ORDER BY total_amount DESC;

-- 5. Monthly account summary (for statements)
SELECT date_trunc('month', created_at) AS month,
       COUNT(*) AS transaction_count,
       SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS credits,
       SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS debits
FROM transactions
WHERE account_id = 'account-uuid'
  AND created_at >= CURRENT_DATE - INTERVAL '6 months'
GROUP BY date_trunc('month', created_at)
ORDER BY month DESC;
```

---

## 🔑 Redis Schema (Caching Layer)

```ascii
# Redis is used for: rate limiting, session state, hot account cache

session:{session_id}                       → HASH (atm_session_id, card_number, authenticated, account_ids)
rate_limit:atm:{atm_id}:minute             → STRING (counter, reset every minute)
rate_limit:customer:{customer_id}:hour     → STRING (counter, reset every hour)
rate_limit:account:{account_id}:day        → STRING (daily withdrawal total)
balance:{account_id}                       → STRING (cached balance, TTL 5s)
card:{card_id}:pin_attempts                → STRING (failed PIN attempts, TTL 24h)
atm:{atm_id}:cash                         → HASH (denomination → count, refreshed every transaction)
fraud:velocity:{card_id}:10m              → SET (transaction IDs in last 10 min)
```

---

## 📐 Table Relationships Summary

| # | Table | Parent FK | Child References | Key Indexes |
|---|-------|-----------|-----------------|-------------|
| 1 | `customers` | — | `accounts(customer_id)`, `cards(customer_id)`, `fraud_alerts(customer_id)`, `atm_sessions(customer_id)` | email, phone |
| 2 | `accounts` | `customer_id → customers` | `cards(account_id)`, `transactions(account_id)`, `daily_limits(account_id)`, `scheduled_payments(account_id)` | customer, number, active(partial) |
| 3 | `cards` | `customer_id → customers`, `account_id → accounts` | `transactions(card_id)`, `fraud_alerts(card_id)`, `atm_sessions(card_id)` | customer, account, status, expiry |
| 4 | `atm_machines` | — | `transactions(atm_id)`, `atm_cash_inventory(atm_id)`, `atm_sessions(atm_id)` | status, location |
| 5 | `transactions` | `account_id → accounts`, `card_id → cards`, `atm_id → atm_machines` | `fraud_alerts(transaction_id)` | account, created DESC, card, atm, idempotency |
| 6 | `atm_cash_inventory` | `atm_id → atm_machines` | — | (atm, denomination) UNIQUE, low-cash(filter) |
| 7 | `atm_sessions` | `atm_id → atm_machines`, `card_id → cards`, `customer_id → customers` | — | atm, customer, start DESC |
| 8 | `employees` | — | `fraud_alerts(reviewed_by)` | — |
| 9 | `fraud_alerts` | `transaction_id → transactions`, `card_id → cards`, `customer_id → customers`, `reviewed_by → employees` | — | transaction, open(filter), severity |
| 10 | `daily_limits` | `account_id → accounts` | — | (account, date) UNIQUE |
| 11 | `audit_log` | polymorphic | — | (entity, id), created DESC |
| 12 | `scheduled_payments` | `account_id → accounts` | — | account, next_execution(filter) |

---

## ⚡ Concurrency & Consistency Strategy

| Concern | Solution |
|---------|----------|
| **Balance accuracy** | Optimistic locking via `version` column. Read version, compute, write only if version unchanged. On conflict, retry. |
| **No double-withdrawal** | `idempotency_key` UNIQUE constraint prevents duplicate transaction processing. |
| **No double-dispense** | Two-phase protocol: `PENDING` → dispense → `COMPLETED`. If dispense fails after 30s timeout, auto-reversal. |
| **Hot account contention** | Redis cache + database. Write-through: update Redis → async write to DB. Read from Redis for balance checks. |
| **ATM session atomicity** | Each session state tracked in both Redis (fast) and PostgreSQL (durable). On failover, replay from DB. |
| **Geographic distribution** | Active-Active with CDC (Debezium + Kafka) for cross-region replication. Local reads, global consistency for balances. |
