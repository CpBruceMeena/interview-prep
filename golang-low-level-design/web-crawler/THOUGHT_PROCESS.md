# 🧠 Web Crawler — Thought Process

## Problem Breakdown

### Step 1: Core Components
- **URL Frontier:** Where discovered URLs wait to be crawled
- **Fetcher:** Downloads page content
- **Parser:** Extracts links and metadata
- **Deduplicator:** Ensures each URL is crawled once

### Step 2: Concurrency Model
- Go's goroutines are ideal for I/O-bound crawling
- Worker pool pattern for controlled concurrency
- Channels for URL queue and result collection

### Step 3: Politeness
- Respect robots.txt
- Rate limit per domain (don't hammer servers)
- Crawl-delay from robots.txt

### Step 4: Graceful Shutdown
- Context-based cancellation propagates to all workers
- Partial results are preserved even on timeout

## Key Decisions

| Decision | Why |
|----------|-----|
| sync.Map for visited URLs | Concurrent-safe without explicit locking |
| Buffered channels (1000) | Tolerates producer-consumer speed mismatch |
| Depth-limited crawl | Prevents infinite exploration |
| Per-domain rate limit | Industry standard politeness |
