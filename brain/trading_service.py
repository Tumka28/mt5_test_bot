"""Full trading brain service — wires:

    EA tick stream → Strategy → RiskManager → Order send to EA → reply → Journal

Энэ нь ariljaa-н бодит pipeline. Ажиллахаас өмнө EA-ийн `AllowExecution`-ийг
true болгох ёстой (default false = dry run).

Анхаар:
- Live deploy-ийн өмнө demo акаунт дээр **4 долоо хоног** paper test хийнэ.
- Бодит мөнгөнд нэвтрэхээс өмнө DEV → BACKTEST → PAPER → SHADOW → PROD
  5-tier funnel-ыг бүрэн дуусгасан байх ёстой.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from brain.order_dispatcher import OrderDispatcher
from brain.risk_manager import RiskManager
from brain.strategy_base import Strategy
from brain.types import AccountState, OrderIntent, Position, Tick
from bridge.tcp_server import _BridgeHandler, encode_pipe
from persistence.journal import Journal

logger = logging.getLogger(__name__)


class TradingService:
    """One per running brain. Not thread-safe vs strategies — single-threaded
    on the handler thread of the TCP server."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        risk: RiskManager,
        journal: Journal,
        mode: str = "paper",  # "paper" | "shadow" | "live"
    ) -> None:
        self._strat = strategy
        self._risk = risk
        self._journal = journal
        self._mode = mode

        # State updated by EA messages
        self._account = AccountState(equity=0.0, balance=0.0, currency="USD")
        self._positions: dict[int, Position] = {}   # ticket → Position
        # When EA pushes a snapshot, we accumulate then swap on positions_end
        self._pending_positions: dict[int, Position] = {}
        self._last_tick_per_symbol: dict[str, Tick] = {}

        # The handler used to send orders (set on connect)
        self._handler: _BridgeHandler | None = None
        self._lock = threading.Lock()
        self._pending_orders: dict[str, OrderIntent] = {}  # client_id → intent

    # ─── EA-side hooks (called from TCP handler thread) ─────────────────

    def on_connect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            self._handler = handler
        logger.info("trading service: EA registered")

    def on_disconnect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            if self._handler is handler:
                self._handler = None
        logger.info("trading service: EA gone")

    def on_message(self, msg: dict, handler: _BridgeHandler) -> None:
        t = msg.get("type")
        if t == "tick":
            self._handle_tick(msg)
        elif t == "account":
            self._handle_account(msg)
        elif t == "position":
            self._handle_position(msg)
        elif t == "positions_end":
            self._handle_positions_end(msg)
        elif t == "ok":
            self._handle_order_reply(msg, ok=True)
        elif t == "err":
            self._handle_order_reply(msg, ok=False)
        elif t == "heartbeat":
            pass  # nothing to do
        else:
            logger.debug("unhandled msg: %s", msg)

    # ─── handlers ───────────────────────────────────────────────────────

    def _handle_account(self, msg: dict) -> None:
        try:
            self._account = AccountState(
                equity=float(msg.get("equity", 0)),
                balance=float(msg.get("balance", 0)),
                currency=msg.get("currency", "USD"),
                pnl_today=float(msg.get("pnl_today", 0)),
                pnl_week=float(msg.get("pnl_week", 0)),
            )
        except (TypeError, ValueError):
            logger.warning("bad account msg: %s", msg)

    def _handle_position(self, msg: dict) -> None:
        try:
            ticket = int(msg["ticket"])
            self._pending_positions[ticket] = Position(
                symbol=msg["symbol"],
                side=msg["side"],
                lots=float(msg["lots"]),
                entry=float(msg["entry"]),
                open_ts_ms=int(msg.get("open_ts_ms", 0)),
            )
        except (KeyError, ValueError, TypeError):
            logger.warning("bad position msg: %s", msg)

    def _handle_positions_end(self, msg: dict) -> None:
        # swap snapshot
        with self._lock:
            self._positions = self._pending_positions
            self._pending_positions = {}

    def _handle_tick(self, msg: dict) -> None:
        try:
            tick = Tick(
                symbol=msg["symbol"],
                bid=float(msg["bid"]),
                ask=float(msg["ask"]),
                ts_ms=int(msg["ts_ms"]),
            )
        except (KeyError, ValueError):
            return
        self._last_tick_per_symbol[tick.symbol] = tick

        # Strategy → intents
        intents = self._strat.on_tick(tick)
        if not intents:
            return

        for intent in intents:
            # Risk gate
            decision = self._risk.check(
                intent,
                account=self._account,
                positions=list(self._positions.values()),
                last_tick=tick,
                now_ms=tick.ts_ms,
            )
            if not decision.approved:
                logger.info("REJECT %s: %s", intent.client_order_id, decision.reason)
                continue

            # Send to EA
            sent = self._send_order(intent)
            if not sent:
                logger.warning("could not send order %s", intent.client_order_id)
                continue
            # Pre-record in journal as "submitted"
            try:
                self._journal.record_submission(
                    client_order_id=intent.client_order_id,
                    symbol=intent.symbol, side=intent.side, lots=intent.lots,
                    entry=intent.entry, stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    submitted_ts=tick.ts_ms, mode=self._mode,
                )
            except Exception as exc:
                logger.warning("journal submit failed: %s", exc)
            self._pending_orders[intent.client_order_id] = intent

    def _send_order(self, intent: OrderIntent) -> bool:
        with self._lock:
            handler = self._handler
        if handler is None:
            return False
        line = encode_pipe(
            "order",
            client_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            lots=f"{intent.lots:.2f}",
            sl=f"{intent.stop_loss or 0.0:.5f}",
            tp=f"{intent.take_profit or 0.0:.5f}",
            entry=f"{intent.entry:.5f}",
        )
        try:
            handler.send_line(line)
            return True
        except Exception as exc:
            logger.error("send_order failed: %s", exc)
            return False

    def _handle_order_reply(self, msg: dict, *, ok: bool) -> None:
        cid = msg.get("client_id", "")
        if not cid:
            return
        intent = self._pending_orders.pop(cid, None)
        if ok:
            try:
                price = float(msg.get("price", 0)) or (intent.entry if intent else 0.0)
                self._journal.record_fill(
                    client_order_id=cid,
                    fill_price=price,
                    fill_ts=int(msg.get("ts_ms", 0)) or 0,
                )
            except Exception as exc:
                logger.warning("journal fill failed: %s", exc)
            logger.info("FILL %s @ %s", cid, msg.get("price"))
        else:
            try:
                self._journal.record_reject(cid, msg.get("reason", "unknown"))
            except Exception:
                pass
            logger.warning("ORDER REJECTED %s: %s", cid, msg.get("reason"))
