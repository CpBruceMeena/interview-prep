# 🐍 Python AsyncIO & Async/Await — Comprehensive Notes

> **A deep-dive into Python's async/await paradigm: coroutines, event loops, tasks, futures, and production-grade async patterns**
> *From fundamentals to staff-level internals — designed for Staff/Principal Engineer interview preparation*

---

## Table of Contents

1. [Core Concepts & Terminology](#1-core-concepts--terminology)
2. [Async/Await Protocol Under the Hood](#2-asyncawait-protocol-under-the-hood)
3. [Event Loop Internals](#3-event-loop-internals)
4. [Running & Managing the Event Loop](#4-running--managing-the-event-loop)
5. [Coroutines Deep Dive](#5-coroutines-deep-dive)
6. [Tasks & Futures](#6-tasks--futures)
7. [Synchronization Primitives](#7-synchronization-primitives)
8. [Async Generators & Async Context Managers](#8-async-generators--async-context-managers)
9. [Streams, Subprocesses & Networking](#9-streams-subprocesses--networking)
10. [Advanced Patterns](#10-advanced-patterns)
11. [Performance Optimization](#11-performance-optimization)
12. [Production Patterns](#12-production-patterns)
13. [Common Pitfalls & Debugging](#13-common-pitfalls--debugging)
14. [asyncio vs Threading vs Multiprocessing](#14-asyncio-vs-threading-vs-multiprocessing)
15. [Interview Questions](#15-interview-questions)

---

## 1. Core Concepts & Terminology

### What is AsyncIO?

AsyncIO is Python's built-in library for writing **concurrent** code using the **async/await** syntax. It provides an event loop that manages cooperative multitasking for I/O-bound workloads.

```python
import asyncio

async def hello():
    await asyncio.sleep(1)
    print("Hello, Async World!")

asyncio.run(hello())
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Coroutine** | A function declared with `async def` — returns a coroutine object when called |
| **Awaitable** | An object that can be `await`ed — coroutines, Tasks, Futures |
| **Event Loop** | The scheduler that runs coroutines and handles I/O multiplexing |
| **Task** | A coroutine wrapped for concurrent execution in the event loop |
| **Future** | A low-level awaitable representing an eventual result |
| **Async Iterator** | An iterator that yields awaitables (`__aiter__`, `__anext__`) |
| **Async Context Manager** | A context manager with async enter/exit (`__aenter__`, `__aexit__`) |

### The Concurrency Spectrum

```python
# ── Synchronous: sequential, blocking ──────────────────────
def sync_fetch():
    data1 = fetch_url("https://api.example.com/a")  # Blocks for 2s
    data2 = fetch_url("https://api.example.com/b")  # Blocks for 2s
    return data1 + data2  # Total: 4s

# ── Async: concurrent, non-blocking ────────────────────────
async def async_fetch():
    async with aiohttp.ClientSession() as session:
        task1 = asyncio.create_task(fetch(session, "https://api.example.com/a"))
        task2 = asyncio.create_task(fetch(session, "https://api.example.com/b"))
        data1, data2 = await asyncio.gather(task1, task2)
        return data1 + data2  # Total: ~2s (overlapped)

# ── Threaded: concurrent, GIL-bound for CPU ────────────────
def threaded_fetch():
    with ThreadPoolExecutor(2) as pool:
        fut1 = pool.submit(fetch_url, "https://api.example.com/a")
        fut2 = pool.submit(fetch_url, "https://api.example.com/b")
        return fut1.result() + fut2.result()  # Total: ~2s
```

### When to Use AsyncIO

| Workload | AsyncIO Suitable? | Reason |
|----------|-------------------|--------|
| Network I/O (HTTP, gRPC, DB) | ✅ Perfect | Non-blocking I/O multiplexing |
| File I/O | ✅ Good (with `aiofiles`) | Async file operations |
| CPU-bound computation | ❌ Bad | Single thread, blocks event loop |
| Many concurrent connections (10K+) | ✅ Excellent | ~2KB per task overhead |
| Microservices / API servers | ✅ Excellent | FastAPI, aiohttp, Sanic |
| Real-time (WebSockets, SSE) | ✅ Excellent | Native WebSocket support |
| GUI applications | ⚠️ Tricky | Requires async-aware GUI loop |

---

## 2. Async/Await Protocol Under the Hood

### What `async def` Actually Generates

```python
# When you write:
async def fetch_data(url: str) -> dict:
    response = await http_get(url)
    return response.json()

# CPython generates a coroutine function that:
# 1. Returns a coroutine object when called (NOT executed)
# 2. The coroutine object implements __await__ → returns an iterator
# 3. At every await, suspends execution via yield

# ── The coroutine object ───────────────────────────────────
coro = fetch_data("https://api.example.com")
print(type(coro))           # <class 'coroutine'>
print(inspect.iscoroutine(coro))  # True
```

### The `__await__` Protocol

```python
# Every awaitable must implement __await__ → returns iterator
class Future:
    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self  # Yield the Future itself to the event loop
        return self.result()
    
    # This is the CRITICAL piece:
    # 1. If future is not done, mark as blocking and yield self
    # 2. Event loop receives the yielded Future
    # 3. Event loop registers a callback on the Future
    # 4. When Future completes, callback schedules coroutine to resume
    # 5. Event loop calls coro.send(result) → continues execution

# ── Manual coroutine driving (what the event loop does) ───
async def demo_coro():
    print("Step 1")
    result = await inner_coro()
    print(f"Step 2: got {result}")
    return "done"

async def inner_coro():
    await asyncio.sleep(0)
    return 42

# The event loop effectively does this:
def drive_coroutine(coro):
    try:
        # First send(None) starts the coroutine
        # The yielded value is a Future
        future = coro.send(None)
        # Register callback to resume when future completes
        future.add_done_callback(lambda f: drive_coroutine(coro))
    except StopIteration as e:
        # Coroutine completed with return value
        return e.value
```

### The `await` Expression — Step by Step

```python
import asyncio
import inspect

# ── Step-by-step execution trace ───────────────────────────
async def step_by_step():
    """
    1. caller calls step_by_step() → gets coroutine object
    2. caller sends None → coroutine starts executing
    3. At 'await sleep(1)':
       a. sleep(1) is called → returns a coroutine (or Future)
       b. __await__() is called on that coroutine
       c. The inner __await__ yields a Future to the event loop
       d. Coroutine is SUSPENDED here
    4. Event loop waits for the Future to complete (1 second)
    5. Event loop calls coro.send(None) → coroutine resumes
    6. sleep(1) returns None
    7. Coroutine continues to next line
    """
    print("Coroutine started")
    await asyncio.sleep(1)  # Suspension point
    print("Coroutine resumed after 1 second")
    return 42

# ── What __await__ looks like for a Future ─────────────────
class TracingFuture:
    """A Future that prints what happens during await"""
    
    def __init__(self):
        self._result = None
        self._done = False
        self._callbacks = []
    
    def __await__(self):
        print("  [Future.__await__] Called!")
        if not self._done:
            self._asyncio_future_blocking = True
            print("  [Future.__await__] Yielding self to event loop")
            yield self  # ← THE KEY LINE: yields control
        print("  [Future.__await__] Resumed! Returning result")
        return self._result
    
    def set_result(self, value):
        self._result = value
        self._done = True
        for cb in self._callbacks:
            cb(self)
    
    def add_done_callback(self, cb):
        self._callbacks.append(cb)
    
    def done(self):
        return self._done
    
    def result(self):
        return self._result

# ── Manual event loop simulation ───────────────────────────
def simple_event_loop(coro):
    """Simplified event loop — drives one coroutine"""
    try:
        print("[Event Loop] Starting coroutine")
        future = coro.send(None)  # Start coroutine, get Future
        print(f"[Event Loop] Got Future: {future}")
        
        # Register callback
        def resume(f):
            try:
                print("[Event Loop] Future completed! Resuming coroutine")
                result = coro.send(None)
                print(f"[Event Loop] Coroutine returned: {result}")
            except StopIteration as e:
                print(f"[Event Loop] Coroutine done: {e.value}")
        
        future.add_done_callback(resume)
        print("[Event Loop] Waiting...")
        
        # Simulate async completion
        import threading
        def complete():
            import time
            time.sleep(0.1)
            future.set_result("completed!")
        
        threading.Thread(target=complete, daemon=True).start()
        
        print("[Event Loop] Back to waiting for I/O events...")
        # In real event loop: selector.select(timeout) here
        
    except StopIteration as e:
        print(f"[Event Loop] Coroutine completed immediately: {e.value}")

# Run the simulation
async def demo():
    fut = TracingFuture()
    print("Created TracingFuture, about to await")
    result = await fut
    print(f"Got result: {result}")

# simple_event_loop(demo())
```

### The Compiler's Perspective

```python
# ── CPython compiler transforms async def into ─────────────
# Essentially equivalent to:

def fetch_data(url):
    """What async def compiles to (conceptually)"""
    
    class Coroutine:
        def __await__(self):
            return self._generator().__await__()
        
        def _generator(self):
            # The actual coroutine body with yields at each await
            response = yield from http_get(url).__await__()
            return response.json()
    
    return Coroutine()

# The `yield from` in __await__ delegates to the inner
# generator, which yields Futures at each suspension point.
# This is why await is "syntactic sugar" for yield from.
```

### `yield from` vs `await`

```python
# ── await is syntactic sugar for yield from ────────────────
# These are functionally equivalent:
result = await awaitable
# ↓
result = yield from awaitable.__await__()

# ── The critical difference ────────────────────────────────
# await expects an awaitable (has __await__)
# yield from expects any iterable/generator

# ── __await__ can be implemented with yield from ────────────
class CustomAwaitable:
    def __await__(self):
        # yield from delegates to the generator
        # The event loop receives yielded values
        result = yield from self._internal_generator()
        return result
    
    def _internal_generator(self):
        print("  Internal generator: step 1")
        yield  # Yield control to event loop
        print("  Internal generator: step 2 (resumed)")
        return "custom result"

# Usage:
async def test_custom():
    result = await CustomAwaitable()
    print(f"Got: {result}")
```

### PEP 492 — The async/await Grammar

```python
# PEP 492 (Python 3.5) introduced async/await as native syntax
# Key grammar additions:

# 1. Coroutine function definition
async def coro_func(): ...

# 2. Await expression
await awaitable  # Can only appear inside async def

# 3. Async for (async iteration)
async for item in async_iterable:
    process(item)

# 4. Async with (async context manager)
async with async_cm as resource:
    await resource.do_something()

# Before PEP 492 (Python 3.3-3.4):
# @asyncio.coroutine decorator + yield from
@asyncio.coroutine
def old_style_coro():
    result = yield from some_future()
    return result

# Modern style (3.5+):
async def modern_coro():
    result = await some_awaitable()
    return result
```

---

## 3. Event Loop Internals

### The Event Loop Three-Phase Cycle

```python
import asyncio
import selectors
import heapq
import time
from collections import deque
from typing import Callable

class ToyEventLoop:
    """Simplified event loop — illustrates the core mechanism"""
    
    def __init__(self):
        self._ready = deque()           # Ready queue (FIFO)
        self._scheduled = []            # Timer heap (min-heap by time)
        self._stopping = False
        self._selector = selectors.DefaultSelector()
    
    def run_forever(self):
        """The main event loop cycle"""
        while not self._stopping:
            # Phase 1: Run all ready callbacks
            while self._ready:
                callback = self._ready.popleft()
                callback()
            
            # Phase 2: Poll for I/O events
            # timeout = time until next scheduled timer
            timeout = self._time_until_next_scheduled()
            events = self._selector.select(timeout)
            for key, mask in events:
                callback = key.data  # Registered via add_reader
                self._ready.append(callback)
            
            # Phase 3: Move expired timers to ready queue
            now = time.monotonic()
            while self._scheduled and self._scheduled[0].when <= now:
                handle = heapq.heappop(self._scheduled)
                self._ready.append(handle.callback)
    
    def call_soon(self, callback: Callable) -> None:
        """Schedule callback for next iteration"""
        self._ready.append(callback)
    
    def call_later(self, delay: float, callback: Callable) -> None:
        """Schedule callback after delay seconds"""
        when = time.monotonic() + delay
        heapq.heappush(self._scheduled, _TimerHandle(when, callback))
    
    def _time_until_next_scheduled(self) -> float:
        """Get timeout for select() call"""
        if not self._scheduled:
            return 1.0  # Default poll interval
        timeout = self._scheduled[0].when - time.monotonic()
        return max(0.0, timeout)

class _TimerHandle:
    def __init__(self, when: float, callback: Callable):
        self.when = when
        self.callback = callback
    
    def __lt__(self, other):
        return self.when < other.when
```

### Real Event Loop (asyncio's SelectorEventLoop)

```python
import asyncio
import selectors
import socket

# ── asyncio uses different event loop implementations ──────

# Linux:   asyncio.SelectorEventLoop  (epoll)
# macOS:   asyncio.SelectorEventLoop  (kqueue)
# Windows: asyncio.ProactorEventLoop  (IOCP)
# Third-party: uvloop (libuv — 2-3x faster)

# ── Internals: how add_reader works ───────────────────────
loop = asyncio.get_event_loop()

def add_reader_demo():
    """Simulate how the event loop registers file descriptors"""
    
    sock = socket.socket()
    sock.setblocking(False)
    
    def on_readable():
        """Called when sock is readable"""
        data = sock.recv(1024)
        print(f"Received: {data}")
    
    # Internally, this registers with the selector:
    # self._selector.register(sock.fileno(), selectors.EVENT_READ, on_readable)
    loop.add_reader(sock.fileno(), on_readable)
    
    # The selector.select() call in the event loop
    # returns (key, mask) pairs where key.data == on_readable

# ── Running the event loop ─────────────────────────────────
def run_loop_manually():
    """What asyncio.run() does internally (simplified)"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create and schedule the main coroutine
        main_coro = main()
        loop.run_until_complete(main_coro)
    finally:
        try:
            # Cancel all remaining tasks
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()
```

### Event Loop Phases in Detail (CPython Source)

```python
# ── From cpython/Lib/asyncio/base_events.py ─────────────────
# The real event loop._run_once() has these phases:

def _run_once(self):
    """Run one iteration of the event loop (real asyncio code)"""
    
    # Phase 0: Calculate poll timeout
    timeout = None
    if self._ready or self._stopping:
        timeout = 0  # Don't block if ready callbacks exist
    
    if timeout is None and self._scheduled:
        # Compute timeout until next scheduled callback
        when = self._scheduled[0]._when
        timeout = max(0, when - self.time())
    
    # Phase 1: Event blocking poll (select / epoll / kqueue)
    event_list = self._selector.select(timeout)
    self._process_events(event_list)
    
    # Phase 2: Move scheduled callbacks that are due to _ready
    end_time = self.time() + self._clock_resolution
    while self._scheduled:
        handle = self._scheduled[0]
        if handle._when >= end_time:
            break
        handle = heapq.heappop(self._scheduled)
        self._ready.append(handle)
    
    # Phase 3: Execute ready callbacks
    ntodo = len(self._ready)
    for _ in range(ntodo):
        handle = self._ready.popleft()
        if not handle._cancelled:
            handle._run()
```

### uvloop — 2x Faster Event Loop

```python
import uvloop
import asyncio

# ── uvloop replaces asyncio's selector with libuv ─────────
# libuv is the library that powers Node.js

# Key optimizations:
# 1. epoll/kqueue in C — no Python overhead per event
# 2. Timer management in C with binary heap
# 3. Async DNS in C via c-ares
# 4. Async file operations via thread pool
# 5. Async signal handling

# ── Setup ───────────────────────────────────────────────────
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Now all asyncio operations use libuv under the hood
async def main():
    # ~2-3x throughput improvement for I/O-bound workloads
    # ~50% latency reduction at p99
    await asyncio.sleep(1)

asyncio.run(main())

# ── Benchmark comparison ────────────────────────────────────
# With default event loop:
#   10,000 concurrent requests: 1500 req/s
#   p99 latency: 45ms
#
# With uvloop:
#   10,000 concurrent requests: 4500 req/s
#   p99 latency: 18ms
```

---

## 4. Running & Managing the Event Loop

### `asyncio.run()` — The High-Level API

```python
import asyncio

# ── Preferred way to run async code (Python 3.7+) ──────────
# asyncio.run() does:
# 1. Creates a new event loop
# 2. Sets it as the current loop
# 3. Runs the coroutine until completion
# 4. Cancels remaining tasks
# 5. Shuts down async generators
# 6. Closes the loop

async def main():
    await asyncio.sleep(1)
    return "done"

result = asyncio.run(main())
print(result)  # "done"

# ── Important: asyncio.run() cannot be called from a running loop ──
# asyncio.run(asyncio.run(main()))  # ❌ RuntimeError!

# ── Create a new loop manually (for testing / embedding) ───
async def test():
    await asyncio.sleep(0.1)
    return 42

loop = asyncio.new_event_loop()
try:
    result = loop.run_until_complete(test())
    print(result)  # 42
finally:
    loop.close()
```

### Low-Level Loop Control

```python
import asyncio

# ── Getting the current loop ───────────────────────────────
loop = asyncio.get_event_loop()        # Deprecated in 3.12
loop = asyncio.get_running_loop()      # ✅ Preferred (raises if no loop)

# ── Scheduling callbacks ───────────────────────────────────
loop = asyncio.get_running_loop()

# Call 'soon' — next iteration of event loop
loop.call_soon(lambda: print("Soon!"))

# Call 'later' — after delay
loop.call_later(1.0, lambda: print("1 second later"))

# Call 'at' — at specific time
loop.call_at(loop.time() + 2.0, lambda: print("2 seconds later"))

# ── Running in executor (for blocking code) ────────────────
import time
from concurrent.futures import ThreadPoolExecutor

async def run_blocking():
    loop = asyncio.get_running_loop()
    
    # Run in default ThreadPoolExecutor
    result = await loop.run_in_executor(
        None,  # Default executor
        time.sleep, 1.0  # Blocks thread, NOT event loop
    )
    
    # Run in custom executor
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = await loop.run_in_executor(
            pool,
            cpu_intensive_function, data
        )
    
    # Run in ProcessPoolExecutor (for CPU-bound)
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool,
            cpu_bound_function, large_data
        )

# ── Stopping the loop ──────────────────────────────────────
loop.stop()          # Stop at next iteration
loop.is_running()    # Check if loop is running
loop.is_closed()     # Check if loop is closed
```

### Debug Mode

```python
import asyncio

# ── Enable debug mode ──────────────────────────────────────
# asyncio.run(main(), debug=True)
# Or: PYTHONASYNCIODEBUG=1 python script.py

# Debug mode provides:
# 1. Slow callback warnings (>100ms)
# 2. Resource warnings (unclosed transports)
# 3. Coroutine was never awaited warnings
# 4. Stack traces for scheduled callbacks

async def slow_callback():
    """This will trigger a warning in debug mode"""
    loop = asyncio.get_running_loop()
    loop.call_later(0.2, lambda: time.sleep(0.5))  # Blocking the loop!
    await asyncio.sleep(0)

# ── Custom slow callback duration ──────────────────────────
# loop.slow_callback_duration = 0.05  # 50ms threshold
```

---

## 5. Coroutines Deep Dive

### Creating and Awaiting Coroutines

```python
import asyncio

# ── Defining coroutines ────────────────────────────────────
async def simple_coro():
    """An async function returns a coroutine object when called"""
    return 42

# When called, NO code runs yet:
coro = simple_coro()
print(type(coro))                    # <class 'coroutine'>
print(asyncio.iscoroutine(coro))     # True

# ── Awaiting coroutines ────────────────────────────────────
async def main():
    # Await runs the coroutine and gets the result
    result = await simple_coro()
    print(result)  # 42
    
    # Without await, you get a warning:
    simple_coro()  # ❌ RuntimeWarning: coroutine was never awaited

# ── Coroutine introspection ────────────────────────────────
import inspect

async def sample(a, b):
    await asyncio.sleep(0)
    return a + b

coro = sample(1, 2)
print(inspect.iscoroutine(coro))             # True
print(inspect.iscoroutinefunction(sample))   # True
print(coro.cr_code)                          # Code object
print(coro.cr_frame)                         # Current frame (or None)
```

### Coroutine Lifecycle

```python
import asyncio

# ── The lifecycle of a coroutine ───────────────────────────
async def lifecycle_demo():
    """States a coroutine passes through"""
    print("1. Coroutine started execution")
    
    await asyncio.sleep(0)
    print("2. Coroutine resumed after first suspension")
    
    await asyncio.sleep(0)
    print("3. Coroutine resumed after second suspension")
    
    return "completed"

# ── Tracking coroutine state ───────────────────────────────
async def track_state():
    coro = lifecycle_demo()
    
    # State before any execution:
    print(f"cr_await: {coro.cr_await}")  # What it's currently awaiting
    print(f"cr_frame: {coro.cr_frame}")  # Execution frame (None before start)
    print(f"cr_running: {coro.cr_running}")  # False
    
    result = await coro
    print(f"Result: {result}")  # "completed"
    
    # After completion, coroutine is exhausted:
    # await coro  # ❌ RuntimeError: cannot reuse already awaited coroutine
```

### The Coroutine as a Generator

```python
import asyncio

# ── Coroutines are built on generators ─────────────────────
# This is the historical foundation:

def generator_coroutine():
    """A coroutine implemented with a generator (pre-3.5 style)"""
    print("Step 1")
    value = yield from asyncio.sleep(1).__await__()  # Suspends
    print(f"Step 2: got {value}")
    return "done"

# ── You can drive a coroutine like a generator ─────────────
async def inspect_coroutine():
    """See what happens inside the coroutine"""
    coro = simple_inner()
    
    # Send None to start:
    try:
        future = coro.send(None)
        print(f"YIELDED: {future}")  # <Future pending>
        print(f"Future type: {type(future).__name__}")
        
        # Complete the future
        future.set_result(None)
        
        # Resume
        try:
            result = coro.send(None)
            print(f"RESUMED: got {result}")
        except StopIteration as e:
            print(f"DONE: {e.value}")
    except StopIteration as e:
        print(f"DONE immediately: {e.value}")

async def simple_inner():
    await asyncio.sleep(0)
    return "hello"
```

### Nested Coroutines and Await Chains

```python
import asyncio

# ── Await chain ────────────────────────────────────────────
async def level3():
    await asyncio.sleep(0.1)
    return "level3"

async def level2():
    result = await level3()
    return f"level2({result})"

async def level1():
    result = await level2()
    return f"level1({result})"

async def main():
    final = await level1()
    print(final)  # "level1(level2(level3))"
    
    # Under the hood, the await chain creates a stack of
    # coroutines, each awaiting the next. The event loop
    # drives the topmost coroutine, which drives the next, etc.

# ── The importance of staying async ────────────────────────
async def wrong_way():
    """Mixing sync blocking code breaks async"""
    import time
    time.sleep(5)  # ❌ BLOCKS the entire event loop!
    return "done"

async def correct_way():
    """Use asyncio.sleep instead of time.sleep"""
    await asyncio.sleep(5)  # ✅ Releases event loop
    return "done"
```

---

## 6. Tasks & Futures

### Tasks — Running Coroutines Concurrently

```python
import asyncio

# ── Creating tasks ─────────────────────────────────────────
async def background_work(name: str, delay: float):
    await asyncio.sleep(delay)
    print(f"Task {name} completed after {delay}s")
    return f"{name}_result"

async def main():
    # create_task schedules the coroutine on the event loop
    # The task starts running immediately (when loop gets to it)
    task1 = asyncio.create_task(background_work("A", 2.0))
    task2 = asyncio.create_task(background_work("B", 1.0))
    
    print("Both tasks created — they're running in background")
    
    # Wait for both to complete
    result1 = await task1  # ~2s
    result2 = await task2  # Already done after 1s
    print(f"Results: {result1}, {result2}")

asyncio.run(main())
# Output:
# Both tasks created — they're running in background
# Task B completed after 1s
# Task A completed after 2s
# Results: A_result, B_result
```

### Task States and Properties

```python
import asyncio

# ── Task introspection ─────────────────────────────────────
async def task_lifecycle():
    task = asyncio.create_task(sample_work())
    
    # Before awaiting:
    print(f"Done: {task.done()}")        # False
    print(f"Cancelled: {task.cancelled()}")  # False
    print(f"Name: {task.get_name()}")    # Task-1 (auto-named)
    print(f"Coroutine: {task.get_coro()}")  # <coroutine object>
    
    # Set custom name (useful for debugging)
    task.set_name("my-background-task")
    
    # Wait for completion
    try:
        result = await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        print("Task timed out!")
    
    # After completion:
    print(f"Done: {task.done()}")        # True
    print(f"Result: {task.result()}")    # The return value (or raises exception)

async def sample_work():
    await asyncio.sleep(0.5)
    return 42
```

### `asyncio.gather()` — Concurrent Execution

```python
import asyncio

# ── Basic gather ───────────────────────────────────────────
async def fetch_url(url: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"Data from {url}"

async def main():
    # gather runs all awaitables concurrently
    # Returns results in the same order
    results = await asyncio.gather(
        fetch_url("A", 2.0),
        fetch_url("B", 1.0),
        fetch_url("C", 0.5),
    )
    print(results)  # ['Data from A', 'Data from B', 'Data from C']
    # Total time: ~2s (the longest), not 3.5s

# ── Gather with return_exceptions ──────────────────────────
async def failing_task():
    await asyncio.sleep(0.5)
    raise ValueError("Something went wrong")

async def safe_gather():
    results = await asyncio.gather(
        fetch_url("A", 1.0),
        failing_task(),
        fetch_url("B", 0.5),
        return_exceptions=True,  # Don't raise, return exceptions
    )
    for r in results:
        if isinstance(r, Exception):
            print(f"Task failed: {r}")
        else:
            print(f"Task succeeded: {r}")

# ── The hidden cost of gather() ────────────────────────────
async def gather_problem():
    """gather() waits for ALL tasks to complete, even on error"""
    results = await asyncio.gather(
        fast_fail(),   # Takes 0.5s, then fails
        slow_work(),   # Takes 5s — still runs to completion!
        return_exceptions=True,
    )
    # You waited 5s even though you could have failed fast!

# Better: use TaskGroup or as_completed
```

### `asyncio.wait()` — Fine-Grained Control

```python
import asyncio

# ── wait() gives you more control ──────────────────────────
async def controlled_wait():
    tasks = [
        asyncio.create_task(fetch_url("A", 2.0)),
        asyncio.create_task(fetch_url("B", 1.0)),
        asyncio.create_task(fetch_url("C", 3.0)),
    ]
    
    # Wait for FIRST to complete
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )
    print(f"Done: {len(done)}, Pending: {len(pending)}")
    
    # Cancel remaining
    for task in pending:
        task.cancel()
    
    # Other modes:
    # FIRST_EXCEPTION: Return when first task raises
    # ALL_COMPLETED: Return when all done (default)

# ── as_completed — iterate as tasks finish ─────────────────
async def process_as_completed():
    tasks = [
        fetch_url("A", 3.0),
        fetch_url("B", 1.0),
        fetch_url("C", 2.0),
    ]
    
    for coro in asyncio.as_completed(tasks):
        result = await coro
        # Process each result as soon as it's ready
        print(f"Got: {result}")
    # Output order: B, C, A

# ── wait_for — timeout wrapper ─────────────────────────────
async def with_timeout():
    try:
        result = await asyncio.wait_for(
            fetch_url("A", 10.0),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        print("Task timed out!")
        # The task is automatically cancelled
```

### TaskGroup — Structured Concurrency (3.11+)

```python
import asyncio

# ── TaskGroup: proper scoping and cancellation ─────────────
async def handle_client(client_id: int):
    """All tasks are properly scoped — no orphaned tasks"""
    try:
        async with asyncio.TaskGroup() as tg:
            # If any task fails, ALL siblings are cancelled
            task1 = tg.create_task(fetch_metadata(client_id))
            task2 = tg.create_task(fetch_history(client_id))
            task3 = tg.create_task(fetch_preferences(client_id))
        
        # All tasks completed successfully here
        return merge_results(
            task1.result(),
            task2.result(),
            task3.result(),
        )
    except* asyncio.CancelledError:
        print("TaskGroup was cancelled — cleaning up")
        await cleanup(client_id)
        raise
    except* Exception as e:
        print(f"TaskGroup failed with: {e}")
        # Other tasks are cancelled automatically
        raise

async def fetch_metadata(client_id: int) -> dict:
    await asyncio.sleep(1)
    if client_id == 0:
        raise ValueError("Invalid client")
    return {"id": client_id, "name": "Alice"}

async def fetch_history(client_id: int) -> list:
    await asyncio.sleep(2)
    return [{"order": 1}, {"order": 2}]

async def fetch_preferences(client_id: int) -> dict:
    await asyncio.sleep(1.5)
    return {"theme": "dark", "language": "en"}

# ── ExceptionGroup and except* ─────────────────────────────
# TaskGroup raises ExceptionGroup which bundles all exceptions
# Use except* (PEP 654, Python 3.11+) to handle by type:

async def handle_exception_group():
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(failing_a())
            tg.create_task(failing_b())
    except* ValueError as eg:
        print(f"ValueErrors: {eg.exceptions}")
    except* TypeError as eg:
        print(f"TypeErrors: {eg.exceptions}")

async def failing_a():
    await asyncio.sleep(0.1)
    raise ValueError("A failed")

async def failing_b():
    await asyncio.sleep(0.1)
    raise TypeError("B failed")
```

### Futures — Low-Level Awaitables

```python
import asyncio

# ── Future: an eventual result ─────────────────────────────
# Futures are the low-level building blocks.
# Tasks ARE Futures (Task inherits from Future).
# You rarely use Future directly in application code.

async def future_demo():
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    # Schedule completion in background
    loop.call_later(1.0, future.set_result, "Future result!")
    
    # Await the future (blocks until completed)
    result = await future
    print(result)  # "Future result!"

# ── Future callbacks ───────────────────────────────────────
async def future_callbacks():
    future = asyncio.get_running_loop().create_future()
    
    def on_done(fut):
        print(f"Future done: {fut.result()}")
    
    def on_cancelled(fut):
        print("Future was cancelled")
    
    future.add_done_callback(on_done)
    # future.add_done_callback(on_cancelled)  # Would also fire
    
    loop.call_later(0.5, future.set_result, 42)
    result = await future

# ── Wrapping callback-based code with Future ───────────────
def async_wrap_callback():
    """Convert callback-based function to awaitable"""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    
    def callback(result):
        loop.call_soon_threadsafe(future.set_result, result)
    
    # Start callback-based operation
    some_callback_api(callback)
    
    return future

# Usage:
# result = await async_wrap_callback()
```

---

## 7. Synchronization Primitives

### Lock

```python
import asyncio

# ── asyncio.Lock — NOT thread-safe, coroutine-safe ────────
# Unlike threading.Lock, asyncio.Lock is awaitable:
# await lock.acquire() instead of lock.acquire()

async def lock_demo():
    lock = asyncio.Lock()
    shared_resource = []
    
    async def worker(name: str):
        async with lock:  # Only one coroutine at a time
            print(f"{name}: acquired lock")
            shared_resource.append(name)
            await asyncio.sleep(0.5)  # Holds lock during await!
            print(f"{name}: releasing lock")
    
    # Create 3 concurrent workers
    await asyncio.gather(
        worker("A"),
        worker("B"),
        worker("C"),
    )
    # A, B, C execute sequentially (one at a time)

# ── The critical insight: lock is held ACROSS await ────────
# This is different from threading where you should
# minimize lock-held time. In asyncio, locks are held
# across suspension points — but this means other
# coroutines that need the lock are blocked.

# ── Lock with timeout ─────────────────────────────────────
async def lock_with_timeout():
    lock = asyncio.Lock()
    
    try:
        await asyncio.wait_for(lock.acquire(), timeout=1.0)
        try:
            # Critical section
            pass
        finally:
            lock.release()
    except asyncio.TimeoutError:
        print("Could not acquire lock within 1 second")
```

### RLock (Reentrant Lock)

```python
import asyncio

# ── asyncio.RLock — coroutine can acquire multiple times ───
# Same thread concerns as threading.RLock

class AsyncCounter:
    def __init__(self):
        self._lock = asyncio.RLock()
        self._value = 0
    
    async def increment(self):
        async with self._lock:
            self._value += 1
    
    async def increment_by(self, n: int):
        async with self._lock:
            for _ in range(n):
                await self.increment()  # Same coroutine re-acquires
    
    async def get_and_increment(self):
        async with self._lock:
            value = self._value
            await self.increment()
            return value

# Usage:
async def rlock_demo():
    counter = AsyncCounter()
    await counter.increment_by(5)
    result = await counter.get_and_increment()
    print(result)  # 5 (incremented to 6)
```

### Semaphore

```python
import asyncio

# ── Semaphore: limit concurrent access ─────────────────────
async def semaphore_demo():
    sem = asyncio.Semaphore(3)  # Max 3 concurrent coroutines
    
    async def worker(name: str, delay: float):
        async with sem:
            print(f"{name}: started")
            await asyncio.sleep(delay)
            print(f"{name}: finished")
    
    # Creates 10 workers, but only 3 run at a time
    await asyncio.gather(*[
        worker(f"W{i}", 1.0) for i in range(10)
    ])
    # Total time: ~4s (10 workers / 3 at a time * 1s each)

# ── BoundedSemaphore ───────────────────────────────────────
# Like Semaphore but raises ValueError if released too many times
bounded_sem = asyncio.BoundedSemaphore(3)

# ── Practical: Rate-limited API client ─────────────────────
class RateLimiter:
    """Limit concurrent API calls"""
    
    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max_concurrent)
    
    async def call_api(self, url: str) -> dict:
        async with self._sem:
            return await make_request(url)

# Usage:
# limiter = RateLimiter(10)
# results = await asyncio.gather(*[
#     limiter.call_api(url) for url in urls
# ])
```

### Event

```python
import asyncio

# ── asyncio.Event — signal between coroutines ──────────────
# One coroutine sets the event, others wait for it

async def event_demo():
    start_event = asyncio.Event()
    data_ready = asyncio.Event()
    shutdown_event = asyncio.Event()
    
    async def worker(name: str):
        print(f"Worker {name}: waiting for start")
        await start_event.wait()  # Block until set
        print(f"Worker {name}: started!")
        
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    data_ready.wait(),
                    timeout=1.0,
                )
                if data_ready.is_set():
                    print(f"Worker {name}: processing data")
                    data_ready.clear()
            except asyncio.TimeoutError:
                pass
        
        print(f"Worker {name}: shutting down")
    
    # Start workers
    workers = [
        asyncio.create_task(worker("A")),
        asyncio.create_task(worker("B")),
    ]
    
    await asyncio.sleep(0.1)
    
    # Signal all workers to start
    print("Main: setting start event")
    start_event.set()
    
    await asyncio.sleep(0.1)
    
    # Signal data available
    print("Main: data ready")
    data_ready.set()
    
    await asyncio.sleep(0.1)
    
    # Shutdown
    print("Main: shutting down")
    shutdown_event.set()
    
    await asyncio.gather(*workers)

# ── Event vs Condition ────────────────────────────────────
# Event: simple on/off signaling (pulse)
# Condition: complex state-dependent waiting (data availability)
```

### Condition

```python
import asyncio

# ── Condition: wait for complex state changes ──────────────
class AsyncBoundedBuffer:
    """Async producer-consumer with Condition"""
    
    def __init__(self, maxsize: int = 10):
        self._buffer = []
        self._maxsize = maxsize
        self._cond = asyncio.Condition()
    
    async def put(self, item):
        async with self._cond:
            while len(self._buffer) >= self._maxsize:
                # Wait until space available
                # Releases lock, re-acquires before return
                await self._cond.wait()
            
            self._buffer.append(item)
            self._cond.notify()  # Wake one consumer
    
    async def get(self):
        async with self._cond:
            while not self._buffer:
                await self._cond.wait()  # Wait until data available
            
            item = self._buffer.pop(0)
            self._cond.notify()  # Wake one producer
            return item
    
    async def put_many(self, items):
        async with self._cond:
            for item in items:
                while len(self._buffer) >= self._maxsize:
                    await self._cond.wait()
                self._buffer.append(item)
            self._cond.notify_all()  # Wake ALL consumers

# Usage:
async def condition_demo():
    buffer = AsyncBoundedBuffer(5)
    
    async def producer():
        for i in range(20):
            await buffer.put(f"item-{i}")
            await asyncio.sleep(0.05)
    
    async def consumer(name: str):
        for _ in range(10):
            item = await buffer.get()
            print(f"{name} got {item}")
            await asyncio.sleep(0.1)
    
    await asyncio.gather(
        producer(),
        consumer("C1"),
        consumer("C2"),
    )
```

### Barrier

```python
import asyncio

# ── Barrier: synchronize N coroutines at a point ───────────
async def barrier_demo():
    barrier = asyncio.Barrier(3)  # 3 coroutines must sync
    
    async def worker(name: str, delay: float):
        print(f"{name}: phase 1 starting")
        await asyncio.sleep(delay)
        print(f"{name}: phase 1 done, waiting at barrier")
        
        await barrier.wait()  # Blocks until all 3 arrive
        
        print(f"{name}: phase 2 starting (all synced!)")
        await asyncio.sleep(0.5)
        print(f"{name}: phase 2 done")
    
    await asyncio.gather(
        worker("A", 1.0),
        worker("B", 0.5),
        worker("C", 0.1),
    )
    # Output order:
    # A: phase 1 starting
    # B: phase 1 starting
    # C: phase 1 starting
    # C: phase 1 done, waiting    (fastest)
    # B: phase 1 done, waiting
    # A: phase 1 done, waiting    (slowest — all synced here!)
    # A: phase 2 starting (all synced!)
    # B: phase 2 starting (all synced!)
    # C: phase 2 starting (all synced!)
```

### Queue

```python
import asyncio
import random

# ── asyncio.Queue — async-safe FIFO ────────────────────────
async def queue_demo():
    queue = asyncio.Queue(maxsize=10)
    
    async def producer():
        for i in range(20):
            item = f"item-{i}"
            await queue.put(item)  # Blocks if full
            print(f"Produced: {item}")
            await asyncio.sleep(random.uniform(0.05, 0.15))
        await queue.put(None)  # Sentinel
    
    async def consumer(name: str):
        while True:
            item = await queue.get()  # Blocks if empty
            if item is None:
                queue.task_done()
                break
            print(f"{name} consumed: {item}")
            await asyncio.sleep(random.uniform(0.1, 0.2))
            queue.task_done()
    
    # Run producer and two consumers
    await asyncio.gather(
        producer(),
        consumer("C1"),
        consumer("C2"),
    )
    
    await queue.join()  # Wait until all items processed
    print("All items processed!")

# ── Queue variants ─────────────────────────────────────────
q = asyncio.Queue(maxsize=100)          # FIFO
q = asyncio.LifoQueue(maxsize=100)      # LIFO (stack)
q = asyncio.PriorityQueue(maxsize=100)  # Priority (min-heap)

# ── Queue methods ──────────────────────────────────────────
await q.put(item)        # Block if full
await q.get()            # Block if empty
q.put_nowait(item)       # Raise asyncio.QueueFull if full
q.get_nowait()           # Raise asyncio.QueueEmpty if empty
q.qsize()                # Approximate size
q.empty()                # True if empty
q.full()                 # True if full
q.join()                 # Block until all items processed
q.task_done()            # Signal item processed
```

---

## 8. Async Generators & Async Context Managers

### Async Generators

```python
import asyncio
from collections.abc import AsyncGenerator

# ── Defining async generators ──────────────────────────────
async def countdown(name: str, start: int) -> AsyncGenerator[str, None]:
    """Async generator that yields values asynchronously"""
    for i in range(start, 0, -1):
        await asyncio.sleep(0.5)  # Non-blocking wait between yields
        yield f"{name}: {i}"
    yield f"{name}: launch!"

# ── Consuming async generators ─────────────────────────────
async def consume_generator():
    async for msg in countdown("Rocket", 3):
        print(msg)
    # Output (with 0.5s intervals):
    # Rocket: 3
    # Rocket: 2
    # Rocket: 1
    # Rocket: launch!

# ── Sending values into async generators ───────────────────
async def echo() -> AsyncGenerator[str, str]:
    """Async generator that receives values via asend()"""
    received = await asyncio.sleep(0)  # Initial suspension
    try:
        while True:
            received = yield f"Echo: {received}"
    except asyncio.CancelledError:
        yield "Goodbye!"

# ── Async generator cleanup ────────────────────────────────
async def cleanup_demo():
    async def resource_generator():
        """Async generator that holds a resource"""
        conn = await acquire_connection()
        try:
            while True:
                data = await conn.fetch()
                if not data:
                    return
                yield data
        finally:
            await conn.close()  # ← Always called, even on cancellation!
    
    # When consumer breaks or raises:
    async for data in resource_generator():
        if condition(data):
            break  # → aclose() is called → finally runs
    
    # Or explicitly:
    gen = resource_generator()
    await gen.asend(None)  # Start
    await gen.aclose()     # Clean close (runs finally)
```

### Async Generator Internals

```python
import asyncio

# ── What async generators compile to ───────────────────────
# Async generators implement:
# - __aiter__ → returns self
# - __anext__ → returns awaitable that advances the generator
# - asend()  → send value into generator (like .send())
# - athrow() → throw exception into generator
# - aclose() → close generator (runs finally blocks)

async def async_gen_internals():
    async def simple_gen():
        yield 1
        yield 2
        return 3  # Not accessible via async for
    
    gen = simple_gen()
    
    # Manual driving:
    print(await gen.__anext__())  # 1
    print(await gen.__anext__())  # 2
    
    try:
        await gen.__anext__()  # Raises StopAsyncIteration
    except StopAsyncIteration:
        print("Generator exhausted")
    
    # Or use aclose for cleanup:
    await gen.aclose()

# ── Async generator and asend ──────────────────────────────
async def asend_demo():
    """Use asend to send values into an async generator"""
    
    async def accumulator():
        total = 0
        value = yield total  # Initial yield, receives first send
        while True:
            total += value
            value = yield total
    
    gen = accumulator()
    
    # Must advance to first yield first (like send(None) for generators)
    await gen.asend(None)  # Start → yields 0
    
    print(await gen.asend(10))  # total=10
    print(await gen.asend(5))   # total=15
    print(await gen.asend(3))   # total=18
    
    await gen.aclose()
```

### Async Context Managers

```python
import asyncio
from contextlib import asynccontextmanager

# ── Defining async context managers ────────────────────────

# Method 1: Class with __aenter__ and __aexit__
class AsyncConnection:
    """Async context manager with clean resource management"""
    
    async def __aenter__(self):
        print("Acquiring connection...")
        self.conn = await create_connection()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("Releasing connection...")
        await self.conn.close()
        return False  # Don't suppress exceptions
    
    async def query(self, sql: str):
        return await self.conn.execute(sql)

# Method 2: Decorator with @asynccontextmanager
@asynccontextmanager
async def open_db(host: str, port: int):
    """Cleaner syntax for async context managers"""
    conn = await create_connection(host, port)
    try:
        yield conn
    finally:
        await conn.close()

# ── Usage ──────────────────────────────────────────────────
async def context_manager_demo():
    # Using class-based
    async with AsyncConnection() as conn:
        result = await conn.query("SELECT 1")
        print(result)
    # Connection is closed here (even if query raises)
    
    # Using decorator-based
    async with open_db("localhost", 5432) as conn:
        result = await conn.query("SELECT 2")
        print(result)

# ── Async ExitStack ───────────────────────────────────────
from contextlib import AsyncExitStack

async def manage_multiple():
    """Manage multiple async context managers dynamically"""
    async with AsyncExitStack() as stack:
        # Open resources as needed
        conn1 = await stack.enter_async_context(open_db("host1", 5432))
        conn2 = await stack.enter_async_context(open_db("host2", 5432))
        
        # Push custom cleanup callbacks
        stack.push_async_callback(lambda: print("Custom cleanup"))
        
        # All close in reverse order on exit
        results = await asyncio.gather(
            conn1.query("SELECT 1"),
            conn2.query("SELECT 2"),
        )
        print(results)
```

---

## 9. Streams, Subprocesses & Networking

### Async Streams (TCP)

```python
import asyncio

# ── TCP Echo Server ────────────────────────────────────────
async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single TCP connection"""
    addr = writer.get_extra_info('peername')
    print(f"Connected: {addr}")
    
    try:
        while True:
            data = await reader.read(1024)  # Read up to 1024 bytes
            if not data:
                break  # EOF
            
            message = data.decode()
            print(f"Received: {message!r}")
            
            writer.write(data)  # Echo back
            await writer.drain()  # Wait for buffer to drain
        
        print(f"Disconnected: {addr}")
    except asyncio.CancelledError:
        print(f"Connection cancelled: {addr}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_server():
    server = await asyncio.start_server(
        handle_echo,
        host='127.0.0.1',
        port=8888,
    )
    
    addr = server.sockets[0].getsockname()
    print(f"Serving on {addr}")
    
    async with server:
        await server.serve_forever()

# ── TCP Client ─────────────────────────────────────────────
async def tcp_client():
    reader, writer = await asyncio.open_connection(
        '127.0.0.1', 8888
    )
    
    writer.write(b"Hello, Server!")
    await writer.drain()
    
    data = await reader.read(1024)
    print(f"Received: {data.decode()!r}")
    
    writer.close()
    await writer.wait_closed()
```

### Async Subprocesses

```python
import asyncio

# ── Running shell commands asynchronously ──────────────────
async def run_command(cmd: str, *args: str) -> tuple[int, str, str]:
    """Run a shell command and capture output"""
    process = await asyncio.create_subprocess_exec(
        cmd, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    
    return process.returncode, stdout.decode(), stderr.decode()

# ── Streaming subprocess output ────────────────────────────
async def stream_command_output():
    """Read command output line by line"""
    process = await asyncio.create_subprocess_exec(
        'ping', '-c', '5', 'google.com',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    # Stream stdout line by line
    async for line in process.stdout:
        print(f"[PING] {line.decode().strip()}")
    
    # Wait for completion
    await process.wait()
    print(f"Exit code: {process.returncode}")

# ── Running multiple commands concurrently ─────────────────
async def run_parallel_commands():
    """Run multiple shell commands in parallel"""
    commands = [
        ('python3', '-c', 'import time; time.sleep(1); print("A")'),
        ('python3', '-c', 'import time; time.sleep(2); print("B")'),
        ('python3', '-c', 'import time; time.sleep(0.5); print("C")'),
    ]
    
    async def run_one(cmd: tuple) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode, stdout.decode().strip()
    
    results = await asyncio.gather(*[run_one(cmd) for cmd in commands])
    for code, output in results:
        print(f"Exit: {code}, Output: {output}")
    # Output order: C, A, B (whatever finishes fastest)
```

### Async HTTP with aiohttp

```python
import asyncio
import aiohttp

# ── Basic async HTTP client ────────────────────────────────
async def fetch_url(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as response:
        return await response.json()

async def fetch_many():
    async with aiohttp.ClientSession() as session:
        urls = [
            "https://api.github.com/repos/python/cpython",
            "https://api.github.com/repos/python/asyncio",
            "https://api.github.com/repos/python/mypy",
        ]
        
        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        for result in results:
            print(f"{result['full_name']}: {result['stargazers_count']} stars")

# ── Rate-limited HTTP client ───────────────────────────────
from typing import Optional

class RateLimitedClient:
    """Async HTTP client with rate limiting"""
    
    def __init__(self, max_concurrent: int = 10, rate: float = 50):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._rate_limit = rate
        self._last_request = 0.0
        self._rate_lock = asyncio.Lock()
        # Use Optional for 3.7+ compatibility. PEP 604 (X | None)
        # requires Python 3.10+ or 'from __future__ import annotations'
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def get(self, url: str) -> dict:
        async with self._sem:
            await self._throttle()
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
    
    async def _throttle(self):
        async with self._rate_lock:
            now = asyncio.get_running_loop().time()
            wait = max(0, (1.0 / self._rate_limit) - (now - self._last_request))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = asyncio.get_running_loop().time()

# Usage:
# async with RateLimitedClient(max_concurrent=5, rate=10) as client:
#     results = await asyncio.gather(*[client.get(url) for url in urls])
```

---

## 10. Advanced Patterns

### Structured Concurrency with TaskGroup

```python
import asyncio

# ── TaskGroup (3.11+) — the gold standard ──────────────────
# Benefits over gather():
# 1. Automatic cancellation on failure
# 2. Proper exception handling with ExceptionGroup
# 3. No orphaned tasks

async def robust_service():
    """Service with proper structured concurrency"""
    try:
        async with asyncio.TaskGroup() as tg:
            # All tasks are children of the group
            tg.create_task(heartbeat())
            tg.create_task(request_handler())
            tg.create_task(metrics_collector())
        
        # If we get here, all tasks completed normally
        # (unusual for long-running service)
    except* asyncio.CancelledError:
        print("Service shutting down gracefully")
        await cleanup()
        raise
    except* Exception as e:
        print(f"Service failed: {e}")
        # Other tasks already cancelled
        raise

async def heartbeat():
    while True:
        await asyncio.sleep(5)
        print("Heartbeat: OK")

async def request_handler():
    # ... handles requests
    pass

async def metrics_collector():
    # ... collects metrics
    pass

# ── Timeout with TaskGroup ─────────────────────────────────
async def with_timeout_group():
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(work_that_might_hang())
            tg.create_task(work_that_might_fail())
        
        # If any task fails or the timeout triggers,
        # all remaining tasks are cancelled automatically
    except*:
        # Handle appropriately
        pass
```

### Timeout Patterns

```python
import asyncio

# ── asyncio.timeout (3.11+) — preferred way ────────────────
async def timeout_demo():
    try:
        # Context manager approach — cleanest
        async with asyncio.timeout(5.0):
            result = await slow_operation()
            print(result)
    except asyncio.TimeoutError:
        print("Operation timed out!")
        # The operation is cancelled automatically

# ── asyncio.wait_for (3.7+) — wraps a single awaitable ─────
async def wait_for_demo():
    try:
        result = await asyncio.wait_for(
            slow_operation(),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        print("Timed out!")
        # Task is cancelled automatically

# ── Per-iteration timeout ──────────────────────────────────
async def per_iteration_timeout():
    """Timeout each iteration separately, not the whole loop"""
    while True:
        try:
            async with asyncio.timeout(1.0):
                data = await fetch_next_batch()
                process(data)
        except asyncio.TimeoutError:
            print("Batch fetch timed out, moving on")
            continue

# ── Deadline-based (absolute time) ─────────────────────────
async def deadline_demo():
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0  # 10 seconds from now
    
    async with asyncio.timeout_at(deadline):
        await complex_operation()
```

### Cancellation Handling

```python
import asyncio

# ── Proper cancellation ────────────────────────────────────
async def cancellable_operation():
    """Operation that handles cancellation gracefully"""
    try:
        await asyncio.sleep(10)  # Will be cancelled
    except asyncio.CancelledError:
        # Clean up resources
        print("Operation cancelled! Cleaning up...")
        await cleanup_resources()
        
        # MUST re-raise unless you have very good reason
        # NOT re-raising is usually a bug
        raise  # ✅ Always re-raise CancelledError

# ── Shield from cancellation ───────────────────────────────
async def critical_section():
    """Shield a critical section from cancellation"""
    # This section will NOT be cancelled
    result = await asyncio.shield(finalize_transaction())
    return result

# ── Cancellation with cleanup ──────────────────────────────
async def handle_with_cleanup():
    """Ensure cleanup on cancellation"""
    resource = await acquire()
    try:
        await resource.process()
    except asyncio.CancelledError:
        # Cleanup on cancellation
        print("Cancelled, cleaning up...")
        await resource.rollback()
        raise  # Re-raise after cleanup
    finally:
        # Always release
        await resource.release()

# ── Cancellation scopes ────────────────────────────────────
async def cancellation_scopes():
    """Different levels of cancellation tolerance"""
    
    async def important_task():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            print("Important task cancelled! Cleaning up...")
            raise
    
    async def main():
        task = asyncio.create_task(important_task())
        await asyncio.sleep(1)
        task.cancel()  # Schedules CancelledError
        
        try:
            await task  # Actually delivers CancelledError
        except asyncio.CancelledError:
            print("Main: task was cancelled (expected)")
```

### Running Sync Code with AsyncIO

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# ── run_in_executor — bridge between sync and async ────────
async def bridge_sync_code():
    loop = asyncio.get_running_loop()
    
    # ── For I/O-bound sync code ──────────────────────────
    # Use ThreadPoolExecutor (default)
    result = await loop.run_in_executor(
        None,  # Default executor (ThreadPoolExecutor)
        requests.get, "https://api.example.com"
    )
    
    # ── For CPU-bound sync code ──────────────────────────
    # Use ProcessPoolExecutor for true parallelism
    with ProcessPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool,
            cpu_intensive_function, large_data
        )
    
    # ── Custom thread pool ──────────────────────────────
    with ThreadPoolExecutor(max_workers=10) as pool:
        tasks = [
            loop.run_in_executor(pool, fetch_url, url)
            for url in urls
        ]
        results = await asyncio.gather(*tasks)

# ── to_thread (3.9+) — simpler API ────────────────────────
async def to_thread_demo():
    # asyncio.to_thread runs in default thread pool
    result = await asyncio.to_thread(
        sync_blocking_function, arg1, arg2
    )
```

### Producer-Consumer Pipeline

```python
import asyncio

# ── Async producer-consumer pipeline ───────────────────────
class AsyncPipeline:
    """Multi-stage async pipeline"""
    
    def __init__(self, maxsize: int = 100):
        self._input = asyncio.Queue(maxsize)
        self._output = asyncio.Queue(maxsize)
        self._stop_event = asyncio.Event()
    
    async def produce(self, items):
        """Produce items into the pipeline"""
        for item in items:
            if self._stop_event.is_set():
                break
            await self._input.put(item)
        await self._input.put(None)  # Sentinel
    
    async def process(self, processor):
        """Process items from input to output"""
        while True:
            item = await self._input.get()
            if item is None:
                await self._output.put(None)
                self._input.task_done()
                break
            
            try:
                result = await processor(item)
                await self._output.put(result)
            except Exception as e:
                await self._output.put(e)
            finally:
                self._input.task_done()
    
    async def consume(self):
        """Consume processed items"""
        results = []
        while True:
            item = await self._output.get()
            if item is None:
                self._output.task_done()
                break
            results.append(item)
            self._output.task_done()
        return results

# Usage:
async def pipeline_demo():
    pipeline = AsyncPipeline()
    
    async def double(x: int) -> int:
        await asyncio.sleep(0.1)
        return x * 2
    
    results = await asyncio.gather(
        pipeline.produce(range(10)),
        pipeline.process(double),
        pipeline.consume(),
    )
    
    print(results[2])  # [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]
```

### Worker Pool Pattern

```python
import asyncio

# ── Worker pool ────────────────────────────────────────────
class WorkerPool:
    """Pool of async workers processing jobs from a queue"""
    
    def __init__(self, num_workers: int):
        self._queue = asyncio.Queue()
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(num_workers)
        ]
        self._num_workers = num_workers
    
    async def _worker(self, worker_id: int):
        """Individual worker loop"""
        while True:
            job = await self._queue.get()
            
            if job is None:  # Sentinel — shutdown
                self._queue.task_done()
                break
            
            try:
                await job['fn'](*job['args'], **job['kwargs'])
            except Exception as e:
                print(f"Worker {worker_id} error: {e}")
            finally:
                self._queue.task_done()
    
    async def submit(self, fn, *args, **kwargs):
        """Submit a job to the pool"""
        await self._queue.put({
            'fn': fn,
            'args': args,
            'kwargs': kwargs,
        })
    
    async def shutdown(self):
        """
        Gracefully shut down all workers.
        
        ⚠️ Order matters:
        1. Put N sentinel Nones into the queue (one per worker)
        2. queue.join() waits for ALL tasks (including sentinel processing
           via task_done()) to complete
        3. Only THEN gather workers — at this point workers have
           received their None sentinel, called task_done(), and broken
           out of their while loop
        
        The old order (gather THEN join) was WRONG because:
        - gather() waits for workers to finish
        - Workers finish by getting None and calling task_done()
        - But join() AFTER gather() may see workers already done
          and task_done() already called — which is fine for join()
          but semantically incorrect: you want to ensure all tasks
          are processed BEFORE declaring workers done
        """
        # 1. Signal all workers to shut down via sentinel
        for _ in range(self._num_workers):
            await self._queue.put(None)
        
        # 2. Wait for ALL queued items (including sentinels) to be processed
        await self._queue.join()
        
        # 3. Now workers have exited their loops — wait for task completion
        await asyncio.gather(*self._workers)

# Usage:
# pool = WorkerPool(4)
# for item in items:
#     await pool.submit(process_item, item)
# await pool.shutdown()
```

---

## 11. Performance Optimization

### Choosing the Right Event Loop

```python
import asyncio

# ── Default event loops by platform ────────────────────────
# Linux:   SelectorEventLoop (epoll) — good for most cases
# macOS:   SelectorEventLoop (kqueue) — good for most cases  
# Windows: ProactorEventLoop (IOCP) — best on Windows

# ── uvloop (libuv-based, 2-3x faster) ─────────────────────
import uvloop  # pip install uvloop

# Set globally:
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Or per run:
# asyncio.run(main())  # Now uses uvloop

# ── When uvloop shines ────────────────────────────────────
# 1. High-throughput network servers (thousands of RPS)
# 2. Microservices with many concurrent connections
# 3. WebSocket servers
# 4. Any I/O-bound workload with 1000+ concurrent tasks
```

### Optimizing Concurrent Tasks

```python
import asyncio

# ── Semaphore for limiting concurrency ─────────────────────
async def optimized_batch(urls: list[str], max_concurrent: int = 50):
    """Process URLs with controlled concurrency"""
    sem = asyncio.Semaphore(max_concurrent)
    
    async def fetch_with_sem(url: str):
        async with sem:
            return await fetch_url(url)
    
    # Process in batches — limits memory usage
    tasks = [fetch_with_sem(url) for url in urls]
    return await asyncio.gather(*tasks)

# ── Chunked processing for large datasets ──────────────────
async def chunked_processing(items: list, chunk_size: int = 100):
    """Process in chunks to avoid overwhelming resources"""
    results = []
    
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        chunk_results = await asyncio.gather(*[
            process_item(item) for item in chunk
        ])
        results.extend(chunk_results)
    
    return results

# ── Connection pooling ─────────────────────────────────────
import aiohttp
from typing import Optional

class ConnectionPool:
    """Reuse connections for performance"""
    
    def __init__(self):
        # aiohttp manages its own connection pool
        # Requires 'from typing import Optional' at module level (see imports)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,           # Max concurrent connections
                limit_per_host=10,   # Max per host
                ttl_dns_cache=300,   # DNS cache TTL
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ── DNS caching ────────────────────────────────────────────
import socket
import aiohttp

# Enable DNS caching (reduces DNS lookup overhead)
resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1"])
connector = aiohttp.TCPConnector(
    resolver=resolver,
    ttl_dns_cache=300,  # Cache DNS for 5 minutes
)
```

### Avoiding Common Performance Traps

```python
import asyncio

# ── ❌ BAD: Blocking the event loop ────────────────────────
async def bad():
    import time
    time.sleep(5)  # Blocks everything!
    return "done"

# ── ✅ GOOD: Using asyncio.sleep ──────────────────────────
async def good():
    await asyncio.sleep(5)  # Releases event loop
    return "done"

# ── ❌ BAD: CPU-bound work in async function ──────────────
async def bad_cpu_bound():
    result = 0
    for i in range(10_000_000):  # Blocks event loop for seconds
        result += i ** 2
    return result

# ── ✅ GOOD: Offloading to executor ───────────────────────
async def good_cpu_bound():
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,  # Default executor (thread pool)
        cpu_intensive_function, 10_000_000
    )
    return result

# ── ❌ BAD: Creating too many tasks at once ───────────────
async def bad_many_tasks():
    # Creates 100,000 tasks immediately — memory spike!
    tasks = [asyncio.create_task(light_work()) for _ in range(100_000)]
    return await asyncio.gather(*tasks)

# ── ✅ GOOD: Using a semaphore to limit ───────────────────
async def good_many_tasks():
    sem = asyncio.Semaphore(1000)
    
    async def limited_work():
        async with sem:
            return await light_work()
    
    tasks = [asyncio.create_task(limited_work()) for _ in range(100_000)]
    return await asyncio.gather(*tasks)

# ── ❌ BAD: Synchronous I/O library ──────────────────────
async def bad_http():
    import requests
    return requests.get("https://api.example.com")  # Blocks!

# ── ✅ GOOD: Async HTTP library ──────────────────────────
async def good_http():
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com") as resp:
            return await resp.json()
```

### Measuring Async Performance

```python
import asyncio
import time

# ── Simple benchmark ───────────────────────────────────────
async def benchmark_async(func, num_calls: int = 100):
    """Benchmark an async function"""
    start = time.perf_counter()
    
    tasks = [func() for _ in range(num_calls)]
    results = await asyncio.gather(*tasks)
    
    elapsed = time.perf_counter() - start
    throughput = num_calls / elapsed
    
    print(f"Total: {elapsed:.2f}s")
    print(f"Throughput: {throughput:.0f} calls/s")
    print(f"Avg latency: {elapsed / num_calls * 1000:.2f}ms")
    
    return results

# Usage:
# async def test_request():
#     async with aiohttp.ClientSession() as session:
#         async with session.get("http://localhost:8000") as resp:
#             return await resp.text()
#
# await benchmark_async(test_request, 1000)
```

---

## 12. Production Patterns

### Graceful Shutdown

```python
import asyncio
import signal

# ── Graceful shutdown handler ──────────────────────────────
class GracefulShutdown:
    """Handle graceful shutdown with signal handling"""
    
    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self._shutdown_event.wait()
    
    def trigger_shutdown(self):
        """Trigger shutdown from signal handler"""
        self._shutdown_event.set()
    
    async def register_task(self, coro):
        """Register a task for tracked lifecycle"""
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task
    
    async def shutdown(self):
        """Graceful shutdown with timeout"""
        print("Shutting down gracefully...")
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait with timeout
        await asyncio.wait(
            self._tasks,
            timeout=30.0,  # Force shutdown after 30s
        )
        
        # Shutdown async generators and executor
        loop = asyncio.get_running_loop()
        await loop.shutdown_asyncgens()
        await loop.shutdown_default_executor()
        
        print("Shutdown complete")

# ── Usage in production service ────────────────────────────
async def main_service():
    shutdown = GracefulShutdown()
    
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            shutdown.trigger_shutdown,
        )
    
    # Start service tasks
    await shutdown.register_task(handle_requests())
    await shutdown.register_task(health_check())
    await shutdown.register_task(metrics_collector())
    
    # Wait for shutdown signal
    await shutdown.wait_for_shutdown()
    
    # Graceful shutdown
    await shutdown.shutdown()
```

### Async Health Check

```python
import asyncio
import time

# ── Health check with timeout ──────────────────────────────
class HealthChecker:
    """Periodic health check with failure detection"""
    
    def __init__(self, check_interval: float = 5.0, timeout: float = 2.0):
        self._interval = check_interval
        self._timeout = timeout
        self._healthy = True
        self._last_check = 0.0
        self._failures = 0
        self._max_failures = 3
    
    async def run(self):
        """Run health checks periodically"""
        while True:
            await asyncio.sleep(self._interval)
            await self._check()
    
    async def _check(self):
        """Perform a single health check"""
        try:
            async with asyncio.timeout(self._timeout):
                # Check dependencies
                db_ok = await self._check_database()
                cache_ok = await self._check_cache()
                queue_ok = await self._check_queue()
                
                self._healthy = db_ok and cache_ok and queue_ok
                if self._healthy:
                    self._failures = 0
                else:
                    self._failures += 1
        except asyncio.TimeoutError:
            self._healthy = False
            self._failures += 1
        
        self._last_check = time.monotonic()
        
        if self._failures >= self._max_failures:
            await self._report_critical_failure()
    
    async def _check_database(self) -> bool:
        """Check database connectivity"""
        try:
            async with async_db_pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False
    
    async def _check_cache(self) -> bool:
        """Check cache connectivity"""
        # Implement cache check
        return True
    
    async def _check_queue(self) -> bool:
        """Check message queue connectivity"""
        return True
    
    async def _report_critical_failure(self):
        """Alert on repeated failures"""
        print("CRITICAL: Service unhealthy after 3 failed checks")
        # Send alert (PagerDuty, Slack, etc.)
```

### Async Retry Pattern

```python
import asyncio
from typing import TypeVar, Callable, Awaitable

T = TypeVar('T')

# ── Generic async retry decorator ──────────────────────────
async def retry(
    fn: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """Async retry with exponential backoff + jitter"""
    import random
    
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e
            
            if attempt == max_retries:
                raise  # Max retries exceeded
            
            # Exponential backoff with jitter
            delay = min(
                base_delay * (exponential_base ** attempt),
                max_delay,
            )
            jitter = random.uniform(0, delay * 0.1)
            total_delay = delay + jitter
            
            print(f"Attempt {attempt + 1} failed, retrying in {total_delay:.2f}s")
            await asyncio.sleep(total_delay)
    
    raise last_exception  # Shouldn't reach here

# Usage:
# result = await retry(
#     fetch_url, "https://api.example.com",
#     max_retries=3,
#     base_delay=0.5,
# )

# ── Retry decorator ────────────────────────────────────────
from functools import wraps

def async_retry(
    max_retries: int = 3,
    base_delay: float = 0.1,
    retryable_exceptions: tuple = (ConnectionError, TimeoutError),
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry(
                func, *args, **kwargs,
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=retryable_exceptions,
            )
        return wrapper
    return decorator

# Usage:
# @async_retry(max_retries=5, base_delay=1.0)
# async def fetch_with_retry(url: str) -> dict:
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url) as resp:
#             return await resp.json()
```

### Async Connection Pool

```python
import asyncio
from typing import Optional, TypeVar, Generic

T = TypeVar('T')

class AsyncConnectionPool(Generic[T]):
    """Generic async connection pool"""
    
    def __init__(
        self,
        factory,
        min_size: int = 2,
        max_size: int = 10,
        max_idle_time: float = 60.0,
    ):
        self._factory = factory
        self._min_size = min_size
        self._max_size = max_size
        self._max_idle_time = max_idle_time
        
        self._pool: asyncio.Queue[T] = asyncio.Queue()
        self._size = 0
        self._lock = asyncio.Lock()
        self._closed = False
    
    async def initialize(self):
        """Pre-create minimum connections"""
        for _ in range(self._min_size):
            conn = await self._factory()
            await self._pool.put(conn)
            self._size += 1
    
    async def acquire(self) -> T:
        """Get a connection from the pool"""
        if self._closed:
            raise RuntimeError("Pool is closed")
        
        try:
            # Try to get existing connection
            return await asyncio.wait_for(
                self._pool.get(),
                timeout=1.0,
            )
        except asyncio.TimeoutError:
            pass
        
        # Create new connection if under max
        async with self._lock:
            if self._size < self._max_size:
                conn = await self._factory()
                self._size += 1
                return conn
        
        # Wait for a connection to be returned
        return await self._pool.get()
    
    async def release(self, conn: T):
        """Return a connection to the pool"""
        if self._closed:
            # Pool closed, close the connection
            if hasattr(conn, 'close'):
                await conn.close()
            return
        
        await self._pool.put(conn)
    
    async def close(self):
        """Close all connections in the pool"""
        self._closed = True
        
        while not self._pool.empty():
            conn = await self._pool.get()
            if hasattr(conn, 'close'):
                await conn.close()
        
        self._size = 0

# ── Usage: Database connection pool ───────────────────────
# async def create_db_conn():
#     return await asyncpg.connect(
#         host="localhost",
#         port=5432,
#         user="app",
#         password="secret",
#         database="mydb",
#     )
# 
# pool = AsyncConnectionPool(create_db_conn, min_size=5, max_size=20)
# await pool.initialize()
# 
# conn = await pool.acquire()
# try:
#     result = await conn.fetch("SELECT * FROM users")
# finally:
#     await pool.release(conn)
```

---

## 13. Common Pitfalls & Debugging

### Pitfall 1: Blocking the Event Loop

```python
import asyncio

# ── ❌ What NOT to do ──────────────────────────────────────
async def blocking_the_loop():
    """Any synchronous blocking call stops ALL async tasks"""
    import time
    time.sleep(5)  # ❌ Event loop is BLOCKED for 5 seconds!
    
    # During this 5 seconds:
    # - No other tasks can run
    # - No I/O events are processed
    # - No timers fire
    # - No new connections are accepted

# ── ✅ What to do instead ─────────────────────────────────
async def non_blocking():
    await asyncio.sleep(5)  # ✅ Releases event loop
    # Or:
    await asyncio.to_thread(time.sleep, 5)  # ✅ Runs in thread pool

# ── Common blockers to watch for ───────────────────────────
# ❌ time.sleep(n)                         → await asyncio.sleep(n)
# ❌ requests.get(url)                     → await session.get(url) (aiohttp)
# ❌ subprocess.run(cmd)                   → await asyncio.create_subprocess_exec(cmd)
# ❌ open(file).read()                     → async with aiofiles.open(file) as f: await f.read()
# ❌ socket.recv(1024)                     → await asyncio.get_event_loop().sock_recv(sock, 1024)
# ❌ db.query("SELECT ...") (sync driver)  → await async_db.execute("SELECT ...")
# ❌ cpu_intensive()                       → await loop.run_in_executor(None, cpu_intensive)
```

### Pitfall 2: Forgotten `await`

```python
import asyncio

# ── ❌ Common mistake ──────────────────────────────────────
async def forgot_await():
    task = asyncio.create_task(background_work())
    # ❌ Forgot to await — task runs but result is lost
    # The function exits immediately
    print("Function done")  
    # RuntimeWarning: coroutine ... was never awaited

# ── ✅ Always await your coroutines ───────────────────────
async def correct_await():
    result = await some_work()  # ✅
    
    task = asyncio.create_task(background_work())
    await task  # ✅ Wait for task

# ── Debug: detect unawaited coroutines ─────────────────────
# Enable in production:
# PYTHONASYNCIODEBUG=1 python app.py
# Or:
# asyncio.run(main(), debug=True)

# This will warn about:
# 1. Coroutines that were never awaited
# 2. Callbacks that take too long (>100ms)
# 3. Resources that weren't properly closed
```

### Pitfall 3: Mixing Sync and Async Libraries

```python
import asyncio

# ── ❌ Mixing sync HTTP library in async code ──────────────
async def mixed_http():
    import requests  # ❌ Synchronous library
    
    # This BLOCKS the event loop for the entire HTTP request
    response = requests.get("https://api.example.com")
    return response.json()

# ── ✅ Use async-native libraries ─────────────────────────
async def pure_async_http():
    import aiohttp  # ✅ Async-native
    
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com") as resp:
            return await resp.json()

# ── Async-friendly library equivalents ─────────────────────
# requests            → aiohttp / httpx
# psycopg2            → asyncpg / aiopg
# redis-py            → aioredis / redis.asyncio (4.x+)
# boto3 (sync)        → aioboto3
# Flask               → FastAPI / Quart / Sanic
# Django ORM          → Database sync → use asyncio.to_thread
# SQLAlchemy          → SQLAlchemy 1.4+ (async support)
```

### Pitfall 4: Shared Mutable State

```python
import asyncio

# ── ❌ Race condition with shared state ────────────────────
shared_counter = 0

async def bad_increment():
    global shared_counter
    # This is NOT safe! Even with asyncio (single-threaded):
    # Two coroutines can be suspended between read and write
    temp = shared_counter  # Coroutine can suspend here
    await asyncio.sleep(0)  # ❌ Suspension point!
    shared_counter = temp + 1  # Another coroutine also wrote!

async def bad_demo():
    await asyncio.gather(*[bad_increment() for _ in range(100)])
    print(shared_counter)  # Likely < 100 (race!)

# ── ✅ Use asyncio.Lock ────────────────────────────────────
async def safe_increment(lock: asyncio.Lock):
    global shared_counter
    async with lock:
        temp = shared_counter
        await asyncio.sleep(0)  # Now safe — lock is held
        shared_counter = temp + 1

async def safe_demo():
    lock = asyncio.Lock()
    await asyncio.gather(*[safe_increment(lock) for _ in range(100)])
    print(shared_counter)  # 100 ✅

# ── Best practice: avoid shared mutable state ──────────────
# Use message passing (queues) instead of shared state
```

### Pitfall 5: Not Handling Cancellation

```python
import asyncio

# ── ❌ Cancellation that doesn't clean up ──────────────────
async def no_cleanup():
    conn = await connect_to_database()
    await conn.query("UPDATE ...")
    # If cancelled here, conn is never closed!
    await conn.close()

# ── ✅ Proper cleanup on cancellation ──────────────────────
async def proper_cleanup():
    conn = await connect_to_database()
    try:
        await conn.query("UPDATE ...")
    except asyncio.CancelledError:
        await conn.close()  # Clean up
        raise  # Must re-raise!
    else:
        await conn.close()  # Normal cleanup

# Even better: use async context manager:
async def best_cleanup():
    async with get_connection() as conn:
        await conn.query("UPDATE ...")
    # Always cleaned up

# ── ⚠️ CancelledError in Python 3.9+ ──────────────────────
# CancelledError is now a subclass of BaseException (not Exception)
# This means:
# except Exception: will NOT catch CancelledError
# You must catch asyncio.CancelledError explicitly (or BaseException)
```

### Debugging Tools

```python
import asyncio
import traceback

# ── 1. Enable debug mode ───────────────────────────────────
# asyncio.run(main(), debug=True)
# 
# This enables:
# - Slow callback warnings (>100ms)
# - Resource warnings (unclosed transports, connections)
# - "Coroutine was never awaited" warnings
# - Detailed stack traces for scheduled callbacks

# ── 2. Get running tasks ──────────────────────────────────
def dump_tasks():
    """Print all currently running async tasks"""
    for task in asyncio.all_tasks():
        coro = task.get_coro()
        name = task.get_name()
        done = task.done()
        cancelled = task.cancelled()
        
        print(f"Task: {name}")
        print(f"  Done: {done}")
        print(f"  Cancelled: {cancelled}")
        
        if not done and coro:
            print(f"  Coroutine: {coro}")
            print(f"  Frame:")
            traceback.print_stack(coro.cr_frame)
        print()

# ── 3. Task timeout debugging ──────────────────────────────
async def debug_timeout():
    """Add logging to track timeout issues"""
    try:
        async with asyncio.timeout(5.0) as cm:
            # When timeout is reached:
            # cm.expired() will be True
            # The wrapped coroutine is cancelled
            result = await slow_operation()
    except asyncio.TimeoutError:
        if cm.expired():
            print(f"Task timed out after 5 seconds")
            # Dump all running tasks for debugging
            dump_tasks()

# ── 4. Monitoring task execution ───────────────────────────
def monitor_task(task: asyncio.Task, name: str = ""):
    """Add callbacks to monitor task lifecycle"""
    def on_done(fut):
        if fut.cancelled():
            print(f"[{name}] Task cancelled")
        elif fut.exception():
            print(f"[{name}] Task failed: {fut.exception()}")
        else:
            print(f"[{name}] Task completed: {fut.result()}")
    
    task.add_done_callback(on_done)
    return task

# Usage:
# task = monitor_task(asyncio.create_task(some_work()), "Worker-1")
```

---

## 14. asyncio vs Threading vs Multiprocessing

### Decision Matrix

| Aspect | AsyncIO | Threading | Multiprocessing |
|--------|---------|-----------|-----------------|
| **Execution Model** | Cooperative (single thread) | Preemptive (OS threads) | Preemptive (OS processes) |
| **True Parallelism** | ❌ No (single thread) | ❌ No (GIL) | ✅ Yes (separate processes) |
| **Memory Overhead** | ~2KB per task | ~1MB per thread | ~50MB per process |
| **Task Switching** | At await points | Anywhere (OS) | Anywhere (OS) |
| **Shared State** | ✅ Safe (single thread) | ⚠️ Needs locks | ❌ Needs IPC |
| **Max Scale** | 100K+ tasks | ~1000 threads | ~100 processes |
| **Best For** | I/O-bound, many conns | I/O-bound, sync libs | CPU-bound |
| **CPU Work** | ❌ Blocks loop | ❌ GIL-bound | ✅ True parallel |
| **Learning Curve** | Medium | Low | Medium |
| **Debugging** | Medium | Hard | Hard |

### When to Choose Which

```python
# ── Choose asyncio when ────────────────────────────────────
# 1. You need 1000+ concurrent connections
# 2. You control the stack (can use async libraries)
# 3. You're building a network service (API, WebSocket, etc.)
# 4. You want to avoid thread-safety complexity
# 5. Most time is spent waiting on I/O

# ── Choose threading when ──────────────────────────────────
# 1. You have blocking I/O libraries (no async support)
# 2. Moderate concurrency (< 1000)
# 3. You need to integrate with synchronous code
# 4. Simple mental model is preferred
# 5. You're working with file I/O and disk access

# ── Choose multiprocessing when ────────────────────────────
# 1. You have CPU-bound computation
# 2. You need true parallelism (multiple cores)
# 3. Fault isolation is important (one crash ≠ all crash)
# 4. You're doing data processing / ETL
# 5. NumPy, Pandas, image processing, ML inference
```

### Hybrid Patterns

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# ── Pattern 1: asyncio + ThreadPoolExecutor ───────────────
# Best for async applications that need to call sync I/O libs

async def hybrid_io(database_urls: list[str]):
    """Async orchestrator with sync database calls"""
    loop = asyncio.get_running_loop()
    
    # Use thread pool for sync DB driver
    with ThreadPoolExecutor(max_workers=10) as pool:
        tasks = [
            loop.run_in_executor(pool, sync_db_query, url)
            for url in database_urls
        ]
        return await asyncio.gather(*tasks)

# ── Pattern 2: asyncio + ProcessPoolExecutor ──────────────
# Best for async applications with CPU-intensive subtasks

async def hybrid_cpu(data_chunks: list):
    """Async orchestrator with parallel CPU processing"""
    loop = asyncio.get_running_loop()
    
    with ProcessPoolExecutor(max_workers=4) as pool:
        # CPU-bound processing runs in parallel processes
        processed = await loop.run_in_executor(
            pool,
            cpu_intensive_batch, data_chunks
        )
        
        # I/O-bound result handling with asyncio
        results = await asyncio.gather(*[
            save_result(item) for item in processed
        ])
    
    return results

# ── Pattern 3: Threaded app with asyncio for I/O ─────────
# Best when main app is threaded but needs high-concurrency I/O

def threaded_with_async():
    """Run asyncio event loop in a separate thread"""
    import threading
    
    async def async_io_worker():
        """High-concurrency I/O work"""
        async with aiohttp.ClientSession() as session:
            tasks = [fetch(session, url) for url in urls]
            return await asyncio.gather(*tasks)
    
    def run_loop():
        """Run async I/O in a dedicated thread"""
        return asyncio.run(async_io_worker())
    
    # Start async I/O in background thread
    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    
    # Main thread continues with other work
    return thread
```

### Performance Comparison

```python
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# ── I/O-bound benchmark ────────────────────────────────────
TOTAL_REQUESTS = 1000

# Sync (sequential) — baseline
def sync_io():
    for _ in range(TOTAL_REQUESTS):
        time.sleep(0.01)  # Simulate I/O
    return "done"

# Threaded
def threaded_io():
    def work():
        time.sleep(0.01)
    
    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(lambda x: work(), range(TOTAL_REQUESTS)))

# Async
async def async_io():
    async def work():
        await asyncio.sleep(0.01)
    
    await asyncio.gather(*[work() for _ in range(TOTAL_REQUESTS)])

# ── CPU-bound benchmark ────────────────────────────────────
def cpu_work(n: int) -> int:
    """CPU-intensive work"""
    result = 0
    for i in range(n):
        result += i ** 2
    return result

# Sync (sequential)
def sync_cpu():
    for _ in range(10):
        cpu_work(5_000_000)

# Threaded (GIL-limited — no speedup)
def threaded_cpu():
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda x: cpu_work(5_000_000), range(10)))

# Multiprocessing (true parallel)
def multiprocess_cpu():
    from multiprocessing import Pool
    with Pool(processes=4) as pool:
        pool.map(cpu_work, [5_000_000] * 10)
```

---

## 15. Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the difference between a coroutine and a task in asyncio?</b></summary>

**Answer:** 
- **Coroutine**: An `async def` function. When called, it returns a coroutine object that hasn't started executing yet. You must `await` it or wrap it in a task to run it.
- **Task**: A coroutine wrapped by `asyncio.create_task()`. Tasks are scheduled on the event loop and run concurrently. They extend `Future` and provide features like cancellation, result retrieval, and status checking.

```python
async def my_coro():
    return 42

coro = my_coro()                    # Coroutine object (not running)
task = asyncio.create_task(my_coro())  # Task (scheduled on event loop)
result = await task                 # Get result: 42
```
</details>

<details>
<summary><b>Q2: How does `asyncio.run()` work?</b></summary>

**Answer:** `asyncio.run()` is the high-level entry point for running async code (added in Python 3.7). It:
1. Creates a new event loop
2. Sets it as the current event loop
3. Runs the provided coroutine until completion
4. Cancels any remaining tasks
5. Shuts down async generators and the default executor
6. Closes the event loop

```python
# Internally (simplified):
def run(main):
    loop = new_event_loop()
    try:
        set_event_loop(loop)
        return loop.run_until_complete(main)
    finally:
        # Cleanup
        try:
            for task in all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            set_event_loop(None)
            loop.close()
```
</details>

<details>
<summary><b>Q3: What is the difference between `asyncio.gather()` and `asyncio.wait()`?</b></summary>

**Answer:**
- **`gather()`**: Takes coroutines or awaitables, runs them concurrently, returns results in the same order. If one task raises, others continue (unless `return_exceptions=False`). Cannot control when to return.
- **`wait()`**: Takes a set of tasks/futures, returns `(done, pending)`. Supports `FIRST_COMPLETED`, `FIRST_EXCEPTION`, `ALL_COMPLETED` modes. Requires tasks (not raw coroutines).

```python
# gather — ordered results
results = await asyncio.gather(coro1(), coro2(), coro3())

# wait — fine-grained control
tasks = [asyncio.create_task(coro()) for _ in range(5)]
done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
```
</details>

### Intermediate

<details>
<summary><b>Q4: Explain the event loop's three-phase cycle. What happens in each phase?</b></summary>

**Answer:** The event loop has three phases in each iteration:

1. **Ready Queue (Phase 1)**: Execute all callbacks in the `_ready` deque. These are scheduled via `call_soon()` and are run FIFO.

2. **I/O Polling (Phase 2)**: Call `selector.select(timeout)` where timeout is calculated as the time until the next scheduled timer. This polls registered file descriptors for I/O events. When events occur, their callbacks are added to the ready queue.

3. **Timer Sweep (Phase 3)**: Check the `_scheduled` heap for timers whose time has come. Move expired timers to the ready queue.

After Phase 3, the loop starts again at Phase 1 (if there are ready callbacks) or goes back to Phase 2.

```python
def _run_once(self):
    # Phase 1: Calculate timeout
    timeout = None if self._ready else self._next_timer_timeout()
    
    # Phase 2: Poll for I/O
    events = self._selector.select(timeout)
    self._process_events(events)
    
    # Phase 3: Move expired timers to ready
    self._sweep_timers()
    
    # Execute ready callbacks
    while self._ready:
        self._ready.popleft()._run()
```
</details>

<details>
<summary><b>Q5: How does the `await` keyword work under the hood? Describe the protocol.</b></summary>

**Answer:** The `await` keyword is syntactic sugar for `yield from`. Here's the protocol:

1. When you `await` an object, Python calls `object.__await__()`
2. `__await__()` must return an iterator
3. The iterator yields control back to the event loop, typically yielding a Future
4. The event loop receives the Future and registers a callback on it
5. When the Future completes, the event loop resumes the coroutine by calling `.send(result)`
6. The coroutine continues execution from where it yielded

```python
# The protocol:
class MyAwaitable:
    def __await__(self):
        # yield from delegates control to event loop
        result = yield from self._internal_gen()
        return result

# What 'await x' becomes:
# result = yield from x.__await__()
```
</details>

<details>
<summary><b>Q6: What is structured concurrency and how does `TaskGroup` implement it?</b></summary>

**Answer:** Structured concurrency ensures that:
1. Tasks are scoped to a block
2. All tasks are completed (or cancelled) when the block exits
3. If one task fails, siblings are cancelled
4. No tasks can outlive their parent scope

`TaskGroup` (Python 3.11+) implements this:
```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(task_a())  # All tasks are scoped to this block
    tg.create_task(task_b())
# All tasks done here — guaranteed

# If task_a fails:
# - task_b is automatically cancelled
# - ExceptionGroup is raised with all exceptions
```
Benefits over `gather()`:
- No orphaned tasks
- Automatic cancellation on failure
- Proper exception handling with `except*`
</details>

<details>
<summary><b>Q7: How do you properly handle cancellation in asyncio?</b></summary>

**Answer:**
```python
async def cancellable_operation():
    try:
        await long_running_work()
    except asyncio.CancelledError:
        # 1. Clean up resources
        await cleanup()
        # 2. ALWAYS re-raise (unless you really know what you're doing)
        raise

# Key points:
# - CancelledError is a BaseException (not Exception) in 3.9+
# - Always clean up before re-raising
# - Use asyncio.shield() to protect critical sections
# - Use async context managers for automatic cleanup

async def critical_section():
    # Protected from cancellation
    result = await asyncio.shield(financial_transaction())
    return result
```
</details>

<details>
<summary><b>Q8: What is uvloop and how does it improve performance?</b></summary>

**Answer:** uvloop is a drop-in replacement for asyncio's event loop that uses libuv (the library powering Node.js) under the hood.

**Performance benefits:**
- **2-3x throughput** improvement for I/O-bound workloads
- **~50% p99 latency reduction**
- libuv uses epoll/kqueue directly in C — no Python overhead per event
- Timer management in C with binary heap
- Async DNS in C via c-ares library

```python
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
# All asyncio operations now use libuv
```

**When to use:** High-throughput network services, microservices, WebSocket servers.
**When NOT to use:** CPU-bound work (uvloop only helps I/O).
</details>

### Advanced

<details>
<summary><b>Q9: Design an async rate-limited API client that handles 10,000 requests per second with proper backpressure.</b></summary>

**Answer:**
```python
import asyncio
import aiohttp
from collections import deque
from typing import Optional

class HighThroughputAPIClient:
    """Async API client with rate limiting and backpressure"""
    
    def __init__(
        self,
        base_url: str,
        max_concurrent: int = 100,
        requests_per_second: int = 1000,
    ):
        self.base_url = base_url
        self._sem = asyncio.Semaphore(max_concurrent)
        self._rate_limit = requests_per_second
        self._window = 1.0  # 1-second sliding window
        self._timestamps: deque[float] = deque()
        self._rate_lock = asyncio.Lock()
        # Optional requires 'from typing import Optional' (added above)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=self._sem._value,
            ttl_dns_cache=300,
        )
        self._session = aiohttp.ClientSession(
            base_url=self.base_url,
            connector=connector,
        )
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def request(self, method: str, path: str, **kwargs) -> dict:
        async with self._sem:  # Limit concurrency
            await self._throttle()  # Rate limit
            
            async with self._session.request(method, path, **kwargs) as resp:
                resp.raise_for_status()
                return await resp.json()
    
    async def _throttle(self):
        """Sliding window rate limiter"""
        async with self._rate_lock:
            now = asyncio.get_running_loop().time()
            
            # Remove expired timestamps
            while self._timestamps and self._timestamps[0] <= now - self._window:
                self._timestamps.popleft()
            
            # If window is full, wait
            if len(self._timestamps) >= self._rate_limit:
                sleep_time = self._timestamps[0] + self._window - now
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            self._timestamps.append(asyncio.get_running_loop().time())
    
    async def get(self, path: str, **kwargs) -> dict:
        return await self.request("GET", path, **kwargs)

# Usage:
# async with HighThroughputAPIClient("https://api.example.com", 100, 1000) as client:
#     results = await asyncio.gather(*[client.get(f"/items/{i}") for i in range(5000)])
```
</details>

<details>
<summary><b>Q10: Explain how Python's async/await protocol maps to generators. Show how you could implement a minimal event loop that drives coroutines.</b></summary>

**Answer:**
```python
import time
from collections import deque

# ── Minimal event loop ─────────────────────────────────────
class MiniEventLoop:
    """Minimal event loop driving coroutines via generators"""
    
    def __init__(self):
        self._ready = deque()
        self._timers = []  # (when, callback)
        import heapq
    
    def call_soon(self, callback):
        self._ready.append(callback)
    
    def call_later(self, delay, callback):
        heapq.heappush(self._timers, (time.monotonic() + delay, callback))
    
    def run_until_complete(self, coro):
        # Wrap coroutine in a task-like structure
        task = Task(coro, self)
        self._ready.append(task.step)
        self._run()
        return task.result
    
    def _run(self):
        while self._ready or self._timers:
            # Process ready queue
            while self._ready:
                callback = self._ready.popleft()
                callback()
            
            # Process timers
            now = time.monotonic()
            while self._timers and self._timers[0][0] <= now:
                _, callback = heapq.heappop(self._timers)
                self._ready.append(callback)
            
            # Poll (simplified — just sleep in real impl)
            time.sleep(0.001)

class Task:
    """Minimal task wrapping a coroutine"""
    def __init__(self, coro, loop):
        self._coro = coro
        self._loop = loop
        self.result = None
        self._done = False
    
    def step(self):
        try:
            # Advance coroutine to next yield point
            future = self._coro.send(None)
            # Register callback to resume when future completes
            if hasattr(future, 'add_done_callback'):
                future.add_done_callback(lambda f: self._loop.call_soon(self.step))
        except StopIteration as e:
            self.result = e.value
            self._done = True

# Usage:
async def my_coro():
    await asyncio.sleep(0.1)
    return 42

# Under the hood, 'await asyncio.sleep(0.1)':
# 1. Creates a Future
# 2. Registers a timer to complete the future after 0.1s
# 3. Yields the Future to the event loop
# 4. Event loop registers callback on Future
# 5. When timer fires, Future is resolved
# 6. Event loop resumes coroutine with Future.result()
# 7. Coroutine gets None back from await
```
</details>

<details>
<summary><b>Q11: How would you implement graceful shutdown for an async web server handling thousands of WebSocket connections?</b></summary>

**Answer:**
```python
import asyncio
import signal
import logging

logger = logging.getLogger(__name__)

class GracefulShutdownServer:
    """WebSocket server with graceful shutdown"""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._shutdown_event = asyncio.Event()
        self._connections: dict[int, asyncio.Task] = {}
        self._server: asyncio.AbstractServer | None = None
    
    def setup_signal_handlers(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._initiate_shutdown)
    
    def _initiate_shutdown(self):
        """Start graceful shutdown"""
        logger.info("Received shutdown signal")
        self._shutdown_event.set()
        
        # Stop accepting new connections
        if self._server:
            self._server.close()
    
    async def start(self):
        """Start the server"""
        self.setup_signal_handlers()
        
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )
        
        logger.info(f"Server listening on {self.host}:{self.port}")
        
        async with self._server:
            await self._shutdown_event.wait()
        
        await self._shutdown()
    
    async def _handle_connection(self, reader, writer):
        """Handle a single connection"""
        conn_id = id(writer)
        task = asyncio.create_task(
            self._connection_handler(conn_id, reader, writer)
        )
        self._connections[conn_id] = task
        
        try:
            await task
        except asyncio.CancelledError:
            # Connection was cancelled during shutdown
            pass
        finally:
            self._connections.pop(conn_id, None)
    
    async def _connection_handler(self, conn_id, reader, writer):
        """Handle the WebSocket/connection lifecycle"""
        try:
            while not self._shutdown_event.is_set():
                data = await asyncio.wait_for(
                    reader.read(1024),
                    timeout=1.0,
                )
                if not data:
                    break
                
                # Process message
                await self._process_message(conn_id, data)
                
        except asyncio.TimeoutError:
            # Normal timeout — check shutdown flag again
            pass
        except asyncio.CancelledError:
            logger.info(f"Connection {conn_id} cancelled during shutdown")
            raise
        except Exception as e:
            logger.error(f"Connection {conn_id} error: {e}")
        finally:
            try:
                # Send goodbye message if appropriate
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
    
    async def _process_message(self, conn_id: int, data: bytes):
        """Process a single message"""
        # Implementation depends on protocol (WebSocket, raw TCP, etc.)
        pass
    
    async def _shutdown(self):
        """Graceful shutdown all connections"""
        logger.info(f"Shutting down {len(self._connections)} connections...")
        
        # Notify all connections of shutdown
        close_tasks = []
        for conn_id, task in self._connections.items():
            task.cancel()  # Triggers CancelledError in handlers
            close_tasks.append(task)
        
        # Wait for tasks to complete with timeout
        if close_tasks:
            await asyncio.wait(close_tasks, timeout=10.0)
        
        # Shutdown remaining async infrastructure
        loop = asyncio.get_running_loop()
        await loop.shutdown_asyncgens()
        await loop.shutdown_default_executor()
        
        logger.info("Shutdown complete")

# Usage:
# server = GracefulShutdownServer("0.0.0.0", 8080)
# asyncio.run(server.start())
```
</details>

<details>
<summary><b>Q12: What happens when you call `asyncio.create_task()` from a non-async context? How do you safely bridge synchronous and asynchronous code?</b></summary>

**Answer:** You cannot call `asyncio.create_task()` from a non-async context because it requires a running event loop. To bridge sync and async:

**Option 1: `asyncio.run()` — Run a coroutine from sync code**
```python
def sync_function():
    """Bridge sync to async"""
    async def async_work():
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.example.com") as resp:
                return await resp.json()
    
    # Creates a new event loop, runs the coroutine, closes loop
    return asyncio.run(async_work())
```

**Option 2: Thread with running event loop** (for repeated calls)
```python
import threading

class AsyncBridge:
    """Maintain an event loop in a background thread"""
    
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )
        self._thread.start()
    
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
    
    async def submit(self, coro):
        """Submit a coroutine to the background loop"""
        future = asyncio.run_coroutine_threadsafe(
            coro, self._loop
        )
        return future.result(timeout=10)
    
    def shutdown(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

# Usage:
# bridge = AsyncBridge()
# result = bridge.submit(fetch_url("https://example.com"))
```

**Option 3: `asyncio.to_thread()` — From async to sync (Python 3.9+)**
```python
async def async_function():
    # Run synchronous function in thread pool
    result = await asyncio.to_thread(sync_function, arg1, arg2)
    return result
```
</details>

---

> *Built for experienced Python engineers targeting Staff/Principal roles at top-tier companies.*
> *Master async/await to build high-performance, concurrent systems at scale.*
