# 🎯 Interview Prep

> **Comprehensive interview preparation for Staff/Principal/Principal backend engineers**
> **18 LLD projects + 1 RAG module + 3 language/CS interview modules = 90+ staff-level questions**

---

## 🔍 Quick Search

Use the **search bar** above (<kbd>Ctrl</kbd>+<kbd>K</kbd> or <kbd>Cmd</kbd>+<kbd>K</kbd>) to find any question, topic, or concept across all modules.

**Popular searches:**
- [2PC vs Saga](?q=2PC+Saga)
- [Raft consensus](?q=Raft+consensus)
- [BBR congestion control](?q=BBR+TCP+BBR)
- [Merkle trees](?q=Merkle+tree)
- [JWT revocation](?q=JWT+revocation)
- [CQRS event sourcing](?q=CQRS+event+sourcing)
- [GIL internals](?q=GIL+Python)
- [GMP scheduler](?q=GMP+scheduler+Go)

!!! tip "Pro tip"
    Press `s` or `/` to focus the search bar from anywhere on the site.

---

## 📊 Repository Overview

| Module | Topics | Questions | Level |
|--------|--------|-----------|-------|
| [Low-Level Design](low-level-design/README.md) | 18 OOD projects with SOLID + Design Patterns | 18 INTERVIEW_QUESTIONS + 18 HLD | Senior/Staff |
| [RAG Learning](rag-learning/README.md) | RAG pipelines, LLM integration, vector search | 7 comprehensive guides | Staff |
| [Python](python-interview/README.md) | CPython internals, GIL, async, metaclasses, C extensions | 12 deep-dives | Staff |
| [Golang](golang-interview/README.md) | GMP scheduler, channels, GC, interfaces, sync primitives | 12 deep-dives | Staff |
| [Operating Systems](cs-interview/operating-systems/INTERVIEW_QUESTIONS.md) | Memory, scheduling, I/O, IPC, cgroups | 12 questions | Staff/Principal |
| [Computer Networks](cs-interview/computer-networks/INTERVIEW_QUESTIONS.md) | TCP, HTTP/2/3, QUIC, TLS, DNS, CDN | 12 questions | Staff/Principal |
| [Database Systems](cs-interview/database-systems/INTERVIEW_QUESTIONS.md) | B-Tree vs LSM, MVCC, replication, sharding | 14 questions | Staff/Principal |
| [Distributed Systems](cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md) | CAP, Raft, Paxos, CRDTs, PBFT, gossip | 12 questions | Staff/Principal |
| [Concurrency](cs-interview/concurrency-parallelism/INTERVIEW_QUESTIONS.md) | Lock-free, memory models, RCU, work-stealing | 10 questions | Staff/Principal |
| [Data Structures](cs-interview/data-structures-algorithms/INTERVIEW_QUESTIONS.md) | Bloom filters, HyperLogLog, consistent hashing | 10 questions | Staff/Principal |
| [Architecture](cs-interview/software-architecture/INTERVIEW_QUESTIONS.md) | CQRS, event sourcing, Kafka, service mesh, saga | 12 questions | Staff/Principal |
| [Security](cs-interview/security/INTERVIEW_QUESTIONS.md) | JWT, OAuth2, SQL injection, encryption, SSRF | 10 questions | Staff/Principal |

---

## 🖥️ Low-Level Design (18 Projects)

| # | Project | Domain | Key Patterns | HLD Focus |
|---|---------|--------|-------------|-----------|
| 1 | **[Parking Lot](low-level-design/parking-lot/INTERVIEW_QUESTIONS.md)** | OOD Basics | Strategy, Factory | IoT gate management, Redis allocation |
| 2 | **[Chess Game](low-level-design/chess-game/INTERVIEW_QUESTIONS.md)** | Game State | Factory, State, Memento | Bitboard engine, Stockfish AI |
| 3 | **[Tic-Tac-Toe](low-level-design/tic-tac-toe/INTERVIEW_QUESTIONS.md)** | Game AI | Strategy, State | MCTS AI, server-authoritative |
| 4 | **[Snakes & Ladders](low-level-design/snakes-and-ladders/INTERVIEW_QUESTIONS.md)** | Board Game | Strategy, Observer | Seeded PRNG, real-time |
| 5 | **[Vending Machine](low-level-design/vending-machine/INTERVIEW_QUESTIONS.md)** | State Machine | State, Strategy | IoT telemetry, offline queue |
| 6 | **[LRU/LFU/TTL Cache](low-level-design/lru-cache/INTERVIEW_QUESTIONS.md)** | Data Structures | Strategy, Decorator | Consistent hashing, avalanche prevention |
| 7 | **[Rate Limiter](low-level-design/rate-limiter/INTERVIEW_QUESTIONS.md)** | API Gateway | Strategy, Factory | Redis Lua scripting, multi-algorithm |
| 8 | **[Pub-Sub System](low-level-design/pub-sub-system/INTERVIEW_QUESTIONS.md)** | Messaging | Observer, Strategy | Kafka append-log, ISR replication |
| 9 | **[Movie Ticket Booking](low-level-design/movie-ticket-booking/INTERVIEW_QUESTIONS.md)** | Concurrency | Strategy, Singleton | CQRS, flash sales, thundering herd |
| 10 | **[Splitwise](low-level-design/splitwise-expense-sharing/INTERVIEW_QUESTIONS.md)** | Graphs | Strategy, Factory | Debt graph, min-transactions |
| 11 | **[Cab Booking (Uber)](low-level-design/cab-booking-uber/INTERVIEW_QUESTIONS.md)** | Real-time | Strategy, State | Redis GEO, Kalman filtering |
| 12 | **[Library Management](low-level-design/library-management/INTERVIEW_QUESTIONS.md)** | Catalog | Strategy, Observer | Elasticsearch, FCFS queue |
| 13 | **[Car Rental](low-level-design/car-rental-platform/INTERVIEW_QUESTIONS.md)** | Fleet | Strategy, State | Exclusion constraints, scoring |
| 14 | **[ATM/Banking](low-level-design/atm-banking-system/INTERVIEW_QUESTIONS.md)** | Security | State, Chain | HSM PIN, PCI DSS compliance |
| 15 | **[Inventory Management](low-level-design/inventory-management/INTERVIEW_QUESTIONS.md)** | Stock | Strategy, Observer | EOQ, optimistic locking |
| 16 | **[Payment Processing](low-level-design/payment-processing-system/INTERVIEW_QUESTIONS.md)** | Payments | Strategy, Chain | Idempotency, circuit breaker |
| 17 | **[Job Scheduling](low-level-design/job-scheduling-system/INTERVIEW_QUESTIONS.md)** | Scheduling | Command, Strategy | DAG scheduling, Redis lease |
| 18 | **[Search Platform](low-level-design/search-platform/INTERVIEW_QUESTIONS.md)** | Indexing | Strategy, Facade | BM25 ranking, autocomplete |

---

## 🧠 RAG Learning Module

| Document | Key Topics |
|----------|-----------|
| [RAG Fundamentals](rag-learning/01_RAG_FUNDAMENTALS.md) | Pipeline architecture, Naive/Advanced/Modular RAG |
| [LM Studio Integration](rag-learning/02_LM_STUDIO_INTEGRATION.md) | Gemma 4B, quantization, GPU acceleration |
| [Fine-Tuning Guide](rag-learning/03_FINE_TUNING.md) | Contrastive learning, cross-encoder reranking, QLoRA |
| [Interview Questions](rag-learning/04_INTERVIEW_QUESTIONS.md) | 8 deep-dive RAG Q&A |
| [Code Base Design](rag-learning/05_CODE_BASE_DESIGN.md) | SOLID, Strategy pattern, error handling |
| [Low-Level Design](rag-learning/06_LOW_LEVEL_DESIGN.md) | Class diagrams, sequence diagrams, API contracts |
| [High-Level Design](rag-learning/07_HIGH_LEVEL_DESIGN.md) | Caching, CQRS, scaling to 10M queries/day |

---

## 🐍 Python Deep-Dive

12 staff-level questions covering [CPython internals](python-interview/INTERVIEW_QUESTIONS.md):

| # | Topic |
|---|-------|
| 1 | GIL Internals (tick mechanism, 5ms switch) |
| 2 | Async/Await Event Loop (3-phase loop, `__await__` protocol) |
| 3 | Metaclasses & Descriptors (Django-style ORM) |
| 4 | Memory Management (arena allocator, cyclic GC) |
| 5 | Type System (covariance, Protocol, Generic) |
| 6 | C Extensions (PyObject, reference counting) |
| 7 | Import System (MetaPathFinder) |
| 8 | Context Managers & Generators |
| 9 | Async Generators & Streaming Pipelines |
| 10 | Packaging & manylinux Wheels |
| 11 | Subinterpreters & Free-Threaded Python |
| 12 | DI Framework with Auto-Wiring |

---

## 🐹 Golang Deep-Dive

12 staff-level questions covering [Go runtime internals](golang-interview/INTERVIEW_QUESTIONS.md):

| # | Topic |
|---|-------|
| 1 | GMP Scheduler (work stealing, signal-based preemption) |
| 2 | Channel Internals (hchan, sudog, direct send) |
| 3 | Interface Satisfaction (itab/iface/eface) |
| 4 | Memory Model (happens-before, atomic.Pointer) |
| 5 | GC (tri-color marking, write barrier, GOGC) |
| 6 | sync Package (Map, Pool, Once, Cond) |
| 7 | Context (Done channel, cancellation) |
| 8 | Error Handling (domain errors, gRPC mapping) |
| 9 | io.Reader/Writer (composition pipeline) |
| 10 | reflect (struct tags, code gen) |
| 11 | Testing (mocking, testcontainers, fuzz) |
| 12 | Production Service (graceful shutdown) |

---

## 🖥️ Computer Science Core

| Topic | Questions | Highlights |
|-------|-----------|------------|
| [Operating Systems](cs-interview/operating-systems/INTERVIEW_QUESTIONS.md) | 12 | Page tables, TLB, CFS, epoll vs io_uring, malloc, cgroups, OOM killer |
| [Computer Networks](cs-interview/computer-networks/INTERVIEW_QUESTIONS.md) | 12 | BBR vs Cubic, HTTP/2 HoL, QUIC 0-RTT, TLS 1.3, DNS anycast |
| [Database Systems](cs-interview/database-systems/INTERVIEW_QUESTIONS.md) | 14 | B-Tree vs LSM, MVCC, query optimization (30s→125ms), sharding |
| [Distributed Systems](cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md) | 12 | CAP+PACELC, Raft, Paxos, 2PC vs Saga, CRDTs, PBFT |
| [Concurrency](cs-interview/concurrency-parallelism/INTERVIEW_QUESTIONS.md) | 10 | Lock-free (ABA, hazard pointers), memory models, RCU, futex |
| [Data Structures](cs-interview/data-structures-algorithms/INTERVIEW_QUESTIONS.md) | 10 | Bloom filter math, HyperLogLog, Merkle trees, consistent hashing |
| [Architecture](cs-interview/software-architecture/INTERVIEW_QUESTIONS.md) | 12 | DDD, CQRS, Kafka, service mesh, saga orchestration, strangler fig |
| [Security](cs-interview/security/INTERVIEW_QUESTIONS.md) | 10 | JWT revocation, OAuth2 PKCE, SQL injection, envelope encryption |

---

## 🚀 How to Use This Site

| Goal | Action |
|------|--------|
| **Find a specific topic** | Use the search bar above or browse the navigation tabs |
| **Study a module** | Start with the Overview page, then dive into questions |
| **Prepare for an interview** | Follow the [roadmap in the README](https://github.com/CpBruceMeena/interview-prep#-interview-preparation-strategy) |
| **Read code examples** | All questions include production-grade code samples |
| **Check evaluation criteria** | Each question ends with a Staff-Level Evaluation rubric table |

---

## 🛠️ Technology Stack

| Area | Technology |
|------|-----------|
| **Languages** | Python 3.14+, Go |
| **Design Patterns** | Strategy, Factory, Observer, State, Command, Decorator, Facade, Chain, Singleton |
| **RAG** | SentenceTransformers, ChromaDB, LangChain, FastAPI |
| **LLM** | Gemma 4B via LM Studio (OpenAI-compatible API) |
| **Site** | [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) |

---

> *Built with ❤️ for backend engineers preparing for Senior/Staff/Principal-level interviews*
