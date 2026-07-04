# 🏗️ Parking Lot System — High-Level Design (AWS Production)

> **Role:** Principal Cloud Architect / Systems Designer  
> **Target Level:** Staff/Principal Engineer  
> **Focus:** Distributed AWS-native architecture, MCP server integration, resilience engineering

---

## 1. SYSTEM OVERVIEW

**Purpose:** Multi-floor parking facility with automated fee collection, real-time spot allocation, and AI-agent operable interfaces via Model Context Protocol (MCP).

**Scale:** 10 floors × 500 spots = 5,000 total. Peak: 500 entries/hr, 500 exits/hr. Target 99.99% availability.

**Domain:** Smart mobility infrastructure with edge computing at gate controllers, cloud-based orchestration, and MCP-exposed management capabilities for autonomous operational agents.

---

## 2. SYSTEM TOPOLOGY & AWS COMPONENT SELECTION

```mermaid
flowchart TB
    subgraph Edge["🌐 Edge & CDN"]
        CF["CloudFront\nCDN + WAF"]
        IoT["IoT Core\nGate Controllers"]
        GKD["Greengrass\nEdge Compute"]
    end

    subgraph Auth["🔐 Auth & Security"]
        COG["Cognito\nUser Pools"]
        KMS["KMS\nEncryption Keys"]
        WAF["WAF\nRate Limiting"]
    end

    subgraph Compute["⚙️ Compute Layer"]
        ALB["Application LB\n(Internal)"]
        L1["Lambda: Entry\n(Ticket Issuance)"]
        L2["Lambda: Exit\n(Fee Calculation)"]
        F1["Fargate: Booking\n(Python/FastAPI)"]
        F2["Fargate: Payment\n(Node.js)"]
    end

    subgraph Stream["📨 Ingestion & Messaging"]
        KDS["Kinesis Data Streams\nEntry/Exit Events"]
        SQS["SQS\nPayment Queue"]
        SNS["SNS\nNotifications"]
        DLQ["DLQ\nFailed Payments"]
    end

    subgraph Data["💾 Data Layer"]
        AUR["Aurora PostgreSQL\nMulti-AZ\nTickets · Payments · Users"]
        DDB["DynamoDB\nDAX\nSpot Inventory"]
        ECR["ElastiCache Redis\nCluster Mode\nLocks · Rate Cards"]
        S3["S3\nReceipts · Logs · ANPR"]
    end

    subgraph MCP["🤖 MCP Server Layer"]
        MCP_SRV["MCP Server\n(Agent Interface)"]
        TOOL["tools/list\nCost · Compliance · Deploy"]
        RES["resources/list\nArch Ref · VPC Rules"]
        PROMPT["prompts/list\nWell-Architected Review"]
    end

    subgraph Obs["📊 Observability"]
        CW["CloudWatch\nLogs + Metrics"]
        XR["X-Ray\nTracing"]
        PROM["Prometheus\non ECS"]
        GRA["Grafana\nDashboards"]
    end

    CF --> WAF
    WAF --> ALB
    IoT --> GKD
    GKD --> KDS

    ALB --> COG
    ALB --> L1
    ALB --> L2
    ALB --> F1
    ALB --> F2

    L1 --> KDS
    L2 --> SQS
    SQS --> DLQ
    SQS --> F2
    F2 --> SNS

    L1 --> DDB
    L1 --> ECR
    L2 --> AUR
    F1 --> AUR
    F1 --> ECR
    F2 --> AUR
    F2 --> S3

    AUR -.-> CW
    DDB -.-> CW
    L1 -.-> XR
    F1 -.-> XR
    CW --> PROM
    PROM --> GRA

    MCP_SRV --> TOOL
    MCP_SRV --> RES
    MCP_SRV --> PROMPT
    MCP_SRV -.-> AUR
    MCP_SRV -.-> CW

    style CF fill:#3b0d0d,stroke:#ef4444,color:#e6edf3
    style COG fill:#4c1d95,stroke:#8b5cf6,color:#e6edf3
    style L1 fill:#1a365d,stroke:#60a5fa,color:#e6edf3
    style L2 fill:#1a365d,stroke:#60a5fa,color:#e6edf3
    style F1 fill:#1a365d,stroke:#60a5fa,color:#e6edf3
    style F2 fill:#1a365d,stroke:#60a5fa,color:#e6edf3
    style KDS fill:#0d3320,stroke:#4ade80,color:#e6edf3
    style SQS fill:#0d3320,stroke:#4ade80,color:#e6edf3
    style AUR fill:#0d3320,stroke:#4ade80,color:#e6edf3
    style DDB fill:#0d3320,stroke:#4ade80,color:#e6edf3
    style ECR fill:#0d3320,stroke:#4ade80,color:#e6edf3
    style MCP_SRV fill:#2d1b69,stroke:#a78bfa,color:#e6edf3,stroke-dasharray:5 5
    style TOOL fill:#2d1b69,stroke:#a78bfa,color:#e6edf3
    style RES fill:#2d1b69,stroke:#a78bfa,color:#e6edf3
    style PROMPT fill:#2d1b69,stroke:#a78bfa,color:#e6edf3

    linkStyle default stroke:#a78bfa,stroke-width:2px
```

> **📥 Download:** [Parking Lot AWS Architecture (draw.io)](parking-lot-hld.drawio) — Open in draw.io Desktop to edit.

---

## 3. MCP INTERFACE SCHEMA

The system exposes its infrastructure and operational capabilities as a Model Context Protocol (MCP) server, enabling AI agents to interact with the architecture programmatically.

### 3.1 Tools (`tools/list`)

```json
{
  "tools": [
    {
      "name": "calculate_infrastructure_cost",
      "description": "Estimate monthly AWS cost for the Parking Lot architecture at a given scale",
      "inputSchema": {
        "type": "object",
        "properties": {
          "num_lots": { "type": "integer", "minimum": 1, "default": 1 },
          "spots_per_lot": { "type": "integer", "default": 5000 },
          "monthly_entries": { "type": "integer", "default": 360000 },
          "high_availability": { "type": "boolean", "default": true }
        },
        "required": []
      }
    },
    {
      "name": "validate_iam_compliance",
      "description": "Scan IAM roles and policies against least-privilege best practices",
      "inputSchema": {
        "type": "object",
        "properties": {
          "scope": {
            "type": "string",
            "enum": ["entry_service", "booking_service", "payment_service", "all"],
            "default": "all"
          }
        },
        "required": []
      }
    },
    {
      "name": "generate_cloudformation_stub",
      "description": "Generate a CloudFormation template stub for a given component",
      "inputSchema": {
        "type": "object",
        "properties": {
          "component": {
            "type": "string",
            "enum": ["vpc", "aurora", "dynamodb", "elasticache", "lambda_entry", "lambda_exit", "fargate_booking", "fargate_payment", "kinesis", "sqs"]
          },
          "environment": {
            "type": "string",
            "enum": ["dev", "staging", "prod"],
            "default": "prod"
          }
        },
        "required": ["component"]
      }
    },
    {
      "name": "simulate_failure",
      "description": "Simulate a failure mode and report system behavior",
      "inputSchema": {
        "type": "object",
        "properties": {
          "failure_mode": {
            "type": "string",
            "enum": [
              "aurora_primary_failover",
              "redis_cluster_node_loss",
              "kinesis_shard_throttle",
              "dlq_backlog",
              "lambda_concurrency_exhaustion",
              "cognito_token_expiry"
            ]
          }
        },
        "required": ["failure_mode"]
      }
    },
    {
      "name": "optimize_dynamoDB_capacity",
      "description": "Recommend DynamoDB read/write capacity and DAX cluster size based on traffic patterns",
      "inputSchema": {
        "type": "object",
        "properties": {
          "peak_tps_read": { "type": "integer", "default": 500 },
          "peak_tps_write": { "type": "integer", "default": 100 },
          "item_size_kb": { "type": "number", "default": 2 }
        },
        "required": []
      }
    }
  ]
}
```

### 3.2 Resources (`resources/list`)

```json
{
  "resources": [
    {
      "uri": "mcp://parking-lot/architecture/vpc-rules",
      "name": "VPC Subnet & Routing Rules",
      "description": "Standard VPC layout with public/private subnets, NAT gateways, and VPC endpoints for all data services",
      "mimeType": "application/json"
    },
    {
      "uri": "mcp://parking-lot/architecture/data-model",
      "name": "Data Model & Schema",
      "description": "Complete relational schema for Aurora PostgreSQL and DynamoDB table designs with GSI/SI keys",
      "mimeType": "application/json"
    },
    {
      "uri": "mcp://parking-lot/architecture/rto-rpo-matrix",
      "name": "RTO/RPO Matrix by Component",
      "description": "Recovery Time Objective and Recovery Point Objective for each service component",
      "mimeType": "application/json"
    },
    {
      "uri": "mcp://parking-lot/architecture/cost-base",
      "name": "Baseline Cost Estimate",
      "description": "Monthly cost breakdown for the reference architecture at stated scale",
      "mimeType": "application/json"
    }
  ]
}
```

### 3.3 Prompts (`prompts/list`)

```json
{
  "prompts": [
    {
      "name": "well-architected-review",
      "description": "Run an automated AWS Well-Architected Review against the Parking Lot architecture across all six pillars"
    },
    {
      "name": "incident-response-plan",
      "description": "Generate an incident response runbook for a given failure mode using the simulate_failure tool"
    },
    {
      "name": "capacity-planning",
      "description": "Analyze current traffic patterns and recommend capacity adjustments using optimize_dynamoDB_capacity and calculate_infrastructure_cost"
    }
  ]
}
```

---

## 4. PARKING FLOW (Production Sequence)

```mermaid
sequenceDiagram
    participant Driver as 🚗 Driver
    participant Gate as 🚧 Gate Controller
    participant KDS as 🏞️ Kinesis Stream
    participant L1 as λ Entry
    participant DDB as DynamoDB
    participant ECR as Redis
    participant AUR as Aurora PG
    participant SQS as SQS Queue
    participant F2 as Fargate Payment
    participant SNS as SNS

    Driver->>Gate: Arrive at entry (ANPR capture)
    Gate->>KDS: Publish plate + timestamp to Kinesis

    KDS->>L1: Trigger Lambda (event source mapping)
    L1->>ECR: Acquire distributed lock (gate:1)
    L1->>DDB: Query nearest available spot (GSI:status)
    DDB-->>L1: Spot A12 (Floor 1, Compact)
    L1->>DDB: Update spot status → RESERVED (conditional write)
    L1->>AUR: INSERT ticket (UUID, plate, spot, entry_time)

    Note over L1: Circuit breaker: if DDB write fails 3x, fall back to Aurora reservation with optimistic locking

    L1-->>KDS: Return spot assignment
    KDS-->>Gate: Open gate → display spot A12
    Gate-->>Driver: Proceed to spot A12
    Driver->>Driver: Park

    Note over Driver,F2: Vehicle parked for duration

    Driver->>Gate: Request exit (ticket scan)
    Gate->>KDS: Publish exit request to Kinesis
    KDS->>L1: Trigger Lambda (fee calculation)
    L1->>AUR: Retrieve ticket + compute duration
    AUR-->>L1: Duration = 2h, rate = compact hourly
    L1->>L1: Fee = $40.00
    L1-->>Driver: Display fee

    Driver->>F2: Pay $40.00 (idempotency key: tkt-001-attempt-1)
    F2->>AUR: Record payment (ON CONFLICT DO NOTHING)
    F2-->>Driver: Receipt generated
    F2->>SQS: Enqueue exit event
    SQS->>L1: Process exit (eventual consistency)
    L1->>DDB: Release spot → AVAILABLE
    L1->>AUR: UPDATE ticket (exit_time, status=PAID)
    L1->>SNS: Notify admin (spot freed)

    Note over F2: Payment idempotency: Redis caches processed idempotency keys with 48h TTL. Duplicate requests return cached receipt without re-charging.
```

---

## 5. COMPONENT BREAKDOWN

### 5.1 Compute Layer

| Component | Service | Runtime | Trigger | Scaling |
|-----------|---------|---------|---------|---------|
| Entry Lambda | AWS Lambda | Python 3.12 | API GW + Kinesis | Provisioned Concurrency: 100 |
| Exit Lambda | AWS Lambda | Python 3.12 | SQS FIFO | Reserved Concurrency: 50 |
| Booking Fargate | ECS Fargate | Python/FastAPI | ALB Target Group | Auto-scale: 2–20 tasks |
| Payment Fargate | ECS Fargate | Node.js 22 | SQS FIFO + ALB | Auto-scale: 2–10 tasks |

### 5.2 Data Layer

**Aurora PostgreSQL (Multi-AZ):**
```sql
CREATE TABLE parking_lots (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    total_spots INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID REFERENCES parking_lots(id),
    spot_id TEXT NOT NULL,
    vehicle_plate TEXT NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMPTZ,
    fee NUMERIC(10,2),
    idempotency_key TEXT UNIQUE,
    status TEXT DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAID','LOST')),
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tickets_status ON tickets(status) WHERE status = 'ACTIVE';
CREATE INDEX idx_tickets_idempotency ON tickets(idempotency_key);
```

**DynamoDB (with DAX):**
| Table | Partition Key | Sort Key | GSI | Read Capacity |
|-------|--------------|----------|-----|---------------|
| `spots` | `lot_id` | `spot_id` | GSI: `status` | 500 RCU (DAX cached) |
| `reservations` | `lot_id` | `time_slot` | GSI: `user_id` | 200 RCU |
| `rate_cards` | `lot_id` | `spot_type` | — | 50 RCU (DAX cached) |

### 5.3 Messaging & Streaming

| Channel | Source | Destination | Pattern | Retention |
|---------|--------|-------------|---------|-----------|
| Kinesis Data Stream | Gate controllers | Entry Lambda | At-least-once | 24 hours |
| SQS FIFO Queue | Exit Lambda | Payment Fargate | Exactly-once (per msg group) | 14 days DLQ |
| SNS Topic | Payment Fargate | Admin + Driver | Pub/sub fan-out | — |

### 5.4 Edge & Security

- **CloudFront:** Global CDN with AWS WAF rate-based rules (1000 req/s per IP)
- **Cognito:** User pools for driver accounts + identity pools for gate controller auth
- **KMS:** Customer-managed key for Aurora storage encryption + S3 SSE-KMS
- **IRSA (EKS):** Not used (Fargate tasks use IAM task roles directly)
- **VPC Endpoints:** Gateway endpoints for S3 + DynamoDB; interface endpoints for ECR, CloudWatch, KMS

---

## 6. RESILIENCE, FAILURE MODES & EDGE CASES

### 6.1 Consistency vs. Availability

| Scenario | Strategy | RPO | RTO |
|----------|----------|-----|-----|
| Aurora Primary Failure | Auto-failover to standby (Multi-AZ) | < 1 minute | ~60 seconds |
| DynamoDB Regional Failure | Global Tables (active-active) | 0 (last writer wins) | < 1 second |
| Redis Cluster Node Loss | Auto-rebuild from replicas | 0 (replica promotion) | ~10 seconds |
| Kinesis Shard Failure | Reshard + replay from checkpoint | < 1 minute | ~120 seconds |
| SQS Message Loss | DLQ + redrive policy | 0 (at-least-once) | Immediate |

### 6.2 Cascading Failure Mitigation

**Backpressure:** SQS visibility timeout + lambda reserved concurrency prevents downstream overwhelm. Kinesis shard limits throttle upstream gate controllers (which queue locally via Greengrass).

**Circuit Breakers:**
- DynamoDB write failures → fall back to Aurora pessimistic lock within 300ms
- Payment gateway timeout (3s) → retry with exponential backoff (jitter: base 100ms × 2^n + rand(0, 100ms))
- Redis connection failure → degrade to direct Aurora reads (p50 increases 40ms → 8ms → skip cache)

**Dead-Letter Queue (DLQ) Triage:**
```
Failed messages → SQS DLQ → CloudWatch Alarm → SNS → PagerDuty
  ↓
Lambda DLQ consumer (every 5 min):
  - Re-drive up to 3 times
  - Dead-letter to S3 for manual inspection
  - Alert if > 10 messages in DLQ for > 1 hour
```

**Retry Jitter Algorithm:**
```python
import random, time, math

def retry_with_jitter(attempt, base_ms=100, max_ms=30000):
    sleep_ms = min(base_ms * math.pow(2, attempt) + random.uniform(0, base_ms), max_ms)
    time.sleep(sleep_ms / 1000)
```

### 6.3 Edge Cases

| Edge Case | Mitigation |
|-----------|-----------|
| **Concurrent entry at same gate** | Redis distributed lock `lock:gate:{id}` (TTL: 5s) prevents double-ticketing |
| **Vehicle leaves without paying** | ANPR gates capture exit; ticket goes to LOST status → fine applied to registered owner |
| **Payment idempotency breach** | `ON CONFLICT (idempotency_key) DO NOTHING` + Redis cache of processed keys (48h TTL) |
| **Kinesis shard hot-spot** | Partition key = `{lot_id}:{gate_id}:{epoch_hour}` ensures uniform shard distribution |
| **DynamoDB hot key (popular spot)** | Add `spot_id` suffix to partition key to distribute writes; DAX absorbs reads |
| **Aurora deadlock on concurrent ticket** | `SELECT ... FOR UPDATE NOWAIT` + retry in application layer (max 3 attempts) |

---

## 7. COST BREAKDOWN (Monthly)

| Component | Configuration | Monthly Cost |
|-----------|--------------|-------------|
| CloudFront | 500 GB data transfer, WAF | $150 |
| Cognito | 10,000 MAUs | $0 |
| Lambda (Entry + Exit) | 500K invocations, 1GB RAM | $85 |
| Fargate (Booking + Payment) | 4 tasks × 2 vCPU × 4GB | $520 |
| Aurora PostgreSQL | db.r6g.large, Multi-AZ, 500GB | $700 |
| DynamoDB + DAX | 500 RCU / 200 WCU, DAX cluster (2 nodes) | $380 |
| ElastiCache Redis | cache.r6g.large, cluster mode (3 shards) | $420 |
| Kinesis Data Streams | 5 shards, 24h retention | $180 |
| SQS + SNS | 10M requests/month | $30 |
| S3 + KMS | 100GB storage, SSE-KMS | $15 |
| CloudWatch + X-Ray | Metrics, logs, tracing | $120 |
| **Total** | | **$2,600** |

---

## 8. IMPLEMENTATION ROADMAP

**Phase 1 (Weeks 1-3):** Core infrastructure — VPC, Aurora Multi-AZ, DynamoDB tables, Redis cluster. Basic Lambda entry/exit with SQS.

**Phase 2 (Weeks 4-6):** Fargate services (Booking + Payment), Kinesis streaming, CloudFront + WAF, Cognito auth. MCP `tools/list` endpoints.

**Phase 3 (Weeks 7-8):** DLQ pipeline, circuit breakers, retry jitter, Chaos Engineering experiments. MCP `resources/list` + `prompts/list`.

**Phase 4 (Weeks 9-10):** Dashboards (Grafana), X-Ray tracing, CloudWatch alarms, Well-Architected Review via MCP prompt. Production hardening.
