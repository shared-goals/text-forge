"""Tests for the p3-references generator module (text_forge.wtd_books_p3).

The module owns the whole `p3-references` page: its template constants, the
parsing of curated bibliography bullets and the projection of `important`
note-books into the page. These tests pin the module's own surface so the
extraction from `text_forge.wtd_books` cannot silently drop a symbol.
"""

import pathlib

from text_forge.wtd_books_p3 import (
    P3_FRONTMATTER,
    P3_INTRO,
    P3_TITLE,
    important_books,
    p3_header,
    parse_reference_lines,
    render_p3_references,
)

SYMBOLS = {
    "P3_FRONTMATTER": str,
    "P3_TITLE": str,
    "P3_INTRO": str,
    "p3_header": "function",
    "parse_reference_lines": "function",
    "important_books": "function",
    "render_p3_references": "function",
}


def test_p3_module_exports_expected_symbols():
    """Every symbol the p3 generator needs is importable from the new module."""
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


def test_render_p3_smoke(tmp_path: pathlib.Path):
    """An empty corpus still yields a complete page and empty items/warnings."""
    out = render_p3_references(tmp_path, [])
    assert set(out) >= {"text", "items", "warnings"}
    assert out["items"] == []
    assert out["warnings"] == []
    assert out["text"] == p3_header()
    assert isinstance(important_books(tmp_path), list)
    assert parse_reference_lines("") == []


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
    """No review and no curated line => bullet without thesis + 'no-thesis'."""
    (tmp_path / "important-note.md").write_text(
        "---\n"
        'title: "Важная книга"\n'
        "important: true\n"
        "weight: 2\n"
        'livelib_book: "https://www.livelib.ru/book/7654321/important"\n'
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    books = important_books(tmp_path)
    assert [b["slug"] for b in books] == ["important-note"]
    assert books[0]["weight"] == 2
    assert books[0]["book_id"] == "7654321"

    out = render_p3_references(tmp_path, [])
    # P5: the bullet targets the note's own page; the missing thesis is still
    # reported, and the note (which carries no `status:`) is reported by the
    # shelf check too — both are warnings, neither is invented content
    assert out["items"] == ["- [Важная книга](/books/important-note/)"]
    assert [w["reason"] for w in out["warnings"]] == ["no-thesis", "no status"] \
        or [w["reason"] for w in out["warnings"]] == ["no status", "no-thesis"], \
        out["warnings"]
    thesis_warnings = [w for w in out["warnings"] if w["reason"] == "no-thesis"]
    assert len(thesis_warnings) == 1
    assert thesis_warnings[0]["slug"] == "important-note"
    assert out["text"].startswith(p3_header())
    assert out["text"].endswith("\n".join(out["items"]) + "\n")
