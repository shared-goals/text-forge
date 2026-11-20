"""EPUB XHTML validation: a broken content document must fail the build loudly."""

import zipfile

import pytest

from text_forge.epub_check import EpubValidationError, validate_epub

VALID = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>ok</p></body></html>'
)
BROKEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>before</p>'
    '<iframe src="https://www.youtube.com/embed/LN6jA_brXXs" allowfullscreen></iframe>'
    "<p>after</p></body></html>"
)


def make_epub(path, documents):
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        for name, data in documents.items():
            epub.writestr(name, data)
    return path


def test_well_formed_epub_passes(tmp_path):
    epub = make_epub(
        tmp_path / "ok.epub",
        {"EPUB/text/ch001.xhtml": VALID, "EPUB/content.opf": "<package/>"},
    )
    validate_epub(epub)  # no exception


def test_bare_attribute_is_reported_with_position(tmp_path):
    epub = make_epub(tmp_path / "broken.epub", {"EPUB/text/ch003.xhtml": BROKEN})
    with pytest.raises(EpubValidationError) as error:
        validate_epub(epub)
    message = str(error.value)
    assert "EPUB/text/ch003.xhtml" in message
    assert "allowfullscreen" in message  # the offending line is quoted
    assert ":1:" in message  # line and column are present


def test_error_is_a_value_error_so_the_cli_reports_it_without_a_traceback(tmp_path):
    epub = make_epub(tmp_path / "broken.epub", {"EPUB/text/ch003.xhtml": BROKEN})
    with pytest.raises(ValueError):
        validate_epub(epub)


def test_non_xhtml_entries_are_ignored(tmp_path):
    epub = make_epub(
        tmp_path / "ok.epub",
        {"EPUB/text/ch001.xhtml": VALID, "EPUB/a.ncx": "<ncx><navPoint>"},
    )
    validate_epub(epub)  # no exception: only *.xhtml is checked
