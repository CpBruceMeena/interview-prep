# 🔌 MCP Module — Model Context Protocol

> **Architecture, server implementation, RAG integration, and production deployment**

---

## Overview

**Model Context Protocol (MCP)** is an open standard that provides a universal, standardized way for AI applications to connect to external data sources, tools, and systems. It's the "USB-C port for AI applications" — replacing fragmented, custom integrations with a single protocol.

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [MCP Fundamentals](01_MCP_FUNDAMENTALS.md) | Architecture, protocol mechanics, setup guide |
| 2 | [MCP Interview Questions](02_MCP_INTERVIEW_QUESTIONS.md) | Staff/Principal-level Q&A transcript |
| 3 | [MCP Implementation & RAG](03_MCP_IMPLEMENTATION.md) | Building custom MCP servers, RAG integration |
| 4 | [MCP Production Architecture](04_MCP_PRODUCTION_ARCHITECTURE.md) | Production deployment, security, tradeoffs |
| 5 | [MCP Explained (draw.io)](05_MCP_EXPLAINER_WITH_DRAWIO.md) | Step-by-step walkthrough with live diagramming example |

## Server Implementations

- **[servers/](servers/)** — MCP server code:
  - `calculator_server.py` — Simple math tools (tutorial)
  - `database_server.py` — PostgreSQL wrapper with rate limiting & auth
  - `rag_server.py` — RAG pipeline integration (uses `../rag/implementation/`)
- **[common/](common/)** — Shared utilities: rate limiter, circuit breaker, auth
- **[clients/](clients/)** — Python client and Claude Desktop config
- **[tests/](tests/)** — Pytest test suite

## Quick Start

```bash
cd mcp/
pip install -r requirements.txt

# Run the calculator server and list its tools
python -m servers.calculator_server &
python -m clients.python_client --server calculator --list

# Or use the MCP Inspector for interactive debugging
npx @anthropic/mcp-inspector python -m servers.calculator_server
```
