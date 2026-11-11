from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.quotas import habit_history, habit_progress, period_window
from quintacle_core.nodes.logs.repository import LogsRepository


def test_week_window_starts_monday():
    # 2026-09-03 is a Thursday -> week starts Monday 2026-08-31
    start, end = period_window("week", date(2026, 9, 3))
    assert start == date(2026, 8, 31)
    assert end == date(2026, 9, 3)


def test_habit_progress_sums_matching_category_in_window(tmp_path):
    conn = connect(tmp_path / "test.db")
    repo = LogsRepository(conn)
    habit_id = repo.add_habit(
        "Golf", target_amount=2, target_period="week", match_category="golf", unit="hrs", today=date(2026, 9, 3)
    )["id"]

    repo.log_activity(date(2026, 9, 3), "golf", "played 9 holes", hours=1.0)
    repo.log_activity(date(2026, 9, 3), "work", "unrelated", hours=3.0)

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 3))

    assert progress["current"] == 1.0
    assert progress["target"] == 2.0
    assert progress["met"] is False


def test_amount_based_goal_is_met_when_under_cap(tmp_path):
    conn = connect(tmp_path / "test.db")
    repo = LogsRepository(conn)
    habit_id = repo.add_habit(
        "Calorie cap", target_amount=2000, target_period="day", match_category=None,
        unit="kcal", metric="food_kcal", direction="at_most", today=date(2026, 9, 3),
    )["id"]

    repo.log_food(date(2026, 9, 3), "lunch", freeform_kcal=1200, servings=1)

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 3))

    assert progress["current"] == 1200
    assert progress["met"] is True


def test_amount_based_goal_is_not_met_over_cap(tmp_path):
    conn = connect(tmp_path / "test.db")
    repo = LogsRepository(conn)
    habit_id = repo.add_habit(
        "Calorie cap", target_amount=2000, target_period="day", match_category=None,
        unit="kcal", metric="food_kcal", direction="at_most", today=date(2026, 9, 3),
    )["id"]

    repo.log_food(date(2026, 9, 3), "lunch", freeform_kcal=1500, servings=1)
    repo.log_food(date(2026, 9, 3), "dinner", freeform_kcal=1000, servings=1)

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 3))

    assert progress["current"] == 2500
    assert progress["met"] is False


def test_habit_history_returns_oldest_first_across_weekly_periods(tmp_path):
    conn = connect(tmp_path / "test.db")
    repo = LogsRepository(conn)
    # Created before the window history will walk — versioned history skips
    # weeks before the habit's first effective_from.
    habit_id = repo.add_habit(
        "Golf", target_amount=2, target_period="week", match_category="golf", unit="hrs", today=date(2026, 8, 10)
    )["id"]

    repo.log_activity(date(2026, 8, 24), "golf", "back nine", hours=1.0)  # week of Aug 24
    repo.log_activity(date(2026, 9, 3), "golf", "front nine", hours=3.0)  # week of Aug 31 (this week)

    history = habit_history(repo, habit_id, periods=3, today=date(2026, 9, 3))

    assert len(history) == 3
    assert history[0]["window"]["start"] < history[-1]["window"]["start"]  # oldest first
    assert history[-1]["current"] == 3.0  # current week
    assert history[-1]["met"] is True
    assert history[-2]["current"] == 1.0  # prior week
    assert history[-2]["met"] is False
    assert history[0]["current"] == 0.0  # two weeks back, nothing logged
