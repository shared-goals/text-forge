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

## Notes
- Pipeline logic is ported from `bongiozzo/whattodo` (`scripts/` + `epub/`).
- Cover image is optional: provide it in the content repo (recommended) and pass `cover_image`, or omit it.
