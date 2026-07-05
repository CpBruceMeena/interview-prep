# 🤖 AI Agent Fundamentals — Architectures, Patterns & Orchestration

> **Target:** Staff/Principal Engineer | **Focus:** Production-grade agent system design from first principles

---

## 1. WHAT IS AN AI AGENT?

An **AI agent** is an autonomous system that uses an LLM to reason, plan, and execute actions in pursuit of a goal. Unlike a simple chatbot that generates text, an agent can:

- **Reason** about its goal and break it into sub-tasks
- **Use tools** to interact with external systems (databases, APIs, file systems)
- **Maintain memory** across interactions (conversation history, state, learned facts)
- **Execute actions** and observe their results
- **Adapt** its plan based on new information or errors

```
User Goal
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                    AI AGENT                           │
│                                                       │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌────────┐ │
│  │ Perceive│→ │  Reason  │→ │  Plan  │→ │  Act   │ │
│  │ (Input) │  │ (LLM)    │  │ (Steps)│  │ (Tool) │ │
│  └─────────┘  └──────────┘  └────────┘  └────┬───┘ │
│       ▲                                       │     │
│       └─────────── Observe ←──────────────────┘     │
└─────────────────────────────────────────────────────┘
```

### 1.1 Agent vs Workflow

| Dimension | Workflow | Agent |
|-----------|----------|-------|
| **Execution** | Deterministic, predefined steps | Non-deterministic, LLM-decided |
| **Flexibility** | Fixed DAG of operations | Dynamic planning at runtime |
| **Reliability** | Highly predictable | Probabilistic, needs guardrails |
| **Complexity** | Simple, multi-step tasks | Open-ended, novel situations |
| **Best for** | Known processes, high-stakes | Exploration, adaptation, tool-use |
| **Example** | Document processing pipeline | Customer support ticket resolver |

**Rule of thumb:** Start with a workflow. Graduate to an agent only when the problem requires dynamic decision-making that can't be pre-programmed.

---

## 2. CORE AGENT ARCHITECTURES

### 2.1 ReAct (Reasoning + Acting)

The most fundamental agent pattern. The LLM iterates through a loop of **Thought → Action → Observation**.

```
Loop:
  1. Thought: "I need to look up the user's account to check their subscription"
  2. Action: call_tool("query_database", {sql: "SELECT * FROM users WHERE id=123"})
  3. Observation: "User has 'basic' subscription, expires 2026-08-01"
  4. Thought: "The user's subscription is basic. I should offer an upgrade."
  5. Action: call_tool("send_message", {user_id: 123, message: "..."})
```

**When to use:** Interactive problem-solving, debugging, customer support — any scenario where the agent needs to adapt based on intermediate results.

**Key consideration:** The agent can loop indefinitely if not bounded. Always set `max_steps`.

### 2.2 Plan-and-Execute

The agent generates a complete plan **first**, then executes it step by step.

```
Phase 1 — Plan:
  "To analyze this sales report, I will:
    1. Read the CSV file
    2. Compute monthly aggregates
    3. Identify top-5 products
    4. Generate a summary chart
    5. Email the report"

Phase 2 — Execute:
  Step 1: read_file("sales_report.csv") → data
  Step 2: call_tool("aggregate", {data, group: "month"})
  Step 3: call_tool("top_n", {data, n: 5, metric: "revenue"})
  ...
```

**When to use:** Complex, multi-step tasks that benefit from upfront planning (data analysis, research reports, code generation).

**Advantage:** More predictable and observable than ReAct. Easier to audit and resume after failures.

**Disadvantage:** The plan may be wrong from the start, wasting time on a bad plan.

### 2.3 Orchestrator-Worker

A central **orchestrator** agent decomposes tasks and delegates to specialized **worker** agents.

```
                  ┌──────────────────┐
                  │   Orchestrator    │
                  │  (Task Decomposer)│
                  └──┬────┬────┬─────┘
                     │    │    │
          ┌──────────┘    │    └──────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Worker A │   │ Worker B │   │ Worker C │
    │ (Search) │   │ (Analyze)│   │ (Write)  │
    └──────────┘   └──────────┘   └──────────┘
```

**When to use:** Complex tasks requiring multiple distinct capabilities (research + analysis + writing). Common in enterprise automation.

**Key challenge:** Workers can run in parallel or sequentially, and the orchestrator must merge results coherently.

### 2.4 Reflection (Critic-Refiner)

A two-agent loop where a **producer** generates output and a **critic** evaluates it against quality rubrics.

```
Loop:
  1. Producer generates draft answer
  2. Critic evaluates: "Missing citations. Fact 2 is unsupported."
  3. Producer revises based on feedback
  4. Repeat until critic passes or max iterations reached
```

**When to use:** Code generation, writing, any task where quality iteration matters more than speed.

**Trade-off:** 2-3x latency cost for significant quality improvement.

### 2.5 Memory-Augmented Agent

An agent with explicit **memory systems** — short-term (conversation), working (task context), and long-term (learned facts, user preferences).

```
┌──────────────────────────────────────────┐
│              AGENT MEMORY                 │
│                                            │
│  ┌──────────────┐  ┌────────────────────┐ │
│  │ Short-term    │  │ Working Memory     │ │
│  │ (last N turns)│  │ (current task ctx) │ │
│  └──────────────┘  └────────────────────┘ │
│  ┌──────────────┐  ┌────────────────────┐ │
│  │ Long-term     │  │ Episodic Memory    │ │
│  │ (facts, prefs)│  │ (past resolutions) │ │
│  └──────────────┘  └────────────────────┘ │
└──────────────────────────────────────────┘
```

---

## 3. TOOL-USE PATTERNS

### 3.1 Tool Registry & Schema

Every tool an agent can call must be registered with a strict schema:

```python
@dataclass
class ToolSpec:
    name: str                      # Unique, descriptive name
    description: str               # What the tool does (for LLM consumption)
    input_schema: dict             # JSON Schema for parameters
    output_schema: Optional[dict]  # Expected output shape
    requires_approval: bool = False  # Human-in-the-loop?
    timeout_seconds: int = 30
    rate_limit_rps: float = 10     # Max calls per second
```

### 3.2 Tool Categories

| Category | Examples | Security Model |
|----------|----------|---------------|
| **Read-only** | `query_database`, `read_file`, `search_web` | Read-only credentials, output filtering |
| **Write** | `send_email`, `create_ticket`, `update_record` | Human approval for high-impact writes |
| **Idempotent** | `set_status`, `cache_clear` | Safe to retry, no side effects |
| **Destructive** | `delete_record`, `drop_table` | Always requires human approval |

### 3.3 Tool Call Lifecycle

```
LLM decides to call tool
    │
    ▼
1. Schema Validation — Reject if params don't match schema
    │
    ▼
2. Authorization — Check RBAC permissions
    │
    ▼
3. Rate Limit — Check per-client rate limits
    │
    ▼
4. Approval — If requires_approval, pause for human OK
    │
    ▼
5. Execute — Run with timeout
    │
    ▼
6. Observe — Return result to LLM (or error)
    │
    ▼
7. Audit — Log full trace: prompt, params, result, latency
```

---

## 4. MEMORY SYSTEMS

### 4.1 Short-Term Memory (Conversation Context)

The LLM's context window. Managed via:

- **Sliding window:** Keep last N turns, drop oldest
- **Summary compression:** Summarize early turns into a single bullet
- **Token budget:** Reserve 70% for tools/results, 30% for conversation

### 4.2 Working Memory (Task Context)

Temporary state for the current task:

```python
@dataclass
class WorkingMemory:
    current_goal: str
    completed_steps: List[str]
    remaining_steps: List[str]
    intermediate_results: Dict[str, Any]
    errors_encountered: List[str]
```

### 4.3 Long-Term Memory (Persistent Facts)

Stored externally and retrieved on demand:

```python
class LongTermMemory:
    def __init__(self):
        self.store = {}  # Could be Redis, PostgreSQL, or vector DB
    
    def remember(self, key: str, value: Any, ttl: Optional[int] = None):
        """Store a fact with optional TTL."""
        self.store[key] = {
            "value": value,
            "expires": time.time() + ttl if ttl else None
        }
    
    def recall(self, key: str) -> Optional[Any]:
        """Retrieve a stored fact if not expired."""
        entry = self.store.get(key)
        if entry and (entry["expires"] is None or time.time() < entry["expires"]):
            return entry["value"]
        return None
    
    def search_by_similarity(self, query: str, top_k: int = 5) -> List[Dict]:
        """Semantic search over stored facts (uses embeddings)."""
        # Encode query, find nearest neighbors in vector space
        pass
```

### 4.4 Episodic Memory (Past Resolutions)

Store how similar problems were solved before:

```python
episodic_memory.store(
    problem="Database connection timeout",
    resolution="Applied exponential backoff with jitter",
    outcome="successful",
    tags=["database", "networking", "retry"]
)
```

---

## 5. MULTI-AGENT PATTERNS

### 5.1 Delegation Pattern

One agent delegates sub-tasks to specialized agents:

```
Orchestrator: "Research the latest AI chip benchmarks"
    ├── Worker(Search): "Find Q1 2026 GPU benchmarks"
    ├── Worker(Analyze): "Compare performance/Watt across vendors"
    └── Worker(Write): "Generate executive summary"
```

### 5.2 Debate Pattern

Two agents debate a question, improving answer quality:

```
Agent A (Pro): "Use PostgreSQL — ACID compliance, mature tooling, 20 years of optimization"
Agent B (Con): "Use MongoDB — schema flexibility, horizontal scaling, better for document data"
Synthesizer: "For this use case (heterogeneous document data with infrequent joins),
              MongoDB is the better choice due to schema flexibility, but PostgreSQL
              would be preferred if query complexity increases."
```

### 5.3 Hierarchical Pattern

```
                    ┌──────────────────┐
                    │   CEO Agent       │
                    │ (High-level goal) │
                    └───────┬──────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ Product    │ │ Engineering│ │  Ops       │
     │ Manager    │ │  Lead      │ │  Lead      │
     └──────┬─────┘ └──────┬─────┘ └──────┬─────┘
            │              │              │
       ┌────┴────┐   ┌────┴────┐    ┌────┴────┐
       │ PM-1    │   │ Dev-1   │    │ Infra-1 │
       │ PM-2    │   │ Dev-2   │    │ Infra-2 │
       └─────────┘   └─────────┘    └─────────┘
```

---

## 6. AGENT FRAMEWORKS COMPARISON (2026)

| Framework | Pattern | Best For | Protocol Support |
|-----------|---------|----------|-----------------|
| **LangGraph** | Graph-based state machine | Regulated production systems | MCP, custom |
| **CrewAI** | Role-based orchestration | Fast prototyping | MCP |
| **OpenAI Agents SDK** | Built-in tool use | GPT-native workflows | OpenAI tools |
| **Pydantic AI** | Type-safe agents | Engineering rigor, reliability | MCP, custom |
| **Google ADK** | Hierarchical agents | GCP-native, multimodal | MCP |

---

## 7. PRODUCTION READINESS CHECKLIST

| Requirement | Check | Implementation |
|------------|-------|---------------|
| **Max step limit** | ✅ | `max_iterations=25` prevents infinite loops |
| **Human-in-the-loop** | ✅ | Approval for high-impact actions |
| **Rate limiting** | ✅ | Per-client token bucket |
| **Observability** | ✅ | Full trace logging of every decision |
| **Error recovery** | ✅ | Retry with backoff, circuit breaker |
| **Token budgeting** | ✅ | Context window management |
| **Testing harness** | ✅ | Automated evaluation of agent outputs |

---

> **Next:** [Agent Interview Questions](02_AGENT_INTERVIEW_QUESTIONS.md) → Staff/Principal-level Q&A
