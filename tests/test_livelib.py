"""Tests for the LiveLib adapter (text_forge.livelib) — pipeline logic only.

Since the migration, ALL API detail lives in livelib-mcp: paging, the envelope
check, retry, and shelf-record shaping. This module delegates to it, so tests
inject a livelib_mcp transport (or the legacy fetch(url)->text callable, which
the adapter wraps). Nothing here touches the network.
"""
import json

import pytest

from text_forge.livelib import SHELF_STATUS, LivelibClient

BASE = "https://beta.api.livelib.ru/trisolaris/api"


# ---------------------------------------------------------------- fixtures

def collection(cid, eid, title, author="Лев Толстой", rating=0):
    return {
        "id": cid,
        "art_edition": {
            "id": eid,
            "title": title,
            "authors": [{"id": 1, "full_name": author}],
            "url": f"/book/{eid}",
        },
        "rating": rating,
        "notes": "",
        "read_date": {"year": 2026, "month": 10, "day": 19},
    }


def api_page(data, next_offset=None):
    pag = {"next_page": f"/api/x?offset={next_offset}"} if next_offset is not None else {"next_page": None}
    return {"status": 200, "error": None,
            "payload": {"pagination": pag, "data": data}}


def route(pages):
    """A transport over {path-substring: body-or-list-of-bodies}.

    A list is consumed one element per call to that route; a scalar answers every
    call. Returns (transport, urls_seen).
    """
    seen = []
    used = {}

    def t(method, url, *, json_body=None, headers=None):
        seen.append(url)
        for frag, body in pages.items():
            if frag in url:
                if isinstance(body, list):
                    i = used.get(frag, 0)
                    used[frag] = i + 1
                    if i >= len(body):
                        raise AssertionError(f"route {frag} exhausted at {url}")
                    return body[i]
                return body
        raise AssertionError(f"unexpected url: {url}")
    return t, seen


def legacy(pages):
    """A legacy fetch(url)->text over {path-substring: body-or-list-of-bodies}.

    Returns (fetch, urls_seen). Used by the tests that inject the old-style
    callable, and by the parity harness when driving the pre-migration client.
    """
    seen = []
    used = {}

    def fetch(url):
        seen.append(url)
        for frag, body in pages.items():
            if frag in url:
                if isinstance(body, list):
                    i = used.get(frag, 0)
                    used[frag] = i + 1
                    if i >= len(body):
                        raise AssertionError(f"route {frag} exhausted at {url}")
                    return body[i]
                return body
        raise AssertionError(f"unexpected url: {url}")
    return fetch, seen


def work_item(wid, title):
    return {"id": 200000 + int(wid) % 100000, "title": title,
            "url": f"/work/{wid}-{title.lower()}", "type": "повесть"}


def contents_response(items):
    return {"status": 200, "error": None, "payload": {"data": items}}


def card(eid, title, authors=("Автор",)):
    return {"status": 200, "error": None, "payload": {"data": {
        "id": int(eid), "title": title, "url": f"/book/{eid}-slug",
        "authors": [{"id": 1, "full_name": a} for a in authors]}}}


# ------------------------------------------------------------ shelves

def test_shelf_walks_api_pages():
    t, seen = route({"/arts/reads": [api_page([collection(1, 100, "А"),
                                             collection(2, 200, "Б")], next_offset=2),
                                    api_page([collection(3, 300, "В")])]})
    recs = LivelibClient(transport=t).shelf(345497, "read")
    assert {r["edition_id"] for r in recs} == {"100", "200", "300"}
    assert all(r["status"] == "read" for r in recs)
    assert "/users/345497/arts/reads" in seen[0]


def test_shelf_maps_slug_to_api_collection():
    """/arts/{reads,readings,unreads,wants} — the trisolaris collection names."""
    for shelf, plural in (("read", "reads"), ("reading", "readings"),
                         ("unread", "unreads"), ("want", "wants")):
        t, seen = route({f"/arts/{plural}": api_page([])})
        LivelibClient(transport=t).shelf(345497, shelf)
        assert f"/arts/{plural}" in seen[0], shelf


def test_shelf_dedupes_double_read_records():
    """Livelib keeps a second record when a book is re-marked read: one book, one entry."""
    t, _ = route({"/arts/reads": api_page([collection(1, 100, "А"), collection(2, 100, "А")])})
    recs = LivelibClient(transport=t).shelf(345497, "read")
    assert len(recs) == 1 and recs[0]["edition_id"] == "100"


def test_shelf_want_uses_wish_status():
    t, _ = route({"/arts/wants": api_page([collection(1, 100, "А")])})
    recs = LivelibClient(transport=t).shelf(345497, "want")
    assert len(recs) == 1 and recs[0]["status"] == "wish"


def test_shelf_record_schema_is_the_export_entry_plus_status():
    """Field-for-field: collection_id, edition_id, title, author, url, rating,
    my_mark, status — the schema wtd_books consumes."""
    t, _ = route({"/arts/reads": api_page([collection(7, 100, "Зона", rating=8)])})
    got = LivelibClient(transport=t).shelf(345497, "read")[0]
    assert got == {"collection_id": 7, "edition_id": "100", "title": "Зона",
                   "author": "Лев Толстой", "url": "/book/100", "rating": 8,
                   "my_mark": 4, "status": "read"}


def test_shelf_marks_my_mark_as_rounded_rating():
    t, _ = route({"/arts/reads": api_page([collection(1, 100, "А", rating=8),
                                          collection(2, 200, "Б", rating=0),
                                          collection(3, 300, "В", rating=7)])})
    marks = {r["edition_id"]: r["my_mark"] for r in LivelibClient(transport=t).shelf(345497, "read")}
    assert marks == {"100": 4, "200": None, "300": 4}     # round(7/2) == 4 (banker's)


def test_shelf_skips_a_mark_without_an_edition_id():
    t, _ = route({"/arts/reads": api_page([{"id": 1, "art_edition": {}},
                                          collection(2, 200, "Б")])})
    recs = LivelibClient(transport=t).shelf(345497, "read")
    assert [r["edition_id"] for r in recs] == ["200"]


def test_shelf_prints_one_progress_line(capsys):
    t, _ = route({"/arts/reads": api_page([collection(1, 100, "А"), collection(2, 100, "А")])})
    LivelibClient(transport=t).shelf(345497, "read")
    assert capsys.readouterr().out == "  shelf read: 2 records → 1 books\n"


def test_books_merges_shelves_with_status_priority():
    t, _ = route({
        "/arts/reads": api_page([collection(1, 100, "Зона", rating=8)]),
        "/arts/unreads": api_page([collection(9, 100, "Зона", rating=8),
                                  collection(2, 200, "Идиот")]),
        "/arts/": api_page([]),
    })
    books = LivelibClient(transport=t).books(345497)
    by_id = {b["book_url"].rsplit("/", 1)[-1]: b for b in books}
    assert by_id["100"]["status"] == "read"       # read wins over unread
    assert by_id["100"]["my_mark"] == 4
    assert by_id["200"]["status"] == "unread"
    assert by_id["200"]["book_url"] == "https://www.livelib.ru/book/200"


def test_books_keeps_a_mark_from_the_losing_shelf():
    """The read record carries no rating; the unread one does — the mark survives."""
    t, _ = route({
        "/arts/reads": api_page([collection(1, 100, "Зона", rating=0)]),
        "/arts/unreads": api_page([collection(2, 100, "Зона", rating=6)]),
        "/arts/": api_page([]),
    })
    books = LivelibClient(transport=t).books(345497)
    assert len(books) == 1 and books[0]["my_mark"] == 3


# ------------------------------------------------------- quotes / reviews

def test_quotes_paginates_until_next_page_is_none():
    pages = [api_page([{"id": 1}], 50), api_page([{"id": 2}], 100), api_page([], None)]
    t, seen = route({"/quotes": pages})
    quotes = LivelibClient(transport=t).quotes(345497)
    assert [q["id"] for q in quotes] == [1, 2]
    assert all("/quotes?" in u for u in seen)


def test_quotes_return_raw_records():
    """The build consumes the raw API envelope records — no shaping here."""
    raw = {"id": 5, "text": "фраза", "quote": {"quote_id": 101556},
           "art_edition": {"id": 100, "url": "/book/100", "title": "Зона"},
           "extra_key": {"nested": 1}}
    t, _ = route({"/quotes": api_page([raw])})
    got = LivelibClient(transport=t).quotes(345497)
    assert got == [raw]


def test_reviews_uses_reviews_endpoint():
    t, seen = route({"/reviews": api_page([{"id": 7}], None)})
    assert LivelibClient(transport=t).reviews(345497)[0]["id"] == 7
    assert "/users/345497/reviews?" in seen[0]


def test_error_envelope_raises():
    """An error envelope on the WIRE (an httpx response) raises LivelibApiError:
    that check belongs to the package and the adapter does not swallow it."""
    import httpx
    from livelib_mcp.client import LivelibApiError

    def responder(request):
        return httpx.Response(500, json={"status": 500, "error": {"type": "ServerError",
                                                                 "detail": "boom"}})

    client = LivelibClient(transport=_httpx_transport(responder))
    with pytest.raises(LivelibApiError):
        client.quotes(345497)


def test_legacy_injected_fetch_answers_the_envelope_as_the_build_does():
    """A fetch that hands back a non-2xx envelope keeps the old behaviour: the
    body is returned and KeyError/empty data is the caller's to absorb — the
    legacy injected path is exactly as tolerant as it always was."""
    fetch, _ = legacy({"/quotes": json.dumps({"status": 500,
                                             "error": {"type": "ServerError",
                                                     "detail": "boom"}})})
    with pytest.raises(KeyError):
        LivelibClient(fetch=fetch).quotes(345497)


def _httpx_transport(responder):
    """A real livelib_mcp transport: an httpx MockTransport behind the wire."""
    import httpx
    mock = httpx.MockTransport(responder)

    def transport(method, url, *, json_body=None, headers=None):
        with httpx.Client(transport=mock) as c:
            r = c.request(method, url, json=json_body, headers=headers)
        return livelib_check(r)
    return transport


def livelib_check(response):
    """The package's own response check (the one its default transport uses)."""
    from livelib_mcp.client import _check
    return _check(response)


# ------------------------------------------------- edition -> work (Содержание)

def test_work_id_reads_the_contents_payload():
    body = contents_response([work_item("1000956774", "Сказание о Кише"),
                             work_item("1000880978", "Белый Клык")])
    t, seen = route({"/contents": body})
    got = LivelibClient(transport=t).work_id("1001477191", title="Белый клык. Сказание о Кише")
    assert got == "1000880978"
    assert seen == [f"{BASE}/art-editions/1001477191/contents"]


def test_work_id_single_work_edition_returns_that_work():
    t, _ = route({"/contents": contents_response([work_item("1002397147", "Ленин. Пантократор солнечных пылинок")])})
    assert LivelibClient(transport=t).work_id("1003248852") == "1002397147"


def test_work_id_prefers_the_entry_matching_the_edition_title():
    """An omnibus lists several works; the work the edition is named after wins."""
    t, _ = route({"/contents": contents_response([work_item("1000956774", "Сказание о Кише"),
                                                 work_item("1000880978", "Белый клык")])})
    c = LivelibClient(transport=t)
    assert c.work_id("1001477191", title="Белый клык. Сказание о Кише") == "1000880978"


def test_contents_lists_every_work_id_in_page_order():
    t, _ = route({"/contents": contents_response([work_item("11", "Первое"),
                                                 work_item("22", "Второе"),
                                                 {"id": 3, "title": "Без work url",
                                                  "url": "/book/3"}])})
    assert LivelibClient(transport=t).contents("100") == ["11", "22"]


def test_contents_is_empty_when_no_item_names_a_work():
    t, _ = route({"/contents": contents_response([{"id": 3, "title": "Х", "url": ""}])})
    assert LivelibClient(transport=t).contents("100") == []


def test_work_id_is_none_for_an_edition_without_a_work_list(tmp_path):
    t, _ = route({"/contents": contents_response([])})
    assert LivelibClient(transport=t).work_id(
        "1000000001", cache_path=tmp_path / "works-cache.json") is None


def test_work_id_caches_under_the_cache_path(tmp_path):
    cache = tmp_path / "works-cache.json"
    calls = []

    def t(method, url, *, json_body=None, headers=None):
        calls.append(url)
        return contents_response([work_item("1002397147", "Ленин")])

    c = LivelibClient(transport=t)
    assert c.work_id("1003248852", cache_path=cache) == "1002397147"
    assert json.loads(cache.read_text(encoding="utf-8"))["1003248852"]["work_id"] == "1002397147"
    # a second call is served from the cache: no transport, same answer
    quiet = LivelibClient(transport=lambda *a, **k: pytest.fail("network on cache hit"))
    assert quiet.work_id("1003248852", cache_path=cache) == "1002397147"


def test_work_id_cache_is_sorted_json(tmp_path):
    """The dump stays byte-stable: indent 1, sort_keys, ensure_ascii=False."""
    cache = tmp_path / "works-cache.json"
    t, _ = route({"/contents": contents_response([work_item("77", "Я")])})
    LivelibClient(transport=t).work_id("1003248852", cache_path=cache)
    raw = cache.read_text(encoding="utf-8")
    assert raw == json.dumps({"1003248852": {"work_id": "77"}},
                            ensure_ascii=False, indent=1, sort_keys=True)


def test_work_id_caches_a_miss_so_a_rebuild_stays_offline(tmp_path):
    cache = tmp_path / "works-cache.json"
    calls = []

    def t(method, url, *, json_body=None, headers=None):
        calls.append(url)
        return contents_response([])

    c = LivelibClient(transport=t)
    assert c.work_id("1000000001", cache_path=cache) is None
    assert json.loads(cache.read_text(encoding="utf-8"))["1000000001"]["work_id"] is None
    assert len(calls) == 1
    quiet = LivelibClient(transport=lambda *a, **k: pytest.fail("network on cache hit"))
    assert quiet.work_id("1000000001", cache_path=cache) is None
    assert len(calls) == 1


def test_work_id_placeholder_from_another_builder_is_no_answer(tmp_path):
    """A record written by the editions builder (title/author, no work_id field)
    must not stop the fetch."""
    cache = tmp_path / "works-cache.json"
    cache.write_text(json.dumps({"100": {"title": "Запись другого строителя",
                                        "author": "Кто-то"}}), encoding="utf-8")
    t, seen = route({"/contents": contents_response([work_item("77", "Я")])})
    assert LivelibClient(transport=t).work_id("100", cache_path=cache) == "77"
    assert len(seen) == 1


def test_work_id_reports_none_when_the_page_is_unreachable(tmp_path):
    """A transport failure is a miss, not a crash — and is not cached, so the
    next build may reach livelib again."""
    cache = tmp_path / "works-cache.json"

    def boom(method, url, *, json_body=None, headers=None):
        raise RuntimeError("403 Forbidden")

    assert LivelibClient(transport=boom).work_id("1001477191", cache_path=cache) is None
    assert not cache.exists() or json.loads(cache.read_text(encoding="utf-8")) == {}


def test_contents_is_empty_when_the_page_is_unreachable():
    def boom(method, url, *, json_body=None, headers=None):
        raise RuntimeError("timeout")

    assert LivelibClient(transport=boom).contents("100") == []


# ----------------------------------------------------------- edition card

def test_edition_meta_reads_the_edition_card():
    """/art-editions/{id} answers the CARD for one edition: a bare object, not a
    list — and it answers for any id, shelf record or not."""
    t, seen = route({"/art-editions/100": card("100", "Зона",
                                              ("Сергей Довлатов", "Третий Ли"))})
    assert LivelibClient(transport=t).edition_meta("100") == {
        "title": "Зона", "author": "Сергей Довлатов, Третий Ли"}
    assert seen == [f"{BASE}/art-editions/100"]


def test_edition_meta_of_another_id_is_a_miss():
    """A card naming a different id is not an answer for ours — livelib answers
    a redirect-ish body, and a wrong title would silently corrupt the note."""
    t, _ = route({"/art-editions/": card("101", "Чужая", ())})
    assert LivelibClient(transport=t).edition_meta("100") == {}


def test_edition_meta_of_an_empty_card_is_a_miss():
    for body in ({"payload": {"data": {}}}, {"payload": {}}, {}):
        t, _ = route({"/art-editions/": body})
        assert LivelibClient(transport=t).edition_meta("100") == {}


def test_edition_meta_swallows_a_transport_error():
    def boom(method, url, *, json_body=None, headers=None):
        raise RuntimeError("403 Forbidden")

    assert LivelibClient(transport=boom).edition_meta("100") == {}


# --------------------------------------------------- injected legacy fetch

def test_legacy_fetch_callable_still_drives_the_client():
    """Callers (wtd_books, tests) hand in fetch(url)->text; the adapter wraps it."""
    pages = {"/arts/reads": api_page([collection(1, 100, "Зона", rating=8)]),
             "/arts/": api_page([]),
             "/quotes": api_page([{"id": 1}]),
             "/reviews": api_page([])}
    fetch, seen = legacy(pages)
    c = LivelibClient(fetch=fetch)
    books = c.books(345497, shelves=("read",))
    assert books[0]["title"] == "Зона" and books[0]["my_mark"] == 4
    assert c.quotes(345497) == [{"id": 1}]
    assert all(u.startswith(BASE) for u in seen)


def test_legacy_fetch_accepts_the_headers_keyword():
    """A fetch written as fetch(url, headers=...) is served the headers the
    client has — anonymous means None, so nothing new leaks into the call."""
    got = []

    def fetch(url, headers=None):
        got.append(headers)
        return json.dumps(api_page([{"id": 1}]))

    assert LivelibClient(fetch=fetch).quotes(1) == [{"id": 1}]
    assert got and all(h is None for h in got)


def test_legacy_fetch_receives_a_plain_url_and_no_extra_args():
    seen = []

    def fetch(url):            # exactly one argument, the way old tests wrote it
        seen.append(url)
        return json.dumps(contents_response([work_item("77", "Я")]))

    assert LivelibClient(fetch=fetch).work_id("100") == "77"
    assert seen == [f"{BASE}/art-editions/100/contents"]


def test_legacy_fetch_receives_the_text_and_headers():
    """The wrapper hands the injected fetch the url and the caller headers, so a
    fetch that inspected them keeps working."""
    got = {}

    def fetch(url, headers=None):
        got["headers"] = headers
        got["url"] = url
        return json.dumps(card("100", "Зона"))

    assert LivelibClient(fetch=fetch).edition_meta("100")["title"] == "Зона"
    assert got["headers"] is None            # anonymous: no Cookie header at all
    assert got["url"] == f"{BASE}/art-editions/100"


def test_fetch_and_transport_together_prefer_transport():
    t, seen = route({"/art-editions/100": card("100", "Через транспорт")})
    c = LivelibClient(fetch=lambda url, **k: pytest.fail("fetch used"), transport=t)
    assert c.edition_meta("100")["title"] == "Через транспорт"
    assert len(seen) == 1


# --------------------------------------------------------------- export_all

def test_export_all_writes_the_three_files(tmp_path):
    pages = {"/arts/reads": api_page([collection(1, 100, "Зона", rating=8)]),
             "/arts/": api_page([]),
             "/quotes": api_page([{"id": 1}, {"id": 2}]),
             "/reviews": api_page([{"id": 7}])}
    t, _ = route(pages)
    counts = LivelibClient.export_all(345497, str(tmp_path), transport=t)
    assert counts == {"livelib-books.json": 1, "livelib-quotes-api.json": 2,
                     "livelib-reviews-api.json": 1}
    books = json.loads((tmp_path / "livelib-books.json").read_text(encoding="utf-8"))
    assert books == [{"book_url": "https://www.livelib.ru/book/100", "title": "Зона",
                     "author": "Лев Толстой", "status": "read", "my_mark": 4}]
    assert json.loads((tmp_path / "livelib-quotes-api.json").read_text(encoding="utf-8")) == \
        [{"id": 1}, {"id": 2}]


def test_export_all_file_text_is_indent_one_no_ascii_escape(tmp_path):
    pages = {"/arts/reads": api_page([collection(1, 100, "Зона")]),
             "/arts/": api_page([]), "/quotes": api_page([]), "/reviews": api_page([])}
    t, _ = route(pages)
    LivelibClient.export_all(345497, str(tmp_path), transport=t)
    raw = (tmp_path / "livelib-books.json").read_text(encoding="utf-8")
    assert raw == json.dumps([{"book_url": "https://www.livelib.ru/book/100",
                               "title": "Зона", "author": "Лев Толстой",
                               "status": "read", "my_mark": None}],
                             ensure_ascii=False, indent=1)


def test_export_all_legacy_fetch_still_works(tmp_path):
    pages = {"/arts/reads": api_page([collection(1, 100, "Зона", rating=8)]),
             "/arts/": api_page([]), "/quotes": api_page([{"id": 1}]),
             "/reviews": api_page([])}
    fetch, _ = legacy(pages)
    counts = LivelibClient.export_all(345497, str(tmp_path), fetch=fetch)
    assert counts["livelib-books.json"] == 1


# ------------------------------------------------------------- module level

def test_module_level_export_all_is_the_client_classmethod():
    from text_forge import livelib
    assert livelib.export_all == LivelibClient.export_all      # same underlying fn


def test_shelf_status_names_are_the_note_statuses():
    assert SHELF_STATUS == {"read": "read", "reading": "reading",
                           "unread": "unread", "want": "wish"}


def test_api_details_are_gone_from_the_module():
    """text-forge keeps no API surface: no base url, no headers, no walker, no
    record parser, no SSR regex, no urllib — the package owns all of it.

    `re` stays (it is a local import inside the work-key heuristic, which is
    pipeline logic); what must not exist is a module-level API constant or wire
    helper.
    """
    from text_forge import livelib
    for name in ("API_BASE", "SITE_BASE", "ART_SHELF", "default_fetch",
                 "parse_flight_collections", "parse_api_record", "urllib",
                 "_HEADERS", "_FLIGHT", "_RECORD", "httpx"):
        assert not hasattr(livelib, name), name
    assert not any(hasattr(LivelibClient, a) for a in ("_paged", "_shelf_page"))


# --------------------------------------------------------- work-key heuristics

def test_pick_work_id_rules():
    from text_forge.livelib import pick_work_id
    titles = [("Сказание о Кише", "W2"), ("Белый Клык", "W1")]
    # 1. exact match on the normalized title
    assert pick_work_id(titles, "Белый клык") == "W1"
    # 2. the collection is named after the work it OPENS with, not the longer
    #    title buried inside it; with no «Морской волк" in the fixture, both
    #    remaining works run from 0 and the longer match wins
    assert pick_work_id(titles, "Морской волк. Белый Клык") == "W2"
    # 3. nothing shares a leading word: livelib's own first-entry choice
    assert pick_work_id(titles, "Неизвестный сборник") == "W2"
    assert pick_work_id(titles) == "W2"
    assert pick_work_id([]) is None


def test_pick_work_id_longest_run_wins_when_two_works_share_the_front():
    """With every candidate running from position 0, the longest one is the work
    the collection is named after (a single-word neighbour must not steal it)."""
    from text_forge.livelib import pick_work_id
    three = [("Морской волк", "W3"), ("Сказание о Кише", "W2"), ("Белый Клык", "W1")]
    assert pick_work_id(three, "Морской волк. Белый Клык") == "W3"


def test_pick_work_id_ignores_volume_noise():
    from text_forge.livelib import pick_work_id
    titles = [("Родная речь", "W1"), ("Советское барокко", "W2")]
    assert pick_work_id(titles, "Родная речь. Советское барокко. 60-е. "
                               "В 2 томах. Том 1") == "W1"


def test_norm_title_drops_edition_noise():
    from text_forge.livelib import _norm_title, _words
    assert _norm_title("Белый Клык. Том 2") == "белый клык"
    assert _words("Сказание о Кише") == ["сказание", "о", "кише"]
