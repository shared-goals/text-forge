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
            '    // "Лунная пыль. Я, робот"\n'
            '    "1000507758": {\n'
            '      "omnibus": true,\n'
            '      "weight": 32\n'
            '    },\n'
            '    /* status and mark are curation: livelib shelves can lie */\n'
            '    "1000284779": {\n'
            '      "status": "read",\n'
            '      "my_mark": 5\n'
            '    }\n'
            '  },\n'
            '  "merges": {"petr-rodnaya-rech": "vayl-rodnaya-rech"},\n'
            '  "links": {"https://www.livelib.ru/review/5033995": "tolstoy-ispoved"},\n'
            '  "external": ["https://www.livelib.ru/quote/251353"],\n'
            '  "reference-books": {"1002971633": {}}\n'
            '}\n', encoding="utf-8")
        assert load_curation(p) == {
            "books": {
                "1000507758": {"omnibus": True, "weight": 32},
                "1000284779": {"status": "read", "my_mark": 5},
            },
            "merges": {"petr-rodnaya-rech": "vayl-rodnaya-rech"},
            "links": {"https://www.livelib.ru/review/5033995": "tolstoy-ispoved"},
            "external": ["https://www.livelib.ru/quote/251353"],
            "reference-books": {"1002971633": {}},
        }

    def test_missing_sections_default_to_empty(self, tmp_path):
        """A curation file may name only what it curates."""
        p = tmp_path / "curation.jsonc"
        p.write_text('{"books": {"1": {"weight": 1}}}', encoding="utf-8")
        cur = load_curation(p)
        for section in ("books", "merges", "links", "external", "reference-books"):
            assert cur.get(section, None) in ({}, [], None) or section == "books"

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

    def test_omnibus_flag_excludes_quotes_but_keeps_review(self, tmp_path):
        """books[].omnibus == the old collections.json entry."""
        omni = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/8888888",
                    title="Собачье сердце. Записки юного врача", author="Михаил Булгаков")
        omni_review = {"id": 900, "url": "/review/900", "text": "<p>Хорошо.</p>",
                       "created_at": "2023-02-01T00:00:00",
                       "art_edition": {"url": "/book/8888888", "title": "Собачье сердце",
                                      "authors": [{"full_name": "Михаил Булгаков"}]}}
        omni_quote = {"id": 1, "text": "<p>Цитата</p>", "created_at": "2024-01-01T00:00:00",
                      "quote": {"quote_id": 10, "url": "/quote/10"},
                      "art_edition": {"url": "/book/8888888-sobache-serdce",
                                     "title": "Собачье сердце",
                                     "authors": [{"full_name": "Михаил Булгаков"}]}}
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[omni],
                                                        quotes=[omni_quote],
                                                        reviews=[omni_review])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"books": {"8888888": {"omnibus": true}}}', encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "bulgakov-sobache-serdtse.md").read_text(encoding="utf-8")
        assert "## Рецензия" in md
        assert "^quote_" not in md
        assert report["quotes_in_collections"] == 1
        # an omnibus is a collection, not an authored book: no author is claimed
        assert "author:" not in md

    def test_omnibus_exclusion_is_keyed_by_id_not_title(self, tmp_path):
        """Omnibus quote exclusion needs the quote's OWN edition id flagged.

        A sibling edition of the same omnibus work is not excluded: only the
        flagged edition's quotes are dropped. This pins the difference from the
        author strip below, which is id-keyed too but for the opposite reason.
        """
        omni = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/8888888",
                    title="Морфий. Записки юного врача", author="Михаил Булгаков")
        q = {"id": 1, "text": "<p>Цитата</p>", "created_at": "2024-01-01T00:00:00",
             "quote": {"quote_id": 10, "url": "/quote/10"},
             "art_edition": {"url": "/book/9999999-morfij",
                            "title": "Морфий. Записки юного врача",
                            "authors": [{"full_name": "Михаил Булгаков"}]}}
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[omni], quotes=[q])
        cur = tmp_path / "curation.jsonc"
        # the quote's edition (9999999) is NOT flagged; only 8888888 is
        cur.write_text('{"books": {"8888888": {"omnibus": "Морфий. Записки юного врача"}}}',
                      encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert report["quotes_in_collections"] == 0
        assert report["quotes_placed"] == 1
        # flagging the quote's own edition is what excludes it
        cur.write_text('{"books": {"9999999": {"omnibus": true}}}', encoding="utf-8")
        out2 = tmp_path / "out2"
        report2 = build_books(books_p, quotes_p, reviews_p, out2, curation_path=cur)
        assert report2["quotes_in_collections"] == 1

    def test_title_match_is_carried_but_author_strip_is_keyed_by_declared_id(self, tmp_path):
        """'Белые ночи. Бедные люди. Преступление и наказание' is an omnibus;
        'Белые ночи' is a real authored book that merely shares its main title.

        The omnibus name therefore comes off the DECLARED id only: a title match
        may not reach across and unname an authored sibling. Pinned against the
        corpus, where every omnibus id marks the very edition that carries no
        author and no quotes.
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
        # omnibus declared for this id: quote excluded, author stripped
        cur = tmp_path / "c.jsonc"
        cur.write_text('{"books": {"1000018782": {"omnibus": true}}}', encoding="utf-8")
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dostoevskiy-belye-nochi.md").read_text(encoding="utf-8")
        assert "^quote_" not in md
        assert "author:" not in md
        assert report["quotes_in_collections"] == 1
        # nothing declared: the same edition keeps its quotes and its author
        out2 = tmp_path / "out2"
        build_books(books_p, quotes_p, reviews_p, out2)
        md2 = (out2 / "dostoevskiy-belye-nochi.md").read_text(encoding="utf-8")
        assert "^quote_" in md2
        assert "author: Фёдор Достоевский" in md2

    def test_merges_section_folds_note_into_canonical(self, tmp_path):
        """merges {removed slug: canonical} replaces work-merges.json.

        The canonical may be named by slug OR by edition id: naming it by id is
        what makes the fold survive the collision renaming that two same-slug
        notes provably trigger (the real vayl/petr pair differs in author name
        order, so it collides before the merge would run).
        """
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1001474484",
                  title="Родная речь", author="Вайль Петр")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2])
        out = tmp_path / "books"
        # without the merge: two notes, both status none
        build_books(books_p, quotes_p, reviews_p, out)
        assert sorted(f.name for f in out.glob("*.md")) == [
            "dovlatov-zona.md", "petr-rodnaya-rech.md"]
        cur = tmp_path / "curation.jsonc"
        # fold zone into the other note, canonical named BY ID. The slug would be
        # author-first here; naming the canonical by id is what makes the fold
        # independent of what the slug ends up being after collision handling.
        cur.write_text('{\n  "merges": {"dovlatov-zona": "1001474484"},\n'
                      '  "books": {"1001474484": {"status": "read"}}\n}\n', encoding="utf-8")
        out2 = tmp_path / "out2"
        build_books(books_p, quotes_p, reviews_p, out2, curation_path=cur)
        names = sorted(f.name for f in out2.glob("*.md"))
        assert len(names) == 1
        md = (out2 / names[0]).read_text(encoding="utf-8")
        # the folded edition url stays so its links still resolve
        assert "1000699994" in md
        assert "status: read" in md

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

    def test_legacy_merges_section_still_folds(self, tmp_path):
        """Back-compat: a top-level `merges` section works unchanged (until the
        file flips to per-book arrays, both forms must build identically)."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1003248852",
                  title="Ленин. Пантократор солнечных пылинок", author="Лев Данилкин")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010727563",
                  title="Ленин", author="Данилкин Лев", my_mark=None)
        q = dict(Q1, id=70, quote={"quote_id": 700, "url": "/quote/700-lenin"},
                 art_edition={"url": "/book/1010727563-lenin", "title": "Ленин",
                             "authors": [{"full_name": "Лев Данилкин"}]})
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2],
                                                        quotes=[q], reviews=[])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{\n  "books": {"1003248852": {"weight": 16}},\n'
                      '  "merges": {"1010727563": "1003248852"}\n}\n', encoding="utf-8")
        out = tmp_path / "out"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert report["books"] == 1
        md = (out / "danilkin-lenin-pantokrator-solnechnykh-pylinok.md").read_text(encoding="utf-8")
        assert "1010727563" in md and "https://www.livelib.ru/quote/700" in md

    def test_external_section_classifies_links(self, tmp_path):
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        out = tmp_path / "books"
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"external": ["https://www.livelib.ru/quote/555-x"]}', encoding="utf-8")
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text("[q](https://www.livelib.ru/quote/555-x)",
                                      encoding="utf-8")
        from text_forge.wtd_books import validate_text_links
        res = validate_text_links(text_dir, out, external_path=cur)
        assert res["external"] == 1
        assert res["unresolved"] == []

    def test_links_section_resolves_foreign_id(self, tmp_path):
        """links {url: slug} still resolves an id that lives in no note."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"links": {"https://www.livelib.ru/book/1001474484-slug-hvost": "dovlatov-zona"}}',
                      encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text("[x](https://www.livelib.ru/book/1001474484)",
                                      encoding="utf-8")
        from text_forge.wtd_books import validate_text_links
        # the build emits link_map (what the notes declare + the curated links);
        # the validator consumes it, so a slug-suffixed curated url matches the
        # short url a text actually links
        res = validate_text_links(text_dir, out, link_mappings_path=report["link_map"])
        assert res["resolved"] == 1
        assert res["unresolved"] == []

    def test_reference_books_entry_gets_title_from_edition_resolver(self, tmp_path, monkeypatch):
        """reference-books entries store NO title/author: they are fetched."""
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"reference-books": {"1002971633": {}}}', encoding="utf-8")
        out = tmp_path / "books"
        monkeypatch.setattr(
            "text_forge.wtd_books.resolve_edition_cached",
            lambda bid, **kw: {"title": "Путешествие из Петербурга в Москву",
                              "author": "Александр Радищев", "source": "api"})
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "radishchev-puteshestvie-iz-peterburga-v-moskvu.md").read_text(encoding="utf-8")
        assert 'title: "Путешествие из Петербурга в Москву"' in md
        assert "status: none" in md

    def test_curated_link_key_is_never_nested_into_a_double_url(self, tmp_path):
        """A link key may be written absolute; mapping it through the url builder
        must not produce '/review/https://...' — such a key matches nothing and
        silently inflates the map."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"links": {"https://www.livelib.ru/review/5033995-ispoved": "some-note"}}',
                      encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert all("https://www.livelib.ru/https" not in k for k in report["link_map"]), \
            [k for k in report["link_map"] if "https://www.livelib.ru/https" in k]
        assert report["link_map"]["https://www.livelib.ru/review/5033995"] == "some-note"

    def test_curation_url_keeps_a_slug_suffixed_edition_url(self, tmp_path):
        """A few editions are only reachable in their long form; the export carries
        short ids only, so curation must be able to pin the url a note declares."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1007344816",
                  title="Что делать?", author="Николай Чернышевский")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2])
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{\n  // "Что делать?"\n'
                      '  "merges": {"1007344816": "dovlatov-zona"},\n'
                      '  "books": {"1007344816":\n'
                      '    {"url": "https://www.livelib.ru/book/1007344816-chto-delat'
                      '-nikolaj-chernyshevskij"}}\n}\n', encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert '  - "https://www.livelib.ru/book/1007344816-chto-delat-nikolaj-chernyshevskij"' in md

    def test_reference_books_query_the_id_so_the_build_can_resolve_it(self, tmp_path, monkeypatch):
        """The build must actually ask livelib for the id.

        Regression: the resolver was called without any query, so it never hit the
        search API and EVERY reference book fell back to 'unresolved' — a build
        that looks fine but silently loses the titles it was meant to fetch.
        """
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"reference-books": {"1000898792": {}}}', encoding="utf-8")
        out = tmp_path / "books"
        seen = []

        def fake(bid, *, cache_path=None, client=None, queries=()):
            seen.append((bid, tuple(queries)))
            return {"title": "Драйв. Что на самом деле нас мотивирует",
                    "author": "Дэниел Пинк", "source": "api"}
        monkeypatch.setattr("text_forge.wtd_books.resolve_edition_cached", fake)
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert seen == [("1000898792", ("1000898792",))], seen
        assert report["unresolved_reference_books"] == []

    def test_unresolved_reference_book_is_reported_and_gets_a_slug_title(self, tmp_path, monkeypatch):
        """An id livelib does not carry is warned about, and the note still gets a
        title — derived from the slug, never invented."""
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path)
        cur = tmp_path / "curation.jsonc"
        cur.write_text('{"reference-books": {"1002971633": {}}}', encoding="utf-8")
        out = tmp_path / "books"
        monkeypatch.setattr("text_forge.wtd_books.resolve_edition_cached",
                           lambda bid, **kw: {"title": "", "author": "", "source": "none"})
        report = build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        assert report["unresolved_reference_books"] == ["1002971633"]
        assert len(list(out.glob("*.md"))) == 1

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
