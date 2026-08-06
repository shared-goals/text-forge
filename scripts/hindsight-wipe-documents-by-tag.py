#!/usr/bin/env python3
"""Safely delete Hindsight documents by tag.

Use this to wipe replaceable corpora (for example whattodo experiments) without
touching unrelated session/OpenClaw memories. Dry-run by default; pass --yes to
delete.
"""

from __future__ import annotations

import argparse
import time
import urllib.parse
from typing import Any

from hindsight_common import ensure_no_proxy, quote_path_part, request_json

DEFAULT_API_URL = "http://rock.lan:8889"
DEFAULT_BANK_ID = "hermes"
DEFAULT_DELAY = 0.1


def list_documents(
    api_url: str, bank_id: str, limit: int, offset: int
) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"limit": str(limit), "offset": str(offset)})
    return request_json(
        api_url, "GET", f"/v1/default/banks/{bank_id}/documents?{qs}", timeout=120
    )


def matching_documents(
    api_url: str,
    bank_id: str,
    required_tags: set[str],
    page_size: int,
    max_docs: int | None,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = list_documents(api_url, bank_id, page_size, offset)
        items = page.get("items", [])
        if not items:
            break
        for item in items:
            tags = set(item.get("tags") or [])
            if required_tags.issubset(tags):
                docs.append(item)
                if max_docs is not None and len(docs) >= max_docs:
                    return docs
        offset += len(items)
        total = int(page.get("total", 0))
        if offset >= total:
            break
    return docs


def delete_document(api_url: str, bank_id: str, document_id: str) -> dict[str, Any]:
    quoted = quote_path_part(document_id)
    return request_json(
        api_url,
        "DELETE",
        f"/v1/default/banks/{bank_id}/documents/{quoted}",
        timeout=120,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete Hindsight documents matching all requested tags"
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Hindsight API URL")
    parser.add_argument("--bank", default=DEFAULT_BANK_ID, help="Hindsight bank id")
    parser.add_argument(
        "--tag",
        action="append",
        required=True,
        help="Required tag; repeat for AND semantics",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Actually delete matching documents"
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum matching docs to process"
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument(
        "--show", type=int, default=50, help="How many matching document IDs to print"
    )
    args = parser.parse_args()

    ensure_no_proxy()
    required_tags = set(args.tag)
    print(f"API: {args.api_url}, bank: {args.bank}")
    print(f"Required tags: {', '.join(sorted(required_tags))}")
    docs = matching_documents(
        args.api_url, args.bank, required_tags, args.page_size, args.limit
    )
    total_units = sum(int(doc.get("memory_unit_count") or 0) for doc in docs)
    print(f"Matching documents: {len(docs)}")
    print(f"Memory units in matching docs: {total_units}")
    for doc in docs[: args.show]:
        print(
            f"- {doc.get('id')} units={doc.get('memory_unit_count')} tags={','.join(doc.get('tags') or [])}"
        )
    if len(docs) > args.show:
        print(f"... {len(docs) - args.show} more")

    if not args.yes:
        print("\nNo deletes performed. Pass --yes to delete these documents.")
        return 0

    if not docs:
        print("\nNothing to delete.")
        return 0

    print("\nDeleting...")
    deleted = 0
    for doc in docs:
        doc_id = str(doc["id"])
        print(f"delete {doc_id}...", end=" ", flush=True)
        delete_document(args.api_url, args.bank, doc_id)
        deleted += 1
        print("OK")
        time.sleep(args.delay)
    print(f"\nDeleted documents: {deleted}")
    print("Run a tagged recall/list check if you need to verify no tagged docs remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
