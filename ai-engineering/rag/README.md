# 📚 RAG Module — Retrieval-Augmented Generation

> **From fundamentals to production design, plus a small working RAG app.**

---

## Overview

**Retrieval-Augmented Generation (RAG)** improves LLM answers by first retrieving relevant passages from a knowledge base and putting them in the prompt. The model answers from current, domain-specific, citable sources instead of only its training data.

```
User Query → Retrieve (search the index) → Augment (add chunks to the prompt) → Generate (LLM answer + citations)
```

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [RAG Fundamentals](01_RAG_FUNDAMENTALS.md) | Pipeline stages, chunking, embeddings, vector stores, evaluation, common failures |
| 2 | [LM Studio Integration](02_LM_STUDIO_INTEGRATION.md) | Running a small local model (Gemma, Qwen, Llama...) behind an OpenAI-compatible API |
| 3 | [Fine-Tuning Guide](03_FINE_TUNING.md) | When and how to fine-tune embeddings, rerankers and the generator |
| 4 | [RAG Interview Questions](04_INTERVIEW_QUESTIONS.md) | 14 Senior/Staff-level questions: hybrid search, contextual retrieval, GraphRAG, evaluation, security |
| 5 | [Code Base Design](05_CODE_BASE_DESIGN.md) | How the implementation is structured: SOLID, patterns, error handling, tests |
| 6 | [Low-Level Design](06_LOW_LEVEL_DESIGN.md) | Class and sequence diagrams, data models, API contract, pgvector schema |
| 7 | [High-Level Design](07_HIGH_LEVEL_DESIGN.md) | Production architecture, capacity estimates, latency, cost model |

## Implementation

- **[implementation/](implementation/index.md)**: working Python RAG chatbot (FastAPI, ChromaDB, sentence-transformers, LM Studio)
- **`test_pipeline.py`**: end-to-end check over the sample corpus in `data/` (no LLM server needed)

## Quick Start

```bash
cd ai-engineering/rag
python -m venv .venv && source .venv/bin/activate
pip install -r implementation/requirements.txt

python test_pipeline.py                                   # index data/*.md into a temp store, run checks
python implementation/main.py --index --docs ./data       # index the sample corpus
python implementation/main.py --query "What is RAG and how does it work?"   # needs LM Studio running
```
