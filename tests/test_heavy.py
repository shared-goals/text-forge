"""Dovlatov layer: sentences that ask to be split, found by counting alone.

The heavy-sentence scan is deterministic on purpose — a comma rule that allows
both variants is not a finding, but a sentence with three commas is always a
refactoring candidate, on every run, on every machine. The model only supplies
the split variants; the counting is arithmetic.
"""

from text_forge.grammar import AddedLine
from text_forge.heavy import HeavySentence, find_heavy


def _row(text: str, line: int = 1, file: str = "text/p1-a.md") -> AddedLine:
    return AddedLine(file=file, line=line, text=text, commit="abc123")


def test_three_commas_is_heavy():
    text = "Однажды, в студёную, зимнюю, пору я пошёл гулять."
    assert find_heavy([_row(text, line=5)]) == [
        HeavySentence(
            file="text/p1-a.md",
            line=5,
            text=text,
            commas=3,
            words=8,
        )
    ]


def test_twenty_five_words_is_heavy_without_a_single_comma():
    text = " ".join(f"слово{n}" for n in range(25)) + "."
    assert find_heavy([_row(text, line=7)])[0].words == 25


def test_two_commas_and_few_words_is_not_heavy():
    text = "Ведь это, друзья, очевидно."
    assert find_heavy([_row(text)]) == []


def test_each_sentence_of_a_line_is_judged_on_its_own():
    light = "Это лёгкое предложение."
    heavy = "Однажды, в студёную, зимнюю, пору я пошёл по делам."
    result = find_heavy([_row(f"{light} {heavy}", line=3)])
    assert len(result) == 1
    assert result[0].text == heavy
    assert result[0].line == 3


def test_link_targets_do_not_inflate_the_counts():
    # the URL has commas and many "words"; the sentence itself has neither
    text = "См. [заметку](https://example.org/a,b,c,d,e?x=1&y=2) там."
    assert find_heavy([_row(text)]) == []


def test_quote_punctuation_is_kept_in_the_sentence():
    # ellipsis does not glue two sentences together
    text = "Впрочем, стоп, не будем, о грустном… Идём дальше."
    result = find_heavy([_row(text, line=9)])
    assert [r.text for r in result] == ["Впрочем, стоп, не будем, о грустном…"]


def test_file_is_carried_through():
    result = find_heavy(
        [_row("Однажды, в студёную, зимнюю, пору.", line=2, file="text/index.md")]
    )
    assert result[0].file == "text/index.md"
