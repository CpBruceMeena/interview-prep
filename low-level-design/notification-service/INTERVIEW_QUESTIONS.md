# 🔔 Notification Service — Interview Questions & Answers

> **Principal/Staff Software Engineer level | High-throughput notification systems**

---

## Q1: Design a notification system that can handle 1M notifications per day with second-level precision.

**Answer:**

**Architecture:**
```
API Gateway → Notification Orchestrator → Channel Queues → Worker Pools → Providers
                              ↓
                    Scheduler Engine (Redis ZSET)
                              ↓
                    PostgreSQL (persistence)
```

**Key decisions:**
- **Queue-based architecture** — decouples ingestion from delivery
- **Per-channel worker pools** — email, SMS, push, webhook each have dedicated workers with different batch sizes and rate limits
- **Redis sorted sets** — for scheduled delivery with second-level precision (ZADD/ ZRANGEBYSCORE)
- **Batching** — 100 emails per API call vs 1 SMS per call
- **Provider abstraction** — Strategy pattern for multi-provider support with automatic failover

**Scaling:**
- API layer: horizontal scale behind ALB
- Workers: per-channel worker pools (configurable count)
- Database: partition by date, archive after 90 days

---

## Q2: How do you ensure exactly-once delivery?

**Answer:** Exactly-once delivery is **impossible** in distributed systems (FLP impossibility). Instead, aim for **at-least-once** with **idempotent processing**:

```python
# Idempotency key ensures we don't process duplicates
async def submit(request):
    if await redis.exists(f"idempotent:{request.idempotency_key}"):
        return {"status": "already_processed"}
    
    # Store notification
    notif_id = await store_notification(request)
    await redis.setex(f"idempotent:{request.idempotency_key}", 86400, notif_id)
    
    return {"notification_id": notif_id, "status": "created"}
```

**Delivery tracking:**
- Track message status: pending → queued → sending → sent → delivered
- Dead letter queue for failed messages (retry up to 3 times)
- Bounce handling: mark email as bounced on 550 response

---

## Q3: How do you handle provider failures?

**Answer:** Use **circuit breaker** pattern with automatic failover:

```python
class CircuitBreakerProvider:
    def __init__(self, primary, fallback, threshold=5, timeout=60):
        self.primary = primary
        self.fallback = fallback
        self.failure_count = 0
        self.threshold = threshold
        self.timeout = timeout
        self.state = "closed"
        self.last_failure = 0
    
    async def send(self, message):
        if self.state == "open":
            if time.time() - self.last_failure > self.timeout:
                self.state = "half-open"
            else:
                return await self.fallback.send(message)
        
        try:
            result = await self.primary.send(message)
            self.failure_count = 0
            self.state = "closed"
            return result
        except Exception:
            self.failure_count += 1
            self.last_failure = time.time()
            if self.failure_count >= self.threshold:
                self.state = "open"
            return await self.fallback.send(message)
```

---

## Q4: How do you keep costs low?

**Answer:**

| Strategy | Impact |
|----------|--------|
| **Batch emails** | 1M API calls → 10K calls (100/batch) = 99% reduction |
| **Use cheapest provider first** | SES ($0.10/1K) > SendGrid ($0.30/1K) |
| **Rate limit free tier** | FCM push is free up to 1M/month |
| **Deduplicate** | Prevent double-sending on retry |
| **Template rendering** | Store templates, send only variables |
| **Compression** | Compress large payloads before storing |
| **Retention policy** | Archive hot data after 30 days, delete after 90 |

**Monthly estimate for 1M notifications:**
- SES: 1M emails @ $0.10/1K = $100
- SNS: 10K SMS @ $0.00645 = $65
- FCM: 500K push @ $0 = $0
- Infrastructure: ~$50
- **Total: ~$215/month**

---

## Q5: How do you achieve second-level scheduling precision?

**Answer:**

```python
# Use Redis sorted sets with Unix timestamp as score
# O(log N) for insert, O(log N + M) for retrieval

async def schedule(notif_id, send_at):
    timestamp = send_at.timestamp()
    await redis.zadd("schedule:queue", {notif_id: timestamp})

# Background loop (runs every second)
async def process_schedule():
    while True:
        now = time.time()
        due = await redis.zrangebyscore(
            "schedule:queue", 0, now
        )
        for notif_id in due:
            await redis.zrem("schedule:queue", notif_id)
            await process_notification(notif_id)
        
        await asyncio.sleep(1)
```

For higher precision (sub-second), use Redis streams with `XREADGROUP BLOCK 0`.

---

## Q6: How do you handle notification failure and retry?

**Answer:**

```python
async def send_with_retry(message, max_retries=3):
    """Exponential backoff retry with dead letter queue."""
    for attempt in range(max_retries):
        try:
            result = await provider.send(message)
            return result
        except TemporaryFailure as e:
            wait = min(2 ** attempt * 10, 300)  # 10s, 20s, 40s...
            await asyncio.sleep(wait)
        except PermanentFailure:
            message.status = "failed"
            await dead_letter_queue.put(message)
            raise
    
    # All retries exhausted
    message.status = "failed"
    await dead_letter_queue.put(message)
    raise MaxRetriesExceeded(f"Failed after {max_retries} attempts")
```

---

## Q7: How do you monitor notification system health?

**Answer:**

```python
# Key metrics
METRICS = {
    "throughput": "notifications/second",
    "latency_p50": "median delivery time",
    "latency_p99": "P99 delivery time",
    "delivery_rate": "successful / total sent",
    "bounce_rate": "bounced / total sent",
    "provider_failover": "how often providers failover",
    "retry_rate": "messages requiring retry",
    "queue_depth": "current queue depth per channel",
}

# Alert thresholds
ALERTS = {
    "delivery_rate < 95%": "Provider issue, check error logs",
    "bounce_rate > 5%": "List quality issue, check recipients",
    "queue_depth > 10K": "Worker scaling needed",
    "latency_p99 > 60s": "Performance degradation",
}
```

---

## Evaluation Rubric

| Criteria | Expected | Excellent |
|----------|----------|-----------|
| **Architecture** | Queue-based, per-channel workers | Multi-provider failover, circuit breakers, dead letter queues |
| **Reliability** | Retry logic | At-least-once delivery, idempotency, deduplication |
| **Performance** | Batching | Configurable batch sizes per channel, rate limiting |
| **Cost** | Basic provider choice | Tiered provider strategy, cost tracking per notification |
| **Scheduling** | Simple timer | Redis sorted sets, sub-second precision, catch-up on restart |
| **Monitoring** | Status endpoint | Full metrics dashboard, proactive alerting, cost analytics |
