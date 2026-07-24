# 📋 Big File Upload — Staff-Level Interview Questions

> *12 questions covering upload architecture, resumability, async processing, and edge cases — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [System Design: Multi-GB Upload Service](#1-system-design-multi-gb-upload-service)
2. [Resumability & the TUS Protocol](#2-resumability--the-tus-protocol)
3. [Chunking Strategy & Parallelism](#3-chunking-strategy--parallelism)
4. [Security: Virus Scanning & File Validation](#4-security-virus-scanning--file-validation)
5. [Async Processing Pipeline](#5-async-processing-pipeline)
6. [Database Schema for Upload Tracking](#6-database-schema-for-upload-tracking)
7. [Pre-signed URLs vs Proxy Uploads](#7-pre-signed-urls-vs-proxy-uploads)
8. [Handling Concurrent Uploads & Rate Limiting](#8-handling-concurrent-uploads--rate-limiting)
9. [Checksum Verification & Data Integrity](#9-checksum-verification--data-integrity)
10. [Garbage Collection & Lifecycle Management](#10-garbage-collection--lifecycle-management)
11. [Download & CDN Delivery Strategy](#11-download--cdn-delivery-strategy)
12. [Monitoring & Debugging Upload Failures](#12-monitoring--debugging-upload-failures)

---

## 1. System Design: Multi-GB Upload Service

**Q:** *"Design a file upload service that supports files up to 100GB. Users must be able to resume interrupted uploads even after closing their browser. The system should serve 10K concurrent uploads with 99.9% durability. Walk me through the full architecture, from client to storage."*

**What They're Really Testing:** Whether you understand that uploading large files is fundamentally different from uploading small ones — you can't just do a simple `POST`. They want to see chunking, resumability, async processing, and direct-to-storage patterns.

### Answer

**Key Design Decisions:**

```yaml
1. Chunked Upload (required for files > 100MB)
   - Split file into 5MB chunks on client
   - Upload chunks in parallel (concurrency: 3-6)
   - Each chunk is independently verifiable (SHA-256)

2. Resumability via Offset Tracking
   - Client sends HEAD request to get last received offset
   - Server stores offset per upload in PostgreSQL
   - Client resumes from that offset (TUS Protocol pattern)

3. Direct-to-Storage (Pre-signed URLs)
   - Server generates time-limited pre-signed S3 URLs
   - Client uploads chunks directly to S3
   - Server only handles metadata (not file data)

4. Async Processing Pipeline
   - Completed uploads queued in Kafka
   - Virus scanning → Transcoding → Thumbnail generation
   - Notifications via WebSocket/Webhook
```

**Why This Architecture:**

```
Without chunking (naive approach):
  Client ──POST 100GB──► Server ──PUT 100GB──► S3
                          │
                          │ ⚠ Problem:
                          │  • 100GB in memory = crash
                          │  • 1 hour upload = timeout
                          │  • Network drop = restart from 0
                          │  • Server bandwidth = bottleneck

With chunking + pre-signed URLs (scalable approach):
  Client ──PATCH chunk_0──► S3 (direct, via pre-signed URL)
  Client ──PATCH chunk_1──► S3
  Client ──PATCH chunk_2──► S3
  Client ──PATCH chunk_N──► S3
  Client ──POST complete──► Server (only metadata)
  
  Benefits:
   • Server handles ZERO bytes of file data
   • Parallel uploads (speed)
   • Resume from last successful chunk
   • S3 handles durability (99.999999999%)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Chunking** | Explains WHY chunking is necessary (memory, retry granularity, parallelism) |
| **Pre-signed URLs** | Uses direct-to-storage to avoid server bottleneck |
| **Resumability** | Implements offset tracking via HEAD/PATCH (TUS pattern) |
| **Async pipeline** | Decouples upload from processing (virus scan, transcode) |
| **Scaling** | Identifies bottlenecks and shows how to scale each component |

---

## 2. Resumability & the TUS Protocol

**Q:** *"Walk me through the TUS resumable upload protocol. How does the client know where to resume? How does the server handle duplicate chunks on resume? How long should you keep incomplete uploads?"*

**What They're Really Testing:** Whether you understand the state-machine nature of resumable uploads — it's not just "save progress", it's about idempotency and offset management.

### Answer

**TUS Protocol State Machine:**

```
Client                                    Server
  │                                         │
  │──── POST /upload ──────────────────────►│  Create upload
  │    {filename, size, mime}               │  Returns upload_id
  │◄─── {upload_id, location}               │
  │                                         │
  │──── PATCH /upload/{id} ────────────────►│  Upload chunk 0
  │    Upload-Offset: 0                     │  (bytes 0-5242879)
  │    [5MB chunk data]                     │
  │◄─── Upload-Offset: 5242880              │  Confirm next offset
  │                                         │
  │ ═══ NETWORK DROP ═══                    │
  │                                         │
  │──── HEAD /upload/{id} ─────────────────►│  Check progress
  │◄─── Upload-Offset: 5242880              │  Server persisted offset
  │                                         │
  │──── PATCH /upload/{id} ────────────────►│  Resume from byte 5MB
  │    Upload-Offset: 5242880               │
  │    [5MB chunk data]                     │
  │◄─── Upload-Offset: 10485760             │
  │                                         │
  │ (repeat until all bytes sent)           │
  │                                         │
  │──── POST /upload/{id}/complete ────────►│  Finalize upload
  │◄─── {status: completed}                 │
```

**Duplicate Chunk Handling:**

```python
# Idempotency: chunks are uniquely identified by (upload_id, offset_start)
# If a chunk with the same upload_id AND same offset_start already exists:
#   → Skip storage (idempotent)
#   → Return the existing offset (don't advance)

async def receive_chunk(upload_id: str, offset: int, data: bytes):
    # Check if chunk was already received
    existing = await db.fetch_one("""
        SELECT offset_start, offset_end, checksum
        FROM chunks
        WHERE upload_id = $1 AND offset_start = $2
    """, upload_id, offset)

    if existing:
        # Client retried — confirm receipt without re-storing
        logger.info(f"Duplicate chunk received: {upload_id} @ {offset}")
        return {"offset": existing["offset_end"]}

    # New chunk — store it
    checksum = hashlib.sha256(data).hexdigest()
    await store_chunk(upload_id, offset, data)
    await db.execute("""
        INSERT INTO chunks (upload_id, chunk_number, offset_start, offset_end, size, checksum)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, upload_id, offset // CHUNK_SIZE, offset, offset + len(data), len(data), checksum)

    return {"offset": offset + len(data)}
```

**Abandoned Upload Retention:**

```yaml
Keep incomplete uploads for 7 days.
  - < 1 hour: user might be on a slow connection
  - < 24 hours: user might have closed laptop, will resume tomorrow
  - < 7 days: user on vacation, mobile data

After 7 days, DELETE chunks and mark as 'expired'.
  - Chunks cost money (S3 storage)
  - Unlikely user will resume after 7 days
  - Can send a notification: "Your upload has expired"

Edge case: What if user resumes on day 6?
  → Extend expiry by +7 days from last activity
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **HEAD/PATCH semantics** | Understands TUS protocol: HEAD gets offset, PATCH sends data from that offset |
| **Idempotency** | Handles duplicate chunks without corruption |
| **Expiry policy** | Has concrete retention period with justification |
| **Edge cases** | Mentions concurrent PATCH requests, overlap handling |

---

## 3. Chunking Strategy & Parallelism

**Q:** *"You need to upload a 50GB video file. How do you decide chunk size? How many parallel uploads should you allow? What happens when parallel chunks arrive out of order?"*

**What They're Really Testing:** Whether you understand the trade-offs in chunk sizing (network, memory, overhead) and can design for real-world network conditions.

### Answer

**Chunk Size Decision:**

```yaml
Factors affecting chunk size:
  1. Network MTU: ~1500 bytes (minimum)
  2. S3 multipart minimum: 5MB (except last chunk)
  3. Browser memory: 5MB chunks × 6 parallel = 30MB in-flight
  4. Retry granularity: smaller chunks = less re-transmit on failure
  5. HTTP overhead: more chunks = more HTTP requests = more latency

Recommendation:
  - Optimal chunk size: 5MB-10MB
  - For mobile/unreliable networks: 1MB-2MB
  - For high-bandwidth LAN: 50MB-100MB

Adaptive chunk sizing:
  Monitor upload speed and adjust:
    Speed > 50 Mbps → 10MB chunks
    Speed 10-50 Mbps → 5MB chunks
    Speed < 10 Mbps → 1MB chunks
```

**Parallelism Decision:**

```yaml
Browser connection limits per origin:
  - HTTP/1.1: 6 concurrent connections (Chrome)
  - HTTP/2: 100+ concurrent streams
  - HTTP/3: unlimited (QUIC)

Recommendation:
  - Max 3-6 parallel chunk uploads (balance speed vs reliability)
  - Use a chunk queue with configurable concurrency

The U-shape curve:
  Too few (1):     Slow, no parallelism benefit
  Optimal (3-6):   Good throughput, manageable retries
  Too many (50+):  Network congestion, TCP window collapse,
                   higher failure rate, server load spike
```

**Out-of-Order Chunk Handling:**

```python
# S3 multipart upload handles out-of-order natively
# You just need to track which part numbers have been received

class MultipartUploadManager:
    def __init__(self):
        self.received_parts: dict[int, PartInfo] = {}

    def record_part(self, part_number: int, etag: str, size: int):
        # Out-of-order is OK — S3 assembles by part_number
        self.received_parts[part_number] = PartInfo(
            part_number=part_number,
            etag=etag,
            size=size,
        )

    def complete_upload(self, upload_id: str) -> bool:
        # Verify ALL parts received (no gaps)
        expected_parts = set(range(1, self.total_parts + 1))
        received = set(self.received_parts.keys())

        missing = expected_parts - received
        if missing:
            logger.warning(f"Missing parts: {missing}")
            return False

        # Send parts in ascending order (S3 requirement)
        sorted_parts = [
            {"PartNumber": p, "ETag": self.received_parts[p].etag}
            for p in sorted(expected_parts)
        ]
        return s3_client.complete_multipart_upload(
            UploadId=upload_id,
            MultipartUpload={"Parts": sorted_parts},
        )
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Chunk sizing** | Explains trade-offs (MTU, memory, retry granularity, overhead) |
| **Parallelism limits** | Knows browser connection limits; recommends 3-6 parallel |
| **Out-of-order handling** | Can handle out-of-order chunks (S3 multipart order at complete time) |
| **Adaptive sizing** | Mentions adjusting chunk size based on network conditions |

---

## 4. Security: Virus Scanning & File Validation

**Q:** *"Design the security layer for a file upload system. How do you validate file types? How do you scan for viruses without blocking the upload completion? What do you do with infected files?"*

**What They're Really Testing:** Whether you understand that file upload is one of the most common attack vectors, and that security must be layered (not just one check).

### Answer

**Layered Security Approach:**

```yaml
Layer 1: Client-side (pre-upload)
  - File extension allowlist (not blocklist)
  - MIME type check (Content-Type header)
  - File size check (reject > 100GB immediately)
  - ⚠ Never trust client-side checks alone!

Layer 2: Server-side (at upload initiation)
  - Re-validate filename (no path traversal: "../etc/passwd")
  - Re-validate MIME type from header
  - Rate limit per user/IP

Layer 3: Magic Bytes (at first chunk)
  - Read first 512 bytes → match against known signatures
  - PDF: %PDF
  - JPEG: \xFF\xD8\xFF
  - PNG: \x89PNG
  - ZIP: PK\x03\x04
  - Reject if client claims "image/png" but magic bytes say "application/zip"

Layer 4: Virus Scan (async, post-completion)
  - ClamAV (open source) or commercial (McAfee, Sophos)
  - YARA rules for custom threat patterns
  - Quarantine infected files (not deleted — can be false positive)
```

**Async Scanning Flow:**

```
File Uploaded ──► Kafka: file.uploaded
                      │
                      ▼
                Virus Scanner Worker
                      │
              ┌───────┴───────┐
              ▼               ▼
           CLEAN            INFECTED
              │               │
              ▼               ▼
    Move to permanent     Move to quarantine
    bucket                 bucket
              │               │
              ▼               ▼
    Update file status    Notify security team
    = 'clean'             + flag user account
              │               │
              ▼               ▼
    Queue for transcode   Log infection details
```

**Handling Infected Files:**

```python
async def handle_infected_file(file_id: str, virus_name: str, user_id: str):
    # 1. Move file to quarantine
    quarantine_key = f"quarantine/{datetime.utcnow()}/{file_id}"
    await storage.copy(permanent_key, quarantine_key)
    await storage.delete(permanent_key)

    # 2. Update database
    await db.execute("""
        UPDATE files
        SET virus_status = 'infected',
            quarantine_reason = $1,
            quarantined_at = NOW()
        WHERE id = $2
    """, virus_name, file_id)

    # 3. Notify security team
    await security_alert.send({
        "type": "VIRUS_DETECTED",
        "file_id": file_id,
        "virus_name": virus_name,
        "user_id": user_id,
        "timestamp": datetime.utcnow(),
    })

    # 4. Flag user for review
    await db.execute("""
        UPDATE users
        SET flags = flags || ARRAY['uploaded_malware'],
            flag_reason = $1,
            flagged_at = NOW()
        WHERE id = $2
    """, f"Uploaded file with {virus_name}", user_id)
```

**False Positive Handling:**

```yaml
If a file is incorrectly flagged:
  - Admin can mark as "false_positive" → move from quarantine to permanent
  - Update ClamAV/YARA signatures to exclude
  - Log for future training data

False positive rate target: < 0.001%
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Layered security** | Multiple validation layers (client, server, magic bytes, virus scan) |
| **Async scanning** | Doesn't block the upload response on virus scan |
| **Quarantine strategy** | Never deletes infected files immediately (false positives) |
| **Magic bytes** | Knows to validate file content, not just headers |
| **User flagging** | Flags users who upload malware (fraud detection) |

---

## 5. Async Processing Pipeline

**Q:** *"After a 50GB video file is uploaded, it needs to be virus-scanned, transcoded to multiple resolutions, and thumbnails generated. Design the processing pipeline. How do you handle failures? What happens if transcoding takes 2 hours?"*

**What They're Really Testing:** Whether you understand that post-upload processing is a distributed workflow, not a synchronous operation. They want to see queues, state machines, and dead-letter handling.

### Answer

**Pipeline Architecture:**

```
Upload Complete
      │
      ▼
┌─────────────────┐
│  Kafka Topic:    │
│  file.uploaded   │
└────────┬─────────┘
         │
   ┌─────▼─────┐
   │ Virus      │── infected ──► Quarantine
   │ Scanner    │── clean ─────►
   └────────────┘               │
                          ┌─────▼─────┐
                          │ Format     │── unsupported ──► Dead Letter
                          │ Detector   │── video/mp4 ────►
                          └────────────┘                  │
                                                     ┌────▼────┐
                                                     │Transcoder│
                                                     │(FFmpeg)  │
                                                     └────┬────┘
                                               ┌───────────┼───────────┐
                                               ▼           ▼           ▼
                                          ┌────────┐ ┌────────┐ ┌────────┐
                                          │ 240p   │ │ 720p   │ │ 1080p  │
                                          │ HLS    │ │ HLS    │ │ HLS    │
                                          └────────┘ └────────┘ └────────┘
                                               │
                                          ┌────▼────┐
                                          │Thumbnail │
                                          │Generator │
                                          └────┬────┘
                                               │
                                          ┌────▼────┐
                                          │ Notifier │
                                          │(WebSocket│
                                          │+ Webhook)│
                                          └─────────┘
```

**State Machine per File:**

```python
class ProcessingStateMachine:
    STATES = {
        "pending": {"virus_scan", "format_detect"},
        "scanning": {"clean", "infected"},
        "transcoding": {"in_progress", "completed", "failed"},
        "ready": {},  # Terminal state
        "failed": {},  # Terminal state
        "quarantined": {},  # Terminal state
    }

    async def transition(self, file_id: str, from_state: str, to_state: str):
        async with self.lock(file_id):
            current = await db.fetch_val(
                "SELECT processing_status FROM files WHERE id = $1",
                file_id
            )
            if current != from_state:
                raise InvalidTransition(
                    f"Cannot transition from {current} to {to_state}"
                )
            if to_state not in self.STATES.get(from_state, set()):
                raise InvalidTransition(
                    f"Invalid transition: {from_state} → {to_state}"
                )
            await db.execute(
                "UPDATE files SET processing_status = $1 WHERE id = $2",
                to_state, file_id
            )
```

**Failure Handling:**

```yaml
Transient failures (retriable):
  - Transcoder OOM: retry on bigger instance (3 retries)
  - S3 download timeout: retry with backoff
  - Worker crash: message goes back to queue (Kafka auto-redeliver)

Permanent failures (dead-letter):
  - Corrupted video file (can't decode)
  - Unsupported codec (AV1 vs H.264)
  - File exceeds transcoding limits (8K video)

Dead Letter Queue handling:
  → Move to DLQ
  → Alert on-call engineer
  → Store original file (don't delete!)
  → Manual review / re-process with different config
```

**Long-Running Transcoding (>2 hours):**

```yaml
Time estimate for 50GB video (H.264 → HLS):
  - 1080p: ~60 min
  - 720p: ~30 min
  - 480p: ~15 min
  - Total: ~105 min

If > 2 hours:
  1. Show progress to user (WebSocket: "Transcoding: 60%")
  2. Allow download of original file while transcoding
  3. Send push notification when transcoding completes
  4. Consider splitting into segments for parallel transcoding
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Queue-based pipeline** | Uses Kafka/RabbitMQ for decoupling |
| **State machine** | Defines clear states and valid transitions |
| **Dead-letter handling** | Separates retriable vs permanent failures |
| **Progress feedback** | Shows progress to user (WebSocket, notifications) |
| **Parallelism** | Considers parallel segment transcoding for speed |

---

## 6. Database Schema for Upload Tracking

**Q:** *"Design the database schema to track uploads, chunks, and processed files at scale. How do you handle the fact that there could be millions of chunk rows? What indexes matter?"*

### Answer

**Core Schema Design:**

```sql
-- Upload sessions (one row per upload attempt)
CREATE TABLE uploads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    filename        TEXT NOT NULL,
    file_size       BIGINT NOT NULL,
    mime_type       TEXT NOT NULL,
    checksum_client TEXT,                       -- SHA-256 from client
    chunk_size      INT NOT NULL DEFAULT 5242880,
    total_chunks    INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'initiated'
                    CHECK (status IN ('initiated','in_progress','completed',
                                      'processing','ready','quarantined','failed','expired')),
    storage_upload_id TEXT,                     -- S3 multipart upload ID
    storage_bucket  TEXT NOT NULL,
    storage_prefix  TEXT NOT NULL,              -- temp-chunks/{upload_id}/
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days',
    client_ip       INET,
    user_agent      TEXT
);

-- Chunk tracking (one row per chunk received)
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id       UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    chunk_number    INT NOT NULL,
    offset_start    BIGINT NOT NULL,
    offset_end      BIGINT NOT NULL,
    size            INT NOT NULL,
    checksum        TEXT NOT NULL,              -- SHA-256 of chunk
    storage_path    TEXT NOT NULL,              -- blob/{upload_id}/chunk_{n}
    received_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(upload_id, chunk_number)
);

-- Partition chunks by month (for scale)
CREATE TABLE chunks_2026_07 PARTITION OF chunks
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE chunks_2026_08 PARTITION OF chunks
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

-- Processed file metadata
CREATE TABLE files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id       UUID NOT NULL REFERENCES uploads(id),
    user_id         UUID NOT NULL,
    filename        TEXT NOT NULL,
    size            BIGINT NOT NULL,
    checksum        TEXT,                       -- Verified SHA-256
    mime_type       TEXT NOT NULL,
    storage_key     TEXT NOT NULL,              -- permanent/{user_id}/{file_id}
    storage_bucket  TEXT NOT NULL,
    virus_status    TEXT DEFAULT 'pending'
                    CHECK (virus_status IN ('pending','clean','infected')),
    virus_name      TEXT,                       -- If infected, which virus
    processing_status TEXT DEFAULT 'pending'
                    CHECK (processing_status IN ('pending','processing','ready','failed')),
    thumbnail_keys  JSONB,                      -- {320: "...", 640: "..."}
    manifest_key    TEXT,                       -- HLS manifest path
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_accessed   TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_uploads_user_status ON uploads(user_id, status);
CREATE INDEX idx_uploads_expires ON uploads(expires_at)
    WHERE status IN ('initiated','in_progress');
CREATE INDEX idx_chunks_upload ON chunks(upload_id, chunk_number);
CREATE INDEX idx_chunks_upload_offset ON chunks(upload_id, offset_start);
CREATE INDEX idx_files_user ON files(user_id);
CREATE INDEX idx_files_processing ON files(processing_status)
    WHERE virus_status = 'clean' AND processing_status = 'pending';
```

**Scaling Considerations:**

```yaml
Chunks table growth:
  - 50GB file ÷ 5MB chunks = 10,240 chunks
  - 10K files/day × 10K chunks = 100M chunk rows/day
  - Need partition by month OR use append-only time-series DB
  
Solution:
  1. Partition chunks by month (as shown above)
  2. Archive old partitions to cold storage (S3 + Athena queries)
  3. Delete expired upload chunks after 7 days (reduces rows)
  
uploads table:
  - Much smaller (1 row per upload)
  - Partition by month or just index by created_at
  - Archive uploads > 90 days to analytical DB (Redshift/BigQuery)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Normalization** | Separates uploads, chunks, and files into separate tables |
| **Chunk indexing** | Has indexes on (upload_id, chunk_number) and (upload_id, offset_start) |
| **Partitioning** | Mentions partition by time for chunks table at scale |
| **Status tracking** | Uses enum-like status fields with CHECK constraints |
| **Checksum storage** | Stores per-chunk and per-file checksums for integrity |

---

## 7. Pre-signed URLs vs Proxy Uploads

**Q:** *"Compare and contrast pre-signed URL uploads vs proxy-through-server uploads. When would you choose one over the other? Are there hybrid approaches?"*

### Answer

**Comparison Table:**

```yaml
Pre-signed URLs:
  How:  Client PUTs directly to S3 using server-generated URL
  
  Pros:
    ✓ Server handles ZERO bytes of file data
    ✓ Scales to unlimited throughput (S3 handles it)
    ✓ Lower latency (direct client→S3)
    ✓ Lower cost (no server bandwidth)
  
  Cons:
    ✗ Need to manage URL expiry (15 min default)
    ✗ Harder to enforce business logic mid-stream
    ✗ S3 events are eventually consistent (up to 60s delay)
    ✗ Client can bypass server validation (upload to wrong path)

Proxy Uploads:
  How:  Client POSTs to server, server streams to S3
  
  Pros:
    ✓ Full control over data (validate, transform, log)
    ✓ Can enforce business rules during upload
    ✓ Simpler client (no S3 SDK)
    ✓ Immediate consistency (no event delay)
  
  Cons:
    ✗ Server is bottleneck (network I/O, CPU, memory)
    ✗ Need to scale servers horizontally
    ✗ Higher latency (client→server→S3)
    ✗ Higher cost (server bandwidth + compute)
```

**Decision Matrix:**

```yaml
Pre-signed URLs preferred when:
  - Files > 100MB
  - High concurrency (> 1K concurrent uploads)
  - Video/media files (large, streaming-friendly)
  - Cost-sensitive (server bandwidth is expensive)

Proxy Uploads preferred when:
  - Files < 100MB
  - Need complex in-flight processing (compress, encrypt, transform)
  - Low concurrency (< 100 concurrent)
  - Simpler client (mobile app, IoT devices)

Hybrid Approach (best of both):
  1. Client sends small metadata first (proxy)
     → Server validates, creates upload record
  2. Server returns pre-signed URLs for chunks
     → Client uploads chunks directly to S3
  3. Client sends completion confirmation (proxy)
     → Server runs final validation, triggers processing

  This hybrid gives you:
  - Validation before upload (mitigates pre-signed URL risk)
  - Direct-to-storage speed (avoids server bottleneck)
  - Post-upload processing (async pipeline)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Trade-off depth** | Understands both approaches with concrete pros/cons |
| **Decision criteria** | Has clear rules for when to use each (file size, concurrency) |
| **Hybrid design** | Proposes combining both approaches for flexibility |
| **Security awareness** | Knows pre-signed URL risks (expiry, path validation) |

---

## 8. Handling Concurrent Uploads & Rate Limiting

**Q:** *"A single user tries to upload 100 10GB files simultaneously. How do you prevent this from overwhelming the system? Design the rate limiting and quota system."*

### Answer

**Multi-Level Rate Limiting:**

```python
class UploadRateLimiter:
    """Three levels of rate limiting for uploads."""

    def __init__(self, redis):
        self.redis = redis

    async def check_limits(self, user_id: str, file_size: int) -> bool:
        """Check all rate limits. Returns True if allowed."""
        checks = [
            self._check_concurrent_uploads(user_id),
            self._check_throughput(user_id, file_size),
            self._check_daily_quota(user_id, file_size),
        ]
        results = await asyncio.gather(*checks)
        return all(results)

    async def _check_concurrent_uploads(self, user_id: str) -> bool:
        """Level 1: Max concurrent uploads per user."""
        key = f"ratelimit:concurrent:{user_id}"
        current = await self.redis.incr(key)
        await self.redis.expire(key, 3600)  # 1 hour TTL
        if current > 10:  # Max 10 concurrent uploads
            raise RateLimitError("Too many concurrent uploads (max: 10)")
        return True

    async def _check_throughput(self, user_id: str, file_size: int) -> bool:
        """Level 2: Throughput limit per user."""
        key = f"ratelimit:throughput:{user_id}"
        current = await self.redis.get(key) or 0
        new_total = int(current) + file_size

        # Convert to MB/s over 60s window
        window_bytes = int(self.redis.ttl(key) or 60)
        mb_per_s = new_total / window_bytes / 1024 / 1024

        if mb_per_s > 50:  # Max 50 MB/s sustained
            raise RateLimitError("Upload throughput exceeded (max: 50 MB/s)")
        
        await self.redis.incrby(key, file_size)
        if not await self.redis.exists(key):
            await self.redis.expire(key, 60)
        return True

    async def _check_daily_quota(self, user_id: str, file_size: int) -> bool:
        """Level 3: Daily storage quota per user."""
        key = f"ratelimit:daily:{user_id}:{datetime.utcnow().date()}"

        current = await self.redis.get(key) or 0
        new_total = int(current) + file_size

        if new_total > 100 * 1024**3:  # 100 GB/day per user
            raise RateLimitError("Daily upload quota exceeded (max: 100 GB)")

        await self.redis.incrby(key, file_size)
        if not await self.redis.exists(key):
            await self.redis.expire(key, 86400)  # 24 hours
        return True
```

**Server-Side Resource Management:**

```yaml
Per-user quotas:
  - Concurrent uploads: 10
  - Throughput: 50 MB/s sustained
  - Daily storage: 100 GB
  - Max file size: 100 GB
  - Min chunk size: 5 MB

Global rate limits (per deployment):
  - Total concurrent uploads: 10,000
  - Aggregate throughput: 500 MB/s
  - New upload initiations: 1,000/second

When limits are exceeded:
  - Return HTTP 429 Too Many Requests
  - Include Retry-After header (seconds until retry allowed)
  - Log the rate limit event for analytics
  - Consider queueing requests (instead of rejecting) for premium users
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-level** | Concurrent, throughput, AND daily quota (not just one) |
| **Redis-based** | Uses Redis for fast, distributed rate counting |
| **User isolation** | One user's uploads don't affect others |
| **Feedback** | Returns Retry-After header + clear error messages |
| **Premium tiering** | Mentions higher limits for premium users |

---

## 9. Checksum Verification & Data Integrity

**Q:** *"How do you ensure a 50GB file was uploaded without corruption? Walk me through the checksum strategy from client to storage."*

### Answer

**End-to-End Integrity Chain:**

```
Layer 1: Client-side (before upload)
  Client computes SHA-256 of ENTIRE file
  → sends as header: X-Checksum-SHA256: <hash>

Layer 2: Per-chunk (during upload)
  Client computes SHA-256 of each chunk
  → sent as header on each PATCH: X-Chunk-Checksum: <hash>
  Server verifies chunk checksum before storing

Layer 3: Multipart upload ETags
  S3's ETag is MD5 of the part (for single-part)
  For multipart: ETag = MD5(all_part_md5s_concat)-numParts
  Can verify at complete time

Layer 4: Post-assembly verification
  After assembling all chunks, server downloads first/last
  few bytes and verifies against expected checksums
  Better: stream entire assembled file through SHA-256
  and compare with client's provided hash

Layer 5: Periodic integrity check (background)
  Background job re-checks checksums of stored files
  Detects bit rot / silent corruption over time
```

**Implementation:**

```python
import hashlib

class IntegrityVerifier:
    """Verifies file integrity at multiple points."""

    CHUNK_SIZE = 5 * 1024 * 1024  # 5MB

    async def verify_chunk(self, upload_id: str, chunk_number: int,
                           data: bytes, expected_checksum: str) -> bool:
        """Verify individual chunk checksum."""
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_checksum:
            logger.error(
                f"Chunk checksum mismatch: upload={upload_id}, "
                f"chunk={chunk_number}, expected={expected_checksum}, "
                f"actual={actual}"
            )
            return False
        return True

    async def verify_complete_file(self, upload_id: str,
                                    expected_checksum: str) -> bool:
        """Stream entire assembled file and verify checksum."""
        s3_key = f"permanent/{upload_id}"
        response = await s3_client.get_object(
            Bucket=UPLOAD_BUCKET, Key=s3_key
        )

        hasher = hashlib.sha256()
        async for chunk in response["Body"].iter_chunks():
            hasher.update(chunk)

        actual = hasher.hexdigest()
        if actual != expected_checksum:
            logger.error(
                f"File checksum mismatch: upload={upload_id}, "
                f"expected={expected_checksum}, actual={actual}"
            )
            # Corrupted! Trigger re-upload or repair
            await self.handle_corruption(upload_id)
            return False
        return True

    async def handle_corruption(self, upload_id: str):
        """Handle corrupted file after assembly."""
        await db.execute(
            "UPDATE uploads SET status = 'failed', failure_reason = 'checksum_mismatch' "
            "WHERE id = $1", upload_id
        )
        # Delete corrupted file
        await s3_client.delete_object(
            Bucket=UPLOAD_BUCKET,
            Key=f"permanent/{upload_id}"
        )
        # Notify user
        await notification_service.send(
            user_id=upload.user_id,
            message="Upload failed: file was corrupted during transfer. Please re-upload.",
        )
```

**Bit Rot Detection (Background):**

```python
async def periodic_integrity_check():
    """Runs daily, checks random sample of stored files."""
    sample = await db.fetch("""
        SELECT id, storage_key, checksum
        FROM files
        WHERE virus_status = 'clean'
        ORDER BY RANDOM()
        LIMIT 1000
    """)
    for file in sample:
        ok = await verify_file_integrity(
            file["storage_key"], file["checksum"]
        )
        if not ok:
            # Bit rot detected! Restore from replica/backup
            await restore_from_backup(file["id"])
            await alert_oncall("BIT_ROT_DETECTED", file_id=file["id"])
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-layered** | Verifies at chunk level AND file level |
| **Streaming verification** | Doesn't load entire file into memory for checksum |
| **Corruption handling** | Has a plan for when checksums don't match |
| **Bit rot** | Mentions background integrity checking for stored files |

---

## 10. Garbage Collection & Lifecycle Management

**Q:** *"What happens to partial/incomplete uploads? How do you clean up abandoned chunks? Design the garbage collection system."*

### Answer

**GC Targets:**

```yaml
Target 1: Abandoned uploads (never completed)
  - User started upload, never finished
  - Chunks stored in temp-chunks/{upload_id}/
  - Database rows in uploads (status = initiated/in_progress)

Target 2: Expired uploads (completed but too old)
  - Some uploads should auto-delete after retention period
  - e.g., temporary sharing links expire after 30 days

Target 3: Orphaned chunks (no associated upload record)
  - Chunks stored but upload record deleted (race condition)
  - Rare, but possible during crashes
```

**Implementation:**

```python
class GarbageCollector:
    """Background job that cleans up abandoned/expired uploads."""

    async def run_gc(self):
        """Run all GC tasks. Called every hour."""
        await asyncio.gather(
            self._clean_abandoned_uploads(),
            self._clean_expired_chunks(),
            self._clean_orphaned_chunks(),
        )

    async def _clean_abandoned_uploads(self):
        """Delete uploads that haven't received a chunk in 7 days."""
        stale = await db.fetch("""
            SELECT id FROM uploads
            WHERE status IN ('initiated', 'in_progress')
            AND updated_at < NOW() - INTERVAL '7 days'
            FOR UPDATE SKIP LOCKED
        """)
        for upload in stale:
            upload_id = upload["id"]
            # Delete from storage
            await storage.delete_prefix(f"temp-chunks/{upload_id}/")

            # If multipart upload was initiated, abort it
            if upload.get("storage_upload_id"):
                await s3_client.abort_multipart_upload(
                    Bucket=UPLOAD_BUCKET,
                    Key=f"temp-chunks/{upload_id}/",
                    UploadId=upload["storage_upload_id"],
                )

            # Update DB
            await db.execute(
                "DELETE FROM chunks WHERE upload_id = $1", upload_id
            )
            await db.execute(
                "UPDATE uploads SET status = 'expired' WHERE id = $1",
                upload_id
            )
            logger.info(f"Cleaned abandoned upload: {upload_id}")

    async def _clean_expired_chunks(self):
        """S3 lifecycle policy handles this, but verify."""
        # Mark uploads older than 90 days for archival
        old_files = await db.fetch("""
            SELECT id, storage_key FROM files
            WHERE created_at < NOW() - INTERVAL '90 days'
            AND last_accessed < NOW() - INTERVAL '30 days'
        """)
        for file in old_files:
            # Option 1: Move to Glacier (cheaper storage)
            await storage.transition_to_glacier(file["storage_key"])
            # Option 2: Delete if retention policy allows
            # await storage.delete(file["storage_key"])
            await db.execute(
                "UPDATE files SET storage_tier = 'glacier' WHERE id = $1",
                file["id"]
            )

    async def _clean_orphaned_chunks(self):
        """Find chunks in storage with no DB record."""
        # List objects in temp-chunks/ prefix
        objects = await storage.list_prefix("temp-chunks/")
        for obj in objects:
            # Parse upload_id from path: temp-chunks/{upload_id}/chunk_N
            upload_id = obj.key.split("/")[1]
            exists = await db.fetch_val(
                "SELECT EXISTS(SELECT 1 FROM uploads WHERE id = $1)",
                upload_id
            )
            if not exists:
                # Orphaned! Delete.
                await storage.delete(obj.key)
                logger.warning(f"Deleted orphaned chunk: {obj.key}")
```

**S3 Lifecycle Policy (for infrastructure-level GC):**

```json
{
  "Rules": [
    {
      "Id": "AbandonedUploadCleanup",
      "Status": "Enabled",
      "Prefix": "temp-chunks/",
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 7
      },
      "Expiration": {
        "Days": 7
      }
    },
    {
      "Id": "GlacierTransition",
      "Status": "Enabled",
      "Prefix": "permanent/",
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "GLACIER"
        }
      ]
    }
  ]
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-target GC** | Handles abandoned, expired, and orphaned cases |
| **S3 lifecycle** | Uses infrastructure-level policies (not just app-level) |
| **FOR UPDATE SKIP LOCKED** | Prevents concurrent GC from processing same upload |
| **Tiered storage** | Moves old files to Glacier instead of deleting |
| **Safety** | Doesn't delete files that might still be accessed |

---

## 11. Download & CDN Delivery Strategy

**Q:** *"After a large file is uploaded and processed, how do you serve it to users? Design the download/CDN strategy for files up to 100GB."*

### Answer

**Download Strategies by File Type:**

```yaml
Small files (< 100MB):
  Direct download via pre-signed URL (15 min TTL)
  CDN cache: cache at edge, TTL = 24 hours
  
Large files (100MB - 10GB):
  Range requests (HTTP Range header)
  CDN: Range-aware caching (CloudFront)
  Chunked download on client side
  
Very large files (10GB - 100GB):
  Streaming only (no download)
  OR: Download manager with parallel range requests
  OR: Physical shipping (AWS Snowball for > 100TB!)
  
Video files (any size):
  HLS adaptive streaming (playlist + segments)
  CDN: cache segments aggressively
  Client decides quality based on bandwidth
```

**Pre-signed Download URL Flow:**

```
Client                    Server                      CDN                     Storage
  │                         │                         │                        │
  │── GET /files/{id}/dl ──►│                         │                        │
  │                         │── Check permissions ───►│                        │
  │                         │◄── OK                   │                        │
  │                         │                         │                        │
  │                         │── Generate pre-signed   │                        │
  │                         │   CDN URL (30 min TTL)  │                        │
  │◄─── {url: "https://cdn. │                         │                        │
  │      example.com/f/xxx  │                         │                        │
  │      ?Expires=...&      │                         │                        │
  │      Signature=..."}    │                         │                        │
  │                         │                         │                        │
  │══ DOWNLOAD ═══════════════►                       │                        │
  │                         │   (if cache MISS:       │── fetch from origin ──►│
  │                         │    if cache HIT: served │                        │
  │                         │    from edge)           │                        │
```

**CDN Cache Strategy:**

```python
class CDNStrategy:
    """Multi-tier caching for uploaded files."""

    # Cache TTL by file popularity tier
    POPULARITY_TIERS = {
        "hot": {     # > 1000 downloads/day
            "edge_ttl": 86400,      # 24h at edge
            "origin_ttl": 604800,   # 7d at origin
        },
        "warm": {    # 100-1000 downloads/day
            "edge_ttl": 3600,       # 1h at edge
            "origin_ttl": 86400,    # 24h at origin
        },
        "cold": {    # < 100 downloads/day
            "edge_ttl": 300,        # 5min at edge
            "origin_ttl": 3600,     # 1h at origin
        },
    }

    async def get_download_url(self, file_id: str, user_id: str) -> str:
        file = await db.fetch_one("SELECT * FROM files WHERE id = $1", file_id)
        tier = await self._get_popularity_tier(file_id)

        # Generate CDN pre-signed URL with appropriate TTL
        url = cdn_client.sign_url(
            url=f"https://cdn.example.com/{file['storage_key']}",
            expires_in=self.POPULARITY_TIERS[tier]["edge_ttl"],
            ip_restriction=user_ip,  # Optional: restrict to user's IP
        )
        return url

    async def _get_popularity_tier(self, file_id: str) -> str:
        downloads_24h = await redis.get(f"downloads:24h:{file_id}") or 0
        if downloads_24h > 1000:
            return "hot"
        elif downloads_24h > 100:
            return "warm"
        return "cold"

    async def invalidate_cache(self, file_id: str):
        """Invalidate CDN cache when file is updated/replaced."""
        file = await db.fetch_one("SELECT storage_key FROM files WHERE id = $1", file_id)
        await cdn_client.invalidate(
            paths=[f"/{file['storage_key']}", f"/thumbnails/{file_id}/*"]
        )
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Size-based strategy** | Different approaches for small, large, and streaming files |
| **CDN integration** | Uses CDN for edge caching, pre-signed URLs for security |
| **Popularity tiers** | Caches hot content longer, cold content shorter |
| **Range requests** | Supports HTTP Range for large file downloads |

---

## 12. Monitoring & Debugging Upload Failures

**Q:** *"A user reports their 10GB upload failed at 95% and they're frustrated. Walk me through how you'd debug this using logs, metrics, and traces."*

### Answer

**Debugging Workflow:**

```python
# Step 1: Find the upload
upload = await db.fetch_one("""
    SELECT * FROM uploads WHERE id = $1
""", upload_id)

# Check what happened
if upload["status"] == "in_progress":
    # Upload never completed — find last received chunk
    last_chunk = await db.fetch_one("""
        SELECT chunk_number, offset_end, received_at
        FROM chunks
        WHERE upload_id = $1
        ORDER BY chunk_number DESC
        LIMIT 1
    """, upload_id)
    # → Last chunk: #194, offset: 1,017,282,560, received: 15 min ago
    # → Missing: #195 (last one!), due to timeout

# Step 2: Check the client-side logs (via WebSocket)
# If client was sending progress events:
client_logs = await get_client_events(upload_id)
# → "Chunk 194 sent, awaiting ack..."
# → "Network error: Socket timeout"
# → "Retrying chunk 194... (attempt 2/3)"
# → "Retry exhausted: giving up on chunk 194"

# Step 3: Check server-side logs
logs = await query_logs(
    service="upload-service",
    filter={"upload_id": upload_id},
)
# → "Received chunk 193, checksum OK"
# → "Received chunk 194, checksum OK"
# → "Error storing chunk 194 in S3: ConnectionResetError"
# → "Retry 1/3: storing chunk 194..."
# → "Error: S3 bucket throttling (503 SlowDown)"
# → "Marked chunk 194 as failed"

# Step 4: Check metrics
metrics = await query_metrics(
    metric="s3_put_latency",
    timeframe="last_hour",
)
# → S3 latency p99 jumped from 50ms to 2s at time of failure
# → S3 503 errors spiked — bucket was being rate-limited

# Root cause: S3 bucket request rate limit exceeded
# (S3 has 3,500 PUT/s per prefix limit)
```

**Key Metrics Dashboard:**

```yaml
Real-time Upload Dashboard:
  ┌─────────────────────────────────────────────────────┐
  │ Active Uploads: 2,347 │ Throughput: 234 MB/s        │
  ├─────────────────────────────────────────────────────┤
  │ Success Rate (1h): 97.2% │ Avg Chunk Time: 1.3s    │
  │ Failure Rate (1h): 2.8%  │ p99 Chunk Time: 4.7s    │
  ├─────────────────────────────────────────────────────┤
  │ Top Failure Reasons:                                │
  │   1. Network timeout (42%)                          │
  │   2. Checksum mismatch (18%)                        │
  │   3. S3 throttling (15%)                            │
  │   4. Client disconnected (12%)                      │
  │   5. Other (13%)                                    │
  ├─────────────────────────────────────────────────────┤
  │ Processing Pipeline:                                │
  │   Queue depth: 1,234 │ Process rate: 45 files/min  │
  │   Virus scan: 98.5% pass │ Avg scan: 4.2s         │
  │   Transcode: 87.3% pass │ Avg transcode: 12.4min  │
  └─────────────────────────────────────────────────────┘
```

**Alerting Thresholds:**

```yaml
Critical alerts (PagerDuty):
  - Upload success rate < 95% for 5 minutes
  - Chunk upload p99 latency > 5s for 5 minutes
  - Processing queue depth > 10,000
  - Virus infection rate > 1%
  - S3 5xx error rate > 1%

Warning alerts (Slack):
  - Upload success rate < 98% for 15 minutes
  - Average chunk upload time > 3s
  - Abandoned upload rate > 20%
  - Checksum mismatch rate > 5%
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Trace-based debugging** | Connects upload_id across services (client, server, storage) |
| **Log analysis** | Can find specific error by searching structured logs |
| **Metric correlation** | Correlates failure with infrastructure metrics (S3 latency, 503s) |
| **Root cause identification** | Identifies S3 bucket throttling as a specific cause |
| **Actionable alerts** | Defines concrete thresholds for alerting |

---

## Implementation

See [CODE.md](./CODE.md) for the Python implementation of the upload service.
