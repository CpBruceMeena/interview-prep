# 🏗️ Job Scheduling System — High-Level Design

> **Target Level:** Senior/Staff Engineer  
> **Core CS Concepts:** Concurrency models, GIL, race conditions, deadlock prevention, async/await

---

## 1. SYSTEM OVERVIEW

**Purpose:** Reliable distributed job scheduler with support for one-time, recurring, and priority-based execution using multiple concurrency models (async, threading, multiprocessing).

**Scale:** 10K jobs/second throughput, 1M scheduled jobs/day, 100 worker nodes

**Concurrency Models:**
| Model | Type | Best For | GIL Impact |
|-------|------|----------|------------|
| **ASYNC** | Cooperative (event loop) | I/O-bound (network, file) | No GIL contention (single thread) |
| **THREAD** | Preemptive (OS threads) | Mixed workloads | GIL limits CPU-bound parallelism |
| **PROCESS** | True parallelism (separate procs) | CPU-bound (computation) | Each process has its own GIL ✓ |

---

## 2. ASYNC-FIRST ARCHITECTURE

```
┌─────────────────────────────────────────────────────┐
│                  API / Dashboard                     │
│  (Submit jobs, check status, view logs)              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│              asyncio-based Scheduler                  │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │           asyncio.Queue (Producer-Consumer)    │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │
│  │  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │   │   │
│  │  │ (async)  │  │ (async)  │  │ (async)  │   │   │
│  │  └─────┬────┘  └─────┬────┘  └─────┬────┘   │   │
│  └────────┼─────────────┼─────────────┼─────────┘   │
│           │             │             │             │
│  ┌────────▼─────────────▼─────────────▼─────────┐   │
│  │         AsyncJobExecutor                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │
│  │  │ ASYNC    │  │ THREAD   │  │ PROCESS  │   │   │
│  │  │ (event   │  │ (Thread  │  │ (Process │   │   │
│  │  │  loop)   │  │  Pool)   │  │  Pool)   │   │   │
│  │  └──────────┘  └──────────┘  └──────────┘   │   │
│  └──────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────┘
                     │
              ┌──────▼──────┐
              │  PostgreSQL  │
              │  - Job defs  │
              │  - History   │
              └─────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/job-scheduling-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Job Scheduling Sequence — Submit → Queue → Schedule → Execute → Complete. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. CORE CS CONCEPTS IN THIS DESIGN

### 3.1 GIL (Global Interpreter Lock)

```python
"""
The GIL is a mutex that protects CPython's internal state. It ensures
only one thread executes Python bytecode at a time. This means:

  ✅ Thread-based I/O-bound jobs: GIL released during I/O → good parallelism
  ❌ Thread-based CPU-bound jobs: GIL held throughout → NO parallelism
  ✅ Process-based CPU-bound jobs: Each process has its own GIL → TRUE parallelism

┌─────────────┬──────────────────────┬──────────────────────┐
│    Core 1   │      Core 2          │      Core 3          │
├─────────────┼──────────────────────┼──────────────────────┤
│ Thread A    │ Thread B (waiting)   │ Thread C (waiting)   │
│ ┌─────────┐ │ ┌──────────────────┐ │ ┌──────────────────┐ │
│ │GIL held │ │ │ GIL not acquired │ │ │ GIL not acquired │ │
│ │running  │ │ │     waiting      │ │ │     waiting      │ │
│ └─────────┘ │ └──────────────────┘ │ └──────────────────┘ │
└─────────────┴──────────────────────┴──────────────────────┘

With PROCESS model (separate interpreters):
┌─────────────┬──────────────────────┬──────────────────────┐
│ Process A   │ Process B            │ Process C            │
│ ┌─────────┐ │ ┌──────────────────┐ │ ┌──────────────────┐ │
│ │GIL held │ │ │ GIL held         │ │ │ GIL held         │ │
│ │running  │ │ │ running           │ │ │ running           │ │
│ └─────────┘ │ └──────────────────┘ │ └──────────────────┘ │
└─────────────┴──────────────────────┴──────────────────────┘
"""
```

### 3.2 Async/Await — Cooperative Multitasking

```python
"""
asyncio uses an event loop to manage concurrent tasks on a single thread.
Key concept: a coroutine YIELDS control at each 'await' point:

  async def email_job():
      print("Sending...")       # ← runs immediately
      await asyncio.sleep(0.5)  # ← YIELDS: event loop runs other tasks
      print("Sent!")            # ← resumes when sleep completes

  async def report_job():
      print("Generating...")
      await asyncio.sleep(0.3)  # ← YIELDS: email_job runs
      print("Done!")

Event Loop Timeline:
  Time  │  email_job        report_job        scheduler_loop
  ──────┼────────────────────────────────────────────────────
  0.0s  │  "Sending..."     (waiting)         (waiting)
  0.0s  │  await sleep(0.5) "Generating..."   (waiting)
  0.0s  │  (yielded)        await sleep(0.3)  checks queue
  0.3s  │  (yielded)        "Done!" ✓         (waiting)
  0.5s  │  "Sent!" ✓        (done)            dispatches next
"""
```

### 3.3 Race Conditions & Deadlocks

```python
"""
RACE CONDITION:
  Two threads increment a shared counter without synchronization.
  self.count += 1 is THREE CPU instructions:
    1. LOAD count into register
    2. ADD 1 to register
    3. STORE register back to count
  A context switch between steps 1 and 3 causes a LOST UPDATE.

  Demo result (100K iterations each, 2 threads):
    UnsafeCounter: 184,230  (lost 15,770 updates = 7.9%)
    SafeCounter:   200,000  (correct — lock prevents interleaving)

DEADLOCK:
  Thread A acquires Lock 1, then waits for Lock 2.
  Thread B acquires Lock 2, then waits for Lock 1.
  → CIRCULAR WAIT → both threads block forever.

  Prevention strategies used in this codebase:
  1. Lock ordering — always acquire locks in the same order
  2. asyncio.Lock — cooperative (no preemption means no deadlock)
  3. Snapshot-then-cancel — avoid holding lock during cancellation
"""
```

---

## 4. ASYNC SCHEDULER DETAILS

### 4.1 Producer-Consumer with asyncio.Queue

```
┌──────────────┐     put()     ┌────────────────┐     get()     ┌──────────────┐
│  Scheduler   │──────────────▶│ asyncio.Queue  │──────────────▶│  Workers     │
│    Loop      │               │   (bounded)    │               │  (3 tasks)   │
│ (Producer)   │               └────────────────┘               │ (Consumers)  │
└──────────────┘                                                └──────────────┘
```

The `asyncio.Queue` decouples job creation from execution. The scheduler loop adds jobs to the queue, and multiple worker coroutines pull from it. This is the **Producer-Consumer** pattern — fundamental to concurrent systems.

### 4.2 Semaphore-based Concurrency Limiting

```python
"""
asyncio.Semaphore(N) acts as a resource counter:
  - acquire() decrements counter (blocks at 0 via cooperative yield)
  - release() increments counter (wakes up a waiting coroutine)

Unlike threading.Semaphore:
  ✔ Yields to event loop (doesn't block the thread)
  ✔ No GIL involvement
  ✔ Safe to use with async/await
"""
```

### 4.3 Event-driven Shutdown

```python
"""
asyncio.Event signals shutdown across all coroutines:
  1. stop() sets the event → _scheduler_loop sees it and exits
  2. Workers check _stop_event.is_set() on each iteration
  3. Remaining tasks are cancelled via task.cancel()
  4. asyncio.CancelledError propagates for cleanup
"""
```

---

## 5. DATA MODEL

```sql
CREATE TABLE job_definitions (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    concurrency_model TEXT DEFAULT 'async',  -- async, thread, process
    schedule TEXT,  -- cron expression or NULL for one-time
    max_retries INT DEFAULT 3,
    timeout_seconds INT DEFAULT 300,
    dependencies JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE job_executions (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID REFERENCES job_definitions(id),
    status TEXT NOT NULL,  -- pending, running, completed, failed, cancelled, timeout
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    worker_id TEXT,
    retry_count INT DEFAULT 0,
    error_message TEXT,
    concurrency_model TEXT,
    result JSONB
);

CREATE INDEX idx_executions_status ON job_executions(status);
CREATE INDEX idx_executions_job_id ON job_executions(job_id, started_at DESC);
```

---

## 6. CONCURRENCY MODEL SELECTION GUIDE

| Workload Type | Example | Recommended Model | Rationale |
|--------------|---------|------------------|-----------|
| **I/O-bound** | Email, HTTP, DB queries | ASYNC | Single thread, cooperative, no GIL contention |
| **Mixed** | Data processing, file parsing | THREAD | GIL released during I/O sections |
| **CPU-bound** | Matrix multiply, crypto | PROCESS | True parallelism (separate GIL per process) |
| **Long-running** | Video encoding, ML training | PROCESS | Must not block event loop |

---

## 7. MONITORING & OBSERVABILITY

| Metric | Source | What It Reveals |
|--------|--------|----------------|
| Queue depth | `asyncio.Queue.qsize()` | Backlog pressure |
| Active jobs | `AsyncJobExecutor._active_jobs` | Current concurrency |
| Worker task status | `asyncio.all_tasks()` | Health of worker pool |
| p50/p95/p99 latency | TimingContext | Job execution performance |
| GIL contention | `perf` tool | Thread model inefficiency |
| Thread pool utilization | `ThreadPoolExecutor` internal | Capacity planning |

---

## 8. COST ESTIMATION (Monthly)

| Component | Cost | Notes |
|-----------|------|-------|
| Scheduler (async workers) | $300 | Single process, multiple coroutines |
| Thread workers (10 pods) | $1,000 | For mixed workloads |
| Process workers (auto-scale) | $3,000 | CPU-intensive, true parallelism |
| Redis (queue persistence) | $500 | Optional for durability |
| PostgreSQL | $400 | Job definitions, history |
| Monitoring | $200 | Metrics, alerts |
| **Total** | **$5,400** | Scales with workload type |

---

## 9. TRADE-OFF ANALYSIS

| Decision | Option A | Option B | Winner |
|----------|----------|----------|--------|
| Concurrency primitive | `asyncio` | `threading` | ASYNC (for I/O), THREAD (for mixed) |
| CPU parallelism | `ProcessPoolExecutor` | `ThreadPoolExecutor` | PROCESS (true parallelism) |
| Job queue | `asyncio.Queue` | Redis | asyncio.Queue (in-process, no network) |
| Shutdown mechanism | `asyncio.Event` | `threading.Event` | asyncio.Event (cooperative) |
| Concurrency limiting | `Semaphore` | BoundedSemaphore | Semaphore (simpler contract) |
