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
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, chunks: List[Chunk]) -> None:
        if not chunks:
            return
        ids = [c.chunk_id for c in chunks]
        texts = [c.text for c in chunks]
        embeddings = [c.embedding for c in chunks]
        metadatas = [c.metadata for c in chunks]

        self._collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def search(self, query_embedding: List[float],
               top_k: int = 5) -> List[SearchResult]:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        if not results["ids"]:
            return []

        search_results = []
        for i in range(len(results["ids"][0])):
            chunk = Chunk(
                text=results["documents"][0][i],
                chunk_id=results["ids"][0][i],
                metadata=results["metadatas"][0][i] if results["metadatas"] else {},
            )
            score = 1 - results["distances"][0][i]  # Convert distance to similarity
            search_results.append(SearchResult(chunk=chunk, score=score))

        return search_results

    def delete(self, chunk_id: str) -> None:
        self._collection.delete(ids=[chunk_id])

    def count(self) -> int:
        return self._collection.count()
