# 🧠 LRU/LFU/TTL Cache LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

What eviction strategy? (LRU, LFU, TTL?) Capacity limit? Thread safety? Statistics tracking? Generics support?

## Phase 1: Identify the Nouns

> *"A cache stores key-value pairs. When capacity is reached, an eviction strategy decides which item to remove."*

| Noun | Decision | Why |
|------|----------|-----|
| Node | Regular Class | Doubly linked list node (key, value, prev, next) |
| Cache | Regular (Generic) | Core cache with Dict + Strategy |
| EvictionStrategy | ABC | Strategy pattern |
| LRUStrategy | Regular | Least Recently Used: doubly linked list |
| LFUStrategy | Regular | Least Frequently Used: frequency map |
| TTLStrategy | Regular | Time To Live: expiry map |
| CacheStats | Regular | Hit/miss/eviction counters |
| CacheWithStats | Regular | Decorator pattern |
| ThreadSafeCache | Regular | Wraps Cache with lock |

## Phase 2: Enums First

The cache design doesn't need many enums — it's more algorithmic. The strategies themselves are the "enum of behaviors."

## Phase 3: dataclass vs `__init__`

- **`Node`**: Regular — linked list node with prev/next pointers
- **`Cache`**: Regular — generic class with complex behavior
- **`EvictionStrategy`**: ABC — interface for strategies
- **`CacheStats`**: Regular — counters with methods
- **`CacheWithStats`**: Regular — decorator pattern

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Store key-value | `Cache._cache` (Dict) | Fast O(1) lookups |
| Track access order | `LRUStrategy` | Doubly linked list + node map |
| Track access frequency | `LFUStrategy` | Frequency map + min_freq tracking |
| Track expiration | `TTLStrategy` | Expiry map with TTL per key |
| Evict item | Strategy's `evict()` | Each strategy evicts differently |
| Get/Put item | `Cache.get()`/`put()` | Delegates to strategy for eviction |
| Record stats | `CacheStats.record_hit()` | SRP: stats are separate |

## Phase 5: The Node + Doubly Linked List (LRU)

```python
class Node:
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None

# LRUStrategy maintains:
# _head (most recent) ←→ ... ←→ _tail (least recent)
# _node_map: Dict[Any, Node]  # O(1) lookup
```

On access: move node to front (O(1))
On eviction: remove from tail (O(1))
On capacity reached: evict tail, add to front

## Phase 6: Strategy Pattern

```python
class EvictionStrategy(ABC):
    def access(self, key, node)     # Called on get/put
    def add(self, key, node)        # Called on put (new key)
    def evict(self) -> Any          # Return key to evict
    def remove(self, key)           # Called on explicit remove

class LRUStrategy(EvictionStrategy):  # Doubly linked list
class LFUStrategy(EvictionStrategy):  # Frequency tracking
class TTLStrategy(EvictionStrategy):  # Expiry time checks
```

The `Cache` class doesn't know *how* eviction works — it just calls `strategy.evict()`.

## Phase 7: Decorator Pattern for Stats

```python
class CacheWithStats:
    def __init__(self, cache: Cache):
        self._cache = cache
        self._stats = CacheStats()
    
    def get(self, key):
        result = self._cache.get(key)
        if result: self._stats.record_hit()
        else: self._stats.record_miss()
        return result
```

This adds stats tracking without modifying the Cache class.

## Phase 8: Quick Checklist

✅ **Strategy Pattern:** Eviction algorithms are swappable
✅ **LRU:** O(1) get/put/evict with doubly linked list + map
✅ **LFU:** O(1) with frequency buckets
✅ **Decorator Pattern:** Stats tracking doesn't pollute Cache
✅ **SRP:** Cache stores, Strategy evicts, Stats tracks
✅ **OCP:** New eviction strategy → new subclass, zero Cache changes
