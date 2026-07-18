# 📊 Multi-LLM Production Operations — Monitoring, Rate Limiting, Caching & Reliability

> **Target:** Principal Engineer | **Focus:** Production operational excellence for multi-LLM deployments
> *Companion to [08_MULTI_LLM_ARCHITECTURE.md](./08_MULTI_LLM_ARCHITECTURE.md) which covers routing, cost management, and fallback architecture*

---

## Table of Contents

1. [Token Usage Monitoring](#1-token-usage-monitoring)
2. [Rate Limiting & Concurrency Control](#2-rate-limiting--concurrency-control)
3. [Response Caching Strategies](#3-response-caching-strategies)
4. [Retry Policies & Exponential Backoff](#4-retry-policies--exponential-backoff)
5. [Observability & Alerting](#5-observability--alerting)
6. [Prompt Versioning & Management](#6-prompt-versioning--management)
7. [A/B Testing Different Models](#7-ab-testing-different-models)
8. [Tenant-Level Cost Allocation](#8-tenant-level-cost-allocation)
9. [Logging & Distributed Tracing](#9-logging--distributed-tracing)
10. [Production Dashboard](#10-production-dashboard)

---

## 1. Token Usage Monitoring

### Granular Token Tracking

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import json

@dataclass
class TokenUsageRecord:
    """Granular record of a single LLM API call's token usage"""
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    latency_ms: float
    endpoint: str                          # e.g., /v1/chat/completions
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    request_id: Optional[str] = None
    prompt_id: Optional[str] = None        # Which prompt template was used
    cache_hit: bool = False
    status_code: int = 200
    error_type: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def tokens_per_second(self) -> float:
        if self.latency_ms > 0:
            return (self.completion_tokens / self.latency_ms) * 1000
        return 0.0

class PrometheusMetrics:
    """Wrapper around prometheus_client for LLM-specific metrics.
    
    In production, use prometheus_client directly:
        from prometheus_client import Counter, Histogram, Gauge
    """
    def create_counter(self, name, description, labels=None):
        import prometheus_client
        return prometheus_client.Counter(name, description, labels or [])
    
    def create_histogram(self, name, description, labels=None, buckets=None):
        import prometheus_client
        return prometheus_client.Histogram(name, description, labels or [], buckets=buckets)
    
    def increment_counter(self, name, value, labels=None):
        # In production, get the counter by name and call .inc(value)
        pass
    
    def observe_histogram(self, name, value, labels=None):
        # In production, get the histogram by name and call .observe(value)
        pass

class TokenUsageTracker:
    """
    Real-time token usage tracking with sliding window aggregation.
    Exposes metrics for Prometheus and dashboards.
    """
    
    def __init__(self):
        self._records: list[TokenUsageRecord] = []
        self._lock = asyncio.Lock()
        self._prometheus = PrometheusMetrics()
        
        # Pre-register Prometheus metrics
        self._prometheus.create_counter(
            "llm_tokens_total",
            "Total tokens used across all models",
            labels=["model", "provider", "type"],  # type: prompt|completion
        )
        self._prometheus.create_counter(
            "llm_requests_total",
            "Total LLM API requests",
            labels=["model", "provider", "status"],
        )
        self._prometheus.create_histogram(
            "llm_latency_seconds",
            "LLM API latency in seconds",
            labels=["model", "provider"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
        )
        self._prometheus.create_histogram(
            "llm_tokens_per_request",
            "Tokens per LLM request",
            labels=["model", "provider"],
            buckets=[100, 500, 1000, 2000, 4000, 8000, 16000, 32000],
        )
    
    async def track(self, record: TokenUsageRecord) -> None:
        """Track a single LLM API call"""
        async with self._lock:
            self._records.append(record)
            
            # Update Prometheus metrics
            self._prometheus.increment_counter(
                "llm_tokens_total",
                record.prompt_tokens,
                labels={"model": record.model, "provider": record.provider, "type": "prompt"},
            )
            self._prometheus.increment_counter(
                "llm_tokens_total",
                record.completion_tokens,
                labels={"model": record.model, "provider": record.provider, "type": "completion"},
            )
            self._prometheus.increment_counter(
                "llm_requests_total",
                1,
                labels={
                    "model": record.model,
                    "provider": record.provider,
                    "status": "success" if record.status_code < 400 else "error",
                },
            )
            self._prometheus.observe_histogram(
                "llm_latency_seconds",
                record.latency_ms / 1000.0,
                labels={"model": record.model, "provider": record.provider},
            )
            self._prometheus.observe_histogram(
                "llm_tokens_per_request",
                record.total_tokens,
                labels={"model": record.model, "provider": record.provider},
            )
    
    def get_current_minute_rate(self, model: Optional[str] = None) -> dict:
        """Get tokens per minute rate for real-time monitoring"""
        now = datetime.utcnow()
        one_minute_ago = now - timedelta(minutes=1)
        
        recent = [
            r for r in self._records
            if r.timestamp >= one_minute_ago
            and (model is None or r.model == model)
        ]
        
        return {
            "tokens_per_minute": sum(r.total_tokens for r in recent),
            "requests_per_minute": len(recent),
            "cost_per_minute": sum(r.cost for r in recent),
            "average_latency_ms": (
                sum(r.latency_ms for r in recent) / len(recent)
                if recent else 0
            ),
            "p99_latency_ms": self._calculate_percentile(
                [r.latency_ms for r in recent], 99
            ),
            "error_rate": (
                sum(1 for r in recent if r.error_type) / len(recent)
                if recent else 0
            ),
        }
    
    def get_model_comparison(self) -> list[dict]:
        """Compare performance across models for cost optimization"""
        from collections import defaultdict
        
        model_stats = defaultdict(lambda: {
            "total_tokens": 0, "total_cost": 0.0,
            "total_requests": 0, "total_latency": 0.0,
            "errors": 0, "cache_hits": 0,
        })
        
        for r in self._records:
            stats = model_stats[r.model]
            stats["total_tokens"] += r.total_tokens
            stats["total_cost"] += r.cost
            stats["total_requests"] += 1
            stats["total_latency"] += r.latency_ms
            if r.error_type:
                stats["errors"] += 1
            if r.cache_hit:
                stats["cache_hits"] += 1
        
        return [
            {
                "model": model,
                **stats,
                "avg_latency_ms": stats["total_latency"] / stats["total_requests"],
                "avg_cost_per_request": stats["total_cost"] / stats["total_requests"],
                "cost_per_1k_tokens": (
                    (stats["total_cost"] / stats["total_tokens"]) * 1000
                    if stats["total_tokens"] > 0 else 0
                ),
                "error_rate": stats["errors"] / stats["total_requests"],
                "cache_hit_rate": stats["cache_hits"] / stats["total_requests"],
            }
            for model, stats in model_stats.items()
        ]
```

### Streaming Token Counter

```python
class StreamingTokenCounter:
    """
    Counts tokens in streaming responses without buffering.
    Uses tiktoken for accurate tokenization.
    """
    
    def __init__(self, model: str = "gpt-4"):
        import tiktoken
        self.encoding = tiktoken.encoding_for_model(model)
        self.total_tokens = 0
        self._buffer = ""
    
    async def count_chunk(self, chunk: str) -> int:
        """
        Count tokens in a streaming chunk.
        Returns cumulative token count so far.
        """
        self._buffer += chunk
        # Tokenize in small batches to avoid OOM on long streams
        if len(self._buffer) >= 1000:
            tokens = self.encoding.encode(self._buffer)
            self.total_tokens += len(tokens)
            self._buffer = ""  # Clear buffer after counting
        return self.total_tokens
    
    def finalize(self) -> int:
        """Count remaining buffered tokens"""
        if self._buffer:
            tokens = self.encoding.encode(self._buffer)
            self.total_tokens += len(tokens)
            self._buffer = ""
        return self.total_tokens

# ── Usage in streaming response ────────────────────────────
@app.post("/chat/stream")
async def stream_chat(request: ChatRequest):
    counter = StreamingTokenCounter()
    
    async def generate():
        async for chunk in llm.stream(request.messages):
            token_count = await counter.count_chunk(chunk)
            yield f"data: {json.dumps({'content': chunk, 'tokens': token_count})}\n\n"
        
        total = counter.finalize()
        yield f"data: {json.dumps({'done': True, 'total_tokens': total})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### Token Budget Enforcement

```python
class TokenBudgetEnforcer:
    """
    Enforces token budgets at multiple levels:
    - Per request
    - Per user/session
    - Per tenant
    - Global (monthly)
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check_request_budget(
        self,
        user_id: str,
        estimated_tokens: int,
        max_tokens_per_request: int = 32000,
    ) -> bool:
        """Check if a single request exceeds per-request limits"""
        if estimated_tokens > max_tokens_per_request:
            raise TokenBudgetExceeded(
                f"Request exceeds max tokens per request "
                f"({estimated_tokens} > {max_tokens_per_request})"
            )
        return True
    
    async def check_session_budget(
        self,
        user_id: str,
        estimated_tokens: int,
        max_tokens_per_session: int = 100_000,
        session_window: int = 3600,
    ) -> bool:
        """
        Check if adding this request would exceed session budget.
        Uses sliding window to track recent token usage.
        """
        key = f"token_budget:session:{user_id}"
        now = int(datetime.utcnow().timestamp())
        
        async with self.redis.pipeline(transaction=True) as pipe:
            # Remove expired entries
            await pipe.zremrangebyscore(key, 0, now - session_window)
            # Get current usage
            await pipe.zcard(key)
            result = await pipe.execute()
            
            current_count = result[1]
            if current_count and int(current_count) + estimated_tokens > max_tokens_per_session:
                return False
            
            # Add current estimated tokens
            await pipe.zadd(key, {str(now): now + estimated_tokens})
            await pipe.expire(key, session_window)
            await pipe.execute()
        
        return True
    
    async def check_daily_budget(
        self,
        user_id: str,
        estimated_tokens: int,
        daily_limit: int = 1_000_000,
    ) -> bool:
        """Check daily token budget per user"""
        key = f"token_budget:daily:{user_id}:{datetime.utcnow().strftime('%Y%m%d')}"
        
        current = await self.redis.get(key)
        current = int(current) if current else 0
        
        if current + estimated_tokens > daily_limit:
            return False
        
        await self.redis.incrby(key, estimated_tokens)
        await self.redis.expire(key, 86400)  # 24 hours
        return True
    
    async def check_global_budget(
        self,
        estimated_tokens: int,
        monthly_budget_tokens: int = 50_000_000,
    ) -> bool:
        """Check global monthly token budget"""
        key = f"token_budget:monthly:{datetime.utcnow().strftime('%Y%m')}"
        
        current = await self.redis.get(key)
        current = int(current) if current else 0
        
        if current + estimated_tokens > monthly_budget_tokens:
            return False
        
        await self.redis.incrby(key, estimated_tokens)
        await self.redis.expire(key, 31 * 86400)  # ~1 month
        return True

# ── Usage in orchestration ─────────────────────────────────
class TokenAwareOrchestrator:
    """Orchestrator that respects token budgets at all levels"""
    
    def __init__(
        self,
        budget_enforcer: TokenBudgetEnforcer,
        usage_tracker: TokenUsageTracker,
    ):
        self.budget = budget_enforcer
        self.tracker = usage_tracker
    
    async def process(
        self,
        request: MultiLLMRequest,
        user_id: str,
        tenant_id: str,
    ) -> LLMResponse:
        # Estimate tokens from prompt length
        estimated_tokens = estimate_tokens(request.prompt)
        
        # Check all budget levels
        await self.budget.check_request_budget(user_id, estimated_tokens)
        
        if not await self.budget.check_session_budget(user_id, estimated_tokens):
            return self._budget_exceeded_response("Session token limit reached")
        
        if not await self.budget.check_daily_budget(user_id, estimated_tokens):
            return self._budget_exceeded_response("Daily token limit reached")
        
        if not await self.budget.check_global_budget(estimated_tokens):
            return self._budget_exceeded_response("Global token limit reached")
        
        # Proceed with LLM call
        start = time.perf_counter()
        response = await self._call_llm(request)
        latency = (time.perf_counter() - start) * 1000
        
        # Track actual usage
        await self.tracker.track(TokenUsageRecord(
            model=request.model,
            provider=request.provider,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            cost=calculate_cost(response.usage),
            latency_ms=latency,
            endpoint=request.endpoint,
            user_id=user_id,
            tenant_id=tenant_id,
        ))
        
        return response
```

---

## 2. Rate Limiting & Concurrency Control

### Multi-Layer Rate Limiting

```python
import time
from enum import Enum
from typing import Optional

class RateLimitTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    INTERNAL = "internal"

class RateLimitConfig:
    """Tiered rate limit configuration"""
    
    # Tokens per minute, requests per minute, concurrent requests
    TIERS = {
        RateLimitTier.FREE:       {"tpm": 10_000,   "rpm": 20,    "concurrent": 1},
        RateLimitTier.PRO:        {"tpm": 100_000,  "rpm": 200,   "concurrent": 5},
        RateLimitTier.ENTERPRISE: {"tpm": 1_000_000,"rpm": 2000,  "concurrent": 50},
        RateLimitTier.INTERNAL:   {"tpm": 10_000_000,"rpm": 10000,"concurrent": 200},
    }

class MultiLayerRateLimiter:
    """
    Rate limits at multiple levels:
    1. Global (across all users)
    2. Per model (e.g., GPT-4, Claude)
    3. Per user/API key
    4. Per IP address
    
    Uses token bucket + sliding window for accuracy.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check_rate_limit(
        self,
        user_id: str,
        model: str,
        estimated_tokens: int,
        tier: RateLimitTier = RateLimitTier.FREE,
        ip_address: Optional[str] = None,
    ) -> RateLimitResult:
        """Check all rate limit layers"""
        
        config = RateLimitConfig.TIERS[tier]
        now = int(time.time())
        
        # Build all rate limit keys
        keys = {
            "global:rpm": f"ratelimit:global:rpm:{now // 60}",
            "global:tpm": f"ratelimit:global:tpm:{now // 60}",
            f"model:{model}:rpm": f"ratelimit:model:{model}:rpm:{now // 60}",
            f"model:{model}:tpm": f"ratelimit:model:{model}:tpm:{now // 60}",
            f"user:{user_id}:rpm": f"ratelimit:user:{user_id}:rpm:{now // 60}",
            f"user:{user_id}:tpm": f"ratelimit:user:{user_id}:tpm:{now // 60}",
        }
        
        if ip_address:
            keys[f"ip:{ip_address}:rpm"] = f"ratelimit:ip:{ip_address}:rpm:{now // 60}"
        
        # Check all limits in a single pipeline
        async with self.redis.pipeline(transaction=True) as pipe:
            for key in keys.values():
                await pipe.get(key)
            results = await pipe.execute()
        
        # Parse results
        limits = {
            "global:rpm": {"current": int(results[0] or 0), "max": 100000},
            "global:tpm": {"current": int(results[1] or 0), "max": 50_000_000},
            f"model:{model}:rpm": {"current": int(results[2] or 0), "max": config["rpm"]},
            f"model:{model}:tpm": {"current": int(results[3] or 0), "max": config["tpm"]},
            f"user:{user_id}:rpm": {"current": int(results[4] or 0), "max": config["rpm"]},
            f"user:{user_id}:tpm": {"current": int(results[5] or 0), "max": config["tpm"]},
        }
        
        if ip_address:
            limits[f"ip:{ip_address}:rpm"] = {
                "current": int(results[6] or 0), "max": 1000,
            }
        
        # Check for exceeded limits
        exceeded = []
        for name, info in limits.items():
            if info["current"] >= info["max"]:
                exceeded.append(name)
        
        if exceeded:
            return RateLimitResult(
                allowed=False,
                exceeded_limits=exceeded,
                retry_after=60 - (now % 60),
                limits=limits,
            )
        
        # Increment counters
        async with self.redis.pipeline(transaction=True) as pipe:
            for key in keys.values():
                await pipe.incr(key)
                await pipe.expire(key, 120)
            await pipe.execute()
        
        return RateLimitResult(allowed=True, limits=limits)
    
    async def check_concurrency_limit(
        self,
        user_id: str,
        model: str,
        tier: RateLimitTier,
    ) -> bool:
        """Check concurrent request limits using Redis semaphore"""
        max_concurrent = RateLimitConfig.TIERS[tier]["concurrent"]
        key = f"concurrent:{user_id}:{model}"
        
        current = await self.redis.incr(key)
        await self.redis.expire(key, 30)  # Auto-cleanup after 30s
        
        if current > max_concurrent:
            await self.redis.decr(key)
            return False
        
        return True
    
    async def release_concurrency(self, user_id: str, model: str):
        """Release concurrency slot"""
        key = f"concurrent:{user_id}:{model}"
        await self.redis.decr(key)

# ── Rate limit middleware for FastAPI ──────────────────────
class LLMRateLimitMiddleware:
    """Middleware that enforces LLM rate limits"""
    
    def __init__(self, limiter: MultiLayerRateLimiter):
        self.limiter = limiter
    
    async def __call__(self, request: Request, call_next):
        # Skip rate limiting for non-LLM endpoints
        if not request.url.path.startswith("/api/v1/llm/"):
            return await call_next(request)
        
        user_id = request.state.user.id
        model = request.headers.get("X-Model", "gpt-4o-mini")
        tier = request.state.user.tier
        
        result = await self.limiter.check_rate_limit(
            user_id=user_id,
            model=model,
            estimated_tokens=estimate_tokens_from_request(request),
            tier=tier,
            ip_address=request.client.host,
        )
        
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded: {', '.join(result.exceeded_limits)}",
                    "retry_after_seconds": result.retry_after,
                },
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(max(
                        info["max"] for info in result.limits.values()
                    )),
                    "X-RateLimit-Remaining": "0",
                },
            )
        
        # Set rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max(
            info["max"] for info in result.limits.values()
        ))
        
        return response
```

### Concurrency Pool Management

```python
import asyncio
from typing import Optional, Callable, Awaitable

class LLMConnectionPool:
    """
    Manages concurrent LLM API connections per model/provider.
    Prevents overwhelming any single provider while maximizing throughput.
    """
    
    def __init__(self):
        self._pools: dict[str, asyncio.Semaphore] = {}
        self._max_concurrent = {
            "gpt-4o": 50,
            "gpt-4o-mini": 200,
            "claude-4-sonnet": 30,
            "claude-4-opus": 10,
            "deepseek-coder-v3": 100,
        }
        self._queue_sizes: dict[str, asyncio.Queue] = {}
        self._metrics = PrometheusMetrics()
    
    def get_semaphore(self, model: str) -> asyncio.Semaphore:
        """Get or create a semaphore for a model"""
        if model not in self._pools:
            max_conn = self._max_concurrent.get(model, 20)
            self._pools[model] = asyncio.Semaphore(max_conn)
        return self._pools[model]
    
    async def execute(
        self,
        model: str,
        call_fn: Callable[..., Awaitable],
        *args,
        timeout: float = 30.0,
        **kwargs,
    ) -> Any:
        """
        Execute an LLM call with concurrency control.
        Waits for a slot if the model is at capacity.
        """
        semaphore = self.get_semaphore(model)
        
        start = time.perf_counter()
        
        try:
            async with semaphore:
                wait_time = time.perf_counter() - start
                
                # Track queue wait time
                self._metrics.observe_histogram(
                    "llm_queue_wait_seconds",
                    wait_time,
                    labels={"model": model},
                )
                
                # Execute with timeout
                result = await asyncio.wait_for(
                    call_fn(*args, **kwargs),
                    timeout=timeout,
                )
                
                return result
                
        except asyncio.TimeoutError:
            self._metrics.increment_counter(
                "llm_timeouts_total",
                1,
                labels={"model": model},
            )
            raise LLMTimeoutError(f"LLM call to {model} timed out after {timeout}s")
    
    async def get_pool_stats(self) -> dict:
        """Get current pool utilization statistics"""
        stats = {}
        for model, semaphore in self._pools.items():
            max_conn = self._max_concurrent.get(model, 20)
            available = semaphore._value
            stats[model] = {
                "max_concurrent": max_conn,
                "current_used": max_conn - available,
                "available": available,
                "utilization_pct": ((max_conn - available) / max_conn) * 100,
            }
        return stats
    
    def update_max_concurrent(self, model: str, new_max: int):
        """Dynamically adjust concurrency limits based on provider health"""
        # Create new semaphore with updated max
        old = self._pools.get(model)
        self._max_concurrent[model] = new_max
        self._pools[model] = asyncio.Semaphore(new_max)
        
        if old:
            # Release any acquired permits to the new semaphore
            # (This is a simplification; production needs careful migration)
            pass

# ── Rate-limited HTTPX client for LLM calls ────────────────
class RateLimitedLLMClient:
    """
    HTTPX client with automatic retry and rate limit handling.
    Respects Retry-After headers from LLM providers.
    """
    
    def __init__(self, pool: LLMConnectionPool):
        self.pool = pool
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(
                max_keepalive_connections=50,
                max_connections=200,
            ),
        )
        self._rate_limit_state: dict[str, datetime] = {}  # model → until
    
    async def call(
        self,
        model: str,
        provider_url: str,
        headers: dict,
        payload: dict,
    ) -> httpx.Response:
        """Make a rate-limited LLM API call"""
        
        # Check if we're in a rate limit cool-down for this model
        if model in self._rate_limit_state:
            until = self._rate_limit_state[model]
            if datetime.utcnow() < until:
                wait = (until - datetime.utcnow()).total_seconds()
                await asyncio.sleep(wait)
        
        # Execute via connection pool
        return await self.pool.execute(
            model,
            self._do_call,
            provider_url,
            headers,
            payload,
        )
    
    async def _do_call(
        self,
        url: str,
        headers: dict,
        payload: dict,
    ) -> httpx.Response:
        response = await self.client.post(url, headers=headers, json=payload)
        
        # Handle rate limit response
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "5")
            self._rate_limit_state[payload.get("model", "unknown")] = (
                datetime.utcnow() + timedelta(seconds=int(retry_after))
            )
            raise RateLimitHit(retry_after=int(retry_after))
        
        response.raise_for_status()
        return response
```

---

## 3. Response Caching Strategies

### Semantic Caching with Embeddings

```python
import hashlib
import numpy as np
from typing import Optional

class SemanticLLMCache:
    """
    Caches LLM responses based on semantic similarity.
    Instead of exact match, uses embeddings to find similar queries.
    Critical for production: avoids redundant LLM calls for similar prompts.
    """
    
    def __init__(
        self,
        redis_client,
        embedding_model: str = "text-embedding-3-small",
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
    ):
        self.redis = redis_client
        self.embedding_model = embedding_model
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl_seconds
    
    async def get(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
    ) -> Optional[dict]:
        """Check cache for semantically similar query"""
        
        # Only cache deterministic responses
        if temperature > 0.1:
            return None
        
        # Compute embedding for the query
        query_embedding = await self._get_embedding(
            self._serialize_messages(messages)
        )
        
        # Search for similar cached queries
        similar = await self._search_similar(
            query_embedding, model, top_k=1
        )
        
        if similar:
            cached_result, similarity = similar[0]
            if similarity >= self.similarity_threshold:
                return cached_result
        
        return None
    
    async def set(
        self,
        messages: list[dict],
        response: dict,
        model: str,
        temperature: float,
    ) -> None:
        """Cache a response for future use"""
        if temperature > 0.1:
            return  # Don't cache non-deterministic responses
        
        key = self._make_key(messages, model)
        embedding = await self._get_embedding(
            self._serialize_messages(messages)
        )
        
        # Store response
        await self.redis.setex(
            f"llm_cache:response:{key}",
            self.ttl,
            json.dumps(response),
        )
        
        # Store embedding for similarity search
        await self.redis.setex(
            f"llm_cache:embedding:{key}",
            self.ttl,
            json.dumps(embedding.tolist()),
        )
        
        # Add to search index
        await self.redis.sadd(
            f"llm_cache:model:{model}:keys",
            key,
        )
        await self.redis.expire(
            f"llm_cache:model:{model}:keys",
            self.ttl,
        )
    
    async def _search_similar(
        self,
        query_embedding: np.ndarray,
        model: str,
        top_k: int = 5,
    ) -> list[tuple[dict, float]]:
        """Search for similar cached responses"""
        keys = await self.redis.smembers(
            f"llm_cache:model:{model}:keys"
        )
        
        if not keys:
            return []
        
        results = []
        for key in keys:
            # Get stored embedding
            embedding_data = await self.redis.get(
                f"llm_cache:embedding:{key}"
            )
            if not embedding_data:
                continue
            
            stored_embedding = np.array(json.loads(embedding_data))
            
            # Compute cosine similarity
            similarity = np.dot(query_embedding, stored_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
            )
            
            if similarity >= self.similarity_threshold:
                response_data = await self.redis.get(
                    f"llm_cache:response:{key}"
                )
                if response_data:
                    results.append((json.loads(response_data), float(similarity)))
        
        # Return top-k sorted by similarity
        results.sort(key=lambda x: -x[1])
        return results[:top_k]
    
    def _make_key(self, messages: list[dict], model: str) -> str:
        """Create a deterministic key from messages"""
        serialized = self._serialize_messages(messages)
        return hashlib.sha256(
            f"{model}:{serialized}".encode()
        ).hexdigest()[:16]
    
    def _serialize_messages(self, messages: list[dict]) -> str:
        """Serialize messages deterministically"""
        return json.dumps(messages, sort_keys=True)
    
    async def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text using configured model"""
        response = await openai_client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return np.array(response.data[0].embedding)
    
    async def invalidate_by_prefix(self, prefix: str):
        """Invalidate cache entries matching a prefix (e.g., user_id)"""
        pattern = f"llm_cache:*:{prefix}*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break
```

### Exact-Match Cache with TTL

```python
class ExactMatchLLMCache:
    """
    Simple exact-match cache for LLM responses.
    Useful for deterministic queries (temperature=0) with repeated prompts.
    10-50x latency reduction for cached queries.
    """
    
    def __init__(self, redis_client, default_ttl: int = 3600):
        self.redis = redis_client
        self.default_ttl = default_ttl
        self.hit_counter = 0
        self.miss_counter = 0
    
    def _build_key(
        self,
        model: str,
        messages: list | str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Build a deterministic cache key"""
        if isinstance(messages, str):
            content = messages
        else:
            content = json.dumps(messages, sort_keys=True)
        
        raw = f"{model}|{temperature}|{max_tokens}|{content}"
        return f"llm:exact:{hashlib.sha256(raw.encode()).hexdigest()}"
    
    async def get(
        self,
        model: str,
        messages: list | str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """Get cached response if available"""
        key = self._build_key(model, messages, temperature, max_tokens)
        cached = await self.redis.get(key)
        
        if cached:
            self.hit_counter += 1
            return cached
        
        self.miss_counter += 1
        return None
    
    async def set(
        self,
        model: str,
        messages: list | str,
        response: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a response"""
        key = self._build_key(model, messages, temperature, max_tokens)
        await self.redis.setex(key, ttl or self.default_ttl, response)
    
    async def invalidate_model(self, model: str):
        """Invalidate all cache entries for a model"""
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=f"llm:exact:*", count=1000
            )
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break
    
    def get_hit_rate(self) -> float:
        total = self.hit_counter + self.miss_counter
        return self.hit_counter / total if total > 0 else 0.0
```

### Cache-Aware Orchestrator

```python
class CacheAwareRouter:
    """
    Router that checks cache before making LLM calls.
    Routes to cache-first, then falls back to LLM.
    """
    
    def __init__(
        self,
        exact_cache: ExactMatchLLMCache,
        semantic_cache: SemanticLLMCache,
    ):
        self.exact_cache = exact_cache
        self.semantic_cache = semantic_cache
    
    async def route(
        self,
        request: LLMRequest,
        user_id: str,
    ) -> RouterResult:
        
        # Level 1: Exact match cache (microseconds)
        exact = await self.exact_cache.get(
            model=request.model,
            messages=request.messages,
            temperature=request.temperature,
        )
        if exact:
            return RouterResult(
                response=exact,
                source="exact_cache",
                latency_us=await self._measure_cache_latency(),
            )
        
        # Level 2: Semantic cache (milliseconds)
        semantic = await self.semantic_cache.get(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
        )
        if semantic:
            return RouterResult(
                response=semantic,
                source="semantic_cache",
                similarity=self.semantic_cache.last_similarity,
            )
        
        # Level 3: Make LLM call
        response = await self._call_llm(request)
        
        # Cache the response asynchronously
        asyncio.create_task(self._cache_response(request, response))
        
        return RouterResult(
            response=response,
            source="llm",
        )
```

---

## 4. Retry Policies & Exponential Backoff

### Production Retry Strategy

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
        "exceptions": [RateLimitHit, httpx.HTTPStatusError],
    },
    # Network errors — retry quickly
    "network": {
        "max_attempts": 3,
        "min_wait": 0.5,
        "max_wait": 10,
        "exceptions": [httpx.TimeoutException, httpx.ConnectError],
    },
    # Server errors — retry with longer backoff
    "server": {
        "max_attempts": 3,
        "min_wait": 5,
        "max_wait": 30,
        "exceptions": [httpx.HTTPStatusError],  # 500s
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
        self.metrics = PrometheusMetrics()
    
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
                    wait = int(e.response.headers.get("Retry-After", base_delay * 2))
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
            if datetime.utcnow() >= state.next_retry_at:
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
                next_retry_at=datetime.utcnow() + timedelta(seconds=60),
                opened_at=datetime.utcnow(),
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
        return await llm_client.chat.completions.create(
            model=model,
            messages=messages,
        )
    
    response = await retry_handler.call_with_retry(
        model=model,
        call_fn=make_call,
        max_attempts=5,
        base_delay=1.0,
    )
    
    return response.choices[0].message.content
```

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
                ["model", "type"],  # type: prompt, completion, total
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
            model=model, type="prompt"
        ).inc(prompt_tokens)
        
        self.metrics["llm_tokens_total"].labels(
            model=model, type="completion"
        ).inc(completion_tokens)
        
        self.metrics["llm_latency_seconds"].labels(
            model=model, provider=provider
        ).observe(duration_ms / 1000.0)
        
        if completion_tokens > 0 and duration_ms > 0:
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

# ── Alert rules (Prometheus) ──────────────────────────────
"""
# prometheus-alerts.yml
groups:
  - name: llm_alerts
    rules:
      # High error rate
      - alert: LLMHighErrorRate
        expr: |
          rate(llm_errors_total[5m]) / rate(llm_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "LLM error rate > 5% for {{ $labels.model }}"
      
      # High latency
      - alert: LLMHighLatency
        expr: |
          histogram_quantile(0.99, rate(llm_latency_seconds_bucket[5m])) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency > 10s for {{ $labels.model }}"
      
      # Budget alert
      - alert: LLMBudgetThreshold
        expr: |
          rate(llm_cost_total[1h]) * 730 > 8000  # ~$8k/month projected
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
          rate(llm_cache_hits_total[1h]) / (rate(llm_cache_hits_total[1h]) + rate(llm_cache_misses_total[1h])) < 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Cache hit rate dropped below 10%"
      
      # Rate limiting spike
      - alert: LLMRateLimitSpike
        expr: rate(llm_rate_limited_requests_total[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limiting: {{ $value }}/s for {{ $labels.model }}"
```

---

## 6. Prompt Versioning & Management

### Prompt Registry

```python
from pydantic import BaseModel, Field
from datetime import datetime
import hashlib

@dataclass
class PromptTemplate:
    """A versioned prompt template with metadata"""
    id: str
    name: str
    version: str
    template: str
    variables: list[str]
    model: str                              # Target model
    temperature: float = 0.3
    max_tokens: int = 1024
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
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
                """SELECT * FROM prompt_templates 
                   WHERE name = $1 AND environment = $2
                   ORDER BY created_at DESC LIMIT 1""",
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
        
        # Render template
        return prompt.template.format(**variables)
    
    async def promote_version(
        self,
        name: str,
        version: str,
        environment: str = "production",
    ) -> None:
        """Promote a specific version to an environment"""
        await self.db.execute(
            """UPDATE prompt_templates 
               SET environment = $1, updated_at = NOW()
               WHERE name = $2 AND version = $3""",
            environment, name, version,
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
    
    async def _next_version(self, name: str) -> str:
        """Generate next version number"""
        last = await self.db.fetchval(
            "SELECT MAX(version) FROM prompt_templates WHERE name = $1",
            name,
        )
        next_num = int(last) + 1 if last else 1
        return f"v{next_num}.0.0"

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
    response = await llm_client.chat.completions.create(
        model=prompt.model,
        messages=[{"role": "user", "content": rendered}],
        temperature=prompt.temperature,
        max_tokens=prompt.max_tokens,
    )
    
    return response.choices[0].message.content
```

---

## 7. A/B Testing Different Models

### Experiment Framework

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
            start_time=datetime.utcnow(),
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
        
        # Consistent hashing on user_id for stable assignment
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
            # Auto-select winner based on metrics
            control = results.get(experiment.control_model, {})
            treatment = results.get(experiment.treatment_model, {})
            
            if control.get("error_rate", 1) > treatment.get("error_rate", 0):
                winner = experiment.treatment_model
            elif treatment.get("avg_cost", float("inf")) < control.get("avg_cost", 0) * 0.8:
                # Treatment is at least 20% cheaper with similar quality
                winner = experiment.treatment_model
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

# ── Example: Compare GPT-4o-mini vs DeepSeek for simple Q&A ──
async def run_ab_test():
    manager = ABTestManager(redis_client, token_tracker)
    
    experiment = await manager.create_experiment(
        name="simple-qa-model-comparison",
        control_model="gpt-4o-mini",
        treatment_model="deepseek-coder-v3",
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
            {"latency_ms": response.latency, "cost": response.cost, "total_tokens": response.total_tokens},
        ))
        
        return response
```

---

## 8. Tenant-Level Cost Allocation

### Usage-Based Billing

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
        
        now = datetime.utcnow()
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
        
        # Model breakdown
        pipe.hincrbyfloat(
            f"tenant:{tenant_id}:cost:model:{model}",
            "total_cost", cost,
        )
        pipe.hincrby(
            f"tenant:{tenant_id}:tokens:model:{model}",
            "total_tokens", prompt_tokens + completion_tokens,
        )
        
        # Monthly totals for billing
        month_key = now.strftime("%Y-%m")
        pipe.hincrbyfloat(
            f"tenant:{tenant_id}:cost:monthly:{month_key}",
            "total_cost", cost,
        )
        
        await pipe.execute()
        
        # Async write to permanent storage
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
        
        # Model breakdown
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=f"tenant:{tenant_id}:cost:model:*"
            )
            for key in keys:
                model = key.split(":")[-1]
                data = await self.redis.hgetall(key)
                if data:
                    usage.model_breakdown[model] = ModelUsage(
                        model=model,
                        total_cost=float(data.get(b"total_cost", 0)),
                        total_tokens=int(
                            (await self.redis.hgetall(
                                f"tenant:{tenant_id}:tokens:model:{model}"
                            )).get(b"total_tokens", 0)
                        ),
                    )
            if cursor == 0:
                break
        
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
        
        # Get per-model breakdown
        model_costs = {}
        async for key in self.redis.scan_iter(
            match=f"tenant:{tenant_id}:cost:model:*"
        ):
            model = key.split(":")[-1]
            data = await self.redis.hgetall(key)
            if data:
                model_costs[model] = float(data.get(b"total_cost", 0))
        
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
        model: str,
        user_id: str,
        tenant_id: Optional[str] = None,
    ):
        """Create a span for an LLM call"""
        with self.tracer.start_as_current_span(
            f"llm_call_{model}",
            attributes={
                "request_id": request_id,
                "model": model,
                "user_id": user_id,
                "tenant_id": tenant_id or "",
                "service": "multi-llm-orchestrator",
            },
        ) as span:
            yield span
            # Set status
            if span.get_attributes().get("error"):
                span.set_status(trace.Status(trace.StatusCode.ERROR))
    
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
        
        with self.tracer.trace_llm_call(
            request_id, request.model, user_id, tenant_id
        ) as span:
            try:
                start = time.perf_counter()
                
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
                span.set_attribute("error", True)
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
    
    # 4. Cost Rate
    "cost_per_hour": """
        sum(rate(llm_cost_total[1h]))
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
    
    # 9. Top Costs by Model
    "top_costs": """
        topk(5, sum by (model) (llm_cost_total))
    """,
    
    # 10. Concurrency by Model
    "concurrency": """
        llm_concurrent_requests
    """,
}
```

---

## Production Checklist

- [ ] **Token monitoring**: Per-request, per-user, per-tenant, global tracking with Prometheus
- [ ] **Rate limiting**: Multi-layer (global, model, user, IP) with tiered configs
- [ ] **Concurrency control**: Per-model semaphores with queue wait monitoring
- [ ] **Caching**: Exact match + semantic caching with configurable TTL
- [ ] **Retry policy**: Exponential backoff with jitter, per-error-type configs
- [ ] **Circuit breaker**: Open after N consecutive failures, half-open retry
- [ ] **Budget enforcement**: Per-request, session, daily, monthly token budgets
- [ ] **Alerting**: Error rate, latency, cost, cache hit rate, circuit breaker alerts
- [ ] **Prompt versioning**: Registry with version history, environment promotion
- [ ] **A/B testing**: Infrastructure for comparing models in production
- [ ] **Cost allocation**: Tenant-level usage tracking for billing
- [ ] **Logging**: Structured JSON logs with correlation IDs
- [ ] **Tracing**: OpenTelemetry distributed tracing through the entire pipeline
- [ ] **Dashboard**: Real-time Grafana dashboard with key metrics

---

> **Related:** [08_MULTI_LLM_ARCHITECTURE.md](./08_MULTI_LLM_ARCHITECTURE.md) — Routing, cost management, fallback chains
> **Related:** [04_AGENT_PRODUCTION_ARCHITECTURE.md](./04_AGENT_PRODUCTION_ARCHITECTURE.md) — General agent production architecture
> **Related:** [07_AGENT_OBSERVABILITY.md](./07_AGENT_OBSERVABILITY.md) — General agent observability patterns
