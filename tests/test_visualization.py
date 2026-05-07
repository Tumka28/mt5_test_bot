"""Visualizer-ийн line encoding тест — wire format-ыг батална."""
from __future__ import annotations

from brain.visualization import (
    COLOR_AQUA, COLOR_GREEN, COLOR_WHITE, STYLE_DASH, Visualizer,
    rgb_to_mql5,
)


def test_rgb_to_mql5_known_colors():
    # Pure green: R=0, G=255, B=0 → (B<<16)|(G<<8)|R = 0x00FF00 = 65280
    assert rgb_to_mql5(0, 255, 0) == 0x00FF00
    # Pure red: R=255, G=0, B=0 → 0x0000FF = 255
    assert rgb_to_mql5(255, 0, 0) == 0x0000FF
    # Pure blue: R=0, G=0, B=255 → 0xFF0000 = 16711680
    assert rgb_to_mql5(0, 0, 255) == 0xFF0000


def _capture():
    sent: list[str] = []
    return sent, sent.append


def test_draw_zone_emits_correct_line():
    sent, send = _capture()
    viz = Visualizer(send_line=send, prefix="px_")
    viz.draw_zone("z1", 1000, 1.10500, 2000, 1.10650, color=COLOR_GREEN, fill=True)
    assert len(sent) == 1
    line = sent[0]
    assert line.startswith("draw_zone|")
    assert "name=px_z1" in line
    assert "t1=1000" in line and "t2=2000" in line
    assert "p1=1.10500" in line and "p2=1.10650" in line
    assert "fill=1" in line
    assert f"color={COLOR_GREEN}" in line


def test_draw_path_encodes_points():
    sent, send = _capture()
    viz = Visualizer(send_line=send, prefix="proj_")
    viz.draw_path("bull1", [(1000, 1.10), (2000, 1.105), (3000, 1.110)],
                  color=COLOR_AQUA, style=STYLE_DASH)
    line = sent[0]
    assert "name=proj_bull1" in line
    assert "points=1000,1.10000;2000,1.10500;3000,1.11000" in line
    assert f"style={STYLE_DASH}" in line


def test_draw_path_requires_at_least_2_points():
    sent, send = _capture()
    viz = Visualizer(send_line=send)
    import pytest
    with pytest.raises(ValueError):
        viz.draw_path("p", [(1, 2.0)])


def test_draw_label_escapes_text():
    sent, send = _capture()
    viz = Visualizer(send_line=send, prefix="lbl_")
    viz.draw_label("l1", 1000, 1.10500, "Hello world | foo", color=COLOR_WHITE)
    line = sent[0]
    assert "text=Hello%20world%20%7C%20foo" in line


def test_clear_emits_prefix_command():
    sent, send = _capture()
    viz = Visualizer(send_line=send, prefix="ns_")
    viz.clear_all()
    assert sent[0] == "clear|prefix=ns_"


def test_request_bars_command():
    sent, send = _capture()
    viz = Visualizer(send_line=send)
    viz.request_bars("EURUSD", "M5", 200, "abc")
    assert sent[0] == "get_bars|symbol=EURUSD|tf=M5|count=200|req_id=abc"


def test_arrow_validates_side():
    sent, send = _capture()
    viz = Visualizer(send_line=send)
    import pytest
    with pytest.raises(ValueError):
        viz.draw_arrow("a1", 1000, 1.10, side="diagonal")


def test_draw_line_default_solid():
    sent, send = _capture()
    viz = Visualizer(send_line=send, prefix="ln_")
    viz.draw_line("a", 100, 1.0, 200, 2.0)
    assert "style=0" in sent[0]
