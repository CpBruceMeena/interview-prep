# 🧠 Operating Systems — Staff-Level Interview Questions

> *12 questions covering memory management, process scheduling, I/O models, file systems, and kernel internals. Each answer leads with the 30-second version, then the mechanism, then trade-offs and what the interviewer probes next. Linux-focused; current as of October 2026 (Linux 6.x, Kubernetes 1.3x).*

---

## Table of Contents

1. [Virtual Memory & Page Tables](#1-virtual-memory-page-tables)
2. [TLB & Huge Pages](#2-tlb-huge-pages)
3. [Process Scheduling (CFS)](#3-process-scheduling-cfs)
4. [Context Switch Cost](#4-context-switch-cost)
5. [I/O Models: epoll, io_uring, kqueue](#5-io-models-epoll-io_uring-kqueue)
6. [Memory Allocation: malloc to mmap](#6-memory-allocation-malloc-to-mmap)
7. [Page Cache & Buffer Cache](#7-page-cache-buffer-cache)
8. [File Systems: ext4 vs xfs vs btrfs](#8-file-systems-ext4-vs-xfs-vs-btrfs)
9. [IPC Mechanisms](#9-ipc-mechanisms)
10. [Signals & Async Signal Safety](#10-signals-async-signal-safety)
11. [cgroups & Namespaces (Container Isolation)](#11-cgroups-namespaces-container-isolation)
12. [OOM Killer & Memory Overcommit](#12-oom-killer-memory-overcommit)

---

## 1. Virtual Memory & Page Tables

**Q:** "Design a page table structure for a 64-bit system with 4KB pages. How does a 4-level page table work, and why can't we use a simple flat page table? How do we handle the case where the virtual address space is sparse?"

**What They're Really Testing:** Whether you understand that `2^64 / 4KB = 2^52` entries is impossible, and whether you've thought about memory-efficient address translation in real systems.

### Answer

!!! tip "30-second answer"
    A flat table needs one entry per virtual page: 2^52 entries × 8 bytes = 32 PB per process, so it's impossible. x86-64 actually uses 48-bit virtual addresses (57 with 5-level paging) and translates through a **radix tree**: four levels of 512-entry tables, each table exactly one 4 KB page, 9 address bits per level. Unused regions simply have no lower-level tables, so cost scales with what is mapped, not with the address-space size. The price is a multi-step walk on a TLB miss, which is why the TLB, paging-structure caches and huge pages matter.

**The math problem:**

- Full 64-bit space with 4 KB pages: 2^64 / 2^12 = 2^52 entries × 8 B = 2^55 B = **32 PB** per process.
- Even x86-64's real 48-bit space would need 2^36 entries × 8 B = **512 GB** per process for a flat table.

**4-level page table (x86-64):**

```
48-bit virtual address
 [47:39]   [38:30]   [29:21]   [20:12]   [11:0]
  PGD idx   PUD idx   PMD idx   PTE idx   offset
  (L4)      (L3)      (L2)      (L1)

CR3 → PGD (512 entries) → PUD → PMD → PTE → physical page + offset
         each table = 512 × 8 B = 4 KB = one page
         each PTE maps 4 KB; each PMD entry covers 2 MB; each PUD entry covers 1 GB
```

Bits 63:48 must copy bit 47 ("canonical" addresses), which splits the space into a user half and a kernel half.

**Sparse address space efficiency** (1 GB of heap in one contiguous, aligned region):

| Level | Tables needed | Why |
|---|---|---|
| PGD | 1 | Root |
| PUD | 1 | One entry covers the 1 GB |
| PMD | 1 | 512 entries × 2 MB = 1 GB |
| PTE | 512 | Each maps 2 MB (512 × 4 KB pages) |
| **Total** | ~515 pages ≈ **2 MB** | ~0.2% overhead, vs 512 GB flat |

With 2 MB huge pages the PTE level disappears for that region: 3 tables total.

**5-level paging:** adds a P4D level (bits 56:48) for a 57-bit (128 PB) virtual space and up to 4 PB physical. Enabled on CPUs that support it (Intel since Ice Lake server, AMD Zen 4); 4-level paging limits virtual space to 256 TB and Linux to 64 TB of physical RAM.

**What they probe next:**

- **TLB miss cost:** a walk is up to 4 dependent memory accesses. Upper-level entries are usually in paging-structure caches and the data cache, so a typical walk costs tens of ns; when entries miss all caches it costs hundreds.
- **Page faults:** a minor fault (page in memory, mapping missing) costs ~1 µs or less; a major fault (read from disk) costs the I/O latency.
- **Virtualization:** nested (two-dimensional) paging means a guest TLB miss can need up to 24 memory accesses, another argument for huge pages in VMs.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Scale intuition** | Can immediately compute why flat page tables don't work |
| **Sparse efficiency** | Explains that unused regions consume zero page table memory; counts tables correctly |
| **TLB miss cost** | Knows a walk is up to 4 dependent accesses, usually partly cached |
| **Page size trade-offs** | Knows 4KB vs 2MB vs 1GB pages and when to use each |

---

## 2. TLB & Huge Pages

**Q:** "Our Redis instance is seeing 8% CPU time in TLB miss handling. Diagnose the root cause and propose a solution. Walk me through the numbers."

**What They're Really Testing:** Quantitative reasoning about TLB coverage and whether you understand huge pages as a practical optimization.

### Answer

!!! tip "30-second answer"
    The TLB covers only a few MB with 4 KB pages, while Redis does pointer-chasing lookups over a 12 GB heap, so most accesses miss and pay a page walk. Huge pages (2 MB) give ~500× more coverage per entry. **But for Redis specifically, the textbook fix backfires:** Redis forks for RDB/AOF persistence and relies on copy-on-write, and with Transparent Huge Pages every 4 KB write after the fork copies a whole 2 MB page, causing latency spikes and memory blow-up. Redis therefore disables THP for itself (`disable-thp yes`, the default). The right answer is to measure first, keep THP off (or `madvise`) for Redis, and attack the working set (sharding, smaller instances, better data structures); use huge pages for workloads that don't fork: JVM heaps, PostgreSQL shared buffers, DPDK, in-memory engines.

**Diagnosis — confirm it's really the TLB:**

```bash
perf stat -e dTLB-loads,dTLB-load-misses,dtlb_load_misses.walk_active -p $(pidof redis-server) -- sleep 10
# walk_active cycles / total cycles ≈ fraction of time spent walking page tables
cat /sys/kernel/mm/transparent_hugepage/enabled     # [always] madvise never
grep AnonHugePages /proc/$(pidof redis-server)/smaps_rollup
```

**The numbers (Skylake-class x86; newer cores are larger but the shape holds):**

```
Working set: ~12 GB, random access
L1 DTLB:  64 entries × 4 KB   = 256 KB
L2 STLB: 1536 entries × 4 KB  =   6 MB
Coverage: 6 MB / 12 GB ≈ 0.05% → nearly every random access misses the TLB

With 2 MB pages:
L1 DTLB:  32 entries × 2 MB   =  64 MB
L2 STLB: 1536 entries × 2 MB  =   3 GB   (STLB shared by 4 KB and 2 MB entries)
Coverage: 3 GB / 12 GB ≈ 25%, and each miss needs one fewer level to walk
```

**Huge page options:**

| Option | How | Trade-offs |
|---|---|---|
| THP `always` | Kernel backs eligible anonymous memory with 2 MB pages automatically; `khugepaged` collapses pages in the background | No app change. Risks: compaction stalls on allocation, RSS bloat (a 2 MB page is charged even if 4 KB is used), fork + COW copying 2 MB at a time |
| THP `madvise` | Only regions the app marks with `madvise(MADV_HUGEPAGE)` | Common distro default; apps opt in (JVM `-XX:+UseTransparentHugePages`) |
| hugetlbfs (`vm.nr_hugepages`) | Pre-reserved pool, app maps explicitly (`MAP_HUGETLB`, PostgreSQL `huge_pages=on`) | Predictable, no compaction; memory is reserved even if unused, needs config |
| 1 GB pages | hugetlbfs at boot | For very large, static heaps (databases, VMs) |

```bash
# Explicit pool for a database that supports it (not Redis): 6000 × 2 MB = 12 GB
sysctl -w vm.nr_hugepages=6000
```

**For Redis:** keep THP at `madvise` or `never` (Redis warns at startup otherwise), and if TLB misses really dominate, reduce the per-instance working set (cluster sharding, several smaller instances per host) or make lookups more cache-friendly (smaller encodings such as listpacks for small hashes/sets). Also check `vm.overcommit_memory=1`, which Redis needs so `fork()` for BGSAVE doesn't fail (Q12).

**What they probe next:** "Why does fork + THP hurt?" After fork, parent and child share pages read-only; the first write to a shared page copies it. With THP that copy is 2 MB instead of 4 KB, so a write-heavy Redis during BGSAVE can duplicate most of its memory and stall on each copy. "What about multi-size THP?" Since Linux 6.8, anonymous memory can use intermediate "mTHP" sizes (e.g. 64 KB) that some CPUs (ARM contiguous PTEs, AMD) coalesce in the TLB, a middle ground between 4 KB and 2 MB.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Quantitative** | Actual TLB entry counts, coverage calculations |
| **Redis expertise** | Knows fork + COW + THP is the trap and that Redis disables THP for itself |
| **THP vs explicit** | Understands THP always/madvise/never and hugetlbfs |
| **Trade-off** | Mentions compaction stalls, RSS bloat, measuring with perf before changing |

---

## 3. Process Scheduling (CFS)

**Q:** "Walk me through how the Linux Completely Fair Scheduler (CFS) works. If I have 4 CPU cores and 8 CPU-bound threads, how does CFS decide who runs when? How does it handle priority (nice values)?"

**What They're Really Testing:** Whether you understand that modern schedulers use weighted fair queuing, not simple round-robin, and whether you know the data structures involved.

### Answer

!!! tip "30-second answer"
    Linux's fair scheduler gives each runnable thread CPU time in proportion to its **weight** (derived from nice). It tracks **virtual runtime**: real runtime scaled by `1024 / weight`, so heavier threads accumulate vruntime more slowly. Each CPU has its own runqueue, a red-black tree ordered by vruntime, and load balancing moves threads between CPUs, so 8 equal threads on 4 cores settle at 2 per core, each getting ~50% of a core. **Currency check:** since **Linux 6.6 (2023)** the pick-next algorithm is **EEVDF** (Earliest Eligible Virtual Deadline First), not classic CFS. Weights and vruntime remain; EEVDF picks among threads that are owed CPU time the one with the earliest virtual deadline, which gives better latency control. Since 6.12, **sched_ext** also lets you load a scheduler written in BPF.

**Virtual runtime:**

```
vruntime += delta_exec × (1024 / weight)      (weight of nice 0 = 1024)
```

**Classic CFS (up to Linux 6.5):** always run the leftmost (smallest vruntime) task in the per-CPU red-black tree. The running task is taken out of the tree; on preemption or sleep it is re-inserted with its updated vruntime. A task waking from sleep has its vruntime raised to near the queue's `min_vruntime`, so sleeping doesn't bank unlimited credit.

```c
/* Simplified CFS logic, not real kernel code */
void update_curr(struct cfs_rq *rq) {            /* on tick, wakeup, preemption */
    u64 delta = now() - rq->curr->exec_start;
    rq->curr->vruntime += delta * NICE_0_WEIGHT / rq->curr->weight;
    if (should_preempt(rq))                       /* curr ran past its fair slice */
        resched_curr(rq);
}

struct task *pick_next(struct cfs_rq *rq) {
    if (rq->curr) rb_insert(&rq->tree, rq->curr); /* put previous back, keyed by vruntime */
    struct task *next = rb_first_cached(&rq->tree); /* leftmost = O(1), cached */
    rb_erase(&rq->tree, next);                    /* running task lives outside the tree */
    return next;
}
```

**EEVDF (Linux 6.6+):**

| Concept | Meaning |
|---|---|
| **Lag** | How much CPU time a task is owed compared to the ideal fair share. Lag ≥ 0 means the task is **eligible** |
| **Virtual deadline** | Eligible time + `slice / weight`. A task asking for a shorter slice gets an earlier deadline |
| **Pick rule** | Among eligible tasks, run the one with the earliest virtual deadline |
| **Why it replaced CFS** | CFS needed a pile of heuristics (wakeup granularity, latency tunables) to give interactive tasks low latency; EEVDF expresses latency needs directly via slice length while keeping proportional fairness |

The old CFS tunables (`sched_latency_ns`, `sched_min_granularity_ns`, `sched_wakeup_granularity_ns`) are gone in EEVDF kernels; the main knob is the base slice (`/sys/kernel/debug/sched/base_slice_ns`).

**Nice values:** each nice step is roughly a 1.25× weight change (≈10% CPU difference between two competing tasks).

| nice | weight | Share vs one nice-0 task on the same CPU |
|------|--------|------------------------------------------|
| -20  | 88761  | 88761 / (88761 + 1024) ≈ 98.9% |
| -10  | 9548   | ≈ 90.3% |
| 0    | 1024   | 50% |
| 10   | 110    | ≈ 9.7% |
| 19   | 15     | ≈ 1.4% |

Weights only matter when threads **compete** for the same CPU. A nice-19 thread on an idle core still gets 100%.

**4 cores, 8 CPU-bound threads:**

- Load balancing spreads them 2 per core. Balancing runs periodically per **scheduling domain** (SMT siblings → cores sharing a cache → package → NUMA nodes), more often at lower levels, plus "newidle" balancing when a CPU is about to go idle.
- On each core the two threads alternate; each gets ~50% of a core.
- Moving a thread across NUMA nodes is expensive (its memory stays behind), so balancing across NUMA is deliberately conservative; automatic NUMA balancing may migrate pages instead.

**Other scheduling classes** (checked in priority order): `SCHED_DEADLINE` (EDF with runtime/period budgets), `SCHED_FIFO`/`SCHED_RR` (real-time, fixed priorities; can starve everything else), then the fair class (`SCHED_NORMAL`, `SCHED_BATCH`), `SCHED_IDLE`, and `sched_ext` (BPF schedulers, Linux 6.12+, used for experimentation and workload-specific policies).

**What they probe next:**

- **Containers:** cgroup CPU **weight** uses the same proportional mechanism between groups; CPU **quota** (`cpu.max`) is a hard cap that throttles even on an idle machine (Q11).
- **Latency:** run-queue latency, not CPU utilisation, is what users feel. Measure it with `runqlat` (bcc/bpftrace) or `perf sched latency`.
- **Thread pools:** more CPU-bound threads than cores only adds switching and cache pollution.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **vruntime** | Explains the weighted fair queuing concept clearly |
| **Data structures** | Per-CPU RB-tree with cached leftmost; running task outside the tree |
| **Currency** | Knows EEVDF replaced CFS's pick logic in 6.6 and what sched_ext is |
| **Nice math** | Can calculate proportional shares for different nice values |
| **Load balancing** | Scheduling domains, newidle balancing, NUMA caution |

---

## 4. Context Switch Cost

**Q:** "Estimate the cost of a context switch between two processes on a modern x86 CPU. Break down the components. How would you measure it in production?"

**What They're Really Testing:** Whether you understand that context switching is more than just register saves — it's a TLB/cache demolition event.

### Answer

!!! tip "30-second answer"
    The **direct** cost (enter the kernel, pick the next task, save and restore registers including FPU/SIMD state, switch stacks and, between processes, the page-table root) is on the order of **1–3 µs** on modern Linux with security mitigations. The **indirect** cost is usually bigger and harder to see: the next task runs with cold caches, branch predictors and TLB entries, which can cost tens of µs of slower execution. Thread switches inside one process skip the address-space change. **PCID** means switching CR3 no longer has to flush the TLB. Measure with `perf bench sched pipe` for the direct cost and with `perf stat` / `runqlat` in production.

**Components:**

| Component | Notes |
|---|---|
| Kernel entry/exit | A syscall or interrupt. Spectre/Meltdown mitigations (KPTI, retpolines, IBRS) made this noticeably more expensive since 2018 |
| Scheduler decision | Pick next task; cheap |
| Save/restore registers | General-purpose registers are cheap; XSAVE/XRSTOR of AVX-512 state is several KB. Linux saves FPU state eagerly |
| Address-space switch (process → process) | Write CR3. With **PCID** (used by Linux since 4.14), TLB entries are tagged per address space and survive the switch; without PCID the non-global TLB is flushed |
| Indirect: cache, TLB and branch-predictor warm-up | Depends on working-set size; for a few MB of working set it can dominate everything above |

**Measuring:**

```bash
# Direct cost: two processes ping-pong over a pipe (each round trip = 2 switches)
perf bench sched pipe -l 1000000
taskset -c 0 perf bench sched pipe -l 1000000   # pin both to one CPU to force switches

# Rate in production
perf stat -e context-switches,cpu-migrations -p <pid> -- sleep 10
pidstat -w 1                    # voluntary (blocked) vs involuntary (preempted) per task

# Run-queue latency: time from runnable to running (eBPF)
runqlat 10 1                    # bcc tools; or: bpftrace -e 'tracepoint:sched:sched_switch ...'
```

High **involuntary** switches mean CPU contention (too many runnable threads, or cgroup throttling). High **voluntary** switches mean threads block a lot (locks, I/O).

**Practical implications:**

- CPU-bound pools: about one thread per core. I/O-bound work: use async I/O or lightweight tasks (goroutines, virtual threads) so blocking doesn't cost a kernel thread switch.
- Spinning beats sleeping only if the expected wait is shorter than a switch; modern mutexes (futex-based, Go's and Java's locks) spin briefly before sleeping.
- io_uring reduces **syscalls** (batching, and SQPOLL mode lets a kernel thread poll the queue), which removes kernel entries and some wakeups. It doesn't make context switching disappear.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Direct vs indirect** | Separates the µs-level direct cost from cache/TLB warm-up |
| **TLB awareness** | Knows PCID avoids TLB flushes; thread switches don't change CR3 |
| **Measurement** | `perf bench sched pipe`, voluntary vs involuntary switches, runqlat |
| **Practical** | Knows when context switching is worth avoiding and how |

---

## 5. I/O Models: epoll, io_uring, kqueue

**Q:** "Compare select, poll, epoll, and io_uring for a high-throughput TCP server handling 100K concurrent connections. What are the internal data structures? Why was io_uring a paradigm shift?"

**What They're Really Testing:** Whether you understand the evolution of I/O in the kernel — from O(n) scanning to O(1) event-driven to submission-queue async.

### Answer

!!! tip "30-second answer"
    `select`/`poll` pass the whole fd set on every call and the kernel scans it: O(n) per call, hopeless at 100K connections. `epoll` (and BSD/macOS `kqueue`) keep the interest set **in the kernel** and return only ready fds, so cost scales with activity, not with connections. But they are **readiness** APIs: after "fd is readable" you still make a `read()` syscall per fd. `io_uring` (Linux 5.1, 2019) is a **completion** API: you put operations into a shared-memory submission ring and collect results from a completion ring, batching many operations per syscall (or none, with polling), and it covers files too. Trade-off: io_uring has had many kernel security bugs, so it is **blocked by default** in Docker's seccomp profile and disabled at Google, Android and ChromeOS; check your platform before betting on it.

**Evolution:**

| API | Since | Model | Cost per wait call | Notes |
|-------|------|-----------|-------------------|------|
| `select` | 4.2BSD (1983) | Readiness | O(n) scan + copy of fd bitmaps | Limited to `FD_SETSIZE` (1024) fds |
| `poll` | SVR3 (1986); Linux 2.1 | Readiness | O(n) scan + copy of the array | No fd limit |
| `epoll` | Linux 2.5.44 (2002) | Readiness | O(ready) | Interest set registered once with `epoll_ctl` |
| `kqueue` | FreeBSD 4.1 (2000), macOS | Readiness (+ events for files, processes, signals, timers) | O(ready) | Registration changes can be batched into the same `kevent()` call |
| IOCP | Windows NT | Completion | — | Completion model that io_uring resembles |
| `io_uring` | Linux 5.1 (2019) | Completion | Many ops per `io_uring_enter`, or zero syscalls with SQPOLL | Sockets and files, plus open/stat/etc. |

**epoll internals:**

```
epoll instance (struct eventpoll)
 ├── red-black tree of epitems   ← every monitored fd; epoll_ctl add/mod/del O(log n)
 ├── ready list (rdllist)        ← fds with pending events
 └── wait queue                  ← threads blocked in epoll_wait

When a socket gets data, its wakeup callback (ep_poll_callback) appends the
epitem to the ready list. epoll_wait just drains the ready list: no scan.
```

Key details interviewers probe:

- **Level- vs edge-triggered:** level-triggered reports an fd as long as it is readable; edge-triggered (`EPOLLET`) reports only transitions, so you must read until `EAGAIN` or you'll stall that connection.
- **Thundering herd:** several threads waiting on one epoll fd or one listen socket can all wake. Fix with `EPOLLEXCLUSIVE` or `SO_REUSEPORT` (one listen socket per thread, kernel distributes connections).
- Readiness APIs require **non-blocking** fds and only work for things that have a meaningful "ready" state: regular files are always "ready", so epoll can't make disk reads async.

**The readiness-model loop:**

```c
struct epoll_event events[1024];
for (;;) {
    int n = epoll_wait(epfd, events, 1024, -1);      /* 1 syscall */
    for (int i = 0; i < n; i++) {
        int fd = events[i].data.fd;
        ssize_t r;
        while ((r = read(fd, buf, sizeof buf)) > 0)   /* 1+ syscalls per ready fd */
            process(fd, buf, r);
        /* r == -1 && errno == EAGAIN → drained; r == 0 → peer closed */
    }
}
```

**io_uring — the completion model:**

```
 user space                         kernel
 ┌─────────────────────┐            ┌──────────────────────────┐
 │ Submission Queue    │──(mmap)───►│ consumes SQEs: read,     │
 │ SQE SQE SQE ...     │            │ recv, send, accept, ...  │
 └─────────────────────┘            └────────────┬─────────────┘
 ┌─────────────────────┐                         │
 │ Completion Queue    │◄──(mmap)────────────────┘ posts CQEs
 │ CQE CQE ...         │   (result + user_data)
 └─────────────────────┘
 Both rings live in memory shared by kernel and process: submitting and
 reaping are plain memory writes/reads. A syscall (io_uring_enter) is needed
 only to tell the kernel there is work or to wait, unless SQPOLL is on.
```

```c
#include <liburing.h>

struct io_uring ring;
io_uring_queue_init(4096, &ring, 0);                 /* io_uring_setup + mmap the rings */

for (int i = 0; i < 100; i++) {                      /* queue 100 reads, no syscalls */
    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
    io_uring_prep_read(sqe, fds[i], bufs[i], 4096, 0);
    io_uring_sqe_set_data64(sqe, i);                 /* tag to match the completion */
}
io_uring_submit(&ring);                              /* ONE syscall for 100 operations */

struct io_uring_cqe *cqe;
io_uring_wait_cqe(&ring, &cqe);                      /* block for at least one */
do {
    handle(cqe->user_data, cqe->res);                /* res = bytes read or -errno */
    io_uring_cqe_seen(&ring, cqe);
} while (io_uring_peek_cqe(&ring, &cqe) == 0);       /* 0 = got one; -EAGAIN = empty */
```

**Why io_uring was a paradigm shift:**

1. **Batching:** one `io_uring_enter` submits and reaps many operations; with `IORING_SETUP_SQPOLL` a kernel thread polls the submission ring, so the hot path needs no syscalls (at the cost of a busy core).
2. **Real async for files:** buffered and direct file I/O complete asynchronously (blocking cases are handed to kernel worker threads), which epoll can't do.
3. **Fewer copies and lookups:** registered buffers and files avoid per-op setup; **zero-copy send** (`IORING_OP_SEND_ZC`, 6.0) and later zero-copy receive avoid data copies. Note: the **rings** are shared memory, but ordinary reads still copy data into your buffer.
4. **Network features:** multishot `accept`/`recv` (one SQE produces many completions) and provided-buffer rings let a server avoid allocating a buffer per idle connection.

**Practical choice for 100K connections:** epoll (via your runtime: Netty, Go's netpoller, Tokio, libuv) is mature and fast; io_uring pays off when syscall overhead dominates (many small operations), when mixing network and file I/O, or with storage-heavy engines. Check that your kernel and container seccomp profile allow it (`kernel.io_uring_disabled` sysctl, Linux 6.6+), and that you can absorb its security update cadence.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Data structures** | RB-tree + ready list for epoll; shared SQ/CQ rings for io_uring |
| **Readiness vs completion** | Explains why epoll can't do async disk I/O and io_uring can |
| **io_uring depth** | Batching, SQPOLL, registered buffers, multishot, zero-copy send |
| **Practical limitations** | Security track record, seccomp blocking, epoll still the default in most runtimes |

---

## 6. Memory Allocation: malloc to mmap

**Q:** "Trace the path of a `malloc(512)` call from user-space library to physical RAM. When does `sbrk` vs `mmap` get used? What fragmentation patterns arise?"

**What They're Really Testing:** Whether you understand the entire memory allocation stack — from glibc arena allocator through brk/mmap to the kernel's page allocator (buddy system).

### Answer

!!! tip "30-second answer"
    `malloc(512)` in glibc is almost always served in user space: first the per-thread **tcache**, then the arena's bins, then by splitting the arena's **top chunk**. Only when the arena runs out does glibc call `brk` (main arena) or `mmap` (other arenas, and any request above the **mmap threshold**, 128 KB by default and adjusted dynamically). Even then, the kernel only reserves **virtual** address space: physical pages are allocated lazily on first touch by the page-fault handler, from the buddy allocator. Fragmentation shows up as RSS that never shrinks after frees (holes in the heap) and as per-thread arena bloat; jemalloc/tcmalloc/mimalloc or `MALLOC_ARENA_MAX` are the usual fixes.

**The full stack:**

```
malloc(512)
    │
    ▼
glibc malloc (ptmalloc2)
  1. tcache (per thread, no lock): 64 size classes up to 1032 B, 7 chunks each
  2. arena bins (arena lock): fastbins (small sizes), smallbins (< 1 KB),
     unsorted bin (recently freed), largebins (sorted, best fit)
  3. split the arena's "top" chunk
  4. grow the arena: brk() for the main arena, mmap'd heaps for other arenas
  (requests ≥ mmap threshold go straight to mmap)
    │  system call only reserves virtual address space (VMA)
    ▼
first write to the page → page fault → kernel allocates a physical page
    │
    ▼
buddy allocator: free lists of 2^order contiguous pages per zone;
watermarks (min/low/high) trigger kswapd reclaim and compaction
    │
    ▼
physical RAM (zeroed page mapped into the process)
```

**Path for `malloc(512)`:**

1. Round up to a chunk size: 512 + 8 B header, aligned to 16 → **528 B** chunk.
2. **tcache** bin for 528 B non-empty? Pop and return (the common fast path).
3. Otherwise lock the thread's **arena**. Exact-size **smallbin** match? Return it (and refill tcache from that bin).
4. Process the **unsorted bin** (recently freed chunks): exact fit returns, others get sorted into small/large bins.
5. Search larger bins; split a bigger chunk if found.
6. Split the **top chunk**. If it's too small, extend the heap with `brk` (or a new mmap'd heap for non-main arenas).

**brk vs mmap:**

| Factor | brk heap / arena | Direct mmap |
|--------|-------------|------------------|
| Used for | Requests below the threshold | Requests ≥ `M_MMAP_THRESHOLD` (128 KB default; raised dynamically up to 32 MB on 64-bit when mmapped chunks are freed) |
| Returning memory | Top of heap is trimmed back with `brk` past `M_TRIM_THRESHOLD`; free pages inside the heap can be released with `madvise(MADV_DONTNEED)` via `malloc_trim()` | `munmap` on free releases immediately |
| Fragmentation | Holes between live chunks keep pages resident | Page-granular: rounds up to 4 KB, no sharing between allocations |
| Cost | Mostly user space | Syscall + page faults on use + `munmap` (TLB shootdown across CPUs) each time |

**Fragmentation patterns:**

```
External fragmentation in the heap (after many alloc/free cycles):
│ live │ free │ live │ free │ live │ free │ live │  ← plenty free in total,
                                                     but no single hole fits a
                                                     large request; and the heap
                                                     can't shrink below the
                                                     highest live chunk

Internal fragmentation:
  malloc(1) → minimum 32 B chunk on 64-bit (8 B header + alignment)
  malloc(130 KB) via mmap → rounded up to 33 pages
```

**Production patterns and mitigations:**

- **Arena bloat:** glibc creates up to 8 × cores arenas on 64-bit; many threads with alloc/free churn can make RSS much larger than live data. `MALLOC_ARENA_MAX=2` or `4` is a classic fix for JVMs and Go-cgo-heavy services with native leaks that aren't leaks.
- **Alternative allocators:** jemalloc (size classes, per-thread caches, background purging; used by Redis, Rust historically), tcmalloc (per-CPU caches), mimalloc. Choose by measuring RSS and p99 latency.
- **Slab/pool allocators** for fixed-size objects avoid fragmentation entirely.
- **Diagnose:** `pmap -x`, `/proc/<pid>/smaps_rollup`, `malloc_info()`, and heap profilers (jemalloc `prof`, heaptrack).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stack depth** | Traces tcache → bins → top chunk → brk/mmap → page fault → buddy |
| **Lazy allocation** | Knows brk/mmap reserve virtual memory; physical pages come on first touch |
| **Thresholds** | Knows the 128KB dynamic mmap threshold, tcache sizes, arena count |
| **Fragmentation** | Distinguishes internal vs external, explains RSS that won't shrink |
| **Tooling** | Can use `pmap`, `/proc/self/smaps`, `malloc_info()` to diagnose |

---

## 7. Page Cache & Buffer Cache

**Q:** "A MySQL instance on Linux is reading 10GB of data from disk. Trace the path from `pread()` system call to the disk and back. Where does the page cache sit? How does `direct I/O` change things?"

**What They're Really Testing:** Understanding of the block I/O layer, page cache, and how database engines interact with the OS.

### Answer

!!! tip "30-second answer"
    `pread()` goes through the VFS to the **page cache**, an in-memory cache of file contents indexed per file (an xarray keyed by page offset). On a hit the kernel **copies** the data into the user buffer; on a miss the filesystem maps the file offset to disk blocks and the block layer (blk-mq) sends the request to the NVMe driver, with readahead fetching more for sequential reads. Writes land in the page cache as dirty pages and are written back later by flusher threads. **O_DIRECT** bypasses the page cache: DMA goes straight to the (aligned) user buffer. InnoDB uses it because it has its own buffer pool and double caching wastes RAM; PostgreSQL historically relies on the page cache instead.

**The path of a `pread()`:**

```
pread(fd, buf, 16384, offset)
  │
  ▼
VFS: file → inode → address_space
  │
  ▼
Page cache lookup (xarray indexed by file page offset; pages grouped into folios)
  ├─ hit:  copy_to_user() into buf → done (one memory copy, no I/O)
  └─ miss: allocate pages, lock them, start I/O; readahead may fetch more
  │
  ▼
Filesystem (ext4/XFS): file offset → extent → disk block numbers
  │
  ▼
Block layer (blk-mq): per-CPU software queues → hardware queues;
  I/O scheduler is usually "none" for NVMe, mq-deadline/BFQ for slower devices;
  plugging merges adjacent requests
  │
  ▼
NVMe driver: submission/completion queues, DMA into the page cache pages,
  completion via interrupt (or polling)
  │
  ▼
Device: ~10s of µs for NVMe flash random reads, ~5-10 ms for HDD seeks
  │
  ▼
Pages marked up to date, waiting reader woken, data copied into buf
```

**Write path and dirty page tunables:**

```
write() → copy into page cache, mark dirty → return (fast)
        → per-device flusher threads write back later (pdflush was replaced in 2.6.32)
        → fsync() forces dirty pages and metadata to stable storage
```

| Tunable | Default | Effect |
|---|---|---|
| `vm.dirty_background_ratio` | 10% | Above this, background writeback starts |
| `vm.dirty_ratio` | 20% | Above this, **writing processes are throttled** in `balance_dirty_pages()` and effectively write synchronously |
| `vm.dirty_expire_centisecs` | 3000 (30 s) | Dirty data older than this gets written back |
| `vm.dirty_writeback_centisecs` | 500 (5 s) | Flusher wake-up interval |

On machines with lots of RAM, percentage-based limits allow many GB of dirty data, causing long write stalls; use `dirty_background_bytes` / `dirty_bytes` instead.

**Reading 10 GB through the page cache:** a big sequential scan can evict hotter data. Linux's LRU (split into active/inactive lists, and the newer multi-gen LRU, MGLRU, default on many distros since 6.1) resists this somewhat; applications can also use `posix_fadvise(POSIX_FADV_SEQUENTIAL / DONTNEED)`.

**Direct I/O (O_DIRECT):**

```c
int fd = open("ibdata1", O_RDWR | O_DIRECT);
/* buffer, offset and length must be aligned to the logical block size (often 512 B or 4 KB) */
void *buf;
posix_memalign(&buf, 4096, 16384);
pread(fd, buf, 16384, offset);   /* DMA straight into buf; page cache skipped */
```

**Why databases differ:**

| | InnoDB (MySQL) | PostgreSQL |
|---|---|---|
| Data files | `innodb_flush_method=O_DIRECT` (default on Linux in MySQL 8.4) | Buffered I/O through the page cache |
| Caching | Large buffer pool (often 50–75% of RAM) | Modest `shared_buffers` (~25% of RAM) + OS page cache: double buffering accepted |
| Async I/O | Own I/O threads, Linux native AIO | **PostgreSQL 18** (2025) added asynchronous I/O (`io_method = worker` default, or `io_uring`) |
| Why | Knows its access pattern, avoids double caching, predictable memory | Simpler, portable, benefits from kernel readahead and writeback |

**What they probe next:** "Is `write()` durable?" No: only after `fsync`/`fdatasync` returns success. And if `fsync` reports an error, the dirty pages may already have been dropped, so retrying `fsync` can falsely succeed; PostgreSQL now panics on fsync failure for this reason (the 2018 "fsyncgate" discussion).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Full path** | VFS → page cache → FS → blk-mq → driver → device, and the copy on hit |
| **Dirty page mechanics** | Explains flusher threads, dirty ratios, writer throttling |
| **Database expertise** | Knows why InnoDB uses O_DIRECT and Postgres doesn't; fsync semantics |
| **Kernel currency** | xarray/folios, blk-mq, MGLRU |

---

## 8. File Systems: ext4 vs xfs vs btrfs

**Q:** "You're designing the storage stack for a high-traffic image hosting service. Compare ext4, XFS, and btrfs for this use case. Which one would you pick and why?"

**What They're Really Testing:** Whether you understand file system internals (allocation, journaling, checksums) at sufficient depth to make a production decision.

### Answer

!!! tip "30-second answer"
    At real scale, an image host stores blobs in **object storage** (S3, GCS, Ceph, or a Haystack-style blob store), not as one file per image on a local filesystem, because billions of small files make inode and directory metadata the bottleneck. For the local disks underneath (or a smaller self-hosted setup), pick **XFS**: allocation groups give parallel allocation and it scales to huge filesystems and files (it's the RHEL default). ext4 is a fine, simpler choice; both use extents and delayed allocation. btrfs earns its complexity only if you need checksummed data, snapshots or transparent compression on the host itself, and its RAID 5/6 is still not recommended for production.

**Quick comparison:**

| Feature | ext4 | XFS | btrfs |
|---------|------|-----|-------|
| Allocation | Extents, delayed allocation, flex block groups | Extents in B+trees, delayed allocation, **allocation groups** | Copy-on-write B-trees |
| Crash consistency | Journal (metadata by default; `data=ordered`) | Metadata log | COW + checksummed trees (no journal needed) |
| Max fs / file size | 1 EiB / 16 TiB (4 KB blocks) | 8 EiB / 8 EiB | 16 EiB / 16 EiB |
| Checksums | Metadata (`metadata_csum`) | Metadata (v5 format) | Data + metadata |
| Snapshots | No | No (but **reflinks**: `cp --reflink`) | Yes (subvolumes) |
| Dedup | No | Yes, via reflink-based `FIDEDUPERANGE` (offline tools) | Yes (offline, e.g. duperemove) |
| Compression | No | No | zstd / lzo / zlib |
| Online defrag | Yes (`e4defrag`) | Yes (`xfs_fsr`) | Yes |
| Shrink | Offline | **Effectively no** (only a limited, experimental shrink of free space at the end) | Online |
| RAID | Via mdadm/LVM | Via mdadm/LVM | Native 0/1/10 fine; **5/6 not production-ready** |

**Image hosting workload:** files of 100 KB–10 MB, write once, read many, never modified, huge count, heavy read concurrency, backups needed.

**Why XFS fits the local layer:**

```
XFS filesystem
┌──────────────┬──────────────┬──────────────┬──────────────┐
│    AG 0      │    AG 1      │    AG 2      │    AG 3      │
│ own free-    │ own free-    │ own free-    │ own free-    │
│ space B+trees│ space B+trees│ space B+trees│ space B+trees│
│ own inode    │ own inode    │ own inode    │ own inode    │
│ B+tree       │ B+tree       │ B+tree       │ B+tree       │
└──────────────┴──────────────┴──────────────┴──────────────┘
Each allocation group is an independent allocator with its own locks,
so concurrent writers in different directories rarely contend.
```

1. **Parallel allocation** through allocation groups.
2. **Extents + delayed allocation** (ext4 has both too): blocks are chosen at writeback time, when the final size is known, so a 10 MB image usually lands in one or a few contiguous extents.
3. **Scales** to very large filesystems and directories with B+tree indexes.

**btrfs when the host needs it:**

```bash
btrfs subvolume snapshot -r /images /snapshots/images-$(date +%Y%m%d)  # instant, COW-shared
mount -o compress=zstd /dev/sdb /images   # JPEG/PNG/WebP are already compressed;
                                          # btrfs detects incompressible data and skips it
```

**The staff-level point: avoid one-file-per-image at scale.** Facebook's Haystack paper (2010) showed that reading a photo from a regular filesystem cost several disk operations just for directory and inode metadata. Their fix: pack many images into large append-only files and keep an in-memory index (`image id → file, offset, size`), so each read is one disk operation. Object stores do the equivalent internally. With a CDN in front (Q9 in Networks), the origin's filesystem mostly serves cache misses anyway.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Allocation awareness** | Explains extents and delayed allocation (and that ext4 has it too) |
| **Parallelism** | Knows XFS AGs reduce lock contention on parallel writes |
| **COW** | Understands snapshot/reflink mechanics, btrfs RAID5/6 caveat |
| **Real trade-offs** | Recognises the metadata problem of billions of small files; object storage / Haystack |

---

## 9. IPC Mechanisms

**Q:** "Design an inter-process communication channel between a high-frequency trading engine (latency-critical, in C++) and a risk management service (in Go). Compare pipes, Unix domain sockets, shared memory, and message queues. Which would you use?"

**What They're Really Testing:** Whether you understand the latency characteristics of each IPC mechanism and when zero-copy shared memory justifies its complexity.

### Answer

!!! tip "30-second answer"
    For the hot path, a **single-producer/single-consumer ring buffer in shared memory** (`shm_open` + `mmap`, or a file in hugetlbfs/tmpfs) with acquire/release atomics: no syscalls, no kernel copies, latency dominated by moving a cache line between cores (~100 ns on one socket). The consumer must busy-poll (burning a core) or fall back to an `eventfd`/futex wakeup, which brings back µs latency. Use a Unix domain socket for the control plane and anything that isn't latency-critical, because it gives you framing, backpressure and crash detection for free. Also ask the design question: a **pre-trade** risk check that can block an order belongs **inside** the C++ engine; a Go service is better suited to post-trade/aggregate risk fed asynchronously.

**IPC comparison** (same host; orders of magnitude, measure on your hardware):

| Mechanism | One-way latency | Copies | Notes |
|-----------|---------|-----------|------------|
| Pipe | Several µs (with wakeup) | 2 (user → kernel → user) | Byte stream, unidirectional, parent/child or named (FIFO) |
| Unix domain socket | Several µs | 2 | Bidirectional, message boundaries with `SOCK_SEQPACKET`, can pass fds and credentials; no TCP/IP stack involved |
| POSIX message queue | Several µs | 2 | Kernel-managed, message priorities, bounded |
| Shared memory + polling | ~100 ns (cache-line transfer between cores) | 0 kernel copies | You build synchronization, framing and recovery yourself |
| Network broker (Kafka, NATS) | 100s of µs to ms | Many | Durable, cross-host, decoupled; not for a µs budget |

**Shared memory ring buffer layout:**

```
┌─────────────── shared memory segment (mmap, MAP_SHARED) ───────────────┐
│ cache line 0: head (written only by producer)                          │
│ cache line 1: tail (written only by consumer)    ← separate lines:     │
│ cache line 2: capacity, version, ...               no false sharing    │
├────────────────────────────────────────────────────────────────────────┤
│ slot 0 │ slot 1 │ slot 2 │ ...                              │ slot N-1 │
│ 40-byte fixed-layout Order records, N = power of two                    │
└────────────────────────────────────────────────────────────────────────┘
```

```cpp
// C++ trading engine — producer (single producer, single consumer)
#include <atomic>
#include <cstdint>
#include <cstring>

struct alignas(64) Cursor { std::atomic<uint64_t> v{0}; };

struct RingHeader {
    Cursor head;               // next slot the producer writes (only producer stores)
    Cursor tail;               // next slot the consumer reads (only consumer stores)
    uint64_t capacity;         // power of two
};

struct Order {                 // fixed layout, no pointers: both languages must agree
    int64_t  order_id;
    uint32_t symbol;
    uint32_t _pad0;
    uint64_t price;            // fixed-point
    uint64_t quantity;
    uint8_t  side;             // 0 = buy, 1 = sell
    uint8_t  order_type;       // 0 = market, 1 = limit
    uint8_t  _pad1[6];
};
static_assert(sizeof(Order) == 40, "layout must match the Go struct");
static_assert(std::atomic<uint64_t>::is_always_lock_free, "needs lock-free 64-bit atomics");

class ShmPublisher {
    RingHeader* hdr_;
    Order* slots_;
public:
    ShmPublisher(RingHeader* h, Order* s) : hdr_(h), slots_(s) {}

    bool try_publish(const Order& o) {
        uint64_t head = hdr_->head.v.load(std::memory_order_relaxed);   // we own head
        uint64_t tail = hdr_->tail.v.load(std::memory_order_acquire);   // consumer's progress
        if (head - tail == hdr_->capacity) return false;                // full: caller decides
        std::memcpy(&slots_[head & (hdr_->capacity - 1)], &o, sizeof o);
        hdr_->head.v.store(head + 1, std::memory_order_release);        // publish the slot
        return true;
    }
};
```

```go
// Go risk service — consumer
type Order struct { // must match the C++ layout byte for byte (40 bytes)
	OrderID   int64
	Symbol    uint32
	_         uint32
	Price     uint64
	Quantity  uint64
	Side      uint8
	OrderType uint8
	_         [6]uint8
}

// Mirrors the C++ RingHeader: head and tail on separate 64-byte cache lines.
type ringHeader struct {
	head     atomic.Uint64
	_        [56]byte
	tail     atomic.Uint64
	_        [56]byte
	capacity uint64
}

type ShmConsumer struct {
	hdr   *ringHeader // points into the mmap'ed segment
	slots []Order     // unsafe.Slice over the segment after the header
}

func (c *ShmConsumer) Run(ctx context.Context, handle func(Order)) {
	mask := c.hdr.capacity - 1
	for ctx.Err() == nil {
		tail := c.hdr.tail.Load() // we own tail
		head := c.hdr.head.Load() // pairs with the producer's release store
		if tail == head {
			runtime.Gosched() // or spin with backoff, or block on an eventfd
			continue
		}
		o := c.slots[tail&mask]    // copy the record out before releasing the slot
		c.hdr.tail.Store(tail + 1) // hand the slot back to the producer
		handle(o)
	}
}
```

Why it's correct: the producer writes the slot, then publishes `head` with a **release** store; the consumer **acquires** `head` before reading the slot, so it sees the full record. The consumer copies the record out before advancing `tail`, so the producer never overwrites a slot that is still being read. Each cursor has exactly one writer, so no CAS is needed. (Go's `sync/atomic` operations are sequentially consistent, which is stronger than needed and compatible.) `volatile` is **not** a substitute: it gives neither atomicity nor ordering in C++.

**Why not pipes or sockets for the hot path:** each message is two copies through the kernel plus a syscall on each side, and if the consumer is asleep, a wakeup and context switch (µs, with scheduler jitter in the tail).

**Risks of shared memory:**

1. **Crash recovery:** a crashed peer leaves the segment in an unknown state. Add a version/epoch field and heartbeats; restart both sides cleanly.
2. **Layout drift:** C++ and Go structs must match exactly (padding, endianness); generate both from one schema or `static_assert` sizes on both sides.
3. **No Go pointers** in shared memory; the Go GC doesn't know about it.
4. **NUMA:** put the segment and both pinned threads on the same socket; cross-socket cache-line transfers cost noticeably more.
5. **Go runtime jitter:** GC assists and scheduling can delay the consumer; lock the polling goroutine to an OS thread (`runtime.LockOSThread`) and pin that thread.
6. **Security:** both processes can corrupt each other; only for mutually trusted processes.

Production-grade options instead of rolling your own: Aeron IPC, the LMAX Disruptor pattern, Chronicle Queue.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Quantitative latency** | Order-of-magnitude numbers and where they come from (copies, syscalls, wakeups, cache lines) |
| **Memory ordering** | Acquire/release on head/tail; knows `volatile` isn't enough |
| **NUMA awareness** | Pins memory and threads to the same NUMA node |
| **Design judgment** | Pre-trade risk in-process; shm only for the hot path; crash safety |

---

## 10. Signals & Async Signal Safety

**Q:** "You're debugging a production crash in a Go service that embeds a C library via cgo. The library uses `SIGALRM` for timeouts, but it's causing random `EINTR` errors on system calls. What's happening and how do you fix it?"

**What They're Really Testing:** Deep understanding of signal delivery, interrupted syscalls, and reentrancy — with a multilingual twist.

### Answer

!!! tip "30-second answer"
    A process-directed signal like `SIGALRM` is delivered to **any** thread that doesn't block it. If that thread is in a blocking syscall and the handler wasn't installed with `SA_RESTART` (or the syscall is one that never restarts, like `epoll_wait`, `poll`, `nanosleep`), the syscall fails with **EINTR**. In a Go program there are many threads, so the C library's alarm interrupts syscalls in unrelated threads, and C code that doesn't retry on EINTR fails "randomly". Separately, if the C library installs its handler **without `SA_ONSTACK`**, Go crashes when the signal lands on a Go thread. Fix: stop using process-wide signals for timeouts (per-call timeouts, `timerfd`, or POSIX timers with `SIGEV_THREAD`), make C code retry EINTR, and if a handler must exist, install it with `SA_RESTART | SA_ONSTACK`.

**What happens:**

```c
// The C library's timeout mechanism
void set_timeout_ms(int ms) {
    struct itimerval it = {0};
    it.it_value.tv_sec  = ms / 1000;
    it.it_value.tv_usec = (ms % 1000) * 1000;
    signal(SIGALRM, timeout_handler);   // process-wide disposition
    setitimer(ITIMER_REAL, &it, NULL);  // one timer per PROCESS, not per thread
}
```

```
Go process: ~10+ OS threads (GOMAXPROCS Ps, sysmon, threads blocked in cgo/syscalls)

Thread 7 (C code): read(fd, ...) blocking
Thread 3 (Go):     running goroutines
                  SIGALRM fires → kernel picks ANY thread not blocking it
                  → if thread 7: read() returns -1, errno = EINTR
                    (unless SA_RESTART and read is restartable)
```

Problems this design causes in a multithreaded process:

1. **EINTR in C code:** C code that treats `-1/EINTR` as a fatal error breaks. Some calls are never restarted even with `SA_RESTART` (see `signal(7)`): `epoll_wait`, `poll`, `select`, `nanosleep`, socket calls with timeouts set.
2. **One timer per process:** two threads calling `set_timeout_ms` overwrite each other's alarm.
3. **Handler on the wrong stack:** Go runs signal handlers on an alternate signal stack because goroutine stacks are small. A non-Go handler installed without `SA_ONSTACK` makes the Go runtime abort ("non-Go code set up signal handler without SA_ONSTACK flag").
4. **Go side:** Go installs its own handlers with `SA_RESTART`, and since Go 1.14 the runtime itself sends `SIGURG` to threads for **asynchronous preemption**. The standard library retries EINTR internally, but C code in the same process may also see interrupted calls. (`GODEBUG=asyncpreemptoff=1` is a diagnostic, not a fix.)

**The fix — remove signal-based timeouts from the library:**

```c
// Per-operation timeout without signals: wait for readiness with a timeout
#include <errno.h>
#include <poll.h>
#include <unistd.h>

ssize_t read_with_timeout(int fd, void *buf, size_t n, int timeout_ms) {
    struct pollfd p = { .fd = fd, .events = POLLIN };
    int r;
    do {
        r = poll(&p, 1, timeout_ms);       /* simplification: restarts with the full timeout */
    } while (r == -1 && errno == EINTR);
    if (r == 0) { errno = ETIMEDOUT; return -1; }
    if (r == -1) return -1;
    ssize_t got;
    do { got = read(fd, buf, n); } while (got == -1 && errno == EINTR);
    return got;
}
```

```c
// Or a dedicated timer thread using timerfd (Linux): timers become readable fds
#include <stdint.h>
#include <sys/timerfd.h>
#include <unistd.h>

void *timer_thread(void *arg) {
    int tfd = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC);
    struct itimerspec ts = {
        .it_value    = { .tv_sec = 0, .tv_nsec = 100 * 1000000 },   /* first expiry: 100 ms */
        .it_interval = { .tv_sec = 0, .tv_nsec = 100 * 1000000 },   /* then every 100 ms */
    };
    timerfd_settime(tfd, 0, &ts, NULL);
    for (;;) {
        uint64_t expirations;
        if (read(tfd, &expirations, sizeof expirations) == sizeof expirations)
            handle_timeout(expirations);    /* normal thread context: any function allowed */
    }
    return NULL;
}
```

If you can't change the library: install its handler yourself with `sigaction` and `SA_RESTART | SA_ONSTACK`, and wrap its blocking calls in EINTR retry loops. On the Go side, don't fight the runtime: `signal.Notify` is for Go code that wants to **receive** signals; `signal.Ignore(SIGALRM)` sets the disposition to ignore for the whole process (which would also disable the C library's handler), and neither masks signals per thread.

**Async-signal-safe functions:** a handler can interrupt the program **anywhere**, including inside `malloc` while it holds the arena lock. Only functions listed in `signal-safety(7)` may be called from a handler.

| Safe (examples) | Unsafe (examples) |
|---|---|
| `write`, `read`, `_exit`, `sigaction`, `sem_post`, `kill`, `clock_gettime` | `malloc`/`free`, `printf` and stdio, `pthread_mutex_lock`, logging libraries, anything in the Go runtime |

Also save and restore `errno` in the handler, and only touch variables of type `volatile sig_atomic_t` (or lock-free atomics).

**Safer patterns for real signal handling:**

```c
// Self-pipe trick: the handler only writes a byte; the event loop does the work
static int sigpipe_fds[2];                 /* both ends O_NONBLOCK | O_CLOEXEC (pipe2) */

static void handler(int sig) {
    int saved = errno;
    unsigned char b = (unsigned char)sig;
    (void)write(sigpipe_fds[1], &b, 1);    /* async-signal-safe; drops if pipe is full */
    errno = saved;
}
/* Register sigpipe_fds[0] with epoll; when readable, drain it and handle signals normally. */
```

Linux alternatives: `signalfd` (block the signal in **all** threads with `pthread_sigmask`, then read signals from an fd) or a dedicated thread in `sigwait()`. Both need the signal blocked everywhere, which you control in C programs but not easily in Go's runtime threads; in Go, use `signal.Notify` and a goroutine.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **EINTR** | Knows which syscalls restart with SA_RESTART and which never do |
| **Go+C interaction** | Process-directed signals hit any thread; SA_ONSTACK requirement; Go's SIGURG preemption |
| **Async safety** | Lists async-signal-safe functions, knows why malloc is unsafe, saves errno |
| **Fix** | Removes signal-based timeouts (poll timeout, timerfd); self-pipe / signalfd for real signals |

---

## 11. cgroups & Namespaces (Container Isolation)

**Q:** "Explain how Docker/LXC achieves resource isolation using Linux cgroups and namespaces. Specifically, how does memory cgroup prevent one container from starving another? And how does CPU cgroup handle burst credits?"

**What They're Really Testing:** Whether you understand container isolation at the kernel level, not just Docker CLI usage.

### Answer

!!! tip "30-second answer"
    **Namespaces** control what a process can **see** (PIDs, network stack, mounts, hostname, IPC, users, cgroup tree, time). **cgroups** control what it can **use** (CPU, memory, I/O, PIDs). With **cgroup v2** (the unified hierarchy, required by Kubernetes 1.35's kubelet by default), memory isolation comes from `memory.max` (hard cap, OOM inside the cgroup), `memory.high` (throttle and reclaim before the cap), and `memory.min`/`memory.low` (protection from other cgroups' pressure). CPU has two separate knobs: `cpu.weight` shares CPU proportionally **only under contention**, while `cpu.max` is a hard quota per period that throttles even on an idle machine; `cpu.max.burst` (Linux 5.14) lets a group bank unused quota for short bursts. Namespaces and cgroups are not a security boundary on their own: add seccomp, capabilities dropping, LSMs (AppArmor/SELinux), user namespaces, or a sandbox (gVisor, Kata, Firecracker).

**Two pillars of container isolation:**

| Namespaces (what you can see) | Isolates |
|---|---|
| PID | Process IDs; container's first process is PID 1 (must reap zombies and handle signals) |
| Network | Interfaces, routes, iptables/nftables, ports |
| Mount | Mount table (with pivot_root into the image's rootfs) |
| UTS | Hostname |
| IPC | System V IPC, POSIX message queues |
| User | UID/GID mapping: root in the container maps to an unprivileged host UID. Kubernetes: `hostUsers: false`, GA in 1.36 |
| Cgroup | View of the cgroup tree |
| Time | `CLOCK_MONOTONIC`/`BOOTTIME` offsets (Linux 5.6) |

| cgroup v2 controllers (what you can use) | Key files |
|---|---|
| cpu | `cpu.weight`, `cpu.max`, `cpu.max.burst`, `cpu.stat`, `cpu.pressure` |
| memory | `memory.max`, `memory.high`, `memory.low`, `memory.min`, `memory.swap.max`, `memory.oom.group`, `memory.events`, `memory.pressure` |
| io (was `blkio` in v1) | `io.max`, `io.weight`, `io.latency` |
| cpuset | `cpuset.cpus`, `cpuset.mems` |
| pids | `pids.max` (fork-bomb protection) |

**cgroup v1 vs v2:** v1 had a separate hierarchy per controller, which made combined policies (e.g. writeback I/O attributed to the right memory cgroup) impossible. v2 has one tree, a single writer per subtree (systemd or the container runtime), and features v1 lacks: PSI pressure files, `memory.high`, `memory.oom.group`, proper writeback accounting. Kubernetes 1.35 deprecated cgroup v1: the kubelet refuses to start on v1 nodes unless `failCgroupV1: false` is set.

**Memory controller:**

```
memory.max  = 4G      hard limit: allocation beyond it triggers reclaim inside the
                      cgroup, then the OOM killer scoped to this cgroup
memory.high = 3.5G    throttle: above it, allocating tasks are slowed and forced to
                      reclaim; never OOM-kills by itself
memory.low  = 1G      best-effort protection from reclaim caused by OTHER cgroups
memory.min  = 512M    hard protection from reclaim
memory.swap.max = 0   no swap for this group
memory.oom.group = 1  on OOM, kill every process in the cgroup together
```

**How it prevents starvation:**

```
Host 16 GB. Container A: max 4G. Container B: max 4G, low 2G.

A leaks memory:
  A's usage reaches memory.high → A's own allocations get throttled and reclaim
                                  A's page cache (A slows down, B unaffected)
  A reaches memory.max          → reclaim within A fails → OOM killer picks a
                                  process in A (or all of A with oom.group)
  B never pays for A's leak.

Host-wide pressure (sum of usage close to RAM):
  kswapd / direct reclaim scans all cgroups, but skips B's memory below
  memory.low (and never touches memory below memory.min).
```

Important: the cgroup charge includes **page cache** and kernel memory (slab, socket buffers) attributed to the group, not just process RSS (Q12).

**CPU controller:**

```
cpu.weight = 200                    # 1–10000, default 100. Proportional share, ONLY under contention
cpu.max    = "400000 100000"        # quota period (µs): 400 ms of CPU per 100 ms = 4 CPUs max
cpu.max.burst = 200000              # may bank up to 200 ms of unused quota (must be ≤ quota)
```

```
Burst accounting (100 ms periods, quota 400 ms, burst 200 ms):
Period 1: uses 200 ms   → 200 ms unused → bank = min(200, 200) = 200 ms
Period 2: uses 550 ms   → 400 quota + 150 from bank → bank = 50 ms, no throttling
Period 3: uses 500 ms   → 400 quota + 50 bank, then THROTTLED for the rest of the period
```

**The quota trap:** a multi-threaded app with `cpu.max = 2 CPUs` can burn its 200 ms of quota in the first 25 ms of a period on 8 threads, then sit throttled for 75 ms, even on an idle node. That shows up as p99 latency spikes with low average CPU. Many teams therefore set Kubernetes CPU **requests** (→ `cpu.weight`) but no CPU **limits** for latency-sensitive services, and fix runtimes to see the right CPU count (Go 1.25 sets `GOMAXPROCS` from the cgroup CPU limit; the JVM has been container-aware for years).

**Production monitoring (cgroup v2 paths):**

```bash
CG=/sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/.../cri-containerd-<id>.scope
cat $CG/memory.pressure
#   some avg10=2.35 avg60=1.88 avg300=0.56 total=1234567
#   full avg10=0.89 avg60=0.45 avg300=0.12 total=456789
#   some = % of time at least one task stalled on memory; full = all tasks stalled
cat $CG/memory.events        # high, max, oom, oom_kill counters
cat $CG/cpu.stat
#   nr_periods 1000
#   nr_throttled 45          ← 4.5% of periods throttled
#   throttled_usec 1500000   ← 1.5 s total
```

PSI (pressure stall information) is the best saturation signal: a sustained non-zero `full` means the workload is losing real time to memory pressure. What threshold to alert on depends on the workload; establish a baseline. Tools like systemd-oomd act on PSI before the kernel OOM killer has to.

**eBPF in this picture:** eBPF programs can be attached per cgroup (socket filtering, device access control in cgroup v2, which replaced the v1 devices controller), and observability tools (bcc, bpftrace, Cilium/Tetragon, Pixie) use eBPF to attribute syscalls, network flows and latency to containers without changing the apps.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Namespace vs cgroup** | Clearly separates what you see vs what you can use; knows it's not a full security boundary |
| **Memory reclaim** | memory.max vs high vs low/min, page cache counted, OOM scoped to the cgroup |
| **CPU** | Weight vs quota, burst accounting, throttling trap on idle nodes |
| **Currency** | cgroup v2 required by recent Kubernetes, user namespaces, PSI |
| **Production monitoring** | memory.pressure, memory.events, cpu.stat |

---

## 12. OOM Killer & Memory Overcommit

**Q:** "Your Kubernetes pod (memory limit 4GB) was OOM-killed even though top shows RSS = 3.5GB. You also see a balloon process allocating 1GB. What happened? How do memory overcommit and OOM killer scoring work?"

**What They're Really Testing:** Understanding of memory overcommit, OOM killer score calculation, and the gap between RSS and actual memory pressure.

### Answer

!!! tip "30-second answer"
    The limit applies to the container's **cgroup**, which is charged for **all** its processes plus page cache, tmpfs/`emptyDir: Medium: Memory`, and kernel memory such as page tables and socket buffers. One process's RSS in `top` is not that number. Redis at 3.5 GB plus a balloon touching 1 GB is already over 4 GB, so the cgroup hit `memory.max`, reclaim couldn't free enough (anonymous memory without swap can't be reclaimed), and the OOM killer ran **inside that cgroup**. It picks the process with the highest badness (mostly memory size), so the big Redis process dies, not the small newcomer. On cgroup v2, Kubernetes 1.28+ sets `memory.oom.group=1`, so the **whole container** is killed. Overcommit (`vm.overcommit_memory`) decides whether `malloc`/`mmap` succeeds up front; it doesn't change cgroup limits.

**Where the cgroup charge comes from:**

```
Container cgroup charge (memory.current) ≈
    anonymous memory of ALL processes       (Redis heap ~3.0 GB + balloon 1.0 GB)
  + page cache for files read/written       (reclaimable, if clean)
  + shmem / tmpfs (incl. memory-backed emptyDir)  (NOT reclaimable without swap)
  + kernel memory charged to the group      (page tables, slab, socket buffers)

Redis RSS 3.5 GB = anon ~3.0 GB + file-backed pages; shared library pages are
counted in each process's RSS but charged to the cgroup only once.
```

```bash
cat /sys/fs/cgroup/<container>/memory.current        # what the limit is compared against
cat /sys/fs/cgroup/<container>/memory.stat           # anon, file, shmem, slab, sock, ...
cat /sys/fs/cgroup/<container>/memory.events         # oom, oom_kill counters
dmesg | grep -i -A20 "memory cgroup out of memory"   # who was killed and why
```

Note the different thresholds: the **kernel** OOM-kills at `memory.max`; the **kubelet** evicts pods when the **node** runs low, based on "working set" (`usage − inactive_file`), which is also what `kubectl top` shows.

**Memory overcommit modes (`vm.overcommit_memory`):**

| Mode | Behaviour | When |
|---|---|---|
| **0** (default) heuristic | Refuses only obviously impossible single allocations; otherwise allows overcommitting. `overcommit_ratio` is **not** used in this mode | General purpose |
| **1** always | Never refuses; failures surface later as OOM kills | **Redis** recommends it so `fork()` for BGSAVE succeeds even though the child could, in theory, touch all of the parent's memory |
| **2** strict | `CommitLimit = swap + RAM × overcommit_ratio/100` (or `overcommit_kbytes`); `malloc`/`mmap` return failure beyond it | Systems that prefer allocation failures to OOM kills. Rarely right for container hosts: JVMs, Go and others reserve large virtual ranges they never touch |

Even mode 2 doesn't prevent cgroup OOM kills: the cgroup limit is a separate mechanism.

**OOM killer scoring (modern kernels):**

```
badness(p) = RSS(p) + swap(p) + page_table_bytes(p)          (in pages)
           + oom_score_adj(p) × (allowed_memory / 1000)
allowed_memory = the cgroup limit for a cgroup OOM, or RAM + swap for a global OOM

/proc/<pid>/oom_score     → badness normalized to 0..1000 (+ adj)
/proc/<pid>/oom_score_adj → -1000 (never kill) .. +1000 (kill first); inherited by children
```

Older heuristics (process runtime, number of children, a bonus for root processes) were removed; today it is essentially "biggest memory user, adjusted by `oom_score_adj`".

**How Kubernetes sets `oom_score_adj` (per container, by QoS class):**

| QoS class | Condition | oom_score_adj |
|---|---|---|
| Guaranteed | requests = limits for every container (CPU and memory) | **-997** |
| Burstable | some requests set, not Guaranteed | `min(max(2, 1000 − 1000 × memory_request / node_capacity), 999)`: the larger the request relative to the node, the more protected |
| BestEffort | no requests or limits | **1000** |

These matter for **node-level** (global) OOMs. Inside one container, every process has the same `oom_score_adj`, so size decides.

**Preventing unnecessary OOM kills:**

1. **Size limits from measurement:** request = limit for memory on critical services (Guaranteed QoS), with headroom for page cache, fork-time COW (Redis BGSAVE can need close to 2× under heavy writes), and tmpfs.
2. **Don't run sidecar-like helpers in the same container**: give them their own container and limit so they can't push the main process over.
3. **Make runtimes cgroup-aware:** JVM `-XX:MaxRAMPercentage`, Go `GOMEMLIMIT` (soft limit that makes the GC work harder before the hard limit).
4. **Protect critical daemons on the node:** kubelet `system-reserved`/`kube-reserved`, and `memory.min` for system slices.
5. **Alert on pressure before kills:** `memory.events` `high` counter, PSI `memory.pressure`.
6. If you truly want only the offending process killed (e.g. a supervisor with worker processes), kubelet's `singleProcessOOMKill: true` (1.32+) restores per-process kills on cgroup v2.

Fragmentation is a separate, rarer cause: a high-order (contiguous) kernel allocation can fail even with free memory. Check `/proc/buddyinfo` (`/sys/kernel/debug/extfrag/unusable_index` with debugfs) and trigger compaction with `echo 1 > /proc/sys/vm/compact_memory`.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **RSS ≠ all** | Explains cgroup charge (all processes, page cache, shmem, kernel memory) vs one process's RSS |
| **oom_score** | Knows badness = memory size + adj, scoped to the cgroup; old heuristics gone |
| **Kubernetes integration** | QoS → oom_score_adj, memory.oom.group since 1.28, eviction vs OOM kill |
| **Mitigation** | Right-sized limits, GOMEMLIMIT/MaxRAMPercentage, overcommit=1 for Redis, PSI alerts |

---

> *Master these OS topics and you'll be prepared for the lowest-level Staff/Principal interviews at FAANG, database companies, and infrastructure platform teams.*
