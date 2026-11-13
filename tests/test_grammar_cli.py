"""Tests for Task 4: `render_markdown`, `build_payload` and the CLI script.

The CLI is loaded by path (like `tests/test_hindsight_ingest.py` loads its
wrapper) so a plain import of `scripts/grammar-diff.py` has no side effects.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import pytest

from text_forge.grammar import (
    AddedLine,
    Issue,
    build_payload,
    render_markdown,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "grammar-diff.py"

CLI_HELP = """usage: grammar-diff.py [-h] [--root ROOT] [--since REF] [--only FILE]
                       [--scope {wtd,all}] [--json JSON_PATH] [--md MD_PATH]
                       [--typo]

Build the proofreading input for a text project: added lines of --since..HEAD,
filtered, with file:line addresses.

options:
  -h, --help         show this help message and exit
  --root ROOT        repository root (default: cwd)
  --since REF        diff base, inclusive of that commit's own changes;
                     omitted means the working tree vs HEAD
  --only FILE        proofread this one file whole (no diff); excludes --since
  --scope {wtd,all}  wtd (default): text/p*.md + text/index.md; all:
                     text/**/*.md
  --json JSON_PATH   where to write JSON (default: <root>/build/grammar-
                     input.json)
  --md MD_PATH       where to write markdown (default: <root>/build/grammar-
                     input.md)
  --typo             add the typography section to the artifacts
"""


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


@pytest.fixture
def repo(tmp_path):
    """A content-shaped repo: chapters, a note-book, a link retarget, new prose."""
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "text" / "books").mkdir(parents=True)
    (tmp_path / "text" / "index.md").write_text(
        "---\ntitle: Hub\n---\n\n# Что делать\n\n"
        "[Александр Аузан](https://www.livelib.ru/quote/42572258-slug){ .author }\n\n"
        "/// quote\n\nЧужие слова, не для вычитки.\n\n///\n\n"
        "Старая строка.\n",
        encoding="utf-8",
    )
    (tmp_path / "text" / "books" / "note.md").write_text(
        "---\ntitle: Note\n---\n\nЦитата из книги другого человека.\n", encoding="utf-8"
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "text" / "index.md").write_text(
        "---\ntitle: Hub\n---\n\n# Что делать\n\n"
        "[Александр Аузан](books/auzan.md#quote_3){ .author }\n\n"
        "/// quote\n\nЧужие слова, не для вычитки.\n\n///\n\n"
        "Новая мысль автора.\nИ ещё  одна, с двойным пробелом.\n",
        encoding="utf-8",
    )
    (tmp_path / "text" / "books" / "note.md").write_text(
        "---\ntitle: Note\n---\n\nЦитата из книги другого человека.\nПлюс строка.\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "edit")
    return tmp_path, base, git(tmp_path, "rev-parse", "HEAD")


class TestRenderMarkdown:
    def setup_method(self):
        self.added = {
            "text/p1-a.md": [
                AddedLine(
                    "text/p1-a.md", 31, "Значит стоит проанализировать опыт", "c1"
                ),
                AddedLine("text/p1-a.md", 32, "  и собрать  находки.  ", "c1"),
            ],
            "text/index.md": [AddedLine("text/index.md", 5, "Вступление", "c1")],
        }
        self.issues = [
            Issue("text/p1-a.md", 32, "double_space", "собрать  находки."),
            Issue("text/index.md", 5, "homoglyph", "Вcтупление"),
        ]
        self.meta = {
            "base": "abc123",
            "head": "def456",
            "scope": "wtd",
            "dropped": {"link_only": 12, "quote": 30, "structural": 40},
        }
        self.out = render_markdown(self.added, self.issues, self.meta)

    def test_header_carries_base_and_totals(self):
        assert "abc123" in self.out
        assert "lines to check: 3" in self.out
        assert "files: 2" in self.out

    def test_header_lists_every_drop_reason_with_counts(self):
        assert "quote=30" in self.out
        assert "link_only=12" in self.out
        assert "structural=40" in self.out

    def test_line_rows_are_addressed(self):
        assert "text/p1-a.md:31 | Значит стоит проанализировать опыт" in self.out

    def test_text_is_trimmed_in_the_row(self):
        assert "text/p1-a.md:32 | и собрать  находки." in self.out

    def test_typography_section_lists_findings(self):
        tail = self.out.split("## Typography", 1)[1]
        assert "text/p1-a.md:32" in tail
        assert "double_space" in tail
        assert "homoglyph" in tail

    def test_empty_typography_says_so(self):
        out = render_markdown(self.added, [], self.meta)
        assert "No findings." in out

    def test_zero_drops_are_still_printed(self):
        out = render_markdown(
            self.added, [], {"base": "b", "scope": "all", "dropped": {}}
        )
        assert "structural=0" in out

    def test_pipe_in_fragment_is_escaped(self):
        out = render_markdown(
            {},
            [Issue("f.md", 1, "double_space", "a | b")],
            {"base": "b", "scope": "wtd", "dropped": {}},
        )
        assert "a \\| b" in out


class TestBuildPayload:
    def test_schema_keys(self, repo):
        root, base, head = repo
        payload = build_payload(root, base, "wtd")
        assert set(payload) == {
            "base",
            "head",
            "scope",
            "files",
            "dropped",
            "typography",
        }
        assert payload["base"] == base
        assert payload["head"] == head
        assert payload["scope"] == "wtd"

    def test_note_book_is_out_of_scope(self, repo):
        root, base, _ = repo
        payload = build_payload(root, base, "wtd")
        assert "text/books/note.md" not in payload["files"]
        assert "text/index.md" in payload["files"]

    def test_note_book_edit_reaches_all_scope_but_not_wtd(self, tmp_path):
        # a note-book edit is visible to `all` and invisible to `wtd`; a chapter
        # edit is visible to both.  This needs a real commit-to-commit range: the
        # `repo` fixture puts chapter and note edits in the SAME commit, so no
        # range can separate them.
        root = tmp_path
        git(root, "init", "-q", "-b", "main")
        (root / "text" / "books").mkdir(parents=True)
        (root / "text" / "p1-ch.md").write_text("Строка главы.\n", encoding="utf-8")
        (root / "text" / "books" / "note.md").write_text("Цитата.\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        base = git(root, "rev-parse", "HEAD")
        (root / "text" / "p1-ch.md").write_text(
            "Строка главы.\nНовая глава.\n", encoding="utf-8"
        )
        (root / "text" / "books" / "note.md").write_text(
            "Цитата.\nНовая note.\n", encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "edits")
        wtd = build_payload(root, base, "wtd")
        alls = build_payload(root, base, "all")
        assert "text/p1-ch.md" in wtd["files"]
        assert "text/books/note.md" not in wtd["files"]
        assert "text/books/note.md" in alls["files"]

    def test_dropped_reasons_are_present_and_counted(self, repo):
        root, base, _ = repo
        dropped = build_payload(root, base, "wtd")["dropped"]
        assert set(dropped) == {"link_only", "quote", "structural"}
        assert dropped["link_only"] == 1
        assert dropped["quote"] == 0
        assert dropped["structural"] == 0

    def test_kept_lines_are_the_authored_ones(self, repo):
        root, base, _ = repo
        rows = build_payload(root, base, "wtd")["files"]["text/index.md"]
        assert [r["text"] for r in rows] == [
            "Новая мысль автора.",
            "И ещё  одна, с двойным пробелом.",
        ]
        assert [r["line"] for r in rows] == [15, 16]

    def test_typography_empty_without_flag(self, repo):
        root, base, _ = repo
        assert build_payload(root, base, "wtd")["typography"] == []

    def test_typography_keeps_line_numbers(self, repo):
        root, base, _ = repo
        typo = build_payload(root, base, "wtd", with_typography=True)["typography"]
        assert [t["kind"] for t in typo] == ["double_space"]
        assert typo[0]["file"] == "text/index.md"
        assert typo[0]["line"] == 16


class TestCli:
    def test_help(self):
        proc = run_cli(REPO_ROOT, "--help")
        assert proc.returncode == 0
        assert (
            proc.stdout.replace("\n", " ").split()
            == CLI_HELP.replace("\n", " ").split()
        )

    def test_writes_both_artifacts(self, repo):
        root, base, _ = repo
        proc = run_cli(root, "--since", base, "--typo")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(
            (root / "build" / "grammar-input.json").read_text(encoding="utf-8")
        )
        assert payload["scope"] == "wtd"
        assert payload["files"]["text/index.md"]
        markdown = (root / "build" / "grammar-input.md").read_text(encoding="utf-8")
        assert "text/index.md:16 | И ещё  одна, с двойным пробелом." in markdown
        assert "double_space" in markdown

    def test_custom_paths(self, repo):
        root, base, _ = repo
        proc = run_cli(
            root, "--since", base, "--json", "out/g.json", "--md", "out/g.md"
        )
        assert proc.returncode == 0, proc.stderr
        assert (root / "out" / "g.json").is_file()
        assert (root / "out" / "g.md").is_file()

    def test_bad_since_exits_1(self, repo):
        root, _, _ = repo
        proc = run_cli(root, "--since", "no-such-ref-1234")
        assert proc.returncode == 1
        assert "no-such-ref-1234" in proc.stderr

    def test_no_added_lines_exits_2_with_message(self, repo):
        root, _base, head = repo
        proc = run_cli(root, "--since", head)
        assert proc.returncode == 2
        assert "no added lines to check" in proc.stderr

    def test_working_tree_diff_is_the_default_base(self, repo):
        root, _committed, _tip = repo
        # an uncommitted edit: `--since HEAD` must diff the working tree, not the
        # always-empty HEAD..HEAD range
        (root / "text" / "index.md").write_text(
            (root / "text" / "index.md").read_text(encoding="utf-8")
            + "\nПравка в рабочем дереве.\n",
            encoding="utf-8",
        )
        proc = run_cli(root, "--json", "wt.json", "--md", "wt.md")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads((root / "wt.json").read_text(encoding="utf-8"))
        assert payload["base"] == "HEAD"
        texts = [r["text"] for r in payload["files"]["text/index.md"]]
        assert "Правка в рабочем дереве." in texts

    def test_scope_flag_selects_more_files(self, repo):
        # `repo` puts its edits in one commit, so scope is the only variable here:
        # `all` (text/**/*.md) reaches the note-book, `wtd` (p1/p2 chapters +
        # text/index.md) cannot, and both must see the chapter edit.
        root, base, _ = repo
        wtd = run_cli(
            root, "--since", base, "--scope", "wtd", "--json", "w.json", "--md", "w.md"
        )
        alls = run_cli(
            root, "--since", base, "--scope", "all", "--json", "a.json", "--md", "a.md"
        )
        assert wtd.returncode == 0, proc_out(wtd)
        assert alls.returncode == 0, proc_out(alls)
        w = json.loads((root / "w.json").read_text(encoding="utf-8"))
        a = json.loads((root / "a.json").read_text(encoding="utf-8"))
        assert "text/index.md" in w["files"]
        assert "text/books/note.md" not in w["files"]
        assert "text/books/note.md" in a["files"]

    def test_prints_counts_of_kept_and_dropped(self, repo):
        root, base, _ = repo
        proc = run_cli(root, "--since", base, "--typo")
        out = proc.stderr  # human output goes to stderr, stdout stays empty
        assert re.search(r"kept\s+2 lines", out)
        assert "link_only 1" in out
        assert "structural 0" in out
        assert "quote 0" in out  # a zero still prints: silence must be visible
        assert re.search(r"typography\s+\S+ 1", out)
        assert proc.stdout == ""  # artifacts and pipes must not see cosmetics

    def test_not_a_git_repo_exits_1(self, tmp_path):
        plain = tmp_path / "nope"
        plain.mkdir()
        proc = run_cli(plain, "--since", "HEAD")
        assert proc.returncode == 1


class TestContractFacts:
    """The numbers established for the real whattodo diff, as executable guards.

    These check the *filter mechanics* against a repo shaped like whattodo's
    `77f44f2..HEAD` diff (attribution retarget, `/// quote` blocks that predate the
    diff, frontmatter, an image line) — they do not pin the real corpus's totals,
    which drift with every commit there.
    """

    def test_raw_line_count_of_the_scope_matches_the_diff(self, repo):
        root, base, _ = repo
        # git itself, same pathspec: 3 added lines in index.md; the note-book edit
        # is outside `wtd`, so it must not appear in the total either
        raw = git(
            root, "diff", "--numstat", "-U0", base, "HEAD", "--", ":(glob)text/index.md"
        )
        assert raw.split("\t")[0] == "3"
        payload = build_payload(root, base, "wtd")
        kept = sum(len(rows) for rows in payload["files"].values())
        assert kept + sum(payload["dropped"].values()) == 3

    def test_quote_lines_are_dropped_as_quote_not_as_structural(self, tmp_path):
        # a quote block that already existed, plus a link retarget inside it:
        # git sees 1 added line, and that line is quote noise, not prose
        root = tmp_path
        git(root, "init", "-q", "-b", "main")
        (root / "text").mkdir()
        (root / "text" / "p1-a.md").write_text(
            "Пролог.\n\n/// quote\n\nЧужая цитата.\n\n"
            "[Автор](https://www.livelib.ru/quote/42572258-slug){ .author }\n\n///\n",
            encoding="utf-8",
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        base = git(root, "rev-parse", "HEAD")
        (root / "text" / "p1-a.md").write_text(
            "Пролог.\n\n/// quote\n\nЧужая цитата.\n\n"
            "[Автор](books/author.md#quote_3){ .author }\n\n///\n",
            encoding="utf-8",
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "retarget")
        payload = build_payload(root, base, "wtd")
        # the attribution swap is inside a quote block: quote wins the reason
        assert payload["dropped"]["quote"] == 1
        assert payload["dropped"]["link_only"] == 0
        assert payload["files"] == {}

    def test_nothing_in_scope_leaves_no_artifacts(self, tmp_path):
        # scope misses the edited file entirely -> exit 2, and the "nothing to
        # check" claim must not be confused with a filter bug: git itself is empty
        root = tmp_path
        git(root, "init", "-q", "-b", "main")
        (root / "text").mkdir()
        (root / "text" / "z.md").write_text("Старое.\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        base = git(root, "rev-parse", "HEAD")
        (root / "text" / "z.md").write_text("Старое.\nНовое.\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "edit")
        assert (
            git(root, "diff", "--numstat", base, "HEAD", "--", ":(glob)text/p*.md")
            == ""
        )
        proc = run_cli(root, "--since", base, "--scope", "wtd")
        assert proc.returncode == 2
        assert "no added lines to check" in proc.stderr
        assert not (root / "build" / "grammar-input.json").exists()

    def test_generated_p3_page_is_outside_wtd(self, tmp_path):
        # text/p3-references.md is rendered from books+reviews by wtd_books_p3, so
        # it is not authored prose: `wtd` names the p1/p2 chapter families
        # explicitly and must not feed the proofreader a generated page.
        root = tmp_path
        git(root, "init", "-q", "-b", "main")
        (root / "text").mkdir()
        (root / "text" / "p3-references.md").write_text("Старое.\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        base = git(root, "rev-parse", "HEAD")
        (root / "text" / "p3-references.md").write_text(
            "Старое.\nНовое.\n", encoding="utf-8"
        )
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "edit")
        assert build_payload(root, base, "wtd")["files"] == {}
        assert "text/p3-references.md" in build_payload(root, base, "all")["files"]


class TestFileMode:
    """`--only FILE`: the whole file, not a diff — for chapters nobody touched."""

    def test_whole_file_keeps_old_lines_and_drops_quotes(self, repo):
        root, _base, _head = repo
        proc = run_cli(root, "--only", "text/index.md", "--typo")
        assert proc.returncode == 0, proc_out(proc)
        payload = json.loads(
            (root / "build" / "grammar-input.json").read_text(encoding="utf-8")
        )
        assert list(payload["files"]) == ["text/index.md"]
        texts = [row["text"] for row in payload["files"]["text/index.md"]]
        # lines that were already committed count too: this is not a diff
        assert "# Что делать" in texts
        assert "Новая мысль автора." in texts
        # somebody else's words never reach the proofreader
        assert not any("Чужие слова" in text for text in texts)
        assert payload["dropped"]["quote"] >= 3
        assert payload["dropped"]["link_only"] == 0
        assert payload["scope"] == "file"
        assert "whole file" in payload["base"]

    def test_only_and_since_are_mutually_exclusive(self, repo):
        root, base, _head = repo
        proc = run_cli(root, "--only", "text/index.md", "--since", base)
        assert proc.returncode == 2
        assert "mutually exclusive" in proc.stderr

    def test_missing_file_exits_1(self, repo):
        root, _base, _head = repo
        proc = run_cli(root, "--only", "text/nope.md")
        assert proc.returncode == 1
        assert "no such file" in proc.stderr

    def test_rerun_is_stable(self, repo):
        """Same file twice → same input: no diff state leaks into file mode."""
        root, _base, _head = repo
        run_cli(root, "--only", "text/index.md")
        first = (root / "build" / "grammar-input.md").read_text(encoding="utf-8")
        run_cli(root, "--only", "text/index.md")
        second = (root / "build" / "grammar-input.md").read_text(encoding="utf-8")
        assert first == second


def proc_out(proc) -> str:
    """stdout+stderr of a CLI run, for assertion messages."""
    return f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
