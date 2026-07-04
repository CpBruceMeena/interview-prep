# 🧠 RAG Learning — Comprehensive Guide to Retrieval-Augmented Generation

> **From fundamentals to production deployment — a complete RAG application learning resource**

---

## 📋 What is RAG?

**Retrieval-Augmented Generation (RAG)** is an architecture that enhances LLM outputs by retrieving relevant information from a knowledge base before generating a response. Instead of relying solely on the model's training data, RAG grounds responses in factual, up-to-date, domain-specific information.

```
User Query → Retrieve (find relevant docs) → Augment (add context) → Generate (LLM response)
```

---

## 📑 Table of Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [RAG Fundamentals](01_RAG_FUNDAMENTALS.md) | Core concepts, architecture, pipeline components |
| 2 | [LM Studio Integration](02_LM_STUDIO_INTEGRATION.md) | Local LLM setup with Gemma 4B via LM Studio |
| 3 | [Fine-Tuning Guide](03_FINE_TUNING.md) | Fine-tuning strategies for RAG pipelines |
| 4 | [Interview Questions](04_INTERVIEW_QUESTIONS.md) | Principal Engineer-level Q&A |
| 5 | [Code Base Design](05_CODE_BASE_DESIGN.md) | Architecture decisions, design patterns, SOLID |
| 6 | [Low-Level Design](06_LOW_LEVEL_DESIGN.md) | Class diagrams, sequence diagrams, data models |
| 7 | [High-Level Design](07_HIGH_LEVEL_DESIGN.md) | Production system architecture, scaling |


---

## 🏗️ Core RAG Pipeline

```
                    ┌──────────────────┐
                    │   Documents      │
                    │   (PDF, HTML,    │
                    │    TXT, Markdown)│
                    └────────┬─────────┘
                             │ Chunking
                             ▼
                    ┌──────────────────┐
                    │  Document        │
                    │  Chunks          │
                    └────────┬─────────┘
                             │ Embedding
                             ▼
                    ┌──────────────────┐
                    │  Vector Store    │
                    │  (Chroma/FAISS)  │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │ User Query       │                  │
          ▼                  │                  │
  ┌──────────────┐          │                  │
  │ Query        │          │                  │
  │ Embedding    │          │                  │
  └──────┬───────┘          │                  │
         │ Semantic Search  │                  │
         ▼                  ▼                  │
  ┌──────────────────────────────────┐         │
  │       Retrieved Chunks          │         │
  └──────────────┬───────────────────┘         │
                 │ Context + Query              │
                 ▼                              │
        ┌────────────────────┐                 │
        │  LLM (Gemma 4B)   │◄────────────────┘
        │  via LM Studio    │
        └────────┬───────────┘
                 │ Generated Response
                 ▼
        ┌────────────────────┐
        │  Final Answer      │
        └────────────────────┘
```

---

## 🔧 Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Document Loader** | LangChain / Custom | Load and parse documents |
| **Text Splitter** | RecursiveCharacterTextSplitter | Chunk documents into segments |
| **Embedding Model** | sentence-transformers / OpenAI | Convert text to vectors |
| **Vector Store** | Chroma / FAISS | Store and search embeddings |
| **Retriever** | Vector store similarity search | Find relevant chunks |
| **LLM** | Gemma 4B via LM Studio | Generate grounded responses |
| **Orchestrator** | LangChain / Custom pipeline | Coordinate RAG flow |

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r implementation/requirements.txt

# 2. Start LM Studio with Gemma 4B
#    - Open LM Studio → Load Gemma 4B → Start Server

# 3. Index documents
python implementation/main.py --index --docs ./data/

# 4. Query the RAG chatbot
python implementation/main.py --query "What is RAG and how does it work?"
```

---

## 📚 Recommended Reading Order

1. Start with **RAG Fundamentals** → understand the architecture
2. Read **LM Studio Integration** → set up local LLM
3. Explore **Code Base Design** → understand implementation
4. Run the **Implementation** code → hands-on learning
5. Study **Interview Questions** → prepare for interviews
6. Review **LLD + HLD** → understand production concerns
7. Read **Fine-Tuning Guide** → advanced customization
