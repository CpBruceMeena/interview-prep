# 📊 Elasticsearch: Architecture & Internals

> **Target:** Staff/Principal Engineer | **Focus:** Elasticsearch architecture, inverted index, BM25 scoring, analysis pipeline, and fuzzy search

---

## 1. ARCHITECTURE OVERVIEW

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

## 2. CORE CONCEPTS

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

## 3. INVERTED INDEX — The Core Data Structure

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

## 4. TEXT ANALYSIS PIPELINE

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

## 5. SEARCH SCORING: BM25

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

## 6. ELASTICSEARCH QUERY: Fuzzy Search Implementation

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

## 7. IMPLEMENTATION: Elasticsearch Client for Search

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
        s = Search(using=self.es, index=index)
        s.aggs.bucket("all_titles", "terms", field="title.keyword", size=10000)
        response = s.execute()
        
        return [
            bucket.key 
            for bucket in response.aggregations.all_titles.buckets
        ]
```

## 8. SEARCH ARCHITECTURE SUMMARY

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

> **Previous:** [Search Autocorrect & Misspelling Handling](12_SEARCH_AUTOCORRECT.md)
> **Next:** See [Job Scheduling Design](../../low-level-design/job-scheduling-system/NEW_AIRFLOW_LIKE_DESIGN.md) for the Airflow-like job scheduler LLD.
