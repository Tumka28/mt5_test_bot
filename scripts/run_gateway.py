"""Run the MT5 → ZMQ gateway. Windows only (requires MetaTrader5 package).

    python scripts/run_gateway.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from bridge.mt5_gateway import MT5Gateway
from observability.logger import configure


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    configure(level=cfg["logging"]["level"], json=cfg["logging"]["json"])

    gw = MT5Gateway(
        pub_url=cfg["transport"]["pub_url"],
        symbols=cfg["mt5"]["symbols"],
        heartbeat_s=cfg["mt5"]["heartbeat_seconds"],
    )
    try:
        gw.start()
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(f"gateway error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
