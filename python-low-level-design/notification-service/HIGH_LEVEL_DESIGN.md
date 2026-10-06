# 🔔 Notification Service — High-Level Design

> **Target:** Principal Engineer | **Focus:** High-throughput, cost-effective notification system with second-level precision

---

## 1. SYSTEM OVERVIEW

```
User submits notification request
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│                    API GATEWAY                               │
│  - Rate limiting (10K req/s per client)                     │
│  - Auth (API Key / JWT)                                     │
│  - Request validation                                        │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│                    NOTIFICATION ORCHESTRATOR                 │
│                                                              │
│  1. Validate & enrich request                                │
│  2. Store notification (pending)                             │
│  3. Enqueue to channel                                       │
│  4. Return confirmation                                      │
└──────┬──────────────────────┬──────────────────┬───────────┘
       │                      │                  │
       ▼                      ▼                  ▼
┌──────────────┐    ┌──────────────────┐  ┌──────────────┐
│  Channel     │    │  Channel Router  │  │  Schedule    │
│  Validator   │    │  (Email/SMS/Push)│  │  Manager     │
└──────┬───────┘    └────────┬─────────┘  └──────┬───────┘
       │                     │                    │
       ▼                     ▼                    ▼
┌────────────────────────────────────────────────────────────┐
│                    DISPATCH SERVICE                           │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Email    │ │ SMS      │ │ Push     │ │ Webhook      │  │
│  │ Worker   │ │ Worker   │ │ Worker   │ │ Worker       │  │
│  │ Pool(10) │ │ Pool(5)  │ │ Pool(10) │ │ Pool(3)      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/notification-service-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Notification Service Sequence — Submit → Queue → Workers → Channel Delivery → Status. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. API DESIGN

### 3.1 REST API

```http
POST /api/v1/notifications
Content-Type: application/json
Authorization: Bearer <api_key>

{
    "template_id": "welcome_email",
    "recipients": [
        {"email": "user@example.com", "user_id": "123"},
        {"phone": "+1234567890"}
    ],
    "channels": ["email", "sms"],
    "schedule": {
        "send_at": "2026-07-07T14:00:00Z",   // Optional: schedule for later
        "timezone": "America/New_York"
    },
    "priority": "high",
    "metadata": {
        "user_name": "John",
        "activation_link": "https://..."
    },
    "idempotency_key": "unique_key_123"
}

Response:
{
    "notification_id": "notif_a1b2c3d4",
    "status": "queued",
    "estimated_delivery": "2026-07-07T14:00:00Z",
    "recipient_count": 2,
    "channel_breakdown": {
        "email": {"queued": 1},
        "sms": {"queued": 1}
    }
}
```

### 3.2 API Schema

```sql
-- Postgres. On a partitioned table every PRIMARY KEY / UNIQUE constraint must include
-- the partition key, so idempotency keys live in their own small, unpartitioned table.
CREATE TABLE idempotency_keys (
    api_key_id        VARCHAR(64)  NOT NULL,
    idempotency_key   VARCHAR(128) NOT NULL,
    notification_id   UUID         NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),   -- purge after 24h
    PRIMARY KEY (api_key_id, idempotency_key)
);

CREATE TABLE notifications (
    notification_id   UUID NOT NULL DEFAULT gen_random_uuid(),
    api_key_id        VARCHAR(64) NOT NULL,
    user_id           VARCHAR(64) NOT NULL,
    template_id       VARCHAR(128) NOT NULL,
    params            JSONB NOT NULL DEFAULT '{}',
    priority          SMALLINT NOT NULL DEFAULT 2,          -- 0 critical .. 3 low
    category          VARCHAR(16) NOT NULL,                 -- transactional | marketing
    send_at           TIMESTAMPTZ,                          -- NULL = now
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (notification_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE deliveries (
    delivery_id         UUID NOT NULL DEFAULT gen_random_uuid(),
    notification_id     UUID NOT NULL,
    channel             VARCHAR(16) NOT NULL,               -- email | sms | push
    address             VARCHAR(256) NOT NULL,
    status              VARCHAR(16) NOT NULL DEFAULT 'queued',
    attempts            SMALLINT NOT NULL DEFAULT 0,
    ready_at            TIMESTAMPTZ NOT NULL,               -- next eligible send time
    provider_message_id VARCHAR(256),                       -- maps provider callbacks back
    last_error          TEXT,
    sent_at             TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (delivery_id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ON deliveries (status, ready_at);               -- scheduler / retry poller
CREATE INDEX ON deliveries (provider_message_id);           -- receipt lookups
CREATE INDEX ON deliveries (notification_id);

CREATE TABLE user_preferences (
    user_id              VARCHAR(64) PRIMARY KEY,
    contacts             JSONB NOT NULL,                    -- {"email": ..., "sms": ...}
    opted_out_channels   TEXT[] NOT NULL DEFAULT '{}',
    opted_out_categories TEXT[] NOT NULL DEFAULT '{}',
    quiet_start          TIME, quiet_end TIME,
    timezone             TEXT NOT NULL DEFAULT 'UTC'        -- IANA name, not an offset
);
```

---

## 4. IMPLEMENTATION

### 4.1 Components

The in-process version of every component below is in [CODE.md](CODE.md); this section is about how they map onto a fleet.

| Component | Responsibility | Production shape |
|-----------|----------------|------------------|
| API / orchestrator | Validate, claim idempotency key, load preferences, render templates, fan out to deliveries, apply opt-outs | Stateless service; one DB transaction writes the notification, deliveries and an outbox row per ready delivery |
| Channel queues | Decouple API from providers; isolate channels and priorities | Kafka topic or SQS queue per (channel, priority band). OTPs never share a queue with campaigns |
| Workers | Quiet hours, rate limits, send, classify errors, retry/DLQ | Consumer group per channel, sized from provider limits, not CPU |
| Rate limiter | Per user+channel, per provider, per tenant buckets | Redis token buckets updated by one Lua script per check (atomic refill + take) |
| Scheduler / retry poller | Re-enqueue deliveries whose `ready_at` has passed (scheduled sends, backoff, deferrals) | `SELECT ... WHERE status='queued' AND ready_at <= now() FOR UPDATE SKIP LOCKED LIMIT 500`, or a Redis sorted set (4.4) |
| Receipt ingester | Provider callbacks → DELIVERED / BOUNCED; invalidate dead contacts | Webhook endpoint, dedupe on provider event id, ignore out-of-order regressions |
| DLQ + replay | Inspect and re-drive failures after a fix | Separate queue/table; replay tool reuses the original delivery id |

### 4.2 Provider notes that change the design

- **Email (SES):** `SendBulkTemplatedEmail` takes up to 50 destinations per call, so batching cuts API calls ~50×, not 100×. Sending rate and daily quota are per account and region (new production accounts commonly start around 14 messages/s and are raised on request). Hard bounces and complaints arrive via SNS; ignoring them gets the account paused. `boto3` is synchronous, so in an asyncio worker run it in a thread pool or use an async client.
- **SMS:** price varies by destination country by more than 10×; sender IDs and templates must be pre-registered in some countries (e.g. DLT in India). Throughput is per sending number / sender ID. SMS pumping fraud makes per-user and per-country limits mandatory.
- **Push (FCM/APNs):** free, high throughput, but tokens rotate; an `UNREGISTERED` / `410 Gone` response means delete the token, not retry. FCM gives no delivery receipt.

### 4.3 Scheduling Engine (Second-Level Precision)

```python
class ScheduleManager:
    """
    Handles scheduled notifications with second-level precision.
    Uses Redis sorted sets for efficient scheduling.
    """
    
    def __init__(self, redis_client, orchestrator):
        self.redis = redis_client
        self.orchestrator = orchestrator
        self.scheduler_key = "notifications:scheduled"
    
    async def schedule(self, notification_id: str, send_at: datetime):
        """Schedule a notification for future delivery."""
        timestamp = send_at.timestamp()
        await self.redis.zadd(
            self.scheduler_key,
            {notification_id: timestamp}
        )
    
    async def process_due(self):
        """
        Process all notifications due for sending.
        Called by the scheduler loop below every second (cron cannot run sub-minute).
        """
        now = time.time()
        
        # Get all notifications scheduled up to now
        due = await self.redis.zrangebyscore(
            self.scheduler_key, 0, now
        )
        
        for notification_id in due:
            # Remove from scheduler
            removed = await self.redis.zrem(
                self.scheduler_key, notification_id
            )
            
            if removed:
                # Load and submit notification
                request = await self._load_notification(notification_id)
                if request:
                    await self.orchestrator.submit(request)

# Scheduler loop (runs every second)
async def scheduler_loop(schedule_manager: ScheduleManager):
    """Run every second to check for due notifications."""
    while True:
        try:
            await schedule_manager.process_due()
        except Exception as e:
            print(f"Scheduler error: {e}")
        await asyncio.sleep(1)
```

Correctness notes on this sketch:

- **Checking `ZREM`'s return value** is what makes multiple pollers safe: only the one that removed the member processes it. A Lua script doing `ZRANGEBYSCORE ... LIMIT` + `ZREM` atomically is the batched equivalent.
- **Remove-then-process loses work on a crash** between the two steps. Either keep the DB row as the source of truth (status `scheduled`, `ready_at`) and have the poller re-scan rows whose Redis entry vanished, or move due members into a "processing" set with a lease and delete them only after enqueueing.
- **Don't re-run the due notification through `submit()`** with its original idempotency key: the key is already recorded, so it would be treated as a duplicate and never sent (the earlier version of the LLD code had exactly this bug). Enqueue the already-created deliveries instead.

---

## 5. SCALING & PERFORMANCE

### 5.1 Throughput Targets

| Component | Target | Strategy |
|-----------|--------|----------|
| API ingestion | 10,000 req/s | Horizontal scaling + idempotency |
| Email delivery | 500/sec | Batching (100/batch) + SES bulk API |
| SMS delivery | 50/sec | Rate-limited per provider limits |
| Push delivery | 1,000/sec | Firebase Cloud Messaging batch |
| Webhook delivery | 500/sec | Connection pooling + keep-alive |

### 5.2 Batching Strategy

```python
class BatchOptimizer:
    """
    Optimizes batching to minimize API calls and costs.
    """
    
    async def optimize_email_batch(self, messages: List) -> List[List]:
        """Group emails by provider and optimize batch size."""
        # SES: max 50 recipients per bulk call
        # SendGrid: max 1000 recipients per call
        # Group by domain for better deliverability
        
        batches = []
        current_batch = []
        
        for msg in sorted(messages, key=lambda m: self._domain(m['recipient'])):
            current_batch.append(msg)
            
            if len(current_batch) >= 50:
                batches.append(current_batch)
                current_batch = []
        
        if current_batch:
            batches.append(current_batch)
        
        return batches  # 1M emails = 20,000 API calls instead of 1,000,000
```

---

## 6. RELIABILITY & FAILURE MODES

**Delivery guarantee:** at-least-once from submit to provider acceptance; duplicates suppressed by idempotency key, content dedup window and worker claims, with a small residual window when a provider accepted a message but its ack was lost.

| Failure | Handling |
|---------|----------|
| Client retries the API call | Idempotency key (unique per API key) returns the original notification id |
| Upstream fires the same event twice with different keys | Content dedup window on (user, template, params) |
| API commits to DB but crashes before enqueueing | Outbox row in the same transaction; a relay enqueues it. No "saved but never sent" |
| Worker dies mid-send | Queue visibility timeout / lease expires; another worker retries. May duplicate if the provider already accepted |
| Provider 5xx / throttling | Backoff with full jitter, honour `Retry-After`; circuit breaker opens and traffic fails over to the secondary provider |
| Provider permanent error | No retry; mark contact invalid (hard bounce, unregistered token) so future sends are suppressed |
| Retries exhausted | DLQ with last error; alert on growth; replay tool |
| Message too old to matter (OTP after 10 min) | Per-template TTL; expired deliveries are dropped, not sent late |
| Redis (rate limiter) unavailable | Fail open for CRITICAL with a conservative local in-process limit; fail closed (defer) for marketing |
| Campaign spike at 9:00 local time | Producer-side pacing per timezone; campaigns use LOW queues with capped consumer share |

**Capacity:** 1M notifications/day ≈ 12/s average, ~120/s at a 10× peak, i.e. a few hundred DB writes per second including deliveries and status updates. One Postgres primary with daily/monthly partitions (dropping old partitions instead of `DELETE`) is enough; deliveries at ~1 KB/row are ~1 GB/day per million.

---

## 7. MONITORING & ALERTS

```python
# Key metrics
NOTIFICATION_METRICS = {
    "notification_throughput": "Notifications processed per second",
    "delivery_latency_p50": "Median delivery latency (target: <5s)",
    "delivery_latency_p99": "P99 delivery latency (target: <30s)",
    "delivery_success_rate": "Fraction successfully delivered",
    "bounce_rate": "Email bounce rate (target: <2%)",
    "provider_failover_count": "How often providers fail over",
    "cost_per_notification": "Total cost / notifications sent",
}

# Alert thresholds
ALERTS = {
    "high_bounce_rate": {"metric": "bounce_rate", "threshold": 0.05, "action": "Pause sending, check list quality"},
    "high_latency": {"metric": "delivery_latency_p99", "threshold": 60, "action": "Scale workers"},
    "high_failure": {"metric": "delivery_success_rate", "threshold": 0.95, "action": "Failover providers"},
    "provider_down": {"metric": "provider_failover_count", "threshold": 3, "action": "Page on-call"},
    "cost_spike": {"metric": "cost_per_notification", "threshold": 0.01, "action": "Review pricing tier"},
}
```

---

> **Next:** [Notification Service API & Code](CODE.md) → Implementation details
