"""Tests for `scripts/job.py` — the job-file builder (prompt + input in one file).

The script is loaded by path (like `tests/test_hindsight_ingest.py`), so a plain
import has no side effects.  The exact rendered strings are the contract: the
prompt body words where its own input markers are, so a drifted separator makes the
model read a job file it does not recognise.
"""

import importlib.util
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "job.py"

spec = importlib.util.spec_from_file_location("job", SCRIPT_PATH)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def run_cli(*args, cwd=None, prompt="grammar"):
    """Run the CLI as a subprocess; `--prompt` goes first to mirror the recipe."""
    argv = ["--prompt", prompt] if prompt else []
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *argv, *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return proc


def write(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestRender:
    def test_job_is_newline_delimited_top_and_bottom(self, tmp_path):
        # blank line, instructions, blank line, input — and a newline closing the
        # last block, so a runner that pipes the file does not glue its own prompt
        # onto a half-line
        inp = write(tmp_path / "in.md", "AAAA\n")
        out = job.build_job("grammar", inputs=[inp], sections=[], footer=None)
        assert out.startswith("\n# ")
        assert out.endswith("AAAA\n")
        assert not out.endswith("\n\n\n")

    def test_prompt_body_then_input(self, tmp_path):
        inp = write(tmp_path / "in.md", "# Input\n\nLine one.\n")
        body = job.load_body("summarize")
        out = job.build_job("summarize", inputs=[inp], sections=[], footer=None)
        assert out.startswith(body)
        assert out.endswith("\n# Input\n\nLine one.\n")

    def test_input_is_glued_without_a_separator(self, tmp_path):
        body = job.load_body("grammar")
        inp = write(tmp_path / "in.md", "AAAA\nBBBB\n")
        out = job.build_job("grammar", inputs=[inp], sections=[], footer=None)
        assert out == body + "AAAA\nBBBB\n"

    def test_md_section_gets_a_rule_and_heading(self, tmp_path):
        sec = write(tmp_path / "books.md", "С 77f44f2: 415 книг\n\n### Читаю\n\n- x\n")
        out = job.build_job(
            "grammar", inputs=[], sections=[("Books", sec)], footer=None
        )
        assert "\n---\n\n## Books\n\n" in out
        assert out.endswith("\nС 77f44f2: 415 книг\n\n### Читаю\n\n- x\n")

    def test_diff_section_is_fenced(self, tmp_path):
        sec = write(tmp_path / "changes.diff", "diff --git a/x.md b/x.md\n+new\n")
        out = job.build_job(
            "summarize", inputs=[], sections=[("Diff", sec)], footer=None
        )
        assert (
            "\n---\n\n## Diff\n\n```diff\ndiff --git a/x.md b/x.md\n+new\n```\n" in out
        )

    def test_patch_section_is_fenced_too(self, tmp_path):
        sec = write(tmp_path / "changes.patch", "+new\n")
        out = job.build_job(
            "summarize", inputs=[], sections=[("Patch", sec)], footer=None
        )
        assert "\n## Patch\n\n```diff\n+new\n```\n" in out

    def test_section_content_gains_a_missing_trailing_newline(self, tmp_path):
        sec = write(tmp_path / "tail.md", "no newline at eof")
        out = job.build_job("grammar", inputs=[], sections=[("T", sec)], footer=None)
        assert out.endswith("\nno newline at eof\n")

    def test_empty_section_is_rendered_as_silence(self, tmp_path):
        # a tool that found nothing writes an empty file, so an empty section is a
        # normal input; a fence around nothing or a fabricated "No book changes."
        # line both change what the model reads
        sec = write(tmp_path / "empty.md", "")
        out = job.build_job(
            "summarize", inputs=[], sections=[("Books", sec)], footer=None
        )
        assert out.endswith("\n## Books\n\n")
        assert "No book changes." not in out

    def test_footer_is_delimited_by_a_rule(self):
        out = job.build_job(
            "grammar", inputs=[], sections=[], footer="Write the report."
        )
        assert out.endswith("\n---\n\nWrite the report.\n")
        assert out == job.load_body("grammar") + "\n---\n\nWrite the report.\n"

    def test_order_is_prompt_input_sections_footer(self, tmp_path):
        body = job.load_body("grammar")
        inp = write(tmp_path / "in.md", "INPUT\n")
        sec = write(tmp_path / "s.md", "SECTION\n")
        out = job.build_job(
            "grammar", inputs=[inp], sections=[("Sec", sec)], footer="FOOTER"
        )
        assert (
            out
            == body + "INPUT\n" + "\n---\n\n## Sec\n\nSECTION\n" + "\n---\n\nFOOTER\n"
        )

    def test_section_heading_is_the_second_heading_when_the_prompt_has_one(
        self, tmp_path
    ):
        # real jobs are built from prompts that already contain `## ` headings, so
        # the section block is located by its own first heading
        a = write(tmp_path / "a.md", "AAA\n")
        b = write(tmp_path / "b.md", "BBB\n")
        out = job.build_job(
            "summarize", inputs=[], sections=[("One", a), ("Two", b)], footer=None
        )
        block = out[out.index("\n---\n\n## One\n\n") :]
        assert block == "\n---\n\n## One\n\nAAA\n\n## Two\n\nBBB\n"

    def test_first_section_is_delimited_by_a_rule(self, tmp_path):
        # the only difference between the first section and a later one is the
        # `---` rule: with inputs ahead of the sections, the block still opens
        # with a rule and its second section still does not
        inp = write(tmp_path / "in.md", "INPUT\n")
        a = write(tmp_path / "a.md", "AAA\n")
        b = write(tmp_path / "b.md", "BBB\n")
        out = job.build_job(
            "grammar",
            inputs=[inp],
            sections=[("One", a), ("Two", b)],
            footer=None,
        )
        assert out == (
            job.load_body("grammar")
            + "INPUT\n"
            + "\n---\n\n## One\n\nAAA\n"
            + "\n## Two\n\nBBB\n"
        )

    def test_several_sections_are_rendered_in_order(self, tmp_path):
        # the section block opens with a rule; further sections are separated by a
        # blank line only — the pre-migration shape, where an extra rule would
        # shift every line number the model cites
        a = write(tmp_path / "a.md", "AAA\n")
        b = write(tmp_path / "b.diff", "+BBB\n")
        out = job.build_job(
            "summarize",
            inputs=[],
            sections=[("First", a), ("Second", b)],
            footer=None,
        )
        assert "\n---\n\n## First\n\nAAA\n\n## Second\n\n```diff\n+BBB\n```\n" in out
        assert out.index("## First") < out.index("## Second")
        assert out.count("\n---\n") == 1

    def test_title_with_punctuation_and_slashes_survives_verbatim(self, tmp_path):
        # real titles name the scope and the range: `Diff (text/*.md, ref..HEAD)`
        sec = write(tmp_path / "d.diff", "+x\n")
        title = "Diff (text/*.md, 77f44f2..HEAD)"
        out = job.build_job(
            "summarize", inputs=[], sections=[(title, sec)], footer=None
        )
        assert f"\n---\n\n## {title}\n\n```diff\n+x\n```\n" in out


class TestCli:
    def test_prompt_and_input_to_stdout(self, tmp_path):
        inp = write(tmp_path / "in.md", "AAAA\n")
        proc = run_cli("--input", str(inp))
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("\n# ")
        assert proc.stdout.endswith("AAAA\n")

    def test_out_writes_a_file_and_creates_its_parent(self, tmp_path):
        inp = write(tmp_path / "in.md", "AAAA\n")
        out = tmp_path / "build" / "job.md"
        proc = run_cli("--input", str(inp), "--out", str(out))
        assert proc.returncode == 0, proc.stderr
        assert out.is_file()
        assert out.read_text(encoding="utf-8").endswith("AAAA\n")

    def test_repeated_inputs_and_sections(self, tmp_path):
        a = write(tmp_path / "a.md", "AAA\n")
        d = write(tmp_path / "d.diff", "+x\n")
        proc = run_cli(
            "--prompt",
            "summarize",
            "--input",
            str(a),
            "--section",
            f"Diff={d}",
            "--out",
            str(tmp_path / "job.md"),
        )
        assert proc.returncode == 0, proc.stderr
        text = (tmp_path / "job.md").read_text(encoding="utf-8")
        assert "AAA\n" in text
        assert "\n## Diff\n\n```diff\n+x\n```\n" in text

    def test_footer_flag(self, tmp_path):
        proc = run_cli("--footer", "Write the report.")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.endswith("\n---\n\nWrite the report.\n")

    def test_unknown_prompt_exits_2_with_message(self, tmp_path):
        proc = run_cli(prompt="no-such-prompt")
        assert proc.returncode == 2
        assert "no-such-prompt" in proc.stderr
        assert "grammar" in proc.stderr

    def test_unreadable_input_exits_2(self, tmp_path):
        proc = run_cli("--input", str(tmp_path / "absent.md"))
        assert proc.returncode == 2
        assert "absent.md" in proc.stderr

    def test_unreadable_section_exits_2(self, tmp_path):
        proc = run_cli("--section", "T=absent.md")
        assert proc.returncode == 2
        assert "absent.md" in proc.stderr

    def test_section_without_equals_is_rejected(self, tmp_path):
        proc = run_cli("--section", "no-equals-here")
        assert proc.returncode == 2
        assert "--section" in proc.stderr

    def test_prompt_is_required(self):
        proc = run_cli("--input", "whatever.md", prompt=None)
        assert proc.returncode != 0
        assert "--prompt" in proc.stderr

    def test_grammar_job_shape_matches_the_makefile_recipe(self, tmp_path):
        # the recipe whattodo's Makefile now delegates: one input, one footer
        inp = write(
            tmp_path / "build" / "grammar-input.md", "# Grammar input\n\nrows\n"
        )
        out = tmp_path / "build" / "grammar-job.md"
        footer = (
            "Проверь добавленные строки выше и запиши отчёт в build/grammar-report.md"
        )
        proc = run_cli(
            "--input",
            str(inp),
            "--footer",
            footer,
            "--out",
            str(out),
        )
        assert proc.returncode == 0, proc.stderr
        text = out.read_text(encoding="utf-8")
        body = job.load_body("grammar")
        assert text == body + "# Grammar input\n\nrows\n" + f"\n---\n\n{footer}\n"
