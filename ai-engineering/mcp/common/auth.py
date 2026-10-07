"""
Authentication and authorization helpers for MCP servers.
Provides JWT validation, RBAC, and tenant-scoped access control.

Where identity comes from depends on the transport (MCP spec, 2025-06-18 onward):

- **Streamable HTTP**: the client sends an OAuth 2.1 access token as
  `Authorization: Bearer ...` on *every* request. The MCP server is an OAuth
  resource server: it validates the token (signature, expiry, issuer and,
  crucially, audience = this server) and must not pass it through to
  downstream APIs. In the Python SDK you plug that in with
  `MCPServer(token_verifier=..., auth=AuthSettings(...))`; call
  `authenticate_bearer()` from your verifier, then `set_current_context()`.
- **stdio**: OAuth does not apply. The server runs as a local subprocess and
  takes credentials from its environment. `MCP_STDIO_PERMISSIONS` (comma
  separated) grants permissions to the local user for development.

The current identity is held in a `ContextVar`, so concurrent requests on an
async server each see their own caller. A module-level "current user"
singleton would leak one caller's identity into another's request.
"""

import contextvars
import logging
import os
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, List, Optional

logger = logging.getLogger("mcp.auth")


# Configuration from environment
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "RS256")
JWT_SECRET = os.environ.get("JWT_SECRET", "")          # HS256 only (dev/tests)
JWT_PUBLIC_KEY = os.environ.get("JWT_PUBLIC_KEY", "")  # RS256/ES256: the issuer's key
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "")      # this MCP server's resource URI
JWT_ISSUER = os.environ.get("JWT_ISSUER", "")


@dataclass
class AuthContext:
    """Authenticated caller context propagated through tool calls."""
    user_id: str
    tenant_id: str = "default"
    roles: List[str] = field(default_factory=list)
    token_id: str = ""
    permissions: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class AuthError(Exception):
    """Authentication failed (HTTP 401)."""


class AuthorizationError(Exception):
    """Authenticated, but not allowed (HTTP 403, or a tool error)."""


_current: contextvars.ContextVar[Optional[AuthContext]] = contextvars.ContextVar(
    "mcp_auth_context", default=None
)


def authenticate_bearer(token: str) -> AuthContext:
    """Validate a bearer JWT and return the caller's identity.

    Checks signature, expiry, and (when configured) audience and issuer.
    Audience validation is what stops a token minted for a different
    service being replayed against this one.

    Raises:
        AuthError: If the token is missing, expired, or invalid.
    """
    if not token:
        raise AuthError("Missing authentication token")
    try:
        import jwt as pyjwt
    except ImportError as e:
        raise AuthError("PyJWT is not installed") from e

    key = JWT_SECRET if JWT_ALGORITHM.startswith("HS") else JWT_PUBLIC_KEY
    if not key:
        raise AuthError(f"No verification key configured for {JWT_ALGORITHM}")

    try:
        payload = pyjwt.decode(
            token,
            key,
            algorithms=[JWT_ALGORITHM],      # never accept the token's own "alg" blindly
            audience=JWT_AUDIENCE or None,
            issuer=JWT_ISSUER or None,
            options={"require": ["exp", "sub"]},
        )
    except pyjwt.PyJWTError as e:
        raise AuthError(f"Token validation failed: {e}") from e

    scopes = payload.get("scope", "")
    context = AuthContext(
        user_id=payload["sub"],
        tenant_id=payload.get("tenant_id", "default"),
        roles=payload.get("roles", []),
        token_id=payload.get("jti", ""),
        # OAuth puts scopes in a space-separated "scope" claim.
        permissions=payload.get("permissions", scopes.split() if scopes else []),
        metadata=payload.get("metadata", {}),
    )
    logger.info(
        "Authenticated user=%s tenant=%s roles=%s",
        context.user_id, context.tenant_id, context.roles,
    )
    return context


def set_current_context(ctx: Optional[AuthContext]) -> contextvars.Token:
    """Bind the caller's identity to the current request (task/context)."""
    return _current.set(ctx)


def reset_current_context(token: contextvars.Token) -> None:
    """Undo a previous `set_current_context`."""
    _current.reset(token)


def _stdio_context() -> AuthContext:
    """Identity for a local stdio server, taken from the environment."""
    perms = [p.strip() for p in os.environ.get("MCP_STDIO_PERMISSIONS", "").split(",") if p.strip()]
    return AuthContext(
        user_id=os.environ.get("USER", "local"),
        tenant_id="local",
        permissions=perms,
    )


def get_current_context() -> AuthContext:
    """Identity of the caller of the current request.

    Falls back to the stdio/local identity when no bearer token was bound.
    With no `MCP_STDIO_PERMISSIONS` set that identity has no permissions, so
    protected tools fail closed.
    """
    return _current.get() or _stdio_context()


def get_current_client_id() -> str:
    """A stable per-caller key for rate limiting."""
    ctx = get_current_context()
    return f"{ctx.tenant_id}:{ctx.user_id}"


def require_permission(permission: str) -> Callable:
    """Decorator for tool-level authorization.

    Put it *under* the MCP decorator so the registered function is the
    checked one:

        @mcp.tool()
        @require_permission("database:read")
        def query(sql: str) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_current_context()
            if permission not in ctx.permissions:
                # Don't echo the caller's full permission list back to the model.
                raise AuthorizationError(f"Missing required permission: '{permission}'")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(role: str) -> Callable:
    """Decorator to require a specific role (place under @mcp.tool())."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_current_context()
            if role not in ctx.roles:
                raise AuthorizationError(f"Missing required role: '{role}'")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def has_permission(permission: str) -> bool:
    """Check if the current caller has a specific permission."""
    return permission in get_current_context().permissions
