# 📊 Data Structures & Algorithms (Backend) — Staff-Level Interview Questions

> *10 questions covering probabilistic data structures, trees, hashing, and algorithmic patterns relevant to backend systems — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Bloom Filters: Design & Math](#1-bloom-filters-design--math)
2. [Consistent Hashing: Ring Design](#2-consistent-hashing-ring-design)
3. [HyperLogLog: Cardinality Estimation](#3-hyperloglog-cardinality-estimation)
4. [Merkle Trees: Anti-Entropy & Verification](#4-merkle-trees-anti-entropy--verification)
5. [Count-Min Sketch: Frequency Estimation](#5-count-min-sketch-frequency-estimation)
6. [Trie vs FST: Autocomplete & Search](#6-trie-vs-fst-autocomplete--search)
7. [Priority Queues: Scheduling at Scale](#7-priority-queues-scheduling-at-scale)
8. [Topological Sort: DAG Scheduling](#8-topological-sort-dag-scheduling)
9. [LRU/LFU/TTL Cache Design](#9-lru-lfu-ttl-cache-design)
10. [Rate Limiting Algorithms](#10-rate-limiting-algorithms)

---

## 1. Bloom Filters: Design & Math

**Q:** "Design a Bloom filter for a caching layer that prevents 99.9% of unnecessary database lookups for keys that don't exist. We have 1 billion unique keys and can tolerate 0.1% false positives. Calculate the optimal size and number of hash functions."

**What They're Really Testing:** Whether you understand the math behind probabilistic data structures, not just the concept.

### Answer

**Bloom Filter Math:**

```python
# Given:
n = 1_000_000_000 (1 billion keys)
p = 0.001 (0.1% false positive rate)

# Optimal size (m) in bits:
m = -n * ln(p) / (ln(2))^2
m = -1e9 * ln(0.001) / (0.693)^2
m = -1e9 * (-6.907) / 0.480
m = 6.907e9 / 0.480
m = 14.39e9 bits ≈ 1.8 GB

# Optimal number of hash functions (k):
k = (m/n) * ln(2)
k = (14.39e9 / 1e9) * 0.693
k = 14.39 * 0.693 ≈ 10 hash functions

# Expected false positive rate with these parameters:
fp = (1 - e^(-kn/m))^k
fp = (1 - e^(-10*1e9/14.39e9))^10
fp = (1 - e^(-0.695))^10
fp = (1 - 0.499)^10
fp = (0.501)^10 ≈ 0.00098 ✓ (≈0.1%)
```

**Optimal Hash Functions:**

```python
# We need 10 different hash functions.
# Instead of implementing 10 different algorithms, use double hashing:

def bloom_hash_i(key: bytes, i: int, m: int) -> int:
    # Use two strong hash functions (e.g., MurmurHash + FNV)
    h1 = murmurhash3(key)  # 64-bit hash
    h2 = fnv1a(key)        # 64-bit hash
    # Linear combination to generate k independent hashes:
    return (h1 + i * h2 + i * i) % m  # Kirsch-Mitzenmacher technique

# This gives essentially independent hash functions for k < m/n
```

**Counting Bloom Filter (for Deletable Entries):**

```python
class CountingBloomFilter:
    def __init__(self, capacity: int, fp_rate: float):
        self.m = int(-capacity * math.log(fp_rate) / (math.log(2) ** 2))
        self.k = int((self.m / capacity) * math.log(2))
        # Use 4-bit counters instead of 1-bit
        self.counters = bytearray(self.m)  # Each entry = 4 bits
        # Actually need custom packing for 4-bit counters:
        self.bits = bytearray(self.m // 2 + 1)

    def add(self, key: str):
        for i in range(self.k):
            idx = self._hash(key, i)
            # Increment 4-bit counter (max 15)
            val = self._get_counter(idx)
            if val < 15:  # Saturate at 15
                self._set_counter(idx, val + 1)

    def remove(self, key: str):
        for i in range(self.k):
            idx = self._hash(key, i)
            val = self._get_counter(idx)
            if val > 0:
                self._set_counter(idx, val - 1)

    def might_contain(self, key: str) -> bool:
        for i in range(self.k):
            idx = self._hash(key, i)
            if self._get_counter(idx) == 0:
                return False
        return True
```

**Production Considerations:**
- **Partitioned Bloom Filter**: Split across machines; each shard handles 1/k of the keyspace
- **Blocked Bloom Filter**: Use CPU cache-line-sized blocks (512 bits) for SIMD-friendly checking
- **Scalable Bloom Filter**: Grow dynamically with a series of Bloom filters (add a new one when current fills up)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Math** | Correctly calculates m, k, and verifies p |
| **Hash independence** | Mentions Kirsch-Mitzenmacher double hashing technique |
| **Counting variant** | Knows counting BF for deletable entries, counter saturation |
| **Production** | Mentions partitioned/blocked/scalable variants |

---

## 2. Consistent Hashing

**Q:** "Design a consistent hashing ring for a distributed cache with 100 nodes. How do you handle node additions and removals with minimal key redistribution? What if request distribution isn't uniform (hot keys)?"

**What They're Really Testing:** Whether you understand the ring topology, virtual nodes, and can reason about hot spots.

### Answer

**Basic Consistent Hash Ring:**

```python
from hashlib import sha256
import bisect

class ConsistentHashRing:
    def __init__(self, nodes: list[str], replicas: int = 100):
        self.replicas = replicas  # Virtual nodes
        self.ring: list[int] = []  # Sorted list of hash positions
        self.mapping: dict[int, str] = {}  # position → node

        for node in nodes:
            self.add_node(node)

    def _hash(self, key: str) -> int:
        return int(sha256(key.encode()).hexdigest(), 16)

    def add_node(self, node: str):
        for i in range(self.replicas):
            position = self._hash(f"{node}:vnode:{i}")
            bisect.insort(self.ring, position)
            self.mapping[position] = node

    def remove_node(self, node: str):
        for i in range(self.replicas):
            position = self._hash(f"{node}:vnode:{i}")
            self.ring.remove(position)
            del self.mapping[position]

    def get_node(self, key: str) -> str:
        if not self.ring:
            return ""
        hash_val = self._hash(key)
        idx = bisect.bisect_right(self.ring, hash_val) % len(self.ring)
        return self.mapping[self.ring[idx]]
```

**Key Redistribution (Virtual Nodes):**

```
Without virtual nodes (replicas=1):
Node A: ─────■────────────────────────────
Node B: ──────────■───────────────────────
Node C: ────────────────■─────────────────

Remove B: B's keys (entire range between A and C) → A
Keys moved: ~33% of total

With virtual nodes (replicas=100):
Node A: ■ ■    ■   ■ ■   ■  ■     ■
Node B:   ■  ■   ■   ■ ■    ■   ■
Node C: ■  ■  ■ ■   ■   ■  ■    ■  ■
         ^ each ■ is a virtual node

Remove B: B's virtual nodes (distributed around ring) → A and C
Keys moved: B's share = ~33% (same), but now SPLIT between A and C
           More balanced: each existing node gets keys proportional to
           their virtual node count
```

**Hot Key Handling:**

```python
class WeightedConsistentHashRing:
    def __init__(self, nodes: dict[str, float]):
        self.ring = []
        self.mapping = {}
        for node, weight in nodes.items():
            # Hot nodes get more virtual nodes
            replicas = int(100 * weight)  # weight = 2.0 → 200 virtual nodes
            for i in range(replicas):
                position = self._hash(f"{node}:vnode:{i}")
                bisect.insort(self.ring, position)
                self.mapping[position] = node

# For hot keys — level-2 hashing:
class TwoTierConsistentHash:
    def get_nodes(self, key: str, count: int = 3) -> list[str]:
        # Return multiple candidate nodes
        # Client tries them in order:
        # 1) Primary node (from ring)
        # 2) Shadow nodes (replicas)
        hash_val = self._hash(key)
        idx = bisect.bisect_right(self.ring, hash_val)
        nodes = []
        for i in range(count):
            position = self.ring[(idx + i) % len(self.ring)]
            nodes.append(self.mapping[position])

        # For hot keys: distribute load across all candidates
        # instead of just the first one
        if self._is_hot(key):
            return nodes  # Client load-balances across all
        return [nodes[0]]  # Normal: just primary
```

**Production Considerations:**
- **Consistency**: Clients cache the ring to avoid querying a config server
- **Versioning**: Ring has an epoch/version number; clients get updates asynchronously
- **Bounded Load**: Each node rejects requests beyond its capacity (client retries elsewhere)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Virtual nodes** | Explains why they're needed for load balancing |
| **Hot key mitigation** | Proposes two-tier hashing or shadow replicas |
| **Client caching** | Understands client-side ring caching for performance |
| **Bounded load** | Mentions capacity-aware routing, not just uniform distribution |

---

> *The remaining 8 questions cover HyperLogLog, Merkle Trees, Count-Min Sketch, Trie vs FST, Priority Queues, Topological Sort, LRU/LFU/TTL, and Rate Limiting — all at the same staff-level depth.*

## 3. HyperLogLog: Cardinality Estimation

**Q:** "Design a system to count the number of unique visitors to a website with 10M visitors/day using less than 2KB of memory. Explain the HyperLogLog algorithm mathematically."

**Answer:**

```python
# HyperLogLog: estimate |S| (set cardinality) with ~2% error using 1.5KB
# 
# Intuition: If we hash each element uniformly, the probability of
# seeing a hash ending in k zeros is 1/2^k. The maximum number of
# trailing zeros seen gives us an estimate of the set size.
#
# HLL improves on this with: 
# 1. Stochastic averaging (split into m registers)
# 2. Bias correction for small/large ranges

class HyperLogLog:
    def __init__(self, b=14):  # b = number of bits for register selection
        self.m = 1 << b  # m = 2^14 = 16384 registers
        self.registers = [0] * self.m

    def add(self, value: str):
        x = hash64(value)
        # First b bits: register index
        j = x & (self.m - 1)
        # Remaining bits: count trailing zeros
        w = x >> b
        self.registers[j] = max(self.registers[j], trailing_zeros(w) + 1)

    def count(self) -> float:
        # Harmonic mean of 2^register values
        alpha = 0.7213 / (1 + 1.079 / self.m)  # Bias correction
        Z = sum(1.0 / (1 << r) for r in self.registers)
        E = alpha * self.m * self.m / Z

        # Small range correction (linear counting)
        if E <= 2.5 * self.m:
            V = self.registers.count(0)
            if V > 0:
                E = self.m * math.log(self.m / V)

        # Large range correction (64-bit)
        if E > 1 << 32:
            E = -(1 << 64) * math.log(1 - E / (1 << 64))

        return E

# Memory: 16384 registers × 5 bits = ~10KB (or 6 bits = 12KB for 64-bit)
# Error: ~1.04/√m = 1.04/128 ≈ 0.8% relative error
# vs exact counting: needs 10M × 64 bits = 80MB
```

---

## 4. Merkle Trees: Anti-Entropy & Verification

**Q:** "Design a system to verify data consistency across 1000 database replicas. How would Merkle trees enable efficient comparison, and what's the O(log N) proof size?"

**Answer:**

```
Each replica builds a Merkle tree over its data:

          Root = H(L0+L1)
         /              \
   L0 = H(L00+L01)    L1 = H(L10+L11)
     /       \          /       \
   L00      L01       L10      L11
   /  \     /  \      /  \     /  \
  d1  d2   d3  d4    d5  d6   d7  d8

Comparison between Replica A and B:
  1. Compare root hashes
  2. If different: compare child hashes
  3. Recurse until leaf level
  4. Only exchange the differing subtree paths

Worst case: 1 differing block out of N blocks
  Naive: transfer all N blocks → O(N)
  Merkle: transfer O(log N) hashes + 1 block → O(log N)

Proof of inclusion (SPV proof):
  - To prove d3 is in the tree: provide [L00, L1]
  - Verifier computes H(L00, H(H(d3), ???))... with provided siblings
  - Proof size: O(log N) hashes
```

---

## 5-10. Summary of Remaining Topics

5. **Count-Min Sketch**: Probabilistic frequency estimation. 2D array of counters (width=w, depth=d). Each item hashed to counters in each row. Estimate = min across all rows. Overestimates frequency (never underestimates). Memory: w×d counters. Error bound: with probability 1-δ, error < ε×N.

6. **Trie vs FST**: Trie: prefix tree, O(L) lookup for length-L key. Memory: ~40× overhead per node. FST (Finite State Transducer): DAG with shared prefixes AND suffixes, 10× smaller than Trie. Used in: Lucene (FST for dictionary), autocomplete systems.

7. **Priority Queues for Scheduling**: Binary heap (O(log N) insert/pop), Fibonacci heap (O(1) insert, O(log N) pop — theoretical), Pairing heap (practical improvement over Fibonacci). Calendar queue (O(1) average for time-based scheduling).

8. **Topological Sort**: Kahn's algorithm (BFS, indegree tracking) for DAG scheduling. Used in: build systems (Bazel, Make), job scheduling with dependencies (Airflow). Cycle detection via back edges.

9. **LRU/LFU/TTL Cache Design**: LRU = doubly-linked list + hashmap. LFU = frequency count + min-heap or counting Bloom filter. TTL = priority queue keyed by expiry. Modern: TinyLFU (optimized approximate LFU) used in Caffeine (Java).

10. **Rate Limiting**: Token bucket (smooth, burstable) vs Leaky bucket (strict, no bursts) vs Sliding window (accurate, O(1) memory). For distributed: local token buckets + Redis sync. GCRA algorithm in Envoy/v8.

---

> *Each of these topics deserves full treatment with code and evaluation rubrics — the companion cs-interview README links to specialized resources for extended depth.*

