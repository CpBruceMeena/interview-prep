import { SequenceData } from "./SequenceDiagram";

export const AWS_COMPUTE_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // COMPUTE — EC2 Nitro / ENA Deep Dive
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-ec2-nitro-ena",
    title: "EC2 Nitro Hypervisor & ENA Enhanced Networking",
    subtitle:
      "Nitro (hardware offload) → ENA (SR-IOV, multi-queue, jumbo frames) → 100 Gbps throughput with < 5μs latency",
    actors: [
      "EC2 Instance",
      "Nitro\nHypervisor",
      "ENA (Elastic\nNetwork Adapter)",
      "EFA (Elastic\nFabric Adapter)",
      "NVMe\nLocal Store",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Instance launch request",
        detail: "Nitro replaces Xen (2013+)",
      },
      {
        from: 1,
        to: 1,
        label: "Hardware offload: network, storage, control",
        detail: "Dedicated chips, no host CPU involvement",
      },
      {
        from: 1,
        to: 2,
        label: "Attach ENA virtual function",
        detail: "SR-IOV: direct NIC-to-instance path",
      },
      {
        from: 2,
        to: 0,
        label: "25-100 Gbps network throughput",
        detail: "< 5 μs latency (vs 30-50 μs Xen)",
      },
      {
        from: 0,
        to: 2,
        label: "ENA Express (SRD protocol)",
        detail: "Reliable datagram, multi-path",
      },
      {
        from: 2,
        to: 0,
        label: "Multi-queue: 1 per vCPU",
        detail: "RSS: distribute packets across CPUs",
      },
      {
        from: 0,
        to: 2,
        label: "Jumbo frames: MTU 9001",
        detail: "VPC internal only, not internet",
      },
      {
        from: 0,
        to: 4,
        label: "NVMe local storage (I4i)",
        detail: "3.8TB-30TB, 16 GB/s read, 1M IOPS",
      },
      {
        from: 0,
        to: 3,
        label: "EFA: RDMA for HPC/ML",
        detail: "OS bypass — 3200 Gbps on P5 (H100)",
      },
      {
        from: 2,
        to: 0,
        label: "100 Gbps achieved!",
        detail: "P5: 8× H100 GPU, 3200 Gbps EFA",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — ASG + ALB Lifecycle
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-asg-lifecycle",
    title: "EC2 Auto Scaling Groups — Policies & Lifecycle",
    subtitle:
      "ALB → Target Group → ASG (Min/Max/Desired) → Launch Template → Scale-out/in with lifecycle hooks",
    actors: [
      "ALB",
      "Target\nGroup",
      "Auto Scaling\nGroup",
      "Launch\nTemplate",
      "Lifecycle\nHook",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Route traffic to healthy targets",
        detail: "Health check: /health 10s interval",
      },
      {
        from: 1,
        to: 2,
        label: "Register/deregister instances",
        detail: "Connection draining: 300s timeout",
      },
      {
        from: 2,
        to: 3,
        label: "Launch new instance",
        detail: "AMI, instance type, user-data, IAM role",
      },
      {
        from: 3,
        to: 2,
        label: "Instance ready signal",
        detail: "cfn-signal: HealthCheckGracePeriod 300s",
      },
      {
        from: 2,
        to: 1,
        label: "Instance InService",
        detail: "ALB begins routing traffic",
      },
      {
        from: 2,
        to: 2,
        label: "CPU > 60% → scale-out",
        detail: "TargetTrackingScaling: add 2 instances",
      },
      {
        from: 2,
        to: 4,
        label: "Scale-in: Terminating:Wait",
        detail: "Lifecycle hook fires on termination",
      },
      {
        from: 4,
        to: 4,
        label: "Graceful shutdown: drain connections",
        detail: "Lambda: complete_lifecycle_action → CONTINUE",
      },
      {
        from: 4,
        to: 2,
        label: "Instance terminated",
        detail: "Capacity reduced, ALB target deregistered",
      },
      {
        from: 2,
        to: 2,
        label: "Scheduled: 10→3 at 10PM",
        detail: "Predictable traffic pattern scaling",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — Lambda Concurrency Model
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-lambda-concurrency",
    title: "Lambda Concurrency & Reservations Model",
    subtitle:
      "Account pool (1000) — Reserved guarantees — Provisioned eliminates cold starts — SQS throttling safety",
    actors: [
      "API Lambda\n(User-facing)",
      "SQS Lambda\n(Worker)",
      "Scheduled\nJob Lambda",
      "Regional\nConcurrency Pool",
      "Provisioned\nConcurrency",
    ],
    steps: [
      {
        from: 0,
        to: 3,
        label: "Burst: 600 concurrent",
        detail: "API spikes — consumes from shared pool",
      },
      {
        from: 1,
        to: 3,
        label: "Burst: 300 concurrent",
        detail: "SQS processing — shares pool with API",
      },
      {
        from: 2,
        to: 3,
        label: "Burst: 100 concurrent",
        detail: "Scheduled job steals from pool!",
      },
      {
        from: 3,
        to: 3,
        label: "❌ API throttles at 1000 total!",
        detail: "Spike to 800 → SQS drops to 200 unfair",
      },
      {
        from: 3,
        to: 0,
        label: "Reserved: API = 500",
        detail: "Guaranteed capacity, no throttling",
      },
      {
        from: 3,
        to: 2,
        label: "Reserved: SQS = 300, Job = 100",
        detail: "Fair share — 100 remaining in pool",
      },
      {
        from: 4,
        to: 0,
        label: "Provisioned=50 (pre-warm)",
        detail: "Zero cold starts! $0.000004/GB-sec",
      },
      {
        from: 1,
        to: 1,
        label: "SQS: batch=10, PF=1",
        detail: "Max throughput: 5000 msg/s per burst",
      },
      {
        from: 1,
        to: 3,
        label: "Throttled → VisibilityTimeout",
        detail: "Messages stay in SQS, retry later",
      },
    ],
    durationInFrames: 330,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — EKS Architecture
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-eks-architecture",
    title: "EKS Architecture — Control Plane & Node Groups",
    subtitle:
      "Managed CP (3 AZs, auto etcd) → VPC CNI (native IP) → Managed/Self-managed/Fargate → IRSA (per-pod IAM)",
    actors: [
      "EKS Control\nPlane (AWS)",
      "Managed Node\nGroup (EC2)",
      "Fargate\nProfile",
      "VPC CNI\n(aws-node)",
      "IRSA (IAM\nRoles for SA)",
    ],
    steps: [
      {
        from: 0,
        to: 0,
        label: "HA API server (3 AZs)",
        detail: "etcd encrypted, auto-scaled, 3000 nodes",
      },
      {
        from: 0,
        to: 1,
        label: "Node group: c6i.4xlarge × 10",
        detail: "AWS manages ASG, patching, rolling updates",
      },
      {
        from: 0,
        to: 2,
        label: "Fargate: serverless pods",
        detail: "No nodes, dedicated microVM per pod",
      },
      {
        from: 1,
        to: 3,
        label: "Assign VPC IP to pod",
        detail: "Native VPC routing — no overlay/VXLAN",
      },
      {
        from: 2,
        to: 2,
        label: "Limitation: no DaemonSets",
        detail: "No host networking, no GPU, EFS only",
      },
      {
        from: 0,
        to: 3,
        label: "Pod networking via ENI",
        detail: "EC2 ENI limits determine pod density",
      },
      {
        from: 4,
        to: 4,
        label: "OIDC federation per SA",
        detail: "sts:AssumeRoleWithWebIdentity for pods",
      },
      {
        from: 4,
        to: 1,
        label: "Pod → IAM role → AWS API",
        detail: "Least privilege per microservice!",
      },
      {
        from: 0,
        to: 4,
        label: "100 pods across 3 AZs",
        detail: "Managed: ~$70/mo vs Fargate: ~$1500/mo",
      },
    ],
    durationInFrames: 300,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — Fargate Platform & Networking
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-fargate-networking",
    title: "Fargate Networking — Platform Versions & Connectivity",
    subtitle:
      "awsvpc → Hyperplane ENI → NAT Gateway → VPC Endpoints → Platform 1.3 vs 1.4 vs 1.5+ comparison",
    actors: [
      "Fargate\nTask",
      "Hyperplane\nENI",
      "NAT Gateway\n(Internet)",
      "VPC\nEndpoints",
      "RDS /\nAurora",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Task ENI assigned",
        detail: "awsvpc mode: ENI in VPC subnet",
      },
      {
        from: 1,
        to: 2,
        label: "Internet → NAT Gateway",
        detail: "Private subnet outbound traffic",
      },
      {
        from: 2,
        to: 0,
        label: "External API response",
        detail: "NAT: $32/mo + $0.045/GB — can be costly",
      },
      {
        from: 0,
        to: 3,
        label: "AWS services via VPC endpoints",
        detail: "S3, DynamoDB, ECR, CW Logs — FREE!",
      },
      {
        from: 3,
        to: 4,
        label: "RDS via PrivateLink",
        detail: "No NAT needed for AWS service traffic",
      },
      {
        from: 1,
        to: 1,
        label: "Platform 1.3: slow ENI create",
        detail: "Task startup ~60s, no EFS support",
      },
      {
        from: 1,
        to: 1,
        label: "Platform 1.4: pre-warmed ENI",
        detail: "~30s startup, EFS support, 200GB storage",
      },
      {
        from: 1,
        to: 1,
        label: "Platform 1.5+: EBS + GPU!!!",
        detail: "~15s startup, Graviton, GPU workloads",
      },
      {
        from: 0,
        to: 0,
        label: "Cost: 50 tasks × NAT = $257/mo",
        detail: "VPC endpoints reduce NAT to ~$32/mo",
      },
    ],
    durationInFrames: 330,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — Spot Instance Interruption
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-spot-interruption",
    title: "Spot Instance Interruption Handling",
    subtitle:
      "2-min notice → IMDS poll → Checkpoint → S3 upload → Fleet diversification → 78% cost savings",
    actors: [
      "Spot\nInstance",
      "IMDS\n(Metadata)",
      "Checkpoint\nManager",
      "S3 Bucket\n(Backup)",
      "Spot Fleet\n(Diversified)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Running — normal operation",
        detail: "Spot: $0.15/hr vs On-Demand: $0.68/hr",
      },
      {
        from: 0,
        to: 2,
        label: "Processing data batch",
        detail: "Progress: item 4500/10000",
      },
      {
        from: 1,
        to: 0,
        label: "⚠️ 2-min termination notice!",
        detail: "IMDS returns 200 with termination time",
      },
      {
        from: 0,
        to: 2,
        label: "SIGTERM received — drain",
        detail: "Stop accepting new work, flush buffers",
      },
      {
        from: 2,
        to: 3,
        label: "Upload checkpoint",
        detail: "last_processed_id: 4500 → s3://checkpoints",
      },
      {
        from: 3,
        to: 2,
        label: "Checkpoint saved",
        detail: "Cross-region durable storage",
      },
      {
        from: 0,
        to: 0,
        label: "Instance terminated ⛔",
        detail: "5 concurrent interruptions!",
      },
      {
        from: 4,
        to: 4,
        label: "Fleet: 6 instance types × 3 AZs",
        detail: "capacityOptimized: <5% mass interruption",
      },
      {
        from: 4,
        to: 0,
        label: "Replacement instance ready",
        detail: "Load checkpoint, resume from 4500",
      },
      {
        from: 0,
        to: 0,
        label: "Batch completed — 78% savings!",
        detail: "$50K/mo → $11K/mo (spot + diversification)",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — AWS Batch
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-batch-job-scheduling",
    title: "AWS Batch — Job Scheduling & Compute Environments",
    subtitle:
      "Job Queue → Compute Environment (Spot + OD mix) → Array Jobs → Fair Share → Dependencies → Retry",
    actors: [
      "Job Queue",
      "Compute\nEnvironment",
      "Spot Instance\n(Primary)",
      "On-Demand\n(Fallback)",
      "S3 Output\nBucket",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Submit 10,000 genomics jobs",
        detail: "Array job: size=10000, priority=10",
      },
      {
        from: 1,
        to: 2,
        label: "Allocate to spot (90% cheaper)",
        detail: "capacityOptimized: c6i.4xlarge primary",
      },
      {
        from: 2,
        to: 2,
        label: "Processing: 16 vCPU, 64GB",
        detail: "1-60 min per job, 10K total",
      },
      {
        from: 2,
        to: 1,
        label: "Spot unavailable → fallback",
        detail: "Compute env order: spot → on-demand",
      },
      {
        from: 1,
        to: 3,
        label: "On-demand: $0.68/hr",
        detail: "Auto-fallback when spot capacity low",
      },
      {
        from: 1,
        to: 4,
        label: "Job output → S3",
        detail: "Per-job results in s3://genomics/output/",
      },
      {
        from: 1,
        to: 1,
        label: "Fair share: teamA (1.0), teamB (0.5)",
        detail: "Equitable resource distribution",
      },
      {
        from: 0,
        to: 0,
        label: "Job dependency: A→B→C",
        detail: "SEQUENTIAL: variant calling → report",
      },
      {
        from: 2,
        to: 1,
        label: "Retry: 3 attempts, exponential backoff",
        detail: "EXIT code 1-127 = fail, 128-255 = retry",
      },
      {
        from: 1,
        to: 0,
        label: "All 10K jobs complete ✅",
        detail: "Total cost: $2,500 (99% spot)",
      },
    ],
    durationInFrames: 330,
  },

  // ═══════════════════════════════════════════════════════════
  // COMPUTE — Cost Optimization Reserved + Savings Plans
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-cost-optimization-compute",
    title: "Compute Cost Optimization — Reserved + Savings Plans + Graviton",
    subtitle:
      "Savings Plan (baseline) + Spot (elastic) + Graviton (20% better) + Right-sizing (Compute Optimizer) = 75% savings",
    actors: [
      "On-Demand\nDemand",
      "Compute\nSavings Plan",
      "Spot\nInstances",
      "Graviton\nMigration",
      "Compute\nOptimizer",
    ],
    steps: [
      {
        from: 0,
        to: 0,
        label: "$500K/mo compute bill",
        detail: "30% of total: EC2, Lambda, Fargate",
      },
      {
        from: 0,
        to: 1,
        label: "Baseline: 3yr Compute SP",
        detail: "50-60% off — covers EC2, Lambda, Fargate",
      },
      {
        from: 1,
        to: 0,
        label: "-40% on committed usage",
        detail: "Most flexible: any instance, any region",
      },
      {
        from: 0,
        to: 2,
        label: "Elastic: Spot Instances",
        detail: "60-90% off — for fault-tolerant workloads",
      },
      {
        from: 2,
        to: 0,
        label: "-80% on elastic portion",
        detail: "Reserved baseline + spot elasticity = optimal",
      },
      {
        from: 0,
        to: 3,
        label: "Graviton ARM migration",
        detail: "20-40% better price/performance",
      },
      {
        from: 3,
        to: 0,
        label: "-20% on migrated workloads",
        detail: "Multi-arch Docker builds for easy swap",
      },
      {
        from: 0,
        to: 4,
        label: "Monthly rightsizing scan",
        detail: "Compute Optimizer: downsize over-provisioned",
      },
      {
        from: 4,
        to: 0,
        label: "-30% on rightsized instances",
        detail: "c5.4xlarge (5% CPU) → c5.xlarge (40%)",
      },
      {
        from: 0,
        to: 0,
        label: "Total: $500K → $125K/mo (75% off!)",
        detail: "SP + Spot + Graviton + Rightsizing = maximum",
      },
    ],
    durationInFrames: 330,
  },
];
