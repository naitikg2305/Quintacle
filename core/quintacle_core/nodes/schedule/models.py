from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum
from uuid import uuid4

from pydantic import BaseModel, Field


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
    created_at: datetime = Field(default_factory=datetime.now)
    notes: str = ""
