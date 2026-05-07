"""Smart Money Concepts (SMC) analysis — pragmatic rule-based detection.

Production-ийн зорилго: ML биш, харин backtestable, deterministic detection rule-уудыг
тавих, projection generator-т өгөх "structure state" бий болгох. Бүх рулиг дотор
тогтсон параметрүүд (lookback гэх мэт)-тэй; hyper-tune үед config-аар оруулна.

Нэр томъёо:
  - Swing high / swing low: Williams fractal (lookback bars on each side)
  - BOS (Break of Structure): trend-ийн чиглэлд latest swing-ыг close break
  - CHOCH (Change of Character): trend-ийн эсрэг чиглэлд эхний BOS
  - FVG (Fair Value Gap): 3-bar imbalance (bar[i-1].high < bar[i+1].low — bull)
  - Order Block (OB): BOS-ыг үүсгэсэн impulse-ийн өмнөх opposite-color candle
  - Liquidity zone: ойролцоо equal high/low кластер (sweep target)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from brain.bar import Bar


Side = Literal["bull", "bear"]


# ─── data classes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Swing:
    idx: int          # bar index
    ts_ms: int
    price: float
    side: Side        # "bull" = swing high; "bear" = swing low


@dataclass(frozen=True)
class StructureEvent:
    kind: Literal["BOS", "CHOCH"]
    direction: Side       # "bull" = price closed above swing high; "bear" = below low
    ts_ms: int
    broken_swing: Swing
    break_idx: int


@dataclass(frozen=True)
class FVG:
    direction: Side       # "bull" = gap up; "bear" = gap down
    ts_ms: int            # candle that creates the gap (middle bar)
    top: float
    bottom: float
    filled: bool = False


@dataclass(frozen=True)
class OrderBlock:
    direction: Side       # "bull" = bullish OB (acts as support); "bear" = bearish OB (resistance)
    ts_ms: int
    top: float
    bottom: float
    origin_idx: int


@dataclass(frozen=True)
class LiquidityZone:
    direction: Side       # "bull" = liquidity ABOVE (buy stops); "bear" = liquidity BELOW (sell stops)
    price: float
    count: int            # how many highs/lows clustered
    last_ts_ms: int


@dataclass
class StructureState:
    """`detect_all`-ийн output. Projection-д өгнө."""
    bars: list[Bar] = field(default_factory=list)
    swing_highs: list[Swing] = field(default_factory=list)
    swing_lows: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    liquidity: list[LiquidityZone] = field(default_factory=list)
    trend: Side | None = None  # last BOS direction

    @property
    def last_event(self) -> StructureEvent | None:
        return self.events[-1] if self.events else None


# ─── detectors ──────────────────────────────────────────────────────


def find_swings(bars: list[Bar], *, lookback: int = 2) -> tuple[list[Swing], list[Swing]]:
    """Williams fractal: bar[i] is swing high if its high > all `lookback` neighbors on each side.

    Returns (swing_highs, swing_lows) in chronological order.
    """
    highs: list[Swing] = []
    lows: list[Swing] = []
    n = len(bars)
    if n < 2 * lookback + 1:
        return highs, lows
    for i in range(lookback, n - lookback):
        h = bars[i].high
        l = bars[i].low
        left_h = max(b.high for b in bars[i - lookback:i])
        right_h = max(b.high for b in bars[i + 1:i + lookback + 1])
        left_l = min(b.low for b in bars[i - lookback:i])
        right_l = min(b.low for b in bars[i + 1:i + lookback + 1])
        if h >= left_h and h > right_h:
            highs.append(Swing(idx=i, ts_ms=bars[i].ts_ms, price=h, side="bull"))
        if l <= left_l and l < right_l:
            lows.append(Swing(idx=i, ts_ms=bars[i].ts_ms, price=l, side="bear"))
    return highs, lows


def find_structure_events(
    bars: list[Bar], swing_highs: list[Swing], swing_lows: list[Swing],
) -> list[StructureEvent]:
    """Bull BOS = close > prior swing high; bear BOS = close < prior swing low.

    CHOCH = first BOS in opposite direction after a sustained run.
    """
    if not bars:
        return []
    events: list[StructureEvent] = []
    last_dir: Side | None = None

    # Pointers walking the swings as bars advance
    h_ptr = 0
    l_ptr = 0

    for i, bar in enumerate(bars):
        # Advance pointers so swings are *prior* to current bar
        while h_ptr < len(swing_highs) and swing_highs[h_ptr].idx >= i:
            h_ptr += 1
            break  # iterate next outer loop
        while l_ptr < len(swing_lows) and swing_lows[l_ptr].idx >= i:
            l_ptr += 1
            break
        # Find the most recent prior swing high / low
        recent_high = next(
            (s for s in reversed(swing_highs[:h_ptr]) if s.idx < i), None,
        )
        recent_low = next(
            (s for s in reversed(swing_lows[:l_ptr]) if s.idx < i), None,
        )
        # Bull BOS
        if recent_high is not None and bar.close > recent_high.price:
            kind: Literal["BOS", "CHOCH"] = "CHOCH" if last_dir == "bear" else "BOS"
            events.append(StructureEvent(
                kind=kind, direction="bull", ts_ms=bar.ts_ms,
                broken_swing=recent_high, break_idx=i,
            ))
            last_dir = "bull"
            # Once consumed, don't re-fire on the same swing
            swing_highs = [s for s in swing_highs if s.idx != recent_high.idx]
            h_ptr = sum(1 for s in swing_highs if s.idx < i)
            continue
        # Bear BOS
        if recent_low is not None and bar.close < recent_low.price:
            kind = "CHOCH" if last_dir == "bull" else "BOS"
            events.append(StructureEvent(
                kind=kind, direction="bear", ts_ms=bar.ts_ms,
                broken_swing=recent_low, break_idx=i,
            ))
            last_dir = "bear"
            swing_lows = [s for s in swing_lows if s.idx != recent_low.idx]
            l_ptr = sum(1 for s in swing_lows if s.idx < i)
    return events


def find_fvgs(bars: list[Bar], *, max_age: int = 100, mark_filled: bool = True) -> list[FVG]:
    """3-bar imbalance pattern. Хэрэв `mark_filled=True` бол хожимд хаагдсан FVG-уудыг
    `filled=True`-аар тэмдэглэнэ."""
    n = len(bars)
    out: list[FVG] = []
    for i in range(1, n - 1):
        prev_b = bars[i - 1]
        next_b = bars[i + 1]
        # Bullish FVG: prev.high < next.low (gap up between them, mid bar is impulse)
        if prev_b.high < next_b.low:
            top = next_b.low
            bot = prev_b.high
            filled = False
            if mark_filled:
                for later in bars[i + 2:]:
                    if later.low <= bot:
                        filled = True
                        break
            if i >= n - 1 - max_age:
                out.append(FVG(direction="bull", ts_ms=bars[i].ts_ms,
                               top=top, bottom=bot, filled=filled))
        elif prev_b.low > next_b.high:
            top = prev_b.low
            bot = next_b.high
            filled = False
            if mark_filled:
                for later in bars[i + 2:]:
                    if later.high >= top:
                        filled = True
                        break
            if i >= n - 1 - max_age:
                out.append(FVG(direction="bear", ts_ms=bars[i].ts_ms,
                               top=top, bottom=bot, filled=filled))
    return out


def find_order_blocks(
    bars: list[Bar], events: list[StructureEvent], *, max_lookback: int = 20,
) -> list[OrderBlock]:
    """For each BOS, walk back to find the last opposite-color candle within `max_lookback`."""
    obs: list[OrderBlock] = []
    for ev in events:
        # Bull BOS → look for last bearish candle before the impulse
        # Bear BOS → look for last bullish candle
        idx = ev.break_idx
        start = max(0, idx - max_lookback)
        if ev.direction == "bull":
            for i in range(idx - 1, start - 1, -1):
                if bars[i].is_bear:
                    obs.append(OrderBlock(
                        direction="bull", ts_ms=bars[i].ts_ms,
                        top=bars[i].high, bottom=bars[i].low, origin_idx=i,
                    ))
                    break
        else:
            for i in range(idx - 1, start - 1, -1):
                if bars[i].is_bull:
                    obs.append(OrderBlock(
                        direction="bear", ts_ms=bars[i].ts_ms,
                        top=bars[i].high, bottom=bars[i].low, origin_idx=i,
                    ))
                    break
    return obs


def find_liquidity(
    bars: list[Bar], swing_highs: list[Swing], swing_lows: list[Swing],
    *, tolerance_atr: float = 0.25, atr_window: int = 14,
) -> list[LiquidityZone]:
    """Equal-highs / equal-lows clusters within `tolerance_atr * ATR`."""
    if not bars:
        return []
    atr = _atr(bars, atr_window)
    if atr <= 0:
        return []
    tol = tolerance_atr * atr
    out: list[LiquidityZone] = []

    def _cluster(swings: list[Swing], side: Side) -> None:
        used: set[int] = set()
        for i, s in enumerate(swings):
            if i in used:
                continue
            cluster = [s]
            for j in range(i + 1, len(swings)):
                if abs(swings[j].price - s.price) <= tol:
                    cluster.append(swings[j])
                    used.add(j)
            if len(cluster) >= 2:
                avg = sum(c.price for c in cluster) / len(cluster)
                last_ts = max(c.ts_ms for c in cluster)
                out.append(LiquidityZone(
                    direction=side, price=avg, count=len(cluster), last_ts_ms=last_ts,
                ))

    _cluster(swing_highs, "bull")
    _cluster(swing_lows, "bear")
    return out


def _atr(bars: list[Bar], n: int) -> float:
    if len(bars) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(bars)):
        c = bars[i]; p = bars[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        trs.append(tr)
    if len(trs) < n:
        n = len(trs)
    return sum(trs[-n:]) / n if n > 0 else 0.0


# ─── top-level analysis ─────────────────────────────────────────────


def detect_all(bars: list[Bar], *, swing_lookback: int = 2) -> StructureState:
    """Run all detectors and return aggregate StructureState."""
    highs, lows = find_swings(bars, lookback=swing_lookback)
    events = find_structure_events(bars, list(highs), list(lows))
    fvgs = find_fvgs(bars)
    obs = find_order_blocks(bars, events)
    liq = find_liquidity(bars, highs, lows)
    trend: Side | None = events[-1].direction if events else None
    return StructureState(
        bars=bars, swing_highs=highs, swing_lows=lows, events=events,
        fvgs=fvgs, order_blocks=obs, liquidity=liq, trend=trend,
    )
