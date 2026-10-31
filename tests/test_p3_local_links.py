"""Tests for the p3 projection's LOCAL link targets and status lists.

Every bibliography bullet targets the site's own book page (`/books/<slug>/`) —
the target is the note the generator just read, so there is no resolution step
and no livelib URL left on the page. Collapsed status lists below the bullets
come from the notes' frontmatter `status:`; a note that names no shelf is
reported by warn().

These tests used to cover the read-back shapes too (curated `lines=` inputs,
livelib targets kept verbatim, links resolving through `_curation` mappings).
That subject no longer exists: the page is written from scratch, so those cases
were DELETED, not weakened — the surviving ones describe the renderer as it is.
"""

from text_forge.wtd_books_p3 import (
    P3_FRONTMATTER,
    P3_INTRO,
    P3_TITLE,
    render_p3_references,
)

STATUS_ORDER = ["Читаю", "Прочтённые", "Недочитанные", "Хочу прочитать"]


def note(title, book_id, *, review=None, status=None, important=None, weight=None):
    fm = ["---", f'title: "{title}"', "tags:", "  - book"]
    if status:
        fm.append(f"status: {status}")
    if important:
        fm.append("important: true")
    if weight is not None:
        fm.append(f"weight: {weight}")
    fm.append(f'livelib_book: "https://www.livelib.ru/book/{book_id}"')
    if review:
        fm.append(f'livelib_review: "https://www.livelib.ru/review/{review}"')
    return (
        "\n".join(fm)
        + "\n---\n\n> Цитата ^quote_1\n\n— [LiveLib](https://www.livelib.ru/quote/1)\n"
    )


def _fm_note(title, book_id, *, status=None):
    """A frontmatter note WITHOUT any `status:` key — a note that names no shelf.

    `note()` above cannot express this (it omits the key only when status is
    falsy, which the reader then sees as the explicit 'none'), so the fixture
    writes the block directly.
    """
    fm = [
        "---",
        f'title: "{title}"',
        "tags:",
        "  - book",
        f'livelib_book: "https://www.livelib.ru/book/{book_id}"',
    ]
    if status is not None:
        fm.append(f"status: {status}")
    return (
        "\n".join(fm)
        + "\n---\n\n> Цитата ^quote_1\n\n— [LiveLib](https://www.livelib.ru/quote/1)\n"
    )


def write_books(tmp_path, **notes):
    d = tmp_path / "books"
    d.mkdir(parents=True, exist_ok=True)
    for slug, md in notes.items():
        (d / f"{slug}.md").write_text(md, encoding="utf-8")
    return d


REVIEW_1 = {
    "id": "1",
    "title": "Тезис А",
    "url": "/review/1",
    # a review is about an edition: the export names the edition by
    # /book/<id>|/work/<id>, and a cited review must name the very
    # edition the note declares (see note()/note_ids below)
    "art_edition": {"id": "100", "url": "/book/100"},
}
REVIEW_2 = {
    "id": "2",
    "title": "Тезис Б",
    "url": "/review/2",
    "art_edition": {"id": "2", "url": "/book/2"},
}
REVIEW_FOREIGN = {
    "id": "9999999",
    "title": "Чужой тезис",
    "url": "/review/9999999",
    # the export says this review is about ANOTHER work, so the
    # note may not cite it: the bullet carries no thesis at all
    "art_edition": {"id": "8888888", "url": "/book/8888888"},
}


class TestLocalTargets:
    def test_important_book_links_local_page(self, tmp_path):
        # book id 100 == the edition review 1 is about, so the note can cite its
        # own review: thesis from the review, text from the note, target local
        books = write_books(
            tmp_path,
            abe=note(
                "Четвертый ледниковый период",
                "100",
                review="1",
                important=True,
                weight=1,
            ),
        )
        out = render_p3_references(books, [REVIEW_1])
        assert "- Тезис А: [Четвертый ледниковый период](/books/abe/)" in out["text"]
        assert "livelib.ru" not in out["text"].split("///")[0]

    def test_book_without_review_links_local_page(self, tmp_path):
        books = write_books(
            tmp_path, abe=note("Икс", "1005497029", important=True, weight=1)
        )
        out = render_p3_references(books, [])
        assert "- [Икс](/books/abe/)" in out["text"]

    def test_a_note_that_is_not_important_is_not_cited(self, tmp_path):
        """Importance decides the bibliography — and nothing else can add a line.

        Regression this pins: a /review/ link used to be pulled into the page by
        reading the previous page back, which let a book whose curation weight was
        removed keep its bullet. With no read-back, only `important: true` writes
        a bullet: the note still owns its page (and its shelf entry), but the
        bibliography says nothing about it.
        """
        books = write_books(
            tmp_path,
            master=note(
                "Мастер и Маргарита", "1000736563", review="4002646", status="read"
            ),
        )
        out = render_p3_references(
            books,
            [
                {
                    "id": "4002646",
                    "title": "Тезис",
                    "url": "/review/4002646",
                    "art_edition": {"id": "1000736563", "url": "/book/1000736563"},
                }
            ],
        )
        assert out["items"] == []
        assert "livelib.ru/review/4002646" not in out["text"]
        # the page still exists and the shelf still lists it
        assert out["text"].startswith(f"{P3_FRONTMATTER}\n# {P3_TITLE}\n\n{P3_INTRO}\n")
        assert "- [Мастер и Маргарита](/books/master/)" in out["text"]

    def test_foreign_review_is_not_cited_and_leaves_no_url(self, tmp_path):
        """A review belonging to another work is neither thesis nor target."""
        books = write_books(
            tmp_path,
            a=note("А", "1", review="9999999", status="none", important=True, weight=1),
        )
        out = render_p3_references(books, [REVIEW_FOREIGN])
        assert out["items"] == ["- [А](/books/a/)"]
        assert "livelib.ru" not in out["text"]
        assert [w["reason"] for w in out["warnings"]] == ["foreign-review"]


class TestStatusSections:
    def test_sections_appear_after_important_lines(self, tmp_path):
        # book id = the edition its review is about, so the review supplies the
        # thesis and the bullet is a full 'thesis: [title](target)' line
        books = write_books(
            tmp_path,
            a=note("А", "100", review="1", status="read", important=True, weight=1),
            b=note("Б", "2", status="wish"),
        )
        out = render_p3_references(books, [REVIEW_1])
        lines = out["text"].splitlines()
        bullet = next(i for i, l in enumerate(lines) if l.startswith("- Тезис А"))
        details = [i for i, l in enumerate(lines) if l.startswith("/// details")]
        assert details and all(i > bullet for i in details)

    def test_section_titles_and_counts(self, tmp_path):
        books = write_books(
            tmp_path,
            r1=note("Читаю-книга", "1", status="reading"),
            x1=note("ПрочТ", "2", status="read"),
            x2=note("яндекс", "3", status="read"),
            u1=note("Унижение", "4", status="unread"),
            w1=note("Хочу", "5", status="wish"),
            w2=note("Хочу ثانية", "6", status="wish"),
        )
        out = render_p3_references(books, [])
        for expected in (
            "/// details | Читаю (1)",
            "/// details | Прочтённые (2)",
            "/// details | Недочитанные (1)",
            "/// details | Хочу прочитать (2)",
        ):
            assert expected in out["text"], expected

    def test_section_order_is_reading_read_unread_wish(self, tmp_path):
        books = write_books(
            tmp_path,
            r=note("Читаю-книга", "1", status="reading"),
            p=note("ПрочТ", "2", status="read"),
            n=note("Недочитано", "3", status="unread"),
            h=note("Хочу", "4", status="wish"),
        )
        out = render_p3_references(books, [])
        found = [l for l in out["text"].splitlines() if l.startswith("/// details |")]
        assert [
            f.split("|")[1].strip().rsplit(" (", 1)[0] for f in found
        ] == STATUS_ORDER

    def test_book_lines_local_and_alphabetical(self, tmp_path):
        """Cyrillic sort must not fall apart — title order, not byte order."""
        books = write_books(
            tmp_path,
            ya=note("Яблоко", "1", status="read"),
            aa=note("Антоновка", "2", status="read"),
            ya2=note("Ярмо", "3", status="read"),
        )
        out = render_p3_references(books, [])
        body = out["text"].split("/// details | Прочтённые (3)")[1]
        got = [l for l in body.splitlines() if l.startswith("- [")]
        assert got == [
            "- [Антоновка](/books/aa/)",
            "- [Яблоко](/books/ya/)",
            "- [Ярмо](/books/ya2/)",
        ]

    def test_closing_marker_after_each_section(self, tmp_path):
        books = write_books(tmp_path, x=note("ПрочТ", "1", status="read"))
        out = render_p3_references(books, [])
        assert out["text"].count("///") == 2  # one open, one close
        assert "///" in out["text"]

    def test_status_none_or_missing_is_not_rendered(self, tmp_path):
        books = write_books(
            tmp_path,
            n=note("Нет статуса", "1", status="none"),
            m=_fm_note("Без статуса", "2"),
        )
        out = render_p3_references(books, [])
        assert "///" not in out["text"]

    def test_explicit_none_status_is_not_a_warning(self, tmp_path):
        """`status: none` says "on no shelf" — clean, not an anomaly."""
        books = write_books(tmp_path, n=note("Нет статуса", "1", status="none"))
        out = render_p3_references(books, [])
        assert out["warnings"] == []

    def test_missing_status_warns_once_per_book(self, tmp_path):
        # only a note with NO `status:` key at all is a reportable gap; the one
        # that says `status: none` is deliberately off every shelf (silent)
        books = write_books(
            tmp_path,
            n=note("Нет статуса", "1", status="none"),
            m=_fm_note("Без статуса", "2"),
        )
        out = render_p3_references(books, [])
        warned = sorted(
            w["slug"] for w in out["warnings"] if w["reason"] == "no status"
        )
        assert warned == ["m"]

    def test_important_book_without_status_is_not_in_a_section(self, tmp_path):
        # a book the page cites but that sits on no shelf: it appears in the
        # bibliography only, and the missing status is reported, not guessed
        books = write_books(
            tmp_path,
            a=note("А", "100", review="1", status="none", important=True, weight=1),
        )
        out = render_p3_references(books, [REVIEW_1])
        assert "- Тезис А: [А](/books/a/)" in out["text"]
        assert "///" not in out["text"]

    def test_empty_corpus_emits_no_sections(self, tmp_path):
        out = render_p3_references(write_books(tmp_path), [])
        assert out["text"] == f"{P3_FRONTMATTER}\n# {P3_TITLE}\n\n{P3_INTRO}\n"


class TestByteStability:
    def test_two_runs_same_bytes(self, tmp_path):
        books = write_books(
            tmp_path,
            a=note("А", "1", review="1", status="read", important=True, weight=1),
            b=note("Б", "2", review="2", status="read", important=True, weight=2),
            c=note("В", "3", status="wish"),
            d=note("Г", "4", status="none"),
        )
        first = render_p3_references(books, [REVIEW_1, REVIEW_2])
        second = render_p3_references(books, [REVIEW_1, REVIEW_2])
        assert first["text"] == second["text"]
        assert first["warnings"] == second["warnings"]
