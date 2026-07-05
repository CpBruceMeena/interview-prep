# 📚 RAG Fundamentals — Complete Architecture Guide

> **Target:** Principal Engineer-level understanding of Retrieval-Augmented Generation

---

## 1. WHAT IS RAG?

**Retrieval-Augmented Generation (RAG)** is an AI architecture that combines information retrieval with text generation. When a user asks a question, RAG:

1. **Retrieves** relevant documents/chunks from a knowledge base
2. **Augments** the LLM prompt with this retrieved context
3. **Generates** a response grounded in the retrieved information

### Why RAG? (Why not just use an LLM directly?)

| Problem | Without RAG | With RAG |
|---------|-------------|----------|
| **Outdated knowledge** | Model stuck at training data cutoff | Queries live, updated documents |
| **Hallucination** | LLM may invent facts | Grounded in retrieved context |
| **Domain specificity** | General knowledge only | Can use proprietary/domain docs |
| **Cost** | Fine-tuning expensive | No model training needed |
| **Updates** | Must retrain to update | Just update the document store |

---

## 2. RAG ARCHITECTURE — FULL PIPELINE

```
                         ┌─────────────────────────────┐
                         │      DATA INGESTION          │
                         │                              │
    ┌──────────┐   ┌─────▼──────┐   ┌──────────┐   ┌──▼───────┐   ┌─────────────┐
    │ Raw      │   │ Document   │   │ Text     │   │Embedding  │   │ Vector      │
    │ Docs     │──▶│ Loader     │──▶│ Splitter │──▶│ Model     │──▶│ Store       │
    │(PDF/TXT) │   │            │   │(Chunks)  │   │           │   │(Chroma/    │
    └──────────┘   └────────────┘   └──────────┘   └───────────┘   │ FAISS)      │
                                                                    └─────────────┘
                                                                          │
                         ┌──────────────────────────────┐                 │
                         │      QUERY PIPELINE           │                │
                         │                               │                │
    ┌──────────┐   ┌─────▼──────┐   ┌──────────┐   ┌────▼───────┐        │
    │ User     │   │ Query      │   │ Semantic  │   │ Retrieved  │        │
    │ Query    │──▶│ Embedding  │──▶│ Search    │──▶│ Chunks     │◄───────┘
    └──────────┘   └────────────┘   └──────────┘   └────┬───────┘
                                                         │
    ┌──────────┐   ┌────────────┐   ┌──────────┐        │
    │ Final    │◀──│ LLM        │◀──│ Prompt   │◀───────┘
    │ Answer   │   │(Gemma 4B)  │   │ Assembly │
    └──────────┘   └────────────┘   └──────────┘
```

---

## 3. COMPONENT DEEP DIVE

### 3.1 Document Loading

**Purpose:** Load documents from various sources into a standard text format.

```python
class DocumentLoader:
    def load_pdf(self, path) -> str:     # PyMuPDF / pdfplumber
    def load_html(self, path) -> str:    # BeautifulSoup
    def load_markdown(self, path) -> str:  # Direct read
    def load_directory(self, path) -> List[str]:  # Recursive load
```

**Key decisions:**
- PDF: Use `PyMuPDF` (fast) over `PyPDF2` (slower)
- HTML: Strip scripts/styles, extract `<main>` or `<article>` content
- Large files: Stream, don't load entirely into memory

---

### 3.2 Text Chunking

**Purpose:** Split documents into manageable, semantically meaningful chunks.

**Chunking Strategies:**

| Strategy | Method | Best For |
|----------|--------|----------|
| **Fixed size** | Split every N characters | Simple, predictable |
| **Recursive** | Split on paragraph → sentence → word | Maintains context (recommended) |
| **Semantic** | Split at topic boundaries | Maximum coherence |
| **Agentic** | LLM decides splits | Best quality, slowest |

**Recommended — RecursiveCharacterTextSplitter:**
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # Characters per chunk
    chunk_overlap=50,    # Overlap to maintain context
    separators=["\n\n", "\n", ".", " ", ""]  # Priority order
)
```

**Why 500 tokens?** Short enough for accurate retrieval, long enough for coherent context. 50-token overlap prevents information loss at boundaries.

---

### 3.3 Embedding Models

**Purpose:** Convert text chunks into dense vector representations.

**Types of embedding models:**
- **Local:** sentence-transformers (`all-MiniLM-L6-v2`, `bge-small-en-v1.5`)
- **API:** OpenAI `text-embedding-3-small`, Cohere `embed-english-v3.0`

**Dimension comparison:**
| Model | Dimensions | Speed | Quality |
|-------|-----------|-------|---------|
| all-MiniLM-L6-v2 | 384 | ⚡⚡⚡ | Good |
| bge-small-en-v1.5 | 384 | ⚡⚡⚡ | Better |
| text-embedding-3-small | 1536 | ⚡⚡ | Best (API) |

---

### 3.4 Vector Store

**Purpose:** Store embeddings and enable fast similarity search.

| Store | Type | Use Case |
|-------|------|----------|
| **Chroma** | Local, persisted | Development, small-med scale |
| **FAISS** | In-memory | High performance, batch processing |
| **Pinecone** | Cloud, managed | Production at scale |
| **Weaviate** | Self-hosted | Production, custom deployment |

**Similarity search methods:**
- **Cosine similarity:** Best for semantic search (recommended)
- **Dot product:** Faster, but magnitude-dependent
- **Euclidean distance:** Sensitive to scale

---

### 3.5 Retrieval Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| **Simple similarity** | Top-K by cosine distance | General purpose |
| **MMR (Maximal Marginal Relevance)** | Diversity + relevance | Avoiding redundancy |
| **Hybrid (dense + sparse)** | BM25 + dense embeddings | Recall improvement |
| **Parent retriever** | Retrieve small chunks, return parent | Context preservation |

---

### 3.6 Prompt Assembly

**The key prompt template:**
```python
SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's question 
based ONLY on the following context. If the context doesn't contain enough 
information, say "I don't have enough information to answer that."

Context:
{context}

Question: {question}

Answer:"""
```

---

### 3.7 LLM (Gemma 4B via LM Studio)

**Communication via OpenAI-compatible API:**
```python
POST http://localhost:1234/v1/chat/completions
{
  "model": "gemma-4b-it",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.3,
  "max_tokens": 1024
}
```

---

## 4. RAG EVALUATION METRICS

| Metric | What It Measures | Target |
|--------|-----------------|--------|
| **Hit Rate** | % of queries with relevant retrieved chunks | >90% |
| **MRR** | Mean Reciprocal Rank of first relevant chunk | >0.8 |
| **NDCG** | Normalized Discounted Cumulative Gain | >0.85 |
| **Faithfulness** | % of claims supported by retrieved context | >95% |
| **Answer Relevance** | How well answer addresses the question | >4/5 |

---

## 5. COMMON RAG CHALLENGES

| Challenge | Problem | Solution |
|-----------|---------|----------|
| **Low retrieval quality** | Wrong chunks returned | Better embeddings, hybrid search |
| **Context window overflow** | Too many retrieved chunks | Limit chunks, summarize |
| **Hallucination with context** | LLM ignores retrieved docs | Stronger prompting, lower temperature |
| **Latency** | Retrieval + generation too slow | Chunk caching, async, smaller model |
| **Stale data** | Retrieved content outdated | Document refresh pipeline |
