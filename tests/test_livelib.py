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

def test_shelf_paginates_until_no_new_editions():
    p1 = flight_html([collection(1, 100, "А"), collection(2, 200, "Б")])
    p2 = flight_html([collection(1, 100, "А"), collection(3, 300, "В")])
    p3 = flight_html([collection(1, 100, "А")])
    urls = []

    def fetch(url):
        urls.append(url)
        return [p1, p2, p3][len(urls) - 1]

    c = LivelibClient(fetch=fetch)
    recs = c.shelf(345497, "read")
    assert {r["edition_id"] for r in recs} == {"100", "200", "300"}
    assert all(r["status"] == "read" for r in recs)
    assert urls[0].endswith("/books/read?page=1")


def test_shelf_dedupes_repeated_page1_payloads():
    """want-style shelves ignore ?page and keep returning page 1: stop cleanly."""
    same = flight_html([collection(1, 100, "А")])

    def fetch(url):
        return same

    recs = LivelibClient(fetch=fetch).shelf(345497, "want")
    assert len(recs) == 1 and recs[0]["status"] == "wish"


def test_rating_scales_to_my_mark():
    recs = parse_flight_collections(flight_html([collection(1, 100, "А", rating=8)]))
    assert recs[0]["rating"] == 8
    assert recs[0]["my_mark"] == 4
    assert parse_flight_collections(flight_html([collection(2, 200, "Б", rating=0)]))[0]["my_mark"] is None


def test_books_merges_shelves_with_status_priority():
    def fetch(url):
        if "/books/read" in url:
            return flight_html([collection(1, 100, "Зона", rating=8)])
        if "/books/unread" in url:
            return flight_html([collection(9, 100, "Зона", rating=8),
                                collection(2, 200, "Идиот")])
        return flight_html([])

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


def test_search_returns_editions_only():
    payload = {"status": 200, "error": None, "payload": {"data": [
        {"type": "art_editions", "instance": {"id": 100, "title": "Зона",
         "authors": [{"full_name": "Сергей Довлатов"}], "url": "/book/100-zona"}},
        {"type": "authors", "instance": {"id": 5, "title": "Довлатов"}},
    ]}}

    results = LivelibClient(fetch=lambda url: json.dumps(payload)).search("зона")
    assert len(results) == 1
    assert results[0]["edition_id"] == "100"
    assert results[0]["author"] == "Сергей Довлатов"
    assert results[0]["livelib_url"].startswith("https://beta.livelib.ru/book/")
