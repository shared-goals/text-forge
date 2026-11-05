"""Tests for whattodo `make books`: which files the build reads and writes.

The one curation file lives at the CORPUS ROOT as `books_curation.yml`, and the
link map the build produces lands in `<root>/.cache/` — a same-run temp artifact
consumed by the link validation stage, so it sits in the repo's existing
gitignored cache dir rather than beside the notes it describes. Both are
contracts between the build and the repo layout, so they are pinned here with a
fixture corpus rather than against the real one: which path the build opens is a
property of the code, and a fixture makes the answer checkable without a network
or a corpus.
"""

import json

from text_forge import livelib, wtd_books_build

BOOK_ZONA = {
    "book_url": "https://www.livelib.ru/book/1000699994-zona-sergej-dovlatov",
    "title": "Зона", "author": "Сергей Довлатов", "my_mark": 4,
}

# a curation file at the new place, carrying a weight the note must show
CURATION_YML = """# Курация книг: id издания LiveLib -> поля.
# Название справа — для глаз, сборка не читает.

"1000699994":   # Зона — Сергей Довлатов
  weight: 70
"""


class TestCurationDefaultPath:
    """The default is <root>/books_curation.yml, and curation_path overrides."""

    def fixture_root(self, tmp_path):
        """A corpus-shaped root: an export, a text dir, a books dir — and no
        curation file at all until a test puts one somewhere."""
        root = tmp_path / "repo"
        export = root / "livelib-export"
        export.mkdir(parents=True)
        (export / "livelib-books.json").write_text(
            json.dumps([BOOK_ZONA], ensure_ascii=False), encoding="utf-8")
        (export / "livelib-quotes-api.json").write_text("[]", encoding="utf-8")
        (export / "livelib-reviews-api.json").write_text("[]", encoding="utf-8")
        (root / "text" / "books" / "_curation").mkdir(parents=True)
        return root

    def run_main(self, root, monkeypatch, capsys):
        monkeypatch.setattr(wtd_books_build, "export", lambda uid, out: {"stubbed": 0})
        monkeypatch.setattr(wtd_books_build, "LivelibClient",
                          lambda: livelib.LivelibClient(fetch=lambda url: ""))
        code = wtd_books_build.main(str(root))
        return code, capsys.readouterr().out

    def test_root_books_curation_yml_is_the_default(self, tmp_path, monkeypatch,
                                                    capsys):
        """A curation file at <root>/books_curation.yml IS read by a plain run:
        the weight it carries shows up in the note the build writes."""
        root = self.fixture_root(tmp_path)
        (root / "books_curation.yml").write_text(CURATION_YML, encoding="utf-8")
        code, out = self.run_main(root, monkeypatch, capsys)
        assert code == 0, out
        md = (root / "text" / "books" / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "weight: 70" in md, md
        assert "important: true" in md, md

    def test_no_curation_file_anywhere_stops_the_build(self, tmp_path, monkeypatch,
                                                       capsys):
        """A named-but-absent curation file must not mean "no curation": the
        build says so and fails rather than dropping the curation silently."""
        root = self.fixture_root(tmp_path)
        code, out = self.run_main(root, monkeypatch, capsys)
        assert code == 1
        assert "curation file not found" in out, out
        # and it names the path it looked for, so the fix is obvious
        assert str(root / "books_curation.yml") in out, out

    def test_the_old_jsonc_path_is_not_read_as_curation(self, tmp_path, monkeypatch,
                                                        capsys):
        """The build no longer looks at text/books/_curation/curation.jsonc: an
        old file left there is not curation for it, so its weight cannot show up
        in a note — and the root books_curation.yml wins the field instead."""
        root = self.fixture_root(tmp_path)
        old = root / "text" / "books" / "_curation" / "curation.jsonc"
        old.write_text('{"books": {"1000699994": {"weight": 3}}}', encoding="utf-8")
        (root / "books_curation.yml").write_text(CURATION_YML, encoding="utf-8")
        code, out = self.run_main(root, monkeypatch, capsys)
        assert code == 0, out
        md = (root / "text" / "books" / "dovlatov-zona.md").read_text(encoding="utf-8")
        assert "weight: 70" in md, md   # the new file's weight
        assert "weight: 3" not in md, md

    def test_link_map_lands_in_the_cache_dir(self, tmp_path, monkeypatch, capsys):
        """The id -> note map is written to <root>/.cache/link-map.json: it is a
        same-run temp artifact — the link validator consumes it right after — so
        it belongs in the repo's gitignored cache dir, not beside the notes.
        The dir is created by the build, not assumed present."""
        root = self.fixture_root(tmp_path)
        assert not (root / ".cache").exists()
        (root / "books_curation.yml").write_text(CURATION_YML, encoding="utf-8")
        code, out = self.run_main(root, monkeypatch, capsys)
        assert code == 0, out
        link_map = root / ".cache" / "link-map.json"
        assert link_map.exists()
        assert "https://www.livelib.ru/book/1000699994" in link_map.read_text(encoding="utf-8")

    def test_link_map_is_no_longer_written_beside_the_notes(self, tmp_path, monkeypatch,
                                                           capsys):
        """The old place stays empty: `_curation/` keeps whatever the corpus
        carries there, and the build adds no link-map.json to it."""
        root = self.fixture_root(tmp_path)
        (root / "books_curation.yml").write_text(CURATION_YML, encoding="utf-8")
        code, out = self.run_main(root, monkeypatch, capsys)
        assert code == 0, out
        assert not (root / "text" / "books" / "_curation" / "link-map.json").exists()
