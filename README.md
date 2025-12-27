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

## Advanced: git-committers token

If your MkDocs config enables `mkdocs-git-committers-plugin-2`, the plugin may need a GitHub token to avoid API rate limits.

This action keeps the “entry level” low by exporting `github.token` as `MKDOCS_GIT_COMMITTERS_APIKEY` by default.

Override/disable options:

```yaml
- uses: shared-goals/text-forge@v1
  with:
    # Use a PAT (recommended if you hit rate limits)
    committers_token: ${{ secrets.COMMITTERS_TOKEN }}

    # Or disable automatic token export entirely
    use_github_token_for_committers: 'false'
```

## Git history (revision date accuracy)

`mkdocs-git-revision-date-localized-plugin` can warn (and sometimes produce incorrect dates) if the repo is checked out shallowly.

This action tries to detect shallow checkouts and runs a best-effort `git fetch --unshallow` before the MkDocs build.
For best performance you can also set `fetch-depth: 0` in your `actions/checkout@v4` step.

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
