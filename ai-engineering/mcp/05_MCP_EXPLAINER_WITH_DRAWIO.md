# 🎯 MCP Explained — Step by Step with a Live Example (draw.io)

> **A practical, hands-on walkthrough of how the Model Context Protocol works — using a draw.io diagramming server as our concrete example.**

---

## 1. THE BIG PICTURE

Before we dive into code, let's understand **where MCP fits** in the AI stack:

```ascii
┌──────────────────────────────────────────────────────────────────────┐
│                       USER (You)                                      │
│  "Create a class diagram for a parking lot system"                    │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    MCP HOST (Claude Desktop / Agent)                   │
│                                                                       │
│  1. LLM receives your request                                         │
│  2. LLM decides: "I need a diagramming tool"                          │
│  3. LLM asks host: "What tools do I have?"                            │
│  4. Host connects to MCP Server → discovers tools                     │
│  5. LLM chooses a tool → Host sends `tools/call` to server           │
│  6. Server executes → returns result                                  │
│  7. LLM processes result → responds to you                            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           │ MCP Protocol (JSON-RPC 2.0 over stdio/HTTP)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      MCP SERVER (draw.io Server)                       │
│                                                                       │
│  Registers tools:                                                     │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ • create_diagram(type, title)    → creates a blank diagram     │  │
│  │ • add_class(uml_class)           → adds a UML class box        │  │
│  │ • add_relationship(from, to)     → adds an arrow/line          │  │
│  │ • export_diagram(format)         → exports as PNG/SVG/XML      │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Concept: MCP Decouples Intent from Execution

| Component | Role | Example |
|-----------|------|---------|
| **You** | Express intent | "Draw a class diagram" |
| **LLM** | Decides what tool to use | "I need `create_diagram` then `add_class`" |
| **MCP Host** | Routes tool calls | Connects to draw.io server, sends JSON-RPC |
| **MCP Server** | Executes the work | Actually draws the diagram |
| **draw.io** | The real backend | Renders the SVG/PNG |

---

## 2. THE LIVE EXAMPLE: draw.io MCP Server

Let's build a real draw.io MCP server and walk through every step of the protocol.

### 2.1 Server Implementation

```python
# drawio_mcp_server.py
"""
A draw.io MCP server that lets AI agents create and edit diagrams.
"""

from mcp.server.fastmcp import FastMCP
import json
import drawpy  # Hypothetical draw.io Python binding (illustrative only — not a real pip package)

# Initialize MCP server
mcp = FastMCP("drawio-diagrammer")

# ── In-memory diagram store ──
diagrams = {}


# ── Tool 1: Create a new diagram ──

@mcp.tool()
def create_diagram(diagram_type: str, title: str) -> str:
    """Create a new blank diagram.
    
    Args:
        diagram_type: Type of diagram — "class", "flowchart", "sequence", "entity"
        title: Title for the diagram
    """
    diagram_id = f"diagram_{len(diagrams) + 1}"
    
    # Creates a draw.io diagram with appropriate template
    if diagram_type == "class":
        diagrams[diagram_id] = drawpy.ClassDiagram(title)
    elif diagram_type == "flowchart":
        diagrams[diagram_id] = drawpy.Flowchart(title)
    else:
        diagrams[diagram_id] = drawpy.Diagram(title)
    
    return json.dumps({
        "diagram_id": diagram_id,
        "title": title,
        "type": diagram_type,
        "url": f"https://embed.diagrams.net/?title={title}"
    })


# ── Tool 2: Add a UML class ──

@mcp.tool()
def add_class(diagram_id: str, class_name: str, 
              attributes: list, methods: list) -> str:
    """Add a UML class box to a class diagram.
    
    Args:
        diagram_id: The diagram to modify
        class_name: Name of the class (e.g., 'ParkingLot')
        attributes: List of attributes as strings (e.g., ['-floors: List[Floor]'])
        methods: List of methods as strings (e.g., ['+park_vehicle(v: Vehicle): Ticket'])
    """
    if diagram_id not in diagrams:
        raise ValueError(f"Diagram {diagram_id} not found")
    
    diagram = diagrams[diagram_id]
    uml_class = drawpy.UMLClass(class_name, attributes, methods)
    diagram.add_class(uml_class)
    
    return json.dumps({
        "status": "added",
        "class": class_name,
        "attributes": len(attributes),
        "methods": len(methods)
    })


# ── Tool 3: Add a relationship ──

@mcp.tool()
def add_relationship(diagram_id: str, from_class: str,
                     to_class: str, relationship_type: str) -> str:
    """Add a relationship arrow between two classes.
    
    Args:
        diagram_id: The diagram to modify
        from_class: Source class name
        to_class: Target class name
        relationship_type: Type — "inheritance", "composition", 
                          "aggregation", "dependency", "association"
    """
    if diagram_id not in diagrams:
        raise ValueError(f"Diagram {diagram_id} not found")
    
    diagram = diagrams[diagram_id]
    diagram.add_relationship(
        from_class, to_class, 
        relationship_type.upper()
    )
    
    return json.dumps({
        "status": "added",
        "from": from_class,
        "to": to_class,
        "type": relationship_type
    })


# ── Tool 4: Export diagram ──

@mcp.tool()
def export_diagram(diagram_id: str, format: str = "svg") -> str:
    """Export the diagram as an image or XML.
    
    Args:
        diagram_id: The diagram to export
        format: Export format — "svg", "png", "xml", "drawio"
    """
    if diagram_id not in diagrams:
        raise ValueError(f"Diagram {diagram_id} not found")
    
    diagram = diagrams[diagram_id]
    
    if format == "svg":
        output = diagram.to_svg()
    elif format == "png":
        output = diagram.to_png()
    elif format == "drawio":
        output = diagram.to_drawio_xml()
    else:
        raise ValueError(f"Unsupported format: {format}")
    
    return json.dumps({
        "diagram_id": diagram_id,
        "format": format,
        "content": output,          # Base64 encoded image or XML
        "preview_url": f"https://viewer.diagrams.net/{diagram_id}"
    })


if __name__ == "__main__":
    # Run with stdio transport (for local use with Claude Desktop)
    mcp.run(transport="stdio")
```

---

## 🔍 DEEP DIVE: What Does `mcp.run(transport="stdio")` Actually Do?

This single line is the entry point that starts the entire MCP server. Let's trace every step of what happens under the hood.

### 1. The Call Chain

```ascii
mcp.run(transport="stdio")
    │
    ▼
FastMCP.run(transport="stdio")
    │
    ├── 1. Create StdioServerTransport
    │    │   • Opens stdin for reading (receive JSON-RPC requests)
    │    │   • Opens stdout for writing (send JSON-RPC responses)
    │    │   • Note: stderr is reserved for logging/debug output
    │    │
    ├── 2. Create Server instance
    │    │   • Wraps the FastMCP app into a low-level MCP Server
    │    │   • Registers all @mcp.tool() functions as tool handlers
    │    │   • Registers all @mcp.resource() functions as resource handlers
    │    │   • Registers all @mcp.prompt() functions as prompt handlers
    │    │
    ├── 3. Start the server loop
    │    │   • Enters an infinite loop waiting for JSON-RPC messages on stdin
    │    │   • Each message is parsed, dispatched to the handler, and responded to
    │    │
    └── 4. Cleanup (on SIGINT/SIGTERM)
         • Closes transport
         • Runs cleanup handlers
         • Exits
```

### 2. What Happens at Each Level

#### Level 1: `FastMCP.run()` — The High-Level Entry

```python
# Inside the FastMCP library (simplified)
def run(self, transport="stdio"):
    if transport == "stdio":
        # Create the stdio transport layer
        transport_obj = StdioServerTransport()
        
        # Wrap self into a protocol-compliant server
        server = Server(self._name)
        
        # Register all our tools/resources/prompts
        for tool_name, tool_fn in self._tools.items():
            @server.tool(tool_name)
            async def handler(args):
                return tool_fn(**args)
        
        # Start the protocol handler
        server.run(transport_obj)
```

#### Level 2: `StdioServerTransport` — The I/O Layer

```python
# Inside the MCP SDK (simplified)
class StdioServerTransport:
    """
    Transport that reads JSON-RPC messages from stdin and writes to stdout.
    
    KEY DESIGN DECISIONS:
    - Uses stdin/stdout (NOT stderr) for protocol messages
    - Messages are delimited by newlines (one JSON-RPC message per line)
    - stderr is free for the developer to use for logging
    - Raw byte reads/writes — no framing beyond newlines
    """
    
    async def receive_message(self) -> dict:
        """Read one JSON-RPC message from stdin."""
        # 1. Read bytes from stdin until we hit a newline
        raw_line = await self._readline()
        
        # 2. Parse as JSON
        message = json.loads(raw_line)
        
        # 3. Validate JSON-RPC structure
        if "method" not in message:
            raise InvalidMessageError("Missing 'method' field")
        
        return message
    
    async def send_message(self, response: dict):
        """Write one JSON-RPC response to stdout."""
        # 1. Serialize to JSON
        raw = json.dumps(response)
        
        # 2. Write to stdout with newline delimiter
        await self._writeline(raw + "\n")
        
        # 3. Flush to ensure immediate delivery
        await self._flush()
```

#### Level 3: `Server` — The Protocol Handler

```python
# Inside the MCP SDK (simplified)
class Server:
    async def run(self, transport):
        """Main server loop — runs forever until interrupted."""
        # --- Phase 1: Wait for initialize ---
        # The host MUST send initialize first. We block until we get it.
        init_msg = await transport.receive_message()
        assert init_msg["method"] == "initialize"
        
        # Respond with our capabilities
        await transport.send_message({
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {},      # We have tools!
                    "resources": {},   # We have resources!
                    "prompts": {}      # We have prompts!
                },
                "serverInfo": {
                    "name": self._name,
                    "version": "1.0.0"
                }
            },
            "id": init_msg["id"]
        })
        
        # --- Phase 2: Main request loop ---
        while True:
            msg = await transport.receive_message()
            
            # Determine method type and dispatch
            if msg["method"] == "tools/list":
                response = self._handle_tools_list(msg)
            elif msg["method"] == "tools/call":
                response = await self._handle_tools_call(msg)
            elif msg["method"] == "resources/list":
                response = self._handle_resources_list(msg)
            elif msg["method"] == "resources/read":
                response = self._handle_resources_read(msg)
            elif msg["method"] == "notifications/initialized":
                continue  # No response needed for notifications
            else:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "Method not found"},
                    "id": msg.get("id")
                }
            
            await transport.send_message(response)
```

### 3. The Complete stdio Transport Lifecycle

```ascii
HOST (Claude Desktop)                     SERVER (Python process)
────────────────────────                  ────────────────────────

1. Spawns server as child process:
   $ python drawio_mcp_server.py
                                          
2. Writes to stdin:                       
   {"method":"initialize","id":1}
                                     ──►  Reads from stdin
                                          Parses JSON-RPC
                                          
                                          Writes to stdout:
                                     ◄──  {"result":{"protocolVersion":...},"id":1}
                                          
3. Reads from stdout:
   Parses capabilities
                                          
4. Writes to stdin:
   {"method":"tools/list","id":2}
                                     ──►  
                                          
                                     ◄──  {"result":{"tools":[...]},"id":2}

5. Writes to stdin:
   {"method":"tools/call",...}
                                     ──►  
                                          Calls create_diagram()
                                     ◄──  {"result":{"content":[...]},"id":3}

... loop continues ...

6. Closes stdin pipe
                                     ──►  Detects EOF
                                          Runs cleanup
                                          Exits process
```

### 4. Technical Details & Timing

| Aspect | Detail |
|--------|--------|
| **Process model** | Server runs as a **child process** of the host. One process per server. |
| **IPC mechanism** | Unix pipe (on macOS/Linux) or Windows pipe. No network sockets involved. |
| **Message format** | One JSON object per line (newline-delimited JSON). |
| **Latency** | ~0.1-0.5ms per round-trip (pure IPC, no network stack). |
| **Buffering** | stdout is line-buffered by default. Each message is flushed immediately. |
| **Memory** | ~10-50MB per server process (Python overhead). |
| **Lifecycle** | Process lives as long as the host. Killed when host exits. |
| **Logging** | Use stderr for logging: `print("debug", file=sys.stderr)` |

### 5. What This Means in Practice

```python
# When you run this:
mcp = FastMCP("my-server")

@mcp.tool()
def my_tool(x: int) -> int:
    return x * 2

if __name__ == "__main__":
    mcp.run(transport="stdio")

# The following happens:
# 1. Python process starts
# 2. FastMCP initializes all registered tools/resources/prompts
# 3. Process blocks on stdin, waiting for JSON-RPC messages
# 4. Host sends: {"method":"initialize",...}
# 5. Server responds with capabilities
# 6. Host sends: {"method":"tools/list",...}
# 7. Server responds with tool schemas
# 8. Host sends: {"method":"tools/call","params":{"name":"my_tool","arguments":{"x":5}}}
# 9. Server calls my_tool(5), gets 10, sends: {"result":{"content":[{"text":"10"}]}}
# 10. Repeat from step 8 for each tool call
# 11. Host closes stdin → server detects EOF → exits
```

### 6. The "stdin/stdout" Architecture Diagram

```ascii
┌────────────────────────────────────────────────────────────────┐
│                      HOST PROCESS                               │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  MCP Client (Protocol Handler)                        │   │
│  │                                                       │   │
│  │  # Write request to child's stdin                     │   │
│  │  os.WriteFile(stdin_pipe, json_request)               │   │
│  │                                                       │   │
│  │  # Read response from child's stdout                  │   │
│  │  response = os.ReadFile(stdout_pipe)                  │   │
│  └────────────┬───────────────────────────────────────────┘   │
└───────────────┼───────────────────────────────────────────────┘
                │
                │  stdin  ──────── JSON-RPC ────────►
                │  stdout ◄─────── JSON-RPC ──────────
                │  stderr ──────── Logs only ─────────►
                │
┌───────────────┼───────────────────────────────────────────────┐
│               ▼                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              SERVER PROCESS (child)                    │   │
│  │                                                        │   │
│  │  import sys                                            │   │
│  │  import json                                           │   │
│  │                                                        │   │
│  │  while True:                                           │   │
│  │      line = sys.stdin.readline()      # Block on stdin  │   │
│  │      if not line:                     # EOF → shutdown  │   │
│  │          break                                          │   │
│  │      msg = json.loads(line)           # Parse JSON-RPC  │   │
│  │      result = dispatch(msg)           # Call handler    │   │
│  │      sys.stdout.write(json.dumps(result) + "\n")       │   │
│  │      sys.stdout.flush()               # Send response   │   │
│  └────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 7. Why No Network Port?

Unlike a web server that binds to `0.0.0.0:8000`, `mcp.run(transport="stdio")` does **not** open any network port. The communication happens through **standard file descriptors** that every process already has:

| File Descriptor | Direction | Used For |
|----------------|-----------|----------|
| `stdin` (fd 0) | Host → Server | Receiving JSON-RPC requests |
| `stdout` (fd 1) | Server → Host | Sending JSON-RPC responses |
| `stderr` (fd 2) | Server → User | Logging, debug output |

**Security benefit:** No firewall rules needed, no open ports, no network attack surface. The server is completely isolated inside its own process.

---

## 3. STEP-BY-STEP: WHAT HAPPENS WHEN YOU SAY "DRAW A PARKING LOT CLASS DIAGRAM"

### Step 1: User Sends a Request

```
You: "Create a class diagram for a parking lot system"
```

### Step 2: LLM Receives the Request

The MCP Host sends this to the LLM (e.g., Claude):

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant with access to a diagramming tool..."
    },
    {
      "role": "user",
      "content": "Create a class diagram for a parking lot system"
    }
  ]
}
```

### Step 3: LLM Decides to Use a Tool

The LLM's response includes a tool call request:

```json
{
  "role": "assistant",
  "content": "I'll create a Parking Lot class diagram. Let me start by creating the diagram.",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "create_diagram",
        "arguments": "{\"diagram_type\": \"class\", \"title\": \"Parking Lot System\"}"
      }
    }
  ]
}
```

### Step 4: Host Sends JSON-RPC Request to MCP Server

The MCP Host translates the tool call into a JSON-RPC 2.0 request:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "create_diagram",
    "arguments": {
      "diagram_type": "class",
      "title": "Parking Lot System"
    }
  },
  "id": 1
}
```

**This is the actual network request.** Whether over stdio (pipe to child process) or HTTP (POST to server), this JSON is what gets sent.

### Step 5: MCP Server Processes the Request

The server:
1. Receives the JSON
2. Validates arguments against the tool's JSON Schema
3. Calls the `create_diagram` Python function
4. Gets the result

```python
# Server-side validation (auto-generated from type hints + docstrings)
# Input validation:
#   - "diagram_type" must be one of: "class", "flowchart", "sequence", "entity"
#   - "title" must be a string
# Result:
result = create_diagram(diagram_type="class", title="Parking Lot System")
# Returns: {"diagram_id": "diagram_1", "title": "Parking Lot System", ...}
```

### Step 6: Server Sends JSON-RPC Response

```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"diagram_id\": \"diagram_1\", \"title\": \"Parking Lot System\", \"type\": \"class\"}"
      }
    ]
  },
  "id": 1
}
```

**This is the response the host receives.** It contains structured text that gets sent back to the LLM.

### Step 7: LLM Receives the Result and Plans Next Steps

The result is added as a tool response message:

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"diagram_id\": \"diagram_1\", \"title\": \"Parking Lot System\", \"type\": \"class\"}"
}
```

The LLM now knows the diagram was created and plans the next steps:

```json
{
  "role": "assistant",
  "content": "Great, the diagram is created! Now let me add the main classes.",
  "tool_calls": [
    {
      "id": "call_def456",
      "function": {
        "name": "add_class",
        "arguments": "{\"diagram_id\": \"diagram_1\", \"class_name\": \"ParkingLot\", \"attributes\": [\"-floors: List[ParkingFloor]\"], \"methods\": [\"+park_vehicle(v: Vehicle): Ticket\", \"+unpark_vehicle(ticket: Ticket): bool\"]}"
      }
    }
  ]
}
```

### Step 8: Multiple Tool Calls Build the Complete Diagram

This repeats — the LLM calls `add_class`, then `add_relationship`, then `add_class` again, etc. Each is a round-trip:

```
LLM: add_class("ParkingLot", ...)  →  Server: ✅ Added
LLM: add_class("Vehicle", ...)     →  Server: ✅ Added
LLM: add_class("Car", ...)         →  Server: ✅ Added
LLM: add_relationship("Car", "Vehicle", "inheritance") → Server: ✅ Added
LLM: add_class("ParkingSpot", ...) →  Server: ✅ Added
LLM: add_relationship("ParkingLot", "ParkingSpot", "composition") → Server: ✅ Added
LLM: export_diagram("diagram_1", "svg") → Server: Returns SVG
```

### Step 9: Final Response to User

```json
{
  "role": "assistant",
  "content": "Here's the Parking Lot class diagram I created:\n\n![Parking Lot Class Diagram](data:image/svg+xml;base64,...)\n\nThe diagram includes:\n- **ParkingLot** — main facade class\n- **ParkingFloor** — composition with ParkingLot\n- **ParkingSpot** — managed by ParkingFloor\n- **Vehicle** (abstract) → Car, Truck, Motorcycle\n- **ParkingTicket** — tracks parking sessions\n- **FeeCalculator** — strategy pattern for pricing\n- Relationships: inheritance, composition, and dependency arrows"
}
```

---

## 4. THE COMPLETE JSON-RPC FLOW (DIAGRAM)

```ascii
USER                    MCP HOST                    MCP SERVER              DRAW.IO
 │                          │                           │                      │
 │  "Draw class diagram"    │                           │                      │
 │─────────────────────────►│                           │                      │
 │                          │                           │                      │
 │                          │  ── 1. Initialize ──►     │                      │
 │                          │  ◄─── Capabilities ──     │                      │
 │                          │     (tools/list)          │                      │
 │                          │                           │                      │
 │                          │  ── 2. tools/list ──►     │                      │
 │                          │  ◄─── create_diagram ──   │                      │
 │                          │        add_class          │                      │
 │                          │        add_relationship   │                      │
 │                          │        export_diagram     │                      │
 │                          │                           │                      │
 │                          │  ── 3. tools/call ──►     │                      │
 │                          │    create_diagram         │── drawpy.create() ──►│
 │                          │    {"type":"class"}       │                      │
 │                          │                           │◄── diagram_id ──────│
 │                          │  ◄─── {"diagram_id": ──   │                      │
 │                          │         "diagram_1"}      │                      │
 │                          │                           │                      │
 │                          │  ── 4. tools/call ──►     │                      │
 │                          │    add_class("ParkingLot") │── drawpy.add() ────►│
 │                          │                           │                      │
 │                          │  ── 5. tools/call ──►     │                      │
 │                          │    add_class("Vehicle")   │── drawpy.add() ────►│
 │                          │                           │                      │
 │                          │  ── 6. tools/call ──►     │                      │
 │                          │    add_relationship(...)  │── drawpy.connect() ─►│
 │                          │                           │                      │
 │                          │  ── 7. tools/call ──►     │                      │
 │                          │    export_diagram("svg")  │── drawpy.export() ──►│
 │                          │                           │◄── SVG data ────────│
 │                          │  ◄─── SVG image ──────    │                      │
 │                          │                           │                      │
 │  ◄── Shows diagram ─────│                           │                      │
 │                          │                           │                      │
```

---

## 5. WHERE IS MCP ACTUALLY?

Many people ask: **"Where does MCP live?"**

The answer: **MCP is a protocol — it lives in the messages between the Host and Server.**

```ascii
┌─────────────────────────────────────────────────────────────┐
│                     YOUR COMPUTER                            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │              CLAUDE DESKTOP (Host)                   │     │
│  │                                                      │     │
│  │  ┌──────────────────────────────────────────────┐   │     │
│  │  │              LLM (Claude Model)               │   │     │
│  │  │  • Receives user message                      │   │     │
│  │  │  • Decides to call tool                       │   │     │
│  │  │  • Returns response                           │   │     │
│  │  └──────────────────────────────────────────────┘   │     │
│  │                      │                               │     │
│  │                      │ JSON-RPC 2.0                  │     │
│  │                      │ over stdin/stdout             │     │
│  │                      ▼                               │     │
│  │  ┌──────────────────────────────────────────────┐   │     │
│  │  │         MCP CLIENT (Protocol Handler)          │   │     │
│  │  │  • Sends JSON-RPC requests                     │   │     │
│  │  │  • Receives JSON-RPC responses                 │   │     │
│  │  │  • Manages transport (stdio or HTTP)           │   │     │
│  │  └────────────┬───────────────────────────────────┘   │     │
│  └───────────────┼──────────────────────────────────────┘     │
│                  │ Child process pipe                         │
│                  ▼                                            │
│  ┌────────────────────────────────────────────────────┐     │
│  │            MCP SERVER (drawio_server.py)             │     │
│  │                                                      │     │
│  │  ┌──────────────────────────────────────────────┐   │     │
│  │  │      FastMCP (Python SDK)                     │   │     │
│  │  │  • Parses JSON-RPC                             │   │     │
│  │  │  • Validates against schema                    │   │     │
│  │  │  • Calls registered functions                  │   │     │
│  │  │  • Formats JSON-RPC response                   │   │     │
│  │  └──────────────────────────────────────────────┘   │     │
│  │                                                      │     │
│  │  ┌──────────────────────────────────────────────┐   │     │
│  │  │      Your Tool Functions                      │   │     │
│  │  │  • create_diagram()                            │   │     │
│  │  │  • add_class()                                │   │     │
│  │  │  • add_relationship()                         │   │     │
│  │  │  • export_diagram()                           │   │     │
│  │  └──────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**MCP lives in the protocol layer** — the standardized JSON-RPC 2.0 messages that flow between the client and server. It's not a library, not a framework — it's a **contract** that both sides agree to speak.

---

## 6. WHAT REQUESTS DO WE SEND? WHAT RESPONSES DO WE GET?

### 6.1 Request Types

| Method | Purpose | When | Example |
|--------|---------|------|---------|
| `initialize` | Handshake + capability negotiation | Connection start | `{"method": "initialize", "params": {...}}` |
| `tools/list` | Discover available tools | After init | `{"method": "tools/list", "id": 1}` |
| `tools/call` | Execute a tool | When LLM decides | `{"method": "tools/call", "params": {"name": "add_class", "arguments": {...}}}` |
| `resources/list` | Discover available resources | After init | `{"method": "resources/list", "id": 2}` |
| `resources/read` | Read a resource | When LLM needs data | `{"method": "resources/read", "params": {"uri": "rag://status"}}` |
| `prompts/list` | Discover prompt templates | After init | `{"method": "prompts/list", "id": 3}` |
| `prompts/get` | Get a prompt template | When LLM needs guidance | `{"method": "prompts/get", "params": {"name": "debug_query"}}` |
| `notifications/initialized` | Confirm initialization complete | After init response | `{"method": "notifications/initialized"}` |

### 6.2 Response Types

| Type | Structure | Example |
|------|-----------|---------|
| **Success** | `{"jsonrpc": "2.0", "result": {...}, "id": 1}` | Tool result, resource content |
| **Error** | `{"jsonrpc": "2.0", "error": {"code": -32602, "message": "Invalid params"}, "id": 1}` | Validation failure, not found |
| **Notification** | `{"jsonrpc": "2.0", "method": "...", "params": {...}}` (no `id`) | Server-initiated events |

### 6.3 Concrete Request/Response Pair

**Request** (Host → Server):
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "add_class",
    "arguments": {
      "diagram_id": "diagram_1",
      "class_name": "ParkingTicket",
      "attributes": [
        "-ticket_id: str",
        "-entry_time: datetime",
        "-exit_time: Optional[datetime]",
        "-status: ParkingTicketStatus"
      ],
      "methods": [
        "+close(fee_calculator: FeeCalculator): float"
      ]
    }
  },
  "id": 3
}
```

**Response** (Server → Host):
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"status\": \"added\", \"class\": \"ParkingTicket\", \"attributes\": 4, \"methods\": 1}"
      }
    ],
    "isError": false
  },
  "id": 3
}
```

### 6.4 Error Response Example

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": {
      "validation_error": "diagram_id 'diagram_99' not found. Available IDs: diagram_1"
    }
  },
  "id": 3
}
```

---

## 7. MCP IN PRODUCTION

In production, we don't run the MCP server as a child process of Claude Desktop. Instead, we deploy it as a microservice:

```ascii
┌──────────────────────────────────────────────────────────────────┐
│                        PRODUCTION ARCHITECTURE                    │
│                                                                   │
│  ┌────────────┐     ┌────────────┐     ┌────────────────────┐   │
│  │  User      │────►│  AI Agent   │────►│  MCP Gateway       │   │
│  │  (Browser) │     │  (K8s Pod)  │     │  (Kong/ALB)        │   │
│  └────────────┘     └────────────┘     │  • Auth (JWT)       │   │
│                                         │  • Rate Limiting    │   │
│                                         │  • Load Balancing   │   │
│                                         │  • TLS Termination  │   │
│                                         └────────┬───────────┘   │
│                                                  │               │
│                    ┌─────────────────────────────┼────────┐      │
│                    │                             │        │      │
│                    ▼                             ▼        │      │
│    ┌────────────────────────┐    ┌────────────────────┐   │      │
│    │  draw.io MCP Server    │    │  DB MCP Server     │   │      │
│    │  (3 replicas, HPA)     │    │  (2 replicas)      │   │      │
│    │                        │    │                    │   │      │
│    │  Streamable HTTP (SSE) │    │  Streamable HTTP   │   │      │
│    │  Port: 8000            │    │  Port: 8001        │   │      │
│    │  Scaling: 70% CPU      │    │  Scaling: 100 rps  │   │      │
│    └────────────────────────┘    └────────────────────┘   │      │
│                    │                                        │      │
│                    ▼                                        │      │
│    ┌────────────────────────────────────────────────┐       │      │
│    │           Observability Stack                   │       │      │
│    │  • Prometheus (metrics)                         │       │      │
│    │  • Grafana (dashboards)                         │       │      │
│    │  • Loki (logs)                                  │       │      │
│    │  • OpenTelemetry (traces)                       │       │      │
│    └────────────────────────────────────────────────┘       │      │
└──────────────────────────────────────────────────────────────┘      │
```

### Production vs Development

| Aspect | Development (stdio) | Production (Streamable HTTP) |
|--------|-------------------|------------------------------|
| **Transport** | Child process pipe | HTTP + SSE |
| **Latency** | <1ms (IPC) | 5-50ms (network) |
| **Scaling** | 1:1 (one client per server) | N:M (many clients, many replicas) |
| **Security** | Trust boundary (local) | JWT auth, TLS, rate limiting |
| **Deployment** | `python server.py` | Docker → Kubernetes |
| **Monitoring** | Manual | Prometheus + Grafana |
| **Resilience** | Process dies = session lost | Health checks, circuit breakers |

### Production Deployment Steps

```bash
# 1. Build the Docker image
docker build -t mcp-drawio-server:latest .

# 2. Push to registry
docker push myregistry/mcp-drawio-server:latest

# 3. Deploy to Kubernetes
kubectl apply -f k8s/mcp-drawio-server.yaml

# 4. Configure the AI Agent to connect
# The agent connects to: https://mcp-gateway.company.com/drawio
```

**Kubernetes Config:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-drawio-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcp-drawio-server
  template:
    metadata:
      labels:
        app: mcp-drawio-server
    spec:
      containers:
      - name: server
        image: myregistry/mcp-drawio-server:latest
        ports:
        - containerPort: 8000
        env:
        - name: MAX_DIAGRAM_SIZE
          value: "10MB"
        - name: RATE_LIMIT
          value: "100/minute"
        resources:
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-drawio-service
spec:
  selector:
    app: mcp-drawio-server
  ports:
  - port: 8000
    targetPort: 8000
```

---

## 8. COMPLETE FLOW SUMMARY

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                    THE COMPLETE MCP FLOW                             │
│                                                                     │
│  PHASE 1: CONNECTION                                                 │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Host spawns/connects to MCP Server                            │  │
│  │ Host → Server: {"method": "initialize", ...}                  │  │
│  │ Server → Host: {"result": {"capabilities": {"tools":{}},...}  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  PHASE 2: DISCOVERY                                                  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Host → Server: {"method": "tools/list", "id": 1}              │  │
│  │ Server → Host: {"result": {"tools": [{"name":"create_diagram",│  │
│  │                                        "inputSchema":...}]}}  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  PHASE 3: EXECUTION                                                  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ LLM decides to call "add_class"                                │  │
│  │ Host → Server: {"method": "tools/call", "params":             │  │
│  │                {"name":"add_class","arguments":{...}}}         │  │
│  │ Server executes: Python function runs                          │  │
│  │ Server → Host: {"result": {"content": [{"type":"text",        │  │
│  │                               "text":"..."}]}}                │  │
│  │ Host feeds result back to LLM as tool response                │  │
│  │ LLM decides next action (more tools or respond to user)       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  PHASE 4: SHUTDOWN                                                   │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Host closes transport connection                               │  │
│  │ Server cleans up resources                                     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 9. KEY TAKEAWAYS

1. **MCP is a protocol, not a product** — it's the standardized way Hosts and Servers communicate via JSON-RPC 2.0
2. **The LLM doesn't know MCP exists** — it just sees "here are your available tools" in the system prompt
3. **The Host handles the plumbing** — it translates between LLM tool calls and JSON-RPC messages
4. **Round-trips matter** — each `tools/call` is one network/process hop. Design tools to minimize round-trips
5. **Schema validation protects against hallucination** — the server validates parameters before executing
6. **Production = Streamable HTTP** — stdio is for development; SSE+HTTP POST is for production deployments
7. **The draw.io example applies to ANY tool** — same protocol works for databases, file systems, APIs, etc.

---

> **Next:** This document covers the practical flow. See [MCP Fundamentals](01_MCP_FUNDAMENTALS.md) for protocol mechanics, and [MCP Production Architecture](04_MCP_PRODUCTION_ARCHITECTURE.md) for production deployment.
