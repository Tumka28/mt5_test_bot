"""EMA crossover strategy — direct unit tests (no replay harness)."""
from __future__ import annotations

import math

from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import Tick


def _tick(mid: float, ts_ms: int = 0) -> Tick:
    return Tick(symbol="EURUSD", bid=mid - 0.00005, ask=mid + 0.00005, ts_ms=ts_ms)


def test_warmup_no_signals():
    s = EmaCrossStrategy()
    intents = []
    for i in range(40):
        intents += s.on_tick(_tick(1.10, ts_ms=i))
    assert intents == [], "should not signal during warmup"


def test_bullish_crossover_emits_buy():
    s = EmaCrossStrategy(fast_period=5, slow_period=20)
    # 80 ticks downtrend → EMAs aligned bearish
    intents: list = []
    for i in range(80):
        intents += s.on_tick(_tick(1.10 - i * 0.0001, ts_ms=i))
    # then sharp uptrend
    last = []
    for i in range(80, 200):
        last += s.on_tick(_tick(1.0920 + (i - 80) * 0.0003, ts_ms=i))
    assert any(o.side == "buy" for o in last), "expected at least one buy on bullish flip"


def test_stop_loss_always_set():
    s = EmaCrossStrategy(fast_period=3, slow_period=10)
    intents: list = []
    for i in range(200):
        # noisy walk — guaranteed to produce some crossovers
        m = 1.10 + 0.001 * math.sin(i / 7)
        intents += s.on_tick(_tick(m, ts_ms=i))
    assert intents, "noisy walk should produce signals"
    assert all(o.stop_loss is not None for o in intents)
    assert all(o.take_profit is not None for o in intents)


def test_fast_must_be_less_than_slow():
    import pytest
    with pytest.raises(ValueError):
        EmaCrossStrategy(fast_period=20, slow_period=10)
