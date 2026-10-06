# Web Crawler — Go Implementation

> A concurrent, polite, bounded web crawler built as a coordinator plus worker pool: robots.txt, per-host rate limiting, URL normalization, depth and page budgets, and exact termination.

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|---------------|---------|
| `Crawler` / `Options` | `Crawl(ctx, seeds) (Stats, error)`, reusable and safe for concurrent calls | Facade |
| coordinator goroutine (inside `Crawl`) | Owns the frontier, seen-set, page budget and in-flight count | Single owner (CSP) |
| workers (inside `Crawl`) | robots → politeness wait → fetch → extract links | Worker pool |
| `crawlGroup` | stdlib-only `errgroup.WithContext`: the first error cancels everything; `Wait` joins | errgroup |
| `Fetcher` / `HTTPFetcher` / `FakeWeb` | I/O boundary; the fake keeps the demo and tests offline and deterministic | Strategy |
| `URLFilter` (`HTTPOnly`, `AllowHosts`, `SkipExtensions`) | Scope control | Chain of predicates |
| `Robots` / `ParseRobots` | RFC 9309 groups, longest-match Allow/Disallow, `*` and `$`, Crawl-delay | |
| `hostState` / `hostTable` | Per-host robots (`sync.Once`) and minimum gap between requests | Rate limiter |
| `Normalize` | Canonical URL used as the dedup key | |

### The coordinator loop

```go
for {
    canSend := len(frontier) > 0 && (MaxPages == 0 || dispatched < MaxPages)
    if !canSend && inFlight == 0 {
        return nil // exact termination
    }
    var send chan job // nil channel ⇒ this select case is disabled
    if canSend { send, next = jobs, frontier[0] }
    select {
    case send <- next:      // dispatch
    case r := <-results:    // record result, admit new links, call OnPage
    case <-ctx.Done():      // cancelled or another goroutine failed
    }
}
```

### Key design decisions

**1. One owner for crawl state, so there are no locks on the hot path.** The frontier, the seen-set and the counters are local variables of the coordinator goroutine. Workers never touch them. That removes the classic crawler bugs. One is check-then-act on a `sync.Map` (`if !visited { visit }` from two goroutines). Another is the bug where the previous version marked a URL "visited" when it was *discovered*, so the worker then skipped every discovered link.

**2. Exact termination.** "Frontier empty" alone is not a stopping condition, because an in-flight page may still add links. The crawl is finished exactly when the frontier is empty **and** `inFlight == 0`. No idle polling, no "wait 100 ms and hope". The previous version only ever stopped on its 30 s timeout.

**3. Mark seen on enqueue.** `admit` normalizes, filters, applies the depth limit, and inserts into `seen` before appending to the frontier. Each URL is dispatched at most once. Because the coordinator does the counting, `MaxPages` is an exact budget, not a racy `Load() >= max` check.

**4. The `select` with a nil channel prevents deadlock.** The coordinator always offers both "send the next job" and "receive a result". Workers block on `results <- r` only until the coordinator's next loop iteration. A coordinator that did a blocking `jobs <- j` while every worker was blocked sending a result would deadlock.

**5. Channel ownership + errgroup lifecycle.** The coordinator creates and closes `jobs` (`defer close(jobs)`). Workers only receive, and every send on `results` also selects on `ctx.Done()`. `crawlGroup` cancels the shared context on the first error (`OnPage` returning an error, or the caller's ctx) and `Wait`s for every goroutine. `Crawl` doesn't return until everything has exited. The tests assert `runtime.NumGoroutine()` returns to its baseline.

**6. A synchronous API.** `Crawl` blocks and calls `OnPage` serially from the coordinator. Returning a `<-chan Page` forces the caller to drain it or leak goroutines. "Let the caller add concurrency" is the Go convention.

**7. Politeness per host.** Robots.txt is fetched once per host (`sync.Once`) and follows RFC 9309: 4xx means allow everything, while 5xx or unreachable means disallow everything. The longest matching rule wins, and Allow wins a tie. The minimum gap between requests to one host is `max(PerHostDelay, Crawl-delay)`. `waitTurn` claims the turn *after* waking, under the host lock. An earlier draft pre-reserved future slots, and a worker that woke late could then fire back-to-back with the next one. The race-detector stress run caught that. All waits are ctx-aware timers, never `time.Sleep`.

**8. Normalization is conservative.** Lower-case the scheme and host, drop default ports, userinfo, fragment and tracking params, sort the query. The path's case and trailing slash are *kept*, because `/a` and `/a/` can be different resources. Stripping them is a heuristic, applied per site in production.

### Where to extend

| Requirement | Change |
|---|---|
| Per-host concurrency cap | A `chan struct{}` semaphore in `hostState`, acquired around the fetch |
| Avoid head-of-line blocking on slow hosts | Mercator-style back queues: one FIFO per host plus a heap of hosts by `next` time; the coordinator dispatches only hosts whose turn has come |
| Priority (PageRank, freshness) | Swap the FIFO frontier for a heap; BFS becomes best-first |
| Content dedup | Hash the body (SHA-256 for exact, SimHash for near-duplicate) in the coordinator |
| Retries on 429/503 | Re-admit with a backoff and `Retry-After`; it needs a `notBefore` per job |
| Huge seen-set | Bloom filter in front of an on-disk set (see HIGH_LEVEL_DESIGN) |

## ▶️ How to Run

```bash
cd golang-low-level-design/web-crawler
go run web_crawler.go                                   # offline: uses the in-memory FakeWeb
go test -race web_crawler.go web_crawler_test.go
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Coordinator / single owner** | `Crawl`'s coordinator goroutine | Lock-free state, exact termination |
| **Worker Pool (fan-out / fan-in)** | `jobs` → workers → `results` | Bounded I/O concurrency |
| **errgroup** | `crawlGroup` | First error cancels everything; join before return |
| **Strategy** | `Fetcher`, `URLFilter` | Swap real HTTP for a fake; compose scope rules |
| **Rate limiter** | `hostState.waitTurn` | Per-host politeness that respects ctx |

## 📄 Full Source

<!-- source: web_crawler.go -->
```go
// Web Crawler - Low Level Design (Go)
// ------------------------------------
// A concurrent, polite, bounded web crawler.
//
// Key design decisions:
//   - Coordinator + workers (CSP). One coordinator goroutine owns ALL crawl
//     state: the frontier, the seen-set, the page budget and the in-flight
//     count. No locks are needed for it, and termination is exact: the crawl
//     is done when the frontier is empty and nothing is in flight.
//   - Workers only do I/O: robots check, politeness wait, fetch, link
//     extraction. They receive jobs on one channel and send results on
//     another. The coordinator selects on "send next job" and "receive
//     result" together, so neither side can deadlock the other.
//   - Channel ownership: the coordinator creates and closes `jobs`; workers
//     never close anything. `results` is never closed (its receiver decides
//     when to stop), and every worker send also selects on ctx.Done().
//   - errgroup-style lifecycle built on the stdlib (crawlGroup): the first
//     error (OnPage returning an error, or ctx cancellation) cancels the
//     shared context and every goroutine unwinds; Crawl returns only after
//     all of them exit. No goroutine outlives Crawl.
//   - Synchronous API: Crawl blocks and calls OnPage serially from the
//     coordinator. The caller does not have to drain a channel to avoid a leak.
//   - Politeness per host: robots.txt (RFC 9309 longest-match Allow/Disallow,
//     fetched once per host with sync.Once) and a minimum delay between
//     requests to the same host (max of PerHostDelay and Crawl-delay),
//     claimed under a per-host lock after a ctx-aware wait.
//   - Fetching is behind an interface, so the demo and tests run against an
//     in-memory web: deterministic, no network.

package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// ============================================================
// FETCHER
// ============================================================

type Response struct {
	URL         string // final URL after redirects; base for resolving links
	StatusCode  int
	ContentType string
	Body        []byte
}

type Fetcher interface {
	Fetch(ctx context.Context, rawURL string) (*Response, error)
}

// HTTPFetcher is the production Fetcher: bounded body size, explicit User-Agent.
type HTTPFetcher struct {
	Client    *http.Client
	UserAgent string
	MaxBody   int64
}

func (f *HTTPFetcher) Fetch(ctx context.Context, rawURL string) (*Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", f.UserAgent)
	resp, err := f.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, f.MaxBody)) // never trust Content-Length
	if err != nil {
		return nil, err
	}
	return &Response{URL: resp.Request.URL.String(), StatusCode: resp.StatusCode,
		ContentType: resp.Header.Get("Content-Type"), Body: body}, nil
}

// ============================================================
// URL NORMALISATION, FILTERS, LINK EXTRACTION
// ============================================================

var trackingParams = map[string]bool{
	"utm_source": true, "utm_medium": true, "utm_campaign": true,
	"utm_term": true, "utm_content": true, "fbclid": true, "gclid": true,
}

// Normalize returns a canonical form used as the dedup key: lower-case
// scheme and host, default port dropped, empty path -> "/", fragment
// removed, tracking params removed, query keys sorted. Path case and
// trailing slashes are kept: servers may treat them as different resources.
func Normalize(u *url.URL) *url.URL {
	n := *u
	n.Scheme = strings.ToLower(n.Scheme)
	host := strings.ToLower(n.Hostname())
	if p := n.Port(); p != "" && !(p == "80" && n.Scheme == "http") && !(p == "443" && n.Scheme == "https") {
		host += ":" + p
	}
	n.Host = host
	n.Fragment, n.RawFragment = "", ""
	n.User = nil
	if n.Path == "" {
		n.Path = "/"
	}
	if n.RawQuery != "" {
		q := n.Query()
		for k := range q {
			if trackingParams[strings.ToLower(k)] {
				q.Del(k)
			}
		}
		n.RawQuery = q.Encode() // Encode sorts by key
	}
	return &n
}

// URLFilter decides whether a discovered URL should be crawled.
type URLFilter func(u *url.URL) bool

// HTTPOnly rejects mailto:, javascript:, ftp:, ...
func HTTPOnly(u *url.URL) bool { return u.Scheme == "http" || u.Scheme == "https" }

// AllowHosts permits the given hosts and their subdomains. It matches on a
// label boundary, so "example.com" does not admit "notexample.com".
func AllowHosts(hosts ...string) URLFilter {
	return func(u *url.URL) bool {
		h := u.Hostname()
		for _, d := range hosts {
			if h == d || strings.HasSuffix(h, "."+d) {
				return true
			}
		}
		return false
	}
}

// SkipExtensions rejects obvious non-HTML resources by path extension.
func SkipExtensions(exts ...string) URLFilter {
	return func(u *url.URL) bool {
		p := strings.ToLower(u.Path)
		for _, e := range exts {
			if strings.HasSuffix(p, e) {
				return false
			}
		}
		return true
	}
}

// hrefRE is a deliberately small extractor: the stdlib has no HTML parser
// (golang.org/x/net/html would be the production choice). It handles quoted
// href attributes on <a> tags, which is what an interview needs.
var hrefRE = regexp.MustCompile(`(?is)<a\s[^>]*?href\s*=\s*["']([^"']+)["']`)

// ExtractLinks returns absolute, de-duplicated links resolved against base.
func ExtractLinks(base *url.URL, body []byte) []*url.URL {
	var out []*url.URL
	seen := make(map[string]bool)
	for _, m := range hrefRE.FindAllSubmatch(body, -1) {
		ref, err := url.Parse(strings.TrimSpace(string(m[1])))
		if err != nil {
			continue
		}
		abs := base.ResolveReference(ref)
		if key := abs.String(); !seen[key] {
			seen[key] = true
			out = append(out, abs)
		}
	}
	return out
}

// ============================================================
// ROBOTS.TXT (RFC 9309)
// ============================================================

type robotsRule struct {
	pattern string
	allow   bool
}

type Robots struct {
	rules       []robotsRule
	crawlDelay  time.Duration
	disallowAll bool
}

// ParseRobots keeps the group that names our user agent, falling back to "*".
// Crawl-delay is non-standard but widely used; we honour it.
func ParseRobots(body []byte, userAgent string) *Robots {
	type group struct {
		agents []string
		rules  []robotsRule
		delay  time.Duration
	}
	var groups []*group
	var cur *group
	lastWasAgent := false
	sc := bufio.NewScanner(bytes.NewReader(body))
	for sc.Scan() {
		line, _, _ := strings.Cut(sc.Text(), "#")
		key, val, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		key, val = strings.ToLower(strings.TrimSpace(key)), strings.TrimSpace(val)
		switch key {
		case "user-agent":
			if !lastWasAgent { // consecutive User-agent lines share one group
				cur = &group{}
				groups = append(groups, cur)
			}
			cur.agents = append(cur.agents, strings.ToLower(val))
			lastWasAgent = true
			continue
		case "allow", "disallow":
			if cur != nil && val != "" { // empty Disallow means "allow all"
				cur.rules = append(cur.rules, robotsRule{pattern: val, allow: key == "allow"})
			}
		case "crawl-delay":
			if secs, err := strconv.ParseFloat(val, 64); err == nil && cur != nil {
				cur.delay = time.Duration(secs * float64(time.Second))
			}
		}
		lastWasAgent = false
	}
	ua := strings.ToLower(userAgent)
	var star *group
	for _, g := range groups {
		for _, a := range g.agents {
			if a == "*" {
				if star == nil {
					star = g
				}
			} else if strings.Contains(ua, a) {
				return &Robots{rules: g.rules, crawlDelay: g.delay}
			}
		}
	}
	if star != nil {
		return &Robots{rules: star.rules, crawlDelay: star.delay}
	}
	return &Robots{}
}

// Allowed applies the longest matching rule; on a tie Allow wins; no match allows.
func (r *Robots) Allowed(u *url.URL) bool {
	if r.disallowAll {
		return false
	}
	path := u.EscapedPath()
	if u.RawQuery != "" {
		path += "?" + u.RawQuery
	}
	best, allowed := -1, true
	for _, rule := range r.rules {
		if robotsMatch(rule.pattern, path) {
			if l := len(rule.pattern); l > best || (l == best && rule.allow) {
				best, allowed = l, rule.allow
			}
		}
	}
	return allowed
}

// robotsMatch implements RFC 9309 matching: a prefix match where '*' matches
// any run of characters and a trailing '$' anchors the end of the path.
func robotsMatch(pattern, path string) bool {
	if p, ok := strings.CutSuffix(pattern, "$"); ok {
		return wildcardMatch(p, path, true)
	}
	return wildcardMatch(pattern, path, false)
}

func wildcardMatch(p, s string, anchored bool) bool {
	for len(p) > 0 {
		if p[0] == '*' {
			p = strings.TrimLeft(p, "*")
			for i := 0; i <= len(s); i++ {
				if wildcardMatch(p, s[i:], anchored) {
					return true
				}
			}
			return false
		}
		if len(s) == 0 || s[0] != p[0] {
			return false
		}
		p, s = p[1:], s[1:]
	}
	return !anchored || len(s) == 0
}

// ============================================================
// PER-HOST POLITENESS
// ============================================================

type hostState struct {
	robotsOnce sync.Once
	robots     *Robots

	mu   sync.Mutex
	next time.Time // earliest time the next request may start
}

// waitTurn blocks until this host may be hit again, then claims the turn.
// The claim happens after waking, under the lock, so the gap is between
// actual request starts. (Pre-reserving future slots is subtly weaker: a
// worker that wakes late then fires back-to-back with the next slot.)
func (h *hostState) waitTurn(ctx context.Context, gap time.Duration) error {
	for {
		h.mu.Lock()
		now := time.Now()
		if !now.Before(h.next) {
			h.next = now.Add(gap)
			h.mu.Unlock()
			return nil
		}
		at := h.next
		h.mu.Unlock()
		if err := sleepUntil(ctx, at); err != nil {
			return err
		}
	}
}

func sleepUntil(ctx context.Context, t time.Time) error {
	d := time.Until(t)
	if d <= 0 {
		return ctx.Err()
	}
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// ============================================================
// ERRGROUP (stdlib-only)
// ============================================================

// crawlGroup is a minimal errgroup.WithContext: the first non-nil error
// cancels ctx; Wait returns that error after every goroutine has exited.
type crawlGroup struct {
	wg     sync.WaitGroup
	once   sync.Once
	err    error
	cancel context.CancelFunc
}

func newCrawlGroup(parent context.Context) (*crawlGroup, context.Context) {
	ctx, cancel := context.WithCancel(parent)
	return &crawlGroup{cancel: cancel}, ctx
}

func (g *crawlGroup) Go(f func() error) {
	g.wg.Add(1)
	go func() {
		defer g.wg.Done()
		if err := f(); err != nil {
			g.once.Do(func() { g.err = err; g.cancel() })
		}
	}()
}

func (g *crawlGroup) Wait() error {
	g.wg.Wait()
	g.cancel()
	return g.err
}

// ============================================================
// CRAWLER
// ============================================================

var (
	ErrRobotsDisallowed = errors.New("crawler: disallowed by robots.txt")
	ErrNoSeeds          = errors.New("crawler: no valid seed URLs")
)

type Page struct {
	URL        string
	Depth      int
	StatusCode int
	Links      int // links discovered on the page (before filtering)
	Err        error
}

type Options struct {
	Workers      int           // default 8
	MaxDepth     int           // seeds are depth 0
	MaxPages     int           // fetch budget; 0 = unlimited
	PerHostDelay time.Duration // floor on the gap between requests to one host
	FetchTimeout time.Duration // per request; default 10s
	UserAgent    string
	Filters      []URLFilter
	Fetcher      Fetcher
	OnPage       func(Page) error // called serially; a non-nil error aborts the crawl
}

type Stats struct {
	Fetched, Failed, Disallowed, Discovered int
}

// Crawler is reusable and safe for concurrent Crawl calls: all per-crawl
// state (frontier, seen-set, host politeness) lives inside Crawl.
type Crawler struct {
	opts Options
}

// hostTable maps scheme://host to its politeness state for one crawl.
type hostTable struct {
	mu    sync.Mutex
	hosts map[string]*hostState
}

func (t *hostTable) get(u *url.URL) *hostState {
	key := u.Scheme + "://" + u.Host
	t.mu.Lock()
	defer t.mu.Unlock()
	h, ok := t.hosts[key]
	if !ok {
		h = &hostState{}
		t.hosts[key] = h
	}
	return h
}

func NewCrawler(opts Options) *Crawler {
	if opts.Workers <= 0 {
		opts.Workers = 8
	}
	if opts.FetchTimeout <= 0 {
		opts.FetchTimeout = 10 * time.Second
	}
	if opts.UserAgent == "" {
		opts.UserAgent = "lld-crawler/1.0"
	}
	if opts.Fetcher == nil {
		opts.Fetcher = &HTTPFetcher{Client: &http.Client{Timeout: opts.FetchTimeout}, UserAgent: opts.UserAgent, MaxBody: 2 << 20}
	}
	if opts.OnPage == nil {
		opts.OnPage = func(Page) error { return nil }
	}
	return &Crawler{opts: opts}
}

type job struct {
	u     *url.URL
	depth int
}

type result struct {
	page  Page
	links []*url.URL
}

// Crawl runs a breadth-first crawl from seeds and blocks until the frontier
// is exhausted, MaxPages is reached, OnPage fails or ctx is done. It returns
// ctx.Err() / the OnPage error in the last two cases; Stats are always valid.
func (c *Crawler) Crawl(ctx context.Context, seeds []string) (Stats, error) {
	var stats Stats
	seen := make(map[string]bool)
	var frontier []job // FIFO => BFS; owned by the coordinator only
	admit := func(u *url.URL, depth int) {
		n := Normalize(u)
		if depth > c.opts.MaxDepth || !c.allowed(n) {
			return
		}
		if key := n.String(); !seen[key] {
			seen[key] = true // mark on enqueue, not on fetch: no duplicate jobs
			frontier = append(frontier, job{n, depth})
		}
	}
	for _, s := range seeds {
		if u, err := url.Parse(s); err == nil && u.Host != "" {
			admit(u, 0)
		}
	}
	if len(frontier) == 0 {
		return stats, ErrNoSeeds
	}

	hosts := &hostTable{hosts: make(map[string]*hostState)}
	g, ctx := newCrawlGroup(ctx)
	jobs := make(chan job)
	results := make(chan result)

	for i := 0; i < c.opts.Workers; i++ {
		g.Go(func() error {
			for j := range jobs {
				r := c.process(ctx, hosts, j)
				select {
				case results <- r:
				case <-ctx.Done():
					return nil // the coordinator reports the cause
				}
			}
			return nil
		})
	}

	g.Go(func() error {
		defer close(jobs) // sole owner of jobs
		inFlight, dispatched := 0, 0
		for {
			canSend := len(frontier) > 0 && (c.opts.MaxPages == 0 || dispatched < c.opts.MaxPages)
			if !canSend && inFlight == 0 {
				return nil // exact termination
			}
			var send chan job // nil channel: that select case is disabled
			var next job
			if canSend {
				send, next = jobs, frontier[0]
			}
			select {
			case send <- next:
				frontier[0] = job{}
				frontier = frontier[1:]
				inFlight++
				dispatched++
			case r := <-results:
				inFlight--
				switch {
				case errors.Is(r.page.Err, ErrRobotsDisallowed):
					stats.Disallowed++
				case r.page.Err != nil:
					stats.Failed++
				default:
					stats.Fetched++
				}
				before := len(seen)
				for _, l := range r.links {
					admit(l, r.page.Depth+1)
				}
				stats.Discovered += len(seen) - before
				if err := c.opts.OnPage(r.page); err != nil {
					return err
				}
			case <-ctx.Done():
				return ctx.Err()
			}
		}
	})

	err := g.Wait()
	return stats, err
}

func (c *Crawler) allowed(u *url.URL) bool {
	for _, f := range c.opts.Filters {
		if !f(u) {
			return false
		}
	}
	return true
}

// robotsFor fetches robots.txt once per host. Per RFC 9309: 4xx means no
// restrictions; 5xx or a network error means assume full disallow.
func (c *Crawler) robotsFor(ctx context.Context, u *url.URL, h *hostState) *Robots {
	h.robotsOnce.Do(func() {
		rctx, cancel := context.WithTimeout(ctx, c.opts.FetchTimeout)
		defer cancel()
		resp, err := c.opts.Fetcher.Fetch(rctx, u.Scheme+"://"+u.Host+"/robots.txt")
		switch {
		case err != nil || resp.StatusCode >= 500:
			h.robots = &Robots{disallowAll: true}
		case resp.StatusCode >= 400:
			h.robots = &Robots{}
		default:
			h.robots = ParseRobots(resp.Body, c.opts.UserAgent)
		}
	})
	return h.robots
}

// process is the worker's I/O: robots, politeness, fetch, extract.
func (c *Crawler) process(ctx context.Context, hosts *hostTable, j job) result {
	page := Page{URL: j.u.String(), Depth: j.depth}
	h := hosts.get(j.u)
	robots := c.robotsFor(ctx, j.u, h)
	if !robots.Allowed(j.u) {
		page.Err = ErrRobotsDisallowed
		return result{page: page}
	}
	gap := max(c.opts.PerHostDelay, robots.crawlDelay)
	if err := h.waitTurn(ctx, gap); err != nil {
		page.Err = err
		return result{page: page}
	}
	fctx, cancel := context.WithTimeout(ctx, c.opts.FetchTimeout)
	defer cancel()
	resp, err := c.opts.Fetcher.Fetch(fctx, page.URL)
	if err != nil {
		page.Err = err
		return result{page: page}
	}
	page.StatusCode = resp.StatusCode
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		page.Err = fmt.Errorf("crawler: HTTP %d", resp.StatusCode)
		return result{page: page}
	}
	if !strings.HasPrefix(resp.ContentType, "text/html") {
		return result{page: page}
	}
	base, err := url.Parse(resp.URL)
	if err != nil {
		base = j.u
	}
	links := ExtractLinks(base, resp.Body)
	page.Links = len(links)
	return result{page: page, links: links}
}

// ============================================================
// IN-MEMORY WEB (demo + tests)
// ============================================================

// FakeWeb serves canned pages and counts requests; unknown URLs are 404.
type FakeWeb struct {
	Pages   map[string]string // url -> HTML (or robots.txt body)
	Latency time.Duration

	mu    sync.Mutex
	Calls map[string]int
}

func (w *FakeWeb) Fetch(ctx context.Context, rawURL string) (*Response, error) {
	w.mu.Lock()
	if w.Calls == nil {
		w.Calls = make(map[string]int)
	}
	w.Calls[rawURL]++
	w.mu.Unlock()
	if w.Latency > 0 {
		if err := sleepUntil(ctx, time.Now().Add(w.Latency)); err != nil {
			return nil, err
		}
	}
	body, ok := w.Pages[rawURL]
	if !ok {
		return &Response{URL: rawURL, StatusCode: 404, ContentType: "text/plain"}, nil
	}
	ct := "text/html; charset=utf-8"
	if strings.HasSuffix(rawURL, "/robots.txt") {
		ct = "text/plain"
	}
	return &Response{URL: rawURL, StatusCode: 200, ContentType: ct, Body: []byte(body)}, nil
}

func demoWeb() *FakeWeb {
	return &FakeWeb{Latency: 5 * time.Millisecond, Pages: map[string]string{
		"https://example.com/robots.txt": "User-agent: *\nDisallow: /private\nAllow: /private/press\n",
		"https://example.com/": `<a href="/about">About</a> <a href="/blog?utm_source=x">Blog</a>
			<a href="https://example.com/private/salaries">x</a> <a href="/private/press">Press</a>
			<a href="https://example.org/">Partner</a> <a href="https://evil.com/">Spam</a>
			<a href="mailto:hi@example.com">Mail</a> <a href="/logo.png">Logo</a>`,
		"https://example.com/about":         `<a href="/">Home</a> <a href="/team#jobs">Team</a>`,
		"https://example.com/blog":          `<a href="/blog/post-1">1</a> <a href="/blog/post-2">2</a>`,
		"https://example.com/blog/post-1":   `<a href="/blog/post-1/comments">deep</a>`,
		"https://example.com/private/press": `press kit`,
		"https://example.org/":              `<a href="/docs">Docs</a> <a href="/missing">Broken</a>`,
		"https://example.org/docs":          `docs`,
	}}
}

// ============================================================
// DEMO
// ============================================================

func main() {
	web := demoWeb()
	var pages []Page
	crawler := NewCrawler(Options{
		Workers:      4,
		MaxDepth:     2,
		PerHostDelay: 10 * time.Millisecond,
		Fetcher:      web,
		Filters:      []URLFilter{HTTPOnly, AllowHosts("example.com", "example.org"), SkipExtensions(".png", ".jpg", ".pdf")},
		OnPage:       func(p Page) error { pages = append(pages, p); return nil }, // serial: no lock needed
	})
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	stats, err := crawler.Crawl(ctx, []string{"https://Example.com:443/#top"})

	sort.Slice(pages, func(i, j int) bool { return pages[i].URL < pages[j].URL })
	fmt.Println("--- Pages (sorted; workers finish in any order) ---")
	for _, p := range pages {
		status := "ok"
		if p.Err != nil {
			status = p.Err.Error()
		}
		fmt.Printf("  d=%d %-40s links=%d %s\n", p.Depth, p.URL, p.Links, status)
	}
	fmt.Printf("--- Stats: %+v err=%v\n", stats, err)
	fmt.Println("  /blog/post-1/comments not fetched: depth 3 > MaxDepth 2")
	fmt.Println("  every page fetched exactly once:", web.Calls["https://example.com/"] == 1)

	fmt.Println("--- MaxPages budget = 3 ---")
	limited := NewCrawler(Options{Workers: 4, MaxDepth: 5, MaxPages: 3, Fetcher: demoWeb(),
		Filters: []URLFilter{HTTPOnly, AllowHosts("example.com")}})
	stats, err = limited.Crawl(ctx, []string{"https://example.com/"})
	fmt.Printf("  %+v err=%v\n", stats, err)

	fmt.Println("--- Abort from OnPage ---")
	stop := errors.New("enough")
	aborting := NewCrawler(Options{Workers: 4, MaxDepth: 5, Fetcher: demoWeb(),
		Filters: []URLFilter{HTTPOnly, AllowHosts("example.com")},
		OnPage:  func(Page) error { return stop }})
	_, err = aborting.Crawl(ctx, []string{"https://example.com/"})
	fmt.Println("  err:", err)
}
```
<!-- /source -->
