# AGENTS.md (text-forge)

This repository is tooling: a MkDocs plugin + build scripts + a composite GitHub Action
for building “text projects” (Markdown chapters -> MkDocs site + EPUB).

There is also a sample content repo in `whattodo/` (used as a fixture/demo).

## Key Paths

- `text_forge/plugin.py`: MkDocs plugin (theme overrides, editor integration, dev save endpoint)
- `text_forge/build.py`: Python build helpers wrapping the same scripts
- `text_forge/cli.py`: CLI entrypoint (`text-forge epub|build|info`; `combine` is TODO)
- `scripts/mkdocs-combine.py`: Stage 1 combiner (mkdocs.yml nav-driven)
- `scripts/pymdown-pandoc.lua`: Stage 2 Pandoc Lua filter (PyMdown blocks -> Pandoc-friendly)
- `scripts/process-epub-meta.py`: Metadata placeholder processor for `epub/book_meta.yml`
- `scripts/tests.py`: pytest tests using fixtures in `scripts/fixtures/`
- `mkdocs/overrides/`: Material theme overrides + editor UI
- `mkdocs/hooks/nobr_emoticons.py`: MkDocs hook wrapping ASCII emoticons in `md-nobr`
- `action.yml`: composite GitHub Action (runs pipeline inside GitHub Actions)

## Tooling / Environment

- Python: `>=3.11` (see `pyproject.toml`)
- Runner/package manager: `uv` (see `uv.lock`)
- Tests: `pytest` (dev dependency group)
- Formatting/lint: Makefile references `ruff` (ensure it exists in the uv env)
- External: `pandoc` is required for EPUB generation

Note: some environments don’t have `python` on PATH. Prefer `uv run python` / `uv run pytest`.

## Build / Lint / Test Commands

### Install

- `make install`
  - Runs `uv --project <repo> sync` for this repo.

### Format + Lint

- `make format`
  - Runs import sorting + formatting via ruff.
- `make lint`
  - Runs ruff checks.

If `ruff` isn’t available, add it to the project dev deps and rerun `make install`.

### i18n Check

- `make check-i18n`
  - Validates `mkdocs/overrides/assets/js/translations.json` against HTML/JS usage.
  - Script: `.github/skills/check-i18n/scripts/check_i18n.py`.

### Build Pipeline (as used by content repos)

Content repos use the text-forge CLI commands directly (not the root Makefile).
Use `whattodo/` as a local content repo for development.

- Fast preview (no EPUB, no pandoc required):
  - `cd whattodo && make serve`

- Build EPUB only (requires `pandoc`):
  - `cd whattodo && make epub`

- Full build (EPUB + site):
  - `cd whattodo && make all`

- Clean outputs:
  - `cd whattodo && make clean`

## Tests (including single test)

Primary tests are in `tests/test_pipeline.py` and validate pipeline functionality
using self-contained fixtures in `tests/fixtures/`.

Recommended full run (from text-forge root):

- `make test`

Run a single test:

- `uv run pytest tests/test_pipeline.py -k test_combined_has_all_chapters -v`

Examples:

- `uv run pytest tests/test_pipeline.py -k combined -v`  # All combined tests
- `uv run pytest tests/test_pipeline.py -k pandoc -v`   # All pandoc tests
- `uv run pytest tests/test_pipeline.py -k consistency -v`  # Consistency tests

Notes:

- `scripts/conftest.py` shortens pytest node IDs for cleaner output.
- Tests will skip if expected outputs/fixtures are missing.

## Code Style Guidelines

### Python

- Imports:
  - stdlib, then third-party, then local; keep imports at top unless there is a
    clear reason (plugin code sometimes lazy-imports).
- Formatting:
  - Prefer small helpers and clear intermediate variables over dense expressions.
  - Use f-strings; keep line lengths reasonable.
- Types:
  - Type public functions; keep `Optional[T]` vs `T | None` consistent within a file.
  - Use `pathlib.Path` for filesystem paths.
- Naming:
  - `snake_case` (functions/vars), `PascalCase` (classes), `UPPER_SNAKE_CASE` (constants),
    `_private` prefix for internal helpers.
- Error handling:
  - Prefer specific exceptions (`FileNotFoundError`, `subprocess.CalledProcessError`).
  - Use `subprocess.run(..., check=True)`; surface stderr on failure.
  - Avoid bare `except:`; catch narrowly and re-raise when appropriate.
- Logging/printing:
  - Scripts/CLI: `print()` / `click.echo()` is fine.
  - MkDocs plugin: use `logging.getLogger("mkdocs.plugins.text-forge")`.
- Safety:
  - Keep path-safety checks on the dev save endpoint (`/_text_forge/save`), ensuring
    writes stay within `docs_dir`.

### JavaScript (editor)

- Plain browser JS (no bundler). Current style is an IIFE with strict mode.
- Be defensive around DOM access and network calls.
- Avoid adding heavy dependencies; editor loads Pyodide dynamically.

### YAML

- mkdocs.yml may use custom tags like `!ENV`; loaders should ignore unknown tags rather
  than crash (see `scripts/mkdocs-combine.py`, `scripts/process-epub-meta.py`).
- Keep action/workflow versions pinned and inputs documented.

## Repo-Specific Agent Rules

Cursor rules:

- None found (`.cursorrules` and `.cursor/rules/` do not exist).

Copilot rules (from `.github/copilot-instructions.md`):

- Pipeline stages:
  1) Combine chapters from `mkdocs.yml nav:` -> `build/text_combined.txt` via `scripts/mkdocs-combine.py`
  2) Normalize PyMdown `/// ... ///` blocks -> `build/pandoc.md` via `scripts/pymdown-pandoc.lua`
  3) Process metadata placeholders from `epub/book_meta.yml` via `scripts/process-epub-meta.py`
  4) Render EPUB via `pandoc` + `epub/epub.css` -> `build/text_book.epub`
  5) Copy artifacts into `docs_dir/assets/`, then `mkdocs build` into `public/ru/` (or configured `site_dir`)

- If you change `scripts/mkdocs-combine.py` or `scripts/pymdown-pandoc.lua`:
  - update fixtures in `scripts/fixtures/`
  - validate via `make CONTENT_ROOT=... test` (tests live in `scripts/tests.py`)

- Packaging note:
  - `pyproject.toml` installs `mkdocs/overrides` + `mkdocs/hooks` into
    `sys.prefix/share/text-forge/...`
  - `TextForgePlugin` looks there first and falls back to repo-relative paths for development
