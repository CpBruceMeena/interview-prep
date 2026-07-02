# 🦦 Go — Staff-Level Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer, 15+ years in distributed systems and infrastructure  \
> **Target Level:** Staff/Principal Engineer (10+ years)  \
> **Evaluation Focus:** Go runtime internals, CSP concurrency, memory model, production system design

---

## Question 1: The GMP Scheduler — How Goroutines Actually Run

**Interviewer:** *"Explain how Go schedules goroutines. What happens when a goroutine blocks on a syscall or channel operation?"*

### 🎯 Expected Answer (Staff Level)

**The GMP model — three abstractions:**

```
┌─────────────────────────────────────────────────────────────────┐
│                      GMP Scheduling Model                         │
├─────────────────────────────────────────────────────────────────┤
│  G (Goroutine)         M (Machine/Thread)     P (Processor)     │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐  │
│  │ Stack: 2KB   │      │ OS Thread    │      │ LRQ: []G     │  │
│  │ PC, SP       │      │ TLS, Signal  │      │ runnext: *G  │  │
│  │ Status       │      │ g0 (scheduler│      │ mcache       │  │
│  │ sched        │      │   stack)     │      │ GC fields    │  │
│  └──────────────┘      └──────────────┘      └──────────────┘  │
│                                                                │
│  G's states: _Gidle → _Grunnable → _Grunning → _Gsyscall       │
│                                        ↓ (channel/io)           │
│                                   _Gwaiting                     │
│                                        ↓ (ready)                │
│                                   _Grunnable                    │
└─────────────────────────────────────────────────────────────────┘
```

**Scheduling loop (runtime.schedule, simplified):**

```go
// runtime/proc.go — the scheduler entry point
//
// The scheduler runs on the M's g0 stack (not user goroutine stack)
// It's called when a goroutine:
//   1. Blocks (channel send/receive, mutex, syscall)
//   2. Preempted (10ms time slice expires)
//   3. Voluntarily yields (runtime.Gosched())
//   4. Calls runtime·park (runtime timer)

func schedule() {
    gp := getg()  // Current M's g0
    
top:
    pp := gp.m.p.ptr()  // The P bound to this M
    
    // Priority 1: Check for GC mark worker
    if gp := gcController.findRunnableGCWorker(); gp != nil {
        execute(gp, true) // Never returns
    }
    
    // Priority 2: Local run queue — runnext first (fast path)
    if gp, ok := runqget(pp); ok {
        execute(gp, true)
    }
    
    // Priority 3: Global run queue (steal from sched.runq)
    if sched.runqsize > 0 {
        lock(&sched.lock)
        gp := globrunqget(pp, 1)
        unlock(&sched.lock)
        if gp != nil {
            execute(gp, true)
        }
    }
    
    // Priority 4: Work stealing — steal from other P's LRQ
    if gp := stealWork(pp); gp != nil {
        execute(gp, true)
    }
    
    // Priority 5: Spin — poll network, then idle
    // (stopm blocks until new work arrives via ready())
    stopm()
    goto top
}
```

**Work stealing in detail:**

```go
// runtime/proc.go — stealWork
func stealWork(pp *p) *g {
    now := nanotime()
    const stealTries = 4  // Try 4 random Ps
    
    for i := 0; i < stealTries; i++ {
        // Random victim selection — avoids thundering herd
        pp2 := allp[fastrand() % uint32(len(allp))]
        if pp2 == pp {
            continue // Don't steal from yourself
        }
        
        // Steal half of victim's run queue
        if gp, ok := runqsteal(pp, pp2, true); ok {
            return gp
        }
    }
    
    // If nothing to steal, check global queue again
    return nil
}
```

**Syscall handling — the critical difference from channels:**

```go
// When a goroutine makes a blocking syscall (e.g., read(fd, buf, n)):
//
// 1. Enters _Gsyscall state
// 2. The M is released from its P → M can block without affecting scheduling
// 3. P finds a new M (or creates one) from the M pool
// 4. New M starts running other goroutines from P's LRQ
// 5. When syscall returns, G tries to reacquire a P:
//    a. If original P is free, reacquire it (fast path)
//    b. Otherwise, wait for a P in the global queue
//    c. If no P available, G goes to _Grunnable and M goes idle

// This is why Go can handle 100K+ goroutines making syscalls
// The P-M separation means N syscalls don't need N OS threads

// Network poller — special case for non-blocking I/O:
// Instead of making blocking read() syscalls, Go uses:
// - epoll (Linux), kqueue (macOS), IOCP (Windows)
// - goroutine calls runtime.netpoll → returns list of ready goroutines
// - No M unbinding needed → much cheaper!

// Simplified:
func netpoll(block bool) *g {
    // epoll_wait with timeout
    n, events := epollwait(epfd, events, -1 if block else 0)
    
    var list *g
    for i := 0; i < n; i++ {
        gp := *(**g)(unsafe.Pointer(&events[i].data))
        if gp.waiting != nil {
            casgstatus(gp, _Gwaiting, _Grunnable)
            list = append(list, gp)
        }
    }
    return list // Ready goroutines to inject
}
```

**Preemption (Go 1.14+ — cooperative preemption):**

```go
// Before 1.14: Go had only cooperative scheduling
// → Tight loops would block the P for unbounded time!

// After 1.14: Signal-based preemption
// The sysmon thread (runtime.monitor) sends SIGURG to M if a goroutine
// runs >10ms without a function call (no chance to check preemption flag)

// runtime.sysmon:
func sysmon() {
    for {
        usleep(10 * 1000) // 10μs sleep
        
        // Check all Ps
        for _, pp := range allp {
            if pp.runnext == nil && runqempty(pp) && pp.gcMarkWorker == nil {
                continue // Idle — skip
            }
            
            gp := pp.curg
            if gp != nil && gp.preempt {
                // Send preemption signal
                preemptM(gp.m)
            }
        }
    }
}

// What actually causes preemption:
// runtime.retake → preemptone → signalM(m, sigPreempt) → receivesig
// → suspendG → asyncPreempt → asyncPreempt2 → schedule()
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **GMP understanding** | Knows G, M, P are separate, understands work stealing, syscall-handler unbinding |
| **Preemption** | Knows pre-1.14 cooperative vs post-1.14 signal-based, sysmon role |
| **Network poller** | Understands netpoll avoids syscall penalty — goroutines stay on M |
| **M:N threading** | Can explain why 100K goroutines is feasible but 100K OS threads isn't |

---

## Question 2: Channels — CSP, Internal Structure, and Patterns

**Interviewer:** *"Implement a channel from scratch in Go. Then explain fan-in, fan-out, and how you'd build a pipeline with proper cancellation."*

### 🎯 Expected Answer

**Channel internal structure (runtime/chan.go):**

```go
// runtime/chan.go — hchan struct
type hchan struct {
    qcount   uint           // Total data in queue
    dataqsiz uint           // Size of circular queue (0 for unbuffered)
    buf      unsafe.Pointer // Pointer to circular queue buffer
    elemsize uint16         // Size of each element
    closed   uint32         // 0 = open, 1 = closed
    elemtype *_type         // Element type (for typed channels)
    sendx    uint           // Send index in buffer
    recvx    uint           // Receive index in buffer
    recvq    waitq          // List of goroutines waiting to receive
    sendq    waitq          // List of goroutines waiting to send
    lock     mutex          // Spin lock protecting the channel
}

// waitq is a doubly-linked list of sudog (goroutine + elem)
type waitq struct {
    first *sudog
    last  *sudog
}

// Simplified send operation:
func chansend(c *hchan, ep unsafe.Pointer, block bool) bool {
    lock(&c.lock)
    
    // 1. If channel is nil → block forever (deadlock)
    if c == nil {
        gopark(nil, nil, waitReasonChanSendNil, traceEvGoStop, 2)
        throw("unreachable")
    }
    
    // 2. If there's a waiting receiver → direct send (no buffer)
    if sg := c.recvq.dequeue(); sg != nil {
        // Send directly to blocked receiver's stack
        memcpy(sg.elem, ep, c.elemsize)
        // Wake up receiver
        goready(sg.g, 5)
        unlock(&c.lock)
        return true
    }
    
    // 3. If buffer has space → enqueue in circular buffer
    if c.qcount < c.dataqsiz {
        qp := chanbuf(c, c.sendx)
        memcpy(qp, ep, c.elemsize)
        c.sendx++
        if c.sendx == c.dataqsiz {
            c.sendx = 0
        }
        c.qcount++
        unlock(&c.lock)
        return true
    }
    
    // 4. No buffer space → block sender
    // Create sudog, enqueue to sendq, gopark
    gp := getg()
    mysg := acquireSudog()
    mysg.elem = ep
    mysg.g = gp
    mysg.c = c
    c.sendq.enqueue(mysg)
    gopark(chanparkcommit, unsafe.Pointer(&c.lock), 
           waitReasonChanSend, traceEvGoBlockSend, 2)
    // ... woken up when receiver takes from buffer
}
```

**Building production patterns with channels:**

```go
// ── Fan-Out: Distribute work across multiple workers ──────────

func FanOut[T any](in <-chan T, workers int) []<-chan T {
    channels := make([]<-chan T, workers)
    
    for i := 0; i < workers; i++ {
        ch := make(chan T)
        channels[i] = ch
        
        go func(out chan T) {
            defer close(out)
            for val := range in {
                out <- val
            }
        }(ch)
    }
    
    return channels
}

// ── Fan-In: Merge multiple channels into one ──────────────────

func FanIn[T any](channels ...<-chan T) <-chan T {
    out := make(chan T)
    var wg sync.WaitGroup
    wg.Add(len(channels))
    
    for _, ch := range channels {
        go func(c <-chan T) {
            defer wg.Done()
            for val := range c {
                out <- val
            }
        }(ch)
    }
    
    // Close out when all input channels are drained
    go func() {
        wg.Wait()
        close(out)
    }()
    
    return out
}

// ── Pipeline with proper cancellation ─────────────────────────

// Pipeline pattern: stage is a function that takes input and returns output
type Stage[T, U any] func(context.Context, <-chan T) <-chan U

// source generates integers
func Source(ctx context.Context, nums ...int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for _, n := range nums {
            select {
            case out <- n:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// process squares numbers
func Process(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {
            result := n * n
            select {
            case out <- result:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// sink consumes results (with timeout)
func Sink(ctx context.Context, in <-chan int) {
    for result := range in {
        select {
        case <-ctx.Done():
            fmt.Println("Cancelled:", ctx.Err())
            return
        default:
            fmt.Println("Result:", result)
        }
    }
}

// Usage:
func PipelineDemo() {
    ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
    defer cancel()
    
    // Compose pipeline
    results := Process(ctx, Process(ctx, Source(ctx, 1, 2, 3, 4, 5)))
    Sink(ctx, results)
}

// ── Tee: Split one channel into two ───────────────────────────

func Tee[T any](in <-chan T) (<-chan T, <-chan T) {
    out1 := make(chan T)
    out2 := make(chan T)
    
    go func() {
        defer close(out1)
        defer close(out2)
        
        for val := range in {
            // Must send to both — use select for non-blocking
            out1, out2 := out1, out2
            for i := 0; i < 2; i++ {
                select {
                case out1 <- val:
                    out1 = nil // Disable this case after send
                case out2 <- val:
                    out2 = nil
                }
            }
        }
    }()
    
    return out1, out2
}

// ── Or-Done: Combine multiple done channels ───────────────────

func OrDone[T any](ctx context.Context, in <-chan T) <-chan T {
    out := make(chan T)
    go func() {
        defer close(out)
        for {
            select {
            case <-ctx.Done():
                return
            case val, ok := <-in:
                if !ok {
                    return
                }
                select {
                case out <- val:
                case <-ctx.Done():
                    return
                }
            }
        }
    }()
    return out
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Internal structure** | Knows hchan, sudog, waitq, circular buffer, direct send optimization |
| **Patterns** | Can implement fan-out, fan-in, pipeline, tee, or-done naturally |
| **Cancellation** | Every select uses ctx.Done() — no goroutine leaks |
| **Deadlock detection** | Knows the runtime's deadlock detector, nil channel blocking behavior |

---

## Question 3: Interface Satisfaction — The Type System's Secret Weapon

**Interviewer:** *"Explain how Go's interface satisfaction works at runtime. How does an interface value get stored in memory? What's the difference between `io.Reader` and `any`?"*

### 🎯 Expected Answer

**Interface value layout (runtime/runtime2.go):**

```go
// An interface value is stored as two machine words:
//
// type iface struct {
//     tab  *itab    // Type information + method table
//     data unsafe.Pointer  // Pointer to the concrete value
// }
//
// For empty interface (any):
// type eface struct {
//     _type *_type   // Just type info (no methods)
//     data  unsafe.Pointer
// }

// The itab structure:
type itab struct {
    inter *interfacetype  // The interface type (e.g., io.Reader)
    _type *_type          // The concrete type (e.g., *os.File)
    hash  uint32           // Copy of _type.hash — for type assertions
    _     [4]byte          // Padding
    fun   [1]uintptr       // Variable-sized — pointers to method implementations
}

// When you assign a concrete value to an interface:
var r io.Reader = &os.File{}

// At compile time, the compiler generates an itab for (io.Reader, *os.File)
// At runtime, this itab is lazily created and cached (itabTable)

// ── Interface satisfaction is STRUCTURAL, not nominal ─────────
// A type satisfies an interface if it implements all the interface's methods
// No "implements" keyword, no explicit declaration

// This means: you can define an interface AFTER the concrete type,
// zero coupling between packages!

// Production example — the "accept interfaces, return structs" pattern:
type Store interface {
    Get(ctx context.Context, key string) ([]byte, error)
    Set(ctx context.Context, key string, value []byte, ttl time.Duration) error
    Delete(ctx context.Context, key string) error
}

// Concrete implementations live in different packages:
// redis_store.go
type RedisStore struct { /* ... */ }
func (r *RedisStore) Get(ctx context.Context, key string) ([]byte, error) { ... }

// s3_store.go
type S3Store struct { /* ... */ }
func (s *S3Store) Get(ctx context.Context, key string) ([]byte, error) { ... }

// The function receiving Store never imports redis or s3!
func CacheMiddleware(store Store) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            data, err := store.Get(r.Context(), r.URL.Path)
            // ...
        })
    }
}
```

**Type assertions and type switches under the hood:**

```go
// Type assertion: x.(T) where x is interface, T is concrete type
//
// Compiler generates:
// 1. Compute hash of T
// 2. Search itab table for matching itab.inter == T
// 3. If found, return data (it's a T!)
// 4. If not, panic or return ok=false

// Performance: O(1) hash lookup — very fast

// Type switch:
var x any = "hello"
switch v := x.(type) {
case string:
    fmt.Println(len(v)) // v is string here
case int:
    fmt.Println(v + 1)  // v is int here
default:
    fmt.Println("unknown")
}

// Compiler generates a jump table — NOT sequential comparisons
// Each case is a hash compare + direct branch

// Important: interface nil vs concrete nil
func NilTrap() {
    var p *os.File = nil
    var r io.Reader = p  // r is NOT nil!
    
    // Why? iface{tab: (*os.File, io.Reader), data: nil}
    // r != nil even though underlying data is nil!
    
    fmt.Println(r == nil) // false!
    
    // Fix: always return a typed nil or use a sentinel:
    // func NewReader() io.Reader {
    //     if err != nil {
    //         return nil  // Returns (nil, nil) — correctly nil
    //     }
    //     return &MyReader{}
    // }
}
```

**Generic interfaces (Go 1.18+):**

```go
// Pre-generics: had to use any + type assertions
type StackOld struct {
    data []any
}
func (s *StackOld) Push(v any) { ... }
func (s *StackOld) Pop() any { ... }  // Caller must type-assert

// With generics:
type Stack[T any] struct {
    data []T
}
func (s *Stack[T]) Push(v T) { ... }
func (s *Stack[T]) Pop() T { ... }   // Type-safe, no assertions!

// Constrained generics:
type Number interface {
    ~int | ~int64 | ~float64 | ~float32
}

func Sum[T Number](values []T) T {
    var sum T
    for _, v := range values {
        sum += v
    }
    return sum
}

// Interface vs generics trade-off:
//
// Interface: dynamic dispatch (one virtual call per method)
//   - ✅ Can store different concrete types in same variable
//   - ✅ Works with any type satisfying the interface
//   - ❌ Extra indirection, non-inlineable
//
// Generics: static monomorphization (each type gets its own instantiation)
//   - ✅ Inlineable, no runtime overhead
//   - ✅ Full compile-time type safety
//   - ❌ Code bloat (one copy per type)
//   - ❌ Can't store different types in same variable

// Best practice: use interfaces for abstraction boundaries,
// use generics for type-safe containers and algorithms
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Memory layout** | Knows itab, iface, eface structures |
| **Structural typing** | Understands duck typing vs nominal — the "implements" isn't needed |
| **Nil interface trap** | Knows the concrete-nil vs interface-nil distinction cold |
| **Generics vs interfaces** | Can explain trade-offs, knows when to use each |

---

## Question 4: The Memory Model — Happens-Before, Data Races, and `sync/atomic`

**Interviewer:** *"Without using `sync.Mutex`, implement a thread-safe counter. Explain every memory ordering guarantee you're relying on."*

### 🎯 Expected Answer

```go
// ── The Go Memory Model ─────────────────────────────────────
//
// Go's memory model is defined by happens-before:
// If event A happens before event B, then B sees the effects of A.
//
// Key rules:
// 1. Within a single goroutine, reads/writes happen in program order
// 2. A send on a channel happens before the corresponding receive
// 3. The kth receive on a buffered channel with capacity C happens
//    before the (k+C)th send completes
// 4. Lock(m) happens before any Unlock(m)
// 5. Once.Do(f) → f's operations happen before Once.Do returns
// 6. Atomic stores happen before atomic loads (with proper ordering)

// ── Sequential consistency with sync/atomic ─────────────────

type AtomicCounter struct {
    // Even alignment is critical on 32-bit platforms!
    // Use sync/atomic — it handles alignment internally
    value atomic.Int64
}

func NewAtomicCounter(initial int64) *AtomicCounter {
    c := &AtomicCounter{}
    c.value.Store(initial)
    return c
}

// 🔴 PROBLEM: What's wrong with this?
func (c *AtomicCounter) Increment() int64 {
    return c.value.Add(1) // Load + Add + Store = atomic!
}

// ✅ CORRECT: atomic.Add is fully sequential consistent
// All goroutines see the same order of operations

// ── What about a CAS (compare-and-swap) based lock? ─────────

type SpinLock struct {
    locked atomic.Bool
}

func (s *SpinLock) Lock() {
    for !s.locked.CompareAndSwap(false, true) {
        // Spin — terrible for production!
        // Use runtime.Gosched() to yield
        runtime.Gosched()
    }
}

func (s *SpinLock) Unlock() {
    s.locked.Store(false)
}

// ── Wait-free counter with load/store ordering ──────────────

type EpochBasedCounter struct {
    epoch atomic.Int64
    // On 64-bit platforms, a single 64-bit atomic load is
    // guaranteed to see a consistent value
}

func (c *EpochBasedCounter) Increment() int64 {
    return c.epoch.Add(1)
}

func (c *EpochBasedCounter) Snapshot() int64 {
    // Load alone doesn't provide ordering guarantees
    // But on x86-64, Load is a MOV instruction — sequentially consistent
    // On ARM64, it's an LDAR instruction
    // Go's sync/atomic always uses sequentially consistent atomics
    return c.epoch.Load()
}

// ── The real problem: data races aren't just about counters ─

type Service struct {
    ready atomic.Bool
    cache map[string]Result  // NOT protected!
}

func (s *Service) Initialize() {
    s.cache = buildCache()  // 1. Write to map
    s.ready.Store(true)    // 2. Publish (release)
}

func (s *Service) Get(key string) Result {
    if s.ready.Load() {    // 3. Check (acquire)
        // 4. Read from map — is this safe?
        // 🔴 NO! Go memory model says atomic Store/Load
        // only guarantees the visibility of the atomic variable itself
        // Not the map!
        return s.cache[key]
    }
    return fallback
}

// ✅ Fix: use a pointer swap with atomic
type Service struct {
    cache atomic.Pointer[map[string]Result]
}

func (s *Service) Initialize() {
    cache := buildCache()
    s.cache.Store(&cache)  // One atomic write — all-or-nothing
}

func (s *Service) Get(key string) Result {
    c := s.cache.Load()  // One atomic read
    return (*c)[key]
}

// ── Production: sharded counter with atomic ────────────────

type ShardedCounter struct {
    shards [64]atomic.Int64  // 64 shards, no sharing
}

func NewShardedCounter() *ShardedCounter {
    return &ShardedCounter{}
}

func (c *ShardedCounter) Increment() {
    shard := &c.shards[fastrand()%64]
    shard.Add(1)
}

func (c *ShardedCounter) Total() int64 {
    var total int64
    for i := range c.shards {
        total += c.shards[i].Load()
    }
    return total
}

// ── The Data Race Detector ──────────────────────────────────
//
// go test -race ./...  or  go build -race ./...
//
// Works by instrumenting every memory access with a check:
// The runtime maintains a "happens-before" graph of goroutine
// and memory access events. Any unsynchronized access = race.
//
// ThreadSanitizer (TSan) under the hood — detects races at
// runtime, not compile time. Zero false positives.
//
// PERFORMANCE COST: 5-10x slower, ~10x more memory
// Never run -race in production!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Happens-before** | Can explain the formal model, not just "use sync/atomic" |
| **Atomic memory ordering** | Knows sequentially consistent atomics, release/acquire semantics |
| **Race detector** | Has used -race extensively, knows its theory of operation |
| **Pointer swap pattern** | Knows atomic.Pointer for lock-free read caching |

---

## Question 5: GC — The Go Garbage Collector

**Interviewer:** *"Walk me through a full GC cycle in Go. How does it decide when to start? How does it minimize STW? What triggers a GC?"*

### 🎯 Expected Answer

**GC is concurrent, tri-color, non-generational, and non-compacting:**

```
┌─────────────────────────────────────────────────────────────┐
│  GC Phases (1 GC cycle ≈ application's GC_GOAL * live data) │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Phase 1: Sweep Termination (STW, <100μs)                    │
│  └─ Finish sweep from previous cycle                         │
│                                                              │
│  Phase 2: Mark Setup (STW, ~10-30μs)                        │
│  └─ Write barrier enabled                                    │
│  └─ GC goroutines (G mark workers) started                   │
│                                                              │
│  Phase 3: Concurrent Mark (concurrent with app)             │
│  └─ 25% CPU dedicated to GC (GOMEMLIMIT adjusts this)       │
│  └─ Tri-color algorithm: white → grey → black               │
│  └─ Write barrier tracks mutations during mark              │
│                                                              │
│  Phase 4: Mark Termination (STW, ~60-200μs)                 │
│  └─ Finish remaining mark work                              │
│  └─ Write barrier disabled                                  │
│  └─ Next GC trigger calculated                              │
│                                                              │
│  Phase 5: Concurrent Sweep (concurrent with app)            │
│  └─ Free memory from white objects                           │
│  └─ Memory returned to OS or cached (span scavenging)       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**GC trigger — the pacing mechanism:**

```go
// GC is triggered when the heap grows to a certain size:
// nextGC = liveHeap + (liveHeap * GOGC) / 100  (default GOGC=100)
//
// So with GOGC=100: GC runs when heap doubles (2x live)
// With GOGC=50: GC runs at 1.5x live (more frequent, less memory)
// With GOGC=off: GC never triggers (you must call runtime.GC())
//
// Go 1.19+ also has GOMEMLIMIT
// GOMEMLIMIT=2GiB: GC will try to keep heap <= 2GiB
// Even if GOGC would say "wait longer", GOMEMLIMIT can force a GC

// Runtime monitoring:
func PrintGCStats() {
    var m runtime.MemStats
    runtime.ReadMemStats(&m)
    
    fmt.Printf("Allocated: %d MB\n", m.Alloc/1024/1024)
    fmt.Printf("Total Allocated: %d MB\n", m.TotalAlloc/1024/1024)
    fmt.Printf("Heap Objects: %d\n", m.HeapObjects)
    fmt.Printf("GC Cycles: %d\n", m.NumGC)
    fmt.Printf("GC Pause (recent): %d μs\n", m.PauseNs[(m.NumGC-1)%256]/1000)
    fmt.Printf("GC CPU Fraction: %.2f%%\n", m.GCCPUFraction*100)
    fmt.Printf("GOGC: %d\n", debug.SetGCPercent(-1)) // Read current
    fmt.Printf("Next GC at: %d MB\n", m.NextGC/1024/1024)
}
```

**Tri-color algorithm in detail:**

```
┌──────────────────────────────────────────────────────────────┐
│  Tri-Color Marking                                            │
├──────────────────────────────────────────────────────────────┤
│  Initial state: All objects are WHITE                         │
│  Root set (stack, globals, registers) → GREY                  │
│                                                              │
│  GC worker loop:                                              │
│  while grey list is not empty:                                │
│      obj = pop grey                           ┌──────┐      │
│      for each ptr in obj's fields:            │ GREY │      │
│          if ptr points to WHITE object:       │Queue │      │
│              mark WHITE → GREY                └──────┘      │
│              add to grey list                   ↓           │
│      mark obj GREY → BLACK                    ┌──────┐      │
│                                               │BLACK │      │
│  Done: All reachable objects = BLACK          └──────┘      │
│        All unreachable objects = WHITE                       │
│        Sweep: free WHITE objects                             │
└──────────────────────────────────────────────────────────────┘
```

**Write barrier — the key to concurrency:**

```go
// Without a write barrier, the GC could miss a pointer:
//
// Goroutine 1 (GC marking):       Goroutine 2 (application):
// scan object A                    A.x = nil  // Remove pointer
// → A has no pointers              B.y = &obj // Add new pointer
// → mark A BLACK (done!)
//
// Problem: obj was WHITE (unscanned), now only reachable via B
// But B might already be BLACK (scanned), so obj is lost!
// This is the "lost object" problem.

// Solution: Dijkstra-style insertion write barrier (pre-1.17)
// Before any pointer write p.x = q:
//    if GC is marking:
//        shade(q)  // Mark q GREY if it's WHITE
// After write barrier, even if GC already scanned p,
// it will find q in the grey set and mark it.

// Go 1.17+: Hybrid write barrier
// Combined Dijkstra + Yuasa barrier
// Reduced STW time from ~100μs to ~10μs for mark termination
```

**GC tuning for production:**

```go
// ── GOGC tuning ────────────────────────────────────
//
// Default GOGC=100:
//   memory = ~2x live heap
//   CPU overhead = ~25% of one core during GC
//
// GOGC=50:
//   memory = ~1.5x live heap
//   GC runs more frequently — more CPU overhead
//   Use for: latency-sensitive apps (smaller pauses)
//
// GOGC=200:
//   memory = ~3x live heap
//   GC runs less frequently — less CPU overhead
//   Use for: batch processing (want throughput)
//
// GOGC=off:
//   Must call runtime.GC() manually
//   Use for: real-time systems, games (precise control)

// ── GOMEMLIMIT (Go 1.19+) ──────────────────────────
// Sets a soft memory limit:
// export GOMEMLIMIT=1.5GiB
//
// GC will trigger more aggressively to stay under limit
// Uses the GC pacer to predict heap growth
// Also handles GOMEMLIMIT "hard" vs "soft" distinction

// ── Reducing GC pressure in hot paths ───────────────

// 🔴 BAD: allocates in hot loop
func SumItems(items []Item) float64 {
    var total float64
    for _, item := range items {
        total += item.Price * item.Quantity
    }
    // No allocation above — but if Item has pointer fields
    // that escape to heap...
    return total
}

// ✅ GOOD: Pre-allocate, reuse buffers
type BufferPool struct {
    pool sync.Pool
}

func (bp *BufferPool) Get() *bytes.Buffer {
    buf := bp.pool.Get().(*bytes.Buffer)
    buf.Reset()
    return buf
}

func (bp *BufferPool) Put(buf *bytes.Buffer) {
    buf.Reset()
    bp.pool.Put(buf)
}

// 🔴 BAD: creates garbage in hot path
func Parse(d []byte) (int, error) {
    s := string(d)  // Allocates! Bytes → string copies
    return strconv.Atoi(s)
}

// ✅ GOOD: avoid allocation
func ParseFast(d []byte) (int, error) {
    return strconv.Atoi(unsafeString(d))
}

// But avoid unsafe unless measured!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Phase knowledge** | Knows the 5 phases, which are STW, which are concurrent |
| **Tri-color algorithm** | Explains white/grey/black correctly with write barrier |
| **GC pacing** | Understands GOGC, nextGC formula, GOMEMLIMIT |
| **Real tuning** | Has profiled GC in production, knows sync.Pool, pre-allocation |

---

## Question 6: `sync` Package Deep Dive — Beyond Mutexes

**Interviewer:** *"Design a connection pool for a database using only the standard library's sync package. Then explain the internals of `sync.Map`."*

### 🎯 Expected Answer

**Production connection pool:**

```go
type Pool[T any] struct {
    mu        sync.Mutex
    idle      chan *T            // Idle connections
    active    int
    maxActive int
    minIdle   int
    factory   func(context.Context) (*T, error)
    closer    func(*T)
    health    func(*T) bool
    done      chan struct{}
}

func NewPool[T any](
    factory func(context.Context) (*T, error),
    closer func(*T),
    opts ...PoolOption[T],
) *Pool[T] {
    p := &Pool[T]{
        idle:    make(chan *T, 100),
        factory: factory,
        closer:  closer,
        health:  func(*T) bool { return true },
        done:    make(chan struct{}),
    }
    
    for _, opt := range opts {
        opt(p)
    }
    
    // Pre-warm connections
    for i := 0; i < p.minIdle; i++ {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        conn, err := p.factory(ctx)
        cancel()
        if err == nil {
            p.idle <- conn
            p.active++
        }
    }
    
    // Health checker goroutine
    go p.healthCheck()
    
    return p
}

func (p *Pool[T]) Acquire(ctx context.Context) (*T, error) {
    for {
        // 1. Try to get from idle connections
        select {
        case conn := <-p.idle:
            // Health check before returning
            if p.health(conn) {
                return conn, nil
            }
            // Dead connection — close it
            p.closer(conn)
            p.mu.Lock()
            p.active--
            p.mu.Unlock()
            continue // Try again
        case <-ctx.Done():
            return nil, ctx.Err()
        default:
        }
        
        p.mu.Lock()
        if p.active >= p.maxActive {
            p.mu.Unlock()
            // Wait for a connection
            select {
            case conn := <-p.idle:
                return conn, nil
            case <-ctx.Done():
                return nil, ctx.Err()
            }
        }
        
        p.active++
        p.mu.Unlock()
        
        // Create new connection
        conn, err := p.factory(ctx)
        if err != nil {
            p.mu.Lock()
            p.active--
            p.mu.Unlock()
            return nil, err
        }
        return conn, nil
    }
}

func (p *Pool[T]) Release(conn *T) {
    select {
    case p.idle <- conn:
    default:
        // Pool is full — close and discard
        p.closer(conn)
        p.mu.Lock()
        p.active--
        p.mu.Unlock()
    }
}

func (p *Pool[T]) healthCheck() {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            p.scrubConnections()
        case <-p.done:
            return
        }
    }
}

func (p *Pool[T]) scrubConnections() {
    p.mu.Lock()
    defer p.mu.Unlock()
    
    remaining := len(p.idle)
    for i := 0; i < remaining; i++ {
        conn := <-p.idle
        if p.health(conn) {
            p.idle <- conn
        } else {
            p.closer(conn)
            p.active--
        }
    }
}
```

**`sync.Map` internals:**

```go
// sync.Map is optimized for two specific patterns:
// 1. Write-once, read-many (e.g., configuration stores)
// 2. Contended keys where different goroutines access different keys

// It achieves this with a double-map structure:
type Map struct {
    mu     Mutex          // Protects dirty map
    read   atomic.Pointer[readOnly]  // Atomic read-only snapshot
    dirty  map[any]*entry // Writable map
    misses int            // Tracks when reads miss the read map
}

type readOnly struct {
    m       map[any]*entry
    amended bool  // true if dirty has entries not in m
}

type entry struct {
    p atomic.Pointer[any]  // Pointer to the value (or expunged sentinel)
}

// ── Load (fast path — no lock) ─────────────────────
func (m *Map) Load(key any) (value any, ok bool) {
    read := m.read.Load()
    e, ok := read.m[key]
    if !ok && read.amended {
        // Missed read map — must check dirty (with lock)
        m.mu.Lock()
        read = m.read.Load()  // Double-check after lock
        e, ok = read.m[key]
        if !ok && read.amended {
            e, ok = m.dirty[key]
            m.missLocked()  // Track miss (may promote dirty → read)
        }
        m.mu.Unlock()
    }
    if !ok {
        return nil, false
    }
    return e.load()
}

// ── Store (always acquires lock) ────────────────────
func (m *Map) Store(key, value any) {
    read := m.read.Load()
    if e, ok := read.m[key]; ok && e.tryStore(&value) {
        return  // Fast path: update existing entry atomically
    }
    
    m.mu.Lock()
    read = m.read.Load()
    if e, ok := read.m[key]; ok {
        if e.unexpungeLocked() {
            m.dirty[key] = e  // Copy to dirty
        }
        e.storeLocked(&value)
    } else if e, ok := m.dirty[key]; ok {
        e.storeLocked(&value)
    } else {
        if !read.amended {
            m.dirtyLocked()  // Initialize dirty
            m.read.Store(&readOnly{m: read.m, amended: true})
        }
        m.dirty[key] = newEntry(value)
    }
    m.mu.Unlock()
}

// When to use sync.Map vs regular map+mutex:
//
// sync.Map:
// ✅ Write-once, read-many patterns (80%+ reads)
// ✅ Different keys accessed by different goroutines
// ❌ Many writes (lock + dirty promotion overhead)
// ❌ Single key contended (a mutex is simpler)
//
// Regular map with sync.RWMutex:
// ✅ Simple, predictable
// ✅ Works well for most cases
// ❌ RLock causes cache-line bouncing on large read volume

// Typical rule of thumb: use sync.Map only if you've profiled
// and determined that RWMutex is the bottleneck
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **sync.Map internals** | Knows read/dirty, amended flag, miss counting, expunged entries |
| **Pool design** | Handles health checks, max capacity, timeouts, backpressure |
| **sync patterns** | Knows when to use RWMutex vs Mutex, Pool, Once, Cond |
| **Production awareness** | Handles context cancellation, resource leaks, clean shutdown |

---

## Question 7: Context — Cancellation Propagation and Request-Scoped Values

**Interviewer:** *"The standard library's context package — implement a custom context that logs every cancellation. Then explain how to propagate values through the context tree safely."*

### 🎯 Expected Answer

**Custom context with logging:**

```go
type LogContext struct {
    context.Context
    mu     sync.Mutex
    doneCh chan struct{}
    err    error
}

func NewLogContext(parent context.Context) *LogContext {
    ctx := &LogContext{
        Context: parent,
        doneCh:  make(chan struct{}),
    }
    
    if parent.Done() != nil {
        // Listen for parent cancellation
        go func() {
            select {
            case <-parent.Done():
                ctx.mu.Lock()
                ctx.err = parent.Err()
                ctx.mu.Unlock()
                log.Printf("LogContext: parent cancelled: %v", parent.Err())
                close(ctx.doneCh)
            case <-ctx.doneCh:
                // Our own cancellation
            }
        }()
    }
    
    return ctx
}

func (c *LogContext) Done() <-chan struct{} {
    return c.doneCh
}

func (c *LogContext) Err() error {
    c.mu.Lock()
    defer c.mu.Unlock()
    return c.err
}

func (c *LogContext) Cancel(err error) {
    c.mu.Lock()
    defer c.mu.Unlock()
    
    if c.err != nil {
        return // Already cancelled
    }
    
    c.err = err
    log.Printf("LogContext: cancelled with: %v", err)
    close(c.doneCh)
}

// ── Safe context value propagation ──────────────────────────

// Design a context-based trace ID system
type contextKey string

const TraceIDKey contextKey = "trace_id"
var ErrTraceNotFound = errors.New("trace ID not found in context")

func WithTraceID(ctx context.Context, traceID string) context.Context {
    return context.WithValue(ctx, TraceIDKey, traceID)
}

func GetTraceID(ctx context.Context) (string, error) {
    val := ctx.Value(TraceIDKey)
    if val == nil {
        return "", ErrTraceNotFound
    }
    
    id, ok := val.(string)
    if !ok {
        return "", fmt.Errorf("unexpected trace ID type: %T", val)
    }
    return id, nil
}

// 🔴 AVOID: Using built-in types as keys
// context.WithValue(ctx, "trace_id", "abc")  // String keys collide!
// context.WithValue(ctx, int(1), "abc")       // Int keys collide!

// ✅ ALWAYS: Use a custom, unexported type with exported accessor
// This prevents any package from overwriting your context values

// ── Structured context values ───────────────────────────────

type ContextValues struct {
    TraceID    string
    UserID     string
    Role       string
    RequestID  string
    StartTime  time.Time
}

func WithRequestValues(ctx context.Context, values ContextValues) context.Context {
    return context.WithValue(ctx, requestValuesKey{}, values)
}

func GetRequestValues(ctx context.Context) ContextValues {
    val, _ := ctx.Value(requestValuesKey{}).(ContextValues)
    return val
}

type requestValuesKey struct{} // Unexported — only GetRequestValues can access

// ── Context best practices for Staff level ──────────────────

// 1. NEVER store context in a struct
// 🔴 BAD
type DBService struct {
    ctx context.Context  // Don't!
}
func (d *DBService) Query() {
    d.ctx.Done()  // Which request's context?
}

// ✅ GOOD
type DBService struct {}
func (d *DBService) Query(ctx context.Context) {
    ctx.Done()  // Each call gets its own context
}

// 2. ALWAYS use context for cancellation, rarely for values
// Context values are opaque — no compile-time type checking
// Use them only for request-scoped metadata:
//   - Trace IDs
//   - Auth tokens
//   - Request-scoped loggers
// NOT for:
//   - Database connections
//   - Configuration
//   - Business logic parameters

// 3. Create child contexts with timeout/deadline but cancel properly
func HandleRequest(parent context.Context, req Request) error {
    // Create a timeout context
    ctx, cancel := context.WithTimeout(parent, 5*time.Second)
    defer cancel()  // ← MUST call, even if not used
    
    // Now ctx is automatically cancelled after 5 seconds
    // OR when parent is cancelled
    // OR when cancel() is called
    
    // Subscribe to external cancellation (e.g., client disconnect)
    go func() {
        select {
        case <-httpClientClosed():
            cancel()   // Cancel our work
        case <-ctx.Done():
            // Context already done
        }
    }()
    
    return process(ctx, req)
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Custom Done channel** | Can implement Done(), Err(), deadline pattern correctly |
| **Value propagation** | Uses unexported key types, never string/int keys |
| **defer cancel()** | Always calls cancel — no context leaks |
| **Context in structs** | Knows the anti-pattern of storing context in structs |

---

## Question 8: Error Handling — Errors as Values, Wrapping, and Production Patterns

**Interviewer:** *"Implement an error handling strategy for a gRPC microservice. Handle different error types (validation, not-found, internal), propagate them across service boundaries, and ensure PII isn't leaked in error messages."*

### 🎯 Expected Answer

```go
// ── Domain-specific error types ─────────────────────────────

type ErrorType int

const (
    ErrorTypeUnknown     ErrorType = iota
    ErrorTypeValidation
    ErrorTypeNotFound
    ErrorTypeConflict
    ErrorTypeUnauthorized
    ErrorTypeForbidden
    ErrorTypeInternal
    ErrorTypeUnavailable
)

type DomainError struct {
    Type    ErrorType
    Message string
    Detail  string           // Internal details (not sent to client)
    Err     error            // Wrapped cause
    Stack   []uintptr        // Stack trace for debugging
    Retryable bool
}

func (e *DomainError) Error() string {
    if e.Err != nil {
        return fmt.Sprintf("%s: %v", e.Message, e.Err)
    }
    return e.Message
}

func (e *DomainError) Unwrap() error {
    return e.Err
}

// ── Sentry errors ──────────────────────────────────────────

var (
    ErrNotFound     = &DomainError{Type: ErrorTypeNotFound, Message: "resource not found"}
    ErrConflict     = &DomainError{Type: ErrorTypeConflict, Message: "resource conflict"}
    ErrUnauthorized = &DomainError{Type: ErrorTypeUnauthorized, Message: "unauthorized"}
)

func NewValidationError(field, reason string) *DomainError {
    return &DomainError{
        Type:    ErrorTypeValidation,
        Message: fmt.Sprintf("validation failed: %s: %s", field, reason),
    }
}

func NewInternalError(msg string, err error) *DomainError {
    stack := make([]uintptr, 32)
    n := runtime.Callers(2, stack)
    
    return &DomainError{
        Type:    ErrorTypeInternal,
        Message: msg,
        Detail:  err.Error(),
        Err:     err,
        Stack:   stack[:n],
    }
}

// ── Error classification middleware ─────────────────────────

func classifyError(err error) *DomainError {
    var de *DomainError
    if errors.As(err, &de) {
        return de
    }
    
    // Check for common library errors
    if errors.Is(err, sql.ErrNoRows) {
        return &DomainError{
            Type:    ErrorTypeNotFound,
            Message: "resource not found",
            Err:     err,
        }
    }
    
    if os.IsNotExist(err) {
        return &DomainError{
            Type:    ErrorTypeNotFound,
            Message: "file not found",
            Err:     err,
        }
    }
    
    // Default: internal error, strip details for client
    return &DomainError{
        Type:    ErrorTypeInternal,
        Message: "an internal error occurred",  // No details leaked!
        Detail:  err.Error(),
        Err:     err,
    }
}

// ── gRPC error mapping ─────────────────────────────────────

func mapDomainToGRPC(err error) error {
    de := classifyError(err)
    
    var code codes.Code
    switch de.Type {
    case ErrorTypeValidation:
        code = codes.InvalidArgument
    case ErrorTypeNotFound:
        code = codes.NotFound
    case ErrorTypeConflict:
        code = codes.AlreadyExists
    case ErrorTypeUnauthorized:
        code = codes.Unauthenticated
    case ErrorTypeForbidden:
        code = codes.PermissionDenied
    case ErrorTypeUnavailable:
        code = codes.Unavailable
    default:
        code = codes.Internal
    }
    
    // Detailed error in gRPC trailers (for internal debugging)
    st := status.New(code, de.Message)
    if de.Detail != "" {
        st, _ = st.WithDetails(&errdetails.ErrorInfo{
            Domain: de.Detail,
        })
    }
    
    return st.Err()
}

// ── Production error logging ────────────────────────────────

func LogError(logger *slog.Logger, err error) {
    var de *DomainError
    if !errors.As(err, &de) {
        logger.Error("untyped error", "error", err)
        return
    }
    
    attrs := []slog.Attr{
        slog.String("type", de.Type.String()),
        slog.String("message", de.Message),
    }
    
    if de.Err != nil {
        attrs = append(attrs, slog.Any("cause", de.Err))
    }
    
    if de.Stack != nil {
        frames := runtime.CallersFrames(de.Stack)
        var stackLines []string
        for {
            frame, more := frames.Next()
            stackLines = append(stackLines, 
                fmt.Sprintf("%s:%d %s", frame.File, frame.Line, frame.Function))
            if !more {
                break
            }
        }
        attrs = append(attrs, slog.Any("stack", stackLines))
    }
    
    // Log at appropriate level
    if de.Type == ErrorTypeInternal || de.Type == ErrorTypeUnavailable {
        logger.Error("domain error", attrs...)
    } else {
        logger.Warn("domain error", attrs...)
    }
}

// ── Error handling best practices ──────────────────────────

// 1. USE errors.Is / errors.As — never compare error strings!
// 🔴 BAD
if err.Error() == "resource not found" { ... }

// ✅ GOOD
if errors.Is(err, ErrNotFound) { ... }

// 2. WRAP errors for context
func GetUser(ctx context.Context, id string) (*User, error) {
    user, err := db.FindUser(ctx, id)
    if err != nil {
        return nil, fmt.Errorf("get user %s: %w", id, err)  // %w preserves Is/As
    }
    return user, nil
}

// 3. SENTINEL errors for package-level comparisons
var ErrNotFound = errors.New("user not found")

// 4. HANDLE errors once — either log OR return, not both
// 🔴 BAD
func Handle() error {
    err := doSomething()
    if err != nil {
        log.Error(err)  // Logged
        return err      // AND returned — double handling!
    }
}

// ✅ GOOD — annotate once
func Handle() error {
    err := doSomething()
    if err != nil {
        return fmt.Errorf("do something: %w", err)
    }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Error wrapping** | Uses %w, errors.Is/As, never string comparison |
| **Error types** | Creates domain error types, not generic "error" everywhere |
| **PII safety** | Distinguishes public message from internal detail |
| **Once handling** | Logs OR returns errors — never both |

---

## Question 9: io.Reader/Writer — The Composition Pattern

**Interviewer:** *"Design a streaming data transformation pipeline using io.Reader and io.Writer. Show how to compose readers for encryption, compression, and buffering."*

### 🎯 Expected Answer

```go
// ── The io.Reader and io.Writer interfaces ──────────────────
//
// type Reader interface {
//     Read(p []byte) (n int, err error)
// }
//
// type Writer interface {
//     Write(p []byte) (n int, err error)
// }
//
// These two interfaces are the foundation of Go's I/O model.
// Their power comes from COMPOSITION — wrapping one reader
// with another to add behavior.

// ── A custom transformation reader ─────────────────────────

type UpperCaseReader struct {
    reader io.Reader
}

func (r *UpperCaseReader) Read(p []byte) (int, error) {
    n, err := r.reader.Read(p)
    for i := 0; i < n; i++ {
        p[i] = bytes.ToUpper(p[i])
    }
    return n, err
}

// ── A streaming pipeline ───────────────────────────────────

func ProcessFilePipeline(inputPath, outputPath string) error {
    // Step 1: Open input file
    inputFile, err := os.Open(inputPath)
    if err != nil {
        return fmt.Errorf("open input: %w", err)
    }
    defer inputFile.Close()
    
    // Step 2: Create output file
    outputFile, err := os.Create(outputPath)
    if err != nil {
        return fmt.Errorf("create output: %w", err)
    }
    defer outputFile.Close()
    
    // Step 3: Build the pipeline (compose readers and writers)
    //
    // Input:  File → Gzip → AES → Base64 → Writer
    // Output: File ← Gzip ← AES ← Base64 ← Reader
    
    // Writer pipeline (data flows: source → transform → file)
    var writer io.Writer = outputFile
    
    // Layer 1: Buffered writing
    bw := bufio.NewWriterSize(writer, 32*1024)
    writer = bw
    defer bw.Flush()
    
    // Layer 2: Gzip compression
    gzWriter := gzip.NewWriter(writer)
    defer gzWriter.Close()
    writer = gzWriter
    
    // Layer 3: AES encryption
    key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes for AES-256
    block, _ := aes.NewCipher(key)
    iv := make([]byte, aes.BlockSize)
    _, _ = rand.Read(iv)
    writer = cipher.StreamWriter{
        S: cipher.NewCTR(block, iv),
        W: writer,
    }
    
    // Layer 4: Base64 encoding
    writer = base64.NewEncoder(base64.StdEncoding, writer)
    
    // Now write to writer = write through all 4 layers!
    _, err = io.Copy(writer, inputFile)
    if err != nil {
        return fmt.Errorf("process: %w", err)
    }
    
    // Close in order (defer handles reverse order)
    return nil
}

// ── io.Pipe for in-memory streaming ─────────────────────────

func ProcessStream(data io.Reader) error {
    // Create a pipe: Write to pr, Read from pw
    pr, pw := io.Pipe()
    
    // Goroutine 1: Process and write to pipe
    errCh := make(chan error, 1)
    go func() {
        defer pw.Close()
        _, err := io.Copy(pw, data)
        errCh <- err
    }()
    
    // Goroutine 2: Read from pipe and consume
    _, err := io.Copy(os.Stdout, pr)
    if err != nil {
        return err
    }
    
    return <-errCh
}

// ── io.MultiReader and io.MultiWriter ──────────────────────

func MergeAndHash(parts ...io.Reader) (io.Reader, []byte) {
    // Merge multiple readers into one stream
    merged := io.MultiReader(parts...)
    
    // Tee: write to both a hash AND output
    hasher := sha256.New()
    teeReader := io.TeeReader(merged, hasher)
    
    // TeeReader: every Read also writes to hasher
    return teeReader, hasher.Sum(nil)
}

// ── io.LimitedReader for safety ────────────────────────────

func SafeRead(reader io.Reader, maxBytes int64) ([]byte, error) {
    // Limit reader to prevent unbounded reads
    limited := io.LimitReader(reader, maxBytes)
    data, err := io.ReadAll(limited)
    if err != nil {
        return nil, err
    }
    
    // Check if we hit the limit
    if int64(len(data)) == maxBytes {
        // Read more to see if there's more data
        _, err := limited.Read(make([]byte, 1))
        if err != io.EOF {
            return nil, fmt.Errorf("response exceeded %d bytes", maxBytes)
        }
    }
    
    return data, nil
}

// ── Production: streaming JSON decoder ─────────────────────

func ProcessJSONStream(reader io.Reader) error {
    decoder := json.NewDecoder(reader)
    
    // Read opening bracket
    _, err := decoder.Token()
    if err != nil {
        return err
    }
    
    for decoder.More() {
        var item Item
        if err := decoder.Decode(&item); err != nil {
            return fmt.Errorf("decode item: %w", err)
        }
        
        // Process item — no need to load entire array into memory
        if err := processItem(item); err != nil {
            return err
        }
    }
    
    return nil
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Reader/Writer composition** | Chains multiple readers/writers naturally |
| **io.Pipe** | Knows when to use pipe for in-memory streaming |
| **Production patterns** | Buffered I/O, limited reads, streaming JSON |
| **Cleanup** | Proper close ordering, defer handling |

---

## Question 10: `reflect` — When and Why (And When to Avoid It)

**Interviewer:** *"Implement a generic validator that validates struct fields based on tags. Then explain the performance implications and when you'd avoid reflection."*

### 🎯 Expected Answer

```go
// ── Struct tag-based validator ──────────────────────────────

type ValidationError struct {
    Field string
    Tag   string
    Value any
    Err   string
}

func (v ValidationError) Error() string {
    return fmt.Sprintf("%s: %s %s=%v: %s", v.Field, v.Tag, v.Value, v.Err)
}

type ValidationErrors []ValidationError

func (v ValidationErrors) Error() string {
    var buf strings.Builder
    buf.WriteString("validation failed:\n")
    for _, err := range v {
        fmt.Fprintf(&buf, "  - %s\n", err.Error())
    }
    return buf.String()
}

func ValidateStruct(v any) ValidationErrors {
    var errs ValidationErrors
    
    rv := reflect.ValueOf(v)
    
    // Only validate structs
    if rv.Kind() == reflect.Ptr {
        rv = rv.Elem()
    }
    if rv.Kind() != reflect.Struct {
        return errs
    }
    
    rt := rv.Type()
    
    // Walk through all fields
    for i := 0; i < rt.NumField(); i++ {
        field := rt.Field(i)
        value := rv.Field(i)
        
        // Skip unexported fields
        if !field.IsExported() {
            continue
        }
        
        // Get validate tag
        tag := field.Tag.Get("validate")
        if tag == "" {
            continue
        }
        
        // Parse tags
        tagParts := strings.Split(tag, ",")
        for _, t := range tagParts {
            parts := strings.SplitN(t, "=", 2)
            tagName := parts[0]
            tagValue := ""
            if len(parts) > 1 {
                tagValue = parts[1]
            }
            
            err := validateTag(field.Name, tagName, tagValue, value)
            if err != nil {
                errs = append(errs, err)
            }
        }
    }
    
    return errs
}

func validateTag(fieldName, tagName, tagValue string, v reflect.Value) *ValidationError {
    switch tagName {
    case "required":
        if isZero(v) {
            return &ValidationError{
                Field: fieldName,
                Tag:   "required",
                Value: v.Interface(),
                Err:   "field is required",
            }
        }
        
    case "min":
        if tagValue == "" {
            return nil
        }
        minVal, _ := strconv.ParseFloat(tagValue, 64)
        actual := getNumericValue(v)
        if actual < minVal {
            return &ValidationError{
                Field: fieldName,
                Tag:   "min",
                Value: v.Interface(),
                Err:   fmt.Sprintf("must be >= %s", tagValue),
            }
        }
        
    case "max":
        if tagValue == "" {
            return nil
        }
        maxVal, _ := strconv.ParseFloat(tagValue, 64)
        actual := getNumericValue(v)
        if actual > maxVal {
            return &ValidationError{
                Field: fieldName,
                Tag:   "max",
                Value: v.Interface(),
                Err:   fmt.Sprintf("must be <= %s", tagValue),
            }
        }
        
    case "len":
        length, _ := strconv.Atoi(tagValue)
        l := getLength(v)
        if l != length {
            return &ValidationError{
                Field: fieldName,
                Tag:   "len",
                Value: v.Interface(),
                Err:   fmt.Sprintf("length must be %d, got %d", length, l),
            }
        }
        
    case "regex":
        matched, _ := regexp.MatchString(tagValue, fmt.Sprintf("%v", v.Interface()))
        if !matched {
            return &ValidationError{
                Field: fieldName,
                Tag:   "regex",
                Value: v.Interface(),
                Err:   "does not match required pattern",
            }
        }
    }
    
    return nil
}

func isZero(v reflect.Value) bool {
    return v.IsZero()
}

func getNumericValue(v reflect.Value) float64 {
    switch v.Kind() {
    case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
        return float64(v.Int())
    case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
        return float64(v.Uint())
    case reflect.Float32, reflect.Float64:
        return v.Float()
    }
    return 0
}

func getLength(v reflect.Value) int {
    switch v.Kind() {
    case reflect.String, reflect.Slice, reflect.Array, reflect.Map:
        return v.Len()
    }
    return 0
}

// ── Performance implications ────────────────────────────────

func BenchmarkValidate(b *testing.B) {
    user := User{Name: "Alice", Age: 30, Email: "alice@example.com"}
    
    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        ValidateStruct(user)
    }
}

// Result: ~500ns-2μs per validation (reflect is slow)
// For high-throughput paths (>10K/sec), consider:
//
// 1. Code generation (go:generate)
//    - github.com/alecthomas/go_serialization_benchmarks
//    - easyjson for JSON, protoc for protobuf, etc.
//
// 2. Generics (Go 1.18+)
//    - Write type-specific validators that are compiled, not reflected
//
// 3. Pre-compiled validation plans
//    - Cache the reflect.Type analysis once, reuse across calls
//
// Example of code generation approach:
//go:generate go run github.com/Go-validate/generator -type=User
func (u *User) Validate() error {
    // Generated code — type-specific, no reflection
    if u.Name == "" {
        return fmt.Errorf("Name is required")
    }
    if u.Age < 0 || u.Age > 150 {
        return fmt.Errorf("Age must be between 0 and 150")
    }
    // ...
    return nil
}

// ── reflect vs unsafe (for extreme performance) ────────────

// reflect can do anything, but it's slow because:
// 1. All values escape to heap
// 2. Function calls through reflect.Value are not inlineable
// 3. Type checks and method lookups at runtime
//
// unsafe.Pointer is faster but loses all type safety:
func FastFieldAccess(ptr unsafe.Pointer, offset uintptr) unsafe.Pointer {
    return unsafe.Pointer(uintptr(ptr) + offset)
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **reflect mastery** | Can navigate struct fields, tags, kinds, values fluently |
| **Performance awareness** | Knows reflect is slow, offers alternatives (code gen, generics) |
| **Tag parsing** | Handles complex tag syntax (multiple tags, `key=value`) |
| **Production judgment** | Knows when reflect is acceptable vs where to avoid it |

---

## Question 11: Testing — From Unit to Integration to E2E

**Interviewer:** *"Design a testing strategy for a Go microservice. Cover unit tests with mocking, integration tests with testcontainers, and E2E tests. Show me the patterns you use."*

### 🎯 Expected Answer

```go
// ── 1. Unit Tests with Interfaces ───────────────────────────

// Define interfaces for testability
type UserStore interface {
    GetUser(ctx context.Context, id string) (*User, error)
    CreateUser(ctx context.Context, user *User) error
}

// Production implementation uses database
type PostgresUserStore struct {
    db *sql.DB
}

func (s *PostgresUserStore) GetUser(ctx context.Context, id string) (*User, error) {
    // Real database query
}

// Test implementation uses in-memory
type InMemoryUserStore struct {
    mu    sync.RWMutex
    users map[string]*User
}

func (s *InMemoryUserStore) GetUser(ctx context.Context, id string) (*User, error) {
    s.mu.RLock()
    defer s.mu.RUnlock()
    
    user, ok := s.users[id]
    if !ok {
        return nil, fmt.Errorf("user not found: %s", id)
    }
    return user, nil
}

func (s *InMemoryUserStore) CreateUser(ctx context.Context, user *User) error {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.users[user.ID] = user
    return nil
}

// Table-driven tests
func TestUserService_CreateUser(t *testing.T) {
    tests := []struct {
        name    string
        user    *User
        wantErr bool
    }{
        {name: "valid user", user: &User{Name: "Alice", Email: "alice@example.com"}, wantErr: false},
        {name: "missing name", user: &User{Email: "alice@example.com"}, wantErr: true},
        {name: "invalid email", user: &User{Name: "Alice", Email: "not-an-email"}, wantErr: true},
    }
    
    store := &InMemoryUserStore{users: make(map[string]*User)}
    service := NewUserService(store)
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := service.CreateUser(context.Background(), tt.user)
            if (err != nil) != tt.wantErr {
                t.Errorf("CreateUser() error = %v, wantErr = %v", err, tt.wantErr)
            }
        })
    }
}

// ── 2. Integration Tests with Testcontainers ────────────────

//go:build integration

package integration

import (
    "context"
    "testing"
    "time"
    
    "github.com/testcontainers/testcontainers-go"
    "github.com/testcontainers/testcontainers-go/wait"
)

func TestPostgresIntegration(t *testing.T) {
    ctx := context.Background()
    
    // Start PostgreSQL container
    req := testcontainers.ContainerRequest{
        Image:        "postgres:16-alpine",
        ExposedPorts: []string{"5432/tcp"},
        Env: map[string]string{
            "POSTGRES_DB":       "testdb",
            "POSTGRES_USER":     "test",
            "POSTGRES_PASSWORD": "test",
        },
        WaitingFor: wait.ForLog("database system is ready to accept connections").
            WithStartupTimeout(30 * time.Second),
    }
    
    postgres, err := testcontainers.GenericContainer(ctx, 
        testcontainers.GenericContainerRequest{
            ContainerRequest: req,
            Started:          true,
        })
    if err != nil {
        t.Fatal(err)
    }
    defer postgres.Terminate(ctx)
    
    // Get connection string
    host, _ := postgres.Host(ctx)
    port, _ := postgres.MappedPort(ctx, "5432")
    dsn := fmt.Sprintf("postgres://test:test@%s:%s/testdb?sslmode=disable", host, port.Port())
    
    // Connect and run migrations
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        t.Fatal(err)
    }
    defer db.Close()
    
    // Run migrations inline
    _, err = db.Exec(`
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    `)
    if err != nil {
        t.Fatal(err)
    }
    
    // Test actual database operations
    store := NewPostgresUserStore(db)
    
    // Test round-trip
    user := &User{Name: "Alice", Email: "alice@example.com"}
    err = store.CreateUser(ctx, user)
    if err != nil {
        t.Fatal(err)
    }
    
    got, err := store.GetUser(ctx, user.ID)
    if err != nil {
        t.Fatal(err)
    }
    
    if got.Name != user.Name {
        t.Errorf("got %s, want %s", got.Name, user.Name)
    }
}

// ── 3. HTTP Handler Testing ────────────────────────────────

func TestHandler_CreateUser(t *testing.T) {
    // Use httptest for handler-level tests
    store := &InMemoryUserStore{users: make(map[string]*User)}
    handler := NewUserHandler(store)
    
    // Create a test HTTP server
    srv := httptest.NewServer(handler)
    defer srv.Close()
    
    // Send requests
    body := `{"name": "Alice", "email": "alice@example.com"}`
    resp, err := http.Post(srv.URL+"/users", "application/json", 
        strings.NewReader(body))
    if err != nil {
        t.Fatal(err)
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusCreated {
        t.Errorf("got status %d, want %d", resp.StatusCode, http.StatusCreated)
    }
    
    var created User
    json.NewDecoder(resp.Body).Decode(&created)
    
    if created.Name != "Alice" {
        t.Errorf("got name %s, want Alice", created.Name)
    }
}

// ── 4. Subtesting and Parallel Execution ────────────────────

func TestUserService_MultipleScenarios(t *testing.T) {
    // Parallel test execution at the top level
    t.Parallel()
    
    tests := []struct {
        name string
        fn   func(t *testing.T, store UserStore)
    }{
        {name: "can create user", fn: testCreateUser},
        {name: "can get user", fn: testGetUser},
        {name: "duplicate email rejected", fn: testDuplicateEmail},
        {name: "get nonexistent user", fn: testGetNonexistent},
    }
    
    // Shared store for all subtests
    store := &InMemoryUserStore{users: make(map[string]*User)}
    
    for _, tt := range tests {
        tt := tt  // Capture range variable
        t.Run(tt.name, func(t *testing.T) {
            t.Parallel() // Subtests run in parallel too!
            tt.fn(t, store)
        })
    }
}

// ── 5. Fuzz Testing ────────────────────────────────────────

func FuzzParsePhone(f *testing.F) {
    // Seed corpus
    f.Add("+1-555-123-4567")
    f.Add("5551234567")
    f.Add("(555) 123-4567")
    f.Add("invalid")
    
    f.Fuzz(func(t *testing.T, input string) {
        result := ParsePhone(input)
        
        // Property-based assertions
        if result.Valid {
            // If valid, area code must be 3 digits
            if len(result.AreaCode) != 3 {
                t.Errorf("area code length %d, want 3", len(result.AreaCode))
            }
            // If valid, national number must be 7 digits
            if len(result.Number) != 7 {
                t.Errorf("number length %d, want 7", len(result.Number))
            }
            // Reformatting must produce valid output
            formatted := result.Format()
            if formatted == "" {
                t.Errorf("valid number formatted to empty string")
            }
        }
    })
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Table-driven tests** | Uses subtests, has good test cases including edge cases |
| **Interface-based mocking** | Uses real implementations (in-memory) not mock frameworks |
| **Testcontainers** | Knows how to spin up real dependencies for integration tests |
| **Parallel execution** | Uses t.Parallel(), handles shared state correctly |

---

## Question 12: Production Patterns — Graceful Shutdown, Middleware, and Observability

**Interviewer:** *"Design a production HTTP service in Go with graceful shutdown, middleware chaining, structured logging, and metrics. Handle SIGTERM properly."*

### 🎯 Expected Answer

```go
// ═══════════════════════════════════════════════════════════
//  Production Service Framework
// ═══════════════════════════════════════════════════════════

type Service struct {
    name    string
    server  *http.Server
    mux     *http.ServeMux
    logger  *slog.Logger
    metrics *Metrics
    health  *HealthChecker
    liveness   atomic.Bool
    shutdownCh chan struct{}
}

func NewService(name string, addr string, logger *slog.Logger) *Service {
    mux := http.NewServeMux()
    
    return &Service{
        name: name,
        server: &http.Server{
            Addr:         addr,
            Handler:      mux,
            ReadTimeout:  10 * time.Second,
            WriteTimeout: 30 * time.Second,
            IdleTimeout:  120 * time.Second,
        },
        mux:    mux,
        logger: logger,
        health: NewHealthChecker(),
        shutdownCh: make(chan struct{}),
        metrics: NewMetrics(),
    }
}

// ── Middleware Chain ───────────────────────────────────────

type Middleware func(http.Handler) http.Handler

func Chain(middlewares ...Middleware) Middleware {
    return func(final http.Handler) http.Handler {
        for i := len(middlewares) - 1; i >= 0; i-- {
            final = middlewares[i](final)
        }
        return final
    }
}

// Request logging middleware
func (s *Service) LoggingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        wrapped := &responseWriter{ResponseWriter: w, statusCode: http.StatusOK}
        
        next.ServeHTTP(wrapped, r)
        
        s.logger.Info("request",
            slog.String("method", r.Method),
            slog.String("path", r.URL.Path),
            slog.Int("status", wrapped.statusCode),
            slog.Duration("duration", time.Since(start)),
            slog.String("ip", r.RemoteAddr),
            slog.String("user_agent", r.UserAgent()),
        )
    })
}

// Recovery middleware — catch panics
func RecoveryMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        defer func() {
            if rec := recover(); rec != nil {
                // Log with stack trace
                stack := make([]byte, 4096)
                n := runtime.Stack(stack, false)
                log.Printf("PANIC: %v\n%s", rec, stack[:n])
                http.Error(w, "Internal Server Error", http.StatusInternalServerError)
            }
        }()
        next.ServeHTTP(w, r)
    })
}

// Rate limiting middleware (token bucket)
type RateLimiter struct {
    mu       sync.Mutex
    tokens   float64
    maxTokens float64
    refill   float64 // Tokens per second
    lastRefill time.Time
}

func NewRateLimiter(rate float64, burst int) *RateLimiter {
    return &RateLimiter{
        tokens:    float64(burst),
        maxTokens: float64(burst),
        refill:    rate,
        lastRefill: time.Now(),
    }
}

func (rl *RateLimiter) Allow() bool {
    rl.mu.Lock()
    defer rl.mu.Unlock()
    
    now := time.Now()
    elapsed := now.Sub(rl.lastRefill).Seconds()
    rl.tokens = math.Min(rl.maxTokens, rl.tokens+elapsed*rl.refill)
    rl.lastRefill = now
    
    if rl.tokens < 1 {
        return false
    }
    rl.tokens--
    return true
}

func (s *Service) RateLimitMiddleware(next http.Handler) http.Handler {
    limiter := NewRateLimiter(100, 200) // 100 req/s, burst 200
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if !limiter.Allow() {
            w.Header().Set("Retry-After", "1")
            http.Error(w, "Too Many Requests", http.StatusTooManyRequests)
            return
        }
        next.ServeHTTP(w, r)
    })
}

// ── Graceful Shutdown ─────────────────────────────────────

func (s *Service) Start() error {
    s.liveness.Store(true)
    
    // Register routes
    s.mux.HandleFunc("GET /health", s.handleHealth)
    s.mux.HandleFunc("GET /ready", s.handleReady)
    
    // Apply middleware chain
    handler := Chain(
        RecoveryMiddleware,
        s.LoggingMiddleware,
        s.RateLimitMiddleware,
    )(s.mux)
    
    s.server.Handler = handler
    
    // Start server in background
    errCh := make(chan error, 1)
    go func() {
        s.logger.Info("server starting", "addr", s.server.Addr)
        if err := s.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            errCh <- err
        }
    }()
    
    // Listen for shutdown signals
    sigCh := make(chan os.Signal, 1)
    signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM, syscall.SIGQUIT)
    
    select {
    case err := <-errCh:
        return err
    case sig := <-sigCh:
        s.logger.Info("shutdown signal received", "signal", sig)
        return s.Shutdown()
    }
}

func (s *Service) Shutdown() error {
    s.logger.Info("shutting down service")
    s.liveness.Store(false)
    
    // First: stop accepting new requests (liveness fails)
    s.health.SetStatus("shutting_down", false)
    
    // Graceful shutdown with timeout
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    
    // Drain in-flight requests
    if err := s.server.Shutdown(ctx); err != nil {
        s.logger.Error("server shutdown error", "error", err)
        // Force close remaining connections
        s.server.Close()
        return err
    }
    
    close(s.shutdownCh)
    s.logger.Info("service stopped gracefully")
    return nil
}

func (s *Service) handleHealth(w http.ResponseWriter, r *http.Request) {
    if !s.liveness.Load() {
        w.WriteHeader(http.StatusServiceUnavailable)
        json.NewEncoder(w).Encode(map[string]string{"status": "shutting_down"})
        return
    }
    json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (s *Service) handleReady(w http.ResponseWriter, r *http.Request) {
    status := s.health.AllHealthy()
    if !status {
        w.WriteHeader(http.StatusServiceUnavailable)
    }
    json.NewEncoder(w).Encode(map[string]bool{"ready": status})
}

// ── Metrics ────────────────────────────────────────────────

type Metrics struct {
    mu         sync.Mutex
    counters   map[string]int64
    gauges     map[string]float64
    histograms map[string][]time.Duration
}

func NewMetrics() *Metrics {
    return &Metrics{
        counters:   make(map[string]int64),
        gauges:     make(map[string]float64),
        histograms: make(map[string][]time.Duration),
    }
}

func (m *Metrics) Increment(name string) {
    m.mu.Lock()
    defer m.mu.Unlock()
    m.counters[name]++
}

func (m *Metrics) RecordDuration(name string, d time.Duration) {
    m.mu.Lock()
    defer m.mu.Unlock()
    m.histograms[name] = append(m.histograms[name], d)
}

// In production, use prometheus client:

// ═══════════════════════════════════════════════════════════
//  Usage
// ═══════════════════════════════════════════════════════════

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
        Level: slog.LevelInfo,
    }))
    
    svc := NewService("my-api", ":8080", logger)
    
    if err := svc.Start(); err != nil {
        logger.Error("service failed", "error", err)
        os.Exit(1)
    }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Graceful shutdown** | Handles SIGTERM, drains connections, respects timeout |
| **Middleware chain** | Applies middleware in correct order, clean composition |
| **Observability** | Structured logging, health checks, readiness probes, metrics |
| **Production readiness** | Timeouts, recovery from panics, rate limiting, connection limits |

---

## 📊 Staff-Level Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Cites Go source code (runtime/proc.go, runtime/chan.go), references commits/versions, has shipped production workarounds for GC/goroutine issues. Discusses trade-offs without prompting. |
| **4 — Strong** | Deep understanding of GMP, GC phases, channel internals, memory model. Can implement lock-free patterns, design production services. Knows the tooling (pprof, trace, race detector). |
| **3 — Competent** | Good Go programmer. Knows goroutines, channels, interfaces, error handling. But doesn't understand scheduling internals or GC pacing deeply. |
| **2 — Developing** | Proficient with Go syntax but doesn't understand why things work. No production experience at scale. |
| **1 — Needs Growth** | Can write basic Go but doesn't understand concurrency patterns, interface satisfaction, or the toolchain. |

---

> *Built for experienced Go engineers targeting Staff/Principal roles at top-tier companies*
