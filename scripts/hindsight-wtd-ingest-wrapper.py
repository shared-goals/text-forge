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
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from hindsight_common import WTD_BASE_TAGS, ensure_no_proxy, latest_document
from wtd_sections_common import anchored_headings

DEFAULT_TEXT_FORGE = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "http://localhost:8889"
DEFAULT_BANK = "hermes"
DEFAULT_STRATEGY = "wtd-primary"
UV_CANDIDATE_PATHS = (
    pathlib.Path("/opt/homebrew/bin/uv"),
    pathlib.Path("/usr/local/bin/uv"),
)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def chapter_from_text_path(path: str) -> str | None:
    if not path.startswith("text/") or not path.endswith(".md"):
        return None
    return pathlib.Path(path).stem


def last_ingest_document(
    api_url: str, bank: str
) -> tuple[dict | None, Exception | None]:
    try:
        return latest_document(api_url, bank, WTD_BASE_TAGS), None
    except (RuntimeError, OSError) as exc:
        return None, exc


def print_last_ingest(doc: dict | None, error: Exception | None) -> None:
    if error is not None:
        print(f"Last ingest: unavailable ({error})")
        return
    if not doc:
        print(f"Last ingest: no documents tagged {'+'.join(WTD_BASE_TAGS)}")
        return
    meta = doc.get("document_metadata") or {}
    print(
        "Last ingest: "
        f"updated_at={doc.get('updated_at', 'unknown')} "
        f"commit={meta.get('commit', 'unknown')} "
        f"document={doc.get('id', 'unknown')}"
    )
    for label, key in (
        ("chapter", "chapter"),
        ("section", "section_uid"),
        ("status", "status"),
        ("changed_at", "changed_at"),
    ):
        if meta.get(key):
            print(f"  {label}: {meta[key]}")


def changed_line_ranges(
    repo_root: pathlib.Path, before: str, after: str, rel_path: str
) -> list[tuple[int, int]]:
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "diff",
        "--unified=0",
        "--no-color",
        before,
        after,
        "--",
        rel_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        match = HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count <= 0:
            continue
        end = start + count - 1
        ranges.append((start, end))
    return ranges


def section_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    headings = anchored_headings(lines)
    if not headings:
        return []
    out: list[tuple[str, int, int]] = []
    for index, (line_no, _lvl, _heading, anchor) in enumerate(headings):
        next_line = (
            headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        )
        end_line = max(line_no, next_line - 1)
        out.append((anchor, line_no, end_line))
    return out


def ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def build_diff_plan(
    repo_root: pathlib.Path, before: str, after: str
) -> dict[str, object]:
    files_cmd = [
        "git",
        "-C",
        str(repo_root),
        "diff",
        "--name-only",
        before,
        after,
        "--",
        "text/*.md",
    ]
    files_result = subprocess.run(files_cmd, check=True, capture_output=True, text=True)
    changed_files = [p.strip() for p in files_result.stdout.splitlines() if p.strip()]

    sections: list[dict[str, str]] = []
    fallback_chapters: set[str] = set()

    for rel_path in changed_files:
        chapter = chapter_from_text_path(rel_path)
        if not chapter:
            continue
        source = repo_root / rel_path
        if not source.exists():
            fallback_chapters.add(chapter)
            continue

        diff_ranges = changed_line_ranges(repo_root, before, after, rel_path)
        lines = source.read_text(encoding="utf-8").splitlines()
        spans = section_ranges(lines)
        if not spans:
            fallback_chapters.add(chapter)
            continue

        matched: set[str] = set()
        for start, end in diff_ranges:
            for anchor, sec_start, sec_end in spans:
                if ranges_overlap(start, end, sec_start, sec_end):
                    matched.add(anchor)

        if matched:
            for anchor in sorted(matched):
                sections.append(
                    {"chapter": chapter, "section": anchor, "source_path": rel_path}
                )
        if not matched:
            fallback_chapters.add(chapter)

    return {
        "before": before,
        "after": after,
        "changed_files": changed_files,
        "sections": sections,
        "fallback_chapters": sorted(fallback_chapters),
    }


def resolve_diff_range(
    repo_root: pathlib.Path,
    commit: str | None,
    since: str | None = None,
    after: str | None = None,
) -> tuple[str, str] | None:
    def rev_parse(rev: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", rev], text=True
        ).strip()

    def parent_of(rev: str) -> str:
        try:
            return rev_parse(f"{rev}^")
        except subprocess.CalledProcessError:
            return rev

    if after:
        return rev_parse(f"{after}^{{commit}}"), rev_parse("HEAD")
    if since:
        return parent_of(rev_parse(f"{since}^{{commit}}")), rev_parse("HEAD")
    if commit:
        commit_sha = rev_parse(f"{commit}^{{commit}}")
        return parent_of(commit_sha), commit_sha
    return None


def python_runner_for_text_forge(text_forge: pathlib.Path) -> tuple[list[str], str]:
    """Return command prefix for running text-forge scripts.

    Prefer uv when present; otherwise use repo-local venv python if available.
    """
    override = os.environ.get("UV_BIN", "").strip()
    if override:
        p = pathlib.Path(override).expanduser()
        if p.exists() and p.is_file() and os.access(p, os.X_OK):
            return [str(p), "run", "python"], "uv"

    uv_bin = shutil.which("uv")
    if uv_bin:
        return [uv_bin, "run", "python"], "uv"

    for candidate in UV_CANDIDATE_PATHS:
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            return [str(candidate), "run", "python"], "uv"

    venv_python = text_forge / ".venv" / "bin" / "python"
    if venv_python.exists():
        return [str(venv_python)], "venv"
    legacy_venv_python = text_forge / "venv" / "bin" / "python"
    if legacy_venv_python.exists():
        return [str(legacy_venv_python)], "legacy_venv"
    return [sys.executable], "system_python"


def run(
    cmd: list[str],
    *,
    cwd: pathlib.Path | None = None,
    stdout=None,
    quiet: bool = False,
) -> None:
    if not quiet:
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

    parser = argparse.ArgumentParser(
        description="WTD inventory -> Hindsight wrapper using text-forge scripts"
    )
    parser.add_argument("--text-forge", type=pathlib.Path, default=DEFAULT_TEXT_FORGE)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        required=True,
        help="WTD repository root containing mkdocs.yml",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--bank", default=DEFAULT_BANK)
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY)
    parser.add_argument("--chapter", help="Process one chapter slug, e.g. p2-200-text")
    parser.add_argument(
        "--section",
        help="Process one section_uid or anchor, e.g. digital_format_freedom",
    )
    parser.add_argument(
        "--commit",
        help="Ingest only sections changed by this single commit (parent..commit)",
    )
    parser.add_argument(
        "--since",
        help="Ingest sections changed from this ref (inclusive) through HEAD",
    )
    parser.add_argument(
        "--after",
        help="Ingest sections changed after this ref (exclusive) through HEAD",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only print computed section/chapter plan",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Chunk limit (default: all)"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print inventory summary before ingest"
    )
    parser.add_argument(
        "--no-drafts", action="store_true", help="Exclude draft chapters from inventory"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually ingest memories (default is preview)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=25, help="Items per retain request"
    )
    parser.add_argument(
        "--update-mode",
        choices=["replace", "append"],
        default="replace",
        help="Document update policy",
    )
    parser.add_argument(
        "--delta", action="store_true", help="Alias for --update-mode append"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process the whole corpus (rare full reingest)",
    )
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
    py_cmd, runtime_mode = python_runner_for_text_forge(text_forge)
    print(f"Runtime mode: {runtime_mode}")
    last_doc, last_err = last_ingest_document(args.api_url, args.bank)
    print_last_ingest(last_doc, last_err)

    if args.section and not args.chapter:
        print("ERROR: --section requires --chapter", file=sys.stderr)
        return 1

    commit_scopes = [
        name
        for name, value in (
            ("--commit", args.commit),
            ("--since", args.since),
            ("--after", args.after),
        )
        if value
    ]
    if len(commit_scopes) > 1:
        print(
            f"ERROR: use only one of {', '.join(commit_scopes)}",
            file=sys.stderr,
        )
        return 1

    auto_scope = False
    if not (args.chapter or commit_scopes or args.all):
        # Default scope: everything after the last ingested commit.
        if last_err is not None:
            print(
                "ERROR: last ingest unknown; pass a scope explicitly (e.g. --after <ref>)",
                file=sys.stderr,
            )
            return 1
        last_commit = ((last_doc or {}).get("document_metadata") or {}).get("commit")
        if not last_commit:
            print(
                "ERROR: no previous ingest found; run with --all for the first ingest",
                file=sys.stderr,
            )
            return 1
        args.after = str(last_commit)
        auto_scope = True
        print(f"Default scope: --after {args.after} (last ingested commit)")

    diff_range = None
    if args.commit or args.since or args.after:
        scope_ref = args.commit or args.since or args.after
        try:
            diff_range = resolve_diff_range(wtd_root, args.commit, args.since, args.after)
        except subprocess.CalledProcessError:
            print(
                f"ERROR: cannot resolve ref {scope_ref!r}; pass an explicit --after <ref>",
                file=sys.stderr,
            )
            return 1
    if diff_range and (args.chapter or args.section):
        print(
            "ERROR: commit range cannot be combined with --chapter/--section",
            file=sys.stderr,
        )
        return 1

    sections_plan: list[tuple[str, str]] = []
    fallback_chapters: list[str] = []
    if diff_range:
        before, after = diff_range
        plan = build_diff_plan(wtd_root, before, after)
        print(
            "Diff plan: "
            f"files={len(plan['changed_files'])}, "
            f"sections={len(plan['sections'])}, "
            f"chapter_fallback={len(plan['fallback_chapters'])}"
        )
        sections_plan = [
            (entry["chapter"], entry["section"]) for entry in plan["sections"]
        ]  # type: ignore[index]
        fallback_chapters = list(plan["fallback_chapters"])  # type: ignore[arg-type]
        if args.plan_only:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if not sections_plan and not fallback_chapters:
            print(f"No changes in text/*.md for range {before[:12]}..{after[:12]}")
            return 0

    targets: list[tuple[str, str | None]] = []
    if sections_plan or fallback_chapters:
        targets.extend((chapter, section) for chapter, section in sections_plan)
        targets.extend((chapter, None) for chapter in fallback_chapters)
    elif args.chapter:
        targets.append((args.chapter, args.section))
    brief = len(targets) > 1

    inventory_base = [*py_cmd, str(inventory_script), "--config", str(config)]
    if include_drafts:
        inventory_base.append("--include-drafts")

    if args.summary:
        run(inventory_base + ["--format", "summary"], cwd=text_forge)
        print()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        inventory_path = pathlib.Path(f.name)

    try:
        with inventory_path.open("w", encoding="utf-8") as out:
            run(
                inventory_base + ["--format", "json"],
                cwd=text_forge,
                stdout=out,
                quiet=brief,
            )

        base_ingest_cmd = [
            *py_cmd,
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
            base_ingest_cmd.append("--yes")
        else:
            base_ingest_cmd.append("--dry-run")
        if args.limit is not None:
            base_ingest_cmd.extend(["--limit", str(args.limit)])
        base_ingest_cmd.extend(["--batch-size", str(args.batch_size)])
        base_ingest_cmd.extend(["--update-mode", args.update_mode])
        if args.delta:
            base_ingest_cmd.append("--delta")

        if not targets:
            run(base_ingest_cmd, cwd=text_forge)
        else:
            if brief:
                inv = json.loads(inventory_path.read_text(encoding="utf-8"))
                print(
                    f"\nInventory commit: {inv.get('commit')} ({inv.get('commit_date')})"
                )
                print(f"API: {args.api_url}, bank: {args.bank}")
                print(f"Mode: {'live ingest' if args.yes else 'preview'}")
                print(f"\nTargets ({len(targets)}):")
                for chapter, section in targets[:20]:
                    print(f"  {chapter}" + (f" #{section}" if section else ""))
                if len(targets) > 20:
                    print(f"  … and {len(targets) - 20} more")
                base_ingest_cmd.append("--brief")
            for chapter, section in targets:
                ingest_cmd = [*base_ingest_cmd, "--chapter", chapter]
                if section:
                    ingest_cmd.extend(["--section", section])
                run(ingest_cmd, cwd=text_forge, quiet=brief)
        if not args.yes:
            print("\nPreview only — no writes performed.")
            if auto_scope:
                hint = "make ingest"
            elif args.chapter:
                hint = f"make ingest CHAPTER={args.chapter}"
                if args.section:
                    hint += f" SECTION={args.section}"
            elif args.commit:
                hint = f"make ingest COMMIT={args.commit}"
            elif args.since:
                hint = f"make ingest SINCE={args.since}"
            elif args.after:
                hint = f"make ingest AFTER={args.after}"
            else:
                hint = "make ingest FULL=yes"
            print(f"To apply: {hint} APPLY=yes")
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
