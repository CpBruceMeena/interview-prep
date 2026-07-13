# 🏗️ Snakes and Ladders — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Real-time multiplayer, game state sync, dynamic board gen

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online multiplayer Snakes & Ladders platform with customizable boards, power-ups, and tournaments.

**Scale:** 100K DAU, 10K concurrent games, 4 players/game avg

**Users:** Casual players, Competitive players

**Use Cases:** Quick play (random match), Private room (invite friends), AI practice, Tournaments

**Constraints:** <100ms dice roll sync, 99.5% uptime, real-time state for all players

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Mobile/Web Client (React/PWA)
      │ WebSocket
┌─────▼──────┐
│ API Gateway │── Auth ── Rate Limit ── WSS Upgrade
└─────┬──────┘
      │
┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼────────┐
│ Lobby      │  │ Game       │  │ Board Gen    │
│ Service    │  │ Engine     │  │ Service      │
│ (Go)       │  │ (Python)   │  │ (Python)     │
└─────┬──────┘  └─────┬──────┘  └─────┬────────┘
      │               │               │
      └───────────────┼───────────────┘
                      │
              ┌───────▼───────┐
              │    Redis       │
              │ (Game state,   │
              │  chat, queue)  │
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │  PostgreSQL   │
              │(Users, games,│  │ leaderboards) │
  └───────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/snakes-and-ladders-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Snakes & Ladders Sequence — Roll → Move → Check → Snake/Ladder → Turn End. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Game Engine (Python)
- Turn management (order, dice rolls, extra turns)
- Snake/ladder chaining (multi-hop)
- Win condition (exact roll or bounce-back)

**🔴 Interview Question:** *"How do you ensure fair dice for all players?"*

**✅ Answer:**
1. **Server-authoritative dice:** Dice rolls happen server-side, not client-side. Clients send "roll intention," server computes result.
2. **Seeded PRNG:** Use a server-side seed that's cryptographically random. Players can't predict rolls.
3. **Cheat detection:** Track roll statistics per player — deviation beyond 3σ triggers investigation.
4. **Spectator verification:** All rolls logged and verifiable post-game.

---

### Lobby Service (Go)
- Matchmaking (ELO/friends/random)
- Private room creation
- Chat system

**🔴 Interview Question:** *"How do you handle disconnect/reconnect in multiplayer?"*

**✅ Answer:**
1. Player disconnected → server holds game state in Redis (TTL: 5 minutes)
2. Bot takes over: Simple AI makes random moves
3. Reconnect: Client sends last known game ID → server replays state
4. After 5 min → game forfeited, other players win

---

### Board Gen Service (Python)
- Validates no cycles (snake→ladder loops)
- Ensures solvability (expected moves < threshold)
- Difficulty tuning (more snakes = harder)

**🔴 Interview Question:** *"How do you generate fair boards programmatically?"*

**✅ Answer:**
1. Place ladders first (bottom cells → higher cells, distance 10-30)
2. Place snakes on remaining cells (head above tail, distance 5-20)
3. Validate: Run Monte Carlo simulation (10K random games, compute average moves)
4. If average moves outside target range (50-200), regenerate
5. Difficulty levels: Easy (few snakes), Medium (balanced), Hard (many snakes)

---

## 4. DATA MODEL

```sql
CREATE TABLE games (
    id UUID, board_size INT, status TEXT,
    created_at TIMESTAMP, finished_at TIMESTAMP
);
CREATE TABLE players (
    id UUID, game_id UUID, user_id UUID, position INT DEFAULT 0,
    finish_order INT, color TEXT
);
CREATE TABLE moves (
    id BIGSERIAL, game_id UUID, player_id UUID,
    dice_value INT, from_pos INT, to_pos INT, timestamp TIMESTAMP
);
CREATE TABLE boards (
    id UUID, game_id UUID, cell INT, type TEXT, destination INT
);
```

---

## 5. SCALABILITY

**Bottleneck:** Game Engine — per-game state management when 10K concurrent games

**Solution:** Redis stores all active game states. Game engine pods stateless — each pod handles N games. Redis pub/sub broadcasts moves to all players in a game room.

**Failure mode:** Redis failure → games in progress lost. Mitigation: Redis replication + periodic snapshots to PostgreSQL every 5 seconds.

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Game Engine (10 pods) | $2,000 |
| Lobby + Matchmaking | $500 |
| Redis + PostgreSQL | $800 |
| Bandwidth (WSS) | $400 |
| **Total** | **$3,700** |
