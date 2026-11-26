"""text_forge.grammar — proofreading input built from a git diff.

Tasks this module covers:

1. `extract_added_lines(root, base_ref, scope)` — `base_ref..HEAD` added lines with
   NEW-side line numbers, keyed per file.
2. Filters: `is_link_only_change`, `quote_line_ranges`, `is_structural`, and
   `filter_noise` which combines them and counts every drop by reason.
3. `typography_issues` — double space inside a phrase, markdown hard break, space
   before punctuation, cyrillic/latin homoglyphs.
4. `render_markdown` + `build_payload` — the report/JSON the CLI writes.

Why not `git diff | grep '^+'`: grep throws the line address away and pulls in
third-party quotes and link retargeting churn.

Scope note: in a git pathspec `*` crosses `/`, so the plain glob `text/*.md` also
matches `text/books/*.md` (hundreds of quotes by other people).  Two defences: the
`wtd` scope names the two authored chapter families plus the hub page
(`text/p1-*.md`, `text/p2-*.md`, `text/index.md`), which cannot reach
`text/books/` or the generated `text/p3-references.md` at all, and scope globs are turned into `:(glob)` pathspecs, where
`*` stops at `/`.  `all` (`text/**/*.md`) is deliberately the wide scope: it does
reach the note-books, and the quote/link/structural filters are what keeps their
text out of the result.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Author-only default scope: chapters plus the hub page.  A pathspec is written
# with `:(glob)` because a plain git glob matches `*` across `/`, which would let
# `text/*.md` swallow `text/books/**` — hundreds of quotes by other people.
SCOPE_WTD: tuple[str, ...] = ("text/p1-*.md", "text/p2-*.md", "text/index.md")
SCOPE_ALL: tuple[str, ...] = ("text/**/*.md",)
SCOPES: dict[str, tuple[str, ...]] = {"wtd": SCOPE_WTD, "all": SCOPE_ALL}


def scope_globs(scope: Sequence[str]) -> list[str]:
    """Scope globs as `:(glob)` pathspecs.

    `:(glob)` is what keeps `*` from crossing `/`: without it the plain git glob
    `text/*.md` also matches `text/books/note.md`, and one author's chapters get
    mixed with a few hundred quotes by other people.  So the scope lists are
    written as globs and a caller who wants the flat `text/*.md` spelling gets the
    same result as `text/*/*.md` included — which is exactly why the scopes name
    what they mean (`text/p*.md`) instead of leaning on `*`.
    """
    return [f":(glob){glob}" for glob in scope]


# Drop reasons of `filter_noise`, in the order they are tested.
REASON_QUOTE = "quote"
REASON_LINK_ONLY = "link_only"
REASON_STRUCTURAL = "structural"
DROP_REASONS: tuple[str, ...] = (REASON_QUOTE, REASON_LINK_ONLY, REASON_STRUCTURAL)

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")

# Markdown link, inline `[text](target)` or reference `[text][ref]`.  A target
# carries no prose, so "link-only" is decided on the link text alone; `!` marks an
# image, which carries no prose at all.
MD_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\[([^\]]*)\]")

# Block marker: `///`, `/// kind`, `   /// kind | атрибут`.  Whatever follows `///`
# is the marker's remainder; a block OPENS only when that remainder starts with a
# kind word, so a bare `///` (or `/// | подпись`) can only ever close.
BLOCK_MARKER_RE = re.compile(r"^\s*///\s*(.*)$")
MARKER_KIND_RE = re.compile(r"^([A-Za-z][\w-]*)")
QUOTE_KIND = "quote"

REF_DEFINITION_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+\S")
IMAGE_LINE_RE = re.compile(r"^(?:\s*!\[[^\]]*\]\([^)]*\)\s*)+$")
FRONTMATTER_FENCE = "---"
# "does this line contain a word at all?" — cyrillic included (\w is unicode-aware
# but the explicit class keeps the intent obvious and the check local).
WORD_CHAR_RE = re.compile(r"[\wа-яА-ЯёЁ]")

# Typography (ported from wtd-grammar/scripts/scan_typography.py).
CYR_RE = re.compile(r"[а-яА-ЯёЁ]")
LAT_RE = re.compile(r"[a-zA-Z]")
WORD_TRIM_RE = re.compile(r"^[^\wа-яА-ЯёЁ]+|[^\wа-яА-ЯёЁ]+$")
DOUBLE_SPACE_RE = re.compile(r"\S  +\S")
TRAILING_DOUBLE_SPACE_RE = re.compile(r"\S  +$")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+[.,;:!?](?=\s|$)")
LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
MIN_HOMOGLYPH_WORD = 4  # "longer than 3 characters"
# Tokens that are plumbing rather than prose: link syntax, URLs, anchors, files.
SKIP_TOKEN_MARKERS = ("](", "http", "www.", "//", ".md", ".png", ".jpg")

KIND_DOUBLE_SPACE = "double_space"
KIND_TRAILING_DOUBLE_SPACE = "trailing_double_space"
KIND_SPACE_BEFORE_PUNCT = "space_before_punct"
KIND_HOMOGLYPH = "homoglyph"
TYPO_KINDS: tuple[str, ...] = (
    KIND_DOUBLE_SPACE,
    KIND_SPACE_BEFORE_PUNCT,
    KIND_HOMOGLYPH,
    KIND_TRAILING_DOUBLE_SPACE,
)


@dataclass(frozen=True)
class AddedLine:
    file: str  # path relative to root, exactly as git reports it
    line: int  # 1-based line number in the NEW version of the file
    text: str  # line content without the leading '+'
    commit: str  # HEAD sha the diff belongs to


@dataclass(frozen=True)
class Hunk:
    """One `-U0` hunk: the +/- lines it carries, with new-side numbering."""

    file: str
    added: tuple[tuple[int, str], ...]
    removed: tuple[tuple[int, str], ...]

    @property
    def removed_texts(self) -> list[str]:
        return [text for _no, text in self.removed]


@dataclass(frozen=True)
class Issue:
    file: str
    line: int
    kind: str
    fragment: str


class GitError(RuntimeError):
    """A git invocation failed; the message carries stderr."""


def _git_text(root: Path, args: Sequence[str]) -> str:
    """Run git in `root` and return stdout; raise GitError with stderr on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def head_sha(root: Path) -> str:
    """HEAD sha of `root`."""
    return _git_text(root, ["rev-parse", "HEAD"]).strip()


def resolve_ref(root: Path, ref: str) -> str | None:
    """Resolve `ref` to a commit sha, or None when it names no commit.

    `rev-list -n 1 <ref>` (no `--`: rev-list reads revisions BEFORE `--`, so that
    form rejects every ref) with stderr captured, so a bogus ref returns None
    instead of leaking usage text into the console.
    """
    proc = subprocess.run(
        ["git", "rev-list", "-n", "1", ref],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().split("\n")[0].strip() or None


def parse_diff(diff: str) -> list[Hunk]:
    """Parse a `-U0` unified diff into hunks with new-side line numbers.

    `@@ -a,b +c,d @@` puts the first added line of the hunk at `c`, and with
    `-U0` nothing but +/- lines moves either counter.  A rename reads through b/,
    the new side, so content that moves INTO the scope counts as added.
    """
    hunks: list[Hunk] = []
    current: str | None = None
    new_no = 0
    old_no = 0
    added: list[tuple[int, str]] = []
    removed: list[tuple[int, str]] = []

    def flush() -> None:
        if current is not None and (added or removed):
            hunks.append(Hunk(file=current, added=tuple(added), removed=tuple(removed)))

    for raw in diff.split("\n"):
        if raw.startswith("diff --git "):
            flush()
            added, removed = [], []
            match = DIFF_FILE_RE.match(raw)
            current = match.group(2) if match else None
            new_no = old_no = 0
            continue
        if current is None:
            continue
        hunk = HUNK_RE.match(raw)
        if hunk:
            flush()
            added, removed = [], []
            new_no = int(hunk.group(2))
            old_no = int(hunk.group(1))
            continue
        if raw.startswith(("+++", "---", "\\")):
            continue
        if raw.startswith("+"):
            added.append((new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            removed.append((old_no, raw[1:]))
            old_no += 1
    flush()
    return hunks


def diff_hunks(root: Path, base_ref: str, scope: Sequence[str]) -> list[Hunk]:
    """Diff hunks between `base_ref` and HEAD, restricted to `scope`.

    `base_ref` == "HEAD" means "the working tree against HEAD", the default: the
    revision becomes the single `HEAD`, which git reads as tree-vs-worktree.  Any
    other ref becomes the range `<ref>..HEAD`.  Without that special case
    `HEAD..HEAD` is a valid but always-empty range, which would silently report
    "nothing to check" when there is uncommitted work.
    """
    revision = "HEAD" if base_ref == "HEAD" else f"{base_ref}..HEAD"
    args = ["diff", "-U0", "--no-color", revision, "--", *scope_globs(scope)]
    return parse_diff(_git_text(root, args))


def extract_added_lines(
    root: Path, base_ref: str, scope: Sequence[str]
) -> dict[str, list[AddedLine]]:
    """`base_ref..HEAD` over `scope` pathspecs, keyed per file.

    Files with no added lines are absent from the result.  `base_ref` == "HEAD"
    means the working tree against HEAD (see `diff_hunks`).
    """
    commit = head_sha(root)
    by_file: dict[str, list[AddedLine]] = {}
    for hunk in diff_hunks(root, base_ref, scope):
        for no, text in hunk.added:
            by_file.setdefault(hunk.file, []).append(
                AddedLine(file=hunk.file, line=no, text=text, commit=commit)
            )
    for rows in by_file.values():
        rows.sort(key=lambda row: row.line)
    return {file: rows for file, rows in by_file.items() if rows}


def normalize_link_targets(text: str) -> str:
    """Drop markdown link targets, keeping link text and everything else."""

    def keep(match: re.Match[str]) -> str:
        if match.group(1) == "!":  # image: nothing textual to keep
            return ""
        if match.group(2) is not None:  # inline: [text](target)
            return match.group(2)
        return match.group(3) or ""  # reference: [text][ref]

    return MD_LINK_RE.sub(keep, text)


def is_link_only_change(removed: Sequence[str], added: Sequence[str]) -> bool:
    """True when both sides read identically once link targets are dropped.

    The comparison is per line and order-sensitive, so a reordered paragraph is
    not a link-only change.  Two empty sides are not a change at all → False.
    """
    if not removed or not added:
        return False
    if len(removed) != len(added):
        return False
    return all(
        normalize_link_targets(old) == normalize_link_targets(new)
        for old, new in zip(removed, added)
    )


def quote_line_ranges(root: Path, file: str) -> list[tuple[int, int]]:
    """Inclusive line ranges of `/// quote` blocks in `file`, markers included.

    The state machine reads the FILE, not the diff: quote content that predates the
    diff still shields the lines inside it, and `-U0` cannot see the marker that
    opened a block.  `/// note`, `/// abstract`, `/// caption`, `/// situation` are
    not collected.  A closing marker with nothing open is ignored, and since no
    nesting exists in this corpus, a further opening marker inside an open block is
    ignored too — the next bare `///` closes it.
    """
    path = root / file
    if not path.is_file():
        raise FileNotFoundError(f"no such file for quote ranges: {file}")

    ranges: list[tuple[int, int]] = []
    open_at: int | None = None
    open_is_quote = False

    for no, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        marker = BLOCK_MARKER_RE.match(raw)
        if not marker:
            continue
        kind = marker_kind(marker.group(1))
        if open_at is None:
            if kind:  # only a named marker opens a block
                open_at, open_is_quote = no, kind == QUOTE_KIND
            continue
        if not kind:  # bare `///` (or `/// | подпись`) closes the open block
            if open_is_quote:
                ranges.append((open_at, no))
            open_at, open_is_quote = None, False
    return ranges


def marker_kind(remainder: str) -> str:
    """The kind word of a block marker's remainder; "" when it has none."""
    match = MARKER_KIND_RE.match(remainder.strip())
    return match.group(1).lower() if match else ""


def is_structural(text: str) -> bool:
    """True for lines that carry no prose to proofread."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped == FRONTMATTER_FENCE:  # frontmatter fence
        return True
    if REF_DEFINITION_RE.match(stripped):  # [ref]: target
        return True
    if _is_block_delimiter(stripped):  # `///`, `/// | подпись`
        return True
    if IMAGE_LINE_RE.match(stripped):  # a line that is nothing but an image
        return True
    # A line with no word in it is a rule, a bullet, a lone gutter or an emoticon
    # (`-----`, `> `, `— `, `**`).  A smiley (`:-)`) falls in here too, and that is
    # right: there is nothing to proofread in it.
    return not WORD_CHAR_RE.search(stripped)


def _is_block_delimiter(stripped: str) -> bool:
    """A block delimiter line: `///`, or `///` followed only by an attribute."""
    match = BLOCK_MARKER_RE.match(stripped)
    return bool(match) and not marker_kind(match.group(1))


def filter_hunks(
    hunks: Sequence[Hunk], quote_ranges: Sequence[tuple[int, int]] = ()
) -> tuple[list[AddedLine], Counter]:
    """Drop quote blocks, link-only swaps and structural lines out of hunks.

    Returns `(kept, dropped)`; `dropped` counts lines per reason, so a report can
    always say what was thrown away and why — a filter that swallows everything has
    to look different from a corpus that genuinely has nothing new.

    Pairing is positional INSIDE each hunk (`removed[i]` against `added[i]`): the
    only pairing that survives a reworded paragraph, where old and new numbering no
    longer agree.  Reason order is quote → link_only → structural, because text
    inside a quote block is somebody else's words and should not be described by a
    cheaper reason.
    """
    kept: list[AddedLine] = []
    dropped: Counter = Counter()
    ranges = list(quote_ranges)

    for hunk in hunks:
        removed_texts = hunk.removed_texts
        for index, (no, text) in enumerate(hunk.added):
            reason: str | None = None
            if in_ranges(no, ranges):
                reason = REASON_QUOTE
            elif index < len(removed_texts) and is_link_only_change(
                [removed_texts[index]], [text]
            ):
                reason = REASON_LINK_ONLY
            elif is_structural(text):
                reason = REASON_STRUCTURAL
            if reason:
                dropped[reason] += 1
            else:
                kept.append(AddedLine(file=hunk.file, line=no, text=text, commit=""))
    return kept, dropped


def filter_noise(
    added: Sequence[AddedLine],
    removed_by_hunk: Sequence[str] = (),
    quote_ranges: Sequence[tuple[int, int]] = (),
) -> tuple[list[AddedLine], Counter]:
    """`filter_hunks` over a flat list of added lines (one file per call).

    `removed_by_hunk` holds the removed lines to pair against `added` by position;
    `quote_ranges` are that file's `/// quote` ranges.
    """
    if not added:
        return [], Counter()
    hunk = Hunk(
        file=added[0].file,
        added=tuple((row.line, row.text) for row in added),
        removed=tuple((0, text) for text in removed_by_hunk),
    )
    kept, dropped = filter_hunks([hunk], quote_ranges)
    commit = added[0].commit
    # the flat shape must hand back the caller's rows, commit included
    return [
        AddedLine(file=row.file, line=row.line, text=row.text, commit=commit)
        for row in kept
    ], dropped


def in_ranges(line: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def typography_issues(added: Sequence[AddedLine]) -> list[Issue]:
    """Mechanical typography findings, each keeping its file and line.

    Ported from scan_typography.py: double space inside a phrase, space before
    punctuation, cyrillic/latin homoglyph words.  A trailing run of spaces is the
    markdown hard break, so it gets its own kind instead of being counted as an
    error, and such a line is not also flagged as a double-space one.
    """
    issues: list[Issue] = []
    for row in added:
        if not row.text.strip():
            continue
        issues.extend(_line_spacing_issues(row))
        issues.extend(_line_homoglyphs(row))
    return issues


def _line_spacing_issues(row: AddedLine) -> list[Issue]:
    found: list[Issue] = []
    if DOUBLE_SPACE_RE.search(row.text):
        found.append(Issue(row.file, row.line, KIND_DOUBLE_SPACE, _clip(row.text)))
    elif TRAILING_DOUBLE_SPACE_RE.search(row.text):
        found.append(
            Issue(row.file, row.line, KIND_TRAILING_DOUBLE_SPACE, _clip(row.text, True))
        )
    if SPACE_BEFORE_PUNCT_RE.search(row.text):
        found.append(
            Issue(row.file, row.line, KIND_SPACE_BEFORE_PUNCT, _clip(row.text, True))
        )
    return found


def _line_homoglyphs(row: AddedLine) -> list[Issue]:
    found: list[Issue] = []
    # Drop link targets before tokenizing: `[Cмерти](p1-010-…md#x)` is prose in
    # the link text, and the old `](` skip-marker lost exactly that case.
    prose = LINK_TARGET_RE.sub("]", row.text)
    for token in prose.split():
        core = WORD_TRIM_RE.sub("", token)
        if _is_homoglyph(token, core):
            found.append(Issue(row.file, row.line, KIND_HOMOGLYPH, core))
    return found


def _is_homoglyph(token: str, core: str) -> bool:
    """A word mixing cyrillic and latin: one of the two is a look-alike typo."""
    if len(core) < MIN_HOMOGLYPH_WORD:
        return False
    lowered = token.lower()
    if any(marker in lowered for marker in SKIP_TOKEN_MARKERS):
        return False
    if "#" in core:  # an anchor is not a word
        return False
    return bool(CYR_RE.search(core) and LAT_RE.search(core))


def _clip(text: str, from_tail: bool = False, width: int = 90) -> str:
    body = text.strip()
    return (body[-width:] if from_tail else body[:width]).strip()


def _payload(
    base: str,
    head: str,
    scope: str,
    kept_by_file: dict[str, list[AddedLine]],
    dropped: Counter,
    with_typography: bool,
) -> dict[str, Any]:
    """Assemble the payload from kept rows and drop counters."""
    kept_rows = [row for rows in kept_by_file.values() for row in rows]
    issues = typography_issues(kept_rows) if with_typography else []
    # heavy imports normalize_link_targets from this module, so the import
    # goes through a cycle — take it lazily, after the module is complete
    from text_forge.heavy import find_heavy

    heavy = find_heavy(kept_rows)
    return {
        "base": base,
        "head": head,
        "scope": scope,
        "files": {
            file: [{"line": row.line, "text": row.text} for row in rows]
            for file, rows in sorted(kept_by_file.items())
            if rows
        },
        "dropped": {reason: int(dropped.get(reason, 0)) for reason in DROP_REASONS},
        "typography": [
            {"file": i.file, "line": i.line, "kind": i.kind, "fragment": i.fragment}
            for i in _sorted_issues(issues)
        ],
        "heavy": [
            {
                "file": h.file,
                "line": h.line,
                "text": h.text,
                "commas": h.commas,
                "words": h.words,
            }
            for h in heavy
        ],
    }


def build_payload(
    root: Path,
    base_ref: str,
    scope_name: str = "wtd",
    with_typography: bool = False,
) -> dict[str, Any]:
    """The grammar-input payload: kept lines per file, drop counts, typography.

    `scope_name` picks a scope from SCOPES.  Quote ranges are read per file from
    the working tree — the same tree the `+` side of the diff came from, so the
    numbers line up.
    """
    scope = SCOPES[scope_name]
    head = head_sha(root)
    hunks = diff_hunks(root, base_ref, scope)
    kept_by_file: dict[str, list[AddedLine]] = {}
    dropped: Counter = Counter()

    for file in _hunk_files(hunks):
        file_hunks = [hunk for hunk in hunks if hunk.file == file]
        ranges = quote_line_ranges(root, file) if (root / file).is_file() else []
        kept, file_dropped = filter_hunks(file_hunks, ranges)
        dropped.update(file_dropped)
        kept_by_file[file] = [
            AddedLine(file=file, line=row.line, text=row.text, commit=head)
            for row in kept
        ]

    return _payload(base_ref, head, scope_name, kept_by_file, dropped, with_typography)


def build_file_payload(
    root: Path, file: str, with_typography: bool = False
) -> dict[str, Any]:
    """The same payload for ONE file read whole, not from a diff.

    Every line counts as added, so a chapter that has not been touched in years
    can still be proofread: the diff mode only ever sees what changed.  Quote
    blocks and structural lines are dropped the same way, and `link_only` stays
    at zero because there is nothing to pair against.
    """
    path = root / file
    if not path.is_file():
        raise FileNotFoundError(f"no such file to proofread: {file}")
    head = head_sha(root)
    texts = path.read_text(encoding="utf-8").split("\n")
    added = tuple((no, text) for no, text in enumerate(texts, start=1))
    hunk = Hunk(file=file, added=added, removed=())
    kept, dropped = filter_hunks([hunk], quote_line_ranges(root, file))
    kept_by_file = {file: [AddedLine(file, row.line, row.text, head) for row in kept]}
    return _payload(
        f"whole file {file}", head, "file", kept_by_file, dropped, with_typography
    )


def _hunk_files(hunks: Sequence[Hunk]) -> list[str]:
    """Files of hunks that add something, in first-appearance order."""
    files: list[str] = []
    for hunk in hunks:
        if hunk.added and hunk.file not in files:
            files.append(hunk.file)
    return files


def render_markdown(
    added: dict[str, list[AddedLine]],
    typography: Sequence[Issue],
    meta: dict[str, Any],
) -> str:
    """The proofreading input as markdown: header, lines per file, typography.

    Rows read `file:line | text`, so a finding can be handed back as an address.
    `meta` carries base/head/scope plus the drop counters.
    """
    total = sum(len(rows) for rows in added.values())
    lines: list[str] = ["# Grammar input", ""]
    lines.append(f"- base-ref: `{meta.get('base', '')}`")
    if meta.get("head"):
        lines.append(f"- head: `{meta['head']}`")
    lines.append(f"- scope: {meta.get('scope', '')}")
    lines.append(f"- files: {len(added)}")
    lines.append(f"- lines to check: {total}")
    lines.append(f"- dropped: {_render_dropped(meta.get('dropped') or {})}")
    lines.append("")

    for file in sorted(added):
        rows = added[file]
        lines.append(f"## {file} ({len(rows)})")
        lines.append("")
        for row in rows:
            lines.append(f"{row.file}:{row.line} | {row.text.strip()}")
        lines.append("")

    from text_forge.heavy import find_heavy

    heavy = find_heavy([row for rows in added.values() for row in rows])
    lines.append(
        f"## Heavy sentences ({len(heavy)}) — split candidates, counted not judged"
    )
    lines.append("")
    if not heavy:
        lines.extend(["_No candidates._", ""])
    else:
        for h in heavy:
            lines.append(
                f"{h.file}:{h.line} | commas {h.commas} · words {h.words} | {h.text}"
            )
        lines.append("")
    lines.append(f"## Typography ({len(typography)})")
    lines.append("")
    if not typography:
        lines.extend(["_No findings._", ""])
    else:
        lines.append("| file:line | kind | fragment |")
        lines.append("| --- | --- | --- |")
        for issue in _sorted_issues(typography):
            fragment = issue.fragment.replace("|", "\\|")
            lines.append(f"| {issue.file}:{issue.line} | {issue.kind} | {fragment} |")
        lines.append("")
    return "\n".join(lines)


def _render_dropped(dropped: dict[str, Any]) -> str:
    """Drop counters in a fixed order, zeros included — silence must be visible."""
    parts = [f"{reason}={int(dropped.get(reason, 0))}" for reason in DROP_REASONS]
    extra = sorted(str(key) for key in dropped if str(key) not in DROP_REASONS)
    parts += [f"{key}={int(dropped[key])}" for key in extra]
    return ", ".join(parts)


def _sorted_issues(issues: Sequence[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (i.file, i.line, i.kind, i.fragment))
