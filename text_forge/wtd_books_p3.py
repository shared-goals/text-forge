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


def render_p3_references(books_dir, reviews: list[dict], *, lines: list[dict] | None = None,
                        line_thesis: dict | None = None) -> dict:
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

    Returns {"text", "items", "warnings"}; a warning is {"slug", "reason", ...}
    with reason 'no-thesis' (line emitted without a thesis), 'untitled-review'
    (review exists but carries no title, so the curated line's thesis was used),
    'foreign-review' (the note's review belongs to a different work) or
    'unmatched-link' (a curated link resolves to no note: kept verbatim).
    """
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
                for link in ln["links"]:
                    warn(None, "unmatched-link", weight, link["name"], url=link["url"])
                items.append((weight, len(items), ln["raw"]))
                continue
            for link, book in known:
                if link["review_id"] and link["review_id"] not in review_by_id and book is not None:
                    warn(book["slug"], "unknown-review", weight, book["title"],
                         review_id=link["review_id"])
            for link, book in known:
                if book is None:
                    # the curated link names nothing in the corpus: keep it verbatim
                    warn(None, "unmatched-link", weight, link["name"], url=link["url"])
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
    warnings.sort(key=lambda w: (w.get("weight") or 0, w.get("slug") or "", w.get("url") or ""))
    text = p3_header()
    if items:
        text += "\n" + "\n".join(t for _, _, t in items) + "\n"
    return {"text": text, "items": [t for _, _, t in items], "warnings": warnings}
