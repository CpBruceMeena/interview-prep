# Circuit Breaker - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)
> **Evaluation Focus:** State machine correctness under concurrency, retry storms and budgets, idempotency, timeouts/bulkheads, production comparison (Resilience4j, Envoy)

---

## Question 1: Why a circuit breaker at all?
**Interviewer:** *"The downstream has timeouts already. What does a breaker add?"*

### 🎯 Expected Answer

A timeout bounds **one** call. When the dependency is down, every request still waits the full timeout, holding a thread/connection the whole time. At 200 req/s with a 2 s timeout that's 400 threads parked on a dead service, and the caller falls over too (cascading failure).

A breaker remembers recent outcomes and, once the failure rate is high, **fails fast** in microseconds. That:
1. frees the caller's resources (threads, connections, memory),
2. stops piling load on a struggling dependency so it can recover,
3. gives a clean signal to fall back (cached data, degraded response).

---

## Question 2: Walk me through the states
**Interviewer:** *"What exactly triggers each transition?"*

### 🎯 Answer

- **CLOSED → OPEN**: at least `minimum_calls` in the window **and** failure rate ≥ threshold. The minimum avoids tripping on 1/1 or 2/2 failures after a deploy.
- **OPEN → HALF_OPEN**: `open_duration` elapsed. Checked lazily on the next `acquire()`/`state` read, so no timer thread.
- **HALF_OPEN → CLOSED**: `half_open_max_calls` probes succeed. Window reset.
- **HALF_OPEN → OPEN**: any probe fails; `open_duration` restarts.

Common variant: exponential backoff on `open_duration` for repeated re-opens (Envoy does this for ejection time: base × number of ejections).

---

## Question 3: Concurrency
**Interviewer:** *"100 threads call through it as it turns HALF_OPEN. What happens?"*

### 🎯 Answer

Exactly `half_open_max_calls` get permits; the rest get `CallNotPermittedError`. The check ("slot free?") and the reservation (`_probes_issued += 1`) are in one critical section. With a check-then-act split across two lock acquisitions, all 100 could pass the check. `test_exactly_n_probes_admitted_under_contention` releases 32 threads on a `Barrier` and asserts exactly 3 get in.

Follow-ups interviewers push on:

- **Stale outcomes.** A call admitted in CLOSED that takes 30 s returns a failure after the breaker went OPEN → HALF_OPEN. Recording it would re-open a recovering circuit. Fix: each `Permit` carries the generation it was issued in; `_transition` bumps the generation; stale results are dropped.
- **Leaked probes.** A probe that raises a non-counted exception (e.g. `ValueError`) must still release its slot, otherwise HALF_OPEN rejects everything forever. `call()` catches `BaseException` and `on_error` releases the slot. A probe that **hangs** forever is the remaining hole: put a `TimeLimiter` inside the breaker or add a max-wait-in-half-open.
- **Listeners.** Called after the lock is released. A listener that does I/O inside the lock would serialize every call to the dependency behind a log write.
- **Lock granularity.** One lock per breaker. The critical sections are a handful of integer updates, so contention is low; a lock-free CAS version (as in Resilience4j's `AtomicReference<State>`) is an optimization, not a correctness requirement.

---

## Question 4: Count-based vs time-based window
**Interviewer:** *"Which window would you pick?"*

### 🎯 Answer

| | Count-based (last N calls) | Time-based (last N seconds) |
|---|---|---|
| Memory | O(N) | O(N buckets) |
| Low traffic | Old outcomes linger for hours | Old outcomes age out |
| High traffic | Window covers milliseconds; reacts instantly | Smooths over N seconds |
| Predictability | Same number of samples every decision | Sample count varies, hence `minimum_calls` |

Low or bursty traffic: time-based. High, steady traffic: count-based is cheap and precise. Both are O(1) per record here (ring buffer with running totals; per-second buckets).

---

## Question 5: Retry storms
**Interviewer:** *"Every service retries 3 times. What goes wrong?"*

### 🎯 Answer

**Retry amplification multiplies across layers.** A → B → C → D, each doing up to 3 attempts: one user request can become 3³ = 27 calls to D. When D slows down, timeouts at each layer fire retries, load on D multiplies exactly when it has the least capacity, and it can't recover even after the original cause is gone (a metastable failure).

Mitigations, from most to least important:
1. **Retry at one layer only**, usually the edge or the layer closest to the failing call; other layers pass errors through.
2. **Retry budgets**: cap retries as a fraction of normal traffic (below).
3. **Exponential backoff with jitter**: spreads retries in time so synchronized clients don't hit in waves.
4. **Breaker inside retry**: once open, retries stop immediately (`CallNotPermittedError` is not retryable).
5. **Respect `Retry-After` / 429 / 503** and don't retry non-transient errors (4xx).
6. **Deadline propagation**: don't retry if the remaining end-to-end deadline can't fit another attempt.

---

## Question 6: Retry budgets
**Interviewer:** *"Explain a retry budget and implement it."*

### 🎯 Answer

A per-client (per downstream) cap on retries relative to regular traffic, so retries can never more than marginally increase load.

`RetryBudget` follows gRPC's retry throttling: tokens start at `max_tokens`; each failed attempt −1; each success +`token_ratio`; retries allowed only while `tokens > max_tokens / 2`. With mostly successes the bucket stays full and retries flow; when failures dominate, it drains below half and retries stop until successes refill it.

Other forms: Envoy's `retry_budget` (active retries ≤ `budget_percent` of active requests, with a `min_retry_concurrency` floor; defaults 20% and 3), Finagle's ratio-of-requests budget. Same idea: **retries proportional to successful work, not to failures**.

```python
budget = RetryBudget(max_tokens=10, token_ratio=0.1)   # one per downstream, shared
retry = Retry(RetryConfig(max_attempts=3), budget=budget)
```

---

## Question 7: Idempotency
**Interviewer:** *"Can you retry a payment call?"*

### 🎯 Answer

Only if the operation is idempotent, because a timeout means **unknown outcome**, not failure: the server may have committed and the response got lost.

- Naturally idempotent: GET, PUT (full replace), DELETE by id, "set status to X".
- Not idempotent: POST create, "increment", "charge $10". Make them idempotent with an **idempotency key**: client generates a key per logical operation and sends it on every attempt; the server stores `(key → result)` atomically with the effect and returns the stored result on a repeat (Stripe's `Idempotency-Key`).
- The key must be generated **outside** the retry loop. A new key per attempt defeats the purpose.
- Safe-to-retry also depends on **where** it failed: connection refused (request never sent) is always safe; a timeout after sending is only safe with idempotency.
- Server side: key store needs a TTL longer than the client's total retry window, and concurrent requests with the same key must serialize (unique constraint or lock), with the second one waiting or getting 409.

---

## Question 8: Bulkhead and timeout
**Interviewer:** *"Why isn't a breaker enough?"*

### 🎯 Answer

The breaker reacts only after failures accumulate. Before it trips, a **slow** dependency can exhaust a shared thread pool and take down unrelated endpoints. A **bulkhead** caps concurrent calls per dependency (semaphore here; Hystrix used a thread pool per dependency), so the blast radius is that dependency's slots. A **timeout** converts a hang into a failure the breaker can count.

Python caveat (stated in `TimeLimiter`): a timed-out thread keeps running. The pool size bounds the leak; the proper fix is to pass the deadline into the I/O call itself so the work stops.

---

## Question 9: Composition order
**Interviewer:** *"In what order do you stack these?"*

### 🎯 Answer

`Retry( CircuitBreaker( Bulkhead( TimeLimiter( call ) ) ) )`. Resilience4j's default aspect order is `Retry( CircuitBreaker( RateLimiter( TimeLimiter( Bulkhead( call ) ) ) ) )`; the only difference is whether the bulkhead slot is held while the caller waits (ours) or only while the work runs on the pool thread (theirs).

- Retry outside the breaker: each attempt is counted, and an open breaker short-circuits the loop.
- Breaker outside the time limiter: timeouts count as failures.
- If retry were **inside** the breaker, one logical call would record one outcome after up to N attempts. The breaker would see fewer, later failures and trip slower.

---

## Question 10: Comparison with production systems
**Interviewer:** *"How does yours compare to Resilience4j or Envoy?"*

### 🎯 Answer

| Feature | This LLD | Resilience4j CircuitBreaker | Envoy |
|---------|----------|-----------------------------|-------|
| Where | In-process library | In-process (JVM) | Sidecar / proxy, per upstream cluster |
| Trip signal | Failure rate over count/time window | Failure rate **and** slow-call rate over count/time window | "Circuit breaking" = concurrency limits (max connections, pending requests, requests, retries); **outlier detection** ejects individual hosts on consecutive 5xx / gateway errors or success-rate deviation |
| Granularity | Per breaker instance | Per named breaker | Per cluster (limits) and per host (outlier ejection) |
| Half-open | N probes, all must succeed | N probes, evaluated against the failure-rate threshold | Ejected host returns after `base_ejection_time × times_ejected`; `max_ejection_percent` caps how much of the cluster can be ejected |
| Extra states | — | DISABLED, FORCED_OPEN, METRICS_ONLY | — |
| Retries | `Retry` + gRPC-style budget | Separate `Retry` module | Retry policy + `retry_budget` |

Key insight: **Envoy's "circuit breaker" is really a bulkhead.** The thing that behaves like a per-host breaker is outlier detection. The proxy approach gives language-independent, centrally configured policies; the library approach knows application semantics (which exceptions count, fallbacks, idempotency).

Hystrix (Netflix) is in maintenance mode since 2018; Resilience4j is its successor.

---

## Question 11: Testing strategy
**Interviewer:** *"How do you test time-based behaviour without sleeping?"*

### 🎯 Answer

- Inject a `Clock`. `ManualClock.advance(10)` crosses `open_duration` instantly; `ManualClock.sleep` lets `Retry` run its backoff without waiting. Seed the RNG for jitter.
- State-machine table tests: every transition and every non-transition (just below threshold, below minimum calls, 9.9 s vs 10 s).
- Concurrency tests: `Barrier` to release threads together; assert exact probe count; assert window totals equal the number of calls after 8 threads × 500 calls.
- Composition tests: retry stops on open breaker; retry attempts trip the breaker; timeout counts as breaker failure.
- In production: chaos tests (inject latency/errors with a fault-injection proxy) and alerting on state transitions.

---

## ⚠️ Common mistakes

- Using `time.time()` (wall clock can jump) instead of a monotonic clock, or hard-coding it so tests must `sleep`.
- Tripping on N consecutive failures only, with no notion of rate or minimum calls.
- Counting caller errors (4xx, validation) as dependency failures.
- Check-then-act in HALF_OPEN, letting every waiting thread become a probe.
- Never releasing a probe slot when the call raises an uncounted exception.
- Recording late results from calls admitted under an earlier state.
- Retrying non-idempotent operations, or generating a new idempotency key per attempt.
- Retry without jitter (synchronized waves) or without a budget (storms).
- Retry inside the breaker, or retrying `CallNotPermittedError`.
- Calling listeners or logging inside the lock.

---

## 🎯 Senior vs Staff signal

- **Senior**: correct three-state machine with a sliding failure-rate window, thread-safe probe limiting, injectable clock with deterministic tests, retry with capped exponential backoff and jitter, decorator API.
- **Staff**: explains retry amplification across layers and metastable failure, insists on budgets and single-layer retries, ties retries to idempotency keys and deadline propagation, handles stale outcomes and leaked probes, and knows where the library vs mesh boundary sits (Envoy outlier detection vs in-process breakers) and what the org-wide defaults should be.
