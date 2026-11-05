"""Tests for the curation file in YAML form (books_curation.yml).

A flat map, one entry per livelib edition: a quoted id key with the title as a
`#` comment beside it, then the entry's fields indented under it.

    "1003047920":   # Моменты счастья — Алекс Дубас
      weight: 10

The key's digits ARE the entry key; the comment is for the eye only — the same
property the jsonc `//` comments had, and the reason the file stays a map rather
than a list of records with a title field.

Two layers stay tested separately on purpose:
  * load_curation — the YAML syntax and its validation;
  * build_books(curation_path=...) — the semantic mapping onto the build.
"""

import json

import pytest
import yaml

from text_forge.wtd_books import CurationError, build_books, load_curation

BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}

DOC = """# Курация книг: id издания LiveLib -> поля.
# Название справа — для глаз, сборка не читает.
"""


def curation(*entries: str) -> str:
    """The doc block plus the given entries, in the layout the file uses."""
    return DOC + "\n" + "\n".join(entries) + "\n"


def write(tmp_path, text, name="books_curation.yml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def load(tmp_path, text, name="books_curation.yml"):
    return load_curation(write(tmp_path, text, name))


class TestLoadCurationYaml:
    """Entries parse into the dict shape build_books already consumes."""

    def test_full_shape(self, tmp_path):
        """weight -> int, merges -> list of int, author/status -> str."""
        got = load(tmp_path, curation(
            '"1000507758":   # Лунная пыль. Я, робот',
            '  weight: 320',
            '  merges: [1000507759, 1000507760]',
            '',
            '"1000284779":   # Зона',
            '  status: read',
            '  author: "Сергей Довлатов"',
        ))
        assert got == {"books": {
            "1000507758": {"weight": 320,
                           "merges": [1000507759, 1000507760]},
            "1000284779": {"status": "read", "author": "Сергей Довлатов"},
        }}

    def test_quoted_id_keys(self, tmp_path):
        """The corpus quotes its ids: they arrive as str and stay digit-only."""
        got = load(tmp_path, curation('"1000699994":', '  weight: 70'))
        assert got == {"books": {"1000699994": {"weight": 70}}}

    def test_bare_id_keys_are_strung(self, tmp_path):
        """A key written without quotes parses as an int — the loader str()s it,
        so both spellings reach build_books as the same kind of key."""
        got = load(tmp_path, curation('1000699994:', '  weight: 70'))
        assert list(got["books"]) == ["1000699994"]

    def test_quoted_and_bare_are_one_entry(self, tmp_path):
        """`"1"` and `1` are ONE id: writing it both ways is a duplicate, not
        two entries — the str() happens before the duplicate check."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":', '  weight: 10', '', '1:',
                                   '  status: read'))
        assert "1" in str(e.value)

    def test_non_digit_id_is_hard(self, tmp_path):
        """A key that is not an edition id has no business here."""
        for key in ("links", "1000699994-zona", "book/1000699994",
                    "1000 699994"):
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation(f'"{key}":', '  weight: 70'))
            assert key in str(e.value), key

    def test_title_comment_is_ignored(self, tmp_path):
        """The text beside the key is for the eye: a wrong title can never
        steer the build."""
        got = load(tmp_path, curation('"1":   # Совершенно неверное название',
                                     '  weight: 10'))
        assert got == {"books": {"1": {"weight": 10}}}

    def test_empty_file_is_an_empty_mapping(self, tmp_path):
        """A corpus may curate nothing at all — written as an empty file."""
        assert load(tmp_path, "") == {"books": {}}
        assert load(tmp_path, "\n\n") == {"books": {}}

    def test_any_key_subset(self, tmp_path):
        got = load(tmp_path, curation('"7":', '  status: read'))
        assert got == {"books": {"7": {"status": "read"}}}

    def test_merges_flow_list_forms(self, tmp_path):
        """One id, many, and the quoted form, all give the id list."""
        for body, n in (("merges: [11]", 1), ("merges: [11, 12]", 2),
                        ('merges: ["11", "12"]', 2), ("merges: [11,12,13]", 3)):
            got = load(tmp_path, curation('"1":', "  " + body))
            assert len(got["books"]["1"]["merges"]) == n, body

    def test_key_order_within_an_entry_does_not_matter(self, tmp_path):
        a = load(tmp_path, curation('"1":', '  weight: 10', '  status: read'))
        b = load(tmp_path, curation('"1":', '  status: read', '  weight: 10'))
        assert a == b

    def test_str_path_as_well_as_path(self, tmp_path):
        write(tmp_path, curation('"1":', '  weight: 10'))
        assert load_curation(str(tmp_path / "books_curation.yml")) == \
            {"books": {"1": {"weight": 10}}}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            load_curation(tmp_path / "nope.yml")

    def test_loader_keeps_its_name_and_signature(self):
        assert load_curation.__name__ == "load_curation"


class TestLoadCurationErrors:
    """Every malformed entry is a hard error naming the entry id — a silently
    dropped entry would produce a plausible wrong corpus."""

    def test_unknown_key_is_hard(self, tmp_path):
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1000225484":', '  bogus: oops'))
        msg = str(e.value)
        assert "bogus" in msg and "1000225484" in msg

    def test_my_mark_is_not_a_valid_key(self, tmp_path):
        """my_mark reaches the frontmatter from LiveLib shelf data, never from
        curation — the field is dead here, so naming it is an error."""
        for key in ("my_mark", "note", "title", "url", "merge", "weights"):
            with pytest.raises(CurationError, match=key):
                load(tmp_path, curation('"1":', f"  {key}: y"))

    def test_unknown_field_is_hard_even_next_to_a_valid_one(self, tmp_path):
        """A good weight does not excuse a bogus sibling in the same entry."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":', '  weight: 10', '  bogus: x'))
        assert "bogus" in str(e.value) and "1" in str(e.value)

    def test_error_message_carries_the_offending_key(self, tmp_path):
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":', '  weight: 10', '  bogus: oops'))
        assert "bogus" in str(e.value)

    def test_duplicate_id_is_hard(self, tmp_path):
        """stock YAML lets the last key win; here it is a refusal."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation(
                '"1000699994":   # Зона', '  weight: 10', '',
                '"1000699994":   # Зона (другое издание)', '  status: read',
            ))
        assert "1000699994" in str(e.value)
        assert "duplicate" in str(e.value)

    def test_duplicate_id_is_detected_even_with_empty_entries(self, tmp_path):
        with pytest.raises(CurationError):
            load(tmp_path, curation('"5":', '', '"5":'))

    def test_duplicate_key_inside_one_entry_is_hard(self, tmp_path):
        """Two `weight` fields: which one wins must not be a parse accident."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":', '  weight: 10', '  weight: 20'))
        msg = str(e.value)
        assert "duplicate" in msg and "weight" in msg, msg
        assert "line" in msg, msg

    def test_non_int_weight_is_hard(self, tmp_path):
        for value in ("high", "7.5", "7 kg", "null"):
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation('"1":', f"  weight: {value}"))
            assert "weight" in str(e.value) and "1" in str(e.value)

    def test_negative_weight_is_hard(self, tmp_path):
        with pytest.raises(CurationError):
            load(tmp_path, curation('"1":', "  weight: -10"))

    def test_non_digit_merges_member_is_hard(self, tmp_path):
        for value in ("[1005482422, zona]", '["1005482422-x"]', "[1.5]",
                     "[1005482422 abc]"):
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation('"1":', f"  merges: {value}"))
            assert "merges" in str(e.value) and "1" in str(e.value)

    def test_merges_scalars_are_hard(self, tmp_path):
        """`merges` names ids, so a scalar or a null is not a merge list."""
        for value in ("1005482422", '"1005482422"', "null"):
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation('"1":', f"  merges: {value}"))
            assert "merges" in str(e.value)

    def test_empty_merges_value_is_hard(self, tmp_path):
        """`merges:` naming nothing must not read as a valid empty merge."""
        with pytest.raises(CurationError):
            load(tmp_path, curation('"1":', "  merges: []"))
        with pytest.raises(CurationError):
            load(tmp_path, curation('"1":', "  merges:"))

    def test_author_and_status_must_be_nonempty_text(self, tmp_path):
        for key in ("author", "status"):
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation('"1":', f"  {key}:"))
            assert key in str(e.value)
            with pytest.raises(CurationError) as e:
                load(tmp_path, curation('"1":', f"  {key}: null"))
            assert key in str(e.value)

    def test_a_field_given_as_a_map_is_hard(self, tmp_path):
        """`weight:` followed by a nested map is not a field value."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":', "  weight:", "    x: 10"))
        assert "1" in str(e.value)

    def test_an_entry_given_as_a_scalar_is_hard(self, tmp_path):
        """An id whose value is a bare scalar carries no fields."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, curation('"1":   10'))
        assert "1" in str(e.value)

    def test_top_level_list_is_hard(self, tmp_path):
        with pytest.raises(CurationError):
            load(tmp_path, "- 1\n- 2\n")

    def test_error_message_names_the_entry_id(self, tmp_path):
        """Every rejection points at the edition it concerns."""
        for bad in ("bogus: x", "weight: 7.5", "merges: [1, zona]",
                   "my_mark: 5", "merges: 10"):
            with pytest.raises(CurationError, match=r"1000225484") as e:
                load(tmp_path, curation('"1000225484":', f"  {bad}"))
            assert "1000225484" in str(e.value)


class TestLoadCurationTombstone:
    """The dead formats must not silently pass — and never as `{"books": {}}`.

    A stale Curation.md is ALL COMMENTS to a YAML parser: it reads as None, and
    a loader that tolerated None would build a plausible corpus with every
    curation decision dropped. Same trap for a jsonc payload: braces make it one
    scalar string, which is not a mapping of entries.
    """

    def test_markdown_sections_payload_raises(self, tmp_path):
        """The dead sections file reaches the loader in one of two shapes: a
        comment-only body, which YAML reads as None, or prose carrying a colon,
        which YAML refuses to parse at all. Neither may read as entries, so both
        are refused — CurationError for the first, a YAMLError for the second."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, "# Curation\n\nОдна секция — одна редакция книги.\n",
                 name="Curation.md")
        assert "Curation.md" in str(e.value)
        assert "books_curation.yml" in str(e.value)
        # a sections file with a colon in its prose is a parse error: still a
        # refusal, and the build's `curation file not found`/load failure names it
        with pytest.raises((CurationError, yaml.YAMLError)):
            load(tmp_path, "# Curation\n\nЗаголовок: это id.\n\n## 1\n- weight: 10\n",
                 name="Curation.md")

    def test_doc_block_only_payload_raises(self, tmp_path):
        """The all-comments file is the stale-Curation.md case: it parses to
        None, and None is a refusal here, not an empty corpus."""
        with pytest.raises(CurationError) as e:
            load(tmp_path, "# Curation\n\nОдна секция — одна редакция книги.\n",
                 name="Curation.md")
        assert "books_curation.yml" in str(e.value)

    def test_comment_lines_are_comments_to_yaml(self, tmp_path):
        """Why a stale sections file can read as nothing: `#` is YAML's own
        comment marker, so a file of only comments yields None — the trap that
        would hand the build an uncurated corpus without saying so."""
        assert yaml.safe_load("# id — название\n# weight кратен 10\n") is None

    def test_jsonc_payload_raises(self, tmp_path):
        with pytest.raises(CurationError) as e:
            load(tmp_path, '{\n  "books": {"1": {"weight": 3}}\n}\n',
                 name="curation.jsonc")
        assert "books_curation.yml" in str(e.value)

    def test_old_full_jsonc_file_raises(self, tmp_path):
        """A real jsonc file — `//` comments and all — is not YAML either: `//`
        is not a comment marker and `"k": v` is not valid at the top level, so
        the refusal comes from the parser rather than the validator. Either way
        the file cannot read as entries, which is what the tombstone guards."""
        with pytest.raises((CurationError, yaml.YAMLError)):
            load(tmp_path, '{\n  // Моменты счастья — Алекс Дубас\n'
                          '  "1003047920": {"weight": 1}\n}\n',
                 name="curation.jsonc")

    def test_tombstone_message_names_the_dead_formats(self, tmp_path):
        """The message says what the file looks like AND what is expected."""
        for text, name, hint in (
                ("# Курация книг: id издания -> поля\n# Только текст для глаз.\n",
                 "Curation.md", "markdown"),
                ('{\n  "books": {\n    "1": {"weight": 1}\n  }\n}\n', "curation.jsonc",
                 "JSONC")):
            with pytest.raises(CurationError) as e:
                load(tmp_path, text, name=name)
            msg = str(e.value)
            assert "books_curation.yml" in msg, (name, msg)
            assert hint in msg, (name, msg)

    def test_a_list_payload_is_not_a_mapping(self, tmp_path):
        with pytest.raises(CurationError) as e:
            load(tmp_path, "- 1\n- 2\n")
        assert "books_curation.yml" in str(e.value)


def write_inputs(tmp_path, books=(), quotes=(), reviews=()):
    for name, data in (("books.json", books), ("quotes.json", quotes),
                      ("reviews.json", reviews)):
        (tmp_path / name).write_text(json.dumps(list(data), ensure_ascii=False),
                                    encoding="utf-8")
    return (tmp_path / "books.json", tmp_path / "quotes.json",
            tmp_path / "reviews.json")


class TestBuildWithCuration:
    """curation_path consumes the YAML map."""

    def test_author_field_replaces_author_overrides(self, tmp_path):
        """books[].author overrides a live export author (livelib has editions
        with the author field empty or wrong)."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1001128870", author="")
        books_p, quotes_p, reviews_p = write_inputs(tmp_path, books=[b])
        cur = write(tmp_path, curation('"1001128870":   # Стратегическая психология',
                                      '  author: "Александр Юрьев"'))
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
        books_p, quotes_p, reviews_p = write_inputs(tmp_path, books=[b])
        cur = write(tmp_path, curation('"1000327729":   # Зона', '  status: read'))
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "status: read" in md

    def test_weight_implies_important(self, tmp_path):
        """weight alone means important: the old file pair (important.json +
        weight) collapses into one field."""
        b = dict(BOOK_ZONA, book_url="https://www.livelib.ru/book/1000699994")
        books_p, quotes_p, reviews_p = write_inputs(tmp_path, books=[b])
        cur = write(tmp_path, curation('"1000699994":   # Зона', '  weight: 70'))
        out = tmp_path / "books"
        build_books(books_p, quotes_p, reviews_p, out, curation_path=cur)
        md = (out / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "important: true" in md
        assert "weight: 70" in md

    def test_per_book_merges_array_folds_edition_into_the_note(self, tmp_path):
        """A `merges` field is the normal form of a work merge: the member
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
        books_p, quotes_p, reviews_p = write_inputs(tmp_path, books=[e1, e2],
                                                   quotes=[q], reviews=[r])
        cur = write(tmp_path, curation(
            '"1003248852":   # Ленин. Пантократор солнечных пылинок',
            '  weight: 160',
            '  merges: [1010727563]'))
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
        books_p, quotes_p, reviews_p = write_inputs(tmp_path, books=[b])
        with pytest.raises((FileNotFoundError, OSError)):
            build_books(books_p, quotes_p, reviews_p, tmp_path / "books",
                       curation_path=tmp_path / "nope.yml")
