import random
import threading
import time
import unittest
from collections import OrderedDict

from lru_cache import (
    LFUCache, LRUCache, ManualClock, StripedCache, ThreadSafeCache,
)


class LRUTest(unittest.TestCase):
    def test_evicts_least_recently_used(self):
        c = LRUCache(2)
        c.put(1, "a"); c.put(2, "b")
        c.get(1)
        c.put(3, "c")
        self.assertNotIn(2, c)
        self.assertEqual(c.keys_mru_to_lru(), [3, 1])
        self.assertEqual(c.stats.evictions, 1)

    def test_overwrite_refreshes_recency_without_growing(self):
        c = LRUCache(2)
        c.put(1, "a"); c.put(2, "b")
        c.put(1, "A")
        c.put(3, "c")
        self.assertEqual(c.get(1), "A")
        self.assertNotIn(2, c)
        self.assertEqual(len(c), 2)

    def test_capacity_one_and_delete(self):
        c = LRUCache(1)
        c.put("x", 1); c.put("y", 2)
        self.assertEqual(c.keys_mru_to_lru(), ["y"])
        self.assertTrue(c.delete("y"))
        self.assertFalse(c.delete("y"))
        self.assertEqual(len(c), 0)
        c.put("z", 3)
        self.assertEqual(c.get("z"), 3)

    def test_none_is_a_cacheable_value(self):
        c = LRUCache(2)
        c.put("k", None)
        sentinel = object()
        self.assertIsNone(c.get("k", sentinel))
        self.assertIs(c.get("missing", sentinel), sentinel)
        self.assertEqual((c.stats.hits, c.stats.misses), (1, 1))

    def test_contains_does_not_touch(self):
        c = LRUCache(2)
        c.put(1, 1); c.put(2, 2)
        self.assertIn(1, c)          # must not make 1 MRU
        c.put(3, 3)
        self.assertNotIn(1, c)

    def test_rejects_bad_capacity(self):
        with self.assertRaises(ValueError):
            LRUCache(0)

    def test_matches_ordereddict_model(self):
        rng = random.Random(42)
        cap = 8
        c, model = LRUCache(cap), OrderedDict()
        for _ in range(5000):
            k = rng.randrange(20)
            op = rng.random()
            if op < 0.45:
                got = c.get(k)
                want = model.get(k)
                if k in model:
                    model.move_to_end(k)
                self.assertEqual(got, want)
            elif op < 0.9:
                v = rng.random()
                if k in model:
                    model.move_to_end(k)
                elif len(model) >= cap:
                    model.popitem(last=False)
                model[k] = v
                c.put(k, v)
            else:
                self.assertEqual(c.delete(k), model.pop(k, None) is not None)
            self.assertEqual(c.keys_mru_to_lru(), list(reversed(model)))
        c._check_invariants()


class LFUTest(unittest.TestCase):
    def test_evicts_least_frequent(self):
        c = LFUCache(2)
        c.put(1, 1); c.put(2, 2)
        c.get(1)
        c.put(3, 3)
        self.assertIn(1, c)
        self.assertNotIn(2, c)

    def test_tie_broken_by_recency(self):
        c = LFUCache(3)
        c.put("a", 1); c.put("b", 2); c.put("c", 3)   # all freq 1; a is oldest
        c.put("d", 4)
        self.assertNotIn("a", c)
        self.assertIn("b", c)

    def test_new_entry_resets_min_freq(self):
        c = LFUCache(2)
        c.put(1, 1); c.put(2, 2)
        for _ in range(3):
            c.get(1); c.get(2)                # both at freq 4
        c.put(3, 3)                           # evicts 1 (LRU among freq 4)
        self.assertEqual(c.frequency(3), 1)
        c.put(4, 4)                           # must evict 3 (freq 1), not 2
        self.assertNotIn(3, c)
        self.assertIn(2, c)
        c._check_invariants()

    def test_delete_of_min_bucket_then_evict(self):
        c = LFUCache(3)
        c.put("a", 1); c.put("b", 2); c.put("c", 3)
        c.get("b"); c.get("c"); c.get("c")    # a:1 b:2 c:3
        c.delete("a")                         # min bucket emptied
        c.put("d", 4)                         # d:1, not full yet
        c.get("d"); c.get("d")                # d:3
        c.put("e", 5)                         # full -> evict b (freq 2)
        self.assertNotIn("b", c)
        c._check_invariants()

    def test_overwrite_counts_as_use(self):
        c = LFUCache(2)
        c.put(1, "a"); c.put(1, "b")
        self.assertEqual(c.frequency(1), 2)
        self.assertEqual(c.get(1), "b")

    def test_matches_reference_model(self):
        rng = random.Random(7)
        cap = 6
        c = LFUCache(cap)
        model = {}           # key -> [value, freq, last_used]
        tick = 0
        for _ in range(5000):
            tick += 1
            k = rng.randrange(15)
            r = rng.random()
            if r < 0.5:
                got = c.get(k)
                if k in model:
                    model[k][1] += 1; model[k][2] = tick
                    self.assertEqual(got, model[k][0])
                else:
                    self.assertIsNone(got)
            elif r < 0.9:
                v = rng.random()
                if k in model:
                    model[k][0] = v; model[k][1] += 1; model[k][2] = tick
                else:
                    if len(model) >= cap:
                        victim = min(model, key=lambda x: (model[x][1], model[x][2]))
                        del model[victim]
                    model[k] = [v, 1, tick]
                c.put(k, v)
            else:
                self.assertEqual(c.delete(k), model.pop(k, None) is not None)
            self.assertEqual(set(c._map), set(model))
            c._check_invariants()


class TTLTest(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()

    def test_lazy_expiry_on_get(self):
        c = LRUCache(4, default_ttl=5, clock=self.clock)
        c.put("k", "v")
        self.clock.advance(4.9)
        self.assertEqual(c.get("k"), "v")
        self.clock.advance(0.1)
        self.assertIsNone(c.get("k"))
        self.assertEqual(len(c), 0)
        self.assertEqual(c.stats.expirations, 1)

    def test_per_key_ttl_and_no_ttl(self):
        c = LRUCache(4, clock=self.clock)
        c.put("forever", 1)
        c.put("short", 2, ttl=1)
        self.clock.advance(100)
        self.assertEqual(c.get("forever"), 1)
        self.assertNotIn("short", c)

    def test_overwrite_resets_ttl(self):
        c = LRUCache(4, default_ttl=5, clock=self.clock)
        c.put("k", 1)
        self.clock.advance(4)
        c.put("k", 2)
        self.clock.advance(4)
        self.assertEqual(c.get("k"), 2)
        self.assertEqual(c.purge_expired(), 0)   # stale heap entry is ignored

    def test_full_cache_reclaims_expired_before_evicting_live(self):
        c = LFUCache(2, clock=self.clock)
        c.put("hot", 1)
        for _ in range(5):
            c.get("hot")
        c.put("temp", 2, ttl=1)
        self.clock.advance(2)
        c.put("new", 3)
        self.assertIn("hot", c)
        self.assertIn("new", c)
        self.assertEqual(c.stats.evictions, 0)
        self.assertEqual(c.stats.expirations, 1)

    def test_purge_expired(self):
        c = LRUCache(10, clock=self.clock)
        for i in range(10):
            c.put(i, i, ttl=i + 1)
        self.clock.advance(5)
        self.assertEqual(c.purge_expired(), 5)
        self.assertEqual(sorted(c._map), [5, 6, 7, 8, 9])

    def test_heap_stays_bounded_under_rewrites(self):
        c = LRUCache(4, default_ttl=60, clock=self.clock)
        for i in range(10_000):
            c.put(i % 4, i)
        self.assertLessEqual(len(c._expiry_heap), 2 * len(c) + 33)

    def test_rejects_non_positive_ttl(self):
        with self.assertRaises(ValueError):
            LRUCache(2, default_ttl=0)
        with self.assertRaises(ValueError):
            LRUCache(2).put("k", 1, ttl=-1)


class ConcurrencyTest(unittest.TestCase):
    def hammer(self, cache, threads=8, ops=3000):
        errors, gets = [], []

        def worker(seed):
            rng = random.Random(seed)
            n_gets = 0
            try:
                for _ in range(ops):
                    k = rng.randrange(64)
                    r = rng.random()
                    if r < 0.6:
                        cache.get(k)
                        n_gets += 1
                    elif r < 0.95:
                        cache.put(k, k)
                    else:
                        cache.delete(k)
            except Exception as e:     # pragma: no cover
                errors.append(e)
            gets.append(n_gets)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=10)
        self.assertEqual(errors, [])
        cache._check_invariants()
        s = cache.stats                # no lost counter updates
        self.assertEqual(s.hits + s.misses, sum(gets))

    def test_thread_safe_lru_and_lfu_keep_invariants(self):
        for factory in (LRUCache, LFUCache):
            with self.subTest(factory=factory.__name__):
                cache = ThreadSafeCache(factory(16))
                self.hammer(cache)
                self.assertLessEqual(len(cache), 16)

    def test_striped_cache_keeps_invariants_and_capacity(self):
        cache = StripedCache(32, 4, LFUCache)
        self.hammer(cache)
        self.assertLessEqual(len(cache), 32)

    def test_get_or_load_is_single_flight(self):
        cache = ThreadSafeCache(LRUCache(10))
        calls = []
        start = threading.Barrier(12)

        def loader(k):
            calls.append(k)
            time.sleep(0.05)
            return k * 10

        results = []

        def client():
            start.wait()
            results.append(cache.get_or_load(3, loader))

        ts = [threading.Thread(target=client) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5)
        self.assertEqual(calls, [3])
        self.assertEqual(results, [30] * 12)

    def test_get_or_load_propagates_errors_and_does_not_cache_them(self):
        cache = ThreadSafeCache(LRUCache(10))

        def boom(k):
            raise IOError("db down")

        with self.assertRaises(IOError):
            cache.get_or_load("k", boom)
        self.assertNotIn("k", cache)
        self.assertEqual(cache.get_or_load("k", lambda k: "ok"), "ok")


if __name__ == "__main__":
    unittest.main()
