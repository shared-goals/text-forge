"""Regenerate whattodo/text/books/*.md from the LiveLib source.

Single entry point for the `make books` target (whattodo/Makefile):

    uv run --project ../text-forge python -m text_forge.wtd_books_build <whattodo_root>

Steps:
1. Export fresh data (shelves incl. statuses, quotes, reviews) into
   <root>/livelib-export/ — anonymous API + SSR, no credentials needed.
2. build_books() with the curation files from <root>/text/books/_curation/.
3. Replace <root>/text/books/*.md with the generated set (_curation/ untouched).
4. Validate: frontmatter contract + text links; print the status distribution.
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


def export(user_id: int, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
    c = LivelibClient()
    data = {
        "livelib-books.json": c.books(user_id),
        "livelib-quotes-api.json": c.quotes(user_id),
        "livelib-reviews-api.json": c.reviews(user_id),
    }
    for name, records in data.items():
        (out_dir / name).write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    return {name: len(records) for name, records in data.items()}


def main(root_str: str, user_id: int = 345497) -> int:
    root = Path(root_str).resolve()
    export_dir = root / "livelib-export"
    books_dir = root / "text" / "books"
    cur = books_dir / "_curation"

    counts = export(user_id, export_dir)
    print("export:", counts)

    tmp = Path(tempfile.mkdtemp(prefix="wtd-books-"))
    report = build_books(
        export_dir / "livelib-books.json",
        export_dir / "livelib-quotes-api.json",
        export_dir / "livelib-reviews-api.json",
        tmp,
        collections_path=cur / "collections.json",
        author_overrides_path=cur / "author-overrides.json",
        work_merges_path=cur / "work-merges.json",
        link_mappings_path=cur / "link-mappings.json",
        book_overrides_path=cur / "book-overrides.json",
        reference_books_path=cur / "reference-books.json",
        important_path=cur / "important.json",
    )
    print("build:", report)

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

    res = validate_text_links(root / "text", books_dir,
                              external_path=cur / "external-links.json",
                              link_mappings_path=cur / "link-mappings.json")
    print(f"links: {res['total']} total, {res['resolved']} resolved, "
          f"{res['external']} external, {len(res['unresolved'])} unresolved")
    if res["unresolved"]:
        for u in res["unresolved"]:
            print("  UNRESOLVED:", u["url"])
    return 0 if not res["unresolved"] and statuses.get("none", 0) == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: uv run --project <text-forge> python -m text_forge.wtd_books_build <whattodo_root>")
    sys.exit(main(sys.argv[1]))
