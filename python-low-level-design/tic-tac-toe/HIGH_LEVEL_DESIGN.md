# 🏗️ Tic-Tac-Toe — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Game architecture, AI, real-time, matchmaking

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online Tic-Tac-Toe platform supporting PvP, AI, tournament, and N×N board variants.

**Scale:** 500K MAU, 5K concurrent games, 100K games/day.

**Users:** Casual players, Competitive players, Spectators

**Use Cases:** Quick match, AI practice (3 levels), Tournament mode, N×N board (4×4, 5×5)

**Constraints:** <50ms move latency, AI responds <1s, 99.9% uptime

**Back-of-envelope:** 100K games/day × ~8 moves ≈ 0.8M moves/day ≈ 10 moves/s average; with a 10× peak factor ~100 moves/s. 5K concurrent games × a few hundred bytes of state ≈ a few MB. Every number here fits on one small server; the design questions are about **correctness (turn order, idempotent retries), reconnects, and not losing a finished game's result**, not throughput. A staff answer says so and keeps the architecture small.

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
              │  PostgreSQL   │
              │ (users, games)│
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
- Win detection: O(1) line sums when K = N; O(K) walk through the last move when K < N
- Undo/redo w/ Command Pattern
- Move validation chain

**🔴 Interview Question:** *"How does your engine handle N×N boards efficiently?"*

**✅ Answer:** Only lines through the last move can become a win, so never rescan the board. For K = N keep running sums per row/column/diagonal (+1 X, −1 O) and test `abs(sum) == N`: O(1) per move. For K < N walk the four directions from the last move: O(K). Storage is O(N²) for the grid either way; a 1D array vs 2D is a constant-factor detail.

---

### AI Service (Python)
- **Easy:** Random legal move — O(N²)
- **Medium:** Minimax depth 3
- **Hard:** Full minimax with a transposition table (optimal for 3×3). Better still: 3×3 has only 5,478 legal positions, so precompute the best move for every position once and ship the table (a few tens of KB). "AI" for 3×3 becomes a hash lookup, and the AI service disappears for the classic board.

**🔴 Interview Question:** *"How do you scale AI for 5×5 boards?"*

**✅ Answer:** Exhaustive search is infeasible for 5×5 (state space bounded by 3^25 ≈ 8.5 × 10¹¹). Use:
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

**Solution:** For 3×3, a precomputed move table removes the bottleneck entirely. For N×N, run time-boxed searches in a CPU worker pool behind a queue, with a per-request deadline so a slow search returns its best-so-far move. GPUs are not useful here; these are branchy tree searches, not tensor math.

**Availability:** 99.9%. Game servers hold no state that isn't in Redis/PostgreSQL. Redis replication + failover.

---

## 6. CORRECTNESS, IDEMPOTENCY & FAILURE MODES

| Concern | Design |
|---------|--------|
| Two moves for the same turn (double tap, two devices) | One writer per game: the server applies `make_move` under a per-game lock (in-process) or a Redis Lua script that checks `turn` and `move_number` atomically |
| Client retries after a timeout | Client sends `move_number` it expects to create. If the server already has that move from the same player, return the current state (idempotent); if it's a different move, reject as stale |
| Game server crash mid-game | State lives in Redis (`game:{id}` hash: board string, turn, move_number, version). Any server can resume. Moves are also appended to PostgreSQL so a Redis failover can't lose a result |
| Result recorded twice (event redelivered) | `UNIQUE(game_id)` on the results table; rating updates keyed by `game_id` |
| Player disconnects | Hold the seat for N seconds; then forfeit by timeout. The timeout and a late move go through the same per-game writer, so exactly one wins |
| Redis down | New games can't start; in-flight games pause. Finished results are already in PostgreSQL |

**Consistency choice:** strong consistency *within a game* (single writer, ordered moves), eventual consistency for everything derived (leaderboards, stats, spectator views).

---

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| Game Engine (5 pods) | $1,000 |
| AI Service (CPU workers, N×N only) | $300 |
| Redis + PostgreSQL | $600 |
| **Total** | **$1,900** |
