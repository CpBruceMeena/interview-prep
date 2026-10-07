"""
PostgreSQL database MCP server with security, rate limiting, and auth.
Run (from ai-engineering/mcp): python -m servers.database_server

Requires: pip install psycopg2-binary "mcp>=2"

Environment variables:
- DATABASE_URL: PostgreSQL connection string (default: postgresql://localhost:5432/analytics)
- MAX_ROWS: Maximum rows per query (default: 1000)
- QUERY_TIMEOUT: Per-statement timeout in seconds (default: 10)
- MCP_STDIO_PERMISSIONS: permissions for the local stdio user, e.g. "database:read"
  (without it the protected tools fail closed; see common/auth.py)

Defence in depth for "let an LLM run SQL":
1. A read-only role in Postgres (the real guarantee; grant SELECT on an allow-list
   of tables/views only). This file can't create it for you.
2. A read-only transaction + statement_timeout on every connection.
3. The SELECT/WITH prefix check below, which only gives a friendlier error:
   it is NOT a security boundary (`WITH x AS (DELETE ...)`, side-effecting
   functions, `SELECT pg_sleep(...)` all pass a prefix check).
"""

import json
import os
import time
import logging
from functools import wraps
from typing import Callable, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from common.rate_limiter import MCPRateLimiter, MCPRateLimitError
from common.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from common.auth import (
    AuthorizationError,
    get_current_client_id,
    get_current_context,
    require_permission,
)

# Configure logging (to stderr: stdout is the stdio transport's JSON-RPC channel)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mcp.database_server")

# ── Configuration ──
DB_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/analytics")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "1000"))
QUERY_TIMEOUT_SECONDS = int(os.environ.get("QUERY_TIMEOUT", "10"))

# ── Initialize MCP Server ──
mcp = MCPServer("DatabaseConnector")

# ── Resilience: Rate Limiter + Circuit Breaker ──
rate_limiter = MCPRateLimiter(rate=10, burst=20)
db_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    reset_timeout=30,
    name="database"
)


# ── Database Helpers ──

def get_connection():
    """Create a read-only database connection with a statement timeout.

    A new connection per call keeps the demo simple; a real server would use a
    pool (psycopg_pool / pgbouncer) sized below the database's connection limit.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        DB_URL,
        cursor_factory=RealDictCursor,
        options=f"-c statement_timeout={QUERY_TIMEOUT_SECONDS * 1000}",
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def execute_query(
    sql: str,
    params: Optional[List] = None,
    max_rows: int = 100
) -> dict:
    """Execute a read-only query with safety checks.

    Validates the query is a SELECT or WITH statement before execution.
    Always uses parameterized queries to prevent SQL injection.

    Args:
        sql: SQL query string (only SELECT/WITH allowed)
        params: Query parameters for parameterized execution
        max_rows: Maximum number of rows to return

    Returns:
        dict with columns, rows, total_returned, and truncated flag
    """
    # Friendly early rejection only; the read-only session/role is the real guard.
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT") and not sql_stripped.startswith("WITH"):
        raise ValueError(
            "Only SELECT queries are allowed for security reasons."
        )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            limit = min(max_rows, MAX_ROWS)
            # Fetch one extra row so "truncated" is exact, not a guess.
            rows = cur.fetchmany(limit + 1) if cur.description else []
            truncated = len(rows) > limit
            rows = rows[:limit]
            return {
                "columns": columns,
                "rows": [dict(row) for row in rows],
                "total_returned": len(rows),
                "truncated": truncated,
            }
    finally:
        conn.close()


def _format_results(sql: str, max_rows: int) -> str:
    """Execute query and format result as a markdown table string."""
    result = execute_query(sql, max_rows=max_rows)

    if not result["rows"]:
        return "Query returned no results."

    # Format as a clean markdown table
    header = "| " + " | ".join(result["columns"]) + " |"
    separator = "| " + " | ".join(["---"] * len(result["columns"])) + " |"
    rows = []
    for row in result["rows"]:
        values = [str(row.get(col, ""))[:100] for col in result["columns"]]
        rows.append("| " + " | ".join(values) + " |")

    output = header + "\n" + separator + "\n" + "\n".join(rows)

    if result["truncated"]:
        output += (
            f"\n\n*Results truncated to {max_rows} rows. "
            "Use a more specific query or WHERE clause to narrow results.*"
        )

    return output


def as_tool_errors(func: Callable) -> Callable:
    """Turn anticipated failures into ToolErrors so the model sees the message.

    In SDK v2, any other exception is reported to the client only as a generic
    "Error executing tool X" (details stay in the server log).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ValueError, AuthorizationError, MCPRateLimitError) as e:
            raise ToolError(str(e)) from e
    return wrapper


# ── Tools ──


@mcp.tool()
@as_tool_errors
@require_permission("database:read")
def query(sql: str, max_rows: int = 100) -> str:
    """Execute a read-only SQL query against the analytics database.

    Use this to ask questions about data stored in the database.
    Only SELECT and WITH (CTE) queries are permitted.

    Args:
        sql: SQL SELECT query — read-only queries only
        max_rows: Maximum number of rows to return (default: 100, max: 1000)
    """
    client_id = get_current_client_id()
    ctx = get_current_context()

    logger.info(
        "Query from user=%s tenant=%s: %.100s",
        ctx.user_id, ctx.tenant_id, sql
    )

    # Rate limiting
    if not rate_limiter.check_rate_limit(client_id):
        retry_after = rate_limiter.get_retry_after(client_id)
        logger.warning("Rate limit exceeded for client=%s", client_id)
        raise MCPRateLimitError(
            f"Rate limit exceeded. Try again in {retry_after:.1f}s.",
            retry_after=int(retry_after)
        )

    # Circuit breaker
    try:
        return db_circuit_breaker.call(
            _format_results, sql, int(min(max_rows, MAX_ROWS))
        )
    except CircuitBreakerOpenError:
        logger.error("Circuit breaker OPEN for database")
        raise MCPRateLimitError(
            "Database is temporarily unavailable. Please try again later.",
            retry_after=15
        )


# ── Resources ──


@mcp.resource("database://schema/tables")
@require_permission("database:read")
def list_tables() -> str:
    """List all tables in the public schema with their sizes."""
    start = time.time()
    # Sizes and row estimates come from the catalog: an exact COUNT(*) per
    # table would scan every table just to render a schema listing.
    result = execute_query(
        "SELECT c.relname AS table_name, "
        "       pg_size_pretty(pg_total_relation_size(c.oid)) AS size, "
        "       c.reltuples::bigint AS approx_rows "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
        "ORDER BY pg_total_relation_size(c.oid) DESC"
    )
    elapsed = (time.time() - start) * 1000
    output = f"*Schema loaded in {elapsed:.0f}ms*\n\n"
    output += json.dumps(result, indent=2, default=str)
    return output


@mcp.resource("database://schema/table/{table_name}")
@require_permission("database:read")
def describe_table(table_name: str) -> str:
    """Describe columns of a specific table.

    Returns column names, data types, nullability, and max lengths.
    """
    if not table_name.isidentifier():
        return f"Error: '{table_name}' is not a valid table name."

    result = execute_query(
        "SELECT column_name, data_type, is_nullable, "
        "       COALESCE(character_maximum_length::text, 'N/A') as max_length, "
        "       COALESCE(column_default, 'N/A') as default_value "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        [table_name]
    )
    return json.dumps(result, indent=2, default=str)


@mcp.resource("database://health")
def health_check() -> str:
    """Check if the database connection is healthy."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            result = cur.fetchone()
        conn.close()
        return json.dumps({
            "status": "healthy",
            "database_url": DB_URL.split("@")[-1] if "@" in DB_URL else "local",
            "timestamp": time.time(),
        }, indent=2)
    except Exception as e:
        logger.warning("Health check failed: %s", e)
        # Don't return raw driver errors: they can contain hostnames or credentials.
        return json.dumps({"status": "unhealthy", "error": type(e).__name__}, indent=2)


# ── Main ──

if __name__ == "__main__":
    # stdio transport: anything printed to stdout would corrupt the JSON-RPC stream.
    logger.info(
        "Starting Database MCP Server (stdio): db=%s max_rows=%d rate=%s/s burst=%s",
        DB_URL.split("@")[-1], MAX_ROWS, rate_limiter.rate, rate_limiter.burst,
    )
    mcp.run(transport="stdio")
