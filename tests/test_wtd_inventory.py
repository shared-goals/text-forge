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


BOOK_TITLED_REVIEW_MD = """---
title: "Сказать жизни «Да»: психолог в концлагере"
author: Виктор Франкл
my_mark: 5
status: read
---

Полка: Прочтённые

## Важность ответа на вопрос о Смысле Жизни {#review}

Review paragraph one about the book.

Review paragraph two with more thoughts.

## Цитаты

A quote that must never be ingested: QUOTE-MARKER-TITLED.
"""

BOOK_TITLED_REVIEW_WITH_AUTHOR_MD = """---
title: "Тяжёлый песок"
author: Анатолий Рыбаков
status: read
---

Полка: Прочтённые

## Человек ищет опору {#review}

Review body of the titled-note book.
"""

BOOK_BOTH_SHAPES_MD = """---
title: "Две формы"
author: Автор Двойной
status: read
---

Полка: Прочтённые

## Первая форма заголовка {#review}

Text of the anchored review.

## Рецензия

Text of the legacy review that must not become a second document.
"""

BOOK_ANCHORED_ELSEWHERE_MD = """---
title: "Якорь не здесь"
author: Автор Другой
status: read
---

Полка: Прочтённые

## Введение {#intro}

An anchored heading that is not the review.

## Цитаты

Only quotes: QUOTE-MARKER-OTHER.
"""

BOOK_FENCED_HEADING_MD = """---
title: "Заголовок в коде"
author: Автор В коде
status: read
---

Полка: Прочтённые

```markdown
## Заголовок внутри код-блока {#review}
```

## Рецензия

The real review sits after the fence.
"""

BOOK_FENCED_LEGACY_MD = """---
title: "Только в коде"
author: Автор Вне кода
status: read
---

Полка: Прочтённые

```markdown
## Рецензия
```

No real review here at all.
"""


# --- Hindsight opt-out -------------------------------------------------------
#
# A generated projection page (p3-references) carries `hindsight: exclude: true`
# in its own frontmatter: its content is a copy of the book notes' review
# titles, so ingesting it would duplicate theses and re-ingest the whole page on
# every regeneration. The inventory is the place the flag must be honored: omit
# the chapter there and every downstream consumer (the ingest wrapper's
# filter_targets, hindsight-ingest) stops seeing it without knowing the name.

EXCLUDED_PUBLISHED_MD = """---
title: "Книги как фундамент"
search:
  exclude: true
hindsight:
  exclude: true
---

# Книги как фундамент

## Ссылки {#links}

A projected list that must never reach memory.
"""

EXCLUDED_DRAFT_MD = """---
title: "Draft projection"
hindsight:
  exclude: true
---

# Draft projection

## Body {#body}

Draft text that must never reach memory either.
"""

HINDSIGHT_KEY_WITHOUT_EXCLUDE_MD = """---
title: "Empty mapping"
hindsight:
---

# Empty mapping

## Body {#body}

A `hindsight:` key with no value excludes nothing.
"""

HINDSIGHT_EXCLUDE_FALSE_MD = """---
title: "Explicit opt-in"
hindsight:
  exclude: false
---

# Explicit opt-in

## Body {#body}

`exclude: false` means include.
"""

HINDSIGHT_EXCLUDE_STRING_TRUE_MD = """---
title: "Quoted flag"
hindsight:
  exclude: "true"
---

# Quoted flag

## Body {#body}

A quoted `"true"` is the same decision as a bare one.
"""

HINDSIGHT_NOT_A_MAPPING_MD = """---
title: "Bad shape"
hindsight: true
---

# Bad shape

## Body {#body}

A scalar `hindsight:` is not a mapping: not an exclusion.
"""

BOOK_FIXTURES = {
    "with-review.md": BOOK_WITH_REVIEW_MD,
    "no-review.md": BOOK_NO_REVIEW_MD,
    "no-mark.md": BOOK_NO_MARK_MD,
    "title-only.md": BOOK_TITLE_ONLY_MD,
    "titled-review.md": BOOK_TITLED_REVIEW_MD,
    "titled-review-author.md": BOOK_TITLED_REVIEW_WITH_AUTHOR_MD,
    "both-shapes.md": BOOK_BOTH_SHAPES_MD,
    "anchored-elsewhere.md": BOOK_ANCHORED_ELSEWHERE_MD,
    "fenced-heading.md": BOOK_FENCED_HEADING_MD,
    "fenced-legacy.md": BOOK_FENCED_LEGACY_MD,
}

# Non-book pages exercising the `hindsight.exclude` frontmatter flag. None of
# them are in nav by default, so they arrive as drafts; tests that need a
# published one pass it via `make_project(nav_extra=[...])`.
EXTRA_PAGE_FIXTURES = {
    "p3-references.md": EXCLUDED_PUBLISHED_MD,
    "draft-excluded.md": EXCLUDED_DRAFT_MD,
    "hindsight-empty.md": HINDSIGHT_KEY_WITHOUT_EXCLUDE_MD,
    "hindsight-false.md": HINDSIGHT_EXCLUDE_FALSE_MD,
    "hindsight-quoted.md": HINDSIGHT_EXCLUDE_STRING_TRUE_MD,
    "hindsight-scalar.md": HINDSIGHT_NOT_A_MAPPING_MD,
}


def make_project(tmp_path: Path, nav_extra: list[str] = ()) -> Path:
    """Minimal MkDocs project: docs_dir `text`, nav with index.md only.

    `nav_extra` publishes extra docs-relative paths, so a test can make a
    fixture chapter published instead of draft.
    """
    config = tmp_path / "mkdocs.yml"
    nav = ["  - index.md\n"] + [f"  - {entry}\n" for entry in nav_extra]
    config.write_text(
        "site_name: Test\n"
        "site_url: https://example.org/\n"
        "repo_url: https://github.com/example/repo\n"
        "docs_dir: text\n"
        "nav:\n" + "".join(nav),
        encoding="utf-8",
    )
    docs = tmp_path / "text"
    (docs / "books").mkdir(parents=True)
    (docs / "index.md").write_text(INDEX_MD, encoding="utf-8")
    for name, content in BOOK_FIXTURES.items():
        (docs / "books" / name).write_text(content, encoding="utf-8")
    for name, content in EXTRA_PAGE_FIXTURES.items():
        (docs / name).write_text(content, encoding="utf-8")
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


def test_titled_review_heading_is_a_review_section(tmp_path: Path):
    """New shape: `## <review title> {#review}` -> the same stable identity."""
    chapters = build_chapters(tmp_path)
    book = chapters["books/titled-review"]
    assert len(book["sections"]) == 1
    section = book["sections"][0]
    assert section["section_uid"] == "review"
    # the anchor mirrors the real attribute, the way regular chapters do
    assert section["anchor"] == "review"
    # heading is the title text alone, without the {...} attribute
    assert section["heading"] == "Важность ответа на вопрос о Смысле Жизни"
    assert section["heading_level"] == 2


def test_titled_review_section_text_prefix_heading_and_excluded_quotes(
    tmp_path: Path,
):
    chapters = build_chapters(tmp_path)
    section = chapters["books/titled-review"]["sections"][0]
    text = section["text"]
    assert text.startswith(
        "Книга: «Сказать жизни «Да»: психолог в концлагере» — Виктор Франкл."
    )
    assert "Оценка: 5." in text
    assert "Полка: Прочтённые." in text
    lines = text.splitlines()
    assert "## Важность ответа на вопрос о Смысле Жизни {#review}" in lines
    assert "Review paragraph one about the book." in text
    assert "Review paragraph two with more thoughts." in text
    assert "## Цитаты" not in text
    assert "QUOTE-MARKER-TITLED" not in text


def test_titled_review_section_keeps_the_page_url(tmp_path: Path):
    """The pinned contract: a book section's url is the note's page url — the
    one hindsight-ingest writes into metadata['url']. A per-section anchor is
    carried in the `anchor` field (and so in the `anchor:` tag), not by
    rewriting the url, which is how every existing book section works."""
    chapters = build_chapters(tmp_path)
    legacy = chapters["books/with-review"]["sections"][0]
    titled = chapters["books/titled-review"]["sections"][0]
    assert titled["url"] == "https://example.org/books/titled-review/"
    assert legacy["url"] == "https://example.org/books/with-review/"
    assert titled["anchor"] == "review"


def test_titled_review_heading_text_is_not_assumed_to_be_review_word(tmp_path: Path):
    """The heading text comes from the file, not from the constant."""
    chapters = build_chapters(tmp_path)
    section = chapters["books/titled-review-author"]["sections"][0]
    assert section["heading"] == "Человек ищет опору"
    assert section["section_uid"] == "review"
    assert "Review body of the titled-note book." in section["text"]


def test_legacy_heading_still_works_with_new_writer_present(tmp_path: Path):
    """Not-yet-rebuilt files keep their legacy identity: uid review, no anchor."""
    chapters = build_chapters(tmp_path)
    legacy = chapters["books/with-review"]["sections"][0]
    titled = chapters["books/titled-review"]["sections"][0]
    assert legacy["section_uid"] == "review" and legacy["anchor"] is None
    assert titled["section_uid"] == "review" and titled["anchor"] == "review"
    assert legacy["heading"] == "Рецензия"


def test_file_with_both_shapes_yields_one_review_section(tmp_path: Path):
    """Synthetic double: the first matching heading wins, no duplicate keys."""
    chapters = build_chapters(tmp_path)
    book = chapters["books/both-shapes"]
    assert len(book["sections"]) == 1
    section = book["sections"][0]
    assert section["section_uid"] == "review"
    assert section["anchor"] == "review"
    assert section["heading"] == "Первая форма заголовка"
    assert "Text of the anchored review." in section["text"]
    assert "Text of the legacy review" not in section["text"]
    # a second `review` section in the same chapter would surface as a
    # duplicate document key here
    assert (
        wtd_inventory.validate_inventory(
            wtd_inventory.build_inventory(
                tmp_path / "mkdocs.yml", include_drafts=True
            ).chapters
        )
        == []
    )


def test_anchored_heading_other_than_review_is_not_a_book_section(tmp_path: Path):
    """Books are review-only: a `{#intro}` anchor names no review section."""
    chapters = build_chapters(tmp_path)
    assert chapters["books/anchored-elsewhere"]["sections"] == []


def test_anchored_review_inside_code_fence_is_not_a_section(tmp_path: Path):
    """Code-fence safety applies to the new shape too: the fence is sample text."""
    chapters = build_chapters(tmp_path)
    book = chapters["books/fenced-heading"]
    assert len(book["sections"]) == 1
    section = book["sections"][0]
    # the fenced `{#review}` is skipped, the legacy heading below is found
    assert section["anchor"] is None
    assert section["heading"] == "Рецензия"
    assert "The real review sits after the fence." in section["text"]
    assert "## Заголовок внутри код-блока" not in section["text"]


def test_legacy_heading_inside_code_fence_only_yields_no_section(tmp_path: Path):
    chapters = build_chapters(tmp_path)
    assert chapters["books/fenced-legacy"]["sections"] == []


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
    assert {
        "index",
        "books/with-review",
        "books/no-review",
        "books/no-mark",
        "books/titled-review",
        "books/both-shapes",
    } <= slugs
    review_uids = {
        f"{ch['chapter']}#{s['section_uid']}"
        for ch in inv["chapters"]
        for s in ch["sections"]
    }
    assert "books/titled-review#review" in review_uids
    assert "books/both-shapes#review" in review_uids


# --- hindsight.exclude: the inventory is where the flag is honored ----------


def slugs(tmp_path: Path, nav_extra: list[str] = ()) -> set[str]:
    """Chapter slugs of the fixture project, extra paths published via nav."""
    inv = wtd_inventory.build_inventory(
        make_project(tmp_path, nav_extra=list(nav_extra)), include_drafts=True
    )
    return {ch["chapter"] for ch in asdict(inv)["chapters"]}


def test_excluded_published_chapter_is_absent_from_inventory(tmp_path: Path):
    """`hindsight.exclude: true` removes the chapter entirely, not just its sections.

    The flag is a nav-published chapter here: status does not rescue it. Omitting
    the Chapter object (instead of emitting one with empty sections) is what makes
    the ingest wrapper report "chapter missing from inv" rather than ingest an
    empty document.
    """
    inv = wtd_inventory.build_inventory(
        make_project(tmp_path, nav_extra=["p3-references.md"]), include_drafts=True
    )
    by_slug = {ch["chapter"]: ch for ch in asdict(inv)["chapters"]}
    assert "p3-references" not in by_slug
    assert "index" in by_slug
    # the exclusion is total: no chapter entry means no sections, no url, no
    # document key for anything the page contains
    assert all(ch["chapter"] != "p3-references" for ch in asdict(inv)["chapters"])
    # the nav still lists it: the exclusion is memory-only, the page stays on the site
    assert "  - p3-references.md\n" in (tmp_path / "mkdocs.yml").read_text(
        encoding="utf-8"
    )
    # and the chapter really was published before being skipped (not a phantom)
    assert (tmp_path / "text" / "p3-references.md").exists()
    assert inv.warnings == []


def test_excluded_draft_chapter_is_absent_from_inventory(tmp_path: Path):
    """The draft path honors the flag too — same rule, both loops."""
    slugs_ = slugs(tmp_path)
    assert "draft-excluded" not in slugs_
    assert "index" in slugs_


def test_excluded_chapter_absent_without_include_drafts(tmp_path: Path):
    """Published-only run: the excluded nav chapter is still skipped."""
    config = make_project(tmp_path, nav_extra=["p3-references.md"])
    inv = wtd_inventory.build_inventory(config, include_drafts=False)
    assert {ch["chapter"] for ch in asdict(inv)["chapters"]} == {"index"}


def test_hindsight_key_without_exclude_key_is_included(tmp_path: Path):
    """Sub-case 1: `hindsight:` with no `exclude` key is not an opt-out."""
    assert "hindsight-empty" in slugs(tmp_path)


def test_hindsight_exclude_false_is_included(tmp_path: Path):
    """Sub-case 2: `exclude: false` is an explicit opt-in."""
    assert "hindsight-false" in slugs(tmp_path)


def test_chapter_without_hindsight_key_is_included(tmp_path: Path):
    """Sub-case 3: no `hindsight` key at all — the default, included."""
    chapters = slugs(tmp_path)
    assert "index" in chapters
    assert "books/with-review" in chapters
    # none of the pre-existing fixtures gained the flag
    assert {"hindsight-empty", "hindsight-false", "hindsight-scalar"} <= chapters
    # and the only exclusions are exactly the two flagged pages
    assert "p3-references" not in chapters
    assert "draft-excluded" not in chapters
    assert "hindsight-quoted" not in chapters


def test_existing_chapters_unaffected_by_the_flag_rule(tmp_path: Path):
    """The flag rule changes nothing for pages that do not carry it."""
    chapters = build_chapters(tmp_path)
    assert chapters["index"]["title"] == "Intro page"
    assert [s["section_uid"] for s in chapters["index"]["sections"]] == [
        "intro",
        "second",
    ]
    assert len(chapters["books/with-review"]["sections"]) == 1
    assert chapters["books/no-review"]["sections"] == []


def test_hindsight_exclude_quoted_true_is_excluded(tmp_path: Path):
    """`exclude: "true"` (a string) is the same decision as the bare bool."""
    assert "hindsight-quoted" not in slugs(tmp_path)


def test_hindsight_scalar_is_not_an_exclusion(tmp_path: Path):
    """`hindsight: true` is not the documented shape — treated as no opt-out.

    The helper requires a mapping, so a scalar cannot silently exclude a chapter
    through a malformed frontmatter edit.
    """
    assert "hindsight-scalar" in slugs(tmp_path)


def test_exclusion_helper_reads_frontmatter_dict():
    """The helper is exported and works on a plain frontmatter dict."""
    assert hasattr(wtd_inventory, "excluded_from_memory")
    assert wtd_inventory.excluded_from_memory({"hindsight": {"exclude": True}}) is True
    assert (
        wtd_inventory.excluded_from_memory({"hindsight": {"exclude": "true"}}) is True
    )
    assert (
        wtd_inventory.excluded_from_memory({"hindsight": {"exclude": False}}) is False
    )
    assert wtd_inventory.excluded_from_memory({"hindsight": {}}) is False
    assert wtd_inventory.excluded_from_memory({"hindsight": None}) is False
    assert wtd_inventory.excluded_from_memory({"hindsight": "true"}) is False
    assert wtd_inventory.excluded_from_memory({}) is False
