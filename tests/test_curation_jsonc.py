"""Tests for the consolidated curation file (curation.jsonc).

One file, one entity, normal form: a LiveLib edition is ONE entry keyed by its
edition id, and every fact that livelib itself can tell us is NOT stored.

Two layers are tested separately on purpose:
  * load_curation — the JSONC syntax (comments outside strings only);
  * build_books(curation_path=...) — the semantic mapping onto the build.
"""

import json

from text_forge.wtd_books import build_books, load_curation

BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}
Q1 = {
    "id": 1,
    "text": "<p>Текст первой цитаты</p>",
    "created_at": "2024-03-01T10:00:00",
    "quote": {"quote_id": 100, "url": "/quote/100-zona-sergej-dovlatov"},
    "art_edition": {"url": "/book/1000699994-zona-sergej-dovlatov", "title": "Зона",
                    "authors": [{"full_name": "Сергей Довлатов"}]},
}


class TestLoadCuration:
    """JSONC: // line comments and /* */ blocks, outside strings only."""

    def test_plain_json_still_loads(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text('{"books": {"1": {"weight": 3}}}', encoding="utf-8")
        assert load_curation(p) == {"books": {"1": {"weight": 3}}}

    def test_line_comments_stripped(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  // a whole-line comment\n'
            '  "books": {} // trailing comment\n'
            '}\n', encoding="utf-8")
        assert load_curation(p) == {"books": {}}

    def test_block_comments_stripped(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  /* block\n     comment */\n'
            '  "external": [] /* inline */\n'
            '}\n', encoding="utf-8")
        assert load_curation(p) == {"external": []}

    def test_double_slash_inside_string_is_kept(self, tmp_path):
        """The regression this pins: a naive regex eats https:// in titles and
        URLs, so 'https://x' becomes 'https:' and silently corrupts curation."""
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  "books": {\n'
            '    // "Лунная пыль. Я, робот" — the comment is real\n'
            '    "1000507758": {"note": "https://www.livelib.ru/book/1000507758"}\n'
            '  }\n'
            '}\n', encoding="utf-8")
        got = load_curation(p)
        assert got["books"]["1000507758"]["note"] == "https://www.livelib.ru/book/1000507758"

    def test_url_in_comment_is_dropped_but_in_string_is_kept(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  // see https://www.livelib.ru/book/999 for details\n'
            '  "links": {"https://www.livelib.ru/book/111": "slug-keeps-http-slashes"}\n'
            '}\n', encoding="utf-8")
        got = load_curation(p)
        assert got == {"links": {"https://www.livelib.ru/book/111": "slug-keeps-http-slashes"}}

    def test_escaped_quote_does_not_open_a_string(self, tmp_path):
        r"""A title like "Книга \"со внутри\" // не комментарий" — the escaped
        quote must not toggle string state, or the // after it survives."""
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  "t": "a \\" b" // comment stripped\n'
            '}\n', encoding="utf-8")
        assert load_curation(p) == {"t": 'a " b'}

    def test_slash_inside_string_not_treated_as_block_start(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text('{"t": "a /* b", "u": "c"} /* real */\n', encoding="utf-8")
        assert load_curation(p) == {"t": "a /* b", "u": "c"}

    def test_full_target_schema_round_trip(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text(
            '{\n'
            '  // entities: one per livelib edition id\n'
            '  "books": {\n'
            '    // Лунная пыль. Я, робот. Стальные пещеры\n'
            '    // @url:`https://www.livelib.ru/book/1000507758`\n'
            '    "1000507758": {\n'
            '      "weight": 32,\n'
            '      "merges": [1000507759]\n'
            '    },\n'
            '    /* status and mark are curation: livelib shelves can lie */\n'
            '    "1000284779": {\n'
            '      "status": "read",\n'
            '      "my_mark": 5\n'
            '    }\n'
            '  }\n'
            '}\n', encoding="utf-8")
        assert load_curation(p) == {
            "books": {
                "1000507758": {"weight": 32, "merges": [1000507759]},
                "1000284779": {"status": "read", "my_mark": 5},
            },
        }

    def test_missing_sections_default_to_empty(self, tmp_path):
        """A curation file may name only what it curates."""
        p = tmp_path / "curation.jsonc"
        p.write_text('{"books": {"1": {"weight": 1}}}', encoding="utf-8")
        cur = load_curation(p)
        assert cur.get("books") == {"1": {"weight": 1}}
        assert cur.get("merges", {}) == {}

    def test_accepts_str_path_as_well_as_path(self, tmp_path):
        p = tmp_path / "curation.jsonc"
        p.write_text('{"books": {}} // ok', encoding="utf-8")
        assert load_curation(str(p)) == {"books": {}}


class TestBuildWithCuration:
    """curation_path replaces the 7 per-concern files."""

    def write_inputs(self, tmp_path, books=(), quotes=(), reviews=()):
        for name, data in (("books.json", books), ("quotes.json", quotes),
                          ("reviews.json", reviews)):
            (tmp_path / name).write_text(json.dumps(list(data), ensure_ascii=False),
                                        encoding="utf-8")
        return (tmp_path / "books.json", tmp_path / "quotes.json",
                tmp_path / "reviews.json")

    def test_author_field_replaces_author_overrides(self, tmp_path):
        """books[].author overrides a live export author (livelib has editions
        with the author field empty or wrong)."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1001128870", author="")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{\n  // "Стратегическая психология"\n'
                      '  "books": {"1001128870": {"author": "Александр Юрьев"}}\n}\n',
                      encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        notes = list(out.glob("*.md"))
        assert len(notes) == 1
        md = notes[0].read_text(encoding="utf-8")
        assert "yurev" in notes[0].name
        # bare scalar, as every other author in the corpus renders
        assert "author: Александр Юрьев" in md

    def test_status_and_my_mark_replace_book_overrides(self, tmp_path):
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000327729",
                 status=None, my_mark=None)
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"books": {"1000327729": {"status": "read", "my_mark": 5}}}',
                      encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "status: read" in md
        assert "my_mark: 5" in md

    def test_weight_implies_important(self, tmp_path):
        """weight alone means important: the old file pair (important.json +
        weight) collapses into one field."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"books": {"1000699994": {"weight": 7}}}', encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "important: true" in md
        assert "weight: 7" in md

    def test_an_edition_keeps_its_author_and_its_quotes(self, tmp_path):
        """No omnibus flag exists: every edition is a book like any other.

        «Белые ночи. Бедные люди. Преступление и наказание» is a collection, but
        with works-based grouping the works inside it group through their own
        work ids, so the collection's own note keeps its author and the quotes
        its records were made from.
        """
        shelf = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000018782",
                     title="Белые ночи. Бедные люди. Преступление и наказание",
                     author="Фёдор Достоевский")
        q = {"id": 1, "text": "<p>Цитата</p>", "created_at": "2024-01-01T00:00:00",
             "quote": {"quote_id": 10, "url": "/quote/10"},
             "art_edition": {"url": "/book/1000018782-belye-nochi",
                            "title": "Белые ночи. Бедные люди. Преступление и наказание",
                            "authors": [{"full_name": "Фёдор Достоевский"}]}}
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[shelf], quotes=[q])
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        md = (out / "dostoevskiy-belye-nochi.md").read_text(encoding="utf-8")
        assert "^quote_" in md
        assert "author: Фёдор Достоевский" in md
        assert report["quotes_placed"] == 1

    def test_no_merges_section(self, tmp_path):
        """A top-level `merges` section is not read.

        A duplicate the work relation DOES reach merges whether or not the dead
        section names it; a duplicate it does NOT reach (two unrelated shelf ids
        with no shared work) stays two notes however the section is written —
        with a `title`/`author` entry shape or without. Only a `merges` array on
        the main entry states a merge the source cannot reach.
        """
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1003248852")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010727563",
                  my_mark=None)
        # one work, stated by the relation: ONE note — the section is not what
        # did it
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{\n  // Ленин. Пантократор солнечных пылинок\n'
                      '  // @url:`https://www.livelib.ru/book/1003248852`\n'
                      '  "books": {"1003248852": {"weight": 16}},\n'
                      '  "merges": {"1010727563": "1003248852"}\n}\n', encoding="utf-8")
        out = tmp_path / "out"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur,
                            work_id_by_edition={"1003248852": "1002397147",
                                               "1010727563": "1002397147"})
        assert report["books"] == 1
        # two UNRELATED shelf ids: the section names a merge and does nothing
        # (1001474484 is cited-by-nothing and shares no work with 1000699994:
        # 1010727563 is not a shelf record here, so nothing relates them)
        for tag, body in (("map", '  "merges": {"1001474484": "1000699994"}\n'),
                         ("list", '  "merges": [{"remove": "1001474484",\n'
                                  '               "into": "1000699994",\n'
                                  '               "title": "Чужой титул",\n'
                                  '               "author": "Кто-то"}]\n')):
            books = [dict(e1, book_url="https://www.livelib.ru/book/1000699994",
                         title="Другая книга"),
                     dict(e2, book_url="https://www.livelib.ru/book/1001474484")]
            books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=books)
            cur.write_text('{\n  "books": {"1000699994": {"weight": 16}},\n'
                           + body + '}\n', encoding="utf-8")
            out2 = tmp_path / ("out-" + tag)
            report = build_books(books_p, quotes_p, reviews_p, out2, curation_path=cur)
            assert report["books"] == 2, body
            names = sorted(p.name for p in out2.glob("*.md"))
            assert all("chuzhoy-titul" not in n for n in names), names

    def test_per_book_merges_array_folds_edition_into_the_note(self, tmp_path):
        """books[main].merges = [other id]: the normal form of a work merge.

        No top-level `merges` section: the canonicity belongs to the canonical
        entry. The other id's quotes and review land in the MAIN id's note, the
        note keeps its slug, and `livelib_editions` still lists the merged id so
        links filed under it resolve.
        """
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1003248852",
                  title="Ленин. Пантократор солнечных пылинок", author="Лев Данилкин")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010727563",
                  title="Ленин", author="Данилкин Лев", my_mark=None)
        q = dict(Q1, id=70, quote={"quote_id": 700, "url": "/quote/700-lenin"},
                 art_edition={"url": "/book/1010727563-lenin",
                             "title": "Ленин",
                             "authors": [{"full_name": "Лев Данилкин"}]})
        r = {"id": 901, "url": "/review/901-lenin", "text": "<p>Биография.</p>",
             "created_at": "2023-05-01T00:00:00",
             "art_edition": {"url": "/book/1010727563-lenin", "title": "Ленин",
                            "authors": [{"full_name": "Лев Данилкин"}]}}
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2],
                                                        quotes=[q], reviews=[r])
        # without the merge: two notes, the review with the doomed one
        plain = tmp_path / "plain"
        build_books(books_p, quotes_p, reviews_p, plain)
        assert len(list(plain.glob("*.md"))) == 2
        # with the per-book merges array: one note, main id's slug and title
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{\n  // Ленин. Пантократор солнечных пылинок\n'
                      '  "books": {"1003248852": {"weight": 16, '
                      '"merges": [1010727563]}}\n}\n', encoding="utf-8")
        out = tmp_path / "out"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert report["books"] == 1
        note = out / "danilkin-lenin-pantokrator-solnechnykh-pylinok.md"
        assert note.exists()
        md = note.read_text(encoding="utf-8")
        assert "livelib_editions:" in md and "1010727563" in md
        assert "https://www.livelib.ru/quote/700" in md
        # the review came from the merged edition but the note owns it now
        assert 'livelib_review: "https://www.livelib.ru/review/901"' in md
        # the merged id maps to the main note in the link map the validator reads
        assert report["link_map"]["https://www.livelib.ru/book/1010727563"] == \
            "danilkin-lenin-pantokrator-solnechnykh-pylinok"

    def test_text_ids_are_derived_into_reference_notes(self, tmp_path):
        """A livelib /book/<id> a text links, that no shelf record and no
        quote/review names, becomes its own note — title and author come from
        the JSON API at build time, cached so a rebuild stays offline.

        No curated section names such a book, and no `url` override exists: the
        id the text writes IS the id the note declares.
        """
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1])
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text(
            "[Радищев](https://www.livelib.ru/book/1002971633-puteshestvie"
            "-iz-peterburga-v-moskvu-aleksandr-radischev)\n", encoding="utf-8")
        out = tmp_path / "books"
        seen = []

        def fetch(url):
            seen.append(url)
            return json.dumps({"status": 200, "error": None, "payload": {"data": {
                "id": 1002971633, "title": "Путешествие из Петербурга в Москву",
                "url": "/book/1002971633-puteshestvie-iz-peterburga-v-moskvu",
                "authors": [{"full_name": "Александр Радищев"}]}}},
                separators=(",", ":"))

        cache = tmp_path / "editions-cache.json"
        report = build_books(books_p, quotes_p, reviews_p, out, text_dir=text_dir,
                            editions_cache_path=cache, fetch=fetch)
        assert seen[0] == ("https://beta.api.livelib.ru/trisolaris/api/art-editions"
                           "/1002971633"), seen
        assert report["unresolved_reference_books"] == []
        md = (out / "radishchev-puteshestvie-iz-peterburga-v-moskvu.md").read_text(encoding="utf-8")
        assert 'title: "Путешествие из Петербурга в Москву"' in md
        assert "author: Александр Радищев" in md
        assert "status: read" in md
        # the same crawl, warm cache: no transport at all
        quiet = lambda u: (_ for _ in ()).throw(AssertionError("network"))
        out2 = tmp_path / "out2"
        build_books(books_p, quotes_p, reviews_p, out2, text_dir=text_dir,
                   editions_cache_path=cache, fetch=quiet)
        assert (out2 / "radishchev-puteshestvie-iz-peterburga-v-moskvu.md").exists()
        # and the url the text wrote resolves against the note the build wrote
        from text_forge.wtd_books import validate_text_links
        res = validate_text_links(text_dir, out, link_mappings_path=report["link_map"])
        assert res["resolved"] == 1 and res["unresolved"] == []

    def test_quote_and_review_ids_in_text_make_no_note(self, tmp_path):
        """Only /book/ and /work/ ids are scanned: a quote or review id is placed
        by the export, it never needs metadata resolution."""
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text(
            "[q](https://www.livelib.ru/quote/555-x)\n"
            "[r](https://www.livelib.ru/review/777-y)\n", encoding="utf-8")
        out = tmp_path / "books"

        def boom(url):
            raise AssertionError(f"must not fetch: {url}")

        build_books(books_p, quotes_p, reviews_p, out, text_dir=text_dir,
                    editions_cache_path=tmp_path / "editions-cache.json", fetch=boom)
        assert list(out.glob("*.md")) == []

    def test_curated_main_without_shelf_record_keys_the_note(self, tmp_path):
        """A merges MAIN may hold no shelf record: the note still keys by it.

        The main id's title/author come from the edition card JSON (the same
        crawl a reference book gets), the member edition's quotes land in the
        main note, and the curation weight rides on the main id.
        """
        e1 = {"book_url": "https://www.livelib.ru/book/1008888709",
              "title": "Письма Баламута. Баламут предлагает тост (сборник)",
              "author": "Клайв Стейплз Льюис", "status": "read", "my_mark": 5}
        q = dict(Q1, id=77, quote={"quote_id": 770, "url": "/quote/770-balamut"},
                 art_edition={"id": 1008888709, "url": "/book/1008888709-pisma",
                              "title": "Письма Баламута",
                              "authors": [{"full_name": "Клайв Стейплз Льюис"}]})
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1], quotes=[q])
        cur = tmp_path / "curation.jsonc"
        cur.write_text(json.dumps({"books": {"1000327729": {
            "weight": 13, "status": "read", "my_mark": 5,
            "merges": [1008888709]}}}), encoding="utf-8")
        card = json.dumps({"payload": {"data": {
            "id": 1000327729,
            "title": "Письма Баламута",
            "authors": [{"full_name": "Клайв Стейплз Льюис"}]}}})

        def fetch(url):
            if "/art-editions/1000327729/contents" in url:
                return json.dumps({"status": 200, "error": None,
                                   "payload": {"data": []}})
            assert "/art-editions/1000327729" in url, url
            return card

        out = tmp_path / "out"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur,
                             editions_cache_path=tmp_path / "ed.json", fetch=fetch)
        note = out / "lyuis-pisma-balamuta.md"
        assert note.exists(), sorted(f.name for f in out.glob("*.md"))
        md = note.read_text(encoding="utf-8")
        assert 'livelib_book: "https://www.livelib.ru/book/1000327729"' in md
        assert "weight: 13" in md
        assert "https://www.livelib.ru/quote/770" in md
        assert report["books"] == 1

    def test_unresolvable_text_id_is_reported_and_makes_no_note(self, tmp_path):
        """An id the edition card does not carry is warned about and no note is
        made: the corpus then reports the link unresolved rather than silently
        inventing a title for it."""
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text("[x](https://www.livelib.ru/book/9999999)\n",
                                      encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, text_dir=text_dir,
                            editions_cache_path=tmp_path / "editions-cache.json",
                            fetch=lambda u: json.dumps({"status": 200, "error": None,
                                                      "payload": {"data": {}}}))
        assert report["unresolved_reference_books"] == ["9999999"]
        assert list(out.glob("*.md")) == []

    def test_no_text_dir_means_no_derived_notes(self, tmp_path):
        """A caller that offers no text dir builds from the export alone."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1])
        out = tmp_path / "books"

        def boom(url):
            raise AssertionError(f"must not fetch: {url}")

        build_books(books_p, quotes_p, reviews_p, out,
                    editions_cache_path=tmp_path / "editions-cache.json", fetch=boom)
        assert [f.name for f in out.glob("*.md")] == ["dovlatov-zona.md"]
    def test_curation_path_none_is_pure_export(self, tmp_path):
        """With no curation the build is still valid (pure source)."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=None)
        assert report["books"] == 1
        assert "important:" not in (out / "dovlatov-zona.md").read_text(encoding="utf-8")

    def test_missing_curation_file_is_an_error(self, tmp_path):
        """A named-but-absent curation file must not silently mean 'no curation'
        — that would drop curation and produce a plausible-looking wrong corpus."""
        import pytest
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        with pytest.raises((FileNotFoundError, OSError)):
            build_books(books_p, quotes_p, reviews_p, tmp_path / "books",
                       curation_path=tmp_path / "nope.jsonc")
