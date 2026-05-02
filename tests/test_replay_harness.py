"""End-to-end replay harness тест.

Synthetic tick stream → EmaCrossStrategy → RiskManager → ExecutionModel →
ReplayResult. Pipeline-ийн бүх хэсэг ажиллаж байгааг батална.
"""
from __future__ import annotations

import math

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import RiskConfig, SymbolMeta, Tick
from replay.harness import ReplayHarness
from replay.simulator import ExecutionModel


SYMBOLS = {
    "EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS"),
}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}


def synth_ticks(n: int = 600, *, regime: str = "trend_up") -> list[Tick]:
    out = []
    for i in range(n):
        if regime == "trend_up":
            mid = 1.1000 + i * 0.00005
        elif regime == "trend_down":
            mid = 1.1000 - i * 0.00005
        elif regime == "noisy":
            mid = 1.1000 + 0.001 * math.sin(i / 11) + 0.0003 * math.sin(i / 3)
        elif regime == "regime_flip":
            mid = 1.1000 + (i * 0.00005 if i < n // 2 else (n // 2) * 0.00005 - (i - n // 2) * 0.00007)
        else:
            mid = 1.1000
        out.append(Tick(symbol="EURUSD", bid=mid - 0.00005, ask=mid + 0.00005, ts_ms=i))
    return out


def make_harness(*, lots: float = 0.10) -> ReplayHarness:
    risk = RiskManager(
        config=RiskConfig(min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    return ReplayHarness(
        strategy=EmaCrossStrategy(fast_period=5, slow_period=20, lots=lots),
        risk=risk,
        execution=ExecutionModel(seed=42),
        symbols=SYMBOLS,
        starting_equity=100_000.0,
    )


def test_pipeline_runs_without_error():
    h = make_harness()
    res = h.run(synth_ticks(300, regime="noisy"))
    assert res.ticks_processed == 300


def test_regime_flip_produces_trades():
    h = make_harness()
    res = h.run(synth_ticks(800, regime="regime_flip"))
    # Should generate at least one signal (regime flip ⇒ EMA crossover)
    assert res.intents_generated >= 1
    # And at least one fill should have happened
    assert res.fills >= 1


def test_oversized_lots_all_rejected_by_risk():
    """5.0 lots × ~10 pip stop = $5000 risk on $100k = 5%. Risk cap = 0.5%.
    Бүх intent reject хийгдэх ёстой."""
    h = make_harness(lots=5.0)
    res = h.run(synth_ticks(800, regime="regime_flip"))
    if res.intents_generated > 0:
        assert res.intents_rejected == res.intents_generated
        assert res.fills == 0


def test_pnl_accounting_balances():
    """Хаасан trade-уудын pnl-ын нийлбэр equity өөрчлөлттэй ойролцоо тэнцэх ёстой
    (commission-ыг тооцвол яг тэнцэнэ)."""
    h = make_harness()
    res = h.run(synth_ticks(600, regime="regime_flip"))
    expected_eq = 100_000.0 + res.net_pnl - res.commissions_paid
    assert abs(res.final_equity - expected_eq) < 0.01, (
        f"equity={res.final_equity} expected~{expected_eq} "
        f"pnl={res.net_pnl} fills={res.fills}"
    )


def test_summary_string_renders():
    h = make_harness()
    res = h.run(synth_ticks(200, regime="trend_up"))
    s = res.summary()
    assert "ticks=200" in s
    assert "pnl_usd=" in s
