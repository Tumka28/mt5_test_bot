"""Real trading brain — ariljaa-н бүрэн pipeline.

Ажиллах өмнө нөхцөл:
  1. MT5-д bridge_ea attach хийсэн, AllowExecution=true (paper test үед false-аар эхэл!)
  2. Tools → Options → Expert Advisors:
       ☑ Allow algorithmic trading
       ☑ Allow WebRequest for: http://127.0.0.1:5555
  3. Toolbar дээр "Algo Trading" товч асаасан
  4. Демо акаунттай (live акаунт ХЭЗЭЭ Ч ХЭРЭГЛЭХГҮЙ paper test-гүйгээр)

Usage:
    python scripts/run_trading.py --symbol EURUSD --mode paper
    python scripts/run_trading.py --symbol EURUSD --mode shadow --lots 0.01
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.trading_service import TradingService
from brain.types import RiskConfig, SymbolMeta
from bridge.tcp_server import BridgeTcpServer, _BridgeHandler
from observability.logger import configure
from persistence.journal import Journal


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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--mode", choices=["paper", "shadow", "live"], default="paper")
    p.add_argument("--lots", type=float, default=0.01)
    p.add_argument("--fast", type=int, default=12)
    p.add_argument("--slow", type=int, default=26)
    p.add_argument("--port", type=int, default=5555)
    args = p.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    symbols, clusters = _load_symbols(ROOT / "config" / "symbols.yaml")
    configure(level="INFO", json=False)
    log = logging.getLogger("trading")

    if args.symbol not in symbols:
        log.error("unknown symbol %s; available: %s", args.symbol, list(symbols))
        return 1

    risk_cfg = RiskConfig(**cfg["risk"])
    risk = RiskManager(config=risk_cfg, symbols=symbols, cluster_members=clusters)
    strat = EmaCrossStrategy(
        fast_period=args.fast, slow_period=args.slow,
        lots=args.lots, symbol_filter=(args.symbol,),
    )
    journal_path = ROOT / cfg["journal"]["sqlite_path"]
    journal = Journal(journal_path)

    service = TradingService(
        strategy=strat, risk=risk, journal=journal, mode=args.mode,
    )

    def on_msg(msg: dict, h: _BridgeHandler) -> None:
        service.on_message(msg, h)

    def on_conn(h: _BridgeHandler) -> None:
        srv.set_client(h)
        service.on_connect(h)

    def on_disc(h: _BridgeHandler) -> None:
        srv.set_client(None)
        service.on_disconnect(h)

    srv = BridgeTcpServer(
        ("127.0.0.1", args.port),
        on_message=on_msg, on_connect=on_conn, on_disconnect=on_disc,
    )

    log.info("=" * 70)
    log.info("MT5 TRADING BRAIN")
    log.info("  mode=%s symbol=%s lots=%.2f strategy=ema(%d/%d)",
             args.mode, args.symbol, args.lots, args.fast, args.slow)
    log.info("  journal=%s", journal_path)
    log.info("  listening on 127.0.0.1:%d (waiting for EA)", args.port)
    log.info("=" * 70)
    if args.mode == "live":
        log.warning("⚠️  MODE=LIVE — REAL MONEY ORDERS WILL BE SENT")
        log.warning("⚠️  AllowExecution=true MUST also be set in EA inputs")

    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        last_summary = 0.0
        while True:
            time.sleep(5.0)
            now = time.time()
            if now - last_summary > 60:
                last_summary = now
                a = service._account  # noqa: SLF001 — internal peek for status
                log.info("status: equity=%.2f pnl_today=%.2f positions=%d",
                         a.equity, a.pnl_today, len(service._positions))
    except KeyboardInterrupt:
        log.info("shutting down ...")
        srv.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
