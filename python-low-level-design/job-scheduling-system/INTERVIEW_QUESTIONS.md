# Job Scheduling System — Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Async/await, GIL, concurrency models, deadlock prevention, CS fundamentals

---

## Question 1: Async/Await Fundamentals

**Interviewer:** *"Explain how async/await works in Python. What happens at each 'await' point?"*

### 🎯 Expected Answer

**The Event Loop Model:**
```python
async def fetch_data(url):
    print("1. Starting fetch")       # Runs synchronously
    data = await http_get(url)       # 2. YIELDS control to event loop
    print("3. Got data")             # 3. Resumes when data arrives
    return data

async def main():
    task1 = asyncio.create_task(fetch_data("/api/1"))
    task2 = asyncio.create_task(fetch_data("/api/2"))
    # Both coroutines are now interleaved on ONE thread
    results = await asyncio.gather(task1, task2)
```

**Key points:**
1. `async def` creates a **coroutine** — it doesn't run until awaited
2. `await` is a **yield point** — the coroutine suspends, event loop runs another task
3. The event loop is a **single-threaded scheduler** — it runs one coroutine at a time
4. No parallelism — this is **concurrency** (interleaved execution), not parallelism

**What the GIL does during async:**
- The GIL is irrelevant for asyncio! Only one thread runs, so there's no GIL contention
- All tasks run on the same thread → no race conditions on shared state **IF** you don't use `run_in_executor`

---

## Question 2: GIL Deep Dive

**Interviewer:** *"How does the Global Interpreter Lock affect your scheduling system? When would you use threads vs processes?"*

### 🎯 Expected Answer

```python
"""
GIL ensures only one thread executes Python bytecode at a time.

For THREAD model:
  - I/O-bound work: GIL is RELEASED during I/O (sleep, read, write, connect)
    → Effective parallelism: ~N cores for I/O-bound work
  - CPU-bound work: GIL is HELD throughout computation
    → Effective parallelism: ~1 core (all threads contend for GIL)
  - Mixed work: speedup = time_in_io / total_time * N_cores

For PROCESS model:
  - Each process has its OWN interpreter and GIL
  - True parallelism: ~N cores for CPU-bound work
  - Cost: ~10-50MB RAM per process + IPC overhead

Triple Dispatch Strategy:
  ASYNC   → I/O-bound, single thread, cooperative
  THREAD  → Mixed, GIL-contended, preemptive
  PROCESS → CPU-bound, true parallelism, memory-heavy
"""
```

**GIL Demo Code:**
```python
class CpuIntensiveJob(Job):
    def _crunch_numbers(self) -> bool:
        total = 0
        for i in range(20_000_000):
            total += i * i  # Pure CPU — GIL held throughout
        return True
    # With 4 jobs on 4 cores:
    #   THREAD model:  ~4x slower than single-thread (contention)
    #   PROCESS model: ~4x faster than single-thread (true parallelism)
```

---

## Question 3: Race Conditions & Thread Safety

**Interviewer:** *"What's a race condition? How do you prevent it? Show me with code."*

### 🎯 Expected Answer

```python
class UnsafeCounter:
    """Demonstrates the classic race condition."""
    def __init__(self):
        self.count = 0

    def increment(self, amount: int) -> None:
        # ⚠️ self.count += 1 is NOT atomic!
        # It's: LOAD → ADD → STORE (3 CPU instructions)
        for _ in range(amount):
            temp = self.count       # LOAD
            # ⏳ Context switch here → another thread reads STALE value
            self.count = temp + 1   # ADD + STORE

class SafeCounter:
    """Thread-safe using lock for mutual exclusion."""
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def increment(self, amount: int) -> None:
        with self._lock:  # Only ONE thread enters at a time
            for _ in range(amount):
                self.count += 1
        # Lock released automatically via __exit__
```

**Expected demo output** (non-deterministic):
```
UNSAFE counter: 184,230 (lost 15,770 updates — 7.9%)
SAFE   counter: 200,000 (expected 200,000)
```

**Why the unsafe counter loses updates:** Thread A reads `count=50`, Thread B reads `count=50` (before A writes), both write `51`. One increment is lost.

---

## Question 4: Deadlock Prevention

**Interviewer:** *"How could your scheduler deadlock? How do you prevent it?"*

### 🎯 Expected Answer

**Deadlock scenario (asyncio.Lock is not reentrant):**
```python
async def cancel_all(self):
    async with self._lock:          # Acquire lock
        for task in self._active_jobs:
            task.cancel()           # Task runs finally block...
    # ...which tries: async with self._lock → DEADLOCK!
```

**Fix — Snapshot-then-cancel:**
```python
async def cancel_all(self):
    async with self._lock:
        tasks = list(self._active_jobs.values())  # Snapshot
    for task in tasks:  # Cancel OUTSIDE the lock
        if not task.done():
            task.cancel()
```

**Four Coffman conditions for deadlock:**
1. **Mutual exclusion** — resources can't be shared
2. **Hold and wait** — thread holds a resource while waiting for another
3. **No preemption** — resources can't be forcibly taken
4. **Circular wait** — two or more threads waiting in a cycle

**Break any one condition to prevent deadlock.** We break #4 via lock ordering.

---

## Question 5: Producer-Consumer Pattern

**Interviewer:** *"Describe the Producer-Consumer pattern in your scheduler."*

### 🎯 Expected Answer

```python
class JobScheduler:
    def __init__(self):
        self._job_queue: asyncio.Queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []

    async def _scheduler_loop(self):       # PRODUCER
        while self._running:
            jobs = self._get_pending_jobs()
            for job in jobs:
                await self._job_queue.put(job)  # Blocks if queue full
            await asyncio.sleep(0.5)

    async def _worker_loop(self, id):       # CONSUMER
        while self._running:
            job = await self._job_queue.get()  # Blocks if queue empty
            await self._executor.execute(job)
            self._job_queue.task_done()        # Signal completion
```

**Key design decisions:**
- `asyncio.Queue` is **thread-safe and async-safe** — no locks needed
- `get()` blocks cooperatively (yields to event loop) — no busy-waiting
- `task_done()` enables `queue.join()` to wait for all items to be processed
- Multiple workers consume from the same queue — automatic load balancing

---

## Question 6: Cooperative Cancellation

**Interviewer:** *"How do you gracefully shut down your scheduler?"*

### 🎯 Expected Answer

```python
async def stop(self):
    """Three-phase shutdown:"""
    # Phase 1: Signal stop
    self._running = False
    self._stop_event.set()          # Workers check this on each loop

    # Phase 2: Cancel running jobs
    await self._executor.cancel_all()  # Cancels asyncio tasks
    # Each task catches CancelledError → updates job status → cleans up

    # Phase 3: Shutdown thread/process pools
    self._thread_pool.shutdown(wait=False)   # Don't block
    self._process_pool.shutdown(wait=False)  # Don't block
```

**Why asyncio.CancelledError is powerful:**
- The cancelled coroutine can catch it and **clean up resources**
- It can't be ignored — re-raising is automatic if not caught
- It propagates through `await` chains cleanly

---

## Question 7: Semaphore vs Lock

**Interviewer:** *"When would you use a Semaphore instead of a Lock?"*

### 🎯 Expected Answer

| Feature | `threading.Lock` | `asyncio.Semaphore` | `threading.Semaphore` |
|---------|-----------------|-------------------|---------------------|
| Purpose | Mutual exclusion | Resource counting | Resource counting |
| Max concurrent | 1 | N (configurable) | N (configurable) |
| Context | Threads | Async | Threads |
| Reentrant | No (by default) | No | No |
| Use case | Protect shared state | Limit API calls | Thread pool |

**In our scheduler:**
```python
class AsyncJobExecutor:
    def __init__(self, max_concurrent=3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # Limits concurrent job executions to 3
        self._lock = asyncio.Lock()
        # Protects _active_jobs dict (mutual exclusion)

    async def execute(self, job):
        async with self._semaphore:   # Counts concurrent jobs
            async with self._lock:    # Protects shared dict
                self._active_jobs[job.job_id] = current_task()
            # ... execute job ...
```

---

## Question 8: Anti-Starvation with Aging

**Interviewer:** *"How do you prevent low-priority jobs from starving?"*

### 🎯 Expected Answer

```python
class WeightedFairScheduler(SchedulingStrategy):
    """
    Priority Aging: the longer a job waits, the higher its
    effective priority becomes. This guarantees eventual execution.
    """
    def __init__(self, age_factor: float = 0.1):
        self._age_factor = age_factor

    def schedule(self, jobs: List[Job]) -> List[Job]:
        now = datetime.now()

        def effective_priority(job: Job) -> float:
            wait_seconds = (now - job._created_at).total_seconds()
            age_bonus = wait_seconds * self._age_factor
            return job.priority.value + age_bonus  # Higher = more urgent

        return sorted(jobs, key=lambda j: (-effective_priority(j), j._created_at))
```

**Without aging** (PriorityScheduler): Critical jobs keep arriving → Low never runs
**With aging** (WeightedFairScheduler): After ~60 seconds, a Low job has the same effective priority as a Medium job

---

## Question 9: Context Managers for Resource Safety

**Interviewer:** *"Why use context managers in concurrent code?"*

### 🎯 Expected Answer

```python
class TimingContext:
    """Context manager ensures deterministic cleanup via __exit__."""
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start
        # __exit__ is called EVEN if an exception occurs
```

**Resources that MUST use context managers:**
1. **Locks** — `with lock:` prevents deadlock from forgotten release
2. **Files** — `with open():` prevents fd leaks
3. **DB connections** — `with connection:` prevents pool exhaustion
4. **Thread pools** — `with executor:` ensures clean shutdown

**In async code:**
```python
async with self._semaphore:  # Even if job. execute() raises, semaphore is released
    await self.execute(job)
```

---

## Question 10: Exponential Backoff & Retry

**Interviewer:** *"How do you implement retry logic without overwhelming the system?"*

### 🎯 Expected Answer

```python
def exponential_backoff(attempt: int, base_delay: float = 1.0,
                        max_delay: float = 3600.0, jitter: bool = True) -> float:
    """
    Formula: delay = min(base * 2^attempt, max_delay)
    With jitter: delay = random(0, delay)
    """
    import random
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        delay = random.uniform(0, delay)  # Prevents thundering herd
    return delay
```

| Attempt | Backoff (no jitter) | Backoff (with jitter) |
|---------|---------------------|-----------------------|
| 1 | 1s | 0.0–1.0s |
| 2 | 2s | 0.0–2.0s |
| 3 | 4s | 0.0–4.0s |
| 4 | 8s | 0.0–8.0s |
| ... | ... | ... |
| Max | 1h | 0.0–1.0h |

**Why jitter matters:** Without jitter, 1000 clients all retry at exactly the same time → thundering herd → cascading failure.

---

## Question 11: ThreadPool vs ProcessPool

**Interviewer:** *"Compare ThreadPoolExecutor and ProcessPoolExecutor when to use which?"*

### 🎯 Evaluation Criteria

| Criterion | ThreadPoolExecutor | ProcessPoolExecutor |
|-----------|-------------------|-------------------|
| **GIL** | Bound by GIL | Each process has own GIL |
| **Memory** | Shared (low overhead) | Separate (high overhead, ~50MB/proc) |
| **Startup** | Fast (~1ms) | Slow (~200ms) |
| **IPC** | Shared variables (with locks) | Pickle serialization |
| **Best for** | I/O-bound, mixed | CPU-bound, compute-intensive |
| **Crash safety** | Thread crash = process crash | Process crash = isolated |
| **Max workers** | ~1000 (OS thread limit) | ~64 (RAM limit) |

**Rule of thumb:** If your workload spends >50% of time waiting (I/O), use threads. If it spends >50% computing, use processes.

---

## Question 12: System Design — Distributed Scheduler

**Interviewer:** *"How would you make your scheduler distributed across multiple machines?"*

### 🎯 Expected Answer

```python
# Changes needed:
# 1. Replace asyncio.Queue with Redis (sorted set)
#    → Multiple scheduler instances share the same queue
#
# 2. Add lease mechanism (prevent double-processing)
#    → Worker atomically pops with lease TTL
#    → Lease expires if worker crashes → job re-queues
#
# 3. Add heartbeat monitoring
#    → Workers report health every 5s
#    → No heartbeat for 30s → reassign jobs
#
# 4. Add leader election (for cron trigger)
#    → Only one scheduler runs cron jobs
#    → Use Redis SETNX or ZooKeeper
```

---

## 📊 Staff-Level Evaluation Criteria

| Score | Criteria |
|-------|----------|
| **Hire** | Explains async/await mechanics, GIL impact, race conditions with code examples |
| **Strong Hire** | Identifies trade-offs between concurrency models, shows deadlock awareness, demonstrates exponential backoff & jitter |
| **No Hire** | Can't explain how await yields to event loop, thinks asyncio provides parallelism, ignores GIL implications |
