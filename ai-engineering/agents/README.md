# 🤖 AI Agents Module

> **Architecture, orchestration, tool-use loops, production guardrails, and interview preparation**

---

## Overview

**AI agents** are systems in which an LLM decides, in a loop, which tools to call and when to stop, rather than following a fixed code path. This module covers the engineering of production-grade agent systems — from single-agent ReAct loops to multi-agent coordination, MCP integration, and production deployment.

```
User Goal → Agent (Think → Act → Observe) → Tools/MCP → Result
```

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [Agent Fundamentals](01_AGENT_FUNDAMENTALS.md) | Core architectures (ReAct, Plan-and-Execute, Orchestrator-Worker), memory, tool-use patterns |
| 2 | [Agent Interview Questions](02_AGENT_INTERVIEW_QUESTIONS.md) | Staff-level Q&A with evaluation rubric |
| 3 | [Agent Implementation Guide](03_AGENT_IMPLEMENTATION_GUIDE.md) | Building agents: tool loops, tool registries, MCP integration |
| 4 | [Agent Production Architecture](04_AGENT_PRODUCTION_ARCHITECTURE.md) | Deployment, guardrails, cost management, trade-offs |
| 5 | [LangGraph Notes](05_LANGGRAPH_NOTES.md) | Graph-based agent state machines, checkpointers, human-in-the-loop |
| 6 | [Python Async & Await](06_PYTHON_ASYNC_AWAIT.md) | asyncio concurrency for agents: tasks, timeouts, cancellation |
| 7 | [Agent Observability](07_AGENT_OBSERVABILITY.md) | Tracing, metrics, OpenTelemetry GenAI conventions, evals in production |
| 8 | [Multi-LLM Architecture](08_MULTI_LLM_ARCHITECTURE.md) | Routing, cost management, fallback chains across providers |
| 9 | [Agent Deployment on ECS](09_AGENT_DEPLOYMENT_ECS.md) | Running agents on AWS ECS/Fargate: streaming, scaling, secrets |
| 10 | [System, User & Assistant Roles](10_SYSTEM_USER_ASSISTANT_ROLES.md) | Message roles, instruction hierarchy, prompt-injection boundaries |
| 11 | [Redis Lease](11_REDIS_LEASE.md) | Distributed locking with TTL, fencing tokens |
| 12 | [Search Autocorrect](12_SEARCH_AUTOCORRECT.md) | Misspelling handling and query correction |
| 13 | [Elasticsearch Internals](13_ELASTICSEARCH_INTERNALS.md) | Shards, segments, inverted index, near-real-time search |
| 14 | [Multi-LLM Production Ops](14_MULTI_LLM_PRODUCTION_OPS.md) | Token monitoring, rate limiting, caching, retries, A/B testing, alerting |
| 15 | [Agent Memory Systems](15_AGENT_MEMORY_SYSTEMS.md) | Short-term, long-term and episodic memory; retrieval and compaction |

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
cd ai-engineering/agents/
pip install -r implementation/requirements.txt

# Run the ReAct agent (uses mock LLM by default)
python -m implementation.simple_react_agent

# Run the orchestrator agent
python -m implementation.orchestrated_agent

# Run the MCP-connected agent (requires mcp>=2; it launches ../mcp/servers/calculator_server.py over stdio)
python -m implementation.agent_with_mcp

# Run tests
python -m pytest tests/ -v
```

---

## Related Modules

- **[RAG Module](../rag/README.md)** — Knowledge retrieval for agents
- **[MCP Module](../mcp/README.md)** — Protocol for agent-tool communication
