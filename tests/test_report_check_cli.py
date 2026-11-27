"""CLI tests for `scripts/check-report-addresses.py`.

The wrapper is loaded by path, the same way `tests/test_grammar_cli.py` loads
its script, so importing it has no side effects and the exit codes are pinned.
"""

import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-report-addresses.py"

CLEAN_REPORT = """# Отчёт

### 1 — опечатка · low
`text/p1-a.md:2`
> Исходный текст.
"""

BAD_REPORT = """# Отчёт

### 1 — настоящая ошибка · high
`text/p1-a.md:2`
> Совсем другой текст.
"""

NO_ADDRESS_REPORT = """# Отчёт

### 1 — без адреса · low
> что-то не так
"""


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    chapter = tmp_path / "text" / "p1-a.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("## Глава\nИсходный текст.\n", encoding="utf-8")
    return tmp_path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_report_exits_zero(tmp_path):
    root = _root(tmp_path)
    report = tmp_path / "report.md"
    report.write_text(CLEAN_REPORT, encoding="utf-8")
    proc = _run(str(report), str(root))
    assert proc.returncode == 0, proc.stderr
    assert "every address resolves" in proc.stderr


def test_invented_quote_exits_one_and_prints_both_lines(tmp_path):
    root = _root(tmp_path)
    report = tmp_path / "report.md"
    report.write_text(BAD_REPORT, encoding="utf-8")
    proc = _run(str(report), str(root))
    assert proc.returncode == 1
    assert "quote not in this file" in proc.stderr
    assert "Исходный текст." in proc.stderr


def test_stale_report_says_where_the_quote_moved(tmp_path):
    """The report is from an older run: the quote lives, the line number moved."""
    root = _root(tmp_path)
    report = tmp_path / "report.md"
    report.write_text(
        "# Отчёт\n\n### 1 — опечатка · low\n`text/p1-a.md:1`\n> Исходный текст.\n",
        encoding="utf-8",
    )
    proc = _run(str(report), str(root))
    assert proc.returncode == 1
    assert "line moved" in proc.stderr
    assert "the quote is at 2" in proc.stderr


def test_report_without_findings_exits_two(tmp_path):
    root = _root(tmp_path)
    report = tmp_path / "report.md"
    report.write_text("# Отчёт\n\nничего\n", encoding="utf-8")
    proc = _run(str(report), str(root))
    assert proc.returncode == 2


def test_missing_address_tolerated_by_default_and_rejected_by_strict(tmp_path):
    root = _root(tmp_path)
    report = tmp_path / "report.md"
    report.write_text(NO_ADDRESS_REPORT, encoding="utf-8")
    assert _run(str(report), str(root)).returncode == 0
    assert _run(str(report), str(root), "--strict").returncode == 1


def test_missing_report_exits_one(tmp_path):
    proc = _run(str(tmp_path / "nope.md"), str(tmp_path))
    assert proc.returncode == 1
    assert "report not found" in proc.stderr


# --- форма цитаты ------------------------------------------------------------

MULTI_REPORT = """# Отчёт

### 1 — настоящая ошибка · high
`text/p1-a.md:2`
> Исходный текст.
> ЭТОЙ СТРОКИ В ФАЙЛЕ НЕТ
"""

COMPOUND_REPORT = """# Отчёт

### 1 — тяжёлая фраза · high
`text/p1-a.md:2`
> Исходный текст. / Бежим дальше.
"""


def _wide_root(tmp_path: pathlib.Path) -> pathlib.Path:
    chapter = tmp_path / "text" / "p1-a.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("## Глава\nИсходный текст.\n\nБежим дальше.\n", encoding="utf-8")
    return tmp_path


def test_multiline_quote_exits_one_and_names_the_contract(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(MULTI_REPORT, encoding="utf-8")
    proc = _run(str(report), str(_wide_root(tmp_path)))
    assert proc.returncode == 1
    assert "multi-line quote" in proc.stderr
    assert "2 quote lines" in proc.stderr


def test_compound_quote_exits_one_and_says_where_the_pieces_are(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(COMPOUND_REPORT, encoding="utf-8")
    proc = _run(str(report), str(_wide_root(tmp_path)))
    assert proc.returncode == 1
    assert "compound quote" in proc.stderr
    assert "line 4" in proc.stderr  # the second piece really is there


# --- чистый прогон: ноль находок — это успех, а не поломка ---------------------

NO_FINDINGS_REPORT = """# Отчёт

Проверено 1 строка, заголовок шапки.

## Итог

Находок нет. Разбивок нет. Типографики нет.
"""

def test_clean_report_with_marker_exits_zero(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(NO_FINDINGS_REPORT, encoding="utf-8")
    proc = _run(str(report), str(_root(tmp_path)))
    assert proc.returncode == 0
    assert "clean" in proc.stderr


def test_report_without_findings_or_marker_still_fails(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Отчёт\n\nВсякое, но контракта нет.\n", encoding="utf-8")
    proc = _run(str(report), str(_root(tmp_path)))
    assert proc.returncode == 2
