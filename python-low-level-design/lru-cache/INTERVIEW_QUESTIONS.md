# LRU/LFU/TTL Cache - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Data structures, O(1) operations, eviction policies, expiry, concurrency, distribution

---

## Question 1: Core Implementation
**Interviewer:** *"Implement an LRU Cache with O(1) get and put operations."*

### 🎯 Expected Answer

**Hashmap + doubly linked list.** The map gives O(1) lookup from key to node. The list keeps recency order: front = most recent, back = least recent. Because the list is doubly linked and every node knows its neighbours, unlinking any node is O(1). The node stores its key so evicting from the back can delete the map entry.

```python
class _DList:                        # head/tail sentinels: no None checks
    def push_front(self, n):
        n.prev, n.next = self.head, self.head.next
        self.head.next.prev = n
        self.head.next = n
    def remove(self, n):
        n.prev.next, n.next.prev = n.next, n.prev
    def back(self):
        return None if self.tail.prev is self.head else self.tail.prev

def get(self, key, default=None):
    node = self._map.get(key)
    if node is None:
        return default
    self._order.remove(node); self._order.push_front(node)
    return node.value

def put(self, key, value):
    node = self._map.get(key)
    if node:
        node.value = value
        self._order.remove(node); self._order.push_front(node)
        return
    if len(self._map) >= self._capacity:
        lru = self._order.back()
        self._order.remove(lru); del self._map[lru.key]
    node = Node(key, value)
    self._map[key] = node; self._order.push_front(node)
```

### 🔍 Alternatives

| Approach | get | put | Note |
|----------|-----|-----|------|
| **Hashmap + DLL** | O(1) | O(1) | The answer |
| `OrderedDict` (`move_to_end`, `popitem(last=False)`) | O(1) | O(1) | Same structure inside CPython; use it in production, but expect to be asked to build it |
| Hashmap + timestamp, scan for min on evict | O(1) | O(n) | Eviction scans everything |
| Hashmap + min-heap on last-access time | O(log n) | O(log n) | Every `get` must update the heap (decrease-key or lazy entries) |
| List of keys | O(n) | O(n) | Removing from the middle shifts elements |

---

## Question 2: "Now make it LFU, still O(1)"

```
key -> node(freq)
freq -> DLL of nodes with that freq (front = most recent)
min_freq
```

- **Hit:** unlink from bucket `f`, push to front of bucket `f+1`. If bucket `f` is now empty and `f == min_freq`, then `min_freq = f+1`.
- **Insert:** bucket 1, `min_freq = 1`.
- **Evict:** back of bucket `min_freq` — least frequent, and least recent among ties.
- **Delete/expire** emptying the min bucket: `min_freq` is unknown. Recompute lazily (`min(buckets)`) only if an eviction comes before the next insert. For strict O(1) on every path, keep frequency buckets in their own ascending linked list (Shah–Mitra–Matani O(1) LFU).

Follow-up: *"What's wrong with LFU in practice?"* Old popular items never leave (frequency never decays), and new items are evicted first because they start at 1. Fixes: decay counts (Redis LFU decrements its log counter per idle period), windowed admission (W-TinyLFU in Caffeine), or LRU with a probation segment (SLRU/2Q).

---

## Question 3: "Add TTL"

- Store `expires_at` on the node; read time from an injected **monotonic** clock (wall-clock jumps from NTP must not expire everything).
- **Lazy expiry:** `get` on an expired node removes it and reports a miss. Cheap, but expired entries that are never read hold memory.
- **Active expiry:** min-heap of `(expires_at, seq, node)`; a purge pops due entries. Overwrites leave stale heap entries — skip any popped entry whose node is no longer in the map or whose `expires_at` changed, and rebuild the heap when it grows past ~2× live size.
- **On a full `put`, purge expired entries before evicting a live one.**
- Don't model TTL as an eviction *policy*. A full TTL-only cache with nothing expired has no victim. TTL and capacity eviction are orthogonal.

Redis uses lazy expiry plus a periodic job that samples keys with a TTL and deletes expired ones, repeating while a large share of the sample was expired. Alternatives: a timer wheel (O(1) schedule, coarse granularity), or one timer per key (too many timers).

---

## Question 4: Thread Safety and Lock Granularity
**Interviewer:** *"Make your cache thread-safe. Then make it scale."*

**Step 1 — one lock.** Wrap every operation in one mutex. The map, the list and the heap must change together; locking only the map leaves the list corrupt.

**Step 2 — explain why not a read-write lock.** In an LRU, `get` moves the node to the front. In an LFU, it changes the node's bucket. **Every `get` is a write**, so a RW lock gives no read concurrency and adds overhead. A RW lock helps only if reads stop mutating: e.g. record accesses in a buffer and apply them later, or use approximate recency (CLOCK: a "referenced" bit set without the lock, swept by the evictor).

**Step 3 — lock striping.** Split into N shards by `hash(key) % N`, each with its own lock and `capacity / N` slots. Contention drops about N-fold. What you give up:

| Cost | Why it matters |
|------|----------------|
| Approximate global LRU | Each shard evicts its own LRU, which may be hotter than another shard's |
| Uneven capacity use | A hot shard evicts while others are half empty |
| Whole-cache ops are slower | `size`, `clear`, resize touch every shard, and aren't atomic across shards unless you take all locks in a fixed order |

Pick N as a power of two, ~2–4× core count, with a well-mixed hash. This is how Guava's `LocalCache` segments work.

**Step 4 — what the best libraries do.** Caffeine never blocks reads on recency updates: reads append to striped lock-free ring buffers, and a maintenance task drains them into the LRU/W-TinyLFU structures under a lock acquired with `tryLock`. Lost read events are acceptable because eviction order is only a heuristic.

**Python-specific note:** under the GIL, pure-Python operations don't run in parallel, so striping mainly cuts lock convoying. On free-threaded CPython (3.13t+) or in Java/Go it raises throughput.

**Not Redlock.** A distributed lock is not how you make a cache thread-safe. A remote cache (Redis/Memcached) makes each command atomic on the server; multi-key updates use transactions/Lua or CAS (`WATCH`, memcached `cas`).

---

## Question 5: Cache Stampede
**Interviewer:** *"A hot key expires and 1,000 requests miss at once. What happens?"*

They all hit the database. Fixes, from local to global:

1. **Single-flight / request coalescing:** the first miss registers an in-flight marker; others wait for its result. `ThreadSafeCache.get_or_load` does this with a per-key `Event`, and runs the loader **outside** the cache lock so unrelated keys aren't blocked behind a slow DB call.
2. **Stale-while-revalidate / refresh-ahead:** serve the old value and refresh in the background when the TTL is close.
3. **TTL jitter:** `ttl = base + random(0, jitter)` so keys written together don't expire together.
4. **Distributed:** a short Redis lock (`SET key NX PX`) per hot key, or Memcache-style leases (Facebook's memcache paper), so only one server reloads.

Race to call out: a loader result can overwrite a newer `put` that landed during the load. Guard with a version number or have `put` invalidate the in-flight load.

---

## Question 6: Testing Strategy

- **Model-based (differential) tests:** run thousands of random get/put/delete operations against the cache and a trivially correct reference (an `OrderedDict` for LRU; a dict with `(freq, last_used)` and `min()` for LFU); compare after every step.
- **Invariant checks** after each step: map size = list length ≤ capacity; every node in bucket `f` has `freq == f`; `min_freq == min(buckets)`.
- **Edge cases:** capacity 1; overwrite doesn't grow; `None` values; `__contains__` doesn't touch recency; delete then evict (LFU min bucket).
- **TTL with a fake clock:** never `sleep`. Test boundaries (`expires_at == now` is expired), overwrite resets TTL, stale heap entries are ignored, the heap stays bounded.
- **Concurrency:** threads hammer random ops; assert no exceptions, invariants hold, and `hits + misses == number of gets` (no lost counter updates). Single-flight: 12 threads miss on one key → the loader runs once; loader errors reach every waiter and aren't cached.

---

## Question 7: Multi-Level Cache (L1 in-process, L2 remote)
**Interviewer:** *"Add a local cache in front of Redis."*

```
get(k): L1 (in-process LRU, small, short TTL) → L2 (Redis) → DB
        fill L2 then L1 on the way back
```

- **Invalidation is the hard part.** On write, delete from DB-backed L2 and broadcast an invalidation (Redis pub/sub or a change-data-capture stream) so every instance drops its L1 copy. Messages can be lost, so L1 TTLs must be short (seconds) to bound staleness.
- Keep L1 small and for read-mostly, hot data; it multiplies memory by the number of instances.
- Don't promote into L1 on every L2 hit for scan-heavy access; use an admission filter (e.g. only after the second hit).

---

## Question 8: Distributed Cache
**Interviewer:** *"Scale this across multiple servers."*

**Consistent hashing** with virtual nodes:
```python
import bisect, hashlib

def _h(s: str) -> int:                      # stable across processes
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:8], "big")

class ConsistentHashRing:
    def __init__(self, nodes, vnodes=150):
        self._ring = sorted((_h(f"{n}#{i}"), n) for n in nodes for i in range(vnodes))
        self._points = [p for p, _ in self._ring]

    def node_for(self, key: str) -> str:
        i = bisect.bisect(self._points, _h(key)) % len(self._ring)
        return self._ring[i][1]
```

Two bugs to avoid: Python's built-in `hash()` of `str` is randomized per process (`PYTHONHASHSEED`), so two clients would disagree on placement; and sorting the ring on every lookup is O(n log n) — sort once, then binary-search.

Adding a node moves ~1/N of keys; for a cache those keys simply miss and reload. Redis Cluster uses 16,384 fixed hash slots instead of a ring; moving slots is an explicit, operator-driven step.

**Write strategies:**
- **Cache-aside:** read through cache, write to DB then delete the key. Most common. Race: a slow reader can repopulate a stale value after the delete; mitigate with short TTLs, leases, or delayed double-delete.
- **Write-through:** write cache and DB on the same path. Fresher reads, but not atomic — a crash between the two writes leaves them divergent.
- **Write-behind:** write cache, flush to DB asynchronously. Fast; data loss if the cache node dies before flushing.

---

## ❌ Common Mistakes

- Singly linked list (can't unlink in O(1)) or a node that doesn't store its key (can't delete the map entry on evict).
- Forgetting the overwrite path: it adds a second node or evicts unnecessarily.
- Inserting first and then checking `len >= capacity`: evicts one entry too many, so the cache never fills.
- Returning `None` for a miss when `None` is a valid value.
- LFU: arbitrary tie-breaking, or recomputing `min_freq` with a scan on every access.
- TTL implemented as an eviction policy; `time.time()` instead of a monotonic clock; tests that `sleep`.
- "Use a read-write lock for read-heavy workloads" — `get` mutates.
- Locking the map but not the list, or releasing the lock between the check and the update.
- Calling the loader while holding the cache lock (one slow key blocks all keys).
- Python `hash()` for consistent hashing across processes.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** writes a correct O(1) LRU with sentinels quickly, handles overwrite and capacity edge cases, extends to LFU with `min_freq`, adds TTL with lazy expiry, wraps it in a lock, and tests it with a reference model.
- **Staff:** explains why `get` being a write rules out RW locks and what does work (striping, buffered recency, CLOCK); names the trade-offs of striping; separates expiry from eviction; protects the backing store (single-flight, jitter, stale-while-revalidate); knows LFU's ageing problem and what production caches do about it (W-TinyLFU, Redis decay); carries the design to a fleet with correct invalidation and a stable hash.
