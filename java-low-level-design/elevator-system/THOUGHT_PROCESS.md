# 🧠 Elevator System — Thought Process

## 📊 Class Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/java-elevator-class-diagram.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Class Diagram — Elevator System: SOLID + State + Strategy + Observer Patterns — 40 floors, 6 elevators. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

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
