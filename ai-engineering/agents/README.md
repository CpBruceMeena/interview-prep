# 🤖 AI Agents Module

> **Architecture, orchestration, tool-use loops, production guardrails, and interview preparation**

---

## Overview

**AI agents** are autonomous systems that use LLMs to reason, plan, and execute actions. This module covers the engineering of production-grade agent systems — from single-agent ReAct loops to multi-agent coordination, MCP integration, and production deployment.

```
User Goal → Agent (Think → Act → Observe) → Tools/MCP → Result
```

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [Agent Fundamentals](01_AGENT_FUNDAMENTALS.md) | Core architectures (ReAct, Plan-and-Execute, Orchestrator-Worker), memory systems, tool-use patterns |
| 2 | [Agent Interview Questions](02_AGENT_INTERVIEW_QUESTIONS.md) | 10 Staff/Principal-level Q&A with evaluation rubric |
| 3 | [Agent Implementation Guide](03_AGENT_IMPLEMENTATION_GUIDE.md) | Building agents with runnable code, tool registries, MCP integration |
| 4 | [Agent Production Architecture](04_AGENT_PRODUCTION_ARCHITECTURE.md) | Production deployment, guardrails, observability, cost management |

## Implementation

- **[implementation/](implementation/index.md)** — Working Python agents:
  - `simple_react_agent.py` — Basic ReAct loop with tool registry
  - `orchestrated_agent.py` — Orchestrator-Worker pattern with async execution
  - `agent_with_mcp.py` — Agent discovering/using tools via MCP protocol
  - `common/` — Shared utilities: memory, guardrails, LLM client, tool registry

## Tests

- **[tests/](tests/index.md)** — Pytest test suite:
  - `test_simple_agent.py` — Agent loop, input/output guardrails, parsing
  - `test_orchestrated_agent.py` — Worker execution, multi-agent coordination

## Quick Start

```bash
cd agents/
pip install -r implementation/requirements.txt

# Run the ReAct agent (uses mock LLM by default)
python -m implementation.simple_react_agent

# Run the orchestrator agent
python -m implementation.orchestrated_agent

# Run the MCP-connected agent (requires MCP SDK)
python -m implementation.agent_with_mcp

# Run tests
python -m pytest tests/ -v
```

---

## Related Modules

- **[RAG Module](../rag/README.md)** — Knowledge retrieval for agents
- **[MCP Module](../mcp/README.md)** — Protocol for agent-tool communication
