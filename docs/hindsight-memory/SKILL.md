# Hindsight Memory Projection Skill

Use this skill when connecting a Text Forge / MkDocs long-form text project to Hindsight memory through Text Forge inventory scripts.

This is a generalized Hermes skill example. Copy it into a Hermes profile and adapt the defaults to your local paths, Hindsight URL, bank, and strategy.

## Purpose

Convert plain Markdown roots into a citable agent-memory corpus without duplicating MkDocs parsing logic inside the agent.

```text
Text Forge inventory
        ↓
Hindsight ingest adapter
        ↓
Hermes local wrapper / operator workflow
```

## Assumptions

- Text Forge repo is available locally.
- The text project is MkDocs-based and has `mkdocs.yml`.
- Hindsight API is reachable.
- The Hindsight bank has been configured before bulk ingestion.
- No credentials are stored in the skill.

## Suggested local variables

Set these in your shell, wrapper script, or Hermes profile-specific config:

```bash
export TEXT_FORGE_ROOT=/path/to/text-forge
export TEXT_PROJECT_ROOT=/path/to/your/mkdocs-project
export HINDSIGHT_API_URL=http://localhost:8889
export HINDSIGHT_BANK=hermes
export HINDSIGHT_RETAIN_STRATEGY=wtd-primary
```

## 1. Generate inventory

Run from any directory:

```bash
python "$TEXT_FORGE_ROOT/scripts/wtd-inventory.py" \
  --config "$TEXT_PROJECT_ROOT/mkdocs.yml" \
  --include-drafts \
  --format json \
  > /tmp/text-forge-inventory.json
```

Inspect summary:

```bash
python "$TEXT_FORGE_ROOT/scripts/wtd-inventory.py" \
  --config "$TEXT_PROJECT_ROOT/mkdocs.yml" \
  --include-drafts \
  --format summary
```

Expected checks:

- chapter count looks right;
- draft/published split is expected;
- sections are found for anchored headings;
- chapters without anchors become `section_uid=chapter`.

## 2. Dry-run Hindsight ingest

```bash
python "$TEXT_FORGE_ROOT/scripts/hindsight-ingest.py" \
  --inventory /tmp/text-forge-inventory.json \
  --api-url "$HINDSIGHT_API_URL" \
  --bank "$HINDSIGHT_BANK" \
  --strategy "$HINDSIGHT_RETAIN_STRATEGY" \
  --limit 3 \
  --dry-run
```

Check:

- generated `document_id` values are stable;
- tags include `wtd`, `roots`, `current`, status, chapter, section, and anchor when present;
- URLs point to public MkDocs pages/anchors;
- GitHub URLs point to exact commit line ranges when repo metadata is available.

## 3. Smoke ingest

Before a full corpus ingest, retain one or a few chunks:

```bash
python "$TEXT_FORGE_ROOT/scripts/hindsight-ingest.py" \
  --inventory /tmp/text-forge-inventory.json \
  --api-url "$HINDSIGHT_API_URL" \
  --bank "$HINDSIGHT_BANK" \
  --strategy "$HINDSIGHT_RETAIN_STRATEGY" \
  --limit 1 \
  --yes
```

Then verify in Hindsight:

- document exists;
- facts/observations are extracted correctly;
- recall finds the section by heading, anchor, and meaning;
- metadata and tags are visible and filterable.

## 4. Full ingest

Only after strategy configuration and smoke verification:

```bash
python "$TEXT_FORGE_ROOT/scripts/hindsight-ingest.py" \
  --inventory /tmp/text-forge-inventory.json \
  --api-url "$HINDSIGHT_API_URL" \
  --bank "$HINDSIGHT_BANK" \
  --strategy "$HINDSIGHT_RETAIN_STRATEGY" \
  --yes
```

## Chapter-only maintenance

For a changed chapter:

1. Delete existing Hindsight documents by AND tags in your local operations tooling:

```text
wtd + roots + current + chapter:<chapter-slug>
```

2. Reingest only that chapter:

```bash
python "$TEXT_FORGE_ROOT/scripts/hindsight-ingest.py" \
  --inventory /tmp/text-forge-inventory.json \
  --api-url "$HINDSIGHT_API_URL" \
  --bank "$HINDSIGHT_BANK" \
  --strategy "$HINDSIGHT_RETAIN_STRATEGY" \
  --chapter p2-200-text \
  --yes
```

Use corpus-wide wipe/reingest only after parser changes, strategy changes, or broad anchor refactors.

## Hindsight retain strategy

Configure a named retain strategy before bulk ingestion. Example sketch:

```json
{
  "retain_strategies": {
    "wtd-primary": {
      "retain_mission": "Extract stable meanings, definitions, worldview, tensions, references, and product-relevant concepts from WTD source sections. Preserve public URLs and section identity. Ignore formatting noise, navigation boilerplate, and transient editorial mechanics."
    }
  }
}
```

Keep global reflection/observation missions conservative. A retain strategy applies only to items that pass `strategy`; global missions affect the whole bank.

## Safety rules

- Dry-run first.
- Configure strategy before large ingestion.
- Use `timestamp: "unset"` for timeless source material.
- Use item-level tags.
- Use stable `document_id` + `update_mode: "replace"`.
- Keep private hostnames, paths, bank IDs, and backup steps in a local wrapper skill, not in public reusable scripts.
- Do not store credentials in a skill.

## Common pitfalls

- Reimplementing MkDocs parsing in Hermes skill: use Text Forge inventory instead.
- Treating draft pages as uncitable: draft pages can still have public/preview URLs if served by MkDocs, but they are not in the released TOC.
- Adding stable IDs to Markdown too early: explicit anchors are enough for MVP; use wipe/reingest or a future meaning graph for anchor mappings.
- Using Hindsight default strategy for specialized source corpora: configure and pass a named strategy.
- Publishing local infrastructure details in reusable docs.
