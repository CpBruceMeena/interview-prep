"""Embedding service — converts text to dense vector representations."""

from abc import ABC, abstractmethod
from typing import List, Optional

from config import settings


class EmbeddingService(ABC):
    """Abstract embedding service — the pipeline depends on this, not on a vendor."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Convert a single text string to a vector embedding."""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert multiple texts to embeddings (batched for efficiency)."""

    def embed_query(self, query: str) -> List[float]:
        """Embed a search query. Override for models that need a query
        prefix or instruction (E5: "query: ", BGE v1.5, Qwen3-Embedding...)."""
        return self.embed_text(query)

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""


class SentenceTransformerEmbedding(EmbeddingService):
    """Uses sentence-transformers for local embeddings (default)."""

    def __init__(self, model_name: Optional[str] = None,
                 device: Optional[str] = None):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(
            model_name or settings.embedding_model,
            device=device or settings.embedding_device,
        )
        # Recent sentence-transformers (6.x) renamed get_sentence_embedding_dimension()
        # (now a deprecated alias) to get_embedding_dimension().
        get_dim = getattr(self._model, "get_embedding_dimension", None) \
            or self._model.get_sentence_embedding_dimension
        self._dimension = get_dim()

    def embed_text(self, text: str) -> List[float]:
        # Unit-normalise so cosine similarity == dot product.
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(
            texts, batch_size=64, normalize_embeddings=True
        ).tolist()

    @property
    def dimension(self) -> int:
        return self._dimension


class OpenAIEmbedding(EmbeddingService):
    """Uses the OpenAI embeddings API (needs `pip install openai` and OPENAI_API_KEY).

    text-embedding-3-* are Matryoshka-trained: pass `dimensions` to get a
    shorter vector (e.g. 256 or 512) at a small quality cost.
    """

    _NATIVE_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}

    def __init__(self, model: str = "text-embedding-3-small",
                 dimensions: Optional[int] = None):
        from openai import OpenAI
        self._client = OpenAI()
        self._model = model
        self._requested_dims = dimensions
        self._dimension = dimensions or self._NATIVE_DIMS.get(model, 1536)

    def _create(self, inputs):
        kwargs = {"model": self._model, "input": inputs}
        if self._requested_dims:
            kwargs["dimensions"] = self._requested_dims
        return self._client.embeddings.create(**kwargs)

    def embed_text(self, text: str) -> List[float]:
        return self._create(text).data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # The API caps inputs per request; batch large corpora upstream.
        return [d.embedding for d in self._create(texts).data]

    @property
    def dimension(self) -> int:
        return self._dimension
