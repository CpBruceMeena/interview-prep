# 📋 Detailed Task List — Staff Engineer Interview Simulation Transcript

> **Objective:** Generate an intense, production-grade technical interview transcript for a Staff Software Engineer position.
> **Format:** Raw dialogue using `[Principal Engineer]` and `[Staff Candidate]` tags.
> **Output file:** `staff_interview_simulation.md` (placed at project root)

---

## Phase 0: Research & Context Gathering

### Task 0.1 — Review Existing Content
- [ ] Review existing `INTERVIEW_QUESTIONS.md` files across the project (distributed-systems, concurrency, software-architecture) to understand depth, tone, and terminology used
- [ ] Review the existing `prompt.txt` to ensure no requirements are missed
- [ ] Note the specific technical depth expected: real engineering concepts (CAS, WAL, CQRS, Raft, LSM-trees, etc.)

### Task 0.2 — Scenario Selection
- [ ] Choose **one** specific complex scenario for Pillar 1 (Advanced System Design):
  - **Option A:** Globally distributed, low-latency financial ledger (strong consistency, cross-region replication, audit trails)
  - **Option B:** Real-time analytics aggregation engine processing 500k+ events/sec (high throughput, eventual consistency, partitioning)
  - *Decision: Select the scenario that enables the richest technical discussion*
- [ ] Choose **one** specific coding scenario for Pillar 2 (Advanced Coding Architecture):
  - **Option A:** Async multi-threaded task scheduler pipeline with priority queues and circuit breakers
  - **Option B:** Lock-free concurrent data structure (e.g., concurrent hashmap or work-stealing deque)
  - *Decision: Select the scenario that best demonstrates concurrency controls, SOLID principles, and resource management*

---

## Phase 1: Pillar 1 — Advanced System Design Transcript

### Task 1.1 — Architectural Deep-Dive (Opening)
- [ ] Write opening question from Principal Engineer — immediate heavy architectural question (no pleasantries)
- [ ] The question must specify specific numbers/scale (e.g., "Design a globally distributed financial ledger processing 50K transactions/sec across 3 regions with <100ms p99 write latency")
- [ ] Candidate's first response must demonstrate depth (architectural trade-offs, fallback flows, metric-driven reasoning)

### Task 1.2 — Consistency vs. Availability Drill-Down
- [ ] Principal Engineer pushes back on replication strategy
- [ ] Drill into: exact replication mechanics (sync vs async), RTO/RPO boundaries, handling network partitions across regions
- [ ] Candidate must counter with: CAP/PACELC analysis, concrete MySQL vs Cassandra vs Spanner examples, quorum math
- [ ] Must include: at least 2 rounds of back-and-forth where Principal Engineer interrupts/pushes back

### Task 1.3 — Data Modeling & Storage Drill-Down
- [ ] Principal Engineer challenges data model choices
- [ ] Drill into: relational DB indexing bottlenecks vs distributed NoSQL, custom caching topologies, hotspot keys (write/read skew)
- [ ] Candidate must counter with: LSM-tree compaction issues, Kafka partition strategies, hotspot mitigation
- [ ] Must include: concrete infrastructure examples, partitioning strategies, cache coherence discussion

### Task 1.4 — Failure Overload & Resiliency Drill-Down
- [ ] Principal Engineer introduces failure scenarios
- [ ] Drill into: degradation strategies, backpressure handling, cascading failures, retry storms
- [ ] Candidate must counter with: distributed rate limiter implementation (token bucket), circuit breaker patterns, bulkhead isolation
- [ ] Must include: exact implementation details of rate limiting, backpressure mechanics

---

## Phase 2: Pillar 2 — Advanced Coding Architecture Transcript

### Task 2.1 — Concurrency Controls Drill-Down
- [ ] Transition question from Principal Engineer into coding architecture
- [ ] Drill into: safe memory sharing, lock-free data structures, deadlock/race condition avoidance
- [ ] Candidate must explain: CAS operations, memory ordering, thread pool saturation optimization
- [ ] Must include: pseudo-implementation code, concrete concurrency patterns

### Task 2.2 — Design Abstractions (SOLID) Drill-Down
- [ ] Principal Engineer pushes on modularity and extensibility
- [ ] Drill into: Strategy, Factory, Dependency Inversion patterns for multi-tenant platforms
- [ ] Candidate must demonstrate: clean abstraction barriers, avoiding tight coupling, extensibility
- [ ] Must include: concrete pattern implementations, SOLID principle applications

### Task 2.3 — Resource Leakage & Profiling Drill-Down
- [ ] Principal Engineer challenges memory/performance characteristics
- [ ] Drill into: memory footprint optimization, object pooling, GC spike mitigation
- [ ] Candidate must address: structuring for high observability (tracing/metrics), profiling strategies
- [ ] Must include: concrete memory management strategies, monitoring approaches

---

## Phase 3: Transcript Assembly & Polish

### Task 3.1 — Structure Validation
- [ ] Ensure proper `[Principal Engineer]` and `[Staff Candidate]` tags throughout
- [ ] Ensure no introductory pleasantries or fluff
- [ ] Verify iterative drilling pattern (Principal Engineer pushes back at least 3-4 times)
- [ ] Verify concrete technical terminology is used throughout (CAS, WAL, CQRS, Raft, etc.)

### Task 3.2 — Technical Accuracy Review
- [ ] Verify all technical claims are accurate and production-realistic
- [ ] Verify code snippets/pseudo-code are correct
- [ ] Verify trade-off discussions are balanced and pragmatic

### Task 3.3 — Formatting & Final Polish
- [ ] Ensure consistent formatting, spacing, and readability
- [ ] Add section headers for the two pillars
- [ ] Add a brief preamble explaining the format
- [ ] Final read-through for quality

---

## Phase 4: Review & Validation

### Task 4.1 — Peer Review
- [ ] Read through the complete transcript for flow and coherence
- [ ] Verify the simulated candidate demonstrates Staff-level depth consistently
- [ ] Verify the Principal Engineer's questions escalate in difficulty with each iteration

### Task 4.2 — Final Delivery
- [ ] Confirm the file is saved as `staff_interview_simulation.md` at project root
- [ ] Provide a summary of what was generated

---

## Summary of Deliverables

| Deliverable | Format | Path |
|------------|--------|------|
| Staff Engineer Interview Simulation | Markdown | `staff_interview_simulation.md` |

**Total estimated sections:** ~8 deep technical exchanges across 2 pillars
**Estimated dialogue turns:** 16-24 turns (8-12 per pillar)
**Target depth:** Staff/Principal Engineer level — no surface-level answers
