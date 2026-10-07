# ☁️ AWS Messaging — Staff-Level Interview Questions

> *10 questions covering SQS, SNS, EventBridge, Kinesis, Amazon MQ (and where MSK fits). Each answer leads with the 30-second version, then the mechanism, trade-offs, failure modes and what interviewers probe next. Limits checked against AWS documentation, October 2026.*

---

## Table of Contents

1. [SQS: Queue Types, Redrive, DLQ](#1-sqs-queue-types-redrive-dlq)
2. [SQS: Long Polling, Visibility Timeout, Batching](#2-sqs-long-polling-visibility-timeout-batching)
3. [SNS: Pub/Sub, Filter Policies, Message Attributes](#3-sns-pubsub-filter-policies)
4. [SNS + SQS: Fan-Out Pattern](#4-sns-sqs-fan-out-pattern)
5. [EventBridge: Event Bus, Rules, Pipes](#5-eventbridge-event-bus-rules-pipes)
6. [EventBridge Schema Registry & Events](#6-eventbridge-schema-registry-events)
7. [Kinesis Data Streams: Shards, Partition Keys, Limits](#7-kinesis-data-streams-shards-partition-keys)
8. [Kinesis Enhanced Fan-Out & EFO](#8-kinesis-enhanced-fan-out-efo)
9. [Amazon MQ vs SQS vs Kinesis](#9-amazon-mq-vs-sqs-vs-kinesis)
10. [Event-Driven Architecture: Design Patterns](#10-event-driven-architecture-design-patterns)

---

## 1. SQS: Queue Types, Redrive, DLQ

**Q:** "Design a message processing pipeline where messages must be processed exactly once, in order, with automatic retry for failures. Compare standard queues, FIFO queues, and dead-letter queues. How does redrive work with DLQ?"

### Answer

!!! tip "30-second answer"
    No queue gives you end-to-end exactly-once *processing*. FIFO gives ordering per `MessageGroupId` and **deduplicates sends** within a 5-minute window; delivery to consumers is still effectively at-least-once (a consumer that crashes before `DeleteMessage` gets the message again). So: FIFO for per-key order, an **idempotent consumer** (dedup table keyed by business ID) for exactly-once *effects*, and a DLQ with `maxReceiveCount` for poison messages, redriven with `StartMessageMoveTask` once the bug is fixed.

**Queue types:**

| | Standard | FIFO |
|---|---|---|
| Ordering | Best-effort | Strict within a `MessageGroupId` |
| Delivery | At-least-once (occasional duplicates) | Send-side dedup within 5 min; consumer side still needs idempotency |
| Throughput | Nearly unlimited | 300 API calls/s per action (3,000 msg/s with batches of 10). **High-throughput mode**: up to 70,000 calls/s (700,000 msg/s batched) in us-east-1, us-west-2, eu-west-1; lower in other Regions |
| Multi-tenant fairness | **Fair queues** (Jul 2025): set `MessageGroupId` on a standard queue and SQS de-prioritises a tenant with a disproportionate share of in-flight messages | Groups are processed in order, so one slow group blocks only itself |
| Price | $0.40 per million requests | $0.50 per million requests |

Shared limits: message size up to **1 MiB** (raised from 256 KiB in Aug 2025; use the Extended Client Library with S3 for up to 2 GB), retention 1 minute to 14 days (default 4 days), delay 0–15 minutes, visibility timeout 0 s to 12 h (default 30 s).

**How FIFO ordering and dedup work:**

```python
sqs.send_message(
    QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/orders.fifo",
    MessageBody='{"orderId": "ORD-123", "action": "create"}',
    MessageGroupId="ORD-123",               # order is guaranteed per group
    MessageDeduplicationId="ORD-123-create" # or enable ContentBasedDeduplication
)
```

- Messages in one group are delivered one batch at a time: while a message from group `ORD-123` is in flight, no later message from that group is delivered. Parallelism therefore equals the number of active groups. One group = one consumer, effectively.
- Pick the group key as the narrowest scope that needs ordering (order ID, account ID), not a constant. A constant group ID caps you at serial processing.
- High-throughput mode partitions the queue by a hash of `MessageGroupId`; it needs `DeduplicationScope=messageGroup` and `FifoThroughputLimit=perMessageGroupId`.

**DLQ and redrive:**

```
source queue ──(receive count > maxReceiveCount)──► DLQ
                                                    │
         StartMessageMoveTask (console/SDK/CLI) ◄───┘  after the fix
```

- `RedrivePolicy` on the source sets `deadLetterTargetArn` and `maxReceiveCount` (3–5 is typical; 1 sends every transient failure to the DLQ).
- A FIFO source needs a FIFO DLQ; a standard source needs a standard DLQ.
- Redrive back to the source (or a custom destination) uses `StartMessageMoveTask`, supported for standard queues since June 2023 and FIFO since November 2023, with an optional max messages-per-second rate.
- Set the DLQ's retention longer than the source's. The enqueue timestamp is preserved for standard queues, so a message can expire in the DLQ sooner than you expect.

**Failure modes and what they probe next:**

- *Poison message in FIFO:* it blocks its whole group until it reaches `maxReceiveCount` and moves to the DLQ. Moving it means later messages in that group run without it, which can break business ordering. Decide explicitly whether to halt the group or skip.
- *"How do you get exactly-once effects?"* Conditional write to a dedup table (`attribute_not_exists(messageId)` in DynamoDB) in the same transaction as the side effect, or make the side effect itself idempotent (upsert, idempotency key on the payment API).
- *DLQ alarm:* `ApproximateNumberOfMessagesVisible > 0` on the DLQ, plus `ApproximateAgeOfOldestMessage` on the source to catch a stuck consumer.

---

## 2. SQS: Long Polling, Visibility Timeout, Batching

**Q:** "Your SQS consumer polls the queue and gets only 1-2 messages per call, wasting network round trips. How does long polling help? How does visibility timeout interact with message processing failures?"

### Answer

!!! tip "30-second answer"
    Set `WaitTimeSeconds=20` and `MaxNumberOfMessages=10`. Short polling queries a *subset* of SQS servers and returns immediately, so you get empty or partial responses; long polling queries all servers and waits until at least one message arrives or the timeout ends. Fewer empty receives means fewer billed requests. Visibility timeout is a lease: if you don't delete the message before it expires, it becomes visible again and another consumer gets it. Set it comfortably above your worst-case processing time (for a Lambda consumer, AWS recommends at least six times the function timeout), or extend it with `ChangeMessageVisibility` as a heartbeat.

**Long polling:**

| | Short polling (`WaitTimeSeconds=0`, default) | Long polling (1–20 s) |
|---|---|---|
| Servers queried | A weighted random subset | All |
| Empty queue | Returns immediately, empty | Waits up to the wait time |
| Cost | Every empty receive is a billed request | Far fewer empty receives |
| Set where | — | Queue attribute `ReceiveMessageWaitTimeSeconds` or per call |

Cost illustration (standard queue, $0.40 per million requests): a consumer that short-polls an often-empty queue 10 times a second makes ~26 million requests a month (~$10). With 20-second long polls it makes at most ~130,000 (~$0.05). The win grows with the number of consumers, and each 64 KiB chunk of a payload is billed as one request.

**Visibility timeout lifecycle:**

```
ReceiveMessage ──► in flight (invisible for VisibilityTimeout)
                     │
         processed ──┼──► DeleteMessage (with receipt handle) ──► gone
                     │
   crash / timeout ──┴──► visible again, ApproximateReceiveCount + 1
                                 │
                       > maxReceiveCount ──► DLQ
```

- Too short: the message reappears while still being processed, causing duplicate work.
- Too long: a crashed consumer delays the retry by the whole timeout.
- Long-running jobs: start with a moderate timeout and call `ChangeMessageVisibility` periodically. Set it to 0 to release a message immediately for retry.
- Receipt handles change on every receive; delete with the latest one.

**Batching:** `SendMessageBatch`, `DeleteMessageBatch` and `ChangeMessageVisibilityBatch` take up to 10 messages, cut API calls (and cost) by up to 10x, and are how FIFO queues reach their batched throughput figures. Batch entries can fail individually: check the `Failed` list in the response.

**Lambda as the consumer:**

- The event source mapping long-polls for you. Enable `ReportBatchItemFailures` so one bad record does not force the whole batch back onto the queue.
- Default mode scales up to 1,250 concurrent invocations per mapping. **Provisioned mode** (Nov 2025) lets you set minimum and maximum event pollers for faster, higher scaling; since Aug 2026 it allows up to 10,000 pollers.
- Use `MaximumConcurrency` on the mapping to protect a downstream database, rather than reserved concurrency (which throttles and returns messages to the queue).

**What they probe next:** in-flight limits (about 120,000 for standard, 120,000 for FIFO), why `ApproximateAgeOfOldestMessage` is the best scaling signal, and how you scale EC2/ECS consumers on queue depth per worker (target tracking on a custom "backlog per task" metric).

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-sqs-long-polling.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated SQS Short Polling vs Long Polling — wasteful empty responses vs batched wait with 90% cost reduction — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. SNS: Pub/Sub, Filter Policies

**Q:** "You have an SNS topic publishing order events. Multiple subscribers need different subsets: the payment service needs only 'payment_captured' events, the inventory service needs 'order_placed', and the audit service needs all events. How do filter policies work?"

### Answer

!!! tip "30-second answer"
    Each subscription gets its own filter policy. SNS evaluates it before delivery, so subscribers only receive (and you only pay delivery for) matching messages. By default the policy matches **message attributes**; set `FilterPolicyScope=MessageBody` to match fields in a JSON body instead. The audit subscription has no policy and receives everything.

**Publishing with attributes:**

```python
sns.publish(
    TopicArn=topic_arn,
    Message=json.dumps({"order_id": "ORD-123", "amount": 99.99}),
    MessageAttributes={
        "event_type": {"DataType": "String", "StringValue": "order_placed"},
        "amount":     {"DataType": "Number", "StringValue": "99.99"},
    },
)
```

**Subscription filter policies** (set as the `FilterPolicy` subscription attribute):

```json
{ "event_type": ["payment_captured", "payment_failed"] }
```

```json
{ "event_type": ["order_placed", "order_cancelled"] }
```

```json
{
  "event_type": ["order_placed"],
  "amount": [{ "numeric": [">=", 500] }]
}
```

- Keys in one policy are ANDed; values in an array are ORed; `$or` combines whole sub-policies.
- Operators include exact match, `prefix`, `suffix`, `anything-but`, `equals-ignore-case`, `numeric` (ranges), `exists`, and IP address (`cidr`).
- Attribute data types: `String`, `String.Array`, `Number`, `Binary` (binary attributes cannot be filtered on).
- Filter-policy changes take up to about 15 minutes to propagate. A new filter is not instant, so deploy filters before relying on them.

**Trade-offs:**

- Attribute filtering keeps the body opaque and lets producers add routing hints cheaply. Body filtering avoids duplicating fields into attributes but couples consumers to the payload shape.
- Topics can be **standard** (very high throughput, best-effort order) or **FIFO** (ordered per message group, dedup; subscribe SQS queues to it, standard or FIFO).
- Payloads: 256 KiB by default; since Sept 2026 you can raise a topic to **1 MiB** with the `MaximumMessageSize` attribute. For larger payloads use the Extended Client Library (S3 pointer).

**What they probe next:** SNS vs EventBridge for routing (EventBridge has richer pattern matching, schema registry, archive/replay and more target types; SNS has higher fan-out throughput, lower latency and mobile/SMS/email endpoints), and how you keep producers from leaking PII to every subscriber (separate topics or body-level message data protection policies).

---

## 4. SNS + SQS: Fan-Out Pattern

**Q:** "Design a fan-out pattern using SNS to SQS for an order processing pipeline. Three services need to process each order: payment (must succeed), inventory (best-effort), and notification (async). How do you handle failure isolation?"

### Answer

!!! tip "30-second answer"
    Publish once to a topic; subscribe one SQS queue per service. Each queue buffers independently, so a slow or broken consumer only grows its own backlog. Retries and DLQs are per queue. Watch the two failure points people forget: SNS-to-SQS delivery (needs a queue policy and, for encrypted queues, KMS permissions; give the subscription its own DLQ) and duplicate delivery (each consumer must be idempotent).

**Fan-out architecture:**

```
SNS topic: order-events
    │
    ├── SQS: payment-queue ────► Lambda: payment-processor
    │      └── DLQ: payment-dlq   (page on-call; money is at stake)
    │
    ├── SQS: inventory-queue ──► Lambda: inventory-updater
    │      └── DLQ: inventory-dlq (retry, reconcile later)
    │
    └── SQS: notification-queue ► Lambda: notification-sender
           └── DLQ: notification-dlq (alarm, low severity)

    + subscription-level DLQ on each SNS→SQS subscription
      (catches messages SNS could not deliver to the queue)
```

**Failure isolation, layer by layer:**

| Failure | What happens | Mitigation |
|---|---|---|
| Consumer throws | Message reappears after visibility timeout; after `maxReceiveCount` goes to that queue's DLQ | Per-service alarms and redrive |
| Consumer slow | Only its queue's backlog grows | Scale on `ApproximateAgeOfOldestMessage` |
| SNS cannot deliver to SQS (queue policy, KMS key policy, queue deleted) | SNS retries (for SQS endpoints, aggressively over a period), then drops or sends to the **subscription DLQ** if configured | Subscription redrive policy; alarm on `NumberOfNotificationsFailed` |
| Duplicate delivery | Rare, but SNS standard is at-least-once | Idempotent consumers |

**Gotchas:**

- The queue's access policy must allow `sqs:SendMessage` from the topic ARN (`aws:SourceArn` condition).
- For KMS-encrypted queues, use SSE-SQS or a customer managed key whose policy allows `sns.amazonaws.com` to use it. The AWS managed key `aws/sqs` cannot be granted to SNS.
- Enable **raw message delivery** if consumers want the original body rather than the SNS JSON envelope.
- "Payment must succeed" is not something fan-out can guarantee. If payment failure must cancel the order, that is a saga with compensation (see Q10), not independent fan-out.

**What they probe next:** why not have the producer write to three queues (coupling and partial failures), and SNS+SQS vs EventBridge-to-SQS (EventBridge adds content-based routing and replay, at lower per-target throughput and higher latency).

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-sns-fanout.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated SNS → SQS Fan-Out Pattern — single topic fans out to multiple queues with independent retry and failure isolation — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 5. EventBridge: Event Bus, Rules, Pipes

**Q:** "Design an event-driven microservices architecture using EventBridge as the central event bus. How do EventBridge Pipes differ from EventBridge Rules? How do you handle schema evolution?"

### Answer

!!! tip "30-second answer"
    A **bus** decouples many producers from many consumers: producers `PutEvents`, and rules (or, on the newer bus type, subscribers) match event patterns and deliver to targets. A **Pipe** is point-to-point: one polling source (SQS, Kinesis, DynamoDB Streams, MSK/Kafka, Amazon MQ), optional filter, optional enrichment (Lambda, Step Functions, API Gateway, API destination), one target. Use Pipes to replace glue Lambdas; use a bus for routing between teams. Evolve schemas additively and version them in `detail-type` or a `version` field (see Q6).

**Bus building blocks:**

```
producers ──PutEvents──► event bus ──► rule: pattern ──► up to 5 targets
                         (default: AWS service events;     (Lambda, SQS, SNS,
                          custom: your app events;           Step Functions,
                          partner: SaaS sources)             API destination,
                                                             another bus, ...)
```

```json
{
  "source": ["com.acme.orders"],
  "detail-type": ["OrderPlaced"],
  "detail": { "amount": [{ "numeric": [">=", 500] }] }
}
```

**Pipes vs rules:**

| | Rule on a bus | Pipe |
|---|---|---|
| Topology | Many-to-many | One source to one target |
| Source | Events pushed with `PutEvents` / AWS services | Polls a stream or queue for you |
| Ordering | Not preserved | Preserved for ordered sources (Kinesis, DynamoDB Streams, FIFO SQS) |
| Enrichment step | No (input transformer only) | Yes |
| Price | $1.00 per million custom events published | $0.40 per million requests **after filtering** |

**Delivery semantics and failure handling (classic bus):**

- At-least-once delivery; no ordering.
- Retries for up to 24 hours and up to 185 attempts by default (configurable per target), then the event is dropped unless the target has a **DLQ** (an SQS queue).
- Archive and replay: an archive keeps matching events; replay re-sends them to the bus, which is how you rebuild a consumer.
- Quotas worth knowing: 300 rules per bus (adjustable), 5 targets per rule (fixed), `PutEvents` 10,000 requests/s in us-east-1 (adjustable). Event payloads up to **1 MB** since January 2026 (was 256 KB) in most Regions.

**The newer "Custom Event Bus" (2026):** AWS now offers a second bus type alongside the rules-based one (renamed *Custom Event Bus - Classic* in the console). It is built for one platform team sharing a bus with many accounts through AWS RAM: consumers attach **subscribers** (filter + one target each), every event is **retained** for 1–365 days, subscribers can start from a past point (replay without a separate archive), delivery can be **FIFO within an event group**, and publishes are deduplicated within 5 minutes. Mention it if asked about Kafka-like replay on EventBridge; verify Regional availability before designing around it.

**Failure modes and what they probe next:**

- Lambda target throttled: EventBridge retries asynchronously, then DLQ. For bursty targets, route through SQS first.
- Cross-account: send to a bus in the other account (needs a resource policy on that bus), or share a new-style bus via RAM.
- Latency: typically tens to hundreds of milliseconds, higher than SNS; don't put EventBridge in a synchronous request path.

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-eventbridge-routing.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated EventBridge Event Bus & Routing — content-based rules filter events and route to Lambda, SQS, and Step Functions — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 6. EventBridge Schema Registry & Events

**Q:** "Your team has 20 microservices producing and consuming events. How do you manage event schema evolution? How does EventBridge Schema Registry help with type safety?"

### Answer

!!! tip "30-second answer"
    Schema Registry is a **catalog plus code generator**, not a gatekeeper. Schema discovery infers schemas from events on a bus (OpenAPI 3 or JSON Schema Draft 4) and versions them; you download code bindings (Java, Python, TypeScript, Go) to get typed events. It does **not** reject incompatible events. Compatibility is your job: additive changes only, never repurpose or remove a field, bump a major version (new `detail-type` or a `version` field) for breaking changes and run both versions until consumers migrate. Enforce that in CI with contract tests.

**A versioned schema (JSON Schema):**

```json
{
  "$schema": "http://json-schema.org/draft-04/schema#",
  "title": "OrderPlaced",
  "type": "object",
  "properties": {
    "version":      { "type": "string", "enum": ["2"] },
    "orderId":      { "type": "string" },
    "amount":       { "type": "number" },
    "customerId":   { "type": "string" },
    "discountCode": { "type": "string" }
  },
  "required": ["orderId", "amount", "customerId"]
}
```

`discountCode` is new and optional, so v1 consumers keep working (they ignore unknown fields) and v2 consumers handle its absence.

**Evolution rules that actually matter:**

| Change | Safe? | Why |
|---|---|---|
| Add an optional field | Yes | Old consumers ignore it |
| Add a required field | No for consumers reading old events (replay, archives) | Old events lack it |
| Remove or rename a field | No | Consumers break |
| Change a type or meaning | No | Silent corruption; worst case |

**Tooling choices:**

- *EventBridge Schema Registry:* discovery and code bindings for JSON events on EventBridge. Discovery is billed per ingested event beyond a free tier, so enable it in dev/staging, not necessarily prod.
- *AWS Glue Schema Registry:* Avro, JSON Schema and Protobuf with **enforced compatibility modes** (BACKWARD, FORWARD, FULL and transitive variants); integrates with MSK, Kinesis and Lambda. Choose it when you need the registry to reject bad producers.
- *Contract tests in CI* (e.g. consumer-driven contracts) catch breaking changes before deploy regardless of registry.

**What they probe next:** the envelope (EventBridge's `source`, `detail-type`, `id`, `time` plus your own `version`, `correlationId`, `idempotencyKey`), fat vs thin events (full state vs ID plus a callback; thin events push load back onto the producer and race with updates), and who owns the schema (the producer, published like an API).

---

## 7. Kinesis Data Streams: Shards, Partition Keys

**Q:** "You're streaming 50MB/s of clickstream data into Kinesis. How many shards do you need? How does partition key affect shard distribution? What happens when a shard is hot?"

### Answer

!!! tip "30-second answer"
    A provisioned shard takes **1 MB/s or 1,000 records/s** of writes and serves **2 MB/s** of shared reads. 50 MB/s needs at least 50 shards for bytes; with 1 KB records that is also 50,000 records/s, exactly at the record limit, so provision about 60–70 for headroom (or use on-demand mode). Kinesis MD5-hashes the partition key into a 128-bit key space and each shard owns a contiguous hash range, so a hot key pins to one shard and throttles at 1 MB/s no matter how many shards you add.

**Sizing (provisioned mode):**

```
shards ≥ max( write MB/s ÷ 1,
              write records/s ÷ 1,000,
              read MB/s per consumer ÷ 2  (shared-throughput consumers combined) )

50 MB/s of 1 KB records:
  bytes:   50 / 1      = 50 shards
  records: 50,000 / 1,000 = 50 shards
  → 50 is the floor; add ~30% headroom for skew → ~65 shards
```

**On-demand mode** removes shard math: a new stream starts at 4 MB/s write and scales automatically, up to 10 GB/s write in us-east-1, us-west-2 and eu-west-1 (200 MB/s elsewhere by default). It absorbs up to double the previous peak instantly; faster growth can briefly throttle. You can switch modes twice per 24 hours. **On-demand Advantage**, an account-level setting, lowers per-GB prices and removes the EFO premium in exchange for a minimum committed throughput across the account.

**Partition keys and hot shards:**

- Key → `MD5(key)` → 128-bit integer → the shard whose `HashKeyRange` contains it. It is *not* `hash mod N`, which is why splitting one shard doesn't move other shards' keys.
- Hot key symptoms: `WriteProvisionedThroughputExceeded` on a few shards while the stream average looks fine. Check per-shard metrics (enhanced monitoring).
- Fixes: a higher-cardinality key (e.g. `userId` not `country`); salt a hot key (`key#0..N`) and accept that you lose per-key ordering across salts; or set `ExplicitHashKey` to place records deliberately.
- Ordering is guaranteed only per shard, for records with the same partition key, in sequence-number order.

**Resharding (provisioned):**

- `SplitShard` splits one shard's hash range into two; `MergeShards` combines two adjacent ranges. The parent shard closes; consumers must finish the parent before reading children to preserve order (the KCL does this).
- `UpdateShardCount` (uniform scaling) is limited to 10 scaling operations per rolling 24 hours per stream, and each call can at most double or halve the count.
- Default account shard quota is 20,000 in us-east-1, us-west-2 and eu-west-1 (lower elsewhere), adjustable.

**Other limits:** record payload up to **10 MiB** (raised from 1 MiB; large records burst against the 1 MB/s per-shard rate), `PutRecords` up to 500 records, retention 24 hours by default and up to 365 days.

**What they probe next:** KCL lease table in DynamoDB and checkpointing (at-least-once, so consumers must be idempotent), Lambda's `ParallelizationFactor` (up to 10 concurrent batches per shard, still ordered per key), and Kinesis vs MSK (see Q9).

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-kinesis-shard-scaling.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Kinesis Shard Allocation & Resharding — partition key hashing, hot key throttling, and split to redistribute load — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 8. Kinesis Enhanced Fan-Out & EFO

**Q:** "You have 5 consumer applications consuming from the same Kinesis stream. Each consumer has 2MB/s read throughput. With 10 shards, your throughput is 20MB/s read. How does Enhanced Fan-Out (EFO) change this?"

### Answer

!!! tip "30-second answer"
    Without EFO, all consumers **share** 2 MB/s and 5 `GetRecords` calls per second per shard. Five consumers on 10 shards split 20 MB/s, about 4 MB/s each, and each polls roughly once a second, so latency is around a second. With EFO each registered consumer gets its **own** 2 MB/s per shard, pushed over an HTTP/2 `SubscribeToShard` connection: 5 × 10 × 2 = 100 MB/s total and ~70 ms propagation. You pay per consumer-shard-hour and per GB retrieved (no EFO premium under On-demand Advantage).

**Shared throughput vs EFO:**

| | Shared (`GetRecords`) | Enhanced fan-out (`SubscribeToShard`) |
|---|---|---|
| Read capacity | 2 MB/s and 5 calls/s per shard, shared by all consumers | 2 MB/s per shard **per consumer** |
| Model | Pull | Push over HTTP/2 (subscription renewed every 5 minutes) |
| Typical propagation delay | ~200 ms with one consumer; grows as consumers compete for the 5 calls/s | ~70 ms |
| Cost | Included in shard/stream price | Extra per consumer-shard-hour and per GB (provisioned and On-demand Standard) |
| Max consumers | No hard limit, but they starve each other | 20 registered consumers per stream (50 with On-demand Advantage) |

**When to use EFO:**

- Three or more consumers on the same stream, or any consumer that needs sub-200 ms latency.
- A consumer that must not be slowed by a batch job reading from the same stream.

**When not to:** one or two consumers that tolerate a second of lag; the shared model is cheaper. An alternative to many EFO consumers is a single consumer (or Firehose) that fans out to SQS/SNS/EventBridge.

**Failure modes:**

- A slow EFO consumer only falls behind itself; it cannot throttle others. But the stream's retention period is still the deadline for catching up.
- `ReadProvisionedThroughputExceeded` in the shared model usually means too many consumers or a polling loop without backoff.
- Lambda supports EFO by passing the consumer ARN in the event source mapping.

**What they probe next:** iterator age (`GetRecords.IteratorAgeMilliseconds`) as the lag metric to alarm on, and how you'd replay (`AT_TIMESTAMP` iterator, within retention).

---

## 9. Amazon MQ vs SQS vs Kinesis

**Q:** "Your team needs a message broker for both point-to-point and pub/sub patterns. Some services use JMS, others use HTTP APIs. Compare Amazon MQ (ActiveMQ/RabbitMQ), SQS, SNS, and Kinesis."

### Answer

!!! tip "30-second answer"
    Use **SQS/SNS** for new cloud-native work: serverless, effectively unlimited scale, nothing to patch. Use **Amazon MQ** when existing code speaks JMS, AMQP, STOMP, MQTT or OpenWire and you want to migrate without rewriting; it is a managed broker on instances you size, so throughput and HA are bounded by the broker. Use **Kinesis** or **MSK** when you need a replayable, ordered log read by several independent consumers.

**Service comparison:**

| Service | Model | Protocols | Ordering | Replay | Scaling | Typical use |
|---|---|---|---|---|---|---|
| SQS | Queue (point-to-point) | AWS API (HTTPS) | Standard best-effort; FIFO per group | No (deleted on consume; DLQ redrive only) | Serverless | Work queues, decoupling, buffering |
| SNS | Push pub/sub | AWS API; delivers to SQS, Lambda, HTTP, email, SMS, mobile | FIFO topics per group | No (FIFO topics can archive and replay) | Serverless | Fan-out, notifications |
| EventBridge | Routed event bus | AWS API | None (classic); FIFO per event group on the newer bus | Archive/replay; retention on the newer bus | Serverless | Cross-team event routing, SaaS and AWS events |
| Kinesis Data Streams | Partitioned log | AWS API / KCL | Per shard | Yes, 24 h to 365 days | Shards or on-demand | Streaming analytics, clickstream, CDC |
| Amazon MSK | Kafka log | Kafka protocol | Per partition | Yes, configurable (tiered storage) | Brokers, or MSK Serverless / Express brokers | Kafka ecosystem, Kafka Connect, high-throughput streaming |
| Amazon MQ (ActiveMQ) | Broker: queues and topics | JMS, OpenWire, AMQP 1.0, STOMP, MQTT, WebSocket | Per queue | No | Vertical; network of brokers | Lift-and-shift of JMS apps |
| Amazon MQ (RabbitMQ) | Broker: exchanges and queues | AMQP 0-9-1 | Per queue | No | Vertical; 3-node cluster for HA | Existing RabbitMQ apps, complex routing |

**Amazon MQ specifics:**

- ActiveMQ HA is an **active/standby** pair across two AZs on shared storage (EFS); failover takes on the order of a minute and clients must use the failover transport URI.
- RabbitMQ HA is a 3-node **cluster** across AZs with quorum queues.
- You choose instance size and patch windows; it is not serverless and does not autoscale.
- For new IoT device fleets, AWS IoT Core is usually a better MQTT endpoint than a broker.

**Decision shortcuts:**

- Need replay or multiple independent readers at their own pace → Kinesis or MSK.
- Need per-message ack, visibility timeout, DLQ, no capacity planning → SQS.
- Need existing protocol compatibility → Amazon MQ, then plan to strangle toward SQS/SNS if you want to stop running brokers.

**What they probe next:** Kinesis vs MSK (Kinesis is simpler and AWS-native with per-shard limits; MSK gives Kafka semantics, consumer groups, compaction, Kafka Connect and higher per-partition throughput, at more operational surface), and how you'd bridge MQ to SQS during a migration (EventBridge Pipes supports Amazon MQ as a source).

---

## 10. Event-Driven Architecture: Design Patterns

**Q:** "Your team is building a new event-driven platform. Five microservices need to communicate asynchronously. Design the event schema, routing, error handling, and observability strategy. What patterns do you use?"

### Answer

!!! tip "30-second answer"
    Publish domain events through a **transactional outbox** so a DB commit and its event can't diverge; route with EventBridge (cross-team) or SNS→SQS (high-throughput fan-out); give every consumer its own queue, DLQ and idempotency check; coordinate multi-step business flows as a **saga** (Step Functions orchestration when you need visibility, choreography when steps are few); and trace with a correlation ID propagated in every event. Assume at-least-once everywhere.

**Patterns:**

| Pattern | What it solves | AWS building blocks | Watch out for |
|---|---|---|---|
| **Transactional outbox** | Dual write (DB commit succeeds, publish fails, or the reverse) | Outbox table + CDC: DynamoDB Streams → Pipes → EventBridge, or Postgres → Debezium/DMS → MSK/Kinesis | Gives **at-least-once** publishing, not exactly-once; downstream must dedup |
| **Saga (choreography)** | Multi-service transaction without 2PC | Services react to each other's events via EventBridge | Hard to see the overall flow; cyclic dependencies |
| **Saga (orchestration)** | Same, with a central coordinator | Step Functions (Standard for long-running, with `.waitForTaskToken`) | Coordinator becomes a dependency; define compensations per step |
| **Event sourcing** | Audit trail, temporal queries, rebuildable read models | Append-only events table in DynamoDB (PK aggregate ID, SK version, conditional put for optimistic concurrency) + Streams to project read models | Kinesis is **not** a permanent event store (max 365-day retention); snapshots needed for long histories |
| **Idempotent consumer** | Duplicates from at-least-once delivery | Conditional write on an idempotency key; Powertools for AWS Lambda idempotency utility | Key must be stable across retries (business ID, not message ID, when producers can resend) |
| **Claim check** | Payloads above the size limit | Store in S3, send the pointer | Lifecycle the S3 objects; authorise consumer reads |
| **DLQ + redrive** | Poison messages | SQS DLQs, SNS subscription DLQs, EventBridge target DLQs, Lambda on-failure destinations | Alarm on DLQ depth > 0 and have a runbook; redrive only after the fix |

**Observability:**

- Correlation ID in every event; X-Ray/OpenTelemetry trace context propagation (SQS, SNS and EventBridge carry the `AWSTraceHeader`).
- Alarms: DLQ depth, `ApproximateAgeOfOldestMessage`, Kinesis iterator age, EventBridge `FailedInvocations` and `ThrottledRules`, Lambda errors and throttles.
- Lag is the user-visible SLO in async systems: measure "event created" to "effect visible" end to end, not just per hop.

**What they probe next:**

- *Ordering across services:* you only get it per key (FIFO group, shard, event group); design consumers to tolerate out-of-order events with version numbers and "last writer wins by version".
- *Backpressure:* queues absorb bursts, but a downstream DB still needs a cap (`MaximumConcurrency`, reserved concurrency, or a rate-limited consumer).
- *Schema ownership and evolution:* see Q6.

---

> *All 10 questions cover the full breadth of AWS messaging — from SQS polling mechanics to event-driven architecture patterns and service selection.*
