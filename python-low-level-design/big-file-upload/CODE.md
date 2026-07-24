# Big File Upload — Implementation

> Python implementation of the Big File Upload system following SOLID principles, TUS protocol, and production-grade patterns.

See [big_file_upload.py](./big_file_upload.py) for the full implementation.

---

## 🧩 Components Overview

| Component | Role | Pattern |
|-----------|------|---------|
| `UploadState` | Enum of upload lifecycle states | Enum |
| `UploadSession` | Represents a single upload attempt | Data class |
| `ChunkInfo` | Metadata for a single chunk | Data class |
| `UploadRepository` | DB access for uploads/chunks | Repository |
| `ChunkStorageBackend(ABC)` | Interface for chunk storage | Abstract Base |
| `S3ChunkStorage` | S3/MinIO chunk storage | Strategy |
| `LocalChunkStorage` | Local filesystem (dev/testing) | Strategy |
| `ChecksumVerifier` | SHA-256 verification | Utility |
| `UploadScheduler` | Controls concurrency + retry | Scheduler |
| `RateLimiter` | Multi-level rate limiting | Utility |
| `UploadService` | Core upload orchestration | Facade |
| `UploadStateMachine` | Validates state transitions | State Machine |
| `BackgroundGC` | Garbage collection for abandoned uploads | Background Task |

---

## 🧠 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `ChunkStorageBackend` | Swap S3 ↔ Local for testing |
| **Repository** | `UploadRepository` | Abstracts DB access behind interface |
| **Facade** | `UploadService` | Single entry point for upload operations |
| **State Machine** | `UploadState` + validation | Ensures valid lifecycle transitions |
| **Scheduler** | `UploadScheduler` | Controls parallel execution + retries |
| **Factory** | RateLimiter creation | Pluggable rate limiting strategies |
| **Observer** | Upload completion callbacks | Async processing pipeline hooks |

---

## 📊 Class Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        UploadService (Facade)                          │
│                                                                         │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────────┐  │
│  │ initiate()     │  │ upload_chunk() │  │ complete()              │  │
│  │ cancel()       │  │ get_status()   │  │ get_progress()          │  │
│  └───────┬────────┘  └───────┬────────┘  └────────────┬─────────────┘  │
│          │                   │                         │                │
└──────────┼───────────────────┼─────────────────────────┼────────────────┘
           │                   │                         │
           ▼                   ▼                         ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐
│ UploadRepository │ │ ChunkStorage     │ │ ChecksumVerifier        │
│ (PostgreSQL)     │ │ Backend          │ │ (SHA-256)               │
└──────────────────┘ │ (Strategy)       │ └──────────────────────────┘
                     └────────┬─────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            ┌──────────────┐   ┌──────────────┐
            │ S3Chunk      │   │LocalChunk    │
            │ Storage      │   │Storage       │
            └──────────────┘   └──────────────┘
```

---

## ▶️ How to Run

```bash
cd python-low-level-design/big-file-upload
python big_file_upload.py
```

Or run the demo specifically:

```bash
python -c "from big_file_upload import demo; demo()"
```
