from datetime import date

from quintacle_core.nodes.schedule.models import Priority, Todo
from quintacle_core.nodes.schedule.store import TodoStore


def test_save_and_load_roundtrip(tmp_path):
    store = TodoStore(tmp_path)
    todo = Todo(
        title="renew passport",
        priority=Priority.URGENT,
        due_date=date(2026, 10, 1),
        notes="check OPT expiry too",
    )

    store.save(todo)
    loaded = store.load(todo.id)

    assert loaded == todo


def test_list_and_delete(tmp_path):
    store = TodoStore(tmp_path)
    t1 = Todo(title="a")
    t2 = Todo(title="b")
    store.save(t1)
    store.save(t2)

    assert {t.id for t in store.list()} == {t1.id, t2.id}

    store.delete(t1.id)
    assert {t.id for t in store.list()} == {t2.id}
