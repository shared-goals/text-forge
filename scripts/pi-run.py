#!/usr/bin/env python3
"""pi-run — run a prepared job through pi, showing live progress.

`pi --mode json` is pi's documented event stream (JSONL on stdout, diagnostics on
stderr).  This wrapper adds nothing to that protocol: it renders the events pi
already emits, so a forty-minute proofreading run is not forty minutes of
silence — and a dead model is visible in seconds instead of in half an hour.

Usage
    pi-run.py build/grammar-job.md

Without a terminal the progress line is skipped and the answer is printed at the
end, so cron logs and `tee` files stay readable.  The exit code is pi's.

Stdlib + rich only; the prompt goes to pi as an argument, exactly as the previous
`pi -p "$(cat job)"` did.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# scripts/ has no package, so the sibling text_forge package is reached by path —
# the same trick the other wrappers in this directory use.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse
from collections.abc import Sequence

from rich.text import Text

from text_forge import console

EXIT_USAGE = 2
PI = os.environ.get("PI", "pi")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pi-run.py",
        description="Run a prepared job file through pi (--mode json) with live progress.",
    )
    parser.add_argument("job", metavar="JOB.md", help="job file: prompt + input")
    parser.add_argument(
        "--quiet", action="store_true", help="no progress line, answer only"
    )
    return parser.parse_args(argv)


def _dur(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _k(number: int) -> str:
    return f"{number / 1000:.1f}k" if number >= 1000 else str(number)


def _text_of(message: dict) -> str:
    """Assistant text from a message record: a plain string or content blocks."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(str(b.get("text", "")) for b in blocks)
    return ""


class Progress:
    """Everything the progress line shows, accumulated from pi's own events."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.phase = "starting"
        self.turns = 0
        self.tools = 0
        self.tool_name = ""
        self.tokens_in = 0
        self.tokens_out = 0
        self.answer = ""

    def feed(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "turn_end":
            self.turns += 1
        elif kind == "tool_execution_start":
            self.tools += 1
            self.tool_name = str(event.get("toolName", ""))
            self.phase = f"calling {self.tool_name}"
        elif kind == "message_update":
            self._feed_usage(event.get("usage"))
            inner: dict = event.get("assistantMessageEvent") or {}
            self.phase = {
                "thinking_delta": "thinking",
                "text_delta": "writing",
            }.get(inner.get("type"), self.phase)
        elif kind == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                text = _text_of(message)
                if text.strip():
                    self.answer = text
                self.phase = "thinking"

    def _feed_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        self.tokens_in = usage.get("input") or self.tokens_in
        self.tokens_out = usage.get("output") or self.tokens_out

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def render(self) -> Text:
        bits = [f"{self.phase} {_dur(self.elapsed)}"]
        if self.turns:
            bits.append(_n(self.turns, "turn"))
        if self.tools:
            bits.append(_n(self.tools, "tool"))
        if self.tokens_in or self.tokens_out:
            bits.append(f"{_k(self.tokens_in)} in / {_k(self.tokens_out)} out")
        return Text("  " + " · ".join(bits), style="dim")

    def summary(self) -> str:
        bits = [_dur(self.elapsed)]
        if self.turns:
            bits.append(_n(self.turns, "turn"))
        if self.tools:
            bits.append(_n(self.tools, "tool"))
        if self.tokens_in or self.tokens_out:
            bits.append(f"{_k(self.tokens_in)} in / {_k(self.tokens_out)} out")
        return " · ".join(bits)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    job = Path(args.job)
    try:
        prompt = job.read_text(encoding="utf-8")
    except OSError as exc:
        console.fail(f"cannot read job {job}: {exc}")
        return EXIT_USAGE

    console.title("pi", note=f"{console.rel(job)} · {prompt.count(chr(10))} lines")
    process = subprocess.Popen(
        [PI, "--no-approve", "--mode", "json", "-p", prompt],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    progress = Progress()
    live = None
    if sys.stderr.isatty() and not args.quiet:
        live = console.live(progress.render())
        live.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                progress.feed(json.loads(line))
            except json.JSONDecodeError:  # a diagnostic that slipped onto stdout
                continue
            if live:
                live.update(progress.render())
    except KeyboardInterrupt:
        process.terminate()
        console.warn("interrupted")
        return 130
    finally:
        if live:
            live.stop()

    code = process.wait()
    if progress.answer:
        console.content(progress.answer)
    if code != 0:
        console.fail(f"pi exited {code}")
        return code
    console.done(progress.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
