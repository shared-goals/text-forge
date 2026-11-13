#!/usr/bin/env python3
"""job.py — build a prompt job file: prompt body + input, ready for a runner.

A prompt-only instruction is not a job: the model also needs the diff, the
addressed line list, or the chapter dump glued behind it, with the separators the
prompt itself describes.  This script owns that glue; the content repo's Makefile
keeps only the runner choice (pi/stub), which is harness policy, not library logic.

Usage
    job.py --prompt NAME [--input FILE]... [--section TITLE=FILE]...
           [--footer TEXT] [--out PATH]

Rendering (exact — the prompt's own input markers depend on it)
    prompt body                       already ends with a newline
    each --input                      appended verbatim, no separator
    each --section                    "\n---\n\n## {TITLE}\n\n" + content for the
                                    first one, "\n## {TITLE}\n\n" + content for the
                                    rest (one rule per job, not per section — an
                                    extra rule shifts the line numbers a report
                                    cites); a .diff/.patch file is fenced
    --footer                          "\n---\n\n{TEXT}\n"

Exit codes
    0  job written (or printed to stdout)
    2  unknown prompt, unreadable input file, or a malformed --section

All the prompt logic lives in `text_forge.prompts`; importing this module has no
side effects.  Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

# scripts/ has no package, so the sibling text_forge package is reached by path —
# the same trick the other wrappers in this directory use.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from text_forge.prompts import UnknownPrompt, load_prompt

EXIT_OK = 0
EXIT_BAD_INPUT = 2
FENCE_LANG = {"diff": "diff", "patch": "diff"}
SECTION_SEP = "\n---\n\n"


class JobError(Exception):
    """A job could not be built: unknown prompt or unreadable file."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job.py",
        description=(
            "Build a prompt job file: prompt body, then inputs, then titled "
            "sections, then a footer."
        ),
    )
    parser.add_argument("--prompt", required=True, metavar="NAME", help="prompt name")
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        default=[],
        metavar="FILE",
        help="file appended right after the prompt; repeatable",
    )
    parser.add_argument(
        "--section",
        dest="sections",
        action="append",
        default=[],
        metavar="TITLE=FILE",
        help="file rendered under '## TITLE'; repeatable",
    )
    parser.add_argument("--footer", default=None, help="text after a final rule")
    parser.add_argument("--out", default=None, help="where to write (default: stdout)")
    return parser.parse_args(argv)


def load_body(name: str) -> str:
    """Prompt body for `name`; wraps UnknownPrompt into JobError."""
    try:
        return load_prompt(name)
    except UnknownPrompt as exc:
        raise JobError(str(exc)) from exc


def read_file(path: Path) -> str:
    """File content as text, with a trailing newline guaranteed."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JobError(f"Cannot read {path}: {exc.strerror}") from exc
    return content if content.endswith("\n") or not content else content + "\n"


def parse_section(spec: str) -> tuple[str, str]:
    """Split a `TITLE=FILE` argument into its two parts."""
    title, sep, path = spec.partition("=")
    if not sep or not title:
        raise JobError(f"Malformed --section (expected TITLE=FILE): {spec!r}")
    return title, path


def render_section(
    title: str, content: str, suffix: str = "", rule: str = SECTION_SEP
) -> str:
    """One section: separator, heading, then content (fenced for diff/patch)."""
    lang = FENCE_LANG.get(suffix.lstrip(".").lower())
    if lang and content:
        content = f"```{lang}\n{content}```\n"
    return f"{rule}## {title}\n\n{content}"


def build_job(
    name: str,
    inputs: Sequence[Path],
    sections: Sequence[tuple[str, Path]],
    footer: str | None,
) -> str:
    """The whole job file: prompt body, inputs, sections, footer."""
    parts = [load_body(name)]
    for path in inputs:
        parts.append(read_file(path))
    for position, (title, path) in enumerate(sections):
        rule = SECTION_SEP if position == 0 else "\n"
        parts.append(render_section(title, read_file(path), path.suffix, rule))
    if footer:
        parts.append(f"{SECTION_SEP}{footer}\n")
    return "".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sections = [parse_section(spec) for spec in args.sections]
        text = build_job(
            args.prompt,
            [Path(p) for p in args.inputs],
            [(title, Path(path)) for title, path in sections],
            args.footer,
        )
    except JobError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"job: {out} ({text.count(chr(10))} lines)")
    else:
        sys.stdout.write(text)
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
