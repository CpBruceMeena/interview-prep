"""Run: python3 -m unittest test_circuit_breaker  (from this directory)"""

import random
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from circuit_breaker import (
    Bulkhead, BulkheadFullError, CallNotPermittedError, CallTimeoutError, CircuitBreaker,
    CircuitBreakerConfig, CircuitState, CountBasedWindow, Jitter, ManualClock, Retry,
    RetryBudget, RetryBudgetExhaustedError, RetryConfig, TimeBasedWindow, TimeLimiter,
    WindowType, resilient,
)


def boom():
    raise ConnectionError("down")


def ok():
    return "ok"


def make_breaker(clock, **overrides):
    cfg = dict(failure_rate_threshold=0.5, window_size=4, minimum_calls=4,
               open_duration=10.0, half_open_max_calls=2)
    cfg.update(overrides)
    return CircuitBreaker("dep", CircuitBreakerConfig(**cfg), clock=clock)


def drive(breaker, outcomes):
    for good in outcomes:
        try:
            breaker.call(ok if good else boom)
        except ConnectionError:
            pass


class TestWindows(unittest.TestCase):
    def test_count_window_evicts_oldest(self):
        w = CountBasedWindow(3)
        for success in (False, False, True, True):
            w.record(success, 0)
        snap = w.snapshot(0)
        self.assertEqual((snap.total, snap.failures), (3, 1))

    def test_time_window_expires_old_buckets(self):
        w = TimeBasedWindow(5)
        w.record(False, 0.5)
        w.record(True, 3.2)
        self.assertEqual(w.snapshot(4.9).failures, 1)
        self.assertEqual(w.snapshot(5.0).failures, 0)     # second 0 is out of [1, 5]
        self.assertEqual(w.snapshot(5.0).total, 1)
        w.record(False, 5.1)                              # reuses bucket 0
        self.assertEqual((w.snapshot(5.1).total, w.snapshot(5.1).failures), (2, 1))


class TestCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.transitions = []
        self.cb = make_breaker(self.clock)
        self.cb._listeners = (lambda n, o, s: self.transitions.append((o, s)),)

    def test_stays_closed_below_minimum_calls(self):
        drive(self.cb, [False, False, False])
        self.assertEqual(self.cb.state, CircuitState.CLOSED)

    def test_opens_at_failure_rate_threshold(self):
        drive(self.cb, [True, True, False, False])
        self.assertEqual(self.cb.state, CircuitState.OPEN)

    def test_stays_closed_below_threshold(self):
        drive(self.cb, [True, True, True, False])
        self.assertEqual(self.cb.state, CircuitState.CLOSED)

    def test_open_fails_fast_without_calling(self):
        drive(self.cb, [False] * 4)
        calls = []
        with self.assertRaises(CallNotPermittedError) as ctx:
            self.cb.call(lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.assertAlmostEqual(ctx.exception.retry_after, 10.0)

    def test_half_open_after_duration_then_close_on_probe_successes(self):
        drive(self.cb, [False] * 4)
        self.clock.advance(9.9)
        self.assertEqual(self.cb.state, CircuitState.OPEN)
        self.clock.advance(0.1)
        self.assertEqual(self.cb.state, CircuitState.HALF_OPEN)
        self.cb.call(ok)
        self.assertEqual(self.cb.state, CircuitState.HALF_OPEN)
        self.cb.call(ok)
        self.assertEqual(self.cb.state, CircuitState.CLOSED)
        self.assertEqual(self.cb.metrics().total, 0, "window resets on close")
        self.assertEqual(self.transitions, [
            (CircuitState.CLOSED, CircuitState.OPEN),
            (CircuitState.OPEN, CircuitState.HALF_OPEN),
            (CircuitState.HALF_OPEN, CircuitState.CLOSED)])

    def test_failed_probe_reopens_and_restarts_timer(self):
        drive(self.cb, [False] * 4)
        self.clock.advance(10)
        drive(self.cb, [False])
        self.assertEqual(self.cb.state, CircuitState.OPEN)
        self.clock.advance(5)
        self.assertEqual(self.cb.state, CircuitState.OPEN)

    def test_half_open_limits_probes(self):
        drive(self.cb, [False] * 4)
        self.clock.advance(10)
        self.cb.acquire()
        self.cb.acquire()
        with self.assertRaises(CallNotPermittedError):
            self.cb.acquire()

    def test_ignored_exception_does_not_count_and_frees_probe(self):
        def bad_input():
            raise ValueError("caller bug")
        for _ in range(10):
            with self.assertRaises(ValueError):
                self.cb.call(bad_input)
        self.assertEqual(self.cb.metrics().total, 0)
        drive(self.cb, [False] * 4)
        self.clock.advance(10)
        for _ in range(5):                      # would exhaust probes if not released
            with self.assertRaises(ValueError):
                self.cb.call(bad_input)
        self.cb.call(ok)
        self.cb.call(ok)
        self.assertEqual(self.cb.state, CircuitState.CLOSED)

    def test_stale_result_from_previous_generation_is_ignored(self):
        slow = self.cb.acquire()                 # admitted while CLOSED
        drive(self.cb, [False] * 4)              # opens
        self.clock.advance(10)                   # half-open
        self.cb.on_error(slow, ConnectionError())   # late failure must not re-open
        self.assertEqual(self.cb.state, CircuitState.HALF_OPEN)

    def test_time_based_window(self):
        cb = make_breaker(self.clock, window_type=WindowType.TIME, window_size=10, minimum_calls=3)
        drive(cb, [False, False])
        self.clock.advance(11)                   # those failures age out
        drive(cb, [False, True, True])
        self.assertEqual(cb.state, CircuitState.CLOSED)
        drive(cb, [False])                       # 2/4 = 50%
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_decorator_preserves_metadata(self):
        @self.cb
        def fetch(x):
            """docstring"""
            return x * 2
        self.assertEqual((fetch(21), fetch.__name__, fetch.__doc__), (42, "fetch", "docstring"))

    def test_reset(self):
        drive(self.cb, [False] * 4)
        self.cb.reset()
        self.assertEqual(self.cb.state, CircuitState.CLOSED)

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(failure_rate_threshold=0)


class TestCircuitBreakerConcurrency(unittest.TestCase):
    def test_exactly_n_probes_admitted_under_contention(self):
        clock = ManualClock()
        cb = make_breaker(clock, half_open_max_calls=3)
        drive(cb, [False] * 4)
        clock.advance(10)
        barrier = threading.Barrier(32)
        admitted, rejected = [], []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                cb.acquire()
                with lock:
                    admitted.append(1)
            except CallNotPermittedError:
                with lock:
                    rejected.append(1)

        threads = [threading.Thread(target=worker) for _ in range(32)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((len(admitted), len(rejected)), (3, 29))

    def test_window_counts_are_exact_under_contention(self):
        cb = make_breaker(ManualClock(), window_size=10_000, minimum_calls=10_000)
        barrier = threading.Barrier(8)

        def worker(n):
            barrier.wait()
            for i in range(500):
                try:
                    cb.call(boom if (i + n) % 4 == 0 else ok)
                except ConnectionError:
                    pass

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = cb.metrics()
        self.assertEqual((snap.total, snap.failures), (4000, 1000))


class TestRetry(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()

    def test_retries_then_succeeds_with_backoff(self):
        attempts = []

        def flaky():
            attempts.append(self.clock.now())
            if len(attempts) < 3:
                raise TimeoutError()
            return "ok"

        retry = Retry(RetryConfig(max_attempts=5, base_delay=1, max_delay=10, jitter=Jitter.NONE),
                      clock=self.clock)
        self.assertEqual(retry.call(flaky), "ok")
        self.assertEqual(attempts, [0, 1, 3])   # waits 1s then 2s

    def test_gives_up_after_max_attempts(self):
        calls = []
        retry = Retry(RetryConfig(max_attempts=3, jitter=Jitter.NONE), clock=self.clock)
        with self.assertRaises(ConnectionError):
            retry.call(lambda: (calls.append(1), boom()))
        self.assertEqual(len(calls), 3)

    def test_does_not_retry_non_retryable(self):
        calls = []

        def bad():
            calls.append(1)
            raise ValueError()

        with self.assertRaises(ValueError):
            Retry(clock=self.clock).call(bad)
        self.assertEqual(len(calls), 1)

    def test_backoff_caps_and_jitter_bounds(self):
        none = Retry(RetryConfig(base_delay=1, max_delay=8, jitter=Jitter.NONE))
        self.assertEqual([none.backoff(i) for i in range(1, 7)], [1, 2, 4, 8, 8, 8])
        full = Retry(RetryConfig(base_delay=1, max_delay=8, jitter=Jitter.FULL), rng=random.Random(1))
        equal = Retry(RetryConfig(base_delay=1, max_delay=8, jitter=Jitter.EQUAL), rng=random.Random(1))
        for i in range(1, 7):
            cap = min(8, 2 ** (i - 1))
            self.assertTrue(0 <= full.backoff(i) <= cap)
            self.assertTrue(cap / 2 <= equal.backoff(i) <= cap)

    def test_budget_stops_retry_storm(self):
        budget = RetryBudget(max_tokens=4, token_ratio=0.5)
        retry = Retry(RetryConfig(max_attempts=5, jitter=Jitter.NONE), clock=self.clock, budget=budget)
        calls = []
        with self.assertRaises(RetryBudgetExhaustedError):
            retry.call(lambda: (calls.append(1), boom()))
        # tokens 4 -> 3 (retry ok) -> 2 (2 > 4/2 is false: stop)
        self.assertEqual(len(calls), 2)
        with self.assertRaises(RetryBudgetExhaustedError):   # next caller gets no retries
            retry.call(boom)
        for _ in range(10):
            retry.call(ok)                                    # successes refill
        self.assertGreater(budget.tokens, 2)

    def test_retry_does_not_hammer_open_circuit(self):
        cb = make_breaker(self.clock)
        drive(cb, [False] * 4)
        calls = []
        fn = resilient(retry=Retry(RetryConfig(max_attempts=5), clock=self.clock), breaker=cb)(
            lambda: calls.append(1))
        with self.assertRaises(CallNotPermittedError):
            fn()
        self.assertEqual(calls, [])

    def test_retry_attempts_are_seen_by_breaker(self):
        cb = make_breaker(self.clock)
        fn = resilient(retry=Retry(RetryConfig(max_attempts=4, jitter=Jitter.NONE), clock=self.clock),
                       breaker=cb)(boom)
        with self.assertRaises(ConnectionError):
            fn()
        self.assertEqual(cb.state, CircuitState.OPEN)   # 4 failed attempts tripped it


class TestBulkheadAndTimeout(unittest.TestCase):
    def test_bulkhead_caps_concurrency(self):
        bulkhead = Bulkhead("b", max_concurrent=3, max_wait=0.5)
        active, peak = [0], [0]
        lock = threading.Lock()

        def work():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.005)
            with lock:
                active[0] -= 1

        with ThreadPoolExecutor(max_workers=10) as pool:
            for f in [pool.submit(bulkhead.call, work) for _ in range(30)]:
                f.result()
        self.assertEqual(peak[0], 3)

    def test_bulkhead_rejects_when_full(self):
        bulkhead = Bulkhead("b", max_concurrent=1)
        inside, release = threading.Event(), threading.Event()
        t = threading.Thread(target=bulkhead.call, args=(lambda: (inside.set(), release.wait(1)),))
        t.start()
        inside.wait(1)
        with self.assertRaises(BulkheadFullError):
            bulkhead.call(ok)
        release.set()
        t.join()
        self.assertEqual(bulkhead.call(ok), "ok")

    def test_full_bulkhead_does_not_count_as_breaker_failure(self):
        cb = make_breaker(ManualClock(), minimum_calls=1, window_size=1)
        bulkhead = Bulkhead("b", max_concurrent=1)
        inside, release = threading.Event(), threading.Event()
        fn = resilient(breaker=cb, bulkhead=bulkhead)(lambda: (inside.set(), release.wait(1)))
        t = threading.Thread(target=fn)
        t.start()
        inside.wait(1)
        with self.assertRaises(BulkheadFullError):
            fn()
        release.set()
        t.join()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.metrics().failures, 0)

    def test_time_limiter_times_out_and_counts_as_breaker_failure(self):
        clock = ManualClock()
        cb = make_breaker(clock, minimum_calls=1, window_size=1)
        stop = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            fn = resilient(breaker=cb, time_limiter=TimeLimiter(0.02, pool))(lambda: stop.wait(1))
            with self.assertRaises(CallTimeoutError):
                fn()
            stop.set()
        self.assertEqual(cb.state, CircuitState.OPEN)


if __name__ == "__main__":
    unittest.main()
