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
from pathlib import Path
from typing import Any

from hindsight_common import ensure_no_proxy, request_json

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


def section_matches(section: dict[str, Any], section_filter: str | None) -> bool:
    if not section_filter:
        return True
    wanted = section_filter.removeprefix("#")
    return wanted in {
        str(section.get("section_uid", "")),
        str(section.get("anchor", "")),
    }


def iter_documents(
    inv: dict[str, Any],
    chapter_filter: str | None,
    section_filter: str | None,
    chunk_size: int,
):
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


def document_id(
    chapter: dict[str, Any], section: dict[str, Any], chunk_idx: int
) -> str:
    return (
        f"wtd-current-{doc_chapter(chapter)}-{section['section_uid']}-{chunk_idx:03d}"
    )


def metadata(
    inv: dict[str, Any],
    chapter: dict[str, Any],
    section: dict[str, Any],
    chunk_idx: int,
    chunk_count: int,
) -> dict[str, str]:
    section_changed = str(section.get("changed") or "")
    chapter_changed = str(chapter.get("changed") or "")
    data: dict[str, str] = {
        "corpus": str(inv.get("corpus", "wtd")),
        "role": "roots",
        "status": str(chapter["status"]),
        "chapter": str(chapter["chapter"]),
        "chapter_created": str(chapter.get("created") or ""),
        "chapter_published": str(chapter.get("published") or ""),
        "section_changed": section_changed,
        "chapter_changed": chapter_changed,
        "heading_level": str(section["heading_level"]),
        "heading": str(section["heading"]),
        "section_uid": str(section["section_uid"]),
        "url": str(section.get("url") or chapter.get("url") or ""),
        "github_url": str(section.get("github_url") or ""),
        "chunk_index": str(chunk_idx),
        "chunk_count": str(chunk_count),
        "text_author": "User",
    }
    if inv.get("commit"):
        data["commit"] = str(inv["commit"])
    changed_at = section_changed or chapter_changed or str(inv.get("commit_date") or "")
    if changed_at:
        data["changed_at"] = changed_at
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
    chapter_title = str(chapter.get("title") or chapter.get("chapter") or "")
    chapter_slug = str(chapter.get("chapter") or "")
    section_heading = str(section.get("heading") or "")
    section_uid = str(section.get("section_uid") or "")
    chapter_label = (
        "Published"
        if str(chapter.get("status") or "").lower() == "published"
        else "Draft"
    )
    return (
        "WTD roots corpus source text is authored by User.\n"
        "Assistant/Hermes role is reader and reflector of this text, not the source author.\n"
        f"{chapter_label} chapter: «{chapter_title}», {chapter_slug}\n"
        f"Section: «{section_heading}», {section_uid}\n"
        f"URL: {url}"
    )


def build_item(
    *,
    content: str,
    context_text: str,
    document_id_value: str,
    metadata_value: dict[str, str],
    tags_value: list[str],
    strategy: str | None,
    observation_scopes: str | None,
    update_mode: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "content": content,
        "context": context_text,
        "document_id": document_id_value,
        "metadata": metadata_value,
        "tags": tags_value,
        "timestamp": "unset",
        "update_mode": update_mode,
    }
    if strategy:
        item["strategy"] = strategy
    if observation_scopes:
        item["observation_scopes"] = observation_scopes
    return item


def retain_batch(
    api_url: str,
    bank: str,
    items: list[dict[str, Any]],
    timeout: int,
    retain_async: bool,
) -> None:
    request_json(
        api_url,
        "POST",
        f"/v1/default/banks/{bank}/memories",
        {"items": items, "async": retain_async},
        timeout=timeout,
    )


def is_retryable(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            socket.timeout,
            TimeoutError,
            ConnectionResetError,
            http.client.RemoteDisconnected,
            urllib.error.URLError,
        ),
    )


def retain_with_retry(*, retries: int, retry_delay: float, **kwargs) -> None:
    for attempt in range(1, retries + 2):
        try:
            retain_batch(**kwargs)
            return
        except Exception as e:
            if not is_retryable(e) or attempt == retries + 1:
                raise
            wait = retry_delay * (2 ** (attempt - 1))
            print(
                f"RETRYABLE ERROR ({type(e).__name__}: {e}); retry {attempt}/{retries} after {wait:.0f}s...",
                flush=True,
            )
            time.sleep(wait)


def validate_documents(
    inv: dict[str, Any],
    chapter_filter: str | None,
    section_filter: str | None,
    chunk_size: int,
) -> list[str]:
    errors: list[str] = []
    seen_doc: set[str] = set()
    for chapter, section, chunk_idx, _chunk_count, _chunk in iter_documents(
        inv, chapter_filter, section_filter, chunk_size
    ):
        did = document_id(chapter, section, chunk_idx)
        if did in seen_doc:
            errors.append(f"duplicate document_id: {did}")
        seen_doc.add(did)
    return errors


def preview(
    inv: dict[str, Any],
    chapter_filter: str | None,
    section_filter: str | None,
    chunk_size: int,
    limit: int | None,
) -> None:
    docs = list(iter_documents(inv, chapter_filter, section_filter, chunk_size))
    shown = docs if limit is None else docs[:limit]
    total_chars = 0
    for chapter, section, chunk_idx, chunk_count, chunk in shown:
        total_chars += len(chunk)
        doc_meta = metadata(inv, chapter, section, chunk_idx, chunk_count)
        print(
            f"- {chapter['chapter']}#{section['section_uid']} ({chapter['status']}) chunk {chunk_idx + 1}/{chunk_count}: {len(chunk):,} chars"
        )
        print(f"  heading: {section['heading']}")
        print(f"  document_id: {document_id(chapter, section, chunk_idx)}")
        print(f"  url: {doc_meta.get('url') or '-'}")
        print(f"  chapter_created: {doc_meta.get('chapter_created') or '-'}")
        print(f"  chapter_published: {doc_meta.get('chapter_published') or '-'}")
        print(
            f"  changed_at: {doc_meta.get('changed_at') or doc_meta.get('chapter_changed') or '-'}"
        )
        print(f"  text_author: {doc_meta.get('text_author') or '-'}")
        print(f"  tags: {', '.join(tags(chapter, section))}")
    print(f"\nTOTAL selected preview: {len(shown)} chunks, {total_chars:,} chars")


def ingest(
    inv: dict[str, Any],
    selected: list[tuple[dict[str, Any], dict[str, Any], int, int, str]],
    args: argparse.Namespace,
) -> int:
    if not selected:
        return 0
    sent = 0
    total_batches = (len(selected) + args.batch_size - 1) // args.batch_size
    for batch_index in range(total_batches):
        start = batch_index * args.batch_size
        end = min(len(selected), start + args.batch_size)
        batch_docs = selected[start:end]
        items: list[dict[str, Any]] = []
        for chapter, section, chunk_idx, chunk_count, chunk in batch_docs:
            did = document_id(chapter, section, chunk_idx)
            items.append(
                build_item(
                    content=chunk,
                    context_text=context(chapter, section),
                    document_id_value=did,
                    metadata_value=metadata(
                        inv, chapter, section, chunk_idx, chunk_count
                    ),
                    tags_value=tags(chapter, section),
                    strategy=args.strategy,
                    observation_scopes=args.observation_scopes,
                    update_mode=args.update_mode,
                )
            )

        print(
            f"\n[batch {batch_index + 1}/{total_batches}] retain {len(items)} items "
            f"(chunks {start + 1}-{end}/{len(selected)})...",
            end=" ",
            flush=True,
        )
        retain_with_retry(
            api_url=args.api_url,
            bank=args.bank,
            items=items,
            timeout=args.retain_timeout,
            retain_async=args.retain_async,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
        sent += len(items)
        print("OK")
        time.sleep(args.delay)
    return sent


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, write_through=True)

    parser = argparse.ArgumentParser(
        description="Ingest text-forge inventory JSON into Hindsight"
    )
    parser.add_argument(
        "--inventory", default="-", help="Inventory JSON path, or '-' for stdin"
    )
    parser.add_argument(
        "--api-url", required=True, help="Hindsight API URL, e.g. http://localhost:8889"
    )
    parser.add_argument("--bank", required=True, help="Hindsight bank id")
    parser.add_argument(
        "--strategy", default=None, help="Named Hindsight retain strategy"
    )
    parser.add_argument(
        "--observation-scopes",
        default="combined",
        choices=["per_tag", "combined", "all_combinations"],
        help="Hindsight observation_scopes value",
    )
    parser.add_argument(
        "--chapter", help="Ingest only one chapter slug, e.g. p2-200-text"
    )
    parser.add_argument(
        "--section",
        help="Ingest only one section_uid or anchor, e.g. digital_format_freedom",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of chunks"
    )
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only; default unless --yes is passed",
    )
    parser.add_argument("--yes", action="store_true", help="Actually retain memories")
    parser.add_argument("--retain-timeout", type=int, default=600)
    parser.add_argument(
        "--retain-async",
        dest="retain_async",
        action="store_true",
        default=True,
        help="Submit retain batches asynchronously (default)",
    )
    parser.add_argument(
        "--retain-sync",
        dest="retain_async",
        action="store_false",
        help="Wait for retain processing before returning",
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument(
        "--batch-size", type=int, default=25, help="Items per retain request"
    )
    parser.add_argument(
        "--update-mode",
        choices=["replace", "append"],
        default="replace",
        help="Document update policy for existing document_id",
    )
    parser.add_argument(
        "--delta", action="store_true", help="Alias for --update-mode append"
    )
    args = parser.parse_args()

    if args.delta:
        args.update_mode = "append"

    ensure_no_proxy()

    inv = load_inventory(args.inventory)
    errors = validate_documents(inv, args.chapter, args.section, args.chunk_size)
    if errors:
        print("ERROR: inventory validation failed:", file=sys.stderr)
        for err in errors[:20]:
            print(f"  - {err}", file=sys.stderr)
        return 1

    docs = list(iter_documents(inv, args.chapter, args.section, args.chunk_size))
    selected = docs if args.limit is None else docs[: args.limit]
    published = sum(1 for ch in inv["chapters"] if ch["status"] == "published")
    draft = sum(1 for ch in inv["chapters"] if ch["status"] == "draft")
    print(f"Inventory commit: {inv.get('commit')}")
    print(f"Inventory commit_date: {inv.get('commit_date')}")
    print(
        f"Chapters: {len(inv['chapters'])} ({published} published, {draft} draft), chunks selected: {len(docs)}"
    )
    print(f"API: {args.api_url}, bank: {args.bank}")
    print(f"Retain strategy: {args.strategy or '(bank default)'}")
    print(f"Retain mode: {'async' if args.retain_async else 'sync'}")
    print(f"Update mode: {args.update_mode}")
    print(f"Batch size: {args.batch_size}")
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

    sent = ingest(inv, selected, args)
    print(f"\nchunks sent: {sent}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Downstream consumer (e.g. `head`) closed the pipe early.
        # Exit cleanly so preview commands can be safely piped.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
