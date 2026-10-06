# Contributing

Thanks for wanting to improve this. The content is the point — a correction to
a wrong answer is worth more than a new section.

## Setup

```bash
git clone https://github.com/CpBruceMeena/interview-prep.git
cd interview-prep

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt

mkdocs serve          # http://127.0.0.1:8000
```

Optionally install the hook that keeps commits off `main`:

```bash
cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## How the repo maps onto the site

Content lives at the **top level**, not under `docs/`. Most entries in `docs/`
are symlinks pointing back out:

```
docs/cs-interview        ->  ../cs-interview
docs/ai-engineering      ->  ../ai-engineering
docs/python-low-level-design -> ../python-low-level-design
...
```

So one markdown file serves both GitHub browsing and the published site, and
you edit it in exactly one place. Only these under `docs/` are real files:

| Path | What it is |
|---|---|
| `docs/index.md` | The site homepage (hand-written HTML + markdown) |
| `docs/404.html` | Custom 404, redirects stale `.md` URLs |
| `docs/assets/` | CSS, JS, and the rendered video/GIF animations |
| `docs/overrides/` | Theme overrides — OG tags, fonts, feedback widget |
| `docs/python-dsa/` | **Generated** — do not edit by hand (see below) |

Navigation is hand-maintained in `mkdocs.yml` under `nav:`. A new page is not
on the site until it has a `nav:` entry.

## Adding content

### A new topic page

1. Add the `.md` file under the relevant top-level directory.
2. Add a `nav:` entry for it in `mkdocs.yml`.
3. Run `mkdocs serve` and check it renders.

### A new LLD project

Each project directory carries a consistent set of pages:

```
python-low-level-design/<project>/
├── THOUGHT_PROCESS.md      how you'd reason about it in an interview
├── CODE.md                 the implementation
├── HIGH_LEVEL_DESIGN.md    architecture, scaling, trade-offs
├── INTERVIEW_QUESTIONS.md  follow-up questions with answers
├── DB_SCHEMA.md            optional — only where persistence matters
└── <project>.py            the runnable source
```

Add all of them to `mkdocs.yml` as a nested nav section.

### DSA questions

Source of truth is `python-dsa/<category>/questions.py`. The site pages are
generated from it:

```bash
python3 scripts/generate_dsa_docs.py
```

Edit the Python, regenerate, commit both. Never hand-edit
`docs/python-dsa/<category>/index.md` — it will be overwritten.

## Before you open a PR

```bash
mkdocs build --strict
```

This is the same gate CI runs. It fails on broken nav entries, dead internal
links and missing files.

If you add a table of contents, verify the anchors:

```bash
python3 scripts/fix_toc_anchors.py
```

MkDocs and GitHub slugify headings differently — GitHub keeps a double dash
where punctuation was stripped (`#tasks--futures`), MkDocs collapses it
(`#tasks-futures`). This script rewrites links to whatever the build actually
emits, and reports anything it can't resolve rather than guessing.

## Other tooling

| Script | Purpose |
|---|---|
| `scripts/generate_dsa_docs.py` | Rebuild DSA pages from `questions.py` |
| `scripts/generate_lld_code_pages.py` | Embed `.py` source into `CODE.md` |
| `scripts/fix_toc_anchors.py` | Repair in-page TOC anchors |
| `scripts/export_diagrams.sh` | Export `.drawio` to SVG/PNG (needs draw.io desktop) |
| `remotion-lld/` | Renders the animated diagrams in `docs/assets/videos/` |

## Pull requests

- Branch off `main`; don't commit to it directly.
- Keep one topic per PR.
- Say what you changed and why. For a corrected answer, a sentence on what was
  wrong is enough.

## Content guidelines

These notes target Senior/Staff/Principal backend interviews, so:

- Prefer depth over breadth. A worked trade-off beats a bullet list.
- Code should run. If it's illustrative pseudocode, say so.
- Name real numbers where they matter (latencies, limits, complexities).
- Cite the primary source for anything surprising.

## License

By contributing you agree your work is published under this repository's
[MIT License](LICENSE).
