"""Migrate the old JSONC curation file to the markdown sections file.

    python -m text_forge.migrate_curation <in.jsonc> <out.md>

One-off, but repeatable: the same input always yields the same bytes, so a
re-run diffs empty and the migration stays auditable after the fact.

What it does:

* reads the old file with its own JSONC scanner — the loader's comment stripper
  was deleted when the format changed, and this module is the only place that
  syntax still has a right to exist;
* multiplies every `weight` by 10, which is why the migration exists at all:
  1..35 leaves no room to insert a book between two neighbours, 10..350 does;
* carries each entry's title across: `// title` above a key, or `// title`
  trailing a one-line entry, becomes the heading's eye text;
* orders sections by weight ascending, then the weightless entries by id, so the
  file reads as a ranked list with an unranked tail;
* drops `my_mark` (it reaches the frontmatter from LiveLib shelf data, never
  from curation) and any section other than `books`.
"""

import argparse
import json
import re
import sys
from pathlib import Path

#: old jsonc key -> new bullet key, in the order bullets are emitted
CURATION_MERGE_ORDER = ("weight", "author", "status", "merges")

#: the weight factor: the whole point of migrating, so it is a named constant
#: rather than a `* 10` someone has to look up
WEIGHT_FACTOR = 10

#: the header every migrated file carries: the format's only documentation,
#: written for a reader who does not program. It carries no bullets on purpose:
#: the loader reads a bullet only inside a `## <id>` section, so a bullet here
#: would be a hard error in the very file this module writes.
DOC_BLOCK = """# Curation

Одна секция — одна редакция книги.

Заголовок секции — это id издания с LiveLib: `## <id> — <название>`.
id слева от тире читает сборка; название справа — только для глаз, сборка его
не трогает. Строки ниже — поля секции.

Что можно писать под заголовком секции (любой набор, в любом порядке).
weight — вес книги, целое число. Вес умножен на 10 по сравнению со старым
файлом: между соседними книгами остаются дырки, чтобы новую книгу можно было
вставить между ними, не перекладывая половину списка (15, 25, 110).
merges — id других изданий той же работы, через запятую. Их цитаты и отзыв
достаются этой заметке. author — автор, если LiveLib его не указал или указал
неверно. status — read / reading / stop, если полка LiveLib врёт.

Поля `my_mark` здесь нет: оценку сборка берёт с полки LiveLib, ей и верить.
Пустая секция (без полей) тоже законна: id уже говорит «эта книга в списке».
"""


def scan_jsonc_lines(text: str) -> list:
    """Per line of the file: (json data, raw with trailing comment, whole-line
    comment text).

    `data` is the line with every comment removed, so the file's line numbers
    survive and a json error still points at the real line. `raw` puts back a
    `//` comment that trailed the data: that is the one comment a key can name
    its own entry with (`"1": {"weight": 1}  // Заголовок`). `whole` is the text
    of a comment occupying the line on its own, which names the entry whose key
    sits BELOW it.

    A `//` inside a string is data, so this walks characters instead of regexing
    the text, and `\\"` does not toggle string state: an escaped quote cannot leave
    a following `//` looking like data. A `/* */` span names no entry at all —
    it is prose — but the lines it covered keep their place in the file. (This
    is the scanner the old loader stripped with; it moved here when the loader
    stopped reading JSONC.)
    """
    rows = []
    data_buf, comment_buf = [], []
    # what the current line carries: "" (no comment), "//", or "*"
    marker = [""]
    i, n = 0, len(text)
    in_string = False

    def flush():
        """Hand over the line built so far and start the next one empty."""
        data = "".join(data_buf)
        comment = "".join(comment_buf)
        trails_data = marker[0] == "//" and bool(data.strip())
        whole = comment[2:].strip() if (marker[0] == "//" and not data.strip()) else ""
        rows.append((data, data + (comment if trails_data else ""), whole))
        data_buf.clear()
        comment_buf.clear()
        marker[0] = ""

    while i < n:
        ch = text[i]
        if ch == "\n":
            flush()
            i += 1
            continue
        if in_string:
            if ch == "\\":
                data_buf.append(text[i:i + 2])
                i += 2
                continue
            data_buf.append(ch)
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            data_buf.append(ch)
            i += 1
            continue
        if text[i:i + 2] == "//" and not marker[0]:
            marker[0] = "//"
            while i < n and text[i] != "\n":
                comment_buf.append(text[i])
                i += 1
            continue
        if text[i:i + 2] == "/*" and not marker[0]:
            # a block comment names no entry: swallow it whole, but let the lines
            # it covered keep their place in the file
            marker[0] = "*"
            end = text.find("*/", i + 2)
            stop = n if end == -1 else end + 2
            while i < stop:
                if text[i] == "\n":
                    flush()
                i += 1
            continue
        data_buf.append(ch)
        i += 1
    if data_buf or comment_buf:
        flush()
    return rows


def strip_jsonc_comments(text: str) -> str:
    """The file with comments removed, line numbers intact — for json.loads.

    One line per input line, so a syntax error points at the real line. The
    walking lives in scan_jsonc_lines, the module's one implementation.
    """
    return "\n".join(data for data, _raw, _whole in scan_jsonc_lines(text)) + "\n"


def _title_of(block: list) -> str:
    """The title among the comment lines of one entry's block.

    The old file wrote the title first and its url as a footnote after it:

        // Моменты счастья — Алекс Дубас
        // @url:`https://www.livelib.ru/book/1003047920`

    so the title is the FIRST line that is not an `@url:` footnote.
    """
    for body in block:
        if not body.startswith("@url"):
            return body
    return ""


def _own_title(key: str, raw: str, trailing: str) -> str:
    """The title a key takes from the comment trailing its own line, or ''.

    `raw` still shows the marker, so the key's tail can be read: the comment
    names the key only when that tail is the key's complete value — closed off
    by the end of the line — and not a value still open (`"1": {`).
    """
    if not trailing:
        return ""
    tail = raw[raw.index(f'"{key}"'):]
    tail = tail.split("//", 1)[0]
    closed = (tail.count("{") + tail.count("[")) <= (tail.count("}") + tail.count("]"))
    return _title_of([trailing]) if closed else ""


def _titles_from_comments(text: str) -> dict:
    """Map an edition id to the title held by the comment naming it.

    The old file put a title in either of two places, and both are carried over:

        // Моменты счастья — Алекс Дубас         <- whole-line block above a key
        // @url:`https://www.livelib.ru/book/1`
        "1003047920": {"weight": 1},
        "1000699994": {"status": "read"}  // Зона — Сергей Довлатов

    so an entry takes its own trailing comment when it is written as one line,
    and otherwise the block above its key. `/* */` asides name nothing, and real
    data ends a block. The same look-up names each `merges` member sitting
    inside the array.
    """
    views = scan_jsonc_lines(text)
    n = len(views)

    def block_above(index: int) -> list:
        """The whole-line `//` comments naming the id at `index`, top first."""
        block = []
        j = index - 1
        while j >= 0:
            data, _raw, whole = views[j]
            if whole:
                block.append(whole)
            elif data.strip():
                break  # real data: anything above names some other entry
            j -= 1
        return list(reversed(block))

    titles: dict = {}
    for i, (data, raw, _whole) in enumerate(views):
        keys = list(re.finditer(r'"(\d+)"\s*:', data))
        for key in keys:
            if key.group(1) in titles:
                continue  # a merges member names itself, see below
            # a key takes its title from the comment trailing its own line (the
            # one place a key can name itself), else from the whole-line block
            # written above it
            trailing = raw.split("//", 1)[1].strip() if "//" in raw else ""
            own = _own_title(key.group(1), raw, trailing) if key is keys[-1] else ""
            titles[key.group(1)] = own if own else _title_of(block_above(i))

        # a merges array may break over lines with a comment above each member:
        # walk the lines it spans and let a line holding an id and nothing else
        # take the title of the block above it
        if '"merges"' not in data:
            continue
        last = i
        while data.count("[") > data.count("]") and last + 1 < n:
            last += 1
        for k in range(i + 1, last + 1):
            member = re.fullmatch(r'\s*(\d+)\s*,?\s*', views[k][0])
            if member:
                titles.setdefault(member.group(1), _title_of(block_above(k)))
    return titles


def _section_sort_key(item):
    """Weight ascending, then the weightless entries by id, then id as the
    tiebreaker — a total order, so the file is a function of the data."""
    entry_id, entry = item
    weight = entry.get("weight")
    weight = int(weight) * WEIGHT_FACTOR if weight is not None else None
    return (weight is None, weight if weight is not None else 0, entry_id)


def _eye(ident: str, title: str) -> str:
    """An id plus whatever the eye should read beside it.

    The loader reads only the part before the em dash, so a title (or a run of
    titles, when the old file kept several for one id) goes after it and can
    never steer the build.
    """
    return f"{ident} — {title}" if title else ident


def _section(entry_id: str, entry: dict, titles: dict) -> str:
    """One `## <id> — <title>` heading plus its bullets.

    A title only ever lands in the eye part of a line: the heading's text after
    the em dash, or the ids' own annotation inside the `merges` bullet. That is
    what makes the file safe to hand-edit — a wrong or missing title cannot steer
    the build, because the loader reads ids and keys, never the eye text.
    """
    heading = "## " + _eye(entry_id, titles.get(entry_id, ""))
    lines = [heading]

    for key in CURATION_MERGE_ORDER:
        value = entry.get(key)
        if value is None:
            continue
        if key == "weight":
            lines.append(f"- weight: {int(value) * WEIGHT_FACTOR}")
        elif key == "merges":
            # ids ONLY: the loader parses this value as the id list, so no title
            # may be annotated into it — extra text would make the ids unreadable
            lines.append("- merges: " + ", ".join(str(int(m)) for m in value))
        else:
            lines.append(f"- {key}: {value}")

    return "\n".join(lines)


def migrate_text(jsonc_text: str) -> str:
    """Convert old JSONC curation text to markdown sections text."""
    data = json.loads(strip_jsonc_comments(jsonc_text))
    if not isinstance(data, dict):
        raise ValueError("curation: expected an object at the top level")

    titles = _titles_from_comments(jsonc_text)
    entries = data.get("books") or {}
    if not isinstance(entries, dict):
        raise ValueError("curation: `books` must be an object of edition id -> entry")

    sections = [_section(entry_id, entry, titles)
                for entry_id, entry in sorted(entries.items(), key=_section_sort_key)]
    return DOC_BLOCK + "\n" + "\n\n".join(sections) + ("\n" if sections else "")


def migrate_file(src, out) -> Path:
    """Read <src>.jsonc, write <out>.md, return the output path."""
    text = Path(src).read_text(encoding="utf-8")
    target = Path(out)
    target.write_text(migrate_text(text), encoding="utf-8")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m text_forge.migrate_curation",
        description="Convert the old curation.jsonc into Curation.md "
                    "(markdown sections, weights ×10).")
    parser.add_argument("input", help="path to the old curation.jsonc")
    parser.add_argument("output", help="path to write the new Curation.md")
    args = parser.parse_args(argv)

    try:
        target = migrate_file(args.input, args.output)
    except (OSError, ValueError) as exc:
        # nothing partial is left behind: a half-written Curation.md would drop
        # curation decisions from the next build without saying so
        print(f"curation migration failed: {exc}", file=sys.stderr)
        return 1

    entries = target.read_text(encoding="utf-8").count("\n## ")
    print(f"curation: wrote {target} ({entries} sections, weights ×{WEIGHT_FACTOR})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
