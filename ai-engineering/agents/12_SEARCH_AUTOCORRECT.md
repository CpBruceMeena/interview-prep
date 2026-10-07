# 🔍 Search Engine: Misspelling Handling & Autocorrect

> **Target:** Staff/Principal Engineer | **Focus:** Search engine misspelling handling, autocorrect algorithms, Levenshtein distance, BK-tree, Soundex | **Reviewed:** October 2026

!!! tip "30-second answer"
    Spelling correction is **candidate generation + ranking**. Generate candidates cheaply (edit distance ≤ 2 via a BK-tree, Levenshtein automaton or SymSpell's precomputed deletes; n-gram overlap; phonetic codes), then rank them by how likely the user *meant* each one: the noisy-channel model, P(word) × P(typo | word), with word and query frequencies from your own query logs and context from neighbouring words. In production you rarely write this yourself: Elasticsearch/OpenSearch fuzzy queries and the term/phrase suggesters do it, and the product decision is when to silently auto-correct versus show "Did you mean…?".

---

## 1. THE PROBLEM

```
User types: "Harry Poter"  →  Intent: "Harry Potter"
User types: "recieve"      →  Intent: "receive"
User types: "Califonia"    →  Intent: "California"
```

A search engine must **correct misspellings** while still showing relevant results.

## 2. ALGORITHM: How It Works

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
│  3. Rank candidates by distance + frequency   │
│     (+ context: "harry potter" is a frequent  │
│      query, "harry porter" is not)            │
│                                                │
│  4. Suggest correction: "Showing results for  │
│     'Harry Potter'. Search instead for 'Poter'"│
└─────────────────────────────────────────────┘
```

## 3. LEVENSHTEIN DISTANCE IMPLEMENTATION

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
    
    # Two rows instead of the full (m+1) x (n+1) matrix: O(n) memory
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


def damerau_distance(s1: str, s2: str) -> int:
    """Optimal string alignment distance: Levenshtein + adjacent transposition.

    Typos are often swaps ("recieve" -> "receive"): Levenshtein counts that as 2,
    this counts it as 1. Lucene's fuzzy queries also count transpositions as 1
    by default. Note: OSA is not a true metric (no triangle inequality).
    """
    m, n = len(s1), len(s2)
    d = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        d[i][0] = i
    for j in range(n + 1):
        d[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)   # transposition
    return d[m][n]

# ─── Efficient Fuzzy Search ───────────────────────

class FuzzySearch:
    """
    Fuzzy search with a BK-tree (Burkhard-Keller tree).

    Works for any metric distance (it relies on the triangle inequality):
    at a node at distance d from the query, only children whose edge label
    lies in [d - k, d + k] can contain matches. That prunes a lot for small
    k, but it is NOT O(log n): with k = 2 a query typically still visits a
    sizeable fraction of the tree. Fine for dictionaries of ~10^5 words.
    """
    
    def __init__(self, distance=levenshtein_distance):
        self.distance = distance
        self.bk_tree = None
    
    def build_index(self, words: list):
        """Build BK-tree from a dictionary of words."""
        for word in words:
            if self.bk_tree is None:
                self.bk_tree = BKTreeNode(word)
            else:
                self._insert(self.bk_tree, word)
    
    def _insert(self, node: 'BKTreeNode', word: str):
        # Iterative to avoid deep recursion on large dictionaries
        while True:
            dist = self.distance(node.word, word)
            if dist == 0:
                return                      # duplicate
            child = node.children.get(dist)
            if child is None:
                node.children[dist] = BKTreeNode(word)
                return
            node = child
    
    def search(self, query: str, max_distance: int = 2) -> list:
        """Find all words within max_distance of the query, closest first."""
        if not self.bk_tree:
            return []
        results, stack = [], [self.bk_tree]
        while stack:
            node = stack.pop()
            dist = self.distance(node.word, query)
            if dist <= max_distance:
                results.append((node.word, dist))
            # Triangle inequality: only these children can be within range
            for d in range(max(1, dist - max_distance), dist + max_distance + 1):
                if d in node.children:
                    stack.append(node.children[d])
        return sorted(results, key=lambda x: x[1])

class BKTreeNode:
    def __init__(self, word: str):
        self.word = word
        self.children = {}
```

## 4. AUTOCORRECT IMPLEMENTATION

```python
from collections import Counter

class Autocorrect:
    """
    Autocorrect combining candidate generation and ranking.

    Candidate generation: edit distance (BK-tree), then n-grams, then phonetics.
    Ranking: smaller edit distance first, then higher word frequency. This is a
    crude version of the noisy-channel model P(correction) * P(typo | correction).
    Without frequency, ties are broken arbitrarily ("beleive" could become
    "receive" instead of "believe": both are 2 Levenshtein edits away).
    """
    
    def __init__(self, word_counts: dict):
        self.freq = Counter({w.lower(): c for w, c in word_counts.items()})
        self.dictionary = set(self.freq)
        # BK-trees need a true metric. OSA (damerau_distance) violates the
        # triangle inequality, so index with Levenshtein and re-rank with OSA.
        self.fuzzy_searcher = FuzzySearch(distance=levenshtein_distance)
        self.fuzzy_searcher.build_index(list(self.dictionary))
        self.ngram_index = self._build_ngram_index(self.dictionary)
        self.soundex_index = {}
        for w in self.dictionary:
            self.soundex_index.setdefault(self._soundex(w), []).append(w)
    
    def correct(self, word: str) -> str:
        """Correct a misspelled word, preserving simple capitalization."""
        lower = word.lower()
        best = self._best(lower)
        if best == lower:
            return word
        return best.capitalize() if word[:1].isupper() else best

    def _best(self, word: str) -> str:
        # Strategy 1: Exact match
        if word in self.dictionary:
            return word
        
        # Strategy 2: Edit distance (Damerau, ≤ 2), ranked by (distance, -frequency)
        # Short words get a tighter limit, like Elasticsearch's fuzziness AUTO
        max_d = 0 if len(word) <= 2 else 1 if len(word) <= 5 else 2
        # A transposition costs 2 in Levenshtein, so search one step wider,
        # then keep candidates within max_d by the transposition-aware distance
        wide = self.fuzzy_searcher.search(word, max_distance=max_d + 1) if max_d else []
        fuzzy = [(w, damerau_distance(w, word)) for w, _ in wide]
        fuzzy = [(w, d) for w, d in fuzzy if d <= max_d]
        if fuzzy:
            return min(fuzzy, key=lambda wd: (wd[1], -self.freq[wd[0]]))[0]
        
        # Strategy 3: N-gram overlap
        ngram_matches = self._ngram_match(word, threshold=0.6)
        if ngram_matches:
            return ngram_matches[0][0]
        
        # Strategy 4: Phonetic match (Soundex)
        phonetic = self.soundex_index.get(self._soundex(word), [])
        if phonetic:
            return max(phonetic, key=lambda w: self.freq[w])
        
        # No correction found
        return word
    
    def suggest(self, query: str, max_suggestions: int = 5) -> list:
        """
        Suggest corrections for a multi-word query.
        
        "Harry Poter" → ["Harry Potter"]
        """
        tokens = query.split()
        corrected = [self.correct(t) for t in tokens]
        if corrected == tokens:
            return []
        # Real systems score whole-query candidates with a language model or
        # query logs ("harry potter" is a frequent query; "harry porter" isn't).
        return [" ".join(corrected)][:max_suggestions]
    
    def _build_ngram_index(self, words, n: int = 3) -> dict:
        """Build trigram index for efficient fuzzy matching."""
        index = {}
        for word in words:
            for gram in self._get_ngrams(word, n):
                index.setdefault(gram, []).append(word)
        return index
    
    def _get_ngrams(self, word: str, n: int = 3) -> set:
        """Get n-grams with padding."""
        padded = f"^{word}$"
        return {padded[i:i+n] for i in range(len(padded) - n + 1)}
    
    def _ngram_match(self, word: str, threshold: float = 0.5) -> list:
        """Find words with high n-gram overlap (Jaccard similarity)."""
        word_grams = self._get_ngrams(word)
        candidates = set()
        for gram in word_grams:
            candidates.update(self.ngram_index.get(gram, []))
        
        scored = []
        for candidate in candidates:
            cand_grams = self._get_ngrams(candidate)
            score = len(word_grams & cand_grams) / len(word_grams | cand_grams)
            if score >= threshold:
                scored.append((candidate, score))
        
        return sorted(scored, key=lambda x: (-x[1], -self.freq[x[0]]))
    
    @staticmethod
    def _soundex(word: str) -> str:
        """
        American Soundex: first letter + 3 digits.
        Example: "Robert" → R163, "Rupert" → R163, "Tymczak" → T522
        """
        codes = {**dict.fromkeys("BFPV", "1"), **dict.fromkeys("CGJKQSXZ", "2"),
                 **dict.fromkeys("DT", "3"), "L": "4", **dict.fromkeys("MN", "5"),
                 "R": "6"}
        word = "".join(c for c in word.upper() if c.isalpha())
        if not word:
            return ""
        result = word[0]
        last = codes.get(word[0], "")
        for ch in word[1:]:
            code = codes.get(ch, "")
            if code and code != last:
                result += code
            if ch not in "HW":        # H and W don't separate equal codes;
                last = code           # vowels do (they reset `last` to "")
        return (result + "000")[:4]   # pad AND truncate to 4 characters

# ─── Demo: Autocorrect in Action ──────────────────

def demo_autocorrect():
    # Word frequencies would come from your corpus or query logs
    dictionary = {
        "harry": 900, "potter": 800, "porter": 50, "hermione": 300, "granger": 200,
        "hogwarts": 250, "ron": 400, "weasley": 300, "voldemort": 200,
        "receive": 500, "believe": 700, "achieve": 300, "perceive": 100,
        "california": 600, "colorado": 300, "connecticut": 100,
        "definitely": 400, "separate": 350, "necessary": 300, "accommodate": 150,
    }
    
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
        print(f"Input: '{query}'  Suggestions: {corrector.suggest(query)}")

# Output:
# Input: 'Harry Poter'  Suggestions: ['Harry Potter']
# Input: 'recieve'  Suggestions: ['receive']
# Input: 'Califonia'  Suggestions: ['California']
# Input: 'seperate'  Suggestions: ['separate']
# Input: 'definately'  Suggestions: ['definitely']
# Input: 'beleive'  Suggestions: ['believe']
```

## 5. PRODUCTION CONSIDERATIONS

| Approach | Lookup cost | Notes |
|----------|-------------|-------|
| Brute-force edit distance | O(N · L²) per query | Fine for a few thousand words |
| BK-tree | Prunes by triangle inequality; visits a fraction of N | Needs a true metric (Levenshtein or full Damerau-Levenshtein, not OSA) |
| SymSpell (symmetric delete) | Near O(1) lookups after precomputing deletes | Very fast, large memory footprint |
| Levenshtein automaton (Lucene) | Intersect an automaton with the term dictionary FST | What Elasticsearch `fuzzy` / `match` with `fuzziness` uses; max edit distance 2 |

In **Elasticsearch / OpenSearch**:

- `match` with `"fuzziness": "AUTO"`: 0 edits for terms of 1–2 characters, 1 for 3–5, 2 for longer; transpositions count as one edit by default. Set `prefix_length` (e.g. 1–2) to cut the search space, since first letters are rarely mistyped.
- **Term suggester** corrects individual tokens; **phrase suggester** scores whole-phrase candidates with an n-gram language model built from a shingle field (this is what turns "harry poter" into "harry potter" rather than "harry porter"); **completion suggester** is for prefix autocomplete (an in-memory FST), not correction.

Things that matter more than the algorithm:

- **Query logs** are the best dictionary: real queries, real frequencies, and reformulations ("user typed X, then immediately typed Y") give you P(typo | word) for free.
- **Don't correct valid rare terms**: product codes, names and new brands look like typos. Only auto-correct when the original query returns few or no results *and* the correction is much more likely; otherwise show "Did you mean…?".
- **Measure it**: correction precision (how often the change was right), recall, and downstream click-through or zero-result rate.
- **Semantic search** (embeddings) tolerates some misspellings on its own, but rare tokens like SKUs and names still need lexical fuzzy matching, which is one reason hybrid (BM25 + vector) retrieval is common.

---

> **Previous:** [Redis Lease](11_REDIS_LEASE.md)
> **Next:** [Elasticsearch Internals](13_ELASTICSEARCH_INTERNALS.md)
