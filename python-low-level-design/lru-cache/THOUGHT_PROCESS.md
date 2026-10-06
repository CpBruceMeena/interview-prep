# 🧠 LRU/LFU/TTL Cache LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![](lru-cache-class-diagram.drawio)

---

## ⏱️ How to Run This in a 45–60 min Interview

| Time | Step | What to say out loud |
|------|------|----------------------|
| 0–5 | **Clarify** | "Capacity in entries or bytes? Which policy — LRU, LFU, or pluggable? Per-key TTL? Is `None` a valid value? Does a `put` on an existing key count as a use? Concurrent access? Need a loader (cache-aside)?" |
| 5–10 | **Data structures** | "Hashmap for lookup plus a doubly linked list for order: both O(1). For LFU, one list per frequency plus `min_freq`." Draw the list with sentinels and the map pointing into it. |
| 10–30 | **Core code** | `_DList` with sentinels first (4 small methods), then `LRUCache.get/put`. Test it out loud with capacity 2: put a, put b, get a, put c → b evicted. |
| 30–40 | **Extensions** | Pull the shared parts into `BaseCache` with hooks; add LFU (bucket move + `min_freq`), then TTL (lazy check + heap). |
| 40–50 | **Concurrency** | "`get` mutates, so a RW lock doesn't help. One lock per cache; then stripe for contention. Single-flight loader against stampedes." |
| 50–60 | **Scale out** | Consistent hashing across nodes, replication, invalidation (see HLD). |

**Clarifying questions worth asking** (defaults to propose):

- Capacity unit? → entry count; bytes is an extension (weighted eviction).
- `get` on a missing key? → return a caller-supplied default, so `None` can be cached.
- Overwrite counts as a use? → yes, and it resets the TTL.
- TTL per key or global? → global default, per-key override.
- Expired entries counted in `len`? → yes until purged (lazy expiry); say so.
- Thread-safe? → yes, as a wrapper, so the single-threaded core stays simple and testable.

---

## Phase 1: Identify the Nouns

> *"A cache stores key-value pairs. When capacity is reached, a policy decides which item to remove. Entries may expire."*

| Noun | Decision | Why |
|------|----------|-----|
| Node | `__slots__` class | Holds key (needed on evict), value, expiry, freq, prev/next |
| Doubly linked list | Small class with sentinels | O(1) unlink anywhere; no head/tail special cases |
| Cache | ABC with hooks (template method) | Map + TTL + stats once; policy varies |
| LRU / LFU | Subclasses | Implement `_insert`, `_touch`, `_unlink`, `_victim` |
| TTL | Part of the base, not a policy | Any policy can have expiring entries |
| Stats | Dataclass | Hits, misses, evictions, expirations |
| Thread safety | Wrapper (`ThreadSafeCache`, `StripedCache`) | Locking is orthogonal to policy |

## Phase 2: Responsibilities

| Action | Owner | Cost |
|--------|-------|------|
| Lookup | `BaseCache._map` | O(1) |
| Recency order | `LRUCache._order` | O(1) move/unlink |
| Frequency order | `LFUCache._buckets` + `_min_freq` | O(1) bucket move |
| Expiry | `node.expires_at` (lazy) + `_expiry_heap` (purge) | O(1) check, O(log n) push |
| Mutual exclusion | `ThreadSafeCache._lock` / per-shard locks | — |
| Stampede protection | `ThreadSafeCache.get_or_load` | One loader per key |

## Phase 3: Write LRU First, Exactly

```python
def get(self, key):
    node = self._map.get(key)
    if node is None: return default
    self._list.remove(node); self._list.push_front(node)
    return node.value

def put(self, key, value):
    node = self._map.get(key)
    if node:                                   # overwrite = use
        node.value = value
        self._list.remove(node); self._list.push_front(node)
        return
    if len(self._map) >= self._capacity:       # evict before insert
        lru = self._list.back()
        self._list.remove(lru); del self._map[lru.key]
    node = Node(key, value)
    self._map[key] = node; self._list.push_front(node)
```

Then point out the duplication with LFU and refactor into hooks — interviewers like seeing the abstraction emerge from working code rather than up-front.

## Phase 4: LFU — the One Subtle Line

When a hit moves a node from bucket `f` to `f+1` and bucket `f` becomes empty, `min_freq` changes **only if** `f == min_freq`, and then it becomes exactly `f+1`. A new insert always resets `min_freq = 1`. Those two rules are the whole O(1) trick.

## Phase 5: Quick Checklist

✅ Map + DLL with sentinels; node stores its key
✅ Overwrite doesn't grow the cache and counts as a use
✅ LFU ties broken by recency; `min_freq` maintained in O(1)
✅ TTL separate from eviction; lazy + heap; expired entries reclaimed before evicting live ones
✅ Injectable clock (monotonic); tests never `sleep` for TTL
✅ One lock per cache, RW lock rejected with a reason; striping and single-flight discussed
