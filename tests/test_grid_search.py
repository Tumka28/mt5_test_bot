"""Grid search — combos enumerated, invalid pruned, objective drives selection."""
from __future__ import annotations

import math

from brain.types import SymbolMeta, Tick
from replay.grid_search import (
    GridSearch,
    total_pnl_objective,
    trade_sharpe_objective,
)
from replay.harness import ReplayResult


SYMBOLS = {"EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS")}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}


def _ticks(n: int) -> list[Tick]:
    out = []
    for i in range(n):
        mid = 1.10 + 0.0005 * math.sin(i / 11)
        out.append(Tick("EURUSD", mid - 5e-5, mid + 5e-5, ts_ms=i))
    return out


def test_grid_combos_prune_invalid():
    gs = GridSearch(
        symbols=SYMBOLS, clusters=CLUSTERS, symbol="EURUSD",
        param_grid={"fast": [5, 12, 20], "slow": [10, 20]},
    )
    combos = gs._all_combos()
    for c in combos:
        assert c["fast"] < c["slow"]
    # 5<10, 5<20, 12<20 → 3 combos
    assert len(combos) == 3


def test_grid_search_runs_and_picks_best():
    gs = GridSearch(
        symbols=SYMBOLS, clusters=CLUSTERS, symbol="EURUSD",
        param_grid={"fast": [3, 5], "slow": [12, 20]},
        objective=total_pnl_objective,
    )
    best, score, all_results = gs.search(_ticks(800))
    assert "fast" in best and "slow" in best
    # best score is the max of all
    assert score == max(s for _, s in all_results)


def test_grid_search_as_tuner_signature_compatible():
    gs = GridSearch(
        symbols=SYMBOLS, clusters=CLUSTERS, symbol="EURUSD",
        param_grid={"fast": [5], "slow": [20]},
    )
    tuner = gs.as_tuner()
    params, score = tuner(_ticks(400))
    assert params["fast"] == 5 and params["slow"] == 20
    assert isinstance(score, float)


def test_trade_sharpe_objective_penalises_few_trades():
    res = ReplayResult()  # 0 trades
    assert trade_sharpe_objective(res) == -math.inf
