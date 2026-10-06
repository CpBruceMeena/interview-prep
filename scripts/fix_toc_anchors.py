#!/usr/bin/env python3
"""
Repair hand-written table-of-contents anchors in the docs.

Many TOCs in this repo were authored against GitHub's slugify rules, which
keep a double dash where punctuation was stripped:

    ## 1. Core Concepts & Terminology   ->  GitHub:  #1-core-concepts--terminology
                                            MkDocs:  #1-core-concepts-terminology

MkDocs renders with Python-Markdown's slugify, so those links land nowhere.
This script reads the real headings out of each file, builds the set of slugs
MkDocs will actually emit, and rewrites any in-page link that doesn't resolve
but does resolve once repeated dashes are collapsed.

Idempotent — safe to re-run. Reports anything it could not match so the
remaining cases can be fixed by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".venv", "site", "node_modules", ".git", ".pytest_cache", "__pycache__", "build"}

# Markdown inline link whose target is a pure in-page anchor: [text](#anchor)
ANCHOR_LINK_RE = re.compile(r"\]\(#([^)\s]+)\)")


def heading_slugs(text: str) -> set[str]:
    """Every anchor MkDocs will emit for this document.

    Rendered through Python-Markdown's own toc extension rather than parsed by
    hand, so fenced code, inline markup and duplicate-heading suffixes are all
    resolved exactly the way the real build resolves them.
    """
    md = markdown.Markdown(extensions=["toc", "fenced_code", "tables", "attr_list"])
    md.convert(text)

    slugs: set[str] = set()

    def walk(tokens) -> None:
        for token in tokens:
            slugs.add(token["id"])
            walk(token.get("children", []))

    walk(getattr(md, "toc_tokens", []))
    return slugs


NUMBER_PREFIX_RE = re.compile(r"^((?:[a-z]+-)?\d+)-")


def match_by_number(anchor: str, slugs: set[str]) -> str | None:
    """Resolve a reworded heading via its section number, e.g. '9-' or 'phase-3-'.

    Only returns a match when exactly one heading carries that number, so an
    ambiguous prefix is left for a human rather than silently mis-linked.
    """
    m = NUMBER_PREFIX_RE.match(anchor)
    if not m:
        return None
    prefix = m.group(1) + "-"
    candidates = [s for s in slugs if s.startswith(prefix)]
    return candidates[0] if len(candidates) == 1 else None


def fix_file(path: Path) -> tuple[int, list[str]]:
    original = path.read_text(encoding="utf-8")
    slugs = heading_slugs(original)
    if not slugs:
        return 0, []

    fixed = 0
    unresolved: list[str] = []

    def repl(match: re.Match[str]) -> str:
        nonlocal fixed
        anchor = match.group(1)
        if anchor in slugs:
            return match.group(0)
        # The dominant failure: GitHub kept a dash where '&' / ':' was stripped.
        collapsed = re.sub(r"-{2,}", "-", anchor).strip("-")
        if collapsed in slugs:
            fixed += 1
            return f"](#{collapsed})"
        # Second failure mode: the heading was reworded after the TOC was
        # written. These docs number their sections, so the numeric prefix
        # ("9-", "phase-3-") still identifies the target unambiguously.
        target = match_by_number(collapsed, slugs)
        if target:
            fixed += 1
            return f"](#{target})"
        unresolved.append(anchor)
        return match.group(0)

    updated = ANCHOR_LINK_RE.sub(repl, original)
    if fixed:
        path.write_text(updated, encoding="utf-8")
    return fixed, unresolved


def main() -> None:
    total_fixed = 0
    total_unresolved: list[tuple[Path, str]] = []

    for path in sorted(PROJECT_ROOT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        fixed, unresolved = fix_file(path)
        rel = path.relative_to(PROJECT_ROOT)
        if fixed:
            print(f"  fixed {fixed:>3}  {rel}")
            total_fixed += fixed
        total_unresolved.extend((rel, a) for a in unresolved)

    print(f"\nRepaired {total_fixed} anchor link(s).")
    if total_unresolved:
        print(f"\n{len(total_unresolved)} link(s) need a human — no heading matches:")
        for rel, anchor in total_unresolved:
            print(f"  {rel}  ->  #{anchor}")


if __name__ == "__main__":
    main()
