"""Tick CSV ingestion → parquet roundtrip."""
from __future__ import annotations

from pathlib import Path

import pytest

from ingest.dukascopy_csv import csv_to_parquet, iter_csv_ticks


_SAMPLE = """Local time,Bid,Ask,AskVolume,BidVolume
2024.01.02 00:00:00.000,1.10412,1.10421,1.5,2.0
2024.01.02 00:00:00.123,1.10410,1.10420,1.0,1.0
2024.01.02 00:00:00.456,1.10415,1.10422,2.0,1.5
"""

_BAD_ROWS = """Local time,Bid,Ask,AskVolume,BidVolume
2024.01.02 00:00:00.000,1.10412,1.10421,,
notatime,1.1,1.2,,
2024.01.02 00:00:00.500,abc,xyz,,
2024.01.02 00:00:00.700,1.10500,1.10501,,
"""


def test_iter_csv_ticks_basic(tmp_path: Path):
    p = tmp_path / "sample.csv"
    p.write_text(_SAMPLE, encoding="utf-8")
    rows = list(iter_csv_ticks(p, "EURUSD"))
    assert len(rows) == 3
    assert rows[0]["symbol"] == "EURUSD"
    assert rows[0]["bid"] == 1.10412
    assert rows[0]["ask"] == 1.10421
    # Monotonic ts
    assert rows[0]["ts_ms"] < rows[1]["ts_ms"] < rows[2]["ts_ms"]


def test_iter_csv_skips_bad_rows(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text(_BAD_ROWS, encoding="utf-8")
    rows = list(iter_csv_ticks(p, "EURUSD"))
    # Two valid rows out of 4
    assert len(rows) == 2


def test_csv_to_parquet_roundtrip(tmp_path: Path):
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    src = tmp_path / "src.csv"
    src.write_text(_SAMPLE, encoding="utf-8")
    out = tmp_path / "out.parquet"
    n = csv_to_parquet(src, out, "EURUSD")
    assert n == 3
    import pandas as pd
    df = pd.read_parquet(out)
    assert list(df.columns) == ["symbol", "bid", "ask", "ts_ms"]
    assert len(df) == 3
    assert (df["symbol"] == "EURUSD").all()
    assert df["ts_ms"].is_monotonic_increasing


def test_missing_columns_raises(tmp_path: Path):
    p = tmp_path / "miss.csv"
    p.write_text("Time,Price\n2024.01.02 00:00:00,1.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        list(iter_csv_ticks(p, "EURUSD"))
