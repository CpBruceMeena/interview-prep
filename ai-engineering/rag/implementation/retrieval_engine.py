"""Retrieval engine — finds relevant document chunks for a query."""

from typing import List, Optional

from config import settings
from embedding_service import EmbeddingService
from vector_store import VectorStore, SearchResult, Chunk


class RetrievalEngine:
    """Orchestrates retrieval: embed query → search → filter → rerank."""

    def __init__(self, embedder: EmbeddingService, store: VectorStore):
        self._embedder = embedder
        self._store = store

    def retrieve(self, query: str, top_k: Optional[int] = None,
                 threshold: Optional[float] = None) -> List[SearchResult]:
        """Full retrieval pipeline for a query string."""
        k = top_k or settings.top_k
        thresh = threshold or settings.similarity_threshold

        # 1. Embed the query
        query_vector = self._embedder.embed_text(query)

        # 2. Search the vector store
        results = self._store.search(query_vector, top_k=k)

        # 3. Filter by similarity threshold
        results = [r for r in results if r.score >= thresh]

        return results

    def retrieve_context(self, query: str, top_k: Optional[int] = None
                         ) -> str:
        """Retrieve chunks and format as a single context string."""
        results = self.retrieve(query, top_k=top_k)
        if not results:
            return ""

        parts = []
        for i, result in enumerate(results, 1):
            source = result.chunk.metadata.get("source", "unknown")
            parts.append(f"[Source {i}: {source}]\n{result.chunk.text}")

        return "\n\n".join(parts)
