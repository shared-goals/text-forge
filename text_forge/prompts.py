"""text_forge.prompts — the prompt library of the pipeline.

Prompts used to live in a content repo (`.github/prompts/*.prompt.md`) while the
tool that feeds them lives here: one contract, two repositories, and the input
format and the prompt's expectations drifted apart twice.  They now ship as
package data, so a content repo cannot fall behind on a prompt change.

A prompt file carries the wrappers an editor expects — an optional ```prompt
fence and an optional YAML frontmatter — in whichever order the editor wrote them
(both shipped prompts open with frontmatter, a file may also open with the
fence).  Both forms resolve to the instruction body, and
the body's own fences and `---` rules are kept: they are examples the model reads,
not wrappers.

Output shape, always: a blank line, the body stripped of blank padding, then a
newline.  The leading blank line is the seam separating instructions from the
input glued behind them, and it is the shape the sed/awk recipes this module
replaces left in the job files — `tests/test_prompts.py` pins that parity against
the shipped prompts, so line numbers quoted from an old report stay addressable.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

#: Opening wrapper written by editors that store a prompt as fenced markdown.
FENCE_OPEN = "```prompt"
#: Closing wrapper of that fence.
FENCE_CLOSE = "```"
#: Delimiter line of YAML frontmatter.
FRONTMATTER_DELIM = "---"

__all__ = ["FENCE_CLOSE", "FENCE_OPEN", "UnknownPrompt", "load_prompt", "prompt_names"]


class UnknownPrompt(KeyError):
    """Raised for a prompt name with no file in the library.

    The message lists the available names, because callers pass names typed by a
    human on a command line.
    """

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(
            f"Unknown prompt: {name!r}. Available: {', '.join(available) or '(none)'}"
        )


def prompt_names(dirpath: Path | None = None) -> list[str]:
    """Prompt names (no `.md` suffix), sorted.

    The library is located relative to this module, so it resolves the same way
    whether the package is used from a checkout, an editable install, or a wheel —
    the way `text_forge.obsidian`'s data is located too.
    """
    directory = PROMPTS_DIR if dirpath is None else dirpath
    return sorted(path.stem for path in directory.glob("*.md"))


def load_prompt(name: str, dirpath: Path | None = None) -> str:
    """Instruction body of prompt `name`, with editor wrappers removed.

    Raises `UnknownPrompt` when the name has no file in the library.
    """
    path = (PROMPTS_DIR if dirpath is None else dirpath) / f"{name}.md"
    if not path.is_file():
        raise UnknownPrompt(name, prompt_names(dirpath))
    return strip_wrappers(path.read_text(encoding="utf-8"))


def strip_wrappers(text: str) -> str:
    """Remove the ```` ```prompt ```` fence and YAML frontmatter, in any order.

    Both wrappers are optional and either may come first.  The fence wraps the
    whole file, so its closing delimiter is the last fence line in it; frontmatter
    is a `---` block at the top, and a block that opens and closes on adjacent
    lines is no frontmatter at all.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    if lines and lines[0] == FENCE_OPEN:
        lines.pop(0)
        _drop_wrapper_fence(lines)

    _drop_frontmatter(lines)

    return "\n" + "\n".join(lines).strip("\n") + "\n"


def _drop_wrapper_fence(lines: list[str]) -> None:
    """Cut the closing line of a whole-file ```prompt fence, if present."""
    for index in range(len(lines) - 1, -1, -1):
        if lines[index] == FENCE_CLOSE:
            del lines[index:]
            return


def _drop_frontmatter(lines: list[str]) -> None:
    """Cut a frontmatter block at the top of `lines`, if there is one."""
    if not lines or lines[0] != FRONTMATTER_DELIM:
        return
    if len(lines) < 2 or lines[1] == FRONTMATTER_DELIM:
        return  # an empty block: no frontmatter to consume
    for index in range(1, len(lines)):
        if lines[index] == FRONTMATTER_DELIM:
            del lines[: index + 1]
            return
