# 📚 RAG Module — Retrieval-Augmented Generation

> **From fundamentals to production deployment — complete RAG application learning resource**

---

## Overview

**Retrieval-Augmented Generation (RAG)** enhances LLM outputs by retrieving relevant information from a knowledge base before generating a response. Instead of relying solely on the model's training data, RAG grounds responses in factual, up-to-date, domain-specific information.

```
User Query → Retrieve (find relevant docs) → Augment (add context) → Generate (LLM response)
```

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [RAG Fundamentals](01_RAG_FUNDAMENTALS.md) | Core concepts, architecture, pipeline components |
| 2 | [LM Studio Integration](02_LM_STUDIO_INTEGRATION.md) | Local LLM setup with Gemma 4B via LM Studio |
| 3 | [Fine-Tuning Guide](03_FINE_TUNING.md) | Fine-tuning strategies for RAG pipelines |
| 4 | [RAG Interview Questions](04_INTERVIEW_QUESTIONS.md) | Principal Engineer-level Q&A |
| 5 | [Code Base Design](05_CODE_BASE_DESIGN.md) | Architecture decisions, design patterns, SOLID |
| 6 | [Low-Level Design](06_LOW_LEVEL_DESIGN.md) | Class diagrams, sequence diagrams, data models |
| 7 | [High-Level Design](07_HIGH_LEVEL_DESIGN.md) | Production system architecture, scaling |

## Implementation

- **[implementation/](implementation/)** — Working Python RAG chatbot (FastAPI, ChromaDB, LM Studio)
- **[test_pipeline.py](test_pipeline.py)** — End-to-end pipeline verification

## Quick Start

```bash
cd rag/
pip install -r implementation/requirements.txt
python implementation/main.py --index --docs ./data/documents/
python implementation/main.py --query "What is RAG and how does it work?"
```
