# In-Memory KV Store — Go Implementation

> A generic, sharded in-memory key-value store with TTL, pluggable LRU/LFU eviction, versioned CAS, watch streams and snapshot/restore.

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|---------------|---------|
| `Store[V]` | Public API: `Set`, `Get`, `GetVersioned`, `Delete`, `CompareAndSwap`, `Expire`, `Persist`, `TTL`, `Keys`, `Watch`, `Snapshot`, `Restore`, `RunJanitor` | Facade |
| `shard[V]` | One lock + map + eviction policy + expiry heap + cost counter | Lock striping |
| `EvictionPolicy` | `OnInsert` / `OnAccess` / `OnRemove` / `Victim` | Strategy |
| `LRU` | `container/list` + index map, all ops O(1) | |
| `LFU` | Frequency buckets (each an LRU list) + `minFreq`, all ops O(1) | |
| `expiryHeap[V]` | Min-heap on `expiresAt` that keeps `entry.heapIdx` current | Indexed heap |
| `Event[V]` / `Watch` | Prefix-filtered change stream on a store-owned channel | Observer |
| `ManualClock` | Injected clock so TTL tests never sleep | |

### Key design decisions

**1. Sharded `sync.Mutex`, not one `sync.RWMutex`.** LRU and LFU change state on every read: `Get` moves the key in the recency list. With an `RWMutex`, `Get` would mutate shared state under `RLock`, which is a data race. (The previous version of this file had exactly that bug.) So reads need the exclusive lock, and the way to scale is striping: `maphash.String(seed, key) % N` picks a shard, and only writers to the same shard contend. The cost is that with N > 1, eviction is per shard, which only approximates global LRU. `Shards: 1` gives exact global LRU. An `RWMutex` pays off only when reads are truly read-only, for example a TTL-only or FIFO store, or a "sampled LRU" that records access with an atomic timestamp the way Redis does.

**2. One lock per operation.** Policies are deliberately *not* goroutine-safe. The shard calls them with its own lock held. If the policy had its own mutex as well, every call would take two locks and invite lock-ordering bugs. The only nested lock is `shard.mu → watchMu`, and it is always taken in that order.

**3. Replace = remove + insert.** `putLocked` removes the old entry before running the eviction loop. That way a write at full capacity can never evict the key being written, and the cost is never double-subtracted. The size check runs *before* the old value is touched, so a failed `ErrTooLarge` write changes nothing. Before evicting live keys, the loop first purges entries whose TTL has already expired.

**4. Indexed expiry heap.** Each entry stores its index in the heap. That makes `Persist`, overwrite and delete O(log n) through `heap.Remove`/`heap.Fix`, and the heap never holds stale nodes. A lazy-deletion heap, where you push on every write and skip stale nodes on pop, is simpler, but a key overwritten in a hot loop with a long TTL grows that heap without bound.

**5. Lazy + active expiry** (what Redis does). Every access checks the deadline and deletes an expired key (`liveLocked`). `RunJanitor(ctx, interval)` pops expired keys from each shard's heap one shard at a time, so it never blocks the whole store. `RunJanitor` blocks and returns `ctx.Err()`, which leaves the caller in charge of the goroutine: `go store.RunJanitor(ctx, time.Second)`.

**6. Store-wide monotonic versions.** Every write takes `version.Add(1)` from one atomic counter, like an etcd revision. If versions were per key and started at 1, then `delete` followed by re-create would reuse version 1, and a stale `CompareAndSwap(k, 1, …)` would succeed. That is the ABA problem. `expected == 0` means "create only if absent" (SETNX).

**7. Watch channel ownership.** `Watch(ctx, prefix)` returns a `<-chan Event[V]`. The store is the only sender, so the store closes it. `context.AfterFunc(ctx, …)` unregisters the watcher and closes the channel under `watchMu.Lock`, which excludes `publish` (it holds `RLock`), so the store can never send on a closed channel. No goroutine runs per watcher. `publish` runs under the key's shard lock, so events for a key arrive in version order. Delivery uses a non-blocking `select`: a slow consumer loses events, counted in `Stats().DroppedEvents`, instead of stalling every writer.

**8. Snapshot is consistent per shard, not per store.** The store copies each shard under its own lock and encodes the result outside any lock. For a cache that's fine. A database would need a point-in-time snapshot (fork + copy-on-write like Redis `BGSAVE`, or snapshot + WAL offset). `Restore` skips entries that expired in the meantime and moves the version counter past every restored version.

### Where to extend

| Requirement | Change |
|---|---|
| New eviction policy (FIFO, ARC, W-TinyLFU) | New `EvictionPolicy` implementation; nothing else changes |
| Byte-based capacity | `Options.Cost = func(k string, v V) int64 { return int64(len(k) + len(v)) }` |
| Namespaces / multi-tenancy | Key prefix + `Keys(prefix)` + `Watch(ctx, prefix)`; per-tenant quotas mean one `Store` per tenant |
| Durability | Append each `putLocked`/`removeLocked` to a WAL before acknowledging; replay the WAL after `Restore` |
| `INCR` without a client retry loop | A `Update(key, func(old V, ok bool) (V, error))` that runs the function under the shard lock |

## ▶️ How to Run

```bash
cd golang-low-level-design/kv-store
go run kv_store.go
go test -race kv_store.go kv_store_test.go
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `EvictionPolicy` (`LRU`, `LFU`) | Swap the eviction algorithm without touching the store |
| **Facade** | `Store[V]` | One API over shards, heaps, policies and watchers |
| **Lock striping** | `shard[V]` | Contention scales with shard count, not total traffic |
| **Observer** | `Watch` / `publish` | Change notifications with explicit drop semantics |
| **Dependency injection** | `Options.Clock` | Deterministic TTL tests |

## 📄 Full Source

<!-- source: kv_store.go -->
```go
// In-Memory Key-Value Store - Low Level Design (Go)
// --------------------------------------------------
// A generic, sharded, in-memory KV store with TTL, pluggable eviction,
// optimistic concurrency (CAS), watch streams and snapshot/restore.
//
// Key design decisions:
//   - Store[V any]: values are typed, so snapshots round-trip without the
//     interface{} -> float64 surprises of encoding/json.
//   - Sharding: keys hash (hash/maphash) onto N shards, each with its own
//     sync.Mutex, map, eviction policy and expiry heap. A Mutex (not an
//     RWMutex) because LRU/LFU turn every Get into a write: the recency list
//     moves on each read, so a read lock would be a data race.
//   - Eviction policy is a Strategy (LRU, LFU). Policies are deliberately not
//     goroutine-safe; the owning shard calls them with its lock held, so there
//     is exactly one lock per operation and no lock-ordering puzzles.
//   - TTL: lazy expiry on access + an active janitor (RunJanitor) that pops an
//     indexed min-heap. Entries carry their heap index, so overwrite/Persist
//     remove the old deadline in O(log n) and the heap never holds stale nodes.
//   - Versions come from one store-wide monotonic counter (like an etcd
//     revision). Delete + re-create yields a new version, so CAS has no ABA.
//   - Watch(ctx, prefix) returns a receive-only channel that the store owns
//     and closes when ctx is cancelled (context.AfterFunc: no goroutine per
//     watcher). Delivery is non-blocking: a slow watcher drops events rather
//     than stalling writers, and drops are counted.
//   - The clock is injected so TTL behaviour is testable without sleeping.

package main

import (
	"container/heap"
	"container/list"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"hash/maphash"
	"io"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

var (
	ErrNotFound        = errors.New("kvstore: key not found")
	ErrVersionMismatch = errors.New("kvstore: version mismatch")
	ErrTooLarge        = errors.New("kvstore: entry cost exceeds shard capacity")
)

// NoTTL is returned by TTL for a key that never expires.
const NoTTL time.Duration = -1

// ============================================================
// EVICTION POLICY (Strategy)
// ============================================================

// EvictionPolicy picks the next key to evict when a shard is over capacity.
// Implementations are NOT goroutine-safe: the shard calls them with its lock held.
type EvictionPolicy interface {
	OnInsert(key string)
	OnAccess(key string)
	OnRemove(key string)
	// Victim returns the key to evict next without removing it; the shard
	// removes it (which calls OnRemove).
	Victim() (string, bool)
	Name() string
}

// LRU: doubly-linked list ordered by recency + index map. All ops O(1).
type LRU struct {
	ll  *list.List // front = most recently used
	idx map[string]*list.Element
}

func NewLRU() EvictionPolicy {
	return &LRU{ll: list.New(), idx: make(map[string]*list.Element)}
}

func (p *LRU) OnInsert(key string) { p.idx[key] = p.ll.PushFront(key) }
func (p *LRU) OnAccess(key string) {
	if e, ok := p.idx[key]; ok {
		p.ll.MoveToFront(e)
	}
}
func (p *LRU) OnRemove(key string) {
	if e, ok := p.idx[key]; ok {
		p.ll.Remove(e)
		delete(p.idx, key)
	}
}
func (p *LRU) Victim() (string, bool) {
	if e := p.ll.Back(); e != nil {
		return e.Value.(string), true
	}
	return "", false
}
func (p *LRU) Name() string { return "LRU" }

// LFU: O(1) LFU with frequency buckets. Each bucket is an LRU list so ties
// on frequency evict the least recently used key.
type LFU struct {
	idx     map[string]*list.Element // value: *lfuNode
	buckets map[int]*list.List       // freq -> keys with that freq (front = most recent)
	minFreq int
}

type lfuNode struct {
	key  string
	freq int
}

func NewLFU() EvictionPolicy {
	return &LFU{idx: make(map[string]*list.Element), buckets: make(map[int]*list.List)}
}

func (p *LFU) bucket(freq int) *list.List {
	b, ok := p.buckets[freq]
	if !ok {
		b = list.New()
		p.buckets[freq] = b
	}
	return b
}

// unlink removes e from its bucket, dropping the bucket when it empties.
func (p *LFU) unlink(e *list.Element) *lfuNode {
	n := e.Value.(*lfuNode)
	b := p.buckets[n.freq]
	b.Remove(e)
	if b.Len() == 0 {
		delete(p.buckets, n.freq)
	}
	return n
}

func (p *LFU) OnInsert(key string) {
	p.idx[key] = p.bucket(1).PushFront(&lfuNode{key: key, freq: 1})
	p.minFreq = 1
}

func (p *LFU) OnAccess(key string) {
	e, ok := p.idx[key]
	if !ok {
		return
	}
	n := p.unlink(e)
	if n.freq == p.minFreq && p.buckets[n.freq] == nil {
		p.minFreq++
	}
	n.freq++
	p.idx[key] = p.bucket(n.freq).PushFront(n)
}

func (p *LFU) OnRemove(key string) {
	if e, ok := p.idx[key]; ok {
		p.unlink(e)
		delete(p.idx, key)
		// minFreq may now point at a missing bucket; Victim repairs it lazily.
	}
}

func (p *LFU) Victim() (string, bool) {
	if len(p.idx) == 0 {
		return "", false
	}
	if p.buckets[p.minFreq] == nil { // stale after an arbitrary OnRemove
		p.minFreq = -1
		for f := range p.buckets { // O(#distinct frequencies), only after deletes
			if p.minFreq == -1 || f < p.minFreq {
				p.minFreq = f
			}
		}
	}
	return p.buckets[p.minFreq].Back().Value.(*lfuNode).key, true
}
func (p *LFU) Name() string { return "LFU" }

// ============================================================
// ENTRY + EXPIRY HEAP
// ============================================================

type entry[V any] struct {
	key       string
	value     V
	version   uint64
	expiresAt time.Time // zero = never expires
	cost      int64
	heapIdx   int // position in the shard's expiry heap, -1 if not in it
}

func (e *entry[V]) expired(now time.Time) bool {
	return !e.expiresAt.IsZero() && !now.Before(e.expiresAt)
}

// expiryHeap is a min-heap on expiresAt that keeps entry.heapIdx current,
// so an entry's deadline can be removed or changed in O(log n).
type expiryHeap[V any] []*entry[V]

func (h expiryHeap[V]) Len() int           { return len(h) }
func (h expiryHeap[V]) Less(i, j int) bool { return h[i].expiresAt.Before(h[j].expiresAt) }
func (h expiryHeap[V]) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
	h[i].heapIdx = i
	h[j].heapIdx = j
}
func (h *expiryHeap[V]) Push(x any) {
	e := x.(*entry[V])
	e.heapIdx = len(*h)
	*h = append(*h, e)
}
func (h *expiryHeap[V]) Pop() any {
	old := *h
	e := old[len(old)-1]
	old[len(old)-1] = nil
	e.heapIdx = -1
	*h = old[:len(old)-1]
	return e
}

// ============================================================
// EVENTS / WATCH
// ============================================================

type EventType int

const (
	EventSet EventType = iota
	EventDelete
	EventExpire
	EventEvict
)

func (t EventType) String() string {
	return [...]string{"SET", "DELETE", "EXPIRE", "EVICT"}[t]
}

type Event[V any] struct {
	Type    EventType
	Key     string
	Value   V // new value for SET, last value otherwise
	Version uint64
}

type watcher[V any] struct {
	prefix string
	ch     chan Event[V]
}

// ============================================================
// STORE
// ============================================================

type Options[V any] struct {
	Shards      int                         // default 1 (exact global LRU/LFU)
	MaxCost     int64                       // total capacity across shards; 0 = unbounded
	Cost        func(key string, v V) int64 // default: 1 per entry, so MaxCost = max items
	NewPolicy   func() EvictionPolicy       // default NewLRU
	Clock       func() time.Time            // default time.Now
	WatchBuffer int                         // per-watcher channel buffer, default 64
}

type shard[V any] struct {
	mu      sync.Mutex
	items   map[string]*entry[V]
	policy  EvictionPolicy
	expiry  expiryHeap[V]
	cost    int64
	maxCost int64 // 0 = unbounded
}

type Stats struct {
	Hits, Misses, Evictions, Expirations, DroppedEvents int64
	Items                                               int
	Cost                                                int64
}

type Store[V any] struct {
	shards  []*shard[V]
	seed    maphash.Seed
	cost    func(string, V) int64
	now     func() time.Time
	watchSz int

	version atomic.Uint64 // store-wide revision; every write gets a fresh one

	watchMu  sync.RWMutex // lock order: shard.mu -> watchMu
	watchers map[*watcher[V]]struct{}

	hits, misses, evictions, expirations, dropped atomic.Int64
}

func NewStore[V any](opts Options[V]) *Store[V] {
	if opts.Shards <= 0 {
		opts.Shards = 1
	}
	if opts.Cost == nil {
		opts.Cost = func(string, V) int64 { return 1 }
	}
	if opts.NewPolicy == nil {
		opts.NewPolicy = NewLRU
	}
	if opts.Clock == nil {
		opts.Clock = time.Now
	}
	if opts.WatchBuffer <= 0 {
		opts.WatchBuffer = 64
	}
	// Capacity is split evenly. With >1 shard eviction is per-shard, i.e. an
	// approximation of global LRU/LFU: the price of not having a global lock.
	var perShard int64
	if opts.MaxCost > 0 {
		perShard = (opts.MaxCost + int64(opts.Shards) - 1) / int64(opts.Shards)
	}
	s := &Store[V]{
		shards:   make([]*shard[V], opts.Shards),
		seed:     maphash.MakeSeed(),
		cost:     opts.Cost,
		now:      opts.Clock,
		watchSz:  opts.WatchBuffer,
		watchers: make(map[*watcher[V]]struct{}),
	}
	for i := range s.shards {
		s.shards[i] = &shard[V]{items: make(map[string]*entry[V]), policy: opts.NewPolicy(), maxCost: perShard}
	}
	return s
}

func (s *Store[V]) shardFor(key string) *shard[V] {
	return s.shards[maphash.String(s.seed, key)%uint64(len(s.shards))]
}

// ---- internal, all called with sh.mu held ----

func (s *Store[V]) removeLocked(sh *shard[V], e *entry[V]) {
	delete(sh.items, e.key)
	sh.cost -= e.cost
	sh.policy.OnRemove(e.key)
	if e.heapIdx >= 0 {
		heap.Remove(&sh.expiry, e.heapIdx)
	}
}

// liveLocked returns the entry for key, lazily expiring it if its TTL passed.
func (s *Store[V]) liveLocked(sh *shard[V], key string, now time.Time) (*entry[V], bool) {
	e, ok := sh.items[key]
	if !ok {
		return nil, false
	}
	if e.expired(now) {
		s.expireLocked(sh, e)
		return nil, false
	}
	return e, true
}

func (s *Store[V]) expireLocked(sh *shard[V], e *entry[V]) {
	s.removeLocked(sh, e)
	s.expirations.Add(1)
	s.publish(Event[V]{Type: EventExpire, Key: e.key, Value: e.value, Version: e.version})
}

// purgeExpiredLocked pops every entry whose deadline has passed.
func (s *Store[V]) purgeExpiredLocked(sh *shard[V], now time.Time) int {
	n := 0
	for sh.expiry.Len() > 0 && sh.expiry[0].expired(now) {
		s.expireLocked(sh, sh.expiry[0])
		n++
	}
	return n
}

// putLocked inserts or replaces key. A replace is "remove + insert" for the
// eviction policy, which guarantees the key being written is never its own
// eviction victim.
func (s *Store[V]) putLocked(sh *shard[V], key string, v V, expiresAt time.Time, version uint64, now time.Time) error {
	cost := s.cost(key, v)
	if sh.maxCost > 0 && cost > sh.maxCost {
		return ErrTooLarge // checked before touching the old value: failed write changes nothing
	}
	if old, ok := sh.items[key]; ok {
		s.removeLocked(sh, old)
	}
	if sh.maxCost > 0 && sh.cost+cost > sh.maxCost {
		s.purgeExpiredLocked(sh, now) // reclaim dead entries before evicting live ones
	}
	for sh.maxCost > 0 && sh.cost+cost > sh.maxCost {
		victim, ok := sh.policy.Victim()
		if !ok {
			break
		}
		e := sh.items[victim]
		s.removeLocked(sh, e)
		s.evictions.Add(1)
		s.publish(Event[V]{Type: EventEvict, Key: e.key, Value: e.value, Version: e.version})
	}
	e := &entry[V]{key: key, value: v, version: version, expiresAt: expiresAt, cost: cost, heapIdx: -1}
	if !expiresAt.IsZero() {
		heap.Push(&sh.expiry, e)
	}
	sh.items[key] = e
	sh.cost += cost
	sh.policy.OnInsert(key)
	s.publish(Event[V]{Type: EventSet, Key: key, Value: v, Version: version})
	return nil
}

func deadline(now time.Time, ttl time.Duration) time.Time {
	if ttl <= 0 {
		return time.Time{}
	}
	return now.Add(ttl)
}

// ---- public API ----

// Set stores v under key. ttl <= 0 means no expiry. Returns the new version.
func (s *Store[V]) Set(key string, v V, ttl time.Duration) (uint64, error) {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	now := s.now()
	ver := s.version.Add(1)
	if err := s.putLocked(sh, key, v, deadline(now, ttl), ver, now); err != nil {
		return 0, err
	}
	return ver, nil
}

func (s *Store[V]) Get(key string) (V, bool) {
	v, _, ok := s.GetVersioned(key)
	return v, ok
}

// GetVersioned returns the value and its version, for a later CompareAndSwap.
func (s *Store[V]) GetVersioned(key string) (V, uint64, bool) {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	e, ok := s.liveLocked(sh, key, s.now())
	if !ok {
		s.misses.Add(1)
		var zero V
		return zero, 0, false
	}
	sh.policy.OnAccess(key)
	s.hits.Add(1)
	return e.value, e.version, true
}

func (s *Store[V]) Delete(key string) bool {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	e, ok := s.liveLocked(sh, key, s.now())
	if !ok {
		return false
	}
	s.removeLocked(sh, e)
	s.publish(Event[V]{Type: EventDelete, Key: key, Value: e.value, Version: e.version})
	return true
}

// CompareAndSwap writes v only if key's current version equals expected.
// expected == 0 means "only if absent" (SETNX). Returns the new version.
func (s *Store[V]) CompareAndSwap(key string, expected uint64, v V, ttl time.Duration) (uint64, error) {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	now := s.now()
	e, exists := s.liveLocked(sh, key, now)
	switch {
	case expected == 0 && exists:
		return 0, ErrVersionMismatch
	case expected != 0 && !exists:
		return 0, ErrNotFound
	case exists && e.version != expected:
		return 0, ErrVersionMismatch
	}
	ver := s.version.Add(1)
	if err := s.putLocked(sh, key, v, deadline(now, ttl), ver, now); err != nil {
		return 0, err
	}
	return ver, nil
}

// Expire sets a new TTL on an existing key. ttl <= 0 expires it immediately
// (Redis EXPIRE semantics). Returns false if the key does not exist.
func (s *Store[V]) Expire(key string, ttl time.Duration) bool {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	now := s.now()
	e, ok := s.liveLocked(sh, key, now)
	if !ok {
		return false
	}
	if ttl <= 0 {
		s.expireLocked(sh, e)
		return true
	}
	e.expiresAt = now.Add(ttl)
	if e.heapIdx >= 0 {
		heap.Fix(&sh.expiry, e.heapIdx)
	} else {
		heap.Push(&sh.expiry, e)
	}
	return true
}

// Persist removes key's TTL. Returns false if the key does not exist.
func (s *Store[V]) Persist(key string) bool {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	e, ok := s.liveLocked(sh, key, s.now())
	if !ok {
		return false
	}
	if e.heapIdx >= 0 {
		heap.Remove(&sh.expiry, e.heapIdx)
	}
	e.expiresAt = time.Time{}
	return true
}

// TTL returns the remaining time to live, NoTTL for a persistent key, and
// false if the key does not exist.
func (s *Store[V]) TTL(key string) (time.Duration, bool) {
	sh := s.shardFor(key)
	sh.mu.Lock()
	defer sh.mu.Unlock()
	now := s.now()
	e, ok := s.liveLocked(sh, key, now)
	if !ok {
		return 0, false
	}
	if e.expiresAt.IsZero() {
		return NoTTL, true
	}
	return e.expiresAt.Sub(now), true
}

// Keys returns the live keys with the given prefix, sorted.
func (s *Store[V]) Keys(prefix string) []string {
	now := s.now()
	var keys []string
	for _, sh := range s.shards {
		sh.mu.Lock()
		for k, e := range sh.items {
			if strings.HasPrefix(k, prefix) && !e.expired(now) {
				keys = append(keys, k)
			}
		}
		sh.mu.Unlock()
	}
	sort.Strings(keys)
	return keys
}

// DeleteExpired actively removes expired keys from every shard (one shard
// lock at a time, so writers to other shards are never blocked).
func (s *Store[V]) DeleteExpired() int {
	n := 0
	for _, sh := range s.shards {
		sh.mu.Lock()
		n += s.purgeExpiredLocked(sh, s.now())
		sh.mu.Unlock()
	}
	return n
}

// RunJanitor calls DeleteExpired every interval until ctx is cancelled.
// It blocks; the caller owns the goroutine: `go store.RunJanitor(ctx, d)`.
func (s *Store[V]) RunJanitor(ctx context.Context, interval time.Duration) error {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			s.DeleteExpired()
		}
	}
}

// Watch streams events for keys with the given prefix ("" = all keys).
// The store owns the channel and closes it once ctx is cancelled.
func (s *Store[V]) Watch(ctx context.Context, prefix string) <-chan Event[V] {
	w := &watcher[V]{prefix: prefix, ch: make(chan Event[V], s.watchSz)}
	s.watchMu.Lock()
	s.watchers[w] = struct{}{}
	s.watchMu.Unlock()
	context.AfterFunc(ctx, func() {
		s.watchMu.Lock() // excludes publish, so no send on a closed channel
		delete(s.watchers, w)
		close(w.ch)
		s.watchMu.Unlock()
	})
	return w.ch
}

// publish is called with the key's shard lock held, so events for one key
// are delivered in version order. It never blocks: a full buffer drops.
func (s *Store[V]) publish(ev Event[V]) {
	s.watchMu.RLock()
	defer s.watchMu.RUnlock()
	for w := range s.watchers {
		if !strings.HasPrefix(ev.Key, w.prefix) {
			continue
		}
		select {
		case w.ch <- ev:
		default:
			s.dropped.Add(1)
		}
	}
}

func (s *Store[V]) Stats() Stats {
	st := Stats{
		Hits: s.hits.Load(), Misses: s.misses.Load(), Evictions: s.evictions.Load(),
		Expirations: s.expirations.Load(), DroppedEvents: s.dropped.Load(),
	}
	for _, sh := range s.shards {
		sh.mu.Lock()
		st.Items += len(sh.items) // includes expired-but-not-yet-collected keys
		st.Cost += sh.cost
		sh.mu.Unlock()
	}
	return st
}

// ---- Snapshot / Restore ----

type snapshotRecord[V any] struct {
	Key       string     `json:"key"`
	Value     V          `json:"value"`
	Version   uint64     `json:"version"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"`
}

// Snapshot writes all live entries as JSON. Shards are copied one at a time
// and encoding happens outside the locks, so it is consistent per shard, not
// a point-in-time image of the whole store (fine for a cache; a database
// would need copy-on-write or a WAL position).
func (s *Store[V]) Snapshot(w io.Writer) error {
	now := s.now()
	var recs []snapshotRecord[V]
	for _, sh := range s.shards {
		sh.mu.Lock()
		for _, e := range sh.items {
			if e.expired(now) {
				continue
			}
			r := snapshotRecord[V]{Key: e.key, Value: e.value, Version: e.version}
			if !e.expiresAt.IsZero() {
				t := e.expiresAt
				r.ExpiresAt = &t
			}
			recs = append(recs, r)
		}
		sh.mu.Unlock()
	}
	sort.Slice(recs, func(i, j int) bool { return recs[i].Key < recs[j].Key })
	return json.NewEncoder(w).Encode(recs)
}

// Restore loads a snapshot, skipping entries that expired in the meantime.
// Versions are preserved and the revision counter is advanced past them so
// a CAS issued before the restart cannot succeed against a different value.
func (s *Store[V]) Restore(r io.Reader) error {
	var recs []snapshotRecord[V]
	if err := json.NewDecoder(r).Decode(&recs); err != nil {
		return fmt.Errorf("restore: %w", err)
	}
	now := s.now()
	for _, rec := range recs {
		var exp time.Time
		if rec.ExpiresAt != nil {
			if !now.Before(*rec.ExpiresAt) {
				continue
			}
			exp = *rec.ExpiresAt
		}
		for { // version = max(version, rec.Version)
			cur := s.version.Load()
			if cur >= rec.Version || s.version.CompareAndSwap(cur, rec.Version) {
				break
			}
		}
		sh := s.shardFor(rec.Key)
		sh.mu.Lock()
		err := s.putLocked(sh, rec.Key, rec.Value, exp, rec.Version, now)
		sh.mu.Unlock()
		if err != nil {
			return fmt.Errorf("restore %q: %w", rec.Key, err)
		}
	}
	return nil
}

// ============================================================
// MANUAL CLOCK (deterministic demo and tests)
// ============================================================

type ManualClock struct {
	mu sync.Mutex
	t  time.Time
}

func NewManualClock(t time.Time) *ManualClock { return &ManualClock{t: t} }
func (c *ManualClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}
func (c *ManualClock) Advance(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

// ============================================================
// DEMO
// ============================================================

func main() {
	clock := NewManualClock(time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC))

	fmt.Println("--- LRU eviction (capacity 3) ---")
	lru := NewStore(Options[string]{MaxCost: 3, Clock: clock.Now})
	lru.Set("a", "1", 0)
	lru.Set("b", "2", 0)
	lru.Set("c", "3", 0)
	lru.Get("a") // a is now most recently used, b is LRU
	lru.Set("d", "4", 0)
	fmt.Println("  keys after inserting d:", lru.Keys(""), "(b evicted)")

	fmt.Println("--- LFU eviction (capacity 2) ---")
	lfu := NewStore(Options[string]{MaxCost: 2, NewPolicy: NewLFU, Clock: clock.Now})
	lfu.Set("hot", "h", 0)
	lfu.Set("cold", "c", 0)
	lfu.Get("hot")
	lfu.Get("hot")
	lfu.Set("new", "n", 0)
	fmt.Println("  keys after inserting new:", lfu.Keys(""), "(cold evicted)")

	fmt.Println("--- TTL with an injected clock ---")
	s := NewStore(Options[int]{Shards: 4, Clock: clock.Now})
	s.Set("session:1", 1, 30*time.Second)
	s.Set("session:2", 2, 90*time.Second)
	s.Set("session:3", 3, 10*time.Second)
	ttl, _ := s.TTL("session:1")
	fmt.Println("  session:1 TTL:", ttl)
	clock.Advance(time.Minute)
	_, ok := s.Get("session:1")
	fmt.Println("  after 60s: session:1 present?", ok, "(lazy expiry on read)")
	fmt.Println("  janitor pass removed:", s.DeleteExpired(), "(session:3, never read)")
	s.Persist("session:2")
	ttl, _ = s.TTL("session:2")
	fmt.Println("  session:2 persisted, TTL == NoTTL?", ttl == NoTTL)

	fmt.Println("--- CAS: 8 goroutines x 100 increments ---")
	counter := NewStore(Options[int]{Shards: 4})
	counter.Set("hits", 0, 0)
	var wg sync.WaitGroup
	for g := 0; g < 8; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 100; i++ {
				for { // optimistic retry loop
					v, ver, _ := counter.GetVersioned("hits")
					if _, err := counter.CompareAndSwap("hits", ver, v+1, 0); err == nil {
						break
					}
				}
			}
		}()
	}
	wg.Wait()
	v, _ := counter.Get("hits")
	fmt.Println("  hits =", v)
	_, err := counter.CompareAndSwap("hits", 1, 0, 0)
	fmt.Println("  stale CAS:", err)

	fmt.Println("--- Watch ---")
	ctx, cancel := context.WithCancel(context.Background())
	events := s.Watch(ctx, "user:")
	s.Set("user:1", 100, 0)
	s.Set("order:1", 5, 0) // filtered out by prefix
	s.Delete("user:1")
	cancel()
	for ev := range events { // the store closes the channel after cancel
		fmt.Printf("  %s %s=%d (v%d)\n", ev.Type, ev.Key, ev.Value, ev.Version)
	}

	fmt.Println("--- Snapshot / Restore ---")
	f, err := os.CreateTemp("", "kvstore-*.json")
	if err != nil {
		fmt.Println("  temp file:", err)
		return
	}
	defer os.Remove(f.Name())
	if err := s.Snapshot(f); err != nil {
		fmt.Println("  snapshot:", err)
	}
	f.Seek(0, io.SeekStart)
	restored := NewStore(Options[int]{Clock: clock.Now})
	if err := restored.Restore(f); err != nil {
		fmt.Println("  restore:", err)
	}
	f.Close()
	fmt.Println("  restored keys:", restored.Keys(""))
	fmt.Printf("  stats: %+v\n", s.Stats())
}
```
<!-- /source -->
