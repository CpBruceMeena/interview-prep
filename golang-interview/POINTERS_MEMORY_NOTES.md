# 📍 Go — Pointers, Addresses, Memory & Object Handling

> **Category:** Language Fundamentals — Memory Model & Pointer Semantics  
> **Target Level:** Staff/Principal Engineer (10+ years)  
> **Why this matters at Staff level:** Memory bugs, escape analysis decisions, and pointer aliasing are the root causes of ~40% of production incidents in Go services. Understanding Go's memory model at the assembly level separates Staff engineers from Senior engineers.

---

## Table of Contents

1. [The `&` and `*` Operators — What They Really Do](#1-the-and-operators-what-they-really-do)
2. [How Objects Are Handled: Value vs Pointer Semantics](#2-how-objects-are-handled-value-vs-pointer-semantics)
3. [Stack vs Heap Allocation & Escape Analysis](#3-stack-vs-heap-allocation-escape-analysis)
4. [Pass by Value — But Everything Is a Copy](#4-pass-by-value-but-everything-is-a-copy)
5. [Pointer Arithmetic — Why Go Doesn't Have It (Usually)](#5-pointer-arithmetic-why-go-doesnt-have-it-usually)
6. [Nil Pointers, Zero Values & The Interface Nil Trap](#6-nil-pointers-zero-values-the-interface-nil-trap)
7. [Memory Alignment & Padding](#7-memory-alignment-padding)
8. [`unsafe.Pointer` & `uintptr` — The Escape Hatch](#8-unsafepointer-uintptr-the-escape-hatch)
9. [GC & Pointer Impact on Garbage Collection](#9-gc-pointer-impact-on-garbage-collection)
10. [Common Pitfalls & Production Bugs](#10-common-pitfalls-production-bugs)
11. [Interview Questions](#11-interview-questions)

---

## 1. The `&` and `*` Operators — What They Really Do

### `&` (Address-of Operator)

The `&` operator returns a **pointer to the memory location** of a variable. It creates a new pointer value pointing to an existing variable.

```go
x := 42
p := &x  // p is *int, holds the memory address of x

fmt.Println(p)  // 0xc0000b2008 (some memory address)
fmt.Println(*p) // 42
```

**What actually happens at the assembly level (simplified):**

```asm
// x := 42
MOVQ $42, (SP)       // Store 42 on stack at SP

// p := &x
LEAQ (SP), AX        // Load Effective Address of SP into AX
MOVQ AX, (SP+8)      // Store address in p's memory location
```

`LEAQ` (Load Effective Address) is the CPU instruction — it computes the address without accessing memory. This is **zero-cost** for stack variables.

### `*` (Dereference Operator)

The `*` operator **accesses the value at the memory address** stored in a pointer.

```go
p := &x
y := *p  // Reads the value at address p, copies it to y
*p = 100 // Writes 100 to the address p points to
```

**Assembly:**

```asm
// y := *p
MOVQ (AX), BX        // Load value at address AX into BX
MOVQ BX, (SP+16)     // Store in y

// *p = 100
MOVQ $100, (AX)      // Store 100 at the address in AX
```

### Declaration Syntax — T vs *T

```go
var a int      // a holds an int value (8 bytes on 64-bit)
var b *int     // b holds a pointer to an int (8 bytes, holds address)

a = 42         // Stores 42 in a's memory
b = &a         // Stores a's address in b's memory
*b = 43        // Writes 43 to wherever b points (a's memory)
```

**Key insight:** `*int` is a type. It's an 8-byte value that holds an address. When you write `*b = 43`, you're saying "follow the address in b and write 43 there."

### The `new()` Built-in

```go
p := new(int)  // Allocates zero-value int on heap, returns *int
*p = 42        // Sets the int to 42

// Equivalent to:
var x int
p := &x        // But x is stack-allocated (usually)
```

`new(T)` always **allocates and returns a pointer**. It does NOT initialize — all fields are zero-valued.

---

## 2. How Objects Are Handled: Value vs Pointer Semantics

### Value Semantics (Copies)

```go
type User struct {
    Name string
    Age  int
}

// Value receiver — operates on a COPY
func (u User) Print() {
    fmt.Printf("%+v\n", u)
}

// Value receiver — modifying has NO effect on caller
func (u User) Birthday() {
    u.Age++  // Only modifies the copy!
}
```

**When to use value semantics:**
- The type is small (< 4 machine words, ~32 bytes)
- Immutable-like behavior (e.g., `time.Time`, `color.RGBA`)
- The type is a primitive or simple scalar

### Pointer Semantics (References)

```go
// Pointer receiver — operates on the ORIGINAL
func (u *User) Birthday() {
    u.Age++  // Modifies the original!
}

// Also works:
func (u *User) Print() {
    fmt.Printf("%+v at %p\n", *u, u)
}
```

**When to use pointer semantics:**
- The type is large (> 4 machine words)
- You need to mutate the receiver
- The type is a struct with `sync.Mutex` or similar (to avoid copying locks)
- The type holds a reference type internally (slice, map, channel)

### The Mixing Rule — Consistency is Key

**🔴 BAD — mixing value and pointer receivers:**

```go
type Config struct {
    Timeout time.Duration
}

func (c Config) GetTimeout() time.Duration { return c.Timeout }
func (c *Config) SetTimeout(d time.Duration) { c.Timeout = d }  // Mixed!
```

**✅ GOOD — be consistent:**

```go
// If one method needs pointer, ALL should be pointer
func (c *Config) GetTimeout() time.Duration { return c.Timeout }
func (c *Config) SetTimeout(d time.Duration) { c.Timeout = d }
```

**The Rule of Thumb:** If you're not sure, use pointer receivers. The only exception is very small, immutable types.

### Factory Functions — Return Value or Pointer?

```go
// Returns a value — caller gets a copy
func NewUser(name string, age int) User {
    return User{Name: name, Age: age}
}

// Returns a pointer — caller gets a pointer to heap-allocated User
func NewUserPtr(name string, age int) *User {
    return &User{Name: name, Age: age}
}
```

**When to return pointer:**
- The caller needs to mutate the returned value
- The type is large (avoids copying)
- The type is expected to be used as a pointer (e.g., database models)

**When to return value:**
- The type is small and immutable
- The caller is expected to own the data independently
- You want to encourage value semantics

---

## 3. Stack vs Heap Allocation & Escape Analysis

### The Stack

- Each goroutine has its own stack (initially 2 KB, grows as needed)
- Allocation = push frame pointer — **essentially free**
- Deallocation = pop frame pointer — **essentially free**
- Data is contiguous, cache-friendly

### The Heap

- Managed by the garbage collector
- Allocation = find free space in heap arena — **slower**
- Deallocation = GC mark/sweep — **much slower**
- Data can be scattered (pointer chasing, cache misses)

### Escape Analysis — The Compiler's Decision

The Go compiler decides whether a variable lives on the stack or the heap using **escape analysis**. If the compiler can prove a variable doesn't outlive its function, it stays on the stack.

```go
// ── Example 1: Stays on stack ────────────────────────────
func sum() int {
    x := 42       // Compiler: x doesn't escape
    y := 58       // Compiler: y doesn't escape
    return x + y
}

// ── Example 2: Escapes to heap ──────────────────────────
func newUser() *User {
    u := User{Name: "Alice"}  // Compiler: u escapes!
    return &u                 // Because we return its address
}

// ── Example 3: Interface escape ─────────────────────────
func printAny(v any) {
    fmt.Println(v)  // v escapes to heap (interface dynamic dispatch)
}

func demo() {
    x := 42
    printAny(x)  // x escapes to heap (boxed into interface)
}

// ── Example 4: Closure escape ───────────────────────────
func adder() func(int) int {
    sum := 0
    return func(x int) int {  // sum escapes to heap
        sum += x               // closure references sum
        return sum
    }
}
```

### Checking Escape Analysis

```bash
# Tell the compiler to show escape analysis decisions
go build -gcflags="-m" ./...
go build -gcflags="-m -m" ./...  # More detail

# Example output:
# ./main.go:10:6: can inline sum
# ./main.go:28:6: moved to heap: u
# ./main.go:35:16: leaking param: v
```

### Real-World Optimization

```go
// 🔴 BAD: Returns pointer, forces heap allocation
type Response struct {
    Data []byte
}
func Process() *Response {
    resp := &Response{Data: make([]byte, 1024)}
    return resp
}

// ✅ GOOD: Return value, let caller decide
func Process() Response {
    return Response{Data: make([]byte, 1024)}
}

// Or even better: pass buffer from caller
func Process(buf []byte) *Response {
    return &Response{Data: buf}
}
```

**Key insight:** Returning a pointer doesn't always cause escape. If the compiler can inline the caller, it may allocate on the caller's stack instead.

### Escape Analysis Rules Summary

| Condition | Escapes? | Reason |
|-----------|----------|--------|
| `return &x` | ✅ Yes | Value must outlive function |
| `fmt.Printf("%p", &x)` | ✅ Yes | Address taken for parameter |
| `x := 42; go func() { fmt.Println(x) }()` | ✅ Yes | Closure captures variable |
| `s := make([]int, 1000)` | ✅ Yes | Large allocations always heap |
| `s := make([]int, 10)` | ❌ No | Small slice fits on stack |
| Interface method call with value | ✅ Yes | Dynamic dispatch boxes value |
| `var x int; p := &x` (no return) | ❌ No | Address doesn't escape scope |
| `json.Marshal(x)` | ✅ Yes | Reflection causes escape |

---

## 4. Pass by Value — But Everything Is a Copy

**Go is ALWAYS pass-by-value.** There is no pass-by-reference in Go. When you pass a variable to a function, Go makes a copy.

```go
func increment(x int) {
    x++  // Only modifies the copy
}

func main() {
    a := 10
    increment(a)
    fmt.Println(a)  // 10 (not 11!)
}
```

### But What About Pointers?

Passing a pointer is still pass-by-value — it copies the pointer itself (the address).

```go
func incrementPtr(p *int) {
    *p++  // Follows the pointer to modify the original
    // p itself is a copy of the address — modifying p wouldn't affect caller
}

func main() {
    a := 10
    incrementPtr(&a)
    fmt.Println(a)  // 11
}
```

**What's being copied:** The 8-byte address value. Both `p` (in function) and `&a` (in caller) point to the same memory, but `p` is a distinct variable containing the same address.

### What About Slices, Maps, and Channels?

These are **reference types** — they contain a pointer to underlying data:

```go
func modifySlice(s []int) {
    s[0] = 999  // Modifies the underlying array
}

func main() {
    nums := []int{1, 2, 3}
    modifySlice(nums)
    fmt.Println(nums[0])  // 999
}
```

**BUT** — the slice header (ptr + len + cap) is still **copied by value**:

```go
func appendSlice(s []int) {
    s = append(s, 4)  // Only modifies the local copy of the header
}

func main() {
    nums := make([]int, 3, 10)
    nums[0], nums[1], nums[2] = 1, 2, 3
    appendSlice(nums)
    fmt.Println(nums)  // [1 2 3] (not [1 2 3 4]!)
}
```

**Go memory layout — the `reflect.SliceHeader`:**

```go
type SliceHeader struct {
    Data uintptr  // Pointer to the underlying array
    Len  int      // Length
    Cap  int      // Capacity
}
// Total: 24 bytes (on 64-bit)
```

### The `map` Gotcha

```go
func modifyMap(m map[string]int) {
    m["key"] = 42  // This DOES modify the original map
    m = nil        // But this does NOT affect caller's m
}

func main() {
    data := map[string]int{"a": 1}
    modifyMap(data)
    fmt.Println(data["key"])  // 42
    fmt.Println(data == nil)  // false
}
```

**Why?** A map variable is a pointer to the runtime's `hmap` struct. The pointer itself is copied, but both copies point to the same underlying hash map.

---

## 5. Pointer Arithmetic — Why Go Doesn't Have It (Usually)

### Go Explicitly Disallows Pointer Arithmetic

```go
arr := [3]int{1, 2, 3}
p := &arr[0]

// 🔴 COMPILE ERROR: Go doesn't allow this
q := p + 1  // invalid operation: p + 1 (type *int does not support +)
```

**Why?** Memory safety. C/code with pointer arithmetic is the single largest source of security vulnerabilities (buffer overflows, use-after-free). Go's design philosophy prioritizes memory safety.

### How to Work Around (When You Absolutely Must)

```go
import "unsafe"

arr := [3]int{1, 2, 3}

// Get pointer to first element
base := unsafe.Pointer(&arr[0])

// Move to second element (int is 8 bytes on 64-bit)
second := (*int)(unsafe.Pointer(uintptr(base) + unsafe.Sizeof(arr[0])))

fmt.Println(*second)  // 2
```

**⚠️ WARNING:** This is fragile, unsafe, and likely to break across Go versions or architectures. Only use in:
- Interfacing with C code (cgo)
- Extreme performance optimization (proven via profiling)
- Implementing low-level data structures

---

## 6. Nil Pointers, Zero Values & The Interface Nil Trap

### Nil Pointer Dereference

```go
var p *int  // p is nil (zero value for pointer types)

// 🔴 PANIC: runtime error: invalid memory address or nil pointer dereference
fmt.Println(*p)
```

**Always check for nil before dereferencing:**

```go
if p != nil {
    fmt.Println(*p)
}
```

### The Interface Nil Trap — Staff-Level Essential

**This is the #1 trick question in Go interviews:**

```go
type Animal interface {
    Speak() string
}

type Dog struct{}
func (d *Dog) Speak() string { return "Woof!" }

func NewAnimal() Animal {
    var d *Dog = nil  // typed nil
    return d          // Returns interface with type *Dog, value nil
}

func main() {
    a := NewAnimal()
    fmt.Println(a == nil)  // false !!!
    
    var b Animal = nil
    fmt.Println(b == nil)  // true
}
```

**Why?** An interface value is `(type, value)`. When you return `(*Dog)(nil)`, the interface becomes `(*Dog, nil)` — the type `*Dog` is set, so the interface is NOT nil even though the underlying value is nil.

**The memory layout:**

```go
// iface{tab: &itab{inter: Animal, _type: *Dog}, data: nil}
// a == nil compares iface == eface{nil, nil} — they don't match!
```

**🔴 What happens when you call methods on this "nil" interface?**

```go
a := NewAnimal()
fmt.Println(a.Speak())  // Works! nil receiver is callable
```

**Yes — Go allows calling methods on nil receivers!** This is intentional and useful:

```go
func (d *Dog) Speak() string {
    if d == nil {
        return "silence"  // Handle nil receiver gracefully
    }
    return "Woof!"
}

a := NewAnimal()
fmt.Println(a.Speak())  // "silence"
```

**Production pattern — nil receivers as tree sentinels:**

```go
type Node struct {
    Value int
    Left  *Node
    Right *Node
}

func (n *Node) Sum() int {
    if n == nil {
        return 0  // nil receiver is the base case!
    }
    return n.Value + n.Left.Sum() + n.Right.Sum()
}
```

---

## 7. Memory Alignment & Padding

### Why Alignment Matters

CPU architectures read memory at word boundaries (8 bytes on 64-bit). Misaligned access can:
- Double the memory read time (two reads instead of one)
- Crash on some architectures (Sparc, ARM pre-v6)
- Cause atomic operation panics on 32-bit platforms

### Struct Padding

```go
// ── BAD: Poor alignment ────────────────────────────────
type BadStruct struct {
    A bool    // 1 byte  + 7 bytes padding
    B int64   // 8 bytes
    C bool    // 1 byte  + 7 bytes padding
} // Total: 24 bytes (8 × 3)
//   Layout: [b|_ _ _ _ _ _ _|B B B B B B B B|b|_ _ _ _ _ _ _]

// ── GOOD: Optimal alignment ─────────────────────────
type GoodStruct struct {
    B int64   // 8 bytes
    A bool    // 1 byte
    C bool    // 1 byte  + 6 bytes padding (tail only)
} // Total: 16 bytes (8 × 2)
//   Layout: [B B B B B B B B|b b|_ _ _ _ _ _]
```

**Rule:** Sort fields by size descending (largest first). This minimizes padding.

### Using `unsafe.Sizeof`, `unsafe.Offsetof`, `unsafe.Alignof`

```go
import "unsafe"

type Point struct {
    X float64  // 8 bytes
    Y float64  // 8 bytes
}

fmt.Println(unsafe.Sizeof(Point{}))    // 16
fmt.Println(unsafe.Alignof(Point{}))   // 8
fmt.Println(unsafe.Offsetof(Point{}.Y)) // 8

// Atomic alignment requirement (critical!)
type AtomicCounter struct {
    // On 32-bit platforms, the first field must be 8-byte aligned
    // for sync/atomic operations to work correctly
    value int64  // Must be 8-byte aligned
}

// 🔴 BAD: On 32-bit platforms, value may NOT be 8-byte aligned
type BadCounter struct {
    flag  bool  // 1 byte + 7 bytes padding
    value int64 // 8 bytes — starts at offset 8, which IS 8-byte aligned
    // Actually on 32-bit, struct base is 4-byte aligned
    // so offset 8 from 4-byte base = 8... this is fine for 64-bit fields
    // The real issue is on 32-bit where atomic.AddInt64 requires 8-byte alignment
    // But a struct starts at 4-byte alignment on 32-bit
    // So value at offset 8 from 4-byte = 12 → NOT 8-byte aligned → PANIC
}
```

**Critical production rule:** On 32-bit platforms, if you use `sync/atomic` on a `int64`/`uint64` field, it must be the **first field** in the struct to guarantee 8-byte alignment. Go's runtime guarantees the first field is 8-byte aligned even on 32-bit platforms.

---

## 8. `unsafe.Pointer` & `uintptr` — The Escape Hatch

### The Three Pointer Types

```go
// 1. Typed pointer — safe, checked by compiler
var p *int

// 2. unsafe.Pointer — pointer to any type, like C's void*
//   - Can convert any typed pointer to unsafe.Pointer
//   - Can convert unsafe.Pointer to any typed pointer
//   - Cannot do arithmetic (uintptr needed for that)
var up unsafe.Pointer = unsafe.Pointer(p)

// 3. uintptr — an integer large enough to hold a pointer address
//   - Can do arithmetic
//   - NOT a pointer — GC doesn't track it!
var addr uintptr = uintptr(up)
```

### The GC Trap with uintptr

```go
// 🔴 DANGEROUS: uintptr doesn't keep object alive!
func dangerous() {
    obj := &SomeLargeStruct{}
    addr := uintptr(unsafe.Pointer(obj))  // GC doesn't know about this
    
    // GC could run here and collect obj!
    // addr now points to garbage!
    
    p := (*SomeLargeStruct)(unsafe.Pointer(addr))  // Use-after-free!
}

// ✅ SAFE: Keep the pointer alive
func safe() {
    obj := &SomeLargeStruct{}
    p := unsafe.Pointer(obj)  // GC sees this as a pointer
    // ... work with p ...
    obj2 := (*SomeLargeStruct)(p)
    _ = obj2
}
```

**Rule of thumb:** Never store a Go pointer in a `uintptr`. Only use `uintptr` for intermediate calculations, then immediately convert back to `unsafe.Pointer`.

### Real-World Use: Zero-Copy String Conversion

```go
// strings.Builder uses this internally
func bytesToString(b []byte) string {
    return *(*string)(unsafe.Pointer(&b))
}

// Equivalent to:
// s := string(b)  // But this COPIES the data
// bytesToString() does ZERO copy — same underlying memory!

// 🔴 BUT: If b is modified, s sees the change!
// This violates Go's string immutability guarantee!
```

**Production pattern — zero-copy JSON parsing:**

```go
// When you know the bytes are valid UTF-8 and won't be modified
func UnsafeString(b []byte) string {
    return *(*string)(unsafe.Pointer(&b))
}

// Matching zero-copy string to bytes (for reuse)
func UnsafeBytes(s string) []byte {
    sh := (*reflect.StringHeader)(unsafe.Pointer(&s))
    bh := reflect.SliceHeader{
        Data: sh.Data,
        Len:  sh.Len,
        Cap:  sh.Len,
    }
    return *(*[]byte)(unsafe.Pointer(&bh))
}
```

---

## 9. GC & Pointer Impact on Garbage Collection

### Pointer Density Affects GC Performance

The Go GC must scan all pointers to find reachable objects. More pointers = more work for GC.

```go
// ── High pointer density — GC intensive ────────────────
type Node struct {
    Left  *Node    // pointer
    Right *Node    // pointer
    Data  []byte   // pointer (slice header)
    Meta  *Metadata // pointer
} // 4 pointers per node

// ── Low pointer density — GC friendly ──────────────────
type FlatNode struct {
    Index int32    // no pointer
    Left  int32    // index into array, not pointer
    Right int32    // index into array, not pointer
    Size  int64    // no pointer
    Flags uint32   // no pointer
} // 0 pointers per node
```

### GC Scanning Cost

```go
// The GC scans:
// 1. Global variables
// 2. Goroutine stacks (every running goroutine's stack!)
// 3. Heap objects (following pointers)
//
// Each pointer scanned takes ~5-20ns (depends on hardware)
// 100M pointers = 0.5 - 2 seconds of scanning time
//
// Reducing pointer count by 50% ≈ doubles GC speed

// ── Before: pointer-heavy ─────────────────────────────
type CacheEntry struct {
    Key   string     // pointer (string header)
    Value []byte     // pointer (slice header)
    Tags  []string   // pointer (slice header)
}

// ── After: pointer-light ──────────────────────────────
type FlatCacheEntry struct {
    KeyData   [32]byte  // inline array, no pointer
    KeyLen    uint8
    ValueData [256]byte // inline, no pointer
    ValueLen  uint16
    TagBitmap uint64    // bitset instead of slice
}
```

### Practical GC Optimization

```go
// ✅ Pre-allocate slices with known capacity
// 🔴 BAD: append causes repeated growth and GC churn
func Build() []Item {
    var items []Item
    for _, v := range data {
        items = append(items, Item{Value: v})
    }
    return items
}

// ✅ GOOD: pre-allocate
func Build() []Item {
    items := make([]Item, 0, len(data))
    for _, v := range data {
        items = append(items, Item{Value: v})
    }
    return items
}

// ✅ Use sync.Pool for frequently allocated objects
var bufferPool = sync.Pool{
    New: func() any {
        return new(bytes.Buffer)
    },
}

func Process() {
    buf := bufferPool.Get().(*bytes.Buffer)
    defer bufferPool.Put(buf)
    buf.Reset()
    // ... use buf ...
}
```

---

## 10. Common Pitfalls & Production Bugs

### Pitfall 1: Loop Variable Capture (pre-Go 1.22)

```go
// 🔴 BUG: All goroutines see the SAME address
for i := 0; i < 3; i++ {
    go func() {
        fmt.Println(&i)  // All point to same address!
    }()
}

// ✅ FIX (pre-1.22): Create a new variable each iteration
for i := 0; i < 3; i++ {
    i := i  // Shadow! Create new variable in this scope
    go func() {
        fmt.Println(&i)
    }()
}

// ✅ Go 1.22+: Fixed! Each iteration gets a new variable
for i := range 3 {
    go func() {
        fmt.Println(&i)  // Different address per iteration
    }()
}
```

### Pitfall 2: Slice Append After Passing to Function

```go
// 🔴 BUG: Appending to a copied slice header
func addItem(items []int) {
    items = append(items, 4)  // Caller's items unaffected
}

items := []int{1, 2, 3}
addItem(items)
fmt.Println(items)  // [1 2 3] — NOT updated!

// ✅ FIX: Return the new slice or pass pointer
func addItem(items *[]int) {
    *items = append(*items, 4)
}
addItem(&items)
fmt.Println(items)  // [1 2 3 4]
```

### Pitfall 3: Range Copies Values (Not References)

```go
type Person struct {
    Name string
}

people := []Person{{"Alice"}, {"Bob"}}

// 🔴 BUG: p is a COPY, doesn't modify original
for _, p := range people {
    p.Name = "Changed"  // Only modifies copy
}

// ✅ FIX: Use index or pointer slice
for i := range people {
    people[i].Name = "Changed"
}

// Or use pointer slice:
people2 := []*Person{{"Alice"}, {"Bob"}}
for _, p := range people2 {
    p.Name = "Changed"  // Works! p is a pointer
}
```

### Pitfall 4: Returning Local Pointer After Inlining

```go
func create() *int {
    x := 42
    return &x  // x escapes to heap — fine
}

// But what if compiler inlines create()?

func caller() {
    p := create()  // Inlined: &x is on caller's stack
    fmt.Println(*p)  // Works because caller's stack is still alive
}
```

### Pitfall 5: Method Value vs Method Expression

```go
type Counter struct {
    Value int
}

func (c *Counter) Inc() { c.Value++ }

// Method value — binds receiver AT CALL TIME
c := &Counter{}
f := c.Inc  // f is a function that will Inc c (or whatever c points to)
c = &Counter{Value: 42}
f()  // Increments which? The new c! (c was reassigned)
fmt.Println(c.Value)  // 43

// Method expression — binds receiver AT CALL SITE? NO
// Actually method expressions work differently:
g := (*Counter).Inc  // g is a function taking (*Counter)
c2 := &Counter{}
g(c2)  // Must pass the receiver explicitly
```

**The real trap with method values:**

```go
type Counter struct {
    Value int
    mu    sync.Mutex
}

func (c *Counter) Process() {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.Value++
    
    // ... some work ...
    
    // 🔴 BUG: Method value captures c BEFORE defer runs
    defer c.Print  // Captures c's pointer value NOW
}

func (c *Counter) Print() {
    fmt.Println(c.Value)
}

// ✅ FIX:
defer func() {
    c.Print()  // Evaluates c at defer time
}()
```

---

## 11. Interview Questions

### Question 1: Escape Analysis

**Problem:** Look at this code and predict what escapes to heap. Explain your reasoning.

```go
type Config struct {
    Name string
    Port int
}

func NewConfig(name string, port int) *Config {
    return &Config{Name: name, Port: port}
}

func Process(config *Config) {
    fmt.Println(config.Name)
}
```

<details>
<summary>🎯 Answer</summary>

- `NewConfig` returns `*Config` → `Config{...}` escapes to heap
- `name string` parameter's underlying data escapes (stored in heap Config)
- `config` parameter in `Process` doesn't escape — it's passed to `fmt.Println` which takes `any`, causing the pointer to escape via interface boxing
- `config.Name` is a string → the pointer data within the Config struct is on heap (already escaped)

**Key insight:** Even though `config` is a pointer to heap memory, passing it to `fmt.Println` which takes `any` causes the pointer value itself to be boxed, which is an additional allocation.

</details>

### Question 2: The Nil vs Non-Nil Interface

**Problem:** This code panics. Why? Fix it.

```go
type Handler interface {
    Handle()
}

type MyHandler struct{}

func (h *MyHandler) Handle() {}

func NewHandler() Handler {
    return nil
}

func NewBetterHandler() Handler {
    var h *MyHandler = nil
    return h
}

func main() {
    h := NewBetterHandler()
    fmt.Println(h == nil)  // What does this print?
}
```

<details>
<summary>🎯 Answer</summary>

Prints `false`. `NewBetterHandler` returns an interface with type `*MyHandler` and value `nil`. Since the type is set, the interface is not nil.

`NewHandler()` returns an interface with type `nil` and value `nil` — that one IS nil.

**Fix:** Either:
1. Always return explicit nil from factory functions
2. Wrap in a struct that checks nil: `if h == nil { return nil }`
3. Use `reflect.ValueOf(h).IsNil()` (but this panics if h is non-pointer)

</details>

### Question 3: Stack or Heap?

**Problem:** For each variable below, will it be stack or heap allocated? Explain.

```go
func main() {
    var a int                                       // ?
    b := 42                                         // ?
    c := new(int)                                   // ?
    d := make([]int, 10)                            // ?
    e := make([]int, 10000)                         // ?
    
    var f [100]int                                  // ?
    g := &f                                         // ?
    
    h := struct{ x int }{42}                        // ?
    i := &struct{ x int }{42}                       // ?
    
    s := "hello"                                    // ?
    t := s[0]                                       // ?
}
```

<details>
<summary>🎯 Answer</summary>

| Var | Location | Reason |
|-----|----------|--------|
| `a` | Stack | Small, doesn't escape |
| `b` | Stack | Small, doesn't escape |
| `c` | Heap | `new()` always allocates on heap |
| `d` | Stack (≤32KB) | Small slice escapes if its size exceeds stack threshold (~32KB on most Go versions) |
| `e` | Heap | Large allocation (>32KB) |
| `f` | Stack | Fixed-size array, doesn't escape |
| `g` | Stack | `g` itself is stack, `f` stays on stack (address doesn't escape) |
| `h` | Stack | Small struct, doesn't escape |
| `i` | Heap | Address taken and returned — must be heap unless compiler can inline |
| `s` | Stack | String header on stack, data may be in read-only data section |
| `t` | Stack | Byte value, small |

</details>

### Question 4: Pointer Copy Semantics

**Problem:** What does this code print?

```go
type User struct {
    Name string
    Age  int
}

func main() {
    users := []User{{"Alice", 30}, {"Bob", 25}}
    
    for _, u := range users {
        u.Age += 10
    }
    
    fmt.Println(users[0].Age)  // ?
    
    for i := range users {
        users[i].Age += 10
    }
    
    fmt.Println(users[0].Age)  // ?
}
```

<details>
<summary>🎯 Answer</summary>

First print: `30`. The `for _, u := range users` creates a copy of each `User`. Modifying `u.Age` only modifies the copy.

Second print: `40`. Using index `users[i]` accesses the actual element in the slice, so the modification persists.

</details>

### Question 5: Memory Alignment Bug

**Problem:** This code works on 64-bit but panics on 32-bit ARM. Why?

```go
type Stats struct {
    active    bool
    requests  int64
    errors    int64
}

var stats Stats
atomic.AddInt64(&stats.requests, 1)
```

<details>
<summary>🎯 Answer</summary>

On 32-bit platforms, `sync/atomic` requires 8-byte alignment for `int64` fields. The struct layout on 32-bit:

- `active bool` at offset 0 (1 byte)
- 3 bytes padding
- `requests int64` at offset 4 (NOT 8-byte aligned!)
- `errors int64` at offset 12 (NOT 8-byte aligned!)

**Fix:** Put 8-byte atomic fields as the first struct fields:

```go
type Stats struct {
    requests  int64  // First field = guaranteed 8-byte aligned
    errors    int64
    active    bool
}
```

Or use `atomic.Int64` (Go 1.19+) which handles alignment internally.

</details>

### Question 6: Using `unsafe` — Structure Size Optimization

**Problem:** How can you use `unsafe.Sizeof` to determine the optimal field order and reduce struct size?

<details>
<summary>🎯 Answer</summary>

```go
import "unsafe"

func AnalyzeStruct[T any]() {
    var v T
    t := reflect.TypeOf(v)
    
    fmt.Printf("Struct %s: %d bytes\n", t.Name(), unsafe.Sizeof(v))
    
    for i := 0; i < t.NumField(); i++ {
        f := t.Field(i)
        fmt.Printf("  %s: offset=%d, size=%d, align=%d\n",
            f.Name,
            f.Offset,
            f.Type.Size(),
            f.Type.Align(),
        )
    }
}

// Rule: Sort fields by alignment requirement descending
// (int64/float64 → float64/int32 → int16 → bool/int8)
type Optimized struct {
    A int64   // 8-byte align, offset 0
    B int32   // 4-byte align, offset 8
    C int16   // 2-byte align, offset 12
    D bool    // 1-byte align, offset 14
    // padding: 1 byte at offset 15 to make struct size multiple of 8
    // Total: 16 bytes
}
```

</details>

### Question 7: Slice Header — Day in the Life

**Problem:** Trace the memory state through this code. What's happening at each step?

```go
func main() {
    s := make([]int, 3, 5)         // Step 1
    s[0], s[1], s[2] = 1, 2, 3    // Step 2
    t := s[:2]                     // Step 3
    t[0] = 99                      // Step 4
    s = append(s, 4)               // Step 5
    t = append(t, 5)               // Step 6 — what happens here?
}
```

<details>
<summary>🎯 Answer</summary>

```
Step 1: s = {Data: 0xc000010400, Len: 3, Cap: 5}
  Underlying array: [_, _, _, _, _]

Step 2: Underlying array: [1, 2, 3, _, _]

Step 3: t = {Data: 0xc000010400, Len: 2, Cap: 5}
  Both s and t share the same underlying array

Step 4: Underlying array: [99, 2, 3, _, _]
  Both s[0] and t[0] see this change

Step 5: s = {Data: 0xc000010400, Len: 4, Cap: 5}
  Underlying array: [99, 2, 3, 4, _]

Step 6: t = append(t, 5)
  t has Cap: 5, Len: 2, so append uses capacity
  Underlying array: [99, 2, 5, 4, _]
  s[2] is now 5 (not 3!) — s and t still share the array!
```

**🔴 KEY INSIGHT:** The slice created by `s[:2]` shares the same underlying array as `s`. Appending to `t` overwrites `s[2]`! This is a common source of subtle bugs.

**Fix:** Use `s[:2:2]` (full slice expression with capacity limit) if you want `t` to have its own independent capacity.

</details>

### Question 8: Method Value Receiver vs Pointer Receiver Escape

**Problem:** Does the code below cause heap allocation? If so, where?

```go
type Logger struct {
    prefix string
}

func (l Logger) Log(msg string) {
    fmt.Println(l.prefix + ": " + msg)
}

func (l *Logger) Error(msg string) {
    fmt.Println(l.prefix + ": ERROR: " + msg)
}

func main() {
    l := Logger{prefix: "app"}
    
    f1 := l.Log    // Method value — value receiver
    f2 := l.Error  // Method value — pointer receiver
    
    f1("hello")
    f2("world")
}
```

<details>
<summary>🎯 Answer</summary>

`f1 := l.Log` — creates a method value. Since `Log` has a value receiver, the compiler must copy `l` into the closure. This causes `l` to escape to heap (the closure captures it). The closure itself is also heap-allocated.

`f2 := l.Error` — creates a method value with pointer receiver. This captures a pointer to `l`. Since `l` already escaped for `f1`, this doesn't cause additional allocation. If `f2` was the only binding, the compiler might still stack-allocate `l` if it could prove `l` doesn't escape through `f2`.

**Lesson:** Method values always escape at least one allocation (the closure). They should be avoided in hot paths.

**Alternative:** Use inline function calls instead of method values in performance-critical code.

</details>

---

## Summary

| Concept | Key Takeaway |
|---------|-------------|
| `&` | Creates pointer to memory location (LEAQ instruction) |
| `*` | Dereferences pointer (reads/writes at address) |
| Pass by value | Everything in Go is pass-by-value — including pointers |
| Escape analysis | Compiler decides stack vs heap — use `-gcflags="-m"` to check |
| Interface nil trap | `(*T)(nil)` != `nil` — interface has type info even when value is nil |
| Memory alignment | Sort struct fields by size descending to minimize padding |
| `unsafe.Pointer` vs `uintptr` | GC tracks `unsafe.Pointer` but NOT `uintptr` |
| Range copies | `for _, v := range slice` copies — use index to mutate |
| Slice sharing | Sub-slices share underlying array — use full slice expr to isolate |
| GC pointers | Every pointer in a struct adds GC scanning work |
