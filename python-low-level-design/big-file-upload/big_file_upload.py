"""
Big File Upload System — Low-Level Design
=========================================

Server side (UploadService) of a resumable, parallel, chunked upload protocol,
plus a client (UploadClient) that splits a file, uploads chunks with bounded
concurrency and retries, and resumes after a crash.

The protocol is chunk-indexed, like S3 multipart upload (and TUS's
concatenation extension): chunk i covers bytes [i*chunk_size, (i+1)*chunk_size).
Chunks may arrive in any order and in parallel. A client resumes either by
asking which chunks are missing (parallel clients) or by asking for the
contiguous offset (TUS HEAD semantics, for a sequential client).

Guarantees the code enforces:
  * Every chunk has the exact expected size and a SHA-256 the server verifies.
  * Re-sending a chunk with the same bytes is a no-op (idempotent retry);
    different bytes for a stored chunk is a conflict, never a silent overwrite.
  * The same chunk can't be written by two requests at once, and an upload
    can't be completed or cancelled while a chunk write is in flight.
  * complete() re-verifies every stored chunk, computes the whole-file SHA-256
    while assembling, and checks it against the client's. A corrupted chunk is
    dropped and the upload goes back to IN_PROGRESS so the client re-sends just
    that chunk.
  * Rate limits are atomic: a rejected upload never leaks a concurrency slot or
    charges quota. Bandwidth is limited per chunk with a token bucket.
  * Expired uploads are garbage-collected; expiry slides with activity.

Concurrency model: asyncio, one event loop. Per-upload asyncio.Lock guards
state changes; it is NOT held during storage I/O, so chunks of one upload
still write in parallel.

Run:   python3 big_file_upload.py
Test:  python3 -m unittest test_big_file_upload
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import random
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("upload-service")

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB


# ════════════════════════════════════════════════════════════════════════
#  ERRORS (each maps to an HTTP status in the API layer)
# ════════════════════════════════════════════════════════════════════════

class UploadError(Exception):
    """Base class."""


class UploadNotFoundError(UploadError):           # 404
    pass


class InvalidRequestError(UploadError):           # 400 / 413
    pass


class InvalidStateError(UploadError):             # 409
    pass


class ChecksumMismatchError(UploadError):         # 460 in TUS, 400 otherwise
    pass


class ChunkConflictError(UploadError):            # 409: different bytes for a stored chunk
    pass


class ChunkInProgressError(UploadError):          # 409: retry later
    pass


class IncompleteUploadError(UploadError):         # 409 on complete()
    def __init__(self, missing: List[int]) -> None:
        super().__init__(f"{len(missing)} chunks missing, first: {missing[:5]}")
        self.missing = missing


class ChunkCorruptedError(UploadError):           # 409 on complete(): re-send these chunks
    def __init__(self, chunks: List[int]) -> None:
        super().__init__(f"stored chunks failed verification: {chunks}")
        self.chunks = chunks


class RateLimitedError(UploadError):              # 429 with Retry-After
    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UploadExpiredError(UploadError):            # 410
    pass


# ════════════════════════════════════════════════════════════════════════
#  POLICY + STATE MACHINE
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UploadPolicy:
    min_chunk_size: int = 5 * MIB           # S3 multipart minimum (except the last part)
    default_chunk_size: int = 8 * MIB
    max_parts: int = 10_000                 # S3 multipart maximum
    max_file_size: int = 100 * GIB
    session_ttl: float = 7 * 86_400         # sliding: extended on every chunk
    max_concurrent_uploads: int = 5         # per user
    daily_quota_bytes: int = 200 * GIB      # per user
    bandwidth_bytes_per_sec: float = 50 * MIB   # per user, token bucket refill
    bandwidth_burst_bytes: float = 100 * MIB    # bucket size; must hold the largest chunk

    def chunk_size_for(self, file_size: int, preferred: Optional[int] = None) -> int:
        """
        At least min_chunk_size, and big enough that the file fits in max_parts.
        100 GiB / 10,000 parts needs >= 10.24 MiB chunks: a fixed 5 MiB would
        need 20,480 parts and S3 would reject the upload.
        """
        size = max(preferred or self.default_chunk_size, self.min_chunk_size,
                   math.ceil(file_size / self.max_parts))
        if size > self.bandwidth_burst_bytes:
            raise InvalidRequestError("chunk size exceeds the bandwidth burst; no chunk could ever be accepted")
        return size


class UploadState(str, Enum):
    INITIATED = "initiated"        # session created, no chunk yet
    IN_PROGRESS = "in_progress"    # receiving chunks
    ASSEMBLING = "assembling"      # complete() is verifying + composing; chunk writes refused
    COMPLETED = "completed"        # assembled and verified; awaiting virus scan
    READY = "ready"                # scan clean: downloadable
    QUARANTINED = "quarantined"    # scan flagged it
    FAILED = "failed"              # whole-file checksum mismatch
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def accepts_chunks(self) -> bool:
        return self in (UploadState.INITIATED, UploadState.IN_PROGRESS)

    @property
    def holds_slot(self) -> bool:
        """Counts against the user's concurrent-upload limit."""
        return self in (UploadState.INITIATED, UploadState.IN_PROGRESS, UploadState.ASSEMBLING)


_TRANSITIONS: Dict[UploadState, Set[UploadState]] = {
    UploadState.INITIATED: {UploadState.IN_PROGRESS, UploadState.ASSEMBLING,   # 0-byte file
                            UploadState.CANCELLED, UploadState.EXPIRED},
    UploadState.IN_PROGRESS: {UploadState.ASSEMBLING, UploadState.CANCELLED, UploadState.EXPIRED},
    UploadState.ASSEMBLING: {UploadState.COMPLETED, UploadState.IN_PROGRESS,    # corrupt chunk dropped
                             UploadState.FAILED},
    UploadState.COMPLETED: {UploadState.READY, UploadState.QUARANTINED},
    UploadState.QUARANTINED: {UploadState.READY},                                # false positive released
}


# ════════════════════════════════════════════════════════════════════════
#  DOMAIN MODEL
# ════════════════════════════════════════════════════════════════════════

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ChunkInfo:
    index: int
    offset: int
    size: int
    sha256: str
    storage_key: str
    received_at: float


@dataclass(frozen=True)
class ChunkReceipt:
    index: int
    duplicate: bool
    received_bytes: int        # progress
    contiguous_offset: int     # TUS Upload-Offset


@dataclass
class UploadSession:
    upload_id: str
    user_id: str
    filename: str
    file_size: int
    mime_type: str
    chunk_size: int
    expected_sha256: Optional[str]
    created_at: float
    expires_at: float
    status: UploadState = UploadState.INITIATED
    chunks: Dict[int, ChunkInfo] = field(default_factory=dict)
    inflight: Set[int] = field(default_factory=set)       # chunk writes in progress
    final_key: Optional[str] = None
    final_sha256: Optional[str] = None
    error: Optional[str] = None

    @property
    def total_chunks(self) -> int:
        return math.ceil(self.file_size / self.chunk_size)

    @property
    def temp_prefix(self) -> str:
        return f"tmp/{self.upload_id}/"

    def chunk_bounds(self, index: int) -> Tuple[int, int]:
        start = index * self.chunk_size
        return start, min(start + self.chunk_size, self.file_size)

    @property
    def received_bytes(self) -> int:
        return sum(c.size for c in self.chunks.values())

    @property
    def contiguous_offset(self) -> int:
        """
        Bytes received with no gap from the start. With out-of-order chunks
        this is NOT received_bytes: chunks {0, 2} received means offset is the
        end of chunk 0, because chunk 1 is still missing.
        """
        i = 0
        while i in self.chunks:
            i += 1
        return min(i * self.chunk_size, self.file_size)

    def missing_chunks(self) -> List[int]:
        return [i for i in range(self.total_chunks) if i not in self.chunks]

    def progress_percent(self) -> float:
        return 100.0 if self.file_size == 0 else 100.0 * self.received_bytes / self.file_size


# ════════════════════════════════════════════════════════════════════════
#  STORAGE — Strategy
# ════════════════════════════════════════════════════════════════════════

class ChunkStorage(ABC):
    """
    Object-store-shaped interface. On S3: put_chunk = UploadPart (or PutObject
    to a temp key), compose = CompleteMultipartUpload, delete_prefix = list +
    DeleteObjects (plus AbortMultipartUpload).
    """

    @abstractmethod
    async def put_chunk(self, key: str, data: bytes) -> None:
        """Write (or overwrite) one object. Must be atomic: readers never see half a chunk."""

    @abstractmethod
    async def get_chunk(self, key: str) -> bytes:
        ...

    @abstractmethod
    async def compose(self, dest_key: str, part_keys: List[str]) -> None:
        """Concatenate parts, in order, into dest_key."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        ...

    @abstractmethod
    async def read_object(self, key: str) -> bytes:
        """Whole final object. For demos/tests only; never do this for a 100 GB file."""


class InMemoryChunkStorage(ChunkStorage):
    def __init__(self) -> None:
        self.objects: Dict[str, bytes] = {}

    async def put_chunk(self, key: str, data: bytes) -> None:
        await asyncio.sleep(0)                      # a real store would yield here
        self.objects[key] = bytes(data)

    async def get_chunk(self, key: str) -> bytes:
        return self.objects[key]

    async def compose(self, dest_key: str, part_keys: List[str]) -> None:
        self.objects[dest_key] = b"".join(self.objects[k] for k in part_keys)

    async def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self.objects if k.startswith(prefix)]:
            del self.objects[key]

    async def read_object(self, key: str) -> bytes:
        return self.objects[key]


class LocalChunkStorage(ChunkStorage):
    """
    Filesystem backend. Blocking file I/O runs in a worker thread
    (asyncio.to_thread) so it doesn't stall the event loop. Writes go to a
    temp file and are renamed into place, so a crash never leaves half a chunk
    under the real name. Keys are built from server-generated ids, never from
    the user's filename, so path traversal can't reach this layer.
    """

    def __init__(self, root: str) -> None:
        self._root = os.path.realpath(root)
        os.makedirs(self._root, exist_ok=True)

    def _path(self, key: str) -> str:
        path = os.path.realpath(os.path.join(self._root, key))
        if not path.startswith(self._root + os.sep):
            raise InvalidRequestError(f"key escapes storage root: {key!r}")
        return path

    async def put_chunk(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._atomic_write, self._path(key), data)

    @staticmethod
    def _atomic_write(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{uuid.uuid4().hex}.part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)                      # atomic on POSIX

    async def get_chunk(self, key: str) -> bytes:
        return await asyncio.to_thread(self._read, self._path(key))

    @staticmethod
    def _read(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    async def compose(self, dest_key: str, part_keys: List[str]) -> None:
        await asyncio.to_thread(self._concat, self._path(dest_key), [self._path(k) for k in part_keys])

    @staticmethod
    def _concat(dest: str, parts: List[str]) -> None:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = f"{dest}.{uuid.uuid4().hex}.part"
        with open(tmp, "wb") as out:
            for part in parts:
                with open(part, "rb") as f:
                    while block := f.read(MIB):     # stream: memory stays O(1 MiB)
                        out.write(block)
        os.replace(tmp, dest)

    async def delete_prefix(self, prefix: str) -> None:
        import shutil
        path = self._path(prefix.rstrip("/"))
        await asyncio.to_thread(shutil.rmtree, path, True)

    async def read_object(self, key: str) -> bytes:
        return await self.get_chunk(key)


# ════════════════════════════════════════════════════════════════════════
#  REPOSITORY (in-memory stand-in for PostgreSQL)
# ════════════════════════════════════════════════════════════════════════

class UploadRepository:
    """
    In production each mutation is a row update guarded by the current status
    (UPDATE ... WHERE id = $1 AND status = $2), which gives the same
    compare-and-set the per-upload lock gives here.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, UploadSession] = {}

    def add(self, session: UploadSession) -> None:
        self._sessions[session.upload_id] = session

    def get(self, upload_id: str) -> UploadSession:
        try:
            return self._sessions[upload_id]
        except KeyError:
            raise UploadNotFoundError(upload_id) from None

    def expired(self, now: float) -> List[UploadSession]:
        return [s for s in self._sessions.values()
                if s.status.accepts_chunks and s.expires_at <= now]


# ════════════════════════════════════════════════════════════════════════
#  RATE LIMITING
# ════════════════════════════════════════════════════════════════════════

class TokenBucket:
    def __init__(self, rate: float, capacity: float, now: float) -> None:
        self.rate, self.capacity = rate, capacity
        self.tokens, self.updated = capacity, now

    def try_take(self, amount: float, now: float) -> float:
        """Take `amount` tokens. Returns 0 on success, else seconds until it would fit."""
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if amount <= self.tokens:
            self.tokens -= amount
            return 0.0
        return (amount - self.tokens) / self.rate


class UploadLimiter:
    """
    Per-user limits, all checked and applied in one step with no await in
    between, so a rejected request changes nothing (the old version incremented
    the concurrency counter even when the quota check then failed, leaking a
    slot forever).

      * concurrent uploads — a set of upload ids, so release is idempotent
      * daily quota — bytes reserved at initiate, refunded on cancel/expiry
      * bandwidth — token bucket charged per chunk (not per declared file size:
        charging 5 GB up front against a 50 MB/s x 60 s window would reject
        every file over 3 GB forever)

    In a fleet these live in Redis, each check-and-apply as one Lua script.
    """

    def __init__(self, policy: UploadPolicy, clock: Callable[[], float]) -> None:
        self._policy = policy
        self._clock = clock
        self._active: Dict[str, Set[str]] = {}
        self._quota_used: Dict[Tuple[str, str], int] = {}
        self._buckets: Dict[str, TokenBucket] = {}

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    def start_upload(self, user_id: str, upload_id: str, size: int) -> None:
        active = self._active.setdefault(user_id, set())
        if len(active) >= self._policy.max_concurrent_uploads:
            raise RateLimitedError(f"{len(active)} uploads already in progress", retry_after=30)
        key = (user_id, self._day())
        if self._quota_used.get(key, 0) + size > self._policy.daily_quota_bytes:
            raise RateLimitedError("daily upload quota exceeded", retry_after=3600)
        active.add(upload_id)
        self._quota_used[key] = self._quota_used.get(key, 0) + size

    def finish_upload(self, user_id: str, upload_id: str, refund: int = 0) -> None:
        active = self._active.get(user_id)
        if active is None or upload_id not in active:
            return                                   # already released: idempotent
        active.discard(upload_id)
        if refund:
            key = (user_id, self._day())
            self._quota_used[key] = max(0, self._quota_used.get(key, 0) - refund)

    def take_bandwidth(self, user_id: str, nbytes: int) -> None:
        now = self._clock()
        bucket = self._buckets.get(user_id)
        if bucket is None:
            bucket = self._buckets[user_id] = TokenBucket(
                self._policy.bandwidth_bytes_per_sec, self._policy.bandwidth_burst_bytes, now)
        wait = bucket.try_take(nbytes, now)
        if wait:
            raise RateLimitedError("bandwidth limit", retry_after=wait)

    def active_uploads(self, user_id: str) -> int:
        return len(self._active.get(user_id, ()))


# ════════════════════════════════════════════════════════════════════════
#  UPLOAD SERVICE — Facade
# ════════════════════════════════════════════════════════════════════════

CompletionHook = Callable[[UploadSession], Awaitable[None]]


class UploadService:
    def __init__(self, storage: ChunkStorage, *,
                 repository: Optional[UploadRepository] = None,
                 policy: UploadPolicy = UploadPolicy(),
                 clock: Callable[[], float] = time.time,
                 id_factory: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._storage = storage
        self._repo = repository or UploadRepository()
        self._policy = policy
        self._clock = clock
        self._new_id = id_factory
        self._limiter = UploadLimiter(policy, clock)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._hooks: List[CompletionHook] = []

    @property
    def limiter(self) -> UploadLimiter:
        return self._limiter

    def on_completed(self, hook: CompletionHook) -> None:
        """Observer: called after an upload is assembled and verified (e.g. enqueue a virus scan)."""
        self._hooks.append(hook)

    # ── POST /uploads ─────────────────────────────────────────────────
    async def initiate(self, user_id: str, filename: str, file_size: int, mime_type: str, *,
                       sha256: Optional[str] = None,
                       preferred_chunk_size: Optional[int] = None) -> UploadSession:
        self._validate_filename(filename)
        if not 0 <= file_size <= self._policy.max_file_size:
            raise InvalidRequestError(f"file_size must be 0..{self._policy.max_file_size}")
        if sha256 is not None and len(sha256) != 64:
            raise InvalidRequestError("sha256 must be 64 hex characters")
        chunk_size = self._policy.chunk_size_for(file_size, preferred_chunk_size)
        upload_id = self._new_id()
        self._limiter.start_upload(user_id, upload_id, file_size)      # atomic; raises on reject
        now = self._clock()
        session = UploadSession(upload_id, user_id, filename, file_size, mime_type, chunk_size,
                                sha256, created_at=now, expires_at=now + self._policy.session_ttl)
        self._repo.add(session)
        self._locks[upload_id] = asyncio.Lock()
        logger.info("initiated %s: %s, %d bytes, %d chunks of %d",
                    upload_id, filename, file_size, session.total_chunks, chunk_size)
        return session

    @staticmethod
    def _validate_filename(name: str) -> None:
        if not name or len(name) > 255 or name in (".", "..") \
                or any(c in name for c in "/\\\x00") or name.startswith("."):
            raise InvalidRequestError(f"invalid filename: {name!r}")

    # ── PUT /uploads/{id}/chunks/{index} ──────────────────────────────
    async def upload_chunk(self, upload_id: str, index: int, data: bytes, sha256: str) -> ChunkReceipt:
        session = self._repo.get(upload_id)
        lock = self._locks[upload_id]

        # Phase 1 (under lock): validate and reserve the index.
        async with lock:
            self._check_accepting(session)
            if not 0 <= index < session.total_chunks:
                raise InvalidRequestError(f"chunk index {index} out of range 0..{session.total_chunks - 1}")
            start, end = session.chunk_bounds(index)
            if len(data) != end - start:
                raise InvalidRequestError(f"chunk {index} must be {end - start} bytes, got {len(data)}")
            if sha256_hex(data) != sha256:
                raise ChecksumMismatchError(f"chunk {index}: body does not match its sha256")
            existing = session.chunks.get(index)
            if existing is not None:
                if existing.sha256 != sha256:
                    raise ChunkConflictError(f"chunk {index} already stored with different content")
                return self._receipt(session, index, duplicate=True)    # idempotent retry
            if index in session.inflight:
                raise ChunkInProgressError(f"chunk {index} is being written by another request")
            self._limiter.take_bandwidth(session.user_id, len(data))
            session.inflight.add(index)

        # Phase 2 (no lock): the slow part. Other chunks of this upload proceed in parallel.
        key = f"{session.temp_prefix}{index:05d}"
        try:
            await self._storage.put_chunk(key, data)
        except BaseException:
            async with lock:
                session.inflight.discard(index)
            raise

        # Phase 3 (under lock): record it, unless the upload was cancelled/expired meanwhile.
        async with lock:
            session.inflight.discard(index)
            if not session.status.accepts_chunks:
                raise InvalidStateError(f"upload became {session.status.value} during the write")
            now = self._clock()
            session.chunks[index] = ChunkInfo(index, start, len(data), sha256, key, now)
            session.expires_at = now + self._policy.session_ttl          # sliding expiry
            if session.status is UploadState.INITIATED:
                self._transition(session, UploadState.IN_PROGRESS)
            return self._receipt(session, index, duplicate=False)

    @staticmethod
    def _receipt(session: UploadSession, index: int, duplicate: bool) -> ChunkReceipt:
        return ChunkReceipt(index, duplicate, session.received_bytes, session.contiguous_offset)

    def _check_accepting(self, session: UploadSession) -> None:
        # The request path only refuses; collect_garbage() owns the EXPIRED
        # transition and the storage cleanup, so neither can be skipped.
        if session.status is UploadState.EXPIRED or \
                (session.status.accepts_chunks and session.expires_at <= self._clock()):
            raise UploadExpiredError(session.upload_id)
        if not session.status.accepts_chunks:
            raise InvalidStateError(f"upload is {session.status.value}")

    # ── HEAD /uploads/{id}  and  GET /uploads/{id} ────────────────────
    async def get_offset(self, upload_id: str) -> int:
        """TUS-style resume point for a sequential client: the contiguous prefix."""
        return self._repo.get(upload_id).contiguous_offset

    async def missing_chunks(self, upload_id: str) -> List[int]:
        """Resume point for a parallel client: exactly the chunks still needed."""
        return self._repo.get(upload_id).missing_chunks()

    async def get_status(self, upload_id: str) -> Dict[str, object]:
        s = self._repo.get(upload_id)
        return {"upload_id": s.upload_id, "status": s.status.value, "filename": s.filename,
                "size": s.file_size, "chunk_size": s.chunk_size,
                "chunks_received": len(s.chunks), "chunks_total": s.total_chunks,
                "progress_percent": round(s.progress_percent(), 1),
                "contiguous_offset": s.contiguous_offset, "error": s.error}

    # ── POST /uploads/{id}/complete ───────────────────────────────────
    async def complete(self, upload_id: str) -> UploadSession:
        session = self._repo.get(upload_id)
        lock = self._locks[upload_id]
        async with lock:
            if session.status in (UploadState.COMPLETED, UploadState.READY, UploadState.QUARANTINED):
                return session                       # idempotent: the client retried complete
            self._check_accepting(session)
            if session.inflight:
                raise ChunkInProgressError(f"chunks still being written: {sorted(session.inflight)}")
            missing = session.missing_chunks()
            if missing:
                raise IncompleteUploadError(missing)
            self._transition(session, UploadState.ASSEMBLING)   # blocks chunk writes + 2nd complete

        # Verify + compose without the lock: ASSEMBLING already keeps chunk
        # writes, cancel and a second complete() out.
        try:
            ordered = [session.chunks[i] for i in range(session.total_chunks)]
            whole = hashlib.sha256()
            corrupted = []
            for chunk in ordered:
                data = await self._storage.get_chunk(chunk.storage_key)
                if sha256_hex(data) != chunk.sha256:
                    corrupted.append(chunk.index)
                whole.update(data)
            digest = whole.hexdigest()

            if corrupted:
                # Bytes changed at rest. Forget those chunks; the client re-sends them.
                async with lock:
                    for i in corrupted:
                        del session.chunks[i]
                    self._transition(session, UploadState.IN_PROGRESS)
                raise ChunkCorruptedError(corrupted)

            if session.expected_sha256 and digest != session.expected_sha256:
                # Every chunk matched its own hash, so the client sent the wrong
                # file (or the wrong hash). Not recoverable by re-sending chunks.
                async with lock:
                    session.error = "whole-file sha256 mismatch"
                    self._transition(session, UploadState.FAILED)
                    self._limiter.finish_upload(session.user_id, upload_id, refund=session.file_size)
                await self._storage.delete_prefix(session.temp_prefix)
                raise ChecksumMismatchError(f"file sha256 {digest} != expected {session.expected_sha256}")

            final_key = f"files/{upload_id}"
            await self._storage.compose(final_key, [c.storage_key for c in ordered])
        except (ChunkCorruptedError, ChecksumMismatchError):
            raise
        except BaseException:
            # Storage error (or cancellation) mid-assembly: chunks are intact,
            # so go back to IN_PROGRESS and let the client retry complete().
            async with lock:
                if session.status is UploadState.ASSEMBLING:
                    self._transition(session, UploadState.IN_PROGRESS)
            raise

        async with lock:
            session.final_key, session.final_sha256 = final_key, digest
            self._transition(session, UploadState.COMPLETED)
            self._limiter.finish_upload(session.user_id, upload_id)
        await self._storage.delete_prefix(session.temp_prefix)     # best effort; GC/lifecycle as backstop

        # Hooks run after the state is committed. In production this is an
        # outbox row written in the same transaction, relayed to Kafka.
        for hook in self._hooks:
            try:
                await hook(session)
            except Exception:
                logger.exception("completion hook failed for %s", upload_id)
        return session

    # ── DELETE /uploads/{id} ──────────────────────────────────────────
    async def cancel(self, upload_id: str) -> bool:
        session = self._repo.get(upload_id)
        async with self._locks[upload_id]:
            if not session.status.accepts_chunks:
                return False
            if session.inflight:
                raise ChunkInProgressError("chunk writes in flight; retry the cancel")
            self._transition(session, UploadState.CANCELLED)
            self._limiter.finish_upload(session.user_id, upload_id, refund=session.file_size)
        await self._storage.delete_prefix(session.temp_prefix)     # state already final; no lock needed
        return True

    # ── virus-scan callback ───────────────────────────────────────────
    async def record_scan_result(self, upload_id: str, clean: bool) -> None:
        session = self._repo.get(upload_id)
        async with self._locks[upload_id]:
            self._transition(session, UploadState.READY if clean else UploadState.QUARANTINED)

    # ── garbage collection ────────────────────────────────────────────
    async def collect_garbage(self) -> List[str]:
        """Expire uploads with no activity for session_ttl. Run periodically."""
        expired = []
        for session in self._repo.expired(self._clock()):
            async with self._locks[session.upload_id]:
                if session.status.accepts_chunks and not session.inflight \
                        and session.expires_at <= self._clock():
                    self._expire(session)
                    expired.append(session.upload_id)
            if session.upload_id in expired:
                await self._storage.delete_prefix(session.temp_prefix)
        return expired

    def _expire(self, session: UploadSession) -> None:
        self._transition(session, UploadState.EXPIRED)
        self._limiter.finish_upload(session.user_id, session.upload_id, refund=session.file_size)

    @staticmethod
    def _transition(session: UploadSession, new: UploadState) -> None:
        if new not in _TRANSITIONS.get(session.status, set()):
            raise InvalidStateError(f"{session.upload_id}: {session.status.value} -> {new.value}")
        logger.info("upload %s: %s -> %s", session.upload_id, session.status.value, new.value)
        session.status = new


# ════════════════════════════════════════════════════════════════════════
#  CLIENT — chunking, bounded parallelism, retries, resume
# ════════════════════════════════════════════════════════════════════════

class TransientNetworkError(Exception):
    """A dropped connection or timeout: the client should retry."""


class ClientCrashed(Exception):
    """Demo/test only: the client process died mid-upload. Not retryable."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0

    def delay(self, attempt: int, rng: random.Random) -> float:
        return rng.uniform(0, min(self.max_delay, self.base_delay * 2 ** (attempt - 1)))   # full jitter


_RETRYABLE = (TransientNetworkError, RateLimitedError, ChunkInProgressError)


class UploadClient:
    """
    `api` is anything with the UploadService methods: the service itself in
    tests, an HTTP client in real life. Uploads at most `concurrency` chunks at
    a time. A chunk that keeps failing raises, but the upload stays resumable:
    call upload() again with the same upload_id and only missing chunks are sent.
    """

    def __init__(self, api, user_id: str, *, concurrency: int = 4,
                 retry: RetryPolicy = RetryPolicy(), rng: Optional[random.Random] = None) -> None:
        self._api = api
        self._user_id = user_id
        self._concurrency = concurrency
        self._retry = retry
        self._rng = rng or random.Random()
        self.chunks_sent = 0                       # successful chunk PUTs by this client
        self.last_upload_id: Optional[str] = None  # persist this to resume after a crash

    async def upload(self, data: bytes, filename: str, mime_type: str = "application/octet-stream", *,
                     upload_id: Optional[str] = None, chunk_size: Optional[int] = None) -> UploadSession:
        if upload_id is None:
            session = await self._api.initiate(self._user_id, filename, len(data), mime_type,
                                               sha256=sha256_hex(data), preferred_chunk_size=chunk_size)
            self.last_upload_id = upload_id = session.upload_id
            todo = list(range(session.total_chunks))
            size = session.chunk_size
        else:
            self.last_upload_id = upload_id
            status = await self._api.get_status(upload_id)
            todo = await self._api.missing_chunks(upload_id)     # resume: ask, don't assume
            size = int(status["chunk_size"])

        for _ in range(3):                         # re-send rounds for corrupted chunks
            await self._send_all(upload_id, data, size, todo)
            try:
                return await self._api.complete(upload_id)
            except ChunkCorruptedError as exc:
                todo = exc.chunks
        raise UploadError("chunks kept failing verification")

    async def _send_all(self, upload_id: str, data: bytes, size: int, indices: List[int]) -> None:
        sem = asyncio.Semaphore(self._concurrency)

        async def one(i: int) -> None:
            async with sem:
                await self._send_with_retry(upload_id, i, data[i * size:(i + 1) * size])

        results = await asyncio.gather(*(one(i) for i in indices), return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise errors[0]

    async def _send_with_retry(self, upload_id: str, index: int, chunk: bytes) -> None:
        digest = sha256_hex(chunk)
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                await self._api.upload_chunk(upload_id, index, chunk, digest)
                self.chunks_sent += 1
                return
            except _RETRYABLE as exc:
                if attempt == self._retry.max_attempts:
                    raise
                wait = self._retry.delay(attempt, self._rng)
                if isinstance(exc, RateLimitedError):
                    wait = max(wait, exc.retry_after)   # honour Retry-After
                await asyncio.sleep(wait)


# ════════════════════════════════════════════════════════════════════════
#  DEMO
# ════════════════════════════════════════════════════════════════════════

class FlakyNetwork:
    """Wraps the service; drops chosen chunk requests, and can 'crash' the client."""

    def __init__(self, service: UploadService, drop: Dict[int, int], crash_after: Optional[int] = None) -> None:
        self._service = service
        self._drop = dict(drop)                    # chunk index -> how many times to drop it
        self._crash_after = crash_after
        self.delivered = 0

    def __getattr__(self, name):
        return getattr(self._service, name)

    async def upload_chunk(self, upload_id, index, data, sha256):
        if self._crash_after is not None and self.delivered >= self._crash_after:
            raise ClientCrashed("client process killed")
        if self._drop.get(index, 0) > 0:
            self._drop[index] -= 1
            raise TransientNetworkError(f"connection reset on chunk {index}")
        receipt = await self._service.upload_chunk(upload_id, index, data, sha256)
        self.delivered += 1
        return receipt


async def _demo() -> None:
    policy = UploadPolicy(min_chunk_size=64 * KIB, default_chunk_size=64 * KIB,
                          max_file_size=10 * MIB, bandwidth_burst_bytes=1 * MIB)
    data = random.Random(42).randbytes(1_000_000)        # ~16 chunks of 64 KiB
    scanned: List[str] = []

    # In-memory storage + zero retry delay keep the demo output deterministic;
    # the tests exercise LocalChunkStorage against real files.
    storage = InMemoryChunkStorage()
    service = UploadService(storage, policy=policy)

    async def virus_scan(session: UploadSession) -> None:
        scanned.append(session.upload_id)
        await service.record_scan_result(session.upload_id, clean=True)

    service.on_completed(virus_scan)
    print("=" * 64)
    print("  BIG FILE UPLOAD DEMO  (1,000,000 bytes, 64 KiB chunks)")
    print("=" * 64)

    # 1. Flaky network (chunk 3 dropped twice, chunk 7 once); the client process dies once
    #    9 chunks are acknowledged. Requests already in flight still land on the server.
    net = FlakyNetwork(service, drop={3: 2, 7: 1}, crash_after=9)
    client = UploadClient(net, "alice", concurrency=4,
                          retry=RetryPolicy(base_delay=0), rng=random.Random(1))
    try:
        await client.upload(data, "dataset.bin")
    except ClientCrashed:
        pass
    upload_id = client.last_upload_id          # a real client persists this (e.g. localStorage)
    status = await service.get_status(upload_id)
    missing = await service.missing_chunks(upload_id)
    print(f"1. client crashed: {status['chunks_received']}/{status['chunks_total']} chunks stored, "
          f"status={status['status']}, {len(missing)} missing")

    # 2. A new client process resumes: it asks the server what's missing.
    resumed = UploadClient(service, "alice", concurrency=4, rng=random.Random(2))
    session = await resumed.upload(data, "dataset.bin", upload_id=upload_id)
    print(f"2. resumed: sent only {resumed.chunks_sent} chunks, status={session.status.value}")

    stored = await storage.read_object(session.final_key)
    print(f"3. stored file intact: {stored == data}, sha256 verified: {session.final_sha256 == sha256_hex(data)}")
    print(f"4. virus-scan hook ran: {scanned == [session.upload_id]}, "
          f"active uploads for alice: {service.limiter.active_uploads('alice')}")

    # 3. Idempotent retry and a conflicting re-send.
    s2 = await service.initiate("alice", "small.txt", 10, "text/plain")
    r1 = await service.upload_chunk(s2.upload_id, 0, b"0123456789", sha256_hex(b"0123456789"))
    r2 = await service.upload_chunk(s2.upload_id, 0, b"0123456789", sha256_hex(b"0123456789"))
    try:
        await service.upload_chunk(s2.upload_id, 0, b"XXXXXXXXXX", sha256_hex(b"XXXXXXXXXX"))
    except ChunkConflictError:
        conflict = "rejected"
    print(f"5. same chunk twice: duplicate={r2.duplicate} (first={r1.duplicate}); "
          f"different bytes for it: {conflict}")

    # 4. Policy: a 100 GiB file needs chunks above the 5 MiB S3 minimum.
    big = UploadPolicy().chunk_size_for(100 * GIB, preferred=5 * MIB)
    print(f"6. chunk size for 100 GiB: {big / MIB:.2f} MiB "
          f"({math.ceil(100 * GIB / big)} parts <= 10,000)")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
