"""Regenerate whattodo/text/books/*.md from the LiveLib source.

Single entry point for the `make books` target (whattodo/Makefile):

    uv run --project ../text-forge python -m text_forge.wtd_books_build <whattodo_root>

Steps:
1. Export fresh data (shelves incl. statuses, quotes, reviews) into
   <root>/livelib-export/ — anonymous API + SSR, no credentials needed.
2. build_books() with the ONE curation file
   <root>/text/books/_curation/curation.jsonc, and the texts themselves passed
   as `text_dir` so a work a chapter cites but no shelf holds still gets its
   note (title/author from the edition card JSON).
3. Replace <root>/text/books/*.md with the generated set (_curation/ untouched).
4. Validate: frontmatter contract + text links; print the status distribution.

Titles/authors of cited-but-unshelved editions come from the LiveLib edition
API during step 2 and are cached in <root>/livelib-export/editions-cache.json,
so a rebuild with the same inputs reproduces the corpus byte for byte without
the network.
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from text_forge.livelib import LivelibClient
from text_forge.wtd_books import (
    _edition_id,
    _work_id,
    build_books,
    render_p3_references,
    validate_text_links,
)

CUR = Path(__file__).parent / "wtd_books.py"
CUR_DIR = CUR.parent


def _record_ids(records: list[dict]) -> set[str]:
    """The stable id of each export record: a quote's or review's own id, else
    the edition id the record was made from (shelf records carry no id of their
    own beyond that)."""
    out = set()
    for r in records:
        qid = (r.get("quote") or {}).get("quote_id")
        rid = (r.get("review") or {}).get("review_id") or r.get("id")
        u = r.get("book_url") or (r.get("art_edition") or {}).get("url") or ""
        out.add(str(qid or rid or _edition_id(u) or _work_id(u)))
    return out


def export(user_id: int, out_dir: Path) -> dict:
    """Fetch the three export files, reporting what a previous run held and this
    one does not (or vice versa).

    The old file is read BEFORE it is overwritten, so a record the user deleted
    on livelib is named by its id rather than lost: the corpus can then be
    checked against a known set instead of a silently shortened one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
    c = LivelibClient()

    def _short(ids, limit=8):
        ids = sorted(ids)
        head = ", ".join(ids[:limit])
        more = f" …+{len(ids) - limit} more" if len(ids) > limit else ""
        return f"[{head}{more}]"

    counts: dict[str, int] = {}
    # shelves: shelf() prints one progress line per shelf, books() merges them
    records = c.books(user_id)
    path = out_dir / "livelib-books.json"
    old = (
        _record_ids(json.loads(path.read_text(encoding="utf-8")))
        if path.exists()
        else None
    )
    path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    counts["livelib-books.json"] = len(records)
    if old is not None:
        new = _record_ids(records)
        if old - new:
            print(f"  livelib-books.json: LOST {_short(old - new)}")
        if new - old:
            print(f"  livelib-books.json: NEW {_short(new - old)}")
    for name, get in (
        ("livelib-quotes-api.json", lambda: c.quotes(user_id)),
        ("livelib-reviews-api.json", lambda: c.reviews(user_id)),
    ):
        path = out_dir / name
        old = (
            _record_ids(json.loads(path.read_text(encoding="utf-8")))
            if path.exists()
            else None
        )
        records = get()
        path.write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        counts[name] = len(records)
        if old is not None:
            new = _record_ids(records)
            if old - new:
                print(f"  {name}: LOST {_short(old - new)}")
            if new - old:
                print(f"  {name}: NEW {_short(new - old)}")
    return counts


def main(root_str: str, user_id: int = 345497) -> int:
    root = Path(root_str).resolve()
    export_dir = root / "livelib-export"
    books_dir = root / "text" / "books"
    cur = books_dir / "_curation"

    counts = export(user_id, export_dir)
    print("export:", counts)

    tmp = Path(tempfile.mkdtemp(prefix="wtd-books-"))
    # one curation file, normal form: one entry per livelib edition id
    curation = cur / "curation.jsonc"
    if not curation.exists():
        print(f"FAIL: curation file not found: {curation}")
        return 1

    # crawl progress: one line per livelib page actually fetched (a cached id
    # costs no network and prints nothing) — the url of the record being read
    seen_pages = [0]

    def progress_fetch(url: str) -> str:
        if "/art-editions/" in url:
            seen_pages[0] += 1
            m = re.search(r"/art-editions/(\d+)", url)
            if m:
                print(
                    f"  crawl {seen_pages[0]:3d}: https://www.livelib.ru/book/{m.group(1)}"
                )
        return LivelibClient().fetch(url)

    report = build_books(
        export_dir / "livelib-books.json",
        export_dir / "livelib-quotes-api.json",
        export_dir / "livelib-reviews-api.json",
        tmp,
        curation_path=curation,
        text_dir=root / "text",
        editions_cache_path=export_dir / "editions-cache.json",
        fetch=progress_fetch,
    )
    # human summary: counts, then every exception as a url to look at —
    # never an id dump (the machine-readable maps live in link-map.json)
    print(
        f"build: {report['books']} notes, "
        f"{report['quotes_placed']} quotes placed, "
        f"{report['own_notes']} own notes"
    )
    for u in report.get("own_note_urls") or []:
        print(f"  OWN NOTE (quote of a work with no shelf record): {u}")
    for bid in report.get("unresolved_reference_books") or []:
        print(
            f"  WARNING: cited edition not resolvable via livelib: "
            f"https://www.livelib.ru/book/{bid}"
        )

    # the mapping the notes declare, written beside the curation file: the link
    # validator and the bibliography generator consume it, and keeping it makes a
    # rebuild's id->note decisions auditable
    link_map = report["link_map"]
    (cur / "link-map.json").write_text(
        json.dumps(link_map, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for old in books_dir.glob("*.md"):
        old.unlink()
    for gen in tmp.glob("*.md"):
        shutil.copy2(gen, books_dir / gen.name)

    # p3-references is a PROJECTION of the notes (importance in frontmatter,
    # thesis = the book's own LiveLib review title, LOCAL link targets) plus the
    # collapsed shelf lists — written FROM SCRATCH on every build: the generator
    # never parses the page it wrote, so there is nothing to read back.
    p3 = render_p3_references(
        books_dir,
        json.loads(
            (export_dir / "livelib-reviews-api.json").read_text(encoding="utf-8")
        ),
    )
    for w in p3["warnings"]:
        print("  P3:", w.get("reason"), w.get("slug") or w.get("url"))
    (root / "text" / "p3-references.md").write_text(p3["text"], encoding="utf-8")

    statuses: dict[str, list[str]] = {}
    for f in sorted(books_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^status: (\S+)", text, re.MULTILINE)
        s = m.group(1) if m else "MISSING"
        statuses.setdefault(s, []).append(f.stem)
    print(
        "statuses:",
        {s: len(v) for s, v in sorted(statuses.items(), key=lambda x: -len(x[1]))},
    )
    # exceptions as urls for manual investigation/fix on livelib
    for slug in statuses.get("none", []):
        note = books_dir / f"{slug}.md"
        m = re.search(r'livelib_book: "([^"]+)"', note.read_text(encoding="utf-8"))
        print(f"  NONE (no shelf list): {m.group(1) if m else slug}")

    # link validation consumes the mapping built from the notes actually written,
    # so a slug renamed by collision handling still resolves and no stale key can
    # paper over a real gap
    link_map = report["link_map"]
    res = validate_text_links(root / "text", books_dir, link_mappings_path=link_map)
    print(
        f"links: {res['total']} total, {res['resolved']} resolved, "
        f"{len(res['unresolved'])} unresolved"
    )
    if res["unresolved"]:
        for u in res["unresolved"]:
            print("  UNRESOLVED:", u["url"], f"(cited in {u.get('file', '?')})")
    # the local-target check: chapters must carry no livelib URL at all — the
    # report-only stage that tells the author which lines still need rewriting
    # (apply it with text_forge.wtd_links.rewrite_text_links(root, apply=True))
    outside = res["livelib_outside_books"]
    print(
        f"outside-books livelib links: {len(outside)}" + ("" if outside else " (clean)")
    )
    for u in outside:
        print(f"  OUTSIDE BOOKS: {u['url']} ({u['file']}:{u['line']})")
    # fail-loud ONLY on unresolved links (a lost reference is data loss);
    # NONE/OWN notes are legitimate exceptions printed above for manual review,
    # and leftover outside links are reported without failing the build — the
    # rewrite is a separate, opt-in step
    if res["unresolved"]:
        print(
            "FAIL: unresolved link above — fix on livelib (shelf/review) or in text, then re-run"
        )
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(
            "usage: uv run --project <text-forge> python -m text_forge.wtd_books_build <whattodo_root>"
        )
    sys.exit(main(sys.argv[1]))
