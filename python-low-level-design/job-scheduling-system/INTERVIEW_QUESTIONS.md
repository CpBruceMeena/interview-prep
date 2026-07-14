# Job Scheduling System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Distributed systems, scheduling algorithms, failure handling, cron

---

## Question 1: Core Design
**Interviewer:** *"Design a job scheduling system — one-time, recurring, and priority-based execution."*

### 🎯 Expected Answer

**Command Pattern for Jobs:**
```python
class Job(ABC):
    @abstractmethod
    def execute(self) -> bool: pass
    
    def on_success(self): self._status = JobStatus.COMPLETED
    def on_failure(self, error): 
        self._retry_count += 1
        if self._retry_count < self._max_retries:
            self._status = JobStatus.RETRYING  # Re-enqueue
        else:
            self._status = JobStatus.FAILED  # To DLQ

class EmailJob(Job):
    def execute(self):
        return send_email(self._to, self._subject, self._body)

class DataProcessingJob(Job):
    def execute(self):
        return process_query(self._source, self._query)
```

**Why Command Pattern?** Each job encapsulates both the action and its metadata (retries, timeout, priority). The scheduler doesn't know what the job does — it just calls `execute()`. This is **Dependency Inversion** — scheduler depends on `Job` abstraction, not concrete implementations.

**Priority Queue for scheduling:**
```python
import heapq

class JobScheduler:
    def __init__(self):
        self._queue = []  # Min-heap: (-priority, created_at, job)
    
    def add_job(self, job):
        heapq.heappush(self._queue, (-job.priority.value, job._created_at, job))
    
    def get_next(self):
        _, _, job = heapq.heappop(self._queue)
        return job
```

---

## Question 2: Scheduling Algorithms
**Interviewer:** *"Compare scheduling algorithms."*

| Algorithm | Behavior | Starvation | Best For |
|-----------|----------|------------|----------|
| **FIFO** | First come, first served | No | Simple, non-critical |
| **Priority Queue** | Higher priority first | Yes (low priority) | Mixed workloads |
| **Round Robin** | Fair time slices | No | CPU-bound tasks |
| **EDF** | Earliest deadline first | No (with admission control) | Time-sensitive jobs |
| **Weighted Fair** | Proportional allocation | No | Multi-tenant systems |

**Starvation prevention:** Implement aging — increase priority of waiting jobs over time:
```python
def get_next_with_aging(self):
    for i, (neg_priority, created, job) in enumerate(self._queue):
        wait_time = (datetime.now() - created).total_seconds()
        # Boost priority by 1 per minute of waiting
        aging_boost = wait_time / 60
        effective_priority = -neg_priority + aging_boost
        self._queue[i] = (effective_priority, created, job)
    heapq.heapify(self._queue)
    return heapq.heappop(self._queue)
```

---

## Question 3: Distributed Job Scheduler
**Interviewer:** *"Scale this across worker nodes."*

### 🎯 Architecture
```
                     ┌──────────────┐
Job Producer ───────▶│  Redis Queue  │◀─────────── Cron Trigger
                     │  (Sorted Set) │
                     └──────┬───────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                  │
    ┌─────▼─────┐    ┌─────▼─────┐    ┌──────▼─────┐
    │ Worker 1  │    │ Worker 2  │    │  Worker N  │
    │ (poll+work)│    │ (poll+work)│    │ (poll+work)│
    └───────────┘    └───────────┘    └────────────┘
```

**Worker lease mechanism:**
```python
def poll_and_work(worker_id):
    while True:
        # Atomically dequeue with lease (prevent double-processing)
        job_data = redis.brpoplpush("job:queue", f"job:inprogress:{worker_id}", timeout=30)
        if job_data:
            job = deserialize(job_data)
            try:
                success = job.execute(timeout=job.timeout)
                if success:
                    redis.lrem(f"job:inprogress:{worker_id}", 0, job_data)
                    redis.lpush("job:completed", job_data)
                else:
                    redis.lrem(f"job:inprogress:{worker_id}", 0, job_data)
                    if job.retry_count < job.max_retries:
                        redis.lpush("job:queue", job_data)  # Re-enqueue
                    else:
                        redis.lpush("job:dead_letter", job_data)
            except Exception:
                # Lease TTL handles recovery — another worker picks up after TTL
                pass
```

**Heartbeat monitoring:** Workers send heartbeats every 5 seconds. If no heartbeat for 30 seconds, reassign their in-progress jobs to other workers.

---

## Question 4: Cron / Recurring Jobs

**Schedule representation:**
```python
class CronExpression:
    def __init__(self, minute="*", hour="*", day="*", month="*", day_of_week="*"):
        self._minute = self._parse_field(minute, 0, 59)
        self._hour = self._parse_field(hour, 0, 23)
        self._day = self._parse_field(day, 1, 31)
        self._month = self._parse_field(month, 1, 12)
        self._day_of_week = self._parse_field(day_of_week, 0, 6)
    
    def next_run(self, from_time=None):
        """Find the next datetime matching this cron expression"""
        # Algorithm: increment from 'from_time' until all fields match
        ...
```

**Daylight saving time:** Run at the specified wall-clock time after the DST change. If ambiguous (fall-back), run once. If skipped (spring-forward), skip that instance.

---

## Question 5: Failure & Retry Handling

**Exponential backoff:**
```python
def retry_delay(attempt: int, base_delay: float = 1.0) -> float:
    return min(base_delay * (2 ** attempt), 3600)  # Cap at 1 hour
```

**Circuit breaker pattern:** If a job type fails >5 times consecutively, stop scheduling it. Manual intervention required to reset.

**Dead letter queue:** After max_retries, move to DLQ for manual inspection. DLQ alert triggers pager duty.

---

## Question 6: Monitoring

**Key metrics to track:**
| Metric | What It Tells You |
|--------|------------------|
| Queue depth | How backlogged we are |
| p50/p95/p99 latency | How fast jobs execute |
| Success rate | System health |
| Worker utilization | Capacity planning |
| Throughput | Business activity |

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Command** | Job classes | Encapsulate action + metadata |
| **Strategy** | Scheduling algorithms | FIFO, Priority, EDF |
| **Observer** | Job lifecycle events | Log, alert, notify |
| **Decorator** | RecurringJob | Wrap one-time job with cron |
| **Facade** | JobScheduler | Unified interface |
| **Template Method** | Job execution | Consistent flow with hooks |
| **Producer-Consumer** | Queue architecture | Decouple creation from execution |
