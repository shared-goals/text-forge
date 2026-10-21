"""wtd-books: LiveLib JSON export -> books/<slug>.md note-books.

Design (agreed 2026-10-19):
- books/<slug>.md note-books are the single source of truth.
- Quotes live INSIDE book notes as headings with ^quote_N anchors.
- Review lives as a section with #review anchor.
- LiveLib URLs are attributes of our entries, never link targets.
"""

import json
import pathlib
import re

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum() or ch == " "):
            out.append(ch)
        # everything else (punctuation, quotes, dashes) is dropped
    return "".join(out)


def _slug_word(text: str) -> str:
    return "-".join(w for w in translit(text).split() if w)


def _main_title(title: str) -> str:
    """First part of title containing at least two real words (initials skipped)."""
    chunks = re.split(r"[:!?.(]", title)
    real = lambda s: [w for w in s.split() if len(w.strip(".")) > 1]
    for i, chunk in enumerate(chunks):
        if len(real(chunk)) >= 2 or i == len(chunks) - 1:
            return " ".join(c for c in chunks[: i + 1]).strip() if i else chunk.strip()
    return title.strip()


def make_slug(title: str, author: str) -> str:
    """First author's surname + first meaningful part of title (author omitted if none)."""
    first_author = author.split(",")[0] if author else author
    return _slug_word(f"{_surname(first_author)} {_main_title(title)}".strip())


def _surname(author: str) -> str:
    """Last token that is neither an initial ('А.', 'А.Ф.') nor a digit ('5 Юрьев').

    Returns '' when no valid surname exists (digits-only author) — the slug then
    comes from the title alone.
    """
    for token in reversed(author.split()):
        if any(ch.isdigit() for ch in token):
            continue
        clean = token.strip(".")
        if len(clean) <= 1 or "." in token:
            continue
        return token
    return ""


def _book_id(url: str) -> str:
    """Numeric id from /book/<id> or /work/<id> (with or without slug)."""
    m = re.search(r"/(?:book|work)/(\d+)", url)
    return m.group(1) if m else url


def _review_id(url: str) -> str:
    """Numeric id from /review/<id> (with or without slug, relative or absolute)."""
    m = re.search(r"/review/(\d+)(?:-|$)", url)
    return m.group(1) if m else ""


def _work_key(title: str, author: str) -> str:
    """Normalization for matching editions of the same work.

    Full normalized title minus edition-info parts (тома, номера, «сборник»),
    NOT the main-title cut — different works sharing a prefix must not merge.
    """
    parts = re.split(r"[:!?.(]", title)
    keep = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.search(r"\d", p) or re.search(r"(?i)том|сборник|издани|комплект", p):
            continue
        keep.append(p)
    t = re.sub(r"[^\w\s]", " ", " ".join(keep).lower())
    t = re.sub(r"\s+", " ", t).strip()
    # first author's surname; stubborn name-order cases handled via work-merges.json
    surname = translit(_surname(author.split(",")[0])) if author else ""
    return f"{t}|{surname.lower()}"


def group_export(books: list[dict], quotes: list[dict], reviews: list[dict]) -> tuple[list[dict], list[dict]]:
    """Group LiveLib export records into per-book entries.

    Returns (entries, own_quotes): entries — one per shelf book with quotes/review
    merged (including other editions of the same work); own_quotes — quotes whose
    work matched no shelf book (they become their own notes).
    """
    reviews_by_book = {}
    for r in reviews:
        reviews_by_book.setdefault(_book_id(r["art_edition"]["url"]), r)

    entries = []
    for book in books:
        bid = _book_id(book["book_url"])
        entries.append({
            "book": book,
            "slug": make_slug(book["title"], book["author"]),
            "quotes": [],
            "review": reviews_by_book.get(bid),
            "_edition_ids": {bid},
        })

    # Merge shelf entries that are different editions of the same work into ONE note:
    # primary = the one with a review, else the one with the most own quotes, else first.
    merged: dict[str, list[dict]] = {}
    for e in entries:
        merged.setdefault(_work_key(e["book"]["title"], e["book"]["author"]), []).append(e)
    final = []
    for group in merged.values():
        primary = next((e for e in group if e["review"]), None) \
            or max(group, key=lambda e: len(e["quotes"])) if len(group) > 1 else group[0]
        for other in group:
            if other is not primary:
                primary["_edition_ids"] |= other["_edition_ids"]
                primary["book"].setdefault("_extra_urls", []).append(other["book"]["book_url"])
        final.append(primary)
    by_work = {_work_key(e["book"]["title"], e["book"]["author"]): e for e in final}

    own_entries = []
    for q in quotes:
        qid = _book_id(q["art_edition"]["url"])
        target = next((e for e in final if qid in e["_edition_ids"]), None)
        if target is None:
            target = by_work.get(_work_key(q["art_edition"]["title"],
                                           (q["art_edition"].get("authors") or [{}])[0].get("full_name", "")))
        if target is None:
            own_entries.append(q)
        else:
            target["quotes"].append(q)

    for e in final:
        e["quotes"].sort(key=lambda q: q["created_at"])
        # same quote may surface via several editions — keep one copy
        seen, uniq = set(), []
        for q in e["quotes"]:
            key = (q["text"], q["created_at"])
            if key not in seen:
                seen.add(key)
                uniq.append(q)
        e["quotes"] = uniq
        del e["_edition_ids"]
    final.sort(key=lambda e: e["slug"])
    return final, own_entries


def _strip_html(text: str) -> str:
    """HTML from trisolaris -> plain text paragraphs separated by blank lines."""
    text = re.sub(r"<br\s*/?>", "\n\n", text)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&laquo;", "«").replace("&raquo;", "»")
    text = text.replace("&amp;", "&").replace("&mdash;", "—")
    return text.strip()


def _blockquote(text: str, n: int) -> str:
    """Quote as blockquote, block-id on the last line (Obsidian anchors the block)."""
    lines = [f"> {line}".rstrip() for line in text.split("\n")]
    lines[-1] += f" ^quote_{n}"
    return "\n".join(lines)


def _author_valid(author: str) -> bool:
    """True when author string contains a surname-like token."""
    return bool(_surname(author))


def render_note(entry: dict) -> str:
    book = entry["book"]
    slug_url = book["book_url"]
    fm = [
        "---",
        # always double-quoted: bare scalars with ':' break Obsidian Bases YAML
        f'title: {json.dumps(book["title"], ensure_ascii=False)}',
    ]
    if _author_valid(book.get("author") or ""):
        author = book["author"].strip()
        # quote when the value carries YAML-hostile characters (trailing
        # spaces come straight from the LiveLib export)
        if (author != book["author"] or ":" in author or "#" in author
                or (author and author[0] in "!&*?|>%@`{}[]>,\"'")):
            author = json.dumps(author, ensure_ascii=False)
        fm.append(f"author: {author}")
    fm += [
        "tags:",
        "  - book",
    ]
    if book.get("my_mark") is not None:
        fm.append(f'my_mark: {book["my_mark"]}')
    # status is always written; books outside any shelf list get 'none'
    fm.append(f'status: {book.get("status") or "none"}')
    fm.append(f'livelib_book: "https://www.livelib.ru/book/{_book_id(slug_url)}"')
    extra = entry["book"].get("_extra_urls") or []
    if extra:
        fm.append("livelib_editions:")
        for u in extra:
            fm.append(f'  - "{u}"')
    if entry["review"]:
        rid = _review_id(entry["review"]["url"])
        if rid:
            fm.append(f'livelib_review: "https://www.livelib.ru/review/{rid}"')
    body = ["\n".join(fm), "---", ""]

    if entry["review"]:
        body += [
            "## Рецензия",
            "",
            _strip_html(entry["review"]["text"]),
            "",
        ]

    for n, q in enumerate(entry["quotes"], start=1):
        meta = q.get("quote") or {}
        qid = meta.get("quote_id") or (meta.get("url") or "").split("/quote/")[-1].split("-")[0]
        qurl = f"/quote/{qid}" if str(qid).isdigit() else None
        block = [_blockquote(_strip_html(q["text"]), n), ""]
        if qurl:
            block.append(f"— [LiveLib](https://www.livelib.ru{qurl})")
            block.append("")
        body += block
    return "\n".join(body).rstrip() + "\n"


def build_books(books_path, quotes_path, reviews_path, out_dir, collections_path=None,
                author_overrides_path=None, work_merges_path=None, link_mappings_path=None,
                book_overrides_path=None, reference_books_path=None) -> dict:
    """Build books/<slug>.md notes from LiveLib export JSON files.

    Editions listed in collections_path are omnibuses: their quotes violate the
    book-quote rule and are excluded (report: quotes_in_collections); their
    reviews are fine and stay. author_overrides_path maps book/edition URLs to
    manually curated author strings (LiveLib has editions without authors).
    """
    from pathlib import Path

    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    books = load(books_path)
    quotes = load(quotes_path)
    reviews = load(reviews_path)
    collections = load(collections_path) if collections_path else {}
    overrides = load(author_overrides_path) if author_overrides_path else {}
    # not-on-shelf editions are kept: text links need note targets even without quotes;
    # work-merge folds them into shelf notes when the work matches
    # apply manual author overrides by edition id (data-level, before grouping)
    ov_by_id = {_book_id(u): a for u, a in overrides.items()}
    # book-overrides: patch status/author/etc. for editions missing or stale on shelves
    book_ov = load(book_overrides_path) if book_overrides_path else {}
    # statuses pass through as LiveLib names; the export's synthetic marker means "no shelf"
    for b in books:
        bid = _book_id(b["book_url"])
        if bid in ov_by_id:
            b["author"] = ov_by_id[bid]
        if bid in book_ov:
            b.update(book_ov[bid])
        if b.get("status") == "not-on-shelf":
            b["status"] = None
    # reference books: works referenced from texts but absent from shelves and
    # quotes (former not-on-shelf stubs) — kept as status-none notes
    ref_books = load(reference_books_path) if reference_books_path else []
    known_ids = {_book_id(b["book_url"]) for b in books}
    books = books + [b for b in ref_books if _book_id(b["book_url"]) not in known_ids]
    for q in quotes:
        qid = _book_id(q["art_edition"]["url"])
        if qid in ov_by_id:
            q["art_edition"]["authors"] = [{"full_name": a} for a in ov_by_id[qid].split(", ")]
    omni_ids = {_book_id(u) for u in collections}
    placed_quotes = [q for q in quotes if _book_id(q["art_edition"]["url"]) not in omni_ids]
    in_collections = [q for q in quotes if _book_id(q["art_edition"]["url"]) in omni_ids]
    entries, own_quotes = group_export(books, placed_quotes, reviews)
    # omnibuses have no author metadata: collections, not authored books.
    # Match by exact full title or declared edition id — NOT by work key,
    # so individual works sharing the main title keep their authors.
    omni_full_titles = {re.split(r"\s*\(омнибус\)", v)[0].strip() for v in collections.values()}
    def _is_omnibus(title, url):
        return _book_id(url) in omni_ids or title.strip() in omni_full_titles
    for e in entries:
        if _is_omnibus(e["book"]["title"], e["book"]["book_url"]):
            e["book"]["author"] = ""
    for q in own_quotes:
        if _is_omnibus(q["art_edition"]["title"], q["art_edition"]["url"]):
            q["art_edition"]["authors"] = []
    # user-curated authors win over the omnibus strip
    for b in books:
        bid = _book_id(b["book_url"])
        if bid in ov_by_id:
            b["author"] = ov_by_id[bid]
    for q in quotes:
        qid = _book_id(q["art_edition"]["url"])
        if qid in ov_by_id:
            q["art_edition"]["authors"] = [{"full_name": a} for a in ov_by_id[qid].split(", ")]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Quotes whose work matched no shelf book -> one own entry per WORK.
    by_work_own: dict[str, list[dict]] = {}
    for q in own_quotes:
        ae = q["art_edition"]
        key = _work_key(ae["title"], (ae.get("authors") or [{}])[0].get("full_name", ""))
        by_work_own.setdefault(key, []).append(q)
    own_notes = 0
    for qs in by_work_own.values():
        ae = qs[0]["art_edition"]
        author = ", ".join(a["full_name"] for a in ae.get("authors") or [])
        book = {
            "book_url": "https://www.livelib.ru" + ae["url"],
            "title": ae["title"],
            "author": author,
            "status": None, "my_mark": None,
        }
        bid = _book_id(book["book_url"])
        if bid in book_ov:
            book.update(book_ov[bid])
        entries.append({
            "book": book,
            "slug": make_slug(ae["title"], author or "unknown"),
            "quotes": sorted(qs, key=lambda q: q["created_at"]),
            "review": None,
        })
        own_notes += 1

    # manual work merges: attach extra edition urls into an existing note (before write)
    merges = load(work_merges_path) if work_merges_path else []
    entry_by_slug = {e["slug"]: e for e in entries}
    for m in merges:
        target = entry_by_slug.get(m["into"])
        if not target:
            continue
        if m.get("extra"):
            target["book"].setdefault("_extra_urls", []).append(m["extra"])
        if m.get("status"):
            target["book"]["status"] = m["status"]
        gone = entry_by_slug.get(m.get("remove", ""))
        if gone is not None:
            target["book"].setdefault("_extra_urls", []).append(gone["book"]["book_url"])
            target["quotes"].extend(gone["quotes"])
            entries.remove(gone)

    used: set[str] = set()

    # collision handling BEFORE writing: extend with title words, id as last resort
    by_base: dict[str, list[dict]] = {}
    for e in entries:
        by_base.setdefault(e["slug"], []).append(e)
    for group in by_base.values():
        if len(group) == 1:
            continue
        for e in group:
            slug_words = set(e["slug"].split("-"))
            ext_words = "-".join(w for w in translit(e["book"]["title"]).split()
                                 if w and w not in slug_words)
            extended = f"{e['slug']}-{ext_words}" if ext_words else e["slug"]
            e["slug"] = extended if extended not in used else f"{e['slug']}-{_book_id(e['book']['book_url'])}"
            used.add(e["slug"])

    for e in entries:
        # final pass: one copy per quote id (same quote can arrive via several editions)
        seen, uniq = set(), []
        for q in e["quotes"]:
            qid = (q.get("quote") or {}).get("quote_id") or q.get("id")
            if qid in seen:
                continue
            seen.add(qid)
            uniq.append(q)
        e["quotes"] = uniq
        (out / f"{e['slug']}.md").write_text(render_note(e), encoding="utf-8")

    placed = sum(len(e["quotes"]) for e in entries) + sum(len(qs) for qs in by_work_own.values())

    return {
        "books": len(entries),
        "quotes_placed": placed,
        "quotes_in_collections": len(in_collections),
        "quotes_unmatched": 0,
        "own_notes": own_notes,
    }


def _note_index(books_dir) -> dict:
    """Map every livelib id mentioned in note-books -> note path."""
    import re as _re
    index = {}
    for note in sorted(pathlib.Path(books_dir).glob("*.md")):
        text = note.read_text(encoding="utf-8")
        for m in _re.finditer(r"livelib\.ru/(?:book|work|review|quote)/(\d+)", text):
            index.setdefault(m.group(1), []).append(note.name)
    return index


def validate_text_links(text_dir, books_dir, external_path=None, link_mappings_path=None) -> dict:
    """Report-only: resolve every livelib link in text/*.md against note-books.

    A link resolves when its numeric id appears in any note (book/review attr or
    quote livelib URL). Links listed in external_path (old-format LiveLib pages,
    site-only) are classified as external. link_mappings_path maps URLs to note
    slugs when the text edition id differs from the note edition. Returns
    {total, resolved, external, unresolved: [{url, file}]}.
    """
    import re as _re
    index = _note_index(books_dir)
    external = set()
    if external_path and pathlib.Path(external_path).exists():
        external = set(json.loads(pathlib.Path(external_path).read_text(encoding="utf-8")))
    mappings = {}
    if link_mappings_path and pathlib.Path(link_mappings_path).exists():
        mappings = json.loads(pathlib.Path(link_mappings_path).read_text(encoding="utf-8"))
    total, resolved, ext_n, unresolved = 0, 0, 0, []
    for chapter in sorted(pathlib.Path(text_dir).glob("*.md")):
        for m in _re.finditer(r"https://www\.livelib\.ru/(?:book|work|review|quote)/(\d+)[^)\s\"']*",
                              chapter.read_text(encoding="utf-8")):
            total += 1
            url = m.group(0).rstrip(".,;")
            if m.group(1) in index or url in mappings:
                resolved += 1
            elif url in external:
                ext_n += 1
            else:
                unresolved.append({"url": url, "file": chapter.name})
    return {"total": total, "resolved": resolved, "external": ext_n, "unresolved": unresolved}


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
    m = re.search(rf"^{key}:[ \t]*(.*?)[ \t]*$", fm, re.M)
    if not m:
        return None
    raw = m.group(1)
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    return raw


def important_books(books_dir) -> list[dict]:
    """Note-books marked `important: true`, ordered by `weight` (then by slug)."""
    out = []
    for note in sorted(pathlib.Path(books_dir).glob("*.md")):
        m = re.match(r"---\n(.*?)\n---", note.read_text(encoding="utf-8"), re.S)
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
                r'^\s*-\s*"?https?://(?:www\.)?livelib\.ru/(?:book|work)/(\d+)', fm, re.M)},
        })
    out.sort(key=lambda b: (b["weight"] is None, b["weight"] or 0, b["slug"]))
    return out


def render_p3_references(books_dir, reviews: list[dict], *, lines: list[dict] | None = None,
                        header: str = "", line_thesis: dict | None = None) -> dict:
    """Project `important` books into p3-references bullet lines.

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
    notes_with_review = {b["review_id"] for b in books if b["review_id"]}
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
    text = header.rstrip("\n") + "\n" if header else ""
    if items:
        text += "\n" + "\n".join(t for _, _, t in items) + "\n"
    return {"text": text, "items": [t for _, _, t in items], "warnings": warnings}
