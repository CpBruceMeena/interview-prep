# 🗄️ Chess Game — Database Schema & Relationships

> **Database:** PostgreSQL 16 + Redis 7  
> **Purpose:** Online chess platform — game state, player profiles, matchmaking, tournaments, analytics  
> **Scale:** 1M+ users, 100K concurrent games, 500K games/day  
> **Tables:** 12 tables + 2 partitioned tables

---

## 📊 Entity Relationship Diagram (Textual)

```
┌──────────────┐     ┌───────────────┐     ┌───────────────┐
│    users     │1───N│   user_stats  │     │  game_sessions│
└──────┬───────┘     └───────────────┘     └───────┬───────┘
       │                                           │
       │1                                          │1
       │                                           │
┌──────▼────────┐     ┌───────────────┐     ┌──────▼────────┐
│ user_ratings  │     │  game_        │     │  game_moves   │
│ (history)     │     │  sessions     │     │               │
└───────────────┘     └───────┬───────┘     └───────────────┘
                              │
                    ┌─────────▼──────────┐     ┌────────────────┐
                    │   tournament_      │     │  tournament_   │
                    │   registrations    │1───N│  rounds        │
                    └────────────────────┘     └───────┬────────┘
                                                        │1
                                                        │
                    ┌───────────────┐     ┌──────────────▼────┐
                    │  game_        │     │  tournament_      │
                    │  analysis     │     │  matches          │
                    └───────────────┘     └───────────────────┘

┌───────────────┐     ┌───────────────┐
│ user_         │     │  user_sessions│
│ friendships   │     │               │
└───────────────┘     └───────────────┘
```

---

## 🏛️ Complete DDL

```sql
-- ============================================================
-- Chess Game Platform - Production Database Schema
-- Database: PostgreSQL 16
-- Scale: 1M+ users, 100K concurrent games, 500K games/day
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------
-- 1. USERS
-- -----------------------------------------------------------
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    avatar_url TEXT,
    bio TEXT,
    country VARCHAR(100),
    language VARCHAR(10) DEFAULT 'en',
    is_verified BOOLEAN DEFAULT false,
    is_bot BOOLEAN DEFAULT false,                    -- Distinguish human vs AI players
    status VARCHAR(20) DEFAULT 'OFFLINE'
        CHECK (status IN ('ONLINE', 'IN_GAME', 'AWAY', 'OFFLINE', 'BANNED')),
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_status ON users(status) WHERE status != 'OFFLINE';
CREATE INDEX idx_users_last_seen ON users(last_seen_at DESC);
CREATE INDEX idx_users_country ON users(country);

-- -----------------------------------------------------------
-- 2. USER STATS (Performance metrics)
-- -----------------------------------------------------------
CREATE TABLE user_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE NOT NULL REFERENCES users(id),
    rating_rapid INT DEFAULT 1200,
    rating_blitz INT DEFAULT 1200,
    rating_classical INT DEFAULT 1200,
    rating_bullet INT DEFAULT 1200,
    peak_rating INT DEFAULT 1200,
    games_played INT DEFAULT 0,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    draws INT DEFAULT 0,
    win_streak INT DEFAULT 0,                        -- Current win streak
    longest_win_streak INT DEFAULT 0,
    total_time_played_seconds BIGINT DEFAULT 0,
    average_move_time_seconds DECIMAL(6,1),
    puzzles_solved INT DEFAULT 0,
    puzzle_rating INT DEFAULT 1200,
    last_rating_change INT DEFAULT 0,
    last_rating_change_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stats_rating_rapid ON user_stats(rating_rapid DESC);
CREATE INDEX idx_stats_rating_blitz ON user_stats(rating_blitz DESC);
CREATE INDEX idx_stats_games ON user_stats(games_played DESC);

-- -----------------------------------------------------------
-- 3. GAME SESSIONS (Core: 100M+ rows expected; defined before user_rating_history)
-- -----------------------------------------------------------
CREATE TABLE game_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    white_player_id UUID NOT NULL REFERENCES users(id),
    black_player_id UUID NOT NULL REFERENCES users(id),
    winner_id UUID REFERENCES users(id),              -- NULL for draws/unfinished
    result VARCHAR(20) DEFAULT 'IN_PROGRESS'
        CHECK (result IN (
            'IN_PROGRESS', 'WHITE_WIN', 'BLACK_WIN', 'DRAW',
            'STALEMATE', 'RESIGNED', 'TIME_OUT', 'ABORTED'
        )),
    termination_reason VARCHAR(50),                   -- 'CHECKMATE', 'RESIGNATION', 'TIMEOUT', etc.
    time_control VARCHAR(30) NOT NULL,                 -- '60+0', '180+2', '600+5', 'UNLIMITED'
    initial_time_seconds INT NOT NULL,                 -- Base time
    increment_seconds INT DEFAULT 0,                   -- Increment per move
    rated BOOLEAN DEFAULT true,

    -- Game state (compressed for storage)
    starting_fen VARCHAR(100) DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    final_fen VARCHAR(100),
    pgn TEXT,                                          -- Full game in PGN format
    move_count INT DEFAULT 0,

    -- Timing
    white_time_remaining_seconds INT,
    black_time_remaining_seconds INT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_seconds INT,                              -- Computed: ended_at - started_at

    -- Metadata
    eco_code VARCHAR(10),                              -- Encyclopedia of Chess Openings
    accuracy_white DECIMAL(5,2),                       -- 0-100% accuracy
    accuracy_black DECIMAL(5,2),
    is_rated BOOLEAN DEFAULT true,
    idempotency_key VARCHAR(64) UNIQUE,
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (started_at);

-- Monthly partitions for game_sessions
CREATE TABLE game_sessions_202401 PARTITION OF game_sessions
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE game_sessions_202402 PARTITION OF game_sessions
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE INDEX idx_games_white ON game_sessions(white_player_id);
CREATE INDEX idx_games_black ON game_sessions(black_player_id);
CREATE INDEX idx_games_status ON game_sessions(result) WHERE result = 'IN_PROGRESS';
CREATE INDEX idx_games_started ON game_sessions(started_at DESC);
CREATE INDEX idx_games_eco ON game_sessions(eco_code);
CREATE INDEX idx_games_players ON game_sessions(white_player_id, black_player_id, started_at DESC);
CREATE INDEX idx_games_idempotency ON game_sessions(idempotency_key);

-- -----------------------------------------------------------
-- 4. USER RATING HISTORY (Time-series for ELO tracking)
-- -----------------------------------------------------------
CREATE TABLE user_rating_history (
    id BIGSERIAL,
    user_id UUID NOT NULL REFERENCES users(id),
    game_id UUID NOT NULL REFERENCES game_sessions(id),
    rating_type VARCHAR(20) NOT NULL                  -- 'rapid', 'blitz', 'classical', 'bullet'
        CHECK (rating_type IN ('rapid', 'blitz', 'classical', 'bullet')),
    rating_before INT NOT NULL,
    rating_after INT NOT NULL,
    rating_change INT NOT NULL,
    opponent_id UUID REFERENCES users(id),
    result VARCHAR(10) NOT NULL                       -- 'win', 'loss', 'draw'
        CHECK (result IN ('win', 'loss', 'draw')),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, recorded_at, rating_type)
);

CREATE INDEX idx_rating_history_user ON user_rating_history(user_id, recorded_at DESC);
CREATE INDEX idx_rating_history_game ON user_rating_history(game_id);

-- -----------------------------------------------------------
-- 5. GAME MOVES (Billions of rows expected)
-- -----------------------------------------------------------
CREATE TABLE game_moves (
    id BIGSERIAL,
    game_id UUID NOT NULL REFERENCES game_sessions(id),
    move_number INT NOT NULL,                          -- 1-indexed half-move
    from_square VARCHAR(2) NOT NULL,                   -- e.g., 'e2'
    to_square VARCHAR(2) NOT NULL,                     -- e.g., 'e4'
    piece VARCHAR(2) NOT NULL,                         -- 'P', 'N', 'B', 'R', 'Q', 'K'
    captured_piece VARCHAR(2),                         -- NULL if no capture
    promotion_piece VARCHAR(2),                        -- NULL if no promotion
    is_castling BOOLEAN DEFAULT false,
    is_en_passant BOOLEAN DEFAULT false,
    is_check BOOLEAN DEFAULT false,
    is_checkmate BOOLEAN DEFAULT false,
    fen_before VARCHAR(100) NOT NULL,                  -- Board state before move
    fen_after VARCHAR(100) NOT NULL,                   -- Board state after move
    time_taken_seconds DECIMAL(5,1),                   -- Seconds player took for this move
    evaluation_cp INT,                                 -- Centipawn evaluation (engine)
    best_move VARCHAR(5),                              -- Engine's best move at this position
    annotations TEXT,                                   -- Commentary / analysis
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (game_id, move_number)
);

CREATE INDEX idx_moves_game ON game_moves(game_id, move_number);

-- -----------------------------------------------------------
-- 6. GAME ANALYSIS (Stockfish/Engine evaluations)
-- -----------------------------------------------------------
CREATE TABLE game_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id UUID UNIQUE NOT NULL REFERENCES game_sessions(id),
    engine_name VARCHAR(50) DEFAULT 'Stockfish_16',
    engine_depth INT DEFAULT 20,
    analysis_depth INT,                                -- Depth reached
    nodes_searched BIGINT,
    evaluation_cp INT,                                 -- Final evaluation in centipawns
    best_line TEXT,                                    -- Best continuation (moves)
    -- Blunder detection
    white_blunders INT DEFAULT 0,
    black_blunders INT DEFAULT 0,
    white_mistakes INT DEFAULT 0,
    black_mistakes INT DEFAULT 0,
    white_inaccuracies INT DEFAULT 0,
    black_inaccuracies INT DEFAULT 0,
    -- Accuracy scores
    white_accuracy DECIMAL(5,2),
    black_accuracy DECIMAL(5,2),
    -- JSON analysis per move
    move_analysis JSONB,                               -- [{move_number, evaluation, best, blunder}, ...]
    opening_name VARCHAR(255),
    opening_moves TEXT,
    status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'ANALYZING', 'COMPLETED', 'FAILED')),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_analysis_game ON game_analysis(game_id);
CREATE INDEX idx_analysis_status ON game_analysis(status) WHERE status = 'PENDING';

-- -----------------------------------------------------------
-- 7. TOURNAMENTS
-- -----------------------------------------------------------
CREATE TABLE tournaments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    tournament_type VARCHAR(30) NOT NULL
        CHECK (tournament_type IN (
            'SWISS', 'ROUND_ROBIN', 'KNOCKOUT', 'ARENA', 'MATCH'
        )),
    time_control VARCHAR(30) NOT NULL,
    rating_min INT DEFAULT 0,
    rating_max INT DEFAULT 9999,
    max_participants INT DEFAULT 64,
    current_participants INT DEFAULT 0,
    rounds INT DEFAULT 7,
    current_round INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'REGISTRATION'
        CHECK (status IN ('REGISTRATION', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ,
    prize_pool DECIMAL(12,2),
    sponsorship_info TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tournaments_status ON tournaments(status);
CREATE INDEX idx_tournaments_start ON tournaments(start_at);

-- -----------------------------------------------------------
-- 8. TOURNAMENT REGISTRATIONS
-- -----------------------------------------------------------
CREATE TABLE tournament_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id UUID NOT NULL REFERENCES tournaments(id),
    user_id UUID NOT NULL REFERENCES users(id),
    seed_rating INT NOT NULL,                          -- Rating at time of registration
    current_score DECIMAL(5,2) DEFAULT 0.00,          -- Tournament score
    current_rank INT,
    status VARCHAR(20) DEFAULT 'REGISTERED'
        CHECK (status IN ('REGISTERED', 'ACTIVE', 'ELIMINATED', 'WITHDREW', 'DISQUALIFIED')),
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tournament_id, user_id)
);

CREATE INDEX idx_tournament_reg ON tournament_registrations(tournament_id, current_rank);

-- -----------------------------------------------------------
-- 9. TOURNAMENT ROUNDS
-- -----------------------------------------------------------
CREATE TABLE tournament_rounds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id UUID NOT NULL REFERENCES tournaments(id),
    round_number INT NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PAIRING', 'IN_PROGRESS', 'COMPLETED')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE(tournament_id, round_number)
);

-- -----------------------------------------------------------
-- 10. TOURNAMENT MATCHES (bridge between tournaments and games)
-- -----------------------------------------------------------
CREATE TABLE tournament_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id UUID NOT NULL REFERENCES tournaments(id),
    round_id UUID NOT NULL REFERENCES tournament_rounds(id),
    game_id UUID REFERENCES game_sessions(id),
    player1_id UUID NOT NULL REFERENCES users(id),
    player2_id UUID NOT NULL REFERENCES users(id),
    player1_score DECIMAL(3,1) DEFAULT 0,              -- 0, 0.5, or 1
    player2_score DECIMAL(3,1) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'SCHEDULED'
        CHECK (status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'BYE', 'FORFEIT')),
    board_number INT,
    scheduled_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE(tournament_id, round_id, player1_id, player2_id)
);

CREATE INDEX idx_tournament_matches_round ON tournament_matches(round_id);
CREATE INDEX idx_tournament_matches_tournament ON tournament_matches(tournament_id);

-- -----------------------------------------------------------
-- 11. USER FRIENDSHIPS
-- -----------------------------------------------------------
CREATE TABLE user_friendships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id UUID NOT NULL REFERENCES users(id),
    addressee_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'ACCEPTED', 'BLOCKED', 'DECLINED')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(requester_id, addressee_id),
    CONSTRAINT no_self_friend CHECK (requester_id != addressee_id)
);

CREATE INDEX idx_friends_requester ON user_friendships(requester_id, status);
CREATE INDEX idx_friends_addressee ON user_friendships(addressee_id, status);

-- -----------------------------------------------------------
-- 12. USER SESSIONS (For WebSocket management)
-- -----------------------------------------------------------
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    session_token VARCHAR(255) UNIQUE NOT NULL,
    device_type VARCHAR(30),                           -- 'WEB', 'MOBILE', 'DESKTOP'
    device_name VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    ws_connection_id VARCHAR(100),                     -- WebSocket connection ID
    is_active BOOLEAN DEFAULT true,
    last_heartbeat TIMESTAMPTZ,
    logged_in_at TIMESTAMPTZ DEFAULT NOW(),
    logged_out_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_sessions_active ON user_sessions(user_id) WHERE is_active = true;
CREATE INDEX idx_sessions_ws ON user_sessions(ws_connection_id) WHERE ws_connection_id IS NOT NULL;

-- -----------------------------------------------------------
-- KEY QUERY EXAMPLES
-- -----------------------------------------------------------

-- 1. Find active games for a player (for reconnect)
SELECT gs.id, gs.white_player_id, gs.black_player_id,
       gs.starting_fen, gs.move_count, gs.time_control,
       gs.white_time_remaining_seconds, gs.black_time_remaining_seconds,
       u1.username AS white_name, u2.username AS black_name
FROM game_sessions gs
JOIN users u1 ON gs.white_player_id = u1.id
JOIN users u2 ON gs.black_player_id = u2.id
WHERE (gs.white_player_id = 'user-uuid' OR gs.black_player_id = 'user-uuid')
  AND gs.result = 'IN_PROGRESS'
ORDER BY gs.started_at DESC;

-- 2. Get game replay with all moves
SELECT gm.move_number, gm.from_square, gm.to_square,
       gm.piece, gm.captured_piece, gm.is_castling,
       gm.is_check, gm.is_checkmate,
       gm.fen_before, gm.fen_after,
       gm.time_taken_seconds, gm.evaluation_cp
FROM game_moves gm
WHERE gm.game_id = 'game-uuid'
ORDER BY gm.move_number;

-- 3. Leaderboard: top 50 rapid players
SELECT u.username, us.rating_rapid, us.games_played,
       us.wins, us.win_streak, us.peak_rating
FROM user_stats us
JOIN users u ON us.user_id = u.id
WHERE u.is_bot = false
ORDER BY us.rating_rapid DESC
LIMIT 50;

-- 4. Find opponent: users near matching rating who are online
SELECT u.id, u.username, us.rating_rapid
FROM users u
JOIN user_stats us ON us.user_id = u.id
WHERE u.status = 'ONLINE'
  AND u.is_bot = false
  AND u.id != 'current-user'
  AND us.rating_rapid BETWEEN 1150 AND 1250     -- ±50 of current rating
  AND NOT EXISTS (
      SELECT 1 FROM game_sessions gs
      WHERE (gs.white_player_id = u.id OR gs.black_player_id = u.id)
        AND gs.result = 'IN_PROGRESS'
  )
ORDER BY ABS(us.rating_rapid - 1200) ASC
LIMIT 10;

-- 5. Get player's opening statistics
SELECT gs.eco_code, COUNT(*) AS games_played,
       SUM(CASE WHEN gs.winner_id = 'user-uuid' THEN 1 ELSE 0 END) AS wins,
       COUNT(*) FILTER (WHERE gs.result = 'DRAW') AS draws,
       ROUND(AVG(gs.accuracy_white), 1) AS avg_accuracy
FROM game_sessions gs
WHERE gs.white_player_id = 'user-uuid'
  AND gs.eco_code IS NOT NULL
GROUP BY gs.eco_code
ORDER BY games_played DESC
LIMIT 10;

-- 6. Tournament standing with tie-breaks
SELECT tr.current_rank, u.username, tr.current_score,
       us.rating_rapid, tr.seed_rating
FROM tournament_registrations tr
JOIN users u ON tr.user_id = u.id
JOIN user_stats us ON us.user_id = u.id
WHERE tr.tournament_id = 'tournament-uuid'
ORDER BY tr.current_rank ASC;

-- 7. Detect engine-like play (anti-cheat heuristic)
SELECT u.id, u.username,
       AVG(gs.accuracy_white) AS avg_accuracy,
       AVG(gm.evaluation_cp) AS avg_eval_change,
       COUNT(*) AS games
FROM game_sessions gs
JOIN users u ON gs.white_player_id = u.id
JOIN game_moves gm ON gm.game_id = gs.id AND gm.piece != 'P'
WHERE gs.started_at >= CURRENT_DATE - 30
  AND u.is_bot = false
GROUP BY u.id, u.username
HAVING AVG(gs.accuracy_white) > 95 AND COUNT(*) > 20
ORDER BY avg_accuracy DESC;
```

---

## 🔑 Redis Schema (Real-Time Game State)

```ascii
# Redis is THE primary data store for active games.
# PostgreSQL is the source of truth for completed/persisted games.

# === Active Game State ===
game:{game_id}:state           → HASH
  white_player_id, black_player_id
  fen                          → Current board position (FEN string)
  turn                         → "white" or "black"
  status                       → "active", "check", "checkmate", etc.
  white_time_ms                → Remaining time in milliseconds
  black_time_ms                → Remaining time in milliseconds
  last_move_at                 → Unix timestamp of last move
  move_count                   → Total half-moves played
  TTL: 24h (or until game ends)

# === Move History (in-memory, flushed to PG periodically) ===
game:{game_id}:moves           → LIST
  Each element: JSON {from, to, piece, captured, time_taken, fen_before, fen_after}
  When game ends → flush entire list to game_moves table

# === WebSocket Connections ===
ws:user:{user_id}              → SET of ws_connection_ids (supports multi-device)
ws:game:{game_id}              → SET of user_ids currently watching this game

# === Matchmaking Queues ===
queue:rapid                    → ZSET (user_id → rating)
queue:blitz                    → ZSET (user_id → rating)
queue:bullet                   → ZSET (user_id → rating)
  # Matchmaking: ZRANGEBYSCORE queue:rapid (rating-range) (rating-range) LIMIT 0 2

# === Rate Limiting ===
ratelimit:user:{user_id}:moves_per_sec  → STRING (counter, TTL 1s)
ratelimit:user:{user_id}:games_per_min  → STRING (counter, TTL 60s)

# === Active Game Count (for scaling metrics) ===
active_games_count             → STRING (atomically INCR/DECR on game start/end)
connected_users_count          → STRING (updated via WebSocket connect/disconnect)
```

---

## 📐 Table Relationships Summary

| # | Table | Parent FK | Child References | Key Indexes |
|---|-------|-----------|-----------------|-------------|
| 1 | `users` | — | `user_stats(user_id)`, `user_rating_history(user_id)`, `game_sessions(white/black)`, `tournament_registrations(user_id)`, `user_friendships(requester/addressee)`, `user_sessions(user_id)` | username, email, status, last_seen |
| 2 | `user_stats` | `user_id → users` | — | rating_rapid DESC, games DESC |
| 3 | `game_sessions` | `white_player_id → users`, `black_player_id → users`, `winner_id → users` | `game_moves(game_id)`, `game_analysis(game_id)`, `tournament_matches(game_id)`, `user_rating_history(game_id)` | white, black, active(filter), started DESC |
| 4 | `user_rating_history` | `user_id → users`, `game_id → game_sessions`, `opponent_id → users` | — | (user, recorded_at DESC) |
| 5 | `game_moves` | `game_id → game_sessions` | — | (game_id, move_number) PK |
| 6 | `game_analysis` | `game_id → game_sessions` | — | game_id UNIQUE, pending(filter) |
| 7 | `tournaments` | `created_by → users` | `tournament_registrations(tournament_id)`, `tournament_rounds(tournament_id)`, `tournament_matches(tournament_id)` | status, start_at |
| 8 | `tournament_registrations` | `tournament_id → tournaments`, `user_id → users` | — | (tournament, rank) |
| 9 | `tournament_rounds` | `tournament_id → tournaments` | `tournament_matches(round_id)` | (tournament, round_number) UNIQUE |
| 10 | `tournament_matches` | `tournament_id → tournaments`, `round_id → tournament_rounds`, `game_id → game_sessions`, `player1/2_id → users` | — | round, tournament |
| 11 | `user_friendships` | `requester_id → users`, `addressee_id → users` | — | (requester, status), (addressee, status) |
| 12 | `user_sessions` | `user_id → users` | — | user, active(filter), ws_connection |

---

## ⚡ Concurrency & Consistency at Scale

| Concern | Solution |
|---------|----------|
| **Game state consistency** | Redis primary for active games → async flush to PG. If Redis node fails, reconstruct from PG (`game_moves` table) + last known FEN. |
| **Race condition: double move** | Redis atomic ops (WATCH/MULTI/EXEC). Each move: verify turn, apply move, update FEN, switch turn — all in one transaction. |
| **Race condition: simultaneous game start** | Redis `SETNX` for game lock. Only one matchmaking worker wins. Loser picks next available opponent. |
| **Game recovery on crash** | Active game state replicated to PG every N moves (checkpoint). On crash → load last checkpoint, replay from game_moves. |
| **ELO rating update** | Idempotent: check if rating already updated for this game in `user_rating_history` before applying. `UNIQUE(user_id, game_id, rating_type)` prevents double-counting. |
| **Read-after-write consistency** | Session stickiness: same player always routed to same game-server pod (hash by game_id). Redis local read replicas. |

---

## 📊 Data Volume Estimates (at 100K concurrent games / 1M users)

| Table | Row Count | Growth Rate | Storage |
|-------|-----------|-------------|---------|
| `users` | 1M | +10K/month | ~500 MB |
| `user_stats` | 1M | +10K/month | ~200 MB |
| `game_sessions` | 10M | +500K/month | ~10 GB |
| `user_rating_history` | 50M | +3M/month | ~4 GB |
| `game_moves` | 500M | +25M/month | ~50 GB |
| `game_analysis` | 5M | +250K/month | ~20 GB |
| `tournament*` | 100K | +5K/month | ~500 MB |

**Total estimated storage after 12 months:** ~100 GB (with partitioning + compression)
