"""Tests for `text_forge.prompts` — the prompt library that shipped with the tool.

The prompt files live inside the package (`text_forge/prompts/*.md`) and carry the
wrappers an editor expects: an optional ```prompt fence and an optional YAML
frontmatter.  The model must receive the instruction body only, so unwrapping is
library behaviour, not Makefile sed.
"""

import pathlib

import pytest

from text_forge import prompts as PROMPTS
from text_forge.prompts import (
    UnknownPrompt,
    load_prompt,
    prompt_names,
    strip_wrappers,
)

PROMPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "text_forge" / "prompts"


class TestPromptNames:
    def test_the_library_holds_exactly_the_migrated_prompts(self):
        assert prompt_names() == ["grammar", "summarize"]

    def test_names_have_no_md_suffix(self):
        assert all(not name.endswith(".md") for name in prompt_names())

    def test_names_match_the_files_on_disk(self):
        on_disk = sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))
        assert prompt_names() == on_disk


class TestLoadPrompt:
    def test_unknown_name_raises_unknown_prompt(self):
        with pytest.raises(UnknownPrompt):
            load_prompt("no-such-prompt")

    def test_unknown_name_lists_what_is_available(self):
        with pytest.raises(UnknownPrompt) as excinfo:
            load_prompt("no-such-prompt")
        message = str(excinfo.value)
        assert "grammar" in message
        assert "summarize" in message

    @pytest.fixture
    def dirpath(self, tmp_path):
        """A prompt library of one, isolated from the shipped files."""
        tmp_path.mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_opening_fence_is_removed(self, dirpath, monkeypatch):
        _write(dirpath, "fenced.md", "```prompt\n# Title\n\nBody.\n```\n")
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        assert load_prompt("fenced") == "\n# Title\n\nBody.\n"

    def test_frontmatter_is_removed(self, dirpath, monkeypatch):
        _write(dirpath, "fm.md", "---\nagent: agent\n---\n\n# Title\n\nBody.\n")
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        assert load_prompt("fm") == "\n# Title\n\nBody.\n"

    def test_parity_with_the_awk_recipe_it_replaces(self):
        # grammar.md ran through the Makefile's sed|awk recipe before the migration,
        # and that output is baked into the 516-line grammar job the content repo is
        # calibrated on.  Byte parity is what makes the migration invisible to the
        # model and to the `file:line` addresses it quotes, so the behaviour is
        # pinned here rather than "tidied up".  The recipe keeps one blank line at
        # the top (it skips the frontmatter lines, not the padding) and drops the
        # terminating newline when the last record is empty — the two rules
        # `strip_wrappers` reproduces.
        text = (PROMPTS_DIR / "grammar.md").read_text(encoding="utf-8")
        assert load_prompt("grammar") == _sed_awk_body(text)

    def test_fence_then_frontmatter_is_removed(self, dirpath, monkeypatch):
        _write(
            dirpath,
            "both.md",
            "```prompt\n---\nagent: agent\n---\n\n# Title\n\nBody.\n```\n",
        )
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        assert load_prompt("both") == "\n# Title\n\nBody.\n"

    def test_empty_frontmatter_block_is_not_treated_as_a_wrapper(self):
        # `---` immediately followed by `---` is not a block to consume: eating it
        # would let a stray rule in the body swallow everything up to the next one
        assert (
            strip_wrappers("---\n---\n\n# Title\n\nBody.\n")
            == "\n---\n---\n\n# Title\n\nBody.\n"
        )

    def test_plain_file_is_returned_as_is(self, dirpath, monkeypatch):
        _write(dirpath, "bare.md", "# Title\n\nBody.\n")
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        assert load_prompt("bare") == "\n# Title\n\nBody.\n"

    def test_inner_fences_survive(self, dirpath, monkeypatch):
        _write(
            dirpath,
            "inner.md",
            "```prompt\n---\nagent: agent\n---\n\n# Title\n\n"
            "Example:\n\n```diff\n+new\n-old\n```\n\nTail.\n```\n",
        )
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        body = load_prompt("inner")
        assert "```diff\n+new\n-old\n```\n" in body
        assert body.startswith("\n# Title\n")
        assert body.endswith("Tail.\n")

    def test_loaded_prompts_keep_no_wrapper(self):
        for name in prompt_names():
            body = load_prompt(name)
            assert not body.lstrip("\n").startswith("```prompt")
            assert not body.lstrip("\n").startswith("---")
            assert "agent: agent" not in body.splitlines()

    def test_body_is_returned_verbatim_after_the_leading_blank_line(self):
        # the seam the model reads: blank line, then the prompt's own first line
        # untouched — grammar.md opens with a heading, summarize.md with prose
        assert load_prompt("grammar").startswith("\n# ")
        assert load_prompt("summarize").startswith("\nRead whole ")

    def test_body_is_padded_with_exactly_one_blank_line(self):
        for name in prompt_names():
            body = load_prompt(name)
            assert body.startswith("\n") and body.endswith("\n"), name
            assert not body.startswith("\n\n"), name
            assert not body.endswith("\n\n"), name

    def test_missing_file_on_disk_raises_unknown_prompt(self, dirpath, monkeypatch):
        monkeypatch.setattr(PROMPTS, "PROMPTS_DIR", dirpath)
        with pytest.raises(UnknownPrompt):
            load_prompt("grammar")


def _sed_awk_body(text):
    """The pre-migration recipe, reproduced in python: `sed` fence, then `awk` fm.

    Kept as an executable oracle: it produced the 516-line grammar job the content
    repo is calibrated on.  Faithful to awk in its one quirk — no terminating
    newline is printed after an empty last record.
    """
    lines = text.split("\n")
    if lines and lines[0] == "```prompt":
        lines.pop(0)
    if len(lines) >= 2 and lines[-1] == "" and lines[-2] == "```":
        lines.pop()

    out = []
    in_fm = False
    for index, line in enumerate(lines):
        if index == 0 and line == "---":
            in_fm = True
            continue
        if in_fm:
            if line == "---":
                in_fm = False
            continue
        out.append(line)

    body = "\n".join(out)
    if out and out[-1] == "" and out[-2:] == ["", ""] and len(out) > 1:
        # awk prints no terminator after an empty last record; the old job files
        # only ever lost it when the body carried two blank lines at the end
        body = body[:-1]
    return body


def _write(dirpath, name, text):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_text(text, encoding="utf-8")
