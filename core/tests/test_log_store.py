from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.log_store import LogFileStore, rebuild_sqlite_index
from quintacle_core.nodes.logs.repository import LogsRepository


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    log_store = LogFileStore(tmp_path / "kb")
    return LogsRepository(conn, log_store), log_store, conn


def test_logging_writes_a_markdown_file_nested_under_its_kb_home(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.log_exercise(date(2026, 9, 8), "Deadlift", [{"reps": 8, "weight": 135}] * 3)

    expected = tmp_path / "kb" / "personal-development" / "physical" / "fitness" / "logs" / "2026-09-08-001.md"
    assert expected.exists()
    assert "Deadlift" in expected.read_text()


def test_activity_goes_under_its_category_specific_home(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.log_activity(date(2026, 9, 8), "social", "talked to mom", hours=0.5)

    expected = tmp_path / "kb" / "daily-log" / "social" / "logs" / "2026-09-08-001.md"
    assert expected.exists()


def test_second_entry_same_day_gets_a_distinct_filename(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.log_exercise(date(2026, 9, 8), "Deadlift", [{"reps": 8, "weight": 135}] * 3)
    repo.log_exercise(date(2026, 9, 8), "Pull Ups", [{"reps": r} for r in (8, 5, 4, 4)])

    entries = log_store.all_entries("exercise")
    assert len(entries) == 2
    assert {e["exercise_name"] for e in entries} == {"Deadlift", "Pull Ups"}


def test_rebuild_index_reproduces_sqlite_from_markdown_alone(tmp_path):
    repo, log_store, conn = make(tmp_path)
    repo.log_activity(date(2026, 9, 8), "productivity", "shipped a feature", hours=3)
    repo.log_exercise(date(2026, 9, 8), "Squat", [{"reps": 5, "weight": 225}] * 5)
    repo.log_substance(date(2026, 9, 8), "coffee", 2, notes="black")
    repo.log_body_stat(date(2026, 9, 8), "weight", 181.2)

    # Nuke SQLite entirely, then rebuild purely from the markdown files.
    conn.execute("DELETE FROM activity_log")
    conn.execute("DELETE FROM exercise_sets")
    conn.execute("DELETE FROM substance_log")
    conn.execute("DELETE FROM body_stats")
    conn.commit()

    counts = rebuild_sqlite_index(log_store, conn)

    assert counts == {
        "activity_log": 1,
        "exercise_sets": 1,
        "substance_log": 1,
        "body_stats": 1,
        "expense_log": 0,
        "food_log": 0,
    }
    assert conn.execute("SELECT description FROM activity_log").fetchone()[0] == "shipped a feature"
    assert conn.execute("SELECT exercise_name FROM exercise_sets").fetchone()[0] == "Squat"
    assert conn.execute("SELECT substance FROM substance_log").fetchone()[0] == "coffee"
    assert conn.execute("SELECT value FROM body_stats").fetchone()[0] == 181.2


def test_structured_sets_round_trip_through_rebuild(tmp_path):
    repo, log_store, conn = make(tmp_path)
    repo.log_exercise(
        date(2026, 9, 8), "Deadlift", [{"reps": 8, "weight": 135}, {"reps": 8, "weight": 135}]
    )
    repo.log_exercise(
        date(2026, 9, 8), "Run", [{"duration_min": 30, "distance": 3.1, "calories_burned": 320}]
    )

    conn.execute("DELETE FROM exercise_sets")
    conn.commit()
    rebuild_sqlite_index(log_store, conn)

    assert repo.total_calories_burned(date(2026, 9, 8)) == 320
    rows = repo.exercise_for_date(date(2026, 9, 8))
    deadlift = next(r for r in rows if r["exercise_name"] == "Deadlift")
    import json

    assert json.loads(deadlift["sets_json"]) == [{"reps": 8, "weight": 135}, {"reps": 8, "weight": 135}]


def test_food_snapshot_captures_meal_macros_at_logging_time(tmp_path):
    repo, log_store, _ = make(tmp_path)
    meal_id = repo.add_meal("Chicken Bowl", protein_g=50, carbs_g=60, fat_g=15, kcal=575, fiber_g=5)

    repo.log_food(date(2026, 9, 8), "lunch", meal_id=meal_id, servings=2)

    entries = log_store.all_entries("food")
    assert len(entries) == 1
    assert entries[0]["meal_name"] == "Chicken Bowl"
    assert entries[0]["kcal"] == 1150  # 575 * 2 servings, baked into the file
    assert entries[0]["protein_g"] == 100
