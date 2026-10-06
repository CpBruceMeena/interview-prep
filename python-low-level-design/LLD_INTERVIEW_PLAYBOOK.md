# 🧭 LLD Interview Playbook (Senior / Staff)

> **Goal:** One page to re-read the night before an LLD / machine-coding round.
> It is language-neutral; Python is the default, with Java and Go shown where the idioms differ.
> Every project linked in [section 11](#11-problem-to-key-concepts-map) has a `THOUGHT_PROCESS.md` that applies this playbook to one problem.

---

## Table of Contents

1. [What the Round Evaluates](#1-what-the-round-evaluates)
2. [The Time-Boxed Script](#2-the-time-boxed-script)
3. [Clarifying Questions Checklist](#3-clarifying-questions-checklist)
4. [Modelling Heuristics](#4-modelling-heuristics)
5. [Pattern Cheat-Sheet](#5-pattern-cheat-sheet)
6. [Concurrency Toolkit](#6-concurrency-toolkit)
7. [Correctness Hot-Spots](#7-correctness-hot-spots)
8. [Testable Code Under Time Pressure](#8-testable-code-under-time-pressure)
9. [Handling Now Extend It](#9-handling-now-extend-it)
10. [Taking an LLD to HLD](#10-taking-an-lld-to-hld)
11. [Problem to Key-Concepts Map](#11-problem-to-key-concepts-map)
12. [Three-Week Practice Plan](#12-three-week-practice-plan)

---

## 🎯 1. What the Round Evaluates

Interviewers score roughly five things. Patterns are the least of them.

| Dimension | What they look for |
|-----------|--------------------|
| **Problem framing** | You narrow scope out loud and write the requirements down before you code. |
| **Modelling** | Classes have one reason to change; behaviour sits next to the data it guards; there are no god classes. |
| **Working code** | It runs. Happy path end-to-end beats a beautiful half-skeleton. |
| **Correctness under stress** | Invariants, invalid transitions, concurrency, money and time are all handled deliberately. |
| **Communication and trade-offs** | You name the alternative you rejected and why. |

### Senior vs Staff: concrete behaviours

| Situation | Senior signal | Staff signal |
|-----------|---------------|--------------|
| Requirements | Asks good clarifying questions. | Also **cuts scope** explicitly ("I'll leave payments behind an interface; we can revisit") and states the invariants the system must never violate. |
| Modelling | Clean entities, sensible interfaces. | Identifies the **one hard part** (e.g. seat contention, matching, state transitions) and spends the time there. Doesn't gold-plate the easy parts. |
| Patterns | Applies the right pattern when prompted. | Explains **why not** a pattern ("Strategy here is one `if`; I'll inline it until a second policy appears"). |
| Concurrency | Adds a lock around the critical section. | Names the race (check-then-act), picks lock granularity, explains lock ordering, and says how the same invariant is enforced once there are N processes (DB constraint, conditional update). |
| Extension | Adds the feature cleanly. | Shows the extension touches **one new class plus one registration line**, and says which future change would break the current design. |
| Testing | Writes a demo `main`. | Writes 3–5 targeted tests, including an invariant test and a concurrency test, with an injected clock. |
| Driving | Responds to prompts. | **Drives the session**: announces the plan and time budget, checks in at milestones, and stays on schedule. |

!!! tip "The single biggest differentiator"
    Staff candidates say what they are **not** doing and why. Silence about scope reads as not having noticed it.

---

## ⏱️ 2. The Time-Boxed Script

The phases are the same for every length; only the budget changes.

| Phase | 45 min | 60 min | 90 min |
|-------|--------|--------|--------|
| Clarify and requirements | 5 | 7 | 10 |
| Core entities and interfaces | 7 | 10 | 15 |
| Happy-path code | 18 | 23 | 30 |
| Edge cases and concurrency | 8 | 10 | 15 |
| Extension | 4 | 6 | 10 |
| Tests and wrap-up | 3 | 4 | 10 |

In a 45-minute round, tests are often only *described*. In a 90-minute round you are expected to have runnable tests.

### What to say out loud, phase by phase

**Clarify (write the answers as a comment block at the top of the file):**

> "Before I code, let me pin the scope. I'll list functional requirements, then a few non-functional ones: concurrency, persistence, scale. I'll write them down so we agree on what done means."

**Entities and interfaces:**

> "The nouns are X, Y, Z. The invariant I care most about is *a seat is never sold twice*. I'll make `BookingService` the only place that mutates seat state, so the invariant has one owner."

**Happy path:**

> "I'm going to get one end-to-end flow working first: create, book, pay. I'll stub the payment gateway behind an interface and keep everything in memory, with repositories so we can swap in storage later."

**Edge cases and concurrency:**

> "Now the failure modes: invalid transitions, double submit, two users racing for the same seat. Here's the check-then-act race, and here's where the lock goes and why it's per show, not global."

**Extension:**

> "To add surge pricing, I add a new `PricingStrategy` and register it. Nothing in `BookingService` changes. If instead you asked for multi-currency, that *would* ripple, because `Money` is currently single-currency, so I'd change that first."

**Tests:**

> "Three tests: the happy path, the invariant under 50 concurrent threads, and an invalid state transition. The clock is injected, so the expiry test doesn't sleep."

!!! warning "Checkpoints"
    At the end of each phase, say "That's the model; anything you'd like me to change before I code?" One sentence buys alignment and stops you from building the wrong thing for 20 minutes.

---

## ❓ 3. Clarifying Questions Checklist

Pick 5–8, not all of them. Prefer questions whose answer **changes the design**.

| Area | Questions | What the answer changes |
|------|-----------|-------------------------|
| **Functional** | Who are the actors? What are the 3 core use cases? Which ones are out of scope? | Entity list, service API |
| | What are the lifecycle states of the main entity? Can it be cancelled or refunded? | State machine |
| | Are rules configurable (pricing, eviction, matching)? | Strategy vs hard-coded |
| **Scale** | One instance or many? Rough counts (spots, users, orders per second)? | Data structures, indexing, lock granularity |
| | Which queries are hot? ("find available X" vs "history of Y") | Which indexes or maps you keep |
| **Concurrency** | Can two actors contend for the same resource? | Locks, holds, conditional updates |
| | Is this multi-threaded in-process, or multi-node? | In-memory lock vs DB constraint vs distributed lock |
| **Persistence** | In-memory OK for the interview? Must state survive restart? | Repository interface, event log |
| **Failure** | What if payment fails or times out mid-booking? Retries? Duplicate requests? | Holds with TTL, idempotency keys, compensation |
| | What happens to in-flight work on crash? | At-least-once semantics, recovery path |
| **Time / money** | Time zones? Currency? Rounding rules? | `Clock`, `Money`, half-open intervals |

!!! tip "Default if they say 'you decide'"
    State an assumption and move on: "I'll assume a single process, in-memory, thread-safe, and I'll call out what changes for multi-node at the end."

---

## 🧱 4. Modelling Heuristics

### Entities vs value objects

| | Entity | Value object |
|--|--------|--------------|
| Identity | Has an ID; equal if same ID | No ID; equal if all fields are equal |
| Mutability | Mutable lifecycle (state changes) | Immutable |
| Examples | `Booking`, `Account`, `Vehicle` | `Money`, `TimeRange`, `Address`, `Coordinate` |
| Python | `@dataclass(eq=False)` or a regular class | `@dataclass(frozen=True)` |
| Java | class with `equals` on id | `record` |
| Go | struct with pointer receivers | small struct passed by value |

Value objects are where validation lives: a `TimeRange` that cannot be constructed with `end <= start` removes a whole class of bugs.

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end
```

### Where behaviour lives

- **Tell, don't ask.** `account.withdraw(amount)` rather than `if account.balance >= amt: account.balance -= amt` in a service.
- **Invariants live with the data.** A `Seat` (or the `Show` owning seats) enforces "no double booking", not the controller.
- **Services orchestrate across aggregates** (booking + payment + notification) and own transactions and locks. They should be thin.
- **Smell:** a `Manager` class with 20 methods and entities that are bags of getters. That's an anaemic model; push behaviour down.

### Composition over inheritance

Use inheritance only for a real *is-a* with **shared invariants** and a stable hierarchy (chess `Piece` subclasses are the canonical OK case). Use composition when behaviour varies independently along more than one axis.

> Vehicle × fuel type × pricing → inheritance would give `ElectricTruckWithSurge`. Compose instead: `Vehicle(size, fuel)` plus an injected `PricingStrategy`.

### Enums vs polymorphism

| Use an enum when… | Use polymorphism when… |
|-------------------|------------------------|
| Variants differ only in **data** (size, rate, label). | Variants differ in **behaviour** (move rules, pricing algorithm). |
| The set is closed and small. | New variants are expected (the "now extend it" axis). |
| Logic is a lookup: `RATE[spot_type]`. | You'd otherwise write the same `match` in 3+ places. |

One `match`/`switch` on an enum is fine. The **same** switch duplicated across the codebase is the signal to make it polymorphic.

### State machines: use an explicit transition table

Most LLD problems have a lifecycle (order, booking, ride, elevator, vending machine, ATM session). Make it data, not scattered `if`s.

```python
from enum import Enum, auto

class OrderStatus(Enum):
    CREATED = auto()
    PAID = auto()
    SHIPPED = auto()
    DELIVERED = auto()
    CANCELLED = auto()

TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED:   {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID:      {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED:   {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}

class InvalidTransition(Exception):
    pass

class Order:
    def __init__(self, order_id: str):
        self.id = order_id
        self.status = OrderStatus.CREATED

    def transition_to(self, new: OrderStatus) -> None:
        if new not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status.name} -> {new.name}")
        self.status = new
```

**Table vs State pattern:** use the table when states differ only in *which transitions are allowed*. Use the State pattern (one class per state) when each state handles the **same events differently** (vending machine: `insert_coin` means different things in `Idle`, `HasMoney`, `Dispensing`).

### When NOT to apply a pattern

- **One implementation, no second in sight:** no interface, no factory. Write the concrete class and say "this is the seam if we need a second one".
- **Strategy for a single `if`:** inline it.
- **Builder for a 3-field object:** use keyword arguments or a dataclass with defaults.
- **Observer when there is exactly one listener and ordering matters:** call it directly.
- **Singleton anywhere:** inject the instance instead (see below).
- **Abstract base class per noun "for flexibility":** that's speculative generality, and interviewers mark it down.

---

## 🧩 5. Pattern Cheat-Sheet

| Problem signal | Pattern |
|----------------|---------|
| "Pricing / eviction / matching / split rule can vary" | **Strategy** |
| Same event behaves differently per lifecycle phase | **State** |
| "Notify X, Y, Z when something happens"; fan-out | **Observer** |
| Create one of many types from input (`"car"`, `"bike"`) | **Factory** |
| Object with many optional parameters and validation | **Builder** |
| Add logging / caching / retry / metrics around an interface | **Decorator** |
| Sequential validation / approval / fraud checks; any step may stop | **Chain of Responsibility** |
| Undo/redo, queue or schedule operations, audit log | **Command** |
| Separate domain from storage; swap in-memory for DB | **Repository** |
| Simple entry point over several subsystems | **Facade** |
| Fixed algorithm skeleton, varying steps | **Template Method** |
| "There's only one X" | **Singleton**: usually avoid |

**Strategy**: pluggable algorithm behind one interface.

```python
class PricingStrategy(Protocol):
    def price(self, minutes: int) -> int: ...      # minor units

class HourlyPricing:
    def __init__(self, rate: int): self.rate = rate
    def price(self, minutes: int) -> int: return -(-minutes // 60) * self.rate  # ceil
```

**State**: each state class handles the same events differently.

```python
class Idle:
    def insert_coin(self, m: "Machine", amt: int): m.balance += amt; m.state = HasMoney()
    def dispense(self, m: "Machine"): raise InvalidTransition("insert money first")

class HasMoney:
    def insert_coin(self, m: "Machine", amt: int): m.balance += amt
    def dispense(self, m: "Machine"): m.release_item(); m.state = Idle()
```

**Observer**: publisher knows only the listener interface.

```python
class EventBus:
    def __init__(self): self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
    def subscribe(self, topic: str, fn: Callable[[dict], None]): self._subs[topic].append(fn)
    def publish(self, topic: str, event: dict):
        for fn in list(self._subs[topic]): fn(event)   # copy: subscribers may unsubscribe
```

**Factory**: a registry beats a growing `if/elif`.

```python
VEHICLES: dict[str, type[Vehicle]] = {"car": Car, "bike": Bike, "truck": Truck}

def make_vehicle(kind: str, plate: str) -> Vehicle:
    try: return VEHICLES[kind](plate)
    except KeyError: raise ValueError(f"unknown vehicle {kind!r}") from None
```

**Builder**: earns its place in Java/Go (no keyword args). In Python, a dataclass with defaults usually suffices.

```java
Pizza p = new Pizza.Builder("large")
    .cheese(true).topping("olive").topping("onion")
    .build();   // build() validates and returns an immutable Pizza
```

**Decorator**: same interface, wraps behaviour.

```python
class RetryingGateway:
    def __init__(self, inner: PaymentGateway, attempts: int = 3): self.inner, self.attempts = inner, attempts
    def charge(self, req: ChargeRequest) -> ChargeResult:
        for i in range(self.attempts):
            try: return self.inner.charge(req)      # req carries an idempotency key
            except TransientError:
                if i == self.attempts - 1: raise
```

**Chain of Responsibility**: ordered handlers, each may reject.

```python
class Check(Protocol):
    def check(self, txn: Txn) -> None: ...          # raises Rejected

def run_checks(txn: Txn, checks: list[Check]) -> None:
    for c in checks: c.check(txn)                   # [Limit(), Velocity(), Blacklist()]
```

**Command**: operation as an object; enables undo, queues, audit.

```python
class Command(Protocol):
    def execute(self) -> None: ...
    def undo(self) -> None: ...

class Editor:
    def __init__(self): self.history: list[Command] = []
    def run(self, cmd: Command): cmd.execute(); self.history.append(cmd)
    def undo(self): self.history.pop().undo()
```

**Repository**: collection-like interface over storage.

```python
class BookingRepo(Protocol):
    def get(self, booking_id: str) -> Booking | None: ...
    def save(self, booking: Booking) -> None: ...

class InMemoryBookingRepo:
    def __init__(self): self._rows: dict[str, Booking] = {}
    def get(self, booking_id): return self._rows.get(booking_id)
    def save(self, booking): self._rows[booking.id] = booking
```

**Facade**: one entry point for clients; keeps the demo and tests short.

```python
class ParkingLot:
    def __init__(self, allocator, pricing, tickets): self.a, self.p, self.t = allocator, pricing, tickets
    def park(self, v: Vehicle) -> Ticket: return self.t.issue(v, self.a.allocate(v))
    def leave(self, ticket_id: str) -> int:
        t = self.t.close(ticket_id); self.a.release(t.spot); return self.p.price(t.minutes)
```

**Template Method**: base class fixes the order, subclasses fill steps. Prefer Strategy if the steps vary independently.

```python
class Exporter(ABC):
    def export(self, rows) -> str:                # the template: fixed order
        return self.header() + self.body(rows) + self.footer()
    @abstractmethod
    def header(self) -> str: ...
    @abstractmethod
    def body(self, rows) -> str: ...
    def footer(self) -> str: return ""            # hook with a default
```

**Singleton, and why to avoid it.** It is global mutable state: it hides dependencies, makes tests order-dependent, and is a concurrency hazard during lazy init. Say: "There is one `ParkingLot` per process, but I construct it in `main` and inject it. The *composition root* guarantees one instance, not the class." If you are forced to show one: in Python a module is already a singleton (or put `@functools.cache` on a factory function); in Java and Go:

=== "Java"

    ```java
    public enum Registry {          // enum singleton: thread-safe, serialization-safe
        INSTANCE;
        private final Map<String, Service> services = new ConcurrentHashMap<>();
    }
    ```

=== "Go"

    ```go
    var (
        once     sync.Once
        instance *Registry
    )

    func Get() *Registry {
        once.Do(func() { instance = &Registry{} })
        return instance
    }
    ```

(Python snippets above elide imports: `from typing import Protocol, Callable`, `from collections import defaultdict`, `from abc import ABC, abstractmethod`.)

---

## 🔒 6. Concurrency Toolkit

### The race you will always be asked about: check-then-act

```python
# BROKEN: two threads both see AVAILABLE, both book.
if seat.status == SeatStatus.AVAILABLE:
    seat.status = SeatStatus.BOOKED
```

The check and the act must be **one atomic step**: hold a lock across both, or use a primitive that does both (CAS, conditional `UPDATE … WHERE status = 'AVAILABLE'`, `putIfAbsent`, unique constraint).

!!! warning "The GIL does not save you"
    CPython's GIL guarantees only that one thread executes bytecode at a time. A thread can be switched out **between** bytecodes, so `count += 1` (load, add, store), `if k not in d: d[k] = v`, and every check-then-act are **not atomic**. Single built-in operations such as `d[k] = v`, `list.append` or `dict.setdefault` happen to be atomic under the GIL, but that is a CPython implementation detail. **Free-threaded CPython** (PEP 703: the optional `python3.13t` build, experimental in 3.13 and officially supported but still optional from 3.14) removes the GIL. Built-in containers keep internal per-object locks so they don't corrupt, but compound operations are just as racy as in Java. Write code that is correct **without** a GIL: lock every compound operation on shared state.

### Lock scope

- **Hold locks for the shortest critical section** that covers the invariant. Never do I/O (payment calls, HTTP, sleeps) while holding a lock.
- **Lock granularity:** global lock (simple, serialises everything) → per-aggregate lock (per show, per account) → per-row/striped. Start with per-aggregate and say why.
- **Pattern for slow external calls:** *reserve under lock → call outside lock → confirm or release under lock*. This is the "seat hold with TTL" pattern.

### Lock ordering (deadlock avoidance)

Transferring between two accounts needs two locks. Thread A locks `a` then `b`, thread B locks `b` then `a`, and you have a deadlock. Fix: **acquire in a global order** (e.g. by ID).

=== "Python"

    ```python
    def transfer(src: Account, dst: Account, amount: int) -> None:
        if src.id == dst.id:
            raise ValueError("same account")
        first, second = sorted((src, dst), key=lambda a: a.id)
        with first.lock, second.lock:
            if src.balance < amount:
                raise InsufficientFunds(src.id)
            src.balance -= amount
            dst.balance += amount
    ```

=== "Java"

    ```java
    void transfer(Account src, Account dst, long amount) {
        Account first = src.id() < dst.id() ? src : dst;
        Account second = first == src ? dst : src;
        synchronized (first) {
            synchronized (second) {
                if (src.balance < amount) throw new InsufficientFundsException(src.id());
                src.balance -= amount;
                dst.balance += amount;
            }
        }
    }
    ```

=== "Go"

    ```go
    func Transfer(src, dst *Account, amount int64) error {
        if src.ID == dst.ID {
            return errors.New("same account")
        }
        first, second := src, dst
        if dst.ID < src.ID {
            first, second = dst, src
        }
        first.mu.Lock()
        defer first.mu.Unlock()
        second.mu.Lock()
        defer second.mu.Unlock()
        if src.Balance < amount {
            return ErrInsufficientFunds
        }
        src.Balance -= amount
        dst.Balance += amount
        return nil
    }
    ```

Other deadlock tools: `tryLock` with a timeout plus back-off, or a single coarser lock when contention is low.

### Optimistic vs pessimistic locking

| | Pessimistic | Optimistic |
|--|-------------|------------|
| Idea | Lock first, then read and modify | Read a version, modify, commit only if the version is unchanged; retry on conflict |
| Best when | Contention is high (hot seat, hot SKU) | Contention is low; reads dominate |
| In memory | `Lock` / `synchronized` / `Mutex` | CAS (`AtomicReference.compareAndSet`, `atomic.CompareAndSwapInt64`), or a version check under a short lock |
| In the DB | `SELECT … FOR UPDATE` inside a transaction | `version` column + conditional `UPDATE` |

```sql
-- Pessimistic: row lock held until COMMIT
BEGIN;
SELECT balance FROM accounts WHERE id = :id FOR UPDATE;
UPDATE accounts SET balance = balance - :amt WHERE id = :id;
COMMIT;

-- Optimistic: affected-rows = 0 means someone else won; reload and retry
UPDATE accounts
SET balance = :new_balance, version = version + 1
WHERE id = :id AND version = :read_version;

-- Conditional update: check-then-act in one statement
UPDATE seats SET status = 'HELD', hold_id = :hold, held_until = :expiry
WHERE show_id = :show AND seat_id = :seat AND status = 'AVAILABLE';

-- Unique constraint: the database enforces the invariant for you
CREATE UNIQUE INDEX one_booking_per_seat ON bookings (show_id, seat_id);
-- INSERT; catch the unique-violation error and return "seat taken"
```

!!! tip "Say this in a booking problem"
    "In memory I use a per-show lock. Once this is a service with N instances, the in-process lock is useless, so the invariant moves to the database: a conditional `UPDATE … WHERE status = 'AVAILABLE'` or a unique index on `(show_id, seat_id)`. The lock becomes an optimisation, not the guarantee."

### Producer-consumer with a bounded queue

Bound the queue so producers block (back-pressure) instead of exhausting memory.

=== "Python"

    ```python
    import queue
    import threading

    jobs: queue.Queue = queue.Queue(maxsize=100)   # put() blocks when full
    STOP = object()

    def worker() -> None:
        while True:
            job = jobs.get()
            try:
                if job is STOP:
                    return
                job.run()
            finally:
                jobs.task_done()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    # producers: jobs.put(job) or jobs.put(job, timeout=1.0), which raises queue.Full
    for _ in threads:
        jobs.put(STOP)
    for t in threads:
        t.join()
    ```

=== "Go"

    ```go
    jobs := make(chan Job, 100) // buffered channel = bounded queue
    var wg sync.WaitGroup
    for i := 0; i < 4; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            for job := range jobs { // exits when jobs is closed and drained
                job.Run()
            }
        }()
    }
    // producers: jobs <- job (blocks when full)
    close(jobs)
    wg.Wait()
    ```

Java: `ArrayBlockingQueue<>(100)` with `put`/`take` (or `offer`/`poll` with a timeout), consumed by an `ExecutorService` and stopped with a poison-pill object.

### Read-write locks, striping, atomics

- **Read-write lock:** many readers or one writer. Worth it only when reads vastly outnumber writes **and** the critical section is non-trivial; otherwise a plain mutex is faster. Python's stdlib has **no** RW lock (build one from `Condition`, or just use `Lock`). Note that an LRU `get` mutates recency order, so it is a *write* and an RW lock doesn't help.
- **Lock striping:** `locks[hash(key) % N]` gives N independent locks without one lock per key. `ConcurrentHashMap` historically used this idea. Good for per-user rate limiters and per-key caches.
- **Atomic counters / CAS:** `AtomicLong.incrementAndGet()`, `atomic.Int64.Add`. A CAS loop is `read → compute → compareAndSet(old, new)`, retried on failure. Python has no user-level CAS; use a `Lock` (or `itertools.count` for IDs, accepting that its atomicity is also a CPython detail).

### Idempotency keys

Clients retry. Without idempotency, a retry after a timeout double-charges.

```python
class PaymentService:
    def __init__(self, gateway: PaymentGateway):
        self._gateway = gateway
        self._lock = threading.Lock()
        self._results: dict[str, ChargeResult] = {}
        self._in_flight: set[str] = set()

    def charge(self, idem_key: str, req: ChargeRequest) -> ChargeResult:
        with self._lock:
            if idem_key in self._results:
                return self._results[idem_key]            # replay the stored result
            if idem_key in self._in_flight:
                raise RequestInProgress(idem_key)         # or wait on a Condition
            self._in_flight.add(idem_key)
        try:
            result = self._gateway.charge(req)            # slow I/O outside the lock
        except Exception:
            with self._lock:
                self._in_flight.discard(idem_key)         # let the client retry
            raise
        with self._lock:
            self._in_flight.discard(idem_key)
            self._results[idem_key] = result
        return result
```

In a service, the same thing is a table with `idempotency_key` as **primary key**: insert `IN_PROGRESS` first (the unique key arbitrates concurrent duplicates), then update with the response. Also store a hash of the request body and reject the same key with a different body.

### Timeouts

Every blocking call needs a bound, or one stuck dependency freezes every thread.

| | Python | Java | Go |
|--|--------|------|----|
| Lock | `lock.acquire(timeout=1.0)` returns `False` | `lock.tryLock(1, SECONDS)` | no timed `Lock`; use a channel or `TryLock` |
| Queue | `q.get(timeout=1.0)` raises `queue.Empty` | `q.poll(1, SECONDS)` returns `null` | `select { case j := <-ch: … case <-time.After(d): … }` |
| Future | `fut.result(timeout=1.0)` raises `TimeoutError` | `cf.get(1, SECONDS)`, `cf.orTimeout(…)` | `ctx, cancel := context.WithTimeout(ctx, d)` |

### Primitives side by side

| Need | Python | Java | Go |
|------|--------|------|----|
| Mutual exclusion | `threading.Lock` | `synchronized`, `ReentrantLock` | `sync.Mutex` |
| Re-entrant lock | `threading.RLock` | `ReentrantLock` (and `synchronized` is re-entrant) | none (by design: restructure) |
| Read-write lock | none in stdlib | `ReentrantReadWriteLock`, `StampedLock` | `sync.RWMutex` |
| Wait for a condition | `threading.Condition` | `Condition` from `lock.newCondition()`, `wait/notify` | `sync.Cond` (channels usually better) |
| Limit concurrency | `threading.Semaphore` / `BoundedSemaphore` | `Semaphore` | buffered channel as semaphore, `x/sync/semaphore` |
| Bounded queue | `queue.Queue(maxsize=n)` | `ArrayBlockingQueue`, `LinkedBlockingQueue(n)` | `make(chan T, n)` |
| Thread-safe map | dict + `Lock` | `ConcurrentHashMap` (`computeIfAbsent`, `merge`) | map + `Mutex`, `sync.Map` (append-mostly) |
| Atomic counter / CAS | `Lock` around `+=` | `AtomicLong`, `LongAdder`, `AtomicReference.compareAndSet` | `atomic.Int64`, `atomic.CompareAndSwapInt64` |
| Thread pool | `concurrent.futures.ThreadPoolExecutor` | `ExecutorService`, virtual threads (21+) | goroutines + `WaitGroup` / `errgroup` |
| Async result | `concurrent.futures.Future` | `CompletableFuture` | channel, `errgroup.Group` |
| Wait for N tasks | `Thread.join`, `wait(futures)`, `Barrier` | `CountDownLatch`, `CyclicBarrier`, `invokeAll` | `sync.WaitGroup` |
| One-time init | `functools.cache`, module import | holder class, `enum` singleton | `sync.Once` |
| Cancellation / deadline | `threading.Event`, timeouts | `Future.cancel`, interrupts | `context.Context` |

!!! note "Go idiom"
    "Don't communicate by sharing memory; share memory by communicating." For a single owner of state (an order book, a scheduler), a goroutine that owns the data and receives commands over a channel removes locks entirely. Mention it; it's a strong signal in Go rounds.

---

## 💰 7. Correctness Hot-Spots

### Money

- **Never float.** `0.1 + 0.2 != 0.3`. Use integer minor units (`int` cents, `long` in Java, `int64` in Go) or a decimal type.
- **Python:** `Decimal("19.99")` from a **string**. `Decimal(19.99)` captures the float error. Round explicitly: `amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)`.
- **Java:** `BigDecimal`; compare with `compareTo`, **not** `equals` (`new BigDecimal("2.0").equals(new BigDecimal("2.00"))` is `false`).
- **Go:** no stdlib decimal; use `int64` minor units (or `shopspring/decimal`).
- **Splitting** (Splitwise, refunds): distribute the remainder so the parts sum to the total.

```python
def split(total_cents: int, n: int) -> list[int]:
    base, rem = divmod(total_cents, n)
    return [base + 1 if i < rem else base for i in range(n)]   # split(1000, 3) -> [334, 333, 333]
```

- Model `Money(amount_minor: int, currency: str)` as a value object; adding different currencies raises.

### Time and time zones

- Store and compute in **UTC**, using timezone-aware datetimes; convert to local only for display. Python: `datetime.now(timezone.utc)` (`datetime.utcnow()` returns a naive datetime and is deprecated since 3.12). Java: `Instant`; `ZonedDateTime` for display. Go: `time.Time` and `.UTC()`.
- Use a **monotonic clock for durations and timeouts** (`time.monotonic()`, `System.nanoTime()`; Go's `time.Now()` carries a monotonic reading that `Sub` uses). Wall clocks jump.
- **Inject the clock.** Any code that calls `now()` directly is untestable for expiry, TTLs, late fees and surge windows.

```python
class Clock(Protocol):
    def now(self) -> datetime: ...

class SystemClock:
    def now(self) -> datetime: return datetime.now(timezone.utc)

class FakeClock:
    def __init__(self, start: datetime): self._t = start
    def now(self) -> datetime: return self._t
    def advance(self, **kw) -> None: self._t += timedelta(**kw)
```

### IDs

- `uuid4()` / `UUID.randomUUID()` / `github.com/google/uuid` for opaque IDs. Prefer **UUIDv7 / ULID** when you want time ordering (Python 3.14+ has `uuid.uuid7()`).
- Sequential counters: thread-safe only behind a lock or an `AtomicLong`. In a service they leak volume and need coordination.
- Inject an `IdGenerator` when tests need predictable IDs.

### Overlapping intervals

Use **half-open** intervals `[start, end)`: a booking ending at 10:00 doesn't conflict with one starting at 10:00.

```python
def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end
```

Don't enumerate the four overlap cases; this one expression covers them all. For many intervals per resource, keep them sorted and binary-search the neighbours (`bisect`, `TreeMap.floorEntry` / `ceilingEntry`) to get O(log n) checks.

### Float comparison

- Never `==` on floats. Use `math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)`: `rel_tol` alone fails near zero.
- Distances / ratings / geo are fine as floats; money and counts are not.
- Prefer comparing squared distances to avoid `sqrt` when ranking nearest drivers.

---

## 🧪 8. Testable Code Under Time Pressure

### Design for it from minute one

1. **Constructor injection** of every collaborator with side effects: `Clock`, `IdGenerator`, `random.Random`, `PaymentGateway`, `Notifier`, repositories.
2. **Fakes over mocks.** A 5-line `InMemoryRepo` or `FakeGateway(fail_next=True)` is clearer than mock assertions and doubles as your demo wiring.
3. **Deterministic RNG:** pass `random.Random(seed)` (Java `new Random(seed)`, Go `rand.New(rand.NewSource(seed))`) into dice, shuffles, load balancers.
4. **Pure core, thin shell:** pricing, matching and validation as pure functions or strategies; the service just wires them.

### The 3–5 tests to write first

| # | Test | Why |
|---|------|-----|
| 1 | **Happy path** end to end through the facade | Proves the design runs. |
| 2 | **Core invariant under concurrency** (N threads, one resource → exactly one winner) | The test interviewers remember. |
| 3 | **Invalid transition / rule violation** raises (pay twice, cancel after delivery) | Shows the state machine is enforced. |
| 4 | **Time-dependent behaviour** with `FakeClock` (hold expiry, late fee, token refill) | Shows injection paid off; no `sleep`. |
| 5 | **Boundary** (exactly full, zero balance, back-to-back intervals) | Off-by-one is the most common bug. |

```python
import threading

def test_only_one_thread_books_a_seat():
    svc = BookingService(repo=InMemoryRepo(), clock=FakeClock(T0))
    n = 50
    barrier = threading.Barrier(n)
    wins: list[str] = []
    wins_lock = threading.Lock()

    def attempt(user: str) -> None:
        barrier.wait()                       # start all threads together
        try:
            svc.book(show_id="s1", seat_id="A1", user_id=user)
        except SeatUnavailable:
            return
        with wins_lock:
            wins.append(user)

    threads = [threading.Thread(target=attempt, args=(f"u{i}",)) for i in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(wins) == 1
```

A concurrency test that passes once proves little. Run it in a loop, and say so. Java: `ExecutorService` + `CountDownLatch`; Go: goroutines + `WaitGroup` and **`go test -race`**.

---

## 🧩 9. Handling Now Extend It

The follow-up is the real test of your design. Process:

1. **Restate** the requirement and ask one clarifying question.
2. **Locate the axis of change.** Is it a new *variant* of something that already varies (cheap), or a new *dimension* (needs a new seam)?
3. **Show the diff is additive:** a new class plus registration. If an existing class must change, say why, and change the abstraction once rather than adding a special case.
4. **Name the remaining risk** ("if we also need X, this map becomes a rules engine").

Open/Closed in practice means the **core flow is closed and the variation points are open**. You cannot be open to every change; choose the axes the clarifying questions surfaced.

### Example A: parking lot, "add EV charging spots with a per-kWh charge"

- Spot compatibility was a `SpotType` enum with a `fits(vehicle)` table: add `EV` and one row.
- Pricing was a `PricingStrategy`: add a `CompositePricing([HourlyPricing(...), EnergyPricing(per_kwh)])` that sums its parts.
- `ParkingLot.park/leave` is unchanged. **Risk:** if charging becomes a separately billed session, it's a new entity (`ChargingSession`), not a pricing tweak.

```python
class CompositePricing:
    def __init__(self, parts: list[PricingStrategy]): self.parts = parts
    def price(self, ticket: Ticket) -> int: return sum(p.price(ticket) for p in self.parts)
```

### Example B: notifications, "add WhatsApp, and fall back to SMS if it fails"

- Channels sit behind a `Channel` interface in a registry keyed by `ChannelType`: adding WhatsApp is one class plus one registry line.
- Fallback is a **new dimension** (ordering and failure policy). Add a `FallbackChannel([whatsapp, sms])` decorator/composite that tries each in order. The dispatcher doesn't change.
- **Risk:** retries plus fallback can double-send. Carry a `notification_id` so providers (or your log) can dedupe.

### Example C: booking, "seats are held for 10 minutes during payment"

- A new **state** (`HELD`) and two transitions (`AVAILABLE → HELD`, `HELD → BOOKED | AVAILABLE`) are added to the transition table.
- Expiry uses the injected `Clock`: either lazy (treat `HELD` with `held_until < now` as available on read) or a sweeper thread. **Lazy is simpler and race-free**; say so.
- **Risk:** payment succeeds after the hold expired. Confirm with a conditional transition (`HELD by this hold_id → BOOKED`); on failure, refund automatically.

---

## 🌐 10. Taking an LLD to HLD

A common Staff probe: "How would this work as a service with 10 instances?" What changes:

| Concern | LLD (in-process) | Service |
|---------|------------------|---------|
| **State** | dicts behind repositories | DB tables behind the **same** repository interface (this is why you drew the seam) |
| **Invariants** | locks | DB constraints, conditional updates, `SELECT … FOR UPDATE`, or a single-writer partition |
| **Concurrency** | threads in one process | multiple instances; in-memory locks are per-instance and therefore useless for cross-instance invariants |
| **Idempotency** | dict of results | idempotency-key table; at-least-once delivery everywhere |
| **Events** | in-process Observer | transactional outbox → message broker (Kafka/SQS); consumers must be idempotent |
| **Scaling** | n/a | stateless API tier behind a load balancer; partition stateful parts by key (show_id, account_id, symbol) |
| **Consistency** | trivially strong | strong within one partition/transaction; eventual across services (sagas with compensations instead of distributed transactions) |
| **Time** | one clock | many clocks: don't order events by wall time across nodes; use DB sequence, log offset or version |
| **Failure** | exceptions | timeouts, retries with back-off and jitter, circuit breakers, dead-letter queues |

**Rule of thumb to say out loud:** "Single-writer per key removes most coordination. Partition by the key the invariant is about (one show's seats, one symbol's order book) and the in-memory design inside a partition stays almost unchanged."

Distributed locks (Redis `SET NX PX`, ZooKeeper): mention them, then note that a lock with a lease can expire while the holder is paused, so correctness still needs **fencing tokens** or a DB-level check. The DB constraint is the real guarantee.

---

## 🗺️ 11. Problem to Key-Concepts Map

### Python (`python-low-level-design/`)

| Problem | Key concepts | The one hard part |
|---------|--------------|-------------------|
| [Parking Lot](parking-lot/THOUGHT_PROCESS.md) | Spot allocation strategy, pricing strategy, Facade | Spot fit rules and concurrent allocation |
| [Chess Game](chess-game/THOUGHT_PROCESS.md) | Polymorphic pieces, move validation, Command/Memento for undo | Check / checkmate detection without simulating side effects |
| [Tic-Tac-Toe](tic-tac-toe/THOUGHT_PROCESS.md) | O(1) win detection with row/col/diagonal counters, player strategy | N×N generalisation |
| [Snakes and Ladders](snakes-and-ladders/THOUGHT_PROCESS.md) | Injectable dice (seeded RNG), board as a jump map | Deterministic tests |
| [Vending Machine](vending-machine/THOUGHT_PROCESS.md) | State pattern, change-making | Invalid events per state |
| [LRU Cache](lru-cache/THOUGHT_PROCESS.md) | Hash map + doubly linked list, eviction strategy, TTL | O(1) ops and thread safety (get is a write) |
| [Rate Limiter](rate-limiter/THOUGHT_PROCESS.md) | Token bucket vs sliding window, injected clock, striping | Atomic refill-and-consume per key |
| [Pub-Sub System](pub-sub-system/THOUGHT_PROCESS.md) | Observer, topics, offsets, delivery semantics | Slow consumers and back-pressure |
| [Movie Ticket Booking](movie-ticket-booking/THOUGHT_PROCESS.md) | Seat holds with TTL, state machine, per-show locks | No double booking |
| [Splitwise](splitwise-expense-sharing/THOUGHT_PROCESS.md) | Split strategies, integer money, debt simplification | Rounding remainders, min cash flow |
| [Cab Booking (Uber)](cab-booking-uber/THOUGHT_PROCESS.md) | Matching strategy, ride state machine, geo index | Driver assigned to two rides |
| [Library Management](library-management/THOUGHT_PROCESS.md) | Book vs BookCopy, reservations, fines with clock | Entity vs copy modelling |
| [Car Rental Platform](car-rental-platform/THOUGHT_PROCESS.md) | Availability calendar, half-open intervals | Overlap checks at scale |
| [ATM Banking System](atm-banking-system/THOUGHT_PROCESS.md) | Session state machine, cash dispenser chain | Transfer atomicity and lock ordering |
| [Inventory Management](inventory-management/THOUGHT_PROCESS.md) | Reservations vs on-hand stock, reorder observer | Oversell prevention |
| [Payment Processing](payment-processing-system/THOUGHT_PROCESS.md) | Idempotency keys, gateway strategy, fraud chain | Retries without double charge |
| [Job Scheduling](job-scheduling-system/THOUGHT_PROCESS.md) | Priority queue by run time, Command, worker pool | Recurring jobs and missed runs |
| [Notification Service](notification-service/THOUGHT_PROCESS.md) | Channel registry, templates, retries, preferences | Fallback without duplicates |
| [Search Platform](search-platform/THOUGHT_PROCESS.md) | Inverted index, TF-IDF ranking strategy | Index updates vs reads |
| [Big File Upload](big-file-upload/THOUGHT_PROCESS.md) | Chunking, resumable uploads (TUS), checksums | Resume after failure, idempotent chunks |
| [Order Matching Engine](order-matching-engine/THOUGHT_PROCESS.md) | Price-time priority, order book with heaps/sorted maps | Partial fills and determinism |
| [Circuit Breaker](circuit-breaker/THOUGHT_PROCESS.md) | CLOSED/OPEN/HALF_OPEN state machine, injected clock | Concurrent half-open probes |
| [Food Delivery](food-delivery/THOUGHT_PROCESS.md) | Order lifecycle, restaurant/rider assignment strategy | Multi-party state transitions |
| [Logging Framework](logging-framework/THOUGHT_PROCESS.md) | Levels, appenders, formatters, Chain/Decorator, async appender | Non-blocking logging with a bounded queue |

### Java (`java-low-level-design/`)

| Problem | Key concepts | The one hard part |
|---------|--------------|-------------------|
| [Elevator System](../java-low-level-design/elevator-system/THOUGHT_PROCESS.md) | Elevator state machine, dispatch strategy (SCAN/LOOK) | Request assignment under load |
| [Hotel Booking System](../java-low-level-design/hotel-booking-system/THOUGHT_PROCESS.md) | Room inventory by date, pricing strategy | Date-range overlap and concurrent booking |
| [Meeting Scheduler](../java-low-level-design/meeting-scheduler/THOUGHT_PROCESS.md) | Interval trees / sorted maps, room selection | Overlap detection and free-slot search |

### Go (`golang-low-level-design/`)

| Problem | Key concepts | The one hard part |
|---------|--------------|-------------------|
| [KV Store](../golang-low-level-design/kv-store/THOUGHT_PROCESS.md) | `RWMutex`, TTL expiry, WAL / snapshots | Durability vs latency |
| [Task Queue](../golang-low-level-design/task-queue/THOUGHT_PROCESS.md) | Channels, worker pool, retries, `context` | Graceful shutdown and at-least-once |
| [Web Crawler](../golang-low-level-design/web-crawler/THOUGHT_PROCESS.md) | Bounded concurrency, visited set, politeness | Dedup and termination detection |

---

## 📅 12. Three-Week Practice Plan

Each problem: 60 minutes timed from a blank file, then 20 minutes comparing against the repo's `THOUGHT_PROCESS.md`. Say everything out loud, even alone.

| Day | Problem | Drill |
|-----|---------|-------|
| | **Week 1: core modelling and state machines** | |
| 1 | Parking Lot | Full script end to end; time every phase |
| 2 | Vending Machine | State pattern vs transition table, argue both |
| 3 | LRU Cache | O(1) structure from memory, then thread safety |
| 4 | Rate Limiter | Token bucket + injected clock + per-key striping |
| 5 | Elevator System | Dispatch strategy; extension: VIP / service mode |
| 6 | Circuit Breaker | State machine with time, concurrent half-open |
| 7 | Review | Re-read sections 4–6 of this page; redo the weakest problem in 45 minutes |
| | **Week 2: concurrency and money (the differentiators)** | |
| 8 | Movie Ticket Booking | Holds with TTL, 50-thread test, then the DB version |
| 9 | Payment Processing | Idempotency keys, retries, refunds |
| 10 | Splitwise | Integer money, remainder distribution, simplification |
| 11 | Hotel Booking / Car Rental | Interval overlap, date-range inventory |
| 12 | Order Matching Engine | Price-time priority, partial fills, deterministic tests |
| 13 | Task Queue / Job Scheduler | Bounded queue, worker pool, graceful shutdown |
| 14 | Review | Write the concurrency test for every week-2 problem |
| | **Week 3: breadth, extension, HLD bridge** | |
| 15 | Cab Booking (Uber) | Matching strategy; take it to HLD (section 10) |
| 16 | Food Delivery | Multi-actor state machine; "now add scheduled orders" |
| 17 | Logging Framework / Notification Service | Decorator/Chain composition, async appender |
| 18 | Pub-Sub / KV Store | Delivery semantics, durability trade-offs |
| 19 | Mock: unseen problem from the list below | Strict 60 minutes, with someone interrupting with "now extend it" |
| 20 | Mock: another unseen problem | 45-minute format |
| 21 | Rest and re-read | This page only |

### Frequently asked problems not in the repo

| Problem | The key twist |
|---------|---------------|
| Stack Overflow | Voting with reputation side effects; one vote per user per post (unique constraint); bounties with expiry |
| Jira-style task tracker | Configurable per-project workflows as **data** (transition tables), custom fields, audit history via Command/events |
| Online auction | Concurrent bids (highest-bid CAS / conditional update), auction close timing, anti-sniping extension |
| Cricket scoreboard | Event-sourced ball-by-ball model; derived stats as Observers; undo the last ball |
| Traffic signal controller | Timed state machine with an injected clock; emergency-vehicle override; no conflicting greens invariant |
| File system (in-memory) | Composite pattern (file/directory), path resolution, permissions |
| Distributed ID generator | Snowflake layout, clock skew and sequence overflow |
| Digital wallet | Double-entry ledger (debits = credits), idempotent transfers, lock ordering |
| Amazon locker | Size-fit allocation, pickup code expiry, overbooking |
| Social feed / Twitter | Fan-out on write vs read, timeline merge (k-way merge with a heap) |
| Spreadsheet | Cell dependency graph, cycle detection, incremental recompute (topological order) |
| Text editor with undo | Command pattern, gap buffer / rope, undo/redo stacks |
| Shopping cart and coupons | Coupon rules as Strategy/Chain, stacking rules, price snapshot at checkout |

!!! success "Night-before checklist"
    1. Clarify, and write the requirements as a comment.
    2. Name the invariant and its single owner.
    3. Happy path first, runnable.
    4. Find the check-then-act race; lock or conditional update; no I/O under the lock.
    5. Money in minor units, UTC, injected clock, half-open intervals.
    6. Extension is a new class plus one registration line.
    7. Three tests: happy, invariant under threads, invalid transition.
    8. Say what changes with N instances: DB constraint, idempotency key, partition by key.
