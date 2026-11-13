"""books_changed — which book notes a range touched, and which shelf they moved to.

A changelog post wants «Автор — Название, полка», not the diff of a book page:
those pages carry quotes, reviews and generated frontmatter, so line-level diffs
are noise.  The signal is the shelf — `status` — because the notes are rewritten
by `make books`, and what a human actually changes is where a book sits and how
it is rated.

So this module answers one question per note: was it added, modified or removed
between `base_ref` and HEAD, and what shelf does it claim now.

Only two git facts are needed:

    git diff --name-status -M base..HEAD -- ':(glob)text/books/**/*.md'
    git show base:path            (for a removed note — it is gone from disk)

The `:(glob)` prefix is not decoration, and neither is the second `*`: git's
default pathspec matches `*` against a full path, so `text/books/*.md` silently
matches nothing at all.  With `:(glob)`, one `*` stops at `/` and `**` crosses it
— `**/*.md` therefore covers both the flat notes a content repo keeps and any
subdirectory it grows later.

Stdlib + PyYAML only.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from text_forge.wtd_books import SHELF_NAMES
from text_forge.wtd_links import split_frontmatter

# `**/*.md`: notes at any depth under text/books, including depth 1.
BOOKS_PATHSPEC = ":(glob)text/books/**/*.md"
NO_SHELF_HEADING = "Без полки"

ADDED = "added"
MODIFIED = "modified"
REMOVED = "removed"
CHANGE_RANK = {ADDED: 0, MODIFIED: 1, REMOVED: 2}
CHANGE_LETTERS = {"A": ADDED, "M": MODIFIED, "D": REMOVED}
KIND_WORDS = {ADDED: "добавлено", MODIFIED: "изменено", REMOVED: "удалено"}

# Slugs named by the 'без автора' part of the summary line, before the ellipsis.
HEADLESS_SHOWN = 6

SHELF_ORDER = list(SHELF_NAMES.values())


class GitError(RuntimeError):
    """A git invocation failed; the message carries stderr."""


def _git(root: Path, args: Sequence[str]) -> str:
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


def is_git_repo(root: Path) -> bool:
    """True when `root` sits inside a work tree."""
    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def resolve_ref(root: Path, ref: str) -> str | None:
    """Resolve `ref` to a commit sha, or None when it names no commit.

    `rev-list -n 1 <ref>` with stderr captured, so a bogus ref returns None
    instead of leaking git usage text into the console.
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


@dataclass(frozen=True)
class BookChange:
    """One book note the range touched, with the shelf it now claims."""

    path: str
    slug: str
    change: str
    title: str
    author: str
    status: str
    shelf: str


def _text(value: Any) -> str:
    """Frontmatter value as a display string; anything odd becomes ''.

    A note is hand-edited as often as generated, so `author:` may hold a list, a
    number or nothing at all.  A changelog line shows text or shows nothing, and
    neither case is worth an exception.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _frontmatter_fields(text: str) -> tuple[str, str, str]:
    """(title, author, status) from a note's frontmatter; '' when unreadable."""
    fm, _ = split_frontmatter(text)
    if not fm.strip():
        return "", "", ""
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError:
        return "", "", ""
    if not isinstance(data, dict):
        return "", "", ""
    return (
        _text(data.get("title")),
        _text(data.get("author")),
        _text(data.get("status")).lower(),
    )


def _read_version(root: Path, ref: str, path: str) -> str:
    """The note as `ref` held it; '' when the blob is missing or unreadable."""
    try:
        return _git(root, ["show", f"{ref}:{path}"])
    except GitError:
        return ""


def _disk_version(root: Path, path: str) -> str:
    """The note as it sits in the work tree; '' when it is not there."""
    try:
        return (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_name_status(out: str) -> list[tuple[str, str, str]]:
    """[(change, path, content_path)] from `git diff --name-status -M` output.

    git writes the status as a bare letter ('A') or with a rename score ('R100'),
    and the letter is the whole story here.  A rename/insert-modify pair is one
    book moving slug, so it reports as two records:

        ('added',   new_path, new_path)  the note that exists now
        ('removed',  old_path, old_path) the slug that no longer does

    `content_path` is the path whose frontmatter the record reports, and for these
    two kinds it is the path that survives — `content_path` is always read with
    the ref that still holds it (HEAD for a record on disk, base for one that is
    gone), so both sides of a rename read the same live note.
    """
    rows: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        kind = fields[0][0]
        if kind in ("R", "C") and len(fields) >= 3:
            # git's field order is old then new; the new path is the second one.
            old, new = fields[1], fields[2]
            rows.append((ADDED, new, new))
            rows.append((REMOVED, old, old))
        elif len(fields) >= 2 and kind in CHANGE_LETTERS:
            path = fields[1]
            rows.append((CHANGE_LETTERS[kind], path, path))
    return rows


def changed_paths(
    root: Path, base_ref: str, head_ref: str = "HEAD"
) -> list[tuple[str, str, str]]:
    """[(change, path, content_path)] for `base_ref..head_ref`.

    Plain range semantics, no rescue: `base..head` means 'what head added on top
    of base', so a range with no commits in it reports nothing.  Probing `head^`
    or the empty tree to fill in a silent range would report notes as changed when
    the range says they are not.
    """
    return parse_name_status(_git(root, _diff_args(base_ref, head_ref)))


def _diff_args(left: str, right: str) -> list[str]:
    return ["diff", "--name-status", "-M", f"{left}..{right}", "--", BOOKS_PATHSPEC]


def _sort_key(change: BookChange) -> tuple[int, int, str, str]:
    """added → modified → removed, then shelf, title, slug.

    Shelves rank by their position in SHELF_NAMES, so the list reads in the order
    a reader expects (Читаю, Хочу прочитать, Прочтённые, Недочитанные) instead of
    alphabetically; records with no shelf go last.
    """
    shelf_rank = (
        SHELF_ORDER.index(change.shelf)
        if change.shelf in SHELF_ORDER
        else len(SHELF_ORDER)
    )
    return (CHANGE_RANK[change.change], shelf_rank, change.title, change.slug)


def _collect(root: Path, base_ref: str, head_ref: str = "HEAD") -> list[BookChange]:
    """One BookChange per changed note, in report order.

    Which version is read depends on the change: a removed note only ever existed
    in the base, everything else comes from disk — so uncommitted edits are
    visible when `base_ref` is HEAD.
    """
    changes: list[BookChange] = []
    for change, path, content_path in changed_paths(root, base_ref, head_ref):
        text = (
            _read_version(root, base_ref, content_path)
            if change == REMOVED
            else _disk_version(root, content_path)
        )
        title, author, status = _frontmatter_fields(text)
        changes.append(
            BookChange(
                path=path,
                slug=Path(path).stem,
                change=change,
                title=title,
                author=author,
                status=status,
                shelf=SHELF_NAMES.get(status, ""),
            )
        )
    changes.sort(key=_sort_key)
    return changes


def changed_books(root: Path, base_ref: str) -> list[BookChange]:
    """Book notes changed between `base_ref` and HEAD, in report order."""
    return _collect(root, base_ref)


def _line(change: BookChange) -> str:
    """`- Автор — [Название](books/slug.md)`, struck through when removed."""
    link = f"[{change.title or change.slug}]({change.path})"
    if change.change == REMOVED:
        link = f"~~{link}~~"
    return f"- {change.author} — {link}" if change.author else f"- — {link}"


def _numeral(count: int, one: str, few: str, many: str) -> str:
    """Russian plural: 1 книга, 2 книги, 5 книг, 11 книг."""
    if count % 100 in range(11, 20):
        return many
    last = count % 10
    if last == 1:
        return one
    if last in range(2, 5):
        return few
    return many


BOOK_NUMERAL = partial(_numeral, one="книга", few="книги", many="книг")


def _headless_note(changes: list[BookChange]) -> str:
    """`без автора — slug1, slug2… (+6)` for notes whose frontmatter has no author.

    A missing author is the one defect a post cannot write around, so it is named
    up front. Only the first HEADLESS_SHOWN slugs are listed: a big range should
    not bury its count under a wall of slugs.
    """
    slugs = [c.slug for c in changes if not c.author]
    if not slugs:
        return ""
    shown = ", ".join(slugs[:HEADLESS_SHOWN])
    rest = f"… (+{len(slugs) - HEADLESS_SHOWN})" if len(slugs) > HEADLESS_SHOWN else ""
    return f"без автора — {shown}{rest}"


def _summary(changes: list[BookChange], base_ref: str) -> str:
    """`С a1b2c3d: 12 книг: 7 добавлено · 4 изменено · 1 убрана · без автора — x`.

    The per-kind counts are what a changelog post opens with. Each part appears
    only when it says something: a range that only modified notes says
    «изменено» without repeating the total, and a corpus whose notes all carry
    authors says nothing about authors.
    """
    kinds = [
        (name, sum(1 for c in changes if c.change == name)) for name in CHANGE_RANK
    ]
    kinds = [(name, n) for name, n in kinds if n]
    parts = []
    if len(kinds) > 1:
        parts.append(" · ".join(f"{n} {KIND_WORDS[name]}" for name, n in kinds))
    elif kinds:
        parts.append(KIND_WORDS[kinds[0][0]])
    headless = _headless_note(changes)
    if headless:
        parts.append(headless)
    head = f"С {base_ref[:7]}: {len(changes)} {BOOK_NUMERAL(len(changes))}"
    return f"{head}: {' · '.join(parts)}" if parts else head


def render_books_markdown(changes: list[BookChange], base_ref: str = "HEAD") -> str:
    """A summary line plus `### <полка> — N книг` sections.

    Returns '' (and says so on stderr) when nothing changed. Groups appear in
    SHELF_NAMES order with «Без полки» last, and lines inside a group keep the
    order `changed_books` produced.
    """
    if not changes:
        print("No book changes to render.", file=sys.stderr)
        return ""
    blocks = [_summary(changes, base_ref)]
    for shelf in SHELF_ORDER + [NO_SHELF_HEADING]:
        group = [c for c in changes if (c.shelf or NO_SHELF_HEADING) == shelf]
        if group:
            n = f"{len(group)} {BOOK_NUMERAL(len(group))}"
            blocks.append(f"### {shelf} — {n}\n\n" + "\n".join(_line(c) for c in group))
    return "\n\n".join(blocks) + "\n"
