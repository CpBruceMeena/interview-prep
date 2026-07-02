# 🐍 Python — Staff-Level Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer, 15+ years across systems infrastructure  \
> **Target Level:** Staff/Principal Engineer (10+ years)  \
> **Evaluation Focus:** Deep CPython internals, concurrency models, memory management, production system design

---

## Question 1: The GIL — Internals & When to Break Free

**Interviewer:** *"Explain the GIL. When does it actually block you, and how do you work around it at scale?"*

### 🎯 Expected Answer (Staff Level)

**What the GIL actually is:** The Global Interpreter Lock is a mutex on the CPython interpreter that prevents multiple native threads from executing Python bytecodes simultaneously. It protects CPython's internal state — reference counts, object allocations — from race conditions without requiring fine-grained locks on every object.

**🔬 Internals — the tick mechanism (pre-3.2):**
```c
// CPython 2.x style — check-interval based switching
for (;;) {
    if (--ticker < 0) {
        ticker = check_interval;  // Default: 100 bytecodes
        if (gil_drop_requested) {
            // Release GIL, let another thread run
            drop_gil(tstate);       // PyThread_release_lock(gil->mutex)
            take_gil(tstate);       // PyThread_acquire_lock(gil->mutex, WAIT)
        }
    }
    // Execute one bytecode
}
```

**Post-3.2 — the new GIL (PEP 1043, Antoine Pitrou):**
```c
// Time-based switching (5ms intervals)
static void drop_gil(PyThreadState *tstate) {
    if (!_Py_atomic_load_relaxed(&gil->locked))
        return;
    // 1. Set switch_interval deadline (5ms default)
    // 2. Signal waiting threads via gil->switch_condition
    // 3. Release the GIL mutex
    // 4. Wait for the GIL to be released again (for own next turn)
}
```

The new GIL uses a condition variable and a timeout: every 5 milliseconds (configurable via `sys.setswitchinterval()`), the holding thread voluntarily releases and re-acquires the GIL. This replaced the old bytecode-count-based switching which was unfair to CPU-bound threads.

**When the GIL actually hurts:**

```
┌─────────────────────────────────────────────────────────────┐
│                   GIL Impact Matrix                          │
├─────────────┬─────────────────────┬─────────────────────────┤
│             │  CPU-bound          │  I/O-bound              │
├─────────────┼─────────────────────┼─────────────────────────┤
│ Threading   │  ❌ 1 thread at a   │  ✅ Releases GIL during │
│             │    time (0% speedup)│    I/O wait (good!)     │
├─────────────┼─────────────────────┼─────────────────────────┤
│ Multiproc   │  ✅ True parallelism│  ❌ Overkill, IPC cost  │
│             │    N processes      │    for simple I/O       │
├─────────────┼─────────────────────┼─────────────────────────┤
│ Asyncio     │  ❌ Single thread   │  ✅ Best for I/O-bound  │
│             │    cooperative      │    high-concurrency     │
└─────────────┴─────────────────────┴─────────────────────────┘
```

**The real issue:** The GIL is released during I/O (file reads, network calls, `time.sleep()`), so I/O-bound programs scale fine with threads. But CPU-bound Python — image processing, numerical computation, JSON serialization at scale — saturates one core.

**Fighting the GIL in production:**

```python
# Strategy 1: multiprocessing with shared memory (avoid serialization)
import multiprocessing as mp
import numpy as np
from multiprocessing import shared_memory

def worker(shm_name, shape, dtype):
    """Process a chunk of a shared NumPy array — zero copy"""
    existing_shm = shared_memory.SharedMemory(name=shm_name)
    arr = np.ndarray(shape, dtype=dtype, buffer=existing_shm.buf)
    # ... process arr in place ...
    existing_shm.close()

# Main process
shape = (10000, 10000)
arr = np.zeros(shape, dtype=np.float64)
shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
shared_arr = np.ndarray(shape, dtype=arr.dtype, buffer=shm.buf)
shared_arr[:] = arr[:]

processes = [mp.Process(target=worker, args=(shm.name, shape, arr.dtype))
             for _ in range(mp.cpu_count())]
for p in processes: p.start()
for p in processes: p.join()
shm.close()
shm.unlink()
```

```python
# Strategy 2: C extensions that release the GIL
// Cython example — nogil block
cdef void compute_in_c(double *data, size_t n) nogil:
    # No Python objects — GIL not needed
    for i in range(n):
        data[i] = expensive_computation(data[i])

def process_array_parallel(list arr):
    """Call from Python — GIL released during C processing"""
    cdef double[::1] view = arr  # memoryview, no copy
    with nogil:
        compute_in_c(&view[0], view.shape[0])
```

```python
# Strategy 3: Using subinterpreters (PEP 684, Python 3.12+)
import _xxsubinterpreters as interpreters

def run_in_isolation(code: str):
    """Each subinterpreter has its own GIL — true parallelism"""
    interp_id = interpreters.create()
    interpreters.run_string(interp_id, code)
    result = interpreters.get_result(interp_id)
    interpreters.destroy(interp_id)
    return result
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Deep internals** | Doesn't just say "GIL prevents parallelism" — explains the 5ms switch interval, condition variable, and why it exists |
| **Practical experience** | Has shipped workarounds: shared memory, C extensions, subinterpreters — not just theory |
| **Trade-off awareness** | Knows when threading IS fine (I/O) and when multiprocessing hurts (serialization overhead) |
| **Modern Python** | Aware of subinterpreters (3.12), free-threaded Python (3.13t), nogil experiment |

---

## Question 2: Async/Await — Event Loop Internals

**Interviewer:** *"Walk me through what happens when you `await` a coroutine. How does the event loop schedule it?"*

### 🎯 Expected Answer

**Step-by-step event loop cycle:**

```python
# Simplified event loop (asyncio uses selectors + callbacks)
class ToyEventLoop:
    def __init__(self):
        self._ready = deque()           # Ready coroutines
        self._scheduled = []            # Sleeping coroutines (heap by time)
        self._stopping = False
    
    def run_forever(self):
        while not self._stopping:
            # Phase 1: Run all ready callbacks
            while self._ready:
                coro = self._ready.popleft()
                coro.send(None)  # Advance coroutine to next await
        
            # Phase 2: Poll I/O (timeout = time until next scheduled)
            timeout = self._time_until_next_scheduled()
            events = self._selector.select(timeout)
            for key, mask in events:
                cb = key.data  # callback registered via add_reader
                self._ready.append(cb)
            
            # Phase 3: Move expired timers to ready queue
            now = time.monotonic()
            while self._scheduled and self._scheduled[0].when <= now:
                handle = heapq.heappop(self._scheduled)
                self._ready.append(handle.callback)
```

**The `await` protocol in detail:**

```python
# Every awaitable must implement __await__ → returns iterator
class CustomAwaitable:
    def __await__(self):
        # Yield control back to event loop
        # The sent value comes from coro.send() in the event loop
        result = yield from self._internal_generator()
        return result

# What `async def` actually generates:
async def fetch_url(url):
    # The compiler generates a coroutine function that:
    # 1. Creates a coroutine object on call
    # 2. Implements __await__ → returns its own generator
    # 3. At every `await`, suspends execution via yield
    response = await http_get(url)  # → calls __await__ → yields Future
    # When http_get completes, event loop calls coro.send(response)
    return response.status

# The critical piece: Future.__await__()
class Future:
    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self  # Yield the Future itself to the event loop
        return self.result()
    
    # Event loop side (simplified):
    def _schedule(self, coro):
        try:
            # First send(None) advances coroutine to first yield
            # The yielded value is a Future
            future = coro.send(None)
            # Register callback: when future completes, schedule coro again
            future.add_done_callback(lambda f: self._ready.append(coro))
        except StopIteration as e:
            # Coroutine completed
            pass
```

**Why uvloop is 2x faster:**

```python
import uvloop
import asyncio

# uvloop replaces asyncio's selector-based event loop with libuv
# (the same library powering Node.js)
# Key optimizations:
# 1. libuv uses epoll (Linux) / kqueue (macOS) directly — no Python overhead per event
# 2. Async handle operations in C — no Python function calls per I/O
# 3. Timer management in C with heap, not Python heapq
# 4. DNS resolution in C via libuv's async DNS (c-ares)

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# ~2-3x throughput improvement for I/O-bound workloads
# ~50% latency reduction at p99
```

**Structured concurrency with `TaskGroup` (3.11+):**

```python
async def handle_request(client_id: int) -> None:
    """All tasks are properly scoped — no orphaned tasks"""
    try:
        async with asyncio.TaskGroup() as tg:
            # If any task fails, all siblings are cancelled
            task1 = tg.create_task(fetch_metadata(client_id))
            task2 = tg.create_task(fetch_history(client_id))
            task3 = tg.create_task(fetch_preferences(client_id))
        
        # All tasks completed successfully here
        return merge_results(task1.result(), task2.result(), task3.result())
    except* asyncio.CancelledError:
        # TaskGroup was cancelled — clean up
        await cleanup(client_id)
        raise
```

**Staff-level insight — the hidden cost of `asyncio.gather()`:**

```python
# Problem: gather() wraps ALL partial results even on exception
async def fragile_service():
    results = await asyncio.gather(
        request_a(),  # Takes 100ms, then fails
        request_b(),  # Takes 5s — still runs to completion!
        return_exceptions=True,
    )
    # You waited 5s even though you could have failed fast!

# Better: TaskGroup or asyncio.wait with FIRST_EXCEPTION
async def fast_fail():
    done, pending = await asyncio.wait(
        [request_a(), request_b()],
        return_when=asyncio.FIRST_EXCEPTION,
    )
    # Cancel pending tasks immediately
    for task in pending:
        task.cancel()
    # Process done tasks
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Protocol knowledge** | Knows `__await__` → `__iter__` → `yield` under the hood |
| **Event loop mechanics** | Explains the 3 phases: ready queue → I/O poll → timer sweep |
| **Production experience** | Has tuned event loops, used uvloop, fixed callback blocking |
| **Modern features** | Knows TaskGroup, except*, Barrier, Queue patterns |

---

## Question 3: Metaclasses & Descriptors — The Object Model Under the Hood

**Interviewer:** *"Design a Django-style ORM field system. How do metaclasses and descriptors make it work?"*

### 🎯 Expected Answer

**The building blocks:**

```python
# Descriptor protocol: controls attribute access on *another* class
class Field(ABC):
    """A descriptor that manages a model field"""
    
    def __set_name__(self, owner: type, name: str) -> None:
        """Called when the owning class is created — PEP 487 (3.6+)"""
        self.name = name
        self.private_name = f"_{name}"
    
    def __get__(self, obj: object | None, objtype: type | None = None):
        if obj is None:
            return self  # Class-level access returns the descriptor itself
        return getattr(obj, self.private_name)
    
    def __set__(self, obj: object, value: Any) -> None:
        # Each Field subclass has its own validation
        self.validate(value)
        setattr(obj, self.private_name, value)
    
    @abstractmethod
    def validate(self, value: Any) -> None: ...

class CharField(Field):
    def __init__(self, max_length: int = 255, required: bool = True):
        self.max_length = max_length
        self.required = required
    
    def validate(self, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{self.name} must be a string, got {type(value)}")
        if len(value) > self.max_length:
            raise ValueError(f"{self.name} exceeds {self.max_length} chars")
        if self.required and not value.strip():
            raise ValueError(f"{self.name} is required")

class IntegerField(Field):
    def __init__(self, min_value: int | None = None, max_value: int | None = None):
        self.min_value = min_value
        self.max_value = max_value
    
    def validate(self, value: Any) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{self.name} must be an integer")
        if self.min_value is not None and value < self.min_value:
            raise ValueError(f"{self.name} must be >= {self.min_value}")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"{self.name} must be <= {self.max_value}")
```

**Now the metaclass that makes it magical:**

```python
class ModelMeta(type):
    """Metaclass: controls class creation itself"""
    
    def __new__(mcs, name: str, bases: tuple, namespace: dict) -> type:
        """Called when a Model subclass is defined (class User(Model): ...)"""
        # Step 1: Create the class normally
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Step 2: Collect all Field descriptors into _fields
        fields: dict[str, Field] = {}
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, Field):
                fields[attr_name] = attr_value
        
        # Step 3: Also inherit fields from parent classes
        for base in bases:
            if hasattr(base, '_fields'):
                for fname, fval in base._fields.items():
                    if fname not in fields:  # Don't override child's fields
                        fields[fname] = fval
        
        cls._fields = fields
        
        # Step 4: Auto-generate table name from class name
        cls._table = ''.join('_' + c.lower() if c.isupper() else c 
                            for c in name).lstrip('_') + 's'
        
        return cls
    
    def __init__(cls, name: str, bases: tuple, namespace: dict):
        """Called after __new__ — use for post-initialization"""
        super().__init__(name, bases, namespace)
        
        # Build create table SQL (one-time, at class definition time)
        if hasattr(cls, '_fields'):
            columns = []
            for fname, field in cls._fields.items():
                sql_type = {
                    CharField: f"VARCHAR({field.max_length})",
                    IntegerField: "INTEGER",
                    # ... more types
                }.get(type(field), "TEXT")
                nullability = "NOT NULL" if getattr(field, 'required', True) else "NULL"
                columns.append(f"  {fname} {sql_type} {nullability}")
            
            cls._ddl = f"CREATE TABLE IF NOT EXISTS {cls._table} (\n" + \
                       ",\n".join(columns) + "\n);"

class Model(metaclass=ModelMeta):
    """Base class for all models — automatically gets metaclass behavior"""
    
    def __init__(self, **kwargs):
        # Set attributes via descriptors (triggers validation)
        for name, value in kwargs.items():
            if name not in self._fields:
                raise AttributeError(f"'{type(self).__name__}' has no field '{name}'")
            setattr(self, name, value)
    
    def save(self):
        """Auto-generate INSERT from _fields"""
        columns = list(self._fields.keys())
        values = [getattr(self, name) for name in columns]
        placeholders = ', '.join(['?' for _ in columns])
        sql = f"INSERT INTO {self._table} ({', '.join(columns)}) VALUES ({placeholders})"
        # db.execute(sql, values)
```

**Usage:**

```python
class User(Model):
    email = CharField(max_length=255, required=True)
    name = CharField(max_length=100, required=True)
    age = IntegerField(min_value=0, max_value=150)

# What actually happens:
# 1. ModelMeta.__new__ is called with namespace={'email': CharField(), ...}
# 2. '_fields' dict is built: {'email': CharField(...), 'name': CharField(...), 'age': IntegerField(...)}
# 3. DDL is generated: "CREATE TABLE IF NOT EXISTS users (...)"
# 4. Descriptors take over attribute access

user = User(email="alice@example.com", name="Alice", age=30)
user.age = 200  # → ValueError: age must be <= 150
```

**Staff-level insight — why `__set_name__` over `__init__`:**

```python
# Before PEP 487 (3.5 and earlier), you had to do this:
class OldField:
    def __init__(self, name=None):
        self.name = name  # ← Had to pass name explicitly!

class User(Model):
    email = OldField(name='email')  # ← So much boilerplate

# The descriptor had no way to know its attribute name during __init__
# because at that point, the class doesn't exist yet.
# __set_name__ is called by type.__new__ AFTER the class is created,
# passing the class and the attribute name.

# Even deeper: __init_subclass__ (PEP 487) also simplified metaclass usage
class PluginBase:
    _registry: dict[str, type] = {}
    
    def __init_subclass__(cls, **kwargs):
        """Called when ANY subclass is created — no metaclass needed!"""
        super().__init_subclass__(**kwargs)
        PluginBase._registry[cls.__name__] = cls
        cls._initialized = True

# Now any class inheriting PluginBase auto-registers
class MyPlugin(PluginBase): ...  # → PluginBase._registry['MyPlugin'] = MyPlugin
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Protocol chaining** | Understands how `__new__` → `__init__` → `__set_name__` sequence works |
| **Real metaclass use** | Has seen production metaclasses (ORM, DI, serialization) — not just toy examples |
| **PEP history** | Knows why `__set_name__` (PEP 487) and `__init_subclass__` eliminated 80% of metaclass needs |
| **Limitations** | Understands metaclass conflicts, diamond inheritance issues with multiple metaclasses |

---

## Question 4: Memory Management — CPython's Allocator & GC

**Interviewer:** *"A production service has a memory leak. Walk me through how you'd find and fix it using only CPython internals."*

### 🎯 Expected Answer

**The CPython memory hierarchy:**

```
┌──────────────────────────────────────────────┐
│              Python Objects                    │
│  (PyObject — ob_refcnt, ob_type, ob_size)     │
├──────────────────────────────────────────────┤
│               PyMem_Allocator                  │
│  Layer 0: Raw (malloc/free — system alloc)    │
│  Layer 1: Object allocator (PyMem_Malloc)     │
│  Layer 2: Cyclic GC (generational collector)    │
├──────────────────────────────────────────────┤
│            Arena-based allocator               │
│  256 KB arenas → 4 KB pools → blocks          │
│  Blocks: 8/16/24/32/.../512 bytes (8-byte     │
│  aligned, size class determined by index)      │
└──────────────────────────────────────────────┘
```

**Reference counting vs GC:**

```python
# Every PyObject has ob_refcnt
# When refcount hits 0 → immediate deallocation
# This is deterministic — unlike tracing GCs

# BUT: cycles can't be resolved by refcounting
class Node:
    def __init__(self):
        self.next = None

a = Node()
b = Node()
a.next = b
b.next = a  # ← Reference cycle!
del a        # refcount is 1 (b.next still points)
del b        # refcount is 1 (a.next still points)
# These objects are now unreachable BUT not freed!
# This is where the cyclic GC comes in.
```

**The cyclic GC (generational, 3 generations):**

```python
import gc

# Generation thresholds (default):
# Gen 0: 700 allocations → collect
# Gen 1: 10 collections of gen 0 → collect
# Gen 2: 10 collections of gen 1 → collect

@gc.callback  # Register a callback BEFORE collection
def gc_callback(phase, info):
    if phase == 'start':
        print(f"GC gen {info['generation']} starting — {info['collected']} objects collected")
    elif phase == 'stop':
        print(f"GC gen {info['generation']} done — {info['uncollectable']} uncollectable")
```

**Diagnosing a leak in production:**

```python
# Step 1: Collect baseline
import sys
import objgraph  # Third-party but indispensable

# Step 2: Find growing objects
objgraph.show_growth(limit=15)
# Output:
# tuple                    12345   +89
# dict                     5678    +45
# MyLeakyClass             234     +234     ← Growing fast!

# Step 3: Find who holds references
objgraph.show_backrefs(
    [obj for obj in gc.get_objects() if isinstance(obj, MyLeakyClass)],
    max_depth=5,
    filename='leak.png'
)

# Step 4: Check for common patterns
def find_common_leaks():
    leaks = {
        'threading._shutdown': [],
        'weakref.WeakSet': [],
        'functools.lru_cache': [],
    }
    for obj in gc.get_objects():
        for pattern, storage in leaks.items():
            if pattern in type(obj).__module__:
                # If thread holds large objects...
                pass
    return leaks
```

**Common production leak patterns:**

```python
# Pattern 1: Exception traceback frames
def leaky():
    try:
        risky_operation()
    except Exception:
        import traceback
        tb = traceback.format_exc()  # ← Holds frame references!
        log.error(tb)
        # Frame objects have __locals__ with ALL local variables
        # If a local holds a large object, it can't be freed

# Fix: clear traceback
except Exception:
    _, _, tb = sys.exc_info()
    log.exception("Failed")
    del tb  # Or use tb=None in except clause (3.12+: PEP 3110)
```

```python
# Pattern 2: LRU cache with unhashable/leaked keys
@functools.lru_cache(maxsize=10000)
def get_user_profile(user_id: int) -> dict:
    return db.query(...)

# Problem: if user_id is a mutable object, it never matches
# and cache grows unbounded.
# Worse: if user_id is a dict with transaction context,
# that dict is kept alive by the cache.

# Fix: ensure keys are hashable and small, use weakref for larger objects
```

```python
# Pattern 3: Celery/thread pool task references
from celery import Celery
app = Celery()

@app.task
def process_user(user_id: int):
    # The task object holds references to ALL local variables
    # until the next task starts (if using thread pool)
    # If a task hangs, it keeps all objects alive
    pass

# Fix: explicit cleanup in long-running workers
# @worker_process_shutdown.connect
# def cleanup(sender, **kwargs):
#     gc.collect(2)  # Force full collection
```

**Deep debugging with `gc` and `sys`:**

```python
def find_leak(threshold_mb: int = 100) -> list[tuple[str, int]]:
    """Find objects holding more than threshold_mb of memory"""
    gc.collect(2)  # Full collection first
    snapshot: dict[type, int] = {}
    
    for obj in gc.get_objects():
        obj_size = sys.getsizeof(obj)
        type_name = type(obj).__module__ + '.' + type(obj).__qualname__
        snapshot[type_name] = snapshot.get(type_name, 0) + obj_size
    
    # Filter by size
    leaks = [(name, size) for name, size in snapshot.items() 
             if size > threshold_mb * 1024 * 1024]
    return sorted(leaks, key=lambda x: -x[1])
```

**Staff-level insight — `__slots__` and memory layout:**

```python
# Normal class: each instance has __dict__ (hash table) + __weakref__ (48 bytes overhead)
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(1, 2)
print(sys.getsizeof(p))          # 56 bytes
print(sys.getsizeof(p.__dict__)) # 184 bytes (empty dict!)
# Total: ~240 bytes per point

# Slotted class: no __dict__, no __weakref__
class PointSlots:
    __slots__ = ('x', 'y')
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = PointSlots(1, 2)
print(sys.getsizeof(p))          # 40 bytes (no __dict__)
hasattr(p, '__dict__')           # False
# Total: 40 bytes — 6x memory savings!

# Production use: Pandas uses __slots__ for DataFrame rows,
# ORMs use it for model instances, game engines for entities
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Three-layer allocator** | Knows arena → pool → block system, not just "CPython uses malloc" |
| **GC vs refcounting** | Understands uncollectable cycles, `__del__` interaction with GC |
| **Tool experience** | Has used `gc.get_objects()`, `objgraph`, `tracemalloc`, `sys.getsizeof` in production |
| **Leak patterns** | Can describe traceback frames, cache leaks, task references without prompting |

---

## Question 5: Type System — Protocols, Generics, and Variance at Scale

**Interviewer:** *"Design a type-safe event bus that dispatches typed events to typed handlers. Handle covariance and contravariance correctly."*

### 🎯 Expected Answer

**Building a type-safe, generic event bus using modern Python typing:**

```python
from typing import (Generic, TypeVar, Protocol, runtime_checkable,
                    assert_type, reveal_type, overload, Concatenate,
                    ParamSpec, Generic, Self)
from datetime import datetime
import asyncio
from collections.abc import Callable, Awaitable

# ── Foundation types ──────────────────────────────────────

EventT = TypeVar('EventT', bound='Event')
ResultT = TypeVar('ResultT', covariant=True)  # ← covariant!
ContraEventT = TypeVar('ContraEventT', bound='Event', contravariant=True)  # ← contravariant!
P = ParamSpec('P')

class Event:
    """Base class for all events"""
    event_id: str
    timestamp: datetime
    
    def __init__(self) -> None:
        self.event_id = str(uuid4())
        self.timestamp = datetime.now()

class UserCreated(Event):
    def __init__(self, user_id: str, email: str) -> None:
        super().__init__()
        self.user_id = user_id
        self.email = email

class OrderPlaced(Event):
    def __init__(self, order_id: str, amount: float) -> None:
        super().__init__()
        self.order_id = order_id
        self.amount = amount

# ── Handler protocol with variance ────────────────────────

@runtime_checkable
class Handler(Protocol[ContraEventT, ResultT]):
    """A handler that processes events — contravariant in event type (consumes),
    covariant in result type (produces)"""
    
    async def handle(self, event: ContraEventT) -> ResultT:
        ...
    
    @property
    def name(self) -> str:
        ...

# ── Concrete handlers ─────────────────────────────────────

class BaseHandler(Generic[EventT, ResultT]):
    """Abstract base implementing the Handler protocol"""
    async def handle(self, event: EventT) -> ResultT:
        return await self.process(event)
    
    async def process(self, event: EventT) -> ResultT:
        raise NotImplementedError

class EmailNotifier(BaseHandler[UserCreated, bool]):
    async def process(self, event: UserCreated) -> bool:
        print(f"Sending welcome email to {event.email}")
        return True

class AuditLogger(BaseHandler[Event, None]):  # Handles ANY Event
    async def process(self, event: Event) -> None:
        print(f"[AUDIT] {type(event).__name__}: {event.event_id}")

class OrderProcessor(BaseHandler[OrderPlaced, str]):
    async def process(self, event: OrderPlaced) -> str:
        print(f"Processing order {event.order_id} for ${event.amount}")
        return f"order_{event.order_id}_confirmed"

# ── The event bus ─────────────────────────────────────────

class EventBus:
    """Type-safe event bus with subscription management"""
    
    def __init__(self):
        self._subscribers: dict[type[Event], list[Handler]] = {}
    
    def subscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT, ResultT],
    ) -> None:
        """Subscribe a handler to an event type.
        
        Type safety: Handler is contravariant in EventT, so:
        - Handler[Event, R] can subscribe to Event.ANY subclass
        - Handler[UserCreated, R] can ONLY subscribe to UserCreated
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    async def publish(self, event: EventT) -> list[Any]:
        """Publish event to all subscribers"""
        results: list[Any] = []
        
        # Direct subscribers
        for handler in self._subscribers.get(type(event), []):
            result = await handler.handle(event)
            results.append(result)
        
        # Also notify parent-type subscribers (e.g., AuditLogger)
        for parent_type, handlers in self._subscribers.items():
            if parent_type is not type(event) and isinstance(event, parent_type):
                for handler in handlers:
                    result = await handler.handle(event)
                    results.append(result)
        
        return results
    
    # ── Decorator-based subscription ──────────────────────
    
    def on(self, event_type: type[EventT]):
        """Decorator to register a handler function"""
        def decorator(func: Callable[Concatenate[EventT, P], Awaitable[ResultT]]):
            handler = FunctionHandler(event_type, func)
            self.subscribe(event_type, handler)
            return func
        return decorator

# ── Usage ─────────────────────────────────────────────────

bus = EventBus()

# Type-safe subscription:
bus.subscribe(UserCreated, EmailNotifier())   # ✅ Exact match
bus.subscribe(UserCreated, AuditLogger())     # ✅ AuditLogger[Event, None] → contravariant: Event ≺ UserCreated
bus.subscribe(OrderPlaced, OrderProcessor())  # ✅ Exact match

# bus.subscribe(OrderPlaced, EmailNotifier()) # ❌ Type error: EmailNotifier expects UserCreated, not OrderPlaced

@bus.on(OrderPlaced)
async def discount_engine(event: OrderPlaced) -> float:
    """Calculate discount for order"""
    return event.amount * 0.1

# Publishing:
async def demo():
    user_event = UserCreated(user_id="u123", email="alice@example.com")
    results = await bus.publish(user_event)
    print(f"Results: {results}")

asyncio.run(demo())
```

**Variance explained for staff-level interviews:**

```python
# ── Variance intuition ──────────────────────
# 
# If Dog is a subtype of Animal (Dog <: Animal):
# 
# 1. Covariance:  List[Dog] <: List[Animal]?
#    → NO in Python (mutable). YES in general (read-only).
#    → Use: List[Animal] = List[Dog] is safe IF you only read.
#    → Python: use Sequence[Dog] (immutable → covariant)
#
# 2. Contravariance:  Handler[Animal] <: Handler[Dog]?
#    → YES! A handler that handles ANY Animal can also handle Dogs.
#    → The handler CONSUMES events, so it's contravariant.
#    → "If you need a function that processes Dogs, a function
#       that processes ALL Animals will work fine."
#
# 3. Invariance:  MutableList[Dog] is NOT a subtype of MutableList[Animal]
#    → Because if you could add a Cat to MutableList[Animal],
#    → and MutableList[Animal] = MutableList[Dog], you just put a Cat in a Dog list!

# Python typing variance:
from typing import Generic, TypeVar

T = TypeVar('T')              # Invariant (default)
T_co = TypeVar('T_co', covariant=True)        # Covariant (producer)
T_contra = TypeVar('T_contra', contravariant=True)  # Contravariant (consumer)

class Stack(Generic[T]):  # Invariant — push AND pop
    def push(self, item: T) -> None: ...
    def pop(self) -> T: ...

class Source(Generic[T_co]):  # Covariant — only produces
    def get(self) -> T_co: ...

class Sink(Generic[T_contra]):  # Contravariant — only consumes
    def put(self, item: T_contra) -> None: ...
```

**Protocol structural subtyping (duck typing at type-check time):**

```python
@runtime_checkable
class Comparable(Protocol):
    """Any type that implements __lt__ is structurally a Comparable"""
    def __lt__(self, other: Any) -> bool: ...

class Version:
    def __init__(self, major: int, minor: int):
        self.major = major
        self.minor = minor
    
    def __lt__(self, other: 'Version') -> bool:
        return (self.major, self.minor) < (other.major, other.minor)

def sort_items(items: list[Comparable]) -> list[Comparable]:
    """Works with any list of comparable items — zero inheritance needed"""
    return sorted(items)

sort_items([Version(2, 0), Version(1, 0)])  # ✅ Works
sort_items([3, 1, 2])                        # ✅ int is comparable
sort_items([{'a': 1}, {'b': 2}])             # ❌ dict is NOT comparable
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Variance mastery** | Explains covariance/producer vs contravariance/consumer naturally |
| **Protocol usage** | Uses `Protocol` for structural typing, not just ABC inheritance |
| **Self type** | Knows `Self` (PEP 673, 3.11+) for return type annotation in class methods |
| **Actual production** | Has designed type-safe APIs, understands `reveal_type`, `assert_type` |

---

## Question 6: Context Managers & Generators — Coroutines Before `async`

**Interviewer:** *"Implement a database connection pool using only generators (no asyncio). Then explain how generators enable async/await under the hood."*

### 🎯 Expected Answer

```python
from collections.abc import Generator
from contextlib import contextmanager, asynccontextmanager
import time
import threading
from queue import Queue, Empty
from typing import Optional

class DatabaseConnection:
    """Simulated DB connection"""
    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.in_use = False
    
    def query(self, sql: str) -> str:
        time.sleep(0.1)  # Simulate I/O
        return f"Result from conn-{self.conn_id}: {sql}"

class ConnectionPool:
    """Thread-safe connection pool using context managers"""
    
    def __init__(self, min_size: int = 2, max_size: int = 10):
        self._min = min_size
        self._max = max_size
        self._pool: Queue[DatabaseConnection] = Queue()
        self._size = 0
        self._lock = threading.Lock()
        
        # Pre-create minimum connections
        for _ in range(min_size):
            self._pool.put(self._create_connection())
    
    def _create_connection(self) -> DatabaseConnection:
        with self._lock:
            self._size += 1
        return DatabaseConnection(self._size)
    
    @contextmanager
    def acquire(self) -> Generator[DatabaseConnection, None, None]:
        """Context manager that:
        1. Gets a connection (or creates one)
        2. Yields it to the caller
        3. Returns it to pool (even if exception!)
        """
        conn = self._acquire_connection()
        try:
            yield conn  # ← Generator yields control here
        finally:
            self._release_connection(conn)
    
    def _acquire_connection(self) -> DatabaseConnection:
        try:
            return self._pool.get_nowait()
        except Empty:
            with self._lock:
                if self._size < self._max:
                    return self._create_connection()
            # Block until a connection is available
            return self._pool.get(timeout=30)
    
    def _release_connection(self, conn: DatabaseConnection) -> None:
        conn.in_use = False
        self._pool.put(conn)

# Usage:
pool = ConnectionPool()

with pool.acquire() as conn:  # __enter__ → generator.send(None)
    result = conn.query("SELECT * FROM users")
    print(result)  # __exit__ → generator.throw() or generator.close()
```

**How generators underpin async/await:**

```python
# ── A coroutine is a generator ────────────────────────
# async def == generator-based coroutine in CPython

def generator_coroutine():
    """Traditional generator = the foundation of async"""
    print("Step 1: Started")
    value = yield 1  # Suspends here
    print(f"Step 2: Got {value}")
    value = yield 2  # Suspends here
    print(f"Step 3: Got {value}")
    return "done"

# Manual drive:
gen = generator_coroutine()
result = gen.send(None)   # "Step 1: Started" → yields 1
result = gen.send("A")     # "Step 2: Got A" → yields 2
result = gen.send("B")     # "Step 3: Got B" → StopIteration("done")

# ── This is EXACTLY how asyncio works ─────────────────
# async def fetch():          → def fetch(): return fetch().__await__()
#     response = await get()  → response = yield from get().__await__()
#     return response         → return response → raise StopIteration(response)

# ── Taming generators with `yield from` ──────────────
def chain():
    """yield from delegates to another generator"""
    yield from generator_coroutine()  # Delegate to sub-generator
    yield "chain done"

# ── The @contextmanager decorator ─────────────────────
# It literally does this:
class _GeneratorContextManager:
    def __init__(self, func, args, kwargs):
        self.gen = func(*args, **kwargs)
    
    def __enter__(self):
        try:
            return next(self.gen)  # Advance to first yield
        except StopIteration:
            raise RuntimeError("generator didn't yield")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            try:
                next(self.gen)  # Resume generator (runs finally)
            except StopIteration:
                return False
            raise RuntimeError("generator didn't stop")
        else:
            try:
                self.gen.throw(exc_type, exc_val, exc_tb)
            except StopIteration as e:
                return e is not None  # Suppress if return value
            except:  # Exception not handled
                raise
            raise RuntimeError("generator didn't stop after throw")
```

**Staff-level insight — closing and cleanup:**

```python
# What happens with contextlib.closing() and contexlib.suppress()
from contextlib import closing, suppress, ExitStack

# ExitStack: manage multiple context managers dynamically
def process_with_resources():
    """Manage N resources with dynamic lifecycle"""
    with ExitStack() as stack:
        # Open files as needed
        files = []
        for filename in filenames:
            f = stack.enter_context(open(filename))
            files.append(f)
        
        # Enter optional context
        if debug:
            stack.enter_context(enable_profiling())
        
        # All close in reverse order on exit
        process_files(files)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Generator mechanics** | Knows `.send()`, `.throw()`, `.close()` — not just `for x in gen` |
| **yield from** | Understands delegation, bidirectional communication |
| **Context manager protocol** | Can implement `__enter__`/`__exit__` manually, not just `@contextmanager` |
| **Connection pool** | Understands thread safety, capacity management, timeout handling |

---

## Question 7: Import System — Finders, Loaders, and Module Caching

**Interviewer:** *"Design a plugin system that discovers and loads Python modules from a directory at runtime. Then explain how you'd handle circular imports at scale."*

### 🎯 Expected Answer

**The import system in detail:**

```python
import sys

# The import process (simplified):
#
# 1. import foo
# 2. sys.modules.get('foo') → found? → return it
# 3. Iterate through sys.meta_path finders:
#    a. _frozen_importlib.BuiltinImporter  (built-in modules)
#    b. _frozen_importlib.FrozenImporter   (frozen modules)
#    c. PathFinder                          (filesystem)
#    d. Any custom finders you added
# 4. finder.find_spec('foo', ...) → ModuleSpec or None
# 5. spec.loader.exec_module(module) → executes code
# 6. sys.modules['foo'] = module
```

**Custom finder + loader for a plugin system:**

```python
import importlib.abc
import importlib.util
import sys
import os
from pathlib import Path
from typing import Optional

class PluginFinder(importlib.abc.MetaPathFinder):
    """Custom finder that discovers plugins from a directory"""
    
    def __init__(self, plugin_dir: str):
        self.plugin_dir = Path(plugin_dir).resolve()
        self._cache: dict[str, ModuleSpec] = {}
        self._scan()
    
    def _scan(self) -> None:
        """Scan plugin directory for Python files"""
        for path in self.plugin_dir.glob("*.py"):
            if path.stem.startswith('_'):
                continue  # Skip __init__.py etc.
            
            spec = importlib.util.spec_from_file_location(
                f"plugins.{path.stem}",
                path,
                submodule_search_locations=None,
            )
            if spec:
                self._cache[path.stem] = spec
    
    def find_spec(self, fullname: str, path: list[str] | None, 
                  target: object | None = None) -> Optional[ModuleSpec]:
        """Called by import machinery for each module import"""
        # Only handle 'plugins.' prefix
        if not fullname.startswith('plugins.'):
            return None
        
        name = fullname.split('.')[-1]
        return self._cache.get(name)

# Register the finder
sys.meta_path.insert(0, PluginFinder('./plugins'))

# Now importing works:
# import plugins.email_notifier  → PluginFinder.find_spec('plugins.email_notifier')

# Install hooks for plugin lifecycle:
class PluginLoader:
    _plugins: dict[str, type] = {}
    
    @classmethod
    def discover(cls, directory: str = './plugins') -> list[str]:
        """Discover and load all plugins"""
        finder = PluginFinder(directory)
        sys.meta_path.insert(0, finder)
        
        loaded = []
        for name in finder._cache:
            try:
                module = importlib.import_module(f"plugins.{name}")
                if hasattr(module, 'register'):
                    cls._plugins[name] = module.register()
                    loaded.append(name)
            except Exception as e:
                print(f"Failed to load plugin {name}: {e}")
        return loaded
    
    @classmethod
    def reload_all(cls) -> None:
        """Hot-reload all plugins (for development)"""
        for name in list(cls._plugins):
            fullname = f"plugins.{name}"
            if fullname in sys.modules:
                importlib.reload(sys.modules[fullname])
                if hasattr(sys.modules[fullname], 'register'):
                    cls._plugins[name] = sys.modules[fullname].register()
```

**Circular imports — the root cause and solutions:**

```python
# ── Why circular imports happen ──────────────────────
# file: models/user.py
from models.order import Order  # ← imports Order when user module loads

class User:
    orders: list[Order]  # Type reference only
    
    def get_total(self) -> float:
        return sum(o.amount for o in self.orders)

# file: models/order.py
from models.user import User  # ← imports User when order module loads

class Order:
    user: User  # Type reference only
    
    def get_user_email(self) -> str:
        return self.user.email

# Result: ImportError when either module is loaded first!

# ── Solution 1: Defer imports ────────────────────────
# This is the most common production fix:
class User:
    orders: list['Order']  # String annotation = lazy evaluation
    
    def get_orders(self):
        from models.order import Order  # ← Deferred import
        return [o for o in self.orders if isinstance(o, Order)]

# ── Solution 2: from __future__ import annotations ───
from __future__ import annotations  # ALL annotations are strings (3.7+)

class User:
    orders: list[Order]  # Not evaluated at import time
    
    def get_total(self) -> float:
        return sum(o.amount for o in self.orders)

# Now both modules can safely import each other
# Annotations are only resolved when actually used (via typing.get_type_hints())

# ── Solution 3: Interface modules ────────────────────
# models/interfaces.py — NO imports from models/
from typing import Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class UserLike(Protocol):
    email: str
    def get_orders(self) -> Iterable['OrderLike']: ...

@runtime_checkable
class OrderLike(Protocol):
    amount: float
    def get_user(self) -> UserLike: ...

# models/user.py
from models.interfaces import OrderLike

class User:
    def __init__(self, email: str):
        self.email = email
        self._orders: list[OrderLike] = []
```

**Production insight — eager vs lazy loading:**

```python
# ── Startup performance optimization ────────────────
import importlib
import time

# Lazy module loading for expensive imports:
class LazyModule:
    def __init__(self, name: str):
        self._name = name
        self._module = None
    
    def __getattr__(self, name: str):
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, name)

# Usage: pandas = LazyModule('pandas')
# pandas.DataFrame  # ← Only imported here!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **MetaPathFinder** | Knows how to insert custom finders into `sys.meta_path` |
| **ModuleSpec** | Understands the full spec protocol (loader, origin, submodule_search_locations) |
| **Circular import** | Has real solutions beyond "restructure your code" |
| **Lazy loading** | Understands `sys.modules` manipulation, deferred imports, startup optimization |

---

## Question 8: C Extensions & Performance — When Python Isn't Fast Enough

**Interviewer:** *"You have a hot loop processing 10M JSON objects. Python is too slow. Walk me through your optimization strategy from Python-level improvements through C extensions."*

### 🎯 Expected Answer

**Tier 1 — Python-level optimization (often sufficient for 3-10x):**

```python
# BEFORE: Slow
data = []
for item in huge_list:
    processed = process(item)  # Function call overhead per item
    data.append(processed)

# AFTER: Use built-ins and comprehensions
# (CPython optimizes comprehensions — no LOAD_GLOBAL for append)
data = [process(item) for item in huge_list]  # ~30% faster

# Use local variable binding (avoid global lookups)
def fast_process(items: list, _process=process) -> list:
    """_process is a local default — avoids global dict lookup"""
    return [_process(item) for item in items]

# Use __slots__ for data classes
from dataclasses import dataclass

@dataclass(slots=True)  # 3.10+ — ~40% faster, ~60% less memory
class Point:
    x: float
    y: float
```

**Tier 2 — NumPy vectorization (10-100x for numeric):**

```python
import numpy as np
import json

# Instead of processing JSON objects one by one,
# extract arrays and use vectorized operations:

def process_json_batch(json_strings: list[str]) -> np.ndarray:
    """Parse 10M JSON objects using vectorized extraction"""
    # Extract all values into flat arrays
    ids = np.array([json.loads(s)['id'] for s in json_strings])
    amounts = np.array([json.loads(s)['amount'] for s in json_strings])
    
    # Vectorized computation — C speed
    result = amounts * (1 + 0.1 * np.sin(ids / 1000))  # No Python loop
    return result
```

**Tier 3 — Cython (10-50x):**

```cython
# process.pyx
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False

import cython
from libc.math cimport sin

@cython.cfunc
@cython.inline
cdef double compute(double amount, double id_factor) nogil:
    return amount * (1.0 + 0.1 * sin(id_factor))

def process_batch(list items):
    cdef Py_ssize_t i, n = len(items)
    cdef double amount, id_val
    cdef list results = [None] * n
    
    for i in range(n):
        amount = items[i]['amount']
        id_val = <double>items[i]['id']
        results[i] = compute(amount, id_val / 1000.0)
    
    return results
```

**Tier 4 — C extension (100-500x):**

```c
// process_module.c
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>

// The processing function — no Python overhead
static PyObject* process_batch(PyObject* self, PyObject* args) {
    PyObject* items;
    if (!PyArg_ParseTuple(args, "O", &items))
        return NULL;
    
    Py_ssize_t n = PyList_Size(items);
    PyObject* results = PyList_New(n);
    if (!results) return NULL;
    
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject* item = PyList_GetItem(items, i);
        
        // Extract 'amount' field (C-level dict access — no Python call)
        PyObject* amount_obj = PyDict_GetItemString(item, "amount");
        double amount = PyFloat_AsDouble(amount_obj);
        
        // Extract 'id' field
        PyObject* id_obj = PyDict_GetItemString(item, "id");
        double id_val = (double)PyLong_AsLong(id_obj);
        
        // Compute in C
        double result = amount * (1.0 + 0.1 * sin(id_val / 1000.0));
        
        // Set result
        PyList_SetItem(results, i, PyFloat_FromDouble(result));
    }
    
    return results;
}

// Module definition
static PyMethodDef ProcessMethods[] = {
    {"process_batch", process_batch, METH_VARARGS, "Process a batch of items"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef processmodule = {
    PyModuleDef_HEAD_INIT,
    "process_c",
    NULL,
    -1,
    ProcessMethods
};

PyMODINIT_FUNC PyInit_process_c(void) {
    return PyModule_Create(&processmodule);
}
```

**Tier 5 — `numba` JIT (just-in-time compilation, 100x with no C code):**

```python
from numba import jit, prange
import numpy as np

@jit(nopython=True, parallel=True, cache=True)
def process_batch_numba(amounts: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """JIT-compiled to machine code — C speed from Python syntax"""
    n = len(amounts)
    result = np.empty(n, dtype=np.float64)
    
    for i in prange(n):  # Parallel loop
        result[i] = amounts[i] * (1.0 + 0.1 * np.sin(ids[i] / 1000.0))
    
    return result
```

**Production decision matrix:**

```python
OPTIMIZATION_GUIDE = {
    'max_speedup_needed': {
        '1-3x': 'Python-level (comprehensions, slots, local refs)',
        '3-10x': 'NumPy vectorization',
        '10-50x': 'Cython (nogil)',
        '50-500x': 'C extension (manual PyObject)',
        '100-1000x': 'Numba JIT or Rust/PyO3',
    },
    'complexity_cost': {
        'comprehensions':       '0 (just better Python)',
        'numpy':                '1 (learn array API)',
        'cython':               '3 (build system, .pyx files)',
        'c_extension':          '5 (memory mgmt, refcounting, segfaults)',
        'numba':                '2 (decorator, nopython constraints)',
        'rust_pyo3':            '4 (build, FFI, deployment)',
    },
    'deployment_constraint': {
        'cython':               'Compiled .so per platform',
        'c_extension':          'Platform wheel required',
        'numba':                'JIT on first call (cold start)',
        'rust_pyo3':            'maturin build, manylinux wheel',
    },
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Tiered approach** | Doesn't jump to C first — optimizes at each level |
| **Profiling-led** | Uses `cProfile`, `py-spy`, `perf` to identify bottlenecks |
| **GIL awareness** | Understands when to use `nogil` in Cython/C extensions |
| **Deployment** | Considers wheel compatibility, platform support, maintenance cost |

---

## Question 9: Async Generators & Async Context Managers — Structured Concurrency

**Interviewer:** *"Design an async streaming data pipeline. Implement a connection that can be used as an async context manager and yields data as an async generator. Handle cleanup properly."*

### 🎯 Expected Answer

```python
import asyncio
from collections.abc import AsyncIterator, AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class StreamConnection:
    """Async connection that supports streaming"""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reconnect_attempts = 0
        self._max_retries = 3
    
    async def connect(self) -> None:
        """Establish connection with retry logic"""
        for attempt in range(self._max_retries):
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=5.0,
                )
                self._reconnect_attempts = 0
                return
            except (ConnectionError, asyncio.TimeoutError) as e:
                self._reconnect_attempts += 1
                wait = min(2 ** attempt, 10)  # Exponential backoff
                logger.warning(f"Connection failed (attempt {attempt+1}), retrying in {wait}s")
                await asyncio.sleep(wait)
        
        raise ConnectionError(f"Failed to connect to {self.host}:{self.port}")
    
    async def read_lines(self) -> AsyncGenerator[str, None]:
        """Async generator that yields lines from the stream"""
        if not self._reader:
            raise RuntimeError("Not connected")
        
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break  # EOF
                yield line.decode('utf-8').rstrip('\n')
        except asyncio.CancelledError:
            # Proper cancellation handling
            logger.info("Stream reading cancelled, cleaning up")
            raise
        finally:
            logger.debug("Stream generator finished")
    
    async def send(self, message: str) -> None:
        """Send a message through the connection"""
        if not self._writer:
            raise RuntimeError("Not connected")
        self._writer.write((message + '\n').encode('utf-8'))
        await self._writer.drain()
    
    async def close(self) -> None:
        """Clean shutdown with drain"""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass  # Already closed
            self._reader = None
            self._writer = None

# ── Async context manager ──────────────────────────────

class ManagedStream:
    """Async context manager wrapping StreamConnection"""
    
    def __init__(self, host: str, port: int):
        self._conn = StreamConnection(host, port)
    
    async def __aenter__(self) -> 'ManagedStream':
        await self._conn.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._conn.close()
        return False  # Don't suppress exceptions
    
    async def read_lines(self) -> AsyncGenerator[str, None]:
        async for line in self._conn.read_lines():
            yield line
    
    async def send(self, message: str) -> None:
        await self._conn.send(message)

# ── Using asynccontextmanager (cleaner syntax) ─────────

@asynccontextmanager
async def open_stream(host: str, port: int):
    """Async context manager using decorator"""
    conn = StreamConnection(host, port)
    try:
        await conn.connect()
        yield conn
    finally:
        await conn.close()

# ── Async generator with cleanup ───────────────────────

async def stream_processor(host: str, port: int) -> AsyncGenerator[dict, None]:
    """Process streamed data, yielding parsed objects"""
    async with open_stream(host, port) as stream:
        async for line in stream.read_lines():
            # Parse and yield — cleanup is handled by the context manager
            try:
                yield parse_line(line)
            except ParseError:
                logger.warning(f"Skipping invalid line: {line}")
                continue

# ── Usage with TaskGroup for structured concurrency ────

async def consume_stream():
    """Properly structured consumer with cancellation"""
    try:
        async with asyncio.TaskGroup() as tg:
            async with open_stream("localhost", 8080) as stream:
                tg.create_task(send_heartbeat(stream))
                
                async for data in stream.read_lines():
                    process(data)  # Each chunk processed here
                    
                    # If processing is slow, we naturally apply backpressure
                    # because the generator won't yield next lines until
                    # this iteration completes
    except* Exception as e:
        logger.error(f"Stream consumer failed: {e}")
        raise

async def send_heartbeat(stream: ManagedStream):
    """Send periodic heartbeats — runs concurrently"""
    while True:
        await asyncio.sleep(30)
        await stream.send("PING")
```

**Staff-level insight — async generator cleanup guarantees:**

```python
# Critical: async generators guarantee cleanup via aclose()

async def resource_holder():
    """This async generator holds a DB connection"""
    conn = await acquire_connection()
    try:
        while True:
            data = await conn.fetch()
            if not data:
                return
            yield data
    finally:
        await conn.close()  # ← Always called, even on CancelledError!

# When the consumer cancels or breaks:
# async for data in resource_holder():
#     if condition:
#         break  # → aclose() is called → generator.throw(CancelledError) → finally runs
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cleanup guarantee** | Understands `aclose()`, `asend()`, `athrow()` for async generators |
| **Cancellation** | Handles `CancelledError` properly in cleanup paths |
| **Backpressure** | Recognizes that async generators naturally apply backpressure |
| **Real protocol** | Has written production async stream processing (not just toy examples) |

---

## Question 10: Packaging & Distribution — Building for the Python Ecosystem

**Interviewer:** *"You need to distribute a Python library that has C extensions. Walk me through your build system, platform support, and distribution strategy."*

### 🎯 Expected Answer

**Modern project structure (PEP 517/518, `pyproject.toml`):**

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel", "setuptools-rust"]
build-backend = "setuptools.build_meta"

[project]
name = "fast-processor"
version = "0.3.0"
description = "High-performance data processor with Rust bindings"
requires-python = ">=3.10"
authors = [{name = "Engineer", email = "eng@example.com"}]
license = {text = "MIT"}

dependencies = [
    "numpy>=1.24",
    "typing-extensions>=4.5; python_version < '3.11'",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-benchmark", "mypy>=1.0"]
docs = ["sphinx>=6.0", "sphinx-rtd-theme"]

[project.urls]
Homepage = "https://github.com/example/fast-processor"
Documentation = "https://fast-processor.readthedocs.io"

[tool.setuptools]
packages = ["fast_processor", "fast_processor._native"]
include-package-data = false

[tool.setuptools.package-data]
"fast_processor._native" = ["*.so", "*.pyd", "*.dylib"]

[tool.setuptools-rust]
# Build Rust extensions with maturin
module-name = "fast_processor._native.core"
```

**Platform wheels (manylinux, musllinux):**

```bash
# Build manylinux2014 wheels (glibc 2.17+, compatible with most Linux)
docker run --rm -v $(pwd):/io quay.io/pypa/manylinux2014_x86_64 bash -c "
    cd /io
    /opt/python/cp311-cp311/bin/pip install maturin
    /opt/python/cp311-cp311/bin/maturin build --release --out dist
    
    # Auditwheel to ensure manylinux compliance
    auditwheel repair dist/fast_processor-*.whl -w dist/
"

# Build for musllinux (Alpine)
docker run --rm -v $(pwd):/io quay.io/pypa/musllinux_1_1_x86_64 bash -c "
    /opt/python/cp311-cp311/bin/pip install maturin
    /opt/python/cp311-cp311/bin/maturin build --release --out dist
"

# macOS universal2 (arm64 + x86_64)
maturin build --release --target universal2-apple-darwin

# Windows
maturin build --release
```

**ABI compatibility — the `cp312-abi3` tag:**

```python
# If your extension uses a stable ABI (PEP 384), you can build ONE wheel
# that works across Python 3.8-3.12:

# Cython: use cpdef instead of cdef for ABI stability
# setup.py:
from setuptools import setup, Extension
import sys

stable_abi = sys.version_info >= (3, 12)
ext = Extension(
    "fast_processor._core",
    sources=["src/core.c"],
    py_limited_api=stable_abi,     # Compile with Py_LIMITED_API
    define_macros=[("Py_LIMITED_API", "0x03080000")] if stable_abi else [],
)

setup(
    ext_modules=[ext],
    options={"bdist_wheel": {"py_limited_api": "cp38"}} if stable_abi else {},
)
```

**Dual packaging (pure Python fallback):**

```python
# fast_processor/__init__.py

def _load_backend():
    """Try native C extension first, fall back to pure Python"""
    try:
        from fast_processor._native import core as _native_impl
        return _native_impl
    except ImportError:
        from fast_processor import _pure as _pure_impl
        import warnings
        warnings.warn(
            "Native extension not available, using pure Python fallback. "
            "Install platform wheel for better performance.",
            RuntimeWarning,
        )
        return _pure_impl

_impl = _load_backend()
process = _impl.process
validate = _impl.validate
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **manylinux** | Knows about manylinux2010/2014/2_28, auditwheel, platform wheels |
| **ABI strategy** | Understands py_limited_api, abi3 tag, and trade-offs |
| **Dual packaging** | Has fallback strategies for platforms without compiled extensions |
| **Build system** | Knows maturin, setuptools-rust, cibuildwheel for CI/CD |

---

## Question 11: Subinterpreters & Free-Threaded Python (3.12/3.13)

**Interviewer:** *"Python 3.12 introduces subinterpreters (PEP 684) and 3.13 adds free-threaded mode (PEP 703). How would you leverage these to build a truly concurrent system?"*

### 🎯 Expected Answer

**Subinterpreters — isolated execution contexts with their own GIL:**

```python
import _xxsubinterpreters as interpreters
import _thread
import queue
from typing import Any

class SubInterpreterPool:
    """Thread pool where each thread hosts its own subinterpreter"""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or (os.cpu_count() or 4)
        self._work_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()
        self._workers: list[_thread.ThreadId] = []
        self._start()
    
    def _start(self) -> None:
        for _ in range(self.max_workers):
            interp_id = interpreters.create()
            t = _thread.start_new_thread(self._worker_loop, (interp_id,))
            self._workers.append(t)
    
    def _worker_loop(self, interp_id: int) -> None:
        """Each thread runs in its own subinterpreter — own GIL"""
        while True:
            task = self._work_queue.get()
            if task is None:  # Shutdown signal
                break
            
            func_source, args = task
            try:
                # Execute in the subinterpreter — truly parallel!
                interpreters.run_string(interp_id, func_source)
                # Get result via channel
                result = interpreters.get_result(interp_id)
                self._result_queue.put(result)
            except Exception as e:
                self._result_queue.put(e)
    
    def submit(self, func_source: str, args: tuple = ()) -> None:
        self._work_queue.put((func_source, args))
    
    def shutdown(self) -> None:
        for _ in self._workers:
            self._work_queue.put(None)

# Before (GIL-bound):
# with concurrent.futures.ThreadPoolExecutor() as pool:
#     results = pool.map(cpu_intensive_func, data)  # Still serialized by GIL!

# After (with subinterpreters):
pool = SubInterpreterPool()
pool.submit("def calc(x): return x ** 2\nresult = calc(42)")
```

**Free-threaded Python (PEP 703, --disable-gil):**

```python
# Python 3.13t — the GIL is optional!
# Build: configure --disable-gil
# Runtime: PYTHON_GIL=0 python my_script.py

# Now threading actually parallelizes CPU-bound work:
import threading
import time

def cpu_heavy(n: int) -> int:
    result = 0
    for i in range(n):
        result += i ** 2
    return result

# With GIL: ~same time as sequential
# Without GIL: Nx speedup on N cores

threads = [
    threading.Thread(target=cpu_heavy, args=(10_000_000,))
    for _ in range(os.cpu_count())
]

start = time.perf_counter()
for t in threads: t.start()
for t in threads: t.join()
elapsed = time.perf_counter() - start

print(f"With {os.cpu_count()} threads: {elapsed:.2f}s")
```

**Critical consideration — thread safety without GIL:**

```python
# Without the GIL, ALL mutable objects need thread safety:
import threading

# List append is NO LONGER thread-safe!
shared_list = []
lock = threading.Lock()

def safe_append(item):
    with lock:
        shared_list.append(item)  # Now required!

# Dict operations are NO LONGER atomic
shared_dict = {}

def safe_update(key, value):
    with lock:
        shared_dict[key] = value  # Required without GIL
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Subinterpreters** | Understands isolated GILs, channel-based communication, limitations |
| **Free-threaded trade-offs** | Knows the ~5-8% single-threaded perf hit, thread-safety implications |
| **Production readiness** | Aware of C extension compatibility, GIL-dependent libraries (NumPy, etc.) |

---

## Question 12: Production Patterns — Dependency Injection, Configuration, and Plugin Architectures

**Interviewer:** *"Design a production service framework in Python that supports dependency injection, configuration management, and a plugin system. Make it testable and extensible."*

### 🎯 Expected Answer

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable, Any
from collections.abc import Callable, Awaitable
import os
import yaml
import json
from pathlib import Path
from dataclasses import dataclass, field
import inspect
import functools

# ═══════════════════════════════════════════════════════════
# 1. Configuration Management
# ═══════════════════════════════════════════════════════════

@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "app"
    username: str = "app"
    password: str = ""  # From secrets manager, not config
    max_connections: int = 10
    pool_timeout: int = 30

@dataclass
class ServiceConfig:
    name: str = "my-service"
    version: str = "1.0.0"
    debug: bool = False
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    @classmethod
    def load(cls, path: str | None = None) -> 'ServiceConfig':
        """Load config from file with environment variable overrides"""
        config_path = path or os.environ.get('CONFIG_PATH', 'config.yaml')
        
        if Path(config_path).exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}
        
        # Environment variable overrides (hierarchical)
        # DB_HOST=db-prod → config.database.host = "db-prod"
        for key, value in os.environ.items():
            if key.startswith('APP_'):
                parts = key[4:].lower().split('_')
                target = data
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value
        
        return cls(**data)

# ═══════════════════════════════════════════════════════════
# 2. Dependency Injection Container
# ═══════════════════════════════════════════════════════════

class ServiceLifecycle(Protocol):
    """Protocol for services that need startup/shutdown"""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

T = TypeVar('T')

class Container:
    """Dependency injection container with lazy resolution and lifecycle"""
    
    def __init__(self):
        self._services: dict[str, Callable[[], Any]] = {}
        self._instances: dict[str, Any] = {}
        self._singletons: set[str] = set()
        self._lifecycle: list[ServiceLifecycle] = []
    
    def register(
        self,
        name: str,
        factory: Callable[[], T],
        singleton: bool = True,
    ) -> None:
        """Register a service factory"""
        self._services[name] = factory
        if singleton:
            self._singletons.add(name)
    
    def resolve(self, name: str) -> Any:
        """Resolve a service (lazy initialization)"""
        if name in self._instances:
            return self._instances[name]
        
        if name not in self._services:
            raise KeyError(f"Service '{name}' not registered")
        
        instance = self._services[name]()
        if name in self._singletons:
            self._instances[name] = instance
        
        if isinstance(instance, ServiceLifecycle):
            self._lifecycle.append(instance)
        
        return instance
    
    async def start_all(self) -> None:
        """Start all lifecycle-aware services in dependency order"""
        for service in self._lifecycle:
            await service.start()
    
    async def stop_all(self) -> None:
        """Stop all services (reverse order)"""
        for service in reversed(self._lifecycle):
            await service.stop()

# ═══════════════════════════════════════════════════════════
# 3. Auto-Wiring Decorator
# ═══════════════════════════════════════════════════════════

class inject:
    """Decorator that auto-injects dependencies based on type hints"""
    
    _container: Container | None = None
    
    @classmethod
    def configure(cls, container: Container) -> None:
        cls._container = container
    
    def __init__(self, func: Callable) -> None:
        functools.update_wrapper(self, func)
        self.func = func
        self._sig = inspect.signature(func)
    
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._container is None:
            raise RuntimeError("Injector not configured")
        
        # Resolve parameters not provided
        bound = self._sig.bind_partial(*args, **kwargs)
        for name, param in self._sig.parameters.items():
            if name not in bound.arguments and param.annotation is not param.empty:
                # Map type to service name
                service_name = param.annotation.__name__.lower()
                kwargs[name] = self._container.resolve(service_name)
        
        return self.func(*args, **kwargs)

# ═══════════════════════════════════════════════════════════
# 4. Usage
# ═══════════════════════════════════════════════════════════

class DatabaseService:
    """Concrete service"""
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.pool = None
    
    async def start(self) -> None:
        self.pool = await create_pool(**self.config.__dict__)
        logger.info("Database connected")
    
    async def stop(self) -> None:
        if self.pool:
            await self.pool.close()
    
    async def query(self, sql: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(sql)

class UserService:
    def __init__(self, db: DatabaseService):
        self.db = db
    
    async def get_user(self, user_id: int) -> dict:
        results = await self.db.query(f"SELECT * FROM users WHERE id = {user_id}")
        return results[0] if results else None

# ── Wire it up ────────────────────────────────────────────
container = Container()
config = ServiceConfig.load()

container.register('databaseservice', lambda: DatabaseService(config.database))
container.register('userservice', lambda: UserService(container.resolve('databaseservice')))

inject.configure(container)

# ── Auto-wired handler ────────────────────────────────────
@inject
async def get_user_handler(request, userservice: UserService):
    user = await userservice.get_user(request.user_id)
    return {"data": user}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Framework design** | Doesn't just "use FastAPI DI" — designs the abstraction layer |
| **Lifecycle** | Handles startup/shutdown ordering, graceful degradation |
| **Testability** | Services can be mocked at container level |
| **Production reality** | Considers secrets management, config validation, env overrides |

---

## 📊 Staff-Level Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Cites CPython source code, references PEPs by number, has shipped production workarounds for GIL/memory issues. Discusses trade-offs without prompting. |
| **4 — Strong** | Deep understanding of internals. Knows the GIL switching mechanism, event loop phases, metaclass protocols. Can write C extensions. |
| **3 — Competent** | Good Pythonista. Knows async/await, context managers, type hints. But doesn't understand CPython internals or memory model deeply. |
| **2 — Developing** | Proficient with Python syntax but doesn't understand why things work. No production experience at scale. |
| **1 — Needs Growth** | Can write scripts but doesn't understand OOP in Python, concurrency models, or the runtime. |

---

> *Built for experienced Python engineers targeting Staff/Principal roles at top-tier companies*
