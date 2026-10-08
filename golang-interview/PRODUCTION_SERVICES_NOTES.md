# 🚀 Go in Production: HTTP, Databases, Performance Debugging, Project Structure

> **What a staff Go engineer is expected to know about running services**, beyond the language. HTTP server/client defaults that bite, `database/sql` pool tuning, a step-by-step performance-debugging playbook, package layout, and the questions interviewers ask. The HTTP snippet was compiled and run with Go 1.26.
>
> Companion files: [Interview Questions](INTERVIEW_QUESTIONS.md) Q7/Q12 (context, graceful shutdown), [Concurrency Coding Challenges](CONCURRENCY_CODING_CHALLENGES.md).

---

## Table of Contents

1. [`net/http` server and client: the defaults are unsafe](#1-nethttp-server-and-client)
2. [`database/sql`: pool sizing and failure modes](#2-databasesql)
3. [Performance debugging playbook](#3-performance-debugging-playbook)
4. [Project layout, modules, and API boundaries](#4-project-layout-modules-and-api-boundaries)
5. [Service checklist](#5-service-readiness-checklist)
6. [Interview questions](#6-interview-questions)

---

## 1. `net/http` server and client

### The server: set every timeout

A zero-value `http.Server` has **no timeouts**. One slow client (slow-loris) can hold a connection and a goroutine indefinitely.

```go
func newServer(h http.Handler) *http.Server {
    return &http.Server{
        Handler:           h,
        ReadHeaderTimeout: 5 * time.Second,  // slow-loris defence
        ReadTimeout:       15 * time.Second, // whole request incl. body
        WriteTimeout:      30 * time.Second, // handler + response write
        IdleTimeout:       60 * time.Second, // keep-alive connections
        MaxHeaderBytes:    1 << 20,
    }
}
```

- `WriteTimeout` is a blunt instrument for streaming/SSE responses; use `http.NewResponseController(w).SetWriteDeadline(...)` per write.
- Per-request deadlines belong in `context` (`http.TimeoutHandler` or your own middleware) so downstream calls are cancelled too. A server timeout closes the connection but **does not cancel your handler's work** unless it honors `r.Context()`.
- `r.Context()` is cancelled when the client disconnects. Pass it to every downstream call.
- Go 1.22+ `ServeMux` supports methods and wildcards: `mux.HandleFunc("GET /items/{id}", ...)` with `r.PathValue("id")`. The standard mux is enough for many services.
- **Graceful shutdown:** `srv.Shutdown(ctx)` stops accepting, waits for in-flight requests. On Kubernetes, sleep a few seconds first (readiness propagation), then shut down, then exit; see Interview Q12.

### The client: `http.DefaultClient` has no timeout

```go
func newClient() *http.Client {
    return &http.Client{
        Timeout: 10 * time.Second, // total, including reading the body
        Transport: &http.Transport{
            MaxIdleConns:        100,
            MaxIdleConnsPerHost: 20, // default is only 2!
            IdleConnTimeout:     90 * time.Second,
            TLSHandshakeTimeout: 5 * time.Second,
        },
    }
}

func fetch(ctx context.Context, c *http.Client, url string) ([]byte, error) {
    req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
    if err != nil { return nil, err }
    resp, err := c.Do(req)
    if err != nil { return nil, err }
    defer resp.Body.Close() // always, even for non-2xx
    if resp.StatusCode != http.StatusOK {
        io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10)) // drain so the conn is reusable
        return nil, fmt.Errorf("status %d", resp.StatusCode)
    }
    return io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // never trust remote sizes
}
```

Output of the verified program: `item 42 <nil>`, `status 404`, `shutdown: <nil>`.

Classic bugs this prevents:

| Bug | Symptom | Fix |
|---|---|---|
| Forgot `resp.Body.Close()` | goroutine + FD leak, "too many open files" | `defer` right after the error check |
| Didn't drain body | new TCP+TLS handshake per request, high latency | drain (bounded) before close |
| `MaxIdleConnsPerHost` = 2 | connection churn under concurrency to one host | raise to match concurrency |
| One shared client **per request** | no reuse, ephemeral port exhaustion | create once, reuse (it's goroutine-safe) |
| No timeout | goroutines pile up behind a hung dependency | `Client.Timeout` and ctx deadlines |
| `ReadAll` on untrusted body | OOM | `LimitReader` / `http.MaxBytesReader` on the server |

HTTP/2 is enabled automatically for HTTPS (client and server). Custom `Transport` fields that disable it (e.g. custom `DialContext` without `ForceAttemptHTTP2`) are a common reason for "why isn't this using h2".

---

## 2. `database/sql`

`*sql.DB` is not a connection; it is a **pool** and is safe for concurrent use. Create one per database, share it.

```go
db.SetMaxOpenConns(25)                  // cap vs DB max_connections / instance count
db.SetMaxIdleConns(25)                  // keep == open to avoid reconnect churn
db.SetConnMaxLifetime(30 * time.Minute) // survive LB / failover / DNS changes
db.SetConnMaxIdleTime(5 * time.Minute)
```

**Sizing:** `max_open_conns × number_of_instances` must stay **below** the database's connection limit, with headroom for migrations and admin. Default max open is **unlimited**, so a traffic spike can open thousands of connections and take the database down. More connections rarely mean more throughput; past a point they cause lock and CPU contention on the server. With Postgres, put PgBouncer in front for many instances.

**Rules that prevent leaks and deadlocks:**

- Always `defer rows.Close()` and check `rows.Err()` after the loop. A leaked `Rows` or `Tx` pins a connection forever; enough of them and every request blocks waiting for the pool.
- Use the `...Context` methods so a cancelled request releases its connection.
- A transaction holds **one** connection. Inside it, use `tx.QueryContext`, **not** `db.QueryContext`, or you take a second connection and can deadlock when the pool is exhausted (N requests each holding a tx connection and waiting for another).
- `defer tx.Rollback()` immediately after `Begin`; after a successful `Commit` it is a harmless no-op.
- Check `db.Stats()` (`WaitCount`, `WaitDuration`, `InUse`, `Idle`) and export it as metrics. Rising `WaitDuration` is pool starvation, the first thing to check when latency rises without CPU rising.
- Scanning `NULL` into a plain `int`/`string` errors; use `sql.NullString`/`*string`/`sql.Null[T]` (Go 1.22).
- Retry transaction serialization failures (Postgres `40001`, deadlock `40P01`), with backoff, as a unit (the whole tx), never a single statement.

```go
func withTx(ctx context.Context, db *sql.DB, fn func(*sql.Tx) error) (err error) {
    tx, err := db.BeginTx(ctx, nil)
    if err != nil { return err }
    defer func() {
        if p := recover(); p != nil { _ = tx.Rollback(); panic(p) }
        if err != nil { _ = tx.Rollback() }
    }()
    if err = fn(tx); err != nil { return err }
    return tx.Commit()
}
```

For anything beyond simple queries consider `pgx` (native Postgres, better types and batching) and code generators (`sqlc`) over heavy ORMs: you keep SQL visible and type-checked at compile time.

---

## 3. Performance debugging playbook

**"The service is slow / using too much CPU / memory."** Don't guess. Follow the evidence.

1. **Define the symptom with numbers** (p50/p99 latency, CPU %, RSS, GC %, goroutine count, error rate) and *when it started* (deploy? traffic? dependency?).
2. **Check the cheap global signals first:** goroutine count (leaks), `db.Stats()` wait time (pool starvation), GC pause/frequency, container CPU throttling (cgroup limits; Go 1.25+ sets `GOMAXPROCS` from the CPU limit, older versions don't), downstream latency.
3. **Profile in production, safely.** Expose `net/http/pprof` on an **internal-only port** (never the public mux).

```bash
go tool pprof -http=:8081 http://svc:6060/debug/pprof/profile?seconds=30   # CPU
go tool pprof -http=:8081 http://svc:6060/debug/pprof/heap                  # live memory (inuse_space)
go tool pprof -sample_index=alloc_space .../heap                            # allocation churn → GC pressure
go tool pprof http://svc:6060/debug/pprof/goroutine                         # leaks, blocked goroutines
go tool pprof http://svc:6060/debug/pprof/mutex                             # lock contention (needs SetMutexProfileFraction)
go tool pprof http://svc:6060/debug/pprof/block                             # blocking (needs SetBlockProfileRate)
curl -o trace.out 'http://svc:6060/debug/pprof/trace?seconds=5' && go tool trace trace.out   # scheduler, GC, latency
```

4. **Read the profile right.** CPU profile says *where time is spent on-CPU*; it won't show waiting. If latency is high but CPU is low, you're **blocked**: use the block/mutex profiles, the goroutine profile (thousands in the same `select`/`Lock` is a smoking gun), or the execution trace.
5. **High GC share** (`runtime.gcBgMarkWorker`, `mallocgc` near the top)? Reduce allocations: preallocate slices/maps, reuse buffers (`sync.Pool`, only with measurement), avoid `fmt.Sprintf` and `[]byte`↔`string` in hot paths, pass pointers to avoid copies only where measurements justify it. Use `GOMEMLIMIT` (soft memory cap) with `GOGC` tuned, e.g. `GOMEMLIMIT` ≈ 90% of the container limit, to avoid OOM kills without thrashing.
6. **Check escape analysis** on the hot function: `go build -gcflags='-m=2'`. Fix only what shows up in the profile.
7. **Benchmark the fix** with `testing.B` (`for b.Loop()` since 1.24), `-benchmem`, `-count=10`, and compare with `benchstat`. A change you can't measure didn't happen.
8. **Use PGO** (`default.pgo` from a production CPU profile, in the main package directory) for typically single-digit-percent wins at no code cost.
9. **Race and leak checks:** `go test -race` in CI; compare goroutine profiles over time; `goleak` or `synctest` in tests; the `goroutineleak` profile (1.27) in prod.
10. **Write down** what the root cause was and add a regression benchmark or alert.

### Memory growth triage

| Symptom | Likely cause | Evidence |
|---|---|---|
| Goroutines grow linearly | leak: unbuffered send with no receiver, missing ctx, ticker not stopped | goroutine profile grouped by stack |
| `inuse_space` grows, goroutines flat | unbounded cache/map, retained sub-slices, global slices | heap profile top entries |
| RSS ≫ `inuse_space` | fragmentation, huge transient allocations not yet returned to the OS, cgo/mmap | `runtime.MemStats`, `GODEBUG=madvdontneed=1`, check non-Go memory |
| Sawtooth RSS, frequent GC, high CPU | allocation churn | `alloc_space` profile, `GODEBUG=gctrace=1` |
| OOM-killed but heap looks fine | goroutine stacks, cgo, `GOMEMLIMIT` unset, limit too close | `StackInuse`, `/proc/<pid>/smaps` |

---

## 4. Project layout, modules, and API boundaries

There is no official "standard layout." Prefer **simple and flat** until the code forces structure.

```
svc/
  go.mod
  cmd/svc/main.go        # wiring only: config, construct, start, signal handling
  internal/              # compiler-enforced: not importable from other modules
    orders/              # package per domain concept, not per layer
      service.go
      store.go           # defines the small interface it needs
      http.go
    platform/            # db, logging, config helpers
  api/                   # openapi / proto definitions (generated code elsewhere)
```

- **`internal/`** is the strongest tool you have for keeping an API small. Export as little as possible; everything exported is a promise.
- **Package by domain,** not `models/`, `controllers/`, `utils/` (which invite import cycles and meaningless names). A package name should say what it provides: `orders`, not `common`.
- **Interfaces belong to the consumer.** `orders` declares `type Store interface{...}` with just the methods it calls. Don't create an interface alongside each implementation "for testing."
- **Constructors and explicit dependencies,** no global state or `init()` side effects. `main` is the only place that wires things together.
- **Config:** env vars → a typed struct validated at startup; fail fast.
- **Errors at boundaries:** wrap with `%w` and context inside; translate to status codes/gRPC codes at the edge; log once, where handled (see Interview Q8).
- **Modules:** semantic import versioning (`/v2` suffix for v2+); MVS picks the *minimum* version satisfying all requirements (no lockfile surprises); `go.sum` is checksum DB verification; use `go mod tidy`, `govulncheck` in CI, `replace` only for local development. The `go` line in `go.mod` selects language semantics (e.g. loop variables) and the `toolchain` line pins the compiler.
- **Tooling baseline in CI:** `gofmt`/`goimports`, `go vet`, `staticcheck` or `golangci-lint`, `go test -race ./...`, `govulncheck ./...`.
- **Testing structure:** table-driven tests with `t.Run`, `t.Parallel()` where safe, `testing/synctest` for time/concurrency, fuzz tests for parsers, `httptest` for handlers, testcontainers for real databases, golden files for stable outputs.

---

## 5. Service readiness checklist

- [ ] Server timeouts set; client has timeout; connection pools sized
- [ ] Every outbound call takes a `context` with a deadline derived from the request
- [ ] Graceful shutdown (`SIGTERM` → fail readiness → drain → close pools)
- [ ] Liveness vs readiness probes distinct (liveness shouldn't depend on the database)
- [ ] Structured logs with request ID (`slog`), no PII/secrets in logs
- [ ] RED metrics (rate, errors, duration) and pool/GC/goroutine gauges; SLO-based alerts
- [ ] Tracing propagated (OpenTelemetry) across HTTP/gRPC/queue boundaries
- [ ] Panic recovery middleware; recover in every background goroutine
- [ ] Bounded everything: request body size, concurrency, queue length, cache size
- [ ] Retries with backoff + jitter, only for idempotent calls; circuit breaker or load shedding for dependencies
- [ ] pprof on an internal port; `GOMEMLIMIT` set from the container limit
- [ ] CI: `-race`, `vet`, lint, `govulncheck`; reproducible build with pinned toolchain
- [ ] Container: static binary (`CGO_ENABLED=0`), distroless/scratch, non-root, read-only filesystem

---

## 6. Interview questions

**Q1. What's wrong with `http.ListenAndServe(":8080", mux)` in production?**
It uses a server with no timeouts and no shutdown handle. Build an `http.Server` with `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, `IdleTimeout`, run `Serve` in a goroutine, and call `Shutdown(ctx)` on `SIGTERM`.

**Q2. Your service makes 200 req/s to one dependency and latency is bad though the dependency is fast. Why?**
Likely `MaxIdleConnsPerHost` = 2 default: most requests dial a new TCP/TLS connection. Raise it, ensure bodies are drained and closed, reuse one client. Verify with `httptrace` or connection counts.

**Q3. p99 latency rises, CPU is flat. Walk me through it.**
Waiting, not computing. Check `db.Stats().WaitDuration`, downstream latency, goroutine profile for pile-ups in one stack, mutex/block profiles, GC pauses and throttling in the execution trace.

**Q4. How do you size a `database/sql` pool for 20 instances against a Postgres with `max_connections=200`?**
Budget: leave headroom (admin, migrations, replicas) so maybe 150 usable ÷ 20 ≈ 7 per instance, then validate with load tests and `db.Stats()`. Or add PgBouncer in transaction mode and keep per-instance pools small. Unlimited default is a bug.

**Q5. How do you find and fix a goroutine leak?**
Goroutine profile at two points in time; diff stacks; most leaks are blocked on a channel send/receive or a missing ctx cancel. Fix with ctx-aware selects, buffered or closed channels, stopping tickers; add `goleak`/`synctest` tests; alert on goroutine count.

**Q6. `GOGC` vs `GOMEMLIMIT`?**
`GOGC` sets the heap growth ratio before the next GC (higher = fewer GCs, more memory). `GOMEMLIMIT` is a soft ceiling that makes the GC work harder as total memory approaches it. Typical container setup: `GOMEMLIMIT` ~90% of the limit and leave `GOGC` default (or `GOGC=off` only with a limit and careful testing).

**Q7. How would you structure a Go monorepo of 10 services?**
One module per deployable (or a `go.work` for local dev), shared internal libraries versioned deliberately, `internal/` to prevent accidental coupling, generated API clients from protos/OpenAPI in a shared module, consistent tooling in CI, and ownership via CODEOWNERS. Avoid a giant `common` package.

**Q8. Where should errors be logged?**
Once, at the layer that handles them (usually the edge: HTTP/gRPC handler), with the wrapped chain (`%w`) providing context. Logging and returning produces duplicate noise. Map errors to status codes at the boundary; don't leak internal details.

**Q9. How do you make a Go service survive a dependency outage?**
Timeouts on every call, bounded concurrency (bulkheads), retry budgets with jitter, circuit breaker, fallback or stale cache, load shedding at ingress (return 503 early when queues are full), and readiness that reflects ability to serve. Test with fault injection.

**Q10. When do you reach for `sync.Pool`, and what are the traps?**
For reusing large, short-lived, same-shaped objects (buffers) on hot paths where allocation shows up in profiles. Objects can be dropped at any GC; always reset before reuse; don't store things with ownership/lifetime semantics; measure, because pools can also *add* cost and hide leaks of references.
