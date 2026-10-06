"""Tests for job_scheduler.py. Run: python3 -m unittest test_job_scheduler"""

import asyncio
import random
import threading
import time
import unittest
from collections import Counter

from job_scheduler import (
    AgingPriorityStrategy, AsyncJob, CsvExportJob, EarliestDeadlineFirstStrategy,
    EmailJob, FIFOStrategy, FlakyUploadJob, InvalidTransitionError, JobPriority,
    JobScheduler, JobStatus, NonRetryableError, PrimeCountJob, PriorityStrategy,
    RecurringSchedule, RetryPolicy, SchedulerStoppedError, SleepJob, UnknownJobError,
)

NO_RETRY = RetryPolicy(max_retries=0)
FAST_RETRY = RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)


class FailFast(AsyncJob):
    async def run(self):
        raise NonRetryableError("bad input")


class Recorder:
    """Listener that records the order jobs start in and every transition."""

    def __init__(self):
        self.started = []
        self.transitions = []

    def __call__(self, job, old, new):
        self.transitions.append((job.job_id, old, new))
        if new is JobStatus.RUNNING:
            self.started.append(job.job_id)


async def run_all(scheduler, *jobs):
    for job in jobs:
        scheduler.submit(job)
    await scheduler.start()
    await asyncio.wait_for(scheduler.join(), 5)
    await scheduler.stop()


class OrderingTest(unittest.IsolatedAsyncioTestCase):
    async def test_priority_runs_highest_first_fifo_within_priority(self):
        s = JobScheduler(PriorityStrategy(), num_workers=1)
        rec = Recorder()
        s.add_listener(rec)
        low = EmailJob("a", "low", latency=0, priority=JobPriority.LOW)
        med1 = EmailJob("b", "m1", latency=0)
        crit = EmailJob("c", "crit", latency=0, priority=JobPriority.CRITICAL)
        med2 = EmailJob("d", "m2", latency=0)
        await run_all(s, low, med1, crit, med2)
        self.assertEqual(rec.started, [crit.job_id, med1.job_id, med2.job_id, low.job_id])

    async def test_fifo_ignores_priority(self):
        s = JobScheduler(FIFOStrategy(), num_workers=1)
        rec = Recorder()
        s.add_listener(rec)
        jobs = [EmailJob(str(i), "x", latency=0, priority=JobPriority(i % 4)) for i in range(5)]
        await run_all(s, *jobs)
        self.assertEqual(rec.started, [j.job_id for j in jobs])


class StrategyKeyTest(unittest.TestCase):
    def test_aging_lets_an_old_low_job_overtake_a_new_high_job(self):
        aging = AgingPriorityStrategy(age_rate=0.1)
        low = EmailJob("a", "low", priority=JobPriority.LOW)
        high = EmailJob("b", "high", priority=JobPriority.HIGH)
        low.submitted_at, low.seq = 0.0, 0
        high.seq = 1
        high.submitted_at = 10.0      # LOW has aged +1: still behind HIGH
        self.assertLess(aging.key(high), aging.key(low))
        high.submitted_at = 25.0      # LOW has aged +2.5: now ahead
        self.assertLess(aging.key(low), aging.key(high))

    def test_edf_orders_by_deadline_and_puts_no_deadline_last(self):
        edf = EarliestDeadlineFirstStrategy()
        a = EmailJob("a", "x", deadline=50.0)
        b = EmailJob("b", "x", deadline=10.0)
        c = EmailJob("c", "x", priority=JobPriority.CRITICAL)
        for i, j in enumerate((a, b, c)):
            j.seq = i
        self.assertEqual(sorted([a, b, c], key=edf.key), [b, a, c])


class RetryTest(unittest.IsolatedAsyncioTestCase):
    def test_backoff_doubles_and_caps(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter=False)
        rng = random.Random(0)
        self.assertEqual([policy.delay(a, rng) for a in (1, 2, 3, 4)], [1.0, 2.0, 4.0, 5.0])
        jittered = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter=True)
        for attempt in range(1, 10):
            self.assertTrue(0 <= jittered.delay(attempt, rng) <= 5.0)

    async def test_retries_until_success(self):
        s = JobScheduler(num_workers=2)
        rec = Recorder()
        s.add_listener(rec)
        job = FlakyUploadJob("f", failures=2, retry=FAST_RETRY)
        await run_all(s, job)
        self.assertEqual((job.status, job.attempts, job.result), (JobStatus.COMPLETED, 3, "uploaded"))
        retry_waits = [t for t in rec.transitions if t[2] is JobStatus.RETRY_WAIT]
        self.assertEqual(len(retry_waits), 2)

    async def test_gives_up_after_max_retries(self):
        s = JobScheduler(num_workers=1)
        job = FlakyUploadJob("f", failures=99, retry=FAST_RETRY)
        await run_all(s, job)
        self.assertEqual((job.status, job.attempts), (JobStatus.FAILED, 3))
        self.assertIn("ConnectionError", job.last_error)

    async def test_non_retryable_error_fails_immediately(self):
        s = JobScheduler(num_workers=1)
        job = FailFast("bad", retry=FAST_RETRY)
        await run_all(s, job)
        self.assertEqual((job.status, job.attempts), (JobStatus.FAILED, 1))

    async def test_timeout_is_retried_then_reported_as_timed_out(self):
        s = JobScheduler(num_workers=1)
        job = SleepJob("slow", 10, timeout=0.05, retry=RetryPolicy(max_retries=1, base_delay=0.01, jitter=False))
        start = time.monotonic()
        await run_all(s, job)
        self.assertEqual((job.status, job.attempts), (JobStatus.TIMED_OUT, 2))
        self.assertLess(time.monotonic() - start, 1.0)


class CancellationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_pending_job_never_runs(self):
        s = JobScheduler(num_workers=1)
        job = EmailJob("x", "y")
        s.submit(job)
        self.assertTrue(s.cancel(job.job_id))
        self.assertFalse(s.cancel(job.job_id))          # already terminal
        await run_all(s)
        self.assertEqual((job.status, job.attempts), (JobStatus.CANCELLED, 0))

    async def test_cancel_running_async_job(self):
        s = JobScheduler(num_workers=1)
        job = SleepJob("long", 10, timeout=None)
        s.submit(job)
        await s.start()
        while job.status is not JobStatus.RUNNING:
            await asyncio.sleep(0.005)
        self.assertTrue(s.cancel(job.job_id))
        await asyncio.wait_for(s.join(), 1)
        await s.stop()
        self.assertEqual(job.status, JobStatus.CANCELLED)

    async def test_stop_with_cancel_running_and_reject_new_submits(self):
        s = JobScheduler(num_workers=1)
        job = SleepJob("long", 10, timeout=None)
        s.submit(job)
        await s.start()
        while job.status is not JobStatus.RUNNING:
            await asyncio.sleep(0.005)
        await asyncio.wait_for(s.stop(cancel_running=True), 1)
        self.assertEqual(job.status, JobStatus.CANCELLED)
        with self.assertRaises(SchedulerStoppedError):
            s.submit(EmailJob("x", "y"))

    def test_illegal_transition_is_rejected(self):
        s = JobScheduler()
        job = EmailJob("x", "y")
        s.submit(job)
        with self.assertRaises(InvalidTransitionError):
            s._transition(job, JobStatus.COMPLETED)     # PENDING -> COMPLETED skips RUNNING


class DependencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_dependent_waits_for_all_upstreams(self):
        s = JobScheduler(num_workers=3)
        rec = Recorder()
        s.add_listener(rec)
        a, b = SleepJob("a", 0.05), SleepJob("b", 0.02)
        c = EmailJob("c", "after a and b", latency=0)
        s.submit(a)
        s.submit(b)
        s.submit(c, depends_on=[a.job_id, b.job_id])
        await run_all(s)
        self.assertEqual(c.status, JobStatus.COMPLETED)
        self.assertEqual(rec.started[-1], c.job_id)
        self.assertGreaterEqual(c.started_at, a.finished_at)

    async def test_upstream_failure_cascades_down_the_chain(self):
        s = JobScheduler(num_workers=2)
        a = FailFast("a")
        b = EmailJob("b", "x")
        c = EmailJob("c", "x")
        s.submit(a)
        s.submit(b, depends_on=[a.job_id])
        s.submit(c, depends_on=[b.job_id])
        await run_all(s)
        self.assertEqual([j.status for j in (a, b, c)],
                         [JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.CANCELLED])
        self.assertEqual((b.attempts, c.attempts), (0, 0))

    def test_unknown_dependency_is_rejected(self):
        s = JobScheduler()
        with self.assertRaises(UnknownJobError):
            s.submit(EmailJob("x", "y"), depends_on=["job-does-not-exist"])


class ExecutionModelTest(unittest.IsolatedAsyncioTestCase):
    async def test_thread_and_process_jobs_return_results(self):
        s = JobScheduler(num_workers=2)
        export = CsvExportJob("t", rows=7)
        primes = PrimeCountJob(100)
        await run_all(s, export, primes)
        self.assertEqual((export.status, export.result), (JobStatus.COMPLETED, 7))
        self.assertEqual((primes.status, primes.result), (JobStatus.COMPLETED, 25))

    async def test_delayed_job_does_not_start_early(self):
        s = JobScheduler(num_workers=1)
        job = EmailJob("x", "y", latency=0)
        s.submit(job, delay=0.1)
        t0 = time.monotonic()
        await run_all(s)
        self.assertGreaterEqual(job.started_at - t0, 0.09)


class ConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_jobs_overlap_and_never_exceed_worker_count(self):
        s = JobScheduler(num_workers=3)
        jobs = [SleepJob(f"s{i}", 0.1) for i in range(6)]
        t0 = time.monotonic()
        await run_all(s, *jobs)
        elapsed = time.monotonic() - t0
        self.assertEqual(s.peak_running, 3)
        self.assertLess(elapsed, 0.5)                   # 2 waves of 0.1 s, not 6 serial
        self.assertTrue(all(j.status is JobStatus.COMPLETED for j in jobs))

    async def test_submit_threadsafe_from_many_threads_runs_each_job_once(self):
        s = JobScheduler(num_workers=4)
        rec = Recorder()
        s.add_listener(rec)
        await s.start()
        jobs = [EmailJob(f"u{i}", "hi", latency=0) for i in range(200)]
        barrier = threading.Barrier(8)

        def producer(chunk):
            barrier.wait()
            for job in chunk:
                s.submit_threadsafe(job)

        threads = [threading.Thread(target=producer, args=(jobs[i::8],)) for i in range(8)]
        for t in threads:
            t.start()
        await asyncio.get_running_loop().run_in_executor(None, lambda: [t.join() for t in threads])
        await asyncio.sleep(0)                          # let queued call_soon_threadsafe callbacks run
        await asyncio.wait_for(s.join(), 5)
        await s.stop()
        self.assertTrue(all(j.status is JobStatus.COMPLETED for j in jobs))
        runs = Counter(rec.started)
        self.assertEqual(len(runs), 200)
        self.assertEqual(set(runs.values()), {1})


class RecurringTest(unittest.IsolatedAsyncioTestCase):
    def test_fixed_rate_and_missed_fires_coalesce(self):
        sched = RecurringSchedule(lambda: EmailJob("x", "y"), interval=10, first_run=100)
        sched.advance(now=100.5)
        self.assertEqual(sched.next_run, 110)           # from the scheduled time, no drift
        sched.advance(now=145)                          # woke 3.5 intervals late
        self.assertEqual(sched.next_run, 150)           # one fire, then the next future slot

    async def test_recurring_fires_and_skips_overlap(self):
        s = JobScheduler(num_workers=4)
        sid = s.schedule_recurring(lambda: SleepJob("tick", 0.12), interval=0.03)
        sched = s._recurring[sid]
        await s.start()
        await asyncio.sleep(0.3)
        s.cancel_recurring(sid)
        await asyncio.wait_for(s.join(), 2)
        await s.stop()
        ticks = [j for j in s.jobs() if j.name == "tick"]
        self.assertGreaterEqual(sched.fired, 2)
        self.assertGreater(sched.skipped, 0)
        self.assertEqual(len(ticks), sched.fired)
        # allow_overlap=False: no two instances ever ran at the same time
        spans = sorted((j.started_at, j.finished_at) for j in ticks)
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertGreaterEqual(start, end)


class HistoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_finished_jobs_are_evicted_beyond_history_limit(self):
        s = JobScheduler(num_workers=2, history_limit=5)
        jobs = [EmailJob(str(i), "x", latency=0) for i in range(12)]
        await run_all(s, *jobs)
        self.assertEqual(len(s.jobs()), 5)
        with self.assertRaises(UnknownJobError):
            s.get(jobs[0].job_id)


if __name__ == "__main__":
    unittest.main()
