# ☁️ AWS Messaging — Staff-Level Interview Questions

> *10 questions covering SQS, SNS, EventBridge, Kinesis, Amazon MQ — every question expects principal engineer-level depth with production patterns for event-driven architectures.*

---

## Table of Contents

1. [SQS: Queue Types, Redrive, DLQ](#1-sqs-queue-types-redrive-dlq)
2. [SQS: Long Polling, Visibility Timeout, Batching](#2-sqs-long-polling-visibility-timeout-batching)
3. [SNS: Pub/Sub, Filter Policies, Message Attributes](#3-sns-pubsub-filter-policies-message-attributes)
4. [SNS + SQS: Fan-Out Pattern](#4-sns-sqs-fan-out-pattern)
5. [EventBridge: Event Bus, Rules, Pipes](#5-eventbridge-event-bus-rules-pipes)
6. [EventBridge Schema Registry & Events](#6-eventbridge-schema-registry-events)
7. [Kinesis Data Streams: Shards, Partition Keys, Limits](#7-kinesis-data-streams-shards-partition-keys-limits)
8. [Kinesis Enhanced Fan-Out & EFO](#8-kinesis-enhanced-fan-out-efo)
9. [Amazon MQ vs SQS vs Kinesis](#9-amazon-mq-vs-sqs-vs-kinesis)
10. [Event-Driven Architecture: Design Patterns](#10-event-driven-architecture-design-patterns)

---

## 1. SQS: Queue Types, Redrive, DLQ

**Q:** "Design a message processing pipeline where messages must be processed exactly once, in order, with automatic retry for failures. Compare standard queues, FIFO queues, and dead-letter queues. How does redrive work with DLQ?"

### Answer

**Queue Types Comparison:**

```yaml
Standard Queue:
  Throughput: unlimited (nearly)
  Ordering: best-effort (no guarantee)
  At-least-once delivery: duplicates possible
  Use: high throughput, non-critical ordering

FIFO Queue:
  Throughput: 300 TPS with batching, 3000 with batching
  Ordering: guaranteed (FIFO within message group)
  Exactly-once: deduplication by MessageDeduplicationId
  Use: order processing, banking, ledger entries

DLQ (Dead Letter Queue):
  After N processing failures → message moved to DLQ
  maxReceiveCount: 3-5 typical
  Redrive: manually or via DLQ redrive (move back to source queue)

# FIFO deduplication:
# Based on MessageDeduplicationId (content-based deduplication)
# 5-minute deduplication window (automatic)
{
    QueueUrl: 'https://sqs.us-east-1.amazonaws.com/123456789/MyQueue.fifo',
    MessageBody: '{"orderId": "ORD-123", "action": "create"}',
    MessageGroupId: 'order-123-group',
    MessageDeduplicationId: 'dedup-abc123'  // Prevents duplicates in 5-min window
}
```

## 2. SQS: Long Polling, Visibility Timeout, Batching

**Q:** "Your SQS consumer polls the queue and gets only 1-2 messages per call, wasting network round trips. How does long polling help? How does visibility timeout interact with message processing failures?"

### Answer

**Long Polling:**

```
receiveMessageWaitTimeSeconds: 0  → short polling (default)
  - Returns immediately even if queue is empty
  - Wastes network calls (frequent empty responses)
  - More API calls ($$$)

receiveMessageWaitTimeSeconds: 20  → long polling (recommended)
  - Waits up to 20 seconds for messages
  - Returns batch of messages (up to 10)
  - Fewer API calls (cheaper!)
  - Real-time: as soon as message arrives, response returns

Cost comparison:
  Short polling (1M empty polls): 1M × $0.0000004 = $0.40
  Long polling (100K polls): 100K × $0.0000004 = $0.04 (90% cheaper!)
  Minimum: waitTimeSeconds = 1 (long polling starts at 1s)
```

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

**Filter Policies:**

```json
// SNS message:
{
  "default": "fallback",
  "event_type": "order_placed",
  "order_id": "ORD-123",
  "amount": 99.99
}

// Payment service subscription filter:
{
  "event_type": ["payment_captured", "payment_failed"]
  // Only receives: payment_captured and payment_failed events
}

// Inventory service subscription filter:
{
  "event_type": ["order_placed", "order_cancelled"]
  // Only receives: order_placed and order_cancelled events
}

// Audit service: no filter → receives ALL events

// Complex filter policies:
{
  "event_type": ["order_placed"],
  "amount": [{ "numeric": [">=", 500] }]
  // Only high-value orders (>= $500)
}

// Message filtering attributes:
// String, String.Array, Number, Binary
// Matching: Exact, Prefix, Numeric, Anything but, Exists
```

## 4. SNS + SQS: Fan-Out Pattern

**Q:** "Design a fan-out pattern using SNS to SQS for an order processing pipeline. Three services need to process each order: payment (must succeed), inventory (best-effort), and notification (async). How do you handle failure isolation?"

**Fan-Out Architecture:**

```
SNS Topic: order-events
    │
    ├── SQS Queue: payment-queue
    │   └── Lambda: payment-processor
    │       └── SQS DLQ: payment-dlq (if payment fails)
    │
    ├── SQS Queue: inventory-queue
    │   └── Lambda: inventory-updater
    │       └── SQS DLQ: inventory-dlq
    │
    └── SQS Queue: notification-queue
        └── Lambda: notification-sender
            └── SQS DLQ: notification-dlq

Failure isolation:
  - Payment failure → retry 3× → DLQ → manual intervention
  - Inventory failure → retry → DLQ → order STILL delivered
  - Notification failure → DLQ → SNS email alert
  - Each service manages its own retry independently
  - SNS message is delivered ONCE to each subscription
```

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

**EventBridge Architecture:**

```
┌──────────────────────────────────────────────┐
│           EventBridge Event Bus               │
│  Default Bus (AWS services → events)          │
│  Custom Bus (application events)              │
│  Partner Bus (SaaS: Datadog, PagerDuty, etc.)  │
│                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  Rule 1  │  │  Rule 2  │  │  Rule 3  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │              │              │          │
│  ┌────▼────┐  ┌─────▼────┐  ┌─────▼────┐     │
│  │ Lambda  │  │ SQS Queue│  │ Step Fun.│     │
│  └─────────┘  └──────────┘  └──────────┘     │
└──────────────────────────────────────────────┘

Pipes vs Rules:
  Pipes: single source → single target (simpler, cheaper)
  Rules: event bus → filter + transform → target (complex routing)

Pipe example:
  Source: DynamoDB Stream → Filter: INSERT events only
  → Enrich: lookup customer data → Target: SQS queue
  One configuration, no code!

Rule example:
  Source: Bus → Pattern: {"source": ["order"], "detail-type": ["OrderPlaced"]}
  → Target: multiple targets (fan-out with different patterns)
```

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

**Schema Registry:**

```json
// Schema discovery:
// EventBridge automatically discovers schemas from events
// OpenAPI format (JSON Schema Draft 4)

// Version: order-placed@v1 → v2 (add optional field)
{
  "openapi": "3.0.0",
  "info": { "version": "2", "title": "OrderPlaced" },
  "components": {
    "schemas": {
      "OrderPlaced": {
        "type": "object",
        "properties": {
          "orderId": { "type": "string" },
          "amount": { "type": "number" },
          "customerId": { "type": "string" },
          "discountCode": { "type": "string" }  // NEW: optional field
        },
        "required": ["orderId", "amount", "customerId"]
      }
    }
  }
}

// Code generation: download schema → generate TypeScript/Java/Python types
// npm install @aws-sdk/eventbridge-schemas
// → generates OrderPlacedEvent type with full type safety!
```

## 7. Kinesis Data Streams: Shards, Partition Keys

**Q:** "You're streaming 50MB/s of clickstream data into Kinesis. How many shards do you need? How does partition key affect shard distribution? What happens when a shard is hot?"

**Shard Sizing:**

```
1 shard: 1MB/s write, 2MB/s read, 1000 records/s write

For 50MB/s:
  Write capacity: 50 shards (50 × 1MB/s = enough)
  Read capacity: 50 shards × 2MB/s = good
  But: 1000 records/s per shard = 50 × 1000 = 50K records/s
  For 50MB/s with 1KB records: 50K records/s → matches!

Partition key → shard mapping:
  Shard = hash(key) mod N_shards
  Hot key: all records with same key → single shard (1MB/s limit)
  Solution: use composite key with high cardinality
  
Resharding:
  Split shard: hot shard → 2 shards (double capacity)
  Merge shards: underutilized shards → 1 shard
  Limits: 2 splits/merges per 24h per shard
         Total shards per stream: default 500 (soft limit)
```

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

**EFO vs Standard:**

```
Standard (shared throughput):
  - All consumers share 2MB/s per shard
  - 10 shards × 2MB/s = 20MB/s TOTAL for all consumers
  - Each consumer gets average: 20/5 = 4MB/s
  - But: one consumer can consume at 2MB/s max per shard
  
  - Polling model: GetRecords (HTTP request)
  - Latency: 200ms average

Enhanced Fan-Out (dedicated throughput):
  - Each consumer gets 2MB/s per shard DEDICATED
  - 10 shards × 2MB/s × 5 consumers = 100MB/s total!
  - Each consumer gets full throughput
  
  - Push model: SubscribeToShard (HTTP/2 stream)
  - Latency: 70ms average (pushed as soon as data arrives)
  - Cost: $0.018 per shard-hour per consumer (vs $0.015 standard)
  
  Use EFO when:
  - Multiple consumers need full throughput
  - Sub-100ms latency required
  - Cost is acceptable
```

## 9. Amazon MQ vs SQS vs Kinesis

**Q:** "Your team needs a message broker for both point-to-point and pub/sub patterns. Some services use JMS, others use HTTP APIs. Compare Amazon MQ (ActiveMQ/RabbitMQ), SQS, SNS, and Kinesis."

**Service Comparison:**

```yaml
Service       | Protocol | Ordering | Throughput  | Use Case
--------------|----------|----------|-------------|-----------------------
SQS           | HTTP API | Best-effort/FIFO | Unlimited | Simple queue, decoupling
SNS           | HTTP API | Pub/Sub  | Unlimited   | Fan-out, push, mobile
Kinesis       | SDK      | Per-shard | 1MB/s per shard | Streaming, analytics
Amazon MQ     | JMS, AMQP, MQTT | Per-queue | Moderate | Migration, existing protocols

Amazon MQ (ActiveMQ):
  - Managed broker (EC2 instance behind the scenes)
  - Protocols: JMS, AMQP 1.0, MQTT, STOMP, OpenWire
  - Features: queues, topics, virtual topics, exclusive consumers
  - HA: active/standby pair (failover: 1-2 min)
  - Scalability: up to broker instance limits (not serverless)

  When to use Amazon MQ:
  - Existing JMS application → migrate without code changes
  - Need AMQP protocol (IoT devices)
  - Need MQTT for IoT
  - Need advanced routing (virtual topics, destinations)
  
  When to use SQS/SNS:
  - New application (no legacy constraints)
  - Need serverless (no capacity management)
  - Need high throughput (unlimited scaling)
  - Need built-in DLQ, redrive, batching
  
  When to use Kinesis:
  - Need replay (retain data for 7 days to 365 days)
  - Multiple consumers with different processing speeds
  - Need time-based analytics (windowed aggregations)
  - Need record ordering within a partition
```

## 10. Event-Driven Architecture: Design Patterns

**Q:** "Your team is building a new event-driven platform. Five microservices need to communicate asynchronously. Design the event schema, routing, error handling, and observability strategy. What patterns do you use?"

**Patterns:**

```yaml
Pattern 1: Event Sourcing
  - Store events as source of truth (not current state)
  - Project current state from events
  - Use Kinesis or DynamoDB Streams as event store
  - Services: EventStore → Projector (build read model)

Pattern 2: Saga (Choreography)
  - Each service listens for events and emits events
  - No central orchestrator
  - Compensation: on failure, emit compensating event
  - Example: Order → Payment → Inventory → Shipping

Pattern 3: Transactional Outbox (reliable publishing)
  - Database transaction: write event to OUTBOX table
  - Outbox publisher (Kafka Connect / Debezium / DynamoDB Streams):
    → Read outbox → publish to SNS/EventBridge
  - Guarantees: exactly-once publishing (no partial failures)

Pattern 4: Dead letter + monitoring
  - SQS DLQ, SNS DLQ, EventBridge DLQ
  - CloudWatch alarm on DLQ depth > 0
  - Automated: DLQ redrive to source queue
```

---

> *All 10 questions cover the full breadth of AWS messaging — from SQS polling mechanics to event-driven architecture patterns and service selection.*
