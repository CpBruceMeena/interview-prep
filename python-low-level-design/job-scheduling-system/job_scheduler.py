"""
Job Scheduling System — Low Level Design
=========================================

An in-process job scheduler built on asyncio:

  * one-shot, delayed and recurring (fixed-interval) jobs
  * pluggable ordering: FIFO, priority, priority-with-aging, earliest-deadline-first
  * per-job timeout, retries with capped exponential backoff + full jitter
  * cancellation of pending and running jobs
  * dependencies between jobs (a small DAG); upstream failure cancels dependents
  * three execution models per job: ASYNC (event loop), THREAD (thread pool),
    PROCESS (process pool, for CPU-bound work that must escape the GIL)
  * graceful shutdown, and a thread-safe submit for producers on other threads

Concurrency model of the scheduler itself
-----------------------------------------
All scheduler state (heaps, maps, counters) is owned by ONE event-loop thread.
Every check-then-act sequence on that state runs without an `await` in the
middle, so no other coroutine can interleave and no lock is needed. Work that
leaves the loop (THREAD / PROCESS jobs) only returns a value; it never touches
scheduler state. Producers on other threads must use `submit_threadsafe`, which
hops onto the loop with `call_soon_threadsafe`.

Patterns: Command (Job), Strategy (SchedulingStrategy), Observer (listeners),
Producer-Consumer (submit -> ready heap -> worker coroutines).

Run:   python3 job_scheduler.py
Test:  python3 -m unittest test_job_scheduler
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import math
import random
import time
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Callable, ClassVar, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
#  ENUMS + STATE MACHINE
# ════════════════════════════════════════════════════════════════════════

class JobPriority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class JobStatus(Enum):
    PENDING = "pending"          # waiting for its run time, its dependencies, or a worker
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"    # failed, waiting out its backoff delay
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED}

# Every legal edge. Anything else is a bug and raises InvalidTransitionError.
_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMED_OUT,
                        JobStatus.CANCELLED, JobStatus.RETRY_WAIT},
    JobStatus.RETRY_WAIT: {JobStatus.RUNNING, JobStatus.CANCELLED},
}


class ConcurrencyModel(Enum):
    """
    ASYNC   — runs on the event loop. For I/O-bound code written with await.
              Blocking calls here stall EVERY job, so never do CPU work in one.
    THREAD  — runs in a ThreadPoolExecutor. For blocking I/O (sync DB drivers,
              requests). Threads share the GIL, so CPU-bound Python gets ~no speedup.
    PROCESS — runs in a ProcessPoolExecutor. Separate interpreter (and GIL) per
              worker, so CPU-bound work runs in parallel. The job object and its
              result are pickled across the process boundary.
    """
    ASYNC = "async"
    THREAD = "thread"
    PROCESS = "process"


# ════════════════════════════════════════════════════════════════════════
#  EXCEPTIONS
# ════════════════════════════════════════════════════════════════════════

class SchedulerError(Exception):
    pass


class InvalidTransitionError(SchedulerError):
    pass


class UnknownJobError(SchedulerError, KeyError):
    pass


class SchedulerStoppedError(SchedulerError):
    pass


class NonRetryableError(Exception):
    """Raise from a job to fail it immediately, skipping remaining retries."""


# ════════════════════════════════════════════════════════════════════════
#  RETRY POLICY
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RetryPolicy:
    """
    Capped exponential backoff with optional "full jitter":
        cap   = min(max_delay, base_delay * 2 ** (attempt - 1))
        delay = uniform(0, cap)   if jitter else cap
    `attempt` is the 1-based number of the attempt that just failed.
    Full jitter spreads retries of many jobs that failed together (e.g. a
    dependency outage) so they don't come back as a synchronized herd.
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True

    def delay(self, attempt: int, rng: random.Random) -> float:
        cap = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return rng.uniform(0, cap) if self.jitter else cap


# ════════════════════════════════════════════════════════════════════════
#  JOB — Command pattern
# ════════════════════════════════════════════════════════════════════════

_job_ids = itertools.count(1)


class Job(ABC):
    """
    What to run plus how to run it (priority, timeout, retry policy).

    Execution state (status, attempts, timestamps, result) lives on the job
    for simplicity but is written ONLY by the scheduler, on the loop thread.
    A job must stay picklable (no locks, tasks or open handles as attributes)
    so PROCESS jobs can be shipped to a worker process.
    """

    model: ClassVar[ConcurrencyModel]

    def __init__(self, name: str, *,
                 priority: JobPriority = JobPriority.MEDIUM,
                 timeout: Optional[float] = 30.0,
                 retry: RetryPolicy = RetryPolicy(),
                 deadline: Optional[float] = None) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive or None")
        self.job_id = f"job-{next(_job_ids)}"
        self.name = name
        self.priority = priority
        self.timeout = timeout
        self.retry = retry
        self.deadline = deadline        # monotonic seconds; used by EDF only

        self.status = JobStatus.PENDING
        self.attempts = 0
        self.result: Any = None
        self.last_error: Optional[str] = None
        self.submitted_at: float = 0.0  # monotonic, set on submit
        self.run_at: float = 0.0        # earliest monotonic time it may start
        self.seq: int = 0               # submit order, the universal tie-breaker
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.job_id}, {self.name!r}, {self.status.value})"


class AsyncJob(Job):
    model = ConcurrencyModel.ASYNC

    @abstractmethod
    async def run(self) -> Any:
        """Do the work. Return a result, or raise to fail this attempt."""


class BlockingJob(Job):
    """Synchronous work, run off the event loop in the thread pool."""
    model = ConcurrencyModel.THREAD

    @abstractmethod
    def run_sync(self) -> Any:
        """Do the work. Return a result, or raise to fail this attempt."""


class CpuBoundJob(BlockingJob):
    """Synchronous CPU-heavy work, run in the process pool (bypasses the GIL)."""
    model = ConcurrencyModel.PROCESS


# ════════════════════════════════════════════════════════════════════════
#  SCHEDULING STRATEGIES — Strategy pattern
# ════════════════════════════════════════════════════════════════════════
# A strategy turns a job into a sort key; the smallest key runs first. Keys are
# computed once, when a job becomes runnable, and must therefore NOT depend on
# the current time. That is what lets the ready queue be a heap (O(log n) push
# and pop) instead of re-sorting every pending job on every dispatch.

SortKey = Tuple[Any, ...]


class SchedulingStrategy(ABC):
    @abstractmethod
    def key(self, job: Job) -> SortKey:
        """Smaller runs first. Must be time-invariant (see note above)."""


class FIFOStrategy(SchedulingStrategy):
    """Submit order. No starvation, no prioritisation."""

    def key(self, job: Job) -> SortKey:
        return (job.seq,)


class PriorityStrategy(SchedulingStrategy):
    """Highest priority first, FIFO within a priority. Low priority can starve."""

    def key(self, job: Job) -> SortKey:
        return (-job.priority, job.seq)


class AgingPriorityStrategy(SchedulingStrategy):
    """
    Priority with aging, which bounds starvation:
        effective(now) = priority + age_rate * (now - submitted_at)
    Every waiting job ages at the same rate, so comparing two jobs at any
    `now` gives the same answer as comparing (priority - age_rate * submitted_at).
    That expression is time-invariant, so it still works as a heap key.
    With age_rate=0.1, a LOW job outranks a newly submitted HIGH job after
    waiting 20 s (2 priority levels / 0.1 per second).
    """

    def __init__(self, age_rate: float = 0.1) -> None:
        if age_rate <= 0:
            raise ValueError("age_rate must be positive")
        self._age_rate = age_rate

    def key(self, job: Job) -> SortKey:
        return (-(job.priority - self._age_rate * job.submitted_at), job.seq)


class EarliestDeadlineFirstStrategy(SchedulingStrategy):
    """Earliest deadline first; jobs without a deadline go last, by priority."""

    def key(self, job: Job) -> SortKey:
        deadline = job.deadline if job.deadline is not None else math.inf
        return (deadline, -job.priority, job.seq)


# ════════════════════════════════════════════════════════════════════════
#  RECURRING SCHEDULE
# ════════════════════════════════════════════════════════════════════════

class RecurringSchedule:
    """
    Fires `factory()` every `interval` seconds.

    * Fixed-rate, not fixed-delay: the next fire time is computed from the
      previous SCHEDULED time, so slow ticks don't make the schedule drift.
    * Missed fires are coalesced: if the ticker wakes up 3 intervals late, the
      job fires once and the schedule jumps to the next future slot.
    * allow_overlap=False skips a fire while the previous instance is unfinished.
    """

    _ids = itertools.count(1)

    def __init__(self, factory: Callable[[], Job], interval: float,
                 first_run: float, allow_overlap: bool = False) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.schedule_id = f"sched-{next(self._ids)}"
        self.factory = factory
        self.interval = interval
        self.next_run = first_run
        self.allow_overlap = allow_overlap
        self.active = True
        self.last_job_id: Optional[str] = None
        self.fired = 0
        self.skipped = 0

    def advance(self, now: float) -> None:
        missed = int((now - self.next_run) // self.interval) + 1
        self.next_run += max(missed, 1) * self.interval


# ════════════════════════════════════════════════════════════════════════
#  JOB EXECUTOR — routes a job to the event loop, a thread, or a process
# ════════════════════════════════════════════════════════════════════════

class JobExecutor:
    """
    Owns the thread and process pools. Pools are created lazily, so a
    scheduler that only runs ASYNC jobs never forks a process.

    Size the thread pool >= the scheduler's worker count: a job that times out
    in a thread keeps running there (Python cannot kill a thread), and until
    it returns it occupies a pool slot.
    """

    def __init__(self, max_threads: int = 4, max_processes: int = 2) -> None:
        self._max_threads = max_threads
        self._max_processes = max_processes
        self._threads: Optional[ThreadPoolExecutor] = None
        self._processes: Optional[ProcessPoolExecutor] = None

    async def invoke(self, job: Job) -> Any:
        if isinstance(job, AsyncJob):
            return await job.run()
        if not isinstance(job, BlockingJob):
            raise TypeError(f"{type(job).__name__} must extend AsyncJob or BlockingJob")
        loop = asyncio.get_running_loop()
        if job.model is ConcurrencyModel.PROCESS:
            if self._processes is None:
                self._processes = ProcessPoolExecutor(max_workers=self._max_processes)
            # Pickles `job` (bound method) into the worker; only the return
            # value comes back. State the job mutates over there is lost.
            return await loop.run_in_executor(self._processes, job.run_sync)
        if self._threads is None:
            self._threads = ThreadPoolExecutor(max_workers=self._max_threads,
                                               thread_name_prefix="job")
        return await loop.run_in_executor(self._threads, job.run_sync)

    def shutdown(self) -> None:
        # Don't block the loop on stragglers (e.g. a timed-out thread job);
        # drop work that never started.
        for pool in (self._threads, self._processes):
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)
        self._threads = self._processes = None


# ════════════════════════════════════════════════════════════════════════
#  JOB SCHEDULER
# ════════════════════════════════════════════════════════════════════════

JobListener = Callable[[Job, JobStatus, JobStatus], None]


class JobScheduler:
    """
    Data structures (all owned by the event-loop thread):

      _ready      heap of (strategy key, job)     runnable now
      _delayed    heap of (run_at, seq, job)      delayed first run or retry backoff
      _blocked    job_id -> unmet dependency ids
      _dependents job_id -> ids of jobs waiting on it
      _attempts   job_id -> asyncio.Task of the attempt in flight

    Cancelled jobs are not removed from the heaps (that would be O(n)); they
    are skipped when popped ("lazy deletion").
    """

    def __init__(self, strategy: Optional[SchedulingStrategy] = None, *,
                 num_workers: int = 4,
                 executor: Optional[JobExecutor] = None,
                 rng: Optional[random.Random] = None,
                 history_limit: int = 10_000) -> None:
        if num_workers < 1:
            raise ValueError("num_workers must be >= 1")
        self._strategy = strategy or PriorityStrategy()
        self._num_workers = num_workers
        self._executor = executor or JobExecutor(max_threads=num_workers)
        self._rng = rng or random.Random()
        self._history_limit = history_limit

        self._jobs: Dict[str, Job] = {}
        self._ready: List[Tuple[SortKey, Job]] = []
        self._delayed: List[Tuple[float, int, Job]] = []
        self._blocked: Dict[str, Set[str]] = {}
        self._dependents: Dict[str, List[str]] = {}
        self._attempts: Dict[str, asyncio.Task] = {}
        self._cancel_requested: Set[str] = set()
        self._finished: deque = deque()           # terminal job ids, oldest first
        self._recurring: Dict[str, RecurringSchedule] = {}
        self._listeners: List[JobListener] = []
        self._seq = itertools.count()

        self._unfinished = 0
        self._running_count = 0
        self.peak_running = 0                     # observability + tests

        self._idle = asyncio.Event()
        self._idle.set()
        self._work_available = asyncio.Event()
        self._ticker_wakeup = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: List[asyncio.Task] = []
        self._started = False
        self._stopping = False

    # ── Public API (call on the loop thread unless noted) ─────────────

    def add_listener(self, listener: JobListener) -> None:
        """Observer hook: called as listener(job, old_status, new_status)."""
        self._listeners.append(listener)

    def submit(self, job: Job, *, delay: float = 0.0,
               depends_on: Iterable[str] = ()) -> str:
        """Queue a job. Returns its id. Dependencies must already be submitted."""
        if self._stopping:
            raise SchedulerStoppedError("scheduler is stopping")
        if job.job_id in self._jobs or job.status is not JobStatus.PENDING or job.attempts:
            raise SchedulerError(f"{job.job_id} was already submitted")
        deps = set(depends_on)
        unknown = [d for d in deps if d not in self._jobs]
        if unknown:
            # Requiring deps to exist first also makes cycles impossible.
            raise UnknownJobError(f"unknown dependencies: {sorted(unknown)}")

        now = time.monotonic()
        job.seq = next(self._seq)
        job.submitted_at = now
        job.run_at = now + max(0.0, delay)
        self._jobs[job.job_id] = job
        self._unfinished += 1
        self._idle.clear()

        failed_dep = next((d for d in deps if self._jobs[d].status.is_terminal
                           and self._jobs[d].status is not JobStatus.COMPLETED), None)
        if failed_dep is not None:
            self._finish(job, JobStatus.CANCELLED, error=f"upstream {failed_dep} did not complete")
            return job.job_id
        unmet = {d for d in deps if self._jobs[d].status is not JobStatus.COMPLETED}
        if unmet:
            self._blocked[job.job_id] = unmet
            for d in unmet:
                self._dependents.setdefault(d, []).append(job.job_id)
        else:
            self._enqueue(job)
        return job.job_id

    def submit_threadsafe(self, job: Job, **kwargs: Any) -> str:
        """
        Submit from ANY thread. The real submit runs on the loop thread, so the
        scheduler's data structures are still touched by one thread only.
        asyncio objects (Event, Task, heaps we own) are not thread-safe.
        """
        if self._loop is None:
            raise SchedulerError("start() the scheduler before submitting from other threads")
        self._loop.call_soon_threadsafe(self._submit_logged, job, kwargs)
        return job.job_id

    def schedule_recurring(self, factory: Callable[[], Job], interval: float, *,
                           start_in: float = 0.0, allow_overlap: bool = False) -> str:
        sched = RecurringSchedule(factory, interval, time.monotonic() + start_in, allow_overlap)
        self._recurring[sched.schedule_id] = sched
        self._ticker_wakeup.set()
        return sched.schedule_id

    def cancel_recurring(self, schedule_id: str) -> bool:
        sched = self._recurring.get(schedule_id)
        if sched is None or not sched.active:
            return False
        sched.active = False
        return True

    def cancel(self, job_id: str) -> bool:
        """
        Cancel a job. Returns False if it is unknown or already finished.
        A queued job is cancelled immediately. A running ASYNC job gets
        CancelledError at its next await. A running THREAD/PROCESS job is
        abandoned: its status becomes CANCELLED but the thread or process
        finishes the call anyway (neither can be interrupted safely).
        """
        job = self._jobs.get(job_id)
        if job is None or job.status.is_terminal:
            return False
        if job.status is JobStatus.RUNNING:
            self._cancel_requested.add(job_id)      # the worker settles the final status
            attempt = self._attempts.get(job_id)
            if attempt is not None:
                attempt.cancel()
        else:
            self._finish(job, JobStatus.CANCELLED, error="cancelled")
        return True

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise UnknownJobError(job_id) from None

    def jobs(self) -> List[Job]:
        return list(self._jobs.values())

    async def join(self) -> None:
        """Wait until every submitted job has reached a terminal state."""
        await self._idle.wait()

    async def start(self) -> None:
        if self._started:
            raise SchedulerError("already started")
        self._started = True
        self._loop = asyncio.get_running_loop()
        self._tasks = [asyncio.create_task(self._worker(i), name=f"job-worker-{i}")
                       for i in range(self._num_workers)]
        self._tasks.append(asyncio.create_task(self._ticker(), name="job-ticker"))

    async def stop(self, *, cancel_running: bool = False) -> None:
        """
        Graceful shutdown. New submits are rejected; workers finish the job
        they are on (or cancel it if cancel_running) and exit; queued jobs are
        left PENDING (a durable store would hand them to the next instance).
        """
        self._stopping = True
        if cancel_running:
            for job_id in list(self._attempts):
                self.cancel(job_id)
        self._work_available.set()
        self._ticker_wakeup.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._executor.shutdown()

    # ── Internals: queueing ───────────────────────────────────────────

    def _submit_logged(self, job: Job, kwargs: Dict[str, Any]) -> None:
        try:
            self.submit(job, **kwargs)
        except SchedulerError:
            logger.exception("threadsafe submit of %s failed", job.job_id)

    def _enqueue(self, job: Job) -> None:
        if job.run_at > time.monotonic():
            heapq.heappush(self._delayed, (job.run_at, job.seq, job))
        else:
            heapq.heappush(self._ready, (self._strategy.key(job), job))
        self._work_available.set()

    def _promote_due(self, now: float) -> None:
        while self._delayed and self._delayed[0][0] <= now:
            _, _, job = heapq.heappop(self._delayed)
            if not job.status.is_terminal:
                heapq.heappush(self._ready, (self._strategy.key(job), job))

    def _take_next(self) -> Optional[Job]:
        """Pop the best runnable job and mark it RUNNING. No await inside, so atomic."""
        self._promote_due(time.monotonic())
        while self._ready:
            _, job = heapq.heappop(self._ready)
            if job.status.is_terminal:          # lazily deleted (cancelled while queued)
                continue
            self._transition(job, JobStatus.RUNNING)
            return job
        return None

    def _next_wakeup_in(self) -> Optional[float]:
        if not self._delayed:
            return None
        return max(0.0, self._delayed[0][0] - time.monotonic())

    # ── Internals: workers ────────────────────────────────────────────

    async def _worker(self, worker_id: int) -> None:
        while True:
            job = None if self._stopping else self._take_next()
            if job is None:
                if self._stopping:
                    return
                # Clear-then-wait is safe: nothing can set the event between
                # _take_next() returning None and clear(), because there is no
                # await in between. Every waiter wakes on set() and re-checks.
                self._work_available.clear()
                try:
                    await asyncio.wait_for(self._work_available.wait(), self._next_wakeup_in())
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self._run_attempt(job)
            except asyncio.CancelledError:
                raise                               # the worker itself is being torn down
            except Exception:                       # a bug in our own bookkeeping
                logger.exception("worker %d crashed on %s", worker_id, job.job_id)

    async def _run_attempt(self, job: Job) -> None:
        job.attempts += 1
        job.started_at = time.monotonic()
        self._running_count += 1
        self.peak_running = max(self.peak_running, self._running_count)

        # Run the attempt as its own task so cancel(job_id) can target it without
        # cancelling the worker, and so the timeout below is unambiguous.
        attempt = asyncio.create_task(self._executor.invoke(job))
        self._attempts[job.job_id] = attempt
        try:
            done, _ = await asyncio.wait({attempt}, timeout=job.timeout)
            if not done:                            # timed out: stop waiting for it
                attempt.cancel()
                await asyncio.gather(attempt, return_exceptions=True)
        except asyncio.CancelledError:
            attempt.cancel()
            self._finish(job, JobStatus.CANCELLED, error="scheduler shut down")
            raise
        finally:
            self._attempts.pop(job.job_id, None)
            self._running_count -= 1

        if job.job_id in self._cancel_requested or (done and attempt.cancelled()):
            self._finish(job, JobStatus.CANCELLED, error="cancelled")
        elif not done:
            self._after_failure(job, f"timed out after {job.timeout}s", timed_out=True)
        elif attempt.exception() is not None:
            exc = attempt.exception()
            self._after_failure(job, f"{type(exc).__name__}: {exc}",
                                retryable=not isinstance(exc, NonRetryableError))
        else:
            job.result = attempt.result()
            self._finish(job, JobStatus.COMPLETED)

    def _after_failure(self, job: Job, error: str, *,
                       retryable: bool = True, timed_out: bool = False) -> None:
        job.last_error = error
        if retryable and job.attempts <= job.retry.max_retries and not self._stopping:
            backoff = job.retry.delay(job.attempts, self._rng)
            job.run_at = time.monotonic() + backoff
            self._transition(job, JobStatus.RETRY_WAIT)
            self._enqueue(job)
        else:
            self._finish(job, JobStatus.TIMED_OUT if timed_out else JobStatus.FAILED, error=error)

    # ── Internals: recurring ──────────────────────────────────────────

    async def _ticker(self) -> None:
        while not self._stopping:
            now = time.monotonic()
            for sched in list(self._recurring.values()):
                if not sched.active:
                    del self._recurring[sched.schedule_id]
                elif sched.next_run <= now:
                    try:
                        self._fire(sched, now)
                    except Exception:               # a broken factory must not kill the ticker
                        logger.exception("recurring %s failed to fire", sched.schedule_id)
            next_due = min((s.next_run for s in self._recurring.values()), default=None)
            timeout = None if next_due is None else max(0.0, next_due - time.monotonic())
            self._ticker_wakeup.clear()
            try:
                await asyncio.wait_for(self._ticker_wakeup.wait(), timeout)
            except asyncio.TimeoutError:
                pass

    def _fire(self, sched: RecurringSchedule, now: float) -> None:
        sched.advance(now)
        previous = self._jobs.get(sched.last_job_id) if sched.last_job_id else None
        if previous is not None and not previous.status.is_terminal and not sched.allow_overlap:
            sched.skipped += 1
            return
        sched.last_job_id = self.submit(sched.factory())
        sched.fired += 1

    # ── Internals: state changes ──────────────────────────────────────

    def _transition(self, job: Job, new: JobStatus) -> None:
        old = job.status
        if new not in _TRANSITIONS.get(old, set()):
            raise InvalidTransitionError(f"{job.job_id}: {old.value} -> {new.value}")
        job.status = new
        for listener in self._listeners:
            try:
                listener(job, old, new)
            except Exception:                       # a bad listener must not kill a worker
                logger.exception("listener failed for %s", job.job_id)

    def _finish(self, job: Job, status: JobStatus, *, error: Optional[str] = None) -> None:
        if job.status.is_terminal:
            return
        if error is not None:
            job.last_error = error
        job.finished_at = time.monotonic()
        self._transition(job, status)
        self._cancel_requested.discard(job.job_id)
        self._blocked.pop(job.job_id, None)

        for dep_id in self._dependents.pop(job.job_id, []):
            dependent = self._jobs.get(dep_id)
            if dependent is None or dependent.status.is_terminal:
                continue
            if status is JobStatus.COMPLETED:
                unmet = self._blocked.get(dep_id)
                if unmet is not None:
                    unmet.discard(job.job_id)
                    if not unmet:
                        del self._blocked[dep_id]
                        self._enqueue(dependent)
            else:                                   # cascade: upstream did not complete
                self._finish(dependent, JobStatus.CANCELLED,
                             error=f"upstream {job.job_id} {status.value}")

        self._unfinished -= 1
        if self._unfinished == 0:
            self._idle.set()
        self._remember_finished(job.job_id)

    def _remember_finished(self, job_id: str) -> None:
        # Bound memory: a recurring job would otherwise grow _jobs forever.
        self._finished.append(job_id)
        while len(self._finished) > self._history_limit:
            old = self._finished.popleft()
            self._jobs.pop(old, None)


# ════════════════════════════════════════════════════════════════════════
#  EXAMPLE JOBS (used by the demo and the tests)
# ════════════════════════════════════════════════════════════════════════

class EmailJob(AsyncJob):
    """I/O-bound: awaits the network, so it belongs on the event loop."""

    def __init__(self, to: str, subject: str, latency: float = 0.05, **kw: Any) -> None:
        super().__init__(f"email {to}: {subject}", **kw)
        self.to = to
        self.latency = latency

    async def run(self) -> str:
        await asyncio.sleep(self.latency)
        return f"sent to {self.to}"


class FlakyUploadJob(AsyncJob):
    """Fails its first `failures` attempts, then succeeds. Exercises retries."""

    def __init__(self, path: str, failures: int, **kw: Any) -> None:
        super().__init__(f"upload {path}", **kw)
        self.failures = failures

    async def run(self) -> str:
        await asyncio.sleep(0.01)
        if self.attempts <= self.failures:
            raise ConnectionError(f"attempt {self.attempts}: connection reset")
        return "uploaded"


class SleepJob(AsyncJob):
    def __init__(self, name: str, seconds: float, **kw: Any) -> None:
        super().__init__(name, **kw)
        self.seconds = seconds

    async def run(self) -> float:
        await asyncio.sleep(self.seconds)
        return self.seconds


class CsvExportJob(BlockingJob):
    """Blocking I/O (a sync DB driver, say): runs in the thread pool."""

    def __init__(self, table: str, rows: int = 1_000, **kw: Any) -> None:
        super().__init__(f"export {table}", **kw)
        self.rows = rows

    def run_sync(self) -> int:
        time.sleep(0.02)                            # releases the GIL while "waiting on the DB"
        return self.rows


class PrimeCountJob(CpuBoundJob):
    """CPU-bound: counts primes below n. Runs in a separate process."""

    def __init__(self, n: int, **kw: Any) -> None:
        super().__init__(f"count primes < {n}", **kw)
        self.n = n

    def run_sync(self) -> int:
        sieve = bytearray([1]) * self.n
        sieve[:2] = b"\x00\x00"
        for i in range(2, int(self.n ** 0.5) + 1):
            if sieve[i]:
                sieve[i * i::i] = bytearray(len(range(i * i, self.n, i)))
        return sum(sieve)


# ════════════════════════════════════════════════════════════════════════
#  DEMO
# ════════════════════════════════════════════════════════════════════════

async def _demo() -> None:
    scheduler = JobScheduler(PriorityStrategy(), num_workers=3, rng=random.Random(7))
    fast_retry = RetryPolicy(max_retries=3, base_delay=0.02, jitter=False)

    export = CsvExportJob("orders", rows=4_200)
    primes = PrimeCountJob(200_000, timeout=30)
    report = EmailJob("finance@corp", "daily report")
    alert = EmailJob("oncall@corp", "disk 91%", priority=JobPriority.CRITICAL)
    flaky = FlakyUploadJob("s3://bucket/report.csv", failures=2, retry=fast_retry)
    dead = FlakyUploadJob("s3://bucket/broken.csv", failures=99, retry=fast_retry)
    slow = SleepJob("slow-endpoint", 5.0, timeout=0.1, retry=RetryPolicy(max_retries=0))
    notify = EmailJob("team@corp", "upload done")
    later = EmailJob("me@corp", "reminder")

    for job in (export, primes, alert, flaky, dead, slow, later):
        scheduler.submit(job)
    scheduler.submit(report, depends_on=[export.job_id, primes.job_id])
    scheduler.submit(notify, depends_on=[dead.job_id])  # upstream will fail -> cancelled
    scheduler.cancel(later.job_id)

    # Recurring: stop after the third heartbeat completes (fires at ~0, 0.1, 0.2 s).
    beats_done = asyncio.Event()
    beats: List[Job] = []

    def count_heartbeats(job: Job, old: JobStatus, new: JobStatus) -> None:
        if job.name == "email ops@corp: heartbeat" and new is JobStatus.COMPLETED:
            beats.append(job)
            if len(beats) == 3:
                beats_done.set()

    scheduler.add_listener(count_heartbeats)
    heartbeat = scheduler.schedule_recurring(lambda: EmailJob("ops@corp", "heartbeat"),
                                             interval=0.1)

    await scheduler.start()
    await beats_done.wait()
    scheduler.cancel_recurring(heartbeat)
    await scheduler.join()
    await scheduler.stop()

    print("=" * 72)
    print("  JOB SCHEDULER DEMO")
    print("=" * 72)
    shown = [export, primes, report, alert, flaky, dead, slow, notify, later]
    for job in shown:
        detail = job.result if job.status is JobStatus.COMPLETED else job.last_error
        print(f"  {job.name:<34} {job.status.value:<10} attempts={job.attempts}  {detail}")
    print(f"  recurring heartbeat completed {len(beats)} runs, then was cancelled")
    print(f"  peak concurrent jobs: {scheduler.peak_running} (workers: 3)")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
