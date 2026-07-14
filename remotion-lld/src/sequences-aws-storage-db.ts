import { SequenceData } from "./SequenceDiagram";

export const AWS_STORAGE_DB_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // STORAGE — S3 Storage Classes & Lifecycle
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-s3-lifecycle",
    title: "S3 Storage Classes & Lifecycle Management",
    subtitle:
      "Standard (hot, 0-30d) → IA (30-90d) → Glacier (90-365d) → Deep Archive (>365d) — automated tiering saves 80%+",
    actors: [
      "S3 PUT\nRequest",
      "S3 Standard\n(Hot)",
      "S3 IA\n(Warm)",
      "S3 Glacier\n(Cold)",
      "S3 Deep\nArchive",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Upload: logs-2025-01-01.gz",
        detail: "Stored in S3 Standard ($0.023/GB)", },
      {
        from: 1,
        to: 1,
        label: "Day 1-30: Frequent access",
        detail: "GET requests: automated querying, dashboards",
      },
      {
        from: 2,
        to: 2,
        label: "Lifecycle: 30d → S3 IA",
        detail: "Intelligent-Tiering auto-moves",
      },
      {
        from: 1,
        to: 2,
        label: "Day 31: Transition to IA",
        detail: "S3 IA: $0.0125/GB + $0.01/GB retrieval",
      },
      {
        from: 2,
        to: 2,
        label: "Day 31-90: Infrequent access",
        detail: "Audit queries once per month",
      },
      {
        from: 3,
        to: 3,
        label: "Lifecycle: 90d → Glacier",
        detail: "S3 Glacier: $0.004/GB, 1-5min retrieval",
      },
      {
        from: 2,
        to: 3,
        label: "Day 91: Transition to Glacier",
        detail: "Compliance retention — 3 years required",
      },
      {
        from: 3,
        to: 3,
        label: "Day 91-365: Rare access",
        detail: "Expedited retrieval: $0.03/GB",
      },
      {
        from: 4,
        to: 4,
        label: "Lifecycle: 365d → Deep Archive",
        detail: "S3 Deep Archive: $0.00099/GB, 12h retrieval",
      },
      {
        from: 3,
        to: 4,
        label: "Year 2+: Deep Archive",
        detail: "90%+ cost savings vs Standard!",
      },
      {
        from: 4,
        to: 0,
        label: "Cost analysis per TB per year",
        detail: "Standard: $276/yr, Lifecycle: $48/yr (-83%)",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // STORAGE — RDS Multi-AZ & Read Replicas
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-rds-multi-az",
    title: "RDS Multi-AZ & Read Replicas — HA + Scale-Out Reads",
    subtitle:
      "Multi-AZ: Sync standby (99.95% HA, <30s failover) | Read Replicas: Async cross-region (5 replicas, RPO <1s, read offload)",
    actors: [
      "Application",
      "RDS Primary\n(Writer)",
      "RDS Standby\n(Sync)",
      "RDS Read\nReplica #1",
      "RDS Read\nReplica #2",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "INSERT INTO orders ...",
        detail: "Write to primary in us-east-1a",
      },
      {
        from: 1,
        to: 2,
        label: "Sync replication to standby",
        detail: "us-east-1b, synchronous commit",
      },
      {
        from: 2,
        to: 1,
        label: "ACK: write committed",
        detail: "Both AZs have the data",
      },
      {
        from: 1,
        to: 0,
        label: "200 OK — write durable",
        detail: "Multi-AZ: zero data loss on AZ failure",
      },
      {
        from: 0,
        to: 3,
        label: "SELECT COUNT(*) FROM orders",
        detail: "Read from Read Replica #1",
      },
      {
        from: 3,
        to: 0,
        label: "10,342 orders (async)",
        detail: "Read replica offloads primary!",
      },
      {
        from: 0,
        to: 4,
        label: "Heavy reporting query",
        detail: "Route to Read Replica #2 in us-west-2",
      },
      {
        from: 4,
        to: 0,
        label: "Report generated (5s query)",
        detail: "Cross-region DR replica",
      },
      {
        from: 1,
        to: 1,
        label: "⚠️ AZ failure detected!",
        detail: "Primary in us-east-1a goes down",
      },
      {
        from: 1,
        to: 2,
        label: "Auto-failover: standby → primary",
        detail: "30-60s DNS update, no data loss",
      },
      {
        from: 2,
        to: 0,
        label: "New primary in us-east-1b",
        detail: "App reconnects via CNAME",
      },
      {
        from: 0,
        to: 0,
        label: "Cost: Multi-AZ = 2x compute",
        detail: "Read Replicas: 50% cheaper in same region",
      },
    ],
    durationInFrames: 390,
  },

  // ═══════════════════════════════════════════════════════════
  // STORAGE — Aurora Serverless v2
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-aurora-serverless",
    title: "Aurora Serverless v2 — Auto-Scaling Database",
    subtitle:
      "Intermittent traffic → Aurora v2 scales 0.5-128 ACU in <30s — no cold start, no capacity planning, pay per ACU-second",
    actors: [
      "Application",
      "Aurora v2\nWriter",
      "Aurora v2\nReader",
      "Auto-Scaling\nPolicy",
      "Aurora\nShared Storage",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Low traffic: 2 concurrent queries",
        detail: "Scales down to 0.5 ACU (idle)",
      },
      {
        from: 1,
        to: 3,
        label: "Monitor: 30% CPU, 10 connections",
        detail: "No scale needed — below threshold",
      },
      {
        from: 0,
        to: 2,
        label: "Read queries: 100 req/s",
        detail: "Auto-scales reader to 2 ACU",
      },
      {
        from: 3,
        to: 2,
        label: "Scale reader: 1→2 ACU",
        detail: "Takes < 30 seconds, zero downtime",
      },
      {
        from: 0,
        to: 1,
        label: "⚠️ Traffic spike: 10K req/s",
        detail: "Black Friday flash sale starts!",
      },
      {
        from: 3,
        to: 1,
        label: "Scale writer: 2→32 ACU",
        detail: "Auto-scaling: aggressive step-up",
      },
      {
        from: 3,
        to: 2,
        label: "Scale readers: 2→64 ACU",
        detail: "3 reader instances added automatically",
      },
      {
        from: 1,
        to: 4,
        label: "Writes to shared storage",
        detail: "6TB Aurora volume, 6-way replicated",
      },
      {
        from: 4,
        to: 2,
        label: "Read your write: <10ms",
        detail: "Storage is shared across writer + readers",
      },
      {
        from: 0,
        to: 1,
        label: "Spike ends: 10 min later",
        detail: "Scale down: 32→2 ACU (auto)",
      },
      {
        from: 1,
        to: 0,
        label: "Cost: only paid for peak",
        detail: "No over-provisioning!",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // STORAGE — DynamoDB Partitions & Hot Keys
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-dynamodb-partitioning",
    title: "DynamoDB Partitioning & Hot Key Mitigation",
    subtitle:
      "Partition key hash → 10GB per partition, 3000 RCU/1000 WCU — hot key throttles: adaptive capacity + write sharding + DAX",
    actors: [
      "Client",
      "DynamoDB\nService",
      "Partition 1\n(key: a-m)",
      "Partition 2\n(key: n-z)",
      "DAX\n(Cache)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Put(sk='user_001')",
        detail: "hash('user_001') → Partition 1",
      },
      {
        from: 1,
        to: 2,
        label: "Store in Partition 1",
        detail: "Partition 1: 3K RCU / 1K WCU capacity",
      },
      {
        from: 0,
        to: 1,
        label: "Get(sk='user_999')",
        detail: "hash('user_999') → Partition 2",
      },
      {
        from: 1,
        to: 3,
        label: "Read from Partition 2",
        detail: "Partition 2: also 3K RCU / 1K WCU",
      },
      {
        from: 0,
        to: 1,
        label: "⚠️ Get('viral_post') × 10K/s",
        detail: "HOT KEY! All reads hit Partition 1!",
      },
      {
        from: 1,
        to: 2,
        label: "🔥 Partition 1 throttled!",
        detail: "Exceeds 3K RCU — ProvisionedThroughputExceeded",
      },
      {
        from: 2,
        to: 0,
        label: "❌ Throttled: retry with backoff",
        detail: "Requests failing — user-facing errors!",
      },
      {
        from: 0,
        to: 4,
        label: "Cache: DAX (DynamoDB Accelerator)",
        detail: "Microsecond reads, 5-min TTL write-through",
      },
      {
        from: 4,
        to: 0,
        label: "HIT: viral_post in cache",
        detail: "DAX absorbs 99% of hot key reads!",
      },
      {
        from: 1,
        to: 1,
        label: "Adaptive capacity: split hot partition",
        detail: "DynamoDB auto-splits, redistributes load",
      },
      {
        from: 0,
        to: 0,
        label: "Design: high-cardinality PK",
        detail: "Add shard key: 'viral_post_1', 'viral_post_2'",
      },
    ],
    durationInFrames: 390,
  },

  // ═══════════════════════════════════════════════════════════
  // STORAGE — ElastiCache Redis Patterns
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-elasticache-redis",
    title: "ElastiCache Redis — Caching Patterns at Scale",
    subtitle:
      "Cache-Aside (lazy loading, TTL) → Write-Through (always fresh, write amplification) → Session Store (TTL, eviction) — 5x latency reduction",
    actors: [
      "Application",
      "ElastiCache\nRedis",
      "RDS / Aurora\n(Database)",
      "Redis Cluster\n(Data Shards)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "GET user:42_profile",
        detail: "Cache-Aside: check cache first",
      },
      {
        from: 1,
        to: 0,
        label: "Cache MISS ❌",
        detail: "Key doesn't exist or TTL expired",
      },
      {
        from: 0,
        to: 2,
        label: "SELECT * FROM users WHERE id=42",
        detail: "Fetch from database (5ms)",
      },
      {
        from: 2,
        to: 0,
        label: "User profile data returned",
        detail: "Load into Redis for next read",
      },
      {
        from: 0,
        to: 1,
        label: "SET user:42_profile + TTL 3600s",
        detail: "Cache populated, next read: <1ms!",
      },
      {
        from: 0,
        to: 1,
        label: "GET user:42_profile (again)",
        detail: "Cache HIT ✅ — 0.5ms response!",
      },
      {
        from: 1,
        to: 0,
        label: "5x faster than database read",
        detail: "Redis: in-memory, P99 < 1ms",
      },
      {
        from: 0,
        to: 2,
        label: "UPDATE users SET ... (write)",
        detail: "Write-Through: update DB + Redis",
      },
      {
        from: 2,
        to: 1,
        label: "Write-Through: update cache",
        detail: "SET user:42_profile = new data",
      },
      {
        from: 0,
        to: 1,
        label: "Session store: login state",
        detail: "Redis with TTL auto-expiry, LRU eviction",
      },
      {
        from: 3,
        to: 3,
        label: "Redis Cluster: 6 shards, 3 replicas",
        detail: "Hash slots: CRC16(key) % 16384 → shard",
      },
      {
        from: 1,
        to: 0,
        label: "P99 reads: 0.8ms, Write: 1.2ms",
        detail: "ElastiCache: 500K ops/sec on r6g.xlarge",
      },
    ],
    durationInFrames: 390,
  },
];
