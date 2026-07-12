# 🕸️ LangGraph — Graph-Based State Machine for LLM Agents

> **Target:** Staff/Principal Engineer | **Focus:** Production-grade LangGraph architecture, patterns, and implementation

---

## 1. WHAT IS LANGGRAPH?

**LangGraph** is a framework for building **stateful, multi-actor LLM applications** as directed graphs. Unlike linear chains (LangChain's legacy `LLMChain`), LangGraph models agent logic as a **state machine** with:

- **Nodes** — computational steps (LLM calls, tool execution, human input)
- **Edges** — conditional routing between nodes
- **State** — shared, typed state object persisted across nodes
- **Checkpoints** — automatic persistence of state at every step

```
         ┌─────────────────────────────────────────┐
         │              GRAPH                        │
         │                                           │
         │  ┌──────────┐    conditional     ┌──────┐ │
         │  │  Node A  │ ─────────────────→ │Node B│ │
         │  │ (LLM)    │                    │(Tool)│ │
         │  └────┬─────┘                    └──┬───┘ │
         │       │                             │     │
         │       │      ┌──────────┐           │     │
         │       └─────→│  Node C  │ ←─────────┘     │
         │              │ (Human)  │                  │
         │              └──────────┘                  │
         └───────────────────────────────────────────┘
```

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/langgraph-flow.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated LangGraph agent flow — created with <a href="https://remotion.dev">Remotion</a>. Nodes appear sequentially with animated edges showing the routing logic (START → LLM → Tools/Error/END).</em>
</p>

### 1.1 LangGraph vs LangChain vs Other Frameworks

| Framework | Paradigm | State Management | Best For |
|-----------|----------|-----------------|----------|
| **LangChain** | Linear chain | Manual | Simple sequential pipelines |
| **LangGraph** | Graph/State Machine | Automatic (typed) | Complex agent loops, production |
| **CrewAI** | Role-based | Manual delegation | Fast prototyping |
| **OpenAI Agents SDK** | Event loop | Built-in | GPT-native workflows |
| **Pydantic AI** | Type-safe agent | Pydantic models | Engineering rigor |

---

## 2. CORE CONCEPTS

### 2.1 State

The **state** is a typed dictionary (or Pydantic model) that flows through the graph. Every node reads from and writes to this state.

```python
from typing import TypedDict, List, Annotated
from langgraph.graph import add_messages

class AgentState(TypedDict):
    """Typed state that flows through the graph."""
    messages: Annotated[List, add_messages]  # Append-only via add_messages
    next_step: str
    user_intent: str
    tool_results: List[str]
    errors: List[str]
    step_count: int
    final_answer: str
```

**State reducers:** LangGraph uses **reducers** to handle how state updates are applied:

| Reducer | Behavior | Use Case |
|---------|----------|----------|
| `add_messages` | Appends to list | Conversation history |
| `operator.add` | List concatenation | Tool results aggregation |
| `default` | Overwrites field | Simple state fields |
| Custom reducer | Arbitrary merge logic | Complex state merging |

### 2.2 Nodes

Nodes are **Python functions** that take the state and return an update:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")

def call_llm(state: AgentState) -> dict:
    """Node that calls the LLM."""
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response], "step_count": state["step_count"] + 1}

def execute_tool(state: AgentState) -> dict:
    """Node that executes a tool call."""
    last_message = state["messages"][-1]
    tool_name = last_message.tool_calls[0]["name"]
    tool_args = last_message.tool_calls[0]["args"]
    
    if tool_name == "search_weather":
        result = search_weather(**tool_args)
    elif tool_name == "get_time":
        result = get_time(**tool_args)
    else:
        result = f"Unknown tool: {tool_name}"
    
    return {"tool_results": [result]}
```

### 2.3 Edges

Edges define the **flow** between nodes:

```python
from langgraph.graph import StateGraph, START, END

# Basic edge: always goes from A to B
graph.add_edge("node_a", "node_b")

# Conditional edge: route based on state
def should_continue(state: AgentState) -> str:
    """Route based on whether tool calls are needed."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "execute_tool"
    elif state["step_count"] >= 10:
        return "error_handler"
    else:
        return "finish"

graph.add_conditional_edges(
    "call_llm",
    should_continue,
    {
        "execute_tool": "execute_tool_node",
        "error_handler": "error_node",
        "finish": END
    }
)
```

---

## 3. BUILDING A PRODUCTION-GRADE AGENT

### 3.1 Complete Working Example

```python
"""
LangGraph Production Agent — Full Working Example
"""
import json
from typing import TypedDict, List, Annotated, Literal
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool

# ─── Tools ────────────────────────────────────────

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    # Simulate API call
    weather_data = {
        "tokyo": "22°C, partly cloudy",
        "london": "15°C, light rain",
        "new york": "28°C, sunny",
        "paris": "18°C, overcast",
    }
    result = weather_data.get(city.lower(), f"Weather data not available for {city}")
    return json.dumps({"city": city, "weather": result})

@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time for a timezone."""
    from datetime import datetime, timezone as tz
    import pytz
    try:
        tz_obj = pytz.timezone(timezone)
        current_time = datetime.now(tz_obj)
        return json.dumps({
            "timezone": timezone,
            "time": current_time.strftime("%H:%M:%S"),
            "date": current_time.strftime("%Y-%m-%d")
        })
    except Exception as e:
        return json.dumps({"error": f"Unknown timezone: {timezone}"})

tools = [get_weather, get_current_time]
tool_map = {tool.name: tool for tool in tools}

# ─── LLM Setup ────────────────────────────────────

llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(tools)

# ─── State ────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[List, add_messages]
    next_step: str
    step_count: int
    max_steps: int

# ─── Nodes ────────────────────────────────────────

def call_llm(state: AgentState) -> dict:
    """Node: Call the LLM with current messages."""
    system_prompt = SystemMessage(
        content="You are a helpful assistant with access to weather and time tools. "
                "Use tools when needed. Be concise and accurate."
    )
    messages = [system_prompt] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {
        "messages": [response],
        "step_count": state["step_count"] + 1
    }

def execute_tools(state: AgentState) -> dict:
    """Node: Execute tool calls from the LLM."""
    last_message = state["messages"][-1]
    tool_messages = []
    
    for tool_call in last_message.tool_calls:
        tool_fn = tool_map.get(tool_call["name"])
        if not tool_fn:
            result = json.dumps({"error": f"Unknown tool: {tool_call['name']}"})
        else:
            result = tool_fn.invoke(tool_call["args"])
        
        tool_messages.append(ToolMessage(
            content=result,
            tool_call_id=tool_call["id"]
        ))
    
    return {"messages": tool_messages}

def error_handler(state: AgentState) -> dict:
    """Node: Handle errors when max steps exceeded."""
    return {
        "messages": [AIMessage(
            content="I apologize, but I was unable to complete your request within "
                    f"the step limit ({state['max_steps']} steps). Please try "
                    "breaking down your request into smaller parts."
        )]
    }

# ─── Conditional Routing ──────────────────────────

def route_after_llm(state: AgentState) -> Literal["tools", "error", "__end__"]:
    """Route based on LLM output."""
    last_message = state["messages"][-1]
    
    # Check step limit
    if state["step_count"] >= state["max_steps"]:
        return "error"
    
    # Check if tool calls are needed
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    # Otherwise finish
    return "__end__"

# ─── Build Graph ──────────────────────────────────

def build_agent_graph() -> StateGraph:
    """Build the agent state graph."""
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("llm", call_llm)
    graph.add_node("tools", execute_tools)
    graph.add_node("error", error_handler)
    
    # Add edges
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", route_after_llm)
    graph.add_edge("tools", "llm")      # Loop back to LLM after tools
    graph.add_edge("error", END)
    
    return graph

# ─── Compile & Run ────────────────────────────────

def run_agent(user_query: str) -> List:
    """Run the agent with a user query."""
    # Build graph
    graph = build_agent_graph()
    
    # Compile with checkpointing
    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    
    # Initial state
    config = {"configurable": {"thread_id": "demo-session-1"}}
    initial_state = {
        "messages": [HumanMessage(content=user_query)],
        "step_count": 0,
        "max_steps": 10,
    }
    
    # Run
    final_state = None
    for event in app.stream(initial_state, config, stream_mode="values"):
        final_state = event
    
    if final_state:
        return final_state["messages"]
    return []

# ─── Demo ─────────────────────────────────────────

if __name__ == "__main__":
    print("=== LangGraph Agent Demo ===\n")
    
    # Test 1: Simple query
    print("--- Test 1: Simple weather query ---")
    messages = run_agent("What's the weather in Tokyo?")
    for msg in messages:
        if hasattr(msg, 'content') and msg.content:
            print(f"{msg.type}: {msg.content[:100]}")
    
    print("\n--- Test 2: Multi-step query ---")
    messages = run_agent("What's the weather in Paris and the time in Asia/Tokyo?")
    for msg in messages:
        if hasattr(msg, 'content') and msg.content:
            print(f"{msg.type}: {msg.content[:100]}")
```

### 3.2 Graph Visualization

```python
# Generate graph visualization
from IPython.display import Image, display

def visualize_graph():
    graph = build_agent_graph()
    app = graph.compile()
    display(Image(app.get_graph().draw_mermaid_png()))

# Outputs:
# ┌──────────┐     ┌──────────┐
# │   START  │────→│   LLM    │
# └──────────┘     └────┬─────┘
#                       │
#              ┌────────┼────────┐
#              ▼        ▼        ▼
#          ┌──────┐ ┌──────┐ ┌───────┐
#          │Tools │ │Error │ │  END  │
#          └──┬───┘ └──────┘ └───────┘
#             │
#             └────────→┐
#                       ▼
#                    ┌──────┐
#                    │ LLM  │ (loop)
#                    └──────┘
```

---

## 4. ADVANCED PATTERNS

### 4.1 Human-in-the-Loop

LangGraph supports **interrupts** for human approval:

```python
from langgraph.types import interrupt, Command

def human_review(state: AgentState) -> dict:
    """Node that pauses for human approval."""
    last_tool_call = state["messages"][-1].tool_calls[-1]
    
    # Pause and ask for human input
    human_response = interrupt({
        "question": "Approve this tool call?",
        "tool_call": last_tool_call,
        "context": state["messages"][:-1]
    })
    
    if human_response.get("approved"):
        return {"next_step": "execute_tool"}
    else:
        return {"next_step": "revise"}
```

### 4.2 Parallel Execution

Use `Send` for fan-out/fan-in patterns:

```python
from langgraph.types import Send

def continue_to_research(state: AgentState):
    """Fan-out to parallel research agents."""
    topics = state["research_topics"]
    return [
        Send("research_agent", {"topic": topic})
        for topic in topics
    ]

# In graph:
graph.add_conditional_edges("planner", continue_to_research)
```

### 4.3 Subgraphs

Compose smaller graphs into larger ones:

```python
def build_research_subgraph() -> StateGraph:
    """A reusable research subgraph."""
    subgraph = StateGraph(ResearchState)
    subgraph.add_node("search", search_web)
    subgraph.add_node("summarize", summarize_results)
    subgraph.add_edge("search", "summarize")
    subgraph.add_edge(START, "search")
    subgraph.add_edge("summarize", END)
    return subgraph.compile()

# Use in parent graph
parent_graph.add_node("research", build_research_subgraph())
```

---

## 5. PERSISTENCE & CHECKPOINTING

### 5.1 Checkpointer Backends

| Backend | Use Case | Features |
|---------|----------|----------|
| `MemorySaver` | Dev/testing | In-memory, lost on restart |
| `SqliteSaver` | Single-node | Simple persistence, SQLite |
| `PostgresSaver` | Production | ACID, concurrency, durable |
| `RedisSaver` | High-throughput | Fast, distributed, TTL support |

### 5.2 Production Checkpointer

```python
from langgraph.checkpoint.postgres import PostgresSaver
import asyncpg

class ProductionAgent:
    def __init__(self, dsn: str):
        self.checkpointer = PostgresSaver(
            conn=asyncpg.connect(dsn)
        )
        self.graph = build_agent_graph()
        self.app = self.graph.compile(
            checkpointer=self.checkpointer
        )
    
    async def run(self, user_id: str, session_id: str, query: str):
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_id": user_id
            }
        }
        
        # Resume from checkpoint if exists
        state = await self.checkpointer.aget(config)
        if state:
            # Continue from where it left off
            pass
        else:
            # Start fresh
            state = {
                "messages": [HumanMessage(content=query)],
                "step_count": 0,
                "max_steps": 25
            }
        
        async for event in self.app.astream(state, config):
            yield event
```

---

## 6. PRODUCTION BEST PRACTICES

### 6.1 Error Handling

```python
from langgraph.errors import NodeInterrupt

def safe_tool_execution(state: AgentState) -> dict:
    """Node with comprehensive error handling."""
    try:
        return execute_tools(state)
    except TimeoutError:
        raise NodeInterrupt("Tool execution timed out")
    except ValueError as e:
        return {"errors": state["errors"] + [str(e)], "next_step": "retry"}
    except Exception as e:
        return {"errors": state["errors"] + [f"Unexpected: {str(e)}"], "next_step": "fallback"}
```

### 6.2 Monitoring & Tracing

```python
# LangSmith integration for full observability
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "production-agent"

# Custom callbacks
from langchain.callbacks.base import BaseCallbackHandler

class MetricsCallback(BaseCallbackHandler):
    def on_llm_end(self, response, **kwargs):
        metrics.llm_calls.inc()
        tokens = response.llm_output.get("token_usage", {})
        metrics.input_tokens.observe(tokens.get("prompt_tokens", 0))
        metrics.output_tokens.observe(tokens.get("completion_tokens", 0))
```

### 6.3 Testing

```python
import pytest
from langgraph.graph import StateGraph

class TestAgentGraph:
    def test_basic_flow(self):
        """Test that basic query reaches END."""
        graph = build_agent_graph()
        app = graph.compile()
        
        result = app.invoke({
            "messages": [HumanMessage(content="Hello")],
            "step_count": 0,
            "max_steps": 10
        })
        
        assert len(result["messages"]) > 0
        assert result["step_count"] <= 10
    
    def test_tool_call_flow(self):
        """Test that tool-requiring query calls tools."""
        graph = build_agent_graph()
        app = graph.compile()
        
        result = app.invoke({
            "messages": [HumanMessage(content="What's the weather in London?")],
            "step_count": 0,
            "max_steps": 10
        })
        
        # Should have tool calls
        tool_calls = [
            msg for msg in result["messages"] 
            if hasattr(msg, 'tool_calls') and msg.tool_calls
        ]
        assert len(tool_calls) > 0
    
    def test_max_steps_limit(self):
        """Test that agent stops at max steps."""
        graph = build_agent_graph()
        app = graph.compile()
        
        result = app.invoke({
            "messages": [HumanMessage(content="Do 20 things for me")],
            "step_count": 0,
            "max_steps": 5
        })
        
        assert result["step_count"] <= 5
```

---

## 7. INTERVIEW QUESTIONS

### Q1: When would you choose LangGraph over a simple ReAct loop?

**Answer:** Choose LangGraph when:
- You need **state persistence** across interruptions
- The flow has **complex branching** (multiple conditional paths)
- You need **human-in-the-loop** approval gates
- The agent requires **parallel execution** of sub-tasks
- You need **fine-grained observability** of each step

Use a simple ReAct loop for linear, stateless interactions where the overhead of graph management isn't justified.

### Q2: How does LangGraph handle state management?

**Answer:** Through **typed state schemas** (TypedDict/Pydantic) with **reducers**:
- Each node returns a state update (partial state)
- Reducers merge updates into the current state
- `add_messages` reducer appends to a list (for conversation history)
- Custom reducers can implement arbitrary merge logic
- Checkpoints persist state at every step for fault tolerance

### Q3: How do you scale LangGraph agents in production?

**Answer:**
- Use `PostgresSaver` or `RedisSaver` for distributed checkpointing
- Run multiple graph instances behind a load balancer
- Use LangSmith for tracing across instances
- Implement circuit breakers for downstream tool calls
- Configure timeouts per node (default 30s, tune per use case)

---

> **Next:** [Python Async/Await](06_PYTHON_ASYNC_AWAIT.md) → Understanding async Python for agent systems
