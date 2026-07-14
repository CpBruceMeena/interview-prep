# Pub-Sub Messaging System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Event-driven architecture, scalability, delivery guarantees, ordering

---

## Question 1: Core Design
**Interviewer:** *"Design a publish-subscribe messaging system."*

### 🎯 Expected Answer

**Core Abstractions:**
```python
class Message:
    def __init__(self, topic, payload, priority=MessagePriority.NORMAL):
        self._message_id = uuid.uuid4()
        self._topic = topic
        self._payload = payload
        self._priority = priority  # For priority queue ordering
        self._timestamp = datetime.now()

class Topic:
    def __init__(self, name):
        self._name = name
        self._subscribers: Dict[str, Subscriber] = {}
        self._message_queue = PriorityQueue()  # Ordered by priority
```

**Observer Pattern is the core:**
```python
class Subscriber(ABC):
    @abstractmethod
    def on_message(self, message: Message): pass

# In Topic:
def publish(self, message: Message):
    self._message_queue.put(message)  # Enqueue with priority

def deliver(self):
    while not self._message_queue.empty():
        msg = self._message_queue.get()
        for sub in self._subscribers.values():
            sub.on_message(msg)
```

**Production Considerations:**
- **Message persistence**: Write to disk/db before acknowledging
- **Idempotent subscribers**: Same message delivered twice should produce same result
- **Dead letter queues**: Failed messages go to DLQ for manual inspection

---

## Question 2: Delivery Semantics

| Guarantee | Meaning | Implementation |
|-----------|---------|---------------|
| **At-most-once** | Message delivered ≤1 time | Fire and forget. No ACK. |
| **At-least-once** | Message delivered ≥1 time | ACK mechanism. Retry on timeout. |
| **Exactly-once** | Message delivered =1 time | ACK + dedup + idempotent subscriber |

**Exactly-once is the hardest.** No distributed system can guarantee exactly-once delivery with 100% certainty (FLP impossibility). What we do instead is **idempotent consumers** + **deduplication**:

```python
class MessageBroker:
    def publish(self, topic, payload, dedup_key=None):
        if dedup_key and dedup_key in self._processed_ids:
            return  # Already processed
        msg = Message(topic, payload, message_id=dedup_key)
        self._topics[topic].publish(msg)
```

---

## Question 3: Scalability (Millions of Msgs/Sec)

**Architecture:**
```
            ┌──────────────┐
Publisher ──▶   Load       ──▶ Partition 1 ──▶ Consumer Group A
Publisher ──▶   Balancer   ──▶ Partition 2 ──▶ Consumer Group A
Publisher ──▶              ──▶ Partition 3 ──▶ Consumer Group B
            └──────────────┘
```

- **Partitioned topics**: Messages with same key go to same partition (maintains order per key)
- **Consumer groups**: Multiple consumers share partitions for parallel processing
- **Batching**: Batch messages for efficient network/storage I/O

---

## Question 4: Ordering Guarantees
**Interviewer:** *"How do you ensure messages within a topic are processed in order?"*

### 🎯 Answer

**Guarantee ordering per partition, not globally:**
```python
# Producer sends with partition key
def send(topic, key, message):
    partition = hash(key) % num_partitions
    partitions[partition].send(message)
```

**Kafka uses in-order per partition, reset on leader election.**  
**RabbitMQ uses per-queue ordering, lost on queue mirroring.**

**Trade-off:** Ordering imposes performance costs — you can't parallelize within a partition.

---

## Question 5: Advanced Features

| Feature | Implementation |
|---------|---------------|
| **Scheduled messages** | Store in ordered list, deliver when timestamp reached |
| **Batch processing** | Accumulate messages, flush on size/time trigger |
| **Message TTL** | Discard messages older than TTL, track in headers |
| **Dead letter queue** | After N retries, move to DLQ for manual processing |
| **Schema registry** | Avro/Protobuf schemas, validate on publish/subscribe |
| **Wildcard topics** | `orders.*` matches `orders.created`, `orders.updated` — regex match |

---

## Question 6: Backpressure & Flow Control

**Push vs Pull:**
- **Push (traditional pub-sub)**: Server pushes to subscribers — risk of overwhelming slow consumers
- **Pull (Kafka-style)**: Consumers pull when ready — natural backpressure

**Strategies:**
1. **Sliding window**: Subscriber specifies max unprocessed messages
2. **Rate limiting per subscriber**: Slow feed for slow consumers
3. **Buffer overflow policies**: Block publisher → Drop oldest → Dead letter

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Observer** | Core pub-sub | Decoupled publisher/subscriber |
| **Strategy** | DeliveryStrategy | Sync, async, reliable delivery |
| **Decorator** | FilteringSubscriber | Add filtering without modifying subscriber |
| **Facade** | MessageBroker | Unified interface |
| **Factory** | Topic creation | Config-driven topic setup |
| **Singleton** | Broker | Single point of management |
