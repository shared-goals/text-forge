#!/usr/bin/env python3
"""books-changed — the book notes a range touched, as author/shelf lines.

Writes one artifact for a changelog post: markdown grouped by shelf
(«Прочтённые», «Хочу прочитать», …), so the post can name the books that were
read instead of quoting book-page diffs.

Why not `git diff --name-only`: a book page is generated, so its diff is quotes
and frontmatter churn. What a post needs is which books appeared, disappeared or
moved shelf — which means reading each changed note's frontmatter, from disk for
a note that is here and from the base commit for a note that is not.

Usage
    scripts/books-changed.py --root <content-repo> --since <ref>
    uv run --project /path/to/text-forge python scripts/books-changed.py \
        --root "$PWD" --since <sha> --md /tmp/books.md

Exit codes
    0  ok — including «no book changed since the ref» (an empty file is written)
    1  `--since` did not resolve to a commit
    2  usage / not a git repository

All the logic lives in `text_forge.books_changed`; importing this module has no
side effects.  Stdlib + PyYAML only.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

# scripts/ has no package, so the sibling text_forge package is reached by path —
# the same trick the other wrappers in this directory use.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse

from text_forge import console
from text_forge.books_changed import (
    BookChange,
    GitError,
    changed_books,
    is_git_repo,
    render_books_markdown,
    resolve_ref,
)

DEFAULT_MD_NAME = "books-changed.md"
EXIT_OK = 0
EXIT_BAD_REF = 1
EXIT_USAGE = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="books-changed.py",
        description=(
            "List the book notes changed between --since and HEAD, grouped by "
            "shelf, as markdown."
        ),
    )
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--since",
        required=True,
        metavar="REF",
        help="diff base; 'HEAD' means the working tree against HEAD",
    )
    parser.add_argument(
        "--md",
        dest="md_path",
        default=None,
        help=f"where to write markdown (default: <root>/build/{DEFAULT_MD_NAME})",
    )
    return parser.parse_args(argv)


def _md_path(root: Path, args: argparse.Namespace) -> Path:
    """Output path, with the documented <root>/build default applied."""
    path = Path(args.md_path) if args.md_path else root / "build" / DEFAULT_MD_NAME
    return path if path.is_absolute() else root / path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _report(changes: Sequence[BookChange], base_ref: str, md_path: Path) -> None:
    """Range, totals per change kind, shelves touched, artifact path."""
    kinds = Counter(c.change for c in changes)
    shelves = Counter(c.shelf or "no shelf" for c in changes)
    console.title("books changed", note=f"{base_ref[:9]}..HEAD")
    console.detail("total", f"{len(changes)} book(s)")
    per_kind = [(k, kinds.get(k, 0)) for k in ("added", "modified", "removed")]
    console.counts("kind", per_kind)
    console.counts("shelf", sorted(shelves.items()))
    console.detail("md", console.rel(md_path))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        console.fail(f"--root is not a directory: {root}")
        return EXIT_USAGE
    if not is_git_repo(root):
        console.fail(f"not a git repository: {root}")
        return EXIT_USAGE

    if not resolve_ref(root, args.since):
        console.fail(f"cannot resolve --since ref: {args.since}")
        return EXIT_BAD_REF

    try:
        changes = changed_books(root, args.since)
    except GitError as exc:
        console.fail(f"git failed: {exc}")
        return EXIT_BAD_REF

    md_path = _md_path(root, args)
    _write(md_path, render_books_markdown(changes, args.since))
    if changes:
        _report(changes, args.since, md_path)
    else:
        console.warn("no book changed since the ref — empty list written")
        console.detail("md", console.rel(md_path))
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
