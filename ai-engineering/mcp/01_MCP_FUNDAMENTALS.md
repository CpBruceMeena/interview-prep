# 🔌 MCP Fundamentals — Architecture, Protocol Mechanics & Setup Guide

> **Target:** Principal Engineer-level understanding of the Model Context Protocol (MCP)

---

## 1. WHAT IS MCP?

**Model Context Protocol (MCP)** is an open standard developed by Anthropic (late 2024) that provides a universal, standardized way for AI applications to connect to external data sources, tools, and systems. It's the "**USB-C port for AI applications**" — a single protocol that replaces fragmented, custom integrations.

### Why MCP? (Why not just use custom API endpoints?)

| Problem | Without MCP | With MCP |
|---------|-------------|----------|
| **Integration fragmentation** | Every AI tool needs bespoke adapters | One protocol, any MCP-compatible client |
| **Discovery** | Hardcoded tool definitions | Runtime capability negotiation (`tools/list`) |
| **Context management** | Manual context construction | Standardized Resources, Tools, Prompts |
| **Security boundaries** | Inconsistent auth patterns | Protocol-level sandboxing & validation |
| **Reusability** | Tied to specific LLM/provider | Portable across any MCP host |

---

## 2. CORE ARCHITECTURE

MCP follows a **client-server architecture** with three distinct roles:

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP HOST                                   │
│  (Claude Desktop, Cursor, custom agent framework)                 │
│  - Loads and coordinates MCP servers                              │
│  - Manages LLM interactions                                       │
│  - Routes tool calls / resource reads                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MCP CLIENT                                 │
│  (Protocol handler — 1:1 connection to a server)                 │
│  - Maintains transport connection (Stdio or SSE)                 │
│  - Sends JSON-RPC 2.0 requests                                   │
│  - Handles capability negotiation                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
│   MCP Server A   │ │  MCP Server B│ │   MCP Server C   │
│  (Database)       │ │ (File System)│ │  (Calculator)    │
└──────────────────┘ └──────────────┘ └──────────────────┘
```

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/mcp-protocol-flow.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated MCP Protocol Flow — User → MCP Host → Client → Server architecture with transport layer, capability negotiation, discovery, and execution lifecycle. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

### Role Breakdown

| Role | Responsibility | Examples |
|------|---------------|----------|
| **MCP Host** | The AI application that orchestrates connections | Claude Desktop, Cursor IDE, custom agent frameworks |
| **MCP Client** | Protocol handler — one per server connection | `mcp` Python SDK's `Client`, protocol transport layer |
| **MCP Server** | Exposes data and tools via the protocol | Database wrapper, file system access, API integrations |

---

## 3. CORE PRIMITIVES

MCP defines three fundamental primitives that servers can expose:

### 3.1 Resources

**Purpose:** Structured data sources that the LLM can **read** — analogous to GET endpoints in REST.

```json
// resources/list response
{
  "resources": [
    {
      "uri": "file:///logs/app-2025-01-01.txt",
      "name": "Application Logs (Jan 1)",
      "description": "Error logs for January 1st, 2025",
      "mimeType": "text/plain",
      "schema": { "type": "object", "properties": {...} }
    },
    {
      "uri": "database://users/active",
      "name": "Active Users",
      "description": "List of currently active users in the system",
      "mimeType": "application/json"
    }
  ]
}
```

**Key characteristics:**
- Schema-backed: Resources declare their data shape via JSON Schema
- Static or dynamic: Can be pre-defined or generated on read
- URI-addressed: Each resource has a unique URI for referencing
- Read-only by design: The LLM can consume but not modify resources

### 3.2 Tools

**Purpose:** Executable actions that the LLM can **invoke** — analogous to POST endpoints in REST.

```json
// tools/list response
{
  "tools": [
    {
      "name": "execute_sql",
      "description": "Execute a read-only SQL query against the analytics database",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": { "type": "string", "description": "SQL SELECT query" },
          "max_rows": { "type": "integer", "default": 100, "description": "Max rows to return" }
        },
        "required": ["query"]
      }
    },
    {
      "name": "send_email",
      "description": "Send an email notification to a user",
      "inputSchema": {
        "type": "object",
        "properties": {
          "to": { "type": "string", "format": "email" },
          "subject": { "type": "string", "maxLength": 200 },
          "body": { "type": "string" }
        },
        "required": ["to", "subject", "body"]
      }
    }
  ]
}
```

**Key characteristics:**
- Strict schema validation: Parameters are validated against JSON Schema before execution
- State-mutating: Tools can execute side effects (write, delete, transform)
- Result-returning: Each tool call returns a structured result (not streaming)
- LLM-decided: The host decides when to invoke a tool based on the conversation

### 3.3 Prompts

**Purpose:** Pre-defined, context-aware prompt templates stored server-side.

```json
// prompts/list response
{
  "prompts": [
    {
      "name": "analyze_error_log",
      "description": "Analyze application error logs and suggest fixes",
      "arguments": [
        {
          "name": "log_date",
          "description": "Date of logs to analyze (YYYY-MM-DD)",
          "required": true
        },
        {
          "name": "severity",
          "description": "Minimum severity level to analyze",
          "required": false,
          "default": "ERROR"
        }
      ]
    }
  ]
}
```

**Key characteristics:**
- Server-side: Templates live on the server, not hardcoded in the client
- Dynamic arguments: Can accept parameters to customize the prompt
- Context-enriched: Server can inject up-to-date data into the prompt template
- Guided interaction: Helps the LLM ask the right questions with proper context

---

## 4. TRANSPORT LAYER

MCP supports two transport mechanisms, each optimized for different deployment scenarios:

### 4.1 Stdio Transport (Standard Input/Output)

```
┌─────────────────────────────────────────┐
│              MCP HOST                     │
│                                          │
│  ┌─────────────────────────────────┐    │
│  │        MCP Client               │    │
│  │  stdin  ◄── JSON-RPC 2.0 ──► stdout │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│                 │ Child process           │
│                 ▼                        │
│  ┌─────────────────────────────────┐    │
│  │        MCP Server                │    │
│  │  (local Python process)          │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**Best for:** Local development, desktop applications, CLI tools

**Characteristics:**
- **No network overhead** — IPC via pipes, sub-millisecond latency
- **Inherently secure** — no open ports, no network attack surface
- **Process isolation** — server runs as separate OS process
- **Simple lifecycle** — host spawns server as child process
- **No auth needed** — trust established via local execution

**Limitations:**
- Single client per server process
- Server process tied to host lifecycle
- Not suitable for distributed/remote deployments

### 4.2 Streamable HTTP (SSE - Server-Sent Events)

```
┌──────────────────┐         ┌──────────────────────────────┐
│    MCP Client     │  HTTP   │       MCP Server             │
│  (Remote)         │◄──────►│  (Remote Microservice)       │
│                   │  SSE    │                              │
│  POST /api/mcp    │  POST   │  - Authentication (Bearer)  │
│  GET  /api/mcp/sse│  STREAM │  - Rate limiting             │
└──────────────────┘         │  - Load balancing            │
                              │  - Horizontal scaling         │
                              └──────────────────────────────┘
```

**Best for:** Production deployments, distributed systems, multi-tenant services

**Characteristics:**
- **Remote access** — server can run anywhere with HTTP connectivity
- **Scalable** — multiple clients can connect to one server
- **Standard auth** — Bearer tokens, OAuth2, API keys
- **Observable** — standard HTTP metrics, logging, tracing

**Limitations:**
- Network latency (5-50ms per round trip)
- Requires authentication infrastructure
- TLS termination needed
- Connection management (reconnection, heartbeat)

---

## 5. PROTOCOL LIFECYCLE

The MCP communication follows a structured lifecycle:

```
┌─────────────────────────────────────────────────────────────┐
│                    CONNECTION LIFECYCLE                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  STEP 1: Transport Connection                                │
│  ├── Stdio: Host spawns server process                       │
│  └── HTTP:  Client connects to server endpoint               │
│                                                              │
│  STEP 2: Capability Negotiation (initialize)                 │
│  ├── Client sends: protocol version, client capabilities     │
│  └── Server responds: protocol version, server capabilities  │
│                                                              │
│  STEP 3: Server Discovery                                    │
│  ├── Client requests: tools/list                             │
│  ├── Client requests: resources/list                         │
│  └── Client requests: prompts/list                           │
│                                                              │
│  STEP 4: Operation                                           │
│  ├── Read resource: resources/read {uri}                     │
│  ├── Call tool: tools/call {name, arguments}                 │
│  └── Get prompt: prompts/get {name, arguments}               │
│                                                              │
│  STEP 5: Shutdown                                            │
│  ├── Close transport connection                              │
│  └── Cleanup server resources                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Initialization Handshake

```json
// Client → Server (initialize)
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "roots": { "listChanged": true },
      "sampling": {}
    },
    "clientInfo": {
      "name": "my-agent",
      "version": "1.0.0"
    }
  },
  "id": 1
}

// Server → Client (initialize result)
{
  "jsonrpc": "2.0",
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "tools": {},           // Server exposes tools
      "resources": {},       // Server exposes resources
      "prompts": {}         // Server exposes prompts
    },
    "serverInfo": {
      "name": "my-db-server",
      "version": "1.0.0"
    }
  },
  "id": 1
}
```

---

## 6. SETUP GUIDE — INSTALLING & RUNNING MCP

### 6.1 Python SDK — FastMCP (Recommended)

**Prerequisites:** Python 3.10+ and `uv` (recommended) or `pip`

```bash
# Install the MCP Python SDK
pip install mcp

# Or with uv (faster)
uv add mcp
```

### 6.2 Creating Your First MCP Server

```python
# server.py
from mcp.server.fastmcp import FastMCP

# Initialize server
mcp = FastMCP("MyFirstMCPServer")

# ── Define a Tool ──
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

# ── Define a Resource ──
@mcp.resource("config://app")
def get_config() -> str:
    """Return application configuration as a resource."""
    return "version: 1.0.0\ndatabase: postgresql://localhost:5432/app"

# ── Define a Prompt ──
@mcp.prompt()
def analyze_error(error: str) -> str:
    """Create a prompt template for error analysis."""
    return f"Analyze the following error and suggest a fix:\n\n{error}"

if __name__ == "__main__":
    # Run with stdio transport (default for local use)
    mcp.run(transport="stdio")
```

### 6.3 Testing Your Server

```bash
# Run the server directly (it will wait for stdin communication)
python server.py

# Test with MCP Inspector (built-in debug tool)
npx @anthropic/mcp-inspector python server.py
```

### 6.4 Connecting from a Client

**Claude Desktop (macOS):**
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-calculator": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

**Custom Python Client:**

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # Configure server
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")
            
            # Call a tool
            result = await session.call_tool("add", {"a": 5, "b": 3})
            print(f"Result: {result.content[0].text}")
            
            # List resources
            resources = await session.list_resources()
            print(f"Available resources: {[r.uri for r in resources.resources]}")

asyncio.run(main())
```

### 6.5 Running with Streamable HTTP (Production)

```python
# server_http.py
from mcp.server.fastmcp import FastMCP
import uvicorn

mcp = FastMCP("ProductionMCP", port=8000)

@mcp.tool()
def query_database(sql: str) -> str:
    """Execute a read-only SQL query."""
    # Your database logic here
    return f"Results for: {sql}"

if __name__ == "__main__":
    # Run with SSE transport for remote access
    mcp.run(transport="sse")
```

```bash
python server_http.py
# Server starts on http://localhost:8000
# SSE endpoint: http://localhost:8000/api/mcp/sse
# POST endpoint: http://localhost:8000/api/mcp
```

---

## 7. MCP vs TRADITIONAL APPROACHES

| Aspect | MCP | Custom Webhook/REST | Function Calling (OpenAI) |
|--------|-----|--------------------|--------------------------|
| **Standardization** | Universal protocol | Ad-hoc per service | Provider-specific |
| **Discovery** | Built-in (`list`) | Documentation | Schema definition |
| **Auth** | Transport-level | Per-endpoint | API key |
| **Context** | Resources + Prompts | Manual construction | System message |
| **Transport** | Stdio / HTTP | HTTP | HTTP |
| **Schema** | JSON Schema (strict) | Varies | JSON Schema |
| **State** | Stateless (JSON-RPC) | Session-managed | Stateless |
| **Security boundary** | Process isolation | Network ACLs | API boundary |
| **LLM control** | Host decides tool calls | Hardcoded | Model decides |

---

## 8. KEY DESIGN PRINCIPLES

1. **Decoupling:** Separates orchestration (host) from execution (server)
2. **Discoverability:** Servers advertise capabilities at runtime — no hardcoding
3. **Safety by default:** Strict schema validation prevents hallucinated parameters
4. **Transport agnostic:** Same protocol works locally (stdio) and remotely (HTTP)
5. **Stateless protocol:** Each request is independent — simplifies scaling
6. **LLM-friendly:** Primitives designed for how LLMs consume and produce information

---

## 9. COMMON MCP CHALLENGES

| Challenge | Problem | Solution |
|-----------|---------|----------|
| **Context window overflow** | Resource returns too much data | Pagination, semantic chunking, summarization |
| **Latency amplification** | Nested tool calls add up | Parallel tool execution, caching |
| **Hallucinated parameters** | LLM invents tool arguments | Strict JSON Schema validation, allowlists |
| **Infinite execution loops** | LLM retries failing tools endlessly | Max retry count, circuit breaker |
| **State management** | MCP is stateless | Session IDs, context propagation |
| **Auth propagation** | User auth across tool calls | JWT passthrough with validation |

---

> **Next:** [MCP Interview Questions](02_MCP_INTERVIEW_QUESTIONS.md) → Staff/Principal-level Q&A transcript
