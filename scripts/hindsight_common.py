#!/usr/bin/env python3
"""Shared helpers for Hindsight script operations in text-forge."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Tags every WTD roots ingestion writes; used to locate previously ingested docs.
WTD_BASE_TAGS = ("wtd", "roots", "current")


def ensure_no_proxy() -> None:
    """Avoid proxy ambiguity when targeting local/LAN Hindsight services."""
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")


def quote_path_part(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def request_json(
    api_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {path}: {detail}") from e
    if not body:
        return {}
    return json.loads(body)


def section_matches(section: dict[str, Any], section_filter: str | None) -> bool:
    """Whether a inventory section is selected by a section filter.

    Shared by `hindsight-ingest.py` (chunk selection) and the WTD ingest
    wrapper (empty-target filtering), so both agree on what a filter matches.
    A `None`/empty filter selects every section; otherwise the filter matches
    `section_uid` or `anchor`, with a leading `#` stripped.
    """
    if not section_filter:
        return True
    wanted = section_filter.removeprefix("#")
    return wanted in {
        str(section.get("section_uid", "")),
        str(section.get("anchor", "")),
    }


def latest_document(
    api_url: str,
    bank_id: str,
    tags: tuple[str, ...] = WTD_BASE_TAGS,
    page_size: int = 100,
) -> dict[str, Any] | None:
    """Return the most recently updated document carrying all given tags.

    The documents API treats repeated `tags` query params as OR, not AND,
    so results are filtered client-side to require every tag.
    """
    newest: dict[str, Any] | None = None
    offset = 0
    while True:
        query = [("limit", str(page_size)), ("offset", str(offset))]
        query.extend(("tags", tag) for tag in tags)
        page = request_json(
            api_url,
            "GET",
            f"/v1/default/banks/{bank_id}/documents?{urllib.parse.urlencode(query)}",
        )
        items = page.get("items") or []
        if not items:
            return newest
        for item in items:
            if not set(tags).issubset(set(item.get("tags") or [])):
                continue
            if newest is None or str(item.get("updated_at", "")) > str(
                newest.get("updated_at", "")
            ):
                newest = item
        offset += len(items)
        if offset >= int(page.get("total", 0)):
            return newest
