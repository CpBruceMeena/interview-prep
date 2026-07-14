# 📋 Task Queue / Worker Pool — Interview Questions

## Q1: How does priority scheduling work? Can a low-priority task starve?

**Answer:**
- Min-heap ensures highest priority tasks are dequeued first
- Starvation is possible: constant high-priority tasks can block low-priority ones
- Solutions:
  1. Priority aging: increase task priority over time
  2. Proportional scheduling: allocate minimum share to each priority level
  3. Multi-level feedback queue: demote tasks that consume too much CPU

## Q2: How do you handle graceful shutdown with in-flight tasks?

**Answer:**
- Context-based cancellation propagates to all workers
- On shutdown: workers finish current task, then exit
- Option 1: Drain existing tasks before shutdown
- Option 2: Save pending/running state to durable storage for recovery
- Option 3: Allow configurable drain timeout, after which force-kill

## Q3: How would you make this a distributed task queue across multiple machines?

**Answer:**
- Replace in-memory PriorityQueue with Redis sorted set (ZADD/ZPOPMIN)
- Replace in-memory task storage with PostgreSQL/Redis
- Leader election for worker coordination
- Heartbeat mechanism for failure detection
- Task reassignment on worker failure

## Q4: How do you handle duplicate task execution (at-least-once vs exactly-once)?

**Answer:**
- **At-least-once:** Task idempotency key, retry on failure
- **Exactly-once:** Requires distributed transaction + idempotency + dedup
- Implementation: store task ID in completed set before executing; check before each execution
- Trade-off: exactly-once adds significant overhead; at-least-once + idempotent handlers is often sufficient
