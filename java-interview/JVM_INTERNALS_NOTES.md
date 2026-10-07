# ☕ JVM Internals & Garbage Collection — Principal Engineer Deep-Dive

> **A reference on JVM architecture, garbage collection, the memory model, JIT compilation, class loading and bytecode**
> *Written for Staff/Principal Engineer interviews. Current as of October 2026: JDK 25 is the latest LTS, JDK 27 the current release. Commands and log excerpts were run on JDK 25 (HotSpot) unless stated otherwise.*

---

## Table of Contents

1. [JVM Architecture Overview](#1-jvm-architecture-overview)
2. [Class Loading Mechanism](#2-class-loading-mechanism)
3. [Runtime Data Areas](#3-runtime-data-areas)
4. [Garbage Collection — Deep Dive](#4-garbage-collection-deep-dive)
5. [G1 GC Detailed Walkthrough](#5-g1-gc-detailed-walkthrough)
6. [ZGC — Colored Pointers & Load Barriers](#6-zgc-colored-pointers-load-barriers)
7. [Shenandoah GC](#7-shenandoah-gc)
8. [Java Memory Model](#8-java-memory-model)
9. [JIT Compilation — C1 & C2](#9-jit-compilation-c1-c2)
10. [Bytecode Structure & Instructions](#10-bytecode-structure-instructions)
11. [Performance Tuning Tools](#11-performance-tuning-tools)
12. [JVM Internals Interview Questions](#12-jvm-internals-interview-questions)

---

## 1. JVM Architecture Overview

!!! tip "30-second answer"
    The JVM loads class files through a chain of class loaders, verifies and links them, and keeps class metadata in **Metaspace** (native memory) and objects in the **heap**. Each thread has its own stack of frames. Code starts in the **interpreter**; hot methods are compiled by **C1** (fast compile, profiling) and then **C2** (slow compile, aggressive speculative optimization), and fall back to the interpreter (**deoptimize**) when a speculation turns out wrong. A **garbage collector** reclaims unreachable objects, coordinating with running threads through barriers and safepoints.

### The JVM as a Specification

The Java Virtual Machine is defined by the **Java Virtual Machine Specification (JVMS)**, published for each Java SE release (the current edition is Java SE 25). HotSpot is the reference implementation; OpenJ9 and GraalVM are others. The spec defines:

- the `class` file format and the bytecode instruction set
- a stack-based execution model (each frame has local variables and an operand stack; there are no general-purpose registers apart from the per-thread pc)
- the run-time data areas (heap, method area, stacks)
- loading, linking and initialization rules and symbolic reference resolution

It deliberately does **not** specify the garbage collector, the JIT, or object layout: those are HotSpot implementation details, and they change between releases.

### JVM Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    HOTSPOT JVM ARCHITECTURE                  │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐  │
│  │              CLASS LOADING SUBSYSTEM                   │  │
│  │   Bootstrap → Platform → Application → Custom loaders  │  │
│  │   load → link (verify, prepare, resolve) → initialize  │  │
│  └───────────────────────────┬────────────────────────────┘  │
│                              ▼                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                 RUNTIME DATA AREAS                     │  │
│  │  Shared:     Heap (objects, arrays, Class mirrors)     │  │
│  │              Metaspace (class metadata = method area)  │  │
│  │              Code cache (JIT-compiled code)            │  │
│  │  Per thread: Java stack (frames), PC, native stack     │  │
│  │              (virtual threads: stack chunks in heap)   │  │
│  └───────────────────────────┬────────────────────────────┘  │
│                              ▼                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                  EXECUTION ENGINE                      │  │
│  │  Interpreter │ C1 JIT │ C2 JIT │ GC │ runtime/safepoints│ │
│  └────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  NATIVE INTERFACES: JNI, FFM API (JDK 22+), JVMTI      │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Class loaders** | Find class bytes; the JVM then verifies, links and initializes them |
| **Runtime data areas** | Heap, Metaspace, code cache, per-thread stacks |
| **Execution engine** | Interpreter plus C1/C2 JIT compilers; deoptimization back to the interpreter |
| **Garbage collector** | Reclaims unreachable objects (Serial, Parallel, G1, ZGC, Shenandoah) |
| **Native interfaces** | JNI (legacy), the Foreign Function & Memory API (final in JDK 22) for calling native code and managing off-heap memory, JVMTI for agents and debuggers |

---

## 2. Class Loading Mechanism

!!! tip "30-second answer"
    A class goes through **loading** (find bytes, create the runtime class), **linking** (verify bytecode, prepare static fields with default values, resolve symbolic references, usually lazily) and **initialization** (run `<clinit>` exactly once, under a lock, on first active use). Loaders delegate **parent-first** so core classes come from the bootstrap loader. A class's identity is its name *plus* its defining loader.

### The Three-Phase Process

```
Loading → Linking (Verification → Preparation → Resolution) → Initialization
```

**1. Loading:**
- A class loader finds the bytes (from a JAR, the runtime image, the network, or generated in memory) and calls `defineClass`.
- The JVM parses them into its internal class representation (a `Klass` in Metaspace) and creates the `java.lang.Class` mirror object on the heap.

**2. Linking:**
- **Verification:** type-checks the bytecode using the `StackMapTable` (no stack overflows/underflows, no jumping into the middle of an instruction, correct types on every path).
- **Preparation:** allocates static fields and sets them to default values (0, `null`, `false`). No user code runs yet.
- **Resolution:** turns symbolic references in the constant pool into direct references. HotSpot does this lazily, the first time each instruction executes.

**3. Initialization:**
- Runs `<clinit>` (static initializers and static field assignments, in source order), once, with the JVM holding an initialization lock (JLS §12.4.2), so other threads wait and then see the fully initialized class. That is why the holder-class singleton idiom is thread-safe.
- Triggered by the first **active use**: `new`, a static method call, reading or writing a static field that is not a compile-time constant, reflection such as `Class.forName(name)`, initializing a subclass, or being the main class.
- Not triggered by: reading a `static final` compile-time constant (inlined by javac), `Foo.class`, or declaring an array `Foo[]`.
- If `<clinit>` throws, the class is marked erroneous: the first use gets `ExceptionInInitializerError`, every later use gets `NoClassDefFoundError`.

### ClassLoader Delegation Model

```java
// java.lang.ClassLoader.loadClass (simplified from the JDK source):
protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
    synchronized (getClassLoadingLock(name)) {           // per-name lock if parallel-capable
        Class<?> c = findLoadedClass(name);              // 1. already defined by this loader?
        if (c == null) {
            try {
                if (parent != null) {
                    c = parent.loadClass(name, false);   // 2. ask the parent first
                } else {
                    c = findBootstrapClassOrNull(name);  //    top of the chain: bootstrap
                }
            } catch (ClassNotFoundException e) {
                // parent couldn't find it
            }
            if (c == null) {
                c = findClass(name);                     // 3. look it up ourselves
            }
        }
        if (resolve) resolveClass(c);
        return c;
    }
}
// Custom loaders normally override findClass(), not loadClass(), to keep delegation.
```

### ClassLoader Hierarchy in Java 9+ (Modules)

```
┌────────────────────────────────────────────┐
│         BOOTSTRAP loader                   │
│  (inside the JVM; `null` in Java code)     │
│  Loads java.base and other core modules    │
│  from the runtime image (lib/modules)      │
├────────────────────────────────────────────┤
│         PLATFORM loader                    │
│  (replaced the Java 8 extension loader;    │
│   lib/ext and rt.jar no longer exist)      │
│  Loads e.g. java.sql, java.net.http        │
├────────────────────────────────────────────┤
│         APPLICATION (system) loader        │
│  Loads the class path and module path      │
├────────────────────────────────────────────┤
│         CUSTOM loaders                     │
│  Plugins, app servers, generated code      │
└────────────────────────────────────────────┘
```

With modules, delegation is not purely parent-first: each loader knows which loader owns each **package** of a named module and delegates directly to it.

### Custom ClassLoader Patterns

```java
// 1. Parent-first (standard delegation): the default
// 2. Child-first (parent-last): servlet containers, plugin systems
// 3. Isolated: parent = platform loader, so only JDK classes are shared

// Child-first loader (Tomcat-style webapp loader, simplified):
public class ChildFirstClassLoader extends URLClassLoader {
    static { registerAsParallelCapable(); }

    public ChildFirstClassLoader(URL[] urls, ClassLoader parent) {
        super(urls, parent);
    }

    @Override
    protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
        if (name.startsWith("java.") || name.startsWith("javax.")) {
            return super.loadClass(name, resolve);       // never override platform classes
        }
        synchronized (getClassLoadingLock(name)) {
            Class<?> c = findLoadedClass(name);          // 1. already defined here?
            if (c == null) {
                try {
                    c = findClass(name);                 // 2. LOCAL first
                } catch (ClassNotFoundException e) {
                    c = super.loadClass(name, false);    // 3. then the parent
                }
            }
            if (resolve) resolveClass(c);
            return c;
        }
    }
}
// Child-first needs a shared API that BOTH sides load from the parent (servlet API,
// logging facades). If the child also bundles it, objects passed across the
// boundary fail with ClassCastException or LinkageError ("loader constraint violation").
```

### ClassLoader Namespace Isolation

The runtime identity of a class is **(binary name, defining class loader)**:

```java
// jarUrl points to a JAR that is NOT on the application class path; parent = null
// means "delegate only to the bootstrap loader".
URLClassLoader loader1 = new URLClassLoader(new URL[]{jarUrl}, null);
URLClassLoader loader2 = new URLClassLoader(new URL[]{jarUrl}, null);

Class<?> class1 = loader1.loadClass("com.example.MyClass");
Class<?> class2 = loader2.loadClass("com.example.MyClass");

class1 == class2;                  // false: two distinct runtime classes
class1.getName().equals(class2.getName());   // true
class1.isAssignableFrom(class2);   // false
Object o = class2.getDeclaredConstructor().newInstance();
class1.cast(o);                    // ClassCastException: com.example.MyClass cannot be
                                   // cast to com.example.MyClass (different loaders)
// If the JAR were also on the class path and the parent were the app loader,
// parent-first delegation would return the SAME class from both loaders.
```

**Class unloading:** a class is unloaded only when its defining loader is unreachable, which requires that no instances, no `Class` objects, and no other reference to *any* class of that loader remain. Classes of the bootstrap, platform and application loaders are never unloaded.

---

## 3. Runtime Data Areas

!!! tip "30-second answer"
    Per thread: a **stack** of frames (locals + operand stack), a pc, and a native stack. Shared: the **heap** (all objects and arrays), **Metaspace** (class metadata, native memory, unbounded by default), and the **code cache** (JIT output). The process uses much more than `-Xmx`: Metaspace, thread stacks, code cache, GC data structures, direct buffers and malloc'd memory all add up, which is why containers get OOM-killed while the heap looks fine. Objects are allocated by bumping a pointer in a per-thread **TLAB**, and objects that never escape a compiled method may not be allocated at all (**scalar replacement**).

### Per-Thread Areas

| Area | What It Stores | Size | Overflow |
|------|---------------|------|----------|
| **PC register** | Address of the current bytecode (undefined while in native code) | One word | n/a |
| **Java stack** | Frames: local variables, operand stack, frame data | `-Xss` / `ThreadStackSize`; default 1 MB on Linux x64 (2 MB on macOS/AArch64) | `StackOverflowError` |
| **Native stack** | Frames of native (C/C++) code | Same thread stack in HotSpot | `StackOverflowError` or a crash |

HotSpot actually uses one native stack per platform thread for both Java and native frames. The stack is *reserved* virtual memory; only touched pages use RAM. **Virtual threads** keep their frames in the heap as stack-chunk objects while unmounted, which is why a million of them is feasible.

### Shared Areas

| Area | What It Stores | Overflow |
|------|---------------|----------|
| **Heap** | All objects and arrays, including `Class` mirrors, interned strings and static field values | `OutOfMemoryError: Java heap space` (or `GC overhead limit exceeded` when the GC is spending almost all its time collecting) |
| **Metaspace** (the method area since JDK 8; replaced PermGen) | Class metadata, method bytecode, constant pools, JIT-independent runtime data. Native memory | `OutOfMemoryError: Metaspace` (only if `-XX:MaxMetaspaceSize` is set; default is unlimited) |
| **Compressed class space** | Class metadata reachable through compressed class pointers (part of Metaspace), 1 GB by default | `OutOfMemoryError: Compressed class space` |
| **Code cache** | JIT-compiled code (segmented into non-method, profiled, non-profiled code) | `CodeCache is full. Compiler has been disabled.` warning: the app keeps running, interpreted, and slows down |
| **Direct / off-heap memory** | `ByteBuffer.allocateDirect`, FFM `Arena` memory, Netty buffers | `OutOfMemoryError: Cannot reserve ... direct buffer memory` |

Use **Native Memory Tracking** to see the whole footprint: `-XX:NativeMemoryTracking=summary` then `jcmd <pid> VM.native_memory summary`.

**Containers:** since JDK 10 the JVM reads cgroup limits (`UseContainerSupport`). The default max heap is **25% of the container memory** (`MaxRAMPercentage=25`), which wastes memory in a single-process container; services typically set `-XX:MaxRAMPercentage=60..75` and leave the rest for non-heap memory.

### Heap Structure (Generational)

```
Classic generational layout (Serial, Parallel GC):
┌───────────────────────────────────────┬──────────────────────────────┐
│           YOUNG GENERATION            │        OLD GENERATION        │
│  ┌────────────────┬────────┬────────┐ │                              │
│  │      Eden      │   S0   │   S1   │ │      Long-lived objects      │
│  │ (new objects)  │(from)  │ (to)   │ │      (tenured)               │
│  └────────────────┴────────┴────────┘ │                              │
└───────────────────────────────────────┴──────────────────────────────┘
G1:  the same roles, but assigned to equal-sized REGIONS that can change role.
ZGC: young and old generations made of pages of different sizes.
```

A minor collection copies live Eden and from-survivor objects to the to-survivor space (or promotes them). Each survival increments the object's **age** (4 bits in the header, so at most 15 = `MaxTenuringThreshold`). The JVM promotes objects earlier when survivor space fills beyond `TargetSurvivorRatio` (50%).

### Allocation: TLABs and Escape Analysis

```java
// FAST PATH (almost every `new`):
// Each thread owns a Thread-Local Allocation Buffer (TLAB) carved out of Eden.
// Allocating = bump a pointer within the TLAB: no lock, no CAS, a few instructions.
// When the TLAB is exhausted, the thread retires it (filling the leftover with a
// dummy object so the heap stays parsable) and takes a new one, sized adaptively
// (ResizeTLAB) to keep waste around TLABWasteTargetPercent (1%).
//
// SLOW PATHS:
// - Object larger than the remaining TLAB / a large fraction of it: allocate
//   directly in Eden with a CAS on the shared top pointer.
// - G1 humongous object (>= half a region): allocated directly in old/humongous regions.
// - Eden full: trigger a young GC, then retry.
//
// Consequences:
// - Allocation itself is cheap; the cost is the GC work for objects that SURVIVE.
// - Allocation profilers (JFR jdk.ObjectAllocationSample, async-profiler -e alloc)
//   sample at TLAB refills, which is why they're cheap enough for production.

// ESCAPE ANALYSIS (C2): if an object provably doesn't escape the compiled method
// (after inlining), C2 can:
//  - SCALAR-REPLACE it: keep its fields in registers/stack slots, no allocation at all
//  - ELIDE locks on it
// HotSpot does NOT do "stack allocation" of whole objects; scalar replacement is
// what people usually mean by that phrase.
```

A runnable demonstration (JDK 21+):

```java
import java.lang.management.ManagementFactory;

public class EscapeDemo {
    record Point(long x, long y) {}

    // `p` never escapes sum(): C2 can scalar-replace it and never allocate it.
    static long sum(int n) {
        long total = 0;
        for (int i = 0; i < n; i++) {
            Point p = new Point(i, i + 1);
            total += p.x() + p.y();
        }
        return total;
    }

    public static void main(String[] args) {
        var mx = (com.sun.management.ThreadMXBean) ManagementFactory.getThreadMXBean();
        for (int i = 0; i < 20; i++) sum(100_000);           // warm up so C2 compiles sum()
        long before = mx.getCurrentThreadAllocatedBytes();
        long r = sum(10_000_000);
        long after = mx.getCurrentThreadAllocatedBytes();
        System.out.printf("result=%d, allocated ~%d MB%n", r, (after - before) >> 20);
    }
}
// $ java EscapeDemo.java
// result=100000000000000, allocated ~0 MB
// $ java -XX:-DoEscapeAnalysis EscapeDemo.java
// result=100000000000000, allocated ~305 MB      (10M Points x 32 bytes)
```

Escape analysis is fragile: it fails if the method isn't inlined (too big, megamorphic call), if the object is stored into a field or array that escapes, or if it flows into a merge point the analysis can't handle. Don't design around it; measure with `-prof gc` in JMH.

### Object Layout in Heap

```java
// HotSpot, 64-bit, compressed oops and compressed class pointers (the default
// for heaps < 32 GB):
//
// ┌──────────────────────────────────────────────────────┐
// │ OBJECT HEADER (12 bytes)                             │
// │   mark word        8 bytes: hash, GC age, lock bits  │
// │   class pointer    4 bytes (compressed Klass*)       │
// ├──────────────────────────────────────────────────────┤
// │ INSTANCE DATA: fields, laid out by size to minimize   │
// │ padding (longs/doubles, ints, shorts/chars, bytes,    │
// │ then references); superclass fields come first        │
// ├──────────────────────────────────────────────────────┤
// │ PADDING to a multiple of 8 bytes (ObjectAlignmentInBytes)
// └──────────────────────────────────────────────────────┘
// Arrays add a 4-byte length after the header.
// new Object() = 16 bytes (12 header + 4 padding); measured with JOL on JDK 25.
//
// COMPACT OBJECT HEADERS (JEP 450 experimental in JDK 24, JEP 519 product in JDK 25,
// JEP 534 default in JDK 27; -XX:+UseCompactObjectHeaders on 25/26):
// the class pointer moves INTO the mark word, so the header is 8 bytes.
// new Object() = 8 bytes, HashMap.Node 32 -> 24 bytes. Typical heap savings are
// 10-20% for object-heavy applications.
//
// MARK WORD (legacy 64-bit layout), unlocked object:
// | unused:25 | identity hash:31 | unused:1 | age:4 | unused:1 | lock:2 |
// lock bits:
//   01  unlocked
//   00  locked: lightweight (fast) locking
//   10  inflated: points to an ObjectMonitor
//   11  marked: used by GCs, e.g. as a forwarding pointer during evacuation
// The old "biased" bit is unused: biased locking was disabled in JDK 15 and
// removed in JDK 18. Since JDK 23 the default lightweight locking keeps a small
// per-thread lock stack instead of writing a stack pointer into the mark word.
// Computing the identity hash (Object.hashCode / System.identityHashCode) stores
// it lazily in the header.
//
// COMPACT layout (one 64-bit word): 22-bit compressed class pointer | 31-bit
// identity hash | 4 bits reserved (Valhalla) | 4-bit age | self-forwarded bit |
// 2 lock bits. The 22-bit class pointer limits a JVM to about 4 million classes,
// and compact headers require the new lightweight locking (no stack locking).
```

The [Object Handling & Memory notes](OBJECT_HANDLING_MEMORY_NOTES.md) go deeper into object sizes and references.

---

## 4. Garbage Collection — Deep Dive

!!! tip "30-second answer"
    A tracing GC finds live objects by following references from **GC roots** and reclaims everything else. Generational collectors collect the young generation often and cheaply (most objects die young) and need a **remembered set / card table** so old-to-young pointers act as extra roots. Pick the collector by goal: **Parallel** for throughput, **G1** (default) for balanced latency, **ZGC** or **Shenandoah** for sub-millisecond pauses on large heaps. Pause time scales with the live data that has to be marked or copied *during the pause*, not with heap size. Concurrent collectors move that work out of pauses at the cost of barriers and CPU.

### Generational Hypothesis

Generational collection relies on two empirical observations:
1. **Most objects die young** (the weak generational hypothesis): request-scoped objects, iterators, temporary strings.
2. **Few references point from old objects to young ones**, so they can be tracked cheaply (card table / remembered set, maintained by a write barrier) instead of scanning the old generation on every young GC.

```
┌──────────────────────────────────────────────────────────────┐
│                     GENERATIONAL GC                          │
│                                                              │
│  ┌──────────┐ survive ┌──────────┐ age > threshold ┌───────┐ │
│  │   Eden   │───────→ │ Survivor │ ──────────────→ │  Old  │ │
│  └──────────┘         └──────────┘   (promotion)   └───────┘ │
│        ▲                                            │        │
│        └── young GC: copy live objects, reclaim the rest     │
│            (STW in Serial/Parallel/G1; concurrent in ZGC)    │
│                                                     │        │
│               old/major collection: mark, then compact ◄─┘   │
└──────────────────────────────────────────────────────────────┘
```

### GC Algorithm Comparison

| Collector | Young collection | Old collection | Pauses | Status |
|-----------|------------------|----------------|--------|--------|
| **Serial** | STW copying, 1 thread | STW mark-compact, 1 thread | Proportional to live data | Small heaps, 1 CPU |
| **Parallel** | STW copying, N threads | STW mark-compact, N threads | Proportional to live data | Best throughput |
| **CMS** | STW copying (ParNew) | Mostly concurrent mark-**sweep**, no compaction → fragmentation | Short, until fragmentation forces a Full GC | Deprecated JDK 9, **removed JDK 14** |
| **G1** | STW evacuation of young regions | Concurrent marking + STW evacuation in mixed GCs (incremental compaction) | Pause goal, default 200 ms | **Default since JDK 9** |
| **ZGC** | Concurrent (generational since JDK 21) | Concurrent mark + concurrent relocation | < 1 ms | Generational-only since JDK 24 |
| **Shenandoah** | Concurrent (optional generational mode, product in JDK 25) | Concurrent mark + concurrent evacuation | < 10 ms, typically ~1 ms | In most OpenJDK builds, not Oracle JDK |

### GC Types in HotSpot

| JVM Flag | Collector | Notes |
|----------|-----------|-------|
| `-XX:+UseSerialGC` | Serial | Picked automatically on "client-class" machines (< 2 CPUs or < 1792 MB) until JDK 27, which makes G1 the default everywhere (JEP 523) |
| `-XX:+UseParallelGC` | Parallel | Young: parallel copying; old: parallel mark-compact |
| ~~`-XX:+UseConcMarkSweepGC`~~ | CMS | Removed in JDK 14; the flag is now rejected |
| `-XX:+UseG1GC` | G1 | Default |
| `-XX:+UseZGC` | ZGC | Generational. On JDK 21–22 add `-XX:+ZGenerational`; from JDK 23 it is the default mode and from JDK 24 the only one |
| `-XX:+UseShenandoahGC` | Shenandoah | `-XX:ShenandoahGCMode=generational` for the generational mode (JDK 25+) |
| `-XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC` | Epsilon | No-op GC for benchmarks and very short-lived jobs |

### GC Trigger Points

| Trigger | What happens |
|---------|--------------|
| Eden (young regions) full on allocation | Young GC |
| G1: old occupancy crosses the (adaptive) IHOP | Next young GC becomes a *Concurrent Start* pause, then concurrent marking |
| G1: evacuation finds no free space ("to-space exhausted") or a humongous allocation fails | Full GC (bad) |
| Parallel/Serial: old generation can't absorb promotions | Full GC |
| Metaspace reaches its current high-water mark (`MetaspaceSize`, then grown) | A GC to unload classes (G1: usually a concurrent cycle, not a Full GC) |
| `System.gc()` | Full GC by default (G1 can make it concurrent with `-XX:+ExplicitGCInvokesConcurrent`; `-XX:+DisableExplicitGC` ignores it) |
| `jmap -dump:live` / `jcmd GC.heap_dump` | Full GC to find live objects first |
| ZGC | Timers and allocation-rate heuristics start young and major cycles proactively; allocation stalls if it falls behind |

### GC Roots

Tracing starts from **roots**: references the GC must treat as live without being pointed to by another heap object.

```
┌──────────────────────────────────────────────────────────────┐
│                         GC ROOTS                             │
│  1. Thread stacks: locals and operand stack slots holding    │
│     references in every frame (found via the JIT's oop maps) │
│  2. Class metadata of live class loaders → Class mirrors →   │
│     static fields                                            │
│  3. JNI global references (and JNI locals of active frames)  │
│  4. Objects used as monitors by threads holding them         │
│  5. VM-internal references: system classes, code cache       │
│     (oops embedded in compiled code), JVMTI tags             │
│  6. For a partial (young/mixed) collection: remembered-set   │
│     entries, i.e. references from regions NOT being collected│
│                                                              │
│  NOT strong roots: the interned-string table and other weak  │
│  tables (cleared when entries die); objects awaiting         │
│  finalization (kept alive via the Finalizer queue, which is  │
│  itself reachable from the Finalizer thread)                 │
└──────────────────────────────────────────────────────────────┘
```

### Object Finalization — The Anti-Pattern

```java
// DON'T USE finalize():
// - no guarantee when, or whether, it runs; runs on one Finalizer thread
// - finalizable objects need at least two GC cycles to be reclaimed and are
//   tracked specially, slowing allocation and GC
// - finalize() can resurrect the object; exceptions in it are ignored
// - Status: deprecated in JDK 9; deprecated FOR REMOVAL in JDK 18 (JEP 421).
//   It still runs by default in JDK 25; test removal readiness with
//   --finalization=disabled.

// INSTEAD:
// 1. try-with-resources + AutoCloseable for deterministic cleanup
// 2. java.lang.ref.Cleaner as a safety net for forgotten close() calls
// 3. For native memory: the FFM API's Arena (closing the arena frees everything)

// Most JDK resources are already AutoCloseable; use them directly:
try (Connection conn = dataSource.getConnection();
     PreparedStatement ps = conn.prepareStatement("select name from users where id = ?")) {
    ps.setLong(1, id);
    try (ResultSet rs = ps.executeQuery()) {
        // ...
    }
}   // closed in reverse order, even if an exception is thrown; a close() failure
    // is attached to the primary exception via getSuppressed()
```

### Fallback: Cleaner (Java 9+)

```java
import java.lang.ref.Cleaner;

public final class NativeBuffer implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();   // one daemon thread: share it

    // The cleanup state must NOT reference the NativeBuffer itself (use a static
    // nested class or a record, never a lambda capturing `this`); otherwise the
    // object stays reachable from the Cleaner and is never cleaned.
    private record State(long address) implements Runnable {
        @Override public void run() {
            System.out.println("freeing native memory at " + address);   // e.g. free()
        }
    }

    private final Cleaner.Cleanable cleanable;

    public NativeBuffer(long address) {
        this.cleanable = CLEANER.register(this, new State(address));
    }

    @Override public void close() {
        cleanable.clean();   // runs State.run() now, at most once
    }

    public static void main(String[] args) throws Exception {
        try (NativeBuffer b = new NativeBuffer(0x1000)) {
            System.out.println("using buffer");
        }                                    // deterministic cleanup via close()
        new NativeBuffer(0x2000);            // forgotten: the Cleaner is the safety net
        System.gc();
        Thread.sleep(200);                   // runs on the Cleaner thread, eventually
    }
}
// using buffer
// freeing native memory at 4096
// freeing native memory at 8192
```

`Cleaner` is built on `PhantomReference`: the action runs after the object is unreachable, can't resurrect it, and runs on the Cleaner's thread. Like finalization, the *timing* is still up to the GC, so it is a safety net, not a resource-management strategy.

---

## 5. G1 GC Detailed Walkthrough

!!! tip "30-second answer"
    G1 splits the heap into equal regions and, in each stop-the-world pause, evacuates (copies live objects out of) a **collection set**: all young regions, plus, after a concurrent marking cycle, the old regions with the most garbage ("garbage first"). It sizes the young generation and picks how many old regions to include so the pause fits `MaxGCPauseMillis`. Remembered sets let it collect a region without scanning the rest of the heap; SATB marking lets it mark concurrently. A Full GC means G1 ran out of space during evacuation and is a sizing or allocation problem to fix.

### Region-Based Heap

G1 divides the heap into equal-sized **regions**, a power of two between 1 MB and 32 MB, chosen so there are about 2048 of them (since JDK 18 you can set up to 512 MB manually with `-XX:G1HeapRegionSize`):

```
Region size ≈ heap_size / 2048, rounded down to a power of two, clamped to [1 MB, 32 MB]

Example: 8 GB heap   → 4 MB regions (2048 regions)
         300 GB heap → 32 MB cap   (~9,600 regions)
```

### G1 Region Types

```
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ E  │ E  │ O  │ E  │ S  │ F  │ O  │ O  │ H  │ H+ │ H+ │ O  │ E  │ F  │ O  │ S  │
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
E = Eden, S = Survivor, O = Old, F = Free
H = start of a humongous object, H+ = its continuation regions
Roles are assigned per region and change over time; young regions need not be contiguous.
```

**Humongous objects** (≥ half a region) are allocated directly into contiguous free regions as old objects. They're expensive (they can trigger GCs, waste the tail of their last region, and need contiguous space), so large `byte[]` buffers on a small-region heap are a classic cause of Full GCs. Dead humongous objects (especially primitive arrays) can be reclaimed eagerly at young GCs, without waiting for a marking cycle.

### G1 Memory Structures

| Data Structure | Description |
|---------------|-------------|
| **Card table** | One byte per 512-byte card of the heap. A post-write barrier dirties the card when a reference store creates a cross-region pointer |
| **Remembered set (RSet)** | Per region (or group of regions): which cards elsewhere contain pointers *into* it. Tracks pointers from old regions only; young regions are always collected, so pointers from them aren't recorded. Stored in compact "card set" containers since JDK 18 (the old fine/coarse PRT tables are gone) |
| **Refinement** | Dirty cards are queued and processed by concurrent refinement threads into RSet entries (JDK 26, JEP 522, reworked this with a second card table to cut synchronization) |
| **Collection set (CSet)** | The regions evacuated in a given pause |
| **SATB queues** | Snapshot-at-the-beginning: during marking, a pre-write barrier records the *old* value of overwritten reference fields so nothing live at mark start is missed |
| **Mark bitmap** | One bit per 8 bytes (minimum object alignment) of heap: marked = live |
| **TAMS (Top At Mark Start)** | Per-region pointer recorded when marking starts. Objects above TAMS were allocated during marking and are implicitly live |

### The G1 GC Cycle — Detailed

```
PHASE 1: YOUNG-ONLY (STW evacuation pauses)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: the young regions G1 budgeted are used up          │
│  Duration: usually milliseconds to tens of ms, scaling with  │
│            live young data and RSet/card scanning            │
│                                                              │
│  1. CSet = all Eden + Survivor regions                       │
│  2. Roots: thread stacks, VM roots, and RSets of the CSet    │
│     (pending dirty cards are processed first)                │
│  3. Copy live objects to Survivor regions, or to Old         │
│     regions once their age reaches the tenuring threshold    │
│  4. Update references to moved objects; free the CSet        │
│                                                              │
│  When old occupancy crosses IHOP, the next young pause is a  │
│  "Concurrent Start" pause that also marks the roots and      │
│  starts a concurrent marking cycle.                          │
└──────────────────────────────────────────────────────────────┘

PHASE 2: CONCURRENT MARKING CYCLE (mostly concurrent)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: old-gen occupancy > IHOP, as a % of the WHOLE heap │
│  (InitiatingHeapOccupancyPercent=45 is only the initial      │
│  value; adaptive IHOP, on by default, learns a better one)   │
│                                                              │
│  a. Concurrent Start (piggybacks on a young pause): mark     │
│     roots, record TAMS per region                            │
│  b. Root region scan (concurrent): scan survivor regions     │
│  c. Concurrent mark: trace the object graph using the        │
│     bitmap; drain SATB buffers                               │
│  d. Remark (STW): finish SATB buffers, reference processing  │
│     (Soft/Weak/Final/Phantom), class unloading; free regions │
│     that turned out completely empty                         │
│  e. Concurrent rebuild of remembered sets for old regions    │
│     that are candidates for collection                       │
│  f. Cleanup (STW, short): finish RSet rebuild, sort          │
│     candidate old regions by reclaimable space               │
└──────────────────────────────────────────────────────────────┘

PHASE 3: SPACE RECLAMATION (MIXED GCs, STW)
┌──────────────────────────────────────────────────────────────┐
│  One "Prepare Mixed" young pause, then up to                 │
│  G1MixedGCCountTarget (8) mixed pauses. Each evacuates:      │
│   - all young regions, PLUS                                  │
│   - a slice of candidate old regions, cheapest-to-collect /  │
│     most garbage first, as many as fit the pause goal        │
│                                                              │
│  Candidates exclude regions more than                        │
│  G1MixedGCLiveThresholdPercent (85%) live:                   │
│   Region 5:  5% live → collected early                       │
│   Region 12: 15% live → collected next                       │
│   Region 3:  90% live → not a candidate (copying is too      │
│              expensive for what it frees)                    │
│                                                              │
│  Stops when the reclaimable space left in candidates drops   │
│  below G1HeapWastePercent (5% of the heap).                  │
└──────────────────────────────────────────────────────────────┘

PHASE 4: FULL GC (STW fallback, a failure mode)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: evacuation can't find free regions ("to-space      │
│  exhausted" / evacuation failure), or a humongous allocation │
│  can't find contiguous regions, or System.gc()               │
│                                                              │
│  Parallel mark-compact of the whole heap (parallel since     │
│  JDK 10, JEP 307; single-threaded in JDK 8/9). Pause scales  │
│  with live data: seconds on large heaps.                     │
│                                                              │
│  TO AVOID: more heap headroom; start marking earlier (lower  │
│  IHOP or let adaptive IHOP work); larger G1ReservePercent;   │
│  larger regions if humongous allocations are the cause;      │
│  reduce the allocation rate or the live set.                 │
└──────────────────────────────────────────────────────────────┘
```

### G1 Tuning Parameters

Start with `-Xms`/`-Xmx` and at most a pause goal; change anything else only with GC logs that show why.

```bash
# PAUSE TIME GOAL
-XX:MaxGCPauseMillis=200          # default 200 ms; G1 sizes young gen/mixed CSets to meet it

# THREADS
-XX:ParallelGCThreads=N           # STW workers. Default: #CPUs up to 8, then 8 + 5/8 of the rest
-XX:ConcGCThreads=N               # concurrent marking threads. Default: max(1, (ParallelGCThreads + 2) / 4)

# MARKING START
-XX:InitiatingHeapOccupancyPercent=45  # initial IHOP: old occupancy as % of the whole heap
-XX:-G1UseAdaptiveIHOP                 # pin IHOP to the value above (adaptive is the default)

# MIXED GCs
-XX:G1MixedGCCountTarget=8             # spread old-region reclamation over up to 8 mixed GCs
-XX:G1MixedGCLiveThresholdPercent=85   # regions more live than this aren't candidates
-XX:G1HeapWastePercent=5               # stop mixed GCs when less than 5% is reclaimable

# REGIONS AND RESERVE
-XX:G1HeapRegionSize=16m          # bigger regions → fewer humongous objects
-XX:G1ReservePercent=10           # heap kept free as evacuation headroom (to-space reserve)

# OTHER USEFUL ONES
-XX:+AlwaysPreTouch               # commit/touch the heap at startup, not during requests
-XX:+UseStringDeduplication       # dedup String backing arrays (supported by all collectors since JDK 18)
```

### Analyzing G1 Logs

JDK 9+ uses unified logging. Real output from JDK 25 with `-Xlog:gc` (a small 256 MB heap, so pauses are tiny):

```
[0.481s][info][gc] GC(0) Pause Young (Normal) (G1 Evacuation Pause) 48M->5M(256M) 2.932ms
[0.507s][info][gc] GC(10) Pause Young (Concurrent Start) (G1 Evacuation Pause) 226M->139M(256M) 1.421ms
[0.507s][info][gc] GC(11) Concurrent Mark Cycle
[0.522s][info][gc] GC(11) Pause Remark 171M->171M(256M) 0.735ms
[0.525s][info][gc] GC(11) Pause Cleanup 182M->182M(256M) 0.017ms
[0.528s][info][gc] GC(11) Concurrent Mark Cycle 20.763ms
[0.529s][info][gc] GC(15) Pause Young (Prepare Mixed) (G1 Evacuation Pause) 236M->175M(256M) 0.863ms
[0.531s][info][gc] GC(16) Pause Young (Mixed) (G1 Evacuation Pause) 238M->181M(256M) 0.765ms
```

Reading a line: `before->after(committed heap)` and the pause duration. Other things to grep for:

```
Pause Young (Normal) (G1 Humongous Allocation)   # humongous allocations driving GCs
To-space exhausted / Evacuation Failure           # G1 ran out of free regions while copying
Pause Full (G1 Compaction Pause)                  # Full GC: investigate
Pause Full (System.gc())                          # someone calls System.gc()
```

Use `-Xlog:gc*:file=gc.log:time,uptime,level,tags` for phase-level detail, and GCeasy, GCViewer or JDK Mission Control to visualize. The Java 8 flags (`-XX:+PrintGCDetails`, `-Xloggc`) are obsolete.

---

## 6. ZGC — Colored Pointers & Load Barriers

!!! tip "30-second answer"
    ZGC does marking, relocation (compaction) and reference updating **concurrently**, so its pauses are under a millisecond and don't grow with the heap. It stores GC state in unused bits of every heap reference (**colored pointers**). A **load barrier** checks those bits whenever a reference is read from the heap and, if the object has moved, fixes the reference in place ("self-healing"). Since JDK 21 it is **generational** (young and old collected separately), and since JDK 24 that is the only mode. Costs: barrier overhead and concurrent GC threads take CPU, it doesn't support compressed oops, and if allocation outpaces collection, threads stall.

### Overview

ZGC (production since JDK 15, JEP 377) targets:
- **Pauses under 1 ms**, independent of heap and live-set size
- **Heaps from a few hundred MB up to 16 TB**
- **Concurrent compaction**, so no fragmentation-driven Full GCs
- **Generational collection** (JEP 439, JDK 21; default mode in JDK 23 via JEP 474; non-generational mode removed in JDK 24 via JEP 490)

The heap is made of **pages** (ZGC's regions): small (2 MB, for objects up to 256 KB), medium (ergonomically sized, typically 32 MB) and large (one object each). Mark information lives in side bitmaps, not in object headers.

### Colored Pointers (64-bit Reinterpretation)

Each reference stored in the heap carries metadata bits alongside the address. The layout changed with generational ZGC:

```
Generational ZGC (JDK 21+):   [ object address (high bits) | color metadata (low 16 bits) ]
  - Heap fields hold COLORED pointers; registers and stack hold plain addresses.
  - The load barrier strips the color with a shift; the store barrier adds it.
  - The color encodes: remapped state (has this pointer been updated since the
    last relocation?), marked state for the young and old generations (with
    alternating "parity" bits per cycle), and whether the field is already
    recorded in the remembered set.

Non-generational ZGC (JDK 15–23, now removed), for reference:
  bits 0–43  address (up to 16 TB)
  bits 44–47 Marked0, Marked1, Remapped, Finalizable
  The same object was mapped at several virtual addresses ("multi-mapping") so a
  pointer with any color could be dereferenced directly. Generational ZGC
  dropped multi-mapping, which also makes RSS numbers in `top` honest again.
```

At any moment one color is **"good"** for the current phase. A reference with the good color can be used directly; any other color means the barrier has work to do.

### Load Barrier

ZGC's load barrier runs on **every load of a reference from a heap field or array element** (not on loads of primitives, and not on references already in registers or on the stack):

```java
// Java code:
Object field = obj.someField;

// What the JIT emits, as pseudo-code:
//   raw = load(obj.someField)          // colored pointer
//   if (raw has the bad color bits)    // fast path: one test + branch
//       raw = slowPath(&obj.someField, raw)
//   field = raw >> shift               // strip color → plain address
//
// slowPath:
//   - if the object was relocated: look up its new address in the forwarding
//     table (or relocate it now if the GC hasn't yet), and remap the pointer
//   - write the good-colored pointer back into obj.someField (CAS), so the next
//     load of this field takes the fast path: "self-healing"
//
// Store barrier (generational ZGC): on reference stores it marks the overwritten
// value if marking is in progress (SATB-style) and records old→young fields in
// the remembered set (a pair of bitmaps per old page, swapped each young cycle,
// rather than a card table).
```

### ZGC Phase Details

Each generation runs its own cycle; young cycles are frequent, major (young + old) cycles less so. Real phase names from JDK 25 `-Xlog:gc+phases` for a young collection:

```
GC(3) y: Pause Mark Start 0.002ms
GC(3) y: Concurrent Mark 1.495ms
GC(3) y: Pause Mark End 0.003ms
GC(3) y: Concurrent Mark Free 0.001ms
GC(3) y: Concurrent Reset Relocation Set 0.002ms
GC(3) y: Concurrent Select Relocation Set 0.034ms
GC(3) y: Pause Relocate Start 0.001ms
GC(3) y: Concurrent Relocate 0.993ms
GC(3) y: Young Generation 120M(47%)->64M(25%) 0.003s
```

```
┌──────────────────────────────────────────────────────────────┐
│                     ZGC CYCLE (per generation)               │
│  Pause Mark Start (STW, ~µs)                                 │
│   └─ flip the good color; set up marking from roots          │
│  Concurrent Mark                                             │
│   └─ trace live objects; thread stacks are scanned           │
│      concurrently too (JEP 376 stack watermarks);            │
│      pointers left over from the previous relocation are     │
│      remapped as they are traced                             │
│  Pause Mark End (STW, ~µs)                                   │
│   └─ confirm marking is complete                             │
│  Concurrent Process References / Select Relocation Set       │
│   └─ handle Soft/Weak/Phantom refs; pick the pages with      │
│      the most garbage                                        │
│  Pause Relocate Start (STW, ~µs)                             │
│   └─ switch to relocation; fix up the few roots              │
│  Concurrent Relocate                                         │
│   └─ copy live objects out of the selected pages, building   │
│      forwarding tables; mutators that hit a not-yet-moved    │
│      object relocate it themselves via the load barrier;     │
│      emptied pages are freed immediately                     │
└──────────────────────────────────────────────────────────────┘
```

None of the pauses does work proportional to the heap or live set; they touch only a small, bounded set of roots.

### ZGC Tuning

ZGC is designed to need almost no tuning. The important decision is **heap size**: it needs headroom to keep allocating while a cycle runs.

```bash
-XX:+UseZGC                      # generational (JDK 23+ default mode; only mode on 24+)
-Xmx<size>                       # the main knob: give it headroom over the live set
-XX:SoftMaxHeapSize=<size>       # try to stay below this; use the rest only for spikes
-XX:ConcGCThreads=<n>            # normally adjusted dynamically; set only if logs say so
-XX:ZAllocationSpikeTolerance=2  # default 2.0; raise for bursty allocation
-XX:ZUncommitDelay=300           # seconds before unused memory is returned to the OS (default 300)
-XX:+AlwaysPreTouch              # avoid page faults on first touch at runtime
-Xlog:gc*:file=gc.log            # watch for "Allocation Stall" lines
```

### ZGC Limitations

- **CPU and throughput:** barriers and concurrent GC threads cost throughput compared with Parallel or G1; the amount is workload-dependent, so measure. It needs spare cores.
- **Allocation stalls:** if the application allocates faster than ZGC can free memory, allocating threads block (`Allocation Stall` in logs, `jdk.ZAllocationStall` in JFR). The fix is more heap headroom or less allocation, not shorter pauses.
- **No compressed oops:** references are 8 bytes (compressed *class* pointers are still used), so the same data takes more heap than under G1 with compressed oops below 32 GB.
- **Small heaps:** ZGC works with small heaps, but G1 usually offers better throughput and footprint there; ZGC pays off when pause times matter or the heap is large.

---

## 7. Shenandoah GC

!!! tip "30-second answer"
    Shenandoah (Red Hat; production since JDK 15) is the other pause-less collector: concurrent marking **and concurrent evacuation**, with pauses typically around a millisecond. It uses a **load-reference barrier** and keeps the forwarding pointer in the object's mark word while it is being moved. It supports compressed oops, and its **generational mode** is a product feature since JDK 25 (JEP 521). It is included in most OpenJDK distributions but not in Oracle JDK builds.

### Overview

- **Concurrent evacuation:** live objects are copied while the application runs; GC threads and mutators race to copy an object and agree on one copy with a CAS on its forwarding pointer.
- **Barriers:** a SATB pre-write barrier for marking, and a **load-reference barrier (LRB)** since JDK 13 that guarantees code only ever sees the to-space copy of an object. (Shenandoah 1.0 used *Brooks pointers*: an extra forwarding word in every object plus read and write barriers. Shenandoah 2.0 in JDK 13 removed the extra word.)
- **Forwarding:** stored in the mark word of the from-space copy while it is being evacuated.
- **Modes:** `satb` (default, single generation) and `generational` (`-XX:ShenandoahGCMode=generational`, product since JDK 25).

### Comparison: ZGC vs Shenandoah

| Aspect | ZGC | Shenandoah |
|--------|-----|-----------|
| Forwarding information | Colored pointers + per-page forwarding tables | Forwarding pointer in the mark word of the moved object |
| Barriers | Load barrier + store barrier (generational) | Load-reference barrier + SATB pre-write barrier |
| Compressed oops | Not supported | Supported |
| Max heap | 16 TB | No special limit beyond the platform's |
| Generational | Yes, the only mode (JDK 24+) | Optional mode, product in JDK 25 |
| Pause target | < 1 ms | Typically a few ms or less; pauses include root scanning |
| Distribution | All OpenJDK builds incl. Oracle JDK | Most OpenJDK builds (Temurin, Corretto, Red Hat...), not Oracle JDK |
| Production since | JDK 15 | JDK 15 |

### Shenandoah Evacuation in One Picture

```
┌──────────────────────────────────────────────────────────────┐
│               SHENANDOAH CONCURRENT EVACUATION               │
│                                                              │
│  from-space copy                to-space copy                │
│  ┌───────────────┐              ┌───────────────┐            │
│  │ mark word ────┼── forwards ─►│ mark word     │            │
│  │ fields (stale)│              │ fields (live) │            │
│  └───────────────┘              └───────────────┘            │
│                                                              │
│  Load-reference barrier on reading a reference:              │
│   - object not in the collection set → use as is             │
│   - already forwarded → use (and heal to) the to-space copy  │
│   - not yet copied → copy it now, CAS the forwarding pointer;│
│     whoever wins the CAS defines the copy                    │
│  After evacuation, a concurrent "update references" phase    │
│  rewrites remaining pointers, then from-space is reclaimed.  │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Java Memory Model

!!! tip "30-second answer"
    The JMM (JLS chapter 17, from JSR-133 in Java 5) defines which values a read may return in a multithreaded program. Correctly synchronized (data-race-free) programs behave as if sequentially consistent. Synchronization comes from **happens-before** edges: unlock → later lock of the same monitor, volatile write → later read of it, `start()`, `join()`, and transitivity. `final` fields get a separate initialization-safety guarantee. The JIT and CPU may reorder anything else. See [Question 1 in the interview questions](INTERVIEW_QUESTIONS.md#question-1-jvm-memory-model-happens-before-volatile) for worked examples.

### Key Definitions

- **Actions:** reads, writes, volatile reads/writes, locks, unlocks, thread start/termination, and so on.
- **Synchronization actions:** volatile accesses, locks/unlocks, thread start/join. They have a single total order (the *synchronization order*) consistent with each thread's program order.
- **Happens-before:** the partial order derived from program order plus synchronizes-with edges, closed under transitivity.
- **Data race:** two accesses to the same variable from different threads, at least one a write, not ordered by happens-before.
- **DRF guarantee:** if a program has no data races under sequentially consistent executions, all its executions *are* sequentially consistent. This is the guarantee you program against.

### Happens-Before Rules (JLS §17.4.5)

```
1. Program order: each action in a thread happens-before every later action
   in that thread
2. Monitor lock: an unlock of monitor m happens-before every subsequent lock of m
3. Volatile: a write to volatile field v happens-before every subsequent read of v
4. Thread start: t.start() happens-before any action in t
5. Thread termination: every action in t happens-before another thread detects
   that t has terminated (t.join() returns, t.isAlive() is false)
6. Interruption: t.interrupt() happens-before t detects the interrupt
7. Default values: the default-value initialization of every variable
   happens-before the first action of every thread
8. Finalizer: the end of a constructor happens-before the start of the object's
   finalizer
9. Transitivity: A hb B and B hb C ⇒ A hb C
```

`java.util.concurrent` adds documented edges on top (e.g. putting into a `BlockingQueue` happens-before taking it out; `Future.get()` sees everything the task did; `CountDownLatch.countDown()` happens-before a returning `await()`).

### The Causality Requirements

The JMM must forbid **out-of-thin-air** values while still allowing compiler optimizations. The canonical example (JLS §17.4.8):

```java
// Initially x = y = 0, both plain (non-volatile) fields.
// Thread 1:            // Thread 2:
int r1 = x;             int r2 = y;
if (r1 == 1) y = 1;     if (r2 == 1) x = 1;

// Can we end with r1 == 1 and r2 == 1?
// That would require a write to justify itself: y = 1 only happens if x was 1,
// which only happens if y was 1. The JMM's causality rules FORBID this result:
// a value can't appear "out of thin air". The program is data-racy, yet the only
// allowed outcome is r1 == r2 == 0.
```

Contrast with a reordering the JMM *does* allow:

```java
// Initially x = y = 0.
// Thread 1:    // Thread 2:
x = 1;          y = 1;
int r1 = y;     int r2 = x;
// r1 == 0 && r2 == 0 is ALLOWED (and observable on x86): each store can sit in
// its core's store buffer while the following load executes. Making x and y
// volatile forbids it (volatile accesses are sequentially consistent), which is
// exactly why a volatile write needs a StoreLoad fence on x86.
```

(The formal causality rules are known to be flawed in corner cases and are still an open research topic; for interviews, "DRF ⇒ SC, plus no out-of-thin-air" is the right summary.)

### Memory Barriers

Barriers are an implementation tool, not part of the JMM. The classic JSR-133 cookbook names four kinds:

| Barrier | Guarantees | x86-64 (TSO) | AArch64 |
|---------|-----------|--------------|---------|
| **LoadLoad** | Earlier loads complete before later loads | No instruction needed | `DMB ISHLD` |
| **LoadStore** | Earlier loads complete before later stores | No instruction needed | `DMB ISHLD` |
| **StoreStore** | Earlier stores visible before later stores | No instruction needed | `DMB ISHST` |
| **StoreLoad** | Earlier stores visible before later loads | `LOCK`-prefixed instruction (HotSpot: `lock addl $0,(rsp)`) or `MFENCE` | `DMB ISH` |

x86 only reorders a later load before an earlier store (via the store buffer), so only StoreLoad costs an instruction. The JIT still needs *compiler* barriers everywhere to stop its own reordering.

### JMM Mappings to Hardware

| Java action | x86-64 | AArch64 |
|-------------|--------|---------|
| Volatile read | Plain `MOV` | `LDAR` (load-acquire) |
| Volatile write | `MOV` + `lock addl $0,(rsp)` (StoreLoad) | `STLR` (store-release) |
| `compareAndSet` / atomic RMW | `LOCK CMPXCHG` / `LOCK XADD` | `CASAL` with LSE atomics, or an `LDAXR`/`STLXR` loop |
| Monitor enter (fast path) | `LOCK CMPXCHG` on the mark word | CAS with acquire semantics |
| Monitor exit (fast path) | CAS or plain store with release semantics, depending on locking mode | Release store / CAS |
| Plain field read/write | Plain `MOV` | Plain `LDR`/`STR` |

### final Fields — Initialization Safety

```java
public class FinalFieldExample {
    final int x;     // final: initialization safety applies
    int y;           // not final: no guarantee

    static FinalFieldExample instance;   // published WITHOUT synchronization (a data race)

    public FinalFieldExample() {
        x = 1;
        y = 2;
        // Don't let `this` escape here (registering a listener, starting a thread,
        // storing it in a static): that voids the guarantee.
    }

    // Thread A:
    static void writer() { instance = new FinalFieldExample(); }

    // Thread B:
    static void reader() {
        FinalFieldExample f = instance;
        if (f != null) {
            int r1 = f.x;   // guaranteed 1
            int r2 = f.y;   // may be 0
        }
    }
    // JLS §17.5: a "freeze" of final fields happens at the end of the constructor.
    // A thread that obtains the reference after the constructor completes (and
    // without `this` escaping) sees the final fields' values as of the freeze,
    // plus everything reachable through them as of that point (e.g. the contents
    // of a final array or list built in the constructor). y gets no such guarantee.
    // Implementation: a StoreStore barrier at the end of such constructors.
}
```

This is why immutable objects (all fields `final`, e.g. records, `String`) can be shared across threads even when published through a data race.

### volatile Semantics

```java
// volatile guarantees:
// 1. A write to v happens-before every later read of v that sees it (visibility)
// 2. Release/acquire ordering: accesses before a volatile write can't move after
//    it; accesses after a volatile read can't move before it
// 3. All volatile accesses are sequentially consistent with each other
// 4. long/double volatile reads and writes are atomic (plain ones may tear)

// volatile does NOT give:
// 1. Atomicity of compound operations (v++, check-then-act): use Atomic*/VarHandle CAS
// 2. Mutual exclusion or invariants across several variables: use a lock

// VarHandle (JDK 9+) exposes weaker modes too: getOpaque/setOpaque (no ordering,
// but no tearing and eventually visible), getAcquire/setRelease (one-directional
// ordering, enough for publishing an object), and fences (VarHandle.fullFence() etc.).
```

---

## 9. JIT Compilation — C1 & C2

!!! tip "30-second answer"
    HotSpot interprets first, then compiles hot methods: **C1** quickly, with profiling code, then **C2** using that profile to speculate (inline the observed receiver types, drop never-taken branches, eliminate allocations). If a speculation fails, the code **deoptimizes** back to the interpreter and is recompiled later. Peak performance therefore depends on warm-up and on the profile seen during warm-up. Inlining is the most important optimization because it enables all the others.

### Tiered Compilation

```java
// Five levels (tiered compilation, on by default since JDK 8):
//   Level 0: interpreter (with invocation and back-edge counters)
//   Level 1: C1, no profiling      (trivial methods: C2 couldn't do better)
//   Level 2: C1, limited profiling (counters only)
//   Level 3: C1, full profiling    (counters + type and branch profiles)
//   Level 4: C2, fully optimized using the level-3 profile
//
// Common transitions:
//   0 → 3 → 4      normal path for hot code
//   0 → 2 → 3 → 4  when the C2 queue is long, C1 compiles at level 2 first
//                  (cheaper) and upgrades to level 3 later
//   0 → 3 → 1      the profile shows the method is trivial, or C2 can't compile it
//   any → 0        deoptimization; the method may be recompiled later
//
// Thresholds (JDK 25 defaults; scaled down/up dynamically with queue lengths):
//   Tier3InvocationThreshold=200,  Tier3CompileThreshold=2000    (to level 3)
//   Tier4InvocationThreshold=5000, Tier4CompileThreshold=15000   (to level 4)
//   Back-edge counters trigger on-stack replacement (OSR) for long-running loops.
//   (CompileThreshold=10000 and counter decay only apply with -XX:-TieredCompilation.)
//
// Compiler threads: CICompilerCount is computed from the CPU count (it grows
// roughly logarithmically, e.g. 4 on a 10-core laptop), split about 1:2 between
// C1 and C2, and threads are started/stopped on demand
// (UseDynamicNumberOfCompilerThreads). C1 and C2 have separate queues.
//
// Code cache: ReservedCodeCacheSize (240 MB by default with tiered compilation),
// segmented into non-method, profiled and non-profiled code. If it fills up,
// compilation stops and the app runs slowly; watch for "CodeCache is full".
```

### C2 Optimizations

| Optimization | Description |
|-------------|-------------|
| **Inlining** | Replace a call with the callee's body; the gateway to most other optimizations |
| **Class hierarchy analysis (CHA)** | If only one implementation of a virtual method is loaded, call it directly (with a dependency that deoptimizes if a new subclass is loaded) |
| **Type-profile speculation** | Monomorphic / bimorphic call sites are inlined behind a cheap type check; megamorphic sites (3+ receiver types) use a virtual/interface call |
| **Escape analysis** | Scalar replacement (no allocation) and lock elision for objects that don't escape the compiled code |
| **Lock coarsening** | Merge adjacent synchronized blocks on the same object |
| **Loop optimizations** | Unrolling, peeling, loop-invariant code motion, range-check elimination, strip mining (keeps safepoint polls) |
| **Auto-vectorization (superword)** | Use SIMD instructions for simple array loops; the Vector API (incubator) exposes SIMD explicitly |
| **Null-check and range-check elimination** | Remove provably redundant checks; implicit null checks rely on the hardware trap |
| **Constant folding / GVN / dead code elimination** | Classic compiler optimizations on the sea-of-nodes IR |
| **Intrinsics** | Replace well-known JDK methods with hand-written assembly or IR (see Q11 below) |
| **Uncommon traps** | Branches never taken during profiling aren't compiled at all; reaching one deoptimizes |

### Inlining Heuristics

```java
// Key flags (JDK 25 defaults):
// -XX:MaxInlineSize=35       callees up to 35 bytes of BYTECODE are inlined even if not hot
// -XX:FreqInlineSize=325     hot callees up to 325 bytecode bytes may be inlined
// -XX:InlineSmallCode=2500   don't inline a callee whose existing compiled code is larger
// -XX:MaxInlineLevel=15      maximum inlining depth (was 9 before JDK 14)
//
// What helps a call get inlined:
// - Statically bound targets (static, private, final methods, constructors, and
//   invokespecial/super calls) need no type check, but are still subject to the
//   size limits above. Nothing is "always inlined" (except JDK-internal
//   @ForceInline methods).
// - Virtual and interface calls are inlined when CHA proves a single target or
//   the profile shows one or two receiver types.
// - Small methods: keep hot paths short; move rare paths (error handling,
//   logging) into separate methods so the hot method stays under FreqInlineSize.
//
// Diagnose with:
// -XX:+UnlockDiagnosticVMOptions -XX:+PrintInlining   (or JITWatch on a -XX:+LogCompilation log)
```

### Deoptimization

```java
// Deoptimization discards compiled code (or one activation of it) and continues
// in the interpreter. Causes:
// 1. A speculation failed at runtime ("uncommon trap"): an unseen receiver type,
//    a never-taken branch taken, a null where none was profiled, an
//    arithmetic/range check that failed
// 2. A dependency was invalidated: e.g. loading a new subclass breaks a CHA
//    assumption that a method had one implementation; the nmethod is
//    "made not entrant" so no new calls enter it
// 3. Class redefinition by an agent (JVMTI), or deopt requested by the VM
//
// Mechanics: compiled frames carry debug info that maps machine state back to
// interpreter state at specific points; on deopt, the JVM rebuilds interpreter
// frames (including for inlined methods) from it and resumes interpreting.
// Old nmethods are freed later (the code-cache sweeper and the "zombie" state
// were removed in JDK 20; nmethods are now unloaded by the GC).
//
// Symptom in production: a sudden, lasting slowdown after a new code path runs
// (e.g. a rarely used subtype appears and a call site goes megamorphic).
// Diagnose with -Xlog:deoptimization=debug or JFR jdk.Deoptimization events.
```

### Escape Analysis Example

```java
public class EscapeAnalysisDemo {

    // `p` does not escape: after inlining, C2 scalar-replaces it.
    // Its fields live in registers; no heap allocation happens.
    public long sum(int[] values) {
        Point p = new Point(0, 0);
        for (int v : values) {
            p.x += v;
            p.y += v;
        }
        return p.x + p.y;
    }

    // `Point` ESCAPES (returned): must be heap-allocated (in the caller's TLAB),
    // unless this method is inlined into a caller where it doesn't escape.
    public Point create(int x, int y) {
        return new Point(x, y);
    }

    // Lock elision: this StringBuffer never escapes, so its synchronized methods'
    // locking can be removed.
    public int sumSynchronized(int[] values) {
        StringBuffer sb = new StringBuffer();
        for (int v : values) {
            sb.append(v);
        }
        return sb.length();
    }
}
```

See [Allocation: TLABs and Escape Analysis](#allocation-tlabs-and-escape-analysis) for a runnable measurement.

---

## 10. Bytecode Structure & Instructions

### Class File Structure

```
ClassFile {
    u4             magic;               // 0xCAFEBABE
    u2             minor_version;       // 0, or 0xFFFF for classes using preview features
    u2             major_version;       // 52 = Java 8, 61 = 17, 65 = 21, 69 = 25, 71 = 27
    u2             constant_pool_count;
    cp_info        constant_pool[constant_pool_count-1];
    u2             access_flags;
    u2             this_class;
    u2             super_class;
    u2             interfaces_count;
    u2             interfaces[interfaces_count];
    u2             fields_count;
    field_info     fields[fields_count];
    u2             methods_count;
    method_info    methods[methods_count];
    u2             attributes_count;
    attribute_info attributes[attributes_count];   // e.g. SourceFile, InnerClasses,
                                                   // BootstrapMethods, Record,
                                                   // PermittedSubclasses, NestMembers
}
```

Since JDK 24, the JDK has a standard API to read and write this format: `java.lang.classfile` (JEP 484). `javap -v -p` prints it.

### Access Flags

The same bit can mean different things for classes, fields and methods:

| Flag | Value | Applies to | Meaning |
|------|-------|-----------|---------|
| ACC_PUBLIC | 0x0001 | class, field, method | public |
| ACC_PRIVATE | 0x0002 | field, method | private |
| ACC_PROTECTED | 0x0004 | field, method | protected |
| ACC_STATIC | 0x0008 | field, method | static |
| ACC_FINAL | 0x0010 | class, field, method | final |
| ACC_SUPER / ACC_SYNCHRONIZED | 0x0020 | class / method | legacy invokespecial semantics (always set) / synchronized method |
| ACC_VOLATILE / ACC_BRIDGE | 0x0040 | field / method | volatile field / compiler-generated bridge method |
| ACC_TRANSIENT / ACC_VARARGS | 0x0080 | field / method | transient field / varargs method |
| ACC_NATIVE | 0x0100 | method | native |
| ACC_INTERFACE | 0x0200 | class | interface |
| ACC_ABSTRACT | 0x0400 | class, method | abstract |
| ACC_STRICT | 0x0800 | method | strictfp; meaningless since JDK 17 (JEP 306 made all FP strict) |
| ACC_SYNTHETIC | 0x1000 | all | compiler-generated |
| ACC_ANNOTATION | 0x2000 | class | annotation interface |
| ACC_ENUM | 0x4000 | class, field | enum / enum constant |
| ACC_MODULE / ACC_MANDATED | 0x8000 | class / parameter | module-info / implicitly declared |

### Common Bytecodes

```
LOAD/STORE (typed by prefix: i=int, l=long, f=float, d=double, a=reference):
  aload_0          # push local 0 ('this' in instance methods)
  aload_1          # push local 1 (first parameter of an instance method)
  iload_2 / istore_2
  astore_3

ARITHMETIC:
  iadd isub imul idiv irem    # pop two ints, push one; idiv/irem throw on /0
  ladd ...                    # long variants (each long/double takes 2 slots)
  iinc 0 1                    # add 1 to int local 0 in place

OBJECTS AND ARRAYS:
  new #Class                  # allocate (uninitialized) object
  invokespecial <init>        # ...then call its constructor
  getfield / putfield         # instance fields
  getstatic / putstatic       # static fields (may trigger class initialization)
  instanceof / checkcast
  newarray / anewarray / arraylength / iaload / aastore ...

METHOD INVOCATION:
  invokevirtual    # virtual dispatch through the vtable
  invokeinterface  # interface dispatch (itable)
  invokespecial    # constructors, private methods, super calls
  invokestatic     # static methods
  invokedynamic    # call site linked at runtime by a bootstrap method: lambdas and
                   # method refs (LambdaMetafactory), string concatenation since
                   # JDK 9 (StringConcatFactory), record equals/hashCode/toString
                   # (ObjectMethods), pattern-matching switch (SwitchBootstraps)

STACK:
  dup pop swap
  ldc #const       # push a constant-pool entry (String, Class, MethodType, dynamic constant)
  iconst_0 bipush sipush aconst_null

CONTROL:
  ifeq ifne iflt ...          # compare int with 0
  if_icmpne if_acmpeq ...     # compare two ints / two references
  goto
  tableswitch                 # dense switch: O(1) jump table
  lookupswitch                # sparse switch: sorted keys, binary search
  ireturn areturn return athrow

MONITORS:
  monitorenter / monitorexit  # synchronized blocks; synchronized methods use the
                              # ACC_SYNCHRONIZED flag instead
```

---

## 11. Performance Tuning Tools

### Command-Line Tools

| Tool | Status | Purpose |
|------|--------|---------|
| `jcmd` | Current | The Swiss-army knife: `jcmd <pid> help`. Thread dumps (`Thread.print`, `Thread.dump_to_file -format=json` for virtual threads), heap dumps (`GC.heap_dump`), class histogram (`GC.class_histogram`), JFR control, `VM.flags`, `VM.native_memory`, `Compiler.codecache` |
| `jfr` | Current | Read and summarize `.jfr` recordings (`jfr print`, `jfr summary`, `jfr view` since JDK 21) |
| `jstat` | Current | Sample GC and class-loading counters: `jstat -gcutil <pid> 1s` |
| `jmap`, `jstack`, `jinfo` | Current, but superseded by `jcmd` | Histograms/dumps, thread dumps, flags |
| `jhsdb` | Current | Serviceability agent: inspect core dumps and hung processes |
| `jhat` | **Removed in JDK 9** | Use Eclipse MAT, VisualVM or JDK Mission Control instead |
| JDK Mission Control | Separate download | GUI for JFR recordings |

### Async Profiler

```bash
# async-profiler 3.0+ ships the `asprof` launcher (older releases: profiler.sh)
asprof -e cpu   -d 60 -f cpu.html   <pid>   # on-CPU time (perf_events or itimer)
asprof -e alloc -d 60 -f alloc.html <pid>   # allocation sites (TLAB-driven sampling)
asprof -e wall  -d 60 -f wall.html  <pid>   # wall clock: includes blocked/waiting threads
asprof -e lock  -d 60 -f lock.html  <pid>   # contended locks

# Several events at once need the JFR output format:
asprof -e cpu,alloc,lock -d 120 -f profile.jfr <pid>

# Or load it as an agent at startup:
java -agentpath:/path/to/libasyncProfiler.so=start,event=cpu,file=cpu.html ...
```

It avoids **safepoint bias** (traditional `jstack`-style samplers can only see threads at safepoints, so tight loops look idle) and shows Java, native and kernel frames together.

### JFR (Java Flight Recorder)

```bash
# At startup (continuous recording, keep the last 6 hours on disk):
-XX:StartFlightRecording=disk=true,maxage=6h,filename=app.jfr,settings=default

# On a running JVM:
jcmd <pid> JFR.start name=perf settings=profile duration=60s filename=perf.jfr
jcmd <pid> JFR.dump name=perf filename=now.jfr
jcmd <pid> JFR.check

# Inspect:
jfr summary perf.jfr
jfr print --events jdk.GCPhasePause perf.jfr
jfr view hot-methods perf.jfr          # JDK 21+ built-in views

# Useful events:
# jdk.ExecutionSample          CPU samples (JDK 25 adds jdk.CPUTimeSample on Linux, JEP 509)
# jdk.ObjectAllocationSample   allocation pressure by site
# jdk.GCPhasePause             GC pause times
# jdk.SafepointBegin / jdk.SafepointStateSynchronization   safepoints and time-to-safepoint
# jdk.JavaMonitorEnter         contended synchronized
# jdk.ThreadPark               LockSupport.park (j.u.c locks, queues)
# jdk.VirtualThreadPinned      virtual thread pinned while blocking
# jdk.Compilation / jdk.Deoptimization   JIT activity
```

`settings=default` is designed for always-on production use (around 1% overhead); `settings=profile` samples more and costs more.

### GC Log Analysis

```bash
# JDK 9+ (unified logging):
-Xlog:gc*:file=gc.log:time,uptime,level,tags:filecount=10,filesize=50m
-Xlog:gc*=debug:file=gc.log:time,uptime,level,tags       # more detail
-Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags   # include safepoints

# JDK 8 only (obsolete flags):
-XX:+PrintGCDetails -XX:+PrintGCDateStamps -Xloggc:gc.log

# Tools: GCeasy (online), GCViewer (open source), JDK Mission Control (for JFR).
```

---

## 12. JVM Internals Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the difference between Stack and Heap memory in Java?</b></summary>

**Answer:**
- **Stack**: one per thread; holds frames with local variables (primitives and *references*) and operand stacks. Fixed maximum size (`-Xss`, 1 MB by default on Linux x64); exhausting it throws `StackOverflowError`. Freed automatically when a method returns. Virtual threads keep their frames on the heap while unmounted.
- **Heap**: shared by all threads; holds every object and array. Sized with `-Xms`/`-Xmx`; managed by the GC; `OutOfMemoryError` when the GC can't free enough.
- Conceptually objects are always on the heap. In practice, C2's escape analysis can avoid allocating an object that never leaves a compiled method by keeping its fields in registers (scalar replacement); HotSpot doesn't place whole objects on the stack.
</details>

<details>
<summary><b>Q2: What is the ClassLoader delegation model?</b></summary>

**Answer:** When asked to load a class, a loader:
1. Returns it if it already defined it (`findLoadedClass`)
2. Asks its parent (ultimately the bootstrap loader)
3. Only if the parent can't, finds and defines it itself (`findClass`)

This ensures:
- Core classes such as `java.lang.Object` always come from the bootstrap loader and can't be replaced by application code.
- A class visible to a parent is loaded once and shared by all children, so types match across the application.

It does **not** prevent two *sibling* loaders from each defining their own `com.example.Foo`: they can, and the two are different runtime types (identity = name + defining loader). That is exactly how app servers isolate applications, and why `Foo cannot be cast to Foo` errors exist.
</details>

<details>
<summary><b>Q3: What is the purpose of the JIT compiler?</b></summary>

**Answer:** The JIT compiles frequently executed bytecode to native code at runtime, using information only available at runtime:
- **C1**: compiles quickly with moderate optimization and inserts profiling (good for startup).
- **C2**: compiles slowly with aggressive, profile-guided speculative optimization (peak performance).
- Tiered compilation (default since JDK 8) goes interpreter → C1 with profiling → C2.
- Key optimizations: inlining, escape analysis, lock elision, loop optimizations, intrinsics. Wrong speculations are undone by deoptimization.
- Alternatives: GraalVM's JIT, and ahead-of-time approaches (GraalVM Native Image; Project Leyden's AOT cache in JDK 24+ which stores loaded classes and profiles but still JIT-compiles).
</details>

### Intermediate

<details>
<summary><b>Q4: Explain the different generations of the heap and how Minor/Major GC works.</b></summary>

**Answer:**
- **Young generation (Eden + two survivor spaces)**: new objects are allocated in Eden (via TLABs). A minor/young GC copies live objects from Eden and one survivor space into the other survivor space, incrementing their age, and promotes objects that reach the tenuring threshold (max 15) to the old generation. Cost is proportional to the *live* young objects, so it's cheap when most die young.
- **Old generation**: long-lived objects. Collected less often by a major/old collection (mark-compact in Serial/Parallel; concurrent marking + mixed evacuations in G1; concurrent in ZGC). "Full GC" means collecting the whole heap in one STW pause.
- **Metaspace (JDK 8+)**: class metadata in native memory, replacing PermGen. Not part of the heap; unbounded unless `-XX:MaxMetaspaceSize` is set. Freed when class loaders are collected.
- G1 and ZGC are generational too, but over regions/pages rather than fixed contiguous spaces.
</details>

<details>
<summary><b>Q5: What is the difference between Stop-The-World and Concurrent GC?</b></summary>

**Answer:**
- **STW**: all application threads are paused at a safepoint while the GC works. Simplest and usually best for throughput, but pause time grows with the live data processed. Serial and Parallel GC do everything STW; G1 evacuates STW.
- **Concurrent**: GC threads work while the application runs. The GC needs barriers to keep its view consistent (SATB pre-write barriers for marking, load/load-reference barriers for concurrent relocation) and must keep up with the allocation rate. Lower pause times, more CPU and memory overhead. ZGC and Shenandoah do marking and compaction concurrently; G1 marks concurrently.

Even "pause-less" collectors have short STW phases (root scanning, phase transitions); ZGC keeps them below a millisecond by making their work independent of heap size.
</details>

<details>
<summary><b>Q6: How does Escape Analysis improve performance?</b></summary>

**Answer:** Escape analysis (C2, on by default via `-XX:+DoEscapeAnalysis`) determines whether an object can be seen outside the compiled code that created it (after inlining):
- **No escape** → **scalar replacement**: the object is never allocated; its fields become locals in registers. This removes allocation and GC cost.
- **No escape** → **lock elision**: synchronization on the object is removed.
- **Arg escape** (passed to a callee that's not inlined but doesn't store it) → locks can still be elided, but the object is allocated.
- HotSpot does not implement true stack allocation; "allocated on the stack" in interviews usually means scalar replacement.

It's fragile: a method too big to inline, a megamorphic call, or storing the object in a field defeats it. Measure allocation (JMH `-prof gc`, JFR) rather than assuming it happened.
</details>

### Advanced

<details>
<summary><b>Q7: How does G1 determine which regions to collect during Mixed GC?</b></summary>

**Answer:** From the concurrent marking cycle G1 knows each old region's live bytes:
- Regions more than `G1MixedGCLiveThresholdPercent` (85%) live are excluded: copying them is expensive and frees little.
- The remaining candidates are sorted by efficiency (reclaimable bytes vs estimated copy cost), most garbage first: "Garbage-First".
- The candidates are spread over up to `G1MixedGCCountTarget` (8) mixed pauses; each pause adds as many old regions as its pause-time prediction allows on top of the young regions.
- Mixed collections stop when the reclaimable space left is below `G1HeapWastePercent` (5% of the heap).

This greedy approach maximizes memory reclaimed per millisecond of pause.
</details>

<details>
<summary><b>Q8: What causes a Full GC in G1, and how do you fix it?</b></summary>

**Answer:** ("Concurrent mode failure" is CMS terminology; in G1 the equivalent is an **evacuation failure** followed by a Full GC.) It happens when:
- G1 can't find free regions to copy live objects into during a young/mixed pause ("to-space exhausted"), or
- a humongous allocation can't find enough contiguous free regions, or
- marking didn't finish (or mixed GCs didn't reclaim enough) before the heap filled.

G1 then does a STW parallel full compaction: seconds on a big heap.

**Causes:**
- Heap too small for the live set plus allocation during a marking cycle
- Marking starts too late (IHOP too high; adaptive IHOP normally prevents this)
- Allocation spikes, or many humongous objects fragmenting the heap
- Marking too slow (too few `ConcGCThreads`, or CPU-starved container)

**Fixes, in order:**
- Look at the GC log to see which of the above it is
- Give the heap more headroom (`-Xmx`)
- Start marking earlier: lower `-XX:InitiatingHeapOccupancyPercent` (or leave adaptive IHOP on); raise `-XX:G1ReservePercent`
- Fix humongous allocations: larger `G1HeapRegionSize` or smaller buffers
- Reduce the allocation rate or the live set (caches!)
- For very large heaps with strict latency, switch to ZGC
</details>

<details>
<summary><b>Q9: How does the JVM handle synchronized at the hardware level?</b></summary>

**Answer:** HotSpot uses a fast path and a slow path:
1. **Biased locking** is history: deprecated and disabled by default in JDK 15 (JEP 374), removed in JDK 18. Its revocations needed safepoints and the payoff had disappeared on modern CPUs.
2. **Lightweight locking (fast path):** an uncontended `monitorenter` is a CAS on the object's mark word lock bits (one `LOCK CMPXCHG` on x86). Since JDK 23 the default implementation also pushes the object onto a small per-thread *lock stack* (the older "stack locking" stored a pointer to a displaced header in the thread's stack frame). Recursive locking is handled without inflating in the common case.
3. **Inflated monitor (slow path):** on contention or `wait()`/`notify()`, the lock is inflated to an `ObjectMonitor`. Threads spin adaptively for a while, then park (on Linux via futexes), and are unparked on release.

Memory effects: monitor enter has acquire semantics and exit has release semantics, which gives the happens-before edge between an unlock and the next lock of the same object. With virtual threads, since JDK 24 (JEP 491) a virtual thread blocked on a monitor unmounts from its carrier instead of pinning it.
</details>

<details>
<summary><b>Q10: Explain the JVM's safepoint mechanism and how it affects latency.</b></summary>

**Answer:** A safepoint is a state in which every Java thread is stopped at a known point, so the VM can safely inspect or modify stacks and the heap (STW GC phases, deoptimization, class redefinition).

**How it works:**
- JIT-compiled code polls at method returns and loop back-edges; the interpreter polls between bytecodes.
- To start a safepoint the VM **arms a per-thread polling word/page** (thread-local polls since JDK 10, which also enabled per-thread *handshakes* that avoid stopping every thread).
- Running threads stop at their next poll. Threads that are blocked, parked, sleeping or **running native (JNI) code** are already safe; a native thread just can't return to Java until the safepoint ends.

**Latency impact:**
- Total pause = **time-to-safepoint** (waiting for the slowest thread to hit a poll) + the VM operation. TTSP is normally microseconds.
- Long TTSP comes from code that runs a long time without polling (historically, counted loops; since JDK 10 loop strip mining keeps a poll every ~1000 iterations), huge `arraycopy`/`Arrays.fill` on giant arrays, or the OS stalling a thread (page faults, swapping, CPU throttling).
- **Diagnosis:** `-Xlog:safepoint` (shows "Reaching safepoint" separately), JFR `jdk.SafepointStateSynchronization`, `-XX:+SafepointTimeout`. The JDK 8 `-XX:+PrintSafepointStatistics` flag is gone.

**Mitigation:**
- Keep `-XX:+UseCountedLoopSafepoints` on (the default)
- Avoid giant single array operations on huge arrays; chunk them
- `-XX:+AlwaysPreTouch`, no swap, sane container CPU limits
- Prefer concurrent collectors so GC needs only tiny safepoints
</details>

<details>
<summary><b>Q11: What are compiler intrinsics? Give examples.</b></summary>

**Answer:** Intrinsics are JDK methods (marked `@IntrinsicCandidate` in the JDK source) that the JIT replaces with hand-optimized machine code or special IR instead of compiling their Java body. Examples:

| Intrinsic | What it becomes |
|-----------|----------------|
| `System.arraycopy`, `Arrays.copyOf` | Optimized copy stubs using wide SIMD loads/stores |
| `Math.sqrt`, `Math.fma` | `SQRTSD`, `VFMADD...` (x86) |
| `Integer.bitCount`, `numberOfLeadingZeros` | `POPCNT`, `LZCNT` |
| `String.equals`, `String.indexOf`, `Arrays.equals`, `ArraysSupport.vectorizedMismatch` | Vectorized SIMD loops |
| `Unsafe.compareAndSet*` / `VarHandle` CAS | `LOCK CMPXCHG` (x86), `CASAL` (AArch64) |
| CRC32 / CRC32C, AES, SHA, Base64 | Dedicated CPU instructions (CLMUL, AES-NI, SHA extensions) |
| `Object.hashCode` | Reads the identity hash from the header (falls back to the runtime to generate one, a thread-local xorshift value by default) |
| `Thread.currentThread()` | Load from the thread register (`r15` on x86-64) |

Intrinsics are one reason JDK library calls often beat hand-written Java loops; prefer the library method.
</details>

<details>
<summary><b>Q12: How does C2 perform loop unrolling? When is it harmful?</b></summary>

**Answer:** Unrolling replicates the loop body to reduce loop overhead (counter updates and branches) and to expose independent operations for instruction-level parallelism and SIMD vectorization. C2 first creates pre/main/post loops so the main loop runs without range checks.

```java
// Before (counted loop):
for (int i = 0; i < n; i++) {
    a[i] = b[i] + c[i];
}

// After (main loop unrolled by 4, conceptually):
int i = 0;
for (; i + 3 < n; i += 4) {
    a[i]   = b[i]   + c[i];
    a[i+1] = b[i+1] + c[i+1];
    a[i+2] = b[i+2] + c[i+2];
    a[i+3] = b[i+3] + c[i+3];
}
for (; i < n; i++) {        // post loop handles the remainder
    a[i] = b[i] + c[i];
}
// The main loop can then be vectorized: one SIMD instruction per 4/8/16 elements.
```

**Harmful when:**
- The body is large: code bloat, instruction-cache and code-cache pressure
- Trip counts are small: the setup cost isn't recovered
- The body has many unpredictable branches
C2 limits this itself (`LoopUnrollLimit`, loop size heuristics); tuning it by hand is rarely worthwhile.
</details>

---

## Quick Reference: JVM Internals at a Glance

| Concept | Key Facts |
|---------|-----------|
| JVM spec | JVMS per Java SE release; stack-based bytecode; GC/JIT/object layout are implementation details |
| Class file | Magic `0xCAFEBABE`; major version 61 = 17, 65 = 21, 69 = 25 |
| Class identity | Binary name + defining class loader |
| Heap | Eden, survivors, old (Serial/Parallel); regions (G1); pages (ZGC) |
| Allocation | TLAB pointer bump; humongous objects in G1; scalar replacement for non-escaping objects |
| Object header | 12 bytes (mark word + compressed class pointer); 8 bytes with compact headers (product JDK 25, default JDK 27) |
| GC roots | Thread stacks, live classes' statics, JNI globals, held monitors, VM internals; RSets for partial GCs |
| Default GC | G1 (since JDK 9; everywhere since JDK 27) |
| ZGC | Generational only (JDK 24+), colored pointers, load + store barriers, < 1 ms pauses, no compressed oops |
| Happens-before | Program order, monitor, volatile, start, termination/join, interrupt, transitivity; plus final-field semantics |
| Barriers | x86 needs a fence only for StoreLoad; AArch64 uses LDAR/STLR |
| JIT | Levels 0–4: interpreter → C1 profiled (3) → C2 (4); deoptimization on failed speculation |
| Safepoint | Thread-local polls at returns and loop back-edges; TTSP + operation time |
| Intrinsic | JIT replaces known JDK methods with optimized machine code |

---

> *Staff/Principal interviews focus on WHY things work the way they do: reason from mechanisms to trade-offs and production symptoms, and know which details changed in recent JDKs.*
