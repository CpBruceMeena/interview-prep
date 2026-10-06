package main

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"reflect"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func mustURL(t *testing.T, s string) *url.URL {
	t.Helper()
	u, err := url.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return u
}

func crawlURLs(t *testing.T, opts Options, seeds ...string) ([]string, Stats, error) {
	t.Helper()
	var mu sync.Mutex
	var got []string
	user := opts.OnPage
	opts.OnPage = func(p Page) error {
		mu.Lock()
		got = append(got, p.URL)
		mu.Unlock()
		if user != nil {
			return user(p)
		}
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	st, err := NewCrawler(opts).Crawl(ctx, seeds)
	sort.Strings(got)
	return got, st, err
}

func TestNormalize(t *testing.T) {
	cases := map[string]string{
		"HTTPS://Example.COM:443/a?b=2&a=1#frag":      "https://example.com/a?a=1&b=2",
		"http://example.com:80":                       "http://example.com/",
		"http://example.com:8080/x":                   "http://example.com:8080/x",
		"https://example.com/p?utm_source=x&id=7":     "https://example.com/p?id=7",
		"https://user:pw@example.com/Case/Sensitive/": "https://example.com/Case/Sensitive/",
	}
	for in, want := range cases {
		if got := Normalize(mustURL(t, in)).String(); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestExtractLinksResolvesAndDedups(t *testing.T) {
	base := mustURL(t, "https://ex.com/dir/page")
	body := []byte(`<A class="x" HREF="../up">u</A><a href='rel'>r</a><a href="/abs">a</a>
		<a href="/abs">dup</a><a href="https://other.com/x">o</a><link href="/style.css"><a name="x">`)
	var got []string
	for _, u := range ExtractLinks(base, body) {
		got = append(got, u.String())
	}
	want := []string{"https://ex.com/up", "https://ex.com/dir/rel", "https://ex.com/abs", "https://other.com/x"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("links = %v, want %v", got, want)
	}
}

func TestFilters(t *testing.T) {
	allow := AllowHosts("example.com")
	for in, want := range map[string]bool{
		"https://example.com/":      true,
		"https://www.example.com/":  true,
		"https://notexample.com/":   false,
		"https://example.com.evil/": false,
	} {
		if got := allow(mustURL(t, in)); got != want {
			t.Errorf("AllowHosts(%q) = %v", in, got)
		}
	}
	if HTTPOnly(mustURL(t, "mailto:a@b.c")) || !HTTPOnly(mustURL(t, "http://x/")) {
		t.Error("HTTPOnly")
	}
	if SkipExtensions(".pdf")(mustURL(t, "http://x/a.PDF")) {
		t.Error("SkipExtensions should be case-insensitive")
	}
}

func TestRobotsLongestMatchAndGroups(t *testing.T) {
	body := []byte(`
# comment
User-agent: otherbot
Disallow: /

User-agent: *
Disallow: /private
Allow: /private/press
Disallow: /*.json$
Disallow: /search?
Crawl-delay: 1.5
`)
	r := ParseRobots(body, "lld-crawler/1.0")
	for path, want := range map[string]bool{
		"/":                  true,
		"/private":           false,
		"/private/x":         false,
		"/private/press/kit": true,
		"/data.json":         false,
		"/data.json?x=1":     true, // '$' anchors: query follows, so no match
		"/search?q=go":       false,
		"/searching":         true,
	} {
		if got := r.Allowed(mustURL(t, "https://h"+path)); got != want {
			t.Errorf("Allowed(%q) = %v, want %v", path, got, want)
		}
	}
	if r.crawlDelay != 1500*time.Millisecond {
		t.Errorf("crawl delay = %v", r.crawlDelay)
	}
	if ParseRobots(body, "OtherBot/2").Allowed(mustURL(t, "https://h/anything")) {
		t.Error("specific user-agent group should win over *")
	}
}

func TestCrawlBFSDepthFiltersAndRobots(t *testing.T) {
	web := demoWeb()
	got, st, err := crawlURLs(t, Options{
		Workers: 4, MaxDepth: 2, Fetcher: web,
		Filters: []URLFilter{HTTPOnly, AllowHosts("example.com", "example.org"), SkipExtensions(".png")},
	}, "https://example.com/")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"https://example.com/", "https://example.com/about", "https://example.com/blog",
		"https://example.com/blog/post-1", "https://example.com/blog/post-2",
		"https://example.com/private/press", "https://example.com/private/salaries",
		"https://example.com/team", "https://example.org/", "https://example.org/docs",
		"https://example.org/missing",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("pages =\n%v\nwant\n%v", got, want)
	}
	if st.Disallowed != 1 || st.Fetched+st.Failed+st.Disallowed != len(want) {
		t.Fatalf("stats = %+v", st)
	}
	for u, n := range web.Calls {
		if n != 1 {
			t.Errorf("%s fetched %d times", u, n)
		}
	}
	if web.Calls["https://example.com/private/salaries"] != 0 {
		t.Error("robots-disallowed URL was fetched")
	}
}

func TestMaxPagesIsExact(t *testing.T) {
	pages := map[string]string{}
	for i := 0; i < 50; i++ { // a dense graph: every page links to every page
		var body string
		for j := 0; j < 50; j++ {
			body += fmt.Sprintf(`<a href="/p%d">x</a>`, j)
		}
		pages[fmt.Sprintf("https://h.com/p%d", i)] = body
	}
	web := &FakeWeb{Pages: pages, Latency: time.Millisecond}
	got, st, err := crawlURLs(t, Options{Workers: 16, MaxDepth: 10, MaxPages: 7, Fetcher: web}, "https://h.com/p0")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 7 || st.Fetched != 7 {
		t.Fatalf("crawled %d pages (stats %+v), want exactly 7", len(got), st)
	}
}

func TestPerHostPoliteness(t *testing.T) {
	var mu sync.Mutex
	starts := map[string][]time.Time{}
	pages := map[string]string{}
	for _, h := range []string{"a.com", "b.com"} {
		body := ""
		for i := 0; i < 5; i++ {
			body += fmt.Sprintf(`<a href="https://%s/%d">x</a>`, h, i)
		}
		pages["https://"+h+"/"] = body
		pages["https://"+h+"/robots.txt"] = "User-agent: *\nCrawl-delay: 0.02\n"
	}
	inner := &FakeWeb{Pages: pages}
	fetcher := fetcherFunc(func(ctx context.Context, raw string) (*Response, error) {
		u, _ := url.Parse(raw)
		if u.Path != "/robots.txt" {
			mu.Lock()
			starts[u.Host] = append(starts[u.Host], time.Now())
			mu.Unlock()
		}
		return inner.Fetch(ctx, raw)
	})
	_, _, err := crawlURLs(t, Options{Workers: 8, MaxDepth: 1, PerHostDelay: 5 * time.Millisecond, Fetcher: fetcher},
		"https://a.com/", "https://b.com/")
	if err != nil {
		t.Fatal(err)
	}
	for host, ts := range starts {
		sort.Slice(ts, func(i, j int) bool { return ts[i].Before(ts[j]) })
		// Crawl-delay (20ms) beats PerHostDelay. The turn is claimed just before
		// the fetch is recorded, so allow a little slack for that window.
		if span := ts[len(ts)-1].Sub(ts[0]); span < time.Duration(len(ts)-1)*20*time.Millisecond {
			t.Errorf("%s: %d requests in %v, faster than one per 20ms", host, len(ts), span)
		}
		for i := 1; i < len(ts); i++ {
			if gap := ts[i].Sub(ts[i-1]); gap < 19*time.Millisecond {
				t.Errorf("%s: requests %d and %d only %v apart", host, i-1, i, gap)
			}
		}
	}
	if len(starts["a.com"]) != 6 || len(starts["b.com"]) != 6 {
		t.Fatalf("starts = a:%d b:%d", len(starts["a.com"]), len(starts["b.com"]))
	}
}

type fetcherFunc func(ctx context.Context, raw string) (*Response, error)

func (f fetcherFunc) Fetch(ctx context.Context, raw string) (*Response, error) { return f(ctx, raw) }

func TestRobotsUnreachableDisallowsAll(t *testing.T) {
	fetcher := fetcherFunc(func(ctx context.Context, raw string) (*Response, error) {
		if u, _ := url.Parse(raw); u.Path == "/robots.txt" {
			return &Response{URL: raw, StatusCode: 503}, nil
		}
		return &Response{URL: raw, StatusCode: 200, ContentType: "text/html"}, nil
	})
	_, st, err := crawlURLs(t, Options{Fetcher: fetcher}, "https://down.com/")
	if err != nil || st.Disallowed != 1 || st.Fetched != 0 {
		t.Fatalf("stats=%+v err=%v", st, err)
	}
}

func TestOnPageErrorAbortsAndNoGoroutineLeak(t *testing.T) {
	before := runtime.NumGoroutine()
	stop := errors.New("stop")
	var calls atomic.Int32
	web := demoWeb()
	_, _, err := crawlURLs(t, Options{Workers: 8, MaxDepth: 5, Fetcher: web,
		Filters: []URLFilter{AllowHosts("example.com", "example.org")},
		OnPage:  func(Page) error { calls.Add(1); return stop }}, "https://example.com/")
	if !errors.Is(err, stop) || calls.Load() != 1 {
		t.Fatalf("err=%v calls=%d", err, calls.Load())
	}
	assertNoLeak(t, before)
}

func TestContextCancelStopsSlowCrawl(t *testing.T) {
	before := runtime.NumGoroutine()
	pages := map[string]string{}
	for i := 0; i < 100; i++ {
		pages[fmt.Sprintf("https://slow.com/%d", i)] = fmt.Sprintf(`<a href="/%d">n</a>`, i+1)
	}
	web := &FakeWeb{Pages: pages, Latency: time.Hour} // every fetch blocks until ctx is done
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := NewCrawler(Options{Workers: 4, MaxDepth: 200, Fetcher: web}).Crawl(ctx, []string{"https://slow.com/0"})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v", err)
	}
	if time.Since(start) > time.Second {
		t.Fatal("Crawl did not return promptly after cancellation")
	}
	assertNoLeak(t, before)
}

func TestConcurrentCrawlsOnOneCrawler(t *testing.T) {
	c := NewCrawler(Options{Workers: 4, MaxDepth: 2, Fetcher: demoWeb(),
		Filters: []URLFilter{AllowHosts("example.com")}})
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			st, err := c.Crawl(context.Background(), []string{"https://example.com/"})
			if err != nil || st.Fetched == 0 {
				t.Errorf("stats=%+v err=%v", st, err)
			}
		}()
	}
	wg.Wait()
}

func TestNoSeeds(t *testing.T) {
	if _, err := NewCrawler(Options{Fetcher: demoWeb()}).Crawl(context.Background(), []string{"::bad", "/relative"}); !errors.Is(err, ErrNoSeeds) {
		t.Fatalf("err = %v", err)
	}
}

func assertNoLeak(t *testing.T, before int) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for runtime.NumGoroutine() > before && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if n := runtime.NumGoroutine(); n > before {
		t.Fatalf("goroutine leak: %d before, %d after", before, n)
	}
}
