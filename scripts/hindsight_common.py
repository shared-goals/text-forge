#!/usr/bin/env python3
"""Shared helpers for Hindsight script operations in text-forge."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


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
    req = urllib.request.Request(f"{api_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {path}: {detail}") from e
    if not body:
        return {}
    return json.loads(body)