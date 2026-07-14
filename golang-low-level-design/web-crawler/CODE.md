# Web Crawler — Go Implementation

> Go implementation of a concurrent Web Crawler using CSP patterns (goroutines + channels).

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|---------------|---------|
| `WebCrawler` | Orchestrates crawl across worker pool | Fan-Out/Fan-In |
| `Fetcher` | HTTP fetch with rate limiting | Token Bucket |
| `VisitTracker` | Concurrent URL deduplication | sync.Map |
| `RobotsChecker` | robots.txt compliance | RWMutex |

### Fan-Out/Fan-In Worker Pool

```go
func (wc *WebCrawler) Crawl(ctx context.Context, seeds []string) (<-chan Page, error) {
    workQueue := make(chan CrawlRequest, 1000)

    // Seed URLs
    for _, seed := range seeds {
        normalized := normalizeURL(seed)
        if !wc.visited.IsVisited(normalized) {
            workQueue <- CrawlRequest{URL: normalized, Depth: 0}
        }
    }

    // Fan-Out: Start N workers
    var wg sync.WaitGroup
    for i := 0; i < wc.workers; i++ {
        wg.Add(1)
        go wc.worker(ctx, i, workQueue, &wg)
    }

    // Fan-In: Close results channel when all workers done
    go func() {
        wg.Wait()
        close(wc.results)
    }()

    return wc.results, nil
}
```

### URL Discovery Loop

```go
func (wc *WebCrawler) discoverURLs(ctx context.Context, queue chan<- CrawlRequest) {
    for page := range wc.results {
        for _, link := range page.Links {
            normalized := normalizeURL(link)
            if !wc.urlFilter(normalized) { continue }
            if wc.visited.IsVisited(normalized) { continue }

            // Non-blocking send
            select {
            case queue <- CrawlRequest{URL: normalized, Depth: page.Depth + 1}:
            default:
            }
        }
    }
}
```

## ▶️ How to Run

```bash
cd golang-low-level-design/web-crawler
go run web_crawler.go
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Worker Pool** | N goroutine workers | Controlled concurrency |
| **Fan-Out/Fan-In** | Work distribution + result collection | Scalable parallel processing |
| **Producer-Consumer** | URL discovery → workers | Decoupled processing stages |
| **Rate Limiter** | Token bucket per domain | Respect robots.txt politeness |
| **Context Cancellation** | Graceful shutdown | No orphaned goroutines |
