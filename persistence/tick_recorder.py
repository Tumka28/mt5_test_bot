"""Tick Recorder — өдөр тутам parquet-д tick хадгална.

Memory-д accumulate хийнэ, threshold буюу day rollover үед disk руу flush.
Replay simulator энэ файлуудаас уншина — сэргэлтэд parquet-ийн compression
+ columnar формат маш тохиромжтой.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any


class TickRecorder:
    def __init__(self, root_dir: str | Path, *, flush_every: int = 5000):
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._buffer: list[dict[str, Any]] = []
        self._flush_every = flush_every
        self._current_date: dt.date | None = None

    def _date_for(self, ts_ms: int) -> dt.date:
        return dt.datetime.utcfromtimestamp(ts_ms / 1000).date()

    def record(self, *, symbol: str, bid: float, ask: float, ts_ms: int) -> None:
        d = self._date_for(ts_ms)
        if self._current_date is None:
            self._current_date = d
        if d != self._current_date:
            self.flush()
            self._current_date = d
        self._buffer.append(
            {"symbol": symbol, "bid": bid, "ask": ask, "ts_ms": ts_ms}
        )
        if len(self._buffer) >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        try:
            import pandas as pd  # local import — pyarrow only loaded on flush
        except Exception:
            self._buffer.clear()
            return
        d = self._current_date or dt.date.today()
        path = self._root / f"ticks-{d.isoformat()}.parquet"
        df_new = pd.DataFrame(self._buffer)
        if path.exists():
            df_old = pd.read_parquet(path)
            df = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df = df_new
        df.to_parquet(path, compression="zstd", index=False)
        self._buffer.clear()
