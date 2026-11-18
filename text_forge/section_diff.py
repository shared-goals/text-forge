"""section_diff — what a markdown section says now against what it said before.

A hunk list answers «where did lines change». An editorial summary needs a
different question: «what did this section stop saying and start saying». A
rewritten paragraph arrives as a `-`/`+` pair that a hunk list renders as pure
addition, and a renamed heading keeps its anchor — compare by title and the whole
body of a renamed section reads as new.

So: split both revisions into sections by heading, diff each section's body on
its own, and report only the sections whose text actually changed. Section
identity is the anchor when the heading has one, the title otherwise.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HEADING = re.compile(r"^(#{2,4})\s+(.*?)\s*(?:\{#([\w-]+)\})?\s*$")

#: Kinds of change a section can show up with.
NEW = "new"
RENAMED = "renamed"
CHANGED = "changed"


@dataclass(frozen=True)
class Section:
    """One heading and the body under it (`title` is empty before the first)."""

    title: str
    anchor: str
    body: list[str]

    @property
    def key(self) -> str:
        return self.anchor or self.title


@dataclass
class SectionDelta:
    """The changed lines of one section, plus how the section itself changed."""

    title: str
    anchor: str
    kind: str
    previous_title: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(1 for line in self.lines if line.startswith("+"))

    @property
    def removed(self) -> int:
        return sum(1 for line in self.lines if line.startswith("-"))

    @property
    def label(self) -> str:
        if not self.title:
            return "(до первого заголовка)"
        return f"{self.title} #{self.anchor}" if self.anchor else self.title

    @property
    def kind_label(self) -> str:
        if self.kind == NEW:
            return "новый раздел"
        if self.kind == RENAMED:
            return f"переименован: «{self.previous_title}» →  +{self.added}/-{self.removed}"
        return f"+{self.added}/-{self.removed}"


def split_sections(text: str) -> list[Section]:
    """Sections of a markdown document, in order.

    Text before the first heading is kept as a section with an empty title, so a
    frontmatter change cannot hide.
    """
    out: list[Section] = []
    title, anchor, body = "", "", []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            out.append(Section(title, anchor, body))
            title, anchor, body = match.group(2), match.group(3) or "", []
        else:
            body.append(line)
    out.append(Section(title, anchor, body))
    return out


def changed_lines(before: list[str], after: list[str], context: int = 0) -> list[str]:
    """The changed lines: `-` what the section stopped saying, `+` what it says
    now; with `context` > 0 the unchanged neighbours come along, space-prefixed.

    Context is dropped by default — a digest cares about the delta, not about
    what stayed."""
    lines = difflib.unified_diff(
        before, after, lineterm="", n=context, fromfile="", tofile=""
    )
    keep = []
    for line in lines:
        if line.startswith(("+++", "---", "@@")):
            continue
        if not line[1:].strip():
            continue
        if line.startswith(" ") and not context:
            continue
        keep.append(line)
    return keep


def diff_sections(old_text: str, new_text: str, context: int = 0) -> list[SectionDelta]:
    """Sections whose body changed, in document order."""
    before = {section.key: section for section in split_sections(old_text)}
    deltas: list[SectionDelta] = []
    for section in split_sections(new_text):
        previous = before.get(section.key)
        lines = changed_lines(previous.body if previous else [], section.body, context)
        renamed = previous is not None and previous.title != section.title
        # a rename with an untouched body is still a change worth reporting
        if not lines and not renamed:
            continue
        if previous is None:
            kind, previous_title = NEW, ""
        elif renamed:
            kind, previous_title = RENAMED, previous.title
        else:
            kind, previous_title = CHANGED, section.title
        deltas.append(
            SectionDelta(
                title=section.title,
                anchor=section.anchor,
                kind=kind,
                previous_title=previous_title,
                lines=lines,
            )
        )
    return deltas


def render(deltas: list[SectionDelta]) -> str:
    """The console form the digest procedure reads: one block per changed section."""
    blocks = []
    for delta in deltas:
        block = [f"### {delta.label}   [{delta.kind_label}]"]
        block.extend(f"  {line}" for line in delta.lines)
        blocks.append("\n".join(block))
    # a blank line before every block, including the first: the shape the digest
    # procedure already read from the shell version, so notes stay comparable
    return "".join(f"\n{block}\n" for block in blocks)


def show(root: Path, ref: str, path: str) -> str | None:
    """File contents at `ref`, or None when the ref or path is unknown."""
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None
