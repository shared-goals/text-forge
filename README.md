# text-forge

Tooling for building/publishing a Markdown chapter collection into multiple formats:
- MkDocs site
- EPUB
- Combined Markdown (for AI/RAG/MCP ingestion)

## Status
This repo is bootstrapped. Next step is porting the pipeline from `bongiozzo/whattodo`.

## Intended usage (content repo)
Add a tiny workflow that checks out your content repo, runs this action, then deploys Pages.

```yaml
- uses: shared-goals/text-forge@v1
```

(Exact workflow example will be added once the pipeline is ported.)
