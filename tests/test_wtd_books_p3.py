"""Tests for the p3-references generator module (text_forge.wtd_books_p3).

The module owns the whole `p3-references` page: its template constants, the
from-scratch projection of `important` note-books, and the collapsed shelf
lists. These tests pin the module's own surface so an extraction or refactor
cannot silently drop a symbol or change the page's shape.
"""

import pathlib

from text_forge.wtd_books_p3 import (
    P3_FRONTMATTER,
    P3_INTRO,
    P3_TITLE,
    important_books,
    p3_header,
    render_p3_references,
)


def _about(out, reason):
    """Warnings for one reason."""
    return [w for w in out["warnings"] if w["reason"] == reason]


SYMBOLS = {
    "P3_FRONTMATTER": str,
    "P3_TITLE": str,
    "P3_INTRO": str,
    "p3_header": "function",
    "important_books": "function",
    "render_p3_references": "function",
}


def test_p3_module_exports_expected_symbols():
    """Every symbol the p3 generator needs is importable from the module."""
    import text_forge.wtd_books_p3 as p3

    for name, kind in SYMBOLS.items():
        assert hasattr(p3, name), f"missing symbol: {name}"
        if kind == "function":
            assert callable(getattr(p3, name)), f"{name} is not callable"
        else:
            assert isinstance(getattr(p3, name), kind), f"{name} has wrong type"

    # the page head is built from the constants, in the documented order
    header = p3_header()
    assert header.startswith(P3_FRONTMATTER)
    assert f"# {P3_TITLE}" in header
    assert P3_INTRO in header
    assert header.endswith("\n")
    # frontmatter is closed on its own
    assert P3_FRONTMATTER.count("---") == 2


def test_p3_module_dropped_the_read_back_surface():
    """The parser the read-back needed is gone — from the module AND its re-export.

    A leftover would mean the dead code still loads, and a caller could quietly
    reintroduce the round trip this refactor removed.
    """
    import text_forge.wtd_books as wb
    import text_forge.wtd_books_p3 as p3

    for name in (
        "parse_reference_lines",
        "p3_bibliography",
        "strip_links",
        "link_map_from_notes",
        "WORK_ID_TO_SLUG",
        "REF_BULLET",
        "REF_LINK",
        "LOCAL_LINK",
        "ANY_LINK",
        "DETAILS_MARKER",
    ):
        assert not hasattr(p3, name), f"read-back symbol survived: p3.{name}"
        assert not hasattr(wb, name), f"read-back symbol re-exported: wtd_books.{name}"


def test_render_p3_smoke(tmp_path: pathlib.Path):
    """An empty corpus still yields a complete page and empty items/warnings."""
    out = render_p3_references(tmp_path, [])
    assert set(out) >= {"text", "items", "warnings"}
    assert out["items"] == []
    assert out["warnings"] == []
    assert out["text"] == p3_header()
    assert isinstance(important_books(tmp_path), list)


def test_render_p3_ignores_non_important_notes(tmp_path: pathlib.Path):
    """A note without `important: true` is not projected onto the page."""
    (tmp_path / "plain-note.md").write_text(
        "---\n"
        'title: "Простая книга"\n'
        "weight: 1\n"
        'livelib_book: "https://www.livelib.ru/book/1234567/plain"\n'
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    assert important_books(tmp_path) == []
    out = render_p3_references(tmp_path, [])
    assert out["items"] == []
    assert out["text"] == p3_header()


def test_important_note_without_thesis_warns(tmp_path: pathlib.Path):
    """A review that carries no title => bullet without thesis + warning.

    The note declares a review, the export gives it no title, so there is no
    thesis to print: the prefix is dropped and 'untitled-review' is reported.
    The note also carries no `status:`, so the shelf check reports 'no status'
    too — both are warnings, neither is invented content.
    """
    (tmp_path / "important-note.md").write_text(
        "---\n"
        'title: "Важная книга"\n'
        "important: true\n"
        "weight: 2\n"
        'livelib_book: "https://www.livelib.ru/book/7654321/important"\n'
        'livelib_review: "https://www.livelib.ru/review/7654321"\n'
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    books = important_books(tmp_path)
    assert [b["slug"] for b in books] == ["important-note"]
    assert books[0]["weight"] == 2
    assert books[0]["book_id"] == "7654321"
    assert books[0]["review_id"] == "7654321"

    out = render_p3_references(
        tmp_path,
        [
            {
                "id": "7654321",
                "title": "",
                "url": "/review/7654321",
                "art_edition": {"id": "7654321", "url": "/book/7654321"},
            }
        ],
    )
    # the bullet targets the note's own page; the missing thesis is reported
    assert out["items"] == ["- [Важная книга](/books/important-note/)"]
    assert {w["reason"] for w in out["warnings"]} == {"untitled-review", "no status"}
    thesis_warnings = _about(out, "untitled-review")
    assert len(thesis_warnings) == 1
    assert thesis_warnings[0]["slug"] == "important-note"
    assert out["text"].startswith(p3_header())
    # the bibliography ends where the shelf lists begin (the note has no shelf,
    # so nothing is appended and the page is the header plus the bullet)
    assert out["text"] == p3_header() + "\n" + "\n".join(out["items"]) + "\n"
