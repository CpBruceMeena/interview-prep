# LRU/LFU/TTL Cache - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Data structures, O(1) operations, eviction strategies, concurrency

---

## Question 1: Core Implementation
**Interviewer:** *"Implement an LRU Cache with O(1) get and put operations."*

### 🎯 Expected Answer

**Data Structure Choice: HashMap + Doubly Linked List**

```python
class Node:
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None

class LRUCache:
    def __init__(self, capacity: int):
        self._capacity = capacity
        self._cache: Dict[K, Node] = {}
        self._head = None  # Most recently used
        self._tail = None  # Least recently used
```

**Why this combination?**
- `HashMap<K, Node>` gives O(1) key lookup
- `DoublyLinkedList` gives O(1) move-to-front and eviction
- Each solves a different problem — HashMap handles *random access*, LinkedList handles *ordering*

**O(1) operations:**
```python
def get(self, key: K) -> Optional[V]:
    if key not in self._cache:
        return None
    node = self._cache[key]
    self._move_to_front(node)  # O(1) pointer updates
    return node.value

def put(self, key: K, value: V) -> None:
    if key in self._cache:
        node = self._cache[key]
        node.value = value
        self._move_to_front(node)
        return
    if len(self._cache) >= self._capacity:
        self._evict_lru()  # O(1) - remove tail
    node = Node(key, value)
    self._cache[key] = node
    self._add_to_front(node)  # O(1) - add to head
```

### 🔍 Trade-off Analysis: Why Not Alternatives?

| Approach | Get | Put | Evict | Issue |
|----------|-----|-----|-------|-------|
| **HashMap + DLL** | O(1) | O(1) | O(1) | ✅ Optimal |
| **OrderedDict** | O(1) | O(1) | O(1) | Built-in, less learning |
| **Timestamp-based** | O(1) | O(log n) | O(log n) | Heap maintenance |
| **Python list** | O(1) scan | O(n) | O(n) | Linear search |

---

## Question 2: Multi-Level Cache (L1/L2/L3)
**Interviewer:** *"Design a multi-level cache with different eviction strategies per level."*

### 🎯 Architecture

```
CPU → L1 Cache (2ns, 32KB, LRU) 
    → L2 Cache (10ns, 256KB, LFU) 
    → L3 Cache (30ns, 8MB, TTL) 
    → Main Memory (100ns)
```

**Strategy composition:**
```python
class MultiLevelCache:
    def __init__(self):
        self._l1 = Cache(256, LRUStrategy())
        self._l2 = Cache(1024, LFUStrategy())
        self._l3 = Cache(8192, TTLStrategy(3600))
    
    def get(self, key):
        if key in self._l1: return self._promote(key, 1)
        if key in self._l2: return self._promote(key, 2)
        if key in self._l3: return self._promote(key, 3)
        return None  # Cache miss — fetch from source
    
    def _promote(self, key, level):
        value = self._get_from_level(key, level)
        self._l1.put(key, value)  # Always promote to L1
        return value
```

---

## Question 3: Distributed Cache
**Interviewer:** *"Scale this across multiple servers."*

### 🎯 Architecture

**Consistent Hashing** for distribution:
```python
class ConsistentHashRing:
    def __init__(self, nodes, virtual_nodes=150):
        self._ring = {}
        for node in nodes:
            for i in range(virtual_nodes):
                hash_val = hash(f"{node}:{i}")
                self._ring[hash_val] = node
    
    def get_node(self, key):
        hash_val = hash(key)
        # Find nearest clockwise node
        for h in sorted(self._ring.keys()):
            if h >= hash_val:
                return self._ring[h]
        return self._ring[min(self._ring.keys())]  # Wrap around
```

**Cache invalidation strategies:**
- **Write-through**: Write to cache + DB synchronously — consistent, slower writes
- **Write-back**: Write to cache, async to DB — faster, risk of data loss
- **Write-around**: Write to DB, invalidate cache — avoids cache pollution

---

## Question 4: Eviction Strategy Comparison

| Strategy | Best For | Memory | Complexity | Weakness |
|----------|----------|--------|------------|----------|
| **LRU** | Temporal locality | Low | O(1) | Scan thrashing |
| **LFU** | Popularity patterns | High (freq tracking) | O(1) amortized | Historical bias |
| **TTL** | Fixed expiry | Low | O(1) | No access awareness |
| **FIFO** | Simplicity | Low | O(1) | No access pattern |
| **ARC** | Adaptive | Moderate | Complex | Implementation |
| **2Q** | Balance | Moderate | O(1) | Tuning params |

---

## Question 5: Thread Safety
**Interviewer:** *"Make your cache thread-safe."*

### 🎯 Answer (In-depth)

There are **three tiers** of thread safety, depending on deployment:

#### Tier 1 — Single-process, single-machine (Python RLock)

```python
import threading

class ThreadSafeCache:
    def __init__(self, capacity, eviction_strategy):
        self._lock = threading.RLock()  # Reentrant — allows same thread to re-acquire
        self._cache = Cache(capacity, eviction_strategy)
    
    def get(self, key):
        with self._lock:
            return self._cache.get(key)
    
    def put(self, key, value):
        with self._lock:
            self._cache.put(key, value)
```

**Why RLock over Lock?** Operations like `get()` with TTL check call `strategy.is_expired()` → `strategy.remove()`. If any of those methods need the lock (e.g., for internal consistency), RLock lets the same thread re-enter without deadlock.

#### Tier 2 — Read-heavy workloads (ReadWriteLock)

```python
from readerwriterlock import rwlock

class ThreadSafeCacheRW:
    def __init__(self, capacity, eviction_strategy):
        self._lock = rwlock.RWLockFair()  # Fair: no writer starvation
        self._cache = Cache(capacity, eviction_strategy)
    
    def get(self, key):
        with self._lock.gen_rlock():  # Multiple concurrent readers
            return self._cache.get(key)
    
    def put(self, key, value):
        with self._lock.gen_wlock():  # Exclusive write access
            self._cache.put(key, value)
```

**Trade-off:** ReadWriteLock allows N concurrent reads but serialises writes. For a 90% read / 10% write workload, throughput can be 5-10× higher than a plain Lock.

#### Tier 3 — Distributed (Redis Redlock)

For caches spanning multiple machines:

```python
import redis

class DistributedCacheLock:
    def __init__(self, redis_client, lock_ttl_ms=1000):
        self._redis = redis_client
        self._lock_ttl = lock_ttl_ms
    
    def acquire_lock(self, key):
        # SET key random_value NX PX 1000  — Redis SETNX with TTL
        lock_key = f"lock:cache:{key}"
        return self._redis.set(lock_key, self._local_id, 
                               nx=True, px=self._lock_ttl)
    
    def release_lock(self, key):
        # Lua script to ensure we only release locks we own
        lock_key = f"lock:cache:{key}"
        self._redis.eval("""
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        """, 1, lock_key, self._local_id)
```

**Redlock algorithm:** For strong consistency across 5 Redis nodes, acquire the lock from a majority (3/5). If a node crashes and restarts without persistence, the lock could be lost — add delayed restarts (TTL + a few seconds) to let locks expire.

---

## Question 6: Production Features

| Feature | Implementation |
|---------|---------------|
| **Stats** | Decorator pattern wrapping the cache |
| **Dynamic resizing** | Copy-on-resize with double buffering |
| **Persistence** | Periodic serialization to disk (RDB/AOF style) |
| **Cache warming** | Pre-load top-K from persistent store |
| **Admin API** | REST endpoints for stats, flush, resize |
| **Thread safety** | RLock (single process) / Redlock (distributed) |

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | EvictionStrategy | Pluggable eviction (LRU, LFU, TTL) |
| **Decorator** | CacheWithStats | Add stats without modifying core |
| **Factory** | Cache creation | Config-driven setup |
| **Template Method** | Cache.get/put | Consistent flow, customizable internals |
| **Adapter** | Multi-level cache | Uniform interface across levels |
| **Proxy / Guard** | ThreadSafeCache | Add thread safety transparently |

---

## 🧩 Staff-Level Evaluation Rubric

| Criteria | Excellent | Good | Needs Work |
|----------|-----------|------|------------|
| **Data structures** | HashMap + DLL, explains why O(1) | Mentions HashMap + DLL | Only one data structure |
| **Eviction strategies** | Implements 3+ (LRU, LFU, TTL), compares trade-offs | Implements 2 | Only LRU |
| **Concurrency** | Discusses RLock, RWLock, and distributed Redlock | Mentions threading.Lock | No concurrency |
| **Distributed scaling** | Consistent hashing, virtual nodes, lazy migration | Mentions sharding | No distributed design |
| **Design patterns** | Strategy, Decorator, Proxy, SRP, OCP | 1-2 patterns | No patterns mentioned |
