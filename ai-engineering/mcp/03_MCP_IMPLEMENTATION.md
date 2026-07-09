# 🛠️ MCP Implementation — Building Custom Servers & RAG Integration

> **Target:** Principal Engineer | **Focus:** Production-ready MCP server code, schema design, RAG pipeline integration

---

## 1. PROJECT STRUCTURE

```
mcp-servers/
├── requirements.txt
├── servers/
│   ├── __init__.py
│   ├── calculator_server.py       # Simple math tools (tutorial)
│   ├── database_server.py         # PostgreSQL wrapper
│   └── rag_server.py              # RAG pipeline integration
├── clients/
│   ├── __init__.py
│   ├── claude_config.json         # Claude Desktop config
│   └── python_client.py           # Custom Python client
├── common/
│   ├── __init__.py
│   ├── rate_limiter.py            # Token bucket rate limiter
│   ├── circuit_breaker.py         # Circuit breaker pattern
│   └── auth.py                    # JWT/auth middleware
└── tests/
    ├── test_calculator.py
    └── test_rag_server.py
```

---

## 2. IMPLEMENTATION — CALCULATOR MCP SERVER

### 2.1 Basic Server

```python
# servers/calculator_server.py
"""
Simple calculator MCP server demonstrating core primitives.
Run: python -m servers.calculator_server
"""

from mcp.server.fastmcp import FastMCP
from typing import Optional

# Initialize server
mcp = FastMCP("Calculator")

# ── Tools ──

@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b

@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b

@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b. Returns error if b is zero."""
    if b == 0:
        raise ValueError("Division by zero is not allowed")
    return a / b

@mcp.tool()
def power(base: float, exponent: float) -> float:
    """Raise base to the power of exponent."""
    return base ** exponent

# ── Resources ──

@mcp.resource("calculator://constants")
def get_constants() -> str:
    """Common mathematical constants."""
    return """pi: 3.141592653589793
e: 2.718281828459045
tau: 6.283185307179586
phi: 1.618033988749895"""

# ── Prompts ──

@mcp.prompt()
def solve_equation(equation: str) -> str:
    """Create a prompt template for solving mathematical equations."""
    return f"""Solve the following mathematical equation step by step:

Equation: {equation}

Show your work:"""

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### 2.2 Testing the Server

```bash
# Using MCP Inspector
npx @anthropic/mcp-inspector python -m servers.calculator_server

# Custom test script
python -c "
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test():
    params = StdioServerParameters(
        command='python',
        args=['-m', 'servers.calculator_server']
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List tools
            tools = await session.list_tools()
            print('Tools:', [t.name for t in tools.tools])
            
            # Test add
            result = await session.call_tool('add', {'a': 5, 'b': 3})
            print(f'5 + 3 = {result.content[0].text}')
            
            # Test divide by zero
            try:
                await session.call_tool('divide', {'a': 1, 'b': 0})
            except Exception as e:
                print(f'Expected error: {e}')

asyncio.run(test())
"
```

---

## 3. IMPLEMENTATION — DATABASE MCP SERVER

### 3.1 Production-Ready Server

```python
# servers/database_server.py
"""
PostgreSQL database MCP server with security, rate limiting, and auth.
Run: python -m servers.database_server
"""

from mcp.server.fastmcp import FastMCP
from common.rate_limiter import MCPRateLimiter
from common.circuit_breaker import CircuitBreaker
from common.auth import AuthMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
from typing import Optional, List

# Configuration from environment
DB_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/analytics")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "1000"))
QUERY_TIMEOUT_SECONDS = int(os.environ.get("QUERY_TIMEOUT", "10"))

mcp = FastMCP("DatabaseConnector")
rate_limiter = MCPRateLimiter(rate=10, burst=20)
db_circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=30)


def get_connection():
    """Create a read-only database connection."""
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def execute_query(sql: str, params: Optional[List] = None, max_rows: int = 100):
    """Execute a read-only query with safety checks."""
    # Validate it's a SELECT statement
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT") and not sql_stripped.startswith("WITH"):
        raise ValueError("Only SELECT queries are allowed")
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchmany(min(max_rows, MAX_ROWS))
            return {
                "columns": columns,
                "rows": [dict(row) for row in rows],
                "total_returned": len(rows),
                "truncated": len(rows) >= min(max_rows, MAX_ROWS)
            }
    finally:
        conn.close()


@mcp.tool()
def query(sql: str, max_rows: int = 100) -> str:
    """Execute a read-only SQL query against the analytics database.
    
    Args:
        sql: SQL SELECT query (read-only queries only)
        max_rows: Maximum number of rows to return (default: 100, max: 1000)
    """
    # Rate limiting
    client_id = get_current_client_id()  # From auth middleware
    if not rate_limiter.check_rate_limit(client_id):
        raise MCPRateLimitError("Rate limit exceeded. Try again shortly.")
    
    # Circuit breaker
    return db_circuit_breaker.call(
        _execute_and_format, sql, int(min(max_rows, MAX_ROWS))
    )


def _execute_and_format(sql: str, max_rows: int) -> str:
    """Execute query and format result as string."""
    result = execute_query(sql, max_rows=max_rows)
    
    if not result["rows"]:
        return "Query returned no results."
    
    # Format as markdown table
    header = "| " + " | ".join(result["columns"]) + " |"
    separator = "| " + " | ".join(["---"] * len(result["columns"])) + " |"
    rows = []
    for row in result["rows"]:
        values = [str(row[col])[:100] for col in result["columns"]]
        rows.append("| " + " | ".join(values) + " |")
    
    output = header + "\n" + separator + "\n" + "\n".join(rows)
    
    if result["truncated"]:
        output += f"\n\n*Results truncated to {max_rows} rows. Use more specific query to narrow results.*"
    
    return output


@mcp.resource("database://schema/tables")
def list_tables() -> str:
    """List all tables in the public schema."""
    result = execute_query(
        "SELECT table_name, "
        "       pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size "
        "FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "ORDER BY pg_total_relation_size(quote_ident(table_name)) DESC"
    )
    return json.dumps(result, indent=2, default=str)


@mcp.resource("database://schema/table/{table_name}")
def describe_table(table_name: str) -> str:
    """Describe columns of a specific table."""
    result = execute_query(
        "SELECT column_name, data_type, is_nullable, "
        "       COALESCE(character_maximum_length::text, 'N/A') as max_length "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        [table_name]
    )
    return json.dumps(result, indent=2, default=str)


if __name__ == "__main__":
    print("Starting Database MCP Server...")
    mcp.run(transport="stdio")
```

---

## 4. IMPLEMENTATION — RAG MCP SERVER

### 4.1 Full RAG Integration

```python
# servers/rag_server.py
"""
RAG pipeline exposed as MCP server.
Combines document indexing, retrieval, and generation through the protocol.
"""

from mcp.server.fastmcp import FastMCP
from typing import Optional, List
import os
import time
from functools import lru_cache

# RAG components
from implementation.rag_pipeline import RAGPipeline
from implementation.embedding_service import SentenceTransformerEmbedding
from implementation.vector_store import ChromaVectorStore
from implementation.llm_service import LMStudioLLMService
from implementation.document_loader import TextFileLoader
from implementation.config import settings

mcp = FastMCP("RAGPipeline", port=8000)

# ── Initialize RAG Pipeline ──
pipeline = RAGPipeline(
    embedder=SentenceTransformerEmbedding(),
    store=ChromaVectorStore(),
    llm=LMStudioLLMService(),
    loader=TextFileLoader(),
)


# ── Tool: Complete RAG Query ──

@mcp.tool()
def rag_query(question: str, top_k: int = 5, temperature: float = 0.3) -> str:
    """Complete RAG query: retrieve context and generate an answer.
    
    Best for simple Q&A where you want a single, grounded answer.
    Includes source citations automatically.
    
    Args:
        question: The user's question to answer
        top_k: Number of document chunks to retrieve (1-10)
        temperature: LLM temperature (0.0-1.0, lower = more factual)
    """
    start = time.time()
    result = pipeline.query(question, top_k=top_k, temperature=temperature)
    elapsed = time.time() - start
    
    # Format answer with citations
    answer = result["answer"]
    sources = result.get("sources", [])
    
    output = f"**Answer:** {answer}\n\n"
    output += f"*Generated in {elapsed:.2f}s*\n\n"
    
    if sources:
        output += "**Sources:**\n"
        for i, src in enumerate(sources, 1):
            source_name = src.get("source", "unknown").split("/")[-1]
            score = src.get("score", 0)
            output += f"{i}. [{source_name}] (relevance: {score:.2f})\n"
    
    return output


# ── Tool: Document Retrieval Only ──

@mcp.tool()
def retrieve(question: str, top_k: int = 5) -> str:
    """Retrieve relevant document chunks WITHOUT generating an answer.
    
    Use this when you want to inspect the source material directly,
    or when you need more detailed context than the RAG query provides.
    Returns chunks with relevance scores and full text.
    """
    chunks = pipeline.retrieve(question, top_k=min(top_k, 10))
    
    if not chunks:
        return "No relevant documents found."
    
    output = f"Retrieved {len(chunks)} relevant chunks:\n\n"
    for i, chunk in enumerate(chunks, 1):
        source = chunk.metadata.get("source", "unknown").split("/")[-1]
        score = chunk.score
        text = chunk.text[:500]  # Truncate for MCP response
        
        output += f"--- [{i}] {source} (score: {score:.4f}) ---\n"
        output += f"{text}\n"
        if len(chunk.text) > 500:
            output += f"...[truncated, {len(chunk.text)} total chars]\n"
        output += "\n"
    
    return output


# ── Tool: Document Indexing ──

@mcp.tool()
def index_document(file_path: str) -> str:
    """Index a file or directory into the RAG knowledge base.
    
    Supports: .md, .txt, .pdf, .html files.
    The document is parsed, chunked, embedded, and stored.
    """
    if not os.path.exists(file_path):
        return f"Error: Path '{file_path}' does not exist."
    
    start = time.time()
    
    if os.path.isdir(file_path):
        chunk_count = pipeline.index_directory(file_path)
        source = f"directory '{file_path}'"
    else:
        chunk_count = pipeline.index_file(file_path)
        source = f"file '{file_path}'"
    
    elapsed = time.time() - start
    
    return (
        f"✅ Indexed {chunk_count} chunks from {source}\n"
        f"⏱️  Time: {elapsed:.2f}s\n"
        f"📊 Total documents in store: {pipeline.document_count}"
    )


# ── Resource: RAG System Status ──

@mcp.resource("rag://status")
def rag_status() -> str:
    """Get the current status of the RAG system."""
    return (
        f"**RAG Pipeline Status**\n\n"
        f"- Document count: {pipeline.document_count}\n"
        f"- Embedding model: {settings.embedding_model}\n"
        f"- Chunk size: {settings.chunk_size}\n"
        f"- Chunk overlap: {settings.chunk_overlap}\n"
        f"- Vector store type: {settings.vector_store}\n"
        f"- Top-K default: {settings.top_k}\n"
        f"- Similarity threshold: {settings.similarity_threshold}"
    )


# ── Resource: Document Inventory ──

@mcp.resource("rag://documents")
def list_documents() -> str:
    """List all indexed documents with chunk counts."""
    docs = pipeline.get_document_inventory()
    if not docs:
        return "No documents indexed yet."
    
    output = "**Indexed Documents:**\n\n"
    output += "| Document | Chunks | Last Updated |\n"
    output += "|----------|--------|--------------|\n"
    for doc in docs:
        output += f"| {doc['name']} | {doc['chunks']} | {doc['updated']} |\n"
    
    return output


# ── Caching Layer ──

class RAGCache:
    """Semantic caching for RAG queries."""
    
    def __init__(self, ttl_seconds: int = 300, max_size: int = 500):
        self.cache = {}
        self.ttl = ttl_seconds
        self.max_size = max_size
    
    def get(self, question: str) -> Optional[str]:
        if question in self.cache:
            entry = self.cache[question]
            if time.time() - entry["time"] < self.ttl:
                return entry["answer"]
            del self.cache[question]
        return None
    
    def set(self, question: str, answer: str):
        if len(self.cache) >= self.max_size:
            # Evict oldest
            oldest = min(self.cache, key=lambda k: self.cache[k]["time"])
            del self.cache[oldest]
        self.cache[question] = {"answer": answer, "time": time.time()}

rag_cache = RAGCache()


if __name__ == "__main__":
    print("Starting RAG MCP Server...")
    mcp.run(transport="sse")  # HTTP for remote access
```

### 4.2 MCP + RAG Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      AI AGENT (Host)                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  LLM decides: "I need to look up documentation"          │    │
│  │  → Calls rag_query("How does chunking work?")            │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────┬────────────────────────────────────┘
                              │ MCP Protocol (JSON-RPC 2.0)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MCP RAG SERVER                                  │
│                                                                   │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────────┐    │
│  │ Cache    │◄───│ RAG Query    │◄───│ Tool Dispatcher     │    │
│  │ (Redis)  │    │ Orchestrator │    │ (tools/list → call) │    │
│  └──────────┘    └──────┬───────┘    └─────────────────────┘    │
│                         │                                         │
│          ┌──────────────┼──────────────┐                        │
│          ▼              ▼              ▼                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                   │
│  │ Embedding  │ │ Vector     │ │ LLM        │                   │
│  │ Service    │ │ Store      │ │ (LM Studio)│                   │
│  │ (GPU)      │ │ (Chroma)   │ │            │                   │
│  └────────────┘ └────────────┘ └────────────┘                   │
└──────────────────────────────────────────────────────────────────┘
```

### 4.3 Client Connection to RAG MCP Server

```python
# clients/python_client.py
"""Python client connecting to the RAG MCP server."""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def query_rag(question: str) -> str:
    """Send a RAG query through MCP and get the answer."""
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "servers.rag_server"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            result = await session.call_tool(
                "rag_query",
                {"question": question, "top_k": 5}
            )
            return result.content[0].text

# Usage
async def main():
    answer = await query_rag("What are the main components of RAG?")
    print(answer)

asyncio.run(main())
```

---

## 5. SCHEMA DISCOVERY & DESIGN PATTERNS

### 5.1 Tool Schema Design Guidelines

| Principle | Bad Example | Good Example |
|-----------|-------------|--------------|
| **Descriptive names** | `query1`, `run` | `query_database`, `get_weather_forecast` |
| **Clear descriptions** | "A tool" | "Execute read-only SQL on analytics DB" |
| **Typed parameters** | `args: string` (JSON blob) | `sql: string, max_rows: int` |
| **Validation constraints** | No constraints | `max_rows: { type: integer, minimum: 1, maximum: 1000 }` |
| **Error documentation** | Unclear errors | "Division by zero is not allowed" |

### 5.2 Resource URI Design

```
# Hierarchical URIs
database://schema/tables
database://schema/table/{table_name}
database://query/{query_id}/results

# Namespace for multi-tenancy
database://{tenant_id}/schema/tables
database://{tenant_id}/metrics/usage

# System resources
system://health
system://config
system://metrics

# RAG-specific resources
rag://status
rag://documents
rag://document/{document_id}
```

### 5.3 Prompt Design

```python
@mcp.prompt()
def debug_query(sql: str, error: str) -> str:
    """Help debug a failed SQL query with context."""
    return f"""I ran a SQL query and got an error. Help me fix it.

Query:
```sql
{sql}
```

Error:
{error}

What went wrong and how can I fix it?"""
```

---

## 6. COMMON UTILITIES

### 6.1 Rate Limiter

```python
# common/rate_limiter.py
import time
from collections import defaultdict
from threading import Lock

class MCPRateLimitError(Exception):
    def __init__(self, message: str, retry_after: int = 1):
        self.retry_after = retry_after
        super().__init__(message)

class MCPRateLimiter:
    """Token bucket rate limiter per client."""
    
    def __init__(self, rate: int, burst: int):
        self.rate = rate
        self.burst = burst
        self.clients = defaultdict(lambda: {
            "tokens": burst,
            "last_refill": time.time()
        })
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
                return False
            client["tokens"] -= 1
            return True
```

### 6.2 Circuit Breaker

```python
# common/circuit_breaker.py
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Failing, rejecting requests
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 30):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = 0
        self.state = CircuitState.CLOSED
        self._probe_in_flight = False  # Tracks whether a HALF_OPEN probe is in progress
    
    def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                self._probe_in_flight = False  # Reset probe flag
            else:
                raise CircuitBreakerOpenError("Service temporarily unavailable")
        
        # ── HALF_OPEN guard: only one probe request at a time ──
        if self.state == CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                raise CircuitBreakerOpenError(
                    "Circuit breaker is HALF_OPEN — "
                    "a probe request is already in flight"
                )
            self._probe_in_flight = True
        
        try:
            result = func(*args, **kwargs)
            if self.state == CircuitState.HALF_OPEN:
                # Probe succeeded — reset to CLOSED
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._probe_in_flight = False
            return result
        except Exception:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN:
                # Probe failed — back to OPEN immediately
                self.state = CircuitState.OPEN
                self._probe_in_flight = False
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            raise

class CircuitBreakerOpenError(Exception):
    pass
```

---

## 7. TESTING MCP SERVERS

```python
# tests/test_rag_server.py
import pytest
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@pytest.fixture
async def server_session():
    params = StdioServerParameters(
        command="python",
        args=["-m", "servers.rag_server"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session

@pytest.mark.asyncio
async def test_list_tools(server_session):
    tools = await server_session.list_tools()
    tool_names = [t.name for t in tools.tools]
    assert "rag_query" in tool_names
    assert "retrieve" in tool_names
    assert "index_document" in tool_names

@pytest.mark.asyncio
async def test_rag_status(server_session):
    resources = await server_session.list_resources()
    resource_uris = [r.uri for r in resources.resources]
    assert "rag://status" in resource_uris

@pytest.mark.asyncio
async def test_rag_query_tool(server_session):
    result = await server_session.call_tool(
        "rag_query",
        {"question": "What is RAG?", "top_k": 3}
    )
    assert result.content[0].text
    assert len(result.content[0].text) > 10
```

---

> **Next:** [MCP Production Architecture](04_MCP_PRODUCTION_ARCHITECTURE.md) → Security, deployment, tradeoffs
