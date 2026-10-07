"""Quintacle's clock: every "today" and timestamp is Eastern Time, not the
host's local zone — a UTC server (AWS, a container) would otherwise roll the
day over at ~8pm ET and file the nightly journal under tomorrow."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TIME_ZONE = ZoneInfo("America/New_York")


def now() -> datetime:
    return datetime.now(TIME_ZONE)


def today() -> date:
    return now().date()
