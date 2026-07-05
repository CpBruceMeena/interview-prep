"""
Circuit breaker pattern for MCP server resilience.
Prevents cascading failures by failing fast when downstream services
are unhealthy, with automatic recovery testing.
"""

import time
import logging
from enum import Enum
from typing import Callable, Optional, Any

logger = logging.getLogger("mcp.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "CLOSED"           # Normal operation — requests pass through
    OPEN = "OPEN"               # Failing — requests rejected immediately
    HALF_OPEN = "HALF_OPEN"     # Testing — limited requests allowed


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and a request is rejected."""
    pass


class CircuitBreaker:
    """Circuit breaker with automatic recovery testing.

    Transitions:
        CLOSED → OPEN: After `failure_threshold` consecutive failures
        OPEN → HALF_OPEN: After `reset_timeout` seconds
        HALF_OPEN → CLOSED: If the probe request succeeds
        HALF_OPEN → OPEN: If the probe request fails

    Args:
        failure_threshold: Number of consecutive failures to trip the breaker
        reset_timeout: Seconds to wait before testing recovery
        name: Optional name for logging
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 30,
        name: Optional[str] = None,
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.name = name or "unnamed"
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._last_success_time = 0.0
        self._state = CircuitState.CLOSED
        self._total_calls = 0
        self._total_failures = 0

    @property
    def state(self) -> CircuitState:
        """Get current circuit breaker state."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "Circuit breaker %s → HALF_OPEN (probing)",
                    self.name
                )
        return self._state

    @property
    def failure_rate(self) -> float:
        """Get the failure rate since last reset."""
        if self._total_calls == 0:
            return 0.0
        return self._total_failures / self._total_calls

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker.

        If the circuit is OPEN, raises CircuitBreakerOpenError.
        If it's HALF_OPEN, allows the call as a probe.
        If it's CLOSED, allows the call normally.

        On success in HALF_OPEN state, resets to CLOSED.
        On failure, increments failure counter and may transition to OPEN.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            self._total_calls += 1
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN. "
                f"Retry after {self.reset_timeout}s."
            )

        try:
            result = func(*args, **kwargs)

            self._total_calls += 1
            self._last_success_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Probe succeeded — reset
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(
                    "Circuit breaker %s → CLOSED (recovered)",
                    self.name
                )

            return result

        except Exception as e:
            self._total_calls += 1
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "Circuit breaker %s → OPEN "
                        "(%d failures, threshold=%d)",
                        self.name,
                        self._failure_count,
                        self.failure_threshold
                    )

            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._total_calls = 0
        self._total_failures = 0
        logger.info("Circuit breaker %s manually reset to CLOSED", self.name)
