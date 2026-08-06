#!/usr/bin/env python3
"""Shared anchor-heading parsing utilities for WTD markdown scripts."""

from __future__ import annotations

import re

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*(\{[^}]*\})\s*$")
ID_ATTR_RE = re.compile(r"(?:^|\s)#([^\s}]+)")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def anchored_headings(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """Return (line_number, level, heading_text, anchor) for headings with {#id}."""
    out: list[tuple[int, int, str, str]] = []
    in_fence = False
    for idx, line in enumerate(lines, start=1):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        hashes, raw_heading, attrs = match.groups()
        id_match = ID_ATTR_RE.search(attrs.strip("{}"))
        if not id_match:
            continue
        heading = re.sub(r"\s+", " ", raw_heading).strip()
        out.append((idx, len(hashes), heading, id_match.group(1)))
    return out
