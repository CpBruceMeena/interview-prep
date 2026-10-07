# 📨 Kafka — Staff-Level Interview Questions

> *12 questions covering Kafka internals, producer/consumer design, replication, and operations. Each answer leads with a 30-second version, then the mechanism, then failure modes and what the interviewer probes next.*

!!! info "Version baseline (October 2026)"
    Current Apache Kafka is the **4.x** line (4.0 March 2025, 4.1 September 2025, 4.2 February 2026, 4.3 May 2026). Things that changed and that interviewers now expect you to know:

    - **KRaft only.** ZooKeeper mode was removed in 4.0. Metadata lives in the `__cluster_metadata` Raft log managed by a controller quorum. Upgrading from a ZooKeeper cluster means migrating to KRaft on 3.x (3.9 is the bridge release) first.
    - **New consumer rebalance protocol (KIP-848)** is GA since 4.0 (`group.protocol=consumer`). The assignment moves to the broker-side group coordinator, and there's no global "stop the world" barrier.
    - **Queues for Kafka / share groups (KIP-932):** early access in 4.0, preview in 4.1, **production-ready in 4.2**.
    - **Tiered storage (KIP-405)** has been production-ready since 3.9.
    - **Eligible Leader Replicas (KIP-966):** available in 4.0, on by default for new clusters since 4.1.
    - 4.0 also removed MirrorMaker 1, the v0/v1 message formats and `AclAuthorizer` (replaced by `StandardAuthorizer`), changed the `linger.ms` default from 0 to 5 ms (KIP-1030), and requires Java 17 for brokers (Java 11 for clients).

---

## Table of Contents

1. [Log Segment Structure & Storage Internals](#1-log-segment-structure-storage-internals)
2. [ISR Replication & Leader Election](#2-isr-replication-leader-election)
3. [Consumer Group Rebalancing](#3-consumer-group-rebalancing)
4. [Exactly-Once Semantics & Transactions](#4-exactly-once-semantics-transactions)
5. [Producer: Batching, Compression, Idempotency](#5-producer-batching-compression-idempotency)
6. [Kafka Connect & Connector Design](#6-kafka-connect-connector-design)
7. [Kafka Streams: Stateful Processing](#7-kafka-streams-stateful-processing)
8. [Disk I/O & Page Cache Optimization](#8-disk-io-page-cache-optimization)
9. [Cluster Scaling & Partition Reassignment](#9-cluster-scaling-partition-reassignment)
10. [Monitoring, Metrics & Alerting](#10-monitoring-metrics-alerting)
11. [Security: TLS, SASL, ACLs](#11-security-tls-sasl-acls)
12. [Kafka vs Pulsar vs Redpanda](#12-kafka-vs-pulsar-vs-redpanda)

---

## 1. Log Segment Structure & Storage Internals

**Q:** "Trace the lifecycle of a Kafka message from producer send to consumer read. What happens at the storage layer? How does Kafka sustain very high write throughput on commodity hardware?"

**What They're Really Testing:** Whether you understand that Kafka is a partitioned, replicated append-only log rather than a queue, and that its speed comes from sequential I/O, batching, the OS page cache and zero-copy reads.

!!! tip "30-second answer"
    A partition is an append-only log split into segment files. The producer sends compressed **batches**. The leader appends each batch as-is to the active segment through the page cache, with no fsync per write, and followers fetch it. Consumers read by offset, and plaintext reads are served with `sendfile()` straight from the page cache to the socket. Throughput comes from **batching + sequential appends + page cache + zero-copy**. Durability comes from **replication**, not fsync.

### Answer

**Message lifecycle (storage layer):**

```
Producer → Topic "orders", Partition 0

Logical view: an ordered, immutable sequence addressed by offset
  offset:  0     1     2     3     4     5
          [m1]  [m2]  [m3]  [m4]  [m5]  [..]  ← appends only at the tail

Physical storage (one directory per partition replica):
/data/kafka/orders-0/
├── 00000000000000000000.log        ← segment: record batches, base offset 0
├── 00000000000000000000.index      ← sparse offset → byte position index
├── 00000000000000000000.timeindex  ← sparse timestamp → offset index
├── 00000000000000001000.log        ← next segment starts at offset 1000
├── 00000000000000001000.index
├── 00000000000000001000.timeindex
├── 00000000000000002000.log        ← active segment (only one receiving writes)
└── leader-epoch-checkpoint         ← epoch → start offset, used for truncation after failover
```

The indexes are **sparse** (one entry per `log.index.interval.bytes`, 4 KB by default) and memory-mapped. A fetch for offset N does a binary search on the index, then a short scan forward in the `.log` file.

**Why it's fast:**

| Technique | Mechanism | Caveat |
|---|---|---|
| **Batching** | Producer groups records per partition into batches. The broker validates and appends the batch without unpacking each record. | Small batches mean lots of requests. Batching is the #1 throughput lever. |
| **Sequential I/O** | All writes are appends to the active segment. Spinning disks do sequential I/O roughly 100× faster than random I/O. SSDs benefit less, but still gain from large writes. | Many partitions per disk turn "sequential" back into interleaved I/O. |
| **Page cache** | Writes land in the OS page cache. The kernel flushes them in the background. Tail reads by up-to-date consumers are served from memory. | Durability relies on replication (`acks=all` + `min.insync.replicas`), not on fsync. |
| **Zero-copy** | `sendfile()` moves data page cache → socket without copying it into the JVM. That saves two CPU copies and the user/kernel context switches for the data. | **Doesn't apply with TLS**, because the broker must encrypt in user space (kTLS isn't used by Kafka). TLS clusters pay a noticeable CPU cost. |
| **Compression end to end** | The producer compresses the batch. The broker stores it compressed (if the topic's `compression.type=producer`). Consumers decompress. | If the topic's compression type differs from the producer's, the broker must **recompress**, which costs a lot of CPU. |

**Segment rolling and retention:**

```properties
log.segment.bytes=1073741824     # 1 GiB (default): roll when the active segment reaches this size
log.roll.hours=168               # or roll after 7 days, whichever comes first
log.retention.hours=168          # 7 days (default). Retention deletes whole closed segments.
log.cleanup.policy=delete        # or "compact" (keep latest value per key), or "compact,delete"
```

Retention and compaction work on **closed segments only**. On a low-volume topic, data can therefore outlive `retention.ms` until the active segment rolls. This is a classic GDPR or "why is old data still here" gotcha.

**Tiered storage (KIP-405, production-ready since 3.9):** closed segments are copied to object storage (S3/GCS/Azure) through a pluggable `RemoteStorageManager`. Local disk keeps only a hot tail (`local.retention.ms`). The result is long retention without big disks, and much faster reassignment and broker replacement because there's less local data to move. Fetches for old offsets are served from the remote tier, at higher latency.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Sequential I/O + batching** | Explains *why* appends are cheap, and that batching (not the disk) is usually the first lever |
| **Zero-copy** | Knows `sendfile()` avoids user-space copies, **and that TLS disables it** |
| **Page cache** | Durability = replication, not fsync. Knows lagging consumers cause cold disk reads. |
| **Segment lifecycle** | Rolling, sparse indexes, retention on closed segments only, compaction vs deletion, tiered storage |

**What they probe next:** "How does compaction work?" The cleaner thread rewrites dirty segments, keeping the latest record per key. Tombstones (null values) are kept for `delete.retention.ms` so consumers see the deletion. "What happens to page cache when one consumer replays 3 days of data?" It evicts the hot tail and hurts everyone else. Tiered storage or separate replay clusters help.

---

## 2. ISR Replication & Leader Election

**Q:** "You're running a Kafka cluster with replication.factor=3, min.insync.replicas=2. A broker fails. Walk through what happens: leader election, ISR changes, and data durability guarantees."

**What They're Really Testing:** Whether you know the exact condition under which a write counts as committed, who elects leaders (the KRaft controller), and the durability vs availability trade-off.

!!! tip "30-second answer"
    The leader tracks the **ISR**, the replicas that are caught up. With `acks=all`, a write is acknowledged once every current ISR member has it, and the leader refuses writes if the ISR is smaller than `min.insync.replicas`. A slow or dead follower is dropped from the ISR after `replica.lag.time.max.ms` (30 s). If the **leader** dies, the KRaft controller picks a new leader from the ISR, so no acknowledged write is lost. RF=3 / min.isr=2 survives one broker failure with no loss and no downtime. A second failure makes the partition read-only for `acks=all` producers instead of losing data.

### Answer

**Terms:** **LEO** (log end offset) is the next offset a replica will write. **HW** (high watermark) is the highest offset replicated to all ISR members. Consumers only see up to the HW.

```
Topic: orders, Partition: 0, Replicas: [1 (leader), 2, 3], ISR = {1,2,3}

Write path (acks=all):
  1. Producer sends a batch to the leader (broker 1). The leader appends and advances its LEO.
  2. Followers send FETCH requests. The fetch offset tells the leader how far each follower has replicated.
  3. Leader advances HW = min(LEO over ISR members).
  4. Once HW passes the batch, the leader acks the producer and consumers can read it.

Follower (broker 2) dies:
  After replica.lag.time.max.ms (30 s default) the leader shrinks ISR → {1,3}.
  |ISR| = 2 ≥ min.insync.replicas → writes continue. No data loss.

Leader (broker 1) dies next:
  The KRaft controller notices (missed broker heartbeats → broker fenced) and elects broker 3
  from the ISR. Leader epoch is bumped. ISR = {3}.
  |ISR| = 1 < min.insync.replicas → acks=all produces fail with NOT_ENOUGH_REPLICAS
  (retriable: the producer keeps retrying until delivery.timeout.ms).
  Reads still work. acks=0/1 producers can still write (min.isr only applies to acks=all).
```

**Why no acknowledged write is lost:** every acked record was on every ISR member, and the new leader always comes from the ISR (or ELR, below). Followers that come back **truncate** to the leader's log using the **leader epoch** history (KIP-101). This drops any unacked tail they wrote under the old leader, instead of trusting the high watermark.

**Eligible Leader Replicas (KIP-966, default on new clusters since 4.1):** the "last replica standing" problem was this: if the ISR shrinks to just the leader and that leader then dies with an unclean disk, there was no clean candidate left. With ELR, the ISR can't shrink below `min.insync.replicas`. Replicas that drop out but are guaranteed to hold everything committed up to the HW go into an **ELR** set, which the controller can elect from safely. This shrinks the cases where you'd need unclean election.

**Unclean leader election** (`unclean.leader.election.enable=true`, default false): if no ISR/ELR replica is available, the controller elects any replica. The partition comes back sooner, but **acknowledged writes the new leader never received are lost**. Consumers may also have already read offsets that get reused for different records. Use it per topic only where availability beats correctness (metrics, logs).

**Diagnostic commands:**

```bash
kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic orders
# Leader: 3  Replicas: 1,2,3  Isr: 3   ← shrunken ISR

kafka-topics.sh --bootstrap-server kafka:9092 --describe --under-replicated-partitions
kafka-topics.sh --bootstrap-server kafka:9092 --describe --under-min-isr-partitions
kafka-metadata-quorum.sh --bootstrap-server kafka:9092 describe --status   # KRaft controller quorum health
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ISR mechanics** | Defines HW and LEO precisely. With acks=all, the ack waits on the *current* ISR, gated by min.isr. |
| **min.isr behavior** | Writes are **rejected** (retriable error), not queued. Only applies to `acks=all`. |
| **Election** | KRaft controller elects from ISR (then ELR). Leader epochs drive follower truncation. |
| **Unclean election** | Names the danger exactly: loss of acknowledged data and offset reuse |
| **Diagnosis** | Under-replicated vs under-min-ISR vs offline partitions, and controller quorum status |

**What they probe next:** "Why RF=3 and min.isr=2, not min.isr=3?" With 3, a single slow follower blocks all writes. "Rack awareness?" `broker.rack` spreads replicas across AZs. Consumers can use `client.rack` to fetch from the closest replica (KIP-392) and save cross-AZ cost. "What does `acks=1` lose?" Writes the leader acked but never replicated before it died.

---

## 3. Consumer Group Rebalancing

**Q:** "A 50-node Kafka consumer group experiences a 30-second processing pause every time a new consumer joins or leaves. How did cooperative rebalancing (KIP-429) improve this? What about static group membership (KIP-345)? What changed with KIP-848?"

**What They're Really Testing:** Whether you understand rebalancing at the protocol level: the stop-the-world problem in the classic protocol, the incremental fixes, and the new broker-driven protocol in Kafka 4.x.

!!! tip "30-second answer"
    The classic **eager** protocol makes every member revoke every partition, then waits at a group-wide barrier while one client computes the new assignment. **Cooperative** rebalancing (KIP-429, 2.4) only revokes partitions that actually move, so the rest keep processing. **Static membership** (KIP-345, 2.3) lets a restarting consumer reclaim its partitions without a rebalance if it returns within `session.timeout.ms`. In Kafka 4.x the real answer is **KIP-848** (`group.protocol=consumer`, GA in 4.0). The broker computes assignments, members reconcile on their own through heartbeats, and there's no global sync barrier at all.

### Answer

**Classic protocol, eager (the old default):**

```
1. A member joins or leaves, or a heartbeat times out → coordinator starts a rebalance.
2. Every member revokes ALL partitions (commit offsets, onPartitionsRevoked) and sends JoinGroup.
3. Coordinator waits for every member (bounded by max.poll.interval.ms / rebalance timeout),
   picks one member as group leader and sends it all subscriptions.
4. The leader runs the client-side assignor (range, round-robin, sticky) → SyncGroup.
5. The coordinator distributes assignments. Everyone resumes.
→ The whole group stops for the duration of the slowest member's revoke + rejoin.
```

The 30 s pause usually comes from step 3: one member is stuck in a long `poll()` loop and the group waits for it.

**Classic protocol, cooperative (KIP-429, `CooperativeStickyAssignor`):**

```
Rebalance 1: members rejoin while KEEPING their partitions. The leader computes the
             target assignment, and any partition that must move is left out of its
             current owner's assignment → that owner revokes just those partitions.
Rebalance 2: triggered automatically, assigns the now-free partitions to their new owners.
→ Partitions that don't move are never paused. Costs two rounds instead of one.
```

**Static membership (KIP-345):**

```properties
group.instance.id=orders-consumer-7   # stable per pod (e.g. StatefulSet ordinal)
session.timeout.ms=45000              # default 45 s since 3.0. Raise it to cover a restart.
```

A restarting member with the same `group.instance.id` gets its old assignment back with no rebalance. The trade-off: a member that **really dies** isn't detected until the session timeout, so its partitions sit unprocessed that long.

**KIP-848: the new consumer group protocol (GA in Kafka 4.0):**

| | Classic protocol | KIP-848 (`group.protocol=consumer`) |
|---|---|---|
| Who assigns | Client-side leader | Broker group coordinator (`uniform` or `range` server-side assignors) |
| Coordination | JoinGroup/SyncGroup rounds with a global barrier | `ConsumerGroupHeartbeat` only. Each member converges on its target independently. |
| Effect of one member joining | Whole group (eager) or two rounds (cooperative) | Only the members whose partitions move do any work |
| Client config | `partition.assignment.strategy`, `session.timeout.ms` on the client | `group.remote.assignor`. Session timeout and heartbeat interval are group configs on the broker. |

Migration: on 4.x brokers, a group can be converted online from classic to consumer protocol during a rolling upgrade of the clients. Kafka Streams has its own equivalent, the streams rebalance protocol (KIP-1071), introduced as early access in 4.1.

**Share groups (KIP-932, production-ready in 4.2):** a different consumption model, not a rebalance fix. Many consumers can read the **same partition**, with per-record acknowledgement, delivery counts and redelivery. This gives queue semantics (worker pools) without being capped at one consumer per partition. You lose per-partition ordering.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Eager vs cooperative** | Explains *why* eager pauses everyone, and that cooperative takes two rounds |
| **Static membership** | Knows `group.instance.id` avoids rebalances on restarts, and the cost: slower detection of real failures |
| **KIP-848** | Knows assignment moved server-side in 4.x and the barrier is gone |
| **Root cause** | Checks `max.poll.interval.ms` violations (slow processing) before blaming the protocol |

**What they probe next:** "How do you avoid duplicates during a rebalance?" Commit offsets in `onPartitionsRevoked`, or make processing idempotent. "When would you pick share groups over more partitions?" When work items are independent, ordering doesn't matter, and per-message processing time varies widely.

---

## 4. Exactly-Once Semantics & Transactions

**Q:** "Design a payment processing pipeline where each transaction must be processed exactly once. How does Kafka's exactly-once semantics work? Walk through the transaction protocol: coordinators, transaction markers, and zombie fencing."

**What They're Really Testing:** Whether you know the EOS building blocks (idempotent producer, transactions, transactional offset commits, read_committed), **and where EOS ends**.

!!! tip "30-second answer"
    Kafka EOS covers **read from Kafka → process → write to Kafka**. The idempotent producer removes duplicates caused by retries (producer ID + per-partition sequence numbers). Transactions make writes to several partitions **and the consumer offset commit** atomic, using a transaction coordinator, a two-phase commit and commit/abort markers. Epochs on the `transactional.id` fence zombie instances. Consumers must use `isolation.level=read_committed`. Calling a payment gateway or writing to a database is **outside** Kafka's transaction, so those side effects still need idempotency keys or an outbox pattern.

### Answer

```
Layer 1: Idempotent producer (default since 3.0: enable.idempotence=true, acks=all)
  Broker assigns a producer ID (PID). Each batch carries (PID, epoch, partition sequence number).
  The broker remembers the last 5 batches per PID per partition. A retried duplicate is acked
  but not appended. A gap in sequence numbers is an error.
  → This is why max.in.flight.requests.per.connection must be ≤ 5. Ordering is preserved.
  Scope: one producer session, retries only. Doesn't cover an app that calls send() twice.

Layer 2: Transactions (transactional.id = stable identity across restarts)
  1. initTransactions(): find the transaction coordinator (a leader of a __transaction_state
     partition), get the PID and bump the epoch → any older instance with the same
     transactional.id is now FENCED. Any open transaction it left behind is aborted.
  2. beginTransaction() (client-local).
  3. send(...) to partitions; the producer registers each new partition with the
     coordinator (AddPartitionsToTxn).
  4. sendOffsetsToTransaction(offsets, groupMetadata): the consumer offsets become part of the txn.
  5. commitTransaction():
       a. coordinator writes PREPARE_COMMIT to __transaction_state  ← commit point
       b. coordinator writes COMMIT markers into every involved partition (incl. __consumer_offsets)
       c. coordinator writes COMPLETE_COMMIT
  If the coordinator crashes after (a), the new coordinator finishes writing markers from its log.

Layer 3: Consumers with isolation.level=read_committed
  Only read up to the Last Stable Offset (LSO): the first offset of any still-open transaction.
  Records from aborted transactions are filtered out using the abort index.
  → One long-running open transaction stalls read_committed consumers on that partition.
```

Kafka 4.0 also shipped **Transactions V2 / server-side defense (KIP-890)**. The epoch is bumped on every transaction, and partitions are added to the transaction implicitly. This closes a class of "hanging transaction" bugs where a late write from an aborted transaction slipped into the next one.

**Consume-transform-produce loop (confluent-kafka Python client):**

```python
from confluent_kafka import Consumer, Producer, KafkaException

consumer = Consumer({
    "bootstrap.servers": "kafka:9092",
    "group.id": "payment-processor",
    "enable.auto.commit": False,
    "isolation.level": "read_committed",
})
producer = Producer({
    "bootstrap.servers": "kafka:9092",
    "transactional.id": "payment-processor-1",  # stable per instance/shard, not random
    "compression.type": "zstd",
})
consumer.subscribe(["payment-requests"])
producer.init_transactions()

while True:
    msgs = consumer.consume(num_messages=500, timeout=1.0)
    if not msgs:
        continue
    producer.begin_transaction()
    try:
        for m in msgs:
            if m.error():
                raise KafkaException(m.error())
            result = process(m.value())          # must be deterministic, no external side effects
            producer.produce("payment-events", key=m.key(), value=result)
            producer.produce("audit-trail", key=m.key(), value=result)
        producer.send_offsets_to_transaction(
            consumer.position(consumer.assignment()),
            consumer.consumer_group_metadata())
        producer.commit_transaction()
    except KafkaException:
        producer.abort_transaction()
        # rewind to last committed offsets so the batch is reprocessed
        # (a partition with no committed offset needs auto.offset.reset handling instead)
        for tp in consumer.committed(consumer.assignment()):
            if tp.offset >= 0:
                consumer.seek(tp)
```

If `commit_transaction()` raises a **fatal** error (for example, the producer was fenced), close the producer and exit rather than aborting. Another instance now owns this `transactional.id`.

**The payment-specific part:** charging a card is an external side effect. Kafka can't roll it back. Standard designs:

- Use the **payment ID as an idempotency key** at the payment provider. A retry after a crash then can't double-charge.
- Or write the intent to Kafka transactionally, and have a separate consumer call the provider with the idempotency key and record the outcome.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **EOS building blocks** | Idempotence (retries) vs transactions (atomic multi-partition + offsets) |
| **Epoch fencing** | `initTransactions()` bumps the epoch, and zombies get `ProducerFencedException` |
| **Read-committed** | LSO, and how a stuck transaction blocks consumers |
| **Failure scenarios** | Coordinator crash after PREPARE_COMMIT is completed by the new coordinator. `transaction.timeout.ms` aborts abandoned transactions. |
| **Boundary** | States clearly that external side effects need idempotency keys or an outbox |

**What they probe next:** "Cost of transactions?" Extra round trips and markers per commit, so commit every N records or every 100 ms rather than per record. "How does Kafka Streams do this?" `processing.guarantee=exactly_once_v2`, one producer per stream thread.

---

## 5. Producer: Batching, Compression, Idempotency

**Q:** "Your Kafka cluster needs to process 500K messages/second through a single topic. Each message is ~1KB JSON. The producer is at 30% CPU but write throughput is capped at 100MB/s. Diagnose and fix. Walk through every producer tuning knob."

**What They're Really Testing:** Whether you understand the producer pipeline (accumulator → sender → in-flight requests) and diagnose with metrics instead of turning knobs at random.

!!! tip "30-second answer"
    A producer with spare CPU but flat throughput is **waiting**, not computing. Usually the cause is batches too small (many requests, each paying a round trip), too few partitions or in-flight requests to pipeline, or a slow broker ack path with `acks=all`. Check `batch-size-avg`, `records-per-request-avg`, `record-queue-time-avg`, `request-latency-avg` and `bufferpool-wait-ratio`. The usual fix is bigger `batch.size` + `linger.ms` + compression, enough partitions, and checking broker produce latency. Only scale out producer instances once a single producer is proven saturated.

### Answer

**Producer internals:**

```
app thread: send(record)
   │  serialize → partition → append to RecordAccumulator (one deque of batches per partition)
   │  returns immediately with a Future, and blocks only if buffer.memory is full (max.block.ms)
   ▼
Sender thread (one per producer instance):
   - drains batches that are full (batch.size) or old enough (linger.ms)
   - groups ready batches by destination broker → one ProduceRequest per broker
   - keeps up to max.in.flight.requests.per.connection unacked requests per broker
   - completes Futures / callbacks when acks arrive, retries retriable errors
Compression happens per batch when the batch is closed. With the Java client
that work runs on the sender path.
```

**Diagnosis:** 100 MB/s of 1 KB records is ~100K records/s, 5× short of the target.

| Metric (producer JMX) | What it tells you |
|---|---|
| `batch-size-avg` far below `batch.size` | Batches ship nearly empty: raise `linger.ms`, or there are too many partitions per producer |
| `records-per-request-avg` low | Each request round trip carries little data |
| `request-latency-avg` high | The broker side is slow (`acks=all` waiting on followers, disk, or request queue) |
| `record-queue-time-avg` high + `bufferpool-wait-ratio` > 0 | The accumulator is backed up: the sender can't drain fast enough |
| `compression-rate-avg` | Compressed size ÷ uncompressed size. Shows whether compression is earning its CPU. |

**Typical fix (Java client property names):**

```properties
batch.size=262144                 # 256 KB per partition batch (default 16 KB)
linger.ms=20                      # wait up to 20 ms to fill a batch (default 5 ms since 4.0)
compression.type=zstd             # or lz4 for lower CPU. Typically 3-10× on JSON, depending on data.
buffer.memory=268435456           # 256 MB accumulator (default 32 MB)
acks=all                          # keep durability. Fix latency elsewhere.
enable.idempotence=true           # default since 3.0
max.in.flight.requests.per.connection=5   # max allowed with idempotence. Ordering still kept.
delivery.timeout.ms=120000        # upper bound on send + retries (prefer this over tuning retries)
```

Then check the other side:

- **Partition count**: one producer request carries one batch per partition, so a few partitions cap batching.
- **Broker produce latency**: `RemoteTimeMs` covers follower replication, `LocalTimeMs` covers the append.
- **Topic compression**: it must match the producer's, or be `producer`, so the broker doesn't recompress.
- **Network**: are you hitting the NIC limit? Compression is the fix there.

**When to scale out:** a single Java producer instance can push hundreds of MB/s with good batching. If one instance really is saturated, with the sender thread busy and the queue backed up, run several producer instances (processes or instances per thread) over disjoint keys. Don't share one producer across hundreds of app threads and then blame Kafka.

**Partitioner note:** since 3.3 (KIP-794), records **without a key** use a "sticky" partitioner that fills one partition's batch before moving on. This gives much larger batches than the old round-robin. Keyed records still hash with murmur2 on the key.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Accumulator model** | `send()` is async, the sender drains per-broker requests, and `buffer.memory` is the back-pressure point |
| **Metric-driven diagnosis** | Uses batch size, queue time and request latency to find the actual bottleneck |
| **Compression trade-off** | zstd = better ratio, more CPU. lz4 = fastest. Ratio depends on the data, so measure it. |
| **Idempotence + ordering** | Knows why in-flight ≤ 5 keeps ordering with idempotence |

**What they probe next:** "Effect of `acks=all` on latency?" Roughly one follower fetch round trip. Producers pipeline around it, so throughput needn't suffer. "Why does a key hot spot cap throughput?" One partition = one leader = one disk/log. You need key salting, or a better key.

---

## 6. Kafka Connect & Connector Design

**Q:** "Design a Kafka Connect source connector that ingests from a PostgreSQL CDC stream using logical replication. How do you handle schema evolution, exactly-once delivery, and connector restart after 3 days of downtime?"

**What They're Really Testing:** Whether you understand Connect's framework (workers, tasks, offset storage, converters, SMTs), Postgres replication slots, and schema compatibility rules.

!!! tip "30-second answer"
    Use Debezium on a distributed Connect cluster. Each source record carries a `sourcePartition` and `sourceOffset` (the Postgres LSN). Connect stores these in the `connect-offsets` topic and resumes from them. For exactly-once, enable `exactly.once.source.support` (KIP-618, Kafka 3.3+), which writes records and offsets in one Kafka transaction. For schema evolution, use Schema Registry with BACKWARD compatibility and only make additive changes with defaults. After 3 days down, the **replication slot** has kept 3 days of WAL on the primary. Either the disk survived and the connector catches up, or the slot was invalidated (`max_slot_wal_keep_size`) and you must re-snapshot.

### Answer

**Connector architecture:**

```
Connect worker cluster (distributed mode, group of workers, internal topics):
  connect-configs  connect-offsets  connect-status

Source task loop: poll() → List<SourceRecord> → producer → offsets flushed periodically
  SourceRecord:
    topic, key (row PK), value (Debezium envelope: before/after/op/source/ts_ms)
    sourcePartition: {"server": "pg-main"}       ← which stream
    sourceOffset:    {"lsn": 123456789, "txId": 42}  ← where we are in it

Debezium for Postgres:
  logical replication slot (pgoutput plugin) + publication
  → initial snapshot (or incremental snapshot via signal table)
  → streaming WAL changes
  → periodically confirms the flushed LSN back to Postgres so it can recycle WAL
```

**Delivery guarantees:**

- **Default is at-least-once.** Offsets are flushed every `offset.flush.interval.ms`. A crash between producing records and flushing the offset replays records, so downstream consumers must deduplicate. The Debezium LSN plus the primary key give a natural key for that.
- **Exactly-once source (KIP-618, Kafka 3.3+):** set `exactly.once.source.support=enabled` on workers and `exactly.once.support=required` on the connector. Each batch of records and its offsets go out in one transaction, and zombie tasks are fenced. Consumers must read with `read_committed`. Check that your Debezium version lists exactly-once support for the connector you use.
- **Sinks:** exactly-once depends on the sink. Either the sink store keeps the Kafka offsets in the same transaction as the data (the JDBC sink with upsert by PK is idempotent), or writes are idempotent upserts.

**Schema evolution (Avro/Protobuf + Schema Registry):**

```properties
key.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry:8081
value.converter=io.confluent.connect.avro.AvroConverter
value.converter.schema.registry.url=http://schema-registry:8081
```

| Compatibility | Guarantee | Allowed changes (Avro) | Upgrade order |
|---|---|---|---|
| **BACKWARD** (Confluent default) | New schema can read data written with the previous schema | Delete fields; add fields **with defaults** | Consumers first |
| **FORWARD** | Previous schema can read data written with the new schema | Add fields; delete fields **that had defaults** | Producers first |
| **FULL** | Both | Add/delete only fields with defaults | Any order |
| `*_TRANSITIVE` | Checked against **all** previous versions, not just the latest | Same | Same |

Type changes such as `int` → `string` aren't compatible. Use a new field (dual-write, migrate, then drop the old one) or a new topic. For CDC this is the real risk: a DBA's `ALTER TABLE` becomes a schema change in production. Gate DDL through review, and choose whether the registry should reject incompatible changes (which stalls the connector) or allow them (which breaks consumers).

**Restart after 3 days of downtime:**

```sql
-- How much WAL is the slot holding back on the primary?
SELECT slot_name, active, wal_status,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained
FROM pg_replication_slots;
```

- **The slot pins WAL indefinitely.** `wal_keep_size` is irrelevant to slots. An inactive slot can fill the primary's disk and **take down the database**. Set `max_slot_wal_keep_size` (PG 13+) to cap it, and alert on retained WAL.
- **Slot still valid** (`wal_status` = `reserved`/`extended`): restart the connector. It resumes from the stored LSN and replays 3 days of changes. Expect a big lag spike, and throttle downstream if needed.
- **Slot invalidated** (`wal_status = lost`): the changes are gone. Drop and recreate the slot, then **re-snapshot**: a Debezium incremental snapshot (chunked, runs alongside streaming) or a full snapshot. Downstream must tolerate duplicates.
- Plan this up front. A heartbeat (`heartbeat.interval.ms` + `heartbeat.action.query`) keeps the slot advancing on quiet databases. Failover slots (PG 17 `failover = true` slots synced to standbys) let CDC survive a primary failover.

**Single Message Transforms (SMTs):** per-record, stateless transforms applied in order before the converter (source) or after it (sink). Use them for routing, masking, renaming and flattening (`io.debezium.transforms.ExtractNewRecordState`). Anything stateful, or a join, belongs in Streams or Flink.

```properties
transforms=unwrap,rename
transforms.unwrap.type=io.debezium.transforms.ExtractNewRecordState
transforms.rename.type=org.apache.kafka.connect.transforms.ReplaceField$Value
transforms.rename.renames=order_id:id,customer_id:cid
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Offset management** | `sourcePartition` / `sourceOffset`, the `connect-offsets` topic, at-least-once by default |
| **Exactly-once** | KIP-618 transactional source tasks. Sink-side idempotence. |
| **Schema Registry** | Gets BACKWARD vs FORWARD right, including upgrade order |
| **CDC mechanics** | Replication slots pin WAL, `max_slot_wal_keep_size`, re-snapshot path |
| **SMT pipeline** | Stateless, per record, in order |

**What they probe next:** "Outbox pattern vs table CDC?" An outbox gives you a stable event contract that isn't tied to table shape. "How do you handle a 500 GB initial snapshot?" Incremental snapshots, a read replica, and throttling.

---

## 7. Kafka Streams: Stateful Processing

**Q:** "You need to implement a 1-hour windowed aggregate that tracks user session duration across 50M daily active users. How would you implement this with Kafka Streams? How do you handle state store recovery when a Streams instance crashes?"

**What They're Really Testing:** Whether you understand Streams' model: tasks per input partition, RocksDB state stores backed by changelog topics, standby replicas, interactive queries, and choosing the right window type.

!!! tip "30-second answer"
    Group by user ID and aggregate in a windowed state store. If "session" means activity bursts separated by idle time, use **session windows**. Use time/hopping windows only for fixed hourly buckets. Each task owns one input partition and a local RocksDB store, and every update is also written to a compacted **changelog** topic. On a crash, another instance restores the store by replaying the changelog from its last checkpoint. **Standby replicas** keep a warm copy, so failover only needs to replay the small gap.

### Answer

**Topology (Java):**

```java
StreamsBuilder builder = new StreamsBuilder();

builder.stream("user-activity", Consumed.with(Serdes.String(), activitySerde))  // key = userId
    .groupByKey()
    // "session" = activity separated by >30 min of inactivity → session windows
    .windowedBy(SessionWindows.ofInactivityGapAndGrace(Duration.ofMinutes(30), Duration.ofMinutes(5)))
    .aggregate(
        SessionStats::new,                                          // initializer
        (userId, event, agg) -> agg.add(event),                     // aggregator
        (userId, left, right) -> left.merge(right),                 // session merger
        Materialized.<String, SessionStats, SessionStore<Bytes, byte[]>>as("session-store")
            .withValueSerde(sessionStatsSerde)
            .withRetention(Duration.ofDays(1)))
    .toStream()
    .to("session-duration", Produced.with(windowedSerde, sessionStatsSerde));

// For fixed hourly buckets instead:
//   .windowedBy(TimeWindows.ofSizeAndGrace(Duration.ofHours(1), Duration.ofMinutes(5)))
```

Internal topics created automatically: `<app-id>-session-store-changelog` (compacted) and, if you re-key, `<app-id>-...-repartition`.

**Sizing sanity check:** 50M users with active windows means tens of millions of keys. That's fine spread over, say, 64 partitions (each task's RocksDB holds about 1/64). Disk and restore time per task are what you size for.

**State store recovery:**

```
Each task keeps a local .checkpoint file: the changelog offset its RocksDB store
reflects (written on commit/flush). This is a CHANGELOG offset, not an input offset.

Instance A (owns task 0_3) crashes.
Instance B is assigned task 0_3:
  1. If B has a local store for 0_3 (it's a standby, or owned it earlier), read its checkpoint.
     Otherwise start from an empty store at changelog offset 0.
  2. Restore: consume changelog partition 3 from the checkpoint to the end → write into RocksDB.
  3. Resume processing input partition 3 from the group's committed input offset.
With exactly_once_v2, input offsets, output and changelog writes commit atomically,
so state and position always agree.
```

**Making failover fast:**

- `num.standby.replicas=1`: another instance tails the changelog continuously. On failover it replays only the last few seconds.
- **Warmup replicas (KIP-441, 2.6+):** on scale-out, Streams keeps the task on its caught-up owner and warms a copy on the new instance first, moving it only once it's within `acceptable.recovery.lag`.
- Keep RocksDB on persistent volumes (StatefulSets) so a restart reuses local state instead of rebuilding.
- Size changelog compaction so restore isn't replaying stale history.

**Interactive queries:**

```java
ReadOnlySessionStore<String, SessionStats> store = streams.store(
    StoreQueryParameters.fromNameAndType("session-store", QueryableStoreTypes.sessionStore()));

// Which instance owns this key? (metadataForKey was replaced by queryMetadataForKey)
KeyQueryMetadata meta = streams.queryMetadataForKey(
    "session-store", "user-12345", Serdes.String().serializer());

if (meta.activeHost().equals(thisHost)) {
    try (KeyValueIterator<Windowed<String>, SessionStats> it = store.fetch("user-12345")) { /* ... */ }
} else {
    // forward to meta.activeHost() over your own RPC (REST/gRPC), or to a standby
    // in meta.standbyHosts() if stale reads are acceptable
}
```

**Threading model:**

```properties
num.stream.threads=4   # default 1
# Unit of parallelism = task = one partition of each co-partitioned input topic.
# 20 input partitions → 20 tasks → spread over all threads of all instances.
# More threads/instances than tasks = idle threads.
# Each task has its own store instances (a window/session store is several RocksDB segments).
```

Kafka 4.1 introduced the **streams rebalance protocol (KIP-1071)** as early access. It moves Streams task assignment to the broker, in the same spirit as KIP-848.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Window choice** | Session vs tumbling vs hopping, grace periods and late data |
| **State store model** | RocksDB + compacted changelog. Task = partition. |
| **Recovery** | Checkpoint = changelog offset. Standby and warmup replicas. Persistent volumes. |
| **Interactive queries** | `queryMetadataForKey`, routing to the active host, standby reads for availability |

**What they probe next:** "How do you handle out-of-order events?" Grace period plus `suppress(untilWindowCloses)` for final-only output. "Repartition cost?" Changing the key writes everything through a repartition topic, so avoid unnecessary `selectKey`.

---

## 8. Disk I/O & Page Cache Optimization

**Q:** "Your Kafka brokers' page cache drops from 40GB to 2GB when another process on the host does a large file operation (think a backup or a Redis BGSAVE). Throughput drops 80%. Diagnose the root cause. How do you isolate Kafka from other processes sharing the same OS?"

**What They're Really Testing:** Whether you know that Kafka's performance depends on the page cache, how Linux writeback works, and the real isolation tools (dedicated hosts/disks, cgroup v2 memory protection).

!!! tip "30-second answer"
    Kafka keeps a small JVM heap (around 6 GB) and relies on the OS page cache for the hot tail of every partition. When another process streams a large file through the cache, it evicts Kafka's pages. Consumer and follower reads that were memory hits become disk reads, which compete with appends, and latency spikes. Fixes in order of strength: **don't co-locate** (dedicated hosts or disks), then cgroup v2 `memory.low`/`memory.min` to protect Kafka's cache and `memory.max` on the noisy neighbour, then tune writeback. Tiered storage also keeps cold replays off local disk.

### Answer

**What actually breaks:**

```
Normal:  appends → page cache (dirty) → kernel flusher threads write back asynchronously
         follower + consumer fetches for recent offsets → page cache hits → sendfile()

After eviction:
  - Fetches for recent data miss the cache → synchronous disk reads on the fetch path
  - Followers slow down → ISR shrink → acks=all produce latency rises (RemoteTimeMs)
  - Random reads interleave with sequential appends → appends slow too
  - If dirty pages exceed vm.dirty_ratio, writers block in the kernel (LocalTimeMs spikes)
```

Confirm it with `free -g` or `/proc/meminfo` (Cached), `vmtouch` on segment files, `iostat -x` (read IOPS on the Kafka disks), and `sar -B` (page reclaim activity).

**Linux tuning (starting points, validate under load):**

```bash
# /etc/sysctl.d/99-kafka.conf
vm.swappiness = 1                 # avoid swapping the JVM. Prefer dropping cache.
vm.dirty_background_ratio = 5     # start background writeback early
vm.dirty_ratio = 60               # allow a large dirty buffer before writers block
                                  # (higher = smoother throughput, longer flush bursts)
vm.max_map_count = 262144         # each segment's index files are mmapped; many partitions need more
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

**OS isolation with cgroup v2 memory controls** (systemd: `MemoryLow=`, `MemoryMax=`):

```bash
# Kafka's cgroup: protect its working set (anon + page cache it has charged)
echo 48G > /sys/fs/cgroup/kafka.slice/memory.low   # best-effort protection from reclaim
#   memory.min = hard protection (never reclaimed). Use sparingly, it can trigger OOM elsewhere.

# Noisy neighbour's cgroup: cap it, so its file I/O reclaims its own cache, not Kafka's
echo 8G > /sys/fs/cgroup/backup.slice/memory.max
echo 6G > /sys/fs/cgroup/backup.slice/memory.high  # throttle + reclaim above this
```

Caveat: page cache is charged to the cgroup that **first touched** the page. Protection only works if the readers and writers of Kafka's files are in Kafka's cgroup. For a backup job, `fadvise(DONTNEED)` / `O_DIRECT` (or tools like `nocache`) stop it from polluting the cache at all.

**Disks:**

```properties
# JBOD: one log dir per physical disk (supported in KRaft since 3.7, KIP-858)
log.dirs=/data/kafka-0,/data/kafka-1,/data/kafka-2
num.recovery.threads.per.data.dir=4   # threads per dir for log recovery after unclean shutdown
```

| Layout | Pros | Cons |
|---|---|---|
| **JBOD** | Full disk bandwidth. One disk failure takes only its partitions offline, and Kafka replication re-protects them. | Uneven disk usage. Rebalance across dirs with `kafka-reassign-partitions` (log dir moves). |
| **RAID10** | Survives disk loss without broker-level recovery, and balances load | Halves usable capacity, on top of Kafka's own RF=3 |
| **RAID5/6** | Capacity-efficient | Small writes cost read-modify-write on parity (RAID5: 4 I/Os per small write). Rebuilds are slow and hurt latency. Generally avoided. |

**File system:** XFS is the usual recommendation (good parallel allocation for many large append-only files, mature at large sizes). ext4 works fine too. Both are journaling, so neither needs a long fsck after a crash. Mount with `noatime`.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Page cache primacy** | Small heap, large cache, and the chain from cache misses to ISR shrink to produce latency |
| **Isolation techniques** | Dedicated hosts first. cgroup v2 `memory.low`/`memory.max` and its charging caveat. |
| **Disk layout** | JBOD vs RAID10 trade-off, why RAID5/6 are avoided |
| **Dirty page trade-off** | Higher `dirty_ratio` gives smoother throughput but bigger flush stalls |

**What they probe next:** "Should Kafka call fsync?" `log.flush.interval.*` is off by default. Replication across AZs is the durability mechanism, and forcing fsync costs a lot of throughput. "How does tiered storage change this?" Historical reads come from object storage, not local disk, so replays don't evict the hot tail.

---

## 9. Cluster Scaling & Partition Reassignment

**Q:** "You add 3 brokers to a 6-broker Kafka cluster. Partition distribution is now heavily skewed (old brokers at 80% load). Walk through the partition reassignment process without downtime. How do you control the impact on production traffic?"

**What They're Really Testing:** Whether you know that Kafka never moves data on its own, how reassignment and throttles work, and how to keep the operation safe.

!!! tip "30-second answer"
    New brokers get **no** existing partitions. Kafka doesn't rebalance automatically. Generate a plan (or let Cruise Control compute one), execute it **with a replication throttle**, move a batch of partitions at a time, watch under-replicated partitions and produce latency, then run `--verify`. That step also **removes the throttle**. Finally, run preferred leader election so leadership (and request load) spreads to the new brokers. Tiered storage makes this far cheaper, because only the local hot tail has to be copied.

### Answer

**Reassignment with the stock tool:**

```bash
# 1. Generate a candidate plan (simple: doesn't consider load, only counts)
cat > topics.json <<'EOF'
{"version": 1, "topics": [{"topic": "orders"}, {"topic": "payments"}]}
EOF
kafka-reassign-partitions.sh --bootstrap-server kafka:9092 \
  --topics-to-move-json-file topics.json --broker-list "1,2,3,4,5,6,7,8,9" --generate
# Prints "Current" (save it as rollback.json) and "Proposed" (save it as plan.json)

# 2. Execute with a throttle (bytes/sec, applied to the brokers involved)
kafka-reassign-partitions.sh --bootstrap-server kafka:9092 \
  --reassignment-json-file plan.json --execute --throttle 100000000   # 100 MB/s

# 3. Poll until complete. --verify also REMOVES the throttle configs once done.
kafka-reassign-partitions.sh --bootstrap-server kafka:9092 \
  --reassignment-json-file plan.json --verify

# Abort an in-flight reassignment if things go wrong
kafka-reassign-partitions.sh --bootstrap-server kafka:9092 \
  --reassignment-json-file plan.json --cancel
```

**How the move works:** the controller sets replicas to old ∪ new. The new replicas fetch from the leader like any follower, catch up and join the ISR. Then the controller drops the old replicas and, if needed, moves leadership. At no point are there fewer in-sync copies than before.

**Throttling:**

```
--throttle sets per-broker dynamic configs:
  leader.replication.throttled.rate / follower.replication.throttled.rate
and per-topic lists of which replicas are throttled:
  leader.replication.throttled.replicas / follower.replication.throttled.replicas
Normal ISR replication is NOT throttled, only the moving replicas.

Sizing: throttle ≈ (disk or NIC headroom at peak) − (normal produce + replication + consumer traffic).
Example: 25 Gb/s NIC (~3 GB/s), peak usage 2 GB/s → leave a safety margin, start at 200–500 MB/s.
Too low: a reassignment that never catches up on a busy partition (data arrives faster than the throttle).
Forgotten throttle: if you never run --verify, the throttle stays and later slows real recovery.
```

**What to watch:** `UnderReplicatedPartitions` (expected for moving partitions only), `kafka.server:type=ReplicaManager,name=ReassigningPartitions`, `ReplicationBytesInPerSec`/`ReplicationBytesOutPerSec`, produce p99 (`RequestMetrics` `TotalTimeMs` for `Produce`), consumer lag, and disk usage on the **source** brokers (they hold both copies until the move finishes).

**Cruise Control** (LinkedIn, open source) models CPU, disk, network and replica counts per broker, and proposes a minimal set of moves that satisfies a prioritized list of goals (rack awareness, capacity, replica and leader distribution). It also runs them in batches with throttles:

```bash
# Dry run first (the default), then execute
curl -X POST "http://cruise-control:9090/kafkacruisecontrol/add_broker?brokerid=7,8,9&dryrun=true"
curl -X POST "http://cruise-control:9090/kafkacruisecontrol/rebalance?dryrun=false&replication_throttle=200000000&concurrent_partition_movements_per_broker=5"
```

On Kubernetes, Strimzi wraps this as `KafkaRebalance` resources (including `add-brokers` / `remove-brokers` modes).

**Preferred leader election:**

```bash
kafka-leader-election.sh --bootstrap-server kafka:9092 --election-type PREFERRED --all-topic-partitions
# The preferred leader is the first replica in the list. auto.leader.rebalance.enable=true (default)
# also does this periodically when imbalance > leader.imbalance.per.broker.percentage (10%).
```

**Adding brokers in KRaft:**

1. Format storage with the cluster ID (`kafka-storage.sh format`).
2. Start the brokers. They register with the controller quorum and get metadata from the `__cluster_metadata` log, not from ZooKeeper.
3. They're idle until you reassign.
4. Reassign in batches, then run preferred leader election.
5. Confirm 0 under-replicated partitions and balanced disk/network usage, and add the new brokers to monitoring.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **No auto-rebalance** | Knows new brokers stay empty until you act |
| **Throttling** | How to size it, what it applies to, and that `--verify` clears it |
| **Batching / rollback** | Moves in batches, keeps the "current" assignment for rollback, knows `--cancel` |
| **Cruise Control** | Goal-based, load-aware planning. Strimzi integration. |
| **Preferred leaders** | Leadership balance after the move |

**What they probe next:** "How do you remove a broker?" Reassign everything off it (Cruise Control `remove_broker`), then unregister it in KRaft (`kafka-cluster.sh unregister`). "Why not just add partitions?" It changes key→partition mapping for keyed topics and doesn't move existing data.

---

## 10. Monitoring, Metrics & Alerting

**Q:** "Design a monitoring dashboard for a Kafka cluster handling 1M messages/second. What metrics do you track? What are the alert thresholds? How do you detect consumer lag before it causes problems?"

**What They're Really Testing:** Whether you know the handful of metrics that indicate real trouble, and whether you treat consumer lag as **time**, not message counts.

!!! tip "30-second answer"
    Page on things that mean data is at risk or unavailable: **offline partitions > 0**, **under-min-ISR partitions > 0**, no active controller or a lost KRaft quorum, and sustained under-replicated partitions. Warn on saturation: request handler and network thread idle % falling, request queue growth, produce/fetch p99 latency. Measure consumer lag as **time behind** (seconds), with alerts on lag that keeps growing, not on a fixed message count. Burrow-style evaluation or `kafka-lag-exporter` does this.

### Answer

**Core broker metrics (JMX):**

| Metric | Why | Alert |
|---|---|---|
| `kafka.controller:type=KafkaController,name=OfflinePartitionsCount` | No leader → unavailable | > 0 → **page** |
| `kafka.server:type=ReplicaManager,name=UnderMinIsrPartitionCount` | `acks=all` writes failing | > 0 → **page** |
| `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | Reduced redundancy | > 0 for 5+ min (outside planned reassignment) |
| `kafka.controller:type=KafkaController,name=ActiveControllerCount` | Exactly one active controller in the KRaft quorum | Sum across controllers ≠ 1 → **page** |
| `kafka.server:type=raft-metrics` (`current-leader`, `high-watermark`, commit latency) | KRaft metadata quorum health | No leader / quorum lag growing |
| `kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent` | I/O thread saturation | < 0.3 sustained |
| `kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent` | Network thread saturation | < 0.3 sustained |
| `kafka.network:type=RequestChannel,name=RequestQueueSize` | Requests waiting for a handler thread | Growing trend |
| `kafka.network:type=RequestMetrics,name=TotalTimeMs,request=Produce` (and `Fetch`), with the `LocalTimeMs` / `RemoteTimeMs` / `RequestQueueTimeMs` breakdown | Where latency comes from: disk vs replication vs queueing | p99 above SLO |
| `kafka.server:type=ReplicaManager,name=IsrShrinksPerSec` / `IsrExpandsPerSec` | Flapping followers | Sustained non-zero |
| `kafka.log:type=LogCleaner,name=DeadThreadCount` | Compaction stopped (compacted topics, `__consumer_offsets` grow forever) | > 0 |
| `BytesInPerSec` / `BytesOutPerSec` (BrokerTopicMetrics) | Capacity | > ~70% of NIC or disk throughput |
| OS: disk util/await, page cache hit ratio, network, open file descriptors, JVM GC pause | Root-cause context | Per host baseline |

**Consumer lag:** offset lag = log end offset − committed offset. The number by itself is meaningless: 1M messages is 1 s on one topic and a week on another. Alert on:

- **Time lag**: how old is the record at the committed offset, or lag ÷ consumption rate.
- **Lag trend**: lag growing over a window while the consumer's committed offset isn't advancing means it's stalled. Lag stable or shrinking is fine.

Burrow (LinkedIn) evaluates each partition over a sliding window with these rules. `kafka-lag-exporter` and most managed platforms export time lag directly. With KIP-848, the broker also exposes group state and assignment, which helps spot stuck members.

```python
# Offset lag per partition for one group (kafka-python). Feed this into a time-lag calculation
# by sampling it periodically along with the consume rate.
from kafka import KafkaAdminClient, KafkaConsumer

def group_lag(bootstrap: str, group_id: str) -> dict:
    admin = KafkaAdminClient(bootstrap_servers=bootstrap)
    committed = admin.list_consumer_group_offsets(group_id)   # {TopicPartition: OffsetAndMetadata}
    probe = KafkaConsumer(bootstrap_servers=bootstrap)        # no group_id: doesn't join the group
    try:
        end = probe.end_offsets(list(committed))
        return {tp: end[tp] - meta.offset for tp, meta in committed.items()}
    finally:
        probe.close()
        admin.close()
```

From the CLI: `kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group payments` shows CURRENT-OFFSET, LOG-END-OFFSET and LAG per partition. Share groups have their own lag metrics, which are part of 4.2's production-ready release.

**Alert tiers:**

```yaml
P0 (page):   OfflinePartitions > 0, UnderMinIsr > 0, controller quorum has no leader,
             consumer time-lag on a critical pipeline > SLO and growing
P1 (urgent): UnderReplicated > 0 for 5+ min (not during reassignment),
             handler/network idle < 0.2, produce p99 > SLO for 10 min, disk > 80%
P2 (ticket): IsrShrinks sustained, disk > 70%, BytesIn > 70% capacity, LogCleaner dead thread
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Signal vs noise** | Pages only on data loss/unavailability. Saturation metrics are warnings. |
| **Latency decomposition** | Uses Local / Remote / Queue time to localize the bottleneck |
| **Lag semantics** | Time lag and trend, not static message counts |
| **KRaft awareness** | Monitors the controller quorum, not ZooKeeper |

**What they probe next:** "Consumer is lagging, what now?" Check whether processing time per record went up, whether there are more partitions than consumers can handle, rebalance storms, or a hot partition. "How do you capacity-plan?" Bytes in × RF for disk and network, plus fan-out of consumers for bytes out.

---

## 11. Security: TLS, SASL, ACLs

**Q:** "Design a multi-tenant Kafka cluster serving 5 teams. Each team must only read/write their own topics. All traffic must be encrypted in transit. How do you configure Kafka security? How do you rotate certificates without downtime?"

**What They're Really Testing:** Whether you understand listeners and security protocols, the authentication options (mTLS, SCRAM, OAUTHBEARER), ACLs with prefixed resource patterns, quotas for noisy tenants, and certificate rotation in practice.

!!! tip "30-second answer"
    Use **SASL_SSL** listeners: TLS for encryption, plus SCRAM or OAUTHBEARER (OIDC) for identity, or mTLS where you control client certs. Turn on `StandardAuthorizer` (KRaft) with `allow.everyone.if.no.acl.found=false`. Give each team **prefixed ACLs** (`team-a.*` topics, `team-a.*` consumer groups, transactional IDs) and enforce naming at topic creation. Add **client quotas** per team so one tenant can't starve the others. Rotate certificates by reloading keystores and truststores dynamically (no restart). Rotate a CA by trusting old + new first, then reissuing, then removing the old CA.

### Answer

**Layers:**

| Layer | Options | Notes |
|---|---|---|
| Encryption | TLS (`SSL` or `SASL_SSL` listeners) | Disables zero-copy (`sendfile`), so budget extra broker CPU |
| Authentication | mTLS (cert DN → principal), SASL/SCRAM-SHA-512, SASL/OAUTHBEARER, SASL/GSSAPI (Kerberos) | SCRAM credentials are stored in the **KRaft metadata log** (`kafka-configs.sh --alter --add-config 'SCRAM-SHA-512=[password=...]'`, or `kafka-storage.sh format --add-scram` to bootstrap) |
| Authorization | ACLs via `org.apache.kafka.metadata.authorizer.StandardAuthorizer` | `AclAuthorizer` was ZooKeeper-only and is gone in 4.0 |
| Isolation | Client quotas (produce/fetch bytes/s, request %) per user or client ID | Without these, multi-tenancy is only an access-control feature |

**Broker configuration (KRaft, abbreviated):**

```properties
listeners=SASL_SSL://:9094,CONTROLLER://:9093
advertised.listeners=SASL_SSL://kafka-1.example.com:9094
inter.broker.listener.name=SASL_SSL
listener.security.protocol.map=SASL_SSL:SASL_SSL,CONTROLLER:SSL

ssl.keystore.type=PEM                      # PEM supported since 2.7 (KIP-651), easier with cert-manager
ssl.keystore.location=/etc/kafka/tls/broker.pem
ssl.truststore.type=PEM
ssl.truststore.location=/etc/kafka/tls/ca-bundle.pem
ssl.enabled.protocols=TLSv1.3,TLSv1.2

sasl.enabled.mechanisms=SCRAM-SHA-512,OAUTHBEARER
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
# OAUTHBEARER: validate real JWTs against the IdP's JWKS (KIP-768). The default
# OAUTHBEARER handlers accept UNSECURED tokens and are for development only.
listener.name.sasl_ssl.oauthbearer.sasl.server.callback.handler.class=\
  org.apache.kafka.common.security.oauthbearer.OAuthBearerValidatorCallbackHandler
listener.name.sasl_ssl.oauthbearer.sasl.jaas.config=\
  org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required;
sasl.oauthbearer.jwks.endpoint.url=https://idp.example.com/.well-known/jwks.json
sasl.oauthbearer.expected.audience=kafka

authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
super.users=User:admin;User:broker          # bypass ALL ACLs: keep this list tiny
allow.everyone.if.no.acl.found=false        # deny by default
```

**ACLs for one tenant** (the admin client authenticates with `--command-config`):

```bash
# Producer: write + describe on team-a.* topics, and its transactional IDs if it uses EOS
kafka-acls.sh --bootstrap-server kafka:9094 --command-config admin.properties \
  --add --allow-principal User:team-a-producer \
  --operation Write --operation Describe \
  --topic team-a. --resource-pattern-type prefixed
kafka-acls.sh --bootstrap-server kafka:9094 --command-config admin.properties \
  --add --allow-principal User:team-a-producer \
  --operation Write --operation Describe \
  --transactional-id team-a. --resource-pattern-type prefixed

# Consumer: read on team-a.* topics AND team-a.* groups (both prefixed)
kafka-acls.sh --bootstrap-server kafka:9094 --command-config admin.properties \
  --add --allow-principal User:team-a-consumer \
  --operation Read --operation Describe \
  --topic team-a. --group team-a. --resource-pattern-type prefixed

# Revoke = remove the ALLOW binding (a DENY binding is a separate, explicit rule that overrides allows)
kafka-acls.sh --bootstrap-server kafka:9094 --command-config admin.properties \
  --remove --allow-principal User:team-a-producer \
  --operation Write --topic team-a. --resource-pattern-type prefixed

# Quota per tenant
kafka-configs.sh --bootstrap-server kafka:9094 --command-config admin.properties --alter \
  --entity-type users --entity-name team-a-producer \
  --add-config 'producer_byte_rate=52428800,consumer_byte_rate=104857600,request_percentage=50'
```

**Certificate rotation without downtime:**

- **Leaf certificate renewal (same CA):** Kafka reloads SSL configs dynamically (KIP-226). Write the new keystore and run `kafka-configs.sh --alter --entity-type brokers --entity-name <id> --add-config listener.name.sasl_ssl.ssl.keystore.location=<path>`. Re-pointing to the same path triggers a reload. New connections use the new certificate, existing ones carry on. No restart, so short-lived certificates from cert-manager or Vault are practical.
- **CA rotation:** (1) add the new CA to **every** truststore, brokers and clients, keeping the old one. (2) Reissue broker and client certificates from the new CA. (3) Once nothing presents an old-CA certificate, remove the old CA from the truststores. Getting the order wrong breaks the handshake for whoever got ahead.
- For SCRAM/OAuth, the credentials rotate independently of TLS. Plan both.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Defense in depth** | TLS + authentication + ACLs + quotas, and knows the TLS CPU cost |
| **KRaft-era config** | `StandardAuthorizer`, SCRAM in the metadata log, `kafka-acls --bootstrap-server` |
| **Deny by default** | `allow.everyone.if.no.acl.found=false`, a minimal `super.users` |
| **Tenant model** | Prefixed ACLs on topics, groups and transactional IDs, plus naming enforcement |
| **Certificate rotation** | Dynamic reload, and the CA rotation ordering |

**What they probe next:** "How do you stop a team creating topics outside its prefix?" A Create ACL on the prefixed topic pattern only, or create topics via GitOps/an operator rather than through clients. "Encryption at rest?" Disk or volume encryption. Kafka doesn't encrypt segments itself.

---

## 12. Kafka vs Pulsar vs Redpanda

**Q:** "Your team is choosing between Kafka, Pulsar, and Redpanda for a new real-time data platform. Walk through the architectural differences. What workloads would make you choose each one?"

**What They're Really Testing:** Whether you can compare architectures accurately (coupled vs disaggregated storage, thread-per-core C++ vs JVM) and tie the choice to workload, team and cost rather than benchmarks.

!!! tip "30-second answer"
    **Kafka** is the default: the biggest ecosystem (Connect, Streams, Flink integrations, every managed cloud). In 4.x it's simpler to run (KRaft only) and has open-source tiered storage and queues. **Pulsar** separates stateless brokers from BookKeeper storage. It's strong for multi-tenancy, geo-replication and very many topics, but has more moving parts. **Redpanda** speaks the Kafka API from a single C++ binary (thread-per-core, Raft per partition, no JVM or page cache). Choose it for tail latency and simpler ops, but check the license and the smaller ecosystem. Also consider **object-storage-native** Kafka-compatible systems (WarpStream, AutoMQ, Bufstream) when cross-AZ network cost dominates and higher latency is acceptable.

### Answer

| | **Apache Kafka 4.x** | **Apache Pulsar** | **Redpanda** |
|---|---|---|---|
| Language/runtime | Java/Scala, JVM | Java, JVM | C++ (Seastar) |
| Storage | Broker-local log + optional tiered storage (KIP-405, open source since 3.9) | Stateless brokers. Apache BookKeeper "bookies" store segmented ledgers. Offload to object storage. | Broker-local log + tiered storage to S3/GCS/Azure |
| Metadata/consensus | KRaft controller quorum (ZooKeeper removed in 4.0) | ZooKeeper (or etcd / Oxia) for metadata | Raft per partition + internal controller Raft group |
| Replication | ISR, leader-follower pull | Quorum writes to bookies (write quorum / ack quorum) | Raft per partition |
| I/O model | OS page cache + `sendfile()` | Bookies: journal + ledger storage | Thread-per-core, own cache, direct I/O (bypasses page cache) |
| Consumption | Consumer groups, plus share groups (queues) since 4.2 | Exclusive, failover, shared and key-shared subscriptions natively | Kafka API (consumer groups) |
| Scaling a broker in/out | Must move partition data (cheap with tiered storage) | Brokers are stateless. Bundles move quickly with no data copy. | Must move partition data (helped by tiered storage) |
| License | Apache 2.0 | Apache 2.0 | Source-available (BSL for core, enterprise license for some features). Check current terms. |

**When to choose each:**

- **Kafka:** the ecosystem matters (Debezium/Connect, Streams, Flink, Schema Registry, managed offerings such as MSK, Confluent, Aiven). The team already knows it. You need mature transactions/EOS. Kafka 4.x removed the "ZooKeeper tax" and covers queue use cases with share groups.
- **Pulsar:** native multi-tenancy (tenants/namespaces with quotas and policies), built-in geo-replication, millions of topics, or fast elastic scaling of the serving layer. The cost is more components to operate (brokers + bookies + metadata store) and a smaller talent pool.
- **Redpanda:** tight p99 latency targets, small ops teams that want one binary with no JVM tuning, and edge or resource-constrained deployments. Kafka API compatibility means most clients work, but check the features you depend on (transactions, specific Connect or Streams behaviour) and the licensing terms.
- **Diskless / object-storage-native** (WarpStream, now part of Confluent; AutoMQ; Bufstream; Kafka's own KIP-1150 "diskless topics" proposal): writes go straight to S3-class storage, with no inter-AZ replication traffic. This can be dramatically cheaper for high-volume logs and telemetry, with end-to-end latency in the hundreds of milliseconds.

**Migration strategy (Kafka → another Kafka-API system, e.g. Redpanda or a managed Kafka):**

```
1. Replicate with MirrorMaker 2 (Connect-based; MirrorMaker 1 was removed in Kafka 4.0)
   or the vendor's tool. MM2 also translates consumer group offsets (checkpoints).
2. Move consumers first, starting from translated offsets (they must tolerate some duplicates).
3. Move producers. Stop replication once the old cluster is drained.
4. Keep the old cluster read-only for a rollback window.
```

Pulsar isn't Kafka-wire-compatible out of the box. You'd use the Kafka-on-Pulsar protocol handler or Pulsar IO connectors, or dual-write at the application layer, which makes the migration a much larger project.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Architecture accuracy** | BookKeeper separation in Pulsar, thread-per-core + Raft in Redpanda, KRaft + tiered storage in Kafka 4.x |
| **Trade-off articulation** | Ties the choice to workload, team skills, cost (cross-AZ traffic) and license |
| **Currency** | Doesn't claim Kafka needs ZooKeeper or lacks tiered storage or queues |
| **Migration** | MM2 with offset translation, consumers-first cutover, rollback plan |

**What they probe next:** "Where does the cost go in a cloud Kafka deployment?" Often cross-AZ replication and consumer traffic, more than compute. Mitigations: fetch-from-follower, tiered storage, diskless designs. "Would you build on Kafka Streams or Flink?" Streams is a library embedded in your service. Flink is a separate cluster with richer windowing, SQL and state, at the cost of more operations.

---

> *These 12 questions cover Kafka from storage internals to production operations and platform choice. Re-check the version baseline at the top when Kafka 5.0 ships.*
