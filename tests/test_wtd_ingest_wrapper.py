import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "hindsight-wtd-ingest-wrapper.py"
# spec-loading does not add the script's directory to sys.path (unlike
# `python hindsight-wtd-ingest-wrapper.py`), so sibling imports
# (hindsight_common, wtd_sections_common) need the scripts dir explicitly.
sys.path.insert(0, str(SCRIPT_PATH.parent))

spec = importlib.util.spec_from_file_location(
    "hindsight_wtd_ingest_wrapper", SCRIPT_PATH
)
assert spec is not None
wrapper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wrapper
assert spec.loader is not None
spec.loader.exec_module(wrapper)


def test_chapter_from_text_path_keeps_flat_stem():
    assert wrapper.chapter_from_text_path("text/p2-200-text.md") == "p2-200-text"


def test_chapter_from_text_path_keeps_subfolder_for_books():
    # Must agree with slug_for_path() in wtd-inventory.py, otherwise the
    # wrapper calls `--chapter abe-x` and matches nothing in the inventory.
    assert wrapper.chapter_from_text_path("text/books/abe-x.md") == "books/abe-x"


def test_chapter_from_text_path_keeps_deeper_subfolders():
    assert wrapper.chapter_from_text_path("text/a/b/c.md") == "a/b/c"


def test_chapter_from_text_path_rejects_non_text_paths():
    assert wrapper.chapter_from_text_path("assets/x.md") is None
    assert wrapper.chapter_from_text_path("text/x.txt") is None
    assert wrapper.chapter_from_text_path("books/x.md") is None


def inv_with_chapters(*entries):
    """Minimal inventory dict; entries are (chapter_slug, sections) tuples."""
    return {
        "corpus": "wtd",
        "commit": "abc123",
        "chapters": [
            {"chapter": slug, "sections": list(sections)} for slug, sections in entries
        ],
    }


def section(uid, anchor, text):
    return {"section_uid": uid, "anchor": anchor, "text": text}


def test_filter_targets_drops_chapter_missing_from_inventory():
    inv = inv_with_chapters(("index", [section("intro", "intro", "Intro text")]))
    kept, dropped = wrapper.filter_targets(inv, [("books/ghost", None)])
    assert kept == []
    assert dropped == 1


def test_filter_targets_keeps_chapter_whole_with_sections():
    inv = inv_with_chapters(("index", [section("intro", "intro", "Intro text")]))
    kept, dropped = wrapper.filter_targets(inv, [("index", None)])
    assert kept == [("index", None)]
    assert dropped == 0


def test_filter_targets_drops_chapter_without_sections():
    # Books without a `## Рецензия` produce no sections in the inventory, so a
    # whole-chapter target for them would ingest 0 chunks.
    inv = inv_with_chapters(("books/grishkovets", []))
    kept, dropped = wrapper.filter_targets(inv, [("books/grishkovets", None)])
    assert kept == []
    assert dropped == 1


def test_filter_targets_keeps_section_matching_section_uid():
    inv = inv_with_chapters(
        (
            "p2-200-text",
            [
                section("digital_format_freedom", "cff", "Digital"),
                section("word", "slovo", "Word"),
            ],
        )
    )
    kept, dropped = wrapper.filter_targets(inv, [("p2-200-text", "word")])
    assert kept == [("p2-200-text", "word")]
    assert dropped == 0


def test_filter_targets_keeps_section_matching_only_via_anchor():
    inv = inv_with_chapters(("p2-200-text", [section("word", "slovo-ozhidaniya", "W")]))
    kept, dropped = wrapper.filter_targets(inv, [("p2-200-text", "slovo-ozhidaniya")])
    assert kept == [("p2-200-text", "slovo-ozhidaniya")]
    assert dropped == 0


def test_filter_targets_drops_section_with_no_matching_section():
    inv = inv_with_chapters(("p2-200-text", [section("word", "word", "Word")]))
    kept, dropped = wrapper.filter_targets(inv, [("p2-200-text", "absent_section")])
    assert kept == []
    assert dropped == 1


def test_filter_targets_drops_section_with_whitespace_only_text():
    # chunk_text() strips and returns [] for blank text -> 0 chunks.
    inv = inv_with_chapters(("index", [section("intro", "intro", "   \n\t  \n")]))
    kept, dropped = wrapper.filter_targets(inv, [("index", None)])
    assert kept == []
    assert dropped == 1
    kept, dropped = wrapper.filter_targets(inv, [("index", "intro")])
    assert kept == []
    assert dropped == 1


def test_filter_targets_keeps_chapter_with_one_nonempty_section_among_empty_ones():
    inv = inv_with_chapters(
        ("index", [section("intro", "intro", "   "), section("next", "next", "Body")])
    )
    kept, dropped = wrapper.filter_targets(inv, [("index", None)])
    assert kept == [("index", None)]
    assert dropped == 0


def test_filter_targets_mixed_list_counts_and_preserves_order():
    inv = inv_with_chapters(
        ("index", [section("intro", "intro", "Intro text")]),
        ("p2-200-text", [section("word", "slovo", "Word text")]),
        ("books/abe-x", []),
    )
    targets = [
        ("index", "intro"),
        ("books/abe-x", None),
        ("p2-200-text", "slovo"),
        ("books/ghost", None),
        ("p2-200-text", None),
        ("p2-200-text", "absent"),
    ]
    kept, dropped = wrapper.filter_targets(inv, targets)
    assert kept == [("index", "intro"), ("p2-200-text", "slovo"), ("p2-200-text", None)]
    assert dropped == 3


def test_filter_targets_empty_target_list_is_empty_result():
    inv = inv_with_chapters(("index", [section("intro", "intro", "Intro")]))
    assert wrapper.filter_targets(inv, []) == ([], 0)
