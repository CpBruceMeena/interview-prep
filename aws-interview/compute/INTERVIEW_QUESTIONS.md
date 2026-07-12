# ☁️ AWS Compute — Staff-Level Interview Questions

> *10 questions covering EC2, Lambda, ECS, EKS, Fargate, Auto Scaling, and serverless architectures — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [EC2: Instance Types, ENI, Enhanced Networking](#1-ec2-instance-types-eni-enhanced-networking)
2. [EC2 Auto Scaling Groups: Policies & Lifecycle](#2-ec2-auto-scaling-groups-policies-lifecycle)
3. [AWS Lambda: Execution Model & Cold Starts](#3-aws-lambda-execution-model-cold-starts)
4. [Lambda Performance: Concurrency & Reservations](#4-lambda-performance-concurrency-reservations)
5. [ECS: Task Definition, Service, Cluster](#5-ecs-task-definition-service-cluster)
6. [EKS: Control Plane, Node Groups, Fargate](#6-eks-control-plane-node-groups-fargate)
7. [Fargate: Serverless Containers & Networking](#7-fargate-serverless-containers-networking)
8. [Spot Instances: Interruption Handling & Strategies](#8-spot-instances-interruption-handling-strategies)
9. [AWS Batch: Job Scheduling & Compute Environments](#9-aws-batch-job-scheduling-compute-environments)
10. [Hybrid: EC2 Reserved, Savings Plans, Cost Optimization](#10-hybrid-ec2-reserved-savings-plans-cost-optimization)

---

## 1. EC2: Instance Types, ENI, Enhanced Networking

**Q:** "Your application needs 100Gbps network throughput, NVMe local storage, and GPU compute. Walk through the EC2 instance families, how ENA (Enhanced Networking) works at the kernel level, and how to maximize network performance."

**What They're Really Testing:** Whether you understand the EC2 virtualization layer — Nitro hypervisor, ENA driver, and instance type selection for specific workload profiles.

### Answer

**EC2 Instance Families:**

```yaml
General purpose (M series):
  M7g: Graviton3, 64 vCPU, 256GB RAM, up to 50 Gbps ENA
  M7i: Intel Xeon, 48 vCPU, 384GB RAM, up to 50 Gbps ENA

Compute optimized (C series):
  C7g: Graviton3, 64 vCPU, 128GB RAM, up to 100 Gbps ENA
  C7i: Intel Xeon, max turbo 4.1GHz

Memory optimized (R/X series):
  R7g: Graviton3, 64 vCPU, 512GB RAM
  X2iedn: Intel Xeon, 128 vCPU, 4TB RAM, up to 100 Gbps, 3.8TB NVMe local

Storage optimized (I/D series):
  I4i: Intel Xeon, NVMe local (up to 30TB), 32 vCPU
  D3: Dense storage (up to 336TB HDD)

GPU (P/G series):
  P5: NVIDIA H100, 8 GPUs × 80GB HBM, 3200 Gbps EFA
  G5: NVIDIA A10G, 4 GPUs, up to 100 Gbps

Network optimized:
  Hpc7g: Graviton3E, instance-level EFA, 200 Gbps
  Trn1: Trainium chips for ML training, 1600 Gbps EFA
```

**Enhanced Networking & ENA:**

```
Nitro Hypervisor (replaces Xen since 2013):
  - Dedicated hardware for networking (ENA), storage (NVMe), and control
  - VirtIO-based, no host CPU involvement for data path
  - < 5μs network latency (vs 30-50μs with Xen)

ENA (Elastic Network Adapter):
  - Network throughput per instance: 25-100 Gbps
  - ENA Express (SRD): reliable datagram protocol
  - Single root I/O virtualization (SR-IOV): direct NIC-to-instance

Instance optimization for 100Gbps:
  1. Enable ENA in AMI
  2. Jumbo frames: MTU 9001 (within VPC), 1500 for internet
  3. Multi-queue: one RX/TX queue per vCPU
  4. RSS (Receive Side Scaling): distribute packets across CPUs
  5. EFA (Elastic Fabric Adapter): RDMA for HPC/ML

Instance storage (NVMe):
  I4i: 3.8TB NVMe per instance (max 30TB)
  Throughput: 16 GB/s read, 8 GB/s write
  IOPS: 1M+ random read, 500K random write
  Ephemeral: data LOST on stop/terminate!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Instance families** | Can match workload to appropriate family (M, C, R, I, P, etc.) |
| **Nitro architecture** | Understands hardware offloading for network/storage/control |
| **ENA deep dive** | Explains SR-IOV, multi-queue, jumbo frames for 100Gbps |
| **EFA for HPC** | Knows Elastic Fabric Adapter provides RDMA with OS bypass |

---

## 2. EC2 Auto Scaling Groups: Policies & Lifecycle

**Q:** "Your web service handles variable traffic: 10K requests/s during the day, 2K at night. Design an Auto Scaling Group with dynamic scaling policies, lifecycle hooks, and graceful shutdown. How does the ASG interact with the ALB target group?"

**What They're Really Testing:** Whether you understand ASG deeply — scaling policies (target tracking vs step scaling), lifecycle hooks, and integration with load balancers.

### Answer

**ASG + ALB Architecture:**

```
Application Load Balancer
    │
    ├── Target Group (port 8080)
    │       ├── EC2 instance A (InService)
    │       ├── EC2 instance B (InService)
    │       ├── EC2 instance C (Draining → soon terminated)
    │       └── EC2 instance D (Pending → soon InService)
    │
    └── Auto Scaling Group: my-app-asg
            ├── Launch Template: my-app-launch-template-v3 (AMI, instance type)
            ├── Min: 2, Max: 20, Desired: 4 (current)
            └── Scaling Policies:
                 ├── CPU Target Tracking (target: 60%)
                 └── Scheduled: scale to 3 at 8PM, to 10 at 8AM
```

**Scaling Policies:**

```yaml
# 1. Target Tracking (recommended)
# Automatically scales to maintain metric at target value
my-app-cpu-tracking:
  type: "TargetTrackingScaling"
  target_value: 60   # Keep CPU at 60% average
  metric: ASGAverageCPUUtilization
  # Pros: Simple, automatic, self-correcting
  # Cons: Can't specify custom scale-in/out cooldowns

# 2. Step Scaling (more control)
my-app-request-tracking:
  type: "StepScaling"
  adjustment_type: "ChangeInCapacity"
  
  step_adjustments:
  - metric_interval_lower: 0
    metric_interval_upper: 1000
    scaling_adjustment: 0          # Normal: no change
  
  - metric_interval_lower: 1000
    metric_interval_upper: 5000
    scaling_adjustment: 2          # Slight load: add 2 instances
  
  - metric_interval_lower: 5000
    scaling_adjustment: 5          # Heavy load: add 5 instances
  
  cooldown: 120                    # Wait 2 min between scaling activities

# 3. Scheduled Scaling (predictable patterns)
my-app-daytime-scale:
  type: "ScheduledScaling"
  schedule: "0 8 * * 1-5"         # Weekdays 8 AM
  min: 5, max: 20, desired: 10

my-app-nighttime-scale:
  type: "ScheduledScaling"
  schedule: "0 22 * * 1-5"        # Weekdays 10 PM
  min: 2, max: 5, desired: 3
```

**Lifecycle Hooks (Graceful Shutdown):**

```python
import boto3
import json

# Lifecycle hook: on instance termination, execute graceful shutdown
# Pattern: ASG sends SNS notification → Lambda performs hook

def lambda_handler(event, context):
    # 1. Parse lifecycle notification
    message = json.loads(event['Records'][0]['Sns']['Message'])
    instance_id = message['EC2InstanceId']
    hook_id = message['LifecycleHookId']
    asg_name = message['AutoScalingGroupName']

    # 2. Drain connections (ALB already stopped sending)
    # Actually: ALB connection draining and lifecycle hook work together
    # - ALB removes instance from target group (stops new connections)
    # - Lifecycle hook fires: instance is in "Terminating:Wait" state
    # - During wait: existing connections finish (connection draining timeout)

    # 3. Perform cleanup
    perform_drain(instance_id)  # e.g., signal service to stop accepting
    wait_for_active_connections_to_finish(instance_id)

    # 4. Complete lifecycle action (allows termination)
    client = boto3.client('autoscaling')
    client.complete_lifecycle_action(
        LifecycleHookName=hook_id,
        AutoScalingGroupName=asg_name,
        LifecycleActionResult='CONTINUE',
        InstanceId=instance_id
    )

    return {'statusCode': 200}
```

**ASG + ALB Warm-Up:**

```yaml
# New instances must be "warm" before serving traffic

# Launch template: configure health check
  InstanceMetadataOptions:
    HttpTokens: required   # IMDSv2 for security
    
  UserData: |
    #!/bin/bash
    # Install and configure application
    # Wait for app to be healthy before signaling
    
    /opt/start-app.sh
    
    # Signal to ASG that instance is healthy
    /opt/aws/bin/cfn-signal \
      --stack my-stack \
      --resource AutoScalingGroup \
      --region us-east-1

# ALB health check (before adding to rotation):
  HealthCheckPath: /health
  HealthCheckIntervalSeconds: 10    # Every 10s
  HealthCheckTimeoutSeconds: 5      # 5s timeout
  HealthyThresholdCount: 2          # 2 successful checks = healthy
  UnhealthyThresholdCount: 3         # 3 failed checks = unhealthy
  HealthCheckGracePeriod: 300        # 5 min grace period after launch
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Scaling policy types** | Can compare target tracking vs step vs scheduled for different patterns |
| **Lifecycle hooks** | Understands Terminating:Wait state for graceful shutdown |
| **ALB integration** | Knows target group health checks, connection draining, warm-up |
| **Cooldown tuning** | Sets appropriate cooldown to avoid scaling flapping |

---

## 3. AWS Lambda: Execution Model & Cold Starts

**Q:** "Your Lambda processes API requests with a 200ms latency SLA. Cold starts are causing 2-3 second delays for 5% of requests. Diagnose the cold start causes and design mitigation strategies including VPC cold starts, SnapStart, and provisioned concurrency."

**What They're Really Testing:** Whether you understand Lambda's execution environment lifecycle — sandbox creation, Firecracker microVM, and the trade-offs of each cold start mitigation.

### Answer

**Lambda Execution Environment Lifecycle:**

```
1. DOWNLOAD: Lambda service downloads your code from S3
   - Unzips to /var/task (ephemeral storage, 512MB default, max 10GB)

2. STARTUP: Firecracker microVM initialization
   - Create MicroVM (KVM-based, ~50ms)
   - Assign ENI from VPC (if VPC-configured): ~250-500ms
   - Configure IAM credentials (STS AssumeRole)

3. RUNTIME INIT: Language runtime startup
   - Python: import all modules → 100-500ms
   - Node.js: require all modules → 50-200ms
   - Java: JVM startup + class loading → 1-5s
   - .NET: JIT compilation → 1-3s

4. HANDLER INIT: Execute initialization code
   - Global scope (outside handler) runs
   - Database connections, HTTP clients, config loading
   - Time: variable (100ms - 5s)

5. INVOKE: Execute handler function
   - Warm: microsecond cost
   - Cold: total = DOWNLOAD + STARTUP + RUNTIME + HANDLER + INVOKE

Cold start latency:
  Python + no VPC: ~200ms
  Python + VPC:    ~500ms (ENI assignment!)
  Java + VPC:      ~5s (JVM + ENI)
  C# + VPC:        ~3s (JIT + ENI)
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-lambda-lifecycle.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Lambda Cold Start & Execution Lifecycle — download → Firecracker µVM → runtime init → handler → warm reuse — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

**Cold Start Mitigation Strategies:**

```yaml
# Strategy 1: Provisioned Concurrency (most expensive, most effective)
# Pre-warms N execution environments
  ProvisionedConcurrency: 50
  # Cost: always running (like EC2, ~$15/concurrency/month)
  # Zero cold starts for first 50 concurrent executions
  # Auto-scaling: gradual warm-up for spikes

# Strategy 2: SnapStart (Java only, very effective)
  SnapStart: true
  # Lambda takes a snapshot of the initialized execution environment
  # New invocations: load snapshot instead of running init
  # Cold start: 5s → 200ms (JVM pre-loaded!)
  # Limitation: no unique runtime state (ephemeral data must be lazy-init)

# Strategy 3: VPC cold start elimination
  # VPC Lambda = Lambda + Hyperplane ENI (pre-created)
  # Hyperplane: AWS-managed NAT, assigns ENI lazily
  
  # Solution: Reserve ENIs
  # AWS Lambda now supports VPC without ENI overhead (Lambda Hyperplane)
  # Must use: AWSLambdaVPCAccessExecutionRole with ENI creation
  # ENI created ONCE (per function+subnet combination), reused across invocations

# Strategy 4: Keep warm with scheduled invocations
  # CloudWatch Events → Lambda every 5 minutes
  # Prevents idle timeout (15-45 min inactivity → recycles)
  # Only works: if concurrency doesn't exceed provisioned instances

# Strategy 5: Language optimization
  # Python: lazy imports, use ORJSON instead of json, use uvloop
  # Node.js: minimize require(), use bundler (esbuild)
  # Java: use SnapStart or Quarkus/Micronaut native compilation
  # .NET: use NativeAOT compilation (AWS Lambda runtime for .NET 8)
```

**Lambda Execution Context Reuse:**

```python
# Execution context reuse: Lambda MAY reuse the same sandbox
# for multiple invocations (but NOT guaranteed!)

# What gets reused:
# - /tmp directory (512MB - 10GB)
# - Database connections (if created in global scope)
# - HTTP persistent connections
# - AWS SDK clients

# Best practice: initialize in GLOBAL scope (outside handler)
import boto3
import os

# Global scope: runs ONCE during cold start, REUSED on warm invocations
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['TABLE_NAME'])

def handler(event, context):
    # Handler scope: runs EVERY invocation
    return table.get_item(Key={'pk': event['key']})

# Worst practice: initialize inside handler
def bad_handler(event, context):
    # Creates new client EVERY invocation!
    dynamodb = boto3.resource('dynamodb')  # 200ms overhead per request!
    ...
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cold start causes** | Breaks down the 4 phases: download, VM, runtime, handler init |
| **VPC cold start** | Knows ENI attachment adds 250-500ms, now mitigated by Hyperplane |
| **Provisioned concurrency** | Understands cost vs latency trade-off |
| **SnapStart** | Knows Java SnapStart eliminates JVM startup cost |

---

## 4. Lambda Performance: Concurrency & Reservations

**Q:** "You have 3 Lambda functions sharing the same account: one processes API requests, one processes SQS messages, one runs a scheduled job. The API function is throttling during peak hours. How does Lambda concurrency work? How do reserved concurrency and provisioned concurrency differ?"

**What They're Really Testing:** Whether you understand Lambda's concurrency model — the account-level burst concurrency, reserved concurrency as a guarantee, and how throttling works.

### Answer

**Lambda Concurrency Model:**

```
Account-level concurrency limit: 1000 (default, can be increased)

Regional pool: 1000 concurrent executions shared across ALL functions

                    ┌─────────────────────────────────────────┐
                    │  Regional Concurrency Pool (1000)        │
                    │                                         │
                    │  ┌────────────────────┐                  │
                    │  │ API Handler (600)  │ (burst)         │
                    │  ├────────────────────┤                  │
                    │  │ SQS Handler (300)  │ (burst)         │
                    │  ├────────────────────┤                  │
                    │  │ Scheduled Job (100)│ (burst)         │
                    │  └────────────────────┘                  │
                    │                                         │
                    │  Region limit 1000 = 1000 total          │
                    │  If API spikes to 800 → SQS drops to 200 │
                    │  (unfair competition!)                   │
                    └─────────────────────────────────────────┘

Burst concurrency (per minute):
  - 500-3000 per region (varies by region)
  - First minute: 3000 concurrent
  - Subsequent: 500 concurrent per minute

Solution: Reserved Concurrency
  API Handler:   reserved=500 (guaranteed 500, max 500)
  SQS Handler:   reserved=300 (guaranteed 300, max 300)
  Scheduled Job: reserved=100 (guaranteed 100, max 100)
  Remaining:     100 (shared pool)
```

**Reserved vs Provisioned Concurrency:**

```yaml
Reserved Concurrency:
  - Guarantees: this function can always scale to this limit
  - Prevents: other functions from using this capacity
  - Cold starts: STILL possible within reserved concurrency
  - Cost: no extra charge (just the normal execution cost)
  - Use: critical functions that must not be throttled

Provisioned Concurrency:
  - Pre-warms: N execution environments BEFORE requests arrive
  - Zero cold starts: first N invocations are warm
  - Cost: $0.000004 per GB-second (24/7 cost, regardless of usage)
  - Scaling: application auto scaling can adjust provisioned level
  - Use: latency-sensitive workloads where cold starts are unacceptable

Comparison:
  Feature               | Reserved  | Provisioned
  ----------------------|-----------|---------------
  Prevents throttling   | ✅ Yes    | ✅ Yes
  Prevents cold starts  | ❌ No     | ✅ Yes
  Additional cost       | ❌ Free   | 💰 Per GB-second
  Auto-scaling          | ❌ Fixed  | ✅ Application auto scaling
```

**SQS Lambda Event Source Mapping (Throttling Handling):**

```python
# When Lambda throttles SQS messages:
# 1. Messages stay in SQS (VisibilityTimeout extends)
# 2. Lambda sends back: "too many invocations"
# 3. SQS retries after visibility timeout expires
# 4. Messages may go to DLQ after maxReceiveCount

# Architecture to avoid throttling:
# - Set reserved concurrency for SQS handler
# - Use batch size to reduce invocation count
# - Enable parallelization factor (SQS, only 1 per shard by default)

{
    "EventSourceMapping": {
        "BatchSize": 10,              # Max 10 messages per invocation
        "MaximumBatchingWindowInSeconds": 5,  # Wait 5s to fill batch
        "ParallelizationFactor": 1,   # Default: 1 concurrent per SQS message
        "FunctionResponseTypes": ["ReportBatchItemFailures"],  # Partial failures
        "ReservedConcurrency": 500    # Guarantee 500 concurrent
    }
}

# SQS throttling mitigation:
# With reserved concurrency=500 and batch size=10
# Max throughput: 500 × 10 = 5000 messages per invocation burst
# (but throttled by SQS's own limits: 120K messages/min from SQS to Lambda)
```

**Lambda Best Practices for Throughput:**

```yaml
# 1. Increase memory (CPU scales linearly with memory)
# 1792MB = full vCPU, <1792MB = fraction of vCPU
# More memory = faster execution = higher throughput per concurrency

# 2. Use burst concurrency wisely
# First minute of burst: 3000 concurrent
# Design for burst: have enough downstream capacity

# 3. Async invocation: SQS vs Lambda async
# SQS: managed retry, DLQ, batch, slow start protection
# Lambda async: 2x retry, DLQ, no throttling protection
# → Prefer SQS for critical workloads

# 4. Function timeout alignment
# API Lambda: 30s max (API Gateway 29s timeout)
# SQS Lambda: 6x visibility timeout / batch size (recommended)
# Event Lambda: matches event source timeout
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Concurrency pool** | Understands account-level shared concurrency |
| **Reserved vs provisioned** | Can explain guarantee vs pre-warming difference |
| **SQS throttling** | Knows messages stay in queue, retry after visibility timeout |
| **Memory scaling** | Understands CPU scales with memory allocation |

---

## 5. ECS: Task Definition, Service, Cluster

**Q:** "Design an ECS deployment for a microservice using Fargate launch type with service discovery, rolling updates, and canary deployments. How does the ECS service scheduler work? How does Service Connect differ from classic service discovery?"

**What They're Really Testing:** Whether you understand ECS deeply — task definition (CPU/memory/port mappings), service scheduling, deployment strategies, and service discovery.

### Answer

**ECS Task Definition:**

```json
{
    "family": "my-app",
    "taskRoleArn": "arn:aws:iam::123456789:role/my-app-task-role",
    "executionRoleArn": "arn:aws:iam::123456789:role/ecsTaskExecutionRole",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "512",        // 0.5 vCPU
    "memory": "1024",    // 1GB
    "containerDefinitions": [{
        "name": "my-app",
        "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/my-app:latest",
        "essential": true,
        "portMappings": [{
            "containerPort": 8080,
            "protocol": "tcp"
        }],
        "environment": [
            { "name": "DB_HOST", "value": "db.example.com" }
        ],
        "secrets": [
            { "name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:..." }
        ],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": "/ecs/my-app",
                "awslogs-region": "us-east-1",
                "awslogs-stream-prefix": "ecs"
            }
        },
        "healthCheck": {
            "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
            "interval": 10,
            "timeout": 5,
            "retries": 3,
            "startPeriod": 60
        }
    }]
}
```

**ECS Service + Deployment:**

```yaml
# Service definition:
my-app-service:
  type: ECS
  cluster: my-cluster
  taskDefinition: my-app:42          # Revision 42
  desiredCount: 4
  platformVersion: LATEST            # Fargate platform 1.4+
  networkConfiguration:
    awsvpcConfiguration:
      subnets:
        - subnet-abc
        - subnet-def
      securityGroups:
        - sg-app
      assignPublicIp: ENABLED         # Or DISABLED for private subnets
  
  # Load balancing
  loadBalancers:
    - targetGroupArn: arn:aws:elasticloadbalancing:...:my-app-tg
      containerName: my-app
      containerPort: 8080
  
  # Service discovery (Cloud Map)
  serviceRegistries:
    - registryArn: arn:aws:servicediscovery:...:my-app-ns
  
  # Service Connect (advanced service mesh)
  serviceConnectConfiguration:
    enabled: true
    namespace: "my-app.local"
    services:
      - portName: "my-app"
        clientAliases:
          - port: 8080

  # Deployment
  deploymentController:
    type: ECS                       # Rolling update (default)
    # type: CODE_DEPLOY             # Blue/green via CodeDeploy
    # type: EXTERNAL                # Third-party (Terraform, etc.)
  
  deploymentConfiguration:
    minimumHealthyPercent: 100      # Keep 100% of desired count
    maximumPercent: 200             # Allow 200% during deployment (8 total)
    alerts:
      - alarmName: my-app-high-error-rate
        rollback: true
  
  # Service auto scaling
  scalingPolicies:
    - type: TargetTrackingScaling
      targetValue: 60
      predefinedMetricSpecification:
        predefinedMetricType: ECSServiceAverageCPUUtilization
```

**Canary Deployment with CodeDeploy:**

```yaml
# Blue/green deployment: CodeDeploy + ECS
# Traffic shifting: linear 10% every 5 minutes

deploymentController:
  type: CODE_DEPLOY

# AppSpec.yaml (CodeDeploy):
version: 1
Resources:
  - TargetService:
      Type: AWS::ECS::Service
      Properties:
        TaskDefinition: "arn:aws:ecs:...:task-definition/my-app:43"
        LoadBalancerInfo:
          ContainerName: "my-app"
          ContainerPort: 8080

Hooks:
  - BeforeAllowTraffic: "arn:aws:lambda:...:before-allow-fn"
  # Run integration tests against new version
  - AfterAllowTraffic: "arn:aws:lambda:...:after-allow-fn"
  # Validate production traffic, rollback if needed

# Traffic shifting:
# Phase 1: 10% traffic for 5 min → observability check
# Phase 2: 100% traffic → completion
# Rollback: one-click revert to old task definition
```

**ECS Service Connect vs Cloud Map:**

```yaml
Cloud Map:
  - DNS-based service discovery
  - A-record, SRV record, or HTTP health checks
  - TTL: 60s default (stale DNS cache possible)
  - Separate Cloud Map namespace per environment
  - Simple, stateless, no traffic management

Service Connect:
  - Envoy sidecar proxy on each task
  - Intercepts traffic: app → service connect → destination
  - Features:
    - Load balancing: round-robin, health checks
    - Retries: configurable
    - Timeouts: per-service
    - Observability: metrics, tracing (AWS Distro for OpenTelemetry)
  - DNS: local namespace (service-name:port)
  - Port management: automatic assignment
  - No load balancer needed for inter-service communication
  
  Cloud Map + Service Connect comparison:
  Feature              | Cloud Map | Service Connect
  ---------------------|-----------|-----------------
  Load balancing       | DNS RR    | Client-side LB
  Health checks        | DNS TTL   | Real-time
  Retry/timeout        | ❌        | ✅ Built-in
  Require DNS cache    | ✅        | ❌ (real-time)
  Complexity           | Low       | Higher
  Best for             | Simple    | Complex microservices
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Task definition fields** | Knows task role, execution role, port mappings, secrets |
| **Deployment strategies** | Compares rolling vs blue/green vs canary |
| **Service Connect** | Understands Envoy sidecar proxy for inter-service comm |
| **Auto scaling** | Uses target tracking with predefined metrics |

---

## 6. EKS: Control Plane, Node Groups, Fargate

**Q:** "Design an EKS cluster for a multi-tenant SaaS platform with 50 microservices. Compare self-managed node groups, managed node groups, and EKS Fargate. How does the EKS control plane work? How do you secure cluster access?"

**What They're Really Testing:** Whether you understand the EKS architecture — the managed control plane, node group types, and the security model with IRSA and pod identity.

### Answer

**EKS Architecture:**

```
EKS Control Plane (AWS-managed, single tenant):
  - API server: Highly available (3 AZs)
  - etcd: Encrypted, auto-scaled, 3000+ nodes support
  - Controllers: scheduler, controller-manager, cloud-controller-manager
  - Certificates: auto-rotated every 90 days
  - Upgrades: manual trigger (or auto via EKS Auto Mode)

Data Plane (customer-managed):
  ┌─────────────────────────────────────────────────┐
  │ Node Group Options:                              │
  │  1. Managed Node Groups (EC2)                    │
  │  2. Self-Managed Node Groups (EC2)               │
  │  3. Fargate Profiles (serverless)                │
  │  4. EKS Auto Mode (new, fully managed)           │
  └─────────────────────────────────────────────────┘

  VPC CNI: aws-node (DaemonSet)
  - Assigns VPC IPs to pods directly (no overlay!)
  - Each pod gets a VPC IP from the subnet
  - Networking: native VPC routing (no VXLAN/overhead!)
  - Limits: EC2 ENI limits determine pod density
```

**Node Group Comparison:**

```yaml
Managed Node Groups:
  - AWS manages: EC2 ASG, launch template, patching, updates
  - Node updates: rolling replacement (drain + replace)
  - Customization: launch template for user data, instance types
  - Cost: no extra charge (pay for EC2 only)
  - Best for: most workloads (balance of control and automation)

Self-Managed Node Groups:
  - You manage: ASG, launch template, patching, updates
  - Full control: kubelet config, bootstrap script, custom AMIs
  - Node replacement: custom tooling (drain scripts, etc.)
  - Best for: GPU/ML workloads (custom AMI needed)

Fargate Profiles:
  - No nodes to manage: AWS runs pods as Fargate tasks
  - Isolation: each pod gets dedicated microVM
  - No node patching, no capacity management
  - Limitations:
    - DaemonSets not supported (no privileged containers)
    - Host networking not supported
    - PVC: only EFS (no EBS)
    - GPUs not supported
    - Pod startup: 30-60s (cold start)

EKS Auto Mode (newest):
  - Fully managed: control plane + data plane + add-ons
  - AWS chooses: instance types, scaling, updates
  - No node group configuration needed
  - Best for: teams wanting to focus on apps, not infrastructure

Performance comparison:
  100 pods across 3 AZs:
  - Managed: 2 m5.large nodes (~$70/month)
  - Fargate: 100 pods (100 × ~$15/month = $1500/month!)
  - EKS Auto: EC2 pricing (most cost-effective)
```

**Security: IRSA (IAM Roles for Service Accounts):**

```yaml
# IAM Roles for Service Accounts (IRSA)
# Pod gets IAM role via Kubernetes ServiceAccount

# Step 1: Create IAM role with trust policy
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::123456789:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E:sub": "system:serviceaccount:my-ns:my-app-sa"
      }
    }
  }]
}

# Step 2: Create Kubernetes ServiceAccount with annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: my-ns
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/my-app-role

# Step 3: Pod uses the ServiceAccount
spec:
  serviceAccountName: my-app-sa

# Pod gets: AWS credentials for my-app-role
# No: long-term credentials on EC2 instance profile!
# Security: least privilege per microservice
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Node group types** | Can compare managed vs self-managed vs Fargate vs Auto Mode |
| **VPC CNI** | Understands native VPC IPs vs overlay networking |
| **IRSA** | Explains OIDC federation and per-pod IAM roles |
| **Fargate limitations** | Knows DaemonSet, host networking, GPU, and PVC limitations |

---

## 7. Fargate: Serverless Containers & Networking

**Q:** "Your ECS service on Fargate needs to connect to an RDS database in a private subnet and an external API via the internet. Design the networking. How does Fargate's network stack work? Compare Fargate platform versions 1.3 vs 1.4."

**What They're Really Testing:** Whether you understand Fargate's network architecture — the Hyperplane ENI, NAT requirements, and platform version differences.

### Answer

**Fargate Networking Architecture:**

```
AWS Cloud ──────────────────────────────────
│                                          │
│  VPC                  Fargate Task       │
│  ┌─────────────────┐  ┌──────────────┐  │
│  │ Public Subnet    │  │ Container    │  │
│  │ 10.0.1.0/24     │  │ eth0:        │  │
│  │                 │  │ 10.0.1.42/24 │  │
│  │ IGW ─── NAT GW  │  │              │  │
│  └────────┬────────┘  │ Routes:      │  │
│           │           │ 0.0.0.0/0    │  │
│  ┌────────▼────────┐  │   → NAT GW   │  │
│  │ Private Subnet  │  │ 10.0.1.0/24  │  │
│  │ 10.0.2.0/24     │  │   → local    │  │
│  │                 │  │              │  │
│  │ RDS (internal)  │  └──────────────┘  │
│  │ 10.0.2.100/24  │                    │
│  └─────────────────┘                    │
│                                          │
│  Hyperplane ENI (AWS-managed):           │
│  - Assigned to Fargate task             │
│  - Provides VPC connectivity            │
│  - No public IP without NAT             │
└──────────────────────────────────────────┘
```

**Platform Versions:**

```yaml
Platform version 1.3 (Legacy):
  - Network: Linux bridge, task ENI in VPC
  - No internal DNS (must use custom DNS)
  - No EFS support
  - No ephemeral storage management
  - Task ENI: created/destroyed with each task start/stop

Platform version 1.4 (Current):
  - Network: awsvpc, task ENI directly in VPC
  - DNS resolution: VPC DNS resolver (Route53 Resolver)
  - EFS: supports EFS filesystem mounts
  - Ephemeral storage: 20GB default, 200GB max
  - Task ENI: pre-warmed (faster task startup!)
  - Security group: per task ENI (fine-grained security)

Platform version 1.5+ (Latest):
  - EBS: supports EBS volumes (Fargate + EBS!)
  - Faster startup: optimized Firecracker microVM
  - GPU: supports GPU workloads
  - Graviton: supports ARM-based Fargate tasks
  - Improved observability: enhanced CloudWatch metrics

AWS Fargate Platform differences:
  Feature                | 1.3     | 1.4     | 1.5+
  -----------------------|---------|---------|------
  awsvpc network mode    | ✅      | ✅      | ✅
  EFS volumes            | ❌      | ✅      | ✅
  EBS volumes            | ❌      | ❌      | ✅
  Ephemeral storage >20GB| ❌      | ✅ 200GB| ✅
  GPU                    | ❌      | ❌      | ✅
  Graviton               | ❌      | ✅      | ✅
  Task startup speed     | ~60s    | ~30s    | ~15s
```

**NAT Gateway Cost Optimization:**

```yaml
# Fargate in private subnet needs NAT for internet access
# NAT Gateway: ~$32/month + $0.045/GB processed

# Cost example:
# 50 Fargate tasks × 100GB data/month = $32 + (5000 × 0.045) = $257/month!

# Optimization strategies:
# 1. VPC endpoints for AWS services (FREE data transfer!)
# S3 Gateway Endpoint: free
# DynamoDB Gateway Endpoint: free
# ECR API/DKR Endpoints: free
# CloudWatch Logs Endpoint: free
# Secrets Manager Endpoint: free
#
# 2. Only NAT for non-AWS external APIs
# Most traffic stays within AWS → near-zero NAT cost

# 3. Shared NAT Gateway across multiple VPCs
# Transit Gateway + shared NAT (cost split across teams)

# 4. NAT Instance (EC2) as cheaper alternative
# c6g.large NAT instance: ~$25/month (vs $32 NAT Gateway)
# But: less available, needs manual failover
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Fargate networking** | Understands awsvpc mode, task ENI, NAT requirement |
| **Platform versions** | Knows 1.4+ supports EFS, 1.5+ supports EBS and GPU |
| **NAT cost optimization** | Uses VPC endpoints to minimize NAT data processing |
| **Security groups** | Applies per-task security groups for micro-segmentation |

---

## 8. Spot Instances: Interruption Handling & Strategies

**Q:** "You run a batch processing workload on EC2 that costs $50K/month in on-demand. How would you migrate to Spot Instances to reduce costs by 70%? Design the interruption handling strategy: how to checkpoint, handle termination notices, and diversify instance types."

**What They're Really Testing:** Whether you understand the Spot market — capacity pools, interruption notices, diversification strategies, and checkpointing for fault tolerance.

### Answer

**Spot Instance Market Mechanics:**

```
Spot pricing:
  - Spot price: dynamic, based on supply/demand of spare capacity
  - Price: typically 60-90% discount vs on-demand
  - "Spot" means: can be reclaimed with 2-minute notice

  - A h1.4xlarge: on-demand $1.00/hr → spot ~$0.20/hr (80% off)

Interruption reasons:
  1. Capacity needed back (most common)
  2. Spot price exceeds your max bid
  3. Service limit reached
  4. Instance type discontinued

Termination notice:
  - 2-minute warning (via Instance Metadata Service)
  - AWS sends: REBALANCE_IN_PROGRESS → INSTANCE_TERMINATION_NOTICE
  - Instance state: running → stopping/terminated (after 2 min)
```

**Interruption Handling Strategy:**

```python
import boto3
import signal
import json
import time
import requests

# Instance metadata endpoint
IMDS_TOKEN = "http://169.254.169.254/latest/api/token"
IMDS_SPOT = "http://169.254.169.254/latest/meta-data/spot/termination-time"

def get_imds_token():
    return requests.put(
        IMDS_TOKEN,
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    ).text

def check_termination_notice():
    """Check if spot termination notice is received"""
    try:
        token = get_imds_token()
        resp = requests.get(
            IMDS_SPOT,
            headers={"X-aws-ec2-metadata-token": token},
            timeout=2
        )
        if resp.status_code == 200:
            # 200 = termination notice received!
            termination_time = resp.text
            return termination_time
        return None
    except:
        return None

def graceful_shutdown(signum, frame):
    """Handle SIGTERM (from instance rebalance recommendation)"""
    print("Received termination notice. Starting graceful shutdown...")
    
    # Step 1: Stop accepting new work
    signal_work_queue_pause()
    
    # Step 2: Save checkpoint
    save_checkpoint(last_processed_id, "/data/checkpoint/spot-last.json")
    
    # Step 3: Upload checkpoint to S3 (cross-region durable)
    s3 = boto3.client('s3')
    s3.upload_file(
        "/data/checkpoint/spot-last.json",
        "my-batch-checkpoints",
        f"checkpoints/{instance_id}.json"
    )
    
    # Step 4: Drain connections (if any)
    database.flush()
    
    print("Checkpoint saved. Instance ready for termination.")

# Register signal handler
signal.signal(signal.SIGTERM, graceful_shutdown)
```

**Spot Diversification Strategy:**

```yaml
# Capacity Pool: a combination of (instance type, AZ)
# Problem: Single pool → high interruption risk

# Solution: Diversify across multiple pools

EC2 Fleet / Spot Fleet:
  AllocationStrategy: capacityOptimized  # AWS picks best pools
  
  LaunchTemplateOverrides:
  # Pool 1: different type, same AZ
  - InstanceType: c6g.4xlarge
    Subnet: subnet-a (us-east-1a)
    WeightedCapacity: 16 (units)
    
  # Pool 2: same type, different AZ
  - InstanceType: c6i.4xlarge
    Subnet: subnet-b (us-east-1b)
    WeightedCapacity: 16
    
  # Pool 3: different type, different AZ
  - InstanceType: m6i.4xlarge
    Subnet: subnet-c (us-east-1c)
    WeightedCapacity: 16
    
  # Pool 4: ARM architecture (cheaper + diverse!)
  - InstanceType: c7g.4xlarge
    Subnet: subnet-a
    WeightedCapacity: 16

# Strategy: 6-10 diverse instance types across 3 AZs
# Result: < 5% chance of mass interruption
```

**Spot Cost Savings Calculation:**

```yaml
Before (on-demand): 100 c6i.4xlarge
  $0.68/hr × 100 × 730 hrs/month = $49,640/month

After (spot + diversified):
  $0.15/hr (average across diverse pools)
  100 instances × $0.15 × 730 = $10,950/month
  2% interruption rate → 2 instances need replacement
  Replacement: $0.15 × 2 × 2hr backup = $0.60 (negligible)

Total: ~$11,000/month
Savings: ~78% ($39,000/month)

Additional savings: Reserved + Spot mix
  - Baseline (always on): Reserved Instances (1yr, ~40% off)
  - Peak/elastic: Spot (70-90% off)
  - Combined: 50-70% total savings
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Termination notice handling** | Monitors IMDS, checkpoint state, drains connections |
| **Capacity pool diversification** | Diversifies across types, sizes, and AZs |
| **Fleet allocation** | Uses capacityOptimized strategy for least interruption |
| **Reserved + spot mix** | Combines reserved for baseline, spot for elasticity |

---

## 9. AWS Batch: Job Scheduling & Compute Environments

**Q:** "You need to run 10,000 genomics analysis jobs daily. Each job takes 1-60 minutes on 16 vCPU, 64GB RAM. Design an AWS Batch architecture. How does Batch optimize resource utilization across job queues? How does it handle job dependencies?"

**What They're Really Testing:** Whether you understand AWS Batch's job scheduling — compute environments, job queues, job definitions, and the scheduling strategy for diverse job types.

### Answer

**AWS Batch Architecture:**

```
Job submission: 
  ┌────────────────────┐
  │    Job Queue:      │  ← Managed by Batch (FIFO by priority)
  │  genomics-queue    │
  │  Priority: 1-100   │
  │  State: ENABLED    │
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────┐
  │  Compute Env:      │  ← Manages EC2/Fargate/Spot resources
  │  genomics-env      │
  │  Type: MANAGED     │
  │  Instance: c6i.4xl  │
  │  Min/Max/Desired   │
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────┐
  │    Batch Jobs      │  ← Run on EC2/Fargate
  │  genomics-job-1    │
  │  genomics-job-2    │
  │  ...               │
  └────────────────────┘
```

**Job Definition:**

```json
{
    "jobDefinitionName": "genomics-analysis",
    "type": "container",
    "containerProperties": {
        "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/genomics:latest",
        "vcpus": 16,
        "memory": 65536,
        "command": ["analysis.py", "Ref::input_file", "Ref::output_bucket"],
        "environment": [
            {"name": "MAX_RUNTIME", "value": "3600"}
        ],
        "resourceRequirements": [
            {"type": "VCPU", "value": "16"},
            {"type": "MEMORY", "value": "65536"}
        ],
        "volumes": [{
            "name": "ref_data",
            "efsVolumeConfiguration": {
                "fileSystemId": "fs-abc123",
                "transitEncryption": "ENABLED",
                "authorizationConfig": {
                    "accessPointId": "fsap-abc123",
                    "iam": "ENABLED"
                }
            }
        }],
        "linuxParameters": {
            "sharedMemorySize": 16384  // 16GB /dev/shm
        },
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": "/aws/batch/genomics",
                "awslogs-stream-prefix": "batch"
            }
        }
    },
    "retryStrategy": {
        "attempts": 3,
        "evaluations": [
            {"action": "EXIT", "onExitCode": "1-127"},
            {"action": "RETRY", "onExitCode": "128-255"},
            {"action": "EXIT", "onReason": "OutOfMemory*"}
        ]
    },
    "timeout": {
        "attemptDurationSeconds": 7200
    }
}
```

**Job Dependencies & Sequencing:**

```yaml
# Job A (alignment) → Job B (variant calling) → Job C (report)

# Submit with dependencies:
aws batch submit-job \
    --job-name genomics-report \
    --job-queue genomics-queue \
    --job-definition genomics-report \
    --depends-on jobId=abc-123,type=SEQUENTIAL \
    --depends-on jobId=def-456,type=SEQUENTIAL

# Dependency types:
#   SEQUENTIAL: child runs after parent completes SUCCESSFULLY
#   TO_RETRY: child runs after retries exhausted (for error handling)
#   N_TO_N: parallel dependency (child runs after ALL parents complete)

# Array jobs (10,000 similar jobs):
aws batch submit-job \
    --job-name genomics-array \
    --job-queue genomics-queue \
    --job-definition genomics-analysis \
    --array-properties size=10000 \
    --parameters input_file=s3://my-bucket/inputs/

# Each child array job gets AWS_BATCH_JOB_ARRAY_INDEX (0-9999)
# Use index to determine which input to process:
# input_file = f"s3://data/input_{AWS_BATCH_JOB_ARRAY_INDEX}.fastq"
```

**Compute Environment Optimization:**

```yaml
# High-throughput compute environment (spot + on-demand mix):

genomics-compute:
  type: MANAGED
  computeResources:
    type: SPOT                    # 90% cost savings!
    allocationStrategy: BEST_FIT  # Use largest instances first
    
    minvCpus: 0
    desiredvCpus: 1024           # 64 × 16 vCPU instances
    maxvCpus: 4096               # 256 × 16 vCPU instances
    
    instanceTypes:
      - c6i.4xlarge              # Primary: 16 vCPU, 32GB
      - c6a.4xlarge              # AMD alternative
      - c7g.4xlarge              # Graviton (ARM, cheaper)
      - m6i.4xlarge              # Fallback (memory-optimized)
      - r6i.4xlarge              # Fallback
    
    # Spot bid percentage:
    bidPercentage: 80            # Max 80% of on-demand price
    spotIamFleetRole: arn:aws:iam::...:role/aws-ec2-spot-fleet-tagging-role
    
    # Block device:
    blockDeviceMappings:
      - deviceName: /dev/xvda
        ebs:
          volumeSize: 500        # 500GB GP3
          volumeType: gp3
          iops: 6000
          throughput: 500
    
    tags:
      Environment: production
      Project: genomics

# Scheduling policy (fair share):
genomics-queue:
  state: ENABLED
  priority: 10
  computeEnvironmentOrder:
    - order: 1
      computeEnvironment: genomics-compute-spot
    - order: 2
      computeEnvironment: genomics-compute-od
    
  schedulingPolicyArn: arn:aws:batch:...:scheduling-policy/genomics-fairshare

# Fair share policy:
genomics-fairshare:
  type: FAIR_SHARE
  fairSharePolicy:
    shareDecaySeconds: 3600      # Fairness window: 1 hour
    computeReservation: 10        # Reserve 10% for urgent jobs
    shareDistribution:
      - shareIdentifier: teamA
        weightFactor: 1.0
      - shareIdentifier: teamB
        weightFactor: 0.5
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Compute environment** | Optimizes spot with fallback to on-demand |
| **Job dependencies** | Uses SEQUENTIAL and N_TO_N for pipeline orchestration |
| **Fair share scheduling** | Implements resource sharing across teams/projects |
| **Array jobs** | Uses array jobs for embarrassingly parallel workloads |

---

## 10. Hybrid: EC2 Reserved, Savings Plans, Cost Optimization

**Q:** "Your AWS bill is $500K/month for EC2, Lambda, and Fargate. 30% is compute. Design a cost optimization strategy covering Reserved Instances, Savings Plans, right-sizing, and graviton migration. How do you track and prove cost savings?"

**What They're Really Testing:** Whether you understand AWS cost optimization holistically — purchase options, right-sizing, architecture changes, and observability.

### Answer

**AWS Compute Pricing Models:**

```yaml
Pricing model           | Discount | Commitment | Flexibility
------------------------|----------|------------|------------
On-Demand               | 0%       | None       | Maximum
Spot                    | 60-90%   | None       | Medium (interruptible)
Reserved Instance (1yr) | 40%      | 1 year     | Low (fixed instance)
Reserved Instance (3yr) | 60%      | 3 years    | Low (fixed instance)
Savings Plan (1yr)      | 30-40%   | 1 year     | High (compute, any instance)
Savings Plan (3yr)      | 50-60%   | 3 years    | High (compute, any instance)

Reserved Instance types:
  - Standard: fixed instance, capacity reservation (best discount)
  - Convertible: can change instance family (lower discount)
  - Scheduled: reserved for specific time windows

Savings Plan types:
  - Compute SP: most flexible (EC2, Fargate, Lambda)
  - EC2 Instance SP: less flexible (EC2 only, specific family)
  - SageMaker SP: SageMaker only
```

**Cost Optimization Strategy:**

```python
# Step 1: Right-sizing analysis
# Use AWS Compute Optimizer to find over-provisioned instances

# Step 2: Graviton migration
# ARM-based Graviton3: 20-30% better price/performance
# Migration steps:
#   1. Build ARM container image (multi-arch build)
#   2. Deploy to Graviton test environment
#   3. Validate performance
#   4. Replace x86 instances with Graviton

# Step 3: Savings Plan + Spot mix
def compute_optimal_mix(workload):
    baseline = workload.min_hourly  # Always-running portion
    elastic = workload.max_hourly - baseline  # Variable portion
    
    return {
        'savings_plan': baseline * 0.6,  # 3yr Compute SP: 60% off on-demand
        'spot': elastic * 0.8,           # Spot: 80% off on-demand
        'on_demand': 0,                   # No on-demand for elastic!
        # Annual savings: (baseline × 0.6 × on_demand) + (elastic × 0.8 × on_demand)
        # Typically: 65-75% total savings
    }

# Step 4: Serverless optimization
lambda_optimization:
  - Increase memory: 1792MB for CPU-bound functions (full vCPU)
  - Reduce timeout: pay only for execution time
  - Use Graviton Lambda: 20% cheaper
  - Use SnapStart: reduce Java cold start cost

  Cost comparison per 1M invocations (128MB, 100ms):
    x86 Lambda: 1M × ($0.0000166667/GB-s) × 0.125GB × 0.1s = $0.20
    ARM Lambda: $0.20 × 0.80 = $0.16 (20% cheaper)
    SnapStart: reduces Init duration cost by ~80%
```

**Cost Tracking & Attribution:**

```yaml
# Tagging strategy for cost allocation:
  - Environment: production, staging, development
  - Team/CostCenter: team-a, team-b, platform
  - Application: my-app, analytics-pipeline
  - Auto-scaling group: web-asg, worker-asg

# Create cost allocation tags in AWS Cost Explorer:
  Cost Allocation Tags:
    - user:Environment
    - user:Team
    - user:Application

# Budget alerts:
  AWS Budgets:
    - Monthly budget: compute-$200,000
    - Alert: 80% → email notification
    - Alert: 100% → SNS → Lambda auto-shutdown non-critical

# Compute Optimizer recommendations:
  AWS Compute Optimizer:
    - Finds over-provisioned instances (CPU < 20% → downsize)
    - Identifies rightsizing candidates
    - Provides estimated savings per recommendation
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Savings Plan vs RI** | Can explain flexibility difference and when to use each |
| **Graviton migration** | Plans multi-arch builds for ARM migration |
| **Spot + SP mix** | Uses SP for baseline, spot for elasticity |
| **Cost attribution** | Uses tags, budgets, and Compute Optimizer for tracking |

---

> *All 10 questions cover the full breadth of AWS Compute — from EC2 Nitro internals to Lambda cold start mitigation, ECS/EKS architectures, and cost optimization at scale.*
