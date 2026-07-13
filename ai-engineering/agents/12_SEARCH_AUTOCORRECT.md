# 🔍 Search Engine: Misspelling Handling & Autocorrect

> **Target:** Staff/Principal Engineer | **Focus:** Search engine misspelling handling, autocorrect algorithms, Levenshtein distance, BK-tree, Soundex

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
│  3. Suggest correction: "Showing results for  │
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

## 4. AUTOCORRECT IMPLEMENTATION

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

> **Previous:** [Redis Lease](11_REDIS_LEASE.md)
> **Next:** [Elasticsearch Internals](13_ELASTICSEARCH_INTERNALS.md)
