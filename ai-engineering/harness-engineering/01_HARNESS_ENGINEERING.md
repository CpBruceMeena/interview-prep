# 🔧 Harness Engineering — Production Scaffolding for AI Systems

> **Target:** Staff/Principal Engineer | **Focus:** Designing the infrastructure layer that makes AI models safe, observable, and controllable in production

!!! tip "30-second answer"
    The **harness** is everything around the model weights: the system prompt and instruction files, the tool set, the sandbox the tools run in, permission checks, verification (tests, validators, judges), memory and context management, budgets, and tracing. You design it as a control system: **guides** steer the model before it acts, **sensors** check what it did afterwards. Prefer cheap deterministic checks (schemas, tests, linters) over expensive model-based ones, and treat anything the model reads from the outside world as untrusted input that can hijack it. The model is not your security boundary; the harness is.

---

## 1. WHAT IS A HARNESS?

In AI engineering, the **harness** is everything surrounding the model that enables it to operate reliably in production. The shorthand:

> **Agent = Model + Harness**

A model without a harness can chat, but cannot reliably act, access external data, or follow organizational constraints. The harness provides:

| Layer | Function | What It Enables |
|-------|----------|----------------|
| **Execution Infrastructure** | Sandbox for running code, calling APIs, querying databases | Safe tool execution |
| **Guardrails** | Safety rules, permissions, human-in-the-loop | Controlled behavior |
| **Verification** | Tests, validators, LLM-as-a-judge | Self-correction |
| **Memory & Context** | RAG pipelines, state management, context compaction | Long-running tasks |
| **Observability** | Tracing, logging, evaluation metrics | Auditability, debugging, cost attribution |

```
┌──────────────────────────────────────────────────────────────┐
│                        AGENT HARNESS                         │
│                                                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │ FEEDFORWARD │ │  EXECUTION  │ │  FEEDBACK   │ │  STATE  │ │
│  │  (Guides)   │ │  (Sandbox)  │ │  (Sensors)  │ │ (Memory)│ │
│  │─────────────│ │─────────────│ │─────────────│ │─────────│ │
│  │ System      │ │ Code exec   │ │ Unit tests  │ │ Context │ │
│  │ prompt      │ │ API calls   │ │ Linters     │ │ window  │ │
│  │ CLAUDE.md / │ │ DB queries  │ │ Schema      │ │ Progress│ │
│  │ AGENTS.md   │ │ File I/O    │ │ checks      │ │ files   │ │
│  │ Skills      │ │             │ │ LLM judge   │ │ Long-   │ │
│  │ Plans       │ │             │ │ Diff review │ │ term    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
└──────────────────────────────────────────────────────────────┘
```

The guides/sensors vocabulary comes from Birgitta Böckeler's 2026 harness-engineering article on martinfowler.com. She adds a second axis that is useful in interviews: each guide or sensor is either **computational** (deterministic, fast, cheap: a linter, a type checker, a test) or **inferential** (model-based, semantic, slower and costlier: an LLM reviewer). Use computational controls wherever they can express the rule, and spend inferential ones on what only judgement can catch.

### 1.1 Why Harness Engineering Now?

Two things changed. Models became good enough to run multi-step tasks with tools for long stretches, and several vendors now ship models of comparable capability. So the failures teams see in production are mostly harness failures: the agent had the wrong context, an unsafe tool, no way to check its work, or no budget limit.

| Era (rough framing) | Focus | Typical question |
|-----|-------|---------------|
| **2022-2023** | Model capability | "Which model is smarter?" |
| **2024-2025** | Prompt and context engineering | "What do we put in the context window?" |
| **2025-2026** | Harness engineering | "What tools, checks and limits surround the model?" |

These eras overlap; treat the table as a mental model, not history.

---

## 2. TYPES OF HARNESSES

### 2.1 Evaluation Harnesses (Testing/Benchmarking)

Focused on **measurement**. An evaluation harness runs a model or agent against a fixed set of tasks and computes metrics, so you can compare versions and catch regressions.

```
┌──────────────────────────────────────────────────┐
│                EVALUATION HARNESS                │
│                                                  │
│  Task set ──→ Agent/Model ──→ Grader ──→ Report  │
│                                                  │
│  Dimensions:                                     │
│  · Correctness / task success rate               │
│  · Latency (p50, p95, p99)                       │
│  · Cost per task (not per request)               │
│  · Safety / policy violations                    │
│  · Adversarial robustness (injection, jailbreak) │
└──────────────────────────────────────────────────┘
```

Points interviewers probe:

- **Non-determinism:** run each task several times and report a pass rate with variance, not a single pass/fail. For agents, distinguish "succeeds at least once in k tries" (pass@k) from "succeeds every time in k tries" (pass^k); the second is what users experience.
- **Grade the outcome, and sometimes the trajectory:** check the final state (tests pass, ticket closed) first; inspect the path (tool calls, wasted steps, unsafe actions) when diagnosing.
- **Environment noise:** flaky sandboxes, rate limits and timeouts can move agentic scores by several points. Fix the infrastructure before you trust small deltas.
- **Contamination:** public benchmarks may be in training data. Keep a private, task-representative set built from real traffic.

**Common tools (check current status before naming one in an interview):**

| Tool | Focus | Notes |
|------|-------|-------|
| **Inspect** (UK AI Security Institute) | Agent and model evals | Open source, sandboxed agent tasks |
| **promptfoo** | Prompt and app regression tests | CLI/CI-friendly, red-teaming |
| **DeepEval** | LLM eval framework | Pytest-style |
| **lm-evaluation-harness** (EleutherAI) | Standard academic benchmarks | Model-level, not app-level |
| **LangSmith, Braintrust, Arize Phoenix** | Tracing plus evals on production data | Online and offline evaluation |

### 2.2 Agent Harnesses (Operational Scaffolding)

Focused on **reliability and control**. The production infrastructure that guides and constrains agent behavior.

```
┌─────────────────────────────────────────────────────┐
│                   AGENT HARNESS                     │
│                                                     │
│  1. Feedforward Controls (guides)                   │
│     ├── System prompt (role, constraints)           │
│     ├── Repo instructions (CLAUDE.md, AGENTS.md)    │
│     ├── Skills (instructions loaded on demand)      │
│     └── Plan (pre-committed execution path)         │
│                                                     │
│  2. Execution Environment                           │
│     ├── Sandboxed container / microVM               │
│     ├── Scoped, short-lived credentials             │
│     └── Resource limits (CPU, memory, time, tokens) │
│                                                     │
│  3. Feedback Sensors                                │
│     ├── Schema validation of tool inputs/outputs    │
│     ├── Tests, type checks, linters                 │
│     └── LLM-as-a-judge / reviewer agent             │
│                                                     │
│  4. Safety Interlocks                               │
│     ├── Permission rules + human approval gates     │
│     ├── Rate limiters / circuit breakers            │
│     └── Budgets and kill switches                   │
└─────────────────────────────────────────────────────┘
```

Claude Code is a useful public example of an agent harness: its documentation describes permission rules (allow / ask / deny per tool), hooks that run your own scripts before and after tool calls, `CLAUDE.md` memory files, skills, subagents and an optional sandbox for the Bash tool. You can cite those documented features; don't claim knowledge of how they are implemented internally.

---

## 3. HARNESS COMPONENTS — DEEP DIVE

### 3.1 Guardrails

Guardrails are the **safety boundaries** around agent behavior. They operate at multiple levels:

| Level | Guardrail | Implementation |
|-------|-----------|---------------|
| **Input** | Injection / jailbreak screening | Classifier models (e.g. Llama Guard, Prompt Guard), heuristics. Reduces risk; never sufficient alone (see 3.5) |
| **Input** | Topic/scope filtering | Small classifier or embedding similarity to allowed topics |
| **Output** | PII/secret redaction | Pattern matching + NER-based detection (e.g. Microsoft Presidio), secret scanners |
| **Output** | Harmful-content filtering | Moderation classifier (provider moderation endpoint or self-hosted). Google's Perspective API is being shut down at the end of 2026, so don't design around it |
| **Tool** | Parameter validation | JSON Schema validation (strict tool schemas where the API supports them) |
| **Tool** | Authorization | Check the *end user's* permissions per tool and per resource, not just the agent's |
| **Execution** | Rate limiting | Token bucket, sliding window |
| **Execution** | Budget control | Token / dollar / step budget per session |

A minimal pipeline (sketch; `Guardrail` and `GuardrailResult` are your own types):

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""


class Guardrail(Protocol):
    def check(self, *args) -> GuardrailResult: ...


@dataclass
class GuardrailPipeline:
    """Run checks in order; block on the first failure."""
    input_guardrails: list[Guardrail] = field(default_factory=list)
    output_guardrails: list[Guardrail] = field(default_factory=list)
    tool_guardrails: list[Guardrail] = field(default_factory=list)

    @staticmethod
    def _run(guardrails: list[Guardrail], *args) -> GuardrailResult:
        for g in guardrails:
            result = g.check(*args)
            if not result.passed:
                return result
        return GuardrailResult(passed=True)

    def check_input(self, user_input: str) -> GuardrailResult:
        return self._run(self.input_guardrails, user_input)

    def check_output(self, model_output: str) -> GuardrailResult:
        return self._run(self.output_guardrails, model_output)

    def check_tool_call(self, tool: str, params: dict) -> GuardrailResult:
        return self._run(self.tool_guardrails, tool, params)
```

Order the checks cheapest first, and decide per guardrail whether a failure should **block**, **redact and continue**, or **escalate to a human**. Blocking everything produces an agent nobody uses; log every decision so you can tune false positives.

### 3.2 Execution Sandbox

Agents that run code or shell commands need **isolation** (what can this process touch?) and **resource control** (how much can it consume?).

```python
from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    """Configuration for an agent execution sandbox."""
    container_image: str = "python:3.14-slim"   # pin a digest in production
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0                      # cores
    timeout_seconds: int = 30
    network_enabled: bool = False               # default deny
    allowed_domains: list[str] = field(default_factory=list)  # egress allowlist via proxy
    read_only_paths: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=lambda: ["/workspace", "/tmp"])
    env_vars: dict[str, str] = field(default_factory=dict)    # no long-lived secrets
```

**Sandbox strategies (weakest to strongest isolation):**

| Strategy | Isolation boundary | Start-up cost | Use case |
|----------|-----------|---------|----------|
| **Subprocess + OS sandbox** (seccomp, Landlock, macOS Seatbelt, bubblewrap) | Process with restricted syscalls and filesystem | Very low | Local coding agents on a developer's machine |
| **WebAssembly** | Language runtime; only the capabilities you pass in | Very low | Plugins, small pure computations |
| **Container** (Docker, containerd) | Linux namespaces and cgroups, **shared host kernel** | Low (sub-second to seconds) | Trusted or semi-trusted code, single-tenant |
| **gVisor** | User-space kernel intercepting syscalls | Low to medium | Untrusted code where you want container ergonomics |
| **microVM** (Firecracker, Kata Containers) | Hardware virtualization, separate guest kernel | Low to medium (Firecracker boots in well under a second) | Untrusted code, multi-tenant platforms |

The key interview point: a plain container shares the host kernel, so a kernel exploit escapes it. For multi-tenant execution of model-written code, use gVisor or a microVM. Also restrict **network egress**: without it, a hijacked agent can exfiltrate whatever it can read.

### 3.3 Verification Layer

The verification layer **closes the loop** by checking agent outputs before they reach the user or a production system.

```python
class VerificationPipeline:
    """Verifies agent outputs before returning to the user (sketch)."""

    def verify(self, task: "Task", output: "AgentOutput") -> "VerificationResult":
        results = []

        # 1. Deterministic, cheap checks first
        if task.output_schema:
            results.append(self._validate_schema(output, task.output_schema))
        if task.has_tests:
            results.append(self._run_unit_tests(output.code))

        # 2. Grounding: does every claim cite a retrieved source?
        if task.requires_citations:
            results.append(self._check_citations(output, task.documents))

        # 3. Model-based judgement last (slowest, costliest, least reliable)
        if task.evaluation_rubric and all(r.passed for r in results):
            results.append(self._llm_evaluate(output, task.evaluation_rubric))

        return VerificationResult(passed=all(r.passed for r in results), details=results)
```

**Verification patterns:**

| Pattern | Mechanism | Best For | Watch out for |
|---------|-----------|----------|---------------|
| **Deterministic check** | Regex, schema validation, type check, diff rules | Format compliance | Only catches what you can specify |
| **Runtime testing** | Run the test suite in the sandbox | Code generation | Agent editing or deleting tests to make them pass; protect test files |
| **LLM-as-a-judge** | Separate model call scores against a rubric | Subjective quality | Position and verbosity bias, self-preference; calibrate against human labels |
| **Human review** | Approval gate | High-stakes or irreversible actions | Approval fatigue leads to rubber-stamping |
| **A/B or shadow comparison** | Run new version beside baseline | Regression detection | Needs enough traffic for significance |

### 3.4 Context & Memory Management

The harness decides what the model sees on each call. The context window is a budget: more tokens cost more, add latency, and past a point make the model worse at finding what matters. Anthropic's "Effective context engineering for AI agents" calls this keeping the *smallest set of high-signal tokens*.

```python
class HarnessMemory:
    """Multi-tier memory managed by the harness (sketch)."""

    def __init__(self):
        self.working = WorkingMemory()                       # current goal, plan, progress
        self.conversation = SlidingWindow(max_tokens=32_000)  # recent turns
        self.long_term = VectorStore(collection="agent_facts")

    def build_prompt_context(self, max_tokens: int = 64_000) -> str:
        parts = [self.working.summarize()]
        facts = self.long_term.similarity_search(self.working.current_goal, k=5)
        parts.extend(f.text for f in facts)
        parts.append(self.conversation.get_window())
        return self._truncate_to_budget("\n".join(parts), max_tokens)
```

Techniques you should be able to name:

| Technique | What it does | Trade-off |
|-----------|--------------|-----------|
| **Compaction** | Summarise older history when nearing the limit | Lossy; details the summary drops are gone |
| **Tool-result clearing** | Drop old, bulky tool outputs and keep the call record | Model may re-fetch what it needs |
| **Just-in-time retrieval** | Keep file paths/IDs in context and let the agent read on demand | More tool calls, much smaller context |
| **External progress notes** | Agent writes a progress file / to-do list it re-reads | Survives compaction and restarts |
| **Subagents** | Delegate a search to a fresh context and get back a short summary | Extra cost; the parent loses the raw detail |

On the Claude API, compaction and context editing (clearing old tool results) are available as server-side features; check the current docs for model support and beta status. Also keep the stable part of the prompt (system prompt, tool definitions) byte-identical across calls so **prompt caching** can reuse it: caching is a prefix match, so anything volatile (timestamps, request IDs) belongs after the cached prefix.

### 3.5 Prompt Injection Containment

**Crisp answer:** prompt injection is not reliably preventable today, because the model reads instructions and data in the same channel. So design the harness so that a fully hijacked model still can't do serious damage.

The dangerous combination (Simon Willison calls it the *lethal trifecta*) is an agent that has all three of:

1. access to private data,
2. exposure to untrusted content (web pages, emails, issues, retrieved docs, tool results), and
3. a way to send data out (HTTP requests, email, creating a public PR, even rendering an image URL).

Remove at least one leg for any given task. Concretely:

- **Least privilege per task:** tools and credentials scoped to what this task needs, granted for this session only.
- **Egress control:** default-deny network, allowlisted domains via a proxy.
- **Human approval** for irreversible or outbound actions, showing the exact parameters.
- **Privilege separation:** a quarantined model reads untrusted content and can only return structured data to a privileged planner that never sees the raw text (the "dual LLM" pattern; Google DeepMind's CaMeL formalises it with capability tracking).
- **Authorize as the user:** the agent's tool calls run with the end user's permissions, so injection can't escalate beyond what that user could do anyway.
- **Classifiers** (input screening) as one layer, measured for false negatives, never as the only one.

### 3.6 Observability

Log every model call and tool call as a span in one trace per task: inputs (or hashes, if sensitive), outputs, tokens in/out, cache hits, latency, cost, the guardrail decisions and the exit reason. OpenTelemetry's GenAI semantic conventions give you standard attribute names. Without traces you can't answer the questions you'll be asked in an incident: what did the agent see, what did it do, and why did it stop?

---

## 4. HARNESS ENGINEERING BEST PRACTICES

### 4.1 Defense in Depth

Never rely on a single guardrail. Layer them so each catches what the previous one missed:

```
Input layer      →  Model layer        →  Tool layer        →  Output layer
──────────────────────────────────────────────────────────────────────────
Injection        →  System prompt      →  Schema            →  PII redaction
screening        +  constraints        +  validation        +  Content filter
+ Scope filter   +  Budget tracking    +  AuthZ as user     +  Grounding check
                                       +  Sandbox + egress  +  Schema check
                                       +  Approval gates
```

The tool layer carries the most weight, because that is where words become side effects.

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

Prefer narrow, purpose-built tools (`refund_order(order_id, amount)` with server-side limits) over general ones (`run_sql(query)`): the narrow tool encodes the policy in code, so the model can't talk its way past it. Design write tools to be **idempotent** (accept a client-generated request ID), because loops retry.

### 4.3 Harness as a Cybernetic System

The harness operates as a **control loop** with feedforward guides and feedback sensors:

```
Feedforward (before action):
  System prompt ──→ Repo instructions / skills ──→ Plan ──→ Action
                                                             │
                                                             ▼
Feedback (after action):
  Action result ──→ Sensors (tests, linters, judge) ──→ Error analysis ──→ Correction
```

| Element | Harness Component | Example |
|---------|------------------|---------|
| **Reference** | Goal / task spec | "Add pagination to `/orders`; existing tests must pass" |
| **Sensor** | Verification layer | Test results, linter output |
| **Comparator** | Rubric or assertion | "Do all tests pass and does the diff touch only allowed files?" |
| **Effector** | Correction mechanism | Feed the failing test output back and retry |

A practical rule from teams running coding agents at scale: when the agent makes the same mistake twice, fix the **harness** (add a lint rule, a test, a line in `AGENTS.md`/`CLAUDE.md`), not just the one output.

### 4.4 Cost & Resource Governors

Prevent runaway agents with hard limits enforced outside the model:

```python
from dataclasses import dataclass


@dataclass
class HarnessBudget:
    """Resource budget enforced by the harness (illustrative values)."""
    max_tokens_per_session: int = 100_000
    max_tool_calls: int = 50
    max_wall_time_seconds: int = 300
    max_cost_usd: float = 0.50
    max_iterations: int = 25
```

Use **soft limits** (warn, tell the model how much budget remains so it can wrap up) before **hard limits** (stop and return partial results with a clear exit reason). Compute cost from the token usage the API returns for every call, including cache reads and writes, at the provider's current price list; don't hard-code prices.

### 4.5 Common Failure Modes

| Failure | Symptom | Harness fix |
|---------|---------|-------------|
| Context rot | Agent forgets constraints late in a long task | Compaction, progress notes, re-inject key constraints |
| Reward hacking | Tests "pass" because the agent weakened them | Read-only test files, diff rules, review gate |
| Tool thrash | Same failing call repeated | Repetition detector, circuit breaker |
| Over-blocking guardrails | Users route around the agent | Measure false-positive rate, tune thresholds |
| Silent cost blow-up | Bill spikes from one tenant | Per-tenant budgets and alerts on cost per task |
| Prompt injection | Agent follows instructions found in a web page | Section 3.5: remove a leg of the trifecta |

---

## 5. HARNESS ENGINEERING INTERVIEW QUESTIONS

| Question | Key Topics | Evaluation Rubric |
|----------|-----------|-------------------|
| "How would you design a safety harness for an autonomous coding agent?" | Sandboxing, egress control, least privilege, approval gates | Defense in depth, with the sandbox and permissions doing the real work rather than the prompt |
| "How do you evaluate whether your AI agent is production-ready?" | Eval harness, task sets from real traffic, repeated trials, canary | Offline eval (pass rate with variance) **and** online eval (shadow mode, canary, user feedback) |
| "Design a verification system for a code-generation agent." | Test execution, static analysis, diff rules, sandbox | Discusses flaky tests, protecting tests from edits, and false-positive management |
| "How would you prevent an agent from exceeding its budget?" | Token/step/dollar budgets, circuit breaker, cost tracking | Hard caps (kill switch) and soft caps (warn the model, wrap up) |
| "How do you defend an agent against prompt injection?" | Lethal trifecta, privilege separation, egress, approvals | States that filters alone fail; designs for a compromised model |
| "Compare evaluation harness vs agent harness." | Purpose, lifecycle, metrics | Measurement (eval) vs guidance and control at runtime (agent harness) |

**What they probe next:** "Your judge model and your agent are the same model; is that a problem?" (self-preference bias, so use a different model or calibrate against human labels). "How do you roll out a harness change?" (version prompts and tool sets like code, run the eval suite in CI, canary). "Who is accountable when the agent does something wrong?" (audit trail tying each action to the user and the approval).

---

## 6. PRODUCTION HARNESS CHECKLIST

| Component | Implementation | Status |
|-----------|---------------|--------|
| **Input guardrails** | Injection screening, scope filter | 📋 |
| **Output guardrails** | PII redaction, content filter, schema validation | 📋 |
| **Execution sandbox** | gVisor/microVM for untrusted code, resource limits, egress allowlist | 📋 |
| **Verification layer** | Tests, linters, LLM-as-a-judge, diff rules | 📋 |
| **Human-in-the-loop** | Approval gates for irreversible or outbound actions | 📋 |
| **Observability** | One trace per task, token/cost per span, audit trail | 📋 |
| **Cost governance** | Token/dollar/step budgets per session and per tenant | 📋 |
| **Context management** | Compaction, tool-result clearing, progress notes, prompt caching | 📋 |
| **Error recovery** | Retry with backoff, circuit breaker, graceful degradation | 📋 |
| **Eval harness** | Task suite run in CI on every prompt/tool/model change | 📋 |

---

> **Next:** [Loop Engineering](02_LOOP_ENGINEERING.md) → Designing autonomous agentic loops
