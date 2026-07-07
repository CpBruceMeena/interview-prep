# 🔐 Redis Lease, Search Autocorrect & Elasticsearch

> **Target:** Staff/Principal Engineer | **Focus:** Distributed locking with Redis, search engine misspelling handling, autocorrect algorithms, and Elasticsearch internals

---

## 1. REDIS LEASE MECHANISM

### 1.1 What is a Lease?

A **lease** is a distributed lock with a **time-to-live (TTL)**. It allows one process to temporarily "own" a resource, preventing other processes from using it simultaneously.

```
Process A wants to take a lease on "resource:job-123"
    │
    ▼
┌─────────────────────────────────────────────┐
│              REDIS LEASE                      │
│                                                │
│  SET resource:job-123 "process-A" NX EX 30    │
│  └──────────────┬──────────────────────┘      │
│                 │                              │
│          ┌──────┴──────┐                      │
│          │  Success?    │                      │
│          └──────┬──────┘                      │
│             ┌───┴───┐                         │
│             ▼       ▼                         │
│         ┌──────┐ ┌──────┐                    │
│         │ Yes  │ │ No   │                    │
│         └──┬───┘ └──┬───┘                    │
│            ▼        ▼                         │
│      Execute     Wait/Retry                   │
│      (30s TTL)   (lease held by B)            │
└─────────────────────────────────────────────┘
```

### 1.2 How It Works

```python
import redis.asyncio as redis
import uuid
import time
from typing import Optional

class RedisLease:
    """
    Distributed lease using Redis.
    
    Key concepts:
    - NX: Only set if key doesn't exist (exclusive creation)
    - EX: Set TTL in seconds (auto-release on crash)
    - Owner ID: Unique identifier (prevents accidental release)
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    async def acquire(
        self, 
        resource: str, 
        ttl: int = 30,
        owner_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Acquire a lease on a resource.
        
        Args:
            resource: The resource to lock (e.g., "job:123")
            ttl: Time-to-live in seconds
            owner_id: Unique owner identifier (auto-generated if None)
            
        Returns:
            owner_id if acquired, None if already held
        """
        owner_id = owner_id or str(uuid.uuid4())
        key = f"lease:{resource}"
        
        # SET NX EX — Atomic operation
        acquired = await self.redis.set(key, owner_id, nx=True, ex=ttl)
        
        if acquired:
            return owner_id
        return None
    
    async def release(self, resource: str, owner_id: str) -> bool:
        """
        Release a lease (only if we own it).
        
        Uses Lua script for atomic check-and-delete.
        """
        key = f"lease:{resource}"
        
        # Lua script: check ownership, then delete
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        end
        return 0
        """
        
        released = await self.redis.eval(lua_script, 1, key, owner_id)
        return released == 1
    
    async def renew(self, resource: str, owner_id: str, ttl: int = 30) -> bool:
        """
        Renew a lease (extend TTL) — only if we own it.
        
        Critical for long-running operations.
        """
        key = f"lease:{resource}"
        
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("EXPIRE", KEYS[1], ARGV[2])
        end
        return 0
        """
        
        renewed = await self.redis.eval(lua_script, 1, key, owner_id, ttl)
        return renewed == 1
    
    async def get_owner(self, resource: str) -> Optional[str]:
        """Check who currently holds the lease."""
        key = f"lease:{resource}"
        owner = await self.redis.get(key)
        return owner.decode() if owner else None
```

### 1.3 Production Usage: Job Scheduler with Leases

```python
class LeasedJobWorker:
    """
    Distributes jobs across multiple workers using Redis leases.
    Each job is a "resource" that one worker leases exclusively.
    """
    
    def __init__(self, redis_client: redis.Redis, worker_id: str):
        self.lease = RedisLease(redis_client)
        self.worker_id = worker_id
        self.active_leases = {}  # Track what we're working on
    
    async def try_claim_job(self, job_id: str) -> bool:
        """Try to claim a job by acquiring its lease."""
        owner = await self.lease.acquire(
            resource=f"job:{job_id}",
            ttl=60,
            owner_id=self.worker_id
        )
        
        if owner:
            self.active_leases[job_id] = {
                "owner": owner,
                "acquired_at": time.time(),
                "renewal_task": asyncio.create_task(
                    self._keep_alive(job_id)
                )
            }
            return True
        return False
    
    async def _keep_alive(self, job_id: str):
        """Background task: renew lease while job is running."""
        while job_id in self.active_leases:
            await asyncio.sleep(15)  # Renew every 15s
            owner = self.active_leases[job_id]["owner"]
            renewed = await self.lease.renew(
                resource=f"job:{job_id}",
                owner_id=owner,
                ttl=60
            )
            if not renewed:
                print(f"⚠️ Lost lease on job {job_id}!")
                break
    
    async def complete_job(self, job_id: str):
        """Complete a job and release the lease."""
        if job_id in self.active_leases:
            info = self.active_leases[job_id]
            info["renewal_task"].cancel()
            await self.lease.release(
                resource=f"job:{job_id}",
                owner_id=info["owner"]
            )
            del self.active_leases[job_id]
```

### 1.4 Lease vs Other Distributed Locking

| Method | Atomic | TTL | Fault-tolerant | Use Case |
|--------|--------|-----|---------------|----------|
| **Redis SET NX EX** | ✅ | ✅ | ✅ (auto-expire) | Most common, simple |
| **Redlock** | ✅ | ✅ | ✅ (quorum) | Critical, multi-node safety |
| **PostgreSQL advisory lock** | ✅ | ❌ | ❌ (session-based) | DB-centric systems |
| **ZooKeeper ephemeral node** | ✅ | ✅ | ✅ | Coordination-heavy systems |
| **etcd lease** | ✅ | ✅ | ✅ | Kubernetes-native |

---

## 2. SEARCH ENGINE: MISSPELLING HANDLING

### 2.1 The Problem

```
User types: "Harry Poter"  →  Intent: "Harry Potter"
User types: "recieve"      →  Intent: "receive"
User types: "Califonia"    →  Intent: "California"
```

A search engine must **correct misspellings** while still showing relevant results.

### 2.2 Algorithm: How It Works

```
User Query: "Harry Poter"
    │
    ▼
┌─────────────────────────────────────────────┐
│             SPELL CORRECTION                  │
│                                                │
│  1. Tokenize: ["Harry", "Poter"]              │
│                                                │
│  2. For each token:                            │
│     ├── Exact match in index? → Use it        │
│     ├── Fuzzy match (Levenshtein distance)    │
│     │   └── "Poter" → "Potter" (dist=1)      │
│     ├── Phonetic match (Soundex/Metaphone)    │
│     │   └── "Poter" → "Potter" (same sound)  │
│     └── N-gram overlap?                       │
│         └── "Poter" → "Potter" (4/6 char match)│
│                                                │
│  3. Suggest correction: "Showing results for  │
│     'Harry Potter'. Search instead for 'Poter'"│
└─────────────────────────────────────────────┘
```

### 2.3 Levenshtein Distance Implementation

```python
def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Compute the Levenshtein (edit) distance between two strings.
    
    Operations: insert, delete, substitute (each costs 1)
    
    Example:
    "Poter" → "Potter"
    - Insert 't' at position 4 → cost 1
    """
    m, n = len(s1), len(s2)
    
    # Use single row for memory efficiency
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    
    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,          # Deletion
                curr[j - 1] + 1,      # Insertion
                prev[j - 1] + cost    # Substitution
            )
        prev, curr = curr, prev
    
    return prev[n]

# ─── Efficient Fuzzy Search ───────────────────────

class FuzzySearch:
    """
    Efficient fuzzy search using BK-tree (Burkhard-Keller tree).
    Instead of comparing against ALL words (O(n)), 
    BK-tree narrows to a subset (O(log n)).
    """
    
    def __init__(self):
        self.words = []
        self.bk_tree = None
    
    def build_index(self, words: list):
        """Build BK-tree from a dictionary of words."""
        self.words = words
        if not words:
            return
        
        self.bk_tree = BKTreeNode(words[0])
        for word in words[1:]:
            self._insert(self.bk_tree, word)
    
    def _insert(self, node: 'BKTreeNode', word: str):
        distance = levenshtein_distance(node.word, word)
        if distance not in node.children:
            node.children[distance] = BKTreeNode(word)
        else:
            self._insert(node.children[distance], word)
    
    def search(self, query: str, max_distance: int = 2) -> list:
        """
        Find all words within max_distance of the query.
        Performance: O(log n) vs O(n) for brute force.
        """
        if not self.bk_tree:
            return []
        
        results = []
        self._search(self.bk_tree, query, max_distance, results)
        return sorted(results, key=lambda x: x[1])  # Sort by distance
    
    def _search(self, node: 'BKTreeNode', query: str, 
                max_dist: int, results: list):
        distance = levenshtein_distance(node.word, query)
        
        if distance <= max_dist:
            results.append((node.word, distance))
        
        # Only search children within distance range
        for d in range(max(0, distance - max_dist), distance + max_dist + 1):
            if d in node.children:
                self._search(node.children[d], query, max_dist, results)

class BKTreeNode:
    def __init__(self, word: str):
        self.word = word
        self.children = {}
```

### 2.4 Autocorrect Implementation

```python
class Autocorrect:
    """
    Full autocorrect system combining multiple strategies.
    """
    
    def __init__(self, dictionary: list):
        self.dictionary = set(dictionary)
        self.fuzzy_searcher = FuzzySearch()
        self.fuzzy_searcher.build_index(dictionary)
        
        # Build n-gram index for faster lookup
        self.ngram_index = self._build_ngram_index(dictionary)
    
    def correct(self, word: str) -> str:
        """Correct a misspelled word."""
        
        # Strategy 1: Exact match
        if word.lower() in self.dictionary:
            return word
        
        # Strategy 2: Fuzzy match (Levenshtein distance ≤ 2)
        fuzzy_results = self.fuzzy_searcher.search(word, max_distance=2)
        if fuzzy_results:
            return fuzzy_results[0][0]  # Return closest match
        
        # Strategy 3: N-gram overlap
        ngram_matches = self._ngram_match(word, threshold=0.6)
        if ngram_matches:
            return ngram_matches[0][0]
        
        # Strategy 4: Phonetic match (Soundex)
        phonetic = self._soundex(word)
        phonetic_matches = self._soundex_match(phonetic)
        if phonetic_matches:
            return phonetic_matches[0]
        
        # No correction found
        return word
    
    def suggest(self, query: str, max_suggestions: int = 5) -> list:
        """
        Suggest corrections for a multi-word query.
        
        "Harry Poter" → ["Harry Potter", "Harry Porter"]
        """
        tokens = query.split()
        suggestions = []
        
        for i, token in enumerate(tokens):
            corrected = self.correct(token)
            if corrected != token:
                alt_query = tokens.copy()
                alt_query[i] = corrected
                suggestions.append(" ".join(alt_query))
        
        return suggestions[:max_suggestions]
    
    def _build_ngram_index(self, words: list, n: int = 3) -> dict:
        """Build trigram index for efficient fuzzy matching."""
        index = {}
        for word in words:
            grams = self._get_ngrams(word, n)
            for gram in grams:
                if gram not in index:
                    index[gram] = []
                index[gram].append(word)
        return index
    
    def _get_ngrams(self, word: str, n: int = 3) -> set:
        """Get n-grams with padding."""
        padded = f"^{word}$"
        return {padded[i:i+n] for i in range(len(padded) - n + 1)}
    
    def _ngram_match(self, word: str, threshold: float = 0.5) -> list:
        """Find words with high n-gram overlap."""
        word_grams = self._get_ngrams(word)
        candidates = set()
        
        for gram in word_grams:
            if gram in self.ngram_index:
                candidates.update(self.ngram_index[gram])
        
        scored = []
        for candidate in candidates:
            cand_grams = self._get_ngrams(candidate)
            overlap = len(word_grams & cand_grams)
            score = overlap / max(len(word_grams), len(cand_grams))
            if score >= threshold:
                scored.append((candidate, score))
        
        return sorted(scored, key=lambda x: -x[1])
    
    def _soundex(self, word: str) -> str:
        """
        Soundex phonetic algorithm.
        
        Converts words to a code based on how they sound.
        Example: "Robert" → R163, "Rupert" → R163
        """
        word = word.upper()
        code = word[0]
        
        mapping = {
            'B': '1', 'F': '1', 'P': '1', 'V': '1',
            'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 
            'S': '2', 'X': '2', 'Z': '2',
            'D': '3', 'T': '3',
            'L': '4',
            'M': '5', 'N': '5',
            'R': '6',
        }
        
        last_code = mapping.get(word[0], '')
        for char in word[1:]:
            if char in 'AEIOUYHW':
                last_code = ''
                continue
            
            code_char = mapping.get(char, '')
            if code_char and code_char != last_code:
                code += code_char
                last_code = code_char
        
        return code + '000'  # Pad with zeros

# ─── Demo: Autocorrect in Action ──────────────────

def demo_autocorrect():
    # Build dictionary
    dictionary = [
        "harry", "potter", "hermione", "granger", "hogwarts",
        "ron", "weasley", "voldemort", "dumbledore", "snape",
        "receive", "believe", "achieve", "perceive",
        "california", "colorado", "connecticut",
        "definitely", "separate", "necessary", "accommodate",
    ]
    
    corrector = Autocorrect(dictionary)
    
    test_cases = [
        "Harry Poter",
        "recieve",
        "Califonia",
        "seperate",
        "definately",
        "beleive",
    ]
    
    for query in test_cases:
        suggestions = corrector.suggest(query)
        print(f"Input: '{query}'")
        print(f"  Suggestions: {suggestions}")
        print()

# Output:
# Input: 'Harry Poter'
#   Suggestions: ['Harry Potter']
#
# Input: 'recieve'
#   Suggestions: ['receive']
#
# Input: 'Califonia'
#   Suggestions: ['California']
```

---

## 3. ELASTICSEARCH — HOW IT WORKS

### 3.1 Architecture Overview

```
                     ┌──────────────────┐
                     │    Client / API    │
                     └────────┬─────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   ┌──────────┐         ┌──────────┐         ┌──────────┐
   │  Node 1   │         │  Node 2   │         │  Node 3   │
   │            │         │            │         │            │
   │ ┌────────┐ │         │ ┌────────┐ │         │ ┌────────┐ │
   │ │Index A │ │         │ │Index A │ │         │ │Index B │ │
   │ │Shard 1 │ │         │ │Shard 2 │ │         │ │Shard 1 │ │
   │ │(Primary)││         │ │(Replica)││         │ │(Primary)││
   │ └────────┘ │         │ └────────┘ │         │ └────────┘ │
   │ ┌────────┐ │         │ ┌────────┐ │         │ ┌────────┐ │
   │ │Index B │ │         │ │Index A │ │         │ │Index A │ │
   │ │Shard 2 │ │         │ │Shard 1 │ │         │ │Shard 1 │ │
   │ │(Replica)││         │ │(Primary)││         │ │(Replica)││
   │ └────────┘ │         │ └────────┘ │         │ └────────┘ │
   └────────────┘         └────────────┘         └────────────┘
```

### 3.2 Core Concepts

| Concept | Description | Analogy |
|---------|-------------|---------|
| **Cluster** | Collection of nodes (servers) | A data center |
| **Node** | Single Elasticsearch instance | A server in the data center |
| **Index** | Collection of documents | A database table |
| **Shard** | Horizontal partition of an index | A partition of a table |
| **Replica** | Copy of a shard for redundancy | A backup partition |
| **Document** | A JSON record | A database row |
| **Mapping** | Schema definition for documents | Table schema |
| **Inverted Index** | Maps terms → documents | Book index at the back |

### 3.3 Inverted Index — The Core Data Structure

The **inverted index** is what makes Elasticsearch fast. Instead of scanning every document, it stores a mapping from each term to the documents containing it.

```
Documents:
Doc 1: "Harry Potter and the Sorcerer's Stone"
Doc 2: "Harry Potter and the Chamber of Secrets"
Doc 3: "The Lord of the Rings"

Inverted Index:
"harry"    → [Doc 1, Doc 2]
"potter"   → [Doc 1, Doc 2]
"sorcerer" → [Doc 1] 
"chamber"  → [Doc 2]
"lord"     → [Doc 3]
"rings"    → [Doc 3]

Search: "Harry Potter"
  → Look up "harry" → [Doc 1, Doc 2]
  → Look up "potter" → [Doc 1, Doc 2]
  → Intersection → [Doc 1, Doc 2]
  → Score by relevance (TF-IDF / BM25)
```

### 3.4 Text Analysis Pipeline

```
Input Text: "Harry Potter and the Chamber of Secrets"
    │
    ▼
┌─────────────────────────────────────────────┐
│           ANALYSIS PIPELINE                   │
│                                                │
│  1. Character Filter                           │
│     └─ Remove HTML tags, convert &amp; → &     │
│                                                │
│  2. Tokenizer                                  │
│     └─ Split into tokens: ["Harry", "Potter",  │
│         "and", "the", "Chamber", "of",         │
│         "Secrets"]                              │
│                                                │
│  3. Token Filters                              │
│     ├─ Lowercase → ["harry", "potter", ...]   │
│     ├─ Stop words → ["harry", "potter",        │
│     │                "chamber", "secrets"]     │
│     ├─ Stemming → ["harri", "pott", ...]      │
│     └─ Synonyms → {"harry" → "potter"}        │
│                                                │
│  Output: ["harri", "pott", "chamber", "secret"]│
└─────────────────────────────────────────────┘
```

### 3.5 Search Scoring: BM25

```python
import math

class BM25Scorer:
    """
    BM25 (Best Matching 25): The default relevance scoring algorithm in Elasticsearch.
    
    Key features:
    - Term frequency (TF): More occurrences → higher score (diminishing returns)
    - Inverse document frequency (IDF): Rare terms → higher weight
    - Field length normalization: Shorter fields → more significant matches
    """
    
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        """
        k1: Controls term frequency saturation (default 1.2)
            Higher = more weight on frequency
        b:  Controls length normalization (default 0.75)
            b=0: No length normalization
            b=1: Full length normalization
        """
        self.k1 = k1
        self.b = b
    
    def score(self, term: str, document: str, 
              avg_doc_length: float, total_docs: int, 
              docs_with_term: int) -> float:
        """
        Compute BM25 score for a term in a document.
        
        BM25(t, d) = IDF(t) × (TF(t,d) × (k1 + 1)) / (TF(t,d) + k1 × (1 - b + b × |d|/avgdl))
        """
        tf = document.count(term)  # Term frequency in this doc
        doc_length = len(document)
        
        # IDF component
        idf = math.log(1 + (total_docs - docs_with_term + 0.5) / (docs_with_term + 0.5))
        
        # TF component with saturation and length normalization
        tf_component = (tf * (self.k1 + 1)) / (
            tf + self.k1 * (1 - self.b + self.b * doc_length / avg_doc_length)
        )
        
        return idf * tf_component
```

### 3.6 Elasticsearch Query: Fuzzy Search Implementation

```json
// Fuzzy search for misspellings
GET /books/_search
{
  "query": {
    "match": {
      "title": {
        "query": "Harry Poter",
        "fuzziness": "AUTO",  // Auto-calculate edit distance
        "operator": "or",
        "minimum_should_match": "70%"
      }
    }
  }
}

// Autocomplete (edge n-grams)
PUT /books
{
  "settings": {
    "analysis": {
      "analyzer": {
        "autocomplete_analyzer": {
          "tokenizer": "standard",
          "filter": ["lowercase", "autocomplete_filter"]
        }
      },
      "filter": {
        "autocomplete_filter": {
          "type": "edge_ngram",
          "min_gram": 1,
          "max_gram": 20
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "autocomplete_analyzer",
        "search_analyzer": "standard"
      }
    }
  }
}

// Phonetic search (Soundex/Metaphone)
PUT /books
{
  "settings": {
    "analysis": {
      "filter": {
        "phonetic_filter": {
          "type": "phonetic",
          "encoder": "double_metaphone"
        }
      },
      "analyzer": {
        "phonetic_analyzer": {
          "tokenizer": "standard",
          "filter": ["lowercase", "phonetic_filter"]
        }
      }
    }
  }
}
```

### 3.7 Implementation: Elasticsearch Client for Search

```python
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search, Q

class SearchEngine:
    """
    Production search engine with autocorrect and fuzzy search.
    """
    
    def __init__(self, hosts: list = ["http://localhost:9200"]):
        self.es = Elasticsearch(hosts)
        self.autocorrect = Autocorrect(self._load_dictionary())
    
    def search(self, query: str, index: str = "books", 
               size: int = 10) -> dict:
        """Search with automatic fallback to fuzzy."""
        
        # Step 1: Try exact search first
        exact_results = self._exact_search(query, index, size)
        
        if exact_results["hits"]["total"]["value"] > 0:
            return exact_results
        
        # Step 2: Apply autocorrect
        corrected = self.autocorrect.correct(query)
        if corrected != query:
            fuzzy_results = self._fuzzy_search(corrected, index, size)
            fuzzy_results["did_you_mean"] = corrected
            return fuzzy_results
        
        # Step 3: Fuzzy search with original query
        fuzzy_results = self._fuzzy_search(query, index, size)
        fuzzy_results["did_you_mean"] = None
        return fuzzy_results
    
    def _exact_search(self, query: str, index: str, size: int) -> dict:
        s = Search(using=self.es, index=index)
        s = s.query("match", title={"query": query, "operator": "and"})
        s = s.extra(size=size)
        return s.execute().to_dict()
    
    def _fuzzy_search(self, query: str, index: str, size: int) -> dict:
        s = Search(using=self.es, index=index)
        s = s.query(Q({
            "match": {
                "title": {
                    "query": query,
                    "fuzziness": "AUTO",
                    "operator": "or",
                    "minimum_should_match": "60%"
                }
            }
        }))
        s = s.extra(size=size)
        return s.execute().to_dict()
    
    def suggest(self, query: str, index: str = "books") -> list:
        """Get search suggestions using completion suggester."""
        s = Search(using=self.es, index=index)
        s = s.suggest("title_suggest", query, completion={
            "field": "title_suggest",
            "size": 5,
            "fuzzy": {
                "fuzziness": 2
            }
        })
        response = s.execute()
        return response.suggest.title_suggest[0].options
    
    def _load_dictionary(self) -> list:
        """Load dictionary from Elasticsearch index for autocorrect."""
        # Aggregation to get all unique terms
        s = Search(using=self.es, index="books")
        s.aggs.bucket("all_titles", "terms", field="title.keyword", size=10000)
        response = s.execute()
        
        return [
            bucket.key 
            for bucket in response.aggregations.all_titles.buckets
        ]
```

---

## 4. SUMMARY: SEARCH ARCHITECTURE

```
User Query: "Harry Poter"
    │
    ▼
┌─────────────────────────────────────────────┐
│            QUERY PROCESSING                   │
│                                                │
│  1. Tokenize & Normalize                       │
│     ├─ Lowercase: "harry poter"               │
│     ├─ Stop word removal                      │
│     └─ Stemming                               │
│                                                │
│  2. Search Execution                           │
│     ├─ Exact match (OR query)                 │
│     ├─ Fuzzy match (Levenshtein distance)     │
│     ├─ Phonetic match (Soundex/Metaphone)     │
│     └─ N-gram match (trigrams)               │
│                                                │
│  3. Scoring (BM25)                             │
│     ├─ TF × IDF × length norm                │
│     └─ Sort by relevance score                │
│                                                │
│  4. Post-processing                            │
│     ├─ Spelling correction                    │
│     │   └─ "Showing results for: Harry Potter"│
│     ├─ Query suggestions                      │
│     └─ Result deduplication                   │
│                                                │
│  5. Response                                   │
│     └─ Return results + metadata              │
└─────────────────────────────────────────────┘
```

---

> **Next:** This concludes the Agents module. See [Job Scheduling Design](../../low-level-design/job-scheduling-system/NEW_AIRFLOW_LIKE_DESIGN.md) for the Airflow-like job scheduler LLD.
