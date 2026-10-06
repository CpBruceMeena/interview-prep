# Rate Limiter - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)
> **Evaluation Focus:** Algorithms, concurrency, distributed atomicity, API design

---

## Question 1: Algorithm Comparison
**Interviewer:** *"Compare rate limiting algorithms. When would you use each?"*

### 🎯 Expected Answer

**1. Token bucket.** A bucket of `capacity` tokens refilled at `rate`/s; each request takes one. Refill lazily on access: `tokens = min(cap, tokens + elapsed * rate)`. Allows a burst of `capacity`, then a sustained `rate`. Two numbers per key. Good default for public APIs, where clients legitimately burst (a page load fires 10 calls). Used by AWS API Gateway and Stripe.

**2. Leaky bucket.** Two forms, and saying which one you mean is a signal:
- *As a meter (policer):* water level rises by 1 per request and drains at `rate`; reject on overflow. Mathematically the mirror of the token bucket (GCRA is the same thing in timestamp form).
- *As a queue (shaper):* requests wait in a bounded FIFO and are released at a constant rate. Smooths output for a downstream that cannot take bursts. Adds latency instead of rejecting.

**3. Fixed window counter.** One counter per aligned window. Cheapest, trivially done in Redis with `INCR`. **Boundary problem:** with 100/min, 100 requests at 00:59 and 100 at 01:00 means 200 within about a second.

**4. Sliding window log.** Store each accepted request's timestamp; count those in `(now − W, now]`. Exact, no boundary burst. Memory is O(limit) per key, which is fine for "5 logins per 15 minutes" and too much for "10,000 per hour" across millions of keys.

**5. Sliding window counter.** `estimate = prev × (1 − elapsed_fraction) + current`. Two counters per key, smooths the boundary problem. Approximate because it assumes the previous window was uniform; Cloudflare reported 0.003% of requests misjudged on real traffic.

| Algorithm | Accuracy | Memory/key | Bursts | Best for |
|-----------|----------|------------|--------|----------|
| Token bucket | Exact for its model | O(1) | Yes (configurable) | Public APIs, default choice |
| Leaky bucket (queue) | Exact | O(queue) | Absorbed as delay | Protecting a fragile downstream |
| Fixed window | Up to 2× at boundary | O(1) | Accidental | Coarse quotas (per day), cheap counters |
| Sliding log | Exact | O(limit) | No | Low limits where precision matters (login, OTP) |
| Sliding counter | ~Exact | O(1) | No | High-volume per-window limits |

---

## Question 2: Distributed Rate Limiting
**Interviewer:** *"Now 50 API servers share one limit per user. How?"*

### 🎯 Answer: centralised Redis, one Lua script per decision

The problem is the same check-then-act race as in-process, now across machines: two servers `GET` the counter, both see 99, both allow. You need the read, the decision and the write to be one atomic step on the server that holds the key.

**Why Lua, not the alternatives:**
- `GET` then `SET` from the client: racy.
- `MULTI/EXEC`: atomic, but the transaction cannot branch on a value it read. `WATCH` + retry works but degrades under contention on a hot key.
- **Lua script:** Redis runs a script to completion without interleaving other commands, so read-decide-write is atomic. One round trip.
- Plain `INCR` then `EXPIRE` as two calls: if the client dies between them, the key never expires and the user is blocked forever. Do both inside the script, or `SET key 0 EX <window> NX` then `INCR`.

**Token bucket in Lua** (one hash per key):

```lua
-- KEYS[1] = "rl:{user42}:search"   ARGV = capacity, rate_per_sec, cost
local t = redis.call('TIME')                         -- Redis server clock, not the app server's
local now = tonumber(t[1]) + tonumber(t[2]) / 1e6
local cap, rate, cost = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])

local b = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(b[1]) or cap
local ts = tonumber(b[2]) or now
tokens = math.min(cap, tokens + math.max(0, now - ts) * rate)

local allowed = 0
if tokens >= cost then tokens = tokens - cost; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(cap / rate * 1000))   -- full again by then
return {allowed, tostring(tokens)}   -- Lua numbers are truncated to integers in replies
```

**Sliding window log in Lua** (sorted set, score = timestamp):

```lua
-- KEYS[1] = key   ARGV = window_ms, limit, unique_request_id
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window, limit = tonumber(ARGV[1]), tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[3])   -- member must be unique, or two requests in one ms collapse
  redis.call('PEXPIRE', KEYS[1], window)
  return 1
end
return 0
```

**Details interviewers probe:**
- **Clock:** use `redis.call('TIME')` inside the script. Passing `time.time()` from 50 app servers mixes 50 clocks with different skew. Calling `TIME` before a write is fine on Redis 5+ (scripts replicate their effects, not the script itself).
- **Redis Cluster:** all keys a script touches must hash to the same slot. One key per limit is fine; for "per-second and per-day for the same user in one script" use a hash tag: `rl:{user42}:sec`, `rl:{user42}:day`.
- **Load scripts once:** `SCRIPT LOAD` at startup, call with `EVALSHA`, fall back to `EVAL` on `NOSCRIPT` (after a failover or restart the script cache is empty).
- **Latency:** one round trip, typically 0.2–1 ms in-region. That is the price of exactness.

**Alternatives and their trade-offs:**
- **Local token bucket with `limit / N` per node.** No network hop, but only correct if the load balancer spreads a user evenly, and N changes with autoscaling.
- **Local counters + periodic sync** (every 100 ms push deltas, pull the global count). Sub-microsecond decisions; can overshoot by roughly `rate × sync_interval × nodes`. Fine for abuse protection, wrong for billing.
- **Sticky routing** (consistent-hash users to limiter nodes). No shared store; rebalancing loses or duplicates state, and a hot user is a hot node.

---

## Question 3: Concurrency in the in-process version
**Interviewer:** *"Your `try_acquire` is called from 32 threads. What breaks, and how do you fix it without a global lock?"*

### 🎯 Answer

`if level >= 1: level -= 1` is a check-then-act. Two threads read `level = 1.0`, both pass the check, both decrement, and the limit is exceeded. Python's GIL does not help: the thread can switch between the comparison and the subtraction.

Fix in `RateLimiter`:
1. A **map lock** held only for get-or-create of the key's entry.
2. A **per-key lock** held around the whole check-and-consume.

Different keys never contend; the same key serialises, which it must. If there are millions of keys and lock objects feel heavy, use **lock striping**: `locks[hash(key) % 1024]`.

Then the follow-up: *"How do you stop the map growing forever?"* `evict_idle()` drops keys whose state equals a fresh one. The race: a request has looked up the entry, the janitor evicts it, the request consumes from the orphan, and the next request gets a fresh full bucket. Fix: mark the entry `evicted` under its lock; the request re-checks under the lock and retries. The test suite forces that interleaving deterministically.

---

## Question 4: "Now add…" extensions

| Ask | Answer |
|-----|--------|
| **Return `Retry-After`** | Each algorithm can compute it: token bucket `(1 − tokens)/rate`; fixed window `window_end − now`; sliding log `oldest + W − now`. The code returns it in `RateLimitDecision`. |
| **Multiple limits** (10/s **and** 1000/day) | Check all, then consume all, atomically. In-process: lock both keys in a fixed order. In Redis: one script over hash-tagged keys. Checking and consuming each limiter in turn wastes the per-second token when the daily limit then denies. |
| **Weighted requests** (a bulk export costs 10) | `try_acquire(state, now, cost)`. Buckets subtract `cost`; the log needs `cost` entries or a (timestamp, cost) pair with a running sum. |
| **Tiers** (free/pro/enterprise) | The rule is looked up by `(tier, endpoint)`; the key stays per client. Changing a client's tier changes the rule, not the state. |
| **Queue instead of reject** | Leaky bucket as a shaper: bounded queue + one worker releasing at `rate`. Reject when the queue is full, and put a deadline on queued requests so callers do not wait past their own timeout. |
| **Hot-reload rules** | Build a new immutable rule map and swap the reference. Existing state keeps working if the algorithm is unchanged; on an algorithm change, start fresh state. |

---

## Question 5: Failure handling
**Interviewer:** *"Redis is down. What happens to traffic?"*

### 🎯 Answer

Decide per endpoint, in advance:
- **Fail open** (allow) for normal API traffic: an outage of the limiter should not become an outage of the product.
- **Fail closed** (deny) for abuse-sensitive endpoints: login, OTP, password reset, expensive exports.
- Middle ground: fall back to a **local token bucket at `limit / N`**, behind a circuit breaker with a tight timeout (a few ms). A slow Redis is worse than a dead one, because every request waits on it.

Also: alert on the fallback being active, and never let the limiter's timeout exceed the endpoint's latency budget.

---

## Question 6: Testing strategy
**Interviewer:** *"How do you test this?"*

### 🎯 Answer
- **Inject the clock.** Never `sleep` in tests. Put requests exactly at `9.999` and `10.0` to pin the window boundaries.
- **Property per algorithm:** after a denial, waiting exactly `retry_after` lets the next request through, and waiting slightly less does not.
- **Document known weaknesses as tests:** fixed window lets 2× through at a boundary.
- **Concurrency:** N threads behind a `Barrier` hammer one key with a frozen clock; assert exactly `limit` were admitted. Check the test actually detects a race by removing the lock once (it should fail).
- **Forced interleavings** for races too narrow to hit by hammering (eviction between lookup and lock): subclass and inject the competing operation at the exact point.
- **Distributed:** run the Lua script against a real Redis in CI (Testcontainers), with concurrent clients.

---

## Question 7: HTTP response design

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 45
RateLimit-Policy: 100;w=60
RateLimit: limit=100, remaining=0, reset=45
```

- `429` and `Retry-After` on it are defined by **RFC 6585**. `X-RateLimit-Limit/Remaining/Reset` are a de facto convention (GitHub, Twitter), not part of any RFC.
- `RateLimit` / `RateLimit-Policy` come from the IETF httpapi working-group draft; header syntax has changed between drafts, so check the version you target.
- Express `reset` as seconds-from-now rather than an epoch timestamp so client clock skew does not matter.

---

## ⚠️ Common mistakes

1. **Check-then-act without a lock** (or "the GIL makes it safe"). It does not.
2. **One global lock** around all keys when per-key locking is just as easy.
3. **`INCR` and `EXPIRE` as separate calls**, leaving keys that never expire.
4. **App-server timestamps in a distributed limiter.** Use the store's clock.
5. **Unbounded memory:** a sliding log that records rejected requests, or per-window counters that are never deleted.
6. **`time.time()` for intervals** instead of a monotonic clock.
7. **Calling the sliding window counter exact**, or the fixed window "good enough" for a 100/min security limit.
8. **No `Retry-After`**, so well-behaved clients retry immediately and make the overload worse.
9. **Not deciding fail-open vs fail-closed** until the first Redis outage decides for you.

---

## 🎚️ Senior vs Staff signal

- **Senior:** implements token bucket and a window algorithm correctly, makes them thread-safe with an atomic check-and-consume, explains the fixed-window boundary burst, knows Redis + Lua is the standard distributed answer, tests with a fake clock.
- **Staff:** frames the choice by product need (burst tolerance, exactness, cost of overshoot) before naming an algorithm; separates policy from state so locking and storage are one concern; reasons about failure (fail open/closed per endpoint, slow-Redis circuit breaking), clock sources, cluster hash slots, and hot keys; quantifies the overshoot of local-with-sync approaches; and knows when *not* to centralise (e.g. per-node protection of a local resource needs no shared store at all).
