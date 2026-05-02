"""Walk-forward validator — window math + integration smoke test."""
from __future__ import annotations

import math

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import RiskConfig, SymbolMeta, Tick
from replay.harness import ReplayHarness
from replay.simulator import ExecutionModel
from replay.walk_forward import make_windows, walk_forward


SYMBOLS = {"EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS")}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}


def _ticks(n: int) -> list[Tick]:
    out = []
    for i in range(n):
        mid = 1.10 + 0.0005 * math.sin(i / 13) + 0.0002 * math.sin(i / 3)
        out.append(Tick("EURUSD", mid - 5e-5, mid + 5e-5, ts_ms=i))
    return out


# ─── window math ──────────────────────────────────────────────────────────

def test_window_math_basic():
    ws = make_windows(1000, train_size=400, test_size=200, step=200)
    # 400+200=600, then steps 200 → starts: 0, 200, 400 → train_end max = 800, test_end max = 1000
    assert len(ws) == 3
    assert ws[0].train_start == 0 and ws[0].test_end == 600
    assert ws[1].train_start == 200 and ws[1].test_end == 800
    assert ws[2].train_start == 400 and ws[2].test_end == 1000


def test_window_math_no_overlap_when_step_eq_test():
    ws = make_windows(900, train_size=300, test_size=150, step=150)
    # test ranges should be contiguous
    test_ranges = [(w.test_start, w.test_end) for w in ws]
    for a, b in zip(test_ranges, test_ranges[1:]):
        assert a[1] == b[0], "test windows should be contiguous when step == test_size"


def test_window_math_short_input_returns_empty():
    assert make_windows(100, train_size=200, test_size=50) == []


# ─── integration ──────────────────────────────────────────────────────────

def _tuner(_train_ticks):
    # Тоглоомын tuner: ямар ч tick-д үл хамаарч fixed params буцаана.
    return ({"fast": 5, "slow": 20, "lots": 0.10}, 0.0)


def _runner(params, test_ticks):
    risk = RiskManager(
        config=RiskConfig(min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    strat = EmaCrossStrategy(
        fast_period=params["fast"], slow_period=params["slow"], lots=params["lots"],
        symbol_filter=("EURUSD",),
    )
    h = ReplayHarness(
        strategy=strat, risk=risk, execution=ExecutionModel(seed=1),
        symbols=SYMBOLS, starting_equity=100_000.0,
    )
    return h.run(test_ticks)


def test_walk_forward_runs_and_aggregates():
    ticks = _ticks(2000)
    report = walk_forward(
        ticks, train_size=600, test_size=300, step=300,
        tuner=_tuner, test_runner=_runner,
    )
    assert len(report.windows) >= 4
    # Each window should have a result; OOS metrics are aggregable
    assert isinstance(report.total_test_pnl, float)
    assert isinstance(report.total_test_trades, int)
    s = report.summary()
    assert "windows=" in s and "oos_pnl=" in s
