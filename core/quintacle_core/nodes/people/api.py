from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...graph import link_new_entry
from ...graph_capture import mention_candidates
from ..journal.normalize import canonicalize_name
from ..travel.store import ExperienceStore
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
    links: list[str] = []


@router.post("")
def create_person(body: PersonCreate) -> dict:
    known_names = [p["name"] for p in get_store().all()]
    resolved_name = canonicalize_name(body.name, known_names)
    folder, slug = get_store().write(resolved_name, body.category, body.how_met, body.met_date, body.notes, body.links)
    person_id = f"note:{folder}/profile"

    # Same retrofit as travel/api.py's create_experience, the other side of
    # it: an experience mentioned alongside this person (e.g. propose_drop's
    # `links` hint) gets a real typed edge instead of being lost once this
    # person is saved independently of the experience.
    # Shared candidate list (graph_capture): experiences this person was met
    # at AND other tracked people their notes mention ("Laura's brother") —
    # the self-candidate is skipped by link_new_entry's own id check.
    candidates = mention_candidates(get_store().all(), ExperienceStore(get_store().kb_root).all())
    text = f"{resolved_name}\n{body.notes}\n{' '.join(body.links)}"
    link_new_entry(person_id, "person", text, candidates, source_of_edge="structural")

    return {"name": resolved_name, "slug": slug, "folder": folder}


@router.get("")
def list_people() -> list[dict]:
    return get_store().all()
