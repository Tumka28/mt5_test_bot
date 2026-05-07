"""SMC advisor end-to-end (fake EA via TCP socket)."""
from __future__ import annotations

import socket
import threading
import time

import pytest

from brain.smc_advisor import SmcAdvisor
from bridge.tcp_server import BridgeTcpServer, _BridgeHandler


HOST = "127.0.0.1"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _gen_bars_payload(n: int = 80, start_price: float = 1.10) -> str:
    """200 fake bars in CSV-style ;-separated."""
    out = []
    price = start_price
    t = 1_700_000_000_000
    for i in range(n):
        change = 0.0006 if i % 3 != 0 else -0.0002
        new = price + change
        h = max(price, new) + 0.0003
        l = min(price, new) - 0.0003
        out.append(f"{t},{price:.5f},{h:.5f},{l:.5f},{new:.5f},10")
        price = new
        t += 60_000
    return ";".join(out)


class _FakeEA:
    def __init__(self, host: str, port: int):
        self._sock = socket.create_connection((host, port), timeout=3)
        self._buf = b""
        self._alive = True
        self._received: list[str] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        while self._alive:
            try:
                chunk = self._sock.recv(8192)
            except OSError:
                return
            if not chunk:
                return
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                with self._lock:
                    self._received.append(line.decode("utf-8", "replace"))

    def received(self) -> list[str]:
        with self._lock:
            return list(self._received)

    def send(self, line: str) -> None:
        self._sock.sendall((line + "\n").encode("utf-8"))

    def close(self) -> None:
        self._alive = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


@pytest.fixture
def advisor_setup():
    port = _free_port()
    advisor = SmcAdvisor(symbol="EURUSD", timeframe="M5",
                         bars_window=80, analysis_period_s=5.0)

    def on_msg(msg: dict, h: _BridgeHandler) -> None:
        advisor.on_message(msg, h)

    def on_conn(h: _BridgeHandler) -> None:
        srv.set_client(h)
        advisor.on_connect(h)

    def on_disc(h: _BridgeHandler) -> None:
        srv.set_client(None)
        advisor.on_disconnect(h)

    srv = BridgeTcpServer(
        (HOST, port),
        on_message=on_msg, on_connect=on_conn, on_disconnect=on_disc,
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield advisor, port
    srv.shutdown()
    srv.server_close()


def test_advisor_requests_bars_on_connect(advisor_setup):
    advisor, port = advisor_setup
    ea = _FakeEA(HOST, port)
    try:
        time.sleep(0.4)
        recv = ea.received()
        get_bars = [s for s in recv if s.startswith("get_bars|")]
        assert get_bars, f"expected get_bars request, got {recv[:5]}"
        assert "symbol=EURUSD" in get_bars[0]
        assert "tf=M5" in get_bars[0]
    finally:
        ea.close()


def test_advisor_draws_after_bars_reply(advisor_setup):
    advisor, port = advisor_setup
    ea = _FakeEA(HOST, port)
    try:
        # Wait for the get_bars request, capture req_id
        deadline = time.time() + 1.0
        get_bars_line: str | None = None
        while time.time() < deadline:
            for s in ea.received():
                if s.startswith("get_bars|"):
                    get_bars_line = s
                    break
            if get_bars_line:
                break
            time.sleep(0.05)
        assert get_bars_line is not None
        req_id = get_bars_line.split("req_id=", 1)[1].split("|")[0]

        # Send bars reply
        payload = _gen_bars_payload(80)
        ea.send(f"bars|req_id={req_id}|symbol=EURUSD|tf=M5|count=80|data={payload}")

        # Wait for draw commands
        deadline = time.time() + 1.5
        draw_lines: list[str] = []
        while time.time() < deadline:
            recv = ea.received()
            draw_lines = [s for s in recv if s.startswith(("draw_", "clear|"))]
            if any(s.startswith("draw_path|") for s in draw_lines):
                break
            time.sleep(0.05)

        # Should have drawn at least: clear, projection paths
        assert any(s.startswith("clear|") for s in draw_lines), \
            f"missing clear, got {draw_lines[:5]}"
        assert any(s.startswith("draw_path|") for s in draw_lines), \
            f"missing projection path, got {draw_lines[:5]}"
        # Should have drawn TP/invalidation lines
        assert any("color=" in s and s.startswith("draw_line|") for s in draw_lines)
    finally:
        ea.close()


def test_advisor_telegram_text_format(advisor_setup):
    advisor, port = advisor_setup
    ea = _FakeEA(HOST, port)
    try:
        deadline = time.time() + 1.0
        get_bars_line: str | None = None
        while time.time() < deadline:
            for s in ea.received():
                if s.startswith("get_bars|"):
                    get_bars_line = s
                    break
            if get_bars_line:
                break
            time.sleep(0.05)
        req_id = get_bars_line.split("req_id=", 1)[1].split("|")[0]
        ea.send(f"bars|req_id={req_id}|symbol=EURUSD|tf=M5|count=80|data={_gen_bars_payload(80)}")
        time.sleep(0.5)

        out = advisor._analyse_and_draw()  # noqa: SLF001 — internal peek for assertion
        if out is None:
            pytest.skip("not enough bars yet for analysis")
        text = out.telegram_text()
        assert "EURUSD M5" in text
        assert "Direction:" in text
        assert "Probability:" in text
        assert "Invalidation:" in text
    finally:
        ea.close()
