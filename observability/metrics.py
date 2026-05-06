"""Prometheus metrics — хэрвээ prometheus_client суусан бол идэвхжинэ.

Үгүй бол no-op stub object-ууд буцаана — production-д prometheus заавал суулгана.
Metrics-ийг scrape хийхдээ `start_http_server(port)` дуудна.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server  # type: ignore
    _HAS_PROM = True
except Exception:  # pragma: no cover
    _HAS_PROM = False

    class _Noop:
        def labels(self, *a: Any, **kw: Any) -> "_Noop":
            return self

        def inc(self, *a: Any, **kw: Any) -> None:
            return None

        def set(self, *a: Any, **kw: Any) -> None:
            return None

        def observe(self, *a: Any, **kw: Any) -> None:
            return None

    def Counter(*a: Any, **kw: Any) -> _Noop:  # type: ignore[no-redef]
        return _Noop()

    def Gauge(*a: Any, **kw: Any) -> _Noop:  # type: ignore[no-redef]
        return _Noop()

    def Histogram(*a: Any, **kw: Any) -> _Noop:  # type: ignore[no-redef]
        return _Noop()

    def start_http_server(*a: Any, **kw: Any) -> None:  # type: ignore[no-redef]
        return None


# Counters
TICKS_RECEIVED = Counter("mt5bot_ticks_received_total", "Ticks received from EA", ["symbol"])
ORDERS_SUBMITTED = Counter("mt5bot_orders_submitted_total", "Orders sent to EA", ["symbol", "side", "mode"])
ORDERS_FILLED = Counter("mt5bot_orders_filled_total", "Filled orders", ["symbol", "mode"])
ORDERS_REJECTED = Counter("mt5bot_orders_rejected_total", "Rejected orders", ["reason"])
RISK_REJECTS = Counter("mt5bot_risk_rejects_total", "Risk gate rejects", ["reason"])
EA_DISCONNECTS = Counter("mt5bot_ea_disconnects_total", "EA disconnect events")
HEARTBEATS_SENT = Counter("mt5bot_heartbeats_sent_total", "Brain→EA heartbeats sent")

# Gauges
EQUITY = Gauge("mt5bot_account_equity", "Account equity", ["currency"])
BALANCE = Gauge("mt5bot_account_balance", "Account balance", ["currency"])
PNL_TODAY = Gauge("mt5bot_pnl_today", "Today realised+floating PnL", ["currency"])
POSITIONS_OPEN = Gauge("mt5bot_positions_open", "Currently open positions")
EA_CONNECTED = Gauge("mt5bot_ea_connected", "1 if EA connected, 0 otherwise")
KILL_SWITCH_ARMED = Gauge("mt5bot_kill_switch_armed", "1 if kill switch armed")

# Histograms
ORDER_LATENCY = Histogram(
    "mt5bot_order_latency_seconds",
    "Latency between submission and fill reply",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)


def start_metrics_server(port: int) -> bool:
    """Prometheus scrape endpoint эхлүүлнэ. Амжилттай бол True."""
    if not _HAS_PROM:
        logger.warning("prometheus_client not installed — metrics endpoint disabled")
        return False
    start_http_server(port)
    logger.info("metrics endpoint up on :%d/metrics", port)
    return True
