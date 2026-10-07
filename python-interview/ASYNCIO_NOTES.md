# 🐍 Python AsyncIO & Async/Await — Comprehensive Notes

> **A deep-dive into Python's async/await paradigm: coroutines, event loops, tasks, futures, and production-grade async patterns**
> *From fundamentals to staff-level internals — designed for Senior/Staff Engineer interview preparation*
> **Version baseline:** CPython 3.14 (current stable, October 2026). Version-specific behaviour is called out inline. Snippets marked with output were run on 3.14.

---

## Table of Contents

1. [Core Concepts & Terminology](#1-core-concepts-terminology)
2. [Async/Await Protocol Under the Hood](#2-asyncawait-protocol-under-the-hood)
3. [Event Loop Internals](#3-event-loop-internals)
4. [Running & Managing the Event Loop](#4-running-managing-the-event-loop)
5. [Coroutines Deep Dive](#5-coroutines-deep-dive)
6. [Tasks & Futures](#6-tasks-futures)
7. [Synchronization Primitives](#7-synchronization-primitives)
8. [Async Generators & Async Context Managers](#8-async-generators-async-context-managers)
9. [Streams, Subprocesses & Networking](#9-streams-subprocesses-networking)
10. [Advanced Patterns](#10-advanced-patterns)
11. [Performance Optimization](#11-performance-optimization)
12. [Production Patterns](#12-production-patterns)
13. [Common Pitfalls & Debugging](#13-common-pitfalls-debugging)
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
| **Async Iterator** | An object whose `__anext__` returns an awaitable producing the next value (`__aiter__`, `__anext__`); consumed with `async for` |
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
| File I/O | ⚠️ Via threads | Disk files are always "ready" to `select`/`epoll`; `aiofiles` and `asyncio.to_thread` just run blocking calls in a thread pool |
| CPU-bound computation | ❌ Bad | Single thread, blocks event loop |
| Many concurrent connections (10K+) | ✅ Excellent | ~1 KB per suspended task (measured on 3.14; ~1.8 KB on 3.10) vs ~8 MB of *virtual* stack reserved per OS thread |
| Microservices / API servers | ✅ Excellent | FastAPI/Starlette, aiohttp, gRPC aio |
| Real-time (WebSockets, SSE) | ✅ Excellent | Long-lived idle connections are cheap (libraries such as `websockets`; not in the stdlib) |
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
    # 2. The yielded Future travels up the await chain to the Task (Task.__step)
    # 3. The Task registers its __wakeup as a done-callback on the Future
    # 4. When the Future completes, the callback is scheduled with call_soon
    # 5. The Task calls coro.send(None) — NOT send(result); execution resumes
    #    inside __await__ after `yield self`, which returns self.result()

# ── Manual coroutine driving (what the event loop does) ───
async def demo_coro():
    print("Step 1")
    result = await inner_coro()
    print(f"Step 2: got {result}")
    return "done"

async def inner_coro():
    await asyncio.sleep(0)
    return 42

# The Task (not the loop itself) effectively does this:
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
    4. The Task registers a wake-up callback on that Future; the loop runs
       other work until a timer (call_later) completes the Future after 1s
    5. The Task calls coro.send(None) → coroutine resumes
    6. sleep(1) returns None
    7. Coroutine continues to next line
    """
    print("Coroutine started")
    await asyncio.sleep(1)  # Suspension point
    print("Coroutine resumed after 1 second")
    return 42

```

**Runnable trace — driving a coroutine by hand, the way a Task does:**

```python
class TracingFuture:
    """A minimal Future that prints what happens during await"""

    def __init__(self):
        self._result = None
        self._done = False

    def __await__(self):
        print("  [Future.__await__] called")
        if not self._done:
            print("  [Future.__await__] not done: yielding self up the chain")
            yield self                      # ← THE KEY LINE: suspends the whole await chain
        print("  [Future.__await__] resumed: returning result")
        return self._result

    def set_result(self, value):
        self._result, self._done = value, True

async def inner(fut):
    return await fut                        # no suspension here by itself: just delegates

async def demo(fut):
    print("demo: started")
    result = await inner(fut)
    print(f"demo: got {result!r}")
    return "demo done"

# ── Drive it by hand, exactly as a Task would ──────────────
fut = TracingFuture()
coro = demo(fut)
yielded = coro.send(None)                   # run until the first real suspension
print("driver: coroutine yielded", type(yielded).__name__)
fut.set_result(42)                          # "I/O completed" (normally a selector callback)
try:
    coro.send(None)                         # resume with None, not with 42
except StopIteration as stop:
    print("driver: coroutine returned", repr(stop.value))

# demo: started
#   [Future.__await__] called
#   [Future.__await__] not done: yielding self up the chain
# driver: coroutine yielded TracingFuture
#   [Future.__await__] resumed: returning result
# demo: got 42
# driver: coroutine returned 'demo done'
```

### The Compiler's Perspective

There's no hidden class. `async def` compiles to an ordinary code object with the `CO_COROUTINE` flag. Calling it creates a coroutine object (`RETURN_GENERATOR`), which shares the frame and suspension machinery of generators. Each `await` compiles to a `yield from`-style loop (CPython 3.14 bytecode, `dis.dis` output trimmed):

```text
async def f(x):
    return await x

  LOAD_FAST_BORROW   x
  GET_AWAITABLE      0        # calls x.__await__() (TypeError if not awaitable)
  LOAD_CONST         None
L2: SEND             (to L5)  # send the value into the sub-iterator
L3: YIELD_VALUE      1        # sub-iterator yielded (a Future): suspend, pass it up
L4: RESUME           3
    JUMP_BACKWARD_NO_INTERRUPT (to L2)
L5: END_SEND                   # sub-iterator finished: its return value is the result
    RETURN_VALUE
```

- That `SEND`/`YIELD_VALUE` loop is exactly `yield from`. This is why `await` is described as "`yield from` restricted to awaitables".
- Only something at the bottom of the chain (a `Future`, or a bare `yield` inside an `__await__`) actually yields. Every coroutine in between just forwards it.

### `yield from` vs `await`

```python
import asyncio

# ── await is (roughly) syntactic sugar for yield from ──────
# Conceptually equivalent (the second form isn't legal inside async def):
#   result = await awaitable
#   result = yield from awaitable.__await__()

# ── The critical differences ───────────────────────────────
# await expects an awaitable (has __await__) and only works in async def
# yield from accepts any iterable and only works in a generator

# ── __await__ can be implemented with yield from ────────────
class CustomAwaitable:
    def __await__(self):
        # yield from delegates to the generator
        # The event loop receives yielded values
        result = yield from self._internal_generator()
        return result
    
    def _internal_generator(self):
        print("  Internal generator: step 1")
        yield  # bare yield (None): the Task reschedules itself — like asyncio.sleep(0)
        print("  Internal generator: step 2 (resumed)")
        return "custom result"

# Usage:
async def test_custom():
    result = await CustomAwaitable()
    print(f"Got: {result}")

asyncio.run(test_custom())
#   Internal generator: step 1
#   Internal generator: step 2 (resumed)
# Got: custom result
```

Under asyncio, the only things an `__await__` may yield are `None` (give up one loop iteration) or an asyncio `Future`. Yielding anything else makes the Task raise `RuntimeError` ("Task got bad yield").

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

# Before PEP 492 (Python 3.4):
# @asyncio.coroutine decorator + yield from
# (deprecated in 3.8, REMOVED in 3.11 — you'll only see this in legacy code)
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
        """The main event loop cycle (same phase order as asyncio's _run_once)"""
        while not self._stopping:
            # Phase 1: Poll for I/O events
            # timeout = 0 if callbacks are ready, else time until next timer
            timeout = 0 if self._ready else self._time_until_next_scheduled()
            events = self._selector.select(timeout)
            for key, mask in events:
                callback = key.data  # Registered via add_reader
                self._ready.append(callback)

            # Phase 2: Move expired timers to ready queue
            now = time.monotonic()
            while self._scheduled and self._scheduled[0].when <= now:
                handle = heapq.heappop(self._scheduled)
                self._ready.append(handle.callback)

            # Phase 3: Run only the callbacks that are ready NOW.
            # Callbacks scheduled while these run wait for the next pass,
            # so a callback that keeps re-scheduling itself can't starve I/O.
            for _ in range(len(self._ready)):
                callback = self._ready.popleft()
                callback()
    
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
            return None  # Block until I/O arrives (real loop: no timeout)
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
# Windows: asyncio.ProactorEventLoop  (IOCP, the default since 3.8)
# Third-party: uvloop (libuv; Linux/macOS only)

# ── Internals: how add_reader works ───────────────────────
async def add_reader_demo():
    """Simulate how the event loop registers file descriptors"""
    loop = asyncio.get_running_loop()   # module-level get_event_loop() raises in 3.14
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
    """What asyncio.run() does internally (simplified asyncio.Runner, 3.11+)"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(main())
    finally:
        try:
            # Cancel remaining tasks AND wait for them to finish unwinding
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())          # finalize async generators
            loop.run_until_complete(loop.shutdown_default_executor())   # join to_thread workers (3.9+)
        finally:
            asyncio.set_event_loop(None)
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
import asyncio
import uvloop

# ── uvloop: the whole event loop reimplemented in Cython on libuv ──
# libuv is the I/O library behind Node.js. What moves into C:
# 1. The polling loop (epoll/kqueue) and per-event dispatch
# 2. Timers, call_soon handles, transports and protocols (TCP/UDP/Unix/pipes)
# 3. Signal handling and subprocess management
# DNS (getaddrinfo) runs on libuv's thread pool; your coroutines still
# run in the Python interpreter, so app-level CPU work isn't faster.

async def main():
    await asyncio.sleep(1)

# ── Setup (uvloop >= 0.18) ─────────────────────────────────
uvloop.run(main())
# Same thing with the stdlib (3.12+):
# asyncio.run(main(), loop_factory=uvloop.new_event_loop)

# Legacy: asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
# The policy system is deprecated in 3.14 and slated for removal in 3.16.
```

- The "2x" in the heading is a rule of thumb. The project's own claim is "2–4x faster" on its networking benchmarks (echo servers, HTTP parsing). Real services that spend most of their time in their own Python code, ORMs or serialization see much less, so benchmark your workload.
- Status (October 2026): uvloop 0.23 supports CPython 3.8–3.15, including free-threaded wheels. Not available on Windows. Uvicorn uses it automatically when installed (`uvicorn[standard]`).

---

## 4. Running & Managing the Event Loop

### `asyncio.run()` — The High-Level API

```python
import asyncio

# ── Preferred way to run async code (Python 3.7+) ──────────
# asyncio.run() does:
# 1. Creates a new event loop (or uses loop_factory=..., 3.12+)
# 2. Sets it as the current loop
# 3. Runs the coroutine until completion
# 4. Cancels remaining tasks and waits for them to finish
# 5. Shuts down async generators
# 6. Shuts down the default executor (3.9+)
# 7. Closes the loop

async def main():
    await asyncio.sleep(1)
    return "done"

result = asyncio.run(main())
print(result)  # "done"

# ── Important: asyncio.run() cannot be called from a running loop ──
# Calling asyncio.run() inside a coroutine (or in Jupyter, which already
# runs a loop) raises:
# RuntimeError: asyncio.run() cannot be called from a running event loop
# In Jupyter, just use top-level `await main()`.

# ── Several top-level calls sharing one loop: asyncio.Runner (3.11+) ──
async def test():
    await asyncio.sleep(0.1)
    return 42

with asyncio.Runner() as runner:          # also accepts loop_factory=
    print(runner.run(test()))             # 42
    print(runner.run(test()))             # 42 — same loop, same contextvars

# ── Lower level (embedding, legacy code) ───────────────────
loop = asyncio.new_event_loop()
try:
    print(loop.run_until_complete(test()))  # 42
finally:
    loop.close()
```

### Low-Level Loop Control

```python
import asyncio

# ── Getting the current loop ───────────────────────────────
# asyncio.get_running_loop()  ✅ Preferred inside coroutines/callbacks;
#                              raises RuntimeError if no loop is running.
# asyncio.get_event_loop()    ⚠️ Inside a running loop: same as get_running_loop().
#                              With no running loop: 3.10–3.13 warned (DeprecationWarning)
#                              and created one; 3.14 raises RuntimeError unless a loop
#                              was explicitly set with set_event_loop().

# ── Scheduling callbacks (these lines run inside a coroutine) ──
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

from concurrent.futures import ProcessPoolExecutor

# Create executors once at startup, not per call
IO_POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="blocking-io")
CPU_POOL = ProcessPoolExecutor()

async def run_blocking():
    # Simplest (3.9+): default thread pool, copies contextvars into the thread
    await asyncio.to_thread(time.sleep, 1.0)      # blocks a worker thread, NOT the loop

    loop = asyncio.get_running_loop()
    # Dedicated thread pool: isolates slow legacy clients from the default pool
    result = await loop.run_in_executor(IO_POOL, blocking_db_call, query)

    # CPU-bound: a process pool sidesteps the GIL (args/results are pickled)
    result = await loop.run_in_executor(CPU_POOL, cpu_bound_function, large_data)

# ⚠️ Don't write `with ProcessPoolExecutor() as pool:` inside a coroutine:
#    leaving the block calls pool.shutdown(wait=True), which blocks the event loop.
# ⚠️ The default executor has min(32, cpu_count + 4) threads. Saturate it with slow
#    calls and every to_thread() caller queues behind them.

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
# 1. Slow callback warnings: any callback/task step taking > 100 ms is logged
# 2. "Coroutine was never awaited" warnings include WHERE it was created
# 3. Tasks and handles record their creation traceback
# 4. Non-thread-safe calls (e.g. call_soon from another thread) raise RuntimeError
# 5. Unclosed transports/loops produce ResourceWarning with source info

import logging, time
logging.basicConfig(level=logging.WARNING)

async def handler():
    time.sleep(0.2)          # blocking call inside a coroutine

async def main():
    await asyncio.create_task(handler())

asyncio.run(main(), debug=True)
# WARNING:asyncio:Executing <Task finished name='Task-2' coro=<handler() done,
#   defined at demo.py:4> result=None created at .../asyncio/tasks.py:395> took 0.205 seconds

# ── Custom slow callback duration ──────────────────────────
# asyncio.get_running_loop().slow_callback_duration = 0.05  # 50ms threshold
```

Debug mode is too slow for production. There, measure loop lag instead: schedule a task that sleeps 100 ms in a loop and records how late it wakes up. To see what a live process is stuck on, use `python -m asyncio pstree <PID>` (3.14+) or `py-spy dump --pid <PID>`.

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

# ── The lifecycle of a coroutine (verified) ────────────────
import inspect

async def lifecycle_demo():
    await asyncio.sleep(0)
    return "completed"

async def track_state():
    coro = lifecycle_demo()
    print(inspect.getcoroutinestate(coro))   # CORO_CREATED
    task = asyncio.create_task(coro)
    await asyncio.sleep(0)                   # let it run to its first await
    print(inspect.getcoroutinestate(coro))   # CORO_SUSPENDED
    print(await task)                        # completed
    print(inspect.getcoroutinestate(coro))   # CORO_CLOSED
    try:
        await coro
    except RuntimeError as e:
        print("RuntimeError:", e)

asyncio.run(track_state())
# CORO_CREATED
# CORO_SUSPENDED
# completed
# CORO_CLOSED
# RuntimeError: cannot reuse already awaited coroutine
```

The four states are `CORO_CREATED`, `CORO_RUNNING`, `CORO_SUSPENDED` and `CORO_CLOSED`. A coroutine is single-use. A Task or Future can be awaited any number of times.

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

# (A plain generator like this can't be passed to asyncio.run/create_task;
#  since 3.11 only native coroutines can.)

# ── You can drive a coroutine like a generator (verified) ──
async def simple_inner(fut):
    value = await fut                      # a pending Future: this really suspends
    return f"hello {value}"

async def inspect_coroutine():
    fut = asyncio.get_running_loop().create_future()
    coro = simple_inner(fut)
    yielded = coro.send(None)              # what a Task does on its first step
    print("YIELDED:", yielded)             # the pending Future itself
    print("same object:", yielded is fut)
    fut.set_result("world")                # normally done by I/O or a timer
    try:
        coro.send(None)                    # resume (with None, not the result)
    except StopIteration as e:
        print("DONE:", e.value)

    zero = asyncio.sleep(0).__await__()
    print("sleep(0) yields:", zero.send(None))   # None: a bare yield
    zero.close()

asyncio.run(inspect_coroutine())
# YIELDED: <Future pending>
# same object: True
# DONE: hello world
# sleep(0) yields: None
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
    print(f"Name: {task.get_name()}")    # Task-2 (Task-1 is main() under asyncio.run)
    print(f"Coroutine: {task.get_coro()}")  # <coroutine object>
    
    # Set custom name (useful for debugging)
    task.set_name("my-background-task")
    
    # Wait for completion (on timeout the task is cancelled)
    try:
        async with asyncio.timeout(5.0):    # 3.11+; preferred over wait_for
            result = await task
    except TimeoutError:                    # asyncio.TimeoutError is an alias since 3.11
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
    # Without return_exceptions: the first error propagates immediately,
    # but the OTHER awaitables are NOT cancelled. slow_work() keeps running
    # as an orphan; if it fails later, nobody sees the error.
    await asyncio.gather(fast_fail(), slow_work())

    # With return_exceptions=True: no orphans, but you always wait for
    # the slowest one even when an early failure makes the result useless.
    await asyncio.gather(fast_fail(), slow_work(), return_exceptions=True)

# Better: TaskGroup (fail fast AND cancel siblings), or wait(FIRST_EXCEPTION)
# and cancel `pending` yourself.
```

| | First error → caller sees it | Siblings cancelled on error | Partial results |
|---|---|---|---|
| `gather()` | immediately | ❌ no (orphans) | ❌ |
| `gather(return_exceptions=True)` | after all finish | n/a | ✅ exceptions in the list |
| `TaskGroup` | after siblings are cancelled | ✅ | ❌ (`ExceptionGroup`) |
| `wait(FIRST_EXCEPTION)` | immediately | ❌ you cancel `pending` | ✅ via `done` |

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

    # 3.13+: async iteration yields the ORIGINAL tasks, so you know which one finished
    # async for task in asyncio.as_completed(task_list):
    #     print(task.get_name(), task.result())

# ── Timeouts ───────────────────────────────────────────────
async def with_timeout():
    try:
        async with asyncio.timeout(2.0):        # 3.11+: covers a whole block
            result = await fetch_url("A", 10.0)
    except TimeoutError:
        print("Timed out!")                     # the inner await was cancelled

    # wait_for still works (reimplemented on top of timeout() in 3.12):
    # result = await asyncio.wait_for(fetch_url("A", 10.0), timeout=2.0)
    # asyncio.timeout_at(deadline) / cm.reschedule(new_deadline) for deadline propagation
```

How `asyncio.timeout()` works: it schedules a callback that cancels the *current task* at the deadline, then converts that `CancelledError` into `TimeoutError` on exit. It uses `Task.uncancel()` (3.11) to tell its own cancellation apart from an outside `task.cancel()`, so nested timeouts and real shutdowns aren't swallowed.

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
    except* ValueError as eg:
        # A child failed: siblings were already cancelled and awaited.
        # eg is an ExceptionGroup holding only the ValueErrors.
        print(f"TaskGroup failed with: {eg.exceptions}")
        raise
    # Don't catch CancelledError here: if the *enclosing* task is cancelled,
    # TaskGroup re-raises a plain CancelledError (not a group). Swallowing it
    # breaks shutdown and asyncio.timeout(). Do cleanup in `finally:` instead.

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
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    def on_done(fut):
        # Fires on ANY completion: result, exception or cancellation
        if fut.cancelled():
            print("Future was cancelled")
        elif fut.exception() is not None:
            print(f"Future failed: {fut.exception()!r}")
        else:
            print(f"Future done: {fut.result()}")
    
    future.add_done_callback(on_done)   # scheduled via call_soon, never run inline
    loop.call_later(0.5, future.set_result, 42)
    result = await future

# ── Wrapping callback-based code with Future ───────────────
async def async_wrap_callback():
    """Convert a callback-based API (callback may fire on another thread)"""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    def _set(result):
        if not future.done():               # we may have been cancelled meanwhile
            future.set_result(result)

    def callback(result):                   # runs on the library's thread
        loop.call_soon_threadsafe(_set, result)   # Futures are NOT thread-safe
    
    some_callback_api(callback)
    return await future

# Usage:
# result = await async_wrap_callback()
# From a *different* thread into the loop: asyncio.run_coroutine_threadsafe(coro, loop)
# returns a concurrent.futures.Future you can .result() on.
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
# Between awaits, a coroutine can't be interrupted, so code with
# no await in it needs no lock at all. You only need asyncio.Lock
# when a critical section contains an await (check-then-act across I/O).
# Keep the locked region as short as with threads: every waiter is
# stalled for the full duration of any I/O done under the lock.
# asyncio.Lock is FIFO-fair, and it's not thread-safe.

# ── Lock with timeout ─────────────────────────────────────
async def lock_with_timeout():
    lock = asyncio.Lock()
    
    try:
        async with asyncio.timeout(1.0):
            await lock.acquire()
        try:
            # Critical section
            pass
        finally:
            lock.release()
    except TimeoutError:
        print("Could not acquire lock within 1 second")
```

### RLock (Reentrant Lock)

**asyncio has no `RLock`.** `asyncio.RLock` doesn't exist (`AttributeError`). An `asyncio.Lock` re-acquired by the coroutine that holds it **deadlocks**: the second `acquire()` waits forever. The usual fix is to lock only in public methods and do the work in private unlocked helpers:

```python
import asyncio

class AsyncCounter:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._value = 0

    async def _increment_unlocked(self) -> None:   # caller must hold the lock
        self._value += 1

    async def increment(self) -> None:
        async with self._lock:
            await self._increment_unlocked()

    async def increment_by(self, n: int) -> None:
        async with self._lock:                     # one acquisition for the batch
            for _ in range(n):
                await self._increment_unlocked()

    async def get_and_increment(self) -> int:
        async with self._lock:
            value = self._value
            await self._increment_unlocked()
            return value

async def demo():
    counter = AsyncCounter()
    await counter.increment_by(5)
    print(await counter.get_and_increment())   # 5 (value is now 6)

asyncio.run(demo())
```

Why there's no RLock: "ownership" in asyncio would have to mean the *task*, and a lock held across `await` and re-entered through calls is usually a design smell.

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

# ── Practical: concurrency-limited API client ──────────────
# A Semaphore caps how many calls are IN FLIGHT. It is not a rate limiter
# (requests/second): fast responses still let you exceed an API's rate.
# For rates use a token bucket (e.g. aiolimiter) — often both together.
class ConcurrencyLimiter:
    """Limit concurrent API calls"""
    
    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max_concurrent)
    
    async def call_api(self, url: str) -> dict:
        async with self._sem:
            return await make_request(url)

# Usage:
# limiter = ConcurrencyLimiter(10)
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
            except TimeoutError:
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
# Event: a latch — set() wakes ALL current and future waiters until clear().
#   Great for "started" / "shutdown" flags. Bad as a work signal: with
#   set()+clear(), waiters that haven't run yet can miss the pulse, and
#   several waiters may see one "data_ready". Use a Queue for work items.
# Condition: wait until a predicate over shared state becomes true.
```

### Condition

```python
import asyncio

# ── Condition: wait for complex state changes (verified) ───
from collections import deque

class AsyncBoundedBuffer:
    """Producer-consumer with two Conditions sharing ONE lock"""

    def __init__(self, maxsize: int = 10):
        self._buffer: deque = deque()
        self._maxsize = maxsize
        lock = asyncio.Lock()
        self._not_full = asyncio.Condition(lock)    # producers wait here
        self._not_empty = asyncio.Condition(lock)   # consumers wait here

    async def put(self, item) -> None:
        async with self._not_full:
            # wait_for re-checks the predicate after every wake-up
            await self._not_full.wait_for(lambda: len(self._buffer) < self._maxsize)
            self._buffer.append(item)
            self._not_empty.notify()                # wake exactly one CONSUMER

    async def get(self):
        async with self._not_empty:
            await self._not_empty.wait_for(lambda: len(self._buffer) > 0)
            item = self._buffer.popleft()
            self._not_full.notify()                 # wake exactly one PRODUCER
            return item

async def condition_demo():
    buffer = AsyncBoundedBuffer(5)
    got: list[str] = []

    async def producer():
        for i in range(20):
            await buffer.put(f"item-{i}")

    async def consumer():
        for _ in range(10):
            got.append(await buffer.get())

    async with asyncio.TaskGroup() as tg:
        tg.create_task(producer())
        tg.create_task(consumer())
        tg.create_task(consumer())
    print(len(got), got[:3])    # 20 ['item-0', 'item-1', 'item-2']

asyncio.run(condition_demo())
```

- **Bugs in the classic one-Condition version:** with a single Condition, `notify()` can wake another *producer* when a consumer was needed; that producer goes back to sleep and the consumer never wakes (lost wake-up → deadlock). A `put_many` that waits for space without notifying first deadlocks the same way. Two Conditions sharing one lock (or `notify_all()`) avoids this.
- In real code, just use `asyncio.Queue(maxsize=...)`. It is exactly this, already debugged.

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
    # Output (3.14):
    # A: phase 1 starting
    # B: phase 1 starting
    # C: phase 1 starting
    # C: phase 1 done, waiting at barrier    (fastest)
    # B: phase 1 done, waiting at barrier
    # A: phase 1 done, waiting at barrier    (last arrival releases everyone)
    # A: phase 2 starting (all synced!)
    # C: phase 2 starting (all synced!)
    # B: phase 2 starting (all synced!)
    # ... phase 2 done lines follow 0.5s later
    # The order AFTER the barrier is a scheduling detail — don't rely on it.
```

`asyncio.Barrier` was added in 3.11. `barrier.wait()` returns a distinct index (0..n-1) to each party, so exactly one can do the "leader" work for the phase.

### Queue

```python
import asyncio
import random

# ── asyncio.Queue — async-safe FIFO (verified) ────────────
async def queue_demo():
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)   # bounded = backpressure
    processed: list[str] = []

    async def producer():
        for i in range(20):
            await queue.put(f"item-{i}")      # waits while the queue is full
        queue.shutdown()                      # 3.13+: no more puts; getters drain, then stop

    async def consumer(name: str):
        while True:
            try:
                item = await queue.get()      # raises QueueShutDown once empty + shut down
            except asyncio.QueueShutDown:
                return
            try:
                await asyncio.sleep(0.01)     # "process" the item
                processed.append(item)
            finally:
                queue.task_done()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(producer())
        for n in range(3):
            tg.create_task(consumer(f"C{n}"))
    print(f"processed {len(processed)} items")   # processed 20 items

asyncio.run(queue_demo())

# Before 3.13 (no shutdown()): put one sentinel PER consumer, or cancel the
# consumers after `await queue.join()`. A single None sentinel with two
# consumers leaves the second one waiting forever.

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
await q.join()           # Wait until task_done() was called for every item
q.task_done()            # Signal item processed
q.shutdown()             # 3.13+: put() raises QueueShutDown; get() drains then raises
q.shutdown(immediate=True)  # 3.13+: also discard queued items
```

Not thread-safe: from another thread use `loop.call_soon_threadsafe(q.put_nowait, item)` or a `janus` queue.

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
    received = yield "ready"              # first asend(None) stops here
    while True:
        received = yield f"Echo: {received}"
# Don't `yield` from an except/finally that handles GeneratorExit:
# aclose() then raises RuntimeError("async generator ignored GeneratorExit").

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
            await conn.close()  # runs on exhaustion, error, or aclose()
    
    # ⚠️ `break` does NOT close the generator. It stays suspended at its
    # `yield`, holding the connection, until someone calls aclose(): you,
    # aclosing(), or the loop's asyncgen finalizer hook after garbage
    # collection (later, in another task, maybe never during shutdown).
    from contextlib import aclosing        # 3.10+
    async with aclosing(resource_generator()) as gen:
        async for data in gen:
            if condition(data):
                break                      # → aclose() on exit → finally runs now
    
    # Or explicitly:
    gen = resource_generator()
    await gen.asend(None)  # Start: runs to the first yield, returns that value
    await gen.aclose()     # Throws GeneratorExit at the yield → finally runs
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
        # `return 3` here would be a SyntaxError: async generators can't
        # return a value (no StopAsyncIteration.value equivalent)
    
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
    
    print(await gen.asend(10))  # 10
    print(await gen.asend(5))   # 15
    print(await gen.asend(3))   # 18
    
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
        
        # Push custom cleanup callbacks (must be an async callable)
        async def custom_cleanup():
            print("Custom cleanup")
        stack.push_async_callback(custom_cleanup)
        
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
        raise                    # never swallow cancellation (server shutdown relies on it)
    except ConnectionResetError:
        pass                     # client vanished
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass

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
        stderr=asyncio.subprocess.STDOUT,   # merge: an unread stderr PIPE can fill
    )                                       # (~64 KiB) and block the child forever
    
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
    # Output order: A, B, C. gather() returns results in INPUT order even though
    # C finished first. Total time ~2s (the slowest), not 3.5s.
    # Use asyncio.as_completed() if you want completion order.
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
        self._session: Optional[aiohttp.ClientSession] = None  # `X | None` on 3.10+
    
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
        # Spaces request STARTS at least 1/rate apart (holding the lock while
        # sleeping serializes callers on purpose). For bursts, use a token bucket.
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
    except* Exception as eg:
        # One child crashed: siblings were cancelled and awaited before this runs
        print(f"Service failed: {eg.exceptions!r}")
        raise
    finally:
        # Runs on success, failure AND outer cancellation (shutdown).
        # Don't catch CancelledError with except*: outer cancellation arrives
        # as a plain CancelledError, and swallowing it breaks shutdown.
        await cleanup()

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
        async with asyncio.timeout(10):              # outer deadline for the whole group
            async with asyncio.TaskGroup() as tg:
                tg.create_task(work_that_might_hang())
                tg.create_task(work_that_might_fail())
    except* TimeoutError:
        ...   # deadline hit: the group's children were all cancelled and awaited
    except* ValueError as eg:
        ...   # a child failed: siblings cancelled; eg holds the ValueErrors
# A bare `except*:` is a SyntaxError (except* always needs a type), and one
# `try` can't mix `except` and `except*`. A bare TimeoutError raised by
# timeout() is still matched by `except* TimeoutError` (it's wrapped in a group).
```

!!! tip "TaskGroup rules worth memorising"
    - The `async with` block doesn't exit until **every** child has finished, so a `while True` child must be cancelled explicitly or the group never exits.
    - `tg.create_task()` after the group has started shutting down raises `RuntimeError`.
    - The first child failure cancels the siblings *and the body of the `async with`*. The errors come out as an `ExceptionGroup` (even if there's only one).
    - Outer cancellation (e.g. shutdown) propagates as a plain `CancelledError`.

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
    except TimeoutError:                     # builtin; asyncio.TimeoutError is an alias (3.11+)
        print("Operation timed out!")
        # The operation is cancelled automatically

# ── asyncio.wait_for (3.7+) — wraps a single awaitable ─────
async def wait_for_demo():
    try:
        result = await asyncio.wait_for(
            slow_operation(),
            timeout=5.0,
        )
    except TimeoutError:
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
        except TimeoutError:
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
_background: set[asyncio.Task] = set()

async def critical_section():
    """Let a commit finish even if the caller is cancelled"""
    task = asyncio.create_task(finalize_transaction())
    _background.add(task)                       # keep a strong reference:
    task.add_done_callback(_background.discard) # the loop only holds weak refs
    # If THIS coroutine is cancelled, `await` still raises CancelledError here,
    # but the inner task keeps running to completion.
    return await asyncio.shield(task)
# shield() doesn't protect against loop shutdown: asyncio.run() cancels all tasks.

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
            # Safe to swallow here: it's the CHILD's cancellation, not ours.
            # (Check asyncio.current_task().cancelling() if unsure, 3.11+.)
            print("Main: task was cancelled (expected)")
```

**Cancellation facts interviewers probe:**

- `task.cancel()` only *requests* cancellation. `CancelledError` is thrown into the coroutine at its next `await`. Code with no `await` can't be cancelled.
- `CancelledError` has inherited from `BaseException` since 3.8, so `except Exception:` no longer swallows it. A bare `except:` or `except BaseException:` still does.
- `task.cancel(msg)` attaches a message. `task.cancelling()` / `task.uncancel()` (3.11) count pending cancel requests; that's how `timeout()` and `TaskGroup` tell their own cancellations apart from external ones.
- Cleanup in `except CancelledError`/`finally` can itself be cancelled at its next `await` (e.g. a second Ctrl-C). Keep it short, and use `shield()` or a timeout for cleanup that must finish.

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
    # Use a ProcessPoolExecutor created ONCE at startup (CPU_POOL below).
    # `with ProcessPoolExecutor() as pool:` inside a coroutine blocks the loop
    # on exit (shutdown(wait=True)) and pays process start-up on every call.
    result = await loop.run_in_executor(
        CPU_POOL,
        cpu_intensive_function, large_data   # args and result are pickled
    )
    
    # ── Custom thread pool (isolate slow legacy clients) ──
    results = await asyncio.gather(*[
        loop.run_in_executor(IO_POOL, fetch_url, url)
        for url in urls
    ])

CPU_POOL = ProcessPoolExecutor()
IO_POOL = ThreadPoolExecutor(max_workers=10)

# ── to_thread (3.9+) — simpler API ────────────────────────
async def to_thread_demo():
    # asyncio.to_thread runs in the default thread pool and copies the
    # current contextvars (request IDs, tracing spans) into the thread
    result = await asyncio.to_thread(
        sync_blocking_function, arg1, arg2
    )
# Cancelling the awaiting task does NOT stop the thread: the function
# runs to completion and its result is discarded.
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
        # Must be constructed inside a running loop (create_task needs one)
        self._queue = asyncio.Queue(maxsize=num_workers * 10)  # bounded: backpressure on submit()
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
    
    async def shutdown(self, timeout: float = 30.0):
        """Drain queued jobs, then stop workers (with a deadline)."""
        # One sentinel per worker. FIFO order means every real job queued
        # before shutdown() is processed before any worker sees its None.
        for _ in range(self._num_workers):
            await self._queue.put(None)
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*self._workers)   # workers exit after their sentinel
        except TimeoutError:
            for w in self._workers:                    # a job hung: stop waiting
                w.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
        # 3.13+: self._queue.shutdown() replaces the sentinels.

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

# ── uvloop (libuv-based; project claims 2-4x on network benchmarks) ──
import uvloop  # pip install uvloop  (Linux/macOS)

uvloop.run(main())                                       # uvloop >= 0.18
# asyncio.run(main(), loop_factory=uvloop.new_event_loop)  # stdlib form, 3.12+
# asyncio.set_event_loop_policy(...) is deprecated in 3.14 (removal in 3.16)

# ── When uvloop shines ────────────────────────────────────
# 1. High-throughput network servers where loop/transport overhead dominates
# 2. Many concurrent connections with small messages (proxies, WebSockets)
# When it doesn't: CPU-heavy handlers, ORM/serialization-bound apps,
# Windows. Measure with your workload before and after.
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
    
    # The semaphore caps IN-FLIGHT requests, but all len(urls) coroutines
    # (and Tasks, inside gather) are created up front. For millions of items,
    # use N workers pulling from a bounded Queue instead.
    tasks = [fetch_with_sem(url) for url in urls]
    return await asyncio.gather(*tasks)

# ── Chunked processing for large datasets ──────────────────
async def chunked_processing(items: list, chunk_size: int = 100):
    """Process in chunks to avoid overwhelming resources.
    Downside: each chunk waits for its slowest item (head-of-line blocking),
    so throughput is worse than a semaphore or worker pool."""
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
        # aiohttp manages its own connection pool inside the ClientSession.
        # Create ONE session per service (not per request) and reuse it.
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
import aiohttp

# TCPConnector caches DNS results (ttl_dns_cache, default 10s).
# The default resolver runs getaddrinfo in a thread; AsyncResolver (needs
# aiodns) is fully async. Don't hard-code public nameservers: in Kubernetes
# or a VPC that bypasses internal DNS and breaks service discovery.
connector = aiohttp.TCPConnector(
    resolver=aiohttp.AsyncResolver(),   # uses the system's configured nameservers
    ttl_dns_cache=60,                   # longer TTL = fewer lookups, slower failover
)
```

### Eager Tasks & Context Propagation

```python
import asyncio, contextvars

request_id = contextvars.ContextVar("request_id", default="-")

async def child() -> str:
    return request_id.get()

async def main():
    # ── contextvars: each Task gets a COPY of the context at creation ──
    request_id.set("req-42")
    t = asyncio.create_task(child())
    request_id.set("changed")                       # doesn't affect the copy
    print(await t, await asyncio.to_thread(request_id.get))   # req-42 changed

    # ── Eager tasks (3.12+): start running synchronously inside create_task ──
    asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
    async def cached() -> str:
        return "hit"                                # never awaits anything
    t2 = asyncio.create_task(cached())
    print(t2.done())                                # True: finished without a loop iteration
    # Per task (3.14+): asyncio.create_task(coro, eager_start=True)

asyncio.run(main())
```

- **contextvars** are how request IDs, tracing spans and auth context flow through async code. Thread-locals don't work, because many tasks share one thread. `asyncio.to_thread` and `loop.run_in_executor` handle this differently: `to_thread` copies the context into the worker thread, `run_in_executor` doesn't.
- **Eager task factory:** a coroutine that completes without suspending (cache hit, memoized result) skips scheduling entirely, which can significantly cut overhead in fan-out-heavy code. Trade-off: the task body starts running *before* `create_task` returns, so code that assumed "create_task never runs anything yet" can change order.

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

# ── ✅ GOOD: Offloading to a process pool ─────────────────
async def good_cpu_bound():
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        CPU_POOL,  # ProcessPoolExecutor created at startup
        cpu_intensive_function, 10_000_000
    )
    return result
# A thread pool (None) keeps the loop responsive only partly: pure-Python
# CPU work in a thread still competes for the GIL with the loop thread,
# raising latency, and gets no parallelism (except on free-threaded 3.14t).

# ── ❌ BAD: Creating too many tasks at once ───────────────
async def bad_many_tasks():
    # Creates 100,000 tasks immediately — memory spike!
    tasks = [asyncio.create_task(light_work()) for _ in range(100_000)]
    return await asyncio.gather(*tasks)

# ── ✅ BETTER: Semaphore limits in-flight work ────────────
async def good_many_tasks():
    sem = asyncio.Semaphore(1000)
    
    async def limited_work():
        async with sem:
            return await light_work()
    
    # Still 100k Task objects (~1 KB each ≈ 100 MB), but only 1000 doing I/O
    # at once, so sockets, DB connections and the remote service are protected.
    tasks = [asyncio.create_task(limited_work()) for _ in range(100_000)]
    return await asyncio.gather(*tasks)

# ── ✅ BEST for very large inputs: fixed workers + bounded queue ──
async def bounded_workers(items, n_workers: int = 1000):
    q: asyncio.Queue = asyncio.Queue(maxsize=n_workers * 2)
    async def worker():
        while True:
            try:
                item = await q.get()
            except asyncio.QueueShutDown:      # 3.13+
                return
            try:
                await light_work(item)
            finally:
                q.task_done()
    async with asyncio.TaskGroup() as tg:
        for _ in range(n_workers):
            tg.create_task(worker())
        for item in items:                     # memory stays O(n_workers)
            await q.put(item)
        q.shutdown()

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
    """Benchmark an async function: throughput AND per-call latency"""
    latencies: list[float] = []

    async def timed():
        t0 = time.perf_counter()
        result = await func()
        latencies.append(time.perf_counter() - t0)
        return result

    start = time.perf_counter()
    results = await asyncio.gather(*(timed() for _ in range(num_calls)))
    elapsed = time.perf_counter() - start

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p99 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]
    print(f"Total: {elapsed:.2f}s  Throughput: {num_calls / elapsed:.0f} calls/s")
    print(f"Latency p50: {p50 * 1000:.1f}ms  p99: {p99 * 1000:.1f}ms")
    # Note: elapsed / num_calls is NOT latency under concurrency — it's 1/throughput.
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

# ── Graceful shutdown: stop intake → drain with a deadline → cancel ──
class GracefulShutdown:
    def __init__(self, drain_timeout: float = 25.0):   # < k8s terminationGracePeriodSeconds (30s)
        self.stopping = asyncio.Event()
        self._drain_timeout = drain_timeout
        self._tasks: set[asyncio.Task] = set()

    def track(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)                     # strong ref; loop keeps only weak refs
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self) -> None:
        # 1. Stop intake: workers check `stopping` between jobs, servers
        #    stop accepting and readiness probes start failing.
        self.stopping.set()
        # 2. Let in-flight work finish, up to the deadline
        if self._tasks:
            done, pending = await asyncio.wait(self._tasks, timeout=self._drain_timeout)
            # 3. Cancel stragglers AND wait for their cleanup to run
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        # asyncio.run() then finalizes async generators and the default executor.

# ── Usage in production service ────────────────────────────
async def main_service():
    gs = GracefulShutdown()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):              # Unix only
        loop.add_signal_handler(sig, gs.stopping.set)

    gs.track(consume_jobs(gs.stopping))    # loops `while not stopping.is_set()`
    gs.track(health_check())

    await gs.stopping.wait()
    await gs.shutdown()

asyncio.run(main_service())
```

- Without custom handlers, `asyncio.run()` (3.11+) turns the **first** Ctrl-C into cancellation of the main task, and a second one raises `KeyboardInterrupt` immediately. SIGTERM isn't handled by default, so the process just dies. Containers send SIGTERM, so install a handler.
- Order matters: fail readiness → stop accepting → drain → cancel → close pools/clients (reverse of startup, e.g. with `AsyncExitStack`).

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
                # Check dependencies concurrently: the total time is the slowest check
                db_ok, cache_ok, queue_ok = await asyncio.gather(
                    self._check_database(), self._check_cache(), self._check_queue(),
                )
                
                self._healthy = db_ok and cache_ok and queue_ok
                if self._healthy:
                    self._failures = 0
                else:
                    self._failures += 1
        except TimeoutError:
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

Design note: keep **liveness** cheap (is the event loop responsive?) and put dependency checks in **readiness**. If liveness checks the database, a DB outage makes Kubernetes restart every pod, which turns a dependency failure into a full outage.

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
            
            # Exponential backoff with FULL jitter: sleep a random amount in
            # [0, cap]. ±10% jitter still lets clients retry in near-lockstep.
            cap = min(base_delay * (exponential_base ** attempt), max_delay)
            total_delay = random.uniform(0, cap)
            
            print(f"Attempt {attempt + 1} failed, retrying in {total_delay:.2f}s")
            await asyncio.sleep(total_delay)
    
    raise last_exception  # Shouldn't reach here

# Usage:
# result = await retry(
#     fetch_url, "https://api.example.com",
#     max_retries=3,
#     base_delay=0.5,
# )
# Production rules: retry only idempotent operations (or use idempotency keys),
# only on transient errors (timeouts, 503, connection reset; never 4xx),
# keep the total within the caller's deadline, and cap retries with a
# retry budget or circuit breaker so retries don't amplify an outage.
# Libraries: tenacity, stamina.

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
        acquire_timeout: float = 5.0,
    ):
        self._factory = factory
        self._acquire_timeout = acquire_timeout
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
            return self._pool.get_nowait()          # idle connection available
        except asyncio.QueueEmpty:
            pass
        
        # Reserve a slot under the lock, but connect OUTSIDE it so one slow
        # connect doesn't serialize every other acquirer.
        async with self._lock:
            can_create = self._size < self._max_size
            if can_create:
                self._size += 1
        if can_create:
            try:
                return await self._factory()
            except BaseException:
                self._size -= 1                      # give the slot back
                raise
        
        # At capacity: wait for a release, but not forever
        async with asyncio.timeout(self._acquire_timeout):
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

In practice, use the driver's pool (`asyncpg.create_pool`, SQLAlchemy's async engine, `redis.asyncio.ConnectionPool`). A real pool also health-checks or resets connections on release, discards broken ones, enforces max lifetime and idle time, and exposes wait-time metrics. Pool exhaustion shows up first as acquire-latency spikes.

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
# ❌ open(file).read() (large/slow disks)  → await asyncio.to_thread(path.read_bytes) (aiofiles also uses threads)
# ❌ socket.recv(1024)                     → await asyncio.get_running_loop().sock_recv(sock, 1024)
# ❌ hidden blockers: sync DNS (socket.gethostbyname), logging to a slow handler,
#    json.dumps of a huge payload, pandas, bcrypt/argon2 hashing
# ❌ db.query("SELECT ...") (sync driver)  → await async_db.execute("SELECT ...")
# ❌ cpu_intensive()                       → await loop.run_in_executor(None, cpu_intensive)
```

### Pitfall 2: Forgotten `await`

```python
import asyncio

# ── ❌ Common mistake #1: calling without await ────────────
async def forgot_await():
    background_work()        # ❌ creates a coroutine object that never runs
    print("Function done")
    # RuntimeWarning: coroutine 'background_work' was never awaited

# ── ❌ Common mistake #2: fire-and-forget task ─────────────
async def fire_and_forget():
    asyncio.create_task(background_work())   # ❌ no reference kept
    # The task DOES start, but the loop holds only a weak reference: it can be
    # garbage-collected mid-flight, and its exception is only logged
    # ("Task exception was never retrieved") when it's collected.
    # Fix: keep it in a set (+ add_done_callback(set.discard)) or use a TaskGroup.

# ── ✅ Always await your coroutines ───────────────────────
async def correct_await():
    result = await some_work()  # ✅
    
    task = asyncio.create_task(background_work())
    await task  # ✅ Wait for task

# ── Debug: detect unawaited coroutines ─────────────────────
# Enable in development/CI (too slow for production):
# PYTHONASYNCIODEBUG=1 python app.py
# Or:
# asyncio.run(main(), debug=True)

# This will warn about:
# 1. Coroutines that were never awaited (with the creation traceback)
# 2. Callbacks that take too long (>100ms)
# 3. Resources that weren't properly closed
# Static checks catch most of these earlier: ruff's flake8-async (ASYNC) rules,
# RUF006 (dangling create_task), and mypy/pyright's unused-coroutine checks.
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
# requests            → httpx (sync + async API) / aiohttp
# psycopg2            → psycopg 3 (native async) / asyncpg
# redis-py            → redis.asyncio (redis-py 4.2+; the old aioredis was merged in and is dead)
# boto3 (sync)        → aioboto3 / aiobotocore
# Flask               → FastAPI / Quart (Flask 2.0+ allows async views, but each request still runs in a WSGI worker)
# Django ORM          → async API since Django 4.1 (aget, afilter...), but queries still
#                       run in a thread via sync_to_async under the hood
# SQLAlchemy          → SQLAlchemy 2.0 asyncio extension (AsyncSession) with asyncpg/psycopg
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
    print(shared_counter)  # 1 (verified): all 100 read 0 before any of them writes

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
# Use message passing (queues) instead of shared state.
# Rule: code between two awaits runs atomically (relative to other coroutines
# on the same loop). The race only exists when an await sits inside a
# read-modify-write, which in real code is usually I/O (cache check → DB → cache set).
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
    finally:
        await conn.close()  # runs on success, error AND cancellation

# Even better: use async context manager:
async def best_cleanup():
    async with get_connection() as conn:
        await conn.query("UPDATE ...")
    # Always cleaned up

# ── ⚠️ CancelledError since Python 3.8 ────────────────────
# CancelledError is a subclass of BaseException (not Exception)
# This means:
# except Exception: will NOT catch CancelledError
# You must catch asyncio.CancelledError explicitly (or BaseException)
```

### Debugging Tools

```python
import asyncio
import traceback

# ── 1. Enable debug mode (dev/CI) ──────────────────────────
# asyncio.run(main(), debug=True)   — see "Debug Mode" in section 4

# ── 1b. Inspect a LIVE process without restarting it (3.14+) ──
# python -m asyncio ps <PID>       # flat table of tasks, their coroutine stacks and awaiters
# python -m asyncio pstree <PID>   # tree of who-awaits-whom; flags await cycles (deadlocks)
# Uses the PEP 768 remote-debugging interface: needs the same privileges as a
# debugger (root/CAP_SYS_PTRACE on Linux, sudo on macOS). Before 3.14: py-spy dump.

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
        
        if not done:
            task.print_stack(limit=5)      # the task's suspended coroutine stack
        print()

# 3.14+: the full async call graph (who is awaiting this task), in-process:
#   asyncio.print_call_graph(task)
# * Task(name='fetch-user-1', id=0x...)
#   + Call stack:
#   |   File '.../asyncio/tasks.py', line 702, in async sleep()
#   |   File 'app.py', line 4, in async fetch_user()
#   + Awaited by:
#     * Task(name='request-1', id=0x...)
#       + Call stack:
#       |   File '.../asyncio/taskgroups.py', line 72, in async TaskGroup.__aexit__()
#       |   File 'app.py', line 7, in async handle_request()

# ── 3. Task timeout debugging ──────────────────────────────
async def debug_timeout():
    """Add logging to track timeout issues"""
    try:
        async with asyncio.timeout(5.0) as cm:
            # When timeout is reached:
            # cm.expired() will be True
            # The wrapped coroutine is cancelled
            result = await slow_operation()
    except TimeoutError:
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
| **True Parallelism** | ❌ No (single thread) | ❌ No (GIL); ✅ on the free-threaded 3.14t build | ✅ Yes (separate processes) |
| **Memory Overhead** | ~1 KB per suspended task (3.14, measured) | Stack reserved per thread (8 MB virtual by default on Linux; real RSS is much smaller) | A full interpreter per process: typically tens of MB RSS once your imports load |
| **Task Switching** | At await points | Anywhere (OS + GIL switch interval) | Anywhere (OS) |
| **Shared State** | ✅ Safe between awaits; locks only if an await sits in a critical section | ⚠️ Needs locks | ❌ Needs IPC / shared memory |
| **Practical Scale (rough)** | 10K–100K+ tasks | Hundreds to low thousands of threads | About one per CPU core |
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
# 5. You're working with file I/O and disk access (OS file I/O isn't async-pollable)

# ── Choose multiprocessing when ────────────────────────────
# 1. You have CPU-bound computation
# 2. You need true parallelism (multiple cores)
# 3. Fault isolation is important (one crash ≠ all crash)
# 4. You're doing data processing / ETL
# 5. NumPy, Pandas, image processing, ML inference
#    (NumPy and many native libs release the GIL, so threads may suffice: measure)

# ── Python 3.14 adds two more options ─────────────────────
# Free-threaded build (python3.14t): threads run Python in parallel,
#   if all your C extensions ship free-threaded wheels.
# InterpreterPoolExecutor (concurrent.futures, 3.14): one GIL per
#   subinterpreter in one process; data crosses by pickling/shareable types.
```

### Hybrid Patterns

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# ── Pattern 1: asyncio + ThreadPoolExecutor ───────────────
# Best for async applications that need to call sync I/O libs

DB_POOL = ThreadPoolExecutor(max_workers=10)   # created once; size = DB connection limit

async def hybrid_io(database_urls: list[str]):
    """Async orchestrator with sync database calls"""
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(DB_POOL, sync_db_query, url)
        for url in database_urls
    ]
    return await asyncio.gather(*tasks)

# ── Pattern 2: asyncio + ProcessPoolExecutor ──────────────
# Best for async applications with CPU-intensive subtasks

CPU_POOL = ProcessPoolExecutor(max_workers=4)  # created once at startup

async def hybrid_cpu(data_chunks: list):
    """Async orchestrator with parallel CPU processing"""
    loop = asyncio.get_running_loop()
    # One executor call per chunk, so chunks run on different processes in parallel
    processed = await asyncio.gather(*[
        loop.run_in_executor(CPU_POOL, cpu_intensive_batch, chunk)
        for chunk in data_chunks
    ])
    # I/O-bound result handling with asyncio
    return await asyncio.gather(*[save_result(item) for item in processed])

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
# For a long-lived loop that sync code submits work to repeatedly, see the
# AsyncBridge in Q12 (run_coroutine_threadsafe).
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

# What to expect (I/O part measured on 3.14, Apple Silicon):
#   sync_io      ≈ 12 s     (1000 × 10 ms, sequential, plus sleep overshoot)
#   threaded_io  ≈ 0.25 s   (1000 / 50 workers × 10 ms)
#   async_io     ≈ 0.02 s   (all 1000 sleeps overlap; one thread)
#   CPU part: threads ≈ sequential on the default build; processes ≈ 4x faster on 4 cores.
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

**Answer:** `asyncio.run()` is the high-level entry point for running async code (added in Python 3.7; since 3.11 it's a thin wrapper over `asyncio.Runner`). It:
1. Creates a new event loop (`loop_factory=` since 3.12, e.g. uvloop)
2. Sets it as the current event loop
3. Runs the provided coroutine until completion
4. Cancels any remaining tasks **and waits for them** to finish unwinding
5. Shuts down async generators and the default executor
6. Closes the event loop

It refuses to run inside an already running loop (`RuntimeError`). In 3.11+ the first Ctrl-C cancels the main task instead of raising `KeyboardInterrupt` somewhere random.

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
            pending = all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(gather(*pending, return_exceptions=True))
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
- **`gather()`**: Takes coroutines or awaitables (wraps coroutines in Tasks), runs them concurrently, returns results in **input order**. By default the first exception propagates to the caller immediately, but the other awaitables are **not cancelled**; they keep running. With `return_exceptions=True` it waits for all and puts exceptions in the result list. Cancelling the gather cancels all children.
- **`wait()`**: Takes an iterable of tasks/futures, returns `(done, pending)` sets. Supports `FIRST_COMPLETED`, `FIRST_EXCEPTION`, `ALL_COMPLETED` and a `timeout` (on timeout it just returns, without cancelling anything). Passing bare coroutines raises `TypeError` since 3.11.
- **Prefer `TaskGroup`** (3.11+) when "all or nothing" is what you mean: it cancels siblings on the first failure.

```python
# gather — ordered results
results = await asyncio.gather(coro1(), coro2(), coro3())

# wait — fine-grained control
tasks = [asyncio.create_task(coro()) for _ in range(5)]
done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
```
</details>

### Intermediate

<details>
<summary><b>Q4: Explain the event loop's three-phase cycle. What happens in each phase?</b></summary>

**Answer:** Each iteration of `BaseEventLoop._run_once()` does three things, in this order:

1. **I/O poll.** Call `selector.select(timeout)`, where `timeout` is `0` if callbacks are already ready, otherwise the time until the earliest timer (or block indefinitely if there are none). Ready file descriptors have their callbacks appended to `_ready`.
2. **Timer sweep.** Pop every `TimerHandle` whose deadline has passed from the `_scheduled` heap into `_ready`. (Cancelled timers are discarded lazily, and the heap is compacted when more than half of it is cancelled.)
3. **Run callbacks.** Run exactly the `len(_ready)` callbacks that were present at the start of this step, in FIFO order. Callbacks scheduled while these run wait for the next iteration, so a coroutine that keeps yielding can't starve I/O polling.

Every Task step (`Task.__step`) is just one of those callbacks, which is why a slow step (CPU work, a blocking call) delays *everything*: I/O, timers and every other task.

```python
def _run_once(self):
    # 1. Poll for I/O (don't block if work is already queued)
    timeout = 0 if self._ready else self._time_until_next_timer()  # None = block
    events = self._selector.select(timeout)
    self._process_events(events)

    # 2. Move expired timers to ready
    self._sweep_timers()

    # 3. Run a snapshot of the ready queue
    for _ in range(len(self._ready)):
        handle = self._ready.popleft()
        if not handle._cancelled:
            handle._run()
```
</details>

<details>
<summary><b>Q5: How does the `await` keyword work under the hood? Describe the protocol.</b></summary>

**Answer:** The `await` keyword is syntactic sugar for `yield from`. Here's the protocol:

1. When you `await` an object, Python calls `object.__await__()`
2. `__await__()` must return an iterator
3. The iterator yields up the whole `await` chain, typically yielding a pending `Future` (or `None` for a bare one-iteration yield)
4. The **Task** driving the outermost coroutine receives the Future and registers its wake-up method as a done-callback
5. When the Future completes, the callback is scheduled; the Task calls `coro.send(None)` (or `coro.throw(exc)` for cancellation), **not** `send(result)`
6. Execution resumes inside `Future.__await__`, which returns `self.result()`, and that becomes the value of the `await` expression

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
# - task_b (and the body of the async with) is cancelled
# - the group waits for task_b to finish unwinding
# - ExceptionGroup is raised with all non-cancellation errors
```
Benefits over `gather()`:
- No orphaned tasks
- Automatic cancellation on failure
- Proper exception handling with `except*`

What interviewers probe next: "What if a child is `while True`?" (the block never exits until it's cancelled). "How do you cap the group's total time?" (wrap it in `asyncio.timeout()`). "How do you let one child fail without killing the others?" (catch inside that child, or use a plain set of tasks plus `gather(return_exceptions=True)`).
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
# - CancelledError is a BaseException (not Exception) since 3.8
# - Prefer try/finally or async context managers for cleanup
# - Re-raise CancelledError; swallowing it breaks timeout(), TaskGroup and shutdown
# - Cancellation is delivered at the next await; CPU loops without awaits can't be cancelled
# - asyncio.shield() protects the INNER task; the awaiting caller still gets
#   CancelledError, so keep a reference to the inner task

async def critical_section():
    task = asyncio.create_task(financial_transaction())
    _keep.add(task)                         # strong ref (module-level set)
    task.add_done_callback(_keep.discard)
    return await asyncio.shield(task)
```
</details>

<details>
<summary><b>Q8: What is uvloop and how does it improve performance?</b></summary>

**Answer:** uvloop is a drop-in replacement for asyncio's event loop, written in Cython on top of libuv (the I/O library behind Node.js).

**Where the speed comes from:**
- The loop, polling (epoll/kqueue), timers, callback handles, and TCP/UDP/Unix transports and protocols run in C instead of Python
- Fewer Python-level allocations and function calls per I/O event
- The project claims **2–4x** over the default loop on its own networking benchmarks (echo/HTTP servers). Real apps gain less, in proportion to how much time they spend in the loop rather than in their own code. Measure.
- DNS goes through libuv's `getaddrinfo` thread pool (not c-ares)

```python
import uvloop
uvloop.run(main())                                           # uvloop >= 0.18
# asyncio.run(main(), loop_factory=uvloop.new_event_loop)    # stdlib form, 3.12+
# asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())    # legacy; policies deprecated in 3.14
```

**When to use:** High-throughput network services, proxies, WebSocket servers (Uvicorn picks it up automatically via `uvicorn[standard]`).
**When NOT to use:** CPU-bound work, apps dominated by ORM/serialization time, Windows (unsupported). Status (Oct 2026): uvloop 0.23 supports CPython 3.8–3.15, including free-threaded builds.
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
        self._max_concurrent = max_concurrent
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=self._max_concurrent,   # don't read the semaphore's private _value
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

**Backpressure and scale, which is what the question is really about:**

- Two limits: the semaphore (and `TCPConnector(limit=)`) caps **in-flight** requests, and the sliding window caps **starts per second**. Little's law: in-flight ≈ rate × latency, so 10,000 rps at 50 ms needs about 500 concurrent requests.
- Don't create 1M coroutines up front with `gather`. Feed work through a bounded `asyncio.Queue` with N worker tasks, so memory stays flat and producers slow down when the client is saturated.
- On HTTP 429/503, honour `Retry-After`, shrink the rate adaptively (AIMD), and retry only idempotent requests, with jittered backoff.
- 10,000 rps of JSON in one Python process is near the ceiling of one core (parsing + TLS). Plan for several processes (each with rate/N), uvloop, a fast JSON library, and HTTP keep-alive or HTTP/2. The sliding-window log costs O(rate) memory; a token bucket is O(1).
</details>

<details>
<summary><b>Q10: Explain how Python's async/await protocol maps to generators. Show how you could implement a minimal event loop that drives coroutines.</b></summary>

**Answer:** A native coroutine is driven like a generator: `send(None)` runs it to the next suspension point, and the value that comes out is whatever the innermost `__await__` yielded (a Future). A Task registers itself as a callback on that Future and calls `send(None)` again when it completes. The loop is just "poll for I/O, sweep timers, run ready callbacks". A runnable minimal version, the same design as asyncio:

```python
import heapq, itertools, time
from collections import deque

class Future:
    def __init__(self, loop):
        self._loop, self._done, self._result, self._callbacks = loop, False, None, []
    def set_result(self, value):
        self._done, self._result = True, value
        for cb in self._callbacks:
            self._loop.call_soon(cb)            # callbacks never run inline
    def __await__(self):
        if not self._done:
            yield self                          # suspend: hand the Future to the Task
        return self._result                     # resumed: this is the value of `await`

class Task:
    def __init__(self, coro, loop):
        self._coro, self._loop = coro, loop
        loop.call_soon(self._step)
    def _step(self):
        try:
            fut = self._coro.send(None)         # run until the next suspension point
        except StopIteration as e:
            print("task finished ->", e.value)
            return
        fut._callbacks.append(self._step)       # wake me when the Future is done

class Loop:
    def __init__(self):
        self._ready, self._timers, self._seq = deque(), [], itertools.count()
    def call_soon(self, cb):
        self._ready.append(cb)
    def call_later(self, delay, cb):
        heapq.heappush(self._timers, (time.monotonic() + delay, next(self._seq), cb))
    def sleep(self, delay, value=None):
        fut = Future(self)
        self.call_later(delay, lambda: fut.set_result(value))
        return fut
    def run(self):
        while self._ready or self._timers:
            # 1. block until the nearest timer (real asyncio: selector.select(timeout))
            if not self._ready and self._timers:
                time.sleep(max(0, self._timers[0][0] - time.monotonic()))
            # 2. move expired timers to the ready queue
            while self._timers and self._timers[0][0] <= time.monotonic():
                self._ready.append(heapq.heappop(self._timers)[2])
            # 3. run only the callbacks that were ready at the start of this pass
            for _ in range(len(self._ready)):
                self._ready.popleft()()

loop = Loop()
async def worker(name, delay):
    value = await loop.sleep(delay, f"{name} woke")
    print(value)
    return name
Task(worker("A", 0.2), loop)
Task(worker("B", 0.1), loop)
loop.run()
# B woke
# task finished -> B
# A woke
# task finished -> A
```

Under the hood, `await asyncio.sleep(0.1)` does the same: it creates a Future, schedules `call_later(0.1, futures._set_result_unless_cancelled, fut, None)`, and awaits the Future. The Task parks on it, the timer fires, the Task resumes with `send(None)`, and `Future.__await__` returns `None`.
</details>

<details>
<summary><b>Q11: How would you implement graceful shutdown for an async web server handling thousands of WebSocket connections?</b></summary>

**Answer:** Graceful means **stop intake → let in-flight work finish within a deadline → force-close the rest**, and it must fit inside the orchestrator's grace period (Kubernetes sends SIGTERM, then SIGKILL after `terminationGracePeriodSeconds`, 30 s by default).

1. On SIGTERM: fail the readiness probe so the load balancer stops routing new connections. (Keep serving for a few seconds; endpoint removal propagates asynchronously.)
2. Stop accepting: `server.close()`.
3. Tell clients to go: for WebSockets send a close frame with code **1001 (Going Away)** so clients reconnect to another pod, ideally with jitter so they don't stampede.
4. Drain with a deadline, then cancel stragglers and **await** their cleanup.
5. Close pools and clients in reverse order of startup.

A runnable TCP version (verified: the client gets its echo, then a clean EOF when the server stops):

```python
import asyncio, contextlib

class GracefulShutdownServer:
    def __init__(self, host: str, port: int, drain_timeout: float = 10.0):
        self.host, self.port = host, port
        self._drain_timeout = drain_timeout
        self._stopping = asyncio.Event()
        self._handlers: set[asyncio.Task] = set()

    async def serve(self) -> None:
        server = await asyncio.start_server(self._handle, self.host, self.port)
        await self._stopping.wait()
        server.close()                          # 1. stop accepting new connections
        # 2. handlers see _stopping and leave between messages
        #    (WebSocket: send close frame 1001 "going away" so clients reconnect elsewhere)
        if self._handlers:                      # 3. drain with a deadline
            _, pending = await asyncio.wait(self._handlers, timeout=self._drain_timeout)
            for t in pending:                   # 4. force-close stragglers
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()

    def stop(self) -> None:
        self._stopping.set()

    async def _handle(self, reader, writer) -> None:
        task = asyncio.current_task()           # start_server already runs us in a Task
        self._handlers.add(task)
        try:
            while not self._stopping.is_set():
                read = asyncio.ensure_future(reader.readline())
                stop = asyncio.ensure_future(self._stopping.wait())
                done, _ = await asyncio.wait({read, stop}, return_when=asyncio.FIRST_COMPLETED)
                stop.cancel()
                if read not in done:
                    read.cancel()
                    break                       # shutting down: leave between messages
                line = read.result()
                if not line:
                    break                       # client closed
                writer.write(b"echo: " + line)
                await writer.drain()
        finally:
            self._handlers.discard(task)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

async def demo():
    srv = GracefulShutdownServer("127.0.0.1", 8899)
    serve = asyncio.create_task(srv.serve())
    await asyncio.sleep(0.1)
    r, w = await asyncio.open_connection("127.0.0.1", 8899)
    w.write(b"hi\n"); await w.drain()
    print(await r.readline())           # b'echo: hi\n'
    srv.stop()
    await serve
    print("closed by server:", await r.read() == b"")   # True
asyncio.run(demo())
# b'echo: hi\n'
# closed by server: True
```

- In a real service, wire `stop()` to `loop.add_signal_handler(signal.SIGTERM, srv.stop)` (Unix only).
- Pitfalls: `asyncio.wait(..., timeout=)` does **not** cancel what's still pending. Cancelling without awaiting skips cleanup. Since 3.12, `Server.wait_closed()` waits for all active connections, so call it *after* draining. 3.13 added `Server.close_clients()` / `abort_clients()` for forced closes.
- Thousands of connections: spread the close frames out over time (jittered), and remember each handler's `finally` runs at shutdown, so keep it fast.
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
    
    def submit(self, coro, timeout: float = 10):
        """Run a coroutine on the background loop; call from SYNC code (blocks)"""
        future = asyncio.run_coroutine_threadsafe(
            coro, self._loop
        )                                   # -> concurrent.futures.Future
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()                 # also cancels the task on the loop
            raise
    
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

Never call `AsyncBridge.submit()` or `asyncio.run()` from code that is already running on an event loop thread. The first deadlocks (the loop waits on itself) and the second raises `RuntimeError`.
</details>

<details>
<summary><b>Q13: A production asyncio service is "stuck": latency is up, CPU is low, nothing in the logs. How do you find out what it's doing?</b></summary>

**30-second answer:** Low CPU plus high latency means tasks are waiting, not computing: on a lock, a pool, a semaphore, a slow dependency, or an await cycle. If CPU is high instead, something is blocking the loop. I'd attach to the live process: on 3.14, `python -m asyncio pstree <PID>` shows the await tree and flags cycles, and `python -m asyncio ps <PID>` lists every task with its coroutine stack. Before 3.14, `py-spy dump --pid` shows the threads (the loop thread blocked in `select` means the tasks are waiting). Then I check pool and semaphore saturation metrics and loop lag.

**Mechanics and tools:**

| Symptom | Likely cause | How to confirm |
|---|---|---|
| CPU ~100% on one core, all requests slow | Blocking call or CPU work on the loop | `py-spy dump` shows the loop thread inside your code, not `select`; loop-lag metric is high; debug mode logs "Executing ... took N seconds" |
| CPU low, latency high | Tasks waiting on an exhausted pool, semaphore or lock | `asyncio pstree/ps` (3.14): many tasks parked in `Queue.get` / `Semaphore.acquire` / pool `acquire`; pool wait-time metrics |
| A few requests hang forever | Missing timeout on a dependency; await cycle (deadlock) | `pstree` reports cycles; add `asyncio.timeout()` at every I/O boundary |
| Memory grows | Unbounded task creation or queues; tasks never finishing | `len(asyncio.all_tasks())` over time; `tracemalloc` snapshot diff |

- **Loop lag probe** (cheap enough for production): a task that does `await asyncio.sleep(0.1)` in a loop and records how late it wakes up. Export it as a histogram and alert on p99.
- **Name your tasks** (`create_task(coro, name=...)`), so `ps`/`pstree` output and logs are readable.
- `asyncio ps/pstree` use the PEP 768 remote-debugging interface: no restart needed, but they require debugger-level privileges (root / `CAP_SYS_PTRACE` in containers). `sys.remote_exec(pid, script)` (3.14) can run a diagnostic script inside the process, e.g. to dump `asyncio.all_tasks()`.

**What they probe next:** "How do you stop this from recurring?" (Timeouts at every boundary, bounded pools with acquire timeouts, loop-lag SLOs, `flake8-async` lint rules for blocking calls in async code, and load tests that saturate dependencies.)
</details>

---

> *Built for experienced Python engineers targeting Senior/Staff roles.*
> *Master async/await to build high-performance, concurrent systems at scale.*
