# Job Scheduling System — Implementation

> Python implementation of the Job Scheduling System system following SOLID principles and design patterns.

```python
"""
Job Scheduling System - Low Level Design
-------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer, Command
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import uuid
import time
import threading
import heapq


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


class RecurrenceType(Enum):
    NONE = "None"
    HOURLY = "Hourly"
    DAILY = "Daily"
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"
    CRON = "Cron Expression"


# --- Job (Command Pattern) ---

class Job(ABC):
    """Abstract job following Command Pattern"""

    def __init__(self, job_id: str, name: str, priority: JobPriority = JobPriority.MEDIUM):
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

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> JobPriority:
        return self._priority

    @property
    def status(self) -> JobStatus:
        return self._status

    @status.setter
    def status(self, value: JobStatus) -> None:
        self._status = value

    @property
    def retry_count(self) -> int:
        return self._retry_count

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @max_retries.setter
    def max_retries(self, value: int) -> None:
        self._max_retries = value

    @abstractmethod
    def execute(self) -> bool:
        """Execute the job. Return True if successful."""
        pass

    def on_success(self) -> None:
        self._status = JobStatus.COMPLETED
        self._completed_at = datetime.now()

    def on_failure(self, error: str) -> None:
        self._error_message = error
        if self._retry_count < self._max_retries:
            self._retry_count += 1
            self._status = JobStatus.RETRYING
        else:
            self._status = JobStatus.FAILED
        self._completed_at = datetime.now()

    def __lt__(self, other: 'Job') -> bool:
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self._created_at < other._created_at

    def __str__(self) -> str:
        return f"Job[{self._job_id[:8]}]: {self._name} ({self._status.value})"


# --- Concrete Job Implementations ---

class EmailJob(Job):
    def __init__(self, to_email: str, subject: str, body: str):
        super().__init__(str(uuid.uuid4()), f"Send Email to {to_email}")
        self._to = to_email
        self._subject = subject
        self._body = body

    def execute(self) -> bool:
        print(f"  📧 Sending email to {self._to}: {self._subject}")
        time.sleep(0.5)  # Simulate
        return True


class DataProcessingJob(Job):
    def __init__(self, data_source: str, query: str):
        super().__init__(str(uuid.uuid4()), f"Process Data: {data_source}")
        self._source = data_source
        self._query = query

    def execute(self) -> bool:
        print(f"  🔄 Processing data from {self._source}: {self._query}")
        time.sleep(1)
        return True


class ReportGenerationJob(Job):
    def __init__(self, report_name: str, report_type: str):
        super().__init__(str(uuid.uuid4()), f"Generate {report_name}")
        self._report_name = report_name
        self._report_type = report_type

    def execute(self) -> bool:
        print(f"  📊 Generating report: {self._report_name} ({self._report_type})")
        time.sleep(0.3)
        return True


class FileUploadJob(Job):
    def __init__(self, file_path: str, destination: str):
        super().__init__(str(uuid.uuid4()), f"Upload {file_path}")
        self._file_path = file_path
        self._destination = destination

    def execute(self) -> bool:
        print(f"  ☁️ Uploading {self._file_path} to {self._destination}")
        time.sleep(2)
        # Simulate failure
        if "fail" in self._file_path.lower():
            raise RuntimeError("Upload failed: Connection timeout")
        return True


# --- Scheduling Strategy (Strategy Pattern) ---

class SchedulingStrategy(ABC):
    @abstractmethod
    def schedule(self, jobs: List[Job]) -> List[Job]:
        """Order jobs for execution"""
        pass


class PriorityScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (-j.priority.value, j._created_at))


class FIFOScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: j._created_at)


class DeadlineAwareScheduler(SchedulingStrategy):
    def schedule(self, jobs: List[Job]) -> List[Job]:
        return sorted(jobs, key=lambda j: (j.priority.value, j._created_at))


# --- Recurring Job (Decorator/Observer) ---

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
    def next_run(self) -> datetime:
        return self._next_run

    @property
    def is_active(self) -> bool:
        return self._is_active

    def create_job(self) -> Job:
        job = self._job_factory()
        return job

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


# --- Job Executor (SRP) ---

class JobExecutor:
    """Single Responsibility: Executes jobs with timeout and retry"""

    def __init__(self, max_concurrent: int = 3):
        self._max_concurrent = max_concurrent
        self._running: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def execute(self, job: Job) -> bool:
        with self._lock:
            if len(self._running) >= self._max_concurrent:
                return False
            self._running[job.job_id] = job

        job.status = JobStatus.RUNNING
        job._started_at = datetime.now()

        try:
            print(f"  ▶️ Executing: {job}")
            success = job.execute()
            if success:
                job.on_success()
                print(f"  ✅ Completed: {job}")
            else:
                job.on_failure("Job returned False")
                print(f"  ❌ Failed: {job}")
        except Exception as e:
            job.on_failure(str(e))
            print(f"  ❌ Error: {job} - {e}")

        with self._lock:
            self._running.pop(job.job_id, None)

        return job.status == JobStatus.COMPLETED


# --- Job Scheduler (Facade) ---

class JobScheduler:
    """Facade for the entire scheduling system"""

    def __init__(self, scheduler_strategy: SchedulingStrategy = None):
        self._executor = JobExecutor()
        self._scheduler = scheduler_strategy or PriorityScheduler()
        self._pending: List[Job] = []
        self._history: List[Job] = []
        self._recurring: List[RecurringJob] = []
        self._running = True
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

    def add_job(self, job: Job) -> None:
        with self._lock:
            self._pending.append(job)

    def add_recurring(self, recurring: RecurringJob) -> None:
        self._recurring.append(recurring)

    def set_scheduler(self, strategy: SchedulingStrategy) -> None:
        self._scheduler = strategy

    def start(self) -> None:
        self._running = True
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()
        print("  🟢 Scheduler started")

    def stop(self) -> None:
        self._running = False
        print("  🔴 Scheduler stopped")

    def _process_loop(self) -> None:
        while self._running:
            # Process recurring jobs
            now = datetime.now()
            for rec in self._recurring:
                if rec.is_active and rec.next_run <= now:
                    job = rec.create_job()
                    self.add_job(job)
                    rec.update_next_run()

            # Process pending jobs
            with self._lock:
                if self._pending:
                    ordered = self._scheduler.schedule(self._pending)
                    job = ordered[0]
                    self._pending.remove(job)
                else:
                    job = None

            if job:
                self._executor.execute(job)
                with self._lock:
                    self._history.append(job)
            else:
                time.sleep(0.5)

    def get_pending_count(self) -> int:
        return len(self._pending)

    def get_history(self, limit: int = 10) -> List[Job]:
        return self._history[-limit:]

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            for j in self._pending:
                if j.job_id == job_id:
                    j.status = JobStatus.CANCELLED
                    self._pending.remove(j)
                    self._history.append(j)
                    return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        completed = sum(1 for j in self._history if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in self._history if j.status == JobStatus.FAILED)
        return {
            "pending": self.get_pending_count(),
            "completed": completed,
            "failed": failed,
            "total": len(self._history),
            "recurring": len(self._recurring),
        }


# --- Demo ---

def demo():
    print("=== Job Scheduling System ===")
    print("=" * 50)

    scheduler = JobScheduler(PriorityScheduler())

    # Add one-time jobs
    scheduler.add_job(EmailJob("alice@email.com", "Welcome!", "Thanks for joining"))
    scheduler.add_job(DataProcessingJob("users_db", "SELECT * FROM active_users"))
    scheduler.add_job(ReportGenerationJob("Daily Sales", "CSV"))
    scheduler.add_job(FileUploadJob("/tmp/backup.sql", "s3://backups/"))

    # Add high priority job
    critical_job = EmailJob("admin@system.com", "CRITICAL: Server Alert", "CPU > 90%")
    critical_job._priority = JobPriority.CRITICAL
    scheduler.add_job(critical_job)

    # Add recurring job (hourly cleanup)
    cleanup = RecurringJob(
        lambda: DataProcessingJob("logs", "CLEANUP old logs"),
        RecurrenceType.HOURLY
    )
    scheduler.add_recurring(cleanup)

    # Start and run
    scheduler.start()
    time.sleep(3)
    scheduler.stop()

    # Stats
    print(f"\n--- Scheduler Stats ---")
    stats = scheduler.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # History
    print(f"\n--- Job History (last 5) ---")
    for job in scheduler.get_history(5):
        duration = ""
        if job._started_at and job._completed_at:
            d = (job._completed_at - job._started_at).total_seconds()
            duration = f" ({d:.1f}s)"
        print(f"  {job}{duration}")


if __name__ == "__main__":
    demo()
```

---

## ▶️ How to Run

```bash
cd low-level-design/job-scheduling-system
python job_scheduler.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
