import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "wtd-inventory.py"
# spec-loading does not add the script's directory to sys.path (unlike
# `python wtd-inventory.py`), so sibling imports (mkdocs_common,
# wtd_sections_common) need the scripts dir on the path explicitly.
sys.path.insert(0, str(SCRIPT_PATH.parent))

spec = importlib.util.spec_from_file_location("wtd_inventory", SCRIPT_PATH)
assert spec is not None
wtd_inventory = importlib.util.module_from_spec(spec)
# dataclass field annotation resolution under PEP 563 (from __future__ import
# annotations) looks the defining module up in sys.modules, so register it
# before exec_module or every @dataclass in the script blows up.
sys.modules[spec.name] = wtd_inventory
assert spec.loader is not None
spec.loader.exec_module(wtd_inventory)


INDEX_MD = """# Intro page

## Intro {#intro}

Intro paragraph text.

## Second {#second}

Second paragraph text.
"""

BOOK_WITH_REVIEW_MD = """---
title: "Сказать жизни «Да»: психолог в концлагере"
author: Виктор Франкл
my_mark: 5
status: read
---

Автор: Виктор Франкл

Полка: Прочтённые

Ссылка: [https://livelib.ru/book/1](https://livelib.ru/book/1)

## Рецензия

Review paragraph one about the book.

Review paragraph two with more thoughts.

## Цитаты

A quote that must never be ingested: QUOTE-MARKER-XYZ.

Another quote: QUOTE-MARKER-2.
"""

BOOK_NO_REVIEW_MD = """---
title: "Прощание с бумажкой"
author: Дмитрий Гришковец
status: read
---

Полка: Хочу прочитать

## Цитаты

Only quotes here: QUOTE-MARKER-NOPE.
"""

BOOK_NO_MARK_MD = """---
title: "Без оценки"
author: Автор Авторов
status: wish
---

Полка: Хочу прочитать

## Рецензия

Short review text without a rating in frontmatter.
"""

BOOK_TITLE_ONLY_MD = """---
title: "Лунная пыль"
status: read
---

Полка: Прочтённые

## Рецензия

A review of a book whose frontmatter has no author.
"""


def make_project(tmp_path: Path) -> Path:
    """Minimal MkDocs project: docs_dir `text`, nav with index.md only."""
    config = tmp_path / "mkdocs.yml"
    config.write_text(
        "site_name: Test\n"
        "site_url: https://example.org/\n"
        "repo_url: https://github.com/example/repo\n"
        "docs_dir: text\n"
        "nav:\n"
        "  - index.md\n",
        encoding="utf-8",
    )
    docs = tmp_path / "text"
    (docs / "books").mkdir(parents=True)
    (docs / "index.md").write_text(INDEX_MD, encoding="utf-8")
    (docs / "books" / "with-review.md").write_text(
        BOOK_WITH_REVIEW_MD, encoding="utf-8"
    )
    (docs / "books" / "no-review.md").write_text(BOOK_NO_REVIEW_MD, encoding="utf-8")
    (docs / "books" / "no-mark.md").write_text(BOOK_NO_MARK_MD, encoding="utf-8")
    (docs / "books" / "title-only.md").write_text(BOOK_TITLE_ONLY_MD, encoding="utf-8")
    return config


def build_chapters(tmp_path: Path) -> dict[str, dict]:
    inv = wtd_inventory.build_inventory(make_project(tmp_path), include_drafts=True)
    # build_inventory returns dataclasses; normalize via asdict like the CLI does.
    return {ch["chapter"]: ch for ch in asdict(inv)["chapters"]}


def test_inventory_reports_all_books_as_drafts(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    assert "index" in chapters
    assert chapters["index"]["status"] == "published"
    for slug in ("books/with-review", "books/no-review", "books/no-mark"):
        assert slug in chapters
        assert chapters[slug]["status"] == "draft"


def test_book_with_review_has_single_review_section(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    book = chapters["books/with-review"]
    assert len(book["sections"]) == 1
    section = book["sections"][0]
    assert section["section_uid"] == "review"
    assert section["heading"] == "Рецензия"
    assert section["heading_level"] == 2
    assert section["anchor"] is None


def test_review_section_text_has_book_prefix_and_excludes_quotes(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    section = chapters["books/with-review"]["sections"][0]
    text = section["text"]

    assert text.startswith(
        "Книга: «Сказать жизни «Да»: психолог в концлагере» — Виктор Франкл."
    )
    assert "Оценка: 5." in text
    assert "Полка: Прочтённые." in text
    assert "Review paragraph one about the book." in text
    assert "Review paragraph two with more thoughts." in text

    # Quotes section must not leak into the review section text.
    assert "## Цитаты" not in text
    assert "QUOTE-MARKER-XYZ" not in text
    assert "QUOTE-MARKER-2" not in text
    # Body preamble is not part of the review either.
    assert "Ссылка:" not in text


def test_review_section_starts_with_prefix_then_heading_line(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    section = chapters["books/with-review"]["sections"][0]
    lines = section["text"].splitlines()
    assert lines[0].startswith("Книга: «")
    assert "## Рецензия" in lines


def test_book_without_review_has_zero_sections(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    book = chapters["books/no-review"]
    assert book["sections"] == []
    assert all(s["section_uid"] != "chapter" for s in book["sections"])


def test_book_chapter_title_uses_title_and_author(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    assert (
        chapters["books/with-review"]["title"]
        == "Сказать жизни «Да»: психолог в концлагере — Виктор Франкл"
    )


def test_review_prefix_omits_rating_when_frontmatter_has_no_my_mark(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    sections = chapters["books/no-mark"]["sections"]
    assert len(sections) == 1
    text = sections[0]["text"]
    assert text.startswith("Книга: «Без оценки» — Автор Авторов.")
    assert "Оценка:" not in text
    assert "Полка: Хочу прочитать." in text


def test_review_prefix_closes_quote_when_frontmatter_has_no_author(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    sections = chapters["books/title-only"]["sections"]
    assert len(sections) == 1
    text = sections[0]["text"]
    assert text.startswith("Книга: «Лунная пыль».")
    assert "A review of a book whose frontmatter has no author." in text


def test_regular_chapter_sections_unchanged(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    index = chapters["index"]
    assert index["title"] == "Intro page"
    uids = [s["section_uid"] for s in index["sections"]]
    assert uids == ["intro", "second"]
    assert index["sections"][0]["anchor"] == "intro"
    assert index["sections"][0]["text"].startswith("## Intro {#intro}")


def test_cli_json_output_reports_no_warnings(tmp_path: Path):
    config = make_project(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--config",
            str(config),
            "--include-drafts",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    inv = json.loads(result.stdout)
    assert inv["warnings"] == []
    assert inv["docs_dir"] == "text"
    slugs = {ch["chapter"] for ch in inv["chapters"]}
    assert {"index", "books/with-review", "books/no-review", "books/no-mark"} <= slugs
