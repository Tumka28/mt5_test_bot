"""MT5 → ZMQ gateway.

Runs on Windows (where the MT5 Python package is available). Reads ticks via
the MetaTrader5 Python binding and publishes them on the PUB socket.

If the MT5 package isn't importable (e.g. running on Linux for tests), the
module still imports — `MT5Gateway.start` raises RuntimeError instead.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from bridge.transport import HeartbeatMessage, Publisher, TickMessage, now_ms

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5  # type: ignore
    _HAS_MT5 = True
except Exception:
    mt5 = None  # type: ignore
    _HAS_MT5 = False


class MT5Gateway:
    def __init__(self, *, pub_url: str, symbols: Iterable[str], heartbeat_s: int = 5):
        self._pub = Publisher(pub_url)
        self._symbols = tuple(symbols)
        self._heartbeat_s = heartbeat_s
        self._last_hb = 0.0

    def _ensure_mt5(self) -> None:
        if not _HAS_MT5:
            raise RuntimeError(
                "MetaTrader5 package not available — gateway must run on Windows "
                "with the MT5 terminal installed and signed in."
            )
        if not mt5.initialize():  # type: ignore[union-attr]
            raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")  # type: ignore[union-attr]
        for s in self._symbols:
            if not mt5.symbol_select(s, True):  # type: ignore[union-attr]
                logger.warning("symbol_select failed: %s", s)

    def start(self) -> None:
        self._ensure_mt5()
        last_seen: dict[str, int] = {s: 0 for s in self._symbols}
        logger.info("gateway started, symbols=%s", self._symbols)
        try:
            while True:
                for sym in self._symbols:
                    info = mt5.symbol_info_tick(sym)  # type: ignore[union-attr]
                    if info is None:
                        continue
                    ts_ms = int(info.time_msc)
                    if ts_ms <= last_seen[sym]:
                        continue
                    last_seen[sym] = ts_ms
                    msg = TickMessage(
                        symbol=sym, bid=float(info.bid), ask=float(info.ask),
                        ts_ms=ts_ms, volume=int(getattr(info, "volume", 0) or 0),
                    )
                    self._pub.send(msg.to_dict())

                now = time.time()
                if now - self._last_hb >= self._heartbeat_s:
                    self._pub.send(HeartbeatMessage(ts_ms=now_ms(), source="gateway").to_dict())
                    self._last_hb = now

                time.sleep(0.01)  # 10ms loop — sufficient for non-HFT
        finally:
            try:
                mt5.shutdown()  # type: ignore[union-attr]
            except Exception:
                pass
            self._pub.close()
