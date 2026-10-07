# 🏗️ MCP Production Architecture — Deployment, Security & Tradeoffs

> **Target:** Staff/Principal Engineer | **Focus:** running remote MCP servers in production: deployment, auth, security, scale, observability. Current as of spec **2026-07-28**.

!!! tip "30-second answer"
    A remote MCP server is a stateless HTTP service (since 2026-07-28) that happens to speak JSON-RPC to AI hosts. Run it like any other: behind TLS and a gateway, horizontally scaled with round-robin load balancing, each replica an OAuth 2.1 resource server validating audience-bound tokens on every request. What's different from a normal API is the caller: an LLM steerable by prompt injection. So add least-privilege tools, human confirmation for side effects, output-size limits, per-user rate limits and full audit of tool calls.

---

## 1. PRODUCTION DEPLOYMENT ARCHITECTURE

### 1.1 High-Level Architecture

```
                      ┌───────────────────────────┐
                      │  MCP hosts (Claude, IDEs, │
                      │  internal agents)         │
                      └─────────────┬─────────────┘
                                    │ Streamable HTTP, POST /mcp
                                    │ Authorization: Bearer <token>
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                       GATEWAY / LOAD BALANCER                     │
│  - TLS termination                                                │
│  - Coarse rate limits by user/tenant (429)                        │
│  - Routing on Mcp-Method / Mcp-Name headers (no body parsing)     │
│  - Round-robin: no sticky sessions needed (2026-07-28)            │
│  - Don't buffer SSE responses                                     │
└───────────────────────────────────────────────────────────────────┘
            │                       │                       │
            ▼                       ▼                       ▼
┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
│  MCP Server A      │ │  MCP Server B      │ │  MCP Server C      │
│  (database)        │ │  (ticketing API)   │ │  (RAG)             │
│  each replica:     │ │                    │ │                    │
│  - validates token │ │  - token exchange  │ │  - ACL-filtered    │
│    (aud, exp, iss) │ │    for downstream  │ │    retrieval       │
│  - tool-level authz│ │    API calls       │ │                    │
│  - bounded DB pool │ │                    │ │                    │
└────────────────────┘ └────────────────────┘ └────────────────────┘
            │                       │                       │
            └──────── OpenTelemetry traces, metrics, audit logs ───────┘

        Authorization server (your IdP): issues tokens for each MCP server's
        resource URI; advertised via /.well-known/oauth-protected-resource
```

The gateway may also validate tokens, but each server must still check that the token's **audience is itself**. A gateway that accepts any valid company token and forwards it lets a token minted for one server be replayed against another.

**What changed with 2026-07-28:** older Streamable HTTP servers that minted `Mcp-Session-Id`, or sent requests back to the client on an SSE stream, needed sticky routing or a shared session store. With sessions and server-initiated requests gone (MRTR instead), any replica can serve any request. Servers still speaking 2025-era clients may need both behaviours during the migration.

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
      maxUnavailable: 0
  selector:
    matchLabels:
      app: mcp-rag-server
  template:
    metadata:
      labels:
        app: mcp-rag-server
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile: { type: RuntimeDefault }
      containers:
      - name: mcp-server
        image: myregistry/mcp-rag-server:1.4.2   # pin a version (or digest), never :latest
        env:
        - name: MCP_TRANSPORT
          value: streamable-http
        - name: RAG_PORT
          value: "8000"
        ports:
        - containerPort: 8000
          name: http
        resources:
          requests: { memory: "1Gi", cpu: "500m" }
          limits:   { memory: "2Gi" }            # embedding models are memory-hungry
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities: { drop: ["ALL"] }
        livenessProbe:                           # process alive; must not check dependencies
          httpGet: { path: /healthz, port: http }
          periodSeconds: 20
        readinessProbe:                          # can serve: model loaded, vector store reachable
          httpGet: { path: /readyz, port: http }
          periodSeconds: 10
        startupProbe:                            # model loading can take a while
          httpGet: { path: /healthz, port: http }
          failureThreshold: 30
          periodSeconds: 5
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcp-rag-server-hpa
  namespace: ai-engineering
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
      target: { type: Utilization, averageUtilization: 70 }
  # A per-pod request-rate metric needs a custom-metrics adapter
  # (e.g. Prometheus Adapter or KEDA) exposing mcp_requests_per_second.
  - type: Pods
    pods:
      metric: { name: mcp_requests_per_second }
      target: { type: AverageValue, averageValue: "100" }
```

The SDK does not provide `/healthz` and `/readyz`; add them with `@mcp.custom_route("/healthz", methods=["GET"])`. With a read-only root filesystem, mount an `emptyDir` for anything that writes (model caches, temp files). Bind to `0.0.0.0` inside the container and keep the Service internal; the "bind to 127.0.0.1" rule is for servers on a user's machine.

### 1.3 Docker Setup

```dockerfile
FROM python:3.13-slim

RUN useradd --create-home --uid 10001 mcp
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=mcp:mcp servers/ servers/
COPY --chown=mcp:mcp common/ common/

USER mcp
EXPOSE 8000
ENV MCP_TRANSPORT=streamable-http

# Kubernetes ignores HEALTHCHECK; it's for plain Docker/Compose.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["python", "-m", "servers.rag_server"]
```

`USER` gives you a non-root process, not a read-only filesystem; that comes from the runtime (`--read-only`, or `readOnlyRootFilesystem` in Kubernetes).

---

## 2. SECURITY ARCHITECTURE

### 2.1 Threat Model

| Threat | Vector | Impact | Mitigation |
|--------|--------|--------|------------|
| **Indirect prompt injection** | Instructions hidden in data a tool returns (web page, email, ticket) | Model takes unintended actions or leaks data | Treat tool output as untrusted; least-privilege tools; confirm side effects with the user; avoid giving one unattended agent private data, untrusted input and an outbound channel together |
| **Tool poisoning / rug pull** | Malicious text in a tool description, or a definition that changes after approval | Model follows the attacker | Allow-list and pin servers; hash approved definitions; re-approve on change |
| **Command / SQL / path injection** | Model-supplied arguments | Server or data compromise | Parameterised queries, allow-lists, `--` before user args, canonicalise paths against a root, no shell |
| **Token passthrough / confused deputy** | Server forwards the client's token, or an OAuth proxy reuses consent | Privilege escalation, audit gaps | Validate audience; never forward tokens; token exchange for downstream calls; per-client consent in proxies |
| **SSRF** | Tool fetches a model-supplied URL | Access to metadata service / internal network | Egress allow-list; block private ranges after DNS resolution |
| **DNS rebinding** | Web page reaches a local HTTP server | Local server driven by a website | Validate `Origin` (403), bind local servers to 127.0.0.1, require auth |
| **Data exfiltration across tenants** | Tenant chosen by the model or a shared cache | Data leak | Tenant from token only; RLS; tenant in every cache key |
| **Resource exhaustion** | Looping agents, huge outputs | Degradation, cost | Per-user rate limits, timeouts, output caps, host tool-call budgets |
| **Supply chain** | Unreviewed `npx`/`uvx` servers, vulnerable SDKs | Code execution as the user | Internal registry, pinned versions, dependency scanning, sandboxed stdio servers |

### 2.2 Defense in Depth

```
Layer 1: Network
├── Remote servers behind TLS; private subnets where possible
├── Egress allow-lists (stops SSRF and exfiltration)
└── Origin validation; local servers bound to 127.0.0.1

Layer 2: Authentication & Authorization
├── OAuth 2.1: server is a resource server; bearer token on EVERY request
├── Validate signature, exp, iss and aud (= this server's canonical URI, RFC 8707)
├── Scopes per tool family; 403 + WWW-Authenticate scope="..." for step-up
├── Tool-level RBAC, row-level security from token claims
└── No token passthrough; token exchange (RFC 8693) for downstream APIs

Layer 3: Input & Output Handling
├── JSON Schema on inputs, re-validated in code
├── Allow-lists, parameterised queries, canonicalised paths
├── Output caps; no raw stack traces or driver errors to the model
└── Treat all tool output as untrusted when it flows back to the model

Layer 4: Execution Sandboxing
├── Containers: non-root, read-only root FS, all capabilities dropped, seccomp
├── CPU/memory limits, per-call timeouts
└── stdio servers on laptops: run in a sandbox or container where the host supports it

Layer 5: Human in the loop
├── destructiveHint tools require confirmation in the host
└── Elicitation (input_required) for "are you sure?" inside the server

Layer 6: Observability & Audit
├── Every tool call: who, tenant, tool, redacted args, outcome, latency
├── Alert on unusual tool-usage patterns
└── Trace context via _meta (traceparent) end to end
```

### 2.3 Auth Middleware Implementation

The repo's [`common/auth.py`](common/index.md) shows the pieces. The two mistakes it avoids are worth naming in an interview:

```python
# common/auth.py (abridged)
_current: contextvars.ContextVar[Optional[AuthContext]] = contextvars.ContextVar("mcp_auth_context", default=None)


def authenticate_bearer(token: str) -> AuthContext:
    payload = pyjwt.decode(
        token, key,
        algorithms=[JWT_ALGORITHM],        # pinned: never trust the token's own "alg" header
        audience=JWT_AUDIENCE or None,     # this server's resource URI
        issuer=JWT_ISSUER or None,
        options={"require": ["exp", "sub"]},
    )
    scopes = payload.get("scope", "")
    return AuthContext(user_id=payload["sub"], tenant_id=payload.get("tenant_id", "default"),
                       permissions=payload.get("permissions", scopes.split() if scopes else []))


def require_permission(permission: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if permission not in get_current_context().permissions:
                raise AuthorizationError(f"Missing required permission: '{permission}'")
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Usage: the MCP decorator must be OUTERMOST, so the checked wrapper is what gets registered.
@mcp.tool()
@require_permission("database:read")
def query_database(sql: str) -> str:
    ...
```

1. **Decorator order.** With `@require_permission` *above* `@mcp.tool()`, the SDK registers the unwrapped function at decoration time and the permission check never runs for MCP calls. It's a silent auth bypass.
2. **Per-request identity.** A module-level "current user" is shared by every concurrent request on an async server, so one caller's identity leaks into another's call. A `ContextVar` set per request (sync tools run on worker threads, which copy the context) keeps them separate.

In the SDK, plug validation in as a `TokenVerifier` and declare the authorization server and resource URL in `AuthSettings`; the SDK then serves `/.well-known/oauth-protected-resource` (RFC 9728) and answers unauthenticated requests with `401` and `WWW-Authenticate: Bearer resource_metadata="..."`.

**Client side of the flow (for the interview):** the client gets a 401, reads the protected-resource metadata to find the authorization server, registers (pre-registered client, a **Client ID Metadata Document** URL as `client_id`, or the now-deprecated Dynamic Client Registration), runs authorization code + **PKCE** with the `resource` parameter set to the server's URI, validates `iss` in the response (RFC 9207), and sends the token on every request.

---

## 3. ENTERPRISE CONSTRAINTS & COMPLIANCE

### 3.1 Audit Requirements

```python
# common/audit.py (sketch)
import json
import logging
import time
from datetime import datetime, timezone
from functools import wraps

audit_logger = logging.getLogger("mcp.audit")
REDACT = {"password", "token", "secret", "ssn", "card_number"}


def redact(params: dict) -> dict:
    return {k: ("[REDACTED]" if k.lower() in REDACT else v) for k, v in params.items()}


def audited(func):
    """Audit every call. Place under @mcp.tool(), above permission checks."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        ctx = get_current_context()
        start = time.perf_counter()
        outcome = "ok"
        try:
            return func(*args, **kwargs)
        except Exception as e:
            outcome = f"error:{type(e).__name__}"   # the type, not the message (may contain data)
            raise
        finally:
            audit_logger.info(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),   # utcnow() is deprecated since 3.12
                "tool": func.__name__,
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
                "token_id": ctx.token_id,
                "params": redact(kwargs),
                "outcome": outcome,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }, default=str))
    return wrapper
```

Log metadata and redacted arguments, not full results: results are where PII lives. Ship audit logs to append-only storage (object lock / WORM) if regulators need immutability.

### 3.2 Compliance Checklist

| Requirement | What it means for an MCP server | Evidence |
|-------------|---------------|--------------|
| **SOC 2** | Access control, change management, audit logging of tool calls | Access reviews, audit-log retention |
| **GDPR** | Data minimisation in tool outputs and logs; deletion must reach caches, vector indexes and logs | Data-flow map, deletion runbooks |
| **HIPAA** | PHI only in covered services; BAAs with the cloud **and LLM provider**; minimum necessary | BAAs, encryption at rest/in transit, access logs |
| **SOX** | Segregation of duties for anything touching financial data; immutable audit trail | Approval workflows for write tools |
| **PCI DSS** | Card data never enters prompts, tool params or logs | Tokenisation before the tool boundary |

The often-missed point: tool outputs go to the **model provider**. Whatever a tool returns is data you've sent to a third party, so data-processing agreements and residency apply.

---

## 4. SCALABILITY & PERFORMANCE

### 4.1 Latency Budget

Illustrative orders of magnitude, not benchmarks; measure your own:

| Component | Typical cost | Notes |
|---|---|---|
| Token validation | sub-millisecond (cached JWKS) | Fetching JWKS per request would add a network round trip |
| Gateway + TLS | ~1–5 ms in-region | More across regions |
| Simple tool (calculator, cache hit) | ~1–10 ms | |
| Database query | tens to hundreds of ms | Dominated by the query |
| Retrieval (hybrid + rerank) | ~100–500 ms | Reranker usually the largest part |
| Server-side LLM generation | seconds | Why retrieval-first tools beat answer tools |
| **The model deciding to call the tool** | often seconds | The biggest cost is usually the extra LLM turn per tool call, not MCP |

`tools/list` isn't on the per-call path: hosts fetch it once and cache it (2026-07-28 adds `ttlMs` for exactly that).

### 4.2 Connection Management

With stateless Streamable HTTP there is no MCP connection to manage per client; the resources to bound are your **downstream** ones:

- **Database pools:** per-replica pool × max replicas < database `max_connections`; use PgBouncer when the fleet scales out.
- **Concurrency limits with load shedding:** a semaphore per expensive dependency, with a short acquire timeout that returns "busy, retry shortly" rather than queueing forever (see [Question 7](02_MCP_INTERVIEW_QUESTIONS.md#question-7-advanced-failure-modes)).
- **Long-lived streams:** each `subscriptions/listen` stream (and each in-flight SSE response) holds a connection; set idle timeouts and keep-alives, and size the async server's connection limits for them.
- **HTTP clients to downstream APIs:** one shared, pooled client per process, with timeouts on every call.

### 4.3 Caching Strategy

| Cache level | What | TTL | Invalidation |
|------------|------|-----|-------------|
| **Tool/resource/prompt lists** | `*/list` results, client side | Server's `ttlMs` hint (2026-07-28) | `list_changed` notification on a `subscriptions/listen` stream |
| **Query results** | Frequent read-only queries | Minutes | TTL; include tenant + permissions in the key |
| **Retrieval results** | Search hits | Minutes | Index version in the key |
| **Query embeddings** | Embedding of normalised query text | Hours or more | Embedding-model version in the key |
| **JWKS / token introspection** | Signing keys, introspection results | Per `Cache-Control`; short for introspection | Key rotation (`kid` miss → refetch) |

`cacheScope: "private"` on list results tells shared intermediaries not to cache a per-user tool list.

---

## 5. USE CASES & TRADEOFFS

### 5.1 When to Use MCP

| Use Case | Why MCP | Example |
|----------|---------|---------|
| **Developer tooling** | stdio servers run locally with the user's context | git, filesystem, IDE, database CLIs for coding agents |
| **Internal platform for agents** | One auth and audit model for every team's tools | "query logs", "deploy status", "open incident" |
| **SaaS integrations** | Ship one server; every major host can use it | Ticketing, CRM, docs products publishing remote MCP servers |
| **Model portability** | Tools aren't tied to one provider's function format | Swap models without rewriting integrations |
| **RAG + actions** | Resources and search tools for knowledge, tools for actions | Support agent: KB search + ticket creation |

### 5.2 When NOT to Use MCP

| Use Case | Why not | Better alternative |
|----------|---------|-------------------|
| **Service-to-service APIs** | No model in the loop; MCP's model-facing features add nothing | REST/gRPC |
| **High-throughput data pipelines** | Wrong shape: request/response JSON for an LLM, not bulk transfer | Batch jobs, Kafka, gRPC streaming |
| **Real-time media** | Request/response; no media streaming | WebRTC, WebSockets |
| **Tools that only live inside one app** | An extra process and protocol for no reuse | In-process function calling |
| **Public browser-facing APIs** | Built for AI hosts, not browsers | REST + OpenAPI |

### 5.3 Tradeoff Analysis

| | MCP | Function calling (in-app) | REST API |
|---|---|---|---|
| Extra moving parts | A server process/service | None | A service |
| Works across hosts and models | ✅ | ❌ (per app, per provider format) | Needs an adapter per host |
| Runtime discovery | ✅ | Tools passed per request | ❌ (docs/OpenAPI) |
| Local execution (stdio) | ✅ | ✅ (it's your process) | ❌ |
| Standard auth for remote | OAuth 2.1 profile | Your app's concern | Anything |
| Model-facing features (errors the model reads, elicitation) | ✅ | Partly | ❌ |
| Maturity | Young; spec changed materially in 2025–26 | Mature | Very mature |
| Ecosystem | Large and growing (official registry, every major host) | Large | Massive |

---

## 6. MONITORING & OBSERVABILITY

### 6.1 Key Metrics

```python
from prometheus_client import Counter, Gauge, Histogram

mcp_requests_total = Counter(
    "mcp_requests_total", "MCP requests",
    ["method", "tool", "outcome"],          # outcome: ok | tool_error | protocol_error
)
mcp_request_duration = Histogram(
    "mcp_request_duration_seconds", "MCP request duration",
    ["method", "tool"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
)
mcp_rate_limited_total = Counter("mcp_rate_limited_total", "Rate-limited requests", ["tenant"])
mcp_circuit_breaker_state = Gauge(
    "mcp_circuit_breaker_state", "0=closed, 1=open, 2=half-open", ["dependency"],
)
mcp_output_bytes = Histogram(
    "mcp_tool_output_bytes", "Size of tool results sent to the model", ["tool"],
    buckets=[1e3, 1e4, 5e4, 1e5, 5e5, 1e6],
)
```

Keep label cardinality bounded: tenant is usually fine, user ID usually isn't (put it in traces and logs). Tool-error rate is a quality signal as well as a health one: a spike after a description change often means the model is calling the tool wrongly.

### 6.2 Alerting Rules

```yaml
groups:
- name: mcp-alerts
  rules:
  - alert: MCPHighErrorRatio
    expr: |
      sum by (tool) (rate(mcp_requests_total{outcome!="ok"}[5m]))
        / sum by (tool) (rate(mcp_requests_total[5m])) > 0.05
    for: 5m
    labels: { severity: critical }
    annotations:
      summary: "MCP error ratio > 5% for {{ $labels.tool }}"

  - alert: MCPHighLatency
    expr: |
      histogram_quantile(0.95,
        sum by (le, tool) (rate(mcp_request_duration_seconds_bucket[5m]))) > 5
    for: 10m
    labels: { severity: warning }
    annotations:
      summary: "p95 latency > 5s for {{ $labels.tool }}"

  - alert: MCPCircuitBreakerOpen
    expr: max by (dependency) (mcp_circuit_breaker_state) == 1
    for: 1m
    labels: { severity: critical }
    annotations:
      summary: "Circuit breaker open for {{ $labels.dependency }}"
```

The ratio form matters: `rate(errors) > 0.05` alone means "more than 0.05 errors per second", not 5%. `histogram_quantile` needs the `_bucket` series, a `rate()`, and `le` kept in the aggregation.

---

## 7. COMPARISON: MCP vs RAG vs FUNCTION CALLING

These aren't alternatives at the same layer:

| Dimension | MCP | RAG | Function calling |
|-----------|-----|-----|-----------------|
| **What it is** | Protocol between hosts and tool/data servers | Pattern: retrieve relevant text, then generate | Model API feature: model emits structured tool calls |
| **Answers** | "How does the host reach the tool?" | "How does the model get the right knowledge?" | "How does the model ask for an action?" |
| **Standardised by** | Open spec (Agentic AI Foundation) | Nobody: an architecture | Each provider's API |
| **Discovery** | Runtime (`tools/list`) | N/A | Tools passed in each request |
| **Typical use** | Reusable integrations | Knowledge-grounded answers | Any tool use |

### Can they be combined? **Yes.**

```
┌──────────────────────────────────────────────────────────────────┐
│                     COMBINED ARCHITECTURE                        │
│                                                                  │
│  Model ──function call──► Host ──tools/call──► MCP servers       │
│                                                                  │
│    ├── ticketing server: create_ticket()      (write action)     │
│    ├── database server:  query()              (read)             │
│    └── RAG server:       search() / answer()                     │
│          └── internally: hybrid retrieval → rerank → (LLM)       │
│              resource: rag://documents/{id}                      │
└──────────────────────────────────────────────────────────────────┘
```

The model uses function calling to request tools, the host fulfils them over MCP, and one of those servers implements RAG.

---

## 8. ROADMAP & FUTURE CONSIDERATIONS

What recently landed, so you don't present it as future work:

| Capability | Status (Oct 2026) |
|---|---|
| Stateless protocol, no sessions | Done in 2026-07-28 |
| Protocol-level cache hints | Done: `ttlMs` / `cacheScope` on list and read results |
| Server push for changes | Done: `subscriptions/listen` |
| Server asks the user mid-call | Elicitation via MRTR (form and URL modes) |
| Long-running operations | Tasks extension (`io.modelcontextprotocol/tasks`), polling via `tasks/get` |
| Interactive UI in hosts | MCP Apps extension (`io.modelcontextprotocol/ui`) |
| Server discovery | Official MCP Registry (registry.modelcontextprotocol.io), a metadata registry; packages stay on npm/PyPI/OCI registries |
| Client registration | Client ID Metadata Documents preferred; Dynamic Client Registration deprecated |
| Deprecated, migrate away | HTTP+SSE transport; Roots, Sampling and Logging features |

Still open or evolving, and good discussion material: streaming partial tool results, fine-grained tool-level authorization standards, cross-server trust and namespacing in hosts, and governance of third-party server supply chains.

---

> **End of MCP Module** — Covers architecture, protocol mechanics, implementation, interview questions, and production deployment.
