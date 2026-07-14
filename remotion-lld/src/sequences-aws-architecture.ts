import { SequenceData } from "./SequenceDiagram";

export const AWS_ARCHITECTURE_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Well-Architected Framework
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-well-architected",
    title: "AWS Well-Architected Framework — Six Pillars",
    subtitle:
      "Operational Excellence → Security → Reliability → Performance Efficiency → Cost Optimization → Sustainability",
    actors: [
      "Operational\nExcellence",
      "Security",
      "Reliability",
      "Performance\nEfficiency",
      "Cost\nOptimization",
      "Sustainability",
    ],
    steps: [
      {
        from: 0,
        to: 0,
        label: "IaC, CI/CD, Observability",
        detail: "Runbooks, structured logging, MTTR tracking",
      },
      {
        from: 1,
        to: 1,
        label: "IAM, KMS, GuardDuty",
        detail: "Least privilege, encryption at rest/transit",
      },
      {
        from: 2,
        to: 2,
        label: "Multi-AZ, Auto Scaling, Backups",
        detail: "RTO/RPO targets, error budgets",
      },
      {
        from: 3,
        to: 3,
        label: "Right-sizing, Graviton, Serverless",
        detail: "Compute Optimizer, p50/p99 latency",
      },
      {
        from: 4,
        to: 4,
        label: "Spot, Savings Plans, Lifecycle",
        detail: "Unit cost, anomaly detection, tagging",
      },
      {
        from: 5,
        to: 5,
        label: "Graviton ARM, Efficient Code",
        detail: "60% less energy, Customer Carbon Footprint Tool",
      },
      {
        from: 0,
        to: 5,
        label: "All six pillars reviewed quarterly",
        detail: "Risk scoring: Likelihood × Impact",
      },
    ],
    durationInFrames: 300,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Multi-Region DR
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-multi-region-dr",
    title: "Multi-Region Disaster Recovery — Active-Passive",
    subtitle:
      "Primary (us-east-1) → DR (us-west-2) with RPO 1s, RTO 5min — Aurora Global DB + DynamoDB Global Tables",
    actors: [
      "Route53 /\nGlobal Accel",
      "us-east-1\n(Primary)",
      "Aurora Global\nDB (Writer)",
      "us-west-2\n(DR Standby)",
      "DynamoDB\nGlobal Tables",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Traffic -> Primary region",
        detail: "Latency-based routing, 100% weight",
      },
      {
        from: 1,
        to: 2,
        label: "Write transactions",
        detail: "Aurora writer handles all DML",
      },
      {
        from: 2,
        to: 3,
        label: "Async replication < 1s",
        detail: "Aurora Global DB physical replication",
      },
      {
        from: 1,
        to: 4,
        label: "Write in us-east-1",
        detail: "DynamoDB active writer",
      },
      {
        from: 4,
        to: 4,
        label: "Cross-region replication",
        detail: "DynamoDB Global Tables < 1s lag",
      },
      {
        from: 0,
        to: 0,
        label: "⚠️ Primary region FAILURE",
        detail: "Health check detects outage",
      },
      {
        from: 0,
        to: 3,
        label: "Failover: traffic -> DR",
        detail: "Route53 DNS update + Aurora promote",
      },
      {
        from: 3,
        to: 3,
        label: "Promote Aurora reader",
        detail: "~60s to become writer",
      },
      {
        from: 3,
        to: 0,
        label: "✅ DR active in < 5 min",
        detail: "ECS scales up 10 → 100 tasks",
      },
      {
        from: 1,
        to: 1,
        label: "Primary recovered",
        detail: "Re-replicate, prepare for failback",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Cloud Migration 6 Rs
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-cloud-migration-6rs",
    title: "Cloud Migration — The 6 Rs",
    subtitle:
      "Retire → Retain → Rehost → Replatform → Refactor → Repurchase — prioritized by value vs complexity",
    actors: [
      "Application\nPortfolio",
      "Retire",
      "Rehost\n(Lift & Shift)",
      "Replatform\n(Lift & Tinker)",
      "Refactor\n(Re-architect)",
      "Cloud\nInfrastructure",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Retire: 10-20% of apps",
        detail: "Decommission zombie servers, save 100%",
      },
      {
        from: 0,
        to: 2,
        label: "Rehost: Quick wins (weeks)",
        detail: "AWS MGN — 20-30% savings, low risk",
      },
      {
        from: 2,
        to: 5,
        label: "Migration to EC2",
        detail: "Same OS, same config, cloud infra",
      },
      {
        from: 0,
        to: 3,
        label: "Replatform: Moderate effort",
        detail: "RDS instead of Oracle — 30-50% savings",
      },
      {
        from: 3,
        to: 5,
        label: "Managed services adoption",
        detail: "RDS, ECS, ElastiCache, MSK",
      },
      {
        from: 0,
        to: 4,
        label: "Refactor: Strategic (months)",
        detail: "Monolith → Microservices — 50-70% savings",
      },
      {
        from: 4,
        to: 5,
        label: "Serverless + containers",
        detail: "Lambda, ECS Fargate, DynamoDB",
      },
      {
        from: 0,
        to: 0,
        label: "Retain: Keep on-prem",
        detail: "Regulatory, mainframe, latency-sensitive",
      },
      {
        from: 5,
        to: 5,
        label: "70% cost reduction target",
        detail: "Post-migration: right-size + SP + graviton",
      },
    ],
    durationInFrames: 330,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Serverless vs Containers
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-serverless-vs-containers",
    title: "Serverless vs Containers — Decision Framework",
    subtitle:
      "Lambda front-end (<100K req/s, variable) + ECS back-end (>100K req/s, steady) = Hybrid best of both",
    actors: [
      "API Gateway",
      "Lambda\n(Front-end)",
      "SQS\n(Buffer)",
      "ECS/Fargate\n(Back-end)",
      "Cost\nAnalyzer",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Low traffic: 100 req/s",
        detail: "Lambda auto-scales from 0, pay per req",
      },
      {
        from: 1,
        to: 2,
        label: "Queue for heavy processing",
        detail: "SQS buffers traffic spikes safely",
      },
      {
        from: 2,
        to: 3,
        label: "ECS drains queue",
        detail: "GPU, long-running, >15 min tasks",
      },
      {
        from: 3,
        to: 4,
        label: "Cost at 50K req/s steady",
        detail: "All-Lambda: $12K/mo, Hybrid: $6.5K/mo",
      },
      {
        from: 0,
        to: 1,
        label: "Spike: 50K req/s burst",
        detail: "Lambda bursts to 3000 concurrency/min",
      },
      {
        from: 1,
        to: 2,
        label: "SQS depth increases",
        detail: "ECS auto-scales by queue depth",
      },
      {
        from: 3,
        to: 4,
        label: "ECS cheaper at steady state",
        detail: "All-ECS: $8K/mo vs All-Lambda: $12K/mo",
      },
      {
        from: 4,
        to: 0,
        label: "✅ Hybrid: $6.5K/mo optimal",
        detail: "Lambda for variable, ECS for steady-state",
      },
    ],
    durationInFrames: 300,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Strangler Fig Pattern
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-strangler-fig",
    title: "Strangler Fig — Incremental Monolith Migration",
    subtitle:
      "API Gateway routes new features → new services → gradually shift traffic → decommission monolith",
    actors: [
      "Client /\nAPI Gateway",
      "Legacy\nMonolith",
      "New\nMicroservice",
      "Data Store\n(DynamoDB)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Phase 1: All traffic → monolith",
        detail: "Existing 500K LOC .NET app serving 10K users",
      },
      {
        from: 0,
        to: 2,
        label: "New feature → new service",
        detail: "Real-time inventory tracking (greenfield)",
      },
      {
        from: 2,
        to: 3,
        label: "Own data store",
        detail: "DynamoDB — bounded context ownership",
      },
      {
        from: 0,
        to: 1,
        label: "Gradual route shift",
        detail: "/orders/v1/* → Monolith, /orders/v2/* → New service",
      },
      {
        from: 0,
        to: 2,
        label: "70% traffic to microservice",
        detail: "Month 6: Checkout, Customer profiles migrated",
      },
      {
        from: 1,
        to: 3,
        label: "Anti-corruption layer",
        detail: "Translate monolith data to new service format",
      },
      {
        from: 0,
        to: 2,
        label: "100% traffic to microservices",
        detail: "Month 12: All features extracted",
      },
      {
        from: 1,
        to: 1,
        label: "Decommission monolith",
        detail: "Zero traffic for 30 days → archive",
      },
    ],
    durationInFrames: 300,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Cost Governance Framework
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-cost-governance",
    title: "Cloud Cost Governance Framework",
    subtitle:
      "Visibility (Tagging) → Governance (Budgets + Anomaly) → Optimization (Rightsizing + Purchases) → Culture",
    actors: [
      "Tagging\nEngine",
      "Budget\nAlerts",
      "Anomaly\nDetection",
      "Rightsizing\nOptimizer",
      "Finance\nDashboard",
    ],
    steps: [
      {
        from: 0,
        to: 0,
        label: "Enforce tags via SCP",
        detail: "CostCenter, Environment, Application, Owner",
      },
      {
        from: 0,
        to: 4,
        label: "Cost allocation per team",
        detail: "$500K team-a, $300K team-b, $400K dev",
      },
      {
        from: 4,
        to: 1,
        label: "Budget: $2M/month",
        detail: "80/90/100% alerts → team leads → CTO",
      },
      {
        from: 1,
        to: 2,
        label: "ML anomaly detection",
        detail: "Learns normal patterns, flags 10%+ spikes",
      },
      {
        from: 2,
        to: 3,
        label: "Anomaly > $10K → auto-remediate",
        detail: "Lambda stops non-critical resources",
      },
      {
        from: 3,
        to: 4,
        label: "Monthly rightsizing report",
        detail: "Compute Optimizer: over-provisioned EC2 → downsize",
      },
      {
        from: 3,
        to: 0,
        label: "Quarterly Savings Plans",
        detail: "3yr Compute SP: 50-60% off across services",
      },
      {
        from: 4,
        to: 4,
        label: "Unit cost = cost per transaction",
        detail: "Weekly reviews, Game Days, cost culture",
      },
    ],
    durationInFrames: 300,
  },

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE — Resilience & Chaos Engineering
  // ═══════════════════════════════════════════════════════════

  {
    id: "arch-resilience-chaos",
    title: "Resilience Engineering & Chaos Engineering",
    subtitle:
      "Circuit Breaker → Bulkhead → Retry + Backoff → Chaos Experiment (FIS) → Game Day → Post-Mortem",
    actors: [
      "Payment\nService",
      "Circuit\nBreaker",
      "SQS\n(Backup Queue)",
      "FIS\n(Chaos)",
      "Monitoring\nDashboard",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Normal: CLOSED state",
        detail: "All requests forwarded to payment gateway",
      },
      {
        from: 1,
        to: 1,
        label: "5 consecutive failures",
        detail: "Threshold breached in 10s window",
      },
      {
        from: 1,
        to: 1,
        label: "State → OPEN",
        detail: "Fail fast — reject immediately",
      },
      {
        from: 0,
        to: 2,
        label: "Queue payment for retry",
        detail: "Degraded mode: 202 Accepted, processing later",
      },
      {
        from: 1,
        to: 1,
        label: "Timeout 30s → HALF-OPEN",
        detail: "Allow 1 probe request",
      },
      {
        from: 1,
        to: 0,
        label: "Probe succeeds → CLOSED",
        detail: "Resume normal operation",
      },
      {
        from: 2,
        to: 0,
        label: "Drain backlog queue",
        detail: "Auto-scale to process 10K queued payments",
      },
      {
        from: 3,
        to: 0,
        label: "FIS: inject 500ms latency",
        detail: "AWS Fault Injection Simulator experiment",
      },
      {
        from: 4,
        to: 4,
        label: "P99, error rate, circuit state",
        detail: "Stop condition: error rate > 5%",
      },
      {
        from: 3,
        to: 4,
        label: "Game Day: validate resilience",
        detail: "Post-mortem → runbook fixes → repeat",
      },
    ],
    durationInFrames: 360,
  },
];
