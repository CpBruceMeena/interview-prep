# 🧠 Task Queue / Worker Pool — Thought Process

## 📊 Class Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/go-taskqueue-class-diagram.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Class Diagram — Task Queue: CSP + Worker Pool + Pipeline — Priority Queue, Scheduling, Dead Letter. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## Problem Breakdown

### Step 1: Core Components
- **Task:** Unit of work with type, priority, retry config
- **Queue:** Ordered by priority, then FIFO
- **Worker Pool:** N goroutines processing tasks concurrently
- **Handler:** Processes a specific task type

### Step 2: Priority Ordering
- Need to process high-priority tasks before low-priority
- Min-heap for O(log n) push/pop
- Same priority = FIFO (by creation time)

### Step 3: Retry with Backoff
- Tasks can fail transiently → need retry
- Exponential backoff to avoid thundering herd
- Configurable max retries before permanent failure

### Step 4: Graceful Shutdown
- Workers must finish in-flight tasks
- Context-based cancellation
- Clean state on shutdown

## Key Decisions

| Decision | Why |
|----------|-----|
| Min-heap for priority | O(log n) efficient, standard pattern |
| Exponential backoff | Industry standard for retry |
| Handler registry | SRP: each handler owns one task type |
| Context cancellation | Go-native graceful shutdown |
| Channel-based results | Type-safe, goroutine-safe, composable |
