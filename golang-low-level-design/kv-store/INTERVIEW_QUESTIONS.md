# 🗄️ In-Memory KV Store — Interview Questions

## Q1: Compare LRU vs LFU eviction. When would you use each?

**Answer:**
- **LRU:** Evicts items not accessed recently. Good for general caching (e.g., CDN, database query cache). Works well when recently accessed items are likely to be accessed again.
- **LFU:** Evicts items accessed infrequently. Better for content distribution (some items are "evergreen" popular). Can suffer from "cache pollution" (items that were once popular but no longer needed stay forever).

## Q2: How do you handle concurrent access efficiently?

**Answer:**
- `sync.RWMutex`: Multiple concurrent reads, exclusive writes
- Sharding: Partition keys across N independent stores (each with own lock)
- For read-heavy workloads (90%+), RWMutex is near-zero contention
- For write-heavy, shard by key hash to reduce lock contention

## Q3: How would you implement distributed sharding?

**Answer:**
- Consistent hashing on key to assign to node
- Virtual nodes for even distribution
- Replication factor 2-3 for fault tolerance
- Gossip protocol for cluster membership
- Read repair + anti-entropy for consistency

## Q4: How would you add persistence and recovery?

**Answer:**
- Write-ahead log (WAL) for durability
- Periodic snapshots (like Redis RDB)
- On restart: load latest snapshot + replay WAL
- For production: use embedded DB like BoltDB or Badger
