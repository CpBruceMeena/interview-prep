# ☁️ AWS Cloud — Staff-Level Interview Questions

> *Deep-dive questions on core AWS services. Each answer starts with a 30-second version, then covers the mechanism, trade-offs, failure modes and what interviewers ask next. Service limits, prices and features were last checked against AWS documentation in October 2026; AWS changes quickly, so re-check numbers before quoting them in an interview.*

---

## 📋 Topic Overview

| Area | Questions | Covers |
|------|-----------|--------|
| [Compute](compute/INTERVIEW_QUESTIONS.md) | 10 | EC2 and Nitro, Auto Scaling, Lambda, ECS, EKS, Fargate, Spot, Batch, compute cost |
| [Messaging](messaging/INTERVIEW_QUESTIONS.md) | 10 | SQS, SNS, EventBridge (buses, Pipes, schemas), Kinesis, Amazon MQ, event-driven patterns |
| [Networking](networking/INTERVIEW_QUESTIONS.md) | 10 | VPC design, ALB/NLB, Route 53, CloudFront, Global Accelerator, Transit Gateway, VPN/Direct Connect, flow logs, WAF/Shield, SGs vs NACLs |
| [Storage & Database](storage-database/INTERVIEW_QUESTIONS.md) | 10 | S3, RDS, Aurora, DynamoDB, ElastiCache/MemoryDB, RDS Proxy, DMS, Glacier |
| [Security](security/INTERVIEW_QUESTIONS.md) | 8 | IAM, SCPs/RCPs, KMS, Cognito, WAF, Secrets Manager, GuardDuty, Security Hub, reference architecture |
| [Architecture](architecture/INTERVIEW_QUESTIONS.md) | 8 | Well-Architected, multi-Region DR, migration (7 Rs), cost governance, microservices, serverless vs containers, resilience |

## 🎯 How to Use

1. **Pick a service area**, starting with the ones on your CV; interviewers go deepest there.
2. **Answer out loud first**, then compare with the 30-second answer at the top of each question.
3. **Learn the numbers that drive designs**: per-partition and per-shard limits, timeouts, payload sizes, failover times, and what things cost per request or per GB.
4. **Connect services**: most real designs combine several (S3 → EventBridge → SQS → Lambda → DynamoDB).
5. **Know the alternatives and when you'd pick each**: SQS vs Kinesis vs EventBridge, Lambda vs Fargate vs EC2, Aurora vs DynamoDB vs DSQL.

---

## 🔗 Cross-Cutting Themes

| Theme | Appears In |
|-------|-----------|
| **Scaling** | EC2 Auto Scaling, Lambda concurrency, ECS/EKS autoscaling, DynamoDB partitions, Kinesis shards |
| **Security** | IAM and SCPs/RCPs, KMS encryption, WAF rules, Cognito auth, data perimeters |
| **Cost Optimization** | Spot, Savings Plans, Graviton, S3 lifecycle, NAT vs VPC endpoints, Lambda vs containers break-even |
| **High Availability** | Multi-AZ, multi-Region (Aurora Global Database, DynamoDB global tables), Route 53 ARC, Global Accelerator |
| **Event-Driven** | S3 events → EventBridge → SQS → Lambda, SNS fan-out, outbox pattern, sagas |
| **Idempotency** | SQS/SNS at-least-once delivery, Lambda retries, payment retries, DMS/CDC replays |

---

> *Work through these and you'll be ready for staff-level AWS design and deep-dive rounds.*
