"""Prometheus metrics smoke test — counter/gauge interface OK эсэхийг шалгана.
Server listening port-той туршихгүй (CI-д порт хязгаарлагдсан байж болно)."""
from __future__ import annotations

from observability import metrics


def test_counters_inc_does_not_raise():
    metrics.TICKS_RECEIVED.labels(symbol="EURUSD").inc()
    metrics.ORDERS_SUBMITTED.labels(symbol="EURUSD", side="buy", mode="paper").inc()
    metrics.ORDERS_FILLED.labels(symbol="EURUSD", mode="paper").inc()
    metrics.ORDERS_REJECTED.labels(reason="test").inc()
    metrics.RISK_REJECTS.labels(reason="test").inc()
    metrics.HEARTBEATS_SENT.inc()
    metrics.EA_DISCONNECTS.inc()


def test_gauges_set_does_not_raise():
    metrics.EQUITY.labels(currency="USD").set(100_000)
    metrics.BALANCE.labels(currency="USD").set(100_000)
    metrics.PNL_TODAY.labels(currency="USD").set(50)
    metrics.POSITIONS_OPEN.set(3)
    metrics.EA_CONNECTED.set(1)
    metrics.KILL_SWITCH_ARMED.set(0)


def test_histogram_observe():
    metrics.ORDER_LATENCY.observe(0.123)
