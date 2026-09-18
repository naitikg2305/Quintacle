from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.drop_router import parse_routine_definition
from quintacle_core.nodes.logs.log_store import LogFileStore, RoutineStore
from quintacle_core.nodes.logs.repository import LogsRepository


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    log_store = LogFileStore(tmp_path / "kb")
    return LogsRepository(conn, log_store), log_store, conn


def test_parse_routine_definition_splits_name_and_exercises():
    assert parse_routine_definition("Pull Day = Pull-ups, Rows, Lat Pulldown") == (
        "Pull Day",
        ["Pull-ups", "Rows", "Lat Pulldown"],
    )


def test_parse_routine_definition_returns_none_without_equals():
    assert parse_routine_definition("did my pull workout") is None


def test_add_routine_writes_markdown(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.add_routine("Pull Day", ["Pull-ups", "Rows"])

    routines = RoutineStore(log_store.kb_root).all()
    assert len(routines) == 1
    assert routines[0]["name"] == "Pull Day"
    assert routines[0]["exercises"] == ["Pull-ups", "Rows"]


def test_routine_exercise_names_canonicalized_against_logged_history(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.log_exercise(date(2026, 9, 8), "Pull Ups", [{"reps": 8}])

    repo.add_routine("Pull Day", ["pull-ups", "Rows"])

    routines = repo.list_routines()
    assert routines[0]["exercises"][0] == "Pull Ups"  # corrected to match logged history


def test_redefining_a_routine_updates_in_place_not_duplicate(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.add_routine("Pull Day", ["Pull-ups"])
    repo.add_routine("pull day", ["Pull-ups", "Rows"])  # slightly different casing

    routines = repo.list_routines()
    assert len(routines) == 1
    assert routines[0]["exercises"] == ["Pull-ups", "Rows"]
