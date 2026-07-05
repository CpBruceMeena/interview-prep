# 🔌 MCP Client Implementations

Client-side code for connecting to MCP (Model Context Protocol) servers.

## Module Overview

```
clients/
├── python_client.py      # Python MCP client
├── claude_config.json    # Claude Desktop configuration
└── __init__.py
```

## Components

### Python Client (`python_client.py`)
A Python client for connecting to MCP servers:
- **Connection management** — Establish and maintain MCP connections
- **Tool discovery** — List available server tools
- **Tool execution** — Call tools and retrieve results
- **Error handling** — Graceful handling of connection failures

**Usage:**
```python
from mcp.clients.python_client import MCPClient

client = MCPClient(server_url="http://localhost:8000")
tools = client.list_tools()
result = client.call_tool("calculator", {"a": 10, "b": 20})
```

### Claude Config (`claude_config.json`)
Configuration file for connecting to MCP servers from Claude Desktop:

```json
{
  "mcpServers": {
    "calculator": {
      "command": "python",
      "args": ["ai-engineering/mcp/servers/calculator_server.py"]
    }
  }
}
```
