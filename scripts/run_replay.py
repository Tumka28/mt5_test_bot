"""Replay a recorded parquet (or synthetic stream) through the same strategy +
risk + execution model that the live brain uses.

Usage:
    python scripts/run_replay.py --synthetic regime_flip --ticks 1000
    python scripts/run_replay.py --parquet data/ticks/ticks-2026-04-15.parquet --symbol EURUSD
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.types import RiskConfig, SymbolMeta, Tick
from observability.logger import configure
from replay.harness import ReplayHarness, ticks_from_parquet
from replay.simulator import ExecutionModel


def _load_symbols(path: Path) -> tuple[dict[str, SymbolMeta], dict[str, list[str]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    clusters = raw.pop("_clusters", {})
    symbols = {
        name: SymbolMeta(
            contract_size=v["contract_size"], min_lot=v["min_lot"],
            lot_step=v["lot_step"], pip_value_usd=v["pip_value_usd"],
            cluster=v["cluster"], typical_spread_pips=v.get("typical_spread_pips", 0.0),
        )
        for name, v in raw.items()
    }
    return symbols, clusters


def _synthetic(regime: str, n: int, symbol: str) -> list[Tick]:
    out: list[Tick] = []
    for i in range(n):
        if regime == "trend_up":
            mid = 1.1000 + i * 0.00005
        elif regime == "trend_down":
            mid = 1.1000 - i * 0.00005
        elif regime == "noisy":
            mid = 1.1000 + 0.001 * math.sin(i / 11) + 0.0003 * math.sin(i / 3)
        elif regime == "regime_flip":
            mid = 1.1000 + (i * 0.00005 if i < n // 2 else
                            (n // 2) * 0.00005 - (i - n // 2) * 0.00007)
        else:
            raise SystemExit(f"unknown regime: {regime}")
        out.append(Tick(symbol=symbol, bid=mid - 0.00005, ask=mid + 0.00005, ts_ms=i))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--parquet", type=Path)
    src.add_argument("--synthetic", choices=["trend_up", "trend_down", "noisy", "regime_flip"])
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--ticks", type=int, default=1000, help="for --synthetic")
    p.add_argument("--lots", type=float, default=0.10)
    p.add_argument("--fast", type=int, default=12)
    p.add_argument("--slow", type=int, default=26)
    args = p.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    symbols, clusters = _load_symbols(ROOT / "config" / "symbols.yaml")
    configure(level="INFO", json=False)

    if args.symbol not in symbols:
        print(f"unknown symbol {args.symbol}; available: {list(symbols)}", file=sys.stderr)
        return 1

    risk_cfg = RiskConfig(**cfg["risk"])
    # Replay-д rate-limit утгагүй (wall-clock биш virtual time)
    risk_cfg.min_seconds_between_orders = 0
    risk = RiskManager(config=risk_cfg, symbols=symbols, cluster_members=clusters)

    strategy = EmaCrossStrategy(
        fast_period=args.fast, slow_period=args.slow,
        lots=args.lots, symbol_filter=(args.symbol,),
    )
    harness = ReplayHarness(
        strategy=strategy, risk=risk,
        execution=ExecutionModel(seed=42),
        symbols=symbols, starting_equity=100_000.0,
    )

    if args.parquet:
        ticks = list(ticks_from_parquet(str(args.parquet), args.symbol))
    else:
        ticks = _synthetic(args.synthetic, args.ticks, args.symbol)

    print(f"replay: source={'parquet' if args.parquet else args.synthetic} "
          f"symbol={args.symbol} ticks={len(ticks)}")
    res = harness.run(ticks)
    print(res.summary())
    print(f"closed trades: {len(res.closed_trades)}")
    for t in res.closed_trades[:10]:
        print(f"  {t.symbol} {t.side} {t.lots} "
              f"entry={t.entry:.5f} exit={t.exit_price:.5f} "
              f"pnl={t.pnl_usd:+.2f} reason={t.reason}")
    if len(res.closed_trades) > 10:
        print(f"  ... and {len(res.closed_trades) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
