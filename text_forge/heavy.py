"""Dovlatov layer: heavy sentences, found by counting — not by a model.

A comma rule that allows both variants makes two runs disagree: the first puts
the comma in, the second takes it out. Counting does not argue. A sentence with
3+ commas or 25+ words is a refactoring candidate on every run, and the fix for
it is not punctuation — it is a split.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from text_forge.grammar import AddedLine, normalize_link_targets

#: 3+ commas or 25+ words — the author's call, one knob to turn.
COMMA_LIMIT = 3
WORD_LIMIT = 25

#: sentence ends: . ! ? or the ellipsis character, followed by whitespace
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class HeavySentence:
    """One sentence asking to be split, with the address of its line."""

    file: str
    line: int
    text: str
    commas: int
    words: int


def split_sentences(text: str) -> list[str]:
    """Sentences of one markdown line, non-empty ones only.

    Abbreviations (`т.д.`, `т.е.`) split early, which only makes the counts
    smaller — a conservative miss, never a false candidate.
    """
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def find_heavy(rows: Sequence[AddedLine]) -> list[HeavySentence]:
    """Heavy sentences of the kept rows, in file and line order.

    Link targets are stripped before counting (`normalize_link_targets`), so a
    URL full of commas never turns its sentence into a candidate.
    """
    found: list[HeavySentence] = []
    for row in rows:
        text = normalize_link_targets(row.text)
        for sentence in split_sentences(text):
            commas = sentence.count(",")
            words = len(sentence.split())
            if commas >= COMMA_LIMIT or words >= WORD_LIMIT:
                found.append(
                    HeavySentence(
                        file=row.file,
                        line=row.line,
                        text=sentence,
                        commas=commas,
                        words=words,
                    )
                )
    return found
