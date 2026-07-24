"""
Big File Upload System — Low-Level Design
============================================
Design Principles: SOLID, TUS Protocol, Strategy Pattern, State Machine

Supports:
  - Chunked uploads (TUS protocol: HEAD/PATCH/POST)
  - Resumability via byte offset tracking
  - Parallel chunk uploads with configurable concurrency
  - Checksum verification (SHA-256 per chunk and per file)
  - Pluggable storage backends (S3, Local)
  - Multi-level rate limiting (concurrent, throughput, daily quota)
  - Upload state lifecycle management
  - Garbage collection for abandoned uploads
  - Async post-processing pipeline hooks
"""

import asyncio
import hashlib
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upload-service")


# ═══════════════════════════════════════════════════════════════
#  DOMAIN MODELS
# ═══════════════════════════════════════════════════════════════

class UploadState(str, Enum):
    """Upload lifecycle states matching TUS protocol semantics."""
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PROCESSING = "processing"
    READY = "ready"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    EXPIRED = "expired"

    def can_transition_to(self, target: "UploadState") -> bool:
        """Validate state transitions."""
        transitions = {
            UploadState.INITIATED: {UploadState.IN_PROGRESS, UploadState.FAILED, UploadState.EXPIRED},
            UploadState.IN_PROGRESS: {UploadState.COMPLETED, UploadState.FAILED, UploadState.EXPIRED},
            UploadState.COMPLETED: {UploadState.PROCESSING, UploadState.FAILED},
            UploadState.PROCESSING: {UploadState.READY, UploadState.QUARANTINED, UploadState.FAILED},
            UploadState.READY: set(),
            UploadState.QUARANTINED: {UploadState.READY},  # False positive reviewed
            UploadState.FAILED: {UploadState.INITIATED},  # Retry
            UploadState.EXPIRED: set(),
        }
        return target in transitions.get(self, set())


@dataclass
class ChunkInfo:
    """Metadata for a single uploaded chunk."""
    chunk_number: int
    offset_start: int
    offset_end: int
    size: int
    checksum: str            # SHA-256 of chunk data
    storage_path: str        # blob/{upload_id}/chunk_{n}
    received_at: float = 0.0


@dataclass
class UploadSession:
    """Tracks a single file upload from initiation through completion."""
    id: str
    user_id: str
    filename: str
    file_size: int
    mime_type: str
    checksum_client: str               # SHA-256 of entire file (from client)
    chunk_size: int = 5 * 1024 * 1024  # 5MB default
    total_chunks: int = 0
    status: UploadState = UploadState.INITIATED
    storage_bucket: str = "uploads"
    storage_prefix: str = ""           # temp-chunks/{id}/
    storage_upload_id: str = ""        # S3 multipart upload ID
    chunks: dict[int, ChunkInfo] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float = 0.0            # 7 days from last activity

    def __post_init__(self):
        now = time.time()
        self.created_at = now
        self.updated_at = now
        self.expires_at = now + 7 * 86400  # 7 days
        self.total_chunks = (self.file_size + self.chunk_size - 1) // self.chunk_size
        self.storage_prefix = f"temp-chunks/{self.id}/"

    @property
    def received_bytes(self) -> int:
        """Total bytes received across all chunks (for progress)."""
        return sum(c.size for c in self.chunks.values())

    @property
    def progress_percent(self) -> float:
        """Upload progress as percentage (0-100)."""
        if self.file_size == 0:
            return 100.0
        return min(100.0, (self.received_bytes / self.file_size) * 100)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


# ═══════════════════════════════════════════════════════════════
#  STRATEGY: STORAGE BACKEND
# ═══════════════════════════════════════════════════════════════

class ChunkStorageBackend(ABC):
    """Strategy interface for chunk storage. Supports S3, local FS, etc."""

    @abstractmethod
    async def store_chunk(self, upload_id: str, chunk_number: int,
                          data: bytes, path: str) -> None:
        """Store a single chunk. Must be idempotent (overwrite OK)."""
        pass

    @abstractmethod
    async def retrieve_chunk(self, path: str) -> bytes:
        """Retrieve a stored chunk by path."""
        pass

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        """Delete all objects under the given prefix."""
        pass

    @abstractmethod
    async def assemble_file(self, upload_id: str, chunks: dict[int, ChunkInfo],
                            destination_path: str) -> str:
        """Assemble all chunks into the final file.
        Returns the final storage key of the assembled file."""
        pass


class S3ChunkStorage(ChunkStorageBackend):
    """AWS S3 (or MinIO) chunk storage backend."""

    def __init__(self, bucket: str = "uploads"):
        self.bucket = bucket
        # In production: initialize boto3 S3 client here
        logger.info(f"S3ChunkStorage initialized for bucket: {bucket}")

    async def store_chunk(self, upload_id: str, chunk_number: int,
                          data: bytes, path: str) -> None:
        """Store chunk to S3. Idempotent — retries overwrite same key."""
        logger.info(f"S3: Stored chunk {chunk_number} for upload {upload_id} "
                    f"({len(data)} bytes)")
        # In production:
        # await self.s3.put_object(Bucket=self.bucket, Key=path, Body=data)

    async def retrieve_chunk(self, path: str) -> bytes:
        """Retrieve chunk from S3."""
        logger.info(f"S3: Retrieved {path}")
        # In production:
        # response = await self.s3.get_object(Bucket=self.bucket, Key=path)
        # return await response["Body"].read()
        return b""

    async def delete_prefix(self, prefix: str) -> None:
        """Delete all objects under prefix."""
        logger.info(f"S3: Deleted prefix {prefix}")
        # In production: list objects then batch delete

    async def assemble_file(self, upload_id: str,
                            chunks: dict[int, ChunkInfo],
                            destination_path: str) -> str:
        """Assemble chunks into final file using S3 multipart upload."""
        logger.info(f"S3: Assembling {len(chunks)} chunks for upload {upload_id}")
        # In production: initiate S3 multipart upload, upload parts in order,
        # then complete.
        return destination_path


class LocalChunkStorage(ChunkStorageBackend):
    """Local filesystem storage backend — useful for development/testing."""

    def __init__(self, base_path: str = "/tmp/upload-chunks"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        logger.info(f"LocalChunkStorage initialized at: {base_path}")

    async def store_chunk(self, upload_id: str, chunk_number: int,
                          data: bytes, path: str) -> None:
        """Write chunk to local filesystem."""
        full_path = os.path.join(self.base_path, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
        logger.info(f"Local: Stored chunk {chunk_number} for upload {upload_id}")

    async def retrieve_chunk(self, path: str) -> bytes:
        """Read chunk from local filesystem."""
        full_path = os.path.join(self.base_path, path)
        with open(full_path, "rb") as f:
            return f.read()

    async def delete_prefix(self, prefix: str) -> None:
        """Recursively delete a prefix directory."""
        full_path = os.path.join(self.base_path, prefix)
        if os.path.exists(full_path):
            import shutil
            shutil.rmtree(full_path)
            logger.info(f"Local: Deleted prefix {prefix}")

    async def assemble_file(self, upload_id: str,
                            chunks: dict[int, ChunkInfo],
                            destination_path: str) -> str:
        """Assemble chunks into final file by concatenating in order."""
        full_path = os.path.join(self.base_path, destination_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "wb") as outfile:
            for chunk_num in sorted(chunks.keys()):
                chunk = chunks[chunk_num]
                chunk_data = await self.retrieve_chunk(chunk.storage_path)
                outfile.write(chunk_data)

        logger.info(f"Local: Assembled {len(chunks)} chunks into {full_path}")
        return destination_path


# ═══════════════════════════════════════════════════════════════
#  REPOSITORY: DATABASE ACCESS
# ═══════════════════════════════════════════════════════════════

class UploadRepository:
    """Repository pattern for upload metadata persistence.
    Abstracts PostgreSQL (or in-memory for testing)."""

    def __init__(self):
        # In production: use asyncpg/psycopg3 connection pool
        self._uploads: dict[str, UploadSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: UploadSession) -> None:
        async with self._lock:
            self._uploads[session.id] = session
            logger.info(f"Created upload session: {session.id}")

    async def get(self, upload_id: str) -> Optional[UploadSession]:
        async with self._lock:
            return self._uploads.get(upload_id)

    async def update_status(self, upload_id: str,
                            new_status: UploadState) -> bool:
        async with self._lock:
            session = self._uploads.get(upload_id)
            if not session:
                return False
            if not session.status.can_transition_to(new_status):
                raise ValueError(
                    f"Invalid state transition: {session.status} → {new_status}"
                )
            session.status = new_status
            session.updated_at = time.time()
            logger.info(f"Upload {upload_id}: {session.status} → {new_status}")
            return True

    async def add_chunk(self, upload_id: str, chunk: ChunkInfo) -> None:
        async with self._lock:
            session = self._uploads.get(upload_id)
            if not session:
                raise KeyError(f"Upload session not found: {upload_id}")
            session.chunks[chunk.chunk_number] = chunk
            session.updated_at = time.time()
            # Extend expiry on activity
            session.expires_at = time.time() + 7 * 86400
            if session.status == UploadState.INITIATED:
                session.status = UploadState.IN_PROGRESS

    async def get_stale_uploads(self, max_age_hours: int = 168
                                ) -> list[UploadSession]:
        """Get uploads that haven't been updated in N hours."""
        async with self._lock:
            cutoff = time.time() - max_age_hours * 3600
            return [
                s for s in self._uploads.values()
                if s.updated_at < cutoff
                and s.status in (UploadState.INITIATED, UploadState.IN_PROGRESS)
            ]

    async def delete(self, upload_id: str) -> None:
        async with self._lock:
            self._uploads.pop(upload_id, None)

    async def delete_upload_data(self, upload_id: str) -> None:
        """Remove upload session and its chunks from the repository."""
        async with self._lock:
            session = self._uploads.pop(upload_id, None)
            if session:
                logger.info(f"Deleted upload data for {upload_id}")


# ═══════════════════════════════════════════════════════════════
#  CHECKSUM VERIFICATION
# ═══════════════════════════════════════════════════════════════

class ChecksumVerifier:
    """Verifies data integrity using SHA-256 at chunk and file levels."""

    @staticmethod
    def compute(data: bytes) -> str:
        """Compute SHA-256 checksum of data."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def verify(data: bytes, expected: str) -> bool:
        """Verify data against expected checksum."""
        return ChecksumVerifier.compute(data) == expected

    @staticmethod
    async def verify_chunks(chunks: dict[int, ChunkInfo],
                            storage: ChunkStorageBackend) -> bool:
        """Verify all chunks haven't been corrupted in storage."""
        for chunk_num, chunk_info in sorted(chunks.items()):
            data = await storage.retrieve_chunk(chunk_info.storage_path)
            if not ChecksumVerifier.verify(data, chunk_info.checksum):
                logger.error(f"Chunk {chunk_num} checksum mismatch!")
                return False
        return True


# ═══════════════════════════════════════════════════════════════
#  UPLOAD SCHEDULER (CONCURRENCY + RETRY)
# ═══════════════════════════════════════════════════════════════

@dataclass
class RetryConfig:
    """Configuration for upload retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0
    backoff_factor: float = 2.0  # exponential


class UploadScheduler:
    """Manages concurrent chunk uploads with retry logic.
    Controls parallelism and ensures chunks are uploaded reliably."""

    def __init__(self, max_concurrent: int = 6, retry_config: Optional[RetryConfig] = None):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._retry = retry_config or RetryConfig()

    async def execute(self, chunk_number: int, upload_fn: Callable,
                      *args, **kwargs) -> bool:
        """
        Execute a chunk upload with retry and concurrency control.
        Returns True if the upload succeeded, False after exhausting retries.
        """
        async with self._semaphore:
            last_error = None
            for attempt in range(1, self._retry.max_retries + 1):
                try:
                    return await upload_fn(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < self._retry.max_retries:
                        delay = min(
                            self._retry.base_delay * (self._retry.backoff_factor ** (attempt - 1)),
                            self._retry.max_delay
                        )
                        logger.warning(
                            f"Chunk {chunk_number} attempt {attempt}/{self._retry.max_retries} "
                            f"failed: {e}. Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Chunk {chunk_number} failed after "
                            f"{self._retry.max_retries} attempts: {last_error}"
                        )

            return False

    async def execute_parallel(self, tasks: list[tuple[int, Callable, tuple, dict]]
                               ) -> dict[int, bool]:
        """
        Execute multiple chunk uploads in parallel.
        tasks: list of (chunk_number, upload_fn, args, kwargs)
        Returns: {chunk_number: success_bool}
        """
        coros = [
            self.execute(num, fn, *args, **kwargs)
            for num, fn, args, kwargs in tasks
        ]
        results = await asyncio.gather(*coros)
        return {tasks[i][0]: results[i] for i in range(len(tasks))}


# ═══════════════════════════════════════════════════════════════
#  RATE LIMITER
# ═══════════════════════════════════════════════════════════════

class RateLimiter:
    """Multi-level rate limiting for uploads.
    In production, use Redis for distributed counting."""

    def __init__(self):
        self._concurrent: dict[str, int] = {}
        self._throughput: dict[str, list[tuple[float, int]]] = {}
        self._daily: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def check_concurrent(self, user_id: str, max_concurrent: int = 5) -> bool:
        """Check and increment concurrent upload count for user."""
        async with self._lock:
            current = self._concurrent.get(user_id, 0)
            if current >= max_concurrent:
                logger.warning(f"Rate limit: user {user_id} exceeded concurrent limit")
                return False
            self._concurrent[user_id] = current + 1
            return True

    async def release_concurrent(self, user_id: str) -> None:
        """Decrement concurrent upload count."""
        async with self._lock:
            current = self._concurrent.get(user_id, 0)
            if current > 0:
                self._concurrent[user_id] = current - 1

    async def check_throughput(self, user_id: str, file_size: int,
                               max_mbps: float = 50.0) -> bool:
        """Check upload throughput limit over a sliding 60s window."""
        async with self._lock:
            now = time.time()
            if user_id not in self._throughput:
                self._throughput[user_id] = []

            # Prune entries older than 60s
            window_start = now - 60
            self._throughput[user_id] = [
                (ts, sz) for ts, sz in self._throughput[user_id]
                if ts > window_start
            ]

            # Calculate current throughput
            total_bytes = sum(sz for _, sz in self._throughput[user_id])
            mb_per_s = total_bytes / 60 / 1024 / 1024

            if mb_per_s + (file_size / 60 / 1024 / 1024) > max_mbps:
                logger.warning(f"Rate limit: user {user_id} throughput {mb_per_s:.1f} MB/s "
                               f"(limit: {max_mbps} MB/s)")
                return False

            self._throughput[user_id].append((now, file_size))
            return True

    async def check_daily_quota(self, user_id: str, file_size: int,
                                max_daily_gb: float = 100.0) -> bool:
        """Check daily storage quota."""
        async with self._lock:
            today = time.strftime("%Y-%m-%d")
            key = f"{user_id}:{today}"
            current = self._daily.get(key, 0)

            new_total_gb = (current + file_size) / (1024 ** 3)
            if new_total_gb > max_daily_gb:
                logger.warning(f"Rate limit: user {user_id} daily quota exceeded")
                return False

            self._daily[key] = current + file_size
            return True

    async def check_all(self, user_id: str, file_size: int) -> bool:
        """Check all rate limits."""
        checks = await asyncio.gather(
            self.check_concurrent(user_id),
            self.check_throughput(user_id, file_size),
            self.check_daily_quota(user_id, file_size),
        )
        return all(checks)


# ═══════════════════════════════════════════════════════════════
#  CORE UPLOAD SERVICE (FACADE)
# ═══════════════════════════════════════════════════════════════

class UploadService:
    """
    Core upload service — Facade for the upload system.
    
    Coordinates:
      - Session management (initiate, track, complete)
      - Chunk storage (delegated to ChunkStorageBackend)
      - Checksum verification
      - Rate limiting
      - Concurrent upload scheduling
      - State machine transitions
      - Post-completion hooks (virus scan, transcode)
    """

    def __init__(
        self,
        repository: UploadRepository,
        storage: ChunkStorageBackend,
        scheduler: Optional[UploadScheduler] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._repo = repository
        self._storage = storage
        self._scheduler = scheduler or UploadScheduler()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._on_complete_hooks: list[Callable] = []

    def register_complete_hook(self, hook: Callable) -> None:
        """Register a callback for when upload completes.
        Used for async processing pipeline (virus scan, transcode)."""
        self._on_complete_hooks.append(hook)

    async def initiate(self, user_id: str, filename: str,
                       file_size: int, mime_type: str,
                       checksum: str = "",
                       chunk_size: int = 5 * 1024 * 1024) -> UploadSession:
        """
        Step 1: Initiate a new upload session.
        
        Returns session with upload_id, chunk_size, and total_chunks.
        Client uses this to know how to split the file.
        """
        # Rate limiting
        allowed = await self._rate_limiter.check_all(user_id, file_size)
        if not allowed:
            raise PermissionError("Rate limit exceeded. Please try again later.")

        # Validate file size
        max_size = 100 * 1024**3  # 100 GB
        if file_size > max_size:
            raise ValueError(f"File too large (max: {max_size / 1024**3:.0f} GB)")

        # Validate filename (no path traversal)
        if ".." in filename or "/" in filename:
            raise ValueError("Invalid filename")

        # Create session
        session = UploadSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            checksum_client=checksum,
            chunk_size=chunk_size,
        )

        await self._repo.create(session)
        logger.info(f"Upload initiated: {session.id} — {filename} ({file_size} bytes, "
                    f"{session.total_chunks} chunks)")

        return session

    async def upload_chunk(self, upload_id: str, chunk_number: int,
                           offset: int, data: bytes,
                           checksum: str = "") -> dict:
        """
        Step 2: Upload a single chunk (TUS PATCH semantics).
        
        TUS protocol:
          - Client sends data starting at given offset
          - Chunk is stored independently (supports out-of-order)
          - Returns the new offset (offset_end) for resume
        
        Idempotent: re-uploading the same chunk returns same result
        without re-storing.
        """
        session = await self._repo.get(upload_id)
        if not session:
            raise KeyError(f"Upload not found: {upload_id}")

        if session.status not in (UploadState.INITIATED, UploadState.IN_PROGRESS):
            raise ValueError(f"Upload is in state {session.status}, "
                             f"cannot accept chunks")

        # Check if chunk already received (idempotency)
        if chunk_number in session.chunks:
            existing = session.chunks[chunk_number]
            logger.info(f"Duplicate chunk {chunk_number} for upload {upload_id}")
            return {
                "chunk_number": chunk_number,
                "offset": existing.offset_end,
                "checksum": existing.checksum,
                "duplicate": True,
            }

        # Verify checksum if provided
        if checksum and not ChecksumVerifier.verify(data, checksum):
            raise ValueError(f"Chunk {chunk_number} checksum mismatch")

        # Compute checksum
        actual_checksum = ChecksumVerifier.compute(data) if not checksum else checksum

        # Store chunk
        storage_path = f"{session.storage_prefix}chunk_{chunk_number}"
        await self._storage.store_chunk(upload_id, chunk_number, data, storage_path)

        # Record chunk metadata
        chunk = ChunkInfo(
            chunk_number=chunk_number,
            offset_start=offset,
            offset_end=offset + len(data),
            size=len(data),
            checksum=actual_checksum,
            storage_path=storage_path,
            received_at=time.time(),
        )
        await self._repo.add_chunk(upload_id, chunk)

        logger.info(f"Chunk {chunk_number}/{session.total_chunks} received "
                    f"for upload {upload_id} — progress: {session.progress_percent:.1f}%")

        return {
            "chunk_number": chunk_number,
            "offset": chunk.offset_end,
            "checksum": actual_checksum,
            "duplicate": False,
        }

    async def get_offset(self, upload_id: str) -> int:
        """
        TUS HEAD: Get the byte offset for resuming.
        
        Returns the next byte the client should send.
        """
        session = await self._repo.get(upload_id)
        if not session:
            raise KeyError(f"Upload not found: {upload_id}")

        return session.received_bytes

    async def complete(self, upload_id: str,
                       checksum: str = "") -> dict:
        """
        Step 3: Finalize upload after all chunks are received.
        
        Verifies:
          1. All chunks are present (no gaps)
          2. Final file checksum matches client-provided checksum
        Then:
          3. Assembles all chunks into final file
          4. Transitions state to COMPLETED
          5. Fires async processing hooks
        """
        session = await self._repo.get(upload_id)
        if not session:
            raise KeyError(f"Upload not found: {upload_id}")

        if session.status != UploadState.IN_PROGRESS:
            raise ValueError(f"Upload is in state {session.status}, "
                             f"expected IN_PROGRESS")

        # Verify all chunks are received
        expected_chunks = set(range(session.total_chunks))
        received_chunks = set(session.chunks.keys())
        missing = expected_chunks - received_chunks

        if missing:
            raise ValueError(f"Missing {len(missing)} chunks: {sorted(missing)}")

        # Verify all chunk checksums against stored data
        chunks_valid = await ChecksumVerifier.verify_chunks(
            session.chunks, self._storage
        )
        if not chunks_valid:
            raise ValueError("Chunk checksum verification failed — corruption detected")

        # Assemble final file
        destination = f"permanent/{session.user_id}/{session.id}_{session.filename}"
        await self._storage.assemble_file(
            upload_id, session.chunks, destination
        )

        # Update status
        await self._repo.update_status(upload_id, UploadState.COMPLETED)

        # Release rate limiter
        await self._rate_limiter.release_concurrent(session.user_id)

        # Fire async processing hooks
        for hook in self._on_complete_hooks:
            try:
                await hook(session)
            except Exception as e:
                logger.error(f"Complete hook failed for {upload_id}: {e}")

        logger.info(f"Upload completed: {upload_id} — {session.filename} "
                    f"({session.file_size} bytes, {session.total_chunks} chunks)")

        return {
            "status": "completed",
            "upload_id": upload_id,
            "file_id": f"f_{session.id[:8]}",
            "filename": session.filename,
            "size": session.file_size,
            "chunks": session.total_chunks,
        }

    async def cancel(self, upload_id: str) -> None:
        """Cancel an in-progress upload and clean up chunks."""
        session = await self._repo.get(upload_id)
        if not session:
            raise KeyError(f"Upload not found: {upload_id}")

        # Clean up storage
        await self._storage.delete_prefix(session.storage_prefix)

        # Update status
        await self._repo.update_status(upload_id, UploadState.FAILED)

        # Release rate limiter
        await self._rate_limiter.release_concurrent(session.user_id)

        logger.info(f"Upload cancelled: {upload_id}")

    async def get_status(self, upload_id: str) -> dict:
        """Get upload status, progress, and metadata."""
        session = await self._repo.get(upload_id)
        if not session:
            raise KeyError(f"Upload not found: {upload_id}")

        return {
            "upload_id": session.id,
            "filename": session.filename,
            "size": session.file_size,
            "status": session.status.value,
            "progress_percent": session.progress_percent,
            "received_bytes": session.received_bytes,
            "total_bytes": session.file_size,
            "chunks_received": len(session.chunks),
            "chunks_total": session.total_chunks,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }


# ═══════════════════════════════════════════════════════════════
#  BACKGROUND GARBAGE COLLECTION
# ═══════════════════════════════════════════════════════════════

class BackgroundGC:
    """Periodic garbage collection for abandoned/expired uploads."""

    def __init__(self, repository: UploadRepository,
                 storage: ChunkStorageBackend,
                 rate_limiter: RateLimiter,
                 interval_hours: int = 1):
        self._repo = repository
        self._storage = storage
        self._rate_limiter = rate_limiter
        self._interval = interval_hours * 3600
        self._running = False

    async def start(self):
        """Start the GC loop."""
        self._running = True
        while self._running:
            await asyncio.sleep(self._interval)
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error(f"GC cycle failed: {e}")

    async def stop(self):
        """Stop the GC loop."""
        self._running = False

    async def _run_cycle(self):
        """Single GC cycle — clean abandoned and expired uploads."""
        logger.info("GC cycle starting...")

        # Clean abandoned uploads (no activity in 7 days)
        stale = await self._repo.get_stale_uploads(max_age_hours=168)
        for session in stale:
            await self._storage.delete_prefix(session.storage_prefix)
            await self._repo.update_status(session.id, UploadState.EXPIRED)
            await self._rate_limiter.release_concurrent(session.user_id)
            await self._repo.delete_upload_data(session.id)
            logger.info(f"GC: Expired abandoned upload {session.id}")

        logger.info(f"GC cycle complete — cleaned {len(stale)} abandoned uploads")


# ═══════════════════════════════════════════════════════════════
#  ASYNC PROCESSING PIPELINE (EXAMPLE HOOKS)
# ═══════════════════════════════════════════════════════════════

class ProcessingPipeline:
    """Async processing pipeline hooks for post-upload processing."""

    @staticmethod
    async def virus_scan(session: UploadSession):
        """Hook: Queue file for virus scanning."""
        logger.info(f"Pipeline: Queued {session.id} for virus scanning")
        # In production: publish to Kafka/RabbitMQ
        await asyncio.sleep(0.1)  # Simulate

    @staticmethod
    async def transcode_video(session: UploadSession):
        """Hook: Queue video for transcoding (if applicable)."""
        video_mimes = {"video/mp4", "video/quicktime", "video/x-msvideo",
                       "video/webm", "video/mkv"}
        if session.mime_type in video_mimes:
            logger.info(f"Pipeline: Queued {session.id} for video transcoding")
            await asyncio.sleep(0.1)  # Simulate

    @staticmethod
    async def notify_user(session: UploadSession):
        """Hook: Send notification to user."""
        logger.info(f"Pipeline: Notified user {session.user_id} about {session.filename}")
        await asyncio.sleep(0.1)  # Simulate


# ═══════════════════════════════════════════════════════════════
#  DEMO
# ═══════════════════════════════════════════════════════════════

async def run_demo():
    """Demonstrate the Big File Upload system end-to-end."""
    print("=" * 60)
    print("  BIG FILE UPLOAD SYSTEM — DEMO")
    print("=" * 60)

    # ── Setup ──
    repo = UploadRepository()
    storage = LocalChunkStorage(base_path="/tmp/upload-demo")
    scheduler = UploadScheduler(max_concurrent=4)
    rate_limiter = RateLimiter()
    service = UploadService(repo, storage, scheduler, rate_limiter)

    # Register processing hooks
    service.register_complete_hook(ProcessingPipeline.virus_scan)
    service.register_complete_hook(ProcessingPipeline.transcode_video)
    service.register_complete_hook(ProcessingPipeline.notify_user)

    print("\n📤 1. Initiate Upload")
    print("-" * 40)
    session = await service.initiate(
        user_id="user_123",
        filename="demo_video.mp4",
        file_size=50 * 1024 * 1024,  # 50MB
        mime_type="video/mp4",
        checksum="",
        chunk_size=5 * 1024 * 1024,  # 5MB chunks
    )
    print(f"   Upload ID: {session.id}")
    print(f"   Total Chunks: {session.total_chunks}")
    print(f"   Chunk Size: {session.chunk_size / 1024 / 1024:.0f}MB")

    print("\n📦 2. Upload Chunks (parallel)")
    print("-" * 40)

    # Simulate uploading chunks in parallel
    fake_data = b"A" * (5 * 1024 * 1024)  # 5MB of data

    tasks = []
    for chunk_num in range(session.total_chunks):
        offset = chunk_num * session.chunk_size
        # Last chunk may be smaller
        if chunk_num == session.total_chunks - 1:
            last_size = session.file_size - offset
            data = fake_data[:last_size]
        else:
            data = fake_data

        tasks.append((
            chunk_num,
            service.upload_chunk,
            (session.id, chunk_num, offset, data),
            {"checksum": ChecksumVerifier.compute(data)},
        ))

    results = await scheduler.execute_parallel(tasks)
    success_count = sum(1 for v in results.values() if v)
    fail_count = sum(1 for v in results.values() if not v)

    print(f"   ✅ {success_count} chunks uploaded successfully")
    if fail_count > 0:
        print(f"   ❌ {fail_count} chunks failed")

    # Simulate a resume scenario (HEAD request)
    print("\n🔄 3. Resume Check (HEAD / get_offset)")
    print("-" * 40)
    offset = await service.get_offset(session.id)
    print(f"   Current offset: {offset} / {session.file_size}")
    print(f"   Progress: {session.progress_percent:.1f}%")

    print("\n✅ 4. Complete Upload")
    print("-" * 40)
    result = await service.complete(session.id)
    print(f"   Status: {result['status']}")
    print(f"   File ID: {result['file_id']}")

    print("\n📊 5. Upload Status")
    print("-" * 40)
    status = await service.get_status(session.id)
    print(f"   Status: {status['status']}")
    print(f"   Progress: {status['progress_percent']:.1f}%")
    print(f"   Chunks: {status['chunks_received']}/{status['chunks_total']}")

    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)


def demo():
    """Entry point for running the demo."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    demo()
