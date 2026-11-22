import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "hindsight-ingest.py"
# spec-loading does not add the script's directory to sys.path (unlike
# `python hindsight-ingest.py`), so the sibling `hindsight_common` import
# needs the scripts dir on the path explicitly.
sys.path.insert(0, str(SCRIPT_PATH.parent))

common_spec = importlib.util.spec_from_file_location(
    "hindsight_common", REPO_ROOT / "scripts" / "hindsight_common.py"
)
assert common_spec is not None and common_spec.loader is not None
hindsight_common = importlib.util.module_from_spec(common_spec)
sys.modules.setdefault("hindsight_common", hindsight_common)
common_spec.loader.exec_module(hindsight_common)
common = hindsight_common

spec = importlib.util.spec_from_file_location("hindsight_ingest", SCRIPT_PATH)
assert spec is not None
hindsight_ingest = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hindsight_ingest)


def sample_inventory():
    return {
        "corpus": "wtd",
        "commit": "abc123",
        "chapters": [
            {
                "chapter": "index",
                "status": "published",
                "url": "https://example.org/",
                "sections": [
                    {
                        "section_uid": "intro",
                        "heading": "Intro",
                        "heading_level": 1,
                        "anchor": "intro",
                        "url": "https://example.org/#intro",
                        "github_url": "https://github.com/example/repo/blob/abc/index.md#L1-L10",
                        "text": "Intro text",
                    },
                    {
                        "section_uid": "second",
                        "heading": "Second",
                        "heading_level": 2,
                        "anchor": "second",
                        "url": "https://example.org/#second",
                        "github_url": "https://github.com/example/repo/blob/abc/index.md#L11-L20",
                        "text": "Second text",
                    },
                ],
            },
            {
                "chapter": "p2-200-text",
                "status": "published",
                "url": "https://example.org/p2-200-text/",
                "sections": [
                    {
                        "section_uid": "digital_format_freedom",
                        "heading": "Цифрой формат = Свобода",
                        "heading_level": 3,
                        "anchor": "digital_format_freedom",
                        "url": "https://example.org/p2-200-text/#digital_format_freedom",
                        "github_url": "https://github.com/example/repo/blob/abc/p2-200-text.md#L30-L40",
                        "text": "Digital format text",
                    },
                    {
                        "section_uid": "word",
                        "heading": "Слово: ожидания",
                        "heading_level": 3,
                        "anchor": "word",
                        "url": "https://example.org/p2-200-text/#word",
                        "github_url": "https://github.com/example/repo/blob/abc/p2-200-text.md#L41-L60",
                        "text": "Word text",
                    },
                ],
            },
        ],
    }


def test_section_matches_lives_in_hindsight_common():
    # The section filter predicate is shared with the WTD ingest wrapper, so it
    # must be importable from hindsight_common (not only defined locally in
    # hindsight-ingest.py).
    assert callable(common.section_matches)


def test_section_matches_none_filter_matches_every_section():
    section = {"section_uid": "intro", "anchor": "intro"}
    assert common.section_matches(section, None) is True


def test_section_matches_strips_leading_hash():
    section = {"section_uid": "digital_format_freedom", "anchor": "cff"}
    assert common.section_matches(section, "#digital_format_freedom") is True
    assert common.section_matches(section, "#cff") is True


def test_section_matches_accepts_section_uid_and_anchor():
    by_uid = {"section_uid": "word", "anchor": "slovo-ozhidaniya"}
    assert common.section_matches(by_uid, "word") is True
    assert common.section_matches(by_uid, "slovo-ozhidaniya") is True
    assert common.section_matches(by_uid, "something-else") is False


def test_section_matches_missing_fields_do_not_match_nonempty_filter():
    assert common.section_matches({}, "word") is False
    assert common.section_matches({}, None) is True


def test_iter_documents_filters_by_section_uid_globally():
    docs = list(
        hindsight_ingest.iter_documents(
            sample_inventory(),
            chapter_filter=None,
            section_filter="digital_format_freedom",
            chunk_size=8000,
        )
    )

    assert len(docs) == 1
    chapter, section, chunk_idx, chunk_count, chunk = docs[0]
    assert chapter["chapter"] == "p2-200-text"
    assert section["section_uid"] == "digital_format_freedom"
    assert chunk_idx == 0
    assert chunk_count == 1
    assert chunk == "Digital format text"


def test_iter_documents_filters_by_chapter_and_section_uid():
    docs = list(
        hindsight_ingest.iter_documents(
            sample_inventory(),
            chapter_filter="p2-200-text",
            section_filter="word",
            chunk_size=8000,
        )
    )

    assert len(docs) == 1
    chapter, section, _chunk_idx, _chunk_count, chunk = docs[0]
    assert chapter["chapter"] == "p2-200-text"
    assert section["section_uid"] == "word"
    assert chunk == "Word text"


def test_iter_documents_section_filter_accepts_anchor_alias():
    docs = list(
        hindsight_ingest.iter_documents(
            sample_inventory(),
            chapter_filter=None,
            section_filter="intro",
            chunk_size=8000,
        )
    )

    assert len(docs) == 1
    _chapter, section, _chunk_idx, _chunk_count, _chunk = docs[0]
    assert section["section_uid"] == "intro"
    assert section["anchor"] == "intro"
