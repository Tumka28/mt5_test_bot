"""SMC advisor service — ties bar history → SMC analysis → projection → chart drawing.

Хариуцлагыг шахаж тус бүрд хариу:
  1. EA-аас bars request → push results into BarHistory
  2. Тогтмол хугацаанд (or шинэ бар оромогц) `detect_all` + `project` дуудна
  3. Visualizer-ээр chart дээр zone/path/label-уудыг update хийнэ
  4. Telegram-style signal text-ийг output (caller хүсвэл нийтэлнэ)

Trading биш — зөвхөн analysis + visualization. Ариljaa-нд ашиглах бол гаралт нь
TradingService-ийн strategy-аар адил OrderIntent болж шилжих ёстой.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Callable

from brain.bar import Bar, BarHistory, parse_bars_payload
from brain.projection import Projection, project
from brain.smc import StructureState, detect_all
from brain.visualization import (
    COLOR_AQUA, COLOR_BEAR, COLOR_BULL, COLOR_FVG_B, COLOR_FVG_S,
    COLOR_GRAY, COLOR_GREEN, COLOR_ORANGE, COLOR_RED, COLOR_WHITE,
    STYLE_DASH, STYLE_DOT, Visualizer,
)
from bridge.tcp_server import _BridgeHandler

logger = logging.getLogger(__name__)


SignalCallback = Callable[[str, "AdvisorOutput"], None]


class AdvisorOutput:
    """Single analyse cycle result — caller (Telegram, DB, etc.)-д тогтмол format-аар."""

    def __init__(
        self, *, symbol: str, timeframe: str, last_close: float,
        state: StructureState, projections: list[Projection],
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.last_close = last_close
        self.state = state
        self.projections = projections

    @property
    def best(self) -> Projection | None:
        if not self.projections:
            return None
        return max(self.projections, key=lambda p: p.probability)

    def telegram_text(self) -> str:
        """ForexFactory-style текст signal."""
        p = self.best
        if p is None:
            return f"{self.symbol} {self.timeframe}\nDirection: NONE\n(insufficient bars)"
        arrow = "UP" if p.direction == "bull" else "DOWN"
        return (
            f"{self.symbol} {self.timeframe}\n"
            f"Direction: {arrow}\n"
            f"Probability: {p.probability * 100:.0f}%\n"
            f"Near target: TP1 {p.tp1:.5f}\n"
            f"Next target: TP2 {p.tp2:.5f}\n"
            f"Structure target: {p.structure_target:.5f}\n"
            f"Big target: {p.big_target:.5f}\n"
            f"Invalidation: {p.invalidation:.5f}"
        )


class SmcAdvisor:
    """One advisor per (symbol, timeframe). Internal thread тогтмол period-ээр
    re-analyses + redraws; caller `start()` / `stop()`."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str = "M5",
        bars_window: int = 300,
        analysis_period_s: float = 5.0,
        signal_callback: SignalCallback | None = None,
        prefix_template: str = "smc_{symbol}_{tf}_",
        max_zones_drawn: int = 8,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._bars_window = bars_window
        self._period = analysis_period_s
        self._cb = signal_callback
        self._prefix = prefix_template.format(symbol=symbol.lower(), tf=timeframe.lower())
        self._max_zones = max_zones_drawn

        self._history = BarHistory(maxlen=bars_window * 2)
        self._handler: _BridgeHandler | None = None
        self._viz: Visualizer | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_analysis_ts: int | None = None
        self._req_ids: set[str] = set()

    # ─── lifecycle hooks (called by EA TCP server) ──────────────────

    def on_connect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            self._handler = handler
            self._viz = Visualizer(send_line=handler.send_line, prefix=self._prefix)
        # Reset state and request initial history
        self._history.reset(self.symbol, self.timeframe)
        self._request_bars()

    def on_disconnect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            if self._handler is handler:
                self._handler = None
                self._viz = None

    def on_message(self, msg: dict, handler: _BridgeHandler) -> None:
        t = msg.get("type")
        if t == "bars":
            self._handle_bars(msg)

    def _handle_bars(self, msg: dict) -> None:
        symbol = msg.get("symbol")
        tf = msg.get("tf")
        if symbol != self.symbol or tf != self.timeframe:
            return
        bars = parse_bars_payload(msg.get("data", ""))
        if not bars:
            return
        self._history.replace_all(self.symbol, self.timeframe, bars)
        # Trigger immediate analysis once we have bars
        self._analyse_and_draw()

    def _request_bars(self) -> None:
        with self._lock:
            viz = self._viz
        if viz is None:
            return
        rid = uuid.uuid4().hex[:12]
        self._req_ids.add(rid)
        viz.request_bars(self.symbol, self.timeframe, self._bars_window, rid)

    # ─── thread loop ────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        t = threading.Thread(target=self._loop, daemon=True, name=f"smc-{self.symbol}")
        self._thread = t
        t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                connected = self._handler is not None
            if connected:
                self._request_bars()
            self._stop.wait(self._period)

    # ─── analysis ───────────────────────────────────────────────────

    def _analyse_and_draw(self) -> AdvisorOutput | None:
        bars = self._history.get(self.symbol, self.timeframe)
        if len(bars) < 50:
            return None
        state = detect_all(bars)
        projections = project(state)
        out = AdvisorOutput(
            symbol=self.symbol, timeframe=self.timeframe,
            last_close=bars[-1].close, state=state, projections=projections,
        )
        self._draw(out)
        if self._cb is not None:
            try:
                self._cb(out.telegram_text(), out)
            except Exception as exc:
                logger.warning("signal callback raised: %s", exc)
        self._last_analysis_ts = bars[-1].ts_ms
        return out

    # ─── drawing ────────────────────────────────────────────────────

    def _draw(self, out: AdvisorOutput) -> None:
        with self._lock:
            viz = self._viz
        if viz is None:
            return
        viz.clear_all()  # full redraw — simplest, low object count

        bars = out.state.bars
        if not bars:
            return
        last_t = bars[-1].ts_ms
        # bar interval (ms) for zone right-edge extension
        if len(bars) >= 2:
            step_ms = max(1, bars[-1].ts_ms - bars[-2].ts_ms)
        else:
            step_ms = 60_000

        # 1. FVGs (last few unfilled)
        unfilled_fvgs = [f for f in out.state.fvgs if not f.filled][-self._max_zones:]
        for i, fvg in enumerate(unfilled_fvgs):
            color = COLOR_FVG_B if fvg.direction == "bull" else COLOR_FVG_S
            viz.draw_zone(
                f"fvg_{i}", fvg.ts_ms, fvg.top, last_t + 5 * step_ms, fvg.bottom,
                color=color, fill=True,
            )

        # 2. Order Blocks
        for i, ob in enumerate(out.state.order_blocks[-self._max_zones:]):
            color = COLOR_BULL if ob.direction == "bull" else COLOR_BEAR
            viz.draw_zone(
                f"ob_{i}", ob.ts_ms, ob.top, last_t + 5 * step_ms, ob.bottom,
                color=color, fill=True,
            )

        # 3. BOS / CHOCH event lines
        for i, ev in enumerate(out.state.events[-5:]):
            color = COLOR_GREEN if ev.direction == "bull" else COLOR_RED
            viz.draw_line(
                f"ev_{i}", ev.broken_swing.ts_ms, ev.broken_swing.price,
                bars[ev.break_idx].ts_ms, ev.broken_swing.price,
                color=color, style=STYLE_DOT, width=1,
            )
            viz.draw_label(
                f"evlbl_{i}", bars[ev.break_idx].ts_ms, ev.broken_swing.price,
                f"{ev.kind} {ev.direction.upper()}", color=color, size=8,
            )

        # 4. Projections — both bull & bear
        for proj in out.projections:
            color = COLOR_GREEN if proj.direction == "bull" else COLOR_RED
            sub = f"proj_{proj.direction}"
            viz.draw_path(sub, proj.waypoints, color=color, style=STYLE_DASH, width=2)
            # TP1, TP2, structure, big, invalidation lines
            t_left = bars[max(0, len(bars) - 30)].ts_ms
            t_right = proj.waypoints[-1][0]
            for tag, level, lbl_color in (
                ("tp1", proj.tp1, COLOR_AQUA),
                ("tp2", proj.tp2, COLOR_BLUE_or_orange(proj.direction)),
                ("struct", proj.structure_target, COLOR_WHITE),
                ("big", proj.big_target, COLOR_GRAY),
                ("inval", proj.invalidation, COLOR_RED if proj.direction == "bull" else COLOR_GREEN),
            ):
                ln = f"{sub}_{tag}_ln"
                lb = f"{sub}_{tag}_lbl"
                viz.draw_line(ln, t_left, level, t_right, level,
                              color=lbl_color, style=STYLE_DOT, width=1)
                viz.draw_label(lb, t_right, level,
                               f"{proj.direction.upper()} {tag} {level:.5f}",
                               color=lbl_color, size=8)

        # 5. Best signal label near last bar
        best = out.best
        if best is not None:
            arrow = "UP" if best.direction == "bull" else "DOWN"
            viz.draw_label(
                "signal", last_t, bars[-1].close,
                f"{arrow} {best.probability * 100:.0f}%",
                color=COLOR_GREEN if best.direction == "bull" else COLOR_RED,
                size=11,
            )


def COLOR_BLUE_or_orange(direction: str) -> int:  # noqa: N802 — match other COLOR_*
    """Pick TP2 color based on direction: blueish for bull, orange for bear."""
    if direction == "bull":
        from brain.visualization import COLOR_BLUE
        return COLOR_BLUE
    return COLOR_ORANGE
