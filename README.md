# text-forge

A reusable build/publish pipeline for Markdown chapter collections.

Primary goal: keep *canonical text + history* in a content repo (e.g. `bongiozzo/whattodo`), while moving *technical build machinery* into this repo so non-developers only need: **edit → commit → published**.

## Outputs (defaults)
- Combined markdown: `build/text_combined.txt`
- Pandoc-normalized markdown: `build/pandoc.md`
- EPUB: `build/text_book.epub`
- MkDocs site output (default): `public/ru/`

## Composite action
Use from a content repo:

```yaml
- uses: shared-goals/text-forge@v1
  with:
    mkdocs_config: mkdocs.yml
    docs_dir: text/ru
    site_dir: public/ru
```

Example full workflow: `examples/content-repo-publish.yml`.

## Comments (Giscus)
This repo intentionally does **not** ship a preconfigured `mkdocs/overrides/partials/comments.html`.

Reason: Giscus config must point to the *current* content repo (and its discussion category ids). Hardcoding a repo (like `bongiozzo/whattodo`) breaks forks/templates.

Recommended approach (Option A): configure comments in each content repo, or skip them.

## EPUB cover
- Cover image is optional.
- If you provide `cover_image` and the file exists, the action uses it.
- If it’s missing, the action builds the EPUB **without** a cover (and emits a warning).

## Notes
- Pipeline logic is ported from `bongiozzo/whattodo` (`scripts/` + `epub/`).
