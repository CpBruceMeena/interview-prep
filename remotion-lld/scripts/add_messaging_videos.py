#!/usr/bin/env python3
"""Insert animated sequence diagram videos into AWS messaging interview markdown files."""

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
    # ── SQS Long Polling (section 2) ──
    (
        "aws-interview/messaging/INTERVIEW_QUESTIONS.md",
        "  Minimum: waitTimeSeconds = 1 (long polling starts at 1s)",
        "aws-sqs-long-polling",
        "Animated SQS Short Polling vs Long Polling — wasteful empty responses vs batched wait with 90% cost reduction",
    ),
    # ── SNS Fan-Out (section 4) ──
    (
        "aws-interview/messaging/INTERVIEW_QUESTIONS.md",
        "- SNS message is delivered ONCE to each subscription",
        "aws-sns-fanout",
        "Animated SNS → SQS Fan-Out Pattern — single topic fans out to multiple queues with independent retry and failure isolation",
    ),
    # ── Kinesis Shard Scaling (section 7) ──
    (
        "aws-interview/messaging/INTERVIEW_QUESTIONS.md",
        "Total shards per stream: default 500 (soft limit)",
        "aws-kinesis-shard-scaling",
        "Animated Kinesis Shard Allocation & Resharding — partition key hashing, hot key throttling, and split to redistribute load",
    ),
    # ── EventBridge Routing (section 5) ──
    (
        "aws-interview/messaging/INTERVIEW_QUESTIONS.md",
        "Rule example:",
        "aws-eventbridge-routing",
        "Animated EventBridge Event Bus & Routing — content-based rules filter events and route to Lambda, SQS, and Step Functions",
    ),
]


def find_section_boundary(content: str, marker: str) -> int:
    """Find a line containing the marker and return the position after its code block."""
    lines = content.split("\n")
    marker_line = None

    for i, line in enumerate(lines):
        if marker in line:
            marker_line = i
            break

    if marker_line is None:
        return -1

    # Look for the NEXT ``` after the marker to close the code block
    for j in range(marker_line, len(lines)):
        line = lines[j].strip()
        if line == "```":
            return len("\n".join(lines[: j + 1])) + 1  # +1 for the newline

    # Fallback
    return len("\n".join(lines[: marker_line + 1])) + 1


def insert_video(file_path: str, after_marker: str, video_id: str, caption: str) -> bool:
    """Insert video section into the markdown file after the given marker."""
    full_path = PROJECT_ROOT / file_path

    if not full_path.exists():
        print(f"  ❌ File not found: {file_path}")
        return False

    content = full_path.read_text()

    # Check if already inserted
    if video_id in content:
        print(f"  ⏭️  Already inserted in {file_path}")
        return True

    # Find the insertion position
    insert_pos = find_section_boundary(content, after_marker)

    if insert_pos < 0:
        print(f"  ⚠️  Marker not found in {file_path}: '{after_marker}'")
        pos = content.find(after_marker)
        if pos < 0:
            print(f"  ❌ Could not find fallback marker either")
            return False
        next_newline = content.find("\n", pos)
        if next_newline < 0:
            insert_pos = len(content)
        else:
            insert_pos = next_newline + 1

    video_section = VIDEO_TEMPLATE.format(video_id=video_id, caption=caption)
    new_content = content[:insert_pos] + video_section + content[insert_pos:]
    full_path.write_text(new_content)
    print(f"  ✅ Inserted {video_id} into {file_path}")
    return True


def main():
    print("Adding AWS messaging animated sequence diagram videos...\n")

    success = 0
    for file_path, marker, video_id, caption in INSERTIONS:
        print(f"  Processing {file_path} (marker: '{marker[:40]}...')...")
        if insert_video(file_path, marker, video_id, caption):
            success += 1

    print(f"\nDone! {success}/{len(INSERTIONS)} videos inserted.")


if __name__ == "__main__":
    main()
