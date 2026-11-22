import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "hindsight_common.py"
# spec-loading does not add the script's directory to sys.path (unlike
# running the script directly), so sibling imports need it explicitly.
sys.path.insert(0, str(SCRIPT_PATH.parent))

spec = importlib.util.spec_from_file_location("hindsight_common", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
hindsight_common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hindsight_common)


def page(items):
    return {"items": items, "total": len(items)}


def doc(doc_id, tags, updated_at, commit=None):
    metadata = {"commit": commit} if commit else {"session_id": "s1"}
    return {
        "id": doc_id,
        "tags": tags,
        "updated_at": updated_at,
        "document_metadata": metadata,
    }


def test_latest_document_ignores_newer_doc_with_partial_tags():
    """API tag filter is OR, not AND: a newer session doc tagged only `wtd`
    must not shadow the real pipeline ingest (which carries all base tags)."""
    session_doc = doc(
        "session-doc",
        ["wtd", "telegram", "milestone", "changelog"],
        "2026-11-22T03:25:26.906105+00:00",
    )
    pipeline_doc = doc(
        "wtd-current-p2-200-text-obsidian-000",
        ["published", "current", "wtd", "chapter:p2-200-text", "roots"],
        "2026-09-21T16:34:30.547296+00:00",
        commit="cd1323ad915b",
    )
    with patch.object(
        hindsight_common, "request_json", return_value=page([session_doc, pipeline_doc])
    ):
        result = hindsight_common.latest_document("http://api", "hermes")
    assert result is not None
    assert result["id"] == "wtd-current-p2-200-text-obsidian-000"


def test_latest_document_returns_none_when_no_doc_has_all_tags():
    other = doc("lesson-doc", ["wtd", "lesson"], "2026-11-02T02:57:12+00:00")
    with patch.object(hindsight_common, "request_json", return_value=page([other])):
        assert hindsight_common.latest_document("http://api", "hermes") is None


def test_latest_document_picks_newest_doc_with_all_tags():
    older = doc(
        "older", ["wtd", "roots", "current"], "2026-09-01T00:00:00+00:00", commit="aaa"
    )
    newer = doc(
        "newer", ["wtd", "roots", "current"], "2026-10-01T00:00:00+00:00", commit="bbb"
    )
    with patch.object(
        hindsight_common, "request_json", return_value=page([older, newer])
    ):
        assert hindsight_common.latest_document("http://api", "hermes")["id"] == "newer"
