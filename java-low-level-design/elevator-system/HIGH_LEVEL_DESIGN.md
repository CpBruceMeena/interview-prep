# 🏗️ Elevator System — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Multi-car dispatching, state management, concurrency, resilience

---

## 1. SYSTEM OVERVIEW

**Purpose:** Control a bank of elevators in a multi-floor building with optimal dispatching.

**Scale:** 4-8 elevators, 50 floors, 100K trips/day. Sub-second response for car assignment.

**Domain:** Building automation / IoT with real-time monitoring and failover.

---

## 2. SYSTEM ARCHITECTURE

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Floor Panel  │    │ Cabin Panel  │    │ Admin Console│
│ (UP/DOWN)    │    │ (Floor Sel)  │    │ (Monitoring) │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
              ┌────────────▼────────────┐
              │   Elevator Controller   │
              │  (Dispatching Strategy) │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
  │  Elevator 1 │  │  Elevator 2 │  │  Elevator N │
  │ (State M/C) │  │ (State M/C) │  │ (State M/C) │
  └─────────────┘  └─────────────┘  └─────────────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
              ┌────────────▼────────────┐
              │   Monitoring Service    │
              │  (Metrics + Alerts)     │
              └─────────────────────────┘
```

## 3. ELEVATOR STATE MACHINE

```
                  ┌──────────┐
                  │  IDLE    │
                  └────┬─────┘
                       │ request received
                       ▼
              ┌──────────────────┐
         ┌────│    MOVING        │◄────────────┐
         │    │ (UP / DOWN)      │              │
         │    └────────┬─────────┘              │
         │             │ reached destination    │
         │             ▼                        │
         │    ┌──────────────────┐              │
         │    │    STOPPED       │              │
         │    └────────┬─────────┘              │
         │             │                        │
         │             ▼                        │
         │    ┌──────────────────┐              │
         │    │   DOOR_OPENING  │              │
         │    └────────┬─────────┘              │
         │             │ 1 sec                  │
         │             ▼                        │
         │    ┌──────────────────┐   more       │
         │    │   DOOR_OPEN      │──stops───────┘
         │    └────────┬─────────┘
         │             │ 2 sec
         │             ▼
         │    ┌──────────────────┐
         │    │  DOOR_CLOSING   │
         │    └────────┬─────────┘
         │             │ 1 sec
         │             ▼
         │         MOVING ──────────────────────┘
         │         (if more stops)
         │             │ no more stops
         │             ▼
         └─────────> IDLE
```

## 4. DISPATCHING ALGORITHMS

| Algorithm | Strategy | Best For | Trade-offs |
|-----------|----------|----------|------------|
| **Nearest Car** | Closest available elevator | Low traffic | Causes bunching under high load |
| **SCAN** | Continue direction, collect requests | Medium traffic | Starves edge floors |
| **Load Balancing** | Fewest pending stops | High traffic | More computation, better distribution |

## 5. CONCURRENCY & EDGE CASES

| Scenario | Approach |
|----------|----------|
| Multiple floor requests | ConcurrentSkipListSet for sorted, thread-safe stops |
| Overload detection | Capacity threshold + notify dispatch another car |
| Emergency stop | Immediate stop + MAINTENANCE mode |
| Power failure | Auto-stop at nearest floor + door open |
| Re-levelling | Fine-tune floor alignment during stop |

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale | Alternative |
|----------|--------|-----------|-------------|
| Dispatching | Nearest Car | Simple, low latency | SCAN (better throughput) |
| Floor traversal | Floor-by-floor | Smooth ride, simpler | Express skip (faster but complex) |
| State storage | In-memory | Sub-millisecond | Database (persistent but slower) |
| Communication | Polling | Simple, reliable | Pub/Sub (event-driven but complex) |
