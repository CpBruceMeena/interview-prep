# Task Queue / Worker Pool — Go Implementation

> Go implementation of a Task Queue with priority scheduling and worker pool processing.

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|---------------|---------|
| `TaskQueue` | Priority queue with retry/cancel | Pipeline |
| `WorkerPool` | N goroutine workers | Worker Pool |
| `TaskHandler` | Processes specific task types | Strategy |
| `PriorityQueue` | Min-heap for task ordering | Heap |

### Worker Pool with Priority Queue

```go
// Worker pool processes tasks from the queue
func (wp *WorkerPool) worker(id int, results chan<- TaskResult) {
    for {
        task := wp.queue.Dequeue()  // Get highest priority task
        if task == nil {
            // Wait for work (non-busy polling)
            select {
            case <-wp.ctx.Done(): return
            case <-time.After(100 * time.Millisecond): continue
            }
        }

        handler := wp.handlers[task.Type]
        result, err := handler.Handle(taskCtx, task)

        if err != nil {
            wp.queue.Fail(task.ID, err)  // Auto-retry with backoff
        } else {
            wp.queue.Complete(task.ID, result)
        }
    }
}
```

### Priority Queue (Min-Heap)

```go
type PriorityQueue []*Task

func (pq PriorityQueue) Less(i, j int) bool {
    // Higher priority first
    if pq[i].Priority != pq[j].Priority {
        return pq[i].Priority > pq[j].Priority
    }
    // FIFO for same priority
    return pq[i].CreatedAt.Before(pq[j].CreatedAt)
}
```

### Retry with Exponential Backoff

```go
func (q *TaskQueue) Fail(taskID string, err error) {
    task := q.running[taskID]
    task.RetryCount++

    if task.RetryCount < task.MaxRetries {
        backoff := time.Duration(math.Pow(2, float64(task.RetryCount))) * time.Second
        // Re-enqueue after backoff
        time.AfterFunc(backoff, func() {
            heap.Push(&q.pending, task)
        })
    } else {
        task.Status = StatusFailed  // Permanent failure
    }
}
```

## ▶️ How to Run

```bash
cd golang-low-level-design/task-queue
go run task_queue.go
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Worker Pool** | N goroutine workers | Controlled concurrent processing |
| **Pipeline** | Task → Queue → Worker → Result | Decoupled processing stages |
| **Strategy** | TaskHandler | Different task types, different handlers |
| **Min-Heap** | PriorityQueue | O(log n) priority ordering |
| **Exponential Backoff** | Retry logic | Avoid thundering herd on failures |
