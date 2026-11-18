"""Tests for `text_forge.section_diff` and its CLI.

The point of the module is the *editorial* question — what did a section stop
saying and start saying — so the tests pin the two failure modes that made a
digest lie: reading a rewrite as pure addition, and reading a rename as a new
section.
"""

import pathlib
import subprocess
import sys
import tempfile

from text_forge.section_diff import (
    CHANGED,
    NEW,
    RENAMED,
    SectionDelta,
    diff_sections,
    render,
    split_sections,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "section-diff.py"

DOC = """\
---
title: chapter
---

## Первый раздел {#first}

Первая мысль.

## Второй раздел {#second}

Вторая мысль с [ссылкой](books/a.md).
"""


class TestSplit:
    def test_frontmatter_is_its_own_section(self):
        sections = split_sections(DOC)
        assert sections[0].title == ""
        assert sections[1].title == "Первый раздел"
        assert sections[1].anchor == "first"

    def test_bodies_stop_at_the_next_heading(self):
        sections = split_sections(DOC)
        # the blank line before the next heading belongs to the body it follows
        assert sections[1].body == ["", "Первая мысль.", ""]
        assert sections[2].body == ["", "Вторая мысль с [ссылкой](books/a.md)."]

    def test_identity_is_the_anchor(self):
        assert split_sections(DOC)[1].key == "first"

    def test_heading_without_anchor_falls_back_to_title(self):
        section = split_sections("## Без якоря\n\nтекст\n")[1]
        assert section.key == "Без якоря"


class TestDiff:
    def test_unchanged_section_is_silent(self):
        assert diff_sections(DOC, DOC) == []

    def test_added_paragraph_is_one_plus_line(self):
        new = DOC.replace("Первая мысль.", "Первая мысль.\n\nНовая мысль.")
        (delta,) = diff_sections(DOC, new)
        assert delta.kind == CHANGED
        assert delta.anchor == "first"
        assert delta.added == 1 and delta.removed == 0
        assert delta.lines == ["+Новая мысль."]

    def test_rewrite_keeps_both_sides(self):
        # the defect a hunk list hides: a rewritten paragraph is a -/+ pair, not
        # an addition
        new = DOC.replace("Первая мысль.", "Переписанная мысль.")
        (delta,) = diff_sections(DOC, new)
        assert delta.added == 1 and delta.removed == 1
        assert "-Первая мысль." in delta.lines
        assert "+Переписанная мысль." in delta.lines

    def test_renamed_heading_is_not_a_new_section(self):
        # the anchor survives a rename; comparing titles would report the whole
        # body as added
        new = DOC.replace(
            "## Первый раздел {#first}", "## Раздел после переименования {#first}"
        )
        (delta,) = diff_sections(DOC, new)
        assert delta.kind == RENAMED
        assert delta.previous_title == "Первый раздел"
        # the body is untouched, so the only news is the new title itself
        assert delta.lines == []

    def test_truly_new_anchor_is_new(self):
        new = DOC + "\n## Третий раздел {#third}\n\nТретья мысль.\n"
        (delta,) = diff_sections(DOC, new)
        assert delta.kind == NEW
        assert delta.lines == ["+Третья мысль."]

    def test_link_only_change_still_counts_as_changed(self):
        # honest reporting: a link retarget changes the body, the digest decides
        # separately whether that is worth a post
        new = DOC.replace("books/a.md", "books/b.md")
        (delta,) = diff_sections(DOC, new)
        assert delta.added == 1 and delta.removed == 1

    def test_context_is_dropped_by_default(self):
        new = DOC.replace("Первая мысль.", "Переписанная мысль.")
        (delta,) = diff_sections(DOC, new)
        assert all(line[1:].strip() for line in delta.lines)

    def test_context_can_be_kept(self):
        old = "## Раздел {#r}\n\nПервый абзац.\n\nВторой абзац.\n"
        new = old.replace("Второй абзац.", "Второй абзац.\n\nТретий абзац.")
        (bare,) = diff_sections(old, new)
        assert bare.lines == ["+Третий абзац."]
        (wide,) = diff_sections(old, new, context=1)
        assert " Второй абзац." in wide.lines  # the unchanged neighbour

    def test_sections_stay_in_document_order(self):
        new = DOC.replace("Первая мысль.", "А.").replace("Вторая мысль", "Б.")
        deltas = diff_sections(DOC, new)
        assert [d.anchor for d in deltas] == ["first", "second"]


class TestRender:
    def test_block_header_names_the_delta(self):
        delta = SectionDelta(title="Раздел", anchor="a", kind=CHANGED, lines=["+новое"])
        assert render([delta]) == "\n### Раздел #a   [+1/-0]\n  +новое\n"

    def test_rename_shows_the_old_title(self):
        delta = SectionDelta(
            title="Новое имя",
            anchor="a",
            kind=RENAMED,
            previous_title="Старое имя",
            lines=["-старое", "+новое"],
        )
        assert "переименован: «Старое имя»" in render([delta])

    def test_new_section_is_labelled(self):
        delta = SectionDelta(title="Т", anchor="a", kind=NEW, lines=["+x"])
        assert "[новый раздел]" in render([delta])

    def test_nothing_to_show_renders_empty(self):
        assert render([]) == ""


def git(repo, *args):
    env = {
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    ).stdout


def run_cli(root, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        cwd=tempfile.mkdtemp(),
        check=False,
    )


class TestCli:
    def test_prints_the_delta_between_two_commits(self, tmp_path):
        git(tmp_path, "init", "-q")
        doc = tmp_path / "chapter.md"
        doc.write_text(DOC, encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-qm", "base")
        doc.write_text(
            DOC.replace("Первая мысль.", "Переписанная мысль."), encoding="utf-8"
        )
        git(tmp_path, "commit", "-qam", "rewrite")

        proc = run_cli(
            tmp_path, "--base", "HEAD^", "--head", "HEAD", "--file", "chapter.md"
        )
        assert proc.returncode == 0, proc.stderr
        assert "Первый раздел #first" in proc.stdout
        assert "-Первая мысль." in proc.stdout
        assert "+Переписанная мысль." in proc.stdout

    def test_unknown_file_exits_2(self, tmp_path):
        git(tmp_path, "init", "-q")
        (tmp_path / "a.md").write_text("# x\n", encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-qm", "base")
        proc = run_cli(tmp_path, "--base", "HEAD", "--file", "nope.md")
        assert proc.returncode == 2
        assert "not in" in proc.stderr

    def test_unchanged_file_says_so_on_stderr(self, tmp_path):
        git(tmp_path, "init", "-q")
        (tmp_path / "a.md").write_text(DOC, encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-qm", "base")
        proc = run_cli(tmp_path, "--base", "HEAD", "--head", "HEAD", "--file", "a.md")
        assert proc.returncode == 0
        assert proc.stdout == ""
        assert "no section changed" in proc.stderr
