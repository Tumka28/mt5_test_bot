"""Projection generator тест."""
from __future__ import annotations

from brain.bar import Bar
from brain.projection import project
from brain.smc import detect_all


def _bars_uptrend() -> list[Bar]:
    """Зориудаар bullish trend үүсгэе — байнга өгсөж буй bar-ууд."""
    bars: list[Bar] = []
    price = 1.10
    for i in range(80):
        new = price + 0.0006 + (0.0004 if i % 7 == 0 else 0.0)
        h = new + 0.0003
        l = price - 0.0001
        bars.append(Bar(ts_ms=i * 60_000, open=price, high=h, low=l, close=new))
        price = new
    return bars


def _bars_downtrend() -> list[Bar]:
    bars: list[Bar] = []
    price = 1.20
    for i in range(80):
        new = price - 0.0006 - (0.0004 if i % 7 == 0 else 0.0)
        h = price + 0.0001
        l = new - 0.0003
        bars.append(Bar(ts_ms=i * 60_000, open=price, high=h, low=l, close=new))
        price = new
    return bars


def test_project_returns_bull_and_bear():
    state = detect_all(_bars_uptrend())
    projs = project(state)
    dirs = {p.direction for p in projs}
    assert dirs == {"bull", "bear"}


def test_bull_projection_has_increasing_targets():
    state = detect_all(_bars_uptrend())
    projs = project(state)
    bull = next(p for p in projs if p.direction == "bull")
    assert bull.tp1 < bull.tp2 <= bull.structure_target <= bull.big_target
    last_close = state.bars[-1].close
    assert bull.invalidation < last_close
    assert bull.tp1 > last_close


def test_bear_projection_has_decreasing_targets():
    state = detect_all(_bars_downtrend())
    projs = project(state)
    bear = next(p for p in projs if p.direction == "bear")
    assert bear.tp1 > bear.tp2 >= bear.structure_target >= bear.big_target
    last_close = state.bars[-1].close
    assert bear.invalidation > last_close
    assert bear.tp1 < last_close


def test_probability_bounded():
    state = detect_all(_bars_uptrend())
    for p in project(state):
        assert 0.05 <= p.probability <= 0.95


def test_trend_aligned_has_higher_probability():
    state = detect_all(_bars_uptrend())
    projs = project(state)
    by_dir = {p.direction: p for p in projs}
    if state.trend == "bull":
        assert by_dir["bull"].probability >= by_dir["bear"].probability


def test_waypoints_chronological():
    state = detect_all(_bars_uptrend())
    for p in project(state):
        ts_list = [t for t, _ in p.waypoints]
        assert ts_list == sorted(ts_list)
        assert len(p.waypoints) >= 3


def test_project_empty_bars_returns_empty():
    from brain.smc import StructureState
    assert project(StructureState()) == []
