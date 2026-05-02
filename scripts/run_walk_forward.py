"""End-to-end backtest pipeline:

  ingest CSV → parquet → walk-forward(grid_search train + replay test)
  → out-of-sample report.

Usage:
    # 1. (өмнө нь нэг л удаа) CSV-г parquet руу хөрвүүлэх:
    python scripts/run_walk_forward.py ingest --csv data/raw/EURUSD_2024.csv \
        --symbol EURUSD --out data/ticks/EURUSD-2024.parquet

    # 2. parquet дээр walk-forward + grid search:
    python scripts/run_walk_forward.py walk \
        --parquet data/ticks/EURUSD-2024.parquet \
        --symbol EURUSD --train 5000 --test 2000

    # 3. синтетик data дээр шууд (аль ч CSV хэрэггүй):
    python scripts/run_walk_forward.py walk \
        --synthetic noisy --ticks 8000 --symbol EURUSD --train 2000 --test 800
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from brain.types import SymbolMeta, Tick
from observability.logger import configure
from replay.grid_search import GridSearch, total_pnl_objective
from replay.harness import ReplayHarness, ticks_from_parquet
from replay.simulator import ExecutionModel
from replay.walk_forward import walk_forward
from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import RiskConfig


def _load_symbols(path: Path) -> tuple[dict[str, SymbolMeta], dict[str, list[str]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    clusters = raw.pop("_clusters", {})
    syms = {
        name: SymbolMeta(
            contract_size=v["contract_size"], min_lot=v["min_lot"],
            lot_step=v["lot_step"], pip_value_usd=v["pip_value_usd"],
            cluster=v["cluster"], typical_spread_pips=v.get("typical_spread_pips", 0.0),
        )
        for name, v in raw.items()
    }
    return syms, clusters


def _synthetic(regime: str, n: int, symbol: str) -> list[Tick]:
    out: list[Tick] = []
    for i in range(n):
        if regime == "trend_up":
            mid = 1.10 + i * 0.00003
        elif regime == "trend_down":
            mid = 1.10 - i * 0.00003
        elif regime == "noisy":
            mid = 1.10 + 0.0008 * math.sin(i / 13) + 0.0003 * math.sin(i / 3)
        elif regime == "regime_flip":
            mid = 1.10 + (i * 0.00004 if i < n // 2 else
                          (n // 2) * 0.00004 - (i - n // 2) * 0.00006)
        else:
            raise SystemExit(f"unknown regime: {regime}")
        out.append(Tick(symbol=symbol, bid=mid - 5e-5, ask=mid + 5e-5, ts_ms=i))
    return out


def cmd_ingest(args) -> int:
    from ingest.dukascopy_csv import csv_to_parquet
    n = csv_to_parquet(args.csv, args.out, args.symbol)
    print(f"ingested {n} rows -> {args.out}")
    return 0


def cmd_walk(args) -> int:
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    symbols, clusters = _load_symbols(ROOT / "config" / "symbols.yaml")
    configure(level="INFO", json=False)

    if args.symbol not in symbols:
        print(f"unknown symbol; available: {list(symbols)}", file=sys.stderr)
        return 1

    if args.parquet:
        ticks = list(ticks_from_parquet(str(args.parquet), args.symbol))
    else:
        ticks = _synthetic(args.synthetic, args.ticks, args.symbol)

    if len(ticks) < args.train + args.test:
        print(f"too few ticks: have {len(ticks)}, need >= {args.train + args.test}",
              file=sys.stderr)
        return 1

    print(f"loaded {len(ticks)} ticks; running walk-forward train={args.train} test={args.test}")

    gs = GridSearch(
        symbols=symbols, clusters=clusters, symbol=args.symbol,
        param_grid={
            "fast": [5, 8, 12],
            "slow": [20, 26, 40],
            "lots": [args.lots],
        },
        objective=total_pnl_objective,
    )

    def runner(params, test_ticks):
        risk_cfg = RiskConfig(**cfg["risk"])
        risk_cfg.min_seconds_between_orders = 0
        risk = RiskManager(config=risk_cfg, symbols=symbols, cluster_members=clusters)
        strat = EmaCrossStrategy(
            fast_period=params["fast"], slow_period=params["slow"],
            lots=params["lots"], symbol_filter=(args.symbol,),
        )
        h = ReplayHarness(
            strategy=strat, risk=risk,
            execution=ExecutionModel(seed=42),
            symbols=symbols, starting_equity=100_000.0,
        )
        return h.run(test_ticks)

    report = walk_forward(
        ticks, train_size=args.train, test_size=args.test,
        step=args.test, tuner=gs.as_tuner(), test_runner=runner,
    )

    print()
    print("-" * 78)
    print("PER-WINDOW (out-of-sample):")
    print(f"  {'win':>3} | {'fast':>4} {'slow':>4} | "
          f"{'train_metric':>12} | {'oos_pnl':>10} {'trades':>6}")
    for wr in report.windows:
        print(f"  {wr.window.index:>3} | "
              f"{wr.best_params.get('fast', 0):>4} "
              f"{wr.best_params.get('slow', 0):>4} | "
              f"{wr.train_metric:>12.2f} | "
              f"{wr.test_result.net_pnl:>+10.2f} "
              f"{len(wr.test_result.closed_trades):>6}")
    print("-" * 78)
    print("AGGREGATE:", report.summary())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="CSV → parquet")
    pi.add_argument("--csv", type=Path, required=True)
    pi.add_argument("--out", type=Path, required=True)
    pi.add_argument("--symbol", required=True)
    pi.set_defaults(func=cmd_ingest)

    pw = sub.add_parser("walk", help="walk-forward + grid search")
    src = pw.add_mutually_exclusive_group(required=True)
    src.add_argument("--parquet", type=Path)
    src.add_argument("--synthetic", choices=["trend_up", "trend_down", "noisy", "regime_flip"])
    pw.add_argument("--symbol", default="EURUSD")
    pw.add_argument("--ticks", type=int, default=8000)
    pw.add_argument("--train", type=int, default=2000)
    pw.add_argument("--test", type=int, default=800)
    pw.add_argument("--lots", type=float, default=0.10)
    pw.set_defaults(func=cmd_walk)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
