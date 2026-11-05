"""p3-references: `text/p3-references.md` generator (Книги как фундамент).

The page is a PROJECTION, generated FROM SCRATCH on every build: the generator
never reads the page it wrote. One data flow —

    LiveLib export (reviews) + curation weights (note frontmatter `weight`)
      -> one bullet per important book, ordered by weight
      -> plus the collapsed shelf lists (`/// details`) below

Bullet contract: `- {thesis}: [{note title}](books/{slug}.md)` where thesis is
the book's OWN review title from the export, link text is the note's
frontmatter title, and the target is the note's own local page. A review with
no title (or no review at all) emits the bullet WITHOUT the thesis prefix and
warns 'untitled-review'. The generator NEVER invents a thesis and never cites a
stranger's review: a review the export attributes to another work is not used
(reported 'foreign-review'). Because the page is written from scratch, it also
cannot carry a line about a book that is not on disk — the whole read-back
machinery (curated-line parsing, link resolution, verbatim fallbacks) is gone.

A shelf line names the author beside the title when the note declares one
(`- [{title} — {author}](books/{slug}.md)`), and shelf lines order by SLUG —
the slug starts with the author's surname, so a shelf reads grouped by author.

Import shape: this module needs `_book_id`/`_review_id` from `wtd_books`, which
re-exports this module's symbols at its bottom — a cycle. So nothing is
imported from `wtd_books` at module level (that would fail when this module is
imported first); the two helpers are fetched from the module registry at CALL
time, when `wtd_books` is fully loaded in either order.
"""

import json
import pathlib
import re

# The local-target producer lives in `text_forge.wtd_links` and is fetched at
# CALL time (see `_local_target`): `wtd_links` imports `_link_key` from this
# module, so a module-level import in both directions is a hard cycle that dies
# on whichever of the two gets imported first.

# ------------------------------------------------------------------ p3-references
#
# text/p3-references.md is a PROJECTION, not a source:
#   importance   -> book frontmatter (`important: true` + `weight: <n>`)
#   thesis       -> title of the book's own LiveLib review
#   link text    -> the book note's frontmatter title
#   link target  -> that very note's own page, `books/<slug>.md`
#
# The page's own words (frontmatter, title, intro) belong to THIS template, not
# to a legacy file: a caller that hands in a `header=` carved out of the old
# file can truncate it (and one did — the closing `---`, the heading and the
# intro paragraph were lost). Emitting the whole page from versioned constants
# makes the output correct by construction.

P3_FRONTMATTER = (
    "---\n"
    "comments: true\n"
    "created: 18.06.2023\n"
    "published: 22.10.2023\n"
    "description: Наш Текст — это сборка смыслов, взятых из книг "
    "и успешно применяемых на практике.\n"
    "---\n"
)
P3_TITLE = "Книги как фундамент"
P3_INTRO = (
    "В тексте были использованы упоминания и выдержки из книг, которые "
    "особенно запомнились или были прочитаны во время написания:"
)


def p3_header() -> str:
    """The whole page head: closed frontmatter, H1 and intro, trailing blank line."""
    return f"{P3_FRONTMATTER}\n# {P3_TITLE}\n\n{P3_INTRO}\n"


def _link_key(url: str) -> tuple[str, str] | None:
    """(kind, id) of a livelib URL, or None when it is not a livelib link."""
    m = re.match(r"https?://(?:www\.)?livelib\.ru/(book|work|review)/(\d+)", url)
    return (m.group(1), m.group(2)) if m else None


def _fm_scalar(fm: str, key: str) -> str | None:
    """Scalar value of a frontmatter key ('' for `key:` with no value).

    Quoted values are JSON-unescaped, so `\\"` inside titles survives
    frontmatter round-trips without leaking backslashes into output.
    """
    m = re.search(rf"^{key}:[ \t]*(.*?)[ \t]*$", fm, re.MULTILINE)
    if not m:
        return None
    raw = m.group(1)
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    return raw


def _book_id(url: str) -> str:
    from text_forge.wtd_books import _book_id as _impl

    return _impl(url)


def _review_id(url: str) -> str:
    from text_forge.wtd_books import _review_id as _impl

    return _impl(url)


def _local_target(entry: dict) -> str:
    """The canonical relative target (`books/<slug>.md`) for one note.

    `text_forge.wtd_links.local_target` is the ONE producer of that shape, so the
    bullets, the shelf lines and the id->page map this module emits cannot drift
    from what the rewriter writes. Fetched at CALL time rather than imported at
    module level, for the reason named at the top of this file.

    An entry carrying an `anchor` (a quote-level key) yields `…#quote_N`.
    """
    from text_forge.wtd_links import local_target as _impl

    return _impl(entry)


def _author_valid(author: str) -> bool:
    """True when the author string holds a surname-like token.

    The very check the note builder uses for its `author:` frontmatter, so a
    rating sitting in the author field ('4,6') or a run of initials ('А. Ф.') is
    no name here either. Fetched from `wtd_books` at CALL time for the same
    reason as `_book_id`/`_review_id` (the two modules import cyclically).
    """
    from text_forge.wtd_books import _author_valid as _impl

    return _impl(author)


def _read_note(note: pathlib.Path) -> dict | None:
    """One note-book's frontmatter -> the record the projection/shelves need.

    None when the file carries no frontmatter block at all. `status` is None
    (not 'none') when the note declares no `status:` key: the generator must
    tell "I am on no shelf" from "I never said anything". `weight` is None for
    a note that is not `important` (or carries no `weight:`).
    """
    m = re.match(r"---\n(.*?)\n---", note.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    raw_status = _fm_scalar(fm, "status")
    book_url = _fm_scalar(fm, "livelib_book") or ""
    review_url = _fm_scalar(fm, "livelib_review") or ""
    weight = _fm_scalar(fm, "weight")
    author = (_fm_scalar(fm, "author") or "").strip()
    return {
        "slug": note.stem,
        "title": _fm_scalar(fm, "title") or note.stem,
        # the note's own page, computed ONCE by the canonical producer: bullets,
        # shelf lines and the id->page map all read this field, so the shapes
        # cannot drift apart inside one build
        "page": _local_target({"slug": note.stem, "anchor": None}),
        # the author the note DECLARES (the build already reduced a multi-author
        # export record to the one the note is named after): a shelf line prints
        # it beside the title, and no valid name means no author segment
        "author": author if _author_valid(author) else "",
        "status": raw_status.lower() if raw_status else None,
        "important": (_fm_scalar(fm, "important") or "").lower() in ("true", "yes"),
        # no weight => the note matters but was never placed in the list
        "weight": int(weight) if weight and weight.isdigit() else None,
        "book_id": _book_id(book_url) if book_url else "",
        "review_id": _review_id(review_url),
        # a shelf lists every edition of the note, so a chapter citing any of
        # them lands on this page
        "edition_ids": {
            m2.group(1)
            for m2 in re.finditer(
                r'^\s*-\s*"?https?://(?:www\.)?livelib\.ru/(?:book|work)/(\d+)',
                fm,
                re.MULTILINE,
            )
        },
    }


def _all_notes(books_dir) -> list[dict]:
    """Every note-book on disk, in sorted-file order."""
    out: list[dict] = []
    for note in sorted(pathlib.Path(books_dir).glob("*.md")):
        b = _read_note(note)
        if b is not None:
            out.append(b)
    return out


def important_books(books_dir) -> list[dict]:
    """Note-books marked `important: true`, ordered by `weight` (then by slug)."""
    books = [b for b in _all_notes(books_dir) if b["important"]]
    books.sort(key=lambda b: (b["weight"] is None, b["weight"] or 0, b["slug"]))
    return books


# the collapsed shelf lists under the bibliography: LiveLib shelf name -> the
# frontmatter `status:` value, in the order the sections are rendered. The
# shelf NAME is the same wording a book page prints under `Полка:`, so
# this tuple is the single source of truth for both renderings.
STATUS_SECTIONS = (
    ("Читаю", "reading"),
    ("Хочу прочитать", "wish"),
    ("Прочтённые", "read"),
    ("Недочитанные", "unread"),
)


def render_status_sections(books_dir) -> tuple[str, list[dict]]:
    """Collapsed per-shelf lists of the note-books, from frontmatter `status:`.

    Returns (text, warnings). A book with `status: none` or no `status:` at all
    belongs to no shelf and is NOT rendered — and is reported once per book, so
    an unread shelf that lost a book is visible instead of silently shorter.
    Lines order by slug (the page target `books/<slug>.md`), so an author's
    books sit together: the slug starts with the surname. A line prints that
    author FIRST (`- [Author — Title](target)`), so a shelf reads by name; a
    note with no valid author prints its title alone, never a dangling dash.
    """
    shelves: dict[str, list[tuple[str, str, str]]] = {
        status: [] for _, status in STATUS_SECTIONS
    }
    warnings: list[dict] = []
    for b in _all_notes(books_dir):
        status = b["status"]
        # `status: none` is an EXPLICIT statement — the book is on no shelf, and
        # that is not an anomaly worth reporting. Only a note that carries no
        # `status:` key at all is the exception a human should look at.
        if status == "none":
            continue
        if status not in shelves:
            warnings.append(
                {
                    "slug": b["slug"],
                    "reason": "no status",
                    "weight": b["weight"],
                    "title": b["title"],
                    "review_id": b["review_id"] or None,
                    "url": f"https://www.livelib.ru/book/{b['book_id']}"
                    if b["book_id"]
                    else None,
                }
            )
            continue
        shelves[status].append((b["title"], b["author"], b["page"]))

    blocks: list[str] = []
    for heading, status in STATUS_SECTIONS:
        entries = shelves[status]
        if not entries:
            continue
        # sort by the PAGE (books/<slug>.md ≡ slug order): the slug starts with
        # the author's surname, so a shelf reads grouped by author
        entries.sort(key=lambda t: t[2])
        blocks.append(
            "\n".join(
                [f"/// details | {heading} ({len(entries)})"]
                + [f"- [{author} — {title}]({target})" if author
                   else f"- [{title}]({target})"
                   for title, author, target in entries]
                + ["///"]
            )
        )
    text = "\n\n".join(blocks) + "\n" if blocks else ""
    warnings.sort(key=lambda w: w["slug"] or "")
    return text, warnings


def render_p3_references(books_dir, reviews: list[dict]) -> dict:
    """Project the `important` note-books into the whole p3-references page.

    One bullet per important book, in the notes' weight order: thesis = the
    title of the book's OWN review in the export, link text = the note's
    frontmatter title, target = the note's own page `books/<slug>.md`. A review
    with no title (or no review at all) emits the bullet WITHOUT the thesis
    prefix and warns 'untitled-review'; a review the export attributes to
    another work is not used for the thesis ('foreign-review') — the generator
    never borrows a thesis from a stranger. Nothing else is ever cited: the
    page is written from scratch, so it cannot carry a line about a book that
    is not on disk.

    Below the bullets, collapsed shelf lists from the notes' `status:`
    (render_status_sections).

    Returns {"text", "items", "link_map", "warnings"}; `items` holds the bullets
    only (no header), `link_map` is the corpus's own `<kind>/<id>` ->
    `/books/<slug>/` map (every note keys its own page by its book id, review
    id and edition ids — handed to the caller for the rewriter/validator, the
    renderer itself needs no map: its targets are the notes it read), and a
    warning is {"slug", "reason", "weight", ...} with reason 'untitled-review' /
    'foreign-review' / 'no status'.
    """
    notes = _all_notes(books_dir)
    review_by_id = {str(r["id"]): r for r in reviews}

    items: list[str] = []
    warnings: list[dict] = []
    for b in important_books(books_dir):
        review = review_by_id.get(b["review_id"]) if b["review_id"] else None
        if review is not None:
            # a review belongs to one edition: if the export says it is about
            # another work, it cannot supply this book's thesis
            target = _book_id((review.get("art_edition") or {}).get("url") or "")
            if target and target not in {b["book_id"], *b["edition_ids"]}:
                warnings.append(
                    {
                        "slug": b["slug"],
                        "reason": "foreign-review",
                        "weight": b["weight"],
                        "title": b["title"],
                        "review_id": b["review_id"],
                        "url": None,
                    }
                )
                review = None
        thesis = (review.get("title") or "").strip() if review else ""
        if review is not None and not thesis:
            warnings.append(
                {
                    "slug": b["slug"],
                    "reason": "untitled-review",
                    "weight": b["weight"],
                    "title": b["title"],
                    "review_id": b["review_id"],
                    "url": None,
                }
            )
        # the bullet's link text stays the TITLE: the author belongs to the
        # shelf lists, not to the bibliography line
        items.append(
            f"- {thesis}: [{b['title']}]({b['page']})"
            if thesis
            else f"- [{b['title']}]({b['page']})"
        )

    text = p3_header()
    if items:
        text += "\n" + "\n".join(items) + "\n"
    # the shelf lists sit after the bibliography: the page first names what the
    # Text stands on, then shows what the reader has on each shelf
    shelves, shelf_warnings = render_status_sections(books_dir)
    warnings.extend(shelf_warnings)
    if shelves:
        text += "\n" + shelves
    warnings.sort(key=lambda w: (w.get("weight") or 0, w.get("slug") or ""))

    # the caller's id -> page map, so the rewriter/validator need no second read
    # of the notes: a page is reached by the livelib ids its note declares (the
    # shape link-map.json carries). Values are `local_target`'s canonical relative
    # form, so the bullets above, this map and the rewriter name one address.
    # Not used by the renderer itself — its targets are the very notes it read.
    link_map: dict[str, str] = {}
    for b in notes:
        target = b["page"]
        if b["book_id"].isdigit():
            link_map.setdefault(f"book/{b['book_id']}", target)
        if b["review_id"].isdigit():
            link_map.setdefault(f"review/{b['review_id']}", target)
        for eid in b["edition_ids"]:
            if eid.isdigit():
                link_map.setdefault(f"book/{eid}", target)
    return {"text": text, "items": items, "link_map": link_map, "warnings": warnings}
