# 🏗️ Agent Production Architecture — Deployment, Guardrails & Tradeoffs

> **Target:** Principal Engineer | **Focus:** Production-grade agent deployment, enterprise security, monitoring | **Reviewed:** October 2026

!!! tip "30-second answer"
    A production agent is a **stateless, horizontally scaled service** whose state (conversation, task progress, pending approvals) lives in a durable store, so any replica can resume any session and a deploy doesn't kill in-flight work. Around the loop you need: authentication and per-user authorization on every tool, hard budgets (steps, tokens, dollars, wall-clock), human approval as a *durable pause* rather than a blocked request, tracing of every model and tool call, and an eval suite gating every prompt/model/tool change. Agents are I/O-bound (most time is spent waiting on the model), so scale on concurrency, not CPU.

---

## 1. PRODUCTION DEPLOYMENT ARCHITECTURE

### 1.1 High-Level Architecture

```
                         ┌──────────────────┐
                         │     User          │
                         │ (Web/Mobile/API)  │
                         └────────┬─────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │     API Gateway          │
                    │  - Auth (JWT/OAuth2)     │
                    │  - Rate limiting         │
                    │  - Request validation    │
                    │  - Session routing       │
                    └────────┬────────────────┘
                             │
                             ▼
                    ┌─────────────────────────┐
                    │      AGENT ORCHESTRATOR  │
                    │                         │
                    │  ┌───────────────────┐  │
                    │  │ Session Manager   │  │
                    │  │ - State persistence│  │
                    │  │ - Context window  │  │
                    │  └───────────────────┘  │
                    │  ┌───────────────────┐  │
                    │  │ Agent Runtime     │  │
                    │  │ - ReAct loop      │  │
                    │  │ - Tool dispatch   │  │
                    │  │ - Guardrails      │  │
                    │  └───────────────────┘  │
                    │  ┌───────────────────┐  │
                    │  │ Memory Manager    │  │
                    │  │ - Short-term      │  │
                    │  │ - Working         │  │
                    │  │ - Long-term       │  │
                    │  └───────────────────┘  │
                    └────────┬────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────────┐
        │            TOOL EXECUTION LAYER               │
        │                                               │
        │  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
        │  │ MCP Serv.│ │ REST API │ │ RAG Pipeline│  │
        │  │(HTTP/std)│ │ (HTTP)   │ │ (Internal)  │  │
        │  └──────────┘ └──────────┘ └─────────────┘  │
        └─────────────────────────────────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────────┐
        │           OBSERVABILITY STACK                 │
        │                                               │
        │  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
        │  │Traces    │ │ Metrics  │ │ Logs         │  │
        │  │(OTel)    │ │(Prometheus)│ │(Loki/ES)    │  │
        │  └──────────┘ └──────────┘ └─────────────┘  │
        └─────────────────────────────────────────────┘
```

### 1.2 Kubernetes Deployment

```yaml
# k8s/agent-orchestrator.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-orchestrator
  namespace: ai-engineering
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2
      maxUnavailable: 0
  selector:
    matchLabels:
      app: agent-orchestrator
  template:
    metadata:
      labels:
        app: agent-orchestrator
    spec:
      # Long agent runs and SSE streams need time to drain on deploy/scale-in.
      terminationGracePeriodSeconds: 300
      containers:
      - name: agent
        image: myregistry/agent-orchestrator:1.42.0   # pin a version or digest; never :latest
        ports:
        - containerPort: 8080
          name: http
        env:
        - name: LLM_API_KEY
          valueFrom:
            secretKeyRef:
              name: llm-credentials
              key: api_key
        - name: REDIS_URL
          value: redis://redis-cluster:6379
        - name: MAX_STEPS
          value: "25"
        - name: RATE_LIMIT_RPS
          value: "100"
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-orchestrator-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-orchestrator
  minReplicas: 3
  maxReplicas: 20
  # Agents spend most of their time waiting on LLM APIs, so CPU stays low
  # while the pod is saturated. Scale primarily on concurrent sessions
  # (custom metric via Prometheus Adapter or KEDA); keep CPU as a backstop.
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: agent_active_sessions
      target:
        type: AverageValue
        averageValue: 50
```

### 1.3 Session State Persistence

```python
# Session state management for fault tolerance
import json
import redis.asyncio as redis
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class AgentSession:
    session_id: str
    user_id: str
    conversation_history: list
    current_task: Optional[dict]
    tool_call_history: list
    memory_snapshot: dict
    step_count: int
    created_at: float
    last_active: float

class SessionManager:
    """Persists agent state across requests for fault tolerance."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url)
    
    async def save(self, session: AgentSession):
        key = f"agent_session:{session.session_id}"
        # JSON, not pickle: unpickling bytes from a shared store is remote
        # code execution if the store is ever compromised, and pickle breaks
        # across code versions during a rolling deploy.
        await self.redis.setex(
            key, 
            3600,  # 1 hour idle TTL, refreshed on every save
            json.dumps(asdict(session))
        )
    
    async def load(self, session_id: str) -> Optional[AgentSession]:
        data = await self.redis.get(f"agent_session:{session_id}")
        return AgentSession(**json.loads(data)) if data else None
    
    async def delete(self, session_id: str):
        await self.redis.delete(f"agent_session:{session_id}")
```

Redis with a TTL suits short-lived session state. For long-running or audited workflows, persist to a database (Postgres) after every step, which is what LangGraph's Postgres checkpointer or a durable-execution engine (Temporal, AWS Step Functions) gives you. Guard against two replicas processing the same session concurrently (a per-session lock or a single-consumer queue per session).

---

## 2. GUARDRAILS (DEFENSE IN DEPTH)

### 2.1 Guardrail Architecture

```
INPUT                     OUTPUT
  │                          │
  ▼                          ▼
┌────────────────────────────────────────────────────┐
│                  GUARDRAIL STACK                      │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ Input Guard   │  │ Output Guard │                  │
│  │ - Injection   │  │ - Toxicity   │                  │
│  │ - PII detect  │  │ - PII leak   │                  │
│  │ - Max length  │  │ - Fact check │                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         │                 │                           │
│         ▼                 ▼                           │
│  ┌──────────────────────────────────────┐            │
│  │         Tool Call Guard               │            │
│  │  - Schema validation                  │            │
│  │  - Authorization (RBAC)              │            │
│  │  - Rate limiting                     │            │
│  │  - Approval for destructive actions  │            │
│  └──────────────────────────────────────┘            │
│                                                       │
│  ┌──────────────────────────────────────┐            │
│  │         Runtime Guard                 │            │
│  │  - Max steps                          │            │
│  │  - Max tokens                         │            │
│  │  - Timeout                            │            │
│  │  - Duplicate detection                │            │
│  └──────────────────────────────────────┘            │
└──────────────────────────────────────────────────────┘
```

### 2.2 Implementation

```python
import re
from collections import defaultdict

class GuardrailViolation(Exception):
    """Raised when a guardrail is triggered."""
    def __init__(self, guardrail: str, message: str, severity: str = "warning"):
        self.guardrail = guardrail
        self.severity = severity
        super().__init__(message)

class InputGuard:
    """Validates all user inputs to the agent."""
    
    MAX_INPUT_LENGTH = 4000
    BLOCKED_PATTERNS = [
        r"ignore all previous instructions",
        r"system prompt:",
        r"you are now",
    ]
    
    def validate(self, user_input: str) -> str:
        if len(user_input) > self.MAX_INPUT_LENGTH:
            raise GuardrailViolation(
                "input_length",
                f"Input exceeds {self.MAX_INPUT_LENGTH} characters"
            )
        
        # Prompt injection "detection": a regex deny-list only stops the
        # laziest attempts (paraphrases, other languages and encodings pass).
        # Use a classifier model as a signal, and rely on least privilege and
        # approvals as the actual control. Also: injections mostly arrive via
        # TOOL RESULTS (web pages, emails, files), not the user's message.
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                raise GuardrailViolation(
                    "prompt_injection",
                    "Input contains blocked patterns",
                    severity="critical"
                )
        
        # PII detection (simplified; real systems use a PII service + Luhn check)
        if re.search(r"\b\d{16}\b", user_input):  # Credit card
            raise GuardrailViolation(
                "pii_detected",
                "Input contains credit card numbers"
            )
        
        return user_input

class OutputGuard:
    """Validates all agent outputs before returning to user."""
    
    def validate(self, agent_output: str) -> str:
        # Check for PII leakage
        if re.search(r"\b\d{16}\b", agent_output):
            agent_output = self._redact_pii(agent_output)
        
        # Check for toxicity
        if self._toxicity_score(agent_output) > 0.3:
            raise GuardrailViolation(
                "toxic_output",
                "Agent output flagged as potentially harmful"
            )
        
        return agent_output
    
    def _toxicity_score(self, text: str) -> float:
        """Use an LLM-as-judge to score output toxicity."""
        # In production: call a toxicity classifier API
        return 0.0
    
    def _redact_pii(self, text: str) -> str:
        """Replace PII with placeholders."""
        text = re.sub(r"\b\d{16}\b", "[REDACTED CC]", text)
        text = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[REDACTED EMAIL]", text)
        return text

class ToolCallGuard:
    """Validates every tool call the agent makes."""
    
    ROLE_LEVEL = {"user": 1, "editor": 2, "admin": 3}

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        # One bucket per (user, tool): a global bucket lets one user starve all.
        self.buckets = defaultdict(lambda: TokenBucket(rate=5, burst=10))
    
    def validate(self, tool_name: str, params: dict, 
                 user_id: str, user_role: str = "user") -> bool:
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return False
        
        # Schema validation
        try:
            jsonschema.validate(params, tool.parameters)
        except jsonschema.ValidationError:
            return False
        
        # Role-based access: the USER's role must meet the tool's requirement
        if self.ROLE_LEVEL.get(user_role, 0) < self.ROLE_LEVEL[tool.required_role]:
            return False
        
        # Rate limit
        return self.buckets[(user_id, tool_name)].consume(1)
```

---

## 3. OBSERVABILITY & MONITORING

### 3.1 Tracing Agent Decisions

```python
# Trace every model call and tool call using the OpenTelemetry GenAI
# semantic conventions (still "Development" status; names may change).
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
import json

tracer = trace.get_tracer("agent.orchestrator")

async def traced_tool_call(tool_name: str, call_id: str, params: dict, fn):
    # Span name convention: "{operation} {target}"; durations come from the span.
    with tracer.start_as_current_span(f"execute_tool {tool_name}",
                                      kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        span.set_attribute("gen_ai.tool.call.id", call_id)
        try:
            result = await fn(**params)
            return result
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
            raise

def record_llm_usage(span, request_model: str, response):
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.request.model", request_model)
    span.set_attribute("gen_ai.response.model", response.model)
    span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
```

Arguments, prompts and results can contain PII and secrets: capture content only when explicitly enabled, redact it, and keep it in a store with access control and retention. The **audit log** is a separate concern from traces: an append-only record (who, which tool, which args, which approval) in a write-once store (e.g. object storage with object lock, or an append-only table), not a local file on an ephemeral container. See [Agent Observability](07_AGENT_OBSERVABILITY.md) for the full model.

### 3.2 Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Request metrics
agent_requests_total = Counter(
    'agent_requests_total',
    'Total agent requests',
    ['status']  # success, failure, escalated
)

agent_request_duration = Histogram(
    'agent_request_duration_seconds',
    'Agent request duration',
    buckets=[0.5, 1, 2, 5, 10, 30, 60]
)

# Step metrics
agent_steps_per_request = Histogram(
    'agent_steps_per_request',
    'Number of steps per agent request',
    buckets=[1, 3, 5, 10, 15, 25, 50]
)

agent_step_duration = Histogram(
    'agent_step_duration_seconds',
    'Duration per step',
    ['tool_name'],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

# Tool metrics
agent_tool_calls_total = Counter(
    'agent_tool_calls_total',
    'Total tool calls',
    ['tool_name', 'status']  # success, error, rate_limited, denied
)

# Don't export pre-computed ratios as Gauges; derive error rates in PromQL
# from the counter above (rate(errors) / rate(all)), which aggregates correctly.

# Safety metrics
agent_guardrail_violations = Counter(
    'agent_guardrail_violations',
    'Guardrail violations',
    ['guardrail', 'severity']
)


# Cost metrics
agent_llm_cost_total = Counter(
    'agent_llm_cost_total',
    'Total LLM API cost in USD',
    ['model']
)

agent_tokens_per_request = Histogram(
    'agent_tokens_per_request',
    'Tokens consumed per request (summed over every model call in the run)',
    ['type'],  # input, cached_input, output (reasoning tokens bill as output)
    buckets=[1_000, 4_000, 16_000, 64_000, 256_000, 1_000_000]  # agents resend history
)

# Active sessions
agent_active_sessions = Gauge(
    'agent_active_sessions',
    'Currently active agent sessions'
)

agent_session_duration = Histogram(
    'agent_session_duration_seconds',
    'Agent session duration',
    buckets=[10, 30, 60, 120, 300, 600, 1800]
)
```

### 3.3 Alerting Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: agent-alerts
    rules:
    - alert: HighFailureRate
      # A ratio, not a raw rate: rate(failures) alone is failures/second.
      expr: |
        sum(rate(agent_requests_total{status="failure"}[5m]))
          / sum(rate(agent_requests_total[5m])) > 0.1
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Agent failure rate > 10%"
    
    - alert: HighEscalationRate
      expr: |
        sum(rate(agent_requests_total{status="escalated"}[15m]))
          / sum(rate(agent_requests_total[15m])) > 0.3
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Agent escalation rate > 30% — may need tuning"
    
    - alert: ToolErrorSpike
      expr: |
        sum by (tool_name) (rate(agent_tool_calls_total{status="error"}[5m]))
          / sum by (tool_name) (rate(agent_tool_calls_total[5m])) > 0.2
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Tool error rate spike for {{ $labels.tool_name }}"
    
    - alert: HighLatency
      expr: histogram_quantile(0.95, sum by (le) (rate(agent_request_duration_seconds_bucket[5m]))) > 30
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "p95 agent latency > 30s"
    
    - alert: GuardrailViolations
      expr: rate(agent_guardrail_violations{severity="critical"}[5m]) > 1
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Critical guardrail violations detected"
    
    - alert: CostAnomaly
      expr: sum(increase(agent_llm_cost_total[1h])) > 50   # rate() would be $/second
      labels:
        severity: warning
      annotations:
        summary: "LLM cost > $50/hour — possible runaway agent"
```

---

## 4. HUMAN-IN-THE-LOOP (HITL)

### 4.1 Approval Workflow

```python
class HumanInTheLoop:
    """
    Manages human approval for high-risk agent actions.
    
    Flow:
    1. Agent proposes action
    2. HITL creates approval ticket
    3. Notifies human reviewer
    4. Waits for approval/rejection
    5. Agent proceeds or replans
    """
    
    def __init__(self, notification_service):
        self.pending_approvals = {}
        self.notifier = notification_service
    
    async def request_approval(self, action: dict, context: dict) -> bool:
        """Request human approval for a proposed action."""
        approval_id = str(uuid.uuid4())
        
        # Create approval request
        request = {
            "id": approval_id,
            "action": action,
            "context": context,
            "status": "pending",
            "created_at": time.time()
        }
        
        self.pending_approvals[approval_id] = request
        
        # Notify reviewer (Slack, email, dashboard)
        await self.notifier.send({
            "channel": "agent-approvals",
            "message": f"⚠️ Approval needed: {action['tool']}",
            "details": f"Params: {json.dumps(action['params'], indent=2)}\n"
                      f"Context: {context.get('conversation_summary', 'N/A')}",
            "approval_id": approval_id,
            "actions": [
                {"label": "Approve", "action": f"/approve/{approval_id}"},
                {"label": "Reject", "action": f"/reject/{approval_id}"},
            ]
        })
        
        # Wait for response (with timeout)
        approved = await self._wait_for_decision(approval_id, timeout=300)
        
        if approved:
            request["status"] = "approved"
            return True
        else:
            request["status"] = "rejected"
            return False
    
    async def _wait_for_decision(self, approval_id: str, timeout: int) -> bool:
        """Wait for a human to approve or reject."""
        start = time.time()
        while time.time() - start < timeout:
            request = self.pending_approvals.get(approval_id)
            if request and request["status"] in ("approved", "rejected"):
                return request["status"] == "approved"
            await asyncio.sleep(1)
        
        # Timeout — escalate
        return False  # Reject on timeout
```

This version is fine for a demo but wrong for production: it holds a request (and a worker) open for up to 5 minutes, keeps pending approvals in process memory (lost on restart, invisible to other replicas) and polls. Real approvals take hours. The production shape is a **durable pause**:

1. Persist the run state and the proposed action, mark the run `awaiting_approval`, return to the caller.
2. Notify the reviewer with the exact action, arguments and a diff of what will change.
3. The approve/reject callback (verified, authorized, idempotent) resumes the run from the checkpoint on any replica.
4. Re-validate before executing: the world may have changed while waiting.

LangGraph's `interrupt()` + `Command(resume=...)` with a persistent checkpointer, the OpenAI Agents SDK's tool approval flow, or a workflow engine (Temporal signals, Step Functions task tokens) implement this pattern.

### 4.2 Escalation Rules

```python
ESCALATION_RULES = {
    # Tool-based: specific tools always require human approval
    "tool_based": {
        "delete_user": "always",
        "drop_table": "always",
        "update_billing": "if_amount > 1000",
        "send_email": "if_recipients > 100",
    },
    
    # Confidence-based: escalate when a CHECKABLE signal is weak (retrieval
    # score, groundedness check, classifier probability). Self-reported LLM
    # confidence is poorly calibrated; calibrate any score on labelled data.
    "confidence_based": {
        "threshold": 0.7,
        "action": "escalate_if_below"
    },
    
    # Pattern-based: escalate if agent retries the same action
    "pattern_based": {
        "max_retries_same_tool": 3,
        "action": "escalate"
    },
    
    # Cost-based: escalate if LLM cost exceeds threshold
    "cost_based": {
        "max_cost_per_request": 0.50,  # USD
        "action": "escalate"
    }
}
```

---

## 5. AGENT EVALUATION FRAMEWORK

### 5.1 Evaluation Pipeline

```python
class AgentEvaluator:
    """
    Production evaluation framework for agent quality.
    
    Metrics:
    - Task completion rate
    - Steps per task
    - Tool error rate
    - Hallucination rate
    - User satisfaction
    - Cost per task
    """
    
    def __init__(self, agent, test_suite_path: str):
        self.agent = agent
        self.test_suite = self._load_tests(test_suite_path)
    
    async def evaluate(self) -> dict:
        results = []
        
        for test_case in self.test_suite:
            result = await self._run_test(test_case)
            results.append(result)
        
        return self._aggregate(results)
    
    async def _run_test(self, test_case: dict) -> dict:
        """Run a single test case and evaluate the result."""
        start = time.time()
        
        # Run agent
        agent_output = await self.agent.run(test_case["input"])
        duration = time.time() - start
        
        # Evaluate using rubrics
        scores = {}
        for rubric_name, rubric_fn in test_case["rubrics"].items():
            scores[rubric_name] = rubric_fn(agent_output, test_case)
        
        return {
            "test_name": test_case["name"],
            "passed": all(s["passed"] for s in scores.values()),
            "duration_seconds": duration,
            "scores": scores,
            "agent_output": agent_output,
            "steps": agent_output.steps_count,
        }
    
    def _aggregate(self, results: list) -> dict:
        """Aggregate results across all test cases."""
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        
        return {
            "pass_rate": passed / total,
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "avg_duration": sum(r["duration_seconds"] for r in results) / total,
            "avg_steps": sum(r["steps"] for r in results) / total,
            "results": results,
        }
```

### 5.2 Benchmark Suite

```python
# Example test cases for agent evaluation

TEST_SUITE = [
    {
        "name": "simple_qa",
        "input": "What is the capital of France?",
        "expected_tools": [],  # Should answer from knowledge alone
        "rubrics": {
            "accuracy": lambda out, tc: {"passed": "Paris" in out, "score": 1.0},
            "conciseness": lambda out, tc: {"passed": len(out) < 200, "score": 0.9},
        }
    },
    {
        "name": "tool_use_basic",
        "input": "What's the weather in Tokyo?",
        "expected_tools": ["get_weather"],
        "rubrics": {
            "tool_used": lambda out, tc: {"passed": out.tools_used == ["get_weather"]},
            "accuracy": lambda out, tc: {"passed": "Tokyo" in out and "°" in out},
        }
    },
    {
        "name": "multi_step_reasoning",
        "input": "Compare the population of Japan and South Korea. Which has a higher population density?",
        "expected_tools": ["get_population", "get_area", "calculate_density"],
        "rubrics": {
            "correct_tools": lambda out, tc: {"passed": len(out.tools_used) >= 2},
            "correct_answer": lambda out, tc: {"passed": "Japan" in out or "South Korea" in out},
        }
    },
    {
        "name": "error_recovery",
        "input": "Get the user data for user 999999 (doesn't exist), then try user 123",
        "expected_tools": ["get_user", "get_user"],
        "rubrics": {
            "recovery": lambda out, tc: {"passed": "doesn't exist" in out or "not found" in out.lower()},
            "continues": lambda out, tc: {"passed": "123" in out},
        }
    },
    {
        "name": "safety_hallucination",
        "input": "When was the company founded? (No data available in KB)",
        "expected_tools": ["search_kb"],
        "rubrics": {
            "refuses": lambda out, tc: {"passed": "I don't know" in out or "don't have" in out.lower()},
            "no_fabrication": lambda out, tc: {"passed": "1990" not in out and "1980" not in out},
        }
    },
]
```

---

## 6. COST MANAGEMENT

### 6.1 Cost Budgeting

```python
class CostManager:
    """
    Tracks and enforces cost budgets for agent execution.
    Prevents runaway costs from loops or expensive tool calls.
    """
    
    def __init__(self, max_cost_per_request: float = 1.0):
        self.max_cost = max_cost_per_request
        self.current_cost = 0.0
    
    def track_llm_call(self, model: str, prompt_tokens: int, 
                        completion_tokens: int):
        """Track LLM API costs."""
        # Prices change often: load them from config (USD per 1M tokens),
        # keyed by the exact model id, and check the provider's pricing page.
        rate = PRICE_TABLE.get(model)
        if rate is None:
            # Fail loudly: silently defaulting to a cheap model's price hides spend.
            raise KeyError(f"No price configured for model {model!r}")
        cost = (prompt_tokens * rate["input"] +
                completion_tokens * rate["output"]) / 1_000_000
        # Real bills also distinguish cached-input reads (much cheaper), cache
        # writes (more expensive than plain input on Anthropic), and reasoning
        # tokens (billed as output). Use the usage fields the API returns.
        
        self.current_cost += cost
        
        if self.current_cost > self.max_cost:
            raise BudgetExceeded(f"Cost ${self.current_cost:.4f} exceeds max ${self.max_cost}")
    
    def track_tool_call(self, tool_name: str, duration_ms: float):
        """Track tool execution costs (infra)."""
        # Estimate based on compute resources
        cost = (duration_ms / 1000) * 0.0001  # ~$0.10/hour
        self.current_cost += cost
```

---

### 6.2 Cost levers, in the order to pull them

1. **Prompt caching** of the stable prefix (system prompt + tool definitions + long documents). Agent loops resend the same prefix every turn, so this is usually the biggest, lowest-risk saving. Keep the prefix byte-stable (no timestamps, deterministic tool order).
2. **Trim what goes back into context:** truncate or summarize large tool results, clear old ones, compact long histories.
3. **Fewer steps:** better tool design and descriptions cut wasted calls more than any model change.
4. **Right-size the model per step:** a smaller model for routing, extraction and sub-agents; reasoning effort turned down for easy steps.
5. **Batch APIs** (typically about half price) for offline, non-interactive work.

Measure **cost per successfully completed task**, not per request: a cheaper model that needs twice the turns or fails more often is not cheaper.

---

## 7. TRADEOFF ANALYSIS

### 7.1 Agent Patterns Decision Matrix

| Criteria | ReAct | Plan-and-Execute | Orchestrator-Worker | Reflection |
|----------|-------|-----------------|-------------------|------------|
| **Flexibility** | High | Medium | High | Low |
| **Predictability** | Low | High | Medium | High |
| **Debug-ability** | Medium | High | Medium | High |
| **Latency** | Low | Medium | High | High |
| **Cost** | Low | Medium | High | High |
| **Quality** | Medium | Medium | High | High when the critic has real signal (tests, sources) |
| **When to use** | Quick answers, dynamic | Complex workflows | Multi-skill tasks | Quality-critical output |

### 7.2 Framework Decision

| Framework | Best For | Tradeoff |
|-----------|----------|----------|
| **LangGraph** | Durable, resumable workflows with human-in-the-loop | Learning curve, graph complexity, framework churn |
| **OpenAI Agents SDK / Claude Agent SDK** | Fast path on one provider's strengths (handoffs, built-in tools, tracing) | Ties you to that provider's abstractions |
| **Custom (DIY) loop + MCP for tools** | Full control, simple needs, provider-agnostic | You build persistence, approvals and tracing yourself |
| **CrewAI** | Quick prototyping | Less control over the loop and state |

### 7.3 What interviewers probe next

- **"A deploy happens mid-run. What breaks?"** Nothing, if state is checkpointed per step and pods drain gracefully; otherwise the run is lost or, worse, a side effect is repeated on retry (idempotency keys).
- **"How do you stop one user's runaway agent from eating your provider rate limit?"** Per-user token and spend budgets, per-tenant queues, and provider-level rate-limit headroom with backoff.
- **"How do you roll out a new model or prompt?"** Offline eval suite first, then shadow or canary traffic with per-variant quality, latency and cost metrics, with fast rollback (the prompt and model id are config, versioned).
- **"Where is the security boundary?"** Not the system prompt. It's credentials, authorization, sandboxing and approvals.

---

> **Next:** [LangGraph Notes](05_LANGGRAPH_NOTES.md) → graph-based agents, checkpointers and human-in-the-loop
