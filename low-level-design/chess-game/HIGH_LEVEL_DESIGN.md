# 🏗️ Chess Game — High-Level Design

> **Interviewer:** Principal Software Engineer  
> **Target Level:** Senior/Staff Engineer  
> **Focus:** Game engine architecture, real-time multiplayer, AI integration

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online chess platform supporting real-time multiplayer, AI opponents, game analysis, and tournament management.

**Scale:** 1M monthly active users, 10K concurrent games, 50K games/day.

**Users:** Players (casual/competitive), Spectators, Tournament organizers

**Use Cases:**
- Play chess vs human (matchmaking)
- Play chess vs AI (3 difficulty levels)
- Analyze completed games
- Watch live tournaments
- Save and review game history

**Constraints:** <100ms move validation, <2s AI move generation (easy), real-time state sync, 99.9% uptime for ranked play

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌──────────────────────────────────────────────────────┐
│                  Client Applications                   │
│  Web (React)  │  Mobile (React Native) │  Desktop     │
└──────────────────────────┬───────────────────────────┘
                           │ HTTPS / WebSocket
┌──────────────────────────▼───────────────────────────┐
│                   API Gateway                         │
│           (Kong / AWS API Gateway)                    │
│  - Authentication (OAuth2)                           │
│  - Rate Limiting (100 req/s per user)                 │
│  - WebSocket upgrade for live games                  │
└──────────────────────────┬───────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  Matchmaking   │ │   Game        │ │   Analysis    │
│  Service       │ │   Engine      │ │   Service     │
│  (Go)          │ │   (Python)    │ │   (Python)    │
└─────────┬──────┘ └───────┬───────┘ └───────┬───────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │          Kafka / Redis PubSub    │
          │  (Game events, notificatons)     │
          └────────────────┬────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  PostgreSQL    │ │   Redis       │ │   S3/Blob    │
│  - Users       │ │  - Game state │ │  - Game      │
│  - Game history│ │  - Sessions   │ │    replays   │
│  - Ratings     │ │  - Match queue│ │  - Analysis  │
└────────────────┘ └───────────────┘ └───────────────┘
```

---

## 3. COMPONENT BREAKDOWN

### 3.1 Game Engine Service
- **Technology:** Python (Python for chess logic; Go for real-time if needed)
- **Responsibilities:**
  - Board state management (bitboard representation)
  - Move validation (6 piece types, special rules)
  - Check/checkmate/stalemate detection
  - AI move generation (Minimax + Alpha-Beta pruning)
  - Game timer management

**🔴 Interview Question:** *"How would you architect the move validation to be fast enough for 10K concurrent games?"*

**✅ Answer:** 
1. **Bitboard representation:** Represent board as 12 × uint64 (one per piece type per color). Move generation becomes bitwise operations — 50M+ positions/second per core.
2. **Pre-computed attack tables:** Knight and king moves are lookup tables (O(1)).
3. **Magic bitboards:** Sliding pieces (bishop, rook, queen) use magic hash to pre-compute attack sets.
4. **Validation pipeline:** Move pattern check → legality check (king safety) → en passant/castling checks.
5. **Stateless design:** Each game state is self-contained (no shared state between games). Scale horizontally by adding more engine pods.

---

### 3.2 Matchmaking Service
- **Technology:** Go (high concurrency)
- **Responsibilities:**
  - ELO-based opponent matching
  - Rating range: ±200 for fast matches, expanding over time
  - Priority to same rating range first
  - Handle casual vs ranked queues separately

**🔴 Interview Question:** *"How does your matchmaking handle 10K users queueing simultaneously?"*

**✅ Answer:** 
1. Redis sorted sets per rating bracket (e.g., 0-1000, 1000-1200, ...)
2. Each bracket key: `matchmaking:{rating_bracket}`
3. Users enter with score = ELO rating
4. Background worker polls each bracket: `ZRANGEBYSCORE` to find opponents within range
5. Match found → atomically remove both users, create game room
6. Expand search range every 5 seconds if no match found

---

### 3.3 Analysis Service
- **Technology:** Python + Stockfish integration
- **Responsibilities:**
  - Position evaluation (centipawns, best move)
  - Game annotation
  - Blunder detection
  - Opening book lookup

---

### 3.4 Data Layer

**PostgreSQL Schema:**
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY, username TEXT UNIQUE, elo_rating INT DEFAULT 1200
);
CREATE TABLE games (
    id UUID PRIMARY KEY, white_id UUID, black_id UUID,
    pgn TEXT, result TEXT, played_at TIMESTAMP DEFAULT NOW(),
    time_control TEXT
);
CREATE TABLE moves (
    id BIGSERIAL, game_id UUID REFERENCES games(id),
    move_number INT, from_sq TEXT, to_sq TEXT, piece TEXT,
    time_seconds INT
);
```

**Redis:**
- Active game state: `HGETALL game:{id}:state`
- User session: `GET session:{token}`
- Matchmaking queue: `ZADD matchmaking:1500 {user_id} {rating}`

**S3 Storage:** Game PGN exports, analysis reports, user profile images

---

### 3.5 Monitoring & Observability

| Metric | Tool | Alert |
|--------|------|-------|
| Move validation latency | Prometheus | p99 > 50ms |
| AI move generation | Prometheus | > 5s (easy mode) |
| Matchmaking time | Grafana | > 30s avg |
| Concurrent games | CloudWatch | > 80% capacity |
| WebSocket connections | Grafana | > 10K per pod |

---

## 4. TRADE-OFFS ANALYSIS

### Trade-off 1: Server-side vs Client-side Game Logic

| Aspect | Server-side | Client-side |
|--------|-------------|-------------|
| Trust | ✅ No cheating possible | ❌ Client can modify state |
| Latency | ❌ 50-100ms per move | ✅ <5ms |
| Cost | ❌ Server compute | ✅ Free |
| Complexity | More infrastructure | Simpler |

**Decision:** Server-authoritative for ranked games. Client-side for AI games (faster UX).

### Trade-off 2: Bitboard vs Array Representation

| Aspect | Bitboard (uint64) | 2D Array |
|--------|------------------|----------|
| Speed | ✅ 50M+ positions/s | ❌ ~500K positions/s |
| Memory | ✅ 768 bits total | ❌ 64+ bytes |
| Complexity | ❌ Harder to debug | ✅ Simple |
| Move generation | ✅ Bitwise ops | ❌ Loops |

**Decision:** Bitboard for core engine, array wrapper for human-readable debugging.

---

## 5. SCALABILITY & RELIABILITY

**Availability:** 99.95%

**Game State Recovery:** Redis persistence (AOF + RDB). If Redis fails, reconstruct from PostgreSQL game log.

**Disaster Recovery:** Cross-region replica of PostgreSQL. Active games lost on region failover → players reconnect to new session.

**Scaling:**
- Game engine pods: Horizontal based on CPU (auto-scale at 70%)
- WebSocket connections: Scale with game count
- AI computation: GPU instances for deep learning AI; spot instances for cost savings

---

## 6. COST BREAKDOWN (Monthly)

| Component | Cost | Notes |
|-----------|------|-------|
| Game Engine (20 pods) | $4,000 | c5.xlarge, auto-scaling |
| Matchmaking (2 pods) | $400 | Small instances |
| PostgreSQL RDS | $1,200 | Multi-AZ, db.r6g.large |
| Redis Cluster | $600 | cache.r6g.large |
| AI computation | $800 | Spot GPU instances |
| CDN + Bandwidth | $500 | Static assets |
| **Total** | **$7,500** | |

---

## 7. IMPLEMENTATION ROADMAP

**Phase 1 (Month 1-2):** Core game engine with all rules. AI (random + minimax depth 3). Local multiplayer only.

**Phase 2 (Month 3-4):** Online multiplayer with WebSocket. Basic matchmaking (ELO-based). Game history.

**Phase 3 (Month 5-6):** AI depth 6 with alpha-beta. Game analysis (Stockfish integration).

**Phase 4 (Month 7-8):** Tournaments. Spectator mode. Opening book. Advanced statistics.
