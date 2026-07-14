# Search Platform - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Information retrieval, inverted index, ranking algorithms, distributed search, relevance

---

## Question 1: Core Design
**Interviewer:** *"Design a search platform — document indexing, tokenization, ranking, query parsing."*

### 🎯 Expected Answer

**Core Architecture:**
```
Documents → Tokenizer → Inverted Index → Query Parser → Ranking → Results
                │                            │
           Stop words,                  AND/OR/NOT,
           stemming                     fuzzy, phrases
```

**Inverted Index — The Heart of Search:**
```python
class InvertedIndex:
    def __init__(self):
        # token -> {doc_id -> term_frequency}
        self._index: Dict[str, Dict[str, int]] = {}
        self._documents: Dict[str, Document] = {}
    
    def add_document(self, doc: Document):
        self._documents[doc.doc_id] = doc
        tokens = self._tokenize(doc.title + " " + doc.content)
        
        for token in set(tokens):
            if token not in self._index:
                self._index[token] = {}
            # Increment term frequency for this document
            self._index[token][doc.doc_id] = self._index[token].get(doc.doc_id, 0) + 1
    
    def search(self, query: str) -> Dict[str, float]:
        tokens = self._tokenize(query)
        scores = {}
        for token in tokens:
            if token in self._index:
                for doc_id, tf in self._index[token].items():
                    scores[doc_id] = scores.get(doc_id, 0) + tf
        return scores
```

**Why Inverted Index?** Without it, search would be O(N × D) — scan every document for every query term. With it, search is O(K) where K = number of matching docs (usually tiny). This is the same technology Google, Elasticsearch, and Lucene use.

---

## Question 2: Ranking with TF-IDF
**Interviewer:** *"How do you rank results by relevance?"*

### 🎯 Answer

**TF-IDF (Term Frequency × Inverse Document Frequency):**
```python
class TfIdfRanking(RankingStrategy):
    def rank(self, scores, query, index):
        n = index.document_count
        
        for doc_id in list(scores.keys()):
            # IDF = log(N / df) — rare terms get higher weight
            doc_freq = sum(1 for t, posting in index._index.items() 
                          if doc_id in posting)
            idf = math.log(n / (1 + doc_freq))
            scores[doc_id] *= idf
        
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

**Why TF-IDF?** A term appearing in a document multiple times (high TF) is important. But a term appearing in many documents (high DF) is NOT discriminative. TF * IDF captures both: it rewards terms that are frequent in the matched document but rare across the collection.

**BM25 (Okapi BM25) — Industry Standard:**
```
BM25 score = IDF * (TF * (k1 + 1)) / (TF + k1 * (1 - b + b * (doc_len / avg_doc_len)))
```
Where `k1` (term saturation, default 1.2) and `b` (length normalization, default 0.75) are tunable. BM25 consistently outperforms raw TF-IDF in practice.

---

## Question 3: Query Understanding
**Interviewer:** *"How would you improve search quality?"*

### 🎯 Techniques

| Technique | Implementation | Impact |
|-----------|----------------|--------|
| **Stemming** | Port stemmer: "running" → "run" | 15% recall improvement |
| **Synonym expansion** | Thesaurus: "laptop" → "laptop notebook" | 10% recall |
| **Spell correction** | Levenshtein distance: "desing" → "design" | 5-20% improvement |
| **Phrase detection** | `"system design"` treated as one token | Precision improvement |
| **Stop words** | Remove "the", "a", "and" | 30% index size reduction |

**Spell correction with Levenshtein:**
```python
class LevenshteinMatcher(FuzzyMatcher):
    def match(self, query, text, max_distance=2):
        return self._levenshtein(query.lower(), text.lower()) <= max_distance
    
    def _levenshtein(self, s1, s2):
        # Dynamic programming — O(m*n)
        dp = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            new_dp = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                new_dp.append(min(new_dp[j] + 1,    # delete
                                  dp[j + 1] + 1,    # insert
                                  dp[j] + cost))    # substitute
            dp = new_dp
        return dp[-1]
```

---

## Question 4: Scaling to Billions of Documents

**Architecture:**
```
                   ┌──────────┐
Query ────────────▶│  Router   │──▶ Shard 1 (docs 0-1B)
                   │          │──▶ Shard 2 (docs 1B-2B)
                   └──────────┘──▶ Shard M
                        │
                   ┌────▼─────┐
                   │  Merge   │──▶ Top K results
                   │  Results │
                   └──────────┘
```

**Sharding strategy:** Document ID hash → shard. Each shard has its own inverted index. Query fan-out to all shards, merge top K results on the coordinating node.

**Caching:** Cache frequent queries in Redis. Pre-compute top-1000 for popular query prefixes.

---

## Question 5: Real-time Indexing

**Approach: Write-ahead log + in-memory buffer + periodic flush:**
```python
class RealTimeIndex:
    def __init__(self):
        self._wal = []  # Write-ahead log for durability
        self._buffer = InMemoryIndex()  # Recent documents (NRT)
        self._main_index = OnDiskIndex()  # Merged index
    
    def index_document(self, doc):
        self._wal.append(doc)  # Durability
        self._buffer.add(doc)  # Queryable immediately
        
        if len(self._buffer) > 10000:  # Flush threshold
            self._flush_buffer()
    
    def search(self, query):
        # Search both — merge results
        buffer_results = self._buffer.search(query)
        main_results = self._main_index.search(query)
        return merge(buffer_results, main_results)
```

**Trade-off:** Real-time vs. batch indexing. Real-time: documents visible within seconds, but higher overhead. Batch: hourly rebuild, simpler, better compression.

---

## Question 6: Advanced Ranking Features

**Recency boost (decorator pattern):**
```python
class RecencyBoostRanking(RankingStrategy):
    def __init__(self, base_ranking):
        self._base = base_ranking
    
    def rank(self, scores, query, index):
        scored = dict(scores)
        now = datetime.now()
        for doc_id in scored:
            doc = index.get_document(doc_id)
            days_ago = (now - doc.created_at).days
            if days_ago < 7:
                scored[doc_id] *= 1.5  # Freshness boost
            elif days_ago > 365:
                scored[doc_id] *= 0.5  # Old content penalty
        return self._base.rank(scored, query, index)
```

**Personalization:** Boost results based on user's past clicks, location, or preferences. Requires user profile store and real-time scoring.

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Ranking | TF-IDF, BM25, popularity, recency |
| **Facade** | SearchService | Unified search API |
| **Builder** | Query construction | AND/OR/NOT tree building |
| **Decorator** | RecencyBoost | Wrap ranking with additional signal |
| **Composite** | Query tree | Recursive AND/OR/NOT structure |
| **Singleton** | Index manager | Single index instance |
| **Template Method** | Search flow | Consistent: parse → search → rank → format |
