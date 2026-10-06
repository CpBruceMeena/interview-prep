"""
Resilience Library: Circuit Breaker + Retry + Bulkhead + Timeout - Low Level Design
-----------------------------------------------------------------------------------
- CircuitBreaker: CLOSED -> OPEN -> HALF_OPEN state machine driven by the
  failure RATE over a sliding window (count-based or time-based), with a
  minimum-calls guard and a fixed number of half-open probe calls.
- Retry: capped exponential backoff with jitter (full / equal / none), a
  retry-on predicate, and an optional gRPC-style RetryBudget (token throttle)
  so retries cannot multiply load during an outage.
- Bulkhead: caps concurrent calls into one dependency (semaphore).
- TimeLimiter: bounds how long the caller waits.
- Clock and sleep are injected, so every state transition is testable
  without real time. Every component is usable as a decorator.

Composition order (outermost first), close to Resilience4j's default
(which puts Bulkhead innermost, under TimeLimiter):
    Retry( CircuitBreaker( Bulkhead( TimeLimiter( fn ) ) ) )

Run:  python3 circuit_breaker.py
"""

from __future__ import annotations

import functools
import random
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Clock (injectable)
# --------------------------------------------------------------------------- #

class Clock(Protocol):
    def now(self) -> float: ...           # monotonic seconds
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()          # never time.time(): wall clock can jump back

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class ManualClock:
    """Deterministic clock for tests and the demo: sleep() just advances time."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class CallNotPermittedError(Exception):
    """Fast failure: the breaker is OPEN (or HALF_OPEN with all probes in use)."""

    def __init__(self, name: str, state: "CircuitState", retry_after: float) -> None:
        super().__init__(f"circuit '{name}' is {state.value}; retry after {retry_after:.2f}s")
        self.state = state
        self.retry_after = retry_after


class BulkheadFullError(Exception):
    pass


class CallTimeoutError(TimeoutError):
    pass


class RetryBudgetExhaustedError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Sliding windows (Strategy)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class WindowSnapshot:
    total: int
    failures: int

    @property
    def failure_rate(self) -> float:
        return self.failures / self.total if self.total else 0.0


class SlidingWindow(ABC):
    """Not thread-safe on its own; the CircuitBreaker's lock guards it."""

    @abstractmethod
    def record(self, success: bool, now: float) -> None: ...

    @abstractmethod
    def snapshot(self, now: float) -> WindowSnapshot: ...

    @abstractmethod
    def reset(self) -> None: ...


class CountBasedWindow(SlidingWindow):
    """Last N outcomes in a ring buffer with running totals. O(1) record and
    snapshot, O(N) memory."""

    def __init__(self, size: int) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        self._size = size
        self.reset()

    def reset(self) -> None:
        self._ring: list[Optional[bool]] = [None] * self._size
        self._idx = 0
        self._total = 0
        self._failures = 0

    def record(self, success: bool, now: float) -> None:
        evicted = self._ring[self._idx]
        if evicted is None:
            self._total += 1
        elif evicted is False:
            self._failures -= 1
        if not success:
            self._failures += 1
        self._ring[self._idx] = success
        self._idx = (self._idx + 1) % self._size

    def snapshot(self, now: float) -> WindowSnapshot:
        return WindowSnapshot(self._total, self._failures)


class TimeBasedWindow(SlidingWindow):
    """Outcomes in the last `seconds` seconds, aggregated into one bucket per
    second (Resilience4j's approach). O(1) memory per bucket regardless of
    call rate; resolution is one bucket, so the window is 'last N whole seconds'."""

    def __init__(self, seconds: int) -> None:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._n = seconds
        self.reset()

    def reset(self) -> None:
        self._epoch = [-1] * self._n     # which absolute second each bucket holds
        self._totals = [0] * self._n
        self._failures = [0] * self._n

    def record(self, success: bool, now: float) -> None:
        second = int(now)
        i = second % self._n
        if self._epoch[i] != second:     # bucket holds an old second: recycle it
            self._epoch[i], self._totals[i], self._failures[i] = second, 0, 0
        self._totals[i] += 1
        if not success:
            self._failures[i] += 1

    def snapshot(self, now: float) -> WindowSnapshot:
        oldest = int(now) - self._n + 1
        total = failures = 0
        for i in range(self._n):
            if self._epoch[i] >= oldest:
                total += self._totals[i]
                failures += self._failures[i]
        return WindowSnapshot(total, failures)


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class WindowType(Enum):
    COUNT = "COUNT"
    TIME = "TIME"


def _default_is_failure(exc: BaseException) -> bool:
    # Caller bugs / bad input say nothing about the dependency's health, and a
    # full local bulkhead is our overload, not theirs.
    return not isinstance(exc, (ValueError, TypeError, KeyError, BulkheadFullError))


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_rate_threshold: float = 0.5        # open when rate >= this
    window_type: WindowType = WindowType.COUNT
    window_size: int = 20                      # calls (COUNT) or seconds (TIME)
    minimum_calls: int = 10                    # don't judge on 2 calls
    open_duration: float = 30.0                # seconds before probing
    half_open_max_calls: int = 3               # probes; all must succeed to close
    is_failure: Callable[[BaseException], bool] = _default_is_failure

    def __post_init__(self) -> None:
        if not 0 < self.failure_rate_threshold <= 1:
            raise ValueError("failure_rate_threshold must be in (0, 1]")
        if self.minimum_calls < 1 or self.half_open_max_calls < 1 or self.open_duration < 0:
            raise ValueError("invalid circuit breaker config")


@dataclass(frozen=True)
class Permit:
    """Ties a call's outcome to the state generation it was admitted under, so
    a slow call admitted while CLOSED cannot vote in a later HALF_OPEN trial."""
    generation: int
    state: CircuitState


StateListener = Callable[[str, CircuitState, CircuitState], None]


class CircuitBreaker:
    def __init__(self, name: str, config: CircuitBreakerConfig = CircuitBreakerConfig(),
                 clock: Optional[Clock] = None,
                 listeners: tuple[StateListener, ...] = ()) -> None:
        self.name = name
        self.config = config
        self._clock = clock or SystemClock()
        self._listeners = listeners
        self._window: SlidingWindow = (CountBasedWindow(config.window_size)
                                       if config.window_type is WindowType.COUNT
                                       else TimeBasedWindow(config.window_size))
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._generation = 0
        self._opened_at = 0.0
        self._probes_issued = 0
        self._probe_successes = 0

    # ---- public API ---------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        transitions: list[tuple[CircuitState, CircuitState]] = []
        with self._lock:
            self._maybe_half_open(transitions)
            state = self._state
        self._notify(transitions)
        return state

    def metrics(self) -> WindowSnapshot:
        with self._lock:
            return self._window.snapshot(self._clock.now())

    def acquire(self) -> Permit:
        """Admit a call or raise CallNotPermittedError. Check-and-reserve is
        one critical section, so N threads can't all grab the last probe."""
        transitions: list[tuple[CircuitState, CircuitState]] = []
        with self._lock:
            self._maybe_half_open(transitions)
            if self._state is CircuitState.CLOSED:
                permit = Permit(self._generation, self._state)
            elif self._state is CircuitState.HALF_OPEN and \
                    self._probes_issued < self.config.half_open_max_calls:
                self._probes_issued += 1
                permit = Permit(self._generation, self._state)
            else:
                retry_after = max(0.0, self._opened_at + self.config.open_duration
                                  - self._clock.now()) if self._state is CircuitState.OPEN else 0.0
                exc = CallNotPermittedError(self.name, self._state, retry_after)
                permit = None
        self._notify(transitions)
        if permit is None:
            raise exc
        return permit

    def on_success(self, permit: Permit) -> None:
        self._on_result(permit, success=True)

    def on_error(self, permit: Permit, exc: BaseException) -> None:
        if self.config.is_failure(exc):
            self._on_result(permit, success=False)
        else:
            self._release(permit)   # not the dependency's fault: free the probe slot, don't count

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        permit = self.acquire()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:     # incl. KeyboardInterrupt: must release a probe slot
            self.on_error(permit, exc)
            raise
        self.on_success(permit)
        return result

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)
        return wrapper

    def reset(self) -> None:
        """Operator override: force CLOSED with an empty window."""
        transitions: list[tuple[CircuitState, CircuitState]] = []
        with self._lock:
            self._transition(CircuitState.CLOSED, transitions)
        self._notify(transitions)

    # ---- state machine (all called with self._lock held) --------------------

    def _on_result(self, permit: Permit, success: bool) -> None:
        transitions: list[tuple[CircuitState, CircuitState]] = []
        with self._lock:
            if permit.generation != self._generation:
                return                     # stale: admitted under an earlier state
            now = self._clock.now()
            if self._state is CircuitState.CLOSED:
                self._window.record(success, now)
                snap = self._window.snapshot(now)
                if snap.total >= self.config.minimum_calls and \
                        snap.failure_rate >= self.config.failure_rate_threshold:
                    self._transition(CircuitState.OPEN, transitions)
            elif self._state is CircuitState.HALF_OPEN:
                if not success:
                    self._transition(CircuitState.OPEN, transitions)   # one bad probe re-opens
                else:
                    self._probe_successes += 1
                    if self._probe_successes >= self.config.half_open_max_calls:
                        self._transition(CircuitState.CLOSED, transitions)
        self._notify(transitions)

    def _release(self, permit: Permit) -> None:
        with self._lock:
            if permit.generation == self._generation and self._state is CircuitState.HALF_OPEN:
                self._probes_issued -= 1

    def _maybe_half_open(self, transitions: list) -> None:
        # Lazy OPEN -> HALF_OPEN on the next access: no timer thread needed.
        if self._state is CircuitState.OPEN and \
                self._clock.now() - self._opened_at >= self.config.open_duration:
            self._transition(CircuitState.HALF_OPEN, transitions)

    def _transition(self, new: CircuitState, transitions: list) -> None:
        old = self._state
        self._state = new
        self._generation += 1
        self._probes_issued = self._probe_successes = 0
        if new is CircuitState.OPEN:
            self._opened_at = self._clock.now()
        if new is CircuitState.CLOSED:
            self._window.reset()           # start fresh; old failures are history
        if old is not new:
            transitions.append((old, new))

    def _notify(self, transitions: list[tuple[CircuitState, CircuitState]]) -> None:
        # Outside the lock: a listener that logs/metrics slowly must not block callers.
        for old, new in transitions:
            for listener in self._listeners:
                listener(self.name, old, new)


# --------------------------------------------------------------------------- #
# Retry with backoff + jitter + budget
# --------------------------------------------------------------------------- #

class Jitter(Enum):
    NONE = "NONE"      # synchronized retries: thundering herd
    FULL = "FULL"      # uniform(0, cap)          - AWS recommendation, best spread
    EQUAL = "EQUAL"    # cap/2 + uniform(0, cap/2) - guarantees a minimum wait


class RetryBudget:
    """gRPC-style retry throttling. Tokens start at max_tokens; each failed
    attempt costs 1, each success refunds token_ratio. Retries are allowed only
    while tokens > max_tokens / 2, so when most calls fail, retries stop and
    load stays ~1x instead of max_attempts x."""

    def __init__(self, max_tokens: float = 10.0, token_ratio: float = 0.1) -> None:
        self._max = max_tokens
        self._ratio = token_ratio
        self._tokens = max_tokens
        self._lock = threading.Lock()

    def on_success(self) -> None:
        with self._lock:
            self._tokens = min(self._max, self._tokens + self._ratio)

    def on_failure(self) -> None:
        with self._lock:
            self._tokens = max(0.0, self._tokens - 1)

    def can_retry(self) -> bool:
        with self._lock:
            return self._tokens > self._max / 2

    @property
    def tokens(self) -> float:
        with self._lock:
            return self._tokens


def _default_retry_on(exc: BaseException) -> bool:
    # Transient transport failures only. Never retry an open circuit (pointless
    # until open_duration passes) or a full bulkhead (it would add load).
    return isinstance(exc, (ConnectionError, TimeoutError))


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3                  # total attempts, including the first
    base_delay: float = 0.1
    max_delay: float = 5.0
    multiplier: float = 2.0
    jitter: Jitter = Jitter.FULL
    retry_on: Callable[[BaseException], bool] = _default_retry_on

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay < 0 or self.max_delay < self.base_delay:
            raise ValueError("invalid retry config")


class Retry:
    """Only safe for idempotent operations (or ones carrying an idempotency key)."""

    def __init__(self, config: RetryConfig = RetryConfig(), clock: Optional[Clock] = None,
                 budget: Optional[RetryBudget] = None, rng: Optional[random.Random] = None) -> None:
        self.config = config
        self._clock = clock or SystemClock()
        self._budget = budget
        self._rng = rng or random.Random()
        self._rng_lock = threading.Lock()    # random.Random is not documented thread-safe

    def backoff(self, retry_number: int) -> float:
        """Delay before retry #retry_number (1-based)."""
        c = self.config
        cap = min(c.max_delay, c.base_delay * c.multiplier ** (retry_number - 1))
        if c.jitter is Jitter.NONE:
            return cap
        with self._rng_lock:
            if c.jitter is Jitter.FULL:
                return self._rng.uniform(0, cap)
            return cap / 2 + self._rng.uniform(0, cap / 2)

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        attempt = 1
        while True:
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                retryable = self.config.retry_on(exc)
                if retryable and self._budget:
                    self._budget.on_failure()
                if not retryable or attempt >= self.config.max_attempts:
                    raise
                if self._budget and not self._budget.can_retry():
                    raise RetryBudgetExhaustedError("retry budget exhausted") from exc
                self._clock.sleep(self.backoff(attempt))
                attempt += 1
                continue
            if self._budget:
                self._budget.on_success()
            return result

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)
        return wrapper


# --------------------------------------------------------------------------- #
# Bulkhead and TimeLimiter
# --------------------------------------------------------------------------- #

class Bulkhead:
    """Semaphore bulkhead: at most max_concurrent calls in flight. Callers wait
    up to max_wait for a slot, then fail fast (bounded queueing, not unbounded)."""

    def __init__(self, name: str, max_concurrent: int, max_wait: float = 0.0) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.name = name
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self._max_wait = max_wait

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        acquired = self._sem.acquire(timeout=self._max_wait) if self._max_wait > 0 \
            else self._sem.acquire(blocking=False)
        if not acquired:
            raise BulkheadFullError(f"bulkhead '{self.name}' is full")
        try:
            return fn(*args, **kwargs)
        finally:
            self._sem.release()

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)
        return wrapper


class TimeLimiter:
    """Bounds how long the CALLER waits. Python threads can't be killed, so the
    work keeps running in the pool after a timeout; the pool size bounds how many
    abandoned calls can pile up. Real fix: pass a deadline down (socket timeouts,
    gRPC deadlines) so the work itself stops."""

    def __init__(self, timeout: float, executor: ThreadPoolExecutor) -> None:
        self.timeout = timeout
        self._executor = executor

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        future = self._executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=self.timeout)
        except FutureTimeout:
            future.cancel()                # only helps if it hasn't started yet
            raise CallTimeoutError(f"call exceeded {self.timeout}s") from None

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)
        return wrapper


def resilient(*, retry: Optional[Retry] = None, breaker: Optional[CircuitBreaker] = None,
              bulkhead: Optional[Bulkhead] = None, time_limiter: Optional[TimeLimiter] = None
              ) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Compose as Retry(CircuitBreaker(Bulkhead(TimeLimiter(fn)))): every retry
    attempt is seen (and can be refused) by the breaker; timeouts count as
    breaker failures; the bulkhead limits in-flight work, not queued retries."""
    def decorate(fn: Callable[..., T]) -> Callable[..., T]:
        wrapped = fn
        for layer in (time_limiter, bulkhead, breaker, retry):
            if layer is not None:
                wrapped = layer(wrapped)
        return functools.wraps(fn)(wrapped)
    return decorate


# --------------------------------------------------------------------------- #
# Demo (deterministic: ManualClock + seeded RNG)
# --------------------------------------------------------------------------- #

def main() -> None:
    clock = ManualClock()
    log = lambda name, old, new: print(f"  [{clock.now():5.1f}s] {name}: {old.value} -> {new.value}")
    breaker = CircuitBreaker(
        "inventory",
        CircuitBreakerConfig(failure_rate_threshold=0.5, window_size=10, minimum_calls=4,
                             open_duration=10.0, half_open_max_calls=2),
        clock=clock, listeners=(log,))

    healthy = {"value": True}

    @breaker
    def get_stock(sku: str) -> int:
        if not healthy["value"]:
            raise ConnectionError("inventory service unreachable")
        return 42

    print("== 1. Dependency fails; breaker opens once failure rate >= 50% over >= 4 calls ==")
    print("  ok:", get_stock("A"), get_stock("B"))
    healthy["value"] = False
    for _ in range(3):
        try:
            get_stock("A")
        except ConnectionError:
            pass
        except CallNotPermittedError as exc:
            print("  fast-fail:", exc)
    print("  state:", breaker.state.value, "| metrics:", breaker.metrics())

    print("\n== 2. While OPEN, calls fail fast without touching the dependency ==")
    try:
        get_stock("A")
    except CallNotPermittedError as exc:
        print("  fast-fail:", exc)

    print("\n== 3. After open_duration, 2 probes allowed; both succeed -> CLOSED ==")
    clock.advance(10)
    healthy["value"] = True
    print("  probe:", get_stock("A"), "| state:", breaker.state.value)
    print("  probe:", get_stock("B"), "| state:", breaker.state.value)

    print("\n== 4. Retry with full jitter + budget, wrapped around the breaker ==")
    flaky_calls = {"n": 0}
    retry = Retry(RetryConfig(max_attempts=4, base_delay=0.2, max_delay=2.0),
                  clock=clock, budget=RetryBudget(max_tokens=10, token_ratio=0.1),
                  rng=random.Random(7))

    @resilient(retry=retry, breaker=breaker)
    def reserve(order_id: str) -> str:            # idempotent: keyed by order_id
        flaky_calls["n"] += 1
        if flaky_calls["n"] < 3:
            raise TimeoutError("upstream timeout")
        return f"reserved:{order_id}"

    start = clock.now()
    print(f"  {reserve('ord-1')} after {flaky_calls['n']} attempts, "
          f"{clock.now() - start:.3f}s of backoff | delays drawn from caps 0.2s, 0.4s")
    print("  backoff caps:", [min(2.0, 0.2 * 2 ** i) for i in range(5)])

    print("\n== 5. Bulkhead: 1 slot, second concurrent caller is rejected ==")
    bulkhead = Bulkhead("reports", max_concurrent=1)
    inside, release = threading.Event(), threading.Event()

    @bulkhead
    def slow_report() -> str:
        inside.set()
        release.wait(1)
        return "report"

    t = threading.Thread(target=slow_report)
    t.start()
    inside.wait(1)
    try:
        slow_report()
    except BulkheadFullError as exc:
        print("  rejected:", exc)
    release.set()
    t.join()

    print("\n== 6. TimeLimiter: caller gives up after 50 ms ==")
    with ThreadPoolExecutor(max_workers=2) as pool:
        limiter = TimeLimiter(0.05, pool)
        stop = threading.Event()
        try:
            limiter.call(stop.wait, 1)
        except CallTimeoutError as exc:
            print("  timeout:", exc)
        stop.set()


if __name__ == "__main__":
    main()
