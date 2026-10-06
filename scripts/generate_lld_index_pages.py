#!/usr/bin/env python3
"""
Generate a landing page for every LLD project.

Each project directory used to carry an index.md containing nothing but

    --8<-- "INTERVIEW_QUESTIONS.md"

which rendered a second, full copy of the questions page at the project's
own URL. Two pages with identical content competed in site search and in
search engines, and the project root — the URL the README links to — had no
page of its own describing the project.

This writes a real index page instead: what the project is, and a table
routing to the pages that exist in that directory. Registered in mkdocs.yml
as the first entry of each project's nav section, so (with the theme's
navigation.indexes feature) it becomes the section landing page.

Titles come from mkdocs.yml so the page heading and the sidebar agree.

    python3 scripts/generate_lld_index_pages.py
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LLD_DIRS = (
    "python-low-level-design",
    "java-low-level-design",
    "golang-low-level-design",
)

LANGUAGE = {
    "python-low-level-design": "Python",
    "java-low-level-design": "Java",
    "golang-low-level-design": "Go",
}

# Ordered as a reader should walk them: reason about it, then read the code,
# then the production view, then test yourself.
PAGES = [
    ("THOUGHT_PROCESS.md", "Thought Process", "How to reason about this design in an interview"),
    ("CODE.md", "Implementation", "Full annotated source with the patterns called out"),
    ("DB_SCHEMA.md", "Database Schema", "Tables, indexes and the constraints that matter"),
    ("HIGH_LEVEL_DESIGN.md", "High-Level Design", "Architecture, scaling and failure modes"),
    ("INTERVIEW_QUESTIONS.md", "Interview Questions", "Follow-up questions with worked answers"),
]

# "    - Parking Lot:" — a project section header inside the nav block.
NAV_SECTION_RE = re.compile(r"^    - (.+):$")
NAV_ENTRY_RE = re.compile(r"^      - [^:]+: ([\w\-/]+)/([\w\-]+)/([\w.]+\.md)$")


def nav_titles() -> dict[str, str]:
    """Map 'python-low-level-design/parking-lot' -> 'Parking Lot' from the nav."""
    text = (PROJECT_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    titles: dict[str, str] = {}
    current: str | None = None
    for line in text[text.index("\nnav:"):].split("\n"):
        section = NAV_SECTION_RE.match(line)
        if section:
            current = section.group(1).strip()
            continue
        entry = NAV_ENTRY_RE.match(line)
        if entry and current:
            top, project, _ = entry.groups()
            if top in LLD_DIRS:
                titles.setdefault(f"{top}/{project}", current)
    return titles


def summary_for(project_dir: Path) -> str:
    """Pull the one-line framing from whichever page states it most plainly."""
    for name in ("HIGH_LEVEL_DESIGN.md", "THOUGHT_PROCESS.md"):
        path = project_dir / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").split("\n")[:12]:
            line = line.strip()
            if not line.startswith(">"):
                continue
            line = line.lstrip("> ").strip()
            # "**Focus:** Multi-floor parking, spot allocation, ..."
            match = re.match(r"\*\*Focus:\*\*\s*(.+)", line)
            if match:
                return match.group(1).strip()
    return ""


def render(key: str, title: str, project_dir: Path) -> str:
    top = key.split("/")[0]
    language = LANGUAGE[top]
    summary = summary_for(project_dir)

    lines = [f"# {title}", ""]
    if summary:
        lines += [f"> {summary}", ""]
    lines += [
        f"A low-level design worked end to end in {language} — from the reasoning "
        "you'd show an interviewer through to the production architecture.",
        "",
        "---",
        "",
        "| Page | What's in it |",
        "|------|--------------|",
    ]

    for filename, label, blurb in PAGES:
        if (project_dir / filename).exists():
            lines.append(f"| **[{label}]({filename})** | {blurb} |")

    source_files = sorted(
        p.name for p in project_dir.iterdir()
        if p.suffix in {".py", ".java", ".go"} and not p.name.startswith("test_")
    )
    if source_files:
        joined = ", ".join(f"`{name}`" for name in source_files)
        lines += ["", "---", "", f"**Runnable source:** {joined}"]

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    titles = nav_titles()
    written = 0
    skipped: list[str] = []

    for top in LLD_DIRS:
        for project_dir in sorted((PROJECT_ROOT / top).iterdir()):
            if not project_dir.is_dir():
                continue
            key = f"{top}/{project_dir.name}"
            title = titles.get(key)
            if not title:
                skipped.append(key)
                continue
            (project_dir / "index.md").write_text(
                render(key, title, project_dir), encoding="utf-8"
            )
            print(f"  ✅ {key}/index.md  ({title})")
            written += 1

    print(f"\nWrote {written} landing page(s).")
    if skipped:
        print("\nNo nav section found — add one in mkdocs.yml first:")
        for key in skipped:
            print(f"  {key}")


if __name__ == "__main__":
    main()
