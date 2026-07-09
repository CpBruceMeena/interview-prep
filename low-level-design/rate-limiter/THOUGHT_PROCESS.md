# 🧠 Rate Limiter LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](rate-limiter-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What algorithms to support? (Token Bucket, Sliding Window, Fixed Window?) What's being rate-limited? (API endpoints, users, IPs?) What's the config format?

## Phase 1: Identify the Nouns

> *"A rate limiter restricts how many requests a user can make in a time window using various algorithms."*

| Noun | Decision | Why |
|------|----------|-----|
| RateLimitRule | Regular Class | Holds config (max_requests, window_seconds) |
| RateLimitAlgorithm | ABC | Strategy pattern for different algorithms |
| RateLimiter | Facade | Thread-safe wrapper with pluggable algorithm |
| RateLimitResult | Enum | ALLOWED or DENIED |
| RateLimitMiddleware | Regular | Applies rules to API endpoints |

## Phase 2: Enums First

```python
class RateLimitResult(Enum):
    ALLOWED = "Allowed"
    DENIED = "Denied"
```

That's it — this is a simple enum.

## Phase 3: dataclass vs `__init__`

- **`RateLimitRule`**: Could be a dataclass — it's passive data (max_requests, window_seconds). But regular class works too.
- **`RateLimiter`**: Regular — has behavior (`allow_request`, `get_remaining`)
- **Algorithms** (`TokenBucket`, `SlidingWindowLog`, etc.): Regular — each has complex internal state

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Check if allowed | `RateLimitAlgorithm.allow_request()` | Algorithm-specific logic |
| Track request count | Internal state of Algorithm | Each algorithm tracks differently |
| Refill tokens | `TokenBucket._refill()` | Bucket-specific math |
| Manage concurrent access | `RateLimiter` (via lock) | SRP: threading is a cross-cutting concern |
| Route to correct limiter | `RateLimitMiddleware` | Maps endpoints to limiters |

**Key insight:** The `RateLimiter` class wraps the algorithm with a lock. This separates *thread safety* from *algorithm logic*.

## Phase 5: Strategy Pattern

```python
class RateLimitAlgorithm(ABC):
    def allow_request(self, key, timestamp) -> RateLimitResult
    
class TokenBucket(RateLimitAlgorithm):      # Tokens refill at constant rate
class SlidingWindowLog(RateLimitAlgorithm):  # Timestamp-based sliding window
class FixedWindowCounter(RateLimitAlgorithm):  # Simple per-window counter
```

The `RateLimiter` delegates to any algorithm — they're swappable.

## Phase 6: Factory Pattern

```python
class RateLimiterFactory:
    _algorithms = {
        "token_bucket": TokenBucket,
        "sliding_window_log": SlidingWindowLog,
        "fixed_window": FixedWindowCounter,
    }
    @classmethod
    def create(cls, algorithm: str, rule: RateLimitRule) -> RateLimitAlgorithm:
        return cls._algorithms[algorithm](rule)
```

## Phase 7: Understanding the Algorithms

| Algorithm | Storage | Complexity | Best For |
|-----------|---------|------------|----------|
| Token Bucket | 2 numbers per key | O(1) | API rate limits, bursts |
| Sliding Window Log | List of timestamps | O(N) per check | Strict accuracy |
| Fixed Window Counter | 1 number per key | O(1) | Simple, high throughput |
| Sliding Window Counter | 2 numbers per key | O(1) | Good balance |

## Phase 8: Quick Checklist

✅ **Strategy Pattern:** Algorithms are swappable
✅ **SRP:** Thread safety separated from algorithm logic
✅ **Factory:** Easy to add new algorithms
✅ **Encapsulation:** Algorithm internals are hidden behind interface
