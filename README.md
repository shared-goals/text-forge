# text-forge

**MkDocs plugin + GitHub Action + CLI tools** для создания интерактивных текстовых сайтов с EPUB, live preview, и GitHub-based редактированием.

Originally developed for [`bongiozzo/whattodo`](https://github.com/bongiozzo/whattodo), and later extracted as reusable tooling.

---

## Quick Start

### For Content Authors (Use GitHub Action)

```yaml
# .github/workflows/publish.yml
- uses: shared-goals/text-forge@main
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
```

### For Local Development

```bash
# Install from PyPI
pip install text-forge

# Or with uv
uv pip install text-forge

# Build EPUB
text-forge epub --config=mkdocs.yml --build-dir=build

# Build site + EPUB
text-forge build --config=mkdocs.yml --build-dir=build

# Live preview (MkDocs dev server)
mkdocs serve
```

---

## TODOs

- [ ] **Publish to PyPI** (ready! package built and tested)
- [ ] GitHub API Save and Commit (editor widget)
- [ ] Remove plugin with github edit buttons  
- [ ] Update action.yml to use `@v1` after first PyPI release

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

5. **Publish Changes:**
   ```bash
   git add .
   git commit -m "Update content"
   git push  # Triggers GitHub Actions to rebuild site
   ```

**Requirements:**
- 📦 `install.sh` script (handles uv + pandoc installation, then `uv sync` for Python deps)
- 📦 `make` (for development commands, pre-installed on macOS/Linux, needs manual install on Windows)
- ✅ `text-forge` installed automatically via `uv sync` (reads pyproject.toml)
- ✅ `pandoc` installed via install.sh (optional, only for EPUB generation)

**Why Local Development:**
- Test multiple changes before publishing
- Preview site appearance with custom CSS/themes
- Work offline
- Faster feedback loop (no waiting for GitHub Actions)

**Target Users:** Content authors who want to preview changes locally before publishing, using the same browser editor widget as production site.

**Implementation Status:** ✅ Complete (Local Dev Setup)
- ✅ `install.sh` script for universal installation (macOS/Linux/Windows)
- ✅ Makefile with development targets (`serve`, `epub`, `build`, `clean`, `info`)
- ✅ Live editor widget works on local server
- ✅ CLI commands migrated (`text-forge epub`, `text-forge build`)
- ✅ Package ready for PyPI publication
- 🚧 GitHub API Save and Commit (in editor widget) - pending

---
