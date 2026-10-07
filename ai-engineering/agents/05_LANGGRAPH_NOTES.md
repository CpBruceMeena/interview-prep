# 🕸️ LangGraph — Graph-Based State Machine for LLM Agents

> **Target:** Staff/Principal Engineer | **Focus:** Production-grade LangGraph architecture, patterns, and implementation | **Reviewed:** October 2026 (LangGraph 1.x; code tested on 1.2)

!!! tip "30-second answer"
    LangGraph models an agent as a **state machine**: a typed state, nodes that return partial updates (merged by per-key *reducers*), and edges, including conditional ones, that decide what runs next. Its value over a hand-written loop is the runtime: a **checkpointer** saves state after every step keyed by `thread_id`, which gives you multi-turn memory, crash recovery, time travel and **human-in-the-loop** via `interrupt()` + `Command(resume=...)`. Use it when you need durable, branching, resumable flows; a plain tool loop is fine otherwise.

---

## 1. WHAT IS LANGGRAPH?

**LangGraph** is a framework for building **stateful, multi-actor LLM applications** as graphs (cycles allowed, which is how agent loops are expressed). LangGraph 1.0 (October 2025) froze the core API; the primitives below are stable. It models agent logic as a **state machine** with:

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
| **LangChain v1** (`create_agent`) | Prebuilt tool-calling agent + middleware, runs on LangGraph | Via LangGraph checkpointer | Standard agents without hand-building a graph |
| **LangGraph** | Explicit graph / state machine | Typed state + reducers + checkpoints | Custom control flow, durable HITL workflows |
| **CrewAI** | Role-based | Manual delegation | Fast prototyping |
| **OpenAI Agents SDK** | Agent loop with handoffs | Sessions | Quick multi-agent handoffs on OpenAI |
| **Pydantic AI** | Type-safe agent | Pydantic models | Engineering rigor |

LangGraph's old prebuilt `langgraph.prebuilt.create_react_agent` is deprecated in 1.x in favour of LangChain v1's `from langchain.agents import create_agent`. Reach for `StateGraph` directly when the control flow isn't the standard "model ↔ tools" loop.

---

## 2. CORE CONCEPTS

### 2.1 State

The **state** is a typed dictionary (or Pydantic model) that flows through the graph. Every node reads from and writes to this state.

```python
import operator
from typing import TypedDict, Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

class AgentState(TypedDict):
    """Typed state that flows through the graph."""
    messages: Annotated[list[AnyMessage], add_messages]  # append, or replace by message id
    next_step: str
    user_intent: str
    tool_results: Annotated[list[str], operator.add]     # concatenate updates
    errors: Annotated[list[str], operator.add]
    step_count: int                                      # no reducer: last write wins
    final_answer: str
```

For the common case, `from langgraph.graph import MessagesState` gives you a state with just the `messages` key and the `add_messages` reducer.

**State reducers:** LangGraph uses **reducers** to handle how state updates are applied:

| Reducer | Behavior | Use Case |
|---------|----------|----------|
| `add_messages` | Appends new messages; a message with an existing id *replaces* it | Conversation history |
| `operator.add` | List concatenation | Tool results, parallel fan-in |
| (none) | Overwrites field | Simple state fields |
| Custom reducer | Arbitrary merge logic | Complex state merging |

Reducers matter most under **parallelism**: if two nodes in the same step write a key that has no reducer, LangGraph raises `InvalidUpdateError` rather than silently picking one.

### 2.2 Nodes

Nodes are **Python functions** that take the state and return an update:

```python
import os
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model=os.environ["AGENT_MODEL"])   # model ids change; keep them in config

def call_llm(state: AgentState) -> dict:
    """Node that calls the LLM."""
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response], "step_count": state["step_count"] + 1}

def execute_tool(state: AgentState) -> dict:
    """Node that executes EVERY tool call in the last AI message."""
    last_message = state["messages"][-1]
    replies = []
    for call in last_message.tool_calls:          # the model may request several
        fn = TOOLS.get(call["name"])
        result = fn(**call["args"]) if fn else f"Unknown tool: {call['name']}"
        # Each call needs a ToolMessage with the matching id in `messages`;
        # otherwise the provider rejects the next model call.
        replies.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": replies}
```

A node returns only the keys it changes. Nodes can be sync or async; an async graph is run with `ainvoke`/`astream`.

### 2.3 Edges

Edges define the **flow** between nodes:

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(AgentState)
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

A node can also route itself by returning `Command(goto="next_node", update={...})` (from `langgraph.types`), which combines a state update and the routing decision. That is the idiomatic way to do agent-to-agent handoffs.

---

## 3. BUILDING A PRODUCTION-GRADE AGENT

### 3.1 Complete Working Example

```python
"""
LangGraph Production Agent — Full Working Example (LangGraph 1.x)
"""
import json
import os
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import TypedDict, Annotated, Literal

from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool

# ─── Tools ────────────────────────────────────────

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    weather_data = {  # simulated API
        "tokyo": "22°C, partly cloudy",
        "london": "15°C, light rain",
        "paris": "18°C, overcast",
    }
    result = weather_data.get(city.lower(), f"Weather data not available for {city}")
    return json.dumps({"city": city, "weather": result})

@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time for an IANA timezone such as 'Asia/Tokyo'."""
    try:
        now = datetime.now(ZoneInfo(timezone))      # stdlib, no pytz needed
    except ZoneInfoNotFoundError:
        return json.dumps({"error": f"Unknown timezone: {timezone}"})
    return json.dumps({"timezone": timezone, "time": now.strftime("%H:%M:%S"),
                       "date": now.strftime("%Y-%m-%d")})

tools = [get_weather, get_current_time]
tool_map = {t.name: t for t in tools}

# ─── LLM Setup ────────────────────────────────────

def make_llm():
    # Any LangChain chat model with tool calling works. The model id comes
    # from config because ids change; e.g. ChatAnthropic or ChatOpenAI.
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=os.environ["AGENT_MODEL"]).bind_tools(tools)

llm_with_tools = None   # created lazily so tests can inject a fake

# ─── State ────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # reducer: append/merge by id
    step_count: int                                        # no reducer: overwrite
    max_steps: int

# ─── Nodes ────────────────────────────────────────

SYSTEM = SystemMessage(content="You are a helpful assistant with weather and time "
                               "tools. Use tools when needed. Be concise.")

def call_llm(state: AgentState) -> dict:
    """Node: call the model with the conversation so far."""
    global llm_with_tools
    llm_with_tools = llm_with_tools or make_llm()
    response = llm_with_tools.invoke([SYSTEM] + state["messages"])
    return {"messages": [response], "step_count": state["step_count"] + 1}

def execute_tools(state: AgentState) -> dict:
    """Node: run every tool call in the last AI message (there may be several)."""
    last = state["messages"][-1]
    out = []
    for call in last.tool_calls:
        fn = tool_map.get(call["name"])
        try:
            result = fn.invoke(call["args"]) if fn else json.dumps(
                {"error": f"Unknown tool: {call['name']}"})
        except Exception as e:                     # errors go back to the model
            result = json.dumps({"error": str(e)})
        # Every tool call MUST get a ToolMessage with the matching id,
        # or the next model call is rejected by the provider.
        out.append(ToolMessage(content=result, tool_call_id=call["id"]))
    return {"messages": out}

def step_limit_reached(state: AgentState) -> dict:
    return {"messages": [AIMessage(
        content=f"I couldn't finish within {state['max_steps']} steps. "
                "Try splitting the request into smaller parts.")]}

# ─── Conditional Routing ──────────────────────────

def route_after_llm(state: AgentState) -> Literal["tools", "limit", "__end__"]:
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return "__end__"                            # plain answer: done
    if state["step_count"] >= state["max_steps"]:
        return "limit"
    return "tools"

# ─── Build Graph ──────────────────────────────────

def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", execute_tools)
    graph.add_node("limit", step_limit_reached)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", route_after_llm)
    graph.add_edge("tools", "llm")                  # loop back after tools
    graph.add_edge("limit", END)
    return graph

# Compile ONCE at startup and reuse; the checkpointer holds state per thread.
app = build_agent_graph().compile(checkpointer=InMemorySaver())

def run_agent(user_query: str, thread_id: str) -> list:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
    result = app.invoke(
        {"messages": [HumanMessage(content=user_query)], "step_count": 0, "max_steps": 10},
        config,
    )
    return result["messages"]

if __name__ == "__main__":
    for m in run_agent("What's the weather in Paris and the time in Asia/Tokyo?", "demo-1"):
        print(f"{m.type}: {str(m.content)[:100]}")
```

Key points: run *all* tool calls in a turn, answer every call id, put the step limit in state **and** set LangGraph's own `recursion_limit` (a cap on super-steps that raises `GraphRecursionError`; the default was 25 in older versions and is much higher in recent 1.x, so set it explicitly). Compile once and reuse the compiled graph; it is thread-safe and the checkpointer separates conversations by `thread_id`. Calling `run_agent` again with the same `thread_id` continues that conversation, because the checkpointer reloads the earlier messages and `add_messages` appends the new one.

### 3.2 Graph Visualization

```python
# Generate graph visualization
from IPython.display import Image, display

def visualize_graph():
    graph = build_agent_graph()
    app = graph.compile()
    print(app.get_graph().draw_mermaid())          # Mermaid text, no network needed
    display(Image(app.get_graph().draw_mermaid_png()))  # PNG (renders via a web service by default)

# Outputs:
# ┌──────────┐     ┌──────────┐
# │   START  │────→│   LLM    │
# └──────────┘     └────┬─────┘
#                       │
#              ┌────────┼────────┐
#              ▼        ▼        ▼
#          ┌──────┐ ┌──────┐ ┌───────┐
#          │Tools │ │Limit │ │  END  │
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

LangGraph supports **interrupts** for human approval. `interrupt(payload)` inside a node saves a checkpoint and returns control to the caller with the payload under `__interrupt__`. Later, possibly from another process, `invoke(Command(resume=value), config)` with the same `thread_id` resumes, and `interrupt()` returns `value`.

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

class State(TypedDict):
    action: dict
    result: str

def propose(state: State) -> dict:
    return {"action": {"tool": "refund", "order_id": "A1", "amount": 120}}

def human_review(state: State) -> Command:
    # Everything above interrupt() re-runs on resume: keep it side-effect free.
    decision = interrupt({"question": "Approve this action?", "action": state["action"]})
    if decision.get("approved"):
        return Command(goto="execute")
    return Command(goto=END, update={"result": "rejected by reviewer"})

def execute(state: State) -> dict:
    return {"result": f"refunded {state['action']['amount']}"}

g = StateGraph(State)
g.add_node("propose", propose)
g.add_node("human_review", human_review, destinations=("execute", END))
g.add_node("execute", execute)
g.add_edge(START, "propose")
g.add_edge("propose", "human_review")
g.add_edge("execute", END)
app = g.compile(checkpointer=InMemorySaver())     # interrupts need a checkpointer

config = {"configurable": {"thread_id": "order-A1"}}
first = app.invoke({}, config)
print(first["__interrupt__"][0].value)            # payload shown to the reviewer
# ...later, possibly in another process sharing the same checkpointer...
final = app.invoke(Command(resume={"approved": True}), config)
print(final["result"])                             # refunded 120
```

Rules interviewers check:

- **A checkpointer and a `thread_id` are mandatory**: the paused state has to live somewhere.
- **The node re-executes from the top on resume.** Code before `interrupt()` runs twice, so it must be idempotent (no "send email, then interrupt"). Put side effects in the node *after* approval.
- **Multiple interrupts in one node** are matched to resume values by order, so don't make the number or order of `interrupt()` calls conditional.
- Static breakpoints (`interrupt_before=[...]` / `interrupt_after=[...]` at compile or invoke time) still exist and are handy for debugging; `interrupt()` is the production mechanism. `NodeInterrupt` is deprecated.
- With a durable checkpointer (Postgres), an approval can take days; nothing is held open while waiting.

### 4.2 Parallel Execution

Use `Send` for fan-out/fan-in patterns:

```python
import operator
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

class State(TypedDict):
    topics: list[str]
    findings: Annotated[list[str], operator.add]   # reducer merges parallel writes

class TopicState(TypedDict):
    topic: str

def planner(state: State) -> dict:
    return {}

def fan_out(state: State) -> list[Send]:
    return [Send("research", {"topic": t}) for t in state["topics"]]

def research(state: TopicState) -> dict:
    return {"findings": [f"notes on {state['topic']}"]}

def merge(state: State) -> dict:
    return {}

g = StateGraph(State)
g.add_node("planner", planner); g.add_node("research", research); g.add_node("merge", merge)
g.add_edge(START, "planner")
g.add_conditional_edges("planner", fan_out, ["research"])
g.add_edge("research", "merge"); g.add_edge("merge", END)
print(g.compile().invoke({"topics": ["a", "b", "c"]})["findings"])
```

`Send(node, arg)` launches one instance of `node` per item with its own input, all in the same super-step; the `operator.add` reducer on `findings` merges their writes (map-reduce). Without a reducer, the parallel writes would conflict.

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

Adding a compiled subgraph directly as a node works when parent and child share state keys (the shared keys flow through). If the schemas differ, call the subgraph from a wrapper node that maps parent state to child input and back. Subgraphs are how you build multi-agent systems: each agent is a subgraph, and a supervisor routes between them (often with `Command(goto=...)`).

---

## 5. PERSISTENCE & CHECKPOINTING

### 5.1 Checkpointer Backends

| Backend | Package | Use Case | Features |
|---------|---------|----------|----------|
| `InMemorySaver` (`MemorySaver` is the old alias) | `langgraph` | Dev/testing | In-memory, lost on restart |
| `SqliteSaver` / `AsyncSqliteSaver` | `langgraph-checkpoint-sqlite` | Single node, local apps | Simple file persistence |
| `PostgresSaver` / `AsyncPostgresSaver` | `langgraph-checkpoint-postgres` | Production | Durable, shared across replicas |
| `RedisSaver` | `langgraph-checkpoint-redis` | Low-latency, TTL-based | Maintained by Redis; TTL support |

A checkpoint is written after every super-step. What you get from that: multi-turn memory per thread, resume after a crash, human-in-the-loop, and **time travel** (`get_state_history(config)` and replaying or forking from an earlier checkpoint). The `durability` option on `invoke`/`stream` (`"exit"`, `"async"`, `"sync"`) trades write overhead against how much progress a crash can lose.

**Checkpointer vs Store:** the checkpointer is *thread-scoped* (one conversation's state). Long-term memory shared across threads (user preferences, facts) goes in a **Store** (`InMemoryStore`, `PostgresStore`), passed as `compile(store=...)` and namespaced per user.

### 5.2 Production Checkpointer

```python
# pip install langgraph-checkpoint-postgres  (uses psycopg 3, not asyncpg)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def main(dsn: str):
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()          # create tables once (e.g. in a migration job)
        app = build_agent_graph().compile(checkpointer=checkpointer)

        async def run(user_id: str, session_id: str, query: str):
            # Namespace thread ids by user so one user can't resume another's thread.
            config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
            # No manual "load then resume": the checkpointer restores this
            # thread's state and add_messages appends the new message.
            async for chunk in app.astream(
                {"messages": [HumanMessage(content=query)], "step_count": 0, "max_steps": 25},
                config, stream_mode="updates",
            ):
                yield chunk
        ...
```

Operational notes: checkpoints grow with every step (prune old threads), large tool outputs bloat every checkpoint (store blobs elsewhere and keep references in state), and two concurrent requests on the same `thread_id` will race (serialize per thread).

---

## 6. PRODUCTION BEST PRACTICES

### 6.1 Error Handling

```python
from langgraph.types import RetryPolicy

# Transient failures: let the runtime retry the node with backoff + jitter.
graph.add_node(
    "tools", execute_tools,
    retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.5,
                             retry_on=(TimeoutError, ConnectionError)),
)

# Expected failures: catch inside the node and record them in state
# (with an operator.add reducer on `errors`), then route on that.
def safe_tool_execution(state: AgentState) -> dict:
    try:
        return execute_tools(state)
    except ValueError as e:
        return {"errors": [str(e)]}
```

Recent 1.x releases also accept a per-node `timeout=` (cooperative, async nodes) on `add_node`; check your version. For "stop and ask a human" on failure, call `interrupt()` instead of the deprecated `NodeInterrupt`. Remember that a retried node re-runs from the start, so tool side effects need idempotency keys.

### 6.2 Monitoring & Tracing

```python
# LangSmith tracing (set in the environment, not in code, in production)
#   LANGSMITH_TRACING=true  LANGSMITH_API_KEY=...  LANGSMITH_PROJECT=production-agent
# (LANGCHAIN_TRACING_V2 / LANGCHAIN_PROJECT are the older names, still honoured.)
# LangSmith can also export OpenTelemetry, or you can instrument with OTel directly.

from langchain_core.callbacks import BaseCallbackHandler

class MetricsCallback(BaseCallbackHandler):
    def on_llm_end(self, response, **kwargs):
        metrics.llm_calls.inc()
        for gen in response.generations[0]:
            usage = getattr(gen.message, "usage_metadata", None) or {}  # provider-neutral
            metrics.input_tokens.observe(usage.get("input_tokens", 0))
            metrics.output_tokens.observe(usage.get("output_tokens", 0))

# app.invoke(inputs, {"callbacks": [MetricsCallback()], "configurable": {...}})
```

### 6.3 Testing

Don't call a real model in unit tests: inject a fake that returns scripted `AIMessage`s, then assert on routing, tool messages and limits. Keep real-model runs for the eval suite.

```python
# test_agent.py  (the example in 3.1 saved as agent.py)
import agent
from langchain_core.messages import AIMessage, HumanMessage

class FakeLLM:
    """Returns scripted AIMessages: deterministic, no network, no API key."""
    def __init__(self, replies): self.replies = list(replies)
    def invoke(self, messages): return self.replies.pop(0)

def run(replies, max_steps=10):
    agent.llm_with_tools = FakeLLM(replies)
    g = agent.build_agent_graph().compile()          # no checkpointer needed
    return g.invoke({"messages": [HumanMessage("hi")], "step_count": 0,
                     "max_steps": max_steps})

def test_tool_call_then_answer():
    out = run([
        AIMessage("", tool_calls=[{"name": "get_weather", "args": {"city": "London"}, "id": "c1"}]),
        AIMessage("It's 15°C and raining in London."),
    ])
    tool_msgs = [m for m in out["messages"] if m.type == "tool"]
    assert tool_msgs[0].tool_call_id == "c1" and "light rain" in tool_msgs[0].content
    assert out["messages"][-1].content.startswith("It's 15")

def test_step_limit():
    loops = [AIMessage("", tool_calls=[{"name": "get_weather", "args": {"city": "x"},
                                        "id": f"c{i}"}]) for i in range(3)]
    out = run(loops, max_steps=3)
    assert out["step_count"] == 3
    assert "couldn't finish" in out["messages"][-1].content
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

Use a simple tool loop (or `create_agent`) for standard "model ↔ tools" interactions where the overhead of graph management isn't justified.

### Q2: How does LangGraph handle state management?

**Answer:** Through **typed state schemas** (TypedDict/Pydantic) with **reducers**:
- Each node returns a state update (partial state)
- Reducers merge updates into the current state
- `add_messages` reducer appends to a list (for conversation history)
- Custom reducers can implement arbitrary merge logic
- Keys without a reducer are overwritten; parallel writes to such a key are an error
- Checkpoints persist state after every super-step for fault tolerance

### Q3: How do you scale LangGraph agents in production?

**Answer:**
- Make workers stateless: `AsyncPostgresSaver` (or the Redis saver) as the shared checkpointer, so any replica can serve any thread
- Run multiple graph instances behind a load balancer; serialize requests per `thread_id` so two replicas don't advance the same thread at once
- Bound every run: `recursion_limit`, step and token budgets in state, and timeouts on model and tool calls (no default node timeout; set one)
- Trace across instances (LangSmith or OpenTelemetry) keyed by thread id
- Retry policies and circuit breakers for downstream tools; idempotency keys because nodes re-run on retry and resume
- Prune old checkpoints and keep large payloads out of state

### Q4: How does human-in-the-loop work, and what is the classic bug?

**Answer:** `interrupt(payload)` persists a checkpoint and surfaces the payload to the caller; `invoke(Command(resume=value), config)` on the same `thread_id` resumes. The classic bug is forgetting that **the interrupted node restarts from its first line** on resume, so any side effect before `interrupt()` (an email, a DB write, a paid API call) happens twice. Keep pre-interrupt code pure, or split it into an earlier node.

### Q5: `create_agent` or a hand-built `StateGraph`?

**Answer:** `create_agent` (LangChain v1) when the flow is the standard model ↔ tools loop and middleware covers your customization (summarization, HITL on certain tools, dynamic prompts). A custom `StateGraph` when the control flow is yours: multi-stage pipelines, supervisors and handoffs, parallel fan-out, or approval steps that aren't tied to a single tool call.

---

> **Next:** [Python Async/Await](06_PYTHON_ASYNC_AWAIT.md) → Understanding async Python for agent systems
