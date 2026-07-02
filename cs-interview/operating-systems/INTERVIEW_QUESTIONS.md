# 🧠 Operating Systems — Staff-Level Interview Questions

> *12 questions covering memory management, process scheduling, I/O models, file systems, and kernel internals — every question expects production-scale reasoning.*

---

## Table of Contents

1. [Virtual Memory & Page Tables](#1-virtual-memory--page-tables)
2. [TLB & Huge Pages](#2-tlb--huge-pages)
3. [Process Scheduling (CFS)](#3-process-scheduling-cfs)
4. [Context Switch Cost](#4-context-switch-cost)
5. [I/O Models: epoll, io_uring, kqueue](#5-io-models-epoll-io_uring-kqueue)
6. [Memory Allocation: malloc to mmap](#6-memory-allocation-malloc-to-mmap)
7. [Page Cache & Buffer Cache](#7-page-cache--buffer-cache)
8. [File Systems: ext4 vs xfs vs btrfs](#8-file-systems-ext4-vs-xfs-vs-btrfs)
9. [IPC Mechanisms](#9-ipc-mechanisms)
10. [Signals & Async Signal Safety](#10-signals--async-signal-safety)
11. [cgroups & Namespaces (Container Isolation)](#11-cgroups--namespaces-container-isolation)
12. [OOM Killer & Memory Overcommit](#12-oom-killer--memory-overcommit)

---

## 1. Virtual Memory & Page Tables

**Q:** "Design a page table structure for a 64-bit system with 4KB pages. How does a 4-level page table work, and why can't we use a simple flat page table? How do we handle the case where the virtual address space is sparse?"

**What They're Really Testing:** Whether you understand that `2^64 / 4KB = 2^52` entries is impossible, and whether you've thought about memory-efficient address translation in real systems.

### Answer

**The Math Problem:**
- 64-bit VA space = 2^64 bytes = 16 exabytes
- 4KB pages = 2^12 bytes/page
- Flat page table would need: 2^64 / 2^12 = 2^52 entries
- Each entry = 8 bytes → 2^52 × 8 = 2^55 bytes = **32 petabytes** per process
- Impossible.

**4-Level Page Table Solution:**

```
VA Bits: [47:39] | [38:30] | [29:21] | [20:12] | [11:0]
            L4        L3        L2        L1      offset
```

```
                    ┌──────────┐
                    │ L4 Table │ ← 512 entries (9 bits)
                    │  (1 page)│
                    └────┬─────┘
                         │ index
                    ┌────▼─────┐
                    │ L3 Table │ ← only allocated for used regions
                    │  (1 page)│
                    └────┬─────┘
                    ┌────▼─────┐
                    │ L2 Table │ ← only allocated where needed
                    │  (1 page)│
                    └────┬─────┘
                    ┌────▼─────┐
                    │ L1 Table │ ← maps to physical pages
                    │  (1 page)│
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │ Physical │
                    │   Page   │
                    └──────────┘
```

**Sparse Address Space Efficiency:**
- Each level table is exactly 1 page (4KB)
- 512 entries × 8 bytes = 4KB (fits perfectly)
- If a region is unmapped, the intermediate table pointer is NULL → entire subtree consumes zero memory
- A process using 1GB of heap in a single contiguous region needs only:
  - 1 × L4 table
  - 1 × L3 table
  - 8 × L2 tables (each covers 1GB/512 = 2MB)
  - ~512 × L1 tables
  - Total overhead: ~2MB for page tables, not 32PB

**Five-Level Page Tables (Ice Lake+):**
- Intel/AMD added a 5th level (57-bit VA) for systems with >64TB physical RAM
- Adds [56:48] level, making 512 × 512 × 512 × 512 × 512 mapping

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Scale intuition** | Can immediately compute why flat page tables don't work |
| **Sparse efficiency** | Explains that unused regions consume zero page table memory |
| **TLB miss cost** | Understands that 4-level walk = 4 DRAM accesses (~40ns) without TLB |
| **Page size trade-offs** | Knows 4KB vs 2MB vs 1GB pages and when to use each |

---

## 2. TLB & Huge Pages

**Q:** "Our Redis instance is seeing 8% CPU time in TLB miss handling. Diagnose the root cause and propose a solution. Walk me through the numbers."

**What They're Really Testing:** Quantitative reasoning about TLB coverage and whether you understand huge pages as a practical optimization.

### Answer

**Root Cause Diagnosis:**

```
Single Redis process:
- Working set: ~12GB (all data in memory)
- Page size: 4KB
- Pages accessed per operation: ~1M in worst case (BGSAVE + read workload)
- TLB entries (modern x86):
  - L1 DTLB: 64 entries
  - L2 TLB: 1536 entries
- TLB coverage at 4KB: 64 × 4KB = 256KB (L1) + 1536 × 4KB = 6MB (L2)
- Total TLB covers: ~6MB of 12GB = 0.05% of working set
```

Every Redis operation touches pointers scattered across the 12GB heap. With only 6MB of TLB coverage, virtually every memory access misses the TLB and requires a 4-level page table walk (4 DRAM accesses = ~40ns per miss).

**Solution: Huge Pages (2MB)**

```bash
# Enable Transparent Huge Pages (THP) — but be careful
echo always > /sys/kernel/mm/transparent_hugepage/enabled

# Or use explicit huge pages for Redis
echo 6000 > /proc/sys/vm/nr_hugepages  # 6000 × 2MB = 12GB
```

**New TLB Coverage with 2MB Pages:**

```
- L1 DTLB: 64 × 2MB = 128MB
- L2 TLB: 1536 × 2MB = 3GB
- Total TLB coverage: ~3GB of 12GB = 25% (vs 0.05%)
```

**Redis-Specific Guidance:**
- Redis < 4.0 had issues with THP because copy-on-write on fork() would fragment huge pages
- Redis 4.0+ uses `THP` correctly with `fork()` using `madvise` mode
- For Redis ≥ 6.0, explicit 2MB huge pages via libc `malloc` arena = 30-40% throughput improvement

**Trade-Off:**
- Huge pages increase internal fragmentation (wasted memory within the last page)
- For Redis with 12GB, worst case = 12GB / 2MB × 2MB/2 = 6MB waste → negligible

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Quantitative** | Actual TLB entry counts, coverage calculations |
| **Redis expertise** | Knows about fork()+THP fragmentation issue historically |
| **Fractional vs explicit** | Understands THP madvise/always/never modes |
| **Trade-off** | Mentions compaction overhead and swap size constraints |

---

## 3. Process Scheduling (CFS)

**Q:** "Walk me through how the Linux Completely Fair Scheduler (CFS) works. If I have 4 CPU cores and 8 CPU-bound threads, how does CFS decide who runs when? How does it handle priority (nice values)?"

**What They're Really Testing:** Whether you understand that modern schedulers use weighted fair queuing, not simple round-robin, and whether you know the data structures involved.

### Answer

**CFS Core Idea: "Perfect multitasking is impossible, so approximate it."**

If we had 4 CPUs and 8 threads, ideal scheduling would give each thread exactly 50% of a CPU. CFS models this using **virtual runtime (vruntime)**.

```
vruntime = actual_runtime × (weight₀ / weight_thread)
         = actual_runtime × (1024 / weight)
```

Where `weight` for `nice=0` is 1024 (the baseline).

**Data Structure: Red-Black Tree (per-CPU runqueue)**

```
      ┌──────────────────────────┐
      │     CFS Runqueue         │
      │     (RB-Tree keyed       │
      │      by vruntime)        │
      │                          │
      │        ┌───┐            │
      │        │min│◄──── pick   │
      │        │vrun│   first    │
      │       ┌┴───┴┐           │
      │   ┌───┤     ├───┐       │
      │  ┌┴┐ ┌┴┐   ┌┴┐ ┌┴┐     │
      │  │ │ │ │   │ │ │ │      │
      └──┴─┴─┴─┴───┴─┴─┴─┘────┘
```

**Scheduling Decision (simplified code):**

```c
// Every tick (~1ms on typical config)
void scheduler_tick(struct task_struct *p) {
    // 1. Update p's actual runtime
    p->se.sum_exec_runtime += delta;

    // 2. Calculate vruntime delta
    u64 delta_vruntime = calc_delta_fair(delta, &p->se);
    p->se.vruntime += delta_vruntime;

    // 3. Re-insert into red-black tree
    //    (might change position if vruntime increased enough)
    rb_erase(&p->se.run_node, &rq->cfs.tasks_timeline);
    rb_insert(&p->se.run_node, &rq->cfs.tasks_timeline);
}

void schedule() {
    struct task_struct *next;
    struct rb_node *leftmost;

    // Pick the thread with minimum vruntime
    leftmost = rb_first(&rq->cfs.tasks_timeline);
    next = rb_entry(leftmost, struct task_struct, se.run_node);

    // Context switch to 'next'
    context_switch(rq->curr, next);
}
```

**Nice Value Effect:**

| nice | weight | Relative share |
|------|--------|----------------|
| -20  | 88761  | 88761/1024 ≈ 86.7× of nice=0 |
| -10  | 9548   | 9548/1024 ≈ 9.3× |
| 0    | 1024   | Baseline |
| 10   | 110    | 1024/110 ≈ 9.3% of nice=0 |
| 19   | 15     | 1024/15 ≈ 1.5% of nice=0 |

A `nice -20` thread doesn't get 86.7× more CPU — it gets **proportionally weighted** CPU. If two threads (nice=0 and nice=-20) compete on one CPU:
- nice=-20 gets: 88761/(88761+1024) = 98.9% CPU
- nice=0 gets: 1024/(88761+1024) = 1.1% CPU

**Load Balancing:**
- CFS runs `load_balance()` every ~1ms or when a CPU goes idle
- Pulls tasks from the busiest runqueue using `find_busiest_group()` and `find_busiest_queue()`
- Uses a multi-level domain hierarchy: SMT → CORE → MC → NUMA → NUMA-other

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **vruntime** | Explains the weighted fair queuing concept clearly |
| **RB-tree** | Knows why O(log n) is acceptable (< 1K threads) and EEVDF in newer kernels |
| **Nice math** | Can calculate proportional shares for different nice values |
| **Load balancing** | Mentions pull vs push, domain hierarchy, active vs idle balancing |

---

## 4. Context Switch Cost

**Q:** "Estimate the cost of a context switch between two processes on a modern x86 CPU. Break down the components. How would you measure it in production?"

**What They're Really Testing:** Whether you understand that context switching is more than just register saves — it's a TLB/cache demolition event.

### Answer

**Components of Context Switch Cost:**

```
1. Mode switch (user→kernel)         ~100ns
2. Save registers (FPU/SIMD state)   ~200ns  (XSAVE takes longer with AVX-512)
3. Switch kernel stack                ~10ns
4. Switch page table (CR3 write)     ~50ns   ← This TLB flushes everything!
5. Schedule() decision                ~100ns  (RB-tree lookup)
6. Restore registers (XRSTOR)        ~200ns
7. Mode switch (kernel→user)         ~100ns
8. TLB/cache warmup                  ~1-10µs (cold cache, worst-case)

Total direct cost:       ~760ns (without cache effects)
Total effective cost:    ~1-10µs (with TLB/cache miss penalty)
```

**Why Context Switching Is Expensive — The TLB Angle:**

```c
// Process A runs → TLB full of A's mappings
// Context switch to B:
write_cr3(B's_page_table);

// On next A's memory access: TLB has NOTHING for A
// Every address → 4-level page table walk → 4 DRAM accesses
// If A's working set is 4MB and 4KB pages:
//   ~1000 TLB misses × ~40ns each = ~40µs of page walks
//   Before: those were cached in TLB (~1ns per translation)
```

**L1/L2 Cache Devastation:**
- L1 cache: 32KB — completely contaminated after switch
- L2 cache: 1MB — mostly contaminated
- L3 cache: typically shared (LLC), but if A runs on different core: cold
- Cache miss: L1 ~4ns, L2 ~12ns, L3 ~40ns, DRAM ~100ns

**Measuring in Production:**

```c
// Use perf to measure context switch cost directly
// perf stat -e context-switches,cpu-migrations,cycles ./workload

// Or trace context switches with eBPF:
// bpftrace -e 'kprobe:finish_task_switch { @start = nsecs; }
//              kretprobe:finish_task_switch { @latency = hist(nsecs - @start); }'
```

**Practical implications:**
- Thread pool with N threads on M CPUs: keep N ≈ M (no over-subscription)
- Async I/O (io_uring) eliminates context switches entirely for I/O workloads
- Busy-wait spinning (spinlock) can outperform mutex if wait time < context switch cost (~1µs)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **TLB awareness** | The CR3 write + TLB flush is the dominant cost |
| **Measurement** | Can use perf/eBPF to measure, not just theoretical |
| **Cache hierarchy** | Breaks down L1/L2/L3/DRAM for each component |
| **practical** | Knows when context switching is worth avoiding |

---

## 5. I/O Models: epoll, io_uring, kqueue

**Q:** "Compare select, poll, epoll, and io_uring for a high-throughput TCP server handling 100K concurrent connections. What are the internal data structures? Why was io_uring a paradigm shift?"

**What They're Really Testing:** Whether you understand the evolution of I/O in the kernel — from O(n) scanning to O(1) event-driven to submission-queue async.

### Answer

**Evolution of I/O Models:**

| Model | Year | Complexity | Syscalls per event | Copy |
|-------|------|-----------|-------------------|------|
| `select` | 1983 | O(n) | 1 | Kernel→userspace (all fds) |
| `poll` | 1997 | O(n) | 1 | Kernel→userspace (all fds) |
| `epoll` | 2002 | O(1) | 1 + 1 setup | Kernel→userspace (ready fds) |
| `io_uring` | 2019 | O(0)* | 0 (shared ring) | Zero-copy (shared memory) |

*For submission, not completion notification.

**epoll Internals:**

```
                    ┌──────────────┐
                    │   epoll      │
                    │  instance    │
                    │              │
                    │  RB-Tree     │ ← O(log n) add/remove monitored fds
                    │  (all fds)   │
                    │              │
                    │  Ready List  │ ← Double-linked list of ready fds
                    │  (ready fds) │     O(1) epoll_wait return
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────▼───┐  ┌────▼───┐  ┌────▼───┐
         │ socket │  │ socket │  │ socket │
         │   fd   │  │   fd   │  │   fd   │
         └────────┘  └────────┘  └────────┘
```

```c
// epoll data structures (kernel)
struct eventpoll {
    struct rb_root_cached rbr;    // RB-Tree — all monitored fds
    struct list_head rdllist;      // Ready list — fds with events
    wait_queue_head_t wq;          // Wait queue — blocked epoll_wait callers
};

struct epitem {
    struct rb_node rbn;            // RB-Tree node
    struct list_head rdllink;      // Ready list link
    struct epoll_filefd ffd;       // The fd being monitored
    struct eventpoll *ep;          // Back-pointer to owning epoll
    struct epoll_event event;      // The events of interest
};
```

**The Problem with epoll:**

```c
// Every event still requires system calls:
void event_loop() {
    struct epoll_event events[1024];
    while (1) {
        int n = epoll_wait(epfd, events, 1024, -1);  // 1 syscall
        for (int i = 0; i < n; i++) {
            if (events[i].events & EPOLLIN) {
                read(events[i].data.fd, buf, 4096);    // 1+ syscalls per event
                process(buf);                           // application logic
            }
        }
    }
}
```

Each `read()` is a separate syscall → user→kernel→user transition (~100ns each).

**io_uring — The Paradigm Shift:**

```
                   Submission Queue (SQ)          Completion Queue (CQ)
                   ┌──────────────────┐           ┌──────────────────┐
User writes ───────►│  SQE  │  SQE    │           │  CQE  │  CQE    │
to SQ ring          ├──────┼────────┤           ├──────┼────────┤
                   │  SQE  │  SQE    │           │  CQE  │  CQE    │
                   ├──────┼────────┤           ├──────┼────────┤
                   │ ...  │         │           │ ...  │         │
                   └──────────┬───────┘           └──────────┬───────┘
                              │                              │
                              │ kernel                       │
                              │ processes                    │
                              │ in batches                   │
                              ▼                              ▼
                        Kernel processes           User reads
                        SQ entries →               completed
                        I/O operations              CQ entries
```

```c
// io_uring — zero syscall per I/O operation
struct io_uring ring;
io_uring_queue_init(4096, &ring, 0);    // 2 syscalls (mmap + setup)

// Submit 100 read operations with NO syscalls:
struct io_uring_sqe *sqe;
for (int i = 0; i < 100; i++) {
    sqe = io_uring_get_sqe(&ring);                 // Get next SQE (user-space)
    io_uring_prep_read(sqe, fds[i], bufs[i], 4096, 0);  // Fill SQE (user-space)
}
io_uring_submit(&ring);   // 1 syscall for 100 operations ← HUGE WIN

// Reap completions:
struct io_uring_cqe *cqe;
while (1 - io_uring_peek_cqe(&ring, &cqe)) {   // No syscall if events ready
    // process(cqe);
    io_uring_cqe_seen(&ring, cqe);
}
```

**Why io_uring Is a Paradigm Shift:**
1. **Batched submission/reaping** — one syscall amortizes 100s of operations
2. **Zero-copy** — SQ/CQ rings are shared memory between kernel and userspace
3. **Asynchronous deep** — `read()` doesn't block even for page cache misses (kernel handles it)
4. **No O_NONBLOCK required** — io_uring handles blocking internally
5. **File system operations** — `openat()`, `statx()`, `rename()` all async (epoll can't do this)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Data structures** | RB-tree + ready list for epoll; shared ring buffers for io_uring |
| **Syscall cost awareness** | Knows each syscall is ~100ns, batch = free |
| **io_uring depth** | Understands SQ/CQ ring semantics, IORING_SETUP_IOPOLL |
| **Practical limitations** | Knows epoll still used when io_uring overkill (simple servers) |

---

## 6. Memory Allocation: malloc to mmap

**Q:** "Trace the path of a `malloc(512)` call from user-space library to physical RAM. When does `sbrk` vs `mmap` get used? What fragmentation patterns arise?"

**What They're Really Testing:** Whether you understand the entire memory allocation stack — from glibc arena allocator through brk/mmap to the kernel's page allocator (buddy system).

### Answer

**The Full Stack:**

```
malloc(512)
    │
    ▼
┌─────────────────────────────────┐
│   glibc malloc (ptmalloc3)      │
│   • Thread-local cache (tcache) │  ← Service from here if hot
│   • Fastbins (16-96 bytes)      │
│   • Small bins                   │
│   • Unsorted bin                 │
│   • Large bins (LIFO best-fit)  │
└────────────────┬────────────────┘
                 │ arena lock (if cross-thread)
                 ▼
┌─────────────────────────────────┐
│   brk() / sbrk()   or   mmap()  │
│                                 │
│   < 128KB: sbrk (heap growth)  │
│   ≥ 128KB: mmap (anonymous)     │
└────────────────┬────────────────┘
                 ▼
┌─────────────────────────────────┐
│   Kernel Page Allocator         │
│   (Buddy System — 2^n pages)    │
│   • Zone Normal / DMA           │
│   • Watermark: min/low/high    │
│   • Compaction / reclaim        │
└────────────────┬────────────────┘
                 ▼
              Physical RAM
```

**Detailed Path for `malloc(512)`:**

```c
void *p = malloc(512);

// Step 1: tcache (per-thread cache, since glibc 2.26+)
//   - 64 bins × up to 7 entries each
//   - Lock-free (!) — uses TLS pointer
//   - If tcache[bin_for(512)] is not empty:
//       return pop(tcache[bin_for(512)]);
//   - Otherwise: fall through

// Step 2: Check fastbin (16-96 bytes, LIFO)
//   512 bytes → too large for fastbin

// Step 3: Check small bin (exact size match)
//   - If matching chunk found: return it
//   - Otherwise: consolidate adjacent free chunks (coalescing)

// Step 4: Check unsorted bin
//   - Recent free() chunks land here first
//   - If exact match found: return
//   - Otherwise: sort into small/large bins

// Step 5: Check large bins (best-fit search)
//   - O(n) search for smallest chunk ≥ 512 bytes

// Step 6: Extend heap via sbrk(512 + overhead)
//   - Kernel finds free physical pages
//   - Maps them into process address space
//   - Splits into desired chunk
//   - Returns pointer
```

**sbrk vs mmap Decision:**

| Factor | sbrk (heap) | mmap (anonymous) |
|--------|-------------|------------------|
| Threshold | < 128KB | ≥ 128KB (or mmap_threshold) |
| Reclaim | Can't return to OS (contiguous) | `munmap` immediately releases |
| Fragmentation | Internal + external | None (each mmap is independent) |
| TLB | Nearby allocations share pages | Each mmap is at random address |
| Cost | O(1) | O(n) page table manipulation |

**Fragmentation Patterns:**

```
Before (after alloc/free cycles):
│████░░░░████░░░░████░░░░│  ← External fragmentation
│  FFFF  │  FFFF  │  FFFF │  ← Free chunks too small to use
└────────────────────────┘

Internal fragmentation:
│  malloc(1) → 4KB page → 4095 bytes wasted │  ← Internal fragmentation

Chunk header overhead:
│ 8-byte header │ 512-byte payload │ 8-byte canary │
                                                 ↑ Glibc uses this for
                                                   consolidation info
```

**Production Mitigations:**
- `jemalloc` / `tcmalloc` — arena-based, reduces fragmentation, better multi-threaded perf
- `MALLOC_ARENA_MAX=4` — limit glibc arenas to reduce VMA count
- Huge pages — 2MB reduces page-level fragmentation
- Memory pools for fixed-size allocations (no fragmentation at all)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stack depth** | Traces through tcache → bins → brk/mmap → buddy → physical |
| **Thresholds** | Knows 128KB mmap threshold, tcache bin count |
| **Fragmentation** | Distinguishes internal vs external, can draw it |
| **Tooling** | Can use `pmap`, `/proc/self/smaps`, `malloc_stats()` to diagnose |

---

## 7. Page Cache & Buffer Cache

**Q:** "A MySQL instance on Linux is reading 10GB of data from disk. Trace the path from `pread()` system call to the disk and back. Where does the page cache sit? How does `direct I/O` change things?"

**What They're Really Testing:** Understanding of the block I/O layer, page cache, and how database engines interact with the OS.

### Answer

**The Path of a `pread()`:**

```
pread(fd, buf, 4096, offset)

    │
    ▼
┌─────────────────────┐
│   VFS Layer          │
│ (virtual file system)│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Page Cache         │ ◄── Check if page is already cached
│   (radix tree /      │
│    xarray keyed by   │
│    inode + offset)   │
│                      │
│   ┌──────────┐      │
│   │ 4KB page │      │  ← Hit: copy to user buffer, zero-copy!
│   │  (cached)│      │     No disk I/O needed
│   └──────────┘      │
│                      │
│   ┌──────────┐      │
│   │ 4KB page │      │  ← Miss: need I/O
│   │ (empty)  │      │
│   └──────────┘      │
└─────────┬───────────┘
          │ (page miss)
          ▼
┌─────────────────────┐
│   File System        │  ← ext4, xfs, btrfs
│   (extents / inodes) │
│                      │
│   Maps file offset   │
│   → logical block # │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Block Layer        │
│   (I/O scheduler)    │
│                      │
│   • Merge adjacent   │
│   • Sort elevator    │
│   • Plug/unplug      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Device Driver      │
│   (NVMe / AHCI)     │
│                      │
│   • DMA setup        │
│   • Interrupt or     │
│     polling           │
└─────────┬───────────┘
          │
          ▼
         ╔══════╗
         ║ Disk ║  ← Actual I/O (~10μs NVMe, ~5ms HDD)
         ╚══════╝
```

**Page Cache Anatomy:**

```c
struct address_space {  // embedded in every inode
    struct xarray i_pages;          // Page cache (radix tree replacement)
    struct rb_root_cached i_mmap;   // Memory-mapped pages
    const struct address_space_operations *a_ops;
    unsigned long nrpages;          // Total cached pages
};

struct page {
    unsigned long flags;            // PG_dirty, PG_uptodate, PG_locked...
    struct address_space *mapping;  // Backing address_space
    pgoff_t index;                  // Page index within the file
    void *private;                  // Filesystem-specific data
    // ... union with LRU lists, swap entries...
};
```

**The Page Cache as a Read/Write Buffer:**

```
         Application
         read()/write()
             │
             ▼
      ┌──────────────┐
      │  Page Cache   │ ◄── Writes go here first (write-back cache)
      │  (dirty pages) │
      └──────┬───────┘
             │ pdflush/flusher threads
             │ (controlled by /proc/sys/vm/dirty_*)
             ▼
      ┌──────────────┐
      │   Disk I/O    │
      └──────────────┘
```

**Key tunables:**
- `dirty_background_ratio` (default 10%) — start writing in background
- `dirty_ratio` (default 20%) — force synchronous writes (processes block!)
- `dirty_expire_centisecs` (default 3000 = 30s) — max age of dirty page
- `dirty_writeback_centisecs` (default 500 = 5s) — flusher wake interval

**Direct I/O (O_DIRECT):**

```c
// MySQL uses O_DIRECT for InnoDB data files
fd = open("ibdata1", O_RDWR | O_DIRECT);

pread(fd, buf, 4096, offset);
```

With direct I/O:
```
pread() → VFS → File System → Block Layer → Disk
                        ↑
                   SKIPS page cache!
```

**Why databases use direct I/O:** Double buffering — if MySQL maintains its own buffer pool (InnoDB buffer pool), the page cache just duplicates data. MySQL knows its access patterns better (e.g., sequential scan eviction policy vs LRU).

**Trade-off:**
- Page cache = OS manages caching for all processes (simple)
- Direct I/O = app manages caching (more control, more complexity)
- MySQL: uses O_DIRECT for data files, page cache for logs (sequential writes benefit from write-back)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Full path** | VFS → page cache → FS → block → driver → disk |
| **Dirty page mechanics** | Explains flusher threads, dirty ratios, blocking behavior |
| **Database expertise** | Knows why DBs use O_DIRECT (no double buffering) |
| **xarray** | Knows radix tree → xarray change in recent kernels |

---

## 8. File Systems: ext4 vs xfs vs btrfs

**Q:** "You're designing the storage stack for a high-traffic image hosting service. Compare ext4, XFS, and btrfs for this use case. Which one would you pick and why?"

**What They're Really Testing:** Whether you understand file system internals (allocation, journaling, checksums) at sufficient depth to make a production decision.

### Answer

**Quick Comparison:**

| Feature | ext4 | XFS | btrfs |
|---------|------|-----|-------|
| Allocator | extents (4KB+ contiguous) | B+ tree extents | Copy-on-Write B-tree |
| Journal | Journal (metadata) | Log (metadata) | No journal (COW) |
| Max fs size | 1 exabyte | 8 exabytes | 16 exabytes |
| Max file size | 16 TB | 8 exabytes | 16 exabytes |
| Subvolumes | No | No | Yes |
| Snapshots | No | No | Yes (COW) |
| Checksums | Metadata only | Metadata only | Data + metadata (CRC32C) |
| Defrag | Offline | Online (xfs_fsr) | Online (btrfs filesystem defrag) |
| RAID | No (mdadm) | No (mdadm/LVM) | RAID0/1/5/6/10 native |
| Dedup | No | No | Yes (offline) |
| Compression | No | No | Yes (zlib/lzo/zstd) |

**Image Hosting Workload Profile:**
- Large files (500KB–10MB per image)
- Write-once, read-many (90:10 read ratio)
- No overwrites (immutable images)
- Snapshots for backup
- Possible dedup if users upload the same image

**XFS — The Pick for Image Hosting:**

```
XFS Allocation Groups (AG):
┌─────────────────────────────────────┐
│ AG 0    │ AG 1    │ AG 2    │ AG 3  │
│ (4GB)   │ (4GB)   │ (4GB)   │ (4GB) │
├─────────┼─────────┼─────────┼─────────┤
│ S  B  I  │ S  B  I  │ S  B  I  │ S  B  I │
│ u  l  n  │ u  l  n  │ u  l  n  │ u  l  n │
│ p  o  o  │ p  o  o  │ p  o  o  │ p  o  o │
│ e  c  d  │ e  c  d  │ e  c  d  │ e  c  d │
│ r  k  e  │ r  k  e  │ r  k  e  │ r  k  e │
│ b     s  │ b     s  │ b     s  │ b     s  │
│ l        │ l        │ l        │ l        │
│ o        │ o        │ o        │ o        │
│ c        │ c        │ c        │ c        │
│ k        │ k        │ k        │ k        │
└─────────┴─────────┴─────────┴─────────┘
Key: S=Superblock, B=B+Tree, I=Inode
```

**Why XFS Wins Here:**

1. **Parallel allocation** — Allocation groups = independent allocators. 8 concurrent image uploads don't contend.

2. **Extent-based allocation** — A 10MB image file is stored as a single extent (or a few). No fragmentation. Fast sequential reads.

3. **Delayed allocation** — XFS buffers writes up to 30s before allocating blocks. This lets it see the final file size and allocate a single contiguous extent.

```c
// XFS delayed allocation example:
write(fd, image_data_1, 5MB);    // XFS: "hmm, I'll wait"
write(fd, image_data_2, 5MB);    // XFS: "10MB total, got it"
// 30s later OR fsync():
// XFS allocates ONE 10MB extent contiguous on disk
// This is MUCH faster than writing 2 extents separated by other writes
```

4. **Efficient metadata** — B+ tree extents mean O(log n) lookup even for 100TB filesystems. ext4 uses HTree for directories (hash table with overflow B-tree).

**btrfs — Better for Some Cases:**

```c
// If you need snapshots and compression:
btrfs subvolume snapshot /images /backups/$(date +%Y%m%d)
// Instant! ~0 seconds, uses COW to share unchanged blocks
// Only tracks blocks that differ from previous snapshot

// Compression (zstd is fast enough for images):
mount -o compress=zstd /dev/sdb /images
// Compresses images transparently
// PNG/JPEG already compressed → minimal gain (~5% savings)
```

**ext4 — When You Need Simplicity:**
- Most battle-tested (since 2008)
- Every distro supports it
- fsck is reliable
- Best for embedded/boot partitions

**Verdict for Image Hosting:** XFS. For workloads where files are large, mostly append/read, and concurrent, XFS's allocation groups and delayed allocation crush ext4. btrfs is only worth the complexity if you need native snapshots/compression.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Allocation awareness** | Explains how delayed allocation creates contiguous extents |
| **Parallelism** | Knows XFS AGs = no lock contention on parallel writes |
| **COW** | Understands snapshot mechanics for btrfs |
| **Real trade-offs** | Doesn't choose btrfs for everything — knows where each excels |

---

## 9. IPC Mechanisms

**Q:** "Design an inter-process communication channel between a high-frequency trading engine (latency-critical, in C++) and a risk management service (in Go). Compare pipes, Unix domain sockets, shared memory, and message queues. Which would you use?"

**What They're Really Testing:** Whether you understand the latency characteristics of each IPC mechanism and when zero-copy shared memory justifies its complexity.

### Answer

**IPC Comparison:**

| Mechanism | Latency | Throughput | Complexity | Use Case |
|-----------|---------|-----------|------------|----------|
| Pipe | ~3-5µs | ~500MB/s | Trivial | Parent-child, small messages |
| Unix socket | ~5-10µs | ~1GB/s | Low | Network-style, cross-language |
| Shared memory | ~100ns | ~100GB/s | High | HFT, massive data |
| Message queue | ~50-200µs | ~100MB/s | Medium | Async, durable messaging |

**Shared Memory Design for HFT:**

```
┌─────────────────── Shared Memory Segment (mmap) ───────────────────┐
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                   Ring Buffer Header                         │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │  │
│  │  │ read_pos │  │ write_pos│  │  magic   │  │  flags   │   │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    Ring Buffer (Slots)                       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐           ┌────────┐     │  │
│  │  │slot 0  │ │slot 1  │ │slot 2  │    ...     │slot N  │     │  │
│  │  │ 128B   │ │ 128B   │ │ 128B   │           │ 128B   │     │  │
│  │  └────────┘ └────────┘ └────────┘           └────────┘     │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

```c
// C++ Trading Engine — Producer
struct RingBufferHeader {
    volatile uint64_t read_pos __attribute__((aligned(64)));
    volatile uint64_t write_pos __attribute__((aligned(64)));
    uint64_t capacity;
};

struct Order {
    int64_t order_id;
    uint32_t symbol;
    uint64_t price;
    uint64_t quantity;
    uint8_t side;       // 0=buy, 1=sell
    uint8_t order_type; // 0=market, 1=limit
};

class ShmPublisher {
    RingBufferHeader *hdr_;
    char *slots_;
    int shm_fd_;

public:
    bool publish(const Order &order) {
        uint64_t pos = hdr_->write_pos;
        uint64_t next = (pos + 1) & (hdr_->capacity - 1);

        // Spin if full (busy-wait — acceptable for HFT with low latency)
        while (next == hdr_->read_pos) {
            _mm_pause();  // PAUSE instruction — yield to hyperthread
        }

        // Copy order to slot (atomic 128-byte write)
        memcpy(slots_ + pos * sizeof(Order), &order, sizeof(Order));

        // Memory barrier — ensure write is visible to reader
        __sync_synchronize();

        // Advance write position (atomic)
        hdr_->write_pos = next;
        return true;
    }
};
```

```go
// Go Risk Manager — Consumer
func (c *ShmConsumer) consume(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        default:
            pos := atomic.LoadUint64(&c.hdr.read_pos)
            writePos := atomic.LoadUint64(&c.hdr.write_pos)

            if pos == writePos {
                // No data — yield to OS
                runtime.Gosched()
                continue
            }

            // Read order directly from shared memory (zero copy!)
            order := (*Order)(unsafe.Pointer(
                &c.slots[pos*c.orderSize],
            ))

            c.riskCheck(order)

            // Advance read position
            atomic.StoreUint64(&c.hdr.read_pos, (pos+1)&(c.capacity-1))
        }
    }
}
```

**Why Not Pipes/Sockets for HFT:**
- Pipe: each message = copy from user→kernel→user = 2 context switches
- Socket: same as pipe + protocol overhead (TCP headers, ACKs)
- Both: limited by scheduler — if consumer isn't scheduled, message is delayed

**Risks of Shared Memory:**
1. **Crash recovery** — if producer crashes with unknown write_pos, consumer sees garbage
2. **Cross-language GC** — no Go pointers in shared memory (Go GC can't track them)
3. **NUMA locality** — shared memory page could be on remote NUMA node (~150ns vs ~50ns local)
4. **Security** — no isolation, both processes must be trusted

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Quantitative latency** | Provides actual latency numbers, not just "shm is faster" |
| **Memory ordering** | Explains volatile + memory barriers, not just mutex |
| **NUMA awareness** | Knows to pin memory and threads to same NUMA node |
| **Crash safety** | Acknowledges shared memory fragility vs socket reliability |

---

## 10. Signals & Async Signal Safety

**Q:** "You're debugging a production crash in a Go service that embeds a C library via cgo. The library uses `SIGALRM` for timeouts, but it's causing random `EINTR` errors on system calls. What's happening and how do you fix it?"

**What They're Really Testing:** Deep understanding of signal delivery, interrupted syscalls, and reentrancy — with a mutlilingual twist.

### Answer

**Root Cause:**

```c
// C library uses SIGALRM for timeouts:
void set_timeout_ms(int ms) {
    struct itimerval it;
    it.it_value.tv_sec = ms / 1000;
    it.it_value.tv_usec = (ms % 1000) * 1000;
    setitimer(ITIMER_REAL, &it, NULL);
    signal(SIGALRM, timeout_handler);
}
```

When SIGALRM fires during a system call like `read()` or `epoll_wait()`:

```
Thread executing:   read(fd, buf, 1024)
                         │
                    SIGALRM arrives
                         │
                         ▼
                    Kernel delivers signal
                         │
                         ▼
                    read() returns -1
                    errno = EINTR
                    (Interrupted system call)
```

**Why This Breaks Go:**
- Go's runtime uses `epoll` for network I/O, `futex` for goroutine scheduling
- If a C signal handler fires on a Go thread:
  1. The `epoll_wait` in Go's network poller returns `EINTR`
  2. Go's runtime assumes no errors from kernel
  3. Go doesn't automatically restart interrupted syscalls (unlike BSD's `SA_RESTART`)
  4. Leading to `EINTR` propagating as an opaque error to Go code
  5. Worse: a SIGALRM during GC could corrupt Go runtime state if it fires between write barrier operations

**The Fix — Signal Masking + Dedicated Signal Thread:**

```go
// Go side — channel-based signal handling
func main() {
    sigs := make(chan os.Signal, 1)
    signal.Notify(sigs, syscall.SIGALRM)

    go func() {
        for {
            sig := <-sigs
            if sig == syscall.SIGALRM {
                // Handle timeout in Go goroutine
                log.Printf("SIGALRM received, resetting connection")
            }
        }
    }()

    // Block SIGALRM on all threads — let the signal goroutine handle it
    signal.Ignore(syscall.SIGALRM)
}
```

```c
// C side — use dedicated timer thread instead of SIGALRM:
#include <pthread.h>
#include <timerfd.h>

int timer_fd;

void *timer_thread(void *arg) {
    struct itimerspec ts;
    ts.it_value.tv_sec = 0;
    ts.it_value.tv_nsec = 100 * 1000000;  // 100ms
    ts.it_interval = ts.it_value;

    timerfd_settime(timer_fd, 0, &ts, NULL);

    uint64_t expirations;
    while (1) {
        read(timer_fd, &expirations, sizeof(expirations));
        // Handle timeout — runs in dedicated thread, no signal issues
        handle_timeout();
    }
    return NULL;
}
```

**Async-Signal-Safe Functions (the safe list):**

```c
// Only these can be called from a signal handler:
// write()  — write to pipe/self-pipe trick
// read()   — read from self-pipe
// sigaction() — change signal disposition
// sem_post()  — wake up waiting thread
// _exit() — immediate termination

// NEVER do this in a signal handler:
// malloc() — not reentrant (uses global lock)
// free()   — same
// printf() — uses stdio buffers (global lock)
// pthread_mutex_lock() — if held by interrupted thread → deadlock!
// any Go runtime function — Go signal handling is different
```

**Safer Pattern — The Self-Pipe Trick:**

```c
static int sigpipe[2];

void handler(int sig) {
    write(sigpipe[1], "", 1);  // Signal → write to pipe
}

// Main event loop polls both epoll AND sigpipe:
struct epoll_event events[1024];

epoll_ctl(epfd, EPOLL_CTL_ADD, sigpipe[0], &ev);

while (1) {
    int n = epoll_wait(epfd, events, 1024, -1);
    for (int i = 0; i < n; i++) {
        if (events[i].data.fd == sigpipe[0]) {
            // It's a signal! Handle safely outside signal context
            char buf[64];
            read(sigpipe[0], buf, sizeof(buf));
            handle_signal();
        } else {
            handle_io(events[i]);
        }
    }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **EINTR** | Knows that interrupted syscalls cause `EINTR` |
| **Go+C interaction** | Understands Go runtime's sensitivity to signals on m=1 GOMAXPROCS threads |
| **Async safety** | Lists async-signal-safe functions, knows why malloc is unsafe |
| **Fix** | Proposes timerfd/epoll-based approach or self-pipe trick |

---

## 11. cgroups & Namespaces (Container Isolation)

**Q:** "Explain how Docker/LXC achieves resource isolation using Linux cgroups and namespaces. Specifically, how does memory cgroup prevent one container from starving another? And how does CPU cgroup handle burst credits?"

**What They're Really Testing:** Whether you understand container isolation at the kernel level, not just Docker CLI usage.

### Answer

**Two Pillars of Container Isolation:**

```
Container
┌─────────────────────────────────┐
│  Namespace Isolation            │  ← What you can SEE
│  ┌───────────────────────────┐  │
│  │ PID Namespace (pid)       │  │  Container sees only its own processes
│  │ Network Namespace (net)   │  │  Own IP stack, interfaces, ports
│  │ Mount Namespace (mnt)     │  │  Own filesystem mount table
│  │ UTS Namespace (uts)       │  │  Own hostname
│  │ IPC Namespace (ipc)      │  │  Own System V IPC / POSIX queues
│  │ User Namespace (user)    │  │  UID/GID mapping (container root != host root)
│  │ Cgroup Namespace         │  │  Own /proc/self/cgroup view
│  └───────────────────────────┘  │
├─────────────────────────────────┤
│  cgroup Resource Control         │  ← What you can USE
│  ┌───────────────────────────┐  │
│  │ cpu cgroup                 │  │  CPU shares, quota, period, burst
│  │ memory cgroup              │  │  Hard/soft limits, swap, OOM priority
│  │ blkio cgroup               │  │  Block I/O throttling
│  │ cpuset cgroup             │  │  CPU pinning, NUMA node affinity
│  │ pids cgroup               │  │  Max process count
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Memory cgroup (v2) — Deep Dive:**

```
memory.max = 2GB   ← Hard limit — OOM kill if exceeded
memory.high = 1.8GB ← Soft limit — reclaim aggressively above this
memory.low = 1GB   ← Guaranteed minimum (protected under memory pressure)
memory.min = 512MB ← Hard guarantee (can't be reclaimed by others)
memory.swap.max = 1GB
memory.oom.group = 1 ← Kill entire cgroup on OOM, not just one process
```

**How Memory Pressure Works:**

```
Memory Pressure Scenario:

Total RAM: 16GB
Container A: memory.max = 4GB, using 3.8GB
Container B: memory.max = 4GB, using 3.0GB
Host processes: using 6GB
Free: 3.2GB

Suddenly: Host + A + B allocate more → total demand = 17GB
    │
    ▼
Kernel's reclaim daemon (kswapd) wakes up
    │
    ▼
Checks memory.high for each cgroup:
    A: 3.8GB > 4GB × 0.90 = 3.6GB → reclaim A aggressively
    B: 3.0GB < 3.6GB → don't touch B
    Host: no cgroup → global reclaim

But wait — if A hits 4GB:
    → OOM killer called
    → memory.oom.group = 1
    → Kills ALL processes in A (not just the allocating one)
    → Prevents partial failures and zombie state
```

**Memory Reclaim Hierarchy (v2):**

```
┌───────────────────────┐
│       Root            │  memory.max = max (unlimited)
│                       │
├───────────────────────┤
│   /system.slice       │  memory.max = 8GB
├───────────────────────┤
│   /docker             │  memory.max = max
│  ┌─────────────────┐  │
│  │ container_A     │  │  memory.max = 4GB, memory.swap.max = 0
│  └─────────────────┘  │
│  ┌─────────────────┐  │
│  │ container_B     │  │  memory.max = 4GB, memory.swap.max = 1GB
│  └─────────────────┘  │
└───────────────────────┘
```

**CPU cgroup — Shares, Quota, Burst:**

```c
// Configuration:
// Container A gets 4 CPUs worth of time
// Container B gets 2 CPUs worth of time
// Both can burst up to 8 CPUs if idle

// cpu.weight: relative shares (1-10000, default 100)
container_A: cpu.weight = 200   // Gets 2× the CPU of default
container_B: cpu.weight = 100   // Baseline

// cpu.max: [quota period] [burst]
container_A: cpu.max = "400000 100000 600000"
//   4 CPUs  │  100ms   │ up to 6 CPUs burst
//            │  period  │
```

**CPU Burst Mechanism (kernel 5.14+):**

```
Time (100ms periods):
Period 1: A uses 5 CPUs (5 × 100ms = 500ms CPU time)
          → quota = 400ms → exceeded by 100ms
          → uses 100ms from burst bucket
          → burst bucket: 600ms → 500ms remaining

Period 2: A uses 2 CPUs (2 × 100ms = 200ms CPU time)
          → quota = 400ms → 200ms under
          → refill burst bucket: 500ms + 200ms → capped at 600ms

Period 3: A is idle
          → burst bucket refills to 600ms

Benefits:
- Latency-sensitive apps get burst when cluster is underutilized
- No need to over-provision (reserve 8 CPUs when average is 2)
- Burst bucket prevents sustained overload
```

**Production Monitoring:**

```bash
# Check memory pressure
cat /sys/fs/cgroup/memory/docker/<container_id>/memory.pressure
some avg10=2.35 avg60=1.88 avg300=0.56 total=1234567
full avg10=0.89 avg60=0.45 avg300=0.12 total=456789

# some = at least one task stalled
# full = all tasks stalled
# >5% avg10 → investigate, >20% avg10 → urgent

# Check CPU throttling
cat /sys/fs/cgroup/cpu/docker/<container_id>/cpu.stat
nr_periods 1000
nr_throttled 45        # 4.5% of periods experienced throttling
throttled_usec 1500000  # 1.5s total throttled time
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Namespace vs cgroup** | Clearly separates what you see vs what you can use |
| **Memory reclaim** | Explains soft vs hard limits, reclaim hierarchy, OOM behavior |
| **CPU burst** | Understands burst bucket mechanics (recent kernel feature) |
| **Production monitoring** | Knows to check memory.pressure, cpu.stat metrics |

---

## 12. OOM Killer & Memory Overcommit

**Q:** "Your Kubernetes pod (memory limit 4GB) was OOM-killed even though top shows RSS = 3.5GB. You also see a balloon process allocating 1GB. What happened? How do memory overcommit and OOM killer scoring work?"

**What They're Really Testing:** Understanding of memory overcommit, OOM killer score calculation, and the gap between RSS and actual memory pressure.

### Answer

**Mystery Solved — What Happened:**

```
Process memory accounting is NOT just RSS:

RSS (Resident Set Size) = 3.5GB
  ├── Anonymous pages (heap, stack)  = 2.0GB
  ├── File-backed pages (code, mmap) = 1.0GB
  └── Shared pages (shared libraries) = 0.5GB ← Counted in RSS!

But the balloon process:
  malloc(1GB) + memset(memset to actually touch pages)
  → 1GB of anonymous pages

Total anonymous memory = 2.0GB + 1.0GB = 3.0GB
Plus kernel overhead:
  - Page tables = ~400MB
  - dentry/inode cache = ~200MB
  - slab = ~300MB
  ↓
Total memory pressure ≈ 3.9GB → close to 4GB limit → OOM kill
```

**Memory Overcommit Modes:**

```
/proc/sys/vm/overcommit_memory

0 = Heuristic overcommit (default)
    - Allow until "obviously" too much
    - Uses: total_ram × overcommit_ratio (default 50%)
    - So on 16GB RAM: 16GB + 16GB × 50% = 24GB virtual allowed

1 = Always overcommit
    - "I know what I'm doing"
    - Allows any malloc(), even if absurd
    - OOM kill when memory actually runs out
    - Used by databases that manage their own memory (e.g., Oracle HugePages)

2 = No overcommit (strict)
    - Commit limit = (RAM + swap) × overcommit_ratio / 100
    - malloc() returns NULL if limit would be exceeded
    - Preferred for safety-critical systems
    - Prevents OOM kills entirely
```

**OOM Killer Score Calculation:**

```c
// Each process has oom_score_adj and oom_score
// oom_score = system_heuristic + oom_score_adj

// System heuristic considers:
//
// 1. Total memory used (resident + swap)
//    more memory → higher score → more likely to be killed
//
// 2. Runtime (processes that just started are preferred over long-lived)
//    oom_score_adj = -1000 for root/init process
//
// 3. Process children (killing a parent reclaims all children's memory too)
//    oom_score is inherited from parent
//
// 4. OOM_SCORE_ADJ_MIN / MAX = -1000 (OOM disabled) to +1000 (always killed)

// Practical example:
// Redis (using 3.5GB RSS, running 30 days):
//   oom_score ≈ 950 + oom_score_adj

// Balloon process (using 1GB RSS, running 5 seconds):
//   oom_score ≈ 400 + oom_score_adj

// Kubernetes ballon process has oom_score_adj = -997!
//   → oom_score ≈ 400 + (-997) = -597
//   → Almost immune

// Redis has default oom_score_adj = 0
//   → oom_score ≈ 950
//   → Most likely to be killed
```

**How Kubernetes Sets OOM Score:**

```yaml
# Kubernetes applies this to pods:
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: redis
    resources:
      limits:
        memory: 4Gi
      requests:
        memory: 2Gi
```

```bash
# Kubernetes sets:
# oom_score_adj for guaranteed pods (limits = requests):
#   -997 (almost protected)
# oom_score_adj for burstable pods (limits > requests):
#   range from -996 to 0 based on memory usage/limit ratio
# oom_score_adj for best-effort pods (no limits):
#   1000 (first to be killed)
```

**Preventing Unnecessary OOM Kills:**

1. **Set memory limits correctly** — request = limit (Guaranteed QoS) for critical services

2. **Use `memory.min` (cgroup v2)**:

```bash
# Reserve 500MB for critical daemon
echo 500M > /sys/fs/cgroup/redis/memory.min
# Now even under global pressure, Redis keeps 500MB
```

3. **Disable overcommit for critical services:**

```bash
sysctl vm.overcommit_memory=2
sysctl vm.overcommit_ratio=100  # Commit limit = 100% of (RAM + swap)
```

4. **Reduce memory fragmentation:**

```bash
# Check memory fragmentation
cat /sys/kernel/debug/extfrag/unusable_index

# Compact memory
echo 1 > /proc/sys/vm/compact_memory
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **RSS ≠ all** | Explains page tables, slab, dentry cache as kernel memory consumers |
| **oom_score** | Understands heuristic + adj, not random killing |
| **Kubernetes integration** | Knows QoS classes map to oom_score_adj ranges |
| **Mitigation** | Suggests memory.min, overcommit=2, proper resource limits |

---

> *Master these OS topics and you'll be prepared for the lowest-level Staff/Principal interviews at FAANG, database companies, and infrastructure platform teams.*
