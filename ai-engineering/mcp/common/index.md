# 🔧 MCP Common Library

Shared infrastructure and utilities used across MCP server implementations.

## Module Overview

```
common/
├── auth.py              # Authentication and authorization
├── rate_limiter.py      # Rate limiting utilities
├── circuit_breaker.py   # Circuit breaker for resilience
└── __init__.py
```

## Components

### Auth (`auth.py`)
Authentication and authorization middleware for MCP servers:
- **Token validation** — JWT-based token verification
- **API key auth** — Key-based authentication for internal services
- **Role-based access** — Permission checking for tool operations

### Rate Limiter (`rate_limiter.py`)
Rate limiting to prevent abuse:
- **Token bucket algorithm** — Configurable rate and burst limits
- **Per-client tracking** — Separate limits per connected client
- **Sliding window** — Time-based window enforcement

### Circuit Breaker (`circuit_breaker.py`)
Resilience pattern for external service calls:
- **State machine** — CLOSED → OPEN → HALF_OPEN → CLOSED
- **Configurable thresholds** — Failure count and timeout window
- **Fallback handling** — Graceful degradation on failure
