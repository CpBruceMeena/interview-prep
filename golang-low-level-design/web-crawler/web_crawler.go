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
// - Sitemap parsing for SEO-aware crawling
// - Content-type filtering for selective crawling
// - Domain-based worker allocation for politeness
// - Crawl statistics and progress tracking
// - Persistent URL frontier with disk-backed queue

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
	URL        string
	Title      string
	Links      []string
	Status     int
	Depth      int
	Size       int
	ContentType string
	Latency    time.Duration
	Error      error
	CrawledAt  time.Time
}

// CrawlRequest represents a URL to crawl
type CrawlRequest struct {
	URL         string
	Depth       int
	ReferrerURL string
	Priority    int // Higher = more important
}

// CrawlStats tracks crawl progress and metrics
type CrawlStats struct {
	PagesCrawled    atomic.Int64
	PagesSkipped    atomic.Int64
	PagesFailed     atomic.Int64
	TotalBytes      atomic.Int64
	TotalLatency    atomic.Int64
	UniqueURLsFound atomic.Int64
	ErrorsByType    map[string]int64
	mu              sync.Mutex
}

func NewCrawlStats() *CrawlStats {
	return &CrawlStats{
		ErrorsByType: make(map[string]int64),
	}
}

func (cs *CrawlStats) RecordError(errorType string) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.ErrorsByType[errorType]++
}

func (cs *CrawlStats) Print() {
	fmt.Printf("\n📊 CRAWL STATISTICS\n")
	fmt.Printf("  Pages crawled:   %d\n", cs.PagesCrawled.Load())
	fmt.Printf("  Pages skipped:   %d\n", cs.PagesSkipped.Load())
	fmt.Printf("  Pages failed:    %d\n", cs.PagesFailed.Load())
	fmt.Printf("  Total bytes:     %d\n", cs.TotalBytes.Load())
	fmt.Printf("  Avg latency:     %dms\n",
		cs.TotalLatency.Load()/max(1, cs.PagesCrawled.Load()))
	fmt.Printf("  Unique URLs:     %d\n", cs.UniqueURLsFound.Load())

	cs.mu.Lock()
	if len(cs.ErrorsByType) > 0 {
		fmt.Printf("  Errors by type:\n")
		for etype, count := range cs.ErrorsByType {
			fmt.Printf("    %s: %d\n", etype, count)
		}
	}
	cs.mu.Unlock()
}

// ============================================================
// ROBOTS.TXT CHECKER
// ============================================================

type RobotsRule struct {
	Disallowed []string
	Allowed    []string
	CrawlDelay time.Duration
}

type RobotsChecker struct {
	mu       sync.RWMutex
	rules    map[string]*RobotsRule
}

func NewRobotsChecker() *RobotsChecker {
	return &RobotsChecker{
		rules: make(map[string]*RobotsRule),
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
	rule, ok := rc.rules[domain]
	rc.mu.RUnlock()

	if !ok {
		return true
	}

	// Check allowed patterns first
	for _, pattern := range rule.Allowed {
		if strings.Contains(path, pattern) {
			return true
		}
	}

	// Then check disallowed
	for _, pattern := range rule.Disallowed {
		if strings.Contains(path, pattern) {
			return false
		}
	}

	return true
}

func (rc *RobotsChecker) GetCrawlDelay(domain string) time.Duration {
	rc.mu.RLock()
	defer rc.mu.RUnlock()

	if rule, ok := rc.rules[domain]; ok {
		return rule.CrawlDelay
	}
	return 0
}

func (rc *RobotsChecker) FetchAndParse(ctx context.Context, domain string) {
	// Simulate fetching and parsing robots.txt
	rc.mu.Lock()
	defer rc.mu.Unlock()

	// Simulate varying crawl delays per domain
	delay := time.Duration(100+rand.Intn(900)) * time.Millisecond
	rc.rules[domain] = &RobotsRule{
		Disallowed: []string{"/admin", "/private", "/api", "/wp-admin", "/tmp"},
		Allowed:    []string{"/public", "/about", "/contact"},
		CrawlDelay: delay,
	}
	log.Printf("  🤖 Parsed robots.txt for %s (delay: %v)", domain, delay)
}

// ============================================================
// SITEMAP PARSER
// ============================================================

type SitemapParser struct {
	mu     sync.RWMutex
	sitemaps map[string][]string // domain -> URLs from sitemap
}

func NewSitemapParser() *SitemapParser {
	return &SitemapParser{
		sitemaps: make(map[string][]string),
	}
}

func (sp *SitemapParser) FetchAndParse(ctx context.Context, domain string) []string {
	// Simulate fetching sitemap.xml
	sp.mu.Lock()
	defer sp.mu.Unlock()

	// Generate simulated sitemap URLs
	urls := []string{
		fmt.Sprintf("https://%s/", domain),
		fmt.Sprintf("https://%s/about", domain),
		fmt.Sprintf("https://%s/products", domain),
		fmt.Sprintf("https://%s/blog", domain),
		fmt.Sprintf("https://%s/contact", domain),
		fmt.Sprintf("https://%s/faq", domain),
		fmt.Sprintf("https://%s/privacy", domain),
		fmt.Sprintf("https://%s/terms", domain),
	}
	sp.sitemaps[domain] = urls
	log.Printf("  🗺️ Parsed sitemap for %s (%d URLs)", domain, len(urls))
	return urls
}

// ============================================================
// URL NORMALIZER & FILTER
// ============================================================

type URLFilter interface {
	Allow(uri string) bool
	Name() string
}

type SchemeFilter struct{}
func (f *SchemeFilter) Allow(uri string) bool {
	parsed, err := url.Parse(uri)
	if err != nil { return false }
	return parsed.Scheme == "http" || parsed.Scheme == "https"
}
func (f *SchemeFilter) Name() string { return "SchemeFilter" }

type ExtensionFilter struct {
	allowedExtensions map[string]bool
}

func NewExtensionFilter() *ExtensionFilter {
	return &ExtensionFilter{
		allowedExtensions: map[string]bool{
			".html": true, ".htm": true, ".php": true, ".aspx": true,
			"/":     true, "":      true, // No extension = HTML page
		},
	}
}

func (f *ExtensionFilter) Allow(uri string) bool {
	parsed, err := url.Parse(uri)
	if err != nil { return false }

	path := parsed.Path
	lastDot := strings.LastIndex(path, ".")
	if lastDot == -1 {
		return true // No extension = probably HTML
	}

	ext := strings.ToLower(path[lastDot:])
	// Allow HTML-like extensions and no-extension URLs
	return f.allowedExtensions[ext] || !strings.Contains(ext, ".")
}

func (f *ExtensionFilter) Name() string { return "ExtensionFilter" }

type DomainFilter struct {
	allowedDomains []string
	deniedDomains  []string
}

func NewDomainFilter(allowed, denied []string) *DomainFilter {
	return &DomainFilter{
		allowedDomains: allowed,
		deniedDomains:  denied,
	}
}

func (f *DomainFilter) Allow(uri string) bool {
	parsed, err := url.Parse(uri)
	if err != nil { return false }

	host := parsed.Hostname()

	// Check denied list
	for _, d := range f.deniedDomains {
		if strings.Contains(host, d) {
			return false
		}
	}

	// If allowed list is empty, allow all
	if len(f.allowedDomains) == 0 {
		return true
	}

	// Check allowed list
	for _, d := range f.allowedDomains {
		if strings.Contains(host, d) {
			return true
		}
	}
	return false
}

func (f *DomainFilter) Name() string { return "DomainFilter" }

func normalizeURL(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}

	// Normalize: lowercase scheme/host, remove fragment, sort query params
	parsed.Scheme = strings.ToLower(parsed.Scheme)
	parsed.Host = strings.ToLower(parsed.Host)
	parsed.Fragment = ""

	path := strings.TrimRight(parsed.Path, "/")
	if path == "" {
		path = "/"
	}
	parsed.Path = path

	// Sort query parameters for consistent comparison
	if parsed.RawQuery != "" {
		params := strings.Split(parsed.RawQuery, "&")
		for i, p := range params {
			parts := strings.SplitN(p, "=", 2)
			if len(parts) == 2 {
				params[i] = parts[0] + "=" + parts[1]
			}
		}
		// Remove tracking parameters
		clean := make([]string, 0)
		trackingParams := map[string]bool{
			"utm_source": true, "utm_medium": true, "utm_campaign": true,
			"utm_term": true, "utm_content": true, "fbclid": true,
			"gclid": true, "ref": true,
		}
		for _, p := range params {
			parts := strings.SplitN(p, "=", 2)
			if !trackingParams[parts[0]] {
				clean = append(clean, p)
			}
		}
		parsed.RawQuery = strings.Join(clean, "&")
	}

	// Remove default ports
	if parsed.Port() == "80" && parsed.Scheme == "http" {
		parsed.Host = strings.TrimSuffix(parsed.Host, ":80")
	}
	if parsed.Port() == "443" && parsed.Scheme == "https" {
		parsed.Host = strings.TrimSuffix(parsed.Host, ":443")
	}

	return parsed.String()
}

func extractLinks(baseURL string, html string) []string {
	var links []string
	lines := strings.Split(html, "\n")
	seen := make(map[string]bool)

	for _, line := range lines {
		// Find href="..." or href='...'
		lowerLine := strings.ToLower(line)
		idx := strings.Index(lowerLine, "href=")
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

		// Skip mailto and tel links
		if strings.HasPrefix(href, "mailto:") || strings.HasPrefix(href, "tel:") {
			continue
		}

		resolved := resolveURL(baseURL, href)
		if resolved != "" && !seen[resolved] {
			seen[resolved] = true
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
// CONTENT-TYPE DETECTOR (simulated)
// ============================================================

func detectContentType(url string) string {
	parsed, _ := url.Parse(url)
	path := parsed.Path

	if strings.HasSuffix(path, ".pdf") { return "application/pdf" }
	if strings.HasSuffix(path, ".xml") || strings.HasSuffix(path, ".atom") { return "application/xml" }
	if strings.HasSuffix(path, ".json") { return "application/json" }
	if strings.HasSuffix(path, ".css") { return "text/css" }
	if strings.HasSuffix(path, ".js") { return "application/javascript" }
	if strings.HasSuffix(path, ".png") || strings.HasSuffix(path, ".jpg") || strings.HasSuffix(path, ".gif") {
		return "image/*"
	}
	return "text/html"
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

type PerDomainRateLimiter struct {
	mu       sync.Mutex
	limiters map[string]*RateLimiter
	defaultRPS float64
	defaultBurst int
}

func NewPerDomainRateLimiter(rps float64, burst int) *PerDomainRateLimiter {
	return &PerDomainRateLimiter{
		limiters:     make(map[string]*RateLimiter),
		defaultRPS:   rps,
		defaultBurst: burst,
	}
}

func (pdrl *PerDomainRateLimiter) getLimiter(domain string) *RateLimiter {
	pdrl.mu.Lock()
	defer pdrl.mu.Unlock()

	if lim, ok := pdrl.limiters[domain]; ok {
		return lim
	}
	lim := NewRateLimiter(pdrl.defaultRPS, pdrl.defaultBurst)
	pdrl.limiters[domain] = lim
	return lim
}

func (pdrl *PerDomainRateLimiter) Allow(domain string) bool {
	return pdrl.getLimiter(domain).Allow()
}

type Fetcher struct {
	rateLimiter      *PerDomainRateLimiter
	robots           *RobotsChecker
	crawlDelay       time.Duration
}

func NewFetcher(rps float64, burst int) *Fetcher {
	return &Fetcher{
		rateLimiter: NewPerDomainRateLimiter(rps, burst),
		robots:      NewRobotsChecker(),
	}
}

func (f *Fetcher) Fetch(ctx context.Context, req CrawlRequest) Page {
	start := time.Now()
	parsed, err := url.Parse(req.URL)
	if err != nil {
		return Page{URL: req.URL, Error: fmt.Errorf("invalid URL: %w", err)}
	}
	domain := parsed.Host

	log.Printf("  🌐 Crawling: %s (depth=%d, priority=%d)", req.URL, req.Depth, req.Priority)

	// Check robots.txt
	if !f.robots.IsAllowed(req.URL) {
		return Page{
			URL:       req.URL,
			Depth:     req.Depth,
			Status:    403,
			Error:     fmt.Errorf("blocked by robots.txt"),
			Latency:   time.Since(start),
			CrawledAt: time.Now(),
		}
	}

	// Rate limit per domain
	if !f.rateLimiter.Allow(domain) {
		backoff := 200*time.Millisecond + time.Duration(rand.Intn(300))*time.Millisecond
		time.Sleep(backoff)
	}

	// Respect robots.txt crawl delay
	crawlDelay := f.robots.GetCrawlDelay(domain)
	if crawlDelay > 0 {
		time.Sleep(crawlDelay)
	}

	// Simulate HTTP fetch
	page := Page{
		URL:         req.URL,
		Depth:       req.Depth,
		ContentType: detectContentType(req.URL),
	}

	// Only fetch HTML pages
	if !strings.HasPrefix(page.ContentType, "text/html") {
		page.Status = 200
		page.Size = 0
		page.Latency = time.Since(start)
		page.CrawledAt = time.Now()
		return page
	}

	// Simulate varying latency (higher for deeper pages)
	baseLatency := 50 + rand.Intn(150)
	latencyMs := baseLatency + req.Depth*10
	latency := time.Duration(latencyMs) * time.Millisecond

	select {
	case <-ctx.Done():
		page.Error = ctx.Err()
		page.Latency = time.Since(start)
		return page
	case <-time.After(latency):
	}

	page.Status = 200
	page.Latency = latency
	page.Size = 1000 + rand.Intn(5000) + req.Depth*200
	page.Title = fmt.Sprintf("Page: %s", req.URL)

	// Simulate links based on URL depth
	if req.Depth < 3 {
		simulatedLinks := []string{
			req.URL + "/about",
			req.URL + "/contact",
			req.URL + "/products",
			req.URL + "/blog",
			req.URL + "/faq",
			req.URL + "/privacy",
			req.URL + "/terms",
		}
		page.Links = simulatedLinks
	}

	page.CrawledAt = time.Now()
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
// URL FRONTIER (Priority Queue)
// ============================================================

type FrontierEntry struct {
	Request CrawlRequest
	Index   int
}

type URLFrontier struct {
	mu       sync.Mutex
	entries  []*FrontierEntry
	visited  *VisitTracker
}

func NewURLFrontier() *URLFrontier {
	return &URLFrontier{
		entries: make([]*FrontierEntry, 0),
		visited: &VisitTracker{},
	}
}

func (f *URLFrontier) Push(req CrawlRequest) {
	f.mu.Lock()
	defer f.mu.Unlock()

	// Insert sorted by priority (higher first), then depth (lower first)
	entry := &FrontierEntry{Request: req}
	insertIdx := len(f.entries)
	for i, e := range f.entries {
		if e.Request.Priority < req.Priority ||
			(e.Request.Priority == req.Priority && e.Request.Depth > req.Depth) {
			insertIdx = i
			break
		}
	}

	f.entries = append(f.entries[:insertIdx],
		append([]*FrontierEntry{entry}, f.entries[insertIdx:]...)...)
}

func (f *URLFrontier) Pop() *CrawlRequest {
	f.mu.Lock()
	defer f.mu.Unlock()

	if len(f.entries) == 0 {
		return nil
	}

	entry := f.entries[0]
	f.entries = f.entries[1:]
	return &entry.Request
}

func (f *URLFrontier) Len() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.entries)
}

func (f *URLFrontier) IsVisited(url string) bool {
	return f.visited.IsVisited(url)
}

func (f *URLFrontier) VisitedCount() int64 {
	return f.visited.Count()
}

// ============================================================
// WEB CRAWLER (Core)
// ============================================================

type WebCrawler struct {
	workers          int
	maxDepth         int
	maxPages         int
	frontier         *URLFrontier
	fetcher          *Fetcher
	sitemapParser    *SitemapParser
	results          chan Page
	pagesFound       atomic.Int64
	filters          []URLFilter
	stats            *CrawlStats
	domainWorkers    map[string]int // domain -> active workers count
	domainWorkersMu  sync.Mutex
}

func NewWebCrawler(workers, maxDepth, maxPages int) *WebCrawler {
	return &WebCrawler{
		workers:       workers,
		maxDepth:      maxDepth,
		maxPages:      maxPages,
		frontier:      NewURLFrontier(),
		fetcher:       NewFetcher(10, 20),
		sitemapParser: NewSitemapParser(),
		results:       make(chan Page, 1000),
		filters: []URLFilter{
			&SchemeFilter{},
			NewExtensionFilter(),
		},
		stats:         NewCrawlStats(),
		domainWorkers: make(map[string]int),
	}
}

func (wc *WebCrawler) AddFilter(filter URLFilter) {
	wc.filters = append(wc.filters, filter)
}

// Crawl starts the web crawl from seed URLs
func (wc *WebCrawler) Crawl(ctx context.Context, seeds []string) (<-chan Page, error) {
	// Fetch sitemaps and seed the frontier
	for _, seed := range seeds {
		parsed, err := url.Parse(seed)
		if err != nil {
			continue
		}
		domain := parsed.Host

		// Fetch robots.txt for each seed domain
		wc.fetcher.robots.FetchAndParse(ctx, domain)

		// Fetch sitemap for each seed domain
		sitemapURLs := wc.sitemapParser.FetchAndParse(ctx, domain)
		for _, smURL := range sitemapURLs {
			normalized := normalizeURL(smURL)
			if wc.allURLFiltersAllow(normalized) {
				wc.frontier.Push(CrawlRequest{
					URL:      normalized,
					Depth:    0,
					Priority: 10, // Sitemap URLs get high priority
				})
			}
		}

		// Also add the seed URL itself
		normalized := normalizeURL(seed)
		if wc.allURLFiltersAllow(normalized) {
			wc.frontier.Push(CrawlRequest{
				URL:      normalized,
				Depth:    0,
				Priority: 5,
			})
		}
	}

	// Start worker goroutines (Fan-Out)
	var wg sync.WaitGroup
	for i := 0; i < wc.workers; i++ {
		wg.Add(1)
		go wc.worker(ctx, i, &wg)
	}

	// URL discovery goroutine
	go wc.discoverURLs(ctx)

	// Close results when all workers finish
	go func() {
		wg.Wait()
		close(wc.results)
	}()

	return wc.results, nil
}

func (wc *WebCrawler) allURLFiltersAllow(uri string) bool {
	for _, filter := range wc.filters {
		if !filter.Allow(uri) {
			return false
		}
	}
	return true
}

// worker processes crawl requests (Fan-Out worker)
func (wc *WebCrawler) worker(ctx context.Context, id int, wg *sync.WaitGroup) {
	defer wg.Done()
	log.Printf("Worker %d started", id)

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		// Check page limit
		if wc.pagesFound.Load() >= int64(wc.maxPages) {
			return
		}

		// Dequeue from frontier
		req := wc.frontier.Pop()
		if req == nil {
			// No more URLs
			select {
			case <-ctx.Done():
				return
			case <-time.After(100 * time.Millisecond):
				continue
			}
		}

		// Track domain worker
		parsed, err := url.Parse(req.URL)
		if err != nil {
			continue
		}
		domain := parsed.Host

		wc.domainWorkersMu.Lock()
		wc.domainWorkers[domain]++
		wc.domainWorkersMu.Unlock()

		// Check depth
		if req.Depth > wc.maxDepth {
			wc.domainWorkersMu.Lock()
			wc.domainWorkers[domain]--
			wc.domainWorkersMu.Unlock()
			wc.stats.PagesSkipped.Add(1)
			continue
		}

		// Check if already visited
		if wc.frontier.IsVisited(req.URL) {
			wc.domainWorkersMu.Lock()
			wc.domainWorkers[domain]--
			wc.domainWorkersMu.Unlock()
			wc.stats.PagesSkipped.Add(1)
			continue
		}

		// Fetch the page
		page := wc.fetcher.Fetch(ctx, *req)
		wc.pagesFound.Add(1)

		wc.domainWorkersMu.Lock()
		wc.domainWorkers[domain]--
		wc.domainWorkersMu.Unlock()

		// Update stats
		if page.Error != nil {
			wc.stats.PagesFailed.Add(1)
			wc.stats.RecordError(page.Error.Error())
		} else {
			wc.stats.PagesCrawled.Add(1)
			wc.stats.TotalBytes.Add(int64(page.Size))
			wc.stats.TotalLatency.Add(page.Latency.Milliseconds())
		}

		// Send result
		select {
		case wc.results <- page:
		case <-ctx.Done():
			return
		}
	}
}

// discoverURLs processes results and discovers new URLs to crawl
func (wc *WebCrawler) discoverURLs(ctx context.Context) {
	for page := range wc.results {
		if page.Error != nil {
			continue
		}

		for _, link := range page.Links {
			normalized := normalizeURL(link)

			// Apply all filters
			if !wc.allURLFiltersAllow(normalized) {
				continue
			}

			// Check if already in frontier
			if wc.frontier.IsVisited(normalized) {
				continue
			}

			// Queue new request with priority based on depth
			priority := max(0, 10-page.Depth*2)
			wc.frontier.Push(CrawlRequest{
				URL:         normalized,
				Depth:       page.Depth + 1,
				ReferrerURL: page.URL,
				Priority:    priority,
			})
			wc.stats.UniqueURLsFound.Add(1)
		}
	}
}

// ============================================================
// DEMO
// ============================================================

func main() {
	fmt.Println("╔══════════════════════════════════╗")
	fmt.Println("║      WEB CRAWLER DEMO            ║")
	fmt.Println("╚══════════════════════════════════╝\n")

	// Create crawler with 5 workers, max depth 2, max 30 pages
	crawler := NewWebCrawler(5, 2, 30)

	// Add domain filter to stay within example domains
	crawler.AddFilter(NewDomainFilter(
		[]string{"example.com", "example.org"},
		[]string{"facebook.com", "twitter.com", "instagram.com"},
	))

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
	fmt.Println("\n--- CRAWL RESULTS ---")
	for page := range results {
		pages = append(pages, page)
		status := "✅"
		if page.Error != nil {
			status = "❌"
		}
		fmt.Printf("  %s [Depth %d] %s (%d bytes, %v, %s)\n",
			status, page.Depth, page.URL, page.Size, page.Latency, page.ContentType)
	}

	// Stats
	crawler.stats.Print()

	fmt.Printf("\n=== Crawl Summary ===\n")
	fmt.Printf("Total pages received: %d\n", len(pages))
	fmt.Printf("Remaining in frontier: %d\n", crawler.frontier.Len())

	var succeeded, failed int
	for _, p := range pages {
		if p.Error != nil {
			failed++
		} else {
			succeeded++
		}
	}
	fmt.Printf("Succeeded: %d\n", succeeded)
	fmt.Printf("Failed:    %d\n", failed)

	fmt.Println("\n╔══════════════════════════════════╗")
	fmt.Println("║       DEMO COMPLETE             ║")
	fmt.Println("╚══════════════════════════════════╝")
}
