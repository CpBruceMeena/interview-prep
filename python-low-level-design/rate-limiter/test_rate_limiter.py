import threading
import unittest

from rate_limiter import (
    UNLIMITED,
    FakeClock,
    FixedWindowCounter,
    LeakyBucket,
    RateLimiter,
    RateLimiterFactory,
    RateLimitMiddleware,
    RateLimitRule,
    SlidingWindowCounter,
    SlidingWindowLog,
    TokenBucket,
)

ALL = (TokenBucket, LeakyBucket, FixedWindowCounter, SlidingWindowLog, SlidingWindowCounter)


def make(algo_cls, max_requests=5, window=10.0, start=0.0):
    clock = FakeClock(start)
    return RateLimiter(algo_cls(RateLimitRule(max_requests, window)), clock), clock


class CommonBehaviour(unittest.TestCase):
    def test_allows_exactly_the_limit_in_a_burst(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, _ = make(cls)
                results = [limiter.allow("k") for _ in range(8)]
                self.assertEqual(results, [True] * 5 + [False] * 3)

    def test_keys_are_independent(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, _ = make(cls, max_requests=1)
                self.assertTrue(limiter.allow("a"))
                self.assertFalse(limiter.allow("a"))
                self.assertTrue(limiter.allow("b"))

    def test_retry_after_is_accurate(self):
        """Waiting exactly retry_after lets the next request through, and
        waiting noticeably less does not."""
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, clock = make(cls, start=3.0)
                for _ in range(5):
                    limiter.allow("k")
                denied = limiter.try_acquire("k")
                self.assertFalse(denied.allowed)
                self.assertGreater(denied.retry_after, 0)
                clock.advance(denied.retry_after - 0.01)
                self.assertFalse(limiter.allow("k"))
                clock.advance(0.01 + 1e-9)
                self.assertTrue(limiter.allow("k"))

    def test_peek_does_not_consume(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, _ = make(cls, max_requests=2)
                for _ in range(10):
                    self.assertEqual(limiter.peek("k").remaining, 2)
                self.assertTrue(limiter.allow("k"))
                self.assertEqual(limiter.peek("k").remaining, 1)

    def test_reset_restores_full_quota(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, _ = make(cls, max_requests=1)
                limiter.allow("k")
                self.assertFalse(limiter.allow("k"))
                limiter.reset("k")
                self.assertTrue(limiter.allow("k"))

    def test_evict_idle_drops_only_recovered_keys(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, clock = make(cls)
                limiter.allow("old")
                clock.advance(25)          # > 2 windows: every algorithm has fully recovered
                limiter.allow("fresh")
                self.assertEqual(limiter.evict_idle(), 1)
                self.assertEqual(len(limiter), 1)
                # The surviving key keeps its state.
                self.assertEqual(limiter.peek("fresh").remaining, 4)


class TokenBucketTests(unittest.TestCase):
    def test_refills_continuously_and_caps_at_capacity(self):
        limiter, clock = make(TokenBucket)      # 0.5 token/s
        for _ in range(5):
            limiter.allow("k")
        clock.advance(2.0)                      # +1 token
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))
        clock.advance(1000)
        self.assertEqual(limiter.peek("k").remaining, 5)

    def test_backwards_clock_does_not_mint_or_drain_tokens(self):
        limiter, clock = make(TokenBucket, start=100.0)
        limiter.allow("k")
        clock.now = 50.0
        self.assertEqual(limiter.peek("k").remaining, 4)


class FixedWindowTests(unittest.TestCase):
    def test_boundary_burst_lets_twice_the_limit_through(self):
        """The known weakness: 5 at t=9.9 plus 5 at t=10.0 = 10 in 0.1 s."""
        limiter, clock = make(FixedWindowCounter, start=9.9)
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 5)
        clock.now = 10.0
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 5)


class SlidingWindowLogTests(unittest.TestCase):
    def test_no_boundary_burst(self):
        limiter, clock = make(SlidingWindowLog, start=9.9)
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 5)
        clock.now = 10.0
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 0)

    def test_entry_expires_exactly_one_window_later(self):
        limiter, clock = make(SlidingWindowLog, max_requests=1)
        limiter.allow("k")
        clock.now = 9.999
        self.assertFalse(limiter.allow("k"))
        clock.now = 10.0
        self.assertTrue(limiter.allow("k"))

    def test_rejected_requests_do_not_grow_the_log(self):
        limiter, _ = make(SlidingWindowLog, max_requests=3)
        for _ in range(1000):
            limiter.allow("k")
        state = limiter._entries["k"].state
        self.assertEqual(len(state.timestamps), 3)


class SlidingWindowCounterTests(unittest.TestCase):
    def test_weights_previous_window(self):
        limiter, clock = make(SlidingWindowCounter, max_requests=10)
        for _ in range(10):
            limiter.allow("k")
        clock.now = 12.0                        # 20% into next window: estimate = 10*0.8 = 8
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 2)

    def test_previous_window_forgotten_after_a_gap(self):
        limiter, clock = make(SlidingWindowCounter, max_requests=10)
        for _ in range(10):
            limiter.allow("k")
        clock.now = 25.0                        # skipped window [10, 20)
        self.assertEqual(sum(limiter.allow("k") for _ in range(15)), 10)


class LeakyBucketTests(unittest.TestCase):
    def test_drains_at_constant_rate(self):
        limiter, clock = make(LeakyBucket)      # 0.5 req/s
        for _ in range(5):
            limiter.allow("k")
        clock.advance(4.0)                      # drained 2 units
        self.assertEqual(sum(limiter.allow("k") for _ in range(5)), 2)


class ConcurrencyTests(unittest.TestCase):
    def _hammer(self, limiter, keys, threads=16, per_thread=200):
        allowed = {k: 0 for k in keys}
        lock = threading.Lock()
        barrier = threading.Barrier(threads)

        def worker(i):
            barrier.wait()
            local = {k: 0 for k in keys}
            for j in range(per_thread):
                k = keys[(i + j) % len(keys)]
                if limiter.allow(k):
                    local[k] += 1
            with lock:
                for k, v in local.items():
                    allowed[k] += v

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return allowed

    def test_never_over_admits_under_contention(self):
        for cls in ALL:
            with self.subTest(cls.__name__):
                limiter, _ = make(cls, max_requests=100, window=60)   # frozen clock
                allowed = self._hammer(limiter, ["a", "b", "c"])
                self.assertEqual(allowed, {"a": 100, "b": 100, "c": 100})

    def test_eviction_between_lookup_and_lock_is_detected(self):
        """Force the worst interleaving: the janitor evicts a key after a request
        has looked up its entry but before it takes the key lock. Without the
        `evicted` re-check the request would consume from an orphaned entry and
        the next request would get a fresh, full bucket (over-admission)."""

        class RacyLimiter(RateLimiter):
            race_once = True

            def _entry(self, key, now):
                entry = super()._entry(key, now)
                if self.race_once:
                    self.race_once = False
                    self.evict_idle()        # entry is fresh => idle => evicted
                return entry

        clock = FakeClock()
        limiter = RacyLimiter(TokenBucket(RateLimitRule(1, 3600)), clock)
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))

    def test_eviction_concurrent_with_traffic(self):
        limiter, _ = make(TokenBucket, max_requests=50, window=3600)
        stop = threading.Event()

        def janitor():
            while not stop.is_set():
                limiter.evict_idle()

        jt = threading.Thread(target=janitor)
        jt.start()
        try:
            allowed = self._hammer(limiter, ["k"], threads=8, per_thread=100)
        finally:
            stop.set()
            jt.join()
        self.assertEqual(allowed["k"], 50)


class FactoryAndMiddlewareTests(unittest.TestCase):
    def test_factory(self):
        rule = RateLimitRule(1, 1)
        self.assertIsInstance(RateLimiterFactory.create("token_bucket", rule), TokenBucket)
        with self.assertRaises(ValueError):
            RateLimiterFactory.create("nope", rule)

    def test_rule_validation(self):
        with self.assertRaises(ValueError):
            RateLimitRule(0, 10)
        with self.assertRaises(ValueError):
            RateLimitRule(10, 0)

    def test_middleware_scopes_by_endpoint_and_client(self):
        clock = FakeClock()
        mw = RateLimitMiddleware(clock)
        mw.add_rule("/login", RateLimitRule(2, 60), "sliding_window_log")
        self.assertTrue(mw.check("/login", "alice").allowed)
        self.assertTrue(mw.check("/login", "alice").allowed)
        denied = mw.check("/login", "alice")
        self.assertFalse(denied.allowed)
        self.assertAlmostEqual(denied.retry_after, 60.0)
        self.assertTrue(mw.check("/login", "bob").allowed)
        self.assertIs(mw.check("/search", "alice"), UNLIMITED)


if __name__ == "__main__":
    unittest.main()
