
# text-forge

**MkDocs plugin + GitHub Action + CLI tools** для создания интерактивных текстовых сайтов с EPUB, live preview, и GitHub-based редактированием.

Originally developed for [`bongiozzo/whattodo`](https://github.com/bongiozzo/whattodo), now extracted as reusable tooling.

---

## Target Use Cases (Specs)

### Use Case 1: Edit Text on Site (Live Editor Widget)

**Scenario:** Content author wants to quickly fix typo or update content using in-browser editor

**Flow:**
1. User visits published site (e.g., `https://bongiozzo.github.io/whattodo/`)
2. Clicks **Edit** button on any page
3. Live markdown editor widget opens directly on site
4. Edit content with real-time preview (Pyodide + pymdown-extensions)
5. Clicks **Save and Commit** button
6. Editor commits file via GitHub API (like standard GitHub web editor)
7. GitHub Actions workflow (`publish.yml`) automatically triggers
8. Site rebuilds and republishes with updated content

**Requirements:**
- ✅ Live editor widget with Pyodide (client-side markdown rendering)
- 🚧 **Save and Commit** button with GitHub API integration
- ✅ GitHub Actions workflow configured with `text-forge` action
- ✅ Proper permissions (`contents: read`, `pages: write`)

**User Permissions:**
- **Repo owner/collaborator:** Can commit directly → auto-publish
- **Authenticated user without write access:** Creates fork and PR automatically
- **Not authenticated:** Read-only preview (no commit button)

**Implementation Status:** 🚧 In Progress
- ✅ Live editor widget (see [editor.js](mkdocs/overrides/assets/js/editor.js))
- 🚧 GitHub API integration for Save and Commit
- ✅ GitHub Actions workflow (see [`publish.yml`](https://github.com/bongiozzo/whattodo/blob/master/.github/workflows/publish.yml))

---

### Use Case 2: Edit Text Locally (Development Preview)

**Scenario:** User wants to preview site locally before publishing, edit content using browser editor widget

**Flow:**
1. **Fork & Clone:**
   ```bash
   # Fork bongiozzo/whattodo on GitHub, then:
   git clone https://github.com/<username>/whattodo.git
   cd whattodo
   ```

2. **One-Command Setup:**
   ```bash
   ./install.sh  # Installs uv + Python deps + text-forge plugin
   ```

3. **Start Local Server:**
   ```bash
   make serve    # Opens http://localhost:8000 with live reload
   ```

4. **Edit Content:**
   - Open any page in browser at `http://localhost:8000`
   - Click **Edit** button to open editor widget
   - Edit markdown with real-time preview (same as production site)
   - Save changes → browser auto-refreshes instantly
   - Test multiple edits before committing

5. **Publish All Changes:**
   ```bash
   make push     # Commits and pushes all changes → triggers GitHub Actions
   ```

**Requirements:**
- 📦 `install.sh` script (handles uv installation + Python deps)
- 📦 `make` (for development commands, auto-installed by install.sh if missing)
- 📦 `pandoc` (optional, only for EPUB generation)
- ✅ `text-forge` installed as Python package (via `uv sync`)
- ✅ `make serve` launches MkDocs dev server with live reload
- ✅ Built-in live markdown editor for in-browser preview

**Why Local Development:**
- Test multiple changes before publishing
- Preview site appearance with custom CSS/themes
- Work offline
- Faster feedback loop (no waiting for GitHub Actions)

**Target Users:** Content authors who want to preview changes locally before publishing, using the same browser editor widget as production site.

**Implementation Status:** 🚧 In Progress
- 🚧 Create `install.sh` script for universal installation
- ✅ Makefile with development targets exists
- ✅ Live editor widget works on local server
- 🚧 Need to migrate scripts to CLI commands for better UX
- 🚧 Need to simplify installation (publish to PyPI)

---

## Three Usage Modes

### Mode 1: PyPI Package + MkDocs Plugin

**What it does:**
- Live markdown editor with Pyodide (client-side preview)
- Prevents line breaks in emoticons `:-)`/`;-)` via `<span class="md-nobr">`
- Custom theme overrides (CSS, JS, templates)
- CLI commands for build pipeline

**Installation:**
```bash
pip install text-forge
# or with uv:
uv add text-forge
```

**MkDocs Configuration:**
```yaml
# mkdocs.yml
plugins:
  - text-forge:
      editor_enabled: true
```

**CLI Commands:**
```bash
text-forge-combine mkdocs.yml -o build/combined.txt
text-forge-epub-meta --config mkdocs.yml --edition "v1.0" --date 2026-01-27
text-forge-build --config mkdocs.yml --output build/
```

### Mode 2: GitHub Action (CI/CD)

**What it does:**
- Builds EPUB from markdown files
- Generates static site via MkDocs
- Publishes to GitHub Pages

**Usage:**
```yaml
# .github/workflows/publish.yml
- uses: shared-goals/text-forge@main
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
    cover_image: text/ru/img/cover.jpg
```

**Outputs:** EPUB, combined markdown, static site in `public/`

### Mode 3: Local Development (Makefile)

**What it does:**
- Quick preview: `make serve` (no EPUB, live reload)
- Full build: `make` or `make site` (EPUB + static site)
- EPUB only: `make epub`

**Commands:**
```bash
---

## Quick Start Guide

### For Content Authors (GitHub Web UI)

1. **Visit your published site** (e.g., `https://<username>.github.io/<repo>/`)
2. **Click Edit button** on any page → redirects to GitHub
3. **Make changes** in GitHub web editor
4. **Commit changes** → site auto-rebuilds via GitHub Actions

No local setup required!

---

### For Developers (Local Editing)

#### 1. Fork & Clone

```bash
# Fork repo on GitHub, then:
git clone https://github.com/<your-username>/<repo>.git
cd <repo>
```

#### 2. Install Dependencies

```bash
make install
```

This will:
- Install `uv` if not present (Python package manager)
- Run `uv sync` to create virtual environment
- Install `text-forge` plugin and all dependencies

#### 3. Start Development Server

```bash
make serve
```

Opens `http://localhost:8000` with:
- ✅ Live reload (saves → instant browser refresh)
- ✅ In-browser markdown editor (Pyodide-powered)
- ✅ Material theme with custom styling

#### 4. Edit Content

Edit any `.md` file in `text/ru/`:
```bash
# Use any text editor:
nano text/ru/p1-010-happiness.md
# or
code text/ru/
```

Save → browser auto-refreshes.

#### 5. Build EPUB (Optional)

```bash
make epub  # Requires pandoc
```

Generates `build/text_book.epub`

#### 6. Publish Changes

```bash
git add text/ru/
git commit -m "Update content"
git push
```

GitHub Actions auto-builds and publishes site.

---

## Repository Structure

```
text-forge/
├── text_forge/              # Python package
│   ├── __init__.py
│   ├── plugin.py            # MkDocs plugin
│   ├── cli.py               # CLI commands (NEW)
│   ├── combine.py           # Markdown combiner (NEW)
│   ├── epub_meta.py         # EPUB metadata processor (NEW)
│   ├── utils.py             # Shared utilities (NEW)
│   └── data/                # Packaged data files (NEW)
│       ├── pymdown-pandoc.lua
│       ├── book_meta.yml
│       └── epub.css
### Minimal (for `make serve`)

- **Python 3.11+**
- **uv** (auto-installed by Makefile if missing)
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`
  - Windows: `winget install -e --id Astral.uv`

### Full Build (for EPUB)

- **pandoc** (for EPUB generation only)
  - macOS: `brew install pandoc`
  - Windows: `winget install -e --id JohnMacFarlane.Pandoc`

### Commands Reference

```bash
make install  # Install/update dependencies
make serve    # Live preview (no EPUB, no pandoc needed)
make epub     # Build EPUB only (requires pandoc)
make site     # Build site + EPUB
make          # Full build (alias for 'make site')
make clean    # Remove build artifacts
make test     # Run tests
make info     # Show resolved paths
```

**Notes:**
- `make serve` disables git-committers plugin for speed
- Build pipeline: combine → pandoc filter → epub → mkdocs build
- All commands use `uv run` for isolated Python environment
├── pyproject.toml           # Python dependencies
├── Makefile                 # Build commands
└── .github/
---

## CLI Commands (v0.1.0+)

After installing `text-forge` package, you get these commands:

### `text-forge-combine`

Combine multiple markdown files into single document.

```bash
# From mkdocs.yml navigation
text-forge-combine mkdocs.yml -o build/combined.txt

# Single file mode
text-forge-combine chapter.md --level 1 -o output.md
```

**Features:**
- Extracts file list from `mkdocs.yml` nav structure
- Adjusts heading levels based on hierarchy
- Fixes internal links: `(file.md)` → `(#file-md)`
- Adds stable anchors for EPUB compatibility
- Extracts git file dates (creation/update)
- Handles `/// details` blocks (replaces with source URLs)

### `text-forge-epub-meta`

Process EPUB metadata placeholders from mkdocs.yml.

```bash
text-forge-epub-meta \
  --config mkdocs.yml \
  --template template.yml \
  --out processed.yml \
  --edition "v1.0, 27 января 2026" \
  --date 2026-01-27
```

**Placeholders:** `[title]`, `[description]`, `[author]`, `[identifier]`, `[language]`, `[copyright]`, `[edition]`, `[date]`

### `text-forge-build`

High-level build command (orchestrates full pipeline).

```bash
text-forge-build --config mkdocs.yml --output build/
text-forge-build --epub-only
text-forge-build --site-only
```

**Pipeline:**
1. Combine markdown files
2. Run Pandoc filter (PyMdown → standard markdown)
3. Process EPUB metadata
4. Generate EPUB (via pandoc)
5. Build MkDocs site

### `text-forge-serve`

Quick development server (wrapper for mkdocs serve with defaults).

```bash
text-forge-serve
text-forge-serve --config mkdocs.yml --host 0.0.0.0
```

---

## Development

### Running Tests

```bash
make test                              # Run all tests
make CONTENT_ROOT=/path/to/repo test   # Test with specific content repo
```

### Building Package

```bash
uv build                    # Creates dist/*.whl and dist/*.tar.gz
uv pip install dist/*.whl   # Test installation
```

### Publishing to PyPI

```bash
uv publish                  # Requires PyPI token
```

---

## Migration from v0.0.x

**v0.1.0 removes backward compatibility:**

- ❌ Direct script invocation no longer supported
- ❌ Git submodule approach deprecated
- ✅ Use PyPI package instead: `pip install text-forge`
- ✅ Scripts now accessible as CLI commands

**Update your workflow:**

1. **Remove git submodule:**
   ```bash
   git rm text-forge
   git commit -m "Remove text-forge submodule"
   ```

2. **Update pyproject.toml:**
   ```toml
   [project]
   dependencies = ["text-forge>=0.1.0"]
   ```

3. **Update Makefile:** Use CLI commands instead of script paths

4. **Update GitHub Action:** Use latest action version

---

## License

MIT License - see LICENSE file

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (TODO)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) (TODO) Requirements

- **uv** (Python package manager):
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh` или `brew install uv`
  - Windows: `winget install -e --id Astral.uv` или через PowerShell: `irm https://astral.sh/uv/install.ps1 | iex`
- **pandoc** (только для EPUB):
  - macOS: `brew install pandoc`
  - Windows: `winget install -e --id JohnMacFarlane.Pandoc`

### Install

```bash
cd your-content-repo
git submodule update --init --recursive  # если submodule не инициализирован
make install                              # установит Python deps через uv
```

### Commands

```bash
make serve    # Preview без EPUB (не требует pandoc)
make          # Full build: EPUB + site (как в CI)
make epub     # Только EPUB
make site     # Только site (EPUB будет собран автоматически)
make clean    # Удалить outputs (build/, public/)
```

**Примечания:**
- `make serve` использует `uv run mkdocs serve` с `MKDOCS_GIT_COMMITTERS_ENABLED=false` для скорости
- Все команды используют скрипты из `text-forge/` submodule
- Build pipeline: `mkdocs-combine.py` → `pymdown-pandoc.lua` → `pandoc` → `mkdocs build`

## Development

### Running Tests

```bash
cd text-forge
make test                                    # Run script tests
make CONTENT_ROOT=/path/to/content test      # Test with specific content
```

### Project Layout

**Будущее направление:** скрипты из `scripts/` можно перенести в plugin как CLI commands через entry points:
```toml
[project.scripts]
text-forge-combine = "text_forge.scripts:combine"
text-forge-pandoc = "text_forge.scripts:pandoc_filter"
```