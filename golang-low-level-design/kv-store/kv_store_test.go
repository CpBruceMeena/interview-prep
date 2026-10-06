package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

func newClock() *ManualClock { return NewManualClock(time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)) }

func TestLRUEvictsLeastRecentlyUsed(t *testing.T) {
	s := NewStore(Options[int]{MaxCost: 2})
	s.Set("a", 1, 0)
	s.Set("b", 2, 0)
	s.Get("a")
	s.Set("c", 3, 0)
	if got := s.Keys(""); !reflect.DeepEqual(got, []string{"a", "c"}) {
		t.Fatalf("keys = %v, want [a c]", got)
	}
	if s.Stats().Evictions != 1 {
		t.Fatalf("evictions = %d", s.Stats().Evictions)
	}
}

func TestOverwriteNeverEvictsItself(t *testing.T) {
	s := NewStore(Options[int]{MaxCost: 2})
	s.Set("a", 1, 0)
	s.Set("b", 2, 0)
	s.Set("a", 10, 0) // at capacity, but replacing: nothing should be evicted
	if got := s.Keys(""); !reflect.DeepEqual(got, []string{"a", "b"}) {
		t.Fatalf("keys = %v", got)
	}
	if st := s.Stats(); st.Cost != 2 || st.Evictions != 0 {
		t.Fatalf("stats = %+v", st)
	}
}

func TestLFUEvictsLeastFrequentlyUsedWithLRUTieBreak(t *testing.T) {
	s := NewStore(Options[int]{MaxCost: 3, NewPolicy: NewLFU})
	s.Set("a", 1, 0)
	s.Set("b", 2, 0)
	s.Set("c", 3, 0)
	s.Get("a")
	s.Get("a")
	s.Get("c") // freqs: a=3 b=1 c=2
	s.Set("d", 4, 0)
	if got := s.Keys(""); !reflect.DeepEqual(got, []string{"a", "c", "d"}) {
		t.Fatalf("keys = %v, want b evicted", got)
	}
	s.Set("e", 5, 0) // d=1 and e is new; d is the only freq-1 key
	if got := s.Keys(""); !reflect.DeepEqual(got, []string{"a", "c", "e"}) {
		t.Fatalf("keys = %v, want d evicted", got)
	}
}

func TestLFURepairsMinFreqAfterRemove(t *testing.T) {
	p := NewLFU()
	p.OnInsert("x")
	p.OnInsert("y")
	p.OnAccess("y")
	p.OnRemove("x") // minFreq (1) now points at a missing bucket
	if k, ok := p.Victim(); !ok || k != "y" {
		t.Fatalf("victim = %q %v, want y", k, ok)
	}
}

func TestTooLargeLeavesOldValue(t *testing.T) {
	s := NewStore(Options[string]{MaxCost: 4, Cost: func(_ string, v string) int64 { return int64(len(v)) }})
	s.Set("k", "ok", 0)
	if _, err := s.Set("k", "too-long", 0); !errors.Is(err, ErrTooLarge) {
		t.Fatalf("err = %v", err)
	}
	if v, _ := s.Get("k"); v != "ok" {
		t.Fatalf("old value lost: %q", v)
	}
}

func TestTTLLazyAndActiveExpiry(t *testing.T) {
	c := newClock()
	s := NewStore(Options[int]{Clock: c.Now, Shards: 4})
	s.Set("short", 1, time.Second)
	s.Set("long", 2, time.Hour)
	s.Set("forever", 3, 0)
	c.Advance(2 * time.Second)
	if _, ok := s.Get("short"); ok {
		t.Fatal("short should be expired on read")
	}
	if n := s.DeleteExpired(); n != 0 {
		t.Fatalf("janitor removed %d, want 0 (already lazily removed)", n)
	}
	c.Advance(2 * time.Hour)
	if n := s.DeleteExpired(); n != 1 {
		t.Fatalf("janitor removed %d, want 1", n)
	}
	if got := s.Keys(""); !reflect.DeepEqual(got, []string{"forever"}) {
		t.Fatalf("keys = %v", got)
	}
}

func TestExpirePersistAndOverwriteClearTTL(t *testing.T) {
	c := newClock()
	s := NewStore(Options[int]{Clock: c.Now})
	s.Set("k", 1, time.Minute)
	if !s.Expire("k", time.Hour) {
		t.Fatal("Expire on live key")
	}
	if d, _ := s.TTL("k"); d != time.Hour {
		t.Fatalf("ttl = %v", d)
	}
	s.Persist("k")
	if d, ok := s.TTL("k"); !ok || d != NoTTL {
		t.Fatalf("ttl = %v %v", d, ok)
	}
	s.Set("j", 1, time.Minute)
	s.Set("j", 2, 0) // overwrite without TTL must drop the old deadline
	c.Advance(time.Hour)
	if _, ok := s.Get("j"); !ok {
		t.Fatal("overwritten key expired with its old TTL")
	}
	if !s.Expire("j", 0) {
		t.Fatal("Expire(0) should expire immediately")
	}
	if _, ok := s.Get("j"); ok || s.Expire("missing", time.Second) {
		t.Fatal("expected j gone and missing key to report false")
	}
}

func TestCompareAndSwap(t *testing.T) {
	s := NewStore(Options[string]{})
	v1, err := s.CompareAndSwap("k", 0, "a", 0) // create-if-absent
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.CompareAndSwap("k", 0, "b", 0); !errors.Is(err, ErrVersionMismatch) {
		t.Fatalf("SETNX on existing key: %v", err)
	}
	if _, err := s.CompareAndSwap("missing", 5, "b", 0); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	// ABA: delete and recreate must yield a different version.
	s.Delete("k")
	s.Set("k", "a", 0)
	if _, err := s.CompareAndSwap("k", v1, "c", 0); !errors.Is(err, ErrVersionMismatch) {
		t.Fatalf("ABA CAS succeeded: %v", err)
	}
}

func TestWatchDeliversFiltersAndCloses(t *testing.T) {
	s := NewStore(Options[int]{MaxCost: 1})
	ctx, cancel := context.WithCancel(context.Background())
	ch := s.Watch(ctx, "u:")
	s.Set("u:1", 1, 0)
	s.Set("x", 9, 0) // evicts u:1; the set of x is filtered out
	cancel()
	var got []string
	for ev := range ch {
		got = append(got, ev.Type.String()+" "+ev.Key)
	}
	if want := []string{"SET u:1", "EVICT u:1"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("events = %v, want %v", got, want)
	}
}

func TestSlowWatcherDropsInsteadOfBlocking(t *testing.T) {
	s := NewStore(Options[int]{WatchBuffer: 1})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	_ = s.Watch(ctx, "")
	for i := 0; i < 5; i++ {
		s.Set("k", i, 0) // must not block
	}
	if d := s.Stats().DroppedEvents; d != 4 {
		t.Fatalf("dropped = %d, want 4", d)
	}
}

func TestSnapshotRestoreRoundTrip(t *testing.T) {
	c := newClock()
	s := NewStore(Options[map[string]int]{Clock: c.Now, Shards: 3})
	s.Set("a", map[string]int{"x": 1}, 0)
	s.Set("b", map[string]int{"y": 2}, time.Minute)
	verB, _ := s.Set("b", map[string]int{"y": 3}, time.Minute)
	s.Set("gone", nil, time.Second)
	var buf bytes.Buffer
	if err := s.Snapshot(&buf); err != nil {
		t.Fatal(err)
	}
	c.Advance(2 * time.Second) // "gone" expires between snapshot and restore
	r := NewStore(Options[map[string]int]{Clock: c.Now})
	if err := r.Restore(&buf); err != nil {
		t.Fatal(err)
	}
	if got := r.Keys(""); !reflect.DeepEqual(got, []string{"a", "b"}) {
		t.Fatalf("keys = %v", got)
	}
	v, ver, _ := r.GetVersioned("b")
	if v["y"] != 3 || ver != verB {
		t.Fatalf("b = %v v%d, want y=3 v%d", v, ver, verB)
	}
	if d, _ := r.TTL("b"); d != time.Minute-2*time.Second {
		t.Fatalf("ttl = %v", d)
	}
	// New writes must get versions above anything restored.
	if nv, _ := r.Set("c", nil, 0); nv <= verB {
		t.Fatalf("version %d not past restored %d", nv, verB)
	}
}

func TestConcurrentCASCounter(t *testing.T) {
	s := NewStore(Options[int]{Shards: 8})
	s.Set("n", 0, 0)
	const workers, perWorker = 16, 200
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < perWorker; i++ {
				for {
					v, ver, _ := s.GetVersioned("n")
					if _, err := s.CompareAndSwap("n", ver, v+1, 0); err == nil {
						break
					}
				}
			}
		}()
	}
	wg.Wait()
	if v, _ := s.Get("n"); v != workers*perWorker {
		t.Fatalf("n = %d, want %d", v, workers*perWorker)
	}
}

func TestConcurrentMixedOpsRespectCapacity(t *testing.T) {
	c := newClock()
	s := NewStore(Options[int]{Shards: 4, MaxCost: 64, Clock: c.Now})
	ctx, cancel := context.WithCancel(context.Background())
	events := s.Watch(ctx, "")
	drained := make(chan struct{})
	go func() { // a consumer that keeps up most of the time
		for range events {
		}
		close(drained)
	}()
	jctx, jcancel := context.WithCancel(context.Background())
	janitorDone := make(chan error)
	go func() { janitorDone <- s.RunJanitor(jctx, time.Millisecond) }()

	var wg sync.WaitGroup
	for g := 0; g < 8; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 500; i++ {
				k := fmt.Sprintf("k%d", (g*31+i)%200)
				switch i % 5 {
				case 0, 1:
					s.Set(k, i, time.Duration(i%3)*time.Second)
				case 2:
					s.Get(k)
				case 3:
					s.Delete(k)
				case 4:
					c.Advance(time.Millisecond)
					s.Expire(k, time.Second)
				}
			}
		}(g)
	}
	wg.Wait()
	for _, sh := range s.shards {
		sh.mu.Lock()
		var sum int64
		for _, e := range sh.items {
			sum += e.cost
		}
		if sh.cost != sum || sh.cost > sh.maxCost || sh.expiry.Len() > len(sh.items) {
			t.Errorf("shard invariant broken: cost=%d sum=%d max=%d heap=%d items=%d",
				sh.cost, sum, sh.maxCost, sh.expiry.Len(), len(sh.items))
		}
		sh.mu.Unlock()
	}
	jcancel()
	if err := <-janitorDone; !errors.Is(err, context.Canceled) {
		t.Fatalf("janitor returned %v", err)
	}
	cancel()
	select {
	case <-drained: // watch channel closed => consumer goroutine exited
	case <-time.After(time.Second):
		t.Fatal("watch channel not closed after cancel")
	}
}
