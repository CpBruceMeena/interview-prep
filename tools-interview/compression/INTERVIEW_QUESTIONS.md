# 🗜️ Compression Algorithms — Staff-Level Interview Questions

> *10 questions covering Gzip, Deflate, Zstandard (zstd), Brotli, and the internals of lossless compression — every question expects principal engineer-level depth with production deployment insight.*

---

## Table of Contents

1. [LZ77 & Huffman Coding Internals](#1-lz77--huffman-coding-internals)
2. [Deflate vs Gzip: The Difference Is the Wrapper](#2-deflate-vs-gzip-the-difference-is-the-wrapper)
3. [Zstandard: Finite-State-Entropy & Dictionary Compression](#3-zstandard-finite-state-entropy--dictionary-compression)
4. [Brotli: Why It Won for Web Assets](#4-brotli-why-it-won-for-web-assets)
5. [Content-Encoding vs Transfer-Encoding](#5-content-encoding-vs-transfer-encoding)
6. [Compression Level Trade-offs: Speed vs Ratio](#6-compression-level-trade-offs-speed-vs-ratio)
7. [Dictionary Compression: Training Domain-Specific Dictionaries](#7-dictionary-compression-training-domain-specific-dictionaries)
8. [Streaming Compression vs Block Compression](#8-streaming-compression-vs-block-compression)
9. [Compression in HTTP/2 & HTTP/3: HPACK, QPACK, and Beyond](#9-compression-in-http2--http3-hpack-qpack-and-beyond)
10. [Production Compression Strategy: When to Compress, What to Skip](#10-production-compression-strategy-when-to-compress-what-to-skip)

---

## 1. LZ77 & Huffman Coding Internals

**Q:** "Walk through the internals of Deflate compression — the algorithm behind gzip and zlib. How do LZ77 and Huffman coding work together to achieve compression? What determines the compression ratio ceiling for a given input?"

**What They're Really Testing:** Whether you understand the TWO-STAGE architecture of Deflate — the sliding-window match finder and the entropy coder — and can reason about the theoretical limits.

### Answer

**Deflate Architecture (Two Stages):**

```
Input: "ABABABABCABABCABABC"

Stage 1 — LZ77 (Sliding Window):
┌────────────────────────────────────────────────────┐
│ Window (32KB max)          │ Lookahead Buffer       │
│ ...A B A B A B A B C A B  │ A B C A B A B C...     │
│                            │                        │
│ Find longest match in      │                        │
│ window for lookahead:      │                        │
│ Match: "ABABC" at offset 3 │                        │
│ → Emit: <length=5, distance=3>                     │
└────────────────────────────────────────────────────┘

Output: literal(A) literal(B) <5,3> literal(C) <5,6> ...

Stage 2 — Huffman Coding:
┌────────────────────────────────────────────────────┐
│ Token frequencies:                                 │
│ - Literal 'A': 1200 occurrences → 2-bit code       │
│ - Literal 'B': 800 occurrences  → 3-bit code       │
│ - Length 5:    400 occurrences  → 4-bit code       │
│ - Literal 'C': 50 occurrences   → 8-bit code       │
│                                                     │
│ Build binary tree (min-heap):                       │
│        [root]                                       │
│      0/      \1                                     │
│    [A]       [node]                                 │
│            0/     \1                                │
│           [B]    [L=5]                              │
│                                                     │
│ Result: variable-length codes based on frequency    │
└────────────────────────────────────────────────────┘
```

**Compression Ratio Ceiling:**

```python
# Shannon entropy: theoretical minimum bits per symbol
H(X) = -Σ P(x) × log₂(P(x))

# For English text:
#   Letter 'e' appears ~12% → needs ~3 bits
#   Letter 'z' appears ~0.07% → needs ~10 bits
# Average: ~4.5 bits per character

# Theoretical max compression:
#   Original: 8 bits/char × N chars = 8N bits
#   Shannon limit: 4.5N bits
#   Max ratio: 8/4.5 ≈ 1.78:1 (for English text)

# But LZ77 exploits REPETITIONS (not just frequency):
#   "the quick brown fox jumps over" → 29 chars
#   With repetition: many substrings repeat
#   Practical gzip ratio: 2.5-5:1 for text
#   Practical gzip ratio: 1.1-1.5:1 for already-binary
```

**What Limits the Ratio:**

```yaml
Input characteristics:
  - Low entropy (repetitive): high ratio (DDL: 100:1+)
  - High entropy (random): barely compresses (1.01:1)
  - Small inputs (< 100 bytes): window too small, overhead dominates

Algorithm limits:
  - LZ77 window: 32KB max (Deflate) → can't match beyond this
  - Huffman tree: must be transmitted with data → overhead
  - Dynamic vs fixed Huffman: dynamic better for large files, overhead for small
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Two-stage understanding** | Clearly separates LZ77 (match finding) from Huffman (entropy coding) |
| **Shannon entropy** | Can compute theoretical limits using information theory |
| **Window limitation** | Knows 32KB window is Deflate's fundamental constraint vs zstd's larger windows |
| **Small file penalty** | Understands why compressing tiny files can INCREASE size |

---

## 2. Deflate vs Gzip: The Difference Is the Wrapper

**Q:** "A colleague says 'we use gzip compression.' You ask: 'Deflate level 6 with gzip wrapper, or raw Deflate?' They look confused. Explain the difference between Deflate, gzip, and zlib. When would you use each?"

**What They're Really Testing:** Whether you understand the three layers: the raw compressed stream (Deflate), the container format (gzip), and the library (zlib). Many engineers conflate these.

### Answer

**The Three Layers:**

```
┌─────────────────────────────────────────────────────────────┐
│                    DEFLATE (compressed stream)                │
│  The raw algorithm output: LZ77 tokens + Huffman codes       │
│  No header, no checksum, no filename — just the bits        │
│                                                              │
│  Used by: PNG (IDAT chunk), ZIP (stored method 8),          │
│           raw zlib streams                                   │
└─────────────────────────────────────────────────────────────┘
         ▲ wrapped with
         │
┌────────┴────────────────────────────────────────────────────┐
│                   GZIP (container format)                    │
│  ┌──────┬──────────┬──────────────────┬─────────┐           │
│  │ ID1  │ ID2      │ CM (Deflate=8)   │ FLG     │           │
│  │ 0x1f │ 0x8b     │                   │ (flags) │           │
│  ├──────┴──────────┴──────────────────┴─────────┤           │
│  │ MTIME (4 bytes)  │ XFL │ OS                 │           │
│  ├──────────────────────────────────────────────┤           │
│  │ Optional: filename, comment, extra headers   │           │
│  ├──────────────────────────────────────────────┤           │
│  │ DEFLATE compressed data                      │           │
│  ├──────────────────────────────────────────────┤           │
│  │ CRC32 (4 bytes)    │ ISIZE (4 bytes)         │           │
│  │ Original data CRC  │ Original size mod 2^32  │           │
│  └──────────────────────────────────────────────┘           │
│                                                              │
│  11 bytes overhead (fixed header) + 8 bytes trailer         │
│  ≈ 20 bytes total overhead                                  │
└─────────────────────────────────────────────────────────────┘
         ▲ wrapped with
         │
┌────────┴────────────────────────────────────────────────────┐
│                   ZLIB (library + wrapper)                   │
│  ┌──────┬──────┬──────────────────────┬───────┐              │
│  │ CMF  │ FLG  │ DEFLATE data         │ ADLER32 │            │
│  │(2B)  │ (1B) │                      │ (4B)    │            │
│  └──────┴──────┴──────────────────────┴─────────┘            │
│                                                              │
│  2 bytes header + ADLER32 checksum (instead of CRC32)       │
│  ≈ 6 bytes overhead                                         │
│                                                              │
│  Used by: HTTP Content-Encoding (with gzip wrapper,         │
│  NOT raw zlib!), PNG (zlib wrapper), TLS (zlib wrapper)     │
└─────────────────────────────────────────────────────────────┘
```

**When to Use Each:**

```yaml
gzip (.gz):
  - File compression (tar -czf → .tar.gz)
  - HTTP Content-Encoding: gzip
  - When you need file metadata (name, timestamp)
  - When CRC32 integrity is required
  - ~20 bytes overhead

Raw Deflate:
  - Embedded systems (tight memory)
  - PNG IDAT chunks
  - Custom container formats
  - When you control the full protocol (no standards compliance needed)

zlib (.zz, or raw .z):
  - PNG (zlib wrapper, not gzip!)
  - TLS compression (rarely used anymore — CRIME/BREACH attacks)
  - When minimum overhead matters (6 bytes vs 20)
  - ADLER32 is slightly faster than CRC32 (but weaker)

HTTP behavior:
  Accept-Encoding: gzip, deflate
  # "deflate" here actually means zlib (RFC 1950), NOT raw deflate (RFC 1951)!
  # Historical mistake — many servers send raw deflate instead → interop issues
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Deflate ≠ gzip** | Can articulate that Deflate is the algorithm, gzip is the container |
| **HTTP deflate confusion** | Knows the historical RFC bug: \"deflate\" in HTTP means zlib |
| **Overhead comparison** | Can quote gzip (~20B) vs zlib (~6B) vs raw (0B) overhead |
| **Checksum difference** | Understands CRC32 vs ADLER32 trade-offs (integrity vs speed) |

---

## 3. Zstandard: Finite-State-Entropy & Dictionary Compression

**Q:** "Facebook replaced zlib/gzip with Zstandard (zstd) in many production services. Walk through zstd's architecture. What makes Finite State Entropy different from Huffman coding? How does zstd's dictionary compression work?"

**What They're Really Testing:** Whether you understand zstd's modern compression architecture — ANS (Asymmetric Numeral Systems) instead of Huffman, and the dictionary training pipeline.

### Answer

**zstd Architecture:**

```
zstd replaces BOTH stages of Deflate with modern alternatives:

Stage 1 — Match Finding (LZ77-like, but improved):
  - Window: up to 2GB (vs Deflate's 32KB!)
  - MML (Minimum Match Length): configurable 3+ bytes
  - Hash chain based matching (not naive scan)
  - Repcode: stores last 3 offsets → short matches use 1-2 bytes

Stage 2 — Entropy Coding:
  - NOT Huffman — uses Finite State Entropy (FSE)
  - Based on ANS (Asymmetric Numeral Systems) by Jarek Duda
  - tANS (table-based ANS): single encoding/decoding pass
  - Near-optimal compression: ~0.01 bits/symbol from Shannon limit
  - Much faster decode than Huffman (no tree traverse)
```

**Finite State Entropy vs Huffman:**

```python
# Huffman decoding:
#   1. Read bits from stream (1 bit at a time!)
#   2. Traverse binary tree
#   3. Stop when leaf reached → output symbol
#   Problem: bit-by-bit read is serial, hard to SIMD-ize

# FSE (tANS) decoding:
#   1. Maintain a STATE value (12-20 bits)
#   2. Look up STATE in precomputed TABLE
#   3. Table entry gives: symbol, new_state, bits_to_read
#   4. Read bits_to_read from stream, update STATE
#   5. Output symbol
#   Advantage: table lookup is 1-2 instructions, easily SIMD-ized
#              Always read 8+ bits at a time → no bit-by-bit loop

# Decode speed: FSE ≈ 500 MB/s, Huffman ≈ 100-200 MB/s
# Compression ratio: FSE ≈ 1-3% better than Huffman
```

**Dictionary Compression:**

```python
# zstd dictionary = precomputed statistical model for a DOMAIN

# Training process:
#   1. Collect sample files from target domain (e.g., JSON HTTP responses)
#   2. zstd --train samples/* -o dictionary.dict
#   3. Algorithm analyzes samples:
#      - Common substrings (field names: "user_id", "timestamp")
#      - Common byte patterns (number formatting)
#      - Typical lengths of repeated fields
#   4. Produces dictionary: ~112KB of preloaded match candidates + FSE tables

# Compression WITH dictionary:
echo "{\"user_id\": 12345, \"timestamp\": 1700000000}" | \
  zstd -D dictionary.dict -o compressed.zst

# Benefits:
#   Small JSON objects (200B each):
#     Without dict: 180B → 150B (1.2:1, barely worth it)
#     With dict:    180B → 40B  (4.5:1, 300% improvement!)
#
# Large objects (10KB):
#     Without dict: 10KB → 2KB (5:1)
#     With dict:    10KB → 1.8KB (5.5:1, marginal gain)

# When dictionary helps most:
#   - Many SIMILAR small objects (< 1KB)
#   - Fixed schema (JSON, Protobuf, Avro)
#   - Server responses (API payloads)
```

**Compression Level Comparison:**

```yaml
zstd --fast (negative levels):
  --fast=1:  ~500 MB/s compression, 2.5:1 ratio
  --fast=5:  ~800 MB/s, 2.0:1
  --fast=10: ~1200 MB/s, 1.5:1 (for speed-critical paths)

zstd standard (positive levels):
  -1:  ~100 MB/s,  2.8:1   (default, sweet spot)
  -3:  ~60 MB/s,   3.0:1
  -6:  ~25 MB/s,   3.3:1
  -10: ~10 MB/s,   3.5:1
  -19: ~1 MB/s,    3.8:1   (ultra, for archival/backup)

vs gzip -6 (typical):
  ~15 MB/s compress, 2.5:1 ratio

vs gzip --best (gzip -9):
  ~5 MB/s compress, 2.7:1 ratio

Key insight: zstd -3 compresses 4× FASTER than gzip -6
             with a BETTER compression ratio!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **FSE/ANS understanding** | Can contrast ANS table-based coding vs Huffman tree traversal |
| **Dictionary mechanism** | Understands how pre-trained dictionaries bootstrap small-object compression |
| **Compression level granularity** | Knows negative levels exist for ultra-fast modes |
| **Production deployment** | Has opinions on when dictionary training is worth the operational cost |

---

## 4. Brotli: Why It Won for Web Assets

**Q:** "Google introduced Brotli as a gzip replacement for HTTP content. What made Brotli better for web assets specifically? Why didn't it replace gzip for file archives? Walk through Brotli's architecture."

**What They're Really Testing:** Whether you understand Brotli's domain-specific optimizations — larger window, context modeling, and the built-in static dictionary designed for web content.

### Answer

**Brotli Architecture:**

```
Brotli (RFC 7932) shares Deflate's 2-stage approach but with MAJOR enhancements:

Stage 1 — LZ77-like matching:
  - Window: 16KB to 16MB (configurable, default 22 bits = 4MB)
  - More match types: literal, copy with distance, 
    copy with reference to context map
  - Distance codes: 24 distance contexts (different handling for 
    close vs far matches)

Stage 2 — Entropy coding:
  - Uses NIBBLE-based prefix coding (similar to Huffman but with 
    context modeling)
  - NOT FSE/ANS — Google chose a variant of prefix coding with 
    context modeling for faster decode on mobile CPUs
  - Context modeling: separate entropy tables for different 
    "contexts" (e.g., literal after copy vs literal after literal)

The Killer Feature — Static Dictionary:
  Brotli ships with a BUILT-IN 120KB static dictionary of common
  English words, HTML tags, CSS properties, and JavaScript keywords.

  Examples from the dictionary:
    - "Content-Type", "text/html", "utf-8"  → match in 1 byte
    - "padding", "margin", "font-size"      → match in 1 byte
    - "function", "var", "return"           → match in 1 byte
    - Common English: "the", "and", "that"  → match in 1 byte
```

**Why Brotli Won for Web Content:**

```yaml
Compression ratio comparison (typical HTML+CSS+JS):

Content type          | gzip -6 | brotli -4 | brotli -11
----------------------|---------|-----------|-----------
HTML (30KB)           | 3.0:1   | 3.8:1     | 4.5:1
CSS (100KB)           | 3.5:1   | 4.5:1     | 5.5:1
JavaScript (200KB)    | 3.0:1   | 4.0:1     | 5.0:1
JSON API (5KB)        | 2.5:1   | 3.5:1     | 4.2:1
PNG (100KB, binary)   | 1.1:1   | 1.2:1     | 1.3:1
Font (WOFF, 50KB)     | 1.0:1   | 1.0:1     | 1.0:1 (already compressed)

Key insight: Brotli at quality 4 beats gzip -6 on BOTH ratio AND speed
             Brotli decodes faster than gzip on mobile CPUs

Why NOT for archives (.tar.br is rare):
  - Static dictionary designed for English + web (not general binary)
  - No embedded filename/timestamp metadata (unlike gzip)
  - Much higher memory for encoder (>100MB for level 11)
  - gzip is universal — every Unix system has it
  - .tar.gz is POSIX standard; .tar.br requires separate brotli install
```

**Brotli Decompression Performance:**

```yaml
Decompression speed (relative):
  gzip -6 decompress:  ~200 MB/s
  brotli -4 decompress: ~250 MB/s  (FASTER, because static dict avoids I/O)
  brotli -11 decompress: ~70 MB/s  (context modeling is complex)
  zstd -3 decompress:   ~500 MB/s  (zstd wins on decompress speed)

Memory during decompression:
  gzip:   ~256KB window + Huffman tables ≈ 1MB
  brotli: ~16MB window (level 4) or more + context maps ≈ 4-32MB
  zstd:   ~8MB window (default) ≈ 1-4MB
```

**Brotli Quality Levels:**

```yaml
# Brotli quality 1-11 (not negative like zstd)

Quality | Compress MB/s | Ratio | Memory (encoder) | Use Case
--------|--------------|-------|------------------|--------
1       | ~200         | 2.0:1 | 8MB              | Dynamic on-the-fly
4       | ~50          | 2.8:1 | 32MB             | CDN default
6       | ~20          | 3.2:1 | 128MB            | CDN on-demand
9       | ~5           | 3.5:1 | 256MB            | Static asset pre-compress
11      | ~1           | 3.8:1 | 1GB+             | Maximum compression (archival)

CDN strategy: brotli -4 for dynamic content, brotli -11 for static assets
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Static dictionary** | Knows the 120KB web-optimized dictionary is Brotli's key advantage |
| **Context modeling** | Understands why separate entropy contexts help for structured data |
| **CDN deployment** | Can describe quality level strategy for dynamic vs static content |
| **Memory trade-offs** | Knows encoder memory can exceed 1GB at level 11 |

---

## 5. Content-Encoding vs Transfer-Encoding

**Q:** "In HTTP, what's the difference between Content-Encoding and Transfer-Encoding? Why does HTTP/2 forbid Transfer-Encoding? How does this affect how you configure compression on a reverse proxy like nginx?"

**What They're Really Testing:** Whether you understand the HTTP layer model — end-to-end vs hop-by-hop headers, and how compression interacts with intermediaries.

### Answer

**HTTP Encoding Model:**

```
┌─────────────────────────────────────────────────────────────────────┐
│ Content-Encoding (end-to-end)                                        │
│                                                                      │
│  Origin ──────────────────────────────────────────────────→ Client  │
│   Server                       CDN / Proxy                           │
│   │                             │                                    │
│   ├─ Response compressed       ├─ Response is STILL compressed      │
│   │   with gzip/brotli         │   (CDN doesn't decompress!)        │
│   │   Content-Encoding: br     │   Content-Encoding: br             │
│   │                             │                                    │
│   └─ Client asks:              └─ Client receives:                  │
│      Accept-Encoding: gzip, br    decompresses Content-Encoding     │
│                                                                      │
│  Characteristics:                                                    │
│  - Encrypted end-to-end (TLS doesn't matter)                        │
│  - CDN caches the compressed version                                │
│  - Compression happens ONCE at origin, lasts entire chain           │
│  - The body bytes are DIFFERENT from original                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ Transfer-Encoding (hop-by-hop)                                       │
│                                                                      │
│  Origin ──────────────→ CDN ───────────────→ Client                 │
│   Server                │                                            │
│   │                     ├─ CDN receives: chunked                    │
│   ├─ Response chunked   │  Transfer-Encoding: chunked               │
│   │  Transfer-Encoding: │  Content-Encoding: gzip                   │
│   │  chunked            │  (body is still gzip-compressed)          │
│   │                     │                                            │
│   │  OR:                ├─ CDN DECOMPRESSES Transfer-Encoding       │
│   │  Transfer-Encoding: │  Re-encodes for client                    │
│   │  gzip (rare)        │  (proxy transform)                         │
│   │                     │                                            │
│  Characteristics:                                                    │
│  - Applies ONLY to one connection hop                               │
│  - Proxies MUST remove TE before forwarding                         │
│  - TE: chunked is the only one broadly supported                   │
│  - TE: gzip is deprecated (intermediaries handle it poorly)         │
└─────────────────────────────────────────────────────────────────────┘
```

**Why HTTP/2 Forbids Transfer-Encoding:**

```yaml
HTTP/2's framing layer REPLACES Transfer-Encoding:
  - HTTP/1.1: chunked encoding for streaming → Transfer-Encoding: chunked
  - HTTP/2: DATA frames with END_STREAM flag → no need for chunked
  - HTTP/2 explicitly forbids Transfer-Encoding header per RFC 7540 §8.2.2

Impact on compression:
  - Content-Encoding: gzip/br → works identically in HTTP/2 and HTTP/3
  - No more Transfer-Encoding: gzip → intermediaries must not transform
  - End-to-end compression is the ONLY model in HTTP/2+
```

**Nginx Configuration Implications:**

```nginx
# Content-Encoding compression (RECOMMENDED):
gzip on;
gzip_types text/plain text/css application/json application/javascript;

# OR with Brotli:
brotli on;
brotli_types text/plain text/css application/json application/javascript;
brotli_comp_level 6;

# NEVER do this for reverse proxy:
# (Transfer-Encoding compression is a bad idea)
proxy_set_header Accept-Encoding "";  # DON'T strip client's AE!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **End-to-end vs hop-by-hop** | Clearly distinguishes Content-Encoding from Transfer-Encoding |
| **HTTP/2 framing** | Understands how HTTP/2 frames replace chunked encoding |
| **CDN caching** | Knows Content-Encoding preserves compressed body through cache |
| **Nginx config** | Can write correct compression config for reverse proxy |

---

## 6. Compression Level Trade-offs: Speed vs Ratio

**Q:** "Your API serves 50KB JSON responses. You currently compress with gzip level 6. You want to reduce p99 latency. Walk me through the dynamic compression decision: should you use a lower level, switch to zstd, pre-compress, or use Brotli? What's the breakeven point?"

**What They're Really Testing:** Whether you systemically evaluate compression trade-offs — CPU cost, bandwidth savings, client decode time, and the benefits of pre-compression.

### Answer

**Compression Decision Framework:**

```python
# The equations that matter:

# Total response time = server_compress_time + network_time + client_decompress_time
# Without compression:
#   T_no = 0 + payload_size / bandwidth + 0
#
# With compression:
#   T_comp = compress_time + (payload_size / ratio) / bandwidth + decompress_time
#
# Breakeven bandwidth:
#   bandwidth_breakeven = payload_size × (1 - 1/ratio) / (compress_time + decompress_time)

# Example: 50KB JSON, gzip -6, ratio=3:1
#   T_no = 0 + 50KB / 100Mbps + 0 = 4ms
#   T_comp = 3ms + 16.7KB / 100Mbps + 0.5ms = 3ms + 1.3ms + 0.5ms = 4.8ms
#   → Compression ADDS latency on fast networks!
#   → On slow networks (5Mbps mobile):
#     T_no = 80ms
#     T_comp = 3ms + 26.7ms + 0.5ms = 30.2ms → 62% improvement!
```

**Comparison for the 50KB JSON Case:**

```yaml
Scenario: API returning 50KB JSON, 100 requests/second

Algorithm  | Level | Ratio | Compress | Decompress | Network  | Total
           |       |       | (server) | (client)   | (10Mbps) | (10Mbps)
-----------|-------|-------|----------|------------|----------|---------
No comp    | -     | 1:1   | 0ms      | 0ms        | 40ms     | 40ms
gzip       | 1     | 2.2:1 | 1ms      | 0.3ms      | 18ms     | 19.3ms
gzip       | 6     | 3.0:1 | 3ms      | 0.5ms      | 13ms     | 16.5ms
gzip       | 9     | 3.2:1 | 10ms     | 0.5ms      | 12.5ms   | 23ms
zstd       | -1    | 2.0:1 | 0.1ms    | 0.1ms      | 20ms     | 20.2ms
zstd       | 3     | 3.2:1 | 0.5ms    | 0.1ms      | 12.5ms   | 13.1ms
zstd       | 10    | 3.5:1 | 5ms      | 0.1ms      | 11.4ms   | 16.5ms
brotli     | 4     | 3.5:1 | 1ms      | 0.2ms      | 11.4ms   | 12.6ms
brotli     | 6     | 4.0:1 | 2.5ms    | 0.5ms      | 10ms     | 13ms
brotli     | 11    | 4.5:1 | 50ms     | 1ms        | 8.9ms    | 59.9ms

Winner for API (dynamic): zstd -3 or brotli -4
Winner for static assets: brotli -6 (pre-compressed at build time)
```

**Pre-compression Strategy:**

```python
# For STATIC assets, pre-compress at BUILD time:
#   gzip -k -9 style.css → style.css.gz
#   brotli -k -11 style.css → style.css.br
#   zstd -k -19 style.css → style.css.zst

# Nginx serves pre-compressed:
location /static/ {
    gzip_static on;       # Serve .gz if exists (avoids runtime compression)
    brotli_static on;     # Serve .br if exists
    gunzip on;            # Fallback for clients that don't support gzip
}

# This eliminates compress_time → ONLY network + decompress
# Total time on 10Mbps for pre-compressed brotli -11:
#   T = 0ms + 50KB/4.5/10Mbps + 1ms = 9.9ms (75% improvement over gzip -6!)
```

**Dynamic Compression Cache:**

```python
# For dynamic API responses, cache compressed versions per variant:

compression_cache = {}
COMPRESSION_VARIANTS = ['gzip-6', 'zstd-3', 'br-4']

def get_compressed_response(payload: bytes, accept_encoding: str):
    # Cache key: payload + encoding variant
    key = hash(payload) + accept_encoding

    if key in compression_cache:
        return compression_cache[key]

    # Select best variant based on client support
    if 'br' in accept_encoding:
        result = brotli_compress(payload, quality=4)
    elif 'zstd' in accept_encoding:
        result = zstd_compress(payload, level=3)
    else:
        result = gzip_compress(payload, level=6)

    compression_cache[key] = result
    return result
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Breakeven analysis** | Can compute when compression is WORTH it based on bandwidth × ratio × CPU |
| **Pre-compression** | Knows static asset compression happens at build time |
| **Level selection** | Can recommend specific levels for specific use cases |
| **Compression caching** | Understands caching compressed variants for dynamic content |

---

## 7. Dictionary Compression: Training Domain-Specific Dictionaries

**Q:** "You have a Kafka topic with 10B messages/day, each a 200-byte Avro record. gzip gives 1.5:1 compression on each record, but you need 5:1+ to reduce storage costs. Walk through how you'd train and deploy a zstd dictionary for this workload. What are the operational challenges?"

**What They're Really Testing:** Whether you understand the dictionary training pipeline end-to-end — from sample collection to deployment, and the failure modes (poisoned dictionary, stale dictionary, dictionary mismatch).

### Answer

**Dictionary Training Pipeline:**

```python
# Step 1: Collect representative samples
#   - 10,000 records from prod (NOT just test data!)
#   - Cover ALL schema versions in the last 30 days
#   - Cover edge cases: null fields, empty strings, large values
#   - Random sampling across ALL partitions (not just partition 0)

# Step 2: Train the dictionary
import subprocess

# Save samples to files
with open('/tmp/samples/record-0001.json', 'w') as f:
    json.dump(record, f)

# Train
subprocess.run([
    'zstd', '--train',
    '--maxdict', '131072',           # 128KB dictionary (sweet spot)
    '--dictID', '42',                # ID to verify at decode time
    '-r', '/tmp/samples/*.json',
    '-o', '/etc/zstd/dict/topic-orders.dict'
])

# Step 3: Verify dictionary quality
# Before train: 200B → 133B (1.5:1, gzip)
# After train:  200B → 35B  (5.7:1, zstd + dict)
```

**Compression With Dictionary:**

```python
import zstandard as zstd

# Encoder (producer side):
dict_data = open('/etc/zstd/dict/topic-orders.dict', 'rb').read()
dict = zstd.ZstdCompressionDict(dict_data)
compressor = zstd.ZstdCompressor(level=3, dict_data=dict)

compressed = compressor.compress(avro_record)
# 200 bytes → 35 bytes (5.7:1)

# Decoder (consumer side):
decompressor = zstd.ZstdDecompressor(dict_data=dict)
decompressed = decompressor.decompress(compressed)
```

**Operational Challenges:**

```yaml
Challenge 1: Dictionary Staleness
  - Schema evolves: new fields appear, old fields change meaning
  - Training from 6 months ago → dictionary doesn't know "new_field"
  - "new_field" values are stored as LITERALS → poor compression
  - Solution: re-train dictionary monthly, deploy as rolling update

Challenge 2: Dictionary Poisoning
  - If training samples include an attacker-controlled value:
    10,000 records of: {"user_id": "AAAAAAAAAAAAAAAAAAA..."}
  - Dictionary learns "AAA..." as a common pattern
  - Normal records don't match → dictionary is wasted
  - Solution: validate samples before training, filter outliers

Challenge 3: Multi-version Deployment
  - Canary deploy new dictionary to 1% of producers
  - But ALL consumers must ALSO have the dictionary to decompress
  - Deploy sequence:
    1. Deploy new dict to ALL consumers FIRST (with old dict still available)
    2. Then deploy new dict to producers
    3. Producers start producing with new dict
    4. Consumers can decode old messages with old dict, new with new dict

Challenge 4: Buffer Management
  - Dictionary must be in memory at all times → 128KB per topic
  - 100 topics × 128KB = 12.8MB (negligible for JVM heap)
  - But 100 topics × 128KB × dictionary versions = 256MB+
  - Memory budget for dictionaries: allocate up to 5 concurrent versions

Challenge 5: Kafka Record-Level Dict Usage
  - Kafka batches: producer compresses the ENTIRE batch (not per record)
  - Dictionary helps most for SMALL batches (< 100 records)
  - Large batches (1000+ records) already compress well without dict
  - Sweet spot: batch_size=16384, dictionary for first ~100 records to seed
```

**When NOT to Use Dictionaries:**

```yaml
Dictionary NOT worth it when:
  - High-entropy fields dominate (UUIDs, hashes, timestamps)
  - Schema changes more than once a week
  - Messages are large (> 10KB) — LZ77 already catches repetitions
  - You can't coordinate producer/consumer deployment
  - Batch sizes are large (> 1000 records) — batch compression is sufficient

Alternative: zstd --long (long distance matching):
  zstd --long=31  # Enable 2GB window (like dictionary but automatic)
  - No training needed
  - No deployment coordination
  - Slightly less compression than trained dict (10-20% worse)
  - Higher memory usage at decode time
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Training pipeline** | Can describe sample collection → training → validation → deployment |
| **Poisoning awareness** | Understands how outlier samples degrade dictionary quality |
| **Multi-version deployment** | Knows consumers must get dictionary BEFORE producers |
| **When to skip** | Can identify workloads where dictionaries don't help |

---

## 8. Streaming Compression vs Block Compression

**Q:** "You need to compress a 50GB log file on a machine with 4GB RAM. Explain why block compression is necessary. How do gzip streaming mode, zstd block mode, and brotli's mode handle this differently? How would you design a compression format for queryable compressed logs?"

**What They're Really Testing:** Whether you understand the fundamental difference between streaming and block compression — memory constraints and random access.

### Answer

**Streaming vs Block Compression:**

```yaml
Streaming Compression (gzip default):
  ┌────────────────────────────────────────────────────────────┐
  │ Entire file processed as ONE continuous stream              │
  │                                                             │
  │ [Header][LZ77 window → Huffman → output stream]            │
  │          ↑ Sliding window grows up to 32KB                 │
  │          ↑ Decompressor must process from START             │
  │                                                             │
  │ Advantages:                                                 │
  │ - Best compression ratio (full history available)           │
  │ - Low memory at any point (32KB window)                     │
  │                                                             │
  │ Disadvantages:                                              │
  │ - NO random access (must decompress from beginning)         │
  │ - Corrupt byte in middle → lose everything after it         │
  │ - Can't parallelize compression/decompression               │
  └────────────────────────────────────────────────────────────┘

Block Compression (zstd --rsyncable, gzip --rsyncable):
  ┌────────────────────────────────────────────────────────────┐
  │ File split into INDEPENDENT blocks                          │
  │                                                             │
  │ [Block1 metadata][Block1 data][Block2 metadata][Block2]... │
  │                                                             │
  │ Each block is independently compressed:                     │
  │ - Block size: 64KB-1MB typical                             │
  │ - Each block can be decompressed WITHOUT previous blocks    │
  │ - Each block can be compressed in PARALLEL                  │
  │                                                             │
  │ Advantages:                                                 │
  │ - Random access (seek to block X, decompress only that)    │
  │ - Parallel compression (N blocks = N× speed on N cores)    │
  │ - Partial decompression (read only the bytes you need)     │
  │ - Error isolation (corruption in block 5 → only block 5 lost) │
  │                                                             │
  │ Disadvantages:                                              │
  │ - Slightly worse ratio (no cross-block history)            │
  │ - More overhead (metadata per block)                       │
  └────────────────────────────────────────────────────────────┘
```

**Algorithm-Specific Behavior:**

```python
# gzip:
#   - NATIVE streaming only (RFC 1952)
#   - --rsyncable flag: inserts sync points every ~4MB
#     Blocks can be decoded independently but WITHIN the gzip stream
#     Not truly random access — still must scan sync points
#   - Multiple members: can contain multiple gzip members concatenated
#     (gunzip handles this!) → pseudo-block compression

# zstd:
#   - NATIVE block support (called "frames")
#   - zstd --rsyncable: inserts resync points at predictable intervals
#   - ZSTD_getFrameHeader() → frame count
#   - ZSTD_decompressBlock() → decompress specific block index
#   - Key API:
#     compressed = b''
#     for block in split_into_blocks(file, block_size=262144):  # 256KB
#         compressed += zstd_compress(block)  # independent blocks!

# brotli:
#   - NATIVE streaming (like gzip)
#   - BrotliEncoderSetParameter(BROTLI_PARAM_MODE, BROTLI_MODE_TEXT)
#   - No native block compression for random access
#   - Workaround: split file, compress each part → concatenate
#     But BROTLI headers at each split → significant overhead
#     Not recommended for this use case
```

**Designing Queryable Compressed Logs:**

```python
# Design: Block-compressed columnar format for log analytics

# File format:
# [Block Index][Block 0][Block 1]...[Block N]
#
# Block Index:
#   - Byte offset of each block
#   - Min/max timestamp and key values for pruning
#   - Total size: ~0.1% of file

import struct
import zstandard as zstd

BLOCK_SIZE = 262144  # 256KB
INDEX_ENTRY = struct.Struct('!Q Q Q Q')  # offset, timestamp_min, timestamp_max, compressed_size

class QueryableCompressedLog:
    def __init__(self):
        self.blocks: list[dict] = []
        self.raw_data = b''

    def write(self, records: list[dict], path: str):
        """Write records as block-compressed file with index."""
        compressor = zstd.ZstdCompressor(level=3)
        index = []
        current_block = b''

        for record in records:
            record_bytes = json.dumps(record).encode()
            current_block += record_bytes + b'\n'

            if len(current_block) >= BLOCK_SIZE:
                compressed = compressor.compress(current_block)
                index.append({
                    'offset': len(self.raw_data),
                    'ts_min': records[0]['timestamp'],
                    'ts_max': record['timestamp'],
                    'size': len(compressed)
                })
                self.raw_data += compressed
                current_block = b''

        # Write final block
        if current_block:
            compressed = compressor.compress(current_block)
            index.append({
                'offset': len(self.raw_data),
                'ts_min': records[0]['timestamp'],
                'ts_max': records[-1]['timestamp'],
                'size': len(compressed)
            })
            self.raw_data += compressed

        # Write index at end (like Parquet footer)
        with open(path, 'wb') as f:
            f.write(self.raw_data)
            # Write index
            f.write(struct.pack('!I', len(index)))
            for entry in index:
                f.write(INDEX_ENTRY.pack(
                    entry['offset'], entry['ts_min'],
                    entry['ts_max'], entry['size']
                ))

    def query_time_range(self, path: str, ts_start: int, ts_end: int) -> list[dict]:
        """Read only blocks matching time range."""
        with open(path, 'rb') as f:
            # Read index
            f.seek(-4, 2)
            num_blocks = struct.unpack('!I', f.read(4))[0]
            f.seek(-4 - num_blocks * INDEX_ENTRY.size, 2)
            index = []
            for _ in range(num_blocks):
                off, ts_min, ts_max, size = INDEX_ENTRY.unpack(f.read(INDEX_ENTRY.size))
                if ts_min <= ts_end and ts_max >= ts_start:
                    index.append({'offset': off, 'size': size})

            # Decompress only matching blocks
            decompressor = zstd.ZstdDecompressor()
            results = []
            for entry in index:
                f.seek(entry['offset'])
                compressed = f.read(entry['size'])
                decompressed = decompressor.decompress(compressed)
                for line in decompressed.split(b'\n'):
                    if line:
                        results.append(json.loads(line))
            return results
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stream vs block** | Clearly distinguishes continuous vs per-segment compression |
| **Random access** | Can design index-based block selection for partial reads |
| **Algorithm properties** | Knows zstd has native block support, gzip needs workarounds |
| **Parallelism** | Understands block compression enables N× speedup on N cores |

---

## 9. Compression in HTTP/2 & HTTP/3: HPACK, QPACK, and Beyond

**Q:** "HTTP/2 introduced HPACK header compression, and HTTP/3 uses QPACK. How do they differ from gzip/brotli body compression? Why couldn't HTTP/2 reuse gzip for headers? Design a compression scheme for a custom binary protocol that needs to handle both headers and bodies."

**What They're Really Testing:** Whether you understand the security constraints that shaped header compression — specifically the CRIME and BREACH attacks that made adaptive compression dangerous over TLS.

### Answer

**Why Headers Need Different Compression:**

```yaml
Body compression (gzip/brotli):
  - Compresses a SINGLE LARGE blob
  - Adaptive (dictionary changes as data is processed)
  - Attacker CANNOT control both compressed CONTENT and compressed TARGET simultaneously
  - Safe over TLS (BREACH requires attacker-controlled content in same compression context)

Header compression (HPACK/QPACK):
  - Compresses SMALL structured key-value pairs
  - SHARED dictionary across requests (on the same connection)
  - Attacker CAN inject headers (via X-Forwarded-For, cookies, etc.)
  - DANGEROUS: CRIME attack (2012) exploits adaptive compressor on headers
    - Attacker injects known string into request headers
    - Observes compressed SIZE change → leaks session cookie byte by byte
    - gzip/deflate header compression in SPDY was vulnerable → HPACK required
```

**HPACK Architecture (HTTP/2):**

```
┌─────────────────────────────────────────────────────────────┐
│ HPACK (RFC 7541) — Header Compression for HTTP/2             │
│                                                              │
│ Two mechanisms:                                               │
│                                                              │
│ 1. STATIC TABLE (pre-defined, 61 entries):                   │
│    Index │ Header Name       │ Header Value                  │
│    ──────┼───────────────────┼───────────────────────────────│
│    0     │ :authority        │ —                             │
│    1     │ :method           │ GET                           │
│    2     │ :method           │ POST                          │
│    3     │ :path             │ /                             │
│    4     │ :path             │ /index.html                   │
│    5     │ :scheme           │ http                          │
│    6     │ :scheme           │ https                         │
│    ...   │                   │                               │
│    58    │ vary              │ Accept-Encoding               │
│    60    │ x-content-type-options  │ nosniff                 │
│                                                              │
│ 2. DYNAMIC TABLE (per-connection, up to settings:            │
│    SETTINGS_HEADER_TABLE_SIZE, default 4096 bytes):          │
│    - Server can PUSH headers into the table                 │
│    - Previously seen headers are REPLACED by index           │
│    - Table is FIFO: oldest entries evicted when full         │

│ Encoding:                                                    │
│  - Indexed (single byte): 1|index (7-bit prefix)             │
│  - Literal with incremental indexing: 01|index|value_length|value
│  - Literal without indexing: 0000|index|value_length|value    │
│  - NEVER adaptive → immune to CRIME attack                   │
│                                                              │
│ Example encoding:                                            │
│   :method: GET          → 0x82 (index 2 in static table)     │
│   :scheme: https        → 0x87 (index 7 in static table)     │
│   :path: /search?q=abc  → literal indexing (dynamic table)   │
│   user-agent: curl/7.68 → literal (no indexing, 1-time)      │
│                                                              │
│   Typical header compression: 800 bytes → 100-200 bytes     │
└─────────────────────────────────────────────────────────────┘
```

**QPACK Architecture (HTTP/3):**

```
┌─────────────────────────────────────────────────────────────┐
│ QPACK (RFC 9204) — Header Compression for HTTP/3 (QUIC)     │
│                                                              │
│ Why different from HPACK?                                    │
│  - QUIC is out-of-order: stream A's header may be processed │
│    BEFORE stream B's header, even if B was sent first       │
│  - HPACK assumes IN-ORDER delivery (TCP guarantee)           │
│  - QPACK decouples table updates from header encoding        │
│                                                              │
│ Key difference: Encoder/Decoder Table Synchronization         │
│                                                              │
│  HPACK (in-order, TCP):                                      │
│    Stream 1: [Add to table: "custom-header: value1"]        │
│    Stream 2: [Use table index: "custom-header" → 0x?]       │
│    → Stream 2 arrives AFTER stream 1 → table has the entry   │
│                                                              │
│  QPACK (out-of-order, QUIC):                                 │
│    Stream 5: [Use table index for "custom-header"]          │
│    Stream 3: [Add to table: "custom-header: value1"]        │
│    → Stream 5 may be PROCESSED before stream 3!              │
│    → Table DOESN'T have the entry yet → can't decode!        │
│                                                              │
│  QPACK Solution:                                             │
│  - Encoder Stream: dedicated QUIC stream for TABLE UPDATES   │
│  - Request Streams: encode headers with REQUIRED KNOWN INDEX │
│  - Decoder uses Encoder Stream to build table, then decodes  │
│  - If decoder encounters unknown index → BLOCK until known   │
│  - Largest Reference: tracks which table entries are safe    │
│                                                              │
│  Result: slightly more overhead than HPACK for out-of-order  │
│          identical to HPACK when in-order                    │
└─────────────────────────────────────────────────────────────┘
```

**Custom Binary Protocol Design:**

```python
# Design a compression scheme for a custom protocol

class CustomProtocolCompressor:
    """
    Hybrid: QPACK-like for headers + zstd block for bodies
    """

    HEADER_STATIC_TABLE = {
        (b'message_type', b'request'): 0,
        (b'message_type', b'response'): 1,
        (b'version', b'1.0'): 2,
        (b'content_type', b'application/json'): 3,
        (b'content_type', b'application/protobuf'): 4,
    }

    def __init__(self):
        self.dynamic_table = OrderedDict()
        self.table_size = 0
        self.max_table_size = 4096

    def compress_message(self, headers: list[tuple], body: bytes) -> bytes:
        # Header compression: QPACK-like (table with encoder stream)
        header_stream = self._compress_headers(headers)

        # Body compression: zstd with pre-trained dictionary
        body_compressed = zstd_compress(body, level=3)

        return header_stream + b'\x00' + body_compressed

    def _compress_headers(self, headers: list[tuple]) -> bytes:
        result = b''
        for name, value in headers:
            # Check static table
            key = (name, value)
            idx = self.HEADER_STATIC_TABLE.get(key)
            if idx is not None:
                result += bytes([0x80 | idx])  # Indexed (1 byte!)
                continue

            # Check dynamic table
            if key in self.dynamic_table:
                idx = len(self.HEADER_STATIC_TABLE) + self.dynamic_table[key]
                result += bytes([0x80 | idx])
                continue

            # Literal + add to dynamic table
            self._add_to_dynamic_table(key)
            result += self._encode_literal(name, value)

        return result
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CRIME/BREACH awareness** | Understands why adaptive compression is dangerous over TLS |
| **HPACK vs QPACK** | Can explain the out-of-order table sync problem in QPACK |
| **Static vs dynamic table** | Understands the two-level lookup strategy |
| **Protocol implications** | Can design compression for custom protocols |

---

## 10. Production Compression Strategy: When to Compress, What to Skip

**Q:** "As a Staff Engineer, design a company-wide compression strategy. What gets compressed, at what level, with what algorithm? Consider: API responses, static assets, log files, database backups, Kafka messages, and inter-datacenter replication traffic."

**What They're Really Testing:** Whether you can make organization-level decisions about compression — balancing CPU cost, bandwidth savings, latency impact, and operational complexity across diverse workloads.

### Answer

**Compression Decision Matrix:**

```yaml
Workload           | Algorithm | Level | Strategy          | Rationale
-------------------|-----------|-------|-------------------|------------------------------------------
API responses      | brotli    | 4     | Dynamic negotiate | Best ratio for text, fast decode on mobile
Static assets      | brotli    | 11    | Pre-compress      | CPU doesn't matter, max ratio at build time
Log files (disk)   | zstd      | 3     | Streaming         | Fast compress/decompress, good ratio
Log files (archive)| zstd      | 19    | Block + index     | Max ratio + queryable with block index
DB backups         | zstd      | 6     | Parallel blocks   | Fast enough, reliable, good ratio
Kafka messages     | zstd      | 3     | Per-batch         | Best speed/ratio trade-off for streaming
Inter-DC traffic   | zstd-fast | -1    | Streaming tunnel  | Bandwidth cheap, latency critical
Database WAL       | lz4       | -     | Per-page          | Must be near-zero CPU overhead
Images/Video       | NONE      | -     | Skip              | Already compressed (JPEG/PNG/WebP)
Binary blobs       | NONE      | -     | Skip first        | Check magic bytes, skip if already compressed
```

**Implementation Details:**

```yaml
# 1. API Responses (nginx config)
http {
    # Brotli for modern clients, gzip for legacy
    brotli on;
    brotli_types text/plain text/css application/json application/javascript
                 text/xml application/xml application/xml+rss text/javascript
                 image/svg+xml;
    brotli_comp_level 4;
    brotli_static on;        # pre-compressed .br files for static assets

    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
    gzip_comp_level 3;       # reduced from 6 — brotli handles the heavy lifting
    gzip_static on;          # pre-compressed .gz for legacy clients
    gzip_vary on;            # Vary: Accept-Encoding for CDN correctness

    # NEVER compress:
    # - Already compressed (JPEG, PNG, MP4, WebP, WOFF2)
    # - Very small responses (< 1400 bytes, fits in single TCP packet)
    gzip_types !image/jpeg !image/png !video/mp4 !font/woff2;
}

# 2. Kafka Messages (producer config)
producer.properties:
  compression.type: zstd
  compression.level: 3
  # zstd at level 3 compresses 4× faster than gzip with BETTER ratio
  # No dictionary needed for typical Kafka batch sizes (10-100KB)

# 3. Log Files (logrotate config)
/var/log/app/*.log {
    daily
    compress
    compresscmd /usr/bin/zstd
    compressoptions -3
    compressext .zst
    uncompresscmd /usr/bin/zstd
    uncompressoptions -d
}

# 4. Database Backups (pg_dump with custom format)
pg_dump \
    --format=custom \
    --compress=6 \          # zstd level 6 (internal pg_dump supports zstd)
    --file=backup.dump \
    mydatabase

# Or parallel dump with compression:
pg_dump \
    --jobs=4 \
    --file=/backups/db-$(date +%Y%m%d).sql \
    mydatabase | zstd -6 -T4 -o backup.sql.zst
```

**When NOT to Compress:**

```yaml
# 1. Very small payloads (< MTU = ~1400 bytes)
#    Compressing a 200-byte JSON response:
#    - Before compression: 200 bytes (1 TCP packet)
#    - After compression: ~80 bytes compressed + 20 bytes gzip header = 100 bytes
#    - Still 1 TCP packet! No network savings!
#    - CPU wasted on compression + decompression
#    Rule: don't compress anything that fits in one TCP packet

# 2. Already compressed content
#    JPEG, PNG, WebP, MP4, WOFF2 are already highly compressed
#    zstd on JPEG: 500KB → 495KB (1% gain, 100% CPU waste)
#    Check Content-Type before compressing

# 3. Real-time streams with < 5ms budget
#    zstd -1: ~100ms/GB added latency
#    If you have 5ms budget, use NO compression or LZ4

# 4. Content that changes every request
#    Session tokens, unique IDs, timestamps, nonces
#    These are HIGH ENTROPY → barely compressible
#    Worse: they pollute the compression window for nearby compressible data
#    Solution: split response into compressible + incompressible parts
```

**Compression-Aware CDN Configuration:**

```yaml
# CloudFront / Cloudflare / Fastly CDN strategy:
#
# Cache key: include Accept-Encoding
#   - Caches BROTLI compressed version separately from GZIP
#   - Different cache entries for different encodings
#
# Origin shield compression:
#   - Origin compresses ONCE with brotli -6
#   - CDN caches brotli version
#   - CDN transcodes to gzip for legacy clients (or passes through)
#
# Pre-warm strategy:
#   - Pre-compress ALL static assets at build time
#   - Deploy .br files alongside originals
#   - CDN serves pre-compressed .br files directly
#   - Zero origin CPU for compression!

# Origin server header:
Cache-Control: public, max-age=31536000, immutable
Content-Encoding: br
Vary: Accept-Encoding
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **System-level thinking** | Can design a coherent strategy across diverse workloads |
| **Per-workload optimization** | Understands that database backups ≠ API responses ≠ Kafka messages |
| **Cost modeling** | Can articulate when compression CPU cost outweighs bandwidth savings |
| **Just-right compression** | Knows that excessive compression (brotli -11 for dynamic APIs) is WORSE than none |

---

> *All 10 questions cover the full breadth of compression technology — from algorithm internals to production deployment at scale. Master these and you'll demonstrate Staff-level depth in one of the most underappreciated areas of infrastructure engineering.*
