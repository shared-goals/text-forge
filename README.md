# text-forge

Text Forge is a toolkit for working with long-form Markdown as a living text: a website, a book, an editable workspace, an AI-readable corpus, and a source model for agent memory and future meaning graphs.

It grew out of the `whattodo` / WTD approach — **Жизнь как Текст** (“Life as Text”): important thinking should remain plain, readable, public, versioned, and useful to both humans and agents. Markdown stays the roots. Everything else is a projection.

[![PyPI](https://img.shields.io/pypi/v/sg-text-forge)](https://pypi.org/project/sg-text-forge/)
[![Python](https://img.shields.io/pypi/pyversions/sg-text-forge)](https://pypi.org/project/sg-text-forge/)
[![License](https://img.shields.io/github/license/shared-goals/text-forge)](LICENSE)

## The idea

A meaningful text is not only a page to publish. It is also:

- a book to read offline;
- a website with stable public addresses;
- an editor for continuous work;
- a corpus for search, review, and AI feedback;
- a memory substrate for agents;
- a future graph of sections, concepts, references, aliases, and changes.

Text Forge keeps these roles connected through one source of truth:

```text
plain Markdown + MkDocs navigation + Git history
        ↓
Text Forge source model
        ↓
website / EPUB / editor / AI-readable export
        ↓
inventory → memory projections → meaning graph projections
```

The key principle is: **do not pollute the source text with infrastructure concerns**. Keep Markdown readable. Put publication, memory, graph, and agent mechanics into generated layers.

## Жизнь как Текст

The WTD approach treats life, work, product thinking, references, doubts, and decisions as a text that can be revised, linked, published, questioned, and remembered.

That creates a different kind of tooling requirement:

- chapters can be published or still in draft, but both may be useful for feedback;
- explicit anchors are public addresses for ideas, not just HTML implementation details;
- source history matters because meanings evolve;
- agents should cite sections, not vaguely “remember something”; 
- future tools should map meanings without forcing technical IDs into the Markdown.

Text Forge is the infrastructure layer for that workflow.

## What Text Forge does today

### Publish a MkDocs text as a website

Text Forge extends MkDocs Material with:

- theme overrides;
- custom partials and assets;
- source links;
- editor/download/header integrations;
- custom content blocks used by long-form text projects.

### Build an EPUB

The same source can become an EPUB:

- chapters are combined from `mkdocs.yml` navigation;
- PyMdown syntax is normalized for Pandoc;
- assets are bundled;
- metadata can include Git-derived dates/versioning;
- output is compatible with normal e-readers.

### Edit text in the browser

The live editor supports:

- browser-based Markdown editing;
- real-time preview through Pyodide + PyMdown Extensions;
- local save during `mkdocs serve`;
- GitHub API commits in production;
- split-pane interface with synchronized scrolling;
- Russian translations.

### Export for AI and agents

Text Forge can generate AI-readable material:

- combined Markdown export;
- normalized anchors and links;
- privacy-first behavior: AI-readable export is opt-in.

### Generate a source inventory

The next layer is a deterministic inventory of the text:

```text
Markdown files + mkdocs.yml + Git metadata
        ↓
chapters, sections, anchors, line ranges, URLs, draft/published status
```

This inventory is the common input for downstream tools. They should not reimplement MkDocs parsing.

Current building block:

```text
scripts/wtd-inventory.py
```

Despite the name, it is the first implementation of a broader pattern: derive a stable source model from a MkDocs text project.

### Project text into agent memory

Text Forge also includes a public Hindsight adapter:

```text
scripts/hindsight-ingest.py
```

It consumes inventory JSON and writes citable documents into Hindsight. This makes a text available to agents as structured memory while preserving public URLs, GitHub source links, chapter/section identity, and tags.

The public adapter is intentionally infrastructure-neutral. Private paths, hostnames, bank names, backups, and operational rituals belong in local Hermes skills or wrappers.

See:

- [`docs/hindsight-memory.md`](docs/hindsight-memory.md) — reference for the Hindsight projection shape;
- [`docs/hindsight-memory/SKILL.md`](docs/hindsight-memory/SKILL.md) — example Hermes skill workflow using Text Forge scripts.

## The architecture

Text Forge is not meant to become a monolith. It should be the reusable source-model layer.

```text
                  ┌────────────────────┐
                  │ plain Markdown text │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ MkDocs + Git roots │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ Text Forge model   │
                  └─────────┬──────────┘
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
┌───────▼────────┐  ┌───────▼────────┐  ┌────────▼─────────┐
│ Website / EPUB │  │ Agent memory   │  │ Meaning graph    │
│ Editor / AI md │  │ Hindsight etc. │  │ future layer     │
└────────────────┘  └────────────────┘  └──────────────────┘
```

For WTD specifically:

```text
WTD roots
  = source Markdown, anchors, references, Git history

WTD Hindsight corpus
  = agent-memory projection of those roots

WTD graph
  = future meaning representation: concepts, mappings, aliases, splits, merges, evolution
```

The graph can eventually preserve anchor renames and section mappings without adding hidden metadata comments to the Markdown.

## Drafts and public addresses

Text Forge distinguishes:

- **published chapters** — included in `mkdocs.yml` navigation and released in the table of contents;
- **draft chapters** — Markdown files under `docs_dir` but not in navigation yet.

Draft does not mean useless or private. A draft page may still have a stable preview/public URL and can be used for feedback, review, and memory. It is simply not part of the released table of contents.

Explicit heading anchors are treated as public addresses for ideas:

```markdown
## Form of the Book {#book_form}
```

A chapter with no anchored headings still has a chapter-level address:

```text
https://example.org/chapter-slug/
```

This is enough for the source. More complex identity mapping belongs in a generated graph layer, not in the Markdown.

## Installation

### Python package

```bash
pip install sg-text-forge
```

### GitHub Action

```yaml
# .github/workflows/publish.yml
- uses: shared-goals/text-forge@main
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
```

## Quick start

Add the plugin to `mkdocs.yml`:

```yaml
plugins:
  - text-forge:
      editor_enabled: true
      nobr_emoticons_enabled: true
      downloads_enabled: false
      ai_readable_enabled: false
      epub_title: "My Book"
      epub_author: "Author Name"
```

Build EPUB:

```bash
text-forge epub --config=mkdocs.yml --build-dir=build
```

Build complete site:

```bash
text-forge build --config=mkdocs.yml --build-dir=build
```

Generate inventory:

```bash
python scripts/wtd-inventory.py --config mkdocs.yml --include-drafts --format json
```

Dry-run a Hindsight memory projection:

```bash
python scripts/wtd-inventory.py --config mkdocs.yml --include-drafts --format json \
  | python scripts/hindsight-ingest.py \
      --api-url http://localhost:8889 \
      --bank hermes \
      --strategy wtd-primary \
      --dry-run
```

## CLI commands

### `text-forge epub`

Build EPUB from a MkDocs project.

```bash
text-forge epub [OPTIONS]

Options:
  --config PATH      Path to mkdocs.yml (default: mkdocs.yml)
  --build-dir PATH   Build output directory (default: build)
```

### `text-forge build`

Build complete site: EPUB + MkDocs site.

```bash
text-forge build [OPTIONS]

Options:
  --config PATH              Path to mkdocs.yml (default: mkdocs.yml)
  --build-dir PATH           Build directory (default: build)
  --site-dir PATH            MkDocs output (default: from mkdocs.yml)
  --strict/--no-strict       Fail on warnings (default: true)
  --copy-artifacts/--no-copy-artifacts
                             Copy EPUB to site root (default: true)
  --create-404-redirect/--no-create-404-redirect
                             Create 404.html for /ru/* redirects (default: true)
```

## Plugin configuration

```yaml
plugins:
  - text-forge:
      # Editor
      editor_enabled: true
      nobr_emoticons_enabled: true

      # Downloads and AI-readable export
      downloads_enabled: false
      ai_readable_enabled: false

      # EPUB metadata
      epub_title: ""
      epub_subtitle: ""
      epub_author: ""
      epub_identifier: ""
      epub_publisher: ""
      epub_rights: ""

      # UI labels
      source_file_published_title: "Published"

      # Theme integration
      auto_configure_theme: true
```

## Repository map

```text
text-forge/
├── text_forge/                    # Python package
│   ├── plugin.py                  # MkDocs plugin
│   ├── build.py                   # Build pipeline
│   ├── cli.py                     # CLI commands
│   └── obsidian/                  # Obsidian-related templates/helpers
├── scripts/
│   ├── mkdocs-combine.py          # Chapter combiner / AI-readable export helper
│   ├── mkdocs_common.py           # Shared MkDocs helpers for scripts
│   ├── wtd-inventory.py           # Source inventory generator
│   ├── hindsight-ingest.py        # Public Hindsight adapter
│   ├── pymdown-pandoc.lua         # Pandoc Lua filter
│   └── process-epub-meta.py       # EPUB metadata processor
├── docs/
│   └── hindsight-memory/          # Example Hermes skill for memory projection
├── mkdocs/
│   ├── overrides/                 # Material theme overrides
│   └── hooks/                     # MkDocs hooks
├── epub/                          # EPUB templates and styles
└── tests/                         # Pytest tests
```

## Example projects

- [whattodo](https://github.com/bongiozzo/whattodo) — the WTD / “Жизнь как Текст” source project;
- [Live demo](https://text.sharedgoals.ru/) — published WTD site.

## Development

```bash
git clone https://github.com/shared-goals/text-forge.git
cd text-forge
make install
make test
```

Useful commands:

```bash
make format      # Format code with ruff
make lint        # Run linters
make test        # Run tests with pytest
make check-i18n  # Validate translation keys
make release     # Interactive release: bump version, tag, push
```

## Requirements

- Python ≥ 3.11
- Pandoc, for EPUB generation
- MkDocs Material
- Git, for version/date/source metadata

## License

MIT License — see [LICENSE](LICENSE).

## Contributing

Contributions welcome. Please open issues or pull requests at [github.com/shared-goals/text-forge](https://github.com/shared-goals/text-forge).
