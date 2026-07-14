# 🏗️ Pub-Sub Messaging System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Event-driven architecture, Kafka-style design, delivery semantics

---

## 1. SYSTEM OVERVIEW

**Purpose:** Scalable publish-subscribe messaging system for event-driven microservices with ordering guarantees and delivery semantics.

**Scale:** 10M messages/second peak, 100K topics, 1M subscribers, 99.99% durability

**Users:** Service developers (publishers/subscribers), Platform operators

**Use Cases:** Event sourcing, Log aggregation, Stream processing, Service decoupling, Real-time analytics

**Constraints:** At-least-once delivery, per-partition ordering, <50ms end-to-end latency, zero data loss

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Producer ──▶  ┌──────────────────────────────────────┐
              │          Kafka / Event Bus            │
Producer ──▶  │                                      │
              │  ┌──────┐ ┌──────┐       ┌──────┐    │
Producer ──▶  │  │Partn │ │Partn │  ...  │Partn │    │
              │  │  1   │ │  2   │       │  N   │    │
              │  └──┬───┘ └──┬───┘       └──┬───┘    │
              │     │        │              │        │
              └─────┼────────┼──────────────┼────────┘
                    │        │              │
              ┌─────▼──┐ ┌──▼────┐    ┌────▼───┐
              │Consumer│ │Consumer│    │Consumer│
              │ Group A│ │ Group B│    │Group C│
              └────────┘ └────────┘    └────────┘
                         │
              ┌──────────▼──────────┐
              │  ZooKeeper / KRaft  ││  (Cluster metadata) │
  └─────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/pub-sub-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Pub-Sub Sequence — Publisher → Topics → Subscribers → Message Delivery. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Message Broker (Kafka-like, C++/Java)
- Append-only commit log per partition
- Configurable retention (time or size)
- Replication factor = 3 for durability
- Leader-follower per partition

**🔴 Interview Question:** *"How does Kafka guarantee ordering within a partition?"*

**✅ Answer:**
1. **Partition = ordered sequence:** Messages appended sequentially — offset = position in log
2. **Single leader per partition:** All writes go to leader, followers replicate in order
3. **Producer acknowledges:** `acks=all` ensures all replicas have committed before confirming
4. **Consumer reads sequentially:** From offset 0 forward. Parallelism comes from multiple partitions, not concurrent reads within one partition.
5. **Key insight:** If you need global ordering, use a single partition (sacrifice throughput). For most cases, order per key (e.g., per user_id) is sufficient.

---

### Producer API
- Batch messages for throughput (up to 1MB or 16KB)
- Idempotent producer (automatic retry without duplicates)
- Configurable durability (`acks=0|1|all`)

**🔴 Interview Question:** *"How do you achieve exactly-once semantics in pub-sub?"*

**✅ Answer:** Exactly-once in distributed systems is impossible (FLP theorem). Instead, we implement **idempotent consumers**:
1. **Producer idempotency:** Include producer_id + sequence_number in each message. Broker deduplicates duplicates.
2. **Consumer idempotency:** Process messages idempotently — if same message received twice, second processing produces same result.
3. **Transactional API:** `beginTransaction() → send() → commitTransaction()` — atomic writes across partitions.
4. **Read-process-write pattern:** Consumer reads offset, processes, writes result to output topic — all in one transaction.

---

### Consumer Groups
- Each partition assigned to exactly one consumer in group
- Rebalancing on consumer join/leave
- Offset management (auto-commit or manual)

**🔴 Interview Question:** *"What happens during consumer rebalancing?"*

**✅ Answer:**
1. Consumer joins/leaves → coordinator detects via heartbeat timeout
2. **Stop phase:** All consumers in group stop processing
3. **Revoke phase:** Partitions revoked from current owners
4. **Assign phase:** Group coordinator assigns partitions using partition.assignment.strategy
5. **Resume phase:** Consumers seek to committed offsets and resume
6. **Duration:** Typically 5-30 seconds. Use **static group membership** (unique member IDs) to avoid rebalance on restart.

---

## 4. DATA MODEL (Storage Layer)

```sql
-- Internal metadata (not the actual messages)
CREATE TABLE topics (
    id SERIAL, name TEXT UNIQUE, partitions INT, replication_factor INT
);
CREATE TABLE consumer_groups (
    id SERIAL, group_id TEXT, topic_id INT,
    partition INT, offset BIGINT
);
```

**Actual messages stored as segments on disk:**
```
/data/kafka/topics/orders/partition-0/00000000000000000000.log
/data/kafka/topics/orders/partition-0/00000000000000100000.log  (after roll)
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | Append-only log | Sequential I/O is 100x faster than random I/O |
| Partitioning | By key hash | Ensures per-key ordering |
| Replication | Leader-follower (ISR) | ISR = in-sync replicas; tolerates f failures with 2f+1 |
| Retention | Time + size based | Delete old segments; compacted topics for latest-value semantics |

---

## 6. SCALABILITY

**Bottleneck:** Disk I/O per partition, network bandwidth

**Solution:** Partition = unit of parallelism. More partitions = more parallelism. Add brokers to distribute partitions. 10M msgs/sec ÷ 1M per broker = 10 brokers.

**Availability:** 99.99% with replication factor 3. Losing leader → ISR follower promotes in <10 seconds.

---

## 7. COST (Monthly)

| Component | Nodes | Cost |
|-----------|-------|------|
| Broker nodes (i3en.2xlarge) | 10 | $6,000 |
| ZooKeeper/KRaft (m5.large) | 3 | $450 |
| Monitoring | — | $300 |
| **Total** | | **$6,750** |
