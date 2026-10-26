"""Tests for the stable LiveLib export client (text_forge.livelib).

Transport is injected: every test drives the client with a fake fetch()
so no network is touched. Fixtures mirror the real formats verified
against livelib.ru on 2026-10-19.
"""
import json

import pytest

from text_forge.livelib import LivelibClient, parse_flight_collections

# ---------------------------------------------------------------- fixtures

def flight_html(records):
    """Wrap collection records the way Next.js embeds them in SSR HTML."""
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    # the payload travels as a JS string literal inside self.__next_f.push
    escaped = json.dumps(payload)
    return (
        "<html><head></head><body><script>"
        f'self.__next_f.push([1,{escaped}])'
        "</script></body></html>"
    )


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
    return json.dumps({"status": 200, "error": None,
                       "payload": {"pagination": pag, "data": data}})


# ------------------------------------------------------- flight collections

def test_parse_flight_collections_extracts_records():
    html = flight_html([collection(1, 100, "Зона"), collection(2, 200, "Мы")])
    recs = parse_flight_collections(html)
    assert [(r["collection_id"], r["edition_id"]) for r in recs] == [(1, "100"), (2, "200")]
    assert recs[0]["title"] == "Зона"
    assert recs[0]["author"] == "Лев Толстой"


def test_parse_flight_collections_keeps_escaped_quotes_in_titles():
    rec = collection(3, 300, 'Фаина Раневская: "Судьба-шлюха"')
    recs = parse_flight_collections(flight_html([rec]))
    assert recs[0]["title"] == 'Фаина Раневская: "Судьба-шлюха"'


def test_parse_flight_collections_ignores_pages_without_data():
    assert parse_flight_collections("<html><body>cookie wall</body></html>") == []


# ----------------------------------------------------------------- shelves
# since 2026-10-26 shelves come from the trisolaris JSON API
# (/users/{id}/arts/{reads,readings,unreads,wants}) — anonymous, paged, exact.
# The old SSR walk is gone: www ignored ?page, beta capped at 343 of 370.


def test_shelf_walks_api_pages():
    p1 = api_page([collection(1, 100, "А"), collection(2, 200, "Б")], next_offset=2)
    p2 = api_page([collection(3, 300, "В")])
    urls = []

    def fetch(url):
        urls.append(url)
        return [p1, p2][len(urls) - 1]

    c = LivelibClient(fetch=fetch)
    recs = c.shelf(345497, "read")
    assert {r["edition_id"] for r in recs} == {"100", "200", "300"}
    assert all(r["status"] == "read" for r in recs)
    assert "users/345497/arts/reads" in urls[0]


def test_shelf_dedupes_double_read_records():
    """Livelib keeps a second record when a book is re-marked read: one book, one entry."""
    p1 = api_page([collection(1, 100, "А"), collection(2, 100, "А")])

    recs = LivelibClient(fetch=lambda url: p1).shelf(345497, "read")
    assert len(recs) == 1 and recs[0]["edition_id"] == "100"


def test_shelf_want_uses_wish_status():
    p1 = api_page([collection(1, 100, "А")])

    recs = LivelibClient(fetch=lambda url: p1).shelf(345497, "want")
    assert len(recs) == 1 and recs[0]["status"] == "wish"


def test_shelf_api_records_carry_rating_and_mark():
    p1 = api_page([collection(1, 100, "А", rating=8), collection(2, 200, "Б", rating=0)])

    recs = LivelibClient(fetch=lambda url: p1).shelf(345497, "read")
    marks = {r["edition_id"]: r["my_mark"] for r in recs}
    assert marks == {"100": 4, "200": None}


def test_books_merges_shelves_with_status_priority():
    def fetch(url):
        if "/arts/reads" in url:
            return api_page([collection(1, 100, "Зона", rating=8)])
        if "/arts/unreads" in url:
            return api_page([collection(9, 100, "Зона", rating=8),
                             collection(2, 200, "Идиот")])
        return api_page([])

    books = LivelibClient(fetch=fetch).books(345497)
    by_id = {b["book_url"].rsplit("/", 1)[-1]: b for b in books}
    assert by_id["100"]["status"] == "read"  # read wins over unread
    assert by_id["100"]["my_mark"] == 4
    assert by_id["200"]["status"] == "unread"


# ------------------------------------------------------------ json exports

def test_quotes_paginates_until_next_page_is_none():
    pages = [api_page([{"id": 1}], 50), api_page([{"id": 2}], 100), api_page([], None)]
    seen = []

    def fetch(url):
        seen.append(url)
        return pages[len(seen) - 1]

    quotes = LivelibClient(fetch=fetch).quotes(345497)
    assert [q["id"] for q in quotes] == [1, 2]
    assert all("/quotes?" in u for u in seen)


def test_reviews_uses_reviews_endpoint():
    def fetch(url):
        assert "/reviews?" in url
        return api_page([{"id": 7}], None)

    assert LivelibClient(fetch=fetch).reviews(345497)[0]["id"] == 7


def test_edition_meta_reads_the_edition_card():
    """/art-editions/{id} answers the CARD for one edition: a bare object, not a
    list — and it answers for any id, shelf record or not. That is what makes the
    search API unnecessary as a metadata source."""
    card = json.dumps({"status": 200, "error": None, "payload": {"data": {
        "id": 100, "title": "Зона", "url": "/book/100-zona-sergej-dovlatov",
        "authors": [{"id": 5, "full_name": "Сергей Довлатов"},
                    {"id": 6, "full_name": "Третий Ли"}]}}},
        separators=(",", ":"))
    seen = []

    def fetch(url):
        seen.append(url)
        return card

    assert LivelibClient(fetch=fetch).edition_meta("100") == {
        "title": "Зона", "author": "Сергей Довлатов, Третий Ли"}
    assert seen == ["https://beta.api.livelib.ru/trisolaris/api/art-editions/100"]


def test_edition_meta_of_another_id_is_a_miss():
    """A card naming a different id is not an answer for ours — livelib answers
    a redirect-ish body, and a wrong title would silently corrupt the note."""
    card = json.dumps({"payload": {"data": {"id": 101, "title": "Чужая",
                                           "authors": []}}})
    assert LivelibClient(fetch=lambda u: card).edition_meta("100") == {}


def test_edition_meta_of_an_empty_card_is_a_miss():
    for body in ('{"payload": {"data": {}}}', '{"payload": {}}', "{}"):
        assert LivelibClient(fetch=lambda u: body).edition_meta("100") == {}


def test_edition_meta_swallows_a_transport_error():
    def boom(url):
        raise RuntimeError("403 Forbidden")

    assert LivelibClient(fetch=boom).edition_meta("100") == {}


# ---------------------------------------------------- edition -> work (Содержание)

def _flight_payload(json_text: str) -> str:
    """A trisolaris envelope as one escaped Next.js flight chunk (shelves)."""
    return ("<html><body><script>"
            f"self.__next_f.push([1,{json.dumps(json_text)}])"
            "</script></body></html>")


def contents_response(items):
    """The trisolaris /art-editions/{id}/contents envelope (live-verified
    2026-10-24): plain JSON, one entry per WORK the edition contains, each
    with its /work/<id> url. No HTML, no escaping layer."""
    return json.dumps({"status": 200, "error": None,
                       "payload": {"data": items}}, separators=(",", ":"))


def work_item(wid, title):
    return {"id": 200000 + int(wid) % 100000, "title": title,
            "url": f"/work/{wid}-{title.lower()}", "type": "повесть"}


def test_work_id_reads_the_trisolaris_contents_payload():
    """The contents travel as plain JSON from /art-editions/{id}/contents;
    Cyrillic arrives decoded — no escape layer exists anymore."""
    body = contents_response([
        work_item("1000956774", "Сказание о Кише"),
        work_item("1000880978", "Белый Клык")])
    got = LivelibClient(fetch=lambda u: body).work_id(
        "1001477191", title="Белый клык. Сказание о Кише")
    assert got == "1000880978"


def test_work_id_fetches_the_trisolaris_contents_endpoint():
    body = contents_response([work_item("1000880978", "Белый Клык")])
    seen = []

    def fetch(url):
        seen.append(url)
        return body

    assert LivelibClient(fetch=fetch).work_id("1001477191") == "1000880978"
    assert seen == ["https://beta.api.livelib.ru/trisolaris/api/art-editions/1001477191/contents"]


def test_work_id_single_work_edition_returns_that_work():
    html = contents_response([work_item("1002397147", "Ленин. Пантократор солнечных пылинок")])
    assert LivelibClient(fetch=lambda u: html).work_id("1003248852") == "1002397147"


def test_work_id_prefers_the_entry_matching_the_edition_title():
    """An omnibus lists several works; the work the edition is named after wins."""
    html = contents_response([work_item("1000956774", "Сказание о Кише"),
                        work_item("1000880978", "Белый клык")])
    c = LivelibClient(fetch=lambda u: html)
    assert c.work_id("1001477191", title="Белый клык. Сказание о Кише") == "1000880978"


def test_work_id_is_none_for_an_edition_without_a_work_list(tmp_path):
    c = LivelibClient(fetch=lambda u: contents_response([]))
    assert c.work_id("1000000001", cache_path=tmp_path / "works-cache.json") is None


def test_work_id_caches_under_the_cache_path(tmp_path):
    cache = tmp_path / "works-cache.json"
    calls = []

    def fetch(url):
        calls.append(url)
        return contents_response([work_item("1002397147", "Ленин")])

    c = LivelibClient(fetch=fetch)
    assert c.work_id("1003248852", cache_path=cache) == "1002397147"
    assert json.loads(cache.read_text(encoding="utf-8"))["1003248852"]["work_id"] == "1002397147"
    # a second call is served from the cache: no transport, same answer
    quiet = LivelibClient(fetch=lambda u: (_ for _ in ()).throw(AssertionError("network")))
    assert quiet.work_id("1003248852", cache_path=cache) == "1002397147"


def test_work_id_caches_a_miss_so_a_rebuild_stays_offline(tmp_path):
    cache = tmp_path / "works-cache.json"
    calls = []

    def fetch(url):
        calls.append(url)
        return contents_response([])

    c = LivelibClient(fetch=fetch)
    assert c.work_id("1000000001", cache_path=cache) is None
    assert json.loads(cache.read_text(encoding="utf-8"))["1000000001"]["work_id"] is None
    assert len(calls) == 1
    quiet = LivelibClient(fetch=lambda u: (_ for _ in ()).throw(AssertionError("network")))
    assert quiet.work_id("1000000001", cache_path=cache) is None
    assert len(calls) == 1


def test_pick_work_id_rules():
    from text_forge.livelib import pick_work_id
    titles = [("Сказание о Кише", "W2"), ("Белый Клык", "W1")]
    # 1. exact match on the normalized title
    assert pick_work_id(titles, "Белый клык") == "W1"
    # 2. the collection is named after the work it OPENS with, not the longer
    #    title buried inside it
    assert pick_work_id(titles, "Белый клык. Сказание о Кише") == "W1"
    #    longer title buried inside it; with no «Морской волк" in the fixture,
    #    both remaining works run from 0 and the longer match wins
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


def test_work_id_reports_none_when_the_page_is_unreachable(tmp_path):
    """A transport failure is a miss, not a crash — and is not cached, so the
    next build may reach livelib again."""
    cache = tmp_path / "works-cache.json"

    def boom(url):
        raise RuntimeError("403 Forbidden")

    assert LivelibClient(fetch=boom).work_id("1001477191", cache_path=cache) is None
    assert not cache.exists() or json.loads(cache.read_text(encoding="utf-8")) == {}
