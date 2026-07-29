#!/usr/bin/env python3
"""
Generate LLD CODE.md files with full source code embedded.

Reads source .py files and creates/updates CODE.md files to embed
the full source code in a Python code block — matching the pattern
used by parking-lot, chess-game, and most other LLD projects.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PAIRS = [
    {
        "src": "python-low-level-design/job-scheduling-system/job_scheduler.py",
        "code_md": "docs/python-low-level-design/job-scheduling-system/CODE.md",
        "header": """# Job Scheduling System — Implementation

> Full Python implementation of the Job Scheduling System following SOLID principles,
> design patterns, and demonstrating core CS concepts (GIL, race conditions, deadlock
> prevention, producer-consumer, cooperative cancellation).

---

""",
        "footer": """---

## ▶️ How to Run

```bash
cd python-low-level-design/job-scheduling-system
python job_scheduler.py
```

The demo:
1. Shows race condition (unsafe vs safe counter)
2. Schedules 8 jobs across all 3 concurrency models
3. Executes via async workers with semaphore limiting
4. Reports stats and execution history
"""
    },
    {
        "src": "python-low-level-design/big-file-upload/big_file_upload.py",
        "code_md": "docs/python-low-level-design/big-file-upload/CODE.md",
        "header": """# Big File Upload — Implementation

> Full Python implementation of the Big File Upload system following SOLID principles,
> TUS protocol, and production-grade patterns with chunked uploads, checksum verification,
> pluggable storage backends, and multi-level rate limiting.

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
""",
        "footer": """---

## ▶️ How to Run

```bash
cd python-low-level-design/big-file-upload
python big_file_upload.py
```

Or run the demo specifically:

```bash
python -c "from big_file_upload import demo; demo()"
```
"""
    }
]


def main():
    for pair in PAIRS:
        src_path = PROJECT_ROOT / pair["src"]
        code_md_path = PROJECT_ROOT / pair["code_md"]

        if not src_path.exists():
            print(f"⚠️  Source not found: {src_path}")
            continue

        source_code = src_path.read_text(encoding="utf-8")

        content = pair["header"]
        content += "## 📦 Full Source Code\n\n```python\n"
        content += source_code
        content += "\n```\n"
        content += pair["footer"]

        code_md_path.write_text(content, encoding="utf-8")
        print(f"✅ Updated {pair['code_md']} ({len(source_code.splitlines())} lines from source)")


if __name__ == "__main__":
    main()
