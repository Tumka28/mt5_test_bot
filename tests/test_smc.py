"""SMC analysis тестүүд — swings, BOS, CHOCH, FVG, OB, liquidity."""
from __future__ import annotations

from brain.bar import Bar
from brain.smc import (
    detect_all, find_fvgs, find_order_blocks, find_structure_events, find_swings,
)


def _bars(prices: list[tuple[float, float, float, float]], step: int = 60_000,
          start_ms: int = 0) -> list[Bar]:
    """Helper: list of (open, high, low, close) → list of Bar."""
    out: list[Bar] = []
    for i, (o, h, l, c) in enumerate(prices):
        out.append(Bar(ts_ms=start_ms + i * step, open=o, high=h, low=l, close=c))
    return out


# ─── swings ─────────────────────────────────────────────────────────


def test_simple_swing_high_detected():
    # Pyramid pattern: low, low, HIGH, low, low → swing high in middle
    bars = _bars([
        (1.10, 1.10, 1.099, 1.099),
        (1.10, 1.105, 1.099, 1.104),
        (1.104, 1.120, 1.103, 1.118),  # high here
        (1.118, 1.118, 1.110, 1.111),
        (1.111, 1.111, 1.105, 1.106),
    ])
    highs, lows = find_swings(bars, lookback=2)
    assert len(highs) == 1
    assert highs[0].idx == 2
    assert highs[0].price == 1.120


def test_swing_low_detected():
    bars = _bars([
        (1.10, 1.10, 1.099, 1.099),
        (1.099, 1.099, 1.095, 1.096),
        (1.096, 1.096, 1.080, 1.082),  # low here
        (1.082, 1.090, 1.082, 1.089),
        (1.089, 1.092, 1.088, 1.091),
    ])
    highs, lows = find_swings(bars, lookback=2)
    assert len(lows) == 1
    assert lows[0].idx == 2
    assert lows[0].price == 1.080


def test_no_swings_in_short_input():
    bars = _bars([(1, 1, 1, 1)] * 3)
    h, l = find_swings(bars, lookback=2)
    assert h == [] and l == []


# ─── BOS / CHOCH ────────────────────────────────────────────────────


def test_bullish_bos_after_swing_high_break():
    # Make a swing high, then a bar that closes above it
    bars = _bars([
        (1.10, 1.10, 1.099, 1.099),
        (1.099, 1.105, 1.099, 1.104),
        (1.104, 1.120, 1.103, 1.118),  # swing high (idx 2)
        (1.118, 1.118, 1.110, 1.111),
        (1.111, 1.111, 1.105, 1.106),
        (1.106, 1.121, 1.106, 1.121),  # closes above 1.120 → BOS bull
    ])
    state = detect_all(bars, swing_lookback=2)
    assert state.events, f"expected BOS event, got {state.events}"
    ev = state.events[0]
    assert ev.kind in ("BOS", "CHOCH")
    assert ev.direction == "bull"
    assert ev.broken_swing.price == 1.120


def test_choch_after_opposite_bos():
    # Bull move, BOS up, then big bear close breaks last swing low → CHOCH bear
    bars = _bars([
        # swing low
        (1.10, 1.10, 1.099, 1.099),
        (1.099, 1.099, 1.095, 1.096),
        (1.096, 1.096, 1.080, 1.082),  # low (idx 2)
        (1.082, 1.090, 1.082, 1.089),
        (1.089, 1.092, 1.088, 1.091),
        # swing high after low
        (1.091, 1.110, 1.090, 1.105),
        (1.105, 1.115, 1.103, 1.110),
        (1.110, 1.130, 1.108, 1.125),  # swing high (idx 7)
        (1.125, 1.125, 1.115, 1.118),
        (1.118, 1.118, 1.112, 1.114),
        # bull BOS — close above 1.130
        (1.114, 1.135, 1.113, 1.135),  # idx 10 → bull BOS
        # crash through swing low — bear CHOCH
        (1.135, 1.135, 1.075, 1.078),  # idx 11 → close < 1.080 = bear
    ])
    state = detect_all(bars, swing_lookback=2)
    kinds = [(e.kind, e.direction) for e in state.events]
    assert ("BOS", "bull") in kinds or ("CHOCH", "bull") in kinds
    bear_evs = [e for e in state.events if e.direction == "bear"]
    assert any(e.kind == "CHOCH" for e in bear_evs), \
        f"expected bearish CHOCH, got {kinds}"


# ─── FVG ────────────────────────────────────────────────────────────


def test_bullish_fvg_detected():
    # 3-bar pattern: bar0.high < bar2.low → bullish FVG
    bars = _bars([
        (1.100, 1.105, 1.100, 1.103),  # bar 0: high = 1.105
        (1.103, 1.115, 1.103, 1.114),  # impulse
        (1.114, 1.116, 1.108, 1.115),  # bar 2: low = 1.108  → gap! 1.105 < 1.108
        (1.115, 1.115, 1.114, 1.115),
    ])
    fvgs = find_fvgs(bars)
    bull = [f for f in fvgs if f.direction == "bull"]
    assert len(bull) == 1
    assert bull[0].bottom == 1.105
    assert bull[0].top == 1.108


def test_bearish_fvg_detected():
    bars = _bars([
        (1.110, 1.115, 1.108, 1.108),  # bar 0: low = 1.108
        (1.108, 1.108, 1.098, 1.099),  # impulse
        (1.099, 1.103, 1.097, 1.100),  # bar 2: high = 1.103 → bear FVG (1.108 > 1.103)
        (1.100, 1.100, 1.099, 1.099),
    ])
    fvgs = find_fvgs(bars)
    bear = [f for f in fvgs if f.direction == "bear"]
    assert len(bear) == 1


def test_fvg_filled_marker():
    bars = _bars([
        (1.100, 1.105, 1.100, 1.103),
        (1.103, 1.115, 1.103, 1.114),
        (1.114, 1.116, 1.108, 1.115),  # bullish FVG: 1.105..1.108
        (1.115, 1.115, 1.105, 1.107),  # later bar dips into bottom → fills
    ])
    fvgs = find_fvgs(bars, mark_filled=True)
    assert any(f.direction == "bull" and f.filled for f in fvgs)


# ─── Order Blocks ───────────────────────────────────────────────────


def test_bullish_ob_is_last_bear_candle_before_bos():
    bars = _bars([
        (1.100, 1.100, 1.099, 1.099),
        (1.099, 1.105, 1.099, 1.104),
        (1.104, 1.120, 1.103, 1.118),  # swing high (idx 2)
        (1.118, 1.118, 1.110, 1.111),  # idx 3 — bearish candle (last bear before BOS)
        (1.111, 1.115, 1.110, 1.114),  # bull
        (1.114, 1.121, 1.113, 1.121),  # idx 5 → BOS bull (close above 1.120)
    ])
    state = detect_all(bars)
    bull_obs = [o for o in state.order_blocks if o.direction == "bull"]
    assert bull_obs
    # OB should be the most recent bearish candle prior to BOS — idx 3
    assert bull_obs[0].origin_idx == 3


# ─── liquidity ──────────────────────────────────────────────────────


def test_liquidity_clusters_equal_highs():
    # Three swing highs at very close levels
    bars = _bars([
        (1.10, 1.10, 1.099, 1.099),
        (1.099, 1.105, 1.099, 1.104),
        (1.104, 1.120, 1.103, 1.118),  # high A = 1.120
        (1.118, 1.118, 1.110, 1.111),
        (1.111, 1.115, 1.110, 1.114),
        (1.114, 1.1205, 1.113, 1.115),  # high B ≈ 1.1205
        (1.115, 1.115, 1.105, 1.106),
        (1.106, 1.110, 1.104, 1.105),
        (1.105, 1.121, 1.104, 1.108),  # high C = 1.121
        (1.108, 1.108, 1.100, 1.102),
        (1.102, 1.102, 1.095, 1.097),
    ])
    state = detect_all(bars)
    bull_liq = [z for z in state.liquidity if z.direction == "bull"]
    assert bull_liq, "expected at least one bull liquidity cluster"
    assert bull_liq[0].count >= 2


# ─── full pipeline ──────────────────────────────────────────────────


def test_detect_all_does_not_crash_on_empty():
    state = detect_all([])
    assert state.swing_highs == [] and state.swing_lows == []
    assert state.events == [] and state.fvgs == []
    assert state.trend is None


def test_detect_all_runs_on_realistic_data():
    # Generate 200 bars with a random-walk-like pattern
    import random
    random.seed(42)
    bars: list[Bar] = []
    price = 1.1000
    for i in range(200):
        change = random.gauss(0, 0.0008)
        new = price + change
        h = max(price, new) + abs(random.gauss(0, 0.0003))
        l = min(price, new) - abs(random.gauss(0, 0.0003))
        bars.append(Bar(ts_ms=i * 60_000, open=price, high=h, low=l, close=new))
        price = new
    state = detect_all(bars)
    # Should produce some swings on 200 random-walk bars
    assert len(state.swing_highs) + len(state.swing_lows) > 5
    # FVGs may or may not exist; OB derived from events
    assert isinstance(state.fvgs, list)
