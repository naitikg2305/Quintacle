from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from .store import PersonStore

router = APIRouter(prefix="/people", tags=["people"])
_store: PersonStore | None = None


def init_store(kb_root) -> None:
    global _store
    _store = PersonStore(kb_root)


def get_store() -> PersonStore:
    if _store is None:
        raise RuntimeError("people store not initialized — call init_store() first")
    return _store


class PersonCreate(BaseModel):
    name: str
    category: str = ""
    how_met: str = ""
    met_date: str | None = None
    notes: str = ""


@router.post("")
def create_person(body: PersonCreate) -> dict:
    known_names = [p["name"] for p in get_store().all()]
    resolved_name = canonicalize_name(body.name, known_names)
    folder, slug = get_store().write(resolved_name, body.category, body.how_met, body.met_date, body.notes)
    return {"name": resolved_name, "slug": slug, "folder": folder}


@router.get("")
def list_people() -> list[dict]:
    return get_store().all()
