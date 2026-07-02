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
    
    # Stage 3: Post-ranking (business logic boost)
    results = es.search(index="documents", body=es_query)
    for hit in results["hits"]["hits"]:
        # Recency boost
        days_old = (now - hit._source.created_at).days
        if days_old < 7: hit._score *= 1.5
        # Popularity boost
        hit._score *= (1 + hit._source.popularity * 0.001)
    
    return results
```

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
2. **Trie (in-memory, for ultra-low latency):**
```python
class AutocompleteTrie:
    def __init__(self):
        self._root = {}
        self._freq = {}
    
    def insert(self, word, freq=1):
        node = self._root
        for char in word:
            node = node.setdefault(char, {})
            node['_freq'] = node.get('_freq', 0) + freq
    
    def suggest(self, prefix, limit=5):
        node = self._root
        for char in prefix:
            if char not in node: return []
            node = node[char]
        # DFS for top suggestions
        return self._top_suggestions(node, prefix, limit)
```

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

**Solution:** Add data nodes. ES scales horizontally — double the nodes, double the throughput. 5 nodes → 5K qps. 10 nodes → 10K qps.

**Caching:**
- Node-level query cache (LRU, 10% of heap)
- Shard-level request cache (for aggregations)
- Application-level: Redis cache for popular queries (TTL: 60 seconds)

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| Elasticsearch (5 nodes) | $3,000 |
| Kafka cluster | $1,200 |
| API Services (2 pods) | $600 |
| Redis Cache | $300 |
| **Total** | **$5,100** |
