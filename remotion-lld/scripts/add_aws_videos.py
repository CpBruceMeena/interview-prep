#!/usr/bin/env python3
"""Insert animated sequence diagram videos into AWS interview markdown files."""

import os
from pathlib import Path

PROJECT_ROOT = Path("/Users/cpbrucemeena/Documents/Projects/interview-prep")

VIDEO_TEMPLATE = """\n### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/{video_id}.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 {caption} — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---\n"""

# Define insertions: (file_path, marker_text_after_which_to_insert, video_id, caption)
INSERTIONS = [
    # ── VPC Peering vs Transit Gateway ──
    (
        "aws-interview/networking/INTERVIEW_QUESTIONS.md",
        "- Supports: VPC, VPN, Direct Connect, Transit Gateway peering",
        "aws-vpc-peering-vs-tgw",
        "Animated VPC Peering vs Transit Gateway — 1:1 connection vs hub-and-spoke with transitive routing comparison",
    ),
    # ── Route53 DNS Routing ──
    (
        "aws-interview/networking/INTERVIEW_QUESTIONS.md",
        "# Route53 hosted zone: saas.example.com",
        "aws-route53-dns-routing",
        "Animated Route53 Multi-Region DNS Routing — latency-based routing with health check failover across 3 regions",
    ),
    # ── S3 Consistency ──
    (
        "aws-interview/storage-database/INTERVIEW_QUESTIONS.md",
        "# Strong read-after-write consistency for ALL operations:",
        "aws-s3-consistency",
        "Animated S3 Strong Consistency Model — read-after-write, strong deletes, and LIST eventual consistency",
    ),
    # ── Lambda Lifecycle ──
    (
        "aws-interview/compute/INTERVIEW_QUESTIONS.md",
        "**Lambda Execution Environment Lifecycle:**",
        "aws-lambda-lifecycle",
        "Animated Lambda Cold Start & Execution Lifecycle — download → Firecracker µVM → runtime init → handler → warm reuse",
    ),
]


def find_section_boundary(content: str, marker: str) -> int:
    """Find a line containing the marker and return the position after its YAML block."""
    lines = content.split("\n")
    marker_line = None

    for i, line in enumerate(lines):
        if marker in line:
            marker_line = i
            break

    if marker_line is None:
        return -1

    # Find the closing ``` of the YAML code block
    # The marker should be inside a YAML block, so we look for the next ``` after it
    for j in range(marker_line, len(lines)):
        line = lines[j].strip()
        if line == "```":
            # Found closing of YAML block — insert after this line
            return len("\n".join(lines[: j + 1])) + 1  # +1 for the newline

    # Fallback: return after the marker line
    return len("\n".join(lines[: marker_line + 1]))


def insert_video(file_path: str, after_marker: str, video_id: str, caption: str) -> bool:
    """Insert video section into the markdown file after the given marker."""
    full_path = PROJECT_ROOT / file_path

    if not full_path.exists():
        print(f"  ❌ File not found: {file_path}")
        return False

    content = full_path.read_text()

    # Find the insertion position
    insert_pos = find_section_boundary(content, after_marker)

    if insert_pos < 0:
        print(f"  ⚠️  Marker not found in {file_path}: '{after_marker}'")
        # Try fallback: find the marker directly
        pos = content.find(after_marker)
        if pos < 0:
            print(f"  ❌ Could not find fallback marker either")
            return False
        # Insert after the marker line (go to next line)
        next_newline = content.find("\n", pos)
        if next_newline < 0:
            insert_pos = len(content)
        else:
            insert_pos = next_newline + 1

    video_section = VIDEO_TEMPLATE.format(video_id=video_id, caption=caption)

    # Check if already inserted
    if video_id in content:
        print(f"  ⏭️  Already inserted in {file_path}")
        return True

    new_content = content[:insert_pos] + video_section + content[insert_pos:]
    full_path.write_text(new_content)
    print(f"  ✅ Inserted {video_id} into {file_path}")
    return True


def main():
    print("Adding AWS animated sequence diagram videos...\n")

    success = 0
    for file_path, marker, video_id, caption in INSERTIONS:
        print(f"  Processing {file_path}...")
        if insert_video(file_path, marker, video_id, caption):
            success += 1

    print(f"\nDone! {success}/{len(INSERTIONS)} videos inserted.")


if __name__ == "__main__":
    main()
