# 🧠 Search Platform LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![](search-platform-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What's being searched? (Documents, products?) What ranking strategy? (TF-IDF, recency, popularity?) Fuzzy search? Autocomplete?

## Phase 1: Identify the Nouns

> *"Documents are indexed by tokens. Users search with queries. Results are ranked by relevance and sorted."*

| Noun | Decision | Why |
|------|----------|-----|
| Document | @dataclass | Structured data with fields |
| InvertedIndex | Regular Class | Core data structure: token → doc → count |
| Tokenizer | Regular | Text processing (stop words, stemming) |
| RankingStrategy | ABC | Strategy for ranking results |
| FuzzyMatcher | ABC | Levenshtein distance for typos |
| QueryParser | Regular | Parses operators (+, -, quotes) |
| SearchService | Facade | Main entry point |
| MatchType / SortOrder | Enum | Search configuration |

## Phase 2: Enums First

```python
class MatchType(Enum):   EXACT, PREFIX, FUZZY, REGEX, SEMANTIC
class SortOrder(Enum):   RELEVANCE, DATE, POPULARITY, RATING
```

## Phase 3: dataclass vs `__init__`

- **`Document`**: `@dataclass` — pure data with many fields, auto-generated defaults
- **`InvertedIndex`**: Regular — the core data structure with complex logic
- **`Tokenizer`**: Regular — has state (stop words set)
- **`SearchService`**: Regular — orchestrates all components

**`Document` is a textbook dataclass** — it has many fields, default values, needs `__hash__`, and has no behavior.

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Tokenize text | `Tokenizer.tokenize()` | Handles lowercasing, stop words |
| Stem tokens | `Tokenizer.stem()` | Reduces words to roots |
| Build index | `InvertedIndex.add_document()` | Maps tokens to documents |
| Search tokens | `InvertedIndex.search_token()` | Returns matching doc IDs with counts |
| Rank results | `RankingStrategy.rank()` | Strategy for ordering |
| Parse query operators | `QueryParser.parse()` | Handles +, -, "quotes" |
| Fuzzy match | `FuzzyMatcher.match()` | Levenshtein distance |
| Orchestrate search | `SearchService.search()` | Parser → Index → Ranking |

## Phase 5: Inverted Index Structure

```python
_index: Dict[str, Dict[str, int]]
#   token   ->  doc_id -> count
# "python"  ->  {"doc1": 3, "doc4": 2}
```

This is the **fundamental data structure** of search engines. The tokenizer feeds into it, and the ranking algorithm reads from it.

## Phase 6: Ranking Strategy (Decorator Pattern)

```python
class RecencyBoostRanking(RankingStrategy):
    def __init__(self, base: RankingStrategy):
        self._base = base
    def rank(self, results, query, index):
        boost recent docs
        return self._base.rank(scored, query, index)
```

You can compose strategies:
```python
ranking = RecencyBoostRanking(
    PopularityRanking(
        TfIdfRanking()
    )
)
```

## Phase 7: Fuzzy Search Fallback

When exact search returns no results, fall back to fuzzy matching:
```python
if not matches and self._fuzzy:
    for doc in index.get_all_documents():
        if self._fuzzy.match(term, doc.title):
            scores[doc.doc_id] += 1
```

## Phase 8: Quick Checklist

✅ **Inverted Index:** Core search data structure is efficient
✅ **Strategy Pattern:** Ranking, fuzzy matching are swappable
✅ **Decorator Pattern:** Rankings can be composed
✅ **SRP:** Tokenizer, Index, Parser, Ranking are all separate
✅ **Encapsulation:** Document data is structured with dataclass
