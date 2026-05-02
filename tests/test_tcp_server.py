"""TCP server smoke test — fake EA connects, sends tick, gets ping reply."""
from __future__ import annotations

import socket
import threading
import time

from bridge.tcp_server import BridgeTcpServer, decode_pipe, encode_pipe


def test_encode_decode_roundtrip():
    line = encode_pipe("tick", symbol="EURUSD", bid=1.10412, ask=1.10421, ts_ms=1)
    assert line == "tick|symbol=EURUSD|bid=1.10412|ask=1.10421|ts_ms=1"
    msg = decode_pipe(line)
    assert msg == {"type": "tick", "symbol": "EURUSD",
                   "bid": "1.10412", "ask": "1.10421", "ts_ms": "1"}


def test_decode_empty():
    assert decode_pipe("") == {"type": ""}


def test_decode_skips_malformed_field():
    msg = decode_pipe("ping|garbage_no_eq|x=1")
    assert msg["type"] == "ping" and msg["x"] == "1"


def test_server_receives_and_replies():
    received: list[dict] = []

    def on_msg(msg, handler):
        received.append(msg)
        if msg["type"] == "tick":
            handler.send_line(encode_pipe("ack", id=msg.get("ts_ms", "?")))

    srv = BridgeTcpServer(("127.0.0.1", 0), on_message=on_msg)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # fake EA connects
        s = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        s.sendall(b"tick|symbol=EURUSD|bid=1.1|ask=1.10001|ts_ms=42\n")
        # read reply (server is sync from handler thread)
        s.settimeout(2.0)
        reply = s.recv(1024).decode("utf-8").strip()
        assert reply.startswith("ack|")
        s.close()
        # give the handler a moment to record
        for _ in range(20):
            if received:
                break
            time.sleep(0.05)
        assert len(received) == 1
        assert received[0]["type"] == "tick"
        assert received[0]["symbol"] == "EURUSD"
    finally:
        srv.shutdown()
