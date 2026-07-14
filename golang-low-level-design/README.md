# 🦦 Golang Low Level Design Problems

A collection of **3 Low-Level Design (LLD)** problems implemented in **Go**, following **CSP** (Communicating Sequential Processes) and **design patterns** — curated for backend developer interviews.

## 📋 Project Index

| # | Project | Domain | Key Patterns |
|---|---------|--------|-------------|
| 1 | [Web Crawler](web-crawler/) | Concurrency | Worker Pool, Fan-Out/Fan-In, Pipeline |
| 2 | [In-Memory KV Store](kv-store/) | Data Structures | Strategy, Singleton, Min-Heap |
| 3 | [Task Queue / Worker Pool](task-queue/) | Async Processing | Worker Pool, Pipeline, Priority Queue |

## 🚀 How to Run

Each project is self-contained. Navigate to the project directory and run:

```bash
cd golang-low-level-design/<project-name>
go run <main_file>.go
```

## 🧩 Design Patterns

| Pattern | Usage |
|---------|-------|
| **Worker Pool** | Controlled concurrent task processing |
| **Strategy** | Eviction policies (LRU, LFU, TTL) |
| **Pipeline** | Task → Process → Result flow |
| **Fan-Out/Fan-In** | Distribute work, collect results |
| **Exponential Backoff** | Retry with delay to prevent thundering herd |
| **Context Cancellation** | Graceful shutdown of goroutines |

## 📖 Interview Preparation

Each project includes:
- **THOUGHT_PROCESS.md** — Design reasoning and trade-offs
- **CODE.md** — Implementation walkthrough with code snippets
- **HIGH_LEVEL_DESIGN.md** — Production architecture and scale
- **INTERVIEW_QUESTIONS.md** — Common interview questions with answers
