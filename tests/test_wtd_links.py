"""Tests for the local link map and the chapter link rewriter (text_forge.wtd_links).

The map keys every livelib id a note-book declares or closes (`<kind>/<id>` ->
{slug, anchor}); the rewriter uses it to point chapter links at the site's own
book pages. Targets are RELATIVE (`books/<slug>.md`), so a chapter living in a
subdirectory of `text/` still reaches its note — `local_target()` is the ONE
producer of that shape. livelib URLs survive only inside text/books/*.md.
"""

import pathlib

from text_forge.wtd_links import (
    build_link_map,
    local_target,
    rewrite_text_links,
)


def note(title, *, book="1000", review=None, quotes=(), status=None, extra=()):
    """A note-book body: frontmatter + one blockquote per quote id.

    quotes: list of (quote_livelib_id,) or (quote_livelib_id, "quote_N") —
    the second form puts the block id on the blockquote's last line, the shape
    render_note emits.
    """
    fm = ["---", f'title: "{title}"', "tags:", "  - book"]
    if status:
        fm.append(f"status: {status}")
    fm.append(f'livelib_book: "https://www.livelib.ru/book/{book}"')
    if extra:
        fm.append("livelib_editions:")
        for e in extra:
            fm.append(f'  - "https://www.livelib.ru/book/{e}"')
    if review:
        fm.append(f'livelib_review: "https://www.livelib.ru/review/{review}"')
    body = ["\n".join(fm), "---", ""]
    for q in quotes:
        # (quote_id,) or (quote_id, block_id) — the block id goes on the
        # blockquote's last line, the shape render_note emits
        if isinstance(q, str):
            qid, anchor = q, None
        else:
            qid, anchor = q[0], q[1] if len(q) > 1 else None
        block = [f"> Цитата номер {qid}" + (f" ^{anchor}" if anchor else ""), ""]
        block.append(f"— [LiveLib](https://www.livelib.ru/quote/{qid}-slug)")
        block.append("")
        body += block
    return "\n".join(body).rstrip() + "\n"


def write_books(tmp_path, **notes):
    d = tmp_path / "books"
    d.mkdir(parents=True, exist_ok=True)
    for slug, md in notes.items():
        (d / f"{slug}.md").write_text(md, encoding="utf-8")
    return d


class TestLocalTarget:
    """`local_target` is the ONLY producer of the canonical local-link form."""

    def test_target_is_relative_md_path(self):
        assert local_target({"slug": "abe", "anchor": None}) == "books/abe.md"

    def test_anchor_appended_after_md_path(self):
        assert local_target({"slug": "abe", "anchor": "quote_8"}) == "books/abe.md#quote_8"

    def test_missing_anchor_key_reads_as_no_anchor(self):
        assert local_target({"slug": "abe"}) == "books/abe.md"


class TestBuildLinkMap:
    def test_book_and_review_keys_from_frontmatter(self, tmp_path):
        books = write_books(tmp_path, abe=note("Четвертый ледниковый период",
                                             book="1001616054", review="4201003"))
        m = build_link_map(books)
        assert m["book/1001616054"] == {"slug": "abe", "anchor": None}
        assert m["review/4201003"] == {"slug": "abe", "anchor": None}

    def test_slugged_url_normalizes_to_same_key(self, tmp_path):
        """Short and slug-suffixed URL forms give the same `<kind>/<id>` key."""
        books = write_books(tmp_path, abe=note("Т", book="1001616054"))
        m = build_link_map(books)
        assert "book/1001616054" in m

    def test_quote_key_gets_anchor_of_preceding_block(self, tmp_path):
        books = write_books(tmp_path, abe=note("Т", book="1",
                                              quotes=[("42572258", "quote_1"),
                                                    ("49559677", "quote_2")]))
        m = build_link_map(books)
        assert m["quote/42572258"] == {"slug": "abe", "anchor": "quote_1"}
        assert m["quote/49559677"] == {"slug": "abe", "anchor": "quote_2"}

    def test_attribution_without_preceding_anchor(self, tmp_path):
        """No block id on the quote above the attribution -> anchor None."""
        books = write_books(tmp_path, abe=note("Т", book="1", quotes=[("42572258",)]))
        m = build_link_map(books)
        assert m["quote/42572258"] == {"slug": "abe", "anchor": None}

    def test_edition_ids_key_to_same_note(self, tmp_path):
        books = write_books(tmp_path, lenin=note("Ленин", book="1003248852",
                                                extra=["1010727563"]))
        m = build_link_map(books)
        assert m["book/1003248852"]["slug"] == "lenin"
        assert m["book/1010727563"]["slug"] == "lenin"

    def test_repeated_quote_first_note_wins_and_dupe_recorded(self, tmp_path):
        books = write_books(tmp_path,
                           aaa=note("Первая", book="1", quotes=[("777", "quote_1")]),
                           bbb=note("Вторая", book="2", quotes=[("777", "quote_1")]))
        m = build_link_map(books)
        assert m["quote/777"]["slug"] == "aaa"
        dupes = m["dupes"]
        assert len(dupes) == 1
        assert dupes[0]["key"] == "quote/777"
        assert dupes[0]["slug"] == "bbb"

    def test_empty_dir_yields_empty_map(self, tmp_path):
        assert build_link_map(tmp_path / "nope") == {}

    def test_note_without_frontmatter_is_skipped(self, tmp_path):
        books = write_books(tmp_path, plain="# Просто заголовок\n")
        m = build_link_map(books)
        assert "dupes" not in m or m["dupes"] == []
        assert not [k for k in m if k != "dupes"]


class TestRewriteTextLinks:
    @staticmethod
    def write_text(root, name, body):
        t = pathlib.Path(root) / "text"
        t.mkdir(parents=True, exist_ok=True)
        (t / name).write_text(body, encoding="utf-8")
        return t

    @staticmethod
    def corpus(tmp_path):
        books = write_books(tmp_path / "text",
                           abe=note("Четвертый ледниковый период", book="1001616054",
                                   review="4201003",
                                   quotes=[("42572258", "quote_1")]),
                           king=note("Как писать книги", book="2002",
                                    quotes=[("162379", "quote_2")]))
        return books

    def test_dry_run_does_not_write(self, tmp_path):
        _ = self.corpus(tmp_path)
        text = self.write_text(tmp_path, "p1-010-happiness.md",
                              "[Книга](https://www.livelib.ru/book/1001616054)\n")
        before = (text / "p1-010-happiness.md").read_text(encoding="utf-8")
        res = rewrite_text_links(tmp_path)
        assert (text / "p1-010-happiness.md").read_text(encoding="utf-8") == before
        assert res["replacements"] == 1

    def test_book_and_review_hit_local_page(self, tmp_path):
        _ = self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[Книга](https://www.livelib.ru/book/1001616054) и "
                              "[рецензия](https://www.livelib.ru/review/4201003)\n")
        res = rewrite_text_links(tmp_path, apply=True)
        out = (text / "ch.md").read_text(encoding="utf-8")
        assert "(books/abe.md)" in out
        assert out.count("(books/abe.md)") == 2
        assert "livelib.ru" not in out
        assert res["files"] == 1

    def test_slugged_url_rewritten(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[К](https://www.livelib.ru/book/1001616054-chetvertyy-lednikovyy-period)\n")
        rewrite_text_links(tmp_path, apply=True)
        assert "(books/abe.md)" in (text / "ch.md").read_text(encoding="utf-8")

    def test_quote_hit_gets_anchor(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "> выдержка\n\n[цитата](https://www.livelib.ru/quote/42572258-sluga)\n")
        rewrite_text_links(tmp_path, apply=True)
        assert "(books/abe.md#quote_1)" in (text / "ch.md").read_text(encoding="utf-8")

    def test_quote_without_anchor_falls_back_to_page(self, tmp_path):
        _ = write_books(tmp_path / "text", abe=note("Т", book="1",
                                                       quotes=[("777",)]))
        text = self.write_text(tmp_path, "ch.md",
                              "[q](https://www.livelib.ru/quote/777)\n")
        rewrite_text_links(tmp_path, apply=True)
        assert "(books/abe.md)" in (text / "ch.md").read_text(encoding="utf-8")

    def test_miss_keeps_url_and_is_reported(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[нет](https://www.livelib.ru/book/999999)\n")
        res = rewrite_text_links(tmp_path, apply=True)
        assert "livelib.ru/book/999999" in (text / "ch.md").read_text(encoding="utf-8")
        assert len(res["unresolved"]) == 1
        assert res["unresolved"][0]["url"].startswith("https://www.livelib.ru/book/999999")

    def test_report_entries_have_file_line_old_new(self, tmp_path):
        self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md",
                      "text\n[Книга](https://www.livelib.ru/book/1001616054)\n")
        res = rewrite_text_links(tmp_path)
        r = res["replacements_list"][0]
        assert r["file"] == "ch.md"
        assert r["line"] == 2
        assert r["old"] == "https://www.livelib.ru/book/1001616054"
        assert r["new"] == "books/abe.md"

    def test_books_dir_and_curation_are_not_rewritten(self, tmp_path):
        # `root/text/books` is the layout rewrite_text_links walks: the dir that
        # holds the notes is exactly the dir that must stay untouched
        books = self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md",
                      "[К](https://www.livelib.ru/book/1001616054)\n")
        inside = books / "abe.md"
        before = inside.read_text(encoding="utf-8")
        cur = books / "_curation"
        cur.mkdir(exist_ok=True)
        (cur / "note.md").write_text("[К](https://www.livelib.ru/book/1001616054)\n",
                                    encoding="utf-8")
        rewrite_text_links(tmp_path, apply=True)
        assert inside.read_text(encoding="utf-8") == before
        assert "livelib.ru" in (cur / "note.md").read_text(encoding="utf-8")

    def test_idempotent_second_run_finds_nothing(self, tmp_path):
        self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md",
                      "[Книга](https://www.livelib.ru/book/1001616054) "
                      "[ц](https://www.livelib.ru/quote/42572258)\n")
        first = rewrite_text_links(tmp_path, apply=True)
        assert first["replacements"] == 2
        second = rewrite_text_links(tmp_path, apply=True)
        assert second["replacements"] == 0
        assert second["candidates"] == 0

    def test_link_text_is_kept(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[Четвертый ледниковый период](https://www.livelib.ru/book/1001616054)\n")
        rewrite_text_links(tmp_path, apply=True)
        assert "[Четвертый ледниковый период](books/abe.md)" in (
            text / "ch.md").read_text(encoding="utf-8")

    def test_naked_url_in_prose_is_rewritten(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "См. https://www.livelib.ru/book/1001616054 далее\n")
        rewrite_text_links(tmp_path, apply=True)
        body = (text / "ch.md").read_text(encoding="utf-8")
        assert "https://www.livelib.ru" not in body
        assert "books/abe.md" in body

    def test_missing_text_dir_is_not_an_error(self, tmp_path):
        # notes exist (root/text/books), chapters do not: nothing to rewrite
        write_books(tmp_path / "text", a=note("A", book="1"))
        res = rewrite_text_links(tmp_path)
        assert res["replacements"] == 0
        assert res["unresolved"] == []


class TestLegacyRewrite:
    """The legacy pass: chapters already carrying the OLD site-absolute form
    (`/books/<slug>/`, optionally `#anchor`) are rewritten to the new relative
    form. It resolves through the SAME link_map — so it is not a blind text
    substitution but the same resolution: a slug no note declares stays untouched
    and lands in `unresolved`, exactly like a livelib URL with no note.
    """

    @staticmethod
    def write_text(root, name, body):
        return TestRewriteTextLinks.write_text(root, name, body)

    @staticmethod
    def corpus(tmp_path):
        return TestRewriteTextLinks.corpus(tmp_path)

    def test_legacy_link_rewritten_to_relative_form(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "Книга [Т](/books/abe/) стоит на полке\n")
        res = rewrite_text_links(tmp_path, apply=True)
        out = (text / "ch.md").read_text(encoding="utf-8")
        assert "(books/abe.md)" in out
        assert "/books/abe/" not in out
        assert res["replacements"] == 1
        assert res["files"] == 1
        assert res["candidates"] == 1
        assert res["candidates_local"] == 1

    def test_legacy_anchor_target_keeps_its_own_anchor(self, tmp_path):
        """The anchor the chapter wrote is what the reader asked for — kept."""
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md", "[цитата](/books/abe/#quote_1)\n")
        res = rewrite_text_links(tmp_path, apply=True)
        out = (text / "ch.md").read_text(encoding="utf-8")
        assert "(books/abe.md#quote_1)" in out
        assert res["replacements"] == 1

    def test_report_entries_have_file_line_old_new(self, tmp_path):
        self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md", "text\n[Книга](/books/abe/)\n")
        res = rewrite_text_links(tmp_path)
        r = res["replacements_list"][0]
        assert r["file"] == "ch.md"
        assert r["line"] == 2
        assert r["old"] == "/books/abe/"
        assert r["new"] == "books/abe.md"

    def test_dry_run_does_not_write(self, tmp_path):
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md", "[Т](/books/abe/)\n")
        before = (text / "ch.md").read_text(encoding="utf-8")
        res = rewrite_text_links(tmp_path)
        assert (text / "ch.md").read_text(encoding="utf-8") == before
        assert res["replacements"] == 1
        assert res["applied"] is False

    def test_unknown_slug_is_unresolved_and_left_untouched(self, tmp_path):
        """A legacy link to a note that does not exist: no invention, just a report."""
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md", "[нет](/books/ghost/)\n")
        res = rewrite_text_links(tmp_path, apply=True)
        assert "(/books/ghost/)" in (text / "ch.md").read_text(encoding="utf-8")
        assert len(res["unresolved"]) == 1
        assert res["unresolved"][0]["url"] == "/books/ghost/"
        assert res["replacements"] == 0

    def test_livelib_and_legacy_links_count_in_one_pass(self, tmp_path):
        """One line holding both kinds: both land in the same report fields."""
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[К](https://www.livelib.ru/book/2002) и "
                              "[А](/books/abe/)\n")
        res = rewrite_text_links(tmp_path, apply=True)
        out = (text / "ch.md").read_text(encoding="utf-8")
        assert "(books/king.md)" in out
        assert "(books/abe.md)" in out
        assert res["candidates"] == 2
        assert res["candidates_local"] == 2
        assert res["replacements"] == 2
        assert res["files"] == 1

    def test_new_form_is_left_untouched(self, tmp_path):
        """Idempotence by target, not by luck: the new form is no candidate."""
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "[Книга](books/abe.md) и [ц](books/abe.md#quote_1)\n")
        before = (text / "ch.md").read_text(encoding="utf-8")
        res = rewrite_text_links(tmp_path, apply=True)
        assert (text / "ch.md").read_text(encoding="utf-8") == before
        assert res["candidates"] == 0
        assert res["replacements"] == 0

    def test_second_run_after_legacy_rewrite_finds_nothing(self, tmp_path):
        """Idempotence over a read/write cycle — the controller's whole migration.

        The migration is ONE `apply=True` pass over chapters still holding the old
        form, so the second pass must be silent for BOTH kinds: the livelib URLs
        are gone, and the relative targets it just wrote are not candidates again.
        One line holding both kinds is what the corpus looks like mid-migration.
        """
        self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md",
                       "[К](https://www.livelib.ru/book/2002) "
                       "[А](/books/abe/) [ц](/books/abe/#quote_1)\n")
        first = rewrite_text_links(tmp_path, apply=True)
        assert first["replacements"] == 3
        second = rewrite_text_links(tmp_path, apply=True)
        assert second["replacements"] == 0
        assert second["candidates"] == 0

    def test_books_dir_is_not_rewritten_for_legacy_links(self, tmp_path):
        """The notes keep their livelib attribution: the walk excludes books/ and
        _curation/ for the legacy pass too."""
        books = self.corpus(tmp_path)
        self.write_text(tmp_path, "ch.md", "[К](/books/abe/)\n")
        inside = books / "abe.md"
        before = inside.read_text(encoding="utf-8")
        cur = books / "_curation"
        cur.mkdir(exist_ok=True)
        (cur / "map.md").write_text("[К](/books/abe/)\n", encoding="utf-8")
        rewrite_text_links(tmp_path, apply=True)
        assert inside.read_text(encoding="utf-8") == before
        assert "(/books/abe/)" in (cur / "map.md").read_text(encoding="utf-8")

    def test_author_link_style_line_rewritten(self, tmp_path):
        """The `{ .author }` shape the corpus uses: only the target changes."""
        self.corpus(tmp_path)
        text = self.write_text(tmp_path, "ch.md",
                              "\t[Аа](/books/abe/#quote_1){ .author }\n")
        rewrite_text_links(tmp_path, apply=True)
        assert "(books/abe.md#quote_1){ .author }" in (
            text / "ch.md").read_text(encoding="utf-8")
