#!/usr/bin/env python3
"""Add animated sequence diagram video sections to remaining LLD HLD docs."""

import os
import re
import shutil

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (source_path_rel, video_id, title, description)
FILES = [
    ("low-level-design/atm-banking-system/HIGH_LEVEL_DESIGN.md",
     "atm-banking-sequence",
     "ATM Banking",
     "Insert Card \u2192 PIN \u2192 Select \u2192 Withdraw \u2192 Cash + Receipt"),
    ("low-level-design/job-scheduling-system/HIGH_LEVEL_DESIGN.md",
     "job-scheduling-sequence",
     "Job Scheduling",
     "Submit \u2192 Queue \u2192 Schedule \u2192 Execute \u2192 Complete"),
    ("low-level-design/notification-service/HIGH_LEVEL_DESIGN.md",
     "notification-service-sequence",
     "Notification Service",
     "Submit \u2192 Queue \u2192 Workers \u2192 Channel Delivery \u2192 Status"),
    ("low-level-design/search-platform/HIGH_LEVEL_DESIGN.md",
     "search-platform-sequence",
     "Search Platform",
     "Query \u2192 Parse \u2192 Index Search \u2192 Rank \u2192 Results"),
]

def make_video_block(video_id, title, description):
    return (
        f"### 🎬 Animated Sequence Diagram\n\n"
        f'<p align="center">\n'
        f'  <video controls width="900" '
        f'style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" '
        f'loop playsinline preload="metadata">\n'
        f'    <source src="../../../assets/videos/{video_id}.mp4" type="video/mp4" />\n'
        f"    Your browser does not support the video tag.\n"
        f"  </video>\n"
        f"  <br/>\n"
        f'  <em>🎬 Animated {title} Sequence \u2014 {description}. '
        f'Click \u25b6 to play/pause. Created with '
        f'<a href="https://remotion.dev">Remotion</a>.</em>\n'
        f"</p>"
    )

def add_video_to_file(filepath, video_id, title, description):
    with open(filepath, 'r') as f:
        content = f.read()

    # Check if already has the video
    if f"assets/videos/{video_id}.mp4" in content:
        print(f"  Already has video: {os.path.relpath(filepath, PROJECT_ROOT)}")
        return True

    video_block = make_video_block(video_id, title, description)
    inserted = video_block + "\n\n---\n\n"

    # Find first `## 3.` heading and insert the video before it, after the diagram
    idx = content.find("\n## 3.")
    if idx == -1:
        idx = content.find("\n## 2.5")
    if idx == -1:
        print(f"  WARNING: No ## 3 or ## 2.5 found in {filepath}")
        return False

    # Look back from the heading to find the closing ```
    before_heading = content[:idx]
    back_idx = before_heading.rfind("```")
    if back_idx == -1:
        # Just insert before the heading
        new_content = content[:idx] + "\n" + inserted + content[idx:].lstrip()
    else:
        end_of_diagram = back_idx + 3
        # Check what follows ```
        rest = before_heading[end_of_diagram:].strip()
        if rest.startswith("---") or rest.startswith("\n"):
            new_content = content[:end_of_diagram] + "\n\n" + video_block + "\n\n---\n\n" + content[idx:].lstrip()
        else:
            new_content = content[:idx] + "\n" + inserted + content[idx:].lstrip()

    with open(filepath, 'w') as f:
        f.write(new_content)

    print(f"  Updated: {os.path.relpath(filepath, PROJECT_ROOT)}")
    return True


def main():
    print("Adding video sections to remaining files...")
    for rel_path, video_id, title, description in FILES:
        src_path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.exists(src_path):
            add_video_to_file(src_path, video_id, title, description)

    print("\nDone!")


if __name__ == "__main__":
    main()
