# 🐘 PostgreSQL — Principal Engineer Deep-Dive

> *Complete PostgreSQL reference for Staff/Principal Engineer interviews — covering architecture, internals, performance tuning, production operations, and 12 staff-level interview questions with evaluation rubrics.*

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Process & Memory Architecture](#2-process--memory-architecture)
3. [Storage Internals](#3-storage-internals)
4. [MVCC & Vacuum](#4-mvcc--vacuum)
5. [WAL & Checkpoints](#5-wal--checkpoints)
6. [Query Execution Pipeline](#6-query-execution-pipeline)
7. [Indexing In Depth](#7-indexing-in-depth)
8. [Partitioning & Sharding](#8-partitioning--sharding)
9. [Performance Tuning](#9-performance-tuning)
10. [Production Operations](#10-production-operations)
11. [Staff-Level Interview Questions](#11-staff-level-interview-questions)
12. [Common Pitfalls & Anti-Patterns](#12-common-pitfalls--anti-patterns)

---

## 1. Architecture Overview

PostgreSQL uses a **multi-process architecture** (not multi-threaded like MySQL). Each client connection gets a dedicated OS process (backend).

```
┌─────────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Instance                            │
│                                                                     │
│  ┌─────────────┐  ┌──────────┐  ┌────────────┐  ┌──────────────┐  │
│  │ Postmaster   │  │ Backend  │  │ Backend    │  │ Backend      │  │
│  │ (Supervisor) │  │ Process 1│  │ Process 2  │  │ Process 3    │  │
│  │  - Fork      │  │  - Parse  │  │  - Parse   │  │  - Parse     │  │
│  │  - Signals   │  │  - Plan   │  │  - Plan    │  │  - Plan      │  │
│  │  - Crash Mgmt│  │  - Exec   │  │  - Exec    │  │  - Exec      │  │
│  │  - Listen on │  │  - Return │  │  - Return  │  │  - Return    │  │
│  │    port 5432 │  └──────────┘  └────────────┘  └──────────────┘  │
│  └──────┬──────┘                                                    │
│         │                                                           │
│         │            ┌─────────────────────────────────────────┐   │
│         │            │         Shared Memory                   │   │
│         └────────────┤  ┌────────────┐ ┌────────┐ ┌────────┐ │   │
│                      │  │Shared      │ │WAL     │ │Clog    │ │   │
│                      │  │Buffers     │ │Buffer  │ │(Commit │ │   │
│                      │  │(8KB pages) │ │(XLOG)  │ │ Log)   │ │   │
│                      │  └────────────┘ └────────┘ └────────┘ │   │
│                      │  ┌────────────┐ ┌──────────────────┐  │   │
│                      │  │Lock Manager│ │Proc Array        │  │   │
│                      │  └────────────┘ └──────────────────┘  │   │
│                      └─────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐        │
│  │BgWriter  │  │WalWriter  │  │Checkpointer│ │Autovacuum│        │
│  │(flush    │  │(flush WAL │  │(checkpoint │ │ Launcher │        │
│  │ dirty    │  │ to disk)  │  │ dirty      │ │ (spawn    │        │
│  │ buffers) │  │           │  │ buffers)   │ │ workers)  │        │
│  └──────────┘  └───────────┘  └──────────┘  └───────────┘        │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐        │
│  │Stats     │  │WAL        │  │Logical   │  │Archiver   │        │
│  │Collector │  │Receiver   │  │Replication│  │(WAL       │        │
│  │          │  │(standby)  │  │Worker    │  │ archiving)│        │
│  └──────────┘  └───────────┘  └──────────┘  └───────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- **Multi-process** over multi-threaded: More resilient (one crash doesn't take down others), better OS scheduling, but higher memory per connection (~5–10MB per connection).
- **Shared memory**: All backends access shared buffers, WAL buffer, lock tables, and process array via System V / POSIX shared memory.
- **Postmaster**: Parent process that forks new backends per connection and handles crash recovery.

---

## 2. Process & Memory Architecture

### 2.1 Key Background Processes

| Process | Role | Configuration |
|---------|------|--------------|
| **Postmaster** | Listens on port, forks backends, handles signals | `port`, `listen_addresses` |
| **BgWriter** | Writes dirty shared buffers to disk proactively | `bgwriter_delay`, `bgwriter_lru_maxpages`, `bgwriter_lru_multiplier` |
| **WalWriter** | Flushes WAL buffer to disk on commit and periodically | `wal_writer_delay`, `wal_writer_flush_after` |
| **Checkpointer** | Performs checkpoints (syncs all dirty buffers) | `checkpoint_timeout`, `max_wal_size`, `checkpoint_completion_target` |
| **Autovacuum Launcher** | Schedules autovacuum workers on tables | `autovacuum_max_workers`, `autovacuum_naptime` |
| **Autovacuum Worker** | Performs actual VACUUM on specific tables | Spawned by launcher, up to `autovacuum_max_workers` |
| **WAL Receiver** | Receives WAL from primary (standby only) | `primary_conninfo` |
| **WAL Sender** | Sends WAL to replicas (primary only) | `max_wal_senders` |
| **Logical Replication Worker** | Applies logical replication changes | `max_logical_replication_workers` |
| **Stats Collector** | Collects table/index/function access stats | `track_counts`, `track_io_timing`, `track_functions` |
| **Archiver** | Copies WAL segments to archive location | `archive_mode`, `archive_command` |

### 2.2 Memory Configuration

```
┌────────────────────────────────────────────────────────────┐
│                    Memory Areas                             │
├────────────────────────────────────────────────────────────┤
│ Shared Memory (allocated at postgres start):                │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Shared Buffers (shared_buffers)      ~25% of RAM       │ │
│ │ Default: 128MB, Recommended: 4-8GB for 32GB RAM       │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ WAL Buffer (wal_buffers)           ~16-64MB            │ │
│ │ Default: 16MB (auto when -1), Should be: 64MB for     │ │
│ │ write-heavy workloads                                  │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Lock Space (max_locks_per_transaction × max_connections)│ │
│ │ Fixed-size in shared memory                            │ │
│ └────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│ Per-Process Memory (allocated per backend):                │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ work_mem (per sort/hash operation per connection)      │ │
│ │ Default: 4MB ×up to number of sort operations          │ │
│ │ 100 connections × 10 sort ops × 4MB = 4GB potential!  │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ maintenance_work_mem (for VACUUM, CREATE INDEX, etc.)  │ │
│ │ Default: 64MB, Should be: 1GB+ for large tables       │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ temp_buffers (per-session temp table buffers)          │ │
│ │ Default: 8MB                                            │ │
│ └────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

**Memory sizing guidelines:**

```sql
-- Rule of thumb for 32GB RAM:
shared_buffers = 8GB                      -- 25% of RAM
effective_cache_size = 24GB               -- 75% of RAM (OS can cache)
wal_buffers = 64MB                         -- Write-heavy: 64MB
work_mem = 32MB                            -- ~100 connections × 32MB = 3.2GB worst case
maintenance_work_mem = 1GB                 -- For vacuum/index creation
random_page_cost = 1.1                     -- For SSD (was 4.0 for HDD)
```

---

## 3. Storage Internals

### 3.1 Physical Storage Layout

```
PGDATA/
├── postgresql.conf         # Main config file
├── pg_hba.conf             # Client authentication
├── global/                 # Cluster-wide tables (pg_database, etc.)
├── base/                   # Per-database directories (OID named)
│   └── <db_oid>/
│       ├── <relfilenode>   # Table data files (heap)
│       ├── <relfilenode>_fsm  # Free space map
│       ├── <relfilenode>_vm   # Visibility map (for index-only scans)
│       └── <relfilenode>.1   # If table > 1GB (segment files)
├── pg_wal/                 # WAL segments (16MB each)
├── pg_stat/                # Statistics files
├── pg_xact/                # Commit log (clog) — tracks transaction status
├── pg_notify/              # LISTEN/NOTIFY data
├── pg_replslot/            # Replication slot data
└── pg_tblspc/              # Symlinks to tablespaces outside PGDATA
```

### 3.2 Page (Block) Structure

PostgreSQL stores data in fixed-size **pages** (default: 8KB).

```
┌─────────────────────────────────────────────────────────────┐
│ PageHeaderData (24 bytes)                                   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ pd_lsn (LSN of last WAL write to this page)             │ │
│ │ pd_checksum (optional page checksum)                    │ │
│ │ pd_lower (offset to start of free space)                │ │
│ │ pd_upper (offset to end of free space)                  │ │
│ │ pd_special (for special index data like B-Tree metadata)│ │
│ │ pd_pagesize_version (page size + version)               │ │
│ │ pd_prune_xid (XID for pruning decisions)                │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ ItemIdData (line pointers — 4 bytes each, from page start) │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ItemId 1: (offset=100, length=48, flags=normal)         │ │
│ │ ItemId 2: (offset=148, length=48, flags=normal)         │ │
│ │ ItemId 3: (offset=196, length=56, flags=normal)         │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────── FREE SPACE ──────────────────────────────┤
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Tuple Data (from page end, growing upward)                  │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ HeapTupleHeader (23+ bytes) + tuple data                │ │
│ │ ┌─────────────────────────────────────────────────────┐ │ │
│ │ │ t_xmin (4B) — creating transaction ID               │ │ │
│ │ │ t_xmax (4B) — deleting/updating transaction ID      │ │ │
│ │ │ t_cid (4B) — command ID within transaction          │ │ │
│ │ │ t_ctid (6B) — current/new version pointer           │ │ │
│ │ │ t_infomask (2B) — status bits                       │ │ │
│ │ │ t_infomask2 (2B) — more status bits + attr count    │ │ │
│ │ │ t_hoff (1B) — header offset                         │ │ │
│ │ └─────────────────────────────────────────────────────┘ │ │
│ │ DATA: column values (possibly TOAST pointers)           │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 TOAST (The Oversized-Attribute Storage Technique)

PostgreSQL has an 8KB page size limit. For large values (> ~2KB), TOAST kicks in:

```
┌──────────────────────────────────────────────────────────────┐
│ TOAST Storage Strategies (per column):                       │
│                                                              │
│ PLAIN      — No TOAST (for fixed-length types like integer) │
│ EXTENDED   — Compress + move to TOAST table (default)       │
│ EXTERNAL   — Move to TOAST table, but don't compress        │
│ MAIN       — Prefer in-line, move to TOAST only if needed   │
│                                                              │
│ TOAST Table: tablename_toast (in pg_toast schema)           │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ chunk_id  — references the original table's ctid         │ │
│ │ chunk_seq — sequence number within the value             │ │
│ │ chunk_data — up to ~2KB of the value                     │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                              │
│ When is TOAST triggered?                                     │
│   - Row size > TOAST_TUPLE_THRESHOLD (default: ~2KB)       │
│   - Selected columns have EXTENDED or EXTERNAL strategy     │
│   - The row can fit without TOAST → stored in-line          │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Free Space Map (FSM)

Each table has an accompanying free space map (`<relfilenode>_fsm`) that tracks available space within each page. When PostgreSQL needs to INSERT a row, it checks the FSM to find a page with enough free space rather than always appending.

```c
// FSM is a binary tree stored across pages:
//   - Leaf nodes: available free space per page (1 byte: 0-255 → 0-8160 bytes)
//   - Internal nodes: max free space of children
//   - Search: O(log N) to find a page with enough free space
//
// FSM structure:
//   Page 0 (root):  [max=200]
//   Page 1:         [max=200, max=150]
//   Page 2:         [max=100, max=200, max=150, max=80]
//   Page 3 (leaf):  [100, 50, 200, 30, 150, 10, 80, 5]  ← each = page free space
//
// Search for 100 bytes of free space:
//   Root: max=200 >= 100 → go left
//   Page 1, slot 0: max=200 >= 100 → go left
//   Page 3, slot 0: 100 >= 100 → FOUND! Use heap page 0
```

### 3.5 Visibility Map (VM)

Each table has a visibility map (`<relfilenode>_vm`) — a simple bitmap where each bit indicates whether a page has only "all-visible" tuples (no dead tuples that need vacuuming).

```
Purpose:
  1. Enables index-only scans: if a page is all-visible, no heap fetch needed
  2. Tells VACUUM which pages to skip: only visit pages NOT marked all-visible

Size: 1 bit per page → ~2.5MB per 1GB table (tiny!)
```

---

## 4. MVCC & Vacuum

### 4.1 PostgreSQL MVCC — Heap Tuple Internals

PostgreSQL's MVCC uses **append-only** storage. UPDATES create new tuple versions; old versions remain in-page until VACUUM reclaims them.

```c
typedef struct HeapTupleHeaderData {
    TransactionId t_xmin;      // XID that created this tuple version
    TransactionId t_xmax;      // XID that deleted/updated this tuple version
    CommandId t_cid;           // Command counter (within-transaction ordering)
    ItemPointerData t_ctid;    // Pointer to self (current) or new version (updated)

    uint16 t_infomask;         // Status bits
    uint16 t_infomask2;        // More status bits + number of attributes
    uint8 t_hoff;              // Header size (offset to actual data)
} HeapTupleHeaderData;

// Key t_infomask bits:
#define HEAP_XMIN_COMMITTED    0x0100  // t_xmin committed
#define HEAP_XMIN_INVALID      0x0200  // t_xmin aborted/invalid
#define HEAP_XMAX_COMMITTED    0x1000  // t_xmax committed
#define HEAP_XMAX_INVALID      0x2000  // t_xmax invalid (no lock/deletion)
#define HEAP_XMAX_IS_MULTI     0x4000  // t_xmax is a MultiXactId (for shared locks)
#define HEAP_UPDATED           0x8000  // This tuple was updated
```

### 4.2 Snapshot Isolation

When a transaction begins, PostgreSQL captures a **snapshot** — the set of in-progress transactions:

```c
typedef struct SnapshotData {
    TransactionId xmin;          // Oldest XID still in progress
    TransactionId xmax;          // Next XID to be assigned (all >= xmax are future)
    TransactionId *xip;          // Array of in-progress XIDs at snapshot time
    uint32 xcnt;                 // Count of in-progress XIDs
    TransactionId *subxip;       // Subtransaction XIDs
    uint32 subxcnt;             // Subtransaction count
    bool takenDuringRecovery;    // Taken during recovery
    CommandId curcid;            // Current command ID (for within-txn visibility)
} Snapshot;
```

**Visibility rules** — a tuple version is visible if:

1. `t_xmin` IS committed AND (t_xmin is committed or t_xmin = my XID)
2. `t_xmax` IS NOT committed OR t_xmax > snapshot.xmax OR t_xmax is my own
3. AND t_xmin is NOT in the in-progress array (xip)

Simplified: `visible = (t_xmin committed AND (t_xmax == 0 OR t_xmax not committed))`

### 4.3 UPDATE Trace

```
Initial: balance = 1000 with t_xmin=100, t_xmax=0

Transaction A (XID=200, REPEATABLE READ):
  BEGIN;  → Snapshot = {xmin=200, xmax=300, in-progress=[200]}

  SELECT balance FROM accounts WHERE id=1;
  → Checks page, finds tuple with t_xmin=100, t_xmax=0
  → t_xmin=100 < snapshot.xmin=200 → committed
  → t_xmax=0 → not deleted
  → VISIBLE! Returns balance=1000

Transaction B (XID=250, READ COMMITTED):
  BEGIN;  → Snapshot = {xmin=250, xmax=350, in-progress=[250]}

  UPDATE accounts SET balance=900 WHERE id=1;
  → Step 1: Lock row (t_xmax is checked/modified)
  → Step 2: Mark OLD tuple: t_xmax=250
  → Step 3: Insert NEW tuple: t_xmin=250, t_xmax=0, balance=900
  → Step 4: Set OLD tuple's t_ctid → (block, offset) of NEW tuple
  → Step 5: Update indexes (if needed for HOT)
  COMMIT;  → t_xmax=250 now marked committed

Transaction A (still active):
  SELECT balance FROM accounts WHERE id=1;
  → Finds OLD tuple: t_xmin=100 (committed, < xmin=200), t_xmax=250
  → Is t_xmax=250 in my snapshot's in-progress array?
  → YES! (250 is < xmax=300 but not in xip → wait, it's between xmin and xmax)
  → Actually: t_xmax=250. xmin=200, xmax=300. xip=[200].
  → 250 is between 200 and 300, AND 250 is NOT in xip=[200].
  → But wait, 250 is NOT committed yet in our snapshot (taken at A's BEGIN)
  → For REPEATABLE READ, the snapshot is taken at BEGIN time.
  → Since 250 is not in xip BUT 250 >= xmin=200,
  → OLD tuple IS visible to A (t_xmax is my concurrent tx, but I use snapshot)
  → Returns balance=1000 (consistent snapshot!)

Transaction C (READ COMMITTED):
  BEGIN;  → Snapshot = {xmin=350, xmax=400, in-progress=[350, 360]}
  SELECT balance FROM accounts WHERE id=1;
  → Finds OLD tuple: t_xmin=100, t_xmax=250 (committed)
  → t_xmax=250 IS committed and < snapshot.xmin=350
  → → OLD tuple is DELETED (t_xmax committed before my txn)
  → Finds NEW tuple: t_xmin=250 (committed), t_xmax=0
  → t_xmin=250 < xmin=350 → committed
  → t_xmax=0 → not deleted
  → VISIBLE! Returns balance=900
```

### 4.4 Vacuum Mechanics

VACUUM is PostgreSQL's garbage collector — it removes dead tuples and updates the visibility map.

```sql
-- VACUUM does:
-- 1. Scans pages NOT marked all-visible in VM
-- 2. Removes dead tuple versions (t_xmax committed and no active snapshot needs them)
-- 3. Defragments remaining tuples within each page (compact free space)
-- 4. Updates FSM with new free space
-- 5. Updates VM (mark pages as all-visible)
-- 6. Optionally removes index entries pointing to dead tuples

-- Autovacuum trigger formula:
--   vacuum_threshold = autovacuum_vacuum_threshold
--     + autovacuum_vacuum_scale_factor * reltuples
--   Default: 50 + 0.2 * reltuples
--   For 1M rows: 50 + 200K = 200,050 dead tuples → triggers VACUUM

-- Autovacuum for table-level tuning:
ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.01);
ALTER TABLE orders SET (autovacuum_vacuum_threshold = 10000);
ALTER TABLE orders SET (autovacuum_vacuum_cost_limit = 2000);
```

**VACUUM cost-based delay:**

```c
// VACUUM throttles itself to avoid saturating I/O:
//   vacuum_cost_limit = 200 (default)
//   vacuum_cost_delay = 2ms (default)
//   vacuum_cost_page_hit = 1  (page already in shared_buffers)
//   vacuum_cost_page_miss = 10 (page must be read from disk)
//   vacuum_cost_page_dirty = 20 (page must be written to disk)
//
// After each batch of operations costing vacuum_cost_limit:
//   → Sleep for vacuum_cost_delay
//
// Disable cost delay for maintenance window:
VACUUM (FREEZE, INDEX_CLEANUP ON, PARALLEL 2) orders;
```

**XID Wraparound:**

```sql
-- PostgreSQL uses 32-bit XIDs: ~4 billion transactions
-- After 2 billion, XIDs wrap around — old transactions appear "future"
-- This is PREVENTED by FREEZE operations

-- Transaction age = current XID - t_xmin
-- When age > autovacuum_freeze_max_age (default: 200M):
--   → Aggressive vacuum is triggered to FREEZE old tuples
-- During wraparound: database becomes READ-ONLY!

-- Monitor XID age:
SELECT datname,
       age(datfrozenxid) AS xid_age,
       mxid_age(datminmxid) AS mxid_age
FROM pg_database
ORDER BY age(datfrozenxid) DESC;

-- Monitor per-table:
SELECT relname,
       age(relfrozenxid) AS xid_age,
       pg_size_pretty(pg_total_relation_size(oid)) AS table_size
FROM pg_class
WHERE relkind IN ('r', 'm')  -- tables and materialized views
ORDER BY age(relfrozenxid) DESC
LIMIT 10;
```

**FREEZE semantics:**

```sql
-- FREEZE sets t_xmin to FrozenTransactionId (2) — always visible
-- Triggered by:
--   1. VACUUM (FREEZE) or VACUUM with table age > vacuum_freeze_min_age
--   2. Autovacuum when age > autovacuum_freeze_max_age
--   3. Explicit FREEZE option

-- For transactional tables that are bulk-loaded once and never updated:
ALTER TABLE historical_data SET (
    autovacuum_freeze_max_age = 2000000000,  -- Delay freeze as long as possible
    toast.autovacuum_freeze_max_age = 2000000000
);

-- For high-churn tables, more aggressive freeze:
ALTER TABLE sessions SET (
    vacuum_freeze_min_age = 10000000,        -- Freeze when age > 10M
    autovacuum_freeze_max_age = 50000000     -- Aggressive trigger at 50M
);
```

### 4.5 HOT Updates (Heap-Only Tuples)

```sql
-- When an UPDATE does NOT change any indexed column:
--   → The new tuple goes into the SAME page (if space permits)
--   → No new index entry is created
--   → The old tuple's t_ctid points to the new tuple
--   → Index still points to old tuple, which redirects via t_ctid

-- Benefits:
--   - No index write amplification (critical for tables with many indexes)
--   - Lower VACUUM overhead (only one page to clean)
--   - Fewer WAL records

-- HOT is blocked if:
--   1. Any indexed column was modified
--   2. The new tuple can't fit in the same page
--   3. The page's pd_prune_xid prevents pruning

-- Monitor HOT ratio:
SELECT relname,
       pg_size_pretty(pg_total_relation_size(oid)) AS table_size,
       n_tup_hot_upd,
       n_tup_upd,
       round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 2) AS hot_ratio
FROM pg_stat_user_tables
WHERE n_tup_upd > 0
ORDER BY hot_ratio;
```

---

## 5. WAL & Checkpoints

### 5.1 WAL Architecture

WAL (Write-Ahead Log) — every transaction change is logged to WAL BEFORE the data page is modified. On crash: replay WAL from last checkpoint.

```
Transaction commit flow:
┌─────────┐    ┌───────────┐    ┌──────────┐    ┌───────────┐
│ Backend │───→│ Shared    │───→│ OS Page  │───→│ Disk      │
│ Process │    │ WAL Buffer│    │ Cache    │    │ (pg_wal)  │
└─────────┘    └───────────┘    └──────────┘    └───────────┘
     │ WAL                     │ fdatasync()   │ 16MB segments
     │ insert                  │ (per commit)  │ recyclable
     ▼                         ▼               ▼
┌───────────────────────────────────────────────────────────────┐
│ LSN (Log Sequence Number): 56-bit offset within WAL          │
│  - insert_lsn:  next LSN to be assigned                      │
│  - write_lsn:   last LSN written to OS page cache           │
│  - flush_lsn:   last LSN fsync'd to disk                     │
│                                                               │
│ WAL Record Header:                                            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ xl_prev (prev record's LSN)                             │ │
│  │ xl_xid (transaction ID)                                 │ │
│  │ xl_len (data length)                                    │ │
│  │ xl_info (resource manager + flags)                      │ │
│  │ xl_rmid (resource manager ID: heap, btree, gin, etc.)  │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

### 5.2 WAL Configuration

```sql
-- wal_level: minimal, replica (default), logical
--   minimal: only crash recovery (no replication)
--   replica: enough for physical replication (including standbys)
--   logical: adds info needed for logical decoding

-- Key settings:
wal_level = replica                    -- For replication
wal_buffers = 64MB                      -- WAL buffer size
wal_writer_delay = 200ms               -- WAL writer flush interval
wal_writer_flush_after = 1MB           -- Flush after this much written
wal_sync_method = fdatasync            -- On Linux: fdatasync (default)
full_page_writes = on                  -- Write full pages on first modification
                                        -- after checkpoint (prevents torn pages)
wal_log_hints = on                     -- Needed for pg_rewind/pg_checksums
wal_compression = zstd                 -- Compress full page images in WAL

-- wal_init_zero = on                  -- Initialize new WAL segments with zeros
-- wal_recycle = on                    -- Recycle WAL segments (less I/O than creating new)
```

### 5.3 Checkpoints

A checkpoint writes ALL dirty buffers from shared_buffers to disk and advances the WAL redo point.

```sql
-- Checkpoint triggers:
--   1. checkpoint_timeout (default: 5min) → timed checkpoint
--   2. max_wal_size (default: 1GB) → WAL size-based checkpoint
--   3. pg_checkpoint (manual)

-- Checkpoint mechanics:
checkpoint_timeout = 15min              -- Max time between checkpoints
max_wal_size = 4GB                      -- If WAL exceeds this → forced checkpoint
min_wal_size = 1GB                      -- Minimum WAL to keep for recycling
checkpoint_completion_target = 0.9      -- Spread checkpoint writes over 90% of
                                         -- checkpoint_timeout window
                                         -- Lower value = faster but more I/O spike
                                         -- Higher value = slower but smoother I/O

-- Per-checkpoint monitor:
--   pg_stat_bgwriter:
--     checkpoints_timed (desired: much higher than req)
--     checkpoints_req (undesired: means WAL size forced a checkpoint)
--     buffers_checkpoint (buffers written by checkpointer)
--     buffers_backend (buffers written by backends — high = BAD)
--     buffers_backend_fsync (backends doing fsync — very BAD)
```

**Checkpoint tuning for high-write workloads:**

```sql
-- Problem: WAL fills up quickly, forcing checkpoints before timeout
-- → lots of checkpoints_req, I/O spikes every few minutes

-- Fix: Increase WAL size to spread out checkpoints
ALTER SYSTEM SET max_wal_size = '16GB';
ALTER SYSTEM SET min_wal_size = '4GB';
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET checkpoint_completion_target = '0.95';
SELECT pg_reload_conf();

-- For write-heavy workloads, also consider:
--   Increasing wal_buffers to absorb write bursts
--   Using wal_compression to reduce WAL volume
--   Tuning bgwriter to keep more buffers clean
```

### 5.4 Full Page Writes

```sql
-- On the FIRST modification of a page after a checkpoint:
--   → PostgreSQL writes the ENTIRE 8KB page to WAL
--   → This prevents "torn page" on partial write (only part of page written during crash)
--   → Without FPI: after crash recovery, page may have half-new, half-old data → corruption!

-- Cost: ~2-3× WAL volume increase (full pages are 8KB vs ~100B for a regular WAL record)

-- Only safe to disable with:
--   - Full_page_writes = off
--   - AND file system that guarantees atomic 8KB writes (e.g., ZFS with blocksize=8K)
--   - AND battery-backed RAID controller with write-back cache
--   → Rarely worth the risk!
```

---

## 6. Query Execution Pipeline

PostgreSQL processes each query through a multi-stage pipeline:

```
SQL Query
    │
    ▼
┌──────────────┐     Lexer + Parser (gram.y, scan.l)
│    Parser    │     Produces: Parse Tree (list of raw parse nodes)
└──────┬───────┘
       │
       ▼
┌──────────────┐     Semantic analysis + name resolution
│   Analyzer   │     Produces: Query Tree (range table, target list, qual, etc.)
└──────┬───────┘
       │
       ▼
┌──────────────┐     Views, rules, security barrier, etc.
│   Rewriter   │     Produces: Rewritten Query Tree(s)
└──────┬───────┘
       │
       ▼
┌──────────────┐     Planner + Optimizer
│    Planner   │     1. Create join permutations
│  + Optimizer │     2. Estimate costs (pg_class, pg_statistics)
└──────┬───────┘     3. Choose cheapest path
       │             Produces: Plan Tree (sequence of plan nodes)
       ▼
┌──────────────┐     Execute plan tree node by node
│   Executor   │     Produces: Result Tuples
└──────┬───────┘
       │
       ▼
    Result Set
```

### 6.1 Parser

```c
// Converts SQL text to a parse tree using LALR(1) grammar
// File: src/backend/parser/gram.y (~16,000 lines!)

// Example: SELECT * FROM users WHERE age > 18

// Parse Tree (simplified):
//   SelectStmt
//   ├── targetList: List of ResTarget (A_Star)
//   ├── fromClause: List of RangeVar (relname="users")
//   └── whereClause: A_Expr
//       ├── kind: AEXPR_OP
//       ├── name: ">"
//       ├── lexpr: ColumnRef (fields=["age"])
//       └── rexpr: A_Const (val=18)
```

### 6.2 Analyzer

```c
// Transforms parse tree → query tree
// Resolves names, checks permissions, adds implicit casts
// File: src/backend/parser/analyze.c

// Query Tree:
//   Query
//   ├── commandType: CMD_SELECT
//   ├── targetList: List of TargetEntry
//   │   └── TargetEntry (resno=1, resname="name")
//   │       └── Var (varno=1, varattno=2, vartype=TEXTOID)
//   ├── rtable: Range Table (RTEs for each FROM entry)
//   │   └── RangeTblEntry (rtekind=RTE_RELATION, relid=<users_oid>)
//   ├── jointree: FromExpr
//   │   └── qual: OpExpr
//   │       ├── opno: 521 (int4gt)
//   │       ├── args: [Var(age), Const(18)]
//   └── targetList: List of TargetEntry
```

### 6.3 Rewriter

Applies rule-based transformations:
- View expansion (replaces view references with their defining queries)
- Security barrier policies
- Rule-based rewriting (CREATE RULE)

### 6.4 Planner / Optimizer

The most complex stage. PostgreSQL uses a **cost-based optimizer** with dynamic programming for join ordering.

```sql
-- Key statistics (pg_class):
--   reltuples: estimated row count
--   relpages: estimated page count

-- Key statistics (pg_statistics / pg_stats):
--   Most Common Values (MCV): top N values with frequencies
--   Histogram: evenly-spaced value boundaries
--   Correlation: physical vs logical ordering (-1 to 1)
--   Null fraction: proportion of NULLs
--   Average width: avg column width in bytes
--   Distinct values: estimated distinct count

-- Cost parameters:
--   seq_page_cost = 1.0     (cost of reading a page sequentially)
--   random_page_cost = 4.0  (cost of reading a page randomly — set to 1.1 for SSD!)
--   cpu_tuple_cost = 0.01   (cost of processing a row)
--   cpu_index_tuple_cost = 0.005 (cost of processing an index entry)
--   cpu_operator_cost = 0.0025 (cost of evaluating a WHERE clause)
```

**Join strategies:**

```c
// PostgreSQL picks from three join strategies based on cost:

// 1. Nested Loop Join — for small inner relations
//    O(|outer| × |inner|) — efficient if inner can use index
//
//    -> Nested Loop (cost=1.14..12.39 rows=5 width=12)
//        -> Seq Scan on users (cost=0.00..1.00 rows=5 width=8)
//        -> Index Scan using idx_orders_user on orders (cost=... rows=1)
//
// 2. Hash Join — for medium-sized relations
//    Build hash on inner relation, probe with outer
//    O(|outer| + |inner|) — good when no sorted order needed
//
//    -> Hash Join (cost=420.00..845.00 rows=6000 width=12)
//        -> Seq Scan on orders (cost=0.00..400.00 rows=6000 width=8)
//        -> Hash (cost=20.00..20.00 rows=1000 width=8)
//            -> Seq Scan on users (cost=0.00..20.00 rows=1000 width=8)
//
// 3. Merge Join — for large sorted relations
//    Sort both, then merge — O(|outer|log|outer| + |inner|log|inner|)
//    Best when both inputs are presorted by join key OR join has ORDER BY
//
//    -> Merge Join (cost=12500.00..25000.00 rows=6000 width=12)
//        -> Sort (cost=5000.00..5200.00 rows=8000 width=8)
//            -> Seq Scan on users
//        -> Sort (cost=7500.00..7800.00 rows=12000 width=8)
//            -> Seq Scan on orders
```

**GEQO (Genetic Query Optimizer):**

```sql
-- When the number of tables in a FROM clause exceeds from_collapse_limit:
--   → PostgreSQL switches from exhaustive search to GEQO
--   → GEQO uses a genetic algorithm (random join permutations)
--   → Does NOT guarantee optimal plan!
--   → Set from_collapse_limit = 20 (default) for most cases

from_collapse_limit = 8     -- Max tables for exhaustive search
geqo = on                    -- Enable genetic optimizer (default)
geqo_threshold = 12          -- Switch to GEQO at this many tables
```

### 6.5 Executor

```c
// Executor iterates through plan tree nodes
// Each node implements three functions:
//   ExecInitNode    — set up state
//   ExecProcNode    — produce next tuple (or NULL when done)
//   ExecEndNode     — clean up

// Execution model: "Volcano-style" pull
//   Each node returns one tuple at a time via ExecProcNode()
//   Parent node calls child's ExecProcNode() to pull tuples
//   Example: HashJoin → Hash → SeqScan (pull from SeqScan to build hash)

// Key executor nodes:
//   Result — returns constant expression
//   ProjectSet — evaluates target list expressions
//   Sort — sorts all tuples (uses work_mem for in-memory, temp files for spilling)
//   Aggregate — GROUP BY aggregation
//   Limit — returns only N tuples, stops pulling from children
//   Materialize — buffers full result in memory/temp
//   Unique — removes adjacent duplicates (needs sorted input)
//   SetOp — INTERSECT, EXCEPT
//   LockRows — FOR UPDATE/FOR SHARE (locks and rechecks visibility)
```

---

## 7. Indexing In Depth

### 7.1 B-Tree Index

The default and most common index type. Balanced tree with fan-out of ~200-400.

```
                  ┌─────────────────────┐
                  │   Meta Page (Page 0) │
                  │   root: Page 1      │
                  └─────────────────────┘
                          │
                          ▼
                  ┌─────────────────────┐
                  │  Root (Page 1):      │
                  │  Keys: [10, 50, 200]│
                  │  Pointers: [2, 3, 4]│
                  └─────┬──────┬──────┬─┘
                        │      │      │
        ┌───────────────┘      │      └───────────────┐
        ▼                      ▼                      ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Internal (Page 2)│ │ Internal (Page 3)│ │ Internal (Page 4)│
│ Keys: [3, 7]     │ │ Keys: [30, 40]   │ │ Keys: [100, 150] │
│ Pointers: [5,6,7]│ │ Pointers: [8,9,10]│ │ Points: [11,12,13]│
└──┬────┬────┬────┘ └──┬────┬────┬────┘ └──┬────┬────┬────┘
   │    │    │          │    │    │          │    │    │
   ▼    ▼    ▼          ▼    ▼    ▼          ▼    ▼    ▼
┌───┐ ┌───┐ ┌───┐   ┌───┐ ┌───┐ ┌───┐   ┌───┐ ┌───┐ ┌───┐
│Leaf │ │Leaf │ │Leaf│ │Leaf│ │Leaf│ │Leaf│ │Leaf│ │Leaf│ │Leaf│
│1,2│ │3,5 │ │7,8│ │10,12│ │30,33│ │40,42│ │100,101│ │150,152│ │200,201│
│→Page6│ │→Page7│ │→Page8│ │→Page9│ │→Page10│ │→Page11│ │→Page12│ │→Page13│ │→Page14│
└────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘
   │←→│   │←→│   │←→│   │←→│   │←→│   │←→│   │←→│   │←→│   │←→│
   Leaf pages form a doubly-linked list for range scans
```

**B-Tree properties:**
- **Ordering**: Keys are sorted within each page and across pages
- **Search**: O(log_400 N) ≈ 3-4 I/Os for 1B rows
- **Insert**: O(log N) — find leaf, insert if space, split page if full
- **Split**: 50-50 split by default; can use suffix truncation in newer versions
- **Deduplication**: PG13+ deduplicates duplicate keys to save space
- **Page-level deletion**: Deleting a key only marks it dead in the leaf page (space reused by new inserts)

```sql
-- B-Tree specific configuration:
--   fillfactor — how full to fill pages (default: 90%, leaves space for updates)
--     Lower fillfactor for high-update tables (avoids page splits)
--     Higher fillfactor for read-only tables (saves space, fewer pages to scan)

CREATE INDEX idx_users_email ON users USING btree (email) WITH (fillfactor = 70);
-- For high-update table: lower fillfactor leaves space for HOT updates

-- Covering Index — includes extra columns for index-only scans:
CREATE INDEX idx_orders_user_date ON orders (user_id, created_at) INCLUDE (amount, status);
-- Index contains amount and status at leaf level → no heap fetch needed
```

### 7.2 GiST Index

Generalized Search Tree — extensible index type for custom data types.

```
Uses: geometric data (points, polygons), full-text search (alternative to GIN),
      range types, inet/cidr

Structure: balanced tree where internal nodes store bounding predicates
  - For points: bounding box of children
  - For ranges: union range of children
  - For full-text: union of tsvector lexemes

Query: "contains" or "overlaps" check at each level
  - If this node's bbox doesn't contain the query → prune entire subtree
  - If it does → recurse to children
```

```sql
-- GiST for geometric search (e.g., find all restaurants within 5km):
CREATE INDEX idx_locations ON venues USING gist (location);
SELECT * FROM venues
WHERE location <@ circle(point(40.7128, -74.0060), 5000);

-- GiST for range types (e.g., find overlapping booking periods):
CREATE INDEX idx_booking_period ON bookings USING gist (booking_period);
SELECT * FROM bookings
WHERE booking_period && '[2024-06-01, 2024-06-07]'::tstzrange;

-- GiST for full-text search (supports ranking better than GIN):
CREATE INDEX idx_doc_fts ON documents USING gist (to_tsvector('english', body));
```

### 7.3 GIN Index

Generalized Inverted Index — maps keys (tokens) to rows containing them.

```
Structure:
┌─────────────────────────────────────────────────────────────┐
│ GIN Index — Inverted Index Structure                        │
│                                                             │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│ │ entry tree   │  │ entry tree   │  │ entry tree   │       │
│ │ (B-Tree)     │  │ (B-Tree)     │  │ (B-Tree)     │       │
│ │              │  │              │  │              │       │
│ │ token_1 ─────┼──│ token_2 ─────┼──│ token_3 ─────┼──... │
│ └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│        │                 │                 │                │
│        ▼                 ▼                 ▼                │
│ ┌──────────┐      ┌──────────┐      ┌──────────┐           │
│ │Posting   │      │Posting   │      │Posting   │           │
│ │List      │      │List      │      │List      │           │
│ │row1,row3,│      │row2,row5 │      │row3,row4 │           │
│ │row7      │      │          │      │          │           │
│ └──────────┘      └──────────┘      └──────────┘           │
└─────────────────────────────────────────────────────────────┘

Properties:
  - Very fast for "contains" queries (any of these tokens present?)
  - Slow to build and update (must rebuild posting lists)
  - Large: posting lists can be hundreds of KB per frequent token
```

```sql
-- GIN for full-text search:
CREATE INDEX idx_docs_fts ON documents USING gin (to_tsvector('english', title || ' ' || body));

-- GIN for JSONB:
CREATE INDEX idx_profiles_meta ON profiles USING gin (metadata jsonb_path_ops);

-- GIN for arrays (int[], text[]):
CREATE INDEX idx_tags ON articles USING gin (tags);

-- FASTUPDATE — buffer pending inserts instead of immediate posting list update:
CREATE INDEX idx_fts ON documents USING gin (fts) WITH (fastupdate = on, gin_pending_list_limit = 4MB);
-- Trade-off: faster writes, but queries must scan pending list too
```

### 7.4 BRIN Index

Block Range Index — stores summary (min/max) for contiguous page ranges.

```
Physical table pages:
┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐
│ P0  │ P1  │ P2  │ P3  │ P4  │ P5  │ P6  │ P7  │ P8  │ P9  │
│ jan │ jan │ jan │ jan │ feb │ feb │ feb │ feb │ mar │ mar │
└─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘

BRIN (pages_per_range=4):
┌──────────────────────────────────────────────┐
│ Range 0 (P0-P3): min=Jan-01, max=Jan-31       │
│ Range 1 (P4-P7): min=Feb-01, max=Feb-28       │
│ Range 2 (P8-P9): min=Mar-01, max=Mar-31       │
└──────────────────────────────────────────────┘

Query: SELECT * FROM events WHERE created_at = 'Feb-15'
  → Check each range: Feb-15 in Range 0? No. In Range 1? Yes!
  → Only need to scan P4-P7 (4 pages instead of 10)
  → 60% reduction in I/O

Space: BRIN is 100-1000× smaller than B-Tree
  - 1TB table with BRIN (pages_per_range=32): ~2MB
  - Same table with B-Tree: ~30GB
```

```sql
-- BRIN for append-only time-series data:
CREATE INDEX idx_events_created ON events USING brin (created_at)
    WITH (pages_per_range = 32);

-- BRIN for naturally correlated data:
CREATE INDEX idx_orders_created ON orders USING brin (created_at)
    WITH (pages_per_range = 16, autosummarize = on);
-- autosummarize: automatically summarize new pages when table grows

-- Multiple columns in BRIN:
CREATE INDEX idx_events_range ON events USING brin (created_at, category_id)
    WITH (pages_per_range = 64);

-- BRIN with minmax-multi (PG14+ — handles non-correlated data better):
CREATE INDEX idx_locations ON venues USING brin (latitude, longitude)
    WITH (pages_per_range = 32, pages_per_range = 32);
```

### 7.5 Index Selection Guide

| Workload | Recommended Index | Why |
|----------|------------------|-----|
| Primary key lookups | B-Tree | O(log N), exact match |
| Range queries on timestamp | BRIN (append-only) | 1000× smaller, fast enough |
| Range queries on timestamp | B-Tree | For OLTP with random inserts |
| Full-text search | GIN | Inverted index = fast token lookup |
| JSONB queries | GIN (jsonb_path_ops) | Indexes entire JSON structure |
| Geospatial queries | GiST | R-Tree semantics for bounding boxes |
| Exact match on high-cardinality | B-Tree | Fast, small, supports ordering |
| Exact match on low-cardinality | B-Tree partial | Partial index per value |
| Exclude constraints | GiST | Range exclusion (no overlaps) |
| ULID/UUID ordered inserts | B-Tree (asc) | Inserts at rightmost leaf = no splits |

---

## 8. Partitioning & Sharding

### 8.1 Declarative Partitioning (PG10+)

```sql
-- Range partitioning (most common):
CREATE TABLE measurements (
    log_time timestamptz NOT NULL,
    sensor_id int NOT NULL,
    value float NOT NULL
) PARTITION BY RANGE (log_time);

-- Create monthly partitions:
CREATE TABLE measurements_2024_01 PARTITION OF measurements
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE measurements_2024_02 PARTITION OF measurements
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- List partitioning:
CREATE TABLE regions (
    id int,
    name text,
    region text
) PARTITION BY LIST (region);

CREATE TABLE regions_na PARTITION OF regions
    FOR VALUES IN ('US', 'CA', 'MX');
CREATE TABLE regions_eu PARTITION OF regions
    FOR VALUES IN ('UK', 'DE', 'FR', 'IT');

-- Hash partitioning:
CREATE TABLE users_partitioned (
    user_id int,
    name text
) PARTITION BY HASH (user_id);

CREATE TABLE users_p0 PARTITION OF users_partitioned
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE users_p1 PARTITION OF users_partitioned
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);

-- Sub-partitioning (partition within partition):
CREATE TABLE logs (
    log_date date NOT NULL,
    log_level text NOT NULL,
    message text
) PARTITION BY RANGE (log_date);

CREATE TABLE logs_2024 PARTITION OF logs
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')
    PARTITION BY LIST (log_level);

CREATE TABLE logs_2024_error PARTITION OF logs_2024
    FOR VALUES IN ('ERROR', 'FATAL');
```

**Partitioning benefits:**
- **Partition pruning**: Queries filtering on partition key only scan relevant partitions
- **Bulk deletion**: DROP PARTITION is instant (vs DELETE millions of rows)
- **Parallelism**: Parallel seq scan can scan partitions concurrently
- **Data management**: Archive old partitions independently

**Partitioning gotchas:**
```sql
-- 1. No cross-partition unique constraints (unless partition key IS the unique key)
--    ❌ UNIQUE (email) on partitioned table — NOT SUPPORTED
--    ✅ UNIQUE (user_id, email) — works if user_id is partition key

-- 2. Trigger on parent doesn't automatically apply to partitions
--    → You must create triggers on each partition individually

-- 3. Row triggers on partitions in PG14+
--    Before PG14, row triggers had to be created per-partition

-- 4. Partition-wise join (PG12+):
--    Enable with: enable_partitionwise_join = on
--    Only beneficial for large partitioned tables with similar partition schemes

-- 5. Autovacuum must be tuned per partition
ALTER TABLE measurements_2024_01 SET (autovacuum_vacuum_scale_factor = 0.01);
```

### 8.2 Sharding via Foreign Data Wrappers (FDW)

```sql
-- PostgreSQL doesn't have built-in sharding like Vitess/MongoDB
-- But can approximate using postgres_fdw + partitioning

-- Step 1: Create server connections to remote PostgreSQL instances
CREATE SERVER shard1 FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'shard1.example.com', port '5432', dbname 'appdb');
CREATE SERVER shard2 FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'shard2.example.com', port '5432', dbname 'appdb');

-- Step 2: Create user mappings
CREATE USER MAPPING FOR app_user SERVER shard1
    OPTIONS (user 'shard_user', password '****');
CREATE USER MAPPING FOR app_user SERVER shard2
    OPTIONS (user 'shard_user', password '****');

-- Step 3: Create foreign tables
CREATE FOREIGN TABLE users_shard1 (
    user_id int NOT NULL,
    name text NOT NULL,
    email text
) SERVER shard1 OPTIONS (schema_name 'public', table_name 'users');

CREATE FOREIGN TABLE users_shard2 (
    user_id int NOT NULL,
    name text NOT NULL,
    email text
) SERVER shard2 OPTIONS (schema_name 'public', table_name 'users');

-- Step 4: Use partitioning for routing
CREATE TABLE users_global (
    user_id int NOT NULL,
    name text NOT NULL,
    email text
) PARTITION BY HASH (user_id);

CREATE TABLE users_s1 PARTITION OF users_global
    FOR VALUES WITH (MODULUS 2, REMAINDER 0);
ALTER TABLE users_s1 NO INHERIT users_global;
-- Actually, just use it as a view/union all on the foreign tables
```

**Production sharding in PostgreSQL:**
```yaml
Real solutions for horizontal scaling:
  1. Citus (CitusData): True distributed PostgreSQL
     - Coordinator node + worker nodes
     - Handles sharding, rebalancing, cross-shard queries
     - Used by: Algolia, Heap, Twilio SendGrid

  2. pg_partman: Partition management extension
     - Automates partition creation and maintenance
     - Time-based and serial-based partitioning
     - Retention policies (auto-drop old partitions)

  3. Application-level sharding:
     - Hash routing in application layer
     - Use PostgreSQL LISTEN/NOTIFY for cache invalidation
     - Separate PostgreSQL clusters per shard
```

---

## 9. Performance Tuning

### 9.1 Configuration Checklist

```ini
# ── MEMORY ─────────────────────────────────────────────────
shared_buffers = 8GB                   # 25% of RAM
effective_cache_size = 24GB            # 75% of RAM
work_mem = 32MB                        # Per-operation (be careful!)
maintenance_work_mem = 1GB             # For VACUUM, CREATE INDEX, etc.
wal_buffers = 64MB                     # 1-2% of shared_buffers
max_worker_processes = 8               # For parallel queries
max_parallel_workers_per_gather = 4    # Per-query parallelism
max_parallel_workers = 8               # Total parallel workers
parallel_tuple_cost = 0.01             # Cost of transferring a tuple between workers
parallel_setup_cost = 1000             # Cost of starting parallel workers

# ── WAL ──────────────────────────────────────────────────
wal_level = replica                    # For replication + pg_rewind
max_wal_size = 4GB                     # Spread checkpoints
min_wal_size = 1GB
checkpoint_completion_target = 0.9     # Smooth I/O
wal_compression = zstd                 # Compress full page images
wal_log_hints = on                     # Needed for pg_rewind

# ── PLANNER ─────────────────────────────────────────────────
random_page_cost = 1.1                 # SSD! (was 4.0 for HDD)
effective_cache_size = 24GB            # Tells planner about OS cache
default_statistics_target = 500        # More detailed stats (default: 100)

# ── CONNECTIONS ──────────────────────────────────────────
max_connections = 100                  # Each connection: ~5-10MB
superuser_reserved_connections = 5     # Reserved for admin

# ── AUTOVACUUM ─────────────────────────────────────────────
autovacuum_max_workers = 3             # Parallel VACUUM workers
autovacuum_naptime = 1min              # Check every minute
autovacuum_vacuum_threshold = 50       # Min dead tuples
autovacuum_vacuum_scale_factor = 0.02  # % of table
autovacuum_vacuum_cost_limit = -1      # Use vacuum_cost_limit (200)
autovacuum_vacuum_cost_delay = 2ms     # Throttle I/O

# ── LOGGING ─────────────────────────────────────────────
log_destination = 'stderr'
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%a.log'
log_truncate_on_rotation = on
log_rotation_age = 1d
log_min_duration_statement = 1000     # Log queries over 1 second
log_autovacuum_min_duration = 0       # Log all autovacuum operations
log_checkpoints = on                  # Log checkpoint details
log_connections = on
log_disconnections = on
log_lock_waits = on                   # Log waits > deadlock_timeout
log_temp_files = 0                    # Log all temp file creation
log_statement = 'ddl'                 # Log DDL statements
```

### 9.2 Index Maintenance

```sql
-- Find unused indexes (reads vs writes):
SELECT schemaname || '.' || relname AS table_name,
       indexrelname AS index_name,
       idx_scan AS index_scans,
       idx_tup_read AS tuples_read,
       idx_tup_fetch AS tuples_fetched,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC;

-- Find duplicate indexes:
SELECT pg_size_pretty(sum(pg_relation_size(idx1.indexrelid))::bigint) AS total_size,
       format('DROP INDEX %s;', array_agg(idx1.indexrelid::regclass)::text[]) AS drop_command
FROM pg_index AS idx1
JOIN pg_index AS idx2 ON idx1.indrelid = idx2.indrelid
    AND idx1.indexrelid < idx2.indexrelid
    AND idx1.indkey = idx2.indkey
    AND idx1.indclass = idx2.indclass
    AND idx1.indoption = idx2.indoption
    AND idx1.indisprimary = idx2.indisprimary
WHERE idx1.indisprimary = false
GROUP BY idx1.indexrelid, idx2.indexrelid;

-- Rebuild indexes (bloated indexes):
REINDEX INDEX CONCURRENTLY idx_users_email;
-- Or rebuild all indexes on table:
REINDEX TABLE CONCURRENTLY users;

-- Monitor index bloat:
SELECT schemaname || '.' || relname AS table_name,
       indexrelname AS index_name,
       pg_relation_size(indexrelid) AS index_size,
       idx_scan AS index_scans,
       idx_tup_read,
       idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC;
```

### 9.3 Query Performance Monitoring

```sql
-- Track slow queries with pg_stat_statements (MUST HAVE extension):
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT queryid,
       LEFT(query, 80) AS query_preview,
       calls,
       round(total_exec_time::numeric, 2) AS total_ms,
       round(mean_exec_time::numeric, 2) AS avg_ms,
       round(min_exec_time::numeric, 2) AS min_ms,
       round(max_exec_time::numeric, 2) AS max_ms,
       round(stddev_exec_time::numeric, 2) AS stddev_ms,
       rows,
       round(shared_blks_hit::numeric / nullif(shared_blks_hit + shared_blks_read, 0) * 100, 2) AS cache_hit_ratio,
       temp_bytes,
       wal_bytes
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;

-- Find queries with high I/O per execution:
SELECT queryid,
       LEFT(query, 80) AS query_preview,
       calls,
       round(shared_blks_read::numeric / nullif(calls, 0), 2) AS avg_blocks_read,
       round(temp_bytes::numeric / nullif(calls, 0), 2) AS avg_temp_bytes,
       round(wal_bytes::numeric / nullif(calls, 0), 2) AS avg_wal_bytes
FROM pg_stat_statements
WHERE calls > 100
ORDER BY shared_blks_read DESC
LIMIT 20;

-- Clear statistics to reset baseline:
SELECT pg_stat_statements_reset();
```

### 9.4 Wait Event Analysis

```sql
-- Current wait events (what is the database waiting for right now):
SELECT pid,
       wait_event_type,
       wait_event,
       state,
       LEFT(query, 100) AS query,
       age(clock_timestamp(), query_start) AS query_duration,
       age(clock_timestamp(), state_change) AS state_duration
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend'
ORDER BY age(clock_timestamp(), query_start) DESC;

-- Common wait events and their meanings:
--   Client:            Waiting on client (idle in transaction, etc.)
--   IO:                Waiting for I/O (BufferIO, WALWrite, DataFileFlush, etc.)
--   Lock:              Waiting for heavyweight lock (relation, transactionid, etc.)
--   LWLock:            Waiting for lightweight lock (buffer mapping, etc.)
--   IPC:               Waiting for inter-process communication
--   Timeout:           Waiting for timeout (deadlock timer, etc.)
--   Extension:         Waiting in extension
--   Activity:          Active backend (BgWriterHibernate, AutoVacuumSleep, etc.)

-- Historical wait events (with pg_stat_kcache or pgbadger):
-- PgBadger: https://github.com/darold/pgbadger
```

---

## 10. Production Operations

### 10.1 High Availability with Patroni

Patroni is the de-facto HA solution for PostgreSQL, using a DCS (Distributed Consensus Store) like etcd, ZooKeeper, or Consul.

```yaml
Patroni topology:
┌──────────────────────────────────────────────────────────────────┐
│                         etcd cluster                              │
│                   (leader election, config store)                  │
│                     ┌─────┐ ┌─────┐ ┌─────┐                       │
│                     │etcd1│ │etcd2│ │etcd3│                       │
│                     └─────┘ └─────┘ └─────┘                       │
│                           │       │       │                        │
└───────────────────────────┼───────┼───────┼────────────────────────┘
                            │       │       │
  ┌─────────────────────────┼───────┼───────┼─────────────────────────┐
  │                  Patroni manages failover                         │
  │                                                                   │
  │    ┌────────────────────┐    ┌────────────────────┐              │
  │    │  Primary (Leader)   │    │  Replica (Standby) │              │
  │    │  patroni-1          │───→│  patroni-2         │              │
  │    │  PostgreSQL 16      │    │  PostgreSQL 16     │              │
  │    │  HAProxy backend 1  │    │  HAProxy backend 2 │              │
  │    └────────────────────┘    └────────────────────┘              │
  │                                                                   │
  │    ┌────────────────────┐    ┌────────────────────┐              │
  │    │  Replica (Standby)  │    │  Replica (Synchronous)│           │
  │    │  patroni-3         │    │  patroni-4          │              │
  │    │  PostgreSQL 16      │    │  PostgreSQL 16      │              │
  │    │  HAProxy backend 3  │    │  HAProxy backend 4  │              │
  │    └────────────────────┘    └────────────────────┘              │
  │                                                                   │
  │                  ┌─────────────────────────────┐                 │
  │                  │ HAProxy or PgBouncer        │                  │
  │                  │ (Connection routing)        │                  │
  │                  │ 192.168.1.100:5432 → Primary│                  │
  │                  │ 192.168.1.100:5433 → Replica│                  │
  │                  └─────────────────────────────┘                 │
  └──────────────────────────────────────────────────────────────────┘

Key features:
  - Automatic failover (< 30s RTO)
  - Clean promotion (no split-brain with DCS-based leader key)
  - Automatic rejoin (former primary rejoins as replica)
  - Scheduled switchovers (maintenance window promotion)
  - REST API for management
```

### 10.2 Backup & Recovery

```sql
── Logical Backup (pg_dump) ───────────────────────────────

-- Full database backup (single transaction, consistent snapshot):
pg_dump -h localhost -U app_user -d mydb -Fc -f mydb.dump

-- Restore (parallel restore for speed):
pg_restore -h localhost -U app_user -d mydb -j 4 mydb.dump

-- For larger databases, use directory format for parallelism:
pg_dump -h localhost -U app_user -d mydb -Fd -j 4 -f mydb_dump_dir/
pg_restore -h localhost -U app_user -d mydb -j 4 mydb_dump_dir/

-- Selective backup (specific tables or schemas):
pg_dump -h localhost -U app_user -d mydb -t public.users -t public.orders -Fc -f partial.dump

── Physical Backup (pg_basebackup) ─────────────────────────

-- Full base backup (used for PITR and replica setup):
pg_basebackup -h primary_host -D /backup/directory -X stream -P -v

-- With replication slot (prevents WAL cleanup during backup):
pg_basebackup -h primary_host -D /backup/directory -X stream -S backup_slot1 -P -v

── Point-in-Time Recovery (PITR) ─────────────────────────

-- 1. Set up WAL archiving on primary:
wal_level = replica                    -- Or 'logical'
archive_mode = on
archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'

-- 2. Take base backup:
pg_basebackup -h primary_host -D /data/pgdata/backup -X stream

-- 3. Configure recovery.conf (PG11-) or use pg_ctl (PG12+):
-- In postgresql.conf on standby:
restore_command = 'cp /archive/%f %p'  -- Recover from archived WAL
recovery_target_time = '2024-06-15 14:30:00 UTC'
recovery_target_action = 'promote'

-- 4. Start PostgreSQL — it will replay WAL to the target time
pg_ctl -D /data/pgdata start

-- 5. After recovery: promote to primary
pg_ctl -D /data/pgdata promote

── Continuous Archiving ────────────────────────────────────

-- WAL archiving with pgBackRest (recommended for production):
-- pgBackRest: https://pgbackrest.org/

-- Configuration:
[mycluster]
pg1-path=/data/pgdata/16/main
pg1-port=5432
repo1-path=/backup/pgbackrest
repo1-retention-full=30

-- Differential + full backup schedule:
pgbackrest --stanza=mycluster --type=full backup          # Weekly (Sunday)
pgbackrest --stanza=mycluster --type=diff backup          # Daily
pgbackrest --stanza=mycluster --type=incr backup          # Hourly

-- Point-in-time recovery to specific time:
pgbackrest --stanza=mycluster --type=time \
    --target="2024-06-15 14:30:00-05:00" \
    --target-action=promote restore
```

### 10.3 Monitoring & Alerting

```sql
── Key monitoring queries ──────────────────────────────────

-- 1. Replication lag:
SELECT pid,
       application_name,
       client_addr,
       state,
       write_lag,
       flush_lag,
       replay_lag,
       pg_size_pretty(pg_wal_lsn_diff(
           pg_current_wal_lsn(),
           replay_lsn
       )) AS lag_bytes
FROM pg_stat_replication;

-- 2. Connection utilization:
SELECT max_conn,
       used_conn,
       round(used_conn::numeric / max_conn * 100, 1) AS pct_used
FROM (
    SELECT setting::int AS max_conn
    FROM pg_settings WHERE name = 'max_connections'
) AS config,
(
    SELECT count(*) AS used_conn
    FROM pg_stat_activity
    WHERE backend_type = 'client backend' AND state IS NOT NULL
) AS active;

-- 3. Table bloat estimate:
SELECT schemaname || '.' || relname AS table_name,
       pg_size_pretty(pg_relation_size(relid)) AS table_size,
       round(100 * (1 - n_live_tup::numeric / nullif(reltuples, 0)), 2) AS dead_pct,
       n_dead_tup,
       last_autovacuum,
       last_vacuum,
       n_mod_since_analyze
FROM pg_stat_user_tables
JOIN pg_class ON pg_stat_user_tables.relid = pg_class.oid
WHERE reltuples > 0
ORDER BY n_dead_tup DESC
LIMIT 20;

-- 4. Long-running transactions:
SELECT pid,
       state,
       LEFT(query, 100) AS query,
       age(clock_timestamp(), xact_start) AS txn_duration,
       age(clock_timestamp(), query_start) AS query_duration,
       wait_event_type,
       wait_event,
       pg_blocking_pids(pid) AS blockers
FROM pg_stat_activity
WHERE state IN ('active', 'idle in transaction')
  AND xact_start IS NOT NULL
  AND backend_type = 'client backend'
  AND pid <> pg_backend_pid()
ORDER BY age(clock_timestamp(), xact_start) DESC
LIMIT 20;
```

### 10.4 Golden Signals for PostgreSQL

```yaml
Latency:
  - p50/p99 query latency (by queryid from pg_stat_statements)
  - WAL write latency
  - Replication lag (bytes and time)

Traffic:
  - Queries per second (by type: SELECT, INSERT, UPDATE, DELETE)
  - Connections per second
  - WAL generation rate (MB/s)

Errors:
  - Connection failures (auth errors, too many connections)
  - Deadlock count
  - Serialization failures (40001 errors)
  - Out of shared memory errors
  - XID wraparound approaching

Saturation:
  - CPU usage (backend processes)
  - Disk I/O (read/write latency, IOPS)
  - Shared buffers hit ratio (target > 99%)
  - Disk space (pg_wal, tablespace, archive)
  - Lock queue depth (from pg_locks)
  - Autovacuum queue depth (work done vs needed)
```

---

## 11. Staff-Level Interview Questions

### Q1: "Design a horizontally scalable PostgreSQL architecture for a SaaS platform with 10K tenants, each with up to 1GB of data. Compare and contrast multi-tenant strategies."

**What They're Really Testing:** Whether you understand the trade-offs between isolation, operational complexity, and query performance in multi-tenant database architectures.

**Answer:**

**Option 1: Database per Tenant**

```
┌─────────────────────────────────────────────────────┐
│ Router Service                                      │
│ tenant_db_map = {                                   │
│   123: "host=db1.example.com dbname=tenant_123",    │
│   456: "host=db2.example.com dbname=tenant_456",    │
│ }                                                   │
└──────────┬──────────────────────────────────────────┘
           │
    ┌──────┴──────┐
    │              │
┌───▼───┐    ┌───▼───┐
│ DB 1   │    │ DB 2   │    ... up to N nodes
│ ┌─────┐│    │ ┌─────┐│
│ │T_123││    │ │T_456││
│ │T_789││    │ │T_012││
│ └─────┘│    │ └─────┘│
└────────┘    └────────┘
```

```yaml
Pros:
  - Strongest isolation (one tenant's heavy query can't affect others)
  - Easy restore per tenant
  - No cross-tenant data leakage risk
  - Can tune per-tenant (different configs per DB)

Cons:
  - Connection pooling overhead (many databases)
  - Migration pain (ALTER TABLE × 10K databases)
  - Monitoring complexity (10K databases to watch)
  - Operational cost (backup 10K databases)

When to use:
  - Enterprise SaaS with large tenants (> 100GB each)
  - Compliance requirements (GDPR, HIPAA, SOC2 per-tenant isolation)
  - Small number of large tenants (< 1000)
```

**Option 2: Schema per Tenant**

```sql
-- Same database, different schemas:
CREATE SCHEMA tenant_123;
CREATE TABLE tenant_123.users (id serial, name text);
CREATE TABLE tenant_123.orders (id serial, amount numeric);

CREATE SCHEMA tenant_456;
CREATE TABLE tenant_456.users (id serial, name text);

-- Set search_path per connection:
-- SET search_path TO tenant_123, public;
```

```yaml
Pros:
  - Good isolation (can't query other schemas without prefix)
  - Single database → simple backup and monitoring
  - Can restore individual schemas (partial pg_dump/restore)
  - Shared connection pool across tenants

Cons:
  - Single database is bottleneck (connection limit, buffer pool)
  - Migration still painful (run per schema)
  - Shared sequence namespace (can cause XID pressure)

When to use:
  - Mid-tier SaaS (10s-100s of tenants)
  - Each tenant < 10GB
```

**Option 3: Row-Level Tenant Filtering**

```sql
CREATE TABLE users (
    id serial,
    tenant_id int NOT NULL,
    name text NOT NULL
);

-- Enable Row-Level Security:
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id')::int);

-- Application sets tenant context:
-- SET app.tenant_id = '123';
-- SELECT * FROM users;  -- Only returns rows for tenant 123
```

```yaml
Pros:
  - Simplest operations (single database, single schema)
  - Shared buffer pool → efficient resource utilization
  - Fast migrations (run once)
  - Scale vertically or with read replicas

Cons:
  - WORST isolation: one tenant's bad query can affect ALL
  - RLS adds overhead to every query
  - Hard to estimate per-tenant resource usage
  - Max database size becomes bottleneck

When to use:
  - B2C applications where tenants are small (< 1GB each)
  - Large number of small tenants (100K+)
  - When operational simplicity is most important
```

**Recommendation for 10K tenants × 1GB = 10TB total:**

```yaml
Hybrid Approach: Schema-per-tenant with sharding

  Shard 1: tenants 1-2500 (database: shard1, 2500 schemas ≈ 2.5TB)
  Shard 2: tenants 2501-5000 (database: shard2, 2500 schemas)
  Shard 3: tenants 5001-7500 (database: shard3, 2500 schemas)
  Shard 4: tenants 7501-10000 (database: shard4, 2500 schemas)

  Each shard:
    - Dedicated PostgreSQL server (32GB RAM, 4TB SSD)
    - pg_partman for automated partition management
    - PgBouncer for connection pooling
    - WAL archiving per shard

Routing:
  tenant_shard_map in Redis (fast lookup, cache with TTL)
  Application-level: shard_id = hash(tenant_id) % 4
  Or use: https://github.com/pgshard/pgshard

Operations:
  - pg_dump per shard (parallelizable)
  - ALTER TABLE per shard (4 vs 10000)
  - Monitoring per shard (4 vs 10000 dashboards)
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Isolation levels** | Identifies 3 strategies and quantifies isolation/ops cost trade-offs |
| **Shard sizing** | Calculates realistic numbers (2500 tenants/shard, 2.5TB each) |
| **Operational complexity** | Considers migration, backup, monitoring at scale |
| **Recommendation** | Proposes a WORKABLE hybrid (schema-per-tenant + sharding) |

---

### Q2: "A PostgreSQL INSERT that takes 1ms suddenly takes 5 seconds. The table has 1 billion rows, 10 indexes, and receives 50K writes/second. Walk through your debugging process."

**What They're Really Testing:** Whether you can systematically debug performance degradation in PostgreSQL under write-heavy workloads.

**Answer:**

**Triage steps:**

```sql
-- Step 1: Check wait events
SELECT pid, wait_event_type, wait_event, state,
       age(clock_timestamp(), query_start) AS duration,
       LEFT(query, 100) AS query
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid()
ORDER BY duration DESC;

-- Likely suspects:
--   "WALWrite" → WAL bottleneck (checkpoint, disk I/O)
--   "BufferIO" → shared_buffers full, eviction thrashing
--   "transactionid" → lock contention on relation
--   "IO/DataFileWrite" → index page writes (10 indexes!)

-- Step 2: Check checkpoint pressure
SELECT checkpoints_timed, checkpoints_req,
       buffers_checkpoint, buffers_clean, buffers_backend,
       buffers_backend_fsync, maxwritten_clean,
       round(100.0 * buffers_backend / nullif(buffers_checkpoint + buffers_clean + buffers_backend, 0), 2) AS backend_write_pct
FROM pg_stat_bgwriter;

-- If buffers_backend_fsync > 0 or buffers_backend > 10%:
--   → Backends are doing their OWN writes (BAD!)
--   → Checkpointer and bgwriter can't keep up

-- Step 3: Check WAL generation
SELECT pg_size_pretty(sum(size)) AS wal_size,
       count(*) AS wal_segments,
       min(name) AS oldest_wal,
       max(name) AS newest_wal
FROM pg_ls_waldir();

-- Step 4: Check index bloat
SELECT schemaname || '.' || relname AS table_name,
       indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(indexrelid) DESC;
```

**Root cause analysis:**

```yaml
Most likely causes:

1. Index bloat + maintenance:
   - 10 indexes on the table
   - Each INSERT must update ALL 10 indexes (write amplification: 1000×)
   - Bloated indexes mean more leaf pages to update per index
   - During VACUUM: index cleanup competes with INSERT I/O
   → Solution: reduce indexes, use partial indexes, REINDEX CONCURRENTLY

2. Checkpoint I/O storm:
   - 50K writes/s × ~200 bytes WAL = 10MB/s WAL generation
   - With 10 indexes, each UPDATE may generate more WAL (index page full writes)
   - When max_wal_size reached: BARRIER checkpoint (all dirty buffers flushed)
   - I/O spikes to 1000+ IOPS, backend processes stall
   → Solution: increase max_wal_size, tune bgwriter

3. XID wraparound protection:
   - 1B rows × 50K UPDATE/s = 50K XIDs consumed per second
   - 4B XID space ÷ 50K/s = 80,000 seconds ≈ 22 hours to wraparound
   - Autovacuum FREEZE is running constantly
   - FREEZE scans the entire table (1B rows) — MASSIVE I/O
   → Solution: manual FREEZE, increase vacuum_freeze_min_age, partition

4. TOAST table contention:
   - If table has large values (>2KB), TOAST tables also have indexes
   - TOAST operations add extra I/O per INSERT/UPDATE
   - TOAST VACUUM might be running
   → Solution: check if TOAST is necessary, optimize column storage
```

**Diagnostic queries:**

```sql
-- Check autovacuum activity
SELECT pid, state, LEFT(query, 100) AS query,
       age(clock_timestamp(), query_start) AS duration,
       wait_event_type, wait_event
FROM pg_stat_activity
WHERE backend_type LIKE 'autovacuum%'
   OR query LIKE 'VACUUM%'
ORDER BY duration DESC;

-- Check table-level statistics
SELECT schemaname || '.' || relname AS table_name,
       n_tup_ins, n_tup_upd, n_tup_del,
       n_tup_hot_upd,
       round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 2) AS hot_ratio,
       n_dead_tup,
       last_vacuum, last_autovacuum,
       vacuum_count, autovacuum_count
FROM pg_stat_user_tables
WHERE relname = 'your_table_name';

-- Check disk I/O
SELECT schemaname || '.' || relname AS table_name,
       heap_blks_read, heap_blks_hit,
       idx_blks_read, idx_blks_hit,
       toast_blks_read, toast_blks_hit
FROM pg_statio_user_tables
WHERE relname = 'your_table_name';
```

**Immediate fixes:**

```sql
-- 1. Check if autovacuum is overwhelmed:
ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 2000;  -- Allow faster vacuum
ALTER SYSTEM SET autovacuum_vacuum_cost_delay = 0;     -- No throttling (temporarily)
SELECT pg_reload_conf();

-- 2. Increase checkpoint distance:
ALTER SYSTEM SET max_wal_size = '16GB';
ALTER SYSTEM SET min_wal_size = '4GB';
SELECT pg_reload_conf();

-- 3. Use ALTER TABLE to reduce autovacuum pressure on HOT updates:
ALTER TABLE your_table SET (autovacuum_vacuum_scale_factor = 0.01);

-- 4. Consider removing unnecessary indexes:
DROP INDEX CONCURRENTLY IF EXISTS idx_unnecessary;

-- 5. For the long-term: partition the table by time and archive old partitions
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Systematic triage** | Starts with pg_stat_activity, narrows down wait events |
| **Write amplification** | Understands 10 indexes × per-index maintenance = massive I/O |
| **WAL/checkpoint interplay** | Connects write rate to checkpoint frequency and I/O storms |
| **XID wraparound** | Identifies autovacuum freeze as a hidden cost at high XID consumption |
| **Quick fixes** | Proposes config changes before code changes |

---

### Q3: "Your team needs to migrate a critical 5TB database from PostgreSQL 12 to PostgreSQL 16 with < 5 minutes of downtime. Design the migration strategy."

**What They're Really Testing:** Whether you understand logical replication, upgrade strategies, and the operational challenges of large database migrations.

**Answer:**

**Strategy: Logical Replication (PG13+ built-in)**

```yaml
Overall approach:
  Phase 1: Setup (weeks before)
  Phase 2: Initial sync (takes days for 5TB)
  Phase 3: Catch-up (replication lag converges)
  Phase 4: Switchover (< 5 minutes downtime)

Phase 1 — Setup:
  1. Spin up PG16 cluster with matching schema
  2. Create publication on PG12 for all tables
  3. Create subscription on PG16 for all tables
  4. Initial data copy starts (takes 1-3 days for 5TB)

Phase 2 — Initial Sync:
  - PG16 subscriber applies initial COPY of all tables
  - WAL positions advance on PG12 while copying
  - After copy: PG16 catches up on WAL differences
  - Lag depends on WAL volume during copy (could be hours)

Phase 3 — Catch-up:
  - Monitor replication lag:
    SELECT pg_size_pretty(
        pg_wal_lsn_diff(pg_current_wal_lsn(), received_lsn)
    ) AS lag
    FROM pg_stat_subscription;

  - When lag < 1 minute: Proceed to phase 4

Phase 4 — Switchover:
  1. SET session_replication_role = 'replica' on PG12
     (stops all writes, but reads continue)
  2. Wait for PG16 to consume remaining WAL (lag = 0)
  3. SET session_replication_role = 'origin' on PG16
     (enables writes)
  4. Update DNS/CNAME to point to PG16
  5. Drop subscription on PG16 (optional, keeps as fallback)
  6. Run ANALYZE on PG16 (critical for query plans!)
```

**Implementation details:**

```sql
── Step 1: Create publication on PG12 (old) ──────────────

-- ALL tables:
CREATE PUBLICATION pub_migration
    FOR ALL TABLES
    WITH (publish = 'insert, update, delete, truncate');

-- Or selective (if you need to exclude some):
CREATE PUBLICATION pub_migration
    FOR TABLE public.users, public.orders, public.products;

── Step 2: Create subscription on PG16 (new) ─────────────

CREATE SUBSCRIPTION sub_migration
    CONNECTION 'host=old-pg12.example.com port=5432 dbname=mydb user=repl_user'
    PUBLICATION pub_migration
    WITH (
        copy_data = true,             -- Initial COPY of existing data
        create_slot = true,           -- Create replication slot on source
        synchronous_commit = off      -- Faster catch-up
    );

── Step 3: Monitor replication ──────────────────────────

SELECT subname, subenabled, subslotname,
       srsubid, srrelid::regclass,
       srsubstate  -- 'i' = init, 'd' = data copying, 's' = synchronized, 'r' = ready
FROM pg_subscription
JOIN pg_subscription_rel ON subid = srsubid;

── Step 4: Validate data consistency ─────────────────────

-- Row count comparison (sample tables):
SELECT 'users' AS table_name,
       (SELECT count(*) FROM public.users) AS old_count,
       (SELECT count(*) FROM public.users) AS new_count;  -- on PG16

-- Checksum comparison (sample tables):
SELECT sum(hashtext(t::text)) AS checksum FROM public.users AS t;

── Step 5: Switchover ──────────────────────────────────

-- On PG12 (old primary):
ALTER SYSTEM SET default_transaction_read_only = on;
SELECT pg_reload_conf();
-- Wait for all transactions to finish
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- On PG16 (new primary):
-- Drop subscription (stops connecting to old PG12)
ALTER SUBSCRIPTION sub_migration DISABLE;
ALTER SUBSCRIPTION sub_migration SET (slot_name = NONE);
DROP SUBSCRIPTION sub_migration;

-- The sequences might need adjustment:
-- If subscription used copy_data = true, sequences were copied too
-- But new inserts on PG16 during catch-up might have advanced sequences
-- Check next value matches what's expected
```

**Alternative: pg_dump/pg_restore (for < 5TB, backup window OK)**

```sql
── Parallel dump/restore ──────────────────────────────────

-- On PG12:
pg_dump -h localhost -U app_user -d mydb \
    -Fd -j 8 -f /backup/mydb_dump_dir/ \
    --no-blobs --no-owner --no-acl --no-tablespaces

-- Transfer to PG16 host:
rsync -avz /backup/mydb_dump_dir/ pg16_host:/backup/mydb_dump_dir/

-- On PG16:
pg_restore -h localhost -U app_user -d mydb \
    -Fd -j 8 -c --no-owner --no-acl --no-tablespaces \
    /backup/mydb_dump_dir/

-- Time estimate: ~2-5 hours for 5TB with 8 parallel jobs
```

**Switchover validation checklist:**

```yaml
Pre-switchover:
  ☐ Replication lag < 1 second on all tables
  ☐ Application can connect to new host (network/DNS)
  ☐ PG16 config matches or exceeds PG12 (shared_buffers, work_mem)
  ☐ All extensions installed on PG16
  ☐ Roles, permissions, grants created on PG16
  ☐ Sequences checked (nextval matches last data + 1)
  ☐ Foreign keys validated:
      ALTER TABLE ... VALIDATE CONSTRAINT ...
  ☐ ANALYZE run with high statistics target:
      ANALYZE (VERBOSE);  -- Full database analyze

Post-switchover:
  ☐ Query p99 latency compared to pre-migration baseline
  ☐ Replication slots on old PG12 cleaned up
  ☐ WAL archiving configured on PG16
  ☐ Monitoring dashboards pointed to new instance
  ☐ Rollback plan documented (reverse subscription possible)
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Replication approach** | Chooses logical replication over physical for cross-version upgrades |
| **Downtime calculation** | Identifies that only switchover phase requires write-drain (minutes) |
| **Data validation** | Proposes row counts, checksums, and foreign key validation |
| **Rollback plan** | Mentions keeping old PG12 as fallback with reverse replication |
| **Operational checklist** | Includes ANALYZE, sequence fixes, monitoring configuration |

---

### Q4: "Explain PostgreSQL's buffer pool eviction algorithm. How does it differ from an LRU cache? When would you tune the buffer pool differently for different workloads?"

**What They're Really Testing:** Whether you understand PostgreSQL's clock-sweep algorithm and can reason about cache behavior under different access patterns.

**Answer:**

**Clock Sweep Algorithm:**

PostgreSQL uses a **clock sweep** (or "second chance") algorithm for buffer eviction — NOT an LRU list.

```c
── Clock Sweep State ────────────────────────────────────────

Each buffer descriptor has:
  - usage_count (0–5): how recently this buffer was accessed
  - pin_count: 0 = unpinned, >0 = currently in use by a backend
  - is_dirty: page modified but not yet written to disk

── Eviction ──────────────────────────────────────────────

while true:
    buf = buffers[clock_hand]

    if buf.pin_count > 0:
        // Buffer is pinned (being read/written) → skip
        clock_hand = (clock_hand + 1) % num_buffers
        continue

    if buf.usage_count > 0:
        // Recently used → decrement and give a second chance
        buf.usage_count -= 1
        clock_hand = (clock_hand + 1) % num_buffers
        continue

    // Found victim: usage_count == 0
    if buf.is_dirty:
        write_to_disk(buf)  // Write dirty page (may block!)

    return buf  // Victim found

── Access (no lock needed!) ─────────────────────────────────

void access_buffer(buf):
    buf.usage_count = min(5, buf.usage_count + 1)
```

**Why Clock Sweep over True LRU?**

```yaml
True LRU (e.g., InnoDB, Redis):
  - Maintains a doubly-linked list ordered by access time
  - On every access: move accessed page to front of list (O(1) with pointer surgery)
  - Eviction: remove from tail (O(1))
  - PROBLEM: Every access requires a LOCK on the LRU list → contention!
  - Under high concurrency (100+ connections), LRU list becomes a bottleneck

Clock Sweep (PostgreSQL):
  - No list reordering on access (just increment a counter)
  - Only requires atomic increment, not a full list lock
  - Eviction requires a brief spinlock (only during eviction)
  - Trade-off: less accurate LRU approximation, but much better concurrency
```

**Access patterns and clock sweep behavior:**

```yaml
Sequential scan (problematic for clock sweep):
  - Reading 1M rows sequentially
  - Each page gets usage_count = 1
  - Clock sweep sees these as "recently used"
  - Hot pages (that people actually query repeatedly) get evicted!
  - Called: "sequential scan cache pollution"

Solution:
  - small tables (< 25% of shared_buffers): not a problem
  - large tables: use effective_cache_size + sequential scan avoidance
  - PG 8.3+: ring buffer for large sequential scans (limits cache pollution)
  - PG 13+: "skip scan" optimization avoids full table scan

High-churn OLTP (good for clock sweep):
  - Many small indexed lookups
  - Each page accessed frequently → usage_count stays high
  - Clock sweep keeps hot pages in cache
  - No LRU list contention → scales to 100s of connections

Mixed workload (most common):
  - 80% OLTP (frequent small queries)
  - 20% reporting (large sequential scans)
  - Clock sweep handles this well with ring buffers for big scans
```

**Tuning buffer pool for different workloads:**

```sql
── OLTP (web app, frequent small queries) ────────────────

shared_buffers = 8GB              -- 25% of 32GB RAM
effective_cache_size = 24GB       -- 75%
-- Benefit: Hot index pages stay in cache
-- Clock sweep keeps frequently accessed pages at usage_count = 5
-- Consequence: Very high cache hit ratio (> 99%)

── Data Warehouse (large scans, aggregations) ────────────

shared_buffers = 16GB             -- 50% of 32GB RAM (more because scans benefit)
effective_cache_size = 16GB       -- 50% (OS cache less useful for large scans)
-- Benefit: Ring buffer for scans prevents cache pollution
-- Clock sweep: sequential scan pages get usage_count = 1, quickly evicted
-- Consequence: Lower hit ratio but better for scan throughput

── Mixed (web + reporting) ───────────────────────────────

shared_buffers = 8GB              -- 25% of 32GB RAM
effective_cache_size = 24GB       -- 75%
-- Benefit: Ring buffer protects hot pages from being polluted by report scans
-- Clock sweep: report pages stay in ring buffer, not main clock
-- Consequence: Most hot pages stay cached despite concurrent reporting
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Algorithm knowledge** | Explains clock sweep with usage_count mechanics, not just "approximate LRU" |
| **Why not LRU** | Identifies lock contention as the key reason PostgreSQL chose clock sweep |
| **Sequential scan** | Mentions ring buffers for large scans to prevent cache pollution |
| **Workload tuning** | Tunes shared_buffers and effective_cache_size differently per workload |

---

### Q5: "How does PostgreSQL handle deadlocks? Walk through a concrete example and explain the detection algorithm."

**What They're Really Testing:** Whether you understand PostgreSQL's deadlock detection at the implementation level — the waits-for graph, cycle detection, and victim selection.

**Answer:**

**Concrete Deadlock Scenario:**

```sql
-- Transaction A:
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
-- Now holds RowExclusive lock on account 1

-- Transaction B (concurrent):
BEGIN;
UPDATE accounts SET balance = balance - 200 WHERE id = 2;
-- Now holds RowExclusive lock on account 2

-- Transaction A continues:
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
-- BLOCKS: waiting for B's lock on account 2

-- Transaction B continues:
UPDATE accounts SET balance = balance + 200 WHERE id = 1;
-- BLOCKS: waiting for A's lock on account 1
-- → DEADLOCK! Neither can proceed.
```

**Deadlock Detection Algorithm:**

```python
# PostgreSQL's deadlock detector runs every deadlock_timeout (default: 1s)
# It builds a "waits-for" graph and searches for cycles.

class DeadlockDetector:
    """
    Simplified implementation of PostgreSQL's deadlock detection.

    Key source file: src/backend/storage/lmgr/deadlock.c
    """

    def __init__(self):
        self.waits_for: dict[int, int] = {}  # waiter_pid → blocker_pid
        self.lock_queues: dict[str, list[int]] = {}  # lock_id → waiting pids

    def build_waits_for_graph(self):
        """
        Phase 1: For each blocked process, determine who is blocking it.

        PostgreSQL does this by checking all lock queues:
        - For each lock, find the HOLDER (process that has the lock granted)
        - For each WAITER, record holder as edge in graph
        - Handle multiple holders: waiter waits for ALL holders of conflicting locks
        """
        graph = {}
        for lock_id, waiters in self.lock_queues.items():
            holders = self.get_lock_holders(lock_id)
            for waiter in waiters:
                # A waiter waits for ALL holders (edge = waiter → holder)
                graph[waiter] = graph.get(waiter, set()) | holders
        return graph

    def detect_cycle(self, graph: dict[int, set[int]]):
        """
        Phase 2: DFS cycle detection in directed graph.

        PostgreSQL uses a depth-first search with edge coloring:
        - White: unvisited
        - Gray: in current DFS stack (cycle if we find a gray node)
        - Black: visited and no cycles found in subtree
        """
        VISITING = 1  # Gray
        VISITED = 2   # Black

        colors = {}

        def dfs(node, path) -> list[int] | None:
            colors[node] = VISITING
            path.append(node)

            for blocker in graph.get(node, set()):
                if blocker not in colors:
                    result = dfs(blocker, path)
                    if result:
                        return result
                elif colors.get(blocker) == VISITING:
                    # Found a cycle!
                    cycle_start = path.index(blocker)
                    return path[cycle_start:] + [blocker]

            colors[node] = VISITED
            path.pop()
            return None

        for pid in graph:
            if pid not in colors:
                result = dfs(pid, [])
                if result:
                    return result
        return None

    def resolve_deadlock(self, cycle: list[int]):
        """
        Phase 3: Choose a victim.

        PostgreSQL's victim selection:
        1. Find the process with the HIGHEST total lock wait time
           (not age, not work done — total time spent waiting)
        2. If tie: pick higher PID (younger process)
        3. Rationale: minimize the amount of work rolled back
           (longer waiter = more accumulated work = more expensive to rollback)

        NOTE: PostgreSQL does NOT use transaction age or work-done heuristics
        It picks the process that would cost the LEAST to abort
        """
        victim = max(cycle, key=lambda pid: self.get_total_wait_time(pid))
        self.send_sigint_to_backend(victim)
        return victim

── Detection in pg_stat_activity ─────────────────────────

-- You can see the deadlock detector running:
SELECT pid, state, query, wait_event_type, wait_event
FROM pg_stat_activity
WHERE query ILIKE '%deadlock%';
-- pid=12345, state='active', query='deadlock check'
```

**PostgreSQL vs InnoDB Deadlock Handling:**

```yaml
PostgreSQL:
  - Detection interval: deadlock_timeout (default: 1s)
  - Victim selection: highest total wait time (≈ cheapest to rollback)
  - On detection: one transaction ABORTED with error:
    "ERROR: deadlock detected"
  - Victim's changes are rolled back automatically
  - Non-victim proceeds normally

MySQL InnoDB:
  - Detection: continuous (every lock wait checks for cycle)
  - Victim selection: lowest undo size (least work to rollback)
  - On detection: one transaction ABORTED with error:
    "ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction"
  - InnoDB also has lock wait timeout (innodb_lock_wait_timeout, default: 50s)
  - After timeout: transaction ABORTED (not deadlock, just timeout)

Key difference:
  PostgreSQL: periodic check (every 1s) → less CPU, but detection delay
  InnoDB: continuous check → instant detection, but higher CPU overhead
```

**Preventing deadlocks:**

```sql
── 1. Order your lock acquisition ─────────────────────────

-- Always acquire locks in the same order:
-- Good:
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;

-- Bad (swapped order causes deadlock):
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;  -- Always this order
-- or the reverse: 2 then 1
-- Never mix!

── 2. Use SELECT ... FOR UPDATE NOWAIT ──────────────────

BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR UPDATE NOWAIT;
-- If lock not immediately available: ERROR, not wait
-- Retry with new transaction

── 3. Use advisory locks for application-level ordering ──

BEGIN;
SELECT pg_advisory_xact_lock(42, 1);  -- Family 42, ID 1
SELECT pg_advisory_xact_lock(42, 2);  -- Always same order
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Graph algorithm** | Explains DFS cycle detection in waits-for graph |
| **Victim selection** | Knows PostgreSQL picks by total wait time |
| **Detection interval** | Mentions deadlock_timeout (1s) and trade-off (CPU vs detection latency) |
| **Prevention strategies** | Proposes lock ordering, NOWAIT, advisory locks |

---

### Q6: "A query with 15 JOINs is running 100× slower than expected. The EXPLAIN ANALYZE shows wrong row estimates on some tables (off by 1000×). How do you fix the optimizer's estimates?"

**What They're Really Testing:** Whether you understand PostgreSQL's statistics system and know how to fix cardinality estimation problems.

**Answer:**

**Problem Diagnosis:**

```sql
── Step 1: Identify which estimates are wrong ─────────────

EXPLAIN (ANALYZE, BUFFERS, TIMING) SELECT ...;

-- Look for the "rows" vs "actual rows" mismatch:
--   rows=50 (estimated) vs actual rows=50000 (off by 1000×)
--   This causes the optimizer to:
--     - Choose Nested Loop when Hash Join would be better
--     - Sort when it shouldn't
--     - Use wrong join order

── Step 2: Check statistics for the problematic tables ────

SELECT schemaname, tablename,
       attname, n_distinct,
       null_frac, avg_width,
       most_common_vals, most_common_freqs,
       histogram_bounds,
       correlation
FROM pg_stats
WHERE tablename = 'orders'
  AND attname IN ('status', 'user_id', 'created_at');

── Step 3: Check when ANALYZE was last run ────────────────

SELECT schemaname, relname,
       last_analyze, last_autoanalyze,
       n_mod_since_analyze
FROM pg_stat_user_tables
WHERE relname = 'orders';
-- If n_mod_since_analyze > 10% of reltuples → stats are stale!
```

**Root Causes:**

```yaml
1. Stale statistics (most common):
   - 1M rows inserted since last ANALYZE
   - n_mod_since_analyze >> threshold
   → Solution: ANALYZE or increase autovacuum_analyze_scale_factor

2. Low statistics target:
   - Default statistics_target = 100 (samples 30000 rows)
   - For a 100M row table: sample only 0.03%!
   - MCV list: only 100 entries → missing distribution details
   → Solution: ALTER TABLE ... SET STATISTICS = 1000

3. Multi-column correlation:
   - WHERE status = 'shipped' AND created_at > '2024-01-01'
   - These columns are correlated (newer orders are more likely 'shipped')
   - PostgreSQL assumes INDEPENDENCE!
   - estimate = P(status) × P(created_at) = 0.5 × 0.3 = 0.15 → off by factor of 10
   → Solution: CREATE STATISTICS (for correlated columns)

4. Expression/function estimates:
   - WHERE date_trunc('month', created_at) = '2024-01-01'
   - PostgreSQL doesn't know the distribution of date_trunc results
   → Solution: expression statistics or functional index

5. Join cardinality:
   - 15 JOINs → 15 join selectivity estimates multiplied
   - Each off by 2× → total estimate off by 2^15 = 32768×!
   → Solution: reduce join count, use CTEs to force materialization
```

**Fixes:**

```sql
── Fix 1: Increase statistics target for problematic columns ──

ALTER TABLE orders ALTER COLUMN status SET STATISTICS 1000;
ALTER TABLE orders ALTER COLUMN user_id SET STATISTICS 1000;
-- Default: 100 → 1000: 10× more detailed histogram
-- For high-cardinality columns (user_id), even 10000 may be needed

-- Also increase default for future:
ALTER SYSTEM SET default_statistics_target = 500;
SELECT pg_reload_conf();

── Fix 2: Create extended statistics for correlated columns ──

-- PG 10+: CREATE STATISTICS for functional dependencies
CREATE STATISTICS orders_status_date_dep (dependencies)
    ON status, created_at FROM orders;

ANALYZE orders;

-- Check what was created:
SELECT stxname, stxkind, stxkeys,
       stxdependencies
FROM pg_statistic_ext
WHERE stxname = 'orders_status_date_dep';

-- Also: ndistinct for multi-column distinct estimates
CREATE STATISTICS orders_user_date_dist (ndistinct)
    ON user_id, created_at FROM orders;

-- Also: mcv for multi-column most-common-values
CREATE STATISTICS orders_mcv (mcv)
    ON status, created_at FROM orders;

── Fix 3: Expression statistics (PG 14+) ────────────────────

-- For functional indexes or WHERE expressions:
CREATE STATISTICS orders_month_stat (dependencies)
    ON (date_trunc('month', created_at)), status FROM orders;

── Fix 4: Force better join ordering ────────────────────────

-- Disable GEQO if near threshold:
SET geqo = off;

-- Use explicit JOIN syntax to force join order:
SELECT *
FROM (
    -- Most selective join first
    SELECT * FROM small_filtered_table
) a
JOIN (
    SELECT * FROM large_table
) b ON a.id = b.a_id;

── Fix 5: Use CTE materialization for stable estimates ──────

-- CTEs act as optimization fences:
WITH filtered_users AS MATERIALIZED (
    SELECT * FROM users
    WHERE created_at > '2024-01-01'
      AND status = 'active'
)
SELECT *
FROM filtered_users u
JOIN orders o ON o.user_id = u.id;
-- PostgreSQL estimates using CTE's actual row count (after filter)
-- Better than cascading bad estimates through 15 JOINs
```

**Long-term prevention:**

```sql
── Create a stats monitoring query ─────────────────────────

SELECT schemaname || '.' || relname AS table_name,
       attname,
       n_distinct,
       CASE
           WHEN n_distinct < 0 THEN 'auto (' || (-n_distinct * reltuples)::bigint || ')'
           ELSE n_distinct::text
       END AS distinct_estimate,
       most_common_vals IS NOT NULL AS has_mcv,
       histogram_bounds IS NOT NULL AS has_histogram,
       correlation
FROM pg_stats
JOIN pg_class ON pg_class.relname = pg_stats.tablename
WHERE schemaname = 'public'
ORDER BY n_distinct DESC;

── Create extended stats for common join columns ─────────

-- For any two columns that frequently appear together in WHERE clauses
-- or JOIN ON clauses:
DO $$
DECLARE
    col_pair record;
BEGIN
    FOR col_pair IN (
        SELECT schemaname, tablename, array_agg(DISTINCT attname) AS columns
        FROM pg_stats
        WHERE schemaname = 'public'
        GROUP BY schemaname, tablename
        HAVING count(*) > 3
    ) LOOP
        EXECUTE format(
            'CREATE STATISTICS IF NOT EXISTS %I_%s_corr (dependencies, ndistinct, mcv) ON %s FROM %I.%I',
            col_pair.tablename,
            replace(col_pair.columns::text, ',', '_'),
            array_to_string(col_pair.columns, ', '),
            col_pair.schemaname,
            col_pair.tablename
        );
    END LOOP;
END $$;
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cardinality estimation** | Explains how PostgreSQL estimates row counts and why they can be wrong |
| **Statistics system** | Knows MCV lists, histograms, n_distinct, and correlation |
| **Extended statistics** | Mentions CREATE STATISTICS for functional dependencies, ndistinct, MCV |
| **Multi-join error** | Understands that errors compound exponentially across 15 JOINs |
| **CTE materialization** | Proposes CTEs to force optimization fences and stable estimates |

---

### Q7: "Design a PostgreSQL logical replication topology for a multi-region active-active application. What are the limitations and how do you handle conflict resolution?"

**What They're Really Testing:** Whether you understand PostgreSQL's logical replication capabilities, the fundamental limitations of multi-primary setups, and practical conflict resolution strategies.

**Answer:**

**Topology Design:**

```yaml
Multi-region active-active with logical replication:

┌─────────────────────┐       ┌─────────────────────┐
│   US-East (Primary)  │       │  EU-West (Primary)  │
│   PostgreSQL 16      │       │  PostgreSQL 16      │
│                      │       │                      │
│  ┌────────────────┐  │       │  ┌────────────────┐  │
│  │ Publication:   │  │◄──────│  │ Publication:   │  │
│  │ pub_us_east    │  │       │  │ pub_eu_west    │  │
│  │ Tables:        │  │       │  │ Tables:        │  │
│  │ - users        │  │       │  │ - users        │  │
│  │ - products (RO)│  │       │  │ - products (RO)│  │
│  │                │  │       │  │                │  │
│  │ Subscription:  │  │       │  │ Subscription:  │  │
│  │ sub_eu_west   │──┼──────►│  │ sub_us_east    │  │
│  └────────────────┘  │       │  └────────────────┘  │
└─────────────────────┘       └─────────────────────┘
         │                            │
         ▼                            ▼
┌─────────────────────┐       ┌─────────────────────┐
│ Application reads   │       │ Application reads   │
│ from LOCAL          │       │ from LOCAL          │
│ Writes to LOCAL     │       │ Writes to LOCAL     │
│ (users, sessions)   │       │ (users, sessions)   │
│ Reads from ANY      │       │ Reads from ANY      │
│ (products, catalog) │       │ (products, catalog) │
└─────────────────────┘       └─────────────────────┘
```

**Conflict Types & Strategies:**

```yaml
╔══════════════════════════════════════════════════════════════╗
║                LOGICAL REPLICATION CONFLICTS                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║ Type 1: INSERT conflict (duplicate key)                      ║
║   - US: INSERT INTO users (id=42, name='Alice')              ║
║   - EU: INSERT INTO users (id=42, name='Bob')                ║
║   → Conflict on pk: duplicate key value violates unique      ║
║                                                              ║
║ Solution A: No conflict (partition by region)                ║
║   - Use UUIDs or include region prefix in PK                 ║
║     id = 'us_000042' vs id = 'eu_000042'                    ║
║   - Or: serial ranges per region                             ║
║     US: 1-1B, EU: 1B-2B, APAC: 2B-3B                        ║
║                                                              ║
║ Solution B: Conflict resolution (PG 16+ pg_output_plugin)    ║
║   - Last-writer-wins (LWW): use updated_at timestamp         ║
║   - Custom conflict handler (pg 16+): trigger function       ║
║   - Skip conflicting row (with logging)                      ║
║                                                              ║
║ Type 2: UPDATE conflict (row updated differently)            ║
║   - US: UPDATE users SET name='Alice' WHERE id=42            ║
║   - EU: UPDATE users SET name='Bob' WHERE id=42              ║
║   → Both rows exist, last write wins (depending on order)    ║
║                                                              ║
║ Solution: Use application-level CRDTs or conflict-free        ║
║   data types (last-writer-wins for simple fields, CRDT for   ║
║   counters and sets)                                         ║
║                                                              ║
║ Type 3: DELETE conflict                                       ║
║   - US: DELETE users WHERE id=42                             ║
║   - EU: same row doesn't exist (already deleted)             ║
║   → "no matching row" error                                  ║
║                                                              ║
║ Solution: Use soft-deletes (deleted_at IS NOT NULL)           ║
║   instead of hard DELETEs when bidirectional replication     ║
╚══════════════════════════════════════════════════════════════╝
```

**Implementation:**

```sql
── US-East setup ──────────────────────────────────────────

-- Publication for US-East tables (sends changes TO EU)
CREATE PUBLICATION pub_us_east
    FOR TABLE public.users, public.sessions
    WITH (publish = 'insert, update, delete');

-- Subscription for EU-West changes
CREATE SUBSCRIPTION sub_eu_west
    CONNECTION 'host=eu-west.example.com port=5432 dbname=app user=repl'
    PUBLICATION pub_eu_west
    WITH (
        origin = none,                       -- Don't forward replicated changes (PG14+)
        binary = true,                       -- Use binary format (faster, less CPU)
        streaming = on,                      -- Stream changes continuously
        disable_on_error = off               -- Don't stop on conflict
    );

── EU-West setup ─────────────────────────────────────────

CREATE PUBLICATION pub_eu_west
    FOR TABLE public.users, public.sessions;

CREATE SUBSCRIPTION sub_us_east
    CONNECTION 'host=us-east.example.com port=5432 dbname=app user=repl'
    PUBLICATION pub_us_east
    WITH (origin = none, binary = true, streaming = on);

── Conflict resolution (PG 16+ with trigger) ─────────────

CREATE OR REPLACE FUNCTION handle_replication_conflict()
RETURNS trigger AS $$
BEGIN
    -- Last-writer-wins based on updated_at
    IF TG_OP = 'INSERT' AND EXISTS (
        SELECT 1 FROM conflicts WHERE table_name = TG_TABLE_NAME
    ) THEN
        -- Skip insert if PK exists
        RETURN NULL;  -- Skip conflicting insert
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Only apply if this is newer
        IF NEW.updated_at > OLD.updated_at THEN
            RETURN NEW;
        END IF;
        RETURN OLD;  -- Skip older update
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Limitations of Active-Active Logical Replication:**

```yaml
1. NOT multi-master! PostgreSQL has no true multi-master:
   - Each table can only have one writer per primary
   - "Active-active" means: app writes to both primaries,
     different data partitions per primary

2. Conflict resolution is minimal:
   - PG 14+: "origin = none" prevents re-replication of changes
   - PG 16+: limited conflict resolution (ignore, error, or apply)
   - No automatic CRDT support
   - Need application-level conflict handling

3. DDL is NOT replicated:
   - Schema changes must be applied manually to both sides
   - ALTER TABLE ... ADD COLUMN → must run on both primaries
   - CREATE INDEX → run separately on each
   - Solution: use migration tools that apply to both clusters

4. Sequences are NOT synchronized:
   - currval/nextval on US ≠ currval/nextval on EU
   - Pre-allocated ranges per region (US: odds, EU: evens)
   - Or use UUIDs as primary keys

5. Lag is unbounded:
   - Cross-region network latency (US→EU: 60-80ms)
   - High write volume can cause persistent lag
   - Monitor: pg_stat_subscription.write_lag, flush_lag, replay_lag
```

**Practical Architecture for Active-Active:**

```yaml
Recommended approach: "Active-passive with regional read replicas"

┌──────────────────┐     Async     ┌──────────────────┐
│  US-East Primary  │─────────────►│  EU-West Standby  │
│  Read + Write     │              │  Read-Only        │
│  (true primary)   │              │  (promotable)     │
│                   │              │                   │
│  ┌──────────────┐ │  Streaming   │ ┌───────────────┐ │
│  │ Row-level    │ │  Replication │ │ Read queries  │ │
│  │ Writes       │ │  (physical)  │ │ Local reads   │ │
│  └──────────────┘ │              │ └───────────────┘ │
└──────────────────┘              └──────────────────┘
         │                                  │
         ▼                                  ▼
┌──────────────────┐              ┌──────────────────┐
│ US-App           │              │ EU-App           │
│ Writes to US     │              │ Reads from EU    │
│ (60-80ms slower) │              │ (local = 1ms)    │
└──────────────────┘              └──────────────────┘

For actual active-active: use application-layer sharding
  US writes to: users_us, orders_us (on US primary)
  EU writes to: users_eu, orders_eu (on EU primary)
  Replicate uni-directionally for global read access
  Only a few tables need cross-region writes
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Honesty about limitations** | Clearly states PG doesn't have true multi-master |
| **Conflict types** | Identifies INSERT, UPDATE, DELETE conflicts with solutions |
| **Origin filtering** | Knows about origin = none to prevent re-replication |
| **Practical topology** | Proposes active-passive with regional read replicas as more realistic |

---

### Q8: "A pg_dump of a 2TB database takes 12 hours and the backup fails at 95% due to a network interruption. Design a backup strategy that can resume from where it left off and completes within a 4-hour backup window."

**What They're Really Testing:** Whether you understand PostgreSQL backup strategies beyond basic pg_dump, and can design for operational reliability at scale.

**Answer:**

**Problem Analysis:**

```yaml
Why pg_dump fails at 95%:
  - Single session (unless using -j with directory format)
  - Network interruption → entire backup lost
  - No checkpoint/resume capability in pg_dump
  - 12 hours = too long (need < 4 hours)

Solution: Multi-layered approach
  Layer 1: pgBackRest (physical backup) — primary backup system
  Layer 2: pg_dump with parallelization — fallback for schema
  Layer 3: WAL archiving — continuous point-in-time recovery
```

**Primary Solution: pgBackRest**

```yaml
pgBackRest advantages for large DB:
  - Checkpoint/resume: can resume interrupted backups
  - Delta backups: only backups changed pages
  - Parallel backup/restore: uses multiple connections
  - Verification: automatically verifies backups
  - Encryption: built-in AES-256
  - Compression: zstd, lz4, gzip, bzip2
  - Retention: full + differential + incremental management
```

```sql
── pgBackRest setup ─────────────────────────────────────┐

-- Repository configuration (S3/GCS/local):
[global]
repo1-path=/backup/pgbackrest
repo1-retention-full=4          -- Keep 4 full backups
repo1-retention-diff=14         -- Keep 14 differentials
repo1-cipher-type=aes-256-cbc   -- Encryption

-- Backup performance optimization:
compress-type=zst               -- Fast + good compression (zstd)
compress-level=6
process-max=4                   -- Parallel compression
delta-check-time=120            -- Check for resumed backups every 2 min

-- Backup schedule:
-- Sun 02:00: full backup
-- Mon-Sat 02:00: differential backup
-- Every 4 hours: incremental backup

── Backup commands ──────────────────────────────────────

-- Full backup (Sunday):
pgbackrest --stanza=myapp --type=full backup

-- Differential backup (daily):
pgbackrest --stanza=myapp --type=diff backup

-- Incremental backup (every 4 hours):
pgbackrest --stanza=myapp --type=incr backup

── PITR restore to specific time ────────────────────────

pgbackrest --stanza=myapp \
    --type=time \
    --target="2024-06-15 14:30:00-05:00" \
    --target-action=promote \
    restore

── Delta restore (only copy changed files) ──────────────

pgbackrest --stanza=myapp \
    --type=time \
    --target="2024-06-15 14:30:00-05:00" \
    --delta \
    --target-action=promote \
    restore
```

**Secondary Solution: Optimized pg_dump**

```sql
── Parallel directory format (for schema-only or small DB) ──

-- Split into schema-only + data-only:
pg_dump -h localhost -U app_user -d mydb \
    --schema-only \
    -Fc -f mydb_schema.dump

pg_dump -h localhost -U app_user -d mydb \
    --data-only \
    -Fd -j 8 --compress=zstd:6 \
    -f mydb_data_dump_dir/

-- Restore with parallel:
pg_restore -h target_host -U app_user -d mydb \
    -j 8 \
    mydb_schema.dump

pg_restore -h target_host -U app_user -d mydb \
    --data-only \
    -j 8 \
    mydb_data_dump_dir/

── Table-level parallel dump (custom script) ────────────

-- Dump each large table in parallel, small tables together:
-- Large tables (use parallel per table):
for table in orders events logs; do
    pg_dump -h localhost -U app_user -d mydb \
        --table=$table \
        --data-only \
        --compress=zstd:6 \
        -f /backup/${table}.sql.zst \
        -Fc &
done

-- Small tables (single dump):
pg_dump -h localhost -U app_user -d mydb \
    --exclude-table-data='orders|events|logs' \
    --data-only \
    --compress=zstd:6 \
    -j 4 \
    -f /backup/small_tables.dump \
    -Fd
```

**Network Resilience:**

```yaml
For network-interruption-resilient backups:

1. Use S3-compatible storage with multipart upload:
   - pgBackRest S3 support
   - Multipart uploads can be resumed
   - Network interruption → resume from last completed part

2. Local staging then upload:
   - Backup to local SSD first (fast, reliable)
   - Then upload to S3/archive in background
   - rclone or s5cmd for parallel upload:
     s5cmd cp /backup/* s3://my-backup-bucket/

3. Streaming WAL archiving with retry:
   archive_command = 'pgbackrest --stanza=myapp archive-push %p'
   -- Built-in retry: pgBackRest retries on failure

4. Backup verification:
   pgbackrest --stanza=myapp check
   -- After each backup:
   pgbackrest --stanza=myapp --type=standby restore --db-path=/tmp/backup_test
   pg_isready -h /tmp/backup_test
   psql -h /tmp/backup_test -c "SELECT count(*) FROM orders;"
```

**Backup window reduction techniques:**

```yaml
From 12 hours → < 4 hours:

1. Parallelism:
   - pgBackRest process-max = 4
   - pg_dump -j 8 (parallel table dumps)
   - Multiple concurrent WAL archiving processes

2. Compression:
   - zstd:level=6 (≈ same speed as gzip, 2× better compression)
   - 2TB → ~500GB (75% reduction for typical text-heavy DB)
   - Less data to transfer = faster backup

3. Delta/incremental:
   - Full backup: 2TB (first time only)
   - Differential: ~10-50GB (only changed data since full)
   - Incremental: ~1-5GB (only changed since last backup)

4. Selective backup:
   - Don't backup temporary/unimportant tables
   - Use --exclude-table-data on staging tables
   - Backup large static tables infrequently

5. Storage:
   - NVMe SSD for temporary backup storage (3GB/s write)
   - S3 for archive (unlimited, but slower)
   - Use local SSD for initial backup, async upload to S3
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Backup resilience** | Proposes checkpoint/resume capable solution (pgBackRest) over pg_dump |
| **Parallelism** | Uses multiple connections and parallel processes to fit backup window |
| **Network interruption** | Handles network failures with multipart uploads and retry |
| **Backup strategy** | Recommends full + differential + incremental layered approach |
| **Verification** | Includes automated backup verification step |

---

### Q9: "Your production database is experiencing periodic 'checkpoints are occurring too frequently' warnings in the logs. Walk through the causes, diagnosis, and solutions."

**What They're Really Testing:** Whether you understand the interplay between WAL generation, checkpoint frequency, and I/O patterns at the system level.

**Answer:**

**Understanding the Warning:**

The message "checkpoints are occurring too frequently" appears when `log_checkpoints = on` and the time between checkpoints is significantly less than `checkpoint_timeout`. This indicates that checkpoints are being triggered by `max_wal_size` being reached, not by timeout.

**Causes:**

```yaml
Root cause: WAL generation rate exceeds the checkpoint smoothing capacity

Why WAL is generated too fast:
  1. High write volume (updates, inserts, deletes) → most common
  2. Full-page writes (first modification after checkpoint writes full 8KB page)
  3. Many indexes on frequently updated tables
  4. Long-running transactions preventing HOT updates
  5. Replication (wal_level = replica adds header overhead)
  6. Large TOAST updates (each generates multiple WAL records)

System consequences:
  - Checkpoint I/O storms (all dirty buffers written at once)
  - Backend processes stall during BARRIER checkpoints
  - Query latency spikes (p99 goes from 10ms to 500ms+)
  - In extreme cases: "could not write to WAL: disk full"
```

**Diagnosis:**

```sql
── Step 1: Check checkpoint statistics ─────────────────────

SELECT checkpoints_timed,   -- Expected: many (> 10× checkpoint_req)
       checkpoints_req,      -- Expected: few (< 10% of total)
       round(100.0 * checkpoints_req / nullif(checkpoints_timed + checkpoints_req, 0), 2) AS req_pct,
       buffers_checkpoint,   -- Buffers written by checkpointer
       buffers_clean,        -- Buffers written by bgwriter
       buffers_backend,      -- Buffers written by backends (SHOULD BE LOW!)
       buffers_backend_fsync -- Backends doing fsync (SHOULD BE ZERO!)
FROM pg_stat_bgwriter;

-- If checkpoints_req > 10% of total: problem!
-- If buffers_backend > 10% of total: backends are helping with writes = BAD

── Step 2: Calculate WAL generation rate ───────────────────

SELECT pg_size_pretty(
    (sum(pg_wal_lsn_diff(end_lsn, start_lsn)) / 3600)::bigint
) AS wal_per_hour
FROM pg_stat_archiver;

-- Or use pg_stat_statements to find WAL-heavy queries:
SELECT LEFT(query, 80) AS query,
       calls,
       pg_size_pretty(wal_bytes::bigint) AS total_wal,
       pg_size_pretty((wal_bytes / nullif(calls, 0))::bigint) AS wal_per_exec
FROM pg_stat_statements
WHERE wal_bytes > 0
ORDER BY wal_bytes DESC
LIMIT 10;

── Step 3: Check current WAL position and size ─────────────

SELECT pg_size_pretty(sum(size)) AS total_wal_size,
       count(*) AS segment_count,
       pg_size_pretty(pg_wal_lsn_diff(
           pg_current_wal_lsn(),
           '0/00000000'
       )) AS total_wal_written
FROM pg_ls_waldir();

── Step 4: Monitor in real-time ────────────────────────────

-- Watch WAL growth in real-time:
SELECT now(),
       pg_size_pretty(pg_wal_lsn_diff(
           pg_current_wal_lsn(),
           '0/00000000'
       )) AS wal_written,
       pg_wal_lsn_diff(
           pg_current_wal_lsn(),
           lag(pg_current_wal_lsn()) OVER (ORDER BY now())
       ) AS wal_diff_bytes
FROM generate_series(1, 10);
```

**Solutions:**

```yaml
┌──────────────────────────────────────────────────────────────┐
│                    TUNING SOLUTIONS                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ Solution 1: Increase max_wal_size (LOW effort, HIGH impact) │
│   max_wal_size = 16GB  (from default 1GB)                   │
│   Effect: Checkpoints happen 16× less often                 │
│   Risk: More WAL disk space needed (~16GB for WAL)         │
│   Recovery time: longer crash recovery if not checkpointed│
│                                                              │
│ Solution 2: Increase checkpoint_timeout                      │
│   checkpoint_timeout = 30min (from default 5min)             │
│   Effect: Max 1 checkpoint per 30min                        │
│   Risk: More WAL accumulated between checkpoints            │
│                                                              │
│ Solution 3: Spread checkpoint writes                         │
│   checkpoint_completion_target = 0.95 (from 0.5)           │
│   Effect: Checkpoint writes spread over 95% of window      │
│   Smoother I/O, no spikes                                   │
│                                                              │
│ Solution 4: Tune bgwriter to pre-clean buffers              │
│   bgwriter_delay = 20ms (from 200ms)                       │
│   bgwriter_lru_maxpages = 1000 (from 100)                  │
│   bgwriter_lru_multiplier = 4.0 (from 2.0)                │
│   Effect: BgWriter keeps more buffers clean                 │
│   Less work for checkpointer = faster checkpoints          │
│                                                              │
│ Solution 5: Reduce WAL volume                                │
│   wal_compression = zstd   (compress full page images)    │
│   Effect: 2-3× less WAL volume                             │
│   Cost: CPU for compression/decompression (~5% overhead)  │
│                                                              │
│ Solution 6: Full page write tuning                         │
│   Only relevant: first write to each page after checkpoint │
│   Solution: increase checkpoint intervals = fewer full pages│
│                                                              │
│ Solution 7: Application changes                              │
│   - Batch updates instead of single-row UPDATEs             │
│   - Reduce unnecessary WAL in temp tables:                  │
│     CREATE TEMP TABLE ... ON COMMIT DELETE ROWS             │
│   - Use UNLOGGED tables for non-critical data               │
│     (Not WAL-logged at all, but lost on crash)              │
│                                                              │
│ For immediate relief (while tuning):                        │
│   SELECT pg_checkpoint(force);  -- Start checkpoint NOW    │
│   Not a solution, but can buy time                          │
└──────────────────────────────────────────────────────────────┘
```

**Implementation:**

```sql
── Apply tuning ───────────────────────────────────────────

-- Increase WAL size to spread checkpoints:
ALTER SYSTEM SET max_wal_size = '16GB';
ALTER SYSTEM SET min_wal_size = '4GB';
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET checkpoint_completion_target = '0.95';

-- Enable WAL compression:
ALTER SYSTEM SET wal_compression = 'zstd';  -- PG 15+

-- Tune bgwriter for more pre-cleaning:
ALTER SYSTEM SET bgwriter_delay = '20ms';
ALTER SYSTEM SET bgwriter_lru_maxpages = 1000;
ALTER SYSTEM SET bgwriter_lru_multiplier = 4.0;

SELECT pg_reload_conf();
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cause identification** | Connects frequent checkpoints to WAL generation rate vs max_wal_size |
| **Quantitative diagnosis** | Uses pg_stat_bgwriter to identify checkpoints_req dominance |
| **Tiered solutions** | Proposes config changes first, then application-level changes |
| **Trade-off awareness** | Understands longer checkpoints = more WAL to replay on crash |

---

### Q10: "Explain how PostgreSQL handles recursive CTEs. Walk through the evaluation model and give an example where a recursive CTE outperforms an application-level query loop."

**What They're Really Testing:** Whether you understand the recursive CTE evaluation model and can identify when it's the right tool versus over-engineering.

**Answer:**

**Recursive CTE Evaluation Model:**

```sql
WITH RECURSIVE cte AS (
    -- Non-recursive term (base case)
    SELECT ...
    UNION ALL
    -- Recursive term (references cte)
    SELECT ...
    FROM cte, ...
)
SELECT * FROM cte;
```

PostgreSQL evaluates recursive CTEs using **iteration** (not recursion):

```python
def evaluate_recursive_cte():
    """
    PostgreSQL's recursive CTE evaluation:
    1. Evaluate non-recursive term → working table (first iteration)
    2. While working table is not empty:
       a. Evaluate recursive term, using working table as 'cte'
       b. Append result to final result
       c. Replace working table with recursive term's result
    """

    # Step 1: Non-recursive term
    working_table = execute(non_recursive_term)
    final_result = working_table.copy()

    # Step 2: Iterate recursive term
    iteration = 0
    while not working_table.is_empty() and iteration < max_recursive_iterations:
        iteration += 1

        # Temporary table: current working table iteration
        # Recursive term references this as 'cte'
        new_rows = execute(recursive_term, cte=working_table)

        if new_rows.is_empty():
            break  # Termination condition

        working_table = new_rows
        final_result.append(new_rows)

    return final_result
```

**Example: Organizational Hierarchy**

```sql
── Schema ─────────────────────────────────────────────────

CREATE TABLE employees (
    id serial PRIMARY KEY,
    name text NOT NULL,
    manager_id int REFERENCES employees(id),
    department text NOT NULL
);

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

── Recursive CTE: Find all direct reports of CTO ─────────

WITH RECURSIVE org_chart AS (
    -- Base case: start with CTO
    SELECT id, name, manager_id, 1 AS level,
           ARRAY[name] AS path
    FROM employees
    WHERE id = 2  -- CTO

    UNION ALL

    -- Recursive step: find reports of reports
    SELECT e.id, e.name, e.manager_id, oc.level + 1,
           oc.path || e.name
    FROM employees e
    JOIN org_chart oc ON e.manager_id = oc.id
)
SELECT level, repeat('  ', level - 1) || name AS org_tree,
       id
FROM org_chart
ORDER BY path;

── Result ────────────────────────────────────────────────

 level |          org_tree           | id
-------+----------------------------+-----
     1 | CTO                        |  2
     2 |   Engineering Director     |  4
     3 |     Platform Lead          |  5
     4 |       Data Engineer        | 10
     3 |     Backend Lead           |  6
     4 |       Backend Engineer 1   |  8
     4 |       Backend Engineer 2   |  9
     3 |     Frontend Lead          |  7
```

**Recursive CTE vs Application Loop:**

```sql
── Problem: Find all ancestors of employee 8 (Backend Engineer) ──

── Application loop approach (N queries = O(N) round trips) ──

-- Query 1: SELECT manager_id FROM employees WHERE id = 8; → 6
-- Query 2: SELECT manager_id FROM employees WHERE id = 6; → 4
-- Query 3: SELECT manager_id FROM employees WHERE id = 4; → 2
-- Query 4: SELECT manager_id FROM employees WHERE id = 2; → 1
-- Query 5: SELECT manager_id FROM employees WHERE id = 1; → NULL
-- 5 round trips to database: ~5 * 2ms = 10ms network latency

── Recursive CTE approach (1 query) ──────────────────────

WITH RECURSIVE ancestors AS (
    -- Base: start at target employee
    SELECT id, name, manager_id, 1 AS level
    FROM employees
    WHERE id = 8

    UNION ALL

    -- Recursive: go up the chain
    SELECT e.id, e.name, e.manager_id, a.level + 1
    FROM employees e
    JOIN ancestors a ON e.id = a.manager_id
)
SELECT name, level
FROM ancestors
ORDER BY level DESC;

── Result: 1 query, 1 round trip ─────────────────────────

 name                | level
---------------------+-------
 CEO                 |     4  (root)
 CTO                 |     3
 Engineering Director |     2
 Backend Lead        |     1
```

**When Recursive CTE Outperforms Application Code:**

```yaml
Recursive CTE wins:
  1. Deep hierarchy traversal (org charts, bill of materials)
  2. Graph traversal (friend-of-a-friend, network paths)
  3. Connected components (find all nodes in same group)
  4. Tree operations (find all descendants, ancestors)
  5. Sequential processing (running totals, date ranges)

Application loop wins:
  1. Shallow hierarchies (max 2-3 levels)
  2. You need procedural logic (if-then-else decisions per level)
  3. The recursion depends on external data (API calls)
  4. You need to inject business logic between recursion steps
  5. Memory-bound operations (recursive CTE builds entire result in memory)
```

**Advanced Recursive CTE: Bill of Materials**

```sql
── Schema ─────────────────────────────────────────────────

CREATE TABLE parts (
    id serial PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE bill_of_materials (
    parent_part_id int REFERENCES parts(id),
    child_part_id int REFERENCES parts(id),
    quantity int NOT NULL,
    PRIMARY KEY (parent_part_id, child_part_id)
);

── Find total quantity of each component for a product ───

WITH RECURSIVE bom_explosion AS (
    -- Base: direct components of product
    SELECT p.id, p.name, b.quantity, 1 AS level,
           b.quantity AS total_quantity
    FROM parts p
    JOIN bill_of_materials b ON b.parent_part_id = p.id
    WHERE p.id = 100  -- Product ID

    UNION ALL

    -- Recursive: components of components
    SELECT p.id, p.name, b.quantity, bom.level + 1,
           bom.total_quantity * b.quantity AS total_quantity
    FROM parts p
    JOIN bill_of_materials b ON b.parent_part_id = p.id
    JOIN bom_explosion bom ON bom.id = b.child_part_id
)
SELECT name, sum(total_quantity) AS total_quantity
FROM bom_explosion
GROUP BY name
ORDER BY total_quantity DESC;
```

**Limitations & Gotchas:**

```sql
-- 1. No LIMIT or ORDER BY in recursive term:
--    ❌ Invalid:
--    WITH RECURSIVE cte AS (
--        SELECT ... FROM base
--        UNION ALL
--        SELECT ... FROM cte ORDER BY id LIMIT 10  -- ERROR!
--    )

-- 2. No aggregation in recursive term:
--    ❌ Invalid:
--    WITH RECURSIVE cte AS (
--        SELECT ... FROM base
--        UNION ALL
--        SELECT count(*) FROM cte  -- ERROR! (aggregate in recursive term)
--    )

-- 3. Must use UNION ALL (not UNION) for performance:
--    UNION would need to deduplicate (expensive)
--    Most recursive CTEs need UNION ALL anyway

-- 4. Cycle detection:
--    WITH RECURSIVE cte AS (
--        SELECT id, manager_id, ARRAY[id] AS cycle
--        FROM employees WHERE id = 1
--        UNION ALL
--        SELECT e.id, e.manager_id, cte.cycle || e.id
--        FROM employees e
--        JOIN cte ON e.manager_id = cte.id
--        WHERE NOT e.id = ANY(cte.cycle)  -- Stop if we've seen this ID
--    )

-- 5. Depth limit (avoid infinite recursion):
--    WITH RECURSIVE cte AS (
--        ...
--        UNION ALL
--        SELECT ... FROM cte WHERE cte.level < 10  -- Max 10 levels
--    )
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Evaluation model** | Explains iterative evaluation (working table repeatedly evaluated) |
| **vs Application loop** | Identifies network round trips as the key advantage of recursive CTEs |
| **Use cases** | Cites hierarchies, BOM, graph traversal as sweet spots |
| **Limitations** | Knows about cycle detection, depth limits, no aggregates in recursive term |

---

### Q11: "Design a PostgreSQL query that paginates efficiently through 10M orders, sorted by created_at DESC. The user can filter by status, date range, or search by order_id. Compare cursor-based vs offset-based pagination."

**What They're Really Testing:** Whether you understand the performance characteristics of different pagination strategies and can design for cursor-based efficiency at scale.

**Answer:**

**Offset-Based Pagination (The Problem):**

```sql
── Standard offset pagination (AVOID at scale) ──────────

-- Page 1: 10ms
SELECT id, order_id, amount, created_at
FROM orders
WHERE status = 'completed'
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 0;

-- Page 10000: 5+ seconds!
SELECT id, order_id, amount, created_at
FROM orders
WHERE status = 'completed'
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 199980;

-- Why it's slow:
--   PostgreSQL must scan + sort ALL rows up to OFFSET + LIMIT
--   Offset 200K: must scan through 200K rows, then discard first 199,980
--   OFFSET 1M: scan 1M+ rows → seq scan on orders (even with index!)
--   Page 500K: essentially a full table scan

-- With covering index, still reads all index entries:
CREATE INDEX idx_orders_status_date ON orders (status, created_at DESC, id DESC);
-- Index scan still needs to walk through 199,980 index entries
-- before returning the 20 we want!
```

**Cursor-Based Pagination (The Solution):**

```sql
── Cursor-based pagination using last_seen values ────────

-- First request (no cursor):
SELECT id, order_id, amount, created_at
FROM orders
WHERE status = 'completed'
ORDER BY created_at DESC, id DESC
LIMIT 20;

-- Return: cursor = {created_at: '2024-06-15T14:30:00Z', id: 12345}

-- Next page (using cursor):
SELECT id, order_id, amount, created_at
FROM orders
WHERE status = 'completed'
  AND (created_at, id) < ('2024-06-15T14:30:00Z', 12345)
ORDER BY created_at DESC, id DESC
LIMIT 20;

── How it's fast ──────────────────────────────────────────

-- This is a SARGable predicate!
-- PostgreSQL can use the index directly to start at the cursor position:
--   "find rows with (created_at, id) < ('2024-06-15T14:30:00Z', 12345)"
--   Index seek to that position → scan next 20 rows forward
--   Constant time: O(log N) for the seek + O(20) for the scan
--   Page 1M = same cost as Page 1!

-- Required index:
CREATE INDEX idx_orders_cursor ON orders (status, created_at DESC, id DESC)
    WHERE status = 'completed';  -- Partial index for common filter
```

**Implementation:**

```python
── Cursor-based pagination in application code ────────────

def paginate_orders(cursor: dict | None, filters: dict) -> Page:
    """
    Cursor-based pagination for orders.

    Args:
        cursor: {'created_at': '2024-06-15T14:30:00Z', 'id': 12345}
                or None for first page
        filters: {'status': 'completed', 'start_date': ..., 'end_date': ...}

    Returns: Page with items + next_cursor
    """
    query = """
        SELECT id, order_id, amount, created_at, status
        FROM orders
        WHERE status = %(status)s
    """
    params = {'status': filters.get('status', 'completed')}

    # Date range filter
    if filters.get('start_date'):
        query += " AND created_at >= %(start_date)s"
        params['start_date'] = filters['start_date']
    if filters.get('end_date'):
        query += " AND created_at <= %(end_date)s"
        params['end_date'] = filters['end_date']

    # Cursor-based filter (keyset pagination)
    if cursor:
        query += """
            AND (created_at, id) < (%(cursor_created)s, %(cursor_id)s)
        """
        params['cursor_created'] = cursor['created_at']
        params['cursor_id'] = cursor['id']

    query += """
        ORDER BY created_at DESC, id DESC
        LIMIT %(limit)s
    """
    params['limit'] = 21  # Fetch one extra to check if there's a next page

    rows = execute(query, params)

    # Check if there's a next page
    has_next = len(rows) > 20
    items = rows[:20]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = {
            'created_at': last['created_at'].isoformat(),
            'id': last['id'],
        }

    return Page(items=items, next_cursor=next_cursor)
```

**Advanced: Composite Filter Pagination**

```sql
── When you need complex filters with cursor pagination ───

-- Problem: User filters by status + date range + search by order_id
-- Cursor pagination needs a stable sort order

── Solution 1: Composite index ────────────────────────────

CREATE INDEX idx_orders_composite ON orders (
    status,
    created_at DESC,
    id DESC
) INCLUDE (amount, order_id);

-- Query with cursor:
SELECT id, order_id, amount, created_at
FROM orders
WHERE status = 'completed'
  AND created_at BETWEEN '2024-01-01' AND '2024-06-15'
  AND (created_at, id) < ('2024-06-14T12:00:00Z', 50000)
ORDER BY created_at DESC, id DESC
LIMIT 20;

-- This works well because PostgreSQL can use the composite index
-- for both filtering and ordering!

── Solution 2: Search-based pagination (order_id lookup) ─

-- If user searches for a specific order_id range:
-- Can't use cursor pagination easily with arbitrary search filters

-- Strategy: Use a stable page token that includes all filter state
-- Encode filters + cursor in a signed token:

-- Token format: base64(json({
--   'cursor': {'created_at': '...', 'id': 12345},
--   'filters': {'status': 'completed', 'q': 'ORD-123'}
-- }))

-- Server decrypts token, applies both filters and cursor
-- Trade-off: more complex, but still efficient

── Solution 3: Pagination via id lookup (for single-record scenarios) ─

-- If you need to paginate through all orders for a single user:
-- Use the fact that (user_id, created_at) is unique

SELECT id, order_id, amount, created_at
FROM orders
WHERE user_id = 42
  AND (created_at, id) < ('2024-06-14T12:00:00Z', 50000)
ORDER BY created_at DESC, id DESC
LIMIT 20;

-- Index: (user_id, created_at DESC, id DESC)
```

**Pagination Strategy Comparison:**

```yaml
                   Offset          Cursor (Keyset)      Seek (ID-based)
                   ──────          ────────────────     ───────────────
Performance        Degrades with   O(log N + limit)     O(log N + limit)
                   page number     (constant time)      (constant time)

Random access      ✅ Yes           ❌ No                ❌ No
(to page 500K)

Real-time updates  ❌ Duplicates/   ✅ No duplicates     ✅ No duplicates
                   misses rows     even with inserts    even with inserts

Implementation     Simple          Moderate             Simple (if sorted by PK)
complexity

Filter support     ✅ Any filter    ❌ Only on indexed    ❌ Only on indexed
                                    columns              columns with stable sort

Backward           ✅ Yes           ✅ Yes (reverse       ✅ Yes (reverse
pagination                           cursor)              comparison)

Best for           Small datasets   Large datasets,      Large datasets,
                   (< 10K rows)     infinite scroll,    sorted by PK
                                    real-time data

DB support         Universal        SQL standard        SQL standard
```

**Recommendation:**

```yaml
Use cursor-based pagination when:
  - You have > 10K rows
  - Users do infinite scroll (no page number)
  - Data changes frequently (real-time updates)
  - You need consistent ordering across requests

Use offset-based pagination when:
  - You have < 10K rows (it's fine)
  - Users need to jump to page N (e.g., "page 42 of 500")
  - The UI shows page numbers
  - Data is static (no inserts between pagination requests)

Hybrid approach:
  - For most pages: use cursor-based for performance
  - For the "jump to page" feature: estimate position from page number
    (approximate offset from estimated row count, then use cursor from there)
  - Or: compute cursor from page number heuristically
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Offset problem** | Quantifies why OFFSET is slow at scale (scan + discard) |
| **Cursor mechanics** | Explains (created_at, id) < (...) predicate for index seek |
| **Composite index** | Creates covering index that supports both filter and sort |
| **Trade-off matrix** | Knows when to use each strategy and why |

---

### Q12: "You're migrating from MySQL to PostgreSQL. A colleague claims 'PostgreSQL doesn't need as many indexes as MySQL.' How do you evaluate this claim? What indexing differences matter most in practice?"

**What They're Really Testing:** Whether you understand the fundamental differences between MySQL (InnoDB) and PostgreSQL indexing, and can translate MySQL patterns to PostgreSQL equivalents.

**Answer:**

**The Claim: Truth and Nuance**

```yaml
The claim: "PostgreSQL doesn't need as many indexes as MySQL"

Partly true, but for different reasons than most people think:

TRUE because:
  - PostgreSQL has better query planning (merge joins, hash joins, bitmap scans)
  - PostgreSQL supports index-only scans (visibility map)
  - PostgreSQL can use partial indexes more effectively
  - PostgreSQL's MVCC doesn't cause index-page-level lock contention
  - PostgreSQL supports multiple index types (not just B-Tree)

FALSE because:
  - Both systems need indexes for the same fundamental reasons (query performance)
  - PostgreSQL still needs covering indexes for index-only scans
  - PostgreSQL doesn't have clustered indexes (InnoDB uses PK as clustered)
  - PostgreSQL's heap storage means every non-index query needs a full seq scan
  - PostgreSQL can't do "loose index scan" (skip scan) until PG 16
```

**Key Differences:**

```yaml
┌────────────────────────────────────────────────────────────────────────┐
│                        MySQL InnoDB                  PostgreSQL        │
├────────────────────────────────────────────────────────────────────────┤
│ Storage model       Clustered index (PK =           Heap + separate    │
│                     data storage)                   indexes            │
│                                                     ─────────────────  │
│                                                     This means:        │
│                                                     - PK index is just │
│                                                       an index (not    │
│                                                       data storage)    │
│                                                     - Always need     │
│                                                       heap fetch for  │
│                                                       non-index cols   │
│                                                     - No clustered     │
│                                                       overhead on     │
│                                                       secondary idxs   │
│                                                                        │
│ Index-only scan    Requires covering              ✅ Supported via     │
│                     indexes (INCLUDE)              visibility map +    │
│                                                    INCLUDE columns     │
│                                                                        │
│ Partial indexes    ❌ Not supported               ✅ Supported         │
│                     (all index entries              WHERE clause       │
│                      for all rows)                 on index           │
│                                                                        │
│ Expression indexes ❌ Virtual columns only         ✅ Supported         │
│                                                                        │
│ Multiple index     ✅ Yes (B-Tree only)           ✅ B-Tree, Hash,    │
│ types                                               GiST, GIN, BRIN,  │
│                                                     SP-GiST            │
│                                                                        │
│ Concurrent index   ❌ (blocks writes)             ✅ CONCURRENTLY     │
│ creation                                             (non-blocking)   │
│                                                                        │
│ Bitmap scan        ❌ Not supported               ✅ Supported         │
│ (combining                                          (combines multiple │
│  multiple indexes)                                   indexes in bitmap)│
│                                                                        │
│ Loose index scan   ✅ Supported                   ❌ Not until PG 16  │
│ (skip scan for                                          (skip scan)    │
│  low-cardinality)                                                      │
└────────────────────────────────────────────────────────────────────────┘
```

**MySQL-to-PostgreSQL Index Translation Guide:**

```sql
── MySQL: CREATE INDEX idx_status ON orders (status);
── PostgreSQL: Same, but consider partial index!

-- Only index 'completed' and 'shipped' statuses:
CREATE INDEX idx_orders_active ON orders (status)
    WHERE status IN ('completed', 'shipped', 'processing');
-- 3 values indexed instead of 10 → 70% smaller index!

── MySQL: CREATE INDEX idx_user_date ON orders (user_id, created_at);
── PostgreSQL: Same, but know that it works differently!

-- In MySQL (InnoDB): secondary index includes PK → index covers more
-- In PostgreSQL: index is separate → consider INCLUDE for coverage:
CREATE INDEX idx_orders_user_date ON orders (user_id, created_at)
    INCLUDE (amount, status);
-- Index-only scan if amount and status are in INCLUDE

── MySQL: ALTER TABLE ... ADD INDEX (LOWER(email));
── PostgreSQL: Expression index!

CREATE INDEX idx_users_email_lower ON users (LOWER(email));
SELECT * FROM users WHERE LOWER(email) = 'alice@example.com';
-- PostgreSQL can use the index! No virtual column needed.

── MySQL: No direct equivalent for full-text index
── PostgreSQL: GIN index for full-text search!

CREATE INDEX idx_docs_fts ON documents USING gin (
    to_tsvector('english', title || ' ' || body)
);
SELECT * FROM documents
WHERE to_tsvector('english', title || ' ' || body)
    @@ to_tsquery('english', 'postgresql & performance');

── MySQL: No direct equivalent for JSON index
── PostgreSQL: GIN index for JSONB!

CREATE INDEX idx_profiles_meta ON profiles USING gin (metadata jsonb_path_ops);
SELECT * FROM profiles WHERE metadata @> '{"role": "admin"}';

── MySQL: No direct equivalent for covering index
── PostgreSQL: INCLUDE columns!

-- MySQL needs: CREATE INDEX idx_user ON orders (user_id);
-- PostgreSQL:
CREATE INDEX idx_orders_user_covering ON orders (user_id) INCLUDE (amount, status);
-- Equivalent to covering index in MySQL

── MySQL: PRIMARY KEY is clustered (data stored in PK order)
── PostgreSQL: PRIMARY KEY is just a unique index

-- If you need MySQL-like clustered behavior:
-- 1. You can't in standard PostgreSQL
-- 2. Use BRIN on monotonically increasing PK for range scans:
CREATE INDEX idx_pk_brin ON orders USING brin (id);
-- 3. Or use pg_repack to physically reorder rows:
--    pg_repack --table orders --order-by id
```

**Common MySQL Migration Pitfalls:**

```sql
── Pitfall 1: Assuming PK = Clustered Index ───────────────

-- MySQL: SELECT * FROM users WHERE id = 42
--   → PK index lookup returns all columns (clustered)
-- PostgreSQL: SELECT * FROM users WHERE id = 42
--   → PK index lookup returns CTID → heap fetch for all columns
--   → If selecting only PK: it IS index-only (B-Tree leaf contains PK)
--   → If selecting other columns: one heap fetch per row

── Pitfall 2: Counting on loose index scan ────────────────

-- MySQL can do "skip scan" — jump between distinct values:
--   SELECT DISTINCT status FROM orders;
--   → Uses index on (status, created_at) without scanning all rows
--
-- PostgreSQL (pre-16) needs a full index scan for DISTINCT:
--   → Must scan ALL index entries to find distinct statuses
--   → PG 16+: SELECT DISTINCT status FROM orders;
--     Uses skip scan: O(n * distinct_values) instead of O(total_rows)

── Pitfall 3: Missing index-only scans due to visibility ──

-- PostgreSQL's index-only scan relies on the visibility map
-- If the VM is incomplete (pages marked dirty), PostgreSQL must
-- fetch the heap to check visibility
-- Solution: ensure VACUUM keeps VM up to date

── Pitfall 4: Assuming ANALYZE is automatic like MySQL ────

-- MySQL: ANALYZE TABLE is lightweight (reads 200 random pages)
-- PostgreSQL: ANALYZE can be expensive on large tables
-- But: PostgreSQL's autovacuum includes autoanalyze
-- Tune: default_statistics_target = 500 for better plans

── Pitfall 5: Expecting COUNT(*) to be instant ────────────

-- MySQL: COUNT(*) on InnoDB is SLOW (no separate row count)
-- PostgreSQL: COUNT(*) is ALSO SLOW (MVCC means counting live tuples)
-- Neither has an instant COUNT — both need an index-only scan or seq scan
-- Use estimated counts or MATERIALIZED VIEWS for fast counts
```

**When PostgreSQL really DOES need fewer indexes:**

```yaml
PostgreSQL can reduce index count because of:

1. Bitmap scans:
   - Multiple indexes can be combined on-the-fly
   - MySQL needs a composite index for the same effect
   - Example:
     SELECT * FROM orders
     WHERE status = 'completed' AND created_at > '2024-01-01';
     → PostgreSQL can use TWO indexes (one on status, one on created_at)
     → MySQL needs a composite index (status, created_at)

2. Partial indexes:
   - Index only 25% of rows = 75% smaller index
   - Fewer indexes needed because each covers a targeted subset
   - Example: instead of one index on status for all values,
              create partial indexes for frequent values

3. Index-only scans:
   - INCLUDE columns reduce need for separate indexes
   - Example: instead of (user_id) + (user_id, created_at),
              create (user_id) INCLUDE (created_at, amount, status)

4. BRIN for sequential data:
   - Replace B-Tree index on timestamps with BRIN
   - BRIN is 1000× smaller → fewer I/O bytes to maintain
   - Example: events table → BRIN(created_at) instead of B-Tree

5. Expression indexes:
   - Index LOWER(email) without adding a column
   - No need for generated columns like MySQL
```

**Staff-Level Evaluation:**

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Clustered vs heap** | Explains the fundamental difference between InnoDB (clustered PK as data) and PostgreSQL (heap + separate indexes) |
| **Partial indexes** | Identifies partial indexes as PostgreSQL's superpower for reducing index bloat |
| **Bitmap scans** | Knows PostgreSQL can combine multiple indexes for query optimization |
| **Migration pitfalls** | Identifies specific patterns that work differently (loose scan, clustering, visibility) |

---

## 12. Common Pitfalls & Anti-Patterns

### 12.1 Index Bloat

```sql
── Cause: Dead index entries from updates (MVCC)
── Effect: Index is 2-10× larger than needed → slower scans, more memory

── Monitor:
SELECT schemaname || '.' || relname AS table_name,
       indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       round(100.0 * pg_relation_size(indexrelid) / nullif(pg_relation_size(indrelid), 0), 2) AS index_pct
FROM pg_stat_user_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(indexrelid) DESC;

── Fix:
REINDEX INDEX CONCURRENTLY idx_users_email;  -- Non-blocking!
REINDEX TABLE CONCURRENTLY users;             -- All indexes on table
```

### 12.2 Row-Level Lock Contention

```sql
── Cause: Concurrent UPDATEs on the same row
── Effect: Queries waiting on "transactionid" lock

── Monitor:
SELECT pid, wait_event_type, wait_event, state,
       pg_blocking_pids(pid) AS blocked_by,
       LEFT(query, 100) AS query
FROM pg_stat_activity
WHERE wait_event = 'transactionid'
   OR pid = ANY(pg_blocking_pids(pid));

── Fix:
-- 1. Batch updates: UPDATE ... WHERE id IN (...) instead of single-row UPDATEs
-- 2. Partition hot rows (e.g., counter table)
-- 3. Use advisory locks for application-level ordering
-- 4. Consider if SELECT ... FOR UPDATE is necessary
```

### 12.3 XID Wraparound Panic

```sql
── Cause: 32-bit XID exhaustion (2 billion transactions)
── Effect: Database becomes read-only, aggressive vacuum required

── Monitor:
SELECT datname, age(datfrozenxid) AS age,
       round(100.0 * age(datfrozenxid) / 2000000000, 2) AS pct_to_wraparound
FROM pg_database
ORDER BY age DESC;

── Prevention:
-- 1. Ensure autovacuum is running (not disabled!)
-- 2. Set autovacuum_freeze_max_age appropriately
-- 3. Use aggressive VACUUM FREEZE during maintenance windows
VACUUM (FREEZE, VERBOSE) orders;

-- 4. For insert-only tables, periodically FREEZE
VACUUM (FREEZE, INDEX_CLEANUP OFF) historical_events;
```

### 12.4 Connection Leaks

```sql
── Cause: Application doesn't close connections → "too many connections"
── Effect: New connections rejected, existing connections slow

── Monitor:
SELECT state, count(*) AS count,
       round(count(*) * 100.0 / (SELECT setting::int FROM pg_settings WHERE name = 'max_connections'), 2) AS pct
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY state;

── Fix:
-- 1. Use connection pooler (PgBouncer) — ESSENTIAL for production
-- 2. Set proper idle timeout:
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET tcp_keepalives_idle = '60';
ALTER SYSTEM SET tcp_keepalives_interval = '10';
ALTER SYSTEM SET tcp_keepalives_count = '6';  -- 60 + 10*6 = 120s to kill dead connections

-- 3. Kill idle transactions:
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND age(clock_timestamp(), state_change) > interval '5 minutes';
```

### 12.5 Long-Running Transactions

```sql
── Cause: Transaction open for hours → blocks VACUUM → table bloat
── Effect: autovacuum can't remove dead tuples, table grows unbounded

── Monitor:
SELECT pid, state,
       age(clock_timestamp(), xact_start) AS txn_age,
       age(clock_timestamp(), query_start) AS query_age,
       LEFT(query, 100) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND state IN ('active', 'idle in transaction')
  AND backend_type = 'client backend'
ORDER BY txn_age DESC
LIMIT 10;

── Prevention:
-- 1. Set statement_timeout and idle_in_transaction_session_timeout
ALTER SYSTEM SET statement_timeout = '30s';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';

-- 2. Use explicit short transactions:
-- Good:
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;

-- Bad:
BEGIN;
SELECT * FROM users WHERE id = 42;  -- Open for hours...
-- (application does other work)
UPDATE accounts SET balance = 900 WHERE id = 42;
COMMIT;  -- 5 hours later!
```

### 12.6 Sequential Scan Denial of Service

```sql
── Cause: A query accidentally scans a 1TB table (no index, bad stats, or wrong plan)
── Effect: Buffer pool polluted, hot pages evicted, all queries slow

── Monitor:
-- Find seq scans:
SELECT schemaname || '.' || relname AS table_name,
       seq_scan,
       seq_tup_read,
       idx_scan,
       round(100.0 * seq_scan / nullif(seq_scan + idx_scan, 0), 2) AS seq_scan_pct
FROM pg_stat_user_tables
WHERE seq_scan > 1000
ORDER BY seq_tup_read DESC
LIMIT 20;

── Prevention:
-- 1. Set enable_seqscan = off for specific roles (temporarily, for debugging):
ALTER ROLE app_user SET enable_seqscan = off;

-- 2. Use statement_timeout to kill runaway queries:
ALTER SYSTEM SET statement_timeout = '60s';

-- 3. Use pg_stat_statements to find high-row-count scans:
SELECT LEFT(query, 80) AS query,
       calls,
       rows,
       shared_blks_hit,
       shared_blks_read
FROM pg_stat_statements
ORDER BY shared_blks_read DESC
LIMIT 10;

-- 4. Ensure proper indexing + ANALYZE regular schedule
```

### 12.7 Auto-Increment Gap (Sequence Exhaustion)

```sql
── Cause: Using SERIAL/BIGSERIAL for primary key, inserting at high rate
── Effect: SERIAL (int4) wraps after 2B → ERROR: duplicate key
──          BIGSERIAL (int8) wraps after 9 quintillion → fine for decades

── Fix for existing SERIAL tables:
ALTER TABLE users
    ALTER COLUMN id TYPE bigint;

── For high-insert tables, use BIGSERIAL from the start:
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,  -- Never use SERIAL for high-insert tables
    ...
);

── Monitor sequence exhaustion:
SELECT schemaname || '.' || relname AS table_name,
       sequence_name,
       last_value,
       max_value,
       round(100.0 * last_value / max_value, 2) AS pct_exhausted
FROM (
    SELECT schemaname, relname,
           pg_get_serial_sequence(schemaname || '.' || relname, 'id') AS seq_name
    FROM pg_stat_user_tables
) t
JOIN LATERAL (
    SELECT sequence_name, last_value,
           (sequence_schema || '.' || sequence_name) AS full_seq_name
    FROM information_schema.sequences
) s ON s.full_seq_name = t.seq_name
CROSS JOIN LATERAL (
    SELECT seq.max_value
    FROM pg_sequences seq
    WHERE seq.schemaname = schemaname
      AND seq.sequencename = s.sequence_name
) m
WHERE last_value > 0
ORDER BY pct_exhausted DESC
LIMIT 20;
```

---

> *This guide covers the foundational knowledge expected of a Staff/Principal engineer working with PostgreSQL. Combine this with hands-on production experience tuning, debugging, and designing database systems at scale.*
