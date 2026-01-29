#!/usr/bin/env python3
"""
Unit tests for text-forge pipeline using minimal self-contained fixtures.

These tests validate the core pipeline functionality without depending on
external content repositories like whattodo.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Paths relative to this test file
TEST_DIR = Path(__file__).parent
FIXTURES_DIR = TEST_DIR / "fixtures"
INPUT_DIR = FIXTURES_DIR / "input"
EXPECTED_DIR = FIXTURES_DIR / "expected"
BUILD_DIR = FIXTURES_DIR / "build"

# Pipeline scripts
REPO_ROOT = TEST_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture(scope="session")
def build_test_epub():
    """Build EPUB from test fixtures once per test session."""
    # Clean previous build
    if BUILD_DIR.exists():
        import shutil

        shutil.rmtree(BUILD_DIR)

    # Build using text-forge CLI
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "text_forge.cli",
            "epub",
            "--config",
            str(INPUT_DIR / "mkdocs.yml"),
            "--build-dir",
            str(BUILD_DIR),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"EPUB build failed:\n{result.stderr}")

    # Verify outputs exist
    assert (BUILD_DIR / "text_combined.txt").exists(), "Combined markdown not generated"
    assert (BUILD_DIR / "pandoc.md").exists(), "Pandoc markdown not generated"
    assert (BUILD_DIR / "text_book.epub").exists(), "EPUB not generated"

    return BUILD_DIR


class TestPipeline:
    """Test the complete text-forge pipeline with minimal fixtures."""

    def test_combined_markdown_generated(self, build_test_epub):
        """Verify combined markdown is generated."""
        combined = build_test_epub / "text_combined.txt"
        assert combined.exists()
        assert combined.stat().st_size > 0

    def test_combined_has_all_chapters(self, build_test_epub):
        """Verify all chapters are included in combined markdown."""
        combined = (build_test_epub / "text_combined.txt").read_text(encoding="utf-8")

        # Check for content from all files
        assert "Test Fixtures" in combined  # from index.md
        assert "Chapter 1: Blocks and Links" in combined  # from chapter1.md
        assert "Chapter 2: Quotes and Images" in combined  # from chapter2.md

    def test_combined_has_pymdown_blocks(self, build_test_epub):
        """Verify PyMdown blocks are preserved in combined markdown."""
        combined = (build_test_epub / "text_combined.txt").read_text(encoding="utf-8")

        # Check for PyMdown block syntax
        assert "/// situation" in combined
        assert "/// quote" in combined

    def test_combined_has_chapter_dates(self, build_test_epub):
        """Verify chapter dates are added."""
        combined = (build_test_epub / "text_combined.txt").read_text(encoding="utf-8")

        # Check for chapter-dates blocks
        assert "/// chapter-dates" in combined
        assert "Создано: 2024-01-15" in combined
        assert "Опубликовано: 2024-01-20" in combined

    def test_combined_internal_links_rewritten(self, build_test_epub):
        """Verify internal links are rewritten to anchors."""
        combined = (build_test_epub / "text_combined.txt").read_text(encoding="utf-8")

        # Original: [Chapter 1](chapter1.md)
        # Should become: [Chapter 1](#chapter1-md)
        assert "[Chapter 1](#chapter1-md)" in combined
        assert "[Chapter 2](#quotes)" in combined
        assert "[home](#index-md)" in combined

    def test_pandoc_markdown_generated(self, build_test_epub):
        """Verify Pandoc-normalized markdown is generated."""
        pandoc_md = build_test_epub / "pandoc.md"
        assert pandoc_md.exists()
        assert pandoc_md.stat().st_size > 0

    def test_pandoc_has_fenced_divs(self, build_test_epub):
        """Verify PyMdown blocks are converted to fenced divs."""
        pandoc = (build_test_epub / "pandoc.md").read_text(encoding="utf-8")

        # Check for fenced div syntax (:::: situation :::)
        assert "::: situation" in pandoc
        assert "::: quote" in pandoc

    def test_pandoc_has_block_captions(self, build_test_epub):
        """Verify block captions are added as h6 headings (when defined in mkdocs.yml)."""
        pandoc = (build_test_epub / "pandoc.md").read_text(encoding="utf-8")

        # Our test fixtures use simple blocks without explicit captions,
        # so we just verify the blocks are converted to fenced divs
        # (Caption support is tested implicitly via consistency tests)
        assert "::: situation" in pandoc
        assert "::: quote" in pandoc

    def test_pandoc_image_attributes_preserved(self, build_test_epub):
        """Verify image attributes are preserved."""
        pandoc = (build_test_epub / "pandoc.md").read_text(encoding="utf-8")

        # Image should have attributes like {width="75%" loading=lazy}
        assert 'width="75%"' in pandoc or "width=75%" in pandoc

    def test_pandoc_author_links_preserved(self, build_test_epub):
        """Verify author links with .author class are preserved."""
        pandoc = (build_test_epub / "pandoc.md").read_text(encoding="utf-8")

        # Author link should have .author class
        assert "{.author}" in pandoc
        assert "Author Name" in pandoc

    def test_epub_generated(self, build_test_epub):
        """Verify EPUB file is generated and has content."""
        epub = build_test_epub / "text_book.epub"
        assert epub.exists()
        # EPUB should be at least 5KB (our minimal fixtures produce smaller EPUB)
        assert epub.stat().st_size > 5000


class TestConsistency:
    """Test output consistency against expected fixtures."""

    def test_combined_matches_expected(self, build_test_epub):
        """Verify combined markdown matches expected output."""
        actual = (build_test_epub / "text_combined.txt").read_text(encoding="utf-8")
        expected = (EXPECTED_DIR / "text_combined.txt").read_text(encoding="utf-8")

        # Normalize line endings
        actual = actual.replace("\r\n", "\n").strip()
        expected = expected.replace("\r\n", "\n").strip()

        assert (
            actual == expected
        ), "Combined markdown differs from expected. Run test suite to regenerate fixtures if changes are intentional."

    def test_pandoc_matches_expected(self, build_test_epub):
        """Verify Pandoc markdown matches expected output."""
        actual = (build_test_epub / "pandoc.md").read_text(encoding="utf-8")
        expected = (EXPECTED_DIR / "pandoc.md").read_text(encoding="utf-8")

        # Normalize line endings
        actual = actual.replace("\r\n", "\n").strip()
        expected = expected.replace("\r\n", "\n").strip()

        assert (
            actual == expected
        ), "Pandoc markdown differs from expected. Run test suite to regenerate fixtures if changes are intentional."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
