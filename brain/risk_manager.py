"""Risk Manager — HARD GATE.

Strategy-ийн гаргасан БҮХ OrderIntent заавал энэ class-ийг дамжина.
Энэ давхрага strategy-д огт итгэхгүй: stop-loss-гүй order, шалгалт даваагүй
size, news blackout-д орсон symbol — бүгдийг хатуу reject хийнэ.

Live, paper, backtest бүгд НЭГ Risk Manager instance-аар дамжих ёстой.
Хэрэв хаа нэг газар "тусгай" risk байгаа бол — энэ давхраг яагаад үнэн
backtest хийдгийн утга алдагдана.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from brain.types import (
    AccountState,
    OrderIntent,
    Position,
    RiskConfig,
    RiskDecision,
    SymbolMeta,
    Tick,
)

logger = logging.getLogger(__name__)


class KillSwitch:
    """Армлагдсаны дараа manual disarm л болно. Bot өөрөө disarm хийдэггүй."""

    def __init__(self) -> None:
        self._armed = False
        self._reason = ""
        self._armed_ts: float = 0.0

    def is_armed(self) -> bool:
        return self._armed

    def arm(self, reason: str) -> None:
        if not self._armed:
            self._armed = True
            self._reason = reason
            self._armed_ts = time.time()
            logger.error("KILL SWITCH ARMED: %s", reason)

    def disarm(self) -> None:
        # Зориудаар тусдаа method — accidental call-аас сэргийлж log-д бичнэ.
        if self._armed:
            logger.warning("kill switch DISARMED — was: %s", self._reason)
        self._armed = False
        self._reason = ""


class NewsCalendar:
    """High-impact news-ийн blackout мэдээллийн хамгийн жижиг interface.

    Production-д ForexFactory CSV эсвэл economic calendar feed-аас уншина.
    Энд тестийн зориулалтаар `add_event` API-тай.
    """

    def __init__(self) -> None:
        # symbol -> list of (ts_ms, minutes_window)
        self._events: dict[str, list[tuple[int, int]]] = {}

    def add_event(self, symbol: str, ts_ms: int, window_minutes: int = 5) -> None:
        self._events.setdefault(symbol, []).append((ts_ms, window_minutes))

    def has_high_impact_within(self, symbol: str, *, now_ms: int, minutes: int) -> bool:
        # symbol-д шууд + currency-аар дамжсан шалгалт (USD news EURUSD-д нөлөөлнө)
        candidates = list(self._events.get(symbol, []))
        # USD-той pair бол USD events-ийг ч авна
        if "USD" in symbol:
            candidates += self._events.get("USD", [])
        for ev_ts, win in candidates:
            window = max(win, minutes) * 60_000
            if abs(now_ms - ev_ts) <= window:
                return True
        return False


class RiskManager:
    def __init__(
        self,
        *,
        config: RiskConfig,
        symbols: dict[str, SymbolMeta],
        cluster_members: dict[str, list[str]],
        kill_switch: KillSwitch | None = None,
        calendar: NewsCalendar | None = None,
    ) -> None:
        self._cfg = config
        self._symbols = symbols
        self._clusters = cluster_members
        self._kill = kill_switch or KillSwitch()
        self._calendar = calendar or NewsCalendar()
        self._recent_order_ids: set[str] = set()
        self._last_order_ts: float = 0.0

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill

    @property
    def calendar(self) -> NewsCalendar:
        return self._calendar

    # ─── public API ────────────────────────────────────────────────────────

    def check(
        self,
        intent: OrderIntent,
        *,
        account: AccountState,
        positions: Iterable[Position],
        last_tick: Tick,
        now_ms: int,
    ) -> RiskDecision:
        """Бүх шалгалтуудыг дарааллаар нь явуулна. Эхний failure-д шууд reject."""
        positions = list(positions)

        # 1. Kill switch
        if self._kill.is_armed():
            return RiskDecision.reject("kill_switch_armed")

        # 2. Daily / weekly loss
        if account.pnl_today <= -self._cfg.max_daily_loss * account.equity:
            self._kill.arm("daily_loss_breached")
            return RiskDecision.reject("daily_loss_breached")
        if account.pnl_week <= -self._cfg.max_weekly_loss * account.equity:
            return RiskDecision.reject("weekly_loss_breached")

        # 3. Position count
        if len(positions) >= self._cfg.max_open_positions:
            return RiskDecision.reject("max_open_positions")

        # 4. Stop-loss заавал
        if self._cfg.require_stop_loss and intent.stop_loss is None:
            return RiskDecision.reject("no_stop_loss")

        # 5. Per-trade risk (stop-distance × lots × contract_size)
        meta = self._symbols.get(intent.symbol)
        if meta is None:
            return RiskDecision.reject(f"unknown_symbol:{intent.symbol}")
        if intent.stop_loss is not None:
            stop_distance = abs(intent.entry - intent.stop_loss)
            risk_usd = stop_distance * intent.lots * meta.contract_size
            if risk_usd > self._cfg.max_risk_per_trade * account.equity:
                return RiskDecision.reject(
                    f"trade_risk_{risk_usd:.0f}_over_cap"
                )
            # Sanity: stop-distance > 0
            if stop_distance == 0:
                return RiskDecision.reject("zero_stop_distance")

        # 6. Correlation cluster
        cluster_name = meta.cluster
        cluster_syms = set(self._clusters.get(cluster_name, [])) | {intent.symbol}
        cluster_lots = sum(p.signed_lots for p in positions if p.symbol in cluster_syms)
        cluster_lots += intent.signed_lots
        if abs(cluster_lots) > self._cfg.max_correlation_cluster_lots:
            return RiskDecision.reject("correlation_cluster_cap")

        # 7. USD net exposure (USD-той pair-уудын нийлбэр lots)
        usd_lots = sum(p.signed_lots for p in positions if "USD" in p.symbol)
        if "USD" in intent.symbol:
            usd_lots += intent.signed_lots
        if abs(usd_lots) > self._cfg.max_usd_net_exposure_lots:
            return RiskDecision.reject("usd_net_exposure_cap")

        # 8. News blackout
        if self._calendar.has_high_impact_within(
            intent.symbol, now_ms=now_ms, minutes=self._cfg.news_blackout_minutes,
        ):
            return RiskDecision.reject("news_blackout")

        # 9. Rate limit
        if (time.time() - self._last_order_ts) < self._cfg.min_seconds_between_orders:
            return RiskDecision.reject("rate_limited")

        # 10. Entry far from market
        ref = last_tick.mid
        if ref > 0 and abs(intent.entry - ref) / ref > self._cfg.entry_far_from_market_pct:
            return RiskDecision.reject("entry_far_from_market")

        # 11. Idempotency
        if intent.client_order_id in self._recent_order_ids:
            return RiskDecision.reject("duplicate_order_id")

        # 12. Lot quantization
        steps = round(intent.lots / meta.lot_step)
        quantized = round(steps * meta.lot_step, 4)
        if intent.lots < meta.min_lot or abs(quantized - intent.lots) > 1e-9:
            return RiskDecision.reject("lot_size_invalid")

        # ─── approved ───
        self._recent_order_ids.add(intent.client_order_id)
        # bound the set so it doesn't grow unboundedly
        if len(self._recent_order_ids) > 10_000:
            self._recent_order_ids = set(list(self._recent_order_ids)[-5_000:])
        self._last_order_ts = time.time()
        return RiskDecision.approve(intent)
