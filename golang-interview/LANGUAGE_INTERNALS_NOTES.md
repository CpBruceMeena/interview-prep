# 🔬 Go Language Internals: Slices, Maps, Strings, Generics, `defer`, Stacks

> **The "how does it actually work" questions staff interviews ask about core Go**, with every snippet compiled and run (Go 1.26; output shown is real). Where internals vary by release, the text says so: interviewers respect "this is an implementation detail" far more than a confident wrong number.
>
> Companion files: [Interview Questions](INTERVIEW_QUESTIONS.md) (scheduler, GC, channels), [Pointers & Memory](POINTERS_MEMORY_NOTES.md) (escape analysis, alignment).

---

## Table of Contents

1. [Slices](#1-slices)
2. [Maps](#2-maps)
3. [Strings, bytes and runes](#3-strings-bytes-and-runes)
4. [Arrays and range semantics](#4-arrays-and-range-semantics)
5. [Generics](#5-generics)
6. [`defer`, `panic`, `recover`](#6-defer-panic-recover)
7. [Method sets and embedding](#7-method-sets-and-embedding)
8. [Goroutine stacks](#8-goroutine-stacks)
9. [Interview questions](#9-interview-questions)

---

## 1. Slices

A slice is a three-word header (`pointer`, `len`, `cap`) pointing into a backing array. Passing a slice copies the **header**, not the data.

```go
var s []int
prev := -1
for i := 0; i < 2000; i++ {
    s = append(s, i)
    if cap(s) != prev {
        fmt.Print(cap(s), " ")
        prev = cap(s)
    }
}
// Go 1.26.2 prints: 4 8 16 32 64 128 256 512 848 1280 1792 2560
```

- Capacity doubles while small, then grows by a smaller factor (roughly 1.25× plus a constant for large slices). Results are also **rounded up to a size class**, which is why you see `848`, not `640`.
- The exact sequence is an implementation detail that has changed between releases. **Never write code or tests that depend on it.** If you know the size, `make([]T, 0, n)`.

### Aliasing: the classic trap

```go
a := []int{1, 2, 3, 4, 5}
b := a[1:3]            // shares a's array: len 2, cap 4
b = append(b, 99)      // fits in cap → OVERWRITES a[3]
fmt.Println(a, b, len(b), cap(b))   // [1 2 3 99 5] [2 3 99] 3 4

c := a[1:3:3]          // full slice expression: cap limited to 2
c = append(c, 100)     // exceeds cap → reallocates, a untouched
fmt.Println(a, c)      // [1 2 3 99 5] [2 3 100]
```

Rule: **after `append`, always use the returned slice**, and if a function might retain or modify a sub-slice, hand it one with a capped capacity (`s[i:j:j]`) or a copy.

### Memory retention

A tiny sub-slice keeps the *entire* backing array alive for the GC.

```go
big := make([]byte, 1<<20)
small := slices.Clone(big[:10])   // copy; big can now be collected
fmt.Println(len(small), cap(small) < 1<<20)   // 10 true
```

The same applies to slices of pointers: `s = s[:len(s)-1]` leaves the last pointer reachable. Zero it first (`s[len(s)-1] = nil`) or use `slices.Delete` / `clear`, which handle it.

### nil vs empty

```go
var ns []int
es := []int{}
fmt.Println(ns == nil, es == nil, len(ns), len(es))   // true false 0 0
```

Both work with `len`, `append`, and `range`. They differ in `== nil`, in `reflect.DeepEqual`, and in **JSON** (`null` vs `[]`), which is the one that bites APIs.

---

## 2. Maps

- Go 1.24 replaced the bucket-based map with a **Swiss table** (open addressing, groups of 8 slots with a control word that is matched using SIMD-style bit tricks). Lookups and inserts are faster, memory is lower; the semantics didn't change.
- **Iteration order is deliberately randomized.** Never depend on it; sort the keys.
- **Not safe for concurrent use.** A concurrent write is detected on a best-effort basis and **kills the process** with `fatal error: concurrent map writes` (not a recoverable panic). Use a mutex, `sync.Map` (read-mostly or disjoint-key workloads), or shard.
- Reading from a `nil` map is fine and returns the zero value. **Writing panics.**
- Keys must be comparable. Floats work but `NaN != NaN`, so a NaN key can be inserted but never found. Interfaces as keys panic at runtime if the dynamic type isn't comparable.
- **Maps never shrink.** Deleting every key doesn't return memory; rebuild the map if a spike was large (or use `clear` only to reuse capacity).
- Values aren't addressable, so `m[k].f = v` doesn't compile for struct values. Read, modify, store back (or store pointers).

```go
m := map[string]int{"a": 1, "b": 2, "c": 3}
keys := slices.Sorted(maps.Keys(m))        // [a b c]  (Go 1.23+ iterator helpers)
for k := range m { delete(m, k) }          // deleting during range is allowed
fmt.Println(len(m))                         // 0

type P struct{ X int }
mp := map[string]P{"a": {1}}
p := mp["a"]; p.X++; mp["a"] = p
fmt.Println(mp)                             // map[a:{2}]
```

During iteration: deleting an unreached entry means it won't be produced; entries added may or may not be produced.

---

## 3. Strings, bytes and runes

- A string is an immutable `(pointer, len)` pair of **bytes**, conventionally UTF-8. `len(s)` is bytes. `s[i]` is a byte. `range s` decodes **runes**.
- A `rune` is `int32` (a code point). `[]rune(s)` copies and decodes: O(n) and allocates.

```go
str := "héllo, 世界"
fmt.Println(len(str), utf8.RuneCountInString(str), []rune(str)[1] == 'é', str[1])
// 14 9 true 195        ← é is two bytes (0xC3 0xA9); str[1] is the first byte 195
```

- Slicing a string is O(1) and shares memory (same retention caveat as slices). `strings.Clone` copies.
- Concatenating in a loop is O(n²); use `strings.Builder` (`Grow` if you know the size).
- `[]byte(s)` and `string(b)` copy, except where the compiler can prove no escape or mutation (e.g. `m[string(b)]` lookups, comparisons).
- Invalid UTF-8 decodes as `U+FFFD` (`utf8.RuneError`). Don't assume user input is valid.
- Normalization: `"é"` can be one code point or `e` + combining accent. Compare with `golang.org/x/text/unicode/norm`, not `==`, when identity matters (usernames, filenames).

---

## 4. Arrays and range semantics

Arrays are **values**: assignment and passing copy all elements. `range` over an array evaluates (copies) it first; over a slice it uses the live slice.

```go
arr := [3]int{1, 2, 3}
arr2 := arr; arr2[0] = 9
fmt.Println(arr, arr2)                 // [1 2 3] [9 2 3]

for i, v := range arr {
    arr[2] = 100                       // mutate during range
    if i == 2 { fmt.Println(v) }       // 3  ← range saw the copy
}
```

Since Go 1.22 each iteration has its own `i`/`v`, and `for i := range 3` ranges over an integer.

---

## 5. Generics

Type parameters (Go 1.18) with constraints are interfaces; `~int` means "any type whose underlying type is `int`".

```go
type Number interface{ ~int | ~int64 | ~float64 }

func Sum[T Number](xs []T) (s T) {
    for _, x := range xs { s += x }
    return
}

type MyInt int
fmt.Println(Sum([]int{1, 2, 3}), Sum([]float64{1.5, 2.5}), Sum([]MyInt{4, 5}))   // 6 4 9
```

**How they are implemented:** GC-shape stenciling with dictionaries. The compiler generates one instantiation per *GC shape* (types with the same memory layout, e.g. all pointer types share one), passing a dictionary of type metadata at runtime. Result: modest binary growth, but method calls on type-parameter values go through the dictionary and **may be slower than a direct interface call or hand-written code**. Don't reach for generics for performance.

**When generics earn their keep:** containers (`Set[T]`, `Cache[K,V]`), algorithms over slices/maps (`slices`, `maps` packages), type-safe wrappers (`atomic.Pointer[T]`, `sync.OnceValue`), channel/iterator helpers.

**When they don't:** if you only call methods, an ordinary interface is simpler. If behavior differs per type, a type switch inside a generic function is a smell. Don't parameterize "just in case."

**Limits worth knowing:** methods can't declare their own type parameters (a long-standing limitation; Go 1.27 begins to relax it, so check the release notes for the form that shipped). No specialization. `comparable` allows `==` but **panics at runtime** for interface-typed values holding uncomparable dynamic types (relaxed in 1.20 to compile).

---

## 6. `defer`, `panic`, `recover`

```go
func f() (n int, err error) {
    defer func() {
        if r := recover(); r != nil {
            err = fmt.Errorf("recovered: %v", r)
        }
    }()
    defer func() { n *= 2 }()
    n = 21
    var m map[string]int
    m["x"] = 1             // panics: assignment to entry in nil map
    return n, nil
}
fmt.Println(f())           // 42 recovered: assignment to entry in nil map
```

Rules to state precisely:

1. Deferred calls run **LIFO** when the function returns *or panics*.
2. **Arguments are evaluated when `defer` executes**, not when the call runs:

```go
x := 1
defer fmt.Println("arg evaluated now:", x)   // prints 1, even though x=2 below
x = 2
```

3. Deferred closures can **read and modify named results**, which is how the `recover` example above set `err`, and why `n` became 42 (the `n *= 2` ran during the panic unwind).
4. `recover()` only works **directly inside a deferred function**, and only in the goroutine that panicked. A panic in another goroutine with no recover **crashes the whole process**; this is why every `go func()` that can panic in a server needs its own recover (or a wrapper like `safeGo`).
5. Don't `defer` in a hot loop: deferred calls pile up until the function returns (open-coded defers cover only simple, non-loop cases). Wrap the body in a function.
6. `defer f.Close()` ignores the error. For writes, check it: `defer func() { err = errors.Join(err, f.Close()) }()`.
7. Don't use panic for control flow. Reserve it for programmer errors and unrecoverable states. Libraries should convert internal panics to errors at their boundary.

---

## 7. Method sets and embedding

| Receiver | Method set of `T` | Method set of `*T` |
|---|---|---|
| `func (t T) M()` | ✅ | ✅ |
| `func (t *T) M()` | ❌ | ✅ |

So a value of type `T` does **not** satisfy an interface whose method has a pointer receiver:

```go
type Animal interface{ Sound() string }
type Dog struct{}
func (*Dog) Sound() string { return "woof" }

var a Animal = &Dog{}     // OK
// var b Animal = Dog{}   // compile error: Dog does not implement Animal (Sound has pointer receiver)
```

**Choosing a receiver:** pointer if the method mutates, the struct is large, or it contains a `sync.Mutex` (copying a mutex is a bug; `go vet` flags it). Be consistent within a type. Mixing is allowed but confusing.

**Embedding is composition, not inheritance.** Embedded fields' methods are *promoted*, but there is no virtual dispatch: the embedded type's methods see the **embedded** value as `self`, never the outer type. Embedding a `sync.Mutex` exports `Lock`/`Unlock` on your type; usually prefer a named field.

---

## 8. Goroutine stacks

- A new goroutine starts with a small stack (on the order of **2 KB**; the runtime may adapt the initial size using observed averages).
- The compiler inserts a stack check in function prologues. When the stack is full the runtime **allocates a larger one (about 2×), copies the old one over, and adjusts pointers** into it. Stacks can also shrink during GC.
- This is why **you can't hold a pointer to a stack variable across a stack move**, which is part of why escape analysis decides what lives on the stack, and why pointers into stacks never appear in the heap.
- Deep recursion works until the limit (1 GB on 64-bit by default) and then **fatal error: stack overflow**, which can't be recovered.
- This is what makes a goroutine ~2 KB while an OS thread reserves ~1–8 MB, and why 100k+ goroutines are routine.

```go
func rec(n int) int {
    var pad [1024]byte; pad[0] = byte(n)
    if n == 0 { return int(pad[0]) }
    return rec(n-1) + int(pad[0])
}
go func() { rec(10000); close(done) }()   // ~10 MB of frames from a 2 KB start: works, stack grew
```

---

## 9. Interview questions

**Q1. What does `append` do when capacity is exhausted, and what bug does aliasing cause?**
It allocates a larger array, copies elements, and returns a header pointing at it. If capacity *isn't* exhausted it writes in place, so other slices sharing the array see the change. Always reassign the result; cap sub-slices you hand out with the three-index form.

**Q2. Why does `for k := range m { delete(m, k) }` work but concurrent map access crashes?**
Single-goroutine mutation during iteration is defined (deleted entries won't be visited; new ones may or may not). Concurrent access is a data race, and the runtime detects some of it and aborts with a fatal, unrecoverable error because continuing could corrupt the table.

**Q3. Is `==` on a `nil` slice and an empty slice the same?**
Both have length 0 and behave identically with `len`/`append`/`range`, but `s == nil` differs, and JSON encodes `nil` as `null` and empty as `[]`. Normalize at API boundaries.

**Q4. Explain `defer` evaluation order and how it interacts with named results.**
LIFO; arguments evaluated at the `defer` statement; closures run after the `return` values are set and can modify named results; `recover` works only directly inside a deferred func.

**Q5. When would you not use generics?**
When an interface already expresses it, when per-type behavior needs a type switch, or when you want speed (dictionary-based calls can be slower than direct ones). Use them for containers and slice/map algorithms.

**Q6. Why can a value `T` not satisfy an interface implemented on `*T`?**
Method sets: `T` has only value-receiver methods. The compiler won't take the address implicitly because the value in the interface would be a copy, and mutations would silently be lost.

**Q7. How can a goroutine's stack be 2 KB and still run deep recursion?**
Stacks are growable and copied on overflow, with pointer adjustment. The cost is a copy per doubling, which is amortized, and a hard limit (1 GB) after which the process dies with `stack overflow`.

**Q8. A service's memory climbs although its live data is small. Slice/map-related suspects?**
Sub-slices pinning big arrays; slices of pointers with stale tails; maps that grew large and never shrank; `[]byte`→`string` retention; `time.After` in loops; unbounded caches. Check with `pprof -inuse_space` and `-alloc_space`.

**Q9. Struct field order and size?**
Fields are aligned to their type's alignment, so order changes padding: `struct{bool; int64; bool}` is **24 bytes**; `struct{int64; bool; bool}` is **16**. Sort fields largest-alignment first for dense, hot structs (and use `fieldalignment` from `x/tools` to check). For sizes: string 16 B, slice 24 B, interface 16 B on 64-bit.

**Q10. What does "accept interfaces, return structs" mean, and when is it wrong?**
Define small interfaces *at the consumer* so callers can substitute fakes; return concrete types so callers get the full API and you avoid premature abstraction. It's wrong when you need to hide the implementation (return an interface from a factory that selects among implementations) or when the interface is large (the bigger the interface, the weaker the abstraction).
