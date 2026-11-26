"""Markdown video marker -> player HTML for the MkDocs site.

The Text project embeds videos as `![type:video](url "Title")` — the marker the
`mkdocs-video` plugin uses. Keeping that syntax means the markdown stays portable
(turning the plugin on later needs no source change), while text-forge renders it
itself: a plugin costs a second dependency and rewrites every page's HTML through
lxml, which is a lot of blast radius for one inline element.

Two rules that are not cosmetic:

* every attribute in the emitted HTML carries a value (`allowfullscreen="allowfullscreen"`,
  never a bare boolean attribute) — the EPUB pipeline converts the marker to a link,
  but a raw player block that reaches XHTML with a bare attribute makes the whole
  file unparseable and e-readers drop the rest of the chapter;
* `youtube-nocookie.com` is rewritten to `www.youtube.com`: the cookie-less host can
  never receive the reader's Google session, and the anonymous player is what gets
  stopped by YouTube's "sign in to confirm you're not a bot" gate on flagged IPs.

Only a marker alone on its line is replaced: an inline occurrence inside a
sentence would have to become a block-level element and break the paragraph.
"""

import html
import re
from urllib.parse import parse_qs, urlparse

MARKER = "type:video"

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
                  "youtube-nocookie.com", "www.youtube-nocookie.com"}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_EXTENSIONS = (".mp4", ".webm", ".ogv", ".ogg", ".m4v")
_IFRAME_ALLOW = ("accelerometer; autoplay; clipboard-write; encrypted-media; "
                 "gyroscope; picture-in-picture; web-share")
_IFRAME_STYLE = "width:100%;aspect-ratio:16/9;height:auto;border:0;"

MARKER_LINE = re.compile(
    r'^[ \t]*!\[type:video\]\('
    r'(?:<(?P<angle>[^>]+)>|(?P<url>[^)\s]+))'
    r'(?:\s+(?:"(?P<title_dq>[^"]*)"|\'(?P<title_sq>[^\']*)\'))?'
    r'[ \t]*\)[ \t]*$',
    re.MULTILINE,
)

LEFTOVER = re.compile(r"!\[type:video\]\(")


def unrendered_markers(markdown: str) -> list[tuple[int, str]]:
    """Markers that survived rendering: (line number, line) for each.

    A marker left in place becomes a broken image on the site, so the build warns
    instead of shipping it silently. Call it after `render_markers`.
    """
    return [
        (number, line.strip())
        for number, line in enumerate(markdown.splitlines(), 1)
        if LEFTOVER.search(line)
    ]


def _title_from(match: re.Match[str]) -> str:
    """The quoted title, if the marker carries one. Plain markdown rules apply:
    a title is delimited by straight quotes — `"…"` or `'…'` — and nothing else."""
    return (match.group("title_dq") or match.group("title_sq") or "").strip()


def youtube_id(src: str) -> str | None:
    """Video id for any of YouTube's link shapes, else None."""
    if not src:
        return None
    parsed = urlparse(src)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] in {"embed", "shorts", "v", "live"} and len(parts) > 1:
            candidate = parts[1]
        elif parsed.path.rstrip("/").endswith("/watch") or parts == ["watch"]:
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    else:
        return None
    return candidate if _VIDEO_ID.match(candidate or "") else None


def youtube_embed_url(src: str) -> str | None:
    """Canonical `https://www.youtube.com/embed/<id>` for a YouTube link."""
    video = youtube_id(src)
    return f"https://www.youtube.com/embed/{video}" if video else None


def youtube_watch_url(src: str) -> str | None:
    """Canonical `https://youtu.be/<id>` for a YouTube link."""
    video = youtube_id(src)
    return f"https://youtu.be/{video}" if video else None


def _iframe(src: str, title: str) -> str:
    return (
        f'<iframe src="{html.escape(src, quote=True)}" '
        f'title="{html.escape(title, quote=True)}" '
        f'loading="lazy" frameborder="0" allow="{_IFRAME_ALLOW}" '
        f'referrerpolicy="strict-origin-when-cross-origin" '
        f'allowfullscreen="allowfullscreen" style="{_IFRAME_STYLE}"></iframe>'
    )


def _video(src: str) -> str:
    path = src.split("?")[0].lower()
    kind = next(ext.lstrip(".") for ext in _VIDEO_EXTENSIONS if path.endswith(ext))
    if kind == "ogv":
        kind = "ogg"
    return (
        '<video controls="controls" preload="metadata" style="width:100%;">'
        f'<source src="{html.escape(src, quote=True)}" type="video/{kind}">'
        "</video>"
    )


def player_block(src: str, title: str = "") -> str:
    """Player HTML for one marker: iframe for remote video, <video> for local files."""
    embed = youtube_embed_url(src)
    if embed:
        return f'<div class="tf-video">\n{_iframe(embed, title or "Video")}\n</div>'
    if src.split("?")[0].lower().endswith(_VIDEO_EXTENSIONS):
        return f'<div class="tf-video">\n{_video(src)}\n</div>'
    return f'<div class="tf-video">\n{_iframe(src, title or "Video")}\n</div>'


def render_markers(markdown: str) -> str:
    """Replace every whole-line `![type:video](url "Title")` with player HTML.

    Text without markers comes back byte-identical, so the function is safe to run
    over every page and idempotent: rendered output never matches the marker again.
    """

    def replace(match: re.Match[str]) -> str:
        src = match.group("angle") or match.group("url")
        title = _title_from(match)
        return player_block(src, title)

    return MARKER_LINE.sub(replace, markdown)
