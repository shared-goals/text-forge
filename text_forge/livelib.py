"""LiveLib pipeline adapter — the seam between the wtd-books build and livelib-mcp.

Everything about *how* to read LiveLib — endpoints, envelopes, pagination, retry,
shelf-record shaping — lives in `livelib_mcp` (the pinned git dependency). What
stays here is pipeline policy, the part that belongs to this build alone:

- the work-key heuristics (`_norm_title`, `_words`, `_tokens_by_index`,
  `pick_work_id`): deciding which work an omnibus edition is named after is a
  corpus decision, not an API fact;
- the caching contract of `work_id` (one record per edition id at `cache_path`,
  placeholder vs answer, failures never recorded);
- the error policy of the crawl: an unreachable edition is a MISS (None / {})
  and never raises, so the caller keeps its title-based grouping;
- the export-file writing (`export_all`) and the per-shelf progress line.

Callers (`wtd_books.py`, `wtd_books_build.py`) see the same `LivelibClient`
interface as before, so nothing outside this module changed.

Transport injection: pass `transport=` (a livelib_mcp transport, i.e.
`(method, url, *, json_body, headers) -> response body as a dict`) or the legacy
`fetch=` callable `(url) -> text`, which the adapter wraps. Tests use either; the
default is the package's own retrying transport.
"""
import inspect
import json
import pathlib
import re

from livelib_mcp.client import TrisolarisClient

# shelf URL slug → note status (livelib names, see wtd_books)
SHELF_STATUS = {"read": "read", "reading": "reading", "unread": "unread", "want": "wish"}
# shelf slug → livelib-mcp collection name (the package's shelf vocabulary)
SHELF_COLLECTION = {"read": "reads", "reading": "readings",
                    "unread": "unreads", "want": "wants"}
# higher wins when the same edition sits on several shelves
_STATUS_RANK = {"read": 0, "reading": 1, "unread": 2, "wish": 3}


def _is_transport(fn) -> bool:
    """Is `fn` a livelib_mcp transport — i.e. declared with (method, url) first?

    Discrimination by SIGNATURE, not by argument guessing: a transport is written
    as a def taking the method positionally, while every legacy caller is
    fetch(url). `functools.partial` and other callables with no nameable
    signature count as legacy, which is exactly what callers used them for.
    """
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    if len(params) < 2 or params[0].name != "method" or params[1].name != "url":
        return False
    return all(p.kind is p.KEYWORD_ONLY for p in params[2:])


def _as_transport(fetch):
    """A legacy fetch(url) / fetch(url, headers=...) -> text, as a transport.

    The text is parsed and the body handed back as is — NO envelope check: the
    old fetch path had none, and a wrapper must not invent error behaviour its
    callee never had. Headers are passed on when the callee can take them.
    """
    def transport(method, url, *, json_body=None, headers=None):
        try:
            body = fetch(url, headers=headers)
        except TypeError:
            # a fetch written as fetch(url) takes nothing else
            body = fetch(url)
        return body if isinstance(body, dict) else json.loads(body)
    return transport


def _counting(transport, marks):
    """Wrap a transport, counting the shelf marks its pages carry.

    Counts the same fact on either wire style — a package transport returns the
    checked body (payload contents), a legacy one the raw envelope — and passes
    the body through untouched, so nothing but the count changes.
    """
    def wrapper(method, url, *, json_body=None, headers=None):
        body = transport(method, url, json_body=json_body, headers=headers)
        if not isinstance(body, dict):
            body = json.loads(body)
        data = (body.get("payload") or {}).get("data")
        if data is None:
            data = body.get("data")
        marks[0] += len(data or [])
        return body
    return wrapper


def _id(edition_id):
    """The package takes an int-ish id; the pipeline hands around strings.

    A non-numeric id passes through unchanged, so the call just misses instead
    of raising on int(): the pipeline's miss policy wins over a type complaint.
    """
    s = str(edition_id)
    return int(s) if s.isdigit() else s


# ------------------------------------------------------ work-key heuristics

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
        Кише» from 3 → the London work wins.
      - «Морской волк. Белый Клык»: «Морской волк» from 0 → it wins.
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


class LivelibClient:
    """Read-only LiveLib client backed by livelib-mcp; `fetch`/`transport` inject
    the wire so tests run without network."""

    def __init__(self, fetch=None, *, transport=None):
        if transport is None and fetch is not None:
            transport = fetch if _is_transport(fetch) else _as_transport(fetch)
        self.client = TrisolarisClient(transport=transport)
        # legacy attribute: a call site may hold `client.fetch` and call it with
        # a bare url (wtd_books_build.progress_fetch)
        self.fetch = lambda url: self.client.transport("GET", url)

    # ---------------------------------------------------------- channels

    def quotes(self, user_id: int) -> list[dict]:
        """Every quote the user marked, as RAW API records — the build consumes
        the envelope records (quote_id, art_edition, text_json, …) as they are."""
        return self.client.get_quotes(user_id)

    def reviews(self, user_id: int) -> list[dict]:
        """Every review the user wrote, as RAW API records."""
        return self.client.get_reviews(user_id)

    # ------------------------------------------------------- edition -> work

    def _contents_stream(self, edition_id) -> list[tuple[str, str]] | None:
        """[(work title, work id)] of the edition's «Содержание», or None when
        the page could not be read.

        None is the caller's signal "no fact was learned" — write no cache
        record, try again next build; an empty list IS the fact "this edition
        lists no works". A transport failure is never raised over the build.
        """
        try:
            return self.client.get_edition_contents(_id(edition_id))
        except Exception:  # noqa: BLE001 - unreachable is a miss, not a crash
            return None

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
            cache[key] = {"work_id": pick_work_id(works, title)}
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
        An unreachable page lists nothing: the caller keeps its own grouping.
        """
        return [wid for _t, wid in (self._contents_stream(edition_id) or [])]

    def edition_meta(self, edition_id: str) -> dict:
        """{title, author} of one edition id, from the edition card.

        /art-editions/{id} answers the card for ANY edition — including one no
        shelf record carries — so it replaces the search API as the metadata
        source: no query to guess, no ~20-hit index to hope the id falls in.

        Returns {} when livelib has no such edition or the page is unreachable:
        an unresolved id is a curation problem the caller reports, not a
        transport failure to raise over.
        """
        try:
            item = self.client.get_edition(_id(edition_id))
        except Exception:  # noqa: BLE001 - unreachable is a miss, not a crash
            return {}
        if not isinstance(item, dict) or str(item.get("id", "")) != str(edition_id):
            return {}
        return {
            "title": item.get("title", ""),
            "author": ", ".join(a["full_name"] for a in item.get("authors") or []
                               if a.get("full_name")),
        }

    # -------------------------------------------------------------- shelves

    def shelf(self, user_id: int, shelf: str) -> list[dict]:
        """One shelf: deduped edition records with the note status attached.

        The package walks the collection, dedupes by edition id (livelib keeps a
        second mark when a book is re-marked read) and shapes each mark into
        collection_id/edition_id/title/author/url/rating/my_mark. This adds
        `status` — the note status the build keys on — and prints one progress
        line per shelf: a human watching `make books` should see it moving. The
        line counts RAW marks seen and deduped books, which is what makes the
        known duplicate-mark drift visible.
        """
        status = SHELF_STATUS[shelf]
        marks = [0]
        paging = TrisolarisClient(transport=_counting(self.client.transport, marks))
        records = paging.shelf_records(user_id, SHELF_COLLECTION[shelf])
        for r in records:
            r["status"] = status
        print(f"  shelf {shelf}: {marks[0]} records → {len(records)} books")
        return records

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

    @classmethod
    def export_all(cls, user_id: int, out_dir: str, fetch=None, *, transport=None) -> dict:
        """Full export → livelib-books.json / livelib-quotes-api.json / livelib-reviews-api.json."""
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        c = cls(fetch=fetch, transport=transport)
        files = {
            "livelib-books.json": c.books(user_id),
            "livelib-quotes-api.json": c.quotes(user_id),
            "livelib-reviews-api.json": c.reviews(user_id),
        }
        for name, data in files.items():
            (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return {name: len(data) for name, data in files.items()}


# module-level entry kept for callers of `livelib.export_all(uid, out_dir)`
export_all = LivelibClient.export_all


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        sys.exit("usage: python -m text_forge.livelib <user_id> <out_dir>")
    uid, out_dir = int(sys.argv[1]), sys.argv[2]
    print(json.dumps(export_all(uid, out_dir), ensure_ascii=False))
