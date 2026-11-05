"""Tests for text_forge.migrate_curation: curation.jsonc -> Curation.md.

The migration is a ONE-OFF rewrite, so its output is pinned exactly: the doc
block, the section order, and the ×10 on weights are all decisions a human made
once, and a drift in them is a silent change to the corpus's ordering. Two
properties matter most: the output is byte-identical on a re-run, and it feeds
back through load_curation as the entries the jsonc held.
"""

import json
import subprocess
import sys

import pytest

from text_forge import migrate_curation
from text_forge.wtd_books import load_curation

# the old file: // comments carrying titles, a merges entry, an author override,
# and entries with no weight at all
OLD = """\
// Curation for text/books — one entry per livelib edition id.
// JSONC: // and /* */ comments are stripped by load_curation() before parse.
{
  "books": {
    // Моменты счастья — Алекс Дубас
    // @url:`https://www.livelib.ru/book/1003047920`
    "1003047920": {"weight": 1},
    /* a block comment, for the eye only */
    // Стратегическая психология глобализации — Александр Юрьев
    // @url:`https://www.livelib.ru/book/1001128870`
    "1001128870": {
      "weight": 3,
      "author": "Александр Юрьев"
    },
    // Зона — Сергей Довлатов
    "1000699994": {
      "status": "read"
    },
    // Сказать жизни «Да»: психолог в концлагере — Виктор Франкл
    // @url:`https://www.livelib.ru/book/1000225484`
    "1000225484": {
      "weight": 5,
      "merges": [
        // Сказать жизни "Да!": психолог в концлагере — Виктор Франкл
        // @url:`https://www.livelib.ru/book/1005482422`
        1005482422,
        // Скажи жизни Да — Виктор Франкл
        1007148466
      ]
    },
    // Моя жизнь — Генри Форд
    "1009172287": {}
  }
}
"""

# what that file must become: doc block, then weight ascending, then the
# weightless entries by id. The eye text is carried from the jsonc comment the
# id carries: title for a key written on a line of its own, and the member
# titles below the merges bullet, where the old file wrote them as comments.
NEW = """\
# Curation

Одна секция — одна редакция книги.

Заголовок секции — это id издания с LiveLib: `## <id> — <название>`.
id слева от тире читает сборка; название справа — только для глаз, сборка его
не трогает. Строки ниже — поля секции.

Что можно писать под заголовком секции (любой набор, в любом порядке).
weight — вес книги, целое число. Вес умножен на 10 по сравнению со старым
файлом: между соседними книгами остаются дырки, чтобы новую книгу можно было
вставить между ними, не перекладывая половину списка (15, 25, 110).
merges — id других изданий той же работы, через запятую. Их цитаты и отзыв
достаются этой заметке. author — автор, если LiveLib его не указал или указал
неверно. status — read / reading / stop, если полка LiveLib врёт.

Поля `my_mark` здесь нет: оценку сборка берёт с полки LiveLib, ей и верить.
Пустая секция (без полей) тоже законна: id уже говорит «эта книга в списке».

## 1003047920 — Моменты счастья — Алекс Дубас
- weight: 10

## 1001128870 — Стратегическая психология глобализации — Александр Юрьев
- weight: 30
- author: Александр Юрьев

## 1000225484 — Сказать жизни «Да»: психолог в концлагере — Виктор Франкл
- weight: 50
- merges: 1005482422, 1007148466

## 1000699994 — Зона — Сергей Довлатов
- status: read

## 1009172287 — Моя жизнь — Генри Форд
"""

BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}


# the header every generated Curation.md carries: tests that write a section
# file need it, because a bullet outside a `## <id>` section is a hard error
DOC = """# Curation

Одна секция — одна редакция книги.

Заголовок секции — это id издания с LiveLib: `## <id> — <название>`.
id слева от тире читает сборка; название справа — только для глаз, сборка его
не трогает. Строки ниже — поля секции.

Что можно писать под заголовком секции (любой набор, в любом порядке).
weight — вес книги, целое число. Вес умножен на 10 по сравнению со старым
файлом: между соседними книгами остаются дырки, чтобы новую книгу можно было
вставить между ними, не перекладывая половину списка (15, 25, 110).
merges — id других изданий той же работы, через запятую. Их цитаты и отзыв
достаются этой заметке. author — автор, если LiveLib его не указал или указал
неверно. status — read / reading / stop, если полка LiveLib врёт.

Поля `my_mark` здесь нет: оценку сборка берёт с полки LiveLib, ей и верить.
Пустая секция (без полей) тоже законна: id уже говорит «эта книга в списке».
"""


def write(tmp_path, text, name):
    """A curation file written the way Curation.md must be written: a file whose
    first line is not a heading would put its bullets outside any section, and
    the loader rejects that, so tests that hand over a bare section get the doc
    block in front of them."""
    p = tmp_path / name
    p.write_text(DOC + "\n" + text if text.lstrip().startswith("## ") else text,
                 encoding="utf-8")
    return p


def run_cli(*args):
    """`python -m text_forge.migrate_curation ...` — returncode and output.

    check=False on purpose: these tests assert on the exit code itself, which is
    the thing the CLI's contract is about.
    """
    return subprocess.run([sys.executable, "-m", "text_forge.migrate_curation", *args],
                         capture_output=True, text=True, check=False)


def ids_of(md):
    """The section ids a migrated file carries, in file order."""
    return [line.split()[1] for line in md.splitlines() if line.startswith("## ")]


class TestMigrateText:
    """migrate_text(jsonc) -> markdown, pinned byte for byte."""

    def test_exact_output(self, tmp_path):
        assert migrate_curation.migrate_text(OLD) == NEW

    def test_byte_deterministic_on_rerun(self, tmp_path):
        """Same input, twice: identical bytes — the migration is auditable by
        diffing two runs, so nothing in it may depend on dict order, the clock,
        or the locale."""
        a = migrate_curation.migrate_text(OLD)
        b = migrate_curation.migrate_text(OLD)
        assert a == b
        # and again through the file path API
        src = write(tmp_path, OLD, "curation.jsonc")
        out1, out2 = tmp_path / "a.md", tmp_path / "b.md"
        migrate_curation.migrate_file(src, out1)
        migrate_curation.migrate_file(src, out2)
        assert out1.read_bytes() == out2.read_bytes()

    def test_output_reload_is_the_entries_the_jsonc_held(self, tmp_path):
        """Round trip: the migrated file feeds load_curation and yields the same
        curation the jsonc did (weights aside — those are ×10 by design)."""
        md = migrate_curation.migrate_text(OLD)
        got = load_curation(write(tmp_path, md, "Curation.md"))["books"]
        assert got == {
            "1003047920": {"weight": 10},
            "1001128870": {"weight": 30, "author": "Александр Юрьев"},
            "1000225484": {"weight": 50, "merges": [1005482422, 1007148466]},
            "1000699994": {"status": "read"},
            "1009172287": {},
        }

    def test_weights_are_multiplied_by_ten(self, tmp_path):
        """1..35 -> 10..350: the gaps are the point of the migration, so the
        factor is checked for a spread of values, not just one."""
        for old, new in ((1, 10), (5, 50), (12, 120), (35, 350)):
            md = migrate_curation.migrate_text(
                f'{{\n  // Книга\n  "books": {{"1": {{"weight": {old}}}}}\n}}\n')
            assert f"- weight: {new}\n" in md, (old, new)
            assert load_curation(write(tmp_path, md, "C.md"))["books"]["1"]["weight"] == new

    def test_heading_title_comes_from_the_comment(self):
        """The eye text is carried from the comment that names the id: the
        trailing comment of a one-line entry, which is the shape the corpus
        writes when it wants the title readable in the heading."""
        md = migrate_curation.migrate_text(
            '{\n  "books": {\n'
            '    "1003047920": {"weight": 1},  // Моменты счастья — Алекс Дубас\n'
            '    "1000225484": {"weight": 5}   // Сказать жизни «Да» — Виктор Франкл\n'
            '  }\n}\n')
        assert "## 1003047920 — Моменты счастья — Алекс Дубас" in md, md
        assert "## 1000225484 — Сказать жизни «Да» — Виктор Франкл" in md

    def test_url_comment_is_not_carried_into_the_heading(self):
        """The `@url:` comment line was metadata the build never read; the id in
        the heading already names the edition, so the url line is dropped."""
        md = migrate_curation.migrate_text(OLD)
        assert "@url" not in md
        assert "livelib.ru/book/1003047920" not in md

    def test_entry_without_a_comment_keeps_a_bare_id_heading(self):
        """No title available (or an empty entry) still yields a valid section —
        the migration may not invent a title."""
        md = migrate_curation.migrate_text('{"books": {"700": {}}}')
        assert "## 700\n" in md

    def test_merged_ids_survive_the_move(self, tmp_path):
        """A merge keeps its ids: the bullet is the one place the loader reads
        the list, so the member titles the old file kept as comments cannot ride
        along in the value — the ids alone come out, and they still fold the
        other editions' quotes and review into this note."""
        md = migrate_curation.migrate_text(OLD)
        section = md.split("\n## 1000225484")[1].split("\n## ")[0]
        assert "- merges: 1005482422, 1007148466" in section
        entry = load_curation(write(tmp_path, md, "C.md"))["books"]["1000225484"]
        assert entry["merges"] == [1005482422, 1007148466]

    def test_order_is_weight_then_weightless_by_id(self):
        """Weight ascending, then every entry without weight by id — so the file
        reads as a ranked list with an unranked tail, and the order is a
        function of the data, not of how the jsonc happened to be typed."""
        md = migrate_curation.migrate_text(OLD)
        ids = ids_of(md)
        assert ids == ["1003047920", "1001128870", "1000225484",
                      "1000699994", "1009172287"]

    def test_order_does_not_follow_the_jsonc_key_order(self):
        """The same three entries typed in another order produce the same file:
        the migration re-sorts, it does not translate position."""
        a = '{\n "books": {\n  // A\n  "1": {"weight": 20},\n  // B\n  "2": {"weight": 10}\n}\n}\n'
        b = '{\n "books": {\n  // B\n  "2": {"weight": 10},\n  // A\n  "1": {"weight": 20}\n}\n}\n'
        assert migrate_curation.migrate_text(a) == migrate_curation.migrate_text(b)
        ids = ids_of(migrate_curation.migrate_text(a))
        assert ids == ["2", "1"]

    def test_key_order_inside_an_entry_does_not_move_bullets(self):
        """Bullets always come out weight, author, status, merges: one shape for
        every section, however the jsonc typed it."""
        md = migrate_curation.migrate_text(
            '{\n "books": {\n  // X\n  "1": {"merges": [2], "status": "read",\n'
            ' "weight": 4, "author": "Кто-то"}\n}\n}\n')
        body = md.split("\n## 1 — X\n")[1].strip().splitlines()
        assert [b.split(":")[0] for b in body] == ["- weight", "- author",
                                                  "- status", "- merges"]

    def test_doc_block_is_first_and_holds_the_conventions(self):
        """The header is the file's only documentation: it must state the id/is
        the key rule and the ×10 weight rule, since those are the two things a
        new editor cannot infer from looking at the file."""
        md = migrate_curation.migrate_text(OLD)
        head, rest = md.split("\n\n## ", 1)
        assert head.lstrip().startswith("# ")
        assert "weight" in head and "10" in head
        assert "merges" in head and "my_mark" in head
        # the doc block carries no id headings, so it parses as no entries
        assert not any(line.startswith("## ") for line in head.splitlines())
        assert rest  # and sections follow

    def test_section_layout_is_heading_blank_bullets_blank(self):
        """The layout the loader and the eye both expect: heading, blank,
        bullets, blank before the next heading; one newline at EOF."""
        md = migrate_curation.migrate_text(OLD)
        lines = md.splitlines()
        assert md.endswith("\n") and not md.endswith("\n\n")
        for i, line in enumerate(lines):
            if line.startswith("## ") and i + 1 < len(lines):
                nxt = lines[i + 1]
                assert nxt == "" or nxt.startswith("- "), repr(nxt)

    def test_empty_books_section_is_just_the_doc_block(self):
        """Nothing curated: a valid file with zero sections, not an empty file."""
        md = migrate_curation.migrate_text('{\n  "books": {}\n}\n')
        assert md.splitlines()[0].startswith("# ")
        assert not any(l.startswith("## ") for l in md.splitlines())
        assert load_curation.__name__ == "load_curation"


class TestMigrateReadsOldSyntax:
    """The old JSONC syntax is parsed by the migrator itself — the loader's
    comment stripper is gone, so this is where it legitimately still lives."""

    def test_a_key_owns_the_comment_on_its_own_line(self):
        """A `//` trailing a complete entry names THAT entry, and takes the
        place of the whole-line block above it."""
        md = migrate_curation.migrate_text(
            '{\n  // title\n  "books": {"1": {"weight": 1}} // trailing\n}\n')
        assert "## 1 — trailing" in md

    def test_block_comments_are_not_data(self):
        """A `/* */` aside documents no entry: an entry behind one keeps the
        heading bare rather than taking the aside as its title."""
        md = migrate_curation.migrate_text(
            '{\n  /* ignored\n     block */\n  "books": {\n    "1": {\n'
            '      "weight": 1\n    }\n  }\n}\n')
        assert "## 1\n" in md
        assert "ignored" not in md

    def test_double_slash_inside_a_string_survives(self):
        """The regression the old stripper pinned, inherited by the migrator: a
        naive regex eats `https://` out of a title comment or an author."""
        md = migrate_curation.migrate_text(
            '{\n "books": {"1": {"author": "Имя https://www.livelib.ru/book/1"}}}\n')
        assert "https://www.livelib.ru/book/1" in md

    def test_escaped_quote_does_not_open_a_string(self, tmp_path):
        r"""`\"` inside a title must not toggle string state, or the `//` after
        it would be read as data and the parse would break."""
        md = migrate_curation.migrate_text(
            '{\n  // a " b\n  "books": {"1": {"weight": 1}}\n}\n')
        assert "## 1 — a \" b" in md

    def test_migrates_a_file_read_from_disk(self, tmp_path):
        src = write(tmp_path, OLD, "curation.jsonc")
        out = tmp_path / "Curation.md"
        migrate_curation.migrate_file(src, out)
        assert out.read_text(encoding="utf-8") == NEW

    def test_other_top_level_sections_are_not_migrated_as_books(self):
        """A `links` section is a different entity — it has no place in a file
        of edition sections, so it is not turned into fake editions. A comment
        holding a url is not an id either, which is the same rule."""
        md = migrate_curation.migrate_text(
            '{\n  // https://www.livelib.ru/book/9\n'
            '  "books": {"1": {"weight": 1}},\n'
            '  "links": {"https://www.livelib.ru/book/9": "slug"}\n}\n')
        ids = ids_of(md)
        assert ids == ["1"]


class TestMigrateErrors:
    """A file the migrator cannot read must stop the migration: a partial
    Curation.md would silently drop curation decisions from the corpus."""

    def test_broken_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            migrate_curation.migrate_text('{\n  "books": {"1": {"weight":\n}\n')

    def test_my_mark_field_is_dropped_not_migrated(self):
        """my_mark is dead in curation (it comes from shelf data), so it has no
        bullet in the new format: the migrator drops it rather than inventing a
        key the loader would reject."""
        md = migrate_curation.migrate_text(
            '{\n "books": {"1": {"weight": 2, "my_mark": 5}}}\n')
        assert "my_mark" not in md.split("\n\n## ")[1]
        assert "- weight: 20" in md

    def test_missing_input_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            migrate_curation.migrate_file(tmp_path / "nope.jsonc",
                                         tmp_path / "Curation.md")

    def test_non_dict_root_raises(self):
        with pytest.raises(ValueError):
            migrate_curation.migrate_text("[1, 2, 3]")


class TestCli:
    """`python -m text_forge.migrate_curation <in.jsonc> <out.md>`."""

    def test_two_positional_paths_write_the_file(self, tmp_path):
        src = write(tmp_path, OLD, "curation.jsonc")
        out = tmp_path / "Curation.md"
        res = run_cli(str(src), str(out))
        assert res.returncode == 0, res.stderr
        assert out.read_text(encoding="utf-8") == NEW

    def test_missing_argument_exits_nonzero_with_usage(self, tmp_path):
        src = write(tmp_path, OLD, "curation.jsonc")
        res = run_cli(str(src))
        assert res.returncode != 0
        assert "usage" in (res.stdout + res.stderr).lower()

    def test_bad_input_exits_nonzero_and_writes_nothing(self, tmp_path):
        src = write(tmp_path, "{ not json", "curation.jsonc")
        out = tmp_path / "Curation.md"
        res = run_cli(str(src), str(out))
        assert res.returncode != 0
        assert not out.exists()
        # the failure says what broke, in terms a human can act on
        assert "curation" in (res.stdout + res.stderr).lower()

    def test_cli_output_is_module_output(self, tmp_path):
        src = write(tmp_path, OLD, "curation.jsonc")
        out = tmp_path / "Curation.md"
        run_cli(str(src), str(out))
        assert out.read_text(encoding="utf-8") == migrate_curation.migrate_text(OLD)
