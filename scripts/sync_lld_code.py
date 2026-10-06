#!/usr/bin/env python3
"""
Keep the source code embedded in each LLD CODE.md identical to the real file.

CODE.md pages used to carry a hand-pasted copy of the implementation, and the
copies drifted: some showed half the file, some an older version, some none.
Each CODE.md now marks where a source file is embedded:

    <!-- source: parking_lot.py -->
    ```python
    ...replaced on every run...
    ```
    <!-- /source -->

The path is relative to the CODE.md's directory. Everything between the two
markers is regenerated from the file; everything outside them is hand-written
and left alone.

    python3 scripts/sync_lld_code.py           # rewrite embeds in place
    python3 scripts/sync_lld_code.py --check   # exit 1 if any embed is stale (CI)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LLD_DIRS = (
    "python-low-level-design",
    "java-low-level-design",
    "golang-low-level-design",
)

FENCE_LANG = {".py": "python", ".java": "java", ".go": "go"}

BLOCK_RE = re.compile(
    r"(<!-- source: (?P<path>[^\s]+) -->\n)(?P<body>.*?)(<!-- /source -->)",
    re.S,
)


def render(code_md: Path, rel: str) -> str:
    src = code_md.parent / rel
    if not src.exists():
        raise FileNotFoundError(f"{code_md}: embedded source {rel} does not exist")
    text = src.read_text(encoding="utf-8").rstrip("\n")
    # A fence longer than any backtick run in the file, so docstrings that
    # contain ``` can't close the block early.
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{FENCE_LANG.get(src.suffix, '')}\n{text}\n{fence}\n"


def sync(code_md: Path) -> tuple[str, str, list[str]]:
    original = code_md.read_text(encoding="utf-8")
    embedded: list[str] = []

    def replace(match: re.Match) -> str:
        rel = match.group("path")
        embedded.append(rel)
        return match.group(1) + render(code_md, rel) + match.group(4)

    return original, BLOCK_RE.sub(replace, original), embedded


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale, missing = [], []

    for top in LLD_DIRS:
        for project in sorted((PROJECT_ROOT / top).iterdir()):
            code_md = project / "CODE.md"
            if not project.is_dir() or not code_md.exists():
                continue
            original, updated, embedded = sync(code_md)

            sources = sorted(
                p.name for p in project.iterdir()
                if p.suffix in FENCE_LANG
                and not p.name.startswith("test_")
                and not p.name.endswith(("_test.go", "Test.java"))
            )
            for name in sources:
                if name not in embedded:
                    missing.append(f"{code_md.relative_to(PROJECT_ROOT)}: {name} is not embedded")

            if updated != original:
                stale.append(str(code_md.relative_to(PROJECT_ROOT)))
                if not check:
                    code_md.write_text(updated, encoding="utf-8")

    for line in missing:
        print(f"missing  {line}")
    for path in stale:
        print(f"{'stale   ' if check else 'updated '} {path}")

    if check and (stale or missing):
        print("\nRun: python3 scripts/sync_lld_code.py")
        return 1
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
