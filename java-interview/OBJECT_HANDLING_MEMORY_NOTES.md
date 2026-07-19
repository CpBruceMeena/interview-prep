# ☕ Java — Object Handling, References, Memory & Object Lifecycle

> **Category:** Language Fundamentals — Object Semantics & Memory Model  
> **Target Level:** Staff/Principal Engineer (10+ years)  
> **Why this matters at Staff level:** Memory leaks from mishandled references, object header overhead at scale, and reference lifecycle bugs cause a significant portion of production incidents in JVM services. Understanding how Java *actually* manages objects in memory is what separates great engineers from the rest.

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

> **Note:** This guide complements the [JVM Internals & GC notes](JVM_INTERNALS_NOTES.md). GC internals, the JMM happens-before rules, volatile semantics, JIT compilation, and ZGC/G1/Shenandoah details are covered there. This guide focuses on object-level memory management.

---

## 1. How Objects Are Stored: Primitives vs References

### The Two Worlds

```java
// PRIMITIVES — stored directly as values
int x = 42;                // Stack: [x = 42]            (4 bytes)
boolean b = true;          // Stack: [b = true]          (1 byte, but JVM often uses 4)
long l = 100000L;         // Stack: [l = 100000]         (8 bytes)

// OBJECTS — stored as references (pointers) on stack, data on heap
String s = new String("hello");
// Stack:  [s = 0xFEED1234]     (reference, 4 or 8 bytes)
// Heap:   [0xFEED1234] String object: header(12-16 bytes) + char[] reference + padding

// ARRAYS — also objects
int[] arr = new int[100];
// Stack:  [arr = 0xCAFE5678]
// Heap:   [0xCAFE5678] int[100]: header(16 bytes) + 100*4 bytes = 416 bytes + padding
```

**Key insight:** In Java, EVERYTHING that is `new` lives on the heap. The variable itself (the reference) lives on the stack for local variables, or in the heap for instance/static fields.

### The Reference Variable — What It Actually Holds

A reference variable holds a pointer to the object's location in the heap. In HotSpot:

```java
// Two reference sizes depending on JVM config:
//
// 1. COMPRESSED OOPs (default, heaps < 32GB):
//    - References are 4 bytes (32 bits)
//    - Can address up to 32GB of heap (shifted by 3 bits = 8-byte granularity)
//    - -XX:+UseCompressedOops (default on)
//
// 2. UNCOMPRESSED (heaps >= 32GB, or -XX:-UseCompressedOops):
//    - References are 8 bytes (64 bits)
//    - Full 64-bit address space
//
// Compressed OOPs encoding:
// real_address = oop << 3 (shift left by 3 = multiply by 8)
// This gives 32GB addressable with 32 bits (because objects are 8-byte aligned)

// -XX:+UseCompressedClassPointers (default on)
// Class pointers in object headers are also compressed when possible
```

### Default Values for References

```java
private String name;    // null (default for ALL object references)
private int age;        // 0 (default for numeric primitives)
private boolean flag;   // false (default for boolean)
private double value;   // 0.0d (default for floating-point)

// The null reference means the variable points to NOTHING
// Dereferencing null → NullPointerException at runtime
```

---

## 2. Pass by Value — The Most Misunderstood Concept

### Java is ALWAYS Pass-by-Value

```java
// ── PRIMITIVES: value is copied ─────────────────────────────
void increment(int x) {
    x = x + 1;  // Only modifies the copy
}

int a = 5;
increment(a);
System.out.println(a);  // 5 (unchanged!)

// ── OBJECT REFERENCES: the REFERENCE is copied, not the object ──
void changeName(User user) {
    user.setName("New Name");  // Modifies the SAME object
}

void reassign(User user) {
    user = new User("Different");  // Only modifies the LOCAL copy of reference!
}

User u = new User("Original");
changeName(u);
System.out.println(u.getName());  // "New Name" (object was mutated)

reassign(u);
System.out.println(u.getName());  // Still "New Name" (reassignment didn't affect caller!)

```

**The classic diagram:**

```
Before calling changeName(u):       After calling changeName(u):
                                    
Stack:                              Stack:
  u = [0x1000]                        u = [0x1000]  ← same reference
  user = [0x1000] (copy)              user = [0x1000] (copy, now out of scope)
                                    
Heap:                               Heap:
  [0x1000] User{name="Original"}      [0x1000] User{name="New Name"}  ← mutated!
```

### Mutability vs Reference Assignment

```java
// ── IMMUTABLE objects (String, Integer, BigDecimal) ─────────
String s = "hello";
appendExclamation(s);
System.out.println(s);  // "hello" (String is immutable)

void appendExclamation(String str) {
    str = str + "!";  // Creates NEW string, doesn't modify original!
}
// str = new reference to "hello!", local variable str now points there
// Caller's s still points to "hello"

// ── MUTABLE objects (StringBuilder, ArrayList, custom classes) ──
StringBuilder sb = new StringBuilder("hello");
appendExclamation(sb);
System.out.println(sb.toString());  // "hello!" (object was mutated)

void appendExclamation(StringBuilder sb) {
    sb.append("!");  // Modifies the object's internal state
}
```

**Staff-level insight:** The confusion arises because people say "objects are passed by reference" — but the *reference* itself is passed *by value*. Java never passes the actual object; it passes a copy of the reference to the object.

---

## 3. Object Layout in Memory

### HotSpot Object Header (64-bit JVM)

```java
// Every Java object in HotSpot has this layout:
//
// ┌──────────────────────────────────────────────────────────┐
// │                    OBJECT HEADER                          │
// ├────────────────────────────┬─────────────────────────────┤
// │       MARK WORD            │      KLASS POINTER          │
// │       8 bytes              │  4 bytes (compressed)       │
// │                            │  8 bytes (uncompressed)     │
// ├────────────────────────────┴─────────────────────────────┤
// │                    INSTANCE DATA                          │
// │   (fields in order: superclass fields → subclass fields) │
// │   (aligned: reference fields grouped, long/double grouped)│
// ├──────────────────────────────────────────────────────────┤
// │                       PADDING                             │
// │   (aligned to 8-byte boundary)                           │
// └──────────────────────────────────────────────────────────┘
//
// TOTAL minimum: 12 bytes (compressed) or 16 bytes (uncompressed)
// After padding: 16 bytes minimum object size!

// ── MARK WORD breakdown (8 bytes, 64-bit) ──────────────────
//
// Bit layout:
// | biased_lock:1 | lock:2 | age:4 | identity_hash:31 | unused:25 | thread:54 | epoch:2 |
//   ↑                       ↑                            ↑
//   biased locking flag     lock state (00=lightweight,   optional identity hash
//   (removed Java 15+)       01=unlocked/biased,          (computed lazily)
//                            10=heavyweight, 11=GC)
//
// The mark word is ALSO used for:
// - Lock state (biased → lightweight → heavyweight)
// - GC marking (forwarding pointer during evacuation)
// - Hash code (computed once, stored after first hashCode() call)

// ── KLASS POINTER ──────────────────────────────────────────
// Points to the Klass structure in Metaspace
// Contains: method table, field layout, superclass info, vtable, itable
// Compressed: 4 bytes (moved to 32-bit address space)
// Uncompressed: 8 bytes
```

### Field Ordering & Alignment

```java
// The JVM reorders fields for optimal alignment:
//
// Order (determined by JVM, not source code):
// 1. longs and doubles (8-byte alignment)
// 2. ints and floats (4-byte alignment)
// 3. shorts and chars (2-byte alignment)
// 4. bytes and booleans (1-byte alignment)
// 5. references (4 or 8 byte alignment depending on compressed OOPs)

// Example:
class Misordered {
    boolean flag;     // 1 byte
    int count;        // 4 bytes
    String name;      // 4 bytes (compressed)
    long id;          // 8 bytes
}
// JVM reorders to:
// long id          offset 0  (8 bytes)  → 8 byte aligned
// int count        offset 8  (4 bytes)  → 4 byte aligned
// String name      offset 12 (4 bytes)  → 4 byte aligned
// boolean flag     offset 16 (1 byte)   → 1 byte aligned
// TOTAL without header: 17 bytes + 7 padding = 24 bytes
// With header (12 compressed): 12 + 24 = 36... but 36 % 8 ≠ 0
// → padding to 40 bytes total

// Inheritance — fields packed from parent to child:
class Parent {
    int parentField;   // offset 12 (after header)
}

class Child extends Parent {
    boolean childFlag; // offset 16 (after parent field)
    int childCount;    // offset 20 (reordered if needed)
}
```

### Object Size Calculation Rules of Thumb

```java
// Minimum object: 16 bytes (12 header + 4 minimum data, padded to 16)
// Empty object (no fields): 16 bytes
// Simple wrapper: Integer = 16 bytes (header only, value stored as field)
// String (no char[] yet): 24 bytes
// String (with char[]{h,e,l,l,o}): 24 + 16 (array header) + 10 (chars) = ~50 bytes
// Object[] of length N: 16 (array header) + N*4 (compressed refs) + padding

// ── JOL (Java Object Layout) tool ──────────────────────────
// Add dependency: org.openjdk.jol:jol-core
// Run: java -jar jol-cli.jar internals java.lang.String

// Example output for a simple class:
// java.lang.Object object internals:
// OFF  SZ   TYPE DESCRIPTION               VALUE
//   0   8        (mark word)                (hash)
//   8   4        (klass pointer)            (class pointer)
//  12   4        (object alignment gap)     (padding)
// Instance size: 16 bytes (estimated)
// Space losses: 0 bytes internal + 4 bytes external = 4 bytes total
```

---

## 4. Object Creation & Lifecycle

### Complete Lifecycle of a Java Object

```java
// PHASE 1: CLASS LOADING
// (Only happens first time class is referenced)
// → Class bytes loaded by ClassLoader
// → Verified, prepared (static fields zeroed), resolved
// → <clinit> executed (static initializers run)

// PHASE 2: ALLOCATION
MyObject obj = new MyObject("test", 42);

// Step-by-step bytecode:
// 0: new             #2    // Allocate memory in heap (or TLAB)
// 3: dup                   // Duplicate reference for constructor
// 4: ldc           #3      // Push "test" constant
// 6: bipush        42      // Push int 42
// 8: invokespecial #4      // MyObject.<init>(String, int)V
//                            // (constructor: init mark word + klass pointer)
//                            // (constructor: initialize fields)
//11: astore_1              // Store reference in local variable 1

// Expanded:
// 1. JVM calculates object size from class metadata
// 2. TLAB (Thread-Local Allocation Buffer) allocation:
//    a. If TLAB has space → bump pointer (free! ~10ns)
//    b. If TLAB full → new TLAB from Eden
//    c. If Eden full → trigger minor GC
//    d. If TLAB too large for object → allocate directly in Eden
// 3. Object header initialized:
//    - Mark word: set to unlocked state (or biased, pre-Java 15)
//    - Klass pointer: set to MyObject's class metadata
// 4. Fields initialized to default values (0, null, false)
// 5. Constructor (<init>) runs:
//    - super() called (chains up to Object)
//    - instance initializer blocks run (in source order)
//    - constructor body executes
//    - final fields get freeze barrier (JMM guarantee)
// 6. Reference stored in variable (or passed to method)

// PHASE 3: USAGE
obj.doSomething();  // Method calls via vtable/itable dispatch

// PHASE 4: REACHABILITY CHANGES
obj = null;  // Object becomes unreachable (if no other references)

// PHASE 5: GC CANDIDATE
// On next GC cycle:
// - GC marks reachable objects from roots
// - Unreachable objects are NOT marked
// - For reference types: ReferenceQueue handling

// PHASE 6: RECLAMATION
// GC sweeps/evacuates and reclaims memory
// - If object has finalize() (deprecated): enqueued to Finalizer
// - If object has Cleaner: cleanup action runs (Java 9+)
// - Memory returned to free list or next TLAB

// PHASE 7: FULL CYCLE
// Memory is now available for new allocations
```

### Constructor Safety with `this` Escape

```java
// 🔴 DANGEROUS: Publishing 'this' during construction
public class UnsafePublish {
    private static UnsafePublish instance;
    private final int value;
    
    public UnsafePublish(int value) {
        instance = this;  // ← 'this' escapes before constructor completes!
        this.value = value;
    }
    
    // Another thread reading instance.value might see 0 (default)
    // because final field freeze hasn't happened yet!
}

// 🔴 Another common anti-pattern:
public class ListenerRegistrar {
    public ListenerRegistrar(EventBus bus) {
        bus.register(this);  // ← 'this' escapes!
        // bus might call methods on this before constructor finishes
        // → sees uninitialized fields!
    }
}

// ✅ Safe patterns:
// 1. Don't publish 'this' in constructor
// 2. Use factory method:
public static SafePublish create(int value) {
    SafePublish obj = new SafePublish(value);
    // obj is fully constructed here
    // Now it's safe to publish
    return obj;
}

// 3. For listeners, use separate init():
ListenerRegistrar lr = new ListenerRegistrar();
bus.register(lr);  // Now it's safe
```

---

## 5. Reference Types: Strong, Soft, Weak, Phantom

### Reference Hierarchy

```java
//   java.lang.ref.Reference<T>  (abstract base)
//       │
//       ├── SoftReference<T>    — cleared at GC's discretion (for caches)
//       ├── WeakReference<T>    — cleared on every GC (for canonical maps)
//       └── PhantomReference<T> — never get referent back (for post-mortem cleanup)
//
// All can be associated with a ReferenceQueue for notification
```

### Strong References — The Default

```java
// THE DEFAULT — every normal reference is strong
String s = "hello";           // Strong reference to "hello"
List<String> list = new ArrayList<>();  // Strong reference to ArrayList

// As long as a strong reference exists, the object is NOT collectable
// Even during OutOfMemoryError, strongly reachable objects survive

// If an object is ONLY strongly reachable, it's eligible for GC
// when the last strong reference goes out of scope or is set to null
```

### SoftReference — Memory-Sensitive Cache

```java
import java.lang.ref.SoftReference;

// Soft references are cleared BEFORE OutOfMemoryError
// They survive as long as memory is plentiful
// They are cleared when GC determines memory is tight

// Use case: memory-sensitive caches (e.g., image cache)
public class SoftCache<K, V> {
    private final Map<K, SoftReference<V>> cache = new ConcurrentHashMap<>();
    
    public V get(K key) {
        SoftReference<V> ref = cache.get(key);
        if (ref == null) return null;
        
        V value = ref.get();  // May return null if GC cleared it
        if (value == null) {
            cache.remove(key);  // Clean up stale entry
        }
        return value;
    }
    
    public void put(K key, V value) {
        cache.put(key, new SoftReference<>(value));
    }
}

// JVM tuning for SoftReferences:
// -XX:SoftRefLRUPolicyMSPerMB=1000  (default)
//   → Soft references survive for 1 second of lifetime per MB of free heap
//   → Higher value = longer survival = less GC pressure but more memory usage

// SoftReference clearing algorithm (HotSpot):
// timestamp = current_time_ms - (free_heap_MB * SoftRefLRUPolicyMSPerMB)
// If ref's last_access timestamp < computed timestamp → clear
```

### WeakReference — Automatically Cleared on GC

```java
import java.lang.ref.WeakReference;

// Weak references are cleared on EVERY GC cycle (minor OR major)
// The referent is immediately eligible for finalization after GC

// Use case 1: Canonical mappings (WeakHashMap)
public class CanonicalMapping {
    // WeakHashMap: entries are automatically removed when key is no longer
    // strongly reachable
    private WeakHashMap<UniqueKey, Metadata> cache = new WeakHashMap<>();
    
    public Metadata get(UniqueKey key) {
        return cache.get(key);  // May return null if key was GC'd
    }
    
    public void put(UniqueKey key, Metadata meta) {
        cache.put(key, meta);
    }
}

// Use case 2: ThreadLocal internals
// ThreadLocalMap uses WeakReference to the ThreadLocal object
// When ThreadLocal goes out of scope, the entry's key becomes null
// Next get/set on the map cleans up stale entries

// Use case 3: Add listener without preventing GC
public class WeakListener {
    private final List<WeakReference<EventListener>> listeners = new CopyOnWriteArrayList<>();
    
    public void register(EventListener listener) {
        listeners.add(new WeakReference<>(listener));
    }
    
    public void fireEvent(Event event) {
        for (WeakReference<EventListener> ref : listeners) {
            EventListener listener = ref.get();
            if (listener != null) {
                listener.onEvent(event);
            }
        }
        // Clean up collected listeners
        listeners.removeIf(ref -> ref.get() == null);
    }
}
```

### PhantomReference — Post-Mortem Cleanup

```java
import java.lang.ref.PhantomReference;
import java.lang.ref.ReferenceQueue;

// PhantomReference is the WEAKEST reference type
// - get() ALWAYS returns null (cannot recover the referent)
// - The referent is considered already dead
// - Used for: post-mortem cleanup, native resource management

// IMPORTANT: PhantomReference must have a ReferenceQueue
// The referent is NOT freed until PhantomReference is cleared or processed

// Proper pattern:
public class ResourceCleaner {
    private static final ReferenceQueue<Object> QUEUE = new ReferenceQueue<>();
    private static final Map<PhantomReference<?>, Runnable> CLEANUP_MAP = new HashMap<>();
    
    static {
        // Background thread processes cleanup actions
        Thread cleaner = new Thread(() -> {
            while (true) {
                try {
                    Reference<?> ref = QUEUE.remove();  // Blocks
                    Runnable cleanup = CLEANUP_MAP.remove(ref);
                    if (cleanup != null) {
                        cleanup.run();  // Native resource cleanup
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }, "phantom-cleaner");
        cleaner.setDaemon(true);
        cleaner.start();
    }
    
    public static <T> T createTracked(T obj, Runnable cleanupAction) {
        PhantomReference<T> ref = new PhantomReference<>(obj, QUEUE);
        CLEANUP_MAP.put(ref, cleanupAction);
        return obj;  // Return the original object
    }
}

// Use: 
// Resource resource = ResourceCleaner.createTracked(new Resource(), () -> {
//     nativeClose();  // Called after resource is GC'd
// });
```

### Reference Type Decision Matrix

| Type | `get()` returns | Cleared when | Use case |
|------|----------------|--------------|----------|
| **Strong** | The object | Never (while reachable) | Normal variables |
| **Soft** | Object or null | Before OOME | Caches that can be rebuilt |
| **Weak** | Object or null | Every GC cycle | Canonical maps, metadata |
| **Phantom** | Always null | After GC (before memory freed) | Native resource cleanup |

---

## 6. ReferenceQueue & Cleaner — Resource Cleanup

### ReferenceQueue — Polling Reference Events

```java
import java.lang.ref.*;

// ReferenceQueue receives enqueued references when referents become
// unreachable (for Weak/Soft) or after GC (for Phantom)

public class ReferenceQueueDemo {
    public static void main(String[] args) throws Exception {
        ReferenceQueue<Object> queue = new ReferenceQueue<>();
        Object obj = new Object();
        WeakReference<Object> ref = new WeakReference<>(obj, queue);
        
        System.out.println(ref.get());  // Not null
        
        obj = null;  // Remove strong reference
        System.gc();  // Suggest GC (not guaranteed)
        
        Thread.sleep(100);  // Give GC time
        
        Reference<?> polled = queue.poll();  // Non-blocking, may return null
        if (polled != null) {
            System.out.println("Object was collected! Reference: " + polled);
            // For PhantomReference, native cleanup would happen here
        }
        
        // Blocking version:
        // Reference<?> removed = queue.remove();  // Blocks until available
    }
}

// ── Production monitoring pattern ───────────────────────────
// Monitor SoftReference queue length to detect memory pressure:
public class MemoryPressureDetector {
    private static final ReferenceQueue<byte[]> QUEUE = new ReferenceQueue<>();
    private static final AtomicLong softRefCollected = new AtomicLong(0);
    
    public static void startMonitoring() {
        Thread monitor = new Thread(() -> {
            try {
                while (true) {
                    QUEUE.remove();  // Blocks
                    long count = softRefCollected.incrementAndGet();
                    
                    if (count > 100) {  // Threshold
                        // Alert: many SoftReferences cleared!
                        // This means the JVM is under memory pressure
                        log.warn("Memory pressure detected! {} soft refs collected", count);
                    }
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }, "memory-monitor");
        monitor.setDaemon(true);
        monitor.start();
    }
}
```

### Cleaner (Java 9+ — Replacing `finalize()`)

```java
import java.lang.ref.Cleaner;

// Cleaner is the official replacement for finalize()
// It uses PhantomReference internally

public class DatabaseConnection implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();
    
    private final Cleaner.Cleanable cleanable;
    private final long nativePtr;  // Native resource handle
    
    // Static inner class — does NOT hold reference to outer object
    private static class CleanupTask implements Runnable {
        private final long nativePtr;
        
        CleanupTask(long nativePtr) {
            this.nativePtr = nativePtr;
        }
        
        @Override
        public void run() {
            // Called when DatabaseConnection is GC'd
            // OR when clean() is called explicitly
            nativeClose(nativePtr);
        }
    }
    
    public DatabaseConnection(String url) {
        this.nativePtr = nativeConnect(url);
        // Register cleanup — runs if connection is GC'd without close()
        this.cleanable = CLEANER.register(this, new CleanupTask(nativePtr));
    }
    
    public void query(String sql) {
        // Use the connection
    }
    
    @Override
    public void close() {
        // Explicit cleanup — preferred path
        cleanable.clean();  // Runs CleanupTask immediately
    }
    
    private static native long nativeConnect(String url);
    private static native void nativeClose(long ptr);
}

// Usage:
try (DatabaseConnection conn = new DatabaseConnection("jdbc:postgresql://...")) {
    conn.query("SELECT * FROM users");
}  // close() called automatically

// Even if close() is forgotten:
// CleanupTask runs when DatabaseConnection is GC'd
// But don't rely on this — always use try-with-resources!
```

---

## 7. Stack vs Heap — What Lives Where

### What Lives on the Stack

```java
// Each thread has its OWN stack (default 1MB, -Xss to configure)

// ON THE STACK:
// 1. Local primitive variables
//    int x = 42;          → x = 42 stored in stack frame
//    boolean flag = true; → flag = true stored in stack frame
//
// 2. Object reference variables
//    String s = "hello";  → s = 0xFEED... stored in stack frame
//    The reference (pointer) is on stack, the object is on heap
//
// 3. Method call frames
//    Each method call pushes a new frame onto the stack
//    Frame contains: local variable array, operand stack, frame data
//
// 4. Partial frame results (in JIT-compiled code)
//    Registers can "spill" to stack if needed

// NOT ON THE STACK:
// - Any object or array created with 'new' → ALWAYS on heap
// - Static fields → on heap (in the Method area / class data)
// - Instance fields → on heap (as part of the object)

// Stack frame size:
// - Local variables: 4 bytes each (primitives) or 4/8 bytes (references)
// - Operand stack: JVM calculates max depth from bytecode
// - Frame data: constant pool resolution, exception table, etc.
```

### Escape Analysis — Stack Allocation

```java
// C2 JIT compiler's Escape Analysis (EA) can allocate objects ON THE STACK
// if they don't "escape" the method

// BEFORE — explicit object:
public long sum(int[] values) {
    Point p = new Point(0, 0);  // ← Object creation
    for (int v : values) {
        p.x += v;
        p.y += v;
    }
    return p.x + p.y;
}
// With EA: p is stack-allocated (NO heap allocation!)
// With scalar replacement: p.x and p.y become local variables (BEST!)

// AFTER — what the JIT might do:
public long sum(int[] values) {
    int x = 0, y = 0;  // Scalar replacement of Point
    for (int v : values) {
        x += v;
        y += v;
    }
    return x + y;
}

// When does EA fail?
// 1. Object returned from method → escapes
// 2. Object stored in a field → escapes
// 3. Object passed to non-inlined method → escapes
// 4. Object stored in an array → escapes
// 5. Object is returned from a method → escapes

// CHECK if EA is working:
// -XX:+PrintEscapeAnalysis  (Java 8) — prints EA results
// -XX:+PrintEliminateAllocations (Java 8) — shows scalar replacements
// -XX:+UnlockDiagnosticVMOptions -XX:+PrintAssembly  — see compiled code
```

### Thread-Local Allocation Buffers (TLABs)

```java
// TLAB = per-thread region in Eden for fast allocation
//
// [Thread 1 TLAB] [Thread 2 TLAB] [Thread 3 TLAB] [Unused Eden]
//       ↑                ↑               ↑
//   bump pointer      bump pointer    bump pointer
//
// Allocation in TLAB: just bump pointer → ~10ns
// Allocation outside TLAB: CAS on Eden top → ~100ns (synchronized)
// TLAB waste: -XX:TLABWasteTargetPercent=1 (default 1% of Eden)

// JVM flags for TLAB tuning:
// -XX:+UseTLAB                  (default: on)
// -XX:TLABSize=2m               (default: auto-sized)
// -XX:TLABWasteTargetPercent=1  (allowed waste before requesting new TLAB)
// -XX:TLABRefillWasteFraction=64 (don't request new TLAB if remaining > 1/64)

// Large objects (> TLAB size) allocated directly in Eden:
// -XX:PretenureSizeThreshold=1m  (objects > 1MB go to Old gen directly)
// Only works with Serial/ParNew; G1 and ZGC handle this differently
```

---

## 8. String Pool & Interning

### String Literals vs `new String()`

```java
// String literals are INTERNED automatically
String s1 = "hello";
String s2 = "hello";
System.out.println(s1 == s2);  // TRUE — same object in string pool

// new String() creates a NEW object on the heap
String s3 = new String("hello");
String s4 = new String("hello");
System.out.println(s3 == s4);  // FALSE — different objects
System.out.println(s3.equals(s4));  // TRUE — same content

// Explicit interning:
String s5 = s3.intern();
System.out.println(s1 == s5);  // TRUE — intern() returns pool reference
```

### String Pool Memory

```java
// String pool location:
// - Java 7+: in heap (was PermGen in Java 6)
// - Part of the heap → subject to GC
// - Interned strings can be collected if no references to them

// String pool size (important for large applications):
// -XX:StringTableSize=1000003  (default: 60013, must be prime number)
// Larger table → faster intern lookup, more memory
// With many unique strings, consider increasing this

// Memory impact:
// String "hello": 
//   - String object: 24 bytes (12 header + 4 hash + 4 ref to char[] + 4 padding)
//   - char[]: 16 header + 10 bytes (5 chars * 2 bytes each) + 6 padding = 32 bytes
//   - TOTAL: 56 bytes per unique interned string

// ── String deduplication (Java 8u20+, G1 only) ──────────────
// -XX:+UseStringDeduplication
// G1 GC detects duplicate char[] arrays and makes Strings share them
// Saves memory in applications with many duplicate strings
// Works only with G1 GC
```

### Common String Memory Pitfall

```java
// 🔴 BAD: creates many intermediate strings
String result = "";
for (int i = 0; i < 1000; i++) {
    result += String.valueOf(i);  // Creates NEW StringBuilder + String each iteration!
}
// → 1000 intermediate String objects created and discarded
// → GC churn!

// ✅ GOOD: use StringBuilder
StringBuilder sb = new StringBuilder(5000);  // Pre-size!
for (int i = 0; i < 1000; i++) {
    sb.append(i);
}
String result = sb.toString();

// ✅ Even better with Java 8+: String.join
String result = IntStream.range(0, 1000)
    .mapToObj(String::valueOf)
    .collect(Collectors.joining());
```

---

## 9. Arrays in Memory

### Array Object Layout

```java
// Array memory layout (HotSpot):
//
// ┌──────────────────────────────────────┐
// │   MARK WORD (8 bytes)                 │
// ├──────────────────────────────────────┤
// │   KLASS POINTER (4 compressed / 8)   │
// ├──────────────────────────────────────┤
// │   ARRAY LENGTH (4 bytes)              │
// ├──────────────────────────────────────┤
// │   ELEMENTS...                         │
// │   (element 0, element 1, ...)        │
// ├──────────────────────────────────────┤
// │   PADDING (to 8-byte boundary)        │
// └──────────────────────────────────────┘
//
// Array overhead: 16 bytes (compressed) or 24 bytes (uncompressed)

// ── Size calculations ─────────────────────────────────────
// int[10]: 
//   16 (header) + 10*4 (ints) + 0 padding (16+40=56, already 8-aligned) = 56 bytes
//
// Object[10] (with compressed OOPs):
//   16 (header) + 10*4 (refs) + 0 padding = 56 bytes
//
// Object[10] (without compressed OOPs):
//   24 (header) + 10*8 (64-bit refs) + 0 padding = 104 bytes
//
// long[10]:
//   16 (header) + 10*8 (longs) = 96 bytes
//
// boolean[10]:
//   16 (header) + 10*1 (bools) + 6 padding (to 8) = 32 bytes

// ── Multidimensional arrays ───────────────────────────────
// int[3][3] = array of 3 references to int[3] arrays:
//   Outer array: 16 + 3*4 (refs) = 28 + 4 padding = 32 bytes
//   3 inner arrays: 3 * (16 + 3*4) = 3 * 28 = 84 + 4 padding = 96 bytes
//   TOTAL: 128 bytes
//
// int[9] (flat):
//   16 + 9*4 = 52 + 4 padding = 56 bytes
//
// → FLAT arrays use HALF the memory of jagged arrays!
```

### Primitive Arrays vs Collections

```java
// ── Memory comparison ──────────────────────────────────────
// int[1000]:           56 + 4000 = 4056 bytes (contiguous!)
// ArrayList<Integer>:  56 (array header) + 1000*4 (refs) + 1000*16 (Integer objects)
//                      ≈ 56 + 4000 + 16000 = 20056 bytes!
//                      → 5x more memory than int[]!

// Access speed:
// int[1000]: contiguous in memory → CPU cache friendly → fast
// ArrayList<Integer>: random object locations → cache misses → 3-5x slower

// ✅ Use primitive collections (fastutil, Eclipse Collections, or arrays) for:
// - Large numeric datasets
// - Performance-critical hot paths
// - Memory-constrained environments

// ── VarHandle for array access ────────────────────────────
// Java 9+ VarHandle provides efficient, type-safe array access:
public class ArrayAccess {
    private static final VarHandle INT_ARRAY = MethodHandles.arrayElementVarHandle(int[].class);
    
    public void demo() {
        int[] arr = new int[100];
        
        // Volatile read (like getIntVolatile in Unsafe)
        int val = (int) INT_ARRAY.getVolatile(arr, 42);
        
        // CAS (compare-and-swap)
        boolean success = INT_ARRAY.compareAndSet(arr, 42, 0, 1);
        
        // Get and set
        INT_ARRAY.setOpaque(arr, 42, 99);
    }
}
```

---

## 10. Finalization, Cleaners & Deprecation

### The `finalize()` Anti-Pattern

```java
// 🔴 NEVER DO THIS:
public class Resource {
    private long nativePtr;
    
    @Override
    protected void finalize() throws Throwable {
        try {
            nativeClose(nativePtr);  // ← Unpredictable timing!
        } finally {
            super.finalize();
        }
    }
}

// Problems:
// 1. UNPREDICTABLE TIMING: GC may run minutes/hours later (or never!)
// 2. THREAD UNSAFE: finalize() runs on Finalizer thread (single thread!)
// 3. PERFORMANCE: Objects with finalize() take longer to collect
//    (must go through "finalization" phase)
// 4. RESURRECTION: finalize() can make object reachable again
// 5. EXCEPTIONS: exceptions in finalize() are ignored
// 6. DEPRECATED: Removed in Java 18 (deprecated in Java 9)

// Stats:
// Objects with finalize(): 1.5-2x slower to allocate, 
//                          ~10x slower to collect (must pass through queue)
//                          Pending finalization queue can grow unbounded
```

### The Cost of Finalization

```java
// Finalization flow:
// 1. GC finds unreachable object with finalize()
// 2. Object placed in F-Queue (pending finalization)
// 3. Finalizer thread executes finalize()
// 4. On NEXT GC cycle, object is collected
//
// → Objects with finalize() survive at least ONE extra GC cycle!
// → The Finalizer thread can become a bottleneck

// The finalizer thread priority? Thread.MIN_PRIORITY!
// → finalize() may NEVER run if the JVM exits quickly

// Production lesson: Never rely on finalize() for anything important.
// Use try-with-resources (AutoCloseable) or Cleaner (Java 9+).
```

### Safe Resource Management Patterns

```java
// PATTERN 1: try-with-resources (PREFERRED)
try (FileInputStream fis = new FileInputStream("/tmp/data.txt");
     BufferedReader br = new BufferedReader(new InputStreamReader(fis))) {
    String line = br.readLine();
} // Both resources closed automatically, even on exception

// PATTERN 2: Explicit close with cleanup guard
public class DatabasePool {
    private final List<Connection> connections = new ArrayList<>();
    
    public Connection acquire() {
        Connection conn = connections.remove(connections.size() - 1);
        return new ConnectionProxy(conn);  // Wrap to track unclosed connections
    }
    
    // Proxy that logs and closes leaked connections:
    private static class ConnectionProxy implements AutoCloseable {
        private final Connection delegate;
        private final StackTraceElement[] allocationStack;
        
        ConnectionProxy(Connection delegate) {
            this.delegate = delegate;
            this.allocationStack = new Throwable().getStackTrace();  // Capture!
        }
        
        @Override
        public void close() {
            connections.add(delegate);  // Return to pool
        }
        
        @Override
        protected void finalize() {
            // LOG WARNING: connection leaked!
            // Include allocationStack for debugging
            log.error("Connection leaked! Allocated at:", allocationStack);
        }
    }
}
```

---

## 11. Memory Leak Patterns

### Pattern 1: Static Collection Growth

```java
// 🔴 CLASSIC LEAK: static collection that grows unbounded
public class UserCache {
    private static final Map<String, User> cache = new HashMap<>();
    
    public static User getUser(String id) {
        return cache.computeIfAbsent(id, UserCache::loadUser);
    }
    
    private static User loadUser(String id) { /* DB load */ }
}
// → cache grows indefinitely → OutOfMemoryError!
// ✅ FIX: Use bounded cache (Guava Cache, Caffeine, or LRU map)
```

### Pattern 2: Forgotten Listeners / Callbacks

```java
// 🔴 LEAK: Listener registered but never removed
public class EventBus {
    private final List<EventListener> listeners = new CopyOnWriteArrayList<>();
    
    public void register(EventListener listener) {
        listeners.add(listener);
    }
    
    public void unregister(EventListener listener) {
        listeners.remove(listener);  // ← Often forgotten!
    }
}
// → Objects that registered as listeners can never be GC'd

// ✅ FIX 1: Always unregister (try-finally)
// ✅ FIX 2: Use WeakReference listeners
// ✅ FIX 3: Use a framework that manages lifecycle (Spring, etc.)
```

### Pattern 3: Inner Class Holding Implicit Reference

```java
// 🔴 LEAK: Non-static inner class holds reference to outer
public class ExpensiveService {
    private final byte[] data = new byte[100_000_000];  // 100MB
    
    public class Callback implements EventHandler {
        public void onEvent(Event e) {
            // Doesn't use ExpensiveService, but implicitly holds reference!
        }
    }
    
    public EventHandler getCallback() {
        return new Callback();  // ← Hides ref to ExpensiveService!
    }
}

// Usage:
ExpensiveService svc = new ExpensiveService();
EventHandler cb = svc.getCallback();
svc = null;  // ← ExpensiveService can't be GC'd! Callback still references it!
// 100MB memory leak!

// ✅ FIX: Make inner class STATIC
public static class Callback implements EventHandler { ... }
```

### Pattern 4: ThreadLocal Leaks

```java
// ThreadLocal values live as long as the THREAD lives
// In web apps: thread pools keep threads alive FOREVER

// 🔴 LEAK:
public class RequestContext {
    private static final ThreadLocal<User> currentUser = new ThreadLocal<>();
    
    public static void setUser(User user) {
        currentUser.set(user);
    }
    
    public static User getUser() {
        return currentUser.get();
    }
}

// In a web filter:
public void doFilter() {
    User user = authenticate(request);
    RequestContext.setUser(user);  // ← Stored in ThreadLocal
    chain.doFilter();
    // ← FORGOT to remove! User object leaked in thread!
}
// → For 100 threads × 100MB each = 100,000 user objects leaked!
// → ThreadLocalMap entries: WeakReference to ThreadLocal, Strong ref to value
// → Even if ThreadLocal goes out of scope, VALUE stays!

// ✅ FIX: Always remove in finally:
public void doFilter() {
    User user = null;
    try {
        user = authenticate(request);
        RequestContext.setUser(user);
        chain.doFilter();
    } finally {
        RequestContext.remove();  // ← CRITICAL!
    }
}
```

### Pattern 5: String.substring() Memory Leak (Java 6)

```java
// Java 6: substring() shared underlying char[]!
String huge = loadHugeString(100_000_000);  // 100MB char[]
String small = huge.substring(0, 2);        // "just 2 chars"
huge = null;
// ⚠️ Java 6: small still references the 100MB char[]!
// → Memory leak: 100MB retained for a 2-char string!

// Java 7+: substring() creates a NEW char[] → no leak
// But other methods still share: String.valueOf(), StringBuilder.toString()
// These use Arrays.copyOfRange() in modern Java → safe

// ✅ Pattern for defensive copy:
String safe = new String(small);  // Force a copy (if you need to trim)
```

### Pattern 6: ClassLoader Leaks

```java
// 🔴 LEAK: Loaded classes leak if their ClassLoader is retained
// Common in:
// - Hot-reload frameworks
// - Plugin systems
// - Application servers

// A single class reference prevents entire ClassLoader + ALL loaded classes
// from being collected!
// Metaspace fills up → OutOfMemoryError: Metaspace

// Common causes:
// 1. Static fields holding references to ClassLoader-loaded objects
// 2. Thread.setContextClassLoader() without cleanup
// 3. java.util.logging handlers referencing custom classes
// 4. java.beans.Introspector caching

// ✅ Detection:
// -XX:+TraceClassLoading -XX:+TraceClassUnloading
// Verbose class loading/unloading info
// jcmd <pid> VM.classloader_stats  (Java 9+)
```

### Pattern 7: Unclosed Resources

```java
// 🔴 LEAK: Unclosed streams, connections, sockets
public void processFile(String path) {
    FileInputStream fis = new FileInputStream(path);
    // ← FORGOT to close!
}
// → File descriptor leak → "Too many open files" error
// → Native memory exhaustion

// ✅ ALWAYS use try-with-resources (Java 7+):
public void processFile(String path) throws IOException {
    try (FileInputStream fis = new FileInputStream(path);
         BufferedInputStream bis = new BufferedInputStream(fis)) {
        // Process file
    }  // Auto-closed, even on exception
}
```

---

## 12. TLABs, PLABs & Allocation Optimizations

### TLAB (Thread-Local Allocation Buffer)

```java
// JVM divides Eden into per-thread regions called TLABs
//
// ┌─────────────────────────────────────────────────────────┐
// │   EDEN SPACE                                              │
// ├─────────────┬──────────────┬──────────────┬──────────────┤
// │ Thread 1    │ Thread 2     │ Thread 3     │ Thread 4     │
// │ TLAB        │ TLAB         │ TLAB         │ TLAB         │
// │ [free: 2KB] │ [free: 0KB]  │ [free: 8KB]  │ [free: 10KB] │
// └─────────────┴──────────────┴──────────────┴──────────────┘
//                                   ↑
//                             Thread 3's TLAB exhausted
//                             → Get new TLAB from Eden top
//
// Allocation in TLAB: bump-pointer (just increment a pointer) → ~10ns
// Allocation without TLAB: CAS on Eden top pointer → ~100-200ns

// Objects too large for TLAB are allocated directly in Eden:
// -XX:TLABSize=2m  (set TLAB size)
// -XX:-ResizeTLAB  (disable automatic resizing)
```

### PLAB (Promotion-Local Allocation Buffer)

```java
// Similar to TLABs but used during GC for promoting objects
// to Survivor/Old regions:
//
// During GC, each GC thread has a PLAB:
// - Objects are moved into the PLAB
// - When full, the PLAB is flushed to the actual survivor/old region
// - Reduces contention on shared survivor space

// -XX:YoungPLABSize=4096   (default: 4096 words)
// -XX:OldPLABSize=1024     (default: 1024 words)
// -XX:PLABWeight=75        (weight for sizing heuristics, default 75%)
```

### Allocation Optimization Checklist

```java
// 1. ENABLE TLABs: -XX:+UseTLAB (default on)
// 2. ENABLE Escape Analysis: -XX:+DoEscapeAnalysis (default on)
// 3. Pre-size collections: new ArrayList<>(expectedSize)
// 4. Use StringBuilder/StringBuffer with initial capacity
// 5. Reuse objects in hot paths (object pools for expensive objects)
// 6. Use primitive collections for large numeric datasets
// 7. Avoid allocating in loops (hoist allocation)
// 8. Use value objects (Java 16+ records are not value types yet)
// 9. Use -XX:+PrintTLAB to verify TLAB effectiveness
```

### Allocation Profiling

```java
// 1. JFR events for allocation analysis:
//    jdk.ObjectAllocationInNewTLAB  (per-object allocations in TLAB)
//    jdk.ObjectAllocationOutsideTLAB (allocations outside TLAB)
//
// 2. Async Profiler:
//    ./profiler.sh -e alloc -d 60 -f alloc.html <pid>
//
// 3. Native memory tracking (-XX:NativeMemoryTracking=summary):
//    jcmd <pid> VM.native_memory summary
//
// 4. Instrumentation agent: java.lang.instrument with ClassFileTransformer
//    to count allocations per class

// Example: Find allocation hot spots
// jcmd <pid> JFR.start duration=60s filename=allocations.jfr
// jcmd <pid> JFR.dump filename=allocations.jfr
// jfr print --events jdk.ObjectAllocationInNewTLAB allocations.jfr | head -20
```

---

## 13. JVM Memory Tuning — Heap & Beyond

### Heap Sizing Strategy

```java
// ── KEY PARAMETERS ─────────────────────────────────────────
// -Xms4g -Xmx4g           # Fixed heap (no resizing overhead)
// -Xms1g -Xmx8g           # Variable heap (min 1G, max 8G)
// -XX:NewRatio=2           # Old:Young = 2:1 (young = 1/3 of heap)
// -XX:NewSize=1g           # Initial young gen size
// -XX:MaxNewSize=2g        # Max young gen size
// -XX:SurvivorRatio=8      # Eden:Survivor = 8:1 (S0 = 1/10 of young)
// -XX:+UseAdaptiveSizePolicy  # JVM auto-tunes generation sizes

// ── COMMON PRODUCTION CONFIGURATIONS ───────────────────────

// Service with predictable memory (e.g., API server):
// -Xms4g -Xmx4g
// -XX:NewSize=2g -XX:MaxNewSize=2g
// -XX:+UseG1GC
// → Fixed heap, fixed young gen, G1 GC

// Data processing (high allocation rate):
// -Xms8g -Xmx8g
// -XX:NewRatio=1           # Young = 4G, Old = 4G
// -XX:+UseParallelGC       # Higher throughput for CPU-bound
// → Larger young gen to handle allocation bursts

// Latency-sensitive (trading, streaming):
// -Xms10g -Xmx10g
// -XX:+UseZGC
// -XX:ConcGCThreads=8
// -XX:SoftMaxHeapSize=9g  # GC tries to stay under 9G
// → ZGC for sub-ms pause times
```

### Metaspace Tuning

```java
// Metaspace (Java 8+) — stores class metadata
// -XX:MetaspaceSize=256m      # Initial threshold for GC (NOT initial size!)
// -XX:MaxMetaspaceSize=512m   # Max metaspace size (default: unlimited!)
// -XX:MinMetaspaceFreeRatio=40  # Min free ratio after GC
// -XX:MaxMetaspaceFreeRatio=70  # Max free ratio after GC

// Monitoring:
// jstat -gcmetacapacity <pid> 1000 1
// jcmd <pid> VM.metaspace

// Compressed Class Space:
// -XX:CompressedClassSpaceSize=1g  # Max size for compressed class pointers
// Only used with compressed class pointers (default on)
```

### Direct Memory & Native Memory

```java
// Direct Memory (ByteBuffer.allocateDirect):
// -XX:MaxDirectMemorySize=1g  (default: -Xmx, but GC-unaware)
// Used by: NIO, Netty, gRPC, any zero-copy I/O

// Monitoring direct memory:
// -XX:NativeMemoryTracking=summary
// jcmd <pid> VM.native_memory summary scale=MB

// Common issue: DirectMemory OOM when buffers aren't released
// -XX:+ExitOnOutOfMemoryError  (recommended for production)

// Other native memory consumers:
// - JIT code cache: -XX:ReservedCodeCacheSize=256m
// - Compiler threads: -XX:CICompilerCount=4
// - Thread stacks: -Xss1m (default, ~1MB per thread)
// - Socket buffers
// - JNI allocations
```

### When OutOfMemoryError Happens

```java
// Different OOM types and their causes:
//
// 1. java.lang.OutOfMemoryError: Java heap space
//    → Objects can't be allocated (heap full)
//    → Fix: increase heap, fix memory leak, reduce object size
//
// 2. java.lang.OutOfMemoryError: Metaspace
//    → Class metadata fills metaspace
//    → Fix: increase MaxMetaspaceSize, fix ClassLoader leak
//
// 3. java.lang.OutOfMemoryError: GC overhead limit exceeded
//    → GC spends >98% of time recovering <2% of heap
//    → Fix: increase heap, reduce allocation rate
//
// 4. java.lang.OutOfMemoryError: Direct buffer memory
//    → Direct memory exhausted (ByteBuffer.allocateDirect)
//    → Fix: increase MaxDirectMemorySize, release buffers
//
// 5. java.lang.OutOfMemoryError: Unable to create new native thread
//    → OS can't create more threads (ulimit -u)
//    → Fix: reduce thread count, increase ulimit

// Production recommendation:
// -XX:+HeapDumpOnOutOfMemoryError    # Auto-dump on OOM
// -XX:HeapDumpPath=/var/log/dumps/   # Where to dump
// -XX:+ExitOnOutOfMemoryError        # Exit JVM (recommended over hanging)
// -XX:OnOutOfMemoryError="kill -9 %p" # Emergency kill script
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
1. `swap(a, b)` — copies the references. Inside swap, `s1` points to `a`'s `"A"` object, `s2` points to `b`'s `"B"` object. Swapping `s1` and `s2` only swaps the local copies. Original references `a` and `b` are unchanged.

2. `modify(x)` — copies the reference. `sb` points to `x`'s `"X"` object. `sb.append("Y")` mutates the shared object to `"XY"`. Then `sb = new StringBuilder("Z")` changes the LOCAL copy to point to a new object, but `x` still points to `"XY"`.

**Key insight:** Java is ALWAYS pass-by-value. For objects, the value of the reference is copied, not the object itself.
</details>

### Question 2: Object Size Estimation

**Problem:** Estimate the memory footprint of this object in HotSpot 64-bit with compressed OOPs:

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

**With compressed OOPs (heaps < 32GB):**

```
Header: 12 bytes (8 mark word + 4 compressed klass pointer)

JVM reorders fields by type:
  long id           offset 12 (+8) = 20  (8-byte aligned)
  int salary        offset 20 (+4) = 24  (4-byte aligned)
  String name       offset 24 (+4) = 28  (4-byte aligned)
  String department offset 28 (+4) = 32  (4-byte aligned)
  boolean active    offset 32 (+1) = 33  (1-byte aligned)

Total without padding: 33 bytes
Padding to 8-byte boundary: +7 bytes = 40 bytes total

Note: The JVM's actual field ordering may differ from source order.
```
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

```
null
world
```

**Why?**
1. `new String("hello")` has NO strong reference outside the WeakReference. After `ref = new WeakReference<>(...)`, the String "hello" is only weakly reachable. On GC, it's cleared → `ref.get()` returns `null`.

2. `strong = new String("world")` holds a STRONG reference. `ref2` wraps it with a WeakReference, but `strong` keeps it alive. On GC, the object survives because there's still a strong reference → `ref2.get()` returns `"world"`.

**Key insight:** WeakReference doesn't prevent GC, but it ALSO doesn't trigger GC. The referent is only cleared if no strong references exist.
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

**Step 1: `new Object()`**
Mark word: `|unlocked:01|` (lock bits = 01, biased_lock = 0)
No hash code computed yet (lazy)

**Step 2: `synchronized (obj)` (first acquisition)**
Mark word: `|lightweight:00|` (lock bits = 00)
Displaced mark word stored in lock record on stack

**Step 3: `obj.hashCode()` inside synchronized block**
Identity hash code must be computed. BUT: the mark word is already in lightweight lock state (stores displaced mark word reference).
→ JVM must INFLATE the lock to heavyweight (mutex) to store the hash code.
Mark word: `|heavyweight:10|` (lock bits = 10)
Hash stored in the inflated monitor structure, not in the mark word

**Step 4: Exit first synchronized block**
Lock remains inflated (heavyweight)

**Step 5: `synchronized (obj)` (second acquisition)**
Mark word: `|heavyweight:10|` (already heavyweight)
Just uses OS mutex

**Lesson:** Calling `hashCode()` on an object that's in a biased/lightweight lock forces lock inflation. This adds overhead. Avoid calling `hashCode()` on heavily contended locks.
</details>

### Question 5: String Pool — Memory Impact

**Problem:** An application reads 1 million unique strings from a file and processes them. Each string is about 10 characters. The strings are compared frequently using `==`. Design a memory-efficient approach. What's the memory impact of interning all strings?

<details>
<summary>🎯 Answer</summary>

**Without interning:**
1 million `new String("...")` objects:
- Each String: 24 bytes (header + fields + padding)
- Each char[]: 16 (header) + 20 (10 chars * 2 bytes) + 4 padding = 40 bytes
- Total: ~64MB for 1M strings

**With interning (`str.intern()`):**
1 million interned String objects:
- String objects: 24 bytes × 1M = 24MB
- char[]: 40 bytes × 1M (but many may share arrays with dedup) = ~40MB
- String table: 60,013 entries × ~8 bytes each = 480KB (default)
- Total: ~64MB (similar, but strings are shared)

**With `==` comparison using interned strings:**
- `==` is pointer comparison — much faster than `equals()` (which is O(n))
- For 1M operations: `==` ≈ 1ns, `equals()` ≈ 10-50ns (depends on length)
- 10x+ performance improvement for comparison operations

**Recommendations:**
1. Intern only if you'll do many `==` comparisons
2. Use `HashMap<String, ...>` instead of intern + `==` for lookups
3. Increase `-XX:StringTableSize` for many unique strings
4. Consider using `-XX:+UseStringDeduplication` (G1 only)
5. Alternative: use `ByteArrayWrapper` with precomputed hash for comparison-heavy workloads

**String pool sizing:**
For 1M unique strings, set `-XX:StringTableSize=1000003` (prime near 1M)
This gives O(1) average lookup vs O(n/k) with default small table.
</details>

### Question 6: TLAB and Allocation

**Problem:** Your application allocates millions of small objects in a tight loop. Each allocation takes ~10ns per object. Suddenly, performance drops to ~200ns per allocation. What happened? How do you fix it?

<details>
<summary>🎯 Answer</summary>

**Most likely cause: TLAB exhaustion.**

**Normal (~10ns):** Each thread allocates in its own TLAB via bump-pointer — just increment the pointer. No contention.

**Slow (~200ns):** TLAB is exhausted. Thread must:
1. Request new TLAB from Eden (needs CAS on Eden top pointer → contention)
2. Wait for other threads requesting TLABs
3. Potentially wait for minor GC if Eden is full

**Diagnosis:**
```bash
-XX:+PrintTLAB  # Shows TLAB usage stats
# Look for: threads with high "refills" count
# "TLAB gc refills" = times TLAB was exhausted
```

**Fixes:**
1. Increase TLAB size: `-XX:TLABSize=4m` (auto-sizing may be too conservative)
2. Disable resizing: `-XX:-ResizeTLAB` (forces consistent TLAB size)
3. Increase Eden size: `-Xmn` (more Eden = more TLAB capacity)
4. Reduce allocation rate: object pooling, value objects, etc.
5. Check if Escape Analysis is working (objects might not need heap allocation)

**Alternative cause: Allocation from multiple threads causing contention on the shared Eden top pointer (when TLABs are too small).**
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

**`Point p`: CAN be stack-allocated (or scalar replaced)**
- `p` never escapes `processData`
- No reference to `p` is stored in a field, returned, or passed to non-inlined method
- JIT can stack-allocate `p` or even replace it with local variables `x` and `y`

**`List<Integer> list`: LIKELY escapes**
- `list` is passed to `System.out.println()` which takes `Object`
- The println method's parameter type is `Object` (not inlined easily)
- Even if `list` doesn't escape otherwise, passing it to a method that the JIT can't inline forces heap allocation

**The real issue: `ArrayList` with `Integer` autoboxing:**
- `list.add(values[i] % 10)` autoboxes the int to `Integer`
- Each `Integer.valueOf(n)` may return cached value for -128 to 127
- For values outside cache range: NEW `Integer` objects on heap
- Even with inlining, `Integer` objects must exist on heap

**Conclusion:**
- `Point` → stack or scalar replaced (ZERO heap allocation)
- `List` + `Integer` objects → heap allocated (despite ArrayList's internal array)
- The `System.out.println` call forces `list` itself to heap

**Lesson:** Even with great EA, autoboxing and non-inlineable method calls force heap allocation.
</details>

### Question 8: Memory Leak Identification

**Problem:** A server application runs fine for 24 hours, then slows down and eventually throws OutOfMemoryError. The heap dump shows millions of `java.util.HashMap$Node` objects. What's the most likely cause? How do you find the root cause?

<details>
<summary>🎯 Answer</summary>

**Most likely cause: Unbounded cache or growing data structure.**

The `HashMap$Node` objects suggest a `HashMap` that grows indefinitely. Common patterns:
1. Static cache without eviction policy
2. Session data never cleaned up
3. Event listener list growing
4. In-memory data accumulated over time

**Root cause analysis:**

1. **Analyze heap dump:**
```bash
# Find the HashMap with most entries
jhat heap.dump  # Browse to find the root
# Or use Eclipse MAT: "Leak Suspects Report"
```

2. **Find the GC root path:**
```bash
# MAT: "Path to GC Roots" → shows which static field holds the map
# Common paths:
# - ThreadLocal → thread → ThreadLocalMap → HashMap
# - ClassLoader → loaded classes → static fields
# - Active threads → local variables
```

3. **Check common suspects:**
```bash
# Thread dumps during degradation:
jstack <pid> > threaddump.txt
# Look for consistent thread stacks in the same place
```

**Fixes:**
1. Add eviction: Guava Cache, Caffeine, or LRU LinkedHashMap
2. Use WeakHashMap for metadata caches
3. Add size limits with backpressure
4. Implement TTL (time-to-live) for entries
5. Use bounded collections

**Prevention:**
- Set `-XX:+HeapDumpOnOutOfMemoryError`
- Monitor heap usage with metrics (Prometheus + Grafana)
- Set `-XX:+ExitOnOutOfMemoryError` for auto-restart
- Use container memory limits with `-XX:MaxRAMPercentage=75.0`
</details>

---

## Summary

| Concept | Key Takeaway |
|---------|-------------|
| **Pass by value** | Java passes reference COPIES, never objects themselves |
| **Object layout** | Header (12-16 bytes) + fields + padding = object size |
| **Compressed OOPs** | 4-byte references for heaps < 32GB — saves ~40% memory |
| **Object lifecycle** | Class load → alloc (TLAB) → init → use → unreachable → GC → free |
| **Strong reference** | Default — prevents GC entirely |
| **SoftReference** | Cleared before OOME — good for caches |
| **WeakReference** | Cleared every GC — good for canonical maps |
| **PhantomReference** | Get() returns null — cleanup after GC |
| **TLAB** | Per-thread Eden region → ~10ns bump-pointer allocation |
| **Escape Analysis** | Stack allocation + scalar replacement if object doesn't escape |
| **String pool** | Interning for == comparison; watch memory with many unique strings |
| **Memory leaks** | Static collections, listeners, ThreadLocal, ClassLoaders, unclosed resources |
| **OOM types** | Heap, Metaspace, Direct memory, GC overhead, native threads |
