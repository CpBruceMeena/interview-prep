# 🌐 Computer Networks — Staff-Level Interview Questions

> *12 questions covering TCP/IP internals, HTTP/2/3, DNS, TLS, load balancing, and network architecture — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [TCP Congestion Control (BBR vs Cubic)](#1-tcp-congestion-control-bbr-vs-cubic)
2. [HTTP/2 Multiplexing & Head-of-Line Blocking](#2-http2-multiplexing-head-of-line-blocking)
3. [HTTP/3 & QUIC](#3-http3-quic)
4. [TLS 1.3 Handshake & 0-RTT](#4-tls-13-handshake-0-rtt)
5. [DNS Resolution Deep Dive](#5-dns-resolution-deep-dive)
6. [Load Balancing: L4 vs L7, Consistent Hashing](#6-load-balancing-l4-vs-l7-consistent-hashing)
7. [Connection Pooling & Keep-Alive](#7-connection-pooling-keep-alive)
8. [gRPC vs REST: Wire Protocol Comparison](#8-grpc-vs-rest-wire-protocol-comparison)
9. [CDN Architecture & Caching Strategies](#9-cdn-architecture-caching-strategies)
10. [TCP TIME_WAIT & Ephemeral Port Exhaustion](#10-tcp-time_wait-ephemeral-port-exhaustion)
11. [Network Namespaces & Overlay Networks](#11-network-namespaces-overlay-networks)
12. [Packet Capture Analysis: Production Debugging](#12-packet-capture-analysis-production-debugging)

---

## 1. TCP Congestion Control (BBR vs Cubic)

**Q:** "We're rolling out a new video streaming service that sends large chunks (1-4MB) over long-fat pipes (100ms RTT, 1Gbps). Our Cubic-based TCP stack is underutilizing the bandwidth — we're seeing only 200Mbps. Diagnose the problem and compare how BBR would handle this differently."

**What They're Really Testing:** Whether you understand TCP congestion control at the level of actual algorithms, not just textbook "slow start, congestion avoidance."

### Answer

**The Problem — Cubic on a Long-Fat Pipe:**

```
Bandwidth-Delay Product (BDP) = 1Gbps × 100ms = 100Mb = 12.5MB

Cubic's congestion window (cwnd) evolution:
1. Slow start: double cwnd per RTT until:
   - ssthresh hit (default ~64KB → 120KB for modern kernels)
   - OR packet loss detected
2. Congestion avoidance: cubic grows cwnd, but...

The issue: Cubic uses packet LOSS as a congestion signal.
On a 100ms RTT link:
- cwnd needs to reach ~830 packets (12.5MB / 1500B) to fill the pipe
- Without loss, it grows cubically (time^3), which is aggressive
- BUT: shallow buffers (typical in cloud) cause packet drops early
- Each drop cuts cwnd in half → sawtooth pattern

Result: Average cwnd ≈ 250 packets → ~300Mbps → 30% utilization
```

**Cubic WSCALE vs BBR — Conceptual Comparison:**

```
Cubic:              BBR:
┌──────────────────┐  ┌──────────────────┐
│ Loss-based       │  │ Model-based      │
│ cwnd = f(time³)  │  │ rate = f(BW, RTT)│
│ until loss → ÷2  │  │ probes BW, paces │
└──────────────────┘  └──────────────────┘

Cubic behavior on lossy/long-fat:
│██████    ██████    ████    ██    │
│   loss    loss    loss   loss    │ ← cwnd halved each time
│~400Mbps  ~350Mbps ~250Mbps~180Mbps│ ← degrading

BBR behavior:
│████████████████████████████████│
│          ~950Mbps steady       │ ← model tracks actual BW
```

**BBR Deep Dive — How It Works:**

BBR estimates two parameters in real time:

1. **`BtlBw` (bottleneck bandwidth)** — max delivery rate observed in the last 10 RTTs
2. **`RTprop` (round-trip propagation time)** — min RTT observed in the last 10 seconds

```
BBR State Machine:

                    ┌─────────┐
                    │  STARTUP│  ← Doubles rate (like slow start)
                    └────┬────┘  ← Until pipe is full (BW flattens)
                         │
                    ┌────▼────┐
                    │ DRAIN   │  ← Reduce rate to drain queue
                    └────┬────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         ┌────▼────┐          ┌────▼────┐
         │  Probe  │◄────────►│  Probe  │
         │ BW      │          │ RTT     │
         │ (gain=1.25)│       │ (no gain)│
         └─────────┘          └─────────┘
              │                     │
              └──────────┬──────────┘
                         │
                    ┌────▼────┐
                    │  PROBE  │  ← Loop: 8 cycles BW, 1 cycle RTT
                    │  RTT    │
                    └─────────┘
```

**Why BBR Wins for Video Streaming:**

```c
// BBR pacing — sends at estimated bandwidth, NOT burst-until-loss:
// Kernel BBR implementation sketch:
struct bbr {
    u64 bw;              // Bottleneck bandwidth (bits/sec)
    u64 min_rtt;         // Min RTT (usec)
    u64 rtt_cnt;         // RTT counter
    u8  mode;            // STARTUP/DRAIN/PROBE_BW/PROBE_RTT
    u32 cwnd_gain;       // cwnd multiplier
    u32 pacing_gain;     // Pacing multiplier
};

void bbr_update_model(struct sock *sk) {
    struct bbr *bbr = inet_csk_ca(sk);
    u64 delivered = tcp_delivered(sk);  // Bytes acked since last call
    u64 interval = tcp_interval_us(sk); // Time since last call

    // Update bandwidth estimate (max filter over last 10 RTTs)
    bbr->bw = max(bbr->bw, delivered * 8 / interval);

    // Update min RTT (windowed min over last 10 seconds)
    bbr->min_rtt = min(bbr->min_rtt, tcp_rtt_us(sk));

    // Set pacing rate = bw * pacing_gain
    tcp_set_pacing_rate(sk, bbr->bw * bbr->pacing_gain);
}

// Result: BBR paces packets to match the bottleneck link
// No burst → no bufferbloat → no loss → no cwnd halving
// Video sees: steady 900Mbps+ with low jitter
```

**Trade-offs:**
- Cubic: simple, fair to other Cubic flows, tested in billions of devices
- BBR: better utilization of long-fat pipes, but can be unfair to Cubic flows (up to 3× more bandwidth)
- BBRv3 (2023): adds fairness convergence, improved loss handling

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **BDP concept** | Calculates BDP = 12.5MB, explains why cwnd must exceed this |
| **Loss-based vs model-based** | Can articulate the fundamental paradigm shift |
| **BBR internals** | Explains BtlBw, RTprop, pacing gain, state machine |
| **Production nuance** | Knows BBR can be unfair to Cubic — deployment strategy matters |

---

## 2. HTTP/2 Multiplexing & Head-of-Line Blocking

**Q:** "We migrated from HTTP/1.1 to HTTP/2 expecting performance gains, but we're seeing WORSE latency on our mobile app (high packet loss, ~3%). One TCP connection carries 20+ concurrent streams. Explain the head-of-line blocking problem in HTTP/2 and how HTTP/3 fixes it."

**What They're Really Testing:** Understanding of HTTP/2's fundamental architectural limitation at the transport layer.

### Answer

**HTTP/1.1 vs HTTP/2 vs HTTP/3:**

```
HTTP/1.1 (6 parallel connections):
┌─Connection 1─┐  ┌─Connection 2─┐  ┌─Connection 3─┐
│ Req1→Resp1   │  │ Req2→Resp2   │  │ Req3→Resp3   │
│ Req4→Resp4   │  │ Req5→Resp5   │  │ Req6→Resp6   │
└──────────────┘  └──────────────┘  └──────────────┘
Each connection → own TCP congestion window
Each connection → independent loss recovery
Downside: 3× TCP handshake, 3× slow start, 3× memory

HTTP/2 (1 connection, multiplexed):
┌─One TCP connection──────────────────────────────────┐
│ Stream 1: Req1→Resp1                                │
│ Stream 2: Req2→Resp2                                │
│ Stream 3: Req3→Resp3                                │
│ Stream 4: Req4→Resp4                                │
│ Stream 5: Req5... ← LOST PACKET!                    │
│ Stream 6: ... ← BLOCKED!                            │
│ Stream 7: ... ← ALL BLOCKED until retransmit!       │
└─────────────────────────────────────────────────────┘

HTTP/3 (QUIC — 1 connection, but independent streams):
┌─QUIC Connection─────────────────────────────────────┐
│ ┌─Stream 1──┐  ┌─Stream 2──┐  ┌─Stream 3──┐       │
│ │ Req1→Resp1│  │ Req2→Resp2│  │ Req3→Resp3│       │
│ └───────────┘  └───────────┘  └───────────┘       │
│ ┌─Stream 4──┐  ┌─Stream 5──┐  ┌─Stream 6──┐       │
│ │ Req4→Resp4│  │ Req5...   │  │ Req6→Resp6│ ← NOT  │
│ └───────────┘  │LOST PACKET│  │ NOT BLOCKED│ BLOCKED│
│                └───────────┘  └───────────┘       │
└─────────────────────────────────────────────────────┘
```

**The HTTP/2 HoL Blocking Problem — Deep Dive:**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/net-http2-vs-quic.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — HTTP/2 vs HTTP/3 (QUIC) — One lost packet blocks H2 entirely, QUIC isolates per-stream. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```
TCP is BYTE-ORIENTED, not MESSAGE-ORIENTED.

TCP guarantees in-order delivery of bytes.
HTTP/2 frames are serialized over a byte stream.

When packet #5 (containing bytes for Stream 5's request) is lost:

TCP receiver:
┌────┬────┬────┬────┬────┬────┬────┐
│ P1 │ P2 │ P3 │ P4 │  ✗  │ P6 │ P7 │ ← Packets on wire
│    │    │    │    │LOST │    │    │
├────┴────┴────┴────┴────┴────┴────┤
│       Reassembly buffer           │
│  ┌───┬───┬───┬───┐  ┌───┬───┐  │
│  │ S1│ S2│ S3│ S4│  │ S6│ S7│  │ ← Can't deliver to app!
│  └───┴───┴───┴───┘  └───┴───┘  │
│        ↑ These are held           │
│        ↑ waiting for P5           │
└────────────────────────────────────┘

Application (browser):
  Stream 1: ✅ Delivered
  Stream 2: ✅ Delivered
  Stream 3: ✅ Delivered
  Stream 4: ✅ Delivered
  Stream 5: ❌ Waiting for retransmit
  Stream 6: ❌ BLOCKED — bytes held by TCP
  Stream 7: ❌ BLOCKED
  Stream 8: ❌ BLOCKED
```

**Why 3% Loss Is Catastrophic for HTTP/2:**

```python
# Expected throughput with loss for HTTP/2 vs HTTP/1.1:

# HTTP/1.1: 6 connections, each loses independently
# Probability any given connection is in recovery: 3% (loss rate)
# Throughput = 6 × (1 - 0.03) = 5.82 connections worth

# HTTP/2: 1 connection, 20 streams share 1 cwnd
# Probability ALL streams are blocked = 100% during loss recovery
# Throughput = 1 × (1 - 0.03) = 0.97 connections worth
# Even though we have 20 streams, they all stop during recovery

# With 3% loss, TCP spends ~9% of time in recovery (RTO backoff)
# Effective throughput = (1 - 0.09) × BDP / RTT
# = 0.91 × 1.0 / 0.1 = 9.1 Mbps (vs potential 100 Mbps)
# HTTP/1.1: 6 × 0.91 × 1.0 / 0.1 = 54.6 Mbps
```

**The Fix: HTTP/3 and QUIC — Independent Stream Loss Recovery:**

```
QUIC's key insight: DON'T use a byte stream. Use PACKET-BASED streams.

Each QUIC stream has its own:
- Stream ID (62-bit, unique per direction)
- Offset tracking (byte position within stream)
- Flow control (stream-level + connection-level)
- Loss recovery (independent per stream)

QUIC packet format:
┌─────────────────────────────────────────────┐
│ QUIC Header (connection-level)              │
├─────────────────────────────────────────────┤
│ ├─ Stream 1 Frame ──────────────────────────┤
│ │ Stream ID: 4, Offset: 0, Length: 100     │
│ └───────────────────────────────────────────┤
│ ├─ Stream 5 Frame ──────────────────────────┤
│ │ Stream ID: 10, Offset: 200, Length: 50   │
│ └───────────────────────────────────────────┤
└─────────────────────────────────────────────┘

If the packet containing Stream 5 is lost:
- QUIC detects the missing frame (via packet number gap)
- Only Stream 5's frames need retransmission
- Stream 1, 2, 3, 4, 6, 7, 8 continue UNIMPEDED
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **TCP byte stream** | Explains that TCP HoL is inherent — bytes must be delivered in order |
| **HTTP/2 framing** | Understands that frames serialize over TCP regardless of stream |
| **Loss math** | Calculates effective throughput with loss for both protocols |
| **QUIC streams** | Knows QUIC = independent stream recovery, not just "faster than TCP" |

---

## 3. HTTP/3 & QUIC

**Q:** "Walk me through the QUIC handshake end-to-end. How does 0-RTT work, and what security implications does it have? Compare connection establishment time vs TCP+TLS 1.3."

**What They're Really Testing:** Whether you understand QUIC's cryptographic and transport design at the level of actual packet formats.

### Answer

**Handshake Comparison:**

```
TCP + TLS 1.3:
Client                 Server
  │                      │
  ├── SYN ──────────────►│
  │◄── SYN+ACK ─────────┤  ← 1 RTT (TCP handshake)
  ├── ACK ──────────────►│
  ├── ClientHello ──────►│
  │◄── ServerHello ─────┤
  │◄── ServerFinished ───┤  ← 1 RTT (TLS 1.3 handshake)
  ├── ClientFinished ───►│
  ├── HTTP Request ─────►│
  │◄── HTTP Response ────┤  ← Data starts at RTT 3
  │                      │

QUIC (initial):
Client                 Server
  │                      │
  ├── Initial ──────────►│  ← ClientHello (TLS 1.3)
  │◄── Initial ─────────┤  ← ServerHello + Handshake
  │◄── Handshake ───────┤  ← ServerFinished + Transport params
  ├── Handshake ────────►│  ← ClientFinished
  ├── 1-RTT Data ───────►│  ← HTTP Request starts at RTT 2
  │◄── 1-RTT Data ──────┤  ← Data available
  │                      │

QUIC 0-RTT (resumed):
Client                 Server
  │                      │
  ├── 0-RTT Data ───────►│  ← HTTP Request WITH Initial
  │   + Initial          │     (uses cached session ticket)
  │◄── Initial ─────────┤  ← Validates 0-RTT
  │◄── Handshake ───────┤
  │◄── 1-RTT Data ──────┤  ← Response arrives ~1 RTT earlier
  │                      │
  │ 0-RTT: Data sent at RTT 1, received and processed at RTT 2
  │ vs TCP+TLS: Data sent at RTT 3
  │ Savings: 66% reduction in time-to-first-byte
```

**QUIC Packet Protection — Detailed:**

```
QUIC Initial Packet:
┌─────────────────────────────────────────────┐
│ Long Header (1 byte)                        │
│   ┌─ 0b11000000 (Initial)                  │
│ Version (4 bytes)                           │
│ DCID Length (1 byte) + DCID (variable)      │
│ SCID Length (1 byte) + SCID (variable)      │
│ Token Length (variable)                     │  ← Anti-amplification
│ Token (variable)                            │
│ Length (variable)                           │
│ Packet Number (1-4 bytes, encrypted)        │  ← Encrypted!
├─────────────────────────────────────────────┤
│ Encrypted Payload                           │
│   ├─ CRYPTO frame (ClientHello)            │
│   ├─ ACK frame                              │
│   └─ PADDING frame                          │  ← Minimum size for
│   (to reach 1200 bytes for anti-amplification)│    anti-amplification
├─────────────────────────────────────────────┤
│ Authentication Tag (16 bytes)               │  ← AEAD integrity check
└─────────────────────────────────────────────┘
```

**0-RTT Security Implications:**

```javascript
// 0-RTT allows the client to send data BEFORE the handshake completes.
// This creates two classes of security issues:

// 1. REPLAY ATTACK
// The 0-RTT data is encrypted with a key derived from the previous session.
// If an attacker captures the 0-RTT packet, they can replay it:
function replayAttack() {
    const captured0RTT = /* previous session's 0-RTT request */ {
        method: 'POST',
        path: '/api/transfer',
        body: { to: 'attacker', amount: '$10000' }
    };
    // Send captured 0-RTT to server again:
    sendUDP(captured0RTT);  // Server processes AGAIN!
    // Server sees: valid session ticket, valid encryption
    // → Second transfer initiated!
}

// Mitigation:
// - Servers MUST implement replay protection
// - Common approach: Replay window (e.g., 10ms) — reject 0-RTT if
//   same data seen within window
// - Idempotency keys on mutating operations:
//   POST /api/transfer HTTP/1.1
//   Idempotency-Key: 123e4567-e89b-12d3-a456-426614174000
//   → Server deduplicates by key, even if 0-RTT is replayed
```

**2. 0-RTT Amplification:**
- 0-RTT response can be larger than 0-RTT request → DDoS vector
- QUIC limits: server can send at most 3× the received bytes before handshake completes

**QUIC vs TCP — A Deeper Comparison:**

| Feature | TCP | QUIC |
|---------|-----|------|
| **Handshake** | 1 RTT (TCP) + 1 RTT (TLS) | 0-1 RTT |
| **Transport** | Kernel (OS) | Userspace (app/library) |
| **Deploy** | OS upgrade required | App update only |
| **Migration** | New socket = new TCP handshake | Connection migration via DCID |
| **NAT rebind** | Connection breaks | Seamless (stable DCID) |
| **Loss recovery** | SACK, RACK | More granular (per-stream) |
| **OSS** | Kernel TCP stack | e.g., quiche, lsquic, picoquic |

**Connection Migration — QUIC's Killer Feature:**

```
Mobile client scenario:
Client (WiFi → Cellular) → Server

TCP: WiFi IP: 10.0.0.5
     → Switch to cellular (new IP: 10.0.1.5)
     → Server has (10.0.0.5:port, listener:port) in connection table
     → Packet from 10.0.1.5 → not matched → RST → connection lost
     → Need new TCP handshake (~200ms gap)

QUIC: DCID = 0xDEADBEEF (stable, not tied to IP)
     → Switch to cellular
     → Packet with DCID=0xDEADBEEF arrives from new IP
     → Server matches DCID → updates connection state with new IP
     → Data continues immediately (~0ms gap)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Wire format** | Knows Initial packet structure, encryption boundaries |
| **0-RTT risks** | Explains replay attack and anti-amplification precisely |
| **Connection migration** | Understands DCID as stable identifier, NAT rebind handling |
| **Deployment** | Knows QUIC over UDP can be blocked by enterprise firewalls (UDP policy) |

---

## 4. TLS 1.3 Handshake & 0-RTT

**Q:** "Design a TLS termination strategy for a microservices architecture processing 50K connections/second. Compare TLS termination at the load balancer (L4) vs at each service (L7). How does TLS 1.3 change the equation vs TLS 1.2?"

**What They're Really Testing:** Whether you understand TLS 1.3's latency improvements at scale and the operational trade-offs of termination strategies.

### Answer

**TLS 1.2 vs 1.3 Handshake:**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/net-tls-handshake.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — TLS 1.3 Handshake — 1-RTT handshake vs TLS 1.2's 2-RTT with 0-RTT resumption. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>


```
TLS 1.2 (2 RTT):
Client                      Server
  │                           │
  ├── ClientHello ───────────►│
  │◄── ServerHello ──────────┤
  │◄── Certificate ──────────┤
  │◄── ServerHelloDone ──────┤  ← 1 RTT
  ├── ClientKeyExchange ────►│
  ├── ChangeCipherSpec ─────►│
  ├── Finished ─────────────►│
  │◄── ChangeCipherSpec ────┤
  │◄── Finished ────────────┤  ← 2 RTT
  ├── Application Data ─────►│  ← Data at RTT 3

TLS 1.3 (1 RTT, often 0-RTT):
Client                      Server
  │                           │
  ├── ClientHello ───────────►│  ← Key share included!
  │   (KeyShare: X25519)     │     (saves 1 RTT)
  │◄── ServerHello ──────────┤
  │◄── EncryptedExtensions ──┤
  │◄── Certificate ──────────┤
  │◄── CertificateVerify ───┤
  │◄── Finished ────────────┤  ← 1 RTT
  ├── Finished ─────────────►│
  ├── Application Data ─────►│  ← Data at RTT 2
```

**The Symmetric Crypto Advantage in TLS 1.3:**

```python
# TLS 1.2 handshake server cost (RSA key exchange):
# - Receive ClientHello
# - Send Certificate (RSA 2048-bit signature)
# - Receive ClientKeyExchange (RSA 2048-bit decrypt → ~250µs on modern CPU)
# - Verify Finished hash

# TLS 1.3 handshake server cost (ECDHE):
# - Receive ClientHello + KeyShare (X25519 curve)
# - ECDHE key agreement: ~25µs (10× faster than RSA decrypt!)
# - Send ServerHello + KeyShare
# - Ed25519 signature on Certificate: ~40µs

# At 50K connections/second:
# TLS 1.2: 50,000 × 250µs = 12.5 seconds of CPU per second → IMPOSSIBLE
# TLS 1.3: 50,000 × 65µs = 3.25 seconds of CPU per second → HIGH but possible
```

**Termination Strategies:**

```
Option A: L4 Load Balancer (TCP proxy)
┌──────────┐    TCP     ┌──────────┐   TCP    ┌──────────┐
│  Client  │───────────►│   LB     │──────────►│  Backend │
│          │    TLS     │ (pass    │  no-TLS  │          │
│          │◄───────────│  through)│◄──────────│          │
└──────────┘            └──────────┘           └──────────┘
Pros: LB is simple, backend doesn't need TLS
Cons: LB can't inspect HTTP → L7 routing impossible
       Client IP hidden from backend (unless PROXY protocol)

Option B: L7 Load Balancer (TLS termination)
┌──────────┐    TLS     ┌──────────┐  internal  ┌──────────┐
│  Client  │───────────►│   LB     │────────────►│  Backend │
│          │◄───────────│ (terminate│◄────────────│ (mTLS or │
│          │            │  TLS)    │             │  plain)  │
└──────────┘            └──────────┘             └──────────┘
Pros: LB can do L7 routing, header injection, cookie stickiness
Cons: TLS private key on LB (security risk), more CPU on LB

Option C: End-to-end TLS (service mesh)
┌──────────┐    TLS     ┌──────────┐   mTLS    ┌──────────┐
│  Client  │───────────►│   LB/    │───────────►│  Backend │
│          │◄───────────│  Envoy   │◄───────────│  (with   │
│          │            │          │            │ sidecar) │
└──────────┘            └──────────┘            └──────────┘
Pros: End-to-end encryption, no plaintext anywhere
Cons: Double TLS overhead, key management complexity
```

**The TLS Session Resumption Strategy for 50K connections/s:**

```python
# Session resumption is CRITICAL at scale.
# Without it: each connection = full handshake = 65µs CPU
# With session tickets: first connection = 65µs, subsequent = ~5µs

session_cache = {}  # {session_id: session_state}

def handle_tls(client_hello, client_ip):
    if client_hello.has_session_ticket():
        ticket = client_hello.session_ticket
        session = session_cache.get(ticket.session_id)

        if session and session.ticket_age < MAX_TICKET_AGE:
            # 0-RTT possible if client also sends early data
            return resume_session(session, client_hello.early_data)
        else:
            # Full handshake required
            return full_handshake(client_hello)
    else:
        return full_handshake(client_hello)

# At 50K/s:
# 80% resumption → 40K × 5µs + 10K × 65µs = 200ms + 650ms = 850ms CPU/s
# 20% full → Manageservice
# Cache: 50K × 10 minutes × 60 = 30M entries → ~60GB (if each entry = 2KB)
# → Need distributed cache (Redis), not local memory
```

**Operational Recommendations:**

```yaml
Production TLS 1.3 configuration:
  tls_versions: [1.3]  # 1.2 only for legacy backward compat
  cipher_suites:
    - TLS_AES_128_GCM_SHA256   # Fast, hardware-accelerated (AES-NI)
    - TLS_AES_256_GCM_SHA384   # For compliance
    - TLS_CHACHA20_POLY1305_SHA256  # For mobile (no AES-NI)
  curves:
    - X25519       # Fast (~25µs), constant-time
    - prime256v1   # For FIPS compliance
  
  # Session management:
  ssl_session_cache: "shared:SSL:10m"  # 10MB shared cache
  ssl_session_timeout: 300              # 5 minutes
  ssl_session_tickets: yes
  ssl_early_data: no  # Disable 0-RTT for production (replay concerns)
```

**Verdict for 50K connections/s:** Use Option B (L7 termination at LB) with TLS 1.3, session ticket resumption, and X25519 key exchange. Offload as many connections as possible to session resumption (target >90%). Distribute session state via shared Redis cache.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **RTT savings** | Knows TLS 1.3 = 1 RTT vs 1.2 = 2 RTT (or 0-RTT with early data) |
| **CPU cost** | Calculates RSA vs ECDHE cost, knows AES-NI acceleration |
| **Session management** | Designs session cache with Redis, understands ticket lifetime trade-offs |
| **Architecture** | Compares L4 vs L7 termination, knows when mTLS is needed |

---

## 5. DNS Resolution Deep Dive

**Q:** "A user reports that your SaaS platform is intermittently unreachable. When they `nslookup saas.example.com`, they get different IPs each time — some work, some timeout. Trace the entire DNS resolution path from browser to root server. How does DNS caching, TTL, and anycast routing affect your diagnosis?"

**What They're Really Testing:** Whether you understand DNS at the protocol level — caching hierarchy, anycast, stub vs recursive resolvers.

### Answer

**Full DNS Resolution Path:**

```
Browser: https://saas.example.com
    │
    ├─1. Check local cache (OS resolver)
    │  └─ nscd / systemd-resolved / dnsmasq
    │
    ├─2. Check /etc/hosts
    │  └─ (skip if not found)
    │
    ├─3. Send query to STUB RESOLVER
    │  └─ Configured in /etc/resolv.conf → e.g., 8.8.8.8 (Google)
    │
    └─4. Recursive Resolver (8.8.8.8) does:
       │
       ├─a. Root Server (.) — 13 logical root hints
       │  └─ "I don't know saas.example.com, ask .com TLD"
       │  └─ Returns: a.gtld-servers.net
       │
       ├─b. TLD Server (.com) — Verisign
       │  └─ "I don't know saas.example.com, ask example.com's nameservers"
       │  └─ Returns: ns1.example.com (authoritative)
       │           ns2.example.com (authoritative)
       │
       └─c. Authoritative Nameserver (ns1.example.com)
          └─ "saas.example.com IN A 203.0.113.10"
          └─ "saas.example.com IN A 203.0.113.20"
          └─ "saas.example.com IN A 203.0.113.30"
          └─ Returns: 3 A records + TTL
          
    │
    └─5. Browser receives IPs, picks one (round-robin or Happy Eyeballs)
       └─ Opens TCP connection to 203.0.113.10:443
```

**The Problem — Intermittent Failures:**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/net-dns-resolution.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — DNS Resolution Path — Browser → Stub → Root → TLD → Authoritative → IP Address. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```dns
; Query
saas.example.com.     300     IN      A

; Answer (authoritative nameserver returns):
saas.example.com.     300     IN      A     203.0.113.10  ← HEALTHY
saas.example.com.     300     IN      A     203.0.113.20  ← HEALTHY
saas.example.com.     300     IN      A     203.0.113.30  ← DEAD (downed server)
saas.example.com.     300     IN      A     203.0.113.40  ← HEALTHY
```

**Diagnosis:**

```bash
# 1. Check DNS resolution with different resolvers
dig @8.8.8.8 saas.example.com     # See Google's view
dig @1.1.1.1 saas.example.com     # See Cloudflare's view
dig @ns1.example.com saas.example.com  # Authoritative view

# 2. Check if the bad IP is being served
dig saas.example.com +short
203.0.113.10
203.0.113.20
203.0.113.30  ← DEAD
203.0.113.40

# 3. Check TTL — if high, the bad IP is cached worldwide
dig saas.example.com +ttlid
saas.example.com. 299 IN A 203.0.113.30  ← 299s remaining until cache expiry

# 4. Check anycast routing — is the user hitting a different PoP?
dig +trace saas.example.com  # See full delegation path
```

**Caching Hierarchy (TTL = 300s = 5 minutes):**

```
Browser Cache (e.g., Chrome):  60s (ignores TTL for performance)
    ↓
OS Cache (systemd-resolved):   300s (respects TTL)
    ↓
Local DNS Resolver (router):   300s (respects TTL)
    ↓
ISP Recursive Resolver:        300s (respects TTL, but may exceed)
    ↓
Root/TLD Servers:              No cache (referral only)
    ↓
Authoritative Server:          Source of truth

Total worst-case cache propagation: ~5 minutes to clear a bad record
```

**Anycast Routing Effect:**

```
Google Public DNS (8.8.8.8):
┌──────────────────────────────────────┐
│  PoP1 (Ashburn)  │  PoP2 (Dublin)    │
│  ┌───────────┐   │  ┌───────────┐    │
│  │ Cache:    │   │  │ Cache:    │    │
│  │ 203.0.113.30│   │  │ 203.0.113.10│  │
│  │ (updating)│   │  │ (updated)│    │
│  └───────────┘   │  └───────────┘    │
│         │ BGP route                 │
│         │ to /24                    │
│         └──────┬──────────────┘     │
└────────────────┼────────────────────┘
                 │
        Client in UK → routed to PoP2 (Dublin) → sees healthy IP
        Client in US → routed to PoP1 (Ashburn) → sees DEAD IP (cached)
```

**The Fix — DNS Health Checks:**

```yaml
# Route53 health check configuration:
HealthCheck:
  Type: HTTPS
  Target: 203.0.113.30:443/health
  Interval: 10 seconds
  FailureThreshold: 2
  RecoveryThreshold: 3

# If health check fails:
# → Route53 REMOVES the dead IP from DNS responses
# → DNS returns only healthy IPs
# → TTL becomes low (60s) during failover for fast convergence

# DNS record with health check:
saas.example.com.    60     IN     A     203.0.113.10
saas.example.com.    60     IN     A     203.0.113.20
; 203.0.113.30 → REMOVED (health check failed)
saas.example.com.    60     IN     A     203.0.113.40
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Full path** | Traces from browser cache → stub → recursive → root → TLD → authoritative |
| **Caching** | Explains TTL, negative caching, cache poisoning mitigation (DNSSEC) |
| **Anycast** | Knows BGP anycast can cause different PoPs to see different cached states |
| **Fix** | Proposes DNS health checks (not just monitoring) |

---

## 6. Load Balancing: L4 vs L7, Consistent Hashing

**Q:** "Design a load balancing strategy for a real-time chat service (WebSocket-based, 1M concurrent connections). Compare L4 (TCP) vs L7 (HTTP/2) load balancers. How do you handle connection draining for WebSocket persistence?"

**Answer:**

```yaml
L4 Load Balancer (e.g., HAProxy in TCP mode):
  - Sees TCP streams, forwards based on IP:port
  - Can't inspect HTTP headers, cookies, or paths
  - Pros: Fast (kernel-level), simple, works for ANY TCP protocol
  - Cons: No content-based routing, can't do SSL termination

L7 Load Balancer (e.g., Envoy, NGINX, AWS ALB):
  - Sees HTTP requests, headers, cookies, paths
  - Pros: Content routing (/api/v1 vs /api/v2), sticky sessions, SSL termination
  - Cons: Higher overhead, protocol-specific (HTTP/2, gRPC)

For WebSocket persistence:
  - L7: ALB supports WebSocket upgrade header → can route per connection
  - Sticky sessions via proxy_protocol header or IP hash
  - Connection draining:
    - Before rolling update: remove backend from pool, send health check FAIL
    - Wait for active connections to drain (max 60s)
    - New connections go to updated backends
    - [GW] → [LB] → [Backend 1 (DRAINING)]
              │        → [Backend 2 (ACTIVE)]
              └────────→ [Backend 3 (ACTIVE)]
```

---

## 7-12. Summary of Remaining Topics

7. **Connection Pooling & Keep-Alive**: HTTP keep-alive reuses TCP connections for multiple requests. Pool sizing with Little's Law. Connection starvation under high concurrency (too many connections → increased latency). H2 multiplexing eliminates head-of-line within a connection.

8. **gRPC vs REST**: REST uses HTTP/1.1 (or HTTP/2) with JSON; gRPC uses HTTP/2 with Protocol Buffers (binary). gRPC: 4× smaller payloads, 7× faster, native streaming (unary, server-streaming, client-streaming, bidirectional). Downside: browser support requires gRPC-Web.

9. **CDN Architecture**: Origin shield (cache hierarchy), edge PoP routing via anycast, cache invalidation (purge by tag/URL), stale-while-revalidate (serve stale content while fetching fresh). Key CDN tunables: Cache-Control with s-maxage, Surrogate-Key tags for batch purge.

10. **TCP TIME_WAIT & Port Exhaustion**: TIME_WAIT = 2× MSL (~120s). With 50K connections/s and 120s TIME_WAIT: 6M entries in TIME_WAIT. Ephemeral port range exhausted (28K ports × 60s = 1.6M/min). Solutions: socket reuse (SO_REUSEADDR), connection pooling (reduce connection rate), increase ephemeral range.

11. **Network Namespaces**: Each container gets its own network namespace (independent routing table, iptables, interfaces). Veth pairs connect namespaces. Overlay networks (VXLAN, Flannel, Calico) encapsulate packets with UDP headers for cross-host container networking.

12. **Packet Capture Analysis**: tcpdump → Wireshark for debugging. Key flags: SYN (handshake start), FIN (clean close), RST (abrupt close, errors), PSH (push data to app). Common issues: retransmissions (>0.1% = problem), dup ACKs (>3 = packet loss), zero-window probes (receiver overwhelmed)

---

> *Each of these 7 topics deserves detailed code examples and evaluation rubrics. See the companion architecture resources for full treatments.*

