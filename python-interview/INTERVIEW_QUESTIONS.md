# 🐍 Python — Staff-Level Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer, 15+ years across systems infrastructure  \
> **Target Level:** Senior / Staff Engineer  \
> **Evaluation Focus:** Deep CPython internals, concurrency models, memory management, production system design  \
> **Version baseline:** CPython 3.14 (current stable as of October 2026; 3.15.0 is due in October 2026). Version-specific behaviour is called out inline.

Every question follows the same shape: a **30-second answer** you could say out loud, then the mechanism, then code, then trade-offs and what the interviewer probes next. All Python snippets were run on CPython 3.14 unless marked otherwise.

---

## Question 1: The GIL — Internals & When to Break Free

**Interviewer:** *"Explain the GIL. When does it actually block you, and how do you work around it at scale?"*

!!! tip "30-second answer"
    The GIL is a per-interpreter mutex that lets only one thread execute Python bytecode at a time. It exists so reference counting and interpreter internals don't need fine-grained locks. It's released around blocking I/O and by C code that opts out (NumPy, hashlib, zlib), so I/O-bound threads scale fine and pure-Python CPU work doesn't. Workarounds: processes, native code that releases the GIL, subinterpreters (one GIL each, `concurrent.interpreters` in 3.14), or the free-threaded build (officially supported but optional in 3.14).

### 🎯 Expected Answer (Staff Level)

**What the GIL actually is:** a lock on the interpreter state. A thread must hold it to touch Python objects. It protects reference counts, the allocator and type internals without a lock per object. Since 3.12 (PEP 684) each *subinterpreter* can have its own GIL, so "global" really means "per interpreter".

**How switching works (the "new GIL", Antoine Pitrou, CPython 3.2):**

- Before 3.2, the running thread released and re-acquired the GIL every 100 "ticks" (roughly bytecodes). On multicore machines this caused the *convoy effect*: the releasing CPU-bound thread usually won the race to re-acquire, starving I/O threads.
- Since 3.2 switching is time-based and request-driven:
    1. A thread that wants the GIL waits on a condition variable with a timeout of the *switch interval* (5 ms by default, `sys.getswitchinterval()` / `sys.setswitchinterval()`).
    2. If the timeout expires and the holder hasn't released, the waiter sets a `gil_drop_request` flag on the "eval breaker".
    3. The holder checks the eval breaker at safe points (backward jumps, function calls) and drops the GIL.
    4. *Forced switching*: the dropping thread then waits until another thread has actually taken the GIL, so it can't immediately re-grab it.
- The holder never releases "every 5 ms" on its own. If nobody is waiting, a CPU-bound thread runs uninterrupted.
- Blocking calls release the GIL explicitly (`Py_BEGIN_ALLOW_THREADS` around `read()`, `recv()`, `sleep()`, `select()`).

**When the GIL actually hurts:**

| Model | CPU-bound pure Python | I/O-bound |
|---|---|---|
| Threads (default build) | ❌ one core; often *slower* than serial from contention | ✅ GIL released while blocked |
| Threads (free-threaded 3.14t) | ✅ scales across cores (see Q11) | ✅ |
| Processes | ✅ N cores; pay pickling/IPC and per-process memory | ⚠️ works, but heavy for plain I/O |
| asyncio | ❌ one thread; CPU work blocks the loop | ✅ best for very high connection counts |
| Subinterpreters (3.14) | ✅ one GIL each; data must be shared explicitly | ⚠️ possible, rarely the right tool |

**Fighting the GIL in production:**

```python
# Strategy 1: processes + shared memory (avoid pickling large arrays)
import multiprocessing as mp
from multiprocessing import shared_memory
import numpy as np

def worker(shm_name: str, shape: tuple[int, ...], dtype, lo: int, hi: int) -> None:
    shm = shared_memory.SharedMemory(name=shm_name)
    arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
    arr[lo:hi] *= 2                      # each worker owns a disjoint slice
    del arr                              # drop the view before closing the mapping
    shm.close()

if __name__ == "__main__":               # required with the spawn start method
    shape, dtype = (8_000_000,), np.float64
    shm = shared_memory.SharedMemory(create=True, size=np.dtype(dtype).itemsize * shape[0])
    arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
    arr[:] = 1.0
    n = mp.cpu_count()
    step = shape[0] // n
    procs = [mp.Process(target=worker,
                        args=(shm.name, shape, dtype, i * step, (i + 1) * step if i < n - 1 else shape[0]))
             for i in range(n)]
    for p in procs: p.start()
    for p in procs: p.join()
    print(arr.sum())                     # 16000000.0
    del arr
    shm.close()
    shm.unlink()                         # exactly one owner unlinks, or the segment leaks
```

```cython
# Strategy 2: native code that releases the GIL (Cython)
# The loop body touches no Python objects, so it can run with the GIL released,
# letting other Python threads run in parallel.
def scale(double[::1] data, double factor):
    cdef Py_ssize_t i
    with nogil:
        for i in range(data.shape[0]):
            data[i] *= factor
```

```python
# Strategy 3: subinterpreters (PEP 734, Python 3.14+): one GIL per interpreter
from concurrent.futures import InterpreterPoolExecutor

def cpu_heavy(n: int) -> int:
    return sum(i * i for i in range(n))

if __name__ == "__main__":
    with InterpreterPoolExecutor(max_workers=4) as pool:
        print(list(pool.map(cpu_heavy, [10, 100, 1_000])))   # [285, 328350, 332833500]
```

**Trade-offs and failure modes**

- Processes: pickling cost, memory duplication, `fork` + threads is unsafe (3.14 changed the default start method on Linux from `fork` to `forkserver`; macOS has used `spawn` since 3.8).
- Native code: only helps if the hot loop really runs without Python objects; one stray `object` access re-acquires the GIL.
- Subinterpreters: objects aren't shared; arguments and results cross by pickling or via shareable types and `concurrent.interpreters.Queue`; many C extensions don't support them yet.
- Free-threaded build: separate wheels (`cp314t`), extensions that don't declare support re-enable the GIL at import, and your own code's races become real.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Deep internals** | Explains request-driven switching (switch interval, drop request, forced switching) and *why* the GIL exists (refcounting) |
| **Practical experience** | Has shipped a workaround: processes + shared memory, native code that releases the GIL, or a move to free-threading |
| **Trade-off awareness** | Knows threads are fine for I/O and that multiprocessing costs serialization and memory |
| **Modern Python** | Per-interpreter GIL (3.12), `concurrent.interpreters` (3.14), free-threaded build officially supported in 3.14 (PEP 779) but not the default |

**What they probe next:** "Is `x += 1` on a shared int thread-safe with the GIL?" (No: it's load, add, store, and a switch can happen between them.) "Why can a CPU-bound thread make an I/O thread's latency worse?" (It holds the GIL up to the switch interval after the I/O completes.) "What breaks under free-threading?" (See Q11.)

---

## Question 2: Async/Await — Event Loop Internals

**Interviewer:** *"Walk me through what happens when you `await` a coroutine. How does the event loop schedule it?"*

!!! tip "30-second answer"
    A coroutine is a suspendable function. `await x` calls `x.__await__()` and delegates to it like `yield from`. Awaiting another coroutine just runs it inline. Only when something awaits a pending `Future` does that Future get yielded all the way up to the `Task` driving the coroutine. The Task registers a done-callback on the Future and returns to the loop. Each loop iteration waits for I/O with a timeout set by the nearest timer, moves expired timers to the ready queue, then runs the callbacks that were ready at the start of the pass. When the Future completes, its callback schedules the Task again, which calls `coro.send(None)`, and `__await__` returns `future.result()`.

### 🎯 Expected Answer

**A toy loop that works the same way as asyncio (runnable):**

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

**How this maps to real asyncio (`BaseEventLoop._run_once`, `Task.__step`):**

- The selector (`epoll`/`kqueue`) is polled with `timeout = 0` if callbacks are ready, else the time until the nearest timer. Ready I/O callbacks are queued.
- Expired `TimerHandle`s move from a heap to `_ready`.
- Only the `len(_ready)` callbacks present at the start of the pass run. Callbacks scheduled during the pass wait for the next iteration, so I/O is polled regularly.
- The Task never calls `coro.send(result)`. It always resumes with `send(None)` (or `throw()` on cancellation), and the result comes back through `Future.__await__` → `return self.result()`.
- Real `Future.__await__` sets `_asyncio_future_blocking = True` before yielding. `Task.__step` checks that flag to reject bare `yield` inside coroutines.
- `await other_coro()` doesn't create a Task or touch the loop. Concurrency only comes from `create_task`, `gather` or `TaskGroup`.

**uvloop:**

```python
import asyncio
import uvloop

async def main() -> None:
    ...

uvloop.run(main())                                   # preferred since uvloop 0.18
# Equivalent stdlib form (3.12+): asyncio.run(main(), loop_factory=uvloop.new_event_loop)
```

- uvloop reimplements the event loop in Cython on top of libuv (the I/O library behind Node.js). Transports, protocols, timers and the polling loop run in C instead of Python. DNS (`getaddrinfo`) runs on libuv's thread pool.
- The project claims "2–4x faster" than the default loop on its own networking benchmarks. Real gains depend on how much time your app spends in the loop versus in your own code, so measure. uvloop 0.23 (October 2026) ships wheels for 3.8–3.15, including free-threaded builds. It doesn't support Windows.
- Don't use `asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())` in new code: the policy system is deprecated in 3.14 and slated for removal in 3.16.

**Structured concurrency with `TaskGroup` (3.11+):**

```python
async def load_profile(client_id: int) -> dict:
    try:
        async with asyncio.TaskGroup() as tg:
            meta = tg.create_task(fetch_metadata(client_id))
            hist = tg.create_task(fetch_history(client_id))
    except* TimeoutError as eg:              # child failures arrive as an ExceptionGroup
        raise ServiceUnavailable(client_id) from eg
    # Leaving the block means every child finished successfully
    return {"meta": meta.result(), "history": hist.result()}
```

- If a child raises, the TaskGroup cancels its siblings, waits for them, and raises an `ExceptionGroup` of the non-cancellation errors.
- If the *enclosing* task is cancelled, you get a plain `CancelledError`, not a group. Don't catch and swallow it.

**Staff-level insight — `gather()` doesn't do what people think (verified):**

```python
import asyncio, time

async def request_a():
    await asyncio.sleep(0.1)
    raise ValueError("a failed")

async def request_b():
    await asyncio.sleep(1)
    return "b"

async def with_gather():
    t0 = time.perf_counter()
    try:
        await asyncio.gather(request_a(), request_b())
    except ValueError as e:
        print(f"gather raised {e!r} after {time.perf_counter() - t0:.1f}s")
    # request_b is still running in the background, orphaned:
    print("tasks still alive:", len(asyncio.all_tasks()) - 1)

async def with_taskgroup():
    t0 = time.perf_counter()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(request_a())
            tg.create_task(request_b())
    except* ValueError as eg:
        print(f"TaskGroup raised {eg.exceptions!r} after {time.perf_counter() - t0:.1f}s")
    print("tasks still alive:", len(asyncio.all_tasks()) - 1)

async def main():
    await with_gather()
    await asyncio.sleep(1)    # let the orphan finish
    await with_taskgroup()

asyncio.run(main())
# gather raised ValueError('a failed') after 0.1s
# tasks still alive: 1
# TaskGroup raised (ValueError('a failed'),) after 0.1s
# tasks still alive: 0
```

- `gather()` without `return_exceptions` fails fast but **doesn't cancel the siblings**. They keep running and their errors may never be retrieved.
- `gather(..., return_exceptions=True)` waits for everything.
- `asyncio.wait(..., return_when=FIRST_EXCEPTION)` needs Tasks: since 3.11, passing bare coroutines raises `TypeError: Passing coroutines is forbidden, use tasks explicitly.` You must also cancel `pending` yourself.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Protocol knowledge** | `await` → `__await__` → `yield from`; only a pending Future actually suspends the Task |
| **Event loop mechanics** | Poll with a timer-derived timeout → expire timers → run a snapshot of `_ready` |
| **Production experience** | Has found a blocking call on the loop (`loop.slow_callback_duration`, debug mode), used `python -m asyncio ps/pstree <PID>` (3.14) or `asyncio.print_call_graph()` to inspect a live process |
| **Modern features** | TaskGroup, `asyncio.timeout()` (3.11), `except*`, eager task factory (3.12), `asyncio.run(loop_factory=...)` (3.12) |

**What they probe next:** "What happens if you call `time.sleep(1)` inside a coroutine?" (The whole loop stalls; use `await asyncio.to_thread(...)`.) "Can several coroutines await the same Task?" (Yes: a Future supports many awaiters and every one gets the result. But cancelling one awaiter with `wait_for` or `timeout` cancels the shared Task for all of them; wrap it in `asyncio.shield()` if that's wrong.) "Why must you keep a reference to `create_task()` results?" (The loop holds only weak references, so an unreferenced Task can be garbage-collected mid-flight.)

---

## Question 3: Metaclasses & Descriptors — The Object Model Under the Hood

**Interviewer:** *"Design a Django-style ORM field system. How do metaclasses and descriptors make it work?"*

!!! tip "30-second answer"
    Each field is a *data descriptor* (`__get__` + `__set__`), so `obj.age = 200` runs validation, and data descriptors take priority over the instance `__dict__`. `__set_name__` tells each field its attribute name when the class is created. A metaclass (or the lighter `__init_subclass__`) runs once per model class to collect the fields, compute the table name and build SQL. Since PEP 487 (3.6), `__set_name__` and `__init_subclass__` cover most needs that used to require a metaclass.

### 🎯 Expected Answer

**Class creation order (verified):** for `class Child(Base): d = D()` where `Base` uses metaclass `Meta`:

```text
1. Meta.__prepare__            → namespace dict for the class body
   (class body executes into that namespace)
2. Meta.__new__ → type.__new__  → creates the class object, and inside type.__new__:
3.     D.__set_name__(Child, "d")   for every descriptor in the namespace
4.     Base.__init_subclass__(Child)
5. back in Meta.__new__ (after super().__new__ returns)
6. Meta.__init__
```

**The fields (descriptors):**

```python
import re
from abc import ABC, abstractmethod
from typing import Any

class Field(ABC):
    """Data descriptor: owns validation and storage for one attribute."""
    sql_type = "TEXT"

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name                  # called by type.__new__ (PEP 487, 3.6+)

    def __get__(self, obj: object | None, objtype: type | None = None):
        if obj is None:
            return self                   # User.email -> the Field itself
        return obj.__dict__[self.name]    # value lives in the instance dict

    def __set__(self, obj: object, value: Any) -> None:
        self.validate(value)
        obj.__dict__[self.name] = value   # same key as the field is fine: data
                                          # descriptors beat the instance dict

    @abstractmethod
    def validate(self, value: Any) -> None: ...

class CharField(Field):
    def __init__(self, max_length: int = 255):
        self.max_length = max_length
        self.sql_type = f"VARCHAR({max_length})"

    def validate(self, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{self.name} must be str, got {type(value).__name__}")
        if len(value) > self.max_length:
            raise ValueError(f"{self.name} exceeds {self.max_length} chars")

class IntegerField(Field):
    sql_type = "INTEGER"

    def __init__(self, min_value: int | None = None, max_value: int | None = None):
        self.min_value, self.max_value = min_value, max_value

    def validate(self, value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{self.name} must be int")
        if self.min_value is not None and value < self.min_value:
            raise ValueError(f"{self.name} must be >= {self.min_value}")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"{self.name} must be <= {self.max_value}")
```

**The metaclass and base model:**

```python
class ModelMeta(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)  # __set_name__ runs in here
        fields: dict[str, Field] = {}
        for base in reversed(cls.__mro__[1:]):              # inherited fields first
            fields.update(getattr(base, "_fields", {}))
        fields.update({k: v for k, v in namespace.items() if isinstance(v, Field)})
        cls._fields = fields
        cls._table = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower() + "s"
        cols = ",\n".join(f"  {n} {f.sql_type} NOT NULL" for n, f in fields.items())
        cls._ddl = f"CREATE TABLE IF NOT EXISTS {cls._table} (\n{cols}\n);"
        return cls

class Model(metaclass=ModelMeta):
    def __init__(self, **kwargs: Any) -> None:
        unknown = kwargs.keys() - self._fields.keys()
        if unknown:
            raise TypeError(f"unknown fields: {sorted(unknown)}")
        for name, value in kwargs.items():
            setattr(self, name, value)    # goes through Field.__set__

    def insert_sql(self) -> tuple[str, list[Any]]:
        cols = list(self._fields)
        marks = ", ".join("?" for _ in cols)
        return (f"INSERT INTO {self._table} ({', '.join(cols)}) VALUES ({marks})",
                [getattr(self, c) for c in cols])
```

**Usage (verified output):**

```python
class UserAccount(Model):
    email = CharField(max_length=255)
    age = IntegerField(min_value=0, max_value=150)

print(UserAccount._ddl)
# CREATE TABLE IF NOT EXISTS user_accounts (
#   email VARCHAR(255) NOT NULL,
#   age INTEGER NOT NULL
# );
u = UserAccount(email="alice@example.com", age=30)
print(u.insert_sql())
# ('INSERT INTO user_accounts (email, age) VALUES (?, ?)', ['alice@example.com', 30])
u.age = 200        # ValueError: age must be <= 150
UserAccount.email  # the CharField descriptor itself (obj is None in __get__)
```

**Staff-level insight — you often don't need the metaclass:**

```python
class Model:
    _fields: dict[str, Field] = {}

    def __init_subclass__(cls, **kwargs):          # runs once per subclass, no metaclass
        super().__init_subclass__(**kwargs)
        cls._fields = {**cls._fields,
                       **{k: v for k, v in vars(cls).items() if isinstance(v, Field)}}
```

- Before PEP 487 you had to write `email = OldField(name="email")` because a descriptor couldn't learn its own name. `__set_name__` fixes that, and `__init_subclass__` handles registries and per-subclass setup.
- Metaclasses are still needed when you must control the namespace (`__prepare__`), change `isinstance` behaviour (`__instancecheck__`, as `ABCMeta` does), or customise class-level operators (`Enum` iteration, `Model.objects`-style class attributes).
- **Metaclass conflict:** `class C(A, B)` fails with `TypeError: metaclass conflict` if A's and B's metaclasses aren't in a subclass relationship. That's a common pain when mixing ORMs, ABCs and Protocols.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Protocol chaining** | Knows the order: `__prepare__` → body → `type.__new__` (`__set_name__`, then `__init_subclass__`) → metaclass `__init__` |
| **Descriptor precedence** | Data descriptor > instance `__dict__` > non-data descriptor (this is why methods can be shadowed but properties can't) |
| **PEP history** | Explains why PEP 487 removed most metaclass use cases |
| **Limitations** | Metaclass conflicts; magic that's hard to type-check; `dataclass_transform` (PEP 681) to tell type checkers about generated `__init__`s |

**What they probe next:** "Where is attribute lookup implemented?" (`object.__getattribute__`: type MRO lookup for data descriptors first, then the instance dict, then non-data descriptors and class attributes, then `__getattr__`.) "How do `property`, `classmethod` and functions relate to descriptors?" (All three are descriptors; a function's `__get__` produces the bound method.)

---

## Question 4: Memory Management — CPython's Allocator & GC

**Interviewer:** *"A production service has a memory leak. Walk me through how you'd find and fix it using only CPython internals."*

!!! tip "30-second answer"
    CPython frees most objects immediately through reference counting. A separate generational *cycle* collector handles reference cycles. A "leak" in Python is almost always objects that are still reachable: an unbounded cache, a registry or listener list, a stored exception holding frames, or tasks that never finish. Process RSS can also stay high because the allocator doesn't return partly used arenas to the OS. My workflow: confirm growth with RSS metrics, then take two `tracemalloc` snapshots and diff them by allocation site. Then find who holds the objects (`gc.get_referrers`, `objgraph`), fix the ownership (bounded caches, weak references, explicit cleanup) and verify with a soak test.

### 🎯 Expected Answer

**The CPython memory stack:**

```text
┌───────────────────────────────────────────────────────────────┐
│ Python objects: PyObject header = ob_refcnt + ob_type          │
│ (+ ob_size for variable-size objects; GC-tracked containers    │
│  carry an extra GC header)                                     │
├───────────────────────────────────────────────────────────────┤
│ Allocator domains:  PyMem_RawMalloc  → system malloc           │
│                     PyMem_Malloc / PyObject_Malloc → pymalloc  │
├───────────────────────────────────────────────────────────────┤
│ pymalloc (requests ≤ 512 bytes; larger go to malloc):          │
│   arenas (mmap'd)  →  pools (one size class each)  →  blocks   │
│   64-bit, 3.10+: 1 MiB arenas, 16 KiB pools                    │
│   (older: 256 KiB arenas, 4 KiB pools)                         │
│   blocks in 16-byte size classes on 64-bit (16, 32, … 512)     │
│ Free-threaded build (3.13t+): mimalloc instead of pymalloc     │
└───────────────────────────────────────────────────────────────┘
The cycle GC sits beside this stack. It isn't an allocator layer.
```

- An arena is only returned to the OS when **every** pool in it is empty. A few long-lived objects scattered across arenas keep RSS high after a spike. That's fragmentation, not a leak. `sys._debugmallocstats()` shows it.

**Reference counting vs the cycle collector:**

```python
class Node:
    def __init__(self):
        self.next = None

a, b = Node(), Node()
a.next, b.next = b, a      # cycle
del a, b                   # each refcount is still 1: refcounting alone can't free them
import gc
print(gc.collect() >= 2)   # True: the cycle collector found and freed them
```

- The collector only tracks *container* objects (lists, dicts, class instances…). It finds groups whose references all come from inside the group.
- Generational thresholds (`gc.get_threshold()`): `(700, 10, 10)` through 3.12, `(2000, 10, 10)` in 3.13. Gen 0 runs when allocations minus deallocations of tracked objects exceed the first number.
- **3.14 caveat:** 3.14.0–3.14.4 shipped an *incremental* collector with two generations. It was **reverted to the 3.13 generational GC in 3.14.5** after reports of significant memory pressure in production. Pin your patch version if you benchmark GC behaviour.
- Objects with `__del__` in cycles have been collectable since PEP 442 (3.4). `gc.garbage` now mostly fills only with `gc.DEBUG_SAVEALL`.
- Production knobs: `gc.freeze()` before forking workers (keeps the parent's objects out of the collector so copy-on-write pages aren't touched), or raising thresholds for allocation-heavy services. Don't use `gc.disable()` unless you can prove there are no cycles.

**Diagnosing a leak with only the stdlib (verified):**

```python
import gc, time, tracemalloc

# 1. GC pause visibility: gc.callbacks is a plain list (not a decorator)
_t0 = 0.0
def gc_timer(phase, info):
    global _t0
    if phase == "start":
        _t0 = time.perf_counter()
    elif info["generation"] == 2:   # "stop": info also has collected / uncollectable
        print(f"gen2 GC {1000*(time.perf_counter()-_t0):.2f} ms, "
              f"collected={info['collected']}")
gc.callbacks.append(gc_timer)

# 2. A leak: an unbounded module-level cache
_cache = {}
def handle(request_id: int) -> None:
    _cache[request_id] = bytearray(1024)     # never evicted

tracemalloc.start(25)                        # keep 25 frames per allocation
before = tracemalloc.take_snapshot()
for i in range(10_000):
    handle(i)
after = tracemalloc.take_snapshot()
for stat in after.compare_to(before, "lineno")[:1]:
    print(stat)
# leak.py:17: size=10.6 MiB (+10.6 MiB), count=20001 (+20001), average=555 B
```

- Step 3 is finding the owner: `gc.get_referrers(obj)` (stdlib) or `objgraph.show_growth()` / `objgraph.show_backrefs()` (third-party) to draw the chain back to a module global.
- In production, attach without restarting: `py-spy dump` for stacks, `memray attach <pid>` for allocations, and in 3.14 `sys.remote_exec(pid, script)` (PEP 768) to run a `tracemalloc` snippet inside the live process.

**Common production leak patterns:**

```python
# Pattern 1: storing exceptions keeps whole stacks alive
class Job:
    def run(self):
        try:
            step()
        except Exception as e:
            self.last_error = e    # e.__traceback__ → frames → every local in every frame
            # Fix: store what you need (repr(e), traceback.format_exc() -> str),
            # or call traceback.clear_frames(e.__traceback__)
# Note: `except E as e` deletes `e` at the end of the block (PEP 3110) precisely to avoid
# the frame → traceback → frame cycle. Re-binding it to self/global defeats that.
```

```python
# Pattern 2: caches that pin objects
import functools

class Repo:
    @functools.lru_cache(maxsize=None)   # BUG: unbounded, and `self` is part of every key,
    def get(self, key: str) -> bytes:    # so every Repo instance is kept alive forever
        ...
# Fix: bound the cache, cache a module-level function keyed by ids, or use
# cachetools.TTLCache. (Unhashable arguments don't leak; they raise TypeError.)
```

```python
# Pattern 3: registries, listeners and tasks that outlive their owner
_listeners: list = []
def subscribe(cb): _listeners.append(cb)   # bound method → keeps its instance alive
# Fix: weakref.WeakMethod / WeakSet, or return an unsubscribe handle.
# asyncio variant: a set of background tasks you add to but never discard.
```

**Staff-level insight — `__slots__` and the 3.11+ object layout (measured with `tracemalloc`, 100k instances of a two-attribute class, 64-bit):**

| CPython | Regular class (bytes/instance) | `__slots__` class |
|---|---|---|
| 3.10 | ~152 (object + separate `__dict__`) | 48 |
| 3.11–3.14 | ~80–88 (attribute values stored inline, `__dict__` created only if you ask for it) | 48 |

- `__slots__` still saves roughly 40–45% per instance in modern CPython (about 3x on 3.10), and it blocks accidental new attributes.
- Costs: no per-instance `__dict__` (unless you add it to the slots), no weak references unless you include `'__weakref__'`, and multiple inheritance from two classes with non-empty slots fails.
- `@dataclass(slots=True)` (3.10+) generates them for you.
- `sys.getsizeof()` is shallow (48 for both classes above) and can't measure this. Use `tracemalloc` or `pympler.asizeof`.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Allocator model** | Arena → pool → block, 512-byte cutoff, why RSS doesn't drop (fragmentation) |
| **GC vs refcounting** | Cycle collector only for containers; thresholds; 3.14's incremental GC and its reversion in 3.14.5 |
| **Tool experience** | `tracemalloc` snapshot diffs, `gc.get_referrers`, `objgraph`, `memray`, `py-spy` |
| **Leak patterns** | Stored exceptions/tracebacks, unbounded or `self`-keyed caches, listener registries, never-finishing tasks |

**What they probe next:** "RSS grows but `tracemalloc` shows flat Python allocations: now what?" (Native allocations from C extensions or glibc malloc arenas: try `memray --native`, `MALLOC_ARENA_MAX`, or jemalloc.) "Why do forked workers' memory usage creep up even when they're idle?" (Refcount writes touch copy-on-write pages; `gc.freeze()` and immortal objects (PEP 683, 3.12) help.)

---

## Question 5: Type System — Protocols, Generics, and Variance at Scale

**Interviewer:** *"Design a type-safe event bus that dispatches typed events to typed handlers. Handle covariance and contravariance correctly."*

!!! tip "30-second answer"
    A handler *consumes* events, so it's **contravariant** in the event type: a handler for `Event` can be used where a handler for `UserCreated` is required. It *produces* results, so it's **covariant** in the result type. I'd model the handler as a `Protocol` (structural, no inheritance needed) and make `subscribe` generic so the checker ties the event class to the handler's parameter type. Dispatch walks the event's MRO so base-class handlers also fire. With PEP 695 syntax (3.12+), the checker infers variance from usage.

### 🎯 Expected Answer

**A runnable, type-checked event bus (passes `mypy --strict` and pyright; Python 3.12+ syntax):**

```python
import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

@dataclass(frozen=True, kw_only=True)
class Event:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass(frozen=True, kw_only=True)
class UserCreated(Event):
    user_id: str
    email: str

@dataclass(frozen=True, kw_only=True)
class OrderPlaced(Event):
    order_id: str
    amount: float

# PEP 695 syntax (3.12+): variance of E and R is inferred from usage.
# E only appears as a parameter -> contravariant; R only as a return -> covariant.
class Handler[E: Event, R](Protocol):
    def __call__(self, event: E, /) -> Awaitable[R]: ...

class EventBus:
    def __init__(self) -> None:
        self._subs: defaultdict[type[Event], list[Handler[Any, Any]]] = defaultdict(list)

    def subscribe[E: Event](self, event_type: type[E], handler: Handler[E, object]) -> None:
        self._subs[event_type].append(handler)

    def on[E: Event, R](self, event_type: type[E]
                        ) -> Callable[[Callable[[E], Awaitable[R]]], Callable[[E], Awaitable[R]]]:
        def register(fn: Callable[[E], Awaitable[R]]) -> Callable[[E], Awaitable[R]]:
            self.subscribe(event_type, fn)
            return fn
        return register

    async def publish(self, event: Event) -> list[object]:
        # Walk the MRO so a handler for Event also sees UserCreated.
        handlers = [h for cls in type(event).__mro__ for h in self._subs.get(cls, [])]
        return list(await asyncio.gather(*(h(event) for h in handlers)))

bus = EventBus()

@bus.on(UserCreated)
async def send_welcome(event: UserCreated) -> bool:
    return True

async def audit(event: Event) -> str:          # handles ANY event
    return f"audit:{type(event).__name__}"

bus.subscribe(UserCreated, audit)   # OK: Handler[Event, str] <: Handler[UserCreated, object]
# bus.subscribe(OrderPlaced, send_welcome)  # type error: needs a handler that accepts OrderPlaced

async def main() -> None:
    print(await bus.publish(UserCreated(user_id="u1", email="a@example.com")))

asyncio.run(main())
# [True, 'audit:UserCreated']
```

- Production gaps worth naming: one failing handler fails the `gather` (use `return_exceptions=True` or a TaskGroup per policy), no ordering guarantees, and no retry or dead-letter. An in-process bus is not durable. If events must survive a crash, write them to an outbox table.

**Variance in one table** (`Dog <: Animal`):

| Kind | Rule | Python examples | Why |
|---|---|---|---|
| Covariant | `C[Dog] <: C[Animal]` | `Sequence`, `frozenset`, `tuple`, `Callable` return type | Read-only producers: whatever comes out is an Animal |
| Contravariant | `C[Animal] <: C[Dog]` | `Callable` parameters, handlers, sinks | A consumer of any Animal can consume Dogs |
| Invariant | neither | `list`, `dict`, `set`, mutable generics | You can both put and take: allowing either direction lets a Cat into a `list[Dog]` |

```python
# Pre-3.12 spelling of the same idea:
from typing import Generic, TypeVar
T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)

class Source(Generic[T_co]):
    def get(self) -> T_co: ...
class Sink(Generic[T_contra]):
    def put(self, item: T_contra) -> None: ...
```

**Protocols: structural typing, and the `runtime_checkable` trap (verified):**

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class SupportsLessThan(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...

isinstance({}, SupportsLessThan)   # True! object defines __lt__ (it returns NotImplemented)
sorted([{"a": 1}, {"b": 2}])       # TypeError: '<' not supported between instances of 'dict' and 'dict'
```

- `isinstance` against a runtime-checkable Protocol only checks that the attributes **exist**. It checks neither signatures nor types, and it's slow.
- Static checkers are stricter: typeshed doesn't declare `dict.__lt__`, so `sorted(list_of_dicts)` is flagged statically.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Variance mastery** | Producer → covariant, consumer → contravariant, mutable → invariant; can explain *why* `list` is invariant |
| **Protocol usage** | Structural typing for plug-in boundaries; knows the `runtime_checkable` limits |
| **Modern syntax** | PEP 695 type parameters and `type` aliases (3.12), `Self` (PEP 673, 3.11), `TypeIs` (PEP 742, 3.13), `@override` (PEP 698, 3.12) |
| **Actual production** | Runs mypy or pyright strictly in CI, uses `reveal_type` / `assert_type`, knows annotations are lazily evaluated in 3.14 (PEP 649/749) |

**What they probe next:** "Why is `Callable[[Animal], None]` assignable to `Callable[[Dog], None]` but not vice versa?" "How do type checkers handle `**kwargs` forwarding?" (`ParamSpec`, PEP 612.) "Generics are erased at runtime: how do you dispatch by type then?" (Explicit `type[E]` keys, as in `subscribe`.)

---

## Question 6: Context Managers & Generators — Coroutines Before `async`

**Interviewer:** *"Implement a database connection pool using only generators (no asyncio). Then explain how generators enable async/await under the hood."*

!!! tip "30-second answer"
    `@contextmanager` turns a generator into a context manager. The code before `yield` is `__enter__`, the yielded value is what `as` binds, and a `try/finally` around the `yield` guarantees the connection goes back to the pool even if the body raises. The generator *protocol* (`send`, `throw`, `close`, `yield from`) is exactly what native coroutines reuse: `await` is `yield from` restricted to awaitables, and the event loop drives coroutines with `send(None)` and `throw()`.

### 🎯 Expected Answer

```python
import threading, time
from collections.abc import Iterator
from contextlib import contextmanager
from queue import Empty, LifoQueue

class Connection:
    def __init__(self, conn_id: int) -> None:
        self.conn_id = conn_id
    def query(self, sql: str) -> str:
        time.sleep(0.01)                          # simulated I/O (releases the GIL)
        return f"conn-{self.conn_id}: {sql}"

class ConnectionPool:
    def __init__(self, max_size: int = 10, acquire_timeout: float = 5.0) -> None:
        self._idle: LifoQueue[Connection] = LifoQueue()   # LIFO keeps hot connections warm
        self._max, self._timeout = max_size, acquire_timeout
        self._created = 0
        self._lock = threading.Lock()                     # guards _created only

    def _get(self) -> Connection:
        try:
            return self._idle.get_nowait()
        except Empty:
            pass
        with self._lock:                                  # reserve a slot, never block here
            can_create = self._created < self._max
            if can_create:
                self._created += 1
                conn_id = self._created
        if can_create:
            return Connection(conn_id)                    # slow connect happens outside the lock
        return self._idle.get(timeout=self._timeout)      # raises queue.Empty on timeout

    @contextmanager
    def acquire(self) -> Iterator[Connection]:
        conn = self._get()
        try:
            yield conn
        finally:
            self._idle.put(conn)                          # returned even if the body raised

pool = ConnectionPool(max_size=3)
seen = set()
def work(i: int) -> None:
    with pool.acquire() as conn:
        seen.add(conn.query(f"SELECT {i}").split(":")[0])
threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
for t in threads: t.start()
for t in threads: t.join()
print(sorted(seen))   # ['conn-1', 'conn-2', 'conn-3']
```

- **Design points interviewers look for:** never hold a lock while connecting or blocking. (The naive version, which calls a lock-taking `_create()` while already holding the same non-reentrant `Lock`, deadlocks.) Use a bounded size and an acquire timeout (fail fast instead of piling up threads). Give connections back in `finally`.
- **Gaps a real pool fills:** if `Connection()` raises, the reserved slot leaks (decrement `_created` in an `except`). It also needs health checks on checkout, max lifetime/idle eviction (to survive DB failovers and NAT idle timeouts), and discarding a connection that's mid-transaction or broken instead of returning it.

**The generator protocol (verified):**

```python
def coroutine():
    print("started")
    x = yield 1
    print("got", x)
    y = yield 2
    print("got", y)
    return "done"

gen = coroutine()
print(gen.send(None))      # started / 1   (must prime with None or next())
print(gen.send("A"))       # got A / 2
try:
    gen.send("B")          # got B, then the return value arrives in StopIteration
except StopIteration as stop:
    print(stop.value)      # done
```

**From generators to `async`/`await`:**

| Generator world | Native coroutine world |
|---|---|
| `def` with `yield` → generator object | `async def` → coroutine object (separate type, same frame machinery) |
| `yield from subgen` delegates `send`/`throw`/return value | `await awaitable` = `yield from awaitable.__await__()` |
| return value travels in `StopIteration.value` | same: `Task.__step` catches `StopIteration` to get the result |
| `gen.throw(exc)` | how `task.cancel()` delivers `CancelledError` |
| `gen.close()` → `GeneratorExit` | `coro.close()`; async generators use `aclose()` |

- Coroutines are *not* iterable and you can't `yield` a value to the loop from `async def`. Only a Future's `__await__` yields (see Q2). Before 3.5 asyncio used `@asyncio.coroutine` generators with `yield from`, which was removed in 3.11.

**What `@contextmanager` does (simplified from `contextlib._GeneratorContextManager`):**

```python
class GeneratorCM:
    def __init__(self, gen):
        self.gen = gen

    def __enter__(self):
        try:
            return next(self.gen)                 # run up to the yield
        except StopIteration:
            raise RuntimeError("generator didn't yield") from None

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                next(self.gen)                    # run the code after yield
            except StopIteration:
                return False
            raise RuntimeError("generator didn't stop")
        try:
            self.gen.throw(exc)                   # re-raise *inside* the generator at the yield
        except StopIteration:
            return True                           # generator swallowed it → suppress
        except BaseException as e:
            if e is exc:
                return False                      # same exception propagated → don't suppress
            raise                                 # generator raised something new
        raise RuntimeError("generator didn't stop after throw()")
```

(The three-argument `gen.throw(type, value, tb)` form has been deprecated since 3.12. Pass the exception instance.)

**Staff-level insight — `ExitStack` for dynamic resource sets:**

```python
from contextlib import ExitStack

def process(paths: list[str], debug: bool) -> None:
    with ExitStack() as stack:
        files = [stack.enter_context(open(p)) for p in paths]  # if #3 fails, #1–2 still close
        if debug:
            stack.enter_context(profiling())
        stack.callback(log_done)                               # arbitrary cleanup, LIFO order
        run(files)
```

`AsyncExitStack` is the async version and is how frameworks such as FastAPI's lifespan handle a variable number of async resources.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Generator mechanics** | `.send()`, `.throw()`, `.close()`, priming, `StopIteration.value` |
| **yield from** | Delegation of send/throw/return value, the basis of `await` |
| **Context manager protocol** | `__exit__` return value means "suppress"; cleanup in `finally` |
| **Connection pool** | No blocking under locks, bounded size, timeouts, health checks, slot accounting |

**What they probe next:** "What happens if the body of a `@contextmanager` raises and the generator has no `try`?" (The exception is raised at the `yield`, so cleanup after the yield never runs.) "Why LIFO for the idle queue?" (Recently used connections are warm and FIFO keeps every connection alive, defeating idle eviction.)

---

## Question 7: Import System — Finders, Loaders, and Module Caching

**Interviewer:** *"Design a plugin system that discovers and loads Python modules from a directory at runtime. Then explain how you'd handle circular imports at scale."*

!!! tip "30-second answer"
    `import a.b` checks `sys.modules`, imports parent package `a` first, then asks each finder on `sys.meta_path` for a `ModuleSpec`. It creates the module, **inserts it into `sys.modules` before executing it**, then runs `loader.exec_module`. That early insertion is why circular imports produce "partially initialized module" errors. For plugins in production, use **entry points** (`importlib.metadata.entry_points(group=...)`). A custom `MetaPathFinder` is the tool when modules come from somewhere unusual. For cycles: import modules rather than names, move type-only imports under `TYPE_CHECKING`, and fix the layering.

### 🎯 Expected Answer

**The import algorithm (simplified `importlib._bootstrap._find_and_load`):**

```text
import a.b
1. "a.b" in sys.modules?  → return it (even if it's only partially initialised!)
2. import parent "a" first; use a.__path__ as the search path
3. for finder in sys.meta_path:   # BuiltinImporter, FrozenImporter, PathFinder, + yours
       spec = finder.find_spec("a.b", a.__path__, None)
       if spec: break
   else: raise ModuleNotFoundError
4. module = module_from_spec(spec)
5. sys.modules["a.b"] = module          ← before executing the code
6. spec.loader.exec_module(module)      (on failure: removed from sys.modules)
7. setattr(a, "b", module)
```

`PathFinder` then consults `sys.path_hooks` and `sys.path_importer_cache` (that's where zip imports and `FileFinder` live).

**Production answer: entry points.** Plugins are packages that declare themselves in their own `pyproject.toml`, so there's no directory scanning and versions and dependencies are handled by the installer:

```toml
# in the plugin's pyproject.toml
[project.entry-points."myapp.plugins"]
email = "myapp_email.plugin:register"
```

```python
from importlib.metadata import entry_points

def load_plugins() -> dict[str, object]:
    plugins = {}
    for ep in entry_points(group="myapp.plugins"):   # selectable API, 3.10+
        try:
            plugins[ep.name] = ep.load()()
        except Exception as exc:                     # one bad plugin must not kill startup
            log.warning("plugin %s failed: %r", ep.name, exc)
    return plugins
```

**Directory-based plugins with a custom finder (verified):**

```python
import importlib, importlib.util, sys
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path

class PluginFinder(MetaPathFinder):
    """Serves the virtual package `plugins` and `plugins.<name>` from one directory."""
    def __init__(self, plugin_dir: str, package: str = "plugins") -> None:
        self.dir, self.package = Path(plugin_dir).resolve(), package

    def find_spec(self, fullname, path, target=None) -> ModuleSpec | None:
        if fullname == self.package:            # the parent must be importable too
            spec = ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = []   # namespace-like, no __init__.py
            return spec
        prefix, _, name = fullname.rpartition(".")
        if prefix != self.package:
            return None                          # not ours: let the next finder try
        file = self.dir / f"{name}.py"
        return importlib.util.spec_from_file_location(fullname, file) if file.exists() else None

def discover(plugin_dir: str) -> dict[str, object]:
    finder = PluginFinder(plugin_dir)
    sys.meta_path.insert(0, finder)
    loaded = {}
    for file in sorted(finder.dir.glob("[!_]*.py")):
        try:
            module = importlib.import_module(f"plugins.{file.stem}")
            loaded[file.stem] = module.register()
        except Exception as exc:                 # one bad plugin must not kill startup
            print(f"skipping {file.stem}: {exc!r}")
    return loaded

print(discover("plugdir"))   # with plugdir/email_notifier.py and a plugdir/broken.py that raises:
# skipping broken: RuntimeError('broken plugin')
# {'email_notifier': 'email-plugin'}
print("plugins.broken" in sys.modules)   # False: failed imports are removed from sys.modules
```

- A finder that only handles `plugins.*` but not `plugins` itself fails: the parent package is imported first.
- Plugins run arbitrary code at import, with your process's privileges. Loading from a writable directory is a code-execution vector.
- `importlib.reload()` re-executes the module in the *same* module object. Existing references to old classes and functions stay stale, and `isinstance` against old classes breaks. Hot reload is for development only.

**Circular imports — root cause and fixes (verified on 3.13 and 3.14):**

```python
# models/user.py
from models.order import Order
# models/order.py
from models.user import User
# import models.user →
# ImportError: cannot import name 'User' from partially initialized module 'models.user'
# (most likely due to a circular import)
```

`models.user` is in `sys.modules` but hasn't reached `class User` yet when `order.py` asks for the name.

| Fix | How | Notes |
|---|---|---|
| Type-only imports | `if TYPE_CHECKING: from models.order import Order` | The standard fix when the cycle exists only for annotations |
| Lazy annotations | 3.14: annotations are evaluated lazily by default (PEP 649/749). ≤3.13: quote them or use `from __future__ import annotations` | Lazy annotations alone don't break the cycle: the top-level `from … import` still executes |
| Import the module, not the name | `import models.order` then `models.order.Order` at call time | Attribute lookup is deferred until use |
| Local import | `from models.order import Order` inside the function | Fine for rare paths; hides the dependency |
| Fix the layering | Extract shared types or Protocols into a lower module both depend on | The real fix at scale; enforce with `import-linter` in CI |

```python
# models/user.py, works on 3.14 with no quotes; on ≤3.13 add quotes or the __future__ import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from models.order import Order   # seen by mypy/pyright, never executed

class User:
    orders: list[Order]              # 3.14: lazily evaluated; <=3.13 needs quotes or __future__
    def total(self) -> float:
        return sum(o.amount for o in self.orders)
```

Caveat: anything that evaluates annotations at runtime (Pydantic, `dataclasses` with `InitVar`, FastAPI dependencies, `typing.get_type_hints`) raises `NameError` for names that exist only under `TYPE_CHECKING`. In 3.14, `annotationlib.get_annotations(obj, format=Format.FORWARDREF)` returns `ForwardRef` placeholders instead of raising.

**Startup time — lazy loading:**

- Measure first: `python -X importtime -c "import myapp" 2> imports.log`.
- Stdlib: `importlib.util.LazyLoader` defers executing a module until first attribute access. Module-level `__getattr__` (PEP 562) lets a package expose heavy submodules lazily.
- PEP 810 (explicit `lazy import` syntax) has been accepted for **Python 3.15**, which is due in October 2026. It isn't available in 3.14.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **MetaPathFinder** | Knows `sys.meta_path`, `find_spec`, and that parents import first |
| **ModuleSpec** | `name`, `loader`, `origin`, `submodule_search_locations`, `module_from_spec` / `exec_module` |
| **Circular imports** | Explains *why* (early `sys.modules` insertion), the `TYPE_CHECKING` fix and its runtime caveat, and the layering fix |
| **Plugins in production** | Entry points, isolation of failures, security of loading code |

**What they probe next:** "Why does `import a.b` sometimes work in a cycle where `from a.b import X` fails?" "How would you make a plugin's failure not take down the service?" (Isolate at import, timeouts, or run plugins in a subprocess or subinterpreter.) "What's a namespace package?" (A package with no `__init__.py`, spread across several directories, PEP 420.)

---

## Question 8: C Extensions & Performance — When Python Isn't Fast Enough

**Interviewer:** *"You have a hot loop processing 10M JSON objects. Python is too slow. Walk me through your optimization strategy from Python-level improvements through C extensions."*

!!! tip "30-second answer"
    Profile first (py-spy, cProfile, Scalene). For JSON the time usually goes into parsing and building Python objects, not your arithmetic. So the biggest win is a faster parser that decodes straight into typed structs (orjson, msgspec), then moving numeric work into NumPy arrays. Only then reach for compiled code (Cython, Rust/PyO3, a C extension, Numba), and only for the remaining hot loop, because they add build, packaging and maintenance cost. Also parallelize: the work is embarrassingly parallel across processes, and on the free-threaded build across threads.

### 🎯 Expected Answer

**Tier 0 — measure.** `py-spy record -o profile.svg --pid <pid>` (sampling, safe in production), `cProfile` + `snakeviz` locally, `scalene` to split Python vs native time and memory. Write a benchmark harness (`pyperf`) before changing anything.

**Tier 1 — Python-level fixes (small, cheap gains):**

```python
# Comprehension vs append loop: ~15% faster on 3.14 in a quick timeit (1M items)
data = [process(item) for item in items]

# Hoisting globals into default args (`_process=process`) mostly stopped mattering in 3.11+:
# the specializing interpreter (PEP 659) caches global lookups.

# Avoid per-item overhead: batch work, use built-ins (sum, map, sorted with key=),
# and avoid repeated attribute lookups in the hottest loop.
```

- Upgrading CPython is a tier-1 optimization: 3.11 was roughly 25% faster than 3.10 on pyperformance. 3.12–3.14 brought smaller gains.
- The experimental JIT (opt-in build, `PYTHON_JIT=1`; shipped in the Windows and macOS binaries since 3.14) currently gives modest or no speedups on typical code. Don't count on it.

**Tier 2 — fix the real bottleneck for JSON: parsing:**

```python
import msgspec

class Row(msgspec.Struct):
    id: int
    amount: float

decoder = msgspec.json.Decoder(list[Row])     # validates and decodes in C, no dict per row
rows = decoder.decode(payload_bytes)
# or: orjson.loads(...) as a drop-in for json.loads
```

- Stdlib `json.loads` on 200k small objects took ~0.09 s here (about 0.5 µs each, so ~5 s for 10M). Specialised parsers are typically several times faster, and decoding into structs avoids building millions of dicts.

**Tier 3 — vectorize numeric work with NumPy:**

```python
import numpy as np
ids = np.fromiter((r.id for r in rows), dtype=np.float64, count=len(rows))
amounts = np.fromiter((r.amount for r in rows), dtype=np.float64, count=len(rows))
result = amounts * (1 + 0.1 * np.sin(ids / 1000))   # one C loop per operation
```

Extraction is still a Python loop. NumPy pays off when the data stays in arrays across many operations, or when you can load columnar data directly (Arrow/Parquet, Polars).

**Tier 4 — Cython (compiled and checked):**

```cython
# process.pyx
# cython: language_level=3, boundscheck=False, wraparound=False
from libc.math cimport sin

cdef inline double compute(double amount, double id_val) noexcept nogil:
    return amount * (1.0 + 0.1 * sin(id_val / 1000.0))

def process_batch(list items):
    cdef Py_ssize_t i, n = len(items)
    cdef list out = [None] * n
    cdef dict item
    for i in range(n):
        item = items[i]
        out[i] = compute(item["amount"], item["id"])   # dict access still needs the GIL
    return out

def process_arrays(const double[::1] amounts, const double[::1] ids, double[::1] out):
    """Typed memoryviews over NumPy arrays: the loop touches no Python objects."""
    cdef Py_ssize_t i
    with nogil:
        for i in range(amounts.shape[0]):
            out[i] = compute(amounts[i], ids[i])
```

`process_batch` is limited by dict lookups and float boxing. `process_arrays` is the version that actually runs at C speed and can release the GIL. In Cython 3, `noexcept` is needed for `nogil` C functions that can't raise.

**Tier 5 — hand-written C extension (compiled and checked against 3.14):**

```c
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>

static PyObject *
process_batch(PyObject *self, PyObject *items)
{
    if (!PyList_Check(items)) {
        PyErr_SetString(PyExc_TypeError, "expected a list of dicts");
        return NULL;
    }
    Py_ssize_t n = PyList_GET_SIZE(items);
    PyObject *out = PyList_New(n);
    if (out == NULL) return NULL;

    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *item = PyList_GET_ITEM(items, i);              /* borrowed */
        PyObject *amount_obj = NULL, *id_obj = NULL;
        /* PyDict_GetItemStringRef (3.13+) returns a strong ref and reports errors */
        if (PyDict_GetItemStringRef(item, "amount", &amount_obj) <= 0 ||
            PyDict_GetItemStringRef(item, "id", &id_obj) <= 0) {
            if (!PyErr_Occurred())
                PyErr_SetString(PyExc_KeyError, "missing 'amount' or 'id'");
            goto error;
        }
        double amount = PyFloat_AsDouble(amount_obj);
        double id_val = PyFloat_AsDouble(id_obj);                /* accepts ints too */
        Py_DECREF(amount_obj); amount_obj = NULL;
        Py_DECREF(id_obj); id_obj = NULL;
        if (PyErr_Occurred()) goto error;                        /* -1.0 + exception */

        PyObject *res = PyFloat_FromDouble(amount * (1.0 + 0.1 * sin(id_val / 1000.0)));
        if (res == NULL) goto error;
        PyList_SET_ITEM(out, i, res);                            /* steals res */
        continue;
    error:
        Py_XDECREF(amount_obj);
        Py_XDECREF(id_obj);
        Py_DECREF(out);
        return NULL;
    }
    return out;
}

static PyMethodDef methods[] = {
    {"process_batch", process_batch, METH_O, "Process a list of {'id', 'amount'} dicts."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, .m_name = "process_c", .m_size = 0, .m_methods = methods,
};

PyMODINIT_FUNC PyInit_process_c(void) { return PyModuleDef_Init(&module); }
```

What interviewers check: error handling on every call, borrowed vs strong references (`PyList_GetItem` and the old `PyDict_GetItemString` return borrowed references; `PyList_SET_ITEM` steals one), no leaks on error paths, multi-phase init (`PyModuleDef_Init`, needed for subinterpreter and free-threading support). Most teams today choose **Rust + PyO3/maturin** or **nanobind/pybind11** (C++) over raw C for memory safety and less boilerplate.

**Tier 6 — Numba JIT (numeric loops over arrays):**

```python
from numba import njit, prange
import numpy as np

@njit(parallel=True, cache=True)
def process_numba(amounts: np.ndarray, ids: np.ndarray) -> np.ndarray:
    out = np.empty_like(amounts)
    for i in prange(amounts.shape[0]):          # parallel loop, no GIL
        out[i] = amounts[i] * (1.0 + 0.1 * np.sin(ids[i] / 1000.0))
    return out
```

**Decision matrix** (speedups depend heavily on the workload, so measure):

| Option | Best for | Cost |
|---|---|---|
| Newer CPython, better algorithms | Everything | Lowest |
| Faster libraries (orjson, msgspec, Polars) | Parsing, serialization, dataframes | A dependency |
| NumPy vectorization | Numeric arrays | Data must live in arrays |
| Numba | Numeric loops NumPy can't express | Compile on first call (cold start); limited Python subset |
| Cython | Mixed Python/C code, wrapping C libraries | Build step, per-platform wheels |
| Rust/PyO3, C++/nanobind | Large native components, safety | Second language, toolchain, wheels |
| Raw C API | Tiny, hot, stable kernels | Refcount bugs, segfaults, ABI churn |
| Parallelism (processes, free-threaded threads) | Independent items | Serialization or thread-safety work |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Profiling-led** | Measures before and after, knows sampling vs deterministic profilers |
| **Finds the real bottleneck** | Sees that JSON parsing and object creation dominate, not the arithmetic |
| **GIL awareness** | Knows when native code can release the GIL (no Python objects in the loop) |
| **Deployment** | Wheels per platform, abi3, free-threaded wheels, maintenance cost of native code |

**What they probe next:** "Your C extension segfaults in production under load: how do you debug it?" (faulthandler, a debug build or `PYTHONMALLOC=debug`, ASan, core dumps + gdb with the CPython helpers.) "Would PyPy help here?" (Often yes for pure-Python loops; check C-extension compatibility and that PyPy supports your Python version.)

---

## Question 9: Async Generators & Async Context Managers — Structured Concurrency

**Interviewer:** *"Design an async streaming data pipeline. Implement a connection that can be used as an async context manager and yields data as an async generator. Handle cleanup properly."*

!!! tip "30-second answer"
    Put connection lifetime in an async context manager (`@asynccontextmanager` with `try/finally`), stream with an async generator, and run side tasks (heartbeats) in a `TaskGroup` that's cancelled when the stream ends. The two traps: an async generator is **not** closed when you `break` out of `async for`; it's only finalized later by the GC and the loop's asyncgen hooks. So wrap it in `contextlib.aclosing()`. And a never-ending sibling task keeps `TaskGroup.__aexit__` waiting forever unless you cancel it. Backpressure comes free: the producer doesn't run until the consumer asks for the next item.

### 🎯 Expected Answer

```python
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager

logger = logging.getLogger(__name__)

class StreamConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader, self._writer = reader, writer

    async def read_lines(self) -> AsyncIterator[str]:
        while line := await self._reader.readline():   # b"" at EOF
            yield line.decode().rstrip("\n")

    async def send(self, message: str) -> None:
        self._writer.write((message + "\n").encode())
        await self._writer.drain()                     # write-side backpressure

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass                                       # peer already gone

@asynccontextmanager
async def open_stream(host: str, port: int, *, retries: int = 3) -> AsyncIterator[StreamConnection]:
    for attempt in range(retries):
        try:
            async with asyncio.timeout(5):             # 3.11+, replaces wait_for
                reader, writer = await asyncio.open_connection(host, port)
            break
        except (OSError, TimeoutError):
            if attempt == retries - 1:
                raise
            await asyncio.sleep(min(2 ** attempt, 10))   # add jitter in real code
    conn = StreamConnection(reader, writer)
    try:
        yield conn
    finally:
        await conn.close()

async def heartbeat(conn: StreamConnection, every: float = 30) -> None:
    while True:
        await asyncio.sleep(every)
        await conn.send("PING")

async def consume(host: str, port: int) -> None:
    async with open_stream(host, port) as conn:         # outer: connection outlives the tasks
        async with asyncio.TaskGroup() as tg:
            hb = tg.create_task(heartbeat(conn))
            try:
                async with aclosing(conn.read_lines()) as lines:
                    async for line in lines:
                        await handle(line)              # slow consumer = natural backpressure
            finally:
                hb.cancel()                             # else TaskGroup.__aexit__ waits forever
```

- Nesting order matters. The connection wraps the TaskGroup, so the heartbeat never writes to a closed socket. If `handle` raises, the TaskGroup cancels the heartbeat and the connection still closes.
- The `hb.cancel()` fix was checked in isolation: without it the TaskGroup never exits after EOF.

**Staff-level insight — async generator cleanup is not automatic (verified):**

```python
import asyncio
from contextlib import aclosing

async def rows():
    try:
        for i in range(10):
            yield i
            await asyncio.sleep(0)
    finally:
        print("  cleanup ran")            # e.g. release the DB connection

async def main():
    print("plain break:")
    gen = rows()
    async for r in gen:
        if r == 1:
            break
    print("  after loop, generator suspended:", gen.ag_frame is not None)
    await gen.aclose()                    # without this, cleanup waits for GC + loop hook

    print("with aclosing:")
    async with aclosing(rows()) as gen:
        async for r in gen:
            if r == 1:
                break
    print("  done")

asyncio.run(main())
# plain break:
#   after loop, generator suspended: True
#   cleanup ran
# with aclosing:
#   cleanup ran
#   done
```

- After `break`, the generator stays suspended at its `yield`. Its `finally` runs only when someone calls `aclose()`: you, `aclosing()` (3.10+), or the event loop's finalizer hook after GC (`sys.set_asyncgen_hooks`). By then it may run in a different task, after the loop has moved on, or not at all if the loop is shutting down. `asyncio.run()` calls `loop.shutdown_asyncgens()` as a last resort.
- `aclose()` throws **`GeneratorExit`** (not `CancelledError`) at the suspended `yield`. Yielding again inside `finally` raises `RuntimeError`.
- Don't `yield` inside a `TaskGroup` or `asyncio.timeout()` block in an async generator. The consumer's code runs while the generator is suspended *inside* the scope, so cancellation scopes get confused. (This is why Trio and AnyIO forbid it.)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cleanup guarantee** | Knows `break` doesn't close the generator; uses `aclosing()`; knows `aclose()` raises `GeneratorExit` |
| **Cancellation** | Re-raises `CancelledError`; cancels long-lived siblings; uses `asyncio.timeout` |
| **Backpressure** | Pull-based async iteration on read; `drain()` on write; bounded `asyncio.Queue` between stages |
| **Real protocol** | Handles EOF, partial lines and `LimitOverrunError` (`readline` has a 64 KiB default limit), reconnects with jittered backoff |

**What they probe next:** "How do you fan out to N workers with bounded memory?" (Bounded `asyncio.Queue(maxsize=…)`, N consumer tasks in a TaskGroup, sentinel or `Queue.shutdown()` (3.13) to stop.) "What happens to in-flight items on SIGTERM?" (Stop accepting, drain with a deadline, then cancel.)

---

## Question 10: Packaging & Distribution — Building for the Python Ecosystem

**Interviewer:** *"You need to distribute a Python library that has C extensions. Walk me through your build system, platform support, and distribution strategy."*

!!! tip "30-second answer"
    Declare everything in `pyproject.toml` with one build backend: maturin for Rust, scikit-build-core for CMake/C++, meson-python or setuptools for C/Cython. Build wheels in CI with **cibuildwheel** (or maturin-action) for manylinux_2_28, musllinux_1_2, macOS arm64/x86_64 and Windows. Repair them so external shared libraries are bundled (auditwheel, delocate, delvewheel). Ship an sdist as a fallback. Use the **stable ABI (abi3)** to build one wheel per platform for all CPython versions ≥ your minimum. Note that free-threaded CPython (3.13t/3.14t) can't use abi3 yet and needs its own `cp314t` wheels. Publish with PyPI Trusted Publishing (OIDC, no API tokens).

### 🎯 Expected Answer

**`pyproject.toml` (Rust extension built with maturin):**

```toml
[build-system]
requires = ["maturin>=1.7,<2"]
build-backend = "maturin"

[project]
name = "fast-processor"
version = "0.3.0"
description = "High-performance data processor with Rust bindings"
requires-python = ">=3.10"
license = "MIT"                       # PEP 639 SPDX expression (replaces license = {text=...})
dependencies = [
    "numpy>=1.26",
    "typing-extensions>=4.5; python_version < '3.11'",
]

[project.urls]
Homepage = "https://github.com/example/fast-processor"

[dependency-groups]                   # PEP 735: dev-only deps, not published as extras
dev = ["pytest>=8", "pytest-benchmark", "mypy>=1.10"]

[tool.maturin]
module-name = "fast_processor._native"   # compiled module inside the Python package
python-source = "python"
features = ["pyo3/extension-module", "pyo3/abi3-py310"]   # one abi3 wheel for 3.10+
```

**Building wheels:**

```bash
# Locally (maturin builds in a manylinux-compatible way and bundles libs itself)
maturin build --release --compatibility manylinux_2_28

# In CI: one matrix covering all platforms
pipx run cibuildwheel --output-dir wheelhouse
#   CIBW_BUILD="cp310-* cp314t-*"                    # abi3 wheel + a free-threaded wheel
#   CIBW_MANYLINUX_X86_64_IMAGE=manylinux_2_28
#   repair step: auditwheel (Linux), delocate (macOS), delvewheel (Windows)
```

| Target | Current choice (2026) | Notes |
|---|---|---|
| Linux glibc | `manylinux_2_28` (AlmaLinux 8) | `manylinux2014` (CentOS 7) has been EOL since June 2024. Use it only if you must support very old distros |
| Linux musl (Alpine) | `musllinux_1_2` | `musllinux_1_1` support ended November 2024 |
| macOS | separate `arm64` and `x86_64` wheels, or `universal2` | Set `MACOSX_DEPLOYMENT_TARGET` deliberately |
| Windows | `win_amd64` (+ `win_arm64` if you need it) | |

**The stable ABI (`abi3`):**

```python
# setuptools + C example: one wheel per platform, valid for CPython 3.10 and later
from setuptools import Extension, setup

setup(
    ext_modules=[Extension(
        "fast_processor._core",
        sources=["src/core.c"],
        define_macros=[("Py_LIMITED_API", "0x030A0000")],   # restrict to the 3.10 limited API
        py_limited_api=True,
    )],
    options={"bdist_wheel": {"py_limited_api": "cp310"}},    # wheel tag: cp310-abi3-<platform>
)
```

- **Trade-off:** fewer wheels and day-one support for new Python releases, in exchange for a restricted C API (no direct struct access, some slower calls). Cython and PyO3 both support abi3.
- **Free-threading gap:** the limited API isn't available on free-threaded builds as of 3.14, so you also ship `cp313t`/`cp314t` wheels. PEP 803 ("abi3t") proposes a free-threading-compatible stable ABI for 3.15; it's still a draft.

**Pure-Python fallback (optional):**

```python
# fast_processor/__init__.py
try:
    from fast_processor._native import process, validate
except ImportError:                                    # no wheel for this platform
    import warnings
    warnings.warn("fast_processor: native extension unavailable, using slow fallback",
                  RuntimeWarning, stacklevel=2)
    from fast_processor._pure import process, validate
```

Test both paths in CI and make sure the two implementations agree on outputs (property-based tests with Hypothesis). A silent fallback can turn a packaging bug into a 50x production slowdown, so expose which backend is active.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **manylinux** | Knows glibc-versioned tags (`manylinux_2_28`), why wheels are repaired, musllinux |
| **ABI strategy** | abi3 trade-offs, plus the free-threaded wheel gap |
| **Build system** | maturin / scikit-build-core / meson-python; cibuildwheel; PEP 517 build isolation |
| **Supply chain** | Trusted Publishing, attestations (PEP 740), pinned build deps, reproducible builds |

**What they probe next:** "A user on Alpine reports a 10-minute install: why?" (No musllinux wheel, so pip builds from the sdist.) "How do you manage the app's own environment?" (`uv` with a lockfile (`uv.lock`), or pip-tools; libraries specify ranges, applications pin exact versions.)

---

## Question 11: Subinterpreters & Free-Threaded Python (3.12/3.13)

**Interviewer:** *"Python 3.12 introduced per-interpreter GILs (PEP 684) and 3.13 added an experimental free-threaded build (PEP 703). Where do they stand in 3.14, and how would you use them to build a truly parallel system?"*

!!! tip "30-second answer"
    Two different bets. **Subinterpreters** (PEP 734, `concurrent.interpreters` and `InterpreterPoolExecutor` in 3.14) give you isolated interpreters with one GIL each in one process. They're like processes with cheaper startup and communication, but nothing is shared implicitly and many C extensions don't support them yet. The **free-threaded build** (`python3.14t`) removes the GIL so ordinary threads run Python in parallel. Since 3.14 it's officially supported (PEP 779) but still a separate, optional build. Single-thread overhead is about 5–10% per the 3.14 release notes, every C extension needs a `cp314t` wheel, and your own races stop being hidden. I'd pilot free-threading on CPU-bound services whose dependencies already ship `t` wheels, and keep processes as the default elsewhere.

### 🎯 Expected Answer

**Subinterpreters (3.14 public API, verified):**

```python
from concurrent import interpreters
from concurrent.futures import InterpreterPoolExecutor

def cpu_heavy(n: int) -> int:
    return sum(i * i for i in range(n))

if __name__ == "__main__":
    interp = interpreters.create()
    interp.exec("x = 6 * 7; print('in subinterpreter:', x)")   # in subinterpreter: 42
    print(interp.call(cpu_heavy, 1_000))                         # 332833500
    interp.close()

    with InterpreterPoolExecutor(max_workers=4) as pool:
        print(list(pool.map(cpu_heavy, [10, 100, 1_000])))       # [285, 328350, 332833500]
```

- Communication: `interpreters.create_queue()` (cross-interpreter queue), shareable types (`None`, `bool`, `int`, `float`, `str`, `bytes`, tuples of those, `memoryview`), and pickling for everything else.
- Limitations listed in the 3.14 docs: startup isn't optimized yet, each interpreter uses more memory than necessary, there are few ways to share objects, and many third-party extension modules aren't compatible. (Before 3.14 only the private `_interpreters` / `_xxsubinterpreters` modules existed; don't use them.)

**Free-threaded build (measured on an Apple Silicon laptop, 4 threads):**

```python
import sys, sysconfig, threading, time
from concurrent.futures import ThreadPoolExecutor

def cpu_heavy(n: int) -> int:
    return sum(i * i for i in range(n))

print("free-threaded build:", bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
      "| GIL enabled now:", sys._is_gil_enabled())
workers = 4
start = time.perf_counter()
for _ in range(workers):
    cpu_heavy(3_000_000)
serial = time.perf_counter() - start
start = time.perf_counter()
with ThreadPoolExecutor(workers) as pool:
    list(pool.map(cpu_heavy, [3_000_000] * workers))
threaded = time.perf_counter() - start
print(f"speedup with {workers} threads: {serial / threaded:.1f}x")

shared: list[int] = []
counter = {"n": 0}
def hammer():
    for _ in range(100_000):
        shared.append(1)          # single operation: internally locked, safe
        counter["n"] += 1         # read-modify-write: NOT atomic, races
ts = [threading.Thread(target=hammer) for _ in range(8)]
for t in ts: t.start()
for t in ts: t.join()
print("append count:", len(shared), "| counter:", counter["n"], "(expected 800000)")

# python3.14 (default build):
#   free-threaded build: False | GIL enabled now: True
#   speedup with 4 threads: 1.0x
#   append count: 800000 | counter: 800000 (expected 800000)   ← correct by luck, not by guarantee
# python3.14t (free-threaded):
#   free-threaded build: True | GIL enabled now: False
#   speedup with 4 threads: 2.7x
#   append count: 800000 | counter: 150043 (expected 800000)   ← lost updates; varies per run
```

**What changes and what doesn't without the GIL:**

- **Built-in containers stay internally consistent.** `list.append`, `dict[k] = v` and `set.add` use per-object locks ("critical sections"), so single operations are as safe as with the GIL. You won't corrupt a list.
- **Compound operations were never atomic** (`d[k] += 1`, check-then-set, iterating while another thread mutates). The GIL made races rare. Free-threading makes them frequent. Use `threading.Lock`, `queue.Queue`, or per-thread state. Sharing one iterator across threads can return duplicates or skip items.
- **C extensions:** an extension must declare support (`Py_mod_gil = Py_MOD_GIL_NOT_USED`). Importing one that doesn't re-enables the GIL for the whole process with a warning. Check `sys._is_gil_enabled()` at startup in production.
- **How to run it:** install the separate free-threaded binary (`python3.14t`; python.org installers and `uv python install 3.14t`), or build with `--disable-gil`. `PYTHON_GIL=0` / `-X gil=0` only work on that build. On the default build they abort with `Fatal Python error: config_read_gil: Disabling the GIL is not supported by this build`.
- **Cost:** about 5–10% single-thread overhead in 3.14 (down from much larger in 3.13, where the specializing interpreter was disabled in free-threaded mode). Memory use is higher, and the build uses mimalloc.

**Choosing a model:**

| Need | Pick |
|---|---|
| CPU-bound, dependencies ship `t` wheels, shared in-memory state | Free-threaded threads |
| CPU-bound, isolation or crash containment, any dependencies | Processes |
| CPU-bound, many small tasks, pure-Python or subinterpreter-safe deps | `InterpreterPoolExecutor` |
| I/O-bound, high concurrency | asyncio (or threads) |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Subinterpreters** | Isolation model, how data crosses, extension compatibility, current maturity |
| **Free-threaded trade-offs** | Single-thread overhead, `t` wheels, GIL re-enabled by incompatible extensions, which races become visible |
| **Correct safety model** | Doesn't claim `list.append` becomes unsafe; does flag compound operations |
| **Production readiness** | A rollout plan: dependency audit, stress tests with ThreadSanitizer-built CPython, canary with `sys._is_gil_enabled()` assertions |

**What they probe next:** "How does CPython keep refcounting fast without the GIL?" (Biased reference counting: the owner thread updates a local count without atomics and other threads use an atomic shared count; immortal objects; deferred refcounting for some objects.) "Would asyncio benefit?" (One loop is still one thread. You can run one loop per thread to use more cores, but CPU work inside a coroutine still blocks its own loop.)

---

## Question 12: Production Patterns — Dependency Injection, Configuration, and Plugin Architectures

**Interviewer:** *"Design a production service framework in Python that supports dependency injection, configuration management, and a plugin system. Make it testable and extensible."*

!!! tip "30-second answer"
    Keep it boring and explicit. Use **typed, validated config** loaded once at startup (env overrides, secrets from a secret manager, fail fast on bad values). Use a **composition root** that wires concrete classes to Protocol-typed dependencies through constructor injection; a small container keyed by type is enough. Use **lifecycle management** via an `AsyncExitStack` so resources close in reverse order. Load **plugins via entry points** (Q7). Testing means overriding a binding, not monkeypatching. Avoid magic auto-wiring by name; it breaks under refactors and under `from __future__ import annotations` or 3.14's lazy annotations, where annotations aren't classes until resolved.

### 🎯 Expected Answer

**A minimal but correct design (runnable; database faked):**

```python
import asyncio, os
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Protocol

# ── 1. Config: typed, validated once at startup, env overrides ─────────
@dataclass(frozen=True)
class DatabaseConfig:
    dsn: str = "postgresql://localhost/app"
    pool_size: int = 10

@dataclass(frozen=True)
class AppConfig:
    debug: bool = False
    db: DatabaseConfig = field(default_factory=DatabaseConfig)

    @classmethod
    def from_env(cls, env: dict[str, str] = os.environ) -> "AppConfig":
        db = DatabaseConfig(
            dsn=env.get("APP_DB_DSN", DatabaseConfig.dsn),
            pool_size=int(env.get("APP_DB_POOL_SIZE", DatabaseConfig.pool_size)),
        )
        return cls(debug=env.get("APP_DEBUG", "0") == "1", db=db)

# ── 2. Container: keyed by type, singletons, lifecycle via AsyncExitStack ─
class Container:
    def __init__(self) -> None:
        self._factories: dict[type, Callable[["Container"], Any]] = {}
        self._instances: dict[type, Any] = {}
        self._stack = AsyncExitStack()

    def register[T](self, iface: type[T], factory: Callable[["Container"], T]) -> None:
        self._factories[iface] = factory

    def override[T](self, iface: type[T], instance: T) -> None:   # for tests
        self._instances[iface] = instance

    def resolve[T](self, iface: type[T]) -> T:
        if iface not in self._instances:
            self._instances[iface] = self._factories[iface](self)  # deps resolve first
        return self._instances[iface]

    async def start[T](self, iface: type[T]) -> T:
        """Resolve and, if it is an async context manager, enter it.
        Exit happens in reverse order on shutdown."""
        obj = self.resolve(iface)
        if hasattr(obj, "__aenter__"):
            await self._stack.enter_async_context(obj)
        return obj

    async def aclose(self) -> None:
        await self._stack.aclose()

# ── 3. Services depend on Protocols, not concrete classes ─────────────
class UserRepo(Protocol):
    async def get(self, user_id: int) -> dict[str, Any] | None: ...

class Database:
    def __init__(self, cfg: DatabaseConfig) -> None:
        self.cfg = cfg
    async def __aenter__(self) -> "Database":
        print(f"db: open pool of {self.cfg.pool_size}")
        return self
    async def __aexit__(self, *exc: object) -> None:
        print("db: closed")
    async def fetch_one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        return {"id": args[0], "name": "Ada"}       # stand-in for asyncpg

class SqlUserRepo:
    def __init__(self, db: Database) -> None:
        self.db = db
    async def get(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM users WHERE id = $1", user_id)  # bound param

class UserService:
    def __init__(self, repo: UserRepo) -> None:
        self.repo = repo
    async def display_name(self, user_id: int) -> str:
        user = await self.repo.get(user_id)
        return user["name"] if user else "<unknown>"

# ── 4. Composition root: the only place that knows concrete classes ───
def build(cfg: AppConfig) -> Container:
    c = Container()
    c.register(AppConfig, lambda c: cfg)
    c.register(Database, lambda c: Database(c.resolve(AppConfig).db))
    c.register(UserRepo, lambda c: SqlUserRepo(c.resolve(Database)))
    c.register(UserService, lambda c: UserService(c.resolve(UserRepo)))
    return c

async def main() -> None:
    c = build(AppConfig.from_env({"APP_DB_POOL_SIZE": "20"}))
    try:
        await c.start(Database)
        print(await c.resolve(UserService).display_name(1))
    finally:
        await c.aclose()

    # Test: swap the repo, no database involved
    class FakeRepo:
        async def get(self, user_id: int) -> dict[str, Any] | None:
            return None
    t = build(AppConfig())
    t.override(UserRepo, FakeRepo())
    print(await t.resolve(UserService).display_name(1))

asyncio.run(main())
# db: open pool of 20
# Ada
# db: closed
# <unknown>
```

**Design choices and why:**

- **Config.** In real services use `pydantic-settings` for parsing nested env vars (`APP_DB__POOL_SIZE`), type coercion and validation errors at startup. Never log the resolved config with secrets in it. Get secrets from a secret manager or mounted files, not committed YAML.
- **Keyed by type, not name.** No string typos, refactor-safe, and mypy can check `resolve(UserService) -> UserService`. (mypy reports `type-abstract` when a `Protocol` is passed as `type[T]`; add `# type: ignore[type-abstract]` or key by a token.)
- **Lifecycle.** `AsyncExitStack` closes resources in reverse order of start, even if a later start fails. Wire it to your framework's lifespan hook (FastAPI `lifespan`) and to SIGTERM handling for graceful shutdown.
- **Scopes.** Singletons for pools and clients. Per-request objects (DB session, request context) come from a request-scoped factory or `contextvars`, never from a singleton, or you'll share state across concurrent requests.
- **Security.** Always use bound parameters (`$1`), never f-strings, in SQL.
- **Libraries.** `dependency-injector`, `svcs`, `punq`, or FastAPI's `Depends` for request scope. A hand-rolled 40-line container is often enough, and its behaviour is obvious.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Framework design** | Composition root, Protocol-typed dependencies, explicit wiring |
| **Lifecycle** | Startup/shutdown ordering, partial-startup failure, graceful drain on SIGTERM |
| **Testability** | Overrides at the container, fakes over mocks, no global state |
| **Production reality** | Validated config, secrets handling, request vs app scope, observability hooks |

**What they probe next:** "How do you avoid the container becoming a service locator everyone imports?" (Only the composition root calls `resolve`; everything else takes constructor arguments.) "How do you detect dependency cycles?" (Track a resolving set in `resolve` and raise with the cycle path.)

---

## Question 13: Modern Python (3.11–3.15) — What Changed That Matters in Production?

**Interviewer:** *"What has changed in recent Python versions that you'd actually use or plan around?"*

!!! tip "30-second answer"
    3.11 made CPython roughly 25% faster and added `TaskGroup`, `asyncio.timeout`, exception groups and `except*`. 3.12 brought PEP 695 generics syntax, per-interpreter GIL and immortal objects. 3.13 added the experimental free-threaded build, an experimental JIT and a much better REPL. 3.14 (current) made free-threading officially supported, made annotations lazy (PEP 649/749), and added template strings (`t"..."`), `concurrent.interpreters`, zstd, safe remote debugging (`sys.remote_exec`, `pdb -p`) and `python -m asyncio ps/pstree`. 3.15 (due October 2026) adds explicit lazy imports (PEP 810).

### 🎯 Expected Answer

| Version | Feature | Why a staff engineer cares |
|---|---|---|
| 3.11 | Faster CPython (specializing adaptive interpreter, PEP 659) | Free speed-up; makes old micro-optimizations obsolete |
| 3.11 | `ExceptionGroup` / `except*`, `TaskGroup`, `asyncio.timeout()` | Structured concurrency in the stdlib |
| 3.11 | `tomllib`, `Self`, `LiteralString`, fine-grained error locations | Better tooling and errors |
| 3.12 | PEP 695 `class Box[T]:` / `type Alias = ...`, `@override` | Cleaner generics, inferred variance |
| 3.12 | Per-interpreter GIL (PEP 684), immortal objects (PEP 683) | Foundations for parallelism; fewer copy-on-write faults |
| 3.12 | `sys.monitoring` (PEP 669), f-string grammar (PEP 701) | Low-overhead profilers and coverage |
| 3.13 | Free-threaded build (PEP 703, experimental), JIT (PEP 744, experimental, off by default) | Test your stack early |
| 3.13 | New interactive REPL (multi-line editing, colour, paste mode) | Day-to-day ergonomics |
| 3.13 | `asyncio.Queue.shutdown()`, `TypeIs`, `warnings.deprecated` | Cleaner shutdown and typing |
| 3.14 | Free-threading officially supported (PEP 779), still optional | Pilot it for CPU-bound services |
| 3.14 | Deferred annotations (PEP 649/749) + `annotationlib` | Forward references just work; runtime annotation users (Pydantic, FastAPI) must use the new APIs |
| 3.14 | Template strings, `t"..."` (PEP 750) → `string.templatelib.Template` | Safe SQL/HTML/shell interpolation: the library sees values separately from the static text |
| 3.14 | `concurrent.interpreters` + `InterpreterPoolExecutor` (PEP 734) | Subinterpreters from Python code |
| 3.14 | `sys.remote_exec` / `python -m pdb -p PID` (PEP 768), `python -m asyncio ps/pstree PID` | Debug live production processes without restarting |
| 3.14 | `compression.zstd` (PEP 784), `except A, B:` without parentheses (PEP 758) | Smaller things you'll see in code reviews |
| 3.14 | asyncio policy system deprecated (removal planned for 3.16); `asyncio.get_event_loop()` raises `RuntimeError` when no loop is running or set | Migrate to `asyncio.run(..., loop_factory=...)` / `asyncio.Runner` |
| 3.14.5 | Incremental GC from 3.14.0 reverted to the 3.13 generational GC | Patch-level behaviour differences matter for memory benchmarks |
| 3.15 (due Oct 2026) | Explicit lazy imports (PEP 810) | Startup time for CLIs and serverless |

**Template strings in one example (3.14):**

```python
from string.templatelib import Interpolation, Template

def sql(t: Template) -> tuple[str, list[object]]:
    parts, args = [], []
    for item in t:
        if isinstance(item, Interpolation):
            args.append(item.value)
            parts.append(f"${len(args)}")      # placeholder, never the raw value
        else:
            parts.append(item)
    return "".join(parts), args

user_id = "42; DROP TABLE users"
print(sql(t"SELECT * FROM users WHERE id = {user_id}"))
# ('SELECT * FROM users WHERE id = $1', ['42; DROP TABLE users'])
```

**What they probe next:** "How do you plan a Python upgrade across 200 services?" (Inventory versions and native dependencies, run the test suite with `-W error::DeprecationWarning` on the new version in CI first, upgrade base images centrally, canary, and track the end-of-life calendar. 3.10 reaches end of life in October 2026.)

---

## 📊 Staff-Level Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Cites CPython mechanisms precisely (switch interval, `Task.__step`, `sys.modules` ordering), references PEPs by number, knows what changed in 3.13/3.14, and has shipped fixes for GIL, memory or async issues. Discusses trade-offs without prompting. |
| **4 — Strong** | Deep understanding of internals. Knows GIL switching, event loop phases, metaclass and descriptor protocols, and leak-hunting tools. Can write correct C or Cython extensions. |
| **3 — Competent** | Good Pythonista. Knows async/await, context managers, type hints, but not CPython internals or the memory model. |
| **2 — Developing** | Proficient with Python syntax but doesn't understand why things work. No production experience at scale. |
| **1 — Needs Growth** | Can write scripts but doesn't understand OOP in Python, concurrency models, or the runtime. |

---

> *Built for experienced Python engineers targeting Senior/Staff roles.*
