# 📐 Data Structures for Scale — Staff/Principal-Level Interview Q&A

> *12 deep-dive topics covering probabilistic data structures, spatial indexes, and ordered structures used at scale in production systems — every question expects principal engineer-level depth with mathematical rigor, production trade-offs, and real-world war stories.*

---

## Table of Contents

1. [Bloom Filter: Approximate Membership](#1-bloom-filter-approximate-membership)
2. [Cuckoo Filter: Better Bloom](#2-cuckoo-filter-better-bloom)
3. [HyperLogLog: Cardinality Estimation](#3-hyperloglog-cardinality-estimation)
4. [Count-Min Sketch: Frequency Estimation](#4-count-min-sketch-frequency-estimation)
5. [MinHash: Set Similarity](#5-minhash-set-similarity)
6. [Geohash: Spatial Encoding](#6-geohash-spatial-encoding)
7. [S2 Geometry: Hierarchical Spatial Indexing](#7-s2-geometry-hierarchical-spatial-indexing)
8. [H3: Hexagonal Grid System](#8-h3-hexagonal-grid-system)
9. [Quad Tree: 2D Spatial Partitioning](#9-quad-tree-2d-spatial-partitioning)
10. [R-Tree: Bounding Box Index](#10-r-tree-bounding-box-index)
11. [Skip List: Probabilistic Ordered Structure](#11-skip-list-probabilistic-ordered-structure)
12. [Merkle Tree: Tamper-Evident Verification](#12-merkle-tree-tamper-evident-verification)

---

## 1. Bloom Filter: Approximate Membership

**Q:** "We run a news aggregator serving 500M unique URLs per day. We need to avoid re-crawling the same URL twice. Design a system that tracks seen URLs with < 1GB memory. What false-positive rate can you guarantee? Walk me through the math."

**What They're Really Testing:** Whether you can reason about the trade-off space between memory, false-positive rate, and capacity — and whether you know which variant to use when.

### Answer

**Classic Bloom Filter Math:**

```python
# Given: n = 500M URLs, m = 1GB = 8e9 bits
# Solve for achievable false-positive rate (p):

n = 500_000_000
m = 8_000_000_000
k = optimal_k(m, n)

# Optimal k = (m/n) * ln(2)
k = (8e9 / 5e8) * 0.693 = 16 * 0.693 ≈ 11 hash functions

# Expected false-positive rate:
p = (1 - e^(-k * n / m))^k
p = (1 - e^(-11 * 5e8 / 8e9))^11
p = (1 - e^(-0.6875))^11
p = (1 - 0.502)^11
p = (0.498)^11 ≈ 0.00048 → 0.048% FPR

# So with 1GB, we achieve 99.95% accuracy at 500M unique URLs.
```

**But here's where the staff-level answer begins — the production deployment:**

```python
# ==============================
# PRODUCTION BLOOM FILTER
# ==============================
import mmh3
import math
from bitarray import bitarray
from typing import List, Optional

class ScalableBloomFilter:
    """Gracefully grows when capacity is exceeded."""
    
    def __init__(self, initial_capacity: int, fp_rate: float = 0.01,
                 scaling_factor: float = 2.0):
        self.filters: List[BloomFilter] = []
        self.fp_rate = fp_rate
        self.scaling_factor = scaling_factor
        self.current = BloomFilter(initial_capacity, fp_rate)
        self.filters.append(self.current)

    def add(self, item: str):
        if self.current.is_full():
            # Create a new filter with tighter FPR
            new_fp = self.fp_rate * (1 - self.scaling_factor ** -1)
            new_capacity = int(self.current.capacity * self.scaling_factor)
            self.current = BloomFilter(new_capacity, new_fp)
            self.filters.append(self.current)
        self.current.add(item)

    def might_contain(self, item: str) -> bool:
        # Check newest filter first (most likely to match)
        for bf in reversed(self.filters):
            if bf.might_contain(item):
                return True
        return False

    def size_bytes(self) -> int:
        return sum(bf.size_bytes() for bf in self.filters)


class BloomFilter:
    def __init__(self, capacity: int, fp_rate: float = 0.01):
        self.capacity = capacity
        # Size in bits
        self.m = int(-capacity * math.log(fp_rate) / (math.log(2) ** 2))
        # Number of hash functions
        self.k = int((self.m / capacity) * math.log(2))
        self.bits = bitarray(self.m)
        self.bits.setall(0)
        self.count = 0

    def _hashes(self, item: str):
        """Kirsch-Mitzenmacher double hashing for k independent hashes."""
        h1 = mmh3.hash64(item, seed=0)[0] & 0xFFFFFFFFFFFFFFFF
        h2 = mmh3.hash64(item, seed=1)[0] & 0xFFFFFFFFFFFFFFFF
        for i in range(self.k):
            yield (h1 + i * h2 + (i ** 2)) % self.m

    def add(self, item: str):
        for pos in self._hashes(item):
            self.bits[pos] = 1
        self.count += 1

    def might_contain(self, item: str) -> bool:
        return all(self.bits[pos] for pos in self._hashes(item))

    def is_full(self) -> bool:
        return self.count >= self.capacity

    def size_bytes(self) -> int:
        return len(self.bits) // 8
```

**Production Variants and When to Use Them:**

| Variant | Key Feature | Use Case |
|---------|-------------|----------|
| **Classic Bloom** | Simple, fastest | Cache dedup (Cassandra, HBase) |
| **Scalable Bloom** | Grows dynamically | URL crawlers, unknown cardinality |
| **Counting Bloom** | Supports deletion | Caching with TTL / eviction |
| **Blocked Bloom** | CPU cache-line sized | SIMD-friendly, ~2x faster lookups |
| **Cuckoo Filter** | Supports deletion, lower FPR | See next section |

**Staff-Level Trade-Offs:**
- **False positives are acceptable** (re-crawl 0.05% of URLs) — but false negatives are NOT (you never miss a new URL)
- **Counting BF uses 4× more memory** (4-bit counters) — only use if you need deletion
- **Blocked Bloom** gives 2× lookup speed by fitting in L1 cache (512-bit blocks) at the cost of slightly higher FPR
- **~1.8GB** would get you 0.001% FPR — is that worth the extra 800MB?

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Math** | Calculates m, k, p correctly from scratch |
| **Hash independence** | Names Kirsch-Mitzenmacher double hashing |
| **Scaling** | Mentions Scalable Bloom Filter for unknown cardinality |
| **Production** | Discusses blocked variant, cache-line alignment |

---

## 2. Cuckoo Filter: Better Bloom

**Q:** "Your caching layer needs to support deletion of stale entries from the probabilistic filter. A counting Bloom filter uses 4× memory. Design a better alternative. What's the Cuckoo filter's advantage, and what's its Achilles' heel?"

**What They're Really Testing:** Whether you understand the fundamental trade-off between Bloom filters (bit array + hashes) and Cuckoo filters (hash table + fingerprints). Most engineers know Bloom filters; staff engineers know when Bloom isn't enough.

### Answer

**Cuckoo Filter — Core Idea:**

Instead of setting bits in a bit array, a Cuckoo filter stores a *fingerprint* (small hash, e.g., 7 bits) of each item in a hash table using **partial-key cuckoo hashing**.

```python
class CuckooFilter:
    def __init__(self, capacity: int, fingerprint_bits: int = 7,
                 bucket_size: int = 4):
        """
        capacity: max number of items
        fingerprint_bits: bits per fingerprint (7-8 bits typical)
        bucket_size: slots per bucket (4 is standard)
        """
        self.bucket_size = bucket_size
        self.fingerprint_bits = fingerprint_bits
        self.fingerprint_mask = (1 << fingerprint_bits) - 1
        
        # Number of buckets = ceil(capacity / bucket_size) * load_factor
        # Cuckoo filters target ~95% load factor
        num_buckets = self._next_pow2(capacity // bucket_size * 2)
        self.buckets = [[] for _ in range(num_buckets)]
        self.size = 0
        self.max_kicks = 500  # threshold for considering table full

    def _fingerprint(self, item: str) -> int:
        hash_val = mmh3.hash64(item, seed=42)[0]
        return hash_val & self.fingerprint_mask

    def _hash(self, item: str) -> int:
        return mmh3.hash64(item, seed=0)[0] % len(self.buckets)

    def _alt_bucket(self, i1: int, fp: int) -> int:
        """Alternative bucket: XOR with hash(fingerprint).
        This allows computing the other bucket without storing the original key.
        """
        return (i1 ^ (mmh3.hash64(bytes([fp]), seed=0)[0] % len(self.buckets))) % len(self.buckets)

    def insert(self, item: str) -> bool:
        fp = self._fingerprint(item)
        i1 = self._hash(item)
        i2 = self._alt_bucket(i1, fp)

        # Try primary bucket first
        if len(self.buckets[i1]) < self.bucket_size:
            self.buckets[i1].append(fp)
            self.size += 1
            return True

        # Try alternate bucket
        if len(self.buckets[i2]) < self.bucket_size:
            self.buckets[i2].append(fp)
            self.size += 1
            return True

        # Cuckoo displacement: kick out existing fingerprint
        cur_bucket = i1 if (hash(item) % 2 == 0) else i2
        for _ in range(self.max_kicks):
            # Pick a random slot in the bucket to evict
            slot = hash(fp) % self.bucket_size
            fp, self.buckets[cur_bucket][slot] = self.buckets[cur_bucket][slot], fp
            cur_bucket = self._alt_bucket(cur_bucket, fp)

            if len(self.buckets[cur_bucket]) < self.bucket_size:
                self.buckets[cur_bucket].append(fp)
                self.size += 1
                return True

        # Table is too full — need to rehash (or grow)
        return False

    def contains(self, item: str) -> bool:
        fp = self._fingerprint(item)
        i1 = self._hash(item)
        i2 = self._alt_bucket(i1, fp)
        return fp in self.buckets[i1] or fp in self.buckets[i2]

    def delete(self, item: str) -> bool:
        fp = self._fingerprint(item)
        i1 = self._hash(item)
        i2 = self._alt_bucket(i1, fp)
        for bucket in (self.buckets[i1], self.buckets[i2]):
            if fp in bucket:
                bucket.remove(fp)
                self.size -= 1
                return True
        return False
```

**The Achilles' Heel — Fingerprint Collisions:**

```python
# Problem: Two different items may have the same 7-bit fingerprint.
# If they hash to the same bucket pair, one insertion can fail.
#
# Probability of fingerprint collision:
#   With 7-bit fingerprints: 1/128 ≈ 0.78% per pair
#   With 10M items: ~39K collisions → could cause insert failures
#
# Mitigation:
#   1. Use adaptive bucket sizes (4 → 8 when collision rate high)
#   2. Use larger fingerprints (8 bits → lower collision, +12.5% memory)
#   3. Use Cuckoo+ variant: fall back to Bloom filter for overflow entries

# The real limitation: Cuckoo filter can fail (insert returns False).
# Bloom filter never fails — it just increases FPR.
# In systems that MUST accept all inserts, this matters.
```

**Bloom vs Cuckoo Comparison:**

| Property | Bloom Filter | Cuckoo Filter |
|----------|-------------|---------------|
| **Lookup** | O(k), k = hash count | O(1) — two buckets × bucket_size |
| **Insert** | O(k) | O(1) amortized, may fail |
| **Delete** | Not supported (Counting BF: O(k), 4× memory) | O(1) native |
| **False positive rate** | ~0.1% at optimal params | ~0.1% at 7-bit fp |
| **Memory** | Lower (1 bit per entry + overhead) | ~1.2× Bloom for same FPR |
| **Load factor** | Always works | ~95% max (cycles at ~98%) |
| **Space** | ~1.44 × log₂(1/p) bits per key | ~(log₂(1/p) + 2) bits per key |

**When would you pick Cuckoo over Bloom?**

- **You need deletion** (Counting BF uses 4× memory for the same FPR)
- **You need fast lookups** (Cuckoo is O(1) average, Bloom is O(k))
- **Your dataset has known cardinality** (Cuckoo benefits from tight sizing)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Fingerprint concept** | Explains partial-key cuckoo hashing — alternative bucket via XOR |
| **Insert failure** | Understands the cycle condition and max-kick threshold |
| **Comparison to Bloom** | Knows exact memory trade-offs (not just "better") |
| **Production** | Mentions adaptive bucket sizing or Cuckoo+ hybrid |

---

## 3. HyperLogLog: Cardinality Estimation

**Q:** "We need to count distinct users visiting our site every hour — 10M DAU, 1B events/hour. Naive exact counting (HashSet) would take 8GB/hour. Design a system that uses < 2KB per time window and gives < 2% error. Walk me through the stochastic averaging math."

**What They're Really Testing:** Whether you understand the algorithm's internal mechanics — not just how to use a library.

### Answer

**The Core Insight:**

HyperLogLog exploits a simple probabilistic fact: if you hash each element uniformly, the probability of seeing a hash value with exactly `ρ` leading zeros is `1/2^ρ`. The maximum number of leading zeros observed across all elements gives a rough estimate of `log₂(n)`.

The problem with a single register is high variance (±1 bit = 2× error). **Stochastic averaging** solves this by splitting into `m = 2^b` registers using the first `b` bits of the hash, then taking the harmonic mean.

```python
class HyperLogLog:
    """
    HLL with bias correction for small and large ranges.
    Memory: m × 6 bits (~12KB for m=16384, which gives ~1% error)
    """
    def __init__(self, b: int = 12):
        # b = number of bits for register selection
        # m = 2^b = number of registers
        self.b = b
        self.m = 1 << b  # e.g., b=12 → 4096 registers → ~1.6% error
        # 5 bits per register (enough to count up to 2^32 distinct items)
        self.registers = [0] * self.m

    def add(self, value: str) -> None:
        # 64-bit hash — use strong hash for uniformity
        x = mmh3.hash64(value, seed=42)[0] & 0xFFFFFFFFFFFFFFFF
        # First b bits: register index
        j = x >> (64 - self.b)
        # Remaining 64-b bits: count leading zeros + 1
        w = x << self.b  # Remove the first b bits
        leading_zeros = w.bit_length() if w > 0 else 0
        rho = 65 - self.b - leading_zeros  # +1 for rank
        self.registers[j] = max(self.registers[j], rho)

    def count(self) -> float:
        # Harmonic mean of 2^{register}
        Z = sum(1.0 / (1 << r) for r in self.registers)

        # Bias correction constant
        alpha = {
            16: 0.673,
            32: 0.697,
            64: 0.709,
        }.get(self.m, 0.7213 / (1 + 1.079 / self.m))

        E = alpha * self.m * self.m / Z

        # === BIAS CORRECTION ===

        # Small range: linear counting (when most registers are empty)
        if E <= 2.5 * self.m:
            V = self.registers.count(0)  # Number of zero registers
            if V > 0:
                E = self.m * math.log(self.m / V)

        # Medium range: use raw HLL estimate
        # (E is already correct for 2.5*m < E <= 2^32)

        # Large range: 64-bit correction
        if E > 1 << 32:  # 2^32
            E = -(1 << 64) * math.log(1 - E / (1 << 64))

        return E

    def merge(self, other: 'HyperLogLog') -> None:
        """Merge another HLL into this one (for distributed counting)."""
        if self.b != other.b:
            raise ValueError("Cannot merge HLLs with different precision")
        for i in range(self.m):
            self.registers[i] = max(self.registers[i], other.registers[i])


# ==============================
# PRODUCTION: HyperLogLog++
# ==============================
#
# Google's HyperLogLog++ (used in BigQuery) adds:
# 1. 64-bit hash (vs original 32-bit) — handles > 4B cardinality
# 2. Sparse representation — when cardinality << m, store (index, value)
#    pairs instead of full register array (saves memory by 10-100×)
# 3. Improved bias correction using empirical curves
#
# Sparse representation:
class SparseHLL(HyperLogLog):
    """When n << m, use a map instead of full register array."""
    def __init__(self, b: int = 12, sparse_threshold: int = None):
        super().__init__(b)
        self._use_sparse = True
        self._sparse_map = {}  # index → max_rho
        self.sparse_threshold = sparse_threshold or (self.m // 4)
        self._sparse_count = 0

    def add(self, value: str):
        if not self._use_sparse:
            return super().add(value)

        x = mmh3.hash64(value, seed=42)[0] & 0xFFFFFFFFFFFFFFFF
        j = x >> (64 - self.b)
        w = x << self.b
        leading_zeros = w.bit_length() if w > 0 else 0
        rho = 65 - self.b - leading_zeros

        # In sparse mode, only store non-zero entries
        prev = self._sparse_map.get(j, 0)
        if rho > prev:
            self._sparse_map[j] = rho
            if prev == 0:
                self._sparse_count += 1

        # Switch to dense mode if too many registers are populated
        if self._sparse_count > self.sparse_threshold:
            self._to_dense()

    def _to_dense(self):
        for idx, rho in self._sparse_map.items():
            self.registers[idx] = rho
        self._use_sparse = False
        self._sparse_map = None
```

**Error Bounds:**

```
Standard error of HLL with m registers:
    σ ≈ 1.04 / √m

    b = 8,  m = 256:   σ ≈ 6.5%   (uses 160 bytes)
    b = 10, m = 1024:  σ ≈ 3.3%   (uses 640 bytes)
    b = 12, m = 4096:  σ ≈ 1.6%   (uses 2.5 KB)
    b = 14, m = 16384: σ ≈ 0.8%   (uses 10 KB)
    b = 16, m = 65536: σ ≈ 0.4%   (uses 40 KB)
```

**Real-World Use:**

| System | What they count | Precision | Memory |
|--------|----------------|-----------|--------|
| Redis | Distinct visitors per page | ~1% | 12KB per key |
| BigQuery | Approximate COUNT(DISTINCT) | ~1% | Configurable |
| Presto | Approximate cardinality | ~2% | Default b=12 |
| Elasticsearch | Cardinality aggregation | ~5% | Configurable |

**Staff-Level Trade-Offs:**
- **HLL vs Bitmap**: For `n < 10M`, a compressed bitmap (RoaringBitmap) is often *better* — exact with ~2 bits per unique
- **HLL vs Bloom**: Bloom can estimate set *size* by using linear counting (counting empty bits), but error is higher than HLL
- **HLL++ sparse mode** is critical for hourly windows where actual cardinality << m

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stochastic averaging** | Explains harmonic mean over registers, not arithmetic |
| **Bias correction** | Knows small-range (linear counting) and large-range (64-bit) corrections |
| **HLL++ enhancements** | Mentions sparse representation and improved bias curves |
| **When not to use** | Knows RoaringBitmap beats HLL for low cardinality |

---

## 4. Count-Min Sketch: Frequency Estimation

**Q:** "Design a system to detect the top-K most frequent search queries in real-time from 100K queries/second. We can tolerate approximate counts but need to guarantee no undercounts. How do you size the sketch? What are the error bounds?"

**What They're Really Testing:** Understanding of the sketch's asymmetric error guarantee — it only overcounts, never undercounts — and how d, w parameters control that.

### Answer

**Count-Min Sketch Properties:**
- **Never underestimates** — the count is always ≥ true count
- **Width** w: controls error magnitude (error ≤ `ε × N` with `ε = e/w`)
- **Depth** d: controls confidence (probability `1 - δ` where `δ = e^{-d}`)

```python
class CountMinSketch:
    """
    Probabilistic frequency table.
    
    Parameters:
        epsilon: error factor (as fraction of total count)
        delta: confidence (probability the error bound holds)
        
    Given epsilon, delta:
        width  = ceil(e / epsilon)
        depth  = ceil(-ln(1 - delta))
    """
    def __init__(self, epsilon: float = 0.001, delta: float = 0.999):
        # e = 2.71828...
        self.width = int(math.ceil(math.e / epsilon))   # e.g., 2718
        self.depth = int(math.ceil(-math.log(1 - delta)))  # e.g., 7
        self.table = [[0] * self.width for _ in range(self.depth)]
        self.total = 0  # Track total count for relative error

    def _hash(self, item: str, row: int) -> int:
        """Row-independent hash."""
        return mmh3.hash64(item, seed=row)[0] % self.width

    def increment(self, item: str, count: int = 1) -> None:
        self.total += count
        for row in range(self.depth):
            col = self._hash(item, row)
            self.table[row][col] += count

    def estimate(self, item: str) -> int:
        """Returns minimum across all rows (guarantees no undercount)."""
        return min(
            self.table[row][self._hash(item, row)]
            for row in range(self.depth)
        )

    def error_bound(self) -> float:
        """ε × N: the maximum likely overcount."""
        return math.e / self.width * self.total
```

**The Heavy Hitters (Top-K) Extension:**

```python
class HeavyHittersTracker:
    """
    Track top-K frequent items using Count-Min Sketch + a min-heap.
    
    The trick: sketch tracks approximate frequency, heap tracks current top-K.
    When a new item comes in, check if its sketch estimate > heap min.
    If so, pop the min and push the new item.
    
    False positives: items may appear in top-K when they shouldn't
    False negatives: NEVER — true top-K items will always have high
                     sketch estimates (no undercount guarantee)
    """
    def __init__(self, k: int, epsilon: float = 0.001, delta: float = 0.999):
        self.k = k
        self.sketch = CountMinSketch(epsilon, delta)
        self.heap = []  # Min-heap of (estimated_count, item)
        self.blacklist = set()

    def add(self, item: str) -> None:
        prev_estimate = self.sketch.estimate(item)
        self.sketch.increment(item)
        new_estimate = self.sketch.estimate(item)

        if item not in self.blacklist:
            if len(self.heap) < self.k:
                heapq.heappush(self.heap, (new_estimate, item))
            else:
                min_est, min_item = self.heap[0]
                if new_estimate > min_est:
                    heapq.heappop(self.heap)
                    heapq.heappush(self.heap, (new_estimate, item))
                    self.blacklist.add(min_item)

    def top_k(self) -> List[Tuple[str, int]]:
        return [(item, -est) for est, item in
                sorted(self.heap, reverse=True)]
```

**Conservative Update — Better Accuracy at No Cost:**

```python
class ConservativeCMS(CountMinSketch):
    """
    Conservative update: only increment cells that contain the *minimum*
    value across the row hashes. This significantly reduces overcounting
    when collisions would otherwise inflate counts.
    
    Trade-off: slightly slower updates (need to read before write),
               but same memory, same error bound.
    """
    def increment(self, item: str, count: int = 1) -> None:
        # First pass: find current minimum
        cols = [self._hash(item, row) for row in range(self.depth)]
        min_val = min(self.table[row][col] for row, col in zip(range(self.depth), cols))

        # Second pass: only increment cells at the minimum
        for row, col in enumerate(cols):
            if self.table[row][col] == min_val:
                self.table[row][col] += count

        self.total += count
```

**Error Analysis:**

```text
Count-Min Sketch guarantees:
    est ≤ true_count + ε × total_count
    with probability ≥ 1 - δ
    
    where ε = e/w, δ = e^{-d}
    
    Example: w=2718, d=7 gives:
        ε = e/2718 ≈ 0.001 (error < 0.1% of total count)
        δ = e^{-7} ≈ 0.0009 (99.91% confidence the bound holds)
    
    For 10M search queries: max error ≈ 10K per item
```

**Count-Min vs Count-Mean-Min:**
- **Count-Min**: Overcounts due to hash collisions (never undercounts)
- **Count-Mean-Min**: Subtracts expected noise (d/width × total), centers estimates at true count — but can now undercount

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Error guarantee** | Explains asymmetry: never undercounts, may overcount |
| **Parameter sizing** | Calculates w, d from ε, δ mathematically |
| **Conservative update** | Mentions the optimization for less overcounting |
| **Heavy hitters** | Describes heap + sketch combo for top-K |

---

## 5. MinHash: Set Similarity

**Q:** "We run a plagiarism detection system with 10M documents. For each new document, we need to find the top-10 most similar documents. Each document contains ~500 unique shingles. A naive pairwise Jaccard calculation is O(N²). Design a system using MinHash. How does the signature size affect accuracy?"

**What They're Really Testing:** Whether you understand the connection between MinHash and Jaccard similarity — and can design the LSH indexing layer for sub-linear retrieval.

### Answer

**The Core Insight:**

MinHash exploits the property that the probability that the minimum hash value of two sets is the same equals their Jaccard similarity:

```python
# For sets A, B:
#   P(min(h(A)) == min(h(B))) = |A ∩ B| / |A ∪ B| = J(A, B)
#
# With k independent hash functions:
#   Signature: [min(h_1(A)), min(h_2(A)), ..., min(h_k(A))]
#   J(A, B) ≈ (matches in signature) / k
```

```python
import numpy as np
from typing import Set, List, Tuple
import mmh3

class MinHasher:
    """
    Generate MinHash signatures for documents.
    
    k = 200 gives standard error ~1/√200 ≈ 7%
    """
    def __init__(self, k: int = 200):
        self.k = k
        # Generate k random hash seeds (reused across all documents)
        self.seeds = [np.random.randint(0, 2**31) for _ in range(k)]

    def signature(self, shingles: Set[str]) -> List[int]:
        """Generate k-length signature."""
        sig = [float('inf')] * self.k
        for shingle in shingles:
            for i, seed in enumerate(self.seeds):
                # MurmurHash is fast and uniform
                h = mmh3.hash64(shingle, seed=seed)[0]
                if h < sig[i]:
                    sig[i] = h
        return sig

    @staticmethod
    def similarity(sig_a: List[int], sig_b: List[int]) -> float:
        """Estimated Jaccard similarity."""
        matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
        return matches / len(sig_a)
```

**LSH for Sub-Linear Retrieval:**

The real power of MinHash is not just computing pairwise similarity — it's **Locality-Sensitive Hashing** (LSH) that finds similar pairs in O(N) instead of O(N²).

```python
class MinHashLSH:
    """
    Banded LSH for MinHash signatures.
    
    Split k-length signature into b bands of r rows each.
    Two items collide in a band if all r hashes match.
    Tune b and r for desired sensitivity.
    
    Probability of collision for Jaccard = J:
        P = 1 - (1 - J^r)^b
    
    For k=200, desired threshold ~0.7:
        b = 50 bands, r = 4 rows/band
        P(0.7) = 1 - (1 - 0.7^4)^50 ≈ 0.94
        P(0.3) = 1 - (1 - 0.3^4)^50 ≈ 0.04
    """
    def __init__(self, k: int = 200, bands: int = 50):
        self.k = k
        self.bands = bands
        self.rows = k // bands  # Should be exact division
        self.hash_tables = [{} for _ in range(bands)]

    def _band_hash(self, signature: List[int], band: int) -> int:
        """Hash a band of the signature into a bucket."""
        start = band * self.rows
        band_sig = signature[start:start + self.rows]
        return hash(tuple(band_sig))

    def insert(self, doc_id: str, signature: List[int]) -> None:
        for band in range(self.bands):
            bucket = self._band_hash(signature, band)
            if bucket not in self.hash_tables[band]:
                self.hash_tables[band][bucket] = []
            self.hash_tables[band][bucket].append(doc_id)

    def candidates(self, signature: List[int]) -> Set[str]:
        """Return candidate similar documents (not deduplicated)."""
        candidates = set()
        for band in range(self.bands):
            bucket = self._band_hash(signature, band)
            if bucket in self.hash_tables[band]:
                candidates.update(self.hash_tables[band][bucket])
        return candidates

    def query(self, doc_id: str, signature: List[int],
              min_similarity: float = 0.7) -> List[Tuple[str, float]]:
        """Find documents similar to the query signature."""
        candidates = self.candidates(signature)
        candidates.discard(doc_id)

        results = []
        for cid in candidates:
            # Retrieve stored signature and compute similarity
            csig = self.stored_signatures.get(cid)
            if csig:
                sim = MinHasher.similarity(signature, csig)
                if sim >= min_similarity:
                    results.append((cid, sim))

        return sorted(results, key=lambda x: -x[1])
```

**How to Tune b and r:**

```
k = 200 (total signature length)

bands=50, rows=4: threshold ≈ (1/50)^{1/4} ≈ 0.37
bands=40, rows=5: threshold ≈ (1/40)^{1/5} ≈ 0.42
bands=25, rows=8: threshold ≈ (1/25)^{1/8} ≈ 0.67
bands=20, rows=10: threshold ≈ (1/20)^{1/10} ≈ 0.74

The probability curve:
    J=0.9: P(collision in any band) ≈ 1.0
    J=0.7: P ≈ 0.94
    J=0.5: P ≈ 0.32
    J=0.3: P ≈ 0.04
    J=0.1: P ≈ 0.0003
```

**Weighted MinHash — Handling Non-Binary Data:**

When sets have weights (e.g., TF-IDF vectors, n-gram frequencies), use **Weighted MinHash** which extends the algorithm to handle integer weights. Used at Google for duplicate detection in Search.

**Real-World Use:**

| System | Application | Signature Size |
|--------|-------------|----------------|
| Google Alog | Near-duplicate web pages | k=84 |
| AltaVista | Duplicate URL detection | k=200 |
| Apache Spark MLlib | Document similarity | Configurable |
| LinkedIn | Job/skill matching | k=100 |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Core probability** | Explains P(min-hash match) = Jaccard |
| **Signature accuracy** | Relates k to standard error (1/√k) |
| **LSH bands** | Tunes b, r for a similarity threshold |
| **Weighted variant** | Mentions Weighted MinHash for non-uniform sets |

---

## 6. Geohash: Spatial Encoding

**Q:** "Design a system to find nearby restaurants within 500m of a user's location. We have 1M restaurants globally. We can't afford to compute Haversine distance on every query. How does Geohash enable efficient proximity search? What's the encoding scheme, and what are its failure modes?"

**What They're Really Testing:** Whether you understand spatial indexing fundamentals — the precision/length trade-off, edge cases at cell boundaries, and when to use Geohash vs alternatives.

### Answer

**Geohash Encoding — Interleaving Bits:**

```python
class Geohash:
    BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    
    @staticmethod
    def encode(lat: float, lng: float, precision: int = 12) -> str:
        """
        Encode (lat, lng) into a base32 Geohash string.
        
        Precision → cell size:
            p=1: ~5000km × 5000km
            p=2: ~1250km × 625km
            p=3: ~156km × 156km
            p=4: ~39km × 19.5km
            p=5: ~4.9km × 4.9km
            p=6: ~1.2km × 0.61km
            p=7: ~152m × 152m   ← Good for "nearby" queries
            p=8: ~38m × 19m
            p=9: ~4.8m × 4.8m
        """
        lat, lng = Geohash._normalize(lat, lng)
        lat_range = [-90.0, 90.0]
        lng_range = [-180.0, 180.0]
        
        bits = []
        for i in range(precision * 5):  # 5 bits per character
            if i % 2 == 0:  # Even bits: longitude
                mid = (lng_range[0] + lng_range[1]) / 2
                if lng >= mid:
                    bits.append('1')
                    lng_range[0] = mid
                else:
                    bits.append('0')
                    lng_range[1] = mid
            else:  # Odd bits: latitude
                mid = (lat_range[0] + lat_range[1]) / 2
                if lat >= mid:
                    bits.append('1')
                    lat_range[0] = mid
                else:
                    bits.append('0')
                    lat_range[1] = mid

        # Group into 5-bit chunks and encode as base32
        result = []
        for i in range(0, len(bits), 5):
            chunk = bits[i:i+5]
            val = int(''.join(chunk), 2)
            result.append(Geohash.BASE32[val])
        return ''.join(result)

    @staticmethod
    def neighbors(geohash: str) -> List[str]:
        """
        Get all 8 neighboring geohash cells.
        CRITICAL for boundary queries — a point at the edge of a cell
        may have nearby points in adjacent cells.
        """
        lat, lng = Geohash.decode(geohash)
        precision = len(geohash)
        neighbors = []
        for dlat in (-1, 0, 1):
            for dlng in (-1, 0, 1):
                if dlat == 0 and dlng == 0:
                    continue
                # Move by one cell in the geohash grid
                nlat = lat + dlat * Geohash._cell_lat(precision)
                nlng = lng + dlng * Geohash._cell_lng(precision)
                if -90 <= nlat <= 90 and -180 <= nlng <= 180:
                    neighbors.append(Geohash.encode(nlat, nlng, precision))
        return neighbors
```

**The Failure Modes:**

```python
# ==============================
# PROBLEM 1: The Edge Case
# ==============================
# User is at a cell boundary. Nearby restaurants are in the NEXT cell.
#
# Example: user at geohash "u4pruydqqvj"
# Restaurant 500m away → geohash "u4pruydqqvk" (different cell!)
# 
# Solution: ALWAYS query the 9-cell grid (cell + 8 neighbors).
# This is non-negotiable for any Geohash-based proximity system.

def nearby_restaurants(user_geohash: str, db_cursor) -> List[Restaurant]:
    cells = [user_geohash] + Geohash.neighbors(user_geohash)
    candidates = db_cursor.execute("""
        SELECT * FROM restaurants 
        WHERE geohash_prefix IN %s
        AND abs(lat - %s) < 0.005
        AND abs(lng - %s) < 0.005
    """, (tuple(cells), user_lat, user_lng))
    
    # Still need Haversine to filter (9 cells is imprecise at edges)
    return [r for r in candidates if haversine(user, r) < 500]

# ==============================
# PROBLEM 2: The Pole Problem
# ==============================
# Near the poles, longitude lines converge. A geohash cell that's
# ~152m wide at the equator narrows to 0 at the poles.
# 
# Consequence: precision 7 gives ~152m × 152m at equator
#              but ~152m × 0.15m at latitude 89°
# 
# Mitigation: Use Geohash only between ±80° latitude.
# Outside that range, fall back to UTM or S2.

# ==============================
# PROBLEM 3: Variable Precision
# ==============================
# Not all characters in the same position encode the same area.
# The first character encodes 5000km × 5000km at equator,
# but only 5000km × 2500km near the pole.
# This makes uniform KNN queries (within 500m regardless of location)
# harder — you need to dynamically choose precision based on latitude.
```

**Geohash for Range Queries — Prefix Property:**

```python
# KEY PROPERTY: Longer hashes are nested inside shorter ones.
# 
# "u4pruydqqvj" starts with "u4pru" → "u4pru" is a LARGER cell
# containing the smaller cell.
#
# This enables:
#   1. Prefix query: WHERE geohash LIKE 'u4pru%' → all items in that region
#   2. Zoom-dependent: shorter prefix = larger area = faster query
#
# For the "find nearby" problem:
#   precision 5 (~4.9km): get all restaurants in ~25km² area
#   precision 7 (~152m): get all restaurants in ~0.023km² area
#
# Start with shorter prefix for a quick broad query,
# then refine with Haversine on the filtered results.

def adaptive_proximity_query(lat: float, lng: float,
                              radius_m: float, db_cursor):
    # Choose precision based on desired radius
    if radius_m > 10000:    # 10km
        precision = 4       # ~39km cells
    elif radius_m > 1000:   # 1km
        precision = 6       # ~1.2km cells
    elif radius_m > 200:    # 200m
        precision = 7       # ~152m cells
    else:
        precision = 8       # ~38m cells

    center = Geohash.encode(lat, lng, precision)
    cells = [center] + Geohash.neighbors(center)
    
    # SQL query with prefix match and Haversine filter
    results = db_cursor.execute("""
        SELECT *, (
            6371 * acos(
                cos(radians(%s)) * cos(radians(lat)) *
                cos(radians(lng) - radians(%s)) +
                sin(radians(%s)) * sin(radians(lat))
            )
        ) AS distance
        FROM restaurants
        WHERE geohash_prefix IN %s
        HAVING distance < %s
        ORDER BY distance
        LIMIT 50
    """, (lat, lng, lat, tuple(cells), radius_m / 1000))
    
    return results
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Encoding** | Explains bit-interleaving of lat/lng → base32 |
| **Edge cells** | Mandatory 9-cell neighbor query |
| **Pole distortion** | Knows Geohash breaks at high latitudes |
| **Precision trade-off** | Chooses precision based on query radius |

---

## 7. S2 Geometry: Hierarchical Spatial Indexing

**Q:** "Uber needs to match riders with drivers within 500ms globally. Geohash has edge cases at cell boundaries and poles. Design a better spatial indexing system. How does Google's S2 geometry solve these problems? Walk me through the projection from the sphere to a Hilbert curve."

**What They're Really Testing:** Whether you understand the fundamental problems with lat/lng indexing on a sphere and how S2's design choices (cube projection + space-filling curve) fix them.

### Answer

**S2's Three-Step Pipeline:**

```python
# S2 converts lat/lng → cell ID via three transforms:
#
# Step 1: lat/lng → unit vector (x, y, z) on the sphere
# Step 2: unit vector → face + (u, v) on cube face
# Step 3: (u, v) → (i, j) → cell ID on Hilbert curve
#
# Result: a 64-bit cell ID that preserves spatial proximity.

import math

class S2CellId:
    """
    64-bit cell identifier.
    
    Bit layout:
    [0..2]: face (0-5, 3 bits)
    [3..60]: position on Hilbert curve (58 bits)
    [61..63]: level (0-30, 4 bits encoded in trailing bits + lsb)
    
    Maximum level 30 gives cells ~1cm² at the equator.
    """

    FACE_SHIFT = 61  # Face occupies top 3 bits
    MAX_LEVEL = 30
    POS_BITS = 2 * MAX_LEVEL + 1  # 61 bits for position

    def __init__(self, cell_id: int):
        self.id = cell_id

    @staticmethod
    def from_lat_lng(lat_deg: float, lng_deg: float, level: int) -> 'S2CellId':
        lat = math.radians(lat_deg)
        lng = math.radians(lng_deg)

        # Step 1: lat/lng → unit vector on sphere
        x = math.cos(lat) * math.cos(lng)
        y = math.cos(lat) * math.sin(lng)  
        z = math.sin(lat)

        # Step 2: unit vector → cube face + (u, v)
        face, u, v = S2CellId._xyz_to_face_uv(x, y, z)

        # Step 3: (u, v) → (s, t) via quadratic transform → (i, j) → cell ID
        cell_id = S2CellId._face_uv_to_cell_id(face, u, v, level)
        return S2CellId(cell_id)

    @staticmethod
    def _xyz_to_face_uv(x: float, y: float, z: float) -> tuple:
        # Find the dominant axis (face)
        abs_x, abs_y, abs_z = abs(x), abs(y), abs(z)
        
        if abs_x >= abs_y and abs_x >= abs_z:
            face = 0 if x > 0 else 3
            u = y / x if x > 0 else y / x  # same but sign
            v = z / x if x > 0 else z / x
        elif abs_y >= abs_z:
            face = 1 if y > 0 else 4
            u = x / y if y > 0 else x / y
            v = z / y if y > 0 else z / y
        else:
            face = 2 if z > 0 else 5
            u = x / z if z > 0 else x / z
            v = y / z if z > 0 else y / z

        # u, v are in [-1, 1] on the cube face
        return face, u, v
```

**Why Quadratic Transform (Not Linear)?**

```python
# S2 uses a quadratic projection (not linear) from cube face → grid:
#
# Linear:   s = 0.5 * (u + 1)  -- uniform sampling, waste at edges
# Tangent:  s = ...             -- non-uniform, expensive
# Quadratic: s = 0.5 * (sign(u) * (sqrt(1 + 3*u²) - 1) + 1)
#
# The quadratic transform is chosen because:
# 1. It's cheap to compute (one sqrt)
# 2. It makes cells more uniform in area (within 2× of each other)
# 3. At the equator (most used), cells are ~square

def _quadratic_transform(u: float) -> float:
    """Maps [-1, 1] to [0, 1] with area-preserving properties."""
    if u >= 0:
        return 0.5 * (math.sqrt(1 + 3 * u) - 1)
    else:
        return 0.5 * (1 - math.sqrt(1 - 3 * u))

# Without this transform, cells near cube face corners would be
# ~5.7× more area than cells at face centers.
# With quadratic transform: max area ratio ≈ 2.0 (much better).
```

**Hilbert Curve — The Key to Locality:**

```python
# S2 encodes (face, level, i, j) → 64-bit cell ID using a
# Hilbert space-filling curve.
# 
# Why Hilbert and not Z-order (Morton)?
#   Z-order:   Leaps between quadrants, poor locality
#   Hilbert:   Max 2 steps between adjacent cells (optimal)
#              Preserves 2D adjacency in 1D ordering
#
# Property: if two points are close in 2D space,
# they are close on the Hilbert curve.
#
# This means: cell IDs that are numerically close
# correspond to spatially close regions.
# 
# Consequence: B-tree indexing on cell ID naturally
# groups spatial neighbors!

# Cell level → approximate size:
level_7  = 2 * (7 * 2 + 1)  # ~15 bits → ~1km
level_15 = 2 * (15 * 2 + 1)  # ~31 bits → ~2m
level_30 = 2 * (30 * 2 + 1)  # ~61 bits → ~1cm
```

**S2 vs Geohash — The Decisive Comparison:**

| Property | Geohash | S2 |
|----------|---------|----|
| **Projection** | Flat lat/lng grid | Cube + quadratic transform |
| **Cell shape** | Rectangular (distorted at poles) | Nearly uniform globally |
| **Locality** | Prefix-based (OK) | Hilbert curve (excellent) |
| **Covering** | Rectangles only | Arbitrary polygons via S2RegionCoverer |
| **Levels** | 12 (by string length) | 31 (0-30, by bit position) |
| **Cell ID** | Variable-length string | 64-bit integer |
| **Worst case** | Poles break | ~2× area variance globally |
| **Ecosystem** | Simple, widely supported | Richer (polygon cover, KNN, S2LatLngRect) |

**S2RegionCoverer — The Killer Feature:**

```python
# S2's most powerful feature: approximate ANY region as a
# union of cell IDs at multiple levels.
#
# Given a polygon (e.g., delivery zone for a restaurant):
# 1. Start with largest cells fully inside the polygon
# 2. Recursively split cells that cross the boundary
# 3. Cap at max_cells (e.g., 20 cells)
# 4. Result: ~20 cells covering the polygon with O(1) lookup

def cover_polygon(polygon_coords, max_cells=20):
    """
    Returns a set of S2 cell IDs covering the polygon.
    
    Query: "Find all restaurants in this delivery zone"
    
    SELECT * FROM restaurants
    WHERE s2_cell_id IN <covering_set>
    
    Instead of expensive polygon intersection,
    we get O(1) equality/in-list lookup.
    
    Typical result: a 5km² zone → 10-50 cells at level 13-15
    """
    # (Python bindings via s2sphere or s2)
    region = S2Polygon(polygon_coords)
    coverer = S2RegionCoverer()
    coverer.set_max_cells(max_cells)
    coverer.set_min_level(12)  # ~3km
    coverer.set_max_level(15)  # ~1km
    covering = coverer.get_covering(region)
    return [cell.id() for cell in covering]
```

**Real-World Use:**

| System | Application |
|--------|-------------|
| Google Maps | All spatial indexing |
| Uber | H3 (predecessor was S2-like) |
| Foursquare | Venue search |
| MongoDB | 2dsphere index (uses S2) |
| BigQuery | GEOGRAPHY type (S2-based) |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Three transforms** | Explains sphere → cube → Hilbert pipeline |
| **Quadratic justification** | Knows why linear fails (area distortion) |
| **Hilbert vs Z-order** | Argues Hilbert's better locality for B-tree |
| **RegionCoverer** | Describes multi-level covering for arbitrary polygons |

---

## 8. H3: Hexagonal Grid System

**Q:** "Uber wants to price surge areas dynamically in real-time. Geohash and S2 use square/rectangular cells — but squares have unequal distances to neighbors (4 edge-neighbors at distance d, 4 corner-neighbors at distance d√2). Design a hexagonal grid system that solves this. Why did Uber build H3 instead of using S2?"

**What They're Really Testing:** Whether you understand the constraints of using square grids for spatial problems that need uniform distance metrics — and the unique design of the hexagon-based H3 system.

### Answer

**Why Hexagons?**

```python
# Square grid neighbor distances:
#    2 3 4
#    1 C 5   (C = center cell)
#    8 7 6
#
# Distance to cells 3, 4, 5, 7: d
# Distance to cells 2, 1, 8, 6: d * √2
#
# This inconsistency causes problems for:
# - Surge pricing (which 8 cells should be included?)
# - Pathfinding (A* with weights depends on direction)
# - Distance queries (KNN with cell expansion is asymmetric)
#
# Hexagonal grid neighbor distances:
#   2   3
# 1   C   4
#   6   5
#
# ALL 6 neighbors are equidistant → perfect for k-ring queries
```

**H3's Hierarchical Structure:**

```python
# H3 uses a planar projection (not cube like S2, not flat like Geohash):
#   1. lat/lng → vertices of an icosahedron (20 triangular faces)
#   2. Each triangle is subdivided into hexagons
#   3. Resolution 0-15 (16 levels)
#   4. Pentagon cells at exactly 12 icosahedron vertices
#
# Resolution → average cell area:
#   res 0:  4,250,000 km²  (macro region)
#   res 5:     253 km²     (city)
#   res 8:       0.74 km²  (neighborhood)
#   res 10:      0.015 km²  (block)
#   res 12:      0.0003 km² (street)
#   res 15:      0.0000009 km² (building)
```

**H3's Key Operations:**

```python
from h3 import h3  # pip install h3

# ==============================
# 1. k-Ring: All cells within k steps
# ==============================
# For surge pricing, we want all hexagons within 3 steps of center:
center = h3.geo_to_h3(37.7749, -122.4194, resolution=9)
surge_zone = h3.k_ring(center, k=3)
# Returns exactly 1 + 6*3 = 37 cells (if no pentagons)
# Every cell is exactly distance k from center → fair pricing

# ==============================
# 2. k-Ring Distances: concentric rings
# ==============================
rings = h3.k_ring_distances(center, k=3)
# rings[0] = [center] (1 cell)
# rings[1] = ring 1 (6 cells)
# rings[2] = ring 2 (12 cells)
# rings[3] = ring 3 (18 cells)
# Total: 1 + 6 + 12 + 18 = 37 cells
# 
# For tiered surge pricing:
#   ring 1: 1.5× multiplier
#   ring 2: 1.2× multiplier
#   ring 3: 1.0× multiplier

# ==============================
# 3. Polyfill: Convert region → hex set
# ==============================
# Given a delivery zone polygon, get all hexagons that cover it:
polygon = [
    [37.7749, -122.4194],
    [37.7849, -122.4194],
    [37.7849, -122.4094],
    [37.7749, -122.4094],
]
hexagons = h3.polyfill(polygon, res=9)
# Returns set of hex IDs → O(1) lookup table for "is this in zone?"

# ==============================
# 4. Compact: Reduce resolution for storage
# ==============================
# Store a zone as the MINIMAL set of parent cells:
compact = h3.compact(hexagons)
# e.g., 50 children at res 9 → 5 parents at res 7
# Reduces storage by 10× while preserving spatial coverage

# ==============================
# 5. H3 Distance: Uniform metric
# ==============================
a = h3.geo_to_h3(37.7749, -122.4194, 9)
b = h3.geo_to_h3(37.7849, -122.4094, 9)
steps = h3.h3_distance(a, b)
# Distance in hex steps (not meters, not degrees)
# Multiply by avg hex radius at this resolution for meters
```

**The Pentagon Problem:**

```python
# H3's "Achilles' Heel": each icosahedron face is triangular,
# and hexagons don't tile a triangle perfectly.
# → Exactly 12 pentagons at the icosahedron vertices.
#
# Pentagon has 5 neighbors (not 6), breaking the uniform property.
#
# Mitigation:
# 1. PENTAGONS are placed over oceans (H3 team chose icosahedron
#    orientation to land on water at 12 specific points)
# 2. k_ring on pentagon = 1 + 5×k cells instead of 1 + 6×k
# 3. In practice, it rarely matters (99.99% of queries don't
#    involve pentagons)
#
# Check for pentagon:
def is_pentagon(cell: str) -> bool:
    return h3.h3_is_pentagon(cell)

# If you need to avoid pentagons:
def safe_k_ring(center: str, k: int) -> set:
    result = h3.k_ring(center, k)
    pentagons = {c for c in result if h3.h3_is_pentagon(c)}
    if pentagons:
        # Handle pentagon case: use parent resolution or custom logic
        pass
    return result
```

**H3 vs S2 — When to Use Which:**

| Criterion | H3 | S2 |
|-----------|----|----|
| **Neighbor uniformity** | ✅ All neighbors equidistant | ❌ Edge vs corner neighbors |
| **k-ring** | ✅ O(k), exact k-ring | ❌ Approximate expansion |
| **Polygon covering** | ✅ polyfill | ✅ RegionCoverer |
| **Pathfinding** | ✅ Hex grids = natural | ❌ Square grids need weights |
| **Distortion** | ❌ 12 pentagons | ❌ ~2× area variance |
| **Precision** | 16 levels | 31 levels |
| **Maturity** | Uber standard | Google standard |
| **Use case** | Movement/geofencing | General spatial (maps, storage) |

**Real-World Use:**

| System | Application |
|--------|-------------|
| Uber | Surge pricing, ETA, geofencing |
| Snapchat | Geofilters (polygon → hex set) |
| Foursquare | Venue clustering |
| Descartes Labs | Satellite image tiling |
| Tesla | Navigation routing |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Hex uniformity** | Explains 6 equidistant neighbors vs 4+4 in squares |
| **Icosahedron projection** | Knows the 12 pentagon artifact |
| **k-ring for surge** | Uses k_ring_distances for tiered pricing |
| **H3 vs S2** | Gives principled trade-off (movement vs storage) |

---

## 9. Quad Tree: 2D Spatial Partitioning

**Q:** "Design a real-time collision detection system for a multiplayer game with 10K entities moving simultaneously on a 2D map. Brute-force pairwise comparison is O(N²) = 100M checks per frame. Design a spatial partitioning structure. How does a Quad Tree compare to a uniform grid? Walk me through insertion, query, and rebalancing."

**What They're Really Testing:** Whether you can reason about the adaptability of Quad Trees vs fixed-grid approaches for non-uniform distributions.

### Answer

**Core Concept:**

```python
class QuadTreeNode:
    """
    Each node represents a rectangular region.
    If the region contains more than capacity items,
    split into 4 children: NW, NE, SW, SE.
    """
    def __init__(self, x: float, y: float, w: float, h: float,
                 capacity: int = 4, max_depth: int = 10):
        self.bounds = (x, y, w, h)  # (center_x, center_y, width, height)
        self.capacity = capacity
        self.max_depth = max_depth
        self.items = []      # Points in this node
        self.children = None  # None until first split
        self.depth = 0

    def insert(self, point: tuple) -> bool:
        """Insert a (x, y) point. Returns True if inserted in this subtree."""
        if not self._contains(point):
            return False
        if len(self.items) < self.capacity or self.depth >= self.max_depth:
            self.items.append(point)
            return True
        if self.children is None:
            self._split()
        for child in self.children:
            if child.insert(point):
                return True
        return False

    def _split(self):
        x, y, w, h = self.bounds
        hw, hh = w / 2, h / 2
        self.children = [
            QuadTreeNode(x - hw/2, y + hh/2, hw, hh, self.capacity, self.max_depth),  # NW
            QuadTreeNode(x + hw/2, y + hh/2, hw, hh, self.capacity, self.max_depth),  # NE
            QuadTreeNode(x + hw/2, y - hh/2, hw, hh, self.capacity, self.max_depth),  # SE
            QuadTreeNode(x - hw/2, y - hh/2, hw, hh, self.capacity, self.max_depth),  # SW
        ]
        for child in self.children:
            child.depth = self.depth + 1
        # Redistribute items to children
        items, self.items = self.items, []
        for point in items:
            for child in self.children:
                if child.insert(point):
                    break
```

**Collision Detection — Range Query:**

```python
class QuadTree:
    def __init__(self, width: float, height: float,
                 capacity: int = 4, max_depth: int = 12):
        self.root = QuadTreeNode(width/2, height/2, width, height,
                                  capacity, max_depth)
        self.all_items = {}  # id → position for fast lookup

    def update(self, entity_id: int, new_pos: tuple):
        """Move entity to new position (reinsert)."""
        self.remove(entity_id)
        self.insert(entity_id, new_pos)

    def insert(self, entity_id: int, pos: tuple):
        self.root.insert(pos)
        self.all_items[entity_id] = pos

    def query_range(self, x: float, y: float,
                    radius: float) -> List[tuple]:
        """Find all points within radius of (x, y)."""
        return self._query_range(self.root, x, y, radius, [])

    def _query_range(self, node, x, y, radius, results):
        if not self._rect_intersects_circle(node.bounds, x, y, radius):
            return results
        for px, py in node.items:
            if ((px - x) ** 2 + (py - y) ** 2) <= radius ** 2:
                results.append((px, py))
        if node.children:
            for child in node.children:
                self._query_range(child, x, y, radius, results)
        return results
```

**Quad Tree vs Uniform Grid — The Trade-Off:**

```python
# ==============================
# UNIFORM GRID: Fixed cell size
# ==============================
#
#   Game map divided into 100×100 cells (10K cells total).
#   Each cell stores entities within its bounds.
#
#   Query: "find entities near (x, y)" = check 9 cells (center + neighbors)
#   Each cell: entities = hashmap lookup → O(1)
#
#   Problem: Players cluster in one area → 1000 entities in one cell
#   → neighbor check still tests 1000 entities → O(N) again
#
#   Solution: Adapt cell size to entity density → QUAD TREE

# ==============================
# QUAD TREE: Adaptive partitioning
# ==============================
#
#   Sparse areas: large cells (few subdivisions)
#   Dense areas: small cells (deep subdivisions)
#
#   Worst-case query: O(log N + k) where k = results
#   Adapts automatically to any distribution
#
#   Problem: Rebalancing cost
#   If entities shift (e.g., all players move from left to right),
#   the tree structure becomes unbalanced.
#
#   Solution: Rebuild every ~60 frames (for games) or
#   use a lazy deletion approach.

# ==============================
# HYBRID: Grid-of-QuadTrees
# ==============================
#
#   Partition world into coarse grid (e.g., 8×8 sectors).
#   Each sector has its own Quad Tree.
#   Sector selection: O(1), Quad Tree query: O(log N)
#   Best of both worlds for large maps.
```

**Lazy Deletion + Bulk Rebuild:**

```python
class LazyQuadTree(QuadTree):
    """
    Instead of removing/reinserting every frame, mark items as stale
    and rebuild the entire tree periodically.
    
    For 10K entities: full rebuild = O(N log N) ≈ 10K × ~14 = 140K ops
    At 60 FPS: that's 8.4M ops/sec — trivial for modern CPUs.
    
    Strategy:
    - Every frame: insert current positions with timestamps
    - Every 60 frames: rebuild from scratch
    - Queries: check both the stale tree and the new positions
    """
    def __init__(self, ...):
        super().__init__(...)
        self.frame_count = 0
        self.rebuild_interval = 60
        self.entity_positions = {}  # Current ground truth

    def update(self, entity_id: int, pos: tuple):
        self.entity_positions[entity_id] = pos

    def rebuild(self):
        self.root = QuadTreeNode(...)
        for eid, pos in self.entity_positions.items():
            self.root.insert(pos)

    def on_frame_end(self):
        self.frame_count += 1
        if self.frame_count % self.rebuild_interval == 0:
            self.rebuild()
```

**Production Lessons:**

```
War Story: "Quad Tree vs R-Tree for Game Server"
- Client: MMORPG with 50K NPCs on a 100km² map
- Quad Tree depth: max 12 (2^12 ≈ 4096 cells — too coarse for dense zones)
- Fix: dynamic capacity based on density (not fixed 4)
- Result: O(log N) queries, 2ms per frame for collision detection
- Lesson: Use capacity = 8-16 for game servers (fewer splits, faster queries)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Adaptive partitioning** | Explains why fixed grids fail under non-uniform distribution |
| **Range query** | Implements recursive query with bounds checking |
| **Rebalancing** | Proposes lazy deletion + periodic rebuild for moving entities |
| **Hybrid** | Suggests grid-of-QuadTrees for very large worlds |

---

## 10. R-Tree: Bounding Box Index

**Q:** "Design a map-based ride-sharing app that needs to find all available drivers within a user's visible map viewport (a rectangular area on screen). The world has 1M drivers. How does an R-Tree organize bounding boxes to enable fast rectangular range queries? What makes it different from a Quad Tree?"

**What They're Really Testing:** Understanding of R-Trees as dynamic, balanced spatial structures optimized for rectangle (not point) storage — and the trade-off between area overlap and query speed.

### Answer

**R-Tree — The Spatial B-Tree:**

```python
class RTreeNode:
    """
    An R-Tree node stores a bounding box + either:
    - Child pointers (if internal node)
    - Data entries (if leaf node)
    
    Key invariants:
    - Root has ≥ 2 children (unless leaf)
    - Internal nodes have M/2 to M children
    - Leaf entries are (MBR, object_id)
    - All leaves at same depth
    
    M = max entries per node (typically 4-20)
    m = M/2 = min entries per node
    """
    def __init__(self, is_leaf: bool = True):
        self.is_leaf = is_leaf
        self.mbr = None  # (min_x, min_y, max_x, max_y)
        self.entries = []  # [(mbr, pointer_or_id), ...]
    
    def update_mbr(self):
        if not self.entries:
            self.mbr = None
            return
        min_x = min(e[0][0] for e in self.entries)
        min_y = min(e[0][1] for e in self.entries)
        max_x = max(e[0][2] for e in self.entries)
        max_y = max(e[0][3] for e in self.entries)
        self.mbr = (min_x, min_y, max_x, max_y)
```

**R-Tree Operations:**

```python
class RTree:
    """
    R-Tree implementation using the R*-Tree heuristics
    (improved split policy, forced reinsert).
    """
    def __init__(self, max_entries: int = 8):
        self.M = max_entries
        self.m = max_entries // 2
        self.root = RTreeNode(is_leaf=True)

    def insert(self, mbr: tuple, obj_id: str):
        """Insert a bounding box (min_x, min_y, max_x, max_y)."""
        leaf = self._choose_leaf(self.root, mbr)
        leaf.entries.append((mbr, obj_id))
        leaf.update_mbr()
        if len(leaf.entries) > self.M:
            self._split_node(leaf)

    def _choose_leaf(self, node: RTreeNode, mbr: tuple) -> RTreeNode:
        """Choose leaf by least area enlargement."""
        if node.is_leaf:
            return node
        # Select child with minimum area enlargement
        best = None
        best_enlargement = float('inf')
        for child_mbr, child_ptr in node.entries:
            current_area = self._area(child_mbr)
            enlarged = self._area(self._union(child_mbr, mbr))
            enlargement = enlarged - current_area
            if enlargement < best_enlargement:
                best_enlargement = enlargement
                best = child_ptr
        return self._choose_leaf(best, mbr)

    def search(self, query_mbr: tuple) -> List[str]:
        """Find all objects whose MBR overlaps query_mbr."""
        return self._search(self.root, query_mbr, [])

    def _search(self, node: RTreeNode, query: tuple, results: List[str]):
        if not self._overlaps(node.mbr, query):
            return results
        if node.is_leaf:
            for mbr, obj_id in node.entries:
                if self._overlaps(mbr, query):
                    results.append(obj_id)
        else:
            for child_mbr, child_ptr in node.entries:
                self._search(child_ptr, query, results)
        return results
```

**The R*-Tree Improvements — Why the Vanilla R-Tree Sucks:**

```python
# Vanilla R-Tree problem: poor split strategy leads to
# overlapping MBRs, which means both branches must be searched.
#
# Worst case: 90% overlap → query touches 90% of nodes
# (same as linear scan!)
#
# R*-Tree (Beckmann et al., 1990) fixes this with:

# 1. BETTER SPLIT: Minimize overlap, not area
#    Vanilla: quadratic split (O(M²)) chooses pair with least waste
#    R*: choose split that minimizes OVERLAP between the two new nodes
#
# 2. FORCED REINSERT (the key insight):
#    When a node overflows:
#    a. Remove 30% of entries (those with centroids farthest from center)
#    b. Reinsert them into the tree
#    c. This often finds better placement and reduces overlap
#
# 3. TOP-DOWN BULK LOADING:
#    When you know all entries upfront, use Sort-Tile-Recursive (STR):
#    a. Sort by x, partition into √N slices
#    b. Sort each slice by y, pack into nodes
#    c. Result: no overlap, 100% fill rate

def str_bulk_load(entries: List[tuple], M: int = 8):
    """
    Sort-Tile-Recursive bulk loading for R-Trees.
    Produces a perfectly packed, non-overlapping R-Tree.
    
    Entries: [(mbr, obj_id), ...]
    M: max entries per node
    """
    # Step 1: Sort by x-center, partition into slices
    entries.sort(key=lambda e: (e[0][0] + e[0][2]) / 2)
    num_slices = int(math.ceil(math.sqrt(len(entries) / M)))
    slice_size = len(entries) // num_slices
    slices = [entries[i:i + slice_size] for i in
              range(0, len(entries), slice_size)]
    
    # Step 2: Sort each slice by y-center, pack into nodes
    nodes = []
    for slice_entries in slices:
        slice_entries.sort(key=lambda e: (e[0][1] + e[0][3]) / 2)
        for i in range(0, len(slice_entries), M):
            node_entries = slice_entries[i:i + M]
            node = RTreeNode(is_leaf=True)
            node.entries = node_entries
            node.update_mbr()
            nodes.append(node)
    
    # Step 3: Recursively build internal nodes
    while len(nodes) > 1:
        nodes = str_bulk_load([(n.mbr, n) for n in nodes], M)
    
    tree = RTree(max_entries=M)
    tree.root = nodes[0]
    return tree
```

**R-Tree vs Quad Tree vs B-Tree with Geohash:**

```python
"""
Query: "Find all restaurants in this viewport rectangle"

                         R-Tree          Quad Tree       Geohash (B-tree)
                         ------          ---------       ---------------
Tree depth               log_M(N)        log_4(N)        B-tree height
Balance                  Always          Depends on data Always balanced
Update (single insert)   O(log_M N)      O(log N)        O(log_B N)
Range query efficiency   Excellent       Good            Moderate
Overlap management       R* heuristics   Adaptive split  9-cell query
Dynamic                  ✅              ✅              ✅
Bulk load optimal        ✅ (STR)        ❌              ✅
Overlap in queries       Can degrade     No overlap      Prefix match floods

For 1M drivers, viewport query:
  R-Tree: ~30 node visits (depth 4-5, M=20)
  Quad Tree: ~40 node visits (depth log_4(1M) ≈ 10, ×4 checks)
  Geohash B-tree: ~100 key lookups (9 cells × 10-15 keys each)
  
Winner: R-Tree, especially for rectangle queries.
But: Quad Tree wins for POINT queries (nearest neighbor).
"""
```

**Real-World Use:**

| System | What it indexes | Variant |
|--------|----------------|---------|
| PostgreSQL GiST | All spatial data | R-Tree over GiST framework |
| SQLite R*Tree | Geolocation | R*-Tree |
| Oracle Spatial | Geographic data | R-Tree |
| Elasticsearch | geoshape queries | Quadtree (recursive) |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **MBR overlap problem** | Explains why overlapping MBRs cause query degradation |
| **R*-Tree heuristics** | Mentions forced reinsert + overlap-minimized split |
| **Bulk loading** | Knows STR packing for read-optimized trees |
| **vs Quad Tree** | Gives principled comparison for rectangle vs point queries |

---

## 11. Skip List: Probabilistic Ordered Structure

**Q:** "Design a real-time leaderboard for a multiplayer game with 10M players. Scores update frequently (100K/sec). We need O(log N) insert, update, delete, and range queries (e.g., 'top 100 players around rank 5000'). A balanced BST works but rebalancing is complex. Design a simpler alternative. How does the Skip List achieve O(log N) with pure probability?"

**What They're Really Testing:** Whether you understand that the Skip List's probabilistic balancing is a simpler alternative to the deterministic balancing of red-black or AVL trees — and how it handles concurrent access.

### Answer

**The Core Insight:**

A Skip List is a **layered linked list** where each level is a "highway" skipping over elements at the level below.

```python
import random

class SkipListNode:
    def __init__(self, score: float, value: str, level: int):
        self.score = score
        self.value = value
        self.forward = [None] * (level + 1)  # Pointers to next nodes at each level

class SkipList:
    """
    Probabilistic balanced ordered structure.
    
    Height: levels 0 to MAX_LEVEL.
    Level i has approximately N/2^i nodes.
    Expected search: O(log N).
    
    Memory overhead: N × (p + 1)/(p - 1) pointers per node
                     ≈ 2N pointers for p = 0.5
                     vs 3N for red-black tree (left + right + parent)
    """
    def __init__(self, max_level: int = 16, p: float = 0.5):
        self.MAX_LEVEL = max_level
        self.p = p  # Probability of promoting to next level
        self.header = SkipListNode(float('-inf'), '', max_level)
        self.level = 0  # Current max level
        self.size = 0

    def random_level(self) -> int:
        """Geometric distribution: P(L=k) = (1-p) * p^{k-1}."""
        level = 0
        while random.random() < self.p and level < self.MAX_LEVEL:
            level += 1
        return level

    def insert(self, score: float, value: str) -> None:
        """Insert or update a node with given score."""
        update = [None] * (self.MAX_LEVEL + 1)
        current = self.header

        # Traverse from top level down, tracking nodes to update
        for i in range(self.level, -1, -1):
            while (current.forward[i] and
                   current.forward[i].score < score):
                current = current.forward[i]
            update[i] = current

        # If score already exists, override value
        current = current.forward[0]
        if current and current.score == score:
            current.value = value
            return

        # Create new node with random level
        new_level = self.random_level()
        if new_level > self.level:
            for i in range(self.level + 1, new_level + 1):
                update[i] = self.header
            self.level = new_level

        new_node = SkipListNode(score, value, new_level)
        for i in range(new_level + 1):
            new_node.forward[i] = update[i].forward[i]
            update[i].forward[i] = new_node

        self.size += 1

    def delete(self, score: float) -> bool:
        """Delete node with given score. Returns True if found."""
        update = [None] * (self.MAX_LEVEL + 1)
        current = self.header

        for i in range(self.level, -1, -1):
            while (current.forward[i] and
                   current.forward[i].score < score):
                current = current.forward[i]
            update[i] = current

        current = current.forward[0]
        if not current or current.score != score:
            return False

        for i in range(current.forward.count(None), len(current.forward)):
            update[i].forward[i] = current.forward[i]

        # Shrink level if top level is now empty
        while self.level > 0 and self.header.forward[self.level] is None:
            self.level -= 1

        self.size -= 1
        return True

    def find_by_rank(self, rank: int) -> tuple:
        """Find the node at given rank (1-indexed). O(log N)."""
        current = self.header
        skipped = 0
        if rank > self.size:
            return None
        # Use the topmost level to skip large ranges
        for i in range(self.level, -1, -1):
            while (current.forward[i] and
                   skipped + self._span(current.forward[i], i) <= rank):
                skipped += self._span(current.forward[i], i)
                current = current.forward[i]
        return (current.score, current.value)

    def _span(self, node, level) -> int:
        """Number of bottom-level nodes skipped by this pointer."""
        # Simplified: could store span in each pointer for O(1)
        # Or use count-based skip list variant
        pass
```

**Range Query — Leaderboard Use Case:**

```python
class Leaderboard:
    """
    Real-time game leaderboard using Skip List.
    
    Operations:
    - update_score(player_id, delta): update by delta → O(log N)
    - get_rank(player_id): current rank → O(log N)  
    - get_top_k(k): top players → O(k + log N)
    - get_around(rank, window): players ±window → O(log N + window)
    """
    def __init__(self):
        self.scores = SkipList()
        self.player_scores = {}  # player_id → score (for rank lookup)

    def update_score(self, player_id: str, delta: float) -> float:
        old_score = self.player_scores.get(player_id, 0)
        new_score = old_score + delta
        
        if old_score > 0:
            self.scores.delete(old_score)
        self.scores.insert(new_score, player_id)
        self.player_scores[player_id] = new_score
        return new_score

    def get_rank(self, player_id: str) -> int:
        score = self.player_scores.get(player_id)
        if score is None:
            return -1
        # Count players with score > this score
        # (Skip List can augment to track ranks via span counters)
        return self.scores.count_greater_than(score) + 1

    def get_top_k(self, k: int) -> List[tuple]:
        """Return top k players by score."""
        results = []
        current = self.scores.header.forward[0]
        while current and len(results) < k:
            results.append((current.value, current.score))
            current = current.forward[0]
        return results

    def get_around(self, player_id: str, window: int) -> List[tuple]:
        """Return players around this player's rank."""
        score = self.player_scores.get(player_id)
        if score is None:
            return []
        rank = self.scores.count_greater_than(score) + 1
        start_rank = max(1, rank - window)
        end_rank = min(self.scores.size, rank + window)
        
        results = []
        current = self.scores.find_by_rank(start_rank)
        for _ in range(end_rank - start_rank + 1):
            results.append((current.value, current.score))
            current = current.forward[0]
        return results
```

**Skip List vs Balanced BST — The Real Difference:**

```python
"""
                    Skip List               Red-Black Tree / AVL
                    ---------               --------------------
Balance method      Probabilistic (coin     Deterministic (rotations)
                    flip)
Insert/Delete       O(log N) expected       O(log N) worst-case
                    O(N) worst-case (!)     
Search              O(log N) expected       O(log N) worst-case
                    O(N) worst-case
Concurrent ops      SIMPLE: fine-grained    HARD: need global lock
                    locking per level       or complex hand-over-hand
Memory              ~2N pointers            ~3N pointers + color bits
Range query         O(k + log N)            O(k + log N)
                   (just traverse level 0)  (in-order traversal)
Implementation     ~100 lines               ~300 lines (RB), 
                                              ~200 lines (AVL)
Cache performance   Poor (linked list)      Better (array-backed)

Key takeaway:
  Skip Lists win on: concurrent access, simplicity, range queries
  BSTs win on: worst-case guarantees, cache locality, determinism

Redis uses Skip Lists for sorted sets (leaderboards)
  Why? Because concurrent access is simpler and range queries
  (ZRANGE, ZRANK) are natural on level-0 traversal.
"""
```

**Concurrent Skip List — The Real Advantage:**

```python
import threading

class ConcurrentSkipList(SkipList):
    """
    Fine-grained locking: lock each node individually.
    
    The key insight: because updates only affect adjacent nodes,
    and level-0 is a linked list, we can use hand-over-hand locking
    (lock current, lock next, update, unlock current).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.locks = threading.local()

    def insert(self, score: float, value: str) -> None:
        # Mark nodes to update (with locks)
        prevs = [None] * (self.MAX_LEVEL + 1)
        locks_held = []
        
        try:
            current = self.header
            for i in range(self.level, -1, -1):
                while (current.forward[i] and
                       current.forward[i].score < score):
                    current = current.forward[i]
                prevs[i] = current
                # Lock the predecessor
                # (In practice: use CAS operations, not locks)
            
            # ... rest of insert with locks held
        finally:
            for lock in locks_held:
                lock.release()
```

**Production Lessons:**

```
War Story: "Skip List in Redis"
- Redis uses Skip Lists for ZSET (sorted set) — NOT a balanced BST
- Why?
  1. Simpler concurrent implementation (single-threaded Redis anyway)
  2. Efficient range queries (ZRANGE, ZRANK traverse level-0)
  3. Less memory per element (~2 pointers vs ~3 for RB-tree)
  4. Easier to debug and get right

Memory comparison per 10M entries:
  Skip List: 10M × 2 pointers × 8 bytes = 160MB
  RB-Tree:  10M × 4 (parent + left + right + color) = 320MB
  
Trade-off: Skip List's O(log N) expected vs RB-tree's O(log N) worst-case
  In practice: path length variation is small (sigma ≈ 1.5)
  The 1-in-a-million worst case is ~6× expected — still only ~60 steps
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Probabilistic balancing** | Explains how random level choice gives O(log N) expected time |
| **Level promotion** | Uses geometric distribution (p=0.5) correctly |
| **Range query** | Shows level-0 traversal as natural leaderboard |
| **Concurrent** | Explains fine-grained locking advantage over BSTs |

---

## 12. Merkle Tree: Tamper-Evident Verification

**Q:** "Design a system to verify data consistency across 1000 database replicas without transferring full snapshots. Replicas may diverge due to network partitions. How would you use Merkle trees to reconcile differences efficiently? What's the communication cost in terms of hashes vs data?"

**What They're Really Testing:** Whether you understand the anti-entropy protocol — specifically, that Merkle tree comparison localizes differences to O(log N) hash exchanges instead of O(N) data transfer.

### Answer

**Core Concept:**

A Merkle tree is a binary tree where each leaf is a hash of a data block, and each internal node is the hash of its two children. The root hash therefore commits the entire dataset.

```python
import hashlib

class MerkleNode:
    def __init__(self, hash_val: bytes, left: 'MerkleNode' = None,
                 right: 'MerkleNode' = None):
        self.hash = hash_val
        self.left = left
        self.right = right

class MerkleTree:
    """
    Binary Merkle tree for data verification.
    
    Properties:
    - Root hash commits the entire dataset
    - Any change to any leaf changes the root
    - Proof of inclusion: O(log N) hashes per leaf
    - Comparison: O(log N) hash exchanges to find differing blocks
    """
    def __init__(self, data_blocks: List[bytes]):
        self.leaves = [self._hash(b) for b in data_blocks]
        self.root = self._build(self.leaves)

    def _hash(self, data: bytes) -> bytes:
        return hashlib.sha256(data).digest()

    def _build(self, hashes: List[bytes]) -> MerkleNode:
        """Build tree bottom-up."""
        if len(hashes) == 1:
            return MerkleNode(hashes[0])

        # Ensure even number of nodes
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])  # Duplicate last for odd counts

        parents = []
        for i in range(0, len(hashes), 2):
            combined = hashes[i] + hashes[i+1]
            parent_hash = self._hash(combined)
            parent = MerkleNode(parent_hash)
            parent.left = MerkleNode(hashes[i])
            parent.right = MerkleNode(hashes[i+1])
            parents.append(parent_hash)
        
        return self._build(parents)

    @property
    def root_hash(self) -> bytes:
        return self.root.hash if self.root else b''

    def get_proof(self, index: int) -> List[bytes]:
        """
        Generate a Merkle proof of inclusion.
        
        Proof = sibling hashes along the path from leaf to root.
        Verifier can reconstruct root using: leaf + proof siblings.
        Proof size: log₂(N) hashes (≈20 for 1M blocks).
        
        Example: N=8, index=3 (leaf 3):
          Path: leaf3 → hash(2,3) → hash(0-3) → hash(0-7)
          Proof: [leaf2, hash(0,1), hash(4-7)]
          
          Verifier computes:
            h03 = hash(leaf2 + leaf3)
            h01 = hash(hash(0,1) as given)
            root = hash(h01 + h03)
            Verify: root == expected_root
        """
        proof = []
        level = self.leaves[:]
        idx = index

        while len(level) > 1:
            if len(level) % 2 != 0:
                level.append(level[-1])

            sibling_idx = idx ^ 1  # XOR to get sibling
            proof.append(level[sibling_idx])

            # Move to parent level
            idx = idx // 2
            level = [self._hash(level[i] + level[i+1])
                     for i in range(0, len(level), 2)]

        return proof
```

**Anti-Entropy Protocol — The Killer App:**

```python
class ReplicaSync:
    """
    Efficient reconciliation between replicas using Merkle trees.
    
    Protocol:
    1. Exchange root hashes
    2. If different: exchange children hashes
    3. Recurse until differing leaf is found
    4. Fetch only the differing data block
    
    Communication cost: O(log N) hash exchanges + O(1) data blocks
    vs O(N) data transfer for full sync.
    """
    def __init__(self, data: Dict[int, bytes]):
        self.data = data
        self.merkle = MerkleTree([data[i] for i in sorted(data.keys())])

    def sync_with(self, remote: 'ReplicaSync'):
        """Reconcile differences with remote replica."""
        differing_blocks = []
        self._compare_node(self.merkle.root, remote.merkle.root,
                          0, len(self.data) - 1, differing_blocks)
        
        # Fetch only the differing blocks
        for block_id in differing_blocks:
            self.data[block_id] = remote.data[block_id]
        
        # Rebuild tree
        self.merkle = MerkleTree(
            [self.data[i] for i in sorted(self.data.keys())]
        )
        return differing_blocks

    def _compare_node(self, local_node, remote_node,
                      start, end, differences):
        """Recursive comparison — O(log N) hash exchange."""
        if local_node.hash == remote_node.hash:
            return  # Subtree is identical
        
        if start == end:
            # Leaf level — we found a difference
            differences.append(start)
            return
        
        mid = (start + end) // 2
        self._compare_node(local_node.left, remote_node.left,
                          start, mid, differences)
        self._compare_node(local_node.right, remote_node.right,
                          mid + 1, end, differences)
```

**Communication Cost Analysis:**

```python
"""
Cost to reconcile N blocks with D differences:

  Naive: transfer all N blocks → O(N) bandwidth
  
  Merkle tree comparison:
    1. Exchange root: 1 hash (32 bytes)
    2. For each differing branch, exchange another hash
    3. Total: O(D × log N) hashes + D blocks
  
  Example: N = 1M blocks, D = 5 differences
    Naive: 1M × 4KB = 4GB transferred
    Merkle: 5 × 20 hashes × 32 bytes = 3.2KB + 5 blocks × 4KB = ~23KB
    
    Savings: ~175,000× less bandwidth

Comparison with other techniques:

  Technique              Bandwidth         CPU           Works with
  ------                 ---------         ---           ---------
  Full snapshot          O(N) × block      O(N) hash     Any data
  Merkle tree            O(D log N)        O(N) hash     Any data
  Bloom filter           O(N) log            O(N)          Membership only
  Listen/notify          O(1) (signal)     O(1)          Active replication
  CDC-based sync         O(D) (chunks)     O(N) cdc      File systems (rsync)

  Merkle trees are best when:
  - Differences are few (< 1% of data)
  - Dataset is large (millions of blocks)
  - You need cryptographic guarantees (not just checksums)
"""
```

**The Sparse Merkle Tree — Scaling to Billions of Keys:**

```python
class SparseMerkleTree:
    """
    A Merkle tree over a potentially HUGE keyspace (2^256).
    Only non-empty leaves are stored. Empty leaves have a
    well-known default hash.
    
    Used in:
    - Certificate Transparency (Google)
    - Ethereum state trie
    - Libra/Diem blockchain
    - DynamoDB's cross-region replication
    
    Properties:
    - Prove inclusion of any key in O(log N) hashes
    - Prove NON-inclusion of any key in O(log N) hashes
      (by proving the path leads to a default hash)
    - Update any key in O(log N)
    - Memory: O(N) where N = number of non-empty keys
    """
    EMPTY_HASH = hashlib.sha256(b'').digest()
    
    def __init__(self):
        self.root = SparseNode()  # Empty tree
    
    def update(self, key: bytes, value: bytes) -> None:
        """Insert or update a key-value pair."""
        path = self._key_to_bits(key)
        leaf_hash = hashlib.sha256(value).digest()
        self.root = self._update(self.root, path, 0, leaf_hash)

    def _update(self, node, path: List[int], depth: int,
                leaf_hash: bytes) -> 'SparseNode':
        if depth == len(path):  # Leaf node
            return SparseNode(hash_val=leaf_hash, is_leaf=True)
        
        bit = path[depth]
        child = self._update(node.children[bit], path,
                             depth + 1, leaf_hash)
        return SparseNode().with_children(
            child if bit == 0 else node.children[0],
            child if bit == 1 else node.children[1]
        )
    
    def prove_inclusion(self, key: bytes) -> List[bytes]:
        """Merkle proof that this key is in the tree."""
        proof = []
        path = self._key_to_bits(key)
        current = self.root
        
        for bit in path:
            sibling_hash = (current.children[bit ^ 1].hash
                           if current.children[bit ^ 1]
                           else self.EMPTY_HASH)
            proof.append(sibling_hash)
            current = current.children[bit]
        
        return proof

    @staticmethod
    def verify_inclusion(proof: List[bytes], key_hash: bytes,
                         root_hash: bytes) -> bool:
        """Verify a Merkle proof of inclusion."""
        current = key_hash
        for sibling in proof:
            current = hashlib.sha256(current + sibling).digest()
        return current == root_hash
```

**Production Lessons:**

```
War Story: "Merkle Tree Anti-Entropy at Amazon DynamoDB"
- DynamoDB uses Merkle trees for cross-region replication
- Each replica maintains a Merkle tree over its key range
- During gossip: replicas exchange root hashes
- When roots differ: recursive compare to find the difference
- Result: most sync cycles find 0-1 differences, cost = O(log N) hashes

But there's a catch — rebuilding the tree is expensive:
  10M keys × 1 SHA-256 each ≈ 300ms on modern hardware
  If keys change at 10K/sec, you need incremental updates

Solution: use a Merkle B-Tree (merge of B-Tree + Merkle tree)
- B-Tree naturally groups keys into pages
- Build hash per page (not per key)
- Root = hash of page hashes
- Update only affects one page's hash and its path to root
- Cost per update: O(log_B N) hashes instead of O(N) rebuild
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Anti-entropy protocol** | Describes recursive hash comparison |
| **Communication cost** | Quantifies O(D log N) hash exchange vs O(N) data transfer |
| **Proof of inclusion** | Constructs and verifies Merkle proofs |
| **Sparse variant** | Knows Sparse Merkle Tree for non-inclusion proofs at scale |

---

## Summary: Choosing the Right Structure

| Problem | Best Structure | Why |
|---------|---------------|-----|
| **Set membership** (deletable) | Cuckoo Filter | Lower memory than Counting BF |
| **Set membership** (insert only) | Bloom Filter | Tighter memory, simpler |
| **Cardinality estimation** | HyperLogLog | ~2KB for 1B distinct values |
| **Frequency estimation** | Count-Min Sketch | Guaranteed no undercount |
| **Set similarity** | MinHash + LSH | Sub-linear retrieval via banding |
| **Geospatial proximity** | H3 | Uniform hex grid, k-ring queries |
| **Geospatial storage** | S2 | 64-bit cell ID, Hilbert curve |
| **Geospatial encoding** | Geohash | Simple string, prefix queries |
| **2D collision/range** | Quad Tree | Adaptive partitioning |
| **Rectangle queries** | R-Tree (R*) | Bounding box index, balanced |
| **Ordered leaderboard** | Skip List | Concurrent, simple range queries |
| **Data integrity** | Merkle Tree | O(log N) proof, anti-entropy |

> *Master these structures and their trade-offs, and you'll be prepared for the most rigorous system design questions at Staff/Principal level — from database internals to distributed systems to geospatial indexing.*
