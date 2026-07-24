# 🧠 Job Scheduling System LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a concurrent job scheduling system.

---

## 📊 Class Diagram

![](job-scheduling-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

**Functional:**
- One-time, recurring, and priority-based job execution
- Retry with exponential backoff
- Job timeout and cancellation
- DAG-based dependencies between jobs

**Non-functional / Concurrency:**
- Handle I/O-bound (email, HTTP) and CPU-bound (data processing) jobs
- Maximum N concurrent executions
- Graceful shutdown (cancel running jobs, drain queue)
- Support multiple concurrency models (async, thread, process)

---

## Phase 1: Concurrency Model Decision

**This is the KEY design decision — everything else flows from it.**

| Model | Pros | Cons |
|-------|------|------|
| **Threading** (`threading`) | Familiar, preemptive, good for blocking I/O | GIL for CPU, heavy (~8KB/thread), race conditions |
| **Multiprocessing** (`multiprocessing`) | True parallelism, own GIL | Heavy (~50MB/proc), IPC overhead, slow startup |
| **Async** (`asyncio`) | Lightweight (~100 bytes/task), no GIL issues, cooperative | Single-thread, need async libraries, no CPU parallelism |
| **Hybrid** (All three) | Right tool for each job | Complexity, need to manage 3 executors |

**Decision: Hybrid.** Let each job declare its model via `ConcurrencyModel` enum. The executor dispatches to the right backend.

---

## Phase 2: Async-First Architecture

```python
# Why asyncio for the scheduler core?
# 1. The scheduler spends 99% of time WAITING (for jobs, for timeouts)
# 2. asyncio uses ~100 bytes per task vs ~8KB per thread
# 3. No GIL contention → no race conditions on scheduler state
# 4. Cooperative multitasking → deterministic interleaving

class JobScheduler:
    async def start(self):
        # Create_task is how we spawn concurrent work in asyncio
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="scheduler-loop"
        )
        self._workers = [
            asyncio.create_task(self._worker_loop(i), name=f"worker-{i}")
            for i in range(self._num_workers)
        ]

    async def stop(self):
        # Event-driven shutdown via asyncio.Event
        self._stop_event.set()  # Signal all coroutines
        # Cancel remaining tasks
        for w in self._workers:
            w.cancel()
```

---

## Phase 3: Producer-Consumer with asyncio.Queue

**The problem:** Scheduler creates jobs faster than workers can execute them. We need a buffer.

**The solution:** `asyncio.Queue` — an async-safe FIFO queue.

```python
# Producer: scheduler loop
await self._job_queue.put(job)   # Blocks if queue at maxsize

# Consumer: worker coroutines
job = await self._job_queue.get()  # Blocks if queue empty
# ... execute ...
self._job_queue.task_done()        # Signal completion to queue.join()
```

**Why asyncio.Queue over threading.Queue or list + lock:**
- `asyncio.Queue.get()` blocks COOPERATIVELY (yields to event loop)
- No busy-waiting or polling
- Built-in maxsize for backpressure
- `join()` / `task_done()` for completion tracking

---

## Phase 4: Triple-Dispatch Executor

**The problem:** Different jobs need different execution models.

**The solution:** `AsyncJobExecutor.execute()` dispatches based on `ConcurrencyModel`.

```python
async def execute(self, job: Job) -> bool:
    async with self._semaphore:  # Limit concurrent jobs
        if job.concurrency_model == ASYNC:
            # Run directly on event loop (cooperative)
            success = await asyncio.wait_for(
                job.execute_async(), timeout=job.timeout_seconds
            )
        elif job.concurrency_model == THREAD:
            # Offload to ThreadPoolExecutor (GIL-contended)
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                self._thread_pool, job.execute_sync
            )
        elif job.concurrency_model == PROCESS:
            # Offload to ProcessPoolExecutor (true parallelism)
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                self._process_pool, job.execute_sync
            )
```

**Why not just use one model for everything?**
- ALL async → CPU jobs block event loop → everything stalls
- ALL thread → CPU jobs fight over GIL → no parallelism
- ALL process → I/O jobs pay heavy IPC cost → wasteful

---

## Phase 5: Semaphore-based Concurrency Limiting

**The problem:** Without limits, 1000 concurrent jobs will overwhelm resources.

**The solution:** `asyncio.Semaphore(N)` — only N jobs run simultaneously.

```python
class AsyncJobExecutor:
    def __init__(self, max_concurrent=3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # Semaphore acts as a resource counter
        # - acquire() decrements (or blocks if 0)
        # - release() increments (wakes up a waiter)

    async def execute(self, job):
        async with self._semaphore:
            # Only max_concurrent jobs reach here
            await self._run_job(job)
        # Semaphore released automatically on exit
```

**Semaphore vs Queue for concurrency limiting:**
- Queue: controls how many items are BUFFERED
- Semaphore: controls how many items are ACTIVE
- We use BOTH: Queue for buffering, Semaphore for active limits

---

## Phase 6: Deadlock Prevention

**The problem:** `asyncio.Lock` is NOT reentrant. If a task holds a lock and gets cancelled, the finally block that tries to acquire the same lock will deadlock.

**The solution:** Snapshot-then-cancel pattern.

```python
# ❌ WRONG - deadlocks on cancel
async def cancel_all(self):
    async with self._lock:          # Acquire lock
        for task in self._tasks:    # Cancel triggers finally...
            task.cancel()           # ...which tries to acquire lock → DEADLOCK

# ✅ CORRECT - snapshot, then cancel outside lock
async def cancel_all(self):
    async with self._lock:
        tasks = list(self._tasks)   # Snapshot under lock
    for task in tasks:              # Cancel outside lock
        if not task.done():
            task.cancel()
```

**General deadlock prevention rules:**
1. Never acquire a lock inside a finally/callback that might be called while holding that lock
2. Always snapshot data under a lock, then work outside the lock
3. Document lock ordering if using multiple locks

---

## Phase 7: Race Condition Demo

**The problem:** Interviewers want to see that you understand thread safety at the hardware level.

**The solution:** `UnsafeCounter` vs `SafeCounter` — live demo.

```python
class UnsafeCounter:
    def increment(self, amount):
        for _ in range(amount):
            temp = self.count      # 1. LOAD
            # ⏳ THREAD SWITCH HERE
            self.count = temp + 1  # 2. ADD + 3. STORE

# With 2 threads × 100K iterations:
# Expected: 200,000
# Unsafe result: ~150,000–180,000 (lost updates)
# Safe result: 200,000 (always correct)
```

**Why this demonstrates CS knowledge:**
- Shows understanding that `+=` is NOT atomic (3 CPU instructions)
- Demonstrates context switch window vulnerability
- Proves that locks provide mutual exclusion

---

## Phase 8: Graceful Shutdown

**The problem:** Killing threads mid-execution leaves corrupted state.

**The solution:** Three-phase shutdown with cooperative cancellation.

```python
async def stop(self):
    # Phase 1: Signal → workers finish current job, stop accepting
    self._stop_event.set()

    # Phase 2: Cancel → CancelledError propagates, cleanup runs
    await self._executor.cancel_all()

    # Phase 3: Drain → workers exit their loops naturally
    await asyncio.gather(*self._workers, return_exceptions=True)
```

**Why this matters:** Shows understanding that cancellation is a COOPERATIVE protocol, not a forceful kill.

---

## Phase 9: Anti-Starvation with Aging

**The problem:** Priority scheduling can starve low-priority jobs.

**The solution:** Priority aging — boost priority proportional to wait time.

```python
def effective_priority(job):
    wait_seconds = (now - job.created_at).total_seconds()
    age_bonus = wait_seconds * 0.1  # +1 priority per 10 seconds waiting
    return job.priority.value + age_bonus
```

**Guarantee:** Every job eventually runs (no infinite starvation) as long as `age_factor > 0`.

---

## Quick Checklist

| Concept | Implemented? | Where |
|---------|-------------|-------|
| ✅ Async/await architecture | Yes | `JobScheduler`, `AsyncJobExecutor` |
| ✅ GIL explanation | Yes | `ConcurrencyModel` docstrings, `AsyncJobExecutor.execute()` |
| ✅ Race condition demo | Yes | `UnsafeCounter` vs `SafeCounter` |
| ✅ Deadlock prevention | Yes | `cancel_all()` snapshot pattern |
| ✅ Semaphore limiting | Yes | `AsyncJobExecutor._semaphore` |
| ✅ Producer-Consumer | Yes | `_scheduler_loop` + `_worker_loop` + `asyncio.Queue` |
| ✅ Cooperative cancellation | Yes | `CancelledError` handlers |
| ✅ Exponential backoff | Yes | `exponential_backoff()` function |
| ✅ Context managers | Yes | `TimingContext`, `_AsyncPendingLock` |
| ✅ Anti-starvation aging | Yes | `WeightedFairScheduler` |
| ✅ Command Pattern | Yes | `Job` ABC + concrete subclasses |
| ✅ Strategy Pattern | Yes | `SchedulingStrategy` + 4 implementations |
| ✅ Facade Pattern | Yes | `JobScheduler` |
