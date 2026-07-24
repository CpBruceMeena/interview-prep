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

## 🚀 Running the Demo

```bash
cd python-low-level-design/job-scheduling-system
python job_scheduler.py
```

The demo:
1. Shows race condition (unsafe vs safe counter)
2. Schedules 8 jobs across all 3 concurrency models
3. Executes via async workers with semaphore limiting
4. Reports stats and execution history
