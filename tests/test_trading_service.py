"""TradingService end-to-end test — fake EA messages drive strategy + risk +
fake handler captures order lines. Бодит pipeline ажиллаж байгааг батална."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.trading_service import TradingService
from brain.types import RiskConfig, SymbolMeta
from persistence.journal import Journal


SYMBOLS = {"EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS")}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}


def _make_service(tmp_path: Path) -> tuple[TradingService, MagicMock]:
    risk = RiskManager(
        config=RiskConfig(min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    strat = EmaCrossStrategy(fast_period=3, slow_period=10, lots=0.01)
    journal = Journal(tmp_path / "j.sqlite")
    svc = TradingService(strategy=strat, risk=risk, journal=journal, mode="paper")
    handler = MagicMock()
    svc.on_connect(handler)
    return svc, handler


def test_account_message_updates_state(tmp_path):
    svc, _ = _make_service(tmp_path)
    svc.on_message({"type": "account", "equity": "100000", "balance": "100000",
                    "currency": "USD", "pnl_today": "0", "pnl_week": "0"}, MagicMock())
    assert svc._account.equity == 100_000
    assert svc._account.currency == "USD"


def test_positions_snapshot_replaces_state(tmp_path):
    svc, _ = _make_service(tmp_path)
    # First snapshot: 2 positions
    svc.on_message({"type": "position", "ticket": "1", "symbol": "EURUSD",
                    "side": "buy", "lots": "0.10", "entry": "1.10",
                    "sl": "1.09", "tp": "1.11", "open_ts_ms": "0"}, MagicMock())
    svc.on_message({"type": "position", "ticket": "2", "symbol": "EURUSD",
                    "side": "sell", "lots": "0.05", "entry": "1.11",
                    "sl": "1.12", "tp": "1.10", "open_ts_ms": "0"}, MagicMock())
    svc.on_message({"type": "positions_end", "count": "2", "ts_ms": "0"}, MagicMock())
    assert len(svc._positions) == 2
    # Second snapshot: 0 positions (simulating all closed)
    svc.on_message({"type": "positions_end", "count": "0", "ts_ms": "1"}, MagicMock())
    assert len(svc._positions) == 0


def test_tick_no_account_no_orders_sent(tmp_path):
    """Risk Manager-д equity 0 байвал per-trade risk шалгалт амжилтгүй —
    ямар ч intent fail хийх ёстой."""
    svc, handler = _make_service(tmp_path)
    # account never sent → equity=0, so per-trade risk cap = $0
    # Send enough ticks to provoke a signal, but all intents should be rejected
    import math
    for i in range(120):
        mid = 1.10 + 0.001 * math.sin(i / 7)
        svc.on_message({"type": "tick", "symbol": "EURUSD",
                        "bid": str(mid - 5e-5), "ask": str(mid + 5e-5),
                        "ts_ms": str(i)}, handler)
    # No order lines should have been sent
    sent_lines = [c[0][0] for c in handler.send_line.call_args_list]
    order_lines = [s for s in sent_lines if s.startswith("order|")]
    assert order_lines == [], f"unexpected orders: {order_lines}"


def test_order_reply_records_fill(tmp_path):
    svc, handler = _make_service(tmp_path)
    # Pretend we sent an order
    from brain.types import OrderIntent
    intent = OrderIntent(
        client_order_id="o1", symbol="EURUSD", side="buy", lots=0.01,
        entry=1.10, stop_loss=1.09, take_profit=1.11,
    )
    svc._pending_orders["o1"] = intent
    svc._journal.record_submission(
        client_order_id="o1", symbol="EURUSD", side="buy", lots=0.01,
        entry=1.10, stop_loss=1.09, take_profit=1.11,
        submitted_ts=1, mode="paper",
    )
    svc.on_message({"type": "ok", "client_id": "o1", "ticket": "9999",
                    "price": "1.10001"}, MagicMock())
    assert svc._pending_orders == {}
    # journal fill recorded
    import sqlite3
    with sqlite3.connect(svc._journal._path) as conn:
        row = conn.execute(
            "SELECT status, fill_price FROM orders WHERE client_order_id='o1'"
        ).fetchone()
    assert row[0] == "filled"
    assert abs(row[1] - 1.10001) < 1e-9


def test_order_reply_err_records_reject(tmp_path):
    svc, handler = _make_service(tmp_path)
    from brain.types import OrderIntent
    intent = OrderIntent(
        client_order_id="o2", symbol="EURUSD", side="buy", lots=0.01,
        entry=1.10, stop_loss=1.09, take_profit=1.11,
    )
    svc._pending_orders["o2"] = intent
    svc._journal.record_submission(
        client_order_id="o2", symbol="EURUSD", side="buy", lots=0.01,
        entry=1.10, stop_loss=1.09, take_profit=1.11,
        submitted_ts=1, mode="paper",
    )
    svc.on_message({"type": "err", "client_id": "o2",
                    "reason": "trade_failed"}, MagicMock())
    import sqlite3
    with sqlite3.connect(svc._journal._path) as conn:
        row = conn.execute(
            "SELECT status, reject_reason FROM orders WHERE client_order_id='o2'"
        ).fetchone()
    assert row[0] == "rejected"
    assert row[1] == "trade_failed"


def test_full_pipeline_with_account_produces_order(tmp_path):
    svc, handler = _make_service(tmp_path)
    # Provide account so risk doesn't reject
    svc.on_message({"type": "account", "equity": "100000", "balance": "100000",
                    "currency": "USD", "pnl_today": "0", "pnl_week": "0"}, MagicMock())
    # Empty positions
    svc.on_message({"type": "positions_end", "count": "0", "ts_ms": "0"}, MagicMock())
    # Drive ticks: bearish setup then bullish flip → buy signal
    for i in range(100):
        mid = 1.1000 - i * 0.0001
        svc.on_message({"type": "tick", "symbol": "EURUSD",
                        "bid": str(mid - 5e-5), "ask": str(mid + 5e-5),
                        "ts_ms": str(i)}, handler)
    for i in range(100, 250):
        mid = 1.0900 + (i - 100) * 0.0003
        svc.on_message({"type": "tick", "symbol": "EURUSD",
                        "bid": str(mid - 5e-5), "ask": str(mid + 5e-5),
                        "ts_ms": str(i)}, handler)
    # At least one order line should have been sent
    sent_lines = [c[0][0] for c in handler.send_line.call_args_list]
    order_lines = [s for s in sent_lines if s.startswith("order|")]
    assert len(order_lines) >= 1, f"expected at least 1 order, got 0. sent={sent_lines[:5]}"
    # Format check
    assert "client_id=" in order_lines[0]
    assert "side=" in order_lines[0]
