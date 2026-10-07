# 🔐 Redis Lease — Distributed Locking with TTL

> **Target:** Staff/Principal Engineer | **Focus:** Distributed locking with Redis, lease mechanism, and production patterns | **Reviewed:** October 2026

!!! tip "30-second answer"
    A lease is a lock that **expires**: `SET key <unique-token> NX PX <ttl>` acquires it atomically, the TTL frees it if the holder crashes, and release/renew are compare-then-act (Lua, or `DELEX`/`SET ... IFEQ` on Redis 8.4+) so you only touch a lease you still own. The catch: expiry means a paused or slow holder can **keep working after its lease has gone** while a second holder starts. So a Redis lease is fine for *efficiency* (avoid duplicate work), but for *correctness* (never double-charge, never corrupt data) the protected resource must also reject stale holders, using a **fencing token**, or you need a consensus-backed lock service (etcd, ZooKeeper) plus fencing.

---

## 1. REDIS LEASE MECHANISM

### 1.1 What is a Lease?

A **lease** is a distributed lock with a **time-to-live (TTL)**. It allows one process to temporarily "own" a resource, preventing other processes from using it simultaneously.

```
Process A wants to take a lease on "resource:job-123"
    │
    ▼
┌─────────────────────────────────────────────┐
│              REDIS LEASE                      │
│                                                │
│  SET resource:job-123 "process-A" NX EX 30    │
│  └──────────────┬──────────────────────┘      │
│                 │                              │
│          ┌──────┴──────┐                      │
│          │  Success?    │                      │
│          └──────┬──────┘                      │
│             ┌───┴───┐                         │
│             ▼       ▼                         │
│         ┌──────┐ ┌──────┐                    │
│         │ Yes  │ │ No   │                    │
│         └──┬───┘ └──┬───┘                    │
│            ▼        ▼                         │
│      Execute     Wait/Retry                   │
│      (30s TTL)   (lease held by B)            │
└─────────────────────────────────────────────┘
```

### 1.2 How It Works

```python
import asyncio
import time
import uuid
from typing import Optional

import redis.asyncio as redis

class RedisLease:
    """
    Distributed lease using Redis.
    
    Key concepts:
    - NX: Only set if key doesn't exist (exclusive creation)
    - EX: Set TTL in seconds (auto-release on crash)
    - Owner ID: Unique identifier (prevents accidental release)
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    async def acquire(
        self, 
        resource: str, 
        ttl: int = 30,
        owner_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Acquire a lease on a resource.
        
        Args:
            resource: The resource to lock (e.g., "job:123")
            ttl: Time-to-live in seconds
            owner_id: Unique owner identifier (auto-generated if None)
            
        Returns:
            owner_id if acquired, None if already held
        """
        # A unique token PER ACQUISITION. Reusing a stable worker id is a bug:
        # a restarted worker with the same id could release or renew a lease
        # acquired by its previous incarnation.
        owner_id = owner_id or str(uuid.uuid4())
        key = f"lease:{resource}"
        
        # SET NX EX — Atomic operation
        acquired = await self.redis.set(key, owner_id, nx=True, ex=ttl)
        
        if acquired:
            return owner_id
        return None
    
    async def release(self, resource: str, owner_id: str) -> bool:
        """
        Release a lease (only if we own it).
        
        Uses Lua script for atomic check-and-delete.
        """
        key = f"lease:{resource}"
        
        # Lua script: check ownership, then delete
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        end
        return 0
        """
        
        released = await self.redis.eval(lua_script, 1, key, owner_id)
        return released == 1
    
    async def renew(self, resource: str, owner_id: str, ttl: int = 30) -> bool:
        """
        Renew a lease (extend TTL) — only if we own it.
        
        Critical for long-running operations.
        """
        key = f"lease:{resource}"
        
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("EXPIRE", KEYS[1], ARGV[2])
        end
        return 0
        """
        
        renewed = await self.redis.eval(lua_script, 1, key, owner_id, ttl)
        return renewed == 1
    
    async def get_owner(self, resource: str) -> Optional[str]:
        """Check who currently holds the lease."""
        key = f"lease:{resource}"
        owner = await self.redis.get(key)
        if isinstance(owner, bytes):           # decode_responses=False
            owner = owner.decode()
        return owner
```

On **Redis 8.4+** the Lua scripts can be replaced by native conditional commands: `DELEX key IFEQ <token>` (compare-and-delete) and `SET key <token> IFEQ <token> EX <ttl>` (compare-and-set to renew). Lua remains the portable choice for older Redis and for Valkey/managed services that lack them.

### 1.3 Production Usage: Job Scheduler with Leases

```python
class LeasedJobWorker:
    """
    Distributes jobs across multiple workers using Redis leases.
    Each job is a "resource" that one worker leases exclusively.
    """
    
    def __init__(self, redis_client: redis.Redis, worker_id: str):
        self.lease = RedisLease(redis_client)
        self.worker_id = worker_id
        self.active_leases = {}  # Track what we're working on
    
    async def try_claim_job(self, job_id: str) -> bool:
        """Try to claim a job by acquiring its lease."""
        owner = await self.lease.acquire(
            resource=f"job:{job_id}",
            ttl=60,
            owner_id=f"{self.worker_id}:{uuid.uuid4()}",  # unique per acquisition
        )
        
        if owner:
            self.active_leases[job_id] = {
                "owner": owner,
                "acquired_at": time.time(),
                "job_task": None,   # caller stores the asyncio.Task running the job
                "renewal_task": asyncio.create_task(
                    self._keep_alive(job_id)
                )
            }
            return True
        return False
    
    async def _keep_alive(self, job_id: str):
        """Background task: renew lease while job is running."""
        while job_id in self.active_leases:
            await asyncio.sleep(15)  # Renew every 15s
            owner = self.active_leases[job_id]["owner"]
            renewed = await self.lease.renew(
                resource=f"job:{job_id}",
                owner_id=owner,
                ttl=60
            )
            if not renewed:
                # Lost the lease (expired during a pause, or Redis failed
                # over). Someone else may now own the job: STOP working on it,
                # don't just log. In production, cancel the job task here.
                logger.warning("lost lease on job %s; aborting", job_id)
                job_task = self.active_leases[job_id]["job_task"]
                if job_task:
                    job_task.cancel()
                break
    
    async def complete_job(self, job_id: str):
        """Complete a job and release the lease."""
        if job_id in self.active_leases:
            info = self.active_leases[job_id]
            info["renewal_task"].cancel()
            await self.lease.release(
                resource=f"job:{job_id}",
                owner_id=info["owner"]
            )
            del self.active_leases[job_id]
```

Renew at a fraction of the TTL (here every 15 s for a 60 s lease) so a couple of failed renewals don't lose the lease, and make the TTL much longer than any expected pause.

### 1.4 Lease vs Other Distributed Locking

| Method | Released on holder crash | Fencing token available | Safety caveat | Use Case |
|--------|--------------------------|-------------------------|---------------|----------|
| **Redis SET NX PX** (single primary) | ✅ TTL | Build one (`INCR` counter) | Async replication: a failover can lose a just-acquired lock, so two holders | Efficiency locks, dedup of work |
| **Redlock** (N independent Redis nodes, majority) | ✅ TTL | ❌ none built in | Depends on bounded clock drift and pauses; contested (Kleppmann vs antirez) | Rarely worth it: if you need correctness, use consensus + fencing |
| **PostgreSQL advisory lock** | ✅ when the session/transaction ends | Use a version column instead | Ties the lock to a DB connection (careful with poolers like PgBouncer in transaction mode) | Work already inside one Postgres |
| **ZooKeeper ephemeral node** | ✅ session expiry | ✅ zxid / sequential node number | Session timeouts still allow brief overlap | Coordination-heavy systems |
| **etcd lease** | ✅ lease TTL | ✅ revision number | Same timing caveat, but linearizable and fenceable | Kubernetes and Go ecosystems |

### 1.5 The Problem Every Lease Has: Fencing Tokens

```
Worker A: acquire lease (token 33) ─── long GC / network pause ────────► writes to storage with token 33
                                       lease expires                    ▲
Worker B:                              acquire lease (token 34) ─► write │ token 34
                                                                         │
Storage: accepts 34, then REJECTS 33 because 33 < last seen (34)  ──────┘
```

A TTL guarantees the lock is eventually freed, not that the old holder has stopped. The fix is a **fencing token**: a number that increases with every acquisition, passed with every write, and checked by the resource ("reject anything older than the newest token I've seen").

```python
FENCED_ACQUIRE = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then
    return redis.call('INCR', KEYS[2])   -- monotonically increasing token
end
return nil
"""

async def acquire_with_fence(r, resource: str, owner: str, ttl_ms: int):
    return await r.eval(FENCED_ACQUIRE, 2,
                        f"lease:{resource}", f"fence:{resource}", owner, ttl_ms)

# The protected resource enforces it, e.g. in SQL:
#   UPDATE jobs SET result = $1, fence = $2
#   WHERE id = $3 AND fence < $2;      -- 0 rows updated => stale holder
```

Even simpler, and often enough: make the side effect **idempotent** (idempotency key, conditional write on a version column) so a duplicate holder can't do damage.

### 1.6 What Interviewers Probe Next

- **"Why not just `SETNX` then `EXPIRE`?"** Two commands: a crash between them leaves a lock with no TTL forever. `SET ... NX PX` is one atomic command.
- **"Why check ownership on release?"** If your lease expired and B acquired it, a blind `DEL` frees B's lock.
- **"What TTL?"** Longer than the worst realistic pause plus renewal interval, short enough that a crash doesn't stall work for long. Renewal makes long jobs work with a short TTL.
- **"Redis Cluster or Sentinel failover?"** Replication is asynchronous, so a lock written to the old primary may be missing on the new one. Accept it (efficiency locks) or add fencing.
- **"Is this an agent concern?"** Yes: two replicas resuming the same agent thread, or two workers claiming the same queued run, is exactly this problem. Lease per thread/run + idempotent tool side effects.

---

> **Previous:** [System, User & Assistant Roles](10_SYSTEM_USER_ASSISTANT_ROLES.md)
> **Next:** [Search Autocorrect & Misspelling Handling](12_SEARCH_AUTOCORRECT.md)
