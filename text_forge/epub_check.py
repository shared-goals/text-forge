"""EPUB XHTML validation.

EPUB content documents are XHTML, i.e. XML: every attribute must carry a value and
every tag must be closed. Pandoc passes raw HTML through verbatim, so a bare
boolean attribute (`<iframe ... allowfullscreen>`) produces a file that is valid
HTML5 and invalid XHTML. E-readers parse the whole file up front, fail, and render
only what came before the error — the rest of the chapter silently disappears.

That failure is invisible at build time, which is how a broken book once shipped.
`validate_epub` runs after pandoc and turns the silent breakage into a failed build
with the file, position and offending line in the message.
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

EXCERPT_WIDTH = 160


class EpubValidationError(ValueError):
    """EPUB XHTML is not well-formed.

    Subclasses ValueError so the CLI's existing error handling reports it as
    `✗ Failed: ...` with exit code 1 instead of a traceback.
    """


def _excerpt(data: bytes, line: int, column: int = 0) -> str:
    text = data.decode("utf-8", "replace").splitlines()
    if not 1 <= line <= len(text):
        return ""
    raw = text[line - 1].strip()
    if len(raw) <= EXCERPT_WIDTH:
        return raw
    # keep the offending column visible: centre a window on it
    start = max(0, column - EXCERPT_WIDTH // 2)
    return raw[start:start + EXCERPT_WIDTH]


def validate_epub(path: Path) -> None:
    """Raise EpubValidationError on the first malformed content document."""
    with zipfile.ZipFile(path) as epub:
        for name in epub.namelist():
            if not name.endswith(".xhtml"):
                continue
            data = epub.read(name)
            try:
                ET.fromstring(data)
            except ET.ParseError as error:
                line, column = getattr(error, "position", (0, 0))
                reason = getattr(error, "msg", str(error))
                message = (
                    f"EPUB XHTML is not well-formed: {name}:{line}:{column} — {reason}"
                    f"\n  {_excerpt(data, line, column)}"
                )
                raise EpubValidationError(message) from error
