"""The book side: a video marker must leave the EPUB as a link, never an iframe.

Two things are checked end to end, because both used to fail silently:

* pandoc used to download the embedded URL and store the fetched page inside the
  EPUB as a media file, with an invalid `<embed>` and a "type:video" caption;
* a raw `<iframe>` carrying a bare boolean attribute made the chapter XHTML
  unparseable, and e-readers dropped the rest of the chapter.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from text_forge.build import normalize_markdown
from text_forge.epub_check import validate_epub

VIDEO = "LN6jA_brXXs"
REPO_ROOT = Path(__file__).parent.parent

MKDOCS_YML = """\
site_name: Video probe
site_url: https://example.com/probe/
docs_dir: docs
site_dir: site
nav:
  - index.md
"""


def write_project(root: Path, chapter: str) -> Path:
    docs = root / "docs"
    docs.mkdir(parents=True)
    (root / "mkdocs.yml").write_text(MKDOCS_YML, encoding="utf-8")
    (docs / "index.md").write_text(chapter, encoding="utf-8")
    return root / "mkdocs.yml"


def normalize(tmp_path: Path, markdown: str) -> str:
    source = tmp_path / "in.md"
    source.write_text(markdown, encoding="utf-8")
    target = tmp_path / "out.md"
    normalize_markdown(source, target)
    return target.read_text(encoding="utf-8")


class TestNormalize:
    def test_marker_becomes_a_watch_link(self, tmp_path):
        out = normalize(
            tmp_path,
            f'Перед.\n\n![type:video](https://www.youtube.com/embed/{VIDEO} "Webzavod 1997")\n\nПосле.\n',
        )
        assert f"youtu.be/{VIDEO}" in out
        assert "Webzavod 1997" in out  # the markdown title becomes the link text
        assert "iframe" not in out
        assert "type:video" not in out

    def test_marker_without_title_gets_a_fallback_text(self, tmp_path):
        out = normalize(tmp_path, f"![type:video](https://youtu.be/{VIDEO})\n")
        assert f"youtu.be/{VIDEO}" in out
        assert "Watch on YouTube" in out

    def test_raw_iframe_becomes_a_watch_link(self, tmp_path):
        out = normalize(
            tmp_path,
            f'<iframe src="https://www.youtube-nocookie.com/embed/{VIDEO}" '
            'title="Reel" frameborder="0" allowfullscreen></iframe>\n',
        )
        assert f"youtu.be/{VIDEO}" in out
        assert "iframe" not in out
        assert "allowfullscreen" not in out

    def test_ordinary_images_are_untouched(self, tmp_path):
        out = normalize(tmp_path, "![Схема](img/schema.png)\n")
        assert "img/schema.png" in out
        assert "youtu.be" not in out


def run_epub(mkdocs_yml: Path, build_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "text_forge.cli", "epub",
         "--config", str(mkdocs_yml), "--build-dir", str(build_dir)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


class TestEpubPipeline:
    def test_marker_chapter_builds_a_valid_epub(self, tmp_path):
        mkdocs_yml = write_project(
            tmp_path / "marker",
            f'# Глава\n\n![type:video](https://www.youtube.com/embed/{VIDEO} "Webzavod 1997")\n\nТекст.\n',
        )
        result = run_epub(mkdocs_yml, tmp_path / "marker" / "build")
        assert result.returncode == 0, result.stderr
        epub = tmp_path / "marker" / "build" / "text_book.epub"
        validate_epub(epub)  # no exception: the book is well-formed
        assert b"shtml" not in epub.read_bytes()  # nothing downloaded from the URL

    def test_invalid_xhtml_fails_the_build_with_a_pointer(self, tmp_path, monkeypatch):
        # Pandoc normalises bare attributes on elements it parses natively, so the
        # broken book is injected where pandoc writes it: the point of the test is
        # that the pipeline refuses to finish when the output cannot be parsed.
        import zipfile

        from text_forge import build as build_module
        from text_forge.epub_check import EpubValidationError

        project = tmp_path / "broken"
        mkdocs_yml = write_project(project, "# Глава\n\nТекст.\n")

        def write_broken_epub(markdown_path, metadata_path, css_path, cover_path,
                              output_path, docs_dir):
            with zipfile.ZipFile(output_path, "w") as epub:
                epub.writestr("mimetype", "application/epub+zip")
                epub.writestr(
                    "EPUB/text/ch003.xhtml",
                    '<html><body><iframe src="x" allowfullscreen></iframe></body></html>',
                )

        monkeypatch.setattr(build_module, "build_epub_with_pandoc", write_broken_epub)
        with pytest.raises(EpubValidationError) as error:
            build_module.build_epub_pipeline(mkdocs_yml, project / "build")
        message = str(error.value)
        assert "EPUB/text/ch003.xhtml" in message
        assert "not well-formed" in message
