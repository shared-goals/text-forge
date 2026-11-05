"""Tests for the curation file in markdown-section form (Curation.md).

One section per livelib edition: an `## <id> — <title for the eye>` heading,
then `- key: value` bullets. The heading's digits ARE the entry key; the text
after the em dash is eye-only, the same property the jsonc `//` comments had.

Two layers stay tested separately on purpose:
  * load_curation — the section syntax and its validation;
  * build_books(curation_path=...) — the semantic mapping onto the build.
"""

import json

import pytest

from text_forge.wtd_books import build_books, load_curation

BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}

DOC = """# Curation

Some words for the human reader — the loader reads none of them.
"""


def curation(*sections: str) -> str:
    """The doc block plus the given sections, in the layout the format uses."""
    return DOC + "\n" + "\n\n".join(sections) + "\n"


def write(tmp_path, text, name="Curation.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def load(tmp_path, text, name="Curation.md"):
    return load_curation(write(tmp_path, text, name))


class TestLoadCurationSections:
    """Sections parse into the dict shape build_books already consumes.

    The doc block carries only a title line: prose between sections could be
    read as a bullet of the section above it, so the format keeps notes next to
    the bullet they qualify.
    """

    def test_full_shape(self, tmp_path):
        """weight -> int, merges -> list of int, author/status -> str."""
        got = load(tmp_path, curation(
            "## 1000507758 — Лунная пыль. Я, робот\n"
            "- weight: 320\n"
            "- merges: 1000507759, 1000507760",
            "## 1000284779 — Зона\n"
            "- status: read\n"
            "- author: Сергей Довлатов",
        ))
        assert got == {"books": {
            "1000507758": {"weight": 320, "merges": [1000507759, 1000507760]},
            "1000284779": {"author": "Сергей Довлатов", "status": "read"},
        }}

    def test_heading_title_is_ignored(self, tmp_path):
        """Whatever follows the em dash is for the eye: id alone keys the entry."""
        a = load(tmp_path, curation("## 1000225484 — Сказать жизни «Да» — Виктор Франкл"))
        b = load(tmp_path, curation("## 1000225484 — total nonsense goes here"))
        assert a == b == {"books": {"1000225484": {}}}

    def test_heading_without_em_dash(self, tmp_path):
        """The title part is optional: a bare id heading is a valid section."""
        assert load(tmp_path, curation("## 1000225484")) == {"books": {"1000225484": {}}}

    def test_str_path_as_well_as_path(self, tmp_path):
        p = write(tmp_path, curation("## 1 — Зона\n- weight: 10"))
        assert load_curation(str(p)) == {"books": {"1": {"weight": 10}}}

    def test_any_key_subset(self, tmp_path):
        """A section may carry any subset of the keys — merges-only is legal."""
        got = load(tmp_path, curation(
            "## 1 — a\n- weight: 10",
            "## 2 — b\n- author: Кто-то",
            "## 3 — c\n- status: reading",
            "## 4 — d\n- merges: 40",
            "## 5 — e",
        ))
        assert got == {"books": {
            "1": {"weight": 10},
            "2": {"author": "Кто-то"},
            "3": {"status": "reading"},
            "4": {"merges": [40]},
            "5": {},
        }}

    def test_empty_file_is_an_empty_mapping(self, tmp_path):
        """A corpus may curate nothing at all."""
        assert load(tmp_path, "") == {"books": {}}
        assert load(tmp_path, DOC) == {"books": {}}

    def test_h2_is_the_only_section_marker(self, tmp_path):
        """The section marker is exactly `## `: the doc block's H1 and any
        deeper heading stay prose, and both are accepted without complaint."""
        got = load(tmp_path, DOC + "\n# Context for the reader\n\n"
                  "### More context\n\n"
                  "## 7 — real\n- weight: 70\n")
        assert got == {"books": {"7": {"weight": 70}}}

    def test_bullet_forms(self, tmp_path):
        """`-`, spaces around key/value, and spaces around the separator."""
        got = load(tmp_path, curation(
            "## 1 — a\n  -  weight :  10  \n"
            "* author: Кто-то\n"
            "- status:   read",
        ))
        assert got == {"books": {"1": {"author": "Кто-то", "status": "read",
                                      "weight": 10}}}

    def test_prose_line_between_bullets_is_ignored(self, tmp_path):
        """A note written between bullets stays for the eye."""
        got = load(tmp_path, curation(
            "## 1 — a\n- weight: 10\n"
            "why it sits here: the edition I actually own\n"
            "- status: read",
        ))
        assert got == {"books": {"1": {"status": "read", "weight": 10}}}

    def test_merges_separator_variants(self, tmp_path):
        """Comma, and comma+space, and a lone id, all give the id list."""
        for body in ("- merges: 11", "- merges: 11,12", "- merges: 11 , 12 , 13"):
            got = load(tmp_path, curation("## 1 — a\n" + body))
            n = body.count(",") + 1
            assert len(got["books"]["1"]["merges"]) == n, body

    def test_key_order_within_a_section_does_not_matter(self, tmp_path):
        a = load(tmp_path, curation("## 1 — x\n- weight: 10\n- status: read"))
        b = load(tmp_path, curation("## 1 — x\n- status: read\n- weight: 10"))
        assert a == b

    def test_markdown_escapes_are_not_stripped(self, tmp_path):
        r"""An author holding `*` or `\_` is data, not markup: the loader reads
        the line literally, so the value comes back byte for byte."""
        got = load(tmp_path, "## 1 — x\n" + r"- author: Зоя \*зоя\* К\__од" + "\n")
        assert got == {"books": {"1": {"author": r"Зоя \*зоя\* К\__од"}}}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            load_curation(tmp_path / "nope.md")


class TestLoadCurationErrors:
    """Every malformed line is a hard error naming the entry id, and where it
    sits — a silently dropped entry would produce a plausible wrong corpus."""

    def test_unknown_key_is_hard(self, tmp_path):
        with pytest.raises(ValueError) as e:
            load(tmp_path, curation("## 1000225484 — x\n- my_mark: 5"))
        msg = str(e.value)
        assert "my_mark" in msg and "1000225484" in msg

    def test_my_mark_is_not_a_valid_key(self, tmp_path):
        """my_mark reaches the frontmatter from LiveLib shelf data, never from
        curation — the field is dead here, so naming it is an error."""
        for key in ("my_mark", "note", "title", "url", "merge", "weights"):
            with pytest.raises(ValueError, match=key):
                load(tmp_path, curation(f"## 1 — x\n- {key}: y"))

    def test_unknown_key_error_carries_the_offending_line(self, tmp_path):
        with pytest.raises(ValueError) as e:
            load(tmp_path, curation("## 1 — a\n- weight: 10\n- bogus: oops"))
        assert "- bogus: oops" in str(e.value)

    def test_duplicate_id_heading_is_hard(self, tmp_path):
        with pytest.raises(ValueError) as e:
            load(tmp_path, curation(
                "## 1000699994 — Зона\n- weight: 10",
                "## 1000699994 — Зона (другое издание)\n- status: read",
            ))
        assert "1000699994" in str(e.value)

    def test_duplicate_id_is_detected_even_with_empty_sections(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, curation("## 5", "## 5"))

    def test_non_digit_id_is_hard(self, tmp_path):
        """A section that is not an edition id has no business here."""
        for heading in ("## links", "## 1000699994-zona", "## book/1000699994",
                       "## 1000 699994"):
            with pytest.raises(ValueError) as e:
                load(tmp_path, curation(heading))
            assert heading[3:] in str(e.value), heading

    def test_non_int_weight_is_hard(self, tmp_path):
        for value in ("high", "7.5", "7 kg", "", '"7"'):
            with pytest.raises(ValueError) as e:
                load(tmp_path, curation("## 1 — a\n- weight: " + value))
            assert "weight" in str(e.value) and "1" in str(e.value)

    def test_negative_weight_is_hard(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, curation("## 1 — a\n- weight: -10"))

    def test_non_digit_merges_member_is_hard(self, tmp_path):
        for value in ("1005482422, zona", "1005482422,", ", 1005482422",
                     "1005482422 abc 1007148466"):
            with pytest.raises(ValueError) as e:
                load(tmp_path, curation("## 1 — a\n- merges: " + value))
            assert "merges" in str(e.value) and "1" in str(e.value)

    def test_empty_merges_value_is_hard(self, tmp_path):
        """`- merges:` with nothing after it names nothing: fall-loud beats a
        silently entry with an empty merge list."""
        with pytest.raises(ValueError):
            load(tmp_path, curation("## 1 — a\n- merges:"))

    def test_author_and_status_must_be_nonempty_text(self, tmp_path):
        for key in ("author", "status"):
            with pytest.raises(ValueError) as e:
                load(tmp_path, curation(f"## 1 — a\n- {key}:"))
            assert key in str(e.value)

    def test_bullet_without_colon_is_hard(self, tmp_path):
        with pytest.raises(ValueError) as e:
            load(tmp_path, curation("## 1 — a\n- weight 10"))
        assert "1" in str(e.value)

    def test_repeated_key_in_one_section_is_hard(self, tmp_path):
        """Two `weight` bullets: which one wins must not be a parse accident."""
        with pytest.raises(ValueError) as e:
            load(tmp_path, curation("## 1 — a\n- weight: 10\n- weight: 20"))
        assert "weight" in str(e.value) and "1" in str(e.value)

    def test_bullet_before_any_heading_is_hard(self, tmp_path):
        """A bullet sitting outside a section belongs to no edition."""
        with pytest.raises(ValueError) as e:
            load(tmp_path, DOC + "\n- weight: 10\n")
        assert "weight" in str(e.value)

    def test_error_message_names_a_line_number(self, tmp_path):
        """Every rejection points at where in the file to look."""
        for bad in ("- bogus: x", "- weight", "- weight: 7.5", "- merges: 1, zona",
                    "- my_mark: 5", "- weight: 10\n- weight: 20"):
            with pytest.raises(ValueError, match=r"line \d+"):
                load(tmp_path, curation("## 1 — a\n" + bad))


class TestLoadCurationTombstone:
    """The JSONC format is DEAD: an old payload must not silently pass."""

    def test_jsonc_books_payload_raises(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, '{\n  "books": {"1": {"weight": 3}}\n}\n')

    def test_old_full_file_raises(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, '{\n  // Моменты счастья — Алекс Дубас\n'
                          '  "1003047920": {"weight": 1}\n}\n')

    def test_json_line_is_not_a_bullet(self, tmp_path):
        """A leftover json fragment is not a markdown bullet: the loader's
        tombstone catches the old format by its braces rather than letting it
        pass as prose."""
        with pytest.raises(ValueError):
            load(tmp_path, DOC + '"books": {\n  "1": {"weight": 3}\n  }\n}\n')

    def test_json_line_is_not_a_heading(self, tmp_path):
        """A jsonc payload is refused as a whole — never mistaken for a
        section, and the message names the migration."""
        got = None
        try:
            load(tmp_path, '{\n  "books": {"1": {"weight": 3}}\n}\n')
        except ValueError as exc:
            got = str(exc)
        assert got and ("migrate" in got or "##" in got), got


class TestBuildWithCuration:
    """curation_path consumes the markdown sections."""

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
        cur = write(tmp_path, curation(
            "## 1001128870 — Стратегическая психология\n- author: Александр Юрьев"))
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        notes = list(out.glob("*.md"))
        assert len(notes) == 1
        assert "yurev" in notes[0].name
        # bare scalar, as every other author in the corpus renders
        assert "author: Александр Юрьев" in notes[0].read_text(encoding="utf-8")

    def test_status_field_replaces_book_override(self, tmp_path):
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000327729",
                 status=None)
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        cur = write(tmp_path, curation(
            "## 1000327729 — Зона\n- status: read"))
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "status: read" in md

    def test_weight_implies_important(self, tmp_path):
        """weight alone means important: the old file pair (important.json +
        weight) collapses into one field."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        cur = write(tmp_path, curation("## 1000699994 — Зона\n- weight: 70"))
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "important: true" in md
        assert "weight: 70" in md

    def test_per_book_merges_array_folds_edition_into_the_note(self, tmp_path):
        """A `merges` bullet is the normal form of a work merge: the member
        edition's quotes and review land in the MAIN id's note, the note keeps
        its slug, and `livelib_editions` still lists the merged id."""
        e1 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1003248852",
                  title="Ленин. Пантократор солнечных пылинок", author="Лев Данилкин")
        e2 = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1010727563",
                  title="Ленин", author="Данилкин Лев", my_mark=None)
        q = {"id": 70, "text": "<p>Цитата</p>", "created_at": "2024-01-01T00:00:00",
             "quote": {"quote_id": 700, "url": "/quote/700-lenin"},
             "art_edition": {"url": "/book/1010727563-lenin", "title": "Ленин",
                            "authors": [{"full_name": "Лев Данилкин"}]}}
        r = {"id": 901, "url": "/review/901-lenin", "text": "<p>Биография.</p>",
             "created_at": "2023-05-01T00:00:00",
             "art_edition": {"url": "/book/1010727563-lenin", "title": "Ленин",
                            "authors": [{"full_name": "Лев Данилкин"}]}}
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[e1, e2],
                                                        quotes=[q], reviews=[r])
        cur = write(tmp_path, curation(
            "## 1003248852 — Ленин. Пантократор солнечных пылинок\n"
            "- weight: 160\n- merges: 1010727563"))
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

    def test_missing_curation_file_is_an_error(self, tmp_path):
        """A named-but-absent curation file must not silently mean 'no curation'
        — that would drop curation and produce a plausible-looking wrong corpus."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = self.write_inputs(tmp_path, books=[b])
        with pytest.raises((FileNotFoundError, OSError)):
            build_books(books_p, quotes_p, reviews_p, tmp_path / "books",
                       curation_path=tmp_path / "nope.md")
