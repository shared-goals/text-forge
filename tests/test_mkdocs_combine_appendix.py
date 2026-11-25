"""EPUB appendix for cited books (`scripts/mkdocs-combine.py`, mkdocs mode).

Chapters cite books with `[Название](books/<slug>.md#quote_N)`, but the book
pages are not in the nav, so those links were dead weight in the EPUB. The
combiner now scans the nav chapters for citations, appends a
`# Приложение: цитируемая литература` section holding the cited notes, and
rewrites every book link to an anchor inside that appendix (or to the live site
URL when the book is not cited, i.e. a p3-references entry).

The script is loaded by path (like `tests/test_wtd_inventory.py`), so unit tests
can call `mode_mkdocs` directly and read the citation set it recorded.
"""

import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mkdocs-combine.py"
# spec-loading does not add the script's directory to sys.path (unlike
# `python mkdocs-combine.py`), so the sibling import (mkdocs_common) needs it.
sys.path.insert(0, str(SCRIPT_PATH.parent))

_spec = importlib.util.spec_from_file_location("mkdocs_combine", SCRIPT_PATH)
assert _spec is not None
mkdocs_combine = importlib.util.module_from_spec(_spec)
# register before exec_module: annotations resolved from sys.modules need it
sys.modules[_spec.name] = mkdocs_combine
assert _spec.loader is not None
_spec.loader.exec_module(mkdocs_combine)

SITE_URL = "https://text.sharedgoals.ru/"
BOOK_HEADER = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([^}]+)\})?\s*$", re.MULTILINE)


def combine(config_path, **kwargs):
    """Run mkdocs mode and return (text, cited-slugs, captured stderr).

    `last_cited_slugs` is the side channel the combiner reports its citation set
    through — the contract that lets a test check "p3 links do not extend it".
    """
    import io
    from contextlib import redirect_stderr

    err = io.StringIO()
    with redirect_stderr(err):
        text = mkdocs_combine.mode_mkdocs(str(config_path), **kwargs)
    cited = getattr(mkdocs_combine, "last_cited_slugs", None)
    assert cited is not None, (
        "mode_mkdocs must record the citation set in `last_cited_slugs`"
    )
    return text, cited, err.getvalue()


# --------------------------------------------------------------------------- #
# Content                                                                     #
# --------------------------------------------------------------------------- #

MKDOCS_YML = """site_name: Appendix Fixture
site_url: https://text.sharedgoals.ru/

docs_dir: docs
site_dir: site

nav:
  - 'Вводная':
    - index.md
  - 'Главы':
    - p1-chapter.md
  - References: p3-references.md
"""

INDEX_MD = """---
title: Home
created: 2024-01-15
---

# Текст

Глава ссылается на [Родную речь](books/vayl-rodnaya-rech.md#review), на [Дубас](books/dubas-momenty-schastya.md#quote_1) и на главу
[Дальше](p1-chapter.md#chapter).

/// chapter-dates
Создано: 2024-01-15
///
"""

CHAPTER_MD = """---
title: Глава
created: 2024-02-01
---

# Глава про цитаты {#chapter}

## Цитаты в главе {#chapter-quotes}

Текст с [цитатой](books/dubas-momenty-schastya.md#quote_2) и книгой без
якоря [Родная речь](books/vayl-rodnaya-rech.md).

Книга, которой нет на диске: [Нет-книга](books/otvertaya-kniga.md#quote_1).
"""

P3_MD = """---
title: Книги как фундамент
---

# Книги как фундамент

- Много счастья: [Моменты счастья](books/dubas-momenty-schastya.md)
- Список прочитанного: [Азазель](books/akunin-azazel.md#review)
- Тоже из списка: [Мастер и Маргарита](books/bulgakov-master-i-margarita.md)
"""

DUBAS_MD = """---
title: "Много счастья без занудства"
author: Алексей Дубас
tags:
  - book
status: unread
livelib_book: "https://www.livelib.ru/book/1003047920"
livelib_review: "https://www.livelib.ru/review/3575245"
---

Автор: Алексей Дубас

Полка: Непрочитённые

Ссылка: [https://www.livelib.ru/book/1003047920](https://www.livelib.ru/book/1003047920)

## Много счастья без занудства {#review}

Странно, что рецензия только одна

Первая же история сильно тянет вниз - туда, куда не хочется.

## Цитаты

> Одна история про счастье.
>
> Конец первой цитаты. ^quote_1

— [LiveLib](https://www.livelib.ru/quote/47123888)

> Вторая история про счастье. ^quote_2

— [LiveLib](https://www.livelib.ru/quote/47123889)
"""

VAYL_MD = """---
title: "Родная речь. Уроки изящной словесности"
author: Петр Вайль, Александр Генис
tags:
  - book
status: read
---

Автор: Петр Вайль, Александр Генис

## Цитаты

### 1 ^quote_1

> Радищев родил декабристов.

— [LiveLib](https://www.livelib.ru/quote/180475)
"""

AKUNIN_MD = """---
title: "Азазель"
author: Борис Акунин
status: read
---

Автор: Борис Акунин

Ссылка: [https://www.livelib.ru/book/1003629901](https://www.livelib.ru/book/1003629901)
"""


def write_project(
    root: pathlib.Path, books: dict[str, str] | None = None
) -> pathlib.Path:
    """Write the tiny content project; `books` overrides `text/books/<slug>.md`."""
    root = pathlib.Path(root)
    docs = root / "docs"
    (docs / "books").mkdir(parents=True, exist_ok=True)
    (root / "mkdocs.yml").write_text(MKDOCS_YML, encoding="utf-8")
    (docs / "index.md").write_text(INDEX_MD, encoding="utf-8")
    (docs / "p1-chapter.md").write_text(CHAPTER_MD, encoding="utf-8")
    (docs / "p3-references.md").write_text(P3_MD, encoding="utf-8")
    notes = {"dubas-momenty-schastya": DUBAS_MD, "vayl-rodnaya-rech": VAYL_MD}
    notes.update(books or {})
    for slug, text in notes.items():
        (docs / "books" / f"{slug}.md").write_text(text, encoding="utf-8")
    return root / "mkdocs.yml"


def book_section(text: str, slug: str) -> str:
    """The appendix section for `slug`, up to the next `## ` heading."""
    start = text.index(f"{{#{slug}}}")
    line_start = text.rindex("\n", 0, start) + 1
    rest = text[line_start:]
    tail = re.search(r"^## (?!#)", rest[3:], re.MULTILINE)
    return rest if tail is None else rest[: tail.start() + 3]


# --------------------------------------------------------------------------- #
# 1. citation scan                                                            #
# --------------------------------------------------------------------------- #


class TestCitationScan:
    def test_cited_set_comes_from_the_nav_chapters(self, tmp_path):
        config = write_project(tmp_path)
        _, cited, _ = combine(config)
        assert cited == {
            "dubas-momenty-schastya",
            "vayl-rodnaya-rech",
            # cited, but the note is not on disk — still part of the scan
            "otvertaya-kniga",
        }

    def test_links_in_p3_references_do_not_extend_the_citation_set(self, tmp_path):
        config = write_project(tmp_path)
        _, cited, _ = combine(config)
        # p3 repeats one cited slug and adds two books of its own
        assert "akunin-azazel" not in cited
        assert "bulgakov-master-i-margarita" not in cited
        # the one slug p3 repeats is there because a chapter cites it, not p3
        assert "dubas-momenty-schastya" in cited

    def test_appendix_holds_one_section_per_cited_book_that_exists(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "# Приложение: цитируемая литература" in text
        assert "{#dubas-momenty-schastya}" in text
        assert "{#vayl-rodnaya-rech}" in text
        # a book with no note is not in the appendix, and its links stay put
        assert "{#otvertaya-kniga}" not in text
        # ... and neither is a p3-only book
        assert "{#akunin-azazel}" not in text

    def test_sections_are_ordered_by_slug(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        dubas = text.index("{#dubas-momenty-schastya}")
        vayl = text.index("{#vayl-rodnaya-rech}")
        assert dubas < vayl  # alphabetical: d before v
        # nav order (index, chapter, p3) is untouched
        assert text.index("# Текст") < text.index("# Глава про цитаты")
        assert text.index("# Книги как фундамент") < dubas

    def test_missing_book_is_skipped_with_a_warning(self, tmp_path):
        config = write_project(tmp_path)
        text, _, err = combine(config)
        assert "otvertaya-kniga" in err
        assert "[WARN]" in err
        # the missing book leaves no half-written section behind, and its path
        # link is gone: the live site page carries that anchor
        assert "otvertaya" not in text.split("# Приложение: цитируемая")[1]
        assert (
            "[Нет-книга](https://text.sharedgoals.ru/books/otvertaya-kniga/"
            "#quote_1)" in text
        )


# --------------------------------------------------------------------------- #
# 2. appendix generation                                                      #
# --------------------------------------------------------------------------- #


class TestAppendixSection:
    def test_frontmatter_is_stripped(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        section = book_section(text, "dubas-momenty-schastya")
        assert "livelib_book" not in section
        assert "tags:" not in section
        # the note's own body survived
        assert "Полка: Непрочитённые" in section

    def test_heading_is_the_frontmatter_title_carrying_the_slug_id(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "## Много счастья без занудства {#dubas-momenty-schastya}" in text
        assert "## Родная речь. Уроки изящной словесности {#vayl-rodnaya-rech}" in text

    def test_note_headings_shift_one_level(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        section = book_section(text, "dubas-momenty-schastya")
        # `## Цитаты` arrived as `###`, the quote heading as `####`
        vayl = book_section(text, "vayl-rodnaya-rech")
        assert [len(m.group(1)) for m in BOOK_HEADER.finditer(vayl)] == [2, 3, 4]
        # the other note: its quotes are blockquote-shaped, so its headings are
        # the book section (`##`), the review (`###`) and the quotes section (`###`)
        assert [len(m.group(1)) for m in BOOK_HEADER.finditer(section)] == [2, 3, 3]

    def test_quote_text_and_attribution_are_kept(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        section = book_section(text, "dubas-momenty-schastya")
        assert "> Одна история про счастье." in section
        # the blockquote keeps its shape; only the block id leaves the last line
        assert ">\n> Конец первой цитаты." in section
        assert "> Вторая история про счастье." in section
        # livelib is an external site: the attribution link stays as it is
        assert "— [LiveLib](https://www.livelib.ru/quote/47123888)" in section

    def test_quote_id_on_a_blockquote_line_becomes_an_anchor_span(self, tmp_path):
        """The shape most real notes have: the id rides the last line of the
        blockquote, so no heading can carry it — an explicit span does, and the
        link from a chapter still lands."""
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        section = book_section(text, "dubas-momenty-schastya")
        assert '<a id="dubas-momenty-schastya-quote_1"></a>' in section
        assert '<a id="dubas-momenty-schastya-quote_2"></a>' in section
        assert "^quote_" not in section
        # the span for a blockquote sits after the block, not inside its `>` lines
        for line in section.split("\n"):
            assert not line.startswith(">") or 'id="' not in line

    def test_quote_heading_numbering_is_not_invented(self, tmp_path):
        """A quote that carries no id gets no header — nothing is invented for it."""
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        section = book_section(text, "dubas-momenty-schastya")
        # both quotes of this note are blockquote-shaped, so no `#### N` appears
        assert "#### " not in section

    def test_review_id_is_dropped(self, tmp_path):
        """`{#review}` would collide between books; the book's own `<slug>` is
        the review target, so the review heading keeps only its title."""
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "{#review}" not in text
        assert "### Много счастья без занудства\n" in text


# --------------------------------------------------------------------------- #
# 3. link rewriting                                                           #
# --------------------------------------------------------------------------- #


class TestLinkRewriting:
    def test_cited_book_link_points_at_the_book_section(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "[Родную речь](#vayl-rodnaya-rech)" in text

    def test_review_anchor_is_rewritten_to_the_book_section(self, tmp_path):
        """`#review` is documented as the review target, and the book section
        carries that anchor — so a `#review` link lands on the book."""
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "[Родную речь](#vayl-rodnaya-rech)" in text
        assert "(books/vayl-rodnaya-rech.md#review)" not in text
        # no LOCAL `#review` anchor survives: it would collide across books. Only
        # the live-site URL of an uncited book may still carry one
        assert "](#review)" not in text
        assert "(#review" not in text

    def test_quote_anchor_is_rewritten_to_the_namespaced_id(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "[Родную речь](#dubas-momenty-schastya#quote_1)" not in text
        assert "(dubas-momenty-schastya.md" not in text
        assert "(#dubas-momenty-schastya-quote_1)" in text
        assert "[цитатой](#dubas-momenty-schastya-quote_2)" in text

    def test_uncited_book_links_go_to_the_live_site(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert (
            "[Азазель](https://text.sharedgoals.ru/books/akunin-azazel/#review)" in text
        )
        assert (
            "[Мастер и Маргарита](https://text.sharedgoals.ru/books/"
            "bulgakov-master-i-margarita/)" in text
        )

    def test_uncited_book_url_is_built_from_the_config_site_url(self, tmp_path):
        config = write_project(tmp_path)
        override = "https://example.com/books-site/"
        text, _, _ = combine(config, site_url=override)
        assert f"[Азазель]({override}books/akunin-azazel/#review)" in text

    def test_site_url_default_is_the_shared_goals_site(self, tmp_path):
        import inspect

        params = inspect.signature(mkdocs_combine.mode_mkdocs).parameters
        assert "site_url" in params
        assert params["site_url"].default == SITE_URL

    def test_chapter_link_to_a_missing_book_goes_to_the_live_site(self, tmp_path):
        """A cited book whose note is absent has no appendix section, so its
        `#quote_N` can only be answered by the live page that really has it."""
        config = write_project(tmp_path)
        text, cited, _ = combine(config)
        assert "otvertaya-kniga" in cited  # cited, but skipped from the appendix
        assert "(books/otvertaya-kniga.md" not in text
        assert (
            "[Нет-книга](https://text.sharedgoals.ru/books/otvertaya-kniga/"
            "#quote_1)" in text
        )

    def test_chapter_links_still_rewrite_to_their_anchors(self, tmp_path):
        """The old behaviour of the combiner survives the appendix work."""
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        assert "[Дальше](#chapter)" in text


# --------------------------------------------------------------------------- #
# 4. id collision guard                                                       #
# --------------------------------------------------------------------------- #


class TestIdCollisionGuard:
    def test_duplicate_note_id_fails_loudly(self, tmp_path):
        """A note whose own heading already carries the slug id would give two
        sections the same anchor — that must raise, not rename silently."""
        stolen = DUBAS_MD.replace(
            "## Много счастья без занудства {#review}",
            "## Много счастья без занудства {#vayl-rodnaya-rech}",
        )
        config = write_project(tmp_path, books={"vayl-rodnaya-rech": stolen})
        with pytest.raises(ValueError, match="vayl-rodnaya-rech"):
            combine(config)

    def test_duplicate_quote_id_fails_loudly(self, tmp_path):
        """One note declaring the same block id twice would emit it twice."""
        stolen = VAYL_MD.replace(
            "### 1 ^quote_1", "### 1 ^quote_1\n\n> Ещё цитата. ^quote_1\n"
        )
        config = write_project(tmp_path, books={"vayl-rodnaya-rech": stolen})
        with pytest.raises(ValueError, match="vayl-rodnaya-rech-quote_1"):
            combine(config)

    def test_duplicate_blockquote_anchor_fails_loudly(self, tmp_path):
        """The span shape is guarded too: two identical ids in one document."""
        stolen = DUBAS_MD.replace(
            "> Конец первой цитаты. ^quote_1", "> Конец первой цитаты. ^quote_2"
        )
        config = write_project(tmp_path, books={"dubas-momenty-schastya": stolen})
        with pytest.raises(ValueError, match="dubas-momenty-schastya-quote_2"):
            combine(config)

    def test_a_chapter_anchor_colliding_with_a_slug_fails_loudly(self, tmp_path):
        """The guard looks at the WHOLE document, not only the appendix."""
        chapter = CHAPTER_MD.replace("{#chapter}", "{#vayl-rodnaya-rech}")
        config = write_project(tmp_path)
        (config.parent / "docs" / "p1-chapter.md").write_text(chapter, encoding="utf-8")
        with pytest.raises(ValueError, match="vayl-rodnaya-rech"):
            combine(config)

    def test_the_plain_project_has_no_collision(self, tmp_path):
        config = write_project(tmp_path)
        text, _, _ = combine(config)
        # ids arrive in two shapes: heading attributes and `<a id="…">` spans
        ids = re.findall(r"\{#([^}]+)\}", text) + re.findall(r'id="([^"]+)"', text)
        assert ids, "the appendix should declare anchors"
        assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------- #
# 5. end to end: combine -> pandoc -> EPUB                                    #
# --------------------------------------------------------------------------- #


def run_pandoc(*args, cwd=None):
    proc = subprocess.run(
        ["pandoc", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        raise AssertionError(f"pandoc failed ({proc.returncode}):\n{proc.stderr}")
    return proc


def test_epub_contains_the_appendix_anchors(tmp_path):
    """combine -> pandoc (lua filter) -> epub3, then read the EPUB XHTML."""
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not installed")

    project = write_project(tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    docs = tmp_path / "docs"

    combined = build / "text_combined.md"
    combined.write_text(mkdocs_combine.mode_mkdocs(str(project)), encoding="utf-8")

    normalized = build / "pandoc.md"
    run_pandoc(
        str(combined),
        "--from",
        "markdown",
        "--to",
        "markdown",
        "--lua-filter",
        str(REPO_ROOT / "scripts" / "pymdown-pandoc.lua"),
        "--output",
        str(normalized),
        cwd=tmp_path,
    )

    epub = build / "book.epub"
    run_pandoc(
        str(normalized),
        "--from",
        "markdown+smart",
        "--to",
        "epub3",
        "--standalone",
        "--toc",
        "--toc-depth=2",
        "--resource-path",
        str(docs),
        "--output",
        str(epub),
        cwd=tmp_path,
    )

    assert epub.exists() and epub.stat().st_size > 0
    with zipfile.ZipFile(epub) as zf:
        pages = [
            (pathlib.PurePosixPath(name).name, zf.read(name).decode("utf-8", "replace"))
            for name in sorted(zf.namelist())
            if name.endswith((".xhtml", ".html"))
        ]
    xhtml = "\n".join(body for _, body in pages)

    # the appendix landed in the book, with the anchors the chapters point at
    assert "Приложение: цитируемая литература" in xhtml
    assert 'id="dubas-momenty-schastya"' in xhtml
    assert 'id="vayl-rodnaya-rech"' in xhtml
    # a heading-shaped id arrives as a section id, a blockquote-shaped one as a
    # span — both must survive the two pandoc passes
    assert 'id="vayl-rodnaya-rech-quote_1"' in xhtml
    assert 'id="dubas-momenty-schastya-quote_1"' in xhtml
    assert 'id="dubas-momenty-schastya-quote_2"' in xhtml
    # pandoc may re-emit a span as an element; either way the id is there
    assert xhtml.count('id="dubas-momenty-schastya-quote_1"') >= 1
    # no dangling book links left in the XHTML
    assert "books/dubas-momenty-schastya.md" not in xhtml
    # external attribution survived
    assert "https://www.livelib.ru/quote/47123888" in xhtml
    # and every link into the book resolves to an id that exists in it. Pandoc
    # rewrites a cross-file `#slug` into `chNNN.xhtml#slug`, so anchors are
    # compared as (file, id) pairs. External links are not the book's business —
    # the live site is — so only relative targets are checked.
    own_pages = {name for name, _ in pages}
    ids: set[tuple[str, str]] = set()
    for name, body in pages:
        ids.update((name, anchor) for anchor in re.findall(r'\bid="([^"]+)"', body))
    targets: set[tuple[str, str]] = set()
    for name, body in pages:
        for anchor in re.findall(r'href="#([^"]+)"', body):
            targets.add((name, anchor))
        for target, anchor in re.findall(r'href="([^"#:]+)#([^"/]+)"', body):
            file_name = pathlib.PurePosixPath(target).name
            if file_name in own_pages:
                targets.add((file_name, anchor))
    broken = {
        f"{src}#{anchor}" for (src, anchor) in targets if (src, anchor) not in ids
    }
    assert not broken, f"dangling anchors in EPUB: {sorted(broken)}"
    # the chapters really link into the appendix, not just near it
    assert ("ch004.xhtml", "dubas-momenty-schastya-quote_1") in targets
    assert ("ch004.xhtml", "vayl-rodnaya-rech") in targets


def test_cli_combine_writes_the_appendix(tmp_path):
    """`text-forge epub` drives the same script through build.py — the appendix
    must reach `build/text_combined.md`.

    The installed copy under `sys.prefix/share/text-forge/scripts/` is what
    `build.py` resolves, and it is a HARD link to `scripts/`, so an edited
    script is live without a reinstall. The assertions below pin a book section,
    which only the new code can produce.
    """
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not installed")

    project = write_project(tmp_path)
    build = tmp_path / "build"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "text_forge.cli",
            "epub",
            "--config",
            str(project),
            "--build-dir",
            str(build),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    combined = (build / "text_combined.md").read_text(encoding="utf-8")
    assert "# Приложение: цитируемая литература" in combined
    assert "## Много счастья без занудства {#dubas-momenty-schastya}" in combined
