# 📨 Kafka — Staff-Level Interview Questions

> *12 questions covering Kafka internals, producer/consumer design, replication, and operational excellence — every question expects principal engineer-level depth with production code and failure analysis.*

---

## Table of Contents

1. [Log Segment Structure & Storage Internals](#1-log-segment-structure--storage-internals)
2. [ISR Replication & Leader Election](#2-isr-replication--leader-election)
3. [Consumer Group Rebalancing](#3-consumer-group-rebalancing)
4. [Exactly-Once Semantics & Transactions](#4-exactly-once-semantics--transactions)
5. [Producer: Batching, Compression, Idempotency](#5-producer-batching-compression-idempotency)
6. [Kafka Connect & Connector Design](#6-kafka-connect--connector-design)
7. [Kafka Streams: Stateful Processing](#7-kafka-streams-stateful-processing)
8. [Disk I/O & Page Cache Optimization](#8-disk-io--page-cache-optimization)
9. [Cluster Scaling & Partition Reassignment](#9-cluster-scaling--partition-reassignment)
10. [Monitoring, Metrics & Alerting](#10-monitoring-metrics--alerting)
11. [Security: TLS, SASL, ACLs](#11-security-tls-sasl-acls)
12. [Kafka vs Pulsar vs Redpanda](#12-kafka-vs-pulsar-vs-redpanda)

---

## 1. Log Segment Structure & Storage Internals

**Q:** "Trace the lifecycle of a Kafka message from producer send to consumer read. What happens at the storage layer? How does Kafka achieve 1GB/s+ write throughput on commodity hardware?"

**What They're Really Testing:** Whether you understand Kafka's storage model — it's not a message queue, it's a write-ahead log. The performance comes from sequential I/O and zero-copy transfers.

### Answer

**Message Lifecycle (Storage Layer):**

```
Producer → Topic "orders", Partition 0

Logical view:
┌─────────────────────────────────────────────────────────────┐
│ Partition 0 (immutable, ordered sequence of records)         │
│ Offset:  0         1         2         3         4         5 │
│         ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
│         │ msg1 │  │ msg2 │  │ msg3 │  │ msg4 │  │ msg5 │  │ ... │
│         └─────┘  └─────┘  └─────┘  └─────┘  └─────┘  └─────┘
│                                                     ↑
│                                               Tail (active writes)
└─────────────────────────────────────────────────────────────┘

Physical storage (on disk):
/data/kafka/orders-0/
├── 00000000000000000000.log        ← Segment 1 (offsets 0-999)
├── 00000000000000000000.index      ← Offset → file position mapping
├── 00000000000000000000.timeindex  ← Timestamp → offset mapping
├── 00000000000000001000.log        ← Segment 2 (offsets 1000-1999)
├── 00000000000000001000.index
├── 00000000000000001000.timeindex
└── 00000000000000002000.log        ← Active segment (currently writing)
```

**How Kafka Achieves 1GB/s+ Write Throughput:**

```yaml
1. Sequential I/O:
   - Writes go to the END of the active segment (sequential, not random!)
   - On HDD: ~150MB/s sequential, ~1MB/s random
   - On NVMe: ~5GB/s sequential, ~500MB/s random

2. Page cache utilization:
   - Kafka reads/writes through the OS page cache (does NOT call fsync on every write!)
   - Producer writes → page cache (microseconds) → background flush (ms)

3. Zero-copy transfer (sendfile):
   - Consumer read WITHOUT zero-copy: Disk → Page Cache → App Buffer → Socket Buffer → NIC (4× copy)
   - Consumer read WITH sendfile(): Page Cache → NIC via DMA (1× copy, 0 context switches!)

4. Batch compression:
   - Producer compresses batches BEFORE sending (CPU for network savings)
   - zstd typically gives 5-10× compression ratio for JSON
```

**Segment Rolling Configuration:**

```properties
log.segment.bytes=1073741824          # 1GB (default), or
log.roll.ms=604800000                 # 7 days (whichever comes first)
log.retention.hours=168               # 7 days (default)
log.cleanup.policy=delete             # Delete old segments; or "compact"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Sequential I/O** | Explains WHY sequential writes are so much faster (no seek, full stripe width) |
| **Zero-copy** | Can diagram sendfile() vs traditional read/write path with copy counts |
| **Page cache** | Understands that Kafka doesn't fsync on every write — relies on OS page cache |
| **Segment lifecycle** | Explains segment rolling, index files, and compaction vs deletion |

---

## 2. ISR Replication & Leader Election

**Q:** "You're running a Kafka cluster with replication.factor=3, min.insync.replicas=2. A broker fails. Walk through what happens: leader election, ISR changes, and data durability guarantees."

**What They're Really Testing:** Whether you understand the ISR protocol in detail — the precise conditions for committed writes, leader election, and the durability vs availability trade-off.

### Answer

**ISR Protocol:**

```
Topic: orders, Partition: 0, Replicas: [Broker1(leader), Broker2, Broker3]

Normal state:
  ISR={1,2,3}  HW=10  LEO=11 (leader and followers all at LEO 11)

Write flow:
  1. Producer sends to leader (Broker1)
  2. Leader appends to its log, advances LEO
  3. Followers pull new data via FETCH requests, append, send ACK
  4. Leader advances HW = min(LEO of all ISR members)
  5. Leader returns ACK to producer when HW ≥ required offset
  6. Consumers can only read up to HW (not LEO!)

Broker2 crashes:
  After replica.lag.time.max.ms (default 30s) → removed from ISR
  ISR={1,3} → min.insync.replicas=2 is satisfied (2 replicas in ISR)
  If Broker1 also fails → ISR={...nothing} → min.isr can't be met
  → Writes return NotEnoughReplicasException (blocked!)

Unclean leader election (unclean.leader.election.enable=true):
  If NO replicas are in-sync, pick any replica (even if far behind)
  → Can cause data LOSS from the chosen replica's gap
  → Can cause data DIVERGENCE (ordering violation)
```

**Diagnostic Commands:**

```bash
kafka-topics --describe --topic orders --bootstrap-server kafka:9092
# Look for ISR list (Isr: 1,3 instead of 1,2,3)

kafka-topics --describe --under-replicated-partitions --bootstrap-server kafka:9092
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ISR mechanics** | Explains HW, LEO, and the ack condition precisely |
| **min.isr behavior** | Knows that writes are REJECTED (not queued) when min.isr can't be met |
| **Unclean election** | Can articulate the exact danger: data loss AND ordering violation |
| **Diagnosis** | Knows which metrics/CLI commands to check for ISR issues |

---

## 3. Consumer Group Rebalancing

**Q:** "A 50-node Kafka consumer group experiences a 30-second processing pause every time a new consumer joins or leaves. How did cooperative rebalancing (KIP-429) improve this? What about static group membership (KIP-345)?"

**What They're Really Testing:** Whether you understand consumer group rebalancing at the protocol level — including the stop-the-world problem and the incremental solutions.

### Answer

**Eager Rebalancing (Pre-KIP-429):**
ALL consumers stop processing → revoke ALL partitions → reassign → ALL resume. 30s pause.

**Cooperative Rebalancing (KIP-429, Kafka 2.4+):**
Phase 1: Consumers revoke ONLY partitions they give up → Phase 2: Only affected partitions reassigned. If 1 new consumer joins 50-consumer group, only ~2 consumers pause (~0.5s).

**Static Group Membership (KIP-345, Kafka 2.3+):**

```properties
group.instance.id=consumer-1     # Stable ID
```

Rolling restart: same group.instance.id → NO rebalance! Consumer rejoins within session.timeout.ms → resumes processing immediately.

**Protocol Detail:**

```
Standard rebalance protocol:
  1. Consumer sends JoinGroup request to Group Coordinator
  2. Coordinator picks first joiner as leader (collects all subscriptions)
  3. Leader computes assignment (range, round-robin, sticky)
  4. Leader sends SyncGroup with assignment to coordinator
  5. Coordinator broadcasts assignment to all consumers
  6. All consumers receive → start/stop partition processing

Cooperative rebalance (KIP-429):
  Step 3: Leader computes "revocation only" assignment
  Step 4-5: Consumers revoke only the partitions they lose
  Step 6: Second JoinGroup → leader computes final assignment
  → Total partitions revoked = Total_new_assignments - Total_consumers_needing_revocation
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Eager vs cooperative** | Can diagram the two protocols and explain the pause difference |
| **Static membership** | Knows group.instance.id eliminates rebalance during planned restarts |
| **Sticky assignor** | Mentions that cooperative needs the StickyAssignor |

---

## 4. Exactly-Once Semantics & Transactions

**Q:** "Design a payment processing pipeline where each transaction must be processed exactly once. How does Kafka's exactly-once semantics work? Walk through the transaction protocol: coordinators, transaction markers, and zombie fencing."

**What They're Really Testing:** Whether you understand the EOS protocol at the transport level — idempotent producer, transactional coordinator, zombie fencing with epochs.

### Answer

```
Kafka EOS = idempotent producer + transactions + consumer offset transactional store

Idempotent Producer:
  producer.id + sequence_number per partition (stored in log)
  Duplicate → broker detects sequence number already seen → silently drops

Transaction Protocol:
  1. Producer sends InitProducerId to Transaction Coordinator
  2. Producer starts transaction: begin_transaction()
  3. All messages in this transaction include a marker:
     - transactional_id (unique producer instance)
     - producer_epoch (monotonically increasing, fences zombies!)
  4. Producer sends messages to multiple partitions
  5. Producer commits: EndTransaction(commit)
  6. Transaction coordinator writes COMMIT/PREPARE markers to __transaction_state
  7. Coordinator writes markers to ALL affected partitions
  8. Consumers see COMMIT marker → make messages visible

Zombie fencing:
  If producer crashes and restarts with same transactional_id:
  - New producer gets higher producer_epoch
  - Old producer (zombie) has lower epoch → broker REJECTS its messages
  - Prevents duplicate writes from crashed-but-still-running producers

Consumer read_committed:
  isolation.level=read_committed
  Consumer filters out messages between BEGIN and COMMIT/ABORT markers
```

**Write Path Code:**

```python
from kafka import KafkaProducer

producer = KafkaProducer(
    bootstrap_servers='kafka:9092',
    transactional_id='payment-pipeline-1',
    acks='all',
    batch_size=16384,
    linger_ms=5,
    compression_type='zstd'
)

# Initialize the transaction coordinator
producer.init_transactions()

def process_payment(payment_event: dict):
    try:
        producer.begin_transaction()

        # Send to payment processing topic
        producer.send('payment-events', payment_event)

        # Send to audit trail
        producer.send('audit-trail', {'type': 'payment', 'data': payment_event})

        # Commit transaction atomically across both partitions
        producer.commit_transaction()
    except Exception:
        producer.abort_transaction()
        raise
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **EOS building blocks** | Explains idempotent producer + transactions as layered solutions |
| **Epoch fencing** | Understands producer_epoch prevents zombie writes |
| **Read-committed isolation** | Knows consumer must set isolation.level=read_committed |
| **Failure scenarios** | Can describe what happens when coordinator crashes mid-transaction |

---

## 5. Producer: Batching, Compression, Idempotency

**Q:** "Your Kafka cluster processes 500K messages/second through a single topic. Each message is ~1KB JSON. The producer is CPU-bound at 30% utilization but write throughput is capped at 100MB/s. Diagnose and fix. Walk through every producer tuning knob."

**What They're Really Testing:** Whether you understand the Kafka producer's internal batching pipeline — accumulator, compression, and the thread model.

### Answer

**Producer Internal Architecture:**

```
Application thread(s)
        │
        └─→ send(record) → RecordAccumulator (per-partition batches)
                │
                ├─→ batch.ready() → if batch.size full OR linger.ms expired
                │        │
                │        └─→ Sender thread (one per producer)
                │                │
                │                ├─→ Compress batch (zstd/gzip/lz4/snappy)
                │                ├─→ Attach sequence number (idempotent mode)
                │                │       │
                │                └─→ broker.send(request)
                │                        │
                │                        └─→ Response callback → dequeue batch
                │
                └─→ Producer.send() doesn't block! (unless buffer.memory exhausted)
```

**Diagnosis:** 100MB/s cap on a 1KB message topic means 100K messages/s — 5× below target. The 30% CPU is NOT the bottleneck.

**Root cause:** Single producer sender thread can't keep up. Each 1KB message with headers = 1.2KB on wire. 100MB/s / 1.2KB ≈ 85K msg/s. Sender thread saturates.

**Solution:** Increase batch size + parallelism:

```python
# Optimized producer config
producer = KafkaProducer(
    bootstrap_servers='kafka:9092',

    # Batch tuning
    batch_size=131072,        # 128KB (default: 16KB) - larger batches = fewer requests
    linger_ms=10,             # Wait 10ms for batch to fill (tunable latency)
    buffer_memory=134217728,  # 128MB total buffer (default: 32MB)
    max_request_size=1048576, # 1MB max request

    # Compression
    compression_type='zstd',  # CPU for network savings: 1KB → ~200B (5:1)
    # zstd.3 (default) vs lz4 (faster CPU, less compression)

    # Throughput
    acks='all',               # Wait for ISR replication
    max_in_flight_requests=5, # Pipeline 5 batches before waiting

    # Idempotency (enables EOS)
    enable_idempotence=True,

    # TCP tuning
    connections_max_idle_ms=600000,  # 10 min (avoid reconnects)
    request_timeout_ms=30000,
    retries=5,               # Retry on transient broker failures

    # Async parallelism
    # NOTE: A single producer has ONE sender thread
    # To scale beyond ~300MB/s, run multiple producers per machine
    # partition N producers across topic partitions
)
```

**Scaling Strategy:**

```
Single producer thread cap: ~200-300 MB/s (depending on batch size)

Options when exceeding this:
  1. Multiple producers in process: pool of producers, each handling subset of partitions
  2. Increase partition count: more parallelism on broker side
  3. Larger batches: 512KB-1MB batches hit 80%+ of network throughput
  4. Compression: zstd level 3 typically 4-5:1 on JSON = 5× effective throughput

Benchmarks (single producer, batch_size=128KB, zstd):
  - 1KB messages: ~250K msg/s, ~250 MB/s
  - 10KB messages: ~100K msg/s, ~1 GB/s
  - 100KB messages: ~20K msg/s, ~2 GB/s
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Accumulator model** | Understands send() queues, sender thread processes batches asynchronously |
| **Sender thread limit** | Knows there's ONE sender thread per producer — cannot parallelize within a single instance |
| **Compression trade-off** | Can compare zstd (5:1, CPU heavy) vs lz4 (2:1, CPU light) |
| **Batch sizing** | Knows that under-filled batches cause excessive requests, over-filled cause latency |

---

## 6. Kafka Connect & Connector Design

**Q:** "Design a Kafka Connect source connector that ingests from a PostgreSQL CDC stream using logical replication. How do you handle schema evolution, exactly-once delivery, and connector restart after 3 days of downtime?"

**What They're Really Testing:** Whether you understand Kafka Connect's framework — REST API, offset management, converters, and the single message transform (SMT) pipeline.

### Answer

**Connector Architecture:**

```
Source Connector (running in Connect worker):
  poll() → SourceRecord list → Offset commit → Repeat

  Each SourceRecord contains:
  - topic: target Kafka topic
  - key: row primary key (optional)
  - value: row payload (after Debezium-like transform)
  - sourcePartition: { "schema": "public", "table": "orders" }
  - sourceOffset:  { "lsn": "12345678", "txId": "42" }

  Connect framework:
  - Auto-commits offsets periodically (offset.flush.interval.ms)
  - Exactly-once: Connect tracks offset per partition
  - Restart: resumes from last committed offset

Debezium pattern:
  PostgreSQL logical replication slot → WAL decoder → change events
    CREATE/UPDATE/DELETE → SourceRecord with operation type + before/after
```

**Schema Evolution Handling:**

```python
# Using Avro + Schema Registry

# Schema evolution rules (Avro):
#   BACKWARD: new schema can read data written by old schema (default)
#   FORWARD: old schema can read data written by new schema
#   FULL: both directions
#   NONE: no compatibility checks

# Config for schema evolution:
converter.schema.registry.url=http://schema-registry:8081
value.converter=io.confluent.connect.avro.AvroConverter
value.converter.schema.registry.url=http://schema-registry:8081

# Multi-step schema evolution (safe):
# 1. ADD field with default value → BACKWARD compatible
# 2. REMOVE field → FORWARD compatible
# 3. Change field type → NEED intermediary schema (e.g., string→union[string,int]→int)
```

**Restart After 3 Days Downtime:**

```python
# Challenge: PostgreSQL replication slot may have grown during 3 days
# pg_replication_slots shows confirmed_flush_lsn far behind

# Recovery strategy:
# 1. Check slot lag:
SELECT slot_name, pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)
FROM pg_replication_slots;

# 2. If lag > disk capacity:
#    a. Create NEW replication slot
#    b. Snapshot current table state
#    c. Start connector from new slot + snapshot offset
#    d. Drop old slot

# 3. If lag is manageable:
#    - Connector resumes from saved offset (confirmed_flush_lsn)
#    - WAL segments between offset and current LSN must still exist
#    - wal_keep_size = 1GB (or more) for short downtimes
```

**Single Message Transforms (SMTs):**

```python
# Lightweight ETL without Kafka Streams
transforms=RenameField,InsertCountry,TimestampConverter
transforms.RenameField.type=org.apache.kafka.connect.transforms.ReplaceField$Value
transforms.RenameField.renames=order_id:id,customer_id:cid
transforms.InsertCountry.type=org.apache.kafka.connect.transforms.InsertField$Value
transforms.InsertCountry.static.field=country
transforms.InsertCountry.static.value=US
transforms.TimestampConverter.type=org.apache.kafka.connect.transforms.TimestampConverter$Value
transforms.TimestampConverter.field=created_at
transforms.TimestampConverter.target.type=unix
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Offset management** | Understands sourcePartition/sourceOffset pair for restart semantics |
| **Schema Registry** | Knows Avro evolution rules and how Connect handles schema changes |
| **CDC mechanics** | Explains PG logical replication slots, WAL, and the snapshot/bootstrap flow |
| **SMT pipeline** | Understands transforms run in order on each record before producing |

---

## 7. Kafka Streams: Stateful Processing

**Q:** "You need to implement a 1-hour rolling window aggregate that tracks user session duration across 50M daily active users. How would you implement this with Kafka Streams? How do you handle state store recovery when a Streams instance crashes?"

**What They're Really Testing:** Whether you understand Kafka Streams' stateful processing model — RocksDB-backed state stores, changelog topics, interactive queries, and the threading model.

### Answer

**Architecture:**

```python
# Kafka Streams topology:
# Input: "user-activity" (key: userId, value: ActivityEvent with timestamp)
# Output: "session-duration" (key: userId, value: SessionDuration)

StreamsBuilder builder = new StreamsBuilder();

KTable<Windowed<String>, Duration> sessionDurations = builder
    .stream("user-activity")
    .groupByKey()
    .windowedBy(TimeWindows.ofSizeWithNoGrace(Duration.ofHours(1)))
    .aggregate(
        SessionDuration::new,  # Initializer
        (key, value, aggregate) -> aggregate.add(value),  # Aggregator
        Materialized.<String, SessionDuration, WindowStore<Bytes, byte[]>>as(
                "session-store")          # RocksDB-backed state store
            .withRetention(Duration.ofDays(3))  # Keep 3 days of windows
    );

sessionDurations.toStream().to("session-duration-output");

# Internal state stores:
#   - session-store (RocksDB): local state for aggregations
#   - session-store-changelog (compact, compact-delete): fault tolerance
#     → Every state mutation also produces to changelog topic
#     → On restart: replay changelog from last checkpoint
```

**State Store Recovery:**

```
Instance A (active, partition 0-4):
  session-store/ (RocksDB)
     └── Checkpoint: offset 14235 in input topic

Instance A crashes:

Instance B takes over partition 0-4:
  1. Restore starting from checkpoint offset 14235
  2. Reads changelog topic "session-store-changelog" from offset 14235
  3. Replays ALL state changes into local RocksDB
  4. Once caught up with changelog end → resume processing from input

Optimization:
  standby.replicas=1
  - A warm standby replica maintains state in parallel
  - Failover: standby has state current to within milliseconds
  - No RocksDB replay needed → sub-second failover
```

**Interactive Queries:**

```python
# Query state stores directly from external services
// Get the store for a specific partition
ReadOnlyWindowStore<String, Duration> store = streams
    .store(StoreQueryParameters.fromNameAndType(
        "session-store", QueryableStoreTypes.windowStore()));

// Query by key
WindowStoreIterator<Duration> result = store.fetch(
    "user-12345",
    Instant.now().minus(1, ChronoUnit.HOURS),
    Instant.now());

// Access across partition: route by key → find hosting instance
HostInfo host = streams.metadataForKey(
    "session-store", "user-12345", Serdes.String().serializer());

if (host.equals(thisHost)) {
    // Local query
} else {
    // Remote query via RPC (gRPC/REST)
}
```

**Threading Model:**

```properties
# Task parallelism (NOT data parallelism)
num.stream.threads=4   # Default: 1

# Each thread runs a subset of tasks (max 1 thread per partition)
# Task: one partition of input topic → one state store (if stateful)
# Threads share JVM heap but have SEPARATE RocksDB instances

# If topic has 20 partitions, num.stream.threads=4:
#   Task assignment: 5 partitions per thread
#   Each thread has 5 RocksDB instances (one per partition)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **State store model** | Understands RocksDB local + changelog topic for fault tolerance |
| **Changelog replay** | Can explain how offset checkpointing + changelog replay enables recovery |
| **Standby replicas** | Knows standby.replicas eliminates replay cost on failover |
| **Interactive queries** | Understands how to query state stores externally across instances |

---

## 8. Disk I/O & Page Cache Optimization

**Q:** "Your Kafka cluster's page cache drops from 40GB to 2GB during a BGSAVE-like operation. Write throughput drops 80%. Diagnose the root cause. How do you isolate Kafka from other processes sharing the same OS?"

**What They're Really Testing:** Whether you understand Kafka's OS-level performance model — page cache as the primary performance layer, and how to isolate it from other processes.

### Answer

**Root Cause:** Another process (or Kafka's own compaction) triggered massive page cache eviction. Kafka's write path relies on the OS page cache for its speed:

```
Normal path: Producer → send() → RecordAccumulator → Sender thread → Socket send
  → Kernel allocates page cache pages → writes reach disk asynchronously via pdflush

When page cache is evicted:
  - Every write must allocate NEW pages (expensive)
  - Every read goes to disk (no cache hit)
  - mmap-based reads (index files) cause page cache churn
  - Dirty page ratio hits vm.dirty_ratio → writes throttle
```

**Linux Tuning for Kafka Isolation:**

```bash
# /etc/sysctl.d/99-kafka.conf

# Dirty page thresholds (critical for Kafka)
vm.dirty_ratio = 40           # % of memory that can be dirty before writes block
vm.dirty_background_ratio = 5 # % that triggers background writeback

# Page cache pressure
vm.vfs_cache_pressure = 50    # Less aggressive cache eviction
vm.swappiness = 1             # Never swap (except emergency)

# Network tuning
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

**OS Isolation (cgroups v2):**

```bash
# Use cgroups v2 to reserve page cache for Kafka
# /etc/cgconfig.d/kafka.conf

# Memory controller: limit but also protect
sudo mkdir -p /sys/fs/cgroup/kafka
echo 50G > /sys/fs/cgroup/kafka/memory.max          # Hard limit
echo 40G > /sys/fs/cgroup/kafka/memory.high         # Throttle above this
echo 350G > /sys/fs/cgroup/kafka/memory.soft_protection  # Page cache reservation

# Move Kafka JVM to this cgroup
echo $(pidof java) > /sys/fs/cgroup/kafka/cgroup.procs
```

**Dedicated Disks:**

```yaml
# Recommendation: JBOD (Just a Bunch of Disks), NOT RAID

# Good:
  /data/kafka-0 (NVMe disk 0) → topics partition 0-9
  /data/kafka-1 (NVMe disk 1) → topics partition 10-19
  /data/kafka-2 (NVMe disk 2) → topics partition 20-29

# Bad:
  RAID5 → Write amplification factor 4 (read-modify-write on parity)
  RAID6 → WAF 6 → Kafka's sequential patterns become random

# /etc/kafka/server.properties
log.dirs=/data/kafka-0,/data/kafka-1,/data/kafka-2
num.recovery.threads.per.data.dir=1  # Parallel recovery across disks
```

**File System: XFS vs ext4:**

```yaml
XFS (recommended):
  - Allocation groups → parallel allocation
  - No fsck after crash (journal replay, instant mount)
  - Delayed allocation → fewer, larger extents
  - Best for large file workloads

ext4:
  - Good for smaller deployments
  - Needs periodic fsck (unmount for hours on large volumes)
  - Block groups can cause allocation contention
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Page cache primacy** | Understands Kafka performance IS page cache performance |
| **Isolation techniques** | Can describe cgroup v2 memory protection, dedicated disks, NUMA pinning |
| **File system choice** | Can defend XFS > ext4 for Kafka workloads |
| **Dirty page tradeoff** | Explains high dirty_ratio for throughput vs low for write latency |

---

## 9. Cluster Scaling & Partition Reassignment

**Q:** "You add 3 brokers to a 6-broker Kafka cluster. Partition distribution is now heavily skewed (old brokers at 80% load). Walk through the partition reassignment process without downtime. How do you control the impact on production traffic?"

**What They're Really Testing:** Whether you understand Kafka's partition reassignment tool, throttling, and the preferred replica election process.

### Answer

**Partition Reassignment Process:**

```bash
# Step 1: Generate reassignment plan
kafka-reassign-partitions \
  --bootstrap-server kafka:9092 \
  --generate \
  --topics-to-move-json-file topics.json > plan.json

# topics.json:
#   {"topics": [{"topic": "orders"}, {"topic": "payments"}],
#    "version": 1}

# plan.json contains:
#   Current partition → broker mapping
#   Proposed partition → broker mapping (evenly distributed)

# Step 2: Execute reassignment with throttle
kafka-reassign-partitions \
  --bootstrap-server kafka:9092 \
  --execute \
  --reassignment-json-file plan.json \
  --throttle 500000000  # 500 MB/s throttle (critical!)
```

**Throttling Mechanics:**

```
Replication throttle limits:
  leader.throttled.rate = 500 MB/s  (per broker, outbound)
  follower.throttled.rate = 500 MB/s (per broker, inbound)

What happens without throttle:
  - New broker pulls 10GB/s from old brokers
  - Old brokers' page cache evicted by outbound replication
  - Production write throughput drops 50%+

Throttle sizing:
  Rule: throttle ≤ (replica.fetch.max.bytes × num.followers) / tolerable_impact
  Example: if 10% throughput drop is acceptable on 500MB/s producers:
    throttle = 500MB/s × 10% = 50 MB/s per broker

Monitoring during reassignment:
  kafka.server:type=ReplicaManager,name=LeaderAndIsrExpiredPerSec
  kafka.network:type=RequestMetrics,name=LocalTimeMs,request=LeaderAndIsr
```

**Automated Rebalancing with Cruise Control:**

```json
# LinkedIn Cruise Control (open source)
# Goals:
#   - RackAwareDistributionGoal
#   - ReplicaDistributionGoal
#   - DiskUsageDistributionGoal (uniform disk usage ±10%)
#   - LeaderBytesInDistributionGoal

POST /kafkacruisecontrol/rebalance
{
  "goals": [
    "com.linkedin.kafka.cruisecontrol.analyzer.goals.RackAwareGoal",
    "com.linkedin.kafka.cruisecontrol.analyzer.goals.DiskCapacityGoal",
    "com.linkedin.kafka.cruisecontrol.analyzer.goals.ReplicaDistributionGoal"
  ],
  "dryRun": false,
  "throttle": 500000000
}
```

**Preferred Replica Election:**

```bash
# After reassignment, the leader may still be on the old broker
# Run preferred replica election to balance leader load

kafka-leader-election \
  --bootstrap-server kafka:9092 \
  --election-type preferred \
  --all-topic-partitions

# Now each partition's preferred leader (first replica in list) is the leader
# Combined with Cruise Control: balanced leaders = balanced request load
```

**Rolling Restart During Scaling:**

```yaml
# After adding brokers:
1. Add new brokers: start with empty data dirs
2. New brokers join cluster, see metadata from ZooKeeper
3. No partitions moved yet → new brokers are idle
4. Run reassignment: move partitions to new brokers
5. After reassignment completes → run preferred leader election
6. Verify: kafka-topics --describe --under-replicated-partitions (should be 0)
7. Update monitoring thresholds (new brokers need alerting)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Throttling** | Knows how to limit reassignment impact with throttles |
| **Plan verification** | Understands --verify to check reassignment completion |
| **Cruise Control** | Mentions LinkedIn's Cruise Control for automated rebalancing |
| **Preferred leaders** | Knows to run leader election after reassignment |

---

## 10. Monitoring, Metrics & Alerting

**Q:** "Design a monitoring dashboard for a Kafka cluster handling 1M messages/second. What metrics do you track? What are the alert thresholds? How do you detect consumer lag before it causes problems?"

**What They're Really Testing:** Whether you understand Kafka's JMX metrics in detail — which ones signal real problems vs normal variance.

### Answer

**Critical Metrics (JVM + Kafka):**

```python
# Essential JMX metrics to track

# ── Broker Health ──
# kafka.server:type=BrokerTopicMetrics,name=MessagesInPerSec
#   Rate: total messages/sec
#   Alert: > 80% of cluster capacity (scale up)

# kafka.server:type=BrokerTopicMetrics,name=TotalFetchRequestPerSec
#   Fan-out ratio: TotalFetchRequests / TotalProduceRequests
#   Alert: > 100:1 → too many consumer groups, enable compression

# kafka.server:type=KafkaServer,name=BrokerState
#   Value (RunningAsController=1, SyncingBroker=2, RunningBroker=3)
#   Alert: NOT RunningAsController (for controllers)

# kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions
#   Alert: > 0 for > 5 minutes → replication lagging

# ── Request Handling ──
# kafka.server:type=RequestMetrics,name=RemoteTimeMs,request=Produce
#   p99: time the leader waits for follower ACKs
#   Alert: p99 > 100ms → slow followers (disk I/O or network)

# kafka.server:type=RequestMetrics,name=LocalTimeMs,request=Produce
#   Time to append to local log
#   Alert: p99 > 10ms → page cache pressure or disk I/O bottleneck

# kafka.network:type=RequestMetrics,name=RequestQueueSize
#   Alert: > 1000 → broker can't keep up with requests

# ── Network ──
# kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent
#   Alert: < 0.3 → network threads saturated, increase network.threads

# ── OS ──
# kafka.log:type=LogCleanerManager,name=TimeSinceLastCompaction
#   Alert: > 24h → compaction stuck or deadlocking
```

**Consumer Lag Monitoring (Burrow Pattern):**

```python
# Burrow's approach (LinkedIn): lag evaluation without fixed thresholds
# Uses consumer's committed offset vs. Kafka's latest offset

# Evaluate lag relative to consumer's OWN behavior:
#   - Track consumer's offset over a sliding window
#   - Calculate expected progress rate
#   - If consumer stops processing but lag is stable → OK (no new messages)
#   - If consumer stops AND lag grows → PROBLEM

# Python consumer lag checker:
def check_lag(bootstrap_servers, group_id, topic):
    admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
    consumer = KafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False
    )

    # Get partition assignments
    partitions = consumer.partitions_for_topic(topic)

    for tp in consumer.assignment():
        # Latest offset (end of log)
        end_offset = consumer.end_offsets([tp])[tp]

        # Consumer committed offset
        committed = consumer.committed(tp)
        if committed is None:
            committed = 0

        lag = end_offset - committed

        # Alert thresholds (dynamic):
        # 1. Lag > 1M messages → PagerDuty alert
        # 2. Lag growth rate > 1000/sec → warning
        # 3. Lag > replica.fetch.max.bytes × 1000 → likely slow consumer

        duration_seconds = lag / (messages_per_second_per_partition or 1)
        if duration_seconds > 300:  # 5 minutes of backlog
            raise Alert(f"Consumer {group_id} lagging by {duration_seconds:.0f}s on {tp}")

    consumer.close()
```

**Alert Thresholds Summary:**

```yaml
# P0 (Immediate):
  UnderReplicatedPartitions > 0 for 5+ minutes
  OfflinePartitions > 0
  ActiveControllerCount != 1 (for controller broker, not data broker)
  KafkaRestExceptionCount (REST proxy)

# P1 (High):
  RequestQueueSize > 1000 (produce or fetch)
  LocalTimeMs p99 > 50ms
  LogSegmentCount growth > 1000/day (retention not keeping up)
  NetworkProcessorAvgIdlePercent < 0.1

# P2 (Warning):
  ConsumerLag > 1M messages
  MessagesInPerSec drop > 50% (producer side issue)
  BytesOutPerSec > 80% of network bandwidth
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **JMX metrics depth** | Knows specific MBean names and alert thresholds, not just concepts |
| **Lag semantics** | Understands committed offset, log end offset, and lag growth rate |
| **Burrow approach** | Evaluates lag relative to consumer behavior, not static thresholds |
| **OS-level metrics** | Includes page cache hit rate, dirty page ratio, disk I/O |

---

## 11. Security: TLS, SASL, ACLs

**Q:** "Design a multi-tenant Kafka cluster serving 5 teams. Each team must only read/write their own topics. All traffic must be encrypted in transit. How do you configure Kafka security? How do you rotate certificates without downtime?"

**What They're Really Testing:** Whether you understand Kafka's security model — SSL/TLS, SASL authentication, and ACL-based authorization at the cluster, topic, and group level.

### Answer

**Multi-Layer Security Architecture:**

```yaml
Layer 1: Encryption in transit (TLS)
  - Mutual TLS (mTLS) for both authentication AND encryption
  - Each broker has server certificate (signed by internal CA)
  - Each client has client certificate (signed by internal CA)
  - All inter-broker communication over TLS

Layer 2: Authentication (SASL)
  - SASL/SCRAM-SHA-512: username + password over TLS
    - Stored in ZooKeeper (zookeeper.set.acl=true) or custom DB
    - Users: admin, team-a-producer, team-b-consumer, etc.
  - SASL/OAUTHBEARER: OAuth2 tokens (best for SSO)
    - Kafka can authenticate against your IdP (Okta, Keycloak)
    - Token introspection (optional) for revocation

Layer 3: Authorization (ACLs)
  - kafka-acls.sh --authorizer-properties ...
  - ACLs evaluated for EVERY produce/fetch/describe operation
```

**Server Configuration:**

```properties
# /etc/kafka/server.properties

# TLS
listeners=SSL://kafka:9093,SASL_SSL://kafka:9094
advertised.listeners=SSL://kafka:9093,SASL_SSL://kafka:9094
ssl.keystore.location=/etc/kafka/secrets/server.keystore.jks
ssl.keystore.password=${KEYSTORE_PASSWORD}
ssl.key.password=${KEY_PASSWORD}
ssl.truststore.location=/etc/kafka/secrets/server.truststore.jks
ssl.truststore.password=${TRUSTSTORE_PASSWORD}
ssl.client.auth=required          # mTLS: require client cert
ssl.enabled.protocols=TLSv1.3,TLSv1.2
ssl.cipher.suites=TLS_AES_256_GCM_SHA384,TLS_CHACHA20_POLY1305_SHA256

# SASL
sasl.enabled.mechanisms=SCRAM-SHA-512,OAUTHBEARER
listener.name.sasl_ssl.scram-sha-512.sasl.jaas.config= \
  org.apache.kafka.common.security.scram.ScramLoginModule required;
listener.name.sasl_ssl.oauthbearer.sasl.jaas.config= \
  org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required;

# Authorization
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
super.users=User:admin       # Bypasses ACL checks
allow.everyone.if.no.acl.found=false  # DENY by default!
```

**ACL Management (Multi-Tenant Example):**

```bash
# Team A: can read/write team-a-* topics
kafka-acls --authorizer-properties zookeeper.connect=zk:2181 \
  --add --allow-principal User:team-a-producer \
  --operation Write --operation Describe \
  --topic 'team-a-' --resource-pattern-type prefixed

kafka-acls --authorizer-properties zookeeper.connect=zk:2181 \
  --add --allow-principal User:team-a-consumer \
  --operation Read --operation Describe \
  --topic 'team-a-' --resource-pattern-type prefixed \
  --group team-a- --resource-pattern-type prefixed

# Admin: full access
kafka-acls --authorizer-properties zookeeper.connect=zk:2181 \
  --add --allow-principal User:admin \
  --operation All --topic '*' --group '*' \
  --cluster

# Revoke: remove access
kafka-acls --authorizer-properties zookeeper.connect=zk:2181 \
  --remove --deny-principal User:team-b-producer \
  --operation Write --topic 'team-a-' --resource-pattern-type prefixed
```

**Certificate Rotation Without Downtime:**

```bash
# Strategy: use two keystores + alias-based rotation

# Phase 1: Prepare new certificate (while old is still valid)
# Generate new CSR with same DN
keytool -certreq -alias kafka-server-current \
  -keystore server.keystore.jks -file server.csr

# Sign with internal CA → get new certificate
# Import CA chain + new cert with new alias
keytool -import -alias kafka-server-new \
  -keystore server.keystore.jks -file server-signed.crt

# Phase 2: Rolling restart of brokers (one at a time)
# Each broker restarts with BOTH old and new cert in keystore
# Clients still connect with old cert → no disruption

# Phase 3: Update client truststores
# Distribute new CA certificate to all clients
# Clients trust both old and new certs during transition

# Phase 4: Remove old certificate
keytool -delete -alias kafka-server-current \
  -keystore server.keystore.jks
# Rolling restart again to remove old alias
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Defense in depth** | Explains TLS + SASL + ACLs as layered controls |
| **Deny by default** | Knows allow.everyone.if.no.acl.found=false (SECURITY!) |
| **Certificate rotation** | Can describe alias-based rotation without downtime |
| **Super users** | Understands super.users bypass ALL ACLs — must restrict |

---

## 12. Kafka vs Pulsar vs Redpanda

**Q:** "Your team is choosing between Kafka, Pulsar, and Redpanda for a new real-time data platform. Walk through the architectural differences. What workloads would make you choose each one?"

**What They're Really Testing:** Whether you understand the fundamental architectural differences — storage/compute separation, tiered storage, and the impact of JVM vs C++ on operations.

### Answer

**Architectural Comparison:**

```
┌─────────────────────────────────────────────────────────────────────┐
│ Kafka (Java, Apache)   │ Pulsar (Java, Apache)    │ Redpanda (C++)   │
├─────────────────────────┼─────────────────────────┼───────────────────┤
│ Monolithic broker       │ Separation: serving +    │ Monolithic (like  │
│ (storage + serving)     │ storage (BookKeeper)     │ Kafka) but in C++ │
│                         │ Tier 1: Broker          │ No ZooKeeper:     │
│ ZooKeeper required      │ Tier 2: BookKeeper       │ uses Raft via     │
│ (or KRaft)              │ Tier 3: Offload (S3)     │ Pandora protocol  │
├─────────────────────────┼─────────────────────────┼───────────────────┤
│ Storage: local disk     │ Storage: BookKeeper      │ Storage: local    │
│ Page cache based        │ separates from serving   │ disk + tiered to  │
│ No tiered storage (not  │ Native tiered storage    │ S3 (Tiered via    │
│ built-in, Confluent has │ (offload to S3/GCS)      │ RAFC v2)          │
│ it as a paid feature)   │                          │                   │
├─────────────────────────┼─────────────────────────┼───────────────────┤
│ Consumer: pull-based    │ Consumer: pull-based     │ Consumer:         │
│ via FETCH requests      │ via long-poll            │ pull-based,       │
│ No segment read        │ No segment read          │ segment read via  │
│ (must read whole batch) │ (must read whole batch)   │ io_uring          │
├─────────────────────────┼─────────────────────────┼───────────────────┤
│ JVM: GC pauses          │ JVM: GC pauses           │ No JVM: no GC     │
│ Heap: 8-32GB typical   │ Same                    │ Direct memory     │
│ Large heap → GC tuning  │                          │ allocation        │
│ Kafka avoids GC by      │                          │ Predictable       │
│ minimizing heap usage   │                          │ latency (no GC)   │
└─────────────────────────┴─────────────────────────┴───────────────────┘
```

**When to Choose Each:**

```yaml
Choose Kafka when:
  - Largest ecosystem: connectors, Schema Registry, ksqlDB, Streams
  - Team already knows Kafka operations
  - Need mature Exactly-Once Semantics
  - Primarily throughput-oriented, latency-tolerant (>10ms)
  - Many integrations: Debezium, Kafka Connect ecosystem

Choose Pulsar when:
  - Need native multi-tenancy (within single cluster)
  - Geo-replication is a primary requirement
  - Need tiered storage (hot/warm/cold)
  - Serverless workloads with Pulsar Functions
  - Storage and compute must scale independently
  - Read:Write ratio is highly skewed (Pulsar's BookKeeper handles read scaling better)

Choose Redpanda when:
  - Sub-5ms end-to-end latency required
  - Want to eliminate ZooKeeper dependency
  - Operations team prefers a single binary (no JVM tuning)
  - Predictable p99 latency more important than ecosystem
  - Need tiered storage without Confluent licensing
  - Running Kubernetes native (simpler operator than Strimzi)
```

**Redpanda's Key Technical Differentiators:**

```yaml
# No ZooKeeper: Raft consensus via Pandora protocol
# Each partition is a Raft group (3 or 5 replicas)

# io_uring for async I/O (instead of epoll + page cache)
# Kernel 5.1+ feature: submission/completion queues
# The application manages its own I/O scheduling
# Redpanda bypasses the page cache entirely!

# Single binary, no JVM:
# - No GC pauses → p99 latency < 5ms sustained
# - No heap tuning → -Xms/-Xmx doesn't exist
# - Memory is managed via seastar (shared-nothing per core)

# The trade-off:
# Redpanda is faster AND simpler to operate
# BUT: smaller ecosystem, fewer connectors
# AND: Schema Registry is immature relative to Confluent's
```

**Migration Strategy (Kafka → Pulsar or Redpanda):**

```python
# MirrorMaker 2.0 for bidirectional replication during migration
# Run both clusters in parallel

# Phase 1: MirrorMaker copies from Kafka to target
# Phase 2: Applications read from Kafka, write to both
# Phase 3: Cutover applications to new cluster
# Phase 4: Shut down Kafka

# Example MirrorMaker config:
kafka-mirror-maker --consumer.config consumer-kafka.properties \
                   --producer.config producer-pulsar.properties \
                   --num.streams 4 \
                   --topics '.*'
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Architecture depth** | Understands BookKeeper layer in Pulsar, io_uring in Redpanda |
| **Trade-off articulation** | Can give specific workload-appropriate recommendations |
| **Ecosystem awareness** | Knows Kafka's ecosystem strength vs others' operational simplicity |
| **Migration** | Can describe MirrorMaker-based migration strategy |

---

> *All 12 questions cover the full breadth of Kafka internals, operations, and ecosystem — from storage internals to production operations and competitive analysis.*
