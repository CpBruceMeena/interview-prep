# 🏭 Production AI Engineering

> **Staff/Principal-level interview preparation for production AI systems — debugging RAG, optimizing costs, designing enterprise agents, building multi-agent workflows, and securing MCP-based applications.**

---

## Overview

Production AI engineering bridges the gap between prototype and production. These 15 questions cover the most common failure modes, architectural decisions, and design challenges faced when deploying LLM-powered systems at scale.

!!! note "Currency"
    Reviewed against provider docs and the MCP spec as of **October 2026**. The answers avoid hard-coding model names and prices, which change every few months; where a version-sensitive detail matters (sampling parameters, prompt-caching pricing, MCP revision), it is dated in the text. Check current provider docs before quoting numbers in an interview.

---

## 📋 Questions Covered

### Part I — RAG & LLM Debugging

| # | Question | Key Topics |
|---|----------|------------|
| 1 | RAG hallucinates despite having the right context | Faithfulness diagnosis, lost-in-the-middle, citations, NLI/judge verification |
| 2 | RAG retrieval is too slow on a large knowledge base | HNSW/IVF-PQ/DiskANN, quantization, two-stage retrieval, caching |
| 3 | Model gives confident but wrong answers in high-risk situations | Uncertainty estimation (semantic entropy, self-consistency, log-probs), calibration, abstention, verification chain |
| 4 | RAG fails on multi-document reasoning | Query decomposition, Map-Reduce, Graph RAG, ReAct patterns |
| 5 | PM wants to ship with 15% edge case hallucinations | Risk assessment, guardrail proposals, phased rollout, escalation |

### Part II — Production AI Systems Design

| # | Question | Key Topics |
|---|----------|------------|
| 6 | RAG suddenly gives wrong answers | Incident triage, "what changed", version pinning, monitoring |
| 7 | Design a production AI coding assistant | Model routing, code indexing, sandboxing, prompt caching, observability |
| 8 | LLM latency jumps from 2s to 15s | TTFT vs decode, reasoning tokens, rate limits, prefix caching, self-hosted serving levers |
| 9 | Design an enterprise AI agent | Tenant isolation, RBAC, audit logging, human-in-loop, prompt injection, structured outputs |
| 10 | Build a multi-agent workflow | Workflows vs agents, orchestrator-workers, conflict resolution, token cost, single-agent tradeoffs |
| 11 | Same prompt gives different outputs | Temperature, Top-P, Seed, batch-invariance non-determinism, 2026 API restrictions |
| 12 | AI inference costs increased by 40% | Cost attribution, prompt caching, token budgets, routing, batch API |
| 13 | AI assistant works in testing but fails in production | Distribution shift analysis, triage metrics, LLM tracing (OpenTelemetry GenAI) |
| 14 | How to evaluate an LLM in production | Online/offline/safety/cost metrics, LLM-as-judge, hallucination detection without ground truth |
| 15 | Design an enterprise MCP-based AI application | MCP 2026-07-28 (stateless), gateway + OAuth, tool policies, DLP, encrypted memory |

---

## 🎯 Target Audience

- **Staff/Principal Software Engineers** preparing for AI engineering interviews
- **ML Infrastructure Engineers** building production RAG and agent systems
- **AI Architects** designing enterprise-grade LLM applications
- **Engineering Managers** evaluating production AI readiness

---

## 🔗 Quick Links

| Resource | Description |
|----------|-------------|
| [📄 Full Interview Questions & Answers](INTERVIEW_QUESTIONS.md) | Complete 15-question guide with code examples and follow-ups |
| [📚 RAG Interview Questions](../rag/04_INTERVIEW_QUESTIONS.md) | RAG-specific architecture, chunking, and production scaling |
| [🤖 Agent Interview Questions](../agents/02_AGENT_INTERVIEW_QUESTIONS.md) | Agent architecture, memory systems, and multi-agent coordination |
| [🔌 MCP Interview Questions](../mcp/02_MCP_INTERVIEW_QUESTIONS.md) | MCP protocol, server design, and production deployment |

---

## 💡 Key Principle

> In production AI engineering, the question is never *"does it work?"* but **"how do I know it's working, how quickly can I detect when it stops, and how do I mitigate the impact when it does?"**
