from datetime import date, datetime

from quintacle_core.nodes.schedule.models import Todo, apply_todo_updates
from quintacle_core.nodes.schedule.store import TodoStore


def test_marking_done_stamps_completed_at_eastern():
    todo = Todo(title="Call landlord", category="productivity")
    done = apply_todo_updates(todo, {"done": True})
    assert done.done
    assert done.completed_at is not None
    assert done.completed_at.tzinfo is not None  # clock.now() is tz-aware ET


def test_unmarking_done_clears_completed_at():
    todo = apply_todo_updates(Todo(title="x"), {"done": True})
    reopened = apply_todo_updates(todo, {"done": False})
    assert not reopened.done
    assert reopened.completed_at is None


def test_already_done_todo_keeps_its_original_stamp():
    todo = apply_todo_updates(Todo(title="x"), {"done": True})
    first_stamp = todo.completed_at
    renamed = apply_todo_updates(todo, {"done": True, "title": "y"})
    assert renamed.completed_at == first_stamp


def test_completed_at_and_category_round_trip_through_the_store(tmp_path):
    store = TodoStore(tmp_path)
    todo = apply_todo_updates(Todo(title="5k run", category="fitness"), {"done": True})
    store.save(todo)

    loaded = store.load(todo.id)
    assert loaded.category == "fitness"
    assert loaded.completed_at == todo.completed_at


def test_day_detail_and_counts_show_completion_on_the_day_it_happened(tmp_path, monkeypatch):
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    import importlib

    import quintacle_core.api as api_module

    importlib.reload(api_module)
    from fastapi.testclient import TestClient

    client = TestClient(api_module.create_app())

    created = client.post(
        "/schedule/todos", json={"title": "Call landlord", "category": "productivity", "due_date": "2026-10-01"}
    ).json()
    done = client.patch(f"/schedule/todos/{created['id']}", json={"done": True}).json()
    done_day = datetime.fromisoformat(done["completed_at"]).date().isoformat()

    detail = client.get(f"/day/{done_day}").json()
    titles = [t["title"] for t in detail["todos_completed"]]
    assert "Call landlord" in titles
    assert detail["todos_completed"][0]["category"] == "productivity"

    counts = client.get(f"/day/counts?start={done_day}&end={done_day}").json()
    assert counts.get(done_day, 0) >= 1
    # and it does NOT count on the due date (a different day)
    assert "2026-10-01" not in counts or counts["2026-10-01"] == 0
