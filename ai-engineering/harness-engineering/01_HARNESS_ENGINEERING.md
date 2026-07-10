# 🔧 Harness Engineering — Production Scaffolding for AI Systems

> **Target:** Staff/Principal Engineer | **Focus:** Designing the infrastructure layer that makes AI models safe, observable, and controllable in production

---

## 1. WHAT IS A HARNESS?

In AI engineering, the **harness** is everything surrounding the model that enables it to operate reliably in production. The industry shorthand:

> **Agent = Model + Harness**

A model without a harness can chat, but cannot reliably act, access external data, or follow organizational constraints. The harness provides:

| Layer | Function | What It Enables |
|-------|----------|----------------|
| **Execution Infrastructure** | Sandbox for running code, calling APIs, querying databases | Safe tool execution |
| **Guardrails** | Safety rules, permissions, human-in-the-loop | Controlled behavior |
| **Verification** | Tests, validators, LLM-as-a-judge | Self-correction |
| **Memory & Context** | RAG pipelines, state management, context optimization | Long-running tasks |
| **Observability** | Tracing, logging, evaluation metrics | Auditability |

```
┌───────────────────────────────────────────────────────────┐
│                       AGENT HARNESS                         │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌─────────┐ │
│  │ FEEDFORWARD  │  │ EXECUTION  │  │ FEEDBACK   │  │ STATE   │ │
│  │ (Guides)   │  │ (Sandbox) │  │ (Sensors) │  │ (Memory)│ │
│  │───────────│  │───────────│  │───────────│  │─────────│ │
│  │ System     │  │ Code exec  │  │ Unit tests│  │ Short-  │ │
│  │ prompts    │  │ API calls  │  │ Output    │  │ term    │ │
│  │ Skills     │  │ DB queries │  │ validation│  │ Working │ │
│  │ Plans      │  │ File I/O   │  │ LLM judge │  │ Long-   │ │
│  │ Rubrics    │  │            │  │ Diff scan │  │ term    │ │
│  └───────────┘  └───────────┘  └───────────┘  └─────────┘ │
│                                                             │
└───────────────────────────────────────────────────────────┘
```

### 1.1 Why Harness Engineering Now?

Raw model intelligence is converging across providers. The **new differentiator** is harness quality:

| Era | Focus | Differentiator |
|-----|-------|---------------|
| **2022-2023** | Model capability | "Which model is smarter?" |
| **2024-2025** | Prompt engineering | "Who writes better prompts?" |
| **2026+** | Harness engineering | "Who builds better scaffolding?" |

Organizations winning with AI are not those with the best models — they're those with the best harnesses.

---

## 2. TYPES OF HARNESSES

### 2.1 Evaluation Harnesses (Testing/Benchmarking)

Focused on **measurement**. An evaluation harness runs a model against standardized tasks and calculates performance metrics.

```
┌──────────────────────────────────────────────────┐
│                 EVALUATION HARNESS                 │
│                                                    │
│  Test Dataset ──→ Model ──→ Scorer ──→ Report     │
│                                                    │
│  Dimensions:                                       │
│  · Accuracy / Correctness                          │
│  · Latency (p50, p95, p99)                         │
│  · Cost per inference                              │
│  · Safety / Toxicity                               │
│  · Adversarial robustness                          │
│                                                    │
└──────────────────────────────────────────────────┘
```

**Key Tools (2026):**

| Tool | Focus | Integration |
|------|-------|-------------|
| **DeepEval** | LLM evaluation framework | Pytest-style, CI-friendly |
| **MLflow Evaluation** | Experiment tracking + eval | MLflow ecosystem |
| **lm-evaluation-harness** | Standardized benchmarks | Hugging Face models |
| **LangSmith** | Agent tracing + evaluation | LangChain ecosystem |
| **Arize AI** | Production monitoring | Real-time drift detection |

### 2.2 Agent Harnesses (Operational Scaffolding)

Focused on **reliability and autonomy**. The production infrastructure that guides agent behavior.

```
┌─────────────────────────────────────────────────────┐
│                  AGENT HARNESS                        │
│                                                       │
│  1. Feedforward Controls                              │
│     ├── System prompt (identity, constraints)         │
│     ├── Skills (reusable instruction files)           │
│     └── Plan (pre-committed execution path)           │
│                                                       │
│  2. Execution Environment                             │
│     ├── Sandboxed container / subprocess              │
│     ├── Scoped credentials (least privilege)          │
│     └── Resource limits (memory, time, tokens)        │
│                                                       │
│  3. Feedback Sensors                                  │
│     ├── Runtime validators (output schema checks)     │
│     ├── Test suite execution                          │
│     └── LLM-as-a-judge evaluation                     │
│                                                       │
│  4. Safety Interlocks                                 │
│     ├── Human-in-the-loop gates                       │
│     ├── Rate limiters / circuit breakers              │
│     └── Kill switches                                 │
│                                                       │
└─────────────────────────────────────────────────────┘
```

---

## 3. HARNESS COMPONENTS — DEEP DIVE

### 3.1 Guardrails

Guardrails are the **safety boundaries** around agent behavior. They operate at multiple levels:

| Level | Guardrail | Implementation |
|-------|-----------|---------------|
| **Input** | Prompt injection detection | Regex patterns, LLM classifier, perplexity check |
| **Input** | Topic/scope filtering | Embedding similarity to allowed topics |
| **Output** | PII/secret redaction | Regex + ML-based PII detection (presidio) |
| **Output** | Toxicity filtering | Perspective API, custom classifier |
| **Tool** | Parameter validation | JSON Schema validation |
| **Tool** | Authorization | RBAC per-tool, per-resource |
| **Execution** | Rate limiting | Token bucket, sliding window |
| **Execution** | Budget control | Token/monetary budget per session |

```python
class GuardrailPipeline:
    """Chain of responsibility for guardrail checks."""

    def __init__(self):
        self.input_guardrails: List[Guardrail] = []
        self.output_guardrails: List[Guardrail] = []
        self.tool_guardrails: List[Guardrail] = []

    def check_input(self, user_input: str) -> GuardrailResult:
        for guardrail in self.input_guardrails:
            result = guardrail.check(user_input)
            if not result.passed:
                return result  # Block on first failure
        return GuardrailResult(passed=True)

    def check_output(self, model_output: str) -> GuardrailResult:
        for guardrail in self.output_guardrails:
            result = guardrail.check(model_output)
            if not result.passed:
                return result
        return GuardrailResult(passed=True)

    def check_tool_call(self, tool: str, params: dict) -> GuardrailResult:
        for guardrail in self.tool_guardrails:
            result = guardrail.check(tool, params)
            if not result.passed:
                return result
        return GuardrailResult(passed=True)
```

### 3.2 Execution Sandbox

Agents need safe environments to execute code. The sandbox provides **isolation** and **resource control**.

```python
@dataclass
class SandboxConfig:
    """Configuration for an agent execution sandbox."""
    container_image: str = "python:3.14-slim"
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0      # Cores
    timeout_seconds: int = 30
    network_enabled: bool = False
    allowed_domains: List[str] = field(default_factory=list)
    read_only_paths: List[str] = field(default_factory=list)
    write_paths: List[str] = field(default_factory=lambda: ["/tmp"])
    env_vars: Dict[str, str] = field(default_factory=dict)
```

**Sandbox strategies (by isolation level):**

| Strategy | Isolation | Latency | Use Case |
|----------|-----------|---------|----------|
| **Subprocess** | Process-level | Low | Script execution, data analysis |
| **Docker container** | OS-level | Medium | Multi-language, sensitive tasks |
| **Firecracker microVM** | Hardware-level | High | Untrusted code, multi-tenant |
| **WebAssembly** | Runtime-level | Very low | Plugin execution, browser-side |

### 3.3 Verification Layer

The verification layer **closes the loop** by checking agent outputs against rubrics.

```python
class VerificationPipeline:
    """Verifies agent outputs before returning to user."""

    def verify(self, task: Task, output: AgentOutput) -> VerificationResult:
        results = []

        # 1. Schema validation
        if task.output_schema:
            results.append(self._validate_schema(output, task.output_schema))

        # 2. Unit tests (for code generation)
        if task.has_tests:
            results.append(self._run_unit_tests(output.code))

        # 3. Factual consistency (RAG-based)
        if task.requires_citations:
            results.append(self._check_citations(output, task.documents))

        # 4. LLM-as-a-judge
        if task.evaluation_rubric:
            results.append(self._llm_evaluate(output, task.evaluation_rubric))

        return VerificationResult(
            passed=all(r.passed for r in results),
            details=results
        )
```

**Verification patterns:**

| Pattern | Mechanism | Best For |
|---------|-----------|----------|
| **Deterministic check** | Regex, schema validation, diff | Format compliance |
| **Runtime testing** | pytest, unit test execution | Code generation |
| **LLM-as-a-judge** | Secondary LLM evaluates output | Quality assessment |
| **Human review** | Manual approval gate | High-stakes decisions |
| **A/B comparison** | Side-by-side with baseline | Regression detection |

### 3.4 Context & Memory Management

The harness manages what the agent knows and remembers:

```python
class HarnessMemory:
    """Multi-tier memory managed by the harness."""

    def __init__(self):
        self.working: WorkingMemory = WorkingMemory()
        self.conversation: SlidingWindow = SlidingWindow(max_tokens=32000)
        self.long_term: VectorStore = VectorStore(collection="agent_facts")

    def build_prompt_context(self, max_tokens: int = 64000) -> str:
        """Assemble context from all memory tiers."""
        context = []

        # Working memory (current task state)
        context.append(self.working.summarize())

        # Relevant long-term facts (RAG retrieval)
        query = self.working.current_goal
        facts = self.long_term.similarity_search(query, k=5)
        context.extend(f.text for f in facts)

        # Recent conversation (sliding window)
        context.append(self.conversation.get_window())

        return self._truncate_to_budget("\n".join(context), max_tokens)
```

---

## 4. HARNESS ENGINEERING BEST PRACTICES

### 4.1 Defense in Depth

Never rely on a single guardrail. Layer them:

```
Input Layer     →   Model Layer     →   Tool Layer     →   Output Layer
──────────────────────────────────────────────────────────────────────
Prompt          →   System prompt   →   Parameter      →   PII redaction
injection       +   constraints     +   validation     +   Toxicity check
detection       +   Topic routing   +   Auth check     +   Factual check
                +   Budget tracking +   Rate limit     +   Schema validation
```

### 4.2 Least Privilege for Tools

Every tool should have the minimum permissions needed:

```python
TOOL_REGISTRY = {
    "query_read_replica": ToolSpec(
        requires_approval=False,
        credentials="readonly_db_user",
        allowed_databases=["analytics", "reporting"],
        rate_limit_rps=100,
    ),
    "execute_sql_write": ToolSpec(
        requires_approval=True,
        credentials="write_user_with_restrictions",
        allowed_tables=["staging.*"],
        rate_limit_rps=10,
    ),
}
```

### 4.3 Harness as a Cybernetic System

The harness operates as a **control loop** with feedforward guides and feedback sensors:

```
Feedforward (Before Action):
  System prompt ──→ Skills ──→ Plan ──→ Action generation
                      │
                      ▼
Feedback (After Action):
  Action result ──→ Verification ──→ Error analysis ──→ Correction
```

| Element | Harness Component | Example |
|---------|------------------|---------|
| **Sensor** | Verification layer | Unit test results |
| **Comparator** | Rubric evaluation | "Does output match expected format?" |
| **Effector** | Correction mechanism | Retry with error context |
| **Reference** | Goal/task spec | "Generate a Python function that..." |

### 4.4 Cost & Resource Governors

Prevent runaway agents with hard limits:

```python
@dataclass
class HarnessBudget:
    """Resource budget enforced by the harness."""
    max_tokens_per_session: int = 100_000
    max_tool_calls: int = 50
    max_wall_time_seconds: int = 300
    max_cost_usd: float = 0.50
    max_iterations: int = 25
```

---

## 5. HARNESS ENGINEERING INTERVIEW QUESTIONS

| Question | Key Topics | Evaluation Rubric |
|----------|-----------|-------------------|
| "How would you design a safety harness for an autonomous coding agent?" | Sandboxing, guardrails, least privilege, human-in-the-loop | Candidate should propose defense-in-depth with multiple verification layers |
| "How do you evaluate whether your AI agent is production-ready?" | Evaluation harness, benchmark datasets, canary deployment, regression testing | Should mention both offline eval (benchmarks) and online eval (shadow mode) |
| "Design a verification system for a code-generation agent." | Unit test execution, static analysis, diff review, sandbox environment | Should discuss test generation, flakiness handling, and false positive management |
| "How would you prevent an agent from exceeding its budget?" | Token budgeting, rate limiting, circuit breaker, cost tracking | Should cover both hard caps (kill switch) and soft caps (warnings) |
| "Compare evaluation harness vs agent harness." | Purpose, lifecycle, metrics, integration | Should distinguish measurement (eval) from guidance/control (agent harness) |

---

## 6. PRODUCTION HARNESS CHECKLIST

| Component | Implementation | Status |
|-----------|---------------|--------|
| **Input guardrails** | Prompt injection detection, topic filter | 📋 |
| **Output guardrails** | PII redaction, toxicity filter, schema validation | 📋 |
| **Execution sandbox** | Docker/Firecracker isolation, resource limits | 📋 |
| **Verification layer** | Tests, LLM-as-a-judge, diff validation | 📋 |
| **Human-in-the-loop** | Approval gates for high-impact actions | 📋 |
| **Observability** | Full trace logging, metrics, audit trail | 📋 |
| **Cost governance** | Token/monetary budget, rate limits | 📋 |
| **Memory management** | Sliding window, RAG, working memory | 📋 |
| **Error recovery** | Retry with backoff, circuit breaker, degradation | 📋 |
| **Testing harness** | Automated evaluation against benchmark suite | 📋 |

---

> **Next:** [Loop Engineering](02_LOOP_ENGINEERING.md) → Designing autonomous agentic loops
