"""Параметрийн grid search — walk-forward-ийн tuner-аар хэрэглэх.

Хязгаарлагдмал param space-аар (жишээ нь fast ∈ {5,8,12}, slow ∈ {20,26,40})
бүх хослолыг train ticks-ээр replay хийж, тогтоосон objective-ээр (default:
sharpe-like = mean_pnl / std_pnl эсвэл total pnl) хамгийн сайныг буцаана.
"""
from __future__ import annotations

import itertools
import math
from typing import Callable, Iterable, Sequence

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import RiskConfig, SymbolMeta, Tick
from replay.harness import ReplayHarness, ReplayResult
from replay.simulator import ExecutionModel


# Objective: replay result-аас нэг скаляр буцаана. Том утга = илүү сайн.
Objective = Callable[[ReplayResult], float]


def total_pnl_objective(res: ReplayResult) -> float:
    return res.net_pnl


def trade_sharpe_objective(res: ReplayResult) -> float:
    """Trade-level "sharpe-like": mean(pnl per trade) / stdev(pnl per trade).

    Хэрэв trade < 5 бол маш бага утга (penalty) буцаана — too few samples."""
    pnls = [t.pnl_usd for t in res.closed_trades]
    if len(pnls) < 5:
        return -math.inf
    mean = sum(pnls) / len(pnls)
    var = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(var)
    if std <= 0:
        return -math.inf
    return mean / std


class GridSearch:
    def __init__(
        self, *,
        symbols: dict[str, SymbolMeta],
        clusters: dict[str, list[str]],
        symbol: str,
        param_grid: dict[str, Iterable],
        objective: Objective = total_pnl_objective,
        starting_equity: float = 100_000.0,
        seed: int = 42,
    ) -> None:
        self._symbols = symbols
        self._clusters = clusters
        self._symbol = symbol
        self._grid = {k: list(v) for k, v in param_grid.items()}
        self._obj = objective
        self._equity = starting_equity
        self._seed = seed

    def _all_combos(self) -> list[dict]:
        keys = list(self._grid.keys())
        out: list[dict] = []
        for combo in itertools.product(*[self._grid[k] for k in keys]):
            d = dict(zip(keys, combo))
            # discard invalid: fast >= slow
            if "fast" in d and "slow" in d and d["fast"] >= d["slow"]:
                continue
            out.append(d)
        return out

    def _replay(self, params: dict, ticks: Sequence[Tick]) -> ReplayResult:
        risk = RiskManager(
            config=RiskConfig(min_seconds_between_orders=0),
            symbols=self._symbols, cluster_members=self._clusters,
        )
        strat = EmaCrossStrategy(
            fast_period=params["fast"], slow_period=params["slow"],
            lots=params.get("lots", 0.10),
            symbol_filter=(self._symbol,),
        )
        h = ReplayHarness(
            strategy=strat, risk=risk,
            execution=ExecutionModel(seed=self._seed),
            symbols=self._symbols, starting_equity=self._equity,
        )
        return h.run(ticks)

    def search(self, ticks: Sequence[Tick]) -> tuple[dict, float, list[tuple[dict, float]]]:
        """Бүх combo-уудыг үнэлээд (best_params, best_score, full_results)."""
        results: list[tuple[dict, float]] = []
        best_params: dict = {}
        best_score = -math.inf
        for params in self._all_combos():
            res = self._replay(params, ticks)
            score = self._obj(res)
            results.append((params, score))
            if score > best_score:
                best_score = score
                best_params = params
        return best_params, best_score, results

    # walk_forward.Tuner интерфэйсэд тохирох wrapper
    def as_tuner(self):
        def _tune(train_ticks: Sequence[Tick]) -> tuple[dict, float]:
            best, score, _ = self.search(train_ticks)
            return best, score
        return _tune
