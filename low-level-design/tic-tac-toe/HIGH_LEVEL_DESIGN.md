# 🏗️ Tic-Tac-Toe — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Game architecture, AI, real-time, matchmaking

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online Tic-Tac-Toe platform supporting PvP, AI, tournament, and N×N board variants.

**Scale:** 500K MAU, 5K concurrent games, 100K games/day.

**Users:** Casual players, Competitive players, Spectators

**Use Cases:** Quick match, AI practice (3 levels), Tournament mode, N×N board (4×4, 5×5)

**Constraints:** <50ms move latency, AI responds <1s, 99.9% uptime

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Web/Mobile App
      │
┌─────▼─────┐
│ API Gateway│── Rate Limiting ── Auth (JWT)
└─────┬─────┘
      │
┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
│ Matchmaking│  │ Game Engine│  │ AI Service │
│ (Go)       │  │ (Python)   │  │ (Python)   │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
      └───────────────┼───────────────┘
                      │
              ┌───────▼───────┐
              │    Redis       │
              │ (Game state,   │
              │  sessions, Q)  │
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │  PostgreSQL│  │ (Users, games)│
  └───────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/tic-tac-toe-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Tic-Tac-Toe Sequence — Player → Move → Win Check → Board Update → Turn Switch. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS

### Game Engine (Python)
- Board state w/ 3×3 to N×N support
- Win detection: O(N²) scan for K-in-a-row
- Undo/redo w/ Command Pattern
- Move validation chain

**🔴 Interview Question:** *"How does your engine handle N×N boards efficiently?"*

**✅ Answer:** Use a 1D array `board[N*N]` instead of 2D. Win check scans rows (stride=1), columns (stride=N), diagonals (stride=N±1). For K-in-a-row, sliding window per direction. O(N²) time, O(N²) memory.

---

### AI Service (Python)
- **Easy:** Random legal move — O(N²)
- **Medium:** Minimax depth 3
- **Hard:** Minimax + alpha-beta, depth 9 (optimal for 3×3)

**🔴 Interview Question:** *"How do you scale AI for 5×5 boards?"*

**✅ Answer:** Full minimax is infeasible for 5×5 (25! permutations). Use:
1. **Monte Carlo Tree Search (MCTS):** Simulate random playouts, select best node
2. **Heuristic eval:** Score based on lines controlled, center control
3. **Time-bounded search:** Return best move found within 2 seconds
4. **Opening book:** Pre-compute best responses to common first moves

---

### Matchmaking (Go)
- ELO-based pairing
- Redis Sorted Set per skill bracket
- Search expands ±100 every 5 seconds

---

## 4. TRADE-OFFS

| Decision | Option A | Option B | Choice |
|----------|----------|----------|--------|
| Game state | Server-authoritative | Client-authoritative | Server — prevents cheating |
| AI compute | Server-side | Client-side (WebAssembly) | Server for complex, WASM for easy |
| Real-time | WebSocket | Polling REST | WebSocket — <20ms latency |
| Board store | In-memory (Redis) | Database only | Redis — fast reads, PG for persistence |

---

## 5. SCALABILITY

**Bottleneck:** AI Service (CPU-bound for deep searches)

**Solution:** Queue AI requests to worker pool. GPU instances for ML-based AI. Cache common positions in Redis.

**Availability:** 99.9%. Stateless game services. Redis replication + failover.

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Game Engine (5 pods) | $1,000 |
| AI Service (GPU) | $800 |
| Redis + PostgreSQL | $600 |
| **Total** | **$2,400** |
