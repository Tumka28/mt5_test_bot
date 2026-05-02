"""Shared types used by strategy, risk, and dispatcher."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class OrderIntent:
    """Strategy-аас гарсан, гэхдээ EXECUTE хийгээгүй захиалга.
    Risk Manager-аар заавал дамжина."""
    client_order_id: str
    symbol: str
    side: Side
    lots: float
    entry: float
    stop_loss: float | None
    take_profit: float | None = None
    comment: str = ""

    @property
    def signed_lots(self) -> float:
        return self.lots if self.side == "buy" else -self.lots


@dataclass(frozen=True)
class Position:
    symbol: str
    side: Side
    lots: float
    entry: float
    open_ts_ms: int

    @property
    def signed_lots(self) -> float:
        return self.lots if self.side == "buy" else -self.lots


@dataclass(frozen=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    ts_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class AccountState:
    equity: float
    balance: float
    currency: str = "USD"
    pnl_today: float = 0.0
    pnl_week: float = 0.0


@dataclass
class RiskDecision:
    approved: bool
    reason: str = ""
    intent: OrderIntent | None = None

    @classmethod
    def approve(cls, intent: OrderIntent) -> "RiskDecision":
        return cls(approved=True, intent=intent)

    @classmethod
    def reject(cls, reason: str) -> "RiskDecision":
        return cls(approved=False, reason=reason)


@dataclass
class SymbolMeta:
    contract_size: float
    min_lot: float
    lot_step: float
    pip_value_usd: float
    cluster: str
    typical_spread_pips: float = 0.0


@dataclass
class RiskConfig:
    max_risk_per_trade: float = 0.005
    max_daily_loss: float = 0.03
    max_weekly_loss: float = 0.06
    max_open_positions: int = 3
    max_usd_net_exposure_lots: float = 2.0
    max_correlation_cluster_lots: float = 1.5
    news_blackout_minutes: int = 5
    min_seconds_between_orders: int = 2
    entry_far_from_market_pct: float = 0.005
    require_stop_loss: bool = True
