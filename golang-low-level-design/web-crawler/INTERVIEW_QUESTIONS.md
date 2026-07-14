# 🕷️ Web Crawler — Interview Questions

## Q1: How do you handle rate limiting and politeness?

**Answer:**
- Token bucket per domain (1 request/sec default)
- Respect `Crawl-Delay` from robots.txt
- Max 2 concurrent requests per domain
- Exponential backoff on 429/503 responses

## Q2: How do you prevent duplicate crawling?

**Answer:**
- Canonical URL normalization (lowercase, strip fragments, trailing slash)
- In-memory Bloom filter + exact set (sync.Map)
- For distributed: Redis set with EX/NX for TTL-based dedup
- URL signature (normalized URL hash) as unique key

## Q3: How would you distribute crawling across multiple machines?

**Answer:**
- URL frontier in Redis (BRPOPLPUSH for reliable queue)
- Consistent hashing for domain affinity
- Heartbeat + rebalancing on worker failure
- Use Redis sorted sets for priority crawling

## Q4: How do you handle JavaScript-rendered pages?

**Answer:**
- Headless browser (ChromeDP or Playwright) for JS-heavy sites
- Tiered approach: static fetch first, fall back to headless if needed
- Cache rendered HTML to avoid repeated rendering
- Cost-benefit: only render pages from whitelist of JS-heavy domains
