"""Local link map + chapter link rewriter.

Chapters of the Text link books/reviews/quotes on livelib.ru. The site already
carries every one of them as a note-book under `text/books/`, so those links can
point at the local page instead — the reader stays on the site, and livelib.ru
survives only inside the note-books (frontmatter + the attribution line under each
quote, which is where attribution belongs).

`build_link_map(books_dir)` reads what the note-books DECLARE and keys it by
`<kind>/<id>` (the canonical form `_link_key` produces, so the decorative slug
suffix of a URL never matters):

    {"book/1001616054":  {"slug": "abe-chetvertyy-lednikovyy-period", "anchor": None},
     "review/4201003":   {"slug": "abe-chetvertyy-lednikovyy-period", "anchor": None},
     "quote/42572258":   {"slug": "abe-chetvertyy-lednikovyy-period", "anchor": "quote_1"},
     "dupes":            [...]}          # report data, see below

book/review keys come from frontmatter (a page, no anchor). A quote key takes the
anchor of the quote block its attribution line closes: the nearest PRECEDING
`^quote_N` in the same note, so the reader lands on the quote, not at the top of
the page. An attribution with no preceding id gives anchor None (the page is still
a fine target).

The same quote can sit on two shelves (the reader quoted it twice), so a quote id
may appear in several notes. That is not an error: the FIRST note wins and the
later ones are recorded under the `dupes` key for the report.

`rewrite_text_links(root, apply=)` walks text/*.md — excluding text/books/ and
any `_curation` directory — and swaps livelib URLs for the local path. It
defaults to a dry run: report only, no writes. Rewriting the URL only, never the
link text: what the author wrote stays what the reader reads.
"""

import pathlib
import re

from text_forge.wtd_books_p3 import _link_key

# every livelib URL shape we know how to place: a /quote/ url in a note body,
# a markdown link in a chapter, a bare url in prose. The url ends at `)`, a
# quote mark or whitespace, so a url inside `[text](url)` is taken whole.
LIVELIB_URL = re.compile(
    r"https?://(?:www\.)?livelib\.ru/(book|work|review|quote)/(\d+)[^)\s\"']*")

# one note's anatomy: frontmatter block, quote block-ids, attribution lines
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
BLOCK_ID = re.compile(r"[ \t]+\^([A-Za-z0-9][A-Za-z0-9_-]*)[ \t]*$")
ATTRIBUTION = re.compile(r"^—\s*\[")
DUPES_KEY = "dupes"


def _entries(text: str) -> list[tuple[str, str, str]]:
    """(kind, id, anchor) for every livelib id a note declares.

    anchor is the block id of the quote block a url closes: the nearest
    preceding `^id` in the file, so an attribution line inherits the id of the
    quote above it. Frontmatter urls have no preceding id -> anchor None.
    """
    out: list[tuple[str, str, str]] = []
    last_anchor: str | None = None
    for line in text.split("\n"):
        for m in LIVELIB_URL.finditer(line):
            out.append((m.group(1), m.group(2), last_anchor))
        # the id is read AFTER the urls on the line: a blockquote's last line
        # carries the id and no attribution, so the next line's attribution gets it
        id_on_line = BLOCK_ID.search(line)
        if id_on_line:
            last_anchor = id_on_line.group(1)
    return out


def build_link_map(books_dir) -> dict:
    """`<kind>/<id>` -> {"slug", "anchor"}, plus a `dupes` report list.

    Notes are read in sorted path order, so "first note wins" for a repeated
    quote id is deterministic across runs. `_curation` directories are skipped:
    they hold mappings, not notes.
    """
    root = pathlib.Path(books_dir)
    link_map: dict[str, dict] = {}
    dupes: list[dict] = []
    if not root.is_dir():
        return {}
    for note in sorted(root.rglob("*.md")):
        if "_curation" in note.parts:
            continue
        slug = note.stem
        # quote ids are read from the BODY: frontmatter urls are the note's own
        # book/review ids and must not inherit an anchor from an earlier note
        body = split_frontmatter(note.read_text(encoding="utf-8"))[1]
        for kind, rid, anchor in _entries(body):
            # a /work/ url names the same work as the note's /book/ id
            normalized = "book" if kind == "work" else kind
            key = f"{normalized}/{rid}"
            if key in link_map:
                dupes.append({"key": key, "slug": slug,
                             "first": link_map[key]["slug"]})
                continue
            link_map[key] = {"slug": slug, "anchor": anchor}
        # frontmatter declares the page-level ids, anchorless
        for url in _frontmatter_urls(note):
            key = _key_of(url)
            if key is None:
                continue
            link_map.setdefault(key, {"slug": slug, "anchor": None})
    if dupes:
        link_map[DUPES_KEY] = dupes
    return link_map


def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter block, body) — no frontmatter, no body, no crash."""
    m = FRONTMATTER.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def _frontmatter_urls(note) -> list[str]:
    """Every livelib URL inside the note's frontmatter block."""
    fm, _ = split_frontmatter(pathlib.Path(note).read_text(encoding="utf-8"))
    return [m.group(0) for m in LIVELIB_URL.finditer(fm)]


def _key_of(url: str) -> str | None:
    """`<kind>/<id>` of a livelib URL ('' / None when it is not one)."""
    key = _link_key(url)
    return f"{key[0]}/{key[1]}" if key else None


def local_target(entry: dict) -> str:
    """The site-root path a map entry points at (`/books/<slug>[#anchor]`)."""
    anchor = entry.get("anchor")
    return f"/books/{entry['slug']}/" + (f"#{anchor}" if anchor else "")


def rewrite_text_links(root, apply: bool = False,
                      link_map: dict | None = None) -> dict:
    """Point chapter links at local pages; report everything it would do.

    root — the content repo root (holds `text/`). apply=False (default) writes
    nothing: dry run. apply=True rewrites the files in place.

    Returns {"files", "replacements", "candidates", "candidates_local",
    "replacements_list", "unresolved", "dupes", "link_map", "applied"} where
    `candidates` counts every livelib URL seen, `candidates_local` those that
    resolve to a note, `replacements_list` the (file, line, old, new) entries of
    the replacements actually made (dry run: the replacements it WOULD make), and
    `unresolved` the URLs with no note — those files are left untouched.
    """
    root = pathlib.Path(root)
    text_dir = root / "text"
    books_dir = text_dir / "books"
    if link_map is None:
        link_map = build_link_map(books_dir)
    # an empty map means the notes are not where we expect them: report what was
    # looked for, so a wrong root fails loudly instead of quietly doing nothing
    if not link_map and not books_dir.is_dir():
        raise FileNotFoundError(f"no note-books under {books_dir}")

    files = 0
    replacements = 0
    candidates = 0
    candidates_local = 0
    replaced: list[dict] = []
    unresolved: list[dict] = []

    for chapter in sorted(text_dir.glob("*.md")) if text_dir.is_dir() else []:
        text = chapter.read_text(encoding="utf-8")
        new_text = text
        file_replacements = 0
        for lineno, line in enumerate(text.split("\n"), start=1):
            for m in LIVELIB_URL.finditer(line):
                candidates += 1
                key = f"{m.group(1)}/{m.group(2)}"
                if key == "work/" + m.group(2):
                    key = f"book/{m.group(2)}"
                entry = link_map.get(key)
                url = m.group(0)
                if entry is None:
                    unresolved.append({"url": url, "file": chapter.name,
                                     "line": lineno})
                    continue
                candidates_local += 1
                target = local_target(entry)
                file_replacements += 1
                replaced.append({"file": chapter.name, "line": lineno,
                               "old": url, "new": target})
                new_text = new_text.replace(url, target)
        if file_replacements and apply:
            chapter.write_text(new_text, encoding="utf-8")
        if file_replacements:
            files += 1
        replacements += file_replacements

    return {
        "applied": bool(apply),
        "files": files,
        "replacements": replacements,
        "candidates": candidates,
        "candidates_local": candidates_local,
        "replacements_list": replaced,
        "unresolved": unresolved,
        "dupes": link_map.get(DUPES_KEY, []),
        "link_map_size": len([k for k in link_map if k != DUPES_KEY]),
    }
