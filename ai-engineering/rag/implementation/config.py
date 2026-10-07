"""Configuration settings for the RAG chatbot.

Every field can be overridden with an environment variable of the same name
(case-insensitive) or a line in `.env`, e.g. `LLM_MODEL=qwen/qwen3-4b`.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings v2 style (the inner `class Config` is deprecated).
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"   # 384-dim, small and fast; fine for a demo
    embedding_dimension: int = 384
    embedding_device: str = "cpu"  # "cpu", "cuda" or "mps"

    # Chunking (RecursiveCharacterTextSplitter counts CHARACTERS, not tokens)
    chunk_size: int = 500
    chunk_overlap: int = 50

    # Retrieval
    top_k: int = 5
    # Cosine-similarity floor. Model-specific: calibrate on your own queries.
    similarity_threshold: float = 0.3
    use_reranker: bool = False  # reserved; no reranker is wired in yet

    # LLM (LM Studio's OpenAI-compatible server)
    llm_provider: str = "lm_studio"
    lm_studio_url: str = "http://localhost:1234"
    # Must match an identifier returned by `GET /v1/models` on your LM Studio.
    llm_model: str = "google/gemma-4-e4b"
    temperature: float = 0.3
    max_tokens: int = 1024

    # Vector store (only Chroma is implemented)
    vector_store: str = "chroma"
    persist_directory: str = "./data/vector_store"

    # API
    host: str = "127.0.0.1"
    port: int = 8000

    # Paths: the sample corpus lives in rag/data/*.md
    data_directory: str = "./data"


settings = Settings()
