# 🏗️ Rate Limiter — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Distributed rate limiting, algorithms, API gateway design

---

## 1. SYSTEM OVERVIEW

**Purpose:** Protect APIs from abuse by enforcing request rate limits per user/IP/API key with configurable algorithms and tiers.

**Scale:** 1M requests/second peak, 100K distinct rate limit keys, <2ms decision latency

**Users:** API consumers (external developers), Internal services, Platform admins

**Use Cases:** Throttle per-user API calls, Tier-based limits (Free/Pro/Enterprise), Burst protection, DDoS mitigation

**Constraints:** p99 latency <2ms, 99.999% uptime, no false negatives (never allow >limit), configurable algorithms

---

## 2. HIGH-LEVEL ARCHITECTURE

```
                       ┌──────────────┐
Request ──────────────▶│   Load       │──▶ Rate Limiter Middleware
                       │   Balancer   │    (Sidecar / Plugin)
                       └──────────────┘         │
                                          ┌─────▼──────┐
                                          │  Local Cache│
                                          │  (Token     │
                                          │   Bucket)   │── 429 if denied
                                          └─────┬──────┘
                                                │ miss (reload)
                                          ┌─────▼──────┐
                                          │  Redis      │
                                          │  Cluster    │
                                          │  (Counters, │
                                          │   Sliding   │
                                          │   Windows)  │
                                          └─────┬──────┘
                                                │
                                          ┌─────▼──────┐
                                          │  Config│  │  Store     │
          │  (Rules    │
          │   per API, │
          │   per Tier)│
          └────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/rate-limiter-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Rate Limiter Sequence — Request → Token Check → Allow/Block → Response. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Rate Limiter Middleware
- **Language:** Go (C++ for ultra-low latency, Lua for Redis scripting)
- **Deployment:** Sidecar proxy (Envoy ext_authz), API Gateway plugin, or library
- **Algorithm selection per route:** Config-driven

**🔴 Interview Question:** *"How do you make rate limiting decisions in under 2ms?"*

**✅ Answer:** Multi-tier approach:
1. **L1 — Local in-memory counter:** Approximate counter with sync interval. Covers 99% of requests without Redis round-trip.
2. **L2 — Redis atomic counters:** Lua script for precise counting (`INCR + EXPIRE` in one atomic operation).
3. **Async sync:** Local L1 sends heartbeat to Redis every 100ms to stay within ~1% of true count.
4. **Result:** 95% of decisions from L1 (sub-microsecond), 5% from L2 (~1ms). p99 stays <2ms.

---

### Redis Cluster (Counters)
- Key design: `ratelimit:{api_key}:{route}:{window}`
- Lua script for atomic check-and-increment
- Key TTL = window size + 1 second

**🔴 Interview Question:** *"How do you handle Redis failure?"*

**✅ Answer:**
1. **Local fallback:** If Redis unavailable, use local approximate counter with lenient limits (e.g., allow 110% of limit). Prevents complete API outage.
2. **Circuit breaker:** If Redis latency > 10ms, skip Redis and use local only.
3. **Redundancy:** Redis Cluster with replication. If primary fails, replica promotes in <5 seconds.
4. **Graceful degradation:** During Redis outage, rate limits become soft (best-effort).

---

### Configuration Store
- Rule schema: `{"route": "/api/v1/users", "tier": "free", "algorithm": "token_bucket", "max": 100, "window_seconds": 60}`
- Watched via etcd/Consul for hot reload — no restart needed

**🔴 Interview Question:** *"How do you support multi-tier rate limiting (Free, Pro, Enterprise)?"*

**✅ Answer:**
```json
{
  "tiers": {
    "free":  { "rps": 5,  "rpm": 100,  "rpd": 1000  },
    "pro":  { "rps": 50, "rpm": 1000, "rpd": 50000 },
    "enterprise": { "rps": 500, "rpm": 10000, "rpd": 500000 }
  },
  "endpoints": {
    "GET /users": { "burst": 2.0 },
    "POST /orders": { "burst": 1.0 }
  }
}
```

Each tier has soft (burst) and hard limits. Exceeding soft → warning headers. Exceeding hard → 429.

---

## 4. ALGORITHM SELECTION GUIDE

| Algorithm | Burst | Accuracy | Memory | CPU | Best For |
|-----------|-------|----------|--------|-----|----------|
| Token Bucket | ✅ | Medium | O(1) | Low | Bursty APIs |
| Sliding Window Log | ❌ | Perfect | O(N) | Medium | Critical accuracy |
| Fixed Window | ❌ | Low | O(1) | Low | Non-critical |
| Sliding Window Counter | ❌ | High | O(1) | Low | Most production (Stripe, GitHub) |

**Recommendation:** Token Bucket for most APIs. Sliding Window Counter for financial APIs.

---

## 5. ERROR HANDLING

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1623456789
Retry-After: 45

{
  "error": "rate_limit_exceeded",
  "message": "API rate limit exceeded. Resets in 45 seconds.",
  "retry_after_seconds": 45
}
```

---

## 6. SCALABILITY

**Bottleneck:** Redis single-threaded processing

**Solution:** Redis Cluster with 16 shards. Each shard handles ~60K ops/sec. Lua scripts are atomic per shard — ensures correctness.

**Worst case:** All requests hit same Redis key → hot shard. Mitigation: Shuffle shards or add local L1 cache.

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| Redis Cluster (6 nodes) | $1,800 |
| Config Store (etcd) | $300 |
| Monitoring + Alerts | $200 |
| **Total** | **$2,300** |
