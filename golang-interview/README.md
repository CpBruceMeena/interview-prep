# 🦦 Go — Staff-Level Interview Questions

> **Deep-dive into Go's runtime scheduler, CSP concurrency, memory model, and production patterns**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## 📋 What's Inside

| File | Content |
|------|---------|
| [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) | 12 in-depth questions covering Go's core internals at staff level |

### Topics Covered

- **GMP Scheduler** — Goroutine scheduling, M:N threading, work-stealing, sysmon, network poller
- **CSP Concurrency** — Channel patterns, select, fan-in/fan-out, pipeline cancellation
- **Interface System** — Duck typing, interface satisfaction, type assertions, generics
- **Memory Model** — Happens-before, data races, `sync/atomic`, the Go memory model document
- **Garbage Collection** — Non-generational concurrent GC, GC tuner, pacing, CPU% trade-offs
- **Escape Analysis** — Stack vs heap allocation, compiler optimizations, allocation profiling
- **`sync` Package** — `Mutex` vs `RWMutex`, `Pool`, `Map`, `Once`, `Cond`, `WaitGroup`
- **Context Package** — Cancellation propagation, deadline propagation, request-scoped values
- **Error Handling** — Errors as values, sentinel errors, error wrapping, `errors.Is`/`As`
- **`io` Package** — `Reader`/`Writer` composition, `io.ReaderFrom`/`io.WriterTo`, `io.Pipe`
- **Reflection & Codegen** — `reflect` deep dive, `go:generate`, `text/template`, code generation patterns
- **Production Patterns** — Graceful shutdown, middleware chaining, testing patterns, pprof

---

### How to Use

1. **Read each question** and try to answer before looking at the expected answer
2. **Study the code examples** — they demonstrate production-quality patterns
3. **Understand the trade-offs** — staff-level interviews are about why, not what
4. **Run the code snippets** to internalize the concepts

---

> *Built for experienced Go engineers targeting Staff/Principal roles at top-tier companies*
