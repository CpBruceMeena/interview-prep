#!/usr/bin/env python3
"""Embed animated sequence diagram videos into AWS architecture and compute interview markdown files."""

import os
from pathlib import Path

PROJECT_ROOT = Path("/Users/cpbrucemeena/Documents/Projects/interview-prep")

VIDEO_TEMPLATE = """
### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/{video_id}.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 {caption} — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

"""

# ─── Architecture File Insertions ─────────────────────────
ARCHITECTURE_INSERTIONS = [
    (
        "### 🔍 Staff-Level Evaluation\n\n| Criterion | What I'm Looking For |\n|-----------|----------------------|\n| **Pillar depth**",
        "arch-well-architected",
        "Animated Well-Architected Framework Six Pillars — Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization, and Sustainability",
    ),
    (
        "| **Active-active** | Understands conflict resolution (LWW, CRDTs, sharding) and idempotent writes |",
        "arch-multi-region-dr",
        "Animated Multi-Region Disaster Recovery — Aurora Global DB replication, Route53 failover, and RPO 1s/RTO 5min active-passive strategy",
    ),
    (
        "| **Cost optimization** | Has post-migration optimization plan with quantifiable savings levers |",
        "arch-cloud-migration-6rs",
        "Animated Cloud Migration 6 Rs — Retire, Retain, Rehost, Replatform, Refactor, Repurchase with prioritization matrix",
    ),
    (
        "| **Cost culture** | Implements team dashboards, weekly reviews, game days, SCP guardrails |",
        "arch-cost-governance",
        "Animated Cloud Cost Governance Framework — tagging, budgets, anomaly detection, rightsizing, and cost culture",
    ),
    (
        "| **Provisioned concurrency** | Knows when Provisioned Concurrency (Lambda) costs more than EC2 |",
        "arch-serverless-vs-containers",
        "Animated Serverless vs Containers Decision Framework — Lambda front-end + ECS back-end with SQS buffer",
    ),
    (
        "| **Orchestration Saga** | Implements Step Functions state machine with compensation flows and idempotency keys |",
        "arch-strangler-fig",
        "Animated Strangler Fig Pattern — incremental monolith migration with API Gateway routing and anti-corruption layer",
    ),
    (
        "| **Post-incident culture** | Runs post-Game Day reviews with concrete action items and ownership |",
        "arch-resilience-chaos",
        "Animated Resilience & Chaos Engineering — circuit breaker, bulkhead, retry backoff, and FIS Game Day scenario",
    ),
]

# ─── Compute File Insertions ─────────────────────────────
COMPUTE_INSERTIONS = [
    (
        "| **EFA for HPC** | Knows Elastic Fabric Adapter provides RDMA with OS bypass |",
        "aws-ec2-nitro-ena",
        "Animated EC2 Nitro Hypervisor & ENA Enhanced Networking — SR-IOV, multi-queue, jumbo frames, and 100 Gbps throughput",
    ),
    (
        "| **Cooldown tuning** | Sets appropriate cooldown to avoid scaling flapping |",
        "aws-asg-lifecycle",
        "Animated EC2 Auto Scaling Group Lifecycle — ALB target group, scaling policies, lifecycle hooks, and graceful shutdown",
    ),
    (
        "| **Memory scaling** | Understands CPU scales with memory allocation |",
        "aws-lambda-concurrency",
        "Animated Lambda Concurrency & Reservations Model — shared pool, reserved concurrency, provisioned concurrency, and SQS throttling safety",
    ),
    (
        "| **Fargate limitations** | Knows DaemonSet, host networking, GPU, and PVC limitations |",
        "aws-eks-architecture",
        "Animated EKS Architecture — managed control plane, VPC CNI, managed/self-managed node groups, Fargate profiles, and IRSA",
    ),
    (
        "| **Security groups** | Applies per-task security groups for micro-segmentation |",
        "aws-fargate-networking",
        "Animated Fargate Networking — Hyperplane ENI, NAT Gateway, VPC Endpoints, and platform version comparison",
    ),
    (
        "| **Reserved + spot mix** | Combines reserved for baseline, spot for elasticity |",
        "aws-spot-interruption",
        "Animated Spot Instance Interruption Handling — 2-min termination notice, checkpoint to S3, fleet diversification, and 78% cost savings",
    ),
    (
        "| **Array jobs** | Uses array jobs for embarrassingly parallel workloads |",
        "aws-batch-job-scheduling",
        "Animated AWS Batch Job Scheduling — compute environments, array jobs, spot + on-demand mix, fair share, and job dependencies",
    ),
    (
        "| **Cost attribution** | Uses tags, budgets, and Compute Optimizer for tracking |",
        "aws-cost-optimization-compute",
        "Animated Compute Cost Optimization — Savings Plans, Spot Instances, Graviton migration, and rightsizing for 75% savings",
    ),
]


def find_and_insert(file_path: str, insertions: list) -> None:
    full_path = PROJECT_ROOT / file_path
    if not full_path.exists():
        print(f"  ❌ File not found: {file_path}")
        return

    content = full_path.read_text()
    modified = False

    for marker, video_id, caption in insertions:
        if video_id in content:
            print(f"  ⏭️  Already embedded: {video_id}")
            continue

        pos = content.find(marker)
        if pos < 0:
            print(f"  ⚠️  Marker not found for {video_id}: {marker[:50]}...")
            continue

        # Find end of the evaluation table (the line containing the marker)
        end_of_line = content.find("\n", pos)
        if end_of_line < 0:
            end_of_line = pos

        # Find the next "---" or end of file
        next_section = content.find("\n---\n", end_of_line)
        if next_section < 0:
            next_section = len(content)

        video_section = VIDEO_TEMPLATE.format(video_id=video_id, caption=caption)

        # Insert video right BEFORE the evaluation table section
        # Actually, let's insert it AFTER the evaluation table, before the next section
        # Find the blank line after the table
        insert_pos = next_section

        content = content[:insert_pos] + video_section + content[insert_pos:]
        print(f"  ✅ Embedded {video_id}")
        modified = True

    if modified:
        full_path.write_text(content)
        print(f"  ✅ File updated: {file_path}")
    else:
        print(f"  ⏭️  No changes needed: {file_path}")


def main():
    print("Embedding AWS Architecture animated videos...\n")
    find_and_insert("aws-interview/architecture/INTERVIEW_QUESTIONS.md", ARCHITECTURE_INSERTIONS)

    print("\nEmbedding AWS Compute animated videos...\n")
    find_and_insert("aws-interview/compute/INTERVIEW_QUESTIONS.md", COMPUTE_INSERTIONS)

    print("\nDone!")


if __name__ == "__main__":
    main()
