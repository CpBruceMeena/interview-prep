# 🕷️ Web Crawler — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Concurrent crawling, politeness, deduplication, graceful shutdown

---

## 1. SYSTEM OVERVIEW

**Purpose:** Crawl web pages to index content, extract links, and build a searchable corpus.

**Scale:** this LLD is a single process. The distributed target is 1 B pages/month: ≈ 400 pages/s on average. At about 100 KB of HTML per page that's ≈ 40 MB/s (≈ 320 Mbit/s) of ingress and ≈ 100 TB/month of raw HTML before compression. Each crawler node handles roughly 50–200 pages/s, so plan for about 5–10 nodes with headroom.

---

## 2. SYSTEM ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────┐
│                        Crawl(ctx, seeds)                        │
│                                                                 │
│   ┌──────────────────────────────┐   jobs (unbuffered)          │
│   │ Coordinator goroutine        │ ─────────────────► ┌───────┐ │
│   │  frontier (FIFO = BFS)       │                    │Worker │ │
│   │  seen-set (normalized URLs)  │ ◄───────────────── │ × N   │ │
│   │  inFlight / dispatched       │   results          └───┬───┘ │
│   │  filters, depth, MaxPages    │                        │     │
│   │  OnPage callback (serial)    │                        ▼     │
│   └──────────────────────────────┘     hostTable: robots (Once) │
│                                        + per-host waitTurn      │
│          crawlGroup: first error cancels ctx; Wait joins all    │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                     Fetcher (HTTPFetcher | FakeWeb)
```

## 3. CRAWL FLOW

```
1. Seeds → Normalize → filters/depth → seen-set → frontier
2. Coordinator dispatches the frontier head to an idle worker (if within MaxPages)
3. Worker: robots.txt (once per host) → wait for the host's turn → fetch (timeout, body limit)
4. Worker extracts and resolves links from 2xx text/html → sends a result
5. Coordinator: update stats, admit new links (normalize → filter → depth → seen), call OnPage
6. Stop when the frontier is empty AND inFlight == 0, or the budget is spent, or ctx is done, or OnPage returns an error
```

## 4. POLITENESS STRATEGY

| Concern | Implementation |
|---------|---------------|
| robots.txt | Fetched once per host per crawl; RFC 9309 groups, longest match, `*`/`$`; 4xx → allow all, 5xx/unreachable → disallow all |
| Rate limiting | Minimum gap per host = max(`PerHostDelay`, Crawl-delay), claimed under the host lock after a ctx-aware wait |
| Crawl delay | Honoured (non-standard; Bing uses it, Google ignores it) |
| Concurrent requests per host | Not capped separately here; add a per-host semaphore (production: 1–2) |
| Identification | Explicit User-Agent |

## 5. CONCURRENCY MODEL

| Pattern | Implementation |
|---------|---------------|
| Single owner | Coordinator owns frontier, seen-set and counters, so they need no locks |
| Worker pool | N goroutines doing only I/O |
| Fan-out / fan-in | Unbuffered `jobs` → workers → unbuffered `results`; the coordinator `select`s on both (nil-channel trick) |
| Channel ownership | The coordinator closes `jobs`; `results` is never closed; every send also selects on `ctx.Done()` |
| errgroup | `crawlGroup`: first error cancels; `Wait` joins every goroutine before `Crawl` returns |
| Shared state | Only `hostTable` (mutex) and `hostState` (`sync.Once` + mutex) |

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deduplication | Plain map owned by the coordinator | The check and the insert are one step; no `sync.Map` races |
| URL frontier | In-memory FIFO slice | BFS order; production uses Mercator front/back queues on disk |
| Termination | Frontier empty AND inFlight == 0 | Exact; no polling or timeouts |
| Politeness | Per-host turn + robots | Avoids overwhelming servers and respects the site's rules |
| API | Synchronous `Crawl` + `OnPage` | No channel the caller must drain to avoid leaks |
| Extraction | Regex over `<a href>` | Stdlib-only; production uses an HTML tokenizer (`x/net/html`) |
| Normalization | Conservative (keeps path case and trailing slash) | Merging distinct URLs loses pages; extra fetches only cost time |

## 7. FAILURE MODES

| Failure | Effect | Mitigation |
|---|---|---|
| Spider trap (calendar, infinite params) | Unbounded frontier | Depth limit, per-host page budget, max URL length, repeated-segment detection |
| Host slow or down | Workers tied up; politeness delays pile up | Fetch timeout; error-rate circuit breaker per host; Mercator back queues to avoid head-of-line blocking |
| 429 / 503 storms | Getting banned | Honour `Retry-After`, exponential backoff per host, lower that host's rate |
| robots.txt unreachable | Unknown permissions | Treat as full disallow (RFC 9309); retry later |
| Huge or binary responses | Memory blow-up | `io.LimitReader`, Content-Type check before parsing |
| Crawler crash | Lost frontier | Checkpoint frontier + seen-set (RocksDB); refetch since the checkpoint (at-least-once) |
| Seen-set too big for RAM | OOM | Bloom filter (≈ 1.2 GB per 1 B URLs at 1% FP) in front of a disk set |
| Duplicate content under different URLs | Wasted crawl budget | `rel=canonical`, redirect targets, SimHash near-dup detection |
