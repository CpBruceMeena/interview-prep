#!/usr/bin/env python3
"""Insert animated sequence diagram videos into AWS security interview markdown file."""

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

INSERTIONS = [
    # ── IAM Permission Boundary (section 1) ──
    (
        "aws-interview/security/INTERVIEW_QUESTIONS.md",
        "AuthZ for Applications",
        "aws-iam-permission-boundary",
        "Animated IAM Permission Boundary Flow — policy evaluation chain: DENY always wins, boundaries cap max permissions",
        "---\n\n## 4. AWS Cognito: AuthN",
    ),
    # ── KMS Envelope Encryption (section 3) ──
    (
        "aws-interview/security/INTERVIEW_QUESTIONS.md",
        "# Encrypt S3 object:",
        "aws-kms-envelope-encryption",
        "Animated KMS Envelope Encryption — CMK encrypts DEK, DEK encrypts data, encrypted DEK stored alongside ciphertext",
        "---\n\n**Key Rotation:**",
    ),
    # ── GuardDuty Multi-Account (section 7) ──
    (
        "aws-interview/security/INTERVIEW_QUESTIONS.md",
        "# Centralized view:",
        "aws-guardduty-multi-account",
        "Animated GuardDuty Multi-Account Threat Detection — 50 member accounts report to delegated admin with auto-remediation",
        "---\n\n**GuardDuty Threat Detection:**",
    ),
    # ── Cognito Auth Flow (section 4) ──
    (
        "aws-interview/security/INTERVIEW_QUESTIONS.md",
        "# Typical flow:",
        "aws-cognito-auth-flow",
        "Animated Cognito Authentication & Authorization Flow — User Pool → JWT → Identity Pool → AWS credentials → Resources",
        "---\n\n**Multi-Tenant Configuration:**",
    ),
]


def insert_video(file_path: str, marker: str, video_id: str, caption: str, section_end_marker: str) -> bool:
    full_path = PROJECT_ROOT / file_path
    if not full_path.exists():
        print(f"  ❌ File not found: {file_path}")
        return False

    content = full_path.read_text()
    if video_id in content:
        print(f"  ⏭️  Already inserted: {video_id}")
        return True

    # Find the marker
    pos = content.find(marker)
    if pos < 0:
        # Try exact line match by scanning through lines
        lines = content.split("\n")
        found = -1
        for i, line in enumerate(lines):
            if marker in line:
                found = i
                break
        if found < 0:
            print(f"  ❌ Marker not found: '{marker[:40]}...'")
            return False
        # Find the closing ``` after this line
        for j in range(found, len(lines)):
            if lines[j].strip() == "```":
                insert_pos = len("\n".join(lines[: j + 1])) + 1
                break
        else:
            insert_pos = len(content)
    else:
        # Find the next section boundary
        section_pos = content.find(section_end_marker, pos)
        if section_pos >= 0:
            # Find the last ``` before section_end_marker after pos
            before_section = content[pos:section_pos]
            last_fence = before_section.rfind("\n```\n")
            if last_fence >= 0:
                insert_pos = pos + last_fence + 5  # after "\n```\n"
            else:
                insert_pos = section_pos
        else:
            insert_pos = pos + len(marker) + 1

    video_section = VIDEO_TEMPLATE.format(video_id=video_id, caption=caption)
    new_content = content[:insert_pos] + video_section + content[insert_pos:]
    full_path.write_text(new_content)
    print(f"  ✅ Inserted {video_id}")
    return True


def main():
    print("Adding AWS security animated sequence diagram videos...\n")
    success = 0
    for file_path, marker, video_id, caption, section_end in INSERTIONS:
        print(f"  Processing marker: '{marker[:40]}...'")
        if insert_video(file_path, marker, video_id, caption, section_end):
            success += 1
    print(f"\nDone! {success}/{len(INSERTIONS)} videos inserted.")


if __name__ == "__main__":
    main()
