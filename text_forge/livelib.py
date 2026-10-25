"""Stable LiveLib export client — the single code path behind wtd-books
and the future livelib-mcp.

Channels verified against livelib.ru (anonymous; last sweep 2026-10-24):

- beta.api.livelib.ru/trisolaris/api/users/{id}/quotes|reviews?limit&offset
  → open JSON, envelope {status, error, payload:{pagination:{next_page}, data}}
- beta.api.livelib.ru/trisolaris/api/search?query=&limit=
  → search; types include art_editions and art_works (art_works carry the
  work id in instance.id)
- beta.api.livelib.ru/trisolaris/api/art-editions/{id}
  → edition card: title, authors, isbn, publication_year, publishers, stats,
  art_id; sub-resources: /contents (the «Содержание» works, each with its
  /work/<id>), /quotes, /reviews, /stats, /sections, /selections, /similars,
  /cycles, /views — all plain JSON. THE metadata source for an edition: it
  answers for ANY id, including one no shelf record carries
- beta.api.livelib.ru/trisolaris/api/art-works/{work_id}
  → work card; /editions lists EVERY edition of the work in one call
- beta.api.livelib.ru/trisolaris/api/arts/{art_id}/editions?limit
  → editions by art_id
- www.livelib.ru/users/{id}/books/{read,reading,unread,want}?page=N
  → SSR HTML (the ONLY channel still parsed as HTML); collection records
  (edition, title, authors, user rating 0-10) embedded as Next.js flight
  chunks (self.__next_f.push([1,"..."])). No anonymous JSON API exists for
  shelves: /users/{id}/books/*, /collections, /editions, /library, /shelf/*
  answer 404 and /users/me/collections answers 405 without cookies
  (verified 2026-10-24).

Known limits: the want shelf ignores ?page server-side (first 20 only);
write endpoints (POST/PATCH/DELETE /users/me/collections, per
advokatb/livelib.koplugin) need session cookies and are out of scope here.

Transport is injected so tests run without network.
"""
import json
import pathlib
import re
import urllib.error
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


def _norm_title(text: str) -> str:
    """Title for comparing a work title with an edition title: case, punctuation
    and edition noise (volume markers, «сборник») dropped."""
    t = re.sub(r"[^\w\s]+", " ", str(text).lower())
    t = re.sub(r"\b(?:том|kniga|chast|сборник)\b\s*\d*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _words(text: str) -> list[str]:
    return _norm_title(text).split()


def _tokens_by_index(titles: list[tuple[str, str]]) -> list[tuple[int, str, list[str]]]:
    """All word runs of the contents, indexed by where they start.

    A collection titles itself by concatenating the works it carries, so a work's
    words form ONE run inside the edition title: «Белый клык. Сказание о Кише»
    holds «Белый Клык» at 0 and «Сказание о Кише» at 3. Indexing them keeps the
    position, which is what tells the leading work from the trailing one.
    """
    out = []
    for t, wid in titles:
        words = _words(t)
        if not words:
            continue
        for k in range(len(words)):
            out.append((k, wid, words[k:]))
    return out


def pick_work_id(titles: list[tuple[str, str]], title: str = "") -> str | None:
    """Choose the work an edition carries, from its contents list.

    A collection names itself after the work it OPENS with, so a work's words
    appear as one contiguous run inside the edition title, and the work whose run
    starts earliest wins. Ties (two contents with the same opening) go to the
    longer match, then to the page order that livelib itself uses.

      - «Белый клык. Сказание о Кише»: «Белый Клык» runs from 0, «Сказание о
        Кише» from 3 → theLondon work wins.
      - «Морской волк. Белый Клык»: «Морской волк" from 0 → it wins.
      - Nothing matches any run: livelib's own choice, the first listed work.
    A match must be contiguous, so a title that only shares scattered words does
    not claim the edition.
    """
    if not titles:
        return None
    want = _words(title)
    if want:
        best = None
        for k, wid, run in _tokens_by_index(titles):
            if len(run) > len(want) - k:
                continue
            if want[k:k + len(run)] != run:
                continue
            cand = (k, -len(run), wid)
            if best is None or cand < best:
                best = cand
        if best is not None:
            return best[2]
    return titles[0][1]


def default_fetch(url: str, timeout: int = 30) -> str:
    """GET with a small retry on transient livelib errors (5xx / 429):
    the SSR shelves and edition pages answer 500 a few times a day — a build
    should survive that instead of dying mid-export. Fatal (4xx except 429)
    raises at once."""
    import time as _time
    last: Exception = RuntimeError("unreached")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            last = e
            _time.sleep(2 * (attempt + 1))
    raise last


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

    def _contents_stream(self, edition_id: str) -> list[tuple[str, str]]:
        """[(work title, work id)] of the edition's «Содержание», via the
        trisolaris JSON API — /art-editions/{id}/contents (live-verified
        2026-10-24). Empty when unreachable: a transport failure is a miss,
        never raised, so the caller keeps its title-based grouping. The
        failure is NOT cached, so a later build gets another chance."""
        try:
            body = self.fetch(f"{API_BASE}/art-editions/{edition_id}/contents")
        except Exception:  # noqa: BLE001 - unreachable is a miss, not a crash
            return None
        data = json.loads(body).get("payload", {}).get("data") or []
        out = []
        for item in data:
            # a contents entry without a url carries no work relation
            if not isinstance(item, dict):
                continue
            m = re.search(r"/work/(\d+)", item.get("url") or "")
            if m and item.get("title"):
                out.append((item["title"], m.group(1)))
        return out

    def _work_id_from_contents(self, stream: list[tuple[str, str]], title: str = "") -> str | None:
        """The work id of the contents entry named after the edition."""
        return pick_work_id(stream, title)

    def work_id(self, edition_id: str, *, title: str = "", cache_path=None) -> str | None:
        """The livelib work id an edition belongs to (None when unknowable).

        LiveLib states the relation itself, on the edition page's «Содержание»
        list: one entry per work the edition contains, each carrying /work/<id>.
        Resolving it at crawl time makes works merge themselves, so no curated
        merge table is needed for editions livelib already links.

        The cache at `cache_path` holds one record per edition, keyed by edition
        id. A cached answer is read as: NO record — the page was never read
        (fetch it); record WITHOUT a `work_id` field — a placeholder written by
        another builder (resolve_edition), still to fetch; record WITH `work_id`
        — the answer, and None in it is a genuine miss ("this edition lists no
        works"), recorded so a rebuild stays offline. A page that could not be
        fetched at all writes nothing, so the next build tries it again rather
        than pinning a temporary failure.
        """
        cache = {}
        if cache_path and pathlib.Path(cache_path).exists():
            cache = json.loads(pathlib.Path(cache_path).read_text(encoding="utf-8"))
        key = str(edition_id)
        if key not in cache or "work_id" not in (cache[key] or {}):
            works = self._contents_stream(key)
            if works is None:             # livelib unreachable: nothing to record
                return None
            cache[key] = {"work_id": self._pick_work_id(works, title)}
            if cache_path:
                pathlib.Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(cache_path).write_text(
                    json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True),
                    encoding="utf-8")
        return cache[key].get("work_id")

    def contents(self, edition_id: str) -> list[str]:
        """EVERY work id the edition's «Содержание» lists, in page order.

        A collection edition states several works, and livelib offers no fact
        that says which one the edition is "about" beyond the title it chose.
        So the whole list is available to the caller: `work_id` still names the
        one called after the edition (the canonical), while grouping treats
        these as the works whose quotes legitimately land in this edition's
        note — «Собачье сердце. Записки юного врача» carries both.
        """
        return [wid for _t, wid in self._contents_stream(edition_id)]

    def _pick_work_id(self, works: list[tuple[str, str]], title: str = "") -> str | None:
        """The one work an edition stands for (see `work_id`)."""
        return pick_work_id(works, title)

    def edition_meta(self, edition_id: str) -> dict:
        """{title, author} of one edition id, from the edition card JSON.

        /art-editions/{id} answers the card for ANY edition — including one no
        shelf record carries — so it replaces the search API as the metadata
        source: no query to guess, no ~20-hit index to hope the id falls in.

        Returns {} when livelib has no such edition or the page is unreachable:
        an unresolved id is a curation problem the caller reports, not a
        transport failure to raise over.
        """
        try:
            item = json.loads(self.fetch(f"{API_BASE}/art-editions/{edition_id}")
                             ).get("payload", {}).get("data") or {}
        except Exception:  # noqa: BLE001 - unreachable is a miss, not a crash
            return {}
        if not isinstance(item, dict) or str(item.get("id", "")) != str(edition_id):
            return {}
        return {
            "title": item.get("title", ""),
            "author": ", ".join(a["full_name"] for a in item.get("authors") or []
                               if a.get("full_name")),
        }

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
