"""Fix "Class Diagram" alt text in drawio image references.

The mkdocs-drawio plugin interprets the alt text as a page name to find
inside the drawio file. Since our drawio files don't have a page named
"Class Diagram", this generates warnings. Removing the alt text fixes it.
"""

import glob
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_PATTERN = "![Class Diagram]("
REPLACEMENT = "![]("

# Fix both source and docs mirror
dirs = [
    os.path.join(PROJECT_ROOT, "low-level-design"),
    os.path.join(PROJECT_ROOT, "docs", "low-level-design"),
]

fixed_count = 0
for base_dir in dirs:
    pattern = os.path.join(base_dir, "*", "THOUGHT_PROCESS.md")
    for filepath in glob.glob(pattern):
        with open(filepath, "r") as f:
            content = f.read()

        if TARGET_PATTERN in content:
            new_content = content.replace(TARGET_PATTERN, REPLACEMENT)
            with open(filepath, "w") as f:
                f.write(new_content)
            print(f"  FIXED: {filepath}")
            fixed_count += 1
        else:
            print(f"  SKIP: {filepath} (no match)")

print(f"\nFixed {fixed_count} files.")
