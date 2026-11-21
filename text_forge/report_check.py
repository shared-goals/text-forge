"""report_check — verify a proofreading report against the files it cites.

A report is written by a model, and a model can invent a `file:line` or a quote.
Reviewing dozens of findings by eye verifies two or three of them; the rest reach
the author with addresses that do not resolve, and he hunts for the line by hand.

Normalisation is not optional. The report contract prints a quote as it *reads*
-- `![text](target)` becomes the link text, markup disappears -- while the file
on disk still carries the targets. Comparing the two raw strings reports almost
every finding as a mismatch. So both sides go through the same `normalize()`.
Ellipsis counts as a fragment boundary, because a long line is legitimately
quoted in part.

Stdlib only: this runs where the checker runs, and it must not pull a dependency
into an environment that only has the text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# `](target)` first: the rest of the normalisation works on prose, not on URLs.
_LINK = re.compile(r"\]\([^)]*\)")
_NOISE = re.compile(r"[*_`\[\]]")
_ADDRESS = re.compile(r"^`([^`:]+\.md):(\d+)`", re.MULTILINE)
_QUOTE = re.compile(r"^>\s?(.*)$", re.MULTILINE)
# A quote glued from several places: `A / B`. The report contract allows one
# line, so this is a form error, and the checker can say where each piece lives.
_COMPOUND = re.compile(r"\s+/\s+")
_FINDING_SPLIT = re.compile(r"\n(?=### )")


def normalize(text: str) -> str:
    """The comparison form of one line: no link targets, no markup, single spaces."""
    text = _LINK.sub("]", text)
    text = _NOISE.sub("", text)
    text = text.replace("…", " ").replace("...", " ")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Finding:
    """One `### ` block: what it claims, and where it claims it."""

    label: str
    file: str
    line: int
    quote: str


@dataclass(frozen=True)
class Mismatch:
    """An address that resolved but does not say what the report says it says.

    `moved_to` is the line where the quoted text actually is, found by searching
    the same file. It is the difference between the two causes that look alike
    from the address alone: text edited since the run pushed the line down
    (nothing is wrong with the report, it is stale), or the quote was invented
    (there is nothing to find).
    """

    finding: Finding
    actual: str
    moved_to: int | None = None
    #: ``quote`` — the words are not on the line; ``multi`` — the finding quotes
    #: several lines; ``compound`` — the quote glues separate places with ``/``.
    reason: str = "quote"
    quote_lines: int = 0
    fragments: tuple[tuple[str, int | None], ...] = ()


@dataclass(frozen=True)
class AddressCheck:
    """Counts plus the failures, in the order they were found."""

    ok: int = 0
    no_address: int = 0
    missing_files: tuple[str, ...] = ()
    out_of_range: tuple[tuple[str, int], ...] = ()
    mismatched: tuple[Mismatch, ...] = ()

    def failed(self, *, strict: bool) -> bool:
        """A mismatch always fails; a finding with no address only when strict.

        Default-tolerant on purpose: the report format allows a finding whose
        address is a section rather than a line, and refusing the whole report
        over one of those teaches the reviewer to bypass the check.
        """
        if self.mismatched or self.missing_files or self.out_of_range:
            return True
        return strict and bool(self.no_address)


def parse_findings(report: str) -> list[Finding]:
    """Every `### ` block of the report, with its address and quote if present."""
    findings: list[Finding] = []
    for block in _FINDING_SPLIT.split(report):
        if not block.startswith("### "):
            continue
        label = block.splitlines()[0].strip()
        address = _ADDRESS.search(block)
        # every quote line, not the first: a finding that quotes two lines must
        # be a violation, not a finding verified by its first line alone
        quote = "\n".join(_QUOTE.findall(block))
        findings.append(
            Finding(
                label=label,
                file=address.group(1).strip() if address else "",
                line=int(address.group(2)) if address else 0,
                quote=quote,
            )
        )
    return findings


def _find_quote(lines: Sequence[str], quote: str) -> int | None:
    """The 1-based line carrying this quote, if any — the drift detector."""
    wanted = normalize(quote)
    if not wanted:
        return None
    for number, line in enumerate(lines, start=1):
        if wanted in normalize(line):
            return number
    return None


def _quote_matches(quote: str, actual_line: str) -> bool:
    """Does the quoted fragment appear in the line, in order and possibly clipped?"""
    wanted, actual = normalize(quote), normalize(actual_line)
    if not wanted:
        return True  # nothing quoted: the address was the whole claim
    if wanted in actual or actual in wanted:
        return True
    position = 0
    for word in wanted.split():
        found = actual.find(word, position)
        if found < 0:
            return False
        position = found + len(word)
    return True


def check_findings(root: Path, findings: Sequence[Finding]) -> AddressCheck:
    """Resolve every finding against `root`; never raise on a bad address.

    Failures are data, not exceptions: the caller prints all of them at once.
    """
    ok = no_address = 0
    missing: list[str] = []
    out_of_range: list[tuple[str, int]] = []
    mismatched: list[Mismatch] = []

    for finding in findings:
        if not finding.file:
            no_address += 1
            continue
        path = root / finding.file
        if not path.is_file():
            missing.append(finding.file)
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if finding.line > len(lines) or finding.line < 1:
            out_of_range.append((finding.file, finding.line))
            continue
        actual = lines[finding.line - 1]
        if "\n" in finding.quote:
            mismatched.append(
                Mismatch(
                    finding=finding,
                    actual=actual,
                    reason="multi",
                    quote_lines=finding.quote.count("\n") + 1,
                )
            )
            continue
        if _COMPOUND.search(finding.quote):
            pieces = [p.strip() for p in _COMPOUND.split(finding.quote) if p.strip()]
            mismatched.append(
                Mismatch(
                    finding=finding,
                    actual=actual,
                    reason="compound",
                    fragments=tuple(
                        (piece, _find_quote(lines, piece)) for piece in pieces
                    ),
                )
            )
            continue
        if _quote_matches(finding.quote, actual):
            ok += 1
        else:
            moved = _find_quote(lines, finding.quote)
            mismatched.append(Mismatch(finding=finding, actual=actual, moved_to=moved))

    return AddressCheck(
        ok=ok,
        no_address=no_address,
        missing_files=tuple(missing),
        out_of_range=tuple(out_of_range),
        mismatched=tuple(mismatched),
    )


def check_report(root: Path, report_path: Path) -> AddressCheck:
    """Convenience for callers that have a report file rather than its text."""
    return check_findings(root, parse_findings(report_path.read_text(encoding="utf-8")))
