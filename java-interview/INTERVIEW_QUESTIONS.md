# ☕ Java — Staff-Level Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer, 15+ years in distributed systems and JVM-based infrastructure  
> **Target Level:** Staff/Principal Engineer (10+ years)  
> **Evaluation Focus:** JVM internals, concurrency models, garbage collection, Spring Boot internals, production system design

---

## Question 1: JVM Memory Model — Happens-Before & Volatile

**Interviewer:** *"Explain the Java Memory Model. What guarantees does `volatile` provide? What does `synchronized` actually do at the memory level? Walk me through a case where `volatile` is NOT enough."*

### Expected Answer (Staff Level)

**The Java Memory Model (JMM) — formalized in JSR-133 (Java 5+):**

The JMM defines when one thread's writes are visible to another thread. Without synchronization, there are NO guarantees — a read can see stale values, see writes out of order, or even see impossible values.

```java
// Without synchronization — NO guarantees
class BrokenCounter {
    int count = 0;
    
    void increment() { count++; }  // Read → Modify → Write = 3 separate operations!
    int get() { return count; }
}
// Thread A: increment() → count might be 0, then 1
// Thread B: get() → might see 0 (stale), 1, or even... nothing (no visibility guarantee)
```

**The Happens-Before Rules (JLS §17.4.5):**

```java
// Rule 1: Program order — within a thread, every action happens-before any later action
// Rule 2: Monitor lock — unlock on a monitor happens-before every subsequent lock on that monitor
// Rule 3: Volatile — write to a volatile field happens-before every subsequent read of that field
// Rule 4: Thread start — Thread.start() happens-before any action in the started thread
// Rule 5: Thread join — any action in a thread happens-before any other thread returns from join()
// Rule 6: Transitivity — if A happens-before B and B happens-before C, then A happens-before C
```

**`volatile` under the hood:**

```java
// volatile guarantees:
// 1. VISIBILITY: write to volatile v happens-before any subsequent read of v
// 2. ORDERING: compiler/JVM cannot reorder volatile accesses with surrounding code

// What the JVM actually does:
// - x86: volatile read = normal load (x86 has acquire semantics)
//        volatile write = MFENCE or locked instruction (xadd)
// - ARM/AARCH64: volatile read = LDAR (load-acquire)
//                volatile write = STLR (store-release)

// volatile does NOT guarantee atomicity!
public class VolatileDemo {
    private volatile int counter = 0;
    
    public void increment() {
        counter++;  // ← NOT atomic! counter = counter + 1 is:
        // 1. Read counter (volatile read)
        // 2. Increment (local computation)
        // 3. Write counter (volatile write)
        // → Step 1-2 can be interleaved between threads!
    }
}
```

**When `volatile` is NOT enough — the classic DCL problem:**

```java
// Double-Checked Locking — BROKEN without volatile (pre-Java 5)
class BrokenSingleton {
    private static BrokenSingleton instance;  // Need volatile!
    
    public static BrokenSingleton getInstance() {
        if (instance == null) {           // Check 1 (no lock)
            synchronized (BrokenSingleton.class) {
                if (instance == null) {   // Check 2 (with lock)
                    instance = new BrokenSingleton();  // ← PROBLEM!
                    // Without volatile, this can be reordered:
                    // (1) allocate memory
                    // (2) store reference to instance memory  ← THREAD B sees non-null!
                    // (3) run constructor                      ← NOT YET RUN!
                }
            }
        }
        return instance;  // Thread B gets partially constructed object!
    }
}

// ✅ FIX: volatile
class CorrectSingleton {
    private static volatile CorrectSingleton instance;
    
    public static CorrectSingleton getInstance() {
        if (instance == null) {
            synchronized (CorrectSingleton.class) {
                if (instance == null) {
                    instance = new CorrectSingleton();
                    // volatile → StoreStore barrier before constructor
                    //            StoreLoad barrier after constructor
                }
            }
        }
        return instance;
    }
}

// Even better: use holder class idiom (no synchronization!)
class HolderSingleton {
    private HolderSingleton() {}
    
    private static class Holder {
        static final HolderSingleton INSTANCE = new HolderSingleton();
    }
    
    public static HolderSingleton getInstance() {
        return Holder.INSTANCE;  // JVM guarantees class loading is thread-safe
    }
}
```

**`synchronized` internal mechanics:**

```java
// synchronized compiles to:
// monitorenter (ACC_SYNCHRONIZED flag on method, or explicit instruction)
// ... method body ...
// monitorexit (paired, including on exception)

// Under the hood:
// 1. Thread attempts to acquire monitor
// 2. If unlocked → mark word stores thread ID (biased locking, Java 15+ removed)
// 3. If contended → lightweight lock (CAS on mark word)
// 4. If still contended → heavyweight lock (OS mutex/condition variable)

// MARK WORD layout (64-bit JVM, little-endian):
// | unused:25 | hash:31 | age:4 | biased_lock:1 | lock:2 |
// OR (biased locking):
// | thread:54 | epoch:2 | age:4 | biased_lock:1 | lock:2 |

// Lock state transitions:
// No lock → Biased (single thread) → Lightweight (CAS) → Heavyweight (OS mutex)

// Memory effects of synchronized:
// synchronized block entry = acquire (volatile read semantic)
// synchronized block exit  = release (volatile write semantic)
// ALL writes inside synchronized block are visible to the NEXT thread
// that enters a synchronized block on the SAME monitor!
```

**The big picture — happens-before in action:**

```java
public class HappensBeforeDemo {
    private int x = 0;
    private volatile boolean flag = false;
    
    // Thread A
    public void writer() {
        x = 42;                    // 1. Normal write
        flag = true;               // 2. Volatile write → StoreLoad barrier
    }
    
    // Thread B
    public void reader() {
        if (flag) {                // 3. Volatile read (sees write from step 2)
            int r = x;             // 4. Normal read — GUARANTEED to see 42!
            // Because: (1) happens-before (2) by program order
            //          (2) happens-before (3) by volatile rule
            //          (3) happens-before (4) by program order
            //          ∴ (1) happens-before (4) by transitivity!
        }
    }
}
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Happens-before rules** | Recites the 6 rules without prompting, explains their practical impact |
| **volatile internals** | Knows what barrier is inserted (StoreLoad on x86, LDAR/STLR on ARM) |
| **DCL problem** | Explains the reordering issue precisely, proposes holder class idiom |
| **Synchronized optimization** | Knows biased locking, lock coarsening, lock elimination, adaptive spinning |

---

## Question 2: Garbage Collection — From Serial to G1 to ZGC

**Interviewer:** *"You have a latency-sensitive trading application with a 300GB heap. Design the GC strategy. Walk me through ZGC's colored pointers and load barriers. Then explain G1's region-based heap and remembered sets."*

### Expected Answer (Staff Level)

**GC evolution at a glance:**

```java
// Serial GC (-XX:+UseSerialGC)
// → Single thread, stop-the-world for ALL phases
// → Good for: small heaps (<100MB), single-core, desktop apps
// → Pause time: proportional to heap size (seconds for GB heaps)

// Parallel GC (-XX:+UseParallelGC)
// → Multi-threaded mark-compact, still stop-the-world
// → Good for: throughput-oriented batch jobs
// → Pause time: still seconds for large heaps

// CMS (-XX:+UseConcMarkSweepGC) — DEPRECATED Java 9, removed Java 14
// → Concurrent mark-sweep, but fragmentation problems
// → Failed to keep up with large heaps

// G1 (-XX:+UseG1GC — DEFAULT since Java 9)
// → Region-based, predictable pause times
// → Good for: 4GB-100GB heaps, sub-10ms pause targets

// ZGC (-XX:+UseZGC — experimental Java 11, production Java 15+)
// → Concurrent, colored pointers, load barriers
// → Sub-millisecond pause times, up to 16TB heap
// → Good for: latency-sensitive apps, huge heaps

// Shenandoah (-XX:+UseShenandoahGC — Java 12+)
// → Similar to ZGC but different approach (brooks pointers vs colored pointers)
// → Good for: latency-sensitive apps, smaller heaps
```

**G1 GC — Region-based heap:**

```java
// G1 divides the heap into ~2048 regions (1MB-32MB each)
// Each region is one of: Eden, Survivor, Old, or Humongous

// HEAP LAYOUT:
// [E][E][E][S][S][O][O][O][H][O][O][O][O][E][E][E]
//  ↑ Young gen regions        ↑ Humongous  ↑ Young gen
//                                (>50% of region)

// KEY DATA STRUCTURES:
// - Remembered Sets (RSets): per-region, track incoming references from OTHER regions
// - Collection Sets (CSets): set of regions to collect in a GC pause
//
// RSet example: Region 5 (Old, object X) ← Region 12 (Young, object Y references X)
//   Region 12's RSet: {} (nothing points TO young? No, other way)
//   Region 5's RSet: {Region 12, card 42} → "Region 12's card 42 has a pointer to me"
//
// Cards: 512-byte units. Dirty Card Queue tracks modified cards.
// Refinement threads process dirty cards → update RSets.

// G1 GC CYCLE (one iteration ≈ 200ms-2s depending on pause target):
//
// Phase 1: Young GC (concurrent with app)
//   - Stop-the-world (STW), but only young regions
//   - Eden → Survivor, Survivor → Old (aging)
//   - Uses RSets to find cross-region references
//   - Target: <10ms per young GC
//
// Phase 2: Concurrent Marking (triggered by IHOP)
//   - Initiating Heap Occupancy Percent (default: 45% of heap)
//   - Concurrent mark (with app running):
//     a. Initial mark (STW, ~1ms) — mark roots
//     b. Concurrent mark — trace object graph
//     c. Remark (STW, ~1ms) — finalize marking with SATB (Snapshot-At-The-Beginning)
//     d. Cleanup (STW, part) — compute region liveness
//
// Phase 3: Mixed GC (STW, multiple pauses)
//   - Collect OLD regions with most garbage first (greedy)
//   - Evacuate live objects from selected CSets
//   - Reclaim regions
//
// Phase 4: Full GC (STW, fallback when concurrent mode fails)
//   - Single-threaded mark-sweep-compact
//   - Can take minutes on large heaps!

// TUNING:
// -XX:MaxGCPauseMillis=200   → Target pause (G1 adjusts young gen size)
// -XX:G1HeapRegionSize=4m     → Region size (default: heap/2048)
// -XX:G1NewSizePercent=5      → Initial young gen (% of heap)
// -XX:G1MaxNewSizePercent=60  → Max young gen (% of heap)
// -XX:InitiatingHeapOccupancyPercent=45 → When to start concurrent mark
// -XX:G1MixedGCCountTarget=8  → Number of mixed GCs to complete marking
```

**ZGC — Colored Pointers and Load Barriers:**

```java
// ZGC is designed for:
// - Sub-millisecond pause times (<1ms target!)
// - Heaps up to 16TB (64-bit address space uses 44 bits → 16TB)
// - Concurrent compaction (no stop-the-world compaction)

// COLORED POINTERS (64-bit pointer reinterpretation):
//
// 6 6 5 5 5 5 5 5 5 5 5 5 4 4 4 4 4 4 4 4 4 4 4 4 3 3 3 3 3 3 3 3 3 3 3 3 2 2 2 2 2 2 2 2 2 2 2 2 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
// 3 2 1 0 9 8 7 6 5 4 3 2 1 0 9 8 7 6 5 4 3 2 1 0 9 8 7 6 5 4 3 2 1 0 9 8 7 6 5 4 3 2 1 0 9 8 7 6 5 4 3 2 1 0 9 8 7 6 5 4 3 2 1 0
//
// |<---------- 44 bits: object address (16TB address space) ---------->|M0|M1|R|0|
//                                                                    ^  ^  ^ ^
//                                                                    │  │  │ Reserved
//                                                                    │  │  Remapped (relocation)
//                                                                    │  Marked 1 (current marking)
//                                                                    Marked 0 (previous marking)
//
// The 3 metadata bits encode object state during GC:
// - M0: marked by current marking cycle
// - M1: marked by previous marking cycle
// - R:  remapped (relocation complete)

// LOAD BARRIER (not ReadBarrier — it's on EVERY object reference load):
//
// When a thread reads an object reference from the heap:
//   Object o = obj.field;  ← This triggers the load barrier!
//
// The barrier checks the pointer's metadata bits:
//   1. If M0=1 → object is alive, use directly
//   2. If M1=1 → object was alive in previous cycle, need to re-mark
//   3. If R=0  → object needs remapping (relocation)
//
// Simplified load barrier pseudo-code:
//   load_barrier(ptr):
//     if is_good(ptr):
//       return ptr
//     else:
//       if in_remap:
//         return remap_object(ptr)
//       else:
//         return mark_object(ptr)

// ZGC PHASES (all concurrent except tiny initial/resume phases):
//
// Phase 1: Pause Mark Start (STW, <1ms)
//   - Roots identified (no marking!)
//   - Set M0 bit = 0 for all objects
//
// Phase 2: Concurrent Mark (concurrent)
//   - Trace live objects from roots
//   - Load barrier handles mutator accesses during marking
//   - If mutator reads an unmarked object → mark it (self-healing)
//
// Phase 3: Pause Mark End (STW, <1ms)
//   - Finalize marking
//   - Prepare for relocation phase
//
// Phase 4: Concurrent Relocation (concurrent)
//   - Relocate live objects to new addresses
//   - Forward table maps old → new addresses
//   - Load barrier: if mutator accesses stale pointer → remap and self-heal
//
// Phase 5: Pause Relocate End (STW, <1ms)
//   - Clean up forwarding tables
//   - Flip M0/M1 for next cycle

// KEY FEATURE: ZGC never needs stop-the-world for compaction!
// The load barrier + colored pointers allow fully concurrent relocation.
```

**GC Strategy for the trading application (300GB heap, <5ms pause target):**

```java
// RECOMMENDATION: ZGC with tuned settings

// JVM flags:
// -XX:+UseZGC
// -Xms300G -Xmx300G                     // Fixed heap (no resizing overhead)
// -XX:SoftMaxHeapSize=280G              // GC target before triggering
// -XX:ConcGCThreads=8                   // Concurrent GC threads
// -XX:ParallelGCThreads=16              // STW parallel workers
// -XX:ZAllocationSpikeTolerance=2.0     // Handle allocation spikes
// -XX:+ZProactive                       // Proactive GC cycles
// -XX:ZUncommitDelay=300                // Delay before returning memory to OS

// Why NOT G1 for this workload:
// - 300GB heap → 300/2048 ≈ 150KB regions → WAY too small
// - G1 pause times: ~10-50ms per mixed GC
// - Remembered sets would be enormous
// - Multiple mixed GC pauses for full compaction

// Why NOT Parallel GC:
// - Full STW → 30+ second pauses

// Why ZGC wins:
// - Sub-millisecond pauses regardless of heap size
// - Concurrent relocation → no compaction pauses
// - Colored pointers → no remembered sets overhead
// - Scalable to 16TB
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **GC history** | Explains evolution from Serial → Parallel → CMS → G1 → ZGC with reasoning |
| **G1 internals** | Knows regions, RSets, SATB, mixed GC, IHOP |
| **ZGC colored pointers** | Explains the 44+3 bit layout and metadata bit semantics |
| **Load barrier** | Understands self-healing pointers, concurrent relocation |
| **Real tuning** | Can size a GC strategy for a specific workload, not just theory |

---

## Question 3: The `synchronized` vs `Lock` vs `Lock-Free` Showdown

**Interviewer:** *"You need a high-throughput concurrent data structure. Walk me through `synchronized`, `ReentrantLock`, `StampedLock`, and `VarHandle`. When would you use each? Implement a lock-free stack using `VarHandle`."*

### Expected Answer (Staff Level)

**Lock evolution in Java:**

```java
// ═══════════════════════════════════════════════════════════════
// 1. synchronized — Built-in, simplest, most optimized by JIT
// ═══════════════════════════════════════════════════════════════
public class SynchronizedCounter {
    private int count = 0;
    
    // JIT optimizations:
    // - Biased locking (removed Java 15+): lock biased towards first thread
    // - Lock coarsening: adjacent synchronized blocks merged
    // - Lock elision: if JIT proves object is thread-local → remove lock entirely
    // - Adaptive spinning: spin a few times before parking
    
    public synchronized void increment() {
        count++;
    }
    
    public synchronized int get() {
        return count;
    }
}

// ═══════════════════════════════════════════════════════════════
// 2. ReentrantLock — More features, explicit try/finally
// ═══════════════════════════════════════════════════════════════
import java.util.concurrent.locks.ReentrantLock;

public class LockCounter {
    private final ReentrantLock lock = new ReentrantLock(true); // fair=true
    private int count = 0;
    
    public void increment() {
        lock.lock();
        try {
            count++;
        } finally {
            lock.unlock();  // MUST release in finally!
        }
    }
    
    // Advanced: tryLock with timeout
    public boolean tryIncrement(long timeout, TimeUnit unit) 
            throws InterruptedException {
        if (lock.tryLock(timeout, unit)) {
            try {
                count++;
                return true;
            } finally {
                lock.unlock();
            }
        }
        return false;
    }
    
    // ReentrantLock features synchronized doesn't have:
    // - Fairness policy
    // - tryLock with timeout
    // - lockInterruptibly()
    // - Condition (multiple wait sets per lock)
    // - getQueuedThreads() (monitoring)
    // - Read/Write separation (ReentrantReadWriteLock)
}

// ═══════════════════════════════════════════════════════════════
// 3. StampedLock — Optimistic reads for read-heavy workloads
// ═══════════════════════════════════════════════════════════════
import java.util.concurrent.locks.StampedLock;

public class StampedLockCounter {
    private final StampedLock sl = new StampedLock();
    private int count = 0;
    
    public void increment() {
        long stamp = sl.writeLock();
        try {
            count++;
        } finally {
            sl.unlockWrite(stamp);
        }
    }
    
    public int get() {
        // OPTIMISTIC READ — NO lock acquired!
        long stamp = sl.tryOptimisticRead();
        int current = count;
        
        // Validate: if stamp is still valid, read was consistent
        // If not (a writer intervened), fall back to full read lock
        if (!sl.validate(stamp)) {
            stamp = sl.readLock();
            try {
                current = count;
            } finally {
                sl.unlockRead(stamp);
            }
        }
        return current;
    }
}
// StampedLock performance:
// - Optimistic read: ~1-2ns (just a volatile read + validation)
// - ReadLock: ~50-100ns
// - WriteLock: ~50-100ns
// - synchronized: ~20-50ns (biased + uncontended)
// These numbers vary hugely by JVM version and hardware!

// ═══════════════════════════════════════════════════════════════
// 4. VarHandle — Direct memory access, lock-free CAS
// ═══════════════════════════════════════════════════════════════
import java.lang.invoke.VarHandle;

public class LockFreeCounter {
    private volatile int count = 0;
    private static final VarHandle COUNT;
    
    static {
        try {
            COUNT = MethodHandles.lookup()
                .findVarHandle(LockFreeCounter.class, "count", int.class);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }
    
    public void increment() {
        // CAS loop — lock-free (wait-free if no contention)
        int prev;
        do {
            prev = (int) COUNT.getVolatile(this);
        } while (!COUNT.compareAndSet(this, prev, prev + 1));
    }
    
    public int get() {
        return (int) COUNT.getVolatile(this);
    }
}
```

**Lock-Free Stack using VarHandle (Treiber Stack):**

```java
import java.lang.invoke.VarHandle;
import java.util.concurrent.atomic.AtomicReference;

public class LockFreeStack<T> {
    private volatile Node<T> top = null;
    
    private static final VarHandle TOP;
    
    static {
        try {
            TOP = MethodHandles.lookup()
                .findVarHandle(LockFreeStack.class, "top", Node.class);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }
    
    private static class Node<T> {
        final T value;
        volatile Node<T> next;
        
        Node(T value) { this.value = value; }
    }
    
    // Lock-free push — CAS loop (no ABA problem with single pointer)
    public void push(T value) {
        Node<T> newNode = new Node<>(value);
        Node<T> oldTop;
        do {
            oldTop = top;
            newNode.next = oldTop;
        } while (!TOP.compareAndSet(this, oldTop, newNode));
    }
    
    // Lock-free pop
    public T pop() {
        Node<T> oldTop;
        Node<T> newTop;
        do {
            oldTop = top;
            if (oldTop == null) {
                return null;  // Empty
            }
            newTop = oldTop.next;
        } while (!TOP.compareAndSet(this, oldTop, newTop));
        
        return oldTop.value;
    }
    
    // Note: ABA problem exists here!
    // Fix: use AtomicStampedReference or insert dummy nodes
}

// ═══════════════════════════════════════════════════════════════
// Performance characteristics
// ═══════════════════════════════════════════════════════════════
//
// synchronized (uncontended): ~20-50ns
// ReentrantLock (uncontended): ~30-60ns
// StampedLock (optimistic read): ~1-2ns
// StampedLock (write): ~50-100ns
// VarHandle CAS: ~10-30ns
// AtomicInteger CAS: ~10-30ns
//
// Under contention, ALL of these degrade.
// At extreme contention (~8+ threads > 50% CAS failure):
//   - Lock-free CAS loops: CPU spins at 100% (can use Thread.onSpinWait())
//   - synchronized/reentrant: threads park (lower CPU, but context switches)
//   - In practice: spinning better for <10μs contention, parking for longer
```

**Decision matrix:**

```java
//                    synchronized  ReentrantLock  StampedLock  VarHandle
// Simple               ✅ BEST          ✅             ❌          ❌
// Fairness             ❌               ✅             ❌          ❌
// Multiple Conditions  ❌               ✅             ❌          ❌
// Interruptible        ❌               ✅             ❌          ❌
// Optimistic read      ❌               ❌          ✅ BEST       ❌
// Lock-free            ❌               ❌             ❌     ✅ BEST
// Read-heavy           ⚠️               ⚠️         ✅ BEST       ✅
// Write-heavy          ✅               ✅             ⚠️          ✅
// JIT optimized        ✅ BEST           ✅             ⚠️          ✅
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Lock evolution** | Can explain evolution from synchronized → Lock → StampedLock → VarHandle |
| **Lock-free stack** | Implements Treiber stack with CAS, acknowledges ABA problem |
| **Performance numbers** | Gives approximate ns ranges, explains spinning vs parking trade-off |
| **JIT optimizations** | Knows lock coarsening, elision, biased locking history |

---

## Question 4: Spring Boot Auto-Configuration & DI Container Internals

**Interviewer:** *"Explain how Spring Boot auto-configuration works under the hood. How does `@Conditional` work? How does Spring resolve circular dependencies? Walk me through the bean lifecycle from `@PostConstruct` to `@PreDestroy`."*

### Expected Answer (Staff Level)

**Auto-configuration mechanism:**

```java
// 1. @SpringBootApplication meta-annotations:
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@SpringBootConfiguration      // ≡ @Configuration
@EnableAutoConfiguration      // ← The magic starts here
@ComponentScan                // Scans current package and subpackages
public @interface SpringBootApplication {}

// 2. @EnableAutoConfiguration imports AutoConfigurationImportSelector:
//    This class reads META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
//    (Spring Boot 3.x, was spring.factories in 2.x)

// Sample content of that file:
// org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration
// org.springframework.boot.autoconfigure.data.jpa.JpaRepositoriesAutoConfiguration
// org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration
// ... 100+ auto-configuration classes

// 3. Each auto-configuration class has @Conditional annotations:

@AutoConfiguration  // Replaces @Configuration in auto-config context
@ConditionalOnClass(DataSource.class)     // Only if H2/HikariCP on classpath
@ConditionalOnMissingBean(DataSource.class)  // Only if user hasn't defined one
@EnableConfigurationProperties(DataSourceProperties.class)
public class DataSourceAutoConfiguration {
    
    @Bean
    @ConditionalOnMissingBean
    public DataSource dataSource(DataSourceProperties properties) {
        // Creates HikariCP connection pool
        HikariDataSource ds = new HikariDataSource();
        ds.setJdbcUrl(properties.getUrl());
        ds.setUsername(properties.getUsername());
        ds.setPassword(properties.getPassword());
        return ds;
    }
}

// 4. @Conditional types:
// @ConditionalOnClass / @ConditionalOnMissingClass → classpath check
// @ConditionalOnBean / @ConditionalOnMissingBean → bean existence check
// @ConditionalOnProperty → environment property check
// @ConditionalOnResource → file/resource check
// @ConditionalOnWebApplication → web context check
// @ConditionalOnExpression → SpEL expression
// All of these use the Condition SPI:
```

**Condition SPI and custom conditions:**

```java
public class OnRedisCondition implements Condition {
    @Override
    public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
        // Check if Redis is available at runtime
        try {
            String host = context.getEnvironment().getProperty("redis.host", "localhost");
            int port = context.getEnvironment().getProperty("redis.port", Integer.class, 6379);
            
            // Try connecting
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(host, port), 1000);
                return true;
            }
        } catch (Exception e) {
            return false;  // Redis not available → skip this configuration
        }
    }
}

@Configuration
@Conditional(OnRedisCondition.class)  // Only if Redis is actually reachable!
public class RedisAutoConfiguration {
    @Bean
    public RedisTemplate<String, Object> redisTemplate() {
        return new RedisTemplate<>();
    }
}
```

**DI Container internals — bean lifecycle:**

```java
// The Spring bean lifecycle (in order):
//
// 1. Instantiate: create raw bean via constructor (reflection)
// 2. Populate properties: setter injection / field injection
// 3. Set bean name (setBeanName if BeanNameAware)
// 4. Set bean factory (setBeanFactory if BeanFactoryAware)
// 5. Pre-initialization: BeanPostProcessor.postProcessBeforeInitialization
// 6. @PostConstruct / InitializingBean.afterPropertiesSet()
// 7. Custom init-method
// 8. Post-initialization: BeanPostProcessor.postProcessAfterInitialization
//    → PROXY CREATION happens here! (AOP, @Transactional, @Cacheable)
//    → The returned proxy REPLACES the original bean in the container
// 9. Bean is ready to use
// ...
// 10. @PreDestroy / DisposableBean.destroy()
// 11. Custom destroy-method

// BeanPostProcessor — the most powerful extension point:
@Component
public class TimingBeanPostProcessor implements BeanPostProcessor {
    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) {
        if (bean instanceof SomeService) {
            System.out.println("Before init: " + beanName);
        }
        return bean;  // Must return the bean (or a proxy!)
    }
    
    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) {
        if (bean instanceof SomeService) {
            // Create a timing proxy
            return Proxy.newProxyInstance(
                bean.getClass().getClassLoader(),
                bean.getClass().getInterfaces(),
                (proxy, method, args) -> {
                    long start = System.nanoTime();
                    Object result = method.invoke(bean, args);
                    long duration = System.nanoTime() - start;
                    System.out.printf("%s.%s took %dμs%n", 
                        beanName, method.getName(), duration / 1000);
                    return result;
                });
        }
        return bean;
    }
}
```

**Circular dependency resolution:**

```java
// Spring uses THREE-LEVEL CACHING to handle circular dependencies:
//
// Level 1: singletonObjects (the fully initialized singleton cache)
// Level 2: earlySingletonObjects (exposed EARLY, before post-processing)
// Level 3: singletonFactories (ObjectFactory for early exposure)
//
// How it works for this circular case:
//   @Service class A { @Autowired B b; }
//   @Service class B { @Autowired A a; }

// Step 1: Spring starts instantiating A
//   → calls A's constructor → raw A object (not yet populated)
//   → puts A into Level 3 (singletonFactories)
//   → starts populating A's dependencies
//     → needs B → starts instantiating B

// Step 2: Spring instantiates B
//   → calls B's constructor → raw B object
//   → puts B into Level 3
//   → starts populating B's dependencies
//     → needs A
//     → checks Level 1: not found
//     → checks Level 2: not found
//     → checks Level 3: FOUND! (A's ObjectFactory)
//     → calls A's ObjectFactory.get() → returns raw A (before AOP!)
//     → puts raw A into Level 2 (earlySingletonObjects)
//     → injects raw A into B

// Step 3: B is now fully populated
//   → B goes through post-processing (AOP proxies created if needed)
//   → moves B to Level 1 (fully initialized)

// Step 4: Spring returns to A
//   → A has its B dependency now (fully initialized)
//   → A goes through post-processing
//   → moves A to Level 1

// LIMITATION: Constructor injection doesn't support circular deps!
// @Service class A { 
//     private final B b;  // ← constructor injection
//     public A(B b) { this.b = b; }  // → Can't create A without B!
// }
// @Service class B {
//     private final A a;  // ← constructor injection  
//     public B(A a) { this.a = a; }  // → Can't create B without A!
// }
// → BeanCurrentlyInCreationException!
// → FIX: use setter/field injection for at least one of the pair

// WHY NOT constructor injection for circular deps:
// Constructor time is BEFORE level 3 factory creation
// The early-exposure trick (level 3) only works AFTER constructor runs
// → Constructor injection can't use the circular dependency cache!
```

**AOP internals — JDK Proxy vs CGLIB:**

```java
// Spring creates proxies for @Transactional, @Cacheable, @Async, @Secured
//
// JDK Dynamic Proxy (default when bean implements an interface):
//   - Creates proxy implementing ALL bean interfaces
//   - Method calls go through InvocationHandler
//   - Only intercepts INTERFACE methods
//   - Uses: java.lang.reflect.Proxy

// CGLIB Proxy (when bean doesn't implement interfaces):
//   - Creates SUBCLASS of the bean class
//   - Overrides ALL non-final methods
//   - Can intercept class methods too
//   - Uses: org.springframework.cglib.proxy.Enhancer

// THE INFAMOUS @Transactional SELF-INVOCATION PROBLEM:
@Service
public class UserService {
    @Transactional
    public void createUser(User user) {
        save(user);
        sendWelcomeEmail(user.getEmail());  // ← NOT transactional!
    }
    
    @Transactional(propagation = REQUIRES_NEW)
    public void sendWelcomeEmail(String email) {
        // This runs WITHOUT a transaction!
        // Because: this.sendWelcomeEmail() calls the method DIRECTLY
        // on the raw bean, NOT through the proxy!
    }
}

// Why? 
// userService bean = PROXY wrapping the real UserService
// userService.createUser(...) → goes through proxy → transaction opens → real method called
// Inside createUser: this.sendWelcomeEmail(...)
//   "this" is the REAL UserService (not the proxy!)
//   → No transaction!

// FIX:
// 1. Self-inject the proxy:
@Service
public class UserService {
    @Autowired
    private UserService self;  // ← Injects the PROXY!
    
    @Transactional
    public void createUser(User user) {
        save(user);
        self.sendWelcomeEmail(user.getEmail());  // ← Goes through proxy!
    }
}

// 2. Extract to a separate service (cleaner)
// 3. Use AspectJ compile-time weaving (no proxy needed)
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Auto-configuration** | Explains the import mechanism + @Conditional evaluation order |
| **Bean lifecycle** | Recites all 11+ steps, knows where proxy creation happens |
| **Circular deps** | Explains 3-level cache, knows why constructor injection fails |
| **AOP proxy** | Explains self-invocation problem and all 3 fixes |

---

## Question 5: Concurrency — Executors, Fork/Join, and Virtual Threads

**Interviewer:** *"Design a task execution system that handles 100K tasks per second with varying execution times (1μs to 10s). Compare ThreadPoolExecutor, ForkJoinPool, and Virtual Threads (Project Loom). Where does each excel and fail?"*

### Expected Answer (Staff Level)

**ThreadPoolExecutor — the workhorse:**

```java
import java.util.concurrent.*;

public class CustomThreadPool {
    
    // ThreadPoolExecutor parameters:
    // corePoolSize: threads kept alive even when idle
    // maxPoolSize: maximum threads that can be created
    // keepAliveTime: time before idle threads are terminated (beyond core)
    // workQueue: holds tasks when all core threads are busy
    // handler: what to do when queue is full AND max threads reached
    
    private final ThreadPoolExecutor executor;
    
    public CustomThreadPool() {
        BlockingQueue<Runnable> workQueue;
        
        // Queue types — CHOOSE CAREFULLY:
        
        // 1. LinkedBlockingQueue (unbounded) — DEFAULT
        //    → maxPoolSize is IGNORED (queue never fills)
        //    → Can grow indefinitely → memory issues
        //    → Use for: predictable load, limited task rate
        // Executors.newFixedThreadPool(n) uses this
        
        // 2. SynchronousQueue (handoff, no capacity)
        //    → Every task immediately needs a thread
        //    → maxPoolSize IS used (queue is always "full")
        //    → Can create maxPoolSize threads quickly
        //    → Use for: many short-lived tasks
        // Executors.newCachedThreadPool() uses this
        
        // 3. ArrayBlockingQueue (bounded)
        //    → Best control: bounded queue + bounded threads
        //    → When queue fills → new threads up to maxPoolSize
        //    → When max threads reached → rejection handler
        //    → Use for: production systems!
        workQueue = new ArrayBlockingQueue<>(10000);
        
        executor = new ThreadPoolExecutor(
            50,            // corePoolSize
            200,           // maxPoolSize
            60,            // keepAliveTime
            TimeUnit.SECONDS,
            workQueue,
            new ThreadPoolExecutor.CallerRunsPolicy()  // Rejection handler
        );
    }
    
    // Rejection handlers:
    // AbortPolicy (default) → throws RejectedExecutionException
    // CallerRunsPolicy → runs task in caller's thread (backpressure!)
    // DiscardPolicy → silently discards
    // DiscardOldestPolicy → discards oldest queued task
    // Custom → implement RejectedExecutionHandler
    
    public Future<?> submit(Runnable task) {
        return executor.submit(task);
    }
    
    // Monitoring hooks
    public void printStats() {
        System.out.printf("Pool: %d/%d active, Queue: %d/%d, Completed: %d%n",
            executor.getActiveCount(), 
            executor.getPoolSize(),
            executor.getQueue().size(),
            executor.getQueue().remainingCapacity() + executor.getQueue().size(),
            executor.getCompletedTaskCount());
    }
}
```

**ForkJoinPool — work-stealing for divide-and-conquer:**

```java
import java.util.concurrent.*;

// ForkJoinPool is designed for:
// - Recursive decomposition (divide and conquer)
// - CPU-bound parallel computation
// - Work-stealing: idle threads steal from busy threads' queues
    
// EXAMPLE: Parallel sum of 10M integers

public class ParallelSum extends RecursiveTask<Long> {
    private static final int THRESHOLD = 10000;
    private final int[] array;
    private final int start, end;
    
    public ParallelSum(int[] array, int start, int end) {
        this.array = array;
        this.start = start;
        this.end = end;
    }
    
    @Override
    protected Long compute() {
        int length = end - start;
        
        if (length <= THRESHOLD) {
            // Sequential computation (base case)
            long sum = 0;
            for (int i = start; i < end; i++) {
                sum += array[i];
            }
            return sum;
        }
        
        // Divide and conquer
        int mid = start + length / 2;
        ParallelSum left = new ParallelSum(array, start, mid);
        ParallelSum right = new ParallelSum(array, mid, end);
        
        // Fork = schedule for parallel execution
        left.fork();
        
        // Compute right in current thread
        long rightResult = right.compute();
        
        // Join = wait for left result
        long leftResult = left.join();
        
        return leftResult + rightResult;
    }
    
    public static void main(String[] args) {
        int[] array = new int[10_000_000];
        Arrays.fill(array, 1);
        
        ForkJoinPool pool = new ForkJoinPool(
            Runtime.getRuntime().availableProcessors() // parallelism
        );
        
        long result = pool.invoke(new ParallelSum(array, 0, array.length));
        System.out.println("Sum: " + result);  // 10_000_000
        
        pool.shutdown();
    }
}

// ForkJoinPool vs ThreadPoolExecutor key differences:
//
// ForkJoinPool:
// - Each thread has its OWN deque (double-ended queue)
// - Work-stealing: idle threads steal from the BACK of other threads' deques
// - LIFO scheduling (top of deque) → better cache locality
// - Built for task granularity: fork small tasks, the pool manages them
// - No work queue in traditional sense
// - Best for: CPU-bound, recursive, balanced tasks
//
// ThreadPoolExecutor:
// - SHARED blocking queue for all threads
// - FIFO scheduling (queue head)
// - Threads compete for queue (one mutex)
// - No work-stealing
// - Best for: I/O-bound, heterogeneous, coarse tasks
```

**Virtual Threads (Project Loom — Java 21+):**

```java
// Virtual threads are JVM-managed "lightweight" threads
// - Mounted on platform/carrier threads (fork/join pool)
// - Park/unpark in microseconds (vs OS thread context switch: microseconds...)
//   Actually: VT park is ~1μs, OS thread park is ~5-10μs
// - Can have millions per JVM (OS threads: thousands)
// - No ThreadPool needed — just create new virtual thread per task

import java.util.concurrent.*;

public class VirtualThreadDemo {
    
    // Before virtual threads:
    public static void threadPerTask() {
        try (var executor = Executors.newFixedThreadPool(200)) {
            for (int i = 0; i < 10_000; i++) {
                int taskId = i;
                executor.submit(() -> handleRequest(taskId));
                // 200 OS threads max, queue for the rest
                // Context switching cost adds latency
            }
        }
    }
    
    // With virtual threads (Java 21+):
    public static void virtualThreadPerTask() throws Exception {
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            for (int i = 0; i < 10_000; i++) {
                int taskId = i;
                executor.submit(() -> handleRequest(taskId));
                // 10,000 virtual threads, mounted on ~8 carrier threads
                // No pool, no queue, just create
            }
        }
        // executor.close() waits for all tasks
    }
    
    // Even simpler: directly create virtual threads
    public static void directVirtual() {
        Thread vt = Thread.startVirtualThread(() -> {
            System.out.println("Running on: " + Thread.currentThread());
            // When this blocks on I/O, the virtual thread parks
            // and the carrier thread picks up another task
        });
    }
    
    private static void handleRequest(int id) {
        // Simulate I/O (e.g., API call, DB query)
        try {
            Thread.sleep(100);  // ← This parks the VIRTUAL thread, 
            // NOT the carrier thread! Carrier picks up another VT.
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}

// Internals — how mounting works:
//
// OS Thread (carrier) = platform thread
// Virtual Thread = continuation + scheduler
//
// Continuation: captures stack as an object (in heap!)
// When VT blocks (sleep, lock, I/O):
//   1. Stack is copied from carrier's native stack → heap
//   2. VThread is unmounted from carrier
//   3. Scheduler picks another ready VThread for the carrier
//   4. When I/O completes, VThread is re-mounted (stack copied back)
//
// KEY LIMITATIONS (Java 21):
// - synchronized blocks PIN the virtual thread to carrier!
//   → If VT acquires synchronized, it can't unmount
//   → Long synchronized = carrier thread blocked
//   → FIX: use ReentrantLock instead of synchronized
// - Native methods via JNI pin the carrier
// - ThreadLocal has no special support → scalability issues
// - Custom caches: ForkJoinPool.commonPool() is the scheduler
```

**Decision framework for 100K tasks/sec:**

```java
// TASK TYPES:
// Type A: short CPU (1μs-1ms) → ForkJoinPool
// Type B: I/O bound (1ms-10s)  → Virtual Threads (or reactive)
// Type C: mixed (CPU + I/O)    → Virtual Threads + parallel streams
// Type D: long CPU (>1s)       → ThreadPoolExecutor (bounded, monitoring)

// For 100K tasks/sec, typical workload is I/O-heavy:
// → Virtual Threads are IDEAL
// → No pool management
// → 10K simultaneous tasks = 10K virtual threads = trivial memory
// → No contention on shared queue

// But if tasks are CPU-bound:
// → Virtual threads don't help (no blocking → no unmounting)
// → ForkJoinPool with proper chunking
// → Parallel streams with custom FJP

// PRODUCTION PATTERN: use StructuredTaskScope (Java 21+)
```

**StructuredTaskScope — structured concurrency:**

```java
// Java 21+ — structured concurrency with error handling and scoping

import java.util.concurrent.*;

public class StructuredConcurrencyDemo {
    
    record Order(User user, List<Product> products, double total) {}
    record User(long id, String name, String email) {}
    record Product(long id, String name, double price) {}
    
    public Order processOrder(long userId, List<Long> productIds) 
            throws InterruptedException, ExecutionException {
        
        // BEFORE (unstructured): tasks are scattered
        // Future<User> userFuture = executor.submit(() -> fetchUser(userId));
        // Future<Product> productFuture = executor.submit(() -> fetchProduct(...));
        // // If fetchUser fails, fetchProduct keeps running — ORPHANED!
        
        // AFTER (structured, Java 21+):
        try (var scope = new StructuredTaskScope.ShutdownOnFailure()) {
            // All tasks are CHILDREN of this scope
            // If any fails → shutdown scope → cancel all siblings
            // If all succeed → gather results
            // Parent waits for ALL children to finish
            
            Subtask<User> user = scope.fork(() -> fetchUser(userId));
            Subtask<List<Product>> products = scope.fork(
                () -> fetchProducts(productIds));
            Subtask<Double> pricing = scope.fork(
                () -> calculatePricing(productIds));
            
            // Wait for all or fail
            scope.join();  // Blocks until all tasks complete or fail
            scope.throwIfFailed();  // Propagate first failure
            
            // All succeeded — get results safely
            return new Order(user.get(), products.get(), pricing.get());
        }
        // scope.close() ensures no orphaned tasks!
    }
    
    private User fetchUser(long id) { /* ... */ }
    private List<Product> fetchProducts(List<Long> ids) { /* ... */ }
    private Double calculatePricing(List<Long> ids) { /* ... */ }
}

// Shutdown policy options:
// StructuredTaskScope.ShutdownOnFailure()    → Shutdown on any failure
// StructuredTaskScope.ShutdownOnSuccess()    → Shutdown on any success (race)
// Custom: extend StructuredTaskScope
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Queue trade-offs** | Explains SyncQueue vs ArrayBlockingQueue vs LinkedBlockingQueue trade-offs |
| **Work-stealing** | Explains FJP deque structure, LIFO scheduling, theft-from-back |
| **Virtual threads** | Explains mounting/unmounting, continuation, pinning with synchronized |
| **Structured concurrency** | Knows StructuredTaskScope, orphan detection, shutdown policies |

---

## Question 6: Java Collections Framework — Internals & Performance

**Interviewer:** *"Walk me through the internal structure of HashMap, ConcurrentHashMap, and TreeMap. When would you use a LinkedHashMap over a TreeMap? What happens when HashMap reaches its load factor? How does ConcurrentHashMap achieve thread-safety without locking the entire map?"*

### Expected Answer (Staff Level)

**HashMap internals (Java 8+):**

```java
// Internal structure:
// Entry<K,V>[] table (power of 2 size, default 16)
// Each bucket is either:
//   - null (empty)
//   - Node<K,V> (single entry)
//   - TreeNode<K,V> (RED-BLACK TREE, when bin count >= 8)
//   - linked list of Node<K,V> (when bin count < 8)

// HASH COMPUTATION:
// int hash = key.hashCode();
// int improvedHash = (h = key.hashCode()) ^ (h >>> 16);  // XOR high bits
// int index = (table.length - 1) & improvedHash;  // Modulo for power of 2

// PUT OPERATION (simplified):
// 1. Compute hash → index
// 2. If table[index] == null → insert Node
// 3. If table[index] is a TreeNode → tree insertion
// 4. If table[index] is a linked list → walk list:
//    a. If key found → replace value
//    b. If not found → append to end of list
//    c. If list length >= TREEIFY_THRESHOLD (8) → convert to tree
// 5. If size > threshold (capacity * loadFactor) → resize

// RESIZE OPERATION:
// - New capacity = old capacity * 2 (always power of 2)
// - Elements are NOT rehashed (Java 8 optimization):
//   An element in position i is either:
//   - Same index i in new table, OR
//   - Index i + oldCapacity in new table
//   - Decision depends on a single bit: hash & oldCapacity
// - This is why capacity is always power of 2!

// Red-Black Tree properties:
// - Self-balancing binary search tree
// - O(log n) for get/put/remove (vs O(n) for linked list worst case)
// - Reverts to linked list when bin count < UNTREEIFY_THRESHOLD (6)
// - Why 8 for treeify? Poisson distribution: λ ≈ 0.5 → P(8) ≈ 0.00000003
//   In practice, bin count > 8 only happens with terrible hashCode()

// WHY NOT use trees immediately?
// - Trees are 2-3x more memory than nodes (TreeNode has 6 references vs Node's 4)
// - For small bins (<8), list traversal is faster than tree navigation
```

**ConcurrentHashMap internals (Java 8+):**

```java
// Java 7: Segment-based locking (16 segments, each with own lock)
// Java 8+: CAS + synchronized on individual bins (finely grained)

// Internal structure:
// Node<K,V>[] table  (same as HashMap, but volatile)
// CAS operations on head of each bin
// synchronized only on the specific bin being modified

// GET (no lock, completely concurrent):
// V get(Object key) {
//     int hash = spread(key.hashCode());
//     Node<K,V>[] tab; Node<K,V> e;
//     int n;  // table length
//     
//     if ((tab = table) != null && (n = tab.length) > 0 &&
//         (e = tabAt(tab, (n - 1) & hash)) != null) {
//         
//         if (e.hash == hash && ((ek = e.key) == key || (ek != null && key.equals(ek))))
//             return e.val;  // Head of bin
//         
//         if (e.hash < 0)  // Tree or ForwardingNode
//             return (e = e.find(hash, key)) != null ? e.val : null;
//         
//         while ((e = e.next) != null) {  // Walk linked list
//             if (e.hash == hash && ((ek = e.key) == key || (ek != null && key.equals(ek))))
//                 return e.val;
//         }
//     }
//     return null;
// }
// 
// KEY: get() uses Unsafe.getObjectVolatile() for volatile reads
// No lock needed! Writes are CAS'd or synchronized per bin.

// PUT (CAS on bin head, synchronized on bin for collisions):
// V put(K key, V value) {
//     for (Node<K,V>[] tab = table;;) {
//         Node<K,V> f; int n, i, fh;
//         
//         if (tab == null || (n = tab.length) == 0)
//             tab = initTable();  // Lazy init with CAS on sizeCtl
//         
//         else if ((f = tabAt(tab, i = (n - 1) & hash)) == null) {
//             // Bin is empty — CAS the new node (no lock!)
//             if (casTabAt(tab, i, null, new Node<K,V>(hash, key, value, null)))
//                 break;
//         }
//         
//         else if ((fh = f.hash) == MOVED)
//             tab = helpTransfer(tab, f);  // Resize in progress — help!
//         
//         else {
//             // Bin exists — synchronized on bin head only
//             V oldVal = null;
//             synchronized (f) {
//                 // Double-check after acquiring lock
//                 if (tabAt(tab, i) == f) {
//                     if (fh >= 0) {  // Linked list
//                         // Walk and insert/update
//                     } else if (f instanceof TreeBin) {  // Tree
//                         // Tree insertion
//                     }
//                 }
//             }
//             if (oldVal != null) return oldVal;
//         }
//     }
// }

// COUNTER OPERATION:
// - Java 7: segment-level counter (contended)
// - Java 8: CounterCell[] — striped counters
//   Multiple counter cells reduce contention
//   Sum all CounterCell values + baseCount for size()
//   size() is an O(n) estimate, not exact!

// RESIZE (transfer) — multi-threaded!
// - ForwardingNode (hash=MOVED) marks transferred bins
// - Multiple threads can help with transfer
// - Each thread claims a stride of bins via CAS on transferIndex
// - New table is accessed through ForwardingNode.find()
```

**TreeMap — Red-Black Tree:**

```java
// TreeMap implements NavigableMap (sorted map)
// Internal structure: Red-Black Tree
//
// Properties:
// 1. Every node is either RED or BLACK
// 2. Root is always BLACK
// 3. No two adjacent RED nodes (RED parent → BLACK children)
// 4. Every path from root to leaf has same number of BLACK nodes
// 5. Leaves (nulls) are BLACK
//
// Operations: O(log n) for get/put/remove
// - Insert: O(log n) + up to 2 rotations + re-coloring
// - Delete: O(log n) + up to 3 rotations + re-coloring

// TreeMap vs LinkedHashMap:
//
// TreeMap:
//   - Sorted by keys (Comparable or Comparator)
//   - O(log n) operations
//   - Supports: subMap(), headMap(), tailMap(), floorKey(), ceilingKey()
//   - Memory: tree nodes (left/right/parent/color/entry → ~48 bytes each)
//   - Use: need sorted iteration, range queries
//
// LinkedHashMap:
//   - Maintains insertion-order (or access-order) doubly-linked list
//   - O(1) operations
//   - Supports: put-order iteration, access-order for LRU caches
//   - Memory: entry + before/after pointers (~32 bytes each)
//   - Use: need predictable iteration order, LRU caches
//   - removeEldestEntry() for automatic LRU eviction
```

**LinkedHashMap as LRU Cache:**

```java
public class LRUCache<K, V> extends LinkedHashMap<K, V> {
    private final int maxCapacity;
    
    public LRUCache(int maxCapacity) {
        // accessOrder=true → order by most-recent-access, not insertion
        super(16, 0.75f, true);  // access order, not insertion!
        this.maxCapacity = maxCapacity;
    }
    
    @Override
    protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
        // Automatically called after every put()
        // Remove oldest entry if over capacity
        return size() > maxCapacity;
    }
}

// Usage:
// LRUCache<String, Object> cache = new LRUCache<>(1000);
// cache.put("key", value);
// // Automatically evicts least-recently-used when > 1000 entries

// Note: LinkedHashMap is NOT thread-safe!
// Use Collections.synchronizedMap() or ConcurrentHashMap variant
```

**Collections performance comparison (approximate, per operation):**

```java
//                get       put      containsKey  iteration  memory/entry
// HashMap        O(1)      O(1)     O(1)         O(cap+n)   32 bytes
// LinkedHashMap  O(1)      O(1)     O(1)         O(n)       40 bytes
// TreeMap        O(log n)  O(log n) O(log n)     O(n)       48 bytes
// ConcurrentHashMap O(1)   O(1)     O(1)         O(cap+n)   36 bytes
// CopyOnWriteArrayList: all mutating ops are O(n) (copy array)
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **HashMap resize** | Explains power-of-2, bit test for reindexing (no rehash needed) |
| **CHM get** | Knows get() is lock-free (volatile reads, CAS for bin head) |
| **CHM resize** | Explains multi-threaded transfer, ForwardingNode |
| **LRU cache** | Can implement with LinkedHashMap+accessOrder+removeEldestEntry |

---

## Question 7: Java Memory Model — Safepoints, Barriers, and JIT Compilation

**Interviewer:** *"Your latency-critical application shows occasional multi-millisecond latency spikes. You discover they correlate with safepoint operations. What are safepoints? What triggers them? How do you diagnose and mitigate safepoint-related pauses?"*

### Expected Answer (Staff Level)

**Safepoints — what they are and why they exist:**

```java
// A safepoint is a point where ALL threads have reached a safe state
// where the JVM can inspect or modify their stacks/registers.
//
// At a safepoint, threads either:
//  1. Are blocked (not executing)
//  2. Have reached a safepoint check in compiled code
//
// WHY NEEDED:
// - GC: need to know all roots (thread stacks, registers)
// - Deoptimization: invalidate JIT-compiled code (e.g., class loading changes)
// - Thread dump (jstack, jcmd)
// - Biased locking revocation
// - JIT code flushing
// - Debugging (breakpoints)

// How JIT-compiled code checks safepoint:
// 
// In interpreted code: every bytecode checks
// In JIT-compiled (C1/C2) code: the JIT inserts safepoint polls:
//
// On x86-64:
//   test %rax, [rip+global_safepoint_state_offset]
//   // OR
//   cmp [r15_thread+thread_local_poll_offset], 0
//
// These are VERY cheap (~1 cycle if not triggered) because:
// - Memory access is usually L1 cache hit
// - Only the flag word, not the entire state, is checked

// SAFEPOINT TRIGGERS (what sets the flag):
// 1. GC request: JVM sets global safepoint flag
// 2. Biased locking revoke (deprecated in Java 15+)
// 3. Class redefinition (HotSwap)
// 4. Thread dump (jstack -F)
// 5. JIT code cache flush
// 6. Debugger attach
// 7. G1 concurrent mark start (initial mark phase is STW at safepoint)
```

**Diagnosing safepoint pauses:**

```java
// JVM flags for safepoint diagnostics:
// -XX:+PrintGCApplicationStoppedTime     → Print all safepoint pauses
// -XX:+PrintSafepointStatistics           → Detailed safepoint info
// -XX:PrintSafepointStatisticsCount=1     → Print every safepoint
// -XX:+SafepointTimeout                   → Enable timeout detection
// -XX:SafepointTimeoutDelay=1000          → Warn if safepoint > 1 second

// Output example:
// vmop                    [threads: total initially_running wait_to_block]
// 3.336: G1CollectFull           [     117          15            15    ]  [2637 ms]
// 
// Interpreting: 
// - 117 total threads at safepoint
// - 15 were initially running (rest were blocked)
// - 15 had to wait to block → they reached safepoint check
// - 2637ms total pause! → PROBLEM!

// Why 15 threads took 2.6s to reach the safepoint?
// → SAFEPOINT DEADLOCK! (or one thread is in a long-running method
//   without safepoint polls)

// Common causes of slow safepoint:
// 1. Thread in JNI code (no safepoint checks!)
// 2. Thread in native memory allocation
// 3. Thread in sun.misc.Unsafe operations
// 4. Long counted loops that JIT didn't poll
// 5. Thread.sleep() with very long duration
```

**Mitigating safepoint-induced pauses:**

```java
// 1. IDENTIFY which thread is blocking the safepoint:
//    -XX:+PrintSafepointStatistics   → shows "delaying" thread
//    jcmd <pid> Thread.print          → thread dump during safepoint
//    -XX:SafepointSpinTimeout=200000  → reduce spin time

// 2. Fix counted loops (JIT can't poll in counted loops):
// BEFORE — no safepoint poll in tight counted loop:
public int spin() {
    int sum = 0;
    for (int i = 0; i < 1_000_000_000; i++) {  // ← C2 optimizes this
        sum += i;                                // no safepoint poll!
    }
    return sum;
}
// JIT C2 can transform this: loop is "counted" (known bounds)
// → C2 removes safepoint poll (safepoint per back-edge optimization)

// AFTER — force safepoint:
public int spinFixed() {
    int sum = 0;
    for (int i = 0; i < 1_000_000_000; i++) {
        if ((i & 0xFFFF) == 0) {  // Check every 65536 iterations
            Thread.onSpinWait();  // Hint: this is a spin loop
            // OR: even simpler — just ensure the loop has a side effect
        }
        sum += i;
    }
    return sum;
}

// 3. Use -XX:-UseCountedLoopSafepoints (safepoint poll every back-edge)
//    → Slower but more predictable

// 4. For GC safepoints specifically:
//    - Use ZGC or Shenandoah (very short safepoints)
//    - G1 safepoint for initial mark: tune -XX:ConcGCThreads

// 5. For JNI/native code:
//    - Ensure native code calls back to Java periodically
//    - Use -XX:+UseCriticalJNINatives for short critical natives

// 6. For biased locking (pre-Java 15):
//    - Use -XX:-UseBiasedLocking to disable (removed in Java 15+)

// 7. Most common in production: JIT compiler threads at safepoint
//    -XX:-UseBiasedLocking (if on Java <15)
//    -XX:+UnlockDiagnosticVMOptions -XX:+DebugNonSafepoints
//    → Shows safepoint locations in JIT-compiled code
```

**JIT Compilation tiers — the compilation pipeline:**

```java
// Java code execution has FIFTEEN levels (C1 + C2 + interpreted):
//
// Level 0: Interpreter (start here)
// Level 1: C1 (simple C1, no profiling)
// Level 2: C1 with limited profiling
// Level 3: C1 with full profiling  ← MOST code lives here initially
// Level 4: C2 (fully optimized)    ← Peak performance
//
// Tiered compilation flow:
//                     ┌──────────────┐
//                     │  Level 0     │
//                     │  Interpreter │
//                     └──────┬───────┘
//                            │
//                    method call count threshold
//                            │
//                            ▼
//                     ┌──────────────┐
//                     │  Level 3     │◄─┐
//                     │  C1 + prof. │  │ (if C2 queue is full)
//                     └──────┬───────┘  │
//                            │          │
//                    profiling count     │
//                      threshold        │
//                            │          │
//                            ▼          │
//                     ┌──────────────┐  │
//                     │  Level 4     │──┘
//                     │  C2          │
//                     └──────────────┘
//
// Transition triggers:
// - Method invocation count > CompileThreshold (default: 10,000)
//   → Tier 3 compilation
// - Method invocation count > C2 threshold (default: 17,500)
//   → Tier 4 compilation
// - Counter decay: counters halved every ~5s if not called

// Compilation in background threads:
// - C1 thread priority: 10 (max, but still background)
// - C2 thread priority: 10
// - Queues can overflow → -XX:CICompilerCount (default: 2 per core, capped at 16)

// JIT WARNING: warm-up time
// - Spring Boot app might take 10-30 minutes to fully warm up C2!
// - All paths eventually reach Level 4
// - Start/stop patterns (serverless) never benefit from C2
```

**Memory barriers — the hardware perspective:**

```java
// JVM inserts memory barriers according to JMM rules.
// On different architectures, barriers are implemented differently:

// x86-64 (Total Store Order — strongest memory model):
//   - Only StoreLoad needs a barrier (MFENCE or locked instruction)
//   - LoadLoad: NOT needed (x86 guarantees load order)
//   - LoadStore: NOT needed
//   - StoreStore: NOT needed (x86 guarantees store order, with store buffer forwarding)
//   
// ARMv8 (Weakly ordered):
//   - ALL four barriers are needed!
//   - LoadLoad: DMB ISH (data memory barrier)
//   - LoadStore: DMB ISH
//   - StoreLoad: DMB ISH
//   - StoreStore: DMB ISH
//   - These are SIGNIFICANTLY more expensive than on x86

// JVM barrier insertion (example: volatile write):
//
// volatile int v;
// v = 42;
//
// On x86-64:
//   mov [r10+12], 42     ← Normal store
//   mfence               ← StoreLoad barrier (prevent subsequent reads from being reordered)
//
// On ARMv8:
//   dmb ishst            ← StoreStore barrier (ensure prior stores visible)
//   str w9, [x10]        ← Normal store
//   dmb ish              ← Full barrier (StoreLoad + StoreStore + LoadStore)

// MEASURING barrier cost (JMH benchmark):
// @Benchmark
// public int noBarrier() {
//     return x;  // ~0.3ns
// }
// 
// @Benchmark
// public int volatileRead() {
//     return volatileX;  // ~0.5ns (on x86, volatile read = normal load)
// }
// 
// @Benchmark
// public void volatileWrite() {
//     volatileX = 42;  // ~5-10ns (MFENCE on x86)
// }
// 
// @Benchmark
// public void synchronizedWrite() {
//     synchronized(this) { x = 42; }  // ~20-50ns (uncontended)
// }
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Safepoint mechanics** | Explains poll instruction, global flag, thread-local flag |
| **Diagnosis** | Knows -XX:+PrintSafepointStatistics, can interpret output |
| **JIT tiers** | Explains the 5 compilation levels and why warm-up matters |
| **Architecture barriers** | Compares x86 vs ARM barrier costs, knows MFENCE vs DMB |

---

## Question 8: Spring Transactions — Propagation, Isolation, and Transaction Management

**Interviewer:** *"Design a transaction management strategy for a financial application that requires: (1) A REQUIRES_NEW transaction inside a parent transaction; (2) A read-only transaction for reporting; (3) Compensation logic for failed transactions. Explain how Spring's @Transactional works with AOP proxies, and how propagation levels are implemented."*

### Expected Answer (Staff Level)

**Transaction propagation — how it works internally:**

```java
// Spring's transaction management uses a ThreadLocal-based TransactionSynchronizationManager
// Each thread has:
//   - TransactionSynchronizationManager.getResourceMap() → bound resources
//   - TransactionSynchronizationManager.getSynchronizations() → callbacks

@Service
public class PaymentService {
    
    @Autowired
    private AuditService auditService;
    
    // PROPAGATION TYPES:
    // REQUIRED (default)  → join existing tx or create new
    // REQUIRES_NEW        → suspend existing, create new, resume afterward
    // NESTED              → savepoint within existing tx (JDBC savepoints)
    // MANDATORY           → must have existing tx (throw if none)
    // NEVER               → must NOT have tx (throw if exists)
    // SUPPORTS            → optional tx (doesn't matter)
    // NOT_SUPPORTED       → suspend existing tx
    
    @Transactional(propagation = Propagation.REQUIRED)
    public void processPayment(Order order) {
        // 1. Creates transaction (or joins existing)
        
        deductBalance(order);
        
        try {
            auditService.logPayment(order);  // REQUIRES_NEW → separate transaction!
        } catch (Exception e) {
            // Audit failed BUT payment is still committed
            log.warn("Audit failed, payment succeeded: {}", e.getMessage());
        }
        
        updateInventory(order);
        // Transaction commits here (if no exception)
    }
}

@Service
public class AuditService {
    
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void logPayment(Order order) {
        // SUSPENDS the parent transaction!
        // Creates a NEW, independent transaction
        // Commits independently
        // If this fails, parent transaction is NOT affected
        auditDao.insert(new AuditRecord(order));
    }
}
```

**Transaction suspension internals:**

```java
// What happens during REQUIRES_NEW:
// 
// Thread: processPayment() → opens TX1
//   → auditService.logPayment() → @Transactional(REQUIRES_NEW)
//
// Spring's TransactionInterceptor:
// 1. Check: existing transaction? YES (TX1)
// 2. Propagation: REQUIRES_NEW
// 3. SUSPEND TX1:
//    - Save TX1 state to SuspendedResourcesHolder
//    - Unbind connection from ThreadLocal
//    - If TX1 entity manager → close EntityManager (detach entities)
// 4. CREATE new TX2:
//    - Get new connection from datasource
//    - Set autoCommit=false
//    - Bind to ThreadLocal
// 5. Execute auditService.logPayment()  (runs in TX2)
// 6. COMMIT TX2:
//    - Connection.commit()
//    - Close resources
//    - Run PostCommit callbacks
// 7. RESUME TX1:
//    - Restore connection from SuspendedResourcesHolder
//    - Rebind to ThreadLocal
// 8. Back in processPayment(), continue in TX1
//
// COST: Suspension requires a DIFFERENT JDBC connection!
// If connection pool has max=10, and 10 threads are in REQUIRES_NEW,
// each holding a parent connection → DEADLOCK!

// PRODUCTION WARNING: 
// REQUIRES_NEW + connection pool exhaustion
// 
// Scenario: 10 threads each have TX1 (10 connections held)
// Each enters REQUIRES_NEW → needs 10 MORE connections
// Pool max = 10 → ALL BLOCK waiting for connection
// → DEADLOCK! Threads wait for a connection they'll never get
// 
// Fix: ensure pool is at least 2x max concurrent transactions
// Or avoid REQUIRES_NEW in hot paths
```

**Isolation levels and locking:**

```java
// ISOLATION LEVELS (from lowest to highest):
// DEFAULT           → database default (usually READ_COMMITTED)
// READ_UNCOMMITTED  → dirty reads, non-repeatable reads, phantom reads
// READ_COMMITTED    → no dirty reads (PostgreSQL default)
// REPEATABLE_READ   → no dirty/non-repeatable reads (MySQL default)
// SERIALIZABLE       → all anomalies prevented (worst performance)

// PHENOMENA:
// Dirty Read:           read uncommitted data from another transaction
// Non-repeatable Read:  same row, two reads, different values (row changed)
// Phantom Read:         same query, two reads, different rows (rows inserted/deleted)

// LOCKING IN Postgres:
// READ_COMMITTED:
//   SELECT: no lock (uses MVCC snapshot of committed data)
//   UPDATE/DELETE: row-level exclusive lock
//   INSERT: row-level exclusive lock
//   SELECT FOR UPDATE: row-level exclusive lock

// REPEATABLE_READ (Postgres):
//   SELECT: snapshot from first query (same snapshot for entire tx)
//   UPDATE/DELETE: row-level exclusive lock + serialization failure if conflict
//   SELECT FOR UPDATE: row-level exclusive lock

// SERIALIZABLE (Postgres):
//   All operations: predicate locking (serialization failure on conflicts)
//   1% - 10% of transactions may fail with:
//   "ERROR: could not serialize access due to read/write dependencies"
//   → Retry logic is REQUIRED

@Transactional(isolation = Isolation.REPEATABLE_READ)
public void transferMoney(Long fromId, Long toId, BigDecimal amount) {
    // Both accounts read at the SAME snapshot (REPEATABLE_READ)
    // But: Postgres REPEATABLE_READ can still fail with serialization error
    // on concurrent UPDATE
    
    Account from = accountRepo.findById(fromId).orElseThrow();
    Account to = accountRepo.findById(toId).orElseThrow();
    
    if (from.getBalance().compareTo(amount) < 0) {
        throw new InsufficientFundsException();
    }
    
    from.setBalance(from.getBalance().subtract(amount));
    to.setBalance(to.getBalance().add(amount));
    
    // If concurrent tx modified same rows → 
    // "ERROR: could not serialize access due to concurrent update"
    // → Spring wraps this in a CannotSerializeTransactionException
    // → RETRY the entire method!
}

// PESSIMISTIC LOCKING — explicit row locks:
@Lock(LockModeType.PESSIMISTIC_WRITE)  // SELECT ... FOR UPDATE
@Query("SELECT a FROM Account a WHERE a.id = :id")
Optional<Account> findByIdWithLock(@Param("id") Long id);

// OPTIMISTIC LOCKING — version column:
@Entity
public class Account {
    @Version
    private Long version;  // Incremented on every update
    // On conflict: OptimisticLockException → retry
}
```

**Transaction management patterns for financial apps:**

```java
@Service
public class FinancialTransactionService {
    
    // PATTERN 1: Choreography with compensation
    // Instead of distributed transactions, use local transactions + compensation
    
    @Transactional
    public void processWithdrawal(Long accountId, BigDecimal amount) {
        Account account = accountRepo.findByIdWithLock(accountId);
        account.setBalance(account.getBalance().subtract(amount));
        // Commit → balance is updated
    }
    
    // Separate transaction (no @Transactional → participates in caller's)
    @Transactional
    public void sendNotification(Long accountId, String message) {
        notificationRepo.save(new Notification(accountId, message));
    }
    
    // COMPENSATION — called when subsequent step fails
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void compensateWithdrawal(Long accountId, BigDecimal amount) {
        Account account = accountRepo.findByIdWithLock(accountId);
        account.setBalance(account.getBalance().add(amount));
        // Always succeeds in separate transaction
    }
    
    // Orchestrator
    public void fullProcess(Long accountId, BigDecimal amount) {
        try {
            processWithdrawal(accountId, amount);
            sendNotification(accountId, "Withdrawal: " + amount);
        } catch (Exception e) {
            // Compensation — runs in its own transaction
            compensateWithdrawal(accountId, amount);
            throw new TransactionFailedException("Process failed, compensated", e);
        }
    }
    
    // PATTERN 2: Transactional outbox (for reliable event publishing)
    @Transactional
    public void processWithOutbox(Long accountId, BigDecimal amount) {
        // 1. Perform business operation
        Account account = accountRepo.findByIdWithLock(accountId);
        account.setBalance(account.getBalance().subtract(amount));
        
        // 2. Write event to OUTBOX table (same transaction!)
        OutboxEvent event = new OutboxEvent();
        event.setAggregateType("Account");
        event.setAggregateId(accountId);
        event.setPayload(jsonMapper.writeValueAsString(
            new WithdrawalEvent(accountId, amount)));
        event.setStatus("PENDING");
        outboxRepo.save(event);
        // ← Both account AND outbox event commit atomically
    }
    
    // Outbox poller (in another service):
    @Scheduled(fixedDelay = 1000)
    @Transactional
    public void processOutbox() {
        List<OutboxEvent> pending = outboxRepo.findByStatus("PENDING");
        for (OutboxEvent event : pending) {
            try {
                messageBroker.send(event.getPayload());
                event.setStatus("SENT");
            } catch (Exception e) {
                event.setErrorCount(event.getErrorCount() + 1);
                if (event.getErrorCount() > 3) {
                    event.setStatus("DEAD_LETTER");
                }
            }
        }
    }
}
```

**Transaction evaluation criteria for staff-level:**

```java
// KEY KNOWLEDGE CHECKLIST:
// 
// ❓ What is the difference between @Transactional on a public vs private method?
//    → Private methods bypass the proxy → NO transaction!
//
// ❓ Does @Transactional work on self-invocation?
//    → No! Same proxy problem as AOP self-invocation
//
// ❓ What happens when a REQUIRED method calls a REQUIRES_NEW method?
//    → The parent transaction is SUSPENDED, requiring a NEW connection
//    → Connection pool must be sized accordingly
//
// ❓ How does TransactionSynchronizationManager work?
//    → ThreadLocal-based. Resources, synchronizations, current transaction name
//
// ❓ What's the difference between @Transactional(rollbackFor=Exception.class)
//    and default behavior?
//    → Default: rollback only for RuntimeException and Error (not checked exceptions!)
//    → rollbackFor=Exception.class → also rollback for checked exceptions
//
// ❓ How does readOnly=true optimization work?
//    → Hibernate: flush mode = MANUAL (no dirty checking)
//    → Hibernate: no need to snapshot loaded entities
//    → JDBC: some drivers optimize (e.g., PostgreSQL read-only connections)
//    → Spring: connection.setReadOnly(true) hint
//
// ❓ What is the "Open Session In View" anti-pattern?
//    → Hibernate session stays open for the entire HTTP request
//    → Lazy loading works in views, but:
//    → Connection held for entire request (pool exhaustion risk)
//    → Lazy loading exceptions become silent (N+1 hidden)
//    → Fix: spring.jpa.open-in-view=false (Spring Boot 2.0+ default was true!)
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Propagation internals** | Explains suspension, connection requirement, ThreadLocal management |
| **REQUIRES_NEW deadlock** | Identifies pool exhaustion scenario, proposes sizing strategy |
| **Compensation pattern** | Designs transaction outbox or saga pattern instead of distributed tx |
| **readOnly=true** | Explains Hibernate flush mode change, JDBC hint, snapshot skipping |

---

## Question 9: Java 8+ Streams & Lambdas — Parallelism and Performance

**Interviewer:** *"You have a Stream of 10M records that need filtering, transformation, and aggregation. Walk me through when to use parallelStream, how the Spliterator works, and what pitfalls exist. Then implement a custom Spliterator for a data source with backpressure."*

### Expected Answer (Staff Level)

**Stream pipeline internals:**

```java
// Stream operations are divided into:
// 1. Intermediate (lazy): filter, map, flatMap, distinct, sorted, peek, limit, skip
// 2. Terminal (eager): collect, forEach, reduce, count, anyMatch, allMatch, findFirst

// Pipeline structure:
// Stream.of(1, 2, 3, 4, 5)
//     .filter(x -> x % 2 == 0)      // ReferencePipeline.StatelessOp
//     .map(x -> x * x)               // ReferencePipeline.StatelessOp  
//     .sorted()                      // ReferencePipeline.StatefulOp
//     .collect(Collectors.toList())  // Terminal operation (evaluate)

// Internally, the pipeline is built as a linked list of stages:
// Head → FilterOp → MapOp → SortedOp → TerminalOp

// Execution:
// 1. Terminal operation triggers evaluation
// 2. The entire pipeline is FUSED into a single pass per element
// 3. Sink chain: each element flows through filter → map → sorted buffer
// 4. For stateful ops (sorted, distinct, limit): elements are buffered

// SOURCE SPLITERATION:
// The key to parallel execution is Spliterator splitting

// Spliterator<T> has four key methods:
//   boolean tryAdvance(Consumer<? super T> action)  // Process one element
//   Spliterator<T> trySplit()                        // Split into two
//   long estimateSize()                              // Remaining elements
//   int characteristics()                            // ORDERED, DISTINCT, SORTED, SIZED, etc.

// FORK/JOIN INTEGRATION:
// parallelStream() uses ForkJoinPool.commonPool()
// 
// Work-stealing: each thread processes its portion
// trySplit() divides the source until threshold reached
// Each split creates a subtask in ForkJoinPool
```

**Custom Spliterator with backpressure:**

```java
import java.util.Spliterator;
import java.util.Spliterators;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;

public class BackpressureSpliterator<T> extends Spliterators.AbstractSpliterator<T> {
    private final BlockingQueue<T> queue;
    private final AtomicBoolean done = new AtomicBoolean(false);
    private T nextItem;
    private boolean hasNext = false;
    
    public BackpressureSpliterator(BlockingQueue<T> queue) {
        super(Long.MAX_VALUE, Spliterator.CONCURRENT | Spliterator.NONNULL);
        this.queue = queue;
    }
    
    @Override
    public boolean tryAdvance(Consumer<? super T> action) {
        // If we have a buffered item, consume it
        if (hasNext) {
            action.accept(nextItem);
            hasNext = false;
            return true;
        }
        
        // Try to get next item with backpressure
        try {
            // poll() with timeout → backpressure!
            // If queue is empty, we block (slowing the producer)
            nextItem = queue.poll(100, TimeUnit.MILLISECONDS);
            
            if (nextItem != null) {
                action.accept(nextItem);
                return true;
            }
            
            // Timeout — check if producer is done
            return !done.get();  // False = no more items
            
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }
    
    public void signalDone() {
        done.set(true);
    }
    
    // Factory method
    public static <T> Stream<T> fromQueue(BlockingQueue<T> queue) {
        BackpressureSpliterator<T> spliterator = new BackpressureSpliterator<>(queue);
        return StreamSupport.stream(spliterator, false);  // Sequential for backpressure
    }
}

// Usage:
// BlockingQueue<Data> queue = new LinkedBlockingQueue<>(1000);
// Stream<Data> stream = BackpressureSpliterator.fromQueue(queue);
// stream
//     .filter(d -> d.isValid())
//     .map(d -> transform(d))
//     .forEach(d -> process(d));  // Backpressure applied!
```

**Parallel stream pitfalls:**

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: Shared mutable state — RACE CONDITIONS!
// ═══════════════════════════════════════════════════════════════
List<Integer> list = new ArrayList<>();  // NOT thread-safe!
IntStream.range(0, 10000)
    .parallel()
    .forEach(list::add);  // ← RACE! ArrayIndexOutOfBoundsException!
System.out.println(list.size());  // Not 10000!

// Fix: use thread-safe collector or ConcurrentLinkedQueue
List<Integer> safeList = IntStream.range(0, 10000)
    .parallel()
    .boxed()
    .collect(Collectors.toList());  // Thread-safe collection

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: Blocking in parallel streams — common pool exhaustion
// ═══════════════════════════════════════════════════════════════
IntStream.range(0, 100)
    .parallel()
    .forEach(i -> {
        httpClient.send(request);  // Blocks FJP common pool!
        // Other parallel operations that use common pool are ALSO blocked
    });

// FIX: use custom ForkJoinPool
ForkJoinPool customPool = new ForkJoinPool(10);
try {
    customPool.submit(() -> 
        IntStream.range(0, 100)
            .parallel()
            .forEach(i -> httpClient.send(request))
    ).get();
} finally {
    customPool.shutdown();
}

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: findFirst vs findAny in parallel
// ═══════════════════════════════════════════════════════════════
stream.parallel()
    .filter(expensive)
    .findFirst()  // ENFORCES ORDER → serial bottleneck (all threads must sync for order)
    // Much slower than:
    .findAny()    // NO order requirement → best performance in parallel

// ═══════════════════════════════════════════════════════════════
// PITFALL 4: Parallel is NOT always faster!
// ═══════════════════════════════════════════════════════════════
// Small streams: overhead of splitting + combining > parallel speedup
// println, synchronized, etc.: parallelism serialized
// I/O-bound: threads help, but need custom pool (pitfall 2)
// NQ model: N * Q > 10,000 where N = elements, Q = cost per element
//   - N=100, Q=1μs → 100μs total → NOT worth parallel
//   - N=10_000, Q=1ms → 10s total → YES, parallelize

// ═══════════════════════════════════════════════════════════════
// PITFALL 5: limit() with unordered source
// ═══════════════════════════════════════════════════════════════
stream.parallel()
    .filter(predicate)
    .limit(10)       // Has to track ENCOUNTERED elements across threads
    // Much better:
    .unordered()     // Relinquish ordering guarantee
    .filter(predicate)
    .limit(10)       // Any 10 elements, much faster parallel execution
```

**Custom Collector for parallel aggregation:**

```java
public class StatsCollector implements Collector<Double, StatsCollector.Accumulator, Stats> {
    
    static class Accumulator {
        long count = 0;
        double sum = 0;
        double min = Double.MAX_VALUE;
        double max = Double.MIN_VALUE;
        
        void add(double value) {
            count++;
            sum += value;
            if (value < min) min = value;
            if (value > max) max = value;
        }
        
        // Combiner for parallel execution
        Accumulator merge(Accumulator other) {
            count += other.count;
            sum += other.sum;
            if (other.min < min) min = other.min;
            if (other.max > max) max = other.max;
            return this;
        }
    }
    
    @Override
    public Supplier<Accumulator> supplier() {
        return Accumulator::new;
    }
    
    @Override
    public BiConsumer<Accumulator, Double> accumulator() {
        return Accumulator::add;
    }
    
    @Override
    public BinaryOperator<Accumulator> combiner() {
        return Accumulator::merge;  // Used for parallel!
    }
    
    @Override
    public Function<Accumulator, Stats> finisher() {
        return acc -> new Stats(acc.count, acc.sum, acc.min, acc.max);
    }
    
    @Override
    public Set<Characteristics> characteristics() {
        return Set.of(Characteristics.CONCURRENT, Characteristics.UNORDERED_IDENTITY_FINISH);
    }
}

// Usage:
// Stats stats = largeStream
//     .parallel()
//     .collect(new StatsCollector());
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pipeline fusion** | Explains how intermediate ops fuse into single pass, sink chain |
| **Spliterator** | Can implement a custom Spliterator with backpressure |
| **Parallel pitfalls** | Identifies shared state, common pool blocking, findFirst cost |
| **NQ model** | Uses N*Q > 10000 heuristic, explains when NOT to parallelize |

---

## Question 10: Class Loading & Bytecode — When Java Gets Its Hands Dirty

**Interviewer:** *"Design a custom ClassLoader that can load and modify classes at runtime for AOP weaving. Explain the delegation model, why it exists, and when you would break it. Then walk me through the bytecode of a simple `synchronized` method and the monitorenter/monitorexit instructions."*

### Expected Answer (Staff Level)

**The ClassLoader hierarchy and delegation model:**

```java
// BOOTSTRAP ClassLoader (native, C++ implementation)
//   └── Loads: rt.jar, java.lang.*, java.util.* (from $JAVA_HOME/lib)
//   └── Parent of all class loaders (null parent in Java code)
//
// EXTENSION ClassLoader (Java 8: ext class loader, Java 9+: platform class loader)
//   └── Loads: $JAVA_HOME/lib/ext/* (Java 8)
//   └── Loads: module system classes (Java 9+)
//
// APPLICATION ClassLoader (system class loader)
//   └── Loads: CLASSPATH, application classes
//   └── Default loader for: your Spring Boot JAR
//
// CUSTOM ClassLoader
//   └── Your implementation

// DELEGATION MODEL (parent-first):
// loadClass(name):
//   1. Check if already loaded (findLoadedClass)
//   2. Delegate to parent loader (parent.loadClass(name))
//   3. If parent fails → findClass(name) — load from custom source
//   4. If both fail → ClassNotFoundException
//
// WHY DELEGATION?
// - java.lang.Object must be the SAME class for ALL loaders
// - Prevents multiple class definitions from different loaders
// - Type safety: classes loaded by different loaders are DIFFERENT types
//   even if the same bytecode!
//
// WHEN TO BREAK DELEGATION?
// - Web servers (Tomcat): child-first for webapp isolation
//   → Check local first, THEN delegate
// - Hot reload: custom loader loads new version, old stays
// - Bytecode manipulation: load modified version before original
```

**Custom ClassLoader with bytecode transformation:**

```java
import java.io.*;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import javassist.*;

public class InstrumentingClassLoader extends ClassLoader {
    private final String basePath;
    private final boolean shouldInstrument;
    
    public InstrumentingClassLoader(String basePath, boolean instrument) {
        super(ClassLoader.getSystemClassLoader());  // Parent = app classloader
        this.basePath = basePath;
        this.shouldInstrument = instrument;
    }
    
    @Override
    protected Class<?> loadClass(String name, boolean resolve) 
            throws ClassNotFoundException {
        
        // Bootstrap classes: delegate to parent (CANNOT modify)
        if (name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("sun.")) {
            return super.loadClass(name, resolve);
        }
        
        // Application classes: load ourselves with possible instrumentation
        Class<?> clazz = findLoadedClass(name);
        if (clazz != null) return clazz;
        
        byte[] classBytes = loadClassBytes(name);
        if (classBytes == null) {
            return super.loadClass(name, resolve);  // Fall back to parent
        }
        
        if (shouldInstrument && shouldInstrument(name)) {
            classBytes = transformClass(name, classBytes);
        }
        
        // DEFINECLASS: defines the class in THIS loader's namespace
        clazz = defineClass(name, classBytes, 0, classBytes.length);
        if (resolve) {
            resolveClass(clazz);
        }
        return clazz;
    }
    
    private byte[] loadClassBytes(String className) {
        String path = className.replace('.', '/') + ".class";
        File classFile = new File(basePath, path);
        
        if (!classFile.exists()) return null;
        
        try (FileInputStream fis = new FileInputStream(classFile);
             ByteArrayOutputStream bos = new ByteArrayOutputStream()) {
            
            byte[] buffer = new byte[4096];
            int read;
            while ((read = fis.read(buffer)) != -1) {
                bos.write(buffer, 0, read);
            }
            return bos.toByteArray();
            
        } catch (IOException e) {
            return null;
        }
    }
    
    // Bytecode transformation using ASM or Javassist
    private byte[] transformClass(String className, byte[] originalBytes) {
        try {
            ClassPool pool = ClassPool.getDefault();
            CtClass cc = pool.makeClass(new ByteArrayInputStream(originalBytes));
            
            // Add timing to every method
            for (CtMethod method : cc.getDeclaredMethods()) {
                if (!method.isEmpty() && Modifier.isPublic(method.getModifiers())) {
                    method.addLocalVariable("__startTime", CtClass.longType);
                    method.insertBefore(
                        "__startTime = System.nanoTime();"
                    );
                    method.insertAfter(
                        "System.out.println(\"" + className + "." 
                        + method.getName() + " took \" + "
                        + "(System.nanoTime() - __startTime) / 1000 + \"μs\");"
                    );
                }
            }
            
            return cc.toBytecode();
            
        } catch (Exception e) {
            // If transformation fails, use original
            return originalBytes;
        }
    }
    
    private boolean shouldInstrument(String className) {
        return className.startsWith("com.myapp.service");
    }
}
```

**Java Agent — bytecode transformation at load time:**

```java
// Simpler alternative: use java.lang.instrument

public class TimingAgent {
    
    // JVM calls this premain before main()
    public static void premain(String args, Instrumentation inst) {
        System.out.println("Agent loaded with args: " + args);
        inst.addTransformer(new TimingTransformer(), true);
    }
    
    static class TimingTransformer implements ClassFileTransformer {
        @Override
        public byte[] transform(
                ClassLoader loader,
                String className,          // Internal name: com/example/MyClass
                Class<?> classBeingRedefined,
                ProtectionDomain protectionDomain,
                byte[] classfileBuffer) {
            
            if (className == null || !className.startsWith("com/myapp")) {
                return null;  // Skip — return null = no change
            }
            
            try {
                ClassPool pool = ClassPool.getDefault();
                CtClass cc = pool.makeClass(new ByteArrayInputStream(classfileBuffer));
                
                // Add timing to all public methods
                for (CtMethod method : cc.getDeclaredMethods()) {
                    if (!method.isEmpty() && Modifier.isPublic(method.getModifiers())) {
                        method.addLocalVariable("__elapsed", CtClass.longType);
                        method.insertBefore("__elapsed = System.nanoTime();");
                        method.insertAfter(
                            "System.out.println(\"" 
                            + className.replace('/', '.') 
                            + "." + method.getName() 
                            + " -> \" + (System.nanoTime() - __elapsed) / 1000 + \"μs\");"
                        );
                    }
                }
                
                return cc.toBytecode();
                
            } catch (Exception e) {
                e.printStackTrace();
                return null;  // Return unmodified bytecode
            }
        }
    }
}

// META-INF/MANIFEST.MF:
// Premain-Class: com.myapp.TimingAgent
// Can-Retransform-Classes: true
// Can-Redefine-Classes: true
//
// Run with: java -javaagent:timing.jar -jar myapp.jar
```

**Bytecode of a synchronized method:**

```java
// Java source:
public class SyncExample {
    public synchronized void syncMethod() {
        System.out.println("Hello");
    }
    
    public void syncBlock() {
        synchronized(this) {
            System.out.println("Hello");
        }
    }
}

// Bytecode of syncMethod():
// 
// public synchronized void syncMethod();
//   flags: ACC_PUBLIC, ACC_SYNCHRONIZED    ← Method-level flag!
//   Code:
//      0: getstatic     #7  // Field java/lang/System.out
//      3: ldc           #13 // String "Hello"
//      5: invokevirtual #15 // Method java/io/PrintStream.println
//      8: return
//
// NOTE: ACC_SYNCHRONIZED flag means JVM acquires the monitor
// on entry and releases it on exit (normal or exceptional).
// The JVM handles this automatically — no monitorenter/monitorexit.

// Bytecode of syncBlock():
//
// public void syncBlock();
//   Code:
//      0: aload_0                    // Load 'this'
//      1: dup                        // Duplicate for monitorexit
//      2: astore_1                   // Store 'this' in local 1
//      3: monitorenter               ← ENTER MONITOR
//      4: getstatic     #7           // System.out
//      7: ldc           #13          // "Hello"
//      9: invokevirtual #15          // println
//     12: aload_1                    // Load stored 'this'
//     13: monitorexit                ← EXIT MONITOR
//     14: goto          22           // Normal exit — jump to return
//     17: astore_2                   // ← EXCEPTION HANDLER
//     18: aload_1                    // Load stored 'this'
//     19: monitorexit                ← EXIT MONITOR (on exception!)
//     20: aload_2                    // Load exception
//     21: athrow                     // Re-throw
//     22: return
//   
//   Exception table:
//     from  to  target  type
//      4    14    17    any        ← Any exception between 4-14 → jump to 17
//
// KEY: The compiler generates a SECOND monitorexit in the exception handler!
// This ensures the lock is ALWAYS released, even if an exception occurs.
// Without this, a deadlock would result from any runtime exception.

// Note: In modern JVMs (Java 8+), the JIT can optimize away
// monitorenter/monitorexit if it proves the object is thread-local (lock elision)
// or merge adjacent synchronized blocks (lock coarsening).
```

**Bytecode of a simple lambda:**

```java
// Java source:
List<String> names = Arrays.asList("Alice", "Bob");
names.stream()
    .filter(name -> name.startsWith("A"))
    .collect(Collectors.toList());

// Lambda bytecode — becomes a synthetic method + invokedynamic:
// 
// Invokedynamic: the lambda is compiled to:
//   1. A synthetic private static method (the lambda body)
//   2. An invokedynamic call site that links to a LambdaMetafactory
//      which creates the functional interface implementation
//
// Bootstrap method:
//   boostrap = LambdaMetafactory.metafactory(
//       caller,               // Lookup
//       invokedName: "test",  // Method handle name (Predicate.test)
//       invokedType: (String) -> boolean,  // Sam method type
//       samMethodType: (Object) -> boolean,  // Erased type
//       implMethod: MyClass.lambda$main$0(String) boolean,  // Implementation
//       instantiatedMethodType: (String) -> boolean  // Instantiated type
//   )
//
// Generated synthetic method:
// private static boolean lambda$main$0(String name) {
//     return name.startsWith("A");
// }

// At runtime: LambdaMetafactory generates an inner class that
// implements Predicate and calls the synthetic method.
// The generated class implements the functional interface.

// WHY invokedynamic for lambdas?
// 1. No anonymous class loaded at compile time
// 2. LambdaMetafactory can choose the implementation strategy:
//    - Generate inner class (default)
//    - Method handle (no class generation)
//    - Inline (future optimization)
// 3. CAPTURE: if lambda captures no variables → singleton instance
//    If captures variables → new instance per creation (with captured fields)
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Delegation model** | Explains parent-first, why it exists, when to break it |
| **Bytecode of synchronized** | Can read monitorenter/monitorexit, explains exception handler exit |
| **Lambda metafactory** | Explains invokedynamic + LambdaMetafactory, capture mechanics |
| **defineClass** | Knows the defineClass call and class loader namespace isolation |

---

## Question 11: CompletableFuture — Async Programming Without External Libraries

**Interviewer:** *"Implement an async workflow that: (1) Fetches user profile; (2) Fetches user's recent orders; (3) Fetches product details for each order; (4) Aggregates all into a response. Handle timeouts, errors, and cancellations. Use only java.util.concurrent — no external libraries."*

### Expected Answer (Staff Level)

**CompletableFuture fundamentals:**

```java
import java.util.concurrent.*;
import java.util.function.*;

// CompletableFuture extends CompletionStage:
// - thenApply(Function)       → map (sync transformation)
// - thenAccept(Consumer)      → consume result
// - thenRun(Runnable)          → run after completion
// - thenCompose(Function)     → flatMap (async chaining)
// - thenCombine(CompletionStage, BiFunction) → zip two futures
// - allOf(CompletableFuture...) → wait for all
// - anyOf(CompletableFuture...) → wait for first

// Executor control — critical for production systems:
// thenApply(Function)         → runs in the completing thread (can be unpredictable!)
// thenApplyAsync(Function)    → runs in ForkJoinPool.commonPool()
// thenApplyAsync(Function, Executor) → runs in CUSTOM executor
```

**Production-ready async workflow:**

```java
@Service
public class OrderAggregationService {
    
    private final UserService userService;
    private final OrderService orderService;
    private final ProductService productService;
    private final ExecutorService executor;
    
    public OrderAggregationService(...) {
        // Dedicated executor for async operations
        // Separated from Tomcat's request threads!
        this.executor = Executors.newFixedThreadPool(
            Runtime.getRuntime().availableProcessors() * 2,
            new ThreadFactoryBuilder()
                .setNameFormat("async-worker-%d")
                .setDaemon(true)
                .build()
        );
    }
    
    public CompletableFuture<UserDashboard> buildDashboard(Long userId) {
        // Phase 1: Fetch user profile + orders in PARALLEL
        CompletableFuture<User> userFuture = CompletableFuture
            .supplyAsync(() -> userService.fetchUser(userId), executor)
            .orTimeout(2, TimeUnit.SECONDS)
            .exceptionally(ex -> {
                log.error("Failed to fetch user: {}", ex.getMessage());
                return User.DEFAULT;  // Fallback user
            });
        
        CompletableFuture<List<Order>> ordersFuture = CompletableFuture
            .supplyAsync(() -> orderService.fetchRecentOrders(userId), executor)
            .orTimeout(5, TimeUnit.SECONDS)
            .exceptionally(ex -> {
                log.error("Failed to fetch orders: {}", ex.getMessage());
                return List.of();  // Empty orders
            });
        
        // Phase 2: Combine user and orders, then fetch product details
        return userFuture.thenCombineAsync(ordersFuture, (user, orders) -> {
            // For each order, fetch product details (in parallel)
            List<CompletableFuture<OrderWithProducts>> orderDetailsFutures = 
                orders.stream()
                    .map(order -> fetchOrderDetails(order))
                    .toList();
            
            // Wait for ALL order details
            CompletableFuture<Void> allOrders = CompletableFuture
                .allOf(orderDetailsFutures.toArray(new CompletableFuture[0]));
            
            return allOrders.thenApply(v -> 
                orderDetailsFutures.stream()
                    .map(CompletableFuture::join)
                    .toList()
            ).thenApply(orderDetails -> new UserDashboard(user, orderDetails));
            
        }, executor)
        .orTimeout(10, TimeUnit.SECONDS)  // Overall timeout
        .exceptionally(ex -> {
            log.error("Dashboard build failed: {}", ex.getMessage());
            return UserDashboard.ERROR_DASHBOARD;
        })
        .thenApply(dashboard -> {
            log.info("Dashboard built for user {} with {} orders", 
                userId, dashboard.orders().size());
            return dashboard;
        });
    }
    
    private CompletableFuture<OrderWithProducts> fetchOrderDetails(Order order) {
        // Fetch ALL product details for this order in parallel
        List<CompletableFuture<Product>> productFutures = 
            order.productIds().stream()
                .map(productId -> CompletableFuture
                    .supplyAsync(() -> productService.fetchProduct(productId), executor)
                    .orTimeout(3, TimeUnit.SECONDS)
                    .exceptionally(ex -> null))  // Skip failed products
                .toList();
        
        return CompletableFuture
            .allOf(productFutures.toArray(new CompletableFuture[0]))
            .thenApply(v -> 
                productFutures.stream()
                    .map(CompletableFuture::join)
                    .filter(Objects::nonNull)
                    .toList()
            )
            .thenApply(products -> new OrderWithProducts(order, products));
    }
}

// RECORD TYPES:
record UserDashboard(User user, List<OrderWithProducts> orders) {
    static final UserDashboard ERROR_DASHBOARD = 
        new UserDashboard(User.DEFAULT, List.of());
}
record OrderWithProducts(Order order, List<Product> products) {}
```

**Advanced patterns — circuit breaker, retry, and rate limiting:**

```java
public class ResilientAsyncUtils {
    
    private final ScheduledExecutorService scheduler = 
        Executors.newScheduledThreadPool(2);
    
    // Retry with exponential backoff
    public <T> CompletableFuture<T> retryAsync(
            Supplier<T> supplier,
            int maxRetries,
            Executor executor) {
        
        CompletableFuture<T> future = CompletableFuture
            .supplyAsync(supplier, executor);
        
        return retry(future, supplier, maxRetries, 1, executor);
    }
    
    private <T> CompletableFuture<T> retry(
            CompletableFuture<T> future,
            Supplier<T> supplier,
            int remainingRetries,
            int attempt,
            Executor executor) {
        
        return future.exceptionally(ex -> {
            if (remainingRetries <= 0) {
                throw new CompletionException(ex);
            }
            
            long delay = Math.min(1000 * (1L << attempt), 30_000L);  // Exponential cap at 30s
            
            CompletableFuture<T> delayed = new CompletableFuture<>();
            scheduler.schedule(() -> {
                CompletableFuture<T> retryFuture = CompletableFuture
                    .supplyAsync(supplier, executor);
                retryFuture.whenComplete((result, error) -> {
                    if (error != null) {
                        retry(retryFuture, supplier, remainingRetries - 1, 
                              attempt + 1, executor)
                            .whenComplete((r, e) -> {
                                if (e != null) delayed.completeExceptionally(e);
                                else delayed.complete(r);
                            });
                    } else {
                        delayed.complete(result);
                    }
                });
            }, delay, TimeUnit.MILLISECONDS);
            
            return delayed.join();
        });
    }
    
    // Timeout with fallback
    public <T> CompletableFuture<T> withTimeout(
            CompletableFuture<T> future,
            long timeout,
            TimeUnit unit,
            T fallback) {
        
        CompletableFuture<T> result = new CompletableFuture<>();
        
        scheduler.schedule(() -> {
            if (!result.isDone()) {
                log.warn("Timeout, using fallback");
                result.complete(fallback);
            }
        }, timeout, unit);
        
        future.whenComplete((value, error) -> {
            if (error != null) {
                result.complete(fallback);
            } else {
                result.complete(value);
            }
        });
        
        return result;
    }
}
```

**CompletableFuture vs reactive streams (Project Reactor/RxJava):**

```java
// CompletableFuture:
// - Push-based (you pull results)
// - Single result (one value or error)
// - Lacks: backpressure, composition of streams, operators for 10+ operations
// - Simple: easy to understand, standard library
// - Good for: request-response, RPC calls, service orchestration
//
// Reactive Streams (Flux/Mono):
// - Pull-based (subscriber controls demand)
// - Multiple results (stream of values)
// - Complete operator catalog (buffer, window, throttle, retryWhen, etc.)
// - Complex: steep learning curve, debugging is hard
// - Good for: streaming data, event processing, high-throughput async

// WHEN TO USE WHICH:
// - Service composition with N futures: CompletableFuture
// - Streaming data (WebSocket, Kafka): Reactive
// - Single API response: CompletableFuture
// - Complex operator chains (10+): Reactive
// - Team expertise: prefer CompletableFuture for most teams
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|----------|----------------------|
| **Parallel composition** | Uses thenCombine, allOf, thenCompose correctly |
| **Error isolation** | Each step has its own timeout and fallback |
| **Executor control** | Uses dedicated executor, not common pool |
| **Retry with backoff** | Implements exponential backoff, timeout, circuit-breaking patterns |

---

## Question 12: Performance Tuning — Profiling, JMH, and Optimization

**Interviewer:** *"Your Spring Boot application serving 50K req/s has a 99th percentile latency of 500ms. Walk me through your performance investigation and optimization approach from end to end."*

### Expected Answer (Staff Level)

**Step 1: Define the problem and collect baseline data:**

```java
// 99th percentile = 500ms → 1% of requests take >500ms
// Throughput = 50K/s → 500 requests/sec are "slow"

// First: Isolate the bottleneck layer
// - Network (between client and server)?
// - Application server (Spring Boot)?
// - Database?
// - External API call?

// Tools:
// 1. Distributed tracing (Zipkin, Jaeger) → which span is slow?
// 2. Request logging with timing → which endpoints are affected?
// 3. CPU profiling → what is the CPU doing during slow requests?
// 4. GC logs → is GC causing pauses?
// 5. Database query analysis → slow queries?
```

**Step 2: JVM profiling — CPU:**

```java
// ── CPU profiling tools ───────────────────────────────

// 1. Async-profiler (async-profiler on Linux):
//    - Low overhead, safe for production
//    - Can profile Java + native + kernel stacks
//    - Flame graphs: which methods are using CPU?
//
//    ./profiler.sh -d 60 -f profile.html <pid>
//    ./profiler.sh -e cpu -d 60 -f cpu.html <pid>
//    ./profiler.sh -e alloc -d 60 -f alloc.html <pid>
//    ./profiler.sh -e lock -d 60 -f lock.html <pid>

// 2. JFR (Java Flight Recorder):
//    - Built into HotSpot JVM
//    - Low overhead (<1%), designed for production
//    - Records: method profiling, GC, I/O, locks, allocations
//
//    -XX:StartFlightRecording=duration=60s,filename=recording.jfr
//    jcmd <pid> JFR.start duration=60s filename=recording.jfr

// 3. jstack: Thread dumps
//    jstack <pid> > threads.txt
//    // Look for BLOCKED threads, WAITING threads, RUNNABLE threads
//    // "BLOCKED" on monitor → lock contention!

// EXAMPLE DIAGNOSIS:
// CPU flame graph shows 40% of CPU in string operations
// → Likely: excessive toString(), string concatenation, serialization
```

**Step 3: GC analysis:**

```java
// GC flags:
// -Xlog:gc*=info:file=gc.log:time,uptime,level,tags  (Java 9+)
// -XX:+PrintGCDetails -XX:+PrintGCDateStamps         (Java 8)

// Read GC log:
// [2024-01-15T10:30:00.123+0000] GC pause (G1 Evacuation Pause) 
//   young->initial-mark 1234M(4096M) -> 456M(4096M) 15.234ms
//
// What to look for:
// 1. Frequent young GCs: young gen too small (increase -XX:G1NewSizePercent)
// 2. Long mixed GC pauses: concurrent mark can't keep up (increase -XX:ConcGCThreads)
// 3. Full GC events: CONCURRENT MODE FAILURE! → heap is too small or IHOP too low
//   - Increase -XX:InitiatingHeapOccupancyPercent (default 45%)
//   - Or increase heap size
// 4. Allocation rate spikes: look at JFR or async-profiler allocation profile

// Common GC optimizations:
// -XX:MaxGCPauseMillis=200  → G1 adjusts to this target
// -XX:G1HeapRegionSize=4m   → Reduce region count for large heaps
// -XX:G1ReservePercent=15   → Reserved space for "full promotion"
// -XX:G1MixedGCLiveThresholdPercent=85 → Don't collect regions with >85% live
```

**Step 4: JMH microbenchmarks:**

```java
// JMH (Java Microbenchmark Harness) — for sub-millisecond optimization

import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.infra.Blackhole;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.Throughput)        // Operations per second
@OutputTimeUnit(TimeUnit.MILLISECONDS)  // Ops/ms
@State(Scope.Thread)                    // New instance per thread
@Fork(value = 2, warmups = 1)          // Number of JVM forks
@Warmup(iterations = 3, time = 1)       // Warmup iterations
@Measurement(iterations = 5, time = 1)  // Measurement iterations
public class StringBenchmark {
    
    private String data = "user_id:12345,amount:99.99,currency:USD";
    
    @Benchmark
    public int splitAndParse(Blackhole bh) {
        // PRE-OPTIMIZATION: ~50M ops/sec
        String[] parts = data.split(",");
        int sum = 0;
        for (String part : parts) {
            sum += part.length();
        }
        return sum;
    }
    
    @Benchmark
    public int charLoop(Blackhole bh) {
        // OPTIMIZED: ~120M ops/sec (2.4x faster)
        int sum = 0;
        int start = 0;
        for (int i = 0; i < data.length(); i++) {
            if (data.charAt(i) == ',') {
                sum += i - start;
                start = i + 1;
            }
        }
        sum += data.length() - start;
        return sum;
    }
    
    @Benchmark
    public String concatenation() {
        // PRE-OPTIMIZATION: ~30M ops/sec
        return "User: " + data + ", timestamp: " + System.currentTimeMillis();
    }
    
    @Benchmark
    public String stringBuilder(Blackhole bh) {
        // OPTIMIZED: ~45M ops/sec (1.5x faster)
        return new StringBuilder()
            .append("User: ")
            .append(data)
            .append(", timestamp: ")
            .append(System.currentTimeMillis())
            .toString();
    }
}

// JMH blackhole: prevents dead-code elimination
// Without Blackhole.consume(), the JIT can eliminate the entire benchmark!
```

**Step 5: Specific optimizations (ordered by impact):**

```java
// 1. Connection pooling (highest impact for 50K req/s)
// - Database: HikariCP (default, optimal)
// - HTTP client: connection pool sizing (default = 200 connections, often too low)
// - Redis: pool size matching concurrent operations

// 2. Caching (reduces downstream calls)
// - Spring @Cacheable with Caffeine (in-process)
// - Redis for distributed cache
// - Cache-aside pattern: TTL-based invalidation

// 3. JSON serialization (often a bottleneck at 50K req/s)
// - Jackson: enable afterburner module
// - Use protocol buffers or flatbuffers for internal services
// - Pre-serialize response templates

// 4. Database query optimization
// - N+1 detection: use Hibernate query plan cache
// - Connection pool: HikariCP (already configured by Spring Boot)
// - Index optimization: check slow query log

// 5. Thread pool tuning
// - Tomcat: server.tomcat.max-threads (default: 200)
// - Async executor: separate from Tomcat threads
// - Database: separate HikariCP pool for slow/reporting queries

// 6. GC tuning (covered in Question 2)

// 7. Application code hotspots
// - Reuse objects (avoid allocation in hot paths)
// - Use primitive collections (Eclipse Collections, fastutil)
// - Lazy initialization for expensive objects
// - Object pooling for expensive and frequently-used objects
```

**Step 6: Verification:**

```java
// After each change, re-measure:
// 1. P99 latency: should decrease (target: <100ms)
// 2. Throughput: should increase (target: >100K req/s per instance)
// 3. CPU usage: should decrease or be better utilized
// 4. GC pause time: should decrease
// 5. Error rate: should NOT increase

// NEVER optimize without measurement!
// "The First Rule of Program Optimization: Don't do it.
//  The Second Rule: Don't do it yet (for experts only)." — Michael A. Jackson

// PRODUCTION OBSERVABILITY SETUP:
// [Micrometer] → [Prometheus] → [Grafana]
// Key dashboards:
// 1. RED metrics: Rate (requests/s), Errors (error rate), Duration (latency)
// 2. JVM dashboard: heap usage, GC, threads, class loading
// 3. Database dashboard: connection pool, slow queries, active connections
// 4. Business dashboard: orders/min, users/min, revenue/min
```

### Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Systematic approach** | Starts with measurement, isolates layer, improves, re-measures |
| **Tool proficiency** | Knows async-profiler, JFR, jstack, JMH — not just theory |
| **GC log analysis** | Can interpret GC logs, identify bottlenecks (frequency vs pause time) |
| **JMH correctness** | Uses Blackhole, proper warmup, fork count, dead-code elimination awareness |

---

## 📊 Staff-Level Evaluation Rubric

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Cites JVM source code (HotSpot source, JVM specification), references JEP/JSR by number. Discusses trade-offs without prompting. Has shipped production workarounds for JVM bugs. |
| **4 — Strong** | Deep understanding of JMM, GC algorithms, Spring DI container internals. Can read bytecode, profile production apps, tune GC. Knows JVM flags by heart. |
| **3 — Competent** | Good Java developer. Knows streams, lambdas, CompletableFuture, Spring Boot. But doesn't understand JVM internals or memory model deeply. |
| **2 — Developing** | Proficient with Java syntax but doesn't understand why things work. No production experience at scale. |
| **1 — Needs Growth** | Can write basic Java but doesn't understand concurrency, memory management, or enterprise patterns. |

---

> *Built for experienced Java engineers targeting Staff/Principal roles at top-tier companies*
