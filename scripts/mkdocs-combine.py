#!/usr/bin/env python3
"""
MkDocs Markdown Combiner - Multi-Mode Tool

Mode 1: mkdocs.yml mode (default for .yml/.yaml input)
  python3 mkdocs-combine.py mkdocs.yml
  - Extracts navigation hierarchy from mkdocs.yml
  - Reads files one by one from specified chapters
  - Preserves YAML frontmatter from first chapter (for EPUB metadata)
  - Shifts headings according to nav level
  - Fixes internal links
  - Outputs to stdout

Mode 2: Single file mode
  python3 mkdocs-combine.py input.md --level 1
  - Reads input.md file
  - Shifts headings by specified level
  - Fixes internal links
  - Outputs to stdout

Mode 3: Summary mode
  python3 mkdocs-combine.py mkdocs.yml --mode summary --exclude p3-summary.md
  - Extracts nav-ordered file list from mkdocs.yml
  - Concatenates raw chapter content (no heading shifts, no link rewrites)
  - Inserts <!-- FILE: filename.md --> markers between chapters
  - Optionally writes heading index JSON to --index-output
  - Outputs concatenated text to stdout

Usage:
  # Mode 1: Process mkdocs.yml for EPUB
  python3 mkdocs-combine.py mkdocs.yml > combined.md

  # Mode 2: Process single file with heading adjustment
  python3 mkdocs-combine.py chapter.md --level 1 > output.md

  # Mode 3: Prepare source for AI summarization
  python3 mkdocs-combine.py mkdocs.yml --mode summary \\
    --exclude p3-summary.md --index-output build/heading_index.json \\
    > build/summary_source.md

  # Mode 1, with the base URL used for books that are not in the appendix
  python3 mkdocs-combine.py mkdocs.yml --site-url https://text.sharedgoals.ru/ \
    > combined.md

Corpus format for quote ids
--------------------------

A book note (`text/books/<slug>.md`) carries its quote anchors on HEADINGS:

    ## Цитаты

    ### 1 ^quote_1

    > Кобо Абэ, фраза.

The heading TEXT is free (`### 1`, `### Цитата 1`, anything else): the trailing
block id `^quote_N` is the whole contract, and it becomes `{#<slug>-quote_N}` in
the appendix. The pre-0.7.4 shape — the id at the end of a blockquote line
(`> … ^quote_7`) — is NOT supported: no heading can carry it, so a cited book
whose ids sit on non-heading lines is a STALE corpus and the combine fails loudly
naming the file and the ids, rather than emitting a dangling `#<slug>-quote_N`.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from mkdocs_common import flatten_nav_files, load_yaml_config, remove_frontmatter

# --------------------------------------------------------------------------- #
# Book citations -> EPUB appendix                                             #
# --------------------------------------------------------------------------- #

# The appendix heading. Level 1: a nav section is a level-1 heading too, so the
# appendix reads as one more part of the book (and lands in `--toc-depth=2`).
APPENDIX_HEADING = "Приложение: цитируемая литература"

# Base URL for books that are not cited by a chapter — the site the content repo
# publishes to. `mode_mkdocs` takes the same value as its `site_url` default.
DEFAULT_SITE_URL = "https://text.sharedgoals.ru/"

# A markdown link to a book note. `docs_dir` is `text/`, so a chapter reaches
# its books as `books/<slug>.md`, and a link from a deeper page reaches them as
# `../books/<slug>.md`. The `books/` segment is REQUIRED: a plain chapter link
# (`index.md`, `p1-chapter.md#quotes`) is not a book citation, and treating it
# as one would pull chapter files into the appendix. A scheme / leading `/` is
# rejected in the replacer, so an absolute URL is never mistaken for a note.
BOOK_LINK = re.compile(
    r"(!?)\[([^\]]+)\]\(((?:\.\./|\./)?books/[^/)\s]+\.md)(?:#([A-Za-z0-9_-]+))?\)"
)
# the slug, out of the whole url captured by BOOK_LINK group 3 (`books/<slug>.md`)
BOOK_SLUG = re.compile(r"books/([^/)\s]+)\.md$")
# an Obsidian block id at the end of a line (`. ^quote_12`): the site turns it
# into an anchor via text_forge/anchor_ids.py; pandoc does not know it at all
BLOCK_ID = re.compile(r"(?<=[ \t])\^([A-Za-z0-9][A-Za-z0-9_-]*)[ \t]*$")
# an explicit anchor span, the other way a document declares an id
# (only the site plugin emits those any more — the appendix does not)
HTML_ANCHOR = re.compile(r'<a\s+id="([^"]+)"></a>')
# an ATX heading line, with its optional explicit `{#id}` attribute
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*(?:\{#([^}]+)\})?\s*$")
FENCE = re.compile(r"^[ \t]*(?:```|~~~)")

# The citation set of the last mkdocs-mode run: every slug a nav chapter linked
# to, whether or not its note exists on disk. Set by `mode_mkdocs`, read by
# callers (and tests) that want to know what the appendix was built from.
last_cited_slugs: set[str] = set()

# Quote ids that ride a line no heading can carry, per book slug. Set by
# `scan_stale_quote_ids` (the citation scan of `mode_mkdocs`) and read by
# `assert_quote_anchors_declared`, which turns the report into a build error.
# Empty for a corpus that is all new-format.
unsupported_quote_ids: dict[str, set[str]] = {}


def scan_stale_quote_ids(content: str, slug: str) -> set[str]:
    """The `^quote_N` ids in a book note that sit on a NON-heading line.

    The supported corpus format is one shape: the id trails a quote heading
    (`### 1 ^quote_1`, heading text free — the id is the contract) and becomes
    `{#<slug>-quote_1}`. An id at the end of a blockquote line (the pre-0.7.4
    shape) has no heading to carry it, so the chapter's `#<slug>-quote_N` link
    would dangle; `build_books_appendix` refuses such a note.

    Frontmatter and fenced code are skipped, like every other walk here, and ids
    that are not `quote_*` are none of this guard's business.
    """
    stale: set[str] = set()
    in_code = False
    for line in remove_frontmatter(content).split("\n"):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        if HEADING.match(line):
            continue
        block_id = BLOCK_ID.search(line)
        if block_id and block_id.group(1).startswith("quote_"):
            stale.add(block_id.group(1))
    if stale:
        unsupported_quote_ids.setdefault(slug, set()).update(stale)
        print(
            f"[ERROR] Quote ids off the headings (old corpus format): "
            f"books/{slug}.md ({', '.join(sorted(stale))})",
            file=sys.stderr,
        )
    return stale


def assert_quote_anchors_declared() -> None:
    """Fail loudly when a cited book note carries `^quote_N` ids off its headings.

    The corpus format is one shape: an id trailing a quote heading
    (`### N ^quote_N`), which the appendix turns into `{#<slug>-quote_N}`. A note
    whose ids sit on blockquote/prose lines is a STALE (pre-0.7.4) corpus: no
    heading can carry the id, so the chapters' `#<slug>-quote_N` links would land
    nowhere. Emitting a substitute anchor would fabricate an anchor the site does
    not have, so the build stops and names the file and the ids instead.
    """
    if not unsupported_quote_ids:
        return
    detail = ", ".join(
        f"books/{slug}.md ({', '.join(sorted(names))})"
        for slug, names in sorted(unsupported_quote_ids.items())
    )
    raise ValueError(
        f"Quote ids that no heading carries: {detail}. The supported corpus "
        "format is `### N ^quote_N` (heading text is free, the id is the "
        "contract); an id at the end of a blockquote line is the unsupported "
        "old form. Regenerate the book notes, or move each id onto the heading "
        "of the quote it names — a chapter link to it would dangle."
    )


def scan_book_citations(content: str) -> set[str]:
    """Every book slug cited by a markdown link in `content`.

    Line-based, and link-shaped: a `books/<slug>.md` mention in prose or inside a
    fenced code block is a mention, not a citation, so it does not pull a book
    into the appendix.
    """
    slugs: set[str] = set()
    in_code = False
    for line in content.split("\n"):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        for match in BOOK_LINK.finditer(line):
            if match.group(1) == "!":  # an image, not a citation
                continue
            slug = _book_slug(match.group(3))
            if slug:
                slugs.add(slug)
    return slugs


def _book_slug(url: str) -> str | None:
    """The slug of a book-note URL (`books/<slug>.md`), or None if it is not one."""
    match = BOOK_SLUG.search(url)
    return match.group(1) if match else None


def book_slugs_in(content: str) -> set[str]:
    """Every book slug linked anywhere in `content` (fences are scanned too).

    This is the set `rewrite_book_links` acts on: a path link whose slug is here
    has a target to rewrite — either an appendix anchor or the live site page.
    It differs from the CITATION set (what the appendix is built from) by the
    reference list and by the books cited but missing from `text/books/`.
    """
    return {
        slug for m in BOOK_LINK.finditer(content) if (slug := _book_slug(m.group(3)))
    }


def assert_resolvable_book_links(content: str) -> None:
    """Fail loudly when a `books/<slug>.md` link survived the rewrite.

    A link that still says `books/<slug>.md` points at a file that is not in the
    EPUB — the dead link the appendix exists to remove — and pandoc reports it at
    most as a warning. So: every book link left in the document must already be an
    absolute site URL, and its anchor must be one the document declares.
    """
    declared = set(collect_anchor_ids(content))
    dead: list[str] = []
    for m in BOOK_LINK.finditer(content):
        url = m.group(3)
        anchor = m.group(4)
        slug = _book_slug(url)
        if url.startswith(("http://", "https://", "//")):
            # an absolute URL is fine, but its anchor has to exist somewhere
            if anchor and anchor not in declared:
                dead.append(f"{url} (anchor #{anchor} is not in the document)")
        elif slug:
            dead.append(url + (f"#{anchor}" if anchor else ""))
    if dead:
        detail = ", ".join(sorted(set(dead)))
        raise ValueError(
            f"Book links the appendix could not resolve: {detail}. "
            "A `books/<slug>.md` link has no target in the combined document."
        )


def book_heading_title(content: str) -> str:
    """The book's title: frontmatter `title`, else its first heading."""
    title = extract_frontmatter(content).get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return extract_first_heading(content)


def _quote_anchor_map(body: str, slug: str) -> dict[str, str]:
    """The quote ids a note carries on its HEADINGS, as `<slug>-quote_N`.

    The note is walked the way the section is rendered (frontmatter and fenced
    code left out, headings shifted), so the numbering here matches the output.

    Only the supported shape is collected: an id trailing a heading
    (`### 1 ^quote_1` -> `#### 1 {#<slug>-quote_1}`). An id that no heading
    carries is reported by `scan_stale_quote_ids`, not picked up here.
    """
    anchors: dict[str, str] = {}
    in_code = False
    for line in remove_frontmatter(body).split("\n"):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = HEADING.match(line)
        if not heading:
            continue
        text = heading.group(2)
        explicit = heading.group(3)
        for block_id in BLOCK_ID.finditer(text):
            name = block_id.group(1)
            if not name.startswith("quote_"):
                continue
            # the id is the heading's own unless an explicit `{#…}` says otherwise
            if explicit is not None and explicit != name:
                continue
            anchors.setdefault(name, f"{slug}-{name}")
    return anchors


def _shift_one_levels(chunk: str, slug: str, anchors: dict[str, str]) -> list[str]:
    """One book note -> appendix lines, with every heading shifted one level.

    Runs line by line, so a fenced code block keeps its content verbatim: only
    real headings are rewritten.

    - `## Title {#review}`   -> `### Title`   (the review is reached by `<slug>`)
    - `### 1 ^quote_1`       -> `#### 1 {#<slug>-quote_1}`
    - `## Anything {#other}` -> `### Anything {#<slug>-other}`

    A quote heading may sit at level 2 (a note without a `## Цитаты` section) or
    level 3 (the usual shape), and its id comes from the block id alone, so both
    shapes land on the same `<slug>-quote_N` anchor. A `^quote_N` id on a
    NON-heading line cannot become a heading attribute: such a note is stale
    old-format, and `build_books_appendix` refuses to render it.
    """
    raw_lines = remove_frontmatter(chunk).split("\n")
    in_code = False
    out: list[str] = []
    for line in raw_lines:
        if FENCE.match(line):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        match = HEADING.match(line)
        if not match:
            out.append(line)
            continue

        level = min(len(match.group(1)) + 1, 6)
        title = match.group(2).strip()
        anchor = match.group(3)

        block_id = BLOCK_ID.search(title)
        if anchor is None and block_id:
            title = title[: block_id.start()].rstrip()
            anchor = block_id.group(1)

        # the review heading loses its id on purpose: `#<slug>` (the book
        # section) is the documented review target, and a literal `{#review}`
        # would collide across the ~60 books sharing this one document
        if anchor == "review" or anchor is None:
            out.append(f"{'#' * level} {title}")
            continue

        namespaced = f"{slug}-{anchor}" if anchor.startswith("quote_") else anchor
        out.append(f"{'#' * level} {title} {{#{namespaced}}}")
    return out


def render_book_appendix_section(content: str, slug: str) -> str:
    """One cited book as an appendix section (pandoc-native markdown).

    Frontmatter is stripped, the note becomes a `## <title> {#<slug>}` section and
    its own headings shift one level down, so a book reads as:

        ## <title> {#<slug>}
        ### <review title>          (was `## ... {#review}`)
        ### Цитаты
        #### 1 {#<slug>-quote_1}

    A quote whose block id rode a blockquote instead of a heading is NOT
    supported: `build_books_appendix` refuses such a note before calling this.
    """
    title = book_heading_title(content) or slug
    body = remove_frontmatter(content).lstrip("\n")
    anchors = _quote_anchor_map(body, slug)
    lines = [f"## {title} {{#{slug}}}", ""]
    lines += _shift_one_levels(body, slug, anchors)
    return "\n".join(lines).rstrip("\n") + "\n"


def collect_anchor_ids(content: str) -> list[str]:
    """Every anchor the document declares: a `{#id}` heading attribute, or an
    explicit `<a id="…"></a>` span.

    Line-based and fence-aware, like the appendix writer itself. The span shape is
    no longer produced by the appendix — it belongs to the site side, which turns
    a block id into a span via `text_forge/anchor_ids.py` — but a document may
    carry one, so the collectors keep reading it.
    """
    ids: list[str] = []
    in_code = False
    for line in content.split("\n"):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = HEADING.match(line)
        if match and match.group(3):
            ids.append(match.group(3))
            continue
        ids.extend(HTML_ANCHOR.findall(line))
    return ids


def assert_unique_anchor_ids(content: str) -> None:
    """Fail loudly when an anchor id appears twice in the combined document.

    Pandoc does not warn about a duplicate id — it emits two elements with the
    same anchor, and every link to it lands on whichever section the reader's
    viewer resolves first. So a collision is a build error, and renaming in
    silence is not an option: chapters already point at those anchors.
    """
    seen: dict[str, int] = {}
    for anchor_id in collect_anchor_ids(content):
        seen[anchor_id] = seen.get(anchor_id, 0) + 1
    duplicates = {name: n for name, n in seen.items() if n > 1}
    if duplicates:
        detail = ", ".join(f"{name} ({n}x)" for name, n in sorted(duplicates.items()))
        raise ValueError(
            f"Duplicate heading anchor ids in combined document: {detail}. "
            "An anchor must be unique — a link cannot say which section it means."
        )


def rewrite_book_links(content: str, appendix_slugs: set[str], site_url: str) -> str:
    """Point book links at the appendix, or at the live site.

    - `books/<slug>.md` and `books/<slug>.md#review` -> `#<slug>`
    - `books/<slug>.md#quote_N`                      -> `#<slug>-quote_N`
    - a book that is not in the appendix             -> `<site_url>books/<slug>/`,
      with any anchor carried over (`#quote_N`) — the live page really has it
    - an image link, or any link whose URL is not a book note, is left verbatim

    Nothing that reads as a book link survives this function unless it became a
    target: `mode_mkdocs` checks that with `assert_resolvable_book_links`.
    """
    base = site_url.rstrip("/") + "/"

    def replace(match: "re.Match[str]") -> str:
        marker, text, url, anchor = match.groups()
        if marker == "!":
            return match.group(0)
        slug = _book_slug(url)
        if not slug:
            return match.group(0)
        already_absolute = url.startswith(("http://", "https://", "//", "mailto:"))
        if already_absolute and anchor is None:
            # an external link to a live book page, with no anchor of ours in it
            return match.group(0)

        if slug in appendix_slugs:
            # the book section carries `{#slug}`, so a link with no anchor — or
            # with `#review`, the review target — lands on the book itself
            return (
                f"[{text}](#{slug})"
                if anchor in (None, "review")
                else (f"[{text}](#{slug}-{anchor})")
            )

        # not in the appendix: the live site page owns that target
        return f"[{text}]({base}books/{slug}/" + (f"#{anchor})" if anchor else ")")

    return BOOK_LINK.sub(replace, content)


def _defer_book_links(content: str) -> int:
    """How many book links in `content` the appendix pass will have to handle.

    Logging only — it counts the links that `fix_internal_links` is asked to
    leave alone, so a run can be read as "the appendix pass had work to do".
    """
    return len(BOOK_LINK.findall(content))


def build_books_appendix(docs_dir: Path, cited_slugs: set[str]) -> tuple[str, set[str]]:
    """The appendix section for cited books that have a note on disk.

    Returns (appendix markdown, slugs actually written). A missing note is
    skipped with a warning: the book stays as dead as it was, instead of taking
    the reader to an empty section.

    A note whose `^quote_N` ids ride blockquote lines instead of headings was
    already recorded in `unsupported_quote_ids` by the citation scan; such a note
    is left out of the appendix, and the build fails on it at
    `assert_quote_anchors_declared` — naming every stale file at once instead of
    stopping at the first.
    """
    books_dir = docs_dir / "books"
    sections: list[str] = []
    written: set[str] = set()

    for slug in sorted(cited_slugs):
        note = books_dir / f"{slug}.md"
        if not note.exists():
            print(f"[WARN] Cited book note not found, skipped: {note}", file=sys.stderr)
            continue
        try:
            content = note.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as e:
            print(f"[ERROR] Reading book note {note}: {e}", file=sys.stderr)
            continue
        if slug in unsupported_quote_ids:
            # stale quote-id format: rendering it would drop the ids and leave the
            # chapters' links pointing at nothing
            continue
        print(f"[INFO] Appendix book: {slug}", file=sys.stderr)
        sections.append(render_book_appendix_section(content, slug))
        written.add(slug)

    if not written:
        # a text project with no cited books gets no appendix chapter at all —
        # an empty "Приложение" heading would be a chapter with nothing in it
        return "", written

    appendix = f"# {APPENDIX_HEADING}\n\n" + "\n".join(sections).rstrip("\n") + "\n"
    return appendix, written


def extract_nav_items(
    nav_config: list[Any], level: int = 0
) -> list[tuple[str, str, int]]:
    """
    Extract navigation items with hierarchy levels.

    Returns list of tuples: (title, filepath, level)
    - level 0: top-level chapters
    - level 1+: nested sections
    """
    items: list[tuple[str, str, int]] = []

    for item in nav_config:
        if isinstance(item, str):
            if item.endswith(".md"):
                items.append(("", item, level))
        elif isinstance(item, dict):
            for section_title, section_items in item.items():
                if isinstance(section_items, str):
                    # A single entry under its title: either an external link
                    # (`'Shared Goals PRD': https://…`) or one file
                    # (`p3-references.md`). The file form used to fall through to
                    # the section branch below, so the nav heading was emitted and
                    # the file itself silently disappeared from the book.
                    if "://" in section_items:
                        items.append((section_title, section_items, level))
                        continue
                    if section_items.endswith(".md"):
                        items.append((section_title, section_items, level))
                        continue

                # Section header
                items.append((section_title, "", level))

                # Nested items
                if isinstance(section_items, list):
                    items.extend(extract_nav_items(section_items, level + 1))

    return items


def extract_frontmatter(content: str) -> dict[str, Any]:
    """Extract YAML frontmatter as dictionary."""
    if not content.startswith("---\n"):
        return {}

    end_match = re.search(r"\n---\n", content[4:])
    if not end_match:
        return {}

    frontmatter_text = content[4 : end_match.start() + 4]

    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        return frontmatter if isinstance(frontmatter, dict) else {}
    except yaml.YAMLError:
        return {}


def get_git_file_dates(file_path: Path) -> tuple[str, str]:
    """
    Retrieve file dates from Git history.

    Returns tuple: (created_date, updated_date) in format %d.%m.%Y
    - created_date: date of first commit (--follow to track renames)
    - updated_date: date of most recent commit
    """
    import subprocess

    try:
        # Determine git repository root (file's parent, or walk up to find .git)
        # Since file_path might be in a different repo than cwd, we need to find
        # the repo that contains this file
        git_dir = file_path.parent
        while git_dir.parent != git_dir:  # not at filesystem root
            if (git_dir / ".git").exists():
                break
            git_dir = git_dir.parent

        # Make file path relative to git root
        try:
            rel_path = file_path.relative_to(git_dir)
        except ValueError:
            # File is not under git_dir, can't get git dates
            return "", ""

        # Get creation date (first commit following file history)
        result_created = subprocess.run(
            [
                "git",
                "-C",
                str(git_dir),
                "log",
                "--follow",
                "--diff-filter=A",
                "--format=%ai",
                "--reverse",
                "--",
                str(rel_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        created_date = None
        if result_created.stdout:
            # Extract first line and parse date (format: YYYY-MM-DD HH:MM:SS +ZZZZ)
            first_line = result_created.stdout.strip().split("\n")[0]
            if first_line:
                date_part = first_line.split()[0]
                created_date = format_git_date(date_part)

        # Get update date (most recent commit)
        result_updated = subprocess.run(
            [
                "git",
                "-C",
                str(git_dir),
                "log",
                "--follow",
                "--format=%ai",
                "--max-count=1",
                "--",
                str(rel_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        updated_date = None
        if result_updated.stdout:
            first_line = result_updated.stdout.strip()
            if first_line:
                date_part = first_line.split()[0]
                updated_date = format_git_date(date_part)

        return created_date or "", updated_date or ""

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        print(
            f"[WARN] Could not retrieve Git dates for {file_path}: {e}", file=sys.stderr
        )
        return "", ""


def format_git_date(date_str: str) -> str:
    """Convert date from YYYY-MM-DD format to %d.%m.%Y format."""
    try:
        from datetime import date

        dt = date.fromisoformat(date_str)
        return dt.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return ""


def format_dates_from_frontmatter(
    frontmatter: dict[str, Any], file_path: Path | None = None
) -> str:
    """
    Format dates from frontmatter as italic text.

    Falls back to Git history if dates are not specified in frontmatter.
    Date format: %d.%m.%Y
    """
    dates: list[str] = []

    # Get Git dates as fallback
    git_created = ""
    git_updated = ""
    if file_path:
        git_created, git_updated = get_git_file_dates(file_path)

    # Use frontmatter date or fall back to Git date
    created = frontmatter.get("created") or git_created
    published = frontmatter.get("published") or git_created
    updated = frontmatter.get("updated") or git_updated

    if created:
        dates.append(f"Создано: {created}")
    if published and published != created:
        dates.append(f"Опубликовано: {published}")
    if updated and updated != created:
        dates.append(f"Обновлено: {updated}")

    if dates:
        # Ensure blank lines so Pandoc treats markers and content as separate blocks
        # This helps the Lua filter detect opening/content/closing correctly.
        return f"/// chapter-dates\n{' '.join(dates)}\n///"
    return ""


def adjust_heading_levels(
    content: str, level: int
) -> tuple[str, list[tuple[int, str | None]]]:
    """
    Shift markdown heading levels by specified amount.
    Returns (new_content, headings) where headings is a list of (pos, anchor or None)
    """
    headings: list[tuple[int, str | None]] = []

    def replace_heading(match: "re.Match[str]") -> str:
        hashes = match.group(1)
        title = match.group(2)
        anchor = match.group(3) or ""
        current_level = len(hashes)
        new_level = max(1, min(current_level + level, 6))
        new_hashes = "#" * new_level
        # Extract anchor name if present
        anchor_name = None
        if anchor:
            m = re.match(r"\s*\{#([^}]+)\}", anchor)
            if m:
                anchor_name = m.group(1)
        headings.append((match.start(), anchor_name))
        return f"{new_hashes} {title}{anchor}"

    pattern = r"^(#{1,6})\s+(.+?)(\s*\{#[^}]+\})?$"
    new_content = re.sub(pattern, replace_heading, content, flags=re.MULTILINE)
    return new_content, headings


def add_anchor_to_first_h1(content: str, anchor_id: str) -> str:
    """
    Add anchor to the first h1 heading if it doesn't have one already.

    Transforms:
    - # Heading -> # Heading {#anchor-id}
    - # Heading {#existing} -> # Heading {#existing} (unchanged if has anchor)
    """
    # Find the first h1 heading
    match = re.search(r"^(# [^\n]*?)(\s*\{#[^}]+\})?\n", content, re.MULTILINE)
    if match:
        heading = match.group(1)
        existing_anchor = match.group(2)

        # If no anchor, add one
        if not existing_anchor:
            new_heading = f"{heading} {{{anchor_id}}}\n"
            return content[: match.start()] + new_heading + content[match.end() :]

    return content


def fix_internal_links(
    content: str, current_file: str, skip_book_links: bool = False
) -> str:
    """
    Fix internal markdown links for combined documents.

    Transformations:
    - [text](file.md) -> [text](#file-md)
    - [text](file.md#anchor) -> [text](#anchor)
    - [text](#anchor) -> [text](#anchor) (unchanged)

    With `skip_book_links`, links to book notes (`books/<slug>.md[#anchor]`) are
    left verbatim for `rewrite_book_links` — the appendix pass that knows whether
    the book landed in the appendix, was skipped, or belongs to the live site.
    """

    def replace_link(match: "re.Match[str]") -> str:
        is_image = match.group(1) == "!"
        text = match.group(2)
        url = match.group(3)

        # Skip image links and external links
        if is_image or url.startswith(("http://", "https://", "//", "mailto:")):
            return match.group(0)

        # Skip book notes when the appendix pass is going to handle them
        if skip_book_links and BOOK_LINK.fullmatch(match.group(0)):
            return match.group(0)

        # Handle internal links
        if "#" in url:
            if url.startswith("#"):
                # Anchor-only link (unchanged)
                new_url = url
            else:
                # File with anchor: file.md#anchor -> #anchor
                _, anchor_part = url.split("#", 1)
                # Just use the anchor part, ignore the file
                new_url = f"#{anchor_part}"
        else:
            # File without anchor: file.md -> #file-md
            if url.endswith(".md"):
                file_base = url.replace(".md", "-md").replace("/", "-")
                new_url = f"#{file_base}"
            else:
                new_url = url

        return f"[{text}]({new_url})"

    pattern = r"(!?)\[([^\]]+)\]\(([^)]+)\)"
    return re.sub(pattern, replace_link, content)


def extract_first_heading(content: str) -> str:
    """Extract first heading from markdown content."""
    content_clean = remove_frontmatter(content)
    match = re.search(
        r"^#{1,6}\s+(.+?)(?:\s*\{#[^}]+\})?$", content_clean, re.MULTILINE
    )
    return match.group(1).strip() if match else ""


def replace_details_with_source_link(
    content: str,
    site_url: str,
    filepath: str,
    headings: list[tuple[int, str | None]],
) -> str:
    """
    Replace content inside /// details blocks with source link.

    Transforms:
        /// details | Title
        <content>
        ///

    Into:
        /// details | Title
        <source_link>
        ///

    Uses headings array to find nearest anchor above each block.
    """
    # Pattern: capture opening line with optional title, then any content until closing ///
    # Group 1: optional title part after 'details' (e.g., ' | Исходник')
    # Group 2: inner content (to be replaced)
    details_pattern = r"^///\s*details([^\n]*)\n+(.*?)\n+///"

    # Keep filename normalized for URL building
    filename_without_md = filepath.replace(".md", "").replace("\\", "/")

    def find_nearest_anchor_above(pos: int) -> str | None:
        anchor: str | None = None
        for hpos, hanchor in headings:
            if hpos < pos and hanchor:
                anchor = hanchor
            elif hpos >= pos:
                break
        return anchor

    def replace_details(match: "re.Match[str]") -> str:
        title_part = match.group(1)  # Includes everything after 'details' on first line
        match_pos = match.start()
        anchor = find_nearest_anchor_above(match_pos)
        if anchor:
            source_link = f"{site_url.rstrip('/')}/{filename_without_md}#{anchor}"
        else:
            source_link = f"{site_url.rstrip('/')}/{filename_without_md}"
        # Preserve delimiters and title, replace inner content with the link only
        return f"/// details{title_part}\n\n<{source_link}>\n\n///"

    # Apply details-block replacement (DOTALL so '.' matches newlines)
    return re.sub(
        details_pattern, replace_details, content, flags=re.MULTILINE | re.DOTALL
    )


def mode_mkdocs(config_path: str, site_url: str = DEFAULT_SITE_URL) -> str:
    """
    Mode 1: Process mkdocs.yml configuration.

    - Extracts nav hierarchy
    - Reads files one by one
    - Shifts headings according to level
    - Fixes links
    - Appends an appendix with the books the chapters cite
    - Returns combined content

    `site_url` is the base URL used for links to books that are NOT cited by a
    chapter (the p3-references list): they point at the live site instead of an
    appendix section that does not exist. Defaults to `site_url:` in mkdocs.yml.
    """
    config = load_yaml_config(config_path)

    if "docs_dir" not in config:
        raise ValueError("Config missing 'docs_dir'")
    if "nav" not in config:
        raise ValueError("Config missing 'nav'")
    if "site_url" not in config:
        raise ValueError("Config missing 'site_url'")

    config_dir = Path(config_path).parent
    docs_dir = config_dir / config["docs_dir"]

    if not docs_dir.exists():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")

    nav_items = extract_nav_items(config["nav"])

    # Which books the text actually cites. Only the nav files are scanned, and
    # only for citations: the reference list (p3-*) enumerates the whole shelf,
    # so including it would turn the appendix into a second copy of the corpus.
    # A nav file whose name says 'reference' is therefore not scanned, and links
    # it makes to books that no chapter cited become external (see below).
    nav_files = flatten_nav_files(config["nav"])
    # a fresh report per run: one left over from a previous build would fail it
    global unsupported_quote_ids
    unsupported_quote_ids = {}
    cited_slugs: set[str] = set()
    for filepath in nav_files:
        # the reference list enumerates the whole shelf, so it is not a citation
        # source — including it would turn the appendix into a second corpus.
        # `reference` in the file name is how content repos spell that file
        # (p3-references.md), and the nav is the only place it is declared.
        if "reference" in Path(filepath).stem.lower():
            continue
        file_path = docs_dir / filepath
        if not file_path.exists():
            continue
        try:
            chapter = remove_frontmatter(file_path.read_text(encoding="utf-8"))
            cited_slugs |= scan_book_citations(chapter)
            # every book this chapter cites is checked for ids that no heading
            # carries (stale pre-0.7.4 corpus) — see `scan_stale_quote_ids`
            for slug in scan_book_citations(chapter):
                note = docs_dir / "books" / f"{slug}.md"
                if note.exists():
                    scan_stale_quote_ids(note.read_text(encoding="utf-8"), slug)
        except (OSError, UnicodeError) as e:
            print(f"[ERROR] Scanning citations in {file_path}: {e}", file=sys.stderr)
            continue
    # the side channel: what the appendix was built from (see module docstring)
    global last_cited_slugs
    last_cited_slugs = set(cited_slugs)
    print(
        f"[INFO] Cited books: {len(cited_slugs)} (from {len(nav_files)} nav files)",
        file=sys.stderr,
    )

    combined: list[str] = []
    first_content = True

    for title, filepath, level in nav_items:
        # External links
        if filepath and "://" in filepath:
            level_hashes = "#" * (level + 1)
            combined.append(f"\n{level_hashes} [{title}]({filepath})\n")
            continue

        # Section headers (no filepath)
        if not filepath:
            level_hashes = "#" * (level + 1)
            combined.append(f"\n{level_hashes} {title}\n\n")
            continue

        # File content
        file_path = docs_dir / filepath
        if not file_path.exists():
            print(f"[WARN] File not found: {file_path}", file=sys.stderr)
            continue

        print(f"[INFO] Processing: {filepath} (level {level})", file=sys.stderr)

        try:
            content = file_path.read_text(encoding="utf-8")

            # Extract frontmatter for dates and metadata
            frontmatter = extract_frontmatter(content)

            # Extract dates for display at end of section
            dates_text = format_dates_from_frontmatter(frontmatter, file_path)

            # Extract title from first heading
            title_from_file = extract_first_heading(content)
            if not title_from_file:
                title_from_file = filepath.replace(".md", "").replace("-", " ").title()

            print(f"[INFO]   Title: {title_from_file}", file=sys.stderr)

            # Calculate anchor ID for the file
            anchor_id = f"#{filepath.replace('.md', '-md').replace('/', '-')}"

            # Process content
            content = remove_frontmatter(content)
            content = content.lstrip(
                "\n"
            )  # Remove leading blank lines after frontmatter

            content = add_anchor_to_first_h1(
                content, anchor_id
            )  # Add anchor to original h1
            content, headings = adjust_heading_levels(content, level)
            content = replace_details_with_source_link(
                content, config["site_url"], filepath, headings
            )
            # Book links are left to the appendix pass at the end of the
            # document: `fix_internal_links` throws the file part away, and the
            # appendix rewrite needs that part to know WHICH book a `#quote_N`
            # belongs to. The order is load-bearing.
            deferred = _defer_book_links(content)
            if deferred:
                print(
                    f"[INFO]   Book links deferred to appendix pass: {deferred}",
                    file=sys.stderr,
                )
            content = fix_internal_links(content, filepath, skip_book_links=True)

            # Combine with dates
            # First content section has no leading newline; subsequent ones do
            if first_content:
                output_section = content
                first_content = False
            else:
                output_section = f"\n{content}"

            # Add dates at the end if present
            if dates_text:
                output_section += f"\n{dates_text}\n"

            combined.append(output_section)

        except (OSError, UnicodeError, ValueError) as e:
            print(f"[ERROR] Processing {filepath}: {e}", file=sys.stderr)
            continue

    # Combine all sections, then rewrite the book links against the appendix
    # that was actually written. This runs on the ASSEMBLED document and AFTER
    # `fix_internal_links` per file, so a book link is still recognisable by its
    # path (`books/<slug>.md#quote_1`) instead of being a bare `#quote_1` that no
    # longer says which book it means.
    result = "".join(combined)
    # the appendix is written BEFORE the links are rewritten, so the rewrite knows
    # which cited books really got a section: a book that did not (no note on
    # disk, or a stale quote-id format) is one the appendix cannot answer, and its
    # links go to the live site page that does
    appendix, appendix_slugs = build_books_appendix(docs_dir, cited_slugs)
    # the rewrite covers the WHOLE document — chapters and the reference list
    # alike — and it keys on the slugs actually linked, so a reference-list link
    # to a book no chapter cited still becomes a live-site URL
    linked_slugs = book_slugs_in(result)
    print(
        f"[INFO] Book links rewritten: {len(linked_slugs)} linked, "
        f"{len(appendix_slugs)} with an appendix section",
        file=sys.stderr,
    )
    result = rewrite_book_links(result, appendix_slugs, site_url)
    if appendix:
        result = result.rstrip("\n") + "\n\n" + appendix

    # two sections with the same anchor would silently mislead every link to it
    assert_unique_anchor_ids(result)
    # a stale quote-id corpus (ids off the headings) is reported as itself, not as
    # an unresolvable link — the defect is in the note, not in the chapter
    assert_quote_anchors_declared()
    # and no book link may survive without a target
    assert_resolvable_book_links(result)

    return result


def extract_headings_with_anchors(content: str) -> list[tuple[str, str]]:
    """
    Extract all headings with {#anchor} from markdown content.

    Returns list of tuples: (heading_text, anchor)
    Only returns headings that have explicit anchors.
    """
    pattern = r"^#{1,6}\s+(.+?)\s*\{#([^}]+)\}\s*$"
    return re.findall(pattern, content, re.MULTILINE)


def mode_summary(
    config_path: str,
    exclude: list[str] | None = None,
    index_output: str | None = None,
) -> str:
    """
    Mode 3: Prepare source text for AI summarization.

    - Extracts nav-ordered file list from mkdocs.yml
    - Skips files listed in --exclude
    - Concatenates raw chapter content (no heading shifts, no link rewrites)
    - Inserts <!-- FILE: filename.md --> markers between chapters
    - Optionally writes heading index JSON to index_output
    - Returns concatenated text
    """
    config = load_yaml_config(config_path)

    if "docs_dir" not in config:
        raise ValueError("Config missing 'docs_dir'")
    if "nav" not in config:
        raise ValueError("Config missing 'nav'")

    config_dir = Path(config_path).parent
    docs_dir = config_dir / config["docs_dir"]

    if not docs_dir.exists():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")

    exclude_set = set(exclude or [])
    nav_files = flatten_nav_files(config["nav"])
    heading_index: dict[str, str] = {}  # "filename_without_md#anchor" -> "Heading text"
    combined: list[str] = []

    for filepath in nav_files:
        if filepath in exclude_set:
            print(f"[INFO] Skipping excluded: {filepath}", file=sys.stderr)
            continue

        file_path = docs_dir / filepath
        if not file_path.exists():
            print(f"[WARN] File not found: {file_path}", file=sys.stderr)
            continue

        print(f"[INFO] Processing: {filepath}", file=sys.stderr)

        try:
            content = file_path.read_text(encoding="utf-8")
            content_body = remove_frontmatter(content).lstrip("\n")

            # Extract headings for the index
            filename_base = filepath.replace(".md", "")
            headings = extract_headings_with_anchors(content_body)
            for heading_text, anchor in headings:
                key = f"{filename_base}#{anchor}"
                heading_index[key] = heading_text

            # Add file marker and content
            combined.append(f"<!-- FILE: {filepath} -->\n{content_body}")

        except (OSError, UnicodeError, ValueError) as e:
            print(f"[ERROR] Processing {filepath}: {e}", file=sys.stderr)
            continue

    # Write heading index if requested
    if index_output:
        index_path = Path(index_output)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(heading_index, f, ensure_ascii=False, indent=2)
        print(
            f"[INFO] Heading index: {index_path} ({len(heading_index)} entries)",
            file=sys.stderr,
        )

    return "\n\n".join(combined)


def mode_single_file(input_file: str, level: int) -> str:
    """
    Mode 2: Process single markdown file.

    - Reads input.md
    - Shifts headings by specified level
    - Fixes internal links
    - Returns processed content
    """
    file_path = Path(input_file)

    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    print(f"[INFO] Processing: {input_file} (level shift: {level})", file=sys.stderr)

    content = file_path.read_text(encoding="utf-8")

    # Extract title for logging
    title_from_file = extract_first_heading(content)
    print(f"[INFO]   Title: {title_from_file}", file=sys.stderr)

    # Process content
    content = remove_frontmatter(content)
    content, _ = adjust_heading_levels(content, level)
    content = fix_internal_links(content, input_file)

    return content


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="MkDocs Markdown Combiner - Multi-mode tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required: input file
    parser.add_argument(
        "input", help="Input file: either mkdocs.yml or a markdown file"
    )

    # Optional: explicit mode selection
    parser.add_argument(
        "--mode",
        choices=["mkdocs", "single", "summary"],
        default=None,
        help="Processing mode: mkdocs (EPUB combine), single (one file), "
        "summary (AI summarization source). Auto-detected if omitted.",
    )

    # Optional: level for single file mode
    parser.add_argument(
        "--level",
        type=int,
        default=0,
        help="Heading level shift for single file mode (default: 0)",
    )

    # Optional: base URL for books that are not cited (appendix links)
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help="Base URL used for links to books that are NOT cited by a chapter "
        f"(default: {DEFAULT_SITE_URL})",
    )

    # Optional: exclude files for summary mode
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Filenames to exclude in summary mode (e.g. p3-summary.md)",
    )

    # Optional: heading index output for summary mode
    parser.add_argument(
        "--index-output",
        default=None,
        help="Path to write heading index JSON (summary mode only)",
    )

    args = parser.parse_args()

    # Auto-detect mode if not specified
    mode = args.mode
    if mode is None:
        if args.input.endswith(".yml") or args.input.endswith(".yaml"):
            mode = "mkdocs"
        else:
            mode = "single"

    try:
        if mode == "mkdocs":
            print("[INFO] Mode: mkdocs (EPUB combine)", file=sys.stderr)
            output = mode_mkdocs(args.input, site_url=args.site_url)
        elif mode == "summary":
            print("[INFO] Mode: summary (AI summarization source)", file=sys.stderr)
            output = mode_summary(args.input, args.exclude, args.index_output)
        else:
            print(
                f"[INFO] Mode: single file (level shift {args.level})",
                file=sys.stderr,
            )
            output = mode_single_file(args.input, args.level)

        # Output to stdout
        print(output, end="")
        print("[INFO] Complete", file=sys.stderr)

    except (
        FileNotFoundError,
        ValueError,
        OSError,
        yaml.YAMLError,
        subprocess.CalledProcessError,
    ) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
