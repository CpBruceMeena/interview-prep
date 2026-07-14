# Rate Limiter - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Algorithms, distributed systems, API design, throttling

---

## Question 1: Algorithm Comparison
**Interviewer:** *"Compare rate limiting algorithms. When would you use each?"*

### 🎯 Expected Answer

**1. Token Bucket**
```python
class TokenBucket:
    def __init__(self, max_tokens, refill_rate):
        self._tokens = max_tokens
        self._max = max_tokens
        self._refill_rate = refill_rate  # tokens/second
        self._last_refill = time.time()
    
    def allow(self) -> bool:
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False
    
    def _refill(self):
        elapsed = time.time() - self._last_refill
        self._tokens = min(self._max, self._tokens + elapsed * self._refill_rate)
        self._last_refill = time.time()
```

**Characteristics:** Bursty (allow up to `max_tokens` in a burst), then throttled to `refill_rate`.  
**Best for:** APIs with legitimate burst traffic (e.g., loading a dashboard with multiple widgets)

**2. Sliding Window Log**
- Stores timestamps of each request in a sorted list
- Memory: O(N) where N = requests in window
- Most accurate, most expensive

**3. Fixed Window Counter**
```
Window 1 (00:00-00:60): count=100 → max=100 → Block
Window 2 (00:60-01:00): count=0 → Allow
```
**Problem:** Boundary spike. If 100 requests at 00:59 and 100 at 01:01, 200 requests in 2 seconds go through.

**4. Sliding Window Counter (Recommended)**
```
current_weight = previous_window_count * (1 - progress) + current_count
```
Balances accuracy and memory. Used by Stripe, GitHub.

| Algorithm | Accuracy | Memory | CPU | Best For |
|-----------|----------|--------|-----|----------|
| Token Bucket | Medium | O(1) | Low | Bursty traffic |
| Sliding Log | Perfect | O(N) | Medium | Critical accuracy |
| Fixed Window | Low | O(1) | Low | Non-critical, simple |
| Sliding Counter | High | O(1) | Low | Most production APIs |

---

## Question 2: Distributed Rate Limiting
**Interviewer:** *"How would you rate-limit across multiple servers?"*

### 🎯 Architecture

**Option A: Centralized Redis (Recommended)**
```python
# Atomic Lua script for correctness
script = """
local key = KEYS[1]
local max = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window)
end
if count > max then
    return 0
end
return 1
"""
result = redis.eval(script, 1, rate_limit_key, max, window, time.time())
```

**Option B: Local + Background Sync**
- Each server maintains local counters
- Periodically sync to central store
- Pros: Low latency, works during network partitions
- Cons: Can temporarily exceed limits after partition

**Option C: Consistent Hashing**
- Route user to specific rate limiter server
- Pros: Simple, no coordination
- Cons: Uneven load, rebalancing complexity

---

## Question 3: API Rate Limiting Design

**Response Headers (RFC 6585):**
```
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1623456789
Retry-After: 45
```

**Tiered limits:**
```python
TIERS = {
    "free": {"per_second": 5, "per_minute": 100, "per_day": 1000},
    "pro": {"per_second": 50, "per_minute": 1000, "per_day": 50000},
    "enterprise": {"per_second": 500, "per_minute": 10000, "per_day": 500000},
}
```

**Graceful degradation:** Return 429 with `Retry-After` header. Never silently drop requests.

---

## Question 4: Throttling vs Quotas

| Aspect | Throttling | Quotas |
|--------|------------|--------|
| **Timeframe** | Seconds/minutes | Days/months |
| **Reset** | Rolling window | Calendar period |
| **Enforcement** | Hard block | Soft then hard |
| **Use case** | Prevent abuse | Monetize usage |
| **Example** | 100 req/min | 10M requests/month |

---

## Question 5: HTTP Header Design

```
RateLimit-Policy: 100;w=60  # 100 requests per 60-second window
RateLimit: limit=100, remaining=87, reset=1623456789
Retry-After: 45
```

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | RateLimitAlgorithm | Pluggable: token-bucket, sliding-window, etc. |
| **Factory** | RateLimiterFactory | Create strategy from config |
| **Decorator** | RateLimitMiddleware | Non-invasively wrap API endpoints |
| **Singleton** | RateLimiter registry | Single global rate limiter |
