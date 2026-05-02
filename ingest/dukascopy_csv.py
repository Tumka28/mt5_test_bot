"""Dukascopy / HistData CSV → parquet ingestion.

Хүлээн авах форматууд:

1. **Dukascopy tick CSV** (most common free source):
       Local time,Bid,Ask,AskVolume,BidVolume
       2024.01.02 00:00:00.123,1.10412,1.10421,1.5,2.0

2. **Generic OHLC CSV** (M1 bars), үүнийг "synthetic tick" болгож (open=bid+ask
   midpoint, ts=bar open time) ingestion-д орохгүй: bar-аас tick үүсгэх нь
   slippage модельд хор учруулдаг. Энэ ingester-т bar дэмжихгүй, зөвхөн tick.

Гарал гаралт: parquet файл `(symbol, bid, ask, ts_ms)` schema-тай.
Replay harness-ийн `ticks_from_parquet` хэрэглэх боломжтой.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Iterable, Iterator


_FORMATS = (
    "%Y.%m.%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_ts(s: str) -> int:
    """Return epoch milliseconds (UTC)."""
    s = s.strip()
    for fmt in _FORMATS:
        try:
            t = dt.datetime.strptime(s, fmt)
            return int(t.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp: {s!r}")


def _normalise_header(header: list[str]) -> dict[str, int]:
    """Map канон-нэр → column index. Dukascopy-ийн нэрсийг ч, lower-case-ыг ч авна."""
    canon = {h.strip().lower(): i for i, h in enumerate(header)}
    aliases = {
        "ts": ["local time", "gmt time", "timestamp", "time", "datetime"],
        "bid": ["bid"],
        "ask": ["ask"],
    }
    out: dict[str, int] = {}
    for k, alts in aliases.items():
        for a in alts:
            if a in canon:
                out[k] = canon[a]
                break
    if not {"ts", "bid", "ask"}.issubset(out):
        raise ValueError(f"missing required columns; have {list(canon)}")
    return out


def iter_csv_ticks(path: str | Path, symbol: str) -> Iterator[dict]:
    """Stream rows из CSV → tick dicts (без загрузки в памет)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return
        cols = _normalise_header(header)
        for row in reader:
            if not row or len(row) <= max(cols.values()):
                continue
            try:
                ts_ms = _parse_ts(row[cols["ts"]])
                bid = float(row[cols["bid"]])
                ask = float(row[cols["ask"]])
            except (ValueError, IndexError):
                continue
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            yield {"symbol": symbol, "bid": bid, "ask": ask, "ts_ms": ts_ms}


def csv_to_parquet(
    csv_path: str | Path, out_path: str | Path, symbol: str,
    *, batch_size: int = 100_000,
) -> int:
    """Convert CSV to parquet. Returns row count.

    Memory-щадящий: pandas-д batch-аар хуваан concatenate."""
    import pandas as pd  # noqa: PLC0415

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    total = 0
    frames: list[pd.DataFrame] = []
    for tick in iter_csv_ticks(csv_path, symbol):
        rows.append(tick)
        if len(rows) >= batch_size:
            frames.append(pd.DataFrame(rows))
            rows.clear()
    if rows:
        frames.append(pd.DataFrame(rows))
    if not frames:
        # write empty parquet so downstream does not fail with FileNotFound
        empty = pd.DataFrame(columns=["symbol", "bid", "ask", "ts_ms"])
        empty.to_parquet(out_path, index=False)
        return 0
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("ts_ms").reset_index(drop=True)
    total = len(df)
    df.to_parquet(out_path, compression="zstd", index=False)
    return total
