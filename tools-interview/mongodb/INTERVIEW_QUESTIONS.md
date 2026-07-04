# 🍃 MongoDB — Staff-Level Interview Questions

> *6 questions covering MongoDB internals, document model, replica sets, sharding, aggregation, and transactions — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Document Model & WiredTiger Storage Engine](#1-document-model-wiredtiger-storage-engine)
2. [Replica Sets: Election, Rollback, Write Concern](#2-replica-sets-election-rollback-write-concern)
3. [Sharding: Architecture, Balancer, Chunk Splitting](#3-sharding-architecture-balancer-chunk-splitting)
4. [Indexing: Compound, Multikey, Text, Geospatial](#4-indexing-compound-multikey-text-geospatial)
5. [Aggregation Pipeline: Optimization & Memory](#5-aggregation-pipeline-optimization-memory)
6. [Transactions: Multi-Document ACID in MongoDB 4.0+](#6-transactions-multi-document-acid-in-mongodb-40)

---

## 1. Document Model & WiredTiger Storage Engine

**Q:** "MongoDB stores documents in BSON format. Explain how BSON differs from JSON, how documents are stored on disk by WiredTiger, and why MongoDB's document model can lead to higher write throughput than a relational database for certain workloads."

**What They're Really Testing:** Whether you understand MongoDB's core storage engine — BSON serialization, WiredTiger's B-tree with compression, and the document model's implications for write performance.

### Answer

**BSON vs JSON:**

```
BSON (Binary JSON): serialization format used by MongoDB
Legacy:  JSON stores strings for everything
         BSON stores typed data (int32, int64, double, datetime, binary)

Type representation:
  JSON: {"age": 30, "name": "Alice", "active": true}
  BSON: \x10\x61\x67\x65\x00\x1E\x00\x00\x00  (int32 30)
        \x02\x6E\x61\x6D\x65\x00\x06\x00\x00\x00Alice\x00
        \x08\x61\x63\x74\x69\x76\x65\x00\x01

  BSON types: double, string, object, array, binary, objectId, boolean,
              date, null, regex, int32, timestamp, int64, decimal128

  Size overhead:
  { "_id": ObjectId("..."), "name": "Alice", "age": 30 }
  JSON:  57 bytes
  BSON:  43 bytes (25% smaller because numeric types are binary)
```

**WiredTiger Storage Engine:**

```
Document storage:
  Collection → B-tree of documents
  Each document stored as a BSON byte array in a WiredTiger page

  WiredTiger page (default 4KB or 16KB):
  ├── Page header (checksum, free space offset)
  ├── Documents (BSON byte arrays)
  ├── Offsets (pointer to each document within page)
  └── Free space tracking

Write path:
  1. Document received → BSON serialization
  2. Write-ahead log (journal): fsynced every 100ms (commitIntervalMs)
  3. In-memory cache (snapshot engine): document updated in cache
  4. Background: modified pages written to disk (checkpoint every 60s)

Read path:
  1. Snapshot engine: consistent view at point in time
  2. Cache hit: return from memory (sub-microsecond)
  3. Cache miss: read from disk to cache → return

Compression:
  - Snappy (default): fast, 2-3:1 ratio
  - Zlib: slower, 3-5:1 ratio
  - Zstandard: balanced, 2-4:1 ratio

Document model advantage for writes:
  - All related data in ONE document = one write to ONE collection
  - No joins needed, no foreign key constraints
  - No multi-table updates (for most operations)
  - One B-tree write vs multiple table writes in relational DB
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **BSON types** | Understands typed binary format and its space efficiency over JSON |
| **WiredTiger B-tree** | Knows document storage, journaling, and checkpointing in WT |
| **Compression** | Can compare Snappy vs Zlib vs Zstd for different workloads |
| **Document model win** | Explains why single-document writes outperform relational multi-table writes |

---

## 2. Replica Sets: Election, Rollback, Write Concern

**Q:** "Your MongoDB replica set has 3 members. The primary goes down for 10 seconds. Walk through the election, failover, and what happens to writes that were acknowledged before the crash. How do you prevent rollbacks?"

**What They're Really Testing:** Whether you understand MongoDB's replication protocol — election timing, the rollback process, and write concern guarantees.

### Answer

**Replica Set Architecture:**

```
Replica Set "rs0" (3 members):
  ┌────────┐     ┌────────┐     ┌────────┐
  │ Primary │     │Secondary│    │Secondary│
  │  Node A  │     │  Node B │    │  Node C │
  └────┬────┘     └────────┘     └────────┘
       │                │                │
       └────────────────┴────────────────┘
             Replication (oplog sync)
  
  Oplog: capped collection (local.oplog.rs)
    - Default size: 5% of free disk space (min 990MB, max 50GB)
    - Each operation recorded as an oplog entry
    - Secondaries apply oplog entries asynchronously
```

**Failover Timeline:**

```
t=0: Primary A receives write {w: "majority"}
   → Writes to own oplog
   → Acknowledges to client (majority = this primary only? No!)
   → Wait: "majority" requires ACK from majority of voting members!

t=2: Primary A crashes (power failure, no clean shutdown)

t=2-10: Secondaries B and C detect A is unreachable
   - heartbeat: every 2 seconds
   - electionTimeoutMillis: 10 seconds (default)
   - After 10s of no heartbeat → election triggered

t=10: Election starts on B and C
   - Both check: who has the most recent oplog?
   - C receives heartbeat from B (higher priority or more recent)
   - Node C votes for B (first-come-first-served within electionTimeout)
   - Node B: 2 votes (B self-vote + C vote) > majority(3) = 2
   - Node B becomes PRIMARY

t=12: New primary B accepts writes
   - Client reconnects → discovers new primary
   - Writes resume
```

**Rollback Scenario:**

```
Critical sequence:
  Write 100: {_id: 1, amount: 100}  ← acknowledged by primary A
  Write 101: {_id: 2, amount: 200}  ← acknowledged by primary A
  
  Primary A crashes BEFORE replicating 100 and 101 to secondaries!
  
  New primary B: has entries up to write 99
  Old primary A comes back online:
    - A has writes 100, 101 that B doesn't have
    - B has entry 99 (common entry)
    - Rollback: A undoes writes 100, 101
  
  Rollback data: saved to rollback/ directory on A
  Admin must manually apply (or discard) rolled-back writes!

Prevention:
  WriteConcern w: "majority" (reduces rollback risk)
  - Write acknowledged only after majority of voting members have it
  - If A acknowledged w:majority write → at least ONE secondary has it
  - After failover: that secondary (now primary) still has the write
  - Rollback: cannot happen for w:majority writes!
```

**Write Concern Hierarchy:**

```javascript
// Client-side write concern:
db.collection.insertOne(
    { _id: 1, amount: 100 },
    { writeConcern: { w: "majority", j: true, wtimeout: 5000 } }
    //   │                │          │          │
    //   │                │          │          └── Wait max 5s then error
    //   │                │          └───────────── Journal: fsync to journal
    //   │                └──────────────────────── Wait majority of voting members
    //   └───────────────────────────────────────── Acknowledgment level
)

// w: 1 (default)     → Primary only (fast, rollback possible)
// w: "majority"      → Majority of voting members (durable, slower)
// w: 2               → 2 members (primary + 1 secondary)
// w: "majority" + j  → Journaled (most durable)
// wtimeout: 5000     → Error after 5 seconds (prevent indefinite blocking)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Election timing** | Knows electionTimeoutMillis and heartbeat interval |
| **Rollback cause** | Understands rollback happens when old primary has writes not in new primary's oplog |
| **Write concern** | Explains w:majority prevents rollback (write is durable across replica set) |
| **Oplog sizing** | Knows oplog is capped, default 5% of disk, can be increased for longer recovery |

---

## 3. Sharding: Architecture, Balancer, Chunk Splitting

**Q:** "Your MongoDB cluster has 10TB of data. Queries are getting slow because the working set doesn't fit in memory. Design a sharded cluster. How does the balancer distribute chunks? How do you choose a shard key? What happens during a chunk migration?"

**What They're Really Testing:** Whether you understand MongoDB's sharded architecture — mongos router, config servers, chunk splitting, and the balancer's impact on performance.

### Answer

**Sharded Cluster Architecture:**

```
Application
    │
    ▼
┌─────────────────────────────────┐
│       mongos (router)           │  ← One per application / region
│  Routes queries to correct shard │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│   Config Servers (replica set, 3 nodes)              │
│   Stores: shard metadata, chunk ranges, DB config    │
│   Chunk distribution: {_id: "001" → "010"} → Shard A │
└─────────────────────────────────────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│ Shard  │ │ Shard  │  ... up to N shards
│  A    │ │  B    │
│ RS: 3  │ │ RS: 3  │  ← Each shard is a replica set (3 nodes)
└────────┘ └────────┘
```

**Shard Key Selection:**

```javascript
// Shard key = field(s) MongoDB uses to distribute documents

// Good shard key properties:
// 1. HIGH CARDINALITY (many unique values)
// 2. EVEN DISTRIBUTION (no hot shards)
// 3. QUERY PATTERN (queries include shard key for targeted routing)

// Example 1: Hashed shard key (best for even distribution)
sh.shardCollection("myapp.events", { event_id: "hashed" })

// Example 2: Compound shard key (for common query pattern)
sh.shardCollection("myapp.orders", { customer_id: 1, _id: 1 })

// Example 3: BAD shard key — monotonically increasing
sh.shardCollection("myapp.logs", { timestamp: 1 })
// Problem: all new writes go to ONE shard (hot shard)
// Solution: use hashed timestamp { timestamp: "hashed" }

// Example 4: Range-based shard key (for range queries)
sh.shardCollection("myapp.users", { country: 1, user_id: 1 })
// Queries: db.users.find({ country: "US" }) → only US shard hit
// But: some countries may have much more data (uneven)
// Need to ensure country distribution is manageable
```

**Chunk Splitting & Migration:**

```
Chunk: contiguous range of shard key values

Initial state:
  Shard A: chunk {min → max} (100,000 documents, 25GB)
           → Too large! Must split.

Split threshold:
  Spec: 64MB (default chunk size)
  When chunk exceeds 64MB → mongos splits into two chunks

  After split:
  Shard A: chunk1 {min → "500"}, chunk2 {"500" → max} (50,000 docs each)

Balancer:
  - Runs on config server primary (mongos in older versions)
  - Checks: are chunks evenly distributed across shards?
  - Threshold: difference > 8 chunks (configurable)
  
  Migration process:
  1. Balancer: move chunk2 from Shard A to Shard B
  2. Shard B: opens a donor shard connection to Shard A
  3. Shard B: copies documents in chunk2 from Shard A
  4. While copying: Shard A still accepts writes to chunk2
  5. Shard B: catches up with writes during copy
  6. Critical section: Shard A stops serving chunk2 → Shard B takes over
  7. Config server: update chunk location (Shard A → Shard B)
  
  Impact during migration:
  - Network: chunk data copied across network
  - Write latency: spike at critical section (brief pause)
  - Read: targeted queries slow during critical section
```

**Balancer Tuning:**

```javascript
// Control balancer timing:
sh.setBalancerState(true)              // Enable/disable
db.settings.updateOne(
    { _id: "balancer" },
    { $set: {
        activeWindow: { start: "02:00", stop: "06:00" }  // Only balance at 2-6 AM!
    }},
    { upsert: true }
)

// Migration threshold:
// Default: 8 chunks imbalance → trigger migration
// For 100TB, you may want smaller chunks (32MB) and tighter balance

// Shard zone for data locality:
sh.addShardTag("shard-01", "US")
sh.addShardTag("shard-02", "EU")
sh.addTagRange("myapp.users", { country: "US" }, { country: "US\uffff" }, "US")
sh.addTagRange("myapp.users", { country: "DE" }, { country: "DE\uffff" }, "EU")
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Shard key criteria** | Knows cardinality, distribution, and query pattern requirements |
| **Hashed vs range** | Can compare hashed (even distribution) vs range (targeted range queries) |
| **Chunk splitting** | Understands chunks split at 64MB for even distribution |
| **Migration impact** | Knows critical section causes brief write pause during chunk handoff |

---

## 4. Indexing: Compound, Multikey, Text, Geospatial

**Q:** "You have a MongoDB collection with 50M documents. A query that filters on status, sorts by createdAt, and projects only 2 fields takes 5 seconds without an index. Design the optimal index. How do compound indexes support sort? What's an index intersection?"

**What They're Really Testing:** Whether you understand MongoDB's B-tree index internals — ESR rule, covered queries, and index intersection trade-offs.

### Answer

**Compound Index Design (ESR Rule):**

```
ESR Rule: Equality → Sort → Range

Query:
  db.orders.find({
      status: "shipped",              // Equality (E)
      createdAt: { $gte: ISODate("2024-01-01") }  // Range (R)
  }).sort({
      createdAt: 1                     // Sort (S)
  }).limit(20)

Optimal index (ESR order):
  db.orders.createIndex({ status: 1, createdAt: 1 })

Why this order:
  1. Equality fields FIRST (status = exact match)
     → Reduces scan to documents matching "shipped"
  2. Sort field SECOND (createdAt)
     → B-tree traversal yields sorted order WITHOUT in-memory sort!
  3. Range field THIRD (or same position as sort if different)
     → Range scan from the indexed sort value

Index usage:
  Query without sort (range on createdAt):
  { status: 1, createdAt: 1 } → traverses from 2024-01-01 in status:"shipped"
  
  Query with sort + range:
  { status: 1, createdAt: 1 } → great! B-tree yields sorted docs
  
  Wrong order: { createdAt: 1, status: 1 }
  → Can't sort by createdAt efficiently because status filter removes docs
  → SORT stage in memory (no index sort!)
```

**Covered Query:**

```javascript
// Covered query: ALL returned fields are in the index
// No need to fetch documents from the collection!

// Covered index:
db.orders.createIndex(
    { status: 1, createdAt: 1 },
    { projection: { status: 1, createdAt: 1, amount: 1 } }
)

// Covered query:
db.orders.find(
    { status: "shipped" },
    { _id: 0, status: 1, createdAt: 1, amount: 1 }
).sort({ createdAt: 1 })
// → MongoDB reads from INDEX ONLY (no document fetch!)
// → 5 seconds → MILLISECONDS
```

**Multikey Index (Array Fields):**

```javascript
// For fields containing arrays:
db.products.createIndex({ tags: 1 })

// Document: { _id: 1, tags: ["electronics", "sale", "new"] }
// Index entries:
//   "electronics" → doc { _id: 1 }
//   "sale" → doc { _id: 1 }
//   "new" → doc { _id: 1 }

// Compound multikey index limitation:
// Only ONE array field per compound index!
db.products.createIndex({ tags: 1, categories: 1 })
// Error if BOTH tags and categories are arrays in the same document!
// (Cross-product: tags × categories can explode)

// Workaround: index ONE array field, filter the other in application
```

**Index Type Selection:**

```yaml
Type            | Use Case                    | Example
----------------|-----------------------------|--------------------------------
B-tree (default)| Equality, range, sort       | createIndex({ status: 1 })
Compound B-tree | Multi-field queries (ESR)   | createIndex({ status: 1, date: 1 })
Multikey        | Array fields                | createIndex({ tags: 1 })
Text            | Full-text search             | createIndex({ description: "text" })
Geospatial 2d   | 2D coordinates               | createIndex({ location: "2d" })
Geospatial 2dsphere | GeoJSON on sphere       | createIndex({ location: "2dsphere" })
Hashed          | Shard key (even distribution)| createIndex({ _id: "hashed" })
TTL             | Auto-expire documents        | createIndex({ createdAt: 1 }, { expireAfterSeconds: 86400 })
Partial         | Index only matching docs     | createIndex({ status: 1 }, { partialFilterExpression: { status: "active" } })

# Partial index: smaller index, less memory, faster for specific queries
db.orders.createIndex(
    { createdAt: 1 },
    { partialFilterExpression: { status: "pending" } }
)
# Only indexes pending orders → much smaller than full index!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ESR rule** | Knows Equality → Sort → Range index field order |
| **Covered queries** | Understands index-only queries avoid document fetch |
| **Multikey limit** | Knows only one array field per compound index |
| **Index type selection** | Can match query patterns to optimal index types |

---

## 5. Aggregation Pipeline: Optimization & Memory

**Q:** "Your aggregation pipeline processes 10M documents, takes 30 seconds, and uses 2GB of memory. Explain what $match, $group, $sort do internally. How does the pipeline optimize stage ordering? When does it spill to disk?"

**What They're Really Testing:** Whether you understand MongoDB's aggregation engine — pipeline optimization, memory constraints (100MB limit), and allowDiskUse.

### Answer

**Aggregation Pipeline Optimization:**

```javascript
// Pipeline stages execute in sequence:
db.orders.aggregate([
    { $match: { status: "shipped" } },          // Stage 1: filter
    { $group: { _id: "$customer_id", total: { $sum: "$amount" } } },  // Stage 2: group
    { $sort: { total: -1 } },                    // Stage 3: sort
    { $limit: 20 }                               // Stage 4: top 20
])

// MongoDB optimization: COALESCE $match with $sort if possible
// If $match is before $group and uses indexed field → INDEX used!
// $match before $project or $unwind → fewer docs through pipeline

// Optimization rewrite (manual):
// 1. Push $match as early as possible (before $unwind, $group)
// 2. Use indexes for $match and $sort
// 3. $project unnecessary fields FIRST to reduce memory

// Query plan visualization:
db.orders.explain("executionStats").aggregate([...])
// Look for: stage boundaries, document counts, execution time per stage
```

**Memory Constraints:**

```javascript
// Default: 100MB memory per pipeline stage
// If $group or $sort exceeds 100MB → ERROR!

// Solution: allow disk usage
db.orders.aggregate([
    { $group: { ... } },
    { $sort: { ... } }
], { allowDiskUse: true })
// → MongoDB spills to temporary files on disk
// → Slower, but avoids OOM

// Memory-heavy stages:
// $group: stores all groups in memory (100MB limit)
// $sort: sorts entire result set in memory (100MB limit)
// $bucket: similar to $group
// $facet: runs multiple pipelines simultaneously!

// When $group spills to disk:
// - Writes intermediate state to /tmp/_mdb_tmp_*
// - Reads back for final merge
// - Performance: 10-100× slower than in-memory

// Memory optimization:
// 1. $match first (reduce documents)
// 2. $project early (reduce field size)
// 3. $limit before $sort (if possible)
// 4. Smaller group key (use fewer fields)
```

**$lookup (Left Outer Join) Performance:**

```javascript
// $lookup: MongoDB's JOIN (expensive!)
db.orders.aggregate([
    { $lookup: {
        from: "customers",
        localField: "customer_id",
        foreignField: "_id",
        as: "customer"
    }}
])

// Internally:
// 1. For EACH document in orders collection
// 2. Query customers collection: find({ _id: order.customer_id })
// 3. Add result to the document as "customer" array

// 10M orders × 1 lookup each → 10M queries to customers!
// Performance: VERY SLOW

// Optimization:
// 1. Create index on customers._id (should be indexed automatically)
// 2. Use $lookup.pipeline in MongoDB 5.0+:
db.orders.aggregate([
    { $lookup: {
        from: "customers",
        let: { cid: "$customer_id" },
        pipeline: [
            { $match: { $expr: { $eq: ["$_id", "$$cid"] } } },
            { $project: { name: 1, email: 1 } }  // Only needed fields
        ],
        as: "customer"
    }}
])
// → Can push pipeline stages into the foreign collection
// → More efficient

// 3. Denormalize: embed customer data in orders (document model advantage!)
```

**Aggregation Pipeline Stages Summary:**

```yaml
Stage       | Memory | Disk | Use
------------|--------|------|--------------------------------------
$match      | Low    | No   | Filter early (use indexes)
$project    | Low    | No   | Reshape/limit fields
$group      | High   | Yes  | Group by key, compute aggregates
$sort       | High   | Yes  | Sort entire result set
$lookup     | Medium | No   | Join with another collection
$unwind     | Medium | No   | Deconstruct array (can explode cardinality!)
$bucket     | High   | Yes  | Histogram-like bucketing
$facet      | High   | Yes  | Multiple pipelines in parallel
$setWindowFields| High | Yes | Window functions (5.0+)
$unionWith  | Low    | No   | Union two collections
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pipeline optimization** | Pushes $match/$limit as early as possible |
| **100MB limit** | Knows default memory per stage, allowDiskUse for overflow |
| **$lookup cost** | Understands $lookup is per-document query — needs index |
| **allowDiskUse** | Knows when and how to enable disk spill for large aggregations |

---

## 6. Transactions: Multi-Document ACID in MongoDB 4.0+

**Q:** "Your application needs to atomically update an order and decrement inventory in two collections. How do MongoDB transactions work? What are the limitations compared to traditional RDBMS transactions? How does the two-phase commit in a sharded cluster differ?"

**What They're Really Testing:** Whether you understand MongoDB's multi-document ACID transactions — snapshot isolation, operation time, and the cross-shard transaction protocol.

### Answer

**Multi-Document Transaction (MongoDB 4.0+):**

```javascript
const session = db.getMongo().startSession();
session.startTransaction({
    readConcern: { level: "snapshot" },     // Consistent snapshot
    writeConcern: { w: "majority" },         // Durable on majority
    readPreference: "primary"                // Must be primary!
});

try {
    const orders = session.getDatabase("shop").getCollection("orders");
    const inventory = session.getDatabase("shop").getCollection("inventory");

    // Step 1: Create order
    orders.insertOne({
        _id: ObjectId(),
        customer_id: 123,
        items: [{ product_id: 456, quantity: 2 }],
        total: 99.99,
        status: "created",
        createdAt: new Date()
    });

    // Step 2: Decrement inventory
    inventory.updateOne(
        { product_id: 456, quantity: { $gte: 2 } },
        { $inc: { quantity: -2 } }
    );

    // Step 3: Commit (atomically)
    session.commitTransaction();
} catch (e) {
    // Abort: all changes rolled back
    session.abortTransaction();
    throw e;
} finally {
    session.endSession();
}
```

**Transaction Internals (Snapshot Isolation):**

```
1. startTransaction: establishes a snapshot timestamp (multiversion concurrency)
   - Reads see a consistent view from the snapshot time
   - Writes are buffered (not visible outside transaction)

2. Write operations:
   - Only visible WITHIN the transaction
   - Lock: document-level locking in WiredTiger
   - Writes to same document: serialize (one at a time)

3. commitTransaction:
   - Phase 1: Prepare (write intent locks, persist journal)
   - Phase 2: Commit (make writes visible atomically)
   - All-or-nothing: either ALL writes visible or NONE

4. abortTransaction:
   - Discard buffered writes
   - No journal changes needed
   - Fast (nothing to rollback on disk!)

Limitations:
  - Max transaction runtime: 60 seconds (default) → transactionLifetimeLimitSeconds
  - Max lock wait: 5ms (default) → Abort on lock conflict
  - Operations within transaction: limited to 1000 writes
  - No DDL operations (createIndex, createCollection) within transaction
  - Must read from PRIMARY only (no secondary reads)
  - Each transaction needs a new session (cannot reuse)
```

**Cross-Shard Transactions (Sharded Cluster):**

```
Cross-shard transaction (MongoDB 4.2+):

  Application → mongos → coordinates across shards

  mongos acts as transaction coordinator:
  1. Start: snapshot timestamp
  2. Execute: send operations to each shard
  3. Prepare: ask ALL shards to commit (2PC-like)
  4. Commit: all shards commit → done

  Transaction coordinator recovery:
  - If mongos crashes mid-transaction: config server has metadata
  - New mongos picks up: check pending transactions after recovery
  - Recovery: prepare → commit (or abort)

  Performance considerations:
  - Cross-shard transactions are SLOWER (2-phase commit = 2× network round trips)
  - Design for SINGLE-shard transactions wherever possible
  - Include shard key in query to route to single shard
```

**Optimistic Concurrency Control:**

```javascript
// MongoDB uses optimistic concurrency (no write locks by default)
// Fine-grained document-level locking in WiredTiger

// Collision example:
// Session 1: START TRANSACTION → reads doc A (quantity: 10)
// Session 2: START TRANSACTION → reads doc A (quantity: 10)
// Session 1: UPDATE A SET quantity = 8 → SUCCESS
// Session 2: UPDATE A SET quantity = 5 → WRITE CONFLICT!
// → Session 2 gets WriteConflict error → must retry

// Retry pattern for production:
function runTransaction(maxRetries = 5) {
    for (let i = 0; i < maxRetries; i++) {
        const session = db.getMongo().startSession();
        session.startTransaction({ writeConcern: { w: "majority" } });

        try {
            // ... transaction logic ...
            session.commitTransaction();
            return;  // Success!
        } catch (e) {
            session.abortTransaction();
            if (e.hasOwnProperty("errorLabels") && 
                e.errorLabels.includes("TransientTransactionError")) {
                continue;  // Retry on transient errors
            }
            throw e;  // Non-retriable error
        } finally {
            session.endSession();
        }
    }
    throw new Error("Transaction failed after retries");
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Snapshot isolation** | Understands consistent read view at transaction start time |
| **Cross-shard 2PC** | Knows mongos coordinates 2-phase commit across shards |
| **Retry logic** | Implements TransientTransactionError retry pattern |
| **Limitations** | Knows 60s timeout, 1000 write limit, no DDL inside transactions |

---

> *All 6 questions cover the full breadth of MongoDB — from WiredTiger storage engine to multi-document ACID transactions and sharded cluster architecture.*
