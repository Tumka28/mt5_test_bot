"""End-to-end smoke test — fake EA TCP client ↔ real Brain (TradingService).

EA-ийн оронд Python тал дээр TCP client socket нээж, bridge_ea.mq5-ийн илгээдэг
яг тэр line-уудыг (hello, account, tick, positions_end, ok/err) илгээнэ.
Brain нь жинхэнэ TradingService — handshake шалгалт, equity gate, strategy,
risk manager, journal — бүгд run хийгдэнэ.

Зорилго: scripts/run_trading.py-ийн wiring + EA wire format-ыг батлах.
"""
from __future__ import annotations

import math
import socket
import threading
import time
from pathlib import Path

import pytest

from brain.risk_manager import RiskManager
from brain.strategies.ema_cross import EmaCrossStrategy
from brain.trading_service import TradingService
from brain.types import RiskConfig, SymbolMeta
from bridge.tcp_server import BridgeTcpServer, _BridgeHandler
from persistence.journal import Journal


SYMBOLS = {"EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS")}
CLUSTERS = {"USD_MAJORS": ["EURUSD"]}
HOST = "127.0.0.1"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _FakeEA:
    """Minimal TCP client that mimics bridge_ea.mq5 wire format."""

    def __init__(self, host: str, port: int):
        self._sock = socket.create_connection((host, port), timeout=3)
        self._buf = b""
        self._reader_alive = True
        self._received: list[str] = []
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _reader(self) -> None:
        while self._reader_alive:
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                with self._lock:
                    self._received.append(line.decode("utf-8", errors="replace"))

    def received(self) -> list[str]:
        with self._lock:
            return list(self._received)

    def send(self, line: str) -> None:
        self._sock.sendall((line + "\n").encode("utf-8"))

    def close(self) -> None:
        self._reader_alive = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


@pytest.fixture
def brain_setup(tmp_path: Path):
    port = _free_port()
    risk = RiskManager(
        config=RiskConfig(min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS,
    )
    strat = EmaCrossStrategy(fast_period=3, slow_period=10, lots=0.01)
    journal = Journal(tmp_path / "j.sqlite")
    svc = TradingService(
        strategy=strat, risk=risk, journal=journal, mode="paper",
        heartbeat_period_s=0.05,
    )

    def on_msg(msg: dict, h: _BridgeHandler) -> None:
        svc.on_message(msg, h)

    def on_conn(h: _BridgeHandler) -> None:
        srv.set_client(h)
        svc.on_connect(h)

    def on_disc(h: _BridgeHandler) -> None:
        srv.set_client(None)
        svc.on_disconnect(h)

    srv = BridgeTcpServer(
        (HOST, port),
        on_message=on_msg, on_connect=on_conn, on_disconnect=on_disc,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    svc.start_heartbeat()

    yield svc, srv, port

    svc.stop_heartbeat()
    srv.shutdown()
    srv.server_close()


def test_e2e_handshake_account_tick_order(brain_setup):
    svc, _, port = brain_setup
    ea = _FakeEA(HOST, port)
    try:
        # 1. Hello (demo account)
        ea.send("hello|account_type=demo|login=12345|server=Demo-1|build=4500|token=")
        # 2. Account snapshot
        ea.send("account|equity=100000.00|balance=100000.00|currency=USD"
                "|pnl_today=0.00|account_type=demo|login=12345|server=Demo-1|ts_ms=1")
        # 3. Empty positions snapshot
        ea.send("positions_end|count=0|ts_ms=2")

        # 4. Tick stream — bearish then bullish flip → buy signal
        for i in range(100):
            mid = 1.1000 - i * 0.0001
            ea.send(f"tick|symbol=EURUSD|bid={mid - 5e-5:.5f}|ask={mid + 5e-5:.5f}"
                    f"|ts_ms={i + 100}|volume=1")
        for i in range(100, 250):
            mid = 1.0900 + (i - 100) * 0.0003
            ea.send(f"tick|symbol=EURUSD|bid={mid - 5e-5:.5f}|ask={mid + 5e-5:.5f}"
                    f"|ts_ms={i + 100}|volume=1")

        # 5. Wait for order line to come back
        deadline = time.time() + 3.0
        order_line: str | None = None
        while time.time() < deadline:
            for line in ea.received():
                if line.startswith("order|"):
                    order_line = line
                    break
            if order_line is not None:
                break
            time.sleep(0.05)

        assert order_line is not None, f"no order received. recv={ea.received()[:10]}"
        assert "client_id=" in order_line
        assert "symbol=EURUSD" in order_line
        assert "sl=" in order_line and "tp=" in order_line

        # 6. Reply with fill
        cid = order_line.split("client_id=", 1)[1].split("|")[0]
        ea.send(f"ok|ticket=987654|price=1.09010|client_id={cid}")
        time.sleep(0.2)

        # 7. Verify journal has filled order
        import sqlite3
        with sqlite3.connect(svc._journal._path) as conn:
            row = conn.execute(
                "SELECT status, fill_price FROM orders WHERE client_order_id=?", (cid,)
            ).fetchone()
        assert row is not None
        assert row[0] == "filled"
    finally:
        ea.close()


def test_e2e_heartbeat_pings_arrive(brain_setup):
    """Brain heartbeat thread → fake EA-руу `ping` 50ms тутамд явсан байх ёстой."""
    _, _, port = brain_setup
    ea = _FakeEA(HOST, port)
    try:
        time.sleep(0.3)
        pings = [s for s in ea.received() if s.startswith("ping")]
        assert len(pings) >= 2, f"expected ≥2 pings, got {pings}"
    finally:
        ea.close()


def test_e2e_real_account_in_paper_mode_arms_kill(brain_setup):
    svc, _, port = brain_setup
    ea = _FakeEA(HOST, port)
    try:
        ea.send("hello|account_type=real|login=12345|server=Live-1|build=4500|token=")
        time.sleep(0.2)
        assert svc._risk.kill_switch.is_armed()
    finally:
        ea.close()


def test_e2e_reconnect_clears_pending(brain_setup):
    """EA disconnect/connect-д stale pending orders цэвэрлэгдсэн байх ёстой."""
    svc, _, port = brain_setup

    # First connection — leave a pending order in the dict directly
    ea1 = _FakeEA(HOST, port)
    try:
        time.sleep(0.1)
        from brain.types import OrderIntent
        svc._pending_orders["stale-1"] = OrderIntent(
            client_order_id="stale-1", symbol="EURUSD", side="buy",
            lots=0.01, entry=1.10, stop_loss=1.09,
        )
    finally:
        ea1.close()

    time.sleep(0.2)

    # Second connection
    ea2 = _FakeEA(HOST, port)
    try:
        time.sleep(0.2)
        assert "stale-1" not in svc._pending_orders
    finally:
        ea2.close()
