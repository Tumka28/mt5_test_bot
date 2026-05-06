"""Production-readiness тестүүд:
  - hello handshake (token, login, account_type)
  - reconnect reconcile (pending orders cleared)
  - per-mode max-lots cap
  - account_type mismatch arms kill switch
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.trading_service import TradingService
from brain.types import OrderIntent, RiskConfig, SymbolMeta
from persistence.journal import Journal


SYMBOLS = {"EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS")}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}


def _make(tmp_path: Path, **kw) -> tuple[TradingService, MagicMock]:
    risk = RiskManager(
        config=RiskConfig(min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    strat = EmaCrossStrategy(fast_period=3, slow_period=10, lots=0.01)
    journal = Journal(tmp_path / "j.sqlite")
    svc = TradingService(strategy=strat, risk=risk, journal=journal, mode="paper", **kw)
    handler = MagicMock()
    svc.on_connect(handler)
    return svc, handler


# ─── handshake ──────────────────────────────────────────────────────


def test_handshake_token_mismatch_arms_kill(tmp_path):
    svc, h = _make(tmp_path, expected_token="secret-abc")
    svc.on_message({"type": "hello", "token": "wrong", "account_type": "demo",
                    "login": "100", "server": "Demo-1"}, h)
    assert svc._risk.kill_switch.is_armed()
    assert not svc._handshake_ok


def test_handshake_login_not_in_allowlist_arms_kill(tmp_path):
    svc, h = _make(tmp_path, expected_logins=(111, 222))
    svc.on_message({"type": "hello", "token": "", "account_type": "demo",
                    "login": "999", "server": "Demo-1"}, h)
    assert svc._risk.kill_switch.is_armed()
    assert not svc._handshake_ok


def test_handshake_real_account_in_paper_mode_arms_kill(tmp_path):
    svc, h = _make(tmp_path)  # mode=paper default
    svc.on_message({"type": "hello", "token": "", "account_type": "real",
                    "login": "100", "server": "Live-1"}, h)
    assert svc._risk.kill_switch.is_armed()
    assert not svc._handshake_ok


def test_handshake_demo_in_paper_mode_ok(tmp_path):
    svc, h = _make(tmp_path)
    svc.on_message({"type": "hello", "token": "", "account_type": "demo",
                    "login": "100", "server": "Demo-1"}, h)
    assert not svc._risk.kill_switch.is_armed()
    assert svc._handshake_ok


def test_strict_handshake_blocks_orders_until_hello(tmp_path):
    svc, h = _make(tmp_path, expected_token="abc")
    # Account мэдэгдсэн ч handshake байхгүй тул order гарахгүй
    svc.on_message({"type": "account", "equity": "100000", "balance": "100000",
                    "currency": "USD", "pnl_today": "0", "account_type": "demo"}, h)
    svc.on_message({"type": "positions_end", "count": "0", "ts_ms": "0"}, h)
    import math
    for i in range(250):
        mid = 1.10 + (0.01 if i > 100 else -0.01) * (i / 100)
        svc.on_message({"type": "tick", "symbol": "EURUSD",
                        "bid": str(mid - 5e-5), "ask": str(mid + 5e-5),
                        "ts_ms": str(i)}, h)
    sent = [c[0][0] for c in h.send_line.call_args_list]
    assert not any(s.startswith("order|") for s in sent)


# ─── reconnect reconcile ────────────────────────────────────────────


def test_reconnect_clears_pending_orders(tmp_path):
    svc, h = _make(tmp_path)
    svc._pending_orders["o1"] = OrderIntent(
        client_order_id="o1", symbol="EURUSD", side="buy", lots=0.01,
        entry=1.10, stop_loss=1.09,
    )
    svc._submission_ts["o1"] = time.time()
    svc._positions[42] = MagicMock()  # stale
    new_handler = MagicMock()
    svc.on_disconnect(h)
    svc.on_connect(new_handler)
    assert svc._pending_orders == {}
    assert svc._positions == {}
    assert svc._submission_ts == {}


# ─── max-lots cap ───────────────────────────────────────────────────


def test_max_lots_cap_blocks_oversized(tmp_path):
    svc, h = _make(tmp_path, max_lots_per_order=0.05)
    # Account snapshot
    svc.on_message({"type": "account", "equity": "1000000", "balance": "1000000",
                    "currency": "USD", "pnl_today": "0", "account_type": "demo"}, h)
    svc.on_message({"type": "positions_end", "count": "0", "ts_ms": "0"}, h)
    # Inject intent directly via strategy mock
    svc._strat = MagicMock()
    svc._strat.on_tick.return_value = [
        OrderIntent(client_order_id="big", symbol="EURUSD", side="buy",
                    lots=0.50, entry=1.10, stop_loss=1.09, take_profit=1.11),
    ]
    svc.on_message({"type": "tick", "symbol": "EURUSD",
                    "bid": "1.0999", "ask": "1.1001", "ts_ms": "1"}, h)
    sent = [c[0][0] for c in h.send_line.call_args_list]
    assert not any(s.startswith("order|") for s in sent)


# ─── invalid mode ──────────────────────────────────────────────────


def test_invalid_mode_rejected(tmp_path):
    risk = RiskManager(
        config=RiskConfig(), symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    strat = EmaCrossStrategy(fast_period=3, slow_period=10, lots=0.01)
    journal = Journal(tmp_path / "j.sqlite")
    import pytest
    with pytest.raises(ValueError):
        TradingService(strategy=strat, risk=risk, journal=journal, mode="invalid")


# ─── heartbeat ──────────────────────────────────────────────────────


def test_heartbeat_sends_ping(tmp_path):
    svc, h = _make(tmp_path)
    svc._heartbeat_period_s = 0.05
    svc.start_heartbeat()
    time.sleep(0.18)
    svc.stop_heartbeat()
    sent = [c[0][0] for c in h.send_line.call_args_list]
    pings = [s for s in sent if s.startswith("ping")]
    assert len(pings) >= 2  # дор хаяж 2 ping явсан байх ёстой


def test_account_type_mismatch_during_runtime_arms_kill(tmp_path):
    svc, h = _make(tmp_path)
    # Эхлээд demo гэж handshake амжилттай
    svc.on_message({"type": "hello", "token": "", "account_type": "demo",
                    "login": "100", "server": "Demo-1"}, h)
    assert not svc._risk.kill_switch.is_armed()
    # Гэнэт runtime-д account_type real-руу солигдов (хортой broker switch?)
    svc.on_message({"type": "account", "equity": "100000", "balance": "100000",
                    "currency": "USD", "pnl_today": "0", "account_type": "real"}, h)
    svc.on_message({"type": "positions_end", "count": "0", "ts_ms": "0"}, h)
    # Tick ирэхэд kill switch arm болох
    svc.on_message({"type": "tick", "symbol": "EURUSD", "bid": "1.10",
                    "ask": "1.10001", "ts_ms": "1"}, h)
    assert svc._risk.kill_switch.is_armed()
