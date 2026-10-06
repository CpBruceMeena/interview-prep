package main

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"runtime"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func noBackoff(int) time.Duration { return time.Millisecond }

func waitAll(t *testing.T, q *Queue, ids ...string) map[string]TaskResult {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	out := make(map[string]TaskResult)
	for _, id := range ids {
		r, err := q.Wait(ctx, id)
		if err != nil {
			t.Fatalf("Wait(%s): %v", id, err)
		}
		out[id] = r
	}
	return out
}

// recorder is a handler that records the order payloads were processed in.
type recorder struct {
	mu    sync.Mutex
	order []string
}

func (r *recorder) Handle(_ context.Context, p any) (any, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.order = append(r.order, p.(string))
	return p, nil
}

func TestPriorityThenFIFO(t *testing.T) {
	rec := &recorder{}
	q := New(Options{Workers: 1, Handlers: map[string]Handler{"r": rec}})
	for _, s := range []struct {
		id string
		p  Priority
	}{{"l1", PriorityLow}, {"n1", PriorityNormal}, {"c1", PriorityCritical}, {"n2", PriorityNormal}, {"l2", PriorityLow}, {"c2", PriorityCritical}} {
		if _, err := q.Submit(TaskSpec{ID: s.id, Type: "r", Payload: s.id, Priority: s.p}); err != nil {
			t.Fatal(err)
		}
	}
	q.Start()
	if err := q.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	if want := []string{"c1", "c2", "n1", "n2", "l1", "l2"}; !reflect.DeepEqual(rec.order, want) {
		t.Fatalf("order = %v, want %v", rec.order, want)
	}
}

func TestSubmitValidationAndIdempotency(t *testing.T) {
	rec := &recorder{}
	q := New(Options{Workers: 1, Handlers: map[string]Handler{"r": rec}})
	if _, err := q.Submit(TaskSpec{Type: "nope"}); !errors.Is(err, ErrUnknownHandler) {
		t.Fatalf("err = %v", err)
	}
	if _, err := q.Submit(TaskSpec{Type: "r", DependsOn: []string{"ghost"}}); !errors.Is(err, ErrUnknownDependency) {
		t.Fatalf("err = %v", err)
	}
	q.Submit(TaskSpec{ID: "a", Type: "r", Payload: "first"})
	q.Submit(TaskSpec{ID: "a", Type: "r", Payload: "second"})
	q.Start()
	q.Shutdown(context.Background())
	if !reflect.DeepEqual(rec.order, []string{"first"}) {
		t.Fatalf("duplicate ID ran twice: %v", rec.order)
	}
	if _, err := q.Submit(TaskSpec{Type: "r"}); !errors.Is(err, ErrClosed) {
		t.Fatalf("submit after shutdown: %v", err)
	}
}

func TestRetriesBackoffAndDeadLetter(t *testing.T) {
	var calls atomic.Int32
	var backoffs []int
	var bmu sync.Mutex
	q := New(Options{
		Workers: 2,
		Backoff: func(a int) time.Duration {
			bmu.Lock()
			backoffs = append(backoffs, a)
			bmu.Unlock()
			return time.Millisecond
		},
		Handlers: map[string]Handler{
			"fail": HandlerFunc(func(context.Context, any) (any, error) { calls.Add(1); return nil, errors.New("boom") }),
			"perm": HandlerFunc(func(context.Context, any) (any, error) { return nil, Permanent(errors.New("bad input")) }),
		},
	})
	q.Start()
	q.Submit(TaskSpec{ID: "f", Type: "fail", MaxAttempts: 4})
	q.Submit(TaskSpec{ID: "p", Type: "perm", MaxAttempts: 4})
	res := waitAll(t, q, "f", "p")
	if r := res["f"]; r.Status != StatusFailed || r.Attempts != 4 || calls.Load() != 4 {
		t.Fatalf("f = %+v calls=%d", r, calls.Load())
	}
	if r := res["p"]; r.Status != StatusFailed || r.Attempts != 1 {
		t.Fatalf("permanent error was retried: %+v", r)
	}
	if !reflect.DeepEqual(backoffs, []int{1, 2, 3}) {
		t.Fatalf("backoff attempts = %v", backoffs)
	}
	if dl := q.DeadLetters(); len(dl) != 2 {
		t.Fatalf("dead letters = %v", dl)
	}
	q.Shutdown(context.Background())
}

func TestExponentialBackoffBounds(t *testing.T) {
	b := ExponentialBackoff(10*time.Millisecond, 50*time.Millisecond)
	for i := 0; i < 200; i++ {
		for a, max := range map[int]time.Duration{1: 10 * time.Millisecond, 3: 40 * time.Millisecond, 10: 50 * time.Millisecond, 100: 50 * time.Millisecond} {
			if d := b(a); d < 0 || d > max {
				t.Fatalf("attempt %d: %v outside [0,%v]", a, d, max)
			}
		}
	}
}

func TestPanicIsContained(t *testing.T) {
	q := New(Options{Workers: 1, Handlers: map[string]Handler{
		"panic": HandlerFunc(func(context.Context, any) (any, error) { panic("kaboom") }),
		"ok":    HandlerFunc(func(context.Context, any) (any, error) { return "fine", nil }),
	}})
	q.Start()
	q.Submit(TaskSpec{ID: "p", Type: "panic", MaxAttempts: 3})
	q.Submit(TaskSpec{ID: "ok", Type: "ok"})
	res := waitAll(t, q, "p", "ok")
	if res["p"].Status != StatusFailed || res["p"].Attempts != 1 || res["ok"].Status != StatusSucceeded {
		t.Fatalf("results = %+v", res)
	}
	q.Shutdown(context.Background())
}

func TestDependenciesRunInOrderAndCascadeFailure(t *testing.T) {
	rec := &recorder{}
	q := New(Options{Workers: 4, Backoff: noBackoff, Handlers: map[string]Handler{
		"r":    rec,
		"fail": HandlerFunc(func(context.Context, any) (any, error) { return nil, Permanent(errors.New("x")) }),
	}})
	// Submit the whole DAG before starting so order is decided only by deps.
	q.Submit(TaskSpec{ID: "a", Type: "r", Payload: "a"})
	q.Submit(TaskSpec{ID: "b", Type: "r", Payload: "b", DependsOn: []string{"a"}})
	q.Submit(TaskSpec{ID: "c", Type: "r", Payload: "c", DependsOn: []string{"a", "b"}})
	q.Submit(TaskSpec{ID: "bad", Type: "fail"})
	q.Submit(TaskSpec{ID: "child", Type: "r", Payload: "child", DependsOn: []string{"bad"}})
	q.Submit(TaskSpec{ID: "grandchild", Type: "r", Payload: "gc", DependsOn: []string{"child", "a"}})
	q.Start()
	res := waitAll(t, q, "a", "b", "c", "bad", "child", "grandchild")
	if !reflect.DeepEqual(rec.order, []string{"a", "b", "c"}) {
		t.Fatalf("order = %v", rec.order)
	}
	for _, id := range []string{"child", "grandchild"} {
		if r := res[id]; r.Status != StatusCancelled || !errors.Is(r.Err, ErrDependencyFailed) {
			t.Fatalf("%s = %+v", id, r)
		}
	}
	// Depending on an already-failed task cancels immediately.
	q.Submit(TaskSpec{ID: "late", Type: "r", DependsOn: []string{"bad"}})
	if r := waitAll(t, q, "late")["late"]; r.Status != StatusCancelled {
		t.Fatalf("late = %+v", r)
	}
	q.Shutdown(context.Background())
}

func TestCancelQueuedAndRunning(t *testing.T) {
	started := make(chan struct{})
	q := New(Options{Workers: 1, Handlers: map[string]Handler{
		"block": HandlerFunc(func(ctx context.Context, _ any) (any, error) {
			close(started)
			<-ctx.Done()
			return nil, ctx.Err()
		}),
		"r": &recorder{},
	}})
	q.Start()
	q.Submit(TaskSpec{ID: "running", Type: "block", MaxAttempts: 5})
	<-started
	q.Submit(TaskSpec{ID: "queued", Type: "r", Payload: "q"})
	q.Submit(TaskSpec{ID: "dependent", Type: "r", Payload: "d", DependsOn: []string{"running"}})
	if err := q.Cancel("queued"); err != nil {
		t.Fatal(err)
	}
	if err := q.Cancel("running"); err != nil {
		t.Fatal(err)
	}
	res := waitAll(t, q, "running", "queued", "dependent")
	for id, r := range res {
		if r.Status != StatusCancelled {
			t.Fatalf("%s = %+v", id, r)
		}
	}
	if res["running"].Attempts != 1 {
		t.Fatalf("cancelled task was retried: %+v", res["running"])
	}
	if err := q.Cancel("running"); !errors.Is(err, ErrAlreadyFinished) {
		t.Fatalf("second cancel: %v", err)
	}
	if err := q.Cancel("nope"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("unknown cancel: %v", err)
	}
	q.Shutdown(context.Background())
}

func TestDelayedTaskRunsAfterRunAt(t *testing.T) {
	rec := &recorder{}
	q := New(Options{Workers: 2, Handlers: map[string]Handler{"r": rec}})
	q.Start()
	start := time.Now()
	q.Submit(TaskSpec{ID: "later", Type: "r", Payload: "later", RunAt: start.Add(40 * time.Millisecond)})
	q.Submit(TaskSpec{ID: "now", Type: "r", Payload: "now"})
	waitAll(t, q, "later")
	if el := time.Since(start); el < 40*time.Millisecond {
		t.Fatalf("delayed task ran after %v", el)
	}
	if !reflect.DeepEqual(rec.order, []string{"now", "later"}) {
		t.Fatalf("order = %v", rec.order)
	}
	q.Shutdown(context.Background())
}

func TestShutdownDrainsIncludingRetries(t *testing.T) {
	var calls atomic.Int32
	q := New(Options{Workers: 2, Backoff: func(int) time.Duration { return 10 * time.Millisecond }, Handlers: map[string]Handler{
		"flaky": HandlerFunc(func(context.Context, any) (any, error) {
			if calls.Add(1) < 3 {
				return nil, errors.New("again")
			}
			return "done", nil
		}),
	}})
	q.Start()
	q.Submit(TaskSpec{ID: "f", Type: "flaky", MaxAttempts: 5})
	if err := q.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	if r := waitAll(t, q, "f")["f"]; r.Status != StatusSucceeded || r.Attempts != 3 {
		t.Fatalf("f = %+v", r)
	}
}

func TestShutdownDeadlineCancelsEverything(t *testing.T) {
	q := New(Options{Workers: 1, Handlers: map[string]Handler{
		"block": HandlerFunc(func(ctx context.Context, _ any) (any, error) { <-ctx.Done(); return nil, ctx.Err() }),
	}})
	q.Start()
	q.Submit(TaskSpec{ID: "a", Type: "block"})
	q.Submit(TaskSpec{ID: "b", Type: "block"})
	q.Submit(TaskSpec{ID: "c", Type: "block", RunAt: time.Now().Add(time.Hour)})
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := q.Shutdown(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("shutdown err = %v", err)
	}
	for id, r := range waitAll(t, q, "a", "b", "c") {
		if r.Status != StatusCancelled {
			t.Fatalf("%s = %+v", id, r)
		}
	}
}

func TestConcurrentSubmitStress(t *testing.T) {
	before := runtime.NumGoroutine()
	var ran atomic.Int64
	q := New(Options{Workers: 8, Backoff: noBackoff, Handlers: map[string]Handler{
		"work": HandlerFunc(func(_ context.Context, p any) (any, error) {
			ran.Add(1)
			if p.(int)%7 == 0 {
				return nil, errors.New("retry me") // every 7th fails on all attempts
			}
			return p, nil
		}),
	}})
	q.Start()
	const producers, perProducer = 8, 250
	var wg sync.WaitGroup
	for g := 0; g < producers; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < perProducer; i++ {
				n := g*perProducer + i
				spec := TaskSpec{ID: fmt.Sprint(n), Type: "work", Payload: n, MaxAttempts: 2, Priority: Priority(n % 4)}
				if n%5 == 0 && n > 0 {
					spec.DependsOn = []string{fmt.Sprint(n - 1)} // may or may not exist yet
				}
				if _, err := q.Submit(spec); err != nil && !errors.Is(err, ErrUnknownDependency) {
					t.Errorf("submit: %v", err)
				}
			}
		}(g)
	}
	wg.Wait()
	if err := q.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	st := q.Stats()
	terminal := st.ByStatus[StatusSucceeded] + st.ByStatus[StatusFailed] + st.ByStatus[StatusCancelled]
	if total := len(q.tasks); terminal != total {
		t.Fatalf("non-terminal tasks after drain: %+v", st.ByStatus)
	}
	if st.DeadLetters != st.ByStatus[StatusFailed] {
		t.Fatalf("dead letters %d != failed %d", st.DeadLetters, st.ByStatus[StatusFailed])
	}
	// All worker goroutines must be gone.
	deadline := time.Now().Add(time.Second)
	for runtime.NumGoroutine() > before && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if n := runtime.NumGoroutine(); n > before {
		t.Fatalf("goroutine leak: %d before, %d after", before, n)
	}
}
