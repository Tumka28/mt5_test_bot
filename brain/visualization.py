"""Chart drawing client — brain-аас EA-руу draw_* команд явуулна.

Шууд line-уудыг encode хийнэ; EA-ийн зүгээс HandleLine doroor handler-уудыг
дамжуулна. Бүх тэмдэгтийн нэр (`name`) brain-аар тогтмол өгнө — ижил нэр
давтагдвал EA delete + create хийнэ (in-place update).

Хэрэглэх жишээ:
    viz = Visualizer(send_line=handler.send_line, prefix="smc_eurusd_")
    viz.draw_zone("ob_bull_1", t1_ms, p1, t2_ms, p2, color=COLOR_GREEN, fill=True)
    viz.draw_path("proj_bull", points=[(t1, p1), (t2, p2), (t3, p3)],
                  color=COLOR_AQUA, style=STYLE_DASH, width=2)
    viz.draw_label("tp1_lbl", t_ms, price, "TP1 4586.67", color=COLOR_WHITE)
    viz.clear_all()
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

from bridge.tcp_server import encode_pipe

logger = logging.getLogger(__name__)


# ─── color helpers (MQL5 stores BGR as integer) ─────────────────────


def rgb_to_mql5(r: int, g: int, b: int) -> int:
    """RGB → MQL5 color int (B << 16) | (G << 8) | R."""
    r &= 0xFF; g &= 0xFF; b &= 0xFF
    return (b << 16) | (g << 8) | r


COLOR_GREEN  = rgb_to_mql5(0, 200, 0)
COLOR_RED    = rgb_to_mql5(220, 0, 0)
COLOR_BLUE   = rgb_to_mql5(0, 120, 255)
COLOR_AQUA   = rgb_to_mql5(0, 220, 220)
COLOR_YELLOW = rgb_to_mql5(255, 220, 0)
COLOR_ORANGE = rgb_to_mql5(255, 140, 0)
COLOR_GRAY   = rgb_to_mql5(160, 160, 160)
COLOR_WHITE  = rgb_to_mql5(255, 255, 255)
COLOR_BULL   = rgb_to_mql5(0, 200, 120)   # demand / bullish OB
COLOR_BEAR   = rgb_to_mql5(220, 80, 80)   # supply / bearish OB
COLOR_FVG_B  = rgb_to_mql5(80, 180, 240)  # bullish FVG
COLOR_FVG_S  = rgb_to_mql5(240, 120, 180) # bearish FVG


STYLE_SOLID = 0
STYLE_DASH  = 2
STYLE_DOT   = 1


# ─── Visualizer class ───────────────────────────────────────────────


SendLineFn = Callable[[str], None]


class Visualizer:
    """Brain-аас илгээх line-уудыг encode хийгээд `send_line` callback-руу дамжуулна.

    `prefix` нь `clear_all()`-д ашиглагдана: ижил prefix-тэй object-уудыг бүгд
    устгана (per-symbol/per-side namespace).
    """

    def __init__(self, *, send_line: SendLineFn, prefix: str = "smc_") -> None:
        self._send = send_line
        self._prefix = prefix

    def _name(self, sub: str) -> str:
        return f"{self._prefix}{sub}"

    def _safe_text(self, text: str) -> str:
        # pipe-delimited wire тул space + pipe-уудыг escape
        return text.replace("|", "%7C").replace(" ", "%20")

    # ─── primitives ───

    def draw_zone(
        self, sub_name: str, t1_ms: int, p1: float, t2_ms: int, p2: float,
        *, color: int = COLOR_BLUE, fill: bool = True, width: int = 1,
    ) -> None:
        line = encode_pipe(
            "draw_zone", name=self._name(sub_name),
            t1=t1_ms, p1=f"{p1:.5f}", t2=t2_ms, p2=f"{p2:.5f}",
            color=color, fill=("1" if fill else "0"), width=width,
        )
        self._send(line)

    def draw_line(
        self, sub_name: str, t1_ms: int, p1: float, t2_ms: int, p2: float,
        *, color: int = COLOR_YELLOW, style: int = STYLE_SOLID, width: int = 1,
    ) -> None:
        line = encode_pipe(
            "draw_line", name=self._name(sub_name),
            t1=t1_ms, p1=f"{p1:.5f}", t2=t2_ms, p2=f"{p2:.5f}",
            color=color, style=style, width=width,
        )
        self._send(line)

    def draw_label(
        self, sub_name: str, t_ms: int, price: float, text: str,
        *, color: int = COLOR_WHITE, font: str = "Arial", size: int = 9,
    ) -> None:
        line = encode_pipe(
            "draw_label", name=self._name(sub_name),
            t=t_ms, p=f"{price:.5f}", text=self._safe_text(text),
            color=color, font=font, size=size,
        )
        self._send(line)

    def draw_arrow(
        self, sub_name: str, t_ms: int, price: float, *,
        side: str = "up", color: int = COLOR_AQUA,
    ) -> None:
        if side not in ("up", "down"):
            raise ValueError(f"side must be up/down, got {side!r}")
        line = encode_pipe(
            "draw_arrow", name=self._name(sub_name),
            t=t_ms, p=f"{price:.5f}", side=side, color=color,
        )
        self._send(line)

    def draw_path(
        self, sub_name: str, points: Iterable[tuple[int, float]], *,
        color: int = COLOR_AQUA, style: int = STYLE_DASH, width: int = 2,
    ) -> None:
        pts = list(points)
        if len(pts) < 2:
            raise ValueError("need at least 2 points")
        encoded = ";".join(f"{t},{p:.5f}" for t, p in pts)
        line = encode_pipe(
            "draw_path", name=self._name(sub_name),
            points=encoded, color=color, style=style, width=width,
        )
        self._send(line)

    def clear_all(self) -> None:
        """Энэ visualizer-ийн prefix-тэй бүх объектыг chart-аас устгана."""
        self._send(encode_pipe("clear", prefix=self._prefix))

    def request_bars(self, symbol: str, timeframe: str, count: int, req_id: str) -> None:
        """EA-аас N bar-ийн history асуух. Reply нь `bars|...` line-аар ирнэ."""
        self._send(encode_pipe(
            "get_bars", symbol=symbol, tf=timeframe, count=count, req_id=req_id,
        ))
