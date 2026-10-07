# 🛠️ Agent Implementation Guide — Building Production Agents

> **Target:** Staff Engineer | **Focus:** Runnable code, design patterns, MCP integration | **Reviewed:** October 2026

!!! tip "30-second answer: how do you implement an agent?"
    A `while` loop around the provider's **native tool-calling API**: send messages + tool schemas, execute any tool calls the model returns (validated, authorized, with timeouts), append the results with the matching call ids, repeat until the model answers without a tool call or a budget runs out. Everything else (registries, memory, orchestration, MCP) is structure around that loop. Section 2.1 shows the classic text-parsing ReAct loop because it is model-agnostic and easy to read; section 2.2 shows what production code does instead.

---

## 1. PROJECT STRUCTURE

```
agents/
├── 01_AGENT_FUNDAMENTALS.md
├── 02_AGENT_INTERVIEW_QUESTIONS.md
├── 03_AGENT_IMPLEMENTATION_GUIDE.md       ← This file
├── 04_AGENT_PRODUCTION_ARCHITECTURE.md
├── implementation/
│   ├── __init__.py
│   ├── simple_react_agent.py              # Basic ReAct agent (uses common/tool_registry.py)
│   ├── orchestrated_agent.py              # Orchestrator-Worker
│   ├── agent_with_mcp.py                  # Agent using MCP servers
│   ├── common/
│   │   ├── __init__.py
│   │   ├── tool_registry.py               # Tool registration & validation
│   │   ├── memory.py                      # Short-term + working memory
│   │   ├── llm_client.py                  # LLM abstraction (Mock, OpenAI Responses, local OpenAI-compatible)
│   │   └── guardrails.py                  # Input/output guardrails
│   └── requirements.txt
└── tests/
    ├── __init__.py
    ├── test_simple_agent.py
    └── test_orchestrated_agent.py
```

---

## 2. IMPLEMENTATION — SIMPLE REACT AGENT

### 2.1 Basic ReAct Loop

```python
# Simplified, self-contained version of implementation/simple_react_agent.py
"""
A minimal ReAct (Reasoning + Acting) agent.
Demonstrates the core loop: Thought → Action → Observation → Repeat.
"""

import json
import time
from typing import List, Dict, Optional, Callable


class Tool:
    """A callable tool with schema for the agent to use."""
    
    def __init__(self, name: str, description: str, 
                 fn: Callable, parameters: dict):
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters  # JSON Schema
    
    def to_mcp_format(self) -> dict:
        """Format as MCP tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.parameters.keys()),
            }
        }


class SimpleReActAgent:
    """
    Minimal ReAct agent.
    
    Architecture:
        Loop max_steps times:
        1. LLM thinks about the next action
        2. If done, return answer
        3. Call the chosen tool
        4. Feed observation back
        5. Repeat
    """
    
    def __init__(self, llm: Callable, tools: List[Tool], 
                 max_steps: int = 10, system_prompt: str = ""):
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.max_steps = max_steps
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.history: List[dict] = []
    
    def _default_system_prompt(self) -> str:
        tools_desc = "\n".join(
            f"- {t.name}: {t.description}\n  Params: {json.dumps(t.parameters)}"
            for t in self.tools.values()
        )
        return f"""You are a helpful AI agent with access to the following tools:

{tools_desc}

Respond in this format:

Thought: <your reasoning about what to do next>
Action: <tool_name>
ActionInput: <JSON argument for the tool>

When you have the final answer:

Thought: I now have the final answer
Answer: <your final response to the user>

Be concise. Use tools when you need external information."""
    
    def run(self, user_input: str) -> str:
        """Execute the agent loop for a user request."""
        self.history = [{"role": "user", "content": user_input}]
        
        for step in range(self.max_steps):
            # Step 1: LLM thinks
            prompt = self._build_prompt()
            response = self.llm(prompt)
            self.history.append({"role": "assistant", "content": response})
            
            # Step 2: Parse response
            parsed = self._parse_response(response)
            
            if "answer" in parsed:
                return parsed["answer"]
            
            if "action" not in parsed:
                return f"I got stuck. Last response: {response}"
            
            # Step 3: Execute tool
            tool_name = parsed["action"]
            if tool_name not in self.tools:
                observation = f"Error: Unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
            else:
                try:
                    tool_input = json.loads(parsed.get("action_input", "{}"))
                    result = self.tools[tool_name].fn(**tool_input)
                    observation = str(result)
                except Exception as e:
                    observation = f"Error calling {tool_name}: {str(e)}"
            
            self.history.append({"role": "observation", "content": observation})
        
        return "I exceeded the maximum number of steps without reaching a final answer."
    
    def _build_prompt(self) -> str:
        """Build the full prompt from system + history."""
        parts = [self.system_prompt]
        for h in self.history:
            if h["role"] == "user":
                parts.append(f"User: {h['content']}")
            elif h["role"] == "assistant":
                parts.append(f"Assistant: {h['content']}")
            elif h["role"] == "observation":
                parts.append(f"Observation: {h['content']}")
        parts.append("\nWhat is your next thought or action?")
        return "\n\n".join(parts)
    
    def _parse_response(self, response: str) -> dict:
        """Parse the LLM response to extract thought/action/answer."""
        result = {}
        
        if "Answer:" in response:
            result["answer"] = response.split("Answer:")[-1].strip()
        
        if "Action:" in response:
            lines = response.split("\n")
            for line in lines:
                if line.startswith("Action:"):
                    result["action"] = line.replace("Action:", "").strip()
                elif line.startswith("ActionInput:"):
                    result["action_input"] = line.replace("ActionInput:", "").strip()
        
        return result


# ── Usage Example ──

def mock_llm(prompt: str) -> str:
    """Mock LLM for demonstration (replace with a real model call, see 2.2)."""
    if "Observation:" not in prompt:       # first turn: no tool result yet
        return """Thought: I need to search for information about this topic.
Action: search_web
ActionInput: {"query": "latest AI developments 2026"}"""
    return """Thought: I have gathered the information needed.
Answer: Based on my research, here are the latest AI developments..."""


def main():
    # Define tools
    tools = [
        Tool(
            name="search_web",
            description="Search the web for information",
            fn=lambda query: f"Results for '{query}': [simulated search results]",
            parameters={"query": {"type": "string", "description": "Search query"}}
        ),
        Tool(
            name="get_time",
            description="Get the current time",
            fn=lambda: f"Current time: {time.ctime()}",
            parameters={}
        ),
    ]
    
    agent = SimpleReActAgent(llm=mock_llm, tools=tools)
    result = agent.run("What are the latest AI developments?")
    print(result)


if __name__ == "__main__":
    main()
```

**Why production code doesn't parse text like this:** the model can emit malformed JSON, put two actions in one reply, or write `Action:` inside an answer, and an observation that contains `Answer:` can end the loop early. Native tool calling returns structured calls, supports several calls per turn, and lets strict schemas guarantee valid arguments.

### 2.2 Native tool calling (what production agents use)

The same loop against the Anthropic Messages API. Model ids change; read them from config.

```python
import os
import anthropic

client = anthropic.Anthropic()                     # reads ANTHROPIC_API_KEY
MODEL = os.environ["AGENT_MODEL"]                  # e.g. a current Claude Sonnet/Opus id
MAX_STEPS = 20

TOOLS = [{
    "name": "get_order",
    "description": "Look up an order by id. Use when the user asks about an order's status.",
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
        "additionalProperties": False,
    },
    "strict": True,                                # arguments guaranteed to match the schema
}]

def run(user_msg: str, dispatch) -> str:
    messages = [{"role": "user", "content": user_msg}]
    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=16000,
            system="You are an order-support agent. Use tools; never guess order data.",
            tools=TOOLS, messages=messages,
        )
        # Append the FULL content (text, thinking and tool_use blocks), not just text:
        # thinking blocks must be passed back unchanged in a tool loop.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":         # end_turn, max_tokens, refusal, ...
            return "".join(b.text for b in resp.content if b.type == "text")

        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                output = dispatch(block.name, block.input)   # validate + authorize + run
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
            except Exception as e:                           # errors are observations
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"Error: {e}", "is_error": True})
        # All results for one turn go back in ONE user message.
        messages.append({"role": "user", "content": results})
    return "Stopped: step limit reached."
```

The OpenAI Responses API version differs only in shapes:

```python
from openai import OpenAI
import json

client = OpenAI()
TOOLS = [{"type": "function", "name": "get_order",
          "description": "Look up an order by id.",
          "parameters": {"type": "object",
                         "properties": {"order_id": {"type": "string"}},
                         "required": ["order_id"], "additionalProperties": False},
          "strict": True}]

def run(user_msg: str, dispatch) -> str:
    items = [{"role": "user", "content": user_msg}]
    for _ in range(MAX_STEPS):
        resp = client.responses.create(model=MODEL, instructions=SYSTEM,
                                       tools=TOOLS, input=items)
        calls = [i for i in resp.output if i.type == "function_call"]
        if not calls:
            return resp.output_text
        items += resp.output                       # keep reasoning + call items
        for c in calls:
            items.append({"type": "function_call_output", "call_id": c.call_id,
                          "output": dispatch(c.name, json.loads(c.arguments))})
    return "Stopped: step limit reached."
```

| Concern | Anthropic Messages | OpenAI Responses |
|---------|--------------------|------------------|
| Tool schema field | `input_schema` | `parameters` (with `"type": "function"`) |
| "Model wants a tool" | `stop_reason == "tool_use"`, `tool_use` blocks | `function_call` items in `output` |
| Return a result | `tool_result` block with `tool_use_id`, in a `user` message | `function_call_output` item with `call_id` |
| Server-side state | None: resend history (cache the prefix) | Optional: `previous_response_id` or the Conversations API |
| Built-in hosted tools | Web search/fetch, code execution, MCP connector | Web search, file search, code interpreter, remote MCP |

Production details the loop above leaves out: prompt caching of the stable prefix (system + tools), retries with backoff on 429/5xx, a token budget across the loop, streaming, and tracing each model and tool call. Agent SDKs (OpenAI Agents SDK, Anthropic's tool runner, LangGraph) wrap exactly this loop.

---

## 3. IMPLEMENTATION — AGENT WITH TOOL REGISTRY

### 3.1 Full Tool Registry with Guardrails

```python
# Sketch of a fuller registry (the runnable version is
# implementation/common/tool_registry.py).
"""
Agent with comprehensive tool registry, validation, and guardrails.
"""

import json
import time
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
import jsonschema  # pip install jsonschema


@dataclass
class ToolSpec:
    """Full tool specification with security metadata."""
    name: str
    description: str
    parameters: dict  # JSON Schema object: {"type": "object", "properties": ..., "required": [...]}
    fn: Callable
    required_role: str = "user"
    requires_approval: bool = False
    timeout_seconds: int = 30
    rate_limit: float = 10.0  # calls per second
    category: str = "read"  # "read", "write", "destructive"


class ToolRegistry:
    """
    Central registry for all agent tools.
    Handles validation, authorization, and rate limiting.
    """
    
    def __init__(self):
        self.tools: Dict[str, ToolSpec] = {}
        self.rate_limiters: Dict[str, 'TokenBucket'] = {}
    
    def register(self, tool: ToolSpec):
        """Register a tool with full spec."""
        self.tools[tool.name] = tool
        
        # Initialize rate limiter for this tool
        from implementation.common.guardrails import TokenBucket
        self.rate_limiters[tool.name] = TokenBucket(
            rate=tool.rate_limit, burst=int(tool.rate_limit * 2)
        )
    
    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self.tools.get(name)
    
    def list_tools(self) -> List[dict]:
        """Return tool definitions in MCP format (name, description, inputSchema)."""
        return self.to_mcp_format()
    
    def validate_and_execute(self, tool_name: str, params: dict, 
                              user_role: str = "user") -> str:
        """
        Full execution pipeline:
        1. Tool exists
        2. Schema validation
        3. Authorization
        4. Rate limit check
        5. Execute (with timeout)
        6. Log audit
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return f"Error: Unknown tool '{tool_name}'"
        
        # 1. Schema validation (the schema decides which params are required;
        #    don't mark every property required, or optional params break)
        try:
            jsonschema.validate(instance=params, schema=tool.parameters)
        except jsonschema.ValidationError as e:
            return f"Error: Invalid parameters - {e.message}"
        
        # 2. Authorization
        roles_hierarchy = {"admin": 3, "editor": 2, "user": 1}
        if roles_hierarchy.get(user_role, 0) < roles_hierarchy.get(tool.required_role, 0):
            return f"Error: Insufficient permissions for '{tool_name}'"
        
        # 2b. Approval gate (in a real system: pause the run, ask a human, resume)
        if tool.requires_approval:
            return f"Error: '{tool_name}' requires human approval"
        
        # 3. Rate limit
        limiter = self.rate_limiters[tool_name]
        if not limiter.consume():
            return f"Error: Rate limit exceeded for '{tool_name}'. Try again later."
        
        # 4. Execute (enforce tool.timeout_seconds: run in a worker thread /
        #    subprocess, or use asyncio.wait_for for async tools)
        try:
            result = tool.fn(**params)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
        # 5. Audit log: user, tool, args, result size, latency, trace id
    
    def to_mcp_format(self) -> List[dict]:
        """Export all tools in MCP format for agent consumption."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.parameters,
            }
            for t in self.tools.values()
        ]


# ── Example Tools ──

def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Search the internal knowledge base."""
    return f"Found {top_k} results for '{query}': [simulated KB results]"

def get_user_account(user_id: int) -> str:
    """Get user account information."""
    return json.dumps({"user_id": user_id, "plan": "premium", "status": "active"})

def send_notification(user_id: int, message: str) -> str:
    """Send a notification to a user."""
    return f"Notification sent to user {user_id}"

# Register tools
registry = ToolRegistry()
registry.register(ToolSpec(
    name="search_kb",
    description="Search the internal knowledge base for information",
    parameters={"type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"},
                               "top_k": {"type": "integer", "minimum": 1, "maximum": 20}},
                "required": ["query"],              # top_k is optional
                "additionalProperties": False},
    fn=search_knowledge_base,
    category="read"
))
registry.register(ToolSpec(
    name="get_user",
    description="Get user account information by user ID",
    parameters={"type": "object",
                "properties": {"user_id": {"type": "integer", "description": "User ID"}},
                "required": ["user_id"], "additionalProperties": False},
    fn=get_user_account,
    required_role="user",
    category="read"
))
registry.register(ToolSpec(
    name="send_notification",
    description="Send a notification to a user",
    parameters={"type": "object",
                "properties": {"user_id": {"type": "integer"}, "message": {"type": "string"}},
                "required": ["user_id", "message"], "additionalProperties": False},
    fn=send_notification,
    required_role="editor",
    requires_approval=True,
    category="write"
))
```

---

## 4. IMPLEMENTATION — ORCHESTRATOR-WORKER

### 4.1 Multi-Agent Orchestration

```python
# Simplified version of implementation/orchestrated_agent.py
"""
Orchestrator-Worker agent pattern.
The orchestrator decomposes tasks and delegates to specialized workers.
"""

import asyncio
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Task:
    """A unit of work for a worker agent."""
    id: str
    description: str
    assigned_to: str  # Worker name
    input: dict
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: Optional[str] = None


@dataclass
class Plan:
    """A decomposition of a user request into tasks."""
    goal: str
    tasks: List[Task]
    created_at: float = field(default_factory=time.time)


class WorkerAgent:
    """A specialized worker that can execute specific types of tasks."""
    
    def __init__(self, name: str, description: str, tools: List[Any]):
        self.name = name
        self.description = description
        self.tools = {t.name: t for t in tools}
    
    async def execute(self, task: Task) -> Task:
        """Execute a task using the worker's tools."""
        task.status = "running"
        try:
            # Simple execution: use the description as prompt.
            # In production, run a tool loop (section 2.2) with a brief built
            # from task.description + the outputs of task.dependencies.
            # In production, this would use an LLM with the worker's tools
            result = f"[{self.name}] Completed: {task.description}"
            task.result = result
            task.status = "completed"
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
        return task


class OrchestratorAgent:
    """
    Orchestrator-Worker pattern.
    
    Flow:
    1. Receive user request
    2. Decompose into sub-tasks
    3. Assign to specialized workers (parallel where possible)
    4. Resolve dependencies between tasks
    5. Merge results into final answer
    """
    
    def __init__(self, workers: List[WorkerAgent]):
        self.workers = {w.name: w for w in workers}
    
    async def run(self, user_request: str) -> str:
        # Phase 1: Plan — decompose into tasks
        plan = await self._create_plan(user_request)
        
        # Phase 2: Execute — dispatch tasks respecting dependencies
        results = await self._execute_plan(plan)
        
        # Phase 3: Synthesize — merge results into final answer
        return await self._synthesize(plan, results)
    
    async def _create_plan(self, request: str) -> Plan:
        """Decompose the request into a DAG of tasks."""
        # In production: use LLM to plan
        # For demo: hardcoded plan for a research task
        return Plan(
            goal=request,
            tasks=[
                Task(id="1", description="Search for information", 
                     assigned_to="researcher", input={"query": request}),
                Task(id="2", description="Analyze findings", 
                     assigned_to="analyst", input={}, dependencies=["1"]),
                Task(id="3", description="Write summary", 
                     assigned_to="writer", input={}, dependencies=["1", "2"]),
            ]
        )
    
    async def _execute_plan(self, plan: Plan) -> Dict[str, Any]:
        """Execute tasks respecting dependency graph."""
        completed = {}
        
        while len(completed) < len(plan.tasks):
            # Find tasks whose dependencies are met
            ready = [
                t for t in plan.tasks 
                if t.id not in completed and all(
                    dep in completed for dep in t.dependencies
                )
            ]
            
            if not ready:
                raise RuntimeError("Deadlock in task dependencies")
            
            # Execute ready tasks in parallel. Each worker catches its own
            # exceptions; the per-task timeout turns a hung worker into a
            # TimeoutError that fails the run instead of hanging it forever.
            tasks = []
            for task in ready:
                worker = self.workers[task.assigned_to]
                tasks.append(asyncio.wait_for(worker.execute(task), timeout=120))
            
            results = await asyncio.gather(*tasks)
            for result in results:
                completed[result.id] = result
        
        return completed
    
    async def _synthesize(self, plan: Plan, results: Dict[str, Task]) -> str:
        """Merge worker results into a coherent final answer."""
        parts = [f"## Result for: {plan.goal}\n"]
        
        for task in plan.tasks:
            result = results[task.id]
            status = "✅" if result.status == "completed" else "❌"
            parts.append(f"\n### {status} {task.assigned_to}: {task.description}")
            if result.result:
                parts.append(str(result.result))
            if result.error:
                parts.append(f"Error: {result.error}")
        
        return "\n".join(parts)


async def main():
    # Create specialized workers
    researcher = WorkerAgent(
        name="researcher",
        description="Searches for and gathers information",
        tools=[]  # In production: search tool, web scraper, etc.
    )
    analyst = WorkerAgent(
        name="analyst", 
        description="Analyzes data and extracts insights",
        tools=[]
    )
    writer = WorkerAgent(
        name="writer",
        description="Composes clear, structured summaries",
        tools=[]
    )
    
    # Create orchestrator
    orchestrator = OrchestratorAgent(
        workers=[researcher, analyst, writer]
    )
    
    # Run
    result = await orchestrator.run(
        "Research the impact of AI on software engineering in 2026"
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

This runs "waves" of ready tasks: a slow task in wave 1 delays every wave-2 task, even ones that only depended on a fast task. For better latency, start each task as soon as its own dependencies finish (one `asyncio.Task` per node awaiting its parents), which is what graph runtimes like LangGraph do.

---

## 5. IMPLEMENTATION — AGENT WITH MCP TOOLS

### 5.1 Connecting an Agent to MCP Servers

```python
# Long-lived-session version of implementation/agent_with_mcp.py
"""
Agent that discovers and uses tools from MCP servers.
Connects to calculator_server, database_server, and rag_server.
"""

import asyncio
import json
from contextlib import AsyncExitStack
from typing import List, Dict
from mcp import Client, StdioServerParameters   # mcp>=2 (Python SDK v2)


class MCPToolAgent:
    """
    Agent that connects to MCP servers and uses their tools.
    
    Architecture:
    1. Connect to each MCP server and KEEP the client open
    2. Discover tools via tools/list
    3. Present unified tool registry to LLM
    4. Route tool calls to the correct server
    """
    
    def __init__(self):
        self.servers: Dict[str, dict] = {}
        self.tool_to_server: Dict[str, str] = {}
        self._stack = AsyncExitStack()   # owns every open client (and its subprocess)
    
    async def connect_server(self, name: str, command: str, args: List[str]):
        """Connect to an MCP server and discover its tools."""
        params = StdioServerParameters(command=command, args=args)
        # enter_async_context keeps the subprocess and client alive after this
        # method returns. (A plain `async with` here would close the client on
        # exit, leaving a dead object behind.) mcp.Client replaces v1's
        # stdio_client + ClientSession + initialize(): against a 2026-07-28
        # server there is no handshake (it probes server/discover and sends
        # version + capabilities in every request's _meta); against older
        # servers it falls back to initialize automatically.
        client = await self._stack.enter_async_context(Client(params))
        
        tools = (await client.list_tools()).tools
        self.servers[name] = {"client": client, "tools": tools}
        for tool in tools:
            if tool.name in self.tool_to_server:
                raise ValueError(f"Tool name collision: {tool.name}; namespace it")
            self.tool_to_server[tool.name] = name
        print(f"Connected to '{name}': {len(tools)} tools discovered")
    
    async def close(self):
        await self._stack.aclose()
    
    async def call_mcp_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the appropriate MCP server, reusing its client."""
        server_name = self.tool_to_server.get(tool_name)
        if not server_name:
            return f"Error: Unknown tool '{tool_name}'"
        client = self.servers[server_name]["client"]
        result = await client.call_tool(tool_name, arguments)
        text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
        # Tool failures are results with is_error=True (SDK v2 snake_case), not exceptions.
        return f"Error: {text}" if result.is_error else text
    
    def get_tool_descriptions(self) -> str:
        """Format all tools for LLM consumption."""
        lines = []
        for server_name, server in self.servers.items():
            lines.append(f"\n[{server_name}]")
            for tool in server["tools"]:
                lines.append(f"  - {tool.name}: {tool.description}")
        return "\n".join(lines)
    
    async def run_with_llm(self, user_query: str, llm_fn) -> str:
        """
        Run a ReAct loop using the MCP-discovered tools.
        
        Args:
            user_query: The user's request
            llm_fn: A function that takes a prompt and returns a response
        """
        tools_desc = self.get_tool_descriptions()
        system_prompt = f"""You are an AI agent with access to these tools:
{tools_desc}

Respond with:
Action: <tool_name>
Arguments: <JSON arguments>

When done:
Answer: <final answer>"""
        
        history = [system_prompt, f"User: {user_query}"]
        
        for step in range(10):  # max steps
            prompt = "\n\n".join(history)
            response = llm_fn(prompt)
            history.append(f"Assistant: {response}")
            
            if "Answer:" in response:
                return response.split("Answer:")[-1].strip()
            
            # Parse action
            action = None
            arguments = {}
            for line in response.split("\n"):
                if line.startswith("Action:"):
                    action = line.replace("Action:", "").strip()
                elif line.startswith("Arguments:"):
                    try:
                        arguments = json.loads(line.replace("Arguments:", "").strip())
                    except json.JSONDecodeError:
                        pass
            
            if not action:
                return f"Could not parse action from: {response}"
            
            # Execute
            result = await self.call_mcp_tool(action, arguments)
            history.append(f"Observation: {result}")
        
        return "Exceeded maximum steps."
```

---

## 6. SETTING UP THE AGENT

### 6.1 Requirements

```txt
# implementation/requirements.txt
openai>=1.66.0             # Responses API client (optional; default LLM is a mock)
jsonschema>=4.0.0          # Tool parameter validation (optional; fallback built in)
httpx>=0.27.0              # OpenAI-compatible local servers (optional)
mcp>=2.0,<3               # MCP SDK v2 (mcp.Client); spec 2026-07-28
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

Add `anthropic` if you use the Messages API example in 2.2, and a store client (`redis`, a vector DB SDK) when you move memory out of process.

### 6.2 Running the Agent

```bash
# Install dependencies
cd ai-engineering/agents/
pip install -r implementation/requirements.txt

# Run the simple ReAct agent
python -m implementation.simple_react_agent

# Run the orchestrator agent
python -m implementation.orchestrated_agent

# Run the MCP-connected agent (spawns the MCP server over stdio itself)
python -m implementation.agent_with_mcp

# Use a real model instead of the mock
USE_MOCK_LLM=false LLM_PROVIDER=openai LLM_MODEL=<current model id> \
  OPENAI_API_KEY=... python -m implementation.simple_react_agent
```

---

> **Next:** [Agent Production Architecture](04_AGENT_PRODUCTION_ARCHITECTURE.md) → Deployment, guardrails, monitoring
