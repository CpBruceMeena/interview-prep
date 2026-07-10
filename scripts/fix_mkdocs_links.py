#!/usr/bin/env python3
"""Fix MkDocs relative links that are missing .md extension in page content.

This script finds and fixes:
1. Links like [text](path/to/file/) -> [text](path/to/file.md) in docs/*.md
2. Links like [text](implementation/) -> [text](implementation/index.md) where index.md exists
"""

import re
import os
import sys

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")


def fix_file(filepath: str) -> int:
    """Fix relative links in a markdown file. Returns number of fixes."""
    with open(filepath, "r") as f:
        content = f.read()

    original = content

    # Pattern: [text](path/to/dir-like/) - links ending in / that point to a .md file
    # We need to check if the target path resolves to an existing .md file

    def resolve_link(match):
        link_text = match.group(1)
        link_url = match.group(2)

        # Skip absolute URLs, anchor-only links, and mailto links
        if link_url.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)

        # Skip links that already have .md extension
        if link_url.endswith(".md"):
            return match.group(0)

        # Handle directory-style links (ending with /)
        if link_url.endswith("/"):
            url_no_slash = link_url.rstrip("/")
            # Check if the corresponding .md file exists
            full_path = os.path.join(os.path.dirname(filepath), url_no_slash + ".md")
            if os.path.exists(full_path):
                return f"[{link_text}]({url_no_slash}.md)"
            # Check if index.md exists
            index_path = os.path.join(os.path.dirname(filepath), url_no_slash, "index.md")
            if os.path.exists(index_path):
                return f"[{link_text}]({url_no_slash}/index.md)"
            return match.group(0)

        # Handle links without extension or trailing slash (e.g., path/to/file)
        # Check if path/to/file.md exists
        full_path = os.path.join(os.path.dirname(filepath), link_url + ".md")
        if os.path.exists(full_path):
            return f"[{link_text}]({link_url}.md)"

        return match.group(0)

    # Find all markdown links [text](url)
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    content = link_pattern.sub(resolve_link, content)

    if content != original:
        with open(filepath, "w") as f:
            f.write(content)
        return 1
    return 0


def main():
    fixed_count = 0

    # Walk through all markdown files in docs/
    for root, dirs, files in os.walk(DOCS_DIR):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md"):
                filepath = os.path.join(root, fname)
                if fix_file(filepath):
                    rel_path = os.path.relpath(filepath, DOCS_DIR)
                    print(f"Fixed: {rel_path}")
                    fixed_count += 1

    print(f"\nTotal files modified: {fixed_count}")
    return 0 if fixed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
