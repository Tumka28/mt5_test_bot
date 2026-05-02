"""Brain service — main loop.

Эх workflow:
    tick subscribe → strategy.on_tick → for intent in intents:
        risk.check(intent) → approved? → dispatcher.submit(intent)

Энэ файл зөвхөн wiring хариуцана. Бизнес логик strategy / risk / dispatcher-д
байх ёстой.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from brain.order_dispatcher import OrderDispatcher
from brain.risk_manager import RiskManager
from brain.strategy_base import Strategy
from brain.types import AccountState, Position, Tick
from bridge.transport import Subscriber

logger = logging.getLogger(__name__)


class BrainService:
    def __init__(
        self,
        *,
        subscriber: Subscriber,
        strategy: Strategy,
        risk: RiskManager,
        dispatcher: OrderDispatcher,
        account_provider,                  # callable() -> AccountState
        positions_provider,                # callable() -> Iterable[Position]
        heartbeat_timeout_s: int = 60,
    ) -> None:
        self._sub = subscriber
        self._strat = strategy
        self._risk = risk
        self._disp = dispatcher
        self._account_provider = account_provider
        self._positions_provider = positions_provider
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._last_gateway_hb = time.time()

    def run_forever(self) -> None:
        logger.info("brain started, strategy=%s", self._strat.name)
        while True:
            msg = self._sub.recv(timeout_ms=500)
            if msg is None:
                self._maybe_panic_flatten()
                continue

            t = msg.get("type")
            if t == "heartbeat":
                self._last_gateway_hb = time.time()
                continue
            if t != "tick":
                continue

            tick = Tick(
                symbol=msg["symbol"], bid=msg["bid"], ask=msg["ask"],
                ts_ms=int(msg["ts_ms"]),
            )
            self._handle_tick(tick)
            self._maybe_panic_flatten()

    # ─── internals ──────────────────────────────────────────────────────

    def _handle_tick(self, tick: Tick) -> None:
        intents = self._strat.on_tick(tick)
        if not intents:
            return
        account = self._account_provider()
        positions = list(self._positions_provider())
        for intent in intents:
            decision = self._risk.check(
                intent,
                account=account,
                positions=positions,
                last_tick=tick,
                now_ms=tick.ts_ms,
            )
            if not decision.approved:
                logger.info("risk reject: id=%s reason=%s",
                            intent.client_order_id, decision.reason)
                continue
            try:
                self._disp.submit(intent)
            except Exception as exc:
                logger.error("dispatcher error: %s", exc)

    def _maybe_panic_flatten(self) -> None:
        """Gateway-аас heartbeat ирэхгүй удвал kill switch-ийг arm хийнэ.
        Live mode-д order dispatcher-аар flatten-all хүсэлт явуулах ёстой —
        энэ хувилбарт зөвхөн kill arm хийнэ."""
        if time.time() - self._last_gateway_hb > self._heartbeat_timeout_s:
            if not self._risk.kill_switch.is_armed():
                self._risk.kill_switch.arm("gateway_heartbeat_lost")
