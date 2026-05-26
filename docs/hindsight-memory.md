# Hindsight Memory Projection

Text Forge can be used as a source-model layer for agent memory systems. The core idea is to keep Markdown plain and readable, generate a deterministic inventory from MkDocs structure, and let memory adapters consume that inventory instead of reparsing source text.

This reference describes the data shape used by `scripts/wtd-inventory.py` and `scripts/hindsight-ingest.py`. For an agent-facing workflow, see [`docs/hindsight-memory/SKILL.md`](hindsight-memory/SKILL.md).

## Inventory model

```text
plain Markdown + mkdocs.yml + git history
        ↓
Text Forge inventory JSON
        ↓
Hindsight adapter or meaning graph builder
```

Inventory distinguishes:

- `published`: listed in `mkdocs.yml` navigation and released in the table of contents;
- `draft`: Markdown under `docs_dir` but not in navigation yet. Draft pages may still have stable URLs and are useful for review, feedback, and memory.

Every explicit heading anchor becomes a section boundary and public memory address:

```markdown
## Form of the Book {#book_form}
```

A chapter without anchored headings still becomes a chapter-level section:

```text
section_uid = chapter
url = https://example.org/chapter-slug/
```

## Hindsight projection shape

The adapter writes timeless documents:

```json
{
  "timestamp": "unset",
  "update_mode": "replace",
  "strategy": "wtd-primary"
}
```

Tags:

```text
wtd
roots
current
published | draft
chapter:p2-200-text
section:book_form
anchor:book_form
```

Metadata:

```json
{
  "corpus": "wtd",
  "role": "roots",
  "status": "published",
  "commit": "<git commit>",
  "chapter": "p2-200-text",
  "heading_level": "2",
  "heading": "Form of the Book",
  "section_uid": "book_form",
  "anchor": "book_form",
  "url": "https://example.org/p2-200-text/#book_form",
  "github_url": "https://github.com/org/repo/blob/<commit>/text/p2-200-text.md#L10-L40",
  "chunk_index": "0",
  "chunk_count": "1"
}
```

Metadata values are strings to match Hindsight's public schema.

Do not add technical metadata that duplicates Hindsight document fields, such as ingestion time. Hindsight already stores document timestamps (`created_at`, `updated_at`).

## Maintenance model

Recommended maintenance patterns:

```text
minor section edits       → reingest the chapter with replace mode
anchor rename in chapter  → wipe chapter tags, then reingest chapter
parser/model changes      → wipe corpus tag, then reingest all
```

Chapter wipe should target an AND combination like:

```text
wtd + roots + current + chapter:p2-200-text
```

Deletion is intentionally left to local operations tooling because APIs and safety policies differ across deployments.
