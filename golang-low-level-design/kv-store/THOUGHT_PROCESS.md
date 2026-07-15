# 🧠 In-Memory KV Store — Thought Process

## 📊 Class Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/go-kvstore-class-diagram.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Class Diagram — KV Store: CSP + Strategy Pattern + Generics — TTL, Eviction, Watch, CAS, Namespaces. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## Problem Breakdown

### Step 1: Core Data Structure
- Map is O(1) for get/set/delete
- Need concurrency safety → sync.RWMutex
- Need size tracking for eviction

### Step 2: Eviction Policies
- Different use cases need different strategies
- Strategy pattern for pluggable policies
- LRU: container/list for O(1) reordering
- LFU: min-heap for O(log n) frequency tracking

### Step 3: TTL Management
- Items can have optional expiry time
- Need efficient cleanup → min-heap by expiry time
- Periodic cleanup goroutine

### Step 4: Persistence
- Snapshot all data to JSON file
- Restore on startup
- Not production-grade but demonstrates the concept

## Key Decisions

| Decision | Why |
|----------|-----|
| RWMutex for concurrency | Read-optimized, typical of cache workloads |
| Pluggable eviction | Different use cases need different strategies |
| Min-heap for TTL | O(log n) for most operations, O(1) to find next expiry |
| Bytes-based size limit | More accurate than item count |
| Background TTL cleanup | Non-blocking expiration of expired items |
