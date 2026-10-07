# ☕ Java — Object Handling, References, Memory & Object Lifecycle

> **Category:** Language Fundamentals — Object Semantics & Memory Model  
> **Target Level:** Staff/Principal Engineer  
> **Why this matters at Staff level:** Leaks from forgotten references, per-object overhead multiplied by millions of objects, and cleanup that depends on the GC are recurring causes of production incidents in JVM services. Knowing what an object really costs and when it really dies lets you size services, read heap dumps and review designs with confidence.
>
> *Current as of October 2026 (JDK 25 LTS, JDK 27). All sizes below were measured with [JOL](https://github.com/openjdk/jol) on JDK 25, 64-bit HotSpot, unless stated otherwise.*

---

## Table of Contents

1. [How Objects Are Stored: Primitives vs References](#1-how-objects-are-stored-primitives-vs-references)
2. [Pass by Value — The Most Misunderstood Concept](#2-pass-by-value-the-most-misunderstood-concept)
3. [Object Layout in Memory](#3-object-layout-in-memory)
4. [Object Creation & Lifecycle](#4-object-creation-lifecycle)
5. [Reference Types: Strong, Soft, Weak, Phantom](#5-reference-types-strong-soft-weak-phantom)
6. [ReferenceQueue & Cleaner — Resource Cleanup](#6-referencequeue-cleaner-resource-cleanup)
7. [Stack vs Heap — What Lives Where](#7-stack-vs-heap-what-lives-where)
8. [String Pool & Interning](#8-string-pool-interning)
9. [Arrays in Memory](#9-arrays-in-memory)
10. [Finalization, Cleaners & Deprecation](#10-finalization-cleaners-deprecation)
11. [Memory Leak Patterns](#11-memory-leak-patterns)
12. [TLABs, PLABs & Allocation Optimizations](#12-tlabs-plabs-allocation-optimizations)
13. [JVM Memory Tuning — Heap & Beyond](#13-jvm-memory-tuning-heap-beyond)
14. [Interview Questions](#14-interview-questions)

> **Note:** This guide complements the [JVM Internals & GC notes](JVM_INTERNALS_NOTES.md), which cover GC algorithms, the JMM happens-before rules, volatile semantics, JIT compilation and ZGC/G1/Shenandoah. This guide focuses on individual objects: their size, their references, and their lifecycle.

!!! tip "30-second summary"
    Every object lives on the heap and is reached through references, which Java passes **by value**. On a typical 64-bit JVM an object costs a **12-byte header** (8 with compact object headers, the default from JDK 27) plus fields, rounded up to 8 bytes; references are 4 bytes with compressed oops (heaps under ~32 GB). An object stays alive while it is **strongly reachable** from a GC root; soft, weak and phantom references let you observe or cache objects without keeping them alive. Clean up resources deterministically with **try-with-resources**; `Cleaner` is only a safety net and `finalize()` is deprecated for removal. Most "leaks" are reachable-but-unwanted objects: unbounded caches, listeners, `ThreadLocal`s on pooled threads, and class loaders pinned by a single reference.

---

## 1. How Objects Are Stored: Primitives vs References

### The Two Worlds

```java
// PRIMITIVES: the variable holds the value itself
int x = 42;            // local: one 32-bit slot in the frame
boolean b = true;      // local: also one slot (the JVM has no smaller local type);
                       // as a FIELD a boolean takes 1 byte
long l = 100000L;      // local: two slots (long/double are "category 2")

// OBJECTS: the variable holds a REFERENCE; the object is on the heap
String s = new String("hello");
// local s: a reference (4 bytes with compressed oops, else 8)
// heap:    String object (24 B) + its byte[] (24 B) = 48 B for "hello"
//          (compact strings, JDK 9+: Latin-1 text uses 1 byte per char)

// ARRAYS are objects too
int[] arr = new int[100];
// heap: 16 B header (12 B object header + 4 B length) + 100 * 4 B = 416 B
```

**Key insight:** every object and array created with `new` is, semantically, on the heap. A *variable* lives wherever its declaration says: locals in the thread's stack frame, instance fields inside their object, static fields in the class's `Class` mirror object (also on the heap since JDK 8). The JIT may avoid allocating an object that never escapes a compiled method (scalar replacement, see [section 7](#7-stack-vs-heap-what-lives-where)), but you can't observe that difference from Java code.

### The Reference Variable — What It Actually Holds

```java
// HotSpot reference ("oop") sizes:
//
// 1. COMPRESSED OOPS (default when the max heap is below ~32 GB):
//    - 4-byte references
//    - decode: address = heap_base + (narrow_oop << 3)
//      (objects are 8-byte aligned, so the low 3 bits are always 0: 2^32 * 8 = 32 GB)
//    - "zero-based" mode (heap_base = 0, no add) when the heap fits below 32 GB of
//      virtual address space; JVM picks the mode at startup (-Xlog:gc+init shows it)
//    - -XX:ObjectAlignmentInBytes=16 stretches compressed oops to 64 GB, at the cost
//      of more padding per object
//
// 2. UNCOMPRESSED (-Xmx of ~32 GB or more, or -XX:-UseCompressedOops, or ZGC):
//    - 8-byte references
//    - The cliff: a 32 GB heap with 8-byte references can hold LESS data than a
//      31 GB heap with 4-byte ones. Stay just under the threshold, or go well past it.
//
// COMPRESSED CLASS POINTERS (-XX:+UseCompressedClassPointers, default on):
// the header's class pointer is 4 bytes, pointing into the compressed class space
// (part of Metaspace). This is independent of compressed oops; ZGC uses
// compressed class pointers but not compressed oops.
```

### Default Values for References

```java
private String name;    // null (every reference field)
private int age;        // 0
private boolean flag;   // false
private double value;   // 0.0
// Fields and array elements get default values. LOCAL variables do not: the
// compiler rejects reading a local before it is definitely assigned.
// Dereferencing null throws NullPointerException; since JDK 14 (JEP 358) the
// message names the null expression, e.g. 'Cannot invoke "String.length()"
// because "user.name" is null'.
```

---

## 2. Pass by Value — The Most Misunderstood Concept

### Java is ALWAYS Pass-by-Value

```java
// ── PRIMITIVES: the value is copied ─────────────────────────
void increment(int x) {
    x = x + 1;  // modifies only the copy
}

int a = 5;
increment(a);
System.out.println(a);  // 5

// ── OBJECTS: the REFERENCE is copied, not the object ────────
void changeName(User user) {
    user.setName("New Name");          // mutates the SAME object the caller sees
}

void reassign(User user) {
    user = new User("Different");      // re-points only the local copy
}

User u = new User("Original");
changeName(u);
System.out.println(u.getName());  // "New Name" (the shared object was mutated)

reassign(u);
System.out.println(u.getName());  // still "New Name" (caller's variable untouched)
```

**The classic diagram:**

```
Before calling changeName(u):        After calling changeName(u):

Stack:                               Stack:
  u    = [0x1000]                      u    = [0x1000]   ← same reference
  user = [0x1000] (copy)               user = (gone: the frame was popped)

Heap:                                Heap:
  [0x1000] User{name="Original"}       [0x1000] User{name="New Name"}  ← mutated
```

### Mutability vs Reference Assignment

```java
// ── IMMUTABLE objects (String, Integer, BigDecimal, records of immutables) ──
String s = "hello";
appendExclamation(s);
System.out.println(s);  // "hello"

static void appendExclamation(String str) {
    str = str + "!";  // creates a NEW String and re-points the local copy
}

// ── MUTABLE objects (StringBuilder, ArrayList, most domain classes) ──
StringBuilder sb = new StringBuilder("hello");
appendExclamation(sb);
System.out.println(sb);  // "hello!"

static void appendExclamation(StringBuilder sb) {
    sb.append("!");  // mutates the shared object
}
```

**Staff-level insight:** "objects are passed by reference" is the wrong mental model: Java passes *references by value*. The practical consequences are about **aliasing**: a method that receives your `List` can mutate it, and a class that stores a caller's mutable array or collection shares it with the caller. Defensive copies (`List.copyOf`, `array.clone()`) and immutable types (records with immutable components) are how you control that.

---

## 3. Object Layout in Memory

### HotSpot Object Header (64-bit JVM)

```java
// Default layout (JDK 25; compressed class pointers on):
//
// ┌──────────────────────────────────────────────────────────┐
// │ OBJECT HEADER: 12 bytes                                  │
// │   mark word     8 bytes                                  │
// │   class pointer 4 bytes (compressed Klass* into class space)
// ├──────────────────────────────────────────────────────────┤
// │ INSTANCE DATA                                            │
// │   superclass fields first, then subclass fields; within  │
// │   each class the JVM orders fields to minimize padding   │
// ├──────────────────────────────────────────────────────────┤
// │ PADDING up to a multiple of 8 bytes                      │
// └──────────────────────────────────────────────────────────┘
// Arrays add a 4-byte length field after the header.
// new Object() = 16 bytes: 12 header + 4 padding.
//
// COMPACT OBJECT HEADERS (JEP 450 experimental in 24, JEP 519 product in 25 with
// -XX:+UseCompactObjectHeaders, JEP 534 ON BY DEFAULT in JDK 27):
// the class pointer is squeezed into the mark word → an 8-byte header.
// new Object() = 8 bytes. Objects with a few fields typically shrink by 4-8 bytes;
// object-heavy heaps shrink by roughly 10-20%.

// ── MARK WORD (legacy 64-bit layout) ──────────────────────
// unlocked:  | unused:25 | identity hash:31 | unused:1 | age:4 | unused:1 | lock:2 |
// lock bits: 01 unlocked, 00 lightweight-locked, 10 inflated monitor, 11 GC-marked
//            (forwarding pointer during evacuation)
// The former "biased" bit is unused: biased locking was disabled by default in
// JDK 15 (JEP 374) and removed in JDK 18.
//
// ── MARK WORD (compact headers) ───────────────────────────
// | class pointer:22 | identity hash:31 | reserved:4 | age:4 | self-fwd:1 | lock:2 |
//
// The mark word holds, depending on state:
// - the identity hash (computed lazily on first Object.hashCode /
//   System.identityHashCode, then stored)
// - the GC age (4 bits → MaxTenuringThreshold can't exceed 15)
// - lock state
// - a forwarding pointer while the GC is moving the object

// ── CLASS POINTER ──────────────────────────────────────────
// Points to the Klass in Metaspace: field layout, vtable/itable, superclass chain,
// and a pointer back to the java.lang.Class mirror on the heap.
```

### Field Ordering & Alignment

The JVM, not the source order, decides field offsets. Since JDK 15 the field-layout algorithm packs fields largest-first, fills gaps (including the 4-byte gap after a 12-byte header) with smaller fields, and places references together:

```java
class Misordered {
    boolean flag;
    int count;
    String name;
    long id;
}
// JOL, JDK 25, compressed oops + class pointers (12-byte header):
// OFF  SZ  TYPE     FIELD
//   0   8           mark word
//   8   4           class pointer
//  12   4  int      count      ← fills the gap after the header
//  16   8  long     id
//  24   1  boolean  flag
//  25   3           (gap)
//  28   4  String   name
// Instance size: 32 bytes
//
// With -XX:+UseCompactObjectHeaders (8-byte header):
//   8: long id, 16: int count, 20: boolean flag, 24: String name → 32 bytes
//   (4 bytes of tail padding instead of 4 saved: the total didn't change here)

// Inheritance: superclass fields come first and are never interleaved with
// subclass fields, but a subclass can fill the superclass's trailing gaps.
class Parent { int parentField; }
class Child extends Parent { boolean childFlag; int childCount; }
// JOL: 12 parentField (int), 16 childCount (int), 20 childFlag → 24 bytes
//      (compact headers: 8, 12, 16 → 24 bytes)
```

**Why it matters:** field order affects size only through padding, but it matters for **false sharing**: two hot fields written by different threads can land on the same 64-byte cache line. The JDK uses `@jdk.internal.vm.annotation.Contended` (usable outside the JDK only with `--add-exports` and `-XX:-RestrictContended`); libraries such as JCTools and Disruptor pad manually.

### Object Size Calculation Rules of Thumb

| Object (JDK 25, compressed oops) | Size | With compact headers |
|-----------------------------------|------|----------------------|
| `new Object()` | 16 B | 8 B |
| `Integer` / `Long` | 16 B / 24 B | 16 B / 16 B |
| `String` object alone (fields: `byte[] value`, `int hash`, `byte coder`, `boolean hashIsZero`) | 24 B | 24 B |
| `"hello"` (String + `byte[5]`, Latin-1) | 48 B | 48 B |
| 10-char Latin-1 String | 56 B | 48 B |
| `HashMap.Node` / `ConcurrentHashMap.Node` | 32 B | 24 B |
| `Object[10]` | 56 B | 56 B |

Rules: header (12, or 8 compact) + fields (8 for `long`/`double`, 4 for `int`/`float`/references, 2 for `short`/`char`, 1 for `byte`/`boolean`) + padding to a multiple of 8. Then add everything the object references: **deep size** is what matters for capacity planning.

```java
// ── JOL (Java Object Layout) ─────────────────────────────────
// CLI:     java -jar jol-cli.jar internals java.lang.String
// Library: org.openjdk.jol:jol-core
//   ClassLayout.parseInstance(obj).toPrintable()   // shallow layout
//   GraphLayout.parseInstance(obj).totalSize()     // deep size of the object graph
//
// java.lang.Object object internals:
// OFF  SZ   TYPE DESCRIPTION               VALUE
//   0   8        (object header: mark)     0x0000000000000001 (non-biasable; age: 0)
//   8   4        (object header: class)    0x00000ce8
//  12   4        (object alignment gap)
// Instance size: 16 bytes
// Space losses: 0 bytes internal + 4 bytes external = 4 bytes total
//
// For a running service, a class histogram is usually more useful:
// jcmd <pid> GC.class_histogram | head -20
```

---

## 4. Object Creation & Lifecycle

### Complete Lifecycle of a Java Object

```java
// PHASE 1: CLASS LOADING AND INITIALIZATION (first active use of the class only)
// → loaded, verified, prepared (static fields zeroed), resolved lazily
// → <clinit> runs (static initializers), once, under the class-init lock

// PHASE 2: ALLOCATION AND CONSTRUCTION
MyObject obj = new MyObject("test", 42);

// Bytecode:
//  0: new           #2    // allocate an UNINITIALIZED MyObject on the heap
//  3: dup                 // keep a copy of the reference for after <init>
//  4: ldc           #3    // "test"
//  6: bipush        42
//  8: invokespecial #4    // MyObject.<init>(String, int): the constructor
// 11: astore_1            // store the reference in local 1
//
// What `new` does:
// 1. Size is known from the class's field layout
// 2. Allocate: bump the pointer in this thread's TLAB (no lock); if the TLAB is
//    too small, take a new TLAB from Eden or allocate directly in Eden (CAS);
//    if Eden is full, run a young GC and retry; very large objects may go
//    elsewhere (e.g. G1 humongous regions)
// 3. Zero the memory (fields get 0/null/false) and write the header:
//    mark word = unlocked, no hash, age 0; class pointer = MyObject
//    (header and zeroing are done by `new`, NOT by the constructor)
// Then invokespecial <init> runs the constructor:
//    - explicit or implicit super(...) call first (up to Object)
//      (JDK 25, JEP 513: statements that don't touch `this` may come before super(...))
//    - instance field initializers and initializer blocks, in source order
//    - the rest of the constructor body
//    - at the end, final fields are "frozen" (JMM initialization safety)

// PHASE 3: USE
obj.doSomething();  // virtual dispatch via the vtable (itable for interfaces),
                    // usually devirtualized and inlined by the JIT

// PHASE 4: UNREACHABLE
obj = null;  // unreachable once NO strong path from any GC root remains.
// Note: the JIT may consider a local dead after its LAST USE, even before the
// method returns or the variable is nulled; nulling locals is almost never needed.

// PHASE 5: COLLECTION
// The next GC that covers the object's region/generation doesn't mark it, so its
// memory is reclaimed: by copying survivors elsewhere (young GC, G1, ZGC) or by
// compaction. The object isn't "deleted" individually; there's no per-object work
// for dead objects in a copying collector.
// - Soft/Weak/Phantom references to it are cleared and enqueued as applicable
// - If its class overrides finalize() (deprecated), it is kept alive one more
//   cycle so the Finalizer thread can run finalize()
// - Registered Cleaner actions run on the Cleaner thread afterwards
```

### Constructor Safety with `this` Escape

```java
// 🔴 DANGEROUS: publishing 'this' during construction
public class UnsafePublish {
    static UnsafePublish instance;
    private final int value;

    public UnsafePublish(int value) {
        instance = this;      // 'this' escapes before the constructor finishes
        this.value = value;
    }
    // Another thread reading instance.value may see 0: the final-field guarantee
    // only applies to references obtained AFTER the constructor completes.
}

// 🔴 Same problem, more common in real code:
public class ListenerRegistrar implements Listener {
    private final Map<String, Handler> handlers = new HashMap<>();

    public ListenerRegistrar(EventBus bus) {
        bus.register(this);   // the bus can call onEvent() from another thread
                              // before `handlers` is assigned
    }
}
// Starting a thread in a constructor, or calling an overridable method from it,
// leaks `this` the same way (a subclass override runs before the subclass's
// fields are initialized).

// ✅ Safe patterns:
// 1. Static factory: construct fully, then publish
public static ListenerRegistrar create(EventBus bus) {
    ListenerRegistrar r = new ListenerRegistrar();
    bus.register(r);          // `r` is fully constructed here
    return r;
}
// 2. Separate lifecycle methods (start()/init()), which is what DI containers do
//    with @PostConstruct / SmartLifecycle.
```

---

## 5. Reference Types: Strong, Soft, Weak, Phantom

!!! tip "30-second answer"
    Reachability decides when an object can be collected: **strong** (normal references) keeps it alive; **soft** lets the GC clear it under memory pressure, and guarantees clearing before an `OutOfMemoryError`; **weak** is cleared at the first GC that finds the object only weakly reachable; **phantom** never gives the object back and is used to learn that an object is gone so you can release *external* resources. Soft references make poor caches in practice; use a bounded cache (Caffeine). Weak references power `WeakHashMap` and `ThreadLocalMap` keys, and are a common source of surprising behaviour.

### Reference Hierarchy

```java
//   java.lang.ref.Reference<T>  (abstract)
//       │
//       ├── SoftReference<T>    — cleared at the GC's discretion under memory pressure
//       ├── WeakReference<T>    — cleared when the referent is only weakly reachable
//       └── PhantomReference<T> — get() always returns null; for post-mortem cleanup
//
// Any of them can be registered with a ReferenceQueue: after the GC clears the
// reference, the Reference object itself is enqueued so your code can react.
// The Reference object must itself stay strongly reachable (e.g. in a set),
// or it is collected and never enqueued.
```

### Strong References — The Default

```java
String s = "hello";                       // strong
List<String> list = new ArrayList<>();   // strong

// An object reachable through a chain of strong references from a GC root is
// never collected, even if that means OutOfMemoryError.
// It becomes collectable once no such chain exists: the referencing variables go
// out of scope (or die early, see below), are overwritten, or the objects holding
// them become unreachable themselves. Cycles of objects that reference each other
// are collected fine once the whole cycle is unreachable (tracing GC, not refcounting).
```

### SoftReference — Memory-Sensitive Cache

```java
import java.lang.ref.SoftReference;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

// Soft references:
// - are cleared only when the GC decides memory is needed
// - are ALL guaranteed to be cleared before the JVM throws OutOfMemoryError
// - recently used ones are kept longer (see the policy below)

public class SoftCache<K, V> {
    private final Map<K, SoftReference<V>> cache = new ConcurrentHashMap<>();

    public V get(K key) {
        SoftReference<V> ref = cache.get(key);
        if (ref == null) return null;
        V value = ref.get();                 // null if the GC cleared it
        if (value == null) cache.remove(key, ref);   // drop the stale entry
        return value;
    }

    public void put(K key, V value) {
        cache.put(key, new SoftReference<>(value));
    }
}

// HotSpot's policy (-XX:SoftRefLRUPolicyMSPerMB=1000, the default):
// a softly reachable object is kept if it was accessed (get() called) within the
// last  (free heap in MB × 1000) milliseconds; otherwise it may be cleared.
// More free heap → soft references live longer.
//
// WHY SOFT CACHES DISAPPOINT IN PRODUCTION:
// - Eviction is driven by GC heuristics, not by your hit rate or size budget
// - Under pressure the GC clears many entries at once: a cache-miss storm exactly
//   when the system is already struggling
// - Lots of soft references keep the heap full, so GCs run more often and longer
// Prefer a bounded cache with explicit size/time limits (Caffeine).
```

### WeakReference — Automatically Cleared on GC

```java
import java.lang.ref.WeakReference;

// A weak reference is cleared by the first GC that finds the referent only weakly
// reachable. Note: a young GC only examines young objects, so a weakly reachable
// OLD object is cleared at the next old/mixed/full collection, not necessarily at
// the next GC.

// Use case 1: WeakHashMap — attach metadata to objects you don't own
public class Metadata {
    private final Map<Object, Info> info =
        Collections.synchronizedMap(new WeakHashMap<>());   // WeakHashMap isn't thread-safe
    // Entry disappears once the KEY is no longer strongly reachable elsewhere.
    // Gotchas:
    // - Keys are compared with equals(); for a canonical/identity map use identity
    //   semantics deliberately.
    // - VALUES are strongly held: if a value references its own key, the entry
    //   can never be cleared (a classic WeakHashMap leak).
    // - String literals and small boxed Integers are effectively never collected
    //   (interned / cached), so they're useless as weak keys.
}

// Use case 2: ThreadLocal internals
// Each Thread has a ThreadLocalMap whose entries have a WEAK key (the ThreadLocal
// object) and a STRONG value. If the ThreadLocal object becomes unreachable, its
// key is cleared, but the value stays until some later get/set/remove on that
// thread's map happens to expunge the stale entry, or the thread dies.

// Use case 3: listeners that shouldn't keep their owners alive
public class WeakListeners {
    private final List<WeakReference<EventListener>> listeners = new CopyOnWriteArrayList<>();

    public void register(EventListener listener) {
        listeners.add(new WeakReference<>(listener));
    }

    public void fire(Event event) {
        for (WeakReference<EventListener> ref : listeners) {
            EventListener l = ref.get();
            if (l != null) l.onEvent(event);
        }
        listeners.removeIf(ref -> ref.get() == null);
    }
}
// GOTCHA: register(e -> handle(e)) with a lambda that nobody else references:
// the lambda object is only weakly reachable and vanishes at the next GC, so the
// listener silently stops firing. Weak listeners need the caller to hold a strong
// reference for as long as it wants events.
```

### PhantomReference — Post-Mortem Cleanup

```java
import java.lang.ref.PhantomReference;
import java.lang.ref.Reference;
import java.lang.ref.ReferenceQueue;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

// PhantomReference:
// - get() ALWAYS returns null: you can never resurrect the referent
// - enqueued after the referent becomes phantom reachable (no strong, soft or weak
//   path left, and finalization, if any, has run)
// - since JDK 9, cleared automatically when enqueued, like soft and weak refs
//   (before JDK 9 the referent's memory was retained until you called clear())
// - only useful with a ReferenceQueue
// You rarely need this directly: java.lang.ref.Cleaner is this pattern, done right.

public final class ResourceCleaner {
    private static final ReferenceQueue<Object> QUEUE = new ReferenceQueue<>();
    // Holds the PhantomReference objects strongly (or they'd never be enqueued)
    private static final Map<Reference<?>, Runnable> ACTIONS = new ConcurrentHashMap<>();

    static {
        Thread t = new Thread(() -> {
            while (true) {
                try {
                    Reference<?> ref = QUEUE.remove();          // blocks
                    Runnable action = ACTIONS.remove(ref);
                    if (action != null) action.run();           // release the external resource
                } catch (InterruptedException e) {
                    return;
                } catch (Throwable t2) {
                    t2.printStackTrace();                        // keep the cleaner thread alive
                }
            }
        }, "phantom-cleaner");
        t.setDaemon(true);
        t.start();
    }

    /** cleanupAction must not reference `obj`, or obj can never become phantom reachable. */
    public static void track(Object obj, Runnable cleanupAction) {
        ACTIONS.put(new PhantomReference<>(obj, QUEUE), cleanupAction);
    }
}
```

### Reference Type Decision Matrix

| Type | `get()` returns | Cleared when | Use case |
|------|----------------|--------------|----------|
| **Strong** | The object | Never while strongly reachable | Normal variables and fields |
| **Soft** | Object or `null` | At the GC's discretion under memory pressure; all before an OOME | Rarely the right cache (prefer bounded caches) |
| **Weak** | Object or `null` | At the first GC (covering the referent) that finds it only weakly reachable | `WeakHashMap` metadata, canonicalizing maps, `ThreadLocalMap` keys |
| **Phantom** | Always `null` | After the object is unreachable (and finalized, if applicable); auto-cleared since JDK 9 | Releasing native/external resources (via `Cleaner`) |

---

## 6. ReferenceQueue & Cleaner — Resource Cleanup

### ReferenceQueue — Polling Reference Events

```java
import java.lang.ref.*;

public class RQ {
    public static void main(String[] args) throws Exception {
        ReferenceQueue<Object> queue = new ReferenceQueue<>();
        Object obj = new Object();
        WeakReference<Object> ref = new WeakReference<>(obj, queue);
        System.out.println(ref.get() != null);       // true
        obj = null;                                   // drop the only strong reference
        System.gc();                                  // a request, not a guarantee
        Reference<?> polled = queue.remove(1000);     // wait up to 1 s for the enqueue
        System.out.println(polled == ref);            // true: the Reference object is enqueued
        System.out.println(ref.get());                // null: already cleared
    }
}
// Output on JDK 25:
// true
// true
// null
//
// queue.poll() is non-blocking; queue.remove() blocks; remove(timeout) waits up to
// the timeout. Enqueuing happens on the JVM's Reference Handler thread shortly
// after the GC, so don't assume it's immediate.
```

**Detecting memory pressure:** don't build this out of soft-reference queues. Use what the JVM already exposes: `MemoryPoolMXBean` usage/collection-usage thresholds with JMX notifications, GC pause and heap-after-GC metrics from Micrometer (`jvm.gc.pause`, `jvm.memory.used`), JFR (`jdk.GCHeapSummary`), and container memory metrics.

### Cleaner (Java 9+ — Replacing `finalize()`)

```java
import java.lang.ref.Cleaner;

// Cleaner = PhantomReference + a daemon thread + a registration API.

public class NativeConnection implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();   // share one per library

    // State needed for cleanup. Must NOT reference the NativeConnection:
    // a static nested class (or record), never an inner class or a lambda that
    // captures `this`, or the object stays reachable forever and is never cleaned.
    private static final class State implements Runnable {
        private final long handle;
        State(long handle) { this.handle = handle; }
        @Override public void run() { nativeClose(handle); }   // runs at most once
    }

    private final State state;
    private final Cleaner.Cleanable cleanable;

    public NativeConnection(String url) {
        this.state = new State(nativeConnect(url));
        this.cleanable = CLEANER.register(this, state);   // safety net if close() is forgotten
    }

    public void query(String sql) { /* use state.handle */ }

    @Override
    public void close() {
        cleanable.clean();      // deterministic path: runs State.run() now, once
    }

    private static native long nativeConnect(String url);
    private static native void nativeClose(long handle);
}

// try (NativeConnection c = new NativeConnection("db://...")) {
//     c.query("SELECT 1");
// }   // close() → cleanup runs now
//
// If close() is forgotten, cleanup runs some time after a GC finds the object
// unreachable, on the Cleaner's thread. Log it in that case: a forgotten close()
// is a bug, and the Cleaner is only a backstop.
//
// SUBTLETY: while a method like query() is still running, the JIT may consider
// `this` unreachable after its last use of a field, so the Cleaner could run
// mid-call. Code that passes the native handle around should end with
// Reference.reachabilityFence(this) (JDK 9+).
// For native memory, the FFM API's Arena (JDK 22+) is usually simpler:
// try (Arena arena = Arena.ofConfined()) { MemorySegment seg = arena.allocate(1024); ... }
```

---

## 7. Stack vs Heap — What Lives Where

### What Lives on the Stack

```java
// Each platform thread has its own stack: -Xss / ThreadStackSize, default 1 MB on
// Linux x64 (2 MB on macOS/AArch64). It's reserved address space; only touched
// pages use RAM. Virtual threads keep their frames in heap objects while unmounted.

// IN A STACK FRAME:
// 1. Local variables of primitive type
//      int x = 42;           → slot holds 42
// 2. Local variables of reference type: the REFERENCE, not the object
//      String s = "hello";   → slot holds a reference to a heap String
// 3. The operand stack (bytecode's scratch space) and frame bookkeeping
//    (return address, link to the caller's frame, pointer to the method's
//    constant pool)
// 4. In JIT-compiled code: register spills and whatever the compiler chose to
//    keep there, including fields of scalar-replaced objects

// NOT ON THE STACK:
// - Objects and arrays: on the heap
// - Instance fields: inside their object, on the heap
// - Static fields: inside the class's java.lang.Class mirror object, on the heap
//   (since JDK 8; before that, in PermGen)
// - Class metadata and bytecode: Metaspace (native memory)

// Frame size: max_locals slots (1 slot per int/float/reference, 2 per long/double)
// plus max_stack for the operand stack, both computed by javac and stored in the
// method's Code attribute.
```

### Escape Analysis — Stack Allocation

```java
// C2's escape analysis classifies each allocation:
//   NoEscape  : never leaves the compiled method (after inlining)
//   ArgEscape : passed to a callee that doesn't store it, but isn't inlined
//   GlobalEscape: stored in a field/static/array, returned, or thrown
//
// For NoEscape objects C2 performs SCALAR REPLACEMENT: the object is never
// allocated and its fields become locals (registers). HotSpot does NOT allocate
// whole objects on the stack; "stack allocation" in interviews usually means
// scalar replacement. Locks on NoEscape/ArgEscape objects can be elided.

// What you write:
public long sum(int[] values) {
    Point p = new Point(0, 0);
    for (int v : values) {
        p.x += v;
        p.y += v;
    }
    return p.x + p.y;
}

// What C2 effectively compiles (scalar replacement):
public long sum(int[] values) {
    int x = 0, y = 0;
    for (int v : values) {
        x += v;
        y += v;
    }
    return x + y;
}
// A measured demo (allocation drops from ~305 MB to ~0 MB for 10M iterations) is
// in the JVM notes: JVM_INTERNALS_NOTES.md#allocation-tlabs-and-escape-analysis

// When does it fail?
// 1. The object is returned, thrown, or stored in a field, static or array
// 2. It's passed to a method that isn't inlined (too big, megamorphic, native,
//    or the call is in a cold path) → at best ArgEscape: still allocated
// 3. Control-flow merges where the reference could be one of several objects
// 4. Large arrays (EliminateAllocationArraySizeLimit=64 elements)
// 5. The method isn't C2-compiled yet (interpreter and C1 always allocate)

// Checking: -XX:+PrintEscapeAnalysis / -XX:+PrintEliminateAllocations exist only
// in debug builds of the JVM. In release builds, measure allocation instead:
// JMH with -prof gc (B/op), JFR jdk.ObjectAllocationSample, or
// ThreadMXBean.getCurrentThreadAllocatedBytes() around the code.
```

### Thread-Local Allocation Buffers (TLABs)

```java
// TLAB = a per-thread chunk of Eden in which that thread allocates without locks.
//
// [Thread 1 TLAB][Thread 2 TLAB][Thread 3 TLAB][ ...  free Eden ... ]
//        ↑              ↑             ↑
//    bump pointer   bump pointer  bump pointer
//
// In TLAB: compare against the TLAB end, bump the pointer: a handful of
// instructions, no atomic operation.
// TLAB refill / allocation outside a TLAB: an atomic CAS on the shared Eden top,
// or a slow-path call into the runtime: much slower, and contended if many
// threads do it at once.
//
// Flags (rarely worth touching; the defaults resize TLABs adaptively per thread):
// -XX:+UseTLAB                    (default on)
// -XX:+ResizeTLAB                 (default on: size from each thread's allocation rate)
// -XX:TLABSize=<n>                (initial size; 0 = adaptive)
// -XX:TLABWasteTargetPercent=1    (percentage of Eden that TLAB waste may use)
// -XX:TLABRefillWasteFraction=64  (if more than 1/64 of the TLAB is still free,
//                                  allocate a too-big object outside it instead of
//                                  throwing the rest of the TLAB away)
//
// Large objects:
// - Serial GC: -XX:PretenureSizeThreshold=<n> sends objects above n bytes straight
//   to the old generation (0 = off, the default). Parallel GC ignores it.
// - G1: objects >= half a region are "humongous" and go straight to dedicated
//   old regions. ZGC: large objects get their own page.
```

---

## 8. String Pool & Interning

### String Literals vs `new String()`

```java
// Literals (and compile-time constant expressions) are interned: one String
// object per distinct value, shared JVM-wide
String s1 = "hello";
String s2 = "hello";
System.out.println(s1 == s2);          // true

// new String(...) always creates a new object
String s3 = new String("hello");
String s4 = new String("hello");
System.out.println(s3 == s4);          // false
System.out.println(s3.equals(s4));     // true

// intern() returns the canonical instance
String s5 = s3.intern();
System.out.println(s1 == s5);          // true

// Compile-time constants are folded and interned; runtime concatenation is not:
final String a = "hel";
String b = "hel";
System.out.println((a + "lo") == s1);  // true  (constant expression)
System.out.println((b + "lo") == s1);  // false (computed at runtime)
// Never compare strings with == in application code; this is interview trivia.
```

### String Pool Memory

```java
// Location:
// - JDK 7+: the String objects are ordinary heap objects; the pool itself is a
//   native hash table (StringTable) of weak references to them
// - Interned strings with no other references are collected (the table is weak)
// - Before JDK 7 the pool lived in PermGen and was a common source of
//   "OutOfMemoryError: PermGen space"
//
// Table size: -XX:StringTableSize (default 65,536 buckets in JDK 25). Since JDK 11
// the table is a concurrent hash table that resizes itself, so the old advice
// ("pick a large prime") is obsolete. Inspect with:
//   jcmd <pid> VM.stringtable        (or -Xlog:stringtable)
//
// Memory per string (compact strings, JDK 9+):
//   "hello" (Latin-1): String 24 B + byte[5] 24 B (16 B header + 5 B, padded)  = 48 B
//   10 Latin-1 chars:  String 24 B + byte[10] 32 B                             = 56 B
//   Non-Latin-1 text is stored as UTF-16 (2 bytes per char; `coder` = 1)
//   Before JDK 9 a String held a char[] (2 bytes per char, always).
//
// String deduplication (-XX:+UseStringDeduplication):
// - The GC finds Strings with equal contents and makes them share one byte[]
//   (the String objects stay distinct, so == still differs)
// - Introduced for G1 in JDK 8u20; supported by ALL collectors since JDK 18
// - Only considers strings that survived StringDeduplicationAgeThreshold (3) GCs
// - Useful when heap dumps show many duplicate strings (JSON keys, enum-like
//   values, repeated IDs); costs some GC CPU
```

### Common String Memory Pitfall

```java
// 🔴 BAD: += in a loop is O(n²): every iteration copies the whole string so far
String result = "";
for (int i = 0; i < 1000; i++) {
    result += i;   // JDK 9+ compiles + to invokedynamic (StringConcatFactory), but
                   // each iteration still builds a brand-new, longer String
}

// ✅ GOOD: one growing buffer
StringBuilder sb = new StringBuilder(4096);   // pre-size if you can estimate
for (int i = 0; i < 1000; i++) {
    sb.append(i);
}
String result2 = sb.toString();

// ✅ Also fine, when it reads better (internally a StringBuilder too):
String result3 = IntStream.range(0, 1000)
    .mapToObj(Integer::toString)
    .collect(Collectors.joining());

// A single expression like "a" + x + "b" + y is already optimal on JDK 9+; don't
// rewrite it into StringBuilder calls.
```

---

## 9. Arrays in Memory

### Array Object Layout

```java
// ┌──────────────────────────────────────┐
// │ MARK WORD (8 bytes)                  │
// ├──────────────────────────────────────┤
// │ CLASS POINTER (4 bytes compressed)   │  ← absent with compact headers
// ├──────────────────────────────────────┤
// │ LENGTH (4 bytes)                     │
// ├──────────────────────────────────────┤
// │ ELEMENTS (aligned to element size;   │
// │  long/double/8-byte refs to 8)       │
// ├──────────────────────────────────────┤
// │ PADDING to a multiple of 8           │
// └──────────────────────────────────────┘
// Array header: 16 bytes by default (12 header + 4 length).
// Max length: a bit below Integer.MAX_VALUE ("Requested array size exceeds VM limit").

// ── Sizes (JOL, JDK 25) ─────────────────────────────────────
//                          default   compact headers   -XX:-UseCompressedOops
// int[10]                   56 B         56 B               56 B
// long[10]                  96 B         96 B               96 B
// boolean[10]               32 B         24 B               32 B
// Object[10]                56 B         56 B               96 B  (8-byte refs)
// int[9] (flat)             56 B         48 B               56 B
// int[3][3] (outer + 3 rows) 128 B       96 B              136 B
// int[1000]               4016 B       4016 B             4016 B
//
// (With compact headers, element data starts at offset 12 for 4-byte and
//  smaller elements, but 8-byte elements still start at 16.)

// ── Multidimensional arrays are arrays of arrays ─────────
// int[3][3]: outer Object-like array of 3 refs (16 + 12 → 32 B)
//            + 3 separate int[3] (16 + 12 → 32 B each = 96 B) = 128 B
// int[9]:    16 + 36 → 56 B
// The flat layout is less than half the size, is one contiguous block (cache
// friendly), and needs one allocation instead of four. For big matrices, index
// a flat array: a[row * cols + col].
```

### Primitive Arrays vs Collections

```java
// ── Memory (JOL, JDK 25, compressed oops) ─────────────────
// int[1000]:                       4,016 B, one contiguous block
// ArrayList<Integer> with 1000 values outside the Integer cache:
//     ArrayList 24 B + Object[] (16 + 1000*4, after growth possibly larger)
//     + 1000 Integer objects × 16 B
//     ≈ 21 KB measured: about 5x the int[]
// (Integer.valueOf caches -128..127 by default, so small values share objects.)
//
// Access: the int[] is sequential memory the CPU prefetches; the ArrayList
// dereferences a pointer per element, scattered across the heap, and unboxes.
// Iterating a large boxed list is typically several times slower; measure for
// your case.
//
// ✅ Use primitive arrays or primitive collections (fastutil, Eclipse Collections,
// HPPC) for large numeric data, hot paths and memory-constrained services.
// (Project Valhalla's value classes, JEP 401, aim to remove much of this
// boxing overhead; as of October 2026 they are integrated in JDK 28 builds as a
// preview feature, not in any GA release yet.)

// ── VarHandle for array elements (JDK 9+) ──────────────────
import java.lang.invoke.MethodHandles;
import java.lang.invoke.VarHandle;

public class ArrayAccess {
    private static final VarHandle INT_ARRAY = MethodHandles.arrayElementVarHandle(int[].class);

    public void demo() {
        int[] arr = new int[100];
        int val = (int) INT_ARRAY.getVolatile(arr, 42);            // volatile read of arr[42]
        boolean swapped = INT_ARRAY.compareAndSet(arr, 42, 0, 1);  // CAS on arr[42]
        INT_ARRAY.setRelease(arr, 42, 99);                         // release store (publication)
    }
}
// Plain array elements can't be volatile; VarHandles (or AtomicIntegerArray)
// give per-element memory ordering and atomics.
```

---

## 10. Finalization, Cleaners & Deprecation

### The `finalize()` Anti-Pattern

```java
// 🔴 DON'T:
public class Resource {
    private long nativePtr;

    @Override
    @SuppressWarnings("removal")
    protected void finalize() throws Throwable {
        try {
            nativeClose(nativePtr);   // runs whenever (or never)
        } finally {
            super.finalize();
        }
    }
}

// Problems:
// 1. TIMING: runs only after a GC finds the object unreachable, then waits for the
//    Finalizer thread: seconds, hours, or never (no guarantee it runs at exit)
// 2. CONCURRENCY: runs on the Finalizer thread, concurrently with your code, so it
//    needs synchronization like any other cross-thread access
// 3. COST: every finalizable object is registered at allocation, survives at least
//    one extra GC cycle, and is processed by a single thread. If objects become
//    finalizable faster than that thread runs, the queue and heap grow until OOME.
// 4. RESURRECTION: finalize() can store `this` somewhere and revive the object
// 5. EXCEPTIONS thrown by finalize() are silently ignored
// 6. STATUS: deprecated in JDK 9; deprecated FOR REMOVAL in JDK 18 (JEP 421).
//    Still enabled by default in JDK 25; run with --finalization=disabled to
//    find out whether your app (and its libraries) depend on it.
```

### The Cost of Finalization

```java
// Finalization flow:
// 1. Allocation: the JVM registers the object (a Finalizer reference) because its
//    class overrides finalize()
// 2. GC finds it unreachable except through that reference: it is NOT reclaimed;
//    it (and everything it references) is kept alive and queued
// 3. The Finalizer thread (priority MAX_PRIORITY - 2) calls finalize()
// 4. A LATER GC reclaims it, if finalize() didn't resurrect it
//
// → At least one extra GC cycle, often promotion to the old generation
// → One slow finalize() delays every other finalizable object in the JVM
// → Heap dumps full of java.lang.ref.Finalizer instances are the symptom
```

### Safe Resource Management Patterns

```java
// PATTERN 1: try-with-resources (preferred, JDK 7+)
try (BufferedReader br = Files.newBufferedReader(Path.of("/tmp/data.txt"))) {
    String line = br.readLine();
}   // closed on every path; a failing close() is added as a suppressed exception

// PATTERN 2: leak detection with a Cleaner, instead of finalize()
// (Connection pools such as HikariCP use a different technique: a timer that
//  logs a stack trace if a connection isn't returned within leakDetectionThreshold.)
public final class TrackedHandle implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();

    private static final class State implements Runnable {
        private final Throwable allocationSite = new Throwable("allocated here");
        private volatile boolean closed;
        @Override public void run() {
            if (!closed) {
                System.err.println("LEAK: handle was never closed");
                allocationSite.printStackTrace();      // where it was created
            }
            // release the underlying resource here as a last resort
        }
    }

    private final State state = new State();
    private final Cleaner.Cleanable cleanable = CLEANER.register(this, state);

    @Override public void close() {
        state.closed = true;
        cleanable.clean();
    }
}
// Capturing a stack trace per allocation is expensive: enable it only in tests or
// behind a sampling flag (Netty's ResourceLeakDetector samples by default).
```

---

## 11. Memory Leak Patterns

A Java "leak" is memory that is still **reachable** but no longer **needed**. The GC can't help, by definition. The diagnosis is always the same: heap dump → dominator tree / biggest retained sizes → path to GC roots → the reference that shouldn't be there.

### Pattern 1: Static Collection Growth

```java
// 🔴 CLASSIC: an unbounded static cache
public class UserCache {
    private static final Map<String, User> CACHE = new ConcurrentHashMap<>();

    public static User getUser(String id) {
        return CACHE.computeIfAbsent(id, UserCache::loadUser);
    }
    private static User loadUser(String id) { /* DB load */ return null; }
}
// Every distinct id ever seen stays forever → OutOfMemoryError eventually.
// Also: entries go stale with no invalidation.

// ✅ FIX: a bounded cache with a size and/or time limit
// Caffeine.newBuilder().maximumSize(100_000).expireAfterWrite(Duration.ofMinutes(10)).build()
// (Guava's Cache is in maintenance mode; Caffeine is its successor.)
```

### Pattern 2: Forgotten Listeners / Callbacks

```java
// 🔴 Listener registered, never removed
public class EventBus {
    private final List<EventListener> listeners = new CopyOnWriteArrayList<>();
    public void register(EventListener l)   { listeners.add(l); }
    public void unregister(EventListener l) { listeners.remove(l); }   // often forgotten
}
// A long-lived bus keeps every registered listener (and everything it references,
// e.g. a whole screen, request context or session) alive.

// ✅ FIX 1: tie registration to a lifecycle: register returns a handle that is
//           AutoCloseable (Subscription), closed in finally / on shutdown
// ✅ FIX 2: let the framework manage lifecycle (Spring @EventListener beans are
//           registered and removed with the context)
// ✅ FIX 3: weak listeners, with the lambda gotcha from section 5 in mind
```

### Pattern 3: Inner Class Holding Implicit Reference

```java
// 🔴 A non-static inner class (and an anonymous class) holds a hidden reference
// to its enclosing instance
public class ExpensiveService {
    private final byte[] data = new byte[100_000_000];   // 100 MB

    public class Callback implements EventHandler {
        public void onEvent(Event e) { /* doesn't use ExpensiveService at all */ }
    }

    public EventHandler getCallback() {
        return new Callback();   // captures ExpensiveService.this
    }
}

ExpensiveService svc = new ExpensiveService();
EventHandler cb = svc.getCallback();
registry.add(cb);            // cb lives on...
svc = null;                  // ...so the 100 MB service can't be collected

// ✅ FIX: make the nested class static when it doesn't need the outer instance
public static class Callback implements EventHandler { /* ... */ }
// Lambdas capture `this` only if their body uses an instance member, which makes
// them safer than anonymous classes here, but check what they capture.
```

### Pattern 4: ThreadLocal Leaks

```java
// A ThreadLocal value lives as long as the THREAD (or until remove()).
// Pooled platform threads (Tomcat, executors) live for the life of the JVM.

public final class RequestContext {
    private static final ThreadLocal<User> CURRENT_USER = new ThreadLocal<>();
    public static void set(User u) { CURRENT_USER.set(u); }
    public static User get()       { return CURRENT_USER.get(); }
    public static void clear()     { CURRENT_USER.remove(); }
}

// 🔴 BUG: set without remove
void doFilter(Request request, Chain chain) {
    RequestContext.set(authenticate(request));
    chain.doFilter(request);
    // forgot RequestContext.clear()
}
// Consequences:
// 1. CORRECTNESS/SECURITY: the next request on this pooled thread that doesn't set
//    a user sees the PREVIOUS request's user. This is the dangerous part.
// 2. MEMORY: each pool thread retains its last value (bounded by the pool size,
//    but large values add up). Worse in app servers: a ThreadLocal value whose class
//    came from a webapp's class loader pins that whole class loader after redeploy.
// (ThreadLocalMap entries have a weak KEY and a strong VALUE, so the value isn't
//  freed just because the ThreadLocal object became unreachable.)

// ✅ FIX: always clear in finally
void doFilter(Request request, Chain chain) {
    try {
        RequestContext.set(authenticate(request));
        chain.doFilter(request);
    } finally {
        RequestContext.clear();
    }
}
// ✅ JDK 25+: ScopedValue (JEP 506) binds a value for the duration of a call and
// can't leak past it:
// ScopedValue.where(CURRENT_USER, user).run(() -> chain.doFilter(request));
// With a virtual thread per request, ThreadLocals die with the thread, but the
// finally-clear discipline still matters for code that runs on pooled threads.
```

### Pattern 5: String.substring() Memory Leak (Java 6)

```java
// Historical, but still asked: before JDK 7u6, substring() shared the parent's
// char[] (it only stored an offset and count).
String huge = loadHugeString();          // 100 MB
String small = huge.substring(0, 2);
huge = null;
// JDK 6: `small` still pinned the whole 100 MB char[].
// JDK 7u6+: substring() copies the characters it needs → no leak.
// The general lesson survives: VIEWS keep their backing storage alive.
// Modern equivalents: ByteBuffer.slice()/duplicate(), List.subList(), a
// MemorySegment slice, or a small object holding an index into a huge array.
```

### Pattern 6: ClassLoader Leaks

```java
// A class loader (with ALL its classes, their static fields and Metaspace) can be
// unloaded only when nothing references the loader, any of its classes, or any
// instance of them. One stray reference pins everything.
// Typical in: app server redeploys, plugin systems, hot reload, test runners
// creating many class loaders, dynamically generated classes (proxies, scripting).
//
// Common culprits:
// 1. A JVM-wide/static registry holding an object from the app's loader:
//    JDBC DriverManager registrations, JMX MBeans, java.util.logging handlers,
//    shutdown hooks, security providers
// 2. Threads started by the app and never stopped (their context class loader and
//    stack reference the app's classes); also Timer threads and executors
// 3. ThreadLocal values of app classes left on server-owned pooled threads
// 4. Caches in libraries loaded by a PARENT loader keyed by app classes
//    (e.g. java.beans.Introspector, some reflection/serialization caches)
//
// Symptom: OutOfMemoryError: Metaspace (or Compressed class space) after N redeploys.
//
// ✅ Detection (JDK 9+ unified logging; -XX:+TraceClassLoading is gone):
// -Xlog:class+load=info -Xlog:class+unload=info
// jcmd <pid> VM.classloader_stats    (loaders, classes per loader, Metaspace use)
// jcmd <pid> VM.metaspace
// Heap dump: find instances of your webapp's loader class; more than one alive
// after a redeploy means a leak; "path to GC roots" shows who holds it.
```

### Pattern 7: Unclosed Resources

```java
// 🔴 LEAK: file descriptors, sockets, connections
public void processFile(String path) throws IOException {
    FileInputStream fis = new FileInputStream(path);
    // ... never closed
}
// → "Too many open files", exhausted connection pools, native memory growth.
// The heap may look fine: the cost is outside it.

// ✅ try-with-resources:
public void processFile(Path path) throws IOException {
    try (InputStream in = new BufferedInputStream(Files.newInputStream(path))) {
        // process
    }
}
// Watch especially: Files.lines()/Files.list()/Files.walk() return Streams that
// hold an open file handle and must be closed (use them in try-with-resources).
```

### Pattern 8: Unbounded Queues and Buffers

```java
// 🔴 Producers faster than consumers + an unbounded queue = a "leak" with a
// perfectly reasonable heap dump: millions of pending tasks.
ExecutorService pool = Executors.newFixedThreadPool(8);   // unbounded LinkedBlockingQueue
// Same for unbounded in-memory retries, outbox buffers, reactive buffers.
// ✅ Bound every queue and decide what happens when it's full (reject, block,
// shed load). See the executor discussion in the interview questions (Q5).
```

---

## 12. TLABs, PLABs & Allocation Optimizations

### TLAB (Thread-Local Allocation Buffer)

TLAB mechanics are covered in [section 7](#thread-local-allocation-buffers-tlabs). The points that matter in practice:

```java
// - Allocation is cheap: the cost of garbage is paid when objects SURVIVE (copying,
//   promotion, marking), not when they are created. Short-lived objects are
//   nearly free; medium-lived ones (survive a few GCs, then die) are the most
//   expensive kind.
// - A high allocation RATE (MB/s) means more frequent young GCs. Reduce it when GC
//   frequency or allocation stalls (ZGC) matter, guided by an allocation profile.
// - TLAB statistics: -Xlog:gc+tlab=debug (the old -XX:+PrintTLAB is gone).
```

### PLAB (Promotion-Local Allocation Buffer)

```java
// The GC's equivalent of TLABs: each GC worker thread copies surviving objects
// into its own PLAB in the survivor or old space, so parallel workers don't
// contend on a shared pointer during evacuation.
//
// -XX:YoungPLABSize=4096   (words; default 4096)
// -XX:OldPLABSize=1024     (words; default 1024)
// -XX:+ResizePLAB          (default on: G1 and Parallel size PLABs adaptively)
// Almost never tuned by hand; mentioning that PLABs exist is enough in interviews.
```

### Allocation Optimization Checklist

```java
// Measure first (allocation profile), then:
// 1. Pre-size collections and builders when the size is known
//    (new ArrayList<>(n), HashMap.newHashMap(n) on JDK 19+, new StringBuilder(n))
// 2. Avoid boxing in hot paths: primitive streams (IntStream), primitive
//    collections, avoid Map<Long, Long> for big numeric data
// 3. Avoid accidental allocation: varargs calls, String.format/concatenation in
//    logging that's disabled (use parameterized logging), streams over tiny
//    collections in tight loops, exceptions for control flow, iterator objects
// 4. Keep hot methods small so they inline and escape analysis can work
// 5. Reuse buffers for large or expensive objects (byte[] for I/O, direct buffers,
//    encoders) — but don't build general object pools: pooled objects live long,
//    get promoted, need thread-safety, and usually make modern GCs slower
// 6. Use records/immutable objects freely: allocation is cheap and immutability
//    removes defensive copies and synchronization
// 7. Check object layout of very numerous classes (JOL); try compact object
//    headers on JDK 25 (-XX:+UseCompactObjectHeaders, default in JDK 27)
```

### Allocation Profiling

```java
// 1. JFR: jdk.ObjectAllocationSample (JDK 16+), throttled sampling that is ON in the
//    default profile and safe in production:
//    jcmd <pid> JFR.start duration=60s filename=alloc.jfr
//    jfr print --events jdk.ObjectAllocationSample alloc.jfr | head -40
//    jfr view allocation-by-class alloc.jfr        (JDK 21+)
//    (jdk.ObjectAllocationInNewTLAB / OutsideTLAB are older, higher-overhead events,
//     disabled by default.)
//
// 2. async-profiler: asprof -e alloc -d 60 -f alloc.html <pid>
//    (allocation flame graph; samples at TLAB refills, low overhead)
//
// 3. JMH: -prof gc reports bytes allocated per operation (gc.alloc.rate.norm)
//
// 4. Heap composition (what's live, not what's allocated):
//    jcmd <pid> GC.class_histogram, or a heap dump in Eclipse MAT
//
// 5. Native (off-heap) memory: -XX:NativeMemoryTracking=summary and
//    jcmd <pid> VM.native_memory summary
```

---

## 13. JVM Memory Tuning — Heap & Beyond

### Heap Sizing Strategy

```java
// ── KEY PARAMETERS ─────────────────────────────────────────
// -Xms4g -Xmx4g            fixed heap: no resize pauses, memory committed predictably
// -XX:MaxRAMPercentage=75  in containers, size the heap relative to the container
//                          limit (default is only 25%!); leave the rest for
//                          Metaspace, threads, code cache, direct buffers, GC structures
// -XX:InitialRAMPercentage / -XX:MinRAMPercentage   the corresponding minimums
//
// Generation sizing (mostly for Serial/Parallel):
// -XX:NewRatio=2           old:young = 2:1 (young = 1/3 of the heap; the default)
// -XX:NewSize / -XX:MaxNewSize / -Xmn   explicit young-gen size
// -XX:SurvivorRatio=8      Eden:each survivor = 8:1 (each survivor = 1/10 of young)
// -XX:+UseAdaptiveSizePolicy  (Parallel GC, on by default) resizes generations
//                          to meet throughput/pause goals
//
// For G1, DON'T fix the young generation (-Xmn, NewSize, NewRatio): it disables the
// pause-time-driven young sizing that is G1's main control loop. Set
// -XX:MaxGCPauseMillis instead. ZGC sizes generations itself.

// ── TYPICAL STARTING POINTS ────────────────────────────────
// Request/response service (most services):
//   -XX:+UseG1GC (default) -Xms=Xmx sized for live set × ~2-3, or MaxRAMPercentage=70-75
//   -XX:+HeapDumpOnOutOfMemoryError -XX:+ExitOnOutOfMemoryError
//
// Batch / data processing (throughput over latency):
//   -XX:+UseParallelGC, a large young generation (allocation-heavy work dies young)
//
// Latency-sensitive (trading, streaming, large heaps):
//   -XX:+UseZGC -Xms=Xmx with generous headroom, optionally -XX:SoftMaxHeapSize,
//   -XX:+AlwaysPreTouch; watch for allocation stalls rather than tuning threads
//
// Then verify with GC logs under production-like load; change one thing at a time.
```

### Metaspace Tuning

```java
// Metaspace (JDK 8+): class metadata in native memory.
// -XX:MetaspaceSize=<n>        initial high-water mark that TRIGGERS a GC for class
//                              unloading (≈21 MB default); NOT an initial allocation.
//                              Raising it avoids early GCs during startup of big apps.
// -XX:MaxMetaspaceSize=<n>     hard cap (default unlimited). Set it so that a
//                              class-loader leak fails fast with a clear error instead
//                              of eating the container's memory.
// -XX:CompressedClassSpaceSize=1g   size of the compressed class space (default 1 GB),
//                              which holds the Klass structures
// JDK 16 (JEP 387, elastic Metaspace) returns unused Metaspace to the OS more
// readily and reduced fragmentation.
//
// Monitoring:
// jcmd <pid> VM.metaspace
// jstat -gcmetacapacity <pid> 1000
```

### Direct Memory & Native Memory

```java
// Direct buffers (ByteBuffer.allocateDirect, used by NIO, Netty, gRPC, Kafka clients):
// -XX:MaxDirectMemorySize=<n>   default: equal to the max heap size
// The native memory is released only when the small ByteBuffer object on the heap
// is garbage collected (via a Cleaner). A big heap with few GCs can therefore hold
// lots of dead direct buffers; hitting the limit makes the JVM call System.gc()
// and retry before throwing "OutOfMemoryError: Cannot reserve ... bytes of direct
// buffer memory". -XX:+DisableExplicitGC breaks that recovery path.
// Libraries like Netty manage their own pooled direct memory (and have their own limit).
//
// Other native memory consumers:
// - Metaspace and compressed class space
// - Code cache: -XX:ReservedCodeCacheSize (240 MB default with tiered compilation)
// - Thread stacks: -Xss × number of platform threads (reserved; touched pages used)
// - GC data structures: card tables, remembered sets, mark bitmaps
//   (G1 and ZGC can use several % of the heap size)
// - Symbol tables, string table, JIT compiler arenas
// - malloc by native libraries (JNI), plus glibc malloc arena fragmentation
//
// See all of it: -XX:NativeMemoryTracking=summary (small overhead), then
// jcmd <pid> VM.native_memory summary scale=MB
// (NMT doesn't see memory malloc'd by third-party native code.)
```

### When OutOfMemoryError Happens

```java
// OOM messages and what they mean:
//
// 1. OutOfMemoryError: Java heap space
//    → An allocation failed even after a full collection.
//    → Fix: find what's retaining memory (heap dump), or size the heap for the
//      real live set; check for a single huge allocation.
//
// 2. OutOfMemoryError: Metaspace / Compressed class space
//    → Too much class metadata: class-loader leak, or runaway class generation
//      (proxies, lambdas in generated code, scripting engines).
//    → Fix: the leak; raise MaxMetaspaceSize only if the growth is legitimate.
//
// 3. OutOfMemoryError: GC overhead limit exceeded
//    → More than 98% of time in GC (GCTimeLimit) while recovering less than 2% of
//      the heap (GCHeapFreeLimit). Parallel GC historically; G1 gained it recently
//      (JDK 26, backported to 25.0.3 and 21.0.11).
//    → Fix: same as heap space; it's an early warning of the same problem.
//
// 4. OutOfMemoryError: Cannot reserve ... bytes of direct buffer memory
//    → Direct buffer limit reached.
//    → Fix: release/reuse buffers; size MaxDirectMemorySize deliberately.
//
// 5. OutOfMemoryError: unable to create native thread
//    → The OS refused a new thread: ulimit -u / pids cgroup limit, or no memory
//      for another stack.
//    → Fix: fewer threads (bounded pools, or virtual threads), raise the limits.
//
// 6. OutOfMemoryError: Requested array size exceeds VM limit
//    → An array near Integer.MAX_VALUE elements; usually a bug.
//
// 7. NOT an OutOfMemoryError: the container is OOM-KILLED by the kernel (exit code
//    137) while the heap looks healthy. Total process memory (heap + native)
//    exceeded the cgroup limit: lower MaxRAMPercentage, cap Metaspace/direct
//    memory/threads, check NMT.

// Production flags:
// -XX:+HeapDumpOnOutOfMemoryError
// -XX:HeapDumpPath=/dumps/            (a volume with enough space: dump ≈ used heap)
// -XX:+ExitOnOutOfMemoryError         (die fast and let the orchestrator restart,
//                                      instead of limping on in a broken state)
// (-XX:OnOutOfMemoryError="..." runs a command; redundant if you exit anyway.)
```

---

## 14. Interview Questions

### Question 1: Pass by Value Confusion

**Problem:** What does this code print? Explain why.

```java
public class PassByValue {
    public static void main(String[] args) {
        StringBuilder a = new StringBuilder("A");
        StringBuilder b = new StringBuilder("B");

        swap(a, b);
        System.out.println("a = " + a + ", b = " + b);

        StringBuilder x = new StringBuilder("X");
        modify(x);
        System.out.println("x = " + x);
    }

    static void swap(StringBuilder s1, StringBuilder s2) {
        StringBuilder temp = s1;
        s1 = s2;
        s2 = temp;
    }

    static void modify(StringBuilder sb) {
        sb.append("Y");
        sb = new StringBuilder("Z");
    }
}
```

<details>
<summary>🎯 Answer</summary>

```
a = A, b = B
x = XY
```

**Why?**
1. `swap(a, b)` receives copies of the two references. Swapping `s1` and `s2` only swaps the method's local copies; the caller's `a` and `b` still point to the same objects as before.
2. `modify(x)` receives a copy of the reference to the `"X"` builder. `sb.append("Y")` mutates that shared object to `"XY"`. `sb = new StringBuilder("Z")` re-points only the local copy.

**Key insight:** Java is always pass-by-value; for objects, the value passed is the reference. You can't write a `swap` method for references in Java, which is the quickest proof.
</details>

### Question 2: Object Size Estimation

**Problem:** Estimate the memory footprint of this object in HotSpot 64-bit with compressed oops:

```java
public class Employee {
    private long id;           // 8 bytes
    private String name;       // compressed ref: 4 bytes
    private int salary;        // 4 bytes
    private boolean active;    // 1 byte
    private String department; // compressed ref: 4 bytes
}
```

<details>
<summary>🎯 Answer</summary>

**Shallow size: 40 bytes.** JOL on JDK 25 (12-byte header):

```
OFF  SZ  TYPE     FIELD
  0   8           mark word
  8   4           class pointer
 12   4  int      salary       ← fills the gap after the 12-byte header
 16   8  long     id
 24   1  boolean  active
 25   3           (gap)
 28   4  String   name
 32   4  String   department
 36   4           (padding to a multiple of 8)
Instance size: 40 bytes
```

With compact object headers (JDK 25 opt-in, JDK 27 default): 8-byte header, `id` at 8, `salary` at 16, `active` at 20, references at 24 and 28 → **32 bytes**.

**But the real answer is the deep size:** two Strings of, say, 10 Latin-1 chars each add 2 × 56 = 112 bytes, so one Employee costs about 152 bytes, almost 4x its shallow size. For 10 million employees that is ~1.5 GB, and deduplicating `department` (a few distinct values) would save ~0.5 GB. Interviewers want you to reason about the object graph, not just the header.
</details>

### Question 3: WeakReference Gotcha

**Problem:** What does this code print? Why?

```java
WeakReference<String> ref = new WeakReference<>(new String("hello"));
System.gc();
Thread.sleep(100);
System.out.println(ref.get());

String strong = new String("world");
WeakReference<String> ref2 = new WeakReference<>(strong);
System.gc();
Thread.sleep(100);
System.out.println(ref2.get());
```

<details>
<summary>🎯 Answer</summary>

Typical output (verified on JDK 25):

```
null
world
```

**Why?**
1. The `new String("hello")` object is only weakly reachable, so a GC clears it and `ref.get()` returns `null`. (With `"hello"` as a literal instead of `new String(...)`, it would never be cleared: literals are interned and strongly held.)
2. `strong` still refers to the `"world"` object, so it survives.

**Two staff-level caveats:**
- `System.gc()` is only a request (and is ignored with `-XX:+DisableExplicitGC`), so the first line *may* print `hello`.
- `strong` is never used after creating `ref2`. Once the method is JIT-compiled, the JVM may treat `strong` as dead after its last use, so the second line *may* print `null`. The JLS allows it (reachability is about future use, not scope). To guarantee liveness, use `Reference.reachabilityFence(strong)` after the point where the object must stay alive. This matters for real code that uses Cleaners or native handles.
</details>

### Question 4: Object Header and Synchronization

**Problem:** Explain what happens in the mark word of this object at each step:

```java
Object obj = new Object();
synchronized (obj) {
    obj.hashCode();
}
synchronized (obj) {
    // something
}
```

<details>
<summary>🎯 Answer</summary>

On JDK 25 with the default **lightweight locking**:

1. **`new Object()`**: mark word = unlocked (lock bits `01`), no hash yet, age 0.
2. **First `synchronized`**: an uncontended CAS sets the lock bits to `00` (fast-locked) and the object is pushed onto the thread's lock stack. The rest of the mark word, including space for the hash, stays in place.
3. **`obj.hashCode()` inside the block**: the identity hash is generated and stored in the header. With lightweight locking the header isn't displaced, so **no inflation is needed**.
4. **Exit**: lock bits back to `01`; the hash stays in the header for the object's lifetime.
5. **Second `synchronized`**: again a fast CAS lock.

**Verified on JDK 25** with `-Xlog:monitorinflation=trace`: under the default locking mode no monitor is inflated for `obj`; under the legacy mode (`-XX:LockingMode=1`, deprecated since JDK 24) the `hashCode()` call inflates it.

**Why the legacy answer was different:** with the old *stack locking*, locking replaced the mark word with a pointer to a "displaced header" on the locking thread's stack, so there was nowhere to store the hash. Hashing a stack-locked object forced **inflation** to a heavyweight `ObjectMonitor` (which holds the displaced header and hash), and the lock stayed inflated afterwards. That's the classic textbook answer; know both.

**Other things that inflate a lock:** contention (another thread tries to lock), `wait()`/`notify()`, and lock-stack overflow from deep nesting. Biased locking, which this question used to be about, was removed in JDK 18.
</details>

### Question 5: String Pool — Memory Impact

**Problem:** An application reads 1 million unique strings from a file and processes them. Each string is about 10 characters. The strings are compared frequently using `==`. Design a memory-efficient approach. What's the memory impact of interning all strings?

<details>
<summary>🎯 Answer</summary>

**First, push back on `==`:** comparing strings with `==` is only correct if *every* string on both sides is guaranteed to be interned. One un-interned string (from a new code path, a library, deserialization) silently breaks equality. That's a correctness risk you need a very good reason to take.

**Memory without interning** (JDK 9+ compact strings, 10 Latin-1 chars):
- `String` 24 B + `byte[10]` 32 B = **56 B per string → ~56 MB for 1M**.

**With interning, all 1M strings unique:**
- Interning removes *duplicates*. With 1M distinct values there are none, so the strings still take ~56 MB, plus the string table's entries (a few tens of bytes each, ~tens of MB), plus `intern()` CPU cost on every string.
- So: interning unique strings costs memory; it saves memory only when the same values repeat many times.

**Speed:** `==` is a pointer comparison, while `equals()` checks length, coder and then the bytes (vectorized intrinsic). For 10-char strings `equals()` is already very fast, and `String.hashCode()` is cached. The difference rarely matters outside a profiled hot loop.

**Recommendations:**
1. Use `equals()` and normal `HashMap`/`HashSet` lookups.
2. If values repeat heavily (status codes, country names, JSON keys), **deduplicate** with your own map (`map.computeIfAbsent(s, k -> k)`) or turn on `-XX:+UseStringDeduplication` (all collectors since JDK 18), or convert to an `enum`/integer ID at the boundary.
3. If you truly need identity comparison for speed, intern into **your own** canonicalizing map that you control, not the JVM-wide `intern()` table.
4. Don't tune `-XX:StringTableSize` in advance; the table resizes itself since JDK 11. Check `jcmd <pid> VM.stringtable` if interning is heavy.
</details>

### Question 6: TLAB and Allocation

**Problem:** Your application allocates millions of small objects in a tight loop. Allocation used to be cheap; now a profile shows threads spending a lot of time in allocation slow paths. What happened? How do you fix it?

<details>
<summary>🎯 Answer</summary>

**Normal case:** each thread bump-allocates in its own TLAB: a few instructions, no atomics.

**Likely causes of slow-path allocation:**
1. **TLAB refills are frequent**: the allocation rate went up (new code path, bigger payloads) or many threads share a small Eden, so threads keep retiring TLABs and taking new ones from the shared Eden pointer, contending on it.
2. **Objects too large for the TLAB** (big arrays/buffers) are allocated outside it each time; in G1, objects of half a region or more are **humongous** allocations, which are much more expensive and can trigger GCs.
3. **Eden is exhausted**: allocation waits for young GCs. With ZGC, threads may hit **allocation stalls** because collection can't keep up.

**Diagnosis:**
```bash
-Xlog:gc+tlab=debug        # TLAB sizes, refills and waste per thread (JDK 9+)
-Xlog:gc*                  # GC frequency, humongous allocations, allocation stalls
# JFR: jdk.ObjectAllocationSample (where), jdk.ObjectAllocationOutsideTLAB (when enabled)
# async-profiler -e alloc: allocation flame graph
```

**Fixes, in order:**
1. **Reduce allocation** at the hot sites the profile shows (that's almost always the real fix)
2. Avoid humongous objects: reuse large buffers, or raise `G1HeapRegionSize`
3. Give the young generation/heap more room (for G1, more heap or a looser pause goal, not a fixed `-Xmn`)
4. Check that escape analysis still works for the hot method (it may have stopped inlining)
5. Only then consider TLAB flags; HotSpot's adaptive TLAB sizing is usually right
</details>

### Question 7: Stack vs Heap — Escape Analysis

**Problem:** Will the JIT compiler allocate this `Point` on the stack or heap? What about the `List`?

```java
public long processData(int[] values) {
    Point p = new Point(0, 0);
    List<Integer> list = new ArrayList<>(100);

    for (int i = 0; i < values.length; i++) {
        p.x += values[i];
        list.add(values[i] % 10);
    }

    System.out.println(list.size());  // Does this affect escape?
    return p.x + p.y;
}
```

<details>
<summary>🎯 Answer</summary>

**`Point p`:** never escapes, so once `processData` is C2-compiled, `p` is **scalar replaced**: no allocation, `x` and `y` live in registers. (Not "stack allocated": HotSpot doesn't do that.)

**`List list`:** `System.out.println(list.size())` does **not** make `list` escape: only the `int` returned by `size()` is passed to `println`. Whether `list` can be eliminated depends on inlining:
- `ArrayList.add` must be inlined, along with its growth path (`grow` → `Arrays.copyOf`), for C2 to see that the list and its backing `Object[]` don't escape. The backing array also has to be small: C2 only scalar-replaces arrays up to `EliminateAllocationArraySizeLimit` (64) elements, and this one starts at 100.
- So in practice the `ArrayList` and its array **are allocated**, in the thread's TLAB.

**Boxing:** `values[i] % 10` is between -9 and 9, inside the `Integer` cache (-128..127), so `Integer.valueOf` returns **cached** objects and allocates nothing. Values outside the cache would allocate a new `Integer` per element; those escape into the list's array, so EA can't remove them.

**Conclusion:** `Point` → no allocation; `ArrayList` + its `Object[100]` → allocated; `Integer`s → cached here. The general lesson: escape analysis depends on inlining and size limits, so verify with an allocation profile (`-prof gc`) instead of reasoning from source.
</details>

### Question 8: Memory Leak Identification

**Problem:** A server application runs fine for 24 hours, then slows down and eventually throws OutOfMemoryError. The heap dump shows millions of `java.util.HashMap$Node` objects. What's the most likely cause? How do you find the root cause?

<details>
<summary>🎯 Answer</summary>

**The pattern** (fine for hours, then slower, then OOM) is a slow leak: the live set grows, so GCs run more often and reclaim less (the "slows down" part is GC overhead), until the heap is full.

**Millions of `HashMap$Node`** means one or more `HashMap`s (or `HashSet`s, `LinkedHashMap`s, which use the same nodes) keep growing. Typical culprits:
1. A static/singleton cache with no eviction
2. Session or per-user state never removed
3. A "seen IDs" set for deduplication with no TTL
4. Metrics with unbounded tag values (high-cardinality labels such as user IDs or URLs with IDs in the path)
5. Listener/registry maps that only ever get `put`s

**Root cause analysis:**

1. **Get a heap dump** (or two, hours apart, to compare growth):
```bash
jcmd <pid> GC.heap_dump /dumps/heap.hprof     # triggers a full GC first (live objects)
# jhat was removed in JDK 9; use Eclipse MAT, VisualVM, or IntelliJ's analyzer
```
2. **Eclipse MAT:** *Leak Suspects* report, then the *Dominator Tree* sorted by retained size: the map that retains gigabytes is near the top. *Path to GC Roots (excluding weak/soft references)* shows exactly which field holds it, e.g. `static UserCache.CACHE`, a Spring singleton bean's field, or a `ThreadLocalMap` of a pooled thread.
3. **Confirm growth over time** without dumps: `jcmd <pid> GC.class_histogram` every hour and compare `HashMap$Node` counts; heap-after-GC metrics trending upward.
4. Check what *writes* to that map in code review: there's always a `put` with no matching `remove`.

**Fixes:**
1. Replace the map with a bounded cache (Caffeine: `maximumSize`, `expireAfterWrite`/`expireAfterAccess`)
2. Remove entries on the lifecycle event that ends them (session expiry, connection close)
3. Bound metric tag cardinality
4. `WeakHashMap` only for metadata keyed by objects whose lifetime is managed elsewhere

**Prevention:**
- `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=...` and `-XX:+ExitOnOutOfMemoryError`
- Alert on heap-used-after-GC trending up, not on raw heap usage (which is sawtooth by design)
- In containers, size with `-XX:MaxRAMPercentage` and leave headroom for native memory
</details>

---

## Summary

| Concept | Key Takeaway |
|---------|-------------|
| **Pass by value** | Java passes copies of references; aliasing, not "pass by reference", is what to manage |
| **Object layout** | 12-byte header (8 with compact headers) + fields packed largest-first + padding to 8 |
| **Compressed oops** | 4-byte references below ~32 GB heap; crossing 32 GB can *reduce* usable capacity |
| **Object lifecycle** | Class init → TLAB allocation → constructor → use → unreachable → reclaimed by the next relevant GC |
| **Strong reference** | Keeps the object alive while reachable from a GC root |
| **SoftReference** | Cleared under memory pressure, all before OOME; usually a poor cache |
| **WeakReference** | Cleared once only weakly reachable; `WeakHashMap`, `ThreadLocalMap` keys |
| **PhantomReference** | `get()` is always null; basis of `Cleaner`; auto-cleared since JDK 9 |
| **Cleanup** | try-with-resources first; `Cleaner` as a safety net; `finalize()` is deprecated for removal |
| **TLAB** | Per-thread bump-pointer allocation; the cost of garbage is in survivors, not allocation |
| **Escape analysis** | Scalar replacement and lock elision for non-escaping objects; depends on inlining |
| **Strings** | Compact strings (1 byte/char for Latin-1); intern only for many duplicates; dedup for all GCs since JDK 18 |
| **Memory leaks** | Static collections, listeners, inner classes, ThreadLocals, class loaders, unclosed resources, unbounded queues |
| **OOM types** | Heap, Metaspace/class space, GC overhead, direct memory, native threads, array size; plus container OOM-kills |
