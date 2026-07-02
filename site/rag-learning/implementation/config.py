"""Configuration settings for the RAG chatbot."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_device: str = "cpu"  # "cpu" or "cuda"

    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50

    # Retrieval
    top_k: int = 5
    similarity_threshold: float = 0.3
    use_reranker: bool = False

    # LLM
    llm_provider: str = "lm_studio"  # "lm_studio" or "openai"
    lm_studio_url: str = "http://localhost:1234"
    llm_model: str = "gemma-4b-it"
    temperature: float = 0.3
    max_tokens: int = 1024

    # Vector Store
    vector_store: str = "chroma"  # "chroma", "faiss"
    persist_directory: str = "./data/vector_store"

    # API
    host: str = "0.0.0.0"
    port: int = 8000

    # Paths
    data_directory: str = "./data/documents"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
