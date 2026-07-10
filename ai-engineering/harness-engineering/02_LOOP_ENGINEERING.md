# 🔄 Loop Engineering — Designing Autonomous Agentic Loops

> **Target:** Staff/Principal Engineer | **Focus:** Production-grade agent loops — from ReAct primitives to enterprise orchestration

---

## 1. WHAT IS LOOP ENGINEERING?

**Loop Engineering** is the discipline of designing autonomous, self-sustaining AI systems that perform iterative work. It shifts the AI engineer's role:

> From "writing the perfect prompt" → To "writing the system that prompts the AI"

An agentic loop gives an AI agent a goal, tools, and an environment — then lets it **reason, act, observe, and iterate** until it reaches an exit condition.

```
┌────────────────────────────────────────────────────────────┐
│                     AGENTIC LOOP                             │
│                                                              │
│         ┌──────────────┐                                    │
│         │   PERCEIVE    │                                    │
│         │  (Input/Goal) │                                    │
│         └──────┬───────┘                                    │
│                │                                             │
│                ▼                                             │
│         ┌──────────────┐     ┌─────────────────┐           │
│         │    REASON     │────→│   FEEDBACK INT   │           │
│         │  (LLM Think)  │     │ (Self-reflection)│           │
│         └──────┬───────┘     └─────────────────┘           │
│                │                                             │
│                ▼                                             │
│         ┌──────────────┐     ┌─────────────────┐           │
│         │     PLAN      │────→│   SUB-AGENTS    │           │
│         │  (Decompose)  │     │  (Delegation)   │           │
│         └──────┬───────┘     └─────────────────┘           │
│                │                                             │
│                ▼                                             │
│         ┌──────────────┐                                    │
│         │     ACT       │──────┐                             │
│         │  (Tool Use)   │      │                             │
│         └──────┬───────┘      │                             │
│                │              │                             │
│                ▼              │                             │
│         ┌──────────────┐      │                             │
│         │   OBSERVE    │◄─────┘                             │
│         │  (Result)    │                                     │
│         └──────┬───────┘                                     │
│                │                                             │
│         ┌──────┴──────┐                                     │
│         │             │                                      │
│    ┌────▼────┐  ┌────▼────┐                                 │
│    │ITERATE  │  │  EXIT   │                                 │
│    │(Loop)   │  │(Return) │                                 │
│    └─────────┘  └─────────┘                                 │
└────────────────────────────────────────────────────────────┘
```

---

## 2. LOOP PRIMITIVES

A production loop consists of six core primitives:

| Primitive | Function | Implementation |
|-----------|----------|---------------|
| **Automations** | Trigger loop execution | Cron, event hooks, webhook receivers |
| **Workspace** | Isolated environment per run | Git worktrees, temp directories, containers |
| **Skills** | Codified knowledge for the agent | `SKILL.md` files, instruction templates |
| **Connectors** | External system access | MCP servers, REST APIs, SDKs |
| **Sub-agents** | Delegated work units | Orchestrator-worker pattern |
| **External State** | Durable progress tracking | Markdown files, databases, DAG state |

```python
@dataclass
class LoopConfig:
    """Configuration for an agentic loop."""
    max_iterations: int = 25
    exit_condition: str = "task_complete"    # Or "max_iterations", "error"
    workspace_type: str = "temp_directory"    # Or "git_worktree", "container"
    skills_path: str = ".agents/skills/"
    connectors: List[MCPConfig] = field(default_factory=list)
    external_state_path: str = ".loop_state.json"
    timeout_minutes: int = 60
```

---

## 3. THE CORE LOOP PATTERNS

### 3.1 ReAct Loop (Reason + Act)

The foundational loop pattern. The LLM iterates: **Thought → Action → Observation**.

```
Iteration 1:
  Thought:  "I need to find the user's account to check their subscription."
  Action:   query_database("SELECT * FROM users WHERE email = 'user@co.com'")
  Observation: "User found: id=123, plan='basic', expires=2026-08-01"

Iteration 2:
  Thought:  "The user's subscription is 'basic'. I should offer an upgrade."
  Action:   send_message(123, "Your plan is basic. Upgrade to pro!")
  Observation: "Message sent successfully."

Iteration 3:
  Exit: Task complete — user contacted with upgrade offer.
```

```python
async def react_loop(goal: str, tools: ToolRegistry, max_steps: int = 25):
    """Basic ReAct loop implementation."""
    messages = [{"role": "user", "content": goal}]

    for step in range(max_steps):
        response = await llm.generate(messages)

        if response.has_tool_call:
            # Execute tool
            result = await tools.execute(
                response.tool_call.name,
                response.tool_call.params
            )
            messages.append({"role": "assistant", "content": str(response)})
            messages.append({"role": "tool", "content": str(result)})
        elif response.has_final_answer:
            return response.content
        else:
            # Continue reasoning
            messages.append({"role": "assistant", "content": str(response)})

    raise LoopExceededError(f"Exceeded {max_steps} iterations")
```

**When to use:** Interactive problem-solving, debugging, customer support — any scenario where the agent must adapt based on intermediate results.

**Key risk:** Can loop indefinitely. Always set `max_iterations` and a circuit breaker.

### 3.2 Plan-and-Execute Loop

The agent generates a complete plan **first**, then executes it step by step.

```
Phase 1 — Planning:
  "To analyze this sales report, I will:
    1. Read the CSV file
    2. Compute monthly aggregates
    3. Identify top-5 products by revenue
    4. Generate a summary chart
    5. Email the report"

Phase 2 — Execution:
  Step 1: read_file("sales_report.csv") → ✅ data loaded
  Step 2: aggregate(data, group="month") → ✅ monthly totals
  Step 3: top_n(data, n=5, metric="revenue") → ✅ top products
  Step 4: generate_chart(data) → ✅ chart saved
  Step 5: send_email("report@co.com", attachment="chart.png") → ✅ sent
```

```python
async def plan_and_execute(goal: str, tools: ToolRegistry):
    """Plan-and-Execute loop."""
    # Phase 1: Generate plan
    plan = await llm.generate_plan(goal)
    log.info(f"Plan generated: {len(plan.steps)} steps")

    # Phase 2: Execute each step
    results = []
    for step in plan.steps:
        try:
            result = await execute_step(step, tools)
            results.append(StepResult(step=step, status="success", data=result))
        except Exception as e:
            # Decide: retry, re-plan, or fail
            if step.retryable and retry_count < step.max_retries:
                result = await retry_step(step, tools)
            else:
                plan = await llm.replan(goal, plan, results, str(e))
                if plan.failed:
                    raise PlanExecutionError(f"Plan failed: {e}")

    return results
```

**When to use:** Complex, multi-step tasks where upfront planning provides clarity (data analysis, research reports, code generation).

**Advantage:** More predictable and observable than ReAct. Easier to audit, resume after failures, and parallelize independent steps.

**Disadvantage:** The plan may be wrong from the start. Mitigate by using a **re-planning** fallback.

### 3.3 Critic-Refiner Loop (Reflection)

A two-agent loop where a **producer** generates output and a **critic** evaluates it.

```
Loop:
  1. Producer generates draft answer
  2. Critic evaluates: "Missing citations. Fact 2 is unsupported."
  3. Producer revises based on feedback
  4. Repeat until critic passes or max iterations reached
```

```python
async def critic_refiner_loop(
    task: str,
    producer: LLMClient,
    critic: LLMClient,
    rubric: EvaluationRubric,
    max_iterations: int = 5
):
    """Reflection loop with separate critic agent."""
    draft = await producer.generate(task)

    for iteration in range(max_iterations):
        evaluation = await critic.evaluate(draft, rubric)

        if evaluation.passed:
            log.info(f"Passed after {iteration + 1} iterations")
            return draft

        feedback = evaluation.feedback
        log.info(f"Iteration {iteration + 1}: {len(feedback.issues)} issues found")
        draft = await producer.revise(draft, feedback)

    return draft  # Best effort after max iterations
```

**When to use:** Code generation, writing, any task where quality iteration matters more than speed.

**Trade-off:** 2-3x latency cost for significant quality improvement (typically 20-40% error reduction).

### 3.4 Orchestrator-Worker Loop

A central **orchestrator** decomposes tasks and delegates to specialized **worker** agents.

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
        │               │               │
        └───────────────┼───────────────┘
                        ▼
                ┌──────────────────┐
                │   Synthesizer    │
                │  (Merge Results) │
                └──────────────────┘
```

```python
async def orchestrator_loop(goal: str, workers: Dict[str, Agent]):
    """Orchestrator-worker loop with result synthesis."""
    orchestrator = OrchestratorAgent()

    # 1. Decompose
    tasks = await orchestrator.decompose(goal)
    log.info(f"Decomposed into {len(tasks)} sub-tasks")

    # 2. Dispatch (parallel where possible)
    results = {}
    async with TaskGroup() as tg:
        for task in tasks:
            worker = workers[task.worker_type]
            tg.create_task(self._run_worker(worker, task, results))

    # 3. Synthesize
    final_output = await orchestrator.synthesize(goal, results)
    return final_output
```

**When to use:** Complex tasks requiring multiple distinct capabilities (research + analysis + writing). Common in enterprise automation and content generation.

---

## 4. LOOP SAFETY & TERMINATION

### 4.1 Exit Conditions

Every loop must have a verifiable exit condition:

| Condition | Trigger | Implementation |
|-----------|---------|---------------|
| **Task complete** | Agent declares completion | Check `final_answer` flag |
| **Max iterations** | Hard cap on steps | `max_iterations=25` |
| **Timeout** | Wall-clock limit | `timeout_seconds=300` |
| **Token budget** | Token consumption cap | `max_tokens_per_run=100000` |
| **Cost budget** | Monetary cost limit | `max_cost_usd=0.50` |
| **Error threshold** | Consecutive failures | `max_errors=3` |
| **Degradation** | Quality below threshold | Check verification score |

```python
class LoopTerminator:
    """Manages loop exit conditions."""

    def __init__(self, config: LoopConfig):
        self.max_iterations = config.max_iterations
        self.timeout = config.timeout_minutes * 60
        self.start_time = time.monotonic()

    def should_terminate(self, state: LoopState) -> tuple[bool, str]:
        if state.task_complete:
            return True, "task_complete"

        if state.iteration >= self.max_iterations:
            return True, "max_iterations"

        if time.monotonic() - self.start_time > self.timeout:
            return True, "timeout"

        if state.token_count >= state.token_budget:
            return True, "token_budget_exceeded"

        if state.consecutive_errors >= 3:
            return True, "too_many_errors"

        return False, ""
```

### 4.2 Circuit Breaker Pattern

Prevent loops from wasting resources on failing operations:

```python
class LoopCircuitBreaker:
    """Circuit breaker for agentic loops."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"  # closed, open, half-open
        self.last_failure_time = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                return True  # Probe request
            return False
        # half-open: allow exactly one request
        return True
```

---

## 5. LOOP OBSERVABILITY

### 5.1 Tracing the Loop

Every iteration of the loop must be observable:

```python
@dataclass
class LoopSpan:
    """Trace span for a single loop iteration."""
    iteration: int
    phase: str              # perceive, reason, plan, act, observe
    llm_call_id: str
    tool_call: Optional[ToolCall]
    tool_result: Optional[Any]
    tokens_used: int
    latency_ms: float
    error: Optional[str]

@dataclass
class LoopTrace:
    """Complete trace of an agentic loop execution."""
    session_id: str
    goal: str
    spans: List[LoopSpan]
    total_tokens: int
    total_latency_ms: float
    total_cost_usd: float
    exit_reason: str
    final_output: Optional[str]
```

### 5.2 Key Metrics to Track

| Metric | What It Measures | Alert Threshold |
|--------|-----------------|----------------|
| **Loop iterations** | Steps to complete task | > 20 iterations |
| **Step latency** | Time per iteration | p95 > 30s |
| **Tool error rate** | Fraction of tool calls that fail | > 10% |
| **Cost per loop** | Total inference + tool cost | > $1.00/run |
| **Retry rate** | How often agents retry failed steps | > 20% |
| **Exit reason** | Distribution of termination causes | "timeout" > 5% |

---

## 6. PRODUCTION LOOP DESIGN PATTERNS

### 6.1 The "Comprehension Debt" Problem

> **"Just because an agent can ship code 10x faster doesn't mean the team understands the codebase 10x better."**

Loop engineering is not a replacement for human understanding. It is a way to **delegate mechanical iteration** while keeping the human in control of strategy.

**Mitigation strategies:**
- Require human review of architectural decisions
- Log and summarize every loop iteration for human review
- Use sub-agents for exploration, not final decisions

### 6.2 When to Loop (vs. When Not To)

| Loop-worthy | Not Loop-worthy |
|-------------|----------------|
| Multi-step research | Single-turn Q&A |
| Code generation with tests | Simple text transformation |
| Bug investigation | Known lookup queries |
| Report generation | Static template filling |
| Data pipeline debugging | Cron-triggered ETL |

**Rule of thumb:** Use loops when:
1. The task has **iterative refinement** (test → feedback → fix)
2. **Verification is deterministic** (pass/fail tests)
3. The **cost of looping amortizes** over task complexity

### 6.3 Enterprise Loop Runtime

For production loops at scale, you need an enterprise runtime:

```yaml
loop_runtime:
  orchestration:
    - State persistence: PostgreSQL or Redis
    - Concurrency control: Distributed locks (Redis Leases)
    - Queue management: SQS / RabbitMQ for task dispatch

  isolation:
    - Per-loop container: Docker with resource limits
    - Credential scoping: Short-lived tokens per session

  governance:
    - Approval gates: Human-in-the-loop for destructive actions
    - Audit trail: Immutable log of all loop iterations
    - Budget enforcement: Per-tenant token/cost budgets

  reliability:
    - Retry policy: Exponential backoff with jitter
    - Dead letter queue: Failed loops for manual review
    - Idempotency: Tool calls should be safe to retry
```

---

## 7. LOOP ENGINEERING INTERVIEW QUESTIONS

| Question | Key Topics | Evaluation Rubric |
|----------|-----------|-------------------|
| "Design an agentic loop for automated bug fixing." | ReAct + test verification, git integration, PR creation | Should discuss sandboxed execution, test suite, iteration limits, human review gate |
| "How would you prevent an agent from infinite looping?" | Max iterations, circuit breaker, timeout, budget, monotonic progress check | Must propose multiple exit conditions and a kill switch |
| "Compare ReAct vs Plan-and-Execute for a data analysis agent." | Determinism vs flexibility, observability, failure modes | Should match pattern to task characteristics (structured vs exploratory) |
| "Design a cost-effective loop for customer support ticket resolution." | Context management, escalation, token budgeting, cost tracking | Should discuss token budgets, FAQ lookup before LLM call, and human escalation |
| "How would you make a loop observable in production?" | Tracing, metrics, logging, audit trail, cost attribution | Must cover spans, metrics dashboard, cost per session, and alerting |

---

## 8. LOOP PERFORMANCE OPTIMIZATION

| Technique | Impact | Trade-off |
|-----------|--------|-----------|
| **Parallel sub-agents** | 2-5x speedup for decomposable tasks | Higher peak cost, result merging complexity |
| **Cached tool results** | 30-60% fewer redundant calls | Staleness risk for time-sensitive data |
| **Early exit heuristics** | 40% fewer iterations for simple tasks | May miss edge cases |
| **Token budget allocation** | Predictable costs | May truncate complex tasks |
| **Step compression** | 20-30% fewer iterations | Risk of skipping verification |

---

## 9. LOOP ENGINEERING CHECKLIST

| Requirement | Implementation | Status |
|------------|---------------|--------|
| **Exit conditions** | Task complete, max iterations, timeout, budget | 📋 |
| **Circuit breaker** | Failure threshold with recovery timeout | 📋 |
| **Observability** | Full span tracing, metrics dashboard | 📋 |
| **Isolation** | Per-loop workspace, scoped credentials | 📋 |
| **Error recovery** | Retry with backoff, re-planning, dead letter queue | 📋 |
| **Human-in-the-loop** | Approval gates for high-impact actions | 📋 |
| **Cost governance** | Per-loop budget, cost tracking, alerts | 📋 |
| **Idempotency** | Tool calls safe to retry | 📋 |
| **State persistence** | Durable loop state across restarts | 📋 |
| **Comprehension debt** | Human review loops, architectural summaries | 📋 |

---

> **Prev:** [Harness Engineering](01_HARNESS_ENGINEERING.md) | **Next:** Related → [Agent Fundamentals](../agents/01_AGENT_FUNDAMENTALS.md)
