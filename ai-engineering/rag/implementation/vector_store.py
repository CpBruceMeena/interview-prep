"""Vector store — abstract interface for storing and searching embeddings."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import uuid

from config import settings


class Chunk:
    """A document chunk with text, embedding, and metadata."""

    def __init__(self, text: str, metadata: Optional[Dict] = None,
                 chunk_id: Optional[str] = None,
                 embedding: Optional[List[float]] = None):
        self.chunk_id = chunk_id or str(uuid.uuid4())
        self.text = text
        self.metadata = metadata or {}
        self.embedding = embedding

    def __repr__(self) -> str:
        return f"Chunk(id={self.chunk_id[:8]}, text_len={len(self.text)})"


class SearchResult:
    """Result of a vector similarity search."""

    def __init__(self, chunk: Chunk, score: float):
        self.chunk = chunk
        self.score = score

    def __repr__(self) -> str:
        return f"SearchResult(score={self.score:.4f}, chunk={self.chunk})"


class VectorStore(ABC):
    """Abstract vector store — follows Dependency Inversion Principle."""

    @abstractmethod
    def add_chunks(self, chunks: List[Chunk]) -> None:
        """Add chunks (with pre-computed embeddings) to the store."""
        pass

    @abstractmethod
    def search(self, query_embedding: List[float],
               top_k: int = 5) -> List[SearchResult]:
        """Search for similar chunks given a query embedding."""
        pass

    @abstractmethod
    def delete(self, chunk_id: str) -> None:
        """Delete a chunk by its ID."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Return the total number of chunks in the store."""
        pass


class ChromaVectorStore(VectorStore):
    """ChromaDB-based vector store for development and small-scale use."""

    def __init__(self, persist_directory: Optional[str] = None,
                 collection_name: str = "rag_docs"):
        import chromadb
        self._client = chromadb.PersistentClient(
            path=persist_directory or settings.persist_directory
        )
        # Distance metric is fixed when the collection is created. "cosine"
        # makes Chroma return distance = 1 - cosine_similarity. Chroma 1.x
        # also accepts configuration={"hnsw": {"space": "cosine"}}; the
        # metadata form is kept so existing persisted collections still match.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: List[Chunk]) -> None:
        """Upsert chunks. With deterministic chunk IDs, re-indexing the same
        document overwrites instead of duplicating."""
        if not chunks:
            return
        # Chroma caps the number of records per call.
        batch = self._client.get_max_batch_size()
        for start in range(0, len(chunks), batch):
            part = chunks[start:start + batch]
            self._collection.upsert(
                ids=[c.chunk_id for c in part],
                documents=[c.text for c in part],
                embeddings=[c.embedding for c in part],
                # Chroma metadata values must be str/int/float/bool (no None).
                metadatas=[{k: v for k, v in c.metadata.items() if v is not None}
                           or {"source": "unknown"} for c in part],
            )

    def search(self, query_embedding: List[float],
               top_k: int = 5) -> List[SearchResult]:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        if not results["ids"] or not results["ids"][0]:
            return []

        search_results = []
        for i, chunk_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else None
            chunk = Chunk(
                text=results["documents"][0][i],
                chunk_id=chunk_id,
                metadata=dict(metadata or {}),
            )
            score = 1 - results["distances"][0][i]  # cosine distance -> similarity
            search_results.append(SearchResult(chunk=chunk, score=score))

        return search_results

    def delete(self, chunk_id: str) -> None:
        self._collection.delete(ids=[chunk_id])

    def delete_source(self, source: str) -> None:
        """Remove every chunk of one source document (used before re-indexing
        it, so chunks from a longer old version don't linger)."""
        self._collection.delete(where={"source": source})

    def count(self) -> int:
        return self._collection.count()
