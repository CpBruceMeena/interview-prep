# ☕ JVM Internals & Garbage Collection — Principal Engineer Deep-Dive

> **A comprehensive reference on JVM architecture, garbage collection, memory model, class loading, and bytecode**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

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

### The JVM as a Specification

The Java Virtual Machine is defined by the **JVM Specification** (Java SE 8: JVMS, Java SE 17: JSR 392). It is an abstract computing machine with:

- An instruction set (bytecodes)
- A set of registers (PC, operand stack, local variables)
- A stack-based execution model
- A garbage-collected heap
- A symbolic reference resolution mechanism

### JVM Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     HOTSPOT JVM ARCHITECTURE                  │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               CLASS LOADING SUBSYSTEM                     │ │
│  │  (Bootstrap/Extension/Application/Custom ClassLoaders)   │ │
│  └────────────────────────┬─────────────────────────────────┘ │
│                           │                                    │
│                           ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              RUNTIME DATA AREAS                           │ │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐ │ │
│  │  │ Method Area  │  │    Heap      │  │  Java Stacks     │ │ │
│  │  │ (Class data) │  │ (Objects)    │  │  (per-thread)    │ │ │
│  │  └─────────────┘  └──────────────┘  └──────────────────┘ │ │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐ │ │
│  │  │ PC Register │  │Native Method │  │  Metaspace (8+)  │ │ │
│  │  │ (per-thread)│  │   Stacks     │  │ (class metadata) │ │ │
│  │  └─────────────┘  └──────────────┘  └──────────────────┘ │ │
│  └────────────────────────┬─────────────────────────────────┘ │
│                           │                                    │
│                           ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               EXECUTION ENGINE                            │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │ │
│  │  │Interpreter│  │ C1 JIT  │  │ C2 JIT  │  │ GC      │ │ │
│  │  │ (bytecode)│  │(client) │  │(server) │  │(collector)│ │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              NATIVE INTERFACE                             │ │
│  │  (JNI: Java Native Interface, JVM TI: Tool Interface)    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Class Loader** | Loads .class files into the JVM, verifies bytecode, links symbolic references |
| **Runtime Data Areas** | Heap, Method Area, Stacks, PC Registers, Native Method Stacks |
| **Execution Engine** | Interprets bytecodes; JIT compilers (C1, C2) compile to native code |
| **Garbage Collector** | Automatic memory management (deallocates unreachable objects) |
| **JNI** | Interface for calling native C/C++ code |

---

## 2. Class Loading Mechanism

### The Three-Phase Process

Class loading is divided into three phases:

```
Loading → Linking (Verification → Preparation → Resolution) → Initialization
```

**1. Loading:**
- Find the binary representation (`.class` file bytes)
- Create `java.lang.Class` object in the method area
- The class loader does the actual byte loading

**2. Linking:**
- **Verification:** Ensure bytecodes are valid (no illegal jumps, correct types)
- **Preparation:** Allocate static fields with default values (0, null, false)
- **Resolution:** Resolve symbolic references to direct references (optional — may be deferred to first use)

**3. Initialization:**
- Execute the `<clinit>` method (static initializers + static field assignments)
- Happens when: first `new`, `getstatic`, `putstatic`, `invokestatic`, or `Class.forName()`

### ClassLoader Delegation Model

```java
// The loadClass method (simplified):
protected Class<?> loadClass(String name, boolean resolve)
        throws ClassNotFoundException {
    // Step 1: Check if already loaded
    Class<?> c = findLoadedClass(name);
    if (c == null) {
        try {
            // Step 2: Delegate to parent
            if (parent != null) {
                c = parent.loadClass(name, false);
            } else {
                // Bootstrap classLoader (null parent)
                c = findBootstrapClassOrNull(name);
            }
        } catch (ClassNotFoundException e) {
            // Parent couldn't load it
        }
        if (c == null) {
            // Step 3: Load it ourselves
            c = findClass(name);
        }
    }
    if (resolve) resolveClass(c);
    return c;
}
```

### ClassLoader Hierarchy in Java 9+ (Modules)

```
┌────────────────────────────────────────────┐
│         BOOTSTRAP ClassLoader              │
│  (null — native, loads java.base module)  │
├────────────────────────────────────────────┤
│         PLATFORM ClassLoader              │
│  (replaced Extension ClassLoader)         │
│  Loads: java.xml, java.sql, etc.          │
├────────────────────────────────────────────┤
│         APPLICATION ClassLoader           │
│  (System ClassLoader)                     │
│  Loads: -cp, module path, application      │
├────────────────────────────────────────────┤
│         CUSTOM ClassLoader                │
│  (your implementation)                    │
└────────────────────────────────────────────┘
```

### Custom ClassLoader Patterns

```java
// 1. Parent-first (standard delegation) — default behavior
// 2. Parent-last (child-first) — used by Tomcat, hot-reload tools
// 3. Isolated — no parent delegation at all (container scenarios)

// Parent-last ClassLoader (Tomcat-style):
public class ChildFirstClassLoader extends URLClassLoader {
    
    public ChildFirstClassLoader(URL[] urls, ClassLoader parent) {
        super(urls, parent);
    }
    
    @Override
    protected Class<?> loadClass(String name, boolean resolve)
            throws ClassNotFoundException {
        // 1. Check if already loaded (NEEDS to be first for safety)
        Class<?> c = findLoadedClass(name);
        if (c != null) return c;
        
        // 2. Try local first (CHILD FIRST!)
        try {
            c = findClass(name);
            if (resolve) resolveClass(c);
            return c;
        } catch (ClassNotFoundException e) {
            // Not found locally — delegate to parent
        }
        
        // 3. Delegate to parent
        return super.loadClass(name, resolve);
    }
}
```

### ClassLoader Namespace Isolation

Each ClassLoader instance defines its own namespace:

```java
// Same class, different ClassLoaders → different types!
ClassLoader loader1 = new URLClassLoader(new URL[]{jarUrl});
ClassLoader loader2 = new URLClassLoader(new URL[]{jarUrl});

Class<?> class1 = loader1.loadClass("com.example.MyClass");
Class<?> class2 = loader2.loadClass("com.example.MyClass");

class1 != class2                    // TRUE — different classes!
class1.getClassLoader() != class2.getClassLoader()  // TRUE
class1.isAssignableFrom(class2)     // FALSE
class1.newInstance() instanceof class2  // COMPILE ERROR — different types!
```

---

## 3. Runtime Data Areas

### Per-Thread Areas

| Area | What It Stores | Size | Overflow |
|------|---------------|------|----------|
| **PC Register** | Current bytecode address | ~4 bytes (native) | N/A |
| **Java Stack** | Frames (local variables, operand stack, frame data) | Configurable (-Xss, default ~1MB) | StackOverflowError |
| **Native Stack** | Native method call frames | Platform-dependent | StackOverflowError |

### Shared Areas

| Area | What It Stores | Overflow |
|------|---------------|----------|
| **Heap** | All objects and arrays | OutOfMemoryError: Java heap space |
| **Method Area** | Class metadata (methods, fields, bytecode, constant pool) | OutOfMemoryError: Metaspace |

### Heap Structure (Generational)

```
┌──────────────────────────────────────────────────────────────┐
│                          HEAP                                 │
├─────────────┬──────────────┬─────────────────────────────────┤
│             │              │                                  │
│    Young    │   Survivor   │           Old                    │
│   (Eden)    │  (S0 / S1)  │       (Tenured)                  │
│             │              │                                  │
│  ┌───────┐  │ ┌────┐ ┌──┐ │  ┌───────────────────────────┐  │
│  │       │  │ │    │ │  │ │  │                           │  │
│  │ New   │  │ │ S0 │ │S1│ │  │   Long-lived objects      │  │
│  │ Objects│  │ │    │ │  │ │  │                           │  │
│  └───────┘  │ └────┘ └──┘ │  └───────────────────────────┘  │
│             │              │                                  │
└─────────────┴──────────────┴─────────────────────────────────┘
```

### Object Layout in Heap

```java
// A Java object in HotSpot (64-bit, compressed OOPs):
//
// ┌──────────────────────────────────────────────────────┐
// │                  OBJECT HEADER                        │
// ├────────────────────┬─────────────────────────────────┤
// │    Mark Word       │      Klass Pointer              │
// │    8 bytes (64-bit)│     4 bytes (compressed)        │
// │                    │     OR 8 bytes (uncompressed)   │
// ├────────────────────┴─────────────────────────────────┤
// │                     INSTANCE DATA                     │
// │  (fields in order: parent fields → child fields)    │
// ├──────────────────────────────────────────────────────┤
// │                     PADDING                           │
// │  (aligned to 8-byte boundary)                       │
// └──────────────────────────────────────────────────────┘

// MARK WORD breakdown:
// | unused:25 | identity_hash:31 | age:4 | biased_lock:1 | lock:2 |
//
// Lock states encoded in mark word:
// - 00: Lightweight Locked (CAS on mark word)
// - 01: Unlocked (or biased, if biased_lock=1)
// - 10: Heavyweight Locked (mutex)
// - 11: Marked for GC
```

---

## 4. Garbage Collection — Deep Dive

### Generational Hypothesis

The generational GC design is based on two empirical observations:
1. **Most objects die young** (Weak Generational Hypothesis)
2. **Few references from old to young objects**

```
┌──────────────────────────────────────────────────────────────┐
│                     GENERATIONAL GC                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐     ┌──────────┐     ┌──────────────────┐     │
│  │  Young   │────→│ Survivor │────→│      Old         │     │
│  │  (Eden)  │     │ (S0/S1)  │     │  (Tenured)       │     │
│  └──────────┘     └──────────┘     └──────────────────┘     │
│       │                │                      │              │
│       │ Minor GC       │ Minor GC             │ Major GC     │
│       │ (STW)          │ (STW)                │ (STW, slower) │
│       ▼                ▼                      ▼              │
│   Dead objects     Aged objects          Promoted objects    │
│   collected        promoted after         until Full GC     │
│                      age threshold                           │
└──────────────────────────────────────────────────────────────┘
```

### GC Algorithm Comparison

| Algorithm | STW? | Compacts? | Description |
|-----------|------|-----------|-------------|
| **Serial** | Yes (all) | Yes | Single-threaded mark-sweep-compact |
| **Parallel** | Yes (all) | Yes | Multi-threaded mark-sweep-compact |
| **CMS** | Concurrent mark + STW initial/remark | No (sweep only) | Concurrent mark-sweep (fragmentation!) |
| **G1** | Young + mixed (STW), marking concurrent | Yes (evacuation) | Region-based, concurrent marking |
| **ZGC** | Sub-ms STW | Concurrent | Colored pointers, load barriers |
| **Shenandoah** | Sub-ms STW | Concurrent | Brooks pointers, forwarding |

### GC Types in HotSpot

| JVM Flag | Collector | Young GC | Old GC |
|----------|-----------|----------|--------|
| `-XX:+UseSerialGC` | Serial | Serial (STW, single thread) | Serial (STW, single thread) |
| `-XX:+UseParallelGC` | Parallel | Parallel (STW, multi-thread) | Parallel (STW, multi-thread) |
| `-XX:+UseConcMarkSweepGC` | CMS + ParNew | ParNew (STW, multi-thread) | CMS (concurrent mark-sweep) |
| `-XX:+UseG1GC` | G1 | G1 (STW, multi-thread) | G1 (concurrent marking) |
| `-XX:+UseZGC` | ZGC | N/A (single generation) | ZGC (concurrent, sub-ms) |
| `-XX:+UseShenandoahGC` | Shenandoah | N/A (single generation) | Shenandoah (concurrent, sub-ms) |

### GC Trigger Points

```
┌──────────────────────────────────────────────────────────────┐
│                    GC TRIGGER MATRIX                          │
├──────────────────────┬───────────────────────┬───────────────┤
│  Trigger              │  Young GC             │  Full GC      │
├──────────────────────┼───────────────────────┼───────────────┤
│  Eden full            │  ✓ Immediate          │  Not directly  │
│  Old gen full         │  —                     │  ✓ Immediate   │
│  System.gc()          │  —                     │  ✓ (if enabled)│
│  Metaspace threshold  │  —                     │  ✓             │
│  Heap dump            │  —                     │  ✓ (depends)   │
│  G1 concurrent mode   │  —                     │  ✓ (emergency) │
│    failure            │                        │               │
└──────────────────────┴───────────────────────┴───────────────┘
```

### GC Roots

Objects considered "alive" start from **GC Roots**:

```
┌──────────────────────────────────────────────────────────────┐
│                     GC ROOTS                                  │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Thread stack local variables and method arguments         │
│  2. Static fields of loaded classes                           │
│  3. JNI global/weak global references                         │
│  4. Active monitor locks                                      │
│  5. JVM internal references (system classes, JIT code)       │
│  6. String intern table                                       │
│  7. Finalizable objects (objects with finalize() pending)    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Object Finalization — The Anti-Pattern

```java
// DO NOT RELY ON finalize()!
// - Unpredictable timing (GC cycle dependent)
// - Can resurrect objects (bad practice)
// - Deprecated in Java 9, removed in Java 18

// INSTEAD, use:
// 1. try-with-resources (AutoCloseable)
// 2. Cleaner (Java 9+, PhantomReference-based)
// 3. Explicit close() methods

public class DatabaseConnection implements AutoCloseable {
    private Connection conn;
    
    public DatabaseConnection(String url) {
        this.conn = DriverManager.getConnection(url);
    }
    
    @Override
    public void close() {
        if (conn != null) {
            conn.close();
            conn = null;
        }
    }
}

// Usage — guaranteed cleanup:
try (DatabaseConnection db = new DatabaseConnection("jdbc:...")) {
    db.query("SELECT * FROM users");
} // close() called automatically, even on exception!
```

### Fallback: Cleaner (Java 9+)

```java
// Cleaner is a lighter, more predictable alternative to finalize():
public class CleanableResource implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();
    private final Cleaner.Cleanable cleanable;
    private final Resource resource;
    
    // Inner static (non-capturing) class for cleanup
    private static class Cleanup implements Runnable {
        private final Resource resource;
        
        Cleanup(Resource resource) { this.resource = resource; }
        
        @Override
        public void run() {
            resource.close();  // Native cleanup
        }
    }
    
    public CleanableResource(Resource resource) {
        this.resource = resource;
        this.cleanable = CLEANER.register(this, new Cleanup(resource));
    }
    
    @Override
    public void close() {
        cleanable.clean();  // Explicit cleanup
    }
}
```

---

## 5. G1 GC Detailed Walkthrough

### Region-Based Heap

G1 divides the heap into **~2048 regions** (each 1MB-32MB depending on heap size):

```
Region size = heap_size / 2048 (rounded to nearest power of 2, between 1MB and 32MB)

Example: 8GB heap → 8GB / 2048 = 4MB regions
```

### G1 Region Types

```
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ E  │ E  │ E  │ E  │ E  │ S  │ S  │ O  │ O  │ O  │ O  │ O  │ H  │ H  │ O  │ O  │
├────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┤
│  Eden (green)     │Surv│       Old (blue)              │Hum│  Old (continued)   │
│  Young Generation │    │                              │on │                     │
│                   │    │                              │g  │                     │
└───────────────────┴────┴──────────────────────────────┴───┴─────────────────────┘
```

### G1 Memory Structures

| Data Structure | Description |
|---------------|-------------|
| **RSet (Remembered Set)** | Per-region set of incoming references from OTHER regions. Stored as card index arrays or hash tables |
| **Card Table** | 512-byte cards across entire heap. Dirty cards indicate modified references. |
| **PRT (Per Region Table)** | Encoding for RSets. Compressed to save memory |
| **SATB (Snapshot At The Beginning)** | Snapshot of object graph at start of concurrent marking |
| **TAMS (Thread-Local Allocation Buffers)** | Thread-local allocation pointers (next TAMS = start of this GC cycle) |

### The G1 GC Cycle — Detailed

```
PHASE 1: YOUNG GC (stop-the-world)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: Eden fills above threshold                         │
│  Duration: ~5-50ms                                           │
│                                                               │
│  1. Select collection set (CSet) = all Eden + Survivor       │
│  2. Scan roots: thread stacks, VM data structures            │
│  3. Drain dirty card queue (update RSets during scan)        │
│  4. RSet scanning: find incoming refs from old gen → young   │
│  5. Copy live objects from CSet regions to other regions     │
│  6. Handle references from old → young (fix up after copy)   │
│                                                               │
│  After Young GC: Eden is empty, live objects promoted        │
│                  to Survivor or Old (if age threshold met)   │
│                                                               │
│  If concurrent marking is in progress:                        │
│    Young GC also includes "initial mark" pause               │
└──────────────────────────────────────────────────────────────┘

PHASE 2: CONCURRENT MARKING (concurrent with application)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: IHOP (Initiating Heap Occupancy Percent, default   │
│            45%) exceeded                                      │
│                                                               │
│  Sub-phase 2a: Initial Mark (STW, ~1ms)                     │
│    - Piggybacks on Young GC                                   │
│    - Marks all GC roots                                       │
│    - Sets TAMS (top-at-mark-start) for each region            │
│                                                               │
│  Sub-phase 2b: Concurrent Mark (concurrent, 10-100ms)        │
│    - Walk object graph from roots                             │
│    - Use SATB to handle concurrent mutations                  │
│    - Process SATB buffers (per-thread queues)                 │
│    - Gray objects: discovered but not yet processed           │
│    - Mark bitmaps: 1 bit per heap word (live/dead)           │
│                                                               │
│  Sub-phase 2c: Remark (STW, ~1ms)                           │
│    - Finalize marking: drain SATB buffers                     │
│    - Reference processing (SoftReference, Weak, Phantom)     │
│    - Class unloading (remove dead classes)                    │
│    - Compute per-region liveness                              │
│                                                               │
│  Sub-phase 2d: Cleanup (STW, ~1ms)                           │
│    - Identify regions with most garbage (for mixed GC)       │
│    - RSet scrubbing (remove stale entries)                    │
│    - Determine collection set for mixed GC phase             │
└──────────────────────────────────────────────────────────────┘

PHASE 3: MIXED GC (STW, multiple pauses)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: After concurrent mark completes                     │
│  Duration: Multiple STW pauses (~10-50ms each)               │
│  Count: -XX:G1MixedGCCountTarget (default: 8)                │
│                                                               │
│  Each mixed GC collects:                                      │
│   - All Eden + Survivor (like young GC)                       │
│   - PLUS some Old regions (those with most garbage first)    │
│                                                               │
│  Selection order: Old regions sorted by liveness (greedy):   │
│   Region 5: 5% live → collect first                          │
│   Region 12: 15% live → collect second                        │
│   Region 3: 80% live → skip (not worth collecting)           │
│                                                               │
│  Evacuation: copy live objects to other regions, compact     │
│  Old regions are reclaimed when all live objects evacuated   │
│                                                               │
│  Continues until: G1HeapWastePercent (default 5%) reached    │
└──────────────────────────────────────────────────────────────┘

PHASE 4: FULL GC (STW, fallback — EMERGENCY)
┌──────────────────────────────────────────────────────────────┐
│  Trigger: Concurrent Mode Failure (concurrent marking too    │
│           slow, heap filling up before reclaim)              │
│  Duration: Can take SECONDS to MINUTES on large heaps        │
│                                                               │
│  1. Single-threaded mark-sweep-compact (Java 8)              │
│  2. Parallel mark-sweep-compact (Java 9+, ParallelGC)        │
│  3. COMPACTS the ENTIRE heap (defragmentation)               │
│  4. All threads stopped for entire duration                  │
│                                                               │
│  TO AVOID: increase heap, increase ConcGCThreads,            │
│            lower InitiatingHeapOccupancyPercent               │
└──────────────────────────────────────────────────────────────┘
```

### G1 Tuning Parameters

```bash
# PAUSE TIME TARGET
-XX:MaxGCPauseMillis=200           # Default: 200ms. G1 adjusts young gen size to hit this.

# CONCURRENT THREADS
-XX:ConcGCThreads=4                # Default: (ParallelGCThreads + 2) / 4. 
                                    # More → faster marking but more CPU overhead.
-XX:ParallelGCThreads=8            # Default: CPU cores. STW worker threads.

# IHOP (Initiating Heap Occupancy)
-XX:InitiatingHeapOccupancyPercent=45  # Default: 45%. Start concurrent marking when 
                                         # old gen is 45% full.
-XX:G1HeapWastePercent=5           # Default: 5%. Stop mixed GC when waste < 5%.

# MIXED GC
-XX:G1MixedGCCountTarget=8         # Default: 8. Number of mixed GC pauses.
-XX:G1MixedGCLiveThresholdPercent=85  # Default: 85%. Don't collect regions with >85% live.

# REGION SIZE
-XX:G1HeapRegionSize=4m            # Auto-calculated, can force specific size.

# RESERVATION
-XX:G1ReservePercent=10            # Default: 10%. Reserved space for "full promotion".
-XX:-G1UseAdaptiveIHOP             # Disable adaptive IHOP (use fixed).
```

### Analyzing G1 Logs

```
# Young GC:
2024-01-15T10:30:00.000+0000: [GC pause (G1 Evacuation Pause) (young)
  Desired survivor size 10485760 bytes, new threshold 15 (max 15)
  [Eden: 2048.0M(2048.0M)->0.0B(2048.0M) 
   Survivors: 256.0M->256.0M 
   Heap: 4096.0M(8192.0M)->2048.0M(8192.0M)]
  [Times: user=0.08 sys=0.01, real=0.02 secs]

# Concurrent Mark:
2024-01-15T10:30:00.000+0000: [GC concurrent-root-region-scan-start]
2024-01-15T10:30:00.020+0000: [GC concurrent-root-region-scan-end, 0.020 secs]
2024-01-15T10:30:00.020+0000: [GC concurrent-mark-start]
2024-01-15T10:30:00.200+0000: [GC concurrent-mark-end, 0.180 secs]

# Mixed GC:
2024-01-15T10:30:00.000+0000: [GC pause (G1 Evacuation Pause) (mixed)
  [Eden: 1024.0M(1024.0M)->0.0B(1024.0M) 
   Survivors: 128.0M->128.0M 
   Heap: 5120.0M(8192.0M)->4096.0M(8192.0M)]
  [Times: user=0.12 sys=0.02, real=0.03 secs]

# Full GC (BAD!):
2024-01-15T10:30:00.000+0000: [Full GC (Allocation Failure)
  8192M->4096M(8192M), 2.345 secs]
  [Times: user=4.56 sys=0.12, real=2.35 secs]
```

---

## 6. ZGC — Colored Pointers & Load Barriers

### Overview

ZGC (Z Garbage Collector) is designed for:
- **Sub-millisecond pause times** (<1ms goal)
- **Heaps up to 16TB** (64-bit address space uses 44 bits)
- **Concurrent compaction** (no stop-the-world)
- **No per-object GC metadata** (no GC header overhead)

### Colored Pointers (64-bit Reinterpretation)

```
63  48|47    45|44                     3|2 1 0  ← bit positions
  ┌────┴──────┴─────────────────────────┴────┐
  │   Unused    │  Metadata  │   Object Offset   │ 0 │
  └─────────────┴────────────┴────────────────────┴───┘
                  ↑            ↑
                  │            └── Address bits (45 bits → 32TB addressable)
                  └── Metadata bits (3 bits):
                      M0: Marked by current marking cycle (bit 45)
                      M1: Marked by previous marking cycle (bit 46)
                      R:  Remapped/relocated (bit 47)
```

### Load Barrier

ZGC's load barrier is triggered on **every reference load from the heap**:

```java
// When Java code does:
Object field = obj.someField;

// The JIT-compiled code executes a load barrier:
// In pseudo-code:
Object load_barrier(Object ref) {
    if (is_good(ref)) {
        return ref;  // Fast path: metadata bits indicate valid pointer
    }
    return slow_path(ref);  // Need to fix up (mark or remap)
}

// The "is_good" check:
// - If M0 = 1 AND R = 1 → good (object is alive and relocated)
// - If M0 = 0 but M1 = 1 → object was alive but needs re-mark
// - If R = 0 → object needs remapping

// Slow path operations:
// 1. Remap: update pointer to new location (self-healing)
// 2. Mark: if pointer is from unmarked region, mark the referent

// Self-healing: the pointer is updated atomically so subsequent accesses
// don't hit the slow path!
```

### ZGC Phase Details

```
┌──────────────────────────────────────────────────────────────┐
│                     ZGC CYCLE                                │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Phase 1: Pause Mark Start (STW, <1ms)                      │
│  └─ Identify GC roots (thread stacks, globals, etc.)         │
│  └─ No object scanning, just root identification              │
│  └─ Flip M0/M1 (swap current/previous marking cycle)         │
│                                                               │
│  Phase 2: Concurrent Mark (concurrent with application)     │
│  └─ Trace live objects from roots                             │
│  └─ Load barrier: if mutator reads unmarked object → mark   │
│  └─ Remap dead objects from previous cycle                   │
│  └─ When all objects marked: end concurrent mark             │
│                                                               │
│  Phase 3: Pause Mark End (STW, <1ms)                        │
│  └─ Finalize marking (ensure no mutator-marked objects lost) │
│  └─ Prepare for relocation phase                              │
│                                                               │
│  Phase 4: Concurrent Relocation (concurrent with app)       │
│  └─ Move live objects to new locations (compact)             │
│  └─ Forward table maps old → new for in-progress accesses    │
│  └─ Load barrier: stale pointer → remap + self-heal          │
│  └─ When all objects relocated: end concurrent relocation    │
│                                                               │
│  Phase 5: Pause Relocate End (STW, <1ms)                    │
│  └─ Clean up forwarding tables                                │
│  └─ Free unused memory (return to OS)                         │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### ZGC Tuning

```bash
# Basic usage:
-XX:+UseZGC

# Key tuning:
-XX:ConcGCThreads=4               # Concurrent GC threads
-XX:ParallelGCThreads=8           # STW parallel workers
-XX:ZAllocationSpikeTolerance=2.0  # Handle allocation spikes (default: 2.0)
-XX:+ZProactive                   # Proactive GC cycles (default: on)
-XX:ZUncommitDelay=300            # Delay before returning memory to OS (seconds)
-XX:SoftMaxHeapSize=280g          # Target heap size (GC tries to stay under)
```

### ZGC Limitations

- **CPU overhead**: Load barrier ~2-5% CPU cost on all reference loads
- **Large heap required**: Multi-TB is ideal; works well above 4GB
- **Not for small heaps**: Below 4GB, G1 or Serial may be better
- **Compressed OOPs not supported**: Slightly more memory usage (larger pointers)
- **No generational GC**: All objects treated equally (changes in Java 22+)

---

## 7. Shenandoah GC

### Overview

Shenandoah (OpenJDK 12+) is similar to ZGC but uses a different approach:

- **Brooks pointer**: Single forwarding pointer embedded in object header
- **GC barrier** on ALL heap accesses (reads AND writes)
- **Concurrent compaction**: Moves objects concurrently

### Comparison: ZGC vs Shenandoah

| Aspect | ZGC | Shenandoah |
|--------|-----|-----------|
| Pointer approach | Colored pointers (bit stealing) | Brooks pointer (header forwarding) |
| Barrier type | Load barrier only | Read + write barriers |
| Compressed OOPs | Not supported | Supported |
| Heap size limit | 16TB | 2TB (with compressed OOPs) |
| Pause time | <1ms | <1ms |
| CPU overhead | ~2-5% | ~5-10% |
| Region-based | Yes (one generation) | Yes (one generation) |
| Maturity | Production (Java 15+) | Production (Java 15+) |

### Shenandoah Brooks Pointer

```
┌──────────────────────────────────────────────────────────────┐
│              SHENANDOAH OBJECT LAYOUT                         │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────┬─────────────┬─────────────────────────┐      │
│  │  Mark Word │  Brooks     │  Instance Data           │      │
│  │  (8 bytes) │  Forward    │  (fields)               │      │
│  │            │  Pointer    │                          │      │
│  │            │  (8 bytes)  │                          │      │
│  └────────────┴─────────────┴──────────────────────────┘      │
│                                                               │
│  Brooks pointer:                                               │
│  - Points to itself (no relocation)                           │
│  - Points to new location (after relocation)                  │
│  - Write barrier updates Brooks pointer during concurrent move │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Java Memory Model

### Key Definitions

The JMM (JSR-133, Java 5+) defines:

- **Actions**: reads, writes, locks, unlocks, thread starts/joins
- **Inter-thread Actions**: the actions that create happens-before edges
- **Happens-Before**: partial ordering of actions
- **Sequential Consistency**: all actions appear in a total order consistent with program order

### Happens-Before Rules (JLS §17.4.5)

```
1. Program order: each action in a thread happens-before every later action
   in that thread

2. Monitor lock: unlock of monitor m happens-before every subsequent lock of m

3. Volatile: write to volatile field v happens-before every subsequent read of v

4. Thread.start(): Thread.start() happens-before any action in the started thread

5. Thread.join(): any action in a thread happens-before any other thread
   successfully returns from join() on that thread

6. Transitivity: if A happens-before B and B happens-before C, then
   A happens-before C
```

### The Causality Requirements

The JMM requires that executions be **causally consistent**:

```java
// Without causality requirements, this could happen:
int r1 = x;
if (r1 == 1) y = 1;
int r2 = y;
if (r2 == 1) x = 1;
// r1 = 1, r2 = 1 is a valid result under JMM!
// This is known as "out of thin air" values — allowed by JMM but
// practically impossible on real hardware.
```

### Memory Barriers

| Barrier | Description | x86 | ARM64 |
|---------|-------------|-----|-------|
| **LoadLoad** | All loads before barrier complete before any load after | Not needed | DMB ISHLD |
| **LoadStore** | Loads before barrier complete before stores after | Not needed | DMB ISH |
| **StoreStore** | Stores before barrier complete before stores after | Not needed | DMB ISHST |
| **StoreLoad** | Stores before barrier complete before loads after | MFENCE/LOCK | DMB ISH |

### JMM Mappings to Hardware

| Java Action | x86-64 | ARM64 |
|-------------|--------|-------|
| Volatile read | Normal load (acquire semantics) | LDAR |
| Volatile write | MOV + MFENCE (or LOCK XADD) | STLR |
| Monitor enter | Normal load + CAS (or LOCK CMPXCHG) | LDAR + CAS |
| Monitor exit | Normal store | DMB + STLR |
| Normal field read | Normal load | Normal load |
| Normal field write | Normal store | Normal store (with store buffer) |

### final Fields — Initialization Safety

```java
public class FinalFieldExample {
    final int x;     // final — initialization safety applies
    int y;           // NOT final — no guarantee
    
    static FinalFieldExample instance;
    
    public FinalFieldExample() {
        x = 1;       // 1. Write to final field
        y = 2;       // 2. Write to normal field
    }
    
    // Thread A:
    static void writer() {
        instance = new FinalFieldExample();  // 3. Publish
    }
    
    // Thread B:
    static void reader() {
        if (instance != null) {
            int r1 = instance.x;  // 4. Guaranteed to see 1 (final field guarantee)
            int r2 = instance.y;  // 5. Might see 0 (NO guarantee for non-final!)
        }
    }
    
    // JMM guarantees for final fields (JLS §17.5):
    // 1. Write to final field (1) happens-before any subsequent freeze action
    // 2. Freeze action happens-before any load of the reference (4)
    // 3. Therefore: x == 1 is guaranteed
    // 4. y might be 0 because there's no happens-before edge from (2) to (5)
}
```

### volatile Semantics

```java
// volatile guarantees:
// 1. Write to volatile v → happens-before → any subsequent read of v
// 2. Compiler cannot reorder volatile accesses with other volatile accesses
// 3. Compiler cannot reorder volatile accesses with surrounding memory operations

// What volatile does NOT guarantee:
// 1. Atomicity of compound operations (++v, v += 1)
// 2. Mutual exclusion
```

---

## 9. JIT Compilation — C1 & C2

### Tiered Compilation

```java
// 5 compilation levels (Java 8+):
//
// Level 0: Interpreter
// Level 1: C1 with no profiling (simple, no counters)
// Level 2: C1 with limited profiling 
// Level 3: C1 with full profiling (counts + branch profile)
// Level 4: C2 — fully optimized (maximum optimization)
//
// Flow:
// 0 → 3 → 4     (normal: interpreted → C1 profiled → C2 optimized)
// 0 → 2 → 3 → 4 (limited profiling → full → C2)
// 0 → 3 → 1     (C2 queue overflow → fallback to C1 without profiling)
// 0 → 1         (trivial methods → C1 simple, no C2 needed)

// Counter mechanism:
// Method entry counter: increments on each call
// Back-edge counter: increments on loop backedge
// -XX:CompileThreshold=10000  (default invocation count for C1)
// C2 threshold: ~1.5x C1 threshold
// Both counters decay over time (half-life ~5s) → cold methods lose counters

// CICompilerCount:
// Number of compiler threads (default: 2 per core, max 16)
// C1 threads: background, high priority
// C2 threads: background, high priority
// Queues: C1 and C2 have separate task queues
```

### C2 Optimizations

| Optimization | Description |
|-------------|-------------|
| **Inlining** | Replace method call with method body (default max: 325 bytes) |
| **Sparse Conditional Constant Propagation** | Eliminate branches with constant-predicate conditions |
| **Loop Optimizations** | Unrolling, peeling, invariant code motion |
| **Escape Analysis** | Object allocated on stack if it doesn't escape method |
| **Lock Elision** | Remove lock on thread-local object (escape analysis) |
| **Lock Coarsening** | Merge adjacent same-lock synchronized blocks |
| **Null Check Elimination** | Remove redundant null checks |
| **Bounds Check Elimination** | Remove array bounds checks when provably safe |
| **Intrinsics** | Replace known methods with CPU-specific instructions |
| **Vectorization** | Use SIMD instructions (e.g., for array loops) |
| **SPECULATION** | Optimize for common path, deoptimize if wrong |

### Inlining Heuristics

```java
// Default inlining limits:
// -XX:MaxInlineSize=35          # Maximum bytecode size to inline (small methods)
// -XX:FreqInlineSize=325        # Maximum bytecode size for hot methods
// -XX:MaxInlineLevel=9          # Maximum nesting depth
// -XX:InlineSmallCode=1000      # Maximum native code size of callee

// Methods always inlined:
// - Methods marked as final
// - Methods in interfaces (default methods)
// - This method calls
// - Super method calls
// - Methods with @ForceInline (JVM internal)
```

### Deoptimization

```java
// Deoptimization occurs when:
// 1. Class loading: new class changes assumptions (e.g., new subclass)
//    → "This method was monomorphic, now it's bimorphic!"
// 2. Profiling disagreement: actual execution path differs from profiled
// 3. Uncommon trap: executing a rarely-taken branch
// 4. Made not entrant: old compilations become stale after class loading
// 5. Made zombie: compiled code can be GC'd

// Deoptimization rolls back to interpreter state:
// 1. The JIT-compiled code has a "safepoint-enabled" state map
// 2. On deopt, registers → stack (execution reverts to interpreter)
// 3. The interpreter continues executing the method
```

### Escape Analysis Example

```java
public class EscapeAnalysisDemo {
    
    // Object does NOT escape → JIT allocates on STACK
    public long sum(int[] values) {
        Point p = new Point(0, 0);  // ← Stack-allocated after EA
        for (int v : values) {
            p.x += v;
            p.y += v;
        }
        return p.x + p.y;
        // Point p is never accessed outside this method
    }
    
    // Object ESCAPES → must be heap-allocated
    public Point create(int x, int y) {
        return new Point(x, y);  // ← Returns the object (escapes!)
    }
    
    // With Escape Analysis, synchronized also elided:
    public long sumSynchronized(int[] values) {
        // This StringBuffer is thread-local → lock elision!
        StringBuffer sb = new StringBuffer();
        for (int v : values) {
            sb.append(v);  // synchronized removed by JIT!
        }
        return sb.length();
    }
}
```

---

## 10. Bytecode Structure & Instructions

### Class File Structure

```
ClassFile {
    u4             magic;               // 0xCAFEBABE
    u2             minor_version;
    u2             major_version;        // 61 = Java 17, 65 = Java 21
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
    attribute_info attributes[attributes_count];
}
```

### Access Flags

| Flag | Value | Meaning |
|------|-------|---------|
| ACC_PUBLIC | 0x0001 | Declared public |
| ACC_PRIVATE | 0x0002 | Declared private |
| ACC_PROTECTED | 0x0004 | Declared protected |
| ACC_STATIC | 0x0008 | Declared static |
| ACC_FINAL | 0x0010 | Declared final |
| ACC_SYNCHRONIZED | 0x0020 | Synchronized method |
| ACC_VOLATILE | 0x0040 | Volatile field |
| ACC_TRANSIENT | 0x0080 | Transient field |
| ACC_NATIVE | 0x0100 | Native method |
| ACC_INTERFACE | 0x0200 | Is an interface |
| ACC_ABSTRACT | 0x0400 | Abstract |
| ACC_STRICT | 0x0800 | strictfp |
| ACC_SYNTHETIC | 0x1000 | Compiler-generated |
| ACC_ANNOTATION | 0x2000 | Is an annotation |
| ACC_ENUM | 0x4000 | Is an enum |

### Common Bytecodes

```
LOAD/STORE:
  aload_0         # Load 'this' onto stack
  aload_1         # Load first argument
  iload_0         # Load int local 0
  istore_1        # Store int to local 1
  astore_2        # Store reference to local 2

ARITHMETIC:
  iadd            # int add (pop 2, push 1)
  isub            # int subtract
  imul            # int multiply
  idiv            # int divide
  iinc 0 1        # Increment local 0 by 1

OBJECT:
  new #Class       # Create new object
  getfield #Field  # Get instance field
  putfield #Field  # Set instance field
  getstatic #Field # Get static field
  putstatic #Field # Set static field
  instanceof #Class# Type check
  checkcast #Class # Type cast
  arraylength      # Get array length

METHOD:
  invokevirtual #Method     # Virtual dispatch
  invokespecial #Method     # Constructor, super, private
  invokestatic #Method      # Static method
  invokeinterface #Method   # Interface method
  invokedynamic #Method     # Lambda, method reference (Java 7+)

STACK:
  dup              # Duplicate top of stack
  pop              # Pop top of stack
  swap             # Swap top two stack items
  ldc #String      # Push constant from pool
  iconst_0         # Push int 0

CONTROL:
  ifeq <label>     # if == 0, branch
  ifne <label>     # if != 0, branch
  if_icmpne <label># Compare ints
  goto <label>     # Unconditional branch
  tableswitch      # Switch statement
  lookupswitch     # Sparse switch
  areturn          # Return reference
  ireturn          # Return int
  return           # Void return

MONITOR:
  monitorenter     # Enter monitor (synchronized)
  monitorexit      # Exit monitor
```

---

## 11. Performance Tuning Tools

### Command-Line Tools

| Tool | Java 9+ | Java 8 | Purpose |
|------|---------|--------|---------|
| jcmd | ✓ | ✓ | Comprehensive JVM diagnostic command |
| jmap | ✓ | ✓ | Heap histogram, heap dump |
| jstack | ✓ | ✓ | Thread dump |
| jstat | ✓ | ✓ | GC stats monitoring |
| jhat | Removed | ✓ | Heap dump analysis |
| jinfo | ✓ | ✓ | JVM configuration |
| jhsdb | ✓ | n/a | HotSpot debugger (replaces jmap/jstack for core dumps) |

### profiler.sh (Async Profiler)

```bash
# CPU profiling:
./profiler.sh -e cpu -d 60 -f cpu_profile.html <pid>

# Allocation profiling:
./profiler.sh -e alloc -d 60 -f alloc_profile.html <pid>

# Wall clock profiling (includes blocked time):
./profiler.sh -e wall -d 60 -f wall_profile.html <pid>

# Lock profiling:
./profiler.sh -e lock -d 60 -f lock_profile.html <pid>

# Combined:
./profiler.sh -e cpu,alloc,lock -d 120 -f combined.html <pid>
```

### JFR (Java Flight Recorder)

```bash
# Start recording from command line:
jcmd <pid> JFR.start duration=60s filename=recording.jfr

# Dump ongoing recording:
jcmd <pid> JFR.dump filename=recording.jfr

# Check recording status:
jcmd <pid> JFR.check

# Start from JVM startup:
-XX:StartFlightRecording=disk=true,duration=60s,filename=recording.jfr

# Event types:
# jdk.AllocationRequiringGC   → allocation pressure
# jdk.GCPhasePause            → GC pause times
# jdk.JavaMonitorEnter        → lock contention
# jdk.ThreadPark              → thread parking
# jdk.Compilation            → JIT compilation events
```

### GC Log Analysis

```bash
# Java 8 format:
-XX:+PrintGCDetails -XX:+PrintGCDateStamps -Xloggc:gc.log

# Java 9+ format (unified logging):
-Xlog:gc*=info:file=gc.log:time,uptime,level,tags
-Xlog:gc*=debug:file=gc.log:time,uptime,level,tags  # More detail

# Common analysis tools:
# - GCeasy (https://gceasy.io) — online GC log analyzer
# - GCViewer (https://github.com/chewiebug/GCViewer) — open source
# - jClarity/Censum — commercial GC analysis
```

---

## 12. JVM Internals Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the difference between Stack and Heap memory in Java?</b></summary>

**Answer:**
- **Stack**: Per-thread, stores local variables, method call frames, references to objects. Fixed size (~1MB default). StackOverflowError if exhausted.
- **Heap**: Shared across threads, stores ALL objects and arrays. Configurable size. OutOfMemoryError if full.
- Stack holds: primitives + object references (not objects themselves)
- Heap holds: actual object data
</details>

<details>
<summary><b>Q2: What is the ClassLoader delegation model?</b></summary>

**Answer:** When asked to load a class, a ClassLoader:
1. Checks if the class is already loaded (findLoadedClass)
2. Delegates to parent ClassLoader
3. If parent fails, loads the class itself

This ensures:
- Core Java classes (java.lang.Object) are always loaded by Bootstrap ClassLoader
- No two ClassLoaders can load the same class independently (type safety)
- Prevents multiple versions of same class
</details>

<details>
<summary><b>Q3: What is the purpose of the JIT compiler?</b></summary>

**Answer:** The JIT (Just-In-Time) compiler converts frequently-executed bytecodes to native machine code at runtime:
- **C1 (Client)**: Quick compilation, moderate optimization (for startup)
- **C2 (Server)**: Slow compilation, aggressive optimization (for peak performance)
- Tiered compilation (default since Java 8): starts with interpreter, then C1, then C2
- Key optimizations: inlining, escape analysis, lock elision, loop optimizations
</details>

### Intermediate

<details>
<summary><b>Q4: Explain the different generations of the heap and how Minor/Major GC works.</b></summary>

**Answer:**
- **Young Generation (Eden + 2 Survivor spaces)**: New objects allocated here. Minor GC (STW) collects Eden. Live objects copied to Survivor. Objects that survive multiple GC cycles are promoted to Old generation.
- **Old Generation**: Long-lived objects. Major GC is less frequent but more expensive.
- **Metaspace (Java 8+)**: Class metadata (replaced PermGen). Not part of heap. Grows automatically.

Generational design exploits the "weak generational hypothesis": most objects die young.
</details>

<details>
<summary><b>Q5: What is the difference between Stop-The-World and Concurrent GC?</b></summary>

**Answer:**
- **STW GC**: All application threads are paused while GC runs. Needed for mark/compact phases. Faster but causes latency spikes. Examples: Serial, Parallel GC use STW for all phases.
- **Concurrent GC**: GC runs in parallel with application threads. Uses barriers (read/write/snapshot) to maintain correctness. Lower latency but higher CPU overhead. Examples: ZGC, Shenandoah, G1 concurrent marking.

ZGC achieves <1ms STW pauses by making ALMOST everything concurrent (including object relocation).
</details>

<details>
<summary><b>Q6: How does Escape Analysis improve performance?</b></summary>

**Answer:** Escape Analysis (EA) determines if an object is accessible outside its allocating method:
- If NOT escaping → **Stack allocation** (no GC involvement)
- If NOT escaping → **Lock elision** (remove synchronized on thread-local objects)
- If NOT escaping → **Scalar replacement** (replace object with its fields as local variables)

EA is a C2 optimization. Must be enabled (-XX:+DoEscapeAnalysis, default: on).
</details>

### Advanced

<details>
<summary><b>Q7: How does G1 determine which regions to collect during Mixed GC?</b></summary>

**Answer:** G1 sorts Old regions by liveness (from concurrent marking):
- The G1 calculates which regions have the highest garbage content
- Collection candidate ordering: most dead first (garbage first!)
- `-XX:G1MixedGCLiveThresholdPercent=85` — Skip regions with >85% live objects
- Collects until `-XX:G1HeapWastePercent=5` → if only 5% of heap is garbage, stop

This greedy approach maximizes reclaimed memory per GC pause.
</details>

<details>
<summary><b>Q8: What causes Concurrent Mode Failure in G1? How do you fix it?</b></summary>

**Answer:** Concurrent Mode Failure (CMF) occurs when:
- Old generation fills up during concurrent marking
- G1 cannot allocate new objects
- FALLS BACK to Full GC (STW, can take minutes!)

**Causes:**
- IHOP (Initiating Heap Occupancy Percent) too high → marking starts too late
- ConcGCThreads too low → marking is slow
- Allocation rate too fast → heap fills before marking completes

**Fixes:**
- Lower IHOP: `-XX:InitiatingHeapOccupancyPercent=35`
- Increase conc threads: `-XX:ConcGCThreads=8`
- Increase heap size: `-Xmx...`
- Reduce allocation rate (optimize code)
- Switch to ZGC for very large heaps (CMF = heap filling faster than G1 marks)
</details>

<details>
<summary><b>Q9: How does the JVM handle synchronized at the hardware level?</b></summary>

**Answer:** The JVM uses adaptive locking:
1. **Biased locking** (Java 8-14, removed Java 15+): First thread to acquire sets thread ID in mark word. No atomic instruction needed. If same thread re-enters → no CAS. Revocation requires safepoint.
2. **Lightweight locking**: If biased lock is revoked (different thread tried to acquire), JVM uses CAS on mark word to set "displaced mark word" pointer.
3. **Heavyweight locking**: If contention persists, JVM inflates to OS mutex + condition variables. Threads are parked (not spinning).

On x86: lightweight lock = 1 LOCK CMPXCHG instruction. Heavyweight = pthread_mutex_lock() system call.
</details>

<details>
<summary><b>Q10: Explain the JVM's safepoint mechanism and how it affects latency.</summary>

**Answer:** A safepoint is a point where all threads have a consistent, well-defined state. At a safepoint, the JVM can inspect thread stacks, read roots for GC, or deoptimize.

**How it works:**
- JIT-compiled code has safepoint polls inserted at loop back-edges and method returns
- When a safepoint is requested (GC start, thread dump), the JVM sets a global flag
- Threads check this flag at their next safepoint poll
- Threads in blocked/sleeping states are already at a safepoint

**Latency impact:**
- Normal safepoint: ~1-10ms (all threads reach a poll)
- Long safepoint: >100ms if a thread is in JNI or a long counted loop
- **Diagnosis**: use `-XX:+PrintSafepointStatistics` to see delays

**Mitigation:**
- Ensure native code periodically calls back to Java
- Use counted loop safepoint polls: `-XX:+UseCountedLoopSafepoints`
- Avoid long JNI calls without returning to Java
</details>

<details>
<summary><b>Q11: What are compiler intrinsics? Give examples.</b></summary>

**Answer:** Intrinsics are JVM-recognized methods that the compiler replaces with CPU-specific instructions (not Java bytecode). Examples:

| Intrinsic | What it does |
|-----------|-------------|
| `System.arraycopy()` | `REP MOVS` or `MOVSQ` (x86) — CPU-accelerated copy |
| `Math.sqrt()` | `SQRTSD` (x86) — hardware square root |
| `Integer.bitCount()` | `POPCNT` (x86) — population count instruction |
| `String.compareTo()` | Vectorized with SIMD (AVX2) |
| `Arrays.fill()` | Vectorized with SIMD |
| `CAS operations` | `LOCK CMPXCHG` — hardware atomic compare-and-swap |
| `Object.hashCode()` | Uses hardware random/thread-local seeding |
| `Thread.currentThread()` | Reads thread-local storage (register-based) |

Intrinsics are why Java code can match or beat hand-written C in numeric benchmarks.
</details>

<details>
<summary><b>Q12: How does C2 perform loop unrolling? When is it harmful?</summary>

**Answer:** Loop unrolling replicates loop body to reduce branch overhead and enable vectorization.

```
// Before (counted loop):
for (int i = 0; i < 100; i++) {
    a[i] = b[i] + c[i];
}

// After (unrolled by 4):
for (int i = 0; i < 96; i += 4) {
    a[i] = b[i] + c[i];
    a[i+1] = b[i+1] + c[i+1];
    a[i+2] = b[i+2] + c[i+2];
    a[i+3] = b[i+3] + c[i+3];
}
for (; i < 100; i++) {  // Remainder loop
    a[i] = b[i] + c[i];
}
```

**Harmful when:**
- Loop body is large (code bloat → instruction cache misses)
- Loop iterations are few (benefit doesn't justify code size)
- Loop has many branches (branch mispredictions increase with unrolled code)
</details>

---

## Quick Reference: JVM Internals at a Glance

| Concept | Key Facts |
|---------|-----------|
| JVM Spec | JSR-392 (Java 17), stack-based architecture |
| Class File | Magic: 0xCAFEBABE, major_version: 65 (Java 21) |
| Heap | Eden, S0, S1, Old (generational); or regions (G1, ZGC) |
| Mark Word | 8 bytes: hash, age, lock state, biased thread ID |
| GC Roots | Thread stacks, static fields, JNI, monitors |
| Happens-Before | 6 rules: program order, monitor, volatile, start, join, transitivity |
| Memory Barrier | LoadLoad, LoadStore, StoreStore, StoreLoad |
| JIT | 5 tiers: 0 (interpreter) → 3 (C1 profiled) → 4 (C2 optimized) |
| Safepoint | Poll at loop back-edges + method returns; needed for GC/deopt |
| Intrinsic | CPU-specific instruction replacement (arraycopy, sqrt, CAS) |

---

> *Use these notes as a comprehensive reference for JVM internals. Staff/Principal interviews focus on understanding WHY things work the way they do — not just memorizing facts, but reasoning about trade-offs and production experience.*
