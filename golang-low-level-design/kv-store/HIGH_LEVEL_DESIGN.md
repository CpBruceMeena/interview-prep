# 🗄️ In-Memory KV Store — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Concurrent data store, eviction policies, TTL, persistence

---

## 1. SYSTEM OVERVIEW

**Purpose:** High-performance in-memory key-value store with configurable eviction policies and TTL support.

**Scale:** Millions of keys, sub-millisecond latency. 64-bit addressable.

---

## 2. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                     KV Store                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐     │
│  │  SET     │   │  GET     │   │  DELETE          │     │
│  └────┬─────┘   └────┬─────┘   └──────┬───────────┘     │
│       │              │                │                  │
│       ▼              ▼                ▼                  │
│  ┌──────────────────────────────────────────┐            │
│  │           sync.RWMutex                   │            │
│  └──────────────────────────────────────────┘            │
│       │              │                │                  │
│       ▼              ▼                ▼                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐     │
│  │  data    │   │eviction  │   │   TTL Heap       │     │
│  │  map     │   │policy    │   │   (Min-Heap)     │     │
│  └──────────┘   └──────────┘   └──────────────────┘     │
│                                                          │
│  ┌──────────────────────────────────────────┐            │
│  │        Snapshot (JSON Persistence)       │            │
│  └──────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────┘
```

## 3. EVICTION POLICIES

| Policy | Algorithm | Complexity | Best For |
|--------|-----------|------------|----------|
| **LRU** | Doubly-linked list + map | O(1) | General purpose |
| **LFU** | Min-heap of frequencies | O(log n) | Hot data retention |
| **TTL** | Min-heap by expiry time | O(log n) | Time-sensitive data |

## 4. CONCURRENCY MODEL

| Operation | Lock | Rationale |
|-----------|------|-----------|
| GET | RLock | Multiple concurrent reads |
| SET | Lock | Write needs exclusive access |
| DELETE | Lock | Write needs exclusive access |
| ExpireExpired | Lock | Batch mutation |
| Snapshot | RLock | Read-only consistent view |

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Locking | sync.RWMutex | Optimized for read-heavy workloads |
| Eviction | Pluggable Strategy | Different use cases need different policies |
| TTL tracking | Min-heap | O(log n) expiration, periodic cleanup |
| Persistence | JSON snapshot | Simple, human-readable; not for production |
| Size tracking | Bytes, not count | More accurate memory management |
