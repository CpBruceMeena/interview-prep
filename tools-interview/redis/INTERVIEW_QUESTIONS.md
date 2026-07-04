# 🔴 Redis — Staff-Level Interview Questions

> *12 questions covering Redis internals, data structures, persistence, clustering, and operational excellence — every question expects principal engineer-level depth with production patterns and failure analysis.*

---

## Table of Contents

1. [Data Structure Internals](#1-data-structure-internals)
2. [Persistence: RDB vs AOF](#2-persistence-rdb-vs-aof)
3. [Replication: Partial Resync & PSYNC2](#3-replication-partial-resync-psync2)
4. [Redis Sentinel: Auto-Failover](#4-redis-sentinel-auto-failover)
5. [Redis Cluster: Hash Slots & Resharding](#5-redis-cluster-hash-slots-resharding)
6. [Expiry & Eviction Policies](#6-expiry-eviction-policies)
7. [Lua Scripting & MULTI/EXEC](#7-lua-scripting-multiexec)
8. [Streams & Consumer Groups](#8-streams-consumer-groups)
9. [Memory Optimization & Fragmentation](#9-memory-optimization-fragmentation)
10. [Distributed Locks & Redlock](#10-distributed-locks-redlock)
11. [Cache Strategies: Thundering Herd](#11-cache-strategies-thundering-herd)
12. [Redis 7+ Features: ACLs, Functions](#12-redis-7-features-acls-functions)

---

## 1. Data Structure Internals

**Q:** "A user stores 1M small key-value pairs (32B key, 64B value). Redis reports 2GB RSS. Diagnose the overhead. How does Redis store strings (SDS), sets (intset vs skiplist), and hashes (ziplist vs hashtable)?"

**What They're Really Testing:** Whether you understand Redis's memory-efficient data structures — SDS overhead, dict hashing, and encoding thresholds.

### Answer

**Memory Overhead Breakdown:**

```
Raw data: 1M × (32 + 64) = 96MB
Reported RSS: 2GB → 20× overhead

Sources of overhead:
├── Server base memory: ~1MB
├── dictEntry (24 bytes each): 1M × 24 = 24MB
├── SDS header for key (sdshdr8: 3 bytes + 32 bytes data = 35 bytes): 35MB
├── SDS header for value (sdshdr8: 3 bytes + 64 bytes data = 67 bytes): 67MB
├── robj (16 bytes each): 1M × 16 = 16MB
├── Hash table buckets: 2M × 8 = 16MB (load factor ~0.5)
├── jemalloc fragmentation: 10-30% → 200-600MB
├── Active keyspace metadata: ~100MB
└── Total: ~450MB + fragmentation → 1.5-2GB (consistent!)
    
Diagnosis: Normal! The overhead is from Redis's C structs and jemalloc.
```

**SDS (Simple Dynamic String) Structure:**

```c
struct __attribute__((__packed__)) sdshdr8 {
    uint8_t len;         // Used length (1 byte) → O(1) strlen
    uint8_t alloc;       // Allocated length
    unsigned char flags; // Type flags (sdshdr5, 8, 16, 32, 64)
    char buf[];          // Binary safe (can contain null bytes!)
};

// Why SDS, not C strings?
// C strings: O(n) strlen, terminated by '\0', not binary safe
// SDS: O(1) strlen, binary safe, pre-allocation for append efficiency
```

**Encoding Optimizations:**

```yaml
Type    | Encoding | Condition                    | Memory/Key
--------|----------|------------------------------|---------------
String  | int      | Value is 64-bit integer       | 8 bytes (no SDS!)
String  | embstr   | Length ≤ 44 bytes             | Single malloc (robj + SDS contiguous)
String  | raw      | Length > 44 bytes             | Two mallocs (robj + SDS separately)
Hash    | ziplist  | ≤ 512 entries AND all ≤ 64B   | ~37 bytes per field
Hash    | hashtable| Threshold exceeded            | ~200 bytes per field (dict overhead)
Set     | intset   | All integers AND ≤ 512        | Sorted array → binary search O(log N)
Set     | hashtable| Threshold exceeded            | dict with NULL values
ZSet    | ziplist  | ≤ 128 entries AND all ≤ 64B   | Compact list of score-member pairs
ZSet    | skiplist | Threshold exceeded            | skiplist + dict hybrid for O(log N)
List    | quicklist| Always (replaced linkedlist)  | Linked list of ziplist segments

# Memory savings via encoding:
# 1M hashes, 5 fields each, 20B values:
#   ziplist: ~185MB
#   hashtable: ~1GB
#   Ratio: 5.4× savings!
```

**Active Defragmentation (Redis 4+):**

```bash
activedefrag yes
active-defrag-threshold-lower 10    # Start defrag when fragmentation > 10%
active-defrag-threshold-upper 100   # Max fragmentation before aggressive defrag
active-defrag-cycle-min 25          # % of CPU time for defrag (minimum)
active-defrag-cycle-max 75          # % of CPU time for defrag (maximum)
active-defrag-ignore-bytes 100mb   # Skip if frag overhead < 100MB
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **SDS internals** | Knows SDS is a length-prefixed, binary-safe string with pre-allocation |
| **Encoding thresholds** | Can recite the magic numbers: 44 bytes for embstr, 512 entries for ziplist |
| **Memory diagnosis** | Can compute memory overhead and identify jemalloc fragmentation |
| **Active defrag** | Knows Redis can defragment in-place without downtime |

---

## 2. Persistence: RDB vs AOF

**Q:** "Your Redis instance holds 50GB and crashes. Walk through recovery. Compare RDB vs AOF. How does AOF rewrite work, and why might it cause latency spikes?"

**What They're Really Testing:** Whether you understand Redis's persistence trade-offs — fork() overhead, COW memory amplification, and the recovery time budget.

### Answer

**RDB Snapshot (BGSAVE):**

```
fork() → child process → writes snapshot to disk (.rdb file)

Memory during BGSAVE:
  1. Parent process: 50GB dataset
  2. fork() creates child: pages are marked COW (Copy-On-Write)
  3. If parent continues writing: each modified page is COPIED
  4. Peak RSS: 50GB + (write rate × COW duration)
     Example: 10K writes/s × 4KB pages × 10s = 400MB → 50.4GB peak
  
  5. If no writes during BGSAVE: child shares all pages with parent (zero overhead!)

RDB file format:
  MAGIC("REDIS") | RDB_VERSION | DATABASE_SECTION | EOF_CHECKSUM
  Compressed via LZF (optional: rdbcompression yes)

Recovery time: 50GB RDB on NVMe → ~30-60 seconds (sequential read)
```

**AOF (Append-Only File):**

```yaml
AOF format: Redis protocol commands, appended:
  SET key1 value1\r\n
  SET key2 value2\r\n
  ...

fsync modes:
  always:
    - fsync() AFTER every write command
    - ~200 ops/s (fsync bottleneck)
    - Never lose data (durability on every write)
    
  everysec (recommended):
    - bg thread fsyncs every 1 second
    - ~100K+ ops/s
    - Lose ≤1 second of data on crash
    
  no:
    - OS decides when to flush (typically 30s)
    - Maximum throughput
    - Lose 30-60s of data

50GB AOF replay:
  - Parse protocol commands
  - Re-execute ALL write commands sequentially
  - ~5-30 minutes (vs 30-60s for RDB!)
```

**AOF Rewrite Mechanics:**

```
State before rewrite:
  AOF file: 50GB (accumulated over days/weeks)
  
Rewrite triggers:
  auto-aof-rewrite-percentage 100     # Grow 100% before rewrite
  auto-aof-rewrite-min-size 64mb      # Minimum size to trigger

Rewrite process:
  1. fork() → child process
  2. Child reads entire dataset into memory
  3. Child writes MINIMAL commands:
     Instead of: SET k1 v1 ... SET k1 v2 ... (multiple updates to same key)
     Writes: SET k1 v2 (only the latest value!)
  4. Parent appends all new writes to a buffer (during rewrite)
  5. When child finishes: parent swaps old file with new file
  6. Parent appends buffered writes to new file

Latency spikes during rewrite:
  - fork() on 50GB instance: ~500ms-2s (page table copy)
  - COW amplification: heavy writes during rewrites double memory
  - Page cache churn: child reads all pages, evicting hot data
  - Solution: auto-aof-rewrite-min-size = 4GB (never rewrite while busy)

Tuning for production:
  appendonly yes
  appendfsync everysec
  no-appendfsync-on-rewrite yes  # Don't fsync during rewrite (OS handles it)
  auto-aof-rewrite-percentage 200  # Less frequent rewrites
  auto-aof-rewrite-min-size 4gb
```

**RDB + AOF Combined (Best Practice):**

```yaml
# RDB for fast recovery + AOF for durability
save 900 1     # RDB snapshot after 15 min if ≥1 key changed
save 300 10    # RDB snapshot after 5 min if ≥10 keys changed
save 60 10000  # RDB snapshot after 1 min if ≥10000 keys changed
appendonly yes # AOF for durability (lose ≤1s)

# Recovery order:
# 1. Check AOF: if exists, load it (more complete)
# 2. Else check RDB: load it
# 3. Empty DB if neither exists

# Strategy: combine for best of both
# - RDB: fast recovery (30-60s for 50GB)
# - AOF: no data loss (≤1s on crash)
# - Recovery loads AOF first → if AOF is corrupt, fall back to RDB
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **fork() overhead** | Explains COW pages, page table copy time commensurate with RSS |
| **AOF rewrite cost** | Knows rewrite fork is same as BGSAVE fork — double memory during heavy writes |
| **Recovery order** | AOF is preferred (more complete), falls back to RDB |
| **fsync trade-offs** | Can compare always (200 ops/s) vs everysec (100K ops/s) |

---

## 3. Replication: Partial Resync & PSYNC2

**Q:** "A Redis replica disconnects from its master for 45 seconds. When it reconnects, the master decides to do a FULL resync instead of a partial resync. Diagnose why. How does PSYNC2 (Redis 4+) improve on PSYNC?"

**What They're Really Testing:** Whether you understand Redis replication's internal state machine — replication ID, offset, and backlog buffer sizing.

### Answer

**PSYNC2 Protocol:**

```
Master maintains:
  - master_replid (random ID, changes on failover)
  - master_repl_offset (current position in replication stream)
  - repl_backlog_buffer (circular buffer, size = repl-backlog-size)
  - repl_backlog_histlen (how much is actually stored)
  - repl_backlog_idx (current write position in circular buffer)

Replica connects:
  1. REPLCONF listening-port 6379
  2. REPLCONF capa psync2
  3. PSYNC ? -1 (first connect) or PSYNC <replid> <offset> (reconnect)

Master checks:
  if replica_replid == master_replid AND offset in backlog:
    → PARTIAL RESYNC (CONTINUE)
  else:
    → FULL RESYNC (send RDB)
```

**Why Full Resync Happened:**

```yaml
Two possibilities:
  
1. Backlog too small:
    repl-backlog-size = 1MB  (default!)
    Replica disconnected for 45 seconds
    During that time: 100K ops × 200 bytes = 20MB of new data
    Backlog only holds 1MB → master wrote past the replica's offset!
    Result: FULL RESYNC

2. Master failover during disconnection:
    Replica was connected to Master-A (replid=abc)
    Master-A crashes, replica reconnects to Master-B (replid=xyz)
    Master-B's replid ≠ abc → FULL RESYNC (unless PSYNC2 can handle it)

Fix:
    repl-backlog-size 500mb   # Hold 500MB of replication data
    # At 20MB/45s = ~444KB/s → 500MB = ~18min of buffer
```

**Backlog Sizing Formula:**

```bash
# repl-backlog-size = (expected throughput) × (max replica disconnect time) × 2

# Example: 10MB/s writes, 5 minute replica disconnect tolerance
# 10MB/s × 300s × 2 = 6GB

repl-backlog-size 6gb
# Note: backlog memory is allocated at master startup
# NOT dynamically grown! Set it correctly upfront.
```

**PSYNC2 Improvement (Redis 4.0+):**

```
PSYNC (pre-4.0): After master failover, ALL replicas need full resync
  - Master-A fails → replica promotes to master-B
  - master-B has DIFFERENT replication ID
  - Other replicas: PSYNC old-id old-offset → master-B: "id mismatch → FULL RESYNC"

PSYNC2 (4.0+): Master keeps TWO replication IDs
  - master_replid: current ID (changed after failover)
  - master_replid2: previous ID (old master's ID)
  - second_repl_offset: offset where ID switch happened

  Replica connects with old replid + offset:
  if replica_replid == master_replid2 AND offset < second_repl_offset:
    → PARTIAL RESYNC (because we know the old ID's history!)
  
  Example:
    Master-A (replid=abc) fails at offset 50000
    Master-B promotes (replid=xyz, replid2=abc, second_repl_offset=50001)
    Replica: PSYNC abc 45000
    Master-B: abc == replid2, 45000 < 50001 → CONTINUE (partial resync!)
```

**Connection Handling (Replication Timeout):**

```bash
# /etc/redis/redis.conf
repl-timeout 60                       # Master/replica timeout (default: 60s)
repl-backlog-size 1gb                 # Sufficient backlog buffer
repl-backlog-ttl 3600                 # Release backlog after 1h if no replicas
repl-diskless-sync yes                # Send RDB directly via socket (no temp file)
repl-diskless-sync-delay 5            # Wait 5s to batch multiple replicas
replica-serve-stale-data yes          # Serve stale data during FULL resync
replica-read-only yes                 # Replicas are read-only (enforced)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PSYNC2 mechanism** | Understands dual replication IDs for seamless failover |
| **Backlog sizing** | Can compute required backlog size from throughput and disconnect tolerance |
| **Replication timeout** | Knows repl-timeout vs repl-backlog-ttl behavior |
| **Diskless sync** | Understands diskless sync avoids RDB temp file bottlenecks |

---

## 4. Redis Sentinel: Auto-Failover

**Q:** "Design a Redis high-availability setup for a payment service that requires <5 seconds of downtime during failover and zero data loss. Walk through Redis Sentinel's monitoring, quorum, and failover process."

**What They're Really Testing:** Whether you understand Sentinel's distributed election protocol — quorum-based ODOWN detection, leader election via Raft-inspired consensus, and the failover state machine.

### Answer

**Sentinel Architecture:**

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Sentinel A     │    │  Sentinel B     │    │  Sentinel C     │
│  (voting)       │───▶│  (voting)       │───▶│  (voting)       │
│  port 26379     │    │  port 26379     │    │  port 26379     │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌───────────────────────────────────────────────────────────────┐
│                       Redis Master:6379                        │
│  Monitors: PING every 1s (down-after-milliseconds 5000)       │
│  Monitored by ALL 3 sentinels                                  │
│  Subjective Down (SDOWN): single sentinel can't reach          │
│  Objective Down (ODOWN): quorum sentinels agree               │
├───────────────────────────────────────────────────────────────┤
│                       Replica 1:6380                           │
│                       Replica 2:6381                           │
└───────────────────────────────────────────────────────────────┘
```

**Failover Process (Step by Step):**

```
Phase 1: ODOWN Detection
  Sentinel A detects: PONG timeout (no response in 5s)
  Sentinel A marks master as sdown (subjectively down)
  Sentinel A asks B and C: "is master down?"
  B and C respond: "yes, non-responsive"
  Sentinel A: quorum=2 reached → master is ODOWN (objectively down)

Phase 2: Leader Election (Raft-like)
  Sentinel A sends: "I want to be leader for epoch 42"
  Sentinel B: "I vote for A in epoch 42" (first-come-first-served)
  Sentinel C: "I vote for A in epoch 42"
  Sentinel A: 3 votes ≥ majority (3/3) → I AM THE LEADER

Phase 3: Failover
  Leader (A) chooses best replica:
    Criteria (in order):
    1. priority (replica-priority 0 = never promote)
    2. replication offset (most up-to-date wins)
    3. run ID (lexicographically smallest, tiebreaker)
  
  Leader A sends: SLAVEOF NO ONE to chosen replica
  A waits: REPLCONF ACK from new master (old replicas now follow)
  A broadcasts: +switch-master <old-master> <new-master>
  B and C: acknowledge the new master

Timing:
  Detection: 5s (down-after-milliseconds)
  Election: <500ms (network round trips)
  Promotion: <1s (SLAVEOF NO ONE + config rewrite)
  Total: <6.5s typical → your 5s target is TIGHT
```

**Configuration for Sub-5s Failover:**

```bash
# /etc/redis-sentinel.conf
sentinel monitor payment-master 192.168.1.10 6379 2
sentinel down-after-milliseconds payment-master 1000   # 1s detection (was 5s)
sentinel failover-timeout payment-master 5000          # 5s max failover
sentinel parallel-syncs payment-master 1               # Sync one replica at a time
sentinel auth-pass payment-master MySecretPass         # For AUTH-enabled instances
sentinel notification-script payment-master /opt/notify.py  # Alert on failover

# Limitation with aggressive timing:
# 1s down-after-milliseconds → false positives on network jitter
# Use only if network is VERY reliable (same rack/AZ)
# Recommended: 3-5s in multi-AZ deployments
```

**Zero Data Loss Configuration:**

```yaml
# Master config: synchronous replication cannot be enforced in Redis
# Redis replication is ASYNCHRONOUS!
# Data loss window: last writes that master accepted before dying
# Solution: MINIMAL
  - WAIT command in application:
    WAIT 1 1000    # Wait for min 1 replica to acknowledge (timeout 1s)
    # WAIT returns: num_replicas_acked
  
  - Trade-off: WAIT blocks the client, increases p99 latency
  
# Alternative: write to multiple primaries (active-active)
  - Redis Enterprise or CRDT-based (conflict resolution required)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ODOWN protocol** | Explains SDOWN vs ODOWN quorum mechanism |
| **Leader election** | Understands Raft-like epoch-based voting among sentinels |
| **Replica selection** | Knows priority > replication offset > run ID hierarchy |
| **Data loss awareness** | Acknowledges async replication means potential data loss |

---

## 5. Redis Cluster: Hash Slots & Resharding

**Q:** "You need to add 3 nodes to a 6-node Redis Cluster handling 1M ops/s. Walk through hash slot assignment, MOVED/ASK redirections, and resharding without downtime. How do you handle resharding while maintaining p99 < 5ms?"

**What They're Really Testing:** Whether you understand Redis Cluster's distributed hash slot scheme — the difference between MOVED (permanent) and ASK (temporary) redirects, and the resharding protocol.

### Answer

**Hash Slot Scheme:**

```
Total slots: 16384 (2^14)

Slot assignment: CRC16(key) mod 16384

Topic → Slot mapping:
  user:{100}:profile → CRC16("user:{100}:profile") mod 16384 = slot 7842
  session:{abc}:data → CRC16("session:{abc}:data") mod 16384 = slot 12001
  
  Hash tags: use {...} to pin keys to the same slot
  user:{100}:profile, user:{100}:cart → SAME slot (transactional!)
  # Redis cluster doesn't support multi-key operations across slots!
```

**MOVED vs ASK Redirects:**

```
MOVED (permanent):
  Client sends command to Node A
  Key's slot lives on Node B → MOVED <slot> <B-ip>:<port>
  Client caches: "slot 7842 is on Node B" → FUTURE requests go directly to B
  Only replied by the CORRECT node for the slot

ASK (temporary, during resharding):
  Node A has slot but is migrating data to Node B
  Client: GET key → ASK <slot> <B-ip>:<port>
  Client sends ASKING command to B (one-time flag) → then GET key
  Client does NOT update slot cache (next request still goes to A first)
  ASKING flag: allows one read/write to a migrating slot
```

**Resharding Process:**

```bash
# /usr/bin/redis-cli --cluster reshard <source>:<port> --cluster-from <node-id> \
#   --cluster-to <node-id> --cluster-slots <count> --cluster-yes

# Step 1: Add new nodes to cluster
redis-cli --cluster add-node new-node:6379 existing-node:6379
# New nodes are empty → no slots assigned

# Step 2: Reshard slots from existing nodes to new nodes
redis-cli --cluster reshard 192.168.1.10:6379

# Interactive prompts:
How many slots do you want to move? 2730
What is the receiving node ID? <new-node-id>
Source node: all
Do you want to proceed? yes

# Step 3: Check cluster health
redis-cli --cluster check 192.168.1.10:6379

redis-cli cluster info
# cluster_state:ok         # Must be ok
# cluster_slots_assigned:16384
# cluster_known_nodes:9    # 6 old + 3 new
```

**Resharding Internals (Slot Migration):**

```
Phase 1: Set slot MIGRATING on source (IMPORTING on destination)
  CLUSTER SETSLOT 7842 MIGRATING <source-node-id>
  CLUSTER SETSLOT 7842 IMPORTING <dest-node-id>

Phase 2: Migrate keys (batch)
  For each key in slot 7842 (discovered via CLUSTER GETKEYSINSLOT 7842 count):
    MIGRATE dest-ip dest-port key dest-db timeout [COPY] [REPLACE]
    # MIGRATE: atomically transfers key, removes from source
  
Phase 3: Set slot NODE (broadcast)
  CLUSTER SETSLOT 7842 NODE <dest-node-id>
  # Broadcast via gossip to ALL nodes
  # After this: ALL nodes know the new slot owner
  # MOVED redirects from old owner now go to new owner
```

**P99 < 5ms During Resharding:**

```yaml
Challenges:
  - MIGRATE commands are blocking (single-threaded Redis!)
  - Each MIGRATE blocks the event loop for ~100-500μs
  - 10K keys × 100μs = 1 second of event loop blocked!

Solutions:
  
  1. Batch migrations:
    redis-cli --cluster reshard uses batch MIGRATE (multiple keys per call)
    trade-off: larger batches = longer single pause
    
  2. Throttle migration rate:
    redis-cli --cluster reshard --cluster-pipeline 10
    # Pipeline 10 MIGRATE commands at a time → 10 × 500μs = 5ms pause
    # With pipeline: ~50ms pause every 10 keys → acceptable for p99 < 5ms
    # (p99 unaffected because pause is ~50ms once per batch)
    
  3. Reshard during low traffic:
    Schedule reshard during off-peak hours
    
  4. Pin clients:
    # Cluster down? Actually, cluster is DOWN if any slot is unreachable
    # BUT: cluster-require-full-coverage no (accept partial coverage)
    cluster-require-full-coverage no
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **MOVED vs ASK** | Understands MOVED is permanent cache update, ASK is temporary with ASKING flag |
| **CRC16 hash tags** | Knows { } for multi-key ops within same slot |
| **MIGRATE blocking** | Understands single-threaded Redis blocks during key migration |
| **Reshard throttling** | Can pipeline migrations to bound event loop pauses |

---

## 6. Expiry & Eviction Policies

**Q:** "Your Redis cache reaches its maxmemory limit. Walk through the eviction policies. How does the approximated LRU work? How do you choose between allkeys-lru and volatile-ttl for a social media feed cache?"

**What They're Really Testing:** Whether you understand Redis's eviction mechanics — not true LRU, but approximated sampling-based eviction, and how expiry interacts with eviction.

### Answer

**Eviction Policies Comparison:**

```yaml
Policy              | Scope        | When Used
--------------------|--------------|-----------------------------------------------
noeviction          | All keys     | Redis as DB (don't evict, return OOM errors)
allkeys-lru         | All keys     | Generic cache (most popular)
allkeys-lfu         | All keys     | Cache with access frequency patterns
allkeys-random      | All keys     | Equal-value cache items
volatile-lru        | TTL keys     | Cache + persistent keys in same instance
volatile-lfu        | TTL keys     | As above, but frequency-based
volatile-ttl        | TTL keys     | Evict shortest TTL first
volatile-random     | TTL keys     | Random eviction from TTL keys

# Formula: allkeys-lru usually best for caches
# volatile-ttl only if you have good expiry estimates
# volatile-lru if mixing cache + DB in same instance (avoid!)
```

**Approximated LRU (Not True LRU):**

```
True LRU: maintains sorted linked list of all keys by access time
  Memory: O(N) pointers (Redis has 1M+ keys!)
  Insertion/Update: O(1) (move to head)
  Eviction: O(1) (remove from tail)
  Problem: 1M keys × 2 pointers = 16MB just for the LRU list

Redis's approach (approximated LRU):
  - Maintains last access time (24-bit field in robj)
  - On eviction: sample N keys (default 5) from the keyspace
  - Evict the OLDEST among the sample
  - Sampling every time = O(1) per eviction (no sorted structure!)

  maxmemory-samples 10
  # Larger sample = more accurate LRU = more CPU per eviction
  
  Accuracy with maxmemory-samples=5: ~90% of what true LRU would choose
  With maxmemory-samples=10: ~95% accuracy
  With maxmemory-samples=20: ~98% accuracy (rarely needed)
```

**Expiry Internals:**

```
SET key value EX 3600  # Set with TTL

internal: setExpire(key, currentTime + 3600000)

Expiry removal strategies:
  1. Lazy: key accessed → check if expired → delete if expired
     Guarantees: no expired key is ever returned to client
  
  2. Active (timed loop):
     While: expired keys sample rate < 25% AND < 16 samples:
       Sample: 20 random keys from the TTL pool
       Delete: all expired
       If >25% were expired → repeat (thundering herd possible)
       Time limit: <25% of CPU per cycle
       Runs: 10 times per second (hz=10)
     
     Why this matters:
       - Without active expiry, expired keys linger until accessed
       - With active expiry: bounded deletion overhead
       - Problem: 50%+ keys expired → active loop runs all the time!

For social media feed cache:
  allkeys-lru over volatile-ttl:
    - volatile-ttl depends on you setting GOOD TTLs
    - allkeys-lru naturally keeps popular items regardless of TTL
    - Social feed: some items go viral, some die → LRU adapts automatically
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Sampled LRU vs true LRU** | Can explain sampling trade-off: memory vs accuracy |
| **Active expiry loop** | Understands the sampling loop and CPU guarantees |
| **allkeys-lru over volatile-ttl** | For caches, LRU adapts to access patterns, TTL is guesswork |

---

## 7. Lua Scripting & MULTI/EXEC

**Q:** "You need to atomically debit a wallet balance and log the transaction. Compare MULTI/EXEC transactions vs Lua scripting in Redis. How do you ensure that your Lua script doesn't block the event loop for too long?"

**What They're Really Testing:** Whether you understand Redis's scripting model — Lua sandbox, EVAL vs EVALSHA, script replication, and the single-threaded performance implications.

### Answer

**MULTI/EXEC (Optimistic, No Rollback):**

```bash
# MULTI/EXEC: commands are queued and executed atomically
# BUT: no conditional logic! Cannot check-then-set.

MULTI
DECRBY wallet:100 50     # Debit $50
INCR transaction:count   # Log transaction
EXEC                     # EXEC may fail mid-way (no rollback!)

# Problem: cannot check balance before debit!
# Redis transactions DON'T ROLLBACK on errors!
# If DECRBY succeeds but INCR fails → money is lost!
```

**Lua Scripting (Preferred for Conditional Logic):**

```lua
-- Atomic debit + audit with Lua
-- EVAL "script" 2 wallet:100 ledger:today 50

local wallet_key = KEYS[1]        -- "wallet:100"
local ledger_key = KEYS[2]        -- "ledger:today"
local amount = tonumber(ARGV[1])  -- 50

local balance = redis.call("GET", wallet_key)
balance = tonumber(balance or 0)

if balance < amount then
    return redis.error_reply("INSUFFICIENT_FUNDS")
end

redis.call("DECRBY", wallet_key, amount)
redis.call("RPUSH", ledger_key, string.format(
    "tx:wallet_debit:%s:%d", wallet_key, amount
))

return { balance - amount, "SUCCESS" }
```

**Script Caching (EVALSHA):**

```bash
# EVAL: send full script every time (wasteful)
EVAL "return redis.call('GET', KEYS[1])" 1 user:100

# EVALSHA: send SHA1 hash, Redis caches script
SCRIPT LOAD "return redis.call('GET', KEYS[1])"
# → returns: "4e6d1b3fc8d5c12b9c4c5d6e7f8a9b0c1d2e3f4a"

EVALSHA 4e6d1b3fc8d5c12b9c4c5d6e7f8a9b0c1d2e3f4a 1 user:100

# If script not cached: NOSCRIPT error → fall back to EVAL
```

**Event Loop Blocking (Script Duration):**

```lua
-- WARNING: Lua scripts ARE BLOCKING!
-- Redis is single-threaded: script runs → nothing else runs!
-- Default max: lua-time-limit 5000 (5 seconds)

-- BAD: O(N) loop over 1M items
for i = 0, 1000000 do
    redis.call("GET", "key:" .. i)  -- Blocks for 10+ seconds!
end

-- GOOD: incremental processing with Lua side effects
-- (Redis doesn't support yielding mid-script)
-- Instead: process in batches outside Redis
```

**Script Replication:**

```bash
# Lua scripts are REPLICATED to replicas AS-TEXT
# Replicas run the SAME Lua script, not just the resulting writes
# This means: script must be DETERMINISTIC!

# DANGEROUS: non-deterministic script
# redis.log() and TIME() return different values on each run!
redis.call("SET", "last_updated", redis.call("TIME")[1])

# SAFE: use Redis commands that are deterministic
redis.call("SET", "last_updated", ARGV[1])

# Script flags (Redis 7+):
# no-writes: script only reads (can run on replicas)
# allow-oom: script can run even when OOM
# allow-cross-slot-keys: bypass slot restriction
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Script vs MULTI** | Knows Lua enables conditionals, MULTI doesn't |
| **Blocking concern** | Understands scripts BLOCK the event loop — must be fast |
| **Determinism** | Knows scripts are replicated as-is, must be deterministic |
| **EVALSHA** | Cached scripts save bandwidth |

---

## 8. Streams & Consumer Groups

**Q:** "Design a real-time event processing pipeline using Redis Streams for 100K events/second. Compare consumer groups with Kafka consumer groups. How do you handle back-pressure and dead-letter processing?"

**What They're Really Testing:** Whether you understand Redis Streams' data model — radix tree storage, consumer group protocol, and the pending entries list (PEL).

### Answer

**Stream Data Structure:**

```
Stream: order-events  (radix tree compressed)

Entry format:
  1728492012345-0 → { "order_id": "ORD-123", "action": "created", "amount": 99.99 }
  1728492012346-0 → { "order_id": "ORD-456", "action": "updated", "amount": 199.99 }

ID format: <millisecondsTime>-<sequenceNumber>
  Time-based: 1728492012345 = Unix timestamp in milliseconds
  Sequence: 0-65535 per millisecond (auto-increment)

Radix tree storage:
  - Common prefixes share storage (saves memory)
  - Example: all "1728492012..." entries share the first 10 characters
  - 100M entries with 50-byte payloads → ~5GB (vs ~15GB uncompressed)
```

**Consumer Group Protocol:**

```
Consumer group: "order-processors"

Pending Entries List (PEL):
  ┌──────┬────────────┬─────────────┬───────────┐
  │ ID   │ Consumer   │ Delivered   │ Retry     │
  ├──────┼────────────┼─────────────┼───────────┤
  │ 1-0  │ processor1 │ 12:34:56    │ 2 times   │
  │ 2-0  │ processor2 │ 12:35:00    │ 0 times   │
  │ 3-0  │ processor1 │ 12:35:02    │ 1 time    │
  └──────┴────────────┴─────────────┴───────────┘

  XREADGROUP GROUP order-processors processor1 COUNT 10 BLOCK 2000 STREAMS order-events >
  # ^ Carat: read new entries (never-before-delivered)
  # ">": returns only entries not yet delivered to any consumer

  XACK order-events order-processors 1728492012345-0
  # Acknowledge: remove from PEL

  XREADGROUP GROUP order-processors processor1 COUNT 10 STREAMS order-events 0
  # "0": read PEL entries (pending, unacknowledged)

  XPENDING order-events order-processors
  # Summary of pending entries

  XCLAIM order-events order-processors processor2 60000 1728492012345-0
  # Claim: transfer pending entry to another consumer (after 60s idle)
```

**100K Events/Second Pipeline:**

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379)

STREAM = "order-events"
GROUP = "order-processors"

# Create stream group (idempotent)
try:
    r.xgroup_create(STREAM, GROUP, id='0', mkstream=True)
except redis.ResponseError:
    pass

# Producer: batch for throughput
def produce_events(events):
    """Batch produce for 100K events/sec"""
    pipeline = r.pipeline(transaction=False)
    for event in events:
        pipeline.xadd(STREAM, event, maxlen=1000000, approximate=True)
    pipeline.execute()
    # ~50K writes/sec per pipeline
    # Use multiple connections for 100K/s

# Consumer: with dead-letter handling
def consume_events(consumer_name, max_retries=3):
    while True:
        try:
            # Read new entries
            results = r.xreadgroup(
                GROUP, consumer_name,
                {STREAM: '>'},
                count=100, block=2000
            )

            if not results:
                continue

            for stream_name, entries in results:
                for msg_id, data in entries:
                    try:
                        process_event(data)
                        r.xack(STREAM, GROUP, msg_id)
                    except Exception as e:
                        # Check retry count
                        pending = r.xpending_range(
                            STREAM, GROUP,
                            min=msg_id, max=msg_id,
                            count=1
                        )
                        if pending and pending[0]['times_redisplyed'] >= max_retries:
                            # Move to dead-letter stream
                            r.xadd(f"{STREAM}:dead", {
                                'original_id': msg_id,
                                'error': str(e),
                                'data': str(data)
                            })
                            r.xack(STREAM, GROUP, msg_id)
                        else:
                            # Will be retried automatically via PEL
                            print(f"Retry later: {msg_id}")

            # Also check for pending entries (automatically retried)
            pending = r.xpending_range(
                STREAM, GROUP,
                min='-', max='+',
                count=100
            )
            for entry in pending:
                if time.time() - entry['time_since_delivered'] > 60000:
                    r.xclaim(STREAM, GROUP, consumer_name, 60000, entry['id'])

        except redis.ConnectionError:
            time.sleep(1)
```

**Back-Pressure and Capacity:**

```yaml
Stream maxlen: 
  XADD my_stream MAXLEN ~ 1000000 * ...
  # Tilde: approximate trimming (saves CPU)
  # 1M entries × 200 bytes = ~200MB per stream

Consumer lag detection:
  XLEN stream - min(XINFO CONSUMERS stream group name:entries)
  
  Alert if lag > 100K → consumer can't keep up

Comparison with Kafka:
  Redis Streams:
    - All in memory (limited by RAM)
    - No partitioning (single stream is a single shard)
    - PEL-based retry (no offset management)
    - Ideal for: 10-100K events/s, bounded memory, fast recovery
  
  Kafka:
    - Disk-backed (unlimited)
    - Partitioned for parallelism
    - Offset-based consumption
    - Ideal for: 100K+ events/s, long retention, large fan-out
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Radix tree storage** | Understands stream compression via shared prefix |
| **PEL mechanics** | Knows PEL tracks pending entries, XACK removes them |
| **Dead-letter pattern** | Implements retry exhaustion → move to dead-letter stream |
| **Stream vs Kafka** | Can articulate when to use each (in-memory vs disk, single-shard vs partitioned) |

---

## 9. Memory Optimization & Fragmentation

**Q:** "Your Redis instance shows used_memory: 8GB but used_memory_rss: 14GB. That's 75% fragmentation. Diagnose the causes and fix them without restarting the instance. How would you prevent this in the future?"

**What They're Really Testing:** Whether you understand Redis's memory allocator (jemalloc) behavior and fragmentation patterns — and the difference between internal, external, and slab fragmentation.

### Answer

**Fragmentation Diagnosis:**

```
MEMORY INFO (Redis 4+):
  used_memory: 8,000,000,000     (8GB - what Redis asked for)
  used_memory_rss: 14,000,000,000 (14GB - actual RSS from OS)

  mem_fragmentation_ratio: 1.75   (bad! > 1.5 needs attention)
  
  used_memory_peak: 12,000,000,000 (earlier peak was 12GB!)
  !!! This is the most likely cause!

  mem_allocator: jemalloc-5.2.1

Three types of fragmentation:
  1. External fragmentation: jemalloc can't fit a new allocation into existing free space
  2. Internal fragmentation: allocation is larger than requested (size class rounding)
  3. Slab fragmentation: jemalloc's slab allocator leaves gaps
```

**Root Causes:**

```yaml
1. Peak memory usage (MOST COMMON):
   - Earlier peak: 12GB → keys expired/set to lower TTLs
   - jemalloc pages that held 12GB of data are now partly free
   - But OS won't reclaim them (jemalloc holds onto them)
   - Solution: memory defrag or restart

2. Uneven key-size distribution:
   - Mix of 10B and 10KB keys
   - jemalloc's size classes: 8, 16, 32, 48, 64, 80, 96, 112, 128, ...
   - Small keys fill small classes, large keys fill large classes
   - When small keys expire: small-size-class pages freed (holes in large pages)

3. Jemalloc page size:
   - Default page size: 4KB
   - Each 4KB page serves ONE size class
   - If 4000 bytes used out of 4096: 96 bytes wasted (2.3% internal fragmentation)
   - Over 1M pages: 96MB wasted
```

**Fix Without Restarting:**

```bash
# 1. Activate defragmentation (Redis 4+)
CONFIG SET activedefrag yes
CONFIG SET active-defrag-threshold-lower 10
CONFIG SET active-defrag-threshold-upper 100
CONFIG SET active-defrag-cycle-min 25
CONFIG SET active-defrag-cycle-max 75
CONFIG SET active-defrag-ignore-bytes 100mb

# What this does:
# Jemalloc's madvise(MADV_DONTNEED) on pages with low utilization
# Returns free pages to OS
# May take 10-30 minutes for 75% fragmentation
# Risk: slight latency increase during defrag (25-75% of one CPU core)

# 2. Check fragmentation reduction:
redis-cli INFO memory | grep mem_fragmentation_ratio
# Should decrease over minutes

# 3. If defrag doesn't work (jemalloc fragmentation too deep):
#   → schedule restart during low traffic
#   → Redis reloads dataset fresh → zero fragmentation
```

**Preventative Measures:**

```yaml
1. Use consistent key sizes:
   - Pad small values to common sizes
   - Or combine related data into hashes (one key, multiple fields)
   
2. Monitor fragmentation trends:
   - mem_fragmentation_ratio > 1.5 → investigate
   - mem_fragmentation_ratio > 2.0 → urgent defrag needed
   
3. Restart periodically:
   - Schedule monthly restarts during maintenance windows
   - Use failover (replica promotion) for zero downtime
   
4. Jemalloc tuning (Linux):
   # /etc/redis/redis.conf
   # Jemalloc background thread for purging
   # Enable: jemalloc background thread
   export MALLOC_CONF="background_thread:true,dirty_decay_ms:5000,muzzy_decay_ms:5000"
   
5. Maxmemory with eviction:
   - Set maxmemory to 75% of physical RAM (leaves room for fragmentation)
   - If dataset = 8GB, set maxmemory 12GB → 4GB fragmentation headroom
   
   maxmemory 12gb
   maxmemory-policy allkeys-lru
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Peak memory causation** | Knows fragmentation is usually from PEAK memory, not current |
| **Active defrag** | Can enable and tune active-defrag parameters |
| **Jemalloc behavior** | Understands size classes and page allocation |
| **Prevention** | Suggests maxmemory headroom, consistent key sizes, periodic restarts |

---

## 10. Distributed Locks & Redlock

**Q:** "Design a distributed lock for a shared resource that must have mutual exclusion even if the lock holder crashes. Is Redis's SET NX EX sufficient? What about Redlock? Can you prove correctness of your lock under network partitions?"

**What They're Really Testing:** Whether you understand the distributed locking problem — the failure modes of single-instance locks, Martin Kleppmann's critique of Redlock, and the fencing token solution.

### Answer

**Simple Lock (Single Redis Instance):**

```bash
# Lock: acquire
SET lock:resource_id <my_token> NX EX 30
# Returns OK → lock acquired
# Returns (nil) → someone else has the lock

# Unlock: must verify ownership (use Lua)
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end

# Problem 1: Single point of failure
#   Master has lock → master crashes → replica has NO lock data (async replication!)
#   Another client acquires the same lock → mutual exclusion broken!

# Problem 2: Clock drift
#   Lock holder's clock is 5 seconds behind
#   Thinks lock expires in 25s, but actually expired in 20s
#   Another client acquires lock while first client still holds it

# Problem 3: GC pause
#   Client acquires lock
#   GC pause: 40 seconds (longer than 30s TTL)
#   Lock expires, another client acquires it
#   First client resumes, thinks it still has the lock → double access!
```

**Redlock Algorithm (5 Independent Redis Nodes):**

```python
import time
import redis

class Redlock:
    def __init__(self, redis_nodes):
        # 5 independent Redis nodes (no replication!)
        self.nodes = [redis.Redis(host=n) for n in redis_nodes]
        self.quorum = len(self.nodes) // 2 + 1  # 3/5 majority

    def acquire(self, resource, ttl_ms=30000):
        token = str(uuid.uuid4())
        start_time = time.monotonic() * 1000

        # Phase 1: Try to lock on ALL nodes
        locked = 0
        for node in self.nodes:
            try:
                if node.set(f"lock:{resource}", token,
                            nx=True, px=ttl_ms, timeout=500):
                    locked += 1
            except (redis.TimeoutError, redis.ConnectionError):
                continue

        # Phase 2: Check if majority acquired
        elapsed = time.monotonic() * 1000 - start_time
        if locked >= self.quorum and elapsed < ttl_ms:
            # Valid lock!
            # TTL remaining = original_ttl - elapsed_time
            return token
        else:
            # Lock failed → release on ALL nodes
            self.release(resource, token)
            return None

    def release(self, resource, token):
        # Release on ALL nodes (not just majority)
        for node in self.nodes:
            try:
                # Lua script for safe release
                node.eval("""
                    if redis.call("GET", KEYS[1]) == ARGV[1] then
                        return redis.call("DEL", KEYS[1])
                    else
                        return 0
                    end
                """, 1, f"lock:{resource}", token)
            except:
                pass
```

**Critique of Redlock (Martin Kleppmann, 2016):**

```
Martin Kleppmann's argument:
  Redlock makes assumptions about:
  1. Synchronous network → "bounded delays"
  2. Synchronous clocks → "bounded clock drift"
  3. Nobody pauses → "no GC pauses"

  Problems:
  - GC pause > TTL: clock is irrelevant, the problem is PAUSES
  - Network delays: can't bound in asynchronous network
  - Clock drift: NTP can make large adjustments

  Solution: FENCING TOKENS
  - Lock service returns a monotonically increasing token
  - Token = fencing token (like ZooKeeper's zxid)
  - Resource checks: "has this token been exceeded?"
  - Even if lock is compromised, resource rejects stale tokens
```

**Fencing Token Implementation:**

```python
# Alternative to Redlock: use ZooKeeper or etcd for fencing tokens

# ZooKeeper: sequential znode → unique monotonically increasing id
#   /locks/myresource/lock-0000000001
#   /locks/myresource/lock-0000000002

# etcd: revision number → fencing token
#   key: /locks/myresource
#   create_revision: 42 (fencing token!)

# Client acquires lock, gets fencing token = 42
# Client sends request to storage with token
# Storage checks: "last processed token was 41"
#   token 42 > 41 → accept (legitimate)
#   token 41 < 42 → reject (stale/zombie)

# Redis CANNOT provide monotonically increasing fencing tokens!
# (Redis Cluster doesn't support linearizable operations by default)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **SET NX EX limitations** | Knows single-node lock fails under master failure |
| **Redlock critique** | Understands Kleppmann's arguments about GC pauses and async networks |
| **Fencing tokens** | Proposes fencing tokens as the REAL solution to distributed locking |
| **Practical advice** | Recommends ZooKeeper/etcd for true distributed locks with fencing |

---

## 11. Cache Strategies: Thundering Herd

**Q:** "A popular API endpoint's cache key expires. 10,000 requests hit your Redis cache simultaneously, all miss, and all hit the database. The database falls over. Design a cache strategy to prevent this. Compare cache-aside, read-through, and refresh-ahead."

**What They're Really Testing:** Whether you understand production caching patterns — thundering herd prevention, staleness vs availability trade-offs, and probabilistic early expiration.

### Answer

**Thundering Herd Analysis:**

```
Timeline:
  t=0: Cache key expires
  t=0.001: Request 1: cache miss → DB query (takes 100ms)
  t=0.002: Request 2: cache miss → DB query (takes 100ms)
  t=0.003: Request 3: cache miss → DB query (takes 100ms)
  ...
  t=0.010: Request 10,000: cache miss → DB query (takes 100ms)
  
  Result: 10,000 simultaneous DB queries
  DB connection pool exhausted: 100 connections × 100ms = 10s queue
  DB CPU: 1000% → query timeout
  Result: CASCADING FAILURE (cache miss → DB overload → all requests fail)
```

**Solution 1: Mutex Lock (Cache-Aside + Lock)**

```python
import redis
import threading

def get_cached_or_compute(key, compute_func, ttl=300):
    """Cache-aside with mutex lock for thundering herd prevention"""

    value = redis_cache.get(key)
    if value is not None:
        return value

    # Mutex lock: only one process computes
    lock_key = f"lock:{key}"
    lock_token = str(uuid.uuid4())

    # Try to acquire lock with 5s TTL (should be > computation time)
    if redis_cache.set(lock_key, lock_token, nx=True, ex=5):
        try:
            # Double-check: another process might have set it while we waited
            value = redis_cache.get(key)
            if value is not None:
                return value

            # Compute the value (DB query, expensive computation)
            value = compute_func()
            redis_cache.setex(key, ttl, value)
            return value
        finally:
            # Release lock
            redis_cache.delete(lock_key)
    else:
        # Lock not acquired: wait for the computing process
        timeout = 5  # Should match lock TTL
        poll_interval = 0.005  # 5ms polling

        while timeout > 0:
            value = redis_cache.get(key)
            if value is not None:
                return value
            time.sleep(poll_interval)
            timeout -= poll_interval

        # Timeout: lock holder crashed
        # Force compute (or raise error)
        return get_cached_or_compute(key, compute_func, ttl)
```

**Solution 2: Probabilistic Early Expiration (Refresh-Ahead)**

```python
# Instead of waiting until TTL expires, proactively refresh BEFORE
# Probabilistic: early-expire based on a random factor

def get_with_early_recompute(key, compute_func, ttl=300, beta=1.0):
    """
    XFetch algorithm (by Voldemort):
    - p(early refresh) proportional to how close we are to expiry
    - Randomness prevents all processes refreshing simultaneously
    """
    value, expiry_str = redis_cache.hmget(key, ['value', 'expiry'])
    if value is None:
        # Cache miss: compute and set
        value = compute_func()
        redis_cache.hmset(key, {'value': value, 'expiry': time.time() + ttl})
        return value

    expiry = float(expiry_str)
    now = time.time()
    ttl_remaining = expiry - now

    if ttl_remaining <= 0:
        # Expired: compute synchronously
        value = compute_func()
        redis_cache.hmset(key, {'value': value, 'expiry': time.time() + ttl})
        return value

    # Probabilistic early recompute: higher probability closer to expiry
    # Formula: p = exp(beta * ttl_remaining / ttl) when ttl_remaining < threshold
    threshold = ttl * 0.5  # Start early recompute at 50% of TTL

    if ttl_remaining < threshold:
        # Probability of early refresh increases as we approach expiry
        # At 10% TTL remaining: 90% probability of early refresh
        # At 1% TTL remaining: 99% probability
        if random.random() < (1 - ttl_remaining / threshold):
            # Early refresh in background
            threading.Thread(target=lambda: redis_cache.hmset(
                key,
                {'value': compute_func(), 'expiry': time.time() + ttl}
            )).start()

    return value  # Return STALE value while refresh happens!
```

**Solution 3: Write-Through + Invalidation Queue**

```python
# For high-write, high-read systems:
# 1. Always write to cache first (write-through)
# 2. DB write happens asynchronously
# 3. Cache always has latest value

class WriteThroughCache:
    def __init__(self, redis_client, db_client, queue):
        self.cache = redis_client
        self.db = db_client
        self.queue = queue

    def get(self, key):
        value = self.cache.get(key)
        if value is not None:
            return value

        # Cache miss → rare with write-through
        # Recompute from DB (only happens on initial load or eviction)
        value = self.db.query(key)
        self.cache.setex(key, 300, value)
        return value

    def set(self, key, value):
        # Write to cache FIRST (immediate consistency)
        self.cache.setex(key, 300, value)

        # Queue DB write (async, eventual consistency)
        self.queue.publish({'action': 'write', 'key': key, 'value': value})

    def invalidate(self, key):
        # Don't delete! Write the new value directly
        # Deletion causes thundering herd!
        # Instead: compute new value and write to cache
        new_value = self.db.query(key)
        self.cache.setex(key, 300, new_value)
```

**Strategy Comparison:**

```yaml
Strategy           | Thundering Herd | Staleness | Complexity | Use When
-------------------|-----------------|-----------|------------|-----------------------
Cache-Aside        | ❌ Vulnerable   | Low       | Low        | Low traffic
Cache-Aside + Lock | ✅ Protected    | Low       | Medium     | Moderate traffic
Read-Through       | ✅ Protected    | Low-Med   | Medium     | Standard pattern
Write-Through      | ✅ Protected    | Zero (write) | High    | High write concurrency
Refresh-Ahead      | ✅ Protected    | Medium    | High       | Predictable access patterns
Probabilistic      | ✅ Best         | Low-Med   | Medium     | Read-heavy, hot keys
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Mutex pattern** | Knows SET NX to serialize computation |
| **Probabilistic refresh** | Understands XFetch formula and why randomness is critical |
| **Write-through** | Knows write-through prevents invalidation storms |
| **Staleness trade-off** | Accepts controlled staleness for protection against cascading failures |

---

## 12. Redis 7+ Features: ACLs, Functions

**Q:** "Your Redis instance serves 5 microservices. Each should only access its own keys. How does Redis 7's ACL system work? What about Redis Functions vs Lua scripts? Design an ACL policy for a multi-tenant API gateway backed by Redis."

**What They're Really Testing:** Whether you understand Redis 7's modern features — ACL-based access control, and Redis Functions as a managed alternative to Lua scripting.

### Answer

**Redis ACL System (Redis 6+, Enhanced in 7):**

```bash
# Redis 7 ACL = authentication + authorization
# Users, passwords, commands permissions, key permissions

# Create users for each microservice:
ACL SET USER payment-service on >payment-p@ssword123 ~payment:* +@all -@dangerous
#  │                      │    │                     │         │       │
#  │                      │    │                     │         │       └── Deny dangerous commands
#  │                      │    │                     │         └────────── Allow all other command categories
#  │                      │    │                     └──────────────────── Key pattern: payment:*
#  │                      │    └────────────────────────────────────────── Password
#  │                      └─────────────────────────────────────────────── Enable user (on)
#  └────────────────────────────────────────────────────────────────────── Username

ACL SET USER ordering-service on >ordering-p@ss ~order:* +@all -FLUSHALL -CONFIG -SHUTDOWN

ACL SET USER monitoring-service on >monitor-p@ss ~* +@read +@connection +INFO
# Monitoring only: READ + INFO, no writes

ACL SET USER admin on >admin-super-s3cret ~* +@all

# Verify:
ACL LIST
# 1) "user payment-service on #3a2b... ~payment:* +@all -@dangerous"
# 2) "user admin on #d4e5... ~* +@all"
```

**Command Categories for ACL:**

```yaml
# Categories (much easier than listing individual commands):
  +@all            # Allow everything
  -@dangerous      # Block: FLUSHALL, FLUSHDB, CONFIG, SHUTDOWN, DEBUG, SCRIPT KILL
  +@read           # GET, MGET, HGET, SMEMBERS, etc.
  +@write          # SET, SETEX, HSET, SADD, etc.
  +@admin          # CONFIG GET/SET, SHUTDOWN, SLAVEOF
  +@fast           # O(1) commands
  +@slow           # O(N) or slower commands
  +@string         # String commands only
  +@list           # List commands only
  +@set            # Set commands only
  +@sortedset      # Sorted set commands only
  +@hash           # Hash commands only
  +@stream         # Stream commands only
  +@connection     # PING, AUTH, SELECT, etc.
  +@keyspace       # DEL, EXISTS, EXPIRE, KEYS, SCAN, etc.
  +@transaction    # MULTI, EXEC, DISCARD
  +@scripting      # EVAL, EVALSHA, SCRIPT LOAD
  +@pubsub         # PUBLISH, SUBSCRIBE, PSUBSCRIBE
```

**Redis Functions (Redis 7, Replaces Lua Scripting):**

```lua
-- Lua scripts: loaded per-application, managed by applications
-- Problem: scripts scattered across codebases, no central management

-- Redis Functions: server-side library of functions
-- Loaded ONCE into Redis, invoked by name
-- Managed via FUNCTION commands

-- #1. Define function library
-- redis-cli FUNCTION LOAD "#!lua name=mylib\n

#!lua name=payment_functions version=1

-- Register functions
redis.register_function{
    function_name = 'debit_wallet',
    callback = function(keys, args)
        local wallet_key = keys[1]
        local amount = tonumber(args[1])
        local balance = redis.call('GET', wallet_key)
        balance = tonumber(balance or 0)

        if balance < amount then
            return redis.error_reply('INSUFFICIENT_FUNDS')
        end

        redis.call('DECRBY', wallet_key, amount)
        redis.call('RPUSH', 'audit_log', 'debit:' .. wallet_key .. ':' .. amount)
        return balance - amount
    end,
    flags = {'no-writes'}  -- Can run on replicas
}

-- #2. Invoke function (from any client)
FCALL debit_wallet 1 wallet:100 50
-- Returns: 50 (new balance)

-- Advantage over EVAL:
-- 1. Loaded once (no EVALSHA/NOSCRIPT issues)
-- 2. Atomic updates (version) - can't accidentally run stale script
-- 3. Centralized in Redis (not scattered across clients)
-- 4. ACL-controlled (can allow FCALL but deny EVAL)
```

**Multi-Tenant API Gateway ACL Design:**

```yaml
# Scenario: Redis-backed API gateway serving 5 teams
# Each team has their own key prefix
# Admin team has full access

# ── Users ──
ACL SET USER team-payments on >p@ssw0rd_pay ~payments:* +@all -@dangerous
ACL SET USER team-orders on >p@ssw0rd_ord ~orders:* +@all -@dangerous
ACL SET USER team-users on >p@ssw0rd_usr ~users:* +@all -@dangerous  
ACL SET USER team-analytics on >p@ssw0rd_anl ~analytics:* +@read +@keyspace
ACL SET USER team-admin on >s3cr3t_adm ~* +@all

# ── Functions (team-specific) ──
# Team-payments can only call their functions
ACL SET USER team-payments on >p@ssw0rd_pay ~payments:* +@all -@dangerous +fcall|debit_wallet +fcall|credit_wallet

# ── Default deny ──
ACL SETUSER default off -@all

# ── Connection limits (Redis 7) ──
# Prevent one team from consuming all connections
ACL SETUSER team-payments on >p@ssw0rd_pay ~payments:* +@all -@dangerous +fcall|debit_wallet
ACL SETUSER team-payments reset-connections 50
```

**Redis 7 Additional Features:**

```yaml
# 1. ACL LOG (audit trail)
ACL LOG
# Track failed authentication attempts (security monitoring)

# 2. Sharded Pub/Sub
# Previously: PUBLISH only on all nodes
# Now: SSPUBLISH to specific shard
# Scales horizontally (no cross-node broadcast)

# 3. Client-side caching (tracking)
# Server tracks which keys clients are caching
# On key update: server sends INVALIDATION message to clients
# Clients don't need TTL-based polling

# 4. Redis Functions (as above)
# 5. Better replication (repl-diskless-sync improved)
# 6. Command tips for better cluster routing
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ACL granularity** | Knows key patterns, command categories, and user management |
| **Functions vs EVAL** | Understands central management advantage of Functions |
| **Multi-tenant isolation** | Can design ACLs that prevent cross-tenant access |
| **New features** | Knows Redis 7 highlights: ACL LOG, sharded pub/sub, client caching |

---

> *All 12 questions cover the full breadth of Redis internals, data structures, persistence, clustering, and operational excellence — from memory optimization to distributed locking and ACL security.*
