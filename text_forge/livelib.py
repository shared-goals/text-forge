"""Stable LiveLib export client — the single code path behind wtd-books
and the future livelib-mcp.

Channels verified against livelib.ru (2026-10-19, anonymous):

- beta.api.livelib.ru/trisolaris/api/users/{id}/quotes|reviews?limit&offset
  → open JSON, envelope {status, error, payload:{pagination:{next_page}, data}}
- beta.api.livelib.ru/trisolaris/api/search?query=&limit=
  → editions search (type == "art_editions")
- www.livelib.ru/users/{id}/books/{read,reading,unread,want}?page=N
  → SSR HTML; collection records (edition, title, authors, user rating 0-10)
  embedded as Next.js flight chunks (self.__next_f.push([1,"..."]))

Known limits: the want shelf ignores ?page server-side (first 20 only);
write endpoints (POST/PATCH/DELETE /users/me/collections, per
advokatb/livelib.koplugin) need session cookies and are out of scope here.

Transport is injected so tests run without network.
"""
import json
import re
import urllib.request

API_BASE = "https://beta.api.livelib.ru/trisolaris/api"
SITE_BASE = "https://www.livelib.ru"

# shelf URL slug → note status (livelib names, see wtd_books)
SHELF_STATUS = {"read": "read", "reading": "reading", "unread": "unread", "want": "wish"}
# higher wins when the same edition sits on several shelves
_STATUS_RANK = {"read": 0, "reading": 1, "unread": 2, "wish": 3}

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_RECORD = re.compile(r'\{"id":\d+,"art_edition":\{')


def default_fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_flight_collections(html: str) -> list[dict]:
    """Extract user-collection records from SSR flight chunks.

    Returns dicts with collection_id, edition_id, title, author, url,
    rating (0-10 as LiveLib stores it) and my_mark (1-5 stars, None if unrated).
    """
    stream = "".join(json.loads(m.group(1)) for m in _FLIGHT.finditer(html))
    if not stream:
        return []
    decoder = json.JSONDecoder()
    records = []
    for m in _RECORD.finditer(stream):
        try:
            rec, _ = decoder.raw_decode(stream, m.start())
        except json.JSONDecodeError:
            continue
        ae = rec.get("art_edition") or {}
        if not isinstance(ae, dict) or "id" not in ae:
            continue
        authors = ", ".join(a["full_name"] for a in ae.get("authors") or [] if a.get("full_name"))
        rating = rec.get("rating") or 0
        records.append({
            "collection_id": rec["id"],
            "edition_id": str(ae["id"]),
            "title": ae.get("title", ""),
            "author": authors,
            "url": ae.get("url") or f"/book/{ae['id']}",
            "rating": rating,
            "my_mark": round(rating / 2) if rating else None,
        })
    return records


class LivelibClient:
    """Read-only LiveLib client; `fetch` returns the response body as text."""

    def __init__(self, fetch=None):
        self.fetch = fetch or default_fetch

    # ---------------------------------------------------------- json API

    def _paged(self, path: str) -> list[dict]:
        out, offset, limit = [], 0, 50
        while True:
            envelope = json.loads(self.fetch(f"{API_BASE}/{path}?limit={limit}&offset={offset}"))
            if envelope.get("error"):
                raise RuntimeError(f"livelib api error on {path}: {envelope['error']}")
            data = envelope["payload"]["data"]
            out.extend(data)
            if not envelope["payload"]["pagination"]["next_page"] or not data:
                return out
            offset += limit

    def quotes(self, user_id: int) -> list[dict]:
        return self._paged(f"users/{user_id}/quotes")

    def reviews(self, user_id: int) -> list[dict]:
        return self._paged(f"users/{user_id}/reviews")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        from urllib.parse import quote
        envelope = json.loads(self.fetch(f"{API_BASE}/search?query={quote(query)}&limit={limit}"))
        results = []
        for item in envelope.get("payload", {}).get("data") or []:
            if item.get("type") != "art_editions":
                continue
            inst = item.get("instance") or {}
            if not inst.get("id"):
                continue
            results.append({
                "edition_id": str(inst["id"]),
                "title": inst.get("title", ""),
                "author": ", ".join(a["full_name"] for a in inst.get("authors") or [] if a.get("full_name")),
                "livelib_url": "https://beta.livelib.ru" + (inst.get("url") or f"/book/{inst['id']}"),
            })
        return results

    def resolve_edition(self, edition_id: str, extra_queries=()) -> dict:
        """{title, author} of one edition id, or {} when livelib has no such edition.

        The search API returns no more than ~20 editions per query and ignores
        `limit` beyond that, so an id cannot be looked up directly. Every query
        tried is the caller's to supply (the edition slug, the title, ...); the
        match itself is exact — of all the hits, only the one carrying this id is
        taken, so a returned title is that edition's own, never a neighbour's.

        Returns {} rather than raising: an unresolved id is a curation problem the
        caller reports and works around (slug-derived title), not a transport one.

        Transport failures are swallowed on purpose and reported as 'unresolved':
        the caller reaches this only for an id the export does not carry, so there
        is nothing else to lose — and a build must not die because livelib is
        unreachable or has no such edition. `resolve_edition_cached` records the
        miss, so a retry does not repeat the network round.
        """
        for q in extra_queries:
            if not str(q).strip():
                continue
            try:
                found = self._search_hit(edition_id, q)
            except Exception:  # noqa: BLE001, S112 - see above: miss, not a crash
                continue
            if found:
                return found
        return {}

    def _search_hit(self, edition_id: str, query: str) -> dict:
        from urllib.parse import quote
        for item in (json.loads(self.fetch(
                f"{API_BASE}/search?query={quote(query)}&limit=20"))
                .get("payload", {}).get("data") or []):
            if item.get("type") != "art_editions":
                continue
            inst = item.get("instance") or {}
            if str(inst.get("id", "")) != str(edition_id):
                continue
            return {
                "title": inst.get("title", ""),
                "author": ", ".join(a["full_name"] for a in inst.get("authors") or []
                                   if a.get("full_name")),
            }
        return {}

    # -------------------------------------------------------------- SSR

    def shelf(self, user_id: int, shelf: str) -> list[dict]:
        """One shelf; walks ?page=N until a page adds no new editions."""
        status = SHELF_STATUS[shelf]
        base = f"{SITE_BASE}/users/{user_id}/books/{shelf}"
        seen: dict[str, dict] = {}
        page = 1
        while True:
            records = parse_flight_collections(self.fetch(f"{base}?page={page}"))
            fresh = [r for r in records if r["edition_id"] not in seen]
            for r in fresh:
                r["status"] = status
                seen[r["edition_id"]] = r
            if not fresh:
                return list(seen.values())
            page += 1

    def books(self, user_id: int, shelves=("read", "reading", "unread", "want")) -> list[dict]:
        """Union of shelves → wtd_books input schema (livelib-books.json)."""
        merged: dict[str, dict] = {}
        for shelf in shelves:
            for r in self.shelf(user_id, shelf):
                cur = merged.get(r["edition_id"])
                if cur is None or _STATUS_RANK[r["status"]] < _STATUS_RANK[cur["status"]]:
                    merged[r["edition_id"]] = cur = dict(r)
                if cur.get("my_mark") is None and r["my_mark"] is not None:
                    cur["my_mark"] = r["my_mark"]
        return [{
            "book_url": f"https://www.livelib.ru/book/{b['edition_id']}",
            "title": b["title"],
            "author": b["author"],
            "status": b["status"],
            "my_mark": b["my_mark"],
        } for b in merged.values()]


def export_all(user_id: int, out_dir: str, fetch=None) -> dict:
    """Full export → livelib-books.json / livelib-quotes-api.json / livelib-reviews-api.json."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    c = LivelibClient(fetch=fetch)
    files = {
        "livelib-books.json": c.books(user_id),
        "livelib-quotes-api.json": c.quotes(user_id),
        "livelib-reviews-api.json": c.reviews(user_id),
    }
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {name: len(data) for name, data in files.items()}


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        sys.exit("usage: python -m text_forge.livelib <user_id> <out_dir>")
    uid, out_dir = int(sys.argv[1]), sys.argv[2]
    print(json.dumps(export_all(uid, out_dir), ensure_ascii=False))
