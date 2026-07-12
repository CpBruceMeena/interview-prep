# ☁️ AWS Storage & Database — Staff-Level Interview Questions

> *10 questions covering S3, RDS, DynamoDB, ElastiCache, Aurora, and storage architecture — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [S3: Storage Classes, Lifecycle, Performance](#1-s3-storage-classes-lifecycle-performance)
2. [S3: Data Consistency, Versioning, Replication](#2-s3-data-consistency-versioning-replication)
3. [RDS: Multi-AZ, Read Replicas, Performance Insights](#3-rds-multi-az-read-replicas-performance-insights)
4. [Aurora: Architecture, Storage, Serverless v2](#4-aurora-architecture-storage-serverless-v2)
5. [DynamoDB: Data Modeling, Partitioning, Hot Keys](#5-dynamodb-data-modeling-partitioning-hot-keys)
6. [DynamoDB: DAX, TTL, Streams, Global Tables](#6-dynamodb-dax-ttl-streams-global-tables)
7. [ElastiCache: Redis Cluster, Replication, Persistence](#7-elasticache-redis-cluster-replication-persistence)
8. [RDS Proxy & Connection Pooling](#8-rds-proxy-connection-pooling)
9. [Database Migration: DMS & Schema Conversion](#9-database-migration-dms-schema-conversion)
10. [S3 Glacier & Archival Strategies](#10-s3-glacier-archival-strategies)

---

## 1. S3: Storage Classes, Lifecycle, Performance

**Q:** "Design a data lake architecture storing 500TB of data with mixed access patterns: hot data (accessed daily), warm data (accessed monthly), cold data (accessed quarterly), and archive data (regulatory compliance, accessed <1%/year). How do S3 storage classes and lifecycle policies optimize cost? What are the performance limits of S3 for 10K PUTs/second?"

**What They're Really Testing:** Whether you understand S3's storage class economics and the performance characteristics of S3 at scale — including the impact of partition allocation on throughput.

### Answer

**S3 Storage Classes:**

```yaml
S3 Standard:
  - Durability: 99.999999999% (11 9's)
  - Availability: 99.99%
  - Min object size: 0 bytes
  - Retrieval: instant
  - Cost: $0.023/GB/month
  - Use: hot data (active datasets)

S3 Intelligent-Tiering:
  - Automatically moves between tiers based on access patterns
  - Tiers: Frequent, Infrequent, Archive Instant, Archive (90 days)
  - Monitoring fee: $0.0025/1000 objects
  - Use: unknown or unpredictable access patterns

S3 Standard-IA:
  - Availability: 99.9%
  - Min object size: 128KB (billed)
  - Retrieval fee: $0.01/GB
  - Cost: $0.0125/GB/month
  - Use: warm data, accessed infrequently

S3 One Zone-IA:
  - Availability: 99.5% (single AZ)
  - Cost: $0.01/GB/month
  - Use: reproducible data (can regenerate)

S3 Glacier Instant Retrieval:
  - Retrieval: milliseconds
  - Min storage: 90 days
  - Cost: $0.004/GB/month
  - Use: archive data needing instant access

S3 Glacier Flexible Retrieval:
  - Retrieval: 1-5 minutes (expedited), 3-5 hours (standard)
  - Min storage: 90 days
  - Cost: $0.0036/GB/month
  - Use: long-term archive

S3 Glacier Deep Archive:
  - Retrieval: 12 hours (standard)
  - Min storage: 180 days
  - Cost: $0.00099/GB/month
  - Use: regulatory compliance (7+ years)
```

**Lifecycle Policy:**

```yaml
# Lifecycle for data lake (500TB):
LifecycleConfiguration:
  Rules:
    - ID: "hot-to-warm"
      Filter:
        Prefix: "active/"
      Status: Enabled
      Transitions:
        - Days: 30
          StorageClass: STANDARD_IA         # After 30 days → warm
        - Days: 90
          StorageClass: GLACIER_INSTANT_RETRIEVAL  # After 90 days → archive instant
        - Days: 365
          StorageClass: DEEP_ARCHIVE        # After 1 year → deep archive
      Expiration:
        Days: 2555                          # After 7 years → delete

    - ID: "intelligent-tiering"
      Filter:
        Prefix: "unknown/"
      Status: Enabled
      Transitions:
        - Days: 0
          StorageClass: INTELLIGENT_TIERING  # Auto-manage from day 1

    - ID: "expire-incomplete-multiparts"
      Filter:
        Prefix: ""
      Status: Enabled
      AbortIncompleteMultipartUpload:
        DaysAfterInitiation: 7

# Cost comparison for 500TB over 7 years:
# All Standard: 500TB × $0.023 × 84 months = $966K
# Lifecycle managed: ~$200K (79% savings!)
```

**S3 Performance Limits:**

```yaml
# S3 performance characteristics:

# Single prefix: 3,500 PUT/POST/DELETE + 5,500 GET/HEAD per second
# Multi-prefix: no limit (distribute across prefixes)

# For 10K PUT/s:
# Need: 10,000 / 3,500 = 3 prefixes minimum
# Design: partition key as prefix
#   /user/123/  (prefix: user/123/)
#   /user/456/  (prefix: user/456/)
# Hash prefix: /{hash_prefix(4 chars)}/{year}/{month}/{day}/

# Example partition scheme:
s3://data-lake/ab12/2024/01/15/events-001.json
s3://data-lake/cd34/2024/01/15/events-002.json
s3://data-lake/ef56/2024/01/15/events-003.json

# PUT performance: 3,500 × N prefixes
# With 10,000 prefixes: 35M PUT/s
# With 1,000 prefixes: 3.5M PUT/s (more than enough)

# Multipart upload (for large objects >100MB):
# Upload in parallel parts (up to 10,000 parts)
# Each part can be uploaded in parallel
# For 10GB file: 100 parts × 100MB
# Parallel upload: completes in 1/100th of sequential time

# S3 Transfer Acceleration:
# Global uploads: uses CloudFront edge locations
# Improves upload speed by 50-500% for global users
# Cost: $0.04/GB (vs $0.00/GB standard)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage class economics** | Quantifies cost difference between classes, uses lifecycle for automatic transitions |
| **Performance limits** | Knows 3,500 PUT/s per prefix, uses hash prefixes for scale |
| **Lifecycle rules** | Applies transitions at appropriate intervals, includes expiration |
| **Multipart upload** | Uses parallel parts for large objects, knows 10,000 part limit |

---

## 2. S3: Data Consistency, Versioning, Replication

**Q:** "You're designing a system that writes objects to S3 and immediately reads them. Users report seeing stale data. Explain S3's read-after-write consistency model for new objects vs overwrite PUTs. How does S3 versioning prevent data loss? Design cross-region replication with RTO < 15 minutes."

**What They're Really Testing:** Whether you understand S3's consistency guarantees — strong consistency for PUTs of new objects (since Dec 2020) and the nuances of eventual consistency for other operations.

### Answer

**S3 Consistency Model (As of December 2020):**

```yaml
# Strong read-after-write consistency for ALL operations:
# - PUT of new objects: immediately readable
# - PUT of overwrites: immediately readable
# - DELETE operations: immediately reflected
# - HEAD/GET: returns latest version
# - List: eventually consistent (can take seconds to propagate)
# - Bucket configuration changes: eventually consistent

# What this means:
# Write object → immediately GET → returns the object (strong!)
# Write object → immediately LIST → MAY NOT appear yet (eventual)
# Delete object → immediately GET → 404 (strong!)
# Delete object → immediately LIST → MAY still appear (eventual)

# Pre-December 2020:
# - PUT new: strong
# - PUT overwrite: eventual (could read old version!)
# - DELETE: eventual

# Impact: Most applications don't need special handling anymore
# But: LIST consistency is STILL eventual
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-s3-consistency.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated S3 Strong Consistency Model — read-after-write, strong deletes, and LIST eventual consistency — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

**S3 Versioning:**

```yaml
# Versioning prevents accidental deletion and overwrite:
# - Each object version gets unique version ID
# - DELETE creates a delete marker (not permanent deletion)
# - Delete marker hides the object, not deletes it
# - Permanently delete: specify version ID

# Versioning states:
#   Unversioned (default)
#   Enabled (irreversible — can suspend, but never disable)
#   Suspended (no new versions, existing versions retained)

# Lifecycle with versioning:
LifecycleRule:
  - ID: "expire-old-versions"
    Filter:
      Prefix: "logs/"
    Status: Enabled
    NoncurrentVersionExpiration:
      NoncurrentDays: 90       # Delete noncurrent versions after 90 days
    NoncurrentVersionTransitions:
      - NoncurrentDays: 30
        StorageClass: STANDARD_IA

# MFA Delete:
# Require MFA to permanently delete versions
# Protects against accidental or malicious deletion
# Only enabled with versioning
```

**Cross-Region Replication (CRR):**

```yaml
# CRR configuration for RTO < 15 minutes:

ReplicationConfiguration:
  Role: arn:aws:iam::123456789:role/s3-crr-role
  
  Rules:
    - ID: "crr-to-dr-region"
      Status: Enabled
      Priority: 1
      
      Filter:
        Prefix: "critical-data/"
      
      Destination:
        Bucket: arn:aws:s3:::dr-bucket-us-west-2
        StorageClass: STANDARD
        ReplicationTime:            # S3 Replication Time Control (S3 RTC)
          Status: Enabled
          Time: 15                   # 15-minute SLA to replicate 99.99% of objects
        
        Metrics:
          Status: Enabled
          EventThreshold:
            Minutes: 15
        
      SourceSelectionCriteria:
        SseKmsEncryptedObjects:
          Status: Enabled            # Replicate SSE-KMS encrypted objects too
      
      DeleteMarkerReplication:
        Status: Enabled              # Replicate delete markers
      
      # Same-Region Replication (SRR):
      # Use for: log aggregation across accounts, prod→test sync

# Replication metrics:
# - BytesPending: objects pending replication
# - OperationsPending: operations pending
# - ReplicationLatency: time to replicate (S3 RTC guarantees <15 min)
# - MaxReplicationLag: in seconds

# Replication time without RTC: 15-30 minutes
# Replication time with RTC: <15 minutes (SLA)
```

**S3 Batch Operations:**

```yaml
# Batch operations for large-scale object management:

# 1. Batch invoke Lambda:
# Process 100M objects → invoke Lambda on each
# Use: transform data, re-encrypt, change storage class

# 2. Batch copy:
# Copy 100M objects between buckets
# Use: migration, replication backfill

# 3. Batch restore:
# Restore 100M Glacier objects to Standard
# Use: bulk retrieval for compliance audit

# Manifest: S3 inventory report (list of objects)
# Batch job progress: CloudWatch Events
# Completion: SNS notification
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Consistency model** | Knows all operations are strongly consistent (since Dec 2020), LIST is eventual |
| **Versioning** | Uses versioning for data protection, lifecycle for old version cleanup |
| **CRR with RTC** | Configures S3 RTC for 15-minute replication SLA |
| **Delete marker replication** | Replicates delete markers for consistent DR state |

---

## 3. RDS: Multi-AZ, Read Replicas, Performance Insights

**Q:** "Your PostgreSQL database is experiencing performance degradation during peak hours (10K TPS). Queries are taking 5-10 seconds during spikes. Design an RDS scaling strategy using Multi-AZ, read replicas, and Performance Insights. How do you identify the bottleneck queries? When does Multi-AZ not help with read performance?"

**What They're Really Testing:** Whether you understand the operational differences between Multi-AZ (HA, not scaling) and read replicas (read scaling, not HA) — and how to use Performance Insights to identify bottlenecks.

### Answer

**Multi-AZ vs Read Replicas:**

```yaml
Multi-AZ:
  - Purpose: High availability (not read scaling!)
  - Architecture: primary in AZ-A, standby in AZ-B
  - Replication: synchronous (committed on both before ack)
  - Failover: automatic (60-120s DNS change)
  - Read/write: only from primary (standby is NOT readable)
  - Cost: 2× compute + 2× storage
  - Performance impact: minor (sync replication adds ~1-5ms)

  # Common misconception: Multi-AZ offloads reads
  # WRONG! Standby is NOT accessible for reads
  # Multi-AZ only protects against AZ failure

Read Replicas:
  - Purpose: Read scaling (not HA!)
  - Architecture: primary in AZ-A, replicas in any AZ
  - Replication: asynchronous (<100ms lag typical)
  - Failover: manual (promote replica to primary)
  - Read/write: replicas are READ-ONLY
  - Cost: each replica = full compute + full storage
  - Performance impact: minor on primary (async replication)

Scaling strategy for 10K TPS:
  # Analyze workload: 70% reads, 30% writes
  # Read replicas: 5 replicas
  #   Each replica: 2K TPS read
  #   Total read throughput: 10K TPS
  #   Write throughput: 3K TPS (single primary)
  
  # If writes are bottleneck: switch to Aurora or shard
```

**Performance Insights:**

```yaml
# Performance Insights dashboard:

# Top SQL by average active sessions:
┌──────────────────────────────────────┬────────────┬─────────┐
│ SQL                                  │ Avg Active │ Wait    │
├──────────────────────────────────────┼────────────┼─────────┤
│ SELECT * FROM orders WHERE ...       │    45      │ IO:Data │
│ UPDATE inventory SET qty = qty - 1 ..│    12      │ Lock:Row│
│ INSERT INTO audit_log ...            │     8      │ IO:Log  │
└──────────────────────────────────────┴────────────┴─────────┘

# Common wait events and fixes:
Wait Event                  | Cause                        | Solution
----------------------------|------------------------------|--------------------------
IO:DataFileRead             | Full table scan, missing idx | Add index, optimize query
IO:WALWrite                 | Too many write operations    | Batch writes, reduce fsync
Lock:RowExclusive           | Row contention/blocking      | Optimize transaction length
CPU:Quantum                 | Compute-bound                | Increase instance size
Network:Throughput          | Large result sets            | Pagination, limit columns

# Performance Insights metrics to monitor:
# - DBLoad: average active sessions (should be < CPU count)
# - DBLoadCPU: CPU-bound sessions
# - DBLoadWait: wait-bound sessions
# - CPUCreditBalance (burstable instances)
```

**Connection Pooling with RDS Proxy:**

```yaml
# RDS Proxy manages database connections:
# Problem: 10K TPS × 100ms query = 1000 concurrent connections
#          Each connection = ~2MB memory
#          Total: 2GB just for connection overhead!

# RDS Proxy:
# - Connection multiplexing: 1000 app connections → 10 DB connections
# - 99% reduction in database connection overhead
# - Connection pooling: reuse connections
# - IAM authentication: no DB password in application config
# - Failover: proxy maintains connections during Multi-AZ failover
# - Cost: $0.015/hour per vCPU of RDS instance

RDS Proxy configuration:
  Proxy:
    EngineFamily: POSTGRESQL
    RoleARN: arn:aws:iam::123456789:role/rds-proxy-role
    VpcSubnetIds:
      - subnet-abc
      - subnet-def
    SecurityGroups:
      - sg-proxy
    IdleClientTimeout: 1800           # 30 minutes idle timeout
    MaxConnectionsPercent: 100        # % of max DB connections
    SessionPinningFilters:
      - EXCLUDE_VARIABLE_SESSIONS     # Don't pin for session variables
    RequireTLS: true

# Application connection string:
# Before: jdbc:postgresql://my-db.xyz.us-east-1.rds.amazonaws.com:5432/mydb
# After:  jdbc:postgresql://my-proxy.proxy-xyz.us-east-1.rds.amazonaws.com:5432/mydb
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-AZ vs replicas** | Clearly distinguishes HA (Multi-AZ) from read scaling (replicas) |
| **Performance Insights** | Uses wait events to diagnose bottlenecks (IO vs Lock vs CPU) |
| **Connection pooling** | Uses RDS Proxy to reduce connection overhead by 90%+ |
| **Scaling strategy** | Combines replicas for reads, proxy for connections, right-sizing for compute |

---

## 4. Aurora: Architecture, Storage, Serverless v2

**Q:** "Design a database architecture for a global SaaS application requiring: 99.99% availability, <10ms write latency in-region, <100ms cross-region read latency, and automatic scaling from 100 to 100K transactions per second. How does Aurora's distributed storage layer work? Compare Aurora Serverless v2 vs provisioned."

**What They're Really Testing:** Whether you understand Aurora's architecture at the storage layer — the 6-replica quorum, log-structured storage, and how the cluster volume enables fast cloning and replication.

### Answer

**Aurora's Distributed Storage Architecture:**

```yaml
Aurora separates compute from storage:

Compute Layer (EC2-based):
  ┌────────────┐  ┌────────────┐  ┌────────────┐
  │  Writer     │  │  Reader 1  │  │  Reader 2  │
  │  (primary)  │  │  (replica) │  │  (replica) │
  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
         ┌───────────────▼───────────────────┐
         │      Aurora Cluster Volume         │
         │    (Virtual, up to 128TB)         │
         │                                     │
         │  ┌──────┐ ┌──────┐ ┌──────┐       │
         │  │SSD   │ │SSD   │ │SSD   │ ...   │
         │  │AZ-1  │ │AZ-1  │ │AZ-2  │       │
         │  └──────┘ └──────┘ └──────┘       │
         │  ┌──────┐ ┌──────┐ ┌──────┐       │
         │  │SSD   │ │SSD   │ │SSD   │ ...   │
         │  │AZ-2  │ │AZ-3  │ │AZ-3  │       │
         │  └──────┘ └──────┘ └──────┘       │
         └─────────────────────────────────────┘

Key properties:
  - 6 storage replicas across 3 AZs (6 copies of data)
  - Writes: need 4/6 acknowledgments (write quorum)
  - Reads: any 3/6 storage nodes (read quorum)
  - Continuous backup to S3 (no backup window!)
  - Crash recovery: <60 seconds (even for 128TB)
  - Storage billing: $0.10/GB/month (vs $0.115/GB for RDS GP2)
```

**Aurora Write Path:**

```yaml
# Aurora doesn't write data pages. It writes REDO LOG records only.

Writer instance:
  ┌──────────────────────┐
  │  BEGIN;              │
  │  UPDATE balance = -100;│
  │  COMMIT;             │
  │                      │
  │  → Write redo log    │
  │    (NOT data pages!) │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Aurora Cluster Volume│
  │                      │
  │  Redo log → 4/6      │
  │  storage nodes ack   │
  │  → COMMIT complete!  │
  │                      │
  │  (Data pages lazily  │
  │   materialized)      │
  └──────────────────────┘

# Performance impact:
# - Only redo log written to storage (4KB vs 8KB data pages)
# - 1/10th the I/O of traditional MySQL/PostgreSQL
# - Write amplification: ~2x vs ~10x (traditional DB)
# - 6-way replication at storage layer (no replication overhead on writer)

# Reader instances:
# - Apply redo log from cluster volume (async)
# - Reader lag: typically <10ms
# - No storage writes on readers → no performance impact
```

**Aurora Serverless v2:**

```yaml
# Aurora Serverless v2 (vs provisioned):

Provisioned:
  - Fixed instance size (e.g., r6g.4xlarge = 16 vCPU, 128GB RAM)
  - Manual scaling: modify instance class (5-10 min downtime)
  - Cost: hourly rate × hours (24/7 billing)
  - Best for: predictable workloads

Serverless v2:
  - Auto-scaling: 0.5 ACU to 256 ACU (1 ACU = 2GB RAM + CPU)
  - Scaling: instant (no downtime, no connection disruption)
  - Scaling granularity: 0.5 ACU increments
  - Cost: ACU-hours consumed (can scale to 0 for dev)
  - Best for: variable/unknown workloads, dev/test

# Scaling characteristics:
# - Scale up: 30 seconds to 10× capacity
# - Scale down: 30 seconds to minimum
# - Pause: after 15 minutes of inactivity (no compute cost!)
# - Resume: <30 seconds

# Capacity planning:
# 100 TPS → 2 ACU (night) → $0.25/hour
# 100K TPS → 256 ACU (peak) → $32/hour
# Average: 20 ACU → $2.50/hour → $1,800/month

# ACU sizing guide:
# 1 ACU ≈ 2GB RAM, moderate CPU
# 1000 TPS (simple queries) ≈ 10 ACU
# 1000 TPS (complex joins) ≈ 50 ACU
```

**Global Database:**

```yaml
# Aurora Global Database:
# - Primary region: writer + local readers
# - Secondary regions: up to 5 read-only replicas
# - Replication: <1 second (AWS backbone)
# - RTO: <1 minute (promote secondary to primary)
# - RPO: <1 second (data loss in extreme failure)
# - Cost: separate compute in each region + cross-region data transfer

Global cluster:
  Primary: us-east-1 (writer + 2 readers)
  Secondary: eu-west-1 (1 reader) → promote if us-east-1 fails
  Secondary: ap-southeast-1 (1 reader)

# Failover:
# 1. Detect primary region failure (health check)
# 2. Promote eu-west-1 reader to writer
# 3. Update application connection string
# 4. Total: <1 minute RTO, <1 second RPO

# Cross-region read latency:
# US → EU: ~80ms (network round trip)
# US → Asia: ~150ms
# Local reads: <5ms (same region)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage architecture** | Explains 6-replica quorum, redo-log-only writes, crash recovery <60s |
| **Serverless v2** | Understands ACU model, instant scaling, pause/resume for dev |
| **Global Database** | Designs multi-region architecture with sub-1s replication |
| **Write amplification** | Quantifies Aurora's 2x vs traditional DB's 10x write amplification |

---

## 5. DynamoDB: Data Modeling, Partitioning, Hot Keys

**Q:** "Design a DynamoDB table for a social media feed service: 10K writes/second (new posts), 100K reads/second (feed queries), each user has up to 1000 followers. How do you model the data for efficient access patterns? What happens when a celebrity posts and 1M followers query simultaneously? How do you prevent hot keys?"

**What They're Really Testing:** Whether you understand DynamoDB's partition mechanics — how partition key design affects throughput, and how to use access patterns to drive table design (single-table design).

### Answer

**DynamoDB Partition Mechanics:**

```yaml
# Each partition:
# - Max storage: 10GB
# - Max throughput: 3000 RCU or 1000 WCU
# - Partition count = max(ceil(total RCU/3000), ceil(total WCU/1000), ceil(storage/10GB))

# For 10K writes + 100K reads:
#   Write partitions: 10,000 / 1000 = 10 partitions
#   Read partitions: 100,000 / 3000 = 34 partitions
#   Total partitions: max(10, 34) = 34 partitions
#
# Each partition gets: 294 WCU + 2941 RCU

# Hot key = all traffic to single partition
# If user "celebrity" has 1M followers:
#   All 1M queries hit the same partition (if celebrity is sole partition key)
#   That partition: 3000 RCU → only 3000 reads processed
#   Remaining 997,000 reads: throttled!

# Prevention strategies:
# 1. Shard the hot key (add suffix: celeb#1, celeb#2, ...)
# 2. Use DAX cache (absorb reads)
# 3. Adaptive capacity (DynamoDB can burst unused capacity to hot partitions)
```

**Single-Table Design (Social Feed):**

```yaml
# Single-table design for social media feed:

# Access patterns:
# 1. Get user profile by user_id
# 2. Get posts by user_id (sorted by created_at DESC)
# 3. Get feed for user (posts from followed users)
# 4. Get followers of user
# 5. Get users that user follows

Table: social-feed
  Partition Key: pk (string)
  Sort Key: sk (string)
  GSI1: gsi1pk (string) → gsi1sk (string)

# Data model:
pk                    | sk                    | type     | data
----------------------|-----------------------|----------|-----------------------
USER#alice            | PROFILE               | profile  | name, avatar, bio
USER#alice            | POST#2024-01-15T10:30 | post     | content, likes, shares
USER#alice            | POST#2024-01-14T08:00 | post     | content, likes, shares
USER#alice            | FOLLOWER#bob          | follower | followed_at
USER#alice            | FOLLOWING#charlie     | following| followed_at
USER#bob              | PROFILE               | profile  | name, avatar, bio
USER#bob              | POST#2024-01-15T09:00 | post     | content, likes, shares
FEED#alice           | CHARLIE#2024-01-15    | feed     | post_id, author, content

# Query patterns:

# 1. Get user profile:
Query: pk = "USER#alice" AND sk = "PROFILE"

# 2. Get user's posts (sorted by date DESC):
Query: pk = "USER#alice" AND sk BEGINS_WITH "POST#"
  ScanIndexForward: false
  Limit: 20

# 3. Get followers (GSI on sk prefix):
GSI1 pk: "FOLLOWER#alice" (inverted index)
GSI1 sk: "USER#bob"
# Actually: use GSI with pk = "FOLLOWER#alice", sk = followed_at

# 4. Get feed for user:
BatchGet: FEED#alice entries (pre-computed fan-out)
```

**Fan-Out on Write (Celebrity Post Pattern):**

```yaml
# When celebrity posts, 1M followers need feed update:

# Option 1: Fan-out on write (push model)
# Pro: Read is fast (just query feed table)
# Con: Write is expensive (1M writes for 1 post)

# Option 2: Fan-out on read (pull model)
# Pro: Write is cheap (1 write for post)
# Con: Read is expensive (query all followed users' posts + merge)

# Hybrid approach:
# - Normal users: fan-out on write (< 1000 followers → manageable)
# - Celebrities (> 100K followers): fan-out on read

# Implementation:
def create_post(post, user):
    # 1. Write post to posts table
    posts.put(post)
    
    # 2. Get follower count
    followers = get_follower_count(user.id)
    
    if followers < 1000:
        # Fan-out on write for small accounts
        fanout_post_sync(post, followers)
    else:
        # Fan-out on read for celebrities
        # Store post with flag: celebrity_content = true
        # Readers will fetch celebrity posts separately
        pass

def get_feed(user_id):
    # Get pre-computed feed (from followed users)
    feed_items = feed_table.query(pk=f"FEED#{user_id}")
    
    # Also fetch celebrity posts
    celebrity_ids = get_followed_celebrities(user_id)
    for celeb_id in celebrity_ids:
        celeb_posts = posts_table.query(
            pk=f"USER#{celeb_id}",
            sk_begins_with="POST#",
            limit=5
        )
        feed_items.merge(celeb_posts)
    
    return feed_items.sorted(by_date, desc=True)
```

**Hot Key Mitigation:**

```yaml
# Strategies for dealing with hot keys:

# Strategy 1: Shard the hot key
# Instead of: pk = "ITEM#ABC123"
# Use:        pk = "ITEM#ABC123#0" to "ITEM#ABC123#N"

def get_item(id):
    # Write: pick random shard
    shard = random.randint(0, 9)
    dynamodb.put(
        pk=f"ITEM#{id}#{shard}",
        data=item_data
    )
    
    # Read: read ALL shards and merge
    for shard in range(10):
        items.append(dynamodb.get(pk=f"ITEM#{id}#{shard}"))
    
    return merge(items)

# Strategy 2: DAX cache (30-second TTL absorbs read spikes)
# DynamoDB Accelerator: in-memory cache, microsecond latency
# 1M reads/s: DAX handles 99% cache hit rate → 10K reads hit DynamoDB

# Strategy 3: Adaptive capacity (DynamoDB built-in)
# DynamoDB can temporarily burst unused capacity
# If 34 partitions: each has 2941 RCU
# If 33 partitions idle, 1 hot partition can use their unused capacity

# Strategy 4: Exponential backoff + client-side caching
# When throttled, cache the result locally for 1-2 seconds
# Reduces read pressure on hot partition
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Partition math** | Calculates partition count from throughput requirements |
| **Hot key handling** | Uses sharding, DAX, adaptive capacity, or hybrid fan-out |
| **Single-table design** | Models access patterns with composite keys and GSIs |
| **Fan-out trade-off** | Explains push vs pull for different scale users |

---

## 6. DynamoDB: DAX, TTL, Streams, Global Tables

**Q:** "You need to add a TTL-based data expiration, real-time streaming to a search index, and global replication for your DynamoDB table. How does DynamoDB TTL work? How do DynamoDB Streams enable event-driven processing? Compare Global Tables vs application-level replication."

**What They're Really Testing:** Whether you understand DynamoDB's built-in features for time-based expiration, change data capture, and multi-region replication.

### Answer

**DynamoDB TTL:**

```yaml
# TTL automatically deletes items after a specified timestamp

# 1. Add a TTL attribute to your item
# 2. Enable TTL on the table pointing to that attribute
# 3. DynamoDB deletes items when TTL expires

{
  "pk": "SESSION#abc123",
  "sk": "TOKEN",
  "data": "encrypted_token_data",
  "ttl": 1705334400,       // Unix epoch timestamp (e.g., Jan 15, 2024)
  "expires_at": "2024-01-15T12:00:00Z"  // Human-readable (not used for TTL)
}

# TTL behavior:
# - DynamoDB checks items periodically (within 48 hours of expiry)
# - Delete happens within 48 hours of TTL expiry (no guarantee on exact time)
# - Deleted items appear in Streams (with userIdentity = "TTL_EXPIRY")
# - TTL deletes consume no write capacity (FREE!)
# - Table billing: no cost for TTL deletions

# Use cases:
# - Session management (delete expired sessions)
# - Event sourcing (delete old events after retention period)
# - Leaderboard (delete old scores)
# - Temporary data (OTP codes, reset tokens)

# Monitoring TTL:
CloudWatch:
  Metric: TimeToLiveDeletedItemCount
  Alarm: if > 10,000/day → notify (normal cleanup volume)
```

**DynamoDB Streams:**

```yaml
# DynamoDB Streams capture item-level changes:
# - INSERT: new item created
# - MODIFY: item updated
# - REMOVE: item deleted (including TTL expiry)

# Stream record:
{
  "eventID": "1",
  "eventName": "INSERT",          // INSERT, MODIFY, REMOVE
  "eventSource": "aws:dynamodb",
  "awsRegion": "us-east-1",
  "dynamodb": {
    "SequenceNumber": "123456",
    "SizeBytes": 1024,
    "StreamViewType": "NEW_AND_OLD_IMAGES",  // NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES, KEYS_ONLY
    "Keys": {"pk": {"S": "USER#alice"}, "sk": {"S": "PROFILE"}},
    "NewImage": {  // Present for INSERT and MODIFY
      "pk": {"S": "USER#alice"},
      "sk": {"S": "PROFILE"},
      "name": {"S": "Alice"},
      "ttl": {"N": "1705334400"}
    },
    "OldImage": {  // Present for MODIFY and REMOVE
      "pk": {"S": "USER#alice"},
      "sk": {"S": "PROFILE"},
      "name": {"S": "Alice"},
      "version": {"N": "1"}
    }
  },
  "userIdentity": {
    "principalId": "dynamodb.amazonaws.com",
    "type": "Service",
    // For TTL deletions: userIdentity = "TTL_EXPIRY"
  }
}

# Stream → Lambda → Elasticsearch:
dynamodb_stream → lambda → elasticsearch.index(document)

# Processor:
def lambda_handler(event, context):
    for record in event['Records']:
        if record['eventName'] == 'INSERT' or record['eventName'] == 'MODIFY':
            # Index to Elasticsearch
            item = record['dynamodb']['NewImage']
            es.index(
                index='users',
                id=item['pk']['S'],
                body=item
            )
        elif record['eventName'] == 'REMOVE':
            # Remove from search index
            item = record['dynamodb']['Keys']
            es.delete(
                index='users',
                id=item['pk']['S']
            )
```

**Global Tables:**

```yaml
# DynamoDB Global Tables:
# - Multi-region, multi-writer replication
# - Active-active: writes in any region → replicated to all regions
# - Conflict resolution: last writer wins (based on timestamp)
# - Replication latency: <1 second (typically)
# - No application changes needed (uses DynamoDB Streams internally)

Global table setup:
  Table: users (us-east-1)  →  replica table (eu-west-1)
                             →  replica table (ap-southeast-1)

# Replication flow:
# 1. Client writes to us-east-1 table
# 2. DynamoDB captures change via Streams
# 3. DynamoDB Streams → cross-region replication → eu-west-1
# 4. eu-west-1 replica receives the update
# 5. Client in eu-west-1 can now read the update

# Conflict resolution (last writer wins):
# Two clients update the same item simultaneously in different regions:
#   us-east-1: update balance = 100 @ t1
#   eu-west-1: update balance = 200 @ t2
#   Last writer wins (t2 > t1) → balance = 200
# This can cause DATA LOSS if both updates modify different fields!
# Solution: Use conditional updates with version numbers

# Conditional writes with version:
def update_balance(user_id, delta, expected_version):
    response = table.update_item(
        Key={'pk': f"USER#{user_id}"},
        UpdateExpression="SET balance = balance + :delta, version = version + :inc",
        ConditionExpression="version = :expected_version",
        ExpressionAttributeValues={
            ':delta': delta,
            ':inc': 1,
            ':expected_version': expected_version
        }
    )
    return response['Attributes']['version']  # New version

# Global Tables vs application-level replication:
# Global Tables:
#   - Managed replication (no code)
#   - <1 second latency
#   - Last-writer-wins conflict resolution
#   - Cost: Streams + cross-region data transfer
#
# Application-level:
#   - Custom conflict resolution
#   - Higher latency (application logic)
#   - More code complexity
#   - Can do CRDT-style merging
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **TTL mechanics** | Knows TTL is free, deletions appear in streams, expiry within 48 hours |
| **Stream processing** | Uses Streams → Lambda for real-time indexing, audit, notifications |
| **Global Tables** | Understands multi-writer replication, last-writer-wins conflicts |
| **Conflict handling** | Uses conditional writes with version numbers for safe concurrent updates |

---

## 7. ElastiCache: Redis Cluster, Replication, Persistence

**Q:** "Design a Redis cluster for a real-time leaderboard with 10M users and 100K score updates/second. How does Redis Cluster shard data? How do you choose between persistence options (AOF vs RDB)? Compare ElastiCache for Redis vs MemoryDB for Redis."

**What They're Really Testing:** Whether you understand Redis Cluster's hash slot partitioning, the trade-offs of Redis persistence, and when to choose MemoryDB over ElastiCache.

### Answer

**Redis Cluster Architecture:**

```yaml
# Redis Cluster: 16384 hash slots distributed across shards
# Key → CRC16(key) % 16384 → hash slot → shard

# Example: 6-node cluster, 3 shards (1 primary + 1 replica each)

Shard 1 (slots 0-5460):
  Primary: redis-001.xxxxx.0001.use1.cache.amazonaws.com:6379
  Replica: redis-001.xxxxx.0002.use1.cache.amazonaws.com:6379

Shard 2 (slots 5461-10922):
  Primary: redis-002.xxxxx.0001.use1.cache.amazonaws.com:6379
  Replica: redis-002.xxxxx.0002.use1.cache.amazonaws.com:6379

Shard 3 (slots 10923-16383):
  Primary: redis-003.xxxxx.0001.use1.cache.amazonaws.com:6379
  Replica: redis-003.xxxxx.0002.use1.cache.amazonaws.com:6379

# For 100K score updates/second:
# Each Redis primary: ~50K-100K ops/s (single-threaded!)
# Need: 2-3 primaries (each handles ~35K ops/s)
# With 3 shards: 3 × 50K = 150K ops/s (headroom)

# Routing: client-side (Redis Cluster client library)
# Client computes hash slot → connects to correct shard
# MOVED redirect: if slot moved (resharding), client follows redirect
```

**Leaderboard Design (Sorted Sets):**

```redis
# Real-time leaderboard using Redis Sorted Sets:

# Add/update score:
ZADD leaderboard:global 1500 "user:alice"
ZADD leaderboard:global 2000 "user:bob"  
ZADD leaderboard:global 1800 "user:charlie"

# Get top 10:
ZREVRANGE leaderboard:global 0 9 WITHSCORES
# Returns: bob(2000), charlie(1800), alice(1500)

# Get user rank:
ZREVRANK leaderboard:global "user:alice"
# Returns: 2 (0-indexed, so 3rd place)

# Get scores near user:
ZREVRANGEBYSCORE leaderboard:global 2000 1500 WITHSCORES LIMIT 0 10

# Daily leaderboard:
ZADD leaderboard:2024-01-15 1500 "user:alice"

# Weekly aggregation:
ZUNIONSTORE leaderboard:week-3 7
  leaderboard:2024-01-15 leaderboard:2024-01-16 ... leaderboard:2024-01-21
  WEIGHTS 1 1 1 1 1 1 1
  AGGREGATE SUM

# For 10M users, 100K updates/s:
# Memory: 10M × (user_id(20B) + score(8B) + overhead(40B)) ≈ 680MB
# Update rate: 100K/s → 100K ZADD/s
# With 3 shards: 33K ZADD/s per shard → within Redis capacity
```

**Persistence Options:**

```yaml
RDB (Redis Database file):
  - Snapshot: point-in-time dump of all data
  - Schedule: every 5/15/60 minutes (configurable)
  - File: dump.rdb (compressed binary)
  - Recovery: load file on startup
  - Data loss: up to 5 minutes of writes (if crash between snapshots)
  - Performance impact: low (fork + background save)
  - Use: cache (recoverable from source)

AOF (Append Only File):
  - Log: every write operation appended
  - fsync: every second (default), every write, or never
  - File: appendonly.aof (text protocol)
  - Recovery: replay log on startup
  - Data loss: up to 1 second (with fsync=everysec)
  - Performance impact: moderate (10-20% overhead)
  - Rewrite: background rewrite (BGREWRITEAOF) to compact

AOF + RDB combined (Redis 7+):
  - RDB for fast startup + AOF for durability
  - Best of both: fast recovery + minimal data loss

# ElastiCache for Redis:
# - Default: no persistence (cache only)
# - Option: Multi-AZ with automatic failover
# - Backup: snapshot to S3 (manual or scheduled)
# - Data loss: up to 5 minutes if Multi-AZ not enabled
# - RTO: 60-120 seconds (failover + recovery)

# MemoryDB for Redis:
# - Durable: data stored in Multi-AZ transaction log
# - RPO: near-zero (data written to durable storage before ack)
# - Recovery: automatic from transaction log
# - 99.99% availability (vs 99.9% for ElastiCache)
# - 3× cost multiplier vs ElastiCache
# - Use: primary database, not just cache
```

**ElastiCache vs MemoryDB:**

```yaml
Feature                | ElastiCache (Redis) | MemoryDB
-----------------------|---------------------|-----------------
Data durability        | Snapshot to S3      | Multi-AZ transaction log
RPO (data loss)        | Up to 5 min        | Near-zero
RTO (recovery)         | 60-120 sec         | <30 seconds
Write throughput       | Same (Redis engine) | Same (Redis engine)
Read replicas          | Up to 5 per shard   | Up to 5 per shard
Multi-AZ               | Yes                 | Yes (built-in)
Use case               | Cache, session store| Primary database
Cost (node)            | 1x                  | 3x

# When to use which:
# ElastiCache: caching, session storage, rate limiting
# MemoryDB: leaderboard (source of truth), real-time analytics, durable counters
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cluster sharding** | Explains 16384 hash slots, client-side routing, MOVED redirects |
| **Sorted sets** | Uses ZADD/ZREVRANGE for real-time leaderboard |
| **Persistence trade-offs** | Compares RDB (fast, up to 5min loss) vs AOF (durable, slower) |
| **MemoryDB** | Knows when to choose durable Redis (MemoryDB) over cache-only (ElastiCache) |

---

## 8. RDS Proxy & Connection Pooling

**Q:** "Your serverless application uses 1000 Lambda functions that each create a new database connection on every invocation. At 100 TPS, you're hitting 'too many connections' errors. Design a connection pooling strategy using RDS Proxy. How does it handle IAM authentication vs password-based auth?"

**What They're Really Testing:** Whether you understand the connection overhead problem in serverless architectures and how RDS Proxy solves it with connection multiplexing.

### Answer

**The Connection Problem:**

```yaml
# Without RDS Proxy:
# 1000 Lambda functions × 1 connection each = 1000 connections to DB
# Each PostgreSQL connection: ~2MB memory
# Total: 2GB for connections alone!

# Lambda cold start: Creates new connection (~500ms overhead)
# Lambda hot: may reuse cached connection (if global scope)
# But: Lambda execution environment may be recycled anytime
# Result: many short-lived connections, high connection churn

# RDS max_connections default:
#   db.r6g.large: 648 connections (2 vCPU × 324)
#   db.r6g.xlarge: 1296 connections (4 vCPU × 324)
#   db.r6g.2xlarge: 2586 connections (8 vCPU × 324)

# At 100 TPS with 500ms query time: 50 active connections
# But connection storms can create 1000+ connections
# → "FATAL: too many connections for role"
```

**RDS Proxy Architecture:**

```yaml
# RDS Proxy sits between application and database:
# Application → RDS Proxy (1000 connections) → Database (10 connections)
# Multiplexing: 1000 app connections → 10 DB connections → 100× reduction!

┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Lambda: 1 conn  │───▶│                 │───▶│                │
│ Lambda: 1 conn  │───▶│  RDS Proxy      │───▶│  RDS Database  │
│ Lambda: 1 conn  │───▶│                 │───▶│  (10 actual    │
│ ...             │───▶│  Connection     │───▶│   connections) │
│ Lambda: 1000    │───▶│  Pool (10-100)  │───▶│                │
└────────────────┘    └────────────────┘    └────────────────┘

# RDS Proxy features:
# - Connection pool: configurable min/max connections
# - Connection reuse: return connection to pool after transaction
# - IAM auth: authenticate with IAM role (no password in config!)
# - Failover: maintains proxy connections during Multi-AZ failover
# - TLS: encrypted connections between proxy and DB
```

**IAM Authentication with RDS Proxy:**

```python
# IAM authentication (no password in code!):

import boto3
import psycopg2

def get_db_connection():
    # Generate IAM auth token (valid for 15 minutes)
    rds_client = boto3.client('rds')
    
    token = rds_client.generate_db_auth_token(
        DBHostname='my-proxy.proxy-xyz.us-east-1.rds.amazonaws.com',
        Port=5432,
        DBUsername='iam_user',
        Region='us-east-1'
    )
    
    # Connect using IAM token
    conn = psycopg2.connect(
        host='my-proxy.proxy-xyz.us-east-1.rds.amazonaws.com',
        port=5432,
        database='mydb',
        user='iam_user',
        password=token,               # IAM token as password!
        sslmode='require'
    )
    
    return conn

# IAM policy for Lambda execution role:
{
    "Effect": "Allow",
    "Action": "rds-db:connect",
    "Resource": "arn:aws:rds-db:us-east-1:123456789:dbuser:*/iam_user"
}

# Benefits:
# - No database passwords in Lambda environment variables
# - Credentials rotate automatically (IAM token expires after 15 min)
# - Fine-grained access: each Lambda function has its own IAM role
# - Audit trail: CloudTrail logs who connected and when
```

**RDS Proxy Configuration:**

```yaml
# RDS Proxy configuration for Lambda + RDS:

RDSProxy:
  DBProxyName: my-app-proxy
  EngineFamily: POSTGRESQL
  
  # IAM role for proxy (to access Secrets Manager and RDS):
  RoleARN: arn:aws:iam::123456789:role/rds-proxy-role
  
  Auth:
    - AuthScheme: SECRETS
      SecretArn: arn:aws:secretsmanager:us-east-1:123456789:secret:db-creds
      IAMAuth: REQUIRED
  
  VpcSubnetIds:
    - subnet-abc
    - subnet-def
    - subnet-ghi
  
  VpcSecurityGroupIds:
    - sg-proxy
  
  IdleClientTimeout: 1800           # 30 min: close idle connections
  RequireTLS: true                  # Enforce TLS
  
  ConnectionPoolConfigurationInfo:
    MaxConnectionsPercent: 100      # % of RDS max_connections
    MaxIdleConnectionsPercent: 50   # Keep 50% idle in pool
    ConnectionBorrowTimeout: 5000   # 5s timeout waiting for connection
    SessionPinningFilters:
      - EXCLUDE_VARIABLE_SESSIONS   # Don't pin for SET commands
    InitQuery: "SET application_name = 'my_app'"  # Run on new connections
    
# Connection pool sizing:
# Max DB connections: 1000 (RDS max_connections)
# MaxConnectionsPercent: 100 → pool can use up to 1000
# MaxIdleConnectionsPercent: 50 → keep 500 idle
# Actual active: whatever the workload needs (up to 1000)

# Target: 10-20 active DB connections for 100 TPS
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Connection overhead** | Quantifies memory per connection (2MB PostgreSQL) |
| **Multiplexing** | Explains how 1000 app connections → 10 DB connections |
| **IAM auth** | Generates auth tokens without storing passwords |
| **Pool sizing** | Configures connection pool based on workload and DB capacity |

---

## 9. Database Migration: DMS & Schema Conversion

**Q:** "You need to migrate a 5TB Oracle database to Aurora PostgreSQL with minimal downtime. Design the migration strategy using AWS DMS (Database Migration Service). How does CDC work? How do you handle schema conversion (Oracle-specific types)? What validation steps ensure data integrity?"

**What They're Really Testing:** Whether you understand database migration at scale — full load + CDC, schema conversion challenges, and validation strategies for zero-data-loss migration.

### Answer

**DMS Migration Strategy:**

```yaml
# Phase 1: Assessment
# Use AWS Schema Conversion Tool (SCT) to analyze Oracle schema
# Report: incompatible types, conversion complexity, effort estimation

Oracle → PostgreSQL conversions:
  Oracle Type      | PostgreSQL Type      | Notes
  -----------------|----------------------|-----------------------
  NUMBER(10)       | INTEGER              | Direct mapping
  VARCHAR2(255)    | VARCHAR(255)         | Direct mapping
  CLOB             | TEXT                 | Direct mapping
  BLOB             | BYTEA                | Direct mapping
  DATE             | TIMESTAMP            | Oracle DATE includes time!
  SEQUENCE         | SERIAL/BIGSERIAL     | Auto-increment
  SYNONYM          | VIEW                 | Manual creation
  MATERIALIZED VIEW| MATERIALIZED VIEW    | Different refresh syntax
  PACKAGE          | SCHEMA + FUNCTION    | Rewrite required
  REF CURSOR       | REFCURSOR            | Syntax differences
  
  Common issues:
  - Oracle: empty string = NULL, PostgreSQL: empty string ≠ NULL
  - Oracle: NVL() → PostgreSQL: COALESCE()
  - Oracle: DECODE() → PostgreSQL: CASE WHEN
  - Oracle: ROWNUM → PostgreSQL: LIMIT/OFFSET

# Phase 2: Full Load
# DMS creates target tables, loads all data

DMS Task:
  MigrationType: full-load
  TargetTablePrepMode: TRUNCATE_BEFORE_LOAD
  
  Mapping Rules:
    - Include all tables from schema 'APP'
    - Exclude: APP.TEMP_% (temporary tables)
    - Rename: APP.USERS → APP.ACCOUNTS (if needed)
  
  Transformation Rules:
    - Column: REMOVE (ORDERS.TEMP_COLUMN)
    - Column: RENAME (USERS.USERNAME → USERS.NAME)

  ParallelLoad:
    MaxFullLoadSubTasks: 8  # Parallel table loads
    Target:
      - Table: ORDERS (range: 1-10M) → Task 1
      - Table: ORDERS (range: 10M-20M) → Task 2
  
  Validation:
    Enabled: true
    ValidationOnly: false

# Phase 3: Change Data Capture (CDC)
# After full load, DMS captures ongoing changes

  MigrationType: full-load-and-cdc
  CdcStartPosition: '2024-01-15T00:00:00Z'  # From full load snapshot
  
  # DMS reads Oracle redo logs to capture changes
  # Applies changes to PostgreSQL in near-real-time
  # Source must enable: ARCHIVELOG mode, supplemental logging
  # Latency: typically <1 second
  
  TaskSettings:
    CdcMinBatchSize: 1000      # Min events in batch
    CdcMaxBatchSize: 100000    # Max events in batch
    CdcApplyBatches: true      # Apply in batch (faster)
    CdcApplyStagingFileLimit: 10000  # Staging file size (MB)
```

**Zero-Downtime Cutover:**

```yaml
# Cutover steps for minimal downtime:

# 1. Setup phase (days before):
DMS → Full load of existing data (5TB at 500Mbps → ~22 hours)
DMS → CDC catches up to real-time (lag < 1 second)

# 2. Validation phase:
# Compare row counts between source and target:
SELECT COUNT(*) FROM source.ORDERS;  -- 10,000,000
SELECT COUNT(*) FROM target.ORDERS;  -- 10,000,000

# Compare checksums:
SELECT MD5(ARRAY_AGG(id || amount || created_at ORDER BY id))
FROM source.ORDERS;

SELECT MD5(ARRAY_AGG(id || amount || created_at ORDER BY id))
FROM target.ORDERS;

# DMS validation: compares each table row by row
# Reports: validation summary table with pass/fail per table

# 3. Cutover (5-10 minute window):
# a. Stop writes to source DB
# b. Wait for DMS CDC to apply remaining changes (lag = 0)
# c. Validate final row count and checksums
# d. Switch application connection string to target
# e. Resume writes on target

# 4. Rollback plan:
# Keep source DB running (read-only)
# DMS reverse: target → source (if needed)
# Application: revert connection string

# Tools for cutover:
# - Route53 weighted DNS: 5% → target, 95% → source (gradual)
# - RDS Proxy: single connection string, swap target behind proxy
```

**DMS Performance Tuning:**

```yaml
# DMS replication instance sizing:
# Large migrations: dms.r6g.4xlarge (16 vCPU, 128GB RAM)

DMS instance:
  - dms.r6g.large: 2 vCPU, 16GB → 10-50GB/hour
  - dms.r6g.xlarge: 4 vCPU, 32GB → 50-150GB/hour
  - dms.r6g.2xlarge: 8 vCPU, 64GB → 150-300GB/hour
  - dms.r6g.4xlarge: 16 vCPU, 128GB → 300-500GB/hour

# To achieve 500GB/hour for 5TB:
# 5TB / 0.5TB/hour = 10 hours full load
# 5TB / 10 hours = 500GB/hour → 4xlarge instance

# Optimization:
# - Target: disable triggers, indexes, foreign keys during load
# - Target: increase maintenance_work_mem (PostgreSQL)
# - Target: commit size = 10000 (configurable)
# - Source: read from replica (avoid production load)
# - Network: use Direct Connect if on-premises
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|----------|----------------------|
| **Schema conversion** | Anticipates Oracle→PostgreSQL type mapping issues (NULL, sequences) |
| **Full load + CDC** | Designs phased migration with ongoing change replication |
| **Validation** | Compares row counts and checksums, uses DMS validation |
| **Cutover** | Plans minimal-downtime cutover with rollback capability |

---

## 10. S3 Glacier & Archival Strategies

**Q:** "Design a data archival strategy for regulatory compliance: 100TB of financial transactions that must be retained for 7 years. Access pattern: <1% of data accessed per year, but when accessed, retrieval must happen within 12 hours. Cost is the primary constraint. How do S3 Glacier and Deep Archive compare? How do you manage the retrieval process?"

**What They're Really Testing:** Whether you understand the cost trade-offs of archival storage and can design an end-to-end retrieval workflow that meets compliance requirements.

### Answer

**Glacier Storage Classes:**

```yaml
Glacier Instant Retrieval:
  - Retrieval: milliseconds (instant)
  - Min storage: 90 days
  - Cost: $0.004/GB/month
  - Retrieval cost: $0.01/GB
  - Use: quarterly access data

Glacier Flexible Retrieval:
  - Retrieval: 1-5 min (expedited), 3-5 hours (standard), 5-12 hours (bulk)
  - Min storage: 90 days
  - Cost: $0.0036/GB/month
  - Retrieval cost: $0.01/GB (standard), $0.03/GB (expedited)
  - Use: semi-annual access data

Glacier Deep Archive:
  - Retrieval: 12 hours (standard), 48 hours (bulk)
  - Min storage: 180 days
  - Cost: $0.00099/GB/month
  - Retrieval cost: $0.02/GB (standard), $0.0025/GB (bulk)
  - Use: annual/rare access data, 7-year retention

Cost comparison for 100TB over 7 years:
  Standard: 100TB × $0.023 × 84 months = $193,200
  IA: 100TB × $0.0125 × 84 months = $105,000
  Glacier Instant: 100TB × $0.004 × 84 months = $33,600
  Glacier Flexible: 100TB × $0.0036 × 84 months = $30,240
  Deep Archive: 100TB × $0.00099 × 84 months = $8,316

Deep Archive saves $185K over Standard (96% reduction)!
```

**Lifecycle with Archival:**

```yaml
# Lifecycle policy for 7-year retention:
LifecycleRules:
  - ID: "archive-transactions"
    Filter:
      Prefix: "transactions/"
    
    Transitions:
      - Days: 0
        StorageClass: STANDARD              # First 30 days: hot
      - Days: 30
        StorageClass: STANDARD_IA           # 1 month: warm
      - Days: 90
        StorageClass: GLACIER_INSTANT_RETRIEVAL  # 3 months: archive instant
      - Days: 365
        StorageClass: GLACIER_FLEXIBLE_RETRIEVAL  # 1 year: archive
      - Days: 730
        StorageClass: DEEP_ARCHIVE          # 2+ years: deep archive
    
    Expiration:
      Days: 2555                            # 7 years: delete
      ExpiredObjectDeleteMarker: true

# Object Lock (compliance/WORM):
# Required for regulatory retention
ObjectLockConfiguration:
  ObjectLockEnabled: Enabled
  Rule:
    DefaultRetention:
      Mode: COMPLIANCE                     # Or GOVERNANCE (less strict)
      Days: 2555                           # 7 years minimum

# COMPLIANCE mode: object can't be deleted or overwritten by ANYONE
# (including root user) until retention period expires
```

**Retrieval Workflow:**

```python
import boto3

s3 = boto3.client('s3')
glacier = boto3.client('glacier')

def initiate_retrieval(object_key, retrieval_type='Standard'):
    """
    Initiate retrieval from Glacier/Deep Archive.
    
    Args:
        object_key: S3 key of archived object
        retrieval_type: 'Expedited', 'Standard', or 'Bulk'
    """
    # Initiate restore
    response = s3.restore_object(
        Bucket='financial-transactions',
        Key=object_key,
        RestoreRequest={
            'Days': 7,                          # Temporary copy for 7 days
            'GlacierJobParameters': {
                'Tier': retrieval_type          # Expedited, Standard, Bulk
            }
        }
    )
    
    # Check restore status (async)
    status = s3.head_object(
        Bucket='financial-transactions',
        Key=object_key
    )
    # status['Restore'] = 'ongoing-request="true"' (if still restoring)
    # status['Restore'] = 'ongoing-request="false", expiry-date="..."' (when ready)
    
    return response

def check_restore_status(object_key):
    """Check if Glacier restore is complete."""
    response = s3.head_object(
        Bucket='financial-transactions',
        Key=object_key
    )
    
    restore_status = response.get('Restore', '')
    if 'ongoing-request="false"' in restore_status:
        # Restore complete! Can read the object
        return s3.get_object(
            Bucket='financial-transactions',
            Key=object_key
        )
    else:
        # Still restoring
        return None

# Bulk retrieval (for compliance audits):
# Use S3 Batch Operations to restore many objects at once

def bulk_retrieve(prefix, date_range):
    """Bulk retrieve all objects matching criteria."""
    # Create inventory manifest
    manifest = s3.create_inventory(...)
    
    # Batch restore
    batch = s3.create_batch_job(
        Operation={
            'S3RestoreObject': {
                'ExpirationInDays': 30,
                'GlacierJobTier': 'Bulk'
            }
        },
        Manifest={
            'Spec': {
                'Format': 'S3InventoryReportCsv',
                'Fields': ['Key', 'VersionId']
            },
            'Location': {
                'ObjectArn': manifest_arn,
                'ETag': manifest_etag
            }
        },
        Priority=10,
        RoleArn='arn:aws:iam::123456789:role/s3-batch-restore'
    )
    
    return batch['JobId']
```

**Cost Optimization for Archival:**

```yaml
# Optimizing archival costs:

# 1. Object size matters:
# Glacier minimum billable size: 40KB (for Glacier Flexible)
# If objects < 40KB: cost is based on 40KB
# Solution: aggregate small objects into larger files (e.g., daily batch)

# 2. Bulk retrieval pricing:
# Deep Archive retrieval:
#   Standard (12 hours): $0.02/GB
#   Bulk (48 hours): $0.0025/GB (87% cheaper!)
# If audit allows 48-hour window: use Bulk tier

# 3. Early deletion fees:
# Glacier Instant: min 90 days → delete at day 30 → pay 60 days
# Deep Archive: min 180 days → delete at day 100 → pay 80 days
# Fee = (min_days - used_days) × storage_rate × size

# 4. S3 Inventory for tracking:
# Generate daily inventory report
# Helps identify large/unused objects for lifecycle optimization

# 5. Compression before archival:
# Text data: 10:1 compression ratio
# 100TB → 10TB compressed → 90% storage cost reduction
# Use gzip/bzip2 before uploading to S3
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Storage class economics** | Quantifies 96% cost savings with Deep Archive vs Standard |
| **Retrieval tiers** | Knows expedited (minutes), standard (hours), bulk (days) retrieval times |
| **Object Lock** | Uses COMPLIANCE mode for regulatory retention enforcement |
| **Bulk retrieval** | Uses S3 Batch Operations for mass restores during audits |

---

> *All 10 questions cover the full breadth of AWS storage and database — from S3 lifecycle and DynamoDB single-table design to Redis clustering and zero-downtime migration.*
