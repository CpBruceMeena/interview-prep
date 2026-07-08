"""
LRU Cache - Low Level Design
-------------------------------
Design Principles: SOLID, O(1) operations

Architecture:
  - Node: Generic doubly-linked list node (key + value + prev/next pointers)
  - EvictionStrategy (ABC): Pluggable eviction policy (Strategy pattern)
    - LRUStrategy: HashMap + DoublyLinkedList for O(1) LRU eviction
    - LFUStrategy: Frequency maps for O(1) amortized LFU eviction
    - TTLStrategy: Time-based expiry with configurable TTL
  - Cache: Generic facade that delegates eviction to plugged-in strategy
  - CacheStats (SRP): Tracks hits/misses/evictions independently
  - CacheWithStats: Decorator wrapping a Cache to add stats tracking
  - ThreadSafeCache: Wraps any Cache with reentrant locks for thread safety

Interview Discussion Points:
  - Why HashMap + DLL for LRU? → O(1) get/put/evict
  - Why abstract EvictionStrategy? → Open/Closed Principle — add FIFO, ARC, 2Q without modifying Cache
  - Why separate CacheStats? → Single Responsibility — stats logic doesn't pollute Cache
  - How to make it thread-safe? → RLock (or ReadWriteLock for higher concurrency)
  - How does this scale to distributed? → Consistent hashing + lazy migration
"""

from abc import ABC, abstractmethod
from threading import RLock
from typing import Any, Dict, Optional, TypeVar, Generic

K = TypeVar("K")
V = TypeVar("V")


# ---------------------------------------------------------------------------
# Node — building block for the doubly linked list
# ---------------------------------------------------------------------------

class Node(Generic[K, V]):
    """A node in the doubly linked list.

    The DLL gives us O(1) move-to-front and O(1) tail-removal, which is
    exactly what LRU eviction needs.  The 'prev' / 'next' pointers let us
    splice the node in/out without scanning the list.

    Attributes:
        key:   Cache key (also stored in the node so evict() can return it).
        value: Cached value.
        prev:  Previous node in the list (None if this is the head).
        next:  Next node in the list (None if this is the tail).
    """

    def __init__(self, key: K, value: V):
        self.key = key
        self.value = value
        self.prev: Optional["Node"] = None
        self.next: Optional["Node"] = None


# ---------------------------------------------------------------------------
# Eviction Strategy — abstract interface (Strategy Pattern → OCP)
# ---------------------------------------------------------------------------

class EvictionStrategy(ABC):
    """Pluggable eviction policy.

    The Cache class depends on *this abstraction*, not on any concrete
    strategy (Dependency Inversion Principle).  New strategies can be
    added without touching Cache (Open/Closed Principle).
    """

    @abstractmethod
    def access(self, key: Any, node: Node) -> None:
        """Notify the strategy that *key* was just accessed (read or updated).

        The *node* parameter carries the DLL node so LRUStrategy can
        move it to the front of its list in O(1).  LFUStrategy and
        TTLStrategy ignore it because they track metadata separately.
        """
        pass

    @abstractmethod
    def add(self, key: Any, node: Node) -> None:
        """Notify the strategy that a brand-new key is being inserted."""
        pass

    @abstractmethod
    def evict(self) -> Any:
        """Choose a victim key and return it.

        Raises ValueError when there is nothing to evict.
        """
        pass

    @abstractmethod
    def remove(self, key: Any) -> None:
        """Remove *key* from internal bookkeeping (called on explicit delete)."""
        pass


# ---------------------------------------------------------------------------
# LRU — Least Recently Used
# ---------------------------------------------------------------------------

class LRUStrategy(EvictionStrategy):
    """Evicts the *least recently used* item.

    Data structures:
      - Doubly linked list (head = MRU, tail = LRU).
      - _node_map: Dict[key → Node] for O(1) node lookup.

    Every access() moves the node to the *head* (most-recently-used end).
    evict() pops the *tail* (least-recently-used end).
    """

    def __init__(self):
        # Head = most recently used, Tail = least recently used
        self._head: Optional[Node] = None
        self._tail: Optional[Node] = None
        # Maps key → Node so we can find nodes in O(1)
        self._node_map: Dict[Any, Node] = {}

    # -- helper: splice a node out of the list (O(1)) --

    def _remove_node(self, node: Node) -> None:
        """Detach *node* from the doubly linked list by updating its neighbours."""
        # Bypass the node in the forward direction
        if node.prev:
            node.prev.next = node.next
        # Bypass the node in the backward direction
        if node.next:
            node.next.prev = node.prev
        # Update head/tail if we are removing the current head or tail
        if node == self._head:
            self._head = node.next
        if node == self._tail:
            self._tail = node.prev
        # Clear the node's own pointers so it's a standalone node again
        node.prev = None
        node.next = None

    # -- helper: prepend a node to the front (O(1)) --

    def _add_to_front(self, node: Node) -> None:
        """Insert *node* at the head (most-recently-used position)."""
        node.next = self._head
        node.prev = None
        if self._head:
            self._head.prev = node
        self._head = node
        if self._tail is None:
            self._tail = node

    # -- interface methods --

    def access(self, key: Any, node: Node) -> None:
        """Move *node* to the front — O(1) pointer updates.

        NOTE: The 'node' parameter is the DLL node associated with 'key'.
        We check the key in _node_map (O(1) dict lookup) rather than
        scanning _node_map.values() (which would be O(n)).
        """
        # Remove the node from its current position, then re-insert at front
        if key in self._node_map:
            self._remove_node(node)
        self._add_to_front(node)

    def add(self, key: Any, node: Node) -> None:
        """Insert a new key → node mapping and prepend node to the DLL."""
        self._add_to_front(node)
        self._node_map[key] = node

    def evict(self) -> Any:
        """Evict the LRU item (tail of the list) — O(1)."""
        if not self._tail:
            raise ValueError("Nothing to evict")
        key = self._tail.key
        self._remove_node(self._tail)
        del self._node_map[key]
        return key

    def remove(self, key: Any) -> None:
        """Remove *key* from tracking (called on Cache.remove())."""
        node = self._node_map.pop(key, None)
        if node:
            self._remove_node(node)


# ---------------------------------------------------------------------------
# LFU — Least Frequently Used
# ---------------------------------------------------------------------------

class LFUStrategy(EvictionStrategy):
    """Evicts the *least frequently used* item.

    Data structures:
      - _freq_map: Dict[freq → Set[key]]  — keys grouped by access frequency
      - _key_freq: Dict[key → freq]        — reverse lookup for O(1) access
      - _min_freq: int                     — current minimum non-empty frequency

    access() increments the frequency counter for a key.  evict() picks an
    arbitrary key from the lowest-frequency bucket.

    NOTE: The 'node' parameter passed to access/add is *unused* here because
    LFUStrategy organises keys by frequency, not by insertion order.  It
    is part of the EvictionStrategy interface so that LRUStrategy *can* use
    it, keeping the interface uniform across all strategies.
    """

    def __init__(self):
        # Frequency → set of keys at that frequency
        self._freq_map: Dict[int, set] = {}
        # Key → current frequency
        self._key_freq: Dict[Any, int] = {}
        # Tracks the smallest frequency that has at least one key
        self._min_freq = 0

    def access(self, key: Any, node: Node) -> None:
        """Increment the access frequency for *key*.

        The *node* parameter is unused here (see class docstring for why).
        """
        freq = self._key_freq.get(key, 0)

        # If the key already had a frequency, remove it from the old bucket
        if key in self._key_freq:
            self._freq_map[freq].discard(key)
            # If the old bucket is now empty and it was the min, advance _min_freq
            if not self._freq_map.get(freq) and freq == self._min_freq:
                while self._min_freq < max(self._key_freq.values(), default=0):
                    self._min_freq += 1
                    if self._freq_map.get(self._min_freq):
                        break

        new_freq = freq + 1
        self._key_freq[key] = new_freq
        self._freq_map.setdefault(new_freq, set()).add(key)
        self._min_freq = (
            new_freq if self._min_freq == 0 else min(self._min_freq, new_freq)
        )

    def add(self, key: Any, node: Node) -> None:
        """Delegate to access() which handles first-time frequency = 0 → 1."""
        self.access(key, node)

    def evict(self) -> Any:
        """Pick an arbitrary key from the lowest-frequency bucket."""
        if self._min_freq not in self._freq_map or not self._freq_map[self._min_freq]:
            raise ValueError("Nothing to evict")
        # Pick any key from the min-frequency set (set iteration is O(1))
        key = next(iter(self._freq_map[self._min_freq]))
        self._freq_map[self._min_freq].discard(key)
        del self._key_freq[key]
        return key

    def remove(self, key: Any) -> None:
        """Remove *key* from frequency tracking."""
        freq = self._key_freq.pop(key, None)
        if freq and freq in self._freq_map:
            self._freq_map[freq].discard(key)


# ---------------------------------------------------------------------------
# TTL — Time To Live
# ---------------------------------------------------------------------------

class TTLStrategy(EvictionStrategy):
    """Evicts items whose TTL has expired.

    Data structures:
      - _expiry_map: Dict[key → absolute_expiry_timestamp]

    NOTE: The 'node' parameter passed to access/add is *unused* (TTL is
    solely based on time, not on access patterns — though some real-world
    designs *do* extend TTL on access).
    """

    def __init__(self, default_ttl_seconds: int = 3600):
        self._default_ttl = default_ttl_seconds
        self._expiry_map: Dict[Any, float] = {}
        import time

        self._time = time

    def access(self, key: Any, node: Node) -> None:
        """No-op: TTL does not change on access in this implementation."""
        pass

    def add(self, key: Any, node: Node) -> None:
        """Record the expiry time for *key*: now + default TTL."""
        self._expiry_map[key] = self._time.time() + self._default_ttl

    def evict(self) -> Any:
        """Scan for an expired key and return it (first expired found).

        This is O(n) in the number of tracked keys.  Production systems use
        a **priority queue** (min-heap of expiry times) for O(log n) eviction.
        """
        now = self._time.time()
        for key, expiry in list(self._expiry_map.items()):
            if now >= expiry:
                del self._expiry_map[key]
                return key
        raise ValueError("Nothing to evict")

    def remove(self, key: Any) -> None:
        """Remove *key* from expiry tracking."""
        self._expiry_map.pop(key, None)

    def is_expired(self, key: Any) -> bool:
        """Check whether *key* has expired (used by Cache.get())."""
        expiry = self._expiry_map.get(key)
        return expiry is not None and self._time.time() >= expiry


# ---------------------------------------------------------------------------
# Cache — Generic facade with pluggable eviction
# ---------------------------------------------------------------------------

class Cache(Generic[K, V]):
    """Generic cache that delegates eviction to a pluggable strategy.

    Design:
      - SRP: Cache only worries about key/value storage and routing to the
        strategy.  Eviction logic lives in EvictionStrategy.
      - DIP: Cache depends on the EvictionStrategy *abstraction*.
      - OCP: New eviction strategies can be added without changing Cache.

    The internal _cache dict maps keys → Node objects.  The Node objects are
    shared with the strategy (LRUStrategy uses them as DLL nodes; LFU/TTL
    ignore the node's neighbours).
    """

    def __init__(self, capacity: int, eviction_strategy: EvictionStrategy):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self._capacity = capacity
        self._strategy = eviction_strategy
        # The primary data store: key → Node (which holds the value + DLL links)
        self._cache: Dict[K, Node[K, V]] = {}

    def get(self, key: K) -> Optional[V]:
        """Retrieve the value for *key*, or None if missing/expired.

        On a hit, the strategy's access() is called so it can update its
        ordering (LRU moves to front, LFU increments frequency, etc.).
        """
        if key not in self._cache:
            return None

        node = self._cache[key]

        # TTL check: if the key has expired, remove it and treat as a miss
        if isinstance(self._strategy, TTLStrategy):
            if self._strategy.is_expired(key):
                self._strategy.remove(key)
                del self._cache[key]
                return None

        # Notify the strategy that this key was accessed
        self._strategy.access(key, node)
        return node.value

    def put(self, key: K, value: V) -> None:
        """Insert or update a key-value pair.

        If the cache is at capacity, the strategy chooses a victim to evict.
        """
        if key in self._cache:
            # Update existing entry
            node = self._cache[key]
            node.value = value
            self._strategy.access(key, node)
            return

        # Evict if full
        if len(self._cache) >= self._capacity:
            evicted_key = self._strategy.evict()
            if evicted_key in self._cache:
                del self._cache[evicted_key]

        # Create a new Node and store it in both the cache dict and the strategy
        node = Node(key, value)
        self._cache[key] = node
        self._strategy.add(key, node)

    def remove(self, key: K) -> bool:
        """Remove *key* from the cache. Returns True if key existed."""
        if key not in self._cache:
            return False
        self._strategy.remove(key)
        del self._cache[key]
        return True

    def clear(self) -> None:
        """Remove all entries from the cache."""
        while self._cache:
            key = next(iter(self._cache))
            self.remove(key)

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def capacity(self) -> int:
        return self._capacity

    def contains(self, key: K) -> bool:
        return key in self._cache

    def __contains__(self, key: K) -> bool:
        return self.contains(key)


# ---------------------------------------------------------------------------
# CacheStats — Single Responsibility: track performance metrics
# ---------------------------------------------------------------------------

class CacheStats:
    """Tracks cache hit/miss/eviction metrics independently of the Cache class.

    This follows SRP: if we need to add logging, alerting, or histogram
    bucketing, we change *this* class, not the Cache class.
    """

    def __init__(self):
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def record_hit(self) -> None:
        self._hits += 1

    def record_miss(self) -> None:
        self._misses += 1

    def record_eviction(self) -> None:
        self._evictions += 1

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def evictions(self) -> int:
        return self._evictions

    def report(self) -> str:
        return (
            f"Cache Stats:\n"
            f"  Hits: {self._hits}\n"
            f"  Misses: {self._misses}\n"
            f"  Hit Rate: {self.hit_rate:.2%}\n"
            f"  Evictions: {self._evictions}"
        )


# ---------------------------------------------------------------------------
# CacheWithStats — Decorator pattern
# ---------------------------------------------------------------------------

class CacheWithStats(Cache):
    """Decorator that wraps a Cache and transparently records statistics.

    Uses the Decorator pattern: same interface as Cache, but adds behaviour
    (stats tracking) without modifying the Cache class.
    """

    def __init__(self, cache: Cache):
        self._cache = cache
        self._stats = CacheStats()

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def get(self, key: K) -> Optional[V]:
        value = self._cache.get(key)
        if value is not None:
            self._stats.record_hit()
        else:
            self._stats.record_miss()
        return value

    def put(self, key: K, value: V) -> None:
        old_size = self._cache.size
        self._cache.put(key, value)
        # If size didn't increase and the key is new, an eviction must have happened
        if self._cache.size <= old_size and key not in self._cache._cache:
            self._stats.record_eviction()

    def remove(self, key: K) -> bool:
        return self._cache.remove(key)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return self._cache.size

    @property
    def capacity(self) -> int:
        return self._cache.capacity


# ---------------------------------------------------------------------------
# ThreadSafeCache — RLock wrapper for concurrent access
# ---------------------------------------------------------------------------

class ThreadSafeCache(Cache):
    """Thread-safe wrapper around a Cache using a reentrant lock.

    Why RLock (reentrant) instead of Lock?
      - Some operations (e.g., get with TTL check) may call strategy methods
        that themselves acquire the lock.  RLock allows the same thread to
        re-enter.

    For higher concurrency (read-heavy workloads):
      - Replace RLock with a ReadWriteLock (Python's ``shared_memory`` or
        a third-party RWLock).  Multiple readers can proceed in parallel;
        writers get exclusive access.

    For distributed systems:
      - Use a distributed lock (Redis Redlock, ZooKeeper) + the local
        ThreadSafeCache as a client-side guard.
    """

    def __init__(self, capacity: int, eviction_strategy: EvictionStrategy):
        super().__init__(capacity, eviction_strategy)
        self._lock = RLock()

    def get(self, key: K) -> Optional[V]:
        with self._lock:
            return super().get(key)

    def put(self, key: K, value: V) -> None:
        with self._lock:
            super().put(key, value)

    def remove(self, key: K) -> bool:
        with self._lock:
            return super().remove(key)

    def clear(self) -> None:
        with self._lock:
            super().clear()

    # Properties are read-only and thread-safe by nature (dict access is atomic
    # under CPython's GIL), but we lock for consistency across operations.
    @property
    def size(self) -> int:
        with self._lock:
            return super().size

    @property
    def capacity(self) -> int:
        with self._lock:
            return super().capacity


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo():
    print("=== LRU Cache Demo ===")
    cache = Cache[int, str](3, LRUStrategy())

    cache.put(1, "One")
    cache.put(2, "Two")
    cache.put(3, "Three")
    print(f"Cache: {[(k, cache.get(k)) for k in [1, 2, 3]]}")

    # Access 1, making 2 the LRU
    print(f"Get 1: {cache.get(1)}")
    cache.put(4, "Four")  # Should evict 2
    print(f"Get 2: {cache.get(2)} (should be None)")

    print("\n=== LFU Cache Demo ===")
    lfu = Cache[int, str](3, LFUStrategy())
    lfu.put(1, "One")
    lfu.put(2, "Two")
    lfu.put(3, "Three")
    lfu.get(1)  # freq: 1
    lfu.get(1)  # freq: 2
    lfu.put(4, "Four")  # Should evict 2 (freq 0) or 3 (freq 0)
    print(f"Get 2: {lfu.get(2)} (should be None)")

    print("\n=== TTL Cache Demo ===")
    import time

    ttl_cache = Cache[int, str](3, TTLStrategy(1))  # 1 second TTL
    ttl_cache.put(1, "One")
    print(f"Get 1 (before expiry): {ttl_cache.get(1)}")
    time.sleep(1.1)
    print(f"Get 1 (after expiry): {ttl_cache.get(1)} (should be None)")

    print("\n=== ThreadSafe Cache Demo ===")
    safe_cache = ThreadSafeCache(3, LRUStrategy())
    safe_cache.put(1, "One")
    safe_cache.put(2, "Two")
    safe_cache.put(3, "Three")
    print(f"ThreadSafe size: {safe_cache.size}")
    print(f"Get 1 from ThreadSafe: {safe_cache.get(1)}")


if __name__ == "__main__":
    demo()
