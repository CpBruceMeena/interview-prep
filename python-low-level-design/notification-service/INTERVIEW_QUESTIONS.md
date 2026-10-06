# 🔔 Notification Service — Interview Questions & Answers

> **Senior/Staff Software Engineer level | Reliable, polite, multi-channel delivery**

---

## Q1: Design a notification system that handles 1M notifications per day across email, SMS and push.

**Answer:**

```
API → validate, idempotency, render, fan out → Delivery records (DB)
                                             → per-channel queues (Kafka/SQS), by priority
                                                    ↓
                       workers: quiet hours → rate limits → provider → retry / DLQ
                                                    ↓
                          provider callbacks (delivered / bounced) → status updates
```

**Sizing first:** 1M/day is ~12/s average; with a 10× peak it is ~120/s. That is small. The hard parts are not throughput but correctness (no duplicates, no lost messages), politeness (rate limits, quiet hours, opt-outs) and provider behaviour (throttling, failures, cost).

**Key decisions:**
- **Fan out to one delivery per channel**, each with its own status, attempts and error.
- **Queue between API and workers** so a slow provider never slows the API, and so each channel scales and is rate limited independently.
- **Separate queues (or partitions) per priority**, so OTPs never wait behind a marketing blast.
- **Provider adapters** behind one `ChannelSender` interface, with failover to a secondary provider on transient errors.

---

## Q2: How do you make sure a user doesn't get the same notification twice?

**Answer:** Exactly-once delivery to a device is not achievable end to end: if the provider accepted the message and the ack was lost, a retry may send it again (the Two Generals problem). So the target is **at-least-once with duplicates suppressed at every layer you control**:

1. **Idempotency key on submit.** The caller sends a key derived from the business event (`order-123-shipped`). A unique constraint on the key (with a TTL / retention window) returns the original notification on retry. Claim it atomically (`INSERT ... ON CONFLICT DO NOTHING`, or Redis `SET key value NX EX 86400`); "check if exists, then insert" lets two concurrent retries both pass.
2. **Content dedup window.** Same (user, template, params) within N minutes under a *different* key, typically an upstream double-fire, is suppressed.
3. **Worker claims.** A delivery is claimed (status SENDING, or a queue visibility timeout) before sending, so two workers never send it concurrently.
4. **Provider idempotency** where it exists: pass the delivery id. Where it doesn't (most SMS and email APIs), accept the small duplicate window after a lost ack.

In the code: `submit()` handles 1 and 2 under one lock, `process_next()` handles 3.

---

## Q3: Retries. What do you retry, how, and when do you stop?

**Answer:**

| Error | Example | Action |
|-------|---------|--------|
| Transient | timeout, 5xx, 429 throttled | Retry with exponential backoff + full jitter, honour `Retry-After` |
| Permanent | invalid number, SMTP 550 hard bounce, FCM `UNREGISTERED` token | Fail now; update the user's contact (mark email invalid, delete token) |
| Policy deferral | quiet hours, rate limited | Not an error; reschedule, don't count an attempt |

```python
delay = random.uniform(0, min(cap, base * 2 ** (attempt - 1)))   # full jitter
```

Jitter matters because a provider outage fails thousands of deliveries at once; without jitter they all retry at the same instant and knock it over again. After `max_attempts`, move to a **dead-letter queue** with the last error, alert on DLQ growth, and provide a replay tool. Also give each message a **time-to-live**: an OTP that is 10 minutes late is useless, so drop it rather than retry forever.

---

## Q4: Rate limiting. Per what?

**Answer:** Three different limits protect three different things:

| Limit | Protects | Example |
|-------|----------|---------|
| Per user per channel | The user from spam; you from SMS-pumping fraud | ≤ 3 SMS / user / hour |
| Per channel / provider | Provider quota and sender reputation | SES account sending rate, Twilio per-number throughput |
| Per tenant / caller | Other tenants from one noisy caller | API quota |

Token bucket (burst + steady rate) per key. Check all applicable buckets and debit only if all allow; otherwise you burn the user's token on a send the provider bucket then refuses. **Defer** over-limit transactional messages; **drop** (or collapse into a digest) over-limit marketing. In a fleet the buckets live in Redis, updated atomically with a Lua script (read tokens, refill by elapsed time, take one, write back), because separate GET and SET calls race between workers.

---

## Q5: Quiet hours and user preferences

**Answer:** Preferences: contacts per channel, opt-outs per channel and per category (marketing vs transactional), quiet hours with a timezone.

Pitfalls interviewers look for:
- **Timezone:** store an IANA zone (`Asia/Kolkata`), not an offset, so DST is handled. Evaluate in the user's local time.
- **Windows that wrap midnight:** 22:00–07:00 means `t >= start or t < end`, not `start <= t < end`.
- **Check at send time**, not just at submit: a retry or scheduled message can land inside the window.
- **Defer to the window end**, don't drop, for transactional; marketing can be dropped or held for the next morning's batch.
- **Explicit overrides:** CRITICAL (OTP, fraud alert) bypasses quiet hours and channel opt-outs, but not rate limits.
- Legal opt-outs (unsubscribe, DND registries) are not preferences you may override.

---

## Q6: Priority. How does an OTP not wait behind 1M marketing emails?

**Answer:** In one process: two heaps, a delayed heap by `ready_at` and a ready heap by `(priority, seq)`. A single heap keyed by time-then-priority gets this wrong. In a distributed system: **separate queues/topics per priority** with dedicated (or weighted) consumer capacity, since a FIFO queue cannot reorder messages already enqueued. Marketing blasts are also paced at the producer, so they never fill the queue in the first place. Under sustained HIGH load LOW starves; fix with weighted fair consumption or aging.

---

## Q7: How do you handle provider failures?

**Answer:** Circuit breaker per provider: CLOSED → OPEN after N consecutive failures (or error rate over a window) → after a cooldown, HALF_OPEN lets a few probe requests through → CLOSED on success. While OPEN, route to the secondary provider (SES → SendGrid, Twilio → SNS). Two caveats: a timeout may mean the primary *did* send, so failover can duplicate (acceptable for most notifications, not for OTPs where it confuses users, so keep the same code); and secondary providers often need warm-up (sender reputation, registered sender IDs), so keep a small share of traffic on them at all times.

---

## Q8: Scheduling ("send at 9 a.m. user local time")

**Answer:** Store `send_at` as UTC computed from the user's zone. Small scale: a DB index on `(status, send_at)` polled every second with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 100` so several schedulers can poll without double-claiming. Redis alternative: a sorted set scored by timestamp; claim due items atomically with a Lua script (`ZRANGEBYSCORE` + `ZREM` in one script), or check that `ZREM` returned 1 before processing, otherwise two pollers send the same item. Large campaigns ("everyone at 9 a.m. local") create spikes per timezone: pre-enqueue and spread them over a few minutes.

---

## Q9: Monitoring

Metrics per channel and provider: accepted/s, send latency (p50/p99 from submit to provider-accepted), provider error rate by error class, retry rate, DLQ size, queue depth and age of oldest message (better than depth for alerting), suppression counts by reason, bounce and complaint rates (email reputation: keep complaints well under 0.1%), cost per message. Alert on oldest-message age for CRITICAL queues, DLQ growth, bounce/complaint spikes and circuit-breaker opens.

---

## 🔁 Follow-ups interviewers push on

**"Add a new channel (WhatsApp)."** New `Channel` value, a `ChannelSender` adapter, templates for it, its own rate limits. Nothing in the service changes. If adding a channel requires touching `process_next`, the abstraction is wrong.

**"Batch the daily digest."** LOW notifications for a user are collected for a period and rendered into one message; that is a separate aggregation step before fan-out, keyed by (user, digest type, period), and itself idempotent.

**"Delivery receipts."** Providers call back (SES via SNS, Twilio status callbacks, FCM has none for delivery). Map the provider message id back to the delivery, move SENT → DELIVERED / BOUNCED, dedupe callbacks, tolerate out-of-order arrival (a late "sent" must not overwrite "delivered").

**"Two workers took the same message."** With an SQS-style visibility timeout this happens if processing exceeds the timeout. Fix: visibility timeout above the worst-case send time, extend it while working, and make the state transition conditional (`UPDATE ... SET status='SENDING' WHERE id=? AND status='QUEUED'`).

**"How do you test this?"** Fake senders with scripted transient/permanent failures, an injected clock (quiet hours, backoff, rate limits, TTLs are all time-based), table tests for quiet-hour edges (exactly at start, exactly at end, wrapping midnight), and concurrency tests that assert invariants: each delivery sent exactly once by N workers, rate limit never exceeded, duplicate submits produce one notification.

---

## ⚠️ Common mistakes

- Claiming exactly-once delivery (or attributing its impossibility to FLP, which is about consensus; the relevant result is the Two Generals problem).
- Idempotency via "if key exists return, else insert": racy without an atomic claim. Unbounded in-memory dedup sets, or clearing the whole set when it fills (which re-allows every recent duplicate).
- Retrying permanent errors, or retrying without jitter.
- Counting quiet-hour or rate-limit deferrals as failed attempts, so messages die without ever being tried.
- Quiet hours compared in UTC, or broken for windows that wrap midnight.
- A single priority queue ordered by time first, or one FIFO shared by OTPs and marketing.
- Debiting the user's rate-limit token before checking the provider limit.
- Holding a lock across the provider call.
- Rendering templates with silent fallback, sending "Hi {{name}}" to real users.

---

## 🎯 Senior vs Staff signal

- **Senior:** clean fan-out model, provider abstraction, retries with backoff and a DLQ, idempotency key, per-user rate limit, quiet hours that work across midnight, tests with a fake clock.
- **Staff:** states the delivery guarantee honestly (at-least-once, where duplicates can still occur and why); places each policy at submit vs send time with reasons; gets priority right in-process and knows a FIFO broker needs separate queues; distinguishes the three kinds of rate limits and what each protects; designs for provider reality (bounces feeding back into contact validity, reputation, warm standby providers, TTLs for time-sensitive messages); sizes the system before scaling it.

---

## Evaluation Rubric

| Criteria | Expected | Excellent |
|----------|----------|-----------|
| **Model** | Request → messages per channel | Per-delivery status, attempts, reasons for suppression |
| **Reliability** | Retry logic | Transient vs permanent, jittered backoff, DLQ + replay, TTL for stale messages |
| **Duplicates** | Idempotency key | Atomic claim, content dedup window, worker claims, honest about the residual window |
| **Politeness** | Rate limit | Per user+channel, per provider, per tenant; opt-outs by category; quiet hours in local time |
| **Priority** | Priority field | Correct ordering among ready work; separate queues in production; starvation addressed |
| **Operations** | Status endpoint | Oldest-message age, DLQ alerts, bounce/complaint rates, cost per message |
