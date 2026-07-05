# 🏗️ Agent Production Architecture — Deployment, Guardrails & Tradeoffs

> **Target:** Principal Engineer | **Focus:** Production-grade agent deployment, enterprise security, monitoring

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
        │  │ (Stdio)  │ │ (HTTP)   │ │ (Internal)  │  │
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
      containers:
      - name: agent
        image: myregistry/agent-orchestrator:latest
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
import redis.asyncio as redis
import pickle
from dataclasses import dataclass
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
        await self.redis.setex(
            key, 
            3600,  # 1 hour TTL
            pickle.dumps(session)
        )
    
    async def load(self, session_id: str) -> Optional[AgentSession]:
        data = await self.redis.get(f"agent_session:{session_id}")
        return pickle.loads(data) if data else None
    
    async def delete(self, session_id: str):
        await self.redis.delete(f"agent_session:{session_id}")
```

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
        
        # Prompt injection detection
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                raise GuardrailViolation(
                    "prompt_injection",
                    "Input contains blocked patterns",
                    severity="critical"
                )
        
        # PII detection (simplified)
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
    
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.token_bucket = TokenBucket(rate=50, burst=100)
    
    def validate(self, tool_name: str, params: dict, 
                 user_role: str = "user") -> bool:
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return False
        
        # Schema validation
        try:
            jsonschema.validate(params, tool.parameters)
        except jsonschema.ValidationError:
            return False
        
        # Role-based access
        if user_role not in ["admin", "editor", "user"]:
            return False
        
        # Rate limit
        return self.token_bucket.consume(tool_name)
```

---

## 3. OBSERVABILITY & MONITORING

### 3.1 Tracing Agent Decisions

```python
# Full trace logging of every agent decision
from opentelemetry import trace
from opentelemetry.trace import SpanKind
import json
import time

tracer = trace.get_tracer("agent.orchestrator")

class AgentTracer:
    """Creates detailed traces of agent execution for debugging."""
    
    def trace_step(self, step: int, thought: str, action: str, 
                   params: dict, result: str, duration_ms: float):
        with tracer.start_as_current_span("agent_step") as span:
            span.set_attribute("step", step)
            span.set_attribute("thought", thought[:500])
            span.set_attribute("action", action)
            span.set_attribute("params", json.dumps(params)[:1000])
            span.set_attribute("result_summary", result[:500])
            span.set_attribute("duration_ms", duration_ms)
            
            # Record for audit
            self._log_to_audit({
                "timestamp": time.time(),
                "step": step,
                "thought": thought[:1000],
                "action": action,
                "params": params,
                "result": result[:2000],
                "duration_ms": duration_ms
            })
    
    def _log_to_audit(self, entry: dict):
        """Write to immutable audit log."""
        with open(f"audit/{entry['timestamp']}.json", "a") as f:
            f.write(json.dumps(entry) + "\n")
```

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

agent_tool_error_rate = Gauge(
    'agent_tool_error_rate',
    'Error rate per tool',
    ['tool_name']
)

# Safety metrics
agent_guardrail_violations = Counter(
    'agent_guardrail_violations',
    'Guardrail violations',
    ['guardrail', 'severity']
)

agent_escalation_rate = Gauge(
    'agent_escalation_rate',
    'Fraction of requests escalated to humans'
)

# Cost metrics
agent_llm_cost_total = Counter(
    'agent_llm_cost_total',
    'Total LLM API cost in USD',
    ['model']
)

agent_tokens_per_request = Histogram(
    'agent_tokens_per_request',
    'Tokens consumed per request',
    ['type'],  # prompt, completion
    buckets=[500, 1000, 2000, 4000, 8000, 16000]
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
      expr: rate(agent_requests_total{status="failure"}[5m]) > 0.1
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Agent failure rate > 10%"
    
    - alert: HighEscalationRate
      expr: agent_escalation_rate > 0.3
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Agent escalation rate > 30% — may need tuning"
    
    - alert: ToolErrorSpike
      expr: rate(agent_tool_calls_total{status="error"}[5m]) > 10
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Tool error rate spike for {{ $labels.tool_name }}"
    
    - alert: HighLatency
      expr: histogram_quantile(0.95, agent_request_duration_seconds) > 30
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
      expr: rate(agent_llm_cost_total[1h]) > 50
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
    
    # Confidence-based: escalate when agent confidence is low
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
        # Example rates (replace with actual API pricing)
        RATES = {
            "gpt-4": {"prompt": 0.03/1000, "completion": 0.06/1000},
            "gpt-4o-mini": {"prompt": 0.00015/1000, "completion": 0.0006/1000},
            "claude-3-sonnet": {"prompt": 0.003/1000, "completion": 0.015/1000},
        }
        
        rate = RATES.get(model, RATES["gpt-4o-mini"])
        cost = (prompt_tokens * rate["prompt"] + 
                completion_tokens * rate["completion"])
        
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

## 7. TRADEOFF ANALYSIS

### 7.1 Agent Patterns Decision Matrix

| Criteria | ReAct | Plan-and-Execute | Orchestrator-Worker | Reflection |
|----------|-------|-----------------|-------------------|------------|
| **Flexibility** | High | Medium | High | Low |
| **Predictability** | Low | High | Medium | High |
| **Debug-ability** | Medium | High | Medium | High |
| **Latency** | Low | Medium | High | High |
| **Cost** | Low | Medium | High | High |
| **Quality** | Medium | Medium | High | Very High |
| **When to use** | Quick answers, dynamic | Complex workflows | Multi-skill tasks | Quality-critical output |

### 7.2 Framework Decision

| Framework | Best For | Tradeoff |
|-----------|----------|----------|
| **LangGraph** | Production, regulated | Steep learning curve, graph complexity |
| **Custom (DIY)** | Full control, simple needs | Rebuilding infrastructure |
| **MCP + simple loop** | MCP-native environments | Limited to MCP tools |
| **CrewAI** | Quick prototyping | Production readiness limits |

---

> **End of Agents Module** — Covers architecture, interview questions, implementation, and production deployment.
