# 🐘 PostgreSQL — Principal Engineer Deep-Dive

> *PostgreSQL reference for Staff/Principal Engineer interviews: architecture, internals, performance tuning, production operations, and 12 staff-level interview questions with evaluation rubrics. Current as of October 2026: PostgreSQL 18 is the latest release (18.6), 19 is in beta, and 14 reaches end of life on 12 November 2026.*

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Process & Memory Architecture](#2-process-memory-architecture)
3. [Storage Internals](#3-storage-internals)
4. [MVCC & Vacuum](#4-mvcc-vacuum)
5. [WAL & Checkpoints](#5-wal-checkpoints)
6. [Query Execution Pipeline](#6-query-execution-pipeline)
7. [Indexing In Depth](#7-indexing-in-depth)
8. [Partitioning & Sharding](#8-partitioning-sharding)
9. [Performance Tuning](#9-performance-tuning)
10. [Production Operations](#10-production-operations)
11. [Staff-Level Interview Questions](#11-staff-level-interview-questions)
12. [Common Pitfalls & Anti-Patterns](#12-common-pitfalls-anti-patterns)
13. [What Changed in PostgreSQL 17 and 18](#13-what-changed-in-postgresql-17-and-18)

---

## 1. Architecture Overview

PostgreSQL uses a **multi-process architecture**: each client connection gets a dedicated OS process (a *backend*), forked by the postmaster. MySQL, by contrast, runs one thread per connection inside a single process.

```
┌───────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL instance                           │
│                                                                       │
│  ┌──────────────┐   fork per    ┌───────────┐ ┌───────────┐           │
│  │ Postmaster   │ ────────────► │ Backend 1 │ │ Backend 2 │  ...      │
│  │ listens 5432 │  connection   │ parse     │ │ parse     │           │
│  │ supervises,  │               │ plan      │ │ plan      │           │
│  │ crash-resets │               │ execute   │ │ execute   │           │
│  └──────────────┘               └─────┬─────┘ └─────┬─────┘           │
│                                       │             │                 │
│  ┌────────────────────────────────────▼─────────────▼──────────────┐  │
│  │ Shared memory                                                   │  │
│  │  shared buffers (8 KB pages) · WAL buffers · lock table ·       │  │
│  │  proc array (running xacts) · SLRU caches (commit status in     │  │
│  │  pg_xact, subtransactions, multixacts) · cumulative statistics  │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  Background processes: checkpointer · background writer · WAL writer │
│  · autovacuum launcher + workers · WAL senders / receiver ·           │
│  archiver · logical replication launcher + workers ·                  │
│  WAL summarizer (PG17, for incremental backup) · I/O workers (PG18)   │
└───────────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Processes, not threads:** a crash in one backend can't corrupt another's private memory, but the postmaster still restarts *all* backends after any backend crash, because shared memory may be damaged. The cost is per-connection memory and fork/setup overhead, which is why production deployments put a pooler in front ([Q13 in the interview questions](INTERVIEW_QUESTIONS.md#13-connection-pooling-pgbouncer-internals)).
- **Shared memory** holds everything backends must agree on: buffers, WAL buffers, locks, the proc array used to build snapshots, and (since PG15) the cumulative statistics that the old stats collector process used to keep.
- **Double buffering:** PostgreSQL does buffered I/O through the OS page cache, so data can sit both in `shared_buffers` and in the kernel cache. That's why `shared_buffers` is usually ~25% of RAM rather than most of it.

---

## 2. Process & Memory Architecture

### 2.1 Key Background Processes

| Process | Role | Configuration |
|---------|------|--------------|
| **Postmaster** | Listens on the port, forks backends, restarts the cluster after a crash | `port`, `listen_addresses`, `max_connections` |
| **Checkpointer** | Writes all dirty buffers at checkpoints, fsyncs data files, advances the redo point | `checkpoint_timeout`, `max_wal_size`, `checkpoint_completion_target` |
| **Background writer** | Writes some dirty buffers ahead of the clock-sweep hand so backends find clean victims | `bgwriter_delay`, `bgwriter_lru_maxpages`, `bgwriter_lru_multiplier` |
| **WAL writer** | Flushes WAL periodically, which matters mainly for `synchronous_commit = off`. Committing backends flush their own WAL | `wal_writer_delay`, `wal_writer_flush_after` |
| **Autovacuum launcher / workers** | Launcher schedules; workers run VACUUM / ANALYZE per table | `autovacuum_max_workers` (changeable without restart up to `autovacuum_worker_slots` since PG18), `autovacuum_naptime` |
| **WAL sender / receiver** | Stream WAL to standbys / receive it on a standby | `max_wal_senders`, `primary_conninfo` |
| **Logical replication workers** | Apply changes from a publication on the subscriber | `max_logical_replication_workers` |
| **Archiver** | Ships completed WAL segments to an archive | `archive_mode`, `archive_command` or `archive_library` (PG15+) |
| **WAL summarizer** (PG17+) | Records which blocks changed, enabling `pg_basebackup --incremental` | `summarize_wal` |
| **I/O workers** (PG18+) | Perform asynchronous reads when `io_method = worker` (the default) | `io_method`, `io_workers` |

There is no "stats collector" process any more: since PG15, cumulative statistics live in shared memory and are written to disk at shutdown.

### 2.2 Memory Configuration

```
Shared memory (allocated at startup)
├── shared_buffers ........... default 128MB; typical 25% of RAM (8GB on a 32GB host)
├── wal_buffers .............. default -1 = 1/32 of shared_buffers, capped at 16MB
├── lock table ............... max_locks_per_transaction × (max_connections + max_prepared_transactions)
└── SLRU caches, proc array, stats ...

Per backend (private, allocated on demand)
├── work_mem ................. default 4MB PER sort/hash node, PER query, PER parallel worker;
│                              hash nodes may use work_mem × hash_mem_multiplier (2.0)
├── maintenance_work_mem ..... default 64MB; VACUUM, CREATE INDEX, ALTER TABLE ADD FK
├── temp_buffers ............. default 8MB; temporary tables
└── catalog/plan caches ...... grow with schema size and prepared statements
```

The `work_mem` trap is multiplication: 200 active queries × 3 hash/sort nodes × 64 MB is 38 GB in the worst case. Set a modest global value and raise it per role or session for reporting.

**Sizing guidelines (32 GB dedicated host, SSD):**

```ini
shared_buffers = 8GB              # ~25% of RAM
effective_cache_size = 24GB       # planner hint: shared_buffers + expected OS cache; allocates nothing
work_mem = 32MB                   # per sort/hash node; watch active-query count
maintenance_work_mem = 1GB        # faster VACUUM index passes and index builds
wal_buffers = 64MB                # only helps very write-heavy workloads; auto (16MB) is fine otherwise
random_page_cost = 1.1            # SSD/NVMe; the default 4.0 assumes spinning disks
huge_pages = try                  # large shared_buffers benefits from huge pages on Linux
```

---

## 3. Storage Internals

### 3.1 Physical Storage Layout

```
PGDATA/
├── postgresql.conf, pg_hba.conf, postgresql.auto.conf (ALTER SYSTEM)
├── global/                 # cluster-wide catalogs (pg_database, pg_authid) + pg_control
├── base/<db_oid>/          # one directory per database
│   ├── <relfilenode>       # main fork (heap or index), split into 1GB segments:
│   ├── <relfilenode>.1     #   second segment
│   ├── <relfilenode>_fsm   # free space map fork
│   └── <relfilenode>_vm    # visibility map fork (tables only)
├── pg_wal/                 # WAL segments (16MB each by default)
├── pg_xact/                # commit status: 2 bits per transaction
├── pg_multixact/           # shared row-lock membership
├── pg_subtrans/            # subtransaction parents
├── pg_replslot/            # replication slot state
├── pg_stat/                # stats saved at shutdown
├── pg_wal/summaries/       # WAL summaries (PG17+, when summarize_wal = on)
└── pg_tblspc/              # symlinks to tablespaces
```

`relfilenode` starts equal to the table's OID but changes on rewrites (`TRUNCATE`, `VACUUM FULL`, `CLUSTER`, some `ALTER TABLE`s). Find it with `pg_relation_filepath('orders')`.

### 3.2 Page (Block) Structure

PostgreSQL stores tables and indexes in fixed-size **pages** (8 KB by default, set at compile time).

```
┌─────────────────────────────────────────────────────────────┐ offset 0
│ PageHeaderData (24 bytes)                                   │
│   pd_lsn       LSN of the last WAL record that changed page │
│   pd_checksum  page checksum (initdb enables by default PG18)│
│   pd_flags, pd_lower, pd_upper, pd_special,                 │
│   pd_pagesize_version, pd_prune_xid                         │
├─────────────────────────────────────────────────────────────┤
│ Line pointers (ItemIdData, 4 bytes each), growing down →    │
│   lp 1: (offset=8144, len=48, LP_NORMAL)                    │
│   lp 2: (offset=8096, len=48, LP_REDIRECT → lp 3)  HOT chain │
│   lp 3: (offset=8040, len=56, LP_NORMAL)                    │
├──────────────────────── pd_lower ───────────────────────────┤
│                       free space                            │
├──────────────────────── pd_upper ───────────────────────────┤
│ ← tuples, allocated from the end of the page backwards      │
│   HeapTupleHeader (23 bytes + null bitmap, padded) + data   │
│     t_xmin, t_xmax, t_cid/t_xvac, t_ctid (6B),              │
│     t_infomask2, t_infomask, t_hoff, t_bits[]               │
├─────────────────────────────────────────────────────────────┤
│ special space (indexes only, e.g. B-tree sibling links)     │
└─────────────────────────────────────────────────────────────┘ offset 8192
```

A tuple's address (TID or `ctid`) is `(block, line pointer)`. Indexes point at line pointers, not byte offsets, so tuples can be compacted within a page without touching indexes.

### 3.3 TOAST (The Oversized-Attribute Storage Technique)

A row must fit in one 8 KB page, so large variable-length values are compressed and/or moved out of line.

```
When: a row exceeds TOAST_TUPLE_THRESHOLD (~2 KB). PostgreSQL compresses and/or moves
      the largest eligible columns until the row is under TOAST_TUPLE_TARGET (~2 KB,
      tunable per table with toast_tuple_target).

Per-column strategy (ALTER TABLE ... ALTER COLUMN ... SET STORAGE):
  PLAIN     never compressed or moved (fixed-length types such as integer)
  EXTENDED  compress first, then move out of line (default for text, jsonb, bytea)
  EXTERNAL  move out of line without compressing (fast substring on large text/bytea)
  MAIN      compress, move out of line only as a last resort

Compression: pglz (default) or lz4 (PG14+, default_toast_compression = lz4; faster)

TOAST table: pg_toast.pg_toast_<table_oid>, with its own index
  chunk_id   OID identifying the toasted VALUE (stored in the main row's TOAST pointer)
  chunk_seq  chunk number within that value
  chunk_data up to ~2 KB of the value
```

Practical consequences: `SELECT *` on wide rows de-TOASTs every big column; selecting only needed columns avoids it. Updating any column of a row whose TOASTed values are unchanged reuses the existing TOAST pointers, so the large values aren't rewritten. A single large `jsonb` document rewritten on every small change is a classic source of write amplification and bloat.

### 3.4 Free Space Map (FSM)

Each table and index has a free space map fork (`<relfilenode>_fsm`) recording roughly how much free space each page has, so INSERTs and non-HOT UPDATEs can reuse space instead of always extending the file.

```c
// One byte per heap page: free space in 32-byte units (0–255 → 0–8160 bytes).
// Stored as a tree of max-values so "find a page with ≥ N bytes" is O(log n):
//
//   upper level:   [ 200 ]
//                  /     \
//   leaves:     [100, 200] [150, 80]     ← free-space category per heap page
//
// Search for 120 bytes: root 200 ≥ 120 → left child max 200 → page 1 has 200 → use it.
// VACUUM updates the FSM after it frees space; the FSM is a hint, so it can be stale.
```

### 3.5 Visibility Map (VM)

Each table has a visibility map fork (`<relfilenode>_vm`) with **two bits per heap page**:

- **all-visible:** every tuple on the page is visible to all current and future transactions. Index-only scans can skip the heap fetch for that page, and VACUUM can skip the page.
- **all-frozen** (PG9.6+): every tuple is frozen. Anti-wraparound (aggressive) VACUUM can skip the page too, which makes freezing large, mostly static tables cheap.

Size: 2 bits per 8 KB page is ~32 KB per GB of table. Any modification to a page clears its bits; VACUUM sets them again.

---

## 4. MVCC & Vacuum

### 4.1 PostgreSQL MVCC — Heap Tuple Internals

PostgreSQL never updates a row in place. An UPDATE writes a **new tuple version** and marks the old one as superseded, and old versions stay in the heap until VACUUM removes them. (Pages aren't append-only: freed space is reused through the FSM, and single pages are pruned opportunistically.)

```c
// src/include/access/htup_details.h (simplified)
typedef struct HeapTupleFields {
    TransactionId t_xmin;        // inserting transaction
    TransactionId t_xmax;        // deleting/updating/locking transaction, or 0
    union { CommandId t_cid; TransactionId t_xvac; } t_field3;  // command id within xact
} HeapTupleFields;

typedef struct HeapTupleHeaderData {
    union { HeapTupleFields t_heap; DatumTupleFields t_datum; } t_choice;
    ItemPointerData t_ctid;      // own TID, or TID of the newer version
    uint16 t_infomask2;          // attribute count + HEAP_HOT_UPDATED / HEAP_ONLY_TUPLE
    uint16 t_infomask;           // flags below
    uint8  t_hoff;               // header length incl. null bitmap
    bits8  t_bits[];             // null bitmap
} HeapTupleHeaderData;           // 23 bytes before t_bits

// Selected t_infomask bits ("hint bits" cache commit status so pg_xact needn't be read again)
#define HEAP_XMAX_KEYSHR_LOCK  0x0010
#define HEAP_XMAX_EXCL_LOCK    0x0040
#define HEAP_XMAX_LOCK_ONLY    0x0080  // xmax only locks the row; it didn't delete it
#define HEAP_XMIN_COMMITTED    0x0100
#define HEAP_XMIN_INVALID      0x0200  // inserter aborted
#define HEAP_XMIN_FROZEN       (HEAP_XMIN_COMMITTED | HEAP_XMIN_INVALID)
#define HEAP_XMAX_COMMITTED    0x0400
#define HEAP_XMAX_INVALID      0x0800  // no valid deleter/locker
#define HEAP_XMAX_IS_MULTI     0x1000  // xmax is a MultiXactId (several lockers)
#define HEAP_UPDATED           0x2000  // this tuple is the result of an UPDATE
```

Hint bits explain a surprise: the first SELECT after a big data load can *write* pages, because it sets hint bits (and, with checksums or `wal_log_hints`, may log full-page images).

### 4.2 Snapshot Isolation

A **snapshot** records which transactions count as committed for a given statement (READ COMMITTED) or a whole transaction (REPEATABLE READ and SERIALIZABLE, taken at the *first statement*, not at `BEGIN`).

```c
typedef struct SnapshotData {        // simplified
    TransactionId xmin;     // all XIDs < xmin had finished when the snapshot was taken
    TransactionId xmax;     // all XIDs >= xmax had not started yet (= next XID to assign)
    TransactionId *xip;     // XIDs in [xmin, xmax) still running at snapshot time
    uint32 xcnt;
    TransactionId *subxip;  // running subtransactions (can overflow → pg_subtrans lookups)
    CommandId curcid;       // own changes made by earlier commands are visible
} SnapshotData;
```

A transaction **X counts as committed for the snapshot** when `X < xmax`, X isn't in `xip`, and `pg_xact` says committed.

A tuple version is **visible** when:

1. `t_xmin` is your own transaction (and inserted by an earlier command), **or** `t_xmin` counts as committed for your snapshot; **and**
2. `t_xmax` is invalid/0, or it only *locked* the row, or its transaction aborted, or it does **not** count as committed for your snapshot (still running, or started after it). If `t_xmax` is your own transaction, the tuple is visible only to commands that ran before your delete/update.

Read-only transactions don't consume an XID. They get a *virtual* transaction ID, and a real XID is assigned at the first write. That's why heavy read traffic doesn't advance XID age.

### 4.3 UPDATE Trace

```
Row id=1: balance=1000, xmin=100 (committed), xmax=0. Next XID to assign: 240.

T_A: BEGIN ISOLATION LEVEL REPEATABLE READ;
T_A: SELECT balance FROM accounts WHERE id = 1;
       snapshot S_A = {xmin=240, xmax=240, xip=[]}     (no XID for T_A: read-only)
       tuple: xmin=100 < 240 and committed → visible; xmax=0 → not deleted
       → 1000

T_B (READ COMMITTED): UPDATE accounts SET balance = 900 WHERE id = 1;
       T_B is assigned XID 240
       1. lock the old tuple: xmax = 240
       2. insert new tuple: xmin = 240, xmax = 0, balance = 900
       3. old tuple's t_ctid → new tuple's TID
       4. HOT if no indexed column changed and the page has room; otherwise
          insert a new entry into EVERY index on the table
     COMMIT;  → pg_xact marks 240 committed

T_A: SELECT balance FROM accounts WHERE id = 1;    (same snapshot S_A)
       old tuple: xmax = 240 ≥ S_A.xmax → T_B "hasn't started" for this snapshot
                  → the delete is invisible → old tuple VISIBLE
       new tuple: xmin = 240 ≥ S_A.xmax → INVISIBLE
       → 1000 (repeatable read)

T_C (READ COMMITTED, starts later): SELECT balance FROM accounts WHERE id = 1;
       snapshot S_C = {xmin=241, xmax=241, xip=[]}
       old tuple: xmax = 240 < 241, committed → deleted → invisible
       new tuple: xmin = 240 committed → visible
       → 900
```

If T_A then tried to UPDATE row 1, it would get `ERROR: could not serialize access due to concurrent update`, because REPEATABLE READ is first-updater-wins. Under READ COMMITTED it would instead wait for T_B, re-evaluate its WHERE clause against the new version (EvalPlanQual), and update that.

### 4.4 Vacuum Mechanics

VACUUM is PostgreSQL's garbage collector. It must also run periodically to prevent XID wraparound.

```
What a (lazy) VACUUM does:
  1. Scan heap pages not marked all-visible in the VM (aggressive vacuums also
     visit all-visible-but-not-frozen pages). Prune dead tuples, defragment pages.
  2. Collect TIDs of dead tuples (PG17+: compact TidStore, no 1 GB cap on
     maintenance_work_mem; older versions could need several index passes).
  3. Remove those TIDs from EVERY index (index vacuuming). Can be skipped when
     few dead tuples exist (INDEX_CLEANUP AUTO, PG14+) or in failsafe mode.
  4. Mark the dead heap line pointers unused so space can be reused.
  5. Update the FSM and VM (all-visible / all-frozen bits), freeze old tuples,
     advance relfrozenxid, and truncate empty pages at the end of the file
     (takes a brief ACCESS EXCLUSIVE lock; disable with vacuum_truncate).

VACUUM doesn't block reads or writes (SHARE UPDATE EXCLUSIVE lock) and doesn't
shrink files except for that tail truncation. VACUUM FULL rewrites the table
under ACCESS EXCLUSIVE; pg_repack / pg_squeeze do it online.
```

**When autovacuum runs:**

```sql
-- Dead-tuple trigger:
--   n_dead_tup > autovacuum_vacuum_threshold (50)
--              + autovacuum_vacuum_scale_factor (0.2) × reltuples
--   capped by autovacuum_vacuum_max_threshold (PG18, default 100M)
--   1M rows → 200,050 dead tuples; 1B rows → 100M (PG18 cap) instead of 200M
-- Insert trigger (PG13+): inserts since last vacuum >
--   autovacuum_vacuum_insert_threshold (1000) + autovacuum_vacuum_insert_scale_factor (0.2) × reltuples
--   → append-only tables get their VM bits set and get frozen incrementally
-- Analyze trigger: changes > autovacuum_analyze_threshold (50) + autovacuum_analyze_scale_factor (0.1) × reltuples

-- Per-table tuning for a large, hot table:
ALTER TABLE orders SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold    = 10000,
    autovacuum_vacuum_cost_limit   = 2000
);
```

**Cost-based throttling:**

```c
// Each page costs: vacuum_cost_page_hit = 1, vacuum_cost_page_miss = 2 (was 10 before PG14),
// vacuum_cost_page_dirty = 20. After accumulating vacuum_cost_limit (200) points, sleep.
//
// Manual VACUUM:  vacuum_cost_delay = 0  → unthrottled by default
// Autovacuum:     autovacuum_vacuum_cost_delay = 2ms (PG12+; was 20ms), limit shared by all workers
//
// The default autovacuum budget is 200 units per 2ms ≈ 100,000 units/s, shared by all
// workers: roughly 800 MB/s of buffer hits, 400 MB/s of reads, or 40 MB/s of pages dirtied.
// Large busy tables often need a higher autovacuum_vacuum_cost_limit.
```

```sql
-- Manual vacuum in a maintenance window: already unthrottled; PARALLEL applies to index vacuuming
VACUUM (VERBOSE, PARALLEL 4) orders;
-- See progress:
SELECT relid::regclass, phase, heap_blks_scanned, heap_blks_total, index_vacuum_count
FROM pg_stat_progress_vacuum;
```

**XID wraparound:**

```sql
-- XIDs are 32-bit and compared modulo 2^31: anything more than ~2.1B transactions
-- old would look like it's in the future. Freezing marks old tuples as visible to everyone
-- (since 9.4 by setting HEAP_XMIN_FROZEN; xmin is kept for forensics).
--
-- Thresholds (defaults):
--   vacuum_freeze_min_age      50M   tuples older than this get frozen when vacuum visits them
--   vacuum_freeze_table_age    150M  a manual or auto VACUUM becomes aggressive
--   autovacuum_freeze_max_age  200M  forces an anti-wraparound autovacuum even if
--                                    autovacuum is disabled
--   vacuum_failsafe_age        1.6B  (PG14+) vacuum drops throttling and skips index cleanup
--   ~3M XIDs left                    server refuses new XIDs: no writes until vacuumed
--
-- PG18 "eager freezing": normal vacuums also freeze some all-visible pages
-- (vacuum_max_eager_freeze_failure_rate, default 0.03), spreading the work of
-- the next aggressive vacuum.

SELECT datname, age(datfrozenxid) AS xid_age, mxid_age(datminmxid) AS mxid_age
FROM pg_database ORDER BY 2 DESC;

SELECT c.oid::regclass AS table_name,
       age(c.relfrozenxid) AS xid_age,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS size
FROM pg_class c
WHERE c.relkind IN ('r', 'm', 't')
ORDER BY age(c.relfrozenxid) DESC
LIMIT 10;
```

What stops freezing (and cleanup) from making progress: long-running transactions, `idle in transaction` sessions, abandoned replication slots (`pg_replication_slots.xmin` / `catalog_xmin`), orphaned prepared transactions (`pg_prepared_xacts`), and `hot_standby_feedback` from a standby running long queries.

**Freeze tuning:**

```sql
-- Append-only tables: freeze EARLY so the eventual anti-wraparound vacuum has nothing to do.
-- Load with COPY ... (FREEZE) into a table created or truncated in the same transaction,
-- or run VACUUM (FREEZE) after a bulk load. PG13+ insert-triggered autovacuum helps too.

-- High-churn tables: let autovacuum freeze sooner (these are table storage parameters):
ALTER TABLE sessions SET (
    autovacuum_freeze_min_age   = 10000000,
    autovacuum_freeze_max_age   = 100000000,
    autovacuum_freeze_table_age = 80000000
);
-- Raising autovacuum_freeze_max_age toward 2B to "avoid" freezing only postpones it
-- and shrinks the safety margin.
```

### 4.5 HOT Updates (Heap-Only Tuples)

```
A HOT update happens when:
  1. no column used by a (non-summarising) index changed. Since PG16, changing a
     column indexed only by BRIN still allows HOT. AND
  2. the new version fits on the same heap page.

Then:
  - the new tuple is a "heap-only tuple": no index entry points to it
  - index entries still point to the chain's root line pointer; scans follow the chain
  - page pruning (during any access, not only VACUUM) removes dead chain members and turns
    the root into an LP_REDIRECT, so space is reclaimed without index vacuuming

Benefits: no index writes, much less WAL, less index bloat, cheaper vacuum.
Lever:    lower the table fillfactor (e.g. 80–90) on update-heavy tables so pages keep room.
Breakers: an index on a frequently updated column (updated_at, status, a counter),
          or pages that are already full.
```

```sql
ALTER TABLE accounts SET (fillfactor = 85);   -- applies to newly written pages

SELECT relname,
       n_tup_upd,
       n_tup_hot_upd,
       n_tup_newpage_upd,                       -- PG16+: updates that moved to another page
       round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 1) AS hot_pct
FROM pg_stat_user_tables
WHERE n_tup_upd > 0
ORDER BY n_tup_upd DESC;
```

---

## 5. WAL & Checkpoints

### 5.1 WAL Architecture

The rule: **a change's WAL record must be on durable storage before the changed data page is written**, and before the commit is acknowledged. Data pages are written later by the checkpointer, the bgwriter or an evicting backend. After a crash, replay from the last checkpoint's redo point recreates every committed change.

```
Backend modifies a page in shared_buffers
   │ (holding the buffer's content lock)
   ├─► builds a WAL record, reserves space (short spinlock),
   │   copies it into WAL buffers under one of 8 WAL-insertion locks (parallel)
   └─► stamps the page with the record's LSN (pd_lsn) and marks it dirty

COMMIT
   └─► append commit record, then flush WAL up to it (WALWriteLock serialises flushes;
       group commit: one fdatasync covers every backend waiting behind it)

Later: evicting or checkpointing a dirty page first ensures WAL ≥ pd_lsn is flushed.
```

- **LSN:** a 64-bit byte position in the WAL stream, shown as `16/B374D848`. `pg_current_wal_lsn()`, `pg_wal_lsn_diff()`.
- **Segments:** 16 MB files in `pg_wal/` (`initdb --wal-segsize` to change), recycled after checkpoints.
- **Record header (`XLogRecord`):** `xl_tot_len`, `xl_xid`, `xl_prev`, `xl_info`, `xl_rmid` (resource manager: heap, btree, gin, ...), `xl_crc`, followed by block references and data.
- Inspect it with `pg_waldump`, or `pg_walinspect` (PG15+) from SQL.

### 5.2 WAL Configuration

```ini
wal_level = replica              # minimal | replica (default) | logical (needed for logical decoding)
synchronous_commit = on          # per transaction: off/local/remote_write/on/remote_apply
wal_buffers = -1                 # auto: 1/32 of shared_buffers, max 16MB
wal_writer_delay = 200ms
wal_sync_method = fdatasync      # the default on Linux
full_page_writes = on            # keep on: protects against torn pages
wal_compression = zstd           # PG15+: compresses full-page images (lz4/pglz also available)
wal_log_hints = on               # needed by pg_rewind unless data checksums are enabled
summarize_wal = on               # PG17+: required for incremental base backups
# wal_init_zero / wal_recycle: turn off on copy-on-write filesystems (ZFS, btrfs)
```

### 5.3 Checkpoints

A checkpoint guarantees that every change before its **redo point** is in the data files, so recovery can start there and older WAL can be recycled.

```
Triggers:
  - checkpoint_timeout elapsed (default 5min)           → "timed"
  - WAL since last checkpoint approaching max_wal_size (default 1GB) → "requested"
  - CHECKPOINT command, shutdown, pg_basebackup start, CREATE DATABASE, ...

Sequence:
  1. Record the redo point (current insert LSN) FIRST.
  2. Write every buffer that was dirty at that moment, paced to finish within
     checkpoint_completion_target (default 0.9 since PG14) of the expected interval.
  3. fsync the data files.
  4. Write the checkpoint record; update pg_control.
  5. Remove/recycle WAL older than the redo point, unless retained by
     replication slots, wal_keep_size, or a lagging archiver.
```

```ini
checkpoint_timeout = 15min
max_wal_size = 16GB                 # large enough that most checkpoints are timed
min_wal_size = 2GB
checkpoint_completion_target = 0.9
checkpoint_warning = 30s            # log if requested checkpoints come closer than this
log_checkpoints = on                # default on since PG15
```

Monitoring (PG17+; on PG16 and earlier these columns were in `pg_stat_bgwriter`):

```sql
SELECT num_timed, num_requested, num_done,           -- num_done: PG18
       write_time, sync_time, buffers_written
FROM pg_stat_checkpointer;

-- Backend writes / fsyncs (formerly buffers_backend / buffers_backend_fsync):
SELECT backend_type, context, writes, fsyncs
FROM pg_stat_io
WHERE object = 'relation' AND backend_type = 'client backend';
```

Trade-off: longer intervals mean fewer full-page images and smoother I/O, but more WAL to replay after a crash (recovery time) and more disk in `pg_wal`.

### 5.4 Full Page Writes

```
On the FIRST modification of a page after a checkpoint, the WAL record carries a full
image of the page (FPI). Why: an 8 KB page is written as several smaller OS/disk
blocks; a crash mid-write leaves a "torn" page that redo records alone can't repair.
Replay starts from the FPI and applies later records on top.

Cost: right after each checkpoint, most records carry 8 KB images, so FPIs can be most
of the WAL volume. Check pg_stat_wal.wal_fpi vs wal_records, or pg_waldump --stats.

Reduce it with: fewer checkpoints (larger max_wal_size / checkpoint_timeout),
wal_compression, and fewer random-page writes (e.g. UUIDv7 instead of random UUID keys).

Turning full_page_writes off is only safe when the storage guarantees atomic 8 KB writes
(e.g. ZFS with recordsize ≥ 8K, which is copy-on-write). A battery-backed controller
cache doesn't prevent torn pages by itself.
```

---

## 6. Query Execution Pipeline

```
SQL text
  │
  ▼  Parser (scan.l + gram.y, a Bison LALR(1) grammar) → raw parse tree; syntax only
  ▼  Analyzer (parse_analyze) → Query tree: names resolved to OIDs, types and implicit
  │                             casts chosen, required permissions recorded
  ▼  Rewriter → views expanded, rules applied, row-level security quals added
  ▼  Planner/optimizer → cheapest Plan tree using statistics and cost constants
  ▼  Executor → pulls tuples through the plan tree (permission checks happen at executor start)
  ▼
Result rows
```

Prepared statements skip parse/analyze/rewrite on each execution, and can reuse a **generic plan** after five executions if it isn't estimated to be worse than the custom plans (`plan_cache_mode` controls this).

### 6.1 Parser

```c
// SELECT name FROM users WHERE age > 18
//
// SelectStmt
// ├── targetList:  [ResTarget(val = ColumnRef("name"))]
// ├── fromClause:  [RangeVar(relname = "users")]
// └── whereClause: A_Expr(kind = AEXPR_OP, name = ">",
//                         lexpr = ColumnRef("age"), rexpr = A_Const(18))
//
// The parser knows nothing about catalogs yet: "users" may not even exist.
```

### 6.2 Analyzer

```c
// Query
// ├── commandType: CMD_SELECT
// ├── rtable:      [RangeTblEntry(rtekind = RTE_RELATION, relid = <oid of users>)]
// ├── jointree:    FromExpr(fromlist = [RangeTblRef 1],
// │                         quals = OpExpr(opno = 521 /* int4 > int4 */,
// │                                        args = [Var(1, age), Const(18)]))
// └── targetList:  [TargetEntry(resno = 1, resname = "name", expr = Var(1, name))]
```

### 6.3 Rewriter

- Expands views into their defining queries (views are implemented as `ON SELECT` rules).
- Applies user-defined rules (`CREATE RULE`, rarely a good idea today).
- Adds row-level security policies as extra quals; `security_barrier` views stop the planner from evaluating leaky functions before those quals.

### 6.4 Planner / Optimizer

A **cost-based optimizer**: it enumerates scan paths and join orders, estimates rows from statistics and cost from cost constants, and keeps the cheapest paths (plus paths with useful sort orders). Join order is searched with dynamic programming up to `geqo_threshold` (12) FROM items, and with the genetic optimizer (GEQO) beyond that.

```sql
-- Table-level stats (pg_class): reltuples, relpages, relallvisible
-- Column stats (pg_statistic; readable via pg_stats), refreshed by ANALYZE:
--   null_frac, avg_width, n_distinct (negative = fraction of rows)
--   most_common_vals / most_common_freqs (MCV list, up to statistics_target entries)
--   histogram_bounds: EQUI-DEPTH buckets (each holds about the same number of rows)
--   correlation: physical vs logical order (-1..1); drives index-scan cost
-- Extended stats (CREATE STATISTICS; pg_stats_ext): dependencies, ndistinct, mcv, expressions
-- ANALYZE samples 300 × default_statistics_target rows (30,000 at the default 100)

-- Cost constants (defaults):
--   seq_page_cost = 1.0, random_page_cost = 4.0 (use ~1.1 on SSD/NVMe)
--   cpu_tuple_cost = 0.01, cpu_index_tuple_cost = 0.005, cpu_operator_cost = 0.0025
--   effective_cache_size: hint for how much of an index is likely cached
```

**Join strategies:**

| Join | How | Cost shape | Wins when |
|---|---|---|---|
| Nested loop | For each outer row, probe the inner (ideally by index) | ~outer × (index probe) | Small outer side, indexed inner; `LIMIT` queries |
| Hash join | Build a hash table on the smaller input, probe with the other | ~outer + inner; spills in batches beyond `work_mem × hash_mem_multiplier` | Large unsorted inputs, equality joins |
| Merge join | Walk two inputs sorted on the join key | ~outer + inner, plus sorts if not presorted | Inputs already ordered (indexes), or the output order is needed |

```
-> Nested Loop  (rows=5)
     -> Index Scan using users_pkey on users  (rows=5)
     -> Index Scan using idx_orders_user on orders  (rows=1 loops=5)   ← "loops" multiplies

-> Hash Join  (rows=6000)
     Hash Cond: (o.user_id = u.id)
     -> Seq Scan on orders o  (rows=6000)
     -> Hash  (rows=1000)  Buckets: 1024  Batches: 1  Memory Usage: 48kB
          -> Seq Scan on users u  (rows=1000)
```

**Collapse limits and GEQO (often confused):**

```ini
from_collapse_limit = 8    # subqueries in FROM are flattened into the parent only if the
                           # resulting FROM list has at most this many items
join_collapse_limit = 8    # explicit JOIN ... ON lists are reordered only up to this many
                           # items; set to 1 to make the planner follow your written JOIN order
geqo_threshold = 12        # at this many FROM items, switch from exhaustive search to GEQO
geqo = on                  # GEQO is randomised: plans can vary run to run
```

Raising the collapse limits above `geqo_threshold` just hands more joins to GEQO. For 15-way joins, keep the defaults and fix estimates, or deliberately set `join_collapse_limit = 1` and write the join order yourself ([Q6 below](#11-staff-level-interview-questions)).

### 6.5 Executor

```c
// Volcano-style pull model: each node implements
//   ExecInitNode  – set up state
//   ExecProcNode  – return the next tuple (NULL when done)
//   ExecEndNode   – release resources
// The parent pulls from its children, so Limit stops pulling once satisfied.
//
// Common nodes: SeqScan, IndexScan, IndexOnlyScan, BitmapHeapScan (+ BitmapIndexScan),
//   NestLoop / HashJoin / MergeJoin, Sort / IncrementalSort (PG13+), Agg (hashed, sorted,
//   mixed), WindowAgg, Limit, Materialize, Memoize (PG14+: caches inner results of a
//   nested loop), Gather / Gather Merge (parallel query), Append / MergeAppend (partitions),
//   LockRows (FOR UPDATE), ModifyTable (INSERT/UPDATE/DELETE/MERGE).
//
// JIT (LLVM, jit = on by default) compiles expressions and tuple deforming, but only
// for plans above jit_above_cost. It helps long analytical queries and can add
// tens of ms of compile time to OLTP queries with inflated cost estimates.
```

Reading `EXPLAIN (ANALYZE, BUFFERS)`: actual time is per loop (multiply by `loops`); compare `rows=` estimated vs actual at each node from the bottom up; `Buffers: shared hit/read` shows cache behaviour (PG18 includes BUFFERS automatically with ANALYZE).

---

## 7. Indexing In Depth

### 7.1 B-Tree Index

The default index type: a Lehman–Yao B+tree with high fan-out (hundreds of keys per 8 KB page) and right-links that let readers proceed through concurrent page splits.

```
                       ┌───────────────┐
                       │ meta page (0) │──► root block number
                       └───────────────┘
                     ┌─────────────────────┐
                     │ root:  [ 50 | 200 ] │
                     └──┬────────┬────────┬┘
              ┌─────────┘        │        └──────────┐
       ┌──────▼──────┐    ┌──────▼──────┐     ┌──────▼──────┐
       │ [ 10 | 30 ] │    │ [ 90 | 150 ]│     │ [250 | 400] │   internal pages
       └─┬────┬────┬─┘    └─┬────┬────┬─┘     └─┬────┬────┬─┘
         ▼    ▼    ▼        ▼    ▼    ▼         ▼    ▼    ▼
       leaf pages: (key → heap TID) ... ◄──► doubly linked for range scans in either direction
```

- **Search:** ~3–4 page reads for a billion rows, and the upper levels are almost always cached.
- **Splits:** a full page splits roughly 50/50, except for the rightmost page under ascending inserts, which is split so the left page stays `fillfactor` full (default 90). Monotonic keys therefore pack densely. **Suffix truncation** (PG12+) keeps internal keys short.
- **Deduplication** (PG13+): equal keys are stored once with a posting list of TIDs, which shrinks low-cardinality indexes a lot.
- **Bottom-up deletion** (PG14+): before splitting a page because of version churn from non-HOT updates, the index deletes entries it can prove are dead, which limits update-driven bloat.
- **Dead entries:** an index scan that finds a dead heap tuple marks the entry `LP_DEAD` so later scans skip it; VACUUM removes entries in bulk.
- **Skip scan** (PG18+): a multicolumn index `(a, b)` can serve `WHERE b = ?` when `a` has few distinct values, by probing once per value of `a`.

```sql
-- fillfactor on an index reduces page splits for random inserts; on a TABLE it leaves
-- room for HOT updates. They are different settings.
CREATE INDEX idx_users_email ON users (email) WITH (fillfactor = 80);

-- Covering index: INCLUDE columns sit in leaves only (not usable for search or order),
-- enabling index-only scans for queries that also need amount and status.
CREATE INDEX idx_orders_user_date ON orders (user_id, created_at) INCLUDE (amount, status);

-- Multicolumn order: equality columns first, then the range/sort column
--   WHERE user_id = ? AND created_at > ? ORDER BY created_at   → (user_id, created_at)
```

### 7.2 GiST Index

The Generalized Search Tree is a framework for balanced trees whose internal entries are *predicates that cover their children*: bounding boxes for geometry, union ranges for range types. It's lossy, so heap rows are rechecked.

```
Uses: PostGIS geometry/geography, range types, exclusion constraints,
      nearest-neighbour ordering (ORDER BY location <-> point LIMIT 10), inet,
      full-text (GIN is usually better), pg_trgm similarity.
Search: descend every child whose covering predicate is consistent with the query; prune others.
```

```sql
-- PostGIS: venues within 5 km (geography uses metres; ST_MakePoint takes lon, lat)
CREATE INDEX idx_venues_geo ON venues USING gist (location);   -- location geography(Point, 4326)
SELECT id, name FROM venues
WHERE ST_DWithin(location, ST_MakePoint(-74.0060, 40.7128)::geography, 5000);

-- Range types: overlapping bookings
CREATE INDEX idx_booking_period ON bookings USING gist (booking_period);
SELECT * FROM bookings WHERE booking_period && tstzrange('2026-06-01', '2026-06-08');

-- Exclusion constraint: no two bookings of the same room may overlap
CREATE EXTENSION IF NOT EXISTS btree_gist;     -- lets GiST handle the scalar room_id with =
ALTER TABLE bookings ADD CONSTRAINT no_double_booking
    EXCLUDE USING gist (room_id WITH =, booking_period WITH &&);
-- PG18 also offers temporal keys: PRIMARY KEY (room_id, booking_period WITHOUT OVERLAPS)
```

### 7.3 GIN Index

The Generalized Inverted Index maps each **key** (lexeme, array element, JSON key/value) to the set of rows containing it.

```
            entry tree (a B-tree over keys)
        ┌──────────────┬──────────────┬──────────────┐
        │ "index"      │ "postgres"   │ "vacuum"     │   ...
        └──────┬───────┴──────┬───────┴──────┬───────┘
               ▼              ▼              ▼
        posting list    posting TREE     posting list       ← sorted, compressed TIDs;
        (3 TIDs)        (millions of     (12 TIDs)            a B-tree once too big
                         TIDs)                                for one page
        + pending list (fastupdate): recent inserts kept unsorted, merged in bulk
```

- **Reads:** look up each query key, then intersect/union the TID sets. Fast for "contains these words or keys".
- **Writes:** one row can produce dozens of keys, so each insert touches many posting lists. With `fastupdate = on` (default), new entries go to a **pending list** that is merged when it exceeds `gin_pending_list_limit` (4 MB) or by VACUUM/ANALYZE. Inserts get cheaper; searches must also scan the pending list, and the merge causes occasional latency spikes.

```sql
-- Full-text search (to_tsvector with an explicit config is immutable, so it can be indexed)
CREATE INDEX idx_docs_fts ON documents
    USING gin (to_tsvector('english', title || ' ' || body));

-- JSONB: jsonb_path_ops supports @>, @?, @@ only and is smaller and faster;
--        the default jsonb_ops also supports key existence ?, ?|, ?&
CREATE INDEX idx_profiles_meta ON profiles USING gin (metadata jsonb_path_ops);

-- Arrays
CREATE INDEX idx_tags ON articles USING gin (tags);       -- tags @> ARRAY['postgres']

-- Substring search (LIKE '%term%') via trigrams
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_users_name_trgm ON users USING gin (name gin_trgm_ops);

-- Pending-list tuning; the storage parameter is in kB (no unit suffix)
CREATE INDEX idx_fts ON documents USING gin (fts)
    WITH (fastupdate = on, gin_pending_list_limit = 4096);
```

### 7.4 BRIN Index

The Block Range Index stores a small summary (by default min/max) per range of `pages_per_range` heap pages (default 128).

```
Heap pages:  P0  P1  P2  P3 │ P4  P5  P6  P7 │ P8  P9
             jan jan jan jan│ feb feb feb feb│ mar mar

BRIN (pages_per_range = 4):
  range 0 (P0–P3): min Jan-01, max Jan-31
  range 1 (P4–P7): min Feb-01, max Feb-28
  range 2 (P8–P9): min Mar-01, max Mar-31

WHERE created_at = 'Feb-15' → only range 1 can match → read P4–P7, recheck rows.
```

- **Size:** one summary per range. A 1 TB table at 128 pages/range has ~1M ranges, so the index is tens of MB. A B-tree on the same column is typically tens to hundreds of GB.
- **Requires physical correlation** between the column and row placement (`pg_stats.correlation` near ±1). Append-only time series is the ideal case. Updates, and inserts that reuse space mid-table, erode it.
- Results are lossy (a bitmap of candidate pages), so BRIN suits queries that read a meaningful fraction of the table, not single-row lookups.

```sql
CREATE INDEX idx_events_created ON events USING brin (created_at)
    WITH (pages_per_range = 32, autosummarize = on);   -- summarise new ranges as the table grows

-- PG14+: minmax-multi keeps several min/max intervals per range, so a few out-of-order
-- rows (late-arriving events) don't widen every range
CREATE INDEX idx_events_created_mm ON events
    USING brin (created_at timestamptz_minmax_multi_ops);

-- PG14+: bloom summaries for equality on columns with no physical order
CREATE INDEX idx_events_device_bloom ON events USING brin (device_id int8_bloom_ops);
```

### 7.5 Index Selection Guide

| Workload | Recommended Index | Why |
|----------|------------------|-----|
| Primary key / equality lookups | B-tree | Equality, ranges, ordering and uniqueness in one structure |
| Range on an append-only timestamp | BRIN | Tiny, near-zero write cost; needs physical correlation |
| Range on a timestamp with random arrival, or `ORDER BY ... LIMIT` | B-tree | BRIN degrades without correlation and can't return rows in order |
| Full-text search | GIN on `tsvector` | Inverted index over lexemes |
| JSONB containment (`@>`) | GIN `jsonb_path_ops` | Smaller and faster than `jsonb_ops`, but no `?` operators |
| One hot JSON field | B-tree expression index `((doc->>'status'))` | Cheaper than GIN, supports ranges and sorting |
| `LIKE '%term%'` | GIN or GiST with `pg_trgm` | Trigram matching |
| Geospatial, nearest neighbour | GiST (PostGIS) | Bounding-box tree, `<->` ordering |
| No-overlap rules | GiST exclusion constraint / PG18 `WITHOUT OVERLAPS` | Enforces non-overlapping ranges |
| Hot subset (`status = 'pending'`) | Partial B-tree | Indexes only the rows queries want |
| Insert-heavy surrogate keys | `bigint` identity or **UUIDv7** (`uuidv7()`, PG18) | Time-ordered keys append at the right edge; random UUIDv4 scatters inserts across the whole index |

---

## 8. Partitioning & Sharding

### 8.1 Declarative Partitioning (PG10+)

```sql
-- Range partitioning (most common: time)
CREATE TABLE measurements (
    log_time  timestamptz NOT NULL,
    sensor_id int NOT NULL,
    value     double precision NOT NULL
) PARTITION BY RANGE (log_time);

CREATE TABLE measurements_2026_01 PARTITION OF measurements
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE measurements_2026_02 PARTITION OF measurements
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE measurements_default PARTITION OF measurements DEFAULT;  -- catches stray rows

-- List partitioning
CREATE TABLE customers (id bigint, name text, region text NOT NULL) PARTITION BY LIST (region);
CREATE TABLE customers_na PARTITION OF customers FOR VALUES IN ('US', 'CA', 'MX');
CREATE TABLE customers_eu PARTITION OF customers FOR VALUES IN ('UK', 'DE', 'FR', 'IT');

-- Hash partitioning (spreads write load; no pruning for ranges)
CREATE TABLE users_partitioned (user_id bigint NOT NULL, name text) PARTITION BY HASH (user_id);
CREATE TABLE users_p0 PARTITION OF users_partitioned FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE users_p1 PARTITION OF users_partitioned FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE users_p2 PARTITION OF users_partitioned FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE users_p3 PARTITION OF users_partitioned FOR VALUES WITH (MODULUS 4, REMAINDER 3);

-- Sub-partitioning
CREATE TABLE logs (log_date date NOT NULL, log_level text NOT NULL, message text)
    PARTITION BY RANGE (log_date);
CREATE TABLE logs_2026 PARTITION OF logs
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')
    PARTITION BY LIST (log_level);
CREATE TABLE logs_2026_error PARTITION OF logs_2026 FOR VALUES IN ('ERROR', 'FATAL');
CREATE TABLE logs_2026_other PARTITION OF logs_2026 DEFAULT;
```

**Benefits:**

- **Pruning** at plan time (constants) and at execution time (parameters, joins; PG11+), so queries touch only relevant partitions.
- **Retention without DELETE:** `ALTER TABLE measurements DETACH PARTITION measurements_2026_01 CONCURRENTLY;` (PG14+), then `DROP TABLE`. There's no vacuum debt and no bloat.
- **Smaller per-partition indexes and vacuums**; hot recent partitions stay cached.
- **Partitionwise join and aggregate** (PG11+, off by default: `enable_partitionwise_join`, `enable_partitionwise_aggregate`) when both sides are partitioned the same way.

**Gotchas:**

```sql
-- 1. Unique constraints and primary keys must include the partition key:
--      UNIQUE (email)            -- ERROR on a table partitioned by user_id
--      UNIQUE (user_id, email)   -- OK
--    Global uniqueness of email needs a separate lookup table.

-- 2. Row triggers and indexes defined on the parent are cloned to every partition
--    (indexes PG11+, row triggers PG11+, BEFORE row triggers PG13+), including future ones.

-- 3. Autovacuum processes each partition, never the parent, and doesn't ANALYZE the parent,
--    so run ANALYZE on the parent periodically for plans that use whole-table statistics.
--    Autovacuum storage parameters must be set per partition:
ALTER TABLE measurements_2026_01 SET (autovacuum_vacuum_scale_factor = 0.01);

-- 4. Too many partitions hurts: planning time and per-query locks grow with the number of
--    partitions not pruned at plan time. Before PG18, touching >16 relations falls off the
--    fast-path lock slots. Hundreds of partitions are fine; tens of thousands are not.

-- 5. Every query should filter on the partition key, or it scans all partitions.
--    Create future partitions ahead of time (pg_partman or a cron job), and alert on rows
--    landing in the DEFAULT partition.
```

### 8.2 Sharding via Foreign Data Wrappers (FDW)

Core PostgreSQL has no built-in sharding, but `postgres_fdw` foreign tables can be **partitions** of a local partitioned table. That gives routing and pruning, with significant limits.

```sql
CREATE EXTENSION postgres_fdw;
CREATE SERVER shard1 FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'shard1.internal', port '5432', dbname 'appdb', async_capable 'true');
CREATE SERVER shard2 FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'shard2.internal', port '5432', dbname 'appdb', async_capable 'true');

CREATE USER MAPPING FOR app_user SERVER shard1 OPTIONS (user 'shard_user', password '...');
CREATE USER MAPPING FOR app_user SERVER shard2 OPTIONS (user 'shard_user', password '...');

CREATE TABLE users_global (
    user_id bigint NOT NULL,
    name    text   NOT NULL,
    email   text
) PARTITION BY HASH (user_id);

CREATE FOREIGN TABLE users_s0 PARTITION OF users_global
    FOR VALUES WITH (MODULUS 2, REMAINDER 0)
    SERVER shard1 OPTIONS (schema_name 'public', table_name 'users');
CREATE FOREIGN TABLE users_s1 PARTITION OF users_global
    FOR VALUES WITH (MODULUS 2, REMAINDER 1)
    SERVER shard2 OPTIONS (schema_name 'public', table_name 'users');

-- Single-shard queries are pruned to one remote; multi-shard scans run in parallel
-- with async Append (PG14+).
```

Limits: no atomic commit across shards (postgres_fdw has no two-phase commit), no global unique constraints, limited pushdown of joins and aggregates across shards, and moving data between shards is manual. Treat it as a building block, not a sharding product.

**Production options for scaling out:**

- **Citus** (open source, Microsoft): distributed tables by a distribution column, co-located joins, reference tables, shard rebalancer, and schema-based sharding (Citus 12+) for schema-per-tenant designs. Offered on Azure as Azure Cosmos DB for PostgreSQL.
- **Application-level sharding:** a directory maps tenant or user to cluster, with independent PostgreSQL clusters per shard (see [the sharding question](INTERVIEW_QUESTIONS.md#7-sharding-strategies)).
- **Distributed SQL with a PostgreSQL interface:** CockroachDB, YugabyteDB, Spanner (PostgreSQL dialect), Aurora Limitless. Check compatibility gaps carefully.
- `pg_partman` is a *partition-management* tool (creating future partitions and enforcing retention), not a sharding layer.

---

## 9. Performance Tuning

### 9.1 Configuration Checklist

Starting points for a dedicated 32 GB / 8-core host on SSD. Measure before and after each change.

```ini
# ── MEMORY ─────────────────────────────────────────────────
shared_buffers = 8GB                   # ~25% of RAM (restart required)
effective_cache_size = 24GB            # planner hint only
work_mem = 32MB                        # per sort/hash node; raise per role for analytics
maintenance_work_mem = 1GB             # VACUUM, CREATE INDEX
autovacuum_work_mem = -1               # -1 = use maintenance_work_mem
huge_pages = try

# ── PARALLELISM ────────────────────────────────────────────
max_worker_processes = 16              # pool for parallel workers, logical replication, extensions
max_parallel_workers = 8               # cap on parallel query workers overall
max_parallel_workers_per_gather = 4
max_parallel_maintenance_workers = 4   # parallel CREATE INDEX / VACUUM index phase

# ── I/O (PG18) ─────────────────────────────────────────────
io_method = worker                     # default; io_uring on Linux builds with liburing
effective_io_concurrency = 16          # PG18 default (was 1)

# ── WAL / CHECKPOINTS ──────────────────────────────────────
wal_level = replica
max_wal_size = 16GB
min_wal_size = 2GB
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9
wal_compression = zstd

# ── PLANNER ────────────────────────────────────────────────
random_page_cost = 1.1                 # SSD/NVMe
default_statistics_target = 100        # raise per column where estimates are bad

# ── CONNECTIONS / SAFETY ───────────────────────────────────
max_connections = 200                  # keep low; pool in front
idle_in_transaction_session_timeout = '5min'
lock_timeout = 0                       # set per session for migrations instead
# statement_timeout and transaction_timeout (PG17): set per role, not globally

# ── AUTOVACUUM ─────────────────────────────────────────────
autovacuum_max_workers = 5             # concurrent workers (PG18: change at runtime ≤ autovacuum_worker_slots)
autovacuum_naptime = 15s
autovacuum_vacuum_scale_factor = 0.05
autovacuum_vacuum_insert_scale_factor = 0.05
autovacuum_analyze_scale_factor = 0.05
autovacuum_vacuum_cost_limit = 2000    # default -1 → vacuum_cost_limit (200) shared by workers
autovacuum_vacuum_cost_delay = 2ms

# ── LOGGING ────────────────────────────────────────────────
logging_collector = on
log_min_duration_statement = 1000      # log statements slower than 1s
log_autovacuum_min_duration = '10s'
log_checkpoints = on
log_lock_waits = on                    # log waits longer than deadlock_timeout
log_temp_files = 0                     # every spill to disk
log_connections = on                   # PG18 also accepts a list, e.g. 'receipt,authentication'
log_line_prefix = '%m [%p] %q%u@%d '
```

### 9.2 Index Maintenance

```sql
-- Unused indexes: check the primary AND every replica (stats are per server),
-- and how long stats have been accumulating
SELECT s.relid::regclass AS table_name,
       s.indexrelid::regclass AS index_name,
       s.idx_scan,
       s.last_idx_scan,                                   -- PG16+
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE NOT i.indisunique                                   -- unique indexes enforce constraints
ORDER BY s.idx_scan, pg_relation_size(s.indexrelid) DESC;

-- Exact duplicates: same table, columns, opclasses, options, expressions and predicate
SELECT a.indrelid::regclass AS table_name,
       a.indexrelid::regclass AS index_a,
       b.indexrelid::regclass AS index_b,
       pg_size_pretty(pg_relation_size(b.indexrelid)) AS droppable_size
FROM pg_index a
JOIN pg_index b ON a.indrelid = b.indrelid
               AND a.indexrelid < b.indexrelid
               AND a.indkey = b.indkey
               AND a.indclass = b.indclass
               AND a.indoption = b.indoption
               AND a.indcollation = b.indcollation
               AND coalesce(pg_get_expr(a.indexprs, a.indrelid), '') = coalesce(pg_get_expr(b.indexprs, b.indrelid), '')
               AND coalesce(pg_get_expr(a.indpred, a.indrelid), '') = coalesce(pg_get_expr(b.indpred, b.indrelid), '');
-- Also look for prefixes: (a) is usually redundant next to (a, b), unless (a) is unique.

-- Bloat: measure, don't guess (pgstattuple extension)
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT avg_leaf_density, leaf_fragmentation FROM pgstatindex('idx_users_email');
-- A fresh B-tree is ~90% dense; well below ~50% suggests rebuilding

-- Rebuild online (PG12+); needs disk space for a second copy
REINDEX INDEX CONCURRENTLY idx_users_email;
REINDEX TABLE CONCURRENTLY users;
-- A failed concurrent build leaves an INVALID index: find (pg_index.indisvalid = false) and drop it
```

### 9.3 Query Performance Monitoring

```sql
-- pg_stat_statements: add to shared_preload_libraries, then CREATE EXTENSION
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Top statements by total time (what to optimise first)
SELECT queryid,
       left(query, 80) AS query_preview,
       calls,
       round(total_exec_time::numeric, 0) AS total_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(stddev_exec_time::numeric, 2) AS stddev_ms,
       rows,
       round(100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0), 2) AS hit_pct,
       temp_blks_written,
       pg_size_pretty(wal_bytes) AS wal
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;

-- Heaviest I/O per call
SELECT queryid, left(query, 80) AS query_preview, calls,
       shared_blks_read / nullif(calls, 0) AS blks_read_per_call,
       temp_blks_written / nullif(calls, 0) AS temp_blks_per_call
FROM pg_stat_statements
WHERE calls > 100
ORDER BY shared_blks_read DESC
LIMIT 20;

-- Reset to start a new baseline
SELECT pg_stat_statements_reset();
```

Also enable `track_io_timing = on` (cheap on modern Linux; check with `pg_test_timing`) so I/O time appears in `EXPLAIN (ANALYZE, BUFFERS)` and pg_stat_statements, and use `auto_explain` (`auto_explain.log_min_duration`) to capture plans of slow statements as they happen.

### 9.4 Wait Event Analysis

```sql
-- What is each session waiting on right now?
SELECT pid, backend_type, state, wait_event_type, wait_event,
       now() - query_start AS query_age,
       now() - xact_start  AS xact_age,
       left(query, 100) AS query
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
ORDER BY xact_start NULLS LAST;

-- Sample this every second into a table (or use pg_wait_sampling / your APM) to get
-- a wait-time profile: "40% IO:DataFileRead, 30% LWLock:WALWrite, ..."
```

| `wait_event_type` | Meaning | Typical events and what they suggest |
|---|---|---|
| (NULL, state `active`) | Running on CPU | Bad plans, too much concurrency |
| `IO` | Waiting for a read, write or fsync | `DataFileRead` (cache misses), `WALSync`/`WALWrite` (commit latency, slow WAL disk), `AioIoCompletion` (PG18 async I/O) |
| `Lock` | Heavyweight lock | `transactionid` (waiting for a row's locker to finish), `tuple`, `relation` (DDL), `extend` (relation extension contention) |
| `LWLock` | Internal lightweight lock | `LockManager` (fast-path overflow), `BufferMapping`, `WALInsert`, `SubtransSLRU` (too many savepoints), `MultiXact*` |
| `IPC` | Waiting for another process | `SyncRep` (waiting for synchronous standby acks), parallel-query coordination |
| `Client` | Waiting for the client | `ClientRead` while `idle in transaction`: the app is holding a transaction open |
| `Timeout` | Sleeping deliberately | `VacuumDelay` (cost-based throttling), `PgSleep` |
| `Activity` | Background process idle in its main loop | Normal: `CheckpointerMain`, `AutovacuumMain` |

Since PG17, `pg_wait_events` lists every event with a description: `SELECT * FROM pg_wait_events WHERE name = 'SyncRep';`.

---

## 10. Production Operations

### 10.1 High Availability with Patroni

Patroni runs next to each PostgreSQL node and uses a **DCS** (distributed configuration store: etcd, Consul, ZooKeeper or the Kubernetes API) to hold a leader lock with a TTL. Only the node holding the lock runs as primary.

```
              ┌────────────── etcd (3 or 5 members) ──────────────┐
              │  /service/pg/leader = pg-1  (TTL 30s)              │
              └───────▲────────────────▲────────────────▲──────────┘
                      │ renew lock     │ watch          │ watch
              ┌───────┴──────┐  ┌──────┴───────┐  ┌─────┴────────┐
              │ Patroni pg-1 │  │ Patroni pg-2 │  │ Patroni pg-3 │
              │ PRIMARY      │─►│ sync standby │  │ async standby│
              │ (AZ a)       │─►│ (AZ b)       │  │ (AZ c)       │
              └──────────────┘  └──────────────┘  └──────────────┘
                      ▲ routing: HAProxy health checks on Patroni's REST API
                      │ (/primary, /replica), a Kubernetes service, or
                      │ libpq target_session_attrs=read-write
                 applications ──► PgBouncer
```

- **Failover:** if the leader stops renewing (crash, partition), standbys race for the lock; Patroni promotes the healthiest one and, in `synchronous_mode`, only a synchronous standby (no lost commits). Typical RTO is 10–40 s, driven by `ttl` and `loop_wait`.
- **Split-brain protection:** a primary that can't renew the lock **demotes itself**. A watchdog (`/dev/watchdog`) resets the machine if Patroni itself hangs.
- **Rejoin:** the old primary is rewound with `pg_rewind` (needs `wal_log_hints` or data checksums) and follows the new leader.
- **Operations:** `patronictl switchover` for planned maintenance, `patronictl edit-config` for cluster-wide parameters, and rolling restarts.
- Kubernetes operators (CloudNativePG, Crunchy PGO, Zalando's operator) package the same ideas.

### 10.2 Backup & Recovery

**Logical backups (pg_dump):** a consistent snapshot of one database, portable across versions and architectures. It's slow to restore at scale (indexes are rebuilt) and has no point-in-time recovery. Use it for migrations and small databases; it's not the primary backup for large ones.

```bash
pg_dump -h db -U app -d mydb -Fc -f mydb.dump                 # custom format (compressed)
pg_dump -h db -U app -d mydb -Fd -j 8 -f mydb_dir/            # directory format, parallel dump
pg_restore -h db2 -U app -d mydb -j 8 mydb_dir/               # parallel restore
pg_dump -h db -U app -d mydb -t public.users -t public.orders -Fc -f partial.dump
pg_dumpall --globals-only > globals.sql                       # roles and tablespaces (not in pg_dump)
```

**Physical backups + WAL archiving = point-in-time recovery (PITR):**

```bash
# postgresql.conf on the primary
#   archive_mode = on
#   archive_command = 'pgbackrest --stanza=main archive-push %p'   # or archive_library (PG15+)

# Base backup (streams the WAL needed to make it consistent)
pg_basebackup -h primary -D /backups/base -X stream -c fast -P

# PG17+: incremental backups (needs summarize_wal = on)
pg_basebackup -h primary -D /backups/incr1 --incremental=/backups/base/backup_manifest
pg_combinebackup /backups/base /backups/incr1 -o /restore/data   # rebuild a full data directory

# Restore to a point in time (PG12+: settings in postgresql.conf + a recovery.signal file)
#   restore_command = 'pgbackrest --stanza=main archive-get %f "%p"'
#   recovery_target_time = '2026-06-15 14:30:00+00'
#   recovery_target_action = 'promote'          # promote automatically when the target is reached
touch /restore/data/recovery.signal
pg_ctl -D /restore/data start
```

**pgBackRest** is the most widely used dedicated tool: parallel and compressed backup and restore, full/differential/incremental (block-level) backups, resume of interrupted backups, encryption, S3/GCS/Azure repositories, `verify`, and `--delta` restore. (In April 2026 its maintainer archived the project for lack of funding; a sponsor coalition revived it in May 2026, so it's maintained again.) Barman and WAL-G are the main alternatives. Managed services (RDS, Cloud SQL, Azure) do this for you, but you still own **restore testing**.

```ini
# /etc/pgbackrest/pgbackrest.conf
[global]
repo1-type=s3
repo1-path=/pgbackrest
repo1-s3-bucket=company-pg-backups
repo1-s3-endpoint=s3.us-east-1.amazonaws.com
repo1-s3-region=us-east-1
repo1-retention-full=4
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=<from a secret store>
process-max=8
compress-type=zst

[main]
pg1-path=/var/lib/postgresql/18/main
```

```bash
pgbackrest --stanza=main --type=full backup     # weekly
pgbackrest --stanza=main --type=diff backup     # daily
pgbackrest --stanza=main --type=incr backup     # hourly
pgbackrest --stanza=main --type=time --target="2026-06-15 14:30:00+00" \
           --target-action=promote --delta restore
```

The only proof a backup works is a restore. Automate a restore to a scratch host on a schedule, start it, run checks, and track the time it took (that's your real RTO).

### 10.3 Monitoring & Alerting

```sql
-- 1. Replication lag (on the primary)
SELECT application_name, client_addr, state, sync_state,
       write_lag, flush_lag, replay_lag,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS replay_lag_bytes
FROM pg_stat_replication;

-- 2. Replication slots retaining WAL (an inactive slot fills the disk)
SELECT slot_name, slot_type, active, wal_status,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
-- Cap it with max_slot_wal_keep_size; PG18 adds idle_replication_slot_timeout

-- 3. Connection usage
SELECT count(*) FILTER (WHERE backend_type = 'client backend') AS client_conns,
       current_setting('max_connections')::int AS max_conns,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_xact
FROM pg_stat_activity;

-- 4. Dead tuples and vacuum recency
SELECT relid::regclass AS table_name,
       n_live_tup, n_dead_tup,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum, last_autoanalyze, n_mod_since_analyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;

-- 5. Oldest transactions (they hold back vacuum everywhere)
SELECT pid, state, now() - xact_start AS xact_age, backend_xmin,
       wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers,
       left(query, 100) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL AND pid <> pg_backend_pid()
ORDER BY xact_start
LIMIT 20;
```

### 10.4 Golden Signals for PostgreSQL

```yaml
Latency:
  - p50/p99 statement latency by queryid (pg_stat_statements deltas, or APM)
  - commit latency (WAL fsync; IO/WALSync waits)
  - replication lag (bytes and seconds)

Traffic:
  - transactions/s (pg_stat_database xact_commit + xact_rollback deltas)
  - rows read/written, WAL bytes/s (pg_stat_wal)
  - new connections/s

Errors:
  - rollbacks, deadlocks (pg_stat_database.deadlocks), serialization failures (40001)
  - connection refusals, "out of shared memory", statement/lock timeouts
  - checksum failures (pg_stat_database.checksum_failures)

Saturation:
  - CPU, disk latency and IOPS, network
  - active sessions vs cores; wait-event profile
  - XID and MultiXact age vs autovacuum_freeze_max_age
  - disk: data, pg_wal, slot retention, archive backlog (pg_stat_archiver.failed_count)
  - autovacuum: workers busy constantly, tables with growing n_dead_tup
```

---

## 11. Staff-Level Interview Questions

### Q1: "Design a horizontally scalable PostgreSQL architecture for a SaaS platform with 10K tenants, each with up to 1GB of data. Compare and contrast multi-tenant strategies."

**What They're Really Testing:** Whether you can trade isolation against operational cost, and size a design to the numbers given (10K tenants, ~10 TB total, skewed tenant sizes).

!!! tip "30-second answer"
    At 10K mostly small tenants, use **shared tables with a `tenant_id` column** leading every primary key and index, enforced by row-level security, and shard **by tenant** across a handful of PostgreSQL clusters using a tenant → shard directory. Schema-per-tenant at 10K tenants means hundreds of thousands of tables: catalog bloat, slow migrations and per-backend cache memory. Database-per-tenant multiplies connections and operations. Give the few largest or regulated tenants **dedicated shards** (the same code with a different directory entry). Citus automates the distribution if you'd rather not build the routing layer.

**Option 1: Database (or cluster) per tenant**

| Pros | Cons |
|---|---|
| Strongest isolation (noisy neighbours, blast radius, per-tenant restore and encryption keys) | Connections: a pooler pool per database; 10K databases × N connections doesn't fit |
| Per-tenant tuning, versions, maintenance windows | 10K migrations per release; fleet tooling needed |
| Easy per-tenant export and deletion | Monitoring, backups and upgrades × 10K; poor utilisation for 1 GB tenants |

*Fits:* tens to hundreds of large or regulated tenants.

**Option 2: Schema per tenant**

```sql
CREATE SCHEMA tenant_123;
CREATE TABLE tenant_123.orders (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, amount numeric);
-- per request (transaction pooling): SET LOCAL search_path = tenant_123;
```

| Pros | Cons |
|---|---|
| Logical isolation; per-tenant dump/restore (`pg_dump -n`) | 10K schemas × 50 tables = 500K tables plus their indexes: huge `pg_class`, slow `pg_dump`, catalog caches bloating every backend's memory |
| No `tenant_id` in queries | Each migration runs 10K times; partial failures leave schemas on different versions |
| Shared server resources | No isolation of CPU/IO; `search_path` mistakes leak data |

*Fits:* tens to low thousands of tenants. Citus 12+ schema-based sharding can distribute schemas across nodes.

**Option 3: Shared tables, `tenant_id` column + row-level security**

```sql
CREATE TABLE orders (
    tenant_id  bigint NOT NULL,
    id         bigint GENERATED ALWAYS AS IDENTITY,
    amount     numeric NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)                  -- tenant first: every lookup is tenant-scoped
);
CREATE INDEX ON orders (tenant_id, created_at DESC);

ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE ROW LEVEL SECURITY;     -- applies to the table owner too
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = current_setting('app.tenant_id')::bigint)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::bigint);

-- Per transaction (safe with PgBouncer transaction pooling):
BEGIN;
SELECT set_config('app.tenant_id', '123', true);   -- true = local to this transaction
SELECT * FROM orders WHERE created_at > now() - interval '7 days';
COMMIT;
```

| Pros | Cons |
|---|---|
| One schema, one migration, efficient resource use | Noisy neighbours: one tenant's heavy query affects others (mitigate with per-tenant rate limits, statement timeouts, moving whales) |
| Scales to 100K+ tenants | Isolation depends on discipline: RLS policies, `tenant_id` in every key; superusers and `BYPASSRLS` roles skip RLS |
| Cross-tenant analytics are easy | Per-tenant restore means extracting rows, not restoring a database |

**Recommendation for 10K tenants × ≤1 GB (~10 TB, skewed):**

```
                 ┌───────────────────────────────┐
request ───────► │ router: tenant_id → shard     │  directory in a small control-plane DB,
(tenant 123)     │ (cached, versioned)           │  cached in the app; not hash(tenant) % N
                 └──────┬───────────┬────────────┘
                        ▼           ▼            ▼
                  shard-01      shard-02  ...  shard-dedicated-acme
                  (~2–3 TB,     Patroni HA,    (one big tenant)
                   ~2.5K        PgBouncer,
                   tenants)     pgBackRest
```

- **Shard count from capacity:** ~10 TB across 4–6 shards of 2–3 TB keeps each shard's restore and `pg_upgrade` within hours, with headroom to grow.
- **Directory, not modulo:** moving one tenant is a directory update after copying its rows (logical replication with a row filter `WHERE (tenant_id = 123)`, PG15+, or export/import), with no global rehash.
- **Whales and compliance:** dedicated shards via the same directory.
- **Schema migrations:** one schema per shard, rolled out shard by shard with canaries.
- **Off-the-shelf alternative:** Citus with `orders` distributed by `tenant_id` gives co-located joins and online shard moves.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Trade-offs** | Quantifies isolation vs operational cost for each model at 10K tenants |
| **Catalog scale** | Knows schema-per-tenant breaks on catalog size and migration count |
| **RLS correctness** | `FORCE`, `WITH CHECK`, transaction-local settings with poolers, bypass roles |
| **Sharding** | Directory-based tenant placement, whale isolation, tenant moves |

---

### Q2: "A PostgreSQL INSERT that takes 1ms suddenly takes 5 seconds. The table has 1 billion rows, 10 indexes, and receives 50K writes/second. Walk through your debugging process."

**What They're Really Testing:** A systematic, evidence-driven triage (wait events first, theories second) and knowledge of the specific things that make inserts slow.

!!! tip "30-second answer"
    A 5,000× jump is almost always **waiting**, not doing more work, so start with what the slow INSERTs are waiting on. `Lock:transactionid` means a **unique-index conflict** with an uncommitted insert of the same key, or a foreign-key check on a parent row another transaction holds. `Lock:extend` means relation-extension contention. `LWLock:WALWrite` or `IO:WALSync` means commit latency from the WAL disk. `IPC:SyncRep` means a slow synchronous standby. `IO:DataFileRead` means index pages no longer fit in cache (random UUID keys across 10 indexes on 1B rows). `LWLock:LockManager` means fast-path overflow. Then correlate with the time it started: a deploy, a checkpoint storm, an autovacuum, a replica outage, a long transaction.

**Triage:**

```sql
-- 1. What are INSERTs waiting on? Sample a few times.
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE state = 'active' AND query ILIKE 'insert%'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- 2. If Lock waits: who is the blocker, and what is it doing?
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event,
       now() - xact_start AS xact_age, left(query, 80) AS query
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0;

-- 3. Checkpoint pressure and backend writes (PG17+ views)
SELECT num_timed, num_requested, write_time, sync_time, buffers_written FROM pg_stat_checkpointer;
SELECT backend_type, context, writes, fsyncs, evictions FROM pg_stat_io
WHERE object = 'relation' AND backend_type = 'client backend';

-- 4. WAL volume and full-page-image share
SELECT wal_records, wal_fpi, pg_size_pretty(wal_bytes) FROM pg_stat_wal;

-- 5. Synchronous replication health (if synchronous_standby_names is set)
SELECT application_name, sync_state, write_lag, flush_lag, replay_lag FROM pg_stat_replication;

-- 6. Is (anti-wraparound) autovacuum running on this table right now?
SELECT p.pid, p.relid::regclass, p.phase, a.query
FROM pg_stat_progress_vacuum p JOIN pg_stat_activity a USING (pid);
```

**Likely causes, mapped to evidence:**

| Evidence | Cause | Fix |
|---|---|---|
| `Lock:transactionid` on INSERT | Two sessions insert the same unique key; the second waits for the first to commit or abort. Or an FK check (`FOR KEY SHARE` on the parent) waits behind a long update of the parent row | Shorten transactions; `INSERT ... ON CONFLICT`; find the long transaction holding the key |
| `Lock:extend` | Many backends extending the same file | PG16 extends in bulk; spread hot inserts (partitioning); faster storage |
| `LWLock:WALWrite`, `IO:WALSync` | Commit = WAL fsync; the WAL disk got slower or WAL volume exploded (e.g. FPIs after frequent checkpoints) | Faster WAL device; larger `max_wal_size`; `wal_compression`; batch rows per commit; `synchronous_commit = off` only for data you can lose |
| `IPC:SyncRep` | Synchronous standby slow or down | Fix the standby; use quorum `ANY 1 (a, b)` so one slow node doesn't stall commits |
| `IO:DataFileRead` | 10 indexes on random keys (UUIDv4): every insert reads ~10 random leaf pages that no longer fit in cache | Time-ordered keys (UUIDv7, identity); drop unused indexes; more RAM; partition so hot indexes are small |
| `LWLock:LockManager` | Each insert locks the table + 10 indexes (+ partitions) and exceeds the 16 fast-path slots (pre-PG18) | Fewer indexes or partitions per statement; PG18 sizes fast-path slots from `max_locks_per_transaction` |
| `LWLock:SubtransSLRU` | ORM savepoint per row (>64 subtransactions per transaction overflows the snapshot cache) | Remove per-row savepoints |
| No waits, high CPU | Triggers, check constraints or generated columns doing heavy work; a plan change in a trigger's query | Profile; `auto_explain.log_nested_statements` |

**About autovacuum and XIDs at this rate:** at 50K single-row transactions per second, XID age reaches `autovacuum_freeze_max_age` (200M) every ~67 minutes, so anti-wraparound vacuums on the 1B-row table are frequent. Thanks to the visibility map's all-frozen bit they only scan pages modified since the last freeze, not the whole table. They compete for I/O but rarely explain a sudden 5 s insert by themselves. Reduce XID burn by batching several rows per transaction or multi-row `INSERT`/`COPY`, and make sure insert-triggered autovacuum (PG13+) freezes recently filled pages promptly.

**Longer term:** partition by time so the active partition's indexes stay hot and small; audit the 10 indexes (each costs an index insertion and WAL on every row); move bulk ingestion to `COPY` in batches.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Systematic triage** | Wait events first; correlates with a start time and recent changes |
| **Insert-specific causes** | Unique-key waits, FK share locks, extension lock, WAL fsync, sync rep, random-key cache misses |
| **Current tooling** | `pg_stat_checkpointer` / `pg_stat_io` (PG17+), `pg_stat_wal`, progress views |
| **XID reasoning** | Correct freeze arithmetic; knows all-frozen pages are skipped |

---

### Q3: "Your team needs to migrate a critical 5TB database from PostgreSQL 13 to PostgreSQL 18 with < 5 minutes of downtime. Design the migration strategy."

**What They're Really Testing:** Whether you know the two real options (`pg_upgrade` in place vs logical-replication blue/green), their downtime and rollback profiles, and the details that bite: sequences, DDL, large objects, replica identity, statistics.

!!! tip "30-second answer"
    Two viable paths. **`pg_upgrade --link`** (or `--swap`, new in PG18) rewrites only the catalogs and hard-links the data files, so a 5 TB upgrade takes minutes. It fits the 5-minute budget, but rollback after starting the new cluster means restoring a backup, and standbys must be rebuilt or resynced. **Logical replication blue/green**: build a PG18 cluster, replicate into it, cut over in seconds to minutes, and keep reverse replication for rollback. It handles bigger jumps (and OS or collation changes) safely, but needs primary keys or replica identity on every table, manual sequence sync and a DDL freeze. With the old cluster on 13 (end of life since November 2025), I'd usually do logical blue/green for a critical system, rehearsed end to end on a production clone.

**Path A: `pg_upgrade` in place**

```bash
# Rehearse on a clone first. Run the checks against the live old cluster:
pg_upgrade --check -b /usr/lib/postgresql/13/bin -B /usr/lib/postgresql/18/bin \
           -d /data/13 -D /data/18
# Downtime window: stop the old cluster, then
pg_upgrade --link --jobs 8 -b ... -B ... -d /data/13 -D /data/18
# PG18 carries over planner statistics (not extended statistics); on older targets
# run vacuumdb --all --analyze-in-stages before opening traffic.
```

- **Downtime:** minutes, dominated by catalog size (many tables or large objects), not data size.
- **Gotchas:** data checksums must match (PG18 `initdb` enables them by default; pass `--no-data-checksums` to match a cluster without them); extensions must exist for both versions; after `--link` and starting the new cluster, the old cluster can't be safely started again. Physical standbys must be re-cloned or upgraded with the documented rsync procedure.

**Path B: logical replication blue/green**

```sql
-- On the PG13 publisher (wal_level = logical; every table needs a PK or REPLICA IDENTITY)
CREATE PUBLICATION upgrade_pub FOR ALL TABLES;

-- On PG18: restore the schema first (pg_dump --schema-only; pg_dumpall --globals-only)
CREATE SUBSCRIPTION upgrade_sub
    CONNECTION 'host=pg13.internal dbname=app user=replicator'
    PUBLICATION upgrade_pub
    WITH (copy_data = true, binary = true);    -- PG18: streaming = parallel is the default

-- Per-table initial-sync state on the subscriber: i=init, d=copying, f=finished copy, s=synced, r=ready
SELECT sr.srrelid::regclass, sr.srsubstate
FROM pg_subscription s
JOIN pg_subscription_rel sr ON sr.srsubid = s.oid
WHERE s.subname = 'upgrade_sub';

-- Lag, measured on the publisher
SELECT slot_name,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag
FROM pg_replication_slots WHERE slot_name = 'upgrade_sub';
```

Speeding up the 5 TB initial copy:

- Create secondary indexes on the subscriber *after* the copy, or raise `max_sync_workers_per_subscription`.
- Since **PG17**, `pg_createsubscriber` turns a physical standby into a logical subscriber with no initial copy, and `pg_upgrade` keeps logical slots and subscription state. Both need the old cluster to be on PG17 or later. They make the *next* upgrade (17 or 18 → 19) much cheaper, but don't help a jump from 13: there you pay the initial copy.

**Cutover runbook (the actual downtime):**

1. DDL freeze for the whole migration (logical replication doesn't carry DDL).
2. Stop writes: `PAUSE` in PgBouncer, or revoke `CONNECT` and terminate app sessions. (`default_transaction_read_only` alone can be overridden per session.)
3. Wait until slot lag is 0.
4. **Sync sequences**: logical replication doesn't copy them until PG19 (`FOR ALL SEQUENCES` + `ALTER SUBSCRIPTION ... REFRESH SEQUENCES`, and that needs a PG19 publisher). For each sequence, `SELECT setval('orders_id_seq', <publisher last_value> + margin);`.
5. Repoint the pooler or DNS to PG18 and resume traffic.
6. Rollback path: before resuming, create a reverse publication on PG18 and a subscription on PG13 (`copy_data = false`), so PG13 stays current for a quick fallback.
7. Afterwards: `ANALYZE` if statistics weren't carried over, compare p99 latency per `queryid`, then drop the old slot (an abandoned slot retains WAL until the disk fills).

**Not replicated, so check each:** DDL, sequences (before PG19), large objects (`pg_largeobject`), materialized view contents (refresh after cutover), and unlogged tables. Tables without a PK or replica identity can't replicate UPDATE or DELETE. Collation-version changes (glibc upgrades) can silently corrupt text indexes in an in-place upgrade; logical replication sidesteps that because the new cluster builds fresh indexes.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Options** | Compares `pg_upgrade --link/--swap` with logical blue/green on downtime and rollback |
| **Replication details** | Replica identity, DDL freeze, sequences, large objects, slot lag on the publisher |
| **Modern tooling** | `pg_createsubscriber` (PG17), statistics carried by `pg_upgrade` (PG18), PG19 sequence sync |
| **Cutover discipline** | Write fence, reverse replication for rollback, rehearsal on a clone |

---

### Q4: "Explain PostgreSQL's buffer pool eviction algorithm. How does it differ from an LRU cache? When would you tune the buffer pool differently for different workloads?"

**What They're Really Testing:** Clock sweep mechanics, why concurrency (not accuracy) drove the design, scan resistance, and the interplay with the OS page cache.

!!! tip "30-second answer"
    PostgreSQL uses **clock sweep**, an approximation of LRU. Each buffer has a `usage_count` (0–5) bumped atomically on access. A shared clock hand circles the buffer array, decrementing counts and evicting the first unpinned buffer at 0. Hits never touch a shared list, so there's no global LRU lock to fight over at high concurrency. Large sequential scans, VACUUM and bulk loads use small **ring buffers**, so they don't flush the hot set. Because PostgreSQL also relies on the OS page cache, `shared_buffers` is usually ~25% of RAM, with the rest left to the kernel. The "right" size is what holds your hot working set, as measured by hit ratio and `pg_buffercache`.

**Mechanics** (code in [the interview-questions page](INTERVIEW_QUESTIONS.md#8-postgresql-buffer-pool-wal-internals)):

1. Lookup: hash `(relfilenode, fork, block)` → buffer id in the buffer mapping table (128 partitions with their own LWLocks).
2. Hit: pin the buffer, increment `usage_count` (cap 5) with a CAS on its state word.
3. Miss: get a victim. The free list is used first (only populated at startup or after drops); otherwise the clock sweep runs. If the victim is dirty, flush WAL up to its LSN, write it out (a "backend write" that adds latency), then read the new page in.
4. The background writer runs ahead of the clock hand writing dirty buffers likely to be evicted soon, so backends usually find clean victims.

**Clock sweep vs true LRU:**

| | True LRU | Clock sweep (PostgreSQL) |
|---|---|---|
| On hit | Move the page to the head of a shared list (needs a lock) | Atomic increment of a counter; no shared structure |
| On eviction | Pop the tail | Sweep, decrementing counts, until an unpinned buffer at 0 |
| Concurrency | List lock is a hotspot | Scales with many backends |
| Scan resistance | Poor: one big scan evicts everything | Ring buffers for large scans, VACUUM and bulk writes |
| Accuracy | Exact recency | Approximate recency and frequency (counts up to 5) |

For comparison: **InnoDB** uses a *midpoint-insertion* LRU (new pages enter the "old" sublist at ~3/8 from the tail and are promoted only if touched again after `innodb_old_blocks_time`, 1 s), which also resists scans. **Redis** doesn't keep an exact LRU either: it samples keys (`maxmemory-samples`) and evicts the best candidate among them.

**Ring buffers (scan resistance):**

| Operation | Strategy | Ring size |
|---|---|---|
| Seq scan of a table larger than ¼ of `shared_buffers` | `BAS_BULKREAD` | 256 KB |
| `VACUUM`, `ANALYZE` | `BAS_VACUUM` | `vacuum_buffer_usage_limit` (2 MB default since PG17) |
| `COPY FROM`, `CREATE TABLE AS`, `ALTER TABLE` rewrites | `BAS_BULKWRITE` | 16 MB |

The pages a big scan reads are recycled within its ring, so the OLTP working set survives a nightly report. The scan's I/O still competes for the disk and the OS cache.

**Sizing for workloads:**

| Workload | `shared_buffers` | Notes |
|---|---|---|
| OLTP, working set fits in RAM | ~25% of RAM; more (40%+) can help if the hot set is just over 25% | Watch the per-table hit ratio; huge pages on; big pools make checkpoints write more |
| Analytics / large scans | Often *smaller* is fine | Scans use ring buffers and the OS cache anyway; give memory to `work_mem` for sorts and hashes; parallel query |
| Mixed | ~25% | Ring buffers protect OLTP pages; isolate heavy reporting on a replica |
| Containers with small RAM | Keep total memory (shared + work_mem × concurrency) under the limit | The OOM killer takes the postmaster down with it |

`effective_cache_size` is only a planner estimate of shared buffers plus OS cache (often ~50–75% of RAM). Setting it doesn't allocate memory.

```sql
-- What's actually in the cache (pg_buffercache extension)
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
SELECT c.relname,
       count(*) AS buffers,
       pg_size_pretty(count(*) * 8192) AS cached,
       round(avg(b.usagecount), 2) AS avg_usage
FROM pg_buffercache b
JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid)
WHERE b.reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())
GROUP BY c.relname
ORDER BY buffers DESC
LIMIT 20;
-- PG18 adds pg_buffercache_evict_relation() / pg_buffercache_evict_all() for testing cold-cache behaviour
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Algorithm** | usage_count, pins, sweep, bgwriter running ahead, dirty-victim cost |
| **Why not LRU** | Concurrency on hits is the reason; accuracy is the price |
| **Scan resistance** | Ring buffers with sizes; contrast with InnoDB midpoint LRU |
| **Sizing** | 25% heuristic and its reasons (double buffering, checkpoints); measures with `pg_buffercache` |

---

### Q5: "How does PostgreSQL handle deadlocks? Walk through a concrete example and explain the detection algorithm."

**What They're Really Testing:** Precise knowledge of what is locked (table lock vs row lock), how detection is triggered, who gets aborted, and how to design deadlocks away.

!!! tip "30-second answer"
    A deadlock is a cycle in the waits-for graph. PostgreSQL doesn't search for cycles continuously. A backend that has waited `deadlock_timeout` (1 s by default) runs the detector **itself**. If it finds a cycle it can't fix by reordering wait queues, it aborts **its own** transaction with `ERROR: deadlock detected` (SQLSTATE `40P01`) and the other transaction proceeds. Prevention matters more than detection: lock rows in a consistent order (e.g. `ORDER BY id FOR UPDATE`), keep transactions short, and retry on 40P01.

**Concrete scenario:**

```sql
-- T1                                              -- T2
BEGIN;                                             BEGIN;
UPDATE accounts SET balance = balance - 100
 WHERE id = 1;      -- row lock on id 1 (in the tuple's xmax);
                    -- RowExclusiveLock on the TABLE, which doesn't conflict with T2's
                                                   UPDATE accounts SET balance = balance - 200
                                                    WHERE id = 2;   -- row lock on id 2
UPDATE accounts SET balance = balance + 100
 WHERE id = 2;      -- waits: tuple lock on id 2, then ShareLock on T2's transactionid
                                                   UPDATE accounts SET balance = balance + 200
                                                    WHERE id = 1;   -- waits for T1's transactionid
-- After deadlock_timeout, whichever backend's timer fires first runs the check, finds
-- T1 → T2 → T1, and aborts itself:
-- ERROR:  deadlock detected
-- DETAIL:  Process 4242 waits for ShareLock on transaction 9001; blocked by process 4343.
--          Process 4343 waits for ShareLock on transaction 9000; blocked by process 4242.
```

**The detector (`src/backend/storage/lmgr/deadlock.c`):**

1. **Trigger:** a backend sleeping on a heavyweight lock wakes after `deadlock_timeout` and calls `DeadLockCheck()`. There's no global periodic sweep, so a lock wait shorter than the timeout costs nothing.
2. **Graph:** a DFS from itself over *hard edges* (it waits for a holder of a conflicting lock) and *soft edges* (it's queued behind a waiter whose request conflicts).
3. **Soft-edge fix:** if every cycle includes a soft edge, the detector tries **rearranging wait queues** (letting a later waiter go first) and resolves the deadlock without aborting anyone.
4. **Hard cycle:** the backend that ran the check aborts **its own** transaction. PostgreSQL doesn't weigh age, work done or wait time; the victim is whoever noticed first.
5. **Cost:** the check holds all lock-manager partition locks while it runs, which is why `deadlock_timeout` defaults to 1 s rather than a few ms. `log_lock_waits = on` logs any wait that outlasts the timeout, even without a deadlock.

```python
def find_cycle(waits_for: dict[int, set[int]], start: int) -> list[int] | None:
    """Simplified: hard edges only, DFS from the backend that is checking."""
    path, on_path = [], set()

    def dfs(p: int) -> list[int] | None:
        path.append(p); on_path.add(p)
        for q in waits_for.get(p, ()):
            if q == start:
                return path + [q]                 # cycle through ourselves → we are the victim
            if q not in on_path and (c := dfs(q)):
                return c
        path.pop(); on_path.discard(p)
        return None

    return dfs(start)

print(find_cycle({4242: {4343}, 4343: {4242}}, start=4242))   # [4242, 4343, 4242]
```

**PostgreSQL vs InnoDB:**

| | PostgreSQL | MySQL InnoDB |
|---|---|---|
| When detection runs | After the waiter has slept `deadlock_timeout` (1 s) | Immediately on each lock wait (`innodb_deadlock_detect = ON`) |
| Victim | The backend that ran the check (itself) | The "lighter" transaction (fewer rows changed and locked) |
| Error | `40P01 deadlock detected` | `ERROR 1213 (40001) Deadlock found when trying to get lock` |
| Fallback | `lock_timeout` (off by default) | `innodb_lock_wait_timeout` (50 s); with high concurrency, detection is sometimes disabled in favour of the timeout |
| Trade-off | No cost for short waits; deadlocks take ≥1 s to resolve | Instant resolution; detection itself can be costly with thousands of waiters |

**Preventing deadlocks:**

```sql
-- 1. Consistent lock order. Two transfers that touch the same accounts in different orders
--    can deadlock; lock both rows up front, in id order.
BEGIN;
SELECT id FROM accounts WHERE id IN (1, 2) ORDER BY id FOR UPDATE;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
-- A multi-row UPDATE ... WHERE id IN (...) locks rows in scan order, which isn't guaranteed.

-- 2. Fail fast instead of waiting (the caller retries)
SELECT * FROM accounts WHERE id = 1 FOR UPDATE NOWAIT;   -- 55P03 if locked
SET lock_timeout = '500ms';                               -- or bound every wait

-- 3. Serialise a whole workflow on a logical key with an advisory lock
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('transfer:' || least(1, 2) || ':' || greatest(1, 2)));
-- ... both updates ...
COMMIT;   -- xact-level advisory locks release automatically
```

Also watch out for **foreign keys**: inserting child rows takes `FOR KEY SHARE` on the parent row, so two transactions inserting children of the same two parents in opposite orders can deadlock too. And keep transactions short. Every deadlock needs two transactions holding locks while waiting.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **What is locked** | Row locks in tuple headers, waits on `transactionid`; table locks don't conflict here |
| **Detection** | Per-waiter check after `deadlock_timeout`, soft edges and queue rearrangement, self-abort |
| **Comparison** | InnoDB's immediate detection and weight-based victim |
| **Prevention** | Lock ordering, `NOWAIT` / `lock_timeout`, advisory locks, retries on 40P01, FK awareness |

---

### Q6: "A query with 15 JOINs is running 100× slower than expected. The EXPLAIN ANALYZE shows wrong row estimates on some tables (off by 1000×). How do you fix the optimizer's estimates?"

**What They're Really Testing:** How cardinality estimation works, why errors compound through joins, and the toolbox for fixing estimates before forcing plans.

!!! tip "30-second answer"
    Find the **lowest node** in the plan where estimated and actual rows diverge; everything above inherits the error. The usual causes: stale stats (run `ANALYZE`), too few MCVs or histogram buckets for a skewed column (raise the per-column statistics target), correlated predicates the planner multiplies as if independent (`CREATE STATISTICS ... (dependencies, mcv)`), functions of columns (expression statistics, PG14+), and join selectivity that compounds across 15 joins. Fix the statistics first. If that's not enough, restructure (a temp table you `ANALYZE`, or `join_collapse_limit = 1` with a hand-chosen order), and only then reach for `pg_hint_plan`.

**Find the first bad estimate:**

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;     -- BUFFERS is implied by ANALYZE in PG18
-- Look for the deepest node like:  (rows=50) (actual rows=50000 loops=1)
-- A 1000× underestimate there typically turns a hash join into a nested loop
-- running 50,000 index probes, and fixes a bad join order for every level above it.

-- Is the table's ANALYZE recent?
SELECT relname, last_analyze, last_autoanalyze, n_mod_since_analyze, n_live_tup
FROM pg_stat_user_tables WHERE relname = 'orders';

-- What does the planner believe about the columns?
SELECT attname, null_frac, n_distinct, most_common_vals, most_common_freqs,
       histogram_bounds, correlation
FROM pg_stats
WHERE schemaname = 'public' AND tablename = 'orders'
  AND attname IN ('status', 'user_id', 'created_at');
```

**Root causes and fixes:**

| Cause | Symptom | Fix |
|---|---|---|
| Stale statistics | `n_mod_since_analyze` large; a bulk load just happened | `ANALYZE`; lower `autovacuum_analyze_scale_factor` for the table; ANALYZE in load jobs |
| Skew not captured | MCV list misses hot values; histogram too coarse | `ALTER TABLE orders ALTER COLUMN status SET STATISTICS 1000;` then `ANALYZE` (samples 300 × target rows) |
| Wrong `n_distinct` on huge tables | Sample-based distinct estimate is far off | `ALTER TABLE orders ALTER COLUMN user_id SET (n_distinct = -0.05);` (negative = fraction of rows) |
| Correlated columns | `WHERE city = 'Paris' AND country = 'FR'` estimated as P(city) × P(country) | Extended statistics: `dependencies`, `mcv` |
| GROUP BY / DISTINCT on several columns | Group count overestimated | Extended statistics: `ndistinct` |
| Expressions | `WHERE date_trunc('month', created_at) = ...` uses a default selectivity guess | Expression statistics (PG14+) or an expression index (which gets its own stats) |
| Join selectivity compounding | Each join's estimate multiplies the previous error | Fix base estimates; materialise a known-size intermediate |
| Generic plans for prepared statements | Fine with literals, bad from the app | `plan_cache_mode = force_custom_plan` for that role or statement |

```sql
-- Extended statistics (PG10+; MCV PG12+; expressions PG14+). Up to 8 columns per object.
CREATE STATISTICS orders_status_created (dependencies, mcv) ON status, created_at FROM orders;
CREATE STATISTICS orders_user_status_nd (ndistinct) ON user_id, status FROM orders;
CREATE STATISTICS orders_month ON (date_trunc('month', created_at)) FROM orders;
ANALYZE orders;

-- Inspect what was built
SELECT statistics_name, attnames, kinds, n_distinct, dependencies
FROM pg_stats_ext WHERE tablename = 'orders';
```

**When statistics can't express it (15-way joins):**

```sql
-- 1. Materialise a selective intermediate result WITH real statistics:
CREATE TEMP TABLE active_users AS
SELECT id FROM users WHERE created_at > '2026-01-01' AND status = 'active';
ANALYZE active_users;                    -- the planner now knows the true row count
SELECT ... FROM active_users u JOIN orders o ON o.user_id = u.id JOIN ...;
-- A MATERIALIZED CTE fences the planner off, but its row estimate is still an estimate;
-- it doesn't feed actual counts back. Only an ANALYZEd temp table does.

-- 2. Pin the join order you've verified, for this statement only:
BEGIN;
SET LOCAL join_collapse_limit = 1;       -- planner follows the written JOIN order
SELECT ... FROM small_filtered s
JOIN medium m ON m.s_id = s.id
JOIN large  l ON l.m_id = m.id ...;
COMMIT;

-- 3. Last resort: pg_hint_plan extension (/*+ HashJoin(a b) Leading((a b) c) */),
--    with a test that alerts when the hinted plan regresses.
```

Note on GEQO: with 15 FROM items (above `geqo_threshold` = 12), the genetic optimizer explores join orders randomly, so plans can change between runs. `SET geqo_threshold = 16` restores exhaustive search at the price of planning time, which is worth testing for a query that runs often.

**Long-term:** schedule `ANALYZE` after bulk loads; add extended statistics where correlated filters are common (driven by query patterns, not blanket generation); capture plans with `auto_explain` and track plan changes per `queryid`.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Diagnosis** | Finds the lowest misestimated node; knows how errors propagate up the tree |
| **Statistics system** | MCVs, equi-depth histograms, n_distinct, correlation, sample size, targets |
| **Extended statistics** | dependencies / ndistinct / mcv / expressions, and when each applies |
| **Escalation path** | Stats → restructure (ANALYZEd temp table, collapse limits) → hints, and knows CTE fences don't fix estimates |

---

### Q7: "Design a PostgreSQL logical replication topology for a multi-region active-active application. What are the limitations and how do you handle conflict resolution?"

**What They're Really Testing:** Honesty about what core PostgreSQL does (bidirectional replication is possible; conflict *resolution* mostly isn't), and a design that avoids conflicts rather than resolving them.

!!! tip "30-second answer"
    Since **PG16**, core logical replication can run bidirectionally without loops (`origin = none`), and **PG18** detects and counts conflicts (`pg_stat_subscription_stats`), but it still doesn't *resolve* them. An insert with an existing key **stops the apply worker with an error**, and a concurrent update of the same row is applied in arrival order (last to arrive wins, per node, so nodes can diverge). DDL and sequences aren't replicated. So design for **no conflicts**: give each row a home region that alone writes it (partition ownership by tenant or region), use globally unique keys (UUIDv7), replicate one-way for read copies, and route the rare cross-region writes to the owner. If you truly need multi-writer, use a product built for it (pgEdge/Spock, EDB Postgres Distributed) or a distributed SQL database.

**Topology: ownership-partitioned "active-active":**

```
        US-East (PG18)                                  EU-West (PG18)
┌──────────────────────────────┐            ┌──────────────────────────────┐
│ writes: rows with            │            │ writes: rows with            │
│   home_region = 'us'         │            │   home_region = 'eu'         │
│ pub_us  (row filter: us) ────┼── logical ►│ sub_from_us (origin = none)  │
│ sub_from_eu (origin = none) ◄┼── logical ─┼── pub_eu (row filter: eu)    │
└──────────────────────────────┘            └──────────────────────────────┘
App: reads locally; writes go to the row's home region (a remote write pays ~70–90 ms RTT
for EU ↔ US-East). Every node holds every row, but each row has exactly one writer.
```

```sql
-- US-East: publish only rows this region owns (row filters PG15+)
CREATE PUBLICATION pub_us FOR TABLE users WHERE (home_region = 'us'),
                               TABLE orders WHERE (home_region = 'us');

-- US-East: subscribe to EU-owned rows; don't re-forward changes that came from elsewhere
CREATE SUBSCRIPTION sub_from_eu
    CONNECTION 'host=eu-west.internal dbname=app user=repl'
    PUBLICATION pub_eu
    WITH (origin = none, copy_data = false, binary = true, disable_on_error = true);
-- (mirror image on EU-West)
```

Row filters on UPDATE/DELETE may only reference replica-identity columns, so `home_region` should be part of the primary key (or of a `REPLICA IDENTITY` index).

**Conflict types and core behaviour (PG18 statistics names):**

| Conflict | Example | Core PostgreSQL behaviour |
|---|---|---|
| `insert_exists` | Both regions insert id 42 | **Error; the apply worker stops and retries** until you fix it (or `disable_on_error` disables the subscription) |
| `update_origin_differs` | Local row last changed by a different origin | Applied: the incoming change wins. Detection needs `track_commit_timestamp = on` |
| `update_exists` | Update would violate a unique constraint | Error |
| `update_missing` / `delete_missing` | Row already deleted locally | Skipped (logged and counted) |
| `delete_origin_differs` | Deleting a row changed by another origin | Applied |
| `multiple_unique_conflicts` | Several unique constraints violated | Error |

```sql
SELECT subname, confl_insert_exists, confl_update_origin_differs,
       confl_update_missing, confl_delete_missing, apply_error_count
FROM pg_stat_subscription_stats;
```

**If you must resolve conflicts in core PostgreSQL:** the apply worker runs with `session_replication_role = replica`, so ordinary triggers **don't fire** on the subscriber. A last-writer-wins guard needs `ENABLE REPLICA TRIGGER` (or `ENABLE ALWAYS`):

```sql
CREATE FUNCTION lww_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.updated_at <= OLD.updated_at THEN
        RETURN NULL;              -- incoming change is older: skip it
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER users_lww BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION lww_guard();
ALTER TABLE users ENABLE REPLICA TRIGGER users_lww;   -- fire in the apply worker too
```

This is fragile. Wall-clock timestamps from different regions are skewed, so the tie-break must be deterministic (e.g. `(updated_at, origin_id)`). It doesn't help `insert_exists`, and deletes vs updates still race. Merging counters or sets needs CRDT-style data modelling, not a trigger.

**Other limitations to state:**

- **DDL** isn't replicated: apply schema changes to every region in a compatible order (expand/contract).
- **Sequences** aren't replicated (PG19 adds explicit sync): use UUIDv7 or region-partitioned identity ranges.
- **Lag is unbounded and asynchronous:** a region failure loses its unreplicated writes; reads in other regions are stale. Monitor `pg_stat_replication` on each publisher and slot lag; set `max_slot_wal_keep_size` so a dead subscriber can't fill the publisher's disk.
- **Large transactions** are streamed while still in progress (`streaming = parallel`, the PG18 default) to reduce apply lag.
- Logical slots fail over with the primary only if configured (PG17+: `failover = true` subscriptions plus `sync_replication_slots` on the standby).

**Often the better answer:** a single primary region with physical replicas elsewhere for local reads (writes pay the cross-region RTT), plus a tested regional failover. Or put each tenant's data in its home region (data residency) with no cross-region writes at all.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Honesty** | Core PG detects (PG18) but doesn't resolve conflicts; `insert_exists` stops apply |
| **Design** | Single-writer-per-row ownership, row filters, `origin = none`, UUIDv7 keys |
| **Mechanics** | Replica triggers, `track_commit_timestamp`, conflict stats, slot failover (PG17) |
| **Alternatives** | Single-primary + replicas, data residency, pgEdge / EDB PGD, distributed SQL |

---

### Q8: "A pg_dump of a 2TB database takes 12 hours and the backup fails at 95% due to a network interruption. Design a backup strategy that can resume from where it left off and completes within a 4-hour backup window."

**What They're Really Testing:** Knowing that logical dumps aren't the backup system for 2 TB, and designing around RPO, RTO and verified restores rather than "a dump that finishes".

!!! tip "30-second answer"
    Replace pg_dump as the primary backup with **physical backups plus continuous WAL archiving**: pgBackRest (or Barman / WAL-G) to object storage. That gives point-in-time recovery, an RPO of seconds, parallel compressed transfer, **resumable** backups, and incrementals that copy only changed files or blocks, so the nightly window shrinks from 12 hours to well under one. PostgreSQL 17's built-in `pg_basebackup --incremental` + `pg_combinebackup` is an alternative without extra tooling. Prove it with automated restore tests that measure RTO. Keep `pg_dump` for logical needs (single tables, migrations), run in parallel directory format, ideally from a replica.

**Why pg_dump fits poorly here:**

- One consistent snapshot per run: an interrupted dump can't resume, and a 12-hour snapshot holds back VACUUM on the primary for 12 hours (bloat).
- Restoring rebuilds every index and constraint, so the RTO for 2 TB is many hours.
- No point-in-time recovery: you lose everything since the last dump.

**Primary design: pgBackRest**

| Need | How |
|---|---|
| Fit in 4 h | `process-max` parallelism + zstd compression; weekly full, daily differential, hourly incremental, each copying only changed files (or blocks with block-level incremental) |
| Survive network blips | Retries on transfer; an interrupted backup **resumes** (`resume=y`, the default), skipping files already copied and verified by checksum |
| RPO of seconds | Continuous WAL archiving (`archive-push`, asynchronous with `archive-async=y`) |
| No load on the primary | Back up from a standby (`backup-standby=y`) |
| Integrity | Checksums of every file; page checksums verified during backup; `pgbackrest verify` |
| Security, retention | `repo1-cipher-type=aes-256-cbc`; `repo1-retention-full`; second repository in another region |

```ini
[global]
repo1-type=s3
repo1-s3-bucket=pg-backups-prod
repo1-s3-endpoint=s3.us-east-1.amazonaws.com
repo1-s3-region=us-east-1
repo1-path=/app
repo1-retention-full=4
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=<from a secret store>
process-max=8
compress-type=zst
compress-level=3
archive-async=y
backup-standby=y

[app]
pg1-path=/var/lib/postgresql/18/main
pg2-host=standby1.internal
pg2-path=/var/lib/postgresql/18/main
```

```bash
pgbackrest --stanza=app --type=full backup        # Sunday
pgbackrest --stanza=app --type=diff backup        # daily
pgbackrest --stanza=app --type=incr backup        # every 4 hours
pgbackrest --stanza=app verify                    # check repository contents

# Point-in-time restore onto an existing data dir, copying only what differs
pgbackrest --stanza=app --delta --type=time --target="2026-06-15 14:30:00+00" \
           --target-action=promote restore
```

**Built-in alternative (PG17+):**

```bash
# postgresql.conf: summarize_wal = on, plus WAL archiving for PITR
pg_basebackup -D /backups/full -X stream -c fast                                # weekly
pg_basebackup -D /backups/incr_mon --incremental=/backups/full/backup_manifest  # daily
pg_combinebackup /backups/full /backups/incr_mon -o /restore/data               # at restore time
pg_verifybackup /backups/full
```

It has no resume, retention management or object-storage support of its own, so it suits simpler setups or pairs with a script.

**Logical exports, when you still need them:**

```bash
# From a standby, in parallel, compressed; restore with pg_restore -j
pg_dump -h standby1 -d app -Fd -j 8 --compress=zstd:3 -f /exports/app_2026_06_15/
```

On a standby, a long dump conflicts with WAL replay; use a dedicated replica with `hot_standby_feedback` or a generous `max_standby_streaming_delay`.

**Restore testing is the real deliverable:**

- Daily: restore the latest backup to a scratch host, replay to a recent point, start it, run sanity queries (row counts, latest order timestamp), and record the duration. That number is the actual RTO.
- Quarterly: a full disaster-recovery drill in another region.
- Alert on archive failures (`pg_stat_archiver.failed_count`, `last_failed_time`) and on backup age.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Right tool** | Physical backup + WAL archiving for 2 TB; pg_dump only for logical needs |
| **Window and resilience** | Parallelism, compression, incrementals, resume, backup from a standby |
| **RPO/RTO** | Continuous archiving for PITR; RTO measured by real restores |
| **Current options** | pgBackRest/Barman/WAL-G; PG17 incremental `pg_basebackup` + `pg_combinebackup` |

---

### Q9: "Your production database is experiencing periodic 'checkpoints are occurring too frequently' warnings in the logs. Walk through the causes, diagnosis, and solutions."

**What They're Really Testing:** The link between WAL generation rate, `max_wal_size`, full-page writes and I/O, and the ability to measure WAL instead of guessing.

!!! tip "30-second answer"
    The warning (`LOG: checkpoints are occurring too frequently (N seconds apart)`) is emitted when a checkpoint *requested by WAL volume* starts within `checkpoint_warning` (30 s) of the previous one. Your WAL generation rate exceeds `max_wal_size` per interval. Frequent checkpoints feed themselves: each one resets full-page-write tracking, so the next burst of changes writes 8 KB page images, inflating WAL and triggering the next checkpoint sooner. Measure WAL per minute and the FPI share, raise `max_wal_size` until checkpoints are mostly timed, enable `wal_compression`, and find what started producing the WAL (bulk jobs, new indexes, lost HOT updates, random-UUID inserts).

**Causes of high WAL volume:**

1. Write volume itself (bulk `UPDATE`/`DELETE`, backfills, ETL).
2. **Full-page images** after every checkpoint, multiplied by how many distinct pages get touched: random-key inserts (UUIDv4) and wide updates touch many pages.
3. Non-HOT updates writing to every index; each extra index adds WAL per row.
4. `wal_level = logical` adds some extra information (old key values, catalog data); `replica` vs `minimal` matters mostly for bulk loads.
5. Maintenance: `VACUUM` freezing old pages, `CREATE INDEX`, `CLUSTER`/`VACUUM FULL`, and hint-bit FPIs when `wal_log_hints` or checksums are on.

**Diagnosis:**

```sql
-- 1. Timed vs requested checkpoints (PG17+; earlier versions: pg_stat_bgwriter.checkpoints_timed/_req)
SELECT num_timed, num_requested,
       round(100.0 * num_requested / nullif(num_timed + num_requested, 0), 1) AS requested_pct,
       write_time, sync_time, buffers_written
FROM pg_stat_checkpointer;

-- 2. WAL rate: sample the LSN twice (psql)
SELECT pg_current_wal_lsn() AS lsn_start \gset
SELECT pg_sleep(60);
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'lsn_start')) AS wal_per_minute;
-- Size max_wal_size to hold at least checkpoint_timeout worth of WAL, with headroom:
-- 1 GB/min with checkpoint_timeout = 15min → max_wal_size ≈ 20–30 GB.

-- 3. How much of it is full-page images? (cumulative since stats reset)
SELECT wal_records, wal_fpi,
       round(100.0 * wal_fpi / nullif(wal_records, 0), 1) AS fpi_pct_of_records,
       pg_size_pretty(wal_bytes) AS wal_bytes
FROM pg_stat_wal;
-- More detail per record type: pg_waldump --stats=record on a segment,
-- or pg_get_wal_stats() from the pg_walinspect extension.

-- 4. Which statements generate WAL?
SELECT left(query, 80) AS query, calls,
       pg_size_pretty(wal_bytes) AS wal, wal_fpi,
       pg_size_pretty(wal_bytes / nullif(calls, 0)) AS wal_per_call
FROM pg_stat_statements
ORDER BY wal_bytes DESC
LIMIT 10;
```

With `log_checkpoints = on` (the default since PG15), each checkpoint logs its trigger (`wal` or `time`), buffers written, and write/sync durations. Correlate those with the warning.

**Solutions, in order:**

| Step | Change | Effect / trade-off |
|---|---|---|
| 1 | `max_wal_size` up (e.g. 1 GB → 16–32 GB) | Checkpoints become timed; fewer FPIs. Costs `pg_wal` disk and longer crash recovery |
| 2 | `checkpoint_timeout` 15–30 min | Fewer checkpoints and FPIs; recovery replays more WAL |
| 3 | `checkpoint_completion_target = 0.9` (already the default since PG14) | Spreads checkpoint writes; smooth I/O |
| 4 | `wal_compression = zstd` (PG15+; or `lz4`) | Compresses FPIs only, often a large share of WAL; small CPU cost |
| 5 | bgwriter: `bgwriter_lru_maxpages` 100 → 1000, `bgwriter_lru_multiplier` 2 → 4 | Fewer backend writes between checkpoints |
| 6 | Workload changes | Batch backfills with pauses; drop unused indexes; keep HOT-friendly schemas (no index on frequently updated columns, table fillfactor 85–90); UUIDv7 instead of UUIDv4 keys |
| 7 | Unlogged tables for truly disposable data | No WAL, but **truncated after a crash** and not replicated |

```sql
ALTER SYSTEM SET max_wal_size = '24GB';
ALTER SYSTEM SET min_wal_size = '4GB';
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET wal_compression = 'zstd';
ALTER SYSTEM SET bgwriter_lru_maxpages = 1000;
ALTER SYSTEM SET bgwriter_lru_multiplier = 4.0;
SELECT pg_reload_conf();      -- all of these are reloadable, no restart needed
```

Don't issue a manual `CHECKPOINT` to "relieve pressure": it forces an immediate, unthrottled flush of every dirty buffer, which is the I/O spike you're trying to avoid.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cause** | Requested checkpoints from WAL volume; the FPI feedback loop |
| **Measurement** | WAL per minute, FPI share, per-statement WAL, checkpoint log lines |
| **Sizing** | Derives `max_wal_size` from the WAL rate and timeout |
| **Trade-offs** | Recovery time, disk, unlogged-table risks, avoiding manual checkpoints |

---

### Q10: "Explain how PostgreSQL handles recursive CTEs. Walk through the evaluation model and give an example where a recursive CTE outperforms an application-level query loop."

**What They're Really Testing:** The working-table iteration model, termination and cycle handling, and judgement about when hierarchies belong in SQL.

!!! tip "30-second answer"
    `WITH RECURSIVE` is evaluated **iteratively**, not recursively. Run the non-recursive term into a working table. Then repeatedly run the recursive term against *only the previous iteration's rows*, append the new rows to the result, and make them the next working table, until an iteration produces nothing. With `UNION` (not `UNION ALL`), duplicate rows are discarded, which also stops simple cycles. There's no built-in depth limit, so guard with a depth column or the `CYCLE` clause (PG14+). It beats an application loop whenever the loop would make one round trip per level or per node, which is N network round trips and N planner passes versus one.

**Evaluation model:**

```python
def evaluate_recursive_cte(non_recursive_term, recursive_term, union_all=True):
    working = run(non_recursive_term)            # iteration 0
    result = list(working)
    seen = set(working) if not union_all else None
    while working:                               # stops only when an iteration yields no rows
        new_rows = run(recursive_term, cte=working)   # sees ONLY the previous iteration
        if not union_all:                        # UNION: drop rows already produced
            new_rows = [r for r in new_rows if r not in seen]
            seen.update(new_rows)
        result.extend(new_rows)
        working = new_rows
    return result                                # spills to disk via a tuplestore if large
```

**Example: org chart below the CTO**

```sql
CREATE TABLE employees (
    id         int PRIMARY KEY,
    name       text NOT NULL,
    manager_id int REFERENCES employees(id),
    department text NOT NULL
);
CREATE INDEX ON employees (manager_id);      -- the recursive join probes this

INSERT INTO employees VALUES
    (1, 'CEO', NULL, 'executive'),
    (2, 'CTO', 1, 'engineering'),
    (3, 'CFO', 1, 'finance'),
    (4, 'Engineering Director', 2, 'engineering'),
    (5, 'Platform Lead', 4, 'engineering'),
    (6, 'Backend Lead', 4, 'engineering'),
    (7, 'Frontend Lead', 4, 'engineering'),
    (8, 'Backend Engineer 1', 6, 'engineering'),
    (9, 'Backend Engineer 2', 6, 'engineering'),
    (10, 'Data Engineer', 5, 'engineering'),
    (11, 'Analyst', 3, 'finance'),
    (12, 'Accountant', 3, 'finance');

WITH RECURSIVE org_chart AS (
    SELECT id, name, 1 AS level, ARRAY[id] AS path      -- base: the CTO
    FROM employees
    WHERE id = 2
    UNION ALL
    SELECT e.id, e.name, oc.level + 1, oc.path || e.id  -- direct reports of the previous level
    FROM employees e
    JOIN org_chart oc ON e.manager_id = oc.id
)
SELECT level, repeat('  ', level - 1) || name AS org_tree, id
FROM org_chart
ORDER BY path;                                          -- depth-first order via the id path
```

```
 level |         org_tree         | id
-------+--------------------------+----
     1 | CTO                      |  2
     2 |   Engineering Director   |  4
     3 |     Platform Lead        |  5
     4 |       Data Engineer      | 10
     3 |     Backend Lead         |  6
     4 |       Backend Engineer 1 |  8
     4 |       Backend Engineer 2 |  9
     3 |     Frontend Lead        |  7
```

PG14+ can produce the ordering column for you: `) SEARCH DEPTH FIRST BY name SET ord` after the CTE body, then `ORDER BY ord` (sorts siblings by name instead of id).

**Ancestors of one employee: CTE vs application loop**

```sql
-- Application loop: one round trip per level
--   SELECT manager_id FROM employees WHERE id = 8;  → 6
--   SELECT manager_id FROM employees WHERE id = 6;  → 4
--   ... 5 queries; at 1–2 ms RTT each that's 5–10 ms, and for a 10K-node subtree, 10K queries

WITH RECURSIVE ancestors AS (
    SELECT id, name, manager_id, 0 AS hops
    FROM employees WHERE id = 8
    UNION ALL
    SELECT e.id, e.name, e.manager_id, a.hops + 1
    FROM employees e
    JOIN ancestors a ON e.id = a.manager_id
)
SELECT name, hops FROM ancestors ORDER BY hops DESC;
```

```
         name         | hops
----------------------+------
 CEO                  |    4
 CTO                  |    3
 Engineering Director |    2
 Backend Lead         |    1
 Backend Engineer 1   |    0
```

**Bill of materials: total quantity of every component in product 100**

```sql
CREATE TABLE parts (id int PRIMARY KEY, name text NOT NULL);
CREATE TABLE bill_of_materials (
    parent_part_id int REFERENCES parts(id),
    child_part_id  int REFERENCES parts(id),
    quantity       int NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (parent_part_id, child_part_id)
);
INSERT INTO parts VALUES (100, 'Bike'), (1, 'Wheel'), (2, 'Spoke'), (3, 'Frame'), (4, 'Bolt');
INSERT INTO bill_of_materials VALUES
    (100, 1, 2),    -- a bike has 2 wheels
    (1, 2, 32),     -- a wheel has 32 spokes
    (1, 4, 1),      -- and 1 bolt
    (100, 3, 1),    -- a bike has 1 frame
    (3, 4, 6);      -- a frame has 6 bolts

WITH RECURSIVE bom AS (
    SELECT child_part_id AS part_id, quantity AS qty           -- direct components
    FROM bill_of_materials
    WHERE parent_part_id = 100
    UNION ALL
    SELECT b.child_part_id, bom.qty * b.quantity                -- multiply down the tree
    FROM bom
    JOIN bill_of_materials b ON b.parent_part_id = bom.part_id
)
SELECT p.name, sum(bom.qty) AS total_qty
FROM bom JOIN parts p ON p.id = bom.part_id
GROUP BY p.name
ORDER BY total_qty DESC;
-- Spoke 64, Bolt 8 (2 wheels × 1 + 1 frame × 6), Wheel 2, Frame 1
```

UNION ALL is required here: the same part reached by two paths (bolts) must be counted twice. UNION would merge identical `(part_id, qty)` rows and undercount.

**When to use which:**

| Recursive CTE wins | Application code (or another model) wins |
|---|---|
| Trees and DAGs of moderate size: org charts, categories, BOMs, comment threads | Per-level business logic or calls to external services |
| Anything an app would do one query per level or per node | Deep, huge graph traversals (shortest paths, PageRank): use a graph engine or precomputed structures |
| Need for one consistent snapshot of the hierarchy | Read-mostly hierarchies queried constantly: materialise with `ltree` paths, nested sets or a closure table |

Running totals are a job for window functions (`sum(x) OVER (ORDER BY t)`), not recursion.

**Limitations and gotchas:**

```sql
-- 1. The recursive term may reference the CTE only once, and not inside an outer join
--    or a subquery. It can't use aggregate functions, ORDER BY or LIMIT/OFFSET
--    ("not implemented" errors). Aggregate in the outer query instead.

-- 2. Cycle protection (PG14+): CYCLE marks and stops on a repeated id
WITH RECURSIVE walk AS (
    SELECT id, manager_id FROM employees WHERE id = 1
    UNION ALL
    SELECT e.id, e.manager_id FROM employees e JOIN walk w ON e.manager_id = w.id
) CYCLE id SET is_cycle USING visited
SELECT * FROM walk WHERE NOT is_cycle;

-- Pre-PG14 equivalent: carry an array and test it
--   ... WHERE NOT e.id = ANY(w.path)

-- 3. Depth guard: add "WHERE w.depth < 20" to the recursive term.

-- 4. The planner can't estimate recursion depth well; index the join column
--    (employees.manager_id) so each iteration is an index probe, not a scan.
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Evaluation model** | Working table holds only the previous iteration; stops on an empty iteration; UNION vs UNION ALL |
| **Correctness** | Cycle handling (`CYCLE` / path arrays), depth guards, UNION ALL for multiplicities |
| **Performance** | Index on the recursive join key; round trips saved vs an app loop |
| **Judgement** | Knows when to use ltree, closure tables, window functions or a graph engine instead |

---

### Q11: "Design a PostgreSQL query that paginates efficiently through 10M orders, sorted by created_at DESC. The user can filter by status, date range, or search by order_id. Compare cursor-based vs offset-based pagination."

**What They're Really Testing:** Keyset pagination mechanics: the tie-breaker, the row-value comparison, and an index that matches filter + sort, plus the UX trade-offs.

!!! tip "30-second answer"
    `OFFSET n` makes the database produce and throw away n rows, so page 10,000 costs 10,000 pages of work, and concurrent inserts shift rows between pages (duplicates and misses). **Keyset (cursor) pagination** remembers the last row's sort key, `(created_at, id)`, and asks for rows after it: `WHERE (created_at, id) < ($1, $2) ORDER BY created_at DESC, id DESC LIMIT 20`. With an index on `(status, created_at, id)` that's an index seek plus 20 rows, the same cost on every page. The `id` tie-breaker makes the order total. You lose "jump to page N", which is usually fine (infinite scroll, next/prev). Looking up an order by id is a point query, not pagination.

**OFFSET:**

```sql
SELECT id, order_no, amount, created_at
FROM orders
WHERE status = 'completed'
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 199980;          -- page 10,000
-- Even with a perfect index, the executor walks 200,000 index entries (and their heap
-- rows unless the scan is index-only) to discard 199,980. Deep pages may also flip
-- the planner to a full sort.
```

**Keyset:**

```sql
CREATE INDEX idx_orders_status_created ON orders (status, created_at DESC, id DESC);

-- First page
SELECT id, order_no, amount, created_at
FROM orders
WHERE status = 'completed'
ORDER BY created_at DESC, id DESC
LIMIT 20;

-- Next page: the client sends back the last row's (created_at, id)
SELECT id, order_no, amount, created_at
FROM orders
WHERE status = 'completed'
  AND (created_at, id) < ('2026-06-15 14:30:00+00', 12345)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

Why it's fast: the row-value comparison `(created_at, id) < (a, b)` matches the index order exactly, so the B-tree seeks to `(status='completed', a, b)` and reads the next 20 entries, about O(log n + 20) on every page. It must be a row comparison, not `created_at <= a AND id < b`, which is a different (wrong) predicate. If the sort directions are mixed (`created_at DESC, id ASC`), a single row comparison no longer works. Keep directions uniform.

**Date-range filter:** add `AND created_at >= $from AND created_at < $to`. The same index serves it, since the range is on the sort column.

**Search by order id or number:** it's a lookup, `WHERE order_no = $1`, using a unique index. If it's a prefix search, use a `text_pattern_ops` B-tree or a trigram GIN and paginate the result the same way, by `(created_at, id)`.

**Application code (Python, psycopg 3):**

```python
from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib, hmac, json

SECRET = b"rotate-me"   # sign cursors so clients can't tamper with them

def encode_cursor(obj: dict) -> str:
    body = json.dumps(obj, separators=(",", ":"), default=str).encode()
    sig = hmac.new(SECRET, body, hashlib.sha256).digest()[:16]
    return urlsafe_b64encode(sig + body).decode()

def decode_cursor(token: str) -> dict:
    raw = urlsafe_b64decode(token.encode())
    sig, body = raw[:16], raw[16:]
    if not hmac.compare_digest(sig, hmac.new(SECRET, body, hashlib.sha256).digest()[:16]):
        raise ValueError("bad cursor")
    return json.loads(body)

def list_orders(conn, status: str, page_size: int = 20, cursor: str | None = None,
                date_from=None, date_to=None):
    sql = ["SELECT id, order_no, amount, created_at FROM orders WHERE status = %(status)s"]
    params = {"status": status, "limit": page_size + 1}     # one extra row → is there a next page?
    if date_from:
        sql.append("AND created_at >= %(date_from)s"); params["date_from"] = date_from
    if date_to:
        sql.append("AND created_at < %(date_to)s"); params["date_to"] = date_to
    if cursor:
        c = decode_cursor(cursor)
        if c["status"] != status:                            # cursor belongs to another filter set
            raise ValueError("cursor does not match filters")
        sql.append("AND (created_at, id) < (%(c_ts)s, %(c_id)s)")
        params.update(c_ts=c["created_at"], c_id=c["id"])
    sql.append("ORDER BY created_at DESC, id DESC LIMIT %(limit)s")

    rows = conn.execute(" ".join(sql), params).fetchall()
    items = rows[:page_size]
    next_cursor = None
    if len(rows) > page_size:
        last = items[-1]
        next_cursor = encode_cursor({"status": status, "created_at": last[3].isoformat(), "id": last[0]})
    return items, next_cursor
```

**Comparison:**

| | OFFSET / LIMIT | Keyset (cursor) |
|---|---|---|
| Cost of page N | Grows with N | Constant (index seek + page size) |
| Jump to page N | Yes | No (only next/previous, or jump to a date) |
| Concurrent inserts and deletes | Rows shift: duplicates or skips | Stable: continues after the last seen key |
| Requirements | None | Total order (tie-breaker), matching index, uniform sort directions |
| Previous page | `OFFSET - n` | Reverse the comparison and the ORDER BY, then reverse the rows |
| Good for | Small result sets, admin UIs with page numbers | Feeds, APIs, exports, large tables |

**Hybrid for "page numbers" UIs:** show pages 1–N for the first few pages with OFFSET, and keyset beyond that. Or offer "jump to date" instead of "jump to page 5,000". Use estimated totals (`EXPLAIN` row estimate or `pg_class.reltuples`) instead of `count(*)` over 10M rows on every request.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **OFFSET cost** | Explains produce-and-discard and the consistency problems |
| **Keyset mechanics** | Row-value comparison, tie-breaker, matching index and directions |
| **API design** | Opaque signed cursors bound to the filter set, `limit + 1` for has-next |
| **Trade-offs** | No random access; hybrid and estimated-count techniques |

---

### Q12: "You're migrating from MySQL to PostgreSQL. A colleague claims 'PostgreSQL doesn't need as many indexes as MySQL.' How do you evaluate this claim? What indexing differences matter most in practice?"

**What They're Really Testing:** Real storage-model differences (clustered InnoDB vs heap PostgreSQL), what each engine actually supports today, and the ability to turn a vague claim into measurable checks.

!!! tip "30-second answer"
    Mostly false as a rule. Both engines need indexes for the same access paths. Some PostgreSQL features can *replace* indexes you'd add in MySQL: **partial indexes**, **expression indexes on anything**, and **bitmap scans** that combine single-column indexes. But PostgreSQL also has no clustered primary key, so every secondary-index lookup goes to the heap, index-only scans depend on VACUUM keeping the visibility map current, and every non-HOT update writes to *every* index, so extra indexes cost more on update-heavy tables. Evaluate it empirically: replay production queries, then use `pg_stat_statements`, `EXPLAIN` and `pg_stat_user_indexes` to see which indexes are used.

**What actually differs (MySQL 8.4 / 9.7 InnoDB vs PostgreSQL 18):**

| Area | MySQL InnoDB | PostgreSQL |
|---|---|---|
| Table storage | **Clustered** by primary key: rows live in the PK B-tree | **Heap**; every index, including the PK, points to a TID |
| Secondary index entry | Key + **primary key** (lookup goes through the PK tree) | Key + TID (lookup goes to the heap page) |
| Covering / index-only | Any secondary index covering the query (PK columns included implicitly); no `INCLUDE` syntax | `INCLUDE` columns; index-only only for all-visible pages |
| PK choice | Random PKs (UUIDv4) fragment the *table itself*; secondary indexes repeat the PK | Random keys fragment the indexes only; the heap is insert-ordered |
| Partial indexes | Not supported | `WHERE` predicate |
| Functional indexes | Yes, since 8.0.13 (functional key parts, backed by hidden virtual columns) | Expression indexes on any immutable expression |
| JSON | Functional indexes on extracted paths; **multi-valued indexes** for arrays (8.0.17+) | GIN (`jsonb_ops`, `jsonb_path_ops`), expression B-trees |
| Full text | `FULLTEXT` indexes (InnoDB, since 5.6) | GIN on `tsvector` (plus `pg_trgm` for fuzzy search) |
| Spatial | `SPATIAL` R-tree indexes | GiST / SP-GiST (PostGIS) |
| Combining indexes | Index merge (union/intersection) in limited cases | **Bitmap AND/OR** across any B-tree, GIN, GiST and BRIN indexes |
| Skipping a leading column | Skip scan (8.0.13+); loose index scan for `GROUP BY` / `DISTINCT` | **Skip scan since PG18**; no loose index scan for `DISTINCT` (emulate with a recursive CTE) |
| Online index build | Online DDL (`ALGORITHM=INPLACE, LOCK=NONE`) allows concurrent DML | `CREATE INDEX CONCURRENTLY` (two table scans; can leave an INVALID index on failure) |
| Write cost of an index | Only indexes on changed columns (plus all of them on PK changes) | Every index on non-HOT updates; none on HOT updates |

**Where PostgreSQL can genuinely use fewer or smaller indexes:**

```sql
-- 1. Partial index for the hot subset instead of a full index on a skewed column
CREATE INDEX idx_orders_open ON orders (created_at)
    WHERE status IN ('pending', 'processing');   -- indexes only the few open orders

-- 2. Expression index without adding a column
CREATE INDEX idx_users_email_lower ON users (lower(email));
SELECT * FROM users WHERE lower(email) = 'alice@example.com';

-- 3. Bitmap AND of two single-column indexes for ad-hoc filter combinations,
--    where MySQL would usually need a composite index per combination
--    (a composite is still faster for a known hot query)

-- 4. BRIN instead of a B-tree on an append-only timestamp: kilobytes to megabytes, not gigabytes
CREATE INDEX idx_events_created_brin ON events USING brin (created_at);
```

**Where PostgreSQL needs *more* care:**

```sql
-- 1. No clustered PK: a range scan by PK in InnoDB reads contiguous rows; in PostgreSQL
--    it can hit a different heap page per row. Options: covering indexes (INCLUDE),
--    a one-off CLUSTER (ACCESS EXCLUSIVE lock) or pg_repack --order-by to re-sort
--    (the order isn't maintained afterwards), or partitioning so hot data is compact.
CREATE INDEX idx_orders_user_cover ON orders (user_id, created_at) INCLUDE (amount, status);

-- 2. Index-only scans silently degrade when autovacuum lags (Heap Fetches in EXPLAIN grows).

-- 3. Every extra index costs every non-HOT UPDATE, and blocks HOT if it includes a
--    frequently updated column. Audit with:
SELECT relid::regclass AS table_name, indexrelid::regclass AS index_name, idx_scan, last_idx_scan
FROM pg_stat_user_indexes ORDER BY idx_scan;
```

**Migration pitfalls:**

- **Collation and case:** MySQL's default collations are case- and accent-insensitive, PostgreSQL's aren't. `WHERE email = 'Alice@x.com'` stops matching. Use `lower()` expression indexes, `citext`, or nondeterministic ICU collations (which don't support `LIKE` before PG18).
- **Implicit PK in secondary indexes:** a MySQL index on `(status)` effectively serves `(status, id)` lookups and ordering. In PostgreSQL write `(status, id)` explicitly if you need that.
- **`COUNT(*)`:** slow in both for large tables (MVCC); use estimates (`pg_class.reltuples`) or counters.
- **Statistics:** InnoDB samples a few pages per index (`innodb_stats_persistent_sample_pages` = 20) and recalculates after ~10% of rows change. PostgreSQL's autoanalyze samples 300 × `default_statistics_target` rows after 10% + 50 changes. After a bulk load into PostgreSQL, run `ANALYZE` yourself.
- **Unsigned integers and `AUTO_INCREMENT`:** map to `bigint GENERATED ALWAYS AS IDENTITY`. Sequences are non-transactional and gaps are normal, as in MySQL.

**How to evaluate the claim:** replay a day of production queries against PostgreSQL with the MySQL index set, then remove one index at a time. Watch `pg_stat_statements` (mean and p99 per query), `EXPLAIN (ANALYZE, BUFFERS)` for the top queries, `pg_stat_user_indexes.idx_scan`, and write throughput and WAL volume. Keep only indexes that earn their write cost.

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage model** | Clustered vs heap and what it means for lookups, PK choice and range scans |
| **Accurate feature map** | Knows MySQL has functional, FULLTEXT, spatial and multi-valued indexes, plus online DDL; PG18 skip scan |
| **Trade-offs** | Partial / expression / bitmap / BRIN wins vs no-clustering, VM dependence, non-HOT write cost |
| **Method** | Replays workload and measures instead of debating |

---

## 12. Common Pitfalls & Anti-Patterns

### 12.1 Index Bloat

```sql
-- Cause: index entries for dead row versions (non-HOT updates, deletes) leave pages
--        sparsely filled; B-tree pages are reused only when they're entirely empty.
-- Effect: bigger indexes → more cache pressure and I/O for every scan.

-- Measure with pgstattuple rather than guessing from size:
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT avg_leaf_density, leaf_fragmentation FROM pgstatindex('idx_users_email');

-- Index size relative to its table:
SELECT s.relid::regclass AS table_name,
       s.indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
       round(100.0 * pg_relation_size(s.indexrelid) / nullif(pg_relation_size(s.relid), 0), 1) AS pct_of_table
FROM pg_stat_user_indexes s
ORDER BY pg_relation_size(s.indexrelid) DESC;

-- Fix online (PG12+):
REINDEX INDEX CONCURRENTLY idx_users_email;
-- Prevent: keep HOT updates working (no index on churny columns, table fillfactor),
-- keep autovacuum ahead, and PG14+ bottom-up deletion handles version churn.
```

### 12.2 Row-Level Lock Contention

```sql
-- Cause: many transactions updating the same rows (counters, a "balance" row, a queue head).
-- Effect: sessions wait on Lock:transactionid / Lock:tuple; throughput collapses to one writer.

SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event,
       now() - xact_start AS xact_age, left(query, 100) AS query
FROM pg_stat_activity
WHERE wait_event_type = 'Lock'
ORDER BY xact_age DESC;

-- Fixes:
-- 1. Shorter transactions: never hold a hot row lock across network calls.
-- 2. Spread the hot row: N counter slots (UPDATE ... WHERE slot = random()*N), sum on read.
-- 3. Append instead of update: insert ledger rows, aggregate periodically.
-- 4. Work queues: SELECT ... FOR UPDATE SKIP LOCKED LIMIT n.
-- 5. Bound waits: lock_timeout, or NOWAIT where callers can retry.
```

### 12.3 XID Wraparound Panic

```sql
-- Cause: freezing can't keep up, usually because something pins the xmin horizon
--        (long transaction, abandoned replication slot, orphaned prepared transaction).
-- Effect: anti-wraparound vacuums everywhere; at ~3M XIDs remaining the server refuses
--         to assign XIDs, so no writes are possible until you VACUUM.

SELECT datname, age(datfrozenxid) AS xid_age,
       round(100.0 * age(datfrozenxid) / 2147483648, 1) AS pct_of_wraparound
FROM pg_database
ORDER BY xid_age DESC;

-- What's holding the horizon back?
SELECT 'backend' AS source, pid::text AS id, age(backend_xmin) AS xmin_age
FROM pg_stat_activity WHERE backend_xmin IS NOT NULL
UNION ALL
SELECT 'slot', slot_name, age(coalesce(xmin, catalog_xmin)) FROM pg_replication_slots
UNION ALL
SELECT 'prepared xact', gid, age(transaction) FROM pg_prepared_xacts
ORDER BY xmin_age DESC NULLS LAST;

-- Prevention:
-- 1. Never disable autovacuum; give it enough workers and cost budget.
-- 2. Alert at, say, 40% of wraparound (~800M), well before the failsafe (1.6B).
-- 3. Kill or fix the horizon holders above; drop abandoned slots.
-- 4. Freeze append-only tables early:
VACUUM (FREEZE, VERBOSE) historical_events;
-- 5. Watch MultiXact age too (mxid_age(datminmxid)): heavy FOR SHARE / FK traffic consumes it.
```

### 12.4 Connection Leaks

```sql
-- Cause: app or pool bugs leave connections open or idle in transaction.
-- Effect: "too many clients already"; idle-in-transaction sessions also pin vacuum.

SELECT state, count(*) AS sessions,
       max(now() - state_change) AS oldest_in_state
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY state
ORDER BY sessions DESC;

-- Fixes:
-- 1. A pooler (PgBouncer, or a pool in each app process) with bounded size.
-- 2. Server-side timeouts:
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET idle_session_timeout = '30min';     -- PG14+; don't apply to pooler connections
ALTER SYSTEM SET tcp_keepalives_idle = 60;
ALTER SYSTEM SET tcp_keepalives_interval = 10;
ALTER SYSTEM SET tcp_keepalives_count = 6;           -- dead peer detected after ~2 minutes
SELECT pg_reload_conf();
-- 3. PG14+: client_connection_check_interval cancels queries whose client has gone away.
```

### 12.5 Long-Running Transactions

```sql
-- Cause: a transaction left open (a forgotten BEGIN in psql, an app holding a transaction
--        across a network call, a long report).
-- Effect: VACUUM can't remove anything newer than its snapshot, in ANY table:
--         bloat everywhere, falling HOT ratios, index-only scans hitting the heap.

SELECT pid, state, now() - xact_start AS xact_age, backend_xmin,
       left(query, 100) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL AND backend_type = 'client backend'
ORDER BY xact_start
LIMIT 10;

-- Prevention: timeouts per role, not one global value that also hits migrations and dumps
ALTER ROLE app_user SET statement_timeout = '30s';
ALTER ROLE app_user SET idle_in_transaction_session_timeout = '1min';
ALTER ROLE app_user SET transaction_timeout = '5min';    -- PG17+
ALTER ROLE reporting SET statement_timeout = '15min';    -- or run reports on a replica

-- Keep transactions short:
-- Good:  BEGIN; UPDATE ...; UPDATE ...; COMMIT;   (milliseconds)
-- Bad:   BEGIN; SELECT ...; <call payment API, wait for user input>; UPDATE ...; COMMIT;
```

### 12.6 Sequential Scan Denial of Service

```sql
-- Cause: a query scans a huge table (missing index, bad estimate, a new filter in a deploy).
-- Effect: saturated disk and CPU and churned OS cache (ring buffers protect shared_buffers,
--         but not the I/O budget), so everyone's latency rises.

SELECT relname, seq_scan, seq_tup_read, idx_scan,
       seq_tup_read / nullif(seq_scan, 0) AS avg_rows_per_seq_scan,
       last_seq_scan                                           -- PG16+
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC
LIMIT 20;

-- Prevention:
-- 1. statement_timeout per role (see 12.5).
-- 2. Plan regression detection: auto_explain + pg_stat_statements per queryid in CI/staging.
-- 3. Run analytics on a replica or OLAP store, not the OLTP primary.
-- 4. enable_seqscan = off is a session-level DEBUGGING tool to see whether an index plan
--    exists; never set it for an application role.
```

### 12.7 Auto-Increment Gap (Sequence Exhaustion)

```sql
-- Cause: an int4 (serial / integer identity) key reaching 2,147,483,647.
--        Sequences don't wrap by default: nextval() fails with
--        "reached maximum value of sequence", so every INSERT errors.
-- Gaps are normal (rollbacks, cached values, crashes); don't use sequence values as counts.

-- Use bigint from day one (identity columns are the modern form of serial):
CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payload jsonb NOT NULL
);

-- Monitor how close every sequence is to its limit:
SELECT schemaname, sequencename, data_type, last_value, max_value,
       round(100.0 * last_value / max_value, 2) AS pct_used
FROM pg_sequences
WHERE last_value IS NOT NULL
ORDER BY pct_used DESC
LIMIT 20;
-- Also check the COLUMN type: an int4 column fed by a bigint sequence fails at 2^31 - 1 too.

-- Fixing a big table: ALTER COLUMN id TYPE bigint rewrites the table and every index under
-- ACCESS EXCLUSIVE (hours of downtime). Online alternative: add a bigint column, sync it with
-- a trigger, backfill in batches, build a unique index CONCURRENTLY, then swap the PK in a
-- short transaction (ADD CONSTRAINT ... PRIMARY KEY USING INDEX), and
-- ALTER SEQUENCE ... AS bigint. Foreign keys referencing it need the same treatment.
```

---

## 13. What Changed in PostgreSQL 17 and 18

Interviewers increasingly ask "what's new?" to check whether your knowledge is current. PostgreSQL 17 was released in September 2024 and PostgreSQL 18 in September 2025. PostgreSQL 19 is in beta as of October 2026.

**PostgreSQL 17**

| Area | Change | Why it matters |
|---|---|---|
| Backup | Incremental backups: `pg_basebackup --incremental` + `pg_combinebackup`, enabled by `summarize_wal` | Built-in incremental physical backups |
| Vacuum | New dead-tuple storage (TidStore): far less memory, no 1 GB limit | Big tables finish vacuum in one index pass |
| Monitoring | `pg_stat_checkpointer` split from `pg_stat_bgwriter`; backend write counters moved to `pg_stat_io`; `pg_wait_events` view | Update dashboards and runbooks |
| Logical replication | `pg_createsubscriber`; failover of logical slots (`failover`, `sync_replication_slots`); `pg_upgrade` keeps slots and subscriptions | Logical replication survives failovers and upgrades |
| Timeouts | `transaction_timeout` | Caps total transaction duration |
| SQL / JSON | `JSON_TABLE`, SQL/JSON constructors and query functions; `MERGE ... RETURNING` | Standard JSON querying |
| COPY | `ON_ERROR ignore` | Skip bad rows during loads |

**PostgreSQL 18**

| Area | Change | Why it matters |
|---|---|---|
| I/O | **Asynchronous I/O** subsystem: `io_method = worker` (default), `io_uring`, or `sync`; `effective_io_concurrency` default 16 | Faster sequential scans, bitmap heap scans and VACUUM on cloud storage |
| Indexes | **B-tree skip scan** on multicolumn indexes | `(a, b)` can serve `WHERE b = ?` when `a` has few distinct values |
| Keys | `uuidv7()` (and `uuidv4()` alias) | Time-ordered UUIDs append to B-trees instead of scattering |
| Schema | **Virtual generated columns** (now the default; `STORED` still available, and required if you need an index) | Computed columns without storage |
| Constraints | `NOT NULL ... NOT VALID`; temporal `PRIMARY KEY/UNIQUE (... WITHOUT OVERLAPS)` and `FOREIGN KEY (..., PERIOD ...)`; `NOT ENFORCED` CHECK/FK | Zero-downtime NOT NULL; built-in temporal integrity |
| DML | `OLD` / `NEW` in `RETURNING` | Return before and after values from UPDATE/DELETE/MERGE |
| Upgrades | `pg_upgrade` keeps planner statistics; `--swap` mode | No long post-upgrade ANALYZE before traffic |
| Vacuum | `autovacuum_vacuum_max_threshold`, `autovacuum_worker_slots` (resize workers without restart), eager freezing, `vacuum_truncate` GUC | Better behaviour on huge tables |
| Locking | Fast-path lock slots sized from `max_locks_per_transaction` | Removes the 16-relation `LockManager` contention cliff |
| initdb | **Data checksums on by default** | Must match when using `pg_upgrade` |
| Security | OAuth authentication; MD5 passwords deprecated (warnings) | Move to SCRAM / SSO |
| Observability | `EXPLAIN ANALYZE` includes BUFFERS by default; more detail in `pg_stat_io`, per-backend I/O and WAL stats; conflict counters in `pg_stat_subscription_stats` | Better diagnosis out of the box |
| Logical replication | `streaming = parallel` default; generated columns can be replicated; conflict detection and logging | Lower apply lag; visible conflicts |

**Coming in PostgreSQL 19 (beta, details may change):** logical replication of sequences (`FOR ALL SEQUENCES`, `REFRESH SEQUENCES`) and eager aggregation (pushing partial `GROUP BY` below joins) are among the committed features. Check the final release notes before citing them.

---

> *This guide covers the foundational knowledge expected of a Staff/Principal engineer working with PostgreSQL. Pair it with hands-on practice: run the queries above against a local PostgreSQL 18 instance, break things on purpose, and read the plans.*
