"""EMA crossover — хамгийн энгийн baseline стратеги.

Зорилго: production-ready бус. Pipeline-ыг (tick → signal → risk → exec)
end-to-end ажиллаж байгааг батлах baseline. Бодит мөнгөнд ашиглахаас
зайлсхий — EMA crossover нь FX-д ихэнх regime-д edge-гүй.

Логик:
    fast EMA periods-ын дотор slow EMA-г дээгүүр огтлоход → buy
    fast EMA slow EMA-аас доош огтлоход → sell
    SL: ATR proxy (стандарт хазайлтын n-катц)
    TP: 2:1 risk-reward
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from brain.strategy_base import Strategy
from brain.types import OrderIntent, Tick


@dataclass
class _SymbolState:
    fast: float | None = None
    slow: float | None = None
    last_fast_above: bool | None = None
    recent_mids: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    order_seq: int = 0


class EmaCrossStrategy(Strategy):
    name = "ema_cross"

    def __init__(
        self,
        *,
        fast_period: int = 12,
        slow_period: int = 26,
        lots: float = 0.10,
        sl_sigmas: float = 1.5,
        rr: float = 2.0,
        symbol_filter: tuple[str, ...] | None = None,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        self._k_fast = 2.0 / (fast_period + 1)
        self._k_slow = 2.0 / (slow_period + 1)
        self._lots = lots
        self._sl_sigmas = sl_sigmas
        self._rr = rr
        self._symbol_filter = symbol_filter
        self._state: dict[str, _SymbolState] = {}

    def on_tick(self, tick: Tick) -> list[OrderIntent]:
        if self._symbol_filter and tick.symbol not in self._symbol_filter:
            return []

        st = self._state.setdefault(tick.symbol, _SymbolState())
        mid = tick.mid

        # EMA update
        if st.fast is None:
            st.fast = mid
            st.slow = mid
        else:
            st.fast += self._k_fast * (mid - st.fast)
            st.slow += self._k_slow * (mid - st.slow)
        st.recent_mids.append(mid)

        # Need at least 50 ticks of history before signalling
        if len(st.recent_mids) < 50:
            st.last_fast_above = st.fast > st.slow
            return []

        # Volatility — ATR proxy via stdev of recent mids
        n = len(st.recent_mids)
        mean = sum(st.recent_mids) / n
        var = sum((x - mean) ** 2 for x in st.recent_mids) / n
        sigma = math.sqrt(var) if var > 0 else 0.0
        if sigma == 0:
            return []

        fast_above = st.fast > st.slow
        intents: list[OrderIntent] = []

        if st.last_fast_above is not None and fast_above != st.last_fast_above:
            st.order_seq += 1
            oid = f"{tick.symbol}-{tick.ts_ms}-{st.order_seq}"
            stop_dist = self._sl_sigmas * sigma
            if fast_above:
                # bullish cross → buy
                intents.append(OrderIntent(
                    client_order_id=oid, symbol=tick.symbol, side="buy",
                    lots=self._lots, entry=tick.ask,
                    stop_loss=tick.ask - stop_dist,
                    take_profit=tick.ask + self._rr * stop_dist,
                    comment="ema_cross_bull",
                ))
            else:
                intents.append(OrderIntent(
                    client_order_id=oid, symbol=tick.symbol, side="sell",
                    lots=self._lots, entry=tick.bid,
                    stop_loss=tick.bid + stop_dist,
                    take_profit=tick.bid - self._rr * stop_dist,
                    comment="ema_cross_bear",
                ))

        st.last_fast_above = fast_above
        return intents
