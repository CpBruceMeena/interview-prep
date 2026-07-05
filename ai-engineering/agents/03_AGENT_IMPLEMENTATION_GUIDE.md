# 🛠️ Agent Implementation Guide — Building Production Agents

> **Target:** Staff Engineer | **Focus:** Runnable code, design patterns, MCP integration

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
│   ├── simple_react_agent.py              # Basic ReAct agent
│   ├── agent_with_tools.py                # Tool-registry agent
│   ├── orchestrated_agent.py              # Orchestrator-Worker
│   ├── agent_with_mcp.py                  # Agent using MCP servers
│   ├── common/
│   │   ├── __init__.py
│   │   ├── tool_registry.py               # Tool registration & validation
│   │   ├── memory.py                      # Short-term + working memory
│   │   ├── llm_client.py                  # LLM abstraction (OpenAI, LM Studio)
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
# implementation/simple_react_agent.py
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
    """Mock LLM for demonstration (replace with real LLM API)."""
    # In production, call: openai.chat.completions.create(...) or similar
    if "search_web" in prompt:
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

---

## 3. IMPLEMENTATION — AGENT WITH TOOL REGISTRY

### 3.1 Full Tool Registry with Guardrails

```python
# implementation/agent_with_tools.py
"""
Agent with comprehensive tool registry, validation, and guardrails.
Integrates with the MCP common/ modules for rate limiting and auth.
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
    parameters: dict  # JSON Schema
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
        from agents.implementation.common.guardrails import TokenBucket
        self.rate_limiters[tool.name] = TokenBucket(
            rate=tool.rate_limit, burst=int(tool.rate_limit * 2)
        )
    
    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self.tools.get(name)
    
    def list_tools(self) -> List[dict]:
        """Return tools in MCP-compatible format."""
        return [t for t in self.tools.values()]
    
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
        
        # 1. Schema validation
        try:
            jsonschema.validate(
                instance=params, 
                schema={"type": "object", "properties": tool.parameters,
                       "required": list(tool.parameters.keys())}
            )
        except jsonschema.ValidationError as e:
            return f"Error: Invalid parameters - {e.message}"
        
        # 2. Authorization
        roles_hierarchy = {"admin": 3, "editor": 2, "user": 1}
        if roles_hierarchy.get(user_role, 0) < roles_hierarchy.get(tool.required_role, 0):
            return f"Error: Insufficient permissions for '{tool_name}'"
        
        # 3. Rate limit
        limiter = self.rate_limiters[tool_name]
        if not limiter.consume():
            return f"Error: Rate limit exceeded for '{tool_name}'. Try again later."
        
        # 4. Execute
        try:
            result = tool.fn(**params)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
    
    def to_mcp_format(self) -> List[dict]:
        """Export all tools in MCP format for agent consumption."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": list(t.parameters.keys()),
                }
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
    parameters={"query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results"}},
    fn=search_knowledge_base,
    category="read"
))
registry.register(ToolSpec(
    name="get_user",
    description="Get user account information by user ID",
    parameters={"user_id": {"type": "integer", "description": "User ID"}},
    fn=get_user_account,
    required_role="user",
    category="read"
))
registry.register(ToolSpec(
    name="send_notification",
    description="Send a notification to a user",
    parameters={"user_id": {"type": "integer"}, "message": {"type": "string"}},
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
# implementation/orchestrated_agent.py
"""
Orchestrator-Worker agent pattern.
The orchestrator decomposes tasks and delegates to specialized workers.
"""

import asyncio
import json
from typing import List, Dict, Optional, Callable, Any
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
    
    def __init__(self, name: str, description: str, tools: List[Tool]):
        self.name = name
        self.description = description
        self.tools = {t.name: t for t in tools}
    
    async def execute(self, task: Task) -> Task:
        """Execute a task using the worker's tools."""
        task.status = "running"
        try:
            # Simple execution: use the description as prompt
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
            
            # Execute ready tasks in parallel
            tasks = []
            for task in ready:
                worker = self.workers[task.assigned_to]
                tasks.append(worker.execute(task))
            
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

---

## 5. IMPLEMENTATION — AGENT WITH MCP TOOLS

### 5.1 Connecting an Agent to MCP Servers

```python
# implementation/agent_with_mcp.py
"""
Agent that discovers and uses tools from MCP servers.
Connects to calculator_server, database_server, and rag_server.
"""

import asyncio
import json
from typing import List, Dict, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPToolAgent:
    """
    Agent that connects to MCP servers and uses their tools.
    
    Architecture:
    1. Connect to each MCP server
    2. Discover tools via tools/list
    3. Present unified tool registry to LLM
    4. Route tool calls to the correct server
    """
    
    def __init__(self):
        self.servers: Dict[str, dict] = {}
        self.tool_to_server: Dict[str, str] = {}
    
    async def connect_server(self, name: str, command: str, args: List[str]):
        """Connect to an MCP server and discover its tools."""
        server_params = StdioServerParameters(
            command=command,
            args=args
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Discover tools
                tools = await session.list_tools()
                
                # Store server info
                self.servers[name] = {
                    "session": session,
                    "tools": tools.tools,
                    "read": read,
                    "write": write,
                    "params": server_params,
                }
                
                # Map tool names to server
                for tool in tools.tools:
                    self.tool_to_server[tool.name] = name
                
                print(f"Connected to '{name}': {len(tools.tools)} tools discovered")
                for t in tools.tools:
                    print(f"  - {t.name}: {t.description}")
    
    async def call_mcp_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the appropriate MCP server."""
        server_name = self.tool_to_server.get(tool_name)
        if not server_name:
            return f"Error: Unknown tool '{tool_name}'"
        
        server = self.servers[server_name]
        async with stdio_client(server["params"]) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return result.content[0].text
    
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
# Core
openai>=1.0.0              # LLM API (or use LM Studio)
jsonschema>=4.0.0          # Tool parameter validation

# MCP Integration
mcp>=1.0.0                 # MCP SDK for agent-to-server communication

# Memory
redis>=5.0.0               # Long-term memory store (optional)
chromadb>=0.4.0            # Vector memory for episodic recall (optional)

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0

# Utility
python-dotenv>=1.0.0       # Environment configuration
httpx>=0.27.0              # HTTP client for API calls
```

### 6.2 Running the Agent

```bash
# Install dependencies
cd ai-engineering/agents/
pip install -r implementation/requirements.txt

# Run the simple ReAct agent
python -m implementation.simple_react_agent

# Run the orchestrator agent
python -m implementation.orchestrated_agent

# Run the MCP-connected agent (with MCP servers running)
python -m implementation.agent_with_mcp
```

---

> **Next:** [Agent Production Architecture](04_AGENT_PRODUCTION_ARCHITECTURE.md) → Deployment, guardrails, monitoring
