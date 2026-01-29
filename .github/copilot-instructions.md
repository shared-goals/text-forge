# Copilot instructions (text-forge)

## Big picture
- This repo is **tooling**: a MkDocs plugin + build pipeline + composite GitHub Action for “text projects” (Markdown chapters → MkDocs site + EPUB).
- The pipeline is intentionally staged:
  1) Combine chapters from `mkdocs.yml` `nav:` → `build/text_combined.txt` via `scripts/mkdocs-combine.py`
  2) Normalize PyMdown `/// ... ///` blocks → Pandoc AST via `scripts/pymdown-pandoc.lua` → `build/pandoc.md`
  3) Generate metadata from placeholders in `epub/book_meta.yml` via `scripts/process-epub-meta.py`
  4) Render EPUB via `pandoc` + `epub/epub.css` → `build/text_book.epub`
  5) Copy artifacts into `docs_dir/assets/`, then `mkdocs build` into `public/ru/` (or configured `site_dir`).

## Key components (where to look)
- MkDocs plugin: `text_forge/plugin.py` (theme overrides, hook wiring, editor integration).
- CLI entrypoint: `text_forge/cli.py` (`text-forge epub|build|info`; `combine` is currently TODO).
- Build helpers: `text_forge/build.py` (Python wrapper around the same scripts).
- Site overrides/assets: `mkdocs/overrides/` (templates + `assets/js/editor.js` + CSS).
- MkDocs hook: `mkdocs/hooks/nobr_emoticons.py` (wraps ASCII emoticons in `md-nobr`).

## Local workflows (tooling repo)
- Install deps: `make install` (uses `uv sync` for this repo).
- Fast preview (no EPUB): `make CONTENT_ROOT=/abs/path/to/content serve`.
- Full build: `make CONTENT_ROOT=/abs/path/to/content all`.
- Tests (fixtures): `make CONTENT_ROOT=/abs/path/to/content test`.
- i18n keys check: `make check-i18n` (validates `mkdocs/overrides/assets/js/translations.json`).
- MkDocs strict mode note: the Makefile defaults `MKDOCS_GIT_COMMITTERS_ENABLED=false` to avoid rate-limit warnings becoming errors under `--strict`.

## CI / GitHub Action
- The composite action in `action.yml` runs the same 3-stage pipeline inside GitHub Actions (no `uv`), with pinned `mkdocs`/`mkdocs-material`/plugins. If you bump versions in `pyproject.toml`, consider updating `action.yml` pins too.

## Conventions that affect content repos
- `scripts/mkdocs-combine.py` is nav-driven and performs transformations:
  - Adds a stable top anchor to each file’s first H1: `{#p2-170-opensource-md}` derived from the file path.
  - Rewrites internal links: `(file.md)` → `(#file-md)`, `(file.md#anchor)` → `(#anchor)`.
  - Replaces inner content of `/// details ... ///` blocks with a source link built from `site_url` + nearest heading anchor.
  - Appends chapter dates as a `/// chapter-dates` block, sourcing `created/published/updated` from frontmatter or Git history.
- `scripts/pymdown-pandoc.lua` converts `/// block-type | caption ... ///` into a Pandoc `Div` with class `block-type` and prepends an `h6.block-caption` (caption can be derived from mkdocs.yml `pymdownx.blocks.admonition` types).

## Live editor (MkDocs dev + GitHub)
- UI is injected via `mkdocs/overrides/partials/editor.html` and implemented in `mkdocs/overrides/assets/js/editor.js`.
- Save strategies:
  - Prefer GitHub Contents API (token stored in `localStorage` under `text_forge_github_token`).
  - For `mkdocs serve`, POST to `/_text_forge/save` (implemented in `TextForgePlugin.on_serve`) which writes to `docs_dir` after path-safety checks.

## When changing the pipeline
- If you touch `scripts/mkdocs-combine.py` or `scripts/pymdown-pandoc.lua`, update fixtures in `scripts/fixtures/` and validate via `make … test` (tests are in `scripts/tests.py`).
- Packaging note: `pyproject.toml` installs `mkdocs/overrides` + `mkdocs/hooks` into `sys.prefix/share/text-forge/...`; `TextForgePlugin` looks there first and falls back to repo-relative paths for development.
