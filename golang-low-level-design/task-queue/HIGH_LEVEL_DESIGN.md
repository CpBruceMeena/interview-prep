# 📋 Task Queue / Worker Pool — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Async task processing, worker management, retry strategies

---

## 1. SYSTEM OVERVIEW

**Purpose:** Reliable async task processing with priority scheduling, retries, and graceful shutdown.

**Scale:** 100K tasks/day, 10-100 concurrent workers, sub-second task dispatch.

---

## 2. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                    Task Queue System                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐          ┌──────────────────────┐     │
│  │  API / Client │          │    Worker Pool        │     │
│  │  (Enqueue)    │          │    ┌────┐ ┌────┐    │     │
│  └──────┬───────┘          │    │ W1 │ │ W2 │    │     │
│         │                  │    └──┬─┘ └──┬─┘    │     │
│         ▼                  │    ┌────┐ ┌────┐    │     │
│  ┌──────────────┐          │    │ W3 │ │ WN │    │     │
│  │  Task Queue   │ ───────→│    └──┬─┘ └──┬─┘    │     │
│  │  (Priority)   │         │       │       │      │     │
│  └──────┬───────┘          │       ▼       ▼      │     │
│         │                  │  ┌────────────────┐  │     │
│         ▼                  │  │  Results Chan  │  │     │
│  ┌──────────────┐          │  └────────────────┘  │     │
│  │  TTL / Retry │          └──────────────────────┘     │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

## 3. TASK LIFECYCLE

```
ENQUEUE → PENDING → RUNNING → COMPLETED
                ↓         ↓
            RETRYING → FAILED (after max retries)
                ↓
            CANCELLED (manual)
```

## 4. RETRY STRATEGY

| Attempt | Backoff | Max Jitter |
|---------|---------|------------|
| 1 | 1s | ±100ms |
| 2 | 2s | ±200ms |
| 3 | 4s | ±400ms |
| 4 | 8s | ±800ms |
| 5 | 16s | ±1.6s |
| 6+ | 30s (cap) | ±3s |

## 5. GRACEFUL SHUTDOWN

```
1. SIGTERM → stop accepting new tasks
2. Notify workers → finish current task
3. Wait for in-flight tasks (configurable timeout)
4. After timeout: save pending/running state
5. Exit
```

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Queue storage | In-memory heap | Fastest, no serialization overhead |
| Persistence | Not included (production: Redis/PG) | Simplifies demo; production needs durability |
| Retry backoff | Exponential | Standard, prevents thundering herd |
| Task routing | Handler registry by type | Simple, extensible; not dynamic |
| Concurrency | Worker pool with channels | Go-native, no external dependencies |
