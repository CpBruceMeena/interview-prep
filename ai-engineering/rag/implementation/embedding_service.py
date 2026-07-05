"""Embedding service — converts text to dense vector representations."""

from abc import ABC, abstractmethod
from typing import List, Optional

from config import settings


class EmbeddingService(ABC):
    """Abstract embedding service — follow Dependency Inversion Principle."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Convert a single text string to a vector embedding."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert multiple texts to embeddings (batched for efficiency)."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass


class SentenceTransformerEmbedding(EmbeddingService):
    """Uses sentence-transformers for local embeddings (default)."""

    def __init__(self, model_name: Optional[str] = None):
        from sentence_transformers import SentenceTransformer
        model_name = model_name or settings.embedding_model
        self._model = SentenceTransformer(model_name)
        self._model.to(settings.embedding_device)
        self._dimension = self._model.get_sentence_embedding_dimension()

    def embed_text(self, text: str) -> List[float]:
        return self._model.encode(text).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts).tolist()

    @property
    def dimension(self) -> int:
        return self._dimension


class OpenAIEmbedding(EmbeddingService):
    """Uses OpenAI API for embeddings (fallback option)."""

    def __init__(self, model: str = "text-embedding-3-small"):
        from openai import OpenAI
        self._client = OpenAI()
        self._model = model
        self._dimension = 1536

    def embed_text(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(
            model=self._model, input=text
        )
        return resp.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        resp = self._client.embeddings.create(
            model=self._model, input=texts
        )
        return [d.embedding for d in resp.data]

    @property
    def dimension(self) -> int:
        return self._dimension
