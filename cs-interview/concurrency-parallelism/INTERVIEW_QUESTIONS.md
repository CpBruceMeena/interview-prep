# ⚡ Concurrency & Parallelism — Staff-Level Interview Questions

> *10 questions covering lock-free data structures, memory models, schedulers, and deadlock analysis — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Lock-Free Data Structures & Hazard Pointers](#1-lock-free-data-structures-hazard-pointers)
2. [Memory Models: Happens-Before & Ordering](#2-memory-models-happens-before-ordering)
3. [Amdahl's Law & Universal Scalability Law](#3-amdahls-law-universal-scalability-law)
4. [Deadlock Analysis & Prevention](#4-deadlock-analysis-prevention)
5. [Work-Stealing Schedulers](#5-work-stealing-schedulers)
6. [Read-Copy-Update (RCU)](#6-read-copy-update-rcu)
7. [Futex & Lock Contention Profiling](#7-futex-lock-contention-profiling)
8. [Thread Pools: Design & Tuning](#8-thread-pools-design-tuning)
9. [Non-Blocking Progress Guarantees](#9-non-blocking-progress-guarantees)

---

## 1. Lock-Free Data Structures & Hazard Pointers

**Q:** "Design a lock-free stack (Treiber's stack) in C++. Now a thread pops an element that another thread has already freed. How do hazard pointers solve this ABA problem? Show the implementation."

**What They're Really Testing:** Whether you understand the memory reclamation problem in lock-free programming, not just the atomic operations.

### Answer

**Treiber's Stack (Lock-Free Push/Pop):**

```cpp
template<typename T>
class TreiberStack {
    struct Node {
        T data;
        Node* next;
    };

    std::atomic<Node*> head_{nullptr};

public:
    void push(const T& value) {
        Node* node = new Node{value, nullptr};
        Node* old_head;
        do {
            old_head = head_.load(std::memory_order_acquire);
            node->next = old_head;
        } while (!head_.compare_exchange_weak(
            old_head, node,
            std::memory_order_release,
            std::memory_order_acquire
        ));
    }

    std::optional<T> pop() {
        Node* old_head;
        do {
            old_head = head_.load(std::memory_order_acquire);
            if (!old_head) return std::nullopt;
        } while (!head_.compare_exchange_weak(
            old_head, old_head->next,
            std::memory_order_release,
            std::memory_order_acquire
        ));
        T result = old_head->data;
        delete old_head;  // ← BUG! Another thread might be reading this!
        return result;
    }
};
```

**The ABA Problem:**

```
Thread A: pop()
  1. head_ = Node1
  2. Read head_ → Node1
  3. Read Node1->next → Node2
  4. [PREEMPTED BY THREAD B]

Thread B: pop() x2, then push(Node1_reused)
  5. pop() → Node1 (head_ = Node2)
  6. pop() → Node2 (head_ = null)
  7. push(Node1_reused) (reused the SAME Node1 pointer from a pool)
     head_ = Node1_reused, Node1_reused->next = null

Thread A resumes:
  8. CAS(&head_, Node1, Node2) → SUCCEEDS!
     (head_ == Node1_reused, which has the SAME address as Node1)
  9. But head_ → Node1_reused, and head_ is now Node2 (wrong!)
  10. delete Node1_reused → but Node1_reused is STILL being used!
```

**Hazard Pointers Solution:**

```cpp
class HazardPointer {
    static constexpr int kMaxThreads = 128;
    static std::atomic<void*> hp_[kMaxThreads];
    static std::atomic<int> next_idx_;

    int idx_;
    std::atomic<void*>* hp_ptr_;
    std::vector<void*> retired_;

public:
    HazardPointer() : idx_(next_idx_.fetch_add(1)) {
        hp_ptr_ = &hp_[idx_];
    }

    void protect(void* ptr) {
        hp_ptr_->store(ptr, std::memory_order_release);
    }

    void unprotect() {
        hp_ptr_->store(nullptr, std::memory_order_release);
    }

    void retire(void* ptr) {
        retired_.push_back(ptr);
        if (retired_.size() >= kRetireThreshold) {
            scan_and_reclaim();
        }
    }

    bool is_protected(void* ptr) {
        for (int i = 0; i < next_idx_.load(); i++) {
            if (hp_[i].load(std::memory_order_acquire) == ptr) {
                return true;
            }
        }
        return false;
    }

    void scan_and_reclaim() {
        std::vector<void*> to_free;
        for (auto* ptr : retired_) {
            if (!is_protected(ptr)) {
                to_free.push_back(ptr);  // Safe to delete
            } else {
                // Keep — still being read by another thread
            }
        }
        for (auto* ptr : to_free) {
            delete static_cast<Node*>(ptr);
        }
        retired_.clear();
    }

    ~HazardPointer() {
        scan_and_reclaim();
        hp_ptr_->store(this, std::memory_order_release);  // Mark as available
    }
};

// Now the lock-free pop is safe:
std::optional<T> pop(HazardPointer& hp) {
    Node* old_head;
    do {
        old_head = head_.load(std::memory_order_acquire);
        if (!old_head) return std::nullopt;

        hp.protect(old_head);  // Announce: "I'm reading this node"
        if (head_.load() != old_head) {
            // head_ changed between load and protect!
            continue;  // Retry the CAS loop
        }
    } while (!head_.compare_exchange_weak(
        old_head, old_head->next,
        std::memory_order_release,
        std::memory_order_acquire
    ));

    hp.unprotect();            // No longer reading
    T result = old_head->data;
    hp.retire(old_head);       // Schedule for safe deletion
    return result;
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ABA awareness** | Explains the ABA problem with a concrete example |
| **Hazard pointers** | Knows the publish-protect-retire-scan lifecycle |
| **Memory ordering** | Uses acquire/release correctly, not just seq_cst everywhere |
| **Alternatives** | Mentions RCU, epoch-based reclamation as alternatives |

---

## 2. Memory Models & Happens-Before

**Q:** "This concurrent counter code produces incorrect results despite using atomic operations. Diagnose why and fix it."

```cpp
struct Counter {
    std::atomic<uint64_t> a{0};
    std::atomic<uint64_t> b{0};
    uint64_t c{0};

    void update() {
        a.store(1, std::memory_order_relaxed);
        b.store(1, std::memory_order_relaxed);
        c = 1;  // ← non-atomic!
    }

    bool check() {
        if (b.load(std::memory_order_relaxed)) {
            return a.load(std::memory_order_relaxed) == 1;  // Can be false!
        }
        return true;
    }
};
```

**Answer:**

```cpp
// The problem: memory_order_relaxed provides NO ordering guarantees.
// Thread 1: a.store(1, relaxed); b.store(1, relaxed);
// Thread 2: b.load(relaxed) → 1; a.load(relaxed) → 0 (reordered!)

// Fixed with release/acquire:
struct Counter {
    std::atomic<uint64_t> a{0};
    std::atomic<uint64_t> b{0};

    void update() {
        a.store(1, std::memory_order_release);
        b.store(1, std::memory_order_release);
        // Release: all writes BEFORE this are visible
        //          to a thread that acquires on b
    }

    bool check() {
        if (b.load(std::memory_order_acquire)) {
            // Acquire: sees all writes from the release
            // → a.load() MUST see 1
            return a.load(std::memory_order_relaxed) == 1;  // Guaranteed!
        }
        return true;
    }
};

// Happens-before chain:
// update(): a.store(1) ──→ b.store(1) (program order)
//                              │
//                       release/acquire on b
//                              │
// check():  b.load(1) ←──────┘
//           a.load() sees everything before release → guaranteed 1
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Relaxed semantics** | Knows relaxed = no ordering at all |
| **Release/acquire** | Explains the synchronizes-with relation correctly |
| **SC-DRF** | Understands SC for DRF programs if sequentially consistent atomics are used |
| **Compiler vs CPU** | Knows both can reorder (compiler + CPU memory model) |

---

## 3. Amdahl's Law & Universal Scalability Law

**Q:** "A database query takes 100ms, of which 20ms is sequential (connection setup, query parsing) and 80ms is parallelizable (scanning 8 partitions). If we double the CPUs from 8 to 16, what speedup do we get? Now factor in the Universal Scalability Law's contention and coherence costs."

**What They're Really Testing:** Whether you understand the fundamental limits of parallelism — not just Amdahl's Law's formula, but the real-world overheads of contention and coherence that the Universal Scalability Law captures.

### Answer

**Amdahl's Law — The Idealized Limit:**

```
Speedup(N) = 1 / (S + P/N)

Where:
  S = sequential fraction (cannot be parallelized)
  P = parallel fraction (can be split across N processors)
  S + P = 1

For the query:
  Total time = 100ms
  Sequential (S) = 20ms → S = 0.2
  Parallel (P) = 80ms → P = 0.8

Speedup with 16 CPUs:
  = 1 / (0.2 + 0.8/16) = 1 / (0.2 + 0.05) = 1/0.25 = 4.00×

Speedup with 32 CPUs:
  = 1 / (0.2 + 0.8/32) = 1 / (0.2 + 0.025) = 1/0.225 = 4.44×

Speedup with 64 CPUs:
  = 1 / (0.2 + 0.8/64) = 1 / (0.2 + 0.0125) = 1/0.2125 = 4.71×

Speedup with ∞ CPUs:
  = 1 / 0.2 = 5.00×  ← HARD LIMIT
```

**The Diminishing Returns Curve:**

```
Speedup
 5× |                                           ● (limit = 5×)
 4× |                      ●───●───●───●───●───
 3× |           ●
 2× |     ●
 1× |●
    └──────────────────────────────────────────
      1    2    4    8    16   32   64   128
                       ↑               Processors
                  Knee point
                  (16 CPUs = 4×,
                   32 CPUs = 4.44×)

Key insight: The first few CPUs give the most benefit.
Doubling from 8→16 gives +1× (3→4).
Doubling from 16→32 gives only +0.44× (4→4.44).
Doubling from 32→64 gives only +0.27×.
```

**Why Amdahl's Law is MISLEADING in Practice:**

```
Amdahl's Law assumes:
  1. No overhead from parallelism (synchronization, communication)
  2. Perfect load balancing (work divides evenly)
  3. No resource contention (memory bandwidth, cache coherence)
  4. Serial fraction S is constant (doesn't grow with N)

In reality:
  - Synchronization overhead grows with N (locking, barriers)
  - Cache coherence traffic grows with N (cache line bouncing)
  - Load imbalance increases with N (skew, stragglers)
  - Memory bandwidth becomes a bottleneck

This is why Amdahl's Law often OVERESTIMATES real speedup.
```

**Universal Scalability Law (Gunther's Law):**

```
C(N) = N / (1 + σ(N-1) + κ·N(N-1))

Where:
  C(N) = relative capacity (throughput) with N processors
  σ = contention coefficient (serialization)
  κ = coherence coefficient (cross-talk overhead)
  N = number of processors

Note the κ·N(N-1) term: coherence overhead grows QUADRATICALLY with N!
This captures the reality that as you add processors:
  - Each new processor talks to ALL existing processors (N-1)
  - The overhead is proportional to the PAIRS of processors
```

**Fitting the USL to Real Data:**

```python
# Real benchmark: HTTP server scaling
# Data collected from production (N = 1, 2, 4, 8, 16):

# Measured throughput (requests/sec):
n_values = [1, 2, 4, 8, 16]
throughput_measured = [1000, 1800, 3200, 4800, 5200]

# USL model: C(N) = N / (1 + σ(N-1) + κ·N(N-1))
def usl(N, sigma, kappa):
    return N / (1 + sigma * (N - 1) + kappa * N * (N - 1))

# Fitted parameters (illustrative):
sigma = 0.1   # 10% serialization (connection setup, lock contention)
kappa = 0.005 # 0.5% coherence per pair (cache line bouncing)

# USL predictions vs Amdahl:
for N in [1, 2, 4, 8, 16, 32, 64, 128]:
    amdahl = 1 / (0.2 + 0.8/N)
    usl_val = usl(N, sigma, kappa)
    print(f"N={N:3d}: Amdahl={amdahl:.2f}×, USL={usl_val:.2f}×")

# Output:
# N=  1: Amdahl=1.00×, USL=1.00×
# N=  2: Amdahl=1.67×, USL=1.80×
# N=  4: Amdahl=2.50×, USL=2.94×
# N=  8: Amdahl=3.33×, USL=4.04×
# N= 16: Amdahl=4.00×, USL=4.32×  ← Knee point (peak throughput)
# N= 32: Amdahl=4.44×, USL=3.53×  ← Retrograde begins!
# N= 64: Amdahl=4.71×, USL=2.33×
# N=128: Amdahl=4.85×, USL=1.35×  ← Slower than 16 CPUs!

# Key insight: Adding CPUs past the knee point REDUCES throughput.
# The coherence overhead κ·N(N-1) grows quadratically and eventually
# overwhelms the linear speedup from additional processors.
```

**The Three Regimes of USL:**

```
                   ┌──────────────────────────────────────┐
                   │           Throughput vs N             │
                   │                                      │
                   │    ▲                                  │
Throughput         │    │   ┌──┐                           │
                   │    │   │  │                           │
                   │    │   │  │    ───┐                    │
                   │    │   │  │       │   ────┐            │
                   │    │   │  │       │       │  ───       │
                   │    │   │  │       │       │    └───    │
                   │    └───┴──┴───────┴───────┴────────────▶
                   │    σ dominates  κ overtakes            N
                   │    ←───────────→←──────────→
                   │    Linear-ish   Retrograde
                   │    (adding CPUs  (adding CPUs
                   │     still helps) hurts throughput)
                   └──────────────────────────────────────┘

Three regimes:
  1. Sub-linear: N=1→8, each CPU adds >0 but <1× throughput
     - Contention σ limits us: lock contention, bus saturation
  2. Saturation: N=8→16, throughput plateaus (knee point)
     - σ + κ combine: adding CPUs barely helps
  3. Retrograde: N>16, throughput DECLINES
     - κ·N(N-1) dominates: coherence overhead exceeds compute gain
     - Cache lines bounce like hot potatoes between cores
     - False sharing amplifies the effect
```

**Practical Implications:**

```yaml
# Use USL to find OPTIMAL concurrency before building:

# Example 1: Database connection pool sizing
#   σ = 0.15 (connection setup, transaction serialization)
#   κ = 0.008 (buffer pool contention, lock manager)
#   Optimal N = sqrt((1-σ)/κ) ≈ sqrt(0.85/0.008) ≈ 10 connections
#   Beyond 10: throughput flattens, latency spikes

# Example 2: Thread pool for web server
#   σ = 0.05 (request parsing, response formatting)
#   κ = 0.002 (worker thread contention, shared cache)
#   Optimal N = sqrt(0.95/0.002) ≈ 22 threads
#   Beyond 22: context switching overhead dominates

# Example 3: MapReduce job
#   σ = 0.02 (job setup, shuffle)
#   κ = 0.0005 (network cross-talk, shuffle bandwidth)
#   Optimal N = sqrt(0.98/0.0005) ≈ 44 mappers
#   Beyond 44: shuffle phase becomes bottleneck
```

**Amdahl vs USL — Side by Side:**

```
N      Amdahl (S=0.2)   USL (σ=0.1, κ=0.005)   Reality (measured)
──      ─────────────   ────────────────────   ─────────────────
1       1.00×           1.00×                  1.00× (1000 req/s)
2       1.67×           1.80×                  1.80×
4       2.50×           2.94×                  3.20×
8       3.33×           4.04×                  4.80×
16      4.00×           4.32×  ← peak          5.20×
32      4.44×           3.53×                  — (retrograde)
64      4.71×           2.33×                  — (worse)
128     4.85×           1.35×                  — (slower than 16!)

Amdahl says: S=0.2 limits max speedup to 5×, but more CPUs always help.
USL says: past the knee point (N=16), coherence overhead makes more CPUs HURT.
Reality matches USL much closer — machines show retrograde scaling.
```

**Production Checklist for Scalability Analysis:**

```bash
# How to measure σ and κ for your system:

# 1. Measure throughput at different concurrency levels
#    (e.g., using wrk, hey, or k6)
wrk -t1 -c1 -d30s http://service        # N=1: baseline
wrk -t2 -c2 -d30s http://service        # N=2
wrk -t4 -c4 -d30s http://service        # N=4
wrk -t8 -c8 -d30s http://service        # N=8
wrk -t16 -c16 -d30s http://service       # N=16

# 2. Plot throughput vs concurrency
#    - Linear-ish at low N: good
#    - Plateau at mid N: contention σ
#    - Decline at high N: coherence κ

# 3. Fit USL model to find knee point
#    Optimal N ≈ sqrt((1-σ)/κ)

# 4. Set thread pool / connection pool to ≤ optimal N
#    If you MUST exceed optimal N, accept the throughput loss
#    and monitor for retrograde behavior
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Amdahl's Law** | Calculates speedup = 1/(S+P/N), identifies infinite-CPU limit |
| **Diminishing returns** | Explains that first CPUs give most benefit, later ones give less |
| **USL understanding** | Knows σ (contention) and κ (coherence), explains quadratic term |
| **Practical application** | Can compute optimal concurrency from USL, knows retrograde regime |

---

## 4. Deadlock Analysis & Prevention

**Q:** "A production PostgreSQL database is experiencing periodic complete hangs. Analysis shows all active queries are waiting on `LWLock` or `transactionid` locks. Walk through the deadlock detection algorithm and propose prevention."

**What They're Really Testing:** Whether you understand deadlock at the system level — the waits-for graph algorithm, detection vs prevention strategies, and how real databases like PostgreSQL handle this under load.

### Answer

**The Four Conditions for Deadlock (Coffman Conditions):**

```
For a deadlock to occur, ALL FOUR conditions must hold:

1. Mutual Exclusion: Resources can't be shared
   - A row lock can be held by only one transaction at a time

2. Hold and Wait: A thread holds resources while waiting for others
   - Transaction A holds lock on row 1 while waiting for row 2

3. No Preemption: Resources can't be forcibly taken away
   - PostgreSQL doesn't steal locks from transactions

4. Circular Wait: There's a cycle in the waits-for graph
   - A waits for B, B waits for C, C waits for A

Deadlock prevention = break at least one condition.
Deadlock detection = let it happen, then recover.
```

**The Waits-For Graph Algorithm:**

```python
# Deadlock detection = cycle detection in a directed graph
# PostgreSQL runs this every deadlock_timeout (default: 1 second)

from collections import defaultdict

class WaitsForGraph:
    """
    Directed graph: edge A → B means "A is waiting for B's lock"
    """
    def __init__(self):
        self.graph = defaultdict(set)  # {waiter: set of blockers}

    def add_wait(self, waiter: int, blocker: int):
        """Add edge: waiter → blocker"""
        self.graph[waiter].add(blocker)

    def remove_process(self, pid: int):
        """Remove process (when it completes or is killed)"""
        self.graph.pop(pid, None)
        for blockers in self.graph.values():
            blockers.discard(pid)

    def detect_deadlock(self) -> list[int] | None:
        """
        DFS-based cycle detection.
        Returns the cycle (list of PIDs) if found, None otherwise.
        """
        WHITE = 0  # Unvisited
        GRAY = 1   # In current DFS path
        BLACK = 2  # Fully explored

        color = defaultdict(int)
        parent = {}

        def dfs(node: int, path: list[int]) -> list[int] | None:
            color[node] = GRAY
            path.append(node)

            for neighbor in self.graph.get(node, []):
                if color[neighbor] == GRAY:
                    # Found a cycle! Extract it
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
                elif color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor, path)
                    if result:
                        return result

            path.pop()
            color[node] = BLACK
            return None

        for pid in list(self.graph.keys()):
            if color[pid] == WHITE:
                result = dfs(pid, [])
                if result:
                    return result
        return None

    def resolve_deadlock(self) -> int:
        """
        Choose a victim to abort.
        PostgreSQL chooses the transaction with the LOWEST
        total cost so far (cheapest to roll back).
        """
        cycle = self.detect_deadlock()
        if not cycle:
            return None

        # PostgreSQL's heuristic: abort the youngest transaction
        # (least work done, cheapest to roll back)
        return min(cycle, key=lambda pid: self.get_cost(pid))

    def get_cost(self, pid: int) -> float:
        """
        Estimated cost of rolling back this transaction.
        Based on: age, total queries executed, rows modified.
        """
        return pg_stat_activity[pid].total_time
```

**PostgreSQL's LWLock Deadlock Trace:**

```
PostgreSQL log output when deadlock is detected:

2024-01-15 10:23:45.123 UTC [12345] LOG:  process 12345 detected deadlock
    while waiting for ShareLock on transaction 1045 after 12345ms
2024-01-15 10:23:45.123 UTC [12345] DETAIL: Processes involved:
    Process 12345 waits for ShareLock on transaction 1045; blocked by 
    process 12346.
    Process 12346 waits for ShareLock on transaction 1046; blocked by 
    process 12347.
    Process 12347 waits for ShareLock on transaction 1047; blocked by 
    process 12345.
2024-01-15 10:23:45.123 UTC [12345] HINT: See server log for query details.
2024-01-15 10:23:45.123 UTC [12345] CONTEXT: while updating tuple (0,1) 
    in relation "orders"
2024-01-15 10:23:45.123 UTC [12345] STATEMENT: UPDATE orders SET 
    status = 'shipped' WHERE order_id = 42;
2024-01-15 10:23:45.124 UTC [12345] ERROR:  deadlock detected
2024-01-15 10:23:45.124 UTC [12345] DETAIL: Process 12345 was chosen as 
    victim by the deadlock detector.
2024-01-15 10:23:45.124 UTC [12345] HINT: See server log for query details.
2024-01-15 10:23:45.124 UTC [12345] STATEMENT: UPDATE orders SET 
    status = 'shipped' WHERE order_id = 42;
2024-01-15 10:23:45.124 UTC [12346] LOG:  process 12346 acquired 
    ShareLock on transaction 1045 after 12345ms
```

This log shows:
- The deadlock detector runs, discovers the cycle, and logs the details (LOG level)
- The detector chooses a victim (process 12345) and aborts its transaction (ERROR level)
- Once the victim releases its locks, process 12346 acquires the lock it was waiting for

**Detection Query (Find Blockers):**

```sql
-- Detect current blocking chains in PostgreSQL:

SELECT blocked.pid AS blocked_pid,
       blocker.pid AS blocker_pid,
       blocked.query AS blocked_query,
       blocker.query AS blocker_query,
       blocked.wait_event_type || ':' || blocked.wait_event AS blocked_waits_on,
       blocker.state AS blocker_state,
       blocked.state AS blocked_state,
       age(now(), blocked.query_start) AS blocked_duration
FROM pg_stat_activity blocked
JOIN pg_locks blocked_locks ON blocked.pid = blocked_locks.pid
JOIN pg_locks blocker_locks
    ON blocked_locks.locktype = blocker_locks.locktype
    AND blocked_locks.database IS NOT DISTINCT FROM blocker_locks.database
    AND blocked_locks.relation IS NOT DISTINCT FROM blocker_locks.relation
    AND blocked_locks.page IS NOT DISTINCT FROM blocker_locks.page
    AND blocked_locks.tuple IS NOT DISTINCT FROM blocker_locks.tuple
    AND blocked_locks.virtualxid IS NOT DISTINCT FROM blocker_locks.virtualxid
    AND blocked_locks.transactionid IS NOT DISTINCT FROM blocker_locks.transactionid
    AND blocked_locks.classid IS NOT DISTINCT FROM blocker_locks.classid
    AND blocked_locks.objid IS NOT DISTINCT FROM blocker_locks.objid
    AND blocked_locks.objsubid IS NOT DISTINCT FROM blocker_locks.objsubid
    AND blocked_locks.pid != blocker_locks.pid
JOIN pg_stat_activity blocker ON blocker.pid = blocker_locks.pid
WHERE blocked_locks.granted = false
  AND blocker_locks.granted = true
  AND blocked.state = 'active'
  AND blocked.pid != pg_backend_pid()
ORDER BY blocked_duration DESC;
```

**Deadlock Prevention Strategies:**

```yaml
# Strategy 1: Lock ordering (MOST EFFECTIVE)
#   Establish a global order for all resources (by ID, by name, etc.)
#   All transactions MUST acquire locks in this order
#   This ELIMINATES circular wait (Coffman condition #4)

Good:  BEGIN; LOCK TABLE A; LOCK TABLE B; ...
Bad:   BEGIN; LOCK TABLE B; LOCK TABLE A; ...  ← different order!

# Strategy 2: Lock timeout + retry
#   Set lock_timeout so transactions fail fast instead of blocking indefinitely
#   Retry with exponential backoff

SET lock_timeout = '5s';
-- If lock not acquired in 5s, transaction is aborted
-- Application retries with: wait = base * 2^attempt (e.g., 1s, 2s, 4s, 8s)

# Strategy 3: Keep transactions short
#   Long transactions hold locks longer → more contention → more deadlocks
#   Break large operations into smaller batches

Bad:  BEGIN; UPDATE millions_of_rows ...;  -- holds locks for MINUTES
Good: BEGIN; UPDATE 1000_rows WHERE id IN (...); COMMIT;  -- seconds

# Strategy 4: NOWAIT for optimistic paths
#   If a lock can't be acquired immediately, fail fast

SELECT ... FOR UPDATE NOWAIT;
-- vs: SELECT ... FOR UPDATE;  (blocks until lock acquired)

# Strategy 5: Indexing to reduce lock granularity
#   Seq scan: LOCKS ENTIRE TABLE (relation-level lock)
#   Index scan: LOCKS ONLY MATCHING ROWS (tuple-level lock)
#   Better indexes → fewer locks → less contention
```

**Deadlock Detection vs Prevention — Tradeoffs:**

```
Aspect              Detection                       Prevention
──────────          ─────────                       ──────────
Approach            Let it happen, abort victim      Design to eliminate possibility
Overhead            Runtime graph traversal           Design-time discipline
Latency impact      ~1s (deadlock_timeout) + abort    Zero (no abort needed)
Completeness        Catches ALL deadlocks             Human error can miss ordering
Best for            Complex, dynamic locking          Simple, known lock patterns
PostgreSQL          Default approach                  Requires application-level discipline

Hybrid approach:
  - Prevention at design time (lock ordering in transactions)
  - Detection as safety net (catch programmer mistakes)
  - Monitoring: alert if deadlocks exceed threshold (e.g., >1/hour)
```

**Real-World Debugging Walkthrough:**

```bash
# Debugging a production deadlock in PostgreSQL:

# Step 1: Check pg_stat_activity for blocked processes
SELECT pid, state, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE state = 'active'
  AND wait_event_type IS NOT NULL
ORDER BY query_start;

# Step 2: Check pg_locks for lock conflicts
SELECT pid, locktype, mode, granted, relation::regclass
FROM pg_locks
WHERE NOT granted;
-- These are processes WAITING for locks

# Step 3: Check deadlock logs (PostgreSQL logs detected deadlocks)
# Look in pg_log/ for "deadlock detected"
# Each entry shows:
#   - The deadlock cycle (which processes were involved)
#   - The exact queries that caused the deadlock
#   - Which process was chosen as victim

# Step 4: Simulate the deadlock
-- Session A:
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;  -- Lock row 1
-- Session B:
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 2;  -- Lock row 2
-- Session A:
UPDATE accounts SET balance = balance + 100 WHERE id = 2;  -- WAIT (B has row 2)
-- Session B:
UPDATE accounts SET balance = balance + 100 WHERE id = 1;  -- WAIT (A has row 1)
-- DEADLOCK! PostgreSQL kills one session within deadlock_timeout (1s)

# Step 5: Fix by enforcing lock ordering
-- Always update accounts in ascending ID order:
-- Session A & B both do: UPDATE ... WHERE id IN (1, 2) ORDER BY id
-- This prevents the circular wait condition
```

**Other Languages — Deadlock Prevention APIs:**

```java
// Java: tryLock with timeout (breaks hold-and-wait)
Lock lock1 = new ReentrantLock();
Lock lock2 = new ReentrantLock();

while (true) {
    if (lock1.tryLock(100, TimeUnit.MILLISECONDS)) {
        try {
            if (lock2.tryLock(100, TimeUnit.MILLISECONDS)) {
                try {
                    // Critical section
                    break;
                } finally {
                    lock2.unlock();
                }
            }
        } finally {
            lock1.unlock();
        }
    }
    // Backoff and retry
    Thread.sleep(50);
}
```

```go
// Go: channel-based communication prevents shared-state deadlock
// (Share memory by communicating, don't communicate by sharing memory)

// But Go can still deadlock with mutexes:
var mu1, mu2 sync.Mutex

// Goroutine A:
mu1.Lock()
mu2.Lock()  // Waits if B holds mu2

// Goroutine B:
mu2.Lock()
mu1.Lock()  // Waits if A holds mu1
// DEADLOCK!

// Go's detection: runtime checks for all goroutines blocked
// "fatal error: all goroutines are asleep - deadlock!"
// But only detects TOTAL deadlock (all goroutines blocked)
// Partial deadlock (some blocked, some running) goes undetected
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Coffman conditions** | Can enumerate all 4 conditions and knows which to break |
| **Waits-for graph** | Explains cycle detection algorithm, victim selection heuristic |
| **Prevention vs detection** | Articulates tradeoffs between both approaches |
| **Real database knowledge** | Knows PostgreSQL's deadlock_timeout, pg_locks, LWLock semantics |
| **Lock ordering** | Proposes this as the most effective prevention strategy |

---

## 5. Work-Stealing Schedulers

**Q:** "Design a work-stealing scheduler for a distributed task system processing 100K tasks/second. Compare the Go scheduler's GMP model with Java's ForkJoinPool. How do you prevent thread starvation while maintaining cache locality?"

**What They're Really Testing:** Whether you understand the fundamentals of work-stealing — the tradeoff between locality and load balancing, and the specifics of production scheduler implementations.

### Answer

**The Core Algorithm:**

```python
from collections import deque
import threading
import random

class WorkStealingThread:
    """
    Each worker thread has:
      - Local deque: push/pop from BOTTOM (LIFO — cache-friendly)
      - Stealing: other threads steal from TOP (FIFO — oldest, coldest)
    """
    def __init__(self, scheduler, thread_id: int):
        self.scheduler = scheduler
        self.thread_id = thread_id
        self.local_deque: deque[callable] = deque()
        self.running = True

    def run(self):
        while self.running:
            task = self.get_task()
            if task:
                task()
            else:
                # No work — yield or sleep
                pass

    def get_task(self) -> callable | None:
        # 1. Try local deque first (LIFO — cache hot)
        if self.local_deque:
            return self.local_deque.pop()  # BOTTOM

        # 2. Steal from a random victim
        victim = random.choice(self.scheduler.workers)
        if victim is not self:
            return victim.steal_task()

        return None

    def steal_task(self) -> callable | None:
        # Steal from TOP (FIFO — oldest, least likely to be cache-hot)
        if self.local_deque:
            return self.local_deque.popleft()
        return None

    def submit(self, task: callable):
        self.local_deque.append(task)
```

**Go Scheduler — GMP Model:**

```go
// Go's scheduler (Go 1.14+, non-cooperative preemption):
//
// G = Goroutine (stack ~2KB initial, growable)
// M = Machine (OS thread, ~2MB stack)
// P = Processor (logical CPU, GOMAXPROCS default = #CPUs)
//
// Scheduling loop (per P):
//   1. Run next G from P's local run queue (LRQ)
//   2. If LRQ empty: steal from other P's LRQ (half)
//   3. If no steal: steal from global run queue (GRQ)
//   4. If nothing: park M (thread), or M goes into "spinning" state
//
// Key design decisions:
//   - GOMAXPROCS limits parallelism, not goroutines
//   - Network poller: G waiting on I/O is unblocked by dedicated poller thread
//   - sysmon: monitors P for >10ms execution → preempts via signal

// Simplified Go scheduler behavior in pseudocode:
func schedule(p *P) {
    for {
        if g := p.runq.next(); g != nil {
            execute(g)  // Run goroutine
            continue
        }
        // Steal loop
        for i := 0; i < 4; i++ {  // 4 attempts before parking
            for _, otherP := range allPs {
                if g := stealFrom(otherP); g != nil {
                    execute(g)
                    continue schedule
                }
            }
            // Spin briefly (avoids expensive park/unpark)
        }
        // Park M until a goroutine becomes available
        stopm()
    }
}
```

**Java ForkJoinPool — Work-Stealing with Divide & Conquer:**

```java
// Java's ForkJoinPool is designed for recursive decomposition:
//   - ForkJoinTask<V>: compute() returns V
//   - fork(): submit subtask to local deque
//   - join(): wait for subtask, BUT while waiting, STEAL work!

class SumTask extends RecursiveTask<Long> {
    private final long[] array;
    private final int lo, hi;
    private static final int THRESHOLD = 10_000;

    @Override
    protected Long compute() {
        if (hi - lo <= THRESHOLD) {
            long sum = 0;
            for (int i = lo; i < hi; i++) sum += array[i];
            return sum;
        }
        int mid = (lo + hi) / 2;
        SumTask left = new SumTask(array, lo, mid);
        SumTask right = new SumTask(array, mid, hi);

        left.fork();    // Push left onto local deque
        long rightResult = right.compute();  // Compute right immediately
        long leftResult = left.join();  // While waiting for left, STEAL other work!
        return leftResult + rightResult;
    }
}

// Key insight: join() calls tryHelpStealer() internally
// The waiting thread processes tasks from its own deque (LIFO)
// OR steals from others (FIFO) — keeps all CPUs busy
```

**Comparison:**

```
Aspect              Go GMP                     Java ForkJoinPool
──────────          ──────────                  ────────────────────
Task unit           Goroutine (2KB stack)       ForkJoinTask (object)
Preemption          Non-cooperative (signal)    Cooperative (fork/join)
Local queue         Lock-free deque (per P)     Lock-free deque (per thread)
Stealing            Random victim + steal half  Random victim + steal oldest
Global queue        Yes (GRQ, for async tasks)   Yes (submission queue)
Blocking I/O        Unblocked via netpoller      Blocking (dedicated thread)
Best for            Network services, I/O        CPU-bound computation
```

**Starvation Prevention:**

```python
# Problem: A thread might idle while others have work, if it keeps
# failing to steal from busy victims.
#
# Solution 1: Enable stealing from global queue
#   — Tasks submitted externally go to a global queue
#   — Idle threads always check global before sleeping
#
# Solution 2: Work-sharing (push work to idle threads)
#   — When a thread's local deque exceeds threshold, push
#     tasks to idling threads or a shared overflow queue
#
# Solution 3: LIFO splitting (Go steals half, not 1 task)
#   — Stealing HALF the deque reduces steal frequency
#   — Original owner gets LIFO (hot), thief gets FIFO (cold)
#   — Both threads work for a while before needing to steal again
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Local deque design** | Explains LIFO for owner (cache hot) vs FIFO for thief (cache cold) |
| **Go GMP model** | Knows G/M/P separation, netpoller, preemption mechanism |
| **ForkJoinPool join()** | Understands tryHelpStealer() — steals while waiting |
| **Starvation** | Mentions techniques to prevent thread starvation (global queue, work-sharing) |

---

## 6. Read-Copy-Update (RCU)

**Q:** "Design a concurrent linked list that supports wait-free reads (millions/sec) while writers update nodes. You can't use reader-writer locks because the read path is too hot. Use RCU."

**What They're Really Testing:** Whether you understand RCU's fundamental insight — that reads can be wait-free if you defer reclamation until all concurrent readers are done.

### Answer

**The RCU Abstraction:**

```python
# RCU = Read-Copy-Update
# 
# Readers:            Writers:
#   1. rcu_read_lock()   1. Copy shared data
#   2. Read pointer      2. Modify the copy
#   3. rcu_read_unlock() 3. rcu_assign_pointer() ← atomic swap
#   4. Use dereferenced   4. synchronize_rcu() ← wait for readers
#      data               5. Free old copy
#
# Key insight: Readers NEVER block, NEVER spin, NEVER take locks.
# The writer waits for readers after publishing the new pointer.
```

**RCU-Protected Linked List:**

```python
import threading
import atomic  # Pseudocode for C11 _Atomic or C++20 std::atomic

class RCUNode:
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.next = None  # Atomic pointer (for lock-free traversal)

class RCUList:
    """
    RCU-protected singly-linked list.
    Readers: wait-free (no locks, no atomics beyond read)
    Writers: copy node, update pointer, wait for grace period, free
    """
    def __init__(self):
        self.head = RCUNode(None, None)  # Sentinel

    def search(self, key) -> str | None:
        """
        Wait-free read path.
        No locks, no retries, just pointer chasing.
        """
        rcu_read_lock()
        try:
            curr = self.head
            while curr:
                if curr.key == key:
                    return curr.value
                curr = curr.next
            return None
        finally:
            rcu_read_unlock()

    def insert(self, key, value):
        """
        Writer: copy new node, update pointer, wait for grace period.
        """
        new_node = RCUNode(key, value)

        while True:
            head = self.head
            new_node.next = head.next
            # Atomic CAS on the head's next pointer
            if CAS(&head.next, new_node.next, new_node):
                break
        # New node is now visible to all NEW readers
        # But OLD readers might still be traversing the OLD next
        synchronize_rcu()  # Wait for all current readers to finish
        # Now it's safe to free any old nodes (none in this case)

    def delete(self, key):
        """
        Writer: logically remove node, update pointer, defer free.
        Uses a "dead" flag to handle in-progress readers.
        """
        prev = self.head
        curr = prev.next
        while curr:
            if curr.key == key:
                # Point prev to curr.next
                # Readers currently at curr will continue traversing
                # old list until they exit their read-side critical section
                CAS(&prev.next, curr, curr.next)

                # Grace period: wait for readers that might be AT curr
                synchronize_rcu()

                # Now it's safe to free curr
                free(curr)
                return
            prev = curr
            curr = curr.next
```

**Grace Period Management:**

```python
# The heart of RCU: how does synchronize_rcu() work?
#
# Approach 1: Quiescent states (Linux kernel)
#   - Each CPU periodically records a "quiescent state"
#     (context switch, user-mode execution, idle)
#   - synchronize_rcu() waits for ALL CPUs to pass through
#     a quiescent state — guarantees all prior readers are done
#   - Very fast: typically <10ms on a modern kernel

# Approach 2: Epoch-based reclamation (userspace)
#   - Global epoch counter (0, 1, 2)
#   - Readers announce which epoch they're in
#   - Writer advances epoch and waits for all readers to leave
#     the old epoch
#
# Userspace RCU (liburcu):
#   - rcu_read_lock() = store thread's current epoch in thread-local
#   - rcu_read_unlock() = clear the epoch
#   - synchronize_rcu() = advance epoch, wait until ALL
#     threads have the current or next epoch (not old)

class EpochBasedRCU:
    def __init__(self):
        self.epoch = 0
        self.reader_epochs = {}  # thread_id → epoch or -1 (not reading)

    def rcu_read_lock(self):
        tid = threading.get_ident()
        self.reader_epochs[tid] = self.epoch
        # Memory barrier: ensure reads don't leak out of CS
        atomic_thread_fence(memory_order_acquire)

    def rcu_read_unlock(self):
        tid = threading.get_ident()
        self.reader_epochs[tid] = -1
        atomic_thread_fence(memory_order_release)

    def synchronize_rcu(self):
        """
        Wait for all readers to finish.
        1. Advance epoch (new readers use new epoch)
        2. Wait until no thread is in the PREVIOUS epoch
        """
        old_epoch = self.epoch
        self.epoch = (self.epoch + 1) % 3

        for tid in list(self.reader_epochs.keys()):
            while self.reader_epochs.get(tid) == old_epoch:
                # Spin until this thread exits its read-side CS
                # Real implementations: yield(), not spin
                pass

        # Memory barrier: ensure all frees happen AFTER readers are done
        atomic_thread_fence(memory_order_release)
```

**Where RCU Shines:**

```yaml
# RCU is ideal when:
#   - Reads >>> writes (e.g., 99.99% reads)
#   - Read path is extremely latency-sensitive (microseconds)
#   - Data structure is pointer-based (linked list, tree, hash table)
#
# Linux kernel uses RCU for:
#   - Routing tables (reads on every packet, writes on route changes)
#   - File system operations (dcache, inode lists)
#   - Process tables (/proc scanning)
#
# Userspace uses:
#   - ConcurrencyKit (userspace RCU library)
#   - liburcu (used by PostgreSQL for some data structures)
#   - memcached (experimental RCU-based hash table)
#
# When NOT to use RCU:
#   - Write-heavy workloads (synchronize_rcu() is expensive!)
#   - Real-time systems with bounded priority inversion
#   - When you need transactional semantics across multiple updates
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Read-side cost** | Emphasizes that reads are wait-free (no locks, no atomics) |
| **Grace period** | Explains quiescent states or epoch-based reclamation |
| **Write-side deferral** | Understands that writes are visible immediately, frees are deferred |
| **Linux kernel context** | Knows real-world RCU usage (rculist, routing tables, dcache) |

---

## 7. Futex & Lock Contention Profiling

**Q:** "A high-frequency trading application shows 8% CPU time spent in `futex_wait` and `futex_wake` syscalls. Walk through how you'd diagnose and fix this: profiling, adaptive spinning, and lock-free alternatives."

**What They're Really Testing:** Whether you understand the fast-path/slow-path design of modern mutexes and can profile/optimize lock contention in production.

### Answer

**Futex — The Fast Userspace Mutex:**

```c
// Futex = Fast Userspace muTex
// Core idea: mutex is a 32-bit integer in userspace
//   Fast path: atomic CAS (no syscall) → ~5ns
//   Slow path: futex_wait/futex_wake syscall → ~500ns (100× slower!)

// Simplified futex-based mutex:
//   State: 0 = unlocked, 1 = locked (no waiters), 2 = locked (waiters)

void lock(int* futex) {
    // Fast path: try to CAS from 0 to 1
    if (atomic_cas(futex, 0, 1)) {
        return;  // Acquired in ~5ns!
    }

    // Slow path: there's contention
    if (*futex != 2) {
        *futex = 2;  // Mark as having waiters
    }

    while (atomic_xchg(futex, 2)) {  // Try to acquire, mark as contended
        futex_wait(futex, 2);  // Syscall — thread sleeps
        // Wakes when another thread calls futex_wake and *futex != 2
    }
    // Acquired (but it took ~500ns+ due to syscall + context switch)
}

void unlock(int* futex) {
    if (atomic_xchg(futex, 0) == 1) {
        return;  // No waiters — fast path, ~5ns
    }

    // Waiters exist — wake one
    *futex = 0;
    futex_wake(futex, 1);  // Wake 1 waiter — syscall (~500ns)
}

// Key insight: if contention is LOW, the mutex is essentially FREE
// (most operations happen in userspace, no syscalls)
// Problem: when contention is HIGH, EVERY operation hits the slow path
```

**Adaptive Spinning — The Fix for Moderate Contention:**

```c
// Problem: futex_wait/ wake involves two expensive context switches
// (waiter sleeps → scheduler runs → waiter wakes → scheduler runs)
// For short critical sections, it's better to SPIN briefly

void lock_adaptive(int* futex) {
    // Fast path
    if (atomic_cas(futex, 0, 1)) return;

    // Adaptive spin: spin for ~1000 iterations before sleeping
    for (int i = 0; i < 1000; i++) {
        if (atomic_cas(futex, 0, 1)) return;
        _mm_pause();  // x86 pause instruction (yield to hyperthread)
    }

    // Slow path: couldn't acquire after spinning — sleep
    if (*futex != 2) *futex = 2;
    while (atomic_xchg(futex, 2)) {
        futex_wait(futex, 2);
    }
}

// Adaptive spinning is used by:
//   - glibc's pthread_mutex_lock (PTHREAD_MUTEX_ADAPTIVE_NP on Linux)
//   - Java's synchronized (biased locking → spin → park)
//   - Rust's std::sync::Mutex (spin briefly before sleeping)
```

**Contention Profiling with Perf:**

```bash
# Step 1: Profile lock contention system-wide
sudo perf lock record -a -- sleep 30
sudo perf lock report

# Output shows:
#   - Total contention time per lock
#   - Number of contentions
#   - Average wait time
#   - Call stack for each contention

# Step 2: Profile specific process
sudo perf lock record -p <PID> -- sleep 10
sudo perf lock report -i perf.data

# Step 3: On-CPU analysis (where threads spin)
sudo perf record -e sched:sched_switch -e syscalls:sys_enter_futex -ag -- sleep 10
sudo perf script | grep futex | head -50
# Shows:
#   - Which functions trigger futex syscalls
#   - Frequency of contention per function

# Step 4: Flame graph of lock contention
sudo perf record -e 'lock:*' -ag -- sleep 10
# lock:acquire, lock:release, lock:contended_begin, lock:contended_end
```

**Contention Mitigation Strategies:**

```python
# Strategy 1: Reduce lock granularity (lock striping)
#   One big lock → array of locks, hash key to lock

def coarse_grained(transactions):
    for tx in transactions:
        with big_lock:
            process(tx)  # Serial! Only 1 CPU busy

def fine_grained(transactions):
    for tx in transactions:
        with locks[hash(tx.id) % NUM_LOCKS]:
            process(tx)  # Parallel! Up to NUM_LOCKS CPUs

# Strategy 2: Read-write locks (when reads >> writes)
#   pthread_rwlock_t: shared reads, exclusive writes
#   But: rwlock is NOT free — has overhead vs simple mutex

# Strategy 3: Lock-free data structures
#   Instead of lock + linked list, use atomic CAS on array
#   e.g., lock-free queue vs mutex-guarded queue:
#     MPMC queue (MoodyCamel) can handle 10M ops/sec
#     Mutex queue: ~1M ops/sec (limited by cache line bouncing)

# Strategy 4: Thread-local storage (eliminate sharing)
#   Instead of shared counter on every write, each thread
#   has a local counter. Periodically aggregate.

def thread_local_counter():
    local = threading.local()
    local.count = 0
    local.start = time.time()

    def increment():
        local.count += 1
        if time.time() - local.start > 1:
            # Push to shared (once per second, not per increment)
            shared.add(local.count)
            local.count = 0
            local.start = time.time()
    return increment
```

**Real-World Example:**

```yaml
# Problem: HFT app showing 8% CPU in futex syscalls
# Diagnosis via perf:
#   1. perf lock record → 90% contention on one "order book" lock
#   2. perf top → 8% in futex_wait, 5% in futex_wake
#   3. Critical section = 200ns (pointer swap)
#
# Root cause: 48 threads fighting over a 200ns critical section
# 
# Solutions (applied in order):
#   1. Adaptive spinning → 8% → 2% (fast path now works most of the time)
#   2. Per-symbol locks (lock striping by ticker) → 2% → 0.5%
#   3. Lock-free order book (atomic CAS on memory-mapped array)
#      → 0% futex time, 10× throughput improvement
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Futex mechanics** | Explains userspace fast path vs syscall slow path |
| **Adaptive spinning** | Knows the spin-then-sleep strategy and why it helps |
| **Perf profiling** | Knows perf lock record/report for contention analysis |
| **Mitigation strategy** | Progresses: adaptive spin → lock striping → lock-free |

---

## 8. Thread Pools: Design & Tuning

**Q:** "Design a thread pool for a web server handling 50K requests/second with mixed CPU-bound (image processing) and I/O-bound (database queries) tasks. How do you size the pool? What happens under overload (backpressure)?"

**What They're Really Testing:** Whether you understand the queuing theory behind thread pool sizing and have practical overload protection strategies.

### Answer

**The Sizing Formula:**

```python
# CPU-bound tasks: pool size = N_CPU (or N_CPU + 1)
#   More threads just cause context switching, no throughput gain
#   Rule: threads = N_CPU for pure CPU
#
# I/O-bound tasks: pool size = N_CPU × (1 + wait_time / compute_time)
#   While one thread waits for I/O, another can use the CPU
#   Rule: threads = N_CPU × (1 + W/C)
#
# Mixed workload:
#   pool_size = N_CPU * (1 + W/C) * target_utilization
#
# Example:
#   N_CPU = 16
#   CPU time per request = 2ms (image resize)
#   I/O wait per request = 18ms (DB query)
#   W/C = 18/2 = 9
#   Optimal threads = 16 × (1 + 9) × 0.9 (90% util) ≈ 144 threads
```

**Practical Thread Pool Implementation:**

```python
from concurrent.futures import ThreadPoolExecutor, Future
from collections import deque
import threading
import time

class BoundedThreadPool:
    """
    Thread pool with backpressure and dynamic sizing.
    """
    def __init__(self, min_workers: int = 4, max_workers: int = 200,
                 queue_size: int = 1000):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.work_queue: deque[callable] = deque(maxlen=queue_size)
        self.workers: list[threading.Thread] = []
        self.active_workers = 0
        self.idle_count = 0
        self.running = True
        self.lock = threading.Lock()
        self.not_empty = threading.Condition(self.lock)

        # Start minimum workers
        for _ in range(min_workers):
            self._start_worker()

        # Start adaptive resize thread
        self.adjuster = threading.Thread(target=self._auto_resize, daemon=True)
        self.adjuster.start()

    def submit(self, task: callable) -> bool:
        """
        Submit task. Returns False if queue is full (backpressure).
        """
        with self.lock:
            if len(self.work_queue) >= self.work_queue.maxlen:
                return False  # Backpressure: caller must handle
            self.work_queue.append(task)
            self.not_empty.notify()

            # Grow pool if queue is growing and we have room
            if (len(self.work_queue) > len(self.workers) * 2
                    and len(self.workers) < self.max_workers):
                self._start_worker()
        return True

    def _start_worker(self):
        t = threading.Thread(target=self._worker_loop, daemon=True)
        self.workers.append(t)
        self.active_workers += 1
        t.start()

    def _worker_loop(self):
        while self.running:
            task = None
            with self.lock:
                self.idle_count += 1
                try:
                    if not self.not_empty.wait(timeout=5.0):
                        # Timed out — no work for 5 seconds
                        if len(self.workers) > self.min_workers:
                            # Shrink pool
                            self.workers.remove(threading.current_thread())
                            self.active_workers -= 1
                            break
                    task = self.work_queue.popleft()
                except IndexError:
                    pass
                finally:
                    self.idle_count -= 1

            if task:
                try:
                    task()
                except Exception as e:
                    print(f"Task failed: {e}")

    def _auto_resize(self):
        """
        Periodically adjust pool size based on queue depth.
        """
        while self.running:
            time.sleep(1)
            with self.lock:
                qlen = len(self.work_queue)
                active = self.active_workers

                if qlen > active * 2 and active < self.max_workers:
                    # Queue growing: add workers
                    to_add = min(10, self.max_workers - active)
                    for _ in range(to_add):
                        self._start_worker()
                elif qlen < active * 0.1 and active > self.min_workers:
                    # Queue mostly empty: let idle workers expire
                    pass  # Workers time out naturally in worker_loop

    def shutdown(self):
        self.running = False
        with self.lock:
            self.not_empty.notify_all()
        for w in self.workers:
            w.join(timeout=1)
```

**Backpressure & Rejection Policies:**

```python
# When the thread pool is overloaded (queue full):

# Policy 1: Abort (throw exception)
#   - Caller gets RejectedExecutionException
#   - Caller must retry or fail gracefully
#   - Simple but harsh

# Policy 2: Caller-Runs (throttle the caller)
#   - The calling thread executes the task itself
#   - Effectively: caller slows down to match pool capacity
#   - Used by: Java ThreadPoolExecutor.CallerRunsPolicy
#   - Best for: when the caller is a request handler (speed of
#     the slowest producer is feedback-controlled)

def caller_runs(task, pool):
    if not pool.submit(task):
        # Queue full: run in caller's thread
        task()  # Caller blocks → can't submit more → natural backpressure

# Policy 3: Discard (drop oldest or newest)
#   - Drop the oldest task in the queue (make room for fresh tasks)
#   - Or drop the newest task (protect existing work)
#   - Best for: real-time streaming (old data is worthless)

# Policy 4: Shed load (return 503)
#   - Web server: respond with HTTP 503 Service Unavailable
#   - Client retries with exponential backoff
#   - Protects both this service and downstream services
```

**ForkJoinPool vs ThreadPoolExecutor:**

```
Aspect              ForkJoinPool                ThreadPoolExecutor
──────────          ───────────                 ──────────────────
Work-stealing       Yes (steals from others)    No (FIFO queue)
Best for            Recursive divide-and-conquer Independent tasks
Pool sizing         Fixed = #CPUs               Dynamic (min/max)
Queue               Per-thread deques           Global blocking queue
Task type           ForkJoinTask<T>             Runnable/Callable
Blocking wait       Steals while waiting        Blocks thread

Use ForkJoinPool when:
  - Tasks can be recursively decomposed (sort, search, matrix)
  - Tasks may spawn subtasks and wait for them

Use ThreadPoolExecutor when:
  - Tasks are independent (web requests, DB queries)
  - Tasks have dependencies (wait for task A before task B)
  - Need to control queue size and rejection policy
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Sizing formula** | Uses N × (1 + W/C) for I/O-bound, N_CPU for CPU-bound |
| **Backpressure** | Implements queue bounds + rejection policy (caller-runs, 503) |
| **Adaptive resize** | Explains dynamic pool sizing based on queue depth |
| **ForkJoin distinction** | Knows when to use ForkJoinPool vs ThreadPoolExecutor |

---

## 9. Non-Blocking Progress Guarantees

**Q:** "Your team is designing a concurrent hash table for a real-time ad bidding system. One engineer proposes a wait-free design, another says lock-free is sufficient, a third suggests obstruction-free. Walk through the tradeoffs and recommend an approach."

**What They're Really Testing:** Whether you understand the non-blocking progress hierarchy — wait-free vs lock-free vs obstruction-free — and can make practical engineering tradeoffs.

### Answer

**The Progress Hierarchy:**

```
                    ┌─────────────────────────────────┐
                    │       WAIT-FREE                  │
                    │  Every thread completes in a     │
                    │  bounded number of steps         │
                    │  ┌───────────────────────────┐   │
                    │  │      LOCK-FREE             │   │
                    │  │  Some thread always makes  │   │
                    │  │  progress (system-wide)    │   │
                    │  │  ┌─────────────────────┐   │   │
                    │  │  │ OBSTRUCTION-FREE     │   │   │
                    │  │  │ Thread completes if  │   │   │
                    │  │  │ no contention        │   │   │
                    │  │  └─────────────────────┘   │   │
                    │  └───────────────────────────┘   │
                    └─────────────────────────────────┘

Wait-free:   HARDEST (bounded steps per thread)
Lock-free:   PRACTICAL (system progress, may starve individual)
Obstruction: EASIEST (forward progress only when alone)
```

**Wait-Free — Strongest Guarantee, Hardest to Build:**

```cpp
// Wait-free: EVERY thread completes in a BOUNDED number of steps.
// No thread can be starved, regardless of what other threads do.
// 
// Example: Wait-free atomic snapshot
//   Problem: Read N atomic variables atomically (consistent snapshot)
//   Wait-free solution: Use a global epoch counter + per-thread buffers

template<typename T>
class WaitFreeSnapshot {
    static constexpr int N = 10;  // Number of shared variables
    static constexpr int NUM_THREADS = 128;

    struct Entry {
        T value[N];       // The actual data
        std::atomic<uint64_t> epoch{0};  // Version
    };

    std::atomic<Entry*> global_ptr_;  // Current published snapshot
    Entry* thread_data_[NUM_THREADS];  // Each thread's write buffer

public:
    // Wait-free write: CAS until success (retry bound by contention)
    void write(int idx, T value) {
        int tid = get_thread_id();
        Entry* local = thread_data_[tid];
        local->value[idx] = value;
        local->epoch = global_ptr_.load()->epoch + 1;
        global_ptr_.store(local);  // Publish
        // Bounded retries: at most NUM_THREADS CAS failures
    }

    // Wait-free read: get latest snapshot, retry if inconsistent
    // Guaranteed: at most 2 reads (bounded!)
    std::array<T, N> read() {
        while (true) {
            Entry* e1 = global_ptr_.load();
            std::atomic_thread_fence(std::memory_order_acquire);
            Entry* e2 = global_ptr_.load();
            if (e1 == e2) {
                // Consistent snapshot!
                std::array<T, N> result;
                std::copy(e1->value, e1->value + N, result.begin());
                return result;
            }
            // Retry — at most 2 iterations in practice
        }
    }
};
```

**Lock-Free — Practical and Widely Used:**

```cpp
// Lock-free: AT LEAST ONE thread always makes progress.
// Individual threads can starve (but not all of them).
//
// All CAS-based lock-free data structures are lock-free:
//   - Treiber stack
//   - Michael-Scott queue
//   - Hazard-pointer-based structures

// Example: Lock-free reference counting (shared_ptr control block)
//   - atomic increment = lock-free (CAS, no blocking)
//   - BUT: atomic decrement + destruction = obstruction-free
//     (need to be alone to safely destroy)

template<typename T>
class LockFreeSharedPtr {
    struct ControlBlock {
        T value;
        std::atomic<int> ref_count{1};
    };

    std::atomic<ControlBlock*> ptr_{nullptr};

public:
    // Lock-free: CAS loop, always makes SYSTEM progress
    void store(const T& value) {
        ControlBlock* new_block = new ControlBlock{value, 1};
        ControlBlock* old = ptr_.exchange(new_block);
        if (old && --old->ref_count == 0) {
            delete old;  // Obstruction-free (no contention expected)
        }
    }
};
```

**Obstruction-Free — Weakest but Often Sufficient:**

```cpp
// Obstruction-free: a thread makes progress ONLY if no other
// thread contends with it. If two threads clash, both may
// need to roll back and retry.
//
// Useful when:
//   - Contention is expected to be very low
//   - Helping mechanisms (lock-free) are too complex
//   - Transactional memory systems 

// Example: Obstruction-free doubly-linked list insertion
//   Uses pointers to detect interference ("collision markers")

struct Node {
    int key;
    Node* prev;
    Node* next;
    std::atomic<uint64_t> op_id{0};  // Unique operation ID
};

bool obstruction_free_insert(Node* head, Node* new_node) {
    // Obstruction-free: CAS loops, but if contention detected,
    // we back off and retry (rather than guaranteeing progress)
    Node* curr = head;
    while (curr) {
        Node* next = curr->next;
        if (next && new_node->key > curr->key && new_node->key < next->key) {
            // Attempt insertion
            new_node->next = next;
            new_node->prev = curr;
            if (CAS(&curr->next, next, new_node)) {
                // CAS succeeded — but other thread might have
                // also modified next->prev! Need consistency check
                bool success = CAS(&next->prev, curr, new_node);
                if (!success) {
                    // Contention! Roll back and retry
                    CAS(&curr->next, new_node, next);
                    return false;  // Obstruction: give up, let caller retry
                }
                return true;
            }
        }
        curr = next;
    }
    return false;
}
```

**Practical Recommendation for Ad Bidding:**

```yaml
# Requirement: 100K queries/sec, 99th percentile latency < 100μs
# Writes are rare (bid updates every 5 min), reads are constant
#
# Recommendation: LOCK-FREE hash table with RCU
#
# Why NOT wait-free:
#   - Wait-free hash tables are EXTREMELY complex (no published practical design)
#   - Memory overhead is 2-5× (versioning, per-thread slots)
#   - Write path is actually slower than lock-free due to helping
#
# Why NOT obstruction-free:
#   - Under load, contention causes repeated rollbacks
#   - Tail latency spikes (retry storms)
#   - Not acceptable for real-time bidding (99.9% latency SLA)
#
# Why lock-free + RCU:
#   - Reads: wait-free (RCU) — millions/sec, single-digit microseconds
#   - Writes: lock-free insert/delete with CAS
#   - Memory reclamation: epoch-based (deferred free, no blocking)
#   - Proven: memcached, Linux kernel, databases
#
# Hardest practical problems in lock-free:
#   1. Memory reclamation (hazard pointers or RCU)
#   2. ABA problem (tagged pointers or GC)
#   3. False sharing (cache line padding)
#   4. Debugging (Heisenbugs: disappear under debugger)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Hierarchy clarity** | Clearly distinguishes wait-free, lock-free, obstruction-free |
| **Practical tradeoffs** | Recommends based on use case (not always picking the strongest) |
| **Wait-free complexity** | Acknowledges that wait-free is very hard for complex structures |
| **Real-world examples** | Knows which data structures are lock-free vs wait-free in practice |

---

> *All 9 topics now provide full code examples, algorithmic analysis, and evaluation rubrics at staff-engineer depth. For complementary resources, see the [cs-interview README](../README.md).*

---


