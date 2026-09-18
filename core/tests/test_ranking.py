from datetime import date

from quintacle_core.nodes.schedule.models import Priority, Todo
from quintacle_core.nodes.schedule.ranking import build_calendar, rank_todos


def make(title, priority=Priority.MEDIUM, due=None, done=False):
    return Todo(title=title, priority=priority, due_date=due, done=done)


def test_rank_by_due_date_then_priority():
    a = make("far", due=date(2026, 5, 1))
    b = make("near-low", due=date(2026, 1, 1), priority=Priority.LOW)
    c = make("near-urgent", due=date(2026, 1, 1), priority=Priority.URGENT)
    d = make("undated")
    e = make("done-but-near", due=date(2026, 1, 1), done=True)

    ranked = rank_todos([a, b, c, d, e])

    assert [t.title for t in ranked] == ["near-urgent", "near-low", "far", "undated"]


def test_calendar_groups_by_due_date_skips_done():
    a = make("a", due=date(2026, 1, 1), priority=Priority.LOW)
    b = make("b", due=date(2026, 1, 1), priority=Priority.HIGH)
    c = make("c", due=date(2026, 1, 2))
    d = make("d", due=date(2026, 1, 1), done=True)

    calendar = build_calendar([a, b, c, d])

    assert list(calendar.keys()) == [date(2026, 1, 1), date(2026, 1, 2)]
    assert [t.title for t in calendar[date(2026, 1, 1)]] == ["b", "a"]
