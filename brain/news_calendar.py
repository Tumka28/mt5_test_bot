"""ForexFactory CSV-аас news event-ийг ачаалах загвар.

ForexFactory weekly CSV format:
    Title,Country,Date,Time,Impact,Forecast,Previous,URL

    Date "MM-DD-YYYY" эсвэл "YYYY-MM-DD"
    Time "HH:MMam/pm" эсвэл "HH:MM" 24h, эсвэл "All Day", "Tentative"
    Impact: "High", "Medium", "Low", "Holiday"

Бид зөвхөн High impact event-ийг авна, тус бүрд window_minutes (default 5)
RiskManager-ийн NewsCalendar-руу хийнэ. Country-г symbol-руу map хийнэ:
    USD → USD, EUR → EUR, GBP → GBP, JPY → JPY, etc.
RiskManager `has_high_impact_within` нь USD-той pair-ыг шалгахдаа "USD" symbol-ыг
ч давхар шалгадаг (risk_manager.py). Тэгэхээр бид зүгээр л currency code-оор тэмдэглэж
болно.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from brain.risk_manager import NewsCalendar

logger = logging.getLogger(__name__)


_DATE_FORMATS = ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")
_TIME_FORMATS = ("%I:%M%p", "%I:%M %p", "%H:%M")


def _parse_dt(date_str: str, time_str: str) -> datetime | None:
    date_str = date_str.strip()
    time_str = time_str.strip().lower()
    if time_str in ("", "all day", "tentative", "tba"):
        return None  # ignore — нэг өдөр window-д их event ороход хор хүргэнэ

    parsed_date: datetime | None = None
    for fmt in _DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None

    # ForexFactory CSV time-уудад "am"/"pm" lowercase-аар ирдэг → uppercase
    time_norm = time_str.replace("am", "AM").replace("pm", "PM").strip()
    parsed_time: datetime | None = None
    for fmt in _TIME_FORMATS:
        try:
            parsed_time = datetime.strptime(time_norm, fmt)
            break
        except ValueError:
            continue
    if parsed_time is None:
        return None

    combined = parsed_date.replace(
        hour=parsed_time.hour, minute=parsed_time.minute,
        tzinfo=timezone.utc,
    )
    return combined


def load_forexfactory_csv(
    path: str | Path,
    *,
    calendar: NewsCalendar | None = None,
    window_minutes: int = 5,
    impact_filter: tuple[str, ...] = ("High",),
) -> NewsCalendar:
    """ForexFactory CSV дээрх event-уудыг calendar-руу хийнэ.

    Args:
        path: ForexFactory weekly CSV-ийн зам.
        calendar: Аль хэдийн байгаа NewsCalendar (нэмэлт event-уудыг merge).
        window_minutes: Тус event-ын blackout window (default 5).
        impact_filter: Аль impact level-ийг авах вэ (default High).
    """
    path = Path(path)
    cal = calendar or NewsCalendar()
    if not path.exists():
        logger.warning("news calendar CSV missing: %s", path)
        return cal

    impact_set = {x.lower() for x in impact_filter}
    n_added = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            impact = (row.get("Impact") or "").strip().lower()
            if impact not in impact_set:
                continue
            country = (row.get("Country") or row.get("Currency") or "").strip().upper()
            if not country:
                continue
            dt = _parse_dt(row.get("Date") or "", row.get("Time") or "")
            if dt is None:
                continue
            ts_ms = int(dt.timestamp() * 1000)
            cal.add_event(country, ts_ms, window_minutes=window_minutes)
            n_added += 1
    logger.info("loaded %d news events from %s", n_added, path)
    return cal


def load_events_iter(
    events: Iterable[tuple[str, datetime, int]],
    *,
    calendar: NewsCalendar | None = None,
) -> NewsCalendar:
    """In-memory event list-аас calendar build хийнэ. Тестэнд хэрэгтэй."""
    cal = calendar or NewsCalendar()
    for sym, dt, window_min in events:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts_ms = int(dt.timestamp() * 1000)
        cal.add_event(sym, ts_ms, window_minutes=window_min)
    return cal
