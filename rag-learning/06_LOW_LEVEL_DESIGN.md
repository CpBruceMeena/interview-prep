# 🧩 Low-Level Design — RAG Chatbot

> **Class diagrams, sequence diagrams, data models, API contracts**

---

## 1. CLASS DIAGRAM

```
┌────────────────────────────────────────────────────────────────┐
│                     RAG SYSTEM CLASS HIERARCHY                 │
└────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐     ┌──────────────────────────────┐
│   <<abstract>>           │     │   <<abstract>>               │
│   DocumentLoader         │     │   EmbeddingService           │
├──────────────────────────┤     ├──────────────────────────────┤
│ + load(path: str): str   │     │ + embed_text(t): List[float] │
│ + load_dir(path): List   │     │ + embed_batch(ts): List[]    │
└──────────┬───────────────┘     └──────────┬───────────────────┘
           │                                │
     ┌─────┼─────┐                   ┌──────┴──────┐
     │     │     │                   │             │
┌────▼┐ ┌─▼──┐ ┌▼────┐   ┌─────────▼┐    ┌───────▼──────┐
│PDF  │ │HTML│ │TXT  │   │Sentence  │    │OpenAI       │
│Loader││Load│ │Load │   │Transform │    │Embedding    │
└─────┘ └────┘ └─────┘   │Embedding │    │Service      │
                          └──────────┘    └──────────────┘

┌──────────────────────────┐     ┌──────────────────────────────┐
│   <<abstract>>           │     │   <<abstract>>               │
│   VectorStore            │     │   LLMService                 │
├──────────────────────────┤     ├──────────────────────────────┤
│ + add(text,vec,meta): id │     │ + generate(msgs): str       │
│ + search(vec, k): List   │     │ + generate_stream(msgs): str│
│ + delete(id): None       │     └──────────┬───────────────────┘
└──────────┬───────────────┘                │
           │                          ┌─────┴─────┐
     ┌─────┼─────┐                   │           │
     │     │     │            ┌──────▼──┐  ┌─────▼─────┐
┌────▼┐ ┌─▼──┐ ┌▼────┐       │LMStudio │  │OpenAI     │
│Chro-│ │FAIS│ │Pine│       │Client   │  │Client     │
│ma   │ │S   │ │cone│       └─────────┘  └───────────┘
└─────┘ └────┘ └────┘

┌─────────────────────────────────────────────────────────────┐
│                     RAGPipeline (Facade)                     │
├─────────────────────────────────────────────────────────────┤
│ - embedder: EmbeddingService                                 │
│ - store: VectorStore                                         │
│ - llm: LLMService                                            │
│ - chunk_size: int = 500                                      │
│ - top_k: int = 5                                             │
├─────────────────────────────────────────────────────────────┤
│ + query(question: str) -> Dict                                │
│ - _embed(question: str) -> List[float]                       │
│ - _retrieve(vector: List[float]) -> List[Chunk]               │
│ - _generate(context: List[Chunk], question: str) -> str       │
│ + index_document(path: str) -> int                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. DATA MODELS

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime

@dataclass
class Document:
    """Represents a loaded document before chunking."""
    content: str
    metadata: Dict[str, str] = field(default_factory=dict)
    source: str = ""
    loaded_at: datetime = field(default_factory=datetime.now)

@dataclass
class Chunk:
    """A chunk of a document with its embedding and metadata."""
    text: str
    metadata: Dict[str, str] = field(default_factory=dict)
    chunk_id: str = ""
    embedding: Optional[List[float]] = None
    source: str = ""

@dataclass
class SearchResult:
    """Result of a vector search."""
    chunk: Chunk
    similarity_score: float
    
@dataclass
class QueryResult:
    """Final result returned by the RAG pipeline."""
    answer: str
    sources: List[Dict]
    confidence: float
    latency_ms: int
```

---

## 3. SEQUENCE DIAGRAM — Query Flow

```
User        RAGPipeline     EmbeddingSvc    VectorStore     LLMService
 │              │               │               │              │
 │  query()     │               │               │              │
 │─────────────▶│               │               │              │
 │              │ embed_text()  │               │              │
 │              │──────────────▶│               │              │
 │              │   vector      │               │              │
 │              │◀──────────────│               │              │
 │              │               │               │              │
 │              │ search(vec,k) │               │              │
 │              │──────────────────────────────▶│              │
 │              │  [Chunk x 5]  │               │              │
 │              │◀──────────────────────────────│              │
 │              │               │               │              │
 │              │ generate(ctx,question)        │              │
 │              │─────────────────────────────────────────────▶│
 │              │   answer      │               │              │
 │              │◀─────────────────────────────────────────────│
 │  result      │               │               │              │
 │◀─────────────│               │               │              │
```

---

## 4. API CONTRACT

### Index Documents
```http
POST /api/index
Content-Type: multipart/form-data

file: @document.pdf
---
Response:
{
  "status": "success",
  "chunks_created": 42,
  "document_id": "doc_abc123"
}
```

### Query
```http
POST /api/query
Content-Type: application/json

{
  "question": "What is RAG?",
  "top_k": 5,
  "filter": {"category": "technical"}
}
---
Response:
{
  "answer": "RAG stands for Retrieval-Augmented Generation...",
  "sources": [
    {"text": "RAG combines retrieval...", "score": 0.92, "source": "rag_guide.pdf"}
  ],
  "latency_ms": 845
}
```

---

## 5. DATABASE SCHEMA (for persistent storage)

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    source_path TEXT,
    title TEXT,
    doc_metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id),
    chunk_index INT,
    text TEXT,
    embedding vector(384),  -- pgvector extension
    metadata JSONB
);

CREATE INDEX idx_chunks_embedding ON chunks 
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

---

## 6. CONFIGURATION

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    
    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    # Retrieval
    top_k: int = 5
    similarity_threshold: float = 0.7
    use_reranker: bool = False
    
    # LLM
    llm_provider: str = "lm_studio"  # "lm_studio" or "openai"
    lm_studio_url: str = "http://localhost:1234"
    llm_model: str = "gemma-4b-it"
    temperature: float = 0.3
    max_tokens: int = 1024
    
    # Vector Store
    vector_store: str = "chroma"  # "chroma", "faiss", "pinecone"
    persist_directory: str = "./data/vector_store"
    
    class Config:
        env_file = ".env"
```

---

## 7. STATE MACHINE — RAG Pipeline Lifecycle

```
        ┌──────────┐
        │  IDLE    │
        └────┬─────┘
             │ index_document()
             ▼
     ┌───────────────┐
     │  INDEXING     │── error → FAILED
     │  (load→chunk→ │
     │   embed→store)│
     └───────┬───────┘
             │ success
             ▼
     ┌───────────────┐
     │  READY        │
     └───────┬───────┘
             │ query()
             ▼
     ┌───────────────┐
     │  PROCESSING   │── error → ERROR
     │  (retrieve→   │
     │   generate)   │
     └───────┬───────┘
             │ success
             ▼
     ┌───────────────┐
     │  COMPLETE     │──▶ returns result
     └───────┬───────┘
             │
             ▼  (next query)
     ┌───────────────┐
     │  READY        │
     └───────────────┘
```
