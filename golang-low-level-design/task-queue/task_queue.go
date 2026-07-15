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
// - Scheduled/future tasks with time-based execution
// - Task chaining with dependency resolution
// - Batch processing for bulk operations
// - Dead letter queue for permanently failed tasks

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
	PriorityBackground TaskPriority = 0
	PriorityLow        TaskPriority = 1
	PriorityNormal     TaskPriority = 2
	PriorityHigh       TaskPriority = 3
	PriorityCritical   TaskPriority = 4
)

type TaskStatus string

const (
	StatusPending    TaskStatus = "PENDING"
	StatusRunning    TaskStatus = "RUNNING"
	StatusCompleted  TaskStatus = "COMPLETED"
	StatusFailed     TaskStatus = "FAILED"
	StatusRetrying   TaskStatus = "RETRYING"
	StatusCancelled  TaskStatus = "CANCELLED"
	StatusScheduled  TaskStatus = "SCHEDULED"
	StatusBlocked    TaskStatus = "BLOCKED" // Waiting for dependencies
	StatusDeadLettered TaskStatus = "DEAD_LETTER"
)

// Task represents a unit of work to be processed
type Task struct {
	ID            string                 `json:"id"`
	Type          string                 `json:"type"`
	Payload       map[string]interface{} `json:"payload"`
	Priority      TaskPriority           `json:"priority"`
	Status        TaskStatus             `json:"status"`
	CreatedAt     time.Time              `json:"created_at"`
	ScheduledAt   time.Time              `json:"scheduled_at,omitempty"`
	StartedAt     time.Time              `json:"started_at,omitempty"`
	CompletedAt   time.Time              `json:"completed_at,omitempty"`
	RetryCount    int                    `json:"retry_count"`
	MaxRetries    int                    `json:"max_retries"`
	Timeout       time.Duration          `json:"timeout"`
	Result        interface{}            `json:"result,omitempty"`
	Error         string                 `json:"error,omitempty"`
	GroupID       string                 `json:"group_id,omitempty"`       // Task grouping
	ParentTaskID  string                 `json:"parent_task_id,omitempty"` // Chaining
	Dependencies  []string               `json:"dependencies,omitempty"`   // Dependency IDs
	Metadata      map[string]string      `json:"metadata,omitempty"`
	index         int                    `json:"-"` // For heap.Interface
}

// TaskResult represents the outcome of a processed task
type TaskResult struct {
	TaskID      string
	Status      TaskStatus
	Result      interface{}
	Error       string
	Duration    time.Duration
	RetryCount  int
	CompletedAt time.Time
}

// ============================================================
// PRIORITY QUEUE (Min-Heap)
// ============================================================

type PriorityQueue []*Task

func (pq PriorityQueue) Len() int { return len(pq) }

func (pq PriorityQueue) Less(i, j int) bool {
	// Scheduled tasks: execute if their time has come
	now := time.Now()
	iScheduled := !pq[i].ScheduledAt.IsZero() && now.After(pq[i].ScheduledAt)
	jScheduled := !pq[j].ScheduledAt.IsZero() && now.After(pq[j].ScheduledAt)

	// If both are ready or both are not scheduled, use priority
	if iScheduled == jScheduled {
		if pq[i].Priority != pq[j].Priority {
			return pq[i].Priority > pq[j].Priority
		}
		return pq[i].CreatedAt.Before(pq[j].CreatedAt)
	}

	// Ready scheduled tasks go first
	return iScheduled && !jScheduled
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
// SCHEDULED TASK QUEUE
// ============================================================

type ScheduledTaskQueue struct {
	mu       sync.Mutex
	tasks    []*Task // Sorted by ScheduledAt (min-heap)
	notifyCh chan struct{}
}

func NewScheduledTaskQueue() *ScheduledTaskQueue {
	return &ScheduledTaskQueue{
		tasks:    make([]*Task, 0),
		notifyCh: make(chan struct{}, 1),
	}
}

func (sq *ScheduledTaskQueue) Add(task *Task) {
	sq.mu.Lock()
	defer sq.mu.Unlock()

	// Insert sorted by ScheduledAt
	insertIdx := len(sq.tasks)
	for i, t := range sq.tasks {
		if t.ScheduledAt.After(task.ScheduledAt) {
			insertIdx = i
			break
		}
	}
	sq.tasks = append(sq.tasks[:insertIdx], append([]*Task{task}, sq.tasks[insertIdx:]...)...)

	// Notify
	select {
	case sq.notifyCh <- struct{}{}:
	default:
	}
}

func (sq *ScheduledTaskQueue) GetReady() []*Task {
	sq.mu.Lock()
	defer sq.mu.Unlock()

	now := time.Now()
	var ready []*Task

	for len(sq.tasks) > 0 && (sq.tasks[0].ScheduledAt.IsZero() || now.After(sq.tasks[0].ScheduledAt)) {
		ready = append(ready, sq.tasks[0])
		sq.tasks = sq.tasks[1:]
	}

	return ready
}

func (sq *ScheduledTaskQueue) NextScheduled() time.Duration {
	sq.mu.Lock()
	defer sq.mu.Unlock()

	if len(sq.tasks) == 0 {
		return time.Hour // Check again in an hour
	}

	delay := time.Until(sq.tasks[0].ScheduledAt)
	if delay < 0 {
		return 0
	}
	return delay
}

// ============================================================
// DEAD LETTER QUEUE
// ============================================================

type DeadLetterQueue struct {
	mu       sync.Mutex
	tasks    []*Task
	maxSize  int
}

func NewDeadLetterQueue(maxSize int) *DeadLetterQueue {
	return &DeadLetterQueue{
		tasks:   make([]*Task, 0, maxSize),
		maxSize: maxSize,
	}
}

func (dlq *DeadLetterQueue) Add(task *Task) {
	dlq.mu.Lock()
	defer dlq.mu.Unlock()

	task.Status = StatusDeadLettered
	if len(dlq.tasks) >= dlq.maxSize {
		// Remove oldest
		dlq.tasks = dlq.tasks[1:]
	}
	dlq.tasks = append(dlq.tasks, task)
	log.Printf("☠️ Task %s moved to dead letter queue (type=%s, retries=%d)", task.ID, task.Type, task.RetryCount)
}

func (dlq *DeadLetterQueue) Peek() []*Task {
	dlq.mu.Lock()
	defer dlq.mu.Unlock()

	result := make([]*Task, len(dlq.tasks))
	copy(result, dlq.tasks)
	return result
}

func (dlq *DeadLetterQueue) Requeue(queue *TaskQueue, taskID string) bool {
	dlq.mu.Lock()
	defer dlq.mu.Unlock()

	for i, task := range dlq.tasks {
		if task.ID == taskID {
			task.Status = StatusPending
			task.RetryCount = 0
			task.Error = ""
			queue.Enqueue(task)
			dlq.tasks = append(dlq.tasks[:i], dlq.tasks[i+1:]...)
			return true
		}
	}
	return false
}

func (dlq *DeadLetterQueue) Size() int {
	dlq.mu.Lock()
	defer dlq.mu.Unlock()
	return len(dlq.tasks)
}

// ============================================================
// BATCH PROCESSOR
// ============================================================

type BatchConfig struct {
	MaxSize     int
	MaxWait     time.Duration
	FlushHandler func(ctx context.Context, tasks []*Task) []TaskResult
}

type BatchProcessor struct {
	mu       sync.Mutex
	batches  map[string][]*Task // groupID -> tasks
	config   BatchConfig
	notifyCh chan struct{}
}

func NewBatchProcessor(config BatchConfig) *BatchProcessor {
	bp := &BatchProcessor{
		batches:  make(map[string][]*Task),
		config:   config,
		notifyCh: make(chan struct{}, 1),
	}

	// Periodic flush
	go func() {
		ticker := time.NewTicker(config.MaxWait)
		defer ticker.Stop()

		for range ticker.C {
			bp.FlushAll(context.Background())
		}
	}()

	return bp
}

func (bp *BatchProcessor) Add(groupID string, task *Task) {
	bp.mu.Lock()
	defer bp.mu.Unlock()

	bp.batches[groupID] = append(bp.batches[groupID], task)
	if len(bp.batches[groupID]) >= bp.config.MaxSize {
		select {
		case bp.notifyCh <- struct{}{}:
		default:
		}
	}
}

func (bp *BatchProcessor) Flush(ctx context.Context, groupID string) []TaskResult {
	bp.mu.Lock()
	tasks := bp.batches[groupID]
	delete(bp.batches, groupID)
	bp.mu.Unlock()

	if len(tasks) == 0 {
		return nil
	}

	log.Printf("Flushing batch %s: %d tasks", groupID, len(tasks))
	return bp.config.FlushHandler(ctx, tasks)
}

func (bp *BatchProcessor) FlushAll(ctx context.Context) map[string][]TaskResult {
	bp.mu.Lock()
	groups := make([]string, 0, len(bp.batches))
	for g := range bp.batches {
		groups = append(groups, g)
	}
	bp.mu.Unlock()

	results := make(map[string][]TaskResult)
	for _, g := range groups {
		results[g] = bp.Flush(ctx, g)
	}
	return results
}

// ============================================================
// TASK HANDLER (Strategy Pattern)
// ============================================================

type TaskHandler interface {
	Handle(ctx context.Context, task *Task) (interface{}, error)
	Type() string
}

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
	mu               sync.RWMutex
	pending          PriorityQueue
	running          map[string]*Task
	handlers         map[string]TaskHandler
	results          chan TaskResult
	scheduled        *ScheduledTaskQueue
	deadLetter       *DeadLetterQueue
	batchProcessor   *BatchProcessor
	stats            QueueStats
}

type QueueStats struct {
	Enqueued   atomic.Int64
	Completed  atomic.Int64
	Failed     atomic.Int64
	Retried    atomic.Int64
	Cancelled  atomic.Int64
	Running    atomic.Int64
	Scheduled  atomic.Int64
	DeadLettered atomic.Int64
	Batched    atomic.Int64
}

func NewTaskQueue() *TaskQueue {
	return &TaskQueue{
		pending:     make(PriorityQueue, 0),
		running:     make(map[string]*Task),
		handlers:    make(map[string]TaskHandler),
		results:     make(chan TaskResult, 1000),
		scheduled:   NewScheduledTaskQueue(),
		deadLetter:  NewDeadLetterQueue(1000),
	}
}

// SetBatchProcessor attaches a batch processor to the queue
func (q *TaskQueue) SetBatchProcessor(bp *BatchProcessor) {
	q.batchProcessor = bp
}

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
	log.Printf("📥 Enqueued task %s (type=%s, priority=%d)", task.ID, task.Type, task.Priority)
}

// Schedule adds a task for future execution
func (q *TaskQueue) Schedule(task *Task, executeAt time.Time) {
	task.Status = StatusScheduled
	task.ScheduledAt = executeAt
	task.CreatedAt = time.Now()
	q.scheduled.Add(task)
	q.stats.Scheduled.Add(1)
	log.Printf("📅 Scheduled task %s for %s (type=%s)", task.ID, executeAt.Format(time.RFC3339), task.Type)
}

// EnqueueWithDependencies enqueues a task with dependencies
func (q *TaskQueue) EnqueueWithDependencies(task *Task, dependencyIDs []string) {
	task.Dependencies = dependencyIDs
	if len(dependencyIDs) > 0 {
		task.Status = StatusBlocked
	}
	q.Enqueue(task)
}

// Dequeue removes and returns the highest priority task
func (q *TaskQueue) Dequeue() *Task {
	q.mu.Lock()
	defer q.mu.Unlock()

	// First check scheduled tasks
	readyTasks := q.scheduled.GetReady()
	for _, t := range readyTasks {
		t.Status = StatusPending
		heap.Push(&q.pending, t)
	}

	if q.pending.Len() == 0 {
		return nil
	}

	task := heap.Pop(&q.pending).(*Task)

	// Check dependencies
	if len(task.Dependencies) > 0 {
		if !q.areDependenciesMet(task) {
			// Not ready yet, put it back
			task.Status = StatusBlocked
			heap.Push(&q.pending, task)
			return nil
		}
	}

	task.Status = StatusRunning
	task.StartedAt = time.Now()
	q.running[task.ID] = task
	q.stats.Running.Add(1)
	return task
}

func (q *TaskQueue) areDependenciesMet(task *Task) bool {
	for _, depID := range task.Dependencies {
		// Check if dependency is still running
		if _, running := q.running[depID]; running {
			return false
		}
		// Check if dependency is still pending
		for _, t := range q.pending {
			if t.ID == depID {
				return false
			}
		}
		// Check if dependency failed or was cancelled — in that case, dependent should fail too
	}
	return true
}

// failDependentTasks fails all tasks that depend on the given task ID
func (q *TaskQueue) failDependentTasks(taskID string) {
	// Collect dependents with their current heap indices
	type depEntry struct {
		task  *Task
		index int
	}
	var dependents []depEntry		for _, t := range q.pending {
		for _, depID := range t.Dependencies {
			if depID == taskID {
				dependents = append(dependents, depEntry{t, t.index})
				break
			}
		}
	}
	// Sort by index descending so removals don't shift remaining indices
	for i := 0; i < len(dependents); i++ {
		for j := i + 1; j < len(dependents); j++ {
			if dependents[j].index > dependents[i].index {
				dependents[i], dependents[j] = dependents[j], dependents[i]
			}
		}
	}
	for _, de := range dependents {
		de.task.Status = StatusFailed
		de.task.Error = fmt.Sprintf("dependency %s failed", taskID)
		heap.Remove(&q.pending, de.index)
		q.stats.Failed.Add(1)
		q.deadLetter.Add(de.task)
		log.Printf("☠️ Task %s failed due to dependency %s failure", de.task.ID, taskID)
	}
}

// Complete marks a task as completed
func (q *TaskQueue) Complete(taskID string, result interface{}) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if task, ok := q.running[taskID]; ok {
		task.Status = StatusCompleted
		task.Result = result
		task.CompletedAt = time.Now()
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
			task.Status = StatusRetrying
			backoff := time.Duration(math.Pow(2, float64(task.RetryCount))) * time.Second
			task.ScheduledAt = time.Now().Add(backoff)

			// Re-schedule
			time.AfterFunc(backoff, func() {
				q.mu.Lock()
				task.Status = StatusPending
				heap.Push(&q.pending, task)
				q.stats.Retried.Add(1)
				q.mu.Unlock()
			})

			log.Printf("🔄 Task %s failed, retry %d/%d in %v",
				taskID, task.RetryCount, task.MaxRetries, backoff)
		} else {
			// Move to dead letter queue
			task.Status = StatusFailed
			q.deadLetter.Add(task)
			q.stats.DeadLettered.Add(1)
			q.stats.Failed.Add(1)
			log.Printf("☠️ Task %s failed permanently after %d retries: %v",
				taskID, task.RetryCount, err)

			// Fail all dependent tasks
			q.failDependentTasks(taskID)
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

		// Fail dependent tasks
		q.failDependentTasks(taskID)
	}
}

// RequeueFromDeadLetter re-queues a task from the dead letter queue
func (q *TaskQueue) RequeueFromDeadLetter(taskID string) bool {
	return q.deadLetter.Requeue(q, taskID)
}

// DeadLetterStats returns dead letter queue info
func (q *TaskQueue) DeadLetterStats() map[string]interface{} {
	tasks := q.deadLetter.Peek()
	typeCounts := make(map[string]int)
	for _, t := range tasks {
		typeCounts[t.Type]++
	}
	return map[string]interface{}{
		"total":  len(tasks),
		"by_type": typeCounts,
	}
}

// Stats returns current queue statistics
func (q *TaskQueue) Stats() map[string]interface{} {
	q.mu.RLock()
	defer q.mu.RUnlock()

	return map[string]interface{}{
		"pending":       q.pending.Len(),
		"running":       len(q.running),
		"enqueued":      q.stats.Enqueued.Load(),
		"completed":     q.stats.Completed.Load(),
		"failed":        q.stats.Failed.Load(),
		"retried":       q.stats.Retried.Load(),
		"cancelled":     q.stats.Cancelled.Load(),
		"scheduled":     q.stats.Scheduled.Load(),
		"dead_lettered": q.stats.DeadLettered.Load(),
		"batched":       q.stats.Batched.Load(),
		"dead_letter":   q.deadLetter.Size(),
	}
}

// ============================================================
// WORKER POOL
// ============================================================

type WorkerPool struct {
	queue          *TaskQueue
	numWorkers     int
	handlers       map[string]TaskHandler
	wg             sync.WaitGroup
	ctx            context.Context
	cancel         context.CancelFunc
	results        []chan TaskResult
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

func (wp *WorkerPool) RegisterHandler(handler TaskHandler) {
	wp.handlers[handler.Type()] = handler
	wp.queue.RegisterHandler(handler)
}

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

func (wp *WorkerPool) Shutdown() {
	log.Println("Shutting down worker pool...")
	wp.cancel()
	wp.wg.Wait()
	log.Println("All workers stopped")
}

func (wp *WorkerPool) worker(id int, results chan<- TaskResult) {
	defer wp.wg.Done()

	for {
		select {
		case <-wp.ctx.Done():
			return
		default:
		}

		task := wp.queue.Dequeue()
		if task == nil {
			// Check scheduled queue wait time before polling again
			waitTime := wp.queue.scheduled.NextScheduled()
			if waitTime > 100*time.Millisecond {
				waitTime = 100 * time.Millisecond
			}
			select {
			case <-wp.ctx.Done():
				return
			case <-time.After(waitTime):
				continue
			}
		}

		handler, ok := wp.handlers[task.Type]
		if !ok {
			wp.queue.Fail(task.ID, fmt.Errorf("no handler for task type: %s", task.Type))
			continue
		}

		start := time.Now()
		taskCtx, taskCancel := context.WithTimeout(wp.ctx, task.Timeout)

		result, err := handler.Handle(taskCtx, task)
		taskCancel()
		duration := time.Since(start)

		if err != nil {
			wp.queue.Fail(task.ID, err)
			results <- TaskResult{
				TaskID:      task.ID,
				Status:      StatusFailed,
				Error:       err.Error(),
				Duration:    duration,
				RetryCount:  task.RetryCount,
				CompletedAt: time.Now(),
			}
		} else {
			wp.queue.Complete(task.ID, result)
			results <- TaskResult{
				TaskID:      task.ID,
				Status:      StatusCompleted,
				Result:      result,
				Duration:    duration,
				CompletedAt: time.Now(),
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
	fmt.Println("╔══════════════════════════════════╗")
	fmt.Println("║   TASK QUEUE / WORKER POOL DEMO  ║")
	fmt.Println("╚══════════════════════════════════╝\n")

	// Create task queue
	queue := NewTaskQueue()

	// Create worker pool with 3 workers
	pool := NewWorkerPool(queue, 3)

	// Register handlers
	pool.RegisterHandler(NewGenericHandler("email", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		to := payload["to"]
		subject := payload["subject"]
		log.Printf("  📧 Sending email to %s: %s", to, subject)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
		return fmt.Sprintf("Email sent to %s", to), nil
	}))

	pool.RegisterHandler(NewGenericHandler("report", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		name := payload["name"]
		log.Printf("  📊 Generating report: %s", name)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(1 * time.Second):
		}
		return fmt.Sprintf("Report '%s' generated", name), nil
	}))

	pool.RegisterHandler(NewGenericHandler("notification", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		channel := payload["channel"]
		message := payload["message"]
		log.Printf("  🔔 Sending %s notification: %s", channel, message)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(300 * time.Millisecond):
		}
		return fmt.Sprintf("Notification sent via %s", channel), nil
	}))

	pool.RegisterHandler(NewGenericHandler("failing", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		return nil, fmt.Errorf("simulated processing error")
	}))

	pool.RegisterHandler(NewGenericHandler("slow", func(ctx context.Context, payload map[string]interface{}) (interface{}, error) {
		name := payload["name"]
		log.Printf("  🐢 Processing slow task: %s", name)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(3 * time.Second):
		}
		return fmt.Sprintf("Slow task '%s' completed", name), nil
	}))

	// Start workers
	results := pool.Start()

	// ---- NORMAL TASKS ----
	fmt.Println("--- NORMAL TASKS ---")
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

	// High-priority task
	reportTask := &Task{
		ID:         generateTaskID(),
		Type:       "report",
		Payload:    map[string]interface{}{"name": "Q4 Summary"},
		Priority:   PriorityHigh,
		MaxRetries: 1,
		Timeout:    10 * time.Second,
	}
	queue.Enqueue(reportTask)
	fmt.Println("  Added high-priority report task")

	// ---- SCHEDULED TASKS ----
	fmt.Println("\n--- SCHEDULED TASKS ---")
	scheduledTask := &Task{
		ID:         generateTaskID(),
		Type:       "notification",
		Payload:    map[string]interface{}{"channel": "slack", "message": "System health check passed"},
		Priority:   PriorityLow,
		MaxRetries: 1,
		Timeout:    5 * time.Second,
	}
	queue.Schedule(scheduledTask, time.Now().Add(2*time.Second))
	fmt.Println("  Scheduled notification in 2 seconds")

	// ---- BATCH PROCESSING ----
	fmt.Println("\n--- BATCH PROCESSING ---")
	bp := NewBatchProcessor(BatchConfig{
		MaxSize: 5,
		MaxWait: 3 * time.Second,
		FlushHandler: func(ctx context.Context, tasks []*Task) []TaskResult {
			log.Printf("  📦 Batch flushing %d tasks", len(tasks))
			var results []TaskResult
			for _, t := range tasks {
				results = append(results, TaskResult{
					TaskID: t.ID,
					Status: StatusCompleted,
					Result: fmt.Sprintf("Batched: %s", t.Type),
				})
				queue.stats.Batched.Add(1)
			}
			return results
		},
	})
	queue.SetBatchProcessor(bp)

	for i := 0; i < 3; i++ {
		batchTask := &Task{
			ID:      generateTaskID(),
			Type:    "email",
			Payload: map[string]interface{}{"to": fmt.Sprintf("batch%d@example.com", i), "subject": "Batch"},
			Priority: PriorityLow,
		}
		bp.Add("email-batch", batchTask)
	}
	fmt.Println("  Added 3 tasks to batch processor")

	// ---- TASK WITH DEPENDENCIES ----
	fmt.Println("\n--- CHAINED TASKS ---")
	depTask1 := &Task{
		ID:         generateTaskID(),
		Type:       "report",
		Payload:    map[string]interface{}{"name": "Data Collection"},
		Priority:   PriorityNormal,
		MaxRetries: 2,
		Timeout:    5 * time.Second,
	}
	queue.Enqueue(depTask1)

	depTask2 := &Task{
		ID:             generateTaskID(),
		Type:           "notification",
		Payload:        map[string]interface{}{"channel": "email", "message": "Report ready"},
		Priority:       PriorityNormal,
		MaxRetries:     2,
		Timeout:        5 * time.Second,
		Dependencies:   []string{depTask1.ID},
	}
	queue.EnqueueWithDependencies(depTask2, []string{depTask1.ID})
	fmt.Printf("  %s depends on %s completing\n", depTask2.ID[:20], depTask1.ID[:20])

	// ---- FAILING TASK (will retry then dead letter) ----
	fmt.Println("\n--- FAILING TASK (Dead Letter Test) ---")
	failTask := &Task{
		ID:         generateTaskID(),
		Type:       "failing",
		Payload:    map[string]interface{}{},
		Priority:   PriorityLow,
		MaxRetries: 2,
		Timeout:    3 * time.Second,
	}
	queue.Enqueue(failTask)

	// ---- COLLECT RESULTS ----
	var completed, failed int
	totalTasks := 13 // 5 email + 1 report + 1 notification + 3 batch + 1 chained + 1 dep + 1 failing
	timeout := time.After(15 * time.Second)

	fmt.Println("\n--- COLLECTING RESULTS ---")
resultLoop:
	for {
		select {
		case result := <-results:
			if result.Status == StatusCompleted {
				completed++
				fmt.Printf("  ✓ %s completed in %v: %v\n", result.TaskID[:20], result.Duration, result.Result)
			} else if result.Status == StatusFailed {
				failed++
				fmt.Printf("  ✗ %s failed: %s (retried %d times)\n", result.TaskID[:20], result.Error, result.RetryCount)
			}
			if completed+failed >= totalTasks {
				fmt.Printf("  All %d tasks accounted for\n", completed+failed)
				// But some may still be processing, wait a bit more
				select {
				case <-time.After(3 * time.Second):
					break resultLoop
				}
			}
		case <-timeout:
			fmt.Println("  Timeout reached, stopping...")
			break resultLoop
		}
	}

	// Shutdown
	pool.Shutdown()

	// ---- FINAL STATS ----
	fmt.Println("\n" + "=".repeat(55))
	fmt.Println("           QUEUE STATISTICS")
	fmt.Println("=".repeat(55))
	stats := queue.Stats()
	fmt.Printf("  Enqueued:     %d\n", stats["enqueued"])
	fmt.Printf("  Completed:    %d\n", stats["completed"])
	fmt.Printf("  Failed:       %d\n", stats["failed"])
	fmt.Printf("  Retried:      %d\n", stats["retried"])
	fmt.Printf("  Cancelled:    %d\n", stats["cancelled"])
	fmt.Printf("  Scheduled:    %d\n", stats["scheduled"])
	fmt.Printf("  Batched:      %d\n", stats["batched"])
	fmt.Printf("  Dead Letter:  %d\n", stats["dead_letter"])

	// Dead letter details
	dlStats := queue.DeadLetterStats()
	if dlStats["total"].(int) > 0 {
		fmt.Printf("\n  ☠️ Dead Letter Queue:")
		fmt.Printf("    Total: %d\n", dlStats["total"])
		if byType, ok := dlStats["by_type"].(map[string]int); ok {
			for t, c := range byType {
				fmt.Printf("    %s: %d\n", t, c)
			}
		}
	}

	fmt.Println("\n" + "=".repeat(55))
	fmt.Println("╔══════════════════════════════════╗")
	fmt.Println("║       DEMO COMPLETE             ║")
	fmt.Println("╚══════════════════════════════════╝")
}
