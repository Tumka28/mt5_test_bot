"""Replay harness — parquet/iterable ticks-ыг strategy → risk → exec → journal-аар
дамжуулна. Live pipeline-тай НЭГ Risk Manager class-ийг ашиглана: backtest
нь яг live-ийн адил хатуу шалгуурыг дамжуулна.

Зорилго: live deploy-ын өмнө strategy-г бодит execution model дотор шалгах.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from brain.risk_manager import RiskManager
from brain.strategy_base import Strategy
from brain.types import (
    AccountState,
    OrderIntent,
    Position,
    SymbolMeta,
    Tick,
)
from replay.simulator import ExecutionModel, FillResult

logger = logging.getLogger(__name__)


@dataclass
class _OpenPosition:
    intent: OrderIntent
    fill_price: float
    fill_ts: int

    def to_position(self) -> Position:
        return Position(
            symbol=self.intent.symbol,
            side=self.intent.side,
            lots=self.intent.intent_lots if hasattr(self.intent, "intent_lots") else self.intent.lots,
            entry=self.fill_price,
            open_ts_ms=self.fill_ts,
        )


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    lots: float
    entry: float
    exit_price: float
    open_ts_ms: int
    close_ts_ms: int
    pnl_usd: float
    reason: str  # "tp" | "sl" | "eod"


@dataclass
class ReplayResult:
    ticks_processed: int = 0
    intents_generated: int = 0
    intents_rejected: int = 0
    fills: int = 0
    fills_rejected_at_exec: int = 0
    commissions_paid: float = 0.0
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    final_equity: float = 0.0

    @property
    def net_pnl(self) -> float:
        return sum(t.pnl_usd for t in self.closed_trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl_usd > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl_usd <= 0)

    def summary(self) -> str:
        n = len(self.closed_trades)
        wr = (self.wins / n * 100) if n else 0.0
        return (
            f"ticks={self.ticks_processed} "
            f"intents={self.intents_generated} (rej={self.intents_rejected}) "
            f"fills={self.fills} (rej={self.fills_rejected_at_exec}) "
            f"trades={n} wr={wr:.1f}% "
            f"pnl_usd={self.net_pnl:+.2f} equity={self.final_equity:.2f}"
        )


class ReplayHarness:
    """Tick stream-ийг strategy + risk + execution-аар дамжуулна.

    Position management:
      - Зөвхөн НЭГ open позиц per symbol per direction (хялбар хувилбар).
      - SL/TP hit → автомат close, P&L бичигдэнэ.
    """

    def __init__(
        self,
        *,
        strategy: Strategy,
        risk: RiskManager,
        execution: ExecutionModel,
        symbols: dict[str, SymbolMeta],
        starting_equity: float = 100_000.0,
    ) -> None:
        self._strat = strategy
        self._risk = risk
        self._exec = execution
        self._symbols = symbols
        self._equity = starting_equity
        self._open: list[_OpenPosition] = []

    def run(self, ticks: Iterable[Tick]) -> ReplayResult:
        result = ReplayResult(final_equity=self._equity)

        for tick in ticks:
            result.ticks_processed += 1

            # 1. Хаагдвал зохих open позицуудыг шалга (SL/TP hit)
            self._check_exits(tick, result)

            # 2. Strategy → intents
            intents = self._strat.on_tick(tick)
            result.intents_generated += len(intents)

            # 3. Risk-аар дамжуулна
            for intent in intents:
                positions = [op.to_position() for op in self._open]
                account = AccountState(
                    equity=self._equity, balance=self._equity,
                    pnl_today=0.0, pnl_week=0.0,
                )
                decision = self._risk.check(
                    intent, account=account, positions=positions,
                    last_tick=tick, now_ms=tick.ts_ms,
                )
                if not decision.approved:
                    result.intents_rejected += 1
                    logger.debug("risk reject %s: %s",
                                 intent.client_order_id, decision.reason)
                    continue

                # 4. Execution model → fill
                meta = self._symbols[intent.symbol]
                fill = self._exec.simulate_fill(intent, tick, meta)
                if not fill.filled:
                    result.fills_rejected_at_exec += 1
                    continue
                # commission debited up-front
                comm = self._exec.commission_usd(intent.lots)
                self._equity -= comm
                result.commissions_paid += comm
                result.fills += 1
                self._open.append(_OpenPosition(
                    intent=intent, fill_price=fill.price, fill_ts=tick.ts_ms,
                ))

        # End-of-replay: одоо нээлттэй байгаа бүх позицийг тухайн tick-ийн
        # mid-ээр force-close (mark-to-market).
        if self._open:
            last_tick = tick  # last loop var
            self._force_close_all(last_tick, result, reason="eod")

        result.final_equity = self._equity
        return result

    # ─── internals ──────────────────────────────────────────────────────

    def _check_exits(self, tick: Tick, result: ReplayResult) -> None:
        still_open: list[_OpenPosition] = []
        for op in self._open:
            if op.intent.symbol != tick.symbol:
                still_open.append(op)
                continue
            close = self._maybe_close_at(op, tick, result)
            if close is None:
                still_open.append(op)
        self._open = still_open

    def _maybe_close_at(
        self, op: _OpenPosition, tick: Tick, result: ReplayResult,
    ) -> ClosedTrade | None:
        intent = op.intent
        sl, tp = intent.stop_loss, intent.take_profit
        if intent.side == "buy":
            # SL: bid <= sl ; TP: bid >= tp
            if sl is not None and tick.bid <= sl:
                return self._close(op, tick.bid, tick.ts_ms, "sl", result)
            if tp is not None and tick.bid >= tp:
                return self._close(op, tick.bid, tick.ts_ms, "tp", result)
        else:
            if sl is not None and tick.ask >= sl:
                return self._close(op, tick.ask, tick.ts_ms, "sl", result)
            if tp is not None and tick.ask <= tp:
                return self._close(op, tick.ask, tick.ts_ms, "tp", result)
        return None

    def _close(
        self, op: _OpenPosition, exit_price: float, ts_ms: int,
        reason: str, result: ReplayResult,
    ) -> ClosedTrade:
        meta = self._symbols[op.intent.symbol]
        if op.intent.side == "buy":
            pnl = (exit_price - op.fill_price) * op.intent.lots * meta.contract_size
        else:
            pnl = (op.fill_price - exit_price) * op.intent.lots * meta.contract_size
        self._equity += pnl
        trade = ClosedTrade(
            symbol=op.intent.symbol, side=op.intent.side, lots=op.intent.lots,
            entry=op.fill_price, exit_price=exit_price,
            open_ts_ms=op.fill_ts, close_ts_ms=ts_ms,
            pnl_usd=pnl, reason=reason,
        )
        result.closed_trades.append(trade)
        return trade

    def _force_close_all(
        self, tick: Tick, result: ReplayResult, *, reason: str,
    ) -> None:
        for op in list(self._open):
            price = tick.bid if op.intent.side == "buy" else tick.ask
            self._close(op, price, tick.ts_ms, reason, result)
        self._open.clear()


# ─── helpers ────────────────────────────────────────────────────────────

def ticks_from_parquet(path: str, symbol: str) -> Iterator[Tick]:
    """Parquet файлаас tick stream унших.

    Schema: (symbol, bid, ask, ts_ms) — `persistence.tick_recorder`-той адил.
    """
    import pandas as pd  # noqa: PLC0415
    df = pd.read_parquet(path)
    df = df[df["symbol"] == symbol].sort_values("ts_ms")
    for row in df.itertuples(index=False):
        yield Tick(symbol=row.symbol, bid=float(row.bid),
                   ask=float(row.ask), ts_ms=int(row.ts_ms))
