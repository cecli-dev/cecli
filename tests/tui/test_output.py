from rich.color import Color

from cecli.tui.widgets.thin_scrollbar import ThinScrollBarRenderer


def test_horizontal_scrollbar_uses_half_block_glyphs():
    track_color = Color.parse("#555555")
    thumb_color = Color.parse("#00ff00")
    rendered = ThinScrollBarRenderer.render_bar(
        size=8,
        virtual_size=16,
        window_size=8,
        position=0,
        thickness=1,
        vertical=False,
        back_color=track_color,
        bar_color=thumb_color,
    )

    assert [segment.text for segment in rendered.segments] == ["▄"] * 8
    assert rendered.segments[0].style.color == thumb_color
    assert rendered.segments[0].style.meta["@mouse.down"] == "grab"
    assert rendered.segments[4].style.color == track_color
    assert rendered.segments[4].style.meta["@mouse.down"] == "scroll_down"
