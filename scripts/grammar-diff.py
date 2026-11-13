#!/usr/bin/env python3
"""grammar-diff — proofreading input from a git diff (text-forge).

Takes the added lines of `--since..HEAD` inside the author's scope, drops the
noise (quote blocks, link retargeting, structural lines) and writes two artifacts:
JSON for tooling and markdown for a human proofreader, both carrying `file:line`
addresses so a finding can be handed back as an address.

Why not `git diff | grep '^+' | sed 's/^+//'`: grep throws the address away and
drags third-party quotes and link churn into the text to be read.

Exit codes
    0  input written
    1  `--since` did not resolve to a commit (or the root is not a git repo)
    2  no added lines to check after the diff (nothing written)

JSON schema
    {"base": str, "head": str, "scope": str,
     "files": {file: [{"line": int, "text": str}]},
     "dropped": {"link_only": int, "quote": int, "structural": int},
     "typography": [{"file": str, "line": int, "kind": str, "fragment": str}]}

All the logic lives in `text_forge.grammar`; importing this module has no side
effects.  Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# scripts/ has no package, so the sibling text_forge package is reached by path —
# the same trick the other wrappers in this directory use.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from text_forge.grammar import (
    DROP_REASONS,
    AddedLine,
    GitError,
    Issue,
    build_file_payload,
    build_payload,
    render_markdown,
    resolve_ref,
)

DEFAULT_JSON_NAME = "grammar-input.json"
DEFAULT_MD_NAME = "grammar-input.md"
EXIT_OK = 0
EXIT_BAD_REF = 1
EXIT_NOTHING = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="grammar-diff.py",
        description=(
            "Build the proofreading input for a text project: added lines of "
            "--since..HEAD, filtered, with file:line addresses."
        ),
    )
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--since",
        default=None,
        metavar="REF",
        help="diff base, inclusive of that commit's own changes; omitted means "
        "the working tree vs HEAD",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="FILE",
        help="proofread this one file whole (no diff); excludes --since",
    )
    parser.add_argument(
        "--scope",
        choices=("wtd", "all"),
        default="wtd",
        help="wtd (default): text/p*.md + text/index.md; all: text/**/*.md",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help=f"where to write JSON (default: <root>/build/{DEFAULT_JSON_NAME})",
    )
    parser.add_argument(
        "--md",
        dest="md_path",
        default=None,
        help=f"where to write markdown (default: <root>/build/{DEFAULT_MD_NAME})",
    )
    parser.add_argument(
        "--typo",
        action="store_true",
        help="add the typography section to the artifacts",
    )
    return parser.parse_args(argv)


def _artifacts(root: Path, args: argparse.Namespace) -> tuple[Path, Path]:
    build = root / "build"
    json_path = Path(args.json_path) if args.json_path else build / DEFAULT_JSON_NAME
    md_path = Path(args.md_path) if args.md_path else build / DEFAULT_MD_NAME
    out_json = json_path if json_path.is_absolute() else root / json_path
    out_md = md_path if md_path.is_absolute() else root / md_path
    return out_json, out_md


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _summary(payload: dict[str, Any]) -> str:
    """One line of facts: kept, dropped per reason, files, typography per kind."""
    files = payload["files"]
    kept = sum(len(rows) for rows in files.values())
    dropped = payload["dropped"]
    typo = Counter(item["kind"] for item in payload["typography"])
    dropped_bits = ", ".join(
        f"{reason}={dropped.get(reason, 0)}" for reason in DROP_REASONS
    )
    parts = [
        f"scope={payload['scope']}",
        f"base={payload['base']}",
        f"head={payload['head'][:9]}",
        f"kept {kept}",
        f"in {len(files)} file(s)",
        f"dropped: {dropped_bits}",
    ]
    if payload["typography"]:
        kinds = ", ".join(f"{kind}={typo[kind]}" for kind in sorted(typo))
        parts.append(f"typography: {kinds}")
    else:
        parts.append("typography: 0")
    return "; ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return EXIT_BAD_REF
    if args.only and args.since:
        print("--only and --since are mutually exclusive", file=sys.stderr)
        return EXIT_NOTHING

    if args.only:
        try:
            payload = build_file_payload(root, args.only, with_typography=args.typo)
        except FileNotFoundError as exc:
            print(f"{exc}", file=sys.stderr)
            return EXIT_BAD_REF
        except GitError as exc:
            print(f"git failed: {exc}", file=sys.stderr)
            return EXIT_BAD_REF
    else:
        base_ref = args.since if args.since else "HEAD"
        if not resolve_ref(root, base_ref):
            print(f"Cannot resolve --since ref: {args.since}", file=sys.stderr)
            return EXIT_BAD_REF
        try:
            payload = build_payload(
                root, base_ref, args.scope, with_typography=args.typo
            )
        except GitError as exc:
            print(f"git failed: {exc}", file=sys.stderr)
            return EXIT_BAD_REF

    if not payload["files"]:
        print("No added lines to check.")
        return EXIT_NOTHING

    json_path, md_path = _write_artifacts(root, args, payload)
    print(_summary(payload))
    print(f"json: {json_path}")
    print(f"md:   {md_path}")
    return EXIT_OK


def _write_artifacts(
    root: Path, args: argparse.Namespace, payload: dict[str, Any]
) -> tuple[Path, Path]:
    """Write JSON + markdown; returns the paths written."""
    json_path, md_path = _artifacts(root, args)
    _write(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    added = {
        file: [
            AddedLine(file=file, line=r["line"], text=r["text"], commit=payload["head"])
            for r in rows
        ]
        for file, rows in payload["files"].items()
    }
    issues = [
        Issue(item["file"], item["line"], item["kind"], item["fragment"])
        for item in payload["typography"]
    ]
    _write(md_path, render_markdown(added, issues, payload))
    return json_path, md_path


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
