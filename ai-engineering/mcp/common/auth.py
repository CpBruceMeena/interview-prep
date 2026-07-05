"""
Authentication and authorization middleware for MCP servers.
Provides JWT validation, RBAC, and tenant-scoped access control.
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Callable, Any
from functools import wraps

logger = logging.getLogger("mcp.auth")


# Configuration from environment
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_SECRET = os.environ.get("JWT_SECRET", "development-secret-change-in-production")
JWT_PUBLIC_KEY = os.environ.get("JWT_PUBLIC_KEY", "")


@dataclass
class AuthContext:
    """Authenticated user context propagated through tool calls."""
    user_id: str
    tenant_id: str = "default"
    roles: List[str] = field(default_factory=list)
    session_id: str = ""
    permissions: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class AuthError(Exception):
    """Authentication failed."""
    pass


class AuthorizationError(Exception):
    """Insufficient permissions."""
    pass


class AuthMiddleware:
    """JWT-based authentication middleware for MCP servers.

    Validates tokens during initialization and provides
    authenticated context for tool execution.
    """

    def __init__(self):
        self._current_context: Optional[AuthContext] = None

    def validate_init_metadata(self, metadata: dict) -> AuthContext:
        """Validate authentication during client initialization.

        Extracts and validates JWT from the client's initialization metadata.
        Returns an AuthContext with the user's identity.

        Args:
            metadata: Client initialization metadata, should contain
                     'authorization' or 'x-api-key' header equivalent.

        Raises:
            AuthError: If the token is missing, expired, or invalid.
        """
        token = (
            metadata.get("authorization", "").replace("Bearer ", "")
            or metadata.get("x-api-key", "")
        )

        if not token:
            raise AuthError("Missing authentication token")

        try:
            if JWT_ALGORITHM == "RS256":
                import jwt as pyjwt
                payload = pyjwt.decode(
                    token, JWT_PUBLIC_KEY, algorithms=["RS256"]
                )
            else:
                import jwt as pyjwt
                payload = pyjwt.decode(
                    token, JWT_SECRET, algorithms=["HS256"]
                )

            context = AuthContext(
                user_id=payload.get("sub", "unknown"),
                tenant_id=payload.get("tenant_id", "default"),
                roles=payload.get("roles", []),
                session_id=payload.get("jti", ""),
                permissions=payload.get("permissions", []),
                metadata=payload.get("metadata", {}),
            )

            self._current_context = context
            logger.info(
                "Authenticated user=%s tenant=%s roles=%s",
                context.user_id, context.tenant_id, context.roles
            )
            return context

        except ImportError:
            raise AuthError("PyJWT library not installed")
        except Exception as e:
            raise AuthError(f"Token validation failed: {e}")

    def get_current_context(self) -> AuthContext:
        """Get the current authenticated context."""
        if self._current_context is None:
            return AuthContext(user_id="anonymous")
        return self._current_context

    def clear_context(self) -> None:
        """Clear the current auth context (on disconnect)."""
        self._current_context = None


# Singleton auth middleware
_auth = AuthMiddleware()


def get_current_context() -> AuthContext:
    """Get current auth context from the singleton middleware."""
    return _auth.get_current_context()


def get_current_client_id() -> str:
    """Get a unique client identifier for rate limiting."""
    ctx = _auth.get_current_context()
    return f"{ctx.tenant_id}:{ctx.user_id}"


def require_permission(permission: str) -> Callable:
    """Decorator for tool-level authorization.

    Usage:
        @require_permission("database:read")
        @mcp.tool()
        def query_database(sql: str) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = _auth.get_current_context()
            if permission and permission not in ctx.permissions:
                raise AuthorizationError(
                    f"Missing required permission: '{permission}'. "
                    f"User {ctx.user_id} has: {ctx.permissions}"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(role: str) -> Callable:
    """Decorator to require a specific role for tool access.

    Usage:
        @require_role("admin")
        @mcp.tool()
        def delete_database() -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = _auth.get_current_context()
            if role not in ctx.roles:
                raise AuthorizationError(
                    f"Missing required role: '{role}'. "
                    f"User {ctx.user_id} has: {ctx.roles}"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def has_permission(permission: str) -> bool:
    """Check if the current user has a specific permission."""
    ctx = _auth.get_current_context()
    return permission in ctx.permissions
