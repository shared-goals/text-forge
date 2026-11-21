#!/usr/bin/env python3
"""check-report-addresses — verify a proofreading report against the files it cites.

Reads the report the model wrote (`build/grammar-report.md`), resolves every
`файл:строка` it names, and compares the quoted fragment with that line.

Why this exists: the report is written by a model and carries dozens of
findings. Two or three are checked by eye; the rest reach the author with
addresses that do not resolve, and hunting the line by hand is the cost. One
run answers "are all the addresses real" before the report is shown.

Exit codes
    0  every address resolves and every quote matches
    1  a finding names a missing file, a line past the end, or a quote that is
       not on that line (all printed; a quote that merely moved says which line
       it is on now)
    2  the report has no `### ` findings at all —  nothing was verified

`--strict` also fails on findings with no address. The default tolerates them:
the report format allows a finding addressed to a section, and one of those is
not worth refusing a whole report over.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ has no package: reach the sibling text_forge package by path, the
# same way the other wrappers here do.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from text_forge import console
from text_forge.report_check import check_report, parse_findings

EXIT_CLEAN = 0
EXIT_BAD = 1
EXIT_EMPTY = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check-report-addresses.py",
        description="Verify a proofreading report's `file:line` addresses and quotes.",
    )
    parser.add_argument("report", help="report file to check")
    parser.add_argument(
        "root", nargs="?", default=".", help="repository root (default: cwd)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail on findings that carry no address",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = Path(args.report)
    root = Path(args.root).resolve()

    if not report_path.is_file():
        console.fail(f"report not found: {console.rel(report_path)}")
        return EXIT_BAD
    if not root.is_dir():
        console.fail(f"not a directory: {root}")
        return EXIT_BAD

    findings = parse_findings(report_path.read_text(encoding="utf-8"))
    if not findings:
        console.fail(
            f"no `### ` findings in {console.rel(report_path)} — nothing verified"
        )
        return EXIT_EMPTY

    result = check_report(root, report_path)
    console.title("report check", f"{len(findings)} findings")
    console.detail("report", console.rel(report_path))

    for name in result.missing_files:
        console.fail(f"no such file: {name}")
    for name, line in result.out_of_range:
        console.fail(f"line past the end: {name}:{line}")
    for mismatch in result.mismatched:
        finding = mismatch.finding
        if mismatch.reason == "multi":
            # Checking only the first quote line would pass an invented second
            # one, so the form itself is the failure.
            console.fail(
                f"multi-line quote: {finding.file}:{finding.line} — "
                f"{mismatch.quote_lines} quote lines; one per finding"
            )
        elif mismatch.reason == "compound":
            console.fail(
                f"compound quote: {finding.file}:{finding.line} — "
                f"one line per finding, not pieces joined with '/'"
            )
            console.detail(
                "fragments",
                " · ".join(
                    f"{number}) {text[:40]} — line {line or 'not found'}"
                    for number, (text, line) in enumerate(mismatch.fragments, 1)
                ),
            )
        elif mismatch.moved_to is not None:
            # The quote exists, some lines away: the text changed after the run.
            # The report is stale, not wrong -- name the line it moved to.
            console.fail(
                f"line moved: {finding.file}:{finding.line} now says something else; "
                f"the quote is at {mismatch.moved_to}"
            )
        else:
            console.fail(f"quote not in this file: {finding.file}:{finding.line}")
        console.detail(
            "report", finding.quote[:110].replace(chr(10), " ⏎ ") or "(empty)"
        )
        console.detail("actual", mismatch.actual[:110])
    if result.no_address:
        console.warn(f"{result.no_address} finding(s) carry no address")

    console.counts(
        "checked",
        [
            ("ok", result.ok),
            ("mismatch", len(result.mismatched)),
            ("no_file", len(result.missing_files)),
            ("out_of_range", len(result.out_of_range)),
            ("no_address", result.no_address),
        ],
    )

    if result.failed(strict=args.strict):
        return EXIT_BAD
    console.done("every address resolves and every quote matches")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
