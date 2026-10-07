# 📚 RAG Pipeline Implementation

A small, runnable RAG chatbot: sentence-transformers embeddings, ChromaDB, a FastAPI server and any OpenAI-compatible LLM (LM Studio by default). The design rationale is in [Code Base Design](../05_CODE_BASE_DESIGN.md) and [Low-Level Design](../06_LOW_LEVEL_DESIGN.md).

**What it deliberately leaves out** (covered in the docs, good extension exercises): hybrid BM25 search, reranking, MMR, query rewriting, streaming, auth and per-user ACLs.

## Module Overview

```
implementation/
├── config.py             # Settings (pydantic-settings): env vars / .env override defaults
├── document_loader.py    # PDF (pypdf), text/markdown and HTML loaders + loader_for() factory
├── embedding_service.py  # EmbeddingService ABC; SentenceTransformer (default) and OpenAI backends
├── vector_store.py       # Chunk, SearchResult, VectorStore ABC, ChromaVectorStore (cosine, upsert)
├── retrieval_engine.py   # embed query → vector search → similarity threshold → context string
├── llm_service.py        # LLMService ABC; OpenAI-compatible, LM Studio and Mock clients
├── rag_pipeline.py       # RAGPipeline facade: chunk + index documents, answer queries
├── chatbot_api.py        # FastAPI app: /health, /api/query, /api/index, /api/index-directory
├── main.py               # CLI entry point
└── requirements.txt
```

## Core Components

### Configuration (`config.py`)

```python
class Settings(BaseSettings):
    embedding_model: str = "all-MiniLM-L6-v2"   # 384-dim
    chunk_size: int = 500                        # characters
    chunk_overlap: int = 50
    top_k: int = 5
    similarity_threshold: float = 0.3
    lm_studio_url: str = "http://localhost:1234"
    llm_model: str = "google/gemma-4-e4b"        # must match GET /v1/models
    persist_directory: str = "./data/vector_store"
    data_directory: str = "./data"
    ...
```

Override with environment variables or `.env`, e.g. `LLM_MODEL=qwen/qwen3-4b`, `EMBEDDING_DEVICE=mps`. Relative paths resolve against the current working directory.

### Document Loader (`document_loader.py`)

- `PDFLoader`: one `Document` per page (`page` in metadata), via LangChain's `PyPDFLoader` (pypdf)
- `TextFileLoader`: `.txt` and `.md`
- `HTMLLoader`: BeautifulSoup; drops script/style/nav/header/footer
- `loader_for(path)`: picks the loader by extension; `load_directory()` walks a folder recursively

Chunking happens in `RAGPipeline` with `RecursiveCharacterTextSplitter` from `langchain-text-splitters`.

### Embedding Service (`embedding_service.py`)

- `SentenceTransformerEmbedding`: local model, unit-normalised vectors, batched encoding
- `OpenAIEmbedding`: `text-embedding-3-small/large`, optional Matryoshka `dimensions` (needs `pip install openai`)
- `embed_query()` hook for models that need a query prefix or instruction

### Vector Store (`vector_store.py`)

`ChromaVectorStore` uses a persistent Chroma collection with cosine distance and returns `score = 1 − distance`. Writes are **upserts** in batches no larger than Chroma's max batch size; `delete_source()` removes a document's old chunks before re-indexing.

```python
store = ChromaVectorStore(persist_directory="./data/vector_store")
results = store.search(query_embedding, top_k=5)   # List[SearchResult(chunk, score)]
```

### Retrieval Engine (`retrieval_engine.py`)

Dense top-k retrieval with a similarity floor, plus `format_context()` that labels chunks `[Source N: path]` for citation.

### RAG Pipeline (`rag_pipeline.py`)

```python
from rag_pipeline import RAGPipeline          # run from implementation/ (top-level imports)

pipeline = RAGPipeline()                       # defaults: MiniLM + Chroma + LM Studio
pipeline.index_directory("./data")
result = pipeline.query("What is chunk overlap?")
# {"answer": "...[Source 1]...", "sources": [{"text", "score", "source"}], "latency_ms": ...}
```

Flow: `retrieve once → format context → system prompt (rules + context) + user question → LLM → answer + the same sources`. Chunk IDs are `hash(source|page|chunk_index)`, so re-indexing is idempotent.

### LLM Service (`llm_service.py`)

- `OpenAICompatibleClient(api_url=".../v1", api_key, model)`: any OpenAI-compatible server
- `LMStudioClient()`: the same, pointed at `settings.lm_studio_url`
- `MockLLMService("fixed text")`: for tests

`generate()` logs and returns `None` on failure; `is_available()` probes `GET /v1/models`.

### Chatbot API (`chatbot_api.py`)

```bash
cd ai-engineering/rag/implementation
uvicorn chatbot_api:app --host 127.0.0.1 --port 8000      # or: python main.py --serve

curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is RAG?", "top_k": 5}'

curl -X POST http://localhost:8000/api/index -F "file=@notes.md"
curl http://localhost:8000/health
```

Blocking work (embedding, LLM calls) runs in worker threads, so one slow request doesn't stall the event loop. `/api/index-directory` only accepts paths inside `DATA_DIRECTORY`. There is no authentication, so keep it on localhost.

## Running the Pipeline

```bash
cd ai-engineering/rag
pip install -r implementation/requirements.txt

# End-to-end check (temp Chroma dir, MockLLM; downloads the embedding model on first run)
python test_pipeline.py

# CLI (run from ai-engineering/rag so ./data paths resolve)
python implementation/main.py --index --docs ./data
python implementation/main.py --query "Your question here"     # needs LM Studio serving a model
python implementation/main.py --interactive
python implementation/main.py --serve
```

## Architecture

```
User Query
    │
    ▼
┌──────────────────┐        ┌──────────────┐
│  RAG Pipeline    │──────▶ │ LLM Service  │  (LM Studio / OpenAI-compatible)
│  (facade)        │        └──────────────┘
└────────┬─────────┘
         ▼
┌──────────────────┐        ┌───────────────────┐
│ Retrieval Engine │──────▶ │ Embedding Service │
└────────┬─────────┘        └───────────────────┘
         ▼
┌──────────────────┐
│  Vector Store    │  (Chroma, cosine)
└──────────────────┘
         ▲
         │ upsert chunks
┌────────┴─────────┐
│ Document Loader  │  (PDF / text / HTML) → chunk → embed
└──────────────────┘
```
