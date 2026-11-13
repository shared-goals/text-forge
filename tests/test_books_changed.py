"""Tests for `changed_books`, `render_books_markdown` and the CLI script.

The CLI is loaded by path (like `tests/test_grammar_cli.py` loads its wrapper),
so a plain import of `scripts/books-changed.py` has no side effects.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

from text_forge.books_changed import (
    BookChange,
    changed_books,
    render_books_markdown,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "books-changed.py"


def git(repo, *args):
    env = {
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )
    return proc.stdout.strip()


def run_cli(root, *args):
    """Run the CLI as a subprocess; cwd is outside git so --root is what counts."""
    workdir = pathlib.Path(tempfile.mkdtemp())
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return proc


def tempfile_dir():
    import tempfile

    return tempfile.mkdtemp()


def note(title, author, status):
    """A book note in the shape `make books` writes."""
    lines = ["---"]
    if title is not None:
        lines.append(f'title: "{title}"')
    if author is not None:
        lines.append(f"author: {author}")
    if status is not None:
        lines.append(f"status: {status}")
    lines.extend(["---", "", "Текст заметки.", ""])
    return "\n".join(lines) + "\n"


def write_book(repo, slug, title, author, status):
    path = repo / "text" / "books" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note(title, author, status), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    """A content-shaped repo with three book notes at the base commit."""
    git(tmp_path, "init", "-q", "-b", "main")
    write_book(
        tmp_path,
        "frankl-skazat-zhizni-da",
        "Сказать жизни «Да»",
        "Виктор Франкл",
        "read",
    )
    write_book(
        tmp_path,
        "basinskiy-lev-tolstoy",
        "Лев Толстой: Бегство из рая",
        "Павел Басинский",
        "read",
    )
    write_book(tmp_path, "goscinaya-voda", "Гостиная вода", "Наринэ Абгарян", "read")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD")


def by_slug(changes):
    return {c.slug: c for c in changes}


class TestChangedBooks:
    def test_added_book_from_disk(self, repo):
        root, base = repo
        write_book(root, "abgaryan-manyunya", "Манюня", "Наринэ Абгарян", "read")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "add one book")
        changes = changed_books(root, base)
        assert len(changes) == 1
        change = changes[0]
        assert change.change == "added"
        assert change.path == "text/books/abgaryan-manyunya.md"
        assert change.slug == "abgaryan-manyunya"
        assert change.title == "Манюня"
        assert change.author == "Наринэ Абгарян"
        assert change.status == "read"
        assert change.shelf == "Прочтённые"

    def test_modified_uses_new_status(self, repo):
        root, base = repo
        path = root / "text" / "books" / "frankl-skazat-zhizni-da.md"
        path.write_text(
            note("Сказать жизни «Да»", "Виктор Франкл", "wish"), encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "moved to wish shelf")
        change = by_slug(changed_books(root, base))["frankl-skazat-zhizni-da"]
        assert change.change == "modified"
        assert change.status == "wish"
        assert change.shelf == "Хочу прочитать"

    def test_removed_reads_frontmatter_from_base(self, repo):
        root, base = repo
        (root / "text" / "books" / "basinskiy-lev-tolstoy.md").unlink()
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "dropped a note")
        change = by_slug(changed_books(root, base))["basinskiy-lev-tolstoy"]
        assert change.change == "removed"
        assert change.title == "Лев Толстой: Бегство из рая"
        assert change.author == "Павел Басинский"
        assert change.shelf == "Прочтённые"

    def test_note_without_frontmatter_is_kept(self, repo):
        root, base = repo
        path = root / "text" / "books" / "bez-frontmatter.md"
        path.write_text("Просто текст, ни title, ни author.\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "a bare note")
        change = by_slug(changed_books(root, base))["bez-frontmatter"]
        assert change.change == "added"
        assert change.title == ""
        assert change.author == ""
        assert change.status == ""
        assert change.shelf == ""

    def test_broken_yaml_is_kept(self, repo):
        root, base = repo
        path = root / "text" / "books" / "slomannyj.md"
        path.write_text(
            "---\ntitle: [unclosed\n  bad: {indent\n---\n\nТекст.\n", encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "broken frontmatter")
        change = by_slug(changed_books(root, base))["slomannyj"]
        assert change.change == "added"
        assert change.title == ""
        assert change.shelf == ""

    def test_order_added_then_modified_then_removed(self, repo):
        root, base = repo
        write_book(root, "zzz-read", "Я", "Автор А", "read")
        write_book(root, "aaa-wish", "А", "Автор Б", "wish")
        (root / "text" / "books" / "frankl-skazat-zhizni-da.md").unlink()
        path = root / "text" / "books" / "basinskiy-lev-tolstoy.md"
        path.write_text(
            note("Лев Толстой", "Павел Басинский", "reading"), encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "mixed")
        order = [(c.change, c.shelf, c.title) for c in changed_books(root, base)]
        assert order == [
            ("added", "Хочу прочитать", "А"),
            ("added", "Прочтённые", "Я"),
            ("modified", "Читаю", "Лев Толстой"),
            ("removed", "Прочтённые", "Сказать жизни «Да»"),
        ]

    def test_within_shelf_sorted_by_title_then_slug(self, repo):
        root, base = repo
        write_book(root, "bbb", "Одинаковый заголовок", "Автор Б", "read")
        write_book(root, "aaa", "Одинаковый заголовок", "Автор А", "read")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "same title")
        slugs = [c.slug for c in changed_books(root, base)]
        assert slugs == ["aaa", "bbb"]

    def test_books_outside_books_dir_ignored(self, repo):
        root, base = repo
        (root / "text" / "p1.md").write_text(
            "---\ntitle: Chapter\n---\n\nТекст.\n", encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "chapter only")
        assert changed_books(root, base) == []

    def test_subdirectory_books_are_covered(self, repo):
        """`:(glob)text/books/*.md` would match NOTHING here — `**/*.md` does.

        Without the `:(glob)` prefix git matches `*` against the whole path, so
        the flat notes the fixture already has would disappear too.  Both depths
        must come back.
        """
        root, base = repo
        path = root / "text" / "books" / "deep" / "inner.md"
        path.parent.mkdir(parents=True)
        path.write_text(note("Внутри", "Автор В", "read"), encoding="utf-8")
        (root / "text" / "books" / "frankl-skazat-zhizni-da.md").write_text(
            note("Сказать жизни «Да»", "Виктор Франкл", "reading"), encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "nested + flat")
        # `added` comes before `modified`, whatever the shelf — so the nested
        # note leads even though its shelf ranks later.
        assert [(c.slug, c.change) for c in changed_books(root, base)] == [
            ("inner", "added"),
            ("frankl-skazat-zhizni-da", "modified"),
        ]
        assert [(c.shelf, c.path) for c in changed_books(root, base)] == [
            ("Прочтённые", "text/books/deep/inner.md"),
            ("Читаю", "text/books/frankl-skazat-zhizni-da.md"),
        ]

    def test_clean_range_returns_empty(self, repo):
        root, base = repo
        git(root, "commit", "-q", "--allow-empty", "-m", "nothing here")
        assert changed_books(root, base) == []

    def test_rename_is_added_plus_removed_of_the_same_book(self, repo):
        """A slug rename reports one book twice: under the new slug and the old.

        Both records must carry the note's real title/author — the survivor reads
        them from disk, the vanished slug from the base. A pure rename is scored
        R100 by git, so neither record is `modified`.
        """
        root, base = repo
        old = root / "text" / "books" / "goscinaya-voda.md"
        old.rename(root / "text" / "books" / "abgaryan-gostinaya-voda.md")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "renamed the slug")
        changes = changed_books(root, base)
        assert sorted(c.slug for c in changes) == [
            "abgaryan-gostinaya-voda",
            "goscinaya-voda",
        ]
        assert sorted(c.change for c in changes) == ["added", "removed"]
        for c in changes:
            assert c.title == "Гостиная вода"
            assert c.author == "Наринэ Абгарян"
            assert c.shelf == "Прочтённые"

    def test_rename_with_new_content_is_added_and_removed(self, repo):
        """A rename that also rewrites the note misses rename detection."""
        root, base = repo
        old = root / "text" / "books" / "goscinaya-voda.md"
        old.rename(root / "text" / "books" / "abgaryan-gostinaya-voda.md")
        (root / "text" / "books" / "abgaryan-gostinaya-voda.md").write_text(
            note("Гостиная вода", "Наринэ Абгарян", "wish")
            + "\nНовый абзац, длинный и новый.\n",
            encoding="utf-8",
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "renamed + moved shelf")
        by_change = {c.change: c for c in changed_books(root, base)}
        assert set(by_change) == {"added", "removed"}
        assert by_change["added"].slug == "abgaryan-gostinaya-voda"
        assert by_change["added"].shelf == "Хочу прочитать"
        assert by_change["removed"].slug == "goscinaya-voda"
        assert by_change["removed"].shelf == "Прочтённые"


class TestRender:
    def test_grouped_by_shelf(self):
        changes = [
            BookChange(
                "text/books/frankl-skazat-zhizni-da.md",
                "frankl-skazat-zhizni-da",
                "added",
                "Сказать жизни «Да»: психолог в концлагере",
                "Виктор Франкл",
                "read",
                "Прочтённые",
            ),
            BookChange(
                "text/books/basinskiy-lev-tolstoy-begstvo-iz-raya.md",
                "basinskiy-lev-tolstoy-begstvo-iz-raya",
                "removed",
                "Лев Толстой: бегство из рая",
                "Павел Басинский",
                "read",
                "Прочтённые",
            ),
        ]
        expected = (
            "### Прочтённые — 2 книги\n"
            "\n"
            "- Виктор Франкл — "
            "[Сказать жизни «Да»: психолог в концлагере]"
            "(text/books/frankl-skazat-zhizni-da.md)\n"
            "- Павел Басинский — "
            "~~[Лев Толстой: бегство из рая]"
            "(text/books/basinskiy-lev-tolstoy-begstvo-iz-raya.md)~~\n"
        )
        out = render_books_markdown(changes)
        assert out.split("\n")[1] == ""
        assert out[len("С HEAD: 2 книги: 1 добавлено · 1 удалено") + 2 :] == expected
        assert out.startswith("С HEAD: 2 книги: 1 добавлено · 1 удалено\n")

    def test_removed_book_is_struck_through_with_a_mark(self):
        """The ~~pair~~ is the whole marker — no trailing prose to trip over."""
        changes = [
            BookChange(
                "text/books/a.md", "a", "removed", "A", "AA", "read", "Прочтённые"
            ),
        ]
        assert render_books_markdown(changes, "0000000") == (
            "С 0000000: 1 книга: удалено\n"
            "\n"
            "### Прочтённые — 1 книга\n"
            "\n"
            "- AA — ~~[A](text/books/a.md)~~\n"
        )

    def test_missing_title_falls_back_to_slug(self):
        changes = [
            BookChange(
                "text/books/bez-zagolovka.md",
                "bez-zagolovka",
                "added",
                "",
                "Виктор Франкл",
                "",
                "",
            ),
        ]
        assert render_books_markdown(changes, "0000000") == (
            "С 0000000: 1 книга: добавлено\n"
            "\n"
            "### Без полки — 1 книга\n"
            "\n"
            "- Виктор Франкл — [bez-zagolovka](text/books/bez-zagolovka.md)\n"
        )

    def test_numeral_agrees_with_count(self):
        def books(change, n):
            return [
                BookChange(
                    f"text/books/{c}.md", c, change, "T", "A", "read", "Прочтённые"
                )
                for c in ("a", "b", "c", "d", "e")[:n]
            ]

        assert render_books_markdown(books("added", 1), "0000000").startswith(
            "С 0000000: 1 книга: добавлено\n"
        )
        assert render_books_markdown(books("added", 2), "0000000").startswith(
            "С 0000000: 2 книги: добавлено\n"
        )
        assert render_books_markdown(books("added", 5), "0000000").startswith(
            "С 0000000: 5 книг: добавлено\n"
        )

    def test_counts_by_kind_when_kinds_mix(self):
        changes = [
            BookChange(
                "text/books/a.md", "a", "added", "A", "AA", "read", "Прочтённые"
            ),
            BookChange(
                "text/books/b.md", "b", "added", "B", "BB", "read", "Прочтённые"
            ),
            BookChange(
                "text/books/c.md", "c", "modified", "C", "CC", "wish", "Хочу прочитать"
            ),
            BookChange(
                "text/books/d.md", "d", "removed", "D", "DD", "wish", "Хочу прочитать"
            ),
            BookChange(
                "text/books/e.md", "e", "removed", "E", "EE", "read", "Прочтённые"
            ),
        ]
        assert render_books_markdown(changes, "0000000abcdef").startswith(
            "С 0000000: 5 книг: 2 добавлено · 1 изменено · 2 удалено\n"
        )

    def test_summary_line_is_one_line(self):
        changes = [
            BookChange("text/books/a.md", "a", "added", "A", "", "read", "Прочтённые"),
            BookChange(
                "text/books/b.md", "b", "modified", "B", "BB", "wish", "Хочу прочитать"
            ),
        ]
        assert render_books_markdown(changes, "0000000").split("\n")[0] == (
            "С 0000000: 2 книги: 1 добавлено · 1 изменено · без автора — a"
        )

    def test_kind_counts_repeat_only_when_counts_differ(self):
        """`12 книг: 12 добавлено` is a stutter — one kind means the total is it."""
        changes = [
            BookChange(
                f"text/books/s{n}.md", f"s{n}", "added", "T", "", "read", "Прочтённые"
            )
            for n in range(12)
        ]
        summary = render_books_markdown(changes, "0000000").split("\n")[0]
        assert summary.startswith("С 0000000: 12 книг: добавлено · без автора — ")
        assert summary.endswith("… (+6)")
        assert "s11" not in summary

    def test_shelf_groups_follow_shelf_name_order(self):
        changes = [
            BookChange("text/books/c.md", "c", "added", "C", "А", "read", "Прочтённые"),
            BookChange(
                "text/books/a.md", "a", "added", "A", "Б", "wish", "Хочу прочитать"
            ),
            BookChange(
                "text/books/b.md", "b", "modified", "B", "В", "read", "Прочтённые"
            ),
            BookChange("text/books/d.md", "d", "added", "D", "Г", "", ""),
        ]
        out = render_books_markdown(changes)
        assert [line for line in out.split("\n") if line.startswith("### ")] == [
            "### Хочу прочитать — 1 книга",
            "### Прочтённые — 2 книги",
            "### Без полки — 1 книга",
        ]

    def test_empty_list_renders_empty_and_warns(self, capsys):
        assert render_books_markdown([]) == ""
        assert "No book changes" in capsys.readouterr().err


class TestCli:
    def test_writes_markdown(self, repo):
        root, base = repo
        write_book(root, "abgaryan-manyunya", "Манюня", "Наринэ Абгарян", "read")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "add")
        proc = run_cli(root, "--since", base)
        assert proc.returncode == 0, proc.stderr
        md = root / "build" / "books-changed.md"
        assert md.is_file()
        assert "### Прочтённые" in md.read_text(encoding="utf-8")

    def test_explicit_path(self, repo, tmp_path):
        root, base = repo
        write_book(root, "abgaryan-manyunya", "Манюня", "Наринэ Абгарян", "wish")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "add")
        out_md = tmp_path / "sub" / "books.md"
        proc = run_cli(root, "--since", base, "--md", str(out_md))
        assert proc.returncode == 0, proc.stderr
        assert "Хочу прочитать" in out_md.read_text(encoding="utf-8")

    def test_bad_ref_exits_1(self, repo):
        root, _ = repo
        proc = run_cli(root, "--since", "0000000000000000000000000000000000000000")
        assert proc.returncode == 1
        assert "since" in proc.stderr.lower() or "ref" in proc.stderr.lower()
        assert not (root / "build" / "books-changed.md").exists()

    def test_not_a_git_repo_exits_2(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        proc = run_cli(plain, "--since", "HEAD")
        assert proc.returncode == 2
        assert "git" in proc.stderr.lower()

    def test_no_changes_writes_an_empty_report(self, repo):
        """An unchanged corpus is still a report: the artifact exists on success.

        A caller piping this into a changelog step needs one contract — the file
        exists whatever the count. It stays empty, and stderr carries the fact.
        """
        root, base = repo
        git(root, "commit", "-q", "--allow-empty", "-m", "nothing")
        proc = run_cli(root, "--since", base)
        assert proc.returncode == 0
        assert "No book changes" in proc.stderr
        assert (root / "build" / "books-changed.md").read_text(encoding="utf-8") == ""

    def test_prose_only_range_writes_empty_markdown(self, repo):
        root, base = repo
        (root / "text" / "index.md").parent.mkdir(parents=True, exist_ok=True)
        (root / "text" / "index.md").write_text(
            "---\ntitle: Hub\n---\n\nПроза.\n", encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "prose only")
        proc = run_cli(root, "--since", base)
        assert proc.returncode == 0
        assert "No book changes" in proc.stderr
        assert (root / "build" / "books-changed.md").read_text(encoding="utf-8") == ""

    def test_since_is_required(self, repo):
        root, _ = repo
        proc = run_cli(root)
        assert proc.returncode == 2
        assert "--since" in proc.stderr

    def test_missing_root_exits_2(self, tmp_path):
        proc = run_cli(tmp_path / "nope", "--since", "HEAD")
        assert proc.returncode == 2
        assert "root" in proc.stderr.lower()
