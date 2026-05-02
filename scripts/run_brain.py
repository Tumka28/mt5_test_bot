"""Run the Python brain (subscriber + strategy + risk + dispatcher).

    python scripts/run_brain.py

Энэ хувилбарт:
- Strategy: NoopStrategy (огт trade хийдэггүй) — wiring-ыг тестлэх зориулалттай.
- Account / positions: stub callable-аар $100k acct, нээлттэй pos алга.
- Dispatcher: REQ socket байхгүй тул print-only stub-аар.

Бодит deploy-ийн өмнө стратеги, account_provider, dispatcher RPC-ийг шинэчил.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from brain.order_dispatcher import OrderDispatcher
from brain.risk_manager import RiskManager
from brain.service import BrainService
from brain.strategy_base import NoopStrategy
from brain.types import AccountState, RiskConfig, SymbolMeta
from bridge.transport import Subscriber
from observability.logger import configure


def _load_symbols(cfg_path: Path) -> tuple[dict[str, SymbolMeta], dict[str, list[str]]]:
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
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


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    symbols, clusters = _load_symbols(ROOT / "config" / "symbols.yaml")
    configure(level=cfg["logging"]["level"], json=cfg["logging"]["json"])

    risk = RiskManager(
        config=RiskConfig(**cfg["risk"]),
        symbols=symbols,
        cluster_members=clusters,
    )
    sub = Subscriber(cfg["transport"]["pub_url"])
    dispatcher = OrderDispatcher(rpc_send=lambda p: print("ORDER:", p) or {"ok": True})

    service = BrainService(
        subscriber=sub,
        strategy=NoopStrategy(),
        risk=risk,
        dispatcher=dispatcher,
        account_provider=lambda: AccountState(equity=100_000, balance=100_000),
        positions_provider=lambda: [],
        heartbeat_timeout_s=cfg["mt5"]["flatten_on_silence_seconds"],
    )

    try:
        service.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
