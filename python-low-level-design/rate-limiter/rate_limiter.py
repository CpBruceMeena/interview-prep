"""
Rate Limiter - Low Level Design
----------------------------------
Design Principles: SOLID, Strategy Pattern, OCP
"""

from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Callable
import threading
import time


class RateLimitResult(Enum):
    ALLOWED = "Allowed"
    DENIED = "Denied"


class RateLimitRule:
    """Represents a single rate limit rule"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds


# --- Algorithm Strategies (Strategy Pattern - OCP) ---

class RateLimitAlgorithm(ABC):
    """Interface Segregation: Specific to rate limiting algorithms"""

    @abstractmethod
    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        pass

    @abstractmethod
    def get_window_remaining(self, key: str) -> int:
        """Get remaining requests in current window"""
        pass

    @abstractmethod
    def reset_key(self, key: str) -> None:
        pass


class SlidingWindowLog(RateLimitAlgorithm):
    """Sliding window log algorithm - keeps timestamp of each request"""

    def __init__(self, rule: RateLimitRule):
        self._rule = rule
        self._logs: Dict[str, deque] = {}

    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        if key not in self._logs:
            self._logs[key] = deque()

        log = self._logs[key]
        # Remove expired entries
        while log and log[0] < timestamp - self._rule.window_seconds:
            log.popleft()

        if len(log) < self._rule.max_requests:
            log.append(timestamp)
            return RateLimitResult.ALLOWED
        return RateLimitResult.DENIED

    def get_window_remaining(self, key: str) -> int:
        if key not in self._logs:
            return self._rule.max_requests
        log = self._logs[key]
        now = time.time()
        while log and log[0] < now - self._rule.window_seconds:
            log.popleft()
        return self._rule.max_requests - len(log)

    def reset_key(self, key: str) -> None:
        self._logs.pop(key, None)


class TokenBucket(RateLimitAlgorithm):
    """Token Bucket algorithm - tokens refill at a constant rate"""

    def __init__(self, rule: RateLimitRule):
        self._rule = rule
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}
        self._refill_rate = rule.max_requests / rule.window_seconds  # tokens per second

    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        self._refill(key, timestamp)
        if self._tokens.get(key, 0) >= 1:
            self._tokens[key] -= 1
            return RateLimitResult.ALLOWED
        return RateLimitResult.DENIED

    def _refill(self, key: str, timestamp: float) -> None:
        if key not in self._tokens:
            self._tokens[key] = self._rule.max_requests
            self._last_refill[key] = timestamp
            return

        elapsed = timestamp - self._last_refill[key]
        new_tokens = elapsed * self._refill_rate
        self._tokens[key] = min(self._rule.max_requests, self._tokens[key] + new_tokens)
        self._last_refill[key] = timestamp

    def get_window_remaining(self, key: str) -> int:
        self._refill(key, time.time())
        return int(self._tokens.get(key, self._rule.max_requests))

    def reset_key(self, key: str) -> None:
        self._tokens.pop(key, None)
        self._last_refill.pop(key, None)


class FixedWindowCounter(RateLimitAlgorithm):
    """Fixed window counter - simple and efficient"""

    def __init__(self, rule: RateLimitRule):
        self._rule = rule
        self._counters: Dict[str, int] = {}
        self._window_start: Dict[str, float] = {}

    def _get_window_key(self, key: str, timestamp: float) -> int:
        return int(timestamp // self._rule.window_seconds)

    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        window_key = self._get_window_key(key, timestamp)
        full_key = f"{key}:{window_key}"

        if full_key not in self._counters:
            self._counters[full_key] = 0
            self._window_start[key] = timestamp

        if self._counters[full_key] < self._rule.max_requests:
            self._counters[full_key] += 1
            return RateLimitResult.ALLOWED
        return RateLimitResult.DENIED

    def get_window_remaining(self, key: str) -> int:
        timestamp = time.time()
        window_key = self._get_window_key(key, timestamp)
        full_key = f"{key}:{window_key}"
        used = self._counters.get(full_key, 0)
        return self._rule.max_requests - used

    def reset_key(self, key: str) -> None:
        keys_to_remove = [k for k in self._counters if k.startswith(f"{key}:")]
        for k in keys_to_remove:
            del self._counters[k]
        self._window_start.pop(key, None)


class SlidingWindowCounter(RateLimitAlgorithm):
    """Sliding window counter - combines fixed window with weighted previous window"""

    def __init__(self, rule: RateLimitRule):
        self._rule = rule
        self._counters: Dict[str, Dict[int, int]] = {}

    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        current_window = int(timestamp // self._rule.window_seconds)
        previous_window = current_window - 1

        if key not in self._counters:
            self._counters[key] = {}

        current_count = self._counters[key].get(current_window, 0)
        previous_count = self._counters[key].get(previous_window, 0)

        # Calculate weighted count for sliding window
        window_progress = (timestamp - current_window * self._rule.window_seconds) / self._rule.window_seconds
        weighted_count = previous_count * (1 - window_progress) + current_count

        if weighted_count < self._rule.max_requests:
            self._counters[key][current_window] = current_count + 1
            return RateLimitResult.ALLOWED
        return RateLimitResult.DENIED

    def get_window_remaining(self, key: str) -> int:
        timestamp = time.time()
        current_window = int(timestamp // self._rule.window_seconds)
        previous_window = current_window - 1

        if key not in self._counters:
            return self._rule.max_requests

        current_count = self._counters[key].get(current_window, 0)
        previous_count = self._counters[key].get(previous_window, 0)
        window_progress = (timestamp - current_window * self._rule.window_seconds) / self._rule.window_seconds
        weighted_count = previous_count * (1 - window_progress) + current_count

        return max(0, self._rule.max_requests - int(weighted_count))

    def reset_key(self, key: str) -> None:
        self._counters.pop(key, None)


class LeakyBucket(RateLimitAlgorithm):
    """Leaky Bucket algorithm - processes requests at a constant leak rate.

    Requests are queued in a bucket. If the bucket (queue) is full, new
    requests are denied. The bucket leaks (processes) requests at a fixed
    rate, smoothing out bursts into a steady flow.
    """

    def __init__(self, rule: RateLimitRule):
        self._rule = rule
        self._queues: Dict[str, deque] = {}
        self._last_leak: Dict[str, float] = {}
        self._leak_rate = rule.max_requests / rule.window_seconds  # requests/sec

    def _leak(self, key: str, timestamp: float) -> None:
        """Process (leak) requests from the queue based on elapsed time"""
        if key not in self._queues:
            return

        queue = self._queues[key]
        last_leak = self._last_leak.get(key, timestamp)
        elapsed = timestamp - last_leak

        # How many requests to process since last leak
        requests_to_process = int(elapsed * self._leak_rate)

        for _ in range(min(requests_to_process, len(queue))):
            queue.popleft()

        # Only advance last_leak by the time actually consumed to preserve
        # fractional carry (like TokenBucket preserves fractional tokens)
        if requests_to_process > 0 and self._leak_rate > 0:
            self._last_leak[key] = last_leak + (requests_to_process / self._leak_rate)
        else:
            self._last_leak[key] = last_leak

    def allow_request(self, key: str, timestamp: float) -> RateLimitResult:
        self._leak(key, timestamp)

        if key not in self._queues:
            self._queues[key] = deque()
            self._last_leak[key] = timestamp

        queue = self._queues[key]

        if len(queue) < self._rule.max_requests:
            queue.append(timestamp)
            return RateLimitResult.ALLOWED
        return RateLimitResult.DENIED

    def get_window_remaining(self, key: str) -> int:
        now = time.time()
        self._leak(key, now)
        if key not in self._queues:
            return self._rule.max_requests
        return self._rule.max_requests - len(self._queues[key])

    def reset_key(self, key: str) -> None:
        self._queues.pop(key, None)
        self._last_leak.pop(key, None)


# --- Rate Limiter Factory ---

class RateLimiterFactory:
    """Factory Pattern for creating rate limiters"""

    _algorithms = {
        "sliding_window_log": SlidingWindowLog,
        "token_bucket": TokenBucket,
        "fixed_window": FixedWindowCounter,
        "sliding_window_counter": SlidingWindowCounter,
        "leaky_bucket": LeakyBucket,
    }

    @classmethod
    def create(cls, algorithm: str, rule: RateLimitRule) -> RateLimitAlgorithm:
        algo_class = cls._algorithms.get(algorithm)
        if not algo_class:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        return algo_class(rule)


# --- Rate Limiter (Facade / SRP) ---

class RateLimiter:
    """Rate limiter with pluggable algorithms.
    Follows Dependency Inversion - depends on algorithm abstraction."""

    def __init__(self, algorithm: RateLimitAlgorithm):
        self._algorithm = algorithm
        self._lock = threading.Lock()

    def allow_request(self, key: str) -> RateLimitResult:
        with self._lock:
            return self._algorithm.allow_request(key, time.time())

    def get_remaining(self, key: str) -> int:
        with self._lock:
            return self._algorithm.get_window_remaining(key)

    def reset(self, key: str) -> None:
        with self._lock:
            self._algorithm.reset_key(key)

    @property
    def algorithm(self) -> RateLimitAlgorithm:
        return self._algorithm


# --- Rate Limit Middleware ---

class RateLimitMiddleware:
    """Middleware for applying rate limits to API calls"""

    def __init__(self):
        self._limiters: Dict[str, RateLimiter] = {}

    def add_rule(self, endpoint: str, rule: RateLimitRule,
                 algorithm: str = "token_bucket") -> None:
        algo = RateLimiterFactory.create(algorithm, rule)
        self._limiters[endpoint] = RateLimiter(algo)

    def check_rate_limit(self, endpoint: str, user_id: str) -> RateLimitResult:
        limiter = self._limiters.get(endpoint)
        if not limiter:
            return RateLimitResult.ALLOWED

        key = f"{endpoint}:{user_id}"
        return limiter.allow_request(key)

    def get_remaining(self, endpoint: str, user_id: str) -> int:
        limiter = self._limiters.get(endpoint)
        if not limiter:
            return float('inf')
        return limiter.get_remaining(f"{endpoint}:{user_id}")


# --- Demo ---

def demo():
    print("=== Rate Limiter Demo ===")
    print("=" * 50)

    # Token Bucket - 5 requests per 10 seconds
    rule = RateLimitRule(max_requests=5, window_seconds=10)
    limiter = RateLimiter(TokenBucket(rule))

    user = "user_123"
    print(f"\nToken Bucket: 5 requests/10s")
    print("-" * 40)

    for i in range(7):
        result = limiter.allow_request(user)
        remaining = limiter.get_remaining(user)
        print(f"  Request {i+1}: {result.value} (Remaining: {remaining})")
        time.sleep(0.1)

    print(f"\n  Waiting for refill...")
    time.sleep(1)
    remaining = limiter.get_remaining(user)
    print(f"  After 1s wait - Remaining: {remaining:.1f}")

    # Fixed Window
    print(f"\nFixed Window: 3 requests/5s")
    rule2 = RateLimitRule(max_requests=3, window_seconds=5)
    limiter2 = RateLimiter(FixedWindowCounter(rule2))

    for i in range(5):
        result = limiter2.allow_request(user)
        remaining = limiter2.get_remaining(user)
        print(f"  Request {i+1}: {result.value} (Remaining: {remaining})")
        time.sleep(0.1)

    # Leaky Bucket
    print(f"\nLeaky Bucket: 4 requests/10s (1 req per 2.5s)")
    rule3 = RateLimitRule(max_requests=4, window_seconds=10)
    limiter3 = RateLimiter(LeakyBucket(rule3))

    for i in range(6):
        result = limiter3.allow_request(user)
        remaining = limiter3.get_remaining(user)
        print(f"  Request {i+1}: {result.value} (Remaining: {remaining})")
        time.sleep(0.1)

    # Middleware demo
    print(f"\nRate Limit Middleware:")
    print("-" * 40)
    middleware = RateLimitMiddleware()
    middleware.add_rule("/api/login", RateLimitRule(3, 60), "sliding_window_log")
    middleware.add_rule("/api/search", RateLimitRule(10, 60), "token_bucket")

    for i in range(5):
        result = middleware.check_rate_limit("/api/login", "user_1")
        print(f"  Login attempt {i+1}: {result.value}")


if __name__ == "__main__":
    demo()
