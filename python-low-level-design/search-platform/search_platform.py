"""
Search Platform - Low Level Design
-------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer, Facade
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any
import uuid
import re


class MatchType(Enum):
    EXACT = "Exact"
    PREFIX = "Prefix"
    FUZZY = "Fuzzy"
    REGEX = "Regex"
    SEMANTIC = "Semantic"


class SortOrder(Enum):
    RELEVANCE = "Relevance"
    DATE = "Date"
    POPULARITY = "Popularity"
    RATING = "Rating"


# --- Document (SRP) ---

@dataclass
class Document:
    """Represents a searchable document"""
    doc_id: str
    title: str
    content: str
    author: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    popularity: int = 0
    rating: float = 0.0
    metadata: Dict[str, str] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.doc_id)

    def __str__(self) -> str:
        return f"{self.title} (id: {self.doc_id[:8]})"


# --- Tokenizer (SRP) ---

class Tokenizer:
    """Converts text into searchable tokens"""

    def __init__(self, stop_words: Optional[Set[str]] = None):
        self._stop_words = stop_words or {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
            'to', 'for', 'of', 'by', 'with', 'is', 'are', 'was', 'were',
            'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
            'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'shall', 'can', 'need', 'dare', 'ought', 'used'
        }

    def tokenize(self, text: str) -> List[str]:
        """Convert text to lowercase tokens, removing punctuation"""
        text = text.lower()
        # Remove punctuation
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if t not in self._stop_words and len(t) > 1]

    def stem(self, token: str) -> str:
        """Simple stemming: remove common suffixes"""
        if len(token) <= 3:
            return token
        for suffix in ['ing', 'ed', 'ly', 'es', 's', 'ion', 'tion', 'ment']:
            if token.endswith(suffix) and len(token) - len(suffix) > 2:
                return token[:-len(suffix)]
        return token


# --- Index (Core Data Structure) ---

class InvertedIndex:
    """Inverted index mapping tokens to documents"""

    def __init__(self, tokenizer: Tokenizer):
        self._tokenizer = tokenizer
        self._index: Dict[str, Dict[str, int]] = {}  # token -> doc_id -> count
        self._documents: Dict[str, Document] = {}
        self._doc_count = 0

    def add_document(self, doc: Document) -> None:
        self._documents[doc.doc_id] = doc
        self._doc_count += 1

        # Index title (weighted higher)
        title_tokens = self._tokenizer.tokenize(doc.title)
        for token in set(title_tokens):
            stemmed = self._tokenizer.stem(token)
            if stemmed not in self._index:
                self._index[stemmed] = {}
            self._index[stemmed][doc.doc_id] = self._index[stemmed].get(doc.doc_id, 0) + 3

        # Index content
        content_tokens = self._tokenizer.tokenize(doc.content)
        for token in set(content_tokens):
            stemmed = self._tokenizer.stem(token)
            if stemmed not in self._index:
                self._index[stemmed] = {}
            self._index[stemmed][doc.doc_id] = self._index[stemmed].get(doc.doc_id, 0) + 1

        # Index tags
        for tag in doc.tags:
            tag_token = self._tokenizer.stem(tag.lower())
            if tag_token not in self._index:
                self._index[tag_token] = {}
            self._index[tag_token][doc.doc_id] = self._index[tag_token].get(doc.doc_id, 0) + 5

    def remove_document(self, doc_id: str) -> None:
        doc = self._documents.pop(doc_id, None)
        if doc:
            self._doc_count -= 1
            for token in list(self._index.keys()):
                if doc_id in self._index[token]:
                    del self._index[token][doc_id]
                    if not self._index[token]:
                        del self._index[token]

    def search_token(self, token: str) -> Dict[str, int]:
        """Get documents containing a token with their term frequency"""
        stemmed = self._tokenizer.stem(token.lower())
        return dict(self._index.get(stemmed, {}))

    def get_document(self, doc_id: str) -> Optional[Document]:
        return self._documents.get(doc_id)

    def get_all_documents(self) -> List[Document]:
        return list(self._documents.values())

    @property
    def document_count(self) -> int:
        return self._doc_count


# --- Ranking Strategy (Strategy Pattern) ---

class RankingStrategy(ABC):
    @abstractmethod
    def rank(self, results: Dict[str, float],
             query: str, index: InvertedIndex) -> List[Tuple[str, float]]:
        pass


class TfIdfRanking(RankingStrategy):
    def rank(self, results: Dict[str, float],
             query: str, index: InvertedIndex) -> List[Tuple[str, float]]:
        """Rank by TF-IDF score"""
        n = index.document_count
        for doc_id in results:
            # Multiply score by inverse document frequency
            doc_freq = sum(1 for t in index._index.values() if doc_id in t)
            if doc_freq > 0:
                idf = n / (1 + doc_freq)
                results[doc_id] *= idf
        return sorted(results.items(), key=lambda x: x[1], reverse=True)


class RecencyBoostRanking(RankingStrategy):
    def __init__(self, base: RankingStrategy, boost_factor: float = 1.5):
        self._base = base
        self._boost = boost_factor

    def rank(self, results: Dict[str, float],
             query: str, index: InvertedIndex) -> List[Tuple[str, float]]:
        scored = dict(results)
        now = datetime.now()
        for doc_id in scored:
            doc = index.get_document(doc_id)
            if doc:
                days_ago = (now - doc.created_at).days
                if days_ago < 7:
                    scored[doc_id] *= self._boost  # Recent boost
                elif days_ago > 365:
                    scored[doc_id] *= 0.5  # Old penalty
        return self._base.rank(scored, query, index)


class PopularityRanking(RankingStrategy):
    def __init__(self, base: Optional[RankingStrategy] = None):
        self._base = base

    def rank(self, results: Dict[str, float],
             query: str, index: InvertedIndex) -> List[Tuple[str, float]]:
        scored = dict(results)
        for doc_id in scored:
            doc = index.get_document(doc_id)
            if doc:
                scored[doc_id] *= (1 + doc.popularity / 1000)  # Boost by popularity
        if self._base:
            return self._base.rank(scored, query, index)
        return sorted(scored.items(), key=lambda x: x[1], reverse=True)


# --- Search Query Parser ---

class QueryParser:
    """Parses search queries with operators"""

    @staticmethod
    def parse(query: str) -> Tuple[List[str], List[str], List[str]]:
        """
        Parse query into required, optional, and excluded terms.
        Returns (required, optional, excluded)
        """
        required = []
        optional = []
        excluded = []

        # Handle quoted phrases
        phrases = re.findall(r'"([^"]+)"', query)
        for phrase in phrases:
            optional.append(phrase)
            query = query.replace(f'"{phrase}"', '')

        # Parse remaining
        for term in query.split():
            if term.startswith('+'):
                required.append(term[1:])
            elif term.startswith('-'):
                excluded.append(term[1:])
            else:
                if term.lower() not in ('and', 'or', 'not'):
                    optional.append(term)

        return required, optional, excluded


# --- Fuzzy Search (Strategy) ---

class FuzzyMatcher(ABC):
    @abstractmethod
    def match(self, query: str, text: str) -> bool:
        pass


class LevenshteinMatcher(FuzzyMatcher):
    def __init__(self, max_distance: int = 2):
        self._max_distance = max_distance

    def match(self, query: str, text: str) -> bool:
        return self._levenshtein(query.lower(), text.lower()) <= self._max_distance

    def _levenshtein(self, s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return self._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)

        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
            prev = curr

        return prev[-1]


# --- Search Service (Facade) ---

class SearchService:
    def __init__(self, index: InvertedIndex,
                 ranking: RankingStrategy = None,
                 fuzzy: Optional[FuzzyMatcher] = None):
        self._index = index
        self._ranking = ranking or TfIdfRanking()
        self._fuzzy = fuzzy
        self._parser = QueryParser()
        self._search_history: List[Tuple[str, int]] = []

    def index_document(self, doc: Document) -> None:
        self._index.add_document(doc)

    def bulk_index(self, documents: List[Document]) -> None:
        for doc in documents:
            self._index.add_document(doc)

    def search(self, query: str, limit: int = 10,
               sort_by: SortOrder = SortOrder.RELEVANCE,
               category: Optional[str] = None) -> List[Document]:
        """Main search method"""
        required, optional, excluded = self._parser.parse(query)

        if not optional and not required:
            return []

        # Score documents
        scores: Dict[str, float] = {}

        for term in optional:
            matches = self._index.search_token(term)
            for doc_id, freq in matches.items():
                scores[doc_id] = scores.get(doc_id, 0) + freq

            # Fuzzy fallback
            if not matches and self._fuzzy:
                for doc in self._index.get_all_documents():
                    if self._fuzzy.match(term, doc.title) or self._fuzzy.match(term, doc.content):
                        scores[doc.doc_id] = scores.get(doc.doc_id, 0) + 1

        for term in required:
            matches = self._index.search_token(term)
            for doc_id in list(scores.keys()):
                if doc_id not in matches:
                    del scores[doc_id]

        for term in excluded:
            matches = self._index.search_token(term)
            for doc_id in list(scores.keys()):
                if doc_id in matches:
                    del scores[doc_id]

        # Filter by category
        if category:
            scores = {did: s for did, s in scores.items()
                      if self._index.get_document(did) and
                      self._index.get_document(did).category == category}

        # Rank
        ranked = self._ranking.rank(scores, query, self._index)

        # Track search history
        self._search_history.append((query, len(ranked)))

        # Return documents
        results = []
        for doc_id, score in ranked[:limit]:
            doc = self._index.get_document(doc_id)
            if doc:
                doc.popularity += 1
                results.append(doc)

        return results

    def suggest(self, prefix: str, limit: int = 5) -> List[str]:
        """Auto-complete suggestions based on indexed tokens"""
        prefix = prefix.lower()
        suggestions = set()

        for token in self._index._index.keys():
            if token.startswith(prefix):
                # Get original word from documents
                for doc in self._index.get_all_documents():
                    if prefix in doc.title.lower():
                        suggestions.add(doc.title[:50])
                    if prefix in doc.content.lower():
                        # Extract the word containing the prefix
                        words = re.findall(r'\b' + re.escape(prefix) + r'\w*', doc.content.lower())
                        suggestions.update(words)

        return sorted(suggestions)[:limit]

    def get_search_stats(self) -> Dict[str, Any]:
        return {
            "total_documents": self._index.document_count,
            "total_tokens": len(self._index._index),
            "total_searches": len(self._search_history),
        }


# --- Demo ---

def demo():
    print("=== Search Platform ===")
    print("=" * 50)

    # Setup
    tokenizer = Tokenizer()
    index = InvertedIndex(tokenizer)
    ranking = RecencyBoostRanking(PopularityRanking(TfIdfRanking()))
    fuzzy = LevenshteinMatcher(2)
    search = SearchService(index, ranking, fuzzy)

    # Index documents
    docs = [
        Document("1", "Python Design Patterns", "Learn about Singleton, Factory, Observer patterns in Python",
                 "John Doe", "Programming", ["python", "design-patterns", "oop"],
                 datetime(2025, 6, 15), 1500, 4.5),
        Document("2", "System Design Interview Guide", "Complete guide for system design interviews including scalability",
                 "Jane Smith", "Interview Prep", ["system-design", "interview", "scalability"],
                 datetime(2025, 6, 20), 2000, 4.8),
        Document("3", "Microservices Architecture", "Building scalable microservices with Docker and Kubernetes",
                 "Bob Wilson", "Architecture", ["microservices", "docker", "kubernetes"],
                 datetime(2025, 6, 10), 1200, 4.2),
        Document("4", "Python for Data Science", "NumPy, Pandas, and Scikit-learn tutorial for beginners",
                 "Alice Brown", "Data Science", ["python", "data-science", "machine-learning"],
                 datetime(2025, 5, 1), 3000, 4.6),
        Document("5", "Database Design Fundamentals", "Relational databases, indexing, query optimization techniques",
                 "Charlie Davis", "Databases", ["database", "sql", "indexing"],
                 datetime(2025, 4, 15), 800, 4.0),
        Document("6", "Design Microservices", "Advanced microservices patterns and best practices",
                 "Bob Wilson", "Architecture", ["microservices", "patterns", "architecture"],
                 datetime(2025, 6, 25), 500, 3.8),
    ]
    search.bulk_index(docs)
    print(f"Indexed {len(docs)} documents")

    # Search queries
    queries = [
        "python design",
        "microservices architecture",
        "system design interview",
        "data science",
        "database",
    ]

    for q in queries:
        print(f"\n--- Search: '{q}' ---")
        results = search.search(q, limit=3)
        for doc in results:
            print(f"  📄 {doc}")

    # Suggestions
    print(f"\n--- Autocomplete for 'py' ---")
    suggestions = search.suggest("py")
    for s in suggestions:
        print(f"  {s}")

    # Fuzzy search
    print(f"\n--- Fuzzy Search: 'desing' (should match 'design') ---")
    results = search.search("desing", limit=3)
    for doc in results:
        print(f"  📄 {doc}")

    # Stats
    print(f"\n--- Search Stats ---")
    stats = search.get_search_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    demo()
