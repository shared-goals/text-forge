"""Tests for extended crawl: resolving an edition's title/author from livelib.

The point of resolve_edition is to make curation smaller: a reference book needs
only its edition id, the rest comes from the source. The limit that shapes the
design is that livelib's search API returns at most ~20 editions per query and
ignores `limit` beyond that — so an id cannot be looked up directly, and the
caller must supply the queries and keep a fallback.
"""

import json

from text_forge.livelib import LivelibClient
from text_forge.wtd_books import resolve_edition_cached


def envelope(items):
    return json.dumps({"status": "ok", "error": None,
                      "payload": {"pagination": {"next_page": None}, "data": items}})


def edition(id_, title, authors, url=None):
    return {"type": "art_editions",
            "instance": {"id": id_, "title": title,
                        "authors": [{"full_name": a} for a in authors],
                        "url": url or f"/book/{id_}-slug"}}


TARGET = "1000898792"
NEIGHBOUR = "1011441203"


def fetch_for(results_by_query):
    """A fetch that answers a search query from a fixed table, recording queries.

    A '*' key is a catch-all (used when the test does not care what was asked);
    any other key matches by substring of the decoded query.
    """
    calls = []

    def fetch(url, timeout=30):
        calls.append(url)
        assert "/search?query=" in url, url
        from urllib.parse import unquote
        q = unquote(url.split("query=", 1)[1].split("&")[0])
        if "*" in results_by_query:
            return envelope(results_by_query["*"])
        for key, items in results_by_query.items():
            if key in q:
                return envelope(items)
        return envelope([])
    fetch.calls = calls
    return fetch


class TestResolveEdition:
    def test_finds_the_edition_by_id_among_neighbours(self):
        """The match is by ID, not by position: a hit for another edition of the
        same work must not be mistaken for the target."""
        fetch = fetch_for({"*": [
            edition(NEIGHBOUR, "Ключевые идеи книги: Драйв", []),
            edition(TARGET, "Драйв. Что на самом деле нас мотивирует", ["Дэниел Пинк"]),
        ]})
        c = LivelibClient(fetch=fetch)
        assert c.resolve_edition(TARGET, extra_queries=["Драйв Пинк"]) == {
            "title": "Драйв. Что на самом деле нас мотивирует", "author": "Дэниел Пинк"}

    def test_author_list_is_joined(self):
        fetch = fetch_for({"*": [edition(TARGET, "Сборник", ["А", "Б", "В"])]})
        c = LivelibClient(fetch=fetch)
        assert c.resolve_edition(TARGET, extra_queries=["q"])["author"] == "А, Б, В"

    def test_missing_edition_returns_empty_not_an_error(self):
        """An id livelib does not return is a curation problem, not a crash: the
        caller reports it and falls back to its own data."""
        fetch = fetch_for({"*": [edition(NEIGHBOUR, "Чужая книга", ["Кто-то"])]})
        c = LivelibClient(fetch=fetch)
        assert c.resolve_edition(TARGET, extra_queries=["q"]) == {}

    def test_queries_are_tried_in_order_and_stopped_on_hit(self):
        fetch = fetch_for({"второй": [edition(TARGET, "Найдено", ["Автор"])]})
        c = LivelibClient(fetch=fetch)
        got = c.resolve_edition(TARGET, extra_queries=["первый запрос", "второй запрос"])
        assert got["title"] == "Найдено"
        assert len(fetch.calls) == 2, fetch.calls

    def test_blank_queries_are_skipped(self):
        fetch = fetch_for({"*": [edition(TARGET, "Найдено", ["Автор"])]})
        c = LivelibClient(fetch=fetch)
        c.resolve_edition(TARGET, extra_queries=["", "   ", "рабочий запрос"])
        assert len(fetch.calls) == 1

    def test_transport_error_on_one_query_does_not_kill_the_lookup(self):
        """The id may be reachable only via another query; a 404 on the first is
        not fatal."""
        def fetch(url, timeout=30):
            if "плохой" in url:
                raise RuntimeError("HTTP 404")
            return envelope([edition(TARGET, "Хорошо", ["Автор"])])
        c = LivelibClient(fetch=fetch)
        assert c.resolve_edition(TARGET, extra_queries=["плохой q", "хороший q"])["title"] == "Хорошо"

    def test_non_edition_hit_types_are_ignored(self):
        fetch = fetch_for({"*": [{"type": "users", "instance": {"id": TARGET,
                                                                      "title": "Профиль",
                                                                      "authors": []}},
                                      edition(TARGET, "Книга", ["Автор"])]})
        c = LivelibClient(fetch=fetch)
        assert c.resolve_edition(TARGET, extra_queries=["q"]) == {"title": "Книга", "author": "Автор"}

    def test_no_queries_means_no_network_and_empty_result(self):
        def fetch(url, timeout=30):
            raise AssertionError("must not fetch: no query to search for")
        assert LivelibClient(fetch=fetch).resolve_edition(TARGET) == {}


class TestEditionsCache:
    def test_second_call_is_served_from_cache_without_network(self, tmp_path):
        cache = tmp_path / "livelib-export" / "editions-cache.json"
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return envelope([edition(TARGET, "Драйв", ["Дэниел Пинк"])])
        client = LivelibClient(fetch=fetch)
        first = resolve_edition_cached(TARGET, cache_path=cache, client=client, queries=["q"])
        second = resolve_edition_cached(TARGET, cache_path=cache, client=client, queries=["q"])
        assert first["title"] == "Драйв"
        assert second == first
        assert len(calls) == 1, "second build must be offline (cache hit)"
        assert json.loads(cache.read_text(encoding="utf-8"))[TARGET]["title"] == "Драйв"

    def test_unresolved_id_is_cached_so_a_rebuild_does_not_retry(self, tmp_path):
        cache = tmp_path / "editions-cache.json"
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return envelope([])
        client = LivelibClient(fetch=fetch)
        a = resolve_edition_cached(TARGET, cache_path=cache, client=client, queries=["q"])
        b = resolve_edition_cached(TARGET, cache_path=cache, client=client, queries=["q"])
        assert a["title"] == "" and b["title"] == ""
        assert len(calls) == 1

    def test_cache_records_where_the_title_came_from(self, tmp_path):
        cache = tmp_path / "editions-cache.json"
        client = LivelibClient(fetch=fetch_for({"*": [edition(TARGET, "T", ["A"])]}))
        assert resolve_edition_cached(TARGET, cache_path=cache, client=client,
                                     queries=["q"])["source"] == "api"
        miss = LivelibClient(fetch=fetch_for({"*": []}))
        assert resolve_edition_cached("999999", cache_path=cache, client=miss,
                                     queries=["q"])["source"] == "none"

    def test_cache_is_written_even_for_a_nested_path(self, tmp_path):
        cache = tmp_path / "deep" / "nested" / "editions-cache.json"
        resolve_edition_cached(TARGET, cache_path=cache,
                              client=LivelibClient(fetch=fetch_for({"*": [edition(TARGET, "T", ["A"])]})),
                              queries=["q"])
        assert cache.exists()

    def test_no_cache_path_still_resolves(self):
        got = resolve_edition_cached(TARGET,
                                    client=LivelibClient(fetch=fetch_for({"*": [edition(TARGET, "T", ["A"])]})),
                                    queries=["q"])
        assert got["title"] == "T"
