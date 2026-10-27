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

from .livelib import LivelibClient

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


def _work_id(url: str) -> str:
    """The /work/<id> of a livelib url, when it names one. '' otherwise."""
    m = re.search(r"/work/(\d+)", url)
    return m.group(1) if m else ""


def _edition_id(url: str) -> str:
    """The /book/<id> of a livelib url, when it names one. '' otherwise."""
    m = re.search(r"/book/(\d+)", url)
    return m.group(1) if m else ""


def load_curation(path) -> dict:
    """Parse a .jsonc curation file: JSON with // line and /* */ block comments.

    Comment markers inside string literals are data, not comments: a title like
    "Письма о Сезанне https://..." must survive intact. Scanning character by
    character (rather than regexing the text) is what makes that true, and it
    also keeps `\"` from pretending to close a string.
    """
    text = pathlib.Path(path).read_text(encoding="utf-8")
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == '"':
                in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))



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


def group_export(books: list[dict], quotes: list[dict], reviews: list[dict],
                 work_id_by_edition: dict[str, str] | None = None,
                 curated_merges: dict[str, list[str]] | None = None
                 ) -> tuple[list[dict], list[dict], dict[str, set]]:
    """Group LiveLib export records into per-book entries.

    work_id_by_edition — {edition id: work id} resolved at crawl time (see
    LivelibClient.work_id). When an entry has one, grouping keys by that work id
    instead of by normalized title: livelib's own relation is exact, so editions
    of one work merge even when their titles differ.

    curated_merges — {main edition id: [other edition id, ...]} read from the
    books entries themselves (`"merges": [...]` on a book): a human statement
    that the other edition's records belong to the MAIN id's note. It enters the
    same union-find as livelib's relations, so one mechanism groups both; use it
    where livelib lists no shared work and so reaches nothing by itself.

    Returns (entries, own_quotes, note_editions): entries — one per shelf book
    with quotes/review merged (including other editions of the same work);
    own_quotes — quotes whose work matched no shelf book (they become their own
    notes); note_editions — {entry slug: every edition id that contributed a
    record to that entry}, so all the ids a note really holds are known even
    though the scratch edition set is dropped from the entry itself.
    """
    reviews_by_book = {}
    for r in reviews:
        reviews_by_book.setdefault(_book_id(r["art_edition"]["url"]), r)

    # The work relation: which livelib ids stand for ONE work, so their shelf
    # entries become one note. Sources, the first of them ours, the rest
    # livelib's own statements:
    #   0. curated_merges — a per-book `merges` array: a human decision that
    #      another edition's records belong to this note, entered as edges
    #      main <-> id into the same union-find below (no second grouping pass).
    #   1. work_id_by_edition — the crawl cache {edition id: work id}, read off
    #      each edition page's «Содержание» (LivelibClient.work_id). A relation
    #      may name SEVERAL works (an anthology lists them all): `work_id` names
    #      the one the edition is called after, `work` the whole list. This is
    #      livelib's statement ABOUT that edition, so it groups that edition with
    #      whatever else the relation reaches — editions whose titles differ by
    #      name order or subtitle merge exactly.
    #   2. a quote/review naming two DIFFERENT ids: art_edition.id and the id its
    #      url carries (e.g. «Родная речь» quoted from edition 1010123266 while
    #      the record names 1001474484). Such a record states a relation for the
    #      edition IT speaks of — the one its title names, the edition the text
    #      was made from — and reaching THROUGH a work (one edition per work) is
    #      livelib's own way of relating siblings, so the subject of the record
    #      is the endpoint that ties to the url's edition.
    # What is NOT a relation: two WORK ids. A work is the thing itself, so two
    # ids of one work are one thing stated twice — joining them would fuse every
    # shelf edition that merely names either of them (an anthology with the
    # collection sharing a work with it, two volumes of different works). The
    # crawl cache therefore records a sibling work only in `work`, never in
    # `work_id`, and an id that names no shelf record groups nothing: it is not
    # an entry we hold, it only guides quote placement (by_work_id below).
    # Entries with no relation at all fall back to title+author normalization.
    # Nothing here is inferred from titles or authors.
    shelf_ids = {_book_id(b["book_url"]) for b in books}
    # a curated merge may name a non-canonical entry first (the file is a map,
    # its direction a reading convention): a listed id that already merges INTO
    # another main is a member, not a main — the arrays are one relation per
    # work however they are written
    curated_raw = {str(k): [str(x) for x in (v or [])]
                   for k, v in (curated_merges or {}).items()}
    members = {o for v in curated_raw.values() for o in v}
    curated_merges = {k: v for k, v in curated_raw.items() if k not in members}
    cache_in = {str(k): str(v) for k, v in (work_id_by_edition or {}).items() if v}
    parent: dict[str, str] = {}
    edge_ids: set[str] = set()             # ids that take part in a join

    def find(x: str) -> str:
        r = x
        while parent.setdefault(r, r) != r:
            r = parent[r]
        while parent[x] != r:          # path compression
            parent[x], x = r, parent[x]
        return r

    def edge(subject: str, other: str) -> None:
        """Join one relation livelib stated, `subject` being the id the cache
        entry or the record is ABOUT (an edition we hold, or a work that is
        itself one). Two work ids are never joined."""
        if not subject or not other or subject == other:
            return
        if subject in cache_in.values() or other in cache_in.values():
            pass                        # keep lint quiet on the empty branch
        ra, rb = find(subject), find(other)
        if ra != rb:
            parent[ra] = rb
        edge_ids.update((subject, other))

    # cache edges: the edition the entry is keyed by, and — when livelib reuses
    # one id for a work and for a shelf edition — that edition too
    for k, v in cache_in.items():
        for w in (x.strip() for x in v.split(",")):
            edge(k, w)
            if k in shelf_ids:
                continue
            # key is a work id: it stands for the work, so the shelf editions
            # whose own cache entry names this same work are siblings of k
            for other, vother in cache_in.items():
                if other != k and w in (x.strip() for x in vother.split(",")):
                    edge(k, other)
    # curated edges: the main id (the entry that carries the array) is joined to
    # every id it lists — the same `edge` mechanism, so a curated merge groups
    # exactly like a livelib relation. An id reaching its main through a curated
    # edge (a shelf edition joined to the main via a work the cache names) is a
    # TRANSIT: the main's array already states the relation, and a transit key
    # would inherit a cache anchor that outranks the main — so only edges the
    # union does not yet imply are added
    for main, others in curated_merges.items():
        for other in others:
            edge(main, other)
    for rec in list(quotes) + list(reviews):
        ae = rec.get("art_edition") or {}
        url = ae.get("url") or ""
        named, url_id = str(ae.get("id") or ""), _book_id(url)
        if "/work/" in url and named:
            # the record names a work: relate it to the shelf editions whose
            # title+author match the work's own title — livelib just told us
            # what this work is called (a shelf record sharing the work's id
            # is the anchor; the trivial self-edge is ignored by edge())
            author = next((a.get("full_name", "") for a in ae.get("authors") or []), "")
            wkey = _work_key(ae.get("title") or "", author)
            for b in books:
                bid = _book_id(b["book_url"])
                if bid in shelf_ids and _work_key(b["title"], b["author"]) == wkey:
                    edge(named, bid)
        if named and url_id and named != url_id:
            # the subject is the edition the record speaks of: the /work/ id
            # always names a work, and a work is a subject when the shelves hold
            # it (livelib reuses one id); otherwise the url's own edition id is
            subject = named if ("/work/" in url and named in shelf_ids) else url_id
            other = named if subject == url_id else url_id
            edge(subject, other)
    # The grouping key of a component: an id that is BOTH a shelf record and a
    # work (livelib reuses one id for both) — livelib's own statement that this
    # entry stands for the whole work — and failing that the subject of the
    # component's relations, the edition the notes are held for. A bare work id
    # nobody holds is never a key.
    def work_ids_of(cache: dict, quotes, reviews) -> set[str]:
        """Ids livelib itself declares to be works: the resolved work of every
        cached edition, and every /work/<id> a quote or review names (livelib
        files collection records under the work they belong to)."""
        ids = {w for v in cache.values()
               for w in (x.strip() for x in str(v).split(",")) if w}
        for rec in list(quotes) + list(reviews):
            ae = rec.get("art_edition") or {}
            if "/work/" in (ae.get("url") or ""):
                wid = _book_id(ae["url"])
                if wid:
                    ids.add(wid)
                if ae.get("id"):
                    ids.add(str(ae["id"]))
        return ids

    works = work_ids_of(cache_in, quotes, reviews)
    anchor_of: dict[str, str] = {}
    for bid in shelf_ids:
        anchor_of.setdefault(find(bid), bid)
    for k in cache_in:
        if k in shelf_ids:
            anchor_of[find(k)] = k
    # a work id (livelib reuses it for a shelf edition) outranks the cache-key
    # edition as the component's anchor — it is the work itself
    for bid in shelf_ids:
        if bid in works:
            anchor_of[find(bid)] = bid
    # a curated merge's MAIN id outranks everything: the human said THIS note
    # is the one the component's records belong to (a member may be the union
    # root — union direction is an implementation accident)
    for main in curated_merges:
        if main in shelf_ids:
            anchor_of[find(main)] = main

    # the work each shelf id stands for, when a relation says so
    #
    # the ORDER of these rules IS the policy for naming a work:
    #   1. the id livelib itself reuses for the work (a shelf id in `works`)
    #      is the work — exact, and it names the note;
    #   2. else the MAIN of a curated `merges` array names it — the human said
    #      which of the component's records the note is;
    #   3. else a component holding several shelf editions is one work, and the
    #      component's named anchor (the edition the relation is keyed by) stands
    #      for it — this is what merges editions whose titles differ only by
    #      name order or subtitle;
    # a component holding ONE shelf id names nothing: that edition is its own
    # note, and the other end of the relation is only a link target
    components: dict[str, list[str]] = {}
    for bid in shelf_ids:
        components.setdefault(find(bid), []).append(bid)
    work_of = {}
    for bid in shelf_ids:
        root = find(bid)
        a = anchor_of.get(root)
        if root == bid or a is None:
            continue
        if a in works or a in curated_merges or len(components[root]) > 1:
            work_of[bid] = a
    # every id the relations name — guides quote placement, never grouping
    record_work = edge_ids | set(cache_in.values())
    mains = set(curated_merges) | works

    entries = []
    for book in books:
        bid = _book_id(book["book_url"])
        # a shelf id livelib itself reuses for the work stands for that work,
        # so it keys by its own id, not only by what other editions point to;
        # an edition joined into a component whose anchor IS a work id (or a
        # curated main) keys by that anchor even when it happens to be the
        # union's root
        wid = work_of.get(bid) or (bid if bid in mains else None)
        if not wid and anchor_of.get(find(bid)) in mains:
            wid = anchor_of[find(bid)]
        entries.append({
            "book": book,
            "slug": make_slug(book["title"], book["author"]),
            "quotes": [],
            # a curated member's review belongs to the main note even when the
            # member holds no shelf record of its own
            "review": reviews_by_book.get(bid)
                      or next((reviews_by_book[m] for m in curated_merges.get(bid, [])
                               if reviews_by_book.get(m)), None),
            # a curated member may hold no shelf record: it still belongs to
            # the main note's edition set, so its links resolve
            "_edition_ids": {bid, *curated_merges.get(bid, [])},
            "_work_id": str(wid) if wid else None,
            "_anchor": anchor_of.get(find(bid)) if find(bid) != bid else None,
            "_main": bid in curated_merges,
        })

    # Merge shelf entries that are different editions of one work, or that a
    # curated `merges` array joins: primary = the note's own shelf record (what
    # the entry is keyed by), else the one with a review, else the most quoted.
    # Grouping key: livelib's work id (or the component's shelf anchor) when we
    # have one — exact, so editions whose titles differ by name order or
    # subtitle still merge — normalized title+author otherwise.
    merged: dict[str, list[dict]] = {}
    for e in entries:
        wid = e.get("_work_id") or e.get("_anchor")
        key = f"work:{wid}" if wid else _work_key(e["book"]["title"], e["book"]["author"])
        merged.setdefault(key, []).append(e)
    final = []
    for group in merged.values():
        # the note's identity is the entry that STANDS for the work: the one
        # whose own relation keyed the group, or the main of a curated merge;
        # failing that, the review holder, then the most quoted
        keys = {str(e.get("_work_id") or e.get("_anchor")) for e in group}
        primary = next((e for e in group
                       if e["_main"] or str(_book_id(e["book"]["book_url"])) in keys),
                       None) \
            or next((e for e in group if e["review"]), None) \
            or (max(group, key=lambda e: len(e["quotes"]))
                if len(group) > 1 else group[0])
        for e in group:
            e.pop("_main", None)
        for other in group:
            if other is not primary:
                primary["_edition_ids"] |= other["_edition_ids"]
                primary["quotes"].extend(other["quotes"])
                primary["review"] = primary["review"] or other["review"]
                primary["book"].setdefault("_extra_urls", []).append(other["book"]["book_url"])
        final.append(primary)
    # a curated member with no shelf record has no entry of its own: its url
    # still belongs to the main note's edition set, so its links resolve and
    # livelib_editions names it
    by_id = {_book_id(b["book_url"]): b for b in books}
    for e in final:
        bid = _book_id(e["book"]["book_url"])
        for m in curated_merges.get(bid, []):
            mb = by_id.get(m)
            url = mb["book_url"] if mb else f"https://www.livelib.ru/book/{m}"
            if m not in e["_edition_ids"]:
                e["_edition_ids"].add(m)
            urls = e["book"].setdefault("_extra_urls", [])
            if url not in urls:
                urls.append(url)
    by_work = {_work_key(e["book"]["title"], e["book"]["author"]): e for e in final}

    # quote placement, most reliable first: the edition the quote was made from
    # is already in a note's edition set; else the id the record names (a /work/
    # url or art_edition.id) belongs to that note's relation component — the ids
    # the component's own edges brought in, NOT a global pool (a global pool
    # would hand another note's ids to whichever entry is processed first);
    # else title+author normalization, the fallback for entries whose work was
    # never resolved
    comps: dict[str, set] = {}
    for x in list(edge_ids) + list(cache_in) + list(record_work):
        if x:
            comps.setdefault(find(x), set()).add(x)
    by_work_id: dict[str, dict] = {}
    for e in final:
        bid = _book_id(e["book"]["book_url"])
        ids = {e.get("_work_id"), e.get("_anchor"), bid}
        ids |= comps.get(find(bid), set())
        for wid in ids:
            if wid:
                by_work_id.setdefault(wid, e)

    own_entries = []
    for q in quotes:
        ae = q["art_edition"]
        qid = _book_id(ae["url"])
        target = next((e for e in final if qid in e["_edition_ids"]), None)
        if target is None:
            target = by_work_id.get(_work_id(ae["url"])
                                    or str(ae.get("id") or "")
                                    or work_of.get(qid, ""))
        if target is None:
            target = by_work_id.get(work_of.get(qid, ""))
        if target is None:
            target = by_work.get(_work_key(q["art_edition"]["title"],
                                           (q["art_edition"].get("authors") or [{}])[0].get("full_name", "")))
        if target is None:
            own_entries.append(q)
        else:
            target["quotes"].append(q)

    # every record that landed in a note is an edition of the work the note
    # speaks of, so its id belongs to that note: the edition a quote was made
    # from, the reissue a review was filed under. The corpus declares them as
    # `livelib_editions`, and the link validator and the bibliography need them;
    # collected here, before the scratch key is dropped.
    note_editions: dict[str, set] = {}
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
        if e.get("review"):
            e["_edition_ids"].add(_book_id(e["review"]["art_edition"]["url"]))
        note_editions[e["slug"]] = set(e["_edition_ids"])
        e.pop("_work_id", None)
        e.pop("_anchor", None)
        del e["_edition_ids"]
    final.sort(key=lambda e: e["slug"])
    return final, own_entries, note_editions


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
    if book.get("important"):
        fm.append("important: true")
        fm.append(f'weight: {book["weight"]}')
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


def resolve_edition_cached(book_id: str, *, cache_path=None, client=None) -> dict:
    """{title, author} of an edition id via the edition card, with a JSON cache.

    Keyed by edition id. An id livelib could not resolve is cached too (as an
    empty entry), so a rebuild does not re-hit the network for what livelib does
    not have. The cache is the build's record of where each fetched title came
    from; `source` says whether it was the API or a recorded miss.
    """
    if client is None:
        from .livelib import LivelibClient
        client = LivelibClient()
    cache = {}
    if cache_path and pathlib.Path(cache_path).exists():
        cache = json.loads(pathlib.Path(cache_path).read_text(encoding="utf-8"))
    key = str(book_id)
    # a record already marked as an answer is not retried: the empty entry IS
    # the answer, and re-hitting the network for what livelib does not have
    # would make a rebuild depend on livelib being up
    if key not in cache or not (cache[key] or {}).get("source"):
        got = client.edition_meta(key) or {}
        cache[key] = {**got,
                     "source": "api" if got.get("title") or got.get("author") else "none"}
        if cache_path:
            pathlib.Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(cache_path).write_text(
                json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8")
    return {"title": "", "author": "", **cache[key]}



def resolve_works_cached(ids, *, cache_path=None, client=None, titles=None, fetch=None):
    """{edition id: work id} for the given ids, cached in one JSON file.

    ids — edition ids, or {"id": ..., "title": ...} dicts when the caller has a
    title to offer (a collection needs it: only the title says which of its works
    the edition is named after). `titles` is the equivalent mapping form for bare
    ids. `client`/`fetch` inject the transport, as everywhere in this module.

    The cache lives beside the export (works-cache.json) and records genuine
    misses ("this edition lists no works") so a rebuild is offline-repeatable; an
    id whose page could not be fetched at all is left OUT of the cache, so the
    next build tries it again rather than pinning a temporary network failure.
    """
    cache = {}
    if cache_path and pathlib.Path(cache_path).exists():
        cache = json.loads(pathlib.Path(cache_path).read_text(encoding="utf-8"))
    titles = titles or {}

    def answered(rec) -> bool:
        """Does this cached record answer the question?

        Only a `work_id` field does — a record written by another builder (an
        edition title from the search API) carries no relation and must not stop
        the fetch.
        """
        return bool(rec) and "work_id" in rec

    # ids the cache already answers need no client at all
    todo = [i for i in ids
            if not answered(cache.get(str(i["id"] if isinstance(i, dict) else i)))]
    if todo and client is None:
        from .livelib import LivelibClient
        client = LivelibClient(fetch=fetch)
    out: dict[str, str | None] = {}
    for item in ids:
        eid, title = (item["id"], item.get("title", "")) \
            if isinstance(item, dict) else (item, titles.get(str(item), ""))
        key = str(eid)
        if answered(cache.get(key)):
            out[key] = cache[key].get("work_id")
            continue
        # LivelibClient.work_id does the caching itself: it writes a
        # {"work_id": ...} entry for a page it read (including "no works
        # listed") and writes nothing at all when the page was unreachable — so
        # the caller's copy must match what the cache ended up holding.
        work = client.work_id(key, title=title, cache_path=cache_path)
        if cache_path and pathlib.Path(cache_path).exists():
            cache = json.loads(pathlib.Path(cache_path).read_text(encoding="utf-8"))
        out[key] = cache[key]["work_id"] if answered(cache.get(key)) else work
    return out


def _load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _text_book_ids(text_dir) -> list[str]:
    """Every /book/ and /work/ id the TEXT links, in first-seen order.

    Only edition/work ids are collected: a quote or review id is placed by the
    export, so it never needs metadata resolution.
    """
    out: list[str] = []
    seen = set()
    for chapter in sorted(pathlib.Path(text_dir).glob("*.md")):
        for m in re.finditer(r"livelib\.ru/(?:book|work)/(\d+)",
                            chapter.read_text(encoding="utf-8")):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(m.group(1))
    return out


def build_books(books_path, quotes_path, reviews_path, out_dir, *, curation_path=None,
                text_dir=None, editions_cache_path=None, works_cache_path=None,
                work_id_by_edition=None, fetch=None) -> dict:
    """Build books/<slug>.md notes from LiveLib export JSON files.

    curation_path — ONE curation.jsonc in normal form: one entry per livelib
    edition id under `books`, each carrying weight?/status?/my_mark?/author?/
    merges?. Anything livelib can tell us is not stored.

    Reference books need no section of their own: pass `text_dir` and the build
    scans the texts for livelib edition ids no note would declare, resolving
    each one's title/author through LivelibClient.edition_meta (cached beside
    the export in editions-cache.json, so a rebuild stays offline-repeatable).
    Such a note declares the short canonical url its id always redirects to.

    Work merges need no section of their own: pass `works_cache_path` (or let the
    build derive it from `editions_cache_path`) and every shelf edition's work is
    resolved through LivelibClient.work_id, cached beside the export, and the
    cache feeds group_export — editions livelib itself links merge themselves.
    A curated `merges` entry still works, and then just matches (or no-ops over)
    what the resolution already did.
    """
    from pathlib import Path

    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    books = load(books_path)
    quotes = load(quotes_path)
    reviews = load(reviews_path)

    # a caller may hand in an already-built curation mapping instead of a path
    cur = (curation_path if isinstance(curation_path, dict)
           else load_curation(curation_path) if curation_path is not None else {})
    entries_cur = dict(cur.get("books") or {})
    ov_by_id = {bid: v.get("author") for bid, v in entries_cur.items() if v.get("author")}
    book_ov = {bid: {k: v[k] for k in ("status", "my_mark") if v.get(k) is not None}
               for bid, v in entries_cur.items()}
    book_ov = {bid: v for bid, v in book_ov.items() if v}
    important = {bid: v["weight"] for bid, v in entries_cur.items() if v.get("weight") is not None}
    # per-book merges: `"merges": [other edition id]` on a books entry says the
    # other edition's quotes/review belong to THIS note
    curated_merges: dict[str, list[str]] = {}
    for bid, ent in entries_cur.items():
        if ent.get("merges"):
            curated_merges.setdefault(str(bid), []).extend(
                str(x) for x in ent["merges"])
    # reference notes: works the TEXTS cite that no shelf holds and no
    # quote/review record names — the edition card JSON (/art-editions/{id})
    # supplies title and author, cached beside the export so a rebuild stays
    # offline. Such a note declares the short canonical url its id always
    # redirects to, so the citation a text wrote resolves from the note.
    ref_warnings: list[str] = []
    if text_dir is not None:
        known = {_book_id(b["book_url"]) for b in books}
        known |= {str((rec.get("art_edition") or {}).get("id") or "")
                  for rec in list(quotes) + list(reviews)}
        known |= {_book_id((rec.get("art_edition") or {}).get("url") or "")
                  for rec in list(quotes) + list(reviews)}
        known |= set(curated_merges) | {o for v in curated_merges.values() for o in v}
        extra: list[dict] = []
        for bid in _text_book_ids(text_dir):
            if bid in known:
                continue
            got = resolve_edition_cached(bid, cache_path=editions_cache_path,
                                        client=LivelibClient(fetch=fetch)
                                        if fetch is not None else None)
            if not (got.get("title") or got.get("author")):
                # nothing to make a note from: the link stays unresolved and the
                # validator reports it, instead of a note with an invented title
                ref_warnings.append(bid)
                continue
            extra.append({"id": bid, "title": got["title"],
                         "book": {"book_url": f"https://www.livelib.ru/book/{bid}",
                                 "title": got["title"], "author": got["author"],
                                 # a work the text quotes from is read, whatever
                                 # the shelves say about it
                                 "status": "read", "my_mark": None}})
        for rec in extra:
            if rec["id"] in book_ov:
                rec["book"].update(book_ov[rec["id"]])
            if rec["id"] in important:
                rec["book"]["important"] = True
                rec["book"]["weight"] = important[rec["id"]]
            books.append(rec["book"])
        # the work relation of a derived edition is resolved with the rest: it is
        # what groups the edition into a sibling note instead of leaving it alone
        if extra:
            resolved_extra = resolve_works_cached(extra, cache_path=works_cache_path,
                                                 fetch=fetch)
            work_id_by_edition = {**{k: v for k, v in resolved_extra.items() if v},
                                 **(work_id_by_edition or {})}
    # the work relation, resolved once per SHELF edition from the edition pages'
    # «Содержание» (LivelibClient.work_id). The cache lives beside the export
    # (default: works-cache.json next to the editions cache), so a rebuild with
    # the same inputs reproduces without the network. An explicit
    # work_id_by_edition from the caller overrides what the cache says.
    # The record of one crawl feeds the next build — an id whose page could not
    # be read stays out of the cache and is tried again; its note is then still
    # assembled from the quote/review ids the export itself carries, so the note
    # content (title, author, quotes) never depends on the fetch, only which
    # extra edition line it declares.
    if works_cache_path is None and editions_cache_path is not None:
        works_cache_path = pathlib.Path(editions_cache_path).with_name("works-cache.json")
    book_editions: dict[str, set] = {}
    for b in books:
        bid = _book_id(b["book_url"])
        if _edition_id(b["book_url"]) == bid:
            book_editions.setdefault(bid, set()).add(bid)
    for q in quotes:
        book_editions.setdefault(_book_id(q["art_edition"]["url"]), set()).add(
            str(q["art_edition"].get("id") or "") or _book_id(q["art_edition"]["url"]))
    for r in reviews:
        book_editions.setdefault(_book_id(r["art_edition"]["url"]), set()).add(
            str(r["art_edition"].get("id") or "") or _book_id(r["art_edition"]["url"]))
    resolved: dict[str, str | None] = {}
    if works_cache_path is not None:
        resolved = resolve_works_cached(
            [{"id": _book_id(b["book_url"]), "title": b.get("title") or ""}
             for b in books],
            cache_path=works_cache_path, fetch=fetch)
    work_id_by_edition = {**(resolved or {}), **(work_id_by_edition or {})}
    work_id_by_edition = {k: v for k, v in work_id_by_edition.items() if v}
    # statuses pass through as LiveLib names; the export's synthetic marker means "no shelf"
    for b in books:
        bid = _book_id(b["book_url"])
        if bid in ov_by_id:
            b["author"] = ov_by_id[bid]
        if bid in book_ov:
            b.update(book_ov[bid])
        if b.get("status") == "not-on-shelf":
            b["status"] = None
    for b in books:
        w = important.get(_book_id(b["book_url"]))
        if w is not None:
            b["important"] = True
            b["weight"] = w
    for q in quotes:
        qid = _book_id(q["art_edition"]["url"])
        if qid in ov_by_id:
            q["art_edition"]["authors"] = [{"full_name": a} for a in ov_by_id[qid].split(", ")]
    # a curated MAIN may hold no shelf record (the id lives only in the texts
    # or as an own-note): the note must still exist and key by the main id, so
    # its card (title/author) is resolved the same way a reference book's is
    for main in list(curated_merges):
        if any(_book_id(b["book_url"]) == main for b in books):
            continue
        got = resolve_edition_cached(main, cache_path=editions_cache_path,
                                     client=LivelibClient(fetch=fetch)
                                     if fetch is not None else None)
        if not (got.get("title") or got.get("author")):
            ref_warnings.append(f"curated main {main} unresolvable")
            continue
        b = {"book_url": f"https://www.livelib.ru/book/{main}",
             "title": got["title"], "author": got.get("author") or "",
             "status": None, "my_mark": None}
        if main in book_ov:
            b.update(book_ov[main])
        if main in important:
            b["important"] = True
            b["weight"] = important[main]
        books.append(b)

    entries, own_quotes, _note_editions = group_export(books, quotes, reviews,
                                                     work_id_by_edition,
                                                     curated_merges)
    # a curated author is the human's word against livelib's: it wins over what
    # the record carried, everywhere that id appears
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
        w = important.get(bid)
        if w is not None:
            book["important"] = True
            book["weight"] = w
        entries.append({
            "book": book,
            "slug": make_slug(ae["title"], author or "unknown"),
            "quotes": sorted(qs, key=lambda q: q["created_at"]),
            "review": None,
            # the editions this work is held in, as the records name them: the
            # ids of the quotes made from it (their urls may differ from the
            # record the note was keyed by — another print, another set)
            "_extra_urls": sorted(({f"https://www.livelib.ru/book/{i}"
                                   for q in qs
                                   for i in book_editions.get(_book_id(q["art_edition"]["url"]), {bid})
                                   if i}) - {book["book_url"]}),
        })
        own_notes += 1

    # (a derived edition's urls are already the short canonical form: the id the
    # text cited is the id the note declares)

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

    # link mappings land here: the mapping is derived from what the built notes
    # actually declare (a slug that collision handling renamed is followed to its
    # new name), so every id a note holds resolves to it.
    link_map = {}

    def add_link(url, slug):
        """Key a link by (kind, id) in canonical form — never nested, and never
        by the decorative slug suffix."""
        key = _link_key(url)
        if key:
            link_map.setdefault(f"https://www.livelib.ru/{key[0]}/{key[1]}", slug)

    for e in entries:
        book_id = _book_id(e["book"]["book_url"])
        if book_id:
            add_link(e["book"]["book_url"], e["slug"])
        for u in (e["book"].get("_extra_urls") or []):
            add_link(u, e["slug"])
        if e["review"]:
            rid = _review_id(e["review"]["url"])
            if rid:
                link_map.setdefault(f"https://www.livelib.ru/review/{rid}", e["slug"])

    return {
        "books": len(entries),
        "quotes_placed": placed,
        "quotes_unmatched": 0,
        "own_notes": own_notes,
        # quote urls, not book urls: a human follows the quote to see what
        # produced the own note (the book itself may not exist as a record)
        "own_note_urls": sorted("https://www.livelib.ru/quote/" + str(q["id"])
                                for e in entries
                                if e["book"]["book_url"] not in
                                {b["book_url"] for b in books}
                                for q in e["quotes"]),
        "unresolved_reference_books": ref_warnings,
        "work_ids": dict(work_id_by_edition),
        "link_map": link_map,
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


def _curation_section(path_or_map, section):
    """Read one section from a curation source given as a path to a consolidated
    .jsonc or as the mapping itself (the form build_books emits, e.g. its
    `link_map`)."""
    if path_or_map is None:
        return None
    if isinstance(path_or_map, (dict, list)):
        return path_or_map
    return load_curation(path_or_map).get(section)


def validate_text_links(text_dir, books_dir, link_mappings_path=None) -> dict:
    """Report-only: resolve every livelib link in text/*.md against note-books.

    A link resolves when its numeric id appears in any note (book/review attr,
    an edition line, or a quote url). link_mappings_path — the mapping
    build_books emits — maps URLs to note slugs for the cases a note names its
    subject by an id the note file does not print. Returns
    {total, resolved, unresolved: [{url, file}]}.
    """
    import re as _re
    index = _note_index(books_dir)
    mappings = _curation_section(link_mappings_path, "links") or {}
    # keyed two ways so the written form of a url does not matter: by the url as
    # written, and by its canonical (kind, id). livelib redirects between the
    # short /book/<id> and the slug-suffixed /book/<id>-<title>-<author> form, so
    # a text and a note may name the same work differently.
    norm_url, norm_key = {}, {}
    for url, slug in mappings.items():
        norm_url[url] = slug
        key = _link_key(url)
        if key:
            norm_key[key] = slug
    total, resolved, unresolved = 0, 0, []
    for chapter in sorted(pathlib.Path(text_dir).glob("*.md")):
        for m in _re.finditer(r"https://www\.livelib\.ru/(?:book|work|review|quote)/(\d+)[^)\s\"']*",
                              chapter.read_text(encoding="utf-8")):
            total += 1
            url = m.group(0).rstrip(".,;")
            key = (m.group(0).split("/")[3], m.group(1))  # (kind, id)
            if m.group(1) in index or url in norm_url or key in norm_key:
                resolved += 1
            else:
                unresolved.append({"url": url, "file": chapter.name})
    return {"total": total, "resolved": resolved, "unresolved": unresolved}


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
    text = p3_header()
    if items:
        text += "\n" + "\n".join(t for _, _, t in items) + "\n"
    return {"text": text, "items": [t for _, _, t in items], "warnings": warnings}
