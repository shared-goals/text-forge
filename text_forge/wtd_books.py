"""wtd-books: LiveLib JSON export -> books/<slug>.md note-books.

Design (agreed 2026-10-19):
- books/<slug>.md note-books are the single source of truth.
- Quotes live INSIDE book notes as headings with ^quote_N anchors.
- Review lives as a section with #review anchor.
- LiveLib URLs are attributes of our entries, never link targets.
"""

import json
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


def _work_key(title: str, author: str) -> str:
    """Normalization for matching editions of the same work (main title + surname)."""
    t = _main_title(title)
    t = re.sub(r"[^\w\s]", "", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    surname = translit(_surname(author)) if author else ""
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
        f'title: {book["title"]}',
    ]
    if _author_valid(book.get("author") or ""):
        fm.append(f'author: {book["author"]}')
    fm += [
        "tags:",
        "  - book",
    ]
    if book.get("status"):
        fm.append(f'status: {book["status"]}')
    if book.get("my_mark") is not None:
        fm.append(f'my_mark: {book["my_mark"]}')
    fm.append(f'livelib_book: "{slug_url}"')
    if entry["review"]:
        fm.append(f'livelib_review: "https://www.livelib.ru{entry["review"]["url"]}"')
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
        qurl = meta.get("url") or (f"/quote/{meta['quote_id']}" if meta.get("quote_id") else None)
        block = [_blockquote(_strip_html(q["text"]), n), ""]
        if qurl:
            block.append(f"livelib: https://www.livelib.ru{qurl}")
            block.append("")
        body += block
    return "\n".join(body).rstrip() + "\n"


def build_books(books_path, quotes_path, reviews_path, out_dir, collections_path=None,
                author_overrides_path=None) -> dict:
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
    # not-on-shelf editions were fetched only to hold quotes before work-merge existed
    books = [b for b in books if b.get("status") != "not-on-shelf"]
    # apply manual author overrides by edition id (data-level, before grouping)
    ov_by_id = {_book_id(u): a for u, a in overrides.items()}
    for b in books:
        bid = _book_id(b["book_url"])
        if bid in ov_by_id:
            b["author"] = ov_by_id[bid]
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
    used: set[str] = set()

    def write(entry: dict) -> None:
        slug, bid = entry["slug"], _book_id(entry["book"]["book_url"])
        if slug in used:
            slug = f"{slug}-{bid}"
        used.add(slug)
        entry["slug"] = slug
        (out / f"{slug}.md").write_text(render_note(entry), encoding="utf-8")

    for e in entries:
        write(e)

    # Quotes whose work matched no shelf book -> one own note per WORK.
    by_work_own: dict[str, list[dict]] = {}
    for q in own_quotes:
        ae = q["art_edition"]
        key = _work_key(ae["title"], (ae.get("authors") or [{}])[0].get("full_name", ""))
        by_work_own.setdefault(key, []).append(q)
    own_notes = 0
    for qs in by_work_own.values():
        ae = qs[0]["art_edition"]
        author = ", ".join(a["full_name"] for a in ae.get("authors") or [])
        entry = {
            "book": {
                "book_url": "https://www.livelib.ru" + ae["url"],
                "title": ae["title"],
                "author": author,
                "status": None, "my_mark": None,
            },
            "slug": make_slug(ae["title"], author or "unknown"),
            "quotes": sorted(qs, key=lambda q: q["created_at"]),
            "review": None,
        }
        write(entry)
        own_notes += 1

    placed = sum(len(e["quotes"]) for e in entries) + sum(len(qs) for qs in by_work_own.values())
    return {
        "books": len(entries),
        "quotes_placed": placed,
        "quotes_in_collections": len(in_collections),
        "quotes_unmatched": 0,
        "own_notes": own_notes,
    }
