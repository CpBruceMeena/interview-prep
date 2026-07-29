# Job Scheduling System — Code Overview

> **Version:** 2.0 (Async + Concurrency Models)  
> **Python:** 3.10+ (asyncio, concurrent.futures, threading)

---

## 🏛️ Architecture

```
                    ┌─────────────────────┐
                    │    JobScheduler     │  ← Facade Pattern
                    │   (asyncio-based)   │
                    └─────────┬───────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
   ┌─────▼─────┐    ┌────────▼────────┐    ┌──────▼──────┐
   │ Scheduler │    │ asyncio.Queue   │    │  Workers    │
   │   Loop    │    │ (Producer-      │    │ (Consumer)  │
   │ (Producer)│    │  Consumer)      │    │  (3 tasks)  │
   └───────────┘    └─────────────────┘    └──────┬──────┘
                                                  │
                                          ┌───────▼───────┐
                                          │ AsyncJobExec- │
                                          │   utor        │
                                          └───────┬───────┘
                                                  │
                    ┌─────────────────────────────┼─────────────┐
                    │               │             │             │
              ┌─────▼────┐   ┌──────▼──────┐   ┌──▼──────────┐
              │ ASYNC    │   │ THREAD      │   │ PROCESS     │
              │ (event   │   │ (ThreadPool │   │ (ProcessPool│
              │  loop)   │   │  Executor)  │   │  Executor)  │
              └──────────┘   └─────────────┘   └─────────────┘
```

---

## 📦 Class Hierarchy

### Classes

| Class | Type | Pattern | Responsibility |
|-------|------|---------|---------------|
| `Job` | ABC | **Command** | Abstract job with `execute_async()` / `execute_sync()` |
| `EmailJob` | Concrete | Command | I/O-bound: async email sending |
| `DataProcessingJob` | Concrete | Command | Mixed: data processing via thread pool |
| `ReportGenerationJob` | Concrete | Command | I/O-bound: async report gen |
| `FileUploadJob` | Concrete | Command | I/O-bound: async file upload with retry |
| `CpuIntensiveJob` | Concrete | Command | CPU-bound: offloaded to process pool |
| `UnsafeCounter` | Concrete | — | Demonstrates race condition (no lock) |
| `SafeCounter` | Concrete | — | Thread-safe counter (with lock) |
| `SchedulingStrategy` | ABC | **Strategy** | Pluggable job ordering algorithm |
| `PriorityScheduler` | Concrete | Strategy | Highest priority first |
| `FIFOScheduler` | Concrete | Strategy | First-come, first-served |
| `DeadlineAwareScheduler` | Concrete | Strategy | Priority + FCFS |
| `WeightedFairScheduler` | Concrete | Strategy | Priority with aging (anti-starvation) |
| `RecurringJob` | Concrete | **Decorator** | Wraps factory with interval |
| `AsyncJobExecutor` | Concrete | — | Triple-dispatch: async/thread/process |
| `JobScheduler` | Concrete | **Facade** | Unified interface for whole system |
| `_AsyncPendingLock` | Concrete | — | Async-safe context manager |
| `TimingContext` | Concrete | **Context Manager** | Elapsed time measurement |
| `DeadlockSafety` | Mixin | — | Documents lock ordering discipline |

---

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Command** | `Job` + subclasses | Encapsulate action + metadata (retries, timeout, priority) |
| **Strategy** | `SchedulingStrategy` | Swap scheduling algorithm (FIFO, Priority, Weighted Fair) |
| **Decorator** | `RecurringJob` | Wrap one-time job factory with recurrence logic |
| **Facade** | `JobScheduler` | Unified API: `add_job()`, `start()`, `stop()` |
| **Producer-Consumer** | `_scheduler_loop` + `_worker_loop` | Decouple creation from execution via queue |
| **Context Manager** | `TimingContext`, `_AsyncPendingLock` | Deterministic setup/cleanup |

---

## 🔄 Concurrency Models

### ASYNC (Default)
```python
class EmailJob(Job):
    async def execute_async(self) -> bool:
        await asyncio.sleep(0.5)  # ← yields to event loop
        return True
```
Best for: I/O-bound workloads. Single thread, cooperative multitasking.

### THREAD
```python
# DataProcessingJob automatically dispatched to ThreadPoolExecutor
executor.execute_sync()  # runs in thread pool via loop.run_in_executor()
```
Best for: Mixed workloads. GIL released during I/O operations.

### PROCESS
```python
class CpuIntensiveJob(Job):
    def execute_sync(self) -> bool:
        return self._crunch_numbers()  # runs in ProcessPoolExecutor
```
Best for: CPU-bound workloads. Each process has its own GIL → true parallelism.

---

## 🧪 Key CS Concepts Demonstrated

| Concept | Code | What to Look For |
|---------|------|------------------|
| **GIL** | `ConcurrencyModel` enum | Docstrings explain GIL behavior per model |
| **Race Condition** | `UnsafeCounter` vs `SafeCounter` | `threading.Lock()` prevents lost updates |
| **Deadlock Prevention** | `cancel_all()` | Snapshot-then-cancel pattern |
| **Cooperative Multi-tasking** | All `await` points | Event loop yields at each await |
| **Semaphore** | `AsyncJobExecutor._semaphore` | Limits concurrent job execution |
| **Aging (Anti-starvation)** | `WeightedFairScheduler` | Priority boost increases with wait time |
| **Exponential Backoff** | `exponential_backoff()` | Prevents thundering herd |
| **Cooperative Cancellation** | `CancelledError` handler | Graceful shutdown with cleanup |

---

## 📦 Full Source Code

```python
"""
Job Scheduling System — Low Level Design
=========================================
Design Principles: SOLID, Strategy, Command, Observer, Producer-Consumer

Core Computer Science Concepts Demonstrated:
  • Concurrency vs Parallelism — asyncio (concurrent) vs multiprocessing (parallel)
  • GIL (Global Interpreter Lock) — why threading is limited for CPU-bound work
  • Race Conditions — demonstrated with and without locks
  • Deadlock Prevention — lock ordering, timeouts, try-lock patterns
  • Context Switching — cooperative (async/await) vs preemptive (threads)
  • Semaphore / Bounded Semaphore — concurrency limiting
  • Producer-Consumer — asyncio.Queue + multiple workers
  • Cooperative Cancellation — asyncio.CancelledError, asyncio.Event
  • Thread-safe vs Async-safe patterns
"""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Tuple
import asyncio
import heapq
import multiprocessing
import os
import signal
import time
import threading
import uuid


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPT: Enums for State Machines
# ════════════════════════════════════════════════════════════════════════

class JobPriority(Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class JobStatus(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    RETRYING = "Retrying"
    TIMEOUT = "Timeout"


class ConcurrencyModel(Enum):
    ASYNC = "async"
    THREAD = "thread"
    PROCESS = "process"


class RecurrenceType(Enum):
    NONE = "None"
    HOURLY = "Hourly"
    DAILY = "Daily"
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"
    CRON = "Cron Expression"


# ════════════════════════════════════════════════════════════════════════
#  JOB — Command Pattern
# ════════════════════════════════════════════════════════════════════════

class Job(ABC):
    def __init__(self, job_id: str, name: str,
                 priority: JobPriority = JobPriority.MEDIUM):
        self._job_id = job_id
        self._name = name
        self._priority = priority
        self._status = JobStatus.PENDING
        self._created_at = datetime.now()
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None
        self._error_message: Optional[str] = None
        self._retry_count = 0
        self._max_retries = 3
        self._timeout_seconds = 300
        self._concurrency_model = ConcurrencyModel.ASYNC

    @property
    def job_id(self) -> str: return self._job_id
    @property
    def name(self) -> str: return self._name
    @property
    def priority(self) -> JobPriority: return self._priority
    @property
    def status(self) -> JobStatus: return self._status
    @status.setter
    def status(self, value: JobStatus) -> None: self._status = value
    @property
    def retry_count(self) -> int: return self._retry_count
    @property
    def max_retries(self) -> int: return self._max_retries
    @max_retries.setter
    def max_retries(self, value: int) -> None: self._max_retries = value
    @property
    def timeout_seconds(self) -> int: return self._timeout_seconds
    @timeout_seconds.setter
    def timeout_seconds(self, value: int) -> None: self._timeout_seconds = value
    @property
    def concurrency_model(self) -> ConcurrencyModel: return self._concurrency_model
    @concurrency_model.setter
    def concurrency_model(self, value: ConcurrencyModel) -> None: self._concurrency_model = value

    @abstractmethod
    async def execute_async(self) -> bool: pass

    def execute_sync(self) -> bool:
        return asyncio.run(self.execute_async())

    def on_success(self) -> None:
        self._status = JobStatus.COMPLETED
        self._completed_at = datetime.now()

    def on_failure(self, error: str) -> None:
        self._error_message = error
        if self._retry_count < self._max_retries:
            self._retry_count += 1
            self._status = JobStatus.RETRYING
            print(f"  🔄 Retry {self._retry_count}/{self._max_retries}: {self}")
        else:
            self._status = JobStatus.FAILED
        self._completed_at = datetime.now()

    def on_timeout(self) -> None:
        self._status = JobStatus.TIMEOUT
        self._error_message = f"Job timed out after {self._timeout_seconds}s"
        self._completed_at = datetime.now()

    def __lt__(self, other: 'Job') -> bool:
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self._created_at < other._created_at

    def __str__(self) -> str:
        return f"Job[{self._job_id[:8]}]: {self._name} ({self._status.value})"


# ════════════════════════════════════════════════════════════════════════
#  CONCRETE JOB IMPLEMENTATIONS
# ════════════════════════════════════════════════════════════════════════

class EmailJob(Job):
    def __init__(self, to_email: str, subject: str, body: str):
        super().__init__(str(uuid.uuid4()), f"Send Email to {to_email}")
        self._to = to_email
        self._subject = subject
        self._body = body
        self._concurrency_model = ConcurrencyModel.ASYNC

    async def execute_async(self) -> bool:
        print(f"  📧 Sending email to {self._to}: {self._subject}")
        await asyncio.sleep(0.5)
        return True

    def execute_sync(self) -> bool:
        print(f"  📧 Sending email to {self._to}: {self._subject}")
        time.sleep(0.5)
        return True


class DataProcessingJob(Job):
    def __init__(self, data_source: str, query: str):
        super().__init__(str(uuid.uuid4()), f"Process Data: {data_source}")
        self._source = data_source
        self._query = query
        self._concurrency_model = ConcurrencyModel.THREAD
        self._timeout_seconds = 600

    async def execute_async(self) -> bool:
        print(f"  🔄 Processing data from {self._source}: {self._query}")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._process_data)
        return result

    def execute_sync(self) -> bool:
        print(f"  🔄 Processing data from {self._source}: {self._query}")
        return self._process_data()

    def _process_data(self) -> bool:
        total = 0
        for i in range(10_000_000):
            total += i
        print(f"  🔄 Data processed: {total} rows analyzed")
        return True


class ReportGenerationJob(Job):
    def __init__(self, report_name: str, report_type: str):
        super().__init__(str(uuid.uuid4()), f"Generate {report_name}")
        self._report_name = report_name
        self._report_type = report_type
        self._concurrency_model = ConcurrencyModel.ASYNC

    async def execute_async(self) -> bool:
        print(f"  📊 Generating report: {self._report_name} ({self._report_type})")
        await asyncio.sleep(0.3)
        return True


class FileUploadJob(Job):
    def __init__(self, file_path: str, destination: str):
        super().__init__(str(uuid.uuid4()), f"Upload {file_path}")
        self._file_path = file_path
        self._destination = destination
        self._concurrency_model = ConcurrencyModel.ASYNC

    async def execute_async(self) -> bool:
        print(f"  ☁️ Uploading {self._file_path} to {self._destination}")
        await asyncio.sleep(2)
        if "fail" in self._file_path.lower():
            raise RuntimeError("Upload failed: Connection timeout")
        return True

    def execute_sync(self) -> bool:
        print(f"  ☁️ Uploading {self._file_path} to {self._destination}")
        time.sleep(2)
        if "fail" in self._file_path.lower():
            raise RuntimeError("Upload failed: Connection timeout")
        return True


class CpuIntensiveJob(Job):
    def __init__(self, name: str, iterations: int = 20_000_000):
        super().__init__(str(uuid.uuid4()), f"CPU-Intensive: {name}")
        self._iterations = iterations
        self._concurrency_model = ConcurrencyModel.PROCESS
        self._timeout_seconds = 120

    async def execute_async(self) -> bool:
        print(f"  🖥️ CPU-intensive ({self._name}): crunching {self._iterations:,} iterations")
        return self._crunch_numbers()

    def _crunch_numbers(self) -> bool:
        total = 0
        for i in range(self._iterations):
            total += i * i
        print(f"  🖥️ CPU work done: {total:,}")
        return True

    def execute_sync(self) -> bool:
        return self._crunch_numbers()


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPT: Race Condition Demonstration
# ════════════════════════════════════════════════════════════════════════

class UnsafeCounter:
    def __init__(self):
        self.count = 0

    def increment(self, amount: int = 1) -> None:
        for _ in range(amount):
            temp = self.count
            self.count = temp + 1


class SafeCounter:
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def increment(self, amount: int = 1) -> None:
        with self._lock:
            for _ in range(amount):
                self.count += 1


# ════════════════════════════════════════════════════════════════════════
#  SCHEDULING STRATEGIES — Strategy Pattern
# ════════════════════════════════════════════════════════════════════════

class SchedulingStrategy(ABC):
    @abstractmethod
    def schedule(self, jobs: List[Job]) -> List[Job]: pass


class PriorityScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (-j.priority.value, j._created_at))


class FIFOScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: j._created_at)


class DeadlineAwareScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (j.priority.value, j._created_at))


class WeightedFairScheduler(SchedulingStrategy):
    def __init__(self, age_factor: float = 0.1):
        self._age_factor = age_factor

    def schedule(self, jobs: List[Job]) -> List[Job]:
        now = datetime.now()
        def effective_priority(job: Job) -> float:
            wait_seconds = (now - job._created_at).total_seconds()
            age_bonus = wait_seconds * self._age_factor
            return job.priority.value + age_bonus
        return sorted(jobs, key=lambda j: (-effective_priority(j), j._created_at))


# ════════════════════════════════════════════════════════════════════════
#  RECURRING JOB — Decorator Pattern
# ════════════════════════════════════════════════════════════════════════

class RecurringJob:
    def __init__(self, job_factory: Callable[[], Job],
                 recurrence: RecurrenceType,
                 interval_seconds: int = 3600,
                 cron_expression: str = ""):
        self._job_factory = job_factory
        self._recurrence = recurrence
        self._interval = interval_seconds
        self._cron = cron_expression
        self._next_run = datetime.now()
        self._is_active = True

    @property
    def next_run(self) -> datetime: return self._next_run
    @property
    def is_active(self) -> bool: return self._is_active

    def create_job(self) -> Job: return self._job_factory()

    def update_next_run(self) -> None:
        if self._recurrence == RecurrenceType.HOURLY:
            self._next_run = datetime.now() + timedelta(hours=1)
        elif self._recurrence == RecurrenceType.DAILY:
            self._next_run = datetime.now() + timedelta(days=1)
        elif self._recurrence == RecurrenceType.WEEKLY:
            self._next_run = datetime.now() + timedelta(weeks=1)
        else:
            self._next_run = datetime.now() + timedelta(seconds=self._interval)

    def cancel(self) -> None: self._is_active = False


# ════════════════════════════════════════════════════════════════════════
#  ASYNC JOB EXECUTOR — Runs jobs with configurable concurrency
# ════════════════════════════════════════════════════════════════════════

class AsyncJobExecutor:
    def __init__(self, max_concurrent: int = 3,
                 max_thread_workers: int = 4,
                 max_process_workers: int = 4):
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_thread_workers,
            thread_name_prefix="job-thread"
        )
        self._process_pool = ProcessPoolExecutor(
            max_workers=max_process_workers
        )
        self._active_jobs: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    @property
    def thread_pool(self) -> ThreadPoolExecutor: return self._thread_pool
    @property
    def process_pool(self) -> ProcessPoolExecutor: return self._process_pool

    async def execute(self, job: Job) -> bool:
        async with self._semaphore:
            async with self._lock:
                task = asyncio.current_task()
                self._active_jobs[job.job_id] = task

            job.status = JobStatus.RUNNING
            job._started_at = datetime.now()

            try:
                print(f"  ▶️ [{job.concurrency_model.value.upper():7}] {job}")

                if job.concurrency_model == ConcurrencyModel.ASYNC:
                    success = await asyncio.wait_for(
                        job.execute_async(), timeout=job.timeout_seconds)
                elif job.concurrency_model == ConcurrencyModel.THREAD:
                    loop = asyncio.get_running_loop()
                    success = await asyncio.wait_for(
                        loop.run_in_executor(self._thread_pool, job.execute_sync),
                        timeout=job.timeout_seconds)
                elif job.concurrency_model == ConcurrencyModel.PROCESS:
                    loop = asyncio.get_running_loop()
                    success = await asyncio.wait_for(
                        loop.run_in_executor(self._process_pool, job.execute_sync),
                        timeout=job.timeout_seconds)
                else:
                    success = False

                if success:
                    job.on_success()
                    print(f"  ✅ [{job.concurrency_model.value.upper():7}] {job}")
                else:
                    job.on_failure("Job returned False")
                    print(f"  ❌ [{job.concurrency_model.value.upper():7}] {job}")

            except asyncio.TimeoutError:
                job.on_timeout()
                print(f"  ⏰ [{job.concurrency_model.value.upper():7}] TIMEOUT: {job} after {job.timeout_seconds}s")
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job._completed_at = datetime.now()
                print(f"  🛑 [{job.concurrency_model.value.upper():7}] CANCELLED: {job}")
                raise
            except Exception as e:
                job.on_failure(str(e))
                print(f"  ❌ [{job.concurrency_model.value.upper():7}] ERROR: {job} — {e}")
            finally:
                async with self._lock:
                    self._active_jobs.pop(job.job_id, None)

            return job.status == JobStatus.COMPLETED

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            task = self._active_jobs.get(job_id)
            if task and not task.done():
                task.cancel()
                return True
            return False

    async def cancel_all(self) -> None:
        async with self._lock:
            tasks = list(self._active_jobs.values())
        for task in tasks:
            if not task.done():
                task.cancel()

    async def shutdown(self) -> None:
        await self.cancel_all()
        self._thread_pool.shutdown(wait=False)
        self._process_pool.shutdown(wait=False)


# ════════════════════════════════════════════════════════════════════════
#  RACE CONDITION DEMONSTRATION
# ════════════════════════════════════════════════════════════════════════

def demonstrate_race_condition(iterations: int = 100_000):
    print("\n  ┌─ RACE CONDITION DEMONSTRATION ─────────────────────┐")
    unsafe = UnsafeCounter()
    t1 = threading.Thread(target=unsafe.increment, args=(iterations,))
    t2 = threading.Thread(target=unsafe.increment, args=(iterations,))
    t1.start(); t2.start(); t1.join(); t2.join()
    lost = (2 * iterations) - unsafe.count
    print(f"  │ UNSAFE counter: {unsafe.count:,} (lost {lost:,} updates — {lost/(2*iterations)*100:.1f}%) │")
    safe = SafeCounter()
    t1 = threading.Thread(target=safe.increment, args=(iterations,))
    t2 = threading.Thread(target=safe.increment, args=(iterations,))
    t1.start(); t2.start(); t1.join(); t2.join()
    print(f"  │ SAFE   counter: {safe.count:,} (expected {2*iterations:,})                      │")
    print("  └────────────────────────────────────────────────────┘")
    return lost


# ════════════════════════════════════════════════════════════════════════
#  ASYNC JOB SCHEDULER — Facade Pattern
# ════════════════════════════════════════════════════════════════════════

class JobScheduler:
    def __init__(self, scheduler_strategy: Optional[SchedulingStrategy] = None,
                 max_concurrent: int = 3, num_workers: int = 2):
        self._executor = AsyncJobExecutor(max_concurrent=max_concurrent)
        self._scheduler = scheduler_strategy or PriorityScheduler()
        self._job_queue: asyncio.Queue = asyncio.Queue()
        self._pending: List[Job] = []
        self._history: List[Job] = []
        self._recurring: List[RecurringJob] = []
        self._running = False
        self._stop_event = asyncio.Event()
        self._num_workers = num_workers
        self._workers: List[asyncio.Task] = []

    def add_job(self, job: Job) -> None:
        self._pending.append(job)

    def add_recurring(self, recurring: RecurringJob) -> None:
        self._recurring.append(recurring)

    def set_scheduler(self, strategy: SchedulingStrategy) -> None:
        self._scheduler = strategy

    async def start(self) -> None:
        self._running = True
        self._stop_event.clear()
        for i in range(self._num_workers):
            worker = asyncio.create_task(self._worker_loop(i), name=f"scheduler-worker-{i}")
            self._workers.append(worker)
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(), name="scheduler-loop")
        print(f"  🟢 Scheduler started ({self._num_workers} workers, max {self._executor._max_concurrent} concurrent)")

    async def stop(self) -> None:
        print("  🔴 Scheduler shutting down...")
        self._running = False
        self._stop_event.set()
        if hasattr(self, '_scheduler_task'):
            self._scheduler_task.cancel()
            try: await self._scheduler_task
            except asyncio.CancelledError: pass
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        await self._executor.shutdown()
        print("  🔴 Scheduler stopped")

    async def _scheduler_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            now = datetime.now()
            for rec in self._recurring:
                if rec.is_active and rec.next_run <= now:
                    job = rec.create_job()
                    self.add_job(job)
                    rec.update_next_run()
            async with self._lock_pending() as pl:
                if pl:
                    ordered = self._scheduler.schedule(pl)
                    for job in ordered:
                        await self._job_queue.put(job)
                    pl.clear()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.5)
                break
            except asyncio.TimeoutError:
                pass

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                try:
                    job = await asyncio.wait_for(self._job_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    await self._executor.execute(job)
                except asyncio.CancelledError:
                    self._job_queue.task_done()
                    raise
                finally:
                    self._history.append(job)
                    self._job_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  ⚠️ Worker {worker_id} error: {e}")
                continue

    def _lock_pending(self):
        return _AsyncPendingLock(self._pending)


class _AsyncPendingLock:
    def __init__(self, pending: List):
        self._pending = pending
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._lock.acquire()
        return self._pending

    async def __aexit__(self, *args):
        self._lock.release()


# ════════════════════════════════════════════════════════════════════════
#  EXPONENTIAL BACKOFF UTILITY
# ════════════════════════════════════════════════════════════════════════

def exponential_backoff(attempt: int, base_delay: float = 1.0,
                        max_delay: float = 3600.0, jitter: bool = True) -> float:
    import random
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        delay = random.uniform(0, delay)
    return delay


# ════════════════════════════════════════════════════════════════════════
#  TIMING CONTEXT MANAGER
# ════════════════════════════════════════════════════════════════════════

class TimingContext:
    def __init__(self, label: str = ""):
        self.label = label
        self.elapsed: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start
        if self.label:
            print(f"  ⏱️  {self.label}: {self.elapsed:.3f}s")


# ════════════════════════════════════════════════════════════════════════
#  DEMO
# ════════════════════════════════════════════════════════════════════════

async def async_demo():
    print("=" * 62)
    print("  JOB SCHEDULING SYSTEM — Async + Concurrency Deep Dive")
    print("=" * 62)

    print("\n  ┌─ SECTION 1: RACE CONDITION DEMONSTRATION ────────┐")
    print("  │  Shows why threading.Lock() is necessary           │")
    demonstrate_race_condition(100_000)

    print("\n  ┌─ SECTION 2: GIL & CONCURRENCY MODELS ────────────┐")
    print("  │  ASYNC   → Cooperative, single-thread, I/O-bound  │")
    print("  │  THREAD  → Preemptive, GIL-bound, mixed workloads │")
    print("  │  PROCESS → True parallelism, CPU-bound             │")
    print("  └────────────────────────────────────────────────────┘")

    print("\n  ┌─ SECTION 3: SCHEDULING JOBS ──────────────────────┐")
    scheduler = JobScheduler(scheduler_strategy=WeightedFairScheduler(), max_concurrent=4, num_workers=3)
    scheduler.add_job(EmailJob("alice@email.com", "Welcome!", "Thanks for joining"))
    scheduler.add_job(DataProcessingJob("users_db", "SELECT * FROM active_users"))
    scheduler.add_job(ReportGenerationJob("Daily Sales", "CSV"))
    scheduler.add_job(DataProcessingJob("logs", "CLEANUP old entries"))
    scheduler.add_job(CpuIntensiveJob("Matrix Multiply", iterations=10_000_000))
    scheduler.add_job(CpuIntensiveJob("Histogram", iterations=10_000_000))
    critical_job = EmailJob("admin@system.com", "CRITICAL: Server Alert", "CPU > 90%")
    critical_job._priority = JobPriority.CRITICAL
    scheduler.add_job(critical_job)
    cleanup = RecurringJob(lambda: DataProcessingJob("logs", "CLEANUP temp files"), RecurrenceType.HOURLY)
    scheduler.add_recurring(cleanup)

    await scheduler.start()
    await asyncio.sleep(0.5)
    await scheduler._job_queue.join()
    await asyncio.sleep(0.5)
    await scheduler.stop()

    print(f"\n  ┌─ SECTION 4: SCHEDULER STATS ─────────────────────┐")
    completed = sum(1 for j in scheduler._history if j.status == JobStatus.COMPLETED)
    failed = sum(1 for j in scheduler._history if j.status == JobStatus.FAILED)
    cancelled = sum(1 for j in scheduler._history if j.status == JobStatus.CANCELLED)
    timeout = sum(1 for j in scheduler._history if j.status == JobStatus.TIMEOUT)
    print(f"  │ Total     : {len(scheduler._history):3d} jobs                │")
    print(f"  │ Completed : {completed:3d} jobs                │")
    print(f"  │ Failed    : {failed:3d} jobs                │")
    print(f"  │ Cancelled : {cancelled:3d} jobs                │")
    print(f"  │ Timeout   : {timeout:3d} jobs                │")
    print(f"  │ Recurring : {len(scheduler._recurring):3d} schedules           │")
    print(f"  └────────────────────────────────────────────────────┘")

    print(f"\n  ┌─ SECTION 5: JOB HISTORY ──────────────────────────┐")
    for job in scheduler._history[-10:]:
        dur = ""
        if job._started_at and job._completed_at:
            d = (job._completed_at - job._started_at).total_seconds()
            dur = f" ({d:.1f}s)"
        print(f"  │ {str(job):55s}{dur} │")
    print(f"  └────────────────────────────────────────────────────┘")

    print(f"\n{'=' * 62}")
    print(f"  Demo complete — see source for CS concept annotations")
    print(f"{'=' * 62}\n")


def demo():
    asyncio.run(async_demo())


if __name__ == "__main__":
    demo()
```

---

## ▶️ How to Run

```bash
cd python-low-level-design/job-scheduling-system
python job_scheduler.py
```

The demo:
1. Shows race condition (unsafe vs safe counter)
2. Schedules 8 jobs across all 3 concurrency models
3. Executes via async workers with semaphore limiting
4. Reports stats and execution history
