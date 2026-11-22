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
