"""ForexFactory CSV news loader-ийн тест."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from brain.news_calendar import load_events_iter, load_forexfactory_csv
from brain.risk_manager import NewsCalendar


def test_load_events_iter_basic():
    cal = NewsCalendar()
    dt = datetime(2026, 5, 6, 12, 30, tzinfo=timezone.utc)
    load_events_iter([("USD", dt, 5)], calendar=cal)
    ts = int(dt.timestamp() * 1000)
    assert cal.has_high_impact_within("EURUSD", now_ms=ts, minutes=5)
    # 10 min away should be outside 5min window
    assert not cal.has_high_impact_within("EURUSD", now_ms=ts + 10 * 60_000, minutes=5)


def test_load_forexfactory_csv_high_only(tmp_path: Path):
    csv = tmp_path / "ff.csv"
    csv.write_text(
        "Title,Country,Date,Time,Impact,Forecast,Previous\n"
        "NFP,USD,05-06-2026,12:30pm,High,200K,180K\n"
        "Fed Speak,USD,05-06-2026,2:00pm,Low,,\n"
        "BoE Rate,GBP,05-07-2026,07:00,High,5.25%,5.25%\n",
        encoding="utf-8",
    )
    cal = load_forexfactory_csv(csv)
    nfp_ts = int(datetime(2026, 5, 6, 12, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert cal.has_high_impact_within("EURUSD", now_ms=nfp_ts, minutes=5)
    # Low impact filtered out
    fed_ts = int(datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert not cal.has_high_impact_within("EURUSD", now_ms=fed_ts, minutes=5)
    # GBP event
    boe_ts = int(datetime(2026, 5, 7, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert cal.has_high_impact_within("GBPUSD", now_ms=boe_ts, minutes=5)


def test_load_forexfactory_csv_skips_all_day(tmp_path: Path):
    csv = tmp_path / "ff.csv"
    csv.write_text(
        "Title,Country,Date,Time,Impact,Forecast,Previous\n"
        "Bank Holiday,USD,05-06-2026,All Day,High,,\n"
        "Tentative,USD,05-06-2026,Tentative,High,,\n",
        encoding="utf-8",
    )
    cal = load_forexfactory_csv(csv)
    # nothing parsed → has_high_impact_within returns False everywhere
    ts = int(datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert not cal.has_high_impact_within("EURUSD", now_ms=ts, minutes=60)


def test_missing_csv_returns_empty(tmp_path: Path):
    cal = load_forexfactory_csv(tmp_path / "nonexistent.csv")
    assert isinstance(cal, NewsCalendar)
