"""OHLC bar dataclass + per-symbol/per-timeframe rolling history buffer."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    """Нэг OHLC бар. ts_ms нь бар-ын open time (millisecond)."""
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


class BarHistory:
    """Per-(symbol, timeframe) rolling buffer.  Append shinэ bar-ыг адил `ts_ms`-тай
    хуучин бар руу overwrite хийнэ — MT5-аас live update хийгдэж буй сүүлийн бар.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._key_index: dict[tuple[str, str], deque[Bar]] = {}
        self._maxlen = maxlen

    def reset(self, symbol: str, timeframe: str) -> None:
        self._key_index[(symbol, timeframe)] = deque(maxlen=self._maxlen)

    def replace_all(self, symbol: str, timeframe: str, bars: list[Bar]) -> None:
        dq: deque[Bar] = deque(maxlen=self._maxlen)
        for b in bars:
            dq.append(b)
        self._key_index[(symbol, timeframe)] = dq

    def append(self, symbol: str, timeframe: str, bar: Bar) -> None:
        dq = self._key_index.setdefault((symbol, timeframe), deque(maxlen=self._maxlen))
        if dq and dq[-1].ts_ms == bar.ts_ms:
            dq[-1] = bar  # type: ignore[index]  # deque assignment OK
            return
        dq.append(bar)

    def get(self, symbol: str, timeframe: str) -> list[Bar]:
        return list(self._key_index.get((symbol, timeframe), ()))

    def latest(self, symbol: str, timeframe: str) -> Bar | None:
        dq = self._key_index.get((symbol, timeframe))
        if not dq:
            return None
        return dq[-1]


def parse_bars_payload(data: str) -> list[Bar]:
    """EA-аас ирсэн "t,o,h,l,c,v;..." string-ийг list[Bar]-руу хөрвүүлнэ."""
    if not data:
        return []
    out: list[Bar] = []
    for chunk in data.split(";"):
        if not chunk:
            continue
        fields = chunk.split(",")
        if len(fields) < 5:
            continue
        try:
            t = int(fields[0])
            o = float(fields[1])
            h = float(fields[2])
            l = float(fields[3])
            c = float(fields[4])
            v = int(fields[5]) if len(fields) > 5 else 0
        except ValueError:
            continue
        out.append(Bar(ts_ms=t, open=o, high=h, low=l, close=c, volume=v))
    return out
