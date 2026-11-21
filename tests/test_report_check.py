"""Tests for `text_forge.report_check`: report addresses and quotes against disk.

The report is written by a model, and a model can invent a `file:line`. These
tests pin the two halves of the guard: a real finding passes, and every way an
address can be wrong is reported by name rather than silently counted as fine.
"""

import pathlib
from dataclasses import FrozenInstanceError

import pytest

from text_forge.report_check import (
    AddressCheck,
    Finding,
    check_findings,
    normalize,
    parse_findings,
)

SAMPLE = """# Грамотный отчёт

## Находки

### 1 — опечатка · low
`text/p1-a.md:2`
> Исходный  текст.

### 2 — настоящая ошибка · high
`text/p1-a.md:4`
> Бежим [по ссылке](https://example.org) дальше.

### 3 — без адреса · low
> что-то не так
"""


@pytest.fixture
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    chapter = tmp_path / "text" / "p1-a.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(
        "## Глава {#x}\nИсходный  текст.\n\nБежим [по ссылке](https://example.org) дальше.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_normalize_strips_link_targets_and_markup():
    assert (
        normalize("Бежим [по ссылке](https://example.org) дальше.")
        == "Бежим по ссылке дальше."
    )
    assert normalize("  *курсив*  и  `код`  ") == "курсив и код"


def test_normalize_treats_ellipsis_as_a_boundary():
    assert normalize("Начало… конец") == "Начало конец"
    assert normalize("Начало... конец") == "Начало конец"


def test_parse_findings_reads_address_and_quote():
    findings = parse_findings(SAMPLE)
    assert [f.file for f in findings] == ["text/p1-a.md", "text/p1-a.md", ""]
    assert findings[0].line == 2
    assert findings[0].quote == "Исходный  текст."
    assert findings[2].line == 0


def test_parse_findings_keeps_the_heading_as_the_label():
    findings = parse_findings(SAMPLE)
    assert findings[1].label.startswith("### 2")
    assert "настоящая ошибка" in findings[1].label


def test_real_address_and_quote_pass(root):
    result = check_findings(
        root, [Finding(label="l", file="text/p1-a.md", line=2, quote="Исходный текст.")]
    )
    assert result.ok == 1
    assert result.mismatched == ()


def test_quote_reads_without_the_link_target(root):
    """The report prints the quote as it reads; the file keeps `](...)`."""
    finding = Finding(
        label="l", file="text/p1-a.md", line=4, quote="Бежим по ссылке дальше."
    )
    assert check_findings(root, [finding]).ok == 1


def test_truncated_quote_passes_when_words_follow_in_order(root):
    finding = Finding(label="l", file="text/p1-a.md", line=4, quote="Бежим … дальше.")
    assert check_findings(root, [finding]).ok == 1


def test_quote_on_the_wrong_line_names_the_line_it_is_on(root):
    """Text edited after the run: the address drifts, the quote is intact."""
    finding = Finding(label="l", file="text/p1-a.md", line=1, quote="Исходный текст.")
    result = check_findings(root, [finding])
    assert result.ok == 0
    assert result.mismatched[0].moved_to == 2


def test_invented_quote_has_no_line_to_point_at(root):
    finding = Finding(
        label="l", file="text/p1-a.md", line=2, quote="Совсем другой текст."
    )
    result = check_findings(root, [finding])
    assert result.ok == 0
    assert len(result.mismatched) == 1
    assert result.mismatched[0].actual.startswith("Исходный")
    assert result.mismatched[0].moved_to is None


def test_unknown_file_is_reported_not_ignored(root):
    result = check_findings(
        root, [Finding(label="l", file="text/nope.md", line=1, quote="x")]
    )
    assert result.missing_files == ("text/nope.md",)
    assert result.ok == 0


def test_line_past_the_end_is_reported(root):
    result = check_findings(
        root, [Finding(label="l", file="text/p1-a.md", line=99, quote="x")]
    )
    assert result.out_of_range == (("text/p1-a.md", 99),)


def test_finding_without_address_is_counted_separately(root):
    result = check_findings(root, parse_findings(SAMPLE))
    assert result.no_address == 1


def test_missing_address_alone_does_not_fail_the_default_check(root):
    result = check_findings(root, [Finding(label="l", file="", line=0, quote="")])
    assert result.failed(strict=False) is False
    assert result.failed(strict=True) is True


def test_sample_report_passes_for_the_two_real_findings(root):
    result = check_findings(root, parse_findings(SAMPLE)[:2])
    assert result.ok == 2
    assert result.failed(strict=True) is False


def test_address_check_is_a_value_not_a_workbench():
    """The result is returned complete; a caller cannot poke at it afterwards."""
    result = AddressCheck()
    with pytest.raises(FrozenInstanceError):
        result.ok = 5  # type: ignore[misc]


# --- форма цитаты: контракт, а не догадка -----------------------------------
# Отчёт — не свободный текст: цитата обязана быть одной строкой, взятой из файла.
# Две ошибки формы опаснее неверного адреса, потому что выглядят как «проверено».


def test_parse_findings_keeps_every_quote_line():
    finding = parse_findings(
        "### 1 — x\n`text/p1-a.md:2`\n> первая строка\n> вторая строка\n"
    )[0]
    assert finding.quote == "первая строка\nвторая строка"


def test_multiline_quote_is_a_contract_violation(root):
    """Проверять только первую строку — значит пропустить выдумку во второй."""
    finding = Finding(
        label="l",
        file="text/p1-a.md",
        line=2,
        quote="Исходный текст.\nЭТОЙ СТРОКИ В ФАЙЛЕ НЕТ",
    )
    result = check_findings(root, [finding])
    assert result.ok == 0
    assert result.mismatched[0].reason == "multi"
    assert result.mismatched[0].quote_lines == 2


def test_compound_quote_is_a_contract_violation(root):
    """`A / B` — склейка разных мест; проверке нужно сказать, где каждое."""
    finding = Finding(
        label="l",
        file="text/p1-a.md",
        line=2,
        quote="Исходный текст. / Бежим по ссылке дальше. / Выдуманный кусок",
    )
    result = check_findings(root, [finding])
    assert result.ok == 0
    assert result.mismatched[0].reason == "compound"
    assert result.mismatched[0].fragments == (
        ("Исходный текст.", 2),
        ("Бежим по ссылке дальше.", 4),
        ("Выдуманный кусок", None),
    )


def test_single_line_quote_is_still_fine(root):
    """Правило не должно ломать нормальный отчёт."""
    finding = Finding(label="l", file="text/p1-a.md", line=2, quote="Исходный текст.")
    assert check_findings(root, [finding]).mismatched == ()
