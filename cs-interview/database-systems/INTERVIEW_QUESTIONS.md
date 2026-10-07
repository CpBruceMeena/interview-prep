# 🗄️ Database Systems — Staff-Level Interview Questions

> *14 questions covering storage engines, MVCC, isolation, query plans, indexing, replication, sharding, locking, migrations, pooling and distributed SQL. Versions are current as of October 2026: PostgreSQL 18 (19 is in beta), MySQL 8.4 LTS and 9.7 LTS, PgBouncer 1.2x.*

Each answer leads with a **30-second answer**, then the mechanism, then trade-offs, failure modes and what the interviewer probes next.

---

## Table of Contents

1. [B-Tree vs LSM-Tree: Storage Engine Design](#1-b-tree-vs-lsm-tree-storage-engine-design)
2. [MVCC Internals: PostgreSQL vs MySQL (InnoDB)](#2-mvcc-internals-postgresql-vs-mysql-innodb)
3. [Transaction Isolation Levels & Anomalies](#3-transaction-isolation-levels-anomalies)
4. [Query Optimization & Execution Plans](#4-query-optimization-execution-plans)
5. [Indexing Strategies: B-Tree, Hash, GiST, GIN, BRIN](#5-indexing-strategies-b-tree-vs-hash-vs-gist-vs-gin-vs-brin)
6. [Replication: Synchronous vs Asynchronous, Quorum](#6-replication-synchronous-vs-asynchronous)
7. [Sharding Strategies & Distributed Query](#7-sharding-strategies)
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

**What They're Really Testing:** Whether you can reason about the read / write / space amplification trade-off (the "RUM conjecture"), and avoid the trap of thinking durability or ACID come from the index structure.

### Answer

!!! tip "30-second answer"
    A B-tree updates pages **in place**: cheap, predictable reads, but every small random write dirties a whole page. An LSM-tree **buffers writes in memory and flushes sorted immutable files**, then merges them in the background: sequential writes and high ingest, paid for with read amplification (several files per lookup) and compaction debt. Durability comes from the write-ahead log in *both* designs, so ACID doesn't decide the choice. A ledger usually gets a B-tree engine (Postgres/InnoDB) for predictable point reads and mature transactions. 10M points/s needs partitioning across many nodes regardless, with an LSM or columnar LSM-like engine (RocksDB, ClickHouse MergeTree) on each.

**How each one writes:**

| | B-Tree (InnoDB, Postgres indexes) | LSM-Tree (RocksDB, Cassandra, ScyllaDB) |
|---|---|---|
| Write path | WAL append, then modify the page in the buffer pool; page flushed later | WAL append, then insert into the memtable (skiplist); flushed as an SSTable |
| Point read | Root-to-leaf: ~3–4 page reads, upper levels almost always cached | Memtable, then every L0 file, then one file per level L1..Ln; Bloom filters skip most files |
| Range scan | Walk sibling-linked leaves | Merge iterators across memtable and all levels (Bloom filters don't help) |
| Write amplification | High for small random updates: change 100 bytes, eventually write an 8–16 KB page, plus a full-page image in the WAL after each checkpoint | Each byte is rewritten once per level it is compacted through: roughly 10–30× for leveled compaction, lower for tiered/universal |
| Space amplification | Pages ~50–70% full after random inserts, plus MVCC garbage | Leveled: ~1.1× (≈90% of data is in the last level). Tiered: up to 2× or more |
| Tail-latency risk | Page splits, checkpoint I/O spikes | **Write stalls** when compaction falls behind (too many L0 files or too many pending compaction bytes) |

**LSM structure (leveled compaction, RocksDB defaults):**

```
 writes ──► WAL (sequential append, fsync per commit or group)
        └─► MemTable (sorted skiplist, write_buffer_size = 64 MB)
                │ full → becomes immutable, flushed to disk
                ▼
 L0:  [SST a–z] [SST c–m] [SST b–x]     files may OVERLAP; a read checks each
                │ compaction once 4 L0 files exist (level0_file_num_compaction_trigger)
                ▼
 L1:  [a–f][g–m][n–s][t–z]              non-overlapping; one file per key range
                ▼  each level ~10× larger than the one above
 L2:  [a–b][c–d] ... [y–z]
                ▼
 Ln:  holds ~90% of the data
```

L0 is the only level whose files overlap, because each is a flushed memtable. From L1 down, each level is one sorted run split into files, so a point read touches at most one file per level.

**B-tree structure:** fan-out is in the hundreds (8 KB Postgres pages, 16 KB InnoDB pages), so four levels address billions of keys:

```
                  [ root: 100 | 500 ]
                 /         |         \
     [ 20 | 60 ]     [ 200 | 350 ]     [ 700 | 900 ]      internal pages
     /   |   \         /   |   \         /   |   \
   leaf leaf leaf    leaf leaf leaf    leaf leaf leaf     leaves hold (key → row / TID)
     ◄──►   ◄──►      ◄──►   ◄──►      ◄──►   ◄──►        siblings linked for range scans
```

**Which engine for each workload?**

*Workload A: ledger.* Writes are random by account, reads are point lookups and short ranges, and predictability matters more than peak ingest.

- A B-tree gives a bounded number of I/Os per lookup and no compaction debt that can stall writes at peak.
- Durability is the WAL plus `fsync` at commit (group commit amortises it). An LSM engine provides the same guarantee: MyRocks and CockroachDB's Pebble are transactional LSM engines, and TigerBeetle, a purpose-built ledger, uses an LSM. Say this out loud; it shows you know that ACID belongs to the transaction layer.
- The hard parts of a ledger are elsewhere: double-entry invariants, idempotency keys, serializable or row-locked balance updates, and synchronous replication for RPO=0 (see [Q6](#6-replication-synchronous-vs-asynchronous)).

*Workload B: 10M points/s.* No single engine of either type absorbs that on one node, so the first decision is **partitioning by (series, time)** across many nodes.

- Per node, an LSM (or a columnar engine with LSM-style merges) wins: writes are batched into memory and flushed sequentially, so the disk sees large sequential writes instead of random page updates.
- Reads are time-range aggregations. Bloom filters do **not** help range scans. What helps is time-partitioned files with min/max key metadata (so whole files are skipped), columnar layout with compression, and dropping whole partitions for retention instead of issuing deletes.
- Tombstones are an LSM failure mode: deletes are writes, and range scans slow down until compaction removes them. TTL or partition-drop retention avoids that.

**Related options to mention:**

```sql
-- PostgreSQL: a BRIN index on an append-only timestamp column stores min/max
-- per block range. It is orders of magnitude smaller than a B-tree, and only
-- useful while physical order tracks the column's value.
CREATE INDEX idx_metrics_time ON metrics USING brin (recorded_at)
    WITH (pages_per_range = 32);
```

```cpp
// RocksDB (C++): size memtables and level targets for leveled compaction.
rocksdb::Options options;
options.OptimizeLevelStyleCompaction(512 * 1024 * 1024);  // memtable memory budget
// Universal (tiered) compaction trades lower write amplification for higher space amplification:
// options.compaction_style = rocksdb::kCompactionStyleUniversal;
```

**Failure modes and what they probe next:**

- *"Why do LSM write stalls happen?"* Ingest exceeds compaction throughput: L0 files pile up (`level0_slowdown_writes_trigger` 20 / `level0_stop_writes_trigger` 36 by default) or pending compaction bytes exceed the soft or hard limit. The fix is more compaction threads, larger levels or tiered compaction. You can't throttle your way out of sustained overload.
- *"How do you cut LSM write amplification for large values?"* Key-value separation (WiscKey, RocksDB BlobDB): store large values in blob files so compaction moves only keys and pointers.
- *"Why are random UUID keys bad for a B-tree?"* Each insert lands on a random leaf: cache misses, page splits, and a full-page WAL image per page after each checkpoint. Time-ordered keys (UUIDv7, `uuidv7()` built into PostgreSQL 18) append at the right edge.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Amplification** | Names read, write and space amplification and where each comes from (page writes and FPIs vs compaction) |
| **Durability** | Separates durability (WAL + fsync) from the index structure |
| **LSM internals** | L0 overlap, Bloom filters (point reads only), compaction styles, write stalls, tombstones |
| **Scale realism** | Recognises 10M points/s as a partitioning problem first |

---

## 2. MVCC Internals: PostgreSQL vs MySQL (InnoDB)

**Q:** "Walk me through how PostgreSQL implements MVCC. How does it differ from MySQL InnoDB? What happens when you UPDATE a row that's actively being read by another transaction?"

**What They're Really Testing:** Whether you understand MVCC at the storage level: tuple headers, snapshots, visibility checks, and why the two designs have opposite garbage-collection problems.

### Answer

!!! tip "30-second answer"
    **PostgreSQL** keeps every row version in the heap. An UPDATE writes a new tuple and stamps the old one's `xmax`. Readers decide visibility by comparing `xmin`/`xmax` against their snapshot, and VACUUM later reclaims versions no snapshot can see. **InnoDB** updates the clustered-index record in place and writes the previous version to the **undo log**. A reader that needs an older version rebuilds it by walking the undo chain, and a purge thread discards undo nobody needs. Either way the reader is never blocked: it sees the version its snapshot allows. The cost shows up in different places. Postgres gets table and index bloat and needs VACUUM; InnoDB gets a growing undo history (history list length) and slower reads of old versions.

**Heap tuple header (PostgreSQL, `htup_details.h`, simplified):**

```c
typedef struct HeapTupleHeaderData {
    union {
        HeapTupleFields t_heap;   // t_xmin, t_xmax, t_cid (or t_xvac)
        DatumTupleFields t_datum; // used for in-memory composite values
    } t_choice;
    ItemPointerData t_ctid;       // (block, offset) of this tuple, or of the newer version
    uint16 t_infomask2;           // number of attributes + HOT flags
    uint16 t_infomask;            // hint bits: XMIN_COMMITTED, XMAX_INVALID, ...
    uint8  t_hoff;                // offset to user data
    bits8  t_bits[];              // null bitmap
} HeapTupleHeaderData;            // 23 bytes before the null bitmap
```

**What an UPDATE does (PostgreSQL):**

1. Lock the row by writing the updater's XID into the old tuple's `xmax`. Row locks live in the tuple header, not in a lock table.
2. Write a new tuple with `xmin = updater XID`, `xmax = 0`, on the same page if there is room.
3. Point the old tuple's `t_ctid` at the new one.
4. Indexes:
    - **HOT update**: if no indexed column changed and the new version fits on the same page, no index entries are written. Index scans follow the chain within the page. Since PostgreSQL 16, changing a column used only by BRIN (summarising) indexes still allows HOT.
    - **Non-HOT**: a new entry goes into **every** index on the table, not just indexes on changed columns. This is the write amplification Uber cited when it moved off Postgres in 2016.
5. Nothing is "dead" yet. The old version stays visible to any snapshot that started before the updater committed.

**Snapshot and visibility (READ COMMITTED vs REPEATABLE READ):**

A snapshot is `(xmin, xmax, xip[])`: every XID below `xmin` has finished, every XID at or above `xmax` hadn't started, and `xip[]` lists the ones in progress in between. A tuple version is visible when its `xmin` committed before the snapshot and its `xmax` is empty, aborted, or not yet committed as far as the snapshot can tell.

```
Row id=5: balance=1000, xmin=100 (committed), xmax=0

T_A: BEGIN ISOLATION LEVEL REPEATABLE READ;
T_A: SELECT balance ... id=5;      -- snapshot S_A = (xmin=240, xmax=240, xip=[])
                                    -- sees balance=1000

T_B (gets XID 240): UPDATE accounts SET balance = 900 WHERE id = 5; COMMIT;
    old version: xmin=100, xmax=240
    new version: xmin=240, xmax=0, balance=900

T_A: SELECT balance ... id=5;      -- reuses S_A
    old version: xmax=240 >= S_A.xmax  → treated as "not committed yet" → still visible
    new version: xmin=240 >= S_A.xmax  → invisible
    → 1000 (the same answer as before)

Had T_A been READ COMMITTED, the second SELECT would take a fresh snapshot
(xmin=241, xmax=241), see xmax=240 as committed, skip the old version and return 900.
```

**InnoDB:** the clustered (primary-key) index record holds the **current** value plus hidden `DB_TRX_ID` (last writer) and `DB_ROLL_PTR` (pointer to the undo record holding the previous version). A consistent read builds a *read view* and walks back through undo records until it reaches a version its read view can see. Secondary index records carry no version information, so InnoDB checks visibility through a page-level max-trx-id and, when in doubt, looks up the clustered record.

| Aspect | PostgreSQL | MySQL InnoDB |
|--------|-----------|--------------|
| Where old versions live | In the table heap, next to live rows | Undo log (undo tablespaces) |
| UPDATE | Writes a new tuple (out of place) | In place in the clustered index; previous version copied to undo |
| Reading an old version | Free: it is just another tuple | Costly: reconstructed by walking the undo chain |
| Garbage collection | VACUUM / autovacuum (heap and every index) | Purge threads |
| Long-running transaction hurts by... | Blocking VACUUM → table and index bloat | Growing history list length → bigger undo, slower reads |
| Secondary index on UPDATE | New entry in all indexes unless HOT | Only indexes whose columns changed (delete-mark old, insert new) |
| Row locks | In the tuple header (`xmax`); unlimited count | In the lock system (a bitmap per page); no escalation |

**VACUUM essentials:**

```sql
-- Autovacuum triggers a VACUUM when
--   dead tuples > autovacuum_vacuum_threshold (50)
--               + autovacuum_vacuum_scale_factor (0.2) × reltuples
-- 1M-row table → 200,050 dead tuples. A 1B-row table → 200M: far too late.
-- PostgreSQL 18 caps the threshold with autovacuum_vacuum_max_threshold (default 100M).
-- Since PostgreSQL 13, inserts alone also trigger vacuum
-- (autovacuum_vacuum_insert_threshold / _insert_scale_factor), so append-only tables get frozen.

-- Per-table tuning for a hot, large table:
ALTER TABLE accounts SET (
    autovacuum_vacuum_scale_factor = 0.01,  -- 1% instead of 20%
    autovacuum_vacuum_threshold    = 1000,
    autovacuum_vacuum_cost_limit   = 2000   -- let this table's vacuum do more I/O per cycle
);
```

**XID wraparound:** XIDs are 32-bit and compared modulo 2³¹, so a row whose `xmin` is more than ~2 billion transactions old would suddenly look like it's in the future. VACUUM **freezes** old tuples (sets a frozen hint bit) so their age no longer matters. Anti-wraparound (aggressive) autovacuum starts when a table's `relfrozenxid` age exceeds `autovacuum_freeze_max_age` (200M). At 1.6B (`vacuum_failsafe_age`, PostgreSQL 14+) vacuum drops its cost limits and skips index cleanup to finish fast. If it still falls behind, the server refuses to assign new XIDs (it stops accepting writes) until someone vacuums manually. The usual root causes are a long-running transaction, an abandoned replication slot, or an orphaned prepared transaction holding back the horizon.

**What they probe next:** "Why doesn't VACUUM shrink the file?" (It makes space reusable inside pages. Returning space to the OS needs `VACUUM FULL` or `pg_repack`.) "Why does an index-only scan still hit the heap?" (Pages not marked all-visible in the visibility map.) "What's the InnoDB equivalent of bloat?" (History list length growing behind a long transaction.)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage format** | Knows PG keeps old versions in the heap; InnoDB keeps the newest in place and older ones in undo |
| **Visibility rules** | Can compute what a READ COMMITTED vs REPEATABLE READ snapshot returns |
| **Vacuum** | Thresholds, freeze, wraparound, what holds the horizon back |
| **HOT updates** | Knows non-HOT updates write to *every* index, and how fillfactor helps HOT |

---

## 3. Transaction Isolation Levels & Anomalies

**Q:** "A user reports that a bank transfer between two accounts (A: $1000, B: $500) shows A debited $100 but B never received it. Another query shows both A and B with $1400 total. What isolation anomaly happened? Trace through each isolation level and explain which prevents this."

**What They're Really Testing:** Whether you can map a symptom to a named anomaly, know how *real* engines implement each level (they differ from the SQL standard and from each other), and pick a fix that works.

### Answer

!!! tip "30-second answer"
    First ask whether the $1400 total is **permanent** or **transient**. If it stays at $1400, it's a **lost update**: the transfer added $100 to B, then a concurrent transaction that read B's old value ($500) wrote it back. The classic culprit is an ORM saving the whole row. If a later read shows $1500, the report saw **read skew**: it read A after the transfer committed and B before. Lost updates happen under READ COMMITTED in both Postgres and MySQL, and **under MySQL's default REPEATABLE READ too**. PostgreSQL's REPEATABLE READ aborts the second writer instead. The robust fixes don't depend on the isolation level: an atomic `UPDATE ... SET balance = balance + 100`, `SELECT ... FOR UPDATE`, or a version check. Read skew goes away by reading both balances in one statement or one REPEATABLE READ snapshot.

**Lost update, traced:**

```
Initial: A = 1000, B = 500

T1 (transfer)                              T2 (edit B's profile via ORM)
BEGIN;                                     BEGIN;
                                           SELECT * FROM accounts WHERE id='B';  -- balance 500
UPDATE accounts SET balance = balance-100 WHERE id='A';
UPDATE accounts SET balance = balance+100 WHERE id='B';   -- B = 600
COMMIT;
                                           UPDATE accounts
                                              SET email='new@x.com', balance=500  -- ORM writes every column
                                            WHERE id='B';
                                           COMMIT;
Result: A = 900, B = 500, total = 1400 (T1's credit to B is lost)
```

What each engine does with T2's final UPDATE:

- **READ COMMITTED (PostgreSQL or MySQL):** T1 has committed, so the UPDATE runs against the latest row and overwrites it. The update is lost.
- **PostgreSQL REPEATABLE READ (snapshot isolation):** the row changed after T2's snapshot was taken, so the UPDATE fails with `ERROR: could not serialize access due to concurrent update` (SQLSTATE 40001). This is *first-updater-wins*. The application must retry the whole transaction.
- **MySQL InnoDB REPEATABLE READ (the default):** plain SELECTs read the snapshot, but UPDATE does a *current read* of the latest committed row and does **not** check whether it changed since the snapshot. The update is lost, just as under READ COMMITTED.
- **SERIALIZABLE:** in PostgreSQL (SSI), one transaction aborts with 40001. In MySQL, with autocommit off, plain SELECTs become `SELECT ... FOR SHARE`. Both transactions hold shared locks, both then want exclusive ones, and InnoDB's deadlock detector aborts one.

**Read skew, traced (READ COMMITTED report):**

```
Report: SELECT balance FROM accounts WHERE id='A';   -- 1000? or 900?
Transfer commits between the report's two statements
Report: SELECT balance FROM accounts WHERE id='B';   -- 600
If the first read ran before the transfer:  1000 + 600 = 1600
If the report read A after and B before:     900 + 500 = 1400
```

Each statement in READ COMMITTED gets a new snapshot. A single statement `SELECT sum(balance) ...`, or both reads in one REPEATABLE READ transaction, always sees 1500.

**Write skew** is the anomaly snapshot isolation does *not* stop. Two on-call doctors each check "is someone else on call?" (yes), and each removes themselves. Neither write touches the other's row, so no write-write conflict exists. Only SERIALIZABLE (PostgreSQL SSI, MySQL lock-based) or explicit locking of the rows you *read* (`SELECT ... FOR UPDATE`) prevents it.

**What each level actually prevents (PostgreSQL 18, MySQL 8.4/9.7 InnoDB):**

| Anomaly | PG READ COMMITTED | PG REPEATABLE READ | PG SERIALIZABLE | MySQL READ COMMITTED | MySQL REPEATABLE READ | MySQL SERIALIZABLE |
|---|---|---|---|---|---|---|
| Dirty read | No | No | No | No | No | No |
| Non-repeatable / read skew | Possible | No | No | Possible | No (consistent reads) | No |
| Phantom (re-run SELECT) | Possible | No (snapshot) | No | Possible | No for plain SELECT; locking reads see new rows, and next-key locks block inserts into ranges they lock | No |
| Lost update (read, then write) | Possible | **No** (40001 error) | No | Possible | **Possible** | No (via deadlock abort) |
| Write skew | Possible | Possible | No | Possible | Possible | No |

PostgreSQL accepts READ UNCOMMITTED but runs it as READ COMMITTED, and its REPEATABLE READ is stricter than the SQL standard requires (no phantoms). PostgreSQL's SERIALIZABLE uses **SSI**: it tracks read/write dependencies with non-blocking SIREAD "locks" and aborts a transaction when it detects a dangerous structure (two consecutive rw-antidependencies). False positives happen, so every SERIALIZABLE caller needs a retry loop. Read-only reporting transactions can use `SERIALIZABLE READ ONLY DEFERRABLE` to wait for a safe snapshot and then run without any abort risk.

**Fixes, best first:**

```sql
-- 1. Atomic update: no read-modify-write window at any isolation level
UPDATE accounts SET balance = balance - 100 WHERE id = 'A' AND balance >= 100;
-- check rows affected = 1, otherwise insufficient funds

-- 2. Pessimistic: lock the rows you read. Lock in a fixed order to avoid deadlocks.
BEGIN;
SELECT id, balance FROM accounts WHERE id IN ('A', 'B') ORDER BY id FOR UPDATE;
-- ... compute ...
UPDATE accounts SET balance = 900 WHERE id = 'A';
UPDATE accounts SET balance = 600 WHERE id = 'B';
COMMIT;

-- 3. Optimistic: version column, retry when 0 rows are affected
UPDATE accounts
   SET balance = 600, version = version + 1
 WHERE id = 'B' AND version = 7;

-- 4. ORM hygiene: update only dirty columns (e.g. Django save(update_fields=[...]))
```

**What they probe next:** "Which level do you run by default?" READ COMMITTED with atomic updates and targeted `FOR UPDATE` is the common choice. Use SERIALIZABLE where invariants span rows and you can afford retries. "How do you retry safely?" Retry the whole transaction on SQLSTATE `40001` and `40P01` with jittered backoff, and keep side effects (emails, payment calls) outside the transaction or behind idempotency keys.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Anomaly identification** | Distinguishes lost update (permanent) from read skew (transient) and write skew |
| **Engine reality** | Knows MySQL REPEATABLE READ allows lost updates while PG REPEATABLE READ aborts |
| **SSI** | Explains rw-dependency tracking, false positives, retries, `DEFERRABLE` |
| **Fix** | Atomic UPDATE first, then FOR UPDATE / versioning, with retry handling |

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

**What They're Really Testing:** Whether you read a plan from the bottom up, compare estimated with actual rows, and know what indexes can and cannot fix. Aggregating millions of rows is never a 5 ms query.

### Answer

!!! tip "30-second answer"
    Run `EXPLAIN (ANALYZE, BUFFERS)` and read it bottom-up. Three observations: (1) the `WHERE` on `o.*` discards the NULL rows the LEFT JOIN would add, so it's really an inner join. The planner already knows this (outer-join reduction), so write `JOIN` to say what you mean. (2) The real cost is joining and aggregating ~6M qualifying orders; the `LIMIT 50` can't stop early because it sits above a sort over all groups. (3) An index can only cut I/O: a partial covering index on orders feeds the aggregate without heap visits, and aggregating orders *before* the join shrinks the join input. That gets you from tens of seconds to roughly a second. For dashboard latency you precompute (a rollup table or materialized view, [Q11](#11-materialized-views-indexed-views)).

**Reading the plan (illustrative numbers, read bottom-up):**

```
Limit  (actual time=28746..28746 rows=50)
  ->  Sort  (actual rows=50)                       Sort Method: top-N heapsort  Memory: 32kB
        Sort Key: (sum(o.amount)) DESC
        ->  HashAggregate  (rows=12000 vs actual 45000)
              Group Key: u.id
              Filter: (count(o.id) > 5)             Rows Removed by Filter: 455000
              Batches: 5  Memory Usage: 65585kB  Disk Usage: 412000kB    ← spilled to disk
              ->  Hash Join  (actual rows=6000000)
                    Hash Cond: (o.user_id = u.id)
                    ->  Seq Scan on orders o  (actual rows=6000000)
                          Filter: (status = ANY ('{completed,shipped}') AND created_at >= '2024-01-01')
                          Rows Removed by Filter: 4000000
                    ->  Hash  (actual rows=1000000)  Buckets: 131072  Batches: 16   ← spilled
                          ->  Seq Scan on users u  (actual rows=1000000)
                                Filter: (created_at >= '2024-01-01')
                                Rows Removed by Filter: 9000000
Execution Time: 28746 ms
```

What to say about it:

- **Both scans are sequential, which is correct here.** 60% of orders qualify, and an index scan over 60% of a table is slower than a seq scan. Don't promise to "add an index on status".
- **`Batches: 16` and `Disk Usage`** mean the hash table and the aggregate spilled because `work_mem` (× `hash_mem_multiplier`, default 2.0) was too small. Raise `work_mem` for this session or role; the setting is per operation, so don't raise it globally.
- **Estimated vs actual groups (12K vs 45K)** suggests stale or insufficient statistics. Check `pg_stat_user_tables.last_autoanalyze` and consider extended statistics on correlated columns.
- **`top-N heapsort`** confirms the LIMIT is applied in the sort, but only after every group has been built.

**Optimizations:**

```sql
-- 1. Aggregate orders first, then join only the surviving users.
--    PostgreSQL 18 never pushes GROUP BY below a join on its own. PostgreSQL 19
--    (in beta) adds "eager aggregation", which can do this automatically.
SELECT u.name, o.order_count, o.total_spent
FROM (
    SELECT user_id, count(*) AS order_count, sum(amount) AS total_spent
    FROM orders
    WHERE status IN ('completed', 'shipped')
      AND created_at >= '2024-01-01'
    GROUP BY user_id
    HAVING count(*) > 5
) o
JOIN users u ON u.id = o.user_id
WHERE u.created_at >= '2024-01-01'
ORDER BY o.total_spent DESC
LIMIT 50;

-- 2. A partial covering index lets the aggregate read user_id order straight from the
--    index (Index Only Scan → GroupAggregate, no sort, no hash spill).
--    The query's WHERE must imply the index predicate for the planner to use it.
CREATE INDEX CONCURRENTLY idx_orders_paid_2024
    ON orders (user_id) INCLUDE (amount)
    WHERE status IN ('completed', 'shipped') AND created_at >= '2024-01-01';

-- 3. Give this query enough memory, and let it go parallel.
SET work_mem = '256MB';                       -- session-level, for the reporting role
SET max_parallel_workers_per_gather = 4;

-- 4. Keep statistics honest.
ANALYZE orders;
```

Expected result: the index-only scan still reads ~6M index tuples, so the query takes on the order of a second (less with parallel workers). An index-only scan is only "index-only" for pages marked all-visible, so check `Heap Fetches:` in the plan and make sure the table is vacuumed.

**When it must be milliseconds:** precompute.

```sql
CREATE MATERIALIZED VIEW user_order_summary AS
SELECT o.user_id, u.name, count(*) AS order_count, sum(o.amount) AS total_spent
FROM orders o JOIN users u ON u.id = o.user_id
WHERE o.status IN ('completed', 'shipped')
  AND o.created_at >= '2024-01-01' AND u.created_at >= '2024-01-01'
GROUP BY o.user_id, u.name;

CREATE UNIQUE INDEX ON user_order_summary (user_id);           -- needed for CONCURRENTLY
CREATE INDEX ON user_order_summary (total_spent DESC) WHERE order_count > 5;

REFRESH MATERIALIZED VIEW CONCURRENTLY user_order_summary;    -- readers aren't blocked
```

**Myths to avoid in the interview:**

- *"Rewrite it as CTEs to force materialization."* Since PostgreSQL 12, a non-recursive CTE referenced once is inlined. `AS MATERIALIZED` blocks predicate pushdown and usually hurts.
- *"Change LEFT to INNER JOIN for speed."* The planner already did it. The change is for readability.
- *"Merge join is faster than hash join."* Neither is faster in general. A merge join needs sorted input; it wins when an index already provides that order.

**What they probe next:** how to see a plan for a parameterised query (`EXPLAIN (GENERIC_PLAN)` since PG16, `auto_explain`), custom vs generic plans for prepared statements (`plan_cache_mode`), and why `rows=` estimates are off (stale stats, correlated predicates, functions of columns).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Plan reading** | Bottom-up; compares estimated vs actual rows; spots spills (`Batches`, `Disk Usage`) |
| **Realism** | Knows seq scans are right at 60% selectivity and that aggregating 6M rows has a floor |
| **Rewrites** | Aggregate-before-join, partial covering index, no CTE-fence myths |
| **Precomputation** | Matview or rollup when latency must be milliseconds |

---

## 5. Indexing Strategies: B-Tree vs Hash vs GiST vs GIN vs BRIN

**Q:** "You have a PostgreSQL table with 100M rows containing the following query patterns: (A) exact-match lookups on user_id, (B) full-text search on document_body, (C) range queries on created_at, (D) JSONB queries on metadata, (E) geospatial queries on a location column. Choose the optimal index type for each."

**What They're Really Testing:** Whether you understand what each access method stores and which operators it supports, not just their names.

### Answer

!!! tip "30-second answer"
    (A) B-tree: it handles equality, ranges, ordering and uniqueness. Hash indexes are equality-only and rarely worth it. (B) GIN on a `tsvector`: an inverted index from lexeme to row IDs. (C) B-tree if rows arrive in random time order or you need `ORDER BY ... LIMIT`; BRIN if the table is append-only, so physical order follows `created_at`. (D) GIN on the `jsonb`: `jsonb_path_ops` (smaller, `@>` and jsonpath only) or the default `jsonb_ops` (also key existence `?`, `?|`, `?&`). For one hot key, a B-tree expression index on `(metadata->>'role')` is better. (E) GiST from PostGIS on a `geography`/`geometry` column, queried with `ST_DWithin`.

```sql
-- (A) B-tree: =, <, >, BETWEEN, IN, ORDER BY, UNIQUE; leaf pages hold (key, heap TID)
CREATE INDEX idx_docs_user ON documents (user_id);

-- (B) Full-text: GIN over a stored tsvector (PostgreSQL 18 also has VIRTUAL generated columns,
--     but those can't be indexed, so use STORED here)
ALTER TABLE documents
    ADD COLUMN body_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', document_body)) STORED;
CREATE INDEX idx_docs_fts ON documents USING gin (body_tsv);
SELECT id FROM documents WHERE body_tsv @@ websearch_to_tsquery('english', 'postgres indexing');

-- (C) BRIN when physical order tracks time (append-only); B-tree otherwise
CREATE INDEX idx_docs_created_brin ON documents USING brin (created_at);   -- 128 pages/range by default
CREATE INDEX idx_docs_created_btree ON documents (created_at);             -- random arrival, ORDER BY

-- (D) JSONB containment
CREATE INDEX idx_docs_meta ON documents USING gin (metadata jsonb_path_ops);
SELECT id FROM documents WHERE metadata @> '{"role": "admin"}';
--     A frequently filtered scalar is better served by an expression B-tree:
CREATE INDEX idx_docs_role ON documents ((metadata->>'role'));

-- (E) Geospatial (PostGIS): GiST over geography, radius in metres
CREATE INDEX idx_venues_geo ON venues USING gist (location);   -- location geography(Point, 4326)
SELECT id FROM venues
WHERE ST_DWithin(location, ST_MakePoint(-74.0060, 40.7128)::geography, 5000);  -- lon, lat
```

| Index | Structure | Supports | Size / write cost | Pick it when |
|---|---|---|---|---|
| **B-tree** | Balanced tree, sorted keys, linked leaves | `= < > BETWEEN IN`, `ORDER BY`, UNIQUE, `LIKE 'abc%'` (with `text_pattern_ops` or C collation) | Moderate; deduplication (PG13+) shrinks repeated keys | Default for almost everything |
| **Hash** | Hash buckets of TIDs (WAL-logged since PG10) | `=` only | Similar to B-tree; no uniqueness, no multi-column | Very long keys used only for equality (rare) |
| **GIN** | Inverted index: key → posting list/tree of TIDs | `@@`, `@>`, `?`, array `&&`, `pg_trgm` `LIKE '%x%'` | Large and slow to update; `fastupdate` pending list batches inserts but makes reads scan the list | Many keys per row: words, tags, JSON keys |
| **GiST** | Balanced tree of bounding predicates (R-tree-like) | Geometry, ranges (`&&`, `@>`), nearest-neighbour `<->`, exclusion constraints | Moderate; lossy, rows rechecked | Spatial, ranges, "no overlapping bookings" |
| **SP-GiST** | Space-partitioned trees (quad-tree, k-d tree, radix) | Points, `inet`, text prefixes | Small for suitable data | Non-overlapping partitions of space |
| **BRIN** | Min/max (or bloom / minmax-multi) per block range | Ranges on physically ordered data | Tiny, near-zero write cost | Huge append-only tables |

**Details that separate a staff answer:**

- **Composite B-tree column order:** equality columns first, then the range or sort column. `(tenant_id, created_at)` serves `WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20` without a sort. PostgreSQL 18 adds **skip scan**, so `(tenant_id, created_at)` can also serve `WHERE created_at > ?` alone when `tenant_id` has few distinct values. It's no substitute for the right index on a hot path.
- **Partial indexes** (`WHERE status = 'pending'`) index a hot subset. **Covering indexes** (`INCLUDE (amount)`) enable index-only scans, which depend on the visibility map.
- **GIN write cost:** each row can add dozens of keys. With `fastupdate` (on by default), new entries go into a pending list that is merged in bulk when it exceeds `gin_pending_list_limit` (4 MB) or during VACUUM. Writes get cheaper; searches scan the pending list too, and the merge causes latency spikes.
- **BRIN** is useless on randomly ordered data: every range's min/max covers everything. `minmax_multi_ops` (PG14+) tolerates a few outliers; `bloom_ops` handles equality on unordered data.
- **Every index slows every write** (unless HOT) and adds WAL. Find unused ones with `pg_stat_user_indexes.idx_scan` / `last_idx_scan` (PG16+), checked on replicas too, before dropping.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Internal structure** | B-tree sorted leaves, GIN inverted lists, GiST bounding predicates, BRIN block-range summaries |
| **Operator support** | Knows `jsonb_path_ops` lacks `?`; hash is `=` only; BRIN needs physical correlation |
| **Write overhead** | GIN pending list, non-HOT updates touching every index |
| **Composite design** | Equality-then-range ordering, partial/covering indexes, PG18 skip scan |

---

## 6. Replication: Synchronous vs Asynchronous

**Q:** "Design the replication strategy for a global payment database. The compliance team requires zero data loss (RPO=0), but the business demands sub-50ms write latency. Show the quorum configurations and failure scenarios."

**What They're Really Testing:** Whether you treat the speed of light as a constraint, know exactly what "acknowledged" means for each `synchronous_commit` level, and can walk through failover without split-brain or silent data loss.

### Answer

!!! tip "30-second answer"
    RPO=0 means a commit isn't acknowledged until a copy is durable in a **second failure domain**, so commit latency is at least one round trip to that domain. Cross-continent round trips are 60–150 ms, so RPO=0 *for a whole-region loss* and sub-50 ms commits conflict unless the second region is close (paired regions ~10–20 ms apart). The usual design: a primary with **quorum-synchronous standbys in other availability zones of the same region** (adds ~1–2 ms; RPO=0 for zone or host loss), plus **async standbys in a distant region** for disaster recovery with an RPO of seconds. Then negotiate explicitly: "RPO=0 for zone failure, RPO ≤ 5 s for region failure", or pay the latency.

**Physics first (typical round-trip times):**

| Link | RTT |
|---|---|
| Same AZ | < 0.5 ms |
| AZ to AZ, same region | ~1–2 ms |
| Nearby paired regions (e.g. Virginia ↔ Ohio) | ~10–20 ms |
| US East ↔ US West | ~60–70 ms |
| US East ↔ Western Europe | ~70–90 ms |

**PostgreSQL configuration:**

```ini
# On the primary (us-east-1a)
synchronous_commit = on        # wait until a standby has flushed the WAL to disk
synchronous_standby_names = 'ANY 1 (pg_1b, pg_1c)'   # quorum: either AZ-b or AZ-c
# pg_dr_west (us-west-2) is not listed, so it is asynchronous
```

| `synchronous_commit` | Commit returns after | Survives |
|---|---|---|
| `off` | WAL in memory (flushed within ~3 × `wal_writer_delay`) | Nothing guaranteed; a crash loses the last ~600 ms of commits (no corruption) |
| `local` | Local WAL fsync | Primary process crash |
| `remote_write` | Standby received it and wrote it to its OS | Standby *Postgres* crash, not standby OS crash |
| `on` (with sync standbys) | Standby fsynced the WAL | Loss of the primary host or AZ → **RPO=0** |
| `remote_apply` | Standby replayed it | Same as `on`, plus read-your-writes on that standby |

`synchronous_commit` can be set per transaction: use `on` for payments and `local` for analytics events.

**Failure scenarios:**

| Event | What happens | Notes |
|---|---|---|
| One sync standby dies | `ANY 1 (b, c)` keeps committing via the other | With `FIRST 1` or a single standby, **commits block**: Postgres never silently falls back to async |
| Both sync standbys die | Commits hang | Patroni `synchronous_mode` may drop to async to restore availability; `synchronous_mode_strict` refuses (keeps RPO=0, loses availability) |
| Primary host / AZ dies | Patroni promotes a standby **that was synchronous**, so no acknowledged commit is lost | The old primary must be fenced: it loses the DCS leader key and demotes itself, ideally backed by a watchdog |
| Primary partitioned from the DCS | It can't renew the leader lock, demotes itself; clients get errors | This is the price of avoiding split-brain |
| Whole region lost | Promote `pg_dr_west`; lose up to the async lag | Monitor `pg_stat_replication.replay_lag` and alert on it as an RPO metric |

**A failure mode most candidates miss:** a commit waiting for a sync ack is *already committed locally*. If the client cancels or the session is terminated during the wait, Postgres emits `WARNING: canceling wait for synchronous replication` and the transaction stays committed and visible on the primary without being replicated. Applications should treat a lost connection during commit as "unknown outcome" and reconcile using idempotency keys.

**If RPO=0 across regions is non-negotiable:**

- Pick regions close enough for the budget (sync between paired regions ~10–20 ms apart, async to a far one).
- Or use a consensus-replicated store (Spanner, CockroachDB, YugabyteDB) with replicas placed so that a majority is reachable within the latency budget. Every write still pays a majority round trip.
- Aurora's model is related: each write goes to 6 storage copies across 3 AZs and needs a 4-of-6 quorum. That survives an AZ loss with RPO=0 inside one region; cross-region Global Database is asynchronous.

**What they probe next:** reads from replicas (staleness and read-your-writes), how failover clients find the new primary (`target_session_attrs=read-write` in libpq, a DNS or proxy layer), and how to test failover (scheduled game days, `patronictl switchover`).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Physics** | Quantifies RTTs and calls out the RPO vs latency conflict instead of hand-waving it |
| **Commit semantics** | Knows what each `synchronous_commit` level waits for |
| **Failover** | Promotes only a synchronous standby, fences the old primary, handles blocked commits |
| **Edge cases** | Cancelled sync waits, async DR lag as a measured RPO |

---

## 7. Sharding Strategies

**Q:** "Design a sharding strategy for a social media platform with 500M users. Compare range-based, hash-based, and directory-based sharding. How do you handle cross-shard queries and resharding?"

**What They're Really Testing:** Shard-key choice, the shape of cross-shard access, and whether you can move data without downtime or double writes.

### Answer

!!! tip "30-second answer"
    Shard user-owned data by `user_id`. Hash it into a fixed, large number of **logical shards** (say 4096), and map logical shards to physical clusters with a small **directory** (a versioned mapping table). Hashing spreads load; the directory lets you move one logical shard at a time without rehashing everything. Design so the hot paths (profile, own posts, own timeline) stay on one shard. Serve the inherently cross-user paths (follower graph, search, feeds) with denormalised, separately sharded structures, not scatter-gather. Reshard by copying a logical shard (snapshot + change capture), briefly freezing writes to that one shard, flipping the directory entry and cleaning up.

| Strategy | How a key is routed | Strengths | Weaknesses |
|---|---|---|---|
| **Range** | Key ranges → shards (`user_id 0–10M → S1`) | Efficient range scans; easy to split a range | Hot spots for monotonic keys (all new users hit the last shard); needs rebalancing |
| **Hash** | `hash(key) mod N` | Even load | Range scans fan out; changing N moves almost every key (unless consistent hashing or fixed logical shards) |
| **Directory** | Lookup table key → shard | Any placement, per-tenant moves, isolate whales | The lookup must be cached and highly available; one more moving part |
| **Hash + logical shards + directory** (recommended) | `hash(user_id) mod 4096` → directory → cluster | Even load, cheap moves of one logical shard, a small directory (4096 rows) | Must pick the logical shard count up front; choose it generously |

```
user_id ──hash──► logical shard 0..4095 ──directory (cached, versioned)──► physical cluster
                                               e.g. 0–63 → pg-01, 64–127 → pg-02, ...
```

**Designing the data around the shard key:**

- Co-locate everything owned by a user (profile, posts, settings) under `user_id`, and include it in every primary key so lookups route to a single shard.
- **Global uniqueness** (username, email): a separate lookup table sharded by `username` → `user_id`, written in the signup flow (outbox or saga, not a distributed transaction).
- **Social graph:** store edges twice, `following` sharded by follower and `followers` sharded by followee, so both directions are single-shard reads.
- **Home timeline:** fan-out-on-write into each follower's timeline (sharded by follower) for normal users; fan-out-on-read for celebrities with millions of followers, merged at read time.
- **IDs:** time-ordered and globally unique without coordination (Snowflake-style IDs embedding a shard or worker ID, or UUIDv7).

**Cross-shard queries:** scatter-gather is acceptable for rare admin or analytics paths, with per-shard timeouts and partial-result handling. Analytics belongs in a warehouse fed by CDC. Cross-shard *writes* are avoided by design; where unavoidable, use sagas with compensations, or 2PC only if the database supports it and you accept blocking on coordinator failure.

**Resharding a logical shard (no double-writes from the application):**

1. Copy the shard's rows to the target cluster from a consistent snapshot (logical replication with a row filter or publication per shard, or Vitess / Citus tooling).
2. Stream changes (CDC) until the target is caught up and lag is near zero.
3. Freeze writes for that **one** logical shard (seconds): reject or queue them at the router.
4. Wait for lag = 0, verify row counts or checksums, then bump the directory entry (`shard 17 → pg-09`, version + 1).
5. Unfreeze; routers pick up the new version (push invalidation, or reject stale-version requests at the old shard).
6. Keep the old copy read-only for a while as a rollback path, then delete it.

**Off-the-shelf:** Vitess (MySQL), Citus (PostgreSQL, including schema-based sharding), and distributed SQL (Spanner, CockroachDB, YugabyteDB, Aurora Limitless) automate placement and moves at the cost of their own constraints.

**What they probe next:** hot shards (one viral user; split the hot logical shard or isolate the tenant), uneven growth (move logical shards, don't rehash), and backups and schema migrations across thousands of shards (run them as a fleet with orchestration, idempotency and canaries).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Shard key** | Chooses one that keeps hot paths single-shard; designs side indexes for the rest |
| **Placement** | Logical shards plus a directory; explains why plain `mod N` breaks on resize |
| **Resharding** | Snapshot + CDC + short per-shard freeze + versioned directory flip |
| **Cross-shard** | Avoids distributed writes; uses denormalisation, sagas, CDC to analytics |

---

## 8. PostgreSQL Buffer Pool & WAL Internals

**Q:** "A query that was running in 50ms suddenly takes 5 seconds. You check `pg_stat_bgwriter` and see `buffers_backend_fsync` is high and `checkpoints_timed` is low. Walk through how PostgreSQL's buffer pool eviction works, how WAL interacts with checkpoints, and what's causing the slowdown."

!!! note "Version note"
    The counters in the question are from PostgreSQL ≤ 16. Since **PostgreSQL 17**, checkpoint counters live in `pg_stat_checkpointer` (`num_timed`, `num_requested`, `buffers_written`), and backend writes and fsyncs are in `pg_stat_io`. `pg_stat_bgwriter` keeps only `buffers_clean`, `maxwritten_clean` and `buffers_alloc`.

**What They're Really Testing:** Whether you understand how shared buffers, WAL and checkpoints interact, and can turn counters into a root cause.

### Answer

!!! tip "30-second answer"
    Few timed checkpoints means most checkpoints are **requested**: WAL hits `max_wal_size` before `checkpoint_timeout`. Frequent checkpoints hurt twice. After every checkpoint, the first change to each page writes a **full-page image** to WAL, so WAL volume and I/O balloon. And the checkpointer and background writer can't keep enough clean buffers, so **backends evict dirty pages themselves**. When the checkpointer's fsync request queue overflows, a backend even has to `fsync` itself; that's what high `buffers_backend_fsync` means. Queries stall on I/O they shouldn't be doing. Fix: raise `max_wal_size` (and `checkpoint_timeout`) so checkpoints are timed and spread out, enable `wal_compression`, tune the bgwriter, and check what started generating more WAL.

**Shared buffers and clock-sweep eviction:**

- `shared_buffers` (default 128 MB; commonly ~25% of RAM) is an array of 8 KB buffers with descriptors (tag, pin count, usage count, dirty flag). A hash table maps `(relation, fork, block)` to a buffer, partitioned and protected by `BufferMapping` LWLocks.
- **Clock sweep, not LRU:** every access bumps the buffer's `usage_count` (capped at 5) with an atomic compare-and-swap, so a hit takes no global lock. To find a victim, a shared "clock hand" moves round the array decrementing usage counts. The first unpinned buffer at 0 is evicted. LRU would need a global list update on every hit, a contention point at high concurrency.
- **Ring buffers protect the cache:** large sequential scans (tables bigger than ¼ of `shared_buffers`), `VACUUM` and bulk writes (`COPY`, `CREATE TABLE AS`) cycle through a small private ring (256 KB for scans; `vacuum_buffer_usage_limit` defaults to 2 MB since PG17; 16 MB for bulk writes) instead of flushing the whole pool. A big seq scan doesn't evict the OLTP working set.
- **Evicting a dirty buffer:** the WAL up to that page's LSN must be flushed first (the WAL rule), then the page is written. When a client backend does this itself, it's a backend write: latency your query pays.

```python
class ClockSweep:
    """Simplified PostgreSQL buffer replacement (src/backend/storage/buffer/freelist.c)."""
    MAX_USAGE = 5  # BM_MAX_USAGE_COUNT

    def __init__(self, n: int):
        self.usage = [0] * n
        self.pins = [0] * n
        self.dirty = [False] * n
        self.hand = 0   # nextVictimBuffer: advanced with an atomic fetch-add in the real code

    def on_access(self, i: int) -> None:
        # Real code: compare-and-swap on the buffer's state word, no global lock.
        self.usage[i] = min(self.MAX_USAGE, self.usage[i] + 1)

    def find_victim(self) -> int:
        tries = len(self.usage) * (self.MAX_USAGE + 1)
        while tries:
            i = self.hand
            self.hand = (self.hand + 1) % len(self.usage)
            if self.pins[i] == 0:
                if self.usage[i] == 0:
                    return i   # caller writes it out first if dirty (after flushing WAL to the page LSN)
                self.usage[i] -= 1   # second chance
            tries -= 1
        raise RuntimeError("no unpinned buffers available")
```

**WAL mechanics:**

- Every change is described by a WAL record. The page is modified in shared memory and stamped with the record's LSN (a 64-bit byte position in the WAL stream). The data page can be written later, but never before its WAL is durable.
- **Insertion is concurrent:** a backend reserves space under a short spinlock, then copies its record into the WAL buffers holding one of 8 WAL-insertion locks. Flushing is serialised by `WALWriteLock`, and **group commit** lets one `fsync` cover every commit waiting behind it.
- Commit = append a commit record, then flush WAL up to it (`wal_sync_method` defaults to `fdatasync` on Linux). Data pages are *not* written at commit.
- **Full-page writes:** the first modification of a page after a checkpoint logs the whole 8 KB page, so recovery can repair a torn (partially written) page. Right after each checkpoint, WAL volume spikes.

**Checkpoint, in order:**

1. Note the **redo point** (current WAL insert position) at the *start*.
2. Write all buffers that were dirty at that moment, spread over `checkpoint_completion_target` (0.9 by default since PG14) of the interval to avoid I/O bursts.
3. `fsync` the data files.
4. Write the checkpoint record and update `pg_control`. Crash recovery will start replaying from the redo point.
5. Remove or recycle WAL segments older than the redo point (subject to slots, `wal_keep_size` and archiving).

**Diagnosis on PostgreSQL 17/18:**

```sql
-- Timed vs requested checkpoints. Mostly requested → max_wal_size is too small for the write rate
SELECT num_timed, num_requested, num_done, write_time, sync_time, buffers_written
FROM pg_stat_checkpointer;

-- Who is writing dirty buffers? Client backends writing or fsyncing → bad
SELECT backend_type, context, writes, fsyncs, evictions
FROM pg_stat_io
WHERE object = 'relation' AND backend_type IN ('client backend', 'checkpointer', 'background writer');

-- WAL volume and how much of it is full-page images (PG18 columns)
SELECT wal_records, wal_fpi, pg_size_pretty(wal_bytes) AS wal_bytes FROM pg_stat_wal;

-- What are active sessions waiting on right now?
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE state = 'active'
GROUP BY 1, 2 ORDER BY 3 DESC;
-- IO/DataFileRead → cache misses; LWLock/WALWrite or IO/WALSync → WAL flush bottleneck
```

**Fix:**

```sql
ALTER SYSTEM SET max_wal_size = '16GB';               -- size it so checkpoints are mostly timed
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_compression = 'zstd';            -- compresses full-page images (PG15+)
ALTER SYSTEM SET bgwriter_lru_maxpages = 1000;        -- let the bgwriter clean more per round
SELECT pg_reload_conf();
```

Trade-offs: longer checkpoint intervals mean more WAL to replay after a crash (longer recovery) and more disk for `pg_wal`. Also find out *why* WAL grew: a new bulk job, an index added to a hot table, or HOT updates lost because an indexed column now changes.

**What they probe next:** "Why not set `shared_buffers` to 80% of RAM?" Postgres also relies on the OS page cache (double buffering), and a huge pool makes checkpoints and dirty-page management heavier. "What changed in PG18?" **Asynchronous I/O** (`io_method = worker` by default, `io_uring` optional) speeds up sequential scans, bitmap heap scans and VACUUM reads. Writes are still synchronous.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Clock sweep** | usage_count, pins, why not LRU, ring buffers for scans and vacuum |
| **WAL rule** | WAL flushed before the data page; group commit; concurrent insertion |
| **Checkpoints** | Redo point at the start, spreading, FPW cost, timed vs requested |
| **Diagnosis** | Uses `pg_stat_checkpointer` / `pg_stat_io` (PG17+), wait events, WAL volume |

---

## 9. Deadlock Detection & Lock Escalation

**Q:** "A production PostgreSQL database running at 80% CPU suddenly spikes to 100% and stays there. Queries are completing but slowly. You notice `pg_locks` shows hundreds of `Relation` locks and many processes waiting on `transactionid`. Walk through how PostgreSQL detects deadlocks, how lock escalation works (or doesn't), and how to resolve this."

**What They're Really Testing:** Lock-manager internals: table locks vs row locks, how detection really works, which engines escalate, and the difference between *waiting* (no CPU) and *contention* (lots of CPU).

### Answer

!!! tip "30-second answer"
    Hundreds of granted `relation` locks are normal: every query takes `AccessShareLock` or `RowExclusiveLock` on each table and index it touches. `transactionid` waits are **row-lock waits**: a session is waiting for another transaction that holds the row to finish. Waiting sessions sleep and use no CPU, so the CPU spike has another cause. Usual suspects: hot-row contention with retries, bad plans, or **`LWLock:LockManager` contention** when queries touch more relations than the per-backend fast-path slots hold (16 before PostgreSQL 18), so every lock goes through the shared lock table. Deadlocks: a waiting backend checks for a cycle after `deadlock_timeout` (1 s) and aborts **itself** if it finds one. **PostgreSQL never escalates locks**, and neither does InnoDB; SQL Server and Db2 do.

**Table-level lock modes (✅ compatible, ❌ conflicts; symmetric):**

```
                    AS   RS   RE   SUE  S    SRE  E    AE
AccessShare         ✅   ✅   ✅   ✅   ✅   ✅   ✅   ❌    SELECT
RowShare            ✅   ✅   ✅   ✅   ✅   ✅   ❌   ❌    SELECT ... FOR UPDATE/SHARE
RowExclusive        ✅   ✅   ✅   ✅   ❌   ❌   ❌   ❌    INSERT / UPDATE / DELETE / MERGE
ShareUpdateExcl     ✅   ✅   ✅   ❌   ❌   ❌   ❌   ❌    VACUUM, ANALYZE, CREATE INDEX CONCURRENTLY, VALIDATE CONSTRAINT
Share               ✅   ✅   ❌   ❌   ✅   ❌   ❌   ❌    CREATE INDEX (non-concurrent)
ShareRowExcl        ✅   ✅   ❌   ❌   ❌   ❌   ❌   ❌    CREATE TRIGGER, some ALTER TABLE
Exclusive           ✅   ❌   ❌   ❌   ❌   ❌   ❌   ❌    REFRESH MATERIALIZED VIEW CONCURRENTLY
AccessExclusive     ❌   ❌   ❌   ❌   ❌   ❌   ❌   ❌    DROP, TRUNCATE, most ALTER TABLE, VACUUM FULL
```

Two things to point out. `RowExclusive` doesn't conflict with `ShareUpdateExclusive`, which is why autovacuum doesn't block writes. And `AccessExclusive` conflicts even with plain SELECT, which is why `ALTER TABLE` needs `lock_timeout` ([Q12](#12-database-migrations-at-scale)).

**Row locks are different:** `FOR UPDATE`, `FOR NO KEY UPDATE` (taken by ordinary UPDATEs), `FOR SHARE` and `FOR KEY SHARE` (taken by foreign-key checks) are recorded **in the tuple header** (`xmax`, or a MultiXact when several transactions share the lock). They cost no shared memory, so updating 10M rows takes no lock-table space. A waiter queues on a `tuple` lock, then waits on the holder's `transactionid`.

**Deadlock detection (`src/backend/storage/lmgr/deadlock.c`):**

1. A backend that can't get a lock sleeps. Only if it is still waiting after `deadlock_timeout` (1 s) does **that backend** run `DeadLockCheck()`. There is no periodic global detector.
2. It walks the waits-for graph from itself. *Hard* edges point to holders of conflicting locks; *soft* edges point to waiters queued ahead with conflicting requests.
3. If the only cycles involve soft edges, it can **reorder the wait queue** to break them. No abort needed.
4. Otherwise it aborts **its own transaction** with `ERROR: deadlock detected` (SQLSTATE 40P01), with details of the cycle in the log. The victim is whoever noticed first, not the youngest or cheapest transaction.
5. The check takes all lock-manager partition locks, which is why `deadlock_timeout` isn't set to a few milliseconds.

InnoDB checks immediately on every lock wait (`innodb_deadlock_detect = ON`) and rolls back the transaction with the smallest "weight" (rows changed and locked). On very high-concurrency hot rows it is sometimes disabled in favour of `innodb_lock_wait_timeout`.

```python
def find_cycle(waits_for: dict[int, set[int]]) -> list[int] | None:
    """DFS over the waits-for graph (waiter -> holders it waits on)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {}
    stack: list[int] = []

    def dfs(p: int) -> list[int] | None:
        color[p] = GRAY
        stack.append(p)
        for q in waits_for.get(p, ()):
            if color.get(q, WHITE) == GRAY:              # back edge: cycle
                return stack[stack.index(q):] + [q]
            if color.get(q, WHITE) == WHITE and (c := dfs(q)):
                return c
        stack.pop()
        color[p] = BLACK
        return None

    for p in list(waits_for):
        if color.get(p, WHITE) == WHITE and (c := dfs(p)):
            return c
    return None

# A (pid 101) holds row 1, waits for row 2; B (pid 202) holds row 2, waits for row 1.
print(find_cycle({101: {202}, 202: {101}, 303: {101}}))   # [101, 202, 101]
```

**Lock escalation, by engine:**

| Engine | Escalates? | Notes |
|---|---|---|
| PostgreSQL | **No** | Row locks live on disk in tuple headers. "Out of shared memory, increase `max_locks_per_transaction`" comes from too many *relation* locks (thousands of partitions or tables in one transaction), not rows |
| MySQL InnoDB | **No** | Row locks kept in compact per-page bitmaps. Intention locks (IS/IX) are table-level markers, not escalation. Gap and next-key locks under REPEATABLE READ can *look* like table locks when there's no usable index |
| SQL Server | Yes | ~5,000 locks on one object in one statement → table lock (configurable with `LOCK_ESCALATION`) |
| Db2 | Yes | When the lock list is full (`LOCKLIST`, `MAXLOCKS`) |

**Working the incident:**

```sql
-- 1. What are active sessions doing? (Lock waits are sleeps; CPU burners show as running or LWLock waits)
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity WHERE state = 'active'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- 2. Who blocks whom? Root blockers appear in blocked_by but aren't blocked themselves.
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event,
       now() - xact_start AS xact_age, state, left(query, 80) AS query
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0
ORDER BY xact_age DESC;

-- 3. Fast-path overflow: many non-fast-path relation locks → LockManager LWLock contention
SELECT fastpath, count(*) FROM pg_locks WHERE locktype = 'relation' GROUP BY fastpath;

-- 4. After confirming the root blocker: cancel the query first, terminate only if needed
SELECT pg_cancel_backend(12345);
SELECT pg_terminate_backend(12345);
```

Lasting fixes: keep transactions short (`idle_in_transaction_session_timeout`, PG17's `transaction_timeout`); touch rows in a consistent order; spread hot counters across rows; make sure partition pruning happens at plan time so queries don't lock every partition; drop unused indexes. On PostgreSQL 18, fast-path slots scale with `max_locks_per_transaction` (default 64), which removes the 16-relation cliff.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Lock types** | Table-lock modes vs tuple-header row locks vs LWLocks; correct conflict matrix |
| **Deadlock detection** | Per-waiter check after `deadlock_timeout`, soft edges, self-abort, 40P01 |
| **Escalation** | PG and InnoDB never escalate; SQL Server and Db2 do; relation-lock memory limits |
| **Diagnosis** | Waiting ≠ CPU; blocker tree with `pg_blocking_pids`; fast-path contention |

---

## 10. Concurrency Control: 2PL vs OCC vs MVCC

**Q:** "Design a booking system for a concert venue with 10,000 seats. Two customers try to book the last seat simultaneously. Compare how Strict 2PL, Optimistic Concurrency Control (OCC), and MVCC would handle this. Which would you choose and why?"

**What They're Really Testing:** Whether you know the guarantees and costs of each paradigm, and can turn that into a design where the database enforces "one booking per seat" whatever the application does.

### Answer

!!! tip "30-second answer"
    **Strict 2PL** locks before touching data and holds locks until commit: correct and serializable, but waiters block and deadlocks are possible. **OCC** works without locks and validates at commit: no blocking, but under contention most transactions abort and retry. **MVCC** gives readers a snapshot so reads never block writes. It's a *read* strategy; writers still need locks or validation for write-write conflicts. For a seat, don't rely on any of them in application logic. Make the database enforce the invariant: a **conditional UPDATE** (`... WHERE booked_by IS NULL`, check rows affected) or a **unique constraint** on `(event_id, seat_id)` in a bookings table. Both are correct under READ COMMITTED, and the loser gets a clean "seat taken".

**How each paradigm resolves "two buyers, one seat":**

| | Strict 2PL | OCC | MVCC (PostgreSQL) |
|---|---|---|---|
| Mechanism | Shared/exclusive locks held to commit | Read set + versions; validate at commit; write if unchanged | Snapshot reads; row locks for writers |
| Last-seat race | Second buyer blocks on the lock, then sees "booked" | Both proceed; the second to commit fails validation and retries | Second UPDATE blocks on the row lock; what happens next depends on isolation (below) |
| Readers block writers? | Yes | No | No |
| Deadlocks? | Yes | No (no waits) | **Yes**: writers take row locks |
| Good fit | Short, high-contention transactions | Low-contention, read-mostly | Mixed OLTP; long reads beside writes |
| Pathology | Convoys, deadlocks | Retry storms on hot items | Bloat from long transactions; write skew under SI |

**What PostgreSQL actually does with the second UPDATE:**

```sql
-- Both buyers run, concurrently:
UPDATE seats SET booked_by = 'bob' WHERE event_id = 7 AND seat_id = 'A42';
```

- **READ COMMITTED:** Bob's UPDATE waits for Alice's row lock. When Alice commits, Postgres **re-checks Bob's WHERE clause against the new row version** and applies the update. Without an availability predicate, **Bob silently overwrites Alice**.
- **REPEATABLE READ / SERIALIZABLE:** Bob's UPDATE fails with `could not serialize access due to concurrent update`; Bob must retry and will then see the seat taken.

**The design that's correct by construction:**

```sql
-- 1. Conditional update: the predicate is re-checked after waiting, so exactly one buyer wins
UPDATE seats
   SET booked_by = 'bob', booked_at = now()
 WHERE event_id = 7 AND seat_id = 'A42' AND booked_by IS NULL;
-- rows affected = 1 → booked; 0 → taken

-- 2. Or let a constraint arbitrate (also protects against bugs in other code paths)
CREATE TABLE bookings (
    event_id int  NOT NULL,
    seat_id  text NOT NULL,
    user_id  bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, seat_id)
);
INSERT INTO bookings (event_id, seat_id, user_id) VALUES (7, 'A42', 42)
ON CONFLICT (event_id, seat_id) DO NOTHING;      -- 0 rows → taken

-- 3. "Give me any free seat in section B": skip rows others are locking, no queueing
SELECT seat_id FROM seats
WHERE event_id = 7 AND section = 'B' AND booked_by IS NULL
ORDER BY seat_id
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

**Real ticketing adds holds:** a checkout takes minutes, so reserve with an expiry (`held_by`, `hold_expires_at`), confirm on payment, and let expired holds be reclaimed by the same conditional UPDATE (`... AND (held_by IS NULL OR hold_expires_at < now())`). Avoid a single "available seats" counter row on the venue: it turns every booking into a write to one hot row, serialising the whole sale. Derive availability with `count(*)` on an index, or keep per-section counters.

**OCC in miniature.** Validate-and-write must be atomic; in a database that's a conditional write:

```python
def book_with_occ(db, seat_id, user_id, max_retries=3) -> bool:
    for _ in range(max_retries):
        row = db.fetchone("SELECT booked_by, version FROM seats WHERE id = %s", (seat_id,))
        if row.booked_by is not None:
            return False                                   # already taken
        updated = db.execute(
            "UPDATE seats SET booked_by = %s, version = version + 1 "
            "WHERE id = %s AND version = %s", (user_id, seat_id, row.version))
        if updated == 1:
            return True                                    # validation + write in one step
    return False                                           # lost too many races
```

**What they probe next:** a flash sale with 1M users for 10K seats. Put a queue or token gate in front so the database sees bounded concurrency, partition by event, and keep every transaction short.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **2PL** | Growing/shrinking phases, strictness (hold to commit), deadlocks |
| **OCC** | Read-set validation, atomic validate-and-write, retry storms under contention |
| **MVCC reality** | Writers still lock; READ COMMITTED re-check can silently overwrite; deadlocks are possible |
| **Design** | Conditional UPDATE / unique constraint, `SKIP LOCKED`, holds with expiry, no hot counter row |

---

## 11. Materialized Views & Indexed Views

**Q:** "A reporting dashboard query that aggregates 50M rows takes 45 seconds to run. Users refresh it every minute. The table receives 100 writes/second during business hours. Design a solution using materialized views."

**What They're Really Testing:** Freshness vs cost, the locking behaviour of each refresh method, and whether you know when to stop recomputing and start maintaining aggregates incrementally.

### Answer

!!! tip "30-second answer"
    A plain materialized view is a snapshot: `REFRESH` re-runs the whole 45 s query. Without `CONCURRENTLY` it holds an `ACCESS EXCLUSIVE` lock and blocks dashboard reads the whole time. `REFRESH ... CONCURRENTLY` lets reads continue, but it's slower (it diffs old against new) and still costs a full recompute, so refreshing every minute would keep a core busy permanently. At 100 writes/s, the better design is to **maintain the aggregate incrementally**: a per-day rollup table that a job updates every minute with only the new rows (upsert), or `pg_ivm`, or TimescaleDB continuous aggregates. Then the dashboard reads a few hundred rows in milliseconds.

**Refresh options in PostgreSQL:**

| Method | Lock on the matview | Readers during refresh | Cost | Requirements |
|---|---|---|---|---|
| `REFRESH MATERIALIZED VIEW` | `ACCESS EXCLUSIVE` | **Blocked** | Full recompute | None |
| `REFRESH ... CONCURRENTLY` | `EXCLUSIVE` (reads allowed) | See the old contents | Full recompute + diff against the old data (more time and WAL) | A unique index on plain columns covering all rows; matview already populated |
| Incremental (rollup / pg_ivm / continuous aggregates) | Row-level or short locks | Unaffected | Proportional to the change | Aggregates that can be combined (count, sum; avg = sum/count) |

**Incremental rollup (the usual production answer):**

```sql
CREATE TABLE daily_sales_rollup (
    category      text    NOT NULL,
    day           date    NOT NULL,
    num_sales     bigint  NOT NULL,
    total_revenue numeric NOT NULL,
    PRIMARY KEY (category, day)
);

-- Every minute: fold in sales with id in ($1, $2] and advance the watermark to $2.
WITH new_sales AS (
    SELECT p.category, s.sale_date::date AS day, count(*) AS n, sum(s.amount) AS revenue
    FROM sales s
    JOIN products p ON p.id = s.product_id
    WHERE s.id > $1 AND s.id <= $2
    GROUP BY 1, 2
)
INSERT INTO daily_sales_rollup AS r (category, day, num_sales, total_revenue)
SELECT category, day, n, revenue FROM new_sales
ON CONFLICT (category, day) DO UPDATE
   SET num_sales     = r.num_sales + EXCLUDED.num_sales,
       total_revenue = r.total_revenue + EXCLUDED.total_revenue;

-- Dashboard: milliseconds
SELECT category, day, num_sales, total_revenue,
       total_revenue / NULLIF(num_sales, 0) AS avg_ticket
FROM daily_sales_rollup
WHERE day >= current_date - 30
ORDER BY day, category;
```

Gotchas to raise:

- **The watermark can skip rows.** Sequence values are handed out at INSERT time but become visible at COMMIT, so id 1001 can commit after id 1002. Keep the upper bound behind in-flight transactions (a safety lag, or a bound derived from `pg_current_snapshot()`), or drive the rollup from CDC / logical decoding, which delivers rows in commit order.
- **Updates and deletes** to past sales need corrections: subtract the old values and add the new ones, which is easy from a CDC stream.
- **Sliding windows:** store per-day buckets and filter "last 30 days" at read time. Never bake `now()` into the stored aggregate.

**`pg_ivm` (immediate view maintenance extension, v1.16, PG 13–19):**

```sql
CREATE EXTENSION pg_ivm;
SELECT pgivm.create_immv('daily_sales_immv', $$
    SELECT p.category, date_trunc('day', s.sale_date) AS day,
           count(*) AS num_sales, sum(s.amount) AS total_revenue
    FROM sales s JOIN products p ON p.id = s.product_id
    GROUP BY p.category, date_trunc('day', s.sale_date)
$$);
```

It updates the view in AFTER triggers **inside each writing transaction**. Limits: only count/sum/avg/min/max; no `now()` or other non-immutable functions (so no "last 30 days" in the definition); no HAVING, window functions, or aggregates over outer joins. Under READ COMMITTED it takes an `ExclusiveLock` on the IMMV for joins and aggregates, which **serialises concurrent writers**. Load-test it at 100 writes/s before relying on it. Managed services may not offer the extension.

**Other engines:** SQL Server *indexed views* are maintained synchronously on every write and need `SCHEMABINDING`, deterministic expressions and `COUNT_BIG(*)`. Oracle has fast refresh driven by materialized view logs (`REFRESH FAST ON COMMIT`). PostgreSQL has neither built in. Streaming systems (Materialize, RisingWave, Flink) maintain aggregates continuously from CDC.

**What they probe next:** "What if the dashboard needs per-user filters?" Pre-aggregate at the right grain and accept more rows, or move it to an OLAP store (ClickHouse, BigQuery, Druid). "How do you backfill or correct the rollup?" Recompute one day's bucket from source in a single transaction.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Refresh mechanics** | Knows plain REFRESH blocks reads; CONCURRENTLY needs a unique index and is slower |
| **Incremental maintenance** | Rollup with upsert, watermark visibility gap, corrections for updates |
| **pg_ivm limits** | Immediate maintenance in the writer's transaction, supported aggregates, lock serialisation |
| **Freshness vs cost** | Matches refresh strategy to write rate and latency needs |

---

## 12. Database Migrations at Scale

**Q:** "You need to add a NOT NULL column with a default value to a 500M row production table. The application cannot have more than 1 second of downtime. Design the migration strategy."

**What They're Really Testing:** Whether you know which DDL rewrites the table and which only changes the catalog, and that the real outage risk is the **lock queue**, not the DDL itself.

### Answer

!!! tip "30-second answer"
    On PostgreSQL 11+, `ALTER TABLE users ADD COLUMN timezone text NOT NULL DEFAULT 'UTC'` is **instant**. A non-volatile default is stored once in the catalog (`attmissingval`) and returned for existing rows, so there's no rewrite and no scan. The danger is the brief `ACCESS EXCLUSIVE` lock: if a long query holds even an `ACCESS SHARE` lock on the table, the ALTER waits, and every query arriving after it queues behind the ALTER. That's an outage caused by a "1 ms" statement. So set `lock_timeout` (e.g. 2 s), retry with backoff, and run off-peak. Use the full **expand → backfill → contract** process only when values must be computed per row, the default is volatile (`gen_random_uuid()`, `clock_timestamp()`), or a type change forces a rewrite. On MySQL 8.0.12+, `ALGORITHM=INSTANT` covers the same case.

**The safe version of the "naive" statement:**

```sql
SET lock_timeout = '2s';        -- give up instead of blocking everyone behind us
SET statement_timeout = '15s';
ALTER TABLE users ADD COLUMN timezone text NOT NULL DEFAULT 'UTC';
-- On SQLSTATE 55P03 (lock_not_available): sleep with jitter, retry; alert after N attempts.
```

**What rewrites in PostgreSQL (and so needs expand/contract):**

| Change | Rewrite / scan? |
|---|---|
| `ADD COLUMN` nullable, or with a non-volatile default (PG11+) | No (catalog only) |
| `ADD COLUMN ... DEFAULT gen_random_uuid()` (volatile) | **Full rewrite** |
| `ALTER COLUMN TYPE` (`int → bigint`, `text → int`) | **Full rewrite** and index rebuilds (except binary-coercible changes such as `varchar(50) → varchar(100)` or `→ text`) |
| `SET NOT NULL` | Full **scan** under `ACCESS EXCLUSIVE`, unless a valid CHECK constraint already proves it |
| `ADD FOREIGN KEY` / `ADD CHECK` | Scan, unless added `NOT VALID` and validated separately |
| `CREATE INDEX` | Blocks writes; use `CREATE INDEX CONCURRENTLY` |
| `DROP COLUMN` | Catalog only (space reclaimed by later rewrites) |

**Expand → backfill → contract (when values must be computed):**

```sql
-- EXPAND: catalog-only, behind lock_timeout
ALTER TABLE users ADD COLUMN timezone text;
-- Deploy app code that writes timezone for new and updated rows and tolerates NULL on read.

-- BACKFILL: many small transactions over primary-key ranges, driven by a script that
-- advances $1 by the batch size, sleeps between batches and watches replica lag.
UPDATE users
   SET timezone = coalesce(tz_for_country(country), 'UTC')
 WHERE id >= $1 AND id < $1 + 10000
   AND timezone IS NULL;

-- ENFORCE NOT NULL without a long ACCESS EXCLUSIVE scan
-- PostgreSQL 18+: NOT NULL constraints can be added NOT VALID
ALTER TABLE users ADD CONSTRAINT users_timezone_nn NOT NULL timezone NOT VALID;
ALTER TABLE users VALIDATE CONSTRAINT users_timezone_nn;   -- SHARE UPDATE EXCLUSIVE: reads and writes continue

-- PostgreSQL 12–17: prove it with a CHECK first, then SET NOT NULL skips the scan
ALTER TABLE users ADD CONSTRAINT users_timezone_chk CHECK (timezone IS NOT NULL) NOT VALID;
ALTER TABLE users VALIDATE CONSTRAINT users_timezone_chk;
ALTER TABLE users ALTER COLUMN timezone SET NOT NULL;       -- brief lock, no scan
ALTER TABLE users DROP CONSTRAINT users_timezone_chk;

-- CONTRACT: remove old code paths; drop a replaced column (catalog-only, still needs lock_timeout)
ALTER TABLE users DROP COLUMN old_timezone;
```

Why PK ranges and not `WHERE timezone IS NULL LIMIT 10000`? The latter rescans already-processed rows and dead tuples on every batch, so it gets slower as it goes; ranges keep each batch an index range scan. Each batch commits on its own, so VACUUM can keep up and replicas don't fall behind on one huge transaction.

**Other zero-downtime patterns:**

- **Unique constraint:** `CREATE UNIQUE INDEX CONCURRENTLY`, then `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX`. A failed CIC leaves an `INVALID` index: drop it and retry. CIC can't run inside a transaction block.
- **Foreign key:** `ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID`, then `VALIDATE CONSTRAINT`.
- **`int → bigint` primary key:** add a `bigint` column, sync it with a trigger, backfill, build the unique index concurrently, then swap in a short transaction.
- **Renames:** never rename in place while old code runs. Add the new column, dual-write, migrate readers, then drop.

**Tools:**

| Tool | Database | Approach |
|---|---|---|
| pgroll (Xata) | PostgreSQL | Expand/contract with versioned schemas exposed as views, triggers to keep old and new columns in sync |
| pg-osc (Shopify) | PostgreSQL | Shadow table + triggers + swap |
| gh-ost (GitHub) | MySQL | Shadow table fed from the binlog (no triggers), throttling, cut-over |
| pt-online-schema-change (Percona) | MySQL | Shadow table + triggers |
| Native online DDL | MySQL 8.0+ | `ALGORITHM=INSTANT` for adding or dropping columns (any position since 8.0.29), `INPLACE, LOCK=NONE` for many index changes |

**Common pitfalls:** a backfill in one giant transaction (bloat, replica lag, hours of locks); forgetting that `lock_timeout` must be set in the *migration's* session; an ORM that caches the schema or does `SELECT *` into a fixed struct; and migrations that aren't backward-compatible with the code version still running during a rolling deploy.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Catalog vs rewrite** | Knows PG11+ fast defaults; lists what does rewrite |
| **Lock queue** | `lock_timeout` + retry; explains how a waiting ALTER blocks everyone |
| **NOT NULL / constraints** | NOT VALID + VALIDATE; PG18 NOT NULL NOT VALID; CHECK trick for older versions |
| **Backfill** | PK-ranged, batched, throttled, lag-aware; tool awareness for PG and MySQL |

---

## 13. Connection Pooling & PgBouncer Internals

**Q:** "A Django application with 200 web workers connects to PostgreSQL and keeps crashing with 'too many connections.' The sysadmin increased max_connections to 500 but now the database is slow. Design a connection pooling strategy."

**What They're Really Testing:** That throughput peaks at a small number of *active* connections, how transaction pooling works and what it breaks, and how to size a pool with Little's Law.

### Answer

!!! tip "30-second answer"
    Every Postgres connection is a process with its own memory and caches, and throughput stops rising once active queries exceed roughly a few times the CPU cores. Past that you only add context switching and lock contention. So keep thousands of *client* connections at a pooler and a few dozen *server* connections at Postgres. Put **PgBouncer in transaction mode** in front: a server connection is lent to a client for one transaction and returned at COMMIT. Size the pool with Little's Law (busy connections = transactions/s × seconds each transaction holds a connection) and cap it at what the database can actually run in parallel. Transaction mode breaks session state: session `SET`, session advisory locks, `LISTEN`, `WITH HOLD` cursors and SQL-level `PREPARE`. Protocol-level prepared statements work since PgBouncer 1.21 (`max_prepared_statements`).

**Why 500 connections made it slower:**

- Each backend is a process: a few MB of private memory to start, growing with catalog caches and cached plans as the schema gets larger.
- `work_mem` is per sort or hash node and allocated on demand. Its risk is *many concurrent queries × several nodes × work_mem*, not idle connections.
- More concurrent active backends means more CPU context switching and contention on shared structures (lock-manager partitions, buffer mapping, WAL insertion). Snapshot cost with many connections was much reduced in PG14, but contention remains.
- Rule of thumb from benchmarks: active connections ≈ 2–4 × cores (more if queries wait on I/O). A 16-core server peaks somewhere around 30–60 active connections.

**Pool modes:**

| Mode | Server connection returned | Breaks | Use |
|---|---|---|---|
| `session` (default) | When the client disconnects | Nothing | Reduces connect cost only; no multiplexing |
| `transaction` | At COMMIT / ROLLBACK | Session `SET` (use `SET LOCAL` or `set_config(..., true)`), session advisory locks, `LISTEN/NOTIFY`, `WITH HOLD` cursors, temp tables across transactions, SQL `PREPARE` | Web apps: the standard choice |
| `statement` | After each statement | Multi-statement transactions entirely | Rare (autocommit-only workloads) |

**Configuration:**

```ini
[databases]
mydb = host=10.0.0.5 port=5432 dbname=mydb

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
pool_mode = transaction
; client sockets are cheap; accept all app workers
max_client_conn = 2000
; server connections per (database, user) pair
default_pool_size = 30
; hard cap per database across all users
max_db_connections = 40
reserve_pool_size = 5
reserve_pool_timeout = 3
server_idle_timeout = 600
; fail fast instead of queueing clients indefinitely
query_wait_timeout = 30
; protocol-level prepared statements in transaction mode (PgBouncer 1.21+)
max_prepared_statements = 200
```

On the Postgres side, set `max_connections` to the pooler caps plus admin headroom, add `idle_in_transaction_session_timeout` (a client idle mid-transaction pins a server connection), and keep `statement_timeout` slightly above PgBouncer's `query_timeout` if you use it.

**Sizing with Little's Law (L = λ × W):**

```
λ = 1,000 requests/s × 3 transactions per request = 3,000 transactions/s
W = 10 ms average time a transaction holds a server connection
L = 3,000 × 0.010 = 30 connections busy on average
→ default_pool_size ≈ 30–40 per (db, user) pair, plus a small reserve.

If L comes out larger than the database can run in parallel (say 200),
more connections won't help: shorten W instead (faster queries,
no network calls or app work inside transactions) or add capacity.
```

**Django specifics:** with transaction pooling set `DISABLE_SERVER_SIDE_CURSORS = True` (named cursors need a session), keep `CONN_MAX_AGE` modest, and avoid session-level `SET` in middleware. Django 5.1+ also has a native psycopg 3 pool (`OPTIONS: {"pool": ...}`), which is per process. You still need PgBouncer to bound the total across 200 workers.

**Operating PgBouncer:**

```sql
-- On the admin console (psql -p 6432 pgbouncer)
SHOW POOLS;   -- cl_active, cl_waiting (should be ~0), sv_active, sv_idle, maxwait / maxwait_us
SHOW STATS;   -- avg_xact_time, avg_query_time, avg_wait_time (microseconds)
-- cl_waiting > 0 or a rising maxwait → pool too small or transactions too long
```

- PgBouncer is **single-threaded**: one process saturates one core at roughly tens of thousands of transactions/s. Run several with `so_reuseport` (and peering so cancel requests work), or several instances behind a load balancer.
- `PAUSE` / `RESUME` drain traffic for switchovers, which is useful in [Q6](#6-replication-synchronous-vs-asynchronous) failovers.
- Alternatives: PgCat and PgDog (multi-threaded, with sharding and load balancing), Supavisor, Odyssey, AWS RDS Proxy.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Why fewer is faster** | Process model, contention, work_mem multiplied by active queries |
| **Pooling modes** | Transaction mode, what it breaks, `SET LOCAL`, prepared statements since 1.21 |
| **Little's Law** | Computes L correctly and caps it at database capacity |
| **Operations** | SHOW POOLS signals, single-threaded scaling, timeouts on both sides |

---

## 14. Distributed SQL: CockroachDB vs Spanner

**Q:** "Your startup is building a global multi-tenant SaaS application. Data must be consistent across US, EU, and Asia regions. Compare CockroachDB and Google Spanner. How does each achieve global consistency without sacrificing availability?"

**What They're Really Testing:** That consistency costs latency and availability in a partition (both are CP), and that the key architectural difference is how each system bounds clock uncertainty.

### Answer

!!! tip "30-second answer"
    Both split tables into ranges ("splits" in Spanner), replicate each with consensus (Raft in CockroachDB, Paxos in Spanner), use MVCC timestamps, and run 2PC-style commits across ranges. Neither keeps full availability in a partition: a minority side can't commit. They differ in clocks. **Spanner's TrueTime** exposes a bounded uncertainty interval from GPS and atomic clocks, and *commit-wait* sleeps it out, so timestamp order matches real-time order (**external consistency**, i.e. strict serializability). **CockroachDB** runs on ordinary NTP clocks with a **hybrid logical clock** and a configured maximum offset (500 ms by default). A read that sees a value inside its uncertainty window has to restart at a higher timestamp. You get serializable transactions and linearizable single keys, but not strict serializability for unrelated keys. For the SaaS question, latency comes from **data placement**: home each tenant's rows in its region so most transactions are local.

**Architecture side by side:**

| | CockroachDB | Spanner |
|---|---|---|
| Unit of replication | Range (split above 512 MiB by default, or by load) | Split (automatic, by size and load) |
| Consensus | Raft per range; the **leaseholder** serves reads and coordinates writes | Paxos per split; a long-lived leader with a lease |
| Clock | HLC + NTP, `max_offset` 500 ms; a node shuts itself down if its offset grows too large | TrueTime: `TT.now()` returns `[earliest, latest]` |
| Strongest guarantee | Serializable (default isolation); READ COMMITTED also available | External consistency (strict serializability) |
| Stale or local reads | Follower reads: `AS OF SYSTEM TIME follower_read_timestamp()` | Stale reads (bounded or exact staleness) from any replica |
| Interface | PostgreSQL wire protocol (subset) | GoogleSQL or PostgreSQL dialect |
| Deployment | Self-hosted or Cockroach Cloud | Google Cloud only (managed) |
| Licensing | Source-available; since Nov 2024 no free "Core" edition. Enterprise is free under $10M annual revenue, with mandatory telemetry | Pay per compute/storage (editions) |

**Clocks, the key difference:**

```python
import time

class HLC:
    """Hybrid Logical Clock (Kulkarni et al., 2014). Timestamp = (l, c)."""
    def __init__(self, wall=time.time_ns):
        self.wall = wall
        self.l = 0  # max physical time seen so far
        self.c = 0  # logical counter to order events within the same l

    def now(self) -> tuple[int, int]:
        """Local event or message send."""
        pt = self.wall()
        if pt > self.l:
            self.l, self.c = pt, 0
        else:
            self.c += 1
        return (self.l, self.c)

    def update(self, ml: int, mc: int) -> tuple[int, int]:
        """Message receive carrying remote timestamp (ml, mc)."""
        pt = self.wall()
        old_l = self.l
        self.l = max(old_l, ml, pt)
        if self.l == old_l == ml:
            self.c = max(self.c, mc) + 1
        elif self.l == old_l:
            self.c += 1
        elif self.l == ml:
            self.c = mc + 1
        else:
            self.c = 0
        return (self.l, self.c)

# Node B's clock is 5 units behind node A's.
a = HLC(wall=lambda: 100)
b = HLC(wall=lambda: 95)
send = a.now()            # (100, 0)
recv = b.update(*send)    # (100, 1): B's timestamp is after A's despite B's slow clock
assert send < recv
```

HLC preserves causality: if A happened before B through a message, then `HLC(A) < HLC(B)`. It can't order two transactions that never communicated when clocks disagree by up to `max_offset`. CockroachDB covers that by treating any value with a timestamp in `(read_ts, read_ts + max_offset]` as "possibly in my past" and restarting or pushing the read. The remaining gap is a *causal reverse*: two transactions on disjoint keys with no communication between them can be ordered differently from real time.

**Spanner commit-wait:** pick commit timestamp `s = TT.now().latest`, replicate through Paxos, and don't release locks or acknowledge until `TT.now().earliest > s`, about 2ε later, overlapped with replication. Every transaction that starts afterwards gets a larger timestamp. The 2012 paper reports ε of roughly 1–7 ms, which is only affordable because Google runs GPS and atomic clock masters in every datacenter.

**Multi-region design for the SaaS app (CockroachDB syntax):**

```sql
ALTER DATABASE app SET PRIMARY REGION "us-east1";
ALTER DATABASE app ADD REGION "europe-west1";
ALTER DATABASE app ADD REGION "asia-northeast1";
ALTER DATABASE app SURVIVE REGION FAILURE;      -- 5 replicas spread so a region can be lost

ALTER TABLE tenant_data SET LOCALITY REGIONAL BY ROW;  -- hidden crdb_region column homes each row
ALTER TABLE plans       SET LOCALITY GLOBAL;           -- read-mostly: fast local reads, slower writes
```

In Spanner, the equivalents are a multi-region instance configuration with a leader region (`ALTER DATABASE ... SET OPTIONS (default_leader = 'us-east1')`), interleaved tables to co-locate a tenant's rows, and stale reads for local latency.

**Latency reality:** a write that must reach a majority across three continents pays ~100+ ms. Region-homed rows with `SURVIVE ZONE FAILURE` commit within one region (a few ms). `SURVIVE REGION FAILURE` needs a cross-region majority on every write. Pick per table, and tell the business which writes are slow and why.

**Choosing:** Spanner if you're on Google Cloud, want a fully managed service, and need strict serializability or massive scale. CockroachDB for multi-cloud or self-hosted deployments and PostgreSQL compatibility, after checking the licence terms. Also consider YugabyteDB (Apache 2.0 core) and plain PostgreSQL with one regional cluster per tenant group, which is often enough if tenants never need cross-region transactions.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CAP honesty** | Both are CP; consistency costs a majority round trip and minority-side availability |
| **Clocks** | TrueTime + commit-wait vs HLC + uncertainty restarts; external consistency vs serializable |
| **Placement** | Regional-by-row, global tables, survival goals, follower/stale reads |
| **Practicalities** | Licensing, managed vs self-hosted, PostgreSQL compatibility gaps |

---
