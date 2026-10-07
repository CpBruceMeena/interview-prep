# ☕ Java — Staff-Level Interview Preparation

> **Comprehensive preparation for Staff/Principal Engineer Java interviews**
> *JVM internals, garbage collection, concurrency, Spring Boot, and production patterns*

---

## 📚 What's Inside

| Resource | Description |
|----------|-------------|
| [Interview Questions](INTERVIEW_QUESTIONS.md) | 13 staff-level Q&As, each with a 30-second answer, runnable code (verified on JDK 25), trade-offs and follow-up probes: JMM, G1/ZGC, locks, Spring internals, virtual threads, collections, safepoints/JIT, transactions, streams, class loading, CompletableFuture, performance tuning, and modern Java 17 → 25 |
| [JVM Internals & GC](JVM_INTERNALS_NOTES.md) | JVM architecture, class loading, runtime data areas, TLABs and escape analysis, GC (G1, generational ZGC, Shenandoah), memory model, JIT, bytecode, profiling tools |
| [Object Handling, References & Memory](OBJECT_HANDLING_MEMORY_NOTES.md) | Object layout and sizes (measured with JOL, incl. compact object headers), pass-by-value, reference types and Cleaner, strings and arrays, leak patterns, allocation, memory tuning and OOM types |
| [Spring Boot Deep-Dive](SPRING_BOOT_NOTES.md) | Spring Boot 4 / Framework 7 changes, DI container and bean lifecycle, auto-configuration, AOP proxies, transactions, JPA, Security 7, MVC, observability, testing, production pitfalls |

*Current as of October 2026: JDK 25 LTS / JDK 27, Spring Boot 4.x on Spring Framework 7.*

## 🎯 Target Audience

- Senior/Staff/Principal Engineers targeting top-tier companies (FAANG, fintech, trading systems)
- Experienced Java engineers (roughly 5+ years) looking to deepen internals knowledge
- Anyone preparing for heavy Java system design and concurrency interviews

## 📖 How to Use

1. **Interview Questions**: Study each question with the "Staff-Level Evaluation" criteria in mind
2. **JVM Internals**: Focus on GC algorithms and memory model — most frequently tested
3. **Spring Boot**: Understand the "why" behind auto-configuration and AOP proxy mechanics

---

> *Built for experienced Java engineers targeting Staff/Principal roles at top-tier companies*
