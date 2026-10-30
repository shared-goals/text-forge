"""Tests for block-id anchors (text_forge.anchor_ids) and their plugin wiring.

Obsidian writes a block id as a TRAILING `^id` on the last line of a block;
MkDocs/python-markdown drops it, so a site page has no `#quote_1` to land on.
The conversion turns the trailing id into an explicit `<a id="..."></a>` and
keeps the markdown on disk untouched (files stay Obsidian-clean).
"""

from text_forge.anchor_ids import convert_block_ids


class TestConvertBlockIds:
    def test_trailing_block_id_becomes_anchor(self):
        out = convert_block_ids("> Последний абзац цитаты ^quote_1\n")
        assert out == '> Последний абзац цитаты <a id="quote_1"></a>\n'

    def test_blockquote_last_line_converts(self):
        md = "> Первая строка\n>\n> Конец цитаты ^quote_2\n"
        out = convert_block_ids(md)
        assert "> Конец цитаты <a id=\"quote_2\"></a>" in out
        assert "> Первая строка" in out
        assert "^" not in out

    def test_midline_caret_superscript_survives(self):
        """`^text^` (pymdownx superscript) is not a block id: keep it verbatim."""
        md = "Слово ^вот так^ остаётся.\n"
        assert convert_block_ids(md) == md

    def test_only_the_trailing_id_converts(self):
        md = "> Текст ^quote_1 ещё внутри ^quote_2\n"
        out = convert_block_ids(md)
        assert out == '> Текст ^quote_1 ещё внутри <a id="quote_2"></a>\n'

    def test_multiple_lines_each_convert(self):
        md = "a ^q1\nb\nc ^q2\n"
        out = convert_block_ids(md)
        assert out.count("<a id=") == 2
        assert "b" in out

    def test_id_chars_letters_digits_underscore_dash(self):
        out = convert_block_ids("x ^quote_12-ab\n")
        assert out == 'x <a id="quote_12-ab"></a>\n'

    def test_caret_at_line_start_is_not_an_id(self):
        """A caret with nothing before it on the line is not a block id."""
        md = "^quote_1\n"
        assert convert_block_ids(md) == md

    def test_trailing_whitespace_after_id_still_converts(self):
        out = convert_block_ids("x ^quote_1   \n")
        assert out == 'x <a id="quote_1"></a>\n'

    def test_frontmatter_fence_is_untouched(self):
        md = "---\ntitle: \"T\"\n---\n\n> Цитата ^quote_1\n"
        out = convert_block_ids(md)
        assert out.startswith("---\ntitle: \"T\"\n---")
        assert "> Цитата <a id=\"quote_1\"></a>" in out

    def test_id_inside_code_fence_is_untouched(self):
        md = "```\ntext ^quote_1\n```\n"
        assert convert_block_ids(md) == md

    def test_line_without_id_unchanged(self):
        md = "Обычная строка текста.\n"
        assert convert_block_ids(md) == md

    def test_no_trailing_newline_input(self):
        assert convert_block_ids("> Цитата ^quote_3") == "> Цитата <a id=\"quote_3\"></a>"

    def test_byte_stable_on_repeated_call(self):
        """Converted output has no ids left, so a second call is a no-op."""
        md = "> Раз ^quote_1\n\n> Два ^quote_2\n"
        once = convert_block_ids(md)
        assert convert_block_ids(once) == once


class TestPluginWiring:
    """The hook converts ONLY pages under books/ — chapters keep their bytes."""

    class FakePage:
        def __init__(self, file_path):
            self.file = type("F", (), {"src_uri": file_path, "src_path": file_path})()

    def call(self, plugin, markdown, path):
        return plugin.on_page_markdown(markdown, self.FakePage(path),
                                      config=None, files=None)

    def make_plugin(self):
        from text_forge.plugin import TextForgePlugin

        plugin = TextForgePlugin()
        # config_scheme defaults, as MkDocs would have resolved them
        plugin.config = {name: opt.default for name, opt in
                        TextForgePlugin.config_scheme}
        plugin.config["nobr_emoticons_enabled"] = False
        return plugin

    def test_books_page_gets_anchors(self):
        plugin = self.make_plugin()
        out = self.call(plugin, "> Цитата ^quote_1\n", "books/abe-chetvertyy.md")
        assert '<a id="quote_1"></a>' in out

    def test_chapter_page_is_untouched(self):
        plugin = self.make_plugin()
        md = "> Цитата ^quote_1\n"
        assert self.call(plugin, md, "p2-200-text.md") == md

    def test_nested_books_page_gets_anchors(self):
        plugin = self.make_plugin()
        out = self.call(plugin, "x ^q1\n", "books/sub/deep.md")
        assert '<a id="q1"></a>' in out
