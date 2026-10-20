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


def next_period_start(target_period: str, today: date) -> date:
    """When a habit edit/upsert takes force (next-wave-plan §8): the NEXT
    period boundary — the current period always finishes under the old
    target. week → next Monday; 2weeks has no natural anchor (its window is
    rolling), so next Monday is the convention there too; month → the 1st of
    next month; day → tomorrow. Deterministic calendar arithmetic."""
    if target_period in ("week", "2weeks"):
        return today + timedelta(days=7 - today.weekday())
    if target_period == "month":
        return date(today.year + today.month // 12, today.month % 12 + 1, 1)
    if target_period == "day":
        return today + timedelta(days=1)
    raise ValueError(f"unknown target_period: {target_period!r}")


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
    # "gym 4x/week": distinct days with any exercise logged in the window —
    # unit "sessions", direction at_least (next-wave-plan §8).
    "exercise_days": lambda repo, habit, start, end: repo.exercise_days_between(start, end),
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


def _ended_date(habit) -> date | None:
    ended_on = habit["ended_on"] if "ended_on" in habit.keys() else None
    return date.fromisoformat(ended_on) if ended_on else None


def habit_progress(repo, habit_id: int, today: date | None = None) -> dict:
    """Current-window progress under versioning (next-wave-plan §8): the
    window is owned by whichever version was in force at its START — a week
    by its Monday's version, a month by its 1st's. Since every version's
    effective_from is a period boundary of its own period, the version in
    force today and the one at the window start normally agree; the rolling
    2weeks window is the one shape where an effective_from can fall inside
    the window, and there the start's version wins (as specified)."""
    today = today or clock.today()
    habit = repo.get_habit(habit_id)
    if habit is None:
        raise ValueError(f"no habit with id {habit_id}")
    ended = _ended_date(habit)
    if ended and today > ended:
        today = ended  # an ended habit's "current" progress is its final window

    v = repo.version_in_force(habit_id, today)
    if v is None:
        # Only reachable for a not-yet-started version chain (shouldn't happen
        # via add_habit, whose first version starts the current period).
        raise ValueError(f"habit {habit_id} has no version in force on {today}")
    start, _ = period_window(v["target_period"], today)
    owner = repo.version_in_force(habit_id, start) or v

    result = _progress_for_window(repo, owner, start, today)
    return {
        "habit": habit["name"],
        "unit": owner["unit"],
        "target_period": owner["target_period"],
        "metric": owner["metric"] or "activity_hours",
        "direction": owner["direction"] or "at_least",
        **result,
    }


def habit_history(repo, habit_id: int, periods: int = 8, today: date | None = None) -> list[dict]:
    """The last N periods' progress, oldest first. Each back-stepped window
    is judged — AND SIZED — by the version in force at its own date, so a
    period change walks per era: weekly windows while the weekly version
    reigned, monthly windows once the monthly one took over. Windows before
    the first effective_from are skipped (the habit didn't exist); for an
    ended habit the walk starts at ended_on. Response shape unchanged —
    per-point target already rides each window."""
    today = today or clock.today()
    habit = repo.get_habit(habit_id)
    if habit is None:
        raise ValueError(f"no habit with id {habit_id}")
    ended = _ended_date(habit)
    cursor = min(today, ended) if ended else today

    history = []
    while len(history) < periods:
        v = repo.version_in_force(habit_id, cursor)
        if v is None:
            break  # stepped back before the habit's first version
        start, _ = period_window(v["target_period"], cursor)
        eff = date.fromisoformat(v["effective_from"])
        if eff > start:
            # A period change can leave a remnant window (e.g. the rolling
            # 2weeks shape) — clamp to this version's own era.
            start = eff
        history.append(_progress_for_window(repo, v, start, cursor))
        cursor = start - timedelta(days=1)

    return list(reversed(history))


def _week_cell(repo, habit, week_start: date, today: date) -> dict:
    """One calendar cell: this habit's state for the Monday-anchored week
    starting week_start, judged under the version in force on that Monday
    (next-wave-plan §8 — 'a week is owned by whichever version was in force
    on its Monday'). All arithmetic here, none on the client."""
    inactive = {
        "window": {"start": week_start.isoformat(), "end": (week_start + timedelta(days=6)).isoformat()},
        "target": None, "actual": None, "met": None, "in_progress": False,
        "elapsed_days": None, "period_days": None, "prorated_target": None,
        "effective_from": None, "active": False,
    }
    v = repo.version_in_force(habit["id"], week_start)
    ended = _ended_date(habit)
    if v is None or (ended and week_start > ended):
        return inactive  # before the habit existed / after it ended

    period = v["target_period"]
    # The last date this cell may measure through: the week is partial if it
    # contains today, and an ended habit is judged only through ended_on.
    as_of = min(today, ended) if ended else today

    if period == "day":
        # Aggregate the week's day-windows: of the days elapsed so far, how
        # many met the daily target ("2000 kcal/day" → 4/5 days this week).
        days_met = 0
        days_total = 0
        d = week_start
        while d <= min(week_start + timedelta(days=6), as_of):
            p = _progress_for_window(repo, v, d, d)
            days_total += 1
            days_met += 1 if p["met"] else 0
            d += timedelta(days=1)
        week_end = week_start + timedelta(days=6)
        return {
            "window": {"start": week_start.isoformat(), "end": week_end.isoformat()},
            "target": v["target_amount"], "actual": days_met,
            "met": days_total > 0 and days_met == days_total,
            # Still in progress only while measurement can still move: the
            # cut-off is today (not a passed ended_on) and the week isn't over.
            "in_progress": as_of == today and week_start <= today <= week_end,
            "elapsed_days": days_total, "period_days": 7,
            "prorated_target": None,
            "days_met": days_met, "days_total": days_total,
            "effective_from": v["effective_from"], "active": True,
        }

    if period == "2weeks":
        # Rolling windows have no grid; the ledger anchors them to the cell's
        # Monday (same next-Monday convention as next_period_start).
        start = week_start
        full_end = week_start + timedelta(days=13)
    else:
        start, _ = period_window(period, week_start)
        full_end = start + timedelta(days=_full_period_days(period, start) - 1)

    measure_end = min(full_end, as_of)
    if measure_end < start:
        return inactive  # whole window after as_of (shouldn't happen for requested weeks)
    p = _progress_for_window(repo, v, start, measure_end)
    return {
        "window": {"start": start.isoformat(), "end": full_end.isoformat()},
        "target": p["target"], "actual": p["current"], "met": p["met"],
        # In progress only while measurement can still move — i.e. the cut-off
        # was today (not a passed ended_on) and the full window isn't over.
        "in_progress": measure_end == today and measure_end < full_end,
        "elapsed_days": p["elapsed_days"], "period_days": p["period_days"],
        "prorated_target": p["prorated_target"],
        "effective_from": v["effective_from"], "active": True,
    }


def weekly_ledger(repo, weeks: int, today: date | None = None) -> dict:
    """The goals-calendar feed (next-wave-plan §8): the last `weeks`
    Monday-anchored weeks (oldest first, last = the current partial week) ×
    every habit, one cell each. Habits with no active cell in the range
    (ended long ago / not yet started) are dropped from the response; ended
    habits otherwise stay, their post-end cells marked active:false — the
    row is history, never deleted."""
    today = today or clock.today()
    monday = today - timedelta(days=today.weekday())
    week_starts = [monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    weeks_out = [
        {"start": s.isoformat(), "end": (s + timedelta(days=6)).isoformat()} for s in week_starts
    ]

    habits_out = []
    for habit in repo.all_habits():
        cells = [_week_cell(repo, habit, s, today) for s in week_starts]
        if not any(c["active"] for c in cells):
            continue
        # Display fields ride the version in force on the current week's
        # Monday (fall back to the latest version for just-ended habits).
        v = repo.version_in_force(habit["id"], monday) or repo.latest_version(habit["id"])
        habits_out.append(
            {
                "id": habit["id"],
                "name": habit["name"],
                "unit": v["unit"],
                "metric": v["metric"] or "activity_hours",
                "direction": v["direction"] or "at_least",
                "cells": cells,
            }
        )

    return {"weeks": weeks_out, "habits": habits_out}
