# 🕷️ Web Crawler — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Concurrent crawling, politeness, deduplication, graceful shutdown

---

## 1. SYSTEM OVERVIEW

**Purpose:** Crawl web pages to index content, extract links, and build a searchable corpus.

**Scale:** Millions of pages, distributed across multiple crawl workers/instances.

---

## 2. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                    Web Crawler                            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  URL Frontier ──→ Worker Pool ──→ Result Collector       │
│  (Channel)         (N goroutines)   (Fan-In)             │
│       │                 │                 │              │
│       ▼                 ▼                 ▼              │
│  DeDuplicator     Rate Limiter      Page Processor       │
│  (sync.Map)       (Token Bucket)   (Extract Links)      │
│                                                          │
└─────────────────────────────────────────────────────────┘
         │                 │                 │
         ▼                 ▼                 ▼
    Seed URLs         HTTP Client        Results Queue
```

## 3. CRAWL FLOW

```
1. Seed URL → URL Frontier (channel)
2. Worker dequeues URL → check visited → rate limit → fetch
3. Parse HTML → extract links → normalize → filter
4. New URLs → check robots.txt → enqueue to frontier
5. Page result → send to results channel
6. Repeat until: max pages reached OR frontier empty OR timeout
```

## 4. POLITENESS STRATEGY

| Concern | Implementation |
|---------|---------------|
| Rate limiting | Token bucket per domain, 1 req/sec default |
| robots.txt | Check before fetching, cache for 24h |
| Crawl delay | Respect Crawl-Delay directive |
| Concurrent requests | Max 2 per domain |

## 5. CONCURRENCY MODEL

| Pattern | Implementation |
|---------|---------------|
| Worker Pool | N goroutines, controlled parallelism |
| Fan-Out | Distribute work across workers |
| Fan-In | Collect results from all workers |
| Producer-Consumer | URL discovery feeds worker queue |
| Context Cancellation | Graceful shutdown via context |

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deduplication | sync.Map | Concurrent-safe, no locking |
| URL frontier | Buffered channel | Simple, bounded memory |
| Politeness | Per-domain rate limiter | Avoids overwhelming servers |
| Extraction | Simple regex-based | Demonstrates concept; production uses goquery |
