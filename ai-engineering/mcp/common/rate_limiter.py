"""
Token bucket rate limiter for MCP servers.
Per-client rate limiting with burst capacity.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Optional


class MCPRateLimitError(Exception):
    """Raised when a client exceeds the rate limit."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 1):
        self.retry_after = retry_after
        super().__init__(message)


class MCPRateLimiter:
    """Token bucket rate limiter per client.

    Each client gets a bucket that refills at `rate` tokens/second
    up to `burst` capacity. If a client runs out of tokens, requests
    are rejected until tokens refill.

    Args:
        rate: Tokens added per second (requests per second sustained)
        burst: Maximum burst capacity (short-term request spike)
    """

    def __init__(self, rate: int = 10, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self._clients: dict = defaultdict(lambda: {
            "tokens": burst,
            "last_refill": time.time()
        })
        self._lock = Lock()

    def check_rate_limit(self, client_id: str) -> bool:
        """Check if a client is within the rate limit.

        Returns True if the request is allowed, False if rate limited.
        Thread-safe.
        """
        with self._lock:
            client = self._clients[client_id]
            now = time.time()
            elapsed = now - client["last_refill"]

            # Refill tokens
            client["tokens"] = min(
                self.burst,
                client["tokens"] + elapsed * self.rate
            )
            client["last_refill"] = now

            if client["tokens"] < 1:
                return False

            client["tokens"] -= 1
            return True

    def get_retry_after(self, client_id: str) -> float:
        """Get how many seconds until the client has a token available."""
        with self._lock:
            client = self._clients[client_id]
            if client["tokens"] >= 1:
                return 0.0
            deficit = 1 - client["tokens"]
            return deficit / self.rate if self.rate > 0 else float("inf")

    def reset_client(self, client_id: str) -> None:
        """Reset rate limit state for a client."""
        with self._lock:
            self._clients.pop(client_id, None)
