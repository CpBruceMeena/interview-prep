# LRU/LFU/TTL Cache — Implementation

> Python implementation of the LRU/LFU/TTL Cache system following SOLID principles and design patterns.

```python
"""
LRU Cache - Low Level Design
-------------------------------
Design Principles: SOLID, O(1) operations
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar, Generic

K = TypeVar('K')
V = TypeVar('V')


# --- Node for Doubly Linked List ---

class Node(Generic[K, V]):
    """Node for doubly linked list"""
    def __init__(self, key: K, value: V):
        self.key = key
        self.value = value
        self.prev: Optional[Node] = None
        self.next: Optional[Node] = None


# --- Eviction Strategy (Strategy Pattern - OCP) ---

class EvictionStrategy(ABC):
    """Interface for cache eviction strategies"""

    @abstractmethod
    def access(self, key: Any, node: Node) -> None:
        """Called when a key is accessed"""
        pass

    @abstractmethod
    def add(self, key: Any, node: Node) -> None:
        """Called when a new key is added"""
        pass

    @abstractmethod
    def evict(self) -> Any:
        """Returns the key to evict"""
        pass

    @abstractmethod
    def remove(self, key: Any) -> None:
        """Called when a key is removed"""
        pass


class LRUStrategy(EvictionStrategy):
    """Least Recently Used - evicts the least recently accessed item"""

    def __init__(self):
        self._head: Optional[Node] = None
        self._tail: Optional[Node] = None
        self._node_map: Dict[Any, Node] = {}

    def _remove_node(self, node: Node) -> None:
        if node.prev:
            node.prev.next = node.next
        if node.next:
            node.next.prev = node.prev
        if node == self._head:
            self._head = node.next
        if node == self._tail:
            self._tail = node.prev
        node.prev = None
        node.next = None

    def _add_to_front(self, node: Node) -> None:
        node.next = self._head
        node.prev = None
        if self._head:
            self._head.prev = node
        self._head = node
        if self._tail is None:
            self._tail = node

    def access(self, key: Any, node: Node) -> None:
        if node in self._node_map.values():
            self._remove_node(node)
        self._add_to_front(node)

    def add(self, key: Any, node: Node) -> None:
        self._add_to_front(node)
        self._node_map[key] = node

    def evict(self) -> Any:
        if not self._tail:
            raise ValueError("Nothing to evict")
        key = self._tail.key
        self._remove_node(self._tail)
        del self._node_map[key]
        return key

    def remove(self, key: Any) -> None:
        node = self._node_map.pop(key, None)
        if node:
            self._remove_node(node)


class LFUStrategy(EvictionStrategy):
    """Least Frequently Used - evicts the least frequently accessed item"""

    def __init__(self):
        self._freq_map: Dict[int, set] = {}
        self._key_freq: Dict[Any, int] = {}
        self._min_freq = 0

    def access(self, key: Any, node: Node) -> None:
        freq = self._key_freq.get(key, 0)
        if key in self._key_freq:
            self._freq_map[freq].discard(key)
            if not self._freq_map.get(freq) and freq == self._min_freq:
                # Find next non-empty frequency
                while self._min_freq < max(self._key_freq.values(), default=0):
                    self._min_freq += 1
                    if self._freq_map.get(self._min_freq):
                        break
        new_freq = freq + 1
        self._key_freq[key] = new_freq
        if new_freq not in self._freq_map:
            self._freq_map[new_freq] = set()
        self._freq_map[new_freq].add(key)
        self._min_freq = new_freq if self._min_freq == 0 else min(self._min_freq, new_freq)

    def add(self, key: Any, node: Node) -> None:
        self.access(key, node)

    def evict(self) -> Any:
        if self._min_freq not in self._freq_map or not self._freq_map[self._min_freq]:
            raise ValueError("Nothing to evict")
        key = next(iter(self._freq_map[self._min_freq]))
        self._freq_map[self._min_freq].discard(key)
        del self._key_freq[key]
        return key

    def remove(self, key: Any) -> None:
        freq = self._key_freq.pop(key, None)
        if freq and freq in self._freq_map:
            self._freq_map[freq].discard(key)


class TTLStrategy(EvictionStrategy):
    """Time To Live - evicts expired items"""

    def __init__(self, default_ttl_seconds: int = 3600):
        self._default_ttl = default_ttl_seconds
        self._expiry_map: Dict[Any, float] = {}
        import time
        self._time = time

    def access(self, key: Any, node: Node) -> None:
        pass  # TTL doesn't change on access

    def add(self, key: Any, node: Node) -> None:
        self._expiry_map[key] = self._time.time() + self._default_ttl

    def evict(self) -> Any:
        now = self._time.time()
        for key, expiry in list(self._expiry_map.items()):
            if now >= expiry:
                del self._expiry_map[key]
                return key
        raise ValueError("Nothing to evict")

    def remove(self, key: Any) -> None:
        self._expiry_map.pop(key, None)

    def is_expired(self, key: Any) -> bool:
        expiry = self._expiry_map.get(key)
        return expiry is not None and self._time.time() >= expiry


# --- Cache (Facade / SRP / DIP) ---

class Cache(Generic[K, V]):
    """Generic cache with pluggable eviction strategy.
    Follows Dependency Inversion: depends on EvictionStrategy abstraction."""

    def __init__(self, capacity: int, eviction_strategy: EvictionStrategy):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self._capacity = capacity
        self._strategy = eviction_strategy
        self._cache: Dict[K, Node[K, V]] = {}

    def get(self, key: K) -> Optional[V]:
        if key not in self._cache:
            return None
        node = self._cache[key]

        # Check TTL
        if isinstance(self._strategy, TTLStrategy):
            if self._strategy.is_expired(key):
                self._strategy.remove(key)
                del self._cache[key]
                return None

        self._strategy.access(key, node)
        return node.value

    def put(self, key: K, value: V) -> None:
        if key in self._cache:
            node = self._cache[key]
            node.value = value
            self._strategy.access(key, node)
            return

        if len(self._cache) >= self._capacity:
            evicted_key = self._strategy.evict()
            if evicted_key in self._cache:
                del self._cache[evicted_key]

        node = Node(key, value)
        self._cache[key] = node
        self._strategy.add(key, node)

    def remove(self, key: K) -> bool:
        if key not in self._cache:
            return False
        self._strategy.remove(key)
        del self._cache[key]
        return True

    def clear(self) -> None:
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


# --- Cache Statistics (SRP) ---

class CacheStats:
    """Single Responsibility: Track cache performance metrics"""

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


# --- Decorator for Stats ---

class CacheWithStats(Cache):
    """Decorator that adds statistics tracking"""

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


# --- Demo ---

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


if __name__ == "__main__":
    demo()
```

---

## ▶️ How to Run

```bash
cd low-level-design/lru-cache
python lru_cache.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
