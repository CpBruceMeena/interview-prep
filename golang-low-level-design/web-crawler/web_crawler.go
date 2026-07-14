// Web Crawler - Low Level Design (Go)
// --------------------------------------
// Design Principles: CSP, Fan-Out/Fan-In, Worker Pool, Graceful Shutdown
//
// Key Design Decisions:
// - Worker pool pattern for concurrent URL fetching
// - goroutines + channels for producer-consumer
// - sync.Map for efficient concurrent deduplication
// - Rate limiting with token bucket per domain
// - Context-based cancellation for graceful shutdown

package main

import (
	"context"
	"fmt"
	"log"
	"math/rand"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ============================================================
// CRAWL TYPES
// ============================================================

// Page represents a crawled page result
type Page struct {
	URL     string
	Title   string
	Links   []string
	Status  int
	Depth   int
	Size    int
	Latency time.Duration
	Error   error
}

// CrawlRequest represents a URL to crawl
type CrawlRequest struct {
	URL   string
	Depth int
}

// ============================================================
// ROBOTS.TXT CHECKER
// ============================================================

type RobotsChecker struct {
	mu       sync.RWMutex
	rules    map[string][]string // domain -> disallowed paths
}

func NewRobotsChecker() *RobotsChecker {
	return &RobotsChecker{
		rules: make(map[string][]string),
	}
}

func (rc *RobotsChecker) IsAllowed(uri string) bool {
	parsed, err := url.Parse(uri)
	if err != nil {
		return false
	}

	domain := parsed.Host
	path := parsed.Path

	rc.mu.RLock()
	disallowed, ok := rc.rules[domain]
	rc.mu.RUnlock()

	if !ok {
		return true // No rules = allowed
	}

	for _, pattern := range disallowed {
		if strings.Contains(path, pattern) {
			return false
		}
	}
	return true
}

func (rc *RobotsChecker) FetchRobots(ctx context.Context, domain string) {
	// Simulate fetching robots.txt
	rc.mu.Lock()
	rc.rules[domain] = []string{"/admin", "/private", "/api"}
	rc.mu.Unlock()
}

// ============================================================
// URL NORMALIZER
// ============================================================

func normalizeURL(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}

	// Normalize: lowercase scheme/host, remove fragment, trim trailing slash
	parsed.Scheme = strings.ToLower(parsed.Scheme)
	parsed.Host = strings.ToLower(parsed.Host)
	parsed.Fragment = ""

	path := strings.TrimRight(parsed.Path, "/")
	if path == "" {
		path = "/"
	}
	parsed.Path = path

	return parsed.String()
}

func extractLinks(baseURL string, html string) []string {
	// Simplified link extraction
	var links []string
	lines := strings.Split(html, "\n")

	for _, line := range lines {
		// Find href="..." or href='...'
		idx := strings.Index(strings.ToLower(line), "href=")
		if idx == -1 {
			continue
		}

		rest := line[idx+5:]
		var quote byte
		if len(rest) > 0 && (rest[0] == '"' || rest[0] == '\'') {
			quote = rest[0]
			rest = rest[1:]
		} else {
			continue
		}

		endIdx := strings.IndexByte(rest, quote)
		if endIdx == -1 {
			continue
		}

		href := rest[:endIdx]
		if href == "" || strings.HasPrefix(href, "#") || strings.HasPrefix(href, "javascript:") {
			continue
		}

		// Resolve relative URLs
		resolved := resolveURL(baseURL, href)
		if resolved != "" {
			links = append(links, resolved)
		}
	}

	return links
}

func resolveURL(base, href string) string {
	baseURL, err := url.Parse(base)
	if err != nil {
		return ""
	}

	hrefURL, err := url.Parse(href)
	if err != nil {
		return ""
	}

	return baseURL.ResolveReference(hrefURL).String()
}

// ============================================================
// FETCHER WITH RATE LIMITING
// ============================================================

type RateLimiter struct {
	mu         sync.Mutex
	tokens     float64
	maxTokens  float64
	refillRate float64
	lastRefill time.Time
}

func NewRateLimiter(rate float64, burst int) *RateLimiter {
	return &RateLimiter{
		tokens:     float64(burst),
		maxTokens:  float64(burst),
		refillRate: rate,
		lastRefill: time.Now(),
	}
}

func (rl *RateLimiter) Allow() bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(rl.lastRefill).Seconds()
	rl.tokens = min(rl.maxTokens, rl.tokens+elapsed*rl.refillRate)
	rl.lastRefill = now

	if rl.tokens < 1 {
		return false
	}
	rl.tokens--
	return true
}

type Fetcher struct {
	rateLimiter *RateLimiter
	robots      *RobotsChecker
}

func NewFetcher(rateLimit float64, burst int) *Fetcher {
	return &Fetcher{
		rateLimiter: NewRateLimiter(rateLimit, burst),
		robots:      NewRobotsChecker(),
	}
}

func (f *Fetcher) Fetch(ctx context.Context, req CrawlRequest) Page {
	start := time.Now()
	log.Printf("Crawling: %s (depth=%d)", req.URL, req.Depth)

	// Rate limit
	if !f.rateLimiter.Allow() {
		time.Sleep(100 * time.Millisecond) // Back off
	}

	// Simulate HTTP fetch (simplified)
	page := Page{
		URL:   req.URL,
		Depth: req.Depth,
	}

	// Simulate varying latency
	latency := time.Duration(50+rand.Intn(200)) * time.Millisecond
	select {
	case <-ctx.Done():
		page.Error = ctx.Err()
		return page
	case <-time.After(latency):
	}

	page.Status = 200
	page.Latency = latency
	page.Size = 1000 + rand.Intn(5000)
	page.Title = fmt.Sprintf("Page: %s", req.URL)

	// Simulate links based on URL depth
	if req.Depth < 3 {
		simulatedLinks := []string{
			req.URL + "/about",
			req.URL + "/contact",
			req.URL + "/products",
			req.URL + "/blog",
			req.URL + "/faq",
		}
		page.Links = simulatedLinks
	}

	return page
}

// ============================================================
// URL VISIT TRACKER
// ============================================================

type VisitTracker struct {
	visited sync.Map
	count   atomic.Int64
}

func (vt *VisitTracker) IsVisited(url string) bool {
	_, loaded := vt.visited.LoadOrStore(url, struct{}{})
	if !loaded {
		vt.count.Add(1)
		return false
	}
	return true
}

func (vt *VisitTracker) Count() int64 {
	return vt.count.Load()
}

// ============================================================
// WEB CRAWLER (Core)
// ============================================================

type WebCrawler struct {
	workers    int
	maxDepth   int
	maxPages   int
	urlFilter  func(string) bool
	fetcher    *Fetcher
	visited    *VisitTracker
	results    chan Page
	pagesFound atomic.Int64
}

func NewWebCrawler(workers, maxDepth, maxPages int) *WebCrawler {
	return &WebCrawler{
		workers:   workers,
		maxDepth:  maxDepth,
		maxPages:  maxPages,
		urlFilter: defaultURLFilter,
		fetcher:   NewFetcher(10, 20),
		visited:   &VisitTracker{},
		results:   make(chan Page, 1000),
	}
}

func defaultURLFilter(uri string) bool {
	parsed, err := url.Parse(uri)
	if err != nil {
		return false
	}
	// Only crawl http/https
	return parsed.Scheme == "http" || parsed.Scheme == "https"
}

// Crawl starts the web crawl from seed URLs
func (wc *WebCrawler) Crawl(ctx context.Context, seeds []string) (<-chan Page, error) {
	// Seed the work queue
	workQueue := make(chan CrawlRequest, 1000)
	for _, seed := range seeds {
		normalized := normalizeURL(seed)
		if !wc.visited.IsVisited(normalized) {
			workQueue <- CrawlRequest{URL: normalized, Depth: 0}
		}
	}

	// Start worker goroutines (Fan-Out)
	var wg sync.WaitGroup
	for i := 0; i < wc.workers; i++ {
		wg.Add(1)
		go wc.worker(ctx, i, workQueue, &wg)
	}

	// Close results when all workers finish
	go func() {
		wg.Wait()
		close(wc.results)
	}()

	// URL discovery goroutine - feeds new URLs back to workQueue
	go wc.discoverURLs(ctx, workQueue)

	return wc.results, nil
}

// worker processes crawl requests (Fan-Out worker)
func (wc *WebCrawler) worker(ctx context.Context, id int, queue <-chan CrawlRequest, wg *sync.WaitGroup) {
	defer wg.Done()
	log.Printf("Worker %d started", id)

	for req := range queue {
		// Check cancellation
		select {
		case <-ctx.Done():
			return
		default:
		}

		// Check page limit
		if wc.pagesFound.Load() >= int64(wc.maxPages) {
			return
		}

		// Check depth
		if req.Depth > wc.maxDepth {
			continue
		}

		// Fetch the page
		page := wc.fetcher.Fetch(ctx, req)
		wc.pagesFound.Add(1)

		// Send result
		select {
		case wc.results <- page:
		case <-ctx.Done():
			return
		}
	}
}

// discoverURLs processes results and discovers new URLs to crawl
func (wc *WebCrawler) discoverURLs(ctx context.Context, queue chan<- CrawlRequest) {
	for page := range wc.results {
		if page.Error != nil {
			continue
		}

		for _, link := range page.Links {
			normalized := normalizeURL(link)

			// Check filters
			if !wc.urlFilter(normalized) {
				continue
			}

			// Check if already visited
			if wc.visited.IsVisited(normalized) {
				continue
			}

			// Queue new request (non-blocking)
			select {
			case queue <- CrawlRequest{URL: normalized, Depth: page.Depth + 1}:
			default:
				// Queue full — skip
			}
		}
	}
}

// ============================================================
// DEMO
// ============================================================

func main() {
	fmt.Println("=== Web Crawler Demo ===\n")

	// Create crawler with 5 workers, max depth 2, max 50 pages
	crawler := NewWebCrawler(5, 2, 50)

	// Create context with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Start crawl
	seeds := []string{
		"https://example.com",
		"https://example.org",
	}
	log.Printf("Starting crawl from %v...\n", seeds)

	results, err := crawler.Crawl(ctx, seeds)
	if err != nil {
		log.Fatal(err)
	}

	// Collect and display results
	var pages []Page
	for page := range results {
		pages = append(pages, page)
		fmt.Printf("  [Depth %d] %s (%d bytes, %v)\n",
			page.Depth, page.URL, page.Size, page.Latency)
	}

	fmt.Printf("\n=== Crawl Complete ===\n")
	fmt.Printf("Total pages crawled: %d\n", len(pages))
	fmt.Printf("Unique URLs found: %d\n", crawler.visited.Count())

	// Stats
	var totalSize, totalLatency int64
	for _, p := range pages {
		totalSize += int64(p.Size)
		totalLatency += p.Latency.Milliseconds()
	}
	if len(pages) > 0 {
		fmt.Printf("Avg page size: %d bytes\n", totalSize/int64(len(pages)))
		fmt.Printf("Avg latency: %dms\n", totalLatency/int64(len(pages)))
	}
}

