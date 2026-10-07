# MCP Server Implementations

Three runnable MCP servers, written for the official Python SDK **v2** (`pip install "mcp>=2"`). In v2 the v1 `FastMCP` class is `MCPServer` (`from mcp.server.mcpserver import MCPServer`); the decorator API is the same.

```
servers/
├── calculator_server.py    # Tutorial: tools, resources, prompts, structured output
├── database_server.py      # Read-only PostgreSQL with auth, rate limit, circuit breaker
├── rag_server.py           # Wraps ../../rag/implementation as MCP tools
└── __init__.py
```

## Calculator (`calculator_server.py`)

| Primitive | Names |
|---|---|
| Tools | `add`, `subtract`, `multiply`, `divide`, `power`, `square_root`, `percentage` |
| Resources | `calculator://constants`, `calculator://help` |
| Prompts | `solve_equation`, `explain_formula` |

Shows two things worth knowing for interviews:

- **Structured output.** The `-> float` annotation becomes the tool's `outputSchema`, so a call returns `structuredContent: {"result": 8.0}` alongside the text block `"8.0"`.
- **Tool errors vs crashes.** `raise ToolError("Division by zero ...")` comes back as a result with `isError: true` and that message, so the model can correct itself. Any other exception is reported only as `Error executing tool divide`; the details stay in the server log.

## Database (`database_server.py`)

- Tool `query(sql, max_rows=100)`: read-only SQL, returned as a Markdown table.
- Resources: `database://schema/tables`, `database://schema/table/{table_name}` (a resource template), `database://health`.
- Guards, in order of strength: a read-only database role (yours to create), a read-only session with `statement_timeout`, then a `SELECT`/`WITH` prefix check that is only a friendly error, not a security boundary.
- Per-caller token-bucket rate limit and a circuit breaker around the database (from `../common`).
- Needs `database:read`. Over stdio, grant it locally with `MCP_STDIO_PERMISSIONS=database:read`; over HTTP it would come from the OAuth token's scopes.

## RAG (`rag_server.py`)

- Tools: `rag_query(question, top_k)` (retrieve and answer, with sources), `retrieve(question, top_k)` (chunks only), `index_document(file_path)`.
- Resources: `rag://status`, `rag://documents`. Prompt: `rag_debug`.
- `index_document` only reads under `RAG_ALLOWED_ROOT` (default `ai-engineering/rag/data`), so a prompt-injected model can't index `~/.ssh`.
- `USE_MOCK_LLM=true` answers without LM Studio.

## Running

From `ai-engineering/mcp/` (the servers import `common.*`, so run them as modules):

```bash
pip install -r requirements.txt

python -m servers.calculator_server            # stdio: normally launched BY a client, not by hand
MCP_TRANSPORT=streamable-http python -m servers.rag_server   # HTTP at http://127.0.0.1:8000/mcp

# Interactive debugging in a browser
npx @modelcontextprotocol/inspector python -m servers.calculator_server
```

On stdio, stdout carries the JSON-RPC messages, so the servers log only to stderr. A stray `print()` to stdout corrupts the stream and is the most common "my server hangs" bug.

## Connecting

```python
from mcp import Client, StdioServerParameters

params = StdioServerParameters(command="python", args=["-m", "servers.calculator_server"])
async with Client(params) as client:
    result = await client.call_tool("multiply", {"a": 15, "b": 27})
    print(result.structured_content)   # {'result': 405.0}
```

See [clients/](../clients/index.md) for the command-line client and desktop configuration.
