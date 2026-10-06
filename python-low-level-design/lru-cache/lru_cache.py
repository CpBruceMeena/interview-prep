"""
LRU / LFU Cache with TTL - Low Level Design
-------------------------------------------
    BaseCache (ABC, template method)
      owns: key -> node map, capacity, TTL (lazy + heap-driven purge), stats
      hooks: _insert / _touch / _unlink / _victim   <- the eviction policy
    LRUCache   hashmap + one doubly linked list             get/put O(1)
    LFUCache   hashmap + one DLL per frequency + min_freq   get/put O(1)
    ThreadSafeCache   one lock around any BaseCache, plus single-flight get_or_load
    StripedCache      N independently locked shards, hash(key) % N

Complexities (n = entries):
    get / put / delete           O(1)  (+ O(log n) heap push when a TTL is set)
    purge_expired                O(k log n) for k expired entries
    LFU delete/expire of the     O(F) to recompute min_freq, F = distinct
      last key at min_freq         frequencies; deferred until the next eviction

Not thread-safe on their own. Note that get() MUTATES (moves a node / bumps a
frequency), so a read-write lock buys nothing for LRU/LFU: every call needs
exclusive access. Scale with striping, not RW locks.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, Iterator, Optional, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
Clock = Callable[[], float]

_MISSING = object()


# --- Doubly linked list with sentinels -----------------------------------

class _Node(Generic[K, V]):
    __slots__ = ("key", "value", "expires_at", "freq", "prev", "next")

    def __init__(self, key, value, expires_at: Optional[float]):
        self.key = key
        self.value = value
        self.expires_at = expires_at
        self.freq = 0
        self.prev: Optional[_Node] = None
        self.next: Optional[_Node] = None


class _DList:
    """head <-> n1 <-> ... <-> tail. Front = most recent. Sentinels remove
    every head/tail None check, which is where hand-rolled DLLs go wrong."""

    __slots__ = ("_head", "_tail", "_len")

    def __init__(self):
        self._head = _Node(None, None, None)
        self._tail = _Node(None, None, None)
        self._head.next = self._tail
        self._tail.prev = self._head
        self._len = 0

    def push_front(self, node: _Node) -> None:
        node.prev = self._head
        node.next = self._head.next
        self._head.next.prev = node
        self._head.next = node
        self._len += 1

    def remove(self, node: _Node) -> None:
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = node.next = None
        self._len -= 1

    def back(self) -> Optional[_Node]:
        return None if self._len == 0 else self._tail.prev

    def __len__(self) -> int:
        return self._len

    def __iter__(self) -> Iterator[_Node]:   # front (MRU) to back (LRU)
        node = self._head.next
        while node is not self._tail:
            yield node
            node = node.next


# --- Stats ----------------------------------------------------------------

@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0      # live entries pushed out by capacity
    expirations: int = 0    # entries removed because their TTL passed

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def __add__(self, other: CacheStats) -> CacheStats:
        return CacheStats(self.hits + other.hits, self.misses + other.misses,
                          self.evictions + other.evictions,
                          self.expirations + other.expirations)


# --- Base cache (template method) -----------------------------------------

class BaseCache(ABC, Generic[K, V]):
    def __init__(self, capacity: int, default_ttl: Optional[float] = None,
                 clock: Clock = time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be positive")
        self._capacity = capacity
        self._default_ttl = default_ttl
        self._clock = clock
        self._map: dict[K, _Node] = {}
        # (expires_at, seq, node). Entries go stale when a key is rewritten
        # or deleted; we skip those on pop and compact when the heap gets big.
        self._expiry_heap: list[tuple[float, int, _Node]] = []
        self._seq = itertools.count()
        self._stats = CacheStats()

    # ---- public API ----
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Value for key, or `default` if absent or expired. Counts as a use."""
        node = self._map.get(key)
        if node is None:
            self._stats.misses += 1
            return default
        if self._is_expired(node):
            self._remove(node)
            self._stats.expirations += 1
            self._stats.misses += 1
            return default
        self._touch(node)
        self._stats.hits += 1
        return node.value

    def put(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        """Insert or overwrite. ttl (seconds) overrides default_ttl for this key.
        Overwriting counts as a use and resets the TTL."""
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        ttl = ttl if ttl is not None else self._default_ttl
        expires_at = self._clock() + ttl if ttl is not None else None

        node = self._map.get(key)
        if node is not None:
            node.value = value
            node.expires_at = expires_at
            self._schedule(node)
            self._touch(node)
            return

        if len(self._map) >= self._capacity:
            # Reclaim dead entries before evicting a live one.
            if self.purge_expired() == 0:
                victim = self._victim()
                self._remove(victim)
                self._stats.evictions += 1
        node = _Node(key, value, expires_at)
        self._map[key] = node
        self._insert(node)
        self._schedule(node)

    def delete(self, key: K) -> bool:
        node = self._map.get(key)
        if node is None:
            return False
        self._remove(node)
        return True

    def purge_expired(self) -> int:
        """Drop every expired entry. Amortised O(log n) per removed entry."""
        now = self._clock()
        removed = 0
        heap = self._expiry_heap
        while heap and heap[0][0] <= now:
            expires_at, _, node = heapq.heappop(heap)
            if self._map.get(node.key) is node and node.expires_at == expires_at:
                self._remove(node)
                self._stats.expirations += 1
                removed += 1
        return removed

    def __contains__(self, key: K) -> bool:
        """Present and not expired. Does NOT count as a use."""
        node = self._map.get(key)
        return node is not None and not self._is_expired(node)

    def __len__(self) -> int:
        """Entries held, including expired ones not yet purged."""
        return len(self._map)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def stats(self) -> CacheStats:
        s = self._stats
        return CacheStats(s.hits, s.misses, s.evictions, s.expirations)

    # ---- internals ----
    def _is_expired(self, node: _Node) -> bool:
        return node.expires_at is not None and node.expires_at <= self._clock()

    def _schedule(self, node: _Node) -> None:
        if node.expires_at is None:
            return
        heapq.heappush(self._expiry_heap, (node.expires_at, next(self._seq), node))
        # Rewrites leave stale heap entries; keep the heap O(live entries).
        if len(self._expiry_heap) > 2 * len(self._map) + 32:
            self._expiry_heap = [(n.expires_at, next(self._seq), n)
                                 for n in self._map.values() if n.expires_at is not None]
            heapq.heapify(self._expiry_heap)

    def _remove(self, node: _Node) -> None:
        del self._map[node.key]
        self._unlink(node)

    # ---- policy hooks ----
    @abstractmethod
    def _insert(self, node: _Node) -> None:
        """A new node entered the cache."""

    @abstractmethod
    def _touch(self, node: _Node) -> None:
        """An existing node was read or overwritten."""

    @abstractmethod
    def _unlink(self, node: _Node) -> None:
        """Forget a node (eviction, expiry or delete)."""

    @abstractmethod
    def _victim(self) -> _Node:
        """The node to evict when full. Cache is non-empty."""

    def _check_invariants(self) -> None:   # for tests
        assert len(self._map) <= self._capacity


class LRUCache(BaseCache[K, V]):
    """Evicts the least recently used entry. Front of the list = MRU."""

    def __init__(self, capacity: int, default_ttl: Optional[float] = None,
                 clock: Clock = time.monotonic):
        super().__init__(capacity, default_ttl, clock)
        self._order = _DList()

    def _insert(self, node: _Node) -> None:
        self._order.push_front(node)

    def _touch(self, node: _Node) -> None:
        self._order.remove(node)
        self._order.push_front(node)

    def _unlink(self, node: _Node) -> None:
        self._order.remove(node)

    def _victim(self) -> _Node:
        return self._order.back()

    def keys_mru_to_lru(self) -> list[K]:
        return [n.key for n in self._order]

    def _check_invariants(self) -> None:
        super()._check_invariants()
        listed = [n.key for n in self._order]
        assert len(listed) == len(self._order) == len(self._map)
        assert set(listed) == set(self._map)


class LFUCache(BaseCache[K, V]):
    """Evicts the least frequently used entry; ties go to the least recently
    used among them. New entries start at freq 1.

    _buckets[f] is a DLL of nodes used exactly f times (front = most recent).
    _min_freq is the smallest non-empty f, or None when it must be recomputed.
    """

    def __init__(self, capacity: int, default_ttl: Optional[float] = None,
                 clock: Clock = time.monotonic):
        super().__init__(capacity, default_ttl, clock)
        self._buckets: dict[int, _DList] = {}
        self._min_freq: Optional[int] = None

    def _bucket(self, freq: int) -> _DList:
        b = self._buckets.get(freq)
        if b is None:
            b = self._buckets[freq] = _DList()
        return b

    def _detach(self, node: _Node) -> bool:
        """Remove from its bucket; True if that emptied the min bucket."""
        b = self._buckets[node.freq]
        b.remove(node)
        if len(b) == 0:
            del self._buckets[node.freq]
            return node.freq == self._min_freq
        return False

    def _insert(self, node: _Node) -> None:
        node.freq = 1
        self._bucket(1).push_front(node)
        self._min_freq = 1                       # nothing can be below 1

    def _touch(self, node: _Node) -> None:
        emptied_min = self._detach(node)
        node.freq += 1
        self._bucket(node.freq).push_front(node)
        if emptied_min:
            self._min_freq = node.freq           # it moved exactly one bucket up

    def _unlink(self, node: _Node) -> None:
        if self._detach(node):
            self._min_freq = None                # recompute lazily in _victim

    def _victim(self) -> _Node:
        if self._min_freq is None:
            self._min_freq = min(self._buckets)  # O(F); rare: only after a
        return self._buckets[self._min_freq].back()  # delete/expire of the min

    def frequency(self, key: K) -> int:
        node = self._map.get(key)
        return node.freq if node else 0

    def _check_invariants(self) -> None:
        super()._check_invariants()
        assert sum(len(b) for b in self._buckets.values()) == len(self._map)
        for f, b in self._buckets.items():
            assert len(b) > 0 and all(n.freq == f for n in b)
        if self._buckets and self._min_freq is not None:
            assert self._min_freq == min(self._buckets)


# --- Concurrency ----------------------------------------------------------

class _Flight:
    __slots__ = ("done", "value", "error")

    def __init__(self):
        self.done = threading.Event()
        self.value = None
        self.error: Optional[BaseException] = None


class ThreadSafeCache(Generic[K, V]):
    """One mutex around a BaseCache. A plain Lock, not an RLock: nothing
    re-enters, and not a read-write lock: get() mutates recency/frequency."""

    def __init__(self, cache: BaseCache[K, V]):
        self._cache = cache
        self._lock = threading.Lock()
        self._inflight: dict[K, _Flight] = {}

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        with self._lock:
            return self._cache.get(key, default)

    def put(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        with self._lock:
            self._cache.put(key, value, ttl)

    def delete(self, key: K) -> bool:
        with self._lock:
            return self._cache.delete(key)

    def purge_expired(self) -> int:
        with self._lock:
            return self._cache.purge_expired()

    def get_or_load(self, key: K, loader: Callable[[K], V],
                    ttl: Optional[float] = None) -> V:
        """Cache-aside with single-flight: on a miss, exactly one caller runs
        loader(key) (outside the lock); concurrent callers for the same key
        wait for its result instead of stampeding the backing store."""
        with self._lock:
            value = self._cache.get(key, _MISSING)
            if value is not _MISSING:
                return value
            flight = self._inflight.get(key)
            leader = flight is None
            if leader:
                flight = self._inflight[key] = _Flight()
        if not leader:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value
        try:
            flight.value = loader(key)
        except BaseException as e:
            flight.error = e
            raise
        finally:
            with self._lock:
                if flight.error is None:
                    self._cache.put(key, flight.value, ttl)
                del self._inflight[key]
            flight.done.set()
        return flight.value

    def __contains__(self, key: K) -> bool:
        with self._lock:
            return key in self._cache

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def stats(self) -> CacheStats:
        with self._lock:
            return self._cache.stats

    def _check_invariants(self) -> None:
        with self._lock:
            self._cache._check_invariants()


class StripedCache(Generic[K, V]):
    """N shards, each its own cache + lock; a key lives in shard hash(key) % N.

    Contention drops roughly N-fold because unrelated keys no longer share a
    lock. The price: eviction is per shard (approximate global LRU/LFU), and
    capacity is split evenly, so a hot shard evicts while others have room.
    Under CPython's GIL pure-Python work is still serialised; striping pays
    off with free-threaded builds or when the critical section releases the
    GIL. In Java/Go/C++ this is the standard design (cf. Guava/Caffeine
    segments, ConcurrentHashMap's per-bin locking).
    """

    def __init__(self, capacity: int, stripes: int,
                 factory: Callable[[int], BaseCache[K, V]]):
        if stripes <= 0 or capacity < stripes:
            raise ValueError("need 1 <= stripes <= capacity")
        per_shard = -(-capacity // stripes)          # ceil
        self._shards = [ThreadSafeCache(factory(per_shard)) for _ in range(stripes)]

    def _shard(self, key: K) -> ThreadSafeCache[K, V]:
        return self._shards[hash(key) % len(self._shards)]

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        return self._shard(key).get(key, default)

    def put(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        self._shard(key).put(key, value, ttl)

    def delete(self, key: K) -> bool:
        return self._shard(key).delete(key)

    def get_or_load(self, key: K, loader: Callable[[K], V],
                    ttl: Optional[float] = None) -> V:
        return self._shard(key).get_or_load(key, loader, ttl)

    def __contains__(self, key: K) -> bool:
        return key in self._shard(key)

    def __len__(self) -> int:
        return sum(len(s) for s in self._shards)

    @property
    def stats(self) -> CacheStats:
        total = CacheStats()
        for s in self._shards:
            total = total + s.stats
        return total

    def _check_invariants(self) -> None:
        for s in self._shards:
            s._check_invariants()


# --- Demo -----------------------------------------------------------------

class ManualClock:
    """Deterministic clock for demos and tests."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def demo() -> None:
    print("=== LRU ===")
    lru: LRUCache[str, int] = LRUCache(3)
    for k, v in (("a", 1), ("b", 2), ("c", 3)):
        lru.put(k, v)
    lru.get("a")                    # a becomes MRU; b is now LRU
    lru.put("d", 4)                 # evicts b
    print("  order MRU->LRU:", lru.keys_mru_to_lru(), "| b present:", "b" in lru)

    print("\n=== LFU (ties broken by recency) ===")
    lfu: LFUCache[str, int] = LFUCache(3)
    for k, v in (("a", 1), ("b", 2), ("c", 3)):
        lfu.put(k, v)
    lfu.get("a"); lfu.get("a"); lfu.get("c")
    lfu.put("d", 4)                 # b has freq 1 and is the only one -> evicted
    lfu.put("e", 5)                 # d (freq 1) evicted, not c (freq 2)
    print("  freqs:", {k: lfu.frequency(k) for k in "abcde"})

    print("\n=== TTL (manual clock) ===")
    clock = ManualClock()
    ttl_cache: LRUCache[str, str] = LRUCache(2, default_ttl=10, clock=clock)
    ttl_cache.put("session", "alice")
    ttl_cache.put("token", "xyz", ttl=2)
    clock.advance(3)
    print("  after 3s: token =", ttl_cache.get("token"), "| session =", ttl_cache.get("session"))
    ttl_cache.put("x", "1")
    clock.advance(8)                # session (t=10) expires; x (t=13) does not
    ttl_cache.put("y", "2")         # full: purges expired 'session' instead of evicting x
    print("  after 11s: keys =", ttl_cache.keys_mru_to_lru(), "|", ttl_cache.stats)

    print("\n=== Thread-safe + single-flight loader ===")
    calls = []
    cache: ThreadSafeCache[int, str] = ThreadSafeCache(LRUCache(100))

    def slow_load(key: int) -> str:
        calls.append(key)
        time.sleep(0.05)
        return f"row-{key}"

    threads = [threading.Thread(target=cache.get_or_load, args=(7, slow_load))
               for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"  10 concurrent misses for key 7 -> loader ran {len(calls)} time(s);",
          "value:", cache.get(7))

    striped: StripedCache[int, int] = StripedCache(64, 8, LRUCache)
    for i in range(200):
        striped.put(i, i * i)
    print(f"  striped: 8 shards x 8 slots, inserted 200 -> holds {len(striped)}")


if __name__ == "__main__":
    demo()
