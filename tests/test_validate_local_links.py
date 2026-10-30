"""Tests for `livelib_outside_books` — the post-rewrite cleanliness check.

After the rewrite pass, no chapter of text/*.md may still carry a livelib.ru
URL: those live only inside text/books/*.md (attribution + frontmatter). The
check reports every offender so `make books` fails loudly on a regression.
"""

import pathlib
import shutil

import pytest

from text_forge.wtd_books import livelib_outside_books, validate_text_links


def write_text(root, name, body):
    t = pathlib.Path(root) / "text"
    t.mkdir(parents=True, exist_ok=True)
    (t / name).write_text(body, encoding="utf-8")
    return t


class TestLivelibOutsideBooks:
    def test_clean_text_reports_nothing(self, tmp_path):
        write_text(tmp_path, "ch.md", "[Книга](/books/abe/) и текст\n")
        assert livelib_outside_books(tmp_path) == []

    def test_chapter_link_is_reported(self, tmp_path):
        write_text(tmp_path, "ch.md",
                   "[Книга](https://www.livelib.ru/book/1001616054)\n")
        found = livelib_outside_books(tmp_path)
        assert len(found) == 1
        assert found[0]["url"] == "https://www.livelib.ru/book/1001616054"
        assert found[0]["file"] == "ch.md"
        assert found[0]["line"] == 1

    def test_every_kind_is_reported(self, tmp_path):
        write_text(tmp_path, "ch.md",
                  "book https://www.livelib.ru/book/1 review "
                  "https://www.livelib.ru/review/2 quote "
                  "https://www.livelib.ru/quote/3 work "
                  "https://www.livelib.ru/work/4\n")
        assert len(livelib_outside_books(tmp_path)) == 4

    def test_http_and_www_variants_reported(self, tmp_path):
        write_text(tmp_path, "ch.md",
                  "http://livelib.ru/book/1\nhttp://www.livelib.ru/review/2\n")
        assert len(livelib_outside_books(tmp_path)) == 2

    def test_slugged_url_kept_in_full(self, tmp_path):
        write_text(tmp_path, "ch.md",
                  "[К](https://www.livelib.ru/book/1001616054-chetvertyy-lednikovyy-period)\n")
        found = livelib_outside_books(tmp_path)
        assert found[0]["url"].endswith("-chetvertyy-lednikovyy-period")

    def test_books_dir_is_excluded(self, tmp_path):
        write_text(tmp_path, "ch.md", "чисто\n")
        books = tmp_path / "text" / "books"
        books.mkdir(parents=True, exist_ok=True)
        (books / "abe.md").write_text(
            '---\nlivelib_book: "https://www.livelib.ru/book/1"\n---\n\n'
            "— [LiveLib](https://www.livelib.ru/quote/2)\n", encoding="utf-8")
        assert livelib_outside_books(tmp_path) == []

    def test_curation_dir_is_excluded(self, tmp_path):
        write_text(tmp_path, "ch.md", "чисто\n")
        cur = tmp_path / "text" / "books" / "_curation"
        cur.mkdir(parents=True, exist_ok=True)
        (cur / "link-map.json").write_text(
            '{"https://www.livelib.ru/book/1": "abe"}', encoding="utf-8")
        assert livelib_outside_books(tmp_path) == []

    def test_several_files_reported_with_paths(self, tmp_path):
        write_text(tmp_path, "a.md", "https://www.livelib.ru/book/1\n")
        write_text(tmp_path, "b.md", "text\nhttps://www.livelib.ru/review/2\n")
        found = livelib_outside_books(tmp_path)
        assert sorted(f["file"] for f in found) == ["a.md", "b.md"]

    def test_missing_text_dir_is_not_an_error(self, tmp_path):
        assert livelib_outside_books(tmp_path) == []

    def test_report_is_sorted_and_stable(self, tmp_path):
        write_text(tmp_path, "b.md",
                  "https://www.livelib.ru/book/2 and https://www.livelib.ru/book/1\n")
        write_text(tmp_path, "a.md", "https://www.livelib.ru/quote/3\n")
        found = livelib_outside_books(tmp_path)
        assert found == sorted(found, key=lambda f: (f["file"], f["line"]))


class TestValidationFlow:
    def test_validate_text_links_carries_the_new_key(self, tmp_path):
        text_dir = write_text(tmp_path, "ch.md",
                             "[Книга](https://www.livelib.ru/book/1001616054)\n")
        res = validate_text_links(text_dir, tmp_path / "books")
        assert "livelib_outside_books" in res
        assert len(res["livelib_outside_books"]) == 1

    def test_clean_text_dir_reports_empty(self, tmp_path):
        text_dir = write_text(tmp_path, "ch.md", "[Книга](/books/abe/)\n")
        res = validate_text_links(text_dir, tmp_path / "books")
        assert res["livelib_outside_books"] == []


class TestBuildReportsIt:
    """`make books` must PRINT the check — the report is only useful if a human
    sees it in the build log.

    Driven on a COPY of the real corpus (read-only source, tmp target): the
    build's own validator stage is checked against real book notes and a real
    export, with the network stage (export) stubbed out. `main()` deletes and
    rewrites text/books/, which is why the corpus is copied first — the real
    repo is never touched.
    """

    REPO = pathlib.Path(__file__).resolve().parents[2] / "whattodo"

    def setup_method(self):
        if not (self.REPO / "livelib-export" / "livelib-books.json").exists():
            pytest.skip("whattodo corpus data not available")

    def corpus_copy(self, tmp_path, chapter_body):
        root = tmp_path / "repo"
        shutil.copytree(self.REPO / "livelib-export", root / "livelib-export")
        shutil.copytree(self.REPO / "text", root / "text")
        (root / "text" / "chapter.md").write_text(chapter_body, encoding="utf-8")
        return root

    def run_main(self, root, monkeypatch, capsys):
        from text_forge import livelib, wtd_books_build

        # the export stage is the network half: stub it, keep everything after
        monkeypatch.setattr(wtd_books_build, "export", lambda uid, out: {"stubbed": 0})
        monkeypatch.setattr(wtd_books_build, "LivelibClient",
                          lambda: livelib.LivelibClient(fetch=lambda url: ""))
        code = wtd_books_build.main(str(root))
        return code, capsys.readouterr().out

    def test_outside_links_are_printed(self, tmp_path, monkeypatch, capsys):
        root = self.corpus_copy(tmp_path, "[Книга](https://www.livelib.ru/book/1001616054)\n")
        code, out = self.run_main(root, monkeypatch, capsys)
        assert "outside-books livelib links:" in out, out
        assert "OUTSIDE BOOKS:" in out and "chapter.md:1" in out, out
        # reported, not fatal: the rewrite is a separate, opt-in step
        assert code == 0, out

    def test_chapters_full_of_livelib_links_are_counted(self, tmp_path, monkeypatch, capsys):
        # the un-rewritten corpus: every chapter link is an outside link, and the
        # count the build prints must equal what the validator finds
        root = self.corpus_copy(tmp_path, "См. https://www.livelib.ru/book/1001616054\n")
        code, out = self.run_main(root, monkeypatch, capsys)
        printed = [l for l in out.splitlines() if l.startswith("outside-books livelib links:")]
        assert len(printed) == 1, out
        n = int(printed[0].rsplit(":", 1)[1])
        assert n >= 200, n                       # the real corpus carries hundreds
        assert code == 0, out
