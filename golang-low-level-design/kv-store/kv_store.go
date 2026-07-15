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
// - Watch channels for subscribe/notify pattern
// - CAS (Check-And-Set) for optimistic concurrency
// - Namespace support for logical partitioning
// - Write-ahead log for crash recovery

package main

import (
	"container/heap"
	"container/list"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ============================================================
// VALUE WRAPPER
// ============================================================

type Value struct {
	Data        interface{} `json:"data"`
	CreatedAt   time.Time   `json:"created_at"`
	ModifiedAt  time.Time   `json:"modified_at"`
	ExpiresAt   *time.Time  `json:"expires_at,omitempty"`
	AccessCount int64       `json:"access_count"`
	Size        int64       `json:"size"`
	Version     uint64      `json:"version"`     // For CAS operations
	Metadata    map[string]string `json:"metadata,omitempty"`
}

func NewValue(data interface{}, ttl time.Duration) *Value {
	v := &Value{
		Data:        data,
		CreatedAt:   time.Now(),
		ModifiedAt:  time.Now(),
		AccessCount: 0,
		Version:     1,
		Metadata:    make(map[string]string),
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
	v.ModifiedAt = time.Now()
}

func (v *Value) ExtendTTL(ttl time.Duration) bool {
	if ttl <= 0 {
		return false
	}
	newExpiry := time.Now().Add(ttl)
	v.ExpiresAt = &newExpiry
	v.ModifiedAt = time.Now()
	return true
}

func (v *Value) ClearTTL() {
	v.ExpiresAt = nil
	v.ModifiedAt = time.Now()
}

func (v *Value) AddMetadata(key, value string) {
	v.Metadata[key] = value
}

func (v *Value) GetMetadata(key string) (string, bool) {
	val, ok := v.Metadata[key]
	return val, ok
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
	case map[string]interface{}:
		bytes, _ := json.Marshal(d)
		return int64(len(bytes))
	default:
		return int64(len(fmt.Sprintf("%v", d)))
	}
}

// ============================================================
// WATCH / SUBSCRIBE
// ============================================================

type WatchEventType int

const (
	EventSet    WatchEventType = iota
	EventDelete
	EventExpire
	EventUpdate
)

type WatchEvent struct {
	Type      WatchEventType
	Key       string
	Namespace string
	OldValue  interface{}
	NewValue  interface{}
	Timestamp time.Time
}

type WatchSubscription struct {
	pattern   string        // Key pattern (supports * wildcard)
	namespace string        // Namespace filter (empty = all)
	channel   chan WatchEvent
	active    atomic.Bool
}

// ============================================================
// EVICTION POLICY (Strategy Pattern)
// ============================================================

type EvictionPolicy interface {
	Record(key string)
	Evict() string
	Remove(key string)
	Name() string
	Size() int
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
func (p *LRUPolicy) Size() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.entries)
}

// LFUPolicy evicts the least frequently used item
type LFUPolicy struct {
	mu      sync.Mutex
	freqs   map[string]int64
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
	key   string
	freq  int64
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
func (p *LFUPolicy) Size() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.freqs)
}

// TTLEvictionPolicy evicts the item expiring soonest
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
func (p *TTLEvictionPolicy) Size() int          { return 0 }

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
	namespace string
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
// WRITE-AHEAD LOG
// ============================================================

type WALEntry struct {
	Timestamp time.Time `json:"timestamp"`
	Operation string    `json:"operation"` // SET, DELETE, CAS
	Namespace string    `json:"namespace"`
	Key       string    `json:"key"`
	Value     json.RawMessage `json:"value,omitempty"`
	TTL       time.Duration   `json:"ttl,omitempty"`
	Checksum  string    `json:"checksum"`
}

type WriteAheadLog struct {
	mu       sync.Mutex
	filePath string
	entries  []WALEntry
	enabled  bool
}

func NewWriteAheadLog(path string, enabled bool) *WriteAheadLog {
	return &WriteAheadLog{
		filePath: path,
		entries:  make([]WALEntry, 0),
		enabled:  enabled,
	}
}

func (wal *WriteAheadLog) Append(entry WALEntry) error {
	if !wal.enabled {
		return nil
	}
	wal.mu.Lock()
	defer wal.mu.Unlock()

	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}

	hash := sha256.Sum256(data)
	entry.Checksum = hex.EncodeToString(hash[:])
	wal.entries = append(wal.entries, entry)

	// Append to disk
	f, err := os.OpenFile(wal.filePath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("open WAL: %w", err)
	}
	defer f.Close()

	line := fmt.Sprintf("%s\n", data)
	if _, err := f.WriteString(line); err != nil {
		return fmt.Errorf("write WAL: %w", err)
	}
	return nil
}

// ============================================================
// KV STORE
// ============================================================

type KVStore struct {
	mu            sync.RWMutex
	data          map[string]*Value
	namespaces    map[string]map[string]*Value // namespace -> key -> value
	eviction      EvictionPolicy
	maxSize       int64
	currentSize   int64
	ttlHeap       expiryHeap
	stats         StoreStats
	subscriptions []*WatchSubscription
	wal           *WriteAheadLog
}

type StoreStats struct {
	Gets      atomic.Int64
	Sets      atomic.Int64
	Deletes   atomic.Int64
	Expired   atomic.Int64
	Hits      atomic.Int64
	Misses    atomic.Int64
	Evictions atomic.Int64
	CASOps    atomic.Int64
	WatchDrops atomic.Int64
}

func NewKVStore(maxSize int64, policy EvictionPolicy) *KVStore {
	store := &KVStore{
		data:          make(map[string]*Value),
		namespaces:    make(map[string]map[string]*Value),
		eviction:      policy,
		maxSize:       maxSize,
		ttlHeap:       make(expiryHeap, 0),
		subscriptions: make([]*WatchSubscription, 0),
		wal:           NewWriteAheadLog("/tmp/kvstore_wal.log", false),
	}
	heap.Init(&store.ttlHeap)
	return store
}

// ---- Basic Operations ----

func (s *KVStore) Set(key string, value interface{}, ttl time.Duration) error {
	return s.SetWithNamespace("default", key, value, ttl)
}

func (s *KVStore) SetWithNamespace(namespace, key string, value interface{}, ttl time.Duration) error {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.Sets.Add(1)

	// Check for existing key
	if existing, ok := s.data[nsKey]; ok {
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
			s.publishEvent(namespace, evictKey, EventDelete, oldVal.Data, nil)
		}
	}

	// Store
	oldVal := s.data[nsKey]
	s.data[nsKey] = newVal
	s.currentSize += newVal.Size
	s.eviction.Record(nsKey)

	// Track in namespace
	if _, ok := s.namespaces[namespace]; !ok {
		s.namespaces[namespace] = make(map[string]*Value)
	}
	s.namespaces[namespace][key] = newVal

	// Track TTL in heap
	if ttl > 0 {
		entry := &expiryEntry{
			key:       nsKey,
			namespace: namespace,
			expiresAt: *newVal.ExpiresAt,
		}
		heap.Push(&s.ttlHeap, entry)
	}

	// Publish watch event
	if oldVal != nil {
		s.publishEvent(namespace, key, EventUpdate, oldVal.Data, value)
	} else {
		s.publishEvent(namespace, key, EventSet, nil, value)
	}

	// WAL
	s.wal.Append(WALEntry{
		Timestamp: time.Now(),
		Operation: "SET",
		Namespace: namespace,
		Key:       key,
		Value:     mustMarshalJSON(value),
		TTL:       ttl,
	})

	return nil
}

func (s *KVStore) Get(key string) (interface{}, bool) {
	return s.GetFromNamespace("default", key)
}

func (s *KVStore) GetFromNamespace(namespace, key string) (interface{}, bool) {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.RLock()
	defer s.mu.RUnlock()

	s.stats.Gets.Add(1)

	val, ok := s.data[nsKey]
	if !ok {
		s.stats.Misses.Add(1)
		return nil, false
	}

	if val.IsExpired() {
		s.stats.Expired.Add(1)
		return nil, false
	}

	val.Touch()
	s.eviction.Record(nsKey)
	s.stats.Hits.Add(1)
	return val.Data, true
}

func (s *KVStore) Delete(key string) bool {
	return s.DeleteFromNamespace("default", key)
}

func (s *KVStore) DeleteFromNamespace(namespace, key string) bool {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.Deletes.Add(1)

	val, ok := s.data[nsKey]
	if !ok {
		return false
	}

	s.currentSize -= val.Size
	s.eviction.Remove(nsKey)
	delete(s.data, nsKey)

	// Remove from namespace
	if ns, ok := s.namespaces[namespace]; ok {
		delete(ns, key)
	}

	s.publishEvent(namespace, key, EventDelete, val.Data, nil)

	// WAL
	s.wal.Append(WALEntry{
		Timestamp: time.Now(),
		Operation: "DELETE",
		Namespace: namespace,
		Key:       key,
	})

	return true
}

// ---- CAS (Check-And-Set) Operations ----

type CASResult int

const (
	CASOK       CASResult = iota // Value was updated
	CASNotFound                  // Key does not exist
	CASVersionMismatch            // Version does not match
	CASExpired                    // Key has expired
)

func (s *KVStore) CAS(key string, expectedVersion uint64, newValue interface{}, ttl time.Duration) CASResult {
	return s.CASWithNamespace("default", key, expectedVersion, newValue, ttl)
}

func (s *KVStore) CASWithNamespace(namespace, key string, expectedVersion uint64, newValue interface{}, ttl time.Duration) CASResult {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.CASOps.Add(1)

	val, ok := s.data[nsKey]
	if !ok {
		return CASNotFound
	}

	if val.IsExpired() {
		return CASExpired
	}

	if val.Version != expectedVersion {
		return CASVersionMismatch
	}

	// CAS succeeded — update value
	oldData := val.Data
	newVal := NewValue(newValue, ttl)
	newVal.Version = val.Version + 1
	newVal.AccessCount = val.AccessCount
	newVal.Metadata = val.Metadata
	newVal.CreatedAt = val.CreatedAt

	s.currentSize -= val.Size
	s.currentSize += newVal.Size
	s.data[nsKey] = newVal
	s.eviction.Record(nsKey)

	s.publishEvent(namespace, key, EventUpdate, oldData, newValue)

	s.stats.Sets.Add(1)

	// WAL
	s.wal.Append(WALEntry{
		Timestamp: time.Now(),
		Operation: "CAS",
		Namespace: namespace,
		Key:       key,
		Value:     mustMarshalJSON(newValue),
		TTL:       ttl,
	})

	return CASOK
}

// ---- Multi-Key Operations ----

func (s *KVStore) MSet(pairs map[string]interface{}, ttl time.Duration) int {
	return s.MSetWithNamespace("default", pairs, ttl)
}

func (s *KVStore) MSetWithNamespace(namespace string, pairs map[string]interface{}, ttl time.Duration) int {
	var count int
	for key, value := range pairs {
		if err := s.SetWithNamespace(namespace, key, value, ttl); err == nil {
			count++
		}
	}
	return count
}

func (s *KVStore) MGet(keys []string) map[string]interface{} {
	return s.MGetFromNamespace("default", keys)
}

func (s *KVStore) MGetFromNamespace(namespace string, keys []string) map[string]interface{} {
	result := make(map[string]interface{})
	for _, key := range keys {
		if val, ok := s.GetFromNamespace(namespace, key); ok {
			result[key] = val
		}
	}
	return result
}

// ---- TTL Operations ----

func (s *KVStore) Expire(key string, ttl time.Duration) bool {
	return s.ExpireKey("default", key, ttl)
}

func (s *KVStore) ExpireKey(namespace, key string, ttl time.Duration) bool {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	val, ok := s.data[nsKey]
	if !ok || val.IsExpired() {
		return false
	}

	val.ExtendTTL(ttl)

	entry := &expiryEntry{
		key:       nsKey,
		namespace: namespace,
		expiresAt: *val.ExpiresAt,
	}
	heap.Push(&s.ttlHeap, entry)

	return true
}

func (s *KVStore) TTL(key string) (time.Duration, bool) {
	return s.TTLFor("default", key)
}

func (s *KVStore) TTLFor(namespace, key string) (time.Duration, bool) {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.RLock()
	defer s.mu.RUnlock()

	val, ok := s.data[nsKey]
	if !ok || val.IsExpired() {
		return 0, false
	}

	if val.ExpiresAt == nil {
		return -1, true // No TTL
	}

	remaining := time.Until(*val.ExpiresAt)
	if remaining < 0 {
		return 0, false
	}
	return remaining, true
}

func (s *KVStore) Persist(key string) bool {
	return s.PersistKey("default", key)
}

func (s *KVStore) PersistKey(namespace, key string) bool {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	val, ok := s.data[nsKey]
	if !ok {
		return false
	}

	val.ClearTTL()
	return true
}

// ---- Namespace Operations ----

func (s *KVStore) ListNamespaces() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	namespaces := make([]string, 0, len(s.namespaces))
	for ns := range s.namespaces {
		namespaces = append(namespaces, ns)
	}
	return namespaces
}

func (s *KVStore) ListKeys(namespace string) []string {
	nsKey := s.namespacedKeyPrefix(namespace)

	s.mu.RLock()
	defer s.mu.RUnlock()

	keys := make([]string, 0)
	for key := range s.data {
		if strings.HasPrefix(key, nsKey) {
			cleanKey := strings.TrimPrefix(key, nsKey+":")
			keys = append(keys, cleanKey)
		}
	}
	return keys
}

func (s *KVStore) DeleteNamespace(namespace string) int {
	s.mu.Lock()
	defer s.mu.Unlock()

	var deleted int
	nsKey := s.namespacedKeyPrefix(namespace)

	for key, val := range s.data {
		if strings.HasPrefix(key, nsKey) {
			s.currentSize -= val.Size
			s.eviction.Remove(key)
			delete(s.data, key)
			deleted++
		}
	}
	delete(s.namespaces, namespace)
	s.stats.Deletes.Add(int64(deleted))

	return deleted
}

// ---- Watch / Subscribe ----

func (s *KVStore) Subscribe(pattern, namespace string, bufferSize int) *WatchSubscription {
	sub := &WatchSubscription{
		pattern:   pattern,
		namespace: namespace,
		channel:   make(chan WatchEvent, bufferSize),
	}
	sub.active.Store(true)

	s.mu.Lock()
	s.subscriptions = append(s.subscriptions, sub)
	s.mu.Unlock()

	return sub
}

func (s *KVStore) Unsubscribe(sub *WatchSubscription) {
	sub.active.Store(false)
	s.mu.Lock()
	defer s.mu.Unlock()

	for i, s := range s.subscriptions {
		if s == sub {
			s.subscriptions = append(s.subscriptions[:i], s.subscriptions[i+1:]...)
			close(sub.channel)
			return
		}
	}
}

func (s *KVStore) publishEvent(namespace, key string, eventType WatchEventType, oldVal, newVal interface{}) {
	for _, sub := range s.subscriptions {
		if !sub.active.Load() {
			continue
		}
		if sub.namespace != "" && sub.namespace != namespace {
			continue
		}
		if sub.pattern != "" && !matchPattern(sub.pattern, key) {
			continue
		}

		select {
		case sub.channel <- WatchEvent{
			Type:      eventType,
			Key:       key,
			Namespace: namespace,
			OldValue:  oldVal,
			NewValue:  newVal,
			Timestamp: time.Now(),
		}:
		default:
			s.stats.WatchDrops.Add(1) // Channel full, drop event
		}
	}
}

// ---- Metadata Operations ----

func (s *KVStore) SetMetadata(key, metaKey, metaValue string) bool {
	return s.SetMetadataFor("default", key, metaKey, metaValue)
}

func (s *KVStore) SetMetadataFor(namespace, key, metaKey, metaValue string) bool {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	val, ok := s.data[nsKey]
	if !ok || val.IsExpired() {
		return false
	}

	val.AddMetadata(metaKey, metaValue)
	return true
}

func (s *KVStore) GetMetadata(namespace, key, metaKey string) (string, bool) {
	nsKey := s.namespacedKey(namespace, key)

	s.mu.RLock()
	defer s.mu.RUnlock()

	val, ok := s.data[nsKey]
	if !ok || val.IsExpired() {
		return "", false
	}

	return val.GetMetadata(metaKey)
}

// ---- Snapshot & Recovery ----

func (s *KVStore) Snapshot(path string) error {
	s.mu.RLock()
	defer s.mu.RUnlock()

	type snapshotEntry struct {
		Key       string        `json:"key"`
		Namespace string        `json:"namespace"`
		Value     *Value        `json:"value"`
	}

	snapshot := struct {
		Data       map[string]*Value            `json:"data"`
		Namespaces map[string]map[string]*Value `json:"namespaces"`
		Stats      StoreStats                    `json:"stats"`
		Timestamp  time.Time                     `json:"timestamp"`
	}{
		Data:       make(map[string]*Value),
		Namespaces: s.namespaces,
		Timestamp:  time.Now(),
	}

	// Filter out expired keys
	for key, val := range s.data {
		if !val.IsExpired() {
			snapshot.Data[key] = val
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

	var snapshot struct {
		Data       map[string]*Value            `json:"data"`
		Namespaces map[string]map[string]*Value `json:"namespaces"`
	}

	if err := json.Unmarshal(data, &snapshot); err != nil {
		return fmt.Errorf("unmarshal snapshot: %w", err)
	}

	s.data = snapshot.Data
	s.namespaces = snapshot.Namespaces
	s.currentSize = 0

	// Rebuild TTL heap from data
	s.ttlHeap = make(expiryHeap, 0)
	heap.Init(&s.ttlHeap)
	for nsKey, val := range s.data {
		if val.ExpiresAt != nil && val.ExpiresAt.After(time.Now()) {
			ns := "default"
			key := nsKey
			if idx := strings.Index(nsKey, ":"); idx > 0 {
				ns = nsKey[:idx]
				if len(nsKey) > idx+1 {
					key = nsKey[idx+1:]
				}
			}
			entry := &expiryEntry{
				key:       nsKey,
				namespace: ns,
				expiresAt: *val.ExpiresAt,
			}
			heap.Push(&s.ttlHeap, entry)
		}
	}

	return nil
}

// ---- Expiry & Cleanup ----

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

			// Clean namespace
			if ns, ok := s.namespaces[entry.namespace]; ok {
				// Extract clean key from namespaced key
				cleanKey := strings.TrimPrefix(entry.key, entry.namespace+":")
				delete(ns, cleanKey)
			}

			expired++
			s.stats.Expired.Add(1)
			s.publishEvent(entry.namespace, entry.key, EventExpire, val.Data, nil)
		}
	}

	return expired
}

// ---- Stats ----

func (s *KVStore) Stats() map[string]interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()

	gets := s.stats.Gets.Load()
	hits := s.stats.Hits.Load()

	hitRatio := 0.0
	if gets > 0 {
		hitRatio = float64(hits) / float64(gets)
	}

	return map[string]interface{}{
		"items":       len(s.data),
		"size":        s.currentSize,
		"max_size":    s.maxSize,
		"eviction":    s.eviction.Name(),
		"eviction_tracking": s.eviction.Size(),
		"namespaces":  len(s.namespaces),
		"gets":        gets,
		"sets":        s.stats.Sets.Load(),
		"deletes":     s.stats.Deletes.Load(),
		"hits":        hits,
		"misses":      s.stats.Misses.Load(),
		"expired":     s.stats.Expired.Load(),
		"evictions":   s.stats.Evictions.Load(),
		"cas_ops":     s.stats.CASOps.Load(),
		"watch_drops": s.stats.WatchDrops.Load(),
		"hit_ratio":   hitRatio,
	}
}

// ---- Internal Helpers ----

func (s *KVStore) namespacedKey(namespace, key string) string {
	return namespace + ":" + key
}

func (s *KVStore) namespacedKeyPrefix(namespace string) string {
	return namespace + ":"
}

func matchPattern(pattern, key string) bool {
	if pattern == "*" || pattern == "" {
		return true
	}
	if strings.HasSuffix(pattern, "*") {
		prefix := strings.TrimSuffix(pattern, "*")
		return strings.HasPrefix(key, prefix)
	}
	return pattern == key
}

func mustMarshalJSON(v interface{}) json.RawMessage {
	data, _ := json.Marshal(v)
	return json.RawMessage(data)
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
	fmt.Println("╔══════════════════════════════════╗")
	fmt.Println("║     IN-MEMORY KV STORE DEMO      ║")
	fmt.Println("╚══════════════════════════════════╝\n")

	// Create store with LRU eviction, max 1MB
	store := NewKVStoreWithCleanup(1024*1024, NewLRUPolicy(), 1*time.Second)
	defer store.Shutdown()

	// ---- BASIC OPERATIONS ----
	fmt.Println("--- BASIC OPERATIONS ---")
	store.Set("user:1", map[string]interface{}{
		"name":  "Alice",
		"email": "alice@example.com",
		"role":  "admin",
	}, 0)

	store.Set("session:abc123", "valid-token", 5*time.Second)
	store.Set("counter", 42, 0)

	if val, ok := store.Get("user:1"); ok {
		fmt.Printf("  user:1 = %v\n", val)
	}
	if val, ok := store.Get("counter"); ok {
		fmt.Printf("  counter = %v\n", val)
	}

	// ---- TTL OPERATIONS ----
	fmt.Println("\n--- TTL OPERATIONS ---")
	ttl, exists := store.TTL("session:abc123")
	if exists {
		fmt.Printf("  session:abc123 TTL = %v\n", ttl)
	}

	// Extend TTL
	store.Expire("session:abc123", 30*time.Second)
	ttl, _ = store.TTL("session:abc123")
	fmt.Printf("  session:abc123 extended TTL = %v\n", ttl)

	// Persist (remove TTL)
	store.Persist("counter")
	ttl, exists = store.TTL("counter")
	fmt.Printf("  counter TTL = %v (persistent: %v)\n", ttl, ttl < 0)

	// ---- CAS OPERATIONS ----
	fmt.Println("\n--- CAS OPERATIONS ---")
	// First get the current version
	store.Set("config:theme", "dark", 0)
	result := store.CAS("config:theme", 1, "light", 0)
	fmt.Printf("  CAS with version 1: %v\n", result)

	result = store.CAS("config:theme", 1, "blue", 0)
	fmt.Printf("  CAS with old version 1 (stale): %v\n", result)

	result = store.CAS("config:theme", 2, "blue", 0)
	fmt.Printf("  CAS with correct version 2: %v\n", result)

	val, _ := store.Get("config:theme")
	fmt.Printf("  config:theme = %v\n", val)

	// ---- NAMESPACE OPERATIONS ----
	fmt.Println("\n--- NAMESPACE OPERATIONS ---")
	store.SetWithNamespace("cache", "homepage", "<html>cached</html>", 30*time.Second)
	store.SetWithNamespace("cache", "api:users", `{"users":[]}`, 10*time.Second)
	store.SetWithNamespace("config", "app:name", "MyApp", 0)
	store.SetWithNamespace("config", "app:version", "1.0.0", 0)

	fmt.Printf("  Namespaces: %v\n", store.ListNamespaces())
	fmt.Printf("  Cache keys: %v\n", store.ListKeys("cache"))
	fmt.Printf("  Config keys: %v\n", store.ListKeys("config"))

	if val, ok := store.GetFromNamespace("cache", "homepage"); ok {
		fmt.Printf("  cache:homepage = %v\n", val)
	}

	// ---- MULTI-KEY OPERATIONS ----
	fmt.Println("\n--- MULTI-KEY OPERATIONS ---")
	store.MSet(map[string]interface{}{
		"color": "red",
		"size":  "large",
		"shape": "circle",
	}, 0)

	results := store.MGet([]string{"color", "size", "shape", "nonexistent"})
	fmt.Printf("  MGet results: %v\n", results)

	// ---- WATCH / SUBSCRIBE ----
	fmt.Println("\n--- WATCH / SUBSCRIBE ---")
	sub := store.Subscribe("user:*", "default", 10)
	fmt.Println("  Subscribed to user:* pattern")

	store.Set("user:2", map[string]string{"name": "Bob"}, 0)
	store.Set("user:3", map[string]string{"name": "Charlie"}, 0)

	// Non-blocking read from subscription channel
	select {
	case event := <-sub.channel:
		fmt.Printf("  Watch event: %s %s = %v\n", eventTypeName(event.Type), event.Key, event.NewValue)
	default:
		fmt.Println("  No watch events available (buffered)")
	}

	// Read remaining events
	for i := 0; i < 2; i++ {
		select {
		case event := <-sub.channel:
			fmt.Printf("  Watch event: %s %s = %v\n", eventTypeName(event.Type), event.Key, event.NewValue)
		default:
			break
		}
	}

	store.Unsubscribe(sub)
	fmt.Println("  Unsubscribed")

	// ---- METADATA ----
	fmt.Println("\n--- METADATA ---")
	store.SetMetadata("user:1", "department", "Engineering")
	store.SetMetadata("user:1", "location", "NYC")

	if dept, ok := store.GetMetadata("default", "user:1", "department"); ok {
		fmt.Printf("  user:1 department = %s\n", dept)
	}

	// ---- STATS ----
	fmt.Printf("\nStore stats: %+v\n", store.Stats())

	// ---- SNAPSHOT ----
	if err := store.Snapshot("/tmp/kvstore_snapshot.json"); err != nil {
		log.Printf("Snapshot error: %v", err)
	} else {
		fmt.Println("\n📸 Snapshot saved to /tmp/kvstore_snapshot.json")
	}

	// ---- DELETE NAMESPACE ----
	fmt.Println("\n--- DELETE NAMESPACE ---")
	deleted := store.DeleteNamespace("config")
	fmt.Printf("  Deleted config namespace: %d keys\n", deleted)

	fmt.Println("\n╔══════════════════════════════════╗")
	fmt.Println("║       DEMO COMPLETE             ║")
	fmt.Println("╚══════════════════════════════════╝")
}

func eventTypeName(t WatchEventType) string {
	switch t {
	case EventSet:
		return "SET"
	case EventDelete:
		return "DELETE"
	case EventExpire:
		return "EXPIRE"
	case EventUpdate:
		return "UPDATE"
	default:
		return "UNKNOWN"
	}
}
