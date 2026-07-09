# 🎯 MCP — Interview Questions & Transcript

> **Principal Software Engineer level | Production-grade technical interview simulation**

---

## Interview Context

- **Interviewer:** Principal Software Engineer — deeply pragmatic, skeptical of architectural hype, intensely focused on security boundaries, protocol overhead, and systemic failure modes.
- **Candidate:** Staff Software Engineer — has built, deployed, and scaled production-ready MCP implementations. Reasons from first principles, balances LLM capabilities with traditional backend engineering guardrails.

---

## Question 1: Fundamentals & Protocol Mechanics

**[Principal Engineer]:** *"Skip the elevator pitch. Tell me what MCP actually changes under the hood compared to traditional custom webhook architectures — I'm talking about the JSON-RPC plumbing, not the marketing."*

### 🎯 Answer

**[Staff Candidate]:** At the transport level, MCP replaces ad-hoc REST endpoints with a standardized JSON-RPC 2.0 bidirectional channel. The critical difference isn't the serialization format — it's the **discovery contract**.

With a custom webhook, you hardcode tool definitions into the system prompt:
```python
# Traditional approach — brittle, manual
system_prompt = """
Available tools:
- get_weather(city: string) -> returns temperature
- send_email(to: string, subject: string, body: string)
"""
```

MCP replaces this with a **runtime discovery handshake**:
```json
// Client sends: {"method": "tools/list", "id": 1}
// Server responds:
{
  "result": {
    "tools": [{
      "name": "get_weather",
      "inputSchema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"]
      }
    }]
  }
}
```

This has three concrete implications:

1. **Schema-driven validation at the protocol layer:** The server enforces parameter types, not the LLM prompt. If the LLM hallucinates `city: 123` as an integer, the JSON-RPC layer rejects it before execution — no SQL injection, no shell injection.

2. **Version coupling elimination:** In a custom webhook setup, updating a tool signature means updating every client's system prompt. With MCP, you bump the server, clients discover the new schema on next `initialize`.

3. **Transport abstraction:** The same protocol primitives work over stdio (sub-millisecond IPC for local agents) and SSE (remote microservices). You don't rewrite the tool logic — you change the transport adapter.

---

## Question 2: Building a Custom MCP Server

**[Principal Engineer]:** *"Walk me through building an MCP server that wraps an internal PostgreSQL database. I want to hear about schema discovery, context truncation, and what happens when the LLM asks for a 50MB table dump."*

### 🎯 Answer

**[Staff Candidate]:** Let me start with the architecture, then address the failure modes.

**Server skeleton:**
```python
from mcp.server.fastmcp import FastMCP
import psycopg2

mcp = FastMCP("db-connector")

@mcp.tool()
def query_database(sql: str, max_rows: int = 100) -> str:
    """Execute a read-only SQL query against the analytics database.
    
    Args:
        sql: SQL SELECT query (read-only enforced via database user permissions)
        max_rows: Maximum rows to return (default 100, max 1000)
    """
    # Read-only user with SELECT-only grants
    conn = psycopg2.connect("dbname=analytics user=ro_user")
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchmany(max_rows)
    return format_as_table(columns, rows)

@mcp.resource("database://schema/tables")
def list_tables() -> str:
    """List all available tables in the analytics database."""
    conn = psycopg2.connect("dbname=analytics user=ro_user")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name, table_rows, engine 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        return format_as_table(...)
```

**Context truncation strategy:**
```python
MAX_TOKENS = 4000  # Leave room for conversation + reasoning

def truncate_result(result: str, max_tokens: int = MAX_TOKENS) -> str:
    """Token-aware truncation with semantic summarization."""
    tokens = estimate_tokens(result)
    
    if tokens <= max_tokens:
        return result
    
    # Try row reduction first
    rows = parse_rows(result)
    if len(rows) > 10:
        return format_as_table(rows[:10]) + \
               f"\n... and {len(rows) - 10} more rows (truncated)"
    
    # For large text blobs, semantic chunking + summary
    chunks = semantic_chunk(result, chunk_size=500)
    summary = llm.summarize(chunks)
    return f"[Summarized from {tokens} tokens]\n{summary}"
```

**Handling the 50MB table dump:**

Three-layer defense:
1. **Database level:** `max_rows` parameter capped at 1000 on the server
2. **Protocol level:** Tool schema enforces `max_rows` as integer with maximum constraint
3. **Application level:** Token-aware truncation with row limit

If the LLM ignores the cap and tries to loop through pages, we've got rate limiting and a max-consecutive-calls circuit breaker.

---

## Question 3: Enterprise Security & Auth

**[Principal Engineer]:** *"I'm skeptical. MCP servers run as local processes with full filesystem access. How do you prevent an LLM from hallucinating `rm -rf /` through an exposed tool? And how do you handle user authentication when MCP is fundamentally stateless over JSON-RPC?"*

### 🎯 Answer

**[Staff Candidate]:** You're right to be skeptical. This is where most MCP implementations fail in enterprise settings.

**RCE Prevention — Defense in Depth:**

```python
# Layer 1: Command allowlist (not blocklist)
ALLOWED_COMMANDS = frozenset({"ls", "cat", "grep", "head", "tail", "wc"})

@mcp.tool()
def execute_command(command: str, args: List[str]) -> str:
    """Execute a whitelisted system command."""
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"Command '{command}' not in allowlist")
    
    # Layer 2: Argument sanitization
    sanitized_args = [shlex.quote(arg) for arg in args]
    
    # Layer 3: Subprocess isolation
    result = subprocess.run(
        [command] + sanitized_args,
        capture_output=True,
        timeout=10,
        cwd="/safe/working/directory",
        env={"PATH": "/usr/local/bin:/usr/bin"}  # Restricted PATH
    )
    return result.stdout.decode()
```

**Layer 4 — Sandboxing:** Run the MCP server in a container:
```dockerfile
FROM python:3.12-slim
RUN useradd -m mcpserver
USER mcpserver
COPY --chown=mcpserver:mcp server.py .
CMD ["python", "server.py"]
```

**Authentication & State Propagation:**

MCP is stateless at the transport level, but you can layer identity on top:

```python
from dataclasses import dataclass
from typing import Optional
import jwt

@dataclass
class AuthenticatedContext:
    user_id: str
    org_id: str
    roles: List[str]
    session_id: str

class AuthMiddleware:
    """Validates JWT from the initialization metadata."""
    
    async def validate_init(self, client_info: dict) -> AuthenticatedContext:
        token = client_info.get("metadata", {}).get("authorization")
        if not token:
            raise PermissionError("Missing auth token")
        
        decoded = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
        return AuthenticatedContext(
            user_id=decoded["sub"],
            org_id=decoded["org_id"],
            roles=decoded.get("roles", []),
            session_id=decoded["jti"]
        )
```

**Row-level security:**
```python
@mcp.tool()
def query_customer_data(customer_id: str) -> str:
    """Query customer data. Automatically scoped to authenticated user's org."""
    ctx = get_current_context()  # From auth middleware
    if not has_permission(ctx, "customer:read", customer_id):
        return "Access denied: insufficient permissions"
    
    # The SQL automatically filters by org_id
    rows = db.query("SELECT * FROM customers WHERE org_id = %s", ctx.org_id)
    return format_results(rows)
```

---

## Question 4: Production Rate Limiting & Backpressure

**[Principal Engineer]:** *"An AI agent enters an infinite loop, calling your MCP tool, getting an error, and retrying. How do you stop it from DDoS-ing your internal database?"*

### 🎯 Answer

**[Staff Candidate]:** Three mechanisms — rate limiting, circuit breakers, and backpressure signaling.

**Rate Limiting (Token Bucket per Client):**

```python
import time
from collections import defaultdict
from threading import Lock

class MCPRateLimiter:
    def __init__(self, rate: int = 10, burst: int = 20, window: int = 1):
        self.rate = rate          # 10 requests/second
        self.burst = burst        # 20 burst capacity
        self.window = window      # 1 second window
        self.clients = defaultdict(lambda: {"tokens": burst, "last_refill": time.time()})
        self.lock = Lock()
    
    def check_rate_limit(self, client_id: str) -> bool:
        with self.lock:
            client = self.clients[client_id]
            now = time.time()
            elapsed = now - client["last_refill"]
            client["tokens"] = min(
                self.burst,
                client["tokens"] + elapsed * self.rate
            )
            client["last_refill"] = now
            
            if client["tokens"] < 1:
                return False  # Rate limited
            client["tokens"] -= 1
            return True

@mcp.tool()
def query_database(sql: str) -> str:
    client_id = get_current_client_id()
    if not rate_limiter.check_rate_limit(client_id):
        raise MCPRateLimitError(
            "Rate limit exceeded. Retry after 1 second.",
            retry_after=1
        )
    # Execute query...
```

**Circuit Breaker (Prevents Cascading Failures):**

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 30):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._probe_in_flight = False  # Tracks whether a HALF_OPEN probe is in progress
    
    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "HALF_OPEN"
                self._probe_in_flight = False  # Reset probe flag
            else:
                raise CircuitBreakerOpen("Service temporarily unavailable")
        
        # ── HALF_OPEN guard: only one probe request at a time ──
        if self.state == "HALF_OPEN":
            if self._probe_in_flight:
                raise CircuitBreakerOpen(
                    "Circuit breaker is HALF_OPEN — "
                    "a probe request is already in flight"
                )
            self._probe_in_flight = True
        
        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                # Probe succeeded — reset to CLOSED
                self.state = "CLOSED"
                self.failure_count = 0
                self._probe_in_flight = False
            return result
        except Exception:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == "HALF_OPEN":
                # Probe failed — back to OPEN immediately
                self.state = "OPEN"
                self._probe_in_flight = False
            elif self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            raise
```

**Backpressure via MCP Error Objects:**

```json
// Server returns structured error instead of HTTP 429
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32000,
    "message": "Rate limit exceeded",
    "data": {
      "retry_after_ms": 1000,
      "limit": 10,
      "window_seconds": 1
    }
  },
  "id": 42
}
```

The key insight: return **MCP-compatible errors** (not HTTP status codes) so the LLM host can parse and handle them gracefully — wait, retry, or ask the user.

---

## Question 5: MCP + RAG Integration

**[Principal Engineer]:** *"You have a RAG pipeline with 100K documents. How do you expose it as an MCP server? What tools do you expose, and how do you handle the latency when the LLM needs to do retrieval + generation through the protocol?"*

### 🎯 Answer

**[Staff Candidate]:** You expose the RAG pipeline as a set of MCP tools with different granularity levels, and you design for the latency amplification problem from the start.

**RAG MCP Server Design:**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rag-server")

@mcp.tool()
def rag_query(question: str, top_k: int = 5) -> str:
    """Complete RAG query: retrieve context + generate answer.
    
    This is a high-level tool optimized for simple Q&A.
    Latency: ~1-2 seconds (retrieval + generation)
    """
    chunks = vector_store.search(question, top_k)
    context = assemble_context(chunks)
    answer = llm.generate(context, question)
    return f"Answer: {answer}\n\nSources:\n{format_sources(chunks)}"

@mcp.tool()
def retrieve_documents(question: str, top_k: int = 10) -> str:
    """Retrieve relevant document chunks without generating an answer.
    
    Use this when you need to inspect the source material directly.
    Latency: ~100ms (retrieval only)
    """
    chunks = vector_store.search(question, top_k)
    return format_chunks_with_scores(chunks)

@mcp.resource("rag://stats")
def get_rag_stats() -> str:
    """Status of the RAG system: indexed documents, collection size, etc."""
    return f"Documents: {vector_store.count()}\nLast indexed: {vector_store.last_indexed()}"

@mcp.tool()
def index_document(file_path: str) -> str:
    """Index a new document into the RAG knowledge base.
    
    Parses the document, chunks it, embeds it, and stores in vector DB.
    Latency: ~5-10 seconds per document
    """
    chunks = document_loader.load_and_chunk(file_path)
    vector_store.add_documents(chunks)
    return f"Indexed {len(chunks)} chunks from {file_path}"
```

**Latency Management Strategy:**

The amplification problem is real — if an LLM calls 3 tools sequentially to answer one question, and each takes 1-2 seconds, you're looking at 3-6 seconds of wall-clock time.

Solutions:
1. **Provide high-level tools** (`rag_query`) that do retrieval+generation in one call — minimizes round-trips
2. **Parallel tool execution** — the host can call `retrieve_documents` and get status concurrently
3. **Caching** — cache frequent queries at the MCP server level
4. **Streaming responses** — return partial results via SSE while generating

```python
# Caching layer
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_rag_query(question: str, top_k: int = 5) -> str:
    """Cache identical questions for 5 minutes."""
    return execute_rag_query(question, top_k)
```

**Trade-off:** The `rag_query` tool is convenient but opaque — the LLM can't see the retrieved documents, which means it can't reason about retrieval quality. Provide both `rag_query` (fast, simple) and `retrieve_documents` (transparent, debuggable).

---

## Question 6: MCP vs Function Calling vs Custom APIs

**[Principal Engineer]:** *"When would you choose MCP over OpenAI function calling? And when would you skip both and just build a REST API?"*

### 🎯 Answer

**[Staff Candidate]:** 

| Use Case | MCP | OpenAI Function Calling | Custom REST API |
|----------|-----|----------------------|-----------------|
| **Single LLM provider** | Overkill | ✅ Best choice | Viable |
| **Multi-LLM orchestration** | ✅ Best choice | ❌ Provider-locked | ❌ Adapters needed |
| **Local/desktop agent** | ✅ Stdio transport | ❌ HTTP only | ❌ Heavy |
| **Complex tool composition** | ✅ Resources + Prompts | ❌ Tools only | ❌ Manual context |
| **High-throughput API** | ⚠️ Protocol overhead | ⚠️ Provider limits | ✅ Full control |
| **Simple CRUD** | ❌ Too much abstraction | ❌ Over-engineered | ✅ Simple endpoints |

**Decision framework:**
- **Choose MCP when:** You need a standardized way to connect AI agents to multiple tools/sources, especially across different LLM providers or for local-first architectures.
- **Choose Function Calling when:** You're building exclusively on OpenAI, you don't need resources/prompts, and you want the tightest integration with GPT models.
- **Choose Custom REST API when:** You're building a traditional backend service that happens to be called by an AI. No protocol overhead, full control, battle-tested.

**Concrete example:**
- **MCP:** An internal developer tool that needs to query databases, read logs, check deployment status, and send notifications — all through a local CLI agent.
- **Function Calling:** A chatbot that needs to look up customer orders using OpenAI's API — single provider, simple tools.
- **REST API:** A payment processing service — needs idempotency, retry logic, webhooks, and audit logging. MCP adds no value here.

---

## Question 7: Advanced Failure Modes

**[Principal Engineer]:** *"Your MCP server goes down. The LLM keeps retrying. Your database connection pool is exhausted. Walk me through the failure cascade and your mitigations."*

### 🎯 Answer

**[Staff Candidate]:** Here's the cascade and mitigation at each level:

**Failure Cascade:**

```
1. LLM calls tool → MCP Server is down (connection refused)
2. LLM retries after 1 second → same result
3. LLM retries 5 more times → each retry creates a new connection attempt
4. Connection attempts pile up → OS socket backlog fills
5. Server comes back up → immediately hit by 6 pending requests → connection pool exhausts
6. Database connection pool exhausts → all subsequent queries fail → cascading failure
```

**Mitigations:**

```python
# Level 1: Exponential backoff in the client
class MCPRetryHandler:
    async def call_with_backoff(self, tool_name, args, max_retries=3):
        for attempt in range(max_retries):
            try:
                return await self.session.call_tool(tool_name, args)
            except (ConnectionError, TimeoutError) as e:
                if attempt == max_retries - 1:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait)

# Level 2: Connection pool management on the server
class ConnectionPool:
    def __init__(self, max_connections=10):
        self.semaphore = asyncio.Semaphore(max_connections)
    
    async def acquire(self):
        if not self.semaphore.locked():
            return await self.semaphore.acquire()
        raise PoolExhausted("All connections in use. Try again later.")

# Level 3: Health check endpoint and circuit breaker
@mcp.resource("health://status")
def health_check() -> str:
    """Returns OK only if all downstream dependencies are healthy."""
    db_ok = check_database_connectivity()
    cache_ok = check_cache_connectivity()
    if not db_ok or not cache_ok:
        return "DEGRADED"
    return "OK"
```

---

## Question 8: MCP in a Multi-Tenant Environment

**[Principal Engineer]:** *"You need to serve 100 different teams with one MCP server. Each team has different database schemas and different access levels. How do you design the MCP server to handle multi-tenancy without leaking data?"*

### 🎯 Answer

**[Staff Candidate]:** Multi-tenancy in MCP requires tenant-aware routing at every layer — transport, initialization, and tool execution.

**Design:**
```python
# Tenant-aware resource URIs
@mcp.resource("database://{tenant_id}/schema/tables")
def list_tenant_tables(tenant_id: str) -> str:
    """List tables scoped to the authenticated tenant."""
    ctx = get_current_context()
    if ctx.tenant_id != tenant_id:
        return "Access denied: tenant mismatch"
    
    # Each tenant has a separate schema in PostgreSQL
    conn = get_tenant_connection(tenant_id)
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                   f"WHERE table_schema = %s", (tenant_id,))
        return format_tables(cur.fetchall())

# Tenant-aware tool routing
@mcp.tool()
def query_tenant_data(table: str, filters: dict) -> str:
    """Query data from the authenticated tenant's schema."""
    ctx = get_current_context()
    conn = get_tenant_connection(ctx.tenant_id)
    # All queries automatically scoped to tenant schema
    return execute_safe_query(conn, table, filters, ctx.tenant_id)
```

**Key Multi-Tenant Principles:**
1. **Connection pooling per tenant** — separate pools prevent cross-tenant impact
2. **Resource URIs as tenant boundaries** — `database://{tenant_id}/...` namespacing
3. **Auth at initialization** — JWT embeds tenant context
4. **Rate limiting per tenant** — one noisy tenant doesn't degrade others
5. **Query rewriting** — always inject `WHERE tenant_id = :ctx.tenant_id`

---

## Evaluation Rubric

| Criteria | Expected | Excellent |
|----------|----------|-----------|
| **Protocol mechanics** | Can explain JSON-RPC lifecycle | Deep knowledge of transport trade-offs, capability negotiation |
| **Security** | Mentions schema validation | Layered defense: allowlist, sandboxing, JWT propagation, row-level security |
| **Production concerns** | Discusses rate limiting | Circuit breakers, backpressure signaling, exponential backoff, health endpoints |
| **RAG integration** | Can describe MCP + RAG | Multi-level tools (high-level vs transparent), caching, latency management |
| **Multi-tenancy** | Tenant-aware routing | Connection isolation per tenant, query rewriting, resource namespacing |
| **Failure modes** | Basic error handling | Failure cascade analysis, defense in depth at every layer |
