# 🎯 Interview Prep — System Design, Low-Level Design & CS Mastery

> **A curated collection of 18 Low-Level Design (LLD) projects + 1 complete RAG Learning module + 3 language/CS interview modules**  
> *Designed for 6+ year experienced backend engineers preparing for Senior/Staff/Principal-level interviews*

---

## 📋 Project Overview

```
interview-prep/
├── low-level-design/        ← 18 LLD projects (Python, SOLID, Design Patterns)
│   ├── parking-lot/
│   ├── chess-game/
│   ├── tic-tac-toe/
│   ├── snakes-and-ladders/
│   ├── vending-machine/
│   ├── lru-cache/
│   ├── rate-limiter/
│   ├── pub-sub-system/
│   ├── movie-ticket-booking/
│   ├── splitwise-expense-sharing/
│   ├── cab-booking-uber/
│   ├── library-management/
│   ├── car-rental-platform/
│   ├── atm-banking-system/
│   ├── inventory-management/
│   ├── payment-processing-system/
│   ├── job-scheduling-system/
│   └── search-platform/
│
├── rag-learning/            ← 1 Complete RAG Application Learning Resource
│   ├── 01_RAG_FUNDAMENTALS.md
│   ├── 02_LM_STUDIO_INTEGRATION.md
│   ├── 03_FINE_TUNING.md
│   ├── 04_INTERVIEW_QUESTIONS.md
│   ├── 05_CODE_BASE_DESIGN.md
│   ├── 06_LOW_LEVEL_DESIGN.md
│   ├── 07_HIGH_LEVEL_DESIGN.md
│   └── implementation/      ← Working Python RAG chatbot
│
├── python-interview/        ← Staff-level Python interview questions (12 deep-dive topics)
│
├── golang-interview/        ← Staff-level Golang interview questions (12 deep-dive topics)
│
├── cs-interview/            ← 8 CS core topics for Staff/Principal engineers
│   ├── operating-systems/
│   ├── computer-networks/
│   ├── database-systems/
│   ├── distributed-systems/
│   ├── concurrency-parallelism/
│   ├── data-structures-algorithms/
│   ├── software-architecture/
│   └── security/
│
├── pyproject.toml
└── README.md                ← You are here
```

---

## 🔥 18 Low-Level Design Projects

Each project contains:
- **Python implementation** — Clean, SOLID-compliant, production-quality code with demo/example runs
- **`INTERVIEW_QUESTIONS.md`** — Principal Engineer-level Q&A covering architecture, trade-offs, and edge cases
- **`HIGH_LEVEL_DESIGN.md`** — Full system architecture with diagrams, component breakdown, data models, cost analysis, and scalability planning

| # | Project | Domain | Key Design Patterns | HLD Focus |
|---|---------|--------|-------------------|-----------|
| 1 | **[Parking Lot](low-level-design/parking-lot/)** | OOD Basics | Strategy, Factory, Singleton | IoT gate management, Redis spot allocation, offline fallback |
| 2 | **[Chess Game](low-level-design/chess-game/)** | Game State | Factory, State, Memento | Bitboard engine, WebSocket real-time, Stockfish AI integration |
| 3 | **[Tic-Tac-Toe](low-level-design/tic-tac-toe/)** | Game AI | Strategy, State, Command | Server-authoritative, MCTS AI, N×N board scaling |
| 4 | **[Snakes & Ladders](low-level-design/snakes-and-ladders/)** | Board Game | Strategy, Observer, State | Real-time multiplayer, seeded PRNG fairness |
| 5 | **[Vending Machine](low-level-design/vending-machine/)** | State Machine | State, Strategy, Factory | IoT/4G telemetry, offline queue, OR-Tools route optimization |
| 6 | **[LRU/LFU/TTL Cache](low-level-design/lru-cache/)** | Data Structures | Strategy, Decorator | Consistent hashing, 3-tier caching, avalanche prevention |
| 7 | **[Rate Limiter](low-level-design/rate-limiter/)** | API Gateway | Strategy, Factory, Decorator | L1 local + L2 Redis, Lua scripting, multi-algorithm comparison |
| 8 | **[Pub-Sub System](low-level-design/pub-sub-system/)** | Messaging | Observer, Strategy, Decorator | Kafka-style append-log, ISR replication, exactly-once semantics |
| 9 | **[Movie Ticket Booking](low-level-design/movie-ticket-booking/)** | Concurrency | Strategy, Singleton, Observer | CQRS, queue-based flash sales, thundering herd protection |
| 10 | **[Splitwise (Expense Sharing)](low-level-design/splitwise-expense-sharing/)** | Graphs | Strategy, Factory | Debt graph, greedy min-transactions, rounding accuracy |
| 11 | **[Cab Booking (Uber)](low-level-design/cab-booking-uber/)** | Real-time Matching | Strategy, State, Observer | Redis GEO, surge pricing zones, Kalman GPS filtering |
| 12 | **[Library Management](low-level-design/library-management/)** | Catalog | Strategy, Observer, Facade | Elasticsearch fuzzy search, FCFS reservation queue |
| 13 | **[Car Rental Platform](low-level-design/car-rental-platform/)** | Fleet | Strategy, State, Decorator | PostgreSQL exclusion constraints, multi-factor warehouse scoring |
| 14 | **[ATM/Banking System](low-level-design/atm-banking-system/)** | Security | State, Strategy, Chain of Responsibility | HSM PIN security, two-phase dispense, PCI DSS compliance |
| 15 | **[Inventory Management](low-level-design/inventory-management/)** | Stock | Strategy, Observer, Facade | EOQ + safety stock, optimistic locking, FIFO costing |
| 16 | **[Payment Processing](low-level-design/payment-processing-system/)** | Payments | Strategy, Chain of Responsibility | Idempotency keys, circuit breaker, fraud ML pipeline |
| 17 | **[Job Scheduling](low-level-design/job-scheduling-system/)** | Scheduling | Command, Strategy, Observer | DAG scheduling, Redis lease mechanism, cron DST handling |
| 18 | **[Search Platform](low-level-design/search-platform/)** | Indexing | Strategy, Facade, Decorator | BM25 ranking, edge-gram autocomplete, Levenshtein spell correction |

### 🎯 SOLID Principles Applied

| Principle | How It's Applied |
|-----------|-----------------|
| **S**ingle Responsibility | Each class has one clear purpose (e.g., `FeeCalculator` doesn't manage parking spots) |
| **O**pen/Closed | New strategies (pricing, eviction, payment) added without modifying existing code |
| **L**iskov Substitution | All strategy implementations are interchangeable without breaking contracts |
| **I**nterface Segregation | Small, focused abstract base classes (e.g., `PaymentStrategy`, `CacheEvictionPolicy`) |
| **D**ependency Inversion | High-level modules depend on abstractions, not concrete implementations |

### 🧩 Design Pattern Inventory

| Pattern | Used In | Purpose |
|---------|---------|---------|
| **Strategy** | 18/18 projects | Algorithm interchangeability (pricing, search, eviction, payments) |
| **Factory** | 10/18 projects | Object creation (vehicles, game pieces, players) |
| **Observer** | 8/18 projects | Event notifications (display updates, alerts, state changes) |
| **State** | 6/18 projects | State-dependent behavior (Vending Machine, ATM, Game states) |
| **Facade** | 5/18 projects | Unified service interfaces |
| **Decorator** | 5/18 projects | Behavior extension without subclassing |
| **Command** | 3/18 projects | Task encapsulation (job scheduling, undo/redo) |
| **Chain of Responsibility** | 3/18 projects | Validation pipelines (payments, ATM security) |
| **Singleton** | 4/18 projects | Shared state management (broker, cache manager) |

---

## 🧠 RAG Learning Module

A **complete, production-ready** RAG (Retrieval-Augmented Generation) application learning resource, built around a working Python chatbot implementation.

### 📚 Documentation

| # | Document | Content | Key Topics |
|---|----------|---------|------------|
| 1 | **[RAG Fundamentals](rag-learning/01_RAG_FUNDAMENTALS.md)** | Core concepts | Pipeline architecture, component breakdown, RAG patterns (Naive/Advanced/Modular) |
| 2 | **[LM Studio Integration](rag-learning/02_LM_STUDIO_INTEGRATION.md)** | Local LLM setup | Gemma 4B configuration, API client, quantization, GPU acceleration |
| 3 | **[Fine-Tuning Guide](rag-learning/03_FINE_TUNING.md)** | Advanced customization | Embedding contrastive learning, cross-encoder reranking, QLoRA |
| 4 | **[Interview Questions](rag-learning/04_INTERVIEW_QUESTIONS.md)** | Principal Engineer Q&A | 8 deep-dive questions on RAG architecture, retrieval, hallucination, scaling |
| 5 | **[Code Base Design](rag-learning/05_CODE_BASE_DESIGN.md)** | Architecture decisions | SOLID implementation, design patterns (Strategy, Facade, Adapter), error handling |
| 6 | **[Low-Level Design](rag-learning/06_LOW_LEVEL_DESIGN.md)** | Implementation details | Class diagrams, sequence diagrams, data models, API contracts |
| 7 | **[High-Level Design](rag-learning/07_HIGH_LEVEL_DESIGN.md)** | Production architecture | Component breakdown, caching, CQRS, cost analysis, scaling to 10M queries/day |

### 💻 Running Implementation

The `rag-learning/implementation/` directory contains a **working RAG chatbot** with:

| File | Component | Purpose |
|------|-----------|---------|
| `config.py` | Configuration | Pydantic settings for all components |
| `document_loader.py` | Ingestion | PDF/HTML/TXT/MD loaders with Strategy pattern |
| `embedding_service.py` | Embeddings | SentenceTransformer + OpenAI (abstract interface) |
| `vector_store.py` | Storage | ChromaDB-backed vector store with cosine search |
| `retrieval_engine.py` | Retrieval | Query → embed → search → filter → rank pipeline |
| `llm_service.py` | Generation | LM Studio client + OpenAI-compatible + Mock |
| `rag_pipeline.py` | Orchestrator | Facade pattern coordinating all RAG components |
| `chatbot_api.py` | API Server | FastAPI with `/api/query` and `/api/index` endpoints |
| `main.py` | CLI | Interactive chat, single query, server, indexing modes |

```bash
cd rag-learning/implementation
pip install -r requirements.txt

# Index sample documents
python main.py --index --docs ../data/documents

# Start interactive chat (requires LM Studio with Gemma 4B)
python main.py --interactive

# Or start the FastAPI server
python main.py --serve
```

---

## 🧪 Language & CS Interview Modules

### 🐍 Python Deep-Dive (`python-interview/`)

12 staff-level interview questions covering CPython internals:

| # | Topic | Key Concepts |
|---|-------|-------------|
| 1 | **GIL Internals** | Tick mechanism, 5ms switch interval, subinterpreters, free-threaded Python 3.13 |
| 2 | **Async/Await** | Event loop phases, `__await__` protocol, TaskGroup, uvloop |
| 3 | **Metaclasses & Descriptors** | `__set_name__`, `__init_subclass__`, Django-style ORM design |
| 4 | **Memory Management** | Arena allocator, cyclic GC, `__slots__`, memory leak patterns |
| 5 | **Type System** | Covariance/contravariance, Generic, Protocol structural typing |
| 6 | **C Extensions** | PyObject layout, reference counting, PyPy vs CPython ABI |
| 7 | **Import System** | MetaPathFinder, PathFinder, circular import resolution |
| 8 | **Context Managers** | `yield from`, coroutine foundation, async context managers |
| 9 | **Async Generators** | Streaming pipelines, `aclose()`, cleanup guarantees |
| 10 | **Packaging** | manylinux wheels, auditwheel, py_limited_api, cibuildwheel |
| 11 | **Subinterpreters** | Isolation model, `interpreters` module, per-interpreter GIL |
| 12 | **DI Framework Design** | Auto-wiring, `inspect.signature`, `__init_subclass__`-based |

### 🐹 Golang Deep-Dive (`golang-interview/`)

12 staff-level interview questions covering Go runtime internals:

| # | Topic | Key Concepts |
|---|-------|-------------|
| 1 | **GMP Scheduler** | Work stealing, syscall handler unbinding, signal-based preemption |
| 2 | **Channel Internals** | hchan struct, sudog, direct send optimization, goroutine parking |
| 3 | **Interface Satisfaction** | itab/iface/eface layout, nil interface trap, structural typing |
| 4 | **Memory Model** | Happens-before, `atomic.Pointer`, sharded counters, false sharing |
| 5 | **GC** | Tri-color marking, write barrier, GC trigger formula, GOMEMLIMIT |
| 6 | **sync Package** | `sync.Map` read/dirty mechanism, `Pool`, `Once`, `Cond` |
| 7 | **Context** | Custom Done channel, safe value propagation, cancellation patterns |
| 8 | **Error Handling** | Domain errors, `errors.Is`/`As`, gRPC error mapping, PII safety |
| 9 | **io.Reader/Writer** | Composition pipeline with encryption + compression, peek vs read |
| 10 | **reflect** | Struct tag validation, code generation vs reflection trade-offs |
| 11 | **Testing** | Interface-based mocking, testcontainers, fuzz testing, gotestsum |
| 12 | **Production Service** | Graceful shutdown, middleware chain, structured logging, health checks |

### 🖥️ Computer Science Core (`cs-interview/`)

8 deep-dive CS topics for Staff/Principal Engineer interviews:

| # | Topic | Key Questions | Depth |
|---|-------|--------------|-------|
| 1 | **Operating Systems** | Virtual memory (4-level page tables), TLB & huge pages, CFS scheduler, context switch cost, epoll vs io_uring, malloc internals, page cache, ext4 vs xfs vs btrfs, IPC (shared memory for HFT), signals & EINTR, cgroups v2, OOM killer | ~12 questions |
| 2 | **Computer Networks** | TCP congestion control (BBR vs Cubic), HTTP/2 HoL blocking, QUIC handshake & 0-RTT, TLS 1.3 optimization, DNS deep dive (anycast, health checks), L4 vs L7 load balancing, connection pooling, gRPC vs REST wire format, CDN caching strategies, TIME_WAIT exhaustion | ~12 questions |
| 3 | **Database Systems** | B-Tree vs LSM-Tree (financial ledger vs time-series), MVCC (PG vs InnoDB), transaction isolation & anomalies, query optimization (30s→125ms), indexing strategies (B-Tree, Hash, GiST, GIN, BRIN), sync/async replication, sharding, buffer pool internals, deadlock detection, 2PL vs OCC, materialized views, connection pooling, CockroachDB vs Spanner | ~14 questions |
| 4 | **Distributed Systems** | CAP & PACELC, Raft consensus (leader election, log matching, split-brain prevention), 2PC vs 3PC vs Saga, vector clocks & Lamport timestamps, consistent hashing with virtual nodes, SWIM gossip protocol, distributed caching coherence, CRDTs, Paxos, distributed UUID generation, BFT | ~12 questions |
| 5 | **Concurrency & Parallelism** | Lock-free structures (Treiber stack, ABA, hazard pointers), memory models (release/acquire, happens-before), Amdahl's Law & Universal Scalability Law, deadlock analysis, work-stealing schedulers, RCU, futex & lock profiling, thread pool design, non-blocking progress guarantees | ~10 questions |
| 6 | **Data Structures & Algorithms** | Bloom filter math (1B keys at 0.1% FP), consistent hashing ring, HyperLogLog cardinality, Merkle tree anti-entropy, Count-Min Sketch, Trie vs FST for search, priority queue for scheduling, topological sort for DAGs, LRU/LFU/TTL cache design, rate limiting algorithms | ~10 questions |
| 7 | **Software Architecture** | DDD bounded contexts & event storming, CQRS & event sourcing with read-your-write, Kafka event-driven internals, API gateway vs service mesh, idempotency & exactly-once, circuit breaker & bulkhead, graceful degradation, observability (logging/metrics/tracing), saga choreography vs orchestration, backpressure, strangler fig migration, feature flags | ~12 questions |
| 8 | **Security** | JWT internals (signed not encrypted, revocation, key rotation), OAuth2 PKCE flow & OIDC, SQL injection prevention at scale, encryption at rest/in-transit, Vault secrets management, rate limiting & DDoS, session vs token vs passwordless auth, CORS/CSRF/SameSite cookies, supply chain security, SSRF prevention | ~10 questions |

---

## 🚀 Quick Start

```bash
# 1. Run any LLD project
cd low-level-design/parking-lot
python parking_lot.py

# 2. Run all LLD projects
cd low-level-design
for dir in */; do
    echo "=== $dir ==="
    cd "$dir" && python *.py && cd - > /dev/null
done

# 3. Verify the RAG pipeline end-to-end
cd rag-learning
python test_pipeline.py

# 4. Start with CS fundamentals
cd cs-interview/operating-systems
# Read INTERVIEW_QUESTIONS.md and trace through the code examples
```

---

## 📖 Interview Preparation Strategy

### Suggested Learning Roadmap

| Phase | Focus | Resources | Goal |
|-------|-------|-----------|------|
| **Phase 1: CS Foundations** | OS, Networks, Data Structures | `cs-interview/` | Build rock-solid CS fundamentals |
| **Phase 2: Object-Oriented Design** | Parking Lot, Vending Machine, Tic-Tac-Toe | `low-level-design/` | Master OOD, SOLID, state machines |
| **Phase 3: Language Deep-Dive** | Python or Go internals | `python-interview/` or `golang-interview/` | Show language mastery in interviews |
| **Phase 4: Concurrency & DB** | LRU Cache, Rate Limiter, Snakes & Ladders | `low-level-design/` + `cs-interview/` | Concurrency patterns, indexing, MVCC |
| **Phase 5: Distributed Systems** | Splitwise, Uber, Search Platform | `low-level-design/` + `cs-interview/` | Consensus, CAP, distributed transactions |
| **Phase 6: Architecture & Security** | Payments, Job Scheduling, ATM | `low-level-design/` + `cs-interview/` | CQRS, event sourcing, OAuth2, threat modeling |
| **Phase 7: ML/AI** | RAG Learning Module | `rag-learning/` | RAG pipelines, vector search, LLM integration |

### How to Study Each Module

1. **Read the question** and attempt to answer aloud
2. **Study the answer** — pay attention to trade-offs, not just the "right" answer
3. **Trace the code examples** — understand every edge case
4. **Connect topics** — e.g., "How does the OS's page cache affect database performance?"
5. **Apply to your experience** — prepare production war stories that demonstrate this knowledge

---

## 🛠️ Technology Stack

| Area | Technology |
|------|-----------|
| **Language** | Python 3.14+, Go |
| **Design Patterns** | Strategy, Factory, Observer, State, Command, Decorator, Facade, Chain of Responsibility, Singleton |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) |
| **Vector Store** | ChromaDB |
| **LLM** | Gemma 4B via LM Studio (OpenAI-compatible API) |
| **Web Framework** | FastAPI + Uvicorn |
| **Text Processing** | LangChain (document loaders, text splitters) |
| **Core Libraries** | NumPy, Requests, BeautifulSoup4, PyPDF |

---

## 📊 Stats

| Metric | Count |
|--------|-------|
| **LLD Projects** | 18 |
| **Python Files** | 18 |
| **INTERVIEW_QUESTIONS.md (LLD)** | 18 |
| **HIGH_LEVEL_DESIGN.md** | 18 |
| **RAG Documents** | 7 comprehensive guides |
| **RAG Implementation Files** | 9 Python files + 1 requirements.txt |
| **Language-Specific Modules** | 2 (Python + Go) |
| **CS Core Topics** | 8 (OS, Networks, DB, Distributed, Concurrency, DSA, Architecture, Security) |
| **Total Staff-Level Questions** | 90+ deep-dive questions |

---

## 🤝 Contributing

This is a personal interview preparation repository. Feel free to:
- **Extend** any project with new features (they're designed for it!)
- **Add** new LLD projects following the same structure
- **Improve** documentation or add test cases
- **Report** issues or suggest better approaches

---

## 📚 Additional Resources

- [Clean Code - Robert C. Martin](https://www.oreilly.com/library/view/clean-code-a/9780136083238/)
- [Design Patterns - Gang of Four](https://www.oreilly.com/library/view/design-patterns-elements/0201633612/)
- [System Design Interview - Alex Xu](https://www.amazon.com/System-Design-Interview-Insiders-Guide/dp/1736049119/)
- [LLM & RAG - Chip Huyen](https://www.oreilly.com/library/view/ai-engineering/9781098166298/)
- [Designing Data-Intensive Applications - Kleppmann](https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/)
- [Operating Systems: Three Easy Pieces](https://pages.cs.wisc.edu/~remzi/OSTEP/)
- [Computer Networking: A Top-Down Approach](https://www.amazon.com/Computer-Networking-Top-Down-Approach-7th/dp/0133594149)
- [LangChain Documentation](https://python.langchain.com/docs/get_started/introduction)
- [LM Studio](https://lmstudio.ai/)
- [Go Blog - Runtime](https://go.dev/blog/)
- [CPython Internals](https://realpython.com/cpython-source-code-guide/)

---

> *Built with ❤️ for backend engineers preparing for Senior/Staff/Principal-level interviews*
