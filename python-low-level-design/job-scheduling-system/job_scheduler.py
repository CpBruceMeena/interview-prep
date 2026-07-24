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
# Enums give us type-safe state representation. Each enum member is a
# singleton, making equality checks O(1). The integer backing (.value)
# enables comparison operations (<, >) used in priority ordering.

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
    TIMEOUT = "Timeout"             # Job exceeded its time budget


class ConcurrencyModel(Enum):
    """
    CORE CS CONCEPT: Concurrency vs Parallelism

    ASYNC  — Cooperative multitasking via event loop. Single thread,
              single process. Best for I/O-bound workloads (network,
              file I/O). Context switching is explicit (await points).

    THREAD — Preemptive multitasking via OS threads. Shared memory space
              but GIL-bound in CPython. Best for I/O-bound work that
              doesn't have async libraries available.

    PROCESS — True parallelism via separate processes. Each process has
               its own GIL and memory space. Best for CPU-bound work.
               Higher overhead (IPC, memory isolation).
    """
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
#  CORE CS CONCEPT: Deadlock Prevention via Lock Ordering
# ════════════════════════════════════════════════════════════════════════
# To prevent deadlocks, we define a global lock ordering. Every component
# that acquires multiple locks must acquire them in this order:
#   1. resource_lock  (highest priority)
#   2. state_lock
#   3. queue_lock     (lowest priority)
# Violating this order risks deadlock (circular wait).

class DeadlockSafety:
    """Mixin-style class documenting lock ordering discipline."""
    LOCK_ORDER = ["resource_lock", "state_lock", "queue_lock"]


# ════════════════════════════════════════════════════════════════════════
#  JOB — Command Pattern
# ════════════════════════════════════════════════════════════════════════
# The Command Pattern encapsulates an action (execute) and its metadata
# (priority, retries, timeout) into an object. The scheduler never needs
# to know what the job *does* — it just calls execute().
#
# This is Dependency Inversion (D of SOLID): the scheduler depends on
# the abstract Job protocol, not concrete implementations.

class Job(ABC):
    """Abstract job — the 'Command' in Command Pattern."""

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
        self._concurrency_model = ConcurrencyModel.ASYNC  # Default

    # ── Properties ──────────────────────────────────────────────

    @property
    def job_id(self) -> str: return self._job_id

    @property
    def name(self) -> str: return self._name

    @property
    def priority(self) -> JobPriority: return self._priority

    @property
    def status(self) -> JobStatus: return self._status

    @status.setter
    def status(self, value: JobStatus) -> None:
        self._status = value

    @property
    def retry_count(self) -> int: return self._retry_count

    @property
    def max_retries(self) -> int: return self._max_retries

    @max_retries.setter
    def max_retries(self, value: int) -> None:
        self._max_retries = value

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @timeout_seconds.setter
    def timeout_seconds(self, value: int) -> None:
        self._timeout_seconds = value

    @property
    def concurrency_model(self) -> ConcurrencyModel:
        return self._concurrency_model

    @concurrency_model.setter
    def concurrency_model(self, value: ConcurrencyModel) -> None:
        self._concurrency_model = value

    # ── Lifecycle Methods ───────────────────────────────────────

    @abstractmethod
    async def execute_async(self) -> bool:
        """
        Async execute — cooperative multitasking version.
        Must use 'await' for any I/O. The event loop can schedule
        other coroutines while this one is waiting.
        """
        pass

    def execute_sync(self) -> bool:
        """
        Sync execute — for ThreadPoolExecutor / ProcessPoolExecutor.
        This runs in a separate OS thread or process. For threading,
        the GIL limits CPU-bound parallelism. For processes, we get
        true parallelism at the cost of memory overhead.
        """
        # Default: wrap async in a new event loop
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

    # ── Comparison (for heapq priority ordering) ────────────────

    def __lt__(self, other: 'Job') -> bool:
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self._created_at < other._created_at

    def __str__(self) -> str:
        return f"Job[{self._job_id[:8]}]: {self._name} ({self._status.value})"


# ════════════════════════════════════════════════════════════════════════
#  CONCRETE JOB IMPLEMENTATIONS
# ════════════════════════════════════════════════════════════════════════
# Each concrete job extends Job and implements execute_async().
# Notice: no __init__ calls to super().__init__ with string literals
# that don't reference instance variables.

class EmailJob(Job):
    """I/O-bound job — best suited for ASYNC model."""

    def __init__(self, to_email: str, subject: str, body: str):
        super().__init__(str(uuid.uuid4()), f"Send Email to {to_email}")
        self._to = to_email
        self._subject = subject
        self._body = body
        self._concurrency_model = ConcurrencyModel.ASYNC

    async def execute_async(self) -> bool:
        print(f"  📧 Sending email to {self._to}: {self._subject}")
        # Simulate I/O: awaiting releases the GIL and lets other tasks run
        await asyncio.sleep(0.5)
        return True

    def execute_sync(self) -> bool:
        # Threaded fallback — blocks the OS thread but GIL is released
        # during the actual sleep() call (time.sleep() releases GIL)
        print(f"  📧 Sending email to {self._to}: {self._subject}")
        time.sleep(0.5)
        return True


class DataProcessingJob(Job):
    """
    Mixed I/O + CPU job.
    CSV parsing is CPU-bound; writing results is I/O-bound.
    Best with THREAD model (GIL released during I/O).
    """

    def __init__(self, data_source: str, query: str):
        super().__init__(str(uuid.uuid4()), f"Process Data: {data_source}")
        self._source = data_source
        self._query = query
        self._concurrency_model = ConcurrencyModel.THREAD
        self._timeout_seconds = 600  # Data processing takes longer

    async def execute_async(self) -> bool:
        print(f"  🔄 Processing data from {self._source}: {self._query}")
        # Simulate CPU work in a thread executor to avoid blocking event loop
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._process_data)
        return result

    def execute_sync(self) -> bool:
        """
        Direct sync execution — avoids the double-executor nesting that
        happens when the base class calls asyncio.run(self.execute_async())
        which then calls loop.run_in_executor() again.
        """
        print(f"  🔄 Processing data from {self._source}: {self._query}")
        return self._process_data()

    def _process_data(self) -> bool:
        """
        CPU-bound work — runs in default ThreadPoolExecutor.
        The GIL means only one thread executes Python bytecode at a time,
        but for I/O-bound sections of this work, the GIL is released.
        """
        total = 0
        # Simulate CPU-intensive computation (no GIL release)
        for i in range(10_000_000):
            total += i
        print(f"  🔄 Data processed: {total} rows analyzed")
        return True


class ReportGenerationJob(Job):
    """Lightweight I/O job — perfect for ASYNC model."""

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
    """
    I/O-bound with failure simulation.
    Demonstrates retry mechanism and exponential backoff.
    """

    def __init__(self, file_path: str, destination: str):
        super().__init__(str(uuid.uuid4()), f"Upload {file_path}")
        self._file_path = file_path
        self._destination = destination
        self._concurrency_model = ConcurrencyModel.ASYNC

    async def execute_async(self) -> bool:
        print(f"  ☁️ Uploading {self._file_path} to {self._destination}")
        await asyncio.sleep(2)
        # Simulate failure
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
    """
    CPU-bound job — best suited for PROCESS model.
    CORE CS CONCEPT: This demonstrates WHY the GIL matters.
    With THREAD model, 4 CPU-intensive jobs on 4 cores = ~1x speedup
    With PROCESS model, 4 CPU-intensive jobs on 4 cores = ~4x speedup

    NOTE: execute_async() delegates to execute_sync() so the
    AsyncJobExecutor.PROCESS branch handles ProcessPoolExecutor
    creation via the shared pool owned by the executor.
    """

    def __init__(self, name: str, iterations: int = 20_000_000):
        super().__init__(str(uuid.uuid4()), f"CPU-Intensive: {name}")
        self._iterations = iterations
        self._concurrency_model = ConcurrencyModel.PROCESS
        self._timeout_seconds = 120

    async def execute_async(self) -> bool:
        """
        CORE CS CONCEPT: Running CPU-bound work in asyncio blocks the
        event loop! The executor handles offloading via its shared
        ProcessPoolExecutor — we just provide the sync version.
        """
        print(f"  🖥️ CPU-intensive ({self._name}): crunching {self._iterations:,} iterations")
        # The actual CPU work is in execute_sync(), which runs via
        # ProcessPoolExecutor in the AsyncJobExecutor.PROCESS branch.
        # This avoids creating a new ProcessPoolExecutor per call.
        return self._crunch_numbers()

    def _crunch_numbers(self) -> bool:
        """
        Pure CPU computation. In THREAD mode, the GIL ensures only one
        thread runs Python bytecode at a time. In PROCESS mode, each
        process has its own GIL — true parallelism.
        """
        total = 0
        for i in range(self._iterations):
            total += i * i  # Pure CPU work
        print(f"  🖥️ CPU work done: {total:,}")
        return True

    def execute_sync(self) -> bool:
        return self._crunch_numbers()


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPT: Race Condition Demonstration
# ════════════════════════════════════════════════════════════════════════
# A race condition occurs when two threads access shared data without
# synchronization, and the outcome depends on the unpredictable timing
# of thread scheduling. Below are two versions of a counter:
#
#   UnsafeCounter — NO lock. Under heavy load, increments are lost
#                   because += is NOT atomic (it's LOAD, ADD, STORE).
#
#   SafeCounter — WITH lock. The threading.Lock guarantees mutual
#                 exclusion: only one thread can increment at a time.

class UnsafeCounter:
    """
    CORE CS CONCEPT: Demonstrates a race condition.
    self.count += 1 is three CPU instructions:
        1. LOAD self.count into register
        2. ADD 1 to register
        3. STORE register back to self.count
    A context switch between steps 1 and 3 by another thread causes
    lost updates (the classic race condition).
    """

    def __init__(self):
        self.count = 0

    def increment(self, amount: int = 1) -> None:
        # ⚠️ RACE CONDITION: Not thread-safe!
        for _ in range(amount):
            temp = self.count       # LOAD
            # ⏳ Context switch here → another thread reads stale value
            self.count = temp + 1   # ADD + STORE


class SafeCounter:
    """
    Thread-safe counter using a lock for mutual exclusion.
    The lock guarantees atomicity of the increment operation.
    """

    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def increment(self, amount: int = 1) -> None:
        with self._lock:  # Acquire → only one thread enters here at a time
            for _ in range(amount):
                self.count += 1
        # Lock released automatically via context manager


# ════════════════════════════════════════════════════════════════════════
#  SCHEDULING STRATEGIES — Strategy Pattern
# ════════════════════════════════════════════════════════════════════════

class SchedulingStrategy(ABC):
    """Strategy pattern — different algorithms for job ordering."""

    @abstractmethod
    def schedule(self, jobs: List[Job]) -> List[Job]:
        """Order jobs for execution. Returns reordered list."""
        pass


class PriorityScheduler(SchedulingStrategy):
    """
    Highest priority first. Secondary sort by creation time (FCFS).
    ⚠️ Suffers from starvation: low-priority jobs may never run if
    high-priority jobs keep arriving.
    """

    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (-j.priority.value, j._created_at))


class FIFOScheduler(SchedulingStrategy):
    """First-Come, First-Served. No starvation, no prioritization."""

    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: j._created_at)


class DeadlineAwareScheduler(SchedulingStrategy):
    """
    Priority first, then FCFS within the same priority.
    A simplified EDF (Earliest Deadline First).
    """

    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (j.priority.value, j._created_at))


class WeightedFairScheduler(SchedulingStrategy):
    """
    CORE CS CONCEPT: Anti-Starvation with Aging.
    Implements priority aging: the longer a job waits, the higher
    its effective priority becomes. This prevents starvation.
    """

    def __init__(self, age_factor: float = 0.1):
        self._age_factor = age_factor

    def schedule(self, jobs: List[Job]) -> List[Job]:
        now = datetime.now()

        def effective_priority(job: Job) -> float:
            """Base priority + age bonus (waiting time in seconds * factor)."""
            wait_seconds = (now - job._created_at).total_seconds()
            age_bonus = wait_seconds * self._age_factor
            return job.priority.value + age_bonus

        return sorted(jobs, key=lambda j: (-effective_priority(j), j._created_at))


# ════════════════════════════════════════════════════════════════════════
#  RECURRING JOB — Decorator Pattern (wraps a job factory with a schedule)
# ════════════════════════════════════════════════════════════════════════

class RecurringJob:
    """Wraps a job factory with recurrence/interval logic."""

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
    def next_run(self) -> datetime:
        return self._next_run

    @property
    def is_active(self) -> bool:
        return self._is_active

    def create_job(self) -> Job:
        return self._job_factory()

    def update_next_run(self) -> None:
        if self._recurrence == RecurrenceType.HOURLY:
            self._next_run = datetime.now() + timedelta(hours=1)
        elif self._recurrence == RecurrenceType.DAILY:
            self._next_run = datetime.now() + timedelta(days=1)
        elif self._recurrence == RecurrenceType.WEEKLY:
            self._next_run = datetime.now() + timedelta(weeks=1)
        else:
            self._next_run = datetime.now() + timedelta(seconds=self._interval)

    def cancel(self) -> None:
        self._is_active = False


# ════════════════════════════════════════════════════════════════════════
#  ASYNC JOB EXECUTOR — Runs jobs with configurable concurrency
# ════════════════════════════════════════════════════════════════════════
# Uses an asyncio.Semaphore to limit concurrent async executions.
# Also maintains a ThreadPoolExecutor and ProcessPoolExecutor for
# jobs that specify those concurrency models.

class AsyncJobExecutor:
    """
    CORE CS CONCEPT: Semaphore-based concurrency limiting.

    An asyncio.Semaphore is like a thread-safe counter. Each acquire()
    decrements the counter. If the counter is 0, the coroutine blocks
    (yields to the event loop) until another task calls release().

    This is different from a threading.Semaphore because:
    - It's cooperative (not preemptive) — the task yields at await points
    - No GIL involvement — all tasks run on the same thread
    - No risk of deadlock from the semaphore itself (asyncio timeout)
    """

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
        self._lock = asyncio.Lock()  # Lock for _active_jobs dict

    @property
    def thread_pool(self) -> ThreadPoolExecutor:
        return self._thread_pool

    @property
    def process_pool(self) -> ProcessPoolExecutor:
        return self._process_pool

    async def execute(self, job: Job) -> bool:
        """
        Execute a job using its preferred concurrency model.

        CORE CS CONCEPT: Triple Dispatch by Concurrency Model.
        ASYNC  → run in event loop (cooperative multitasking)
        THREAD → run_in_executor(ThreadPoolExecutor)
        PROCESS → run_in_executor(ProcessPoolExecutor)
        """
        async with self._semaphore:
            async with self._lock:
                task = asyncio.current_task()
                self._active_jobs[job.job_id] = task

            job.status = JobStatus.RUNNING
            job._started_at = datetime.now()

            try:
                print(f"  ▶️ [{job.concurrency_model.value.upper():7}] {job}")

                if job.concurrency_model == ConcurrencyModel.ASYNC:
                    # Cooperative multitasking: runs on the event loop thread
                    # The GIL is released during await points (I/O waits)
                    success = await asyncio.wait_for(
                        job.execute_async(),
                        timeout=job.timeout_seconds
                    )

                elif job.concurrency_model == ConcurrencyModel.THREAD:
                    """
                    CORE CS CONCEPT: GIL Behavior in ThreadPoolExecutor

                    When a thread runs Python code, it holds the GIL.
                    The GIL is released during:
                      - I/O operations (sleep, read, write, connect)
                      - C-extension calls that release it (NumPy, Pandas)
                      - Thread waits (Lock.acquire(), Queue.get())

                    In THREAD mode, CPU-bound code still contends for the GIL.
                    The effective speedup on N cores is roughly:
                      speedup = time_in_io / total_time * N
                    """
                    loop = asyncio.get_running_loop()
                    success = await asyncio.wait_for(
                        loop.run_in_executor(self._thread_pool, job.execute_sync),
                        timeout=job.timeout_seconds
                    )

                elif job.concurrency_model == ConcurrencyModel.PROCESS:
                    """
                    CORE CS CONCEPT: ProcessPoolExecutor Bypasses the GIL

                    Each process gets its own Python interpreter and GIL.
                    This is TRUE PARALLELISM for CPU-bound work.
                    Trade-offs:
                      + Linear speedup for CPU-bound work (up to N cores)
                      + Memory isolation (no shared state bugs)
                      - Higher memory overhead (each process ~10-50MB)
                      - IPC overhead for passing data between processes
                    """
                    loop = asyncio.get_running_loop()
                    success = await asyncio.wait_for(
                        loop.run_in_executor(self._process_pool, job.execute_sync),
                        timeout=job.timeout_seconds
                    )
                else:
                    success = False

                if success:
                    job.on_success()
                    print(f"  ✅ [{job.concurrency_model.value.upper():7}] {job}")
                else:
                    job.on_failure("Job returned False")
                    print(f"  ❌ [{job.concurrency_model.value.upper():7}] {job}")

            except asyncio.TimeoutError:
                """
                CORE CS CONCEPT: Cooperative Cancellation

                When asyncio.wait_for() times out, it cancels the task:
                  1. asyncio.CancelledError is raised inside the coroutine
                  2. The coroutine can catch it to clean up resources
                  3. If uncaught, the task stops immediately

                For ThreadPoolExecutor/ProcessPoolExecutor:
                  - The thread/process is NOT killed (in-progress work continues)
                  - We log the timeout and move on
                  - The future is cancelled, but the underlying thread completes
                    in the background (orphaned)
                """
                job.on_timeout()
                print(f"  ⏰ [{job.concurrency_model.value.upper():7}] TIMEOUT: {job} after {job.timeout_seconds}s")

            except asyncio.CancelledError:
                """
                CORE CS CONCEPT: Graceful Cancellation

                When the scheduler is shutting down, it cancels all
                running tasks. We catch CancelledError to update job
                status before re-raising.
                """
                job.status = JobStatus.CANCELLED
                job._completed_at = datetime.now()
                print(f"  🛑 [{job.concurrency_model.value.upper():7}] CANCELLED: {job}")
                raise  # Re-raise to propagate cancellation

            except Exception as e:
                job.on_failure(str(e))
                print(f"  ❌ [{job.concurrency_model.value.upper():7}] ERROR: {job} — {e}")

            finally:
                async with self._lock:
                    self._active_jobs.pop(job.job_id, None)

            return job.status == JobStatus.COMPLETED

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job by cancelling its asyncio task."""
        async with self._lock:
            task = self._active_jobs.get(job_id)
            if task and not task.done():
                task.cancel()
                return True
            return False

    async def cancel_all(self) -> None:
        """
        Cancel all running jobs (for graceful shutdown).

        CORE CS CONCEPT: Deadlock Prevention
        We snapshot the task references under the lock, then cancel
        OUTSIDE the lock. This prevents a deadlock when cancelled
        tasks try to acquire the lock in their finally blocks
        (asyncio.Lock is NOT reentrant!).
        """
        async with self._lock:
            tasks = list(self._active_jobs.values())
        # Cancel outside the lock to avoid deadlock on reentrancy
        for task in tasks:
            if not task.done():
                task.cancel()

    async def shutdown(self) -> None:
        """Graceful shutdown: cancel all jobs, shutdown pools."""
        await self.cancel_all()
        self._thread_pool.shutdown(wait=False)
        self._process_pool.shutdown(wait=False)


# ════════════════════════════════════════════════════════════════════════
#  RACE CONDITION DEMONSTRATION
# ════════════════════════════════════════════════════════════════════════

def demonstrate_race_condition(iterations: int = 100_000):
    """
    CORE CS CONCEPT: Live demonstration of a race condition.

    Two threads increment the same counter 100,000 times each.
    Expected result: 200,000.
    Actual result (UnsafeCounter): ~150,000-180,000 (depends on timing)
    Actual result (SafeCounter): 200,000 (always correct)
    """
    print("\n  ┌─ RACE CONDITION DEMONSTRATION ─────────────────────┐")

    # Unsafe version
    unsafe = UnsafeCounter()
    t1 = threading.Thread(target=unsafe.increment, args=(iterations,))
    t2 = threading.Thread(target=unsafe.increment, args=(iterations,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    lost = (2 * iterations) - unsafe.count
    print(f"  │ UNSAFE counter: {unsafe.count:,} "
          f"(lost {lost:,} updates — {lost/(2*iterations)*100:.1f}%) │")

    # Safe version
    safe = SafeCounter()
    t1 = threading.Thread(target=safe.increment, args=(iterations,))
    t2 = threading.Thread(target=safe.increment, args=(iterations,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    print(f"  │ SAFE   counter: {safe.count:,} "
          f"(expected {2*iterations:,})                      │")
    print("  └────────────────────────────────────────────────────┘")
    return lost


# ════════════════════════════════════════════════════════════════════════
#  ASYNC JOB SCHEDULER — Facade Pattern
# ════════════════════════════════════════════════════════════════════════
# The Facade Pattern provides a unified interface to a complex subsystem.
# JobScheduler hides the async executor, scheduling strategies, recurring
# job management, and worker pools behind a simple API:
#
#   scheduler.add_job(job)
#   scheduler.start()
#   scheduler.stop()

class JobScheduler:
    """
    Facade for the async job scheduling system.

    Uses Producer-Consumer pattern:
      Producer — add_job(), recurring job checker
      Consumer — worker coroutines that pull from the queue
    """

    def __init__(self, scheduler_strategy: Optional[SchedulingStrategy] = None,
                 max_concurrent: int = 3,
                 num_workers: int = 2):
        self._executor = AsyncJobExecutor(max_concurrent=max_concurrent)
        self._scheduler = scheduler_strategy or PriorityScheduler()

        # asyncio.Queue: thread-safe producer-consumer channel
        self._job_queue: asyncio.Queue = asyncio.Queue()

        self._pending: List[Job] = []
        self._history: List[Job] = []
        self._recurring: List[RecurringJob] = []

        self._running = False
        self._stop_event = asyncio.Event()
        self._num_workers = num_workers
        self._workers: List[asyncio.Task] = []

    def add_job(self, job: Job) -> None:
        """
        Add a job to the pending list.

        CORE CS CONCEPT: append() on a Python list is an atomic
        operation at the C level for single appends, so this is
        safe without a lock for CPython. However, for production
        code, you'd use a proper lock or asyncio.Queue to be safe
        across Python implementations.
        """
        self._pending.append(job)

    def add_recurring(self, recurring: RecurringJob) -> None:
        """Register a recurring job."""
        self._recurring.append(recurring)

    def set_scheduler(self, strategy: SchedulingStrategy) -> None:
        """Swap scheduling strategy at runtime."""
        self._scheduler = strategy

    async def start(self) -> None:
        """
        Start the scheduler: spawn worker coroutines and the
        scheduler loop. Uses asyncio.create_task() for true
        cooperative multitasking.
        """
        self._running = True
        self._stop_event.clear()

        # Spawn worker tasks (Producer-Consumer pattern)
        for i in range(self._num_workers):
            worker = asyncio.create_task(
                self._worker_loop(i),
                name=f"scheduler-worker-{i}"
            )
            self._workers.append(worker)

        # Spawn scheduler loop
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name="scheduler-loop"
        )
        print(f"  🟢 Scheduler started ({self._num_workers} workers, "
              f"max {self._executor._max_concurrent} concurrent)")

    async def stop(self) -> None:
        """
        Graceful shutdown:

        1. Signal stop (asyncio.Event)
        2. Wait for scheduler loop to finish
        3. Cancel all running jobs
        4. Cancel all workers
        5. Shutdown thread/process pools
        """
        print("  🔴 Scheduler shutting down...")
        self._running = False
        self._stop_event.set()

        # Wait for scheduler loop
        if hasattr(self, '_scheduler_task'):
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        # Cancel workers
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

        # Shutdown executor
        await self._executor.shutdown()
        print("  🔴 Scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """
        Scheduler loop — the 'Producer' in Producer-Consumer.

        Periodically checks for:
        1. Recurring jobs that need instantiation
        2. Pending jobs that need dispatching to the queue

        Runs on the event loop (cooperative) — yields via asyncio.sleep.
        """
        while self._running and not self._stop_event.is_set():
            now = datetime.now()

            # Process recurring jobs
            for rec in self._recurring:
                if rec.is_active and rec.next_run <= now:
                    job = rec.create_job()
                    self.add_job(job)
                    rec.update_next_run()

            # Dispatch pending jobs to the queue
            # Note: using 'await' with the async context manager
            async with self._lock_pending() as pl:
                if pl:
                    ordered = self._scheduler.schedule(pl)
                    for job in ordered:
                        await self._job_queue.put(job)
                    pl.clear()

            # Yield control back to the event loop
            # This is cooperative multitasking in action:
            # the scheduler yields at this await point, allowing
            # worker tasks to process jobs from the queue.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=0.5
                )
                break  # stop event was set
            except asyncio.TimeoutError:
                pass  # Normal: no stop signal, continue loop

    async def _worker_loop(self, worker_id: int) -> None:
        """
        Worker loop — the 'Consumer' in Producer-Consumer.

        Pulls jobs from the queue and executes them via the executor.
        Multiple workers run concurrently (cooperatively).

        CORE CS CONCEPT: When a worker awaits job.execute(), it yields
        control to the event loop. Another worker (or the scheduler loop)
        gets to run. This is how concurrency is achieved with a single
        thread.
        """
        while self._running and not self._stop_event.is_set():
            try:
                # Block until a job is available (with timeout for
                # responsiveness during shutdown)
                try:
                    job = await asyncio.wait_for(
                        self._job_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue  # No job available, loop to check shutdown

                # Execute the job (MUST await — this is an async def!)
                try:
                    await self._executor.execute(job)
                except asyncio.CancelledError:
                    self._job_queue.task_done()
                    raise  # Re-raise to stop this worker
                finally:
                    self._history.append(job)
                    # Always mark task as done for proper Queue cleanup
                    self._job_queue.task_done()

            except asyncio.CancelledError:
                # Worker is being shut down — exit gracefully
                break

            except Exception as e:
                print(f"  ⚠️ Worker {worker_id} error: {e}")
                continue

    def _lock_pending(self):
        """
        Context manager for async-safe access to pending list.

        Uses asyncio.Lock instead of threading.Lock because this is
        called from async context. A threading.Lock would block the
        entire event loop thread! asyncio.Lock yields cooperatively
        to other coroutines when contended.
        """
        return _AsyncPendingLock(self._pending)


class _AsyncPendingLock:
    """
    Async-safe context manager for list access.
    Uses asyncio.Lock which is cooperative (non-blocking to the thread).
    """

    def __init__(self, pending: List):
        self._pending = pending
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._lock.acquire()
        return self._pending

    async def __aexit__(self, *args):
        self._lock.release()


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPT: Exponential Backoff Utility
# ════════════════════════════════════════════════════════════════════════

def exponential_backoff(attempt: int, base_delay: float = 1.0,
                        max_delay: float = 3600.0, jitter: bool = True) -> float:
    """
    Calculate retry delay with exponential backoff and optional jitter.

    Formula: delay = min(base * 2^attempt, max_delay)
    With jitter: delay = random(0, delay) — prevents thundering herd

    CORE CS CONCEPT: Exponential Backoff prevents:
    - Thundering herd (all clients retry simultaneously)
    - Resource exhaustion from rapid retries
    - Cascading failures (one failure triggers more failures)
    """
    import random
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        delay = random.uniform(0, delay)
    return delay


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPT: Context Manager for Timing
# ════════════════════════════════════════════════════════════════════════

class TimingContext:
    """
    Context manager that measures elapsed time.
    Useful for profiling job execution.

    CORE CS CONCEPT: Context managers provide deterministic
    resource cleanup (via __exit__), which is crucial for:
    - Lock release (avoid deadlocks)
    - File handles (avoid fd leaks)
    - Database connections (avoid connection pool exhaustion)
    """

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
    """Full demo showcasing all concurrency models and CS concepts."""
    print("=" * 62)
    print("  JOB SCHEDULING SYSTEM — Async + Concurrency Deep Dive")
    print("=" * 62)

    # ── Section 1: Race Condition Demo ────────────────────────
    print("\n  ┌─ SECTION 1: RACE CONDITION DEMONSTRATION ────────┐")
    print("  │  Shows why threading.Lock() is necessary           │")
    demonstrate_race_condition(100_000)

    # ── Section 2: GIL Demo ───────────────────────────────────
    print("\n  ┌─ SECTION 2: GIL & CONCURRENCY MODELS ────────────┐")
    print("  │  ASYNC   → Cooperative, single-thread, I/O-bound  │")
    print("  │  THREAD  → Preemptive, GIL-bound, mixed workloads │")
    print("  │  PROCESS → True parallelism, CPU-bound             │")
    print("  └────────────────────────────────────────────────────┘")

    # ── Section 3: Job Execution ──────────────────────────────
    print("\n  ┌─ SECTION 3: SCHEDULING JOBS ──────────────────────┐")
    scheduler = JobScheduler(
        scheduler_strategy=WeightedFairScheduler(),
        max_concurrent=4,
        num_workers=3
    )

    # Add one-time jobs with various concurrency models
    scheduler.add_job(EmailJob("alice@email.com", "Welcome!", "Thanks for joining"))
    scheduler.add_job(DataProcessingJob("users_db", "SELECT * FROM active_users"))

    # ASYNC model: lightweight I/O
    report = ReportGenerationJob("Daily Sales", "CSV")

    # THREAD model: mixed workload
    data_job = DataProcessingJob("logs", "CLEANUP old entries")

    # PROCESS model: CPU-intensive (true parallelism)
    cpu_job = CpuIntensiveJob("Matrix Multiply", iterations=10_000_000)
    cpu_job2 = CpuIntensiveJob("Histogram", iterations=10_000_000)

    scheduler.add_job(report)
    scheduler.add_job(data_job)
    scheduler.add_job(cpu_job)
    scheduler.add_job(cpu_job2)

    # Add high priority job (will skip ahead in queue)
    critical_job = EmailJob("admin@system.com", "CRITICAL: Server Alert", "CPU > 90%")
    critical_job._priority = JobPriority.CRITICAL
    scheduler.add_job(critical_job)

    # Add a recurring job (hourly cleanup)
    cleanup = RecurringJob(
        lambda: DataProcessingJob("logs", "CLEANUP temp files"),
        RecurrenceType.HOURLY
    )
    scheduler.add_recurring(cleanup)

    # ── Section 4: Run ───────────────────────────────────────
    await scheduler.start()

    # Wait for jobs to complete: first give the scheduler loop time to
    # dispatch pending jobs to the queue, then wait for queue drain.
    # Note: a small initial sleep is needed because create_task() schedules
    # the scheduler loop "soon" but not immediately — the queue may be
    # empty at start(). After that, queue.join() blocks until all
    # dispatched jobs are processed. Then we wait briefly for stragglers.
    await asyncio.sleep(0.5)                     # Let scheduler dispatch
    await scheduler._job_queue.join()            # Wait for queue drain
    await asyncio.sleep(0.5)                     # Straggler window
    await scheduler.stop()

    # ── Section 5: Stats ─────────────────────────────────────
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

    # ── Section 6: History ───────────────────────────────────
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
    """Entry point: runs the async demo."""
    asyncio.run(async_demo())


# ════════════════════════════════════════════════════════════════════════
#  CORE CS CONCEPTS SUMMARY (for documentation)
# ════════════════════════════════════════════════════════════════════════
#
# 1. GIL (Global Interpreter Lock)
#    - Only one thread executes Python bytecode at a time
#    - Released during I/O, C-extension calls, and lock waits
#    - ProcessPoolExecutor bypasses GIL (separate interpreters)
#
# 2. Race Conditions
#    - Occur when non-atomic operations are interrupted mid-way
#    - Prevented by locks (mutual exclusion), atomic operations
#    - Demonstrated: UnsafeCounter vs SafeCounter
#
# 3. Deadlocks
#    - Circular wait: Thread A holds Lock 1, waits for Lock 2
#                     Thread B holds Lock 2, waits for Lock 1
#    - Prevention: Lock ordering, timeouts, lock hierarchy
#
# 4. Concurrency vs Parallelism
#    - Concurrency: Multiple tasks making progress (interleaved)
#    - Parallelism: Multiple tasks running simultaneously
#    - asyncio = concurrency, multiprocessing = parallelism
#
# 5. Semaphore
#    - Resource counter for limiting concurrent access
#    - asyncio.Semaphore for async, threading.Semaphore for threads
#
# 6. Producer-Consumer
#    - asyncio.Queue decouples job creation from execution
#    - Multiple workers consume from the same queue
#
# 7. Cooperative Cancellation
#    - asyncio.CancelledError allows clean resource cleanup
#    - asyncio.Event signals shutdown across multiple coroutines
#
# 8. Context Managers
#    - Deterministic resource cleanup via __enter__/__exit__
#    - Used for locks, file handles, timing, connections
#
# 9. Exponential Backoff
#    - Prevents thundering herd in retry scenarios
#    - Jitter distributes retry timing randomly
#
# 10. State Machine (Enum-based)
#     - Type-safe state transitions
#     - O(1) comparison for equality checks
#     - Prevents invalid states (e.g., COMPLETED → PENDING)

if __name__ == "__main__":
    demo()
