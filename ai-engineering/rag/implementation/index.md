# 📚 RAG Pipeline Implementation

This directory contains runnable Python implementations of the Retrieval-Augmented Generation (RAG) pipeline components described in the [RAG documentation](../05_CODE_BASE_DESIGN.md).

## Module Overview

```
implementation/
├── config.py                # Configuration management
├── document_loader.py       # Document ingestion (PDF, text, web)
├── embedding_service.py     # Text embedding generation
├── vector_store.py          # Vector storage and similarity search
├── retrieval_engine.py      # Document retrieval with hybrid search
├── rag_pipeline.py          # End-to-end RAG pipeline orchestrator
├── llm_service.py           # LLM interaction (OpenAI, LM Studio)
├── chatbot_api.py           # FastAPI chatbot interface
├── main.py                  # CLI entry point
├── requirements.txt         # Python dependencies
└── __init__.py
```

## Core Components

### Configuration (`config.py`)

Central configuration management using Pydantic:

```python
class RAGConfig(BaseSettings):
    embedding_model: str = "text-embedding-ada-002"
    llm_model: str = "gpt-4o-mini"
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
    vector_store_path: str = "./data/vector_store"
```

Supports environment variables, `.env` files, and direct initialization.

### Document Loader (`document_loader.py`)

Multi-format document ingestion:
- **PDF loading** — Text extraction with page metadata
- **Text file loading** — Plain text and markdown
- **Web scraping** — URL content extraction
- **Chunking** — Configurable chunk size and overlap with semantic boundary detection

```python
from implementation.document_loader import DocumentLoader

loader = DocumentLoader(chunk_size=512, chunk_overlap=50)
chunks = loader.load("path/to/document.pdf")
```

### Embedding Service (`embedding_service.py`)

Abstract embedding provider with multiple backends:
- **OpenAIEmbeddings** — OpenAI API (`text-embedding-ada-002`, `text-embedding-3-small`)
- **LMStudioEmbeddings** — Local embeddings via LM Studio
- **HuggingFaceEmbeddings** — Open-source models via sentence-transformers

Supports batch processing, caching, and configurable dimensions.

### Vector Store (`vector_store.py`)

Vector database abstraction layer:
- **FAISS** — In-memory similarity search for development
- **ChromaDB** — Persistent storage with metadata filtering
- **Hybrid search** — Combines vector similarity with keyword matching (BM25)

```python
from implementation.vector_store import VectorStore

store = VectorStore(backend="chroma", persist_dir="./data/chroma")
store.add_documents(chunks, embeddings)
results = store.similarity_search(query_embedding, k=5)
```

### Retrieval Engine (`retrieval_engine.py`)

Advanced retrieval with multiple strategies:
- **Simple retrieval** — Top-k vector similarity
- **Hybrid retrieval** — Weighted combination of dense + sparse
- **Contextual retrieval** — Window expansion around matched chunks
- **MMR (Maximal Marginal Relevance)** — Diversity-enhanced results

### RAG Pipeline (`rag_pipeline.py`)

End-to-end pipeline orchestrating the full RAG flow:

```python
from implementation.rag_pipeline import RAGPipeline

pipeline = RAGPipeline()
answer = pipeline.query("What is the capital of France?")
# Returns: "The capital of France is Paris."
```

Pipeline flow: `query → embed → retrieve → format → generate → answer`

### LLM Service (`llm_service.py`)

LLM interaction abstraction:
- **OpenAI** — GPT-4o, GPT-4o-mini
- **LM Studio** — Local LLM inference
- **Custom** — Configurable endpoint and model

Supports streaming, structured output, and system prompts.

### Chatbot API (`chatbot_api.py`)

FastAPI-based REST API for the RAG chatbot:

```bash
# Start the API server
uvicorn implementation.chatbot_api:app --host 0.0.0.0 --port 8000

# Query the chatbot
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is RAG?", "session_id": "abc123"}'
```

## Running the Pipeline

```bash
cd ai-engineering/rag
pip install -r implementation/requirements.txt

# CLI mode
python -m implementation.main --query "Your question here"

# API mode
python -m implementation.chatbot_api

# Test mode
python -m pytest tests/
```

## Architecture

```
User Query
    │
    ▼
┌─────────────┐     ┌──────────────────┐
│  LLM Service │◄────│  RAG Pipeline    │
│  (openai/    │     │  (orchestrator)  │
│   lmstudio)  │     └────────┬─────────┘
└─────────────┘              │
                             ▼
              ┌──────────────────────────┐
              │   Retrieval Engine       │
              │  (hybrid + MMR search)   │
              └────────┬─────────────────┘
                       │
              ┌────────▼─────────┐
              │   Vector Store    │
              │  (FAISS/Chroma)  │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │ Embedding Service │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │ Document Loader   │
              │ (PDF/text/web)   │
              └──────────────────┘
```
