# 🧠 Elevator System — Thought Process

## Problem Breakdown

### Step 1: Core Entities
- **Elevator:** State machine with position, direction, door state, load
- **Request:** Floor + direction + timestamp
- **Controller:** Manages dispatch and fleet coordination

### Step 2: State Machine Design
The elevator has clear states (MOVING, STOPPED, DOOR_OPEN, etc.) → State pattern or enum-based FSM

### Step 3: Dispatching Strategy
Different buildings need different algorithms → Strategy pattern for interchangeable dispatch

### Step 4: Observer for Monitoring
Display boards, logging, and emergency systems need real-time updates → Observer pattern

### Step 5: Concurrency
- Multiple floor panels can request simultaneously → Thread-safe request queue
- Each elevator runs independently → ScheduledExecutorService per elevator
- Stops tracking → ConcurrentSkipListSet for sorted, concurrent access

## Key Decisions

| Decision | Why |
|----------|-----|
| Floor-by-floor traversal | Smoother ride, simpler prioritization |
| SCAN algorithm | Industry standard, prevents starvation |
| CopyOnWriteArrayList for observers | Thread-safe, iteration without locks |
| Immutable Request objects | Safe for queue, traceable via UUID |
