# 🔌 MCP Server Implementations

This directory contains runnable Python MCP (Model Context Protocol) server implementations that provide tools and resources for AI agents.

## Server Overview

```
servers/
├── calculator_server.py    # Basic arithmetic tools for agents
├── database_server.py      # Database query tools with SQL support
├── rag_server.py           # RAG retrieval tools for knowledge-augmented queries
├── requirements.txt        # Python dependencies
└── __init__.py
```

## Servers

### Calculator Server (`calculator_server.py`)

Provides mathematical operation tools for AI agents:
- **`add(a, b)`** — Addition of two numbers
- **`subtract(a, b)`** — Subtraction
- **`multiply(a, b)`** — Multiplication
- **`divide(a, b)`** — Division with error handling
- **`power(base, exp)`** — Exponentiation

**Usage:**
```python
from mcp.server import Server

server = Server("calculator")
server.add_tool(add, subtract, multiply, divide, power)
server.run()
```

### Database Server (`database_server.py`)

Provides database interaction tools:
- **`query(sql, params)`** — Execute SQL queries
- **`list_tables()`** — List available database tables
- **`describe(table)`** — Get schema for a specific table

Designed to work with SQLite for local development and PostgreSQL/Aurora in production.

### RAG Server (`rag_server.py`)

Provides retrieval-augmented generation tools for knowledge-augmented agent responses:
- **`search(query, top_k)`** — Vector search across indexed documents
- **`get_context(doc_id)`** — Retrieve full document context
- **`list_collections()`** — List available knowledge collections

Integrates with the vector store and embedding services from the RAG pipeline.

## Running Servers

Each server can be run independently:

```bash
cd ai-engineering/mcp/servers
python calculator_server.py
python database_server.py
python rag_server.py
```

## Connecting from an MCP Agent

```python
from implementation.agent_with_mcp import MCPAgent

agent = MCPAgent(mcp_server_command=["python", "ai-engineering/mcp/servers/calculator_server.py"])
result = await agent.run("Calculate 15 * 27")
```

## Dependencies

```bash
pip install mcp httpx pydantic
```
