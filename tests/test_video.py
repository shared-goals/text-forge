"""Video marker -> player HTML (the site side of `![type:video](...)`)."""

import pytest

from text_forge.video import (
    player_block,
    render_markers,
    replace_markers_with_links,
    unrendered_markers,
    youtube_embed_url,
    youtube_id,
    youtube_watch_url,
)

VIDEO = "LN6jA_brXXs"
VIDEO_EMBED = f"https://www.youtube.com/embed/{VIDEO}"


class TestYoutubeUrls:
    @pytest.mark.parametrize(
        "src",
        [
            f"https://www.youtube.com/embed/{VIDEO}",
            f"https://www.youtube.com/embed/{VIDEO}?rel=0",
            f"https://www.youtube-nocookie.com/embed/{VIDEO}",
            f"https://www.youtube.com/watch?v={VIDEO}&t=30s",
            f"https://youtu.be/{VIDEO}?si=abc123",
            f"https://www.youtube.com/shorts/{VIDEO}",
        ],
    )
    def test_embed_url_is_canonical(self, src):
        assert youtube_embed_url(src) == f"https://www.youtube.com/embed/{VIDEO}"

    @pytest.mark.parametrize(
        "src",
        [
            f"https://www.youtube.com/embed/{VIDEO}",
            f"https://www.youtube-nocookie.com/embed/{VIDEO}",
            f"https://www.youtube.com/watch?v={VIDEO}",
            f"https://youtu.be/{VIDEO}",
        ],
    )
    def test_watch_url_is_canonical(self, src):
        assert youtube_watch_url(src) == f"https://youtu.be/{VIDEO}"

    @pytest.mark.parametrize(
        "src",
        [
            "https://vimeo.com/224903454",
            "https://example.com/video",
            f"https://youtube.com.example.org/embed/{VIDEO}",
            "https://www.youtube.com/embed/short",
            "",
        ],
    )
    def test_non_youtube_links(self, src):
        assert youtube_id(src) is None
        assert youtube_embed_url(src) is None
        assert youtube_watch_url(src) is None


class TestPlayerBlock:
    def test_nocookie_is_rewritten_to_youtube(self):
        html = player_block(f"https://www.youtube-nocookie.com/embed/{VIDEO}", "Reel")
        assert f'src="https://www.youtube.com/embed/{VIDEO}"' in html
        assert "nocookie" not in html

    def test_player_attributes_carry_values(self):
        html = player_block(f"https://youtu.be/{VIDEO}", "Reel")
        # bare boolean attributes are valid HTML5 but invalid XHTML — never emit them
        assert 'allowfullscreen="allowfullscreen"' in html
        for attr in ("allow=", "referrerpolicy=", "loading=", "style=", "title="):
            assert attr in html
        assert "aspect-ratio:16/9" in html
        assert 'class="tf-video"' in html

    def test_title_is_escaped(self):
        html = player_block(f"https://youtu.be/{VIDEO}", 'A & B <C> "D"')
        assert "&amp;" in html and "&lt;C&gt;" in html
        assert "<C>" not in html

    def test_title_fallback(self):
        assert 'title="Video"' in player_block(f"https://youtu.be/{VIDEO}")

    def test_local_video_uses_video_tag(self):
        html = player_block("assets/video/clip.mp4", "Clip")
        assert "<video" in html and "<iframe" not in html
        assert 'src="assets/video/clip.mp4"' in html
        assert 'type="video/mp4"' in html

    def test_other_host_stays_an_iframe(self):
        html = player_block("https://player.vimeo.com/video/224903454", "Vimeo")
        assert 'src="https://player.vimeo.com/video/224903454"' in html
        assert "<iframe" in html


class TestRenderMarkers:
    def test_marker_becomes_player(self):
        src = f'![type:video](https://www.youtube.com/embed/{VIDEO} "Webzavod 1997")'
        out = render_markers(src)
        assert "<iframe" in out and 'title="Webzavod 1997"' in out
        assert "type:video" not in out

    def test_surrounding_text_is_kept(self):
        src = f"Перед.\n\n![type:video](https://youtu.be/{VIDEO})\n\nПосле.\n"
        out = render_markers(src)
        assert out.startswith("Перед.\n\n")
        assert out.endswith("\n\nПосле.\n")
        assert "<iframe" in out

    def test_text_without_marker_is_byte_identical(self):
        text = "# Заголовок\n\nТекст с ![картинкой](img/a.png) и всё.\n"
        assert render_markers(text) == text

    def test_idempotent(self):
        src = f'![type:video](https://youtu.be/{VIDEO} "Reel")'
        once = render_markers(src)
        assert render_markers(once) == once

    def test_inline_marker_is_left_alone(self):
        # a marker inside a sentence cannot become a block without eating the prose
        src = f"Смотрите ![type:video](https://youtu.be/{VIDEO}) тут."
        assert render_markers(src) == src

    @pytest.mark.parametrize(
        "title_markup",
        [
            '"What is SoDA?"',        # straight pair
            '"What is SoDA?”',        # straight open, typographic close (the bug)
            "“What is SoDA?”",        # typographic pair, as Obsidian writes them
            "«What is SoDA?»",        # guillemets
            '"What is SoDA?"  ',      # trailing spaces
        ],
    )
    def test_title_quotes_of_any_shape(self, title_markup):
        src = f"![type:video](https://www.youtube.com/embed/{VIDEO} {title_markup})"
        out = render_markers(src)
        assert 'title="What is SoDA?"' in out, out
        assert "type:video" not in out

    def test_title_containing_a_quote_mark_is_kept(self):
        src = f'![type:video](https://youtu.be/{VIDEO} "He said «no»")'
        assert 'title="He said «no»"' in render_markers(src)


class TestUnrenderedMarkers:
    def test_no_leftovers_after_rendering(self):
        src = f'![type:video](https://youtu.be/{VIDEO} "Reel")'
        assert unrendered_markers(render_markers(src)) == []

    def test_broken_marker_is_reported_with_its_line(self):
        src = f"Перед.\n\n![type:video](https://youtu.be/{VIDEO}\n\nПосле."
        assert render_markers(src) == src  # nothing to render
        found = unrendered_markers(src)
        assert found and found[0][0] == 3
        assert "type:video" in found[0][1]


class TestMarkersToLinks:
    """The book side: a marker must become a link before pandoc sees it."""

    def test_marker_becomes_a_link(self):
        src = f'![type:video](https://www.youtube.com/embed/{VIDEO} "Webzavod 1997")'
        assert replace_markers_with_links(src) == f"[▶ Webzavod 1997](https://youtu.be/{VIDEO})"

    @pytest.mark.parametrize(
        "title_markup",
        ['"What is SoDA?”', "“What is SoDA?”", "«What is SoDA?»"],
    )
    def test_typographic_title_still_becomes_a_link(self, title_markup):
        src = f"![type:video](https://www.youtube.com/embed/{VIDEO} {title_markup})"
        out = replace_markers_with_links(src)
        assert "![type:video]" not in out  # pandoc would keep it as literal text
        assert f"[▶ What is SoDA?](https://youtu.be/{VIDEO})" in out

    def test_title_fallback_and_local_file(self):
        assert replace_markers_with_links(f"![type:video]({VIDEO_EMBED})") == (
            f"[▶ Watch on YouTube](https://youtu.be/{VIDEO})"
        )
        assert replace_markers_with_links("![type:video](assets/clip.mp4)") == (
            "[▶ Watch on YouTube](assets/clip.mp4)"
        )

    def test_text_without_markers_is_untouched(self):
        text = "# Глава\n\nОбычный [текст](https://example.com).\n"
        assert replace_markers_with_links(text) == text
