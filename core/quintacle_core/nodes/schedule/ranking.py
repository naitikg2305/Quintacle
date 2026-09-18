from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import Todo

# Deterministic — no AI needed (see schedule.md). Undated todos sort last;
# priority (higher first) breaks ties on the same due date.
_FAR_FUTURE = date.max


def rank_todos(todos: list[Todo]) -> list[Todo]:
    open_todos = [t for t in todos if not t.done]
    return sorted(
        open_todos,
        key=lambda t: (t.due_date or _FAR_FUTURE, -t.priority),
    )


def build_calendar(todos: list[Todo]) -> dict[date, list[Todo]]:
    calendar: dict[date, list[Todo]] = defaultdict(list)
    for todo in todos:
        if todo.due_date and not todo.done:
            calendar[todo.due_date].append(todo)
    for day_todos in calendar.values():
        day_todos.sort(key=lambda t: -t.priority)
    return dict(sorted(calendar.items()))
