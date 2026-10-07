# MCP Client Implementations

```
clients/
├── python_client.py      # Command-line client for the servers in ../servers
├── claude_config.json    # Example desktop-client (mcpServers) configuration
└── __init__.py
```

## Python client (`python_client.py`)

Built on the SDK v2 `mcp.Client`, which replaces v1's `stdio_client` + `ClientSession` + `initialize()` boilerplate. Against a server on the 2026-07-28 spec it skips the handshake (it probes `server/discover`, then every request carries its version and capabilities in `_meta`); against older servers it falls back to `initialize` automatically.

```bash
cd ai-engineering/mcp
python -m clients.python_client --server calculator --list        # tools, resources, prompts
python -m clients.python_client --server calculator --add 5 3
python -m clients.python_client --server rag --query "What is RAG?"
python -m clients.python_client --server calculator --interactive # /tools /call /read ...
```

In your own code:

```python
from mcp import Client, StdioServerParameters

async with Client(StdioServerParameters(command="python", args=["-m", "servers.calculator_server"])) as client:
    tools = await client.list_tools()
    result = await client.call_tool("add", {"a": 10, "b": 20})
    print(result.content[0].text, result.structured_content)   # "30.0" {'result': 30.0}

async with Client("https://mcp.example.com/mcp") as client:    # Streamable HTTP
    ...
```

`result.content` is what you would show a model; `result.structured_content` is what program code should parse. Check `result.is_error` before using either.

## Desktop configuration (`claude_config.json`)

Hosts such as Claude Desktop and IDE agents read an `mcpServers` map: each entry is a command the host launches as a **stdio subprocess**. The host does not set your working directory, so tell Python where the package is:

```json
{
  "mcpServers": {
    "calculator": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "servers.calculator_server"],
      "env": { "PYTHONPATH": "/absolute/path/to/interview-prep/ai-engineering/mcp" }
    }
  }
}
```

Remote servers are added by URL instead (Streamable HTTP, usually with OAuth); the exact config key varies by host, so check its docs.
