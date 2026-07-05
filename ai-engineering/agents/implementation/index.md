# 🤖 Agent Implementation Code

This directory contains runnable Python implementations of the agent architectures and components described in the [Agent Implementation Guide](../03_AGENT_IMPLEMENTATION_GUIDE.md).

## Module Overview

```
implementation/
├── common/                    # Shared infrastructure
│   ├── llm_client.py         # LLM provider abstraction (OpenAI, LM Studio, Mock)
│   ├── guardrails.py          # Input/output validation + rate limiter
│   ├── memory.py              # Short-term, working, and long-term memory
│   └── tool_registry.py       # Tool registration, schema validation, RBAC
├── simple_react_agent.py      # ReAct loop agent (plan → tool call → observe)
├── orchestrated_agent.py      # Async orchestrator-worker with dependency resolution
├── agent_with_mcp.py          # Agent discovering tools via MCP protocol
├── requirements.txt           # Python dependencies
└── __init__.py
```

## Core Components

### Simple ReAct Agent (`simple_react_agent.py`)

A straightforward ReAct (Reasoning + Acting) loop that:
- Takes a user query and iteratively plans, calls tools, and observes results
- Uses the tool registry for schema-validated tool execution
- Applies guardrails for input/output safety
- Manages conversation context via memory module
- Supports XML-based parsing of thought/action/observation patterns

**Usage:**
```bash
cd ai-engineering/agents
python -m implementation.simple_react_agent
```

### Orchestrated Agent (`orchestrated_agent.py`)

An async orchestrator that decomposes complex tasks into subtasks and delegates to specialized worker agents:
- `Orchestrator`: Generates execution plans with dependency graphs
- `WorkerAgent`: Executes individual subtasks with retry logic
- Resolves inter-worker dependencies automatically
- Supports parallel execution of independent subtasks

**Usage:**
```python
from implementation.orchestrated_agent import Orchestrator, WorkerAgent

orchestrator = Orchestrator(workers=[worker_a, worker_b])
result = await orchestrator.run("Complex task description")
```

### MCP-Connected Agent (`agent_with_mcp.py`)

An agent that connects to an MCP (Model Context Protocol) server to dynamically discover and use tools:
- Connects to MCP server via stdio
- Lists available tools via `tools/list`
- Executes tools via `tools/call`
- Falls back to mock tools when no MCP server is available

## Shared Infrastructure (`common/`)

| Module | File | Purpose |
|--------|------|---------|
| **LLM Client** | `llm_client.py` | Abstract base + OpenAI/Mock providers, configurable endpoints |
| **Guardrails** | `guardrails.py` | Regex pattern blocking, token bucket rate limiter |
| **Memory** | `memory.py` | Short-term (conversation), working (scratchpad), long-term (episodic) |
| **Tool Registry** | `tool_registry.py` | Tool registration with JSON Schema validation + RBAC |

## Running Tests

```bash
cd ai-engineering/agents
python -m pytest tests/ -v
```

## Dependencies

```bash
pip install -r implementation/requirements.txt
```

Key dependencies:
- `pydantic` — Data validation for tool schemas
- `httpx` — HTTP client for LLM API calls
- `jsonschema` — Tool parameter validation (fallback included)
- `pytest` and `pytest-asyncio` — Testing framework
