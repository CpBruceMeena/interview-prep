# 🏗️ Payment Processing System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Financial transactions, idempotency, fraud detection, PCI compliance

---

## 1. SYSTEM OVERVIEW

**Purpose:** Payment processing platform handling merchant payments, customer charges, refunds, and settlements with high reliability and security.

**Scale:** 1M transactions/day peak, 10K merchants, 100K customers, $50M monthly volume

**Users:** Customers (payers), Merchants (payees), Platform admins, Fraud analysts

**Use Cases:** Charge payment, Process refund, Merchant settlement, Fraud detection, Dispute management

**Constraints:** <1s transaction latency, 99.999% uptime, PCI DSS Level 1, 100% idempotency, no double-charge

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌──────────────┐     ┌──────────────┐
│ Customer App │     │ Merchant     │
│              │     │ Dashboard    │
└──────┬───────┘     └──────┬───────┘
       │                    │
┌──────▼────────────────────▼───────┐
│           API Gateway              │
│  - Rate limiting per merchant      │
│  - Idempotency key validation      │
│  - TLS 1.3 termination             │
└──────┬────────────────────────────┘
       │
┌──────▼────────────────────────────┐
│     Payment Service (Python/Go)    │
│  - Validation pipeline (COR)       │
│  - Fraud checks (multi-stage)      │
│  - Gateway routing                 │
│  - Idempotency (unique key in DB)  │
└──────┬────────────────────────────┘
       │
┌──────▼────────┐   ┌───────────────┐
│ Stripe        │   │ PayPal        │
│ Gateway       │   │ Gateway       │
└───────────────┘   └───────────────┘
       │                    │
┌──────┴────────────────────┴──────────┐
│        PostgreSQL + Redis             │
│  - Transactions, Refunds, Payouts    │
│  - Idempotency keys, outbox table    │
│  - Settlement batches                │
└──────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/payment-processing-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Payment Processing Sequence — Validate → Fraud Check → Gateway → Complete → Refund. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Payment Service (Python/Go)
- Validation pipeline: amount → currency → payment method → fraud checks
- Gateway routing by currency/amount/region
- Idempotency — the most critical feature

**🔴 Interview Question:** *"How do you guarantee idempotency in payment processing?"*

**✅ Answer:** Every payment request carries an `Idempotency-Key` header (a UUID the client generates once per logical payment). The key is claimed in Postgres, in the same row as the payment, *before* the gateway is called:
```python
def pay(merchant_id, key, request):
    row = db.execute("""
        INSERT INTO payments (id, merchant_id, idempotency_key, request_hash, status, ...)
        VALUES (:id, :m, :k, :h, 'PROCESSING', ...)
        ON CONFLICT (merchant_id, idempotency_key) DO NOTHING
        RETURNING id""")
    if row is None:                                   # someone already claimed this key
        existing = db.fetch_payment(merchant_id, key)
        if existing.request_hash != hash(request): raise Conflict(422)
        if existing.status == "PROCESSING":        raise InProgress(409)
        return existing.stored_response               # same answer as the first time

    result = gateway.charge(..., idempotency_key=key)  # key forwarded: provider dedupes too
    db.update_status_and_insert_outbox(row.id, result) # one transaction
    return result
```
Why not "check Redis, charge, then `SETEX`": two concurrent requests both miss the cache and both charge (check-then-act), and a crash between the charge and the `SETEX` loses the result. Redis can still front this as a cache of *completed* responses, but the unique constraint is the source of truth. Forwarding the key to the gateway covers the case our own table cannot: our request timed out after the provider had already charged the card.

---

### Fraud Detection (Chain of Responsibility)
- Amount threshold check
- Velocity check (too many transactions in short time)
- Geolocation/IP anomaly detection
- ML model scoring (real-time, <50ms)

**🔴 Interview Question:** *"How do you balance fraud prevention with minimizing false positives?"*

**✅ Answer:** Layered approach with configurable thresholds:
1. **Rules engine:** Hard blocks (amount > $10K, >10 transactions/minute). Low false positives.
2. **ML model:** Trained on historical chargebacks. Scores 0-100. Threshold tuned for 95% recall.
3. **Manual review:** Transactions scoring 80-95 flagged for manual review (1 hour SLA).
4. **A/B testing:** New rules deployed to 10% of traffic first, monitor false positive rate.
5. **Feedback loop:** Confirmed fraud → retrain model. False positive → adjust threshold.

Target: Catch 95% of fraud with <1% false positive rate.

---

### Settlement Engine
- Daily batch settlement calculation
- Payout to merchants (T+1, T+3, weekly)
- Reconciliation against bank statements

**🔴 Interview Question:** *"How does daily merchant settlement work?"*

**✅ Answer:**
```python
def daily_settlement(merchant_id, date):
    # Calculate
    gross = sum(charges for merchant on date)
    fees = sum(charge.fee for charges on date)          # per-charge fee, rounded per charge
    refunds = sum(refunds processed on date)
    net = gross - fees - refunds - chargebacks          # Decimal throughout; from the ledger
    
    # Generate ACH/NEFT file
    bank_file = generate_ach(merchant.bank_account, net)
    
    # Upload to bank
    bank_connector.upload(bank_file)
    
    # Record for reconciliation
    Settlement.create(merchant_id, date, gross, fees, net)
```

---

## 4. DATA MODEL

```sql
CREATE TABLE payments (
    id UUID PRIMARY KEY, merchant_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    amount NUMERIC(19,4) NOT NULL CHECK (amount > 0), currency CHAR(3) NOT NULL,
    status TEXT NOT NULL, gateway_tx_id TEXT, failure_reason TEXT,
    created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ,
    UNIQUE (merchant_id, idempotency_key)        -- the idempotency guarantee
);
CREATE TABLE refunds (
    id UUID PRIMARY KEY, payment_id UUID NOT NULL REFERENCES payments,
    idempotency_key TEXT NOT NULL, amount NUMERIC(19,4) NOT NULL CHECK (amount > 0),
    reason TEXT, status TEXT NOT NULL,          -- PENDING rows count against refundable
    created_at TIMESTAMPTZ,
    UNIQUE (payment_id, idempotency_key)
);
CREATE TABLE outbox (                             -- written in the same txn as the status change
    id BIGSERIAL PRIMARY KEY, aggregate_id UUID, type TEXT, payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now(), published_at TIMESTAMPTZ
);
CREATE TABLE settlements (
    id UUID, merchant_id UUID, period_start DATE,
    period_end DATE, gross DECIMAL(12,2), fees DECIMAL(12,2),
    net DECIMAL(12,2), status TEXT
);
CREATE TABLE fraud_checks (
    id UUID, payment_id UUID, check_type TEXT,
    passed BOOLEAN, reason TEXT, score DECIMAL(5,2)
);
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Idempotency | Client-generated key | Simplest, no coordination needed |
| Gateway routing | By currency / region / cost | Local acquiring avoids cross-border fees and usually raises approval rates |
| Settlement | T+1 batch | Balances cash flow with operational cost |
| Storage | Postgres as source of truth; Redis only as a cache | Idempotency, status and outbox must commit atomically, which needs one ACID store |

---

## 6. CONSISTENCY & FAILURE MODES

**Capacity check.** 1M transactions/day ≈ 12 TPS average, maybe 100–200 TPS at peak. A single Postgres primary handles this; the latency budget is dominated by the gateway round trip (hundreds of ms), not our DB. Scale concerns are availability and correctness, not throughput.

| Failure | Handling |
|---------|----------|
| Client times out and retries | Same key → stored result, or 409 while still PROCESSING |
| Gateway times out after charging | Retries reuse the key, so the provider returns the original charge. After the retry budget: status UNKNOWN, never FAILED |
| Service crashes between gateway response and DB commit | Row stays PROCESSING. Reconciler picks up PROCESSING/UNKNOWN rows older than N minutes and re-sends with the same key (or queries the provider / waits for the webhook) |
| Gateway outage | Circuit breaker opens; fail over to a second provider only for requests that never reached the first (no shared idempotency keys across providers) |
| Duplicate / out-of-order webhooks | Dedupe on provider event id; apply through the state transition table, so stale events cannot move a payment backwards |
| Kafka down | Outbox rows accumulate; relay catches up later. Consumers dedupe on event id (at-least-once) |
| Two concurrent refunds | `SELECT ... FOR UPDATE` on the payment, check refundable including PENDING refunds, insert PENDING, commit, then call the gateway |
| Ledger vs provider mismatch | Daily three-way reconciliation (ledger, provider settlement file, bank statement); mismatches go to an exception queue |

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| Payment Services (auto-scaled) | $3,000 |
| PostgreSQL (Multi-AZ) | $2,500 |
| Redis (response cache, rate limits) | $500 |
| Payment gateway fees (2.5%) | $125,000 (on $50M volume) |
| **Total** | **$131,000** (gateway fees dominate) |
