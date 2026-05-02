"""TCP server — Python brain side.

EA нь TCP CLIENT, энэ нь TCP SERVER. Wire format pipe-delimited line:
    in (EA → brain):
       tick|symbol=EURUSD|bid=1.10412|ask=1.10421|ts_ms=...|volume=...
       heartbeat|ts_ms=...|source=gateway
       ok|ticket=...|price=...      (order reply)
       err|reason=...               (order reply)
    out (brain → EA):
       order|client_id=...|symbol=EURUSD|side=buy|lots=0.10|sl=1.0950|tp=1.1100
       flatten_all
       ping

EA-аас ирсэн tick-ийг ConnectionHandler-ийн `on_message` callback дамжуулна.
Order/RPC-г илгээхийн тулд `send_line(...)` гэж дуудна.
"""
from __future__ import annotations

import logging
import socket
import socketserver
import threading
from typing import Callable

logger = logging.getLogger(__name__)


def encode_pipe(mtype: str, **fields) -> str:
    parts = [mtype]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    return "|".join(parts)


def decode_pipe(line: str) -> dict:
    parts = line.split("|")
    if not parts:
        return {}
    out = {"type": parts[0]}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = v
    return out


class _BridgeHandler(socketserver.StreamRequestHandler):
    """One handler per connected EA. We expect at most one EA at a time."""

    def handle(self) -> None:
        server: BridgeTcpServer = self.server  # type: ignore[assignment]
        peer = self.client_address
        logger.info("EA connected: %s", peer)
        server._on_connect(self)
        try:
            buf = b""
            while True:
                chunk = self.rfile.readline()
                if not chunk:
                    break
                line = chunk.rstrip(b"\r\n").decode("utf-8", errors="replace")
                if not line:
                    continue
                msg = decode_pipe(line)
                try:
                    server._on_message(msg, self)
                except Exception:
                    logger.exception("on_message handler crashed")
        except (ConnectionResetError, OSError) as exc:
            logger.warning("EA disconnected: %s (%s)", peer, exc)
        finally:
            server._on_disconnect(self)
            logger.info("EA gone: %s", peer)

    def send_line(self, line: str) -> None:
        try:
            self.wfile.write((line + "\n").encode("utf-8"))
            self.wfile.flush()
        except OSError as exc:
            logger.warning("send_line failed: %s", exc)


class BridgeTcpServer(socketserver.ThreadingTCPServer):
    """TCP server with one-line-per-message protocol.

    Usage:
        srv = BridgeTcpServer(("127.0.0.1", 5555),
                              on_message=my_handler,
                              on_connect=lambda h: print("connected"))
        srv.serve_forever()
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        on_message: Callable[[dict, _BridgeHandler], None],
        on_connect: Callable[[_BridgeHandler], None] | None = None,
        on_disconnect: Callable[[_BridgeHandler], None] | None = None,
    ) -> None:
        super().__init__(address, _BridgeHandler)
        self._on_message = on_message
        self._on_connect = on_connect or (lambda h: None)
        self._on_disconnect = on_disconnect or (lambda h: None)
        self._lock = threading.Lock()
        self._client: _BridgeHandler | None = None

    # The handler thread may register itself; main thread reads via this prop.
    def set_client(self, h: _BridgeHandler | None) -> None:
        with self._lock:
            self._client = h

    def get_client(self) -> _BridgeHandler | None:
        with self._lock:
            return self._client

    def send_to_ea(self, line: str) -> bool:
        h = self.get_client()
        if h is None:
            return False
        h.send_line(line)
        return True
