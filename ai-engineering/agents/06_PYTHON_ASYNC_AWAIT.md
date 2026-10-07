# ⚡ Python Async & Await — Concurrency for AI Agents

> **Target:** Staff/Principal Engineer | **Focus:** Async Python patterns for high-throughput agent systems | **Reviewed:** October 2026 (Python 3.11–3.14)

!!! tip "30-second answer"
    `asyncio` runs many I/O-bound tasks on **one thread** by switching at every `await`: while one task waits on an LLM or database, the event loop runs another. That fits agents, which spend most of their time waiting. The rules that matter in production: never block the loop (no `time.sleep`, sync HTTP or heavy CPU in a coroutine; offload with `asyncio.to_thread` or a process pool), bound concurrency with a semaphore, put deadlines on everything (`asyncio.timeout`), and use **structured concurrency** (`asyncio.TaskGroup`, 3.11+) so failures and cancellation propagate instead of leaking orphan tasks.

---

## 1. WHY ASYNC FOR AI AGENTS?

AI agent systems are **I/O-bound**, not CPU-bound. The agent spends most of its time:

- Waiting for LLM API responses (200ms–10s)
- Waiting for tool/API calls (50ms–5s)
- Waiting for database queries (1ms–500ms)
- Waiting for RAG retrieval (10ms–2s)

**Synchronous execution** wastes this waiting time. **Async execution** allows the agent to work on other tasks while waiting.

```python
# ❌ Synchronous — blocks on every I/O
def handle_user_sync(user_id, query):
    user = get_user_sync(user_id)          # Block 50ms
    context = search_kb_sync(query)        # Block 200ms  
    response = call_llm_sync(context)       # Block 2s
    return send_response_sync(response)     # Block 10ms
# Total: ~2.26s — CPU idle 99% of the time

# ✅ Asynchronous — non-blocking I/O
async def handle_user_async(user_id, query):
    user_task = get_user_async(user_id)    # Start
    context_task = search_kb_async(query)   # Both in parallel
    user, context = await asyncio.gather(user_task, context_task)
    
    response = await call_llm_async(context)  # Still must wait
    return await send_response_async(response)
# Total: ~2.01s — 250ms saved via parallel user+KB lookup
```

---

## 2. CORE CONCEPTS

### 2.1 The `async def` Keyword

Defines a **coroutine** — a function that can be paused and resumed:

```python
async def fetch_weather(city: str) -> dict:
    """This is a coroutine. It doesn't run when called — it returns a coroutine object."""
    data = await make_api_call(f"/weather/{city}")
    return data

# Calling it:
coro = fetch_weather("Tokyo")  # Returns a coroutine object, NOT the result
# To run it, you need an event loop:
result = await coro  # Inside another async function
# or
result = asyncio.run(fetch_weather("Tokyo"))  # Top-level entry point
```

### 2.2 The `await` Keyword

Pauses the current coroutine until the awaited coroutine completes:

```python
async def process():
    # Without await: returns a coroutine object (WRONG)
    coro = fetch_weather("Tokyo")  #  <coroutine object fetch_weather at 0x...>
    
    # With await: returns the actual result (CORRECT)
    result = await fetch_weather("Tokyo")  #  {"temp": 22, "condition": "cloudy"}
```

**What `await` does:**
1. Suspends execution of the current coroutine
2. Gives control back to the event loop
3. Event loop can run other tasks while waiting
4. When the awaited coroutine completes, the event loop resumes the current coroutine

### 2.3 The Event Loop

The event loop is the **scheduler** that manages all async tasks:

```
Time ────────────────────────────────────────────────────────→

Task A: |──fetch_weather──|  |──parse_result──|  |──save──|
Task B:                    |──fetch_weather──|  |──parse──|
Task C:                                        |──fetch──|

Without Async:
Task A: |──fetch──|──parse──|──save──|
Task B:                              |──fetch──|──parse──|
Task C:                                        |──fetch──|
Total: ~9 time units

With Async (I/O overlap):
Task A: |──fetch──|──parse──|──save──|
Task B:    |──fetch──|──parse──|
Task C:                |──fetch──|
Total: ~5 time units — I/O wait is overlapped!
```

---

## 3. PRACTICAL PATTERNS FOR AGENT SYSTEMS

### 3.1 Parallel LLM Calls

```python
import asyncio
import os
from openai import AsyncOpenAI

client = AsyncOpenAI()
MODEL = os.environ["LLM_MODEL"]            # model ids change; keep them in config
llm_slots = asyncio.Semaphore(8)           # bound concurrency: provider rate limits are finite

async def call_llm_parallel(prompts: list[str]) -> list[str]:
    """Call multiple LLM prompts in parallel."""
    async def single_call(prompt: str) -> str:
        async with llm_slots:
            response = await client.responses.create(model=MODEL, input=prompt)
            return response.output_text
    
    # All calls run concurrently (up to the semaphore limit)
    tasks = [single_call(p) for p in prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle any failures
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append(f"[Error on prompt {i}]: {result}")
        else:
            processed.append(result)
    
    return processed

# Usage
results = await call_llm_parallel([
    "Summarize this document",
    "Extract key entities",
    "Classify sentiment",
])
# All 3 calls run concurrently — ~2s instead of ~6s
```

`gather(..., return_exceptions=True)` gives partial results when some calls fail. If any failure should abort the rest, use a `TaskGroup` instead (3.6).

### 3.2 Async Agent Loop with Timeout

```python
async def run_agent_with_timeout(
    agent_fn, query: str, timeout: float = 30.0
) -> str:
    """Run an agent with a deadline — prevents runaway agents."""
    try:
        async with asyncio.timeout(timeout):      # 3.11+; wait_for() also works
            return await agent_fn(query)
    except TimeoutError:                          # asyncio.TimeoutError is an alias since 3.11
        # The agent coroutine has been CANCELLED, not paused: any work it did
        # is lost unless it checkpoints. Return a clear failure, not a fake answer.
        return f"Agent did not complete within {timeout}s"

# ─── Usage ────────────────────────────────────────
async def my_agent(query: str) -> str:
    """Agent might take 2s or 60s depending on complexity."""
    await asyncio.sleep(2)  # Simulate work
    return f"Result for: {query}"

result = await run_agent_with_timeout(my_agent, "Hello", timeout=5.0)
```

Timeouts work by cancellation: `CancelledError` is raised at the coroutine's current `await`. Code that catches it must clean up and **re-raise**; swallowing it breaks timeouts and shutdown. Timeouts also only fire at an `await`, so a coroutine stuck in blocking code can't be timed out.

### 3.3 Async Generator for Streaming Agent Outputs

```python
import json

def sse(event: dict) -> str:
    # Server-Sent Events wire format: "data: <payload>\n\n"
    return f"data: {json.dumps(event)}\n\n"

async def stream_agent_events(query: str):
    """Stream agent thoughts and actions as they happen."""
    agent = Agent()
    
    # Yield initial acknowledgment
    yield {"type": "status", "content": "Processing..."}
    
    async for step in agent.run(query):
        if step["type"] == "thought":
            yield {"type": "thought", "content": step["content"]}
        elif step["type"] == "tool_call":
            yield {"type": "action", "content": f"🔧 Calling {step['tool']}({step['params']})"}
        elif step["type"] == "tool_result":
            yield {"type": "observation", "content": f"Result: {step['result'][:100]}..."}
        elif step["type"] == "error":
            yield {"type": "error", "content": f"❌ {step['error']}"}
    
    yield {"type": "done", "content": "✅ Complete"}

# FastAPI endpoint
@app.get("/chat")
async def chat(query: str):
    async def body():
        async for event in stream_agent_events(query):
            yield sse(event)           # StreamingResponse needs str/bytes, not dicts
    return StreamingResponse(body(), media_type="text/event-stream")
```

When the client disconnects, the server cancels the generator at its current `await`; make sure that also cancels the in-flight model call (or the run keeps burning tokens), and send periodic heartbeat comments so proxies and load balancers don't cut idle streams.

### 3.4 Async Rate Limiting

```python
import asyncio
from time import monotonic as time   # monotonic: immune to wall-clock jumps

class AsyncRateLimiter:
    """Token-bucket rate limiter for async contexts."""
    
    def __init__(self, rate: float = 10, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_refill = time()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """Acquire a token. Returns True if allowed."""
        async with self._lock:
            now = time()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.burst,
                self.tokens + elapsed * self.rate
            )
            self.last_refill = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False
    
    async def wait_and_acquire(self):
        """Wait until a token is available."""
        while not await self.acquire():
            await asyncio.sleep(1 / self.rate)
    
    async def __aenter__(self):
        await self.wait_and_acquire()
        return self
    
    async def __aexit__(self, *args):
        pass

# Usage
rate_limiter = AsyncRateLimiter(rate=10, burst=20)

async def call_api(data: dict) -> dict:
    async with rate_limiter:
        return await http_client.post("/api/endpoint", json=data)
```

### 3.5 Circuit Breaker Pattern (Async)

```python
class AsyncCircuitBreaker:
    """Circuit breaker for async API calls."""
    
    def __init__(self, failure_threshold: int = 5, 
                 recovery_timeout: float = 30.0):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"  # closed, open, half-open
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()
    
    async def call(self, coro_factory):
        """Execute a coroutine with circuit breaking.

        Simplification: in half-open state every caller gets through; a real
        breaker lets one (or a few) trial calls through and fails the rest fast.
        Count only failures that indicate an unhealthy dependency (timeouts,
        5xx, 429), not caller errors like 400s.
        """
        async with self._lock:
            if self.state == "open":
                if time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half-open"
                else:
                    raise CircuitBreakerOpen("Circuit breaker is open")
        
        try:
            result = await coro_factory()
            
            async with self._lock:
                if self.state == "half-open":
                    self.state = "closed"
                    self.failure_count = 0
                else:
                    self.failure_count = 0
            
            return result
        
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time()
                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
            
            raise
```

### 3.6 Structured Concurrency with TaskGroup (3.11+)

```python
async def gather_context(query: str) -> dict:
    async with asyncio.TaskGroup() as tg:
        user = tg.create_task(get_user(query))
        docs = tg.create_task(search_kb(query))
        hist = tg.create_task(load_history(query))
    # Leaving the block means ALL tasks finished. If any task raised, the
    # others were cancelled and the errors are raised together as an
    # ExceptionGroup (handle with `except* SomeError:`).
    return {"user": user.result(), "docs": docs.result(), "history": hist.result()}
```

| | `asyncio.gather` | `asyncio.TaskGroup` |
|---|---|---|
| One task fails | Other tasks **keep running** (default) | Other tasks are **cancelled** |
| Error reporting | First exception, or all results with `return_exceptions=True` | All exceptions in an `ExceptionGroup` |
| Leaked tasks | Possible | Impossible: the block waits for every task |
| Use when | You want partial results | All-or-nothing work, clean cancellation |

---

## 4. ASYNC VS THREADING VS MULTIPROCESSING

| Feature | Async (`asyncio`) | Threading (`threading`) | Multiprocessing (`multiprocessing`) |
|---------|-------------------|------------------------|------------------------------------|
| **Concurrency model** | Cooperative (single-threaded) | Preemptive (OS threads) | Parallel (separate processes) |
| **Best for** | I/O-bound tasks | I/O-bound + blocking calls | CPU-bound tasks |
| **Memory** | Low (single process) | Medium (shared memory) | High (separate memory) |
| **GIL limitation** | One thread, so no CPU parallelism | No CPU parallelism on the default build (see note) | Not affected |
| **Overhead** | Very low | Moderate | High |
| **Race conditions** | Fewer (single-thread) | Common (shared state) | Fewer (separate memory) |
| **Example use** | 1000 concurrent API calls | 10 blocking I/O threads | 4 CPU cores for ML inference |

**GIL note (3.13+):** CPython now ships an optional **free-threaded** build (PEP 703; experimental in 3.13, officially supported but still not the default in 3.14) where threads can run Python code in parallel. The default build still has the GIL, and many C extensions need to opt in, so treat it as something to evaluate, not assume.

### When to Use Each in Agent Systems:

```python
# ✅ Async: Default choice for agent systems
async def agent_handler(request):
    user_data = await db.get_user(request.user_id)
    context = await rag.retrieve(request.query)
    response = await llm.generate(context, user_data)
    return response

# ✅ Threading: When you must use blocking (I/O) libraries
async def run_blocking_code():
    # 3.9+: runs in the loop's default ThreadPoolExecutor
    return await asyncio.to_thread(blocking_io_function, arg1, arg2)

# ✅ Multiprocessing: For CPU-bound agent tasks (parsing, embeddings on CPU)
from concurrent.futures import ProcessPoolExecutor

process_pool = ProcessPoolExecutor(max_workers=4)   # create once, reuse

async def process_batch(items: list) -> list:
    loop = asyncio.get_running_loop()               # not get_event_loop() inside a coroutine
    # Note: run_in_executor(None, ...) uses a THREAD pool, not a process pool.
    return await loop.run_in_executor(
        process_pool, cpu_intensive_batch, items   # function and args must be picklable
    )
```

---

## 5. COMMON PITFALLS

### 5.1 Blocking the Event Loop

```python
# ❌ BAD: Blocks the event loop for 2 seconds
async def bad_agent():
    import time
    time.sleep(2)  # Blocks ALL other async tasks!
    return "result"

# ✅ GOOD: Non-blocking sleep
async def good_agent():
    await asyncio.sleep(2)  # Yields control — other tasks run
    return "result"
```

### 5.2 Forgetting to Await

```python
# ❌ BAD: Returns coroutine instead of result
async def bad():
    result = fetch_data()  # Forgot await!
    return result  # Returns coroutine object, not data!

# ✅ GOOD: Awaits the coroutine
async def good():
    result = await fetch_data()
    return result  # Returns actual data
```

### 5.3 Mixing Sync and Async Incorrectly

```python
# ❌ BAD: Calling async function from sync code without event loop
def sync_function():
    result = async_function()  # Returns coroutine, not result!
    # ❌ Can't use await here

# ✅ GOOD: Use asyncio.run() at the boundary
def sync_function():
    result = asyncio.run(async_function())  # Works correctly
    return result

# ✅ BETTER: Make the whole call chain async if possible
async def better_sync_function():
    return await async_function()
```

### 5.4 Fire-and-Forget Without Tracking

```python
# ❌ BAD: Fire and forget — exception is lost
async def bad():
    asyncio.create_task(some_work())  # If it fails, nobody knows

# ✅ GOOD: Keep a strong reference AND surface failures
class TaskTracker:
    def __init__(self):
        self.tasks = set()
    
    def create_tracked_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)          # the loop only holds a WEAK ref: an
                                      # unreferenced task can be garbage-collected mid-run
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("background task failed", exc_info=task.exception())

tracker = TaskTracker()

async def good():
    tracker.create_tracked_task(some_work())  # Tracked and logged
```

Better still, when the work belongs to a request, run it inside a `TaskGroup` so it can't outlive its parent.

### 5.5 Unbounded Fan-out

`gather(*[call(x) for x in ten_thousand_items])` starts everything at once: you hit provider 429s, exhaust connection pools and memory. Bound it with a `Semaphore` (as in 3.1) or a fixed pool of worker tasks reading from an `asyncio.Queue`.

---

## 6. PERFORMANCE TUNING

```python
import asyncio

class AsyncAgentTuner:
    """Tune async agent performance."""
    
    @staticmethod
    def optimal_concurrency(test_fn, min_concurrent=1, max_concurrent=100):
        """Find optimal concurrency level for your API calls."""
        import time
        
        results = []
        for n in range(min_concurrent, max_concurrent, 10):
            sem = asyncio.Semaphore(n)
            
            async def limited_call():
                async with sem:
                    start = time.perf_counter()
                    await test_fn()
                    return time.perf_counter() - start
            
            async def run_batch():
                tasks = [limited_call() for _ in range(100)]
                return await asyncio.gather(*tasks)
            
            wall_start = time.perf_counter()
            latencies = asyncio.run(run_batch())
            wall = time.perf_counter() - wall_start
            throughput = len(latencies) / wall          # completed calls per second of WALL time
            avg_latency = sum(latencies) / len(latencies)
            results.append((n, throughput, avg_latency))
        
        # Throughput rises with concurrency until the provider or pool
        # saturates; past that point latency climbs and 429s appear.
        return results  # Plot to find the elbow
    
    @staticmethod
    def connection_pool_size(max_connections: int = 100):
        """Configure optimal connection pool for HTTP clients."""
        import aiohttp
        
        connector = aiohttp.TCPConnector(
            limit=max_connections,
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True
        )
        return connector
```

---

## 7. TESTING ASYNC CODE

```python
import pytest

@pytest.mark.asyncio
async def test_calls_run_concurrently(monkeypatch):
    """Concurrency test with a FAKE client: deterministic, no network."""
    class FakeResponses:
        async def create(self, **kwargs):
            await asyncio.sleep(0.2)                 # pretend LLM latency
            return type("R", (), {"output_text": "ok"})()
    monkeypatch.setattr(client, "responses", FakeResponses())

    loop = asyncio.get_running_loop()
    start = loop.time()
    results = await call_llm_parallel(["a", "b", "c", "d"])
    duration = loop.time() - start

    assert results == ["ok"] * 4
    assert duration < 0.5  # ~1x latency (0.2s), not 4x (0.8s)

@pytest.mark.asyncio
async def test_rate_limiter():
    """Test that rate limiter respects limits."""
    limiter = AsyncRateLimiter(rate=100, burst=10)
    calls = []
    
    async def limited_call(i):
        await limiter.wait_and_acquire()
        calls.append(i)
    
    # Fire 20 calls quickly
    tasks = [limited_call(i) for i in range(20)]
    await asyncio.gather(*tasks)
    
    # First 10 should be immediate, rest should be delayed
    assert len(calls) == 20
```

With pytest-asyncio, set `asyncio_mode = "auto"` in config to drop the per-test marker. For timing-sensitive tests, prefer fake clocks or loose bounds; CI machines are noisy.

---

## 8. NESTED ASYNC FUNCTIONS — Async Inside Async (Deep Dive)

One of the most common questions about async Python is: **"How do nested async functions work? What happens technically when I `await` inside an `async def` that's already inside another `async def`?"**

Let's trace the exact execution path.

### 8.1 The Stack of Coroutines

```python
async def inner():
    # Level 3
    await asyncio.sleep(0.1)
    return "inner done"

async def middle():
    # Level 2
    result = await inner()  # <--- Nested await!
    return f"middle got: {result}"

async def outer():
    # Level 1
    result = await middle()  # <--- Another nested await!
    return f"outer got: {result}"

# Entry point
final = asyncio.run(outer())
print(final)  # "outer got: middle got: inner done"
```

### 8.2 What Happens Step-by-Step (The Exact Execution Trace)

```ascii
Time ────────────────────────────────────────────────────────────────►

asyncio.run(outer())
  │
  ├── 1. Creates a NEW event loop (raises if called from a running loop)
  ├── 2. Wraps outer() in a Task (the only Task in this example)
  └── 3. Runs the event loop
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  TASK: outer() entered                                           │
│                                                                  │
│  ── Line: result = await middle() ──                             │
│                                                                  │
│  4. outer() creates middle() coroutine object                   │
│  5. outer() calls middle().__await__() — THIS IS KEY            │
│  6. middle() starts executing                                   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  COROUTINE (same Task): middle() entered                   │  │
│  │                                                            │  │
│  │  ── Line: result = await inner() ──                       │  │
│  │                                                            │  │
│  │  7. middle() creates inner() coroutine object              │  │
│  │  8. middle() calls inner().__await__()                     │  │
│  │  9. inner() starts executing                               │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │  COROUTINE (same Task): inner() entered            │    │  │
│  │  │                                                    │    │  │
│  │  │  ── Line: await asyncio.sleep(0.1) ──            │    │  │
│  │  │                                                    │    │  │
│  │  │  10. inner() calls asyncio.sleep(0.1)              │    │  │
│  │  │  11. sleep() creates a Future that will be         │    │  │
│  │  │      resolved in 100ms                            │    │  │
│  │  │  12. inner() awaits the Future → SUSPENDS          │    │  │
│  │  │  13. Control returns to middle()'s await          │    │  │
│  │  │      → middle() also SUSPENDS                      │    │  │
│  │  │  14. Control returns to outer()'s await           │    │  │
│  │  │      → outer() also SUSPENDS                      │    │  │
│  │  │  15. Control returns to the EVENT LOOP            │    │  │
│  │  │                                                    │    │  │
│  │  │  ── Event loop runs OTHER tasks for 100ms ──     │    │  │
│  │  │                                                    │    │  │
│  │  │  16. After 100ms, the Future is resolved           │    │  │
│  │  │  17. Loop resumes the Task: outer→middle→inner     │    │  │
│  │  │  18. inner() resumes, gets None from sleep()       │    │  │
│  │  │  19. inner() returns "inner done"                 │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  20. middle()'s await resumes with "inner done"           │  │
│  │  21. middle() continues: f"middle got: inner done"        │  │
│  │  22. middle() returns the string                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  23. outer()'s await resumes with the string                    │
│  24. outer() continues: f"outer got: middle got: inner done"    │
│  25. outer() returns the final result                           │
└──────────────────────────────────────────────────────────────────┘
```

### 8.3 The Call Stack (How It Really Works)

A plain `await other_coro()` does **not** create a new task. The awaiting coroutine delegates to the awaited one (like `yield from`), so the whole chain `outer → middle → inner` runs inside **one Task**. When `inner` hits a real suspension point (a Future that isn't done), the Future is passed *up* through every frame to the Task, which hands control back to the event loop.

```ascii
Event loop
   │  task.step()  (resumes the Task)
   ▼
Task(outer)
   │  outer frame ── send() ──► middle frame ── send() ──► inner frame
   │                                                          │
   │                         awaits sleep() Future (not done) │
   ◄──────────── Future bubbles back up through each frame ───┘
   │
   ▼  Task registers a callback on the Future, returns to the loop
Event loop runs other Tasks; when the Future completes, it resumes Task(outer),
which re-enters outer → middle → inner and continues after the await.
```

While **suspended**, the coroutine frames live on the heap and hold no thread stack, which is why 10,000 concurrent idle tasks are cheap. But while **running**, a deep `await` chain is resumed frame by frame, and each level counts toward Python's recursion limit, exactly like normal calls.

### 8.4 The Technical Mechanism: Generators + Yield

`async`/`await` is built on the same machinery as generators. `await x` calls `x.__await__()` and delegates to that iterator, roughly like `yield from`. Only the innermost object, an `asyncio.Future`, actually *yields*, which suspends the whole chain:

```python
# Conceptually (not literally what CPython emits):
async def my_coro():
    result = await other_coro()
    return result

# behaves like a generator-based coroutine:
def my_coro_gen():
    result = yield from other_coro().__await__()   # delegate until it returns
    return result

# And asyncio.Future.__await__ is, in essence:
def __await__(self):
    if not self.done():
        yield self            # hand the Future to the Task / event loop
    return self.result()      # resumed after the loop marks it done
```

### 8.5 The Event Loop's Perspective

```python
# Simplified event loop: what asyncio's BaseEventLoop does, minus details
class EventLoop:
    def __init__(self):
        self._ready = collections.deque()   # callbacks ready to run now
        self._scheduled = []                # heap of (when, callback) timers

    def run_forever(self):
        while True:
            timeout = self._time_until_next_timer()  # 0 if _ready is non-empty
            events = self._selector.select(timeout)  # epoll/kqueue: wait for I/O
            self._process_io_events(events)          # their callbacks -> _ready
            self._move_due_timers_to_ready()
            for _ in range(len(self._ready)):
                callback = self._ready.popleft()
                callback()        # usually Task.__step: resume a coroutine
                                  # until its next suspension point
```

A `Task` is the bridge: its `__step` resumes the coroutine with `send()`; when the coroutine yields a Future, the Task adds `add_done_callback(self.__wakeup)` and returns. When the Future completes, the wake-up callback is put on `_ready`. Nothing runs in parallel; everything is "run until the next await".

### 8.6 What This Means for Deeply Nested Async

```python
async def very_deep(n: int):
    if n == 0:
        await asyncio.sleep(0)
        return "base"
    return await very_deep(n - 1)   # recursive await, all in ONE task

asyncio.run(very_deep(900))    # fine
asyncio.run(very_deep(5000))   # RecursionError (default limit 1000), same as sync recursion
```

Measured on CPython 3.14: `very_deep(900)` succeeds and `very_deep(1100)` raises `RecursionError`, matching a plain recursive function. Recursive `await` is **not** a way around the recursion limit. If you genuinely need deep recursion, convert it to iteration, or break the chain by running sub-steps as separate tasks.

| Property | Sync call chain | `await` chain (one Task) | Separate Tasks |
|----------|-----------------|--------------------------|----------------|
| Counts toward recursion limit | Yes | Yes, while running | No (each task starts a fresh chain) |
| Can be suspended mid-chain | No | Yes, at any `await` | Yes |
| Memory while idle | Thread stack held | Heap frames only | Heap frames + Task object |
| Runs concurrently with siblings | No | No | Yes |

### 8.7 Nested Async in Agent Systems

```python
# Real-world example: an agent with deeply nested async calls

class AIAgent:
    async def handle_request(self, query: str) -> str:
        """Entry point — called by the API server."""
        context = await self._gather_context(query)
        plan = await self._make_plan(context)
        result = await self._execute_plan(plan)
        return await self._format_response(result)
    
    async def _gather_context(self, query: str) -> dict:
        """Collect all context needed — runs sub-tasks in parallel."""
        user_task = self._get_user_context(query)
        kb_task = self._search_knowledge_base(query)
        hist_task = self._get_conversation_history(query)
        
        # Nested await + gather = 3 levels of async nesting
        user, kb, hist = await asyncio.gather(
            user_task, kb_task, hist_task
        )
        
        return {"user": user, "kb": kb, "history": hist}
    
    async def _get_user_context(self, query: str) -> dict:
        """Fetch user data — another nested call."""
        user_id = await self._extract_user_id(query)
        
        # Even deeper nesting with parallel calls
        profile, prefs, perms = await asyncio.gather(
            self._db.get_user_profile(user_id),
            self._db.get_user_preferences(user_id),
            self._auth.get_permissions(user_id),
        )
        
        return {"profile": profile, "prefs": prefs, "perms": perms}
```

**Nesting depth in this example:** `handle_request` → `_gather_context` → `_get_user_context` → `_db.get_user_profile` → (some DB driver's async call) → (socket I/O). That's about 6 levels of nested `await`, trivially within limits. Note where the concurrency actually comes from: the two `gather` calls each create Tasks; the plain nested awaits just run inside their parent's Task.

### 8.8 Performance Characteristics of Nested Async

Rough numbers measured on CPython 3.14 on a laptop (order of magnitude only; measure on your own hardware):

| Operation | Approximate cost |
|-----------|------------------|
| `await` of a coroutine that returns immediately | tens of nanoseconds |
| Creating and running a Task (via `gather`) | about a microsecond |
| Size of a coroutine object (`sys.getsizeof`) | ~200 bytes, plus its frame |

Compared with a 1–30 s LLM call, async overhead is noise. What actually hurts agent latency is accidental serialization (awaiting in a loop when calls are independent), blocking calls on the loop, and unbounded fan-out hitting rate limits.

### 8.9 Common Nested Async Patterns

```python
# Pattern 1: Sequential (natural await chain)
async def sequential():
    a = await step1()
    b = await step2(a)    # Depends on step1
    c = await step3(b)    # Depends on step2
    return c

# Pattern 2: Parallel within sequential (gather inside nested)
async def parallel_nested():
    # Step 1: do A and B in parallel
    a, b = await asyncio.gather(get_a(), get_b())
    
    # Step 2: use results in parallel calls
    results = await asyncio.gather(
        process_a(a),
        process_b(b),
        compute_derived(a, b)  # Depends on both
    )
    return results

# Pattern 3: Dynamic nesting (loop with awaits)
async def dynamic_nesting(items: list):
    """Process N items with varying numbers of steps per item."""
    async def process_one(item):
        # Each item might need different steps
        if item.type == "simple":
            return await quick_process(item)
        elif item.type == "complex":
            data = await fetch_details(item)
            return await analyze(data)
        else:
            return await default_process(item)
    
    # Process all items concurrently
    return await asyncio.gather(*[
        process_one(item) for item in items
    ])

# Pattern 4: Cancellation propagation
async def cancellable_deep():
    """When cancelled, all nested awaits also get cancelled."""
    try:
        result = await asyncio.wait_for(
            deep_operation(),
            timeout=5.0
        )
        return result
    except asyncio.TimeoutError:
        # deep_operation was cancelled → all its nested awaits cancelled too
        return "Timed out"
```

### 8.10 Key Takeaways for Nested Async

| Takeaway | Why It Matters |
|----------|---------------|
| **A nested `await` is not a new task** | The chain runs inside one Task; only `create_task`, `gather` and `TaskGroup` create concurrency |
| **Deep `await` recursion still hits the recursion limit** | Frames are resumed one inside another while running |
| **Idle coroutines are cheap** | Suspended frames sit on the heap; thousands of waiting tasks are fine |
| **Each `await` on an unfinished Future is a suspension point** | The event loop can interleave other work only there |
| **Cancellation propagates down the chain** | Cancelling the Task raises `CancelledError` at the innermost `await` |
| **Exceptions propagate up naturally** | try/except around the outer await catches inner exceptions |
| **Overhead is negligible next to I/O** | Nanoseconds per await vs seconds per LLM call |

### 8.11 What Interviewers Probe Next

- **"How do you find what's blocking the loop?"** Enable debug mode (`PYTHONASYNCIODEBUG=1` or `asyncio.run(..., debug=True)`), which logs callbacks slower than `loop.slow_callback_duration` (100 ms by default). Python 3.14 adds `python -m asyncio ps <PID>` / `pstree <PID>` to inspect running tasks of a live process.
- **"How do you shut down cleanly?"** On SIGTERM stop accepting work, cancel or drain in-flight tasks with a deadline, and make sure handlers re-raise `CancelledError`.
- **"Why is my async service slow at 100 concurrent requests?"** Usually a sync client hiding in the path (`requests`, a sync DB driver, a CPU-heavy JSON parse), or a connection pool smaller than your concurrency.

---

## 9. QUICK REFERENCE

```python
# ─── Key Functions ─────────────────────────────────

asyncio.run(main())                           # Run async from sync (creates a new loop)
await coroutine                                # Wait for result (same task)
asyncio.create_task(coro)                      # Run concurrently (keep a reference!)
async with asyncio.TaskGroup() as tg: ...      # Structured concurrency (3.11+)
asyncio.gather(*tasks, return_exceptions=True) # Parallel execution, partial results
async with asyncio.timeout(10): ...            # Deadline (3.11+)
asyncio.wait_for(coro, timeout=10.0)          # Deadline (older style)
asyncio.shield(coro)                           # Protect inner work from outer cancellation
asyncio.to_thread(blocking_fn, *args)          # Offload blocking I/O (3.9+)
asyncio.get_running_loop()                     # Inside coroutines (not get_event_loop())
asyncio.sleep(0.1)                            # Non-blocking sleep

# ─── Async Context Managers ───────────────────────

async with aiohttp.ClientSession() as session:  # Async context manager
    async with session.get(url) as response:    # Nested async ctx
        data = await response.json()

# ─── Async Iterators ──────────────────────────────

async for chunk in stream_response():           # Streaming
    process(chunk)

# ─── Async Queues ─────────────────────────────────

queue = asyncio.Queue(maxsize=100)
await queue.put(item)                           # Producer
item = await queue.get()                        # Consumer

# ─── Synchronization ──────────────────────────────

lock = asyncio.Lock()
sem = asyncio.Semaphore(10)  # Max 10 concurrent
event = asyncio.Event()
```

---

> **Next:** [Agent Observability](07_AGENT_OBSERVABILITY.md) → Debugging, monitoring, and production observability for agent systems
