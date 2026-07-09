# 🏗️ MCP Production Architecture — Deployment, Security & Tradeoffs

> **Target:** Principal Engineer | **Focus:** Production-grade MCP deployment, enterprise security, scalability

---

## 1. PRODUCTION DEPLOYMENT ARCHITECTURE

### 1.1 High-Level Architecture

```
                             ┌─────────────┐
                             │  AI Agent    │
                             │  (Host)      │
                             └──────┬──────┘
                                    │ MCP Protocol (Streamable HTTP)
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                     MCP GATEWAY (Kong/ALB)                         │
│  - Authentication (JWT/OAuth2)                                     │
│  - Rate limiting (per client/tool)                                 │
│  - Load balancing (least connections)                              │
│  - Request logging + audit trail                                   │
│  - Circuit breaker per upstream                                    │
│  - TLS termination                                                  │
└───────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
│  MCP Server A      │ │  MCP Server B      │ │  MCP Server C      │
│  (Database Wrapper) │ │  (File System)     │ │  (RAG Pipeline)    │
│                    │ │                    │ │                    │
│  - 3 replicas      │ │  - 2 replicas      │ │  - 5 replicas      │
│  - HPA (70% CPU)   │ │  - HPA (100 req/s) │ │  - HPA (GPU util)  │
│  - Pool: 10 DB    │ │  - Pool: 20 conn   │ │  - Pool: 5 GPU     │
│  - Timeout: 10s    │ │  - Timeout: 30s    │ │  - Timeout: 60s    │
└────────────────────┘ └────────────────────┘ └────────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌───────────────────────────────────────────────────────────────────┐
│                      OBSERVABILITY STACK                            │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │Prometheus│  │  Grafana │  │   Loki   │  │  OpenTelemetry │   │
│  │ Metrics  │  │  Alerts  │  │   Logs   │  │   Traces       │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘   │
│                                                                   │
│  Key Metrics:                                                     │
│  - mcp_requests_total{tool, client, status}                       │
│  - mcp_request_duration_seconds{tool, p50/p95/p99}               │
│  - mcp_rate_limit_exceeded_total{client}                         │
│  - mcp_circuit_breaker_state{server, state}                      │
│  - mcp_tool_error_total{tool, error_type}                        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### 1.2 Kubernetes Deployment

```yaml
# k8s/mcp-rag-server.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-rag-server
  namespace: ai-engineering
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Zero-downtime deployments
  selector:
    matchLabels:
      app: mcp-rag-server
  template:
    metadata:
      labels:
        app: mcp-rag-server
    spec:
      containers:
      - name: mcp-server
        image: myregistry/mcp-rag-server:latest
        ports:
        - containerPort: 8000
          name: mcp-sse
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        - name: MAX_ROWS
          value: "1000"
        - name: QUERY_TIMEOUT
          value: "10"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcp-rag-server-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mcp-rag-server
  minReplicas: 2
  maxReplicas: 10
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
        name: mcp_requests_per_second
      target:
        type: AverageValue
        averageValue: 100
```

### 1.3 Docker Setup

```dockerfile
# Dockerfile
FROM python:3.12-slim

# Security: run as non-root
RUN useradd -m -u 1001 mcpserver

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY servers/ servers/
COPY common/ common/

# Security: read-only filesystem
USER mcpserver

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "servers.rag_server"]
```

---

## 2. SECURITY ARCHITECTURE

### 2.1 Threat Model

| Threat | Vector | Impact | Mitigation |
|--------|--------|--------|------------|
| **RCE via tool params** | LLM hallucinates malicious params | Server compromise | Schema validation, allowlists, sandboxing |
| **Data exfiltration** | Resource URIs reading sensitive data | Data leak | Auth middleware, row-level security |
| **Prompt injection** | User input in tool descriptions | Unauthorized actions | Input sanitization, context isolation |
| **DDoS / resource exhaustion** | Loop/infinite tool calls | Service degradation | Rate limiting, circuit breaker |
| **Privilege escalation** | JWT manipulation | Unauthorized access | Token validation, least privilege |
| **Supply chain** | Vulnerable MCP SDK version | Various | Dependency scanning, pinned versions |

### 2.2 Defense in Depth

```python
"""
MCP Security — Multi-Layer Defense Architecture

Layer 1: Network Isolation
├── MCP servers in private subnets only
├── No direct internet access for servers
├── TLS 1.3 for all remote connections
└── API Gateway enforces auth before reaching servers

Layer 2: Authentication & Authorization
├── JWT validation on every initialize
├── OAuth2 flow for user-level identity
├── Tool-level RBAC (role:viewer can't call delete tools)
└── Row-level security via tenant context propagation

Layer 3: Input Validation
├── JSON Schema validation (reject unknown parameters)
├── Command allowlists (not blocklists)
├── SQL injection prevention (parameterized queries)
└── Path traversal protection (canonicalize paths)

Layer 4: Execution Sandboxing
├── Container-level isolation (Docker + seccomp)
├── Read-only filesystem for servers
├── Resource limits (CPU, memory, timeout)
└── Dropped capabilities (no CAP_SYS_ADMIN)

Layer 5: Observability & Audit
├── Full audit trail: every tool call logged
├── Anomaly detection on tool usage patterns
├── Rate limiting alerts
└── Scheduled security reviews
"""
```

### 2.3 Auth Middleware Implementation

```python
# common/auth.py
import os
import jwt
from dataclasses import dataclass
from typing import Optional, List
from functools import wraps

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "RS256"
JWT_PUBLIC_KEY = os.environ.get("JWT_PUBLIC_KEY", "")

@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    roles: List[str]
    session_id: str
    permissions: List[str]

class AuthError(Exception):
    pass

class AuthorizationError(Exception):
    pass

def validate_token(token: str) -> AuthContext:
    """Validate JWT and extract auth context."""
    try:
        if JWT_ALGORITHM == "RS256":
            payload = jwt.decode(token, JWT_PUBLIC_KEY, algorithms=["RS256"])
        else:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        
        return AuthContext(
            user_id=payload["sub"],
            tenant_id=payload.get("tenant_id", "default"),
            roles=payload.get("roles", []),
            session_id=payload.get("jti", ""),
            permissions=payload.get("permissions", [])
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid token")

def require_permission(permission: str):
    """Decorator for tool-level authorization."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            ctx = get_current_context()
            if permission not in ctx.permissions:
                raise AuthorizationError(
                    f"Missing required permission: {permission}"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@require_permission("database:read")
@mcp.tool()
def query_database(sql: str) -> str:
    """Only callable by users with database:read permission."""
    ctx = get_current_context()
    return execute_query(sql, tenant_id=ctx.tenant_id)
```

---

## 3. ENTERPRISE CONSTRAINTS & COMPLIANCE

### 3.1 Audit Requirements

```python
# common/audit.py
import json
import logging
from datetime import datetime

audit_logger = logging.getLogger("mcp.audit")

class AuditEntry:
    """Immutable audit entry for compliance."""
    
    def __init__(self, tool_name: str, params: dict, result: str,
                 auth_context: "AuthContext", duration_ms: float):
        self.timestamp = datetime.utcnow().isoformat()
        self.tool_name = tool_name
        self.params = sanitize_params(params)  # Remove sensitive fields
        self.result_summary = truncate_result(result, 500)
        self.user_id = auth_context.user_id
        self.tenant_id = auth_context.tenant_id
        self.session_id = auth_context.session_id
        self.duration_ms = duration_ms
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "params": self.params,
            "result_summary": self.result_summary,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "duration_ms": self.duration_ms
        }

def log_tool_call(func):
    """Decorator to audit all tool calls."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            entry = AuditEntry(
                tool_name=func.__name__,
                params=kwargs,
                result=result,
                auth_context=get_current_context(),
                duration_ms=duration
            )
            audit_logger.info(json.dumps(entry.to_dict()))
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            entry = AuditEntry(
                tool_name=func.__name__,
                params=kwargs,
                result=f"ERROR: {str(e)}",
                auth_context=get_current_context(),
                duration_ms=duration
            )
            audit_logger.error(json.dumps(entry.to_dict()))
            raise
    return wrapper
```

### 3.2 Compliance Checklist

| Requirement | Implementation | Verification |
|-------------|---------------|--------------|
| **SOC 2** | Audit logging, access controls | Quarterly audit review |
| **GDPR** | Data minimization, right to deletion | PII sanitization in logs |
| **HIPAA** | PHI isolation, BAA with cloud provider | Encrypted at rest + transit |
| **SOX** | Immutable audit trail, segregation of duties | Read-only + approval workflows |
| **PCI DSS** | No credit card data in MCP params | Tokenization at tool boundary |

---

## 4. SCALABILITY & PERFORMANCE

### 4.1 Latency Budget

```
Typical MCP Request Lifecycle:
                           Percentile
Component             p50     p95     p99
─────────────────────────────────────────
Auth + Rate Limit     2ms     5ms    10ms
Tool Discovery        1ms     3ms     5ms
Parameter Validation  1ms     2ms     5ms
Tool Execution:
  - Simple (calc)     5ms    10ms    20ms
  - DB Query          50ms   200ms   500ms
  - RAG Query         800ms  2s      5s
  - File Index        5s     15s     30s
Response Formatting   2ms     5ms    10ms
─────────────────────────────────────────
Total (simple)        ~10ms   ~25ms   ~50ms
Total (RAG)           ~900ms  ~2.2s   ~5.5s
```

### 4.2 Connection Management

```python
class ConnectionManager:
    """Manages MCP server connections with pooling."""
    
    def __init__(self, max_connections: int = 100, idle_timeout: int = 300):
        self.semaphore = asyncio.Semaphore(max_connections)
        self.idle_timeout = idle_timeout
        self.active_connections = {}
    
    async def acquire(self, client_id: str) -> bool:
        if self.semaphore.locked():
            return False
        
        await self.semaphore.acquire()
        self.active_connections[client_id] = time.time()
        return True
    
    def release(self, client_id: str):
        self.semaphore.release()
        self.active_connections.pop(client_id, None)
    
    def cleanup_stale(self):
        """Periodically clean up stale connections."""
        now = time.time()
        stale = [
            cid for cid, ts in self.active_connections.items()
            if now - ts > self.idle_timeout
        ]
        for cid in stale:
            self.release(cid)
```

### 4.3 Caching Strategy

| Cache Level | What | TTL | Invalidation |
|------------|------|-----|-------------|
| **L1 — Tool schemas** | `tools/list`, `resources/list` | Session | Server restart |
| **L2 — Query results** | Frequent DB queries | 5 min | Write-through |
| **L3 — RAG queries** | Semantic caching | 10 min | Document update |
| **L4 — Embeddings** | Query embeddings | 1 hour | Model update |

---

## 5. USE CASES & TRADEOFFS

### 5.1 When to Use MCP

| Use Case | Why MCP | Example |
|----------|---------|---------|
| **Developer tooling** | Local stdio transport, low latency, no network | Code analysis, CLI agents |
| **Internal enterprise agents** | Standardized tool access, audit logging | Employee HR bot, IT ops |
| **Multi-LLM orchestration** | Provider-agnostic protocol | Switch between Claude, GPT, local models |
| **RAG + tool composition** | Resources for docs, tools for actions | Customer support with KB lookup + ticket creation |
| **Desktop AI assistants** | Process isolation, local execution | File management, email drafting |

### 5.2 When NOT to Use MCP

| Use Case | Why Not | Better Alternative |
|----------|---------|-------------------|
| **Simple CRUD API** | Protocol overhead adds latency, no benefit | REST/GraphQL |
| **High-throughput data pipeline** | JSON-RPC parsing is CPU-intensive | gRPC, message queue |
| **Real-time streaming (audio/video)** | MCP is request-response, not streaming | WebRTC, raw WebSocket |
| **Single-provider LLM app** | Function calling is tighter integration | OpenAI/Anthropic function calling |
| **Public-facing API** | MCP is designed for AI agents, not browsers | REST + OpenAPI |

### 5.3 Tradeoff Analysis

```
              MCP vs Alternatives Decision Matrix
          
                    MCP     Function Calling    REST API
                    ───     ───────────────     ────────
Protocol Overhead    Low     None (built-in)    Low
Provider Agnostic    ✅      ❌ (locked in)     ✅ (if designed)
Security Boundary    ✅      ⚠️ (API key)      ✅ (standard)
Tool Discovery       ✅      ✅                 ❌ (docs)
Local Transport      ✅      ❌ (HTTP only)     ❌ (HTTP only)
Multi-Tenancy        ⚠️      ⚠️                 ✅ (battle-tested)
Maturity             New     Mature             Very Mature
Ecosystem Size      Small   Large              Massive
```

---

## 6. MONITORING & OBSERVABILITY

### 6.1 Key Metrics

```python
# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

mcp_requests_total = Counter(
    'mcp_requests_total',
    'Total MCP requests',
    ['tool', 'client', 'status']
)

mcp_request_duration = Histogram(
    'mcp_request_duration_seconds',
    'MCP request duration',
    ['tool'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10]
)

mcp_rate_limited_total = Counter(
    'mcp_rate_limited_total',
    'Rate limited requests',
    ['client']
)

mcp_circuit_breaker_state = Gauge(
    'mcp_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half-open)',
    ['server']
)

mcp_active_connections = Gauge(
    'mcp_active_connections',
    'Active MCP connections',
    ['server']
)
```

### 6.2 Alerting Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: mcp-alerts
    rules:
    - alert: HighErrorRate
      expr: rate(mcp_requests_total{status="error"}[5m]) > 0.05
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "MCP error rate > 5% for {{ $labels.tool }}"
    
    - alert: HighLatency
      expr: histogram_quantile(0.95, mcp_request_duration_seconds) > 5
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "p95 latency > 5s for {{ $labels.tool }}"
    
    - alert: CircuitBreakerOpen
      expr: mcp_circuit_breaker_state > 0
      for: 30s
      labels:
        severity: critical
      annotations:
        summary: "Circuit breaker open for {{ $labels.server }}"
    
    - alert: RateLimitExhaustion
      expr: rate(mcp_rate_limited_total[5m]) > 100
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High rate limiting on {{ $labels.client }}"
```

---

## 7. COMPARISON: MCP vs RAG vs FUNCTION CALLING

| Dimension | MCP | RAG | Function Calling |
|-----------|-----|-----|-----------------|
| **Purpose** | Tool/context protocol | Knowledge retrieval | Model-specific tool invocation |
| **Data flow** | Bidirectional (read + write) | Read-only (retrieve) | Unidirectional (call + result) |
| **State** | Stateless per call | Stateless per query | Stateless |
| **Security** | Protocol-level sandboxing | Document-level access | API key scoping |
| **Latency** | 10ms-5s (varies by tool) | 200ms-2s | 100ms-5s |
| **Standardization** | Open standard | Architectural pattern | Provider-specific |
| **Discovery** | Runtime (`tools/list`) | Configuration | Schema definition |
| **Best for** | Agents that act | Agents that know | Agents on one provider |

### Can they be combined? **Yes.**

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMBINED ARCHITECTURE                          │
│                                                                   │
│  AI Agent                                                         │
│    │                                                              │
│    ├── MCP Tool: query_database()     → Database (write action)  │
│    ├── MCP Tool: send_email()         → Email (write action)     │
│    ├── MCP Tool: rag_query()          → RAG Pipeline             │
│    │    └── RAG internally uses:                                  │
│    │         ├── Vector Store (retrieval)                        │
│    │         └── LLM (generation)                                │
│    └── MCP Resource: rag://documents → Document inventory        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**MCP provides the standardized protocol for tool invocation.**
**RAG provides the knowledge retrieval pipeline.**
**Function calling is an alternative for single-provider scenarios.**

---

## 8. ROADMAP & FUTURE CONSIDERATIONS

| Capability | Current State | Coming Soon |
|-----------|--------------|-------------|
| **Streaming responses** | SSE for transport | Streaming tool results |
| **Bidirectional streaming** | Request-response only | Server push notifications |
| **Revocation** | Manual | Protocol-level revocation |
| **Federation** | Manual server composition | Cross-server discovery |
| **Caching standard** | Application-level | Protocol-level cache hints |
| **WebSocket transport** | SSE + HTTP POST | Full-duplex WebSocket |

---

> **End of MCP Module** — Covers architecture, protocol mechanics, implementation, interview questions, and production deployment.
