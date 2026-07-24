# 🧠 Big File Upload LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design for a big file upload system.

---

## Phase 0: Requirements Gathering

**Key questions to ask:**
- What's the maximum file size? (100MB, 10GB, 100GB?)
- How many concurrent uploads? (100, 10K, 1M?)
- Do uploads need to be resumable? (Yes, always for large files)
- What happens after upload? (Virus scan, transcode, just store?)
- Who are the users? (General public, internal team, enterprise?)
- Storage backend? (S3, GCS, local filesystem?)
- Availability requirements? (99.9%, 99.99%?)
- Do we need progress tracking? (Yes, always for large files)

## Phase 1: Identify the Nouns

> *"A big file upload system splits a large file into chunks, uploads them reliably, verifies integrity, assembles the final file, and triggers async processing."*

| Noun | Decision | Why |
|------|----------|-----|
| UploadSession | Data class | Holds state, progress, metadata — single responsibility |
| ChunkInfo | Data class | Simple structure — no behavior |
| UploadState | Enum | Finite set of lifecycle states |
| ChunkStorageBackend | ABC (Abstract Base) | Different backends (S3, Local) need pluggable interface |
| UploadRepository | Regular class | Manages persistence — hides DB from service |
| UploadService | Regular class | Facade — orchestrates the entire flow |
| UploadScheduler | Regular class | Manages concurrency and retry — separated from business logic |
| RateLimiter | Regular class | Cross-cutting concern — should be independent |
| ChecksumVerifier | Static utility | Pure function — no state needed |
| BackgroundGC | Regular class | Background job — runs periodically |

## Phase 2: Enums First

```python
class UploadState(str, Enum):
    INITIATED = "initiated"      # Just created, no chunks yet
    IN_PROGRESS = "in_progress"  # Receiving chunks
    COMPLETED = "completed"      # All chunks received and assembled
    PROCESSING = "processing"    # Post-processing pipeline
    READY = "ready"              # Available for download
    QUARANTINED = "quarantined"  # Virus detected
    FAILED = "failed"            # Upload abandoned or failed
    EXPIRED = "expired"          # Upload session timed out
```

**Key insight:** The state machine with `can_transition_to()` prevents invalid transitions (e.g., going from INITIATED directly to READY). This makes the code self-documenting and prevents bugs.

## Phase 3: Dataclass vs `__init__`

- **`UploadSession`**: Dataclass with field defaults — it's primarily data with computed properties (`received_bytes`, `progress_percent`). The `__post_init__` handles derived fields.
- **`ChunkInfo`**: Simple dataclass — pure data, no behavior.
- **`ChunkStorageBackend`**: Regular ABC — has behavior, needs abstract methods.
- **`UploadService`**: Regular class — complex orchestration with many dependencies injected via constructor (Dependency Injection).
- **`RateLimiter`**: Regular class — maintains state (concurrent counts, throughput windows).

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Validate chunk checksums | `ChecksumVerifier` | Pure function, no side effects |
| Store/retrieve chunk bytes | `ChunkStorageBackend` | Encapsulates storage details |
| Persist/query upload metadata | `UploadRepository` | Abstracts DB access |
| Rate limit checks | `RateLimiter` | Cross-cutting concern, separate from business logic |
| Control parallel uploads | `UploadScheduler` | Separates concurrency from upload logic |
| Orchestrate upload flow | `UploadService` | Facade — delegates to components |
| Clean abandoned uploads | `BackgroundGC` | Separate responsibility from upload flow |

**Key insight:** The `UploadService` doesn't do much itself — it delegates to specialized components. This is the Facade pattern at work.

## Phase 5: Strategy Pattern

```python
class ChunkStorageBackend(ABC):
    @abstractmethod
    async def store_chunk(self, upload_id, chunk_number, data, path): ...
    @abstractmethod
    async def assemble_file(self, upload_id, chunks, destination_path): ...

class S3ChunkStorage(ChunkStorageBackend):  # Production
class LocalChunkStorage(ChunkStorageBackend):  # Dev/Test
```

Why this matters:
- **Testability**: Unit tests use `LocalChunkStorage` without needing AWS credentials
- **Flexibility**: Swap S3 for GCS, MinIO, or Azure Blob without changing `UploadService`
- **Open/Closed**: New storage backends extend, never modify, existing code

## Phase 6: TUS Protocol Design

The TUS resumable upload protocol defines these HTTP operations:

```
POST   /upload              → Initiate (create upload session)
PATCH  /upload/{id}/chunk   → Upload chunk (with offset)
HEAD   /upload/{id}         → Get current offset (for resume)
POST   /upload/{id}/complete → Finalize (verify + assemble)
DELETE /upload/{id}         → Cancel (clean up chunks)
```

In the LLD, these map to:
- `UploadService.initiate()` → POST
- `UploadService.upload_chunk()` → PATCH
- `UploadService.get_offset()` → HEAD
- `UploadService.complete()` → POST /complete
- `UploadService.cancel()` → DELETE

## Phase 7: Understanding the Key Decisions

| Decision | Options | Why We Chose This |
|----------|---------|-------------------|
| Chunk size | 1MB, 5MB, 10MB, 50MB | 5MB matches S3 multipart minimum, good for general networks |
| Parallel uploads | 1, 3, 6, 10 | 3-6: balances speed vs reliability; browser limit is 6 |
| Storage | Direct upload vs proxy | Pre-signed URLs for large files; proxy for small files |
| Checksum | MD5, SHA-256, CRC32 | SHA-256: collision-resistant, standard for integrity |
| State persistence | In-memory, PostgreSQL | PostgreSQL for production; in-memory for testing/prototype |
| Retry backoff | Fixed, exponential, jitter | Exponential + jitter: prevents thundering herd on retry |

## Phase 8: Quick Checklist

✅ **Strategy Pattern:** `ChunkStorageBackend` for pluggable storage
✅ **Facade Pattern:** `UploadService` simplifies the complex upload flow
✅ **State Machine:** `UploadState.can_transition_to()` prevents invalid transitions
✅ **Dependency Injection:** Constructor injection of repo, storage, scheduler
✅ **SRP:** Rate limiting, storage, scheduling are all separate classes
✅ **Idempotency:** Duplicate chunk detection via `(upload_id, chunk_number)`
✅ **Async-first:** All I/O operations use asyncio
✅ **Retry logic:** Exponential backoff with configurable limits
✅ **TUS compliance:** HEAD for offset, PATCH for upload, POST for complete
✅ **Garbage collection:** Background job cleans abandoned uploads
