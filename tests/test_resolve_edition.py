"""Tests for resolving an edition's title/author from livelib, and its cache.

The point of the resolver is to make curation smaller: a cited-but-unshelved
work needs only its edition id, the rest comes from the source. The edition card
(/art-editions/{id}) answers for ANY id, so no query is guessed and no search
index is involved — one call per id, and the cache makes the next build offline.
"""

import json

from text_forge.livelib import LivelibClient
from text_forge.wtd_books import resolve_edition_cached

TARGET = "1000898792"


def card(id_=TARGET, title="Драйв. Что на самом деле нас мотивирует",
         authors=("Дэниел Пинк",)):
    return json.dumps({"status": 200, "error": None, "payload": {"data": {
        "id": int(id_), "title": title,
        "url": f"/book/{id_}-slug",
        "authors": [{"full_name": a} for a in authors]}}},
        separators=(",", ":"))


class TestEditionsCache:
    def test_second_call_is_served_from_cache_without_network(self, tmp_path):
        cache = tmp_path / "livelib-export" / "editions-cache.json"
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return card()
        client = LivelibClient(fetch=fetch)
        first = resolve_edition_cached(TARGET, cache_path=cache, client=client)
        second = resolve_edition_cached(TARGET, cache_path=cache, client=client)
        assert first["title"] == "Драйв. Что на самом деле нас мотивирует"
        assert second == first
        assert len(calls) == 1, "second build must be offline (cache hit)"
        assert json.loads(cache.read_text(encoding="utf-8"))[TARGET]["title"] == \
            "Драйв. Что на самом деле нас мотивирует"

    def test_unresolved_id_is_cached_so_a_rebuild_does_not_retry(self, tmp_path):
        cache = tmp_path / "editions-cache.json"
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return json.dumps({"payload": {"data": {}}})
        client = LivelibClient(fetch=fetch)
        a = resolve_edition_cached(TARGET, cache_path=cache, client=client)
        b = resolve_edition_cached(TARGET, cache_path=cache, client=client)
        assert a["title"] == "" and b["title"] == ""
        assert len(calls) == 1

    def test_cache_records_where_the_title_came_from(self, tmp_path):
        cache = tmp_path / "editions-cache.json"
        client = LivelibClient(fetch=lambda u: card(title="T"))
        assert resolve_edition_cached(TARGET, cache_path=cache,
                                     client=client)["source"] == "api"
        miss = LivelibClient(fetch=lambda u: json.dumps({"payload": {"data": {}}}))
        assert resolve_edition_cached("999999", cache_path=cache,
                                     client=miss)["source"] == "none"

    def test_cache_is_written_even_for_a_nested_path(self, tmp_path):
        cache = tmp_path / "deep" / "nested" / "editions-cache.json"
        resolve_edition_cached(TARGET, cache_path=cache,
                              client=LivelibClient(fetch=lambda u: card(title="T")))
        assert cache.exists()

    def test_no_cache_path_still_resolves(self):
        got = resolve_edition_cached(TARGET,
                                    client=LivelibClient(fetch=lambda u: card(title="T")))
        assert got["title"] == "T"
