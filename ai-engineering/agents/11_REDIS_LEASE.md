# 🔐 Redis Lease — Distributed Locking with TTL

> **Target:** Staff/Principal Engineer | **Focus:** Distributed locking with Redis, lease mechanism, and production patterns

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
import redis.asyncio as redis
import uuid
import time
from typing import Optional

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
        return owner.decode() if owner else None
```

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
            owner_id=self.worker_id
        )
        
        if owner:
            self.active_leases[job_id] = {
                "owner": owner,
                "acquired_at": time.time(),
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
                print(f"⚠️ Lost lease on job {job_id}!")
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

### 1.4 Lease vs Other Distributed Locking

| Method | Atomic | TTL | Fault-tolerant | Use Case |
|--------|--------|-----|---------------|----------|
| **Redis SET NX EX** | ✅ | ✅ | ✅ (auto-expire) | Most common, simple |
| **Redlock** | ✅ | ✅ | ✅ (quorum) | Critical, multi-node safety |
| **PostgreSQL advisory lock** | ✅ | ❌ | ❌ (session-based) | DB-centric systems |
| **ZooKeeper ephemeral node** | ✅ | ✅ | ✅ | Coordination-heavy systems |
| **etcd lease** | ✅ | ✅ | ✅ | Kubernetes-native |

---

> **Previous:** [System, User & Assistant Roles](10_SYSTEM_USER_ASSISTANT_ROLES.md)
> **Next:** [Search Autocorrect & Misspelling Handling](12_SEARCH_AUTOCORRECT.md)
