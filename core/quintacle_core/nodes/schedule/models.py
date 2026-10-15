from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from ... import clock


class Priority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class Todo(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    priority: Priority = Priority.MEDIUM
    due_date: date | None = None
    start_time: str | None = None  # "HH:MM", 24-hour — e.g. an event's time window
    end_time: str | None = None
    done: bool = False
    # Same loose vocabulary as the activity log ("productivity", "fitness",
    # "social", ...) so a completed todo slots into the Action view's
    # category picture instead of floating uncategorized.
    category: str = ""
    # When it was actually finished (ET) — the calendar's Action view shows a
    # completed todo on this day with this time, not on its due date.
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    notes: str = ""


def apply_todo_updates(todo: Todo, updates: dict) -> Todo:
    """The one place a `done` flip is interpreted, shared by the REST PATCH
    and the MCP todo_update so they can't drift: marking done stamps
    completed_at with the real moment (unless the caller backdated it);
    un-marking clears it."""
    if updates.get("done") is True and not todo.done and "completed_at" not in updates:
        updates = {**updates, "completed_at": clock.now()}
    elif updates.get("done") is False:
        updates = {**updates, "completed_at": None}
    return todo.model_copy(update=updates)
