# 🏗️ Job Scheduling System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Distributed scheduling, retry logic, cron, worker pools

---

## 1. SYSTEM OVERVIEW

**Purpose:** Reliable distributed job scheduler handling one-time, recurring, and dependency-based job execution with failure handling and monitoring.

**Scale:** 10K jobs/second throughput, 1M scheduled jobs/day, 100 worker nodes, 5-minute SLA

**Users:** Developers (submit jobs), DevOps (monitor), Platform admins

**Use Cases:** Schedule one-time task, Recurring cron job, DAG-based job pipeline, Retry failed jobs, Monitor job health

**Constraints:** <2s scheduling latency, at-least-once execution, no job loss on worker failure, cron accuracy within 1 second

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────┐
│              API / Admin Dashboard           │
│  (Submit jobs, check status, view logs)      │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│              API Gateway                      │
└──────┬──────────────────────────────────┬────┘
       │                                  │
┌──────▼──────────────┐    ┌──────────────▼──────┐
│  Scheduler Service  │    │  Cron Trigger       │
│  (Go)               │    │  Service (Python)   │
│  - Priority queue   │    │  - Cron parser      │
│  - Scheduling algo  │    │  - Recurring jobs   │
│  - DAG resolution   │    │  - Missed job catch │
└──────┬──────────────┘    └──────────────┬──────┘
       │                                  │
       └──────────────┬───────────────────┘
                      │
              ┌───────▼───────┐
              │  Redis Queue   │
              │  (Sorted Set)  │
              │  - Job queue   │
              │  - Dead letter │
              └───────┬───────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
  ┌─────▼───┐   ┌─────▼───┐   ┌─────▼───┐
  │ Worker 1│   │ Worker 2│   │ Worker N│
  │ (Go)    │   │ (Go)    │   │ (Go)    │
  └─────┬───┘   └─────┬───┘   └─────┬───┘
        │             │             │
        └─────────────┼─────────────┘
                      │
              ┌───────▼───────┐
              │  PostgreSQL   │
              │  - Job defs   │
              │  - History    │
              │  - Worker     │
              │    heartbeat  │
              └───────────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Scheduler Service (Go)
- Priority queue (heap-based, O(log n) insert/extract)
- FIFO, Priority, EDF scheduling algorithms
- Job dependency resolution (DAG topological sort)

**🔴 Interview Question:** *"How do you handle job dependencies (DAG of jobs)?"*

**✅ Answer:** DAG-based scheduling with topological ordering:
```python
class DAGScheduler:
    def schedule(self, dag_id):
        # 1. Build dependency graph from job definitions
        graph = self._load_dag(dag_id)
        
        # 2. Topological sort to find execution order
        order = self._topological_sort(graph)
        
        # 3. Submit root nodes (no dependencies) immediately
        for job_id in order:
            if not graph[job_id].dependencies:
                self._submit(job_id)
        
        # 4. As each job completes, check if dependent jobs can start
        def on_job_complete(job_id):
            for downstream in graph[job_id].downstream:
                if all_completed(graph[downstream].dependencies):
                    self._submit(downstream)
```

---

### Cron Trigger Service (Python)
- Cron expression parser (minute, hour, day, month, weekday)
- Next-run-time calculation
- Missed job catch-up policy

**🔴 Interview Question:** *"How do you handle daylight saving time for cron jobs?"*

**✅ Answer:**
1. **Store cron in UTC** — always. Convert to local timezone only for display.
2. **On DST spring-forward:** Jobs scheduled at 2:30 AM (nonexistent time in some zones) run at 3:00 AM instead.
3. **On DST fall-back:** Jobs at 1:30 AM run once — we skip the duplicate occurrence.
4. **Missed catch-up:** On scheduler restart, check cron.next_run for each job. If past due, decide policy: `catch_up=True` (run missed occurrences) or `catch_up=False` (skip, wait for next).

---

### Worker Pool (Go)
- Pull jobs from Redis queue
- Lease-based execution (prevent double-processing)
- Heartbeat every 5 seconds
- Graceful shutdown (finish current job, stop accepting)

**🔴 Interview Question:** *"How do you prevent two workers from running the same job?"*

**✅ Answer:** Redis lease mechanism:
```python
def acquire_job(worker_id):
    # Atomically pop from queue with lease
    job_data = redis.eval("""
        local job = redis.call('RPOP', 'job:queue')
        if job then
            -- Set lease (worker must heartbeat to extend)
            redis.call('SETEX', 'job:lease:' .. job, 30, ARGV[1])
        end
        return job
    """, 1, 'job:queue', worker_id)
    
    if not job_data:
        return None
    
    # Start heartbeat goroutine
    def heartbeat():
        while running:
            redis.expire(f'job:lease:{job.id}', 30)
            time.sleep(10)
    
    return deserialize(job_data)
```
If the worker crashes, the lease expires after 30 seconds. A recovery worker picks up the job (at-least-once guarantee).

---

## 4. DATA MODEL

```sql
CREATE TABLE job_definitions (
    id UUID, name TEXT, type TEXT, 
    schedule TEXT, -- cron expression or NULL for one-time
    max_retries INT DEFAULT 3, timeout_seconds INT DEFAULT 300,
    dependencies JSONB
);
CREATE TABLE job_executions (
    id BIGSERIAL, job_id UUID, status TEXT,
    started_at TIMESTAMP, completed_at TIMESTAMP,
    worker_id TEXT, retry_count INT, error_message TEXT,
    result JSONB
);
CREATE TABLE workers (
    id TEXT PRIMARY KEY, hostname TEXT,
    last_heartbeat TIMESTAMP, status TEXT,
    current_load INT
);
```

---

## 5. SCALABILITY

**Bottleneck:** Redis single-threaded. At 10K jobs/sec, Redis becomes CPU-bound.

**Solution:** Shard job queues by priority tier. Critical → Redis instance 1, Normal → instance 2, Low → instance 3.

**Availability:** 99.99%. Scheduler is stateless — run behind load balancer. Redis replication + Sentinel for failover. Workers auto-scale via K8s HPA based on queue depth.

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Scheduler (2 pods) | $600 |
| Workers (50 pods, auto-scale) | $5,000 |
| Redis Cluster | $1,200 |
| PostgreSQL | $600 |
| Monitoring + Alerts | $200 |
| **Total** | **$7,600** |
