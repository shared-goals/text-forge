#!/usr/bin/env python3
"""section-diff — what a section says now against what it said at a base ref.

Answers the digest question («what did this section stop saying and start
saying»), not the hunk question («where did lines change»).

Usage
    scripts/section-diff.py --root REPO --base REF --head REF --file PATH

Exit codes
    0  printed (nothing changed prints nothing)
    2  usage: repo, ref or file not found

All the logic lives in `text_forge.section_diff`.
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

from text_forge import console
from text_forge.section_diff import diff_sections, render, show

EXIT_OK = 0
EXIT_BAD_INPUT = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="section-diff.py",
        description="Per-section before/after diff of one markdown file.",
    )
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--base", required=True, metavar="REF", help="older ref")
    parser.add_argument("--head", default="HEAD", metavar="REF", help="newer ref")
    parser.add_argument(
        "--file", required=True, metavar="PATH", help="file in the repo"
    )
    parser.add_argument(
        "--full", action="store_true", help="keep two lines of context per change"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        console.fail(f"not a directory: {root}")
        return EXIT_BAD_INPUT
    old = show(root, args.base, args.file)
    new = show(root, args.head, args.file)
    if old is None or new is None:
        console.fail(f"not in {args.base!r}/{args.head!r}: {args.file}")
        return EXIT_BAD_INPUT

    deltas = diff_sections(old, new, context=2 if args.full else 0)
    if not deltas:
        console.warn("no section changed — links, wording or nothing at all")
        return EXIT_OK
    print(render(deltas), end="")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
