# 🤖 Agent Implementation Code

This directory contains runnable Python implementations of the agent architectures and components described in the [Agent Implementation Guide](../03_AGENT_IMPLEMENTATION_GUIDE.md).

## Module Overview

```
implementation/
├── common/                    # Shared infrastructure
│   ├── llm_client.py         # LLM client: Mock (default), OpenAI Responses API, OpenAI-compatible local servers
│   ├── guardrails.py          # Input/output validation + rate limiter
│   ├── memory.py              # Short-term, working, and long-term memory
│   └── tool_registry.py       # Tool registration, JSON Schema validation, RBAC, approval gate, timeouts
├── simple_react_agent.py      # ReAct loop agent (thought → tool call → observation)
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
- Parses the classic text format (`Thought:` / `Action:` / `ActionInput:` / `Answer:`) so it runs against any model or the mock. Production agents should use the provider's native tool calling instead of parsing free text; see [Agent Implementation Guide](../03_AGENT_IMPLEMENTATION_GUIDE.md).

**Usage:**
```bash
cd ai-engineering/agents
python -m implementation.simple_react_agent
```

### Orchestrated Agent (`orchestrated_agent.py`)

An async orchestrator that decomposes complex tasks into subtasks and delegates to specialized worker agents:
- `OrchestratorAgent`: builds a plan (a DAG of `Task`s; keyword-matched in the demo, LLM-generated in production)
- `WorkerAgent`: executes one task with its own tools (no retries in the demo; add them per task in production)
- Runs each "wave" of ready tasks concurrently with `asyncio.gather`, skips tasks whose dependencies failed, and detects cycles/missing dependencies

**Usage:**
```python
from implementation.orchestrated_agent import OrchestratorAgent, WorkerAgent

orchestrator = OrchestratorAgent(workers=[worker_a, worker_b])
result = await orchestrator.run("Complex task description")
```

### MCP-Connected Agent (`agent_with_mcp.py`)

An agent that connects to an MCP (Model Context Protocol) server to dynamically discover and use tools:
- Connects to the MCP server over stdio with `mcp.Client` (Python SDK v2, `mcp>=2`; it replaces v1's `stdio_client` + `ClientSession` + `initialize()`)
- Lists available tools via `tools/list`
- Executes tools via `tools/call` and surfaces `is_error` results (`isError` on the wire) as errors
- Reports and continues with zero tools if a server fails to start
- Demo simplification: spawns a fresh stdio server per call; a real host keeps one long-lived `Client` per server

## Shared Infrastructure (`common/`)

| Module | File | Purpose |
|--------|------|---------|
| **LLM Client** | `llm_client.py` | Mock (default), OpenAI Responses API, OpenAI-compatible local servers; model id from `LLM_MODEL` |
| **Guardrails** | `guardrails.py` | Regex deny-list and PII checks (teaching examples, easily bypassed), token bucket rate limiter |
| **Memory** | `memory.py` | Short-term (sliding window), working (task scratchpad), long-term (in-process key-value with TTL) |
| **Tool Registry** | `tool_registry.py` | JSON Schema validation (`additionalProperties: false`), RBAC, approval gate, per-tool timeout, audit log |

## Running Tests

```bash
cd ai-engineering/agents
python -m pytest tests/ -v
```

## Dependencies

```bash
pip install -r implementation/requirements.txt
```

Key dependencies (all optional except the test tools; the default mock LLM needs none of them):
- `openai` — Responses API client for real LLM calls
- `httpx` — HTTP client for OpenAI-compatible local servers
- `jsonschema` — Tool parameter validation (a minimal fallback is built in)
- `mcp` — MCP Python SDK for `agent_with_mcp.py`
- `pytest` and `pytest-asyncio` — Testing framework

To use a real model: `USE_MOCK_LLM=false LLM_PROVIDER=openai LLM_MODEL=<current model id> OPENAI_API_KEY=...`. Model ids change often, so the code does not hard-code one.
