"""Tick Replay Simulator — STUB.

Бодит execution-ийн ойролцоо backtest хийхийн тулд:
    spread / slippage / latency / partial-fill / commission / reject probability
гэсэн 6 модель-ийг tick-replay-тай хослуулна.

Энэ файл одоогоор skeleton — алхам алхмаар бөглөнө. Validation gate:
live trade-ийн ID-аар replay буулгаад P&L зөрүү 5%-аас бага байх ёстой.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from brain.types import OrderIntent, SymbolMeta, Tick


@dataclass
class FillResult:
    filled: bool
    price: float
    lots_filled: float
    reject_reason: str = ""


class ExecutionModel:
    def __init__(
        self, *,
        slippage_pips_base: float = 0.3,
        latency_ms: tuple[int, int] = (20, 80),
        reject_prob_news: float = 0.15,
        commission_per_lot_round: float = 7.0,
        seed: int | None = None,
    ):
        self._slip_base = slippage_pips_base
        self._latency = latency_ms
        self._reject_prob_news = reject_prob_news
        self._comm = commission_per_lot_round
        self._rng = random.Random(seed)

    def simulate_fill(
        self, intent: OrderIntent, market: Tick, meta: SymbolMeta,
        *, vol_regime: float = 1.0,
    ) -> FillResult:
        # Spread cost — tick-аас шууд
        if intent.side == "buy":
            base_price = market.ask
        else:
            base_price = market.bid

        # Slippage
        size_pen = max(0.0, intent.lots - 1.0) * 0.5
        slip_pips = self._slip_base + size_pen + max(0.0, vol_regime - 1.0) * 0.4
        # rough pip definition: 0.0001 for FX; symbol-specific for metals/indices
        pip_size = 0.0001 if meta.contract_size >= 100_000 else 0.01
        slip = slip_pips * pip_size * (1 if intent.side == "buy" else -1)

        # Reject probability under high vol
        if vol_regime > 2.0 and self._rng.random() < self._reject_prob_news:
            return FillResult(False, 0.0, 0.0, reject_reason="off_quote_news")

        return FillResult(
            filled=True,
            price=base_price + slip,
            lots_filled=intent.lots,
        )

    def commission_usd(self, lots: float) -> float:
        return lots * self._comm
