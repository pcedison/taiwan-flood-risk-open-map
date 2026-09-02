from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


HISTORICAL_LOOKBACK_YEARS = 15
HISTORICAL_CALENDAR_TIMEZONE = "Asia/Taipei"


@dataclass(frozen=True)
class HistoricalYearWindow:
    start_year: int
    end_year: int


def historical_year_window(as_of: datetime) -> HistoricalYearWindow:
    """Return the rolling calendar-year window in Taiwan civil time."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("historical window as_of must be timezone-aware")
    local_year = as_of.astimezone(ZoneInfo(HISTORICAL_CALENDAR_TIMEZONE)).year
    return HistoricalYearWindow(
        start_year=local_year - HISTORICAL_LOOKBACK_YEARS + 1,
        end_year=local_year,
    )


def historical_window_start(as_of: datetime) -> datetime:
    """Return the first instant of the oldest calendar year in the 15-year window."""

    window = historical_year_window(as_of)
    local_start = datetime(
        window.start_year,
        1,
        1,
        tzinfo=ZoneInfo(HISTORICAL_CALENDAR_TIMEZONE),
    )
    return local_start.astimezone(as_of.tzinfo)
