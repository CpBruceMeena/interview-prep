# 🗄️ Database Systems — Staff-Level Interview Questions

> *14 questions covering indexing, transactions, MVCC, replication, sharding, and query optimization — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [B-Tree vs LSM-Tree: Storage Engine Design](#1-b-tree-vs-lsm-tree-storage-engine-design)
2. [MVCC Internals: PostgreSQL vs MySQL (InnoDB)](#2-mvcc-internals-postgresql-vs-mysql-innodb)
3. [Transaction Isolation Levels & Anomalies](#3-transaction-isolation-levels-anomalies)
4. [Query Optimization & Execution Plans](#4-query-optimization-execution-plans)
5. [Indexing Strategies: B-Tree, Hash, GiST, GIN, BRIN](#5-indexing-strategies-b-tree-hash-gist-gin-brin)
6. [Replication: Synchronous vs Asynchronous, Quorum](#6-replication-synchronous-vs-asynchronous-quorum)
7. [Sharding Strategies & Distributed Query](#7-sharding-strategies-distributed-query)
8. [PostgreSQL Buffer Pool & WAL Internals](#8-postgresql-buffer-pool-wal-internals)
9. [Deadlock Detection & Lock Escalation](#9-deadlock-detection-lock-escalation)
10. [Concurrency Control: 2PL vs OCC vs MVCC](#10-concurrency-control-2pl-vs-occ-vs-mvcc)
11. [Materialized Views & Indexed Views](#11-materialized-views-indexed-views)
12. [Database Migrations at Scale](#12-database-migrations-at-scale)
13. [Connection Pooling & PgBouncer Internals](#13-connection-pooling-pgbouncer-internals)
14. [Distributed SQL: CockroachDB vs Spanner](#14-distributed-sql-cockroachdb-vs-spanner)

---

## 1. B-Tree vs LSM-Tree: Storage Engine Design

**Q:** "Design a storage engine for two different workloads: (A) a financial ledger where every write must be immediately durable and queryable for ACID compliance, and (B) a time-series metrics system ingesting 10M points/second. Compare B-Tree and LSM-Tree for each workload."

**What They're Really Testing:** Whether you understand the fundamental read/write/space trade-offs between the two dominant storage engine families.

### Answer

**B-Tree vs LSM-Tree — Core Comparison:**

```
B-Tree (e.g., InnoDB, PostgreSQL heap):
┌─────────────────────────────────────────┐
│ Random write:     ~500µs/page (4KB)    │
│ Sequential write: ~20µs/page            │
│ Read (point):     O(log_B N) ~ 3-4 I/Os │
│ Range scan:       Efficient (next ptr)  │
│ Space:            ~1.1× (low overhead)   │
│ Write amplification: ~10-50×           │
│ Storage:          In-place update       │
└─────────────────────────────────────────┘

LSM-Tree (e.g., LevelDB, RocksDB, Cassandra):
┌─────────────────────────────────────────┐
│ Random write:     ~1µs (append to mem) │
│ Sequential write: ~1µs                   │
│ Read (point):     O(log² N)  (bloom + L0..Ln) │
│ Range scan:       O(log² N + results)    │
│ Space:            ~1.5× (temporary garbage)   │
│ Write amplification: ~10-100×          │
│ Storage:          Append-only + compaction│
└─────────────────────────────────────────┘
```

**B-Tree Structure (InnoDB Page = 16KB):**

```
                  ┌─────────────────────┐
                  │  Root Page (Level 2) │
                  │  ┌─────────────────┐ │
                  │  │ 5 │ 20 │ 45 │ 80│ │
                  │  └────┬────┬────┬──┘ │
                  └───────┼────┼────┼────┘
                          │    │    │
        ┌─────────────────┘    │    └─────────────────┐
        │                      │                      │
   ┌────▼────────┐       ┌────▼────────┐       ┌────▼────────┐
   │Level 1 Pg 1 │       │Level 1 Pg 2 │       │Level 1 Pg 3 │
   │ 1 │ 3 │ 4   │       │ 6 │ 8 │ 12  │       │ 22 │ 30 │ 40│
   └───┬───┬───┬─┘       └───┬───┬───┬─┘       └───┬───┬───┬─┘
       │   │   │             │   │   │             │   │   │
   ┌───┘   │   └───┐   ┌───┘   │   └───┐   ┌───┘   │   └───┐
   ▼       ▼       ▼   ▼       ▼       ▼   ▼       ▼       ▼
┌────┐  ┌────┐  ┌────┐ ┌────┐  ┌────┐  ┌────┐ ┌────┐  ┌────┐  ┌────┐
│Leaf│  │Leaf│  │Leaf│ │Leaf│  │Leaf│  │Leaf│ │Leaf│  │Leaf│  │Leaf│
│ 1  │  │ 3  │  │ 4  │ │ 6  │  │ 8  │  │ 12 │ │ 22 │  │ 30 │  │ 40 │
└────┘┌─┴────┴──┴────┘ └────┘ ┌┴────┴──┴────┘ └────┘ ┌┴────┴──┴────┐
      │← next →│               │← next →│               │← next →│
```

**LSM-Tree Compaction Levels:**

```
MemTable (in-memory, sorted):
┌──────────────────┐
│ k1:v1 │ k3:v3   │  ← Writes go here first (~1µs)
│ k5:v5 │ k8:v8   │  ← Sorted by key (skiplist)
└────────┬─────────┘
         │ flush when full (~64MB)
         ▼
┌─────────────────────────────────────┐
│ L0 (SS Tables, unsorted overlaps)   │
│ ┌─────┐ ┌─────┐ ┌─────┐           │
│ │SST1 │ │SST2 │ │SST3 │           │ ← Overlapping key ranges!
│ └─────┘ └─────┘ └─────┘           │ ← Read must check ALL
└────────────┬────────────────────────┘
             │ compaction (merge)
             ▼
┌─────────────────────────────────────┐
│ L1 (non-overlapping SS Tables)      │  ← Sorted by key
│ ┌─────┐ ┌─────┐ ┌─────┐           │  ← Each SST covers disjoint range
│ │a-m  │ │n-z  │ │a-f  │ ← Wait,   │
│ └─────┘ └─────┘ └─────┘  this breaks non-overlap!
│ → Actually: each level is sorted properly
└────────────┬────────────────────────┘
             │ more compaction
             ▼
┌─────────────────────────────────────┐
│ Ln (max level)                      │
│ ┌──────────────┐ ┌──────────────┐  │
│ │  a-m         │ │  n-z         │  │  ← Final sorted state
│ └──────────────┘ └──────────────┘  │
└─────────────────────────────────────┘
```

**Which Engine for Each Workload?**

```
Workload A: Financial Ledger
- Requirement: Durable, ACID, point queries (SELECT * FROM accounts WHERE id = 5)
- Write pattern: Random (account balance updates)
- Read pattern: Point lookups + small range scans

→ B-Tree wins.
  Reason:
  - 3-4 I/Os per point query vs LSM's need to check Bloom filters + L0..Ln
  - In-place update means no compaction overhead during peak hours
  - Lower write amplification (10-50×) vs LSM (10-100×) on typical configs
  - Transaction isolation more natural (page-level locking)

Workload B: Time-Series Metrics (10M points/s)
- Requirement: Append-only, batch reads (SELECT avg(value) WHERE time > NOW()-1h)
- Write pattern: Sequential by timestamp
- Read pattern: Large range scans

→ LSM-Tree wins.
  Reason:
  - In-memory buffering: 10M writes/s → memtable accepts at memory speed
  - Sequential SST writes to disk: ~500MB/s sustained
  - B-Tree: random page writes would bottleneck at ~50K random IOPs/s
  - Bloom filters efficiently skip non-matching SSTs
```

**Hybrid Approaches:**

```python
# Modern engines hybridize:
# PostgreSQL: B-Tree + BRIN index for time-series
#   BRIN uses min/max per page range → 1000× smaller than B-Tree for time-series

CREATE INDEX idx_time ON metrics USING BRIN (recorded_at)
    WITH (pages_per_range = 32);

# RocksDB: B-Tree-like LSM compaction (leveled compaction)
#   Limits per-level overlap, bounds write amplification to ~10×
options.OptimizeLevelStyleCompaction(memtable_memory_budget=512MB)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **I/O patterns** | Quantifies random vs sequential write costs for each engine |
| **Amplification** | Explains write amplification sources (LSM: compaction, B-Tree: page splits) |
| **Read amplification** | LSM requires bloom filter + L0..Ln checks; B-Tree is O(log N) |
| **Trade-off decision** | Maps workload characteristics to engine choice with reasoning |

---

## 2. MVCC Internals: PostgreSQL vs MySQL (InnoDB)

**Q:** "Walk me through how PostgreSQL implements MVCC. How does it differ from MySQL InnoDB? What happens when you UPDATE a row that's actively being read by another transaction?"

**What They're Really Testing:** Whether you understand MVCC at the storage level — tuple headers, visibility checks, and vacuum mechanics.

### Answer

**PostgreSQL MVCC — Row Format (Heap Tuple):**

```c
// PostgreSQL page format:
typedef struct HeapTupleHeaderData {
    union {
        HeapTupleFields t_heap;     // MVCC metadata
        DatumFields t_datum;        // For tuple routing
    } t_choice;

    ItemPointerData t_ctid;         // Current tuple ID (block, offset)
    // or next version's CTID for updated rows

    uint16 t_infomask;              // Status bits (used for visibility)
    uint16 t_infomask2;             // More status bits + number of attributes

    // Fields for visibility:
    TransactionId t_xmin;           // Created by this transaction
    TransactionId t_xmax;           // Deleted/updated by this transaction
    CommandId t_cid;                // Within-transaction command counter
} HeapTupleHeaderData;

// Page layout:
┌─────────────────────────────────────────────────────────────┐
│ PageHeaderData (24B)                                        │
├─────────────────────────────────────────────────────────────┤
│ ItemIdData array (line pointers — 4B per tuple)            │
│   │ (offset, length, flags)                                 │
├─────────────────────────────────────────────────────────────┤
│ ... free space ...                                          │
├─────────────────────────────────────────────────────────────┤
│ HeapTupleHeader + data (from end of page, growing upward)  │
│   │                                                         │
│   │ ┌──────────────────────┐                                │
│   │ │ t_xmin: 1234         │ ← creator XID                 │
│   │ │ t_xmax: 0            │ ← 0 = not deleted/updated     │
│   │ │ t_ctid: (0,1)       │ ← points to itself             │
│   │ │ infomask: HEAP_XMIN_COMMITTED                         │
│   │ └──────────────────────┘                                │
│   │ ┌──────────────────────┐                                │
│   │ │ t_xmin: 1234         │                                │
│   │ │ t_xmax: 5678         │ ← updated by XID 5678         │
│   │ │ t_ctid: (1,2)       │ ← redirects to new version     │
│   │ │ infomask: HEAP_XMIN_COMMITTED | HEAP_XMAX_COMMITTED  │
│   │ └──────────────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

**UPDATE Trace — PostgreSQL:**

```
Transaction A: BEGIN; SELECT balance FROM accounts WHERE id = 5;
    → Sees: t_xmin = 100, t_xmax = 0, balance = 1000
    → Records snapshot: xmin_snapshot = {100}, xmax_snapshot = {}

Transaction B: BEGIN; UPDATE accounts SET balance = 900 WHERE id = 5;
    ↓
    Step 1: Mark old tuple as DEAD
        Old tuple: t_xmax = 5678 (B's XID)
        Old tuple is still visible to any transaction with snapshot < 5678
    
    Step 2: Insert NEW tuple
        New tuple: t_xmin = 5678 (B's XID), t_xmax = 0
        New tuple: balance = 900
        New tuple exists in the SAME page (if space) or different page
        t_ctid of old tuple → (block, offset) of new tuple
    
    Step 3: Update index
        For each index on the table:
        - If key changed: insert new index entry → old entry becomes DEAD
        - If key unchanged: HOT (Heap-Only Tuple) update
          → chain within same page, no index change needed
    
    COMMIT;
    ↓
    Visibility rule: t_xmin committed and t_xmax NOT visible to snapshot = visible
    
Transaction A: SELECT balance FROM accounts WHERE id = 5;
    → A's snapshot: xmin = 100, xmax_snapshot = {5678}
    → Sees OLD tuple (t_xmin = 100, t_xmax = 5678)
    → Rule: t_xmin IS in snapshot, t_xmax IS visible in snapshot
    → Therefore: old tuple IS visible to A, new tuple is NOT
    → Returns: balance = 1000
    → Transaction A sees its consistent snapshot!
```

**InnoDB MVCC — Different Approach:**

```c
// InnoDB stores old versions in ROLLBACK SEGMENT (undo log), NOT in-page:

// InnoDB B-Tree page:
┌─────────────────────────────────┐
│ Clustered Index Record          │
│ ┌─────────────────────────────┐ │
│ │ DB_TRX_ID: 5678             │ │  ← Last modifying transaction
│ │ DB_ROLL_PTR: undo_ptr      │ │  ← Pointer to rollback segment
│ │ balance: 900                │ │  ← CURRENT value
│ └─────────────────────────────┘ │
└─────────────────────────────────┘

// Undo log (rollback segment):
┌─────────────────────────────────┐
│ Undo Log Record (TRX 5678)     │
│ ┌─────────────────────────────┐ │
│ │ Previous value: balance=1000│ │
│ │ Next undo: ptr_to_prev     │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

**Key Differences:**

| Aspect | PostgreSQL | MySQL InnoDB |
|--------|-----------|--------------|
| **Storage** | Old versions stay in-page (dead tuples) | Old versions in rollback segment (undo log) |
| **Cleanup** | VACUUM reclaims dead tuples | Purge thread reclaims undo log |
| **Visibility** | Compare t_xmin/t_xmax with snapshot | Construct version from rollback ptr |
| **Update** | INSERT new tuple, mark old as dead | In-place update, save old to undo log |
| **HOT** | Heap-Only Tuple (same page) if no index change | Same page update possible (B-Tree) |
| **Page split** | Can trigger VACUUM fragmentation | Can cause B-Tree page splits |
| **Free space** | Each dead tuple occupies space until VACUUM | Undo log space is recycled faster |

**Vacuum in PostgreSQL:**

```sql
-- VACUUM does two things:
-- 1. Removes dead tuples → frees space within pages
-- 2. Updates visibility map → enables index-only scans

-- Autovacuum trigger:
--   Vacuum threshold = vac_base_keep + vac_scale_factor × reltuples
--   Default: 50 + 0.2 × reltuples
--   So for 1M row table: 50 + 200K = 200,050 dead tuples → triggers VACUUM

-- Aggressive VACUUM (wraparound prevention):
--   When age(t_xmin) > autovacuum_freeze_max_age (default 200M)
--   MUST happen periodically to prevent XID wraparound!
--   During wraparound: database becomes read-only!

-- Tuning for high-update workloads:
ALTER TABLE accounts SET (
    autovacuum_vacuum_scale_factor = 0.01,    -- Trigger at 1% dead tuples
    autovacuum_vacuum_threshold = 1000,       -- Minimum dead tuples
    autovacuum_vacuum_cost_limit = 10000      -- Allow faster vacuum I/O
);
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage format** | Knows PG keeps dead tuples in-page; InnoDB uses undo log |
| **Visibility rules** | Can compute which version a transaction sees given snapshot |
| **Vacuum** | Understands autovacuum triggers, freeze, XID wraparound |
| **HOT updates** | Knows HOT vs non-HOT and index implications |

---

## 3. Transaction Isolation Levels & Anomalies

**Q:** "A user reports that a bank transfer between two accounts (A: $1000, B: $500) shows A debited $100 but B never received it. Another query shows both A and B with $1400 total. What isolation anomaly happened? Trace through each isolation level and explain which prevents this."

**What They're Really Testing:** Whether you can map real anomalies to isolation levels and reason about serializability.

### Answer

**The Anomaly — Lost Update (or Write Skew):**

```
Initial state:
  Account A: $1000
  Account B: $500
  Total:     $1500

Transaction 1: Transfer $100 from A to B
  T1: READ(A)   → 1000
  T1: A = A - 100 → 900
  T1: READ(B)   → 500
  T1: B = B + 100 → 600
  T1: WRITE(A)  → 900
  T1: WRITE(B)  → 600

Transaction 2: Check and distribute interest
  T2: READ(A)   → 1000 (reads BEFORE T1's write!)
  T2: READ(B)   → 500  (reads BEFORE T1's write!)
  T2: interest = (1000 + 500) × 0.05 = 75
  T2: A = A + 37 → 1037
  T2: B = B + 38 → 538   (rounding)
  T2: WRITE(A)
  T2: WRITE(B)

What if T1 and T2 interleave?
  T1: READ(A) = 1000
  T1: A = 900
  T2: READ(A) = 1000  ← Dirty Read? No, T1 hasn't committed yet...
  T2: READ(B) = 500
  T1: READ(B) = 500
  T1: B = 600
  T1: WRITE(A) → 900  ← COMMIT
  T1: WRITE(B) → 600  ← COMMIT
  T2: interest = 75
  T2: A = 1037
  T2: B = 538
  T2: WRITE(A) → 1037 ← OVERWRITES T1's write!
  T2: WRITE(B) → 538  ← OVERWRITES T1's write!

Result: A = 1037 (should be 900 + 37 = 937)
        B = 538  (should be 600 + 38 = 638)
        Total = 1575 (wrong! should be 1500)
        The $100 transfer was LOST!
```

**Anomaly Trace Through Isolation Levels:**

```sql
-- READ UNCOMMITTED:
--   Anomaly: Dirty Read + Lost Update
--   T2 can read T1's uncommitted writes
--   Result: wrong total, but at least values reflect partial updates

-- READ COMMITTED (PostgreSQL default):
--   Anomaly: Lost Update still possible!
--   T2 reads committed values, but after T1 commits:
--     T2: READ(A) → 900 (sees T1's commit)
--     T2: READ(B) → 600 (sees T1's commit)
--   BUT: T2 calculated interest before seeing T1's commit!
--   → T2 overwrites T1's update with stale calculation
--   → LOST UPDATE!

-- REPEATABLE READ (PostgreSQL):
--   Even with repeatable reads, the phantom READ + stale calc causes:
--   T1: SELECT balance FROM accounts WHERE id = 1 → 1000
--   T2: SELECT balance FROM accounts WHERE id = 1 → 1000 (snapshot)
--   T1: UPDATE accounts SET balance = 900 WHERE id = 1
--   T2: UPDATE accounts SET balance = 1037 WHERE id = 1
--   → In PostgreSQL, T2's UPDATE would DETECT CONFLICT:
--      "ERROR: could not serialize access due to concurrent update"
--   → T2 must RETRY!
--   → This is SERIALIZABLE behavior in practice!

-- SERIALIZABLE (PostgreSQL):
--   Uses SSI (Serializable Snapshot Isolation)
--   Tracks read-write conflicts via SIREAD locks
--   Detects WRITE SKEW anomaly:
--     T1 reads A, writes A and B
--     T2 reads A and B, writes A and B
--     → rw-conflict detected
--     → One transaction aborted
```

**Preventing Lost Updates — The Right Way:**

```sql
-- Option 1: SELECT ... FOR UPDATE (Pessimistic Locking)
BEGIN;
SELECT balance FROM accounts WHERE id = 1 FOR UPDATE;
-- This LOCKs the row until commit
-- T2's SELECT ... FOR UPDATE will BLOCK until T1 commits
-- T2 then sees T1's updated value

-- Option 2: Optimistic Locking with version column
BEGIN;
SELECT balance, version FROM accounts WHERE id = 1;
-- version = 5
UPDATE accounts
SET balance = 900, version = version + 1
WHERE id = 1 AND version = 5;
-- If T2 already updated: rows affected = 0 → RETRY
-- COMMIT;

-- Option 3: Atomic UPDATE
UPDATE accounts
SET balance = balance - 100
WHERE id = 1;
-- No read-before-write → no race condition
```

**Isolation Levels Summary:**

| Level | Dirty Read | Non-Repeatable Read | Phantom Read | Lost Update | Write Skew |
|-------|-----------|-------------------|-------------|-------------|------------|
| READ UNCOMMITTED | Possible | Possible | Possible | Possible | Possible |
| READ COMMITTED | Prevented | Possible | Possible | Possible | Possible |
| REPEATABLE READ | Prevented | Prevented | Possible | Prevented* | Possible |
| SERIALIZABLE | Prevented | Prevented | Prevented | Prevented | Prevented |

*PostgreSQL REPEATABLE READ detects concurrent update conflicts via snapshot overlap detection (not true prevention, but practical).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Anomaly identification** | Maps the bug to Lost Update / Write Skew, not just "race condition" |
| **Level trace** | Steps through each isolation level showing exact behavior |
| **PG-specific** | Knows PostgreSQL's REPEATABLE READ detects update conflicts |
| **Fix** | Proposes FOR UPDATE, optimistic locking, or atomic UPDATE |

---

## 4. Query Optimization & Execution Plans

**Q:** "The following query is slow (30 seconds) on a table with 10M rows. Analyze and optimize it. Walk me through how PostgreSQL would execute this."

```sql
SELECT u.name, COUNT(o.id) as order_count, SUM(o.amount) as total_spent
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE u.created_at >= '2024-01-01'
  AND o.status IN ('completed', 'shipped')
  AND o.created_at >= '2024-01-01'
GROUP BY u.id, u.name
HAVING COUNT(o.id) > 5
ORDER BY total_spent DESC
LIMIT 50;
```

**What They're Really Testing:** Whether you can read and optimize query plans — understanding join strategies, index selection, and statistics.

### Answer

**Initial Execution Plan Analysis:**

```sql
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT ...;
```

```
                                                                 QUERY PLAN
----------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=1234567.89..1234598.76 rows=50 width=72) (actual time=28745.3..28746.1 rows=50 loops=1)
   ->  Sort  (cost=1234567.89..1234598.76 rows=12345 width=72) (actual time=28745.3..28746.1 rows=50 loops=1)
         Sort Key: (sum(o.amount)) DESC
         Sort Method: quicksort  Memory: 1024kB
         ->  HashAggregate  (cost=1234500..1234598.76 rows=12345 width=72) (actual time=28600.2..28730.1 rows=12345 loops=1)
               Group Key: u.id, u.name
               Filter: (count(o.id) > 5)
               Rows Removed by Filter: 500000
               ->  Hash Right Join  (cost=50000..1234000 rows=6000000 width=20) (actual time=1200..28000 rows=6000000 loops=1)
                     Hash Cond: (o.user_id = u.id)
                     ->  Seq Scan on orders o  (cost=0..500000 rows=6000000 width=16) (actual time=0.5..15000 rows=6000000 loops=1)
                           Filter: ((status = ANY ('{completed,shipped}'::text[])) AND (created_at >= '2024-01-01'::date))
                           Rows Removed by Filter: 4000000
                     ->  Hash  (cost=30000..30000 rows=1000000 width=12) (actual time=1199..1199 rows=1000000 loops=1)
                           Buckets: 131072  Batches: 8  Memory Usage: 4096kB
                           ->  Seq Scan on users u  (cost=0..30000 rows=1000000 width=12) (actual time=0.2..800 rows=1000000 loops=1)
                                 Filter: (created_at >= '2024-01-01'::date)
                                 Rows Removed by Filter: 9000000
 Planning Time: 0.5 ms
 Execution Time: 28746.1 ms
```

**Problem Diagnosis:**

```
Problems identified:
1. ✅ Full table scan on users (10M rows, but 1M qualify → 10%)
2. ❌ Full table scan on orders (10M rows, 6M qualify → JOIN)
3. ❌ Hash Right Join on 6M × 1M = expensive
4. ❌ HashAggregate on 512K rows (temp file if memory insufficient)
5. ✅ LIMIT 50 fetched early, but all computation done first!
```

**Optimization Strategy:**

```sql
-- Step 1: Create indexes
CREATE INDEX idx_users_created_at_id ON users (created_at, id) 
    WHERE created_at >= '2024-01-01';
-- Covering index: created_at filter + id for join

CREATE INDEX idx_orders_user_status_date ON orders (user_id, status, created_at, amount)
    WHERE created_at >= '2024-01-01';
-- Covering index for the join + WHERE + aggregation

-- Step 2: Rewrite the query
EXPLAIN (ANALYZE, BUFFERS, TIMING)
WITH filtered_users AS (
    SELECT id, name FROM users
    WHERE created_at >= '2024-01-01'
),
filtered_orders AS (
    SELECT user_id, id, amount FROM orders
    WHERE status IN ('completed', 'shipped')
      AND created_at >= '2024-01-01'
),
user_orders AS (
    SELECT u.id, u.name,
           COUNT(o.id) AS order_count,
           SUM(o.amount) AS total_spent
    FROM filtered_users u
    INNER JOIN filtered_orders o ON o.user_id = u.id
    GROUP BY u.id, u.name
    HAVING COUNT(o.id) > 5
)
SELECT name, order_count, total_spent
FROM user_orders
ORDER BY total_spent DESC
LIMIT 50;
```

**Optimized Execution Plan:**

```
                                                                 QUERY PLAN
----------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=45000.5..45001.2 rows=50 width=72) (actual time=125.3..125.5 rows=50 loops=1)
   ->  Sort  (cost=45000.5..45001.2 rows=345 width=72) (actual time=125.3..125.4 rows=50 loops=1)
         Sort Key: (sum(o.amount)) DESC
         Sort Method: top-N quicksort  Memory: 40kB
         ->  GroupAggregate  (cost=44000..44987.6 rows=345 width=72) (actual time=80.2..124.8 rows=345 loops=1)
               Group Key: u.id
               Filter: (count(o.id) > 5)
               ->  Merge Join  (cost=44000..44967.3 rows=600000 width=20) (actual time=60.1..115.4 rows=600000 loops=1)
                     Merge Cond: (u.id = o.user_id)
                     ->  Index Scan using idx_users_created_at_id on users u  (cost=0..5000 rows=1000000 width=12)
                           (actual time=0.3..20.5 rows=1000000 loops=1)
                     ->  Index Scan using idx_orders_user_status_date on orders o  (cost=0..38000 rows=6000000 width=16)
                           (actual time=0.5..60.2 rows=6000000 loops=1)
 Planning Time: 0.8 ms
 Execution Time: 125.8 ms
```

**Optimization Gains: 30s → 125ms (240× improvement)**

```
Key changes:
1. Covering indexes → Index-Only Scans (no heap fetches)
2. Merge Join instead of Hash Join → sorted input reduces memory
3. INNER JOIN instead of LEFT JOIN (HAVING already filters nulls)
4. CTE forces materialization of filtered sets
5. top-N sort uses minimal memory (40KB vs 1MB)
```

**Additional Optimizations for Sub-50ms:**

```sql
-- If the query is very frequent, use a materialized view:
CREATE MATERIALIZED VIEW user_order_summary AS
SELECT u.id, u.name, 
       COUNT(o.id) AS order_count,
       SUM(o.amount) AS total_spent,
       MAX(o.created_at) AS last_order
FROM users u
INNER JOIN orders o ON o.user_id = u.id
WHERE o.status IN ('completed', 'shipped')
  AND o.created_at >= '2024-01-01'
GROUP BY u.id, u.name
HAVING COUNT(o.id) > 5;

CREATE INDEX ON user_order_summary (total_spent DESC);

REFRESH MATERIALIZED VIEW CONCURRENTLY user_order_summary;
-- CONCURRENTLY = non-blocking refresh (requires unique index)

-- Query becomes:
SELECT * FROM user_order_summary
ORDER BY total_spent DESC
LIMIT 50;
-- ~2ms
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Plan reading** | Identifies seq scans, hash joins, sort methods from plan |
| **Index design** | Creates covering indexes, partial indexes, correct column order |
| **Join optimization** | Knows when to use Merge vs Hash vs Nested Loop Join |
| **Materialization** | Knows CTE materialization, materialized views for precomputation |

---

## 5. Indexing Strategies: B-Tree vs Hash vs GiST vs GIN vs BRIN

**Q:** "You have a PostgreSQL table with 100M rows containing the following query patterns: (A) exact-match lookups on user_id, (B) full-text search on document_body, (C) range queries on created_at, (D) JSONB queries on metadata. Choose the optimal index type for each."

**What They're Really Testing:** Whether you understand the internal data structures of each index type, not just their names.

### Answer

```sql
-- B-Tree (default) — for user_id exact match and range:
-- Best for: =, >, <, >=, <=, BETWEEN, IN, ORDER BY
-- Structure: balanced tree, leaf pages contain (key, TID)
-- Space: ~24B/row (key + 6B TID + page overhead)
SELECT * FROM users WHERE user_id = 42;
CREATE INDEX idx_user_id ON users USING btree (user_id);

-- Hash — for exact-match lookups only (no range queries):
-- Best for: = operator only
-- Structure: hash code + TID in hash buckets
-- Space: ~24B/row (4B hash + 6B TID + page overhead)
SELECT * FROM sessions WHERE session_token = 'abc123';
CREATE INDEX idx_session_token ON sessions USING hash (session_token);

-- GIN for full-text search:
-- Best for: tsvector @@ tsquery, JSONB @>, arrays, full-text
-- Structure: inverted index (maps tokens to rows), slower to build
SELECT * FROM documents WHERE doc_body @@ to_tsquery('english', 'postgresql & indexing');
CREATE INDEX idx_doc_search ON documents USING GIN (to_tsvector('english', doc_body));

-- BRIN for created_at range queries on append-only data:
-- Best for: correlated physical order (insert time matches index order)
-- Structure: stores min/max per page range (default 128 pages per range)
-- Space: 1000× smaller than B-Tree for time-series data!
SELECT * FROM events WHERE created_at BETWEEN '2024-01-01' AND '2024-01-02';
CREATE INDEX idx_created ON events USING BRIN (created_at) WITH (pages_per_range = 32);

-- GIN for JSONB:
-- Best for: @>, ?, ?|, ?& operators
-- Structure: inverted index (maps keys/values to rows), slow to build
SELECT * FROM profiles WHERE metadata @> '{"role": "admin"}';
CREATE INDEX idx_metadata ON profiles USING GIN (metadata jsonb_path_ops);
```

| Index Type | Query Pattern | Build Speed | Size | Write Overhead |
|-----------|--------------|-------------|------|---------------|
| B-Tree | =, ranges, ORDER BY | Fast | ~24B/row | ~2× log(N) writes |
| Hash | = only (no ranges) | Fast | ~24B/row | ~same as B-Tree |
| GiST | tsquery, geometry | Medium | ~30B/row | Medium (WAL-logged) |
| GIN | JSONB, arrays, tsvector | Slow (3×) | ~50B/row | High (inverted list update) |
| BRIN | Range on append-only | Fastest | ~0.1B/row | Minimal |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Internal structure** | Knows B-Tree has leaf-level linked list, GIN is inverted index, BRIN is page min/max |
| **Write overhead** | Can explain why GIN is slow on UPDATE (must rebuild inverted list) |
| **Physical correlation** | Knows BRIN is worthless on randomly inserted data |
| **Trade-off matrix** | Maps query patterns to index types with quantitative reasoning |

---

## 6. Replication: Synchronous vs Asynchronous

**Q:** "Design the replication strategy for a global payment database. The compliance team requires zero data loss (RPO=0), but the business demands sub-50ms write latency. Show the quorum configurations and failure scenarios."

**Answer:**

```yaml
Solution: Synchronous replication with quorum commit

Topology: 3 data centers (US-East, US-West, EU-West)
Each DC has 1 primary + 2 replicas (synchronous within DC)

Write path:
  1. Client writes to nearest primary
  2. Primary sends WAL to:
     - Local replicas (sync, within DC, ~0.5ms)
     - Remote quorum (1 of 2 remote DCs, sync, ~60ms)
  3. Primary commits when:
     - Local quorum ACK'd (1 of 2 local sync replicas)
     - Remote quorum ACK'd (1 of 2 remote sync replicas)
     Total: commit = min 2 confirmations

Failure scenarios:
  - US-West DC failure: US-East + EU-West continue with quorum
  - US-West network partition:
    - If EU-West can't reach US-West: EU-West writes to local quorum only
    - Remaining DCs form new quorum
  - RPO = 0 (no data loss on any single DC failure)
  - RTO = < 30s (auto-failover to secondary DC)
```

---

## 7. Sharding Strategies

**Q:** "Design a sharding strategy for a social media platform with 500M users. Compare range-based, hash-based, and directory-based sharding. How do you handle cross-shard queries and resharding?"

**Answer:**

```
Recommendation: Hash-based sharding with 4096 logical shards → 64 physical nodes

     Logical shards (4096)           Physical nodes (64)
┌────┬────┬────┬────┬────┐        ┌────┬────┬────┬────┐
│ 0  │ 1  │ 2  │ 3  │ 4  │ ──→   │ N1 │ N2 │ N3 │ N4 │
├────┼────┼────┼────┼────┤        ├────┼────┼────┼────┤
│ 5  │ 6  │ 7  │ 8  │ 9  │        │... │... │... │... │
├────┼────┼────┼────┼────┤        └────┴────┴────┴────┘
│ ...│ ...│ ...│ ...│ ...│        Each node: 64 shards
└────┴────┴────┴────┴────┘

shard_id = hash(user_id) % 4096
node_id  = shard_id / 64

Cross-shard queries:
  - Fan-out: query all shards, merge results (slow but correct)
  - Scatter-gather pattern with timeout + retry
  - Use secondary indexes for frequent cross-shard patterns

Resharding (64 → 128 nodes):
  - Each shard moves from old node to new node
  - Move shard #0 from N1 to N1' (new)
  - During move: N1 handles reads, N1' handles writes for shard #0
  - After move: update mapping table, drop old shard
```

---

## 8. PostgreSQL Buffer Pool & WAL Internals

**Q:** "A query that was running in 50ms suddenly takes 5 seconds. You check `pg_stat_bgwriter` and see `buffers_backend_fsync` is high and `checkpoints_timed` is low. Walk through how PostgreSQL's buffer pool eviction works, how WAL interacts with checkpoints, and what's causing the slowdown."

**What They're Really Testing:** Whether you understand the interplay between shared buffers, WAL, and checkpoints — the three pillars of PostgreSQL's durability and performance.

### Answer

**Shared Buffer Pool Architecture:**

```
PostgreSQL Shared Buffers (default: 128MB, recommended: 25% of RAM)

┌────────────────────────────────────────────────────────────────┐
│ Buffer Descriptors (in shared memory)                         │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│ │ buf1 │ │ buf2 │ │ buf3 │ │ ...  │ │ bufN │ │ bufN │       │
│ │state:│ │state:│ │state:│ │      │ │      │ │      │       │
│ │ref:3 │ │ref:0 │ │ref:1 │ │      │ │      │ │      │       │
│ │usage:2│ │usage:0│ │usage:1│ │      │ │      │ │      │       │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘       │
└────────────────────────────────────────────────────────────────┘
         │               │
         ▼               ▼
┌─────────────────┐ ┌─────────────────┐
│ Buffer Pool     │ │ WAL (pg_wal)    │
│ (8KB pages)     │ │ (16MB segments) │
│ ┌─────┐ ┌─────┐│ │ ┌─────┐ ┌─────┐│
│ │pg 1 │ │pg 2 ││ │ │WAL1 │ │WAL2 ││
│ └─────┘ └─────┘│ │ └─────┘ └─────┘│
└─────────────────┘ └─────────────────┘
```

**Clock Sweep Eviction Algorithm:**

```python
# PostgreSQL uses a "clock sweep" (not LRU!) for buffer eviction.
# Reason: LRU requires locks on every buffer access → contention.
# Clock sweep: approximate LRU with low overhead.

class ClockSweep:
    """
    Each buffer has a usage_count (0-5).
    - When a buffer is accessed: usage_count = min(5, usage_count + 1)
    - When searching for a victim: sweep clockwise, decrement each
    - First buffer with usage_count == 0 is the victim
    - If none found: wrap around and decrement again
    """
    def __init__(self, num_buffers: int):
        self.buffers = [{
            'usage_count': 0,
            'is_dirty': False,
            'pin_count': 0,     # 0 = unpinned, >0 = currently being read
            'page_id': None,
        } for _ in range(num_buffers)]
        self.clock_hand = 0  # Current sweep position

    def access_buffer(self, idx: int):
        """Called when a buffer is hit (no lock needed!)"""
        self.buffers[idx]['usage_count'] = min(5, self.buffers[idx]['usage_count'] + 1)

    def evict_one(self) -> int:
        """
        Find a buffer to evict. Returns buffer index.
        Called when a new page needs to be read but all buffers are in use.
        """
        while True:
            buf = self.buffers[self.clock_hand]

            if buf['pin_count'] > 0:
                # Buffer is pinned (currently being read/written) — skip
                self.clock_hand = (self.clock_hand + 1) % len(self.buffers)
                continue

            if buf['usage_count'] > 0:
                # Recently used — decrement and move on
                buf['usage_count'] -= 1
                self.clock_hand = (self.clock_hand + 1) % len(self.buffers)
                continue

            # Found a victim (usage_count == 0)
            victim_idx = self.clock_hand
            self.clock_hand = (self.clock_hand + 1) % len(self.buffers)

            if buf['is_dirty']:
                # Must write to disk before reuse → triggers bgwriter
                self.write_to_disk(victim_idx)

            return victim_idx

# Clock sweep means:
#   - Hot pages stay in cache (usage_count keeps getting reset)
#   - Cold pages get evicted (usage_count decays to 0)
#   - No expensive LRU list maintenance
#   - But: large sequential scans can "pollute" the cache
#     (each scanned page gets usage_count=1, evicting real hot pages)
```

**The Problem — Checkpoint Starvation:**

```sql
-- Symptom: high buffers_backend_fsync, low checkpoints_timed

SELECT * FROM pg_stat_bgwriter;
--   checkpoints_timed: 5          (expected: many)
--   checkpoints_req: 98           (too many!)
--   buffers_backend: 450000       (backend wrote instead of bgwriter)
--   buffers_backend_fsync: 12000  (backend did fsync! BAD!)
--   maxwritten_clean: 45          (bgwriter couldn't keep up)

-- Root cause:
--   1. WAL generates too many writes (full_page_writes = on)
--   2. Checkpoint frequency is too low (checkpoint_timeout > 15min)
--   3. bgwriter can't flush dirty buffers fast enough
--   4. Backends start doing their own writes + fsync → SLOW!
```

**WAL Write and Checkpoint Mechanics:**

```python
# WAL (Write-Ahead Logging): Every data change is written to WAL BEFORE
# the data page. On crash: replay WAL to recover.

class WALManager:
    """
    WAL architecture:
    - WAL segments: 16MB each, stored in pg_wal/
    - Each record has a unique LSN (Log Sequence Number)
    - LSN = (segment_file, offset_within_segment)
    - WAL insertion is SERIAL (one at a time, protected by WALInsertLock)
    """
    def __init__(self):
        self.insert_lsn = 0  # Next LSN to assign
        self.flush_lsn = 0   # Last LSN fsync'd to disk
        self.write_lsn = 0   # Last LSN written (but maybe not fsync'd)

    def insert_record(self, data: bytes) -> int:
        """
        Step 1: Reserve space in WAL buffer
        Step 2: Copy data to WAL buffer
        Step 3: Update insert_lsn
        """
        lsn = self.reserve_space(len(data))
        self.wal_buffer[self.get_offset(lsn)] = data
        self.insert_lsn = lsn + len(data)
        return lsn

    def flush(self, lsn: int):
        """
        Ensure all WAL up to 'lsn' is on disk.
        Uses wal_sync_method:
          - open_datasync (default on Linux): fdatasync()
          - fdatasync: fsync()
          - fsync_writethrough: write-through caching
        """
        if lsn > self.flush_lsn:
            # Write from write_lsn to lsn
            os.write(self.wal_fd, self.wal_buffer[self.write_lsn:lsn])
            self.write_lsn = lsn
            # fsync to guarantee durability
            os.fdatasync(self.wal_fd)
            self.flush_lsn = lsn

    def checkpoint(self, force: bool = False):
        """
        Checkpoint writes ALL dirty buffers to disk and advances
        the redo point so WAL can be recycled.
        """
        # Phase 1: Write all dirty shared buffers
        for buf in shared_buffers:
            if buf.is_dirty:
                # Write buffer (with full_page_write if first after checkpoint)
                if buf.is_first_write_after_checkpoint:
                    # full_page_write: write the ENTIRE 8KB page to WAL
                    # Prevents "torn page" on partial write during crash
                    wal.insert_record(buf.full_page_data)
                buf.write_to_disk()
                buf.is_dirty = False

        # Phase 2: Flush WAL (all WAL up to this point)
        wal.flush(wal.insert_lsn)

        # Phase 3: Update pg_control (redo point)
        self.redo_point = wal.insert_lsn

        # Phase 4: Remove old WAL segments (before redo point)
        self.recycle_wal_segments()
```

**Diagnosing the 5s Query:**

```sql
-- Diagnosis queries:

-- 1. Check if the query is waiting on I/O
SELECT pg_blocking_pids(pid), wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE state = 'active' AND wait_event IS NOT NULL;
-- If wait_event = 'BufferIO' or 'WALWrite': I/O bottleneck

-- 2. Check checkpoint frequency
SELECT * FROM pg_stat_bgwriter;
-- If checkpoints_req >> checkpoints_timed: checkpoint happening too often

-- 3. Check shared_buffers hit ratio
SELECT 'buffer_hit_ratio',
       (blks_hit::float / (blks_hit + blks_read) * 100)::numeric(5,2)
FROM pg_stat_database WHERE datname = current_database();
-- If < 95%: shared_buffers too small or bad query plans

-- 4. Fix: Increase checkpoint distance
ALTER SYSTEM SET checkpoint_completion_target = 0.9;  -- Spread writes over 90% of window
ALTER SYSTEM SET max_wal_size = '4GB';                -- Checkpoint less often
ALTER SYSTEM SET checkpoint_timeout = '15min';         -- Max interval
SELECT pg_reload_conf();
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Clock sweep** | Explains why PostgreSQL doesn't use LRU (lock contention) and how usage_count works |
| **WAL LSN** | Knows insert/flush/write LSN positions and the WAL flush protocol |
| **Checkpoint interaction** | Understands full_page_writes, checkpoint spreading, and how dirty buffers accumulate |
| **Diagnosis** | Can read pg_stat_bgwriter to identify the root cause of I/O stalls |

---

## 9. Deadlock Detection & Lock Escalation

**Q:** "A production PostgreSQL database running at 80% CPU suddenly spikes to 100% and stays there. Queries are completing but slowly. You notice `pg_locks` shows hundreds of `Relation` locks and many processes waiting on `transactionid`. Walk through how PostgreSQL detects deadlocks, how lock escalation works (or doesn't), and how to resolve this."

**What They're Really Testing:** Whether you understand PostgreSQL's lock manager internals — the difference between relation-level and row-level locks, deadlock detection mechanics, and how InnoDB's lock escalation differs.

### Answer

**PostgreSQL Lock Types:**

```
PostgreSQL has TWO independent lock systems:

1. Heavyweight Locks (pg_locks):
   - Relation-level: AccessShare, RowShare, RowExclusive, ShareUpdateExclusive,
                     Share, ShareRowExclusive, Exclusive, AccessExclusive
   - Row-level: FOR UPDATE, FOR NO KEY UPDATE, FOR SHARE, FOR KEY SHARE
   - Transaction-level: transactionid (row XMIN/XMAX waits)
   - Visible in pg_locks, managed by lock manager

2. Lightweight Locks (LWLock):
   - Internal to PostgreSQL subsystems
   - Buffer mapping, WAL insert, clog, etc.
   - NOT visible in pg_locks! (visible in pg_stat_activity wait_event)
   - Uses spinlock + sleep retry
```

**Lock Modes and Conflicts:**

```
              Requested Lock Mode
              AS  RS  RE  SU  S  SR  E  AE
Held Mode     ──────────────────────────────
AccessShare   ✅  ✅  ✅  ✅  ✅  ✅  ✅  ❌
RowShare      ✅  ✅  ✅  ✅  ✅  ✅  ❌  ❌
RowExclusive  ✅  ✅  ✅  ❌  ❌  ❌  ❌  ❌
ShareUpdateEx ✅  ✅  ❌  ❌  ❌  ❌  ❌  ❌
Share         ✅  ✅  ❌  ❌  ❌  ❌  ❌  ❌
ShareRowExcl  ✅  ❌  ❌  ❌  ❌  ❌  ❌  ❌
Exclusive     ✅  ❌  ❌  ❌  ❌  ❌  ❌  ❌
AccessExclus  ❌  ❌  ❌  ❌  ❌  ❌  ❌  ❌

Key insight: RowExclusive (the default for INSERT/UPDATE/DELETE)
conflicts ONLY with Share, ShareRowExclusive, Exclusive, AccessExclusive.
This is why many SELECT queries can run alongside writes!
```

**Deadlock Detection Algorithm:**

```python
# PostgreSQL's deadlock detector runs every deadlock_timeout (1s).
# It builds a "waits-for" graph and searches for cycles using DFS.

class DeadlockDetector:
    """
    Simplified PostgreSQL deadlock detection.
    """
    def __init__(self):
        self.waits_for = {}  # {waiter_pid: blocker_pid}
        self.lock_queue = {}  # {lock_id: [waiting_pids]}

    def add_lock_wait(self, waiter: int, lock_id: str):
        """A process starts waiting for a lock."""
        if lock_id not in self.lock_queue:
            self.lock_queue[lock_id] = []
        self.lock_queue[lock_id].append(waiter)

    def remove_lock_holder(self, holder: int, lock_id: str):
        """A process releases a lock. Wake up waiters."""
        if lock_id in self.lock_queue:
            # Wake the first waiter (PG wakes ALL waiters, they recheck)
            self.lock_queue[lock_id].pop(0)

    def build_waits_for_graph(self):
        """
        For each blocked process, find who holds the lock it's waiting for.
        """
        graph = {}
        for lock_id, waiters in self.lock_queue.items():
            for waiter in waiters:
                holder = self.find_lock_holder(lock_id)
                if holder:
                    graph[waiter] = holder
        return graph

    def detect_cycle(self, graph: dict) -> list[int] | None:
        """
        DFS cycle detection in the waits-for graph.
        """
        visited = set()
        in_stack = set()

        def dfs(node: int, path: list[int]) -> list[int] | None:
            visited.add(node)
            in_stack.add(node)
            path.append(node)

            blocker = graph.get(node)
            if blocker in in_stack:
                # Found a cycle!
                cycle_start = path.index(blocker)
                return path[cycle_start:] + [blocker]
            elif blocker and blocker not in visited:
                result = dfs(blocker, path)
                if result:
                    return result

            path.pop()
            in_stack.discard(node)
            return None

        for pid in graph:
            if pid not in visited:
                result = dfs(pid, [])
                if result:
                    return result
        return None

    def resolve_deadlock(self):
        """
        PostgreSQL selects the victim based on:
        1. Transaction age (youngest = cheapest to rollback)
        2. NOT based on amount of work done
        """
        graph = self.build_waits_for_graph()
        cycle = self.detect_cycle(graph)

        if cycle:
            # Pick the newest transaction as victim
            victim = max(cycle, key=lambda pid: self.get_tx_age(pid))
            self.abort_transaction(victim)
            return victim
        return None
```

**InnoDB vs PostgreSQL Lock Escalation:**

```
PostgreSQL:
  - NO lock escalation! Row-level locks NEVER escalate to page or table locks
  - Every row lock stays as a separate entry in the lock table
  - Problem: UPDATE 1M rows in a transaction → 1M lock entries in memory
  - Lock table is sized by max_locks_per_transaction × max_connections
  - If lock table fills: "out of shared memory" error

MySQL InnoDB:
  - Escalation: multiple row locks on the same table → table-level intention lock
  - The lock manager converts many fine-grained locks into fewer coarse ones
  - Reduces memory pressure but increases contention
  - Example: UPDATE ... WHERE status = 'pending' on 1M rows
    → InnoDB may escalate to table-level IX lock
    → Blocks all other writes to the table!

Which is better?
  - PostgreSQL: better concurrency (no escalation = fewer blocking situations)
  - InnoDB: better memory usage (escalation = fewer lock manager entries)
```

**Diagnosing the 100% CPU Scenario:**

```sql
-- Step 1: Find what's using CPU
SELECT pid, state, wait_event_type, wait_event,
       query_start, query
FROM pg_stat_activity
WHERE backend_type = 'client backend'
ORDER BY (EXTRACT(EPOCH FROM now()) - EXTRACT(EPOCH FROM query_start)) DESC;

-- Likely finding: Hundreds of connections on RowExclusive locks
-- Each spends CPU checking lock compatibility

-- Step 2: Check lock count
SELECT count(*), locktype, mode, granted
FROM pg_locks
GROUP BY locktype, mode, granted
ORDER BY count(*) DESC;

-- If many 'relation' + 'RowExclusive' NOT granted: lock contention

-- Step 3: Find the blocked query chain
SELECT blocked.pid, blocked.query, blocker.pid, blocker.query
FROM pg_locks blocked
JOIN pg_locks blocker ON blocked.locktype = blocker.locktype
  AND blocked.database = blocker.database
  AND blocked.relation = blocker.relation
  AND blocked.pid != blocker.pid
WHERE NOT blocked.granted AND blocker.granted;

-- Step 4: Kill the oldest transaction holding conflicting locks
SELECT pg_terminate_backend(
    (SELECT pid FROM pg_stat_activity
     ORDER BY query_start ASC LIMIT 1)
);
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Lock types** | Distinguishes heavyweight locks from LWLocks, knows conflict matrix |
| **Deadlock detection** | Explains waits-for graph, cycle detection, victim selection |
| **Lock escalation** | Knows PostgreSQL never escalates; InnoDB does — tradeoffs of each |
| **Diagnosis** | Can identify lock contention from pg_locks and pg_stat_activity |

---

## 10. Concurrency Control: 2PL vs OCC vs MVCC

**Q:** "Design a booking system for a concert venue with 10,000 seats. Two customers try to book the last seat simultaneously. Compare how Strict 2PL, Optimistic Concurrency Control (OCC), and MVCC would handle this. Which would you choose and why?"

**What They're Really Testing:** Whether you understand the fundamental concurrency control paradigms — their guarantees, tradeoffs, and when each is appropriate.

### Answer

**Three Paradigms at a Glance:**

```
Approach          Philosophy                  Guarantee         Throughput
────────          ──────────                  ─────────         ──────────
Strict 2PL        Lock first, then do work   Conflict serializable    Low
OCC               Do work, then validate     Conflict serializable    Medium (low contention only)
MVCC              Snapshot + detect conflict Snapshot isolation       High
```

**Strict 2PL (Two-Phase Locking):**

```sql
-- Phase 1: Growing (acquire locks, no release)
-- Phase 2: Shrinking (release locks, no acquire)

BEGIN;
-- GROWING phase:
SELECT * FROM seats WHERE id = 42 FOR UPDATE;  -- Acquire exclusive lock
-- Now we hold the lock. No other transaction can read/write seat 42.

UPDATE seats SET booked_by = 'Alice' WHERE id = 42;

-- SHRINKING phase:
COMMIT;  -- Release ALL locks at commit

-- If another transaction also tries to lock seat 42:
--   → It BLOCKS until we commit → NO lost update!
--   → But: no concurrency! Only one booking at a time for the same seat.

-- Problem: Can cause deadlocks when multiple resources are involved:
--   T1: LOCK seat 42, wants seat 50
--   T2: LOCK seat 50, wants seat 42
--   → DEADLOCK! One must be aborted.
```

**OCC (Optimistic Concurrency Control):**

```python
# OCC: Assume no conflict. Do the work. Validate at commit.
# Three phases: Read → Validate → Write

class OCCTransaction:
    """
    OCC transaction for booking seats.
    """
    def __init__(self, db):
        self.db = db
        self.read_set = set()     # Objects I read
        self.write_set = set()    # Objects I'll write
        self.old_values = {}      # Snapshot of read values
        self.start_ts = None

    def read(self, key: str):
        """PHASE 1: Read — record the value and version"""
        value, version = self.db.get_with_version(key)
        self.read_set.add(key)
        self.old_values[key] = (value, version)
        return value

    def write(self, key: str, value):
        """PHASE 1: Write — buffer the write, don't apply yet"""
        self.write_set.add(key)
        self.old_values[key + '_new'] = value

    def commit(self) -> bool:
        """PHASE 2: Validate — check no conflicts"""
        # Backward validation: check if any object I read was
        # modified by another transaction since I read it
        for key in self.read_set:
            _, current_version = self.db.get_with_version(key)
            if current_version != self.old_values[key][1]:
                # Conflict! Another transaction modified this key.
                return False  # Must retry!

        # PHASE 3: Write — apply all buffered writes
        for key in self.write_set:
            self.db.put(key, self.old_values[key + '_new'])
        return True

    # For the booking scenario:
    # T1 and T2 both read seat 42 (available = true)
    # Both try to book it
    # T1 commits first: validates, writes, succeeds
    # T2 commits: VALIDATION FAILS! (seat 42's version changed)
    # T2 retries from scratch
    #
    # Tradeoff: Under LOW contention, OCC wins (no locking overhead)
    # Under HIGH contention (like last-seat scenario), lots of retries → waste
```

**MVCC (Multi-Version Concurrency Control):**

```sql
-- MVCC: Each transaction sees a SNAPSHOT of the database at its start time.
-- Readers NEVER block writers, writers NEVER block readers.

-- PostgreSQL's MVCC for the booking scenario:

-- Transaction A:
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- Sees snapshot of seat 42: available=true, version=5

-- Transaction B:
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- Sees SAME snapshot: available=true, version=5

-- A books the seat:
UPDATE seats SET booked_by = 'Alice' WHERE id = 42;
-- Creates new tuple version (t_xmin = A, t_xmax = 0)
-- Old tuple: t_xmax = A (not committed yet)
COMMIT;

-- B books the same seat:
UPDATE seats SET booked_by = 'Bob' WHERE id = 42;
-- PostgreSQL detects: the row has been updated by a concurrent transaction!
-- ERROR: could not serialize access due to concurrent update
-- B's transaction is ABORTED automatically!
-- B must RETRY.

-- Difference from OCC:
--   OCC: validates at commit time after doing all work
--   MVCC: detects conflict at FIRST write that would violate snapshot
--         → earlier detection = less wasted work
```

**Comparison Table:**

| Aspect | Strict 2PL | OCC | MVCC (PostgreSQL) |
|--------|-----------|-----|-------------------|
| **Reads block writes?** | Yes (S-lock) | No | No |
| **Writes block reads?** | Yes (X-lock) | No | No |
| **Writes block writes?** | Yes (queued) | At validation | At first conflicting write |
| **Deadlock possible?** | Yes | No (no locks) | No (SSI might abort) |
| **Best for** | High contention, short txns | Low contention | Mixed workloads |
| **Worst for** | Long transactions | High contention | Long write txns (bloat) |
| **Implementation** | Simple | Moderate | Complex |

**Recommendation for Booking System:**

```sql
-- Use MVCC (PostgreSQL default) + explicit locking for hot spots:

BEGIN ISOLATION LEVEL READ COMMITTED;

-- For the "last seat" scenario, use SELECT FOR UPDATE:
SELECT * FROM seats WHERE id = 42 FOR UPDATE;
-- This serializes access to this specific seat
-- Other seats remain fully concurrent (no table-level lock)

-- Check availability
SELECT available_count FROM venue WHERE id = 1 FOR UPDATE;

-- Book the seat if available
INSERT INTO bookings (seat_id, user_id) VALUES (42, 'Alice');
UPDATE seats SET status = 'booked' WHERE id = 42;
UPDATE venue SET available_count = available_count - 1 WHERE id = 1;

COMMIT;

-- Why this hybrid:
--   - Most seats: MVCC handles reads without blocking
--   - Hot spots (last seat, venue counter): explicit locking prevents race
--   - No table-level locks needed = maximum concurrency
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **2PL phases** | Explains growing and shrinking phases, lock escalation |
| **OCC validation** | Describes read-set validation, retry on conflict, when it excels |
| **MVCC conflict detection** | Knows PG detects conflict on first conflicting write (vs OCC's commit-time) |
| **Practical hybrid** | Recommends MVCC + targeted SELECT FOR UPDATE for hot spots |

---

## 11. Materialized Views & Indexed Views

**Q:** "A reporting dashboard query that aggregates 50M rows takes 45 seconds to run. Users refresh it every minute. The table receives 100 writes/second during business hours. Design a solution using materialized views."

**What They're Really Testing:** Whether you understand materialized views as a tradeoff between freshness and speed — and the mechanics of incremental vs full refresh.

### Answer

**Materialized View vs Live Query:**

```
Aspect              Live Query                   Materialized View
─────────           ──────────                   ─────────────────
Data freshness      100% current                 As of last refresh
Query time          O(N) on 50M rows             O(log N) on indexed view
Storage             0 (uses existing tables)     ~size of result set
Write impact        0 (no overhead)              Refresh cost
Refresh cost        0                             Full rebuild or incremental
Best for            Ad-hoc, infrequent           Repeated, predictable queries
```

**Creating and Refreshing:**

```sql
-- Create a materialized view for the dashboard:
CREATE MATERIALIZED VIEW daily_sales_summary AS
SELECT p.category,
       DATE_TRUNC('day', s.sale_date) AS day,
       COUNT(*) AS num_sales,
       SUM(s.amount) AS total_revenue,
       AVG(s.amount) AS avg_ticket
FROM sales s
JOIN products p ON s.product_id = p.id
WHERE s.sale_date >= NOW() - INTERVAL '30 days'
GROUP BY p.category, DATE_TRUNC('day', s.sale_date)
WITH DATA;  -- Populate immediately

-- Add indexes for query performance:
CREATE UNIQUE INDEX idx_dss_pk ON daily_sales_summary (category, day);
CREATE INDEX idx_dss_revenue ON daily_sales_summary (total_revenue DESC);
```

**Refresh Strategies:**

```sql
-- Strategy 1: Full refresh (blocks readers!)
REFRESH MATERIALIZED VIEW daily_sales_summary;
-- Takes 45 seconds (same as the original query)
-- ALL queries block during refresh → dashboard DOWN for 45s

-- Strategy 2: CONCURRENTLY refresh (non-blocking)
REFRESH MATERIALIZED VIEW CONCURRENTLY daily_sales_summary;
-- Requires a UNIQUE index
-- Takes LONGER (50-60s instead of 45s) but readers are NOT blocked
-- Uses a temporary snapshot + merge approach:
--   1. Create temp view with new data
--   2. Acquire weak lock on matview
--   3. INSERT new rows, UPDATE changed rows, DELETE removed rows
--   4. Drop temp view
--   5. Release lock

-- Strategy 3: Incremental refresh (pg_ivm extension)
-- Requires: CREATE EXTENSION pg_ivm;

CREATE INCREMENTAL MATERIALIZED VIEW daily_sales_summary_immv AS
SELECT p.category,
       DATE_TRUNC('day', s.sale_date) AS day,
       COUNT(*) AS num_sales,
       SUM(s.amount) AS total_revenue
FROM sales s
JOIN products p ON s.product_id = p.id
WHERE s.sale_date >= NOW() - INTERVAL '30 days'
GROUP BY p.category, DATE_TRUNC('day', s.sale_date)
WITH DATA;

-- Now when sales are inserted/updated, the materialized view is
-- automatically updated incrementally (no full refresh needed):
INSERT INTO sales (product_id, amount, sale_date)
VALUES (42, 150.00, NOW());
-- pg_ivm automatically updates the materialized view:
--   finds the matching category + day row
--   increments count, adds to sum
-- Takes ~1ms vs 45 seconds for full refresh!
```

**Designing the Right Refresh Schedule:**

```python
# For the dashboard that needs 1-minute freshness with 100 writes/s:

# Option A: Full refresh every 5 minutes (off-peak)
#   - CONCURRENTLY to avoid blocking
#   - Accepts 5-minute stale data
#   - 45s CPU spike every 5 minutes

# Option B: Incremental materialized view (pg_ivm)
#   - Auto-updates on every write (~1ms overhead)
#   - Always fresh
#   - Requires pg_ivm extension
#   - Best for 1-minute refresh requirement

# Option C: Hybrid approach
#   - Incremental IMMV for real-time (last 24h)
#   - Full refresh nightly for historical data

CREATE INCREMENTAL MATERIALIZED VIEW live_dashboard AS
SELECT ... FROM sales WHERE sale_date >= NOW() - INTERVAL '24 hours'
WITH DATA;

-- Nightly job:
REFRESH MATERIALIZED VIEW CONCURRENTLY historical_dashboard;
```

**PostgreSQL Indexed Views (vs SQL Server):**

```sql
-- PostgreSQL does NOT have "indexed views" like SQL Server.
-- In SQL Server:
--   CREATE UNIQUE CLUSTERED INDEX ON view → view is materialized and index-maintained
--
-- PostgreSQL equivalent:
--   1. CREATE MATERIALIZED VIEW
--   2. CREATE INDEX ON the materialized view
--   3. Schedule REFRESH (or use pg_ivm for auto-refresh)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CONCURRENTLY mechanics** | Knows how non-blocking refresh works (temp table + merge) |
| **Incremental maintenance** | Mentions pg_ivm extension for automatic incremental refresh |
| **Freshness vs cost** | Can recommend refresh interval based on write rate and query tolerance |
| **Index strategy** | Creates indexes on materialized view for query performance |

---

## 12. Database Migrations at Scale

**Q:** "You need to add a NOT NULL column with a default value to a 500M row production table. The application cannot have more than 1 second of downtime. Design the migration strategy."

**What They're Really Testing:** Whether you understand that schema changes on large tables require multi-phase strategies, not a single ALTER TABLE.

### Answer

**The Problem — ALTER TABLE on 500M Rows:**

```sql
-- Naive approach (DISASTER):
ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC';
-- PostgreSQL: Only metadata change (no row rewrite) since PostgreSQL 11+
-- BUT: Writes a new version of EVERY row to WAL (full_page_writes!)
-- Locks: AccessExclusive lock on table → ALL queries blocked
-- Time: ~30-60 minutes of complete downtime
```

**Zero-Downtime Strategy — Expand-Migrate-Contract:**

```yaml
Phase 1: EXPAND
  - Add the column as nullable (no default)
  - Application uses both old and new code paths
  - NO downtime, NO locks on reads/writes

Phase 2: MIGRATE
  - Backfill the default value in batches
  - Add NOT NULL constraint
  - Application fully switches to new column

Phase 3: CONTRACT
  - Drop the old column (if replacing)
  - Remove compatibility code from application
```

**Step-by-Step Implementation:**

```sql
-- ─────────────────────────────────────────────────
-- PHASE 1: EXPAND — Add column (non-blocking!)
-- ─────────────────────────────────────────────────

-- PostgreSQL 11+: ALTER TABLE ... ADD COLUMN with DEFAULT is
-- a metadata-only change for NON-NULL columns
-- But for NOT NULL with DEFAULT, PG must rewrite every row!

-- Safe approach: Add as nullable first
ALTER TABLE users ADD COLUMN timezone TEXT;
-- This is INSTANT (no row rewrite, just catalog change)
-- Takes: ~1ms
-- Lock: AccessExclusive, but held briefly

-- ─────────────────────────────────────────────────
-- PHASE 2a: Backfill — Fill in the default value
-- ─────────────────────────────────────────────────

-- Backfill in small batches (10,000 rows each)
-- Using a batched UPDATE to avoid long-running transactions

CREATE EXTENSION IF NOT EXISTS pg_batch;

DO $$
DECLARE
    batch_size CONSTANT INT := 10000;
    affected INT;
BEGIN
    LOOP
        WITH batch AS (
            SELECT ctid FROM users
            WHERE timezone IS NULL
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED  -- Don't block concurrent updates!
        )
        UPDATE users
        SET timezone = 'UTC'
        FROM batch
        WHERE users.ctid = batch.ctid;

        GET DIAGNOSTICS affected = ROW_COUNT;
        RAISE NOTICE 'Updated % rows', affected;

        COMMIT;  -- Commit each batch to release locks

        EXIT WHEN affected < batch_size;
    END LOOP;
END;
$$;

-- Alternative: Use pt-online-schema-change (Percona Toolkit):
-- pt-online-schema-change h=localhost,D=mydb,t=users \
--   --alter "ADD COLUMN timezone TEXT DEFAULT 'UTC'" \
--   --chunk-size=10000 --max-lag=1 --pause-file=/tmp/pause
-- Creates a shadow table, copies data incrementally via triggers

-- ─────────────────────────────────────────────────
-- PHASE 2b: Add NOT NULL constraint
-- ─────────────────────────────────────────────────

-- First: validate all rows have the value
-- If any NULLs remain, the constraint will fail!
-- Use NOT VALID to add the constraint without checking existing rows:

ALTER TABLE users ADD CONSTRAINT users_timezone_not_null
    CHECK (timezone IS NOT NULL) NOT VALID;
-- This is INSTANT — no row scan, just catalog change

-- Then VALIDATE in the background (takes ShareUpdateExclusive lock):
ALTER TABLE users VALIDATE CONSTRAINT users_timezone_not_null;
-- This SCANS the table, but doesn't block SELECT/INSERT/UPDATE!
-- Only blocks ALTER TABLE, VACUUM, etc.
-- If it finds violations: fails (but constraint remains for new rows)

-- ─────────────────────────────────────────────────
-- PHASE 3: CONTRACT — Clean up
-- ─────────────────────────────────────────────────

-- If replacing an old column:
-- 1. Stop all code from writing to old column
-- 2. Drop old column:
ALTER TABLE users DROP COLUMN old_timezone CASCADE;
-- 3. Remove compatibility code from application
```

**Online Schema Change Tools Comparison:**

```
Tool                    Approach                 Locking                    Speed
────                    ────────                 ───────                    ─────
pgroll (xata)           Create new table + view   Lock-free                  Fast
pt-online-schema-change Triggers + shadow table   Short metadata lock        Medium
gh-ost (GitHub)         Binlog-based + shadow     No triggers (MySQL only)   Fast
pg_batch                Batched UPDATE            Short row locks            Variable

For PostgreSQL:
  - pgroll: Best overall (no triggers, no locking)
  - pg_batch: Good for backfills
  - Manual expand-migrate-contract: Most control
```

**Common Pitfalls:**

```yaml
# Pitfall 1: Long-running migration transaction
#   Problem: Holds snapshot → blocks VACUUM → bloat
#   Fix: Commit every batch

# Pitfall 2: Lock wait timeouts
#   Problem: ALTER TABLE waits for other queries to finish
#   Fix: SET lock_timeout = '5s'; on migration session
#        Retry if timeout

# Pitfall 3: Application reads NULL before backfill completes
#   Problem: New column defaults to NULL, code doesn't handle it
#   Fix: Backfill BEFORE deploying code that uses the column
#        Or: Deploy code with NULL-safe reads first

# Pitfall 4: Adding UNIQUE constraint on large table
#   Problem: Requires full table scan + lock
#   Fix: CREATE UNIQUE INDEX CONCURRENTLY (non-blocking)
#        Then: ALTER TABLE ADD CONSTRAINT ... USING INDEX
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Expand-Migrate-Contract** | Explains the multi-phase strategy with concrete SQL |
| **NOT VALID + VALIDATE** | Knows how to add constraints without blocking writes |
| **Batch backfill** | Uses batched updates with SKIP LOCKED to avoid contention |
| **Tool awareness** | Mentions pgroll, pg_batch, or pt-online-schema-change |

---

## 13. Connection Pooling & PgBouncer Internals

**Q:** "A Django application with 200 web workers connects to PostgreSQL and keeps crashing with 'too many connections.' The sysadmin increased max_connections to 500 but now the database is slow. Design a connection pooling strategy."

**What They're Really Testing:** Whether you understand that more connections ≠ more throughput, and how PgBouncer's pooling modes change the equation.

### Answer

**The Problem — Connection Overload:**

```
Naive setup:
  200 Django workers × 2 connections each = 400 connections to PostgreSQL
  
  PostgreSQL max_connections = 500
  
  Each connection:
    - ~10MB shared memory (work_mem, sort_mem, etc.)
    - ~5MB backend process (postgres process)
    - ~2MB for buffers
    Total per connection: ~17MB
    
  400 connections × 17MB = 6.8GB just for connection overhead
  
  Worse: The PostgreSQL query scheduler (process-based) spends
  significant CPU context-switching between 400 processes
  
  Optimal: ~2× CPU cores = 32 connections for a 16-core machine
```

**PgBouncer Pooling Modes:**

```
Session Mode (default):
┌────────┐      ┌──────────┐      ┌──────────┐
│Worker 1│──────│PgBouncer │──────│PostgreSQL│
│conn=5  │      │  pool=10 │      │  conn=10 │← Connection held for entire session
└────────┘      └──────────┘      └──────────┘
  Worker 1 disconnects → PgBouncer keeps connection for next use
  Benefit: Quick reconnect for worker
  Downside: Idle connections still consume resources

Transaction Mode (recommended):
┌────────┐      ┌──────────┐      ┌──────────┐
│Worker 1│─TX1──│PgBouncer │──────│PostgreSQL│← Connection acquired
└────────┘      └──────────┘      └──────────┘
                    │              │ ← Connection RELEASED after COMMIT
┌────────┐      ┌──────────┐      ┌──────────┐
│Worker 2│─TX2──│PgBouncer │──────│PostgreSQL│← Different worker uses it
└────────┘      └──────────┘      └──────────┘
  Connections are shared ACROSS workers
  10 pool connections can serve 200 workers!
  Downside: SET statements, prepared statements, temp tables
            are LOST between transactions!

Statement Mode (rare):
  Connection released after each statement
  Even more sharing, but almost nothing survives between calls
  Prepared statements, session variables, cursors — all lost
```

**PgBouncer Configuration:**

```ini
# pgbouncer.ini
[databases]
mydb = host=localhost port=5432 dbname=mydb

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432

# Pool sizing:
pool_mode = transaction        # Best for web apps
default_pool_size = 32         # Total PostgreSQL connections
max_client_conn = 500          # Max clients PgBouncer will accept

# Queue management:
reserve_pool_size = 4          # Extra connections for when pool is full
reserve_pool_timeout = 2       # Seconds before using reserve pool
max_db_connections = 32        # Hard limit per database

# Timeouts:
server_idle_timeout = 300      # Close idle connections after 5min
client_idle_timeout = 600      # Drop idle clients after 10min
query_timeout = 30             # Kill queries running >30s

# Prepared statement handling:
pkt_buf = 8192                 # Increased for prepared statements
```

**Pool Sizing with Little's Law:**

```python
# Little's Law: L = λ × W
#   L = average number of connections in the pool (occupied)
#   λ = arrival rate (transactions/second)
#   W = average time a connection is held (seconds)

# Example: Django app serving 1000 req/s
request_rate = 1000         # 1000 requests/second
avg_query_time = 0.050      # 50ms per query
transactions_per_req = 3    # Each request does ~3 transactions

# Total transaction rate:
λ = request_rate * transactions_per_req  # 3000 tx/s

# Average connection hold time (per transaction):
W = avg_query_time  # 50ms = 0.05s

# Required connections (Little's Law):
L = λ × W = 3000 × 0.05 = 150 connections

# But PgBouncer in transaction mode reuses connections rapidly!
# Actual pool size can be smaller:
#   Each of 32 connections can handle ~20 tx/s
#   32 × (1/0.05) = 640 tx/s per connection group
#   Need: 3000 / 640 ≈ 5 connection groups → not quite right

# Better formula: pool = N_CPUs × (1 + wait_time / compute_time)
#   For database-bound: pool = N_CPUs × 2
#   For mixed: pool = N_CPUs × (1 + W/C)
#   Where W = I/O wait time, C = CPU time

# Safe starting point:
pool_size = N_CPUs * 2  # 32 for 16-core machine
# Monitor and adjust based on:
#   - avg_wait_time (pgbouncer stats)
#   - avg_query_time
#   - Connection utilization
```

**Monitoring PgBouncer:**

```sql
-- PgBouncer's SHOW commands (connect to pgbouncer admin console):
SHOW STATS;
--   total_xact_count: 1,234,567
--   total_query_count: 12,345,678
--   total_received: 8.2 GB
--   avg_xact_time: 0.045s  ← Average transaction duration
--   avg_query: 0.012s

SHOW POOLS;
--   cl_active: 32     (connections currently processing)
--   cl_waiting: 0     (clients waiting for a connection) ← Should be 0!
--   sv_active: 28     (server connections in use)
--   sv_idle: 4        (idle server connections)
--   sv_used: 0        (connections held for session-mode clients)
--   sv_tested: 0
--   sv_login: 0
--   maxwait: 0         (oldest client wait time in seconds) ← Should be 0!

-- If cl_waiting > 0: increase pool size or optimize queries
-- If maxwait > 0.1: pool is undersized for current load
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pooling modes** | Explains session vs transaction vs statement mode tradeoffs |
| **Little's Law** | Applies L = λW correctly to size the pool |
| **PgBouncer config** | Knows default_pool_size, reserve_pool, timeouts |
| **Limitations** | Knows transaction mode breaks SET statements, prepared stmts, temp tables |

---

## 14. Distributed SQL: CockroachDB vs Spanner

**Q:** "Your startup is building a global multi-tenant SaaS application. Data must be consistent across US, EU, and Asia regions. Compare CockroachDB and Google Spanner. How does each achieve global consistency without sacrificing availability?"

**What They're Really Testing:** Whether you understand the fundamental architectural differences between the two major distributed SQL databases — and the tradeoffs in consistency model, clock assumptions, and deployment.

### Answer

**Architecture Comparison:**

```
CockroachDB:                                    Spanner:
┌──────────────────────────────┐               ┌──────────────────────────────┐
| SQL Gateway                  |               | SQL Gateway (any node)      |
|   │                          |               |   │                          |
|   ▼                          |               |   ▼                          |
| Range 1 ── Raft ── Replica A |               | Split 1 ── Paxos ── Replica 1|
|          ├── Replica B       |               |          ├── Replica 2       |
|          └── Replica C       |               |          └── Replica 3       |
|                              |               |                              |
| CockroachDB uses:            |               | Spanner uses:                |
|   - HLC (Hybrid Logical Clock)              |   - TrueTime (GPS + atomic)   |
|   - Raft consensus          |               |   - Paxos consensus          |
|   - Range splits            |               |   - Split + directory        |
|   - Serializable by default |               |   - External consistency     |
└──────────────────────────────┘               └──────────────────────────────┘
```

**Clock Mechanisms — The Key Difference:**

```python
# Both databases need a way to order transactions across regions.
# The clock mechanism is THE critical architectural difference.

# CockroachDB: HLC (Hybrid Logical Clock)
#   = Wall clock + Logical counter
#   No special hardware needed!

class HLC:
    """
    Hybrid Logical Clock: combines physical time with a logical counter.
    """
    def __init__(self):
        self.physical = 0  # Wall clock (nanoseconds)
        self.logical = 0   # Logical counter (for same-timestamp events)

    def now(self) -> tuple[int, int]:
        """Return current HLC time."""
        current_wall = self.get_wall_clock()

        if current_wall > self.physical:
            # Wall clock advanced normally
            self.physical = current_wall
            self.logical = 0
        else:
            # Same or earlier wall time — advance logical counter
            self.logical += 1

        return (self.physical, self.logical)

    def update_from_remote(self, remote_physical: int, remote_logical: int):
        """Update HLC from a message received from another node."""
        current_wall = self.get_wall_clock()

        # Take the MAX of local wall, remote wall, and remote HLC
        self.physical = max(current_wall, remote_physical, self.physical)

        if self.physical == current_wall == remote_physical:
            # Same physical time — use max logical + 1
            self.logical = max(self.logical, remote_logical) + 1
        elif self.physical == remote_physical:
            # Remote physical is newer — take its logical + 1
            self.logical = remote_logical + 1
        else:
            # Local wall clock is newest
            self.logical = 0

# HLC gives us: if A happens-before B, then HLC(A) < HLC(B)
# BUT: clock skew between nodes can cause false conflicts
# Mitigation: CockroachDB uses "read refreshing" to handle clock uncertainty


# Google Spanner: TrueTime
#   = GPS + Atomic clocks in EVERY datacenter
#   Expresses time as an INTERVAL [earliest, latest]

class TrueTime:
    """
    TrueTime returns a time interval [tt_earliest, tt_latest].
    The REAL time is guaranteed to be within this interval.
    Clock uncertainty (ε) is typically 1-7ms.
    """
    def __init__(self):
        self.epsilon = 7  # ms of uncertainty

    def now(self) -> tuple[int, int]:
        """
        Returns (earliest, latest) — the real time is somewhere in between.
        """
        wall = self.get_gps_time()
        return (wall - self.epsilon, wall + self.epsilon)

    def after(self, timestamp: int) -> bool:
        """
        Is this timestamp definitively in the past?
        True if: timestamp < tt_earliest (the earliest possible now)
        """
        earliest, _ = self.now()
        return timestamp < earliest

    def commit_wait(self, timestamp: int):
        """
        Spanner waits until TrueTime.after(timestamp) returns True.
        This guarantees that the timestamp is IN THE PAST.
        Typically: wait ε (7ms) to ensure no future transaction
        assigns a conflicting timestamp.
        """
        while not self.after(timestamp):
            sleep(1)  # Wait 1ms and recheck

# TrueTime gives Spanner EXTERNAL CONSISTENCY:
#   Transaction A commits at T(A)
#   Transaction B starts after A commits
#   → T(A) < T(B) guaranteed!
```

**Consensus Protocols — Raft vs Paxos:**

```
Raft (CockroachDB):                             Paxos (Spanner):
───────────────                                 ───────────────
Simpler, more understandable                    More complex, battle-tested
Single leader per range (splits read/write)     Single proposer, multiple acceptors
Leader election: randomized timeout             Leader election: multi-phase
Writes: majority (N/2 + 1) of replicas          Writes: majority of voting members
Reads: from leaseholder (follower reads stale)  Reads: can be from any replica

Both provide:
  - Linearizable writes (committed = durable)
  - Automatic leader failover
  - Strong consistency within the replication group
```

**Range Splits and Data Distribution:**

```
CockroachDB:                                    Spanner:
────────────  
Initial: 1 range for the table                  Initial: 1 split for the table
Split threshold: 512MB or 64M rows              Split threshold: configurable
Split: range splits into 2 at midpoint          Split: split into 2 directories
Each range has its own Raft group               Each split has its own Paxos group
Leaseholder executes reads/writes               Leader executes reads/writes

Loading data into CockroachDB:
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    region STRING AS (substr(id::string, 1, 1)) STORED,
    PRIMARY KEY (region, id)
);
-- Use regional-by-row table to pin rows to specific regions:
ALTER TABLE users CONFIGURE ZONE USING
    constraints = '{"+region=us-east": 1, "+region=eu-west": 1, "+region=ap-southeast": 1}';
```

**Choosing Between Them:**

```yaml
Use CockroachDB when:
  - You need multi-region but can tolerate slightly higher latency
  - You want to self-host (Kubernetes, on-premise)
  - You need PostgreSQL compatibility (wire protocol)
  - Your budget can't support Spanner's pricing
  - Clock skew uncertainty is acceptable (HLC + read refreshing)

Use Spanner when:
  - You need TRUE external consistency (stronger than CockroachDB)
  - Budget is not a concern (Spanner is expensive)
  - You want Google to handle operations (fully managed)
  - You need the lowest possible commit wait times (TrueTime's 7ms ε)
  - Your workload benefits from interleaved tables (hierarchical storage)

Key differences in consistency:
  - Spanner: EXTERNAL consistency (TrueTime commit wait)
  - CockroachDB: SERIALIZABLE (but may have clock-skew edge cases)
  - In practice: both are "strongly consistent" for nearly all use cases
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **HLC vs TrueTime** | Understands the fundamental clock difference and its implications |
| **Raft vs Paxos** | Can compare consensus protocols and their practical tradeoffs |
| **Range splitting** | Knows how data is distributed and rebalanced across nodes |
| **Deployment** | Understands self-hosted (CockroachDB) vs managed (Spanner) implications |

---


