# 📊 Multi-LLM Production Operations — Monitoring, Rate Limiting, Caching & Reliability

> **Target:** Principal Engineer | **Focus:** Production operational excellence for multi-LLM deployments | **Reviewed:** October 2026
> *Companion to [08_MULTI_LLM_ARCHITECTURE.md](./08_MULTI_LLM_ARCHITECTURE.md) which covers routing, cost management, and fallback architecture*

!!! tip "30-second answer"
    Running LLMs in production is ordinary SRE plus four LLM-specific twists. **Usage is multi-dimensional** (input, cached input, cache writes, output, reasoning tokens, each priced differently), so meter what the provider reports, per call. **Limits are token-based** on both sides (your per-tenant quotas and the providers' RPM/TPM), so enforce them atomically in a shared store and back off on 429s. **Caching has two layers:** provider prompt caching of stable prefixes (free and always correct; do it first) and response caching (exact, or semantic with real correctness risk). **Quality is invisible to infra metrics**, so prompts and models are versioned config, changes ship through offline evals and A/B or canary tests on task-level quality, and every call is traced with OpenTelemetry GenAI attributes.

---

## Table of Contents

1. [Token Usage Monitoring](#1-token-usage-monitoring)
2. [Rate Limiting & Concurrency Control](#2-rate-limiting-concurrency-control)
3. [Response Caching Strategies](#3-response-caching-strategies)
4. [Retry Policies & Exponential Backoff](#4-retry-policies-exponential-backoff)
5. [Observability & Alerting](#5-observability-alerting)
6. [Prompt Versioning & Management](#6-prompt-versioning-management)
7. [A/B Testing Different Models](#7-ab-testing-different-models)
8. [Tenant-Level Cost Allocation](#8-tenant-level-cost-allocation)
9. [Logging & Distributed Tracing](#9-logging-distributed-tracing)
10. [Production Dashboard](#10-production-dashboard)

---

## 1. Token Usage Monitoring

### Granular Token Tracking

Record what the provider's response actually reports, per call. Modern usage objects have more than two numbers: cached input reads, cache writes and reasoning tokens are billed differently, so a two-field `prompt/completion` record mis-costs most real traffic.

```python
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional
from prometheus_client import Counter, Histogram

LLM_TOKENS = Counter("llm_tokens_total", "Tokens by type",
                     ["model", "provider", "type"])  # input|cached_input|cache_write|output|reasoning
LLM_REQUESTS = Counter("llm_requests_total", "LLM API requests",
                       ["model", "provider", "status"])
LLM_LATENCY = Histogram("llm_latency_seconds", "End-to-end LLM call latency",
                        ["model", "provider"],
                        buckets=[0.25, 0.5, 1, 2, 5, 10, 30, 60, 120])
LLM_TTFT = Histogram("llm_time_to_first_token_seconds", "Streaming time to first token",
                     ["model", "provider"], buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10])
LLM_COST = Counter("llm_cost_usd_total", "Estimated cost in USD", ["model", "provider"])

@dataclass
class TokenUsageRecord:
    """One LLM API call. Field names are provider-neutral; map from
    OpenAI usage.input_tokens / output_tokens / *_details.cached_tokens /
    reasoning_tokens, or Anthropic usage.input_tokens / output_tokens /
    cache_read_input_tokens / cache_creation_input_tokens."""
    model: str                      # the exact model id the response reports
    provider: str
    input_tokens: int               # uncached input
    output_tokens: int              # includes reasoning tokens where billed as output
    cached_input_tokens: int = 0    # prompt-cache reads (cheap)
    cache_write_tokens: int = 0     # prompt-cache writes (Anthropic bills a premium)
    reasoning_tokens: int = 0       # informational: already inside output_tokens
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    ttft_ms: Optional[float] = None
    tenant_id: Optional[str] = None
    prompt_version: Optional[str] = None
    status: str = "success"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

def record(r: TokenUsageRecord) -> None:
    labels = {"model": r.model, "provider": r.provider}
    for kind, n in [("input", r.input_tokens), ("cached_input", r.cached_input_tokens),
                    ("cache_write", r.cache_write_tokens), ("output", r.output_tokens)]:
        LLM_TOKENS.labels(**labels, type=kind).inc(n)
    LLM_REQUESTS.labels(**labels, status=r.status).inc()
    LLM_LATENCY.labels(**labels).observe(r.latency_ms / 1000)
    if r.ttft_ms is not None:
        LLM_TTFT.labels(**labels).observe(r.ttft_ms / 1000)
    LLM_COST.labels(**labels).inc(r.cost_usd)
    # Ship the full record (with tenant_id, prompt_version, request id) to the
    # log/event pipeline for per-tenant analysis. Don't put tenant or user ids
    # in Prometheus labels: unbounded cardinality.
```

Keep raw records in a log/event store (or your warehouse), not in a process-local list: an in-memory list grows without bound and is per replica. Derive per-minute rates, percentiles and per-model comparisons in PromQL or SQL.

### Streaming Token Counter

Don't count streamed tokens yourself with a local tokenizer: `tiktoken` only matches OpenAI tokenizers (Claude, Gemini and open models tokenize differently), and splitting text at arbitrary chunk boundaries miscounts. Use the usage the provider sends with the stream:

- **OpenAI:** final usage arrives in the last event (Responses API `response.completed`; Chat Completions needs `stream_options={"include_usage": True}`).
- **Anthropic:** `message_start` carries input usage and `message_delta` carries cumulative output usage; the SDK's `get_final_message()` returns the totals.

A local estimate (characters ÷ ~4 for English) is fine for a live progress indicator, never for billing. For pre-flight estimates on Claude, use the token-counting endpoint.

```python
async def generate(request):
    first_token_at = None
    start = time.perf_counter()
    async with anthropic_client.messages.stream(model=MODEL, max_tokens=4096,
                                                messages=request.messages) as stream:
        async for text in stream.text_stream:
            first_token_at = first_token_at or time.perf_counter()
            yield f"data: {json.dumps({'content': text})}\n\n"
        final = await stream.get_final_message()
    u = final.usage
    record(TokenUsageRecord(
        model=final.model, provider="anthropic",
        input_tokens=u.input_tokens, output_tokens=u.output_tokens,
        cached_input_tokens=u.cache_read_input_tokens or 0,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
        latency_ms=(time.perf_counter() - start) * 1000,
        ttft_ms=((first_token_at or time.perf_counter()) - start) * 1000,
    ))
    yield f"data: {json.dumps({'done': True, 'output_tokens': u.output_tokens})}\n\n"
```

### Token Budget Enforcement

Budgets must be **atomic** across replicas and must account for **output** as well as input. Pattern: *reserve* the worst case (estimated input + `max_tokens`) before the call, then *reconcile* to the actual usage afterwards.

```python
RESERVE = """
-- KEYS: budget counters; ARGV[1]: tokens to reserve; ARGV[i+1]: limit for KEYS[i]
for i, key in ipairs(KEYS) do
    local used = tonumber(redis.call('GET', key) or '0')
    if used + tonumber(ARGV[1]) > tonumber(ARGV[i + 1]) then
        return i            -- index of the budget that would be exceeded
    end
end
for i, key in ipairs(KEYS) do
    redis.call('INCRBY', key, ARGV[1])
    if redis.call('TTL', key) < 0 then redis.call('EXPIRE', key, 40 * 86400) end
end
return 0
"""

class TokenBudgetEnforcer:
    """Per-user daily, per-tenant monthly and global monthly token budgets."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.reserve_script = redis_client.register_script(RESERVE)

    def _keys(self, user_id: str, tenant_id: str) -> list[str]:
        now = datetime.now(UTC)
        return [f"budget:user:{user_id}:{now:%Y%m%d}",
                f"budget:tenant:{tenant_id}:{now:%Y%m}",
                f"budget:global:{now:%Y%m}"]

    async def reserve(self, user_id, tenant_id, est_input, max_output, limits) -> list[str]:
        keys = self._keys(user_id, tenant_id)
        reserved = est_input + max_output                # worst case
        exceeded = await self.reserve_script(keys=keys, args=[reserved, *limits])
        if exceeded:
            raise TokenBudgetExceeded(keys[exceeded - 1])
        return keys

    async def reconcile(self, keys: list[str], reserved: int, actual: int) -> None:
        # Give back the unused part of the reservation (or add any overrun)
        delta = actual - reserved
        if delta:
            pipe = self.redis.pipeline()
            for k in keys:
                pipe.incrby(k, delta)
            await pipe.execute()
```

For agents, enforce a per-*run* budget too (sum over every model call in the loop), and stop the loop cleanly when it is exhausted. Token budgets are a proxy; for money, budget in dollars using the price table, because cached input, output and reasoning tokens cost very different amounts.

---

## 2. Rate Limiting & Concurrency Control

### Multi-Layer Rate Limiting

Two different limits are in play: the limits **you impose** on your users (fairness, abuse, cost) and the limits **providers impose** on you (requests per minute, input and output tokens per minute, per model and organization). Enforce yours at the edge; stay under theirs with shared accounting and backoff.

```python
import time
from enum import Enum

class RateLimitTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    INTERNAL = "internal"

# Per-user limits: tokens per minute, requests per minute, concurrent requests
TIERS = {
    RateLimitTier.FREE:       {"tpm": 10_000,     "rpm": 20,     "concurrent": 1},
    RateLimitTier.PRO:        {"tpm": 100_000,    "rpm": 200,    "concurrent": 5},
    RateLimitTier.ENTERPRISE: {"tpm": 1_000_000,  "rpm": 2_000,  "concurrent": 50},
    RateLimitTier.INTERNAL:   {"tpm": 10_000_000, "rpm": 10_000, "concurrent": 200},
}

# Check-and-increment in ONE atomic script. A GET-then-INCR from the client
# races: two replicas both see "under limit" and both proceed.
CHECK_AND_INCR = """
-- KEYS[i] counter key; ARGV[2i-1] amount to add; ARGV[2i] limit
for i, key in ipairs(KEYS) do
    local used = tonumber(redis.call('GET', key) or '0')
    if used + tonumber(ARGV[2*i-1]) > tonumber(ARGV[2*i]) then
        return i
    end
end
for i, key in ipairs(KEYS) do
    redis.call('INCRBY', key, ARGV[2*i-1])
    redis.call('EXPIRE', key, 120)
end
return 0
"""

class MultiLayerRateLimiter:
    """Fixed one-minute windows for user, model (provider quota) and global
    limits. Fixed windows allow up to 2x bursts at a boundary; use a sliding
    window or token bucket (GCRA) if that matters."""

    def __init__(self, redis_client, provider_limits: dict):
        self.redis = redis_client
        self.script = redis_client.register_script(CHECK_AND_INCR)
        self.provider_limits = provider_limits   # {model: {"rpm":..., "tpm":...}} from your provider quota

    async def check(self, user_id: str, model: str, est_tokens: int,
                    tier: RateLimitTier) -> tuple[bool, int]:
        minute = int(time.time()) // 60
        user, prov = TIERS[tier], self.provider_limits[model]
        checks = [
            (f"rl:user:{user_id}:rpm:{minute}", 1, user["rpm"]),
            (f"rl:user:{user_id}:tpm:{minute}", est_tokens, user["tpm"]),   # TOKENS, not +1
            (f"rl:model:{model}:rpm:{minute}", 1, prov["rpm"]),
            (f"rl:model:{model}:tpm:{minute}", est_tokens, prov["tpm"]),
        ]
        args = [x for _, amount, limit in checks for x in (amount, limit)]
        failed = await self.script(keys=[k for k, _, _ in checks], args=args)
        retry_after = 60 - int(time.time()) % 60
        return failed == 0, retry_after
```

Return `429` with a `Retry-After` header when a user limit is hit. Providers also report their own remaining quota in response headers (OpenAI `x-ratelimit-remaining-requests` / `-tokens`; Anthropic `anthropic-ratelimit-requests-remaining`, `-input-tokens-remaining`, `-output-tokens-remaining`, plus `retry-after` on 429s); feed those back into your model-level limits instead of hard-coding them.

### Concurrency Pool Management

```python
import asyncio
from prometheus_client import Histogram, Counter

QUEUE_WAIT = Histogram("llm_queue_wait_seconds", "Wait for a concurrency slot", ["model"])
TIMEOUTS = Counter("llm_timeouts_total", "LLM call timeouts", ["model"])

class LLMConnectionPool:
    """Per-model concurrency cap within one process. Limits come from config
    (load-tested against provider quotas), not from hard-coded model names."""

    def __init__(self, max_concurrent: dict[str, int], default: int = 20):
        self._max = max_concurrent
        self._default = default
        self._pools: dict[str, asyncio.Semaphore] = {}

    def _sem(self, model: str) -> asyncio.Semaphore:
        if model not in self._pools:
            self._pools[model] = asyncio.Semaphore(self._max.get(model, self._default))
        return self._pools[model]

    async def execute(self, model: str, call_fn, *args, timeout: float = 120.0, **kwargs):
        start = time.perf_counter()
        async with self._sem(model):
            QUEUE_WAIT.labels(model=model).observe(time.perf_counter() - start)
            try:
                async with asyncio.timeout(timeout):
                    return await call_fn(*args, **kwargs)
            except TimeoutError:
                TIMEOUTS.labels(model=model).inc()
                raise
```

A semaphore only bounds one replica: with N replicas the effective limit is N × cap, so size caps as `provider_quota / replicas` or use the Redis limits above as the global guard. Set timeouts from observed latency: long reasoning or agentic calls can legitimately take minutes, so stream them rather than lowering the timeout until healthy calls fail. Changing a cap at runtime by swapping the semaphore loses track of in-flight permits; restart-free tuning needs a resizable limiter (or just a config reload with drain).

The provider SDKs already retry 408/409/429/5xx with exponential backoff (OpenAI and Anthropic both default to 2 retries and honour `retry-after`). Configure `max_retries` and timeouts on the client rather than wrapping raw HTTP calls, and keep your own retry layer for cross-provider fallback (section 4).

---

## 3. Response Caching Strategies

### Provider-Side Prompt Caching (Do This First)

Before building any response cache, use the providers' **prompt (prefix) caching**. It caches the model's processing of a repeated prompt *prefix*, not the answer, so it is always correct, and agent loops resend the same system prompt, tool definitions and growing history on every turn.

| | Anthropic | OpenAI |
|---|---|---|
| How to enable | `cache_control: {"type": "ephemeral"}` on content blocks (up to 4 breakpoints) or once at the top level | Automatic for prompts above a minimum length |
| Lifetime | 5 minutes by default (refreshed on use), optional 1 hour | Minutes by default; longer retention options on some models |
| Billing | Cache reads much cheaper than input; cache writes cost more than plain input | Cached input billed at a discount |
| Check it worked | `usage.cache_read_input_tokens` | `usage.input_tokens_details.cached_tokens` (Responses) |

Rules that make or break the hit rate:

- **Stable content first, volatile content last.** Order is tools → system → messages. A timestamp, request id or user name in the system prompt invalidates everything after it.
- **Deterministic serialization:** same tool order, `sort_keys=True` for JSON you embed.
- **Caches are per model** (and per provider), so switching models mid-conversation or failing over starts cold.
- Check the minimum cacheable prefix length for each model; shorter prompts silently don't cache.

Track `cached_input_tokens / (input + cached_input)` as a first-class metric; a drop usually means someone added a dynamic value to the prompt prefix.

### Semantic Caching with Embeddings

A semantic cache returns a *previous answer* when a new query is similar enough. It can cut cost for FAQ-style traffic, but it is the riskiest cache: similarity is not equivalence.

- "How do I **cancel** my order?" and "How do I **not cancel** my order?" embed very close together.
- Answers that depend on the user, their account, the date or retrieved documents must not be shared: key the cache by everything the answer depends on (tenant, user or role, prompt version, model, data version).
- Thresholds are embedding-model specific; tune on labelled pairs and measure the false-hit rate, not just the hit rate.

```python
import hashlib, json
import numpy as np

class SemanticLLMCache:
    """Semantic cache backed by a vector index (Redis Query Engine / RediSearch,
    pgvector, OpenSearch kNN...). A linear scan over every cached key per
    lookup does not scale past a few thousand entries."""

    def __init__(self, vector_index, embed, threshold: float = 0.95, ttl_s: int = 3600):
        self.index = vector_index      # supports upsert(id, vector, payload, ttl) and knn(vector, k, filter)
        self.embed = embed             # async text -> np.ndarray (normalized)
        self.threshold = threshold
        self.ttl = ttl_s

    @staticmethod
    def scope(model: str, prompt_version: str, tenant_id: str) -> dict:
        # Everything the answer depends on, besides the query text
        return {"model": model, "prompt_version": prompt_version, "tenant": tenant_id}

    async def get(self, query: str, scope: dict) -> tuple[dict | None, float]:
        vec = await self.embed(query)
        hits = await self.index.knn(vec, k=1, filter=scope)
        if hits and hits[0].score >= self.threshold:
            return hits[0].payload["response"], hits[0].score
        return None, (hits[0].score if hits else 0.0)

    async def set(self, query: str, scope: dict, response: dict) -> None:
        vec = await self.embed(query)
        key = hashlib.sha256(json.dumps([query, scope], sort_keys=True).encode()).hexdigest()
        await self.index.upsert(key, vec, {"response": response, **scope}, ttl=self.ttl)
```

Only cache responses that are safe to reuse: no personal data, no time-sensitive facts, and not the output of tool calls with side effects.

### Exact-Match Cache with TTL

```python
class ExactMatchLLMCache:
    """
    Exact-match cache for identical requests (same model, prompt version,
    messages and parameters). Hits return in milliseconds instead of seconds.
    """
    
    def __init__(self, redis_client, default_ttl: int = 3600):
        self.redis = redis_client
        self.default_ttl = default_ttl
    
    def _build_key(self, model: str, params: dict, messages: list) -> str:
        # Model in the readable prefix so it can be invalidated per model;
        # everything that changes the answer goes into the hash.
        raw = json.dumps({"params": params, "messages": messages}, sort_keys=True)
        return f"llm:exact:{model}:{hashlib.sha256(raw.encode()).hexdigest()}"
    
    async def get(self, model: str, params: dict, messages: list) -> str | None:
        return await self.redis.get(self._build_key(model, params, messages))
    
    async def set(self, model: str, params: dict, messages: list,
                  response: str, ttl: int | None = None) -> None:
        await self.redis.setex(self._build_key(model, params, messages),
                               ttl or self.default_ttl, response)
    
    async def invalidate_model(self, model: str) -> None:
        """Delete only this model's entries (SCAN, never KEYS, in production)."""
        async for key in self.redis.scan_iter(match=f"llm:exact:{model}:*", count=1000):
            await self.redis.unlink(key)
```

Count hits and misses with Prometheus counters (`llm_cache_hits_total{cache="exact"}`), not instance attributes, so the rate is correct across replicas.

### Cache-Aware Orchestrator

```python
class CacheAwareRouter:
    """Exact cache → semantic cache → model call. Provider prompt caching
    applies underneath the model call regardless."""
    
    def __init__(self, exact_cache: ExactMatchLLMCache, semantic_cache: SemanticLLMCache):
        self.exact_cache = exact_cache
        self.semantic_cache = semantic_cache
    
    async def route(self, request, scope: dict) -> dict:
        params = {"prompt_version": request.prompt_version, "max_tokens": request.max_tokens}

        # Level 1: exact match
        if (hit := await self.exact_cache.get(request.model, params, request.messages)):
            return {"response": hit, "source": "exact_cache"}
        
        # Level 2: semantic (only for routes where reuse is safe)
        if request.semantic_cache_ok:
            hit, similarity = await self.semantic_cache.get(request.query_text, scope)
            if hit:
                return {"response": hit, "source": "semantic_cache", "similarity": similarity}
        
        # Level 3: call the model
        response = await self._call_llm(request)
        # Write-back in the background; keep a reference or use a TaskGroup
        # so the task isn't garbage-collected and failures get logged.
        self._spawn(self._cache_response(request, scope, response))
        return {"response": response, "source": "llm"}
```

---

## 4. Retry Policies & Exponential Backoff

### Production Retry Strategy

Start with the SDK's built-in retries (both the OpenAI and Anthropic SDKs retry connection errors, 408, 409, 429 and 5xx with exponential backoff and respect `retry-after`). Add your own layer only for what the SDK can't know: per-model circuit breakers, retry budgets across a whole agent run, and failover to another provider. Retry **only transient** errors: 429, 5xx (including Anthropic's `529 overloaded`), timeouts and connection errors. A 400 (bad request, context too long) or a content-policy refusal will fail identically on every retry.

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)
import logging

logger = logging.getLogger(__name__)

# ── Retry configuration by error type ──────────────────────
RETRY_CONFIGS = {
    # Transient errors — retry with backoff
    "rate_limit": {
        "max_attempts": 5,
        "min_wait": 1,      # seconds
        "max_wait": 60,     # seconds
        "exceptions": [RateLimitHit],
    },
    # Network errors — retry quickly
    "network": {
        "max_attempts": 3,
        "min_wait": 0.5,
        "max_wait": 10,
        "exceptions": [httpx.TimeoutException, httpx.ConnectError],
    },
    # Server errors (5xx, incl. 529 overloaded) — retry with longer backoff
    "server": {
        "max_attempts": 3,
        "min_wait": 5,
        "max_wait": 30,
        "exceptions": [ServerError],
    },
    # Non-retryable errors
    "no_retry": {
        "exceptions": [
            InvalidRequestError,  # Bad payload
            AuthenticationError,  # Bad API key
            TokenBudgetExceeded,  # Budget control
        ],
    },
}

class LLMRetryHandler:
    """
    Sophisticated retry handler for LLM API calls.
    Uses different strategies per error type.
    """
    
    def __init__(self):
        self.consecutive_failures: dict[str, int] = {}  # model → count
        self.circuit_breakers: dict[str, CircuitBreakerState] = {}
        self.metrics = metrics   # thin wrapper over prometheus_client counters/histograms
    
    async def call_with_retry(
        self,
        model: str,
        call_fn: Callable,
        max_attempts: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> Any:
        """Execute an LLM call with intelligent retry logic"""
        
        # Check circuit breaker
        if self._is_circuit_open(model):
            raise CircuitBreakerOpen(f"Circuit breaker open for {model}")
        
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                start = time.perf_counter()
                result = await call_fn()
                elapsed = (time.perf_counter() - start) * 1000
                
                # Success — record it
                self._record_success(model)
                self.metrics.observe_histogram(
                    "llm_retry_attempts",
                    attempt,
                    labels={"model": model, "result": "success"},
                )
                
                return result
                
            except (RateLimitHit, httpx.HTTPStatusError) as e:
                last_error = e
                
                if isinstance(e, RateLimitHit):
                    wait = e.retry_after
                elif e.response.status_code == 429:
                    # Retry-After may be seconds or an HTTP date; add jitter so
                    # many clients don't retry in lockstep
                    wait = parse_retry_after(e.response.headers.get("retry-after"),
                                             default=base_delay * 2) + random.uniform(0, 1)
                elif e.response.status_code >= 500:
                    wait = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                else:
                    raise  # Non-retryable HTTP error
                
                self._record_failure(model)
                
                if attempt < max_attempts:
                    logger.warning(
                        "LLM call to %s failed (attempt %d/%d): %s. "
                        "Retrying in %.1fs...",
                        model, attempt, max_attempts, str(e), wait,
                    )
                    self.metrics.increment_counter(
                        "llm_retries_total",
                        1,
                        labels={"model": model, "error": type(e).__name__},
                    )
                    await asyncio.sleep(wait)
                else:
                    self.metrics.increment_counter(
                        "llm_retries_exhausted",
                        1,
                        labels={"model": model, "error": type(e).__name__},
                    )
                    raise LLMRetryExhausted(
                        f"All {max_attempts} retries exhausted for {model}: {e}"
                    )
            
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                wait = min(base_delay * (2 ** (attempt - 1)), 10)  # Faster backoff for network
                
                if attempt < max_attempts:
                    logger.warning(
                        "Network error for %s (attempt %d/%d): %s",
                        model, attempt, max_attempts, str(e),
                    )
                    await asyncio.sleep(wait)
                else:
                    raise LLMRetryExhausted(
                        f"Network retries exhausted for {model}: {e}"
                    )
        
        raise last_error or LLMRetryExhausted(f"Retries exhausted for {model}")
    
    def _is_circuit_open(self, model: str) -> bool:
        """Check if circuit breaker is open for a model"""
        if model not in self.circuit_breakers:
            return False
        
        state = self.circuit_breakers[model]
        if state.status == "open":
            if datetime.now(UTC) >= state.next_retry_at:
                # Move to half-open
                state.status = "half-open"
                return False
            return True
        return False
    
    def _record_success(self, model: str):
        """Record a successful call"""
        self.consecutive_failures[model] = 0
        if model in self.circuit_breakers:
            self.circuit_breakers[model].status = "closed"
    
    def _record_failure(self, model: str):
        """Record a failed call and potentially open circuit"""
        self.consecutive_failures[model] = (
            self.consecutive_failures.get(model, 0) + 1
        )
        
        # Open circuit after 5 consecutive failures
        if self.consecutive_failures[model] >= 5:
            self.circuit_breakers[model] = CircuitBreakerState(
                status="open",
                failure_count=self.consecutive_failures[model],
                next_retry_at=datetime.now(UTC) + timedelta(seconds=60),
                opened_at=datetime.now(UTC),
            )
            logger.error(
                f"Circuit breaker OPEN for {model} after "
                f"{self.consecutive_failures[model]} consecutive failures"
            )

# ── Usage ──────────────────────────────────────────────────
retry_handler = LLMRetryHandler()

async def call_llm_with_retry(model: str, messages: list) -> str:
    """Production LLM call with full retry logic"""
    
    async def make_call():
        # SDK retries disabled here so the two layers don't multiply
        # (2 SDK retries x 5 handler attempts = up to 15 calls).
        return await llm_client.with_options(max_retries=0).responses.create(
            model=model,
            input=messages,
        )
    
    response = await retry_handler.call_with_retry(
        model=model,
        call_fn=make_call,
        max_attempts=5,
        base_delay=1.0,
    )
    
    return response.output_text
```

Two production details: cap retries with a **retry budget** (e.g. retries may add at most 10% extra load) so a provider brown-out isn't amplified by your own traffic, and remember that a timed-out request may still have been processed and billed, so a retry can double-charge tokens.

---

## 5. Observability & Alerting

### LLM-Specific Metrics

```python
class LLMMetricsCollector:
    """
    Collects and exposes LLM-specific Prometheus metrics.
    Provides the data needed for dashboards and alerting.
    """
    
    def __init__(self):
        self.metrics = {
            # ── Volume metrics ────
            "llm_requests_total": prometheus_client.Counter(
                "llm_requests_total", "Total LLM API requests",
                ["model", "provider", "status"],
            ),
            "llm_tokens_total": prometheus_client.Counter(
                "llm_tokens_total", "Total tokens processed",
                ["model", "type"],  # type: input, cached_input, cache_write, output
            ),
            
            # ── Performance metrics ────
            "llm_latency_seconds": prometheus_client.Histogram(
                "llm_latency_seconds", "LLM API latency",
                ["model", "provider"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            ),
            "llm_tokens_per_second": prometheus_client.Histogram(
                "llm_tokens_per_second", "Token generation speed",
                ["model"],
                buckets=[10, 50, 100, 200, 500, 1000],
            ),
            
            # ── Cost metrics ────
            "llm_cost_total": prometheus_client.Counter(
                "llm_cost_total", "Total cost in USD",
                ["model", "provider"],
            ),
            "llm_cost_per_request": prometheus_client.Histogram(
                "llm_cost_per_request", "Cost per request in USD",
                ["model"],
                buckets=[0.001, 0.01, 0.1, 1.0, 10.0],
            ),
            
            # ── Health metrics ────
            "llm_errors_total": prometheus_client.Counter(
                "llm_errors_total", "LLM API errors",
                ["model", "error_type"],
            ),
            "llm_circuit_breaker_status": prometheus_client.Gauge(
                "llm_circuit_breaker_status",
                "Circuit breaker status (0=closed, 1=open, 2=half-open)",
                ["model"],
            ),
            "llm_concurrent_requests": prometheus_client.Gauge(
                "llm_concurrent_requests",
                "Current concurrent LLM requests",
                ["model"],
            ),
            
            # ── Cache metrics ────
            "llm_cache_hits_total": prometheus_client.Counter(
                "llm_cache_hits_total", "Cache hits",
                ["cache_type"],  # exact, semantic
            ),
            "llm_cache_misses_total": prometheus_client.Counter(
                "llm_cache_misses_total", "Cache misses",
                ["cache_type"],
            ),
            
            # ── Rate limit metrics ────
            "llm_rate_limited_requests_total": prometheus_client.Counter(
                "llm_rate_limited_requests_total",
                "Requests that hit rate limits",
                ["model", "tier"],
            ),
            
            # ── Fallback metrics ────
            "llm_fallbacks_total": prometheus_client.Counter(
                "llm_fallbacks_total", "Fallback events",
                ["from_model", "to_model", "reason"],
            ),
        }
    
    def record_request(
        self, model: str, provider: str, duration_ms: float,
        status: str, prompt_tokens: int, completion_tokens: int,
        cost: float, error: Optional[str] = None,
    ):
        """Record all metrics for a single LLM request"""
        
        self.metrics["llm_requests_total"].labels(
            model=model, provider=provider, status=status
        ).inc()
        
        self.metrics["llm_tokens_total"].labels(
            model=model, type="input"
        ).inc(prompt_tokens)
        
        self.metrics["llm_tokens_total"].labels(
            model=model, type="output"
        ).inc(completion_tokens)
        
        self.metrics["llm_latency_seconds"].labels(
            model=model, provider=provider
        ).observe(duration_ms / 1000.0)
        
        if completion_tokens > 0 and duration_ms > 0:
            # Approximation: includes time-to-first-token. For true decode
            # speed use (duration - ttft). Track TTFT separately for streaming UX.
            tps = (completion_tokens / duration_ms) * 1000
            self.metrics["llm_tokens_per_second"].labels(
                model=model
            ).observe(tps)
        
        self.metrics["llm_cost_total"].labels(
            model=model, provider=provider
        ).inc(cost)
        
        self.metrics["llm_cost_per_request"].labels(
            model=model
        ).observe(cost)
        
        if error:
            self.metrics["llm_errors_total"].labels(
                model=model, error_type=error
            ).inc()

```

**Alert rules (Prometheus):**

```yaml
# prometheus-alerts.yml
groups:
  - name: llm_alerts
    rules:
      # High error rate (sum by model: the two metrics have different
      # label sets, so dividing them without aggregation matches nothing)
      - alert: LLMHighErrorRate
        expr: |
          sum by (model) (rate(llm_errors_total[5m]))
            / sum by (model) (rate(llm_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "LLM error rate > 5% for {{ $labels.model }}"
      
      # High latency
      - alert: LLMHighLatency
        expr: |
          histogram_quantile(0.99, sum by (le, model) (rate(llm_latency_seconds_bucket[5m]))) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency > 10s for {{ $labels.model }}"
      
      # Budget alert
      - alert: LLMBudgetThreshold
        expr: |
          sum(increase(llm_cost_total[1h])) * 730 > 8000  # last hour's spend x ~730 h/month
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Projected monthly cost > $8,000"
      
      # Circuit breaker open
      - alert: LLMCircuitBreakerOpen
        expr: llm_circuit_breaker_status == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker OPEN for {{ $labels.model }}"
      
      # Cache hit rate drop
      - alert: LLMCacheHitRateDrop
        expr: |
          sum(rate(llm_cache_hits_total[1h]))
            / (sum(rate(llm_cache_hits_total[1h])) + sum(rate(llm_cache_misses_total[1h]))) < 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Cache hit rate dropped below 10%"
      
      # Rate limiting spike
      - alert: LLMRateLimitSpike
        expr: sum by (model) (rate(llm_rate_limited_requests_total[5m])) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limiting: {{ $value }}/s for {{ $labels.model }}"
```

Also alert on **prompt-cache hit rate** (`cached_input` share of input tokens) dropping, and on **quality** signals from online evals (groundedness, task success on a sampled stream), since a silent model or prompt regression shows up in none of the infra metrics above.

---

## 6. Prompt Versioning & Management

Treat prompts like code: immutable versions, review, an eval run before promotion, and a pointer per environment that can be rolled back instantly. Store the **prompt version and exact model id on every trace** so you can attribute a regression. Many teams use a prompt-management tool (Langfuse, LangSmith, PromptLayer, Braintrust) or simply keep prompts in the repo and ship them with the code; a database registry like the one below matters when non-engineers edit prompts.

### Prompt Registry

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from typing import Optional
import hashlib
import json
import string

@dataclass
class PromptTemplate:
    """A versioned prompt template with metadata"""
    id: str
    name: str
    version: int                            # integer: "v10" < "v9" as strings
    template: str
    variables: list[str]
    model: str                              # Exact model id the prompt was evaluated on
    temperature: Optional[float] = None     # some models reject sampling params
    max_tokens: int = 1024
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    author: str = "system"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=lambda: {
        "avg_tokens": 0,
        "avg_latency_ms": 0,
        "success_rate": 1.0,
        "total_calls": 0,
    })

class PromptRegistry:
    """
    Versioned prompt management system.
    Stores prompt templates, manages versions, and tracks performance.
    """
    
    def __init__(self, redis_client, db_session):
        self.redis = redis_client
        self.db = db_session
        self._cache: dict[str, PromptTemplate] = {}
    
    async def register_prompt(
        self,
        name: str,
        template: str,
        variables: list[str],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        author: str = "system",
        description: str = "",
        tags: list[str] = None,
    ) -> PromptTemplate:
        """Register a new prompt template version"""
        
        # Generate ID and version
        prompt_id = f"prompt:{name}:{hashlib.md5(template.encode()).hexdigest()[:8]}"
        version = await self._next_version(name)
        
        prompt = PromptTemplate(
            id=prompt_id,
            name=name,
            version=version,
            template=template,
            variables=variables,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            author=author,
            description=description,
            tags=tags or [],
        )
        
        # Store in database
        await self.db.execute(
            """INSERT INTO prompt_templates 
               (id, name, version, template, variables, model, 
                temperature, max_tokens, author, description, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            prompt.id, prompt.name, prompt.version, prompt.template,
            json.dumps(prompt.variables), prompt.model,
            prompt.temperature, prompt.max_tokens,
            prompt.author, prompt.description,
            json.dumps(prompt.tags),
        )
        
        # Cache
        self._cache[prompt.id] = prompt
        await self.redis.setex(f"prompt:{prompt.id}", 3600, json.dumps(asdict(prompt)))
        
        return prompt
    
    async def get_prompt(
        self,
        name: str,
        version: Optional[str] = None,
        environment: str = "production",
    ) -> Optional[PromptTemplate]:
        """Get a prompt template by name and version"""
        
        # Try cache first
        cache_key = f"prompt:{name}:{version or 'latest'}:{environment}"
        cached = await self.redis.get(cache_key)
        if cached:
            return PromptTemplate(**json.loads(cached))
        
        # Query database
        if version:
            result = await self.db.fetchrow(
                """SELECT * FROM prompt_templates 
                   WHERE name = $1 AND version = $2
                   ORDER BY created_at DESC LIMIT 1""",
                name, version,
            )
        else:
            result = await self.db.fetchrow(
                """SELECT t.* FROM prompt_templates t
                   JOIN prompt_deployments d
                     ON d.name = t.name AND d.version = t.version
                   WHERE t.name = $1 AND d.environment = $2""",
                name, environment,
            )
        
        if result:
            prompt = PromptTemplate(**result)
            # Cache for next time
            await self.redis.setex(cache_key, 300, json.dumps(asdict(prompt)))
            return prompt
        
        return None
    
    async def render_prompt(
        self,
        name: str,
        variables: dict,
        version: Optional[str] = None,
    ) -> str:
        """Render a prompt template with variables"""
        prompt = await self.get_prompt(name, version)
        if not prompt:
            raise ValueError(f"Prompt '{name}' not found")
        
        # Validate all required variables are provided
        missing = [v for v in prompt.variables if v not in variables]
        if missing:
            raise ValueError(f"Missing variables: {missing}")
        
        # Render with string.Template ($var), not str.format: prompts often
        # contain literal JSON braces, which str.format treats as fields.
        return string.Template(prompt.template).substitute(variables)
    
    async def promote_version(
        self,
        name: str,
        version: int,
        environment: str = "production",
    ) -> None:
        """Point an environment at a version (rollback = promote the old one).

        A separate pointer table (name, environment) -> version avoids the bug
        of tagging rows: after a rollback, "latest row tagged production"
        would still return the newer, bad version.
        """
        await self.db.execute(
            """INSERT INTO prompt_deployments (name, environment, version, updated_at)
               VALUES ($1, $2, $3, NOW())
               ON CONFLICT (name, environment)
               DO UPDATE SET version = EXCLUDED.version, updated_at = NOW()""",
            name, environment, version,
        )
        # Invalidate cache
        await self.redis.delete(f"prompt:{name}:latest:{environment}")
    
    async def get_version_history(self, name: str) -> list[PromptTemplate]:
        """Get all versions of a prompt"""
        results = await self.db.fetch(
            """SELECT * FROM prompt_templates 
               WHERE name = $1 
               ORDER BY created_at DESC""",
            name,
        )
        return [PromptTemplate(**row) for row in results]
    
    async def _next_version(self, name: str) -> int:
        """Next integer version (enforce UNIQUE (name, version) in the DB to
        make concurrent registrations safe)."""
        last = await self.db.fetchval(
            "SELECT MAX(version) FROM prompt_templates WHERE name = $1",
            name,
        )
        return (last or 0) + 1

# ── Usage in orchestration ─────────────────────────────────
async def process_with_prompt(
    registry: PromptRegistry,
    prompt_name: str,
    variables: dict,
) -> str:
    """Process a request using a versioned prompt"""
    
    # Render the prompt
    rendered = await registry.render_prompt(
        name=prompt_name,
        variables=variables,
    )
    
    # Get prompt config
    prompt = await registry.get_prompt(prompt_name)
    
    # Make LLM call
    response = await llm_client.responses.create(
        model=prompt.model,
        input=rendered,
        max_output_tokens=prompt.max_tokens,
    )
    
    return response.output_text
```

---

## 7. A/B Testing Different Models

### Experiment Framework

Online experiments compare models or prompts on **real traffic**, but only after the candidate passes the offline eval suite. The metric that decides the winner must include **quality** (task success, user rating, escalation or retry rate, an LLM-judge score on a sample), not only latency, cost and error rate: a cheaper model with fewer errors can still give worse answers. Decide the primary metric, minimum detectable effect and sample size up front, and assign by user (not by request) so one user gets a consistent experience.

```python
from enum import Enum
from typing import Optional, Callable
import random

class ExperimentStatus(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"

@dataclass
class ModelExperiment:
    """A/B test configuration for comparing models"""
    id: str
    name: str
    control_model: str
    treatment_model: str
    traffic_percentage: float  # 0.0-1.0, percentage to treatment
    metrics: list[str]         # Which metrics to compare
    start_time: datetime
    min_sample_size: int = 1000
    status: ExperimentStatus = ExperimentStatus.RUNNING
    filters: Optional[dict] = None  # Optional filters (e.g., only complex queries)

class ABTestManager:
    """
    Manages A/B experiments between different models.
    Routes traffic according to experiment configuration and tracks results.
    """
    
    def __init__(self, redis_client, tracker: TokenUsageTracker):
        self.redis = redis_client
        self.tracker = tracker
        # In-process dict for brevity; with several replicas, load experiment
        # config from a shared store (or a feature-flag service) instead.
        self.experiments: dict[str, ModelExperiment] = {}
    
    async def create_experiment(
        self,
        name: str,
        control_model: str,
        treatment_model: str,
        traffic_percentage: float = 0.5,
        min_sample_size: int = 1000,
        filters: Optional[dict] = None,
    ) -> ModelExperiment:
        """Create a new A/B experiment"""
        experiment = ModelExperiment(
            id=str(uuid.uuid4()),
            name=name,
            control_model=control_model,
            treatment_model=treatment_model,
            traffic_percentage=traffic_percentage,
            min_sample_size=min_sample_size,
            start_time=datetime.now(UTC),
            filters=filters,
        )
        
        self.experiments[experiment.id] = experiment
        
        # Store in Redis for distributed coordination
        await self.redis.setex(
            f"abtest:{experiment.id}",
            86400 * 30,  # 30 days
            json.dumps(asdict(experiment), default=str),
        )
        
        return experiment
    
    def should_route_to_treatment(
        self,
        experiment_id: str,
        user_id: str,
    ) -> bool:
        """Determine if this request should go to treatment or control"""
        experiment = self.experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return False
        
        # Deterministic hash bucketing on user_id for stable assignment
        hash_val = int(hashlib.md5(
            f"{experiment_id}:{user_id}".encode()
        ).hexdigest(), 16) % 1000
        
        return (hash_val / 1000) < experiment.traffic_percentage
    
    async def record_result(
        self,
        experiment_id: str,
        user_id: str,
        model: str,
        metrics: dict,
    ) -> None:
        """Record result for an A/B experiment"""
        key = f"abtest:results:{experiment_id}:{model}"
        
        async with self.redis.pipeline(transaction=True) as pipe:
            # Increment counters
            await pipe.hincrby(key, "count", 1)
            await pipe.hincrbyfloat(key, "total_latency", metrics.get("latency_ms", 0))
            await pipe.hincrbyfloat(key, "total_cost", metrics.get("cost", 0))
            await pipe.hincrby(key, "total_tokens", metrics.get("total_tokens", 0))
            await pipe.hincrby(key, "errors", 1 if metrics.get("error") else 0)
            await pipe.hincrby(key, "successes", 1 if metrics.get("task_success") else 0)
            await pipe.expire(key, 86400 * 30)
            await pipe.execute()
    
    async def get_experiment_results(
        self,
        experiment_id: str,
    ) -> dict:
        """Get aggregated results for an experiment"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return {}
        
        results = {}
        for model in [experiment.control_model, experiment.treatment_model]:
            key = f"abtest:results:{experiment_id}:{model}"
            data = await self.redis.hgetall(key)
            
            if data:
                count = int(data.get(b"count", 0))
                results[model] = {
                    "count": count,
                    "avg_latency_ms": (
                        float(data.get(b"total_latency", 0)) / count
                        if count > 0 else 0
                    ),
                    "avg_cost": (
                        float(data.get(b"total_cost", 0)) / count
                        if count > 0 else 0
                    ),
                    "avg_tokens": (
                        int(data.get(b"total_tokens", 0)) / count
                        if count > 0 else 0
                    ),
                    "error_rate": (
                        int(data.get(b"errors", 0)) / count
                        if count > 0 else 0
                    ),
                    "successes": int(data.get(b"successes", 0)),
                }
        
        return {
            "experiment_id": experiment_id,
            "name": experiment.name,
            "status": experiment.status.value,
            "control_model": experiment.control_model,
            "treatment_model": experiment.treatment_model,
            "results": results,
        }
    
    async def complete_experiment(
        self,
        experiment_id: str,
        winner: Optional[str] = None,
    ) -> dict:
        """
        Complete an experiment and declare a winner.
        Automatically promotes the winning model to production config.
        """
        results = await self.get_experiment_results(experiment_id)
        experiment = self.experiments[experiment_id]
        
        if not winner:
            # Pick a winner only on a QUALITY metric with a significance test,
            # then apply cost/latency as tie-breakers or guardrails. Comparing
            # raw averages ("lower error rate wins") declares winners from noise.
            control = results.get(experiment.control_model, {})
            treatment = results.get(experiment.treatment_model, {})
            if min(control.get("count", 0), treatment.get("count", 0)) < experiment.min_sample_size:
                return {"winner": None, "reason": "insufficient sample", "results": results}
            quality = compare_proportions(              # e.g. two-proportion z-test
                control["successes"], control["count"],
                treatment["successes"], treatment["count"],
            )
            if quality.significant and quality.treatment_worse:
                winner = experiment.control_model
            elif not quality.treatment_worse and treatment["avg_cost"] < 0.8 * control["avg_cost"]:
                winner = experiment.treatment_model   # non-inferior quality, 20%+ cheaper
            else:
                winner = experiment.control_model
        
        experiment.status = ExperimentStatus.COMPLETED
        
        return {
            "winner": winner,
            "results": results,
            "recommendation": (
                f"Promote {winner} to production based on experiment results"
            ),
        }

# ── Example: compare the current small model with a cheaper candidate ──
async def run_ab_test():
    manager = ABTestManager(redis_client, token_tracker)
    
    experiment = await manager.create_experiment(
        name="simple-qa-model-comparison",
        control_model=CONFIG["small"],            # exact model ids from config
        treatment_model=CONFIG["small_candidate"],
        traffic_percentage=0.5,
        min_sample_size=5000,
        filters={"complexity": "simple"},
    )
    
    # In request handler:
    def handle_simple_qa(user_id: str, query: str):
        use_treatment = manager.should_route_to_treatment(
            experiment.id, user_id
        )
        model = experiment.treatment_model if use_treatment else experiment.control_model
        
        response = call_llm(model, query)
        
        asyncio.create_task(manager.record_result(
            experiment.id,
            user_id,
            model,
            {"latency_ms": response.latency, "cost": response.cost,
             "total_tokens": response.total_tokens,
             "task_success": response.judged_success},   # from evaluator / user signal
        ))
        
        return response
```

---

## 8. Tenant-Level Cost Allocation

### Usage-Based Billing

Use Redis counters for **real-time dashboards and quota checks**, but bill from a **durable, append-only usage ledger** (a database table or event stream such as Kafka → warehouse) with one row per call and an idempotency key. Redis is not a system of record: evictions, failovers and missed writes would silently change invoices. Reconcile the ledger against the providers' own usage and cost reports.

```python
@dataclass
class TenantUsage:
    """Aggregated usage data for a tenant"""
    tenant_id: str
    total_tokens: int = 0
    total_cost: float = 0.0
    total_requests: int = 0
    model_breakdown: dict[str, ModelUsage] = field(default_factory=dict)
    daily_usage: dict[str, float] = field(default_factory=dict)  # date → cost

class TenantCostAllocator:
    """
    Tracks LLM usage and cost per tenant for billing and chargeback.
    Essential for multi-tenant SaaS products using LLMs.
    """
    
    def __init__(self, db_session, redis_client):
        self.db = db_session
        self.redis = redis_client
    
    async def record_usage(
        self,
        tenant_id: str,
        user_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
    ) -> None:
        """Record LLM usage for a tenant"""
        
        now = datetime.now(UTC)
        date_key = now.strftime("%Y-%m-%d")
        
        # Redis: real-time counters for dashboards
        pipe = self.redis.pipeline()
        
        # Daily totals
        pipe.hincrbyfloat(
            f"tenant:{tenant_id}:cost:daily:{date_key}",
            "total_cost", cost,
        )
        pipe.hincrby(
            f"tenant:{tenant_id}:tokens:daily:{date_key}",
            "total_tokens", prompt_tokens + completion_tokens,
        )
        pipe.hincrby(
            f"tenant:{tenant_id}:requests:daily:{date_key}",
            "total_requests", 1,
        )
        
        # Monthly totals, with a per-model field in the SAME hash, so the
        # breakdown is for the billing month (not lifetime) and needs no SCAN
        month_key = now.strftime("%Y-%m")
        pipe.hincrbyfloat(
            f"tenant:{tenant_id}:cost:monthly:{month_key}",
            "total_cost", cost,
        )
        pipe.hincrbyfloat(
            f"tenant:{tenant_id}:cost:monthly:{month_key}",
            f"model:{model}", cost,
        )
        
        await pipe.execute()
        
        # Durable ledger write (the billing source of truth)
        await self._write_usage_record(
            tenant_id, user_id, model,
            prompt_tokens, completion_tokens, cost,
        )
    
    async def get_tenant_usage(
        self,
        tenant_id: str,
        start_date: str,
        end_date: str,
    ) -> TenantUsage:
        """Get aggregated usage for a tenant over a date range"""
        
        usage = TenantUsage(tenant_id=tenant_id)
        
        for date_key in self._date_range(start_date, end_date):
            # Get daily data from Redis
            daily_cost = await self.redis.hgetall(
                f"tenant:{tenant_id}:cost:daily:{date_key}"
            )
            daily_tokens = await self.redis.hgetall(
                f"tenant:{tenant_id}:tokens:daily:{date_key}"
            )
            daily_requests = await self.redis.hgetall(
                f"tenant:{tenant_id}:requests:daily:{date_key}"
            )
            
            if daily_cost:
                cost = float(daily_cost.get(b"total_cost", 0))
                usage.total_cost += cost
                usage.daily_usage[date_key] = cost
            
            if daily_tokens:
                usage.total_tokens += int(daily_tokens.get(b"total_tokens", 0))
            
            if daily_requests:
                usage.total_requests += int(daily_requests.get(b"total_requests", 0))
        
        # Model breakdown comes from the monthly hash's "model:*" fields
        # (or, better, from the ledger in the warehouse)
        
        return usage
    
    async def get_billing_report(
        self,
        tenant_id: str,
        month: str,
    ) -> dict:
        """Generate a billing report for a tenant"""
        monthly_data = await self.redis.hgetall(
            f"tenant:{tenant_id}:cost:monthly:{month}"
        )
        
        total_cost = float(monthly_data.get(b"total_cost", 0))
        
        # Per-model breakdown for THIS month
        model_costs = {
            k.decode().removeprefix("model:"): float(v)
            for k, v in monthly_data.items()
            if k.startswith(b"model:")
        }
        
        return {
            "tenant_id": tenant_id,
            "billing_period": month,
            "total_cost": round(total_cost, 4),
            "model_breakdown": model_costs,
            "estimated_invoice": round(total_cost * 1.2, 2),  # 20% markup
        }
```

---

## 9. Logging & Distributed Tracing

### Structured LLM Logging

```python
import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# ── Structured logging configuration ──────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ── OpenTelemetry tracing ─────────────────────────────────
class LLMTracer:
    """
    Distributed tracing for LLM calls.
    Traces each request through routing → LLM call → fallback → caching.
    """
    
    def __init__(self, service_name: str = "multi-llm-service"):
        self.tracer = trace.get_tracer(service_name)
        self._setup_exporters()
    
    def _setup_exporters(self):
        """Set up OpenTelemetry exporters"""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        
        provider = TracerProvider()
        processor = BatchSpanProcessor(
            OTLPSpanExporter(endpoint="http://otel-collector:4317")
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
    
    @contextmanager
    def trace_llm_call(
        self,
        request_id: str,
        provider: str,
        model: str,
        tenant_id: Optional[str] = None,
    ):
        """Create a span for an LLM call using the OpenTelemetry GenAI
        semantic conventions (still "Development" status)."""
        with self.tracer.start_as_current_span(
            f"chat {model}",                       # "{operation} {model}"
            kind=trace.SpanKind.CLIENT,
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": provider,  # e.g. "openai", "anthropic"
                "gen_ai.request.model": model,
                "app.request_id": request_id,
                "app.tenant_id": tenant_id or "",  # app-specific attrs: own namespace
            },
        ) as span:
            # start_as_current_span records exceptions and sets ERROR status
            # automatically when one propagates out of the block.
            yield span

    @staticmethod
    def record_response(span, response_model: str, input_tokens: int,
                        output_tokens: int, finish_reason: str):
        span.set_attribute("gen_ai.response.model", response_model)
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.response.finish_reasons", [finish_reason])
    
    def log_llm_call(
        self,
        request_id: str,
        model: str,
        provider: str,
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cost: float,
        error: Optional[str] = None,
        cache_hit: bool = False,
        fallback_chain: Optional[list] = None,
    ):
        """Log a structured log entry for an LLM call"""
        
        log_data = {
            "event": "llm_call",
            "request_id": request_id,
            "model": model,
            "provider": provider,
            "status": status,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_ms": round(latency_ms, 2),
            "cost": round(cost, 6),
            "cache_hit": cache_hit,
        }
        
        if error:
            log_data["error"] = error
        
        if fallback_chain:
            log_data["fallback_chain"] = fallback_chain
        
        if status == "success":
            logger.info("LLM call completed", **log_data)
        else:
            logger.error("LLM call failed", **log_data)

# ── Example: Structured logging in orchestrator ──────────
class ObservableLLMOrchestrator:
    """Orchestrator with logging and tracing built in"""
    
    def __init__(self):
        self.tracer = LLMTracer()
        self.logger = structlog.get_logger()
    
    async def process(
        self,
        request: LLMRequest,
        user_id: str,
        tenant_id: str,
    ) -> dict:
        request_id = str(uuid.uuid4())
        
        start = time.perf_counter()
        with self.tracer.trace_llm_call(
            request_id, request.provider, request.model, tenant_id
        ) as span:
            try:
                
                # Route and execute
                response = await self._execute(request)
                
                latency = (time.perf_counter() - start) * 1000
                
                # Structured log
                self.tracer.log_llm_call(
                    request_id=request_id,
                    model=response.model_used,
                    provider=response.provider,
                    status="success",
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=latency,
                    cost=response.cost,
                    cache_hit=response.from_cache,
                    fallback_chain=response.fallback_chain,
                )
                
                return response
                
            except Exception as e:
                self.tracer.log_llm_call(
                    request_id=request_id,
                    model=request.model,
                    provider=request.provider,
                    status="error",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    cost=0.0,
                    error=str(e),
                )
                span.set_attribute("error.type", type(e).__name__)
                raise
```

---

## 10. Production Dashboard

### Grafana Dashboard Queries

```python
# ── Grafana dashboard JSON (abbreviated queries) ─────────
DASHBOARD_QUERIES = {
    # 1. Overview Panel
    "total_requests": """
        sum(rate(llm_requests_total[5m]))
    """,
    
    # 2. Requests by Model
    "requests_by_model": """
        sum by (model) (rate(llm_requests_total[5m]))
    """,
    
    # 3. Token Usage
    "tokens_per_minute": """
        sum(rate(llm_tokens_total[1m]))
    """,
    
    # 4. Cost Rate (rate() is per second; increase() gives $ per hour)
    "cost_per_hour": """
        sum(increase(llm_cost_total[1h]))
    """,
    
    # 5. Latency P99 by Model
    "latency_by_model": """
        histogram_quantile(
            0.99,
            sum by (le, model) (rate(llm_latency_seconds_bucket[5m]))
        )
    """,
    
    # 6. Error Rate
    "error_rate": """
        sum(rate(llm_errors_total[5m])) / sum(rate(llm_requests_total[5m]))
    """,

    # 6b. Prompt-cache share of input tokens
    "prompt_cache_hit_ratio": """
        sum(rate(llm_tokens_total{type="cached_input"}[15m]))
          / sum(rate(llm_tokens_total{type=~"input|cached_input"}[15m]))
    """,
    
    # 7. Cache Hit Rate
    "cache_hit_rate": """
        sum(rate(llm_cache_hits_total[5m])) / (
            sum(rate(llm_cache_hits_total[5m])) + 
            sum(rate(llm_cache_misses_total[5m]))
        )
    """,
    
    # 8. Circuit Breaker Status
    "circuit_breakers": """
        llm_circuit_breaker_status
    """,
    
    # 9. Top Costs by Model over the dashboard range (raw counters reset
    #    on restart and count since process start, so use increase())
    "top_costs": """
        topk(5, sum by (model) (increase(llm_cost_total[$__range])))
    """,
    
    # 10. Concurrency by Model
    "concurrency": """
        llm_concurrent_requests
    """,
}
```

---

## Production Checklist

- [ ] **Token monitoring**: Input, cached input, cache writes, output and reasoning tokens per call, from provider-reported usage
- [ ] **Prompt caching**: Stable prefixes cached at the provider; cache-hit ratio monitored
- [ ] **Rate limiting**: Atomic, shared (Redis) per-user and per-model RPM/TPM limits; provider rate-limit headers honoured
- [ ] **Concurrency control**: Per-model semaphores with queue wait monitoring
- [ ] **Response caching**: Exact match by default; semantic only on routes where reuse is safe, scoped by tenant and prompt version
- [ ] **Retry policy**: Exponential backoff with jitter, per-error-type configs
- [ ] **Circuit breaker**: Open after N consecutive failures, half-open retry
- [ ] **Budget enforcement**: Per-request, session, daily, monthly token budgets
- [ ] **Alerting**: Error rate, latency, cost, cache hit rate, circuit breaker alerts
- [ ] **Prompt versioning**: Immutable versions, environment pointers, instant rollback, version on every trace
- [ ] **Evals as a release gate**: Offline suite on every prompt/model change; online quality sampling after release
- [ ] **A/B testing**: Quality-based success metric, pre-registered sample size, per-user assignment
- [ ] **Cost allocation**: Durable usage ledger for billing; Redis only for real-time counters
- [ ] **Logging**: Structured JSON logs with correlation IDs
- [ ] **Tracing**: OpenTelemetry with GenAI semantic conventions through the entire pipeline
- [ ] **Dashboard**: Real-time Grafana dashboard with key metrics

---

> **Related:** [08_MULTI_LLM_ARCHITECTURE.md](./08_MULTI_LLM_ARCHITECTURE.md) — Routing, cost management, fallback chains
> **Related:** [04_AGENT_PRODUCTION_ARCHITECTURE.md](./04_AGENT_PRODUCTION_ARCHITECTURE.md) — General agent production architecture
> **Related:** [07_AGENT_OBSERVABILITY.md](./07_AGENT_OBSERVABILITY.md) — General agent observability patterns
