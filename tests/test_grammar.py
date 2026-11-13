"""Tests for `text_forge.grammar` — git-diff added lines, filters, typography.

Covers Task 1 (extract_added_lines), Task 2 (is_link_only_change,
quote_line_ranges, is_structural, filter_noise) and Task 3 (typography_issues).
The fixture `tests/fixtures/grammar/chapter-snippet.md` is a real slice of
whattodo `text/p2-110-system.md` plus the shapes each filter keys on.
"""

import pathlib
import subprocess

import pytest

from text_forge import grammar
from text_forge.grammar import (
    AddedLine,
    filter_noise,
    is_link_only_change,
    is_structural,
    quote_line_ranges,
    typography_issues,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "grammar"
SNIPPET = (FIXTURES / "chapter-snippet.md").read_text(encoding="utf-8")
SNIPPET_LINES = SNIPPET.split("\n")[:-1]


def git(repo, *args, env_extra=None):
    """Run git in `repo` with a deterministic identity; return stdout."""
    import os

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    env.update(env_extra or {})
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A two-commit repo: base commit, then a commit that edits text/a.md.

    The edit mixes the shapes extraction must get right: an insertion in the
    middle, an append at the end, and replacement pairs elsewhere.
    """
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "a.md").write_text(
        "One original line\nTwo original line\nThree original line\n", encoding="utf-8"
    )
    (tmp_path / "text" / "untouched.md").write_text("Steady state\n", encoding="utf-8")
    (tmp_path / "text" / "books").mkdir(parents=True)
    (tmp_path / "text" / "books" / "note.md").write_text(
        "Out of scope\n", encoding="utf-8"
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "text" / "a.md").write_text(
        "One original line\nInserted after one\nTwo original line\nInserted after two\n"
        "Three original line\nFour appended tail\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "edit")
    base = git(tmp_path, "rev-parse", "HEAD~1")
    head = git(tmp_path, "rev-parse", "HEAD")
    return tmp_path, base, head


class TestExtractAddedLines:
    def test_text_strips_plus_and_line_is_exact(self, repo):
        root, base, head = repo
        got = _extract(root, base, head)
        line = got["text/a.md"][0]
        assert (line.line, line.text) == (2, "Inserted after one")
        assert "+" not in line.text
        assert line.file == "text/a.md"
        assert line.commit == head

    def test_line_numbers_count_from_new_side(self, repo):
        root, base, head = repo
        got = _extract(root, base, head)
        assert [row.line for row in got["text/a.md"]] == [2, 4, 6]

    def test_untouched_file_absent(self, repo):
        root, base, head = repo
        got = _extract(root, base, head)
        assert "text/untouched.md" not in got
        # both the pathspec and the standing text/books exclusion keep noise out
        assert "text/books/note.md" not in got

    def test_empty_diff_gives_empty_dict(self, repo):
        root, _, head = repo
        got = _extract(root, head, head)
        assert got == {}

    def test_appended_line_keeps_its_new_number(self, repo):
        root, base, head = repo
        got = _extract(root, base, head)
        tail = got["text/a.md"][-1]
        assert (tail.line, tail.text) == (6, "Four appended tail")
        assert [r.line for r in got["text/a.md"]] == [2, 4, 6]


def _extract(root, base, head):
    """Diff base..head over an explicit pathspec list (the API takes globs)."""
    return grammar.extract_added_lines(root, base, ("text/*.md", "text/index.md"))


class TestLinkOnlyChange:
    def test_url_swapped_only(self):
        removed = [
            "More on [Что делать?](https://www.livelib.ru/book/1001616054-chto-delat)."
        ]
        added = ["More on [Что делать?](books/chernyshevskiy-chto-delat.md)."]
        assert is_link_only_change(removed, added) is True

    def test_ref_style_target_swapped(self):
        removed = ["See [Тодд][todd] for the argument."]
        added = ["See [Тодд][todd-2] for the argument."]
        assert is_link_only_change(removed, added) is True

    def test_quote_text_changed_too(self):
        removed = ["[Александр Аузан](https://www.livelib.ru/quote/42572258)"]
        added = ["[Александр Аузан](books/auzan.md#quote_3){ .author }"]
        assert is_link_only_change(removed, added) is False

    def test_order_matters(self):
        # one hunk, the two lines swapped: same lines, different order
        removed = ["Alpha [one](u1)", "Beta [two](u2)"]
        added = ["Beta [two](u3)", "Alpha [one](u4)"]
        assert is_link_only_change(removed, added) is False

    def test_empty_sides_are_not_a_link_only_change(self):
        assert is_link_only_change([], []) is False

    def test_new_link_counts_as_authored_text(self):
        assert is_link_only_change([], ["New [link](books/x.md) here"]) is False


class TestQuoteLineRanges:
    def test_ranges_from_the_fixture_file(self, tmp_path):
        path = tmp_path / "text"
        path.mkdir()
        (path / "chapter.md").write_text(SNIPPET, encoding="utf-8")
        assert quote_line_ranges(tmp_path, "text/chapter.md") == [(14, 21)]

    def test_note_block_is_not_a_quote_range(self, tmp_path):
        path = tmp_path / "text"
        path.mkdir()
        (path / "chapter.md").write_text(SNIPPET, encoding="utf-8")
        for start, end in quote_line_ranges(tmp_path, "text/chapter.md"):
            assert not any(
                SNIPPET_LINES[i - 1].strip().startswith("/// note")
                for i in range(start, end + 1)
                if i <= len(SNIPPET_LINES)
            )

    def test_attribute_form_marker(self, tmp_path):
        path = tmp_path / "text"
        path.mkdir()
        (path / "c.md").write_text(
            "Intro\n/// quote | подпись\nЦитата\n///\nAfter\n", encoding="utf-8"
        )
        assert quote_line_ranges(tmp_path, "text/c.md") == [(2, 4)]

    def test_unclosed_marker_ignores_dangling_marker(self, tmp_path):
        path = tmp_path / "text"
        path.mkdir()
        (path / "c.md").write_text("///\nNothing open here\n", encoding="utf-8")
        assert quote_line_ranges(tmp_path, "text/c.md") == []

    def test_note_marker_never_opens_a_quote_range(self, tmp_path):
        path = tmp_path / "text"
        path.mkdir()
        # a dangling `///` must not close the next block: `/// note` stays open and
        # its own `///` closes it, so no quote range is reported
        (path / "c.md").write_text(
            "///\nDangling\n/// note\nЗаметка\n///\n", encoding="utf-8"
        )
        assert quote_line_ranges(tmp_path, "text/c.md") == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            quote_line_ranges(tmp_path, "text/nope.md")


class TestIsStructural:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "///",
            "   ///   ",
            "---",
            "![Поляризация мнений](assets/polarization.png)",
            "[1]: https://example.org 'title'",
            "[ref]: books/x.md",
            "-----",
            "> ",
            "— ",
        ],
    )
    def test_structural(self, text):
        assert is_structural(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "/// quote",
            "/// note",
            "   /// quote | подпись",
            "Значит стоит проанализировать опыт прошлых поколений",
            "![alt](x.png) и ещё мысль автора",
            "/// caption | подпись без имени вида",
            "— Так говорит автор",
        ],
    )
    def test_prose(self, text):
        assert is_structural(text) is False


class TestFilterNoise:
    def test_counts_and_kept_shape(self):
        added = [
            AddedLine(file="text/a.md", line=2, text="/// quote", commit="c"),
            AddedLine(file="text/a.md", line=3, text="Чужая цитата тут", commit="c"),
            AddedLine(file="text/a.md", line=4, text="   ///", commit="c"),
            AddedLine(
                file="text/a.md",
                line=5,
                text="Авторская мысль на пять слов",
                commit="c",
            ),
            AddedLine(
                file="text/a.md", line=6, text="[Автор](books/x.md#quote_1)", commit="c"
            ),
            AddedLine(file="text/a.md", line=7, text="![x](a.png)", commit="c"),
            AddedLine(file="text/a.md", line=8, text=":-)", commit="c"),
            AddedLine(file="text/a.md", line=9, text="", commit="c"),
        ]
        # the removed counterpart of line 6 sits at position 4 of the hunk
        removed = [
            "",
            "/// quote",
            "Чужая цитата тут",
            "   ///",
            "[Автор](https://www.livelib.ru/quote/1-slug)",
        ]
        quote_ranges = [(2, 4)]  # an empty added line is structural, not quote
        kept, dropped = filter_noise(
            added, removed_by_hunk=removed, quote_ranges=quote_ranges
        )
        assert [(r.file, r.line) for r in kept] == [("text/a.md", 5)]
        assert dropped["quote"] == 3
        assert dropped["link_only"] == 1
        assert dropped["structural"] == 3  # image, `:-)`, empty line

    def test_author_line_survives_when_nothing_was_removed(self):
        added = [
            AddedLine(
                file="text/a.md", line=9, text="[Имя](books/x.md#quote_1)", commit="c"
            )
        ]
        kept, dropped = filter_noise(added)
        assert len(kept) == 1
        assert dropped == {}

    def test_multi_line_hunk_pairs_by_hunk_not_by_line_number(self):
        # A reworded paragraph: old lines sit at 30-31, the new ones at 30-32.
        # Pairing by line number would compare "30 vs 30" and "31 vs 31" and call
        # the leftover new line authored text; pairing within the hunk is what
        # makes a pure link retarget read as link_only.
        old = [
            "Текст про [Книгу](https://www.livelib.ru/book/1001616054-kniga),",
            "которая важна.",
        ]
        new = [
            "Текст про [Книгу](books/kniga.md),",
            "которая важна.",
            "Третья строка.",
        ]
        added = [
            AddedLine(file="text/a.md", line=n, text=t, commit="c")
            for n, t in zip([30, 31, 32], new)
        ]
        kept, dropped = filter_noise(added, removed_by_hunk=old)
        assert dropped["link_only"] == 2
        assert [r.line for r in kept] == [32]

    def test_unchanged_prose_pair_is_not_link_only(self):
        old = ["Старая формулировка мысли."]
        new = ["Новая формулировка мысли."]
        added = [AddedLine(file="text/a.md", line=5, text=new[0], commit="c")]
        kept, dropped = filter_noise(added, removed_by_hunk=old)
        assert [r.line for r in kept] == [5]
        assert dropped == {}

    def test_all_quoted_lines_dropped(self):
        # the fixture's quote block spans lines 14-21: marker, blank, quote text,
        # blank, attribution line, blank, closing marker — none of it is authored
        added = [
            AddedLine(file="text/a.md", line=i, text=text, commit="c")
            for i, text in enumerate(SNIPPET_LINES, 1)
        ]
        kept, dropped = filter_noise(added, quote_ranges=[(14, 21)])
        assert dropped["quote"] == 8
        assert not any(14 <= r.line <= 21 for r in kept)

    def test_reasons_are_only_the_three_kinds(self):
        added = [
            AddedLine(file="text/a.md", line=i, text=text, commit="c")
            for i, text in enumerate(SNIPPET_LINES, 1)
        ]
        kept, dropped = filter_noise(added, quote_ranges={(14, 21)})
        assert set(dropped) <= {"link_only", "quote", "structural"}
        assert sum(dropped.values()) + len(kept) == len(SNIPPET_LINES)


class TestTypography:
    def _issue_map(self, texts):
        added = [
            AddedLine(file="text/a.md", line=i, text=t, commit="c")
            for i, t in enumerate(texts, 1)
        ]
        issues = typography_issues(added)
        return {(i.kind, i.line): i for i in issues}

    def test_kinds_reported(self):
        got = self._issue_map(
            [
                "Значит стоит разобрать  опыт прошлых поколений.",
                "Перенос строки маркдауном   ",
                "Пробел перед точкой .",
                "Eдиная точка опоры всех поколений",
            ]
        )
        assert ("double_space", 1) in got
        assert ("trailing_double_space", 2) in got
        assert ("space_before_punct", 3) in got
        assert ("homoglyph", 4) in got

    def test_clean_lines_produce_nothing(self):
        got = self._issue_map(
            [
                "Обычная строка авторского текста.",
                "Ссылка [книга](books/x.md#quote_3) внутри фразы.",
                "Якорь #polarization и домен example.org не в счёт.",
                "Аббревиатура ОК",
            ]
        )
        assert got == {}

    def test_double_space_inside_is_reported_once_per_line(self):
        got = self._issue_map(["Три  пробела  внутри  одной  строки"])
        kinds = [k for (k, _l) in got]
        assert kinds.count("double_space") == 1

    def test_trailing_double_space_is_not_an_error_kind(self):
        got = self._issue_map(["Фраза продолжается   "])
        assert [k for (k, _l) in got] == ["trailing_double_space"]

    def test_single_space_before_punct_is_fine(self):
        got = self._issue_map(["Слова, продолжение"])
        assert got == {}

    def test_fragment_carries_the_offender(self):
        got = self._issue_map(["Тут cвязаны кириллица и латиница"])
        issue = got[("homoglyph", 1)]
        assert issue.fragment == "cвязаны"
        assert issue.file == "text/a.md"

    def test_short_mixed_token_is_ignored(self):
        got = self._issue_map(["Пишем ok и да"])
        assert got == {}

    def test_homoglyph_inside_link_text_is_reported(self):
        # `[Cмерти](p1-010-happiness.md#funeral_as_result)` was lost by the old
        # `](` skip-marker while raw_targets in the same line are still noise.
        got = self._issue_map(
            ["важнее скорости приближения [Cмерти](p1-010-happiness.md#x)!"]
        )
        issue = got[("homoglyph", 1)]
        assert issue.fragment == "Cмерти"

    def test_link_target_alone_is_not_a_prose_token(self):
        got = self._issue_map(["Ссылка [книга](books/x.md#quote_3) внутри фразы."])
        assert got == {}
