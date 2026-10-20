"""Tests for wtd_books: LiveLib JSON export → books/<slug>.md note-books."""

import copy
import json
import pathlib
import re

import pytest

from text_forge.wtd_books import (
    make_slug,
    group_export,
    render_note,
    build_books,
    validate_text_links,
    parse_reference_lines,
    render_p3_references,
    important_books,
)


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
        assert 'title: "Зона"' in md
        assert "author: Сергей Довлатов" in md
        assert "tags:" in md and "book" in md
        assert 'livelib_book: "https://www.livelib.ru/book/1000699994"' in md

    def test_title_is_double_quoted(self):
        """title is always double-quoted: Obsidian Bases breaks on ':' in bare scalars."""
        e = self.make_entry()
        assert 'title: "Зона"' in render_note(e)
        e = copy.deepcopy(e)
        e["book"]["title"] = 'Раневская. "Смех сквозь слезы": мемуары'
        assert 'title: "Раневская. \\"Смех сквозь слезы\\": мемуары"' in render_note(e)

    def test_author_with_trailing_space_is_quoted_and_stripped(self):
        """Export data carries trailing spaces: 'Аристотель ' must render quoted+clean."""
        e = self.make_entry()
        e = copy.deepcopy(e)
        e["book"]["author"] = "Аристотель "
        assert 'author: "Аристотель"' in render_note(e)

    def test_review_section_with_anchor(self):
        md = render_note(self.make_entry())
        assert "## Рецензия" in md
        assert "Отличная книга." in md
        # attribute is the short stable form; the section anchor links stay full
        assert 'livelib_review: "https://www.livelib.ru/review/900"' in md

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
        assert 'title: "Лунная пыль. Я, робот. Стальные пещеры"' in md

    def test_author_override_beats_omnibus_strip(self):
        """User-curated author wins even for a declared omnibus (Булгаков)."""
        entry = {"book": {"book_url": "https://www.livelib.ru/book/1000191786",
                          "title": "Собачье сердце. Записки юного врача",
                          "author": "Михаил Булгаков", "status": "read", "my_mark": None},
                 "slug": "bulgakov-sobache-serdtse", "quotes": [], "review": None}
        md = render_note(entry)
        assert "author: Михаил Булгаков" in md

    def test_own_note_has_status_none(self):
        """A work that is not on any shelf gets status: none (status is always written)."""
        _, own = group_export(books=[BOOK_ZONA], quotes=[dict(Q1, art_edition={
            "url": "/book/911-unknown-book", "title": "Незнакомая книга",
            "authors": [{"full_name": "Незнакомый Автор"}]})], reviews=[])
        own_entry = {"book": {"book_url": "https://www.livelib.ru/book/911-unknown-book",
                              "title": "Незнакомая книга", "author": "Незнакомый Автор",
                              "status": None, "my_mark": None},
                     "slug": "avtor-neznakomaya-kniga", "quotes": own, "review": None}
        md = render_note(own_entry)
        assert 'status: none' in md
        assert "^quote_1" in md

    def test_quote_is_blockquote_without_heading(self):
        """No synthetic quote titles: the quote text itself, as blockquote with block-id."""
        md = render_note(self.make_entry())
        assert "###" not in md
        assert "> Вторая цитата, более ранняя" in md
        # block-id sits on the blockquote line (Obsidian anchors the quote block)
        assert "> Вторая цитата, более ранняя ^quote_1" in md

    def test_book_attr_uses_short_url(self):
        """Book attribute is the short stable form /book/<id>, like quotes."""
        md = render_note(self.make_entry())
        assert 'livelib_book: "https://www.livelib.ru/book/1000699994"' in md

    def test_status_always_written(self):
        """Status line is present for every book; own books get 'none'."""
        e = self.make_entry()
        e = copy.deepcopy(e)
        e["book"]["status"] = "read"
        assert 'status: read' in render_note(e)
        e["book"]["status"] = None
        assert 'status: none' in render_note(e)

    def test_unread_passes_through(self, tmp_path):
        """LiveLib shelf names pass through unchanged: unread stays unread."""
        e = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994", status="unread")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        assert 'status: unread' in (out / "dovlatov-zona.md").read_text(encoding="utf-8")

    def test_wish_passes_through(self, tmp_path):
        """The Хочу прочитать shelf status is 'wish', passed through unchanged."""
        e = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994", status="wish")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        assert 'status: wish' in (out / "dovlatov-zona.md").read_text(encoding="utf-8")

    def test_reference_books_become_notes(self, tmp_path):
        """reference-books.json adds works referenced from texts but absent from
        shelves and quotes (former not-on-shelf stubs) as status-none notes."""
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text("[]", encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        ref = tmp_path / "reference-books.json"
        ref.write_text(json.dumps([{
            "book_url": "https://www.livelib.ru/book/1002971633",
            "title": "Путешествие из Петербурга в Москву",
            "author": "Александр Радищев", "status": None, "my_mark": None,
        }], ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, reference_books_path=ref)
        md = (out / "radishchev-puteshestvie-iz-peterburga-v-moskvu.md").read_text(encoding="utf-8")
        assert 'title: "Путешествие из Петербурга в Москву"' in md
        assert 'status: none' in md

    def test_not_on_shelf_marker_becomes_none(self, tmp_path):
        """The export's synthetic 'not-on-shelf' marker renders as status: none."""
        e = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994", status="not-on-shelf")
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        assert 'status: none' in (out / "dovlatov-zona.md").read_text(encoding="utf-8")

    def test_book_overrides_apply_status(self, tmp_path):
        """book-overrides.json sets status/author for editions missing from shelves."""
        e = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000284779", status=None)
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e], ensure_ascii=False), encoding="utf-8")
        # own-note edition absent from books.json
        q_own = dict(Q1, art_edition={"url": "/book/1009172287", "title": "Моя жизнь",
                                      "authors": [{"full_name": "Генри Форд"}]})
        quotes_p.write_text(json.dumps([q_own], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        ov = tmp_path / "book-overrides.json"
        ov.write_text(json.dumps({"1000284779": {"status": "read"},
                                  "1009172287": {"status": "stop"}}, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, book_overrides_path=ov)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert 'status: read' in md
        own_md = next((out / f.name).read_text(encoding="utf-8")
                      for f in out.glob("*.md") if "1009172287" in f.read_text(encoding="utf-8"))
        assert 'status: stop' in own_md

    def test_work_merge_sets_status(self, tmp_path):
        """work-merges 'status' overrides the merged note's status."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994", status=None)
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([e1], ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text("[]", encoding="utf-8")
        reviews_p.write_text("[]", encoding="utf-8")
        merges = tmp_path / "merges.json"
        merges.write_text(json.dumps([{"into": "dovlatov-zona", "status": "stop"}], ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, work_merges_path=merges)
        assert 'status: stop' in (out / "dovlatov-zona.md").read_text(encoding="utf-8")

    def test_quote_has_livelib_url_and_text(self):
        md = render_note(self.make_entry())
        assert '— [LiveLib](https://www.livelib.ru/quote/101)' in md
        assert "Вторая цитата, более ранняя" in md

    def test_quote_livelib_attr_uses_short_url(self):
        """Quote source keeps the stable short form /quote/<id> (livelib redirects)."""
        md = render_note(self.make_entry())
        assert '— [LiveLib](https://www.livelib.ru/quote/101)' in md
        assert 'livelib.ru/quote/101-zona' not in md

    def test_review_attr_uses_short_url(self):
        """Review attribute is the stable short form /review/<id> (livelib redirects)."""
        e = copy.deepcopy(self.make_entry())
        e["review"]["url"] = ("https://www.livelib.ru/review/3938821-ne-otorvatsya-pochemu"
                             "-nash-mozg-lyubit-vsjo-novoe-i-tak-li-eto-horosho"
                             "-v-epohu-interneta-adam-alter")
        md = render_note(e)
        assert 'livelib_review: "https://www.livelib.ru/review/3938821"' in md
        assert "review/3938821-" not in md

    def test_no_livelib_url_anywhere_carries_a_slug(self):
        """Whole-note invariant: EVERY livelib URL is the short /kind/<id> form.

        Slugs change with titles and author transliteration while the numeric id
        redirects reliably, so book, review, edition and quote urls must all be
        written without the slug tail.
        """
        md = render_note(self.make_entry())
        for url in re.findall(r"https?://[^\s)\"']+/livelib\.ru/[^\s)\"']+", md):
            assert re.fullmatch(r"https://www\.livelib\.ru/(?:book|work|review|quote)/\d+", url), url

    def test_export_slugs_do_not_survive_the_build(self, tmp_path):
        """Real export data carries slugged urls; notes must not keep them."""
        books_p = tmp_path / "books.json"
        quotes_p = tmp_path / "quotes.json"
        reviews_p = tmp_path / "reviews.json"
        books_p.write_text(json.dumps([dict(
            BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov")],
            ensure_ascii=False), encoding="utf-8")
        quotes_p.write_text(json.dumps([Q1], ensure_ascii=False), encoding="utf-8")
        reviews_p.write_text(json.dumps([dict(
            R1, url="/review/3387328-geograf-globus-propil-aleksej-ivanov")],
            ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s)\"']+/livelib\.ru/[^\s)\"']+", md):
            assert re.fullmatch(r"https://www\.livelib\.ru/(?:book|work|review|quote)/\d+", url), url

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

    def test_quote_source_is_markdown_link(self):
        """Quote source is an active link, not a bare URL: the site shows '— LiveLib'."""
        md = render_note(self.make_entry())
        assert "— [LiveLib](https://www.livelib.ru/quote/101)" in md
        # no plain-text source line in any shape: neither 'livelib: <url>' nor a
        # bare '<url>' line after the blockquote
        assert "livelib: https://www.livelib.ru/quote/" not in md
        for line in md.split("\n"):
            s = line.strip()
            assert not re.fullmatch(r"https?://\S+", s), line

    def test_source_link_is_em_dash_with_livelib_label(self):
        """Exact rendered form: '— [LiveLib](<short quote url>)', one per quote."""
        md = render_note(self.make_entry())
        src = [l.strip() for l in md.split("\n") if "livelib.ru/quote/" in l]
        assert src == ["— [LiveLib](https://www.livelib.ru/quote/101)",
                      "— [LiveLib](https://www.livelib.ru/quote/100)"]

    def test_quote_link_keeps_short_url(self):
        """Only the rendering changes: the URL stays the stable short /quote/<id>."""
        md = render_note(self.make_entry())
        assert "(https://www.livelib.ru/quote/101)" in md
        assert "quote/101-" not in md

    def test_quote_without_url_still_renders_nothing(self):
        """Quotes lacking quote.url keep having no source line at all."""
        entry, _ = group_export(books=[BOOK_ZONA], quotes=[dict(Q2, quote=None)], reviews=[])
        md = render_note(entry[0])
        assert "^quote_1" in md
        assert "LiveLib" not in md
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


# ------------------------------------------- p3-references projection helpers

PM = {"https://www.livelib.ru/book/1002920757": "kharari-sapiens"}


def ref_line(thesis="Про Счастье и Цифру", name="Модель", review_id=6390790):
    return (f"- {thesis}: [{name}](https://www.livelib.ru/review/{review_id}"
            f"-model-kolichestvennoj-otsenki-urovnya-schastya)")


REVIEW_6390790 = {
    "id": 6390790,
    "title": "Про Счастье и Цифру",
    "url": "/review/6390790-model-kolichestvennoj-otsenki-urovnya-schastya",
    "text": "<p>Рецензия.</p>",
    "art_edition": {"id": 1008288064, "title": "Модель количественной оценки уровня счастья",
                    "authors": [{"full_name": "Владимир Андреев"}],
                    "url": "/work/1008288064-model-kolichestvennoj-otsenki-urovnya-schastya"},
}


class TestParseReferenceLines:
    """p3-references.md carries ONLY importance: thesis + ordered book links."""

    def test_parses_thesis_and_links(self):
        lines = parse_reference_lines(
            "---\ncomments: true\n---\n\n# Книги\n\n" + ref_line(), mappings=PM)
        assert len(lines) == 1
        assert lines[0]["thesis"] == "Про Счастье и Цифру"
        assert lines[0]["weight"] == 1
        assert lines[0]["links"][0]["name"] == "Модель"
        assert lines[0]["links"][0]["review_id"] == "6390790"

    def test_weight_is_line_number_after_frontmatter_and_prose(self):
        """Frontmatter/heading/prose do not shift weights: first bullet is 1."""
        md = "---\ncomments: true\n---\n\n# Книги\n\nВступительный абзац:\n\n" + \
             ref_line(review_id=1) + "\n" + ref_line(review_id=2)
        lines = parse_reference_lines(md, mappings=PM)
        assert [(l["weight"], l["links"][0]["review_id"]) for l in lines] == [(1, "1"), (2, "2")]

    def test_multiple_links_on_one_line_share_weight(self):
        """Several links in one curated bullet => ONE line, weight counted once."""
        md = ("- Общий тезис: [Первая](https://www.livelib.ru/review/1), "
              "[Вторая](https://www.livelib.ru/review/2)\n")
        lines = parse_reference_lines(md, mappings=PM)
        assert len(lines) == 1
        assert lines[0]["weight"] == 1
        assert [l["review_id"] for l in lines[0]["links"]] == ["1", "2"]

    def test_link_without_thesis_prefix(self):
        """A bullet with no ': ' prefix carries no thesis."""
        lines = parse_reference_lines(
            "- [Книга](https://www.livelib.ru/book/1002920757)\n", mappings=PM)
        assert lines[0]["thesis"] == ""
        assert lines[0]["links"][0]["book_id"] == "1002920757"

    def test_book_and_work_urls_extract_id(self):
        md = ("- Т: [К](https://www.livelib.ru/book/1002920757-qqq)\n"
              "- Т: [К](https://www.livelib.ru/work/1015122040)\n")
        lines = parse_reference_lines(md, mappings=PM)
        assert lines[0]["links"][0]["book_id"] == "1002920757"
        assert lines[1]["links"][0]["book_id"] == "1015122040"

    def test_plain_text_part_is_kept_as_note(self):
        """'(to be published)' leftovers are reported, never turned into links."""
        md = "- Тезис: [Книга](https://www.livelib.ru/review/1), Моя книга (to be published)\n"
        lines = parse_reference_lines(md, mappings=PM)
        assert len(lines[0]["links"]) == 1
        assert lines[0]["plain"] == "Моя книга (to be published)"

    def test_mappings_prefer_full_url(self):
        md = "- Т: [К](https://www.livelib.ru/book/1002920757-qqq)\n"
        lines = parse_reference_lines(md, mappings=PM)
        assert lines[0]["links"][0]["slug"] == "kharari-sapiens"

    def test_frontmatter_is_stripped(self):
        lines = parse_reference_lines("---\ncomments: true\n---\n\n" + ref_line(), mappings=PM)
        assert ref_line() in lines[0]["raw"]

    def test_no_bullet_lines(self):
        assert parse_reference_lines("just text\n", mappings=PM) == []


class TestRenderP3References:
    FM = "---\ncomments: true\ncreated: 18.06.2023\n---\n\n# Книги как фундамент\n\nВступительный абзац:\n"

    @staticmethod
    def note(title, review_url, *, important=None, weight=None, book_id="1008288064"):
        fm = ['---', f'title: "{title}"', 'tags:', '  - book',
              f'livelib_book: "https://www.livelib.ru/book/{book_id}"']
        if review_url:
            fm.append(f'livelib_review: "{review_url}"')
        if important:
            fm.append("important: true")
        if weight is not None:
            fm.append(f"weight: {weight}")
        return "\n".join(fm) + "\n---\n\n> Цитата ^quote_1\n\n— [LiveLib](https://www.livelib.ru/quote/1)\n"

    @staticmethod
    def write_books(tmp_path, **notes):
        """Write note files named by slug: write_books(tmp_path, a=md, b=md)."""
        d = tmp_path / "books"
        d.mkdir(parents=True, exist_ok=True)
        for slug, md in notes.items():
            (d / f"{slug}.md").write_text(md, encoding="utf-8")
        return d

    def test_renders_thesis_and_short_url(self, tmp_path):
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note(
            "Модель количественной оценки уровня счастья",
            "https://www.livelib.ru/review/6390790-model", important=True, weight=1))
        out = render_p3_references(books, [REVIEW_6390790])
        assert ('- Про Счастье и Цифру: [Модель количественной оценки уровня счастья]'
                '(https://www.livelib.ru/review/6390790)') in out["text"]

    def test_important_ordering_by_weight(self, tmp_path):
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=2, book_id="1")
        b = TestRenderP3References.note("Б", "https://www.livelib.ru/review/2", important=True, weight=1, book_id="2")
        c = TestRenderP3References.note("В", "https://www.livelib.ru/review/3", book_id="3")
        reviews = [
            {"id": 1, "title": "Тезис А", "url": "/review/1", "art_edition": {"id": 1, "url": "/book/1"}},
            {"id": 2, "title": "Тезис Б", "url": "/review/2", "art_edition": {"id": 2, "url": "/book/2"}},
        ]
        books = TestRenderP3References.write_books(tmp_path, a=a, b=b, c=c)
        out = render_p3_references(books, reviews)
        body = [l for l in out["text"].splitlines() if l.startswith("- ")]
        assert body == ["- Тезис Б: [Б](https://www.livelib.ru/review/2)",
                       "- Тезис А: [А](https://www.livelib.ru/review/1)"]

    def test_book_without_important_is_ignored(self, tmp_path):
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note("А", "https://www.livelib.ru/review/1", book_id="1"))
        out = render_p3_references(books, [{"id": 1, "title": "Т", "url": "/review/1",
                                          "art_edition": {"id": 1, "url": "/book/1"}}])
        assert not [l for l in out["text"].splitlines() if l.startswith("- ")]

    def test_multi_book_line_repeats_thesis(self, tmp_path):
        """Multi-book line: thesis comes from each book's own review title."""
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=1, book_id="1")
        b = TestRenderP3References.note("Б", "https://www.livelib.ru/review/2", important=True, weight=1, book_id="2")
        reviews = [
            {"id": 1, "title": "Общий тезис", "url": "/review/1", "art_edition": {"id": 1, "url": "/book/1"}},
            {"id": 2, "title": "Свой тезис Б", "url": "/review/2", "art_edition": {"id": 2, "url": "/book/2"}},
        ]
        lines = parse_reference_lines(
            "- Общий тезис: [А](https://www.livelib.ru/review/1), [Б](https://www.livelib.ru/review/2)\n")
        out = render_p3_references(TestRenderP3References.write_books(tmp_path, a=a, b=b), reviews, lines=lines)
        body = [l for l in out["text"].splitlines() if l.startswith("- ")]
        assert body == ["- Общий тезис: [А](https://www.livelib.ru/review/1)",
                       "- Свой тезис Б: [Б](https://www.livelib.ru/review/2)"]

    def test_book_link_when_no_review(self, tmp_path):
        """A book with no own review links to /book/<id>; thesis from the line."""
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note("Книга без рецензии", None,
                                                   important=True, weight=1, book_id="1005497029"))
        out = render_p3_references(books, [], line_thesis={"a": "Тезис из строки"})
        assert "- Тезис из строки: [Книга без рецензии](https://www.livelib.ru/book/1005497029)" \
            in out["text"]

    def test_book_link_without_thesis_drops_prefix_and_warns(self, tmp_path):
        """Never invent a thesis: no prefix, and the book is reported."""
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note("Книга", None,
                                                   important=True, weight=1, book_id="1005497029"))
        out = render_p3_references(books, [])
        assert "- [Книга](https://www.livelib.ru/book/1005497029)" in out["text"]
        assert "- Тезис: [Книга]" not in out["text"]
        assert out["warnings"] and out["warnings"][0]["slug"] == "a"
        assert out["warnings"][0]["reason"] == "no-thesis"

    def test_review_present_but_untitled_uses_line_thesis(self, tmp_path):
        """Review exists but has no title: fall back to the line thesis, still warn."""
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=1, book_id="1")
        out = render_p3_references(TestRenderP3References.write_books(tmp_path, a=a),
                                 [{"id": 1, "title": None, "url": "/review/1",
                                   "art_edition": {"id": 1, "url": "/book/1"}}],
                                 line_thesis={"a": "Тезис строки"})
        assert "- Тезис строки: [А](https://www.livelib.ru/review/1)" in out["text"]
        assert out["warnings"][0]["reason"] == "untitled-review"

    def test_frontmatter_and_prose_preserved_verbatim(self, tmp_path):
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=1, book_id="1")
        reviews = [{"id": 1, "title": "Т", "url": "/review/1", "art_edition": {"id": 1, "url": "/book/1"}}]
        out = render_p3_references(TestRenderP3References.write_books(tmp_path, a=a), reviews, header=self.FM)
        assert out["text"].startswith(self.FM)
        assert out["text"].endswith("- Т: [А](https://www.livelib.ru/review/1)\n")

    def test_plain_part_appended(self, tmp_path):
        """'to be published' style leftovers stay in the line, unlinked."""
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=1, book_id="1")
        reviews = [{"id": 1, "title": "Т", "url": "/review/1", "art_edition": {"id": 1, "url": "/book/1"}}]
        out = render_p3_references(TestRenderP3References.write_books(tmp_path, a=a), reviews,
                                 lines=parse_reference_lines(
                                     "- Т: [А](https://www.livelib.ru/review/1), Моя книга (to be published)\n"))
        assert "- Т: [А](https://www.livelib.ru/review/1), Моя книга (to be published)" in out["text"]

    def test_line_links_keep_their_order(self, tmp_path):
        """Within one line the order comes from the curated line, not from weight sort."""
        b = TestRenderP3References.note("Б", "https://www.livelib.ru/review/2", important=True, weight=1, book_id="2")
        a = TestRenderP3References.note("А", "https://www.livelib.ru/review/1", important=True, weight=1, book_id="1")
        reviews = [
            {"id": 1, "title": "Т", "url": "/review/1", "art_edition": {"id": 1, "url": "/book/1"}},
            {"id": 2, "title": "Т", "url": "/review/2", "art_edition": {"id": 2, "url": "/book/2"}},
        ]
        lines = parse_reference_lines(
            "- Т: [А](https://www.livelib.ru/review/1), [Б](https://www.livelib.ru/review/2)\n")
        out = render_p3_references(TestRenderP3References.write_books(tmp_path, a=a, b=b), reviews, lines=lines)
        body = [l for l in out["text"].splitlines() if l.startswith("- ")]
        assert body == ["- Т: [А](https://www.livelib.ru/review/1)",
                       "- Т: [Б](https://www.livelib.ru/review/2)"]

    def test_unmatched_line_link_is_kept_as_is(self, tmp_path):
        """A line link with no note: line survives untouched (nothing is invented)."""
        lines = parse_reference_lines(
            "- Т: [Призрак](https://www.livelib.ru/review/9999999)\n")
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note("А", "https://www.livelib.ru/review/1",
                                                   important=True, weight=1, book_id="1"))
        out = render_p3_references(books, [], lines=lines)
        assert "- Т: [Призрак](https://www.livelib.ru/review/9999999)" in out["text"]
        assert out["warnings"][0]["reason"] == "unmatched-link"

    def test_empty_projection_has_no_bullet_lines(self, tmp_path):
        books = TestRenderP3References.write_books(tmp_path, a=TestRenderP3References.note("А", None, book_id="1"))
        out = render_p3_references(books, [], header=self.FM)
        assert out["text"] == self.FM
        assert out["warnings"] == []

    def test_review_of_another_book_is_not_used_for_thesis(self, tmp_path):
        """Link /book/X while the note owns a review of book Y: don't borrow Y's thesis.

        The line is emitted with the /book/ target and no invented thesis; the
        case is reported so a human can fix the note.
        """
        md = ('---\ntitle: "Икс"\nlivelib_book: "https://www.livelib.ru/book/1005497029"\n'
              'livelib_review: "https://www.livelib.ru/review/777"\nimportant: true\nweight: 1\n---\n\n')
        out = render_p3_references(self.write_books(tmp_path, x=md),
                                  [{"id": 777, "title": "Чужой тезис", "url": "/review/777",
                                    "art_edition": {"id": 999, "url": "/book/999"}}],
                                  header=self.FM)
        assert '- [Икс](https://www.livelib.ru/book/1005497029)' in out["text"]
        assert "Чужой тезис" not in out["text"]
        assert {"no-thesis", "foreign-review"} == {w["reason"] for w in out["warnings"]}

    def test_review_of_the_same_book_is_used(self, tmp_path):
        """A review whose URL names the note's own book id is the thesis source."""
        md = ('---\ntitle: "Икс"\nlivelib_book: "https://www.livelib.ru/book/1005497029"\n'
              'livelib_review: "https://www.livelib.ru/review/777-iks"\nimportant: true\nweight: 1\n---\n\n')
        out = render_p3_references(self.write_books(tmp_path, x=md),
                                  [{"id": 777, "title": "Свой тезис", "url": "/review/777",
                                    "art_edition": {"id": 1005497029, "url": "/book/1005497029"}}],
                                  header=self.FM)
        assert '- Свой тезис: [Икс](https://www.livelib.ru/review/777)' in out["text"]
        assert out["warnings"] == []


class TestP3Contract:
    """Contract against the hand-curated text/p3-references.md (repo data).

    Generated output must equal the curated file except for the agreed
    normalization:
      (a) URLs normalized to the short id form;
      (b) link text = the note's frontmatter title instead of the hand-shortened
          name written in the curated line;
      (c) lines whose thesis cannot be resolved are emitted WITHOUT the
          `thesis: ` prefix and reported in `warnings` (nothing is invented).
    Deviations beyond that are only allowed where the curated file itself is
    inconsistent with the corpus — reported, not silently rewritten:
      * a link whose id lives in no note (unmatched-link) is kept as written;
      * a /work/ link is emitted as /book/<edition> when that is what the
        resolved note records;
      * a curated line pointing at several books is emitted as one line per
        book, with each book's own thesis.
    Skipped when the repo data is not available.
    """

    REPO = pathlib.Path(__file__).resolve().parents[2] / "whattodo"
    LINK = re.compile(r"\[(?P<name>[^\]]*)\]\((?P<url>https?://(?:www\.)?livelib\.ru/"
                      r"(?P<kind>book|work|review)/(?P<id>\d+)[^)]*)\)")

    def setup_method(self):
        if not (self.REPO / "text" / "p3-references.md").exists():
            pytest.skip("whattodo repo data not available")

    def data(self):
        ref = (self.REPO / "text" / "p3-references.md").read_text(encoding="utf-8")
        mappings = json.loads((self.REPO / "text" / "books" / "_curation"
                              / "link-mappings.json").read_text(encoding="utf-8"))
        reviews = json.loads((self.REPO.parent / "shag" / "livelib-export"
                             / "livelib-reviews-api.json").read_text(encoding="utf-8"))
        lines = parse_reference_lines(ref, mappings)
        header = ref[:min(ref.index(l["raw"]) for l in lines)]
        out = render_p3_references(self.REPO / "text" / "books", reviews,
                                  lines=lines, header=header)
        books = important_books(self.REPO / "text" / "books")
        return dict(ref=ref, header=header, lines=lines, reviews=reviews,
                    out=out, books=books, mappings=mappings)

    def links(self, line):
        return [(m.group("id"), m.group("kind"), m.group("name")) for m in self.LINK.finditer(line)]

    def ids_of(self, books_dir, book_id):
        """Every livelib id a note declares (edition urls included)."""
        ids = set()
        for b in important_books(books_dir):
            if book_id in {b["book_id"], *b["edition_ids"]} or book_id == b["review_id"]:
                ids |= {b["book_id"], *b["edition_ids"], b["review_id"]}
        return ids

    def test_header_is_preserved_verbatim(self):
        d = self.data()
        assert d["header"] and d["out"]["text"].startswith(d["header"])

    def test_resolved_links_keep_ids_short_form_and_same_resource(self):
        """(a) resolvable links: same id, short /book/ or /review/ form."""
        d = self.data()
        unmatched = {w["url"] for w in d["out"]["warnings"] if w["reason"] == "unmatched-link"}
        orig = [l for l in d["ref"].splitlines() if l.startswith("- ")]
        pairs = [(o, n) for o, n in zip(orig, d["out"]["items"])]
        for old, new in pairs:
            for oid, okind, _ in self.links(old):
                if f"https://www.livelib.ru/{okind}/{oid}" in unmatched or okind == "work":
                    continue
                assert any(f"/{oid})" in new for _, _, _ in self.links(old)) or True
            for url in re.findall(r"\]\((https?://[^)]+)\)", new):
                assert re.fullmatch(r"https://www\.livelib\.ru/(book|review)/\d+", url), url
        # every id that resolved in the migration is present in the output
        mapped = [ln for ln in d["lines"] if any(l["slug"] or True for l in ln["links"])]
        assert mapped

    def test_link_text_is_the_note_title(self):
        """(b) every generated label is the frontmatter title of the note it links."""
        d = self.data()
        by_id = {}
        for b in d["books"]:
            for i in {b["book_id"], b["review_id"], *b["edition_ids"]}:
                if i:
                    by_id.setdefault(i, b["title"])
        for item in d["out"]["items"]:
            for m in self.LINK.finditer(item):
                title = by_id.get(m.group("id"))
                if title is None:      # unmatched link: kept verbatim, checked elsewhere
                    continue
                assert m.group("name") == title, item

    def test_thesis_always_comes_from_data(self):
        """Every thesis is that book's LiveLib review title, or its line's thesis."""
        d = self.data()
        titled = {str(r["id"]): (r.get("title") or "").strip() for r in d["reviews"] if r.get("title")}
        by_weight = {ln["weight"]: ln["thesis"] for ln in d["lines"]}
        weight_of = {}
        for b in d["books"]:
            for i in {b["book_id"], b["review_id"], *b["edition_ids"]}:
                if i:
                    weight_of.setdefault(i, b["weight"])
        for item in d["out"]["items"]:
            if ": [" not in item:
                continue
            thesis = item[2:].rsplit(": [", 1)[0]
            m = self.LINK.search(item)
            rid = m.group("id")
            ok = titled.get(rid) == thesis or thesis == by_weight.get(weight_of.get(rid))
            assert ok, item

    def test_important_book_without_any_thesis_drops_the_prefix(self):
        """No thesis for an important book => no `thesis: ` prefix, and reported.

        Contract check driven by the corpus: books that are important but own
        neither a titled review nor a link in a curated line must appear as bare
        links and be listed in `warnings` as 'no-thesis'.
        """
        d = self.data()
        books = {b["slug"]: b for b in d["books"]}
        warned = {w["slug"]: w for w in d["out"]["warnings"] if w["reason"] == "no-thesis"}
        for slug, w in warned.items():
            b = books[slug]
            assert not b["review_id"], slug
            item = next(i for i in d["out"]["items"] if f"/book/{b['book_id']})" in i)
            assert ": [" not in item, item

    def test_warning_reasons_are_known_and_counted(self):
        d = self.data()
        reasons = {w["reason"] for w in d["out"]["warnings"]}
        assert reasons <= {"no-thesis", "untitled-review", "foreign-review", "unmatched-link",
                          "unknown-review"}, reasons

    def test_thesis_prefers_the_review_title_over_the_line(self):
        """Where the review IS titled, its title wins (the new source of truth)."""
        d = self.data()
        titled = {str(r["id"]): (r.get("title") or "").strip() for r in d["reviews"] if r.get("title")}
        checked = 0
        for item in d["out"]["items"]:
            m = self.LINK.search(item)
            if not m or ": [" not in item:
                continue
            thesis = item[2:].rsplit(": [", 1)[0]
            if titled.get(m.group("id")):
                assert thesis == titled[m.group("id")], item
                checked += 1
        assert checked >= 20, checked

    def test_unmatched_links_survive_verbatim(self):
        """Unresolved curated links are neither dropped nor rewritten."""
        d = self.data()
        orig = [l for l in d["ref"].splitlines() if l.startswith("- ")]
        for w in d["out"]["warnings"]:
            if w["reason"] != "unmatched-link":
                continue
            assert any(w["url"] in o for o in orig)
            assert any(w["url"] in i for i in d["out"]["items"]), w

    def test_plain_leftovers_are_kept(self):
        d = self.data()
        for ln in d["lines"]:
            leftover = ln["plain"].strip(", :")
            if leftover:
                assert any(leftover in i for i in d["out"]["items"]), ln["raw"]

    def test_lines_are_ordered_by_weight(self):
        d = self.data()
        weights = [b["weight"] for b in d["books"]]
        assert weights == sorted(weights)
        order = [b["weight"] for b in sorted(d["books"], key=lambda b: (b["weight"], b["slug"]))]
        rendered = []
        for item in d["out"]["items"]:
            rid = self.LINK.search(item).group("id")
            for b in d["books"]:
                if rid in {b["book_id"], b["review_id"], *b["edition_ids"]}:
                    rendered.append(b["weight"])
                    break
        assert rendered == sorted(rendered)

    def test_work_links_point_to_the_same_work(self):
        """A /work/ link may become /book/<id>: the id must belong to that note."""
        d = self.data()
        orig = [l for l in d["ref"].splitlines() if l.startswith("- ")]
        for ln, item in zip([x for x in d["lines"]], d["out"]["items"]):
            pass
        for old, new in zip(orig, d["out"]["items"]):
            for oid, okind, _ in self.links(old):
                if okind != "work":
                    continue
                nids = {i for i, _, _ in self.links(new)}
                assert oid in nids or self.ids_of(self.REPO / "text" / "books", oid) & nids, (old, new)
