# MCP Common Library

Small, dependency-light building blocks shared by the servers in [servers/](../servers/index.md).

```
common/
├── auth.py              # Bearer-JWT validation, per-request identity, permission decorators
├── rate_limiter.py      # Per-client token bucket
├── circuit_breaker.py   # CLOSED → OPEN → HALF_OPEN breaker for a downstream dependency
└── __init__.py
```

## `auth.py`

- `authenticate_bearer(token)` validates a JWT: signature with a pinned algorithm, `exp`, and, when configured, **audience** (`JWT_AUDIENCE`, this server's resource URI) and issuer. Audience checking is what stops a token minted for another service being replayed here; the MCP authorization spec requires it.
- The caller's identity lives in a `ContextVar` (`set_current_context` / `get_current_context`), so concurrent requests each see their own caller. A module-level "current user" would leak identities between requests.
- `@require_permission("database:read")` and `@require_role("admin")` go **under** `@mcp.tool()`. Permissions come from the token's `permissions` claim or its OAuth `scope`.
- Over **stdio** there is no OAuth: the server is a local subprocess and takes credentials from its environment. `MCP_STDIO_PERMISSIONS` grants permissions to the local user; without it, protected tools fail closed.

## `rate_limiter.py`

Token bucket per client key (`tenant:user`): refills at `rate` tokens/second up to `burst`. `check_rate_limit()` is thread-safe; `get_retry_after()` says how long until the next token. The per-client map is in-process and unbounded, so a multi-replica deployment needs a shared store (for example Redis) and eviction of idle keys.

## `circuit_breaker.py`

Opens after `failure_threshold` **consecutive** failures, rejects calls for `reset_timeout` seconds, then lets exactly one probe through (HALF_OPEN). The probe's result closes or re-opens the circuit. State changes are guarded by a lock because sync MCP tools run on worker threads; the lock is never held while the protected call runs.
