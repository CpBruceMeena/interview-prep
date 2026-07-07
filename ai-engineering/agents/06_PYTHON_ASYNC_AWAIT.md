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

## 8. QUICK REFERENCE

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
