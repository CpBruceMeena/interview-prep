# 🧠 Big File Upload LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design for a big file upload system.

---

## ⏱️ How to Run This in a 45–60 Minute Interview

| Time | Phase | What you produce | What to say out loud |
|------|-------|------------------|----------------------|
| 0–7 min | **Clarify** | Max size, resumability, parallelism, post-processing, scale | "Chunked and resumable is the requirement. I'll make chunk *i* a fixed byte range so chunks can go in parallel and out of order." |
| 7–15 min | **Entities + interfaces** | `UploadSession`, `UploadState` + transitions, `ChunkStorage` ABC, `UploadService.initiate/upload_chunk/missing_chunks/complete/cancel` | "Storage is a strategy; the service never knows if it's S3 or disk." |
| 15–35 min | **Core code** | `initiate` (chunk sizing), `upload_chunk` (size + checksum + idempotency), `complete` (gaps, verify, compose) | "A retry of the same chunk is a no-op; different bytes for a stored chunk is a 409, never an overwrite." |
| 35–45 min | **Concurrency + failure** | Per-upload lock released during storage I/O, `inflight` set, `ASSEMBLING` state, rollback on storage error | "Two requests for the same chunk, or complete() racing a write: here's what each sees." |
| 45–60 min | **Extensions** | Rate limits, expiry/GC, virus-scan hook, pre-signed URLs | Each lands in one place: `UploadLimiter`, `collect_garbage`, `on_completed`, the storage strategy. |

Get `initiate → upload_chunk → complete` working first. Rate limiting and GC are 5-minute extensions once the state machine is right. A perfect rate limiter on a protocol that can't resume is a fail.

### Clarifying questions worth asking

- **Max file size?** (Decides chunk size: S3 allows 10,000 parts, so 100 GiB needs ≥ 10.24 MiB chunks.)
- **Must uploads survive a browser restart?** (The client must persist `upload_id`; the server must answer "what's missing".)
- **Parallel chunks or sequential?** (Parallel → chunk-indexed like S3 multipart. Sequential → TUS offset semantics. This design supports both.)
- **Bytes through our servers, or direct to the object store?** (Pre-signed URLs change who verifies checksums.)
- **What happens after upload?** (Virus scan before download? Transcode?)
- **Per-user limits?** (Concurrent uploads, daily quota, bandwidth.)
- **How long do incomplete uploads live?**

---

## Phase 1: Identify the Nouns

> *"A big file upload system splits a large file into chunks, uploads them reliably, verifies integrity, assembles the final file, and triggers async processing."*

| Noun | Decision | Why |
|------|----------|-----|
| `UploadPolicy` | Frozen dataclass | Limits and chunk sizing in one testable place |
| `UploadSession` | Dataclass | State, chunks, derived progress/offset/missing |
| `ChunkInfo` | Frozen dataclass | Immutable record of a stored chunk |
| `UploadState` | Enum + transition table | Finite lifecycle; illegal edges raise |
| `ChunkStorage` | ABC | S3 vs disk vs memory |
| `UploadRepository` | Class | Hides persistence; in prod a status-guarded row update |
| `UploadLimiter` | Class | Cross-cutting limits, atomic check-and-apply |
| `UploadService` | Facade | Orchestrates the flow, owns the per-upload locks |
| `UploadClient` | Class | Chunking, parallelism, retry, resume (the other half of the protocol) |

---

## Phase 2: State Machine First

```python
INITIATED   → IN_PROGRESS, ASSEMBLING (0-byte file), CANCELLED, EXPIRED
IN_PROGRESS → ASSEMBLING, CANCELLED, EXPIRED
ASSEMBLING  → COMPLETED, IN_PROGRESS (corrupt chunk / storage error), FAILED
COMPLETED   → READY, QUARANTINED
QUARANTINED → READY            # false positive released
```

**Key insight:** `ASSEMBLING` is what makes `complete()` safe. It is set under the lock, and from then on chunk writes, `cancel` and a second `complete` are refused, so the slow verification and composition can run *without* holding the lock.

---

## Phase 3: Chunk Protocol

- Chunk *i* covers `[i·chunk_size, min((i+1)·chunk_size, file_size))`. Every chunk must be exactly that long. The server checks, so chunks can't overlap or run past the end.
- Each request carries the chunk's SHA-256; the server verifies before storing.
- **Idempotency:** a stored chunk with the same hash → success, `duplicate=True`. A different hash → `ChunkConflictError` (409).
- **Resume:** `missing_chunks()` for parallel clients. `get_offset()` = the **contiguous** prefix for TUS-style sequential clients. "Total bytes received" is the wrong answer when chunks arrive out of order.

---

## Phase 4: Concurrency (where most designs are wrong)

`upload_chunk` runs in three phases:

1. **Lock:** validate state, index, size, checksum; handle duplicates; take bandwidth tokens; add the index to `inflight`.
2. **No lock:** write to storage (slow). Other chunks of the same upload write in parallel.
3. **Lock:** remove from `inflight`; if the upload was cancelled or expired meanwhile, fail; else record the chunk and slide `expires_at`.

| Race | Outcome |
|------|---------|
| Same chunk sent twice at once | Second gets `ChunkInProgressError` (retryable); exactly one write |
| `complete()` while a chunk is in flight | `ChunkInProgressError`; client retries `complete()` |
| `cancel()` while a chunk is in flight | `ChunkInProgressError` |
| Two `complete()` calls | First moves to `ASSEMBLING`; second is refused; after success, `complete()` returns the same session (idempotent) |
| Storage fails during compose | Back to `IN_PROGRESS`, chunks intact, retry `complete()` |

---

## Phase 5: Strategy Pattern for Storage

```python
class ChunkStorage(ABC):
    async def put_chunk(self, key, data): ...          # S3: UploadPart
    async def get_chunk(self, key): ...
    async def compose(self, dest_key, part_keys): ...  # S3: CompleteMultipartUpload
    async def delete_prefix(self, prefix): ...         # S3: AbortMultipartUpload / DeleteObjects
```

- **Testability:** tests use `InMemoryChunkStorage`; one test runs `LocalChunkStorage` on real files.
- **Local backend details worth saying:** blocking file I/O goes through `asyncio.to_thread`; writes go to a temp file and `os.replace` into place (atomic); every key is resolved and checked to stay under the root.

---

## Phase 6: Integrity

1. Per chunk on arrival: SHA-256 must match the header.
2. At `complete()`: re-hash every stored chunk (catches corruption at rest) and compute the whole-file SHA-256 in the same ordered pass.
3. Corrupt chunk → drop it, back to `IN_PROGRESS`, client re-sends just that chunk.
4. Whole-file mismatch with every chunk intact → the client sent the wrong file or the wrong hash → `FAILED`.

On S3 you'd let S3 verify per-part checksums and use a composite checksum, instead of re-reading 100 GB.

---

## Phase 7: Limits, Expiry, Hooks

- **`UploadLimiter`:** concurrent-upload slots (a set, so release is idempotent), daily quota reserved at initiate and refunded on cancel/expiry/failure, a bandwidth token bucket charged per chunk. Check everything, then apply everything, with no `await` between.
- **Expiry:** sliding TTL (each chunk extends it). The request path refuses expired uploads; `collect_garbage()` owns the `EXPIRED` transition and the cleanup.
- **Hooks:** `on_completed` runs after the state is committed (virus scan → `record_scan_result`).

---

## Phase 8: Key Decisions

| Decision | Options | Choice and why |
|----------|---------|----------------|
| Chunk size | Fixed 5 MB, adaptive | `max(preferred, 5 MiB, ceil(size/10,000))`: S3's minimum part size and maximum part count |
| Parallel uploads | 1, 3–6, 10+ | 4–6 from a browser over HTTP/1.1 (6 connections per origin); more over HTTP/2 to S3 |
| Bytes path | Proxy vs pre-signed URL | Pre-signed for big files; this LLD is the proxy shape so the server logic is visible |
| Checksum | MD5, CRC32C, SHA-256 | SHA-256 per chunk and whole file; CRC32C is cheaper and S3-native if you only need corruption detection |
| Retry | Fixed, exponential, + jitter | Exponential with full jitter; honour `Retry-After` on 429 |

---

## Phase 9: Quick Checklist

✅ **Strategy Pattern:** `ChunkStorage` (memory, local; S3 mapping documented)
✅ **Facade:** `UploadService`
✅ **State machine:** transition table incl. `ASSEMBLING` and its rollback edge
✅ **Idempotency:** same chunk → no-op; different bytes → conflict; `complete()` idempotent
✅ **Correct resume:** `missing_chunks()` + contiguous `get_offset()`
✅ **Concurrency:** lock not held across storage I/O; `inflight` guards same-chunk and complete/cancel races
✅ **Integrity:** per-chunk, at-rest re-verify, whole-file SHA-256
✅ **Atomic limits** with refunds; bandwidth per chunk
✅ **GC:** sliding expiry, GC owns cleanup
✅ **Client:** bounded parallelism, jittered retries, resume after crash
