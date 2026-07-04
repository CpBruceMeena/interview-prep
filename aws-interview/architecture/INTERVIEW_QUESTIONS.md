# ☁️ AWS Architecture — Staff-Level Interview Questions

> *8 questions covering Well-Architected Framework, multi-region design, migration strategies, cost optimization, microservices, serverless vs containers, cloud-native patterns, and resilience engineering — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [AWS Well-Architected Framework: The Six Pillars](#1-aws-well-architected-framework-the-six-pillars)
2. [Multi-Region Architecture & Disaster Recovery](#2-multi-region-architecture-disaster-recovery)
3. [Cloud Migration Strategies: The 6 Rs](#3-cloud-migration-strategies-the-6-rs)
4. [Cost Optimization Architecture at Scale](#4-cost-optimization-architecture-at-scale)
5. [Microservices Architecture Patterns on AWS](#5-microservices-architecture-patterns-on-aws)
6. [Serverless vs Containers: Architecture Decision](#6-serverless-vs-containers-architecture-decision)
7. [Cloud-Native Design Patterns: Strangler Fig, CQRS, Saga](#7-cloud-native-design-patterns-strangler-fig-cqrs-saga)
8. [Resilience Engineering & Chaos Engineering](#8-resilience-engineering-chaos-engineering)

---

## 1. AWS Well-Architected Framework: The Six Pillars

**Q:** "Your CTO wants a formal Well-Architected Framework review of a production system processing $10M/month in transactions. Walk through the six pillars, the key questions you'd ask in each, and how you'd prioritize remediation. How do you operationalize WA reviews across 50 microservices?"

**What They're Really Testing:** Whether you understand the Well-Architected Framework as an operational tool — not just theory — and can drive continuous improvement at scale across an organization.

### Answer

**The Six Pillars:**

```yaml
1. Operational Excellence:
   - Run and monitor systems to deliver business value
   - Key questions:
     - How do you understand the health of your workload? (dashboards, alarms)
     - How do you manage workload resources? (IaC, tagging, change management)
     - How do you improve operations? (runbooks, post-incident reviews)
   - Best practices:
     - Infrastructure as Code (CloudFormation/Terraform)
     - Immutable infrastructure (AMI/container immutability)
     - Deployment pipelines (CI/CD with canary deployments)
     - Observability: structured logging, distributed tracing, metrics
   - Metrics: MTTR, deployment frequency, change failure rate

2. Security:
   - Protect data, systems, and assets
   - Key questions:
     - How do you manage identities? (IAM, SSO, least privilege)
     - How do you protect data at rest and in transit? (KMS, TLS)
     - How do you detect security events? (GuardDuty, Security Hub)
   - Best practices:
     - IAM: permission boundaries, SCPs, service-linked roles
     - Encryption: envelope encryption with KMS, S3 default encryption
     - Network: VPC isolation, security groups, NACLs
   - Metrics: time to detect/correlate/remediate security findings

3. Reliability:
   - Recover from failures and meet demand
   - Key questions:
     - How do you plan for failure? (Multi-AZ, multi-region)
     - How do you handle changes? (deployment rollback, feature flags)
     - How do you manage capacity? (auto-scaling, load testing)
   - Best practices:
     - Horizontal scaling (ASG, ECS service auto-scaling)
     - Graceful degradation (circuit breakers, bulkheads)
     - Data durability (S3 11 9s, RDS Multi-AZ, Aurora replication)
   - Metrics: availability %, RTO, RPO, error budget

4. Performance Efficiency:
   - Use computing resources efficiently
   - Key questions:
     - How do you select compute resources? (right-sizing, Graviton)
     - How do you optimize storage? (S3 lifecycle, EBS gp3)
     - How do you monitor performance? (CloudWatch, Perf Insights)
   - Best practices:
     - Right-size: use Compute Optimizer to find over-provisioned resources
     - Graviton migration: 20-40% better price/performance
     - Serverless: eliminate idle capacity
   - Metrics: resource utilization %, cost per transaction, p50/p99 latency

5. Cost Optimization:
   - Avoid unnecessary costs
   - Key questions:
     - How do you match supply with demand? (auto-scaling, spot instances)
     - How do you monitor cost? (budgets, anomaly detection)
     - How do you optimize over time? (Savings Plans, Reserved Instances)
   - Best practices:
     - Spot instances: 60-90% discount for fault-tolerant workloads
     - Savings Plans: 30-60% discount with flexibility
     - S3 lifecycle: auto-move data to colder tiers
   - Metrics: unit cost (cost per transaction/customer), unused resources

6. Sustainability (newest pillar, 2021+):
   - Minimize environmental impact
   - Key questions:
     - How do you measure your carbon footprint? (Customer Carbon Footprint Tool)
     - How do you minimize impact? (Graviton, serverless, efficient code)
   - Best practices:
     - Graviton ARM: 60% less energy for same compute
     - Right-sizing: eliminate idle resources
     - Efficient storage: compress data, use lifecycle policies
   - Metrics: CO2e per workload, power usage effectiveness
```

**Prioritizing Remediation:**

```yaml
# WA review workflow for 50 microservices:

# Step 1: Triage by risk score
Risk = Likelihood × Impact
  Likelihood: 1-5 (how likely is this to fail?)
  Impact: 1-5 (how bad is the impact?)
  
  High risk (15-25): fix within 1 sprint (2 weeks)
  Medium risk (8-14): fix within 2 sprints (1 month)
  Low risk (1-7): prioritize by effort

# Step 2: Common high-risk findings:
# Pillar   | Finding                     | Risk | Fix
# ---------|-----------------------------|------|---------------------------
# Security | IAM roles too permissive    | 25   | Implement least privilege
# Reliabil | No multi-region DR          | 20   | Design DR plan
# Cost     | Right-size opportunities    | 16   | Use Compute Optimizer
# Security | S3 buckets publicly acessbl | 20   | Block public access
# Reliabil | No auto-scaling configured  | 15   | Implement ASG

# Step 3: Automate reviews
# AWS Well-Architected Tool: API-driven reviews
# Custom lenses: organization-specific best practices
# CI/CD integration: WA checks in deployment pipeline
# Score: track per-microservice WA score over time (goal: 80%+)
```

**Operationalizing WA Reviews:**

```yaml
# Quarterly WA review cadence:
# Month 1: Self-assessment (microservice owner fills out questions)
# Month 2: Peer review (two senior engineers review)
# Month 3: Remediation (fix high/medium findings)
# Month 4: Score tracking (update WA dashboard)

# WA tool configuration:
# - Use the AWS Well-Architected Tool (free)
# - Create a workload for each microservice
# - Define custom lenses for org-specific patterns
# - Link to milestones (Jira tickets for remediation)
# - Track improvement over time

# Reward: teams scoring 90%+ get fast-track deployment approval
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pillar depth** | Can explain specific best practices and metrics for each of the 6 pillars |
| **Prioritization** | Uses risk scoring (likelihood × impact) to triage remediation |
| **Operationalization** | Designs quarterly review cadence with self-assessment, peer review, remediation |
| **Automation** | Uses WA Tool API, CI/CD integration, and custom lenses for scale |

---

## 2. Multi-Region Architecture & Disaster Recovery

**Q:** "Design a multi-region architecture for a financial services platform with RPO of 1 second and RTO of 5 minutes. 99.999% availability required. Compare active-passive vs active-active strategies. How do you handle data replication across regions with strong consistency requirements?"

**What They're Really Testing:** Whether you understand the operational and architectural trade-offs of multi-region deployment — the hard realities of cross-region replication lag, DNS propagation, and failover complexity.

### Answer

**DR Strategies Comparison:**

```yaml
Backup & Restore:
  RPO: 24 hours (last backup)
  RTO: 12-24 hours (restore from S3/Glacier)
  Cost: low (S3 storage + occasional restore testing)
  Complexity: low
  Use: non-critical systems, dev/test

Pilot Light:
  RPO: minutes (replication lag)
  RTO: 30-60 minutes
  Cost: medium (smaller standby environment)
  Complexity: medium
  Architecture: replicate data, keep minimal compute running
  Use: moderately critical systems

Warm Standby:
  RPO: seconds (CDC replication)
  RTO: 5-15 minutes
  Cost: high (50-60% of prod capacity in DR)
  Complexity: high
  Architecture: scaled-down replica of prod, auto-scale on failover
  Use: critical production systems

Multi-Site Active-Active:
  RPO: near-zero (synchronous replication)
  RTO: <1 minute (DNS or Global Accelerator failover)
  Cost: very high (100% capacity in each region)
  Complexity: very high (conflict resolution, data consistency)
  Use: mission-critical, 99.999% required
```

**Active-Passive Architecture (for RPO=1s, RTO=5min):**

```yaml
# Primary: us-east-1 (active)
# DR: us-west-2 (warm standby)

┌─────────────────────────┐     ┌─────────────────────────┐
│  us-east-1 (Primary)    │     │  us-west-2 (DR)         │
│                         │     │                         │
│  Aurora Global DB       │────►│  Aurora (read replica)  │
│  (writer)               │     │  (replication lag <1s)  │
│                         │     │                         │
│  ALB (active)           │     │  ALB (standby, 0 weight)│
│                         │     │                         │
│  ECS services           │     │  ECS services           │
│  (desired: 100)         │     │  (desired: 10, standby) │
│                         │     │                         │
│  ElastiCache (primary)  │     │  ElastiCache (replica)  │
│  (Global Datastore)     │────►│  (cross-region repl.)   │
│                         │     │                         │
│  SQS queues (active)    │     │  SQS queues (empty)     │
│                         │     │                         │
│  DynamoDB Global Tables │────►│  DynamoDB (replica)     │
│  (active writer)        │     │  (active reader)        │
└─────────────────────────┘     └─────────────────────────┘

Failover sequence (RTO < 5 min):
  T+0:   Detect primary region failure (Route53 health check fails)
  T+0.5: Route53 failover → traffic shifted to us-west-2
  T+1:   Aurora promote reader → writer (~60s)
  T+2:   ECS services scale up from 10 → 100 desired (2 min)
  T+3:   ALB health checks pass → traffic flowing to new instances
  T+4:   Validate: all transactions processing
  T+5:   Failover declared complete

# RPO validation:
# - Aurora replication: <1s lag → at most 1 second of data loss
# - DynamoDB Global Tables: <1s replication
# - Application: idempotent writes to handle duplicate transactions
```

**Active-Active Architecture (for zero-downtime):**

```yaml
# Both regions actively serving traffic
# Requires: conflict resolution, idempotent writes, careful data modeling

┌──────────────────┐     ┌──────────────────┐
│  us-east-1       │     │  eu-west-1       │
│                  │     │                  │
│  Route53 latency │     │  Route53 latency │
│  (50% traffic)   │     │  (50% traffic)   │
│       │          │     │       │          │
│  Global Accelerator   │  Global Accelerator │
│       │          │     │       │          │
│  ALB + ECS       │     │  ALB + ECS       │
│       │          │     │       │          │
│  ┌──────────┐    │     │  ┌──────────┐    │
│  │DynamoDB  │    │     │  │DynamoDB  │    │
│  │Global Tab│◄───┼─────┼──►│Global Tab│    │
│  └──────────┘    │     │  └──────────┘    │
│       │          │     │       │          │
│  ┌──────────┐    │     │  ┌──────────┐    │
│  │SQS (FIFO)│    │     │  │SQS (FIFO)│    │
│  │per region│    │     │  │per region│    │
│  └──────────┘    │     │  └──────────┘    │
└──────────────────┘     └──────────────────┘

Conflict resolution:
  1. Last-writer-wins (DynamoDB): acceptable for some data
  2. CRDTs: mergeable data types (counters, sets)
  3. Application-level: version vectors, custom merge logic
  4. Shard by region: each region owns a subset of data (e.g., user region)

Data access patterns:
  - Read: local region (low latency)
  - Write: local region (async replicated)
  - Strong consistency reads: read from local region with conditional check
  - Cross-region reads: use Global Accelerator for low-latency
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|----------|----------------------|
| **DR strategies** | Can quantitatively compare backup/pilot/warm/active-active with RPO, RTO, cost |
| **Failover sequence** | Has granular step-by-step failover plan with timing for each step |
| **Cross-region data** | Uses Aurora Global DB, DynamoDB Global Tables, ElastiCache Global Datastore |
| **Active-active** | Understands conflict resolution (LWW, CRDTs, sharding) and idempotent writes |

---

## 3. Cloud Migration Strategies: The 6 Rs

**Q:** "Your company has 200 on-premises servers running a mix of legacy .NET applications, Java microservices, and Oracle databases. The CFO wants 40% cost reduction in 18 months. Walk through the migration strategy: how do you assess, prioritize, and execute? What are the 6 Rs and when do you use each?"

**What They're Really Testing:** Whether you understand cloud migration as a business transformation — not just a technical lift-and-shift — and can navigate the trade-offs between speed, cost, and risk.

### Answer

**The 6 Rs of Migration:**

```yaml
1. Rehost (Lift & Shift) — fastest, lowest risk:
   - Move applications as-is to EC2
   - Use: VMware Cloud on AWS, AWS SMS (Server Migration Service)
   - Timeline: weeks per app
   - Savings: 20-30% (data center exit, no hardware refresh)
   - Tools: AWS Application Migration Service (MGN), CloudEndure
   - Best for: time-sensitive migrations, apps needing immediate cloud benefits

2. Replatform (Lift, Tinker & Shift) — moderate effort:
   - Move to managed services without changing app code
   - Example: RDS instead of self-managed Oracle, ECS instead of EC2
   - Timeline: weeks to months
   - Savings: 30-50% (managed services reduce operational overhead)
   - Best for: databases to RDS/Aurora, web servers to Elastic Beanstalk

3. Refactor / Re-architect — highest effort, biggest benefit:
   - Rewrite or significantly modify applications
   - Example: monolith → microservices, Oracle → Aurora PostgreSQL
   - Timeline: months to years
   - Savings: 50-70% (serverless, right-sized, auto-scaling)
   - Best for: applications needing modernization, scale, or new features

4. Repurchase (Drop & Shop) — vendor change:
   - Replace with SaaS alternative
   - Example: CRM → Salesforce, CMS → WordPress.com
   - Timeline: months (procurement + migration)
   - Savings: varies (licensing consolidation)
   - Best for: non-differentiated applications (HR, CRM, email)

5. Retire — decommission:
   - Shut down applications that are no longer needed
   - 10-20% of apps are typically retired
   - Timeline: weeks (data archival + sunset)
   - Savings: 100% of hosting cost
   - Best for: zombie servers, duplicate apps, end-of-life systems

6. Retain (Revisit) — keep on-premises:
   - Applications that can't move yet or shouldn't move
   - Reasons: regulatory, latency-sensitive, pending replacement
   - Timeline: indefinite (revisit in 12 months)
   - Savings: 0% (but avoids migration cost/risk)
   - Best for: legacy mainframe, real-time trading systems, compliance-locked data
```

**Migration Assessment & Prioritization:**

```yaml
# Phase 1: Discovery (2-4 weeks)
# Use AWS Discovery Agent or Migration Evaluator

Discovery output per server:
  Server: web-001.prod.example.com
    CPU: 8 vCPU, avg 15% utilization (over-provisioned!)
    Memory: 32GB, avg 8GB used (75% waste)
    Storage: 500GB, 100GB used
    Network: 100Mbps peak
    Dependencies: db-001, cache-001, ldap-001
    Application: customer-portal (.NET 4.8, IIS)
    Database: SQL Server 2016 (50GB)

# Phase 2: Prioritization matrix
App       | Complexity | Business Value | Migration Strategy | Effort | Savings
----------|------------|----------------|-------------------|--------|--------
Portal    | Low        | High           | Replatform (ECS)  | 4 wk   | 50%
CRM       | High       | Medium         | Repurchase (Sales)| 8 wk   | 30%
Legacy DB | High       | High           | Rehost (RDS)      | 6 wk   | 60%
Reporting | Medium     | Low            | Retire            | 2 wk   | 100%

# Prioritize by: (Business Value − Complexity) / Effort
# High value + low complexity = quick wins (do first)
# Low value + high complexity = retain or retire

# Phase 3: Migration waves
Wave 1 (Month 1-3): Rehost 20 low-risk apps (quick wins, prove the model)
Wave 2 (Month 4-9): Replatform 40 apps (RDS, ECS, ElastiCache)
Wave 3 (Month 10-15): Refactor 5 strategic apps (microservices, serverless)
Wave 4 (Month 16-18): Retire 10 apps + migrate remaining 10
```

**Cost Optimization Post-Migration:**

```yaml
# Year 1: Optimize after migration
# On-prem cost: $200K/month (servers, licenses, power, cooling, staff)
# After rehost: $150K/month (25% savings)
# After replatform: $120K/month (40% savings)
# After refactor: $80K/month (60% savings)
# After optimization: $60K/month (70% total savings)

# Optimization levers (after migration):
# 1. Right-sizing: use Compute Optimizer
#    → 30% savings (downsize over-provisioned instances)
# 2. Graviton migration: ARM-based instances
#    → 20% savings (better price/performance)
# 3. Spot instances: for fault-tolerant workloads
#    → 60-90% savings on compute
# 4. Savings Plans: 1-year Compute SP
#    → 30-40% discount on compute
# 5. S3 lifecycle: move cold data to Glacier
#    → 80-95% storage savings
# 6. Reserved RDS instances: 3-year
#    → 40-60% database cost reduction

# Target: 40% cost reduction in 18 months
# Track with: AWS Cost Explorer + tagging + budgets
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **6 Rs fluency** | Can explain each R, when to use it, and typical savings/effort |
| **Assessment process** | Uses discovery tools to catalog servers, dependencies, and utilization |
| **Prioritization** | Creates wave plan (quick wins first, strategic refactors later) |
| **Cost optimization** | Has post-migration optimization plan with quantifiable savings levers |

---

## 4. Cost Optimization Architecture at Scale

**Q:** "Your AWS bill is $2M/month and growing 15% month over month. Your CFO wants a cost optimization strategy that doesn't sacrifice growth. Design a cloud cost governance framework covering tagging, budgets, anomaly detection, and automated remediation. How do you build a culture of cost awareness?"

**What They're Really Testing:** Whether you understand cloud cost management as a cultural and operational discipline — not just a one-time rightsizing exercise — and can design a governance framework that scales with the organization.

### Answer

**Cost Governance Framework:**

```yaml
# Three pillars of cloud cost governance:

Pillar 1: Visibility (Tagging + Allocation)
  ┌─────────────────────────────────────────────────────────────┐
  │ Tagging Strategy:                                           │
  │   Required tags (enforced by SCP):                          │
  │     - CostCenter: team-a, team-b, platform                  │
  │     - Environment: production, staging, development          │
  │     - Application: order-service, payment-service            │
  │     - Owner: dev-team@example.com                            │
  │     - AutoShutdown: true/false                               │
  │                                                             │
  │   Automated enforcement:                                     │
  │     - AWS Tag Policies (Organization level)                  │
  │     - SCP: deny launch if required tags missing              │
  │     - Lambda: auto-tag resources on creation                 │
  │                                                             │
  │   Cost allocation reports:                                   │
  │     - By CostCenter: $500K team-a, $300K team-b              │
  │     - By Environment: $1.2M prod, $400K staging, $400K dev  │
  │     - By Service: $600K compute, $400K storage, $300K data  │
  └─────────────────────────────────────────────────────────────┘

Pillar 2: Governance (Budgets + Anomaly Detection)
  ┌─────────────────────────────────────────────────────────────┐
  │ Budget Structure:                                            │
  │   Level 1: Organization ($2M/month)                         │
  │     → CTO gets alert at 80%, 90%, 100%                      │
  │                                                             │
  │   Level 2: Cost Center ($500K/team/month)                   │
  │     → Team lead gets alert at 85%                           │
  │                                                             │
  │   Level 3: Service ($100K/service/month)                   │
  │     → Service owner gets alert at 80%                       │
  │                                                             │
  │   Anomaly Detection (AWS Cost Anomaly Detection):           │
  │     - ML-based: learns normal spending patterns             │
  │     - Detects: unexpected spikes (10%+ above normal)        │
  │     - Root cause analysis: linked to specific service/region │
  │     - Alert: Slack + email within 24 hours                  │
  │                                                             │
  │   Automated response to anomaly:                             │
  │     - SNS → Lambda → analyze Cost Explorer                  │
  │     - If anomaly > $10K/day: auto-stop non-critical resources │
  │     - Create Jira ticket for investigation                  │
  └─────────────────────────────────────────────────────────────┘

Pillar 3: Optimization (Continuous Improvement)
  ┌─────────────────────────────────────────────────────────────┐
  │ Rightsizing (monthly):                                       │
  │   - AWS Compute Optimizer scans all EC2, ECS, Lambda       │
  │   - Finds over-provisioned resources (<20% CPU utilization) │
  │   - Estimated savings: $50K/month                           │
  │   - Auto-remediate: resize during maintenance window        │
  │                                                             │
  │   Resource type   | Over-provisioned | Target   | Savings   │
  │   c5.4xlarge (50) | 16 vCPU, 5% util  | c5.xlarge | $15K/mo │
  │   r5.2xlarge (30) | 64GB, 10% used    | r5.large  | $12K/mo │
  │   Lambda 1024MB   | 40% of invocations| 512MB     | $8K/mo  │
  │                                                             │
  │ Purchases (quarterly):                                       │
  │   - Compute Savings Plan (3yr, partial upfront): 50-60% off  │
  │   - RDS Reserved Instance (3yr): 40-60% off                 │
  │   - DynamoDB Reserved Capacity: 50-70% off                  │
  │                                                             │
  │ Architecture (continuous):                                   │
  │   - Graviton migration: 20-40% better price/performance     │
  │   - Spot instances: 60-90% off for batch/fault-tolerant     │
  │   - S3 Lifecycle: auto-move to IA/Glacier after N days      │
  │   - EBS gp3: 20% cheaper than gp2 with better performance  │
  └─────────────────────────────────────────────────────────────┘
```

**Automated Cost Remediation:**

```python
import boto3
import json

def lambda_handler(event, context):
    """
    Auto-remediate cost anomalies.
    Triggered by: AWS Budgets action or Cost Anomaly Detection.
    """
    anomaly = json.loads(event['detail']['analysis'])
    service = anomaly['service']
    estimated_impact = anomaly['estimatedImpact']['actualAmount']
    
    if estimated_impact > 10000:  # > $10K/day anomaly
        # Step 1: Identify the resources causing the spike
        resources = identify_anomalous_resources(anomaly)
        
        # Step 2: Categorize by criticality
        critical = [r for r in resources if r.get('critical', False)]
        non_critical = [r for r in resources if not r.get('critical', False)]
        
        # Step 3: Stop non-critical resources immediately
        for resource in non_critical:
            if resource['type'] == 'ec2':
                ec2 = boto3.client('ec2')
                ec2.stop_instances(InstanceIds=[resource['id']])
                print(f"Stopped non-critical EC2: {resource['id']}")
            
            elif resource['type'] == 'ecs-service':
                ecs = boto3.client('ecs')
                ecs.update_service(
                    cluster=resource['cluster'],
                    service=resource['service'],
                    desired_count=0
                )
                print(f"Scaled down ECS service: {resource['service']}")
        
        # Step 4: Notify owners
        sns = boto3.client('sns')
        sns.publish(
            TopicArn='arn:aws:sns:us-east-1:123456789:cost-anomaly',
            Message=json.dumps({
                'action': 'STOPPED_NON_CRITICAL',
                'resources': non_critical,
                'estimated_savings': estimated_impact,
                'investigation_link': f'https://console.aws.amazon.com/cost-management/home?region=us-east-1#/custom?anomaly={anomaly["anomalyId"]}'
            })
        )
```

**Building a Cost Culture:**

```yaml
# Cultural practices for cost awareness:

# 1. Cost dashboards per team
# Each team has a CloudWatch dashboard showing:
#   - Daily cost trend (7-day, 30-day)
#   - Cost by service (top 5)
#   - Cost anomalies (last 30 days)
#   - Unit cost (cost per request/transaction)

# 2. Weekly cost reviews
# 15 min in team standup:
#   - Cost change vs last week: +5% (expected: +3%)
#   - Anomaly: new QA environment left running over weekend
#   - Action: implement auto-shutdown for non-prod

# 3. Game Days (quarterly)
# Team challenge: reduce cost by 10% in 1 week
# Prize: team lunch sponsored by "savings"
# Typical findings: orphaned volumes, oversized instances, unused load balancers

# 4. Cost efficiency as a metric
# Include in performance reviews:
#   - Unit cost reduction: cost per API call, cost per active user
#   - Savings implemented: $ value of rightsizing/purchases
#   - Anomaly response time: time to remediate cost spikes

# 5. Guardrails (SCP enforcement)
# Prevent costly mistakes:
#   - Deny: non-Graviton instance types in dev
#   - Require: auto-shutdown tag for non-prod
#   - Limit: max instance size in dev accounts
#   - Enforce: gp3 instead of io1 unless approved
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Governance framework** | Designs 3-pillar approach: visibility, governance, optimization |
| **Anomaly detection** | Uses ML-based detection with automated remediation workflows |
| **Tagging strategy** | Enforces required tags via SCP, automates cost allocation |
| **Cost culture** | Implements team dashboards, weekly reviews, game days, SCP guardrails |

---

## 5. Microservices Architecture Patterns on AWS

**Q:** "Your team is migrating a monolithic .NET application to microservices on AWS. Design the architecture covering: service decomposition, inter-service communication, data management, and observability. How do you handle distributed transactions? How do you manage service discovery?"

**What They're Really Testing:** Whether you understand the real challenges of microservices — data consistency, service discovery, observability, and deployment complexity — not just the theoretical benefits.

### Answer

**Service Decomposition Strategy:**

```yaml
# Monolith: e-commerce platform
# Decomposed into bounded contexts:

┌─────────────────────────────────────────────────────────┐
│                    API Gateway (AWS API Gateway)         │
├─────────────┬────────────┬─────────────┬────────────────┤
│  Order      │  Payment   │  Inventory  │  Notification  │
│  Service    │  Service   │  Service    │  Service       │
│  ─────────  │  ────────  │  ─────────  │  ────────────  │
│  DynamoDB   │  RDS       │  DynamoDB   │  DynamoDB      │
│  + SQS      │  (Aurora)  │  + SQS      │  + SNS         │
└─────────────┴────────────┴─────────────┴────────────────┘

Decomposition rules:
  1. Business capability: each service owns a complete business function
  2. Data autonomy: each service owns its data (no shared databases!)
  3. Communication: async via events (SNS/SQS), sync only when necessary
  4. Deployment independence: each service deploys separately

  Strangler Fig pattern:
    Phase 1: New microservice handles NEW functionality
    Phase 2: Route NEW requests to microservice, old to monolith
    Phase 3: Migrate monolith features one by one
    Phase 4: Decommission monolith
```

**Inter-Service Communication Patterns:**

```yaml
# Pattern 1: Async Event-Driven (preferred)
# Order Service → SNS event → Payment Service (SQS) + Inventory Service (SQS)

Order Service:
  1. Create order (write to own DB)
  2. Publish: "OrderPlaced" event to SNS
  3. Return 202 Accepted to client

Payment Service:
  1. Consume "OrderPlaced" from SQS
  2. Process payment
  3. Publish: "PaymentProcessed" or "PaymentFailed" event

# Pattern 2: Sync Request-Reply (use only when necessary)
# API Gateway → Order Service → Payment Service (HTTP)

Order → Payment:
  GET /payment/status?orderId=123
  # Problem: synchronous coupling
  # Payment service failure = Order service failure
  # Mitigation: circuit breaker + timeout + fallback

# Pattern 3: EventBridge for complex routing
# Central event bus with rules

OrderPlaced → EventBridge → Rule: amount > $1000 → Fraud Detection Lambda
                         → Rule: all → Inventory SQS
                         → Rule: digital goods → Fulfillment SQS
```

**Handling Distributed Transactions — Orchestration Saga (Step Functions):**

```yaml
# Orchestration Saga: AWS Step Functions as central coordinator
# Each step has a compensating transaction for rollback

Order Saga state machine:
{
  "Comment": "Order Processing Saga",
  "StartAt": "ProcessPayment",
  "States": {
    "ProcessPayment": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:process-payment",
      "Next": "ReserveInventory",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "CancelOrder" }]
    },
    "ReserveInventory": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:reserve-inventory",
      "Next": "ConfirmOrder",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "RefundPayment" }]
    },
    "ConfirmOrder": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:confirm-order",
      "End": true,
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "ReleaseInventory" }]
    },
    "CancelOrder": { "Type": "Task", "Resource": "...cancel-order", "End": true },
    "RefundPayment": { "Type": "Task", "Resource": "...refund-payment", "Next": "CancelOrder" },
    "ReleaseInventory": { "Type": "Task", "Resource": "...release-inventory", "Next": "RefundPayment" }
  }
}

# Compensation flows (execute in reverse order of success):
# 1. ConfirmOrder fails → ReleaseInventory → RefundPayment
# 2. ReserveInventory fails → RefundPayment (no inventory to release)
# 3. ProcessPayment fails → CancelOrder (no payment to refund)

# Idempotency key pattern:
# Each saga instance gets a unique saga_id
# All compensating actions use saga_id to ensure idempotent retries
# Step Functions automatically retries on transient failures using the same input
```

**Service Discovery & Observability:**

```yaml
Service Discovery:
  ECS Service Connect:
    - Envoy sidecar proxy per task
    - DNS: service-name.namespace (e.g., order-service.prod)
    - Client-side load balancing + health checks
    - No ALB needed for inter-service calls
  
  AWS Cloud Map:
    - DNS-based: A records + SRV records + health checks
    - TTL: 60s (DNS caching)
    - Simple but less feature-rich than Service Connect
  
  API Gateway:
    - External entry point (public APIs)
    - Route: /orders → order-service, /payments → payment-service
    - Internal: use VPC link to private NLB/ALB

Observability (three pillars):
  Logging: CloudWatch Logs → central account
    - Structured logging (JSON)
    - Correlation ID across services (trace ID in every log)
    - Log group: /ecs/{service-name}
  
  Metrics: CloudWatch + custom metrics
    - RED metrics: Rate (requests/s), Errors (error rate), Duration (latency)
    - USE metrics: Utilization, Saturation, Errors (for infrastructure)
    - Business metrics: orders processed, revenue, conversion
  
  Tracing: AWS X-Ray
    - Trace: end-to-end request flow across services
    - Segments: API Gateway → Order → Payment → RDS
    - Annotations: order ID, customer ID for filtering
    - Sampling: 10% of requests (or 1 req/sec, whichever is higher)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Decomposition** | Uses bounded contexts, Strangler Fig pattern, data autonomy per service |
| **Async-first** | Prefers SNS/SQS events over sync HTTP; uses Saga for distributed transactions |
| **Service discovery** | Designs Service Connect or Cloud Map for inter-service communication |
| **Observability** | Implements RED metrics, structured logging with correlation IDs, X-Ray tracing |

---

## 6. Serverless vs Containers: Architecture Decision

**Q:** "Your team is building a new data processing platform with unpredictable traffic: 0-50K requests/second. Half the workload is latency-sensitive (API responses <100ms), half is batch processing (can take minutes). Walk through the decision framework for serverless (Lambda + Fargate) vs containers (ECS/EKS). When would you use each, and how do you combine them?"

**What They're Really Testing:** Whether you have a pragmatic decision framework — not dogmatic about serverless or containers — and can match the right compute model to the workload's actual requirements.

### Answer

**Decision Framework:**

```yaml
# Decision factors:
Factor                | Serverless (Lambda/Fargate) | Containers (ECS/EKS)
----------------------|----------------------------|---------------------
Startup latency       | 10-200ms cold start        | <1ms (always running)
Max execution time    | 15 min (Lambda), 8h (Farg)| No limit
Concurrency           | 1000 default (soft limit)  | Node limits (EC2)
Memory                | 10GB (Lambda), 120GB (Far) | Rack-scale (24TB)
GPU                   | ❌ (Lambda), ✅ (Fargate 1.5+)| ✅ All GPU types
Cost at low traffic   | Very low (pay per request) | High (pay per node)
Cost at high traffic  | Higher (per-request premium)| Lower (fixed cost)
Operational overhead  | Minimal (no servers)       | Cluster management
Customization         | Limited runtime/OS choices | Any container, any OS
Cold start mitigation | Provisioned concurrency    | N/A (always warm)

# Decision matrix for specific workloads:

Workload type          | Recommended | Rationale
-----------------------|-------------|---------------------------------------
Real-time API          | Lambda      | Auto-scale, pay per request
WebSocket connections  | ECS/Fargate | Long-lived connections, Lambda max 15min
Batch processing       | Batch/Fargate| Lambda 15min limit, GPU needs
ML inference           | EKS+Fargate | GPU required, long inference times
Event processing       | Lambda      | Native S3/SQS/SNS integration
Stateful workloads     | ECS+EFS     | Lambda is stateless by design
High-perf computing    | EKS+EC2     | Bare metal, EFA networking
CI/CD pipeline         | Fargate     | Ephemeral runners, no cluster management
```

**Combined Architecture (Serverless + Containers):**

```yaml
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway                                │
│                         │                                     │
│           ┌─────────────┴─────────────┐                     │
│           │                           │                      │
│     Lambda (API)                 Lambda (Auth)              │
│     - 50ms p99 latency          - JWT validation            │
│     - Auto-scale from 0         - Cache with ElastiCache    │
│           │                           │                      │
│           └─────────────┬─────────────┘                     │
│                         │                                     │
│              ┌──────────▼──────────┐                         │
│              │  SQS Queue          │                         │
│              │  (request buffer)   │                         │
│              └──────────┬──────────┘                         │
│                         │                                     │
│              ┌──────────▼──────────┐                         │
│              │  ECS/Fargate        │                         │
│              │  - Heavy processing  │                         │
│              │  - 5 min tasks      │                         │
│              │  - GPU for ML       │                         │
│              │  - Auto-scale:      │                         │
│              │    SQS queue depth  │                         │
│              └──────────┬──────────┘                         │
│                         │                                     │
│              ┌──────────▼──────────┐                         │
│              │  S3 (output) + SNS  │                         │
│              │  (notify completion)│                         │
│              └─────────────────────┘                         │
└─────────────────────────────────────────────────────────────┘

# Why this split:
# API layer: Lambda (auto-scale from 0, low latency, pay per request)
# Processing layer: ECS/Fargate (no 15-min limit, GPU support, lower cost at scale)
# Queue: SQS buffers traffic spikes (safety valve between layers)

# Cost comparison at 50K req/s:
# All Lambda: $12,000/month (higher per-request cost)
# All ECS: $8,000/month (but must run 24/7, even at 0 traffic)
# Hybrid Lambda+ECS: $6,500/month (Lambda handles low traffic, ECS for burst)
```

**When Serverless Becomes Expensive:**

```yaml
# Serverless cost traps:

# Trap 1: High-throughput, steady-state workloads
Lambda 128MB, 100ms, 1B requests/month:
  Cost: 1B × $0.0000002 × 0.125GB × 0.1s = $2.50
  Plus: 1B × $0.20/1M = $200
  Total: $202.50

Same workload on ECS (2 c6g.large, always on):
  Cost: 2 × $0.068 × 730 = $99.28/month
  → ECS is 50% cheaper for steady-state high throughput!

# Trap 2: Lambda Provisioned Concurrency
50 provisioned concurrency = 50 × $0.000004 × 730h = $146/month
  → Equivalent to a t3.medium EC2 instance! ($30/month)

# Trap 3: Data transfer costs
Lambda → S3 (same region): free
Lambda → DynamoDB (same region): free
Lambda → external API (internet): $0.09/GB
ECS → external API: same $0.09/GB (no difference)

# Recommendation:
# - Lambda: < 100K req/s, variable traffic, event-driven
# - ECS/Fargate: > 100K req/s steady, long-running, GPU
# - Hybrid: Lambda front-end + ECS back-end (best of both)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Decision framework** | Has structured criteria (latency, duration, cost, GPU) for choosing Lambda vs ECS |
| **Cost awareness** | Quantifies where Lambda gets expensive (steady-state high throughput) |
| **Hybrid architecture** | Designs Lambda front-end + ECS back-end with SQS as buffer |
| **Provisioned concurrency** | Knows when Provisioned Concurrency (Lambda) costs more than EC2 |

---

## 7. Cloud-Native Design Patterns: Strangler Fig, CQRS, Saga

**Q:** "Your legacy monolith is 500K lines of code, serving 10K customers. You need to modernize without downtime. Walk through the Strangler Fig pattern for incremental migration. When would you use CQRS? How does the Saga pattern handle distributed transactions across microservices?"

**What They're Really Testing:** Whether you understand cloud-native patterns as practical tools for incremental modernization — not just theoretical concepts — and can sequence them for real-world migration.

### Answer

**Strangler Fig Pattern:**

```yaml
# Phase 1: Identify Strangler Fig entry points
# New feature request: add real-time inventory tracking

┌─────────────────────────────────────────────────────┐
│  Legacy Monolith                                      │
│  ┌───────────────────────────────────────────┐       │
│  │ Orders │ Customers │ Payments │ Inventory │       │
│  └───────────────────────────────────────────┘       │
│                                                        │
│  New Feature: Real-time Inventory                     │
│  ┌─────────────────────┐  ┌────────────────────┐     │
│  │ API Gateway         │  │ Route: /inventory/*│     │
│  └──────────┬──────────┘  │ → New Service     │     │
│             │             └────────────────────┘     │
│  ┌──────────▼──────────┐                             │
│  │ Inventory Service    │  (NEW microservice)        │
│  │ - DynamoDB           │                             │
│  │ - Real-time updates  │                             │
│  │ - WebSocket API      │                             │
│  └─────────────────────┘                             │
└─────────────────────────────────────────────────────┘

# Phase 2: Incrementally migrate features
# Month 1: Inventory (new feature → new service)
# Month 2: Checkout → new Order Service (CQRS)
# Month 3: Customer profiles → new Customer Service
# Month 4: Legacy reports → new Analytics Service

# Phase 3: Route traffic gradually
# API Gateway routes:
#   /orders/v1/* → Legacy monolith (old customers)
#   /orders/v2/* → New Order Service (new customers)
#   /customers/* → New Customer Service (after migration complete)

# Phase 4: Decommission monolith
# When: all routes point to microservices
# Verify: zero traffic to legacy monolith for 30 days
# Archive: source code + data snapshot
```

**CQRS (Command Query Responsibility Segregation):**

```yaml
# Problem: single database handles both writes and complex reads
# Writes: simple CRUD (insert/update individual records)
# Reads: complex aggregations (10-table JOIN, GROUP BY, window functions)
# Result: read queries slow down write throughput

# Solution: Separate read and write paths

┌─────────────────────────────────────────────────────┐
│  CQRS Architecture for Order Service                  │
│                                                        │
│  Command Side (Write):                                 │
│  ┌────────────┐    ┌──────────────┐                   │
│  │ API: POST  │───►│ Write Model  │                   │
│  │ /orders    │    │ (DynamoDB)   │                   │
│  └────────────┘    └──────┬───────┘                   │
│                           │                            │
│                    DynamoDB Streams                    │
│                           │                            │
│  Query Side (Read):      │                            │
│  ┌────────────┐    ┌──────▼───────┐                   │
│  │ API: GET   │───►│ Read Model   │                   │
│  │ /orders    │    │ (Elasticache │                   │
│  │ /reports   │    │  + S3 + ES)  │                   │
│  └────────────┘    └──────────────┘                   │
│                                                        │
│  Eventual consistency: write → read in <100ms         │
└─────────────────────────────────────────────────────┘

# When to use CQRS:
# - Complex read queries that don't match write model
# - High read/write ratio (e.g., 100:1)
# - Different performance requirements for reads vs writes
# - Multiple read models needed (dashboard, API, search)

# When NOT to use CQRS:
# - Simple CRUD (no complex queries)
# - Strong consistency required (read-after-write, same transaction)
# - Small application (over-engineering)

# Implementation on AWS:
Write model: DynamoDB (single-item writes, low latency)
Read model: ElasticSearch (full-text search, aggregations)
Sync: DynamoDB Streams → Lambda → ElasticSearch
Cache: ElastiCache (frequently accessed read models)
Materialized views: event-sourced projections

# Example: Order dashboard displaying:
# - Total revenue by product category (7-day window)
# - Top 10 customers by spend
# - Order status distribution (pie chart)
# → Complex aggregation query
# → Read model: ElasticSearch pre-aggregated index
# → Write model: DynamoDB individual order records
```
**Saga Pattern — Choreography (Event-Driven):**

```yaml
# Choreography Saga: no central coordinator
# Each service emits events and subscribes to relevant events

Order Service         Payment Service        Inventory Service    Shipping Service
    │                      │                      │                    │
    │──OrderCreated─────►  │                      │                    │
    │                      │──PaymentAuthorized─► │                    │
    │                      │                      │──InventoryDeducted→│
    │                      │                      │                    │──ShipmentCreated→
    │                      │                      │                    │
    │◄─────────OrderConfirmed─────────────────────│                    │
    │                      │                      │                    │
    │ Failure: Payment fails                       │                    │
    │◄──PaymentFailed───  │                      │                    │
    │(compensation: cancel order, notify user)     │                    │
    │                      │                      │                    │
    │ Failure: Inventory unavailable               │                    │
    │                      │◄──InventoryFailed── │                    │
    │◄──PaymentRefund───  │(compensation: refund payment)             │
    │(compensation:        │                      │                    │
    │ notify user)         │                      │                    │

# Key difference from orchestration (covered in Q5):
# - Choreography: services talk via event bus (SNS/EventBridge)
# - Orchestration: Step Functions controls the flow
# 
# Choreography pros: simpler, less coupling, no single point of failure
# Choreography cons: harder to trace flow, no centralized error handling
# 
# When to use each:
#   Choreography: few services (<5), simple compensation logic
#   Orchestration: complex sagas with branching, compliance-heavy workflows
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Strangler Fig** | Plans incremental migration with API Gateway routing, no downtime |
| **CQRS** | Separates read/write paths, uses DynamoDB Streams for sync, knows when NOT to use it |
| **Orchestration Saga** | Implements Step Functions state machine with compensation flows and idempotency keys |

---

## 8. Resilience Engineering & Chaos Engineering

**Q:** "Design a resilience strategy for a payment processing system processing $1M/hour. How do you implement circuit breakers, bulkheads, and retry with exponential backoff? How do you use Chaos Engineering to validate resilience? Walk through a Game Day scenario."

**What They're Really Testing:** Whether you understand resilience as an engineering discipline — not just HA configuration — and can design failure injection experiments to validate system behavior under real failure conditions.

### Answer

**Resilience Patterns:**

```yaml
# Pattern 1: Circuit Breaker
# Prevents cascading failures when downstream service is unhealthy

┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Payment API    │───►│ Circuit        │───►│ Payment        │
│                │    │ Breaker        │    │ Gateway (3rd   │
│                │    │                │    │ party)         │
│                │    │ States:        │    │                │
│                │    │  CLOSED: normal│    │                │
│                │    │  OPEN: failing │    │                │
│                │    │  HALF_OPEN: try│    │                │
└────────────────┘    └────────────────┘    └────────────────┘

# Circuit breaker configuration:
circuit_breaker:
  failure_threshold: 5        # Open after 5 consecutive failures
  success_threshold: 3        # Close after 3 consecutive successes
  timeout: 30000              # 30 seconds in OPEN state before HALF_OPEN
  half_open_limit: 1          # Only 1 request when in HALF_OPEN

# Implementation:
def charge_payment(order_id, amount):
    cb = circuit_breaker.get('payment-gateway')
    
    if not cb.allow_request():
        # Circuit is OPEN → fail fast
        queue_payment_for_retry(order_id, amount, delay=30000)
        return PaymentResult(status='QUEUED', message='Circuit open, retrying later')
    
    try:
        result = payment_gateway.charge(amount)
        cb.record_success()
        return result
    
    except (ConnectionError, TimeoutError) as e:
        cb.record_failure()
        
        if cb.is_open():
            # Open circuit → switch to retry queue
            queue_payment_for_retry(order_id, amount, backoff=True)
        
        raise

# Pattern 2: Bulkhead (isolate failure domains)
# Prevents one service failure from consuming all resources

┌─────────────────────────────────────────────┐
│               Thread Pools                    │
│                                                │
│  ┌──────────────────┐  ┌──────────────────┐  │
│  │ Payment Pool      │  │ Notification Pool│  │
│  │ max: 10 threads  │  │ max: 5 threads   │  │
│  │ queue: 100       │  │ queue: 50        │  │
│  └──────────────────┘  └──────────────────┘  │
│                                                │
│  ┌──────────────────┐  ┌──────────────────┐  │
│  │ Report Pool       │  │ Health Check Pool│  │
│  │ max: 2 threads   │  │ max: 2 threads   │  │
│  │ queue: 10        │  │ queue: 10        │  │
│  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────┘

# Benefit: Payment pool exhaustion does NOT affect health checks
# Result: system stays alive (degraded but operational)

# Pattern 3: Retry with Exponential Backoff + Jitter
def retry_with_backoff(operation, max_retries=5):
    for attempt in range(max_retries):
        try:
            return operation()
        except (TransientError, ThrottlingError) as e:
            if attempt == max_retries - 1:
                raise  # Last attempt failed permanently
            
            # Exponential backoff: 1s, 2s, 4s, 8s, 16s
            delay = 2 ** attempt
            
            # Add jitter: ±50% random variance
            jitter = random.uniform(0.5, 1.5)
            delay = delay * jitter
            
            time.sleep(delay)
            
            # On retry: try alternate endpoint if available
            operation.endpoint = select_healthy_endpoint()
```

**Chaos Engineering Principles:**

```yaml
# Chaos Engineering: proactive failure testing
# Core principle: inject failures in production to validate resilience

# AWS Fault Injection Simulator (FIS):
# Managed chaos engineering service

# Experiment template:
Experiment: payment-system-resilience
  Targets:
    - payment-service (ECS service, us-east-1)
  
  Actions:
    - Stop EC2 instances: 20% of tasks
      Duration: 5 minutes
    - Network latency: inject 500ms on 30% of requests
      Duration: 3 minutes
    - CPU stress: 80% utilization on 2 instances
      Duration: 2 minutes
  
  Stop conditions:
    - Error rate > 5% (if exceeded, rollback immediately)
    - P99 latency > 2s
    - Payment failures > 1% of total
```

**Game Day Scenario: Payment System Failure:**

```yaml
# Game Day: Simulate payment gateway outage

Pre-conditions:
  - All teams on-call are available
  - Monitoring dashboards are configured
  - Runbook is updated
  - Stakeholders are informed (no surprises)

Experiment timeline:

T-1 week: Announce Game Day
  - Teams prepare: review runbooks, check monitoring
  - Communication plan: who to notify if things go wrong

T-0: Inject failure
  FIS Action: Block all traffic to payment-gateway.example.com
  Expected: Payment circuit breaker opens within 30 seconds

T+1min: Detection
  CloudWatch alarm: PaymentErrorRate > 10%
  Dashboard: Circuit breaker shows OPEN state
  Alert: PagerDuty notifies on-call engineer

T+3min: Mitigation
  Service switches to degraded mode:
  - New payments queued (SQS) instead of processed
  - 202 Accepted returned with "Processing" status
  - Customers see: "Payment pending, we'll notify you"
  - No data loss (all queued)

T+5min: Recovery
  FIS removes the block
  Circuit breaker: transitions to HALF_OPEN
  First request: try one request → success
  Circuit breaker: transitions to CLOSED

T+6min: Backlog processing
  SQS queue has 10,000 pending payments
  Payment service scales up to drain queue
  Auto-scaling: SQS queue depth triggers scale-out

T+10min: All clear
  Queue drained (10K payments processed)
  Error rate back to normal (<0.1%)
  Circuit breaker: CLOSED (normal operation)

Post-Game Day review:
  What went well:
    - Circuit breaker opened correctly
    - Queued payments prevented data loss
    - Auto-scaling handled backlog
  
  What to improve:
    - Alert was 30 seconds late (tune health check interval)
    - Runbook was outdated (step 3 was wrong)
    - Some customers saw 500 errors (add better error messages)
  
  Action items:
    - Fix runbook (owner: on-call team, due: 1 week)
    - Reduce health check interval from 30s to 10s
    - Add "maintenance mode" status page for customer visibility
```

**Resilience Metrics & Monitoring:**

```yaml
# Key resilience metrics:

Metric                  | Target        | Description
------------------------|---------------|----------------------------------------
Availability            | 99.99%        | Uptime across all services
Error rate              | <0.1%         | 5xx errors / total requests
P99 latency             | <500ms        | Slowest 1% of requests
Circuit breaker state   | CLOSED        | Should be closed >99% of time
SQS queue depth         | <1000         | Messages waiting to be processed
DLQ depth               | 0             | Messages that failed permanently
Recovery time (MTTR)    | <5 min        | Time to recover from failure

# Monitoring:
# CloudWatch dashboard: Service Health
# - Circuit breaker status per service (OPEN/CLOSED)
# - Error rate (5xx) per service, per endpoint
# - P50/P99/P999 latency per service
# - SQS queue depth (showing backlog)
# - DLQ count (spike = permanent failures)
# - Auto-scaling events (scale-in/out activity)

# Alarms (PagerDuty):
# - PaymentErrorRate > 1% → Critical (page on-call)
# - Any circuit breaker OPEN > 1 min → Warning
# - SQS queue depth > 10K → Warning
# - DLQ has messages → Info (investigate next business day)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Circuit breaker** | Implements with failure/success thresholds, half-open state, fast-fail on open |
| **Bulkhead isolation** | Separates thread pools for different service types to prevent cascading failure |
| **Chaos Engineering** | Designs FIS experiments with stop conditions (error budget), Game Day scenarios |
| **Post-incident culture** | Runs post-Game Day reviews with concrete action items and ownership |

---

> *All 8 questions cover the full breadth of AWS architecture — from Well-Architected reviews and multi-region DR to cloud-native patterns and chaos engineering.*
