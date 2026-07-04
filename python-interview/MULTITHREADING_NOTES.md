# 🐍 Python Multithreading & Concurrency — Practical Notes

> **A hands-on guide to writing concurrent Python code: threading, GIL, multiprocessing, asyncio, and production patterns**
> *From basics to staff-level depth*

---

## Table of Contents

1. [Concurrency Landscape in Python](#1-concurrency-landscape-in-python)
2. [The GIL — Global Interpreter Lock](#2-the-gil-global-interpreter-lock)
3. [Threading Module](#3-threading-module)
4. [Thread Synchronization](#4-thread-synchronization)
5. [Thread-Safe Queues & Communication](#5-thread-safe-queues-communication)
6. [concurrent.futures — High-Level API](#6-concurrentfutures-high-level-api)
7. [Multiprocessing — True Parallelism](#7-multiprocessing-true-parallelism)
8. [AsyncIO — Event Loop Concurrency](#8-asyncio-event-loop-concurrency)
9. [Choosing the Right Approach](#9-choosing-the-right-approach)
10. [Thread Safety Patterns](#10-thread-safety-patterns)
11. [Debugging Concurrency Issues](#11-debugging-concurrency-issues)
12. [Concurrency & Parallelism Interview Questions](#12-concurrency-parallelism-interview-questions)

---

## 1. Concurrency Landscape in Python

### Three Models

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Python Concurrency Models                         │
├─────────────────┬─────────────────┬─────────────────────────────────┤
│   threading      │  multiprocessing │      asyncio                    │
│ (thread-based)   │ (process-based)  │ (event loop based)             │
├─────────────────┼─────────────────┼─────────────────────────────────┤
│ GIL-limited     │ True parallelism │ Single-thread cooperative       │
│ Best for I/O    │ Best for CPU     │ Best for I/O with many conns    │
│ Shared memory   │ Separate memory  │ Shared state (single thread)    │
│ ~1MB/thread     │ ~50MB/process    │ ~2KB/task (coroutine)           │
│ ~1000 threads   │ ~100 processes   │ ~100K+ tasks per process        │
└─────────────────┴─────────────────┴─────────────────────────────────┘
```

### Decision Matrix

| Workload | threading | multiprocessing | asyncio |
|----------|-----------|-----------------|---------|
| CPU-bound (compute) | ❌ GIL serializes | ✅ True parallelism | ❌ Single thread |
| I/O-bound (network) | ✅ GIL releases | ⚠️ Overkill | ✅ Best option |
| I/O-bound (file) | ✅ Works well | ⚠️ Overkill | ✅ Works well |
| Mixed CPU/I/O | ⚠️ Partial | ✅ Best | ⚠️ Partial |
| Low latency required | ⚠️ GIL adds jitter | ❌ IPC overhead | ✅ Best |
| Memory sharing needed | ✅ Easy | ⚠️ IPC needed | ✅ Single thread |

### Key Terminology

```python
# ── Concurrency ──────────────────────────────────────────
# "Dealing with many things at once" (structuring)
# Python: threading and asyncio are concurrent models

# ── Parallelism ──────────────────────────────────────────
# "Doing many things at once" (execution)
# Python: multiprocessing gives true parallelism
# threading is NOT parallel (GIL limits CPU work)

# ── Multithreading ──────────────────────────────────────
# Multiple threads sharing the same memory space
# Python: threads are real OS threads (N:M mapping via OS)
# But: GIL prevents parallel CPython bytecode execution

# ── Multiprocessing ─────────────────────────────────────
# Multiple processes with separate memory spaces
# Python: true parallel execution across CPU cores
# Cost: IPC overhead, memory duplication (unless shared)
```

---

## 2. The GIL — Global Interpreter Lock

### What the GIL Actually Is

```python
# The GIL is a mutex that prevents multiple native threads from
# executing Python bytecodes simultaneously in the same process.
#
# It protects CPython's internal state:
#   - Reference counts (garbage collection)
#   - Object allocation (arena allocator)
#   - Internal data structures (dict, list, etc.)
#
# Without the GIL, every operation on PyObject would need
# fine-grained locking — massive overhead for single-threaded code.

# ═══════════════════════════════════════════════════════════
# GIL switching mechanism (Python 3.2+, PEP 1043)
# ═══════════════════════════════════════════════════════════
#
# The GIL uses a condition variable with a 5ms timeout.
# Every 5ms, the holding thread:
#   1. Releases the GIL
#   2. Signals waiting threads
#   3. Re-acquires the GIL (fair competition)
#
# This replaced the old bytecode-count-based switching
# which was unfair to CPU-bound threads.
#
# You can adjust: sys.setswitchinterval(0.001)  # 1ms
```

### GIL Impact Analysis

```python
import sys
import time
import threading

def cpu_intensive(n: int) -> int:
    """CPU-bound work — GIL serializes this"""
    result = 0
    for i in range(n):
        result += i ** 2
    return result

def io_simulation(n: int) -> None:
    """I/O-bound work — GIL releases during sleep/I/O"""
    for _ in range(n):
        time.sleep(0.001)  # GIL released during sleep!

# ── CPU-bound test ───────────────────────────────────────
def test_cpu():
    start = time.perf_counter()
    threads = [
        threading.Thread(target=cpu_intensive, args=(5_000_000,))
        for _ in range(4)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"CPU-bound with 4 threads: {time.perf_counter() - start:.2f}s")
    # ~SAME as sequential! GIL prevents parallel execution.

# ── I/O-bound test ───────────────────────────────────────
def test_io():
    start = time.perf_counter()
    threads = [
        threading.Thread(target=io_simulation, args=(1000,))
        for _ in range(4)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"I/O-bound with 4 threads: {time.perf_counter() - start:.2f}s")
    # ~4x faster than sequential! GIL releases during I/O.
```

### Working Around the GIL

```python
# ── Strategy 1: Multiprocessing ──────────────────────────
# True parallelism via separate processes
from multiprocessing import Pool

def cpu_bound_task(data: list) -> list:
    return [expensive_func(x) for x in data]

with Pool(processes=4) as pool:
    results = pool.map(cpu_bound_task, chunks)

# ── Strategy 2: C Extensions (release GIL) ──────────────
# C extensions can release the GIL during heavy computation
# Cython: with nogil: block
# C: Py_BEGIN_ALLOW_THREADS / Py_END_ALLOW_THREADS
# numpy releases GIL during array operations!
import numpy as np
# np.dot(A, B)  ← GIL released during computation

# ── Strategy 3: Subinterpreters (Python 3.12+) ──────────
# Each subinterpreter has its own GIL!
import _xxsubinterpreters as interpreters

interp_id = interpreters.create()
interpreters.run_string(interp_id, """
def compute():
    return sum(i ** 2 for i in range(10_000_000))
result = compute()
""")
# True parallelism with independent GILs

# ── Strategy 4: Free-Threaded Python (3.13t) ────────────
# PYTHON_GIL=0 python my_script.py
# The GIL is completely disabled!
# BUT: all mutable objects become thread-unsafe
# Current: ~5-8% single-threaded performance cost
```

---

## 3. Threading Module

### Creating and Managing Threads

```python
import threading
import time
from typing import Callable, Any

# ── Basic thread creation ────────────────────────────────
def worker(name: str, delay: float) -> None:
    print(f"Thread {name} starting")
    time.sleep(delay)
    print(f"Thread {name} finished")

t = threading.Thread(target=worker, args=("A", 1.0))
t.start()
t.join()  # Wait for thread to finish
print("Main thread continues")

# ── Thread with return values ────────────────────────────
class ResultThread(threading.Thread):
    def __init__(self, target: Callable, args: tuple = ()):
        super().__init__()
        self._target_fn = target
        self._args = args
        self._result = None
        self._exception = None
    
    def run(self):
        try:
            self._result = self._target_fn(*self._args)
        except Exception as e:
            self._exception = e
    
    def result(self, timeout: float = None) -> Any:
        self.join(timeout)
        if self._exception:
            raise self._exception
        return self._result

def expensive_compute(n: int) -> int:
    return sum(i ** 2 for i in range(n))

thread = ResultThread(target=expensive_compute, args=(10_000_000,))
thread.start()
result = thread.result(timeout=5.0)
print(f"Result: {result}")

# ── Daemon threads ────────────────────────────────────────
# Daemon threads die when the main thread exits
# Use: background tasks, monitoring, health checks
def background_monitor():
    while True:
        print("Monitoring...")
        time.sleep(1)

monitor = threading.Thread(target=background_monitor, daemon=True)
monitor.start()
# Main thread exits → daemon thread is killed
```

### Thread Lifecycle

```
┌──────────┐   .start()   ┌──────────┐   acquires    ┌──────────┐
│   New    │─────────────→│ Runnable │──────────────→│ Running  │
└──────────┘              └──────────┘               └──────────┘
                                                          │
                                                    ┌─────┴──────┐
                                                    │            │
                                                    ↓            ↓
                                               ┌────────┐  ┌─────────┐
                                               │Waiting │  │ Blocked │
                                               │ (sleep)│  │ (I/O)   │
                                               └────────┘  └─────────┘
                                                    ↑            ↑
                                                    │            │
                                                    └─────┬──────┘
                                                          │
                                                     ┌────────┐
                                                     │Running │
                                                     └────────┘
                                                          │
                                                     ┌────────┐
                                                     │  Dead  │
                                                     └────────┘
```

### Thread Identification & Utilities

```python
# ── Current thread info ──────────────────────────────────
current = threading.current_thread()
print(f"Name: {current.name}")
print(f"Ident: {current.ident}")
print(f"Daemon: {current.daemon}")
print(f"Alive: {current.is_alive()}")

# ── Enumerate all threads ────────────────────────────────
for thread in threading.enumerate():
    print(f"Thread: {thread.name} (alive={thread.is_alive()})")

# ── Thread count ─────────────────────────────────────────
print(f"Active threads: {threading.active_count()}")

# ── Thread-local data ────────────────────────────────────
# Data isolated per thread (no race conditions)
thread_local = threading.local()

def setup_thread():
    thread_local.user_id = threading.current_thread().ident
    thread_local.transaction_id = str(uuid4())

def get_context():
    return {
        'user_id': getattr(thread_local, 'user_id', None),
        'transaction_id': getattr(thread_local, 'transaction_id', None),
    }
```

### Thread Pools (Manual)

```python
from queue import Queue
from typing import Callable

class ThreadPool:
    """Simple thread pool with configurable worker count"""
    
    def __init__(self, num_workers: int = 4):
        self.tasks = Queue()
        self.results = Queue()
        self.workers = []
        self._stop_event = threading.Event()
        
        for _ in range(num_workers):
            worker = threading.Thread(target=self._worker_loop)
            worker.daemon = True
            worker.start()
            self.workers.append(worker)
    
    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                task_id, func, args, kwargs = self.tasks.get(timeout=0.1)
                try:
                    result = func(*args, **kwargs)
                    self.results.put((task_id, result, None))
                except Exception as e:
                    self.results.put((task_id, None, e))
            except Exception:
                pass  # Queue.Empty timeout
    
    def submit(self, func: Callable, *args, **kwargs) -> int:
        task_id = id(func)
        self.tasks.put((task_id, func, args, kwargs))
        return task_id
    
    def get_result(self, timeout: float = None):
        """Get next completed result"""
        return self.results.get(timeout=timeout)
    
    def shutdown(self):
        self._stop_event.set()
        for worker in self.workers:
            worker.join(timeout=1.0)
```

---

## 4. Thread Synchronization

### Lock (Mutex)

```python
import threading

# ── Basic lock ────────────────────────────────────────────
counter = 0
counter_lock = threading.Lock()

def increment():
    global counter
    for _ in range(100000):
        with counter_lock:  # Context manager — always releases
            counter += 1

# ── Non-blocking acquire ──────────────────────────────────
def try_acquire():
    if counter_lock.acquire(blocking=False):  # Don't block
        try:
            # Critical section
            pass
        finally:
            counter_lock.release()
    else:
        print("Lock not available, doing something else")

# ── Lock with timeout ─────────────────────────────────────
def acquire_with_timeout(lock: threading.Lock, timeout: float):
    acquired = lock.acquire(timeout=timeout)
    if acquired:
        try:
            # Critical section
            pass
        finally:
            lock.release()
    else:
        raise TimeoutError("Could not acquire lock")
```

### RLock (Reentrant Lock)

```python
# ── RLock: same thread can acquire multiple times ─────────
# Without RLock, this would deadlock:
class Counter:
    def __init__(self):
        self.lock = threading.RLock()  # NOT threading.Lock!
        self.value = 0
    
    def increment(self):
        with self.lock:
            self.value += 1
    
    def increment_by(self, n):
        with self.lock:
            for _ in range(n):
                self.increment()  # Same thread re-acquires lock
    
    def get_and_increment(self):
        with self.lock:
            val = self.value
            self.increment()
            return val

# ⚠️ RLock vs Lock:
# Lock: one acquisition per thread. If same thread tries again → deadlock
# RLock: same thread can acquire N times (reentrant), must release N times
# Use RLock when a method with a lock calls another method with the same lock
```

### Semaphore

```python
# ── Semaphore: limit concurrent access to N threads ───────
# Semaphore(n) allows n threads to enter
# BoundedSemaphore can't exceed initial value

import threading
import time

pool_semaphore = threading.Semaphore(3)  # Max 3 concurrent connections

def database_query(query: str):
    with pool_semaphore:
        print(f"Running: {query}")
        time.sleep(1)  # Simulate DB query
        return f"Result of {query}"

# ── Practical: rate-limited API client ─────────────────────
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.semaphore = threading.Semaphore(max_calls)
        self.period = period
        self._start_time = time.monotonic()
    
    def acquire(self):
        self.semaphore.acquire()
        # Start refill timer
        threading.Timer(self.period, self._refill).start()
    
    def _refill(self):
        try:
            self.semaphore.release()
        except ValueError:
            pass  # Already at max

# Usage:
# limiter = RateLimiter(10, 1.0)  # 10 calls per second
# limiter.acquire()
# make_api_call()
```

### Event

```python
# ── Event: signal between threads ─────────────────────────
# One thread sets the event, others wait for it

start_event = threading.Event()
data_ready = threading.Event()
shutdown_event = threading.Event()

def worker_thread(worker_id: int):
    print(f"Worker {worker_id} waiting for start signal")
    start_event.wait()  # Block until set
    print(f"Worker {worker_id} started!")
    
    while not shutdown_event.is_set():
        data_ready.wait(timeout=1.0)
        if data_ready.is_set():
            print(f"Worker {worker_id} processing data")
            data_ready.clear()
    
    print(f"Worker {worker_id} shutting down")

# Signal all workers to start
start_event.set()

# Signal data available
data_ready.set()

# Shutdown all workers
shutdown_event.set()

# ── Event vs Condition ────────────────────────────────────
# Event: simple on/off signaling (pulse)
# Condition: complex state-dependent waiting (data availability)
```

### Condition

```python
# ── Condition: wait for complex state changes ─────────────
import threading
import time

class BoundedBuffer:
    """Producer-consumer with Condition variables"""
    
    def __init__(self, maxsize: int = 10):
        self.buffer = []
        self.maxsize = maxsize
        self.cond = threading.Condition()  # Has its own Lock
    
    def put(self, item):
        with self.cond:
            while len(self.buffer) >= self.maxsize:
                # Wait until space is available
                # Releases the lock, re-acquires before return
                self.cond.wait()
            
            self.buffer.append(item)
            # Notify one waiting consumer
            self.cond.notify()
    
    def get(self):
        with self.cond:
            while len(self.buffer) == 0:
                self.cond.wait()  # Wait until data available
            
            item = self.buffer.pop(0)
            # Notify one waiting producer
            self.cond.notify()
            return item
    
    def put_many(self, items):
        with self.cond:
            for item in items:
                while len(self.buffer) >= self.maxsize:
                    self.cond.wait()
                self.buffer.append(item)
            # Notify ALL waiting consumers
            self.cond.notify_all()

# ── Condition vs Event ─────────────────────────────────────
# Condition: use when threads wait for a specific state
#            (e.g., buffer not empty, queue size < max)
# Event: use for simple one-shot signaling
#         (e.g., start, shutdown, initialization complete)
```

### Barrier

```python
# ── Barrier: synchronize N threads at a point ─────────────
# All N threads must reach the barrier before any can proceed

import threading

barrier = threading.Barrier(3)  # 3 threads must sync

def parallel_phase(worker_id: int, phase_name: str):
    print(f"Worker {worker_id} starting phase {phase_name}")
    time.sleep(worker_id * 0.5)  # Simulate variable work
    print(f"Worker {worker_id} waiting at barrier for {phase_name}")
    barrier.wait()  # Blocks until all 3 threads arrive
    print(f"Worker {worker_id} passed barrier for {phase_name}")
    # All threads proceed together

# ── Barrier with timeout ──────────────────────────────────
try:
    barrier.wait(timeout=5.0)
except threading.BrokenBarrierError:
    print("Barrier broken — one thread timed out or failed")

# ── Barrier with callback ─────────────────────────────────
barrier = threading.Barrier(3, action=lambda: print("All threads synced!"))
```

---

## 5. Thread-Safe Queues & Communication

### queue.Queue

```python
import queue
import threading

# ── Queue — thread-safe FIFO ───────────────────────────────
task_queue = queue.Queue(maxsize=100)

def producer():
    for i in range(50):
        task_queue.put(f"Task-{i}")  # Blocks if full
        print(f"Produced Task-{i}")
    task_queue.put(None)  # Sentinel: signals end

def consumer():
    while True:
        task = task_queue.get()  # Blocks if empty
        if task is None:
            task_queue.task_done()
            break  # Sentinel received
        print(f"Consumed {task}")
        task_queue.task_done()  # Signal task completion

producer_thread = threading.Thread(target=producer)
consumer_thread = threading.Thread(target=consumer)

producer_thread.start()
consumer_thread.start()

# Wait until all tasks are processed
task_queue.join()  # Blocks until every put has a corresponding task_done
print("All tasks completed")

# ── Queue variants ─────────────────────────────────────────
q = queue.Queue(maxsize=100)      # FIFO (default)
q = queue.LifoQueue(maxsize=100)  # LIFO (stack)
q = queue.PriorityQueue(maxsize=100)  # Priority (min-heap)

# ── Non-blocking operations ────────────────────────────────
try:
    item = task_queue.get(block=False)
except queue.Empty:
    print("Queue empty, doing other work")

try:
    task_queue.put(item, block=False)
except queue.Full:
    print("Queue full, discarding item")

# ── Queue with timeout ─────────────────────────────────────
try:
    item = task_queue.get(timeout=5.0)
except queue.Empty:
    print("No item after 5 seconds")
```

### Pipe (multiprocessing)

```python
# ── Pipe for two-way communication ─────────────────────────
# Simplex/duplex channels between processes/threads
from multiprocessing import Pipe

parent_conn, child_conn = Pipe()

def worker(conn):
    conn.send("Hello from worker")
    data = conn.recv()  # Receive from main
    conn.close()

t = threading.Thread(target=worker, args=(child_conn,))
t.start()

msg = parent_conn.recv()  # Receive from worker
print(f"Got: {msg}")
parent_conn.send("Hello from main")
t.join()
```

### Producer-Consumer Patterns

```python
# ── Multi-producer, single consumer ────────────────────────
class Pipeline:
    def __init__(self, maxsize: int = 100):
        self.queue = queue.Queue(maxsize)
        self._stop_event = threading.Event()
    
    def producer(self, producer_id: int, data: list):
        for item in data:
            if self._stop_event.is_set():
                break
            self.queue.put((producer_id, item))
        # Signal completion
        self.queue.put((producer_id, None))
    
    def consumer(self):
        active_producers = set()
        
        while True:
            producer_id, item = self.queue.get()
            
            if item is None:
                active_producers.discard(producer_id)
                if not active_producers:
                    break
                continue
            
            active_producers.add(producer_id)
            self.process(item)
            self.queue.task_done()
    
    def process(self, item):
        # Process individual item
        pass
    
    def stop(self):
        self._stop_event.set()

# ── Fan-out: one producer, multiple consumers ──────────────
class FanOut:
    def __init__(self, num_consumers: int = 4):
        self.queues = [queue.Queue() for _ in range(num_consumers)]
        self.consumers = []
        self._counter = 0  # For round-robin
    
    def add_consumer(self, worker):
        idx = len(self.consumers)
        t = threading.Thread(target=worker, args=(self.queues[idx],))
        t.daemon = True
        t.start()
        self.consumers.append(t)
    
    def publish(self, item):
        # Round-robin distribution
        q = self.queues[self._counter % len(self.queues)]
        self._counter += 1
        q.put(item)
    
    def broadcast(self, item):
        # Send to ALL consumers
        for q in self.queues:
            q.put(item)
```

---

## 6. concurrent.futures — High-Level API

### ThreadPoolExecutor

```python
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
import urllib.request

# ── Basic usage ────────────────────────────────────────────
def fetch_url(url: str) -> tuple[str, str]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return url, response.read().decode()[:100]

urls = [
    "https://python.org",
    "https://github.com",
    "https://stackoverflow.com",
]

# Context manager — automatically shuts down pool
with ThreadPoolExecutor(max_workers=4) as executor:
    # Submit individual tasks
    futures = {executor.submit(fetch_url, url): url for url in urls}
    
    # Process as they complete
    for future in as_completed(futures):
        url = futures[future]
        try:
            _, content = future.result(timeout=10)
            print(f"{url}: {len(content)} chars")
        except Exception as e:
            print(f"{url} failed: {e}")

# ── map() — simple mapping ────────────────────────────────
with ThreadPoolExecutor(max_workers=4) as executor:
    results = executor.map(fetch_url, urls, timeout=10)
    for url, content in results:
        print(f"{url}: OK")
```

### ProcessPoolExecutor

```python
from concurrent.futures import ProcessPoolExecutor
import math

# ── CPU-bound work: processes give true parallelism ───────
def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            return False
    return True

def find_primes(limit: int) -> list[int]:
    return [n for n in range(limit) if is_prime(n)]

# ProcessPoolExecutor uses multiprocessing under the hood
with ProcessPoolExecutor(max_workers=4) as executor:
    # Chunk the work
    chunks = [range(i, i + 25000) for i in range(0, 100000, 25000)]
    futures = [executor.submit(find_primes, chunk) for chunk in chunks]
    
    results = []
    for future in as_completed(futures):
        results.extend(future.result())

# ── Thread vs Process ──────────────────────────────────────
# ThreadPoolExecutor:  GIL-bound, good for I/O
# ProcessPoolExecutor: True parallel, good for CPU
# ProcessPoolExecutor: Arguments must be picklable!
```

### Custom Executor Patterns

```python
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import time

# ── Rate-limited executor ──────────────────────────────────
class RateLimitedExecutor:
    def __init__(self, max_workers: int, calls_per_second: float):
        self.executor = ThreadPoolExecutor(max_workers)
        self.semaphore = threading.Semaphore(int(calls_per_second))
        self._last_reset = time.monotonic()
        self._lock = threading.Lock()
    
    def submit(self, fn, *args, **kwargs) -> Future:
        self._throttle()
        return self.executor.submit(fn, *args, **kwargs)
    
    def _throttle(self):
        with self._lock:
            now = time.monotonic()
            if now - self._last_reset >= 0.1:  # Reset every 100ms
                self._last_reset = now
                # Don't actually release — too complex for example
                pass
        self.semaphore.acquire()

# ── Progress tracking executor ─────────────────────────────
class ProgressExecutor:
    def __init__(self, max_workers: int, total: int):
        self.executor = ThreadPoolExecutor(max_workers)
        self.completed = 0
        self.total = total
        self.lock = threading.Lock()
    
    def submit(self, fn, *args, **kwargs) -> Future:
        future = self.executor.submit(fn, *args, **kwargs)
        future.add_done_callback(self._on_complete)
        return future
    
    def _on_complete(self, future):
        with self.lock:
            self.completed += 1
        print(f"Progress: {self.completed}/{self.total} ({self.completed*100//self.total}%)")

# Usage:
# executor = ProgressExecutor(4, len(urls))
# for url in urls:
#     executor.submit(fetch_url, url)
```

---

## 7. Multiprocessing — True Parallelism

### Process Basics

```python
import multiprocessing as mp
import os
import time

# ── Process creation ───────────────────────────────────────
def worker(name: str):
    print(f"Worker {name} (PID: {os.getpid()}) running")
    time.sleep(1)
    return f"Result from {name}"

# Process has its own memory space, GIL, and Python interpreter
p = mp.Process(target=worker, args=("A",))
p.start()
p.join()  # Wait for process to complete

# ── Process with return value (via Queue) ─────────────────
def worker_with_result(q: mp.Queue, name: str):
    result = expensive_computation(name)
    q.put(result)

result_queue = mp.Queue()
p = mp.Process(target=worker_with_result, args=(result_queue, "B"))
p.start()
result = result_queue.get()  # Get result
p.join()
```

### Pool — Process Pool

```python
from multiprocessing import Pool, cpu_count

# ── Pool.map — parallel mapping ────────────────────────────
def process_item(item: dict) -> dict:
    # CPU-intensive processing
    item['result'] = expensive_transform(item['data'])
    return item

data = [{'id': i, 'data': range(1000000)} for i in range(16)]

with Pool(processes=cpu_count()) as pool:
    # map: blocks until all done
    results = pool.map(process_item, data)
    
    # imap: lazy iteration (yields as completed)
    for result in pool.imap(process_item, data):
        print(f"Got: {result['id']}")
    
    # imap_unordered: yields as completed, no order guarantee
    for result in pool.imap_unordered(process_item, data):
        print(f"Got: {result['id']}")

# ── Pool.starmap — multiple arguments ──────────────────────
def multiply(x, y):
    return x * y

with Pool(4) as pool:
    results = pool.starmap(multiply, [(1,2), (3,4), (5,6)])
    # results = [2, 12, 30]

# ── Pool.apply_async — non-blocking submission ────────────
def process_chunk(chunk):
    return [item * 2 for item in chunk]

with Pool(4) as pool:
    futures = []
    for chunk in chunks:
        future = pool.apply_async(process_chunk, (chunk,))
        futures.append(future)
    
    for future in futures:
        result = future.get(timeout=30)
        all_results.extend(result)
```

### Shared Memory

```python
from multiprocessing import shared_memory, Value, Array, Manager
import numpy as np

# ── Shared Memory (Python 3.8+) ────────────────────────────
# Zero-copy shared memory between processes
def worker_process(shm_name: str, shape: tuple, dtype: np.dtype):
    existing_shm = shared_memory.SharedMemory(name=shm_name)
    arr = np.ndarray(shape, dtype=dtype, buffer=existing_shm.buf)
    
    # Modify in place — no serialization!
    arr *= 2
    
    existing_shm.close()

# Main process
shape = (1000, 1000)
arr = np.zeros(shape, dtype=np.float64)

shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
shared_arr = np.ndarray(shape, dtype=arr.dtype, buffer=shm.buf)
shared_arr[:] = arr[:]

p = mp.Process(target=worker_process, args=(shm.name, shape, arr.dtype))
p.start()
p.join()

print(shared_arr[:5, :5])  # Values doubled!

shm.close()
shm.unlink()

# ── Value and Array (simpler shared primitives) ────────────
counter = mp.Value('i', 0)  # Shared integer
data = mp.Array('d', 100)   # Shared array of 100 doubles

def increment(counter):
    with counter.get_lock():  # Value has built-in lock
        counter.value += 1

# ── Manager — shared Python objects ────────────────────────
# Manager provides shared dicts, lists, Namespaces, etc.
# Slower than shared_memory (uses IPC) but more flexible

def manager_worker(d, key, value):
    d[key] = value

with mp.Manager() as manager:
    shared_dict = manager.dict()
    shared_list = manager.list()
    
    processes = []
    for i in range(5):
        p = mp.Process(target=manager_worker, args=(shared_dict, f'key-{i}', i))
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()
    
    print(dict(shared_dict))  # {'key-0': 0, 'key-1': 1, ...}
```

### Multiprocessing Queue & Pipe

```python
# ── Queue — thread & process safe ─────────────────────────
from multiprocessing import Queue, Pipe

task_queue = Queue(maxsize=100)
result_queue = Queue()

def producer(q: Queue, items: list):
    for item in items:
        q.put(item)
    q.put(None)  # Sentinel

def consumer(in_q: Queue, out_q: Queue):
    while True:
        item = in_q.get()
        if item is None:
            out_q.put(None)
            break
        result = process(item)
        out_q.put(result)

# ── Pipe — two-way communication ───────────────────────────
parent_conn, child_conn = Pipe(duplex=True)

def pipe_worker(conn):
    conn.send("Hello")
    msg = conn.recv()
    print(f"Worker received: {msg}")
    conn.close()

p = mp.Process(target=pipe_worker, args=(child_conn,))
p.start()

msg = parent_conn.recv()
print(f"Main received: {msg}")
parent_conn.send("World")
p.join()
```

---

## 8. AsyncIO — Event Loop Concurrency

### When to Use AsyncIO

```python
# ── AsyncIO is best for ────────────────────────────────────
# 1. Many concurrent I/O connections (1000s of open sockets)
# 2. Network services (HTTP servers, WebSocket handlers)
# 3. Microservices communicating over the network
# 4. File I/O (async file operations)
# 5. Any workload that spends most time waiting for I/O

# ── AsyncIO is NOT good for ────────────────────────────────
# 1. CPU-bound computation (blocking the event loop)
# 2. Libraries that don't support async
# 3. True parallelism (single-threaded by design)
```

### Event Loop Mechanics

```python
import asyncio

# ── The event loop in action ──────────────────────────────
async def task_a():
    print("A: started")
    await asyncio.sleep(1)  # Yields control
    print("A: finished")

async def task_b():
    print("B: started")
    await asyncio.sleep(0.5)
    print("B: finished")

# These run concurrently (not in parallel)
async def main():
    await asyncio.gather(task_a(), task_b())

asyncio.run(main())
# Output:
# A: started
# B: started
# B: finished
# A: finished

# ── Mixed threading and asyncio ────────────────────────────
# Run blocking code in a thread pool
async def fetch_with_fallback(url: str):
    loop = asyncio.get_event_loop()
    
    # Run sync function in thread pool — doesn't block event loop
    result = await loop.run_in_executor(
        None,  # Default ThreadPoolExecutor
        sync_http_request, url
    )
    return result
```

### Running Blocking Code with AsyncIO

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

# ── Thread pool with asyncio ───────────────────────────────
async def process_items():
    loop = asyncio.get_event_loop()
    
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = []
        for item in items:
            # CPU-bound or blocking work runs in thread pool
            task = loop.run_in_executor(pool, cpu_bound_func, item)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
    return results

# ── Async context manager for thread pool ─────────────────
class ThreadPoolAsync:
    def __init__(self, max_workers: int = 4):
        self.pool = ThreadPoolExecutor(max_workers)
    
    async def run(self, fn, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.pool, fn, *args, **kwargs)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        self.pool.shutdown(wait=True)

# Usage:
# async with ThreadPoolAsync(4) as pool:
#     result = await pool.run(expensive_compute, data)
```

---

## 9. Choosing the Right Approach

### Decision Guide

```python
# ═══════════════════════════════════════════════════════════
# How to choose your concurrency model
# ═══════════════════════════════════════════════════════════

def choose_concurrency_model(workload_type: str, concurrency: int):
    """
    workload_type: 'cpu', 'io_network', 'io_disk', 'mixed'
    concurrency: number of simultaneous tasks
    """
    
    guide = {
        'cpu': {
            'few_tasks': 'multiprocessing',
            'many_tasks': 'multiprocessing with Pool',
            'logic': 'True parallelism needed. GIL prevents threading.',
        },
        'io_network': {
            'few_tasks': 'threading (simpler than asyncio)',
            'many_tasks': 'asyncio (thousands of connections)',
            'logic': 'Both release GIL. asyncio scales to more connections.',
        },
        'io_disk': {
            'few_tasks': 'threading',
            'many_tasks': 'asyncio with aiofiles',
            'logic': 'Disk I/O also releases GIL.',
        },
        'mixed': {
            'few_tasks': 'multiprocessing + threading',
            'many_tasks': 'asyncio + ProcessPoolExecutor',
            'logic': 'Use threads for I/O, processes for CPU.',
        },
    }
    
    return guide[workload_type]

# ── Hybrid pattern: asyncio + multiprocessing ─────────────
import asyncio
from concurrent.futures import ProcessPoolExecutor

async def hybrid_pipeline(data: list) -> list:
    """Use asyncio for I/O, processes for CPU work"""
    
    loop = asyncio.get_event_loop()
    
    with ProcessPoolExecutor(max_workers=4) as pool:
        # Phase 1: CPU-bound processing in parallel
        cpu_results = await loop.run_in_executor(
            pool, cpu_heavy_process, data
        )
        
        # Phase 2: I/O-bound with asyncio
        io_tasks = [
            make_network_call(result)
            for result in cpu_results
        ]
        final_results = await asyncio.gather(*io_tasks)
    
    return final_results
```

### Performance Comparison Table

| Aspect | Threading | Multiprocessing | AsyncIO |
|--------|-----------|-----------------|---------|
| **True parallelism** | ❌ | ✅ | ❌ |
| **Memory overhead** | ~1MB/thread | ~50MB/process | ~2KB/task |
| **Startup time** | Fast | Slow (fork) | Fast |
| **IPC required** | No (shared memory) | Yes | No (single thread) |
| **GIL-limited** | Yes (CPU work) | No | N/A (single thread) |
| **Max scale** | ~1000 threads | ~100 processes | ~100K tasks |
| **Debug complexity** | Medium | High | Medium |
| **Best for** | I/O-bound, shared state | CPU-bound, isolation | I/O-bound, many conns |

---

## 10. Thread Safety Patterns

### Immutable Data

```python
# ── Immutable objects are inherently thread-safe ──────────

from typing import NamedTuple
import threading

# NamedTuple is immutable (no __dict__, no attribute mutation)
class Config(NamedTuple):
    host: str
    port: int
    timeout: float
    max_connections: int

# Once created, Config is safe to share across threads
config = Config("localhost", 8080, 30.0, 100)

def worker():
    # Reading config is always safe — no mutation!
    conn = connect(config.host, config.port, config.timeout)
```

### Thread-Local Storage

```python
# ── Each thread gets its own copy of data ──────────────────
import threading

_request_context = threading.local()

def set_request_context(user_id: str, request_id: str):
    _request_context.user_id = user_id
    _request_context.request_id = request_id
    _request_context.trace_id = f"{user_id}:{request_id}"

def get_request_context():
    return {
        'user_id': getattr(_request_context, 'user_id', None),
        'request_id': getattr(_request_context, 'request_id', None),
        'trace_id': getattr(_request_context, 'trace_id', None),
    }

# ── Thread-local logger ─────────────────────────────────────
import logging

class ThreadLocalLogger:
    _storage = threading.local()
    
    def __init__(self, name: str):
        self.name = name
    
    def get_logger(self) -> logging.Logger:
        if not hasattr(self._storage, 'logger'):
            self._storage.logger = logging.getLogger(self.name)
        return self._storage.logger

# Usage in thread pool:
# logger = ThreadLocalLogger("my_service")
# log = logger.get_logger()  # Each thread has its own logger instance
```

### Atomic Operations (No Lock Needed)

```python
# ── In CPython, some operations are atomic ─────────────────
# Due to the GIL, these single bytecode operations are safe:

# ✅ Atomic (single bytecode):
value = shared_dict['key']    # dict lookup
shared_dict['key'] = value    # dict assignment in many cases
shared_list.append(item)      # list append
shared_list[i] = value        # list index assignment

# ❌ NOT atomic (multiple bytecodes):
shared_dict['key'] += 1       # read + modify + write
shared_list[i] += 1           # read + modify + write
shared_counter -= 1            # read + subtract + write

# ── Even with GIL, += is NOT safe! ─────────────────────────
# counter += 1 compiles to:
# LOAD_FAST counter
# LOAD_CONST 1
# INPLACE_ADD       ← Thread switch can happen here!
# STORE_FAST counter

# This is why threading.Lock is still needed for compound ops.
```

### Read-Copy-Update (RCU) Pattern

```python
# ── Lock-free reads with atomic pointer swap ───────────────
import copy
import threading

class RCUCache:
    """Read-Copy-Update pattern for high-read workloads"""
    
    def __init__(self, initial_data: dict = None):
        self._lock = threading.Lock()
        self._data = initial_data or {}  # Immutable snapshot
        self._version = 0
    
    def get(self, key: str, default=None):
        # Lock-free read! Always safe because _data is never mutated
        data = self._data  # Atomic reference assignment (GIL)
        return data.get(key, default)
    
    def update(self, key: str, value):
        """Copy data, modify copy, swap atomically"""
        with self._lock:
            # Copy whole structure (expensive but read-safe)
            new_data = copy.deepcopy(self._data)
            new_data[key] = value
            # Atomic swap — subsequent reads see new version
            self._data = new_data
            self._version += 1
    
    def batch_update(self, updates: dict):
        """Multiple updates with single atomic swap"""
        with self._lock:
            new_data = copy.deepcopy(self._data)
            new_data.update(updates)
            self._data = new_data
            self._version += 1

# Usage:
# cache = RCUCache({'config': 'initial'})
# # Readers (no lock needed):
# val = cache.get('config')
# # Writers:
# cache.update('config', 'new_value')
```

### Read-Write Lock Pattern

```python
# ── Read-Write lock for read-heavy workloads ───────────────
# Note: Python doesn't have built-in RWLock in threading
# Here's an implementation:

class RWLock:
    """Read-Write lock: multiple readers, exclusive writer"""
    
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
    
    def acquire_read(self):
        """Multiple readers can acquire simultaneously"""
        with self._read_ready:
            self._readers += 1
    
    def release_read(self):
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()
    
    def acquire_write(self):
        """Exclusive — waits for all readers to finish"""
        with self._read_ready:
            while self._readers > 0:
                self._read_ready.wait()
    
    def release_write(self):
        pass  # Nothing to do
    
    @contextmanager
    def read_lock(self):
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()
    
    @contextmanager
    def write_lock(self):
        self.acquire_write()
        try:
            yield
        finally:
            self.release_write()

# Usage:
# rwlock = RWLock()
# 
# # Readers (concurrent):
# with rwlock.read_lock():
#     print(cache.data)
# 
# # Writer (exclusive):
# with rwlock.write_lock():
#     cache.data = new_data
```

### Pipeline Pattern (Thread-Safe)

```python
# ── Thread-safe pipeline using queues ──────────────────────
class PipelineStage(threading.Thread):
    def __init__(self, input_queue: queue.Queue, output_queue: queue.Queue,
                 process_fn, name: str = ""):
        super().__init__(daemon=True)
        self.input = input_queue
        self.output = output_queue
        self.process = process_fn
        self.name = name
    
    def run(self):
        while True:
            item = self.input.get()
            if item is None:  # Sentinel
                self.output.put(None)
                break
            try:
                result = self.process(item)
                self.output.put(result)
            except Exception as e:
                self.output.put(e)

class Pipeline:
    def __init__(self, stages: list):
        self.queues = [queue.Queue() for _ in range(len(stages) + 1)]
        self.stages = []
        
        for i, (process_fn, name) in enumerate(stages):
            stage = PipelineStage(
                self.queues[i], self.queues[i+1],
                process_fn, name
            )
            self.stages.append(stage)
    
    def start(self):
        for stage in self.stages:
            stage.start()
    
    def process(self, item):
        self.queues[0].put(item)
    
    def get_result(self, timeout: float = None):
        return self.queues[-1].get(timeout=timeout)
    
    def shutdown(self):
        self.queues[0].put(None)  # Propagates through all stages
        for stage in self.stages:
            stage.join(timeout=1.0)

# Usage:
# def parse_data(data): return json.loads(data)
# def validate(item): return item if item['id'] else None
# def save(item): db.insert(item); return item
#
# pipeline = Pipeline([
#     (parse_data, "parser"),
#     (validate, "validator"),
#     (save, "saver"),
# ])
# pipeline.start()
# pipeline.process('{"id": 1, "name": "test"}')
# result = pipeline.get_result()
```

---

## 11. Debugging Concurrency Issues

### Common Pitfalls

```python
# ── 1. Deadlock ─────────────────────────────────────────────
# Thread A holds Lock 1, waits for Lock 2
# Thread B holds Lock 2, waits for Lock 1

# Fix: consistent lock ordering, timeouts, or try-lock

# ── 2. Race Condition ──────────────────────────────────────
# Two threads read/write shared data without synchronization

counter = 0
def bad_increment():
    global counter
    counter += 1  # NOT safe! Read, modify, write are not atomic

# ── 3. False Sharing (Cache Line Ping-Pong) ──────────────
# Multiple threads modify different variables on the same cache line
# CPU caches invalidate each other → performance collapse

# ── 4. Thread Starvation ─────────────────────────────────
# Low-priority threads never get CPU time
# Fix: fairness mechanisms, explicit scheduling

# ── 5. GIL Convoy ─────────────────────────────────────────
# Multiple CPU-bound threads all competing for GIL
# Each gets ~5ms before switching → worse than sequential!
# Fix: use multiprocessing for CPU work

# ── 6. Holding Lock During I/O ────────────────────────────
with lock:
    data = fetch_from_network()  # ⚠️ I/O while holding lock!
    process(data)
# Fix: minimize locked regions, fetch outside lock
```

### Debugging Tools

```python
# ── 1. Trace all threads ──────────────────────────────────── 
import traceback
import sys

def dump_threads():
    """Print stack traces for all threads"""
    for thread_id, stack in sys._current_frames().items():
        thread = threading._active.get(thread_id)
        thread_name = thread.name if thread else f"Thread-{thread_id}"
        print(f"\n=== {thread_name} (ID: {thread_id}) ===")
        traceback.print_stack(stack)

# Register as signal handler for debugging
import signal
signal.signal(signal.SIGUSR1, lambda sig, frame: dump_threads())

# ── 2. Logging threading events ────────────────────────────
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(threadName)s] %(message)s',
)

# ── 3. Deadlock detection ──────────────────────────────────
import threading
import time

class DeadlockDetectMixin:
    """Mixin that tracks lock acquisition order to detect deadlocks"""
    
    _acquired_locks = threading.local()
    
    def acquire(self, blocking=True, timeout=-1):
        result = super().acquire(blocking, timeout)
        if result:
            if not hasattr(self._acquired_locks, 'stack'):
                self._acquired_locks.stack = []
            self._acquired_locks.stack.append({
                'lock': self,
                'thread': threading.current_thread().name,
                'time': time.monotonic(),
            })
        return result
    
    def release(self):
        if hasattr(self._acquired_locks, 'stack'):
            for i, entry in enumerate(self._acquired_locks.stack):
                if entry['lock'] is self:
                    self._acquired_locks.stack.pop(i)
                    break
        super().release()

# ── 4. ThreadSanitizer (requires compile flag) ─────────────
# python3.12 -X tsan my_script.py
# Or compile with: --with-thread-sanitizer
# Detects: data races, lock ordering violations

# ── 5. objgraph for reference cycle detection ──────────────
import objgraph

def find_leaking_objects():
    """Find objects that shouldn't be alive"""
    gc.collect()
    
    # Show most common types
    objgraph.show_most_common_types(limit=20)
    
    # Show growth since last call
    objgraph.show_growth(limit=10)
```

### Profiling Concurrent Code

```python
# ── Profile thread contention ──────────────────────────────
import cProfile
import pstats
import threading

def profile_threads(func, *args, **kwargs):
    """Profile a function that spawns threads"""
    profiler = cProfile.Profile()
    profiler.enable()
    
    result = func(*args, **kwargs)
    
    profiler.disable()
    
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')
    stats.print_stats(20)
    
    return result

# ── Measure lock contention ────────────────────────────────
import time

class LockProfiler:
    """Wraps a lock and profiles contention"""
    
    def __init__(self, lock, name="lock"):
        self._lock = lock
        self.name = name
        self.acquire_count = 0
        self.total_wait_time = 0.0
        self.max_wait_time = 0.0
    
    def acquire(self, blocking=True, timeout=-1):
        start = time.monotonic()
        result = self._lock.acquire(blocking, timeout)
        wait = time.monotonic() - start
        
        if result:
            self.acquire_count += 1
            self.total_wait_time += wait
            self.max_wait_time = max(self.max_wait_time, wait)
        
        return result
    
    def release(self):
        self._lock.release()
    
    def stats(self):
        if self.acquire_count == 0:
            return "No acquisitions"
        avg_wait = self.total_wait_time / self.acquire_count
        return (f"Lock '{self.name}': "
                f"acquired={self.acquire_count}, "
                f"avg_wait={avg_wait*1000:.2f}ms, "
                f"max_wait={self.max_wait_time*1000:.2f}ms")
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, *args):
        self.release()
```

---

## 12. Concurrency & Parallelism Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the difference between concurrency and parallelism? Give Python examples.</b></summary>

**Answer:** Concurrency is about structuring a program to handle multiple tasks simultaneously (interleaving). Parallelism is about executing multiple tasks simultaneously on multiple cores.

In Python:
- **Concurrency:** Threading and asyncio — multiple tasks make progress, but only one executes at a time (GIL prevents parallel bytecode execution)
- **Parallelism:** Multiprocessing — separate processes each have their own GIL and can run on different cores simultaneously

```python
# Concurrency: tasks interleaved on single core
import threading
# Threads take turns executing (concurrent, not parallel)

# Parallelism: tasks run simultaneously on different cores
from multiprocessing import Pool
# Processes run truly in parallel
```
</details>

<details>
<summary><b>Q2: What is the GIL? Why does it exist?</b></summary>

**Answer:** The Global Interpreter Lock (GIL) is a mutex that prevents multiple threads from executing Python bytecodes simultaneously in the same process. It exists because:
1. **Reference counting:** CPython's memory management relies on reference counts, which must be protected from race conditions
2. **Internal data structures:** Objects like dicts and lists need protection from concurrent modification
3. **Simplicity:** Without the GIL, CPython would need fine-grained locks on every object, making single-threaded code much slower

The GIL makes single-threaded code fast (~15% speed loss vs no GIL) at the cost of multithreaded CPU performance.
</details>

<details>
<summary><b>Q3: When would you use threading vs asyncio vs multiprocessing?</b></summary>

**Answer:** 
- **Threading:** I/O-bound work with moderate concurrency (<1000 connections), when you need shared state, or when using libraries that don't support asyncio
- **AsyncIO:** I/O-bound work with very high concurrency (1000s of connections), network servers, when you want lightweight tasks
- **Multiprocessing:** CPU-bound work, when you need true parallelism, or when isolating workloads for fault tolerance

Choose by workload type first, then by concurrency requirements.
</details>

### Intermediate

<details>
<summary><b>Q4: How does the GIL switch between threads? Can you control it?</b></summary>

**Answer:** Since Python 3.2 (PEP 1043), the GIL uses a time-based switching mechanism:
- The GIL is released and re-acquired every 5ms (default)
- Uses a condition variable for fairness
- The holding thread signals waiting threads when it releases

You can control it with:
```python
sys.setswitchinterval(0.001)  # 1ms — more frequent switching
sys.setswitchinterval(10.0)   # 10s — almost no switching

# Check current interval:
print(sys.getswitchinterval())  # Default: 0.005 (5ms)
```

C extensions can explicitly release the GIL:
```c
Py_BEGIN_ALLOW_THREADS
// C computation without Python calls
Py_END_ALLOW_THREADS
```

NumPy, Pandas, and many C extensions release the GIL during heavy computation.
</details>

<details>
<summary><b>Q5: What is a deadlock? How do you prevent it?</b></summary>

**Answer:** A deadlock occurs when two or more threads are each waiting for a lock held by another, creating a cycle of waiting.

**Prevention strategies:**
1. **Lock ordering:** Always acquire locks in a consistent global order
2. **Lock timeout:** Use `lock.acquire(timeout=5.0)` instead of unbounded wait
3. **Try-lock:** Use `lock.acquire(blocking=False)` to avoid blocking
4. **Minimize lock scope:** Only hold locks for the shortest time necessary
5. **Avoid nested locks:** If possible, restructure to use a single lock or lock-free patterns

**Detection:**
```python
# Check for deadlocked threads
import threading
for thread in threading.enumerate():
    if thread.is_alive() and thread.ident:
        # Thread is stuck — likely deadlocked
        import traceback
        traceback.print_stack(sys._current_frames()[thread.ident])
```
</details>

<details>
<summary><b>Q6: Explain the difference between Lock, RLock, Semaphore, and Condition.</b></summary>

**Answer:**

| Primitive | Behavior | Use Case |
|-----------|----------|----------|
| **Lock** | Only one thread can acquire. Same thread can't re-acquire (would deadlock). | Simple mutual exclusion |
| **RLock** | Reentrant — same thread can acquire multiple times. Must release same number of times. | Methods calling other methods with same lock |
| **Semaphore** | Allows N threads to acquire simultaneously. Counter-based. | Connection pools, rate limiting |
| **Condition** | Combines a Lock with wait/notify mechanism. Threads wait for a condition, are notified when state changes. | Producer-consumer, bounded buffers |

```python
# Lock — simple mutual exclusion
lock = threading.Lock()
with lock:
    counter += 1

# RLock — reentrant (same thread can acquire again)
rlock = threading.RLock()
with rlock:
    with rlock:  # OK with RLock, deadlock with Lock
        counter += 1

# Semaphore — limit concurrent access
sem = threading.Semaphore(5)  # Max 5 threads
with sem:
    # At most 5 threads here
    pass

# Condition — wait for state
cond = threading.Condition()
with cond:
    while not data_available:
        cond.wait()  # Release lock, sleep until notified
    process_data()
```
</details>

<details>
<summary><b>Q7: What are daemon threads? When would you use them?</b></summary>

**Answer:** Daemon threads are threads that run in the background and die automatically when the main thread exits. The Python interpreter exits when only daemon threads remain.

**Use cases:**
- Background monitoring/heartbeat threads
- Periodic cache cleanup
- Logging/telemetry collection
- Health check servers

```python
# Daemon thread — dies when main thread exits
monitor = threading.Thread(target=watchdog, daemon=True)
monitor.start()

# Non-daemon thread — keeps process alive
worker = threading.Thread(target=process_data)  # daemon=False by default
worker.start()
```

**⚠️ Warning:** Daemon threads can be interrupted mid-operation, potentially leaving resources in an inconsistent state. Don't use them for critical cleanup or transactions.
</details>

<details>
<summary><b>Q8: How do you safely share data between threads?</b></summary>

**Answer:** Safe data sharing approaches (ordered by preference):

1. **Queues** (`queue.Queue`): Pass messages, not shared state
2. **Thread-local storage** (`threading.local`): Each thread has its own copy
3. **Locks** (`Lock`, `RLock`): Protect critical sections
4. **Atomic operations**: Simple reads/writes (GIL-protected for single bytecodes)
5. **Immutable data**: No mutation means no races

```python
# ✅ Safe: Queue-based communication
q = queue.Queue()
def producer():
    q.put(data)
def consumer():
    data = q.get()

# ✅ Safe: Thread-local storage
local = threading.local()
def worker():
    local.counter = 0  # Each thread has its own

# ✅ Safe: Lock-protected shared state
lock = threading.Lock()
shared_list = []
with lock:
    if condition:
        shared_list.append(item)

# ❌ Unsafe: Shared mutable state without synchronization
shared_dict[key] = value  # Safe in CPython (single bytecode)
shared_dict[key] += 1     # UNSAFE (read + modify + write)
```
</details>

### Advanced

<details>
<summary><b>Q9: Implement a thread-safe bounded buffer (producer-consumer) using Condition variables.</b></summary>

**Answer:**
```python
import threading

class BoundedBuffer:
    def __init__(self, capacity: int):
        self.buffer = []
        self.capacity = capacity
        self.cond = threading.Condition()
    
    def put(self, item):
        with self.cond:
            while len(self.buffer) >= self.capacity:
                self.cond.wait()  # Buffer full, wait
            self.buffer.append(item)
            self.cond.notify()  # Wake one consumer
    
    def get(self):
        with self.cond:
            while len(self.buffer) == 0:
                self.cond.wait()  # Buffer empty, wait
            item = self.buffer.pop(0)
            self.cond.notify()  # Wake one producer
            return item
    
    def put_many(self, items):
        with self.cond:
            for item in items:
                while len(self.buffer) >= self.capacity:
                    self.cond.wait()
                self.buffer.append(item)
            self.cond.notify_all()  # Wake all consumers
    
    def size(self):
        with self.cond:
            return len(self.buffer)

# Usage:
buffer = BoundedBuffer(10)

def producer():
    for i in range(100):
        buffer.put(f"item-{i}")

def consumer():
    for _ in range(100):
        item = buffer.get()
        print(f"Got: {item}")

t1 = threading.Thread(target=producer)
t2 = threading.Thread(target=consumer)
t1.start(); t2.start()
t1.join(); t2.join()
```
</details>

<details>
<summary><b>Q10: How does Python's GIL affect I/O-bound vs CPU-bound performance? Explain with benchmark.</b></summary>

**Answer:**
```python
import threading
import time
import requests

# ── I/O-bound: GIL releases during I/O wait ────────────────
# Threads work well here!
def io_heavy(urls):
    def fetch(url):
        requests.get(url)  # GIL released during network I/O
    
    threads = [threading.Thread(target=fetch, args=(url,)) 
               for url in urls]
    start = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    return time.perf_counter() - start

# ── CPU-bound: GIL serializes execution ────────────────────
# Threads are WORSE than sequential!
def cpu_heavy():
    def compute():
        sum(i ** 2 for i in range(10_000_000))
    
    threads = [threading.Thread(target=compute) for _ in range(4)]
    start = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    return time.perf_counter() - start

# Results:
# I/O-bound: 4 threads ≈ 4x faster than 1
# CPU-bound: 4 threads ≈ SAME as 1 (GIL contention adds overhead)
# CPU-bound with multiprocessing: 4 processes ≈ 3.5x faster
```

**The GIL impact:**
- I/O-bound: Threads work great (GIL released during I/O)
- CPU-bound: Threads don't help (GIL serializes)
- Mixed: Threads help with I/O portion, CPU portion is serialized
</details>

<details>
<summary><b>Q11: Design a concurrent web scraper that respects rate limits, handles errors, and collects results asynchronously using multiple approaches.</b></summary>

**Answer:**
```python
import asyncio
import aiohttp
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
import time

# ── Approach 1: AsyncIO (best for I/O-bound) ──────────────
class AsyncScraper:
    def __init__(self, max_concurrent: int = 10, rate_limit: float = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limit = rate_limit
        self.last_request = 0
        self.lock = asyncio.Lock()
    
    async def fetch(self, session: aiohttp.ClientSession, url: str) -> dict:
        async with self.semaphore:
            await self._throttle()
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(10)) as resp:
                    text = await resp.text()
                    return {'url': url, 'status': resp.status, 'size': len(text)}
            except Exception as e:
                return {'url': url, 'error': str(e)}
    
    async def _throttle(self):
        async with self.lock:
            now = time.monotonic()
            wait = 1.0 / self.rate_limit - (now - self.last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_request = time.monotonic()
    
    async def scrape_many(self, urls: list[str]) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            tasks = [self.fetch(session, url) for url in urls]
            return await asyncio.gather(*tasks)

# ── Approach 2: Threading (good for mixed workloads) ──────
class ThreadedScraper:
    def __init__(self, num_workers: int = 10, rate_limit: float = 10):
        self.url_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.num_workers = num_workers
        self.rate_limiter = threading.Semaphore(int(rate_limit))
        self._stop = threading.Event()
    
    def _worker(self):
        import requests
        while not self._stop.is_set():
            try:
                url = self.url_queue.get(timeout=1)
                self.rate_limiter.acquire()
                
                try:
                    resp = requests.get(url, timeout=10)
                    self.result_queue.put({
                        'url': url,
                        'status': resp.status_code,
                        'size': len(resp.text),
                    })
                except Exception as e:
                    self.result_queue.put({'url': url, 'error': str(e)})
                
                # Schedule rate limit token refill
                threading.Timer(1.0, self.rate_limiter.release).start()
                
            except queue.Empty:
                continue
    
    def scrape(self, urls: list[str]) -> list[dict]:
        workers = []
        for _ in range(self.num_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            workers.append(t)
        
        for url in urls:
            self.url_queue.put(url)
        
        # Wait for all URLs to be processed
        self.url_queue.join()
        self._stop.set()
        
        results = []
        while not self.result_queue.empty():
            results.append(self.result_queue.get_nowait())
        
        return results

# ── Approach 3: ProcessPoolExecutor (for CPU+IO mixed) ────
from concurrent.futures import ProcessPoolExecutor, as_completed

def scrape_url(url: str) -> dict:
    import requests
    start = time.perf_counter()
    try:
        resp = requests.get(url, timeout=10)
        return {
            'url': url,
            'status': resp.status_code,
            'time': time.perf_counter() - start,
            'size': len(resp.text),
        }
    except Exception as e:
        return {'url': url, 'error': str(e), 'time': time.perf_counter() - start}

def parallel_scrape(urls: list[str]) -> list[dict]:
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(scrape_url, url): url for url in urls}
        results = []
        for future in as_completed(futures):
            results.append(future.result(timeout=30))
        return results
```
</details>

<details>
<summary><b>Q12: Explain free-threaded Python (PEP 703). What changes and what breaks?</b></summary>

**Answer:** PEP 703 (Python 3.13t) makes the GIL optional. Key implications:

**What changes:**
- `--disable-gil` configure option or `PYTHON_GIL=0` environment variable
- Multiple threads can execute Python bytecodes simultaneously
- True parallelism with `threading` for CPU-bound work
- ~5-8% single-threaded performance penalty (biasing GC, reference counting changes)

**What breaks:**
- C extensions that assume GIL protection must be updated
- Thread-unsafe became the default — all mutable objects need explicit synchronization
- Atomic operations under GIL (dict lookup, list append) are no longer atomic
- JIT compilers (PyPy) need updates
- Reference counting changes: deferred reference counting, immortal objects

**Migration path:**
1. Run with `PYTHON_GIL=1` for GIL-enabled (default until at least 3.13)
2. Test with `PYTHON_GIL=0` and fix C extensions
3. For Python code: ensure proper locking on all shared mutable state
</details>

<details>
<summary><b>Q13: Design a thread-safe connection pool for a database.</b></summary>

**Answer:**
```python
import threading
import time
from collections import deque
from typing import Optional, Callable, TypeVar

T = TypeVar('T')

class ConnectionPool:
    """Thread-safe connection pool with health checks and max connections"""
    
    def __init__(
        self,
        create_conn: Callable[[], T],
        close_conn: Callable[[T], None],
        max_connections: int = 10,
        min_connections: int = 2,
        timeout: float = 30.0,
        health_check: Optional[Callable[[T], bool]] = None,
    ):
        self._create = create_conn
        self._close = close_conn
        self._max = max_connections
        self._min = min_connections
        self._timeout = timeout
        self._health = health_check or (lambda c: True)
        
        self._pool = deque()
        self._in_use = set()
        self._count = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        
        # Create minimum connections
        for _ in range(min_connections):
            conn = self._create()
            self._pool.append(conn)
            self._count += 1
    
    def acquire(self) -> T:
        """Get a connection from the pool, creating if needed"""
        with self._cond:
            # Try existing connections first
            while self._pool:
                conn = self._pool.popleft()
                if self._health(conn):
                    self._in_use.add(conn)
                    return conn
                # Dead connection — close and replace
                self._close(conn)
                self._count -= 1
            
            # No available connections — create one if under max
            if self._count < self._max:
                conn = self._create()
                self._count += 1
                self._in_use.add(conn)
                return conn
            
            # At max — wait for a release
            if not self._cond.wait(timeout=self._timeout):
                raise TimeoutError("Connection pool timeout")
            
            # Wake up — try again (another thread released a connection)
            return self.acquire()
    
    def release(self, conn: T):
        """Return a connection to the pool"""
        with self._cond:
            self._in_use.discard(conn)
            if self._health(conn):
                self._pool.append(conn)
            else:
                # Dead connection — close it
                self._close(conn)
                self._count -= 1
                # Try to maintain minimum pool size
                if self._count < self._min:
                    new_conn = self._create()
                    self._pool.append(new_conn)
                    self._count += 1
            self._cond.notify()  # Wake waiting acquirers
    
    @contextmanager
    def connection(self):
        """Context manager for automatic release"""
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)
    
    def close_all(self):
        """Close all connections in the pool"""
        with self._cond:
            for conn in list(self._pool) + list(self._in_use):
                self._close(conn)
            self._pool.clear()
            self._in_use.clear()
            self._count = 0

# Usage:
# pool = ConnectionPool(
#     create_conn=lambda: sql.connect("postgresql://..."),
#     close_conn=lambda c: c.close(),
#     max_connections=20,
#     min_connections=5,
# )
# with pool.connection() as conn:
#     conn.execute("SELECT * FROM users")
```
</details>

<details>
<summary><b>Q14: How do subinterpreters (Python 3.12+) enable true parallelism? What are the limitations?</b></summary>

**Answer:** Subinterpreters (PEP 684) provide isolated Python interpreters within the same process. Each subinterpreter has its own GIL, enabling true parallel execution of Python code.

**How they work:**
- Each subinterpreter has its own: GIL, memory allocator, module state, exception state
- Communication via channels (queue-like queues between interpreters)
- No shared mutable state between subinterpreters

```python
import _xxsubinterpreters as interpreters
import _xxinterpchannels as channels

# Create a channel for communication
channel_id = channels.create()

# Create and start a subinterpreter
interp_id = interpreters.create()
interpreters.run_string(interp_id, f"""
import _xxinterpchannels as channels

# Receive data
data = channels.recv({channel_id})
result = process_data(data)

# Send result back
channels.send({channel_id}, result)
""")

# Send data to subinterpreter
channels.send(channel_id, {"items": [1, 2, 3]})

# Receive result
result = channels.recv(channel_id)
```

**Limitations:**
1. **No shared state** — all objects must be pickled/serialized for channel communication
2. **C extension compatibility** — many C extensions aren't subinterpreter-safe (PEP 684 addresses this)
3. **API is low-level** — `_xxsubinterpreters` is an internal module, not a public API yet
4. **Module isolation** — modules are loaded per-interpreter, increasing memory usage
5. **No direct object sharing** — can't pass complex Python objects between interpreters

**vs multiprocessing:** Subinterpreters are lighter (no separate process), share the same address space, but can't share Python objects directly. Multiprocessing can share memory via `shared_memory`.
</details>

<details>
<summary><b>Q15: Implement a thread-safe, lock-free concurrent counter using only atomic operations (considering the GIL).</b></summary>

**Answer:**
```python
import threading
import ctypes

class LockFreeCounter:
    """
    Lock-free counter using CTypes for atomic operations.
    
    Note: Python doesn't have native CAS (Compare-And-Swap)
    in the standard library. This uses ctypes to access 
    hardware-level atomic operations.
    
    In practice, the GIL makes simple operations atomic,
    but this demonstrates lock-free patterns.
    """
    
    def __init__(self, initial: int = 0):
        # Windows: LONG type
        # Linux/macOS: c_long
        self._value = ctypes.c_long(initial)
    
    def increment(self) -> int:
        """Atomic increment, returns new value"""
        # InterlockedIncrement is atomic on all modern CPUs
        if hasattr(ctypes, 'windll'):
            # Windows
            return ctypes.windll.kernel32.InterlockedIncrement(
                ctypes.byref(self._value)
            )
        else:
            # Fallback: GIL makes this safe for simple cases
            # In production, use C extension or Cython
            with threading.Lock():
                self._value.value += 1
                return self._value.value
    
    def decrement(self) -> int:
        if hasattr(ctypes, 'windll'):
            return ctypes.windll.kernel32.InterlockedDecrement(
                ctypes.byref(self._value)
            )
        else:
            with threading.Lock():
                self._value.value -= 1
                return self._value.value
    
    def add(self, n: int) -> int:
        """Atomic add"""
        if hasattr(ctypes, 'windll'):
            return ctypes.windll.kernel32.InterlockedExchangeAdd(
                ctypes.byref(self._value), n
            ) + n
        else:
            with threading.Lock():
                self._value.value += n
                return self._value.value
    
    def value(self) -> int:
        """Read current value"""
        return self._value.value

# ── Simpler approach: use threading's atomic guarantee ─────
# The GIL ensures simple reads/writes are safe:
class SimpleLockFreeCounter:
    """Relies on GIL for atomicity of simple operations"""
    
    def __init__(self, initial: int = 0):
        self._value = initial  # Simple int, GIL-protected read/write
    
    def read(self) -> int:
        return self._value  # Safe: single LOAD_FAST bytecode
    
    # ⚠️ increment is NOT safe without lock!
    # self._value += 1  # LOAD_FAST + LOAD_CONST + INPLACE_ADD + STORE_FAST

# ── Production approach: use multiprocessing.Value ────────
from multiprocessing import Value

class ProductionCounter:
    def __init__(self, initial: int = 0):
        self._counter = Value('i', initial)  # Shared memory with lock
    
    def increment(self) -> int:
        with self._counter.get_lock():
            self._counter.value += 1
            return self._counter.value
    
    def value(self) -> int:
        with self._counter.get_lock():
            return self._counter.value
```
</details>

<details>
<summary><b>Q16: Explain Python's async/await protocol and how it relates to generator-based coroutines.</b></summary>

**Answer:** Python's async/await is built on top of the generator protocol:

**The await protocol:**
1. `async def` creates a coroutine function (returns a coroutine object)
2. `await x` requires `x` to be an awaitable (implements `__await__`)
3. `__await__` must return an iterator
4. The `for x in y: yield x` pattern is how coroutines suspend

```python
# Under the hood, async/await is syntactic sugar for generators:

# This:
async def fetch_data():
    response = await http_get(url)
    return response.json()

# Is equivalent to:
def fetch_data():
    return fetch_data_impl().__await__()

def fetch_data_impl():
    # Each await is a yield from delegation
    response = yield from http_get(url).__await__()
    return response.json()

# The event loop drives this:
# coro.send(None)  → advances to first yield
# coro.send(result) → passes result back
# StopIteration(value) → return value
```

**Event loop mechanics:**
```python
# Simplified event loop:
loop = asyncio.new_event_loop()

# 1. Create coroutine
coro = my_async_function()

# 2. Send None to start
coro.send(None)  # Returns a Future object

# 3. When Future completes, send result back
coro.send(result)  # Returns next Future or raises StopIteration

# 4. catch StopIteration.value for the return value
```

**Key insight:** Async/await doesn't add anything new to Python — it's all generators and event loops. The syntax just makes it readable.
</details>

---

## 📊 Quick Reference: Python Concurrency at a Glance

| Pattern | Module | When to Use |
|---------|--------|-------------|
| Thread creation | `threading.Thread` | I/O-bound parallel tasks |
| Thread pool | `concurrent.futures.ThreadPoolExecutor` | Many similar I/O tasks |
| Mutual exclusion | `threading.Lock` | Protect shared state |
| Reentrant lock | `threading.RLock` | Methods calling other locked methods |
| Semaphore | `threading.Semaphore` | Limit concurrent access |
| Event | `threading.Event` | One-shot signaling |
| Condition | `threading.Condition` | State-dependent waiting |
| Barrier | `threading.Barrier` | Synchronize N threads at a point |
| Queue | `queue.Queue` | Thread-safe data passing |
| Process pool | `concurrent.futures.ProcessPoolExecutor` | CPU-bound parallel tasks |
| Shared memory | `multiprocessing.shared_memory` | Zero-copy data sharing |
| Async I/O | `asyncio` | High-concurrency network I/O |
| Thread-local | `threading.local` | Per-thread data isolation |

---

> *Use these notes as a practical reference for writing concurrent Python code. Remember: choose the concurrency model based on your workload (I/O vs CPU), not on familiarity.*
