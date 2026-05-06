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
import time
from typing import Callable

from brain.risk_manager import RiskManager
from brain.strategy_base import Strategy
from brain.types import AccountState, OrderIntent, Position, Tick
from bridge.tcp_server import _BridgeHandler, encode_pipe
from observability import metrics
from persistence.journal import Journal

logger = logging.getLogger(__name__)


# Mode → expected account_type. Brain-д EA "real"/"demo"/"contest" account_type
# илгээдэг — энэ нь mode-той зөрвөл order огт явуулахгүй (safety net).
_MODE_EXPECTED_ACCOUNT: dict[str, tuple[str, ...]] = {
    "paper":  ("demo", "contest"),
    "shadow": ("demo", "real", "contest"),
    "live":   ("real",),
}


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
        max_lots_per_order: float | None = None,
        require_account_type_match: bool = True,
        heartbeat_period_s: float = 5.0,
        expected_token: str = "",
        expected_logins: tuple[int, ...] = (),
    ) -> None:
        if mode not in _MODE_EXPECTED_ACCOUNT:
            raise ValueError(f"invalid mode: {mode!r}")
        self._strat = strategy
        self._risk = risk
        self._journal = journal
        self._mode = mode
        self._max_lots = max_lots_per_order
        self._require_acct_match = require_account_type_match
        self._heartbeat_period_s = heartbeat_period_s
        self._expected_token = expected_token
        self._expected_logins = set(expected_logins)
        self._handshake_ok = False

        # State updated by EA messages
        self._account = AccountState(equity=0.0, balance=0.0, currency="USD")
        self._account_type: str = "unknown"   # "demo" | "real" | "contest" | "unknown"
        self._positions: dict[int, Position] = {}   # ticket → Position
        self._pending_positions: dict[int, Position] = {}
        self._last_tick_per_symbol: dict[str, Tick] = {}

        # Connection / orders
        self._handler: _BridgeHandler | None = None
        self._lock = threading.Lock()
        self._pending_orders: dict[str, OrderIntent] = {}
        self._submission_ts: dict[str, float] = {}

        # Heartbeat thread
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    # ─── lifecycle ──────────────────────────────────────────────────────

    def start_heartbeat(self) -> None:
        """Brain → EA-руу үечилсэн ping явуулах thread эхлүүлнэ.

        EA-ийн `flatten_on_silence` watchdog-ыг идэвхгүй байлгахад зайлшгүй.
        EA нь ping хүлээж аваад "ok|pong=1" буцаана; brain энэ message-ийг ч
        тоохгүй ч, watchdog `g_last_brain_msg_time` reset хийгдэнэ.
        """
        if self._hb_thread is not None:
            return
        self._hb_stop.clear()
        t = threading.Thread(target=self._heartbeat_loop, daemon=True, name="brain-hb")
        self._hb_thread = t
        t.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        t = self._hb_thread
        if t is not None:
            t.join(timeout=2.0)
        self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.is_set():
            with self._lock:
                handler = self._handler
            if handler is not None:
                try:
                    handler.send_line(encode_pipe("ping"))
                    metrics.HEARTBEATS_SENT.inc()
                except Exception as exc:
                    logger.warning("heartbeat send failed: %s", exc)
            self._hb_stop.wait(self._heartbeat_period_s)

    # ─── EA-side hooks (called from TCP handler thread) ─────────────────

    def on_connect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            self._handler = handler
            stale = list(self._pending_orders.keys())
            self._pending_orders.clear()
            self._submission_ts.clear()
            self._positions.clear()
            self._pending_positions.clear()
            self._handshake_ok = False
        for cid in stale:
            try:
                self._journal.record_reject(cid, "ea_disconnected_before_reply")
            except Exception:
                pass
        metrics.EA_CONNECTED.set(1)
        logger.info("trading service: EA registered (cleared %d stale pending orders)", len(stale))

    def on_disconnect(self, handler: _BridgeHandler) -> None:
        with self._lock:
            if self._handler is handler:
                self._handler = None
        metrics.EA_CONNECTED.set(0)
        metrics.EA_DISCONNECTS.inc()
        logger.info("trading service: EA gone")

    def on_message(self, msg: dict, handler: _BridgeHandler) -> None:
        t = msg.get("type")
        if t == "hello":
            self._handle_hello(msg, handler)
        elif t == "tick":
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

    def _handle_hello(self, msg: dict, handler: _BridgeHandler) -> None:
        token = (msg.get("token") or "").strip()
        acct_type = (msg.get("account_type") or "").strip().lower()
        try:
            login = int(msg.get("login", 0))
        except (TypeError, ValueError):
            login = 0
        server = (msg.get("server") or "").strip()

        if self._expected_token and token != self._expected_token:
            self._handshake_ok = False
            self._risk.kill_switch.arm("hello_token_mismatch")
            metrics.KILL_SWITCH_ARMED.set(1)
            logger.error("HANDSHAKE REJECTED: token mismatch (login=%s server=%s)", login, server)
            try:
                handler.send_line(encode_pipe("err", reason="token_mismatch"))
            except Exception:
                pass
            return

        if self._expected_logins and login not in self._expected_logins:
            self._handshake_ok = False
            self._risk.kill_switch.arm(f"unauthorised_login:{login}")
            metrics.KILL_SWITCH_ARMED.set(1)
            logger.error("HANDSHAKE REJECTED: login %s not in allow-list", login)
            return

        if acct_type in ("demo", "real", "contest"):
            self._account_type = acct_type
        if self._require_acct_match and self._account_type != "unknown":
            allowed = _MODE_EXPECTED_ACCOUNT[self._mode]
            if self._account_type not in allowed:
                self._handshake_ok = False
                self._risk.kill_switch.arm(
                    f"account_type_mismatch_at_hello:{self._account_type}_in_mode_{self._mode}",
                )
                metrics.KILL_SWITCH_ARMED.set(1)
                logger.error(
                    "HANDSHAKE REJECTED: %s account in mode=%s (login=%s server=%s)",
                    self._account_type, self._mode, login, server,
                )
                return

        self._handshake_ok = True
        logger.info(
            "HANDSHAKE OK: account_type=%s login=%s server=%s mode=%s",
            self._account_type, login, server, self._mode,
        )

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
            acct_type = (msg.get("account_type") or "").strip().lower()
            if acct_type in ("demo", "real", "contest"):
                self._account_type = acct_type
        except (TypeError, ValueError):
            logger.warning("bad account msg: %s", msg)
            return
        # metrics
        metrics.EQUITY.labels(currency=self._account.currency).set(self._account.equity)
        metrics.BALANCE.labels(currency=self._account.currency).set(self._account.balance)
        metrics.PNL_TODAY.labels(currency=self._account.currency).set(self._account.pnl_today)
        metrics.KILL_SWITCH_ARMED.set(1 if self._risk.kill_switch.is_armed() else 0)

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
        with self._lock:
            self._positions = self._pending_positions
            self._pending_positions = {}
        metrics.POSITIONS_OPEN.set(len(self._positions))

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
        metrics.TICKS_RECEIVED.labels(symbol=tick.symbol).inc()

        # Handshake gate — token/login/account_type шалгалт өнгөрөөгүй бол
        # ямар ч intent strategy-аас явахгүй. (Backwards-compat: эх expected
        # token/logins тохируулаагүй бол _handshake_ok нь зөвхөн hello
        # ирэхэд true болдог. Тестүүдэд hello мэдэгдэлгүй ажилладаг тул
        # _expected_token/_expected_logins хоосон үед энэ gate-ыг алгасна.)
        strict_handshake = bool(self._expected_token or self._expected_logins)
        if strict_handshake and not self._handshake_ok:
            return

        # Equity gate — account snapshot ирээгүй байхад ямар ч order гаргахгүй.
        if self._account.equity <= 0:
            return

        # Account type sanity — paper mode-д real account зөрвөл хатуу татгалз.
        if self._require_acct_match and self._account_type != "unknown":
            allowed = _MODE_EXPECTED_ACCOUNT[self._mode]
            if self._account_type not in allowed:
                self._risk.kill_switch.arm(
                    f"account_type_mismatch:{self._account_type}_in_mode_{self._mode}",
                )
                metrics.KILL_SWITCH_ARMED.set(1)
                return

        intents = self._strat.on_tick(tick)
        if not intents:
            return

        for intent in intents:
            # Mode-aware safety cap — live mode-д max-lot хатуулна
            if self._max_lots is not None and intent.lots > self._max_lots:
                logger.warning("ORDER CAPPED %s: lots %.2f > max %.2f",
                               intent.client_order_id, intent.lots, self._max_lots)
                metrics.ORDERS_REJECTED.labels(reason="lots_over_mode_cap").inc()
                continue

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
                metrics.RISK_REJECTS.labels(reason=decision.reason).inc()
                continue

            sent = self._send_order(intent)
            if not sent:
                logger.warning("could not send order %s", intent.client_order_id)
                metrics.ORDERS_REJECTED.labels(reason="send_failed").inc()
                continue
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
            self._submission_ts[intent.client_order_id] = time.time()
            metrics.ORDERS_SUBMITTED.labels(
                symbol=intent.symbol, side=intent.side, mode=self._mode,
            ).inc()

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
        sub_ts = self._submission_ts.pop(cid, None)
        if sub_ts is not None:
            metrics.ORDER_LATENCY.observe(max(0.0, time.time() - sub_ts))
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
            sym = intent.symbol if intent else "unknown"
            metrics.ORDERS_FILLED.labels(symbol=sym, mode=self._mode).inc()
            logger.info("FILL %s @ %s", cid, msg.get("price"))
        else:
            try:
                self._journal.record_reject(cid, msg.get("reason", "unknown"))
            except Exception:
                pass
            metrics.ORDERS_REJECTED.labels(reason=str(msg.get("reason", "unknown"))).inc()
            logger.warning("ORDER REJECTED %s: %s", cid, msg.get("reason"))
