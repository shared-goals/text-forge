```prompt
---
agent: agent
---

# Changelog Summary in Russian

Generate a structured bulleted summary in Russian of all text changes since a given reference point.

## Input

The user provides one of:
- A **git tag** (e.g. `v1.0`)
- A **commit hash** (e.g. `a3f9c12`)
- A **date** (e.g. `2025-01-01`)

## Step 1 — Get the diff

**The diff is already appended below**, under the heading «Diff». Use it as-is:
do not run git yourself, and do not ask for the reference — it is named in that
heading. If the section is missing or empty, stop and say so instead of
inventing changes.

## Step 2 — Analyse changes

- Focus only on added (`+`) and removed (`-`) lines in `text/*.md` files
- Ignore frontmatter, blank lines, and purely formatting changes
- Group changes by file
- For each changed chunk, identify the nearest heading above it — this will be used as the anchor

**Books are a separate section, not diff lines.** The appended «Books» list is
already extracted from the note frontmatter: author, title, shelf. Reading a book
is a fact worth mentioning in the post — the author explicitly wants the books he
has read to be named. Do not read book pages from the diff and do not invent titles:
everything you say about books must come from that list.

- shelf «Прочтённые» — **mention every such book by name** (this is the point of
  the list), one short line each or a compact sentence if there are many;
- shelves «Читаю», «Хочу прочитать», «Недочитанные» — at most one summarizing
  sentence, no full enumeration;
- removals are marked with «убрана» — do not present them as additions.

## Step 3 — Build anchor links

The site URL is `https://text.sharedgoals.ru/`.

URL mapping rules:

- `text/index.md` → `https://text.sharedgoals.ru/`
- `text/<filename>.md` → `https://text.sharedgoals.ru/<filename>/`
- `text/books/<slug>.md` → `https://text.sharedgoals.ru/books/<slug>/`

Heading anchors follow MkDocs slug rules:
- lowercase, spaces → hyphens, punctuation removed
- Example: heading `## Общие цели {#shared_goals}` → anchor `#shared_goals`

Link format:
```
[ключевое слово или фраза](https://text.sharedgoals.ru/chapter#anchor)
```

## Step 4 — Output

This summary will be used as a **post for a Telegram channel**, so write it in an engaging, conversational tone suitable for a public audience — not a dry technical log.

Write a **bulleted list in Russian** summarising what changed, grouped by chapter.
Each bullet must contain at least one link pointing to the relevant heading.

Focus on **semantic changes** (new ideas, revised arguments, added examples, removed sections)
— not on wording tweaks or punctuation fixes.

Example output format:
```
- В главе о [цифровых инструментах](https://text.sharedgoals.ru/p2-140-digital#tools) добавлено описание новых подходов к работе с задачами.
- Раздел [о рутине](https://text.sharedgoals.ru/p2-160-routine#practice) переработан: акцент смещён на осознанность вместо продуктивности.
- В [открытом исходном коде](https://text.sharedgoals.ru/p2-170-opensource#contribute) добавлен новый пример участия в проекте.
```
```
