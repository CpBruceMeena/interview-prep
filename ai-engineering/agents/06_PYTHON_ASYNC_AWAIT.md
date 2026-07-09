# ⚡ Python Async & Await — Concurrency for AI Agents

> **Target:** Staff/Principal Engineer | **Focus:** Async Python patterns for high-throughput agent systems

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
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def call_llm_parallel(prompts: list[str]) -> list[str]:
    """Call multiple LLM prompts in parallel."""
    async def single_call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content
    
    # All calls run concurrently
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

### 3.2 Async Agent Loop with Timeout

```python
async def run_agent_with_timeout(
    agent_fn, query: str, timeout: float = 30.0
) -> str:
    """Run an agent with a deadline — prevents runaway agents."""
    try:
        result = await asyncio.wait_for(
            agent_fn(query),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        return f"Agent did not complete within {timeout}s — response truncated"

# ─── Usage ────────────────────────────────────────
async def my_agent(query: str) -> str:
    """Agent might take 2s or 60s depending on complexity."""
    await asyncio.sleep(2)  # Simulate work
    return f"Result for: {query}"

result = await run_agent_with_timeout(my_agent, "Hello", timeout=5.0)
```

### 3.3 Async Generator for Streaming Agent Outputs

```python
async def stream_agent_response(query: str):
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
    return StreamingResponse(
        stream_agent_response(query),
        media_type="text/event-stream"
    )
```

### 3.4 Async Rate Limiting

```python
import asyncio
from dataclasses import dataclass
from time import time

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
        """Execute a coroutine with circuit breaking."""
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
            
            raise e
```

---

## 4. ASYNC VS THREADING VS MULTIPROCESSING

| Feature | Async (`asyncio`) | Threading (`threading`) | Multiprocessing (`multiprocessing`) |
|---------|-------------------|------------------------|------------------------------------|
| **Concurrency model** | Cooperative (single-threaded) | Preemptive (OS threads) | Parallel (separate processes) |
| **Best for** | I/O-bound tasks | I/O-bound + blocking calls | CPU-bound tasks |
| **Memory** | Low (single process) | Medium (shared memory) | High (separate memory) |
| **GIL limitation** | Not affected | Affected (CPU-bound) | Not affected |
| **Overhead** | Very low | Moderate | High |
| **Race conditions** | Fewer (single-thread) | Common (shared state) | Fewer (separate memory) |
| **Example use** | 1000 concurrent API calls | 10 blocking I/O threads | 4 CPU cores for ML inference |

### When to Use Each in Agent Systems:

```python
# ✅ Async: Default choice for agent systems
async def agent_handler(request):
    user_data = await db.get_user(request.user_id)
    context = await rag.retrieve(request.query)
    response = await llm.generate(context, user_data)
    return response

# ✅ Threading: When you must use blocking libraries
from concurrent.futures import ThreadPoolExecutor

async def run_blocking_code():
    with ThreadPoolExecutor() as pool:
        result = await asyncio.get_event_loop().run_in_executor(
            pool,
            blocking_function,  # e.g., CPU-intensive parsing
            arg1, arg2
        )
    return result

# ✅ Multiprocessing: For CPU-bound agent tasks
from multiprocessing import Pool

class BatchProcessor:
    def __init__(self):
        self.pool = Pool(processes=4)
    
    async def process_batch(self, items: list) -> list:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,  # Uses default ProcessPoolExecutor
            self.pool.map,
            cpu_intensive_task,
            items
        )
        return results
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

# ✅ GOOD: Track tasks
class TaskTracker:
    def __init__(self):
        self.tasks = set()
    
    def create_tracked_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

tracker = TaskTracker()

async def good():
    tracker.create_tracked_task(some_work())  # Tracked and logged
```

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
                    start = time.time()
                    await test_fn()
                    return time.time() - start
            
            async def run_batch():
                tasks = [limited_call() for _ in range(100)]
                return await asyncio.gather(*tasks)
            
            latencies = asyncio.run(run_batch())
            throughput = len(latencies) / sum(latencies)
            avg_latency = sum(latencies) / len(latencies)
            results.append((n, throughput, avg_latency))
        
        # Find elbow point
        return results  # Plot to find optimal concurrency
    
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
async def test_parallel_llm_calls():
    """Test that parallel LLM calls complete within expected time."""
    start = asyncio.get_event_loop().time()
    
    results = await call_llm_parallel([
        "Say 'hello'",
        "Say 'world'",
        "Say 'foo'",
        "Say 'bar'",
    ])
    
    duration = asyncio.get_event_loop().time() - start
    
    assert len(results) == 4
    assert duration < 5.0  # Should be ~1x latency, not 4x

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
  ├── 1. Creates a new event loop (if none exists)
  ├── 2. Creates a Task for outer()
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
│  │  SUB-TASK: middle() entered                                │  │
│  │                                                            │  │
│  │  ── Line: result = await inner() ──                       │  │
│  │                                                            │  │
│  │  7. middle() creates inner() coroutine object              │  │
│  │  8. middle() calls inner().__await__()                     │  │
│  │  9. inner() starts executing                               │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │  SUB-SUB-TASK: inner() entered                     │    │  │
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
│  │  │  17. Event loop schedules inner() to resume        │    │  │
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

```ascii
NORMAL FUNCTION CALLS:                      ASYNC AWAIT CHAIN:
(Real stack frames, one per call)          (Coroutine objects, not stack frames)

┌─────────────┐                            ┌─────────────────┐
│  main()     │                            │  Event Loop     │
│  calls a()  │                            │  (single thread)│
├─────────────┤                            └────────┬────────┘
│  a()        │                                     │
│  calls b()  │                            ┌────────▼────────┐
├─────────────┤                            │  Task for       │
│  b()        │                            │  outer()        │
│  calls c()  │                            │                 │
├─────────────┤                            │  → awaits       │
│  c()        │                            │    middle()     │
│  does work  │                            └────────┬────────┘
├─────────────┤                                     │
│  returns    │                            ┌────────▼────────┐
│  to b()     │                            │  Coroutine      │
├─────────────┤                            │  middle()       │
│  b()        │                            │                 │
│  returns    │                            │  → awaits       │
│  to a()     │                            │    inner()      │
├─────────────┤                            └────────┬────────┘
│  a()        │                                     │
│  returns    │                            ┌────────▼────────┐
│  to main()  │                            │  Coroutine      │
└─────────────┘                            │  inner()        │
                                           │                 │
Thread has a REAL stack.                   │  → awaits       │
Each frame uses actual memory.             │    sleep()      │
                                           └────────┬────────┘
                                                    │
                                           ┌────────▼────────┐
                                           │  Future         │
                                           │  (sleep 100ms)  │
                                           └─────────────────┘

The coroutines are Python objects on the heap,
NOT stack frames. They can be suspended and
resumed without consuming stack space.
```

### 8.4 The Technical Mechanism: Generators + Yield

Under the hood, `async`/`await` is implemented using **generators** with `yield`:

```python
# What you write:
async def my_coro():
    result = await other_coro()
    return result

# What Python roughly compiles it to:
@types.coroutine
def my_coro():
    result = yield from other_coro().__await__()
    return result

# What __await__ returns:
class Coroutine:
    def __await__(self):
        # This is what makes 'await' work!
        # It returns an iterator that the event loop drives
        return self._iterate()
    
    def _iterate(self):
        # This generator yields control at each await point
        try:
            while True:
                # Get the next future to wait on
                future = self._get_next_step()
                if future is None:
                    break
                # Yield the future to the event loop
                yield future
        except StopIteration as e:
            # Return the final value
            return e.value
```

### 8.5 The Event Loop's Perspective

```python
# Simplified event loop — this is what actually runs
class EventLoop:
    def __init__(self):
        self._ready = []       # Tasks ready to run
        self._waiting = {}      # Future → [tasks waiting on it]
    
    def run_until_complete(self, main_coro):
        # Wrap coroutine in a Task
        main_task = Task(main_coro, self)
        self._ready.append(main_task)
        
        while self._ready or self._waiting:
            # Run all ready tasks one step each
            while self._ready:
                task = self._ready.pop(0)
                try:
                    # Resume the task — it runs until the next await
                    # If await encounters a Future, the task yields it
                    yielded_future = task.step()
                    
                    if yielded_future is not None:
                        # Task is waiting for this future
                        self._waiting[id(yielded_future)] = task
                        yielded_future.add_done_callback(
                            lambda f: self._ready.append(
                                self._waiting.pop(id(f))
                            )
                        )
                except StopIteration as e:
                    # Task completed — store its return value
                    task.set_result(e.value)
            
            # No tasks ready — either done or all waiting
            # This is where the loop would block on I/O (select/poll/epoll)
            if not self._ready and self._waiting:
                self._wait_for_io()  # Blocks until something is ready
```

### 8.6 What This Means for Deeply Nested Async

```python
# This works: infinitely nested async calls
async def level_5():
    return await level_4()

async def level_4():
    return await level_3()

async def level_3():
    return await level_2()

async def level_2():
    return await level_1()

async def level_1():
    await asyncio.sleep(0)
    return "deep result"

# ❗ This works because coroutines don't use the CALL STACK
# They use HEAP-ALLOCATED coroutine objects.
# You can nest 1000 levels without stack overflow (memory permitting).

async def very_deep(n: int):
    if n == 0:
        return "base"
    result = await very_deep(n - 1)  # Recursive async call!
    return f"level {n}: {result}"

# This works fine even with n=5000:
result = asyncio.run(very_deep(5000))
print(result)  # "level 5000: ... level 1: base"

# Compare with sync recursion:
def sync_deep(n: int):
    if n == 0:
        return "base"
    result = sync_deep(n - 1)  # Uses REAL stack frames!
    return f"level {n}: {result}"

# This will stack overflow at ~1000 (depends on Python's recursion limit):
# sync_deep(5000)  # RecursionError: maximum recursion depth exceeded
```

**Key insight:** `await` chains don't consume stack space. Each coroutine frame is a Python object on the heap, not a C stack frame. This means:

| Property | Sync Functions | Async Coroutines |
|----------|---------------|-----------------|
| **Frame location** | C stack (limited, ~1MB total) | Python heap (can be GB) |
| **Max recursion depth** | ~1000 (sys.getrecursionlimit()) | Limited only by memory |
| **Suspend/Resume** | Not possible | Built-in via `await` |
| **State preservation** | Automatic (stack frame) | Manual (coroutine object) |

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

**Nesting depth in this example:** `handle_request` → `_gather_context` → `_get_user_context` → `_db.get_user_profile` → (some DB driver's async call) → (socket I/O). That's **6 levels** of nested async, and it works perfectly because each level is a heap-allocated coroutine object.

### 8.8 Performance Characteristics of Nested Async

| Metric | Value | Explanation |
|--------|-------|-------------|
| **Coroutine creation** | ~0.5μs | Python object allocation (heap) |
| **Await overhead** | ~0.2μs | Yield/resume cycle |
| **Nested chain (10 levels)** | ~7μs | Total overhead for 10 awaits |
| **Nested chain (100 levels)** | ~70μs | Still negligible for practical use |
| **Memory per coroutine** | ~200 bytes | Coroutine object + frame |
| **Memory for 10K coroutines** | ~2MB | Entirely feasible |

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
| **Await chains don't stack overflow** | Coroutines are heap objects, not C stack frames |
| **Depth is practically unlimited** | Limited by memory, not stack size |
| **Each await is a suspension point** | The event loop can interleave other work
| **Cancellation propagates through nesting** | Cancelling the outer task cancels all inner awaits |
| **Exception handling works naturally** | try/except around the outer await catches inner exceptions |
| **Parallelism within nesting works** | `asyncio.gather()` inside a nested await creates sub-tasks |
| **Overhead is negligible** | ~0.2μs per await, ~200 bytes per coroutine |

---

## 9. QUICK REFERENCE

```python
# ─── Key Functions ─────────────────────────────────

asyncio.run(main())                           # Run async from sync
await coroutine                                # Wait for result
asyncio.create_task(coro)                      # Run in background
asyncio.gather(*tasks, return_exceptions=True) # Parallel execution
asyncio.wait_for(coro, timeout=10.0)          # With timeout
asyncio.shield(coro)                           # Prevent cancellation
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
