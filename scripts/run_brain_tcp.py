"""Run a minimal brain that listens for the EA on TCP.

Эхлээд listen-д ор → EA chart-д тохиргоо хийсний дараа холбогдоно.
Бүх tick-ийг console-д хэвлэнэ. Ctrl+C-ээр зогсооно.

    python scripts/run_brain_tcp.py
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bridge.tcp_server import BridgeTcpServer, _BridgeHandler, encode_pipe
from observability.logger import configure


HOST = "127.0.0.1"
PORT = 5555


def main() -> int:
    configure(level="INFO", json=False)
    log = logging.getLogger("brain")

    state = {"ticks": 0, "heartbeats": 0, "last_print": 0.0}

    def on_message(msg: dict, handler: _BridgeHandler) -> None:
        t = msg.get("type")
        if t == "tick":
            state["ticks"] += 1
            now = time.time()
            if now - state["last_print"] >= 1.0:
                log.info("tick %s bid=%s ask=%s ts_ms=%s  (total ticks=%d)",
                         msg.get("symbol"), msg.get("bid"), msg.get("ask"),
                         msg.get("ts_ms"), state["ticks"])
                state["last_print"] = now
        elif t == "heartbeat":
            state["heartbeats"] += 1
            log.info("heartbeat from %s (total hb=%d, ticks=%d)",
                     msg.get("source"), state["heartbeats"], state["ticks"])
        else:
            log.info("msg: %s", msg)

    def on_connect(h: _BridgeHandler) -> None:
        srv.set_client(h)
        log.info("EA registered as active client")
        # ping the EA to validate the bidirectional channel
        h.send_line(encode_pipe("ping"))

    def on_disconnect(h: _BridgeHandler) -> None:
        srv.set_client(None)

    srv = BridgeTcpServer(
        (HOST, PORT),
        on_message=on_message,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )
    log.info("brain listening on %s:%d  (waiting for EA to connect)", HOST, PORT)
    log.info("press Ctrl+C to stop")

    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("shutting down ...")
        srv.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
