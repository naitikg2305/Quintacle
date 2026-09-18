from __future__ import annotations

from datetime import date, timedelta

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


# Two goal shapes: time-based ("golf >= 2hrs this week") and amount-based
# ("kcal <= 2000 today", "spend <= $X this week") — same window mechanics,
# different metric source and comparison direction.
_METRIC_SOURCES = {
    "activity_hours": lambda repo, habit, start, end: repo.hours_for_category_between(
        habit["match_category"], start, end
    ),
    "food_kcal": lambda repo, habit, start, end: repo.kcal_between(start, end),
    "spend": lambda repo, habit, start, end: repo.total_spend_between(start, end),
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

    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "current": current,
        "target": habit["target_amount"],
        "met": met,
    }


def habit_progress(repo, habit_id: int, today: date | None = None) -> dict:
    today = today or date.today()
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
    today = today or date.today()
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
