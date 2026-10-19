"""Tests for wtd_books: LiveLib JSON export → books/<slug>.md note-books."""

import json
import pathlib

import pytest

from text_forge.wtd_books import make_slug, group_export, render_note, build_books, validate_text_links


Q1 = {
    "id": 1,
    "text": "<p>Текст первой цитаты</p>",
    "created_at": "2024-03-01T10:00:00",
    "quote": {"quote_id": 100, "url": "/quote/100-zona-sergej-dovlatov"},
    "art_edition": {"url": "/book/1000699994-zona-sergej-dovlatov", "title": "Зона",
                    "authors": [{"full_name": "Сергей Довлатов"}]},
}
Q2 = {
    "id": 2,
    "text": "<p>Вторая цитата, более ранняя</p>",
    "created_at": "2023-01-15T09:00:00",
    "quote": {"quote_id": 101, "url": "/quote/101-zona-sergej-dovlatov"},
    "art_edition": {"url": "/book/1000699994-zona-sergej-dovlatov", "title": "Зона",
                    "authors": [{"full_name": "Сергей Довлатов"}]},
}
R1 = {
    "id": 900,
    "url": "/review/900-zona-sergej-dovlatov",
    "text": "<p>Отличная книга.</p>",
    "created_at": "2023-02-01T00:00:00",
    "art_edition": {"url": "/book/1000699994-zona-sergej-dovlatov", "title": "Зона",
                    "authors": [{"full_name": "Сергей Довлатов"}]},
}
BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}


class TestGroupExport:
    def group(self, quotes=(Q1, Q2), reviews=(R1,)):
        entries, own = group_export(books=[BOOK_ZONA], quotes=list(quotes), reviews=list(reviews))
        return entries, own

    def test_quotes_grouped_by_book(self):
        entries, own = self.group()
        assert len(entries) == 1 and own == []
        assert entries[0]["book"]["title"] == "Зона"

    def test_quotes_sorted_by_created_at(self):
        entries, _ = self.group()
        assert [q["id"] for q in entries[0]["quotes"]] == [2, 1]

    def test_review_attached_to_book(self):
        entries, _ = self.group()
        assert entries[0]["review"]["id"] == 900

    def test_book_without_review_gets_none(self):
        entries, _ = self.group(quotes=(Q2,), reviews=())
        assert entries[0]["review"] is None


class TestRenderNote:
    def make_entry(self):
        return group_export(books=[BOOK_ZONA], quotes=[Q1, Q2], reviews=[R1])[0][0]

    def test_frontmatter_fields(self):
        md = render_note(self.make_entry())
        assert md.startswith("---\n")
        assert "title: Зона" in md
        assert "author: Сергей Довлатов" in md
        assert "tags:" in md and "book" in md
        assert 'livelib_book: "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov"' in md

    def test_review_section_with_anchor(self):
        md = render_note(self.make_entry())
        assert "## Рецензия" in md
        assert "Отличная книга." in md
        assert 'livelib_review: "https://www.livelib.ru/review/900-zona-sergej-dovlatov"' in md

    def test_quotes_anchored_in_order(self):
        md = render_note(self.make_entry())
        assert md.count("^quote_") == 2
        # older quote gets lower number
        i2, i1 = md.find("^quote_1"), md.find("^quote_2")
        assert 0 < i2 < i1

    def test_no_quotes_header(self):
        """No empty section header: quotes are self-evident blockquotes."""
        md = render_note(self.make_entry())
        assert "## Цитаты" not in md

    def test_invalid_author_omitted_from_frontmatter(self):
        """Rating-garbage author ('4,6') must not appear in frontmatter."""
        entry = {"book": {"book_url": "https://www.livelib.ru/book/1000507758",
                          "title": "Лунная пыль. Я, робот. Стальные пещеры",
                          "author": "4,6", "status": "read", "my_mark": None},
                 "slug": "lunnaya-pyl", "quotes": [], "review": None}
        md = render_note(entry)
        assert "author:" not in md
        assert "title: Лунная пыль" in md

    def test_author_override_beats_omnibus_strip(self):
        """User-curated author wins even for a declared omnibus (Булгаков)."""
        entry = {"book": {"book_url": "https://www.livelib.ru/book/1000191786",
                          "title": "Собачье сердце. Записки юного врача",
                          "author": "Михаил Булгаков", "status": "read", "my_mark": None},
                 "slug": "bulgakov-sobache-serdtse", "quotes": [], "review": None}
        md = render_note(entry)
        assert "author: Михаил Булгаков" in md

    def test_own_note_has_no_status(self):
        """A work that is not on any shelf has no status line."""
        _, own = group_export(books=[BOOK_ZONA], quotes=[dict(Q1, art_edition={
            "url": "/book/911-unknown-book", "title": "Незнакомая книга",
            "authors": [{"full_name": "Незнакомый Автор"}]})], reviews=[])
        own_entry = {"book": {"book_url": "https://www.livelib.ru/book/911-unknown-book",
                              "title": "Незнакомая книга", "author": "Незнакомый Автор",
                              "status": None, "my_mark": None},
                     "slug": "avtor-neznakomaya-kniga", "quotes": own, "review": None}
        md = render_note(own_entry)
        assert "status:" not in md
        assert "^quote_1" in md

    def test_quote_is_blockquote_without_heading(self):
        """No synthetic quote titles: the quote text itself, as blockquote with block-id."""
        md = render_note(self.make_entry())
        assert "###" not in md
        assert "> Вторая цитата, более ранняя" in md
        # block-id sits on the blockquote line (Obsidian anchors the quote block)
        assert "> Вторая цитата, более ранняя ^quote_1" in md

    def test_quote_has_livelib_url_and_text(self):
        md = render_note(self.make_entry())
        assert 'livelib: https://www.livelib.ru/quote/101' in md
        assert "Вторая цитата, более ранняя" in md

    def test_quote_livelib_attr_uses_short_url(self):
        """Quote attribute is the stable short form /quote/<id> (livelib redirects)."""
        md = render_note(self.make_entry())
        assert 'livelib: https://www.livelib.ru/quote/101' in md
        assert 'livelib.ru/quote/101-zona' not in md

    def test_book_without_review_omits_section(self):
        entries, _ = group_export(books=[BOOK_ZONA], quotes=[Q2], reviews=[])
        md = render_note(entries[0])
        assert "## Рецензия" not in md

    def test_quote_without_livelib_meta_omits_url(self):
        """8 real quotes lack quote.url (added outside the site) — still exported."""
        entry, _ = group_export(books=[BOOK_ZONA], quotes=[dict(Q2, quote=None)], reviews=[])
        md = render_note(entry[0])
        assert "Вторая цитата, более ранняя" in md
        assert "^quote_1" in md
        assert "livelib:" not in md

    def test_html_stripped_from_quote_text(self):
        md = render_note(self.make_entry())
        assert "<p>" not in md


class TestValidateTextLinks:
    def make_books_dir(self, tmp_path):
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([Q1, Q2], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text(json.dumps([R1], ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        return out

    def write_text(self, tmp_path, content):
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "chapter.md").write_text(content, encoding="utf-8")
        return text_dir

    def test_resolves_quote_review_book_links(self, tmp_path):
        books_dir = self.make_books_dir(tmp_path)
        text_dir = self.write_text(tmp_path, (
            "[цитата](https://www.livelib.ru/quote/101-zona-sergej-dovlatov) "
            "[рецензия](https://www.livelib.ru/review/900-zona-sergej-dovlatov) "
            "[книга](https://www.livelib.ru/book/1000699994)"))
        report = validate_text_links(text_dir, books_dir)
        assert report["total"] == 3
        assert report["resolved"] == 3
        assert report["unresolved"] == []

    def test_unresolved_link_reported(self, tmp_path):
        books_dir = self.make_books_dir(tmp_path)
        text_dir = self.write_text(tmp_path,
            "[цитата](https://www.livelib.ru/quote/555-neizvestnaya)")
        report = validate_text_links(text_dir, books_dir)
        assert report["resolved"] == 0
        assert len(report["unresolved"]) == 1
        assert report["unresolved"][0]["url"].endswith("555-neizvestnaya")

    def test_external_links_classified(self, tmp_path):
        """Old-format quotes (site shows, API 404) are external, not errors."""
        books_dir = self.make_books_dir(tmp_path)
        text_dir = self.write_text(tmp_path,
            "[цитата](https://www.livelib.ru/quote/555-neizvestnaya)")
        ext = tmp_path / "external.json"
        ext.write_text(json.dumps(["https://www.livelib.ru/quote/555-neizvestnaya"]), encoding="utf-8")
        report = validate_text_links(text_dir, books_dir, external_path=ext)
        assert report["resolved"] == 0
        assert report["unresolved"] == []
        assert report["external"] == 1

    def test_work_links_resolve(self, tmp_path):
        """5 work links in WTD — resolve like book links when id matches a note."""
        books_dir = self.make_books_dir(tmp_path)
        text_dir = self.write_text(tmp_path,
            "[произведение](https://www.livelib.ru/work/1000699994)")
        report = validate_text_links(text_dir, books_dir)
        assert report["resolved"] == 1


class TestBuildBooks:
    def test_writes_one_note_per_unique_book(self, tmp_path):
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([Q1, Q2], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text(json.dumps([R1], ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        files = list(out.glob("*.md"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8").startswith("---\n")
        assert report["books"] == 1 and report["quotes_placed"] == 2

    def test_report_counts_own_notes_for_unknown_works(self, tmp_path):
        orphan = dict(Q1, art_edition={"url": "/book/999-unknown", "title": "Х", "authors": []})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([orphan], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        report = build_books(books_p, quotes_p, reviews_p, tmp_path / "books")
        assert report["own_notes"] == 1
        assert report["quotes_unmatched"] == 0

    def test_matches_edition_to_shelf_book_by_title_and_author(self, tmp_path):
        """Quotes from other editions of the same work merge into the shelf book note."""
        edition_quote = dict(Q1, art_edition={"url": "/book/7777777-zona-izdanie-2", "title": "Зона",
                                              "authors": [{"full_name": "Сергей Довлатов"}]})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([edition_quote], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        assert sorted(f.name for f in out.glob("*.md")) == ["dovlatov-zona.md"]
        assert report["quotes_placed"] == 1
        assert report["quotes_unmatched"] == 0

    def test_unmatched_edition_stays_own_note(self, tmp_path):
        """A genuinely unknown work keeps its own note for manual review."""
        orphan = dict(Q1, art_edition={"url": "/book/999-unknown-book", "title": "Незнакомая книга",
                                       "authors": [{"full_name": "Незнакомый Автор"}]})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([orphan], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        assert len(list(out.glob("*.md"))) == 2
        assert report["quotes_unmatched"] == 0  # placed into its own note
        assert report["own_notes"] == 1

    def test_matches_book_by_id_when_slugs_differ(self, tmp_path):
        """HTML export has bare /book/<id>; API has /book/<id>-<slug>."""
        book_bare = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([book_bare], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([Q1], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        report = build_books(books_p, quotes_p, reviews_p, tmp_path / "books")
        assert report["quotes_placed"] == 1
        assert report["quotes_unmatched"] == 0

    def test_slug_collision_gets_book_id_suffix(self, tmp_path):
        """Different works of the same author keep distinct slugs (no collision)."""
        b1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        b2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/7777777")
        b2["title"] = "Зона. Другая книга"  # different work
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([b1, b2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        names = sorted(f.name for f in out.glob("*.md"))
        assert names == ["dovlatov-zona-drugaya-kniga.md", "dovlatov-zona.md"]

    def test_own_notes_grouped_by_work_not_edition(self, tmp_path):
        """Several editions of the same unknown work -> ONE own note."""
        q1 = dict(Q1, art_edition={"url": "/book/911-unknown-book", "title": "Незнакомая книга",
                                   "authors": [{"full_name": "Незнакомый Автор"}]})
        q2 = dict(Q2, art_edition={"url": "/book/912-unknown-book-izdanie-2", "title": "Незнакомая книга",
                                   "authors": [{"full_name": "Незнакомый Автор"}]})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([q1, q2], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        files = list(out.glob("*.md"))
        assert len(files) == 2  # zona + one own note
        own = [f for f in files if f.name != "dovlatov-zona.md"][0]
        assert own.read_text(encoding="utf-8").count("^quote_") == 2
        assert report["own_notes"] == 1

    def test_omnibus_quotes_not_placed_but_review_stays(self, tmp_path):
        """Quotes from a declared omnibus edition fail the book-quote rule;
        the omnibus review is fine and stays."""
        omni = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/8888888",
                    title="Собачье сердце. Записки юного врача", author="Михаил Булгаков")
        omni_review = dict(R1, art_edition={"url": "/book/8888888", "title": "Собачье сердце",
                                            "authors": [{"full_name": "Михаил Булгаков"}]})
        coll = tmp_path / "collections.json"
        coll.write_text(json.dumps({"https://www.livelib.ru/book/8888888": "omnibus"}, ensure_ascii=False),
                        encoding="utf-8")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        omni_quote = dict(Q1, art_edition={"url": "/book/8888888-sobache-serdce",
                                           "title": "Собачье сердце",
                                           "authors": [{"full_name": "Михаил Булгаков"}]})
        books_p.write_text(json.dumps([omni], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([omni_quote], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text(json.dumps([omni_review], ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out, collections_path=coll)
        files = list(out.glob("*.md"))
        assert len(files) == 1
        md = files[0].read_text(encoding="utf-8")
        assert "## Рецензия" in md
        assert "^quote_" not in md
        assert report["quotes_in_collections"] == 1

    def test_work_key_uses_main_title_not_full(self, tmp_path):
        """«Война и мир» / «Война и мир (комплект из 2 книг)» / «Война и мир. В 4 томах»
        are ONE work -> one note, no -<id> suffix files."""
        editions = [{"book_url": f"https://www.livelib.ru/book/100{i:05d}",
                     "title": t, "author": "Лев Толстой", "status": "read", "my_mark": None}
                    for i, t in enumerate(["Война и мир", "Война и мир (комплект из 2 книг)",
                                           "Война и мир. В 4 томах", "Война и мир. В 4 томах. Том 1-4"])]
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps(editions, ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        files = sorted(f.name for f in out.glob("*.md"))
        assert files == ["tolstoy-voyna-i-mir.md"]
        assert report["books"] == 1

    def test_work_key_name_order_handled_by_curation(self):
        """Name-order variants («Петр Вайль» vs «Вайль Петр») are NOT heuristically
        merged — they are resolved explicitly via _curation/work-merges.json."""
        from text_forge.wtd_books import _work_key
        assert _work_key("Родная речь. Уроки изящной словесности", "Петр Вайль, Александр Генис") != \
               _work_key("Родная речь. Уроки изящной словесности", "Вайль Петр, Генис Александр")

    def test_slug_collision_extends_with_title_words_not_id(self, tmp_path):
        """«Бегство из рая» и «Свободный человек» both cut to «Лев Толстой» —
        collision extends with title words, never with numeric id."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1007290363",
                  title="Лев Толстой: Бегство из рая", author="Павел Басинский")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010116129",
                  title="Лев Толстой. Свободный человек", author="Павел Басинский")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1, e2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        names = sorted(f.name for f in out.glob("*.md"))
        assert names == ["basinskiy-lev-tolstoy-begstvo-iz-raya.md",
                         "basinskiy-lev-tolstoy-svobodnyy-chelovek.md"]

    def test_duplicate_quote_across_merged_editions_placed_once(self, tmp_path):
        """Same quote reachable via two editions of one work — rendered once."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/7777777", my_mark=None)
        q_ed1 = dict(Q1, quote={"quote_id": 101, "url": "/quote/101-zona"})
        q_ed2 = dict(Q1, id=99, quote={"quote_id": 101, "url": "/quote/101-zona"},
                     art_edition={"url": "/book/7777777", "title": "Зона",
                                  "authors": [{"full_name": "Сергей Довлатов"}]})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1, e2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([q_ed1, q_ed2], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert md.count("/quote/101") == 1
        assert report["quotes_placed"] == 1

    def test_placed_quotes_equal_unique_input(self, tmp_path):
        """No double counting: placed == unique quotes, even with manual merges."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1001474484",
                  title="Родная речь", author="Вайль Петр")  # name-order variant
        q1 = dict(Q1, art_edition={"url": "/book/1001474484", "title": "Родная речь",
                                   "authors": [{"full_name": "Петр Вайль"}]})
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1, e2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([Q1, Q2, q1], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        total_q = report["quotes_placed"] + report["quotes_in_collections"]
        assert total_q == 3

    def test_manual_work_merges_and_link_mappings(self, tmp_path):
        """Curation files: work-merges.json merges stubborn duplicates;
        link-mappings.json resolves ids that differ from note editions."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994",
                  title="Родная речь", author="Петр Вайль")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        merges = tmp_path / "work-merges.json"
        merges.write_text(json.dumps([{"into": "vayl-rodnaya-rech", "extra": "https://www.livelib.ru/book/1001474484",
                                       "title": "Родная речь. Уроки изящной словесности",
                                       "author": "Петр Вайль, Александр Гениис"}], ensure_ascii=False), encoding="utf-8")
        mappings = tmp_path / "link-mappings.json"
        mappings.write_text(json.dumps({
            "https://www.livelib.ru/book/1001474484": "vayl-rodnaya-rech"}, ensure_ascii=False), encoding="utf-8")
        report = build_books(books_p, quotes_p, reviews_p, out,
                             work_merges_path=merges, link_mappings_path=mappings)
        md = (out / "vayl-rodnaya-rech.md").read_text(encoding="utf-8")
        assert "1001474484" in md
        text_dir = tmp_path / "text"
        text_dir.mkdir(exist_ok=True)
        (text_dir / "c.md").write_text("[x](https://www.livelib.ru/book/1001474484)", encoding="utf-8")
        res = validate_text_links(text_dir, out, link_mappings_path=mappings)
        assert res["resolved"] == 1

    def test_work_key_does_not_merge_different_works_sharing_prefix(self, tmp_path):
        """«Лев Толстой: Бегство из рая» и «Лев Толстой. Свободный человек» —
        разные работы Басинского, несмотря на общий префикс титула."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1007290363",
                  title="Лев Толстой: Бегство из рая", author="Павел Басинский")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010116129",
                  title="Лев Толстой. Свободный человек", author="Павел Басинский")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1, e2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        names = sorted(f.name for f in out.glob("*.md"))
        assert len(names) == 2

    def test_merged_editions_keep_their_livelib_urls(self, tmp_path):
        """Every merged edition URL stays in the note (validator + converter need them)."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/7777777", my_mark=None)
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1, e2], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "livelib_editions:" in md
        assert "7777777" in md

    def test_shelf_editions_of_same_work_merge_into_one_note(self, tmp_path):
        """Six read editions of Тяжелый песок = ONE book note with all their quotes."""
        editions = [{"book_url": f"https://www.livelib.ru/book/100{i:04d}",
                     "title": "Тяжелый песок", "author": "Анатолий Рыбаков",
                     "status": "read", "my_mark": 5 if i == 0 else None} for i in range(6)]
        q_eds = [dict(Q1, id=i, text=f"<p>Цитата номер {i}</p>",
                      created_at=f"2024-03-0{i+1}T10:00:00",
                      quote={"quote_id": 200 + i, "url": f"/quote/200{i}-tyazhelyy-pesok"},
                      art_edition={"url": f"/book/100{i:04d}", "title": "Тяжелый песок",
                                   "authors": [{"full_name": "Анатолий Рыбаков"}]})
                 for i in range(6)]
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps(editions, ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps(q_eds, ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        report = build_books(books_p, quotes_p, reviews_p, out)
        files = list(out.glob("*.md"))
        assert len(files) == 1
        md = files[0].read_text(encoding="utf-8")
        assert md.count("^quote_") == 6
        assert report["books"] == 1


class TestMakeSlug:
    def test_frankl_example(self):
        """Author surname + title without subtitle, transliterated."""
        slug = make_slug("Сказать жизни «Да»: психолог в концлагере", "Виктор Франкл")
        assert slug == "frankl-skazat-zhizni-da"

    def test_single_word_title(self):
        assert make_slug("Лавр", "Евгений Водолазкин") == "vodolazkin-lavr"

    def test_author_with_two_words_uses_surname(self):
        assert make_slug("Зона", "Сергей Довлатов") == "dovlatov-zona"

    def test_latin_title_stays(self):
        assert make_slug("Pro Git", "Скотт Чакон") == "chakon-pro-git"

    def test_strips_punctuation(self):
        slug = make_slug("Не могу, Господи, жить без Тебя! Книга о молитве", "Антоний Сурожский")
        assert slug == "surozhskiy-ne-mogu-gospodi-zhit-bez-tebya"

    def test_no_double_hyphens(self):
        slug = make_slug("Я, Робот", "Айзек Азимов")
        assert "--" not in slug

    def test_author_initials_are_skipped(self):
        assert make_slug("Не молчи, или Книга для тех, кто хочет получать ответы", "Максимов А.") == \
            "maksimov-ne-molchi-ili-kniga-dlya-tekh-kto-khochet-poluchat-otvety"

    def test_author_digit_pseudonym_skipped(self):
        assert make_slug("Стратегическая психология глобализации. Психология человеческого капитала", "5 Юрьев") == \
            "yurev-strategicheskaya-psikhologiya-globalizatsii"

    def test_author_compound_initials_skipped(self):
        assert make_slug("Сугубо доверительно. Посол в Вашингтоне при шести президентах США (1962-1986 гг.)", "Добрынин А.Ф.") == \
            "dobrynin-sugubo-doveritelno"

    def test_multi_author_takes_first_author_surname(self):
        assert make_slug("Я чувствую… Что? Гид по эмоциональному интеллекту",
                         "Мария Горина, Антипова Юлия, Марченко Елена") == "gorina-ya-chuvstvuyu-chto"
        assert make_slug("Родная речь. Уроки изящной словесности", "Петр Вайль, Александр Генис") == \
            "vayl-rodnaya-rech"

    def test_digit_only_author_omitted_from_slug(self):
        """Author '5' or rating '4,6' (no surname parsed) must not appear in the filename."""
        assert make_slug("Стратегическая психология глобализации. Психология человеческого капитала", "5") == \
            "strategicheskaya-psikhologiya-globalizatsii"
        assert make_slug("Лунная пыль. Я, робот. Стальные пещеры", "4,6") == \
            "lunnaya-pyl"  # omnibus: first work, full title stays in frontmatter
        assert make_slug("Упрямый город. Блокада 1941–1944", "4,5") == \
            "upryamyy-gorod"

    def test_dot_subtitle_cut(self):
        assert make_slug("Стратегическая психология глобализации. Психология человеческого капитала", "5 Юрьев") == \
            "yurev-strategicheskaya-psikhologiya-globalizatsii"

    def test_leading_initials_title_not_cut_to_empty(self):
        assert make_slug("П. А. Столыпин. Воспоминания о моем отце", "Мария Бок") == \
            "bok-p-a-stolypin-vospominaniya-o-moem-ottse"
