"""Budget lines (next-wave-plan §1 decision 2): the quota engine's spend
metric matching by kind and/or whole-word text, plus time-proration. All
seeded arithmetic — the engine must reproduce hand-computed numbers."""
from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.quotas import habit_progress
from quintacle_core.nodes.logs.repository import LogsRepository


def _repo(tmp_path) -> LogsRepository:
    return LogsRepository(connect(tmp_path / "test.db"))


def _seed_expenses(repo):
    # Week of Mon 2026-09-07 .. Sun 2026-09-13
    repo.log_expense(date(2026, 9, 8), 20.0, "Chipotle", "dining", "", "food")
    repo.log_expense(date(2026, 9, 9), 35.0, "Total Wine", "", "", "alcohol")
    repo.log_expense(date(2026, 9, 10), 14.0, "GNC", "supplements", "creatine monohydrate", "shopping")
    repo.log_expense(date(2026, 9, 10), 100.0, "Rent Co", "", "", "regular")
    # Outside the window — must never count.
    repo.log_expense(date(2026, 9, 1), 500.0, "Chipotle", "", "", "food")


def test_spend_habit_without_matcher_stays_total_spend(tmp_path):
    repo = _repo(tmp_path)
    _seed_expenses(repo)
    habit_id = repo.add_habit("Total spend", 200, "week", None, unit="$", metric="spend", direction="at_most")

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 20.0 + 35.0 + 14.0 + 100.0
    assert progress["met"] is True


def test_spend_habit_matches_by_kind(tmp_path):
    repo = _repo(tmp_path)
    _seed_expenses(repo)
    habit_id = repo.add_habit("Food budget", 50, "week", None, unit="$", metric="spend", direction="at_most", match_kind="food")

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 20.0  # only the in-window food expense
    assert progress["met"] is True


def test_spend_habit_matches_by_whole_word_text(tmp_path):
    repo = _repo(tmp_path)
    _seed_expenses(repo)
    habit_id = repo.add_habit("Creatine line", 20, "week", "creatine", unit="$", metric="spend", direction="at_most")

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 14.0  # matched in the notes field


def test_spend_habit_kind_or_text_union(tmp_path):
    # "creatine + alcohol monthly"-style line: kind=alcohol OR the word creatine.
    repo = _repo(tmp_path)
    _seed_expenses(repo)
    habit_id = repo.add_habit(
        "Creatine + alcohol", 60, "week", "creatine", unit="$", metric="spend", direction="at_most", match_kind="alcohol"
    )

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 35.0 + 14.0
    assert progress["met"] is True


def test_text_match_is_whole_word_not_substring(tmp_path):
    repo = _repo(tmp_path)
    repo.log_expense(date(2026, 9, 10), 10.0, "Barnes & Noble", "", "", "shopping")
    habit_id = repo.add_habit("Bars", 50, "week", "bar", unit="$", metric="spend", direction="at_most")

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 0.0  # "bar" must not match inside "Barnes"


def test_progress_includes_time_proration_for_month(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Monthly cap", 310, "month", None, unit="$", metric="spend", direction="at_most")

    # Sept 10th: 10 of 30 days elapsed -> prorated cap 310 * 10/30
    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["period_days"] == 30
    assert progress["elapsed_days"] == 10
    assert progress["prorated_target"] == round(310 * 10 / 30, 2)


def test_activity_and_kcal_metrics_unchanged_by_matcher(tmp_path):
    repo = _repo(tmp_path)
    repo.log_activity(date(2026, 9, 10), "golf", "front nine", hours=2.0)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs")

    progress = habit_progress(repo, habit_id, today=date(2026, 9, 10))

    assert progress["current"] == 2.0
    assert progress["met"] is True
