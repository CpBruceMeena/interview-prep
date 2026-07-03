# 🌐 Nginx — Staff-Level Interview Questions

> *10 questions covering Nginx internals, event-driven architecture, reverse proxying, performance optimization, and operational excellence — every question expects principal engineer-level depth with production deployment insight.*

---

## Table of Contents

1. [Event-Driven Architecture: Master/Worker Process Model](#1-event-driven-architecture-masterworker-process-model)
2. [Event Loop Internals: epoll, kqueue, io_uring](#2-event-loop-internals-epoll-kqueue-io_uring)
3. [Reverse Proxy Mechanics: Connection Pooling & Buffering](#3-reverse-proxy-mechanics-connection-pooling--buffering)
4. [Load Balancing Algorithms & Health Checks](#4-load-balancing-algorithms--health-checks)
5. [SSL/TLS Termination Optimization](#5-ssltls-termination-optimization)
6. [Static File Serving & sendfile Zero-Copy](#6-static-file-serving--sendfile-zero-copy)
7. [Connection Handling: Keepalive, Timeouts, and Backpressure](#7-connection-handling-keepalive-timeouts-and-backpressure)
8. [Nginx Configuration Patterns for High Traffic](#8-nginx-configuration-patterns-for-high-traffic)
9. [Nginx vs Caddy vs Envoy vs HAProxy](#9-nginx-vs-caddy-vs-envoy-vs-haproxy)
10. [Troubleshooting Nginx in Production](#10-troubleshooting-nginx-in-production)

---

## 1. Event-Driven Architecture: Master/Worker Process Model

**Q:** "Explain Nginx's master/worker process architecture in detail. How does it compare to Apache's process-per-connection or thread-per-connection model? What happens during a graceful reload (nginx -s reload) at the process level?"

**What They're Really Testing:** Whether you understand the fundamental architectural decision that made Nginx famous — asynchronous, event-driven, non-blocking I/O vs synchronous, thread/process-per-connection.

### Answer

**Nginx Process Model:**

```
┌─────────────────────────────────────────────────────────────────┐
│                        MASTER PROCESS (PID 1)                    │
│                                                                  │
│  Responsibilities:                                               │
│  - Reads and validates configuration                             │
│  - Creates listening sockets (bind)                              │
│  - Forks worker processes                                        │
│  - Monitors worker health (SIGCHLD)                             │
│  - Reloads configuration (SIGHUP)                                │
│  - Gracefully upgrades binary (SIGUSR2)                          │
│  - Reopens log files (SIGUSR1)                                  │
│                                                                  │
│  Does NOT handle any client connections!                         │
└─────────────────────────────────────────────────────────────────┘
         │ forks
         ├─────────────────┬─────────────────┬─────────────────┐
         ▼                 ▼                 ▼                 ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  Worker 1     │  │  Worker 2     │  │  Worker N     │  │ Cache Manager │
│  (CPU 0)      │  │  (CPU 1)      │  │  (CPU N-1)    │  │               │
├───────────────┤  ├───────────────┤  ├───────────────┤  ├───────────────┤
│ Event loop:   │  │ Event loop:   │  │ Event loop:   │  │ Manages       │
│ accept()      │  │ accept()      │  │ accept()      │  │ disk cache    │
│ read()        │  │ read()        │  │ read()        │  │ filesystem    │
│ process       │  │ process       │  │ process       │  │ expiration    │
│ write()       │  │ write()       │  │ write()       │  │ cleanup       │
│ close()       │  │ close()       │  │ close()       │  │               │
└───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘

Key design principle: ONE worker per CPU core
Workers are SINGLE-THREADED (no locks, no contention)
Workers use non-blocking I/O with event notification
```

**Apache vs Nginx:**

```yaml
Apache MPM (Multi-Processing Module):

  MPM prefork (old, but stable):
    Process per connection (500 connections = 500 processes)
    Each process: 2-10MB → 500 connections = 1-5GB RAM!
    Context switch overhead for ALL connections
    For CPU-bound, blocking (mod_php) workloads

  MPM worker (threaded):
    Thread per connection (500 connections = 500 threads)
    Thread: ~200-500KB → 500 connections = 100-250MB RAM
    Better than prefork, but still per-connection overhead
    Thread safety concerns (mod_php is NOT thread-safe!)

  MPM event (modern):
    Event-driven like Nginx, but still has thread pool
    Better than worker, but NOT as efficient as Nginx
    PHP bottlenecks still apply (blocking)

Nginx:
  Single-threaded worker per CPU core
  No per-connection process/thread
  Memory per connection: ~500 bytes (idle keepalive) to ~10KB (active)
  10,000 idle connections: ~5MB RAM (vs Apache prefork: 20GB!)
  10,000 active connections: ~100MB RAM

  The trade-off: blocking modules are IMPOSSIBLE
    - Can't embed PHP/Node.js in Nginx worker
    - Must use FastCGI or reverse proxy for application code
    - Nginx is a REVERSE PROXY + WEB SERVER, not an app server
```

**Graceful Reload (nginx -s reload):**

```
Phase 1: Master reads new config
  1. Master process receives SIGHUP
  2. Master reads and parses new nginx.conf
  3. If config is INVALID → master logs error, keeps running with OLD config
  4. If config is VALID → proceed to Phase 2

Phase 2: Fork new workers
  5. Master creates new listening sockets (port reuse)
  6. Master forks NEW set of workers (with new config)
  7. New workers start accepting connections (SO_REUSEPORT on Linux 3.9+)

Phase 3: Graceful shutdown of old workers
  8. Master sends SIGQUIT to OLD workers
  9. Old workers stop accepting new connections
  10. Old workers continue processing EXISTING connections
  11. Old workers exit when all existing connections complete
  12. If old workers don't exit within worker_shutdown_timeout (default: 30s),
      master sends SIGTERM (force kill)
```

**Binary Upgrade (Zero-Downtime):**

```bash
# Phase 1: Send USR2 to old master
kill -USR2 $(cat /var/run/nginx.pid)

# Phase 2: Old master renames PID file, starts new master
#   /var/run/nginx.pid → /var/run/nginx.pid.oldbin
#   New master writes new PID to /var/run/nginx.pid

# Phase 3: Send WINCH to old master (graceful shutdown of old workers)
kill -WINCH $(cat /var/run/nginx.pid.oldbin)

# Phase 4: Verify new workers are healthy

# Phase 5: Send QUIT to old master (fully switch)
kill -QUIT $(cat /var/run/nginx.pid.oldbin)

# To rollback:
kill -HUP $(cat /var/run/nginx.pid.oldbin)   # Restart old workers
kill -QUIT $(cat /var/run/nginx.pid)           # Stop new master
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Process model** | Can diagram master/worker and explain why workers are single-threaded |
| **Apache comparison** | Understands the fundamental architecture difference and its implications |
| **Graceful reload** | Can walk through the 3-phase config reload without connection loss |
| **Binary upgrade** | Knows the 5-phase zero-downtime upgrade procedure |

---

## 2. Event Loop Internals: epoll, kqueue, io_uring

**Q:** "Walk through Nginx's event loop in detail. How does it use epoll on Linux? What's the difference between edge-triggered and level-triggered notifications? How did io_uring change the game for Nginx performance?"

**What They're Really Testing:** Whether you understand the kernel mechanisms Nginx depends on — epoll readiness notification vs io_uring async completion, and the implications for event-driven architecture.

### Answer

**Nginx Event Loop (Linux epoll):**

```
Nginx worker main loop (pseudo-code):

while (!quit) {
    // Step 1: Get ready events from kernel
    // epoll_wait with timeout (default: 500ms)
    nfds = epoll_wait(epoll_fd, events, maxevents, timeout);

    // Step 2: Process each ready event
    for (i = 0; i < nfds; i++) {
        connection = events[i].data.ptr;  // Event carries connection context

        if (events[i].events & EPOLLIN) {
            // Data available to READ
            handle_read_event(connection);
        }

        if (events[i].events & EPOLLOUT) {
            // Socket ready to WRITE
            handle_write_event(connection);
        }

        if (events[i].events & (EPOLLERR | EPOLLHUP)) {
            // Error or hangup
            handle_error_event(connection);
        }
    }

    // Step 3: Process timer events (timeouts, keepalive)
    process_timer_events();

    // Step 4: Process post-events (deferred work)
    process_post_events();
}
```

**Edge-Triggered vs Level-Triggered:**

```text
Level-Triggered (LT) — Default epoll behavior:
  ┌─────────────────────────────────────────────────────────┐
  │ Socket buffer has 100 bytes:                             │
  │   epoll_wait → EPOLLIN → read 50 bytes                  │
  │   epoll_wait → EPOLLIN (still has 50 bytes!) → read 50  │
  │   epoll_wait → (no EPOLLIN, buffer empty)               │
  │                                                          │
  │ Simple: just read until done, kernel re-notifies         │
  │ Safe: you can miss data, kernel reminds you              │
  │ But: can cause spurious wakeups on high-traffic sockets  │
  └─────────────────────────────────────────────────────────┘

Edge-Triggered (ET) — Nginx default:
  ┌─────────────────────────────────────────────────────────┐
  │ Socket buffer has 100 bytes:                             │
  │   epoll_wait → EPOLLIN                                   │
  │   → YOU MUST READ ALL DATA (or miss it!)                 │
  │   → read in loop until EAGAIN / EWOULDBLOCK              │
  │                                                          │
  │   read 20 bytes → still has 80                           │
  │   read 80 bytes → buffer empty                           │
  │   read → EAGAIN (no more data)                           │
  │                                                          │
  │ Efficient: one notification per event change             │
  │ Risky: must handle partial reads correctly               │
  │ Best: lower CPU, fewer syscalls                          │
  │                                                          │
  │ Nginx uses ET with its own read buffer management:       │
  │   ngx_event_accept() sets ET on listening socket         │
  │   ngx_epoll_process_events() handles ET semantics        │
  └─────────────────────────────────────────────────────────┘

Why Nginx chose ET:
  - LT can cause thundering herd on accept (multiple workers wake for 1 connection)
  - ET + SO_REUSEPORT = each connection delivered to exactly ONE worker
  - ET reduces epoll_wait returns per connection from 2+ to 1
  - Lower CPU usage under high connection counts (100K+)
```

**io_uring — The Future (Linux 5.1+, Nginx 1.25+):**

```
Traditional (epoll) I/O path:
  read(fd, buf, count) → syscall → kernel copies to buf → return → app processes
  ┌──────┐    syscall    ┌─────────┐
  │ App  │ ───────────→ │ Kernel  │
  │      │ ←─────────── │         │
  │      │    return     │   I/O   │
  │      │               │  done!  │
  └──────┘               └─────────┘
  Each I/O operation = 1 syscall = ~100ns-1μs overhead
  For 100K requests/sec → 100K syscalls/sec → 10ms+ just in syscall overhead

io_uring I/O path:
  Submission Queue (SQ)        Completion Queue (CQ)
  ┌─────────────────┐          ┌─────────────────┐
  │ SQE: read(fd=5) │          │ CQE: bytes=4096 │
  │ SQE: read(fd=6) │          │ CQE: bytes=8192 │
  │ SQE: open(path) │          │ CQE: fd=7       │
  └─────────────────┘          └─────────────────┘
          │                              ▲
          │ submit (1 syscall)           │ reap (1 syscall)
          ▼                              │
  ┌───────────────────────────────────────────┐
  │              Kernel                        │
  │  Processes SQEs in parallel (DMA, async)  │
  │  Places results in CQ                     │
  └───────────────────────────────────────────┘

  Batch 32 SQEs → 1 syscall (io_uring_enter)
  Batch 32 CQEs → 1 syscall (io_uring_enter)
  → 64 I/O operations → 2 syscalls = 32× reduction in syscall overhead!

Nginx + io_uring benefits:
  - Zero-copy file serving (splice between file and socket in kernel)
  - Asynchronous openat() (no blocking on file open)
  - Statx() batching (reduce stat calls for directory listings)
  - 15-30% throughput improvement on static file serving
  - Especially beneficial on fast NVMe storage (where CPU is bottleneck)
```

**kqueue (macOS/BSD) — Nginx's Event System:**

```
kqueue is more flexible than epoll:
  - Can monitor: socket events, file changes, process events, signal events
  - EVFILT_READ / EVFILT_WRITE (socket I/O)
  - EVFILT_VNODE (file changes)
  - EVFILT_PROC (process events)
  - EVFILT_TIMER (one-shot timers, no need for separate timer wheel)

Nginx's cross-platform abstraction:
  ngx_epoll_module.c (Linux)
  ngx_kqueue_module.c (macOS/BSD)
  ngx_poll_module.c (fallback)
  ngx_select_module.c (last resort)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ET vs LT** | Can explain the exact difference and why Nginx chose ET |
| **epoll_wait cycle** | Can diagram the event loop: wait → process events → timers → post-events |
| **io_uring** | Understands the submission/completion queue model and its advantages |
| **Cross-platform** | Knows Nginx abstracts event mechanisms behind a common interface |

---

## 3. Reverse Proxy Mechanics: Connection Pooling & Buffering

**Q:** "Nginx as a reverse proxy: walk through what happens when a client sends a POST request through Nginx to a backend application server. How does Nginx handle the proxying? What's the role of buffering? How does connection pooling work?"

**What They're Really Testing:** Whether you understand Nginx's reverse proxy internals — upstream connection management, request/response buffering strategies, and the proxy lifecycle.

### Answer

**Proxy Request Lifecycle:**

```
Client → Nginx → Backend (e.g., Gunicorn on port 8000)

Phase 1: Client request arrives
  ┌──────────┐      TCP connect      ┌──────────┐
  │  Client   │ ─────────────────→   │  Nginx   │
  │          │                       │  Worker  │
  └──────────┘                       └──────────┘
    POST /api/data HTTP/1.1             │
    Content-Type: application/json      │
    Content-Length: 1024                │
    { "data": "..." }                   │
                                          │ client_headers done
                                          │ → start reading body
                                          ▼

Phase 2: Nginx connects to upstream
  ┌──────────┐                       ┌──────────┐
  │  Nginx   │     TCP connect       │ Backend  │
  │  Worker  │ ─────────────────→    │          │
  └──────────┘                       └──────────┘
                                          │
     Config: proxy_http_version 1.1;      │
             proxy_set_header Host $host; │
                                          ▼

Phase 3: Forward request + buffer response
  ┌──────────┐   proxy_pass http://upstream;  ┌──────────┐
  │  Nginx   │ ─────────────────────────────→ │ Backend  │
  │  Worker  │     GET /api/data HTTP/1.1     │          │
  │          │     Host: example.com           │          │
  │          │     X-Real-IP: 1.2.3.4         │          │
  └──────────┘                                └──────────┘
       │  ←──────────────  200 OK, 10KB JSON  ←───────────
       │
       │  Buffer the response
       ▼

Phase 4: Stream response to client
  ┌──────────┐                       ┌──────────┐
  │  Client  │ ←─────────────────   │  Nginx   │
  │          │     HTTP/1.1 200 OK  │  Worker  │
  └──────────┘                       └──────────┘
```

**Buffering Strategies:**

```nginx
# PROXY BUFFERING (default: on)
# Nginx reads entire backend response into buffer before sending to client
proxy_buffering on;
proxy_buffer_size 4k;         # Buffer for response headers
proxy_buffers 8 16k;           # 8 buffers of 16KB each = 128KB total
proxy_busy_buffers_size 64k;  # Size of "sending to client" buffer

# WITHOUT buffering (proxy_buffering off):
#   Nginx reads from backend → writes to client synchronously
#   Problem: slow client blocks backend connection
#   Backend keeps connection open while client receives data slowly
#   100 slow clients × 30 seconds = 3000 seconds of backend connection time!

# WITH buffering (proxy_buffering on):
#   Nginx reads from backend → stores in buffer (fast, local)
#   Nginx reads from buffer → writes to client (slowly)
#   Backend connection: ~10ms (just buffer the response, done!)
#   Client connection: ~30s (slow mobile client)
#   Backend resource saved: 30s - 10ms = 29.99s!

# When to disable buffering:
#   - Server-Sent Events (SSE) or WebSocket
#   - Real-time streaming (video, audio)
#   - Large file downloads where client is fast
#   - Chunked transfer encoding responses

# When buffering SAVES you:
#   - Backend generates response in 2 seconds
#   - Client takes 10 seconds to download
#   - Without buffering: backend connection held for 10 seconds
#   - With buffering: backend connection freed in 2 seconds
```

**Connection Pooling (keepalive to upstream):**

```nginx
# Upstream keepalive connection pool
upstream backend_cluster {
    server 10.0.0.1:8000;
    server 10.0.0.2:8000;
    server 10.0.0.3:8000;

    keepalive 32;          # Max idle connections to UPSTREAM
    keepalive_requests 100; # Max requests per keepalive connection
    keepalive_timeout 60s;  # Idle keepalive timeout
}

# Without keepalive pool:
#   Request 1: Nginx → TCP connect (1ms) → send request → receive → TCP close
#   Request 2: Nginx → TCP connect (1ms) → send request → receive → TCP close
#   TCP connect per request = 3-way handshake (1 RTT) + close (4-way)
#   Total overhead: ~2ms per request on local network
#   For 10K req/s: 20 seconds of CPU wasted on TCP handshakes!

# With keepalive pool:
#   Request 1: Nginx → get idle connection from pool → send request → return to pool
#   Request 2: Nginx → get idle connection from pool → send request → return to pool
#   No TCP handshake overhead! Zero additional RTT!
#   10K req/s: zero syscall overhead for connection setup

# Pool sizing:
#   keepalive = max number of idle connections PER WORKER
#   If you have 4 workers, keepalive 32 = 128 total idle connections
#   Sizing: pool = max(worker_connections / 8, peak_connections)
```

**Request Body Buffering:**

```nginx
# Client request body buffering
client_body_buffer_size 128k;  # Buffer body in memory first
client_body_temp_path /tmp/nginx-body;  # If body > buffer, spill to disk
client_max_body_size 10m;       # Max request body size

# Without body buffering:
#   Slow client uploads (300ms over mobile) → upstream connection held open
#   Each upstream worker is blocked waiting for the complete body

# With body buffering:
#   Nginx receives the body (slowly) → stores in memory/disk
#   Once complete → forward to upstream (fast)
#   Upstream connection: 1ms (just forward already-buffered body)
#   Client connection: 300ms (slow upload, doesn't block upstream!)

# proxy_request_buffering off:
#   Fast CGI/WSGI backends (Python, Ruby) need the full body
#   Node.js / Go: can handle streaming (proxy_request_buffering off)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Buffering value** | Understands how Nginx's buffering protects slow backends from slow clients |
| **Connection pool** | Can explain keepalive pool sizing and why it eliminates TCP handshake overhead |
| **Streaming vs proxy** | Knows when to disable buffering (SSE, WebSocket, large streams) |
| **Body buffering** | Understands the trade-off: memory for client body vs upstream connection time |

---

## 4. Load Balancing Algorithms & Health Checks

**Q:** "Design an nginx upstream configuration for a microservice that has variable request processing times (50ms p50, 500ms p99). Some requests are CPU-heavy, some are I/O-bound. Compare the load balancing algorithms and recommend one. How do you handle slow backends without dropping requests?"

**What They're Really Testing:** Whether you understand the practical implications of different load balancing algorithms — not just their names, but how they behave under real-world conditions.

### Answer

**Algorithms Compared:**

```nginx
upstream microservice {
    # ── Round-Robin (default) ──
    # Distributes evenly, assumes identical capacity
    # Problem: if server A has 200ms tasks and server B has 50ms tasks,
    #          A's queue grows 4× faster than B's
    # Effective for: uniform request time, identical hardware
    server 10.0.0.1:8000;
    server 10.0.0.2:8000;
    server 10.0.0.3:8000;

    # ── Least Connections ──
    # Sends to server with fewest active connections
    # Adapts to variable request times!
    # Server A (200ms tasks): 5 active connections
    # Server B (50ms tasks):  2 active connections
    # → Next request goes to Server B (fewest connections)
    # Best for: variable processing times, heterogeneous hardware
    least_conn;

    # ── IP Hash (session persistence) ──
    # Same client IP → same backend
    # Required for: sticky sessions (PHP sessions, shopping carts)
    # Problem: uneven distribution if clients cluster behind same IP
    ip_hash;

    # ── Generic Hash (advanced routing) ──
    # Hash any variable: $request_uri, $cookie_userid
    # Consistent hashing via hash $consistent
    # Good for: cache-aware routing (same URL → same backend)
    hash $request_uri consistent;

    # ── Random Two Choices (power of two choices) ──
    # Pick 2 backends at random, choose the one with fewer connections
    # Near-optimal distribution without monitoring all backends!
    # Used by: HAProxy default, Google's internal load balancers
    random two least_conn;
}
```

**Real-World Behavior:**

```yaml
Scenario: 3 backends, 1000 req/s, p50=50ms, p99=500ms

Round-Robin behavior:
  ┌──────────┬──────────┬──────────┐
  │ Svr A    │ Svr B    │ Svr C    │
  │ 333 req/s│ 333 req/s│ 334 req/s│
  │          │          │          │
  │ Queue: 50│ Queue: 20│ Queue: 5 │  (unbalanced!)
  │ (because │          │          │
  │  a slow  │          │          │
  │  request │          │          │
  │  started)│          │          │
  └──────────┴──────────┴──────────┘
  P50 latency: 55ms  (good)
  P99 latency: 1200ms (terrible! slow requests cascade queue on Server A)

Least Connections behavior:
  ┌──────────┬──────────┬──────────┐
  │ Svr A    │ Svr B    │ Svr C    │
  │ 400 req/s│ 300 req/s│ 300 req/s│
  │          │          │          │
  │ Queue: 3 │ Queue: 2 │ Queue: 2 │  (balanced!)
  │          │          │          │
  │ (gets more requests │          │
  │  because it finishes│          │
  │  fast requests quickly)         │
  └──────────┴──────────┴──────────┘
  P50 latency: 52ms
  P99 latency: 520ms (only slightly above p99 processing time!)

Winner: least_conn for variable workloads
```

**Health Checks:**

```nginx
# ACTIVE HEALTH CHECKS (Nginx Plus only — or use nginx-upstream-check module)
# Nginx periodically connects to each backend and verifies it responds

# For open source Nginx, use PASSIVE health checks:
upstream microservice {
    server 10.0.0.1:8000 max_fails=3 fail_timeout=30s;
    server 10.0.0.2:8000 max_fails=3 fail_timeout=30s;
    server 10.0.0.3:8000 max_fails=3 fail_timeout=30s;

    # Passive health check: if server fails 3 times in 30 seconds,
    # mark it as DOWN for 30 seconds (fail_timeout)
    # After 30s, Nginx will try 1 request (slow_start)
    # If success → mark UP, if fails → back to DOWN

    # slow_start: gradually increase traffic to recovering server
    # Prevents thundering herd on a just-recovered backend
    server 10.0.0.4:8000 slow_start=30s;
}

# PROXY TIMEOUTS (critical for slow backends)
proxy_connect_timeout 5s;     # Time to establish TCP connection
proxy_read_timeout 30s;       # Time to receive response body
proxy_send_timeout 30s;       # Time to send request to upstream

# Retry on upstream error
proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
proxy_next_upstream_timeout 10s;   # Max time for all retries
proxy_next_upstream_tries 3;       # Max retry attempts
```

**Slow Backend Handling:**

```nginx
# Strategy 1: Queue requests (Nginx Plus)
# When all backends are busy, queue requests instead of returning 502
proxy_queue_size 100;    # Queue up to 100 requests
proxy_queue_timeout 5s;  # Max time in queue before 504

# Strategy 2: Circuit Breaker (manual via max_fails)
# Aggressive failure detection for degraded backends
server 10.0.0.1:8000 max_fails=1 fail_timeout=10s slow_start=60s;
# 1 failure → mark DOWN for 10s
# On recovery: 60s ramp-up (avoid connection surge)

# Strategy 3: Backup servers (for excess traffic)
server 10.0.0.1:8000;
server 10.0.0.2:8000;
server 10.0.0.3:8000;
server 10.0.0.4:8000 backup;  # Only used when all primary servers are down
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Algorithm trade-offs** | Can explain WHEN least_conn beats round-robin (variable request time) |
| **Passive health checks** | Understands max_fails/fail_timeout mechanism and slow_start |
| **Retry semantics** | Knows proxy_next_upstream config and idempotency implications |
| **Circuit breaker** | Can design aggressive failure detection with proper recovery |

---

## 5. SSL/TLS Termination Optimization

**Q:** "Your nginx terminates TLS for 50K connections per second. CPU usage is 80% on all cores, primarily in SSL handshake. Walk through the optimizations you'd make — from protocol selection, session caching, OCSP stapling, to hardware offloading."

**What They're Really Testing:** Whether you understand the full TLS performance optimization toolkit — protocol, certificate, session, and hardware layers.

### Answer

**TLS Optimization Stack:**

```nginx
# ── Layer 1: Protocol & Cipher Suite ──
server {
    listen 443 ssl;
    server_name example.com;

    # Protocol: ONLY TLS 1.2 and 1.3 (NO TLS 1.0/1.1, NO SSLv3!)
    ssl_protocols TLSv1.2 TLSv1.3;

    # Preferred ciphers (TLS 1.2):
    # Priority: speed + security
    # ECDHE for perfect forward secrecy
    # AES-GCM for hardware-accelerated AES (AES-NI)
    # CHACHA20 for mobile CPUs without AES-NI (ARM)
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers on;

    # TLS 1.3 cipher suites are NOT configurable (they're all AEAD)
    # TLS 1.3 handshake: 1-RTT (vs TLS 1.2: 2-RTT)
    # TLS 1.3 0-RTT: replay attack risk, use with caution
}
```

**TLS Handshake Performance Breakdown:**

```yaml
TLS 1.2 full handshake (no resumption):
  Step            | Time | CPU work
  ────────────────|──────|────────────────────────────
  TCP connect    | 1 RTT| 0 (kernel handles)
  ClientHello    | —    | parse + match cipher
  ServerHello    | —    | — 
  Certificate    | —    | PEM parse (I/O!)
  ServerKeyExch  | —    | ECDHE key generation (CPU intensive!)
  ClientKeyExch  | —    | ECDHE point multiplication (~50μs)
  ChangeCipher   | —    | — 
  Finished       | —    | HMAC verification
  
  Total: 2-RTT + ~100-200μs CPU per handshake
  50K handshakes/sec → 5-10 seconds of CPU = 80% on 8 cores!

TLS 1.3 full handshake:
  Step            | Time | CPU work
  ────────────────|──────|────────────────────────────
  TCP connect    | 1 RTT| 0
  ClientHello +  | —    | Server sends Certificate + Finished IN same flight
    KeyShare     | —    | Client's ECDHE shares included in first message
  ServerHello +  | —    | Server responds with its ECDHE share
    Certificate +| —    | → key derivation done!
    Finished     | —    | 
  Client Finished| —    | 
  
  Total: 1-RTT + ~50-100μs CPU per handshake
  TLS 1.3 is ~40% faster than TLS 1.2 in both latency and CPU
```

**Session Caching (Eliminate Handshakes):**

```nginx
# ── Layer 2: Session Resumption ──

# Option A: Session Cache (shared memory)
ssl_session_cache shared:SSL:10m;   # 10MB shared cache = ~40K sessions
ssl_session_timeout 4h;             # Reuse session for 4 hours

# 10MB cache with ~250 bytes per session ≈ 40,000 sessions
# Returning client with cached session: 0-RTT (no full handshake!)
# Cache hit → 0 additional CPU for SSL handshake

# Option B: Session Tickets (RFC 5077, no server-side storage)
ssl_session_tickets on;
ssl_session_ticket_key /etc/nginx/ticket.key;  # Rotate daily!

# How session tickets work:
#   1. Server issues encrypted ticket to client during first handshake
#   2. Client presents ticket on reconnect
#   3. Server decrypts → if valid → resume session
#   4. NO server-side cache needed! Perfect for load-balanced clusters
#   5. Ticket key must be SHARED across all Nginx instances in the cluster

# Session ticket key rotation:
#   0:00  generate new key (valid for 24h)
#   4:00  keep old key for validation (clients with old ticket)
#   Next 0:00: discard old key
openssl rand 80 > /etc/nginx/ticket.key  # 80 bytes = key for AES-256-CBC + HMAC-SHA256
```

**OCSP Stapling:**

```nginx
# ── Layer 3: OCSP Stapling (no browser-side revocation check) ──

# WITHOUT stapling:
#   1. Client receives certificate → "I need to check revocation"
#   2. Client makes SEPARATE HTTP request to OCSP responder
#   3. Client waits for OCSP response → extra 100-500ms latency!
#   4. If OCSP responder is down → browser may fail or proceed unverified

# WITH stapling:
#   1. Nginx fetches OCSP response (from CA) periodically
#   2. Nginx attaches (staples) OCSP response to TLS Certificate message
#   3. Client receives certificate + revocation proof IN ONE FLIGHT
#   4. No extra round trip! No dependency on OCSP responder!
#   5. Also shows you're serious about security (auditors love this)

ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/ssl/certs/ca-chain.crt;
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;
```

**Hardware Offloading:**

```yaml
Software (CPU-only):
  50K handshakes/sec → 8 cores at 80%
  No additional hardware cost
  But: CPU can't do anything else

Private Key in HSM (Hardware Security Module):
  Private key never leaves the HSM
  ECDHE key generation on hardware accelerator
  50K handshakes/sec → 4 cores at 40%
  Cost: $5K-20K (CloudHSM, Luna, etc.)

TLS Termination at Load Balancer (AWS ALB / GCP HTTP LB):
  Offload TLS to the LB
  Backend traffic is HTTP (plaintext between LB and Nginx)
  Nginx CPU: 0% for TLS
  But: traffic between LB and Nginx is unencrypted (internal VPC)

QUIC (HTTP/3) offloading:
  TLS 1.3 is REQUIRED for QUIC
  QUIC runs over UDP, not TCP
  Requires kernel bypass (XDP, DPDK) for best performance
  Nginx supports QUIC since 1.25 (experimental)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Session cache vs tickets** | Can describe the trade-off (shared memory vs stateless tickets) |
| **OCSP stapling** | Understands why it eliminates an entire round-trip for certificate validation |
| **TLS 1.3 advantages** | Knows 1-RTT vs 2-RTT and 0-RTT replay risks |
| **Hardware offloading** | Can recommend when to use HSM, LB offload, or software-only |

---

## 6. Static File Serving & sendfile Zero-Copy

**Q:** "Nginx serves static files 2-3× faster than Apache. Walk through the Linux I/O stack that makes this possible. What is sendfile? How does Nginx use it? What are the memory implications for serving a 10GB file vs a 1KB file?"

**What They're Really Testing:** Whether you understand the zero-copy data path — from disk to network without copying through userspace.

### Answer

**Traditional I/O Path (Apache with mod_files):**

```
Traditional read + write (2 copies through userspace):

  1. Disk → Page Cache (DMA, kernel)     ← 1 copy (CPU: 0, DMA engine)
  2. Page Cache → App Buffer (read())     ← 2nd copy (CPU: moves data)
  3. App Buffer → Socket Buffer (write()) ← 3rd copy (CPU: moves data)
  4. Socket Buffer → NIC (DMA, kernel)    ← 1 copy (CPU: 0, DMA engine)

  Total: 4 copies, 2 CPU copies
  For 1GB file: 2GB moved by CPU!
  Context switches: read() + write() = 2 syscalls per operation
```

**Nginx Zero-Copy Path:**

```
sendfile() path (Nginx default):

  1. Disk → Page Cache (DMA, kernel)     ← 1 copy (CPU: 0, DMA engine)
  2. Page Cache → Socket Buffer (sendfile) ← 0 copies! Kernel does it
  3. Socket Buffer → NIC (DMA, kernel)    ← 1 copy (CPU: 0, DMA engine)

  Total: 2 copies, 0 CPU copies!
  For 1GB file: 0GB moved by CPU! (DMA does it all)

  sendfile() syscall:
    sendfile(out_fd, in_fd, offset, count);
    → Kernel copies data from file's page cache directly to socket's buffer
    → No intermediate application buffer needed
    → Single syscall, no context switch overhead

  aio + sendfile:
    # For large files, use AIO (async I/O) + direct I/O
    # Avoids page cache entirely (no eviction of hot small files)
    location /downloads/ {
        directio 4m;          # Use direct I/O for files > 4MB
        sendfile on;
        output_buffers 2 1m;  # 2 buffers of 1MB for assembling
    }

  sendfile_max_chunk:
    # Limit per single sendfile call (prevent worker starvation)
    sendfile_max_chunk 2m;  # Send max 2MB per event loop iteration
```

**tcp_nopush + tcp_nodelay:**

```nginx
# ── TCP optimization for sendfile ──

# tcp_nopush: optimize for packet efficiency
tcp_nopush on;
# When sendfile is on, Nginx sends HEADERS and the beginning of the FILE
# in the SAME TCP packet (instead of separate packets for headers + data)
# Effect: 1 packet vs 2+ packets per response = fewer interrupts, more throughput
# Especially important for small files!

# tcp_nodelay: optimize for latency
tcp_nodelay on;
# Disables Nagle's algorithm (waiting for buffer to fill before sending)
# Critical for interactive responses (SSH, real-time APIs)
# sendfile() with tcp_nodelay: send data as soon as it's in the socket buffer
# Trade-off: more packets (higher overhead) but lower latency

# Nginx's smart usage:
#   - tcp_nopush: ON by default with sendfile
#   - tcp_nodelay: ON for keepalive connections
#   - They work TOGETHER: nopush packs, nodelay flushes
```

**File Size Implications:**

```yaml
Small file (1KB):
  - sendfile: one syscall, zero CPU copy → ~2μs
  - Traditional: ~5μs (more syscalls, more copies)
  - But: 1KB fits in L1 cache on modern CPUs
  - Nginx optimization: merge small files into single packet (tcp_nopush)

Medium file (1MB):
  - sendfile: one syscall, DMA does the work → ~100μs (10M req/s on NVMe)
  - Traditional: CPU copies 1MB → ~500μs (2M req/s)
  - Page cache hit: 95%+ for popular files

Large file (10GB):
  - sendfile + directio: bypasses page cache entirely
  - Without directio: page cache EVICTION disaster!
    - 10GB file displaces 10GB of otherwise useful cache
    - Other file requests will MISS cache → HDD seeks → 10ms per file
    - Cache pollution problem

  - Solution: directio for large files
    location /video/ {
        directio 4m;           # Use direct I/O for files > 4MB
        directio_alignment 512; # Block device alignment
        output_buffers 1 2m;   # 2MB buffer for assembly
    }
```

**File Serving Best Practices:**

```nginx
# Static file serving configuration
server {
    root /var/www/static;
    open_file_cache max=10000 inactive=30s;  # Cache file metadata (stat results)
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;               # Cache after 2 accesses
    open_file_cache_errors on;

    # Cache-Control headers for CDN
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
        log_not_found off;

        # Pre-compressed assets
        gzip_static on;    # Serve .gz if exists (no runtime compression)
        brotli_static on;  # Serve .br if exists

        # Security headers for static content
        add_header X-Content-Type-Options "nosniff" always;
    }

    location / {
        try_files $uri $uri/ /index.html;  # SPA fallback
    }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **sendfile mechanics** | Can explain zero-copy path with exact copy counts |
| **directio for large files** | Understands page cache pollution and when to bypass it |
| **tcp_nopush + nodelay** | Knows how these interact with sendfile for packet optimization |
| **open_file_cache** | Understands caching file metadata (stat) avoids stat() syscall |

---

## 7. Connection Handling: Keepalive, Timeouts, and Backpressure

**Q:** "Your nginx is handling 100K concurrent connections (mostly keepalive). Average response time is 50ms, but you're seeing 504 errors during traffic spikes. Walk through the connection lifecycle. How do worker_connections, keepalive_requests, and various timeouts interact? How do you design for backpressure?"

**What They're Really Testing:** Whether you understand Nginx's resource management — how connection limits, timeouts, and queue sizes interact under load.

### Answer

**Connection Lifecycle:**

```
Client connects:
  TCP SYN → Nginx accept() → allocate ngx_connection_t (~232 bytes)
  → Add to epoll → wait for data

Client sends request:
  epoll_wait → EPOLLIN → read request → process → write response
  → If response is final: wait for next request (keepalive)

Client disconnects:
  epoll_wait → EPOLLRDHUP → close connection → free ngx_connection_t

Keepalive lifecycle:
  ┌─────────┐    ┌─────────┐    ┌─────────┐         ┌─────────┐
  │ Request │    │ Idle    │    │ Request │         │ Timeout │
  │ 1       │ →  │ wait    │ →  │ 2       │ → ... → │ → close │
  └─────────┘    └─────────┘    └─────────┘         └─────────┘
  Memory: ~10KB  Memory: ~500B  Memory: ~10KB       Memory: 0
```

**Worker Connection Accounting:**

```nginx
# The critical formula:
events {
    worker_connections 1024;  # Max connections per worker
    use epoll;
}

# Max concurrent connections = worker_processes × worker_connections
# 4 workers × 1024 = 4096 concurrent connections

# But: each worker connection includes:
#   - Client connection (inbound)
#   - Upstream connection (outbound, if proxying)
#   - Cache file descriptor (if caching)
#   - Log file descriptor

# So for a reverse proxy:
#   worker_connections = client_connections + upstream_connections + overhead
#   Each proxied request: client_conn + upstream_conn = 2 connections
#   Effective capacity: worker_connections / 2 per worker

# Connection state breakdown:
#   ┌────────────────────────────────────────┐
#   │ Active requests: 200                   │
#   │   └─ Reading request:  50              │
#   │   └─ Writing response: 150             │
#   │ Idle keepalive:      800               │
#   │ Available:            24 (1024-1000)   │  ← THIS IS THE PROBLEM
#   └────────────────────────────────────────┘
#   Only 24 available for NEW connections!
#   If 100 clients connect simultaneously → 76 get denied!
```

**Backpressure Design:**

```yaml
Problem: 100K idle keepalive connections consume worker connection slots
           leaving few slots for new connections.

Solution 1: Aggressive keepalive limits
  keepalive_requests 100;      # Max requests per keepalive connection
  keepalive_timeout 30s;        # Idle timeout (was 300s!)

  Effect: Clients reuse connections 100×, then reconnect
          Idle connections expire in 30s instead of 5min
          → Freed connection slots → more capacity for new connections

Solution 2: Connection queue (listen backlog)
  listen 80 backlog=4096;       # SYN queue size (default: 511)
  
  When all workers are busy (epoll_wait → all connections active):
    - New TCP SYNs go to SYN queue (backlog)
    - Nginx accept()s from SYN queue when connections free up
    - If SYN queue full → kernel drops SYN → client retries (TCP retransmit)
    - Retry in 3s, 6s, 12s... (exponential backoff)
    - Client experiences CONNECTION_TIMEOUT (not 502/503!)

Solution 3: Rate limiting (limit connections)
  limit_conn_zone $binary_remote_addr zone=addr:10m;

  server {
      location /api/ {
          limit_conn addr 10;         # Max 10 concurrent connections per IP
          limit_conn_status 429;      # Too Many Requests
          limit_conn_log_level error;
      }
  }

Solution 4: Request queuing with timeout
  client_header_timeout 10s;     # Time to receive complete headers
  client_body_timeout 10s;       # Time to receive complete body
  send_timeout 10s;              # Time to send response to client

  Without these:
    - Slow client takes 60s to send request → blocks connection for 60s
    - 1000 slow clients × 60s = 1000 connections blocked for 1 minute
    - No capacity for legitimate requests!

  With aggressive timeouts:
    - Slow client gets 30s to send headers → 10s to send body
    - If exceeded → Nginx returns 408 and closes
    - Connection freed in < 30s instead of 60s+
```

**Connection Pool Accounting:**

```nginx
# Tuning for 100K concurrent connections

worker_processes auto;            # Typically: one per CPU core
worker_rlimit_nofile 30000;       # OS max open files (ulimit -n)

events {
    worker_connections 10000;     # Per worker
    # Total: 4 workers × 10000 = 40000 possible connections
    # But OS max: worker_rlimit_nofile = 30000 per process
    # Effective: min(worker_rlimit_nofile, worker_connections) per worker

    multi_accept on;              # Accept MULTIPLE connections per event
    accept_mutex on;              # Avoid thundering herd on accept()
    accept_mutex_delay 500ms;     # Wait before trying to accept next
}

# Keepalive management
keepalive_requests 1000;          # Reuse connection 1000 times
keepalive_timeout 30s;            # Idle keepalive: 30 seconds

# Timeouts (aggressive)
client_header_timeout 10s;
client_body_timeout 10s;
send_timeout 10s;
lingering_close 5s;
lingering_time 30s;
```

**Monitoring Connection States:**

```bash
# Check current connection state:
curl http://localhost/nginx-status  # Requires ngx_http_stub_status_module

# Active connections: 245
#   server accepts handled requests
#   10500 10500 42000
#   Reading: 5 Writing: 40 Waiting: 200
#
# Reading:  worker reading request headers/body    (5)
# Writing:  worker sending response                 (40)
# Waiting:  idle keepalive connections              (200) ← THE KEY METRIC!
#
# If Waiting grows close to worker_connections,
# you have too many idle keepalive connections!

# Prometheus metrics (nginx-exporter):
# nginx_connections_active
# nginx_connections_reading
# nginx_connections_writing
# nginx_connections_waiting

# Alerts:
#   nginx_connections_waiting > 0.8 × worker_connections → scale up or reduce keepalive_timeout
#   nginx_connections_writing > 0.5 × worker_connections → backend slow (upstream issue)
#   nginx_connections_reading > 0.3 × worker_connections → client body buffering issue
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Connection accounting** | Can compute effective capacity = workers × connections / 2 (proxy) |
| **Keepalive impact** | Understands idle keepalive connections CONSUME worker slots |
| **Backpressure strategy** | Can design timeouts + queues + limit_conn for traffic spikes |
| **Monitor state** | Knows the Reading/Writing/Waiting triplet and what each means |

---

## 8. Nginx Configuration Patterns for High Traffic

**Q:** "Design an Nginx configuration for a globally distributed SaaS platform serving 50K requests/second. Include: API gateway routing, rate limiting, caching, microservice routing, WebSocket support, and multi-region failover."

**What They're Really Testing:** Whether you can compose Nginx's many features into a coherent, production-ready configuration — not just for a single server, but as an API gateway / reverse proxy layer.

### Answer

**Complete Production Configuration:**

```nginx
# ── Core Settings ──
user nginx;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /var/run/nginx.pid;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
    accept_mutex on;
    accept_mutex_delay 500ms;
}

# ── HTTP Block ──
http {
    # Basic settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    server_tokens off;

    # Timeouts
    keepalive_requests 1000;
    keepalive_timeout 30s;
    client_header_timeout 10s;
    client_body_timeout 10s;
    send_timeout 10s;
    resolver_timeout 5s;

    # Buffer sizing
    client_body_buffer_size 128k;
    client_max_body_size 10m;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    output_buffers 2 64k;

    # File cache
    open_file_cache max=10000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;

    # Logging
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" $request_time '
                    '$upstream_addr $upstream_status';
    access_log /var/log/nginx/access.log main buffer=32k flush=5s;
    error_log /var/log/nginx/error.log warn;

    # ── Rate Limiting Zones ──
    # Global: 100 req/s per IP
    limit_req_zone $binary_remote_addr zone=global:10m rate=100r/s;
    # API: 1000 req/s per IP
    limit_req_zone $binary_remote_addr zone=api:10m rate=1000r/s;
    # Burst: 50 req/s per IP for sensitive endpoints
    limit_req_zone $binary_remote_addr zone=auth:10m rate=50r/s;

    # Connection limiting
    limit_conn_zone $binary_remote_addr zone=conn:10m;

    # ── Upstream Backends ──
    upstream api_servers {
        least_conn;
        keepalive 64;
        keepalive_requests 100;
        keepalive_timeout 60s;

        # Primary region
        server api-primary-1.internal:8080 max_fails=3 fail_timeout=30s;
        server api-primary-2.internal:8080 max_fails=3 fail_timeout=30s;

        # Secondary region (dr-*)
        server api-dr-1.internal:8080 max_fails=3 fail_timeout=30s backup;
        server api-dr-2.internal:8080 max_fails=3 fail_timeout=30s backup;
    }

    upstream websocket_servers {
        ip_hash;  # Session stickiness for WebSocket
        keepalive 32;
        server ws-1.internal:9090 max_fails=3 fail_timeout=30s;
        server ws-2.internal:9090 max_fails=3 fail_timeout=30s;
    }

    upstream auth_servers {
        least_conn;
        keepalive 16;
        server auth-1.internal:8443 max_fails=3 fail_timeout=10s;
        server auth-2.internal:8443 max_fails=3 fail_timeout=10s;
    }

    # ── Cache Zone ──
    proxy_cache_path /var/cache/nginx/api levels=1:2 keys_zone=api_cache:100m
                     max_size=10g inactive=60m use_temp_path=off;

    # ── Main Server ──
    server {
        listen 80 default_server;
        listen 443 ssl http2 default_server;
        server_name api.example.com;

        # SSL configuration (optimized)
        ssl_certificate /etc/ssl/certs/api.example.com.pem;
        ssl_certificate_key /etc/ssl/private/api.example.com.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-CHACHA20-POLY1305';
        ssl_prefer_server_ciphers on;
        ssl_session_cache shared:SSL:50m;
        ssl_session_timeout 4h;
        ssl_session_tickets on;
        ssl_session_ticket_key /etc/nginx/ticket.key;
        ssl_stapling on;
        ssl_stapling_verify on;
        ssl_trusted_certificate /etc/ssl/certs/ca-chain.crt;

        # Security headers
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        # ── Global Rate Limiting ──
        limit_req zone=global burst=200 nodelay;
        limit_conn conn 20;

        # ── Health Check Endpoint ──
        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        # ── Static Assets ──
        location /static/ {
            root /var/www/static;
            expires 1y;
            add_header Cache-Control "public, immutable";
            access_log off;
            gzip_static on;
            brotli_static on;
        }

        # ── API Gateway ──
        location /api/v1/ {
            # API-specific rate limiting
            limit_req zone=api burst=500 nodelay;

            # Proxy to backend
            proxy_pass http://api_servers;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Caching (for GET requests)
            proxy_cache api_cache;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            proxy_cache_valid 200 60s;
            proxy_cache_valid 404 5s;
            proxy_cache_use_stale error timeout updating http_500 http_502;
            proxy_cache_background_update on;
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;

            # Timeouts
            proxy_connect_timeout 5s;
            proxy_read_timeout 30s;
            proxy_send_timeout 10s;

            # Buffering
            proxy_buffering on;
            proxy_buffer_size 4k;
            proxy_buffers 8 16k;
            proxy_busy_buffers_size 64k;

            # Retry
            proxy_next_upstream error timeout invalid_header http_500 http_502;
            proxy_next_upstream_tries 3;
            proxy_next_upstream_timeout 10s;
        }

        # ── Authentication Endpoints ──
        location /auth/ {
            limit_req zone=auth burst=100 nodelay;
            # No caching for auth endpoints!
            proxy_no_cache 1;
            proxy_cache_bypass 1;

            proxy_pass http://auth_servers;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_connect_timeout 3s;
            proxy_read_timeout 10s;
        }

        # ── WebSocket Support ──
        location /ws/ {
            proxy_pass http://websocket_servers;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;

            # No buffering for WebSocket!
            proxy_buffering off;
            proxy_read_timeout 3600s;  # 1 hour for WebSocket
            proxy_send_timeout 3600s;
        }

        # ── Admin endpoints (internal only) ──
        location /admin/ {
            allow 10.0.0.0/8;
            allow 172.16.0.0/12;
            deny all;

            # Stricter rate limiting
            limit_req zone=global burst=20 nodelay;
            limit_conn conn 5;

            proxy_pass http://api_servers;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
        }

        # ── Error Pages ──
        error_page 404 /404.html;
        error_page 500 502 503 504 /5xx.html;

        location = /404.html {
            internal;
        }

        location = /5xx.html {
            internal;
        }
    }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Composition** | Can compose rate limiting, caching, proxying, WebSocket into coherent config |
| **Security defaults** | Includes security headers, rate limiting, access controls |
| **Caching strategy** | Understands what to cache (GET API) vs not cache (auth) |
| **Failover design** | Uses backup servers, proxy_next_upstream, stale cache |

---

## 9. Nginx vs Caddy vs Envoy vs HAProxy

**Q:** "Your team is choosing between Nginx, Caddy, Envoy, and HAProxy for the edge proxy layer. Walk through the architectural and operational differences. For what use cases would you choose each one?"

**What They're Really Testing:** Whether you have broad knowledge of the proxy landscape and can make reasoned architectural decisions.

### Answer

**Architecture Comparison:**

```yaml
┌──────────────────┬──────────┬──────────┬──────────┬──────────┐
│                  │ Nginx    │ Caddy    │ Envoy    │ HAProxy  │
├──────────────────┼──────────┼──────────┼──────────┼──────────┤
│ Language         │ C        │ Go       │ C++      │ C        │
│ Config format    │ Custom   │ Caddyfile│ YAML/DSL │ Custom   │
│                   │ (nginx.conf)│ (opinionated)│ (xDS via gRPC) │ (haproxy.cfg)│
│ Auto HTTPS       │ No       │ Yes      │ No       │ No       │
│                   │          │ (LetsEncrypt)│ (cert-manager)│          │
│ Dynamic reconfig │ Reload   │ Reload   │ Hot swap │ Reload   │
│ Plugin system    │ Dynamic  │ Modules  │ Filters  │ Lua      │
│                   │ modules  │ (Go plugins)│ (Wasm, Lua) │          │
│ Service mesh     │ No       │ No       │ Yes      │ No       │
│ CPU model        │ Event    │ Goroutine│ Event    │ Event    │
│                   │ (epoll)  │ (epoll)  │ (epoll)  │ (epoll)  │
│ HTTP/3 / QUIC    │ Partial  │ Yes      │ Yes      │ No       │
├──────────────────┼──────────┼──────────┼──────────┼──────────┤
│ Throughput       │ Excellent│ Very good│ Excellent│ Excellent│
│ (static files)   │ (sendfile)│ (sendfile)│           │          │
│ Throughput       │ Excellent│ Good     │ Excellent│ Excellent│
│ (proxy)          │          │          │          │          │
│ Config complexity│ High     │ Low      │ Very high│ Medium   │
│ Ecosystem        │ Large    │ Small    │ Medium   │ Medium   │
└──────────────────┴──────────┴──────────┴──────────┴──────────┘
```

**When to Choose Each:**

```yaml
Choose Nginx when:
  - Serving STATIC FILES (best sendfile performance)
  - You need a REVERSE PROXY + WEB SERVER in one
  - Your team knows nginx.conf (large talent pool)
  - You need MODULE ecosystem (ngx_http_* modules)
  - Running on bare metal or VMs (not containers)
  - You need to handle 100K+ connections with low memory

Choose Caddy when:
  - You want ZERO-CONFIG TLS (LetsEncrypt auto)
  - You're building a NEW service (no legacy config)
  - Your team PREFERS Go (Caddyfile is simple)
  - You want built-in HTTP/3 (QUIC) support
  - You don't need Nginx's module ecosystem
  - Running on small/medium deployments
  - You want sane SECURITY defaults out of the box

Choose Envoy when:
  - You're building a SERVICE MESH (Istio, Consul Connect)
  - You need DYNAMIC configuration (xDS protocol)
  - You want OBSERVABILITY built in (tracing, stats)
  - You need advanced L7 routing (header-based, weight-based)
  - Running in KUBERNETES (sidecar pattern)
  - You need Envoy's WASM-based extensibility
  - You have an operations team that can handle complexity

Choose HAProxy when:
  - You need PURE TCP/UDP LOAD BALANCING
  - You need the HIGHEST raw throughput (benchmarks)
  - You need ABSOLUTE RELIABILITY (runs for years without restart)
  - You need advanced LB algorithms (power of two choices origin)
  - TLS termination with EXCELLENT performance
  - You don't need HTTP features (static files, caching)
  - Running as dedicated hardware LB or L4 reverse proxy
```

**Performance Benchmarks (Approximate):**

```yaml
Static file serving (1KB file):
  Nginx:   250K req/s
  Caddy:   200K req/s
  Envoy:   180K req/s (not designed for static files)
  HAProxy: N/A (not a web server)

Reverse proxy (10KB backend response):
  Nginx:   150K req/s
  Caddy:   120K req/s
  Envoy:   180K req/s
  HAProxy: 200K req/s

TLS termination (1KB response, TLS 1.3):
  Nginx:   80K  handshakes/sec
  Caddy:   60K  handshakes/sec
  Envoy:   100K handshakes/sec (BoringSSL, optimized)
  HAProxy: 120K handshakes/sec (best-in-class TLS)

Memory per connection (idle keepalive):
  Nginx:   ~500 bytes
  Caddy:   ~2KB (Go runtime overhead)
  Envoy:   ~1KB (C++ optimized)
  HAProxy: ~400 bytes (most efficient)
```

**Migration Strategy:**

```yaml
Nginx → Envoy (service mesh migration):
  1. Deploy Envoy as sidecar alongside Nginx
  2. Use Nginx as EDGE proxy, Envoy as INTERNAL mesh
  3. Gradually move path-based routes from Nginx to Envoy
  4. Eventually: Nginx only handles TLS termination + static files
  5. Envoy handles all internal routing + observability

Nginx → Caddy (simplification):
  1. Stand up Caddy alongside Nginx on alternate port
  2. Mirror traffic to both (using tcpdump/pcap for testing)
  3. Verify Caddy produces identical responses
  4. Switch DNS to point to Caddy
  5. Keep Nginx as fallback during migration period

Nginx → HAProxy (L4 offload):
  1. Place HAProxy in FRONT of Nginx
  2. HAProxy handles TLS + L4 load balancing
  3. Nginx handles L7 routing + static files
  4. Best of both: HAProxy's TLS performance + Nginx's L7 features
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Architecture differences** | Can compare event models (epoll/goroutine), config formats, extensibility |
| **Use-case matching** | Recommends Envoy for mesh, Nginx for static, HAProxy for L4 |
| **Performance awareness** | Knows approximate throughput numbers, not just "fast" or "slow" |
| **Migration pragmatism** | Can describe realistic multi-step migration strategies |

---

## 10. Troubleshooting Nginx in Production

**Q:** "Your production nginx is returning intermittent 502 errors. Show me your systematic debugging approach — from checking the basics to deep diving into kernel-level diagnostics."

**What They're Really Testing:** Whether you have a systematic troubleshooting methodology — not guessing, but following evidence from symptoms to root cause.

### Answer

**Systematic Debugging Approach:**

```bash
# ── Step 1: Check the Basics ──

# 1.1 Is nginx running?
systemctl status nginx
ps aux | grep nginx
# Expected: 1 master + N workers (N = CPU cores)

# 1.2 Any recent config changes?
ls -la /etc/nginx/ | grep -E '\.(conf|bak|old)'
nginx -t  # Validate config
# If broken: check error log for line numbers

# 1.3 Error log (the FIRST place to look!)
tail -100 /var/log/nginx/error.log
# Look for: "no live upstreams", "connect() failed",
#           "upstream timed out", "connection refused"

# 1.4 Access log for 502 patterns
tail -100 /var/log/nginx/access.log | grep ' 502 '
# Look for time patterns: same backend? same endpoint? same time?
```

```bash
# ── Step 2: Connection & Upstream Analysis ──

# 2.1 Connection state
curl http://localhost/nginx_status
# Active: 1200
# Reading: 5 Writing: 45 Waiting: 1150
# Warning signs:
#   - Writing > 50% of worker_connections → backend slow
#   - Waiting > 80% → too many idle keepalive connections

# 2.2 Upstream health
# Check each upstream server manually
for i in 10.0.0.1 10.0.0.2 10.0.0.3; do
    echo -n "Server $i: "
    curl -s -o /dev/null -w "%{http_code} %{time_total}s" \
        --connect-timeout 3 \
        http://$i:8000/health
    echo
done
# Look for: slow time_total (>1s), non-200 status

# 2.3 Upstream connection pool
# Check upstream sockets in TIME_WAIT / CLOSE_WAIT
ss -tanp | grep :8000 | awk '{print $1}' | sort | uniq -c
# Expected: mostly ESTABLISHED with some TIME_WAIT
# Warning: many CLOSE_WAIT → upstream not closing connections!
# Warning: many SYN_SENT → upstream unreachable!
```

```bash
# ── Step 3: Resource Limits ──

# 3.1 Open file descriptors (the most common cause of 502!)
cat /proc/$(cat /var/run/nginx.pid)/limits | grep "open files"
# Expected: "65535" or higher
# If "1024": this is your problem!

# Check current usage:
for pid in $(pgrep nginx); do
    echo "PID $pid: $(ls /proc/$pid/fd | wc -l) FDs"
done
# If any worker is near the limit → socket exhaustion → 502

# 3.2 Ephemeral port range (for upstream connections)
cat /proc/sys/net/ipv4/ip_local_port_range
# Default: 32768 60999 (≈ 28K ports)
# For high traffic: widen to 1024 65535

net.ipv4.ip_local_port_range = 1024 65535
# ≈ 64K ports per source IP

# Check port exhaustion:
netstat -an | grep TIME_WAIT | wc -l
# If > 10000 and growing → port exhaustion

# 3.3 Connection backlog
ss -lntp | grep :80
# Recv-Q should be near 0
# If Recv-Q is growing → backlog is full → 502

# Check and increase:
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
```

```bash
# ── Step 4: Kernel-Level Diagnostics ──

# 4.1 Strace one worker (intermittent 502?)
# Find worker PID:
PID=$(pgrep -f 'nginx: worker' | head -1)

# Trace for 5 seconds, filter for failures:
strace -p $PID -e trace=network -f -T 2>&1 | \
    grep -E 'connect|accept|EAGAIN|refused|timeout' | head -30

# Look for:
#   connect(3, ...) = -1 EAGAIN (Resource temporarily unavailable)
#   → Connection pool exhausted
#   connect(3, ...) = -1 ECONNREFUSED
#   → Upstream not listening
#   connect(3, ...) = -1 ETIMEDOUT
#   → Upstream overloaded or network issue

# 4.2 Tcpdump specific requests
tcpdump -i eth0 -nn port 8000 and "tcp[tcpflags] & tcp-syn != 0" -c 100
# Count failed connections:
tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn|tcp-rst) == tcp-syn|tcp-rst'
# RST after SYN → upstream actively refusing
# No SYN-ACK → upstream not listening or firewall dropping

# 4.3 Perf (CPU profiling during 502 spikes)
perf record -g -p $(pgrep -f 'nginx: worker' | head -3) -a -- sleep 10
perf report
# Look for functions with high CPU:
#   - ngx_epoll_process_events: normal (waiting for I/O)
#   - ngx_ssl_handshake: TLS handshake CPU bound
#   - ngx_http_upstream_connect: connection setup overhead
```

**Common 502 Root Causes & Fixes:**

```yaml
Root Cause 1: Upstream Pods Crashing (Kubernetes)
  Symptom: 502 spikes every few minutes
  Diagnosis: kubectl get pods -w shows CrashLoopBackOff
  Fix: 
    - Increase readiness probe grace period
    - Add minReadySeconds to deployment
    - Use preStop hook for graceful shutdown

Root Cause 2: Upstream Connection Pool Exhausted
  Symptom: 502 under load, error log: "connect() to upstream failed"
  Diagnosis: ss -tanp shows many upstream connections, port range near limit
  Fix:
    - Increase upstream keepalive pool
    - Widen ip_local_port_range
    - Enable SO_REUSEPORT on upstream

Root Cause 3: Slow Backend Causes Timeout
  Symptom: 504 (not 502), error: "upstream timed out"
  Diagnosis: proxy_read_timeout too low (default: 60s)
  Fix:
    - Increase proxy_read_timeout for slow endpoints
    - OR refactor the slow endpoint to be async
    - OR use proxy_next_upstream to try different backend

Root Cause 4: File Descriptor Exhaustion
  Symptom: 502, error: "socket() failed (24: Too many open files)"
  Diagnosis: cat /proc/PID/limits shows low limit
  Fix:
    - worker_rlimit_nofile 65535 in nginx.conf
    - ulimit -n 65535 in systemd unit
    - Check: LimitNOFILE=65535 in /etc/systemd/system/nginx.service.d/override.conf

Root Cause 5: Backend Connection Refused (Health Check Failed)
  Symptom: 502 for specific backend, error: "connect() failed (111: Connection refused)"
  Diagnosis: curl to upstream directly fails
  Fix:
    - Check upstream service status
    - Increase max_fails/fail_timeout to avoid flapping
    - Add backup servers for failover
```

**502 Debugging Cheatsheet:**

```bash
# Quick triage script:
echo "=== Nginx 502 Triage ==="

echo "1. Error log (last 50 lines):"
tail -50 /var/log/nginx/error.log | grep -E '502|error|emerg|alert'

echo "2. Connection state:"
curl -s http://localhost/nginx_status 2>/dev/null || echo "Status module not enabled"

echo "3. Upstream backends:"
for backend in $(grep server /etc/nginx/conf.d/upstream.conf | grep -v backup); do
    IP=$(echo $backend | grep -oP '\d+\.\d+\.\d+\.\d+')
    PORT=$(echo $backend | grep -oP '(?<=:)\d+')
    curl -s -o /dev/null -w "$IP:$PORT -> %{http_code} %{time_total}s\n" \
        --connect-timeout 3 http://$IP:$PORT/health
done

echo "4. File descriptors:"
for pid in $(pgrep nginx); do
    echo "PID $pid: FD count=$(ls /proc/$pid/fd 2>/dev/null | wc -l)"
done

echo "5. Kernel TCP state:"
ss -tanp | grep -E '(80|443|8080)' | awk '{print $1}' | sort | uniq -c
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Systematic approach** | Checks error logs → upstream health → resource limits → kernel diagnostics |
| **File descriptor awareness** | Knows this is the #1 cause of nginx 502 errors |
| **Port exhaustion** | Understands ephemeral port range limits upstream connections |
| **Diagnostic tools** | Can use strace, tcpdump, perf, ss for deep investigation |

---

> *All 10 questions cover the full breadth of Nginx internals and operations — from the master/worker process model to kernel-level diagnostics. Master these and you'll demonstrate Staff-level depth in one of the most critical infrastructure components at any scale.*
