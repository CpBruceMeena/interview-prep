# 🧠 In-Memory KV Store — Thought Process

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
