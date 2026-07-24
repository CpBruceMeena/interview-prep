# 🏗️ Big File Upload System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Reliable multi-GB uploads, resumability, async processing, storage optimization

---

## 1. SYSTEM OVERVIEW

**Purpose:** Handle reliable upload of large files (100MB–100GB) with progress tracking, resume capability, virus scanning, and post-processing pipelines.

**Scale:** 10K concurrent uploads, files up to 100GB, 1M+ files stored, 500MB/s aggregate throughput

**Users:** End users (upload/download), Content moderators (review/approve), System admins (monitor/manage)

**Use Cases:** Video upload (YouTube/Vimeo), Document upload (Google Drive), Media sharing (Dropbox), Dataset upload (ML platforms), Medical imaging (DICOM)

**Constraints:**
- p99 upload completion time < 30 min for 10GB file (on 50 Mbps connection)
- Resumability: survive network drops up to 7 days
- Virus scanning: 100% of uploads scanned < 5 min
- 99.9% durability for stored files
- Idempotency: no duplicate storage on retry

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT SIDE                                │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────────────────┐  │
│  │  File Splitter  │  │  Chunk Manager │  │  Upload Scheduler    │  │
│  │  (Blob.slice()) │  │  (Queue +      │  │  (Concurrency 3-6)   │  │
│  │                 │  │   Retry Logic) │  │                       │  │
│  └────────┬───────┘  └───────┬────────┘  └──────────┬────────────┘  │
│           │                  │                      │               │
│           └──────────────────┴──────────────────────┘               │
│                              │                                      │
│                   ┌──────────▼──────────┐                           │
│                   │  TUS Client / SDK   │                           │
│                   │  (tus-js-client)    │                           │
│                   └──────────┬──────────┘                           │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (Kong/NGINX)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ Auth     │  │ Rate     │  │ Request  │  │ TLS Termination   │  │
│  │ (JWT)    │  │ Limiting │  │ Validation│  │ + Load Balancing  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     UPLOAD SERVICE (FastAPI/Python)                 │
│                                                                     │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐   │
│  │ Initiate       │  │ Chunk Receive  │  │ Complete Assembly   │   │
│  │ (POST /upload) │  │ (PATCH /upload │  │ (POST /upload/{id}) │   │
│  │                │  │  /{id}/chunk)  │  │                      │   │
│  └───────┬────────┘  └───────┬────────┘  └──────────┬───────────┘   │
│          │                  │                       │                │
│          └──────────────────┴───────────────────────┘                │
│                              │                                       │
│                   ┌──────────▼──────────┐                            │
│                   │  Presigned URL Gen  │                            │
│                   │  (S3 STS / Vault)   │                            │
│                   └──────────┬──────────┘                            │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  METADATA DB     │ │  OBJECT STORE    │ │  MESSAGE QUEUE   │
│  (PostgreSQL)    │ │  (S3/MinIO)      │ │  (Kafka/RMQ)     │
│                  │ │                  │ │                  │
│  • uploads       │ │  • temp-chunks/  │ │  • file.uploaded │
│  • chunks        │ │  • permanent/    │ │  • file.scanned  │
│  • files         │ │  • quarantine/   │ │  • file.ready    │
│  • users         │ │  • thumbnails/   │ │                  │
└──────────────────┘ └──────────────────┘ └────────┬─────────┘
                                                   │
                                                   ▼
                              ┌────────────────────────────────────────┐
                              │        ASYNC PROCESSING PIPELINE       │
                              │                                        │
                              │  ┌────────────────────────────────┐   │
                              │  │  VIRUS SCANNER (ClamAV + YARA) │   │
                              │  │  → clean: move to permanent    │   │
                              │  │  → infected: move to quarantine│   │
                              │  └────────────┬───────────────────┘   │
                              │               │                        │
                              │  ┌────────────▼───────────────────┐   │
                              │  │  TRANSCODER (FFmpeg)           │   │
                              │  │  → resolutions (1080p, 720p…)  │   │
                              │  │  → thumbnails + HLS segments   │   │
                              │  └────────────┬───────────────────┘   │
                              │               │                        │
                              │  ┌────────────▼───────────────────┐   │
                              │  │  NOTIFIER (WebSocket/Webhook)   │   │
                              │  │  → user notified on completion  │   │
                              │  └────────────────────────────────┘   │
                              └────────────────────────────────────────┘
```

---

## 3. DETAILED DESIGN FLOW

### 3.1 Upload Lifecycle State Machine

```
                  ┌─────────────────────────┐
                  │       INITIATED          │
                  │  (metadata created,      │
                  │   upload_id returned)    │
                  └────────────┬─────────────┘
                               │ first chunk received
                               ▼
                  ┌─────────────────────────┐
                  │      IN_PROGRESS         │
                  │  (chunks being uploaded) │
                  │  (can be PAUSED/         │
                  │   RESUMED via offset)   │
                  └────────────┬─────────────┘
                               │ all chunks complete
                               ▼
                  ┌─────────────────────────┐
                  │      COMPLETED           │
                  │  (chunks assembled,      │
                  │   file integrity check) │
                  └────────────┬─────────────┘
                               │ queued for processing
                               ▼
                  ┌─────────────────────────┐
                  │     PROCESSING           │
                  │  (virus scan, transcode) │
                  └──────┬──────────┬───────┘
                    clean │          │ infected
                          ▼          ▼
              ┌──────────────┐ ┌──────────────┐
              │    READY     │ │  QUARANTINED │
              │ (available   │ │ (flagged for │
              │  for download│ │  review)     │
              └──────────────┘ └──────────────┘
```

### 3.2 Step-by-Step Upload Flow

```
Client                Upload Service           Metadata DB          Object Store
  │                         │                      │                   │
  │──── POST /upload ──────►│                      │                   │
  │   {filename, size,      │                      │                   │
  │    mime_type, checksum} │                      │                   │
  │                         │── INSERT upload ────►│                   │
  │                         │   (status=INITIATED) │                   │
  │◄─── {upload_id,         │                      │                   │
  │      chunk_size: 5MB,   │                      │                   │
  │      max_chunks: 100}   │                      │                   │
  │                         │                      │                   │
  │ ═══════ UPLOAD CHUNKS (parallel, up to 6) ════════                │
  │                         │                      │                   │
  │──── PATCH /upload/{id} ─►                      │                   │
  │   /chunk?offset=0       │                      │                   │
  │   [chunk_data]          │                      │                   │
  │                         │── PUT chunk ────────────────────────────►│
  │                         │   blob/{id}/chunk_0  │                   │
  │                         │── UPDATE chunk ─────►│                   │
  │◄─── {offset: 0,         │   {chunk_num=0,      │                   │
  │      received: 5242880, │    size=5MB,          │                   │
  │      checksum: <sha256>}│    checksum_matched}  │                   │
  │                         │                      │                   │
  │ (network drops here!)   │                      │                   │
  │                         │                      │                   │
  │──── HEAD /upload/{id} ──►                      │                   │
  │                         │── SELECT max(offset)─►│                   │
  │◄─── {offset: 5242880}   │                      │                   │
  │                         │                      │                   │
  │──── PATCH /upload/{id} ─►                      │                   │
  │   /chunk?offset=5242880 │                      │                   │
  │   [next_chunk_data]     │                      │                   │
  │                         │── PUT chunk ────────────────────────────►│
  │ (repeated for all       │                      │                   │
  │  chunks)                │                      │                   │
  │                         │                      │                   │
  │──── POST /upload/{id} ──►                      │                   │
  │   /complete             │                      │                   │
  │   {checksum: <sha256>,  │                      │                   │
  │    total_chunks: N}     │                      │                   │
  │                         │── Verify all chunks ─►│                  │
  │                         │── Assemble (multipart ──────────────────►│
  │                         │   upload complete)    │                   │
  │                         │── UPDATE status ─────►│                   │
  │                         │   =COMPLETED          │                   │
  │◄─── {status: "completed",                       │                   │
  │      file_id: "f_xxx",                          │                   │
  │      size: 1.2GB}                               │                   │
  │                         │                      │                   │
  │                         │── PUBLISH ───────────────────────────────►│
  │                         │   file.uploaded → Kafka                  │
```

### 3.3 Async Processing Flow

```
Kafka: file.uploaded ──► Virus Scanner ──► clean ──► Transcoder ──► Notifier
                                                      │
                                 ┌────────────────────┤
                                 ▼                    ▼
                          ┌──────────────┐   ┌──────────────┐
                          │  Thumbnails  │   │  HLS Segments│
                          │  (320, 640,  │   │  (240p, 480p,│
                          │   1280, 1920)│   │   720p, 1080p)│
                          └──────────────┘   └──────────────┘
                                                      │
                                                      ▼
                          ┌──────────────────────────────┐
                          │  CDN Invalidation + Cache    │
                          │  Warm (CloudFront / Cloudflare│
                          └──────────────────────────────┘
```

---

## 4. KEY COMPONENTS

### 4.1 Upload Service (Python/FastAPI)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/upload` | POST | Initiate new upload — returns `upload_id`, `chunk_size`, `max_chunks` |
| `/api/v1/upload/{id}/chunk` | PATCH | Upload a chunk at a specific offset (TUS-compatible) |
| `/api/v1/upload/{id}` | HEAD | Get current upload offset (for resume) |
| `/api/v1/upload/{id}/complete` | POST | Finalize upload — verify checksum, assemble, queue processing |
| `/api/v1/upload/{id}/status` | GET | Get upload status (progress, ETA, processing status) |
| `/api/v1/upload/{id}` | DELETE | Cancel/abort upload — clean up partial chunks |

### 4.2 Metadata Database Schema (PostgreSQL)

```sql
-- Upload sessions
CREATE TABLE uploads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    filename        TEXT NOT NULL,
    file_size       BIGINT NOT NULL,           -- Total file size in bytes
    mime_type       TEXT NOT NULL,
    checksum        TEXT,                       -- Client-provided SHA-256
    chunk_size      INT NOT NULL DEFAULT 5242880,  -- 5MB default
    total_chunks    INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'initiated'
                    CHECK (status IN ('initiated','in_progress','completed',
                                      'processing','ready','quarantined','failed')),
    storage_key     TEXT,                       -- S3 object key
    storage_bucket  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);

-- Chunk tracking
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id       UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    chunk_number    INT NOT NULL,
    offset_start    BIGINT NOT NULL,
    offset_end      BIGINT NOT NULL,
    size            INT NOT NULL,
    checksum        TEXT,                       -- SHA-256 of chunk
    storage_path    TEXT,                       -- blob/{upload_id}/chunk_{n}
    received_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(upload_id, chunk_number)
);

-- Processed file metadata
CREATE TABLE files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id       UUID NOT NULL REFERENCES uploads(id),
    storage_key     TEXT NOT NULL,
    size            BIGINT NOT NULL,
    checksum        TEXT,
    mime_type       TEXT NOT NULL,
    virus_status    TEXT DEFAULT 'pending'
                    CHECK (virus_status IN ('pending','clean','infected')),
    processing_status TEXT DEFAULT 'pending'
                    CHECK (processing_status IN ('pending','processing','ready','failed')),
    thumbnail_keys  JSONB,                      -- {320: "path_320", 640: "path_640"}
    manifest_key    TEXT,                       -- HLS manifest path
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_uploads_user_status ON uploads(user_id, status);
CREATE INDEX idx_uploads_expires ON uploads(expires_at) WHERE status IN ('initiated','in_progress');
CREATE INDEX idx_chunks_upload ON chunks(upload_id, chunk_number);
CREATE INDEX idx_files_status ON files(processing_status) WHERE virus_status = 'clean';
```

### 4.3 Object Storage Layout (S3/MinIO)

```
bucket/
├── temp-chunks/
│   └── {upload_id}/
│       ├── chunk_0
│       ├── chunk_1
│       └── ...
├── permanent/
│   └── {user_id}/
│       └── {file_id}_{filename}
├── quarantine/
│   └── {timestamp}_{file_id}
├── thumbnails/
│   └── {file_id}/
│       ├── 320.webp
│       ├── 640.webp
│       ├── 1280.webp
│       └── 1920.webp
├── hls/
│   └── {file_id}/
│       ├── master.m3u8
│       ├── 240p/
│       ├── 480p/
│       ├── 720p/
│       └── 1080p/
└── av-scan/
    └── {file_id}.scan_result
```

**Lifecycle Policies:**
- `temp-chunks/`: Auto-delete after 7 days (abandoned uploads)
- `quarantine/`: Auto-delete after 30 days
- `thumbnails/` and `hls/`: Retain indefinitely

---

## 5. DESIGN PATTERNS & TRADE-OFFS

### Strategy: Direct-to-Storage (Pre-signed URLs)

```yaml
Approach: Client uploads directly to S3 via pre-signed URLs
          1. Server generates short-lived (15 min) pre-signed URL
          2. Client PUTs chunk directly to S3
          3. S3 triggers Lambda/notification on completion

Pros:
  - Server is not a bottleneck — no bandwidth consumed
  - Scales with S3 (essentially unlimited)
  - Lower latency for client (direct connection)

Cons:
  - More complex client logic
  - Pre-signed URL expiry management
  - S3 event notifications have eventual consistency

When to use:
  - Files > 100MB
  - High upload concurrency
  - Want to minimize server resource usage
```

### Strategy: Proxy Upload (via App Server)

```yaml
Approach: Client sends all data through the upload service
          1. Server receives full/chunked data
          2. Server writes to S3

Pros:
  - Simpler client (just POST)
  - Full control over validation and transformation
  - Can enforce business logic mid-stream

Cons:
  - Server is bottleneck (network I/O, memory)
  - Requires horizontal scaling of app servers
  - Higher cost (server bandwidth is expensive)

When to use:
  - Files < 100MB
  - Need complex in-flight validation
  - Low concurrency requirements
```

### Chunking Strategy Comparison

| Strategy | Description | Best For |
|----------|-------------|----------|
| **Fixed-size chunks** | All chunks same size (e.g., 5MB) | Simplicity, predictable storage |
| **Variable-size chunks** | First/last chunk smaller | Streaming, media files |
| **Adaptive chunking** | Adjust size based on network | Mobile, unreliable connections |
| **TUS Protocol** | Standard HTTP PATCH/HEAD | Interoperability, resumability |

### Storage Strategy: Multipart Upload vs Single Object

```yaml
Multipart Upload (S3):
  - Upload parts in parallel
  - Upload parts in any order
  - Resume from failed parts
  - Min part size: 5MB (except last)
  - Max parts: 10,000

Single Object Upload:
  - Simple PUT request
  - Max 5GB in single operation
  - No partial failure recovery
  - Lower overhead for small files

Decision:
  - Files < 100MB: Single PUT (or pre-signed URL)
  - Files > 100MB: Multipart upload via S3 API
  - Files > 5GB: MUST use multipart upload
```

---

## 6. RESILIENCE & ERROR HANDLING

### Retry Strategy

```python
RETRY_BACKOFF = {
    "chunk_upload": {
        "max_retries": 3,
        "base_delay": 1.0,  # seconds
        "max_delay": 30.0,
        "backoff_factor": 2.0,  # exponential
    },
    "complete_upload": {
        "max_retries": 5,
        "base_delay": 2.0,
        "max_delay": 60.0,
    },
    "processing": {
        "max_retries": 3,
        "base_delay": 5.0,  # virus scan transient failures
    }
}
```

### Error Types & Handling

| Error | Client Action | Server Action |
|-------|---------------|---------------|
| Network timeout | Retry chunk with exponential backoff | Accept duplicate chunk (idempotent) |
| 401 Unauthorized | Refresh token, retry | Revoke old pre-signed URLs |
| 409 Conflict | Re-initiate upload | Clean up stale chunks |
| 413 Payload Too Large | Reject client-side | Return max_allowed_size |
| 500 Server Error | Retry with backoff | Log, alert on-call |
| Checksum mismatch | Re-upload corrupted chunk | Delete corrupted chunk |

### Garbage Collection

```python
# Background job — runs every hour
async def cleanup_abandoned_uploads():
    """Delete chunks for uploads that were never completed."""
    stale_uploads = await db.fetch("""
        SELECT id FROM uploads
        WHERE status IN ('initiated', 'in_progress')
        AND created_at < NOW() - INTERVAL '7 days'
        FOR UPDATE SKIP LOCKED
    """)
    for upload in stale_uploads:
        await storage.delete_prefix(f"temp-chunks/{upload.id}/")
        await db.execute("DELETE FROM chunks WHERE upload_id = $1", upload.id)
        await db.execute("UPDATE uploads SET status = 'expired' WHERE id = $1", upload.id)
```

---

## 7. SECURITY CONSIDERATIONS

| Threat | Mitigation |
|--------|------------|
| **Malicious file upload** | File type validation (magic bytes, not just extension) + virus scanning |
| **Upload bombing** | Rate limit per user (10 concurrent uploads, 1GB/min) |
| **Path traversal** | Sanitize filenames, use UUID-based storage paths |
| **Pre-signed URL abuse** | Short TTL (15 min), scope to specific upload_id + chunk_number |
| **Unrestricted upload size** | Reject files > max_allowed_size (100GB default) |
| **SSRF via upload URL** | Validate all redirect URLs, use allowlist |
| **Storage access bypass** | Signed URLs for downloads with expiry |

---

## 8. SCALABILITY

### Bottlenecks & Solutions

| Bottleneck | Limit | Solution |
|------------|-------|----------|
| Upload Service CPU | Request handling | Auto-scale pods (HPA: CPU > 70%) |
| Metadata DB writes | Concurrent chunk tracking | Partition by upload_id, connection pooling |
| Object Store PUTs | S3 bucket limits | Use prefix sharding (`{upload_id:0-3}/...`) |
| Virus Scanner | Scan throughput (500MB/min per node) | Parallel scanning workers, separate queue |
| Transcoder | CPU/GPU for encoding | Auto-scale transcoder pool with priority queue |

### Horizontal Scaling

```
LOAD BALANCER (Round Robin)
    │
    ├── Upload Service Pod 1 (CPU: 40%)
    ├── Upload Service Pod 2 (CPU: 35%)
    ├── Upload Service Pod 3 (CPU: 55%)
    └── Upload Service Pod N (scales to N)
            │
            ▼
    PostgreSQL Read Replicas
    └── Writes go to Primary
    └── Reads (status checks) go to Replicas
```

### Cost Estimation (Monthly — 10TB upload volume)

| Component | Cost |
|-----------|------|
| Upload Service (4 × t3.large) | $600 |
| Metadata DB (RDS PostgreSQL) | $400 |
| Object Storage (S3 — 10TB stored + 10TB uploaded) | $500 |
| Virus Scanning (Lambda × 100K files) | $100 |
| Transcoding (Spot instances) | $800 |
| CDN (CloudFront — 50TB egress) | $4,000 |
| Message Queue (Kafka — 2 brokers) | $400 |
| **Total** | **~$6,800** |

---

## 9. MONITORING & ALERTS

### Key Metrics (RED)

```yaml
Rate:
  - upload_initiations_per_second
  - chunks_uploaded_per_second
  - files_processed_per_second

Errors:
  - upload_failure_rate (SLO: < 1%)
  - chunk_checksum_mismatch_rate
  - virus_infection_rate (alert if > 0.1%)
  - processing_pipeline_failure_rate

Duration:
  - p50/p95/p99 upload_completion_time
  - p50/p95/p99 chunk_upload_latency
  - p50/p95/p99 virus_scan_duration
  - p95 processing_pipeline_latency
```

### Dashboards

```yaml
Upload Dashboard:
  - Active concurrent uploads (current + trend)
  - Upload throughput (MB/s)
  - Success rate by file size bracket
  - Top 5 errors by type

Storage Dashboard:
  - Total stored bytes (by tier)
  - Object count by bucket prefix
  - Lifecycle expiration rate
  - Glacier transition rate

Processing Dashboard:
  - Queue depth (pending files)
  - Scan/completion rate
  - Infected file count (alert)
  - Transcoding queue wait time
```

---

## 10. INTERVIEW DEEP-DIVE QUESTIONS

See [INTERVIEW_QUESTIONS.md](./INTERVIEW_QUESTIONS.md) for a comprehensive set of staff-level interview questions covering this design.
