"""Walk-forward validator.

Зорилго: static train/test split-ийн overfitting-ийг илрүүлэх.

Алгоритм:
    Tick stream-ийг N тэнцүү цонхонд хуваана.
    Цонх бүр дээр:
        train_window = ticks[i : i+train_size]
        test_window  = ticks[i+train_size : i+train_size+test_size]
    Train дээр tune (grid search) → best params
    Test дээр энэ params-аар replay → OOS P&L бичнэ
    Цонхыг step_size-аар урагшлуулна

Энэ файл walk-forward-ийн **скаффолд**: actual params-tuning grid search-ийн
хариуцлага. Энэ class зөвхөн window-уудыг үүсгэж, өгсөн `evaluate(params, ticks)`
callable-аар train/test үнэлгээг гүйцэтгэнэ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from brain.types import Tick
from replay.harness import ReplayResult


@dataclass
class Window:
    index: int
    train_start: int
    train_end: int           # exclusive
    test_start: int
    test_end: int            # exclusive

    @property
    def train_len(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_len(self) -> int:
        return self.test_end - self.test_start


@dataclass
class WindowResult:
    window: Window
    best_params: dict
    train_metric: float                # objective on train (chosen by tuner)
    test_result: ReplayResult


@dataclass
class WalkForwardReport:
    windows: list[WindowResult]

    @property
    def total_test_pnl(self) -> float:
        return sum(w.test_result.net_pnl for w in self.windows)

    @property
    def total_test_trades(self) -> int:
        return sum(len(w.test_result.closed_trades) for w in self.windows)

    @property
    def avg_train_metric(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.train_metric for w in self.windows) / len(self.windows)

    def summary(self) -> str:
        n = len(self.windows)
        wins = sum(1 for w in self.windows if w.test_result.net_pnl > 0)
        return (
            f"windows={n} oos_pnl={self.total_test_pnl:+.2f} "
            f"oos_trades={self.total_test_trades} "
            f"win_windows={wins}/{n} "
            f"avg_train_metric={self.avg_train_metric:+.4f}"
        )


# Tuner contract: дамжуулсан train_ticks дээр best params-ийг олж, train metric-ийн
# хамт буцаана. Test phase-д энэ params-аар replay руу дамжуулна.
Tuner = Callable[[Sequence[Tick]], tuple[dict, float]]
# Test runner: params + test_ticks → ReplayResult.
TestRunner = Callable[[dict, Sequence[Tick]], ReplayResult]


def make_windows(
    n_ticks: int, *, train_size: int, test_size: int, step: int | None = None,
) -> list[Window]:
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train/test size must be positive")
    if step is None:
        step = test_size
    out: list[Window] = []
    i = 0
    idx = 0
    while i + train_size + test_size <= n_ticks:
        out.append(Window(
            index=idx,
            train_start=i, train_end=i + train_size,
            test_start=i + train_size, test_end=i + train_size + test_size,
        ))
        idx += 1
        i += step
    return out


def walk_forward(
    ticks: Sequence[Tick], *,
    train_size: int, test_size: int, step: int | None = None,
    tuner: Tuner, test_runner: TestRunner,
) -> WalkForwardReport:
    windows = make_windows(
        len(ticks), train_size=train_size, test_size=test_size, step=step,
    )
    results: list[WindowResult] = []
    for w in windows:
        train_slice = ticks[w.train_start:w.train_end]
        test_slice = ticks[w.test_start:w.test_end]
        params, train_metric = tuner(train_slice)
        test_res = test_runner(params, test_slice)
        results.append(WindowResult(
            window=w, best_params=params,
            train_metric=train_metric, test_result=test_res,
        ))
    return WalkForwardReport(windows=results)
