"""Projection path generator — SMC structure-аас bullish/bearish ирээдүйн зам гаргана.

Гаралт: `Projection` объект — bullish/bearish 2 path (multi-point), TP1/TP2/structure
target/big target/invalidation түвшин, мөн evristic probability score (0..1).

Энэ нь NN биш, **rule-based heuristic** — production-readiness үүднээс deterministic,
backtestable. Дараа нь ML probability model-ыг adapter-аар оруулж болно.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from brain.bar import Bar
from brain.smc import StructureState


Side = Literal["bull", "bear"]


@dataclass(frozen=True)
class Projection:
    direction: Side
    probability: float           # 0..1
    waypoints: list[tuple[int, float]]  # (ts_ms, price)
    tp1: float
    tp2: float
    structure_target: float
    big_target: float
    invalidation: float
    rationale: list[str] = field(default_factory=list)


# ─── helpers ────────────────────────────────────────────────────────


def _last_n_swings(swings: list, n: int) -> list:
    return swings[-n:] if len(swings) > n else list(swings)


def _atr(bars: list[Bar], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        c = bars[i]; p = bars[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    if not trs:
        return 0.0
    take = min(n, len(trs))
    return sum(trs[-take:]) / take


def _bar_ms_step(bars: list[Bar]) -> int:
    """Estimate bar interval (ms)."""
    if len(bars) < 2:
        return 60_000
    diffs = sorted([bars[i].ts_ms - bars[i - 1].ts_ms for i in range(1, len(bars))])
    return diffs[len(diffs) // 2]


# ─── public API ─────────────────────────────────────────────────────


def project(state: StructureState, *, lookahead_bars: int = 12) -> list[Projection]:
    """Build bullish + bearish projection paths from current SMC state.

    Логик:
      Bullish:
        - tp1 = ойролцоо bull liquidity (last swing high) эсвэл ATR×2
        - tp2 = previous structure high (даалгасан гол түвшин)
        - structure_target = өмнөх том swing high (last 5)
        - big_target = бүх swing high дотроос дээд хязгаар
        - invalidation = ойрд bull OB-ийн bottom эсвэл last swing low
        - waypoints: [now, retracement_low (OB зүйрлэл), tp1, tp2]
        - probability: trend-той ижил үед өндөр; CHOCH тал дээр бага
      Bearish: тэгш хэмтэй эсрэг.
    """
    bars = state.bars
    if not bars:
        return []
    last = bars[-1]
    last_close = last.close
    atr = _atr(bars)
    step_ms = _bar_ms_step(bars)
    now_ms = last.ts_ms

    bull = _build(state, last_close, atr, now_ms, step_ms, lookahead_bars, side="bull")
    bear = _build(state, last_close, atr, now_ms, step_ms, lookahead_bars, side="bear")
    return [p for p in (bull, bear) if p is not None]


def _build(
    state: StructureState, price: float, atr: float, now_ms: int, step_ms: int,
    lookahead: int, *, side: Side,
) -> Projection | None:
    """Side-specific projection builder."""
    if atr <= 0:
        return None
    rationale: list[str] = []

    # Targets
    if side == "bull":
        highs = sorted({s.price for s in state.swing_highs if s.price > price})
        lows = sorted({s.price for s in state.swing_lows if s.price < price})
        recent_obs = [o for o in state.order_blocks if o.direction == "bull"]
    else:
        highs = sorted({s.price for s in state.swing_highs if s.price > price})
        lows = sorted({s.price for s in state.swing_lows if s.price < price})
        recent_obs = [o for o in state.order_blocks if o.direction == "bear"]

    if side == "bull":
        if not highs:
            tp1 = price + 2.0 * atr
            rationale.append("no swing highs above — using ATR×2 for tp1")
        else:
            tp1 = highs[0]
        tp2 = highs[1] if len(highs) > 1 else (tp1 + 1.5 * atr)
        structure_target = highs[-1] if highs else (tp2 + 2.0 * atr)
        big_target = max(structure_target, price + 6.0 * atr)
        if recent_obs:
            invalidation = min(o.bottom for o in recent_obs[-3:])
            rationale.append("invalidation at recent bull OB bottom")
        elif lows:
            invalidation = lows[-1]
            rationale.append("invalidation at last swing low")
        else:
            invalidation = price - 3.0 * atr
            rationale.append("invalidation at ATR×3 below")
    else:
        if not lows:
            tp1 = price - 2.0 * atr
            rationale.append("no swing lows below — using ATR×2 for tp1")
        else:
            tp1 = lows[-1]
        tp2 = lows[-2] if len(lows) > 1 else (tp1 - 1.5 * atr)
        structure_target = lows[0] if lows else (tp2 - 2.0 * atr)
        big_target = min(structure_target, price - 6.0 * atr)
        if recent_obs:
            invalidation = max(o.top for o in recent_obs[-3:])
            rationale.append("invalidation at recent bear OB top")
        elif highs:
            invalidation = highs[0]
            rationale.append("invalidation at next swing high")
        else:
            invalidation = price + 3.0 * atr
            rationale.append("invalidation at ATR×3 above")

    # Waypoints — pullback then leg up to tp1, then to tp2
    if side == "bull":
        retrace = max(price - 0.5 * atr, invalidation + 0.1 * atr)
    else:
        retrace = min(price + 0.5 * atr, invalidation - 0.1 * atr)
    t0 = now_ms
    t1 = now_ms + 2 * step_ms
    t2 = now_ms + (lookahead // 2) * step_ms
    t3 = now_ms + lookahead * step_ms
    waypoints = [
        (t0, price),
        (t1, retrace),
        (t2, tp1),
        (t3, tp2),
    ]

    # Probability heuristic: aligned with trend → boost, opposite → discount
    base = 0.5
    if state.trend == side:
        base += 0.18
        rationale.append(f"trend aligned ({state.trend})")
    elif state.trend is not None:
        base -= 0.10
        rationale.append(f"counter-trend (current {state.trend})")
    last_event = state.last_event
    if last_event and last_event.direction == side:
        if last_event.kind == "BOS":
            base += 0.08
            rationale.append("recent BOS in this direction")
        elif last_event.kind == "CHOCH":
            base += 0.05
            rationale.append("recent CHOCH supports new direction")
    # FVG / OB confluence
    confluence = 0
    for fvg in state.fvgs:
        if fvg.direction == side and not fvg.filled:
            confluence += 1
    for ob in recent_obs:
        if (side == "bull" and ob.bottom < price) or (side == "bear" and ob.top > price):
            confluence += 1
    if confluence:
        bump = min(0.15, 0.04 * confluence)
        base += bump
        rationale.append(f"+{bump:.2f} for {confluence} unfilled FVG/OB confluence")

    probability = max(0.05, min(0.95, base))

    return Projection(
        direction=side, probability=probability, waypoints=waypoints,
        tp1=tp1, tp2=tp2, structure_target=structure_target,
        big_target=big_target, invalidation=invalidation, rationale=rationale,
    )
