# 🏛️ Code Base Design — RAG Chatbot

> **Architecture decisions, design patterns, SOLID principles, and code organization**

---

## 1. PACKAGE STRUCTURE

```
ai-engineering/rag/
├── implementation/
│   ├── requirements.txt
│   ├── config.py                  # Configuration & constants
│   ├── document_loader.py         # Document ingestion
│   ├── text_splitter.py           # Chunking strategies
│   ├── embedding_service.py       # Embedding model wrapper
│   ├── vector_store.py            # Vector database abstraction
│   ├── retrieval_engine.py        # Retrieval + reranking
│   ├── llm_service.py             # LM Studio / LLM interface
│   ├── rag_pipeline.py            # Main RAG orchestrator
│   ├── chatbot_api.py             # FastAPI web server
│   └── main.py                    # CLI entry point
```

---

## 2. DESIGN PRINCIPLES APPLIED

### SOLID Principles

**S — Single Responsibility:**
| Class | Responsibility |
|-------|---------------|
| `DocumentLoader` | Only loads and parses documents |
| `EmbeddingService` | Only converts text to embeddings |
| `VectorStore` | Only stores and searches vectors |
| `LLMService` | Only communicates with LM Studio |

**O — Open/Closed:**
```python
# New document format? Add new loader subclass
class PDFLoader(DocumentLoader): ...
class HTMLLoader(DocumentLoader): ...
class MarkdownLoader(DocumentLoader): ...

# New vector store? Add new implementation
class ChromaVectorStore(VectorStore): ...
class FAISSVectorStore(VectorStore): ...
class PineconeVectorStore(VectorStore): ...
```

**L — Liskov Substitution:**
Any `DocumentLoader` subclass can replace `DocumentLoader` anywhere.

**I — Interface Segregation:**
```python
class EmbeddingService(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]: pass
    
    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]: pass
    
    # NOT polluted with search, storage, or generation methods
```

**D — Dependency Inversion:**
```python
class RAGPipeline:
    def __init__(
        self,
        embedding_service: EmbeddingService,  # Abstraction
        vector_store: VectorStore,             # Abstraction
        llm_service: LLMService,               # Abstraction
    ):
        # High-level module depends on abstractions, not concrete implementations
```

---

## 3. DESIGN PATTERNS USED

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Text splitting, Embedding models | Swap strategies at runtime |
| **Factory** | Document loader creation | Create loader based on file type |
| **Facade** | RAGPipeline | Unified interface over subsystems |
| **Adapter** | LM Studio API | Adapts OpenAI-compatible API |
| **Template Method** | RAG pipeline flow | Consistent: retrieve → augment → generate |
| **Singleton** | Vector store connection | Single connection pool |

### Strategy Pattern Example:
```python
class SplittingStrategy(ABC):
    @abstractmethod
    def split(self, text: str) -> List[str]: pass

class RecursiveSplitter(SplittingStrategy):
    def split(self, text):
        return RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50
        ).split_text(text)

class SemanticSplitter(SplittingStrategy):
    def split(self, text):
        # Use embeddings to find topic boundaries
        ...
```

---

## 4. DATA FLOW

```
1. config.py → loads settings (model name, chunk size, etc.)
2. DocumentLoader → loads raw text from files
3. TextSplitter → chunks text into segments
4. EmbeddingService → converts chunks to vectors
5. VectorStore → stores vectors with metadata

6. User Query → EmbeddingService (embed query)
7. VectorStore → similarity search (top-5 chunks)
8. RetrievalEngine → rerank chunks, filter by threshold
9. RAGPipeline → assemble prompt with context
10. LLMService → generate response via LM Studio
11. Return answer to user
```

---

## 5. ERROR HANDLING STRATEGY

```python
class RAGError(Exception): pass
class EmbeddingError(RAGError): pass
class VectorStoreError(RAGError): pass
class LLMServiceError(RAGError): pass

class RAGPipeline:
    def query(self, question: str) -> Dict:
        try:
            # 1. Embed
            query_vector = self.embedder.embed_text(question)
            
            # 2. Retrieve
            chunks = self.retriever.retrieve(query_vector, top_k=5)
            if not chunks:
                return {"answer": "I don't have enough information.", "sources": []}
            
            # 3. Generate
            answer = self.llm.generate(context=chunks, question=question)
            return {"answer": answer, "sources": [c.metadata for c in chunks]}
            
        except LLMServiceError:
            return {"answer": "LLM is unavailable. Please try again later.", "error": True}
        except Exception as e:
            return {"answer": "An error occurred.", "error": str(e)}
```

---

## 6. TESTING STRATEGY

```python
def test_rag_pipeline():
    # Unit tests
    test_embedding_service()
    test_vector_store()
    test_llm_service()
    
    # Integration test
    pipeline = RAGPipeline(
        embedder=MockEmbeddingService(),  # Returns known vectors
        store=MockVectorStore(),          # Returns known chunks
        llm=MockLLMService()              # Returns fixed response
    )
    result = pipeline.query("What is RAG?")
    assert "Retrieval-Augmented" in result["answer"]
    assert len(result["sources"]) > 0
```
