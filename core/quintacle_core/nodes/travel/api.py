from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from .store import ExperienceStore

router = APIRouter(prefix="/travel", tags=["travel"])
_store: ExperienceStore | None = None


def init_store(kb_root) -> None:
    global _store
    _store = ExperienceStore(kb_root)


def get_store() -> ExperienceStore:
    if _store is None:
        raise RuntimeError("travel store not initialized — call init_store() first")
    return _store


class ExperienceCreate(BaseModel):
    name: str
    city: str
    kind: str
    rating: str = ""
    would_return: bool | None = None
    visited_date: str | None = None
    notes: str = ""
    links: list[str] = []


@router.post("/experiences")
def create_experience(body: ExperienceCreate) -> dict:
    known_names = [e["name"] for e in get_store().all()]
    name = canonicalize_name(body.name, known_names)
    folder, slug = get_store().write(
        name, body.city, body.kind, body.rating, body.would_return, body.visited_date, body.notes, body.links
    )
    return {"name": name, "slug": slug, "folder": folder}


@router.get("/experiences")
def list_experiences(city: str | None = None) -> list[dict]:
    store = get_store()
    return store.by_city(city) if city else store.all()
