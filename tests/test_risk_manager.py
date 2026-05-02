"""Risk Manager — hard gate тестүүд.

Стратеги ямар ч bug гаргасан энд дамжсан order *хэзээ ч* config-ийн
хязгаарыг давах ёсгүй. Энэ тестүүд live deploy-ын өмнөх минимум баталгаа.
"""
from __future__ import annotations

import pytest

from brain.risk_manager import KillSwitch, NewsCalendar, RiskManager
from brain.types import (
    AccountState,
    OrderIntent,
    Position,
    RiskConfig,
    SymbolMeta,
    Tick,
)


SYMBOLS = {
    "EURUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS"),
    "GBPUSD": SymbolMeta(100_000, 0.01, 0.01, 10.0, "USD_MAJORS"),
    "XAUUSD": SymbolMeta(100,     0.01, 0.01, 1.0,  "METALS"),
}
CLUSTERS = {
    "USD_MAJORS": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"],
    "METALS": ["XAUUSD", "XAGUSD"],
}


def make_rm(cfg: RiskConfig | None = None) -> RiskManager:
    return RiskManager(
        config=cfg or RiskConfig(),
        symbols=SYMBOLS,
        cluster_members=CLUSTERS,
    )


def acct(equity: float = 100_000, **kw) -> AccountState:
    return AccountState(equity=equity, balance=equity, **kw)


def tick(symbol: str = "EURUSD", mid: float = 1.1000) -> Tick:
    return Tick(symbol=symbol, bid=mid - 0.00005, ask=mid + 0.00005, ts_ms=1700000000000)


def intent(
    *, oid: str = "o1", side: str = "buy", lots: float = 0.10,
    entry: float = 1.1000, sl: float | None = 1.0950,
) -> OrderIntent:
    return OrderIntent(
        client_order_id=oid, symbol="EURUSD", side=side, lots=lots,
        entry=entry, stop_loss=sl,
    )


# ─── kill switch ──────────────────────────────────────────────────────────

def test_kill_switch_blocks_all():
    rm = make_rm()
    rm.kill_switch.arm("manual")
    d = rm.check(intent(), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason == "kill_switch_armed"


# ─── stop-loss requirement ────────────────────────────────────────────────

def test_no_stop_loss_rejects():
    rm = make_rm()
    d = rm.check(intent(sl=None), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason == "no_stop_loss"


# ─── per-trade risk ───────────────────────────────────────────────────────

def test_trade_risk_within_cap_approves():
    rm = make_rm()
    # 0.10 lot × 50 pip × 100k = $50 risk on $100k acct = 0.05% — well under 0.5% cap
    d = rm.check(
        intent(lots=0.10, entry=1.1000, sl=1.0950),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert d.approved, d.reason


def test_trade_risk_over_cap_rejects():
    rm = make_rm()
    # 5.0 lots × 50 pip = $2500 risk on $100k = 2.5% — over 0.5% cap
    d = rm.check(
        intent(lots=5.0, entry=1.1000, sl=1.0950),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert not d.approved
    assert d.reason.startswith("trade_risk_")


def test_zero_stop_distance_rejects():
    rm = make_rm()
    d = rm.check(
        intent(entry=1.1000, sl=1.1000),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "zero_stop_distance"


# ─── daily / weekly loss ──────────────────────────────────────────────────

def test_daily_loss_breach_arms_kill():
    rm = make_rm()
    a = acct()
    a.pnl_today = -3500  # 3.5% on $100k
    d = rm.check(intent(), account=a, positions=[], last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason == "daily_loss_breached"
    d2 = rm.check(intent(oid="o2"), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert d2.reason == "kill_switch_armed"


def test_weekly_loss_breach_rejects_without_kill():
    rm = make_rm()
    a = acct()
    a.pnl_week = -7000  # 7% on $100k — over 6% cap
    d = rm.check(intent(), account=a, positions=[], last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason == "weekly_loss_breached"
    assert not rm.kill_switch.is_armed()


# ─── position count ───────────────────────────────────────────────────────

def test_max_positions_rejects():
    rm = make_rm()
    pos = [
        Position(symbol="EURUSD", side="buy", lots=0.1, entry=1.1, open_ts_ms=0),
        Position(symbol="GBPUSD", side="buy", lots=0.1, entry=1.3, open_ts_ms=0),
        Position(symbol="XAUUSD", side="buy", lots=0.1, entry=2000, open_ts_ms=0),
    ]
    d = rm.check(intent(oid="o4"), account=acct(), positions=pos, last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason == "max_open_positions"


# ─── correlation cluster ──────────────────────────────────────────────────

def test_correlation_cluster_cap_rejects():
    rm = make_rm(RiskConfig(max_correlation_cluster_lots=1.0, min_seconds_between_orders=0))
    pos = [
        Position(symbol="EURUSD", side="buy", lots=0.5, entry=1.1, open_ts_ms=0),
        Position(symbol="GBPUSD", side="buy", lots=0.4, entry=1.3, open_ts_ms=0),
    ]
    # 0.5 + 0.4 + 0.2 (new) = 1.1 > 1.0
    d = rm.check(
        intent(oid="o5", lots=0.20),
        account=acct(equity=100_000), positions=pos, last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "correlation_cluster_cap"


# ─── USD net exposure ─────────────────────────────────────────────────────

def test_usd_net_exposure_rejects():
    rm = make_rm(RiskConfig(
        max_usd_net_exposure_lots=1.0,
        max_correlation_cluster_lots=10.0,   # disable cluster gate for this test
        min_seconds_between_orders=0,
    ))
    pos = [Position("EURUSD", "buy", lots=0.9, entry=1.1, open_ts_ms=0)]
    d = rm.check(
        intent(oid="o6", lots=0.20),
        account=acct(equity=100_000), positions=pos, last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "usd_net_exposure_cap"


# ─── news blackout ────────────────────────────────────────────────────────

def test_news_blackout_rejects():
    cal = NewsCalendar()
    cal.add_event("USD", ts_ms=1700000000000, window_minutes=5)
    rm = RiskManager(
        config=RiskConfig(news_blackout_minutes=5, min_seconds_between_orders=0),
        symbols=SYMBOLS, cluster_members=CLUSTERS, calendar=cal,
    )
    d = rm.check(
        intent(),
        account=acct(), positions=[], last_tick=tick(), now_ms=1700000000000,
    )
    assert not d.approved and d.reason == "news_blackout"


# ─── entry far from market ────────────────────────────────────────────────

def test_entry_far_from_market_rejects():
    rm = make_rm(RiskConfig(min_seconds_between_orders=0))
    # market mid ≈ 1.1000, intent entry 1.2000 (~9% away)
    d = rm.check(
        intent(entry=1.2000, sl=1.1900),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "entry_far_from_market"


# ─── idempotency ──────────────────────────────────────────────────────────

def test_duplicate_order_id_rejects():
    rm = make_rm(RiskConfig(min_seconds_between_orders=0))
    d1 = rm.check(intent(oid="dup"), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert d1.approved
    d2 = rm.check(intent(oid="dup"), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert not d2.approved and d2.reason == "duplicate_order_id"


# ─── lot quantization ─────────────────────────────────────────────────────

def test_lot_below_minimum_rejects():
    rm = make_rm(RiskConfig(min_seconds_between_orders=0))
    d = rm.check(
        intent(oid="oQ", lots=0.001),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "lot_size_invalid"


def test_lot_off_step_rejects():
    rm = make_rm(RiskConfig(min_seconds_between_orders=0))
    d = rm.check(
        intent(oid="oQ2", lots=0.013),
        account=acct(), positions=[], last_tick=tick(), now_ms=0,
    )
    assert not d.approved and d.reason == "lot_size_invalid"


# ─── unknown symbol ───────────────────────────────────────────────────────

def test_unknown_symbol_rejects():
    rm = make_rm()
    bad = OrderIntent(
        client_order_id="oU", symbol="XXXYYY", side="buy", lots=0.1,
        entry=1.0, stop_loss=0.9,
    )
    d = rm.check(bad, account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert not d.approved and d.reason.startswith("unknown_symbol")


# ─── happy path ───────────────────────────────────────────────────────────

def test_happy_path_approves():
    rm = make_rm(RiskConfig(min_seconds_between_orders=0))
    d = rm.check(intent(), account=acct(), positions=[], last_tick=tick(), now_ms=0)
    assert d.approved
    assert d.intent is not None
