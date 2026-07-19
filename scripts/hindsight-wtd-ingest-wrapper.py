#!/usr/bin/env python3
"""Canonical wrapper for WTD -> Hindsight ingestion.

This script orchestrates:
- `wtd-inventory.py` to build inventory JSON from MkDocs content
- `hindsight-ingest.py` to preview or ingest that inventory into Hindsight

It is designed to live in the text-forge repo so downstream wrappers can
delegate to one canonical implementation.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

from hindsight_common import ensure_no_proxy

DEFAULT_TEXT_FORGE = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "http://localhost:8889"
DEFAULT_BANK = "hermes"
DEFAULT_STRATEGY = "wtd-primary"


def run(cmd: list[str], *, cwd: pathlib.Path | None = None, stdout=None) -> None:
    printable = " ".join(cmd)
    if cwd:
        print(f"$ (cd {cwd} && {printable})")
    else:
        print(f"$ {printable}")
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    subprocess.run(cmd, cwd=cwd, check=True, stdout=stdout, env=env)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, write_through=True)

    parser = argparse.ArgumentParser(description="WTD inventory -> Hindsight wrapper using text-forge scripts")
    parser.add_argument("--text-forge", type=pathlib.Path, default=DEFAULT_TEXT_FORGE)
    parser.add_argument("--root", type=pathlib.Path, required=True, help="WTD repository root containing mkdocs.yml")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--bank", default=DEFAULT_BANK)
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY)
    parser.add_argument("--chapter", help="Process one chapter slug, e.g. p2-200-text")
    parser.add_argument("--section", help="Process one section_uid or anchor, e.g. digital_format_freedom")
    parser.add_argument("--limit", type=int, default=None, help="Chunk limit (default: all)")
    parser.add_argument("--summary", action="store_true", help="Print inventory summary before ingest")
    parser.add_argument("--no-drafts", action="store_true", help="Exclude draft chapters from inventory")
    parser.add_argument("--yes", action="store_true", help="Actually ingest memories (default is preview)")
    parser.add_argument("--batch-size", type=int, default=25, help="Items per retain request")
    parser.add_argument("--update-mode", choices=["replace", "append"], default="replace", help="Document update policy")
    parser.add_argument("--delta", action="store_true", help="Alias for --update-mode append")
    args = parser.parse_args()

    ensure_no_proxy()

    text_forge = args.text_forge.expanduser().resolve()
    wtd_root = args.root.expanduser().resolve()
    inventory_script = text_forge / "scripts" / "wtd-inventory.py"
    ingest_script = text_forge / "scripts" / "hindsight-ingest.py"
    config = wtd_root / "mkdocs.yml"

    missing = [p for p in [inventory_script, ingest_script, config] if not p.exists()]
    if missing:
        print("ERROR: required file not found:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    include_drafts = not args.no_drafts
    inventory_base = ["uv", "run", "python", str(inventory_script), "--config", str(config)]
    if include_drafts:
        inventory_base.append("--include-drafts")

    if args.summary:
        run(inventory_base + ["--format", "summary"], cwd=text_forge)
        print()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        inventory_path = pathlib.Path(f.name)

    try:
        with inventory_path.open("w", encoding="utf-8") as out:
            run(inventory_base + ["--format", "json"], cwd=text_forge, stdout=out)

        ingest_cmd = [
            "uv",
            "run",
            "python",
            str(ingest_script),
            "--inventory",
            str(inventory_path),
            "--api-url",
            args.api_url,
            "--bank",
            args.bank,
            "--strategy",
            args.strategy,
        ]
        if args.yes:
            ingest_cmd.append("--yes")
        else:
            ingest_cmd.append("--dry-run")
        if args.chapter:
            ingest_cmd.extend(["--chapter", args.chapter])
        if args.section:
            ingest_cmd.extend(["--section", args.section])
        if args.limit is not None:
            ingest_cmd.extend(["--limit", str(args.limit)])
        ingest_cmd.extend(["--batch-size", str(args.batch_size)])
        ingest_cmd.extend(["--update-mode", args.update_mode])
        if args.delta:
            ingest_cmd.append("--delta")
        run(ingest_cmd, cwd=text_forge)
    finally:
        try:
            inventory_path.unlink()
        except FileNotFoundError:
            pass

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
