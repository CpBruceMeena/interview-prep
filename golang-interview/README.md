# 🦦 Go — Staff-Level Interview Questions

> **Deep-dive into Go's runtime scheduler, CSP concurrency, memory model, and production patterns**
> *For Senior / Staff Software Engineer interviews. Current as of Go 1.27 (August 2026).*

---

## 📋 What's Inside

| File | Content |
|------|---------|
| [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) | 13 in-depth questions on Go internals and production engineering, each with a 30-second answer, the mechanism, trade-offs and follow-up probes |
| [`CONCURRENCY_NOTES.md`](./CONCURRENCY_NOTES.md) | Practical concurrency guide (goroutines, channels, `select`, `sync`, atomics, context, production patterns, debugging) plus 17 interview questions |
| [`POINTERS_MEMORY_NOTES.md`](./POINTERS_MEMORY_NOTES.md) | Pointers, value vs pointer semantics, escape analysis (with real `-gcflags=-m` output), alignment, `unsafe`, GC impact, plus 8 interview questions |
| [`LANGUAGE_INTERNALS_NOTES.md`](./LANGUAGE_INTERNALS_NOTES.md) | Slice growth and aliasing, maps (Swiss tables), strings/runes, generics (when and how implemented), `defer`/`recover` rules, method sets, goroutine stacks, plus 10 interview questions (all output verified) |
| [`CONCURRENCY_CODING_CHALLENGES.md`](./CONCURRENCY_CODING_CHALLENGES.md) | 7 coding-round problems with complete `-race`-tested solutions: bounded parallel map, token bucket, singleflight cache, worker pool, pub/sub, leak-free pipeline, retry with jitter |
| [`PRODUCTION_SERVICES_NOTES.md`](./PRODUCTION_SERVICES_NOTES.md) | `net/http` timeouts and client pooling, `database/sql` pool sizing, a pprof/trace performance-debugging playbook, project layout and modules, service checklist, plus 10 interview questions |

### Topics Covered

- **GMP Scheduler**: M:N threading, run queues, work stealing, syscalls vs netpoller, async preemption, container-aware `GOMAXPROCS` (1.25)
- **CSP Concurrency**: channel internals, `select`, fan-in/fan-out, pipelines with cancellation, leaks and the `goroutineleak` profile (1.27)
- **Interface System**: iface/eface/itab, structural typing, the nil-interface trap, how generics are implemented (GC-shape stenciling), generic methods (1.27)
- **Memory Model**: happens-before (2022 revision), data races, sequentially consistent `sync/atomic`, the race detector
- **Garbage Collection**: concurrent tri-color mark-sweep, pacer, `GOGC`/`GOMEMLIMIT`, Green Tea GC (default since 1.26)
- **Escape Analysis**: stack vs heap, size limits, reading `-m` output, allocation-free APIs
- **`sync` Package**: `Mutex` vs `RWMutex`, `Pool`, `Map` (hash-trie since 1.24), `OnceValue`, `WaitGroup.Go` (1.25)
- **Context**: cancellation trees, `WithCancelCause`/`AfterFunc`/`WithoutCancel`, request-scoped values
- **Error Handling**: wrapping, `errors.Is`/`As`/`AsType` (1.26), `errors.Join`, gRPC boundary mapping without leaking PII
- **`io` Package**: Reader/Writer composition, layer and close order, `io.Pipe`, streaming JSON, `encoding/json/v2` (1.27)
- **Reflection**: tag-driven validation with per-type plans, measured costs, when to generate code instead
- **Testing**: fakes vs mocks, testcontainers, `testing/synctest` (1.25), fuzzing, `B.Loop`
- **Production Patterns**: graceful shutdown on Kubernetes, middleware, `slog`, metrics, pprof/PGO
- **Modern Go (1.21–1.27)**: per-iteration loop variables, range-over-func iterators, Swiss-table maps, what changed and why it matters

---

### How to Use

1. **Read each question** and try to answer it before looking at the expected answer
2. **Say the 30-second answer out loud**, then go deeper into the mechanism
3. **Understand the trade-offs**: staff-level interviews are about why, not what
4. **Run the code snippets**: the self-contained ones were run with Go 1.27.1 (`go vet`, `go test -race`)

---

> *Built for experienced Go engineers targeting Senior and Staff roles*
