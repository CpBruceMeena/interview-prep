# Search Platform — Implementation

> Python 3.10+, stdlib only. An in-memory full-text search engine: analyzer, positional inverted index, BM25/TF-IDF scoring, boolean + phrase queries, typo tolerance, autocomplete, and thread-safe indexing.

---

## 🏛️ Request Flow

```
index(doc) ─▶ Analyzer ─▶ InvertedIndex.upsert ─▶ postings[term][doc_id] = Posting(positions per field)
                                                   forward[doc_id] = {terms}      (for delete/update)
                                                   doc_len[doc_id], N, avgdl      (for BM25)

search(q) ─▶ QueryParser (same Analyzer) ─▶ Query(should, must, must_not, phrases)
          ─▶ fuzzy-expand SHOULD terms with no postings
          ─▶ candidates: ∩ MUST postings (smallest first)  or  ∪ SHOULD postings
          ─▶ − MUST_NOT, category filter, phrase check on positions
          ─▶ score = Σ term scores (Scorer) × Π boosts (Boost)
          ─▶ heapq.nlargest(limit)
```

---

## 📦 Classes

| Class | Role | Pattern |
|-------|------|---------|
| `Document` | Frozen dataclass; update = re-index with the same `doc_id` | Value object |
| `Analyzer`, `light_stem` | Lowercase → split on non-alphanumerics → drop stop words (keeping positions) → stem | — |
| `QueryParser`, `Query` | `term` = SHOULD, `+term` = MUST, `-term` = MUST_NOT, `"a b"` = phrase | Interpreter (tiny) |
| `InvertedIndex`, `Posting` | `term → doc_id → positions per field`; forward index; length stats | — |
| `Scorer` → `BM25Scorer`, `TfIdfScorer` | Per-term relevance | **Strategy** |
| `Boost` → `RecencyBoost`, `PopularityBoost` | Multiplicative, composable non-text signals | **Strategy** (list, composed) |
| `levenshtein`, `allowed_edits` | Bounded edit distance; fuzziness by term length | — |
| `SearchEngine` | Index/delete/search/suggest under one lock | **Facade** |

---

## 🧩 Key Design Decisions

| Decision | Why |
|----------|-----|
| **One analyzer for index and query** | Matching only works if both sides normalise identically. The old code tokenized query terms differently from document text (no punctuation split, stemming of whole tags like `design-patterns`), so many queries could never match. |
| **IDF is per term** (`df = len(postings[term])`) | The previous `TfIdfRanking` computed "how many vocabulary terms this *document* contains" and called it document frequency. That isn't IDF at all. |
| **BM25 by default** | TF saturation (`k1`) stops keyword stuffing; length normalisation (`b`) stops long documents winning by size. Lucene's IDF form `ln(1 + (N − df + 0.5)/(df + 0.5))` never goes negative. |
| **Field weights inside TF** (title 3, tags 2, body 1) | A simplified BM25F: weighted term counts are summed before saturation, so a title hit counts more but still saturates. Document length is weighted the same way. |
| **Positional postings** | Needed for phrase queries. Stop words keep their position, so `"design of systems"` doesn't match "design systems". Tags get a 100-position gap between them (Lucene's `position_increment_gap`), so a phrase can't span two tags. |
| **Forward index** | `delete`/re-index touch only that document's terms, O(terms in doc) instead of O(vocabulary). Empty posting lists are dropped so the vocabulary doesn't fill with dead terms. |
| **MUST intersect smallest-first** | Intersection cost is bounded by the shortest posting list; the early exit on empty saves the rest. |
| **Fuzzy only for terms with no postings** | Typo tolerance without diluting precise queries. Expansions score at `fuzzy_penalty` (0.5). Edit budget follows Elasticsearch's `AUTO`: 0 for ≤2 chars, 1 for 3–5, 2 beyond. |
| **Boosts multiply, with `now` injected** | Recency uses exponential decay with a half-life (smooth, no cliff at "7 days"); popularity is logarithmic. Injecting `now` makes ranking reproducible in tests. |
| **Search has no side effects** | The previous version incremented `popularity` on every search hit, so the same query returned different rankings each time. |
| **One lock** | Writers and readers serialise, so a search never sees a half-indexed document. Simple and correct; see "Where to extend" for the scalable version. |

---

## 🔧 Where to Extend

| New requirement | Change |
|-----------------|--------|
| Better stemming / other languages | Pass a different `stemmer` (Porter/Snowball) or a different `Analyzer`. Re-index everything afterwards: index and query must use the same analyzer. |
| Synonyms ("k8s" → "kubernetes") | Expand in the query analyzer (cheap to change, no re-index), not at index time. |
| Facet counts | Count `doc.category` over the candidate set before taking top-k. |
| Pagination | `nlargest(offset + limit)` then slice, and cap `offset` (deep paging is O(offset) per shard). Use `search_after` (last sort key) for deep scrolling. |
| Read-heavy concurrency | Replace the single lock with immutable **segments**: writers build a new small segment, readers search a snapshot list of segments, a background merge combines them. That's Lucene's design, and it gives lock-free reads. |
| Prefix search in queries (`kube*`) | Range-scan the sorted vocabulary (same `bisect` trick as `suggest`). |
| Learning-to-rank | Keep BM25 as the cheap first stage over all candidates, re-rank the top ~100 with a model. |

---

## 📦 Full Source Code

<!-- source: search_platform.py -->
```python
"""
Search Platform — Low Level Design
==================================

An in-memory full-text search engine:

  * Analyzer: lowercase -> split on non-alphanumerics -> drop stop words -> light
    stemming. The SAME analyzer runs at index time and query time, which is the
    single most important rule in search (otherwise "Databases" never matches
    "database").
  * Positional inverted index with per-field postings (title, tags, body), a
    forward index for O(terms-in-doc) delete/update, and the corpus statistics
    BM25 needs (N, document frequency, average document length).
  * Query language: plain terms are SHOULD (OR), +term is MUST, -term is
    MUST_NOT, "quoted phrase" is a MUST phrase checked against positions.
  * Scoring (Strategy): BM25 (default) or classic TF-IDF, with field weights.
  * Boosts (Strategy, composable): recency (exponential decay) and popularity.
  * Typo tolerance: a query term with no postings is expanded to vocabulary
    terms within edit distance 1-2, scored at a discount.
  * Autocomplete over surface words, ranked by document frequency.
  * Thread safety: one lock guards index mutation and search, so a search never
    sees a half-indexed document.

Run:   python3 search_platform.py
Test:  python3 -m unittest test_search_platform
"""

from __future__ import annotations

import bisect
import heapq
import math
import re
import threading
from abc import ABC, abstractmethod
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ════════════════════════════════════════════════════════════════════════
#  DOCUMENT
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Document:
    """Immutable: to change a document, index a new version with the same doc_id."""
    doc_id: str
    title: str
    body: str
    tags: Tuple[str, ...] = ()
    category: str = ""
    created_at: datetime = datetime(2000, 1, 1)
    popularity: int = 0


class SortOrder(Enum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    POPULARITY = "popularity"


@dataclass(frozen=True)
class SearchHit:
    doc: Document
    score: float


# ════════════════════════════════════════════════════════════════════════
#  ANALYZER — text -> terms
# ════════════════════════════════════════════════════════════════════════

DEFAULT_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "in", "is", "it", "of", "on", "or", "that", "the", "to", "was",
    "were", "will", "with",
})

_WORD = re.compile(r"[a-z0-9]+")

# Longest suffix first, so "ization" wins over "ion". "es" is deliberately
# absent because it mangles "databases" vs "database": "s" alone maps both to
# "database".
_SUFFIXES = ("ational", "ization", "ations", "ation", "ments", "ment", "ness",
             "ings", "ing", "ies", "ers", "er", "ed", "ly", "s")


def light_stem(word: str) -> str:
    """
    A deliberately tiny suffix stripper (not Porter). It conflates the common
    inflections an interviewer will try (patterns/pattern, indexing/index,
    designed/design). Guards: a plural "s" needs a 3-letter stem, every other
    suffix a 4-letter one, so "string" and "desing" are left alone instead of
    becoming "str" and "des".
    """
    if len(word) <= 3 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if not word.endswith(suffix):
            continue
        stem = word[: -len(suffix)]
        if len(stem) < (3 if suffix in ("s", "ies") else 4):
            continue
        if suffix == "ies":
            return stem + "y"                   # libraries -> library
        if suffix == "s" and stem.endswith(("s", "u")):
            return word                         # "class", "status" stay as they are
        if suffix in ("ing", "ings", "ed", "er", "ers") and stem[-1] == stem[-2] \
                and stem[-1] not in "aeioulsz":
            return stem[:-1]                    # running -> run, stopped -> stop
        return stem
    return word


@dataclass(frozen=True)
class Token:
    term: str           # normalised (stemmed) form, what the index stores
    surface: str        # lowercased original word, for autocomplete
    position: int       # word offset; stop words still consume a position


class Analyzer:
    def __init__(self, stop_words: Iterable[str] = DEFAULT_STOP_WORDS,
                 stemmer: Callable[[str], str] = light_stem) -> None:
        self._stop_words = frozenset(stop_words)
        self._stem = stemmer

    def analyze(self, text: str) -> List[Token]:
        tokens = []
        for position, word in enumerate(_WORD.findall(text.lower())):
            if word in self._stop_words:
                continue    # keep the gap: "design of systems" is not the phrase "design systems"
            tokens.append(Token(self._stem(word), word, position))
        return tokens

    def terms(self, text: str) -> List[str]:
        return [t.term for t in self.analyze(text)]


# ════════════════════════════════════════════════════════════════════════
#  QUERY PARSING
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Query:
    should: List[str] = field(default_factory=list)          # analyzed terms
    must: List[str] = field(default_factory=list)
    must_not: List[str] = field(default_factory=list)
    phrases: List[List[str]] = field(default_factory=list)   # each a term sequence (with gaps as None)

    @property
    def is_empty(self) -> bool:
        return not (self.should or self.must or self.phrases)


_QUERY_PART = re.compile(r'([+-]?)"([^"]*)"|(\S+)')


class QueryParser:
    """
    hello world        -> should: hello, world      (OR, ranked)
    +python -java      -> must: python, must_not: java
    "system design"    -> phrase (also MUST); also counts toward the score
    """

    def __init__(self, analyzer: Analyzer) -> None:
        self._analyzer = analyzer

    def parse(self, text: str) -> Query:
        q = Query()
        for m in _QUERY_PART.finditer(text):
            sign, phrase, word = m.group(1), m.group(2), m.group(3)
            if phrase is not None:
                tokens = self._analyzer.analyze(phrase)
                if sign == "-":
                    q.must_not.extend(t.term for t in tokens)
                elif len(tokens) == 1:
                    q.must.append(tokens[0].term)
                elif tokens:
                    q.phrases.append(self._with_gaps(tokens))
                continue
            sign, word = (word[0], word[1:]) if word[0] in "+-" and len(word) > 1 else ("", word)
            terms = self._analyzer.terms(word)
            {"+": q.must, "-": q.must_not}.get(sign, q.should).extend(terms)
        return q

    @staticmethod
    def _with_gaps(tokens: List[Token]) -> List[str]:
        """Encode stop-word gaps as '' so positions line up with the document."""
        out, start = [], tokens[0].position
        for t in tokens:
            out.extend([""] * (t.position - start - len(out)))
            out.append(t.term)
        return out


# ════════════════════════════════════════════════════════════════════════
#  INVERTED INDEX
# ════════════════════════════════════════════════════════════════════════

TAG_POSITION_GAP = 100      # same idea as Lucene's position_increment_gap


@dataclass
class Posting:
    """One term in one document: positions per field."""
    positions: Dict[str, List[int]] = field(default_factory=dict)

    def weighted_tf(self, weights: Dict[str, float]) -> float:
        return sum(weights[f] * len(p) for f, p in self.positions.items())


class InvertedIndex:
    """
    postings:  term -> {doc_id -> Posting}
    forward:   doc_id -> set of terms          (delete/update without scanning the vocabulary)
    doc_len:   doc_id -> weighted field length (BM25 length normalisation)

    Not thread-safe on its own; SearchEngine serialises access.
    """

    def __init__(self, analyzer: Analyzer, field_weights: Dict[str, float]) -> None:
        self._analyzer = analyzer
        self.field_weights = dict(field_weights)
        self.postings: Dict[str, Dict[str, Posting]] = defaultdict(dict)
        self._forward: Dict[str, Set[str]] = {}
        self._surface: Dict[str, Set[str]] = {}          # doc_id -> surface words (for autocomplete)
        self.docs: Dict[str, Document] = {}
        self.doc_len: Dict[str, float] = {}
        self._total_len = 0.0

    # ── writes ──
    def upsert(self, doc: Document) -> None:
        if doc.doc_id in self.docs:
            self.delete(doc.doc_id)
        fields = {"title": self._analyzer.analyze(doc.title),
                  "tags": self._analyze_tags(doc.tags),
                  "body": self._analyzer.analyze(doc.body)}
        terms: Set[str] = set()
        surface: Set[str] = set()
        length = 0.0
        for name, tokens in fields.items():
            length += self.field_weights[name] * len(tokens)
            for tok in tokens:
                posting = self.postings[tok.term].setdefault(doc.doc_id, Posting())
                posting.positions.setdefault(name, []).append(tok.position)
                terms.add(tok.term)
                surface.add(tok.surface)
        self.docs[doc.doc_id] = doc
        self._forward[doc.doc_id] = terms
        self._surface[doc.doc_id] = surface
        self.doc_len[doc.doc_id] = length
        self._total_len += length

    def _analyze_tags(self, tags: Sequence[str]) -> List[Token]:
        # Leave a large position gap between tags so a phrase can't match across
        # two of them: tags ("python", "design-patterns") must not match "python design".
        tokens: List[Token] = []
        for i, tag in enumerate(tags):
            base = i * TAG_POSITION_GAP
            tokens.extend(Token(t.term, t.surface, base + t.position)
                          for t in self._analyzer.analyze(tag))
        return tokens

    def delete(self, doc_id: str) -> bool:
        if doc_id not in self.docs:
            return False
        for term in self._forward.pop(doc_id):
            plist = self.postings[term]
            del plist[doc_id]
            if not plist:
                del self.postings[term]           # keep the vocabulary free of dead terms
        del self.docs[doc_id]
        del self._surface[doc_id]
        self._total_len -= self.doc_len.pop(doc_id)
        return True

    # ── reads ──
    @property
    def n_docs(self) -> int:
        return len(self.docs)

    @property
    def avg_len(self) -> float:
        return self._total_len / self.n_docs if self.n_docs else 0.0

    def df(self, term: str) -> int:
        plist = self.postings.get(term)
        return len(plist) if plist else 0

    def docs_with(self, term: str) -> Dict[str, Posting]:
        return self.postings.get(term, {})

    def surface_words(self, doc_id: str) -> Set[str]:
        return self._surface.get(doc_id, set())


# ════════════════════════════════════════════════════════════════════════
#  SCORING — Strategy
# ════════════════════════════════════════════════════════════════════════

class Scorer(ABC):
    @abstractmethod
    def score(self, tf: float, df: int, n_docs: int, doc_len: float, avg_len: float) -> float:
        """Contribution of one query term to one document."""


class BM25Scorer(Scorer):
    """
    idf(t)   = ln(1 + (N - df + 0.5) / (df + 0.5))         (Lucene's form; never negative)
    tf part  = tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))

    k1 caps how much repeating a term helps (saturation); b scales the length
    penalty (b=0: none, b=1: full). Defaults are the usual k1=1.2, b=0.75.
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b

    def score(self, tf, df, n_docs, doc_len, avg_len):
        if tf <= 0 or df == 0:
            return 0.0
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        norm = self.k1 * (1 - self.b + self.b * doc_len / avg_len) if avg_len else self.k1
        return idf * tf * (self.k1 + 1) / (tf + norm)


class TfIdfScorer(Scorer):
    """
    Log-scaled tf times smoothed idf:  (1 + ln tf) * (ln((1 + N) / (1 + df)) + 1)
    No length normalisation and no saturation, which is why BM25 usually wins.
    """

    def score(self, tf, df, n_docs, doc_len, avg_len):
        if tf <= 0 or df == 0:
            return 0.0
        return (1 + math.log(tf)) * (math.log((1 + n_docs) / (1 + df)) + 1)


# ════════════════════════════════════════════════════════════════════════
#  BOOSTS — Strategy, composable (score is multiplied by each boost)
# ════════════════════════════════════════════════════════════════════════

class Boost(ABC):
    @abstractmethod
    def factor(self, doc: Document) -> float:
        """Multiplier applied to the text-relevance score. 1.0 = neutral."""


class RecencyBoost(Boost):
    """
    Exponential decay: factor = 1 + weight * 0.5 ** (age_days / half_life_days).
    A brand-new doc gets (1 + weight), one half-life old gets (1 + weight/2).
    `now` is injected so results are reproducible.
    """

    def __init__(self, now: datetime, half_life_days: float = 30.0, weight: float = 0.5) -> None:
        self._now, self._half_life, self._weight = now, half_life_days, weight

    def factor(self, doc: Document) -> float:
        age_days = max(0.0, (self._now - doc.created_at).total_seconds() / 86_400)
        return 1 + self._weight * 0.5 ** (age_days / self._half_life)


class PopularityBoost(Boost):
    """factor = 1 + weight * log10(1 + popularity). Logarithmic, so 10x more
    views is a constant bump instead of drowning out relevance."""

    def __init__(self, weight: float = 0.1) -> None:
        self._weight = weight

    def factor(self, doc: Document) -> float:
        return 1 + self._weight * math.log10(1 + max(0, doc.popularity))


# ════════════════════════════════════════════════════════════════════════
#  FUZZY MATCHING
# ════════════════════════════════════════════════════════════════════════

def levenshtein(a: str, b: str, max_dist: Optional[int] = None) -> int:
    """
    Edit distance with two rows, O(len(a) * len(b)) time, O(min) space.
    With max_dist, stops early once every cell in a row exceeds it.
    """
    if len(a) < len(b):
        a, b = b, a
    if max_dist is not None and len(a) - len(b) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        if max_dist is not None and min(cur) > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def allowed_edits(term: str) -> int:
    """Same idea as Elasticsearch's fuzziness AUTO: 0 edits for 1-2 chars, 1 for 3-5, 2 beyond."""
    return 0 if len(term) <= 2 else 1 if len(term) <= 5 else 2


# ════════════════════════════════════════════════════════════════════════
#  SEARCH ENGINE — Facade
# ════════════════════════════════════════════════════════════════════════

DEFAULT_FIELD_WEIGHTS = {"title": 3.0, "tags": 2.0, "body": 1.0}


class SearchEngine:
    def __init__(self, analyzer: Optional[Analyzer] = None,
                 scorer: Optional[Scorer] = None,
                 boosts: Sequence[Boost] = (),
                 field_weights: Optional[Dict[str, float]] = None,
                 fuzzy: bool = True,
                 fuzzy_penalty: float = 0.5,
                 query_log_size: int = 1_000) -> None:
        self._analyzer = analyzer or Analyzer()
        self._index = InvertedIndex(self._analyzer, field_weights or DEFAULT_FIELD_WEIGHTS)
        self._parser = QueryParser(self._analyzer)
        self._scorer = scorer or BM25Scorer()
        self._boosts = list(boosts)
        self._fuzzy = fuzzy
        self._fuzzy_penalty = fuzzy_penalty
        self._lock = threading.Lock()
        self._query_log: deque = deque(maxlen=query_log_size)   # bounded
        self._suggest_df: Counter = Counter()      # surface word -> number of docs containing it
        self._suggest_sorted: List[str] = []       # sorted keys, rebuilt lazily for prefix lookup
        self._suggest_dirty = False

    # ── indexing ──
    def index(self, doc: Document) -> None:
        """Insert or replace (by doc_id). Atomic with respect to searches."""
        with self._lock:
            self._forget_surface(doc.doc_id)
            self._index.upsert(doc)
            self._suggest_df.update(self._index.surface_words(doc.doc_id))
            self._suggest_dirty = True

    def index_many(self, docs: Iterable[Document]) -> None:
        for doc in docs:
            self.index(doc)

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            self._forget_surface(doc_id)
            removed = self._index.delete(doc_id)
            self._suggest_dirty = self._suggest_dirty or removed
            return removed

    def _forget_surface(self, doc_id: str) -> None:
        old = self._index.surface_words(doc_id)
        if old:
            self._suggest_df.subtract(old)
            for word in old:
                if self._suggest_df[word] <= 0:
                    del self._suggest_df[word]

    # ── search ──
    def search(self, text: str, *, limit: int = 10, category: Optional[str] = None,
               sort: SortOrder = SortOrder.RELEVANCE) -> List[SearchHit]:
        query = self._parser.parse(text)
        with self._lock:
            hits = self._execute(query, limit, category, sort)
            self._query_log.append((text, len(hits)))
            return hits

    def explain_terms(self, text: str) -> Query:
        """What the parser and analyzer turned the query into (debugging aid)."""
        return self._parser.parse(text)

    def _execute(self, q: Query, limit: int, category: Optional[str],
                 sort: SortOrder) -> List[SearchHit]:
        if q.is_empty:
            return []
        idx = self._index

        # 1. Expand SHOULD terms that don't exist (typos) into near vocabulary terms.
        scored_terms: Dict[str, float] = {}             # term -> weight in the score
        for term in q.should:
            if idx.df(term):
                scored_terms[term] = 1.0
            elif self._fuzzy:
                for alt in self._fuzzy_expand(term):
                    scored_terms.setdefault(alt, self._fuzzy_penalty)
        must_terms = list(q.must) + [t for p in q.phrases for t in p if t]
        for term in must_terms:
            scored_terms[term] = 1.0

        # 2. Candidate set. MUST clauses intersect (smallest posting list first);
        #    otherwise SHOULD clauses union.
        if must_terms:
            lists = sorted((idx.docs_with(t) for t in set(must_terms)), key=len)
            candidates = set(lists[0])
            for plist in lists[1:]:
                candidates &= plist.keys()
                if not candidates:
                    return []
        else:
            candidates = set()
            for term in scored_terms:
                candidates |= idx.docs_with(term).keys()

        for term in q.must_not:
            candidates -= idx.docs_with(term).keys()
        if category is not None:
            candidates = {d for d in candidates if idx.docs[d].category == category}
        if q.phrases:
            candidates = {d for d in candidates if all(self._has_phrase(d, p) for p in q.phrases)}

        # 3. Score: sum of per-term scores, then multiplicative boosts.
        n, avg = idx.n_docs, idx.avg_len
        weights = idx.field_weights
        hits = []
        for doc_id in candidates:
            score = 0.0
            for term, w in scored_terms.items():
                posting = idx.docs_with(term).get(doc_id)
                if posting is not None:
                    score += w * self._scorer.score(posting.weighted_tf(weights), idx.df(term),
                                                    n, idx.doc_len[doc_id], avg)
            doc = idx.docs[doc_id]
            for boost in self._boosts:
                score *= boost.factor(doc)
            hits.append(SearchHit(doc, score))

        # 4. Top-k without sorting everything: O(m log k).
        if sort is SortOrder.NEWEST:
            key = lambda h: (h.doc.created_at, h.score, h.doc.doc_id)
        elif sort is SortOrder.POPULARITY:
            key = lambda h: (h.doc.popularity, h.score, h.doc.doc_id)
        else:
            key = lambda h: (h.score, h.doc.doc_id)
        return heapq.nlargest(limit, hits, key=key)

    def _fuzzy_expand(self, term: str) -> List[str]:
        """
        Linear scan of the vocabulary with a length pre-filter: O(V) distance
        checks. Fine for an LLD; at scale use a Levenshtein automaton over a
        sorted term dictionary (Lucene) or a BK-tree / SymSpell deletes index.
        """
        k = allowed_edits(term)
        if k == 0:
            return []
        out = [t for t in self._index.postings
               if abs(len(t) - len(term)) <= k and levenshtein(term, t, k) <= k]
        return sorted(out)

    def _has_phrase(self, doc_id: str, phrase: List[str]) -> bool:
        """
        True if the terms appear at consecutive positions (gaps '' match any
        word, i.e. a removed stop word) inside one field.
        """
        anchors = [(i, t) for i, t in enumerate(phrase) if t]
        first_off, first_term = anchors[0]
        first = self._index.docs_with(first_term).get(doc_id)
        if first is None:
            return False
        for fld, starts in first.positions.items():
            others = []
            for off, term in anchors[1:]:
                posting = self._index.docs_with(term).get(doc_id)
                others.append((off, set(posting.positions.get(fld, ())) if posting else set()))
            for p in starts:
                base = p - first_off
                if all(base + off in pos for off, pos in others):
                    return True
        return False

    # ── autocomplete ──
    def suggest(self, prefix: str, limit: int = 5) -> List[str]:
        """
        Words starting with `prefix`, most common (by document count) first.
        Prefix range found by binary search on a sorted word list:
        O(log V + matches). A trie, or precomputed top-k per prefix, avoids
        scanning all matches for very short prefixes.
        """
        prefix = prefix.lower().strip()
        if not prefix:
            return []
        with self._lock:
            if self._suggest_dirty:
                self._suggest_sorted = sorted(self._suggest_df)
                self._suggest_dirty = False
            lo = bisect.bisect_left(self._suggest_sorted, prefix)
            hi = bisect.bisect_left(self._suggest_sorted, prefix + "￿")
            matches = self._suggest_sorted[lo:hi]
            return heapq.nsmallest(limit, matches, key=lambda w: (-self._suggest_df[w], w))

    # ── stats ──
    def stats(self) -> Dict[str, float]:
        with self._lock:
            return {"documents": self._index.n_docs,
                    "terms": len(self._index.postings),
                    "avg_doc_len": round(self._index.avg_len, 2),
                    "queries_logged": len(self._query_log)}


# ════════════════════════════════════════════════════════════════════════
#  DEMO
# ════════════════════════════════════════════════════════════════════════

def sample_documents() -> List[Document]:
    return [
        Document("1", "Python Design Patterns",
                 "Learn the Singleton, Factory and Observer patterns in Python.",
                 ("python", "design-patterns", "oop"), "Programming", datetime(2026, 9, 20), 1500),
        Document("2", "System Design Interview Guide",
                 "A complete guide to system design interviews, including scalability and sharding.",
                 ("system-design", "interview"), "Interview Prep", datetime(2026, 8, 1), 2000),
        Document("3", "Microservices Architecture",
                 "Building scalable microservices with Docker and Kubernetes.",
                 ("microservices", "docker"), "Architecture", datetime(2026, 3, 10), 1200),
        Document("4", "Python for Data Science",
                 "NumPy, Pandas and scikit-learn tutorial for beginners in data science.",
                 ("python", "data-science"), "Data Science", datetime(2025, 5, 1), 3000),
        Document("5", "Database Design Fundamentals",
                 "Relational databases, indexing and query optimization techniques.",
                 ("database", "sql", "indexing"), "Databases", datetime(2025, 4, 15), 800),
        Document("6", "Designing Microservices",
                 "Advanced microservice patterns: sagas, outbox and the design of service boundaries.",
                 ("microservices", "patterns"), "Architecture", datetime(2026, 9, 30), 500),
    ]


def main() -> None:
    now = datetime(2026, 10, 1)
    engine = SearchEngine(boosts=[RecencyBoost(now), PopularityBoost()])
    engine.index_many(sample_documents())
    print(f"Indexed: {engine.stats()}")

    queries = [
        "python design",              # OR, ranked
        "+microservices patterns",    # MUST microservices, SHOULD patterns
        '"system design"',            # phrase
        "design -microservices",      # exclusion
        "databases",                  # stemming: databases -> database
        "desing paterns",             # typos -> design, pattern
    ]
    for q in queries:
        print(f"\nsearch {q!r}")
        for hit in engine.search(q, limit=3):
            print(f"  {hit.score:6.3f}  [{hit.doc.doc_id}] {hit.doc.title}")

    print("\nsearch 'design' in category Architecture, newest first")
    for hit in engine.search("design", category="Architecture", sort=SortOrder.NEWEST):
        print(f"  {hit.doc.created_at:%Y-%m-%d}  [{hit.doc.doc_id}] {hit.doc.title}")

    print(f"\nsuggest 'mi' -> {engine.suggest('mi')}")
    print(f"suggest 'py' -> {engine.suggest('py')}")

    engine.delete("1")
    print(f"\nafter deleting doc 1, 'singleton' -> {[h.doc.doc_id for h in engine.search('singleton')]}")
    print(f"stats: {engine.stats()}")


if __name__ == "__main__":
    main()
```
<!-- /source -->

---

## ▶️ How to Run

```bash
cd python-low-level-design/search-platform
python3 search_platform.py                    # demo
python3 -m unittest test_search_platform      # 27 tests, < 1 s
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
