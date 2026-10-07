"""
Guardrails for AI agents — rate limiting, input/output validation, safety checks.

These are deliberately simple teaching examples. Regex deny-lists catch only
the laziest prompt injections and are trivially bypassed (paraphrase, another
language, base64, or injection hidden in a tool result). Real defences are
architectural: least-privilege tools, approval gates on side effects, treating
tool output as untrusted data, and a classifier model for screening.
"""

import re
import time
from typing import Optional, Set
from dataclasses import dataclass


class TokenBucket:
    """Token bucket rate limiter (single-process, not thread-safe).

    Uses time.monotonic() so wall-clock jumps (NTP steps, manual changes) can't mint tokens.
    """

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens < tokens:
            return False
        self.tokens -= tokens
        return True

    @property
    def retry_after(self) -> float:
        """Seconds until a token is available."""
        if self.tokens >= 1:
            return 0
        return (1 - self.tokens) / self.rate


CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    message: str = ""
    severity: str = "info"  # info, warning, critical


class InputGuard:
    """Validates all inputs to the agent."""

    MAX_INPUT_LENGTH = 8000
    BLOCKED_PATTERNS: Set[str] = {
        r"ignore all previous instructions",
        r"system prompt:",
        r"you are now an ai",
        r"print your instructions",
    }

    def validate(self, user_input: str) -> GuardrailResult:
        """Validate user input before it reaches the agent."""
        if len(user_input) > self.MAX_INPUT_LENGTH:
            return GuardrailResult(
                passed=False,
                message=f"Input exceeds {self.MAX_INPUT_LENGTH} characters",
                severity="warning",
            )

        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                return GuardrailResult(
                    passed=False,
                    message="Input contains blocked patterns",
                    severity="critical",
                )

        # PII detection (basic): 13-19 digit card numbers, optional spaces/dashes.
        if CARD_RE.search(user_input):
            return GuardrailResult(
                passed=False,
                message="Input contains credit card numbers",
                severity="critical",
            )

        return GuardrailResult(passed=True)


class OutputGuard:
    """Validates all agent outputs before returning to user."""

    def validate(self, agent_output: str) -> GuardrailResult:
        """Validate agent output before it reaches the user."""
        # Check for PII leakage
        if CARD_RE.search(agent_output):
            return GuardrailResult(
                passed=False,
                message="Output contains sensitive information",
                severity="critical",
            )

        # Check for HTML/script injection into a web UI
        if re.search(r"<script[^>]*>", agent_output, re.IGNORECASE):
            return GuardrailResult(
                passed=False,
                message="Output contains script tags",
                severity="critical",
            )

        return GuardrailResult(passed=True)

    def sanitize(self, text: str) -> str:
        """Remove or replace sensitive content."""
        text = CARD_RE.sub("[REDACTED]", text)
        text = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[EMAIL]", text)
        return text
