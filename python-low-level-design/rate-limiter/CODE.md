# Rate Limiter — Implementation

> Five algorithms behind one Strategy interface, a per-key thread-safe `RateLimiter`, and a middleware that maps endpoints to limiters. Python 3.10+, stdlib only.

---

## 🗺️ Shape of the code

| Piece | Role |
|-------|------|
| `RateLimitRule` | Frozen value object: `max_requests` per `window_seconds`; validates itself; `rate` = requests/second |
| `RateLimitDecision` | What the HTTP layer needs: `allowed`, `remaining`, `retry_after` (drives `429` + `Retry-After`) |
| `RateLimitAlgorithm[S]` | Strategy ABC. A *policy* over a per-key state object `S`: `new_state`, `try_acquire`, `remaining`, `retry_after`, `is_idle` |
| `TokenBucket`, `LeakyBucket` | Bucket policies over `_BucketState(level, last)` |
| `FixedWindowCounter`, `SlidingWindowCounter` | Window policies over `_WindowState(window, count, prev_count)` |
| `SlidingWindowLog` | Exact policy over `_LogState(timestamps: deque)` |
| `RateLimiterFactory` | Config string → algorithm, with `register()` for new ones |
| `RateLimiter` | Owns the key → state map and **all** locking; injectable `clock` |
| `RateLimitMiddleware` | Endpoint → `RateLimiter`; key is `"{endpoint}:{client_id}"`; unknown endpoints are `UNLIMITED` |
| `FakeClock` | Deterministic time for the demo and tests |

---

## 🔑 Key design decisions

### 1. Algorithms are stateless policies; state lives per key

```python
class RateLimitAlgorithm(ABC, Generic[S]):
    def new_state(self, now: float) -> S: ...
    def try_acquire(self, state: S, now: float) -> bool: ...   # check AND consume, one step
    def remaining(self, state: S, now: float) -> int: ...
    def retry_after(self, state: S, now: float) -> float: ...
```

The algorithm never owns a `dict[key, ...]`. That buys three things:

- **Concurrency is one concern in one place.** The algorithm is plain single-threaded math; `RateLimiter` decides how state is locked. Swapping the in-process map for Redis would replace `RateLimiter`, not the algorithms' interface.
- **Testable with a fake clock.** `now` is a parameter, so tests can sit exactly on window boundaries.
- **Uniform eviction.** `is_idle(state, now)` (default: "remaining is back at the full quota") tells the limiter when a key can be forgotten without changing any future decision.

### 2. Per-key locks, not one global lock

```python
def _with_state(self, key, fn):
    while True:
        entry = self._entry(key, self._clock())   # map lock: get-or-create only
        with entry.lock:                          # key lock: the whole check-and-consume
            if entry.evicted:                     # lost a race with evict_idle -> retry
                continue
            return fn(entry.state, self._clock())
```

- The map lock is held for a dict lookup only. Requests for different keys never contend; requests for one key serialise, so "is there a token? take it" is atomic. Without the key lock two threads can both see `level >= 1` and both consume the last token (the concurrency test detects exactly this).
- The clock is read **under** the key lock, so a key's timestamps never go backwards between two callers.
- **Lock order** is always map → key. The request path never holds both at once; `evict_idle` holds the map lock and only *try*-acquires key locks, so there is no deadlock.

### 3. Eviction without losing consumption

`evict_idle()` bounds memory to recently active keys. The subtle race: request A looks up entry E, the janitor evicts E (it looked idle), A then consumes from E, which is no longer in the map, and the next request creates a fresh full E'. That is one free request per race. The `evicted` flag closes it: A re-checks under the key lock and retries with the new entry. `test_eviction_between_lookup_and_lock_is_detected` forces that interleaving deterministically.

### 4. Monotonic, injected time

`clock` defaults to `time.monotonic`. Wall-clock time can jump (NTP step, manual change); a backwards jump with `time.time()` could make `elapsed` negative and drain a bucket, and a forward jump could refill it. The bucket refills also clamp `elapsed` at 0. (Across machines there is no shared monotonic clock; the distributed version uses Redis server time. See [High-Level Design](HIGH_LEVEL_DESIGN.md).)

### 5. Bounded memory per key

| Algorithm | State per key | Note |
|-----------|---------------|------|
| `TokenBucket` / `LeakyBucket` | 2 floats | |
| `FixedWindowCounter` | window index + count | rolls in place, so old windows never accumulate |
| `SlidingWindowCounter` | window index + 2 counts | skipping a whole window zeroes both counts |
| `SlidingWindowLog` | ≤ `max_requests` timestamps | only *accepted* requests are logged, so a flood of rejected requests cannot grow it |

---

## 🧮 The algorithms, precisely

**Token bucket.** Capacity `max_requests`, refill `rate = max/window` per second, applied lazily on each call: `level = min(cap, level + elapsed * rate)`. Permits bursts up to capacity, then a sustained `rate`. `retry_after = (1 - level) / rate`.

**Leaky bucket (as a meter).** Each request adds one unit; the bucket drains at `rate`; a request that would overflow is rejected. As a policer it is equivalent to GCRA and is the mirror image of the token bucket (same burst and same sustained rate for the same parameters, which is why the demo output is identical). The *queue* form (a shaper that delays instead of rejecting) needs a worker draining a bounded queue and does not fit an allow/deny API.

**Fixed window.** Counter per aligned window `[k·W, (k+1)·W)`. Cheapest, but up to `2 × max` requests can pass in a short span around a boundary (`test_boundary_burst_lets_twice_the_limit_through`).

**Sliding window log.** Exact. Keeps accepted timestamps in `(now − W, now]`; an entry stops counting exactly `W` seconds after it was accepted. Amortised O(1) per call, O(max) memory per key.

**Sliding window counter.** `estimate = prev_count × (1 − fraction_elapsed) + count`. Two integers per key; assumes the previous window was uniform, so it can err in either direction (Cloudflare measured 0.003% of requests misjudged on real traffic). `retry_after` solves the estimate for the moment it drops to `max − 1`.

---

## 🧩 Where to extend

| Requirement | Change |
|-------------|--------|
| New algorithm (e.g. GCRA) | Subclass `RateLimitAlgorithm`, `RateLimiterFactory.register("gcra", Gcra)` |
| Separate burst size and sustained rate | Add `burst` to `RateLimitRule`; `TokenBucket` uses it as capacity |
| Weighted requests (cost > 1) | Add `cost: int = 1` to `try_acquire`; buckets subtract `cost`, logs append `cost` entries |
| Multiple limits per request (10/s **and** 1000/day) | Composite limiter that checks all, then consumes all. Peek-then-consume across limiters is racy, so either lock the keys in a fixed order or accept a small overshoot |
| Distributed limits | Replace `RateLimiter`'s map with a Redis Lua script per algorithm (see Interview Questions Q2) |
| Hot-reloaded rules | Middleware swaps an immutable `dict` reference on reload instead of mutating it |

---

## ▶️ How to run

```bash
cd python-low-level-design/rate-limiter
python3 rate_limiter.py                    # deterministic demo (FakeClock)
python3 -m unittest test_rate_limiter -v   # 21 tests, < 1 s
```

The tests cover each algorithm's exact boundaries, `retry_after` accuracy for every algorithm, per-key isolation, eviction, and two concurrency properties: no over-admission under 16 threads, and no lost consumption when eviction races a request.

---

## 📄 Full source

<!-- source: rate_limiter.py -->
```python
"""
Rate Limiter - Low Level Design
-------------------------------
Five algorithms behind one Strategy interface, a thread-safe per-key limiter,
and a middleware that maps endpoints to limiters.

Key design decisions
  * Algorithms are *policies* over a small per-key state object. They hold no
    shared mutable state themselves, so they are trivially testable with a
    fake clock and need no locking of their own.
  * `RateLimiter` owns concurrency: one short-lived lock guards the key -> entry
    map (get-or-create only), and each key has its own lock. Requests for
    different keys never contend; requests for the same key serialise, which
    makes every check-then-consume atomic.
  * Time is injected (`clock`), defaulting to `time.monotonic` so wall-clock
    jumps (NTP, DST) cannot refill buckets or reopen windows.
  * Memory is bounded per key (the log is capped at `max_requests` entries, the
    counters keep two numbers) and idle keys can be evicted with `evict_idle`.

Python 3.10+, stdlib only.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

Clock = Callable[[], float]


# --- Value objects -----------------------------------------------------------

@dataclass(frozen=True)
class RateLimitRule:
    """`max_requests` per `window_seconds`. For the buckets this means
    capacity = max_requests and refill/leak rate = max_requests / window."""

    max_requests: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

    @property
    def rate(self) -> float:
        """Requests per second."""
        return self.max_requests / self.window_seconds


@dataclass(frozen=True)
class RateLimitDecision:
    """What the caller needs to build a 200 or a 429 with headers."""

    allowed: bool
    remaining: int          # requests still allowed right now (X-RateLimit-Remaining)
    retry_after: float      # seconds until the next request could pass (Retry-After); 0 if allowed


UNLIMITED = RateLimitDecision(allowed=True, remaining=sys.maxsize, retry_after=0.0)


# --- Algorithm strategies ----------------------------------------------------

S = TypeVar("S")


class RateLimitAlgorithm(ABC, Generic[S]):
    """Strategy interface. Implementations are NOT thread-safe on purpose: the
    caller (RateLimiter) holds the key's lock around every call."""

    def __init__(self, rule: RateLimitRule) -> None:
        self.rule = rule

    @abstractmethod
    def new_state(self, now: float) -> S:
        """Fresh state for a key seen for the first time."""

    @abstractmethod
    def try_acquire(self, state: S, now: float) -> bool:
        """Consume one permit if available. Must be check-and-consume in one step."""

    @abstractmethod
    def remaining(self, state: S, now: float) -> int:
        """Permits available at `now` without consuming any."""

    @abstractmethod
    def retry_after(self, state: S, now: float) -> float:
        """Seconds until `try_acquire` could succeed (0 if it would now)."""

    def is_idle(self, state: S, now: float) -> bool:
        """True when the state is indistinguishable from a fresh one, so the key
        can be dropped without changing any future decision."""
        return self.remaining(state, now) >= self.rule.max_requests


# Token bucket ----------------------------------------------------------------

@dataclass
class _BucketState:
    level: float          # tokens available (token bucket) or water level (leaky bucket)
    last: float           # last time the level was brought up to date


class TokenBucket(RateLimitAlgorithm[_BucketState]):
    """Bucket of `max_requests` tokens refilled continuously at `rule.rate`.
    Allows a burst of up to capacity, then a sustained `rate`. O(1) time/space."""

    def new_state(self, now: float) -> _BucketState:
        return _BucketState(level=float(self.rule.max_requests), last=now)

    def _refill(self, s: _BucketState, now: float) -> None:
        elapsed = max(0.0, now - s.last)   # never let a backwards clock drain tokens
        s.level = min(float(self.rule.max_requests), s.level + elapsed * self.rule.rate)
        s.last = now

    def try_acquire(self, state: _BucketState, now: float) -> bool:
        self._refill(state, now)
        if state.level >= 1.0:
            state.level -= 1.0
            return True
        return False

    def remaining(self, state: _BucketState, now: float) -> int:
        self._refill(state, now)
        return int(state.level)

    def retry_after(self, state: _BucketState, now: float) -> float:
        self._refill(state, now)
        return 0.0 if state.level >= 1.0 else (1.0 - state.level) / self.rule.rate


# Leaky bucket (as a meter) ---------------------------------------------------

class LeakyBucket(RateLimitAlgorithm[_BucketState]):
    """Leaky bucket *as a meter* (policer): each request adds one unit of water,
    the bucket drains at `rule.rate`, and a request that would overflow
    capacity is rejected. Equivalent to GCRA and the mirror image of the token
    bucket. The *queue* variant (shaper) delays requests instead of rejecting
    them; that belongs in a worker that drains a bounded queue, not in an
    allow/deny check."""

    def new_state(self, now: float) -> _BucketState:
        return _BucketState(level=0.0, last=now)

    def _leak(self, s: _BucketState, now: float) -> None:
        elapsed = max(0.0, now - s.last)
        s.level = max(0.0, s.level - elapsed * self.rule.rate)
        s.last = now

    def try_acquire(self, state: _BucketState, now: float) -> bool:
        self._leak(state, now)
        if state.level + 1.0 <= self.rule.max_requests:
            state.level += 1.0
            return True
        return False

    def remaining(self, state: _BucketState, now: float) -> int:
        self._leak(state, now)
        return int(self.rule.max_requests - state.level)

    def retry_after(self, state: _BucketState, now: float) -> float:
        self._leak(state, now)
        overflow = state.level + 1.0 - self.rule.max_requests
        return 0.0 if overflow <= 0 else overflow / self.rule.rate


# Fixed window ----------------------------------------------------------------

@dataclass
class _WindowState:
    window: int           # index of the current window: floor(now / W)
    count: int = 0
    prev_count: int = 0   # only used by the sliding window counter


class FixedWindowCounter(RateLimitAlgorithm[_WindowState]):
    """One counter per aligned window [k*W, (k+1)*W). O(1). Weakness: up to
    2 * max_requests can pass in a short span straddling a boundary."""

    def _window(self, now: float) -> int:
        return math.floor(now / self.rule.window_seconds)

    def new_state(self, now: float) -> _WindowState:
        return _WindowState(window=self._window(now))

    def _roll(self, s: _WindowState, now: float) -> None:
        w = self._window(now)
        if w > s.window:
            s.window, s.count = w, 0

    def try_acquire(self, state: _WindowState, now: float) -> bool:
        self._roll(state, now)
        if state.count < self.rule.max_requests:
            state.count += 1
            return True
        return False

    def remaining(self, state: _WindowState, now: float) -> int:
        self._roll(state, now)
        return self.rule.max_requests - state.count

    def retry_after(self, state: _WindowState, now: float) -> float:
        self._roll(state, now)
        if state.count < self.rule.max_requests:
            return 0.0
        return (state.window + 1) * self.rule.window_seconds - now


# Sliding window log ----------------------------------------------------------

@dataclass
class _LogState:
    timestamps: deque[float] = field(default_factory=deque)


class SlidingWindowLog(RateLimitAlgorithm[_LogState]):
    """Exact: keeps the timestamp of each *accepted* request in (now - W, now].
    Memory O(max_requests) per key (rejected requests are not logged, so the
    deque never exceeds the limit); eviction is amortised O(1)."""

    def new_state(self, now: float) -> _LogState:
        return _LogState()

    def _evict(self, s: _LogState, now: float) -> None:
        cutoff = now - self.rule.window_seconds
        log = s.timestamps
        while log and log[0] <= cutoff:
            log.popleft()

    def try_acquire(self, state: _LogState, now: float) -> bool:
        self._evict(state, now)
        if len(state.timestamps) < self.rule.max_requests:
            state.timestamps.append(now)
            return True
        return False

    def remaining(self, state: _LogState, now: float) -> int:
        self._evict(state, now)
        return self.rule.max_requests - len(state.timestamps)

    def retry_after(self, state: _LogState, now: float) -> float:
        self._evict(state, now)
        if len(state.timestamps) < self.rule.max_requests:
            return 0.0
        return state.timestamps[0] + self.rule.window_seconds - now


# Sliding window counter ------------------------------------------------------

class SlidingWindowCounter(RateLimitAlgorithm[_WindowState]):
    """Approximates the sliding log with two counters:
        estimate = prev_count * (1 - elapsed_fraction) + count
    O(1) memory. Assumes the previous window's requests were evenly spread, so
    it can be off in either direction; Cloudflare measured ~0.003% of requests
    misjudged on real traffic."""

    def _window(self, now: float) -> int:
        return math.floor(now / self.rule.window_seconds)

    def new_state(self, now: float) -> _WindowState:
        return _WindowState(window=self._window(now))

    def _roll(self, s: _WindowState, now: float) -> None:
        w = self._window(now)
        if w == s.window + 1:
            s.window, s.prev_count, s.count = w, s.count, 0
        elif w > s.window + 1:              # skipped a whole window: both are stale
            s.window, s.prev_count, s.count = w, 0, 0

    def _fraction(self, s: _WindowState, now: float) -> float:
        return (now - s.window * self.rule.window_seconds) / self.rule.window_seconds

    def _estimate(self, s: _WindowState, now: float) -> float:
        return s.prev_count * (1.0 - self._fraction(s, now)) + s.count

    def try_acquire(self, state: _WindowState, now: float) -> bool:
        self._roll(state, now)
        if self._estimate(state, now) + 1 <= self.rule.max_requests:
            state.count += 1
            return True
        return False

    def remaining(self, state: _WindowState, now: float) -> int:
        self._roll(state, now)
        return max(0, math.floor(self.rule.max_requests - self._estimate(state, now)))

    def retry_after(self, state: _WindowState, now: float) -> float:
        self._roll(state, now)
        limit, w = self.rule.max_requests, self.rule.window_seconds
        if self._estimate(state, now) + 1 <= limit:
            return 0.0
        start = state.window * w
        headroom = limit - 1 - state.count          # room the decaying prev_count must shrink into
        if headroom >= 0 and state.prev_count > 0:
            # prev * (1 - f) <= headroom  =>  f >= 1 - headroom / prev
            return max(0.0, start + w * (1 - headroom / state.prev_count) - now)
        # Current window alone is over the limit: wait for the next window,
        # where today's count becomes the decaying previous count.
        return max(0.0, start + w + w * (1 - (limit - 1) / state.count) - now)


# --- Factory -----------------------------------------------------------------

class RateLimiterFactory:
    """Config string -> algorithm. `register` keeps it open for extension."""

    _algorithms: dict[str, type[RateLimitAlgorithm]] = {
        "token_bucket": TokenBucket,
        "leaky_bucket": LeakyBucket,
        "fixed_window": FixedWindowCounter,
        "sliding_window_log": SlidingWindowLog,
        "sliding_window_counter": SlidingWindowCounter,
    }

    @classmethod
    def register(cls, name: str, algo: type[RateLimitAlgorithm]) -> None:
        cls._algorithms[name] = algo

    @classmethod
    def create(cls, name: str, rule: RateLimitRule) -> RateLimitAlgorithm:
        try:
            return cls._algorithms[name](rule)
        except KeyError:
            raise ValueError(f"Unknown algorithm: {name!r}") from None


# --- Thread-safe limiter -----------------------------------------------------

class _Entry:
    __slots__ = ("lock", "state", "evicted")

    def __init__(self, state: object) -> None:
        self.lock = threading.Lock()
        self.state = state
        self.evicted = False


class RateLimiter:
    """Applies one algorithm to many keys with per-key locking."""

    def __init__(self, algorithm: RateLimitAlgorithm, clock: Clock = time.monotonic) -> None:
        self._algo = algorithm
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._map_lock = threading.Lock()

    @property
    def algorithm(self) -> RateLimitAlgorithm:
        return self._algo

    def _entry(self, key: str, now: float) -> _Entry:
        with self._map_lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = _Entry(self._algo.new_state(now))
            return entry

    def _with_state(self, key: str, fn: Callable[[object, float], RateLimitDecision]) -> RateLimitDecision:
        while True:
            now = self._clock()
            entry = self._entry(key, now)
            with entry.lock:
                if entry.evicted:   # lost a race with evict_idle; use the fresh entry
                    continue
                # Read the clock under the key lock so time is monotonic per key.
                return fn(entry.state, self._clock())

    def try_acquire(self, key: str) -> RateLimitDecision:
        def go(state: object, now: float) -> RateLimitDecision:
            ok = self._algo.try_acquire(state, now)
            return RateLimitDecision(
                allowed=ok,
                remaining=self._algo.remaining(state, now),
                retry_after=0.0 if ok else self._algo.retry_after(state, now),
            )
        return self._with_state(key, go)

    def allow(self, key: str) -> bool:
        return self.try_acquire(key).allowed

    def peek(self, key: str) -> RateLimitDecision:
        """Current status without consuming a permit."""
        def go(state: object, now: float) -> RateLimitDecision:
            wait = self._algo.retry_after(state, now)
            return RateLimitDecision(wait == 0.0, self._algo.remaining(state, now), wait)
        return self._with_state(key, go)

    def reset(self, key: str) -> None:
        with self._map_lock:
            entry = self._entries.pop(key, None)
        if entry is not None:
            with entry.lock:
                entry.evicted = True

    def evict_idle(self) -> int:
        """Drop keys whose state equals a fresh one. Run periodically (e.g. from a
        janitor thread) to bound memory to the set of recently active keys.
        Lock order is map lock -> key lock everywhere, so this cannot deadlock."""
        removed = 0
        with self._map_lock:
            for key, entry in list(self._entries.items()):
                if not entry.lock.acquire(blocking=False):
                    continue                     # in use right now, so not idle
                try:
                    if self._algo.is_idle(entry.state, self._clock()):
                        entry.evicted = True
                        del self._entries[key]
                        removed += 1
                finally:
                    entry.lock.release()
        return removed

    def __len__(self) -> int:
        with self._map_lock:
            return len(self._entries)


# --- Middleware ---------------------------------------------------------------

class RateLimitMiddleware:
    """Endpoint -> limiter; the key is (endpoint, client). Unknown endpoints are
    unlimited. Rules are registered at startup; a production version would
    hot-swap an immutable rule map instead of mutating it."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._limiters: dict[str, RateLimiter] = {}

    def add_rule(self, endpoint: str, rule: RateLimitRule, algorithm: str = "token_bucket") -> None:
        self._limiters[endpoint] = RateLimiter(RateLimiterFactory.create(algorithm, rule), self._clock)

    def check(self, endpoint: str, client_id: str) -> RateLimitDecision:
        limiter = self._limiters.get(endpoint)
        if limiter is None:
            return UNLIMITED
        return limiter.try_acquire(f"{endpoint}:{client_id}")


# --- Demo ---------------------------------------------------------------------

class FakeClock:
    """Deterministic clock for the demo and tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def demo() -> None:
    rule = RateLimitRule(max_requests=5, window_seconds=10)   # 5 per 10 s = 0.5 req/s

    for name in ("token_bucket", "leaky_bucket", "fixed_window",
                 "sliding_window_log", "sliding_window_counter"):
        clock = FakeClock(0.0)
        limiter = RateLimiter(RateLimiterFactory.create(name, rule), clock)
        print(f"\n{name}: 5 requests / 10 s")
        for i in range(7):
            d = limiter.try_acquire("user_1")
            status = "allowed" if d.allowed else f"denied  retry_after={d.retry_after:.2f}s"
            print(f"  t={clock.now:4.1f}s req {i + 1}: {status:28} remaining={d.remaining}")
            clock.advance(0.5)
        clock.advance(4.0)
        d = limiter.try_acquire("user_1")
        print(f"  t={clock.now:4.1f}s after a 4 s pause: {'allowed' if d.allowed else 'denied'},"
              f" remaining={d.remaining}")
        clock.advance(30.0)
        print(f"  idle keys evicted after 30 s quiet: {limiter.evict_idle()}")

    clock = FakeClock(0.0)
    print("\nMiddleware: /login 3 per 60 s (sliding log), /search unlimited")
    mw = RateLimitMiddleware(clock)
    mw.add_rule("/login", RateLimitRule(3, 60), "sliding_window_log")
    for i in range(4):
        d = mw.check("/login", "alice")
        print(f"  login {i + 1}: {'200' if d.allowed else f'429 Retry-After: {math.ceil(d.retry_after)}'}")
    print(f"  /search: {'200' if mw.check('/search', 'alice').allowed else '429'}")


if __name__ == "__main__":
    demo()
```
<!-- /source -->
