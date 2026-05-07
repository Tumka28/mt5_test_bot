"""SMC advisor — chart дээр SMC analysis + projection line зурдаг standalone сервис.

Trading биш — зөвхөн analysis + visualization. EA-аас bars + tick авч, chart дээр
zone + projection + label-уудыг зурна. Хэрэглээ:

    python scripts/run_smc.py --symbol EURUSD --tf M5
    python scripts/run_smc.py --symbol XAUUSD --tf M15 --bars 500 --period 10

EA-ийн зүгээс `bridge_ea.mq5`-ийг тэгш symbol chart-руу attach хийсэн байх ёстой
(AllowExecution=false ч асуудалгүй — зөвхөн draw command явна).
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

from brain.smc_advisor import AdvisorOutput, SmcAdvisor
from bridge.tcp_server import BridgeTcpServer, _BridgeHandler
from observability.logger import configure


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--tf", default="M5", choices=["M1", "M5", "M15", "M30", "H1", "H4", "D1"])
    p.add_argument("--bars", type=int, default=300)
    p.add_argument("--period", type=float, default=5.0,
                   help="re-analysis period in seconds")
    p.add_argument("--port", type=int, default=5555)
    args = p.parse_args()

    configure(level="INFO", json=False)
    log = logging.getLogger("smc")

    def _signal_cb(text: str, out: AdvisorOutput) -> None:
        # Console-руу хэвлэнэ; production-д Telegram bot руу шилжүүлэх боломжтой
        log.info("\n%s", text)

    advisor = SmcAdvisor(
        symbol=args.symbol, timeframe=args.tf, bars_window=args.bars,
        analysis_period_s=args.period, signal_callback=_signal_cb,
    )

    def on_msg(msg: dict, h: _BridgeHandler) -> None:
        advisor.on_message(msg, h)

    def on_conn(h: _BridgeHandler) -> None:
        srv.set_client(h)
        advisor.on_connect(h)

    def on_disc(h: _BridgeHandler) -> None:
        srv.set_client(None)
        advisor.on_disconnect(h)

    srv = BridgeTcpServer(
        ("127.0.0.1", args.port),
        on_message=on_msg, on_connect=on_conn, on_disconnect=on_disc,
    )

    log.info("=" * 70)
    log.info("MT5 SMC ADVISOR")
    log.info("  symbol=%s timeframe=%s bars_window=%d period=%.1fs",
             args.symbol, args.tf, args.bars, args.period)
    log.info("  listening on 127.0.0.1:%d (waiting for EA)", args.port)
    log.info("=" * 70)

    advisor.start()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("shutting down ...")
        advisor.stop()
        srv.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
