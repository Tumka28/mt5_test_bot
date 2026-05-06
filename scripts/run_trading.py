"""Real trading brain — ariljaa-н бүрэн pipeline.

Ажиллах өмнө нөхцөл:
  1. MT5-д bridge_ea attach хийсэн, AllowExecution=true (paper test үед false-аар эхэл!)
  2. Tools → Options → Expert Advisors:
       ☑ Allow algorithmic trading
  3. Toolbar дээр "Algo Trading" товч асаасан
  4. Демо акаунттай (live акаунт ХЭЗЭЭ Ч ХЭРЭГЛЭХГҮЙ paper test-гүйгээр)

Usage:
    python scripts/run_trading.py --symbol EURUSD --mode paper
    python scripts/run_trading.py --symbol EURUSD --mode shadow --lots 0.01
    python scripts/run_trading.py --symbol EURUSD --mode live --lots 0.01

Live горимд env var заавал тохируулна:
    MT5BOT_HMAC=...                        (≥16 char secret)
    MT5BOT_HELLO_TOKEN=...                 (EA HelloToken-той ижил)
    MT5BOT_ALLOWED_LOGINS=12345,67890      (зөвшөөрөгдсөн account login)
    MT5BOT_I_KNOW_THIS_IS_REAL_MONEY=yes
    MT5BOT_STRICT=1
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from brain.news_calendar import load_forexfactory_csv
from brain.risk_manager import NewsCalendar, RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.trading_service import TradingService
from brain.types import RiskConfig, SymbolMeta
from bridge.tcp_server import BridgeTcpServer, _BridgeHandler
from observability import metrics
from observability.logger import configure
from persistence.journal import Journal
from scripts.preflight import check as preflight_check


# Per-mode max lots safety cap
_MODE_MAX_LOTS: dict[str, float | None] = {
    "paper":  None,    # demo — let strategy decide
    "shadow": 0.05,    # tiny on real
    "live":   0.50,    # absolute hard cap; raise консерватив
}


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


def _parse_logins(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            pass
    return tuple(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--mode", choices=["paper", "shadow", "live"], default="paper")
    p.add_argument("--lots", type=float, default=0.01)
    p.add_argument("--fast", type=int, default=12)
    p.add_argument("--slow", type=int, default=26)
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--metrics-port", type=int, default=9090)
    p.add_argument("--news-csv", default="", help="ForexFactory weekly CSV path")
    p.add_argument("--max-lots", type=float, default=None,
                   help="override per-mode max lots safety cap")
    p.add_argument("--skip-preflight", action="store_true")
    args = p.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    symbols, clusters = _load_symbols(ROOT / "config" / "symbols.yaml")
    configure(level="INFO", json=False)
    log = logging.getLogger("trading")

    # ─── PRE-FLIGHT ─────────────────────────────────────────────────
    if not args.skip_preflight:
        errs, warns = preflight_check(args.mode)
        for w in warns:
            log.warning("WARN: %s", w)
        if errs:
            for e in errs:
                log.error("ERROR: %s", e)
            log.error("PREFLIGHT FAILED — abort. (use --skip-preflight to bypass dev)")
            return 1

    if args.symbol not in symbols:
        log.error("unknown symbol %s; available: %s", args.symbol, list(symbols))
        return 1

    risk_cfg = RiskConfig(**cfg["risk"])

    # ─── NEWS CALENDAR ──────────────────────────────────────────────
    calendar = NewsCalendar()
    if args.news_csv:
        try:
            load_forexfactory_csv(
                args.news_csv, calendar=calendar,
                window_minutes=cfg["risk"]["news_blackout_minutes"],
            )
        except Exception as e:
            log.warning("news calendar load failed: %s", e)

    risk = RiskManager(
        config=risk_cfg, symbols=symbols, cluster_members=clusters,
        calendar=calendar,
    )
    strat = EmaCrossStrategy(
        fast_period=args.fast, slow_period=args.slow,
        lots=args.lots, symbol_filter=(args.symbol,),
    )
    journal_path = ROOT / cfg["journal"]["sqlite_path"]
    journal = Journal(journal_path)

    max_lots = args.max_lots if args.max_lots is not None else _MODE_MAX_LOTS[args.mode]
    expected_token = os.environ.get("MT5BOT_HELLO_TOKEN", "")
    expected_logins = _parse_logins(os.environ.get("MT5BOT_ALLOWED_LOGINS", ""))

    service = TradingService(
        strategy=strat, risk=risk, journal=journal, mode=args.mode,
        max_lots_per_order=max_lots,
        expected_token=expected_token,
        expected_logins=expected_logins,
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

    # ─── METRICS ───────────────────────────────────────────────────
    metrics.start_metrics_server(args.metrics_port)

    log.info("=" * 70)
    log.info("MT5 TRADING BRAIN")
    log.info("  mode=%s symbol=%s lots=%.2f strategy=ema(%d/%d)",
             args.mode, args.symbol, args.lots, args.fast, args.slow)
    log.info("  max_lots_cap=%s journal=%s", max_lots, journal_path)
    log.info("  listening on 127.0.0.1:%d (waiting for EA)", args.port)
    log.info("  metrics on http://127.0.0.1:%d/metrics", args.metrics_port)
    log.info("=" * 70)
    if args.mode == "live":
        log.warning("⚠️  MODE=LIVE — REAL MONEY ORDERS WILL BE SENT")
        log.warning("⚠️  EA-д AllowExecution=true, HelloToken таарсан байх ёстой")

    service.start_heartbeat()
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
                log.info("status: equity=%.2f pnl_today=%.2f positions=%d kill=%s",
                         a.equity, a.pnl_today, len(service._positions),
                         risk.kill_switch.is_armed())
    except KeyboardInterrupt:
        log.info("shutting down ...")
        service.stop_heartbeat()
        srv.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
