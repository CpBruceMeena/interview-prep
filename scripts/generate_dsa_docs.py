#!/usr/bin/env python3
"""
Generate DSA category documentation pages from Python source files.

For each category in python-dsa/, reads questions.py and creates
docs/python-dsa/<category>/index.md that embeds the full source code
in a Python code block — mirroring the LLD CODE.md pattern.
"""

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DSA_SRC_DIR = PROJECT_ROOT / "python-dsa"
DSA_DOCS_DIR = PROJECT_ROOT / "docs" / "python-dsa"

CATEGORY_TITLES = {
    "01_arrays": "Arrays",
    "02_strings": "Strings",
    "03_stacks": "Stacks",
    "04_queues": "Queues",
    "05_hashing": "Hashing",
    "06_linked_lists": "Linked Lists",
    "07_trees": "Trees",
    "08_graphs": "Graphs",
    "09_dynamic_programming": "Dynamic Programming",
    "10_sorting_searching": "Sorting & Searching",
    "11_backtracking": "Backtracking",
    "12_trie": "Trie",
    "13_heaps": "Heaps",
    "14_bit_manipulation": "Bit Manipulation",
    "15_advanced_strings": "Advanced Strings",
    "16_advanced_trees": "Advanced Trees",
    "17_sliding_window": "Sliding Window",
    "18_greedy": "Greedy",
    "19_math_number_theory": "Math & Number Theory",
    "20_design_problems": "Design Problems",
}

# Question count mapping
QUESTION_COUNTS = {
    "01_arrays": 10,
    "02_strings": 10,
    "03_stacks": 8,
    "04_queues": 6,
    "05_hashing": 8,
    "06_linked_lists": 8,
    "07_trees": 10,
    "08_graphs": 10,
    "09_dynamic_programming": 11,
    "10_sorting_searching": 12,
    "11_backtracking": 10,
    "12_trie": 7,
    "13_heaps": 9,
    "14_bit_manipulation": 10,
    "15_advanced_strings": 8,
    "16_advanced_trees": 4,
    "17_sliding_window": 8,
    "18_greedy": 9,
    "19_math_number_theory": 10,
    "20_design_problems": 6,
}


def extract_module_docstring(content: str) -> str:
    """Extract the module-level docstring from a Python file."""
    match = re.match(r'^"""(.+?)"""', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def generate_page(category: str) -> str:
    """Generate markdown content for a DSA category page."""
    src_file = DSA_SRC_DIR / category / "questions.py"
    if not src_file.exists():
        print(f"  ⚠️  Source not found: {src_file}")
        return ""

    title = CATEGORY_TITLES.get(category, category.replace("_", " ").title())
    question_count = QUESTION_COUNTS.get(category, "?")

    content = src_file.read_text(encoding="utf-8")
    module_doc = extract_module_docstring(content)

    # Extract clean first-line summary from module docstring
    doc_summary = module_doc.split('\n')[0].strip() if module_doc else ''

    md = f"""# {title}

> Python implementation — {question_count} questions covering core concepts and interview patterns.

{doc_summary}

---

```python
{content}
```

---

[← Back to DSA Overview](../index.md)
"""

    return md


def main():
    DSA_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for category in sorted(CATEGORY_TITLES.keys()):
        print(f"📄 Generating {category}...")
        md_content = generate_page(category)
        if not md_content:
            continue

        target_dir = DSA_DOCS_DIR / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "index.md"
        target_file.write_text(md_content, encoding="utf-8")
        print(f"  ✅ Created {target_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
