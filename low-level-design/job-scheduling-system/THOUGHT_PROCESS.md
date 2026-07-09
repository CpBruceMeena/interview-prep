# 🧠 Job Scheduling System LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](job-scheduling-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What types of jobs? (Email, data processing, file upload?) Priority system? Recurring jobs? Retry policy? Concurrency limits?

## Phase 1: Identify the Nouns

> *"Jobs are submitted to a scheduler, prioritized, and executed. Failed jobs are retried. Recurring jobs run on a schedule."*

| Noun | Decision | Why |
|------|----------|-----|
| Job | ABC | Command Pattern — each job type has logic + metadata |
| RecurringJob | Regular | Wraps a job factory with interval |
| JobExecutor | Regular | Runs jobs with concurrency limit |
| SchedulingStrategy | ABC | Strategy for ordering jobs |
| JobScheduler | Facade | Main entry point |
| JobStatus | Enum | PENDING, RUNNING, COMPLETED, FAILED, etc. |
| JobPriority | Enum | LOW, MEDIUM, HIGH, CRITICAL |
| RecurrenceType | Enum | NONE, HOURLY, DAILY, WEEKLY, CRON |

## Phase 2: Enums First

```python
class JobPriority(Enum):     LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3
class JobStatus(Enum):       PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, RETRYING
class RecurrenceType(Enum):  NONE, HOURLY, DAILY, WEEKLY, MONTHLY, CRON
```

Note the integer values on `JobPriority` — enables `<` comparison for priority sorting.

## Phase 3: dataclass vs `__init__`

- **`Job`**: ABC — abstract, subclasses implement `execute()`
- **Concrete jobs** (`EmailJob`, `DataProcessingJob`): Regular — each has specific `execute()` logic
- **`RecurringJob`**: Regular — wraps a factory function
- **`JobExecutor`**: Regular — manages running jobs with thread pool
- **`JobScheduler`**: Regular — orchestrates everything with threading

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Define job logic | Concrete Job classes | Each job knows what to do |
| Sort jobs | `SchedulingStrategy.schedule()` | Strategy for ordering |
| Run job | `JobExecutor.execute()` | Manages concurrency |
| Handle success/failure | `Job.on_success()`/`on_failure()` | Job owns its lifecycle callbacks |
| Create recurring instances | `RecurringJob.create_job()` | RecurringJob wraps the factory |
| Process loop | `JobScheduler._process_loop()` | Orchestrates the whole system |

## Phase 5: Command Pattern

Each `Job` is a command — it encapsulates an action:

```python
class Job(ABC):
    def execute(self) -> bool  # The action
    def on_success(self)       # Post-action callback
    def on_failure(self, error)  # Error callback
```

This allows the scheduler to treat all jobs uniformly — it just calls `execute()`.

## Phase 6: Strategy Pattern for Scheduling

```python
class SchedulingStrategy(ABC):
    def schedule(self, jobs: List[Job]) -> List[Job]

class PriorityScheduler(SchedulingStrategy):  # Highest priority first
class FIFOScheduler(SchedulingStrategy):       # First in, first out
```

The scheduler delegates ordering to the strategy.

## Phase 7: Threading Model

The `JobScheduler` runs a background thread (`_process_loop`) that continuously processes jobs. The `JobExecutor` limits concurrent executions.

## Phase 8: Quick Checklist

✅ **Command Pattern:** Each job encapsulates its action
✅ **Strategy:** Scheduling algorithms are swappable
✅ **SRP:** JobExecutor runs, SchedulingStrategy orders, Jobs define logic
✅ **OCP:** New job type → new Job subclass, no scheduler changes
