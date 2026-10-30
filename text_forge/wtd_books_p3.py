"""p3-references: `text/p3-references.md` generator (Книги как фундамент).

Extracted verbatim from `text_forge.wtd_books` (batch 5A of the livelib-migration
refactor) so that book-note generation and bibliography projection live apart.
The page is a PROJECTION of the note-books, never a source: `important: true` +
`weight:` choose the books, the book's own LiveLib review (or a curated line)
supplies the thesis, and the note's own ids give the link target.

Import shape: this module owns `_link_key`, the template constants and the
parsing/projection functions, and needs `_book_id`/`_review_id` from
`wtd_books`, which re-exports this module's symbols at its bottom — a cycle.
So nothing is imported from `wtd_books` at module level (that would fail when
this module is imported first); the two helpers are fetched from the module
registry at CALL time, when `wtd_books` is fully loaded in either order.
"""

import json
import pathlib
import re

# ------------------------------------------------------------------ p3-references
#
# text/p3-references.md is a PROJECTION, not a source:
#   importance   -> book frontmatter (`important: true` + `weight: <line number>`)
#   thesis       -> title of the book's own LiveLib review
#   link text    -> the book note's frontmatter title
#   link target  -> short canonical livelib URL of that very note
#
# Curated review target: when a line links /review/<R> and that link resolves to
# a note WITHOUT a usable review of its own (no `livelib_review`, or one the
# export says belongs to another work), the bullet keeps /review/<R>. The link is
# what the author wrote, the reader lands on the review the line's thesis comes
# from, and the id stays resolvable via _curation/link-mappings.json. A note that
# CAN cite its own review still wins: the curated url is then the stale one and
# gets normalized to the note's ids (a /book/ link never becomes a /review/).
#
# The generator NEVER invents a thesis: when neither the review nor the curated
# line offers one, the bullet is emitted without the `thesis: ` prefix and the
# book is reported in `warnings`.
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
P3_INTRO = ("В тексте были использованы упоминания и выдержки из книг, которые "
            "особенно запомнились или были прочитаны во время написания:")


def p3_header() -> str:
    """The whole page head: closed frontmatter, H1 and intro, trailing blank line."""
    return f"{P3_FRONTMATTER}\n# {P3_TITLE}\n\n{P3_INTRO}\n"


REF_BULLET = re.compile(r"^- (?P<body>.*\S)\s*$")
REF_LINK = re.compile(r"\[(?P<name>[^\]]*)\]\((?P<url>https?://(?:www\.)?livelib\.ru/"
                      r"(?P<kind>book|work|review)/(?P<id>\d+)[^)]*)\)")
# /work/<id> -> slug: only work ids that appear in NO note frontmatter (the
# curated link points at the 'all editions' page while our note is an edition).
WORK_ID_TO_SLUG = {
    "1008288064": "andreev-model-kolichestvennoy-otsenki-urovnya-schastya",
    "1001474484": "vayl-rodnaya-rech",
}


def _link_key(url: str) -> tuple[str, str] | None:
    """(kind, id) of a livelib URL, or None when it is not a livelib link."""
    m = re.match(r"https?://(?:www\.)?livelib\.ru/(book|work|review)/(\d+)", url)
    return (m.group(1), m.group(2)) if m else None


def parse_reference_lines(md: str, mappings: dict | None = None) -> list[dict]:
    """Parse curated bibliography bullets into {thesis, weight, links, raw, plain}.

    weight is the 1-based number of the bullet line — frontmatter, headings and
    prose do not shift it. `mappings` maps legacy livelib URLs to note slugs
    (text/books/_curation/link-mappings.json), matched by id and kind so the
    slug suffix of the URL does not matter.
    """
    mappings = mappings or {}
    mapped_by_key = {}
    for url, slug in mappings.items():
        # accept any url shape (short, slug-suffixed, /work/) — a curated link
        # names a work by its id, and only the id is trustworthy
        key = _link_key(url)
        if key:
            mapped_by_key[key] = slug

    lines = []
    for line in md.splitlines():
        m = REF_BULLET.match(line)
        if not m:
            continue
        body = m.group("body")
        links = []
        for lm in REF_LINK.finditer(body):
            kind, rid = lm.group("kind"), lm.group("id")
            links.append({
                "name": lm.group("name"),
                # canonical short form: a link resolves by id, so the slug suffix
                # of the written url is not part of the match
                "url": f"https://www.livelib.ru/{kind}/{rid}",
                "kind": kind,
                "book_id": "" if kind == "review" else rid,
                "review_id": rid if kind == "review" else "",
                "slug": mapped_by_key.get((kind, rid), ""),
            })
        if not links:
            continue
        # text left after dropping the links: 'thesis: , leftovers'; separators
        # between links belong to the links, not to the prose
        residue = REF_LINK.sub("", body)
        thesis = residue.split(":", 1)[0].strip(" ,")
        if not thesis or len(thesis.split()) < 2:
            thesis = ""  # no 'thesis: ' prefix on this line
        lines.append({
            "thesis": thesis,
            "weight": len(lines) + 1,
            "links": links,
            "raw": line,
            "plain": re.sub(r"^.*?:\s*", "", residue, count=1 if ":" in residue else 0).strip(" ,"),
        })
    return lines


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


def important_books(books_dir) -> list[dict]:
    """Note-books marked `important: true`, ordered by `weight` (then by slug)."""
    out = []
    for note in sorted(pathlib.Path(books_dir).glob("*.md")):
        m = re.match(r"---\n(.*?)\n---", note.read_text(encoding="utf-8"), re.DOTALL)
        if not m:
            continue
        fm = m.group(1)
        if (_fm_scalar(fm, "important") or "").lower() not in ("true", "yes"):
            continue
        weight = _fm_scalar(fm, "weight")
        book_url = _fm_scalar(fm, "livelib_book") or ""
        review_url = _fm_scalar(fm, "livelib_review") or ""
        out.append({
            "slug": note.stem,
            "title": _fm_scalar(fm, "title") or note.stem,
            # no weight => the note matters but was never placed in the list
            "weight": int(weight) if weight and weight.isdigit() else None,
            "book_id": _book_id(book_url) if book_url else "",
            "review_id": _review_id(review_url),
            "edition_ids": {m2.group(1) for m2 in re.finditer(
                r'^\s*-\s*"?https?://(?:www\.)?livelib\.ru/(?:book|work)/(\d+)', fm, re.MULTILINE)},
        })
    out.sort(key=lambda b: (b["weight"] is None, b["weight"] or 0, b["slug"]))
    return out


def _work_key(key: str) -> str:
    """A /work/ id names the same work as the note's /book/ id."""
    return "book/" + key.split("/", 1)[1] if key.startswith("work/") else key


def link_map_from_notes(books_dir) -> dict:
    """`<kind>/<id>` -> `/books/<slug>/` for every id a note declares.

    The generator's own view of the map (it resolves ids it already parsed, and
    needs no anchor): the note's book id, its edition ids and its review id all
    name the same local page. Deterministic — notes are read in sorted order and
    the first declaration of an id wins.

    EVERY note is keyed, not only the important ones: a shelf list names books
    the Text does not cite, and a chapter linking one must still land on its
    page. An id keys only the kind it really is (a review id stays a review key)
    — the same digits can name different works in different kinds.
    """
    out: dict[str, str] = {}
    for b in _all_notes(books_dir):
        target = f"/books/{b['slug']}/"
        if b["book_id"].isdigit():
            out.setdefault(f"book/{b['book_id']}", target)
        if b["review_id"].isdigit():
            out.setdefault(f"review/{b['review_id']}", target)
        for eid in b["edition_ids"]:
            if eid.isdigit():
                out.setdefault(f"book/{eid}", target)
    return out


def _key_of(link) -> str:
    """`<kind>/<id>` of a curated link dict or a plain URL (work -> book)."""
    url = link["url"] if isinstance(link, dict) else str(link)
    key = _link_key(url)
    return _work_key(f"{key[0]}/{key[1]}") if key else ""


# the collapsed shelf lists under the bibliography: LiveLib shelf name -> the
# frontmatter `status:` value, in the order the sections are rendered
STATUS_SECTIONS = (("Читаю", "reading"), ("Прочтённые", "read"),
                   ("Недочитанные", "unread"), ("Хочу прочитать", "wish"))


def render_status_sections(books_dir) -> tuple[str, list[dict]]:
    """Collapsed per-shelf lists of the note-books, from frontmatter `status:`.

    Returns (text, warnings). A book with `status: none` or no `status:` at all
    belongs to no shelf and is NOT rendered — and is reported once per book, so
    an unread shelf that lost a book is visible instead of silently shorter.
    Titles sort alphabetically, case-folded and with punctuation pushed aside:
    Cyrillic order must read like a dictionary, not like byte order.
    """
    shelves: dict[str, list[tuple[str, str]]] = {status: [] for _, status in STATUS_SECTIONS}
    warnings: list[dict] = []
    for b in _all_notes(books_dir):
        status = b["status"]
        # `status: none` is an EXPLICIT statement — the book is on no shelf, and
        # that is not an anomaly worth reporting. Only a note that carries no
        # `status:` key at all is the exception a human should look at.
        if status == "none":
            continue
        if status not in shelves:
            warnings.append({"slug": b["slug"], "reason": "no status", "weight": b["weight"],
                            "title": b["title"], "review_id": b["review_id"] or None,
                            "url": f"https://www.livelib.ru/book/{b['book_id']}"
                            if b["book_id"] else None})
            continue
        shelves[status].append((b["title"], f"/books/{b['slug']}/"))

    blocks: list[str] = []
    for heading, status in STATUS_SECTIONS:
        entries = shelves[status]
        if not entries:
            continue
        entries.sort(key=lambda t: _sort_key(t[0]))
        blocks.append("\n".join(
            [f"/// details | {heading} ({len(entries)})"]
            + [f"- [{title}]({target})" for title, target in entries]
            + ["///"]))
    text = "\n\n".join(blocks) + "\n" if blocks else ""
    warnings.sort(key=lambda w: w["slug"] or "")
    return text, warnings


def _sort_key(title: str) -> list:
    """Alphabetical key: case-folded, letters and digits only.

    `"Яблоко"` vs `"Ярмо"` must order by their letters, so a space or a quote
    sitting between them cannot decide the comparison.
    """
    return [c for c in title.casefold() if c.isalnum()]


def _all_notes(books_dir) -> list[dict]:
    """Every note-book, with the fields the shelf lists need (status included).

    Same frontmatter reading as `important_books`, minus the importance filter —
    a shelf lists every book the reader has, not only the ones the Text cites.
    `status` is None (not 'none') when the note carries no `status:` key: the
    generator must tell "I am on no shelf" from "I never said anything".
    """
    out: list[dict] = []
    for note in sorted(pathlib.Path(books_dir).glob("*.md")):
        m = re.match(r"---\n(.*?)\n---", note.read_text(encoding="utf-8"), re.DOTALL)
        if not m:
            continue
        fm = m.group(1)
        raw_status = _fm_scalar(fm, "status")
        out.append({
            "slug": note.stem,
            "title": _fm_scalar(fm, "title") or note.stem,
            "status": raw_status.lower() if raw_status else None,
            "weight": None,
            "book_id": _book_id(_fm_scalar(fm, "livelib_book") or ""),
            "review_id": _review_id(_fm_scalar(fm, "livelib_review") or ""),
            # a shelf lists every edition of the note, so a chapter citing any of
            # them lands on this page
            "edition_ids": {m2.group(1) for m2 in re.finditer(
                r'^\s*-\s*"?https?://(?:www\.)?livelib\.ru/(?:book|work)/(\d+)', fm,
                re.MULTILINE)},
        })
    return out


def render_p3_references(books_dir, reviews: list[dict], *, lines: list[dict] | None = None,
                        line_thesis: dict | None = None,
                        link_map: dict | None = None) -> dict:
    """Project `important` books into the p3-references page.

    The returned `text` is the WHOLE page: closed frontmatter, `# {P3_TITLE}`, the
    intro line and the bullets — all from this module's template constants, so a
    no-argument call already produces a valid file. `items` holds the bullets
    only (no header).

    lines — curated bullets from parse_reference_lines(): they define grouping
    (books sharing a weight stay consecutive) and provide the thesis for books
    whose LiveLib review carries no title. line_thesis ({slug: thesis}) supplies
    the same fallback for callers that pass no lines. Without either, every
    important book becomes its own line, thesis taken from its review only.

    Targets are LOCAL: a bullet links the note's own page (`/books/<slug>/`),
    resolved through `link_map` (`<kind>/<id>` -> `/books/<slug>/`, derived from
    the notes when not handed in). A target that resolves to no note keeps its
    livelib.ru URL and is reported with reason 'no local note' — the reader can
    still follow it, and the gap is visible. Link TEXT never changes.

    Below the bullets, collapsed shelf lists from the notes' `status:`
    (render_status_sections).

    Returns {"text", "items", "warnings"}; a warning is {"slug", "reason", ...}
    with reason 'no-thesis' (line emitted without a thesis), 'untitled-review'
    (review exists but carries no title, so the curated line's thesis was used),
    'foreign-review' (the note's review belongs to a different work),
    'unmatched-link' / 'no local note' (a curated link resolves to no note, so
    the bullet keeps the livelib.ru URL it was written with) or 'no status'
    (a book belongs to no shelf list).
    """
    if link_map is None:
        link_map = link_map_from_notes(books_dir)
    books = important_books(books_dir)
    by_slug = {b["slug"]: b for b in books}
    by_review = {b["review_id"]: b for b in books if b["review_id"]}
    by_book: dict[str, dict] = {}
    for b in books:
        if b["book_id"]:
            by_book.setdefault(b["book_id"], b)
        for eid in b["edition_ids"]:
            by_book.setdefault(eid, b)
    review_by_id = {str(r["id"]): r for r in reviews}
    # review ids a note declares as its own: a review may only be cited by the
    # note that owns it (see 'curated review target' in the header comment)
    declared_reviews = {b["review_id"] for b in books if b["review_id"]}
    line_thesis = line_thesis or {}
    warnings: list[dict] = []
    items: list[tuple[int, int, str]] = []

    def warn(slug, reason, weight, title, review_id=None, url=None):
        warnings.append({"slug": slug, "reason": reason, "weight": weight,
                        "title": title, "review_id": review_id, "url": url})

    def resolve(link: dict) -> dict | None:
        """Curated link -> note: mapping slug, then review id, then edition id.

        A /review/ link is keyed by the review id: a review belongs to one
        edition, so this finds the note even when the curated URL names a
        different edition or a collection. /work/ ids that live in no note fall
        back to WORK_ID_TO_SLUG; anything else stays unmatched.
        """
        if link["slug"] and link["slug"] in by_slug:
            return by_slug[link["slug"]]
        if link["review_id"] and link["review_id"] in by_review:
            return by_review[link["review_id"]]
        if link["book_id"] and link["book_id"] in by_book:
            return by_book[link["book_id"]]
        if link["kind"] == "work":
            for candidate in (link["book_id"], link["review_id"]):
                if candidate in WORK_ID_TO_SLUG and WORK_ID_TO_SLUG[candidate] in by_slug:
                    return by_slug[WORK_ID_TO_SLUG[candidate]]
        return None

    def note_review(book: dict) -> dict | None:
        """The note's own review as recorded in the export, else None.

        A review belongs to one edition: if the export says it is about another
        work, it cannot supply this book's thesis (the case is reported as
        'foreign-review'). A review id the export does not carry is simply
        unknown — reported once by the caller that needed it.
        """
        if not book["review_id"]:
            return None
        review = review_by_id.get(book["review_id"])
        if review is None:
            return None
        target = _book_id((review.get("art_edition") or {}).get("url") or "")
        if target and target not in {book["book_id"], *book["edition_ids"]}:
            warn(book["slug"], "foreign-review", book["weight"], book["title"],
                 review_id=book["review_id"])
            return None
        return review

    def emit(book: dict, thesis: str, weight: int, order: int, link: dict | None = None) -> None:
        review = note_review(book)
        if review is not None and (review.get("title") or "").strip():
            text, reason = review["title"].strip(), None
        elif thesis or line_thesis.get(book["slug"]):
            text, reason = (thesis or line_thesis[book["slug"]]), "untitled-review"
        else:
            text, reason = "", "no-thesis"
        if reason:
            warn(book["slug"], reason, weight, book["title"], book["review_id"] or None)
        # short canonical URL: the note's own review when it has one, else the
        # note's book id — unless the curated link already pointed at a review
        # and this note has nothing of its own to cite, in which case the
        # curated target stays (see 'curated review target' in the header)
        if review:
            url = f"https://www.livelib.ru/review/{book['review_id']}"
        elif (link is not None and link["kind"] == "review" and link["review_id"]
                and link["review_id"] in review_by_id
                # a review is cited by the note that DECLARES it: another note must
                # not send the reader to a sibling shelf entry and still claim the
                # line's thesis as its own source
                and link["review_id"] not in declared_reviews - {book["review_id"]}):
            # keep the target the author wrote: the reader lands on the resource
            # the line's thesis refers to. Only its ID is kept — the note may not
            # cite that review, so the thesis still comes from the line itself
            url = f"https://www.livelib.ru/review/{link['review_id']}"
        else:
            # nothing to cite: the note's own book id, never a stranger's review
            url = f"https://www.livelib.ru/book/{book['book_id']}"
        # the note's page is what the reader should get; the livelib URL above is
        # only the fallback for a note the map does not carry (a slug collision,
        # a note that is not on disk) — then the gap is reported, not hidden
        local = link_map.get(_key_of(url)) or link_map.get(f"book/{book['book_id']}")
        if local:
            url = local
        else:
            warn(book["slug"], "no local note", weight, book["title"],
                 book["review_id"] or None, url=url)
        link = f"[{book['title']}]({url})"
        items.append((weight, order, f"- {text}: {link}" if text else f"- {link}"))

    if lines is None:
        for order, b in enumerate(books):
            emit(b, "", b["weight"], order)
    else:
        # curated grouping: a bullet's links keep their order and share its
        # weight, so a multi-book line emits one line per book
        for ln in lines:
            weight = ln["weight"]
            known = [(link, resolve(link)) for link in ln["links"]]
            if all(book is None for _, book in known):
                # nothing in this line resolves: keep the curated line verbatim
                # — that IS a livelib target left on the page, so it is reported
                # under the reason the validator looks for, once per link
                for link in ln["links"]:
                    warn(None, "no local note", weight, link["name"], url=link["url"])
                items.append((weight, len(items), ln["raw"]))
                continue
            for link, book in known:
                if link["review_id"] and link["review_id"] not in review_by_id and book is not None:
                    warn(book["slug"], "unknown-review", weight, book["title"],
                         review_id=link["review_id"])
            for link, book in known:
                if book is None:
                    # the curated link names nothing in the corpus: keep it verbatim
                    warn(None, "no local note", weight, link["name"], url=link["url"])
                    items.append((weight, len(items),
                                f"- {ln['thesis']}: [{link['name']}]({link['url']})"
                                if ln["thesis"] else f"- [{link['name']}]({link['url']})"))
                    continue
                emit(book, ln["thesis"], weight, len(items), link)
            if ln["plain"].strip(", :"):
                # 'to be published' style leftovers stay in the line, unlinked
                w, o, text = items[-1]
                items[-1] = (w, o, f"{text}, {ln['plain'].strip().lstrip(',').strip()}")
    items.sort(key=lambda t: (t[0] is None, t[0] or 0, t[1]))
    text = p3_header()
    if items:
        text += "\n" + "\n".join(t for _, _, t in items) + "\n"
    # the shelf lists sit after the bibliography: the page first names what the
    # Text stands on, then shows what the reader has on each shelf
    shelves, shelf_warnings = render_status_sections(books_dir)
    warnings.extend(shelf_warnings)
    if shelves:
        text += "\n" + shelves
    warnings.sort(key=lambda w: (w.get("weight") or 0, w.get("slug") or "", w.get("url") or ""))
    return {"text": text, "items": [t for _, _, t in items],
            # the generator's own id -> page map, so a caller can hand it to the
            # rewriter/validator without a second read of the notes
            "link_map": link_map, "warnings": warnings}
