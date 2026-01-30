# text-forge

MkDocs plugin + GitHub Action for building text-based websites with EPUB, live editor, and GitHub integration.

## TODOs

- TODO MCP?

## Quick Start

### GitHub Action (Publish Site)

```yaml
# .github/workflows/publish.yml
- uses: shared-goals/text-forge@main
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
```

### Local Development

```bash
./install.sh  # Install dependencies
make serve    # Start dev server with editor
```

## Features

### ✅ Live Editor Widget
- Browser-based markdown editor with real-time preview
- Pyodide + pymdown-extensions (client-side rendering)
- Works on localhost (local saves in `make serve`) and production (GitHub commits)
- Auto-detects environment (local vs production)
- Russian translations

### ✅ GitHub Integration
- Save to GitHub via Personal Access Token (PAT)
- Commits directly to repository
- Auto-triggers GitHub Actions workflow
- Localhost auto-saves to disk

### ✅ EPUB Generation
- Combines markdown chapters via `mkdocs.yml` nav
- Converts PyMdown blocks to Pandoc format
- Generates EPUB with custom CSS
- CLI: `text-forge epub --config=mkdocs.yml`

### ✅ GitHub Actions
- Composite action in `action.yml`
- Builds site + EPUB in one workflow
- Publishes to GitHub Pages
- Example: [whattodo/publish.yml](https://github.com/bongiozzo/whattodo/blob/master/.github/workflows/publish.yml)

