from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import Priority, Todo, apply_todo_updates
from .ranking import build_calendar, rank_todos
from .store import TodoStore

router = APIRouter(prefix="/schedule", tags=["schedule"])
_store: TodoStore | None = None


def init_store(root) -> None:
    global _store
    _store = TodoStore(root)


def get_store() -> TodoStore:
    if _store is None:
        raise RuntimeError("schedule store not initialized — call init_store() first")
    return _store


class TodoCreate(BaseModel):
    title: str
    category: str = ""
    priority: Priority = Priority.MEDIUM
    due_date: date | None = None
    start_time: str | None = None
    end_time: str | None = None
    notes: str = ""


class TodoUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    priority: Priority | None = None
    due_date: date | None = None
    start_time: str | None = None
    end_time: str | None = None
    done: bool | None = None
    notes: str | None = None


@router.get("/todos")
def list_todos() -> list[Todo]:
    return rank_todos(get_store().list())


@router.post("/todos")
def create_todo(body: TodoCreate) -> Todo:
    todo = Todo(**body.model_dump())
    get_store().save(todo)
    return todo


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: str, body: TodoUpdate) -> Todo:
    store = get_store()
    try:
        todo = store.load(todo_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="todo not found")
    updates = body.model_dump(exclude_unset=True)
    todo = apply_todo_updates(todo, updates)
    store.save(todo)
    return todo


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: str) -> dict:
    get_store().delete(todo_id)
    return {"deleted": todo_id}


@router.get("/calendar")
def get_calendar() -> dict[str, list[Todo]]:
    calendar = build_calendar(get_store().list())
    return {day.isoformat(): todos for day, todos in calendar.items()}
