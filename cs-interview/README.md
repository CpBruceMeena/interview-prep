# 🖥️ Computer Science — Staff-Level Interview Questions

> **8 deep-dive CS topics** for Staff/Principal Engineer backend interviews  \
> *Each topic contains 10–15 questions with production-grade code examples, whiteboard-ready diagrams, and principal engineer–level analysis*

---

## 📋 Topic Overview

```
cs-interview/
├── README.md                           ← You are here
│
├── operating-systems/                  ← Memory, processes, I/O, scheduling
│   └── INTERVIEW_QUESTIONS.md          (12 questions)
│
├── computer-networks/                  ← TCP/IP, HTTP/2/3, DNS, TLS, load balancing
│   └── INTERVIEW_QUESTIONS.md          (12 questions)
│
├── database-systems/                   ← B-Trees vs LSM, MVCC, replication, sharding
│   └── INTERVIEW_QUESTIONS.md          (14 questions)
│
├── distributed-systems/                ← CAP, Raft, gossip, distributed transactions
│   └── INTERVIEW_QUESTIONS.md          (12 questions)
│
├── concurrency-parallelism/            ← Lock-free, memory models, schedulers
│   └── INTERVIEW_QUESTIONS.md          (10 questions)
│
├── data-structures-algorithms/         ← Bloom filters, sketches, Merkle trees
│   ├── INTERVIEW_QUESTIONS.md          (10 questions)
│   └── DATA_STRUCTURES_FOR_SCALE.md   (12 structures, 700+ lines)
│
├── software-architecture/              ← Microservices → Strangler Fig (all 12 topics)
│   └── INTERVIEW_QUESTIONS.md          (fully expanded with code examples & evaluation rubrics)
│
└── security/                           ← OWASP, JWT, OAuth2, secrets management
    └── INTERVIEW_QUESTIONS.md          (10 questions)
```

## 🎯 Target Audience

| Level | Years Exp | What's Expected |
|-------|-----------|----------------|
| **Senior** | 5–8 | Deep understanding of one topic area |
| **Staff** | 8–12 | Cross-cutting knowledge across ALL topics |
| **Principal** | 12+ | Production war stories, trade-off mastery, ability to design from scratch |

## 📖 How to Use

1. **Pick a topic** you're weaker on
2. **Read the question** and attempt to answer aloud
3. **Study the answer** — pay attention to trade-offs, not just the "right" answer
4. **Trace the code examples** — run them mentally, understand every edge case
5. **Connect topics** — e.g., "How does the OS's page cache affect database performance?"

## 🔗 Cross-Cutting Themes

| Theme | Appears In |
|-------|-----------|
| **Caching** | OS (page cache), Networks (CDN), Databases (buffer pool), Distributed (caches) |
| **Consistency vs Availability** | Databases (CAP), Distributed (PACELC), Architecture (eventual consistency) |
| **Concurrency Control** | OS (locks), DB (MVCC), Distributed (consensus), Concurrency (lock-free) |
| **Latency at Scale** | Networks (TCP), DB (query opt), Distributed (RTT), Architecture (CQRS) |
| **Fault Tolerance** | Distributed (Raft), Architecture (circuit breakers), Security (redundancy) |

---

> *Master these topics and you'll be prepared for the most rigorous Staff/Principal engineer interviews at FAANG, tier-2 tech, and high-growth startups.*
