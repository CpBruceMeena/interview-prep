# 🏗️ Search Platform — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Information retrieval, inverted index, ranking, distributed search

---

## 1. SYSTEM OVERVIEW

**Purpose:** Full-text search platform providing fast, relevant search results across millions of documents with typo tolerance, faceted filtering, and ranking.

**Scale:** 10M indexed documents, 5K queries/second peak, 500ms p99 latency

**Users:** End users (search), Content managers (index), Platform admins

**Use Cases:** Full-text search, Typo-tolerant ("Did you mean?"), Faceted search, Autocomplete suggestions, Real-time indexing

**Constraints:** p99 latency <500ms, 95%+ recall, 99.9% uptime, <1 minute indexing delay for real-time updates

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌──────────────┐
│  Search UI   │
│  (React/PWA) │
└──────┬───────┘
       │
┌──────▼───────┐
│ API Gateway  │── Auth ── Rate Limit (10 qps per user)
└──────┬───────┘
       │
┌──────▼───────┐  ┌─────────────────┐  ┌──────────────┐
│ Search       │  │ Autocomplete    │  │ Recommendation│
│ Service      │  │ Service         │  │ Service       │
│ (Python)     │  │ (Python)        │  │ (ML model)    │
└──────┬───────┘  └───────┬─────────┘  └──────┬───────┘
       │                  │                    │
┌──────▼──────────────────▼────────────────────▼──────┐
│              Elasticsearch Cluster                   │
│  - 5 data nodes, 2 replica shards                   │
│  - NRT indexing (<1s refresh interval)              │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Indexing Pipeline (Kafka + Logstash/Fluentd)       │
│  - Document producers → Kafka topic → ES bulk index │
│  - Full reindex: hourly from PostgreSQL             │
└─────────────────────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/search-platform-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Search Platform Sequence — Query → Parse → Index Search → Rank → Results. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Search Service (Python/FastAPI)
- Query parsing (AND/OR/NOT, phrase matching)
- Ranking (TF-IDF, BM25, recency boost, popularity boost)
- Faceted aggregation (category, date, author)
- Spell correction (Levenshtein automaton)

**🔴 Interview Question:** *"How does the search ranking work? Walk me through a query."*

**✅ Answer:** Multi-stage ranking pipeline:
```python
def search(query, filters, page=1, size=20):
    # Stage 1: Query parsing
    tokens = tokenizer.tokenize(query)
    corrected = spell_check(query)  # "desing" → "design"
    
    # Stage 2: Elasticsearch query (BM25 scoring)
    es_query = {
        "query": {
            "bool": {
                "should": [
                    {"match": {"title": {"query": query, "boost": 3}}},
                    {"match": {"content": {"query": query, "boost": 1}}},
                ],
                "filter": build_filters(filters)
            }
        },
        "aggs": {"categories": {"terms": {"field": "category"}}}
    }
    
    # Stage 3: Business signals INSIDE the engine, before top-k.
    # (Multiplying scores after es.search() only reorders the page you got
    # back; it can never promote a fresher doc that ranked 21st.)
    es_query = {
        "query": {
            "function_score": {
                "query": es_query["query"],
                "functions": [
                    {"gauss": {"created_at": {"origin": "now", "scale": "30d", "decay": 0.5}}},
                    {"field_value_factor": {"field": "popularity", "modifier": "log1p", "factor": 0.1}},
                ],
                "score_mode": "multiply",
                "boost_mode": "multiply",
            }
        },
        "aggs": es_query["aggs"],
    }
    return es.search(index="documents", body=es_query)
```

The LLD's `RecencyBoost` (half-life decay) and `PopularityBoost` (log) are the in-process version of these two functions.

---

### Autocomplete Service (Python)
- Trie-based prefix matching
- Edge n-gram index for fast lookups
- Frequency-sorted suggestions

**🔴 Interview Question:** *"How do you implement fast autocomplete?"*

**✅ Answer:** Two approaches:
1. **Edge n-gram index in Elasticsearch:**
```json
{
  "settings": {
    "analysis": {
      "analyzer": {
        "autocomplete": {
          "tokenizer": "edge_ngram",
          "filter": ["lowercase"]
        }
      }
    }
  }
}
```
2. **Trie with cached top-k per node (in-memory, for ultra-low latency):**
```python
class TrieNode:
    __slots__ = ("children", "top")
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.top: list[tuple[int, str]] = []        # best (freq, word) under this prefix

class AutocompleteTrie:
    def __init__(self, k: int = 5):
        self._root, self._k = TrieNode(), k

    def insert(self, word: str, freq: int) -> None:
        node = self._root
        for ch in word:
            node = node.children.setdefault(ch, TrieNode())
            # Keep each node's top-k current, so a lookup never walks the subtree.
            entries = {w: f for f, w in node.top}
            entries[word] = max(freq, entries.get(word, 0))
            node.top = sorted(((f, w) for w, f in entries.items()), reverse=True)[: self._k]

    def suggest(self, prefix: str) -> list[str]:
        node = self._root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return []
        return [w for _, w in node.top]              # O(len(prefix))
```
Lookup is O(len(prefix)); the cost moves to insert and to memory (k entries per node). Rebuild offline from query logs (e.g. hourly) instead of updating per keystroke. Lucene's suggesters store the same thing more compactly as a weighted FST.

---

### Indexing Pipeline (Kafka + Logstash)
- Document producers → Kafka topic
- Logstash/Fluentd consumer → bulk index to ES
- Refresh interval: 1 second (NRT)

**🔴 Interview Question:** *"How do you handle real-time indexing without impacting search performance?"*

**✅ Answer:**
1. **Refresh interval:** ES default is 1 second. Set to 5 seconds for bulk, 1 second for real-time topics.
2. **Separate write path:** Indexing goes through Kafka → ES. Search queries hit ES directly. No shared bottleneck.
3. **Index swapping:** For large reindexes, build index in background, then atomically swap alias.
4. **Bulk indexing:** Batch 1K documents or 5MB per bulk request. Queue via Kafka for backpressure handling.

---

## 4. ELASTICSEARCH CLUSTER DESIGN

| Component | Configuration |
|-----------|---------------|
| Data nodes | 5 × r6g.xlarge.search (30GB RAM, 2TB storage) |
| Replica shards | 2 (3 copies of each shard) |
| Primary shards | 5 (1 per data node) |
| Refresh interval | 1 second (NRT) |
| Index storage | Managed with ILM (hot → warm → delete) |

---

## 5. SPELL CORRECTION

**Levenshtein automaton** for "Did you mean?" suggestions:
```python
def spell_correct(query, index, max_distance=2):
    tokens = query.split()
    corrected = []
    
    for token in tokens:
        if token in index:  # Exact match
            corrected.append(token)
        else:
            # Find closest in dictionary using Levenshtein
            candidates = index.fuzzy_search(token, max_distance)
            if candidates:
                corrected.append(candidates[0])  # Best match
            else:
                corrected.append(token)  # Unknown word
    
    return ' '.join(corrected)
```

---

## 6. SCALABILITY

**Bottleneck:** Elasticsearch CPU (scoring + aggregation)

**Solution:** a query hits one copy of **every** shard, so:

- **More replicas** (and nodes to hold them) scale *query throughput*: each extra copy can serve a share of queries. Doubling copies roughly doubles QPS if the queries are CPU-bound.
- **More primary shards** don't add throughput; they cut per-query latency on big indexes (each shard scans less) but add fan-out and merge cost. Primary count is fixed at index creation (changing it means `_split`/`_shrink` or a reindex), so size for growth: ~10–50 GB per shard.
- Rough sizing for the stated load: 10M docs × ~5 KB ≈ 50 GB primary; ×3 copies ≈ 150 GB, comfortably within 5 nodes. 5K QPS ÷ 15 shard copies ≈ 333 shard-queries/s per copy; benchmark a single shard to confirm it handles that at the p99 target.

**Caching:**
- Node-level query cache (LRU, 10% of heap)
- Shard-level request cache (for aggregations)
- Application-level: Redis cache for popular queries (TTL: 60 seconds)

---

## 7. CONSISTENCY & FAILURE MODES

| Concern | Choice |
|---------|--------|
| **Source of truth** | PostgreSQL. The search index is a derived, rebuildable view. Never write to ES as the only copy. |
| **Getting changes into the index** | CDC (Debezium) or a transactional outbox → Kafka → indexer. Avoid "write DB, then write ES" in the request path: a crash between the two loses the update (dual-write problem). |
| **Out-of-order events** | Index with `version_type=external` using the row's version/updated_at, so a stale event can't overwrite a newer document. Kafka partition by `doc_id` keeps per-document order. |
| **Idempotency** | Index by `doc_id` (PUT, not auto-id POST), so replaying Kafka after an indexer crash is harmless. |
| **Read-your-writes** | A document is searchable only after the next refresh (~1 s). For "I just saved it and it's missing", either return the saved doc from the DB on that screen or index with `refresh=wait_for` on that one request (never globally). |
| **Mapping change / analyzer change** | Build a new index from the source of truth, catch up from Kafka, then atomically swap the alias. Old index kept for rollback. |
| **Node loss** | Replicas are promoted; the cluster goes yellow while copies rebuild. Keep ≥ 1 replica and spread copies across zones (shard allocation awareness). |
| **Indexer lag** | Alert on consumer lag in seconds; the "<1 minute indexing delay" constraint is a lag SLO. |
| **Expensive queries** | Leading wildcards, huge `from`, deep aggregations: block or cap them at the API (max `from + size`, query timeouts, `terminate_after`). |
| **Split brain** | Use an odd number (3) of dedicated master-eligible nodes; ES 7+ manages the quorum itself. |

---

## 8. COST (Monthly)

| Component | Cost |
|-----------|------|
| Elasticsearch (5 nodes) | $3,000 |
| Kafka cluster | $1,200 |
| API Services (2 pods) | $600 |
| Redis Cache | $300 |
| **Total** | **$5,100** |
