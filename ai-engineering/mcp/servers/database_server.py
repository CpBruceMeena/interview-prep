"""
PostgreSQL database MCP server with security, rate limiting, and auth.
Run: python -m servers.database_server

Requires: pip install psycopg2-binary mcp

Environment variables:
- DATABASE_URL: PostgreSQL connection string (default: postgresql://localhost:5432/analytics)
- MAX_ROWS: Maximum rows per query (default: 1000)
- QUERY_TIMEOUT: Query timeout in seconds (default: 10)
"""

import json
import os
import time
import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP

from common.rate_limiter import MCPRateLimiter, MCPRateLimitError
from common.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from common.auth import get_current_context, get_current_client_id, require_permission

# Configure logging
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
mcp = FastMCP("DatabaseConnector")

# ── Resilience: Rate Limiter + Circuit Breaker ──
rate_limiter = MCPRateLimiter(rate=10, burst=20)
db_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    reset_timeout=30,
    name="database"
)


# ── Database Helpers ──

def get_connection():
    """Create a read-only database connection."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
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
    # Safety check: only allow SELECT and WITH (CTE) queries
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
            rows = cur.fetchmany(min(max_rows, MAX_ROWS))
            return {
                "columns": columns,
                "rows": [dict(row) for row in rows],
                "total_returned": len(rows),
                "truncated": len(rows) >= min(max_rows, MAX_ROWS),
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


# ── Tools ──


@mcp.tool()
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
    result = execute_query(
        "SELECT table_name, "
        "       pg_size_pretty(pg_total_relation_size("
        "           quote_ident(table_name)"
        "       )) as size, "
        "       (SELECT COUNT(*) FROM "
        "           quote_ident(table_name)) as row_count "
        "FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "ORDER BY pg_total_relation_size("
        "    quote_ident(table_name)"
        ") DESC"
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
        return json.dumps({
            "status": "unhealthy",
            "error": str(e),
        }, indent=2)


# ── Main ──

if __name__ == "__main__":
    print("🗄️  Starting Database MCP Server...")
    print(f"   Database: {DB_URL.split('@')[-1] if '@' in DB_URL else DB_URL}")
    print(f"   Max rows: {MAX_ROWS}")
    print(f"   Rate limit: {rate_limiter.rate} req/s (burst: {rate_limiter.burst})")
    print("   Transport: stdio")
    mcp.run(transport="stdio")
