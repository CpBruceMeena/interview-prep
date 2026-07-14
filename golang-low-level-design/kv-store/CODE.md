# In-Memory KV Store — Go Implementation

> Go implementation of an in-memory Key-Value store with TTL, eviction policies, and snapshots.

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|---------------|---------|
| `KVStore` | Core data store with get/set/delete | Facade |
| `EvictionPolicy` | Defines eviction strategy | Strategy |
| `LRUPolicy` | Evicts least recently used | LRU via container/list |
| `LFUPolicy` | Evicts least frequently used | LFU via min-heap |
| `expiryHeap` | Efficient TTL expiration | Min-Heap |

### Concurrent Operations

```go
type KVStore struct {
    mu       sync.RWMutex     // Read-Write lock
    data     map[string]*Value
    eviction EvictionPolicy   // Pluggable strategy
    maxSize  int64
}

func (s *KVStore) Get(key string) (interface{}, bool) {
    s.mu.RLock()              // Concurrent reads!
    defer s.mu.RUnlock()

    val, ok := s.data[key]
    if !ok { return nil, false }
    if val.IsExpired() { return nil, false }

    val.Touch()
    s.eviction.Record(key)    // Update LRU/LFU tracking
    return val.Data, true
}
```

### TTL Expiration with Min-Heap

```go
type expiryEntry struct {
    key       string
    expiresAt time.Time
    index     int
}

func (s *KVStore) ExpireExpired() int64 {
    now := time.Now()
    var expired int64

    for s.ttlHeap.Len() > 0 {
        entry := s.ttlHeap[0]     // Peek earliest expiry
        if entry.expiresAt.After(now) {
            break                   // No more expired items
        }
        heap.Pop(&s.ttlHeap)
        // Remove from data map...
    }
    return expired
}
```

## ▶️ How to Run

```bash
cd golang-low-level-design/kv-store
go run kv_store.go
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | EvictionPolicy | LRU / LFU / TTL interchangeable |
| **Singleton** | KVStore | Single store instance |
| **Facade** | KVStore | Unified API over data + eviction + TTL |
| **Min-Heap** | expiryHeap | O(log n) TTL expiration |
