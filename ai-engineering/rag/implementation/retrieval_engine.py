"""Retrieval engine — finds relevant document chunks for a query."""

from typing import List, Optional

from config import settings
from embedding_service import EmbeddingService
from vector_store import VectorStore, SearchResult


class RetrievalEngine:
    """Orchestrates retrieval: embed query → search → filter by threshold.

    Dense-only. Hybrid search (BM25 + dense with RRF) and reranking are the
    usual next steps; see data/04_retrieval_strategies.md.
    """

    def __init__(self, embedder: EmbeddingService, store: VectorStore):
        self._embedder = embedder
        self._store = store

    def retrieve(self, query: str, top_k: Optional[int] = None,
                 threshold: Optional[float] = None) -> List[SearchResult]:
        """Full retrieval pipeline for a query string."""
        # `is None` checks, not `or`: top_k=0 / threshold=0.0 are legitimate.
        k = settings.top_k if top_k is None else top_k
        thresh = settings.similarity_threshold if threshold is None else threshold

        query_vector = self._embedder.embed_query(query)
        results = self._store.search(query_vector, top_k=k)
        return [r for r in results if r.score >= thresh]

    @staticmethod
    def format_context(results: List[SearchResult]) -> str:
        """Format retrieved chunks as one context string with source labels."""
        parts = []
        for i, result in enumerate(results, 1):
            source = result.chunk.metadata.get("source", "unknown")
            parts.append(f"[Source {i}: {source}]\n{result.chunk.text}")
        return "\n\n".join(parts)

    def retrieve_context(self, query: str, top_k: Optional[int] = None
                         ) -> str:
        """Retrieve chunks and format as a single context string."""
        return self.format_context(self.retrieve(query, top_k=top_k))
