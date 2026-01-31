# text-forge

MkDocs plugin and build pipeline for text-based websites with EPUB generation, live editor, and GitHub integration.

[![PyPI](https://img.shields.io/pypi/v/sg-text-forge)](https://pypi.org/project/sg-text-forge/)
[![Python](https://img.shields.io/pypi/pyversions/sg-text-forge)](https://pypi.org/project/sg-text-forge/)
[![License](https://img.shields.io/github/license/shared-goals/text-forge)](LICENSE)

## Installation

### As Python Package

```bash
pip install sg-text-forge
```

### As GitHub Action

```yaml
# .github/workflows/publish.yml
- uses: shared-goals/text-forge@main
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
```

## Quick Start

### 1. Configure MkDocs Plugin

Add to your `mkdocs.yml`:

```yaml
plugins:
  - text-forge:
      editor_enabled: true          # Enable live editor (default: true)
      nobr_emoticons_enabled: true  # Wrap emoticons in no-break spans (default: true)
      downloads_enabled: false      # Show EPUB download button (default: false)
      ai_readable_enabled: false    # Show "Open in Perplexity" button (default: false)
      epub_title: "My Book"         # EPUB metadata (optional)
      epub_author: "Author Name"
      # ... other epub_* options
```

### 2. Build EPUB

```bash
text-forge epub --config=mkdocs.yml --build-dir=build
```

### 3. Build Complete Site

```bash
text-forge build --config=mkdocs.yml --build-dir=build
```

## Features

### 📝 Live Editor Widget

- **Browser-based markdown editor** with real-time preview
- **Pyodide + PyMdown Extensions** for client-side rendering
- **Dual save modes**:
  - `mkdocs serve`: Auto-saves to local filesystem
  - Production: Commits to GitHub via Personal Access Token
- **Split-pane interface** with synchronized scrolling
- **Responsive design** (mobile: editor only, desktop: split view)
- **i18n support** (Russian translations included)

### 🔗 GitHub Integration

- **GitHub API commits** via Personal Access Token
- **Auto-triggers CI/CD** workflows on commit
- **Path-safe writes** with security validation
- **Local fallback** when GitHub token unavailable

### 🤖 AI Agent Integration

- **"Open in Perplexity" button** for AI-powered content analysis
- **Combined markdown export** (`text_combined.md`) with all chapters
- **Normalized anchors and links** for easy navigation
- **AI-readable format** for semantic search and Q&A
- **Privacy-first**: Disabled by default, opt-in via `ai_readable_enabled`

### 📚 EPUB Generation

- **Chapter combining** from `mkdocs.yml` navigation structure
- **PyMdown → Pandoc** syntax normalization via Lua filter
- **Metadata processing** with git version/date extraction
- **Custom CSS styling** for professional EPUB output
- **Asset bundling** (images, resources)
- **Pandoc-based** for wide e-reader compatibility

### 🚀 GitHub Actions

- **Composite action** (`action.yml`) for one-step publishing
- **Builds site + EPUB** in single workflow
- **GitHub Pages deployment** ready
- **Example**: [whattodo publish workflow](https://github.com/bongiozzo/whattodo/blob/master/.github/workflows/publish.yml)

### 🎨 Material Theme Integration

- **Auto-configures** Material theme overrides
- **Custom partials**: editor, downloads, header
- **Custom assets**: editor.js, editor.css, translations.json
- **EPUB download button** in header (when enabled)
- **Custom blocks**: situation, music, chapter-dates, ...

## CLI Commands

### `text-forge epub`

Build EPUB from MkDocs project.

```bash
text-forge epub [OPTIONS]

Options:
  --config PATH      Path to mkdocs.yml (default: mkdocs.yml)
  --build-dir PATH   Build output directory (default: build)
```

### `text-forge build`

Build complete site (EPUB + MkDocs site).

```bash
text-forge build [OPTIONS]

Options:
  --config PATH              Path to mkdocs.yml (default: mkdocs.yml)
  --build-dir PATH           Build directory (default: build)
  --site-dir PATH            MkDocs output (default: from mkdocs.yml)
  --strict/--no-strict       Fail on warnings (default: true)
  --copy-artifacts/--no-copy-artifacts
                             Copy EPUB to site assets (default: true)
  --create-redirect/--no-create-redirect
                             Create root redirect (default: true)
  --redirect-target PATH     Redirect target (default: /ru/)
```

## Plugin Configuration

### MkDocs Plugin Options

```yaml
plugins:
  - text-forge:
      # Editor
      editor_enabled: true                    # Show editor widget
      nobr_emoticons_enabled: true            # Wrap emoticons in md-nobr
      
      # Downloads
      downloads_enabled: false                # Show EPUB download button
      ai_readable_enabled: false              # Show "Open in Perplexity" button
      
      # EPUB Metadata (overrides site_name, site_author, etc.)
      epub_title: ""                          # Book title
      epub_subtitle: ""                       # Book subtitle
      epub_author: ""                         # Author name
      epub_identifier: ""                     # ISBN or URL
      epub_publisher: ""                      # Publisher name
      epub_rights: ""                         # Copyright notice
      
      # UI Labels
      source_file_published_title: "Published"  # Source link label
      
      # Theme
      auto_configure_theme: true              # Auto-set theme overrides
```

## Development

### Setup

```bash
git clone https://github.com/shared-goals/text-forge.git
cd text-forge
make install  # uv sync
```

### Commands

```bash
make format      # Format code with ruff
make lint        # Run linters
make test        # Run tests with pytest
make check-i18n  # Validate translation keys
make release     # Interactive release (bump version, tag, push)
```

### Project Structure

```
text-forge/
├── text_forge/          # Python package
│   ├── plugin.py        # MkDocs plugin
│   ├── build.py         # Build pipeline
│   └── cli.py           # CLI commands
├── scripts/             # Build scripts
│   ├── mkdocs-combine.py      # Chapter combiner
│   ├── pymdown-pandoc.lua     # Pandoc Lua filter
│   └── process-epub-meta.py   # Metadata processor
├── mkdocs/
│   ├── overrides/       # Material theme overrides
│   │   ├── partials/    # HTML templates
│   │   └── assets/      # JS, CSS, translations
│   └── hooks/           # MkDocs hooks
├── epub/                # EPUB templates
│   ├── book_meta.yml    # Metadata template
│   └── epub.css         # EPUB styles
├── tests/               # Pytest tests

```

## Example Projects

- **[whattodo](https://github.com/bongiozzo/whattodo)** - Full example site with Russian content
- **[Live demo](https://text.sharedgoals.ru/ru/)** - Published whattodo site

## Requirements

- **Python** ≥ 3.11
- **Pandoc** (for EPUB generation)
- **MkDocs Material** theme
- **Git** (for version/date metadata)

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please open issues or pull requests at [github.com/shared-goals/text-forge](https://github.com/shared-goals/text-forge).

