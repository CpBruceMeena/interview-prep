# 🔌 MCP Module — Model Context Protocol

> **Architecture, server implementation, RAG integration, and production deployment**

---

## Overview

**Model Context Protocol (MCP)** is an open standard, introduced by Anthropic in November 2024 and since December 2025 governed under the Linux Foundation's Agentic AI Foundation, for connecting AI applications to tools, data and prompts. One protocol replaces an N×M matrix of custom integrations: write a server once and any MCP host can use it.

The current spec revision is **2026-07-28**, which made the protocol stateless (no `initialize` handshake or sessions). Pages here call out where earlier revisions (2025-03-26, 2025-06-18, 2025-11-25) differ, because interviewers and most deployed servers still reference them.

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [MCP Fundamentals](01_MCP_FUNDAMENTALS.md) | Architecture, protocol mechanics, setup guide |
| 2 | [MCP Interview Questions](02_MCP_INTERVIEW_QUESTIONS.md) | Staff/Principal-level Q&A transcript |
| 3 | [MCP Implementation & RAG](03_MCP_IMPLEMENTATION.md) | Building custom MCP servers, RAG integration |
| 4 | [MCP Production Architecture](04_MCP_PRODUCTION_ARCHITECTURE.md) | Production deployment, security, tradeoffs |
| 5 | [MCP Explained (draw.io)](05_MCP_EXPLAINER_WITH_DRAWIO.md) | Step-by-step walkthrough with a diagramming example |

## Server Implementations

- **[servers/](servers/index.md)** — MCP server code:
  - `calculator_server.py` — Simple math tools (tutorial)
  - `database_server.py` — PostgreSQL wrapper with rate limiting & auth
  - `rag_server.py` — RAG pipeline integration (uses `../rag/implementation/`)
- **[common/](common/index.md)** — Shared utilities: rate limiter, circuit breaker, auth
- **[clients/](clients/index.md)** — Python client and Claude Desktop config
- **[tests/](tests/index.md)** — Pytest test suite

## Quick Start

The code targets the official Python SDK v2 (`mcp>=2`, spec revision 2026-07-28).

```bash
cd ai-engineering/mcp/
pip install -r requirements.txt

# The client launches the stdio server itself; no need to start it first
python -m clients.python_client --server calculator --list

# Interactive debugging with the MCP Inspector
npx @modelcontextprotocol/inspector python -m servers.calculator_server

# Tests
python -m pytest tests/ -v
```
