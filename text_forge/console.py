"""console — the one place text-forge talks to a human.

Human output goes to stderr so stdout stays free for artifacts and pipes; rich
degrades to plain text by itself when stderr is not a terminal, so cron and CI
need no separate branch.

Keep this module formatting-only.  A helper earns its place here when at least
two scripts print the same shape; anything else is a `console.print` in place.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

# A pipe has no width: wrapping a path mid-name makes the line useless in a log.
console = Console(stderr=True, highlight=False, soft_wrap=not sys.stderr.isatty())


def live(renderable: RenderableType, *, transient: bool = True) -> Live:
    """A Live bound to this console — for a progress line while a model runs."""
    return Live(renderable, console=console, refresh_per_second=4, transient=transient)


def rel(path: Path | str) -> str:
    """Path relative to the working directory when possible — shorter, copyable."""
    try:
        return os.path.relpath(path)
    except ValueError:  # different drive (Windows)
        return str(path)


def title(text: str, note: str | None = None) -> None:
    """Headline: what is happening, with a short qualifier after the dot."""
    tail = f" [dim]·[/dim] [cyan]{note}[/cyan]" if note else ""
    console.print(f"[bold]›[/bold] {text}{tail}")


def detail(label: str, value: str) -> None:
    """`label    value` — labels aligned, so numbers scan vertically."""
    console.print(f"  [dim]{label:<12}[/dim]{value}")


def counts(label: str, pairs: Sequence[tuple[str, object]]) -> None:
    """`label    a 1 · b 0`.

    Zeros are printed on purpose: silence has to be distinguishable from a
    filter that quietly stopped working.
    """
    body = " [dim]·[/dim] ".join(f"{name} {value}" for name, value in pairs)
    detail(label, body or "none")


def done(text: str) -> None:
    console.print(f"[green]✓[/green] {text}")


def warn(text: str) -> None:
    console.print(f"[yellow]![/yellow] {text}")


def fail(text: str) -> None:
    console.print(f"[red]✗[/red] {text}")


def content(text: str) -> None:
    """A model answer or file text: brackets are text here, not rich markup."""
    console.print(Text(text))
