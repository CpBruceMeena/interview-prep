# 🔎 Elasticsearch — Staff-Level Interview Questions

> *8 questions covering Elasticsearch internals, inverted index, sharding, query DSL, cluster management, and operations. Each answer leads with a 30-second version, then the mechanism, then failure modes and what the interviewer probes next.*

!!! info "Version baseline (October 2026)"
    - **Elasticsearch 9.x** is current (9.0 GA April 2025 on **Lucene 10**, with minor releases since; 8.19 is the last 8.x minor). Things interviewers now assume:
        - Mapping types are gone (removed in 8.0).
        - **Security is on by default since 8.0** (TLS + auth auto-configured).
        - `transient` cluster settings are deprecated: use `persistent`.
        - Data tiers (`data_hot`/`warm`/`cold`/`frozen`) and **searchable snapshots** replace hand-rolled node attributes.
        - **ES|QL** is GA (piped query language, `LOOKUP JOIN` GA in 9.1).
        - **logsdb** index mode (synthetic `_source`, index sorting, much smaller on disk) is the default for `logs-*-*` data streams on new 9.0 deployments.
        - `dense_vector` fields default to HNSW with quantization. **BBQ** (better binary quantization) has been the default for ≥384 dimensions since 9.1.
    - **Licensing:** Elastic moved from Apache 2.0 to SSPL / Elastic License 2.0 in 2021 (7.11). In 2024 it **added AGPLv3** as a third option, so Elasticsearch is open source again under OSI terms.
    - **OpenSearch** forked from Elasticsearch 7.10.2 (Apache 2.0) in 2021. Since September 2024 it's governed by the **OpenSearch Software Foundation** (Linux Foundation). **OpenSearch 3.x** (3.0 in May 2025) is also on Lucene 10. APIs diverged after 7.10: OpenSearch uses ISM instead of ILM, and has its own security plugin, k-NN plugin and PPL/SQL. Most answers below apply to both at the Lucene level, but the config names differ.

---

## Table of Contents

1. [Inverted Index & Segment Structure](#1-inverted-index-segment-structure)
2. [Sharding, Routing & Rebalancing](#2-sharding-routing-rebalancing)
3. [Query DSL: Filter vs Query Context](#3-query-dsl-filter-vs-query-context)
4. [Aggregations: Metric, Bucket, Pipeline](#4-aggregations-metric-bucket-pipeline)
5. [Cluster Management: Discovery, Master Election](#5-cluster-management-discovery-master-election)
6. [Indexing: Refresh, Flush, Merge](#6-indexing-refresh-flush-merge)
7. [Tuning: Mapping, Analyzers, Field Data](#7-tuning-mapping-analyzers-field-data)
8. [Hot-Warm-Cold Architecture & ILM](#8-hot-warm-cold-architecture-ilm)

---

## 1. Inverted Index & Segment Structure

**Q:** "Explain how Elasticsearch's inverted index works under the hood. How does it handle multi-word full-text search across millions of documents? What's the role of segments, and what happens during a merge?"

**What They're Really Testing:** Whether you understand Lucene's core data structures (term dictionary, postings, doc values, immutable segments) and how scoring and merging follow from them.

!!! tip "30-second answer"
    Each shard is a Lucene index made of **immutable segments**. A segment maps every term to a **postings list** (sorted doc IDs, plus frequencies and positions), found through a compact term index (an FST). A multi-term query walks the postings lists in parallel. AND intersects them, OR unions them, and **BM25** scores the hits. Algorithms like block-max WAND skip blocks that can't make the top-k, so Lucene rarely scores every match. Because segments never change, deletes are just bits in a live-docs bitmap and updates are delete + reinsert. Background **merges** combine small segments into larger ones and physically drop the deleted documents. Merging costs I/O and CPU but keeps search fast.

### Answer

**Inverted index:**

```
Documents:
  Doc 1: "the quick brown fox jumps"
  Doc 2: "the lazy dog sleeps"
  Doc 3: "the quick dog runs"

Term dictionary → postings (docID:position)
  the    → [1:0, 2:0, 3:0]
  quick  → [1:1, 3:1]
  brown  → [1:2]
  dog    → [2:2, 3:2]
  fox    → [1:3]
  jumps  → [1:4]
  lazy   → [2:1]
  runs   → [3:3]
  sleeps → [2:3]

Query "quick dog" (operator AND): intersect [1,3] ∩ [2,3] → doc 3
Query "quick dog" (default OR):   union → docs 1, 2, 3, ranked by score
Phrase "quick dog": doc 3 only if positions are adjacent (1 then 2). Positions make phrases possible.
```

**Scoring is BM25** (the default since ES 5.0, not classic TF-IDF):

- **IDF:** rare terms weigh more.
- **Term frequency with saturation (`k1` = 1.2):** the 10th occurrence adds far less than the 2nd.
- **Length normalization (`b` = 0.75):** a match in a short field beats one in a long field. It uses the per-field **norms**.
- Statistics are **per shard** by default. This explains "different scores on different shards" with small indexes. `search_type=dfs_query_then_fetch` computes global statistics at extra cost.

**Segment files (Lucene):**

```
One ES shard = one Lucene index = N segments + a commit point

Segment (written once, never modified):
├── .tim / .tip   term dictionary + term index (FST): term → postings pointer
├── .doc          postings: doc IDs + term frequencies
├── .pos / .pay   positions (+ offsets/payloads): phrase queries, highlighting
├── .nvd / .nvm   norms (field length, used by BM25)
├── .dvd / .dvm   doc values: columnar per-field values for sorting/aggregations
├── .fdt / .fdx   stored fields (_source) + their index
├── .kdd / .kdi   BKD trees for numeric, date, geo and range queries (points)
├── .vec / .vex   vectors + HNSW graph (dense_vector)
├── .fnm          field infos
└── .liv          live-docs bitmap (which docs are deleted). Written per commit, not part of the immutable core.
```

**Write path to segments:**

```
Index request → in-memory indexing buffer (+ translog append)
  │
  ├─ Refresh (default every 1 s, on shards that have seen a search recently):
  │    buffer → new segment written to the OS page cache and opened for search.
  │    Searchable now, but NOT fsynced. The translog provides durability meanwhile.
  │
  ├─ Flush (= Lucene commit): fsync all segments, write a commit point,
  │    start a new translog generation (older translog can be dropped).
  │
  └─ Merge (background, TieredMergePolicy):
       picks similar-sized segments → writes one new segment without deleted docs
       → switches readers to it → old segments deleted.
       Segments stop being merged at index.merge.policy.max_merged_segment (5 GB).
```

**Trade-off:** more segments means cheaper writes but slower search (each query visits every segment), more open files and more heap for segment metadata. Merging trades I/O now for faster search later.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Inverted index** | Term → postings, intersection/union, positions for phrases |
| **Scoring** | BM25 (saturation + length normalization), per-shard statistics |
| **Segment immutability** | Deletes via live-docs bitmap, updates = delete + add, merges reclaim space |
| **Refresh vs flush** | Refresh = visible (no fsync). Flush = Lucene commit (fsync). Translog covers the gap. |
| **Other structures** | Doc values (columnar) for aggregations, BKD trees for numbers and geo, HNSW for vectors |

**What they probe next:**

- "How does vector search fit in?" `dense_vector` fields are indexed as an **HNSW graph** per segment, and kNN search walks each segment's graph. Quantization (int8, int4, **BBQ**, the default for ≥384 dims since 9.1) cuts memory several-fold, and rescoring with the full vectors recovers accuracy. Many segments means many graphs, so merges matter even more here.
- "Hybrid search?" BM25 + kNN combined with **RRF** (reciprocal rank fusion) through the `retriever` API.
- "Why are deleted docs still using disk?" They stay until the segments holding them are merged.

---

## 2. Sharding, Routing & Rebalancing

**Q:** "Your ES cluster has 5 nodes and an index with 20 primary shards. You need to scale to 10 nodes. Walk through the rebalancing process. How does Elasticsearch route documents to shards? What happens to search performance during rebalancing?"

**What They're Really Testing:** Whether you understand routing, how the master's allocator decides shard placement, how peer recovery copies data, and the right levers to limit impact.

!!! tip "30-second answer"
    A document goes to shard `murmur3(_routing) mod num_routing_shards / routing_factor`. `_routing` defaults to `_id`, so primary count is fixed at creation. You can only change it with the **split** (to multiples) or **shrink** (to factors) APIs, or a reindex. When nodes join, the elected master's **desired-balance allocator** computes a target layout, weighing shard count, disk usage and indexing load. It then relocates shards a few at a time through **peer recovery**: copy segment files, then replay recent operations. The source keeps serving until hand-off. Impact is limited by concurrent recoveries and `indices.recovery.max_bytes_per_sec`. Expect extra disk and network I/O and some latency increase while it runs.

### Answer

**Routing:**

```
shard_num = (murmur3(_routing) % num_routing_shards) / routing_factor
  routing_factor = num_routing_shards / number_of_shards
  num_routing_shards defaults to a value that allows later splits (index.number_of_routing_shards)

Default _routing = _id
Custom routing keeps related docs together (e.g. per tenant):
  PUT my-index/_doc/doc-1?routing=tenant_a
  GET my-index/_search?routing=tenant_a      ← hits one shard instead of all
Risk: a big tenant creates a hot shard. index.routing_partition_size spreads
one routing value over a subset of shards.
```

**Changing primary count:** `_split` (e.g. 20 → 40, a multiple) and `_shrink` (e.g. 20 → 5, a factor) work by hard-linking segment files and then rewriting them, which is much faster than reindexing. The index must be made read-only first. For time-series data you rarely need either: change the shard count in the template and **roll over**.

**Rebalancing 5 → 10 nodes (20 primaries, 1 replica = 40 shard copies):**

```
1. New nodes join through discovery (discovery.seed_hosts) and the elected master adds them
   to the cluster state.
2. The desired-balance allocator (8.6+) computes a target: roughly 4 copies per node,
   weighted by shard count, disk usage and write load. It respects allocation deciders:
     - never two copies of the same shard on one node
     - disk watermarks (low 85%, high 90%, flood-stage 95% by default)
     - awareness (zones/racks), filters, data tiers
3. Relocations start, bounded by:
     cluster.routing.allocation.node_concurrent_recoveries (default 2 per node)
     cluster.routing.allocation.cluster_concurrent_rebalance (default 2 cluster-wide)
4. Peer recovery for each moved copy:
     a. copy segment files from the source (throttled by indices.recovery.max_bytes_per_sec)
     b. replay operations indexed during the copy (from Lucene soft-deletes history,
        protected by retention leases)
     c. the new copy is marked started; the old copy is removed.
        For a primary, there's a hand-off so indexing continues without a gap.
5. The source copy serves reads and writes throughout. Search adapts automatically
   (adaptive replica selection prefers less-loaded copies).
```

**Controlling the impact:**

```json
PUT _cluster/settings
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "100mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 2,
    "cluster.routing.allocation.cluster_concurrent_rebalance": 2
  }
}
```

- `indices.recovery.max_bytes_per_sec` default depends on node type and size in 8.x+ (40 MB/s on many nodes, higher on dedicated data tiers). Raise it if the network and disks have headroom, so the move finishes sooner.
- `cluster.routing.rebalance.enable` (`all` | `primaries` | `replicas` | `none`) controls **which** shard types may rebalance. It doesn't set an order. Setting it to `none` during a maintenance window is common.
- Check progress with `GET _cat/recovery?active_only`, `GET _cluster/health`, and `GET _cluster/allocation/explain` for a shard that won't move.

**Shard sizing (current Elastic guidance):**

- Aim for **10-50 GB per shard** and under ~200M documents per shard.
- Too many small shards waste heap (mappings and segment metadata per shard) and cluster-state work. Too few huge shards make recovery and relocation slow and cap parallelism.
- For time-series data, use **data streams with rollover on `max_primary_shard_size: 50gb`**, not one index per day. That keeps shard size steady as volume changes.
- The old "20 shards per GB of heap" rule was replaced (8.3+) by guidance based on fields per shard. Check the heap estimate via `GET _nodes/stats`.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Routing formula** | Routing by `_id`, custom routing and its hot-shard risk |
| **Changing shard count** | Split/shrink (multiples/factors) vs reindex vs rollover |
| **Allocation** | Master's allocator + deciders (watermarks, awareness, tiers), concurrency limits |
| **Recovery mechanics** | File copy + ops replay via retention leases. Source serves throughout. |
| **Shard sizing** | 10-50 GB, size-based rollover, not "1 index per day" |

**What they probe next:** "A shard stays unassigned. How do you debug it?" `_cluster/allocation/explain`, usually disk watermarks, awareness constraints or a missing tier. "Why does one node get all the writes?" Hot routing value, or a write index whose primaries all landed on one node. Check `index.routing.allocation.total_shards_per_node`.

---

## 3. Query DSL: Filter vs Query Context

**Q:** "A search on your e-commerce index returns 5M matching documents but the UI only shows 10 results per page. The query takes 800ms. How do you optimize it? Explain the difference between filter and query context, and how caching works."

**What They're Really Testing:** Whether you know where query time goes (matching, scoring, counting, fetching), what filter context and the caches really do, and how to diagnose with the Profile API.

!!! tip "30-second answer"
    Clauses in **query context** (`must`, `should`) score. Clauses in **filter context** (`filter`, `must_not`) only include or exclude, so they skip scoring and are eligible for the per-segment **node query cache**. Move every yes/no condition (status, category, price range, dates) into `filter`. For a 10-hit page over 5M matches, the big wins are usually: don't count all hits exactly (`track_total_hits` defaults to 10,000, which lets Lucene skip non-competitive blocks), avoid scripts and expensive queries, fetch only the fields you need, and profile it (`"profile": true`) to see which clause dominates. Deep pagination needs `search_after` + point-in-time, not large `from`.

### Answer

**Filter vs query context:**

```json
GET /products/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "title": "laptop" } }
      ],
      "filter": [
        { "term":  { "status": "active" } },
        { "term":  { "category": "electronics" } },
        { "range": { "price": { "gte": 500, "lte": 2000 } } }
      ]
    }
  },
  "_source": ["title", "price", "image_url"],
  "size": 10
}
```

Only `title` contributes to the score. The filters narrow the candidate set cheaply and can be cached. Moving a condition from `must` to `filter` doesn't change *which* documents match, only the scoring.

**Where 800 ms usually goes, and the fix:**

| Symptom (from the Profile API / slow log) | Fix |
|---|---|
| Exact counting of 5M hits | `track_total_hits: false` or a cap (the default is 10,000, so check the client isn't setting `true`) |
| Expensive clause: leading wildcard, regexp, `script` query, large `terms` list | Index-time solutions: `wildcard` field type, `keyword` normalizers, precomputed fields |
| Filters re-evaluated every time | Put them in `filter` context so the query cache can reuse them |
| Large `_source` fetch | `_source` filtering or `fields`, smaller documents |
| Big `from` (deep pages) | `search_after` + PIT |
| Many shards hit per query | Fewer, larger shards. Routing. Time-range pruning (shards outside the range are skipped by `can_match`). |
| Same aggregation-only dashboard request repeated | The **shard request cache** (caches `size: 0` results until the next refresh) |

**Caches (all per node):**

- **Node query cache** (`indices.queries.cache.size`, default 10% of heap): caches filter results as per-segment doc-ID sets (bitsets or similar). It's LRU, and only caches filters that are **used repeatedly** (usage history over recent queries) on **segments with ≥10,000 docs** (and more than 3% of the shard). Cheap term filters are often not cached at all because recomputing them is as fast. Entries stay valid as long as their segment exists, because segments are immutable. New segments need new entries, and merged-away segments drop theirs. So frequent refreshes and merges reduce hit rates.
- **Shard request cache:** whole shard-level responses for `size: 0` requests (aggregations, counts). Invalidated on refresh, so it pays off on indexes that don't change often.
- **OS page cache:** holds segment files, doc values and postings. The biggest cache of all, which is why ES heap is capped around 50% of RAM (and below ~31 GB for compressed pointers).

**Scoring-free shortcuts:** `constant_score` wraps a filter and gives every hit the same score. Handy when you need a query but don't need relevance.

**Deep pagination:**

- `from + size`: every shard must collect its top `from + size` hits, and the coordinating node merges `shards × (from + size)`. Cost grows linearly with page depth. It's capped by `index.max_result_window` (10,000).
- `search_after` with a **point-in-time (PIT)**: each shard keeps only `size` hits after the cursor. It still evaluates the matching docs, but with a constant-size priority queue. PIT gives a consistent snapshot across pages.
- `scroll` is no longer recommended for deep pagination. Use PIT + `search_after`.

```json
POST /products/_pit?keep_alive=1m
GET /_search
{
  "size": 10,
  "pit": { "id": "<pit-id>", "keep_alive": "1m" },
  "sort": [ { "created_at": "desc" }, { "_shard_doc": "asc" } ],
  "search_after": [ 1735689600000, 4294967298 ]
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Filter vs query** | Same matches, no scoring, cache-eligible |
| **Cache mechanics** | Per-segment, usage-tracked, immutability makes entries valid until merge. Request cache vs query cache. |
| **Diagnosis** | Profile API, slow logs, `track_total_hits`, expensive query types |
| **Deep pagination** | Why `from+size` grows with depth. `search_after` + PIT. |

**What they probe next:** "Relevance tuning without slowing queries?" `function_score`/`rank_feature` for popularity, `rescore` on the top N only. "How do you protect the cluster from a bad query?" `search.max_buckets`, `allow_expensive_queries: false`, timeouts, circuit breakers.

---

## 4. Aggregations: Metric, Bucket, Pipeline

**Q:** "You have 10M e-commerce orders. Build a dashboard showing: revenue by category (drill-down to subcategory), top-selling products, and month-over-month growth. How do aggregations work internally? What's the field data memory cost?"

**What They're Really Testing:** Whether you know aggregations run on **doc values** (on-disk columnar data), how global ordinals and terms-agg accuracy work, and what actually consumes heap.

!!! tip "30-second answer"
    Aggregations read **doc values**, columnar per-field data stored on disk and served through the page cache, not from the heap. `terms` aggs on `keyword` fields use **global ordinals**: a per-shard mapping from each segment's term ordinals to one shard-wide ordinal, so buckets are counted as integers. They're built lazily after each refresh (or eagerly with `eager_global_ordinals`), and their cost scales with the number of **unique terms**, not documents. Heap goes mainly to **buckets** (high-cardinality, nested terms aggs), guarded by `search.max_buckets` and the request circuit breaker. `terms` results are approximate across shards (`shard_size`, `doc_count_error_upper_bound`). MoM growth is a `derivative` / `bucket_script` pipeline inside a `date_histogram`.

### Answer

**Metric and bucket aggregations:**

```json
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "total_revenue":   { "sum": { "field": "amount" } },
    "price_stats":     { "stats": { "field": "amount" } },
    "unique_customers": {
      "cardinality": { "field": "customer_id", "precision_threshold": 40000 }
    },
    "by_category": {
      "terms": { "field": "category", "size": 10, "order": { "revenue": "desc" } },
      "aggs": {
        "revenue": { "sum": { "field": "amount" } },
        "by_subcategory": {
          "terms": { "field": "subcategory", "size": 10 },
          "aggs": { "revenue": { "sum": { "field": "amount" } } }
        }
      }
    },
    "top_products": {
      "terms": { "field": "product_id", "size": 10, "order": { "units": "desc" } },
      "aggs": { "units": { "sum": { "field": "quantity" } } }
    }
  }
}
```

- **`cardinality`** uses HyperLogLog++. Counts below `precision_threshold` (max 40,000) are close to exact. Above it, the error is typically a few percent, with fixed memory (about `precision_threshold × 8` bytes per bucket).
- **`terms` accuracy:** each shard returns its top `shard_size` (default `size × 1.5 + 10`) buckets and the coordinator merges them. A term that's #11 on every shard can be missing from the global top 10. Check `doc_count_error_upper_bound`, raise `shard_size`, or use a `composite` aggregation to page through **all** buckets exactly.
- **Ordering by a sub-aggregation** (as above) makes the error bound worse. Use it knowingly.

**Global ordinals and memory:**

```
keyword field "category" in one segment:
  segment-local ordinals: 0=electronics 1=fashion 2=home  (sorted terms in that segment)
Different segments have different term sets → global ordinals map each segment
ordinal to a shard-wide ordinal, so a terms agg can count into an int-indexed array.

Cost:
  - Built per shard, lazily on the first agg after a refresh (latency spike on
    high-cardinality fields), or eagerly at refresh with "eager_global_ordinals": true.
  - Memory ∝ unique terms (the mapping), NOT doc count. A 10-value category field is trivial.
    A 50M-value product_id field is not.
  - Lives on heap (fielddata breaker accounts for it).

execution_hint:
  "global_ordinals" (default for keyword): best when many docs match.
  "map": builds buckets from the actual values of matching docs. Only better when
         very FEW docs match (e.g. a narrow filter), since it skips global ordinals.
```

**What actually uses heap:** bucket objects (a nested 1,000 × 1,000 terms agg is 1M buckets), `top_hits` documents, global ordinals for high-cardinality fields, and `fielddata` on `text` fields (avoid it). Guards:

```yaml
search.max_buckets: 65536                # per request (default)
indices.breaker.request.limit: 60%       # per-request structures (default)
indices.breaker.total.limit: 95%         # parent breaker with real-memory tracking (default);
                                         # 70% if indices.breaker.total.use_real_memory=false
indices.breaker.fielddata.limit: 40%
```

Exceeding one throws `CircuitBreakingException` (HTTP 429) instead of an OutOfMemoryError.

**Month-over-month growth (pipeline aggregations):**

```json
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "monthly": {
      "date_histogram": { "field": "order_date", "calendar_interval": "month", "format": "yyyy-MM" },
      "aggs": {
        "revenue": { "sum": { "field": "amount" } },
        "revenue_change": { "derivative": { "buckets_path": "revenue" } },
        "mom_pct": {
          "bucket_script": {
            "buckets_path": { "change": "revenue_change", "current": "revenue" },
            "script": "params.change / (params.current - params.change) * 100"
          }
        }
      }
    }
  }
}
```

Pipeline aggs run on the coordinating node over the finished buckets. The first month has no derivative, so `bucket_script` skips it by default (`gap_policy: skip`). `serial_diff` with `lag: 12` gives year-over-year.

**At dashboard scale:** pre-aggregate rather than scanning 10M raw orders on every page load. Options: **transforms** (continuous pivot into a summary index), **downsampling** for metrics (TSDS), or ES|QL `STATS ... BY` for ad hoc analysis. The rollup feature is deprecated in favour of downsampling.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Doc values** | Aggregations read columnar on-disk data, not the heap |
| **Global ordinals** | Per-shard mapping, cost ∝ unique terms, lazy vs eager build |
| **Accuracy** | `shard_size`, error bounds, `composite` for exhaustive results, HLL error |
| **Memory guards** | Buckets, circuit breakers, `search.max_buckets` |
| **Pipeline aggs** | `derivative` / `serial_diff` / `bucket_script` inside the histogram |

**What they probe next:** "First dashboard load after each refresh is slow?" Global ordinals rebuild, so use `eager_global_ordinals` on the hot fields or a longer refresh interval. "How do you get exact top-N?" `composite` paging, or a transform that precomputes it.

---

## 5. Cluster Management: Discovery, Master Election

**Q:** "Your ES cluster has 10 nodes. Two nodes experience a network partition. One side has 6 nodes, the other has 4. What happens? How does Elasticsearch's Zen Discovery handle master election? How does the 7.x cluster coordination layer differ?"

**What They're Really Testing:** Whether you know that quorum is counted over **master-eligible voting nodes**, not all nodes, how the 7.x+ coordination layer removed the split-brain footgun, and how to lay out node roles.

!!! tip "30-second answer"
    What matters is where the **master-eligible voting nodes** are, not the 6/4 split of all nodes. With 3 dedicated masters, the side holding 2 of them keeps (or elects) a master and carries on. Replicas on the far side are marked stale and replaced, and missing primaries are promoted from local replicas. The minority side has no master. It rejects writes, and by default (`cluster.no_master_block: write`) can still serve reads from local shards, possibly stale. In 6.x and earlier, **Zen** required you to set `minimum_master_nodes` correctly by hand, and getting it wrong caused split-brain. Since **7.0** the coordination layer tracks the **voting configuration** automatically, needs a majority of it for every election and cluster-state commit, and is formally specified (TLA+). Split-brain from misconfiguration is no longer possible.

### Answer

**The partition, with 3 dedicated master-eligible nodes M1–M3 and 7 data nodes:**

```
Side 1 (6 nodes): M1, M2, D1..D4      Side 2 (4 nodes): M3, D5..D7

Side 1: 2/3 voters → majority. Keeps the current master (or elects M1/M2).
  - Removes side-2 nodes after fault detection (follower checks fail).
  - Primaries that lived on side 2: promotes in-sync replicas on side 1.
    Shards with no copy on side 1 → red until the partition heals.
  - Writes continue for green/yellow indices.
Side 2: 1/3 voters → cannot elect. No master.
  - cluster.no_master_block = write (default): reject writes and metadata changes,
    serve reads from local shard copies (may be stale). "all" blocks reads too.
  - When the partition heals, side-2 nodes rejoin and their stale copies resync
    or are rebuilt from the current primaries.
```

If all 10 nodes were master-eligible, the 6-node side would hold a majority of voters, with the same outcome. Quorum is always about **voters**.

**Zen Discovery (6.x and earlier):**

```yaml
discovery.zen.ping.unicast.hosts: ["m1", "m2", "m3"]   # unicast pings, not gossip
discovery.zen.minimum_master_nodes: 2                  # must be (master_eligible / 2) + 1
```

The problems: the setting had to be kept correct by hand as master-eligible nodes were added or removed. Set too low, you got two masters (split-brain) and diverging cluster states. Set too high, you lost availability. There were also known edge cases where acknowledged cluster-state updates could be lost.

**Cluster coordination (7.0+):**

- **Voting configuration** = the set of master-eligible nodes whose votes count. It's stored in the cluster state and adjusted automatically as nodes join or leave, keeping an odd size (`cluster.auto_shrink_voting_configuration`).
- **Elections:** a candidate must win votes from a majority of the voting configuration for a new **term**. Nodes only vote for candidates whose last accepted cluster state is at least as fresh as their own.
- **Publication:** cluster-state updates are two-phase (publish, then commit once a majority acks, `cluster.publish.timeout` 30 s). They're applied in order.
- **Bootstrapping:** `cluster.initial_master_nodes` is used **once**, when forming a brand-new cluster. Remove it afterwards. Leaving it on can form a second, separate cluster after a full restart with wiped data.
- **Removing master-eligible nodes:** with more than half at once, use the voting config exclusions API (`POST _cluster/voting_config_exclusions?node_names=...`), otherwise the cluster loses quorum.

**Node roles:**

```yaml
# Dedicated master-eligible (3 is the standard, rarely more)
node.roles: [ master ]

# Optional tiebreaker in a 2-zone deployment: votes, never becomes master, tiny hardware
node.roles: [ master, voting_only ]

# Data nodes by tier
node.roles: [ data_hot, data_content, ingest ]
node.roles: [ data_warm ]

# Coordinating-only (fan-out/merge for heavy search or aggregation traffic)
node.roles: []
```

**Why dedicated masters:** the master maintains cluster state (mappings, routing table, settings) and runs allocation. If it shares a node with heavy search or indexing, GC pauses and resource contention delay cluster-state updates and can trigger re-elections. The master doesn't route search or index requests (any node can coordinate). Three dedicated masters across three zones survive the loss of one zone.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Quorum** | Counted over master-eligible voters, not all nodes |
| **Minority behavior** | No master → writes blocked, reads per `no_master_block` |
| **Zen vs 7.x** | Manual `minimum_master_nodes` vs automatic voting configuration with terms and two-phase publication |
| **Roles** | Dedicated `[master]`, `voting_only` tiebreaker, coordinating-only |
| **Bootstrapping** | `initial_master_nodes` only for first formation |

**What they probe next:** "Two availability zones only?" Put a `voting_only` tiebreaker master in a third location. Otherwise losing the zone holding 2 of 3 masters stops the cluster. "Cluster state is huge and updates are slow?" Too many indices, shards or fields: consolidate, use data streams, `dynamic: strict`.

---

## 6. Indexing: Refresh, Flush, Merge

**Q:** "Your ES cluster ingests 50K documents/second. Indexing latency is 200ms but you need 50ms. Search latency is also high during indexing bursts. Walk through the indexing pipeline — refresh interval, translog, merge policy — and optimize for this throughput."

**What They're Really Testing:** Whether you understand the write path (primary → replicas, translog durability modes), what refresh and merges cost, and which knobs trade freshness and durability for throughput.

!!! tip "30-second answer"
    A bulk request is split per shard, indexed on the **primary** (in-memory Lucene buffer + translog append), then sent to all **in-sync replicas** in parallel. With the default `translog.durability: request`, the translog is **fsynced on primary and replicas before the ack**. Bulk latency is therefore roughly analysis + fsync + slowest replica. Levers: well-sized bulk requests (5–15 MB) from parallel clients, auto-generated IDs, a longer `refresh_interval` (fewer tiny segments and less merge pressure), lean mappings, and enough indexing threads and fast disks. `translog.durability: async` cuts latency but can lose up to `sync_interval` (5 s) of acknowledged writes. Search slows during bursts because refresh, merges and indexing compete for CPU, I/O and page cache. Separating hot indexing from heavy search (tiers or separate clusters) is the structural fix.

### Answer

**Write path:**

```
Client bulk → coordinating node → split by shard → primary shard
  1. Parse + map + analyze document; index into the Lucene in-memory buffer
  2. Append operation to the translog
  3. Forward to in-sync replicas (in parallel); each does 1–2
  4. translog fsync (durability=request: per request, before ack) on primary + replicas
  5. Ack to client  ← document is durable but NOT yet searchable

Later:
  Refresh (1 s default): buffer → searchable segment (no fsync)
  Flush:  Lucene commit (fsync segments) + roll the translog
          triggered by index.translog.flush_threshold_size (512 MB default) and periodically
  Merge:  background, concurrent with indexing
```

**Translog and recovery:**

- `index.translog.durability: request` (default): every acknowledged operation is fsynced on every in-sync copy. No acked write is lost when a node crashes.
- `async`: fsync every `index.translog.sync_interval` (5 s). Higher throughput, and up to 5 s of **acknowledged** writes can be lost if the primary and its replicas all crash. Acceptable for some log pipelines that can replay from Kafka, not for primary data.
- **Crash recovery:** the shard opens the last Lucene commit and replays the translog after it. **Peer recovery** of replicas uses file copy plus operation history (soft deletes + retention leases).

**Refresh tuning:**

```json
PUT logs-app/_settings
{ "index": { "refresh_interval": "30s" } }
```

Fewer, larger segments mean less flush and merge churn and more CPU for indexing. The cost is up to 30 s before new data is searchable. If you **don't** set `refresh_interval` explicitly, shards that haven't been searched for 30 s (`index.search.idle.after`) skip scheduled refreshes entirely. Heavy-ingest indexes that are rarely searched get this for free.

**Initial bulk load (not steady state):**

```json
PUT my-index/_settings
{ "index": { "refresh_interval": "-1", "number_of_replicas": 0 } }
// ... bulk load ...
PUT my-index/_settings
{ "index": { "refresh_interval": null, "number_of_replicas": 1 } }
```

Adding replicas afterwards copies finished segments, which is cheaper than indexing every document twice. Never run production writes with zero replicas: one node loss means data loss.

**Merges:**

- TieredMergePolicy defaults are right for almost everyone. Merges are auto-throttled. `index.merge.scheduler.max_thread_count` defaults from CPU count; setting it to 1 is advice for **spinning disks** only.
- If merges fall behind (segment count climbing, `merges.current` high, indexing throttled with "now throttling indexing" in logs), the bottleneck is disk I/O. Fix it with faster disks, a longer refresh interval or fewer shards per node, not merge-policy tuning.
- **Force merge** to 1 segment only for indexes that will **no longer be written** (ILM does this on rollover to warm). It doesn't block writes, but segments over 5 GB produced this way aren't merged again by normal merging, so later updates and deletes leave dead space that never gets reclaimed.

**Optimization checklist for 50K docs/s:**

| Lever | Why |
|---|---|
| Bulk 5–15 MB per request, several concurrent clients, retry on 429 with backoff | Amortizes per-request overhead, keeps all shards busy. 429 = write thread pool queue full (back-pressure). |
| Auto-generated `_id` | Skips the "does this ID exist?" lookup per document |
| `refresh_interval` 5–30 s | Fewer tiny segments |
| Lean mappings: `dynamic: strict`, no unnecessary `text` + `keyword` pairs, `index: false` on unsearched fields | Less analysis and fewer data structures per doc |
| `index.mode: logsdb` (logs) or `time_series` (metrics) | Index sorting + synthetic `_source`: much less disk, often faster ingest per byte |
| Enough primaries on the write index, spread across hot nodes | Parallelism. `total_shards_per_node` avoids stacking. |
| Ingest pipelines: watch `_nodes/stats/ingest` | Grok/regex processors are often the hidden CPU cost |
| NVMe on hot nodes, `indices.memory.index_buffer_size` (10% default) if many active shards | Disk fsync latency is the floor for `durability: request` |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Write path** | Primary then replicas, translog fsync before ack by default |
| **Translog trade-off** | `request` vs `async`, and what "lose 5 s of **acked** writes" means |
| **Refresh** | Visibility vs segment churn, search-idle shards |
| **Merges** | When force merge is safe, merge throttling as a symptom of disk limits |
| **Bulk practice** | Request size, 429 back-pressure, auto IDs, replicas only during initial loads |

**What they probe next:** "Why are 429s good?" They're back-pressure: clients must slow down and retry, not escalate. "Ingest via Kafka?" Kafka absorbs bursts, consumers bulk-index at a steady rate, and you can replay after mapping mistakes.

---

## 7. Tuning: Mapping, Analyzers, Field Data

**Q:** "A text field in your index is used for both exact match filtering and full-text search. Currently it's mapped as 'text' and you're using a 'keyword' subfield. The filter performance is poor. Diagnose and optimize the mapping. What analyzers should you use?"

**What They're Really Testing:** Whether you understand text vs keyword, how index-time and search-time analysis must line up, doc values vs fielddata, and how mapping choices drive disk, heap and latency.

!!! tip "30-second answer"
    `text` + a `keyword` multi-field is the **correct** pattern: full-text queries go to `product_name`, and exact filters, sorts and aggregations go to `product_name.keyword` with `term`/`terms` in filter context. When "filter performance is poor", the cause is usually the query, not the mapping. Typical culprits: filtering on the `text` field, `wildcard`/`regexp` with leading wildcards, case-insensitive matching via scripts, or huge `terms` lists. Fixes: a `keyword` **normalizer** for case-insensitive exact matches, the `wildcard` field type for substring search, `edge_ngram` at index time for autocomplete. Index and search analyzers must produce **compatible tokens**.

### Answer

**Mapping with explicit analyzers:**

```json
PUT products
{
  "settings": {
    "analysis": {
      "normalizer": {
        "lowercase_ascii": { "type": "custom", "filter": ["lowercase", "asciifolding"] }
      },
      "filter": {
        "english_stemmer": { "type": "stemmer", "language": "english" },
        "autocomplete_edge": { "type": "edge_ngram", "min_gram": 2, "max_gram": 15 }
      },
      "analyzer": {
        "product_text": {
          "type": "custom", "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding", "english_stemmer"]
        },
        "autocomplete_index": {
          "type": "custom", "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding", "autocomplete_edge"]
        },
        "autocomplete_search": {
          "type": "custom", "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding"]
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "product_name": {
        "type": "text",
        "analyzer": "product_text",
        "fields": {
          "exact":   { "type": "keyword", "normalizer": "lowercase_ascii", "ignore_above": 256 },
          "suggest": { "type": "text", "analyzer": "autocomplete_index",
                       "search_analyzer": "autocomplete_search" }
        }
      },
      "sku":           { "type": "keyword" },
      "description":   { "type": "text", "analyzer": "product_text", "norms": false },
      "internal_note": { "type": "text", "index": false },
      "attributes":    { "type": "flattened" }
    }
  }
}
```

Analyzers are index settings. Define them at creation (or in a template). Changing an existing analyzer requires closing the index, and changing a field's analyzer requires a **reindex**.

**Index vs search analyzers:**

- The tokens produced at search time must match tokens stored at index time. If the index side stems `running → run` and the search side doesn't, a search for "running" finds nothing. Use the **same** analyzer unless you have a specific reason.
- Legitimate asymmetric cases:
    - `edge_ngram` at index time with a plain analyzer at search time (autocomplete, as above). Otherwise the query is also split into n-grams and matches everything.
    - **Synonyms at search time** (`synonym_graph`), so synonym lists can be updated without reindexing (`updateable: true` + reload search analyzers).
- Test with `POST products/_analyze { "analyzer": "product_text", "text": "Running Shoes Café" }`.
- The `standard` analyzer = standard tokenizer + lowercase (stop words **off** by default).

**Doc values vs fielddata:**

| | Doc values | Fielddata |
|---|---|---|
| For | `keyword`, numeric, date, boolean, geo, ... | `text` fields only |
| Where | On disk, columnar, read via page cache | On **heap**, built on first use by un-inverting the index |
| Default | On (disable with `doc_values: false` if never sorted or aggregated) | Off (`fielddata: true` is almost always a mistake) |

To aggregate on text-like data, aggregate on a `keyword` sub-field.

**Mapping levers that save disk and heap:**

- **Synthetic `_source`** (default in logsdb/TSDS index modes): `_source` is rebuilt from doc values instead of stored, which saves a lot of disk. Field order and some formatting aren't preserved exactly.
- Disabling `_source` entirely (`"_source": {"enabled": false}`) also breaks update, update-by-query, reindex and highlighting from source. Prefer synthetic source.
- `norms: false` on text fields where length shouldn't affect scoring (e.g. a long `description` used mainly for matching).
- `index: false` for fields only returned, never queried. `doc_values: false` for keyword fields never sorted or aggregated.
- **Mapping explosion:** `dynamic: strict` (or `runtime`), `index.mapping.total_fields.limit` (1,000 default), and `flattened` for arbitrary key/value attributes. Every field costs cluster-state size and heap on every node.
- **Runtime fields** compute values at query time from `_source` or doc values. They're great for exploring and fixing mistakes without reindexing, but they're evaluated per matching doc, so promote hot ones to indexed fields.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Diagnosis first** | Checks the query (field used, query type) before blaming the mapping |
| **Multi-fields** | text + keyword (with normalizer), autocomplete sub-field |
| **Analyzer symmetry** | Knows when asymmetric analyzers break recall and when they're intended |
| **Doc values vs fielddata** | Disk/page cache vs heap |
| **Mapping hygiene** | Synthetic source, strict dynamic mapping, field limits, flattened |

**What they probe next:** "How do you change a mapping in production?" Create a new index with the new mapping, `_reindex` (or reindex from the source of truth), then atomically swap an alias. "Multi-language content?" A field per language with its analyzer, or language detection in an ingest pipeline.

---

## 8. Hot-Warm-Cold Architecture & ILM

**Q:** "Design an Elasticsearch architecture for time-series metrics data: 5TB/day ingestion, 90-day retention, with 500ms query latency SLA on last 7 days and archive-then-delete after 90 days. How does Index Lifecycle Management (ILM) work?"

**What They're Really Testing:** Whether you can design data streams + ILM across data tiers (including searchable snapshots), size them with real arithmetic, and use time-series-specific features to cut cost.

!!! tip "30-second answer"
    Write into a **data stream** backed by an index template with an ILM policy. Hot nodes (`data_hot`, NVMe) hold the write index plus the last 7 days, sized for both indexing and the 500 ms SLA. ILM **rolls over** at `max_primary_shard_size: 50gb` or 1 day. After 7 days it force-merges (and **downsamples** metrics) and migrates to warm. Later it moves to **cold** or **frozen** as **searchable snapshots** in object storage, so the snapshot replaces replicas. It deletes at 90 days, after confirming a snapshot exists. For metrics, use **TSDS** (`index.mode: time_series`): index sorting and synthetic source shrink storage a lot, and downsampling cuts it further for older data.

### Answer

**Node tiers (built-in data tier roles since 7.10):**

```yaml
# Hot: indexing + recent queries. NVMe, high CPU, ~30 GB heap, rest page cache.
node.roles: [ data_hot, data_content, ingest ]

# Warm: read-mostly, cheaper SSD/large disks, fewer cores
node.roles: [ data_warm ]

# Cold: fully mounted searchable snapshots (one local copy, snapshot repo is the redundancy)
node.roles: [ data_cold ]

# Frozen: partially mounted searchable snapshots; small local cache, data fetched from S3 on demand
node.roles: [ data_frozen ]
```

ILM moves indices between tiers automatically (the implicit `migrate` action uses `_tier_preference`). There's no need for custom `node.attr` filters.

**ILM policy:**

```json
PUT _ilm/policy/metrics-90d
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_primary_shard_size": "50gb", "max_age": "1d" },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "downsample": { "fixed_interval": "5m" },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "searchable_snapshot": { "snapshot_repository": "s3-metrics" },
          "set_priority": { "priority": 0 }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "wait_for_snapshot": { "policy": "nightly-snapshots" },
          "delete": {}
        }
      }
    }
  }
}
```

Notes:

- `min_age` is measured from **rollover**, not index creation.
- `max_size` in rollover is deprecated in favour of `max_primary_shard_size`.
- **Shrink** is optional and must target a **factor** of the current primary count (e.g. 6 → 3, 2 or 1; never 5 → 2). It also needs all copies on one node first. Often you just skip it by sizing primaries correctly.
- `downsample` needs a TSDS index. It replaces raw points with per-interval aggregates (min/max/sum/count/last), which is ideal for older metrics.
- "Archive then delete": snapshot lifecycle management (SLM) takes snapshots, `wait_for_snapshot` guarantees one exists before deletion, and the snapshot repo (S3 with lifecycle rules) is the archive.

**Index template (data stream + TSDS):**

```json
PUT _index_template/metrics
{
  "index_patterns": ["metrics-*"],
  "data_stream": {},
  "priority": 200,
  "template": {
    "settings": {
      "index.mode": "time_series",
      "index.routing_path": ["host", "metric_name"],
      "number_of_shards": 6,
      "number_of_replicas": 1,
      "index.lifecycle.name": "metrics-90d"
    },
    "mappings": {
      "properties": {
        "@timestamp":  { "type": "date" },
        "host":        { "type": "keyword", "time_series_dimension": true },
        "metric_name": { "type": "keyword", "time_series_dimension": true },
        "value":       { "type": "double",  "time_series_metric": "gauge" }
      }
    }
  }
}
```

With a data stream, the first write (`POST metrics-prod/_doc`) creates the stream and its backing index. There's no bootstrap index and no rollover alias.

**Sizing (back of the envelope; measure real on-disk size, since TSDS/logsdb often store far less than raw):**

```
Assume 5 TB/day raw ≈ 2.5 TB/day on disk after TSDS compression (measure!).

Hot (days 0–7):  7 × 2.5 TB × 2 (1 replica) = 35 TB
                 at ~3 TB usable per node (keep under the 85% low watermark, plus headroom
                 for merges and node loss) → ~12–14 hot nodes.
                 Also check indexing: 5 TB/day ≈ 58 MB/s raw sustained (peaks several ×).
Warm (7–30 d):   downsampled 5m from raw seconds-level data → often 10×+ smaller.
                 23 days × (2.5 TB / 10) × 2 ≈ 12 TB → a few warm nodes.
Cold (30–90 d):  searchable snapshots: 1 local copy + S3. Or frozen tier: S3 + small cache.
```

**Meeting the 500 ms SLA on the last 7 days:**

- Query the data stream with a `@timestamp` range filter. Shards whose time range doesn't overlap are skipped in the `can_match` pre-filter phase. You don't need index-name patterns or date math.
- Keep the last 7 days on hot nodes with enough RAM for the page cache to hold the hot working set. Give dashboards pre-aggregated or downsampled data. Watch shards per query and shard sizes.
- Run queries that reach cold or frozen data asynchronously (`_async_search`) with a looser SLA.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Tiered architecture** | Built-in data tiers. Cold/frozen via searchable snapshots, not HDD nodes with replicas. |
| **ILM mechanics** | Rollover on primary shard size, `min_age` from rollover, valid shrink targets, `wait_for_snapshot` |
| **Data streams + TSDS** | No aliases to manage. Downsampling for metrics. |
| **Sizing** | Real arithmetic with replicas, watermarks and headroom |
| **Query SLA** | Time-range shard skipping, page cache on hot, async search for old data |

**What they probe next:** "Would you use Elasticsearch for metrics at all?" Compare it with a purpose-built TSDB (Prometheus/Mimir, VictoriaMetrics, ClickHouse). ES wins when logs, metrics and traces are searched together. "OpenSearch equivalent?" ISM policies, UltraWarm/cold storage on AWS, and searchable snapshots in OpenSearch.

---

> *These 8 questions cover Elasticsearch from Lucene internals to tiered architectures for time-series data. Re-check the version baseline at the top on each major release.*
