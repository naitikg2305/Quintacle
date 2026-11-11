"""Versioned habits (next-wave-plan §8): effective-dated versions, upsert/edit
takes force next period, end-dating, per-era history, the exercise_days
metric, and the weekly ledger behind the goals calendar. All seeded,
deterministic arithmetic — fixed dates around Thu 2026-09-10 (its week runs
Mon 2026-09-07 .. Sun 2026-09-13)."""
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from quintacle_core import clock
from quintacle_core.db import connect
from quintacle_core.nodes.logs import api as logs_api
from quintacle_core.nodes.logs.quotas import habit_history, habit_progress, next_period_start, weekly_ledger
from quintacle_core.nodes.logs.repository import LogsRepository

THU = date(2026, 9, 10)  # Thursday
MON = date(2026, 9, 7)  # its Monday
NEXT_MON = date(2026, 9, 14)


def _repo(tmp_path) -> LogsRepository:
    return LogsRepository(connect(tmp_path / "test.db"))


# --- activation boundaries ---


def test_next_period_start_boundaries():
    assert next_period_start("week", THU) == NEXT_MON
    assert next_period_start("week", MON) == NEXT_MON  # a Monday edit still waits a week
    assert next_period_start("2weeks", THU) == NEXT_MON  # next-Monday convention
    assert next_period_start("month", THU) == date(2026, 10, 1)
    assert next_period_start("month", date(2026, 12, 10)) == date(2027, 1, 1)  # year rollover
    assert next_period_start("day", THU) == date(2026, 9, 11)


# --- migration backfill ---


def test_migration_backfills_one_initial_version_per_legacy_habit(tmp_path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    # A legacy row written before versioning existed (direct INSERT, no version).
    conn.execute(
        "INSERT INTO habits (name, target_amount, target_period, match_category, unit) VALUES ('Golf', 2, 'week', 'golf', 'hrs')"
    )
    conn.commit()
    conn.close()

    conn = connect(db_path)  # migrations re-run on connect → backfill fires
    repo = LogsRepository(conn)
    habit_id = conn.execute("SELECT id FROM habits WHERE name='Golf'").fetchone()["id"]
    v = repo.version_in_force(habit_id, date(2020, 1, 1))
    assert v is not None  # in force since forever — pre-versioning weeks judged against it
    assert v["effective_from"] == "0001-01-01"
    assert v["target_amount"] == 2
    conn.close()

    conn = connect(db_path)  # and it is idempotent on every later connect
    assert conn.execute("SELECT COUNT(*) AS c FROM habit_versions").fetchone()["c"] == 1


# --- upsert / edit activation ---


def test_upsert_on_thursday_takes_effect_next_monday(tmp_path):
    repo = _repo(tmp_path)
    created = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=THU)
    assert created["updated"] is False
    assert created["effective_from"] == MON.isoformat()  # brand-new habit counts THIS week

    upsert = repo.add_habit("Golf", 5, "week", "golf", unit="hrs", today=THU)
    assert upsert["id"] == created["id"]
    assert upsert["updated"] is True
    assert upsert["effective_from"] == NEXT_MON.isoformat()

    repo.log_activity(THU, "golf", "front nine", hours=3.0)
    repo.log_activity(date(2026, 9, 15), "golf", "back nine", hours=3.0)

    # Thursday is still the old target's week…
    p = habit_progress(repo, created["id"], today=THU)
    assert p["target"] == 2
    assert p["met"] is True
    # …next Tuesday is the new target's week.
    p = habit_progress(repo, created["id"], today=date(2026, 9, 15))
    assert p["target"] == 5
    assert p["met"] is False


def test_update_habit_appends_version_and_history_flips_at_the_right_week(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=date(2026, 8, 31))["id"]
    result = repo.update_habit(habit_id, {"target_amount": 5}, today=THU)
    assert result["effective_from"] == NEXT_MON.isoformat()

    history = habit_history(repo, habit_id, periods=3, today=date(2026, 9, 16))
    assert [h["window"]["start"] for h in history] == ["2026-08-31", "2026-09-07", "2026-09-14"]
    assert [h["target"] for h in history] == [2, 2, 5]  # flips exactly at Sep 14's week


def test_history_skips_weeks_before_first_effective_from(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=THU)["id"]
    history = habit_history(repo, habit_id, periods=8, today=THU)
    assert len(history) == 1  # the habit's first week only — nothing invented before it
    assert history[0]["window"]["start"] == MON.isoformat()


def test_period_change_week_to_month_walks_per_era(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=date(2026, 8, 10))["id"]
    # Edit to monthly on Sep 10 → takes force at the NEW period's next
    # boundary, Oct 1 (a version's effective_from sits on its own period grid).
    result = repo.update_habit(habit_id, {"target_period": "month", "target_amount": 8}, today=THU)
    assert result["effective_from"] == "2026-10-01"

    history = habit_history(repo, habit_id, periods=4, today=date(2026, 11, 10))
    windows = [(h["window"]["start"], h["window"]["end"]) for h in history]
    assert windows == [
        ("2026-09-21", "2026-09-27"),  # weekly era steps by weeks…
        ("2026-09-28", "2026-09-30"),  # …its last window truncated at the era boundary
        ("2026-10-01", "2026-10-31"),  # monthly era steps by real months
        ("2026-11-01", "2026-11-10"),  # current partial month
    ]
    assert [h["target"] for h in history] == [2, 2, 8, 8]


def test_month_period_edit_activates_on_the_first(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Monthly cap", 310, "month", None, unit="$", metric="spend", direction="at_most", today=date(2026, 9, 1))["id"]
    result = repo.update_habit(habit_id, {"target_amount": 400}, today=THU)
    assert result["effective_from"] == "2026-10-01"
    assert habit_progress(repo, habit_id, today=date(2026, 9, 30))["target"] == 310
    assert habit_progress(repo, habit_id, today=date(2026, 10, 1))["target"] == 400


# --- end-dating ---


def test_end_habit_judges_through_period_end_then_retires(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=date(2026, 8, 31))["id"]
    repo.log_activity(THU, "golf", "front nine", hours=3.0)

    ended = repo.end_habit(habit_id, today=THU)
    assert ended["ended_on"] == "2026-09-13"  # the current week's Sunday — this week still counts

    # Still listed (and judged) until ended_on passes…
    assert [h["name"] for h in repo.list_habits(today=THU)] == ["Golf"]
    assert habit_progress(repo, habit_id, today=date(2026, 9, 12))["met"] is True
    # …then gone from the live list, but the row is never deleted.
    assert repo.list_habits(today=NEXT_MON) == []
    assert repo.get_habit(habit_id) is not None
    # Progress asked after the end reports the FINAL window, frozen.
    final = habit_progress(repo, habit_id, today=date(2026, 9, 25))
    assert final["window"] == {"start": "2026-09-07", "end": "2026-09-13"}

    # Ledger keeps the habit, marks post-end weeks inactive.
    ledger = weekly_ledger(repo, weeks=3, today=date(2026, 9, 25))
    golf = ledger["habits"][0]
    actives = [c["active"] for c in golf["cells"]]
    assert actives == [True, False, False]  # week of Sep 7 active; Sep 14/21 after the end
    assert golf["cells"][0]["met"] is True
    assert golf["cells"][0]["in_progress"] is False  # frozen, not forever "in progress"


def test_re_adding_an_ended_habit_revives_it(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=date(2026, 8, 31))["id"]
    repo.end_habit(habit_id, today=date(2026, 9, 3))
    revived = repo.add_habit("Golf", 4, "week", "golf", unit="hrs", today=THU)
    assert revived["id"] == habit_id  # same identity, history intact
    listed = repo.list_habits(today=THU)
    assert listed[0]["ended_on"] is None
    assert listed[0]["pending"]["target_amount"] == 4  # takes force next Monday


# --- flattened list shape ---


def test_list_habits_keeps_flat_shape_with_additive_keys(tmp_path):
    repo = _repo(tmp_path)
    habit_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=THU)["id"]
    repo.update_habit(habit_id, {"target_amount": 5}, today=THU)

    (h,) = repo.list_habits(today=THU)
    # Original flat keys, with the in-force (old) values…
    assert h["id"] == habit_id and h["name"] == "Golf"
    assert h["target_amount"] == 2 and h["target_period"] == "week"
    assert h["match_category"] == "golf" and h["unit"] == "hrs"
    assert h["metric"] == "activity_hours" and h["direction"] == "at_least"
    # …plus the additive versioning keys.
    assert h["ended_on"] is None
    assert h["effective_from"] == MON.isoformat()
    assert h["pending"]["target_amount"] == 5
    assert h["pending"]["effective_from"] == NEXT_MON.isoformat()


# --- exercise_days metric ---


def test_exercise_days_counts_distinct_days(tmp_path):
    repo = _repo(tmp_path)
    repo.log_exercise(date(2026, 9, 7), "Squat", [{"reps": 5}])
    repo.log_exercise(date(2026, 9, 8), "Bench", [{"reps": 5}])
    repo.log_exercise(date(2026, 9, 8), "Rows", [{"reps": 8}])  # same day — still one day
    repo.log_exercise(date(2026, 9, 9), "Deadlift", [{"reps": 3}])
    assert repo.exercise_days_between(date(2026, 9, 7), date(2026, 9, 13)) == 3

    habit_id = repo.add_habit("Gym", 4, "week", None, unit="sessions", metric="exercise_days", today=THU)["id"]
    p = habit_progress(repo, habit_id, today=THU)
    assert p["current"] == 3
    assert p["met"] is False  # 3 of 4 sessions so far


# --- weekly ledger ---


def test_weekly_ledger_shape_order_and_cells(tmp_path):
    repo = _repo(tmp_path)
    golf_id = repo.add_habit("Golf", 2, "week", "golf", unit="hrs", today=date(2026, 8, 31))["id"]
    repo.add_habit("Calorie cap", 2000, "day", None, unit="kcal", metric="food_kcal", direction="at_most", today=MON)
    repo.log_activity(date(2026, 9, 2), "golf", "full round", hours=4.0)  # week of Aug 31: met
    repo.log_activity(THU, "golf", "front nine", hours=1.0)  # current week: not yet
    repo.log_food(MON, "lunch", freeform_kcal=1500)  # Mon under cap
    repo.log_food(date(2026, 9, 8), "feast", freeform_kcal=2600)  # Tue over cap

    ledger = weekly_ledger(repo, weeks=3, today=THU)

    # Weeks oldest-first, last = current partial week.
    assert [w["start"] for w in ledger["weeks"]] == ["2026-08-24", "2026-08-31", "2026-09-07"]
    assert [h["name"] for h in ledger["habits"]] == ["Calorie cap", "Golf"]

    golf = next(h for h in ledger["habits"] if h["id"] == golf_id)
    assert [c["active"] for c in golf["cells"]] == [False, True, True]  # not yet created in Aug 24's week
    full_week = golf["cells"][1]
    assert full_week["met"] is True and full_week["in_progress"] is False
    assert full_week["actual"] == 4.0 and full_week["target"] == 2
    current = golf["cells"][2]
    assert current["in_progress"] is True and current["met"] is False
    assert current["elapsed_days"] == 4 and current["period_days"] == 7
    assert current["prorated_target"] == round(2 * 4 / 7, 2)  # computed in code, client formats only
    assert current["effective_from"] == "2026-08-31"

    kcal = next(h for h in ledger["habits"] if h["name"] == "Calorie cap")
    day_cell = kcal["cells"][2]
    assert day_cell["days_total"] == 4  # Mon..Thu elapsed
    assert day_cell["days_met"] == 3  # Tue blew the cap
    assert day_cell["met"] is False and day_cell["in_progress"] is True
    assert kcal["cells"][0]["active"] is False and kcal["cells"][1]["active"] is False


# --- API level ---


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(clock, "today", lambda: THU)
    logs_api.init_repo(connect(tmp_path / "test.db"))
    app = FastAPI()
    app.include_router(logs_api.router)
    return TestClient(app)


def test_habit_endpoints_upsert_patch_delete_and_ledger(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    created = client.post(
        "/logs/habits",
        json={"name": "Golf", "target_amount": 2, "target_period": "week", "match_category": "golf", "unit": "hrs"},
    ).json()
    assert created["updated"] is False
    assert created["effective_from"] == MON.isoformat()

    upserted = client.post(
        "/logs/habits",
        json={"name": "Golf", "target_amount": 5, "target_period": "week", "match_category": "golf", "unit": "hrs"},
    ).json()
    assert upserted["id"] == created["id"]
    assert upserted["updated"] is True
    assert upserted["effective_from"] == NEXT_MON.isoformat()

    (listed,) = client.get("/logs/habits").json()
    assert listed["target_amount"] == 2  # old version still in force this week
    assert listed["pending"]["target_amount"] == 5

    patched = client.patch(f"/logs/habits/{created['id']}", json={"target_amount": 7}).json()
    assert patched == {"id": created["id"], "effective_from": NEXT_MON.isoformat()}

    ledger = client.get("/logs/habits/ledger?weeks=2").json()
    assert len(ledger["weeks"]) == 2
    assert ledger["weeks"][-1]["start"] == MON.isoformat()
    assert len(ledger["habits"][0]["cells"]) == 2

    ended = client.delete(f"/logs/habits/{created['id']}").json()
    assert ended == {"id": created["id"], "ended_on": "2026-09-13"}
    (still_listed,) = client.get("/logs/habits").json()  # until ended_on passes
    assert still_listed["ended_on"] == "2026-09-13"
