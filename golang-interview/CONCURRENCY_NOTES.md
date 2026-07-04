# 🦦 Go Concurrency & Multithreading — Practical Notes

> **A hands-on guide to writing concurrent Go code: goroutines, channels, synchronization, and production patterns**
> *From basics to staff-level depth*

---

## Table of Contents

1. [Concurrency vs Parallelism vs Multithreading](#1-concurrency-vs-parallelism-vs-multithreading)
2. [Goroutines — The Lightweight Thread](#2-goroutines--the-lightweight-thread)
3. [Channels — Communicating Between Goroutines](#3-channels--communicating-between-goroutines)
4. [Moving Data Through Channels](#4-moving-data-through-channels)
5. [Structs and Channels](#5-structs-and-channels)
6. [The Select Statement](#6-the-select-statement)
7. [Synchronization Primitives](#7-synchronization-primitives)
8. [sync/atomic — Lock-Free Operations](#8-syncatomic--lock-free-operations)
9. [Context — Cancellation & Deadlines](#9-context--cancellation--deadlines)
10. [Production Concurrency Patterns](#10-production-concurrency-patterns)
11. [Common Pitfalls & Debugging](#11-common-pitfalls--debugging)
12. [Concurrency & Parallelism Interview Questions](#12-concurrency--parallelism-interview-questions)

---

## 1. Concurrency vs Parallelism vs Multithreading

### Definitions

```go
// ── CONCURRENCY ──────────────────────────────────────────────
// "Dealing with many things at once" — Rob Pike
// Structure: composing independently executing tasks
// Go's superpower: you structure your program as concurrent
//   goroutines, and the runtime maps them to parallel execution.
//
// go func() { ... }()  // This is CONCURRENT design
// The runtime decides if it runs in PARALLEL.

// ── PARALLELISM ──────────────────────────────────────────────
// "Doing many things at once" — Rob Pike
// Execution: actually running on multiple cores simultaneously
// Requires: GOMAXPROCS > 1 (default = runtime.NumCPU())
// Go handles this via GMP scheduler.
//
// runtime.GOMAXPROCS(4)  // Allow parallel execution on 4 cores

// ── MULTITHREADING ──────────────────────────────────────────
// Go abstracts OS threads behind goroutines.
// You don't manage threads — Go does.
// M:N threading: M goroutines scheduled on N OS threads.
//
// OS Thread (M)  ← Goroutine (G) ← Goroutine (G) ← ...
//        ↓
//   Processor (P) — one per GOMAXPROCS
```

### Go's Approach

| Concept | Traditional OS | Go |
|---------|---------------|----|
| Unit of execution | OS thread (MB stack) | Goroutine (2KB stack, growable) |
| Creation cost | ~1MB memory, syscall | ~2KB, user-space |
| Context switch | Kernel-mode (~1μs) | User-mode (~100ns) |
| Communication | Shared memory + locks | Channels (prefer) + sync |
| Scheduler | Kernel preemptive | Go runtime (cooperative + preemptive) |

### When to Use What

```go
// ── DECISION TREE ───────────────────────────────────────────

// 1. I/O-bound work (network, files, databases)
//    → Goroutines + channels (async by design)
//    go fetchURL(ctx, url)

// 2. CPU-bound work (computation, data processing)
//    → Goroutines + GOMAXPROCS
//    runtime.GOMAXPROCS(runtime.NumCPU())
//    for i := 0; i < runtime.NumCPU(); i++ {
//        go worker(jobs)
//    }

// 3. Sequential logic with occasional blocking
//    → Simple goroutines with select
//    go periodicTask(ctx, interval)

// 4. N-to-M communication (multiple producers, multiple consumers)
//    → Channels (buffered)
//    jobs := make(chan Job, 100)
```

---

## 2. Goroutines — The Lightweight Thread

### Creating Goroutines

```go
// ── Basic goroutine ─────────────────────────────────────────
go fmt.Println("Hello from goroutine") // Simplest possible

// ── Anonymous function ──────────────────────────────────────
go func() {
    result := expensiveComputation()
    fmt.Println("Result:", result)
}()

// ── Named function with arguments ───────────────────────────
go processData(ctx, inputCh, outputCh)

// ── Goroutine with wait ─────────────────────────────────────
var wg sync.WaitGroup
for i := 0; i < 10; i++ {
    wg.Add(1)
    go func(id int) {
        defer wg.Done()
        fmt.Printf("Worker %d starting\n", id)
        time.Sleep(time.Second)
    }(i)
}
wg.Wait() // Wait for ALL goroutines
```

### Goroutine Lifecycle

```
┌──────────┐     ┌────────────┐     ┌──────────┐     ┌───────────┐
│ _Gidle   │────→│ _Grunnable │────→│ _Grunning │────→│ _Gdead    │
└──────────┘     └────────────┘     └──────────┘     └───────────┘
                       ↑                 │    ↘
                       │                 │     ┌──────────┐
                       │                 │     │_Gsyscall │
                       │                 │     └──────────┘
                       │                 │    ↗
                       │                 │     ┌──────────┐
                       │                 │     │_Gwaiting │
                       │                 │     └──────────┘
                       │                 │    ↗
                       └─────────────────┘
```

### Key Properties

```go
// 1. Stack starts at ~2KB, grows as needed (up to 1GB on 64-bit)
//    → You can have 100K+ goroutines without memory issues

// 2. Goroutines are NOT garbage collected
//    → You must ensure they complete or are cancelled
//    → Leaked goroutines = memory leak that never goes away

// 3. Goroutines share the same address space
//    → Race conditions are possible (and dangerous)
//    → Use channels or sync primitives to coordinate

// 4. The go statement is a "fire and forget"
//    → The caller doesn't wait
//    → Use channels/WaitGroup to get results
```

### Goroutine Leaks — The #1 Mistake

```go
// 🔴 LEAK: Goroutine blocks forever on channel send
func leak() {
    ch := make(chan int)  // Unbuffered
    go func() {
        ch <- 42  // Blocks forever — no one reads!
    }()
    // Goroutine never exits
}

// ✅ FIX: Use context or buffered channel
func noLeak(ctx context.Context) {
    ch := make(chan int, 1)  // Buffered
    go func() {
        select {
        case ch <- 42:
        case <-ctx.Done():
            return
        }
    }()
}

// 🔴 LEAK: Reading from channel that never closes
func leakReader() {
    ch := make(chan int)
    go func() {
        for v := range ch { // Never exits — ch never closed
            fmt.Println(v)
        }
    }()
    ch <- 1
    // ch is never closed, goroutine runs forever
}

// ✅ FIX: Close the channel when done, or use done channel
func noLeakReader() {
    ch := make(chan int)
    done := make(chan struct{})
    
    go func() {
        defer fmt.Println("reader exited")
        for {
            select {
            case v, ok := <-ch:
                if !ok {
                    return // Channel closed
                }
                fmt.Println(v)
            case <-done:
                return // Cancelled
            }
        }
    }()
    
    ch <- 1
    close(ch)
    // Reader exits because range loop ends
}
```

---

## 3. Channels — Communicating Between Goroutines

### Channel Anatomy

```go
// ── Channel internals (runtime/chan.go) ────────────────────
//
// type hchan struct {
//     qcount   uint           // Elements in buffer
//     dataqsiz uint           // Buffer capacity (0 = unbuffered)
//     buf      unsafe.Pointer // Circular buffer
//     elemsize uint16         // Element size
//     closed   uint32         // 0 = open, 1 = closed
//     elemtype *_type
//     sendx    uint           // Send index in circular buffer
//     recvx    uint           // Receive index in circular buffer
//     recvq    waitq          // Goroutines blocked on receive
//     sendq    waitq          // Goroutines blocked on send
//     lock     mutex          // Protects the channel
// }

// ── Creating channels ───────────────────────────────────────

// Unbuffered: synchronous — send blocks until someone receives
ch := make(chan int)

// Buffered: asynchronous — send blocks only when buffer is full
ch := make(chan int, 100)

// Directional channels (compile-time enforced):
var sendOnly chan<- int  // Can only send
var recvOnly <-chan int  // Can only receive

// Convert bidirectional to directional:
ch := make(chan int)
var out chan<- int = ch  // OK
var in <-chan int = ch   // OK
// ch2 := make(chan<- int) // Can't convert back to bidirectional!
```

### Channel Operations

```go
// ── SEND ────────────────────────────────────────────────────
ch <- value  // Blocks until:
             // - Unbuffered: a receiver is ready
             // - Buffered: buffer has space
             // - Never on a nil channel (blocks forever)
             // - Panics on a closed channel

// ── RECEIVE ─────────────────────────────────────────────────
value := <-ch         // Blocks until data available
value, ok := <-ch     // ok == false when channel is closed AND empty

// ── CLOSE ───────────────────────────────────────────────────
close(ch)  // Panics if already closed
// After close: receives succeed (draining), sends panic

// ── NIL CHANNEL ─────────────────────────────────────────────
var ch chan int  // nil
ch <- 1          // Blocks FOREVER (handy in select: disable cases)
<-ch             // Blocks FOREVER
close(ch)        // PANIC: close of nil channel
```

### Channel Types

```go
// ── UNBUFFERED CHANNEL (synchronous) ───────────────────────
// Use: guaranteed synchronization, rendezvous
func unbuffered() {
    ch := make(chan int)
    
    go func() {
        ch <- 42  // Will block until main goroutine receives
        fmt.Println("Sent!") // Only runs AFTER receive
    }()
    
    time.Sleep(time.Second) // Simulate work
    val := <-ch             // Unblocks the sender
    fmt.Println("Received:", val)
}

// ── BUFFERED CHANNEL (asynchronous) ─────────────────────────
// Use: decouple sender/receiver, burst handling, bounded queues
func buffered() {
    ch := make(chan int, 3)
    
    ch <- 1  // No block (buffer: [1, _, _])
    ch <- 2  // No block (buffer: [1, 2, _])
    ch <- 3  // No block (buffer: [1, 2, 3])
    // ch <- 4  // BLOCK (buffer full)
    
    fmt.Println(<-ch) // 1 (buffer: [_, 2, 3])
    fmt.Println(<-ch) // 2
    fmt.Println(<-ch) // 3
}

// ── CHANNEL OF CHANNELS (multiplexing) ──────────────────────
// Use: reply channels, RPC patterns
type Request struct {
    Data   string
    RespCh chan Response
}

func handler(requests <-chan Request) {
    for req := range requests {
        result := process(req.Data)
        req.RespCh <- Response{Result: result}
    }
}

// ── ZERO-SIZE CHANNEL (signaling only) ──────────────────────
// Use: signal events (no data needed)
done := make(chan struct{}) // struct{} is zero bytes
// close(done) signals — all receivers get zero value immediately
```

---

## 4. Moving Data Through Channels

### Basic Data Flow

```go
// ── One producer, one consumer ──────────────────────────────
func produce(ctx context.Context, out chan<- int) {
    defer close(out)
    for i := 0; i < 10; i++ {
        select {
        case out <- i:
        case <-ctx.Done():
            return
        }
    }
}

func consume(ctx context.Context, in <-chan int) {
    for v := range in {
        fmt.Println("Got:", v)
    }
}

// ── Multiple producers, single consumer ─────────────────────
func merge(ctx context.Context, producers ...<-chan int) <-chan int {
    out := make(chan int)
    var wg sync.WaitGroup
    
    // Start a goroutine for each producer
    for _, p := range producers {
        wg.Add(1)
        go func(ch <-chan int) {
            defer wg.Done()
            for v := range ch {
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            }
        }(p)
    }
    
    // Close output when all producers are done
    go func() {
        wg.Wait()
        close(out)
    }()
    
    return out
}

// ── Single producer, multiple consumers ─────────────────────
func distribute(ctx context.Context, in <-chan int, n int) []<-chan int {
    channels := make([]<-chan int, n)
    for i := 0; i < n; i++ {
        ch := make(chan int)
        channels[i] = ch
        go func(out chan<- int) {
            defer close(out)
            for v := range in {
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            }
        }(ch)
    }
    return channels
}
```

### Channel Direction for Data Flow

```go
// ── Using function signatures to enforce data flow ─────────

// Producer: can only SEND
func gen(ctx context.Context) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for i := 0; i < 100; i++ {
            select {
            case out <- i:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Transformer: receives, processes, sends
func square(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for v := range in {
            select {
            case out <- v * v:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Consumer: can only RECEIVE
func sink(ctx context.Context, in <-chan int) {
    for v := range in {
        fmt.Println(v)
    }
}
```

### Closing Channels — Rules & Patterns

```go
// ── RULE: The sender should close the channel ───────────────
// Never close from the receiver side.
// Closing a channel is a signal: "no more data"

// ── PATTERN: Deferred close ─────────────────────────────────
func producer(out chan<- int) {
    defer close(out) // Always close when done
    for i := 0; i < 10; i++ {
        out <- i
    }
}

// ── PATTERN: Closing with sync.Once ─────────────────────────
// For multiple goroutines that might close the same channel
type SafeClose struct {
    once sync.Once
    ch   chan struct{}
}

func (s *SafeClose) Close() {
    s.once.Do(func() {
        close(s.ch)
    })
}

// ── PATTERN: Nil channel to disable select cases ───────────
func multiplex(ctx context.Context, in1, in2 <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        
        // Set both channels to their initial values
        ch1, ch2 := in1, in2
        var v1, v2 int
        var ok1, ok2 bool
        
        for {
            select {
            case v1, ok1 = <-ch1:
                // Got value from ch1
                if !ok1 {
                    ch1 = nil // Disable this case forever
                    if ch2 == nil {
                        return // Both channels done
                    }
                    continue
                }
            case v2, ok2 = <-ch2:
                if !ok2 {
                    ch2 = nil
                    if ch1 == nil {
                        return
                    }
                    continue
                }
            }
            
            // Send to output (but don't block)
            select {
            case out <- v1:
            case out <- v2:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}
```

### Ring Buffer Channel (Bounded Queue)

```go
type RingChannel[T any] struct {
    buf    []T
    head   int
    tail   int
    count  int
    cap    int
    sendCh chan T
    recvCh chan T
    done   chan struct{}
    mu     sync.Mutex
    notFull  *sync.Cond
    notEmpty *sync.Cond
}

func NewRingChannel[T any](capacity int) *RingChannel[T] {
    rc := &RingChannel[T]{
        buf:    make([]T, capacity),
        cap:    capacity,
        sendCh: make(chan T),
        recvCh: make(chan T),
        done:   make(chan struct{}),
    }
    rc.notFull = sync.NewCond(&rc.mu)
    rc.notEmpty = sync.NewCond(&rc.mu)
    go rc.run()
    return rc
}

func (rc *RingChannel[T]) run() {
    for {
        rc.mu.Lock()
        for rc.count == 0 {
            rc.notEmpty.Wait() // Block until not empty
        }
        
        val := rc.buf[rc.head]
        rc.head = (rc.head + 1) % rc.cap
        rc.count--
        
        rc.notFull.Signal() // Wake up blocked senders
        rc.mu.Unlock()
        
        select {
        case rc.recvCh <- val:
        case <-rc.done:
            return
        }
    }
}

func (rc *RingChannel[T]) Send(val T) {
    rc.mu.Lock()
    for rc.count == rc.cap {
        rc.notFull.Wait() // Block until not full
    }
    rc.buf[rc.tail] = val
    rc.tail = (rc.tail + 1) % rc.cap
    rc.count++
    rc.notEmpty.Signal()
    rc.mu.Unlock()
}

func (rc *RingChannel[T]) Receive() T {
    return <-rc.recvCh
}

func (rc *RingChannel[T]) Close() {
    close(rc.done)
}
```

---

## 5. Structs and Channels

### Channels of Structs

```go
// ── Passing structured data through channels ────────────────
type Task struct {
    ID      int
    Payload string
    Priority int
    Created time.Time
}

type Result struct {
    TaskID   int
    Output   string
    Duration time.Duration
    Err      error
}

// Producer sends Tasks
func taskProducer(ctx context.Context, tasks []Task) <-chan Task {
    out := make(chan Task, len(tasks))
    go func() {
        defer close(out)
        for _, t := range tasks {
            select {
            case out <- t:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Worker receives Tasks, sends Results
func worker(ctx context.Context, id int, tasks <-chan Task, results chan<- Result) {
    for task := range tasks {
        start := time.Now()
        
        // Process task
        output, err := processTask(task)
        
        select {
        case results <- Result{
            TaskID:   task.ID,
            Output:   output,
            Duration: time.Since(start),
            Err:      err,
        }:
        case <-ctx.Done():
            return
        }
    }
}
```

### Structs Containing Channels

```go
// ── Worker pool using struct with embedded channels ─────────
type Worker struct {
    ID       int
    JobQueue chan Job
    Quit     chan struct{}
}

func NewWorker(id int) *Worker {
    return &Worker{
        ID:       id,
        JobQueue: make(chan Job),
        Quit:     make(chan struct{}),
    }
}

func (w *Worker) Start(ctx context.Context, results chan<- Result) {
    go func() {
        defer fmt.Printf("Worker %d stopped\n", w.ID)
        for {
            select {
            case job := <-w.JobQueue:
                result := w.execute(job)
                select {
                case results <- result:
                case <-ctx.Done():
                    return
                }
            case <-w.Quit:
                return
            case <-ctx.Done():
                return
            }
        }
    }()
}

func (w *Worker) Stop() {
    close(w.Quit)
}

func (w *Worker) execute(job Job) Result {
    // ... process job
    return Result{WorkerID: w.ID, JobID: job.ID, Output: "done"}
}

// ── Dispatcher manages the pool ─────────────────────────────
type Dispatcher struct {
    workers   []*Worker
    jobQueue  chan Job
    results   chan Result
    maxWorkers int
}

func NewDispatcher(maxWorkers int) *Dispatcher {
    return &Dispatcher{
        workers:    make([]*Worker, maxWorkers),
        jobQueue:   make(chan Job, 100),
        results:    make(chan Result, 100),
        maxWorkers: maxWorkers,
    }
}

func (d *Dispatcher) Start(ctx context.Context) {
    for i := 0; i < d.maxWorkers; i++ {
        worker := NewWorker(i)
        worker.Start(ctx, d.results)
        d.workers[i] = worker
    }
    
    // Distribute jobs to workers
    go func() {
        for job := range d.jobQueue {
            // Round-robin or use select across workers
            worker := d.workers[job.ID%d.maxWorkers]
            select {
            case worker.JobQueue <- job:
            case <-ctx.Done():
                return
            }
        }
    }()
}

// Channel as struct field — advanced patterns
type Service struct {
    // Request channel — external callers send here
    requestCh chan Request
    
    // Internal channels
    stopCh    chan struct{}
    readyCh   chan struct{}
    
    // State
    lastValue string
    client    *http.Client
}

func NewService() *Service {
    s := &Service{
        requestCh: make(chan Request, 10),
        stopCh:    make(chan struct{}),
        readyCh:   make(chan struct{}),
        client:    &http.Client{Timeout: 5 * time.Second},
    }
    go s.loop()
    return s
}

func (s *Service) loop() {
    // Wait until ready
    close(s.readyCh)
    
    for {
        select {
        case req := <-s.requestCh:
            s.handleRequest(req)
        case <-s.stopCh:
            return
        }
    }
}

func (s *Service) Handle(req Request) {
    s.requestCh <- req
}

func (s *Service) WaitReady() {
    <-s.readyCh
}

func (s *Service) Stop() {
    close(s.stopCh)
}
```

### Immutable Structs Through Channels

```go
// ── Immutable state by passing snapshots through channels ───

// State is private to the owning goroutine
type CounterState struct {
    value    int64
    lastUpdated time.Time
}

func (c CounterState) Value() int64 {
    return c.value
}

// Operations are commands passed through channels
type CounterCommand interface {
    Apply(CounterState) CounterState
}

type Increment struct{}
func (Increment) Apply(s CounterState) CounterState {
    s.value++
    s.lastUpdated = time.Now()
    return s
}

type Add struct {
    N int64
}
func (a Add) Apply(s CounterState) CounterState {
    s.value += a.N
    s.lastUpdated = time.Now()
    return s
}

type Reset struct{}
func (Reset) Apply(s CounterState) CounterState {
    s.value = 0
    s.lastUpdated = time.Now()
    return s
}

// Counter actor — state encapsulated in goroutine
type Counter struct {
    commands chan CounterCommand
    queries  chan chan int64
}

func NewCounter(initial int64) *Counter {
    c := &Counter{
        commands: make(chan CounterCommand, 100),
        queries:  make(chan chan int64),
    }
    go c.run(CounterState{
        value:       initial,
        lastUpdated: time.Now(),
    })
    return c
}

func (c *Counter) run(state CounterState) {
    for {
        select {
        case cmd := <-c.commands:
            state = cmd.Apply(state) // New state, old state discarded
        case resp := <-c.queries:
            resp <- state.Value()
        }
    }
}

func (c *Counter) Increment() {
    c.commands <- Increment{}
}

func (c *Counter) Add(n int64) {
    c.commands <- Add{N: n}
}

func (c *Counter) Value() int64 {
    resp := make(chan int64)
    c.queries <- resp
    return <-resp
}
```

---

## 6. The Select Statement

### Basic Patterns

```go
// ── Basic select — wait for either channel ──────────────────
select {
case v := <-ch1:
    fmt.Println("Got from ch1:", v)
case v := <-ch2:
    fmt.Println("Got from ch2:", v)
}

// ── Select with default — non-blocking ──────────────────────
select {
case v := <-ch:
    fmt.Println("Got:", v)
default:
    fmt.Println("No data available, moving on")
}

// ── Select with timeout ─────────────────────────────────────
select {
case v := <-ch:
    fmt.Println("Got:", v)
case <-time.After(5 * time.Second):
    fmt.Println("Timeout waiting for data")
}

// ── Select with send and receive ────────────────────────────
select {
case ch <- value:
    fmt.Println("Sent to channel")
case v := <-ch:
    fmt.Println("Received from channel")
case <-ctx.Done():
    fmt.Println("Cancelled:", ctx.Err())
}
```

### The Nil Channel Trick

```go
// ── Dynamically enable/disable select cases ─────────────────
//
// A nil channel is NEVER chosen in select.
// So setting a channel to nil "disables" that case.

func merge(ctx context.Context, ch1, ch2 <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        
        // Both channels alive initially
        for ch1 != nil || ch2 != nil {
            select {
            case v, ok := <-ch1:
                if !ok {
                    ch1 = nil // Disable this case
                    continue
                }
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            case v, ok := <-ch2:
                if !ok {
                    ch2 = nil // Disable this case
                    continue
                }
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}
```

### Priority Select

```go
// ── Simulate priority: prefer one channel over another ──────

func prioritySelect(ctx context.Context, high, low <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for {
            select {
            case v := <-high:
                // Process high priority immediately
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            default:
                // No high priority — try low
                select {
                case v := <-high: // Check high again (can't starve low)
                    select {
                    case out <- v:
                    case <-ctx.Done():
                        return
                    }
                case v := <-low:
                    select {
                    case out <- v:
                    case <-ctx.Done():
                        return
                    }
                case <-ctx.Done():
                    return
                }
            }
        }
    }()
    return out
}
```

---

## 7. Synchronization Primitives

### sync.WaitGroup

```go
// ── WaitGroup — wait for goroutines to complete ─────────────
func processBatch(items []Item) []Result {
    var wg sync.WaitGroup
    results := make([]Result, len(items))
    
    for i, item := range items {
        wg.Add(1)
        go func(idx int, it Item) {
            defer wg.Done()
            results[idx] = process(it)
        }(i, item)
    }
    
    wg.Wait() // Blocks until all Done() calls
    return results
}

// ── Common mistake: Add after goroutine starts ──────────────
// 🔴 BAD
go func() {
    wg.Add(1) // Race condition — main might reach wg.Wait() before this runs
    defer wg.Done()
    doWork()
}()

// ✅ GOOD
wg.Add(1)
go func() {
    defer wg.Done()
    doWork()
}()

// ── WaitGroup with error collection ─────────────────────────
type ErrorGroup struct {
    mu     sync.Mutex
    errors []error
}

func (eg *ErrorGroup) Add(err error) {
    if err != nil {
        eg.mu.Lock()
        eg.errors = append(eg.errors, err)
        eg.mu.Unlock()
    }
}

func (eg *ErrorGroup) Err() error {
    eg.mu.Lock()
    defer eg.mu.Unlock()
    if len(eg.errors) == 0 {
        return nil
    }
    return fmt.Errorf("%d errors: %v", len(eg.errors), eg.errors)
}

func parallelWork(items []string) error {
    var wg sync.WaitGroup
    var eg ErrorGroup
    
    for _, item := range items {
        wg.Add(1)
        go func(s string) {
            defer wg.Done()
            if err := process(s); err != nil {
                eg.Add(err)
            }
        }(item)
    }
    
    wg.Wait()
    return eg.Err()
}
```

### sync.Mutex & sync.RWMutex

```go
// ── Mutex — mutual exclusion ────────────────────────────────
type SafeCounter struct {
    mu    sync.Mutex
    value int64
}

func (c *SafeCounter) Increment() {
    c.mu.Lock()
    c.value++  // Only one goroutine at a time
    c.mu.Unlock()
}

func (c *SafeCounter) Value() int64 {
    c.mu.Lock()
    defer c.mu.Unlock()
    return c.value
}

// ── RWMutex — reader/writer lock ────────────────────────────
type SafeCache struct {
    mu    sync.RWMutex
    data  map[string]any
}

func (c *SafeCache) Get(key string) any {
    c.mu.RLock()          // Multiple readers allowed
    defer c.mu.RUnlock()
    return c.data[key]
}

func (c *SafeCache) Set(key string, value any) {
    c.mu.Lock()           // Exclusive — no readers or writers
    defer c.mu.Unlock()
    c.data[key] = value
}

// ── Deadlock example ────────────────────────────────────────
// 🔴 BAD: Lock ordering inconsistency
type Account struct {
    mu    sync.Mutex
    balance float64
}

func Transfer(a, b *Account, amount float64) {
    a.mu.Lock()
    b.mu.Lock()
    a.balance -= amount
    b.balance += amount
    a.mu.Unlock()
    b.mu.Unlock()
}
// If goroutine 1 calls Transfer(acctA, acctB, 100)
// and goroutine 2 calls Transfer(acctB, acctA, 50)
// → DEADLOCK! Each holds one lock, waiting for the other.

// ✅ GOOD: Consistent lock ordering (by memory address)
func SafeTransfer(a, b *Account, amount float64) {
    // Always lock the lower address first
    aPtr := uintptr(unsafe.Pointer(a))
    bPtr := uintptr(unsafe.Pointer(b))
    
    if aPtr < bPtr {
        a.mu.Lock()
        b.mu.Lock()
    } else {
        b.mu.Lock()
        a.mu.Lock()
    }
    
    a.balance -= amount
    b.balance += amount
    
    if aPtr < bPtr {
        b.mu.Unlock()
        a.mu.Unlock()
    } else {
        a.mu.Unlock()
        b.mu.Unlock()
    }
}
```

### sync.Once

```go
// ── sync.Once — run initialization exactly once ─────────────
type Singleton struct {
    once     sync.Once
    instance *ExpensiveDB
    err      error
}

func (s *Singleton) Get() (*ExpensiveDB, error) {
    s.once.Do(func() {
        s.instance, s.err = NewExpensiveDB()
    })
    return s.instance, s.err
}

// ── Lazy singleton with error ───────────────────────────────
var (
    connOnce sync.Once
    conn     *sql.DB
    connErr  error
)

func GetConnection() (*sql.DB, error) {
    connOnce.Do(func() {
        conn, connErr = sql.Open("postgres", os.Getenv("DATABASE_URL"))
    })
    return conn, connErr
}
```

### sync.Cond

```go
// ── Condition Variable — signal/wait pattern ────────────────
type Queue struct {
    items []int
    cond  *sync.Cond
}

func NewQueue() *Queue {
    return &Queue{
        cond: sync.NewCond(&sync.Mutex{}),
    }
}

func (q *Queue) Enqueue(item int) {
    q.cond.L.Lock()
    q.items = append(q.items, item)
    q.cond.L.Unlock()
    q.cond.Signal() // Wake one waiting goroutine
}

func (q *Queue) Dequeue() int {
    q.cond.L.Lock()
    defer q.cond.L.Unlock()
    
    for len(q.items) == 0 {
        q.cond.Wait() // Release lock and sleep
    }
    
    item := q.items[0]
    q.items = q.items[1:]
    return item
}

// ── Broadcast — wake all waiters ───────────────────────────
// q.cond.Broadcast() // Used for "all hands" events like shutdown
```

### sync.Pool

```go
// ── Object Pool — reduce GC pressure ────────────────────────
var bufferPool = sync.Pool{
    New: func() any {
        return new(bytes.Buffer)
    },
}

func processRequest(data []byte) string {
    buf := bufferPool.Get().(*bytes.Buffer)
    buf.Reset()
    defer bufferPool.Put(buf)
    
    buf.Write(data)
    // ... processing
    return buf.String()
}

// ── Pool for expensive structs ──────────────────────────────
type LargeStruct struct {
    Data [1024]byte
    Meta map[string]any
}

var largePool = sync.Pool{
    New: func() any {
        return &LargeStruct{
            Meta: make(map[string]any, 16),
        }
    },
}

func GetLarge() *LargeStruct {
    return largePool.Get().(*LargeStruct)
}

func PutLarge(s *LargeStruct) {
    // Reset before returning
    clear(s.Meta) // Go 1.21+
    largePool.Put(s)
}
```

---

## 8. sync/atomic — Lock-Free Operations

### Atomic Types (Go 1.19+)

```go
// ── Atomic counter ──────────────────────────────────────────
var counter atomic.Int64

func increment() {
    counter.Add(1)
}

func value() int64 {
    return counter.Load()
}

// ── Atomic boolean (flag) ──────────────────────────────────
var ready atomic.Bool

func setReady() {
    ready.Store(true)
}

func isReady() bool {
    return ready.Load()
}

// ── Compare and swap (CAS) ─────────────────────────────────
var value atomic.Int64

func tryIncrement() bool {
    for {
        old := value.Load()
        if value.CompareAndSwap(old, old+1) {
            return true
        }
        // CAS failed — someone else changed it, retry
    }
}

// ── Atomic pointer — lock-free read cache ───────────────────
type Config struct {
    mu     sync.Mutex
    config atomic.Pointer[ConfigData]
}

func (c *Config) Get() ConfigData {
    return *c.config.Load() // Lock-free read!
}

func (c *Config) Update(data ConfigData) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.config.Store(&data) // Atomic pointer swap
}
```

### Lock-Free Data Structures

```go
// ── Lock-free stack (Treiber stack) ─────────────────────────
type LockFreeStack[T any] struct {
    top atomic.Pointer[node[T]]
}

type node[T any] struct {
    value T
    next  *node[T]
}

func (s *LockFreeStack[T]) Push(value T) {
    new := &node[T]{value: value}
    for {
        new.next = s.top.Load()
        if s.top.CompareAndSwap(new.next, new) {
            return // Success!
        }
        // CAS failed — retry with updated top
    }
}

func (s *LockFreeStack[T]) Pop() (T, bool) {
    for {
        old := s.top.Load()
        if old == nil {
            var zero T
            return zero, false // Empty
        }
        if s.top.CompareAndSwap(old, old.next) {
            return old.value, true
        }
        // CAS failed — retry
    }
}
```

### Memory Ordering

```go
// ── Go uses sequentially consistent atomics ─────────────────
// This means all goroutines see atomic operations in the same order.
// On x86: MOV instruction (cheap)
// On ARM: LDAR/STLR instructions (more expensive)

// ── Happens-before with atomics ─────────────────────────────
var data atomic.Pointer[LargeData]

// Goroutine 1: writer
func writer() {
    d := computeExpensive()
    data.Store(&d) // Store happens BEFORE any Load that sees it
}

// Goroutine 2: reader
func reader() {
    d := data.Load() // Load happens AFTER the Store that set this value
    fmt.Println(d.Value) // Guaranteed to see `d` fully initialized
}

// ── This is the "publication" pattern ───────────────────────
// atomic Store = "publish" (acts as release barrier)
// atomic Load = "subscribe" (acts as acquire barrier)
```

---

## 9. Context — Cancellation & Deadlines

### Context Trees

```go
// ── Context hierarchy ───────────────────────────────────────
//                    background
//                        │
//                   ┌────┴────┐
//                   │         │
//               timeout    value
//                   │         │
//              ┌────┼────┐   │
//              │    │    │   │
//            sub1 sub2 sub3  └── withCancel
//              │                   │
//           value              withDeadline

// ── Parent cancels → all children cancel ────────────────────
func handle(ctx context.Context) error {
    // Create child with timeout
    childCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
    defer cancel() // Must call to avoid leak!
    
    return process(childCtx)
}
```

### Propagation Patterns

```go
// ── Propagate context through channel operations ────────────
func fetchData(ctx context.Context, url string) (<-chan Data, <-chan error) {
    dataCh := make(chan Data, 1)
    errCh := make(chan error, 1)
    
    go func() {
        defer close(dataCh)
        defer close(errCh)
        
        req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
        resp, err := http.DefaultClient.Do(req)
        if err != nil {
            errCh <- err
            return
        }
        defer resp.Body.Close()
        
        var data Data
        if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
            errCh <- err
            return
        }
        
        select {
        case dataCh <- data:
        case <-ctx.Done():
        }
    }()
    
    return dataCh, errCh
}

// ── Fan-out with context ────────────────────────────────────
func fanOutWithContext[T any](ctx context.Context, in <-chan T, workers int) []<-chan T {
    channels := make([]<-chan T, workers)
    
    for i := 0; i < workers; i++ {
        ch := make(chan T)
        channels[i] = ch
        
        go func(out chan<- T) {
            defer close(out)
            for {
                select {
                case val, ok := <-in:
                    if !ok {
                        return
                    }
                    select {
                    case out <- val:
                    case <-ctx.Done():
                        return
                    }
                case <-ctx.Done():
                    return
                }
            }
        }(ch)
    }
    
    return channels
}
```

### Graceful Shutdown with Context

```go
func main() {
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()
    
    // Handle SIGINT/SIGTERM
    sigCh := make(chan os.Signal, 1)
    signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
    
    go func() {
        <-sigCh
        fmt.Println("Shutting down...")
        cancel() // Cancel ALL goroutines
    }()
    
    // Start workers — they all receive cancellation
    results := make(chan Result)
    var wg sync.WaitGroup
    
    for i := 0; i < 10; i++ {
        wg.Add(1)
        go func(id int) {
            defer wg.Done()
            worker(ctx, id, results)
        }(i)
    }
    
    // Wait for graceful shutdown
    go func() {
        wg.Wait()
        close(results)
    }()
    
    // Process results until cancelled
    for r := range results {
        fmt.Println(r)
    }
}
```

---

## 10. Production Concurrency Patterns

### Worker Pool

```go
// ── Generalized worker pool ─────────────────────────────────
func WorkerPool[T, U any](
    ctx context.Context,
    jobs []T,
    workers int,
    process func(context.Context, T) (U, error),
) ([]U, error) {
    if workers <= 0 {
        workers = runtime.NumCPU()
    }
    if workers > len(jobs) {
        workers = len(jobs)
    }
    
    jobCh := make(chan T, len(jobs))
    resultCh := make(chan struct {
        idx int
        val U
        err error
    }, len(jobs))
    
    // Send all jobs
    for _, job := range jobs {
        jobCh <- job
    }
    close(jobCh)
    
    // Start workers
    var wg sync.WaitGroup
    for i := 0; i < workers; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            for job := range jobCh {
                val, err := process(ctx, job)
                select {
                case resultCh <- struct {
                    idx int
                    val U
                    err error
                }{val: val, err: err}:
                case <-ctx.Done():
                    return
                }
            }
        }()
    }
    
    // Wait for all workers
    go func() {
        wg.Wait()
        close(resultCh)
    }()
    
    // Collect results in order
    results := make([]U, len(jobs))
    for result := range resultCh {
        if result.err != nil {
            return nil, result.err
        }
        results[result.idx] = result.val
    }
    
    return results, nil
}

// Usage:
// results, err := WorkerPool(ctx, urls, 10, fetchURL)
```

### Pipeline Pattern

```go
// ── Stage-based pipeline ────────────────────────────────────
type Pipeline[T, U any] struct {
    stages []StageFunc
}

type StageFunc func(context.Context, <-chan T) <-chan U

func NewPipeline[T, U any](stages ...StageFunc) *Pipeline[T, U] {
    return &Pipeline[T, U]{stages: stages}
}

func (p *Pipeline[T, U]) Run(ctx context.Context, in <-chan T) <-chan U {
    var out any = in
    for _, stage := range p.stages {
        // Type assertion — in practice use generics carefully
        next := stage(ctx, out.(<-chan T))
        out = next
    }
    return out.(<-chan U)
}

// ── Concrete pipeline example ───────────────────────────────
// Stage 1: Generate numbers
func genNumbers(ctx context.Context, nums ...int) <-chan int {
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

// Stage 2: Double
func double(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {
            select {
            case out <- n * 2:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Stage 3: Filter evens
func filterEvens(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {
            if n%2 == 0 {
                select {
                case out <- n:
                case <-ctx.Done():
                    return
                }
            }
        }
    }()
    return out
}

// Usage:
// pipeline := NewPipeline(double, filterEvens)
// results := pipeline.Run(ctx, genNumbers(ctx, 1,2,3,4,5))
```

### Fan-Out / Fan-In

```go
// ── Fan-Out: Distribute work ────────────────────────────────
func fanOut[T any](in <-chan T, n int) []<-chan T {
    channels := make([]<-chan T, n)
    for i := 0; i < n; i++ {
        ch := make(chan T)
        channels[i] = ch
        go func(out chan<- T) {
            defer close(out)
            for v := range in {
                out <- v
            }
        }(ch)
    }
    return channels
}

// ── Fan-In: Merge results ───────────────────────────────────
func fanIn[T any](ctx context.Context, channels ...<-chan T) <-chan T {
    out := make(chan T)
    var wg sync.WaitGroup
    
    for _, ch := range channels {
        wg.Add(1)
        go func(c <-chan T) {
            defer wg.Done()
            for v := range c {
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            }
        }(ch)
    }
    
    go func() {
        wg.Wait()
        close(out)
    }()
    
    return out
}

// ── Full example ────────────────────────────────────────────
func processBatch(ctx context.Context, items []int, workers int) []int {
    // Stage 1: Source
    source := make(chan int, len(items))
    for _, v := range items {
        source <- v
    }
    close(source)
    
    // Stage 2: Fan out to workers
    pipelines := fanOut(source, workers)
    
    // Stage 3: Each worker doubles (could be any processing)
    processed := make([]<-chan int, workers)
    for i, p := range pipelines {
        processed[i] = double(ctx, p)
    }
    
    // Stage 4: Fan in results
    merged := fanIn(ctx, processed...)
    
    // Collect all results
    var results []int
    for v := range merged {
        results = append(results, v)
    }
    return results
}
```

### Tee (Split One Channel)

```go
// ── Split one channel into two ──────────────────────────────
func tee[T any](in <-chan T) (<-chan T, <-chan T) {
    out1 := make(chan T)
    out2 := make(chan T)
    
    go func() {
        defer close(out1)
        defer close(out2)
        
        for val := range in {
            // Must send to both — clone val for second send
            v1, v2 := val, val
            for i := 0; i < 2; i++ {
                select {
                case out1 <- v1:
                    out1 = nil // Disable first case
                case out2 <- v2:
                    out2 = nil // Disable second case
                }
            }
            // Re-enable both
            out1 = make(chan T) // Wait, this creates new channels each iteration
            // NO — this is wrong. Fix below:
        }
    }()
    
    return out1, out2
}

// ── Correct Tee implementation ──────────────────────────────
func teeCorrect[T any](in <-chan T) (<-chan T, <-chan T) {
    out1 := make(chan T)
    out2 := make(chan T)
    
    go func() {
        defer close(out1)
        defer close(out2)
        
        for val := range in {
            // Local variables shadow the channel variables
            // so we can nil them out after each send
            o1, o2 := out1, out2
            for i := 0; i < 2; i++ {
                select {
                case o1 <- val:
                    o1 = nil
                case o2 <- val:
                    o2 = nil
                }
            }
        }
    }()
    
    return out1, out2
}
```

### Circuit Breaker

```go
// ── Channel-based circuit breaker ────────────────────────────
type CircuitBreaker struct {
    mu            sync.Mutex
    state         State
    failures      int
    threshold     int
    resetTimeout  time.Duration
    lastFailure   time.Time
    halfOpenCh    chan struct{}
}

type State int

const (
    StateClosed   State = iota // Normal operation
    StateHalfOpen              // Testing if service recovered
    StateOpen                  // Rejecting requests
)

func (cb *CircuitBreaker) Execute(fn func() error) error {
    if !cb.allowRequest() {
        return ErrCircuitOpen
    }
    
    err := fn()
    cb.recordResult(err)
    return err
}

func (cb *CircuitBreaker) allowRequest() bool {
    cb.mu.Lock()
    defer cb.mu.Unlock()
    
    switch cb.state {
    case StateClosed:
        return true
    case StateOpen:
        if time.Since(cb.lastFailure) > cb.resetTimeout {
            cb.state = StateHalfOpen
            return true
        }
        return false
    case StateHalfOpen:
        return true
    default:
        return false
    }
}

func (cb *CircuitBreaker) recordResult(err error) {
    cb.mu.Lock()
    defer cb.mu.Unlock()
    
    if err == nil {
        if cb.state == StateHalfOpen {
            cb.state = StateClosed
            cb.failures = 0
        }
        return
    }
    
    cb.failures++
    cb.lastFailure = time.Now()
    
    if cb.failures >= cb.threshold {
        cb.state = StateOpen
    }
}
```

### Rate Limiter (Token Bucket)

```go
// ── Token bucket rate limiter using channels ────────────────
type RateLimiter struct {
    tokens chan struct{}
    ticker *time.Ticker
    closeCh chan struct{}
}

func NewRateLimiter(rate int, burst int) *RateLimiter {
    rl := &RateLimiter{
        tokens:  make(chan struct{}, burst),
        ticker:  time.NewTicker(time.Second / time.Duration(rate)),
        closeCh: make(chan struct{}),
    }
    
    // Fill bucket to capacity initially
    for i := 0; i < burst; i++ {
        rl.tokens <- struct{}{}
    }
    
    // Refill tokens
    go func() {
        for {
            select {
            case <-rl.ticker.C:
                select {
                case rl.tokens <- struct{}{}:
                default:
                    // Bucket full, discard
                }
            case <-rl.closeCh:
                rl.ticker.Stop()
                return
            }
        }
    }()
    
    return rl
}

func (rl *RateLimiter) Wait(ctx context.Context) error {
    select {
    case <-rl.tokens:
        return nil
    case <-ctx.Done():
        return ctx.Err()
    }
}

func (rl *RateLimiter) Close() {
    close(rl.closeCh)
}
```

---

## 11. Common Pitfalls & Debugging

### Pitfall Checklist

```go
// 🔴 1. Goroutine leaks (already covered above)
//     → Always have a done/close path for every goroutine

// 🔴 2. Closing a channel twice
//     → Use sync.Once for channels that might be closed by multiple goroutines

// 🔴 3. Sending on a closed channel
//     → Never send after close; use a done channel pattern

// 🔴 4. Forgetting to close channels
//     → Causes receiver goroutines to leak (reading from never-closed channel)

// 🔴 5. Deadlock from lock ordering
//     → Always acquire locks in the same order

// 🔴 6. Calling wg.Add inside the goroutine
//     → Call wg.Add BEFORE go func()

// 🔴 7. Mutex copy (mutexes must not be copied)
//     → Pass mutexes by pointer, not by value
//     type Safe struct { mu sync.Mutex } // OK
//     func (s *Safe) Lock() { s.mu.Lock() } // OK (by pointer)

// 🔴 8. Forgetting to call context cancel
//     → defer cancel() ALWAYS after creating a cancellable context

// 🔴 9. Data race on maps
//     → Maps are NOT thread-safe. Use sync.Map or mutex.

// 🔴 10. Using time.After in a loop (leaks!)
for {
    select {
    case v := <-ch:
        fmt.Println(v)
    case <-time.After(time.Second): // New timer each iteration!
        // → TIMER LEAK: timer not stopped until it fires
    }
}

// ✅ FIX: Use time.NewTicker instead
ticker := time.NewTicker(time.Second)
defer ticker.Stop()
for {
    select {
    case v := <-ch:
        fmt.Println(v)
    case <-ticker.C:
        fmt.Println("timeout")
    }
}
```

### Debugging Tools

```go
// ── 1. Race Detector ─────────────────────────────────────────
// go test -race ./...
// go build -race .
// go run -race main.go
//
// Catches: unsynchronized reads/writes to shared memory
// Cost: 5-10x slower, ~10x memory
// Never run in production!

// ── 2. Goroutine stack dump ─────────────────────────────────
// Send SIGQUIT (Ctrl+\ on Linux) to get ALL goroutine stacks
// Or programmatically:
func dumpGoroutines() {
    buf := make([]byte, 1<<20)
    n := runtime.Stack(buf, true) // true = all goroutines
    fmt.Printf("=== GOROUTINE DUMP ===\n%s\n", buf[:n])
}

// ── 3. GODEBUG environment variables ─────────────────────────
// GODEBUG=gctrace=1    → GC trace
// GODEBUG=schedtrace=1000 → Scheduler trace every 1000ms
// GODEBUG=scheddetail=1   → Detailed scheduler trace

// ── 4. pprof ─────────────────────────────────────────────────
// import _ "net/http/pprof"
// go run main.go
// go tool pprof http://localhost:6060/debug/pprof/goroutine
// go tool pprof http://localhost:6060/debug/pprof/heap
// go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30

// ── 5. Execution tracer ──────────────────────────────────────
// import "runtime/trace"
// f, _ := os.Create("trace.out")
// trace.Start(f)
// defer trace.Stop()
// go tool trace trace.out

// ── 6. Channel debugging with reflect ────────────────────────
func inspectChannel[T any](ch chan T) {
    v := reflect.ValueOf(ch)
    fmt.Printf("Channel type: %v\n", v.Type())
    fmt.Printf("Buffer size: %v\n", v.Cap())
    fmt.Printf("Current length: %v\n", v.Len())
}
```

---

## 12. Concurrency & Parallelism Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the difference between concurrency and parallelism?</b></summary>

**Answer:** Concurrency is about dealing with many things at once (structuring a program as independently executing tasks). Parallelism is about doing many things at once (actually executing on multiple cores). Concurrency enables parallelism but is not required for it. A concurrent program can run on a single core by interleaving tasks, while parallelism requires multiple cores.

In Go: you design with concurrency (goroutines), the runtime and hardware provide parallelism if available.
</details>

<details>
<summary><b>Q2: How do you create a goroutine? What is the minimum stack size?</b></summary>

**Answer:** Use `go f()` or `go func() { ... }()`. A goroutine starts with ~2KB stack (varies by Go version) that grows and shrinks as needed. This is why you can have hundreds of thousands of goroutines — compared to OS threads that start with ~1MB stacks.
</details>

<details>
<summary><b>Q3: What is the difference between buffered and unbuffered channels?</b></summary>

**Answer:** An unbuffered channel (`make(chan T)`) synchronizes the sender and receiver — the send blocks until a receive is ready. A buffered channel (`make(chan T, N)`) allows N sends without blocking — the sender only blocks when the buffer is full. Unbuffered channels guarantee that send and receive happen at the same time, providing stronger synchronization.
</details>

### Intermediate

<details>
<summary><b>Q4: What happens when you send on a closed channel? Receive from a closed channel?</b></summary>

**Answer:** Sending on a closed channel causes a panic. Receiving from a closed channel returns the zero value immediately — use the `value, ok := <-ch` form where `ok` is `false` when the channel is closed and empty. You can use range (`for v := range ch`) to safely read until the channel is closed.
</details>

<details>
<summary><b>Q5: How do you prevent a goroutine leak?</b></summary>

**Answer:**
1. Every goroutine needs a guaranteed exit path — use a `done` channel or `context.Context`
2. Use `select` with context cancellation in every goroutine that does I/O or channel operations
3. Close channels from the sender side to signal no more data
4. Use `sync.WaitGroup` to track goroutine completion
5. For long-running goroutines, always check `ctx.Done()` in the loop
6. Use `defer` for cleanup actions that must run on goroutine exit

Tools: `runtime.NumGoroutine()` to detect leaks, `pprof` goroutine profile to see which goroutines are stuck.
</details>

<details>
<summary><b>Q6: Explain the select statement. How does the runtime choose when multiple cases are ready?</b></summary>

**Answer:** `select` lets a goroutine wait on multiple channel operations. When multiple cases are ready simultaneously, the runtime picks one pseudo-randomly (not round-robin or first-come-first-served). This prevents starvation. The `default` case makes the select non-blocking. A `nil` channel is never chosen, allowing you to dynamically disable cases.
</details>

<details>
<summary><b>Q7: How does Go's scheduler decide which goroutine to run next?</b></summary>

**Answer:** Go uses a GMP scheduler. When a goroutine blocks (channel op, syscall, mutex, or gets preempted after ~10ms), the scheduler runs:
1. Check for GC work
2. Try `runnext` (goroutine priority queue per P)
3. Try local run queue (LRQ) per P
4. Try global run queue (GRQ)
5. Steal work from other P's LRQ (random victim, steal half)
6. Spin, then idle

Work stealing ensures load balancing. The network poller (epoll/kqueue) handles I/O-bound goroutines without blocking OS threads.
</details>

<details>
<summary><b>Q8: When would you use sync.Mutex vs channels in Go?</b></summary>

**Answer:** Guidelines from Go's creators and production experience:
- **Channels:** For passing ownership of data, coordinating goroutines, signaling events. When data flows from producer to consumer.
- **Mutexes:** For protecting shared state, critical sections, updating cached data. When many goroutines access the same data.

Practical rule: Use channels for orchestrating goroutine communication. Use mutexes for protecting data. Many production systems use both.

Go proverb: "Don't communicate by sharing memory; share memory by communicating."
</details>

### Advanced

<details>
<summary><b>Q9: Write a program that detects if a goroutine is stuck (blocked forever).</b></summary>

**Answer:**
```go
func detectStuckGoroutine(timeout time.Duration) {
    initial := runtime.NumGoroutine()
    
    time.Sleep(timeout)
    
    current := runtime.NumGoroutine()
    if current > initial {
        // Goroutines didn't complete — dump stacks
        buf := make([]byte, 1<<20)
        n := runtime.Stack(buf, true)
        fmt.Printf("STUCK GOROUTINES (%d leaked):\n%s\n", 
            current-initial, buf[:n])
    }
}

// Usage in tests:
func TestNoGoroutineLeak(t *testing.T) {
    initial := runtime.NumGoroutine()
    defer func() {
        if runtime.NumGoroutine() != initial {
            t.Error("goroutine leak detected")
        }
    }()
    
    // Run test
}
```
</details>

<details>
<summary><b>Q10: Implement a concurrent, scalable rate limiter that works across multiple goroutines.</b></summary>

**Answer:**
```go
// ── Sliding window rate limiter ─────────────────────────────
type SlidingWindowRateLimiter struct {
    mu       sync.Mutex
    requests map[string]*window
    rate     int
    interval time.Duration
}

type window struct {
    timestamps []time.Time
}

func NewSlidingWindowRateLimiter(rate int, interval time.Duration) *SlidingWindowRateLimiter {
    return &SlidingWindowRateLimiter{
        requests: make(map[string]*window),
        rate:     rate,
        interval: interval,
    }
}

func (rl *SlidingWindowRateLimiter) Allow(key string) bool {
    rl.mu.Lock()
    defer rl.mu.Unlock()
    
    w, exists := rl.requests[key]
    if !exists {
        w = &window{}
        rl.requests[key] = w
    }
    
    now := time.Now()
    cutoff := now.Add(-rl.interval)
    
    // Remove expired timestamps
    i := 0
    for i < len(w.timestamps) && w.timestamps[i].Before(cutoff) {
        i++
    }
    w.timestamps = w.timestamps[i:]
    
    if len(w.timestamps) >= rl.rate {
        return false
    }
    
    w.timestamps = append(w.timestamps, now)
    return true
}

// ── Concurrent usage ────────────────────────────────────────
func main() {
    limiter := NewSlidingWindowRateLimiter(100, time.Second)
    var wg sync.WaitGroup
    
    for i := 0; i < 200; i++ {
        wg.Add(1)
        go func(id int) {
            defer wg.Done()
            if limiter.Allow("user:123") {
                fmt.Printf("Request %d allowed\n", id)
            } else {
                fmt.Printf("Request %d rate limited\n", id)
            }
        }(i)
    }
    
    wg.Wait()
}
```
</details>

<details>
<summary><b>Q11: Explain the "happens-before" guarantees of different channel operations.</b></summary>

**Answer:**

According to the Go Memory Model:
1. **Unbuffered channel:** A send happens before the corresponding receive completes. Conversely, a receive happens before the send completes if the send was the one that synchronized (both are synchronized).

2. **Buffered channel (capacity C):** The kth receive on a channel with capacity C happens before the (k+C)th send completes. This means:
   - The first receive happens before the (1+C)th send
   - This guarantees that the sender sees everything the earlier receiver did

3. **Channel close:** A close happens before any receive that returns a zero value due to the channel being closed.

4. **`sync.Mutex`:** The nth `Unlock()` happens before the (n+1)th `Lock()`.

5. **`sync/atomic`:** All atomic operations are sequentially consistent — all goroutines see the same order of atomic operations.

Practical implication: If goroutine A sends a value on a channel, and goroutine B receives that value, then B sees everything A did before the send (including writes to shared variables).
</details>

<details>
<summary><b>Q12: How do Go 1.14+ signal-based preemption work? What problem did it solve?</b></summary>

**Answer:** Before Go 1.14, Go used cooperative scheduling — goroutines only yielded at function calls. A tight loop like `for { sum++ }` would block the OS thread indefinitely (no function call = no preemption).

Go 1.14+ added signal-based preemption. The `sysmon` thread sends a `SIGURG` signal to the M running a goroutine that has been executing for >10ms without preempting. The signal handler sets a flag, and at the next safe point (any function prologue), the goroutine checks the flag and yields. This ensures that tight loops can be preempted.

Key details:
- Signal is `SIGURG` (unused by most programs) not `SIGALRM`
- Preemption points are at async-safe locations (function entry, loop back edges)
- The GC uses this mechanism to stop-the-world for mark termination
</details>

<details>
<summary><b>Q13: Design an actor-based system using goroutines and channels (no external framework).</b></summary>

**Answer:**
```go
// ── Actor model in Go ───────────────────────────────────────
type ActorID string

type Actor struct {
    id    ActorID
    inbox chan Message
    state map[string]any
    handlers map[string]func(Message) error
}

type Message struct {
    Type    string
    Payload any
    ReplyTo chan Response
}

type Response struct {
    Data any
    Err  error
}

func NewActor(id ActorID) *Actor {
    return &Actor{
        id:       id,
        inbox:    make(chan Message, 100),
        state:    make(map[string]any),
        handlers: make(map[string]func(Message) error),
    }
}

func (a *Actor) Handle(msgType string, handler func(Message) error) {
    a.handlers[msgType] = handler
}

func (a *Actor) Start(ctx context.Context) {
    go func() {
        for {
            select {
            case msg := <-a.inbox:
                handler, ok := a.handlers[msg.Type]
                if !ok {
                    if msg.ReplyTo != nil {
                        msg.ReplyTo <- Response{Err: fmt.Errorf("unknown msg type: %s", msg.Type)}
                    }
                    continue
                }
                
                err := handler(msg)
                if msg.ReplyTo != nil {
                    msg.ReplyTo <- Response{Data: nil, Err: err}
                }
                
            case <-ctx.Done():
                return
            }
        }
    }()
}

func (a *Actor) Tell(msg Message) {
    a.inbox <- msg
}

func (a *Actor) Ask(msg Message) (any, error) {
    msg.ReplyTo = make(chan Response, 1)
    a.inbox <- msg
    resp := <-msg.ReplyTo
    return resp.Data, resp.Err
}

// ── Actor system ────────────────────────────────────────────
type ActorSystem struct {
    actors map[ActorID]*Actor
    mu     sync.RWMutex
}

func NewActorSystem() *ActorSystem {
    return &ActorSystem{
        actors: make(map[ActorID]*Actor),
    }
}

func (as *ActorSystem) Spawn(id ActorID, fn func(*Actor)) *Actor {
    actor := NewActor(id)
    fn(actor)
    as.mu.Lock()
    as.actors[id] = actor
    as.mu.Unlock()
    return actor
}

func (as *ActorSystem) Send(from, to ActorID, msg Message) error {
    as.mu.RLock()
    actor, ok := as.actors[to]
    as.mu.RUnlock()
    if !ok {
        return fmt.Errorf("actor %s not found", to)
    }
    actor.Tell(msg)
    return nil
}

// Usage:
// system := NewActorSystem()
// counter := system.Spawn("counter", func(a *Actor) {
//     a.state["count"] = 0
//     a.Handle("increment", func(msg Message) error {
//         a.state["count"] = a.state["count"].(int) + 1
//         return nil
//     })
//     a.Handle("get", func(msg Message) error {
//         msg.ReplyTo <- Response{Data: a.state["count"]}
//         return nil
//     })
// })
```
</details>

<details>
<summary><b>Q14: What is the difference between CSP (Communicating Sequential Processes) and the Actor model? Where does Go fit?</b></summary>

**Answer:**

| Feature | CSP (Go) | Actor Model (Erlang/Akka) |
|---------|---------|--------------------------|
| Communication | Via channels (anonymous) | Direct messages to named actors |
| Channel/Capacity | Buffered or unbuffered | Mailbox (always bounded) |
| Sender identity | Anonymous (channel doesn't know sender) | Actor knows sender via address |
| Error handling | Propagate via error values | "Let it crash" + supervision |
| State isolation | Shared memory + synchronization | Complete isolation (no shared state) |
| Addressing | No identity — data goes to channel | Actors have addresses |

Go is primarily CSP-inspired (via Hoare's CSP paper), borrowing channel-based communication. However, Go also has shared memory (mutexes, atomics), making it a hybrid. Pure actor systems like Erlang enforce complete isolation — actors never share state and only communicate via messages with actor addresses.
</details>

<details>
<summary><b>Q15: How would you implement a distributed rate limiter using consistent hashing and goroutines?</b></summary>

**Answer:**
```go
// ── Distributed rate limiter shard ──────────────────────────
type Shard struct {
    mu       sync.Mutex
    counters map[string]*tokenBucket
}

type tokenBucket struct {
    tokens    float64
    maxTokens float64
    rate      float64
    lastRefill time.Time
}

func (s *Shard) Allow(key string, rate, burst float64) bool {
    s.mu.Lock()
    defer s.mu.Unlock()
    
    bucket, ok := s.counters[key]
    if !ok {
        bucket = &tokenBucket{
            tokens:    burst,
            maxTokens: burst,
            rate:      rate,
            lastRefill: time.Now(),
        }
        s.counters[key] = bucket
    }
    
    // Refill
    now := time.Now()
    elapsed := now.Sub(bucket.lastRefill).Seconds()
    bucket.tokens = math.Min(bucket.maxTokens, bucket.tokens+elapsed*bucket.rate)
    bucket.lastRefill = now
    
    if bucket.tokens < 1 {
        return false
    }
    bucket.tokens--
    return true
}

// ── Sharded rate limiter ────────────────────────────────────
type DistributedRateLimiter struct {
    shards    []*Shard
    replicas  int // Virtual nodes for consistent hashing
}

func NewDistributedRateLimiter(shardCount, replicas int) *DistributedRateLimiter {
    limiter := &DistributedRateLimiter{
        shards:   make([]*Shard, shardCount),
        replicas: replicas,
    }
    for i := range limiter.shards {
        limiter.shards[i] = &Shard{counters: make(map[string]*tokenBucket)}
    }
    return limiter
}

func (d *DistributedRateLimiter) getShard(key string) *Shard {
    // Consistent hash using FNV
    h := fnv.New64a()
    h.Write([]byte(key))
    hash := h.Sum64()
    return d.shards[hash%uint64(len(d.shards))]
}

func (d *DistributedRateLimiter) Allow(key string, rate, burst float64) bool {
    shard := d.getShard(key)
    return shard.Allow(key, rate, burst)
}
```
</details>

<details>
<summary><b>Q16: How does the Go race detector work under the hood?</b></summary>

**Answer:** The Go race detector uses ThreadSanitizer (TSan), a dynamic analysis tool. It:
1. **Instrumentation:** At compile time, every memory access (read/write) is instrumented with a TSan callback. The compiler adds metadata tracking per-access.
2. **Happens-before graph:** TSan maintains a vector clock for each goroutine and each synchronization event (lock acquire/release, channel send/receive, etc.).
3. **Race detection:** When two goroutines access the same memory location without a happens-before relation, and at least one access is a write, TSan reports a data race.
4. **False positives:** Zero false positives in theory (precise detection). However, it only detects races that occur during execution — so a race exists if you don't trigger it. Run with multiple workloads.
5. **Performance cost:** 5-10x slower, 10x more memory. Never use in production.
6. **Limitations:** Only works for actual runtime races, not compile-time races. Can't detect races in hand-written assembly or cgo code.
</details>

<details>
<summary><b>Q17: Implement a lock-free, concurrent hash map using atomic operations.</b></summary>

**Answer:**
```go
type ConcurrentHashMap[K comparable, V any] struct {
    buckets []atomic.Pointer[bucket[K, V]]
    mask    uint64
}

type bucket[K comparable, V any] struct {
    entries []entry[K, V]
}

type entry[K comparable, V any] struct {
    key   K
    value atomic.Value
}

func NewConcurrentHashMap[K comparable, V any](size int) *ConcurrentHashMap[K, V] {
    // Round to power of 2
    n := 1
    for n < size {
        n <<= 1
    }
    
    m := &ConcurrentHashMap[K, V]{
        buckets: make([]atomic.Pointer[bucket[K, V]], n),
        mask:    uint64(n - 1),
    }
    
    for i := range m.buckets {
        b := &bucket[K, V]{
            entries: make([]entry[K, V], 8), // Initial per-bucket capacity
        }
        m.buckets[i].Store(b)
    }
    
    return m
}

func (m *ConcurrentHashMap[K, V]) hash(key K) uint64 {
    h := fnv.New64a()
    h.Write([]byte(fmt.Sprintf("%v", key)))
    return h.Sum64()
}

func (m *ConcurrentHashMap[K, V]) Load(key K) (V, bool) {
    hash := m.hash(key)
    idx := hash & m.mask
    
    b := m.buckets[idx].Load()
    if b == nil {
        var zero V
        return zero, false
    }
    
    for _, e := range b.entries {
        if e.key == key {
            val, ok := e.value.Load().(V)
            if ok {
                return val, true
            }
            return val, false
        }
    }
    
    var zero V
    return zero, false
}

func (m *ConcurrentHashMap[K, V]) Store(key K, value V) {
    hash := m.hash(key)
    idx := hash & m.mask
    
    // Load bucket
    b := m.buckets[idx].Load()
    
    // Try to update existing
    for i := range b.entries {
        if b.entries[i].key == key {
            b.entries[i].value.Store(value)
            return
        }
    }
    
    // Append new entry
    newEntries := make([]entry[K, V], len(b.entries)+1)
    copy(newEntries, b.entries)
    newEntries[len(b.entries)] = entry[K, V]{
        key:   key,
        value: atomic.Value{},
    }
    newEntries[len(b.entries)].value.Store(value)
    
    newBucket := &bucket[K, V]{entries: newEntries}
    m.buckets[idx].Store(newBucket)
}
```
</details>

---

## 📊 Quick Reference: Go Concurrency at a Glance

| Pattern | Primitive | When to Use |
|---------|-----------|-------------|
| One-to-one | Unbuffered channel | Synchronous handoff |
| N-to-1 | Buffered channel | Decoupled producer/consumer |
| N-to-M | Fan-in, Fan-out | Work distribution |
| Broadcast | `close(ch)` | Signal all waiters |
| Timeout | `time.After` + select | Deadline for single op |
| Cancellation | `context.Context` + select | Graceful shutdown |
| Mutual exclusion | `sync.Mutex` | Protect shared state |
| Reader/Writer | `sync.RWMutex` | Read-heavy workloads |
| Coordination | `sync.WaitGroup` | Wait for goroutines |
| One-time init | `sync.Once` | Lazy initialization |
| Lock-free | `sync/atomic` | High-performance counters |
| Object reuse | `sync.Pool` | Reduce GC pressure |
| Signal/wait | `sync.Cond` | Complex state-dependent logic |

---

> *Use these notes as a practical reference for writing concurrent Go code. The Go mantra: "Do not communicate by sharing memory; instead, share memory by communicating."*
