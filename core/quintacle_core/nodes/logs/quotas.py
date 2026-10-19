from __future__ import annotations

import calendar
from datetime import date, timedelta

from ... import clock

# Deterministic — no AI needed, same principle as schedule.md's ranking.
_PERIOD_LENGTHS = {"day": 1, "week": 7, "2weeks": 14, "month": 30}


def period_window(target_period: str, today: date) -> tuple[date, date]:
    if target_period == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        return start, today
    if target_period == "month":
        return today.replace(day=1), today
    length = _PERIOD_LENGTHS.get(target_period)
    if length is None:
        raise ValueError(f"unknown target_period: {target_period!r}")
    return today - timedelta(days=length - 1), today


def _full_period_days(target_period: str, start: date) -> int:
    """How many days the FULL period spans — a month's real length, not 30 —
    so a budget line can be time-prorated ("by day 12 of October you should
    be at 12/31 of the cap"). Deterministic calendar arithmetic."""
    if target_period == "month":
        return calendar.monthrange(start.year, start.month)[1]
    return _PERIOD_LENGTHS[target_period]


# Two goal shapes: time-based ("golf >= 2hrs this week") and amount-based
# ("kcal <= 2000 today", "spend <= $X this week") — same window mechanics,
# different metric source and comparison direction. The spend metric routes
# through the budget-line matcher (next-wave-plan §1 decision 2): no
# match_kind/match_category keeps the original total-spend behavior, so
# pre-existing "total spend ≤ $X" quotas are untouched.
_METRIC_SOURCES = {
    "activity_hours": lambda repo, habit, start, end: repo.hours_for_category_between(
        habit["match_category"], start, end
    ),
    "food_kcal": lambda repo, habit, start, end: repo.kcal_between(start, end),
    "spend": lambda repo, habit, start, end: repo.spend_for_habit_between(habit, start, end),
}


def _progress_for_window(repo, habit, start: date, end: date) -> dict:
    metric = habit["metric"] or "activity_hours"
    source = _METRIC_SOURCES.get(metric)
    if source is None:
        raise ValueError(f"unknown habit metric: {metric!r}")
    current = source(repo, habit, start, end)

    direction = habit["direction"] or "at_least"
    if direction == "at_least":
        met = current >= habit["target_amount"]
    elif direction == "at_most":
        met = current <= habit["target_amount"]
    else:
        raise ValueError(f"unknown habit direction: {direction!r}")

    # Time-proration (all arithmetic in code): how much of the cap "should"
    # be used by the window's last day if spending were perfectly even. Only
    # really meaningful for at_most lines mid-period — for a completed
    # history window elapsed == full, so prorated_target == target.
    period_days = _full_period_days(habit["target_period"], start)
    elapsed_days = (end - start).days + 1
    prorated_target = round(habit["target_amount"] * elapsed_days / period_days, 2)

    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "current": current,
        "target": habit["target_amount"],
        "met": met,
        "period_days": period_days,
        "elapsed_days": elapsed_days,
        "prorated_target": prorated_target,
    }


def habit_progress(repo, habit_id: int, today: date | None = None) -> dict:
    today = today or clock.today()
    habit = repo.get_habit(habit_id)
    if habit is None:
        raise ValueError(f"no habit with id {habit_id}")

    start, end = period_window(habit["target_period"], today)
    result = _progress_for_window(repo, habit, start, end)
    return {
        "habit": habit["name"],
        "unit": habit["unit"],
        "target_period": habit["target_period"],
        "metric": habit["metric"] or "activity_hours",
        "direction": habit["direction"] or "at_least",
        **result,
    }


def habit_history(repo, habit_id: int, periods: int = 8, today: date | None = None) -> list[dict]:
    """The last N periods' progress, oldest first — the actual-vs-target
    trend a dashboard needs, not just the current period's snapshot."""
    today = today or clock.today()
    habit = repo.get_habit(habit_id)
    if habit is None:
        raise ValueError(f"no habit with id {habit_id}")

    history = []
    cursor = today
    for _ in range(periods):
        start, end = period_window(habit["target_period"], cursor)
        history.append(_progress_for_window(repo, habit, start, end))
        cursor = start - timedelta(days=1)

    return list(reversed(history))
