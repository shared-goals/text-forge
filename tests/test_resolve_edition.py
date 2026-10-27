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


class TestCachedLookup:
    """The cache-aside skeleton of the livelib caches: `_load_cache`,
    `_cached_lookup`, `_store_cache`.

    Three states of a key: ABSENT, a placeholder WITHOUT the answer field, and an
    ANSWER (which may legitimately be None). Plus: a fetch that fails (raises, or
    returns None meaning unreachable) records NOTHING, so the next build retries.
    The load/store pair is what makes a caller's disk traffic exactly one read and
    one write.
    """

    def test_absent_key_fetches(self):
        from text_forge.wtd_books import _cached_lookup
        calls = []
        cache = {}
        assert _cached_lookup(cache, "k", has_answer,
                             lambda: calls.append(1) or {"answer": "v"}) == {"answer": "v"}
        assert calls == [1]
        assert cache == {"k": {"answer": "v"}}

    def test_placeholder_without_answer_field_fetches(self):
        """A record written by another builder is not an answer."""
        from text_forge.wtd_books import _cached_lookup
        calls = []
        cache = {"k": {"title": "запись другого строителя"}}
        assert _cached_lookup(cache, "k", has_answer,
                             lambda: calls.append(1) or {"answer": "v"}) == {"answer": "v"}
        assert calls == [1]
        # the fresh record REPLACES the placeholder: no half-true provenance is
        # kept beside an answer the source just gave
        assert cache["k"] == {"answer": "v"}

    def test_an_answer_is_returned_without_fetching(self):
        """EVERY record carrying the answer field is an answer — None included."""
        from text_forge.wtd_books import _cached_lookup

        def boom():
            raise AssertionError("network")

        for record in ({"answer": "v"}, {"answer": None}):
            cache = {"k": record}
            assert _cached_lookup(cache, "k", has_answer, boom) == record

    def test_an_empty_record_is_no_answer(self):
        """`{}` (and None) carries no field, so the fetch still runs."""
        from text_forge.wtd_books import _cached_lookup
        for record in ({}, None):
            cache = {"k": record}
            # a placeholder record is completed in place, keeping what the other
            # builder wrote when it was a dict
            assert _cached_lookup(cache, "k", has_answer,
                                 lambda: {"answer": None})["answer"] is None

    def test_a_none_from_fetch_writes_nothing(self):
        """Unreachable is a miss, not a record: the cache file stays untouched."""
        from text_forge.wtd_books import _cached_lookup
        cache = {}
        assert _cached_lookup(cache, "k", has_answer, lambda: None) is None
        assert cache == {}

    def test_a_raising_fetch_writes_nothing_and_reports_no_crash(self):
        """A transport failure is a miss, never raised over the whole build."""
        from text_forge.wtd_books import _cached_lookup
        cache = {}

        def boom():
            raise RuntimeError("403 Forbidden")

        assert _cached_lookup(cache, "k", has_answer, boom) is None
        assert cache == {}

    def test_the_answer_record_replaces_a_placeholder(self):
        """What the fetch answered is what gets stored — no merge of another
        builder's now-unverified fields into the answered record.
        """
        from text_forge.wtd_books import _cached_lookup
        cache = {"k": {"title": "T"}}
        assert _cached_lookup(cache, "k", has_answer,
                             lambda: {"source": "api"}) == {"source": "api"}
        assert cache["k"] == {"source": "api"}

    def test_load_and_store_round_trip_a_cache_file(self, tmp_path):
        """The pair is the whole disk contract: one read, one write, same data,
        and a nested directory is created for the store.
        """
        from text_forge.wtd_books import _load_cache, _store_cache
        path = tmp_path / "deep" / "nested" / "c.json"
        assert _load_cache(path) == {}                 # absent: no record, no crash
        data = {"7": {"work_id": None}, "9": {"title": "Т"}}
        _store_cache(path, data)
        assert _load_cache(path) == data
        # rewriting a loaded record replaces the file content wholesale
        loaded = _load_cache(path)
        loaded["8"] = {"work_id": "W8"}
        _store_cache(path, loaded)
        assert _load_cache(path) == {**data, "8": {"work_id": "W8"}}

    def test_a_missing_path_is_no_read_and_no_write(self, tmp_path):
        """No cache asked for, no file touched — the resolution still answers."""
        from text_forge.wtd_books import _cached_lookup, _load_cache, _store_cache
        path = tmp_path / "untouched.json"
        cache = _load_cache(None)
        assert _cached_lookup(cache, "k", has_answer, lambda: {"answer": "v"}) \
            == {"answer": "v"}
        _store_cache(None, cache)
        assert not path.exists()                       # only an explicit store writes
        _store_cache(path, cache)
        assert _load_cache(path) == cache

    def test_a_file_of_junk_is_no_record_and_the_next_store_wins(self, tmp_path):
        """A cache file holding no JSON object is treated as an empty cache, so
        the build rebuilds it instead of dying on it.
        """
        from text_forge.wtd_books import _load_cache, _store_cache
        path = tmp_path / "c.json"
        for junk in ("", "not json at all", "[]", '"a string"'):
            path.write_text(junk, encoding="utf-8")
            assert _load_cache(path) == {}
        _store_cache(path, {"k": {"answer": "v"}})
        assert _load_cache(path) == {"k": {"answer": "v"}}

    def test_the_unreachable_key_is_written_by_nobody_but_the_caller(self, tmp_path):
        """The helper keeps no file of its own: the caller stores the record, and
        a key the fetch could not answer stays out of what gets written.
        """
        from text_forge.wtd_books import _cached_lookup, _load_cache, _store_cache
        path = tmp_path / "c.json"
        cache = _load_cache(path)
        assert _cached_lookup(cache, "k", has_answer, lambda: None) is None
        _store_cache(path, cache)                     # the caller's single store
        assert _load_cache(path) == {}               # nothing recorded for `k`


def has_answer(record) -> bool:
    """The answer field for these tests is `answer` (None in it IS the answer)."""
    return bool(record) and "answer" in record
