# Copilot instructions (text-forge)

## Big picture
- This repo is a *composite GitHub Action* that builds/publishes a Markdown chapter collection into:
  - combined markdown (`build/text_combined.txt`)
  - pandoc-normalized markdown (`build/pandoc.md`)
  - EPUB (`build/text_book.epub`)
  - MkDocs site output (default `public/ru/`)
- The pipeline is intentionally split into 3 stages in [action.yml](action.yml):
  1) **Combine**: `scripts/mkdocs-combine.py` reads a content repo’s `mkdocs.yml` (`nav`, `docs_dir`, `site_url`) and emits one merged markdown document.
  2) **Normalize**: Pandoc runs `scripts/pymdown-pandoc.lua` to convert PyMdown-style `///` blocks into Pandoc `Div`s and to sanitize image attributes.
  3) **Publish artifacts**: Pandoc generates EPUB using `epub/book_meta.yml` (+ placeholder processing) and MkDocs builds the site.

- Content repos may reference shared MkDocs assets from this repo via paths like:
  - `hooks: [text-forge/mkdocs/hooks/nobr_emoticons.py]`
  - `theme.custom_dir: text-forge/mkdocs/overrides`
  The action provisions these paths at runtime so CI builds work even without a git submodule checkout.

## Key conventions baked into the build
- `scripts/mkdocs-combine.py` (mkdocs.yml mode) requires `mkdocs.yml` to define: `docs_dir`, `nav`, and `site_url`.
- Link rewriting in the combined doc:
  - `[text](file.md)` becomes `[text](#file-md)` (anchor derived from path).
  - `[text](file.md#anchor)` becomes `[text](#anchor)`.
- Frontmatter handling: YAML frontmatter is removed from chapters, but dates may be emitted as a PyMdown block:
  - `/// chapter-dates ... ///` created from `created/published/updated` frontmatter or Git history.
- “Details” blocks: `/// details ... ///` bodies are replaced with a source link derived from `site_url`.
- MkDocs hook `mkdocs/hooks/nobr_emoticons.py` wraps emoticons in `<span class="md-nobr">…</span>` to prevent line breaks.

## Local dev workflow (mirrors the action)
Local runs should mirror [action.yml](action.yml).

- Recommended: use `uv` (see `pyproject.toml` / `uv.lock`) and run via `uv run ...`.

- Create combined markdown:
  - `python scripts/mkdocs-combine.py mkdocs.yml > build/text_combined.txt`
- Run the Pandoc normalization step:
  - `pandoc -f markdown+smart build/text_combined.txt --lua-filter=scripts/pymdown-pandoc.lua --wrap=preserve -t markdown -o build/pandoc.md`
- Generate EPUB (metadata placeholders are normally processed by the action):
  - `pandoc -f markdown+smart build/pandoc.md -o build/text_book.epub --standalone --toc --toc-depth=2 --metadata-file=build/book_meta_processed.yml --resource-path=text/ru --css=epub/epub.css -t epub3`

## Tests
- Tests are fixture-based smoke checks in [scripts/tests.py](scripts/tests.py).
- They look for specific fixture snippets under `scripts/fixtures/` inside the generated outputs:
  - `COMBINED_MD` defaults to `build/text_combined.txt`
  - `PANDOC_MD` defaults to `build/pandoc.md`
- Typical run (after generating outputs): `pytest -q scripts/tests.py`

## Making changes safely
- If changing how `///` blocks are interpreted, update both:
  - [scripts/mkdocs-combine.py](scripts/mkdocs-combine.py) (what is emitted, e.g. `/// chapter-dates`)
  - [scripts/pymdown-pandoc.lua](scripts/pymdown-pandoc.lua) (what Pandoc will parse/convert)
- If changing action inputs/outputs, keep [action.yml](action.yml) and README in sync.
