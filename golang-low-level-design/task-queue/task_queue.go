// Task Queue / Worker Pool - Low Level Design (Go)
// ---------------------------------------------------
// Design Principles: CSP, Worker Pool, Pipeline, Graceful Shutdown
//
// Key Design Decisions:
// - Worker pool pattern for concurrent task processing
// - Priority queue for task ordering (heap-based)
// - Context-based cancellation for graceful shutdown
// - Configurable retry with exponential backoff
// - Result collection via channel fan-in

package main

import (
	"container/heap"
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log"
	"math"
	"sync"
	"sync/atomic"
	"time"
)

// ============================================================
// TASK TYPES
// ============================================================

type TaskPriority int

const (
	PriorityLow    TaskPriority = 1
	PriorityNormal TaskPriority = 2
	PriorityHigh   TaskPriority = 3
	PriorityCritical TaskPriority = 4
)

type TaskStatus string

const (
	StatusPending   TaskStatus = "PENDING"
	StatusRunning   TaskStatus = "RUNNING"
	StatusCompleted TaskStatus = "COMPLETED"
	StatusFailed    TaskStatus = "FAILED"
	StatusRetrying  TaskStatus = "RETRYING"
	StatusCancelled TaskStatus = "CANCELLED"
)

// Task represents a unit of work to be processed
type Task struct {
	ID          string                 `json:"id"`
	Type        string                 `json:"type"`
	Payload     map[string]interface{} `json:"payload"`
	Priority    TaskPriority           `json:"priority"`
	Status      TaskStatus             `json:"status"`
	CreatedAt   time.Time              `json:"created_at"`
	ScheduledAt time.Time              `json:"scheduled_at,omitempty"`
	RetryCount  int                    `json:"retry_count"`
	MaxRetries  int                    `json:"max_retries"`
	Timeout     time.Duration          `json:"timeout"`
	Result      interface{}            `json:"result,omitempty"`
	Error       string                 `json:"error,omitempty"`
	index       int                    // For heap.Interface
}

// TaskResult represents the outcome of a processed task
type TaskResult struct {
	TaskID     string
	Status     TaskStatus
	Result     interface{}
	Error      string
	Duration   time.Duration
	RetryCount int
}

// ============================================================
// PRIORITY QUEUE (Min-Heap)
// ============================================================

// PriorityQueue implements heap.Interface with higher priority = sooner execution
// For equal priorities, FIFO ordering
type PriorityQueue []*Task

func (pq PriorityQueue) Len() int { return len(pq) }

func (pq PriorityQueue) Less(i, j int) bool {
	// Higher priority first (higher number = more important)
	if pq[i].Priority != pq[j].Priority {
		return pq[i].Priority > pq[j].Priority
	}
	// FIFO for same priority
	return pq[i].CreatedAt.Before(pq[j].CreatedAt)
}

func (pq PriorityQueue) Swap(i, j int) {
	pq[i], pq[j] = pq[j], pq[i]
	pq[i].index = i
	pq[j].index = j
}

func (pq *PriorityQueue) Push(x interface{}) {
	n := len(*pq)
	task := x.(*Task)
	task.index = n
	*pq = append(*pq, task)
}

func (pq *PriorityQueue) Pop() interface{} {
	old := *pq
	n := len(old)
	task := old[n-1]
	old[n-1] = nil
	task.index = -1
	*pq = old[:n-1]
	return task
}

// ============================================================
// TASK HANDLER (Strategy Pattern)
// ============================================================

// TaskHandler defines how a specific task type is processed
type TaskHandler interface {
	// Handle processes a task and returns result/error
	Handle(ctx context.Context, task *Task) (interface{}, error)
	// Type returns the task type this handler serves
	Type() string
}

// GenericHandler is a simple handler for demo purposes
type GenericHandler struct {
	taskType  string
	processFn func(context.Context, map[string]interface{}) (interface{}, error)
}

func NewGenericHandler(taskType string, fn func(context.Context, map[string]interface{}) (interface{}, error)) *GenericHandler {
	return &GenericHandler{
		taskType:  taskType,
		processFn: fn,
	}
}

func (h *GenericHandler) Handle(ctx context.Context, task *Task) (interface{}, error) {
	return h.processFn(ctx, task.Payload)
}

func (h *GenericHandler) Type() string { return h.taskType }

// ============================================================
// TASK QUEUE
// ============================================================

type TaskQueue struct {
	mu          sync.RWMutex
	pending     PriorityQueue      // Tasks waiting to be processed
	running     map[string]*Task   // Currently processing
	handlers    map[string]TaskHandler
	results     chan TaskResult
	stats       QueueStats
}

type QueueStats struct {
	Enqueued   atomic.Int64
	Completed  atomic.Int64
	Failed     atomic.Int64
	Retried    atomic.Int64
	Cancelled  atomic.Int64
	Running    atomic.Int64
}

func NewTaskQueue() *TaskQueue {
	return &TaskQueue{
		pending:  make(PriorityQueue, 0),
		running:  make(map[string]*Task),
		handlers: make(map[string]TaskHandler),
		results:  make(chan TaskResult, 1000),
	}
}

// RegisterHandler registers a handler for a task type
func (q *TaskQueue) RegisterHandler(handler TaskHandler) {
	q.mu.Lock()
	defer q.mu.Unlock()
	q.handlers[handler.Type()] = handler
}

// Enqueue adds a task to the queue
func (q *TaskQueue) Enqueue(task *Task) {
	q.mu.Lock()
	defer q.mu.Unlock()

	task.Status = StatusPending
	task.CreatedAt = time.Now()
	heap.Push(&q.pending, task)
	q.stats.Enqueued.Add(1)
	log.Printf("Enqueued task %s (type=%s, priority=%d)", task.ID, task.Type, task.Priority)
}

// Dequeue removes and returns the highest priority task
func (q *TaskQueue) Dequeue() *Task {
	q.mu.Lock()
	defer q.mu.Unlock()

	if q.pending.Len() == 0 {
		return nil
	}

	task := heap.Pop(&q.pending).(*Task)
	task.Status = StatusRunning
	q.running[task.ID] = task
	q.stats.Running.Add(1)
	return task
}

// Complete marks a task as completed
func (q *TaskQueue) Complete(taskID string, result interface{}) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if task, ok := q.running[taskID]; ok {
		task.Status = StatusCompleted
		task.Result = result
		delete(q.running, taskID)
		q.stats.Completed.Add(1)
		q.stats.Running.Add(-1)
	}
}

// Fail marks a task as failed (with optional retry)
func (q *TaskQueue) Fail(taskID string, err error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if task, ok := q.running[taskID]; ok {
		task.Error = err.Error()
		task.RetryCount++

		if task.RetryCount < task.MaxRetries {
			// Schedule retry with backoff
			task.Status = StatusRetrying
			backoff := time.Duration(math.Pow(2, float64(task.RetryCount))) * time.Second
			task.ScheduledAt = time.Now().Add(backoff)

			// Re-enqueue after backoff
			time.AfterFunc(backoff, func() {
				q.mu.Lock()
				task.Status = StatusPending
				heap.Push(&q.pending, task)
				q.stats.Retried.Add(1)
				q.mu.Unlock()
			})

			log.Printf("Task %s failed, retry %d/%d in %v", taskID, task.RetryCount, task.MaxRetries, backoff)
		} else {
			task.Status = StatusFailed
			log.Printf("Task %s failed permanently after %d retries: %v", taskID, task.RetryCount, err)
			q.stats.Failed.Add(1)
		}

		delete(q.running, taskID)
		q.stats.Running.Add(-1)
	}
}

// Cancel cancels a task
func (q *TaskQueue) Cancel(taskID string) {
	q.mu.Lock()
	defer q.mu.Unlock()

	// Check pending
	for i, task := range q.pending {
		if task.ID == taskID {
			task.Status = StatusCancelled
			heap.Remove(&q.pending, i)
			q.stats.Cancelled.Add(1)
			return
		}
	}

	// Check running
	if task, ok := q.running[taskID]; ok {
		task.Status = StatusCancelled
		delete(q.running, taskID)
		q.stats.Cancelled.Add(1)
		q.stats.Running.Add(-1)
	}
}

// Stats returns current queue statistics
func (q *TaskQueue) Stats() map[string]interface{} {
	q.mu.RLock()
	defer q.mu.RUnlock()

	return map[string]interface{}{
		"pending":   q.pending.Len(),
		"running":   len(q.running),
		"enqueued":  q.stats.Enqueued.Load(),
		"completed": q.stats.Completed.Load(),
		"failed":    q.stats.Failed.Load(),
		"retried":   q.stats.Retried.Load(),
		"cancelled": q.stats.Cancelled.Load(),
	}
}

// ============================================================
// WORKER POOL
// ============================================================

type WorkerPool struct {
	queue       *TaskQueue
	numWorkers  int
	handlers    map[string]TaskHandler
	wg          sync.WaitGroup
	ctx         context.Context
	cancel      context.CancelFunc
	results     []chan TaskResult
}

func NewWorkerPool(queue *TaskQueue, numWorkers int) *WorkerPool {
	ctx, cancel := context.WithCancel(context.Background())
	return &WorkerPool{
		queue:      queue,
		numWorkers: numWorkers,
		handlers:   make(map[string]TaskHandler),
		ctx:        ctx,
		cancel:     cancel,
	}
}

// RegisterHandler registers a handler
func (wp *WorkerPool) RegisterHandler(handler TaskHandler) {
	wp.handlers[handler.Type()] = handler
}

// Start launches the worker pool
func (wp *WorkerPool) Start() <-chan TaskResult {
	results := make(chan TaskResult, 1000)
	wp.results = append(wp.results, results)

	for i := 0; i < wp.numWorkers; i++ {
		wp.wg.Add(1)
		go wp.worker(i, results)
		log.Printf("Worker %d started", i)
	}

	return results
}

// Shutdown gracefully stops all workers
func (wp *WorkerPool) Shutdown() {
	log.Println("Shutting down worker pool...")
	wp.cancel()
	wp.wg.Wait()
	log.Println("All workers stopped")
}

// worker processes tasks from the queue
func (wp *WorkerPool) worker(id int, results chan<- TaskResult) {
	defer wp.wg.Done()

	for {
		select {
		case <-wp.ctx.Done():
			return
		default:
		}

		// Dequeue a task
		task := wp.queue.Dequeue()
		if task == nil {
			// No tasks available, wait a bit
			select {
			case <-wp.ctx.Done():
				return
			case <-time.After(100 * time.Millisecond):
				continue
			}
		}

		// Find handler
		handler, ok := wp.handlers[task.Type]
		if !ok {
			wp.queue.Fail(task.ID, fmt.Errorf("no handler for task type: %s", task.Type))
			continue
		}

		// Process task with timeout
		start := time.Now()
		taskCtx, taskCancel := context.WithTimeout(wp.ctx, task.Timeout)

		result, err := handler.Handle(taskCtx, task)

		taskCancel()
		duration := time.Since(start)

		if err != nil {
			wp.queue.Fail(task.ID, err)
			results <- TaskResult{
				TaskID:     task.ID,
				Status:     StatusFailed,
				Error:      err.Error(),
				Duration:   duration,
				RetryCount: task.RetryCount,
			}
		} else {
			wp.queue.Complete(task.ID, result)
			results <- TaskResult{
				TaskID:   task.ID,
				Status:   StatusCompleted,
				Result:   result,
				Duration: duration,
			}
			log.Printf("Worker %d completed task %s in %v", id, task.ID, duration)
		}
	}
}

// ============================================================
// TASK ID GENERATOR
// ============================================================

func generateTaskID() string {
	bytes := make([]byte, 8)
	rand.Read(bytes)
	return "task-" + hex.EncodeToString(bytes)
}

// ============================================================
// DEMO
// ============================================================

func main() {
	fmt.Println("=== Task Queue / Worker Pool Demo ===\n")

	// Create task queue
	queue := NewTaskQueue()

	// Create worker pool with 3 workers
	pool := NewWorkerPool(queue, 3)

	// Register handlers
	pool.RegisterHandler(NewGenericHandler("email", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		to := payload["to"]
		subject := payload["subject"]
		log.Printf("Sending email to %s: %s", to, subject)
		time.Sleep(500 * time.Millisecond) // Simulate work
		return fmt.Sprintf("Email sent to %s", to), nil
	}))

	pool.RegisterHandler(NewGenericHandler("report", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		name := payload["name"]
		log.Printf("Generating report: %s", name)
		time.Sleep(1 * time.Second) // Simulate longer work
		return fmt.Sprintf("Report '%s' generated", name), nil
	}))

	pool.RegisterHandler(NewGenericHandler("failing", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		return nil, fmt.Errorf("simulated processing error")
	}))

	// Start workers
	results := pool.Start()

	// Enqueue tasks
	for i := 0; i < 5; i++ {
		task := &Task{
			ID:         generateTaskID(),
			Type:       "email",
			Payload:    map[string]interface{}{"to": fmt.Sprintf("user%d@example.com", i+1), "subject": "Welcome!"},
			Priority:   PriorityNormal,
			MaxRetries: 2,
			Timeout:    5 * time.Second,
		}
		queue.Enqueue(task)
	}

	// Enqueue high-priority report
	reportTask := &Task{
		ID:         generateTaskID(),
		Type:       "report",
		Payload:    map[string]interface{}{"name": "Monthly Summary"},
		Priority:   PriorityHigh,
		MaxRetries: 1,
		Timeout:    10 * time.Second,
	}
	queue.Enqueue(reportTask)

	// Enqueue a failing task (will retry)
	failTask := &Task{
		ID:         generateTaskID(),
		Type:       "failing",
		Payload:    map[string]interface{}{},
		Priority:   PriorityLow,
		MaxRetries: 2,
		Timeout:    3 * time.Second,
	}
	queue.Enqueue(failTask)

	// Collect results
	var completed, failed int
	timeout := time.After(10 * time.Second)

	resultLoop:
	for {
		select {
		case result := <-results:
			if result.Status == StatusCompleted {
				completed++
				fmt.Printf("✓ Task %s completed in %v: %v\n", result.TaskID[:20], result.Duration, result.Result)
			} else if result.Status == StatusFailed {
				failed++
				fmt.Printf("✗ Task %s failed: %s (retried %d times)\n", result.TaskID[:20], result.Error, result.RetryCount)
			}
			if completed+failed >= 7 {
				break resultLoop
			}
		case <-timeout:
			fmt.Println("Timeout reached, stopping...")
			break resultLoop
		}
	}

	// Shutdown
	pool.Shutdown()

	// Stats
	fmt.Printf("\n=== Queue Stats ===\n")
	stats := queue.Stats()
	fmt.Printf("Enqueued:  %d\n", stats["enqueued"])
	fmt.Printf("Completed: %d\n", stats["completed"])
	fmt.Printf("Failed:    %d\n", stats["failed"])
	fmt.Printf("Retried:   %d\n", stats["retried"])
	fmt.Printf("Cancelled: %d\n", stats["cancelled"])
	fmt.Printf("\n=== Demo Complete ===\n")
}
