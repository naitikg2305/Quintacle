from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.repository import LogsRepository


def make_repo(tmp_path):
    conn = connect(tmp_path / "test.db")
    return LogsRepository(conn)


def test_meal_autofills_macros_on_log(tmp_path):
    repo = make_repo(tmp_path)
    meal_id = repo.add_meal("chicken meal", protein_g=50, carbs_g=60, fat_g=15, kcal=575)

    repo.log_food(date(2026, 9, 3), "lunch", meal_id=meal_id, servings=1)
    repo.log_food(date(2026, 9, 3), "dinner", meal_id=meal_id, servings=1.5)

    totals = repo.daily_totals(date(2026, 9, 3))

    assert totals["total_kcal"] == 575 * 2.5
    assert totals["total_protein_g"] == 50 * 2.5


def test_freeform_entry_without_premade_meal(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_food(date(2026, 9, 3), "out", freeform_kcal=600, servings=1)

    totals = repo.daily_totals(date(2026, 9, 3))

    assert totals["total_kcal"] == 600
    assert totals["total_protein_g"] == 0


def test_activity_and_exercise_logging(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_activity(date(2026, 9, 3), "work", "Regli Email")
    repo.log_exercise(
        date(2026, 9, 3), "Pull Ups", [{"reps": 8}, {"reps": 5}, {"reps": 4}, {"reps": 4}]
    )

    activities = repo.activities_for_date(date(2026, 9, 3))
    assert activities[0]["description"] == "Regli Email"


def test_expense_kind_defaults_and_round_trips(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_expense(date(2026, 9, 3), 12.5, merchant="Chipotle", category="dining")
    repo.log_expense(date(2026, 9, 3), 15.99, merchant="Netflix", category="streaming", kind="subscription")

    expenses = repo.expenses_between(date(2026, 9, 1), date(2026, 9, 30))
    by_merchant = {e["merchant"]: e["kind"] for e in expenses}

    assert by_merchant["Chipotle"] == "regular"
    assert by_merchant["Netflix"] == "subscription"
