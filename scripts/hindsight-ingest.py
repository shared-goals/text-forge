#!/usr/bin/env python3
"""Ingest text-forge inventory documents into Hindsight.

Reads inventory JSON from stdin or a file. Intended downstream of
`scripts/wtd-inventory.py`; it does not parse Markdown or MkDocs itself.

Example:
    python scripts/wtd-inventory.py --config mkdocs.yml --include-drafts --format json \
      | python scripts/hindsight-ingest.py --api-url http://localhost:8889 --bank hermes --strategy wtd-primary --dry-run
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CHUNK_SIZE = 8000
DEFAULT_DELAY = 0.5


def chunk_text(text: str, size: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while text:
        if len(text) <= size:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, size)
        if split_at == -1:
            split_at = text.rfind("\n", 0, size)
        if split_at == -1 or split_at < size // 2:
            split_at = size
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return [c for c in chunks if c]


def load_inventory(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def request_json(api_url: str, method: str, path: str, payload: dict | None = None, timeout: int = 120) -> dict:
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
    return json.loads(body) if body else {}


def section_matches(section: dict[str, Any], section_filter: str | None) -> bool:
    if not section_filter:
        return True
    wanted = section_filter.removeprefix("#")
    return wanted in {str(section.get("section_uid", "")), str(section.get("anchor", ""))}


def iter_documents(inv: dict[str, Any], chapter_filter: str | None, section_filter: str | None, chunk_size: int):
    wanted_chapter = chapter_filter.removesuffix(".md") if chapter_filter else None
    for chapter in inv["chapters"]:
        if wanted_chapter and chapter["chapter"] != wanted_chapter:
            continue
        for section in chapter["sections"]:
            if not section_matches(section, section_filter):
                continue
            chunks = chunk_text(section.get("text", ""), chunk_size)
            for chunk_idx, chunk in enumerate(chunks):
                yield chapter, section, chunk_idx, len(chunks), chunk


def doc_chapter(chapter: dict[str, Any]) -> str:
    return chapter["chapter"].replace("/", "-")


def document_id(chapter: dict[str, Any], section: dict[str, Any], chunk_idx: int) -> str:
    return f"wtd-current-{doc_chapter(chapter)}-{section['section_uid']}-{chunk_idx:03d}"


def metadata(inv: dict[str, Any], chapter: dict[str, Any], section: dict[str, Any], chunk_idx: int, chunk_count: int) -> dict[str, str]:
    data: dict[str, str] = {
        "corpus": str(inv.get("corpus", "wtd")),
        "role": "roots",
        "status": str(chapter["status"]),
        "chapter": str(chapter["chapter"]),
        "heading_level": str(section["heading_level"]),
        "heading": str(section["heading"]),
        "section_uid": str(section["section_uid"]),
        "url": str(section.get("url") or chapter.get("url") or ""),
        "github_url": str(section.get("github_url") or ""),
        "chunk_index": str(chunk_idx),
        "chunk_count": str(chunk_count),
    }
    if inv.get("commit"):
        data["commit"] = str(inv["commit"])
    if section.get("anchor"):
        data["anchor"] = str(section["anchor"])
    return data


def tags(chapter: dict[str, Any], section: dict[str, Any]) -> list[str]:
    out = [
        "wtd",
        "roots",
        "current",
        str(chapter["status"]),
        f"chapter:{doc_chapter(chapter)}",
        f"section:{section['section_uid']}",
    ]
    if section.get("anchor"):
        out.append(f"anchor:{section['anchor']}")
    return out


def context(chapter: dict[str, Any], section: dict[str, Any]) -> str:
    url = section.get("url") or chapter.get("url")
    return f"WTD roots corpus. {chapter['status']} chapter {chapter['chapter']}, section «{section['heading']}». URL: {url}"


def retain_item(
    api_url: str,
    bank: str,
    content: str,
    context_text: str,
    document_id_value: str,
    metadata_value: dict[str, str],
    tags_value: list[str],
    timeout: int,
    strategy: str | None,
    observation_scopes: str | None,
) -> None:
    item: dict[str, Any] = {
        "content": content,
        "context": context_text,
        "document_id": document_id_value,
        "metadata": metadata_value,
        "tags": tags_value,
        "timestamp": "unset",
        "update_mode": "replace",
    }
    if strategy:
        item["strategy"] = strategy
    if observation_scopes:
        item["observation_scopes"] = observation_scopes
    request_json(api_url, "POST", f"/v1/default/banks/{bank}/memories", {"items": [item], "async": False}, timeout=timeout)


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionResetError, http.client.RemoteDisconnected, urllib.error.URLError))


def retain_with_retry(*, retries: int, retry_delay: float, **kwargs) -> None:
    for attempt in range(1, retries + 2):
        try:
            retain_item(**kwargs)
            return
        except Exception as e:
            if not is_retryable(e) or attempt == retries + 1:
                raise
            wait = retry_delay * (2 ** (attempt - 1))
            print(f"RETRYABLE ERROR ({type(e).__name__}: {e}); retry {attempt}/{retries} after {wait:.0f}s...", flush=True)
            time.sleep(wait)


def validate_documents(inv: dict[str, Any], chapter_filter: str | None, section_filter: str | None, chunk_size: int) -> list[str]:
    errors: list[str] = []
    seen_doc: set[str] = set()
    for chapter, section, chunk_idx, _chunk_count, _chunk in iter_documents(inv, chapter_filter, section_filter, chunk_size):
        did = document_id(chapter, section, chunk_idx)
        if did in seen_doc:
            errors.append(f"duplicate document_id: {did}")
        seen_doc.add(did)
    return errors


def preview(inv: dict[str, Any], chapter_filter: str | None, section_filter: str | None, chunk_size: int, limit: int | None) -> None:
    docs = list(iter_documents(inv, chapter_filter, section_filter, chunk_size))
    shown = docs if limit is None else docs[:limit]
    total_chars = 0
    for chapter, section, chunk_idx, chunk_count, chunk in shown:
        total_chars += len(chunk)
        print(f"- {chapter['chapter']}#{section['section_uid']} ({chapter['status']}) chunk {chunk_idx + 1}/{chunk_count}: {len(chunk):,} chars")
        print(f"  heading: {section['heading']}")
        print(f"  document_id: {document_id(chapter, section, chunk_idx)}")
        print(f"  url: {section.get('url') or chapter.get('url')}")
        print(f"  tags: {', '.join(tags(chapter, section))}")
    print(f"\nTOTAL selected preview: {len(shown)} chunks, {total_chars:,} chars")


def ingest(inv: dict[str, Any], args: argparse.Namespace) -> int:
    docs = list(iter_documents(inv, args.chapter, args.section, args.chunk_size))
    selected = docs if args.limit is None else docs[: args.limit]
    sent = 0
    for idx, (chapter, section, chunk_idx, chunk_count, chunk) in enumerate(selected, start=1):
        did = document_id(chapter, section, chunk_idx)
        print(f"\n[{idx}/{len(selected)}] retain {did} ({len(chunk):,} chars)...", end=" ", flush=True)
        retain_with_retry(
            api_url=args.api_url,
            bank=args.bank,
            content=chunk,
            context_text=context(chapter, section),
            document_id_value=did,
            metadata_value=metadata(inv, chapter, section, chunk_idx, chunk_count),
            tags_value=tags(chapter, section),
            timeout=args.retain_timeout,
            strategy=args.strategy,
            observation_scopes=args.observation_scopes,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
        sent += 1
        print("OK")
        time.sleep(args.delay)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest text-forge inventory JSON into Hindsight")
    parser.add_argument("--inventory", default="-", help="Inventory JSON path, or '-' for stdin")
    parser.add_argument("--api-url", required=True, help="Hindsight API URL, e.g. http://localhost:8889")
    parser.add_argument("--bank", required=True, help="Hindsight bank id")
    parser.add_argument("--strategy", default=None, help="Named Hindsight retain strategy")
    parser.add_argument("--observation-scopes", default="combined", choices=["per_tag", "combined", "all_combinations"], help="Hindsight observation_scopes value")
    parser.add_argument("--chapter", help="Ingest only one chapter slug, e.g. p2-200-text")
    parser.add_argument("--section", help="Ingest only one section_uid or anchor, e.g. digital_format_freedom")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of chunks")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Preview only; default unless --yes is passed")
    parser.add_argument("--yes", action="store_true", help="Actually retain memories")
    parser.add_argument("--retain-timeout", type=int, default=600)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args()

    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    inv = load_inventory(args.inventory)
    errors = validate_documents(inv, args.chapter, args.section, args.chunk_size)
    if errors:
        print("ERROR: inventory validation failed:", file=sys.stderr)
        for err in errors[:20]:
            print(f"  - {err}", file=sys.stderr)
        return 1

    docs = list(iter_documents(inv, args.chapter, args.section, args.chunk_size))
    published = sum(1 for ch in inv["chapters"] if ch["status"] == "published")
    draft = sum(1 for ch in inv["chapters"] if ch["status"] == "draft")
    print(f"Inventory commit: {inv.get('commit')}")
    print(f"Chapters: {len(inv['chapters'])} ({published} published, {draft} draft), chunks selected: {len(docs)}")
    print(f"API: {args.api_url}, bank: {args.bank}")
    print(f"Retain strategy: {args.strategy or '(bank default)'}")
    if args.chapter:
        print(f"Chapter only: {args.chapter}")
    if args.section:
        print(f"Section only: {args.section}")
    if inv.get("warnings"):
        print("Inventory warnings:")
        for warning in inv["warnings"][:20]:
            print(f"  - {warning}")

    print("\nDRY-RUN PREVIEW")
    preview(inv, args.chapter, args.section, args.chunk_size, args.limit)
    if not args.yes:
        print("\nNo writes performed. Pass --yes to ingest.")
        return 0

    sent = ingest(inv, args)
    print(f"\nchunks sent: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
