"""Obsidian block ids -> site anchors.

Obsidian marks the end of a block with a trailing `^id` (a block id). MkDocs /
python-markdown does not understand that syntax, so the id is dropped and the
built page has no `#quote_1` for a cross-page link to land on (verified on the
live site: no `id="quote_1"` in the HTML).

`convert_block_ids` rewrites a TRAILING block id into an explicit
`<a id="...</a>`. It is a pure string function used by the MkDocs plugin at
build time, so the markdown on disk keeps the clean Obsidian syntax Obsidian
itself needs, while the site gets a real anchor.

Only a trailing id converts: `^text^` (pymdownx superscript) and a caret with no
text before it on the line are left verbatim, so no prose is eaten.

A HEADING carrying the id converts differently — `## Title <a id="x"></a>` puts
the span INSIDE the heading text, where the toc does not see it as the section
anchor — so a heading gets the attr_list form `## Title {#x}`, which is a real
section id (`attr_list` is enabled in the site's mkdocs.yml).
"""

import re

# a block id sits at the very end of a line: `<space>^id` + optional trailing
# whitespace. The leading whitespace is required — a caret that starts a line is
# not an id — and it is what makes a mid-line caret (`^text^`) survive.
BLOCK_ID = re.compile(r"[ \t]+\^([A-Za-z0-9][A-Za-z0-9_-]*)[ \t]*$")
# an ATX heading, with optional leading spaces; `#` must be followed by whitespace
# or end-of-line, so `#tag` is not a heading
HEADING = re.compile(r"^[ \t]*#{1,6}(?:\s|$)")
FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
FM_FENCE = "---"


def convert_block_ids(markdown: str) -> str:
    """Replace each line-trailing Obsidian block id with an HTML anchor.

    Frontmatter at the top of the file and content inside fenced code blocks are
    left untouched: a `---` block is YAML, not prose, and a code sample must show
    code, not markup.
    """
    out: list[str] = []
    in_code = False
    lines = markdown.split("\n")
    # the frontmatter fence: file opens with `---`, and YAML ends at the next one
    fm_open = lines and lines[0].strip() == FM_FENCE
    for i, line in enumerate(lines):
        if FENCE.match(line):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        if fm_open and i > 0:
            if line.strip() == FM_FENCE:
                out.append(line)
                fm_open = False  # frontmatter closed; prose follows
            else:
                out.append(line)  # still inside frontmatter
            continue
        out.append(_convert_line(line))
    return "\n".join(out)


def _convert_line(line: str) -> str:
    """One prose line: heading -> `{#id}`, anything else -> `<a id="..."></a>`."""
    # the braces are spelled outside the f-string: the attr_list shape would
    # need `{{#…}}` escapes, and plain concatenations keep both shapes readable
    if HEADING.match(line):
        return BLOCK_ID.sub(lambda m: " {#" + m.group(1) + "}", line)
    return BLOCK_ID.sub(lambda m: ' <a id="' + m.group(1) + '"></a>', line)
