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

**What They're Really Testing:** Whether you understand the architectural trade-offs between L4 and L7 load balancing, and can design for connection affinity at scale.

### Answer

**L4 vs L7 — Layer-by-Layer Breakdown:**

```
L4 Load Balancer (e.g., HAProxy TCP mode, AWS NLB, Keepalived):
┌──────────────────────────────────────────┐
│ Sees TCP segments only (no HTTP content) │
│ Forwarding: IP:port → IP:port            │
│ Algorithms: Round-robin, least conn, IP hash │
│ Pros: ~10µs per packet, kernel-bypass (DPDK) │
│ Cons: No path-based routing, no header inspect │
│        No TLS termination                 │
└──────────────────────────────────────────┘

L7 Load Balancer (e.g., NGINX, Envoy, AWS ALB, HAProxy HTTP mode):
┌──────────────────────────────────────────┐
│ Sees HTTP requests, headers, cookies     │
│ Forwarding: HTTP method + path + headers │
│ Algorithms: Least request, weighted, ring hash │
│ Pros: Content routing, TLS termination, header mod │
│ Cons: ~100µs per request, more CPU/memory     │
└──────────────────────────────────────────┘
```

**WebSocket Connection Persistence:**

```
WebSocket upgrade handshake:
Client                     LB                    Backend
  │                         │                      │
  ├── HTTP Upgrade: ───────►│                      │
  │    websocket            │                      │
  │    Connection: Upgrade  │                      │
  │                         ├── Route to backend ──►│
  │                         │   (consistent hash    │
  │                         │    on client IP)      │
  │◄── 101 Switching ──────┤◄── 101 Switching ─────┤
  │    Protocols            │                       │
  │                         │                       │
  │◄══ WebSocket frames ═══►│◄══ WebSocket ═══════►│
  │  (bidirectional)       │   (bidirectional)     │

Sticky session strategies:
  1. IP hash: hash(client_ip) % backends
     - Simple, but uneven if clients behind same NAT
  2. Cookie insert: LB sets cookie with backend ID
     - Works through NAT, but can leak backend topology
  3. Consistent hashing: ring hash with virtual nodes
     - Best for WebSocket: only affected connections rebalanced on scale
```

**Connection Draining — Graceful Shutdown:**

```python
# Connection draining lifecycle:

class LoadBalancer:
    def __init__(self):
        self.backends = {}  # {name: Backend}
        self.health_checks = {}  # {name: status}

    def rolling_update(self, backend_name: str):
        """
        Step 1: Mark backend as DRAINING
        - Remove from active pool
        - Stop sending NEW connections
        - Allow EXISTING connections to finish (max 60s)
        """
        backend = self.backends[backend_name]
        backend.status = 'DRAINING'

        # Send health check failure to upstream routers
        self.health_checks[backend_name] = 'UNHEALTHY'

        # Wait for active connections to drain
        start = time.time()
        while backend.active_connections > 0:
            if time.time() - start > 60:
                backend.force_close = True
                break
            time.sleep(1)

        # Step 2: Kill remaining connections (timeout reached)
        for conn in backend.active_connections:
            conn.send(RST_frame)
            conn.close()

        # Step 3: Update backend (code push, config change)
        backend.update()
        backend.status = 'ACTIVE'
        backend.health_checks[backend_name] = 'HEALTHY'

    def route_request(self, client_ip, request):
        """Route new connections to healthy backends only."""
        healthy = [b for b in self.backends.values() if b.status == 'ACTIVE']
        idx = hash(client_ip) % len(healthy)
        return healthy[idx]
```

**Consistent Hashing for WebSocket Affinity:**

```python
class ConsistentHashRing:
    """
    Consistent hashing with virtual nodes.
    When backends change, only 1/N connections are remapped.
    """
    def __init__(self, virtual_nodes: int = 100):
        self.ring = {}  # {hash: backend_name}
        self.sorted_hashes = []
        self.virtual_nodes = virtual_nodes

    def add_backend(self, name: str):
        for i in range(self.virtual_nodes):
            vnode_hash = hash(f"{name}:{i}")
            self.ring[vnode_hash] = name
        self.sorted_hashes = sorted(self.ring.keys())

    def remove_backend(self, name: str):
        for i in range(self.virtual_nodes):
            vnode_hash = hash(f"{name}:{i}")
            del self.ring[vnode_hash]
        self.sorted_hashes = sorted(self.ring.keys())

    def get_backend(self, key: str) -> str:
        """Return the backend for this key (client IP)."""
        if not self.sorted_hashes:
            return None
        key_hash = hash(key)
        # Binary search for first hash >= key_hash
        idx = bisect_left(self.sorted_hashes, key_hash)
        if idx == len(self.sorted_hashes):
            idx = 0  # Wrap around
        return self.ring[self.sorted_hashes[idx]]

# When scaling from 4 → 5 backends:
# With vanilla hashing: 80% of connections remapped (disconnects!)
# With consistent hashing: ~20% of connections remapped (acceptable for WebSocket)
```

**Production Configuration (Envoy):**

```yaml
# Envoy proxy configuration for WebSocket load balancing
static_resources:
  listeners:
  - name: websocket_listener
    address:
      socket_address: { address: 0.0.0.0, port_value: 443 }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          upgrade_configs:
          - upgrade_type: websocket
          route_config:
            virtual_hosts:
            - name: chat
              domains: ["chat.example.com"]
              routes:
              - match: { prefix: "/ws" }
                route:
                  cluster: websocket_backends
                  timeout: 0s  # No timeout for WebSocket
                  idle_timeout: 3600s  # 1 hour idle max
  clusters:
  - name: websocket_backends
    connect_timeout: 5s
    type: STRICT_DNS
    lb_policy: RING_HASH  # Consistent hashing
    lb_subset_config:
      fallback_policy: ANY_ENDPOINT
    health_checks:
      timeout: 1s
      interval: 5s
      unhealthy_threshold: 2
      healthy_threshold: 2
      http_health_check:
        path: /health
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **L4 vs L7 trade-offs** | Quantifies latency/capability differences, knows when each is appropriate |
| **WebSocket affinity** | Explains upgrade handshake, sticky session mechanisms, consistent hashing |
| **Connection draining** | Describes graceful shutdown lifecycle with health check manipulation |
| **Production config** | References real tools (Envoy, NGINX) and specific config parameters |

---

## 7. Connection Pooling & Keep-Alive

**Q:** "Our microservice handles 10K requests/second but we're seeing 'connection refused' errors and high TIME_WAIT counts. Each request creates a new TCP connection. Walk through connection pooling: pool sizing with Little's Law, keep-alive tuning, and HTTP/2 multiplexing benefits."

**What They're Really Testing:** Whether you understand the queuing theory behind connection pooling and can size pools correctly using Little's Law.

### Answer

**The Problem — Connection Per Request:**

```
Without pooling:
  Request → TCP connect (SYN/SYN-ACK/ACK 1.5 RTT) → HTTP request → response → close (FIN/FIN-ACK)

  Latency per request: 1.5 RTT + response time + 0.5 RTT
  Connections created: 10,000/s
  TIME_WAIT entries: 10,000 × 120s (2MSL) = 1,200,000 simultaneous entries

  At 65K ephemeral ports: exhaustion in ~6.5 seconds!
```

**Little's Law for Pool Sizing:**

```python
# Little's Law: L = λ × W
#   L = average number of connections in the pool (occupied)
#   λ = arrival rate (requests/second)
#   W = average time a connection is held (seconds)

# Example:
request_rate = 10000  # 10K req/s
avg_request_time = 0.050  # 50ms per request (including network)
connections_occupied = request_rate * avg_request_time
# = 10,000 × 0.05 = 500 connections

# But we need HEADROOM for bursts:
# Target pool size = occupied × (1 + burst_factor)
pool_size = int(connections_occupied * 1.5)  # 750 connections

# With keep-alive, connections can be reused:
connections_occupied_with_keepalive = 10000 * 0.002  # 2ms reused
# = 20 connections!  (much smaller pool)
```

**Keep-Alive Tuning:**

```python
# HTTP keep-alive: reuse TCP connection for MULTIPLE requests
#
# Without keep-alive:
#   1 request = 1 TCP handshake (1.5 RTT) + 1 HTTP transaction + 1 teardown
#
# With keep-alive:
#   1st request = 1 TCP handshake, then connection stays open
#   Subsequent requests = 0 handshake, just HTTP on existing connection
#
# Optimal keep-alive timeout:
#   Too short: connections close before next request (wasted potential reuse)
#   Too long: idle connections consume memory (each ~4KB in kernel)

# Calculation:
avg_idle_time = 0.1  # 100ms between requests on same connection
max_idle_time = 5.0  # 5 seconds maximum wait

# NGINX configuration:
# keepalive_timeout 65;  # Close idle connections after 65s
# keepalive_requests 1000;  # Max requests per connection

# Envoy configuration:
# idle_timeout: 3600s  # 1 hour max idle
# max_requests_per_connection: 1000
```

**Connection Starvation Under High Concurrency:**

```yaml
Problem: Too many concurrent connections → each gets slower → 
         connections held longer → more connections needed → death spiral

Trace:
  1. Normal: 10K req/s, 50ms avg, pool=500
  2. Spike: 20K req/s, pool=500 → queue builds in LB
  3. Queue wait increases response time from 50ms → 200ms
  4. Little's Law: L = 20K × 0.2 = 4000 needed (8x pool size!)
  5. New connections created → ephemeral port exhaustion
  6. "Connection refused" errors

Solutions:
  a. Increase pool size preemptively before spikes
  b. Rate-limit at LB (reject early vs crash late)
  c. Circuit breaker: fail fast rather than queue
  d. HTTP/2 multiplexing: 1 connection carries N streams
```

**HTTP/2 Multiplexing Benefits:**

```python
# HTTP/1.1 with keep-alive:
#   6 connections × 10 requests each = 60 concurrent requests
#   Each connection handles 1 request at a time (pipelining risky)
#
# HTTP/2 multiplexing:
#   1 connection × 128 streams = 128 concurrent requests
#   Streams are truly parallel (interleaved frames)

# HTTP/2 eliminates head-of-line blocking WITHIN a connection:
#   Stream 1: |------req1------|------resp1------|
#   Stream 2: |----req2----|----resp2----|
#   Stream 3: |--------req3--------|--------resp3--------|
#   Time:     |______________________________|
#
# Compare to HTTP/1.1 keep-alive:
#   Connection 1: |--req1--|--resp1--|--req2--|--resp2--|...
#   (sequential — one request at a time)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Little's Law** | Applies L = λW correctly, calculates pool size with headroom |
| **Keep-alive trade-offs** | Explains timeout tuning, max requests, memory implications |
| **Connection starvation** | Traces the death spiral, proposes circuit breakers |
| **H2 multiplexing** | Understands stream-level parallelism vs H1.1 sequential |

---

## 8. gRPC vs REST: Wire Protocol Comparison

**Q:** "A mobile app sends 500-byte payloads at 100 req/s per device. Currently using REST/JSON. The team proposes migrating to gRPC. Compare wire formats, performance, and streaming capabilities. When would you NOT use gRPC?"

**What They're Really Testing:** Whether you understand the protocol-level differences — serialization, framing, streaming — not just buzzwords.

### Answer

**Wire Format Deep Dive:**

```protobuf
// REST/JSON:
POST /api/users HTTP/1.1
Content-Type: application/json
Content-Length: 85

{
  "name": "Alice",
  "email": "alice@example.com",
  "role": "admin",
  "age": 30
}
// Wire size: ~120 bytes (85 payload + 35 headers)

// gRPC/Protobuf:
// .proto definition:
message CreateUserRequest {
  string name = 1;
  string email = 2;
  string role = 3;
  int32 age = 4;
}

// Protobuf binary encoding (varint + length-delimited):
// Field 1 (string): tag(0x0A) + len(5) + "Alice"
// Field 2 (string): tag(0x12) + len(17) + "alice@example.com"
// Field 3 (string): tag(0x1A) + len(5) + "admin"
// Field 4 (int32):  tag(0x20) + varint(30)
// Wire size: ~40 bytes (no headers beyond HTTP/2 frames)
```

**Performance Comparison:**

```python
# Serialization benchmarks (protobuf vs JSON):

# JSON serialization (Python json.dumps):
#   10,000 objects: ~45ms, ~120 bytes each
#   CPU: ~4.5μs/byte
#   Memory: temporary strings for each field

# Protobuf serialization:
#   10,000 objects: ~8ms, ~40 bytes each
#   CPU: ~0.8μs/byte (binary, no string parsing)
#   Memory: direct write to buffer

# Wire comparison for 100 req/s per device:
# JSON: 100 × 120B × 1000 devices = 12 MB/s bandwidth
# gRPC: 100 × 40B × 1000 devices = 4 MB/s bandwidth
# Savings: 67% bandwidth reduction

# CPU comparison (server-side per request):
# JSON parsing: ~5μs (string-based)
# Protobuf parsing: ~1μs (binary, fixed schema)
```

**Streaming Patterns:**

```protobuf
service ChatService {
  // Unary (traditional request-response)
  rpc SendMessage(SendMessageRequest) returns (SendMessageResponse);

  // Server-streaming (server pushes multiple responses)
  rpc SubscribeMessages(SubscribeRequest) returns (stream Message);

  // Client-streaming (client sends multiple requests)
  rpc UploadFiles(stream FileChunk) returns (UploadResponse);

  // Bidirectional streaming (full duplex)
  rpc Chat(stream ChatMessage) returns (stream ChatMessage);
}
```

**HTTP/2 Frame Anatomy for gRPC:**

```
REST/HTTP/1.1:
|-------- TCP segment --------|
| HTTP/1.1 request headers    |
| JSON body                   |
|------------------------------|
One TCP segment holds both headers and body

gRPC/HTTP/2:
|-------- HTTP/2 frame --------|
| Frame header (9 bytes):      |
|   Length: 3 bytes            |
|   Type: 1 byte (DATA)        |
|   Flags: 1 byte (END_STREAM) |
|   Stream ID: 4 bytes         |
|------------------------------|
| gRPC header (5 bytes):       |
|   Compression: 1 byte (0=no) |
|   Message length: 4 bytes    |
|------------------------------|
| Protobuf payload (variable)  |
|------------------------------|
```

**When NOT to Use gRPC:**

```yaml
Use REST when:
  - Browser clients (gRPC-Web has limitations: no bidirectional streaming,
    no trailing metadata, requires proxy)
  - Public-facing APIs (curl, Postman, easy debugging)
  - Simple CRUD with no streaming needs
  - Team unfamiliar with protobuf schema management
  - Caching (HTTP caching works naturally with REST)

Use gRPC when:
  - Internal microservice-to-microservice communication
  - Mobile apps (smaller payloads = faster on cellular)
  - Real-time streaming (chat, events, logs)
  - Polyglot environments (auto-generated clients in 11+ languages)
  - Performance-critical paths (sub-millisecond serialization)

Hybrid approach:
  - Expose REST/JSON externally (API gateway translates to gRPC)
  - Internal services communicate via gRPC
  - This gives you both: developer-friendly API + performant internals
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Wire format knowledge** | Explains protobuf varint encoding, tag-length-value, HTTP/2 framing |
| **Performance quant** | Provides actual serialization speed/ size numbers, not just "faster" |
| **Streaming modes** | Knows all 4 gRPC streaming patterns and their use cases |
| **Trade-off decision** | Articulates clear criteria for when NOT to use gRPC (browsers, public APIs) |

---

## 9. CDN Architecture & Caching Strategies

**Q:** "Design a CDN caching strategy for a global news website with 500M monthly visitors. Articles are updated frequently (breaking news), images are mostly static, and APIs need <50ms response. How do you handle cache invalidation, origin shielding, and stale-while-revalidate?"

**What They're Really Testing:** Whether you understand CDN internals at the architecture level — cache hierarchy, purge mechanics, and HTTP caching directives.

### Answer

**CDN Cache Hierarchy:**

```
                          ┌─────────────────────┐
                          │   Origin Server      │
                          │   (us-east-1)        │
                          └──────────┬──────────┘
                                     │
                     ┌───────────────┴───────────────┐
                     │        Origin Shield          │
                     │    (single PoP, acts as       │
                     │     write-through cache)      │
                     └───────────────┬───────────────┘
                                     │
        ┌────────────┬──────────────┼──────────────┬────────────┐
        │            │              │              │            │
   ┌────▼────┐ ┌────▼────┐  ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
   │Edge PoP1│ │Edge PoP2│  │Edge PoP3│  │Edge PoP4│  │Edge PoP5│
   │ (NYC)   │ │ (LON)   │  │ (SGP)   │  │ (SYD)   │  │ (SAO)   │
   └─────────┘ └─────────┘  └─────────┘  └─────────┘  └─────────┘

Without origin shield:
  - 5 PoPs × 100 req/s each = 500 req/s to origin
  - Cache miss storm: ALL PoPs miss simultaneously → 500 req/s to origin

With origin shield:
  - Shield absorbs 500 req/s → only 1 req/s to origin (shield hit serves all)
  - Shield is L2 cache: larger, slower eviction, higher capacity
```

**Cache Invalidation Strategies:**

```python
# Strategy 1: TTL-based (time-to-live)
#   Static assets: Cache-Control: public, max-age=31536000, immutable
#   API responses: Cache-Control: public, max-age=60, stale-while-revalidate=300
#   News articles: Cache-Control: public, max-age=300, stale-if-error=86400

# Strategy 2: Purge by URL
curl -X POST https://api.fastly.com/service/abc/purge/articles/breaking-news
#   Invalidates single URL across ALL edge PoPs
#   Propagation: ~200ms globally (anycast purge messages)

# Strategy 3: Purge by tag (Surrogate-Key)
#   Set multiple tags per response:
Surrogate-Key: "articles section:world author:jdoe breaking-news"
#   Purge all articles about world news:
curl -X POST https://api.fastly.com/service/abc/purge/section:world
#   All cached responses tagged 'section:world' are invalidated

# Strategy 4: Stale-while-revalidate
#   Serve stale content while fetching fresh version in background
#   Cache-Control: public, max-age=60, stale-while-revalidate=86400
#   0-60s: fresh (served from cache, instant)
#   61-86460s: stale but acceptable (served from cache + background refresh)
#   86460s+: must fetch from origin (blocking miss)
```

**Anycast Routing (How CDNs Work):**

```python
# Anycast: multiple servers share the SAME IP address
# BGP announces the same /24 prefix from multiple locations
# Client routes to the CLOSEST PoP based on BGP path length

# Example: Fastly's anycast IP 151.101.1.1
#   Client in London: BGP path → LON PoP (1 hop, ~5ms)
#   Client in Sydney: BGP path → SYD PoP (1 hop, ~15ms)
#   Client in Tokyo: BGP path → SGP PoP (2 hops, ~30ms)
#
# Problem: BGP doesn't account for server LOAD
#   If LON PoP is overloaded, client still routes there
#   Solution: DNS-based GSLB + Anycast
#     DNS returns multiple A records, ordered by health/load
#     Client picks first (usually closest), but can fall back
```

**CDN Configuration (Fastly VCL / Cloudfront):**

```c
// Fastly VCL for news website:
sub vcl_recv {
    // API requests: bypass cache for mutations
    if (req.url ~ "^/api/") {
        if (req.method != "GET") {
            return (pass);  // Never cache POST/PUT/DELETE
        }
        // Cache GET API responses for 30s
        set req.ttl = 30s;
        set req.grace = 300s;  // Serve stale for 5m
    }

    // Static assets: long cache + immutable
    if (req.url ~ "\.(js|css|png|jpg|woff2)$") {
        set req.ttl = 365d;
        set req.stale_while_revalidate = true;
    }

    // News articles: short TTL, but serve stale if origin down
    if (req.url ~ "^/article/") {
        set req.ttl = 5m;
        set req.stale_if_error = 24h;
    }
}

sub vcl_fetch {
    // Set surrogate keys for batch purge
    if (beresp.http.Content-Type ~ "text/html") {
        # Tag with section and author from response headers
        set beresp.http.Surrogate-Key = beresp.http.X-Section
                                        + " " + beresp.http.X-Author;
    }
}
```

**Metrics to Monitor:**

```yaml
Key CDN metrics:
  - Cache hit ratio: 90-95% target for static, 70% for dynamic
  - Origin load: req/s sent to origin (should be <5% of edge traffic)
  - Purge propagation time: time for purge to reach all PoPs
  - Stale serves: how often stale content was served (monitor for freshness)
  - Shield hit ratio: should be >99% (shield absorbs all edge misses)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cache hierarchy** | Explains edge → shield → origin, why shield prevents cache miss storms |
| **Invalidation** | Knows TTL, URL purge, tag-based purge, surrogate keys |
| **Stale patterns** | Understands stale-while-revalidate and stale-if-error trade-offs |
| **Anycast + DNS** | Explains BGP anycast routing, GSLB, and their limitations |

---

## 10. TCP TIME_WAIT & Ephemeral Port Exhaustion

**Q:** "A high-traffic web server handling 50K connections/second is experiencing intermittent 'address already in use' errors and connections timing out. You notice thousands of sockets in TIME_WAIT. Diagnose the problem and propose solutions."

**What They're Really Testing:** Whether you understand TCP connection lifecycle at the system level — TIME_WAIT purpose, port exhaustion math, and mitigation strategies.

### Answer

**TCP Connection Lifecycle:**

```
CLOSED
  │
  ▼
SYN_SENT ────► SYN_RCVD
  │               │
  ▼               ▼
ESTABLISHED ◄────┘
  │
  ├── ACTIVE CLOSE ──► FIN_WAIT_1 ──► CLOSE_WAIT ──► LAST_ACK ──► CLOSED
  │                       │               │
  │                       ▼               │
  │                   FIN_WAIT_2 ◄────────┘
  │                       │
  ▼                       ▼
TIME_WAIT (2MSL = 120s) ──► CLOSED
```

**The Purpose of TIME_WAIT:**

```
TIME_WAIT serves TWO critical purposes:

1. Ensure the remote peer received the final ACK
   - If final ACK is lost, remote will retransmit FIN
   - TIME_WAIT allows handling of retransmitted FIN
   - Without TIME_WAIT: remote retransmits FIN → new connection receives stale FIN → RST

2. Prevent delayed segments from corrupting new connections
   - An old packet from connection (A:1234, B:80) with SEQ=1000 arrives
   - New connection (A:1234, B:80) might interpret it as valid data
   - TIME_WAIT ensures old segments have expired before port reuse
   - 2MSL = 2 × Maximum Segment Lifetime = 120s (RFC 793)
```

**Ephemeral Port Exhaustion Math:**

```python
# Linux ephemeral port range:
#   /proc/sys/net/ipv4/ip_local_port_range
#   Default: 32768 → 60999 (28,232 ports)

# Each connection uses:
#   - 1 ephemeral port on the CLIENT side
#   - 1 tuple: (src_ip, src_port, dst_ip, dst_port)
#   - If client has 1 IP and server has 1 IP: max 28,232 concurrent connections

# At 50K connections/second with TIME_WAIT=120s:
connections_per_second = 50000
timewait_duration = 120  # seconds
total_timewait_entries = connections_per_second * timewait_duration
# = 50,000 × 120 = 6,000,000 simultaneous TIME_WAIT entries

# But we only have 28,232 ports!
# After ~0.56 seconds: ALL ports are in TIME_WAIT
# After ~0.56 seconds: EVERY new connection fails with EADDRNOTAVAIL

# Wait, this is the CLIENT side problem. For server-side:
# Server listens on fixed port (e.g., :80)
# Server identifies connections by 4-tuple: (client_ip, client_port, server_ip, server_port)
# Server doesn't exhaust ports — it accepts connections from many clients
# But CLIENT exhausts ephemeral ports if opening many connections to same server

# Scenario where server IS the client (e.g., proxy server):
# Proxy ←→ Backend: proxy opens connections to backend
# Proxy has: 1 IP, backend has: 1 IP
# Proxy is CLIENT in this connection → ephemeral port exhaustion!
```

**Mitigation Strategies:**

```shell
# Strategy 1: Increase ephemeral port range
echo 1024 65535 > /proc/sys/net/ipv4/ip_local_port_range
# 64,511 ports available (vs 28,232)
# At 50K/s: 64,511 / 50,000 = 1.29 seconds before exhaustion (better but not enough)

# Strategy 2: Enable SO_REUSEADDR / SO_REUSEPORT
# SO_REUSEADDR: allows binding to a port in TIME_WAIT
# SO_REUSEPORT: allows multiple sockets to bind to same port (kernel load balances)
setsockopt(socket, SOL_SOCKET, SO_REUSEADDR, 1)
setsockopt(socket, SOL_SOCKET, SO_REUSEPORT, 1)

# BUT: SO_REUSEADDR doesn't help with ephemeral port exhaustion!
# It helps the SERVER bind to a port, not the CLIENT's port selection
# For CLIENT-side exhaustion: need SO_LINGER with 0 timeout (risky!)

# Strategy 3: Reduce TIME_WAIT duration
echo 30 > /proc/sys/net/ipv4/tcp_fin_timeout
# WARNING: Reducing below 60s violates TCP spec (2MSL)
# Can cause segment corruption on port reuse
# Only do this if you fully understand the risks

# Strategy 4: Connection Pooling (BEST)
# Instead of creating new connections, REUSE existing ones
# HTTP keep-alive: 1 connection handles 100+ requests
# Connection pool: replace 50K new connections/s with ~500 reused connections
pool = ConnectionPool(max_connections=1000)
# All requests share pool → TIME_WAIT rate drops from 50K/s to ~1K/s

# Strategy 5: Multiple client IPs
# Bind to multiple source IPs → multiply available tuples
# Each IP adds 28K ports → with 10 IPs: 280K tuples
# ip addr add 10.0.0.10/24 dev eth0
# ip addr add 10.0.0.11/24 dev eth0
# Then bind sockets to specific source IPs

# Strategy 6: TCP_TW_REUSE (Linux-specific)
echo 1 > /proc/sys/net/ipv4/tcp_tw_reuse
# Allows kernel to reuse TIME_WAIT sockets for NEW outbound connections
# Kernel checks if timestamp of old connection < new connection timestamp
# Safe for outbound connections (client side)
# Does NOT work for inbound (server) connections

# Strategy 7: TCP_TW_RECYCLE (DEPRECATED, removed in Linux 4.12)
# Was faster than TW_REUSE but broke NAT (timestamp-based validation)
# DO NOT USE this on modern kernels
```

**Practical Decision Tree:**

```python
def diagnose_timewait(conn_rate: int, current_tw_count: int):
    """Diagnose TIME_WAIT problem and recommend solution."""
    port_range = 65535 - 1024  # 64,511
    ports_needed_per_sec = conn_rate * 120  # 120s TIME_WAIT

    if ports_needed_per_sec < port_range:
        print("TIME_WAIT is normal, no concern")
        print(f"Only using {ports_needed_per_sec}/{port_range} ports")
        return

    print(f"EPHEMERAL PORT EXHAUSTION: need {ports_needed_per_sec} ports")
    print(f"Available: {port_range}")
    print()
    print("Recommended solution: CONNECTION POOLING")
    print(f"  At {conn_rate} req/s with keep-alive reusing 100 req/conn:")
    print(f"  New conn rate: {conn_rate // 100}/s")
    print(f"  TIME_WAIT count: {(conn_rate // 100) * 120} (manageable)")
    print()
    print("Secondary: increase port range + enable tcp_tw_reuse")
    print("Tertiary: add multiple client IPs")
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **TIME_WAIT purpose** | Explains both functions: final ACK protection and segment expiration |
| **Port exhaustion math** | Calculates exact time to exhaustion given conn rate and port range |
| **Mitigation priority** | Recommends connection pooling first, then sysctl tuning, then multi-IP |
| **Kernel specifics** | Knows tcp_tw_reuse vs tcp_tw_recycle, SO_REUSEADDR limitations |

---

## 11. Network Namespaces & Overlay Networks

**Q:** "Design the container networking for a Kubernetes cluster with 1000 nodes. Containers on different nodes need to communicate as if they're on the same flat network. Walk through network namespaces, veth pairs, and overlay networks (VXLAN, Calico)."

**What They're Really Testing:** Whether you understand Linux networking primitives at the namespace level — veth, bridges, iptables, and overlay encapsulation.

### Answer

**Network Namespace — The Isolation Primitive:**

```bash
# Each container gets its own network namespace:
#   - Independent routing table
#   - Independent iptables rules
#   - Independent set of network interfaces
#   - Independent ARP table

# Create a network namespace:
ip netns add container1

# Run a process in a namespace:
ip netns exec container1 ip addr
# Shows: lo (down) — nothing else, completely isolated

# Each namespace has:
#   lo: loopback (127.0.0.1)
#   eth0: veth pair connected to host bridge
```

**Veth Pairs — Connecting Namespaces:**

```
Host Network Namespace:
┌─────────────────────────────────────┐
│ Bridge (docker0 / cbr0)             │
│ ┌────────────────────────────────┐  │
│ │ veth1    veth2    veth3        │  │
│ └──┬───────┬────────┬───────────┘  │
│    │       │        │              │
└────┼───────┼────────┼──────────────┘
     │       │        │
┌────┴──┐ ┌──┴────┐ ┌┴───────┐
│ eth0  │ │ eth0  │ │ eth0   │   <- veth peer in container
│       │ │       │ │        │
│ Cont1 │ │ Cont2 │ │ Cont3  │
│ NS    │ │ NS    │ │ NS     │
└───────┘ └───────┘ └────────┘

# veth pair = virtual ethernet cable:
#   - Packets sent on one end appear on the other
#   - Each end can be in a different namespace
#   - Acts like a patch cable between namespaces

ip link add veth0 type veth peer name eth0
ip link set veth0 master bridge0  # Connect host side to bridge
ip link set eth0 netns container1 # Move container side to namespace
```

**Overlay Networks — VXLAN:**

```python
# Problem: containers on Node A need to talk to containers on Node B
# Node A: 10.0.0.1, Pod CIDR: 10.1.0.0/16
# Node B: 10.0.0.2, Pod CIDR: 10.2.0.0/16

# VXLAN = Virtual Extensible LAN
# Encapsulates L2 frames in UDP packets over L3 network
#      +--- Outer Ethernet ---+--- Outer IP ---+--- Outer UDP ---+--- VXLAN ---+--- Inner Ethernet ---+--- Inner IP ---+
#      | dst: NodeB MAC       | dst: NodeB IP  | dst port: 4789  | VNI: 100    | dst: PodB MAC       | dst: PodB IP  |
#      +----------------------+----------------+-----------------+-------------+---------------------+---------------+

# VXLAN Header:
#   Flags (8 bits): VNI present flag
#   Reserved (24 bits)
#   VNI (24 bits): Virtual Network Identifier (up to 16M networks)
#   Reserved (8 bits)

# Setting up VXLAN on Node A:
ip link add vxlan0 type vxlan     id 100 \                    # VNI
    dstport 4789 \              # Standard VXLAN port
    local 10.0.0.1 \            # Local tunnel IP
    remote 10.0.0.2 \           # Remote tunnel IP (or group for multicast)
    dev eth0                    # Underlay interface

ip link set vxlan0 master bridge0  # Attach to Pod bridge
ip link set vxlan0 up
```

**CNI Plugins Compared:**

```yaml
Flannel (VXLAN):
  - Simple, widely used
  - Encapsulation overhead: 50 bytes per packet (14 eth + 20 IP + 8 UDP + 8 VXLAN)
  - MTU adjustment: 1500 - 50 = 1450
  - Performance: ~90% of line rate (encap/decap overhead)

Calico (no overlay — pure L3 routing):
  - No encapsulation — uses BGP to distribute routes
  - Each node announces Pod CIDR via BGP peering
  - Packet travels: Pod → veth → host → router → Node B → veth → Pod
  - No MTU overhead: 1500 MTU
  - Performance: ~98% of line rate (no encap/decap)
  - Downside: requires L3 fabric (BGP support), no L2 adjacency

Cilium (eBPF-based):
  - Uses eBPF for networking, load balancing, security
  - Can use VXLAN, Geneve, or direct L3 routing
  - eBPF programs attached to network hooks bypass iptables
  - Performance: near-native (~99% of line rate with eBPF)
  - Supports: Hubble observability, L7 policies, cluster mesh

Weave (fast datapath):
  - Uses Linux kernel OVS fast path + encryption
  - Can use VXLAN with UDP aggregation
  - Better for cross-cloud (AWS ↔ GCP) with encryption
```

**Packet Walk — VXLAN:**

```
Pod A (10.1.0.5) sends to Pod B (10.2.0.10):

1. Pod A ARP for 10.2.0.10 → resolved via bridge FDB or ARP proxy
2. Packet: src=10.1.0.5 dst=10.2.0.10
3. Leaves Pod A via veth pair → bridge0 on Node A
4. Bridge looks up MAC → learned via VXLAN tunnel
5. VXLAN encapsulation:
   src MAC: NodeA_eth0_MAC
   dst MAC: NodeB_eth0_MAC
   src IP: 10.0.0.1
   dst IP: 10.0.0.2
   UDP src: random port
   UDP dst: 4789
   VNI: 100
   Original packet (Pod A → Pod B)
6. Packet travels over physical network
7. Node B receives, UDP port 4789 → vxlan0
8. VXLAN decapsulation: check VNI 100
9. Inner packet: src=10.1.0.5 dst=10.2.0.10
10. Forwards to bridge0 → veth pair → Pod B
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Namespace isolation** | Knows namespaces have separate routing, iptables, interfaces |
| **Veth pairs** | Explains how veth connects namespaces, bridge role |
| **Overlay encapsulation** | Understands VXLAN header structure, MTU implications, VNI purpose |
| **CNI comparison** | Can compare Flannel vs Calico vs Cilium with performance numbers |

---

## 12. Packet Capture Analysis: Production Debugging

**Q:** "Users report intermittent slow page loads. Using tcpdump, you capture traffic and see retransmissions, dup ACKs, and zero-window probes. Walk through how you'd analyze the capture to identify the root cause."

**What They're Really Testing:** Whether you can use packet-level analysis to diagnose real network problems — not just tool knowledge but protocol-level reasoning.

### Answer

**Packet Capture Toolchain:**

```bash
# Production-safe capture (ring buffer, no disk fill):
tcpdump -i eth0 -w /tmp/capture.pcap     -C 100 \          # Rotate at 100MB per file
    -W 10 \           # Max 10 files (1GB total)
    -s 96 \           # Snaplen 96 bytes (headers only, no payload)
    port 443          # Filter: only HTTPS traffic

# Common capture filters:
#   host 10.0.0.5                    # Specific IP
#   tcp port 80 and host 10.0.0.5   # HTTP to specific host
#   tcp[13] & 2 != 0                # SYN packets only
#   tcp[13] & 4 != 0                # RST packets only
#   tcp[13] & 16 != 0               # ACK packets only
#   tcp[13] & 24 = 24               # SYN-ACK packets
#   (tcp[13] & 8 = 8) or (tcp[13] & 16 = 16)  # PSH or ACK
```

**Reading TCP Flags from Hex:**

```python
# TCP header byte 13 (flags):
#   0x00 = no flags
#   0x01 = FIN (finished sending)
#   0x02 = SYN (synchronize, handshake start)
#   0x04 = RST (reset, error/abort)
#   0x08 = PSH (push, deliver to application now)
#   0x10 = ACK (acknowledgment)
#   0x20 = URG (urgent)
#   0x40 = ECE (congestion experienced)
#   0x80 = CWR (congestion window reduced)

# Common flag combinations:
#   SYN: 0x02
#   SYN-ACK: 0x12 (0x02 | 0x10)
#   ACK: 0x10
#   FIN-ACK: 0x11 (0x01 | 0x10)
#   RST: 0x04
#   PSH-ACK: 0x18 (0x08 | 0x10)

# Using tcpdump flag expression:
tcpdump 'tcp[tcpflags] & tcp-syn != 0'     # All SYN packets
tcpdump 'tcp[tcpflags] & (tcp-syn|tcp-ack) == (tcp-syn|tcp-ack)'  # SYN-ACK
```

**Diagnosing Common Issues:**

```python
# Issue 1: Packet Retransmissions (>0.1% = problem)
# tcpdump output:
# 00:00.001 IP A.443 > B.54321: Flags [.], seq 1000:2000, ack 500
# 00:00.201 IP A.443 > B.54321: Flags [.], seq 1000:2000, ack 500  # RETRANSMISSION!
# 00:00.401 IP A.443 > B.54321: Flags [.], seq 1000:2000, ack 500  # AGAIN!

# Root causes:
#   - Network congestion (intermediate buffer drop)
#   - Packet corruption (CRC error → switch drops)
#   - Firewall dropping packets (stateful inspection timeout)
#   - Mismatched MTU (packet > path MTU, fragmented and lost)

# Diagnosis:
#   - Check retransmission rate: retransmits / total packets
#   - Check TCP RTT: if RTT spikes with retransmissions → congestion
#   - Check TCP window: if window is full → receiver slow, not network

# Issue 2: Duplicate ACKs (>3 = fast retransmit trigger)
# 00:00.001 IP B.54321 > A.443: Flags [.], ack 1000
# 00:00.002 IP B.54321 > A.443: Flags [.], ack 1000  # DUP ACK #1
# 00:00.003 IP B.54321 > A.443: Flags [.], ack 1000  # DUP ACK #2
# 00:00.004 IP B.54321 > A.443: Flags [.], ack 1000  # DUP ACK #3
# 00:00.005 IP A.443 > B.54321: Flags [.], seq 1000:2000  # Fast retransmit!

# Pattern: receiver saw out-of-order packet (gap)
# Got packet 2000:3000 but still waiting for 1000:2000
# Keeps ACKing 1000 to tell sender "I'm still waiting"

# Root causes:
#   - Single packet loss (the #1 most common issue)
#   - Reordering in network (rare with modern switches)

# Issue 3: Zero-Window Probes
# 00:00.001 IP B.54321 > A.443: Flags [.], ack 1000, win 0  # Window closed!
# 00:00.501 IP A.443 > B.54321: Flags [.], seq 1000:1100    # Probe (1 byte)
# 00:00.501 IP B.54321 > A.443: Flags [.], ack 1001, win 0  # Still closed
# 00:01.001 IP A.443 > B.54321: Flags [.], seq 1000:1100    # Probe again
# 00:01.001 IP B.54321 > A.443: Flags [.], ack 1001, win 65535  # Window opened!

# Root causes:
#   - Application not consuming data fast enough
#   - Buffer bloat at receiver (NIC buffer full)
#   - Slow application processing (database query, GC pause)
#   - Receiver CPU overload → can't drain socket buffer

# Diagnosis:
#   - Duration of zero window: how long was the receiver blocking?
#   - If >100ms: application-level issue (slow processing)
#   - If <10ms: normal TCP flow control
```

**Advanced Analysis with Wireshark/TShark:**

```bash
# TShark analysis (command-line Wireshark):
tshark -r capture.pcap -q -z io,stat,1,    "AVG(tcp.analysis.ack_rtt)tcp.analysis.ack_rtt",    "COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission",    "COUNT(tcp.analysis.fast_retransmission)tcp.analysis.fast_retransmission",    "COUNT(tcp.analysis.duplicate_ack)tcp.analysis.duplicate_ack",    "COUNT(tcp.analysis.zero_window)tcp.analysis.zero_window",    "COUNT(tcp.analysis.window_full)tcp.analysis.window_full"

# Expert info:
tshark -r capture.pcap -z expert,note

# HTTP request analysis:
tshark -r capture.pcap -Y "http.request" -T fields     -e http.request.method -e http.request.uri -e http.response.code     -e http.time -e ip.src -e ip.dst

# TCP stream reassembly:
tshark -r capture.pcap -z follow,tcp,ascii,0
```

**Real-World Debugging Example:**

```python
# Problem: Users report 3-second page load latency
# Suspect: TCP connection issue

# Step 1: Check connection establishment timing
tcpdump:
# 00:00.000 Client → Server: SYN                         # T=0ms
# 00:02.500 Server → Client: SYN-ACK                      # T=2500ms!
# 00:02.501 Client → Server: ACK                          # T=2501ms
# 00:02.502 Client → Server: GET /page                   # T=2502ms
# 00:02.505 Server → Client: HTTP Response                # T=2505ms

# Diagnosis: 2.5-second SYN→SYN-ACK delay!
# Root cause: Server SYN queue (listen backlog) overflow

# Check server's listen backlog:
ss -lntp | grep :443
# Recv-Q Send-Q Local Address
# 100    128    :::443               ← Recv-Q=100 (connections waiting to be accepted!)
#                                         Send-Q=128 (backlog limit)

# Connection: Server has 100 pending connections, backlog=128
# New SYN comes in → SYN queue full → server drops SYN
# Client retries after 1s, then 2s, then 4s (exponential backoff)
# At 2.5s: client's third SYN finally gets SYN-ACK

# Fix: Increase listen backlog
# In NGINX: listen 443 ssl backlog=4096;
# In sysctl: net.core.somaxconn=65536

# Verified fix: connection time drops from 2.5s to <1ms
```

**Performance Baseline Metrics:**

```yaml
Healthy TCP indicators:
  - Retransmission rate: <0.1% of total packets
  - Duplicate ACK rate: <0.5% of total ACKs
  - Zero-window events: <0.01% of total duration
  - Connection establishment: <10ms (99th percentile)
  - TCP RTT: stable within 20% of baseline
  - Out-of-order packets: <0.01% of total

Unhealthy indicators:
  - Retransmission rate: >1% → congestion or packet corruption
  - Duplicate ACK rate: >3% → significant packet loss
  - Zero-window events >1% → application bottleneck
  - Connection establishment: >100ms → SYN backlog or firewall
  - RTT spikes: >200ms → bufferbloat or route flapping
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **tcpdump fluency** | Constructs precise filters, uses ring buffers, snaplen for production |
| **Flag reading** | Reads TCP flags from hex, understands flag combinations |
| **Issue diagnosis** | Maps retransmissions/dup ACKs/zero-window to specific root causes |
| **Wireshark analysis** | Uses advanced stats (io,stat, expert info) and knows TShark commands |

---


