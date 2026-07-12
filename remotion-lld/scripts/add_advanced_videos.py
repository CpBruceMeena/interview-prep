"""
Add animated sequence diagram videos to advanced content files.
Handles the 5 areas: CI/CD, Kubernetes, Networks, Distributed Systems, Architecture.
"""
import os
import re
from pathlib import Path

REPO_ROOT = Path("/Users/cpbrucemeena/Documents/Projects/interview-prep")
VIDEO_PATH = "../../../assets/videos"

def video_html(video_id: str, caption: str, width: str = "900") -> str:
    return f"""
<p align="center">
  <video controls width="{width}" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="{VIDEO_PATH}/{video_id}.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — {caption}. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>
"""

# ─── Config: file, marker, video_id, caption ────────────────

INSERTIONS = [
    # ── CI/CD Deployment Guide ──
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "### 2.1 The Complete Pipeline (Overview)",
        "after": "```\n\n**Each stage in detail:**",
        "video_id": "cicd-end-to-end-pipeline",
        "caption": "CI/CD Pipeline — Code → Commit → CI (Test) → Build (Artifact) → CD (Promote) → Production (Serve)",
    },
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "### Blue-Green Deployment",
        "after": "```\n\n### Canary Release",
        "video_id": "cicd-blue-green-deployment",
        "caption": "Blue-Green Deployment — Two identical environments with instant switch and rollback",
    },
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "### Canary Release",
        "after": "```\n\n### Feature Flags (Feature Toggles)",
        "video_id": "cicd-canary-release",
        "caption": "Canary Release — Progressive traffic shift with metric-based gates",
    },
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "### 2.7 Artifact Promotion Across Environments",
        "after": "```\n\n---\n\n### 2.8 Key Takeaway",
        "video_id": "cicd-artifact-promotion",
        "caption": "Artifact Promotion — Dev → Staging → Canary → Production with validation gates",
    },
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "#### Frontend (React / Next.js / Vue)",
        "after": "```\n\n**Real Example — Tracing a Commit:**",
        "video_id": "cicd-frontend-pipeline",
        "caption": "Frontend Deployment — Developer → GitHub → CI → Build → S3/CloudFront CDN",
    },
    {
        "file": "tools-interview/ci-cd-deployment/DEPLOYMENT_GUIDE.md",
        "marker": "#### Backend (Node.js / Python / Go / Java / Rust)",
        "after": "```\n\n**Real Example — Tracing a Commit (Backend):**",
        "video_id": "cicd-backend-pipeline",
        "caption": "Backend Deployment — Dockerized service pipeline from commit to Kubernetes",
    },

    # ── Kubernetes Pod Lifecycle & Monitoring ──
    {
        "file": "tools-interview/kubernetes/POD_LIFECYCLE_AND_MONITORING.md",
        "marker": "**Pod Phases (High-Level Lifecycle):**",
        "after": "           └──────────┘\n```\n\n**Pod Conditions (Detailed Status):**",
        "video_id": "k8s-pod-lifecycle",
        "caption": "Pod Lifecycle State Machine — Pending → Running → Succeeded/Failed with container states",
    },
    {
        "file": "tools-interview/kubernetes/POD_LIFECYCLE_AND_MONITORING.md",
        "marker": "**Container States (Inside Each Container):**",
        "after": "                    └──────────┘\n```\n\n**Common Waiting Reasons:**",
        "video_id": "k8s-container-states",
        "caption": "Container States — Waiting → Running → Terminated with common failure reasons",
    },
    {
        "file": "tools-interview/kubernetes/POD_LIFECYCLE_AND_MONITORING.md",
        "marker": "**Three Metrics Sources:**",
        "after": "└─────────────────────────────────────────────────────────────┘\n```\n\n**Metrics-Server (Resource Metrics API):**",
        "video_id": "k8s-monitoring-stack",
        "caption": "Kubernetes Monitoring Stack — kubelet → cAdvisor → Metrics Server → HPA/kubectl top",
    },

    # ── Computer Networks ──
    {
        "file": "cs-interview/computer-networks/INTERVIEW_QUESTIONS.md",
        "marker": "**Handshake Comparison:**",
        "after": "                      │\n```\n\n**QUIC Packet Protection — Detailed:**",
        "video_id": "net-tls-handshake",
        "caption": "TLS 1.3 Handshake — 1-RTT handshake vs TLS 1.2's 2-RTT with 0-RTT resumption",
    },
    {
        "file": "cs-interview/computer-networks/INTERVIEW_QUESTIONS.md",
        "marker": "**Full DNS Resolution Path:**",
        "after": "       └─ Opens TCP connection to 203.0.113.10:443\n```\n\n**The Problem — Intermittent Failures:**",
        "video_id": "net-dns-resolution",
        "caption": "DNS Resolution Path — Browser → Stub → Root → TLD → Authoritative → IP Address",
    },
    {
        "file": "cs-interview/computer-networks/INTERVIEW_QUESTIONS.md",
        "marker": "**HTTP/1.1 vs HTTP/2 vs HTTP/3:**",
        "after": "└─────────────────────────────────────────────────────┘\n```\n\n**The HTTP/2 HoL Blocking Problem — Deep Dive:**",
        "video_id": "net-http2-vs-quic",
        "caption": "HTTP/2 vs HTTP/3 (QUIC) — One lost packet blocks H2 entirely, QUIC isolates per-stream",
    },

    # ── Distributed Systems ──
    {
        "file": "cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md",
        "marker": "**Leader Election — Step by Step:**",
        "after": "                      │\n```\n\n**How Raft Prevents Split-Brain:**",
        "video_id": "ds-raft-leader-election",
        "caption": "Raft Leader Election — Term increment, randomized timeouts, majority vote, split-brain prevention",
    },
    {
        "file": "cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md",
        "marker": "**The Problem — Local ACID vs Distributed Atomicity:**",
        "after": "```\n\n**2-Phase Commit (2PC) — The Coordinator Problem:**",
        "video_id": "ds-twopc-vs-saga",
        "caption": "2PC vs Saga — Coordinator crash blocks 2PC; Saga's compensating actions handle failure gracefully",
    },
    {
        "file": "cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md",
        "marker": "**Consistent Hashing Ring:**",
        "after": "→ Only ~1/N of keys move (N=50 → ~2%) vs ~25% with naive hashing\n```\n\n**Virtual Nodes — The Load Balancing Fix:**",
        "video_id": "ds-consistent-hashing",
        "caption": "Consistent Hashing on a Ring — Minimal key redistribution with virtual nodes for load balancing",
    },
    {
        "file": "cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md",
        "marker": "**SWIM Main Loop (simplified pseudocode):**",
        "after": "                local.sequence_number = update.sequence_number\n```\n\n**Why Indirect Probing Is Critical:**",
        "video_id": "ds-swim-gossip",
        "caption": "SWIM Gossip Protocol — Ping → Indirect Probe → Suspect → Dead with O(log N) convergence",
    },

    # ── Software Architecture ──
    {
        "file": "cs-interview/software-architecture/INTERVIEW_QUESTIONS.md",
        "marker": "**CQRS + Event Sourcing Architecture:**",
        "after": "```\n\n**Command Model (Aggregate):**",
        "video_id": "arch-cqrs-event-sourcing",
        "caption": "CQRS + Event Sourcing — Command → Aggregate → Event Store → Projector → Materialized View",
    },
    {
        "file": "cs-interview/software-architecture/INTERVIEW_QUESTIONS.md",
        "marker": "**Strategy Comparison:**",
        "after": ")\n\n| Strategy        | Downtime | Rollback Speed | Cost       | Traffic Control | Complexity |\n|-----------------|----------|----------------|------------|-----------------|-----------|\n| Recreate        | Yes      | Slow           | Low        | None            | Minimal |\n| RollingUpdate   | No       | Medium         | Low        | At pod level    | Low |\n| Blue-Green      | No       | Instant        | High (2×)      | At service      | Medium |\n| Canary          | No       | Fast           | Medium     | % based         | High |\n| A/B Testing     | No       | Fast           | Medium     | Header based    | High |\n\n# Recreate: Kill all old, create all new (downtime!)\n# RollingUpdate: Incrementally replace pods (no downtime)\n# Blue-Green: Two full environments, switch traffic instantly\n# Canary: Gradual % traffic shift with rollback\n# A/B: Traffic routing by header/cookie (for testing features)\n```\n\n**Blue-Green Deployment:**",
        "video_id": "arch-circuit-breaker",
        "caption": "Circuit Breaker Pattern — Closed → Open → Half-Open states protecting against cascading failures",
    },
    {
        "file": "cs-interview/software-architecture/INTERVIEW_QUESTIONS.md",
        "marker": "**Event Storming — Identifying Bounded Contexts:**",
        "after": "```\n\n**Shared Data — User Profiles Across Contexts:**",
        "video_id": "arch-microservices-decomposition",
        "caption": "Microservices Decomposition — Monolith → Bounded Contexts with Anti-Corruption Layer",
    },
]


def add_video_section(file_path: Path, marker: str, after: str, video_id: str, caption: str):
    """Insert the video HTML section after the specified marker+after pattern in the file."""
    if not file_path.exists():
        print(f"  ❌ File not found: {file_path}")
        return False

    content = file_path.read_text(encoding="utf-8")

    # Check if video already exists for this file
    if video_id in content:
        print(f"  ⏭️  Video {video_id} already in {file_path.name}, skipping")
        return True

    # Find the marker position
    marker_pos = content.find(marker)
    if marker_pos == -1:
        print(f"  ❌ Marker not found in {file_path.name}: {marker[:60]}...")
        return False

    # Find the 'after' text AFTER the marker
    after_marker = content.find(after, marker_pos)
    if after_marker == -1:
        print(f"  ❌ 'After' text not found after marker in {file_path.name}")
        return False

    # Find the end of the 'after' text
    insert_pos = after_marker + len(after)

    # Build the video section
    section = f"""

### 🎬 Animated Sequence Diagram{video_html(video_id, caption)}
"""

    # Insert
    new_content = content[:insert_pos] + section + content[insert_pos:]
    file_path.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Added {video_id} to {file_path.name}")
    return True


def main():
    success = 0
    failed = 0
    skipped = 0

    for ins in INSERTIONS:
        file_path = REPO_ROOT / ins["file"]
        ok = add_video_section(
            file_path,
            ins["marker"],
            ins["after"],
            ins["video_id"],
            ins["caption"],
        )
        if ok:
            success += 1
        elif "already" in str(ok):
            skipped += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {success} added, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
