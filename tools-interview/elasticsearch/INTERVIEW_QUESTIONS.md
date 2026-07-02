# 🔎 Elasticsearch — Staff-Level Interview Questions

> *8 questions covering Elasticsearch internals, inverted index, sharding, query DSL, cluster management, and operational excellence — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Inverted Index & Segment Structure](#1-inverted-index--segment-structure)
2. [Sharding, Routing & Rebalancing](#2-sharding-routing--rebalancing)
3. [Query DSL: Filter vs Query Context](#3-query-dsl-filter-vs-query-context)
4. [Aggregations: Metric, Bucket, Pipeline](#4-aggregations-metric-bucket-pipeline)
5. [Cluster Management: Discovery, Master Election](#5-cluster-management-discovery-master-election)
6. [Indexing: Refresh, Flush, Merge](#6-indexing-refresh-flush-merge)
7. [Tuning: Mapping, Analyzers, Field Data](#7-tuning-mapping-analyzers-field-data)
8. [Hot-Warm-Cold Architecture & ILM](#8-hot-warm-cold-architecture--ilm)

---

## 1. Inverted Index & Segment Structure

**Q:** "Explain how Elasticsearch's inverted index works under the hood. How does it handle multi-word full-text search across millions of documents? What's the role of segments, and what happens during a merge?"

**What They're Really Testing:** Whether you understand Lucene's core data structures — inverted index, segment tree, and the immutable segment model.

### Answer

**Inverted Index Structure:**

```
Documents indexed:
  Doc 1: "the quick brown fox jumps"
  Doc 2: "the lazy dog sleeps"
  Doc 3: "the quick dog runs"

Inverted index (simplified):
  term      → doc_freq → postings list (docID, positions)
  ──────      ────────   ─────────────────────────────────
  the        → 3        → [1:0,2:0,3:0]
  quick      → 2        → [1:1,3:1]
  brown      → 1        → [1:2]
  dog        → 2        → [2:1,3:2]
  fox        → 1        → [1:3]
  jumps      → 1        → [1:4]
  lazy       → 1        → [2:1]
  runs       → 1        → [3:3]
  sleeps     → 1        → [2:2]

Query: "quick dog" → AND
  quick: [1:1, 3:1]
  dog:   [2:1, 3:2]
  Intersection: [3] (doc 3 matches both terms)

TF-IDF: term frequency × inverse document frequency
  quick: TF in doc1=1, doc3=1; IDF log(3/2)=0.176 → score = 0.176
  dog:   TF in doc2=1, doc3=1; IDF log(3/2)=0.176 → score = 0.176
  Doc 3 score: 0.176 + 0.176 = 0.352
```

**Segment Structure (Lucence's Immutable Segments):**

```
One ES shard = a Lucene index = collection of segments

Segment (immutable, written once, never modified):
├── .tim  (term dictionary: sorted terms → postings offset)
├── .tip  (term index: prefix-compressed trie for fast term lookup)
├── .pos  (postings file: doc IDs + term positions)
├── .doc  (stored fields: original document data)
├── .nvd  (norms: length normalization data for scoring)
├── .fdx  (field index: for stored field retrieval)
└── .fnm  (field metadata: field names, types, analyzers)

Merge process:
  5 small segments (1GB each) → merge into 1 large segment (5GB)
  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
  │ S1  │ │ S2  │ │ S3  │ │ S4  │ │ S5  │
  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘
     └───────┴───────┴───────┴───────┘
                    │
               ┌────▼────┐
               │  New S  │ (5GB, one segment)
               └─────────┘

  # Merge policy: tiered (default)
  # Merge triggers when: segment count > tiered merge factor
  
  Performance trade-off:
  More segments: faster indexing, slower search
  Fewer segments: slower indexing (merge cost), faster search
```

**Writing to Immutable Segments:**

```
Write request → IndexBuffer (in memory, 1 second refresh interval)
  │
  ├─→ Refresh (every 1s): open new segment from buffer
  │    Buffer becomes a READABLE segment (not yet fsynced)
  │    No fsync → visible to search but NOT durable!
  │
  ├─→ Flush (automatic or manual):
  │    Buffer → segment → fsync to disk
  │    Translog (transaction log) is truncated
  │
  └─→ Merge (background):
       Small segments → big segment
       Delete documents: old segment marked as deleted, new segment without deleted docs
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Inverted index** | Can explain term → postings list mapping and Boolean query intersection |
| **Segment immutability** | Understands segments are written once, never modified — only merged |
| **Refresh vs flush** | Explains refresh makes visible, flush makes durable (fsync) |
| **Merge cost** | Knows merging is I/O intensive but necessary for search performance |

---

## 2. Sharding, Routing & Rebalancing

**Q:** "Your ES cluster has 5 nodes and an index with 20 primary shards. You need to scale to 10 nodes. Walk through the rebalancing process. How does Elasticsearch route documents to shards? What happens to search performance during rebalancing?"

**What They're Really Testing:** Whether you understand Elasticsearch's distributed architecture — shard allocation, routing, and the rebalancing state machine.

### Answer

**Routing Formula:**

```
shard_num = hash(_routing) % num_primary_shards

Default _routing = _id (document ID)
Custom _routing = any field (e.g., user_id for better locality)

GET my-index/_search?routing=user_123
# Search only the shard containing user_123's documents

PUT my-index/_doc/doc-1?routing=group_a
# Force routing by group_a → all group_a docs on same shard

Critical limitation:
  Once index is created, num_primary_shards CANNOT be changed!
  → Routing formula would produce different results
  → You need reindex to change shard count
```

**Shard Allocation & Rebalancing:**

```
5 nodes → 10 nodes: rebalance process

Phase 1: Add nodes to cluster
  Node 6,7,8,9,10 join → discover master node
  Master detects: 20 shards across 5 nodes = 4 shards/node
  Target: 20 shards across 10 nodes = 2 shards/node
  → Rebalance needed!

Phase 2: Master computes allocation plan
  Decision: move 2 shards from each old node to new nodes
  Constraints:
    1. No two replicas of same shard on same node
    2. Each shard movement bounded by cluster.routing.rebalance.enable=...
    3. Throttle: cluster.routing.allocation.node_concurrent_recoveries=2

Phase 3: Shard relocation
  ┌──────────────────────────────────────────────────┐
  │ Node 1: S0,S1,S2,S3 → S0,S1 (move S2,S3 to N7) │
  │ Node 2: S4,S5,S6,S7 → S4,S5 (move S6,S7 to N8) │
  │ ...                                              │
  │ Node 7: (new) ← S2,S3 (receiving)               │
  │ Node 8: (new) ← S6,S7 (receiving)               │
  │ ...                                              │
  └──────────────────────────────────────────────────┘

Phase 4: Rebalancing recovery
  Source node: file copy to destination node
  During copy: source continues serving search
  After copy: destination opens segment readers → serves searches
  Source: removes primary shard → update routing table

Performance during rebalance:
  - Node_concurrent_recoveries: 2 per node (default)
  - Each recovery: network copy of shard data
  - Network bandwidth shared with search traffic
  - P99 latency may increase 2-3× during heavy rebalancing
```

**Throttling Rebalancing Impact:**

```json
// Dynamic settings — apply without restart
PUT _cluster/settings
{
  "transient": {
    "cluster.routing.allocation.node_concurrent_recoveries": 2,
    "cluster.routing.allocation.node_initial_primaries_recoveries": 4,
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.rebalance.enable": "replicas"  // Move replicas before primaries
  }
}

// After rebalance, reset:
PUT _cluster/settings
{
  "transient": {
    "cluster.routing.allocation.node_concurrent_recoveries": null,
    "indices.recovery.max_bytes_per_sec": null
  }
}
```

**Shard Sizing Guidelines:**

```yaml
# Recommended shard sizes:
  - Target: 20-50GB per shard
  - Max: 100GB per shard (beyond that, recovery is too slow)

# Number of shards formula:
  total_shards = (expected_data_size / target_shard_size) × (1 + growth_factor)

# Example: 500GB dataset, 30GB target, 50% growth
  total = (500 / 30) × 1.5 = 25 shards

# Time-based indices (logs):
  One index per day: 30GB daily volume → 1-2 shards per day index
  ILM: rollover at 50GB → creates new index

# Old advice: shard count = node count × 1.5
# Modern advice: let shard SIZE drive count (20-50GB)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Routing formula** | Understands shard_num = hash(routing) % num_shards — can't change primary count |
| **Rebalancing throttles** | Can tune node_concurrent_recoveries and max_bytes_per_sec |
| **Shard sizing** | Recommends 20-50GB per shard, not the old "1.5× nodes" rule |
| **Reindex for resharding** | Knows reindex is the only way to change shard count |

---

## 3. Query DSL: Filter vs Query Context

**Q:** "A search on your e-commerce index returns 5M matching documents but the UI only shows 10 results per page. The query takes 800ms. How do you optimize it? Explain the difference between filter and query context, and how caching works."

**What They're Really Testing:** Whether you understand ES's scoring and caching internals — filter context bypasses scoring and uses bit set caching.

### Answer

**Filter vs Query Context:**

```json
// Query context: scoring matters
GET /products/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "title": "laptop" } }  // Scoring: "how well does this match?"
      ]
    }
  }
}

// Filter context: no scoring, just matching
GET /products/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "title": "laptop" } }
      ],
      "filter": [                           // Filter context!
        { "term": { "status": "active" } }, // Exact match, no scoring
        { "range": { "price": { "gte": 500, "lte": 2000 } } }
      ]
    }
  }
}

// Performance difference:
// Query: score every document (TF-IDF/BM25) → 800ms
// Filter: just check inclusion → 50ms (no scoring overhead!)
// Filter result: cached as bit set → subsequent queries are FREE
```

**Bit Set Caching:**

```
Filter on "status:active" (100M docs, 80M active):
  Bit set: [1,1,0,1,1,1,0,1,1,0,...] (80M bits = 10MB)
  
  Next query: filter + anything
  Step 1: load bit set from cache (0 I/O, 10MB in memory)
  Step 2: iterate matches from bit set
  Step 3: score only matched docs (reduced scoring work)

When is bit set invalidated?
  - NEVER for filters on index-based data (status, date ranges, etc.)
  - IMMEDIATELY for filters on updated fields (but ES indices are append-only!)
  - Practically: filters are cached until segment merge

Caching hierarchy:
  Node-level cache (shared across all indices on the node)
  Each filter result = (segment, filter_query) → bit set
  Cache size: indices.queries.cache.size (default: 10%)
```

**Optimized Query for 800ms → 50ms:**

```json
// Before: 800ms
GET /products/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "title": "laptop" } },
        { "match": { "description": "laptop" } }
      ]
    }
  }
}

// After: 50ms
GET /products/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "title": "laptop" } }
      ],
      "filter": [
        { "term": { "status": "active" } },
        { "range": { "price": { "gte": 500, "lte": 2000 } } },
        { "term": { "category": "electronics" } }
      ]
    }
  }
}
```

**Performance Optimization Techniques:**

```yaml
# 1. Use filter for everything that doesn't need scoring
#    - status, dates, range, geo, terms → ALL filter context

# 2. Use constant_score for terms that need no TF-IDF
GET /products/_search
{
  "query": {
    "constant_score": {
      "filter": { "term": { "brand": "apple" } },
      "boost": 1.0
    }
  }
}
# No TF-IDF computed! Just check inclusion → score = boost

# 3. Use search_after instead of from/size for deep pagination
GET /products/_search
{
  "size": 10,
  "search_after": [12345678, "doc_999999"],
  "sort": [
    { "timestamp": "asc" },
    { "_id": "asc" }
  ]
}
# from+size: ES loads ALL matching docs, sorts, then SLICES → O(N) per page!
# search_after: only loads 10 docs after the cursor → O(1) per page!

# 4. Use _source filtering (don't send entire document)
GET /products/_search
{
  "_source": ["title", "price", "image_url"],
  "query": { ... }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Filter vs query** | Understands filter misses scoring, uses bit set caching |
| **Bit set mechanics** | Knows bit sets are per-segment, cached in node-level cache |
| **Deep pagination** | Can explain why from+size is O(N) and search_after is O(1) |
| **Source filtering** | Optimizes network transfer with _source reduction |

---

## 4. Aggregations: Metric, Bucket, Pipeline

**Q:** "You have 10M e-commerce orders. Build a dashboard showing: revenue by category (drill-down to subcategory), top-selling products, and month-over-month growth. How do aggregations work internally? What's the field data memory cost?"

**What They're Really Testing:** Whether you understand ES aggregation internals — global ordinals, field data, and the memory impact of high-cardinality fields.

### Answer

**Aggregation Types:**

```json
// Metric: compute values
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "total_revenue": { "sum": { "field": "amount" } },
    "avg_order_value": { "avg": { "field": "amount" } },
    "order_count": { "value_count": { "field": "order_id" } },
    "price_stats": {
      "stats": { "field": "amount" }
      // Returns: count, min, max, avg, sum
    },
    "cardinality": {
      "cardinality": {
        "field": "customer_id",
        "precision_threshold": 40000
        // HLL algorithm: accurate up to 40K unique values
      }
    }
  }
}

// Bucket: group by values
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "by_category": {
      "terms": {
        "field": "category",
        "size": 10,
        "order": { "revenue": "desc" }
      },
      "aggs": {
        "revenue": { "sum": { "field": "amount" } },
        "by_subcategory": {
          "terms": { "field": "subcategory" },
          "aggs": {
            "top_products": {
              "top_hits": {
                "size": 3,
                "_source": ["product_name", "amount"]
              }
            }
          }
        }
      }
    }
  }
}
```

**Global Ordinals (Field Data Memory):**

```
How aggregations work internally:
  1. Load field values for ALL matching documents into memory
  2. Build global ordinals: sorted unique values, each with an ordinal
  
  Example: field "category" with values [electronics, fashion, home, ...]
  
  Global ordinals:
    ordinal 0: electronics
    ordinal 1: fashion
    ordinal 2: home
    ...
  
  Each document stores: ordinal (4 bytes) instead of string (variable)
  Document 1: ordinal 0 → "electronics"
  Document 2: ordinal 1 → "fashion"
  
  Memory:
  - Strings: 10 unique categories × 15 bytes avg = 150 bytes
  - Ordinals: 10M docs × 4 bytes = 40MB
  - Total: ~40MB for terms aggregation on category

  HIGH CARDINALITY fields (like "product_name"):
  - 5M unique product names × 30 bytes = 150MB
  - 10M docs × 4 bytes = 40MB
  - Total: ~190MB for ONE aggregation!
  - Solution: use "execution_hint": "map" for high cardinality
```

**Pipeline Aggregations:**

```json
// Month-over-month growth (bucket_script)
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "monthly": {
      "date_histogram": {
        "field": "order_date",
        "calendar_interval": "month",
        "format": "yyyy-MM"
      },
      "aggs": {
        "revenue": { "sum": { "field": "amount" } }
      }
    },
    "mom_growth": {
      "bucket_script": {
        "buckets_path": {
          "prev": "monthly['last-1'].revenue",
          "current": "monthly['last'].revenue"
        },
        "script": "(params.current - params.prev) / params.prev * 100"
      }
    }
  }
}
```

**Aggregation Memory Budget:**

```yaml
# Aggregation memory: part of the circuit breaker

indices.breaker.request.limit: 60%    # Max heap for single request
indices.breaker.total.limit: 70%      # Max heap for all aggregations

# If exceeded: CircuitBreakingException (request aborted)

Budget calculation:
  1 terms aggregation on 10M docs × 4 bytes = 40MB
  1 date_histogram on 10M docs × 8 bytes = 80MB
  1 sum metric = ~negligible
  Total: ~120MB per coordinated node (for 1 request)

# Optimization:
# - Use filter aggregation to pre-reduce document set
# - Use sampling for approximate results
# - Increase shard count for parallelization
# - Use execution_hint = "map" for high cardinality
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Global ordinals** | Understands how field values are mapped to ordinals for aggregation |
| **Memory cost** | Can estimate memory for terms aggregation: ordinals × doc count |
| **Cardinality precision** | Knows precision_threshold and HLL accuracy |
| **Pipeline aggs** | Can chain bucket scripts for MoM/WoW calculations |

---

## 5. Cluster Management: Discovery, Master Election

**Q:** "Your ES cluster has 10 nodes. Two nodes experience a network partition. One side has 6 nodes, the other has 4. What happens? How does Elasticsearch's Zen Discovery handle master election? How does the 7.x cluster coordination layer differ?"

**What They're Really Testing:** Whether you understand ES's consensus mechanism — Zen Discovery vs the modern cluster coordination layer (based on Raft-like protocol).

### Answer

**Network Partition Behavior:**

```
Cluster state before partition:
  Master: Node A (voting)
  Nodes: A, B, C, D, E, F, G, H, I, J (10 total)
  Voting members: all 10 (or configured minimum_master_nodes)

Network partition:
  Side 1: A, B, C, D, E, F (6 nodes)
  Side 2: G, H, I, J (4 nodes)

Outcome:
  Side 1: 6/10 ≥ 5 (majority) → Cluster stays HEALTHY
    New leader elected (if old master was on side 2)
    Continues accepting writes

  Side 2: 4/10 < 5 (no majority) → Cluster GOES DOWN
    No master election possible
    All indices RED (unassigned shards)
    Rejects all writes (will retry when reconnected)

Prevention: discovery.zen.minimum_master_nodes = (N/2) + 1
  With 10 nodes: minimum_master_nodes = 6
  Prevents split-brain: a partition of <6 can't elect a master
```

**Zen Discovery (Pre-7.x):**

```yaml
# Pre-7.x: Zen Discovery
# Challenges:
#   - Static minimum_master_nodes (must be updated when adding/removing nodes)
#   - Gossip-based membership (eventual consistency)
#   - Split-brain possible if minimum_master_nodes not configured correctly

discovery.zen.ping.unicast.hosts: ["node1", "node2", "node3"]
discovery.zen.minimum_master_nodes: 6

# Problems:
# 1. Forget to update minimum_master_nodes after scaling? → split-brain
# 2. 2-node cluster: minimum_master_nodes = 2 → both must be up
# 3. Rolling restart: need to temporarily reduce minimum_master_nodes
```

**Cluster Coordination Layer (7.x+):**

```yaml
# 7.x+: Cluster coordination based on Raft-like consensus
# Key improvements:
#   1. Dynamic voting configurations (no manual minimum_master_nodes!)
#   2. Voting-only nodes (separate data and voting roles)
#   3. Cluster bootstrapping for new clusters

# Voting configuration:
#   Initial set: 3 dedicated master-eligible nodes
#   When adding node: coordination layer adjusts voting config
#   No need to manually update minimum_master_nodes!

# Recommended node roles:
  master:
    node.roles: [master, voting_only]  # Voting only, no data
    # 3 nodes for small clusters, 5 for large clusters

  data:
    node.roles: [data, ingest]  # No master eligibility
    # Scale horizontally

  coordinating:
    node.roles: []  # No master, no data, no ingest
    # For high-throughput search/fronting

Configuration:
  discovery.seed_hosts: ["master1", "master2", "master3"]
  cluster.initial_master_nodes: ["master1", "master2", "master3"]
  # Only used for cluster BOOTSTRAPPING (first time)
```

**Master Election (Raft-like):**

```
1. All master-eligible nodes participate in election
2. Each node votes for the node with the highest cluster state version
3. Leader = node that gets votes from majority of voting nodes
4. Leader maintains: heartbeat to followers
5. If leader loses heartbeat: new election triggered

Election trigger conditions:
  - Node starts and doesn't know of a master
  - Node loses heartbeat from current master
  - Current master steps down (cluster state update failure)

Dedicated master nodes (recommended):
  3 dedicated masters for up to 1,000 nodes
  5 dedicated masters for 1,000+ nodes
  7 dedicated masters for very large clusters

Performance impact of master duties:
  - Master maintains cluster state (indices, mappings, shard allocation)
  - Cluster state update: confirm from majority within 30s
  - Master does NOT handle data requests (routing only)
  - Dedicated masters prevent GC pauses from affecting cluster stability
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Split-brain prevention** | Explains minimum_master_nodes formula and why partitions happen |
| **Raft-like coordination** | Understands 7.x+ dynamic voting vs static Zen Discovery |
| **Dedicated masters** | Recommends 3 dedicated master-eligible nodes |
| **Bootstrapping** | Knows cluster.initial_master_nodes is for first-time setup only |

---

## 6. Indexing: Refresh, Flush, Merge

**Q:** "Your ES cluster ingests 50K documents/second. Indexing latency is 200ms but you need 50ms. Search latency is also high during indexing bursts. Walk through the indexing pipeline — refresh interval, translog, merge policy — and optimize for this throughput."

**What They're Really Testing:** Whether you understand ES's near-real-time indexing pipeline and the trade-offs between indexing throughput, search latency, and durability.

### Answer

**Indexing Pipeline:**

```
Client → Node → Primary Shard → Replica Shards

Primary shard path:
  1. Receive document → apply mapping/analysis
  2. Write to translog (durable, fsynced)
  3. Write to in-memory buffer (Lucene's IndexWriter buffer)
  4. Return success to client
  5. Refresh (default 1s): buffer → new segment (visible to search)
  6. Translog commit (flush): buffer → segment → fsynced
```

**Translog Mechanics:**

```
Translog = write-ahead log (WAL) for durability

Write flow:
  1. Document received
  2. Translog: append (fsync every index.translog.sync_interval = 5s)
  3. In-memory buffer: append
  4. Response to client: INDEXED (but not yet searchable!)

Recovery:
  Node crash → on restart:
    1. Recover from translog (replay all operations)
    2. Translog replayed → in-memory buffer → segments
    3. Cluster health: green (no data loss!)

Translog sizing:
  index.translog.flush_threshold_size: 512mb  (default)
  # When translog reaches 512MB → flush is triggered
  
  index.translog.durability: request (default)
    # fsync on every request → slower but no data loss
    # async: fsync every sync_interval → faster, lose up to 5s
```

**Refresh Interval Tuning:**

```yaml
# Default: refresh_interval = 1s
# Result: documents visible within ~1s of indexing

# For high-ingestion scenarios (logs, metrics):
PUT my-index/_settings
{
  "index": {
    "refresh_interval": "30s"  // Reduce refresh frequency
  }
}
# → Fewer, larger segments (less I/O)
# → Indexing throughput: +200-300%
# → Search visibility: 30s lag (acceptable for logs!)

# For bulk indexing (initial load):
PUT my-index/_settings
{
  "index": {
    "refresh_interval": -1,  // DISABLE refresh
    "number_of_replicas": 0  // No replica during bulk load
  }
}
# Bulk complete → restore:
PUT my-index/_settings
{
  "index": {
    "refresh_interval": "30s",
    "number_of_replicas": 2
  }
}
```

**Merge Policy Tuning:**

```yaml
# Default: TieredMergePolicy
# Segments per tier: index.merge.policy.segments_per_tier = 10

# Problem with high writes:
#   Too many small segments → high merge overhead
#   Merge churn → I/O contention with search

# Solution: increase segments_per_tier
PUT my-index/_settings
{
  "index": {
    "merge.policy.segments_per_tier": 20,
    "merge.scheduler.max_thread_count": 1  // Single thread for merges
  }
}

# Alternative: LogByteSizeMergePolicy
#   Merge based on total byte size of segment
#   More predictable than tiered, but slower merge pacing

# Force merge for read-only indices (e.g., completed time-series index):
POST my-index-2024-01-01/_forcemerge?max_num_segments=1
# → Single segment per shard → optimal search speed
# → But: CANNOT be done on write-active indices (blocks writes!)
```

**50K Docs/Second Optimization Summary:**

```yaml
Before:
  refresh_interval: 1s
  number_of_replicas: 2
  translog.durability: request
  merge policy: default (segments_per_tier=10)
  → Indexing: 200ms latency, search: high during bursts
  
Optimized:
  refresh_interval: 30s
  number_of_replicas: 0 (during bulk) → restore to 2 later
  translog.durability: async (lose ≤5s on crash)
  merge policy: segments_per_tier=20, max_thread_count=1
  index_buffer_size: 20% (up from 10%)
  → Indexing: 40ms latency, search: stable
  
  Additional:
  - Use bulk API (batch 500-5000 docs)
  - Use multiple indexing workers (parallelism per node)
  - Pre-allocate shards (20-50 shards for parallel ingestion)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Refresh vs flush** | Understands refresh makes searchable, flush makes durable |
| **Translog trade-off** | Can explain durability vs throughput with translog.sync_interval |
| **Merge throttling** | Adjusts merge policy for write-intensive workloads |
| **Bulk optimization** | Disables replicas and refresh during bulk loads |

---

## 7. Tuning: Mapping, Analyzers, Field Data

**Q:** "A text field in your index is used for both exact match filtering and full-text search. Currently it's mapped as 'text' and you're using a 'keyword' subfield. The filter performance is poor. Diagnose and optimize the mapping. What analyzers should you use?"

**What They're Really Testing:** Whether you understand ES mappings at a deep level — multi-fields, analyzer selection, and the trade-offs of text vs keyword.

### Answer

**Multi-Field Mapping:**

```json
// Current (problematic) mapping:
PUT my-index
{
  "mappings": {
    "properties": {
      "product_name": {
        "type": "text",              // Full-text search (analyzed)
        "fields": {
          "keyword": {               // Exact match (not analyzed)
            "type": "keyword"
          }
        }
      }
    }
  }
}

// Problem:
// product_name: analyzed → "laptop bag" → ["laptop", "bag"]
// product_name.keyword: not analyzed → "laptop bag" (exact)
// Filter on product_name.keyword: works, but stores BOTH fields
// → Double storage, double indexing cost!

// Optimized mapping for your use case:
PUT my-index
{
  "mappings": {
    "properties": {
      "product_name": {
        "type": "text",
        "analyzer": "custom_analyzer",  // Custom analyzer instead of standard
        "fields": {
          "exact": {
            "type": "keyword",
            "ignore_above": 256  // Don't index keywords longer than this
          },
          "ngram": {
            "type": "text",
            "analyzer": "ngram_analyzer"  // For partial/autocomplete matches
          }
        }
      }
    }
  }
}
```

**Analyzer Selection:**

```yaml
# Standard analyzer (default):
  tokenizer: standard
  filters: lowercase, stop (disabled by default)
  "Laptop Bag 2024!" → ["laptop", "bag", "2024"]

# Custom analyzer for e-commerce:
PUT _component_template/my_analyzer
{
  "template": {
    "settings": {
      "analysis": {
        "analyzer": {
          "ecommerce_analyzer": {
            "type": "custom",
            "tokenizer": "standard",
            "filter": [
              "lowercase",
              "asciifolding",          // café → cafe
              "trim",                   // Remove whitespace
              "stop",                   // Remove English stop words
              "snowball"                // Stemming: running → run
            ]
          }
        }
      }
    }
  }
}

# For search-time: use different analyzer than index-time
# Index: ecommerce_analyzer (stemming, stop words)
# Search: search_analyzer (less aggressive)
PUT my-index/_settings
{
  "analysis": {
    "analyzer": {
      "search_analyzer": {
        "type": "custom",
        "tokenizer": "standard",
        "filter": ["lowercase", "asciifolding"]
      }
    }
  }
}
// No stemming at search time → matches both "run" and "running"
```

**Field Data & Doc Values:**

```yaml
# Doc values: columnar storage for sorting/aggregations (default for most types)
# Field data: in-memory data structure (text fields default)

# text fields: fielddata=false by default!
# Enabling fielddata on text fields is EXPENSIVE:
PUT my-index/_mapping
{
  "properties": {
    "description": {
      "type": "text",
      "fielddata": true  // WARNING: memory heavy!
    }
  }
}

# Instead: use keyword subfield for text aggregations:
{
  "description": {
    "type": "text",
    "fields": {
      "aggregatable": {
        "type": "keyword",
        "doc_values": true  // Off-heap, disk-based, efficient
      }
    }
  }
}

# Disable doc_values for fields you don't aggregate on:
{
  "session_id": {
    "type": "keyword",
    "doc_values": false  // Save disk space (if not used in sorting/aggs)
  }
}
```

**Mapping Optimization Rules:**

```yaml
# 1. Disable _source if you don't need original document
PUT my-index
{
  "mappings": {
    "_source": { "enabled": false }
  }
}
# → Save 30-50% disk space, CANNOT perform partial updates

# 2. Use runtime fields for expensive computations AT QUERY TIME
# (instead of storing computed fields)
GET my-index/_search
{
  "runtime_mappings": {
    "price_with_tax": {
      "type": "double",
      "script": {
        "source": "emit(doc['price'].value * 1.1)"
      }
    }
  }
}

# 3. Disable norms on fields that don't need scoring
{
  "product_name": {
    "type": "text",
    "norms": false  // Don't store length normalization → save 10-15% disk
  }
}

# 4. Use index: false for fields that only need _source retrieval
{
  "internal_note": {
    "type": "text",
    "index": false  // Not searchable, but retrievable from _source
  }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-field mapping** | Understands text + keyword subfields for search + filter use cases |
| **Analyzer selection** | Can customize analyzers for language, stemming, and specific tokenization |
| **Fielddata vs doc_values** | Knows fielddata is heap memory, doc_values is off-heap and more efficient |
| **Mapping savings** | Can disable norms, _source, and index on appropriate fields |

---

## 8. Hot-Warm-Cold Architecture & ILM

**Q:** "Design an Elasticsearch architecture for time-series metrics data: 5TB/day ingestion, 90-day retention, with 500ms query latency SLA on last 7 days and zip-then-delete after 90 days. How does Index Lifecycle Management (ILM) work?"

**What They're Really Testing:** Whether you understand ES's tiered storage strategy — hot/warm/cold nodes with ILM policies, and how to architect for time-series data at scale.

### Answer

**Node Tier Design:**

```yaml
# Hot nodes (SSD, high CPU)
node.roles: [data, ingest]
node.attr.data: hot
# - Fast indexing: NVMe RAID0, 32-64 cores
# - High I/O: 100K+ IOPS per node
# - 3 replicas for high availability

# Warm nodes (SSD, standard)
node.roles: [data]
node.attr.data: warm
# - Large capacity: 8-16TB per node (SATA SSD)
# - Lower I/O: 10K IOPS
# - 2 replicas (lower reliability requirement)

# Cold nodes (HDD, storage-optimized)
node.roles: [data]
node.attr.data: cold
# - Massive capacity: 50-100TB per node (HDD)
# - Lower query latency (acceptable for archival)
# - 1 replica or none (can reindex from source)
```

**ILM Policy — 90-Day Retention:**

```json
PUT _ilm/policy/metrics_90day_policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50gb",      // Rollover at 50GB
            "max_age": "1d"          // Or after 1 day
          },
          "set_priority": {
            "priority": 100          // Hot: highest recovery priority
          }
        }
      },
      "warm": {
        "min_age": "7d",             // Move to warm after 7 days
        "actions": {
          "shrink": {
            "number_of_shards": 2    // Shrink from 5 → 2 shards
          },
          "forcemerge": {
            "max_num_segments": 1    // Single segment for best compression
          },
          "allocate": {
            "number_of_replicas": 2,
            "require": {
              "data": "warm"         // Pin to warm nodes
            }
          },
          "set_priority": {
            "priority": 50           // Medium priority
          }
        }
      },
      "cold": {
        "min_age": "30d",            // Move to cold after 30 days
        "actions": {
          "allocate": {
            "number_of_replicas": 1,
            "require": {
              "data": "cold"
            }
          },
          "set_priority": {
            "priority": 0            // Lowest priority
          }
        }
      },
      "delete": {
        "min_age": "90d",            // Delete after 90 days
        "actions": {
          "delete": {}               // Permanently delete index
        }
      }
    }
  }
}
```

**Index Template with ILM:**

```json
PUT _index_template/metrics_template
{
  "index_patterns": ["metrics-*"],
  "template": {
    "settings": {
      "number_of_shards": 5,
      "number_of_replicas": 3,
      "routing.allocation.require.data": "hot",
      "index.lifecycle.name": "metrics_90day_policy",
      "index.lifecycle.rollover_alias": "metrics"
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        },
        "metric_name": {
          "type": "keyword"
        },
        "value": {
          "type": "double"
        }
      }
    }
  }
}

// Create first write index:
PUT metrics-000001
{
  "aliases": {
    "metrics": {
      "is_write_index": true
    }
  }
}
```

**500ms Query SLA for Last 7 Days:**

```yaml
# Challenge: hot-only for last 7 days keeps data in fast SSDs
# 5TB/day × 7 days = 35TB hot storage

# Architecture:
# 10 hot nodes: 4TB NVMe each = 40TB total
# 20 warm nodes: 16TB SATA SSD each = 320TB total
# 10 cold nodes: 100TB HDD each = 1000TB total

# Hot node sizing:
# 5TB/day ÷ 10 nodes = 500GB/day/node
# 500GB/day × 3x replica factor = 1.5TB/node
# 7 days × 1.5TB = 10.5TB/node (not feasible in 4TB!)
# → Need more hot nodes OR compress data

# Solution: rollover at 50GB (not 50TB!)
# Each rollover creates new index → ILM moves OLD indices to warm
# Hot only holds: current write index + 1 day = ~100GB/node
# Warm holds 2-30 day old data: 28 days × 5TB ÷ 20 nodes × 2 replicas = 14TB/node

# Search routing for 7-day query:
GET metrics-2024-01-*/_search
# Or use date math:
GET metrics-<2024-01-01-2024-01-07>/_search
```

**Shard Shrinking for Warm/Cold:**

```yaml
# Hot: 5 shards (for fast indexing parallelism)
# Warm: 2 shards (shrink: 5 shards → 2 shards)
# Cold: 1 shard (shrink: 2 shards → 1 shard)

# Benefits of shrinking:
# 1. Less segment metadata (fewer files open)
# 2. Better compression (larger files, fewer overhead)
# 3. Lower memory for file system cache
# 4. Enough shards for warm queries (fewer users query warm data)

Rollover → 5 shards (hot) → ILM shrink → 2 shards (warm) → ILM → 1 shard (cold)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Tiered architecture** | Designs hot/warm/cold with appropriate hardware per tier |
| **ILM rollover** | Understands rollover triggers, shrink, forcemerge, allocation |
| **Search SLA** | Ensures hot holds recent data, warm handles 7-day queries at 500ms |
| **Shard shrinking** | Knows shrinking reduces shard count for lower storage overhead |

---

> *All 8 questions cover the full breadth of Elasticsearch — from inverted index internals to tiered architectures for time-series data at scale.*
