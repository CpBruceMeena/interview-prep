# ☁️ AWS Cloud — Staff-Level Interview Questions

> *Deep-dive questions for core AWS services — every question expects principal engineer-level depth with production operational insight, cost optimization, and security best practices.*

---

## 📋 Topic Overview

```
aws-interview/
├── README.md
├── compute/              ← 10 questions: EC2, Lambda, ECS, EKS, Fargate
├── messaging/            ← 10 questions: SQS, SNS, EventBridge, Kinesis, MQ
├── networking/           ← 10 questions: ALB/NLB, API Gateway, Route53, CloudFront, VPC
├── storage-database/     ← 10 questions: S3, RDS, DynamoDB, ElastiCache, Aurora
├── security/             ← 8 questions: IAM, KMS, WAF, Cognito, Secrets Manager
└── architecture/         ← 8 questions: Well-Architected, multi-region, cost, migration
```

## 🎯 How to Use

1. **Pick a service area** — focus on ones you claim expertise in
2. **Read the question** — try to answer with specific AWS service details
3. **Study the answer** — understand the service limits, pricing models, and failure modes
4. **Connect services** — most real-world architectures combine multiple services
5. **Know the alternatives** — "When would you use SQS vs Kinesis vs EventBridge?"

---

## 🔗 Cross-Cutting Themes

| Theme | Appears In |
|-------|-----------|
| **Scaling** | EC2 ASG, Lambda concurrency, ECS/EKS HPA, DynamoDB autoscaling |
| **Security** | IAM policies, KMS encryption, WAF rules, Cognito auth |
| **Cost Optimization** | EC2 spot, S3 lifecycle, RDS reserved, Lambda provisioned concurrency |
| **High Availability** | Multi-AZ, multi-region, Route53 failover, RDS read replicas |
| **Event-Driven** | S3 events → SNS → SQS → Lambda, EventBridge scheduling |

---

> *Master these AWS services and you'll be prepared for Staff/Principal interviews at cloud-first companies, FAANG, and any organization with significant AWS infrastructure.*
