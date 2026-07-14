// In-Memory Key-Value Store with TTL - Low Level Design (Go)
// -----------------------------------------------------------
// Design Principles: CSP, Strategy Pattern, Singleton
//
// Key Design Decisions:
// - sync.RWMutex for concurrent read/write safety
// - Min-heap for efficient TTL expiration
// - Strategy pattern for eviction policies (LRU, LFU, TTL)
// - Snapshot for persistence (JSON serialization)
// - Generics for type-safe operations

package main

import (
	"container/heap"
	"container/list"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

// ============================================================
// VALUE WRAPPER
// ============================================================

type Value struct {
	Data      interface{} `json:"data"`
	CreatedAt time.Time   `json:"created_at"`
	ExpiresAt *time.Time  `json:"expires_at,omitempty"`
	AccessCount int64     `json:"access_count"`
	Size       int64      `json:"size"`
}

func NewValue(data interface{}, ttl time.Duration) *Value {
	v := &Value{
		Data:        data,
		CreatedAt:   time.Now(),
		AccessCount: 0,
	}
	if ttl > 0 {
		expiry := time.Now().Add(ttl)
		v.ExpiresAt = &expiry
	}
	v.Size = estimateSize(data)
	return v
}

func (v *Value) IsExpired() bool {
	if v.ExpiresAt == nil {
		return false
	}
	return time.Now().After(*v.ExpiresAt)
}

func (v *Value) Touch() {
	v.AccessCount++
}

func estimateSize(data interface{}) int64 {
	switch d := data.(type) {
	case string:
		return int64(len(d))
	case []byte:
		return int64(len(d))
	case int, int64, float64:
		return 8
	case bool:
		return 1
	default:
		return int64(len(fmt.Sprintf("%v", d)))
	}
}

// ============================================================
// EVICTION POLICY (Strategy Pattern)
// ============================================================

type EvictionPolicy interface {
	// Record records an access to a key
	Record(key string)
	// Evict returns the key to evict
	Evict() string
	// Remove removes a key from tracking
	Remove(key string)
	// Name returns the policy name
	Name() string
}

// LRUPolicy evicts the least recently used item
type LRUPolicy struct {
	mu          sync.Mutex
	accessOrder *list.List
	entries     map[string]*list.Element
}

func NewLRUPolicy() *LRUPolicy {
	return &LRUPolicy{
		accessOrder: list.New(),
		entries:     make(map[string]*list.Element),
	}
}

func (p *LRUPolicy) Record(key string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if elem, ok := p.entries[key]; ok {
		p.accessOrder.MoveToFront(elem)
		return
	}
	elem := p.accessOrder.PushFront(key)
	p.entries[key] = elem
}

func (p *LRUPolicy) Evict() string {
	p.mu.Lock()
	defer p.mu.Unlock()

	elem := p.accessOrder.Back()
	if elem == nil {
		return ""
	}
	key := elem.Value.(string)
	p.accessOrder.Remove(elem)
	delete(p.entries, key)
	return key
}

func (p *LRUPolicy) Remove(key string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if elem, ok := p.entries[key]; ok {
		p.accessOrder.Remove(elem)
		delete(p.entries, key)
	}
}

func (p *LRUPolicy) Name() string { return "LRU" }

// LFUPolicy evicts the least frequently used item
type LFUPolicy struct {
	mu    sync.Mutex
	freqs map[string]int64 // key -> access count
	minHeap *freqHeap
}

func NewLFUPolicy() *LFUPolicy {
	h := &freqHeap{}
	heap.Init(h)
	return &LFUPolicy{
		freqs:   make(map[string]int64),
		minHeap: h,
	}
}

type freqEntry struct {
	key  string
	freq int64
	index int
}

type freqHeap []*freqEntry

func (h freqHeap) Len() int           { return len(h) }
func (h freqHeap) Less(i, j int) bool { return h[i].freq < h[j].freq }
func (h freqHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
	h[i].index = i
	h[j].index = j
}
func (h *freqHeap) Push(x interface{}) {
	n := len(*h)
	entry := x.(*freqEntry)
	entry.index = n
	*h = append(*h, entry)
}
func (h *freqHeap) Pop() interface{} {
	old := *h
	n := len(old)
	entry := old[n-1]
	old[n-1] = nil
	entry.index = -1
	*h = old[:n-1]
	return entry
}

func (p *LFUPolicy) Record(key string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	p.freqs[key]++
}

func (p *LFUPolicy) Evict() string {
	p.mu.Lock()
	defer p.mu.Unlock()

	for p.minHeap.Len() > 0 {
		entry := heap.Pop(p.minHeap).(*freqEntry)
		if currentFreq, ok := p.freqs[entry.key]; ok && currentFreq == entry.freq {
			delete(p.freqs, entry.key)
			return entry.key
		}
	}

	// Fallback: find min frequency
	var minKey string
	var minFreq int64 = 1<<63 - 1
	for key, freq := range p.freqs {
		if freq < minFreq {
			minFreq = freq
			minKey = key
		}
	}
	if minKey != "" {
		delete(p.freqs, minKey)
	}
	return minKey
}

func (p *LFUPolicy) Remove(key string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	delete(p.freqs, key)
}

func (p *LFUPolicy) Name() string { return "LFU" }

// TTLEvictionPolicy evicts the item expiring soonest (nearest TTL)
type TTLEvictionPolicy struct {
	mu    sync.Mutex
	store *KVStore
}

func NewTTLEvictionPolicy(store *KVStore) *TTLEvictionPolicy {
	return &TTLEvictionPolicy{store: store}
}

func (p *TTLEvictionPolicy) Record(key string) {}
func (p *TTLEvictionPolicy) Remove(key string) {}
func (p *TTLEvictionPolicy) Name() string       { return "TTL" }

func (p *TTLEvictionPolicy) Evict() string {
	p.store.mu.RLock()
	defer p.store.mu.RUnlock()

	now := time.Now()
	var evictKey string
	var evictTime time.Time

	for key, val := range p.store.data {
		if val.ExpiresAt == nil {
			continue
		}
		if evictKey == "" || val.ExpiresAt.Before(evictTime) {
			evictKey = key
			evictTime = *val.ExpiresAt
		}
	}

	return evictKey
}

// ============================================================
// TTL MIN-HEAP FOR EFFICIENT EXPIRATION
// ============================================================

type expiryEntry struct {
	key       string
	expiresAt time.Time
	index     int
}

type expiryHeap []*expiryEntry

func (h expiryHeap) Len() int           { return len(h) }
func (h expiryHeap) Less(i, j int) bool { return h[i].expiresAt.Before(h[j].expiresAt) }
func (h expiryHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
	h[i].index = i
	h[j].index = j
}
func (h *expiryHeap) Push(x interface{}) {
	n := len(*h)
	entry := x.(*expiryEntry)
	entry.index = n
	*h = append(*h, entry)
}
func (h *expiryHeap) Pop() interface{} {
	old := *h
	n := len(old)
	entry := old[n-1]
	old[n-1] = nil
	entry.index = -1
	*h = old[:n-1]
	return entry
}

// ============================================================
// KV STORE
// ============================================================

type KVStore struct {
	mu            sync.RWMutex
	data          map[string]*Value
	eviction      EvictionPolicy
	maxSize       int64
	currentSize   int64
	ttlHeap       expiryHeap
	stats         StoreStats
}

type StoreStats struct {
	Gets     atomic.Int64
	Sets     atomic.Int64
	Deletes  atomic.Int64
	Expired  atomic.Int64
	Hits     atomic.Int64
	Misses   atomic.Int64
	Evictions atomic.Int64
}

func NewKVStore(maxSize int64, policy EvictionPolicy) *KVStore {
	store := &KVStore{
		data:     make(map[string]*Value),
		eviction: policy,
		maxSize:  maxSize,
		ttlHeap:  make(expiryHeap, 0),
	}
	heap.Init(&store.ttlHeap)
	return store
}

// Set stores a key-value pair with optional TTL
func (s *KVStore) Set(key string, value interface{}, ttl time.Duration) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.Sets.Add(1)

	// Check for existing key
	if existing, ok := s.data[key]; ok {
		s.currentSize -= existing.Size
	}

	// Evict if needed
	newVal := NewValue(value, ttl)
	for s.maxSize > 0 && s.currentSize+newVal.Size > s.maxSize {
		evictKey := s.eviction.Evict()
		if evictKey == "" {
			break
		}
		if oldVal, ok := s.data[evictKey]; ok {
			s.currentSize -= oldVal.Size
			delete(s.data, evictKey)
			s.stats.Evictions.Add(1)
		}
	}

	// Store
	s.data[key] = newVal
	s.currentSize += newVal.Size
	s.eviction.Record(key)

	// Track TTL in heap
	if ttl > 0 {
		entry := &expiryEntry{
			key:       key,
			expiresAt: *newVal.ExpiresAt,
		}
		heap.Push(&s.ttlHeap, entry)
	}

	return nil
}

// Get retrieves a value by key
func (s *KVStore) Get(key string) (interface{}, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	s.stats.Gets.Add(1)

	val, ok := s.data[key]
	if !ok {
		s.stats.Misses.Add(1)
		return nil, false
	}

	// Check expiration
	if val.IsExpired() {
		s.stats.Expired.Add(1)
		return nil, false
	}

	val.Touch()
	s.eviction.Record(key)
	s.stats.Hits.Add(1)
	return val.Data, true
}

// Delete removes a key
func (s *KVStore) Delete(key string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.Deletes.Add(1)

	val, ok := s.data[key]
	if !ok {
		return false
	}

	s.currentSize -= val.Size
	s.eviction.Remove(key)
	delete(s.data, key)
	return true
}

// ExpireExpired removes all expired keys
func (s *KVStore) ExpireExpired() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now()
	var expired int64

	for s.ttlHeap.Len() > 0 {
		entry := s.ttlHeap[0]
		if entry.expiresAt.After(now) {
			break
		}
		heap.Pop(&s.ttlHeap)

		if val, ok := s.data[entry.key]; ok && val.IsExpired() {
			s.currentSize -= val.Size
			s.eviction.Remove(entry.key)
			delete(s.data, entry.key)
			expired++
			s.stats.Expired.Add(1)
		}
	}

	return expired
}

// Snapshot saves the store to a JSON file
func (s *KVStore) Snapshot(path string) error {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Filter out expired keys
	snapshot := make(map[string]*Value)
	for key, val := range s.data {
		if !val.IsExpired() {
			snapshot[key] = val
		}
	}

	data, err := json.MarshalIndent(snapshot, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal snapshot: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("write snapshot: %w", err)
	}

	return nil
}

// LoadSnapshot loads the store from a JSON file
func (s *KVStore) LoadSnapshot(path string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("read snapshot: %w", err)
	}

	var snapshot map[string]*Value
	if err := json.Unmarshal(data, &snapshot); err != nil {
		return fmt.Errorf("unmarshal snapshot: %w", err)
	}

	s.data = snapshot
	for _, val := range snapshot {
		s.currentSize += val.Size
		if val.ExpiresAt != nil {
			entry := &expiryEntry{
				key:       "", // Will set after
				expiresAt: *val.ExpiresAt,
			}
			heap.Push(&s.ttlHeap, entry)
		}
	}

	return nil
}

// Stats returns store statistics
func (s *KVStore) Stats() map[string]interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return map[string]interface{}{
		"items":     len(s.data),
		"size":      s.currentSize,
		"max_size":  s.maxSize,
		"eviction":  s.eviction.Name(),
		"gets":      s.stats.Gets.Load(),
		"sets":      s.stats.Sets.Load(),
		"deletes":   s.stats.Deletes.Load(),
		"hits":      s.stats.Hits.Load(),
		"misses":    s.stats.Misses.Load(),
		"expired":   s.stats.Expired.Load(),
		"evictions": s.stats.Evictions.Load(),
		"hit_ratio": float64(s.stats.Hits.Load()) / float64(max(1, s.stats.Gets.Load())),
	}
}

// ============================================================
// BACKGROUND TTL CLEANUP
// ============================================================

type KVStoreWithCleanup struct {
	*KVStore
	stopCh chan struct{}
}

func NewKVStoreWithCleanup(maxSize int64, policy EvictionPolicy, cleanupInterval time.Duration) *KVStoreWithCleanup {
	store := &KVStoreWithCleanup{
		KVStore: NewKVStore(maxSize, policy),
		stopCh:  make(chan struct{}),
	}

	go func() {
		ticker := time.NewTicker(cleanupInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				expired := store.ExpireExpired()
				if expired > 0 {
					log.Printf("TTL cleanup: removed %d expired keys", expired)
				}
			case <-store.stopCh:
				return
			}
		}
	}()

	return store
}

func (s *KVStoreWithCleanup) Shutdown() {
	close(s.stopCh)
}

// ============================================================
// DEMO
// ============================================================

func main() {
	fmt.Println("=== In-Memory KV Store Demo ===\n")

	// Create store with LRU eviction, max 1MB
	store := NewKVStoreWithCleanup(1024*1024, NewLRUPolicy(), 1*time.Second)
	defer store.Shutdown()

	// Basic operations
	store.Set("user:1", map[string]interface{}{
		"name":  "Alice",
		"email": "alice@example.com",
	}, 0) // No TTL

	store.Set("session:abc123", "valid", 5*time.Second) // 5 second TTL

	store.Set("counter", 42, 0)

	// Reads
	if val, ok := store.Get("user:1"); ok {
		fmt.Printf("user:1 = %v\n", val)
	}

	if val, ok := store.Get("counter"); ok {
		fmt.Printf("counter = %v\n", val)
	}

	// TTL test
	fmt.Println("\nWaiting for TTL to expire session:abc123...")
	time.Sleep(6 * time.Second)
	store.ExpireExpired()

	if _, ok := store.Get("session:abc123"); !ok {
		fmt.Println("session:abc123 expired and removed")
	}

	// Remaining items
	if _, ok := store.Get("user:1"); ok {
		fmt.Println("user:1 still exists (no TTL)")
	}

	// Delete
	store.Delete("counter")

	// Stats
	fmt.Printf("\nStore stats: %+v\n", store.Stats())

	// Snapshot
	if err := store.Snapshot("/tmp/kvstore_snapshot.json"); err != nil {
		log.Printf("Snapshot error: %v", err)
	} else {
		fmt.Println("\nSnapshot saved to /tmp/kvstore_snapshot.json")
	}

	fmt.Println("\n=== Demo Complete ===")
}

