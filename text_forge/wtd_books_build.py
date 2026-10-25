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
from text_forge.wtd_books import build_books, validate_text_links

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
        eid = _book_url_id(r.get("book_url")
                           or (r.get("art_edition") or {}).get("url") or "")
        out.add(str(qid or rid or eid))
    return out


def _book_url_id(url: str) -> str:
    m = re.search(r"/(?:book|work)/(\d+)", url or "")
    return m.group(1) if m else ""


def export(user_id: int, out_dir: Path) -> dict:
    """Fetch the three export files, reporting what a previous run held and this
    one does not (or vice versa).

    The old file is read BEFORE it is overwritten, so a record the user deleted
    on livelib is named by its id rather than lost: the corpus can then be
    checked against a known set instead of a silently shortened one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
    c = LivelibClient()
    counts: dict[str, int] = {}
    for name, get in (("livelib-books.json", lambda: c.books(user_id)),
                     ("livelib-quotes-api.json", lambda: c.quotes(user_id)),
                     ("livelib-reviews-api.json", lambda: c.reviews(user_id))):
        path = out_dir / name
        old = _record_ids(json.loads(path.read_text(encoding="utf-8"))) \
            if path.exists() else None
        records = get()
        path.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        counts[name] = len(records)
        if old is not None:
            new = _record_ids(records)
            if old - new:
                print(f"  {name}: LOST {sorted(old - new)}")
            if new - old:
                print(f"  {name}: NEW {sorted(new - old)}")
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
    report = build_books(
        export_dir / "livelib-books.json",
        export_dir / "livelib-quotes-api.json",
        export_dir / "livelib-reviews-api.json",
        tmp,
        curation_path=curation,
        text_dir=root / "text",
        editions_cache_path=export_dir / "editions-cache.json",
    )
    print("build:", {k: v for k, v in report.items() if k != "link_map"})
    link_map = report["link_map"]
    for bid in report.get("unresolved_reference_books") or []:
        print("  WARNING: cited edition not resolvable via livelib:", bid)

    # the mapping the notes declare, written beside the curation file: the link
    # validator and the bibliography generator consume it, and keeping it makes a
    # rebuild's id->note decisions auditable
    (cur / "link-map.json").write_text(
        json.dumps(link_map, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    for old in books_dir.glob("*.md"):
        old.unlink()
    for gen in tmp.glob("*.md"):
        shutil.copy2(gen, books_dir / gen.name)

    statuses: dict[str, int] = {}
    for f in books_dir.glob("*.md"):
        m = re.search(r"^status: (\S+)", f.read_text(encoding="utf-8"), re.M)
        s = m.group(1) if m else "MISSING"
        statuses[s] = statuses.get(s, 0) + 1
    print("statuses:", dict(sorted(statuses.items(), key=lambda x: -x[1])))

    # link validation consumes the mapping built from the notes actually written,
    # so a slug renamed by collision handling still resolves and no stale key can
    # paper over a real gap
    res = validate_text_links(root / "text", books_dir,
                             link_mappings_path=link_map)
    print(f"links: {res['total']} total, {res['resolved']} resolved, "
          f"{len(res['unresolved'])} unresolved")
    if res["unresolved"]:
        for u in res["unresolved"]:
            print("  UNRESOLVED:", u["url"])
    return 0 if not res["unresolved"] and statuses.get("none", 0) == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: uv run --project <text-forge> python -m text_forge.wtd_books_build <whattodo_root>")
    sys.exit(main(sys.argv[1]))
