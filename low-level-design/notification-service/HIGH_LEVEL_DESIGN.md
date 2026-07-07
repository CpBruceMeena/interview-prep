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

---

## 2. COST-EFFICIENT ARCHITECTURE

### 2.1 Why This Design is Cost-Effective

| Component | Strategy | Cost Impact |
|-----------|----------|-------------|
| **PostgreSQL** | Single instance, partitioned tables | ~$50/month |
| **Redis** | Small instance for queues only | ~$20/month |
| **Worker pools** | Dynamic scaling, max 10 concurrent | Pay-per-use |
| **Batching** | Batch emails (up to 1000 per API call) | 10-100x cheaper |
| **Retry** | Exponential backoff, limit 3 retries | Avoids wasted calls |
| **Deduplication** | In-memory + DB (prevents double-send) | Reduces waste |

### 2.2 Monthly Cost Estimate (1M notifications)

| Item | Cost |
|------|------|
| PostgreSQL (db.t4g.small) | $25 |
| Redis (cache.t3.micro) | $18 |
| EC2 for API + workers (t4g.medium × 2) | $50 |
| SES (100K emails) | $10 |
| SNS (10K SMS) | $20 |
| SQS | $5 |
| **Total** | **~$128/month** |

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
-- Notifications table
CREATE TABLE notifications (
    notification_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id        VARCHAR(64) NOT NULL,
    template_id       VARCHAR(128),
    recipient_count   INTEGER NOT NULL,
    channels          JSONB NOT NULL,         -- ["email", "sms", "push"]
    priority          VARCHAR(16) DEFAULT 'normal',
    status            VARCHAR(16) DEFAULT 'pending',
    schedule_at       TIMESTAMPTZ,             -- NULL = send immediately
    metadata          JSONB DEFAULT '{}',
    idempotency_key   VARCHAR(128) UNIQUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    
    INDEX idx_notif_status (status, created_at),
    INDEX idx_notif_schedule (schedule_at) WHERE schedule_at IS NOT NULL
) PARTITION BY RANGE (created_at);

-- Individual messages
CREATE TABLE notification_messages (
    message_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id   UUID NOT NULL REFERENCES notifications(notification_id),
    channel           VARCHAR(16) NOT NULL,    -- email, sms, push, webhook
    recipient         VARCHAR(256) NOT NULL,   -- email address or phone
    content           TEXT NOT NULL,
    status            VARCHAR(16) DEFAULT 'pending',
    -- Email specific
    email_provider_id VARCHAR(256),            -- SES message ID
    -- SMS specific
    sms_provider_id   VARCHAR(256),            -- SNS message ID
    -- Delivery tracking
    delivery_attempts INTEGER DEFAULT 0,
    last_error        TEXT,
    sent_at           TIMESTAMPTZ,
    delivered_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    
    INDEX idx_msg_notif (notification_id),
    INDEX idx_msg_status (status, channel, created_at)
) PARTITION BY RANGE (created_at);
```

---

## 4. IMPLEMENTATION

### 4.1 Core Components

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
import uuid
import json
import asyncio

class NotificationChannel(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"

class NotificationPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

class MessageStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"

@dataclass
class NotificationRequest:
    """Incoming notification request."""
    notification_id: str
    template_id: Optional[str]
    recipients: List[Dict]
    channels: List[str]
    schedule_at: Optional[datetime]
    priority: str
    metadata: dict
    idempotency_key: Optional[str]

@dataclass
class NotificationMessage:
    """Individual message to a single recipient via a single channel."""
    message_id: str
    notification_id: str
    channel: str
    recipient: str
    content: str
    status: str
```

### 4.2 Queue-Based Architecture

```python
import asyncio
from collections import defaultdict
import time

class NotificationOrchestrator:
    """
    Orchestrates notification submission, queuing, and dispatch.
    Uses in-memory queues for low latency, persisted to DB for durability.
    """
    
    def __init__(self, db_pool, redis_client):
        self.db = db_pool
        self.redis = redis_client
        self.queues = defaultdict(asyncio.Queue)  # Per-channel queues
        self.workers = {}
        self.dedup_cache = set()  # Idempotency check (in-memory LRU)
    
    async def submit(self, request: NotificationRequest) -> dict:
        """Submit a notification request."""
        
        # Idempotency check
        if request.idempotency_key:
            if request.idempotency_key in self.dedup_cache:
                return {
                    "notification_id": "DUPLICATE",
                    "status": "already_processed"
                }
            self.dedup_cache.add(request.idempotency_key)
        
        # For scheduled notifications, store and don't queue yet
        if request.schedule_at and request.schedule_at > datetime.utcnow():
            await self._schedule_notification(request)
            return {
                "notification_id": request.notification_id,
                "status": "scheduled",
                "estimated_delivery": request.schedule_at.isoformat()
            }
        
        # Generate messages for each recipient/channel combo
        messages = await self._generate_messages(request)
        
        # Persist to database
        await self._persist_notification(request, messages)
        
        # Enqueue for immediate dispatch
        for msg in messages:
            await self.queues[msg.channel].put(msg)
        
        return {
            "notification_id": request.notification_id,
            "status": "queued",
            "recipient_count": len(messages),
            "channel_breakdown": self._count_by_channel(messages)
        }
    
    async def _generate_messages(self, request: NotificationRequest) -> List[NotificationMessage]:
        """Generate individual messages using templates."""
        messages = []
        
        for recipient in request.recipients:
            for channel in request.channels:
                if channel not in recipient:
                    continue  # Skip if recipient doesn't have this channel
                
                content = await self._render_template(
                    request.template_id,
                    channel,
                    recipient,
                    request.metadata
                )
                
                messages.append(NotificationMessage(
                    message_id=f"msg_{uuid.uuid4().hex[:12]}",
                    notification_id=request.notification_id,
                    channel=channel,
                    recipient=recipient.get(channel),
                    content=content,
                    status=MessageStatus.QUEUED.value
                ))
        
        return messages
    
    async def start_workers(self):
        """Start per-channel worker pools."""
        worker_configs = {
            "email": {"count": 10, "batch_size": 100, "rate_limit": 50},   # 50/sec
            "sms": {"count": 5, "batch_size": 1, "rate_limit": 10},        # 10/sec
            "push": {"count": 10, "batch_size": 50, "rate_limit": 100},    # 100/sec
            "webhook": {"count": 3, "batch_size": 1, "rate_limit": 30},    # 30/sec
        }
        
        for channel, config in worker_configs.items():
            for i in range(config["count"]):
                worker = NotificationWorker(
                    channel=channel,
                    queue=self.queues[channel],
                    batch_size=config["batch_size"],
                    rate_limit=config["rate_limit"],
                    db=self.db
                )
                self.workers[f"{channel}_{i}"] = worker
                asyncio.create_task(worker.run())

class NotificationWorker:
    """Processes messages from a channel queue."""
    
    def __init__(self, channel: str, queue: asyncio.Queue,
                 batch_size: int, rate_limit: int, db_pool):
        self.channel = channel
        self.queue = queue
        self.batch_size = batch_size
        self.rate_limit = rate_limit
        self.db = db_pool
        self.rate_limiter = TokenBucket(rate=rate_limit, burst=rate_limit)
    
    async def run(self):
        """Main worker loop."""
        while True:
            try:
                # Collect batch
                batch = []
                while len(batch) < self.batch_size:
                    try:
                        msg = await asyncio.wait_for(
                            self.queue.get(), timeout=1.0
                        )
                        batch.append(msg)
                    except asyncio.TimeoutError:
                        break
                
                if not batch:
                    await asyncio.sleep(0.1)
                    continue
                
                # Rate limit
                await self.rate_limiter.acquire(len(batch))
                
                # Send batch
                await self._dispatch_batch(batch)
                
            except Exception as e:
                print(f"Worker error ({self.channel}): {e}")
                await asyncio.sleep(1)
    
    async def _dispatch_batch(self, batch: List[NotificationMessage]):
        """Dispatch a batch of messages via appropriate provider."""
        
        if self.channel == "email":
            await self._send_email_batch(batch)
        elif self.channel == "sms":
            await self._send_sms_batch(batch)
        elif self.channel == "push":
            await self._send_push_batch(batch)
        elif self.channel == "webhook":
            await self._send_webhook_batch(batch)
```

### 4.3 Provider Abstraction (Cost-Effective)

```python
class EmailProvider:
    """
    Abstraction over email providers.
    Default: Amazon SES (cheapest at $0.10/1000 emails)
    Fallback: SendGrid
    """
    
    PROVIDERS = {
        "ses": {
            "cost_per_1000": 0.10,
            "daily_limit": 50000,
            "rate_limit": 14  # emails/second
        },
        "sendgrid": {
            "cost_per_1000": 0.30,
            "daily_limit": 100000,
            "rate_limit": 100
        }
    }
    
    def __init__(self, primary="ses", fallback="sendgrid"):
        self.primary = primary
        self.fallback = fallback
        self.current = primary
        self.daily_count = 0
        self.reset_time = time.time() + 86400
    
    async def send_batch(self, messages: List[dict]) -> List[dict]:
        """Send batch with automatic failover."""
        try:
            return await self._send_via(self.current, messages)
        except Exception as e:
            if self.current != self.fallback:
                print(f"Failing over to {self.fallback}: {e}")
                self.current = self.fallback
                return await self._send_via(self.current, messages)
            raise
    
    async def _send_via(self, provider: str, messages: List[dict]) -> List[dict]:
        """Send via specific provider."""
        if provider == "ses":
            return await self._send_ses(messages)
        elif provider == "sendgrid":
            return await self._send_sendgrid(messages)
    
    async def _send_ses(self, messages: List[dict]) -> List[dict]:
        """Send via Amazon SES (bulk API for cost efficiency)."""
        # SES bulk send supports up to 50 recipients per call
        # Cost: $0.10 per 1000 emails + $0.12 per GB of attachments
        import boto3
        client = boto3.client('ses', region_name='us-east-1')
        
        results = []
        # Batch in groups of 50 (SES bulk limit)
        for i in range(0, len(messages), 50):
            batch = messages[i:i+50]
            
            response = await client.send_bulk_templated_email(
                Source="notifications@example.com",
                Template="default_template",
                Destinations=[
                    {
                        'Destination': {'ToAddresses': [msg['recipient']]},
                        'ReplacementTemplateData': json.dumps(msg.get('data', {}))
                    }
                    for msg in batch
                ]
            )
            
            for j, status in enumerate(response.get('Status', [])):
                results.append({
                    "message_id": batch[j]['message_id'],
                    "provider_id": status.get('MessageId'),
                    "status": "sent" if status.get('Status') == 'Success' else "failed",
                    "error": status.get('Error')
                })
        
        return results

class SMSProvider:
    """
    SMS provider abstraction.
    Default: Amazon SNS ($0.00645/SMS in US)
    Fallback: Twilio
    """
    
    async def send(self, phone: str, message: str) -> dict:
        import boto3
        sns = boto3.client('sns')
        
        response = await sns.publish(
            PhoneNumber=phone,
            Message=message,
            MessageAttributes={
                'AWS.SNS.SMS.SenderID': {'DataType': 'String', 'StringValue': 'Notify'},
                'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}
            }
        )
        
        return {
            "provider_id": response['MessageId'],
            "status": "sent"
        }
```

### 4.4 Scheduling Engine (Second-Level Precision)

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
        Called by a cron job every 1 second.
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

## 6. MONITORING & ALERTS

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
