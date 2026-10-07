# 🏛️ Code Base Design — RAG Chatbot

> **How the code in [`implementation/`](implementation/index.md) is organised, which design principles it uses, and where it would need to change for production.** Snippets marked *(extension)* show how to grow the design; they are not in the repo.

---

## 1. PACKAGE STRUCTURE

```
ai-engineering/rag/
├── data/                          # Sample corpus (*.md) + committed demo Chroma store
├── test_pipeline.py               # End-to-end check (script, uses MockLLMService)
└── implementation/
    ├── requirements.txt
    ├── config.py                  # pydantic-settings: env vars / .env override defaults
    ├── document_loader.py         # Document + PDF/Text/HTML loaders + loader_for() factory
    ├── embedding_service.py       # EmbeddingService ABC, SentenceTransformer + OpenAI impls
    ├── vector_store.py            # Chunk, SearchResult, VectorStore ABC, ChromaVectorStore
    ├── retrieval_engine.py        # embed query → search → threshold → format context
    ├── llm_service.py             # LLMService ABC, OpenAI-compatible / LM Studio / Mock clients
    ├── rag_pipeline.py            # RAGPipeline facade: index + query (chunking lives here)
    ├── chatbot_api.py             # FastAPI app
    └── main.py                    # CLI: --index, --query, --interactive, --serve
```

Modules import each other as top-level modules (`from config import settings`), so run them from inside `implementation/` or with it on `sys.path` (as `test_pipeline.py` does). A production version would be a proper package with relative imports.

---

## 2. DESIGN PRINCIPLES APPLIED

### SOLID Principles

**S — Single Responsibility:**

| Class | Responsibility |
|-------|---------------|
| `DocumentLoader` subclasses | Parse one file type into `Document`s |
| `EmbeddingService` | Text → vectors |
| `VectorStore` | Store and search vectors + metadata |
| `RetrievalEngine` | Query → filtered, ranked chunks → context string |
| `LLMService` | Messages → completion text |
| `RAGPipeline` | Orchestration only |

Honest gap: chunking is a private method of `RAGPipeline`. Pulling it into a `Chunker` strategy (below) would make it swappable and testable on its own.

**O — Open/Closed:** add a format or backend by adding a class, not by editing callers.
```python
# In the repo
class PDFLoader(DocumentLoader): ...
class TextFileLoader(DocumentLoader): ...
class HTMLLoader(DocumentLoader): ...
class ChromaVectorStore(VectorStore): ...

# (extension)
class PgVectorStore(VectorStore): ...
class QdrantVectorStore(VectorStore): ...
```

**L — Liskov Substitution:** anything accepting `LLMService` works with `LMStudioClient`, `OpenAICompatibleClient` or `MockLLMService`, which is how `test_pipeline.py` runs without a model server. LSP is about *behavioural* contracts too: every `LLMService.generate` returns `None` on failure rather than raising, so callers can rely on that.

**I — Interface Segregation:**
```python
class EmbeddingService(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]: ...
    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]: ...
    def embed_query(self, query: str) -> List[float]:   # hook for query prefixes
        return self.embed_text(query)
    # NOT polluted with search, storage or generation methods
```

**D — Dependency Inversion:**
```python
class RAGPipeline:
    def __init__(self,
                 embedder: Optional[EmbeddingService] = None,  # abstractions in,
                 store: Optional[VectorStore] = None,          # defaults if omitted
                 llm: Optional[LLMService] = None,
                 loader: Optional[DocumentLoader] = None): ...
```
Constructor injection with defaults: convenient for the demo, and tests can inject fakes. The trade-off is that the defaults import heavy concrete classes; a composition root (factory in `main.py`) would keep the core free of them.

---

## 3. DESIGN PATTERNS USED

| Pattern | Where | Why |
|---------|-------|-----|
| **Facade** | `RAGPipeline` | One simple API (`index_*`, `query`) over five subsystems |
| **Strategy** | `EmbeddingService`, `VectorStore`, `LLMService` implementations | Swap providers by injection |
| **Factory** | `document_loader.loader_for(path)` | Pick the loader from the file extension |
| **Adapter** | `ChromaVectorStore`, `OpenAICompatibleClient` | Wrap a vendor API behind our interface (e.g. Chroma's distance → our similarity score) |
| **Template Method** *(extension)* | A base pipeline with overridable `rewrite → retrieve → rerank → generate` steps | Consistent flow, customisable steps |

Not used, deliberately: **Singleton**. The FastAPI app creates one pipeline in its lifespan hook and the CLI creates one in `main()`; passing instances around beats a global singleton for testing.

### Strategy Pattern Example *(extension)*
```python
class Chunker(ABC):
    @abstractmethod
    def split(self, text: str) -> List[str]: ...

class RecursiveChunker(Chunker):
    def __init__(self, size: int = 500, overlap: int = 50):
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
    def split(self, text: str) -> List[str]:
        return self._splitter.split_text(text)

class MarkdownHeadingChunker(Chunker):
    def split(self, text: str) -> List[str]:
        ...  # split on headings, prepend the heading path to each chunk
```

---

## 4. DATA FLOW

```
Indexing
1. config.py → settings (env vars / .env override defaults)
2. loader_for(path) / load_directory → Document(content, metadata{source, page, type})
3. RAGPipeline._chunk_documents → Chunks with deterministic IDs = hash(source|page|index)
4. ChromaVectorStore.delete_source(source) → remove the old version's chunks
5. EmbeddingService.embed_batch → normalised vectors
6. ChromaVectorStore.add_chunks → upsert in batches (Chroma caps batch size)

Query
7. RetrievalEngine.retrieve: embed_query → store.search(top_k) → drop score < threshold
8. RAGPipeline.query: format context with [Source N] labels → system + user messages
9. LLMService.generate → answer (or None → "model unavailable")
10. Return {answer, sources[{text, score, source}], latency_ms}
```

Retrieval runs **once** per query and the same results feed both the prompt and the returned citations, so citations always match what the model saw.

---

## 5. ERROR HANDLING STRATEGY

The repo uses **return-value degradation**: `LLMService.generate` logs and returns `None`, and the pipeline turns that into a friendly message (and the API into HTTP 503). That's fine for a demo. For production, typed exceptions let callers tell failures apart:

```python
class RAGError(Exception): ...
class EmbeddingError(RAGError): ...
class VectorStoreError(RAGError): ...
class LLMTimeoutError(RAGError): ...
class LLMUnavailableError(RAGError): ...

def query(self, question: str) -> Dict:
    try:
        results = self._retriever.retrieve(question)
        if not results:
            return {"answer": "I don't have enough information.", "sources": []}
        answer = self._llm.generate(self._build_messages(question, results))
        return {"answer": answer, "sources": [r.chunk.metadata for r in results]}
    except (LLMTimeoutError, LLMUnavailableError):
        # degrade: return the sources without a generated answer
        return {"answer": None, "sources": [...], "error": "llm_unavailable"}
    except VectorStoreError:
        raise          # can't answer without retrieval: let the API return 503
```

**Principles:** catch narrowly (a bare `except Exception` hides bugs); degrade where a partial answer is still useful (show sources when the LLM is down); log with a request ID; never return raw exception strings to users (they can leak internals).

---

## 6. TESTING STRATEGY

| Level | What | How |
|---|---|---|
| Unit | Chunk IDs deterministic, threshold filtering, context formatting, loaders | Fakes for `EmbeddingService` / `VectorStore` |
| Integration | Real embeddings + real Chroma in a **temp directory** + `MockLLMService` | `test_pipeline.py` |
| API | Status codes, validation, path confinement | FastAPI `TestClient` |
| Quality | Recall@k, faithfulness on a golden set | Eval job in CI, compared to a baseline |

```python
class FakeEmbedder(EmbeddingService):
    def embed_text(self, t): return [1.0, 0.0] if "rag" in t.lower() else [0.0, 1.0]
    def embed_batch(self, ts): return [self.embed_text(t) for t in ts]
    @property
    def dimension(self): return 2

def test_query_returns_sources(tmp_path):
    pipeline = RAGPipeline(
        embedder=FakeEmbedder(),
        store=ChromaVectorStore(persist_directory=str(tmp_path)),
        llm=MockLLMService("Retrieval-Augmented Generation [Source 1]"),
    )
    (tmp_path / "doc.md").write_text("RAG means Retrieval-Augmented Generation.")
    pipeline.index_document(str(tmp_path / "doc.md"))
    result = pipeline.query("What is RAG?")
    assert "Retrieval-Augmented" in result["answer"]
    assert result["sources"]
```

Mock-LLM tests prove the plumbing, not answer quality. Quality needs the eval set and a real model.
