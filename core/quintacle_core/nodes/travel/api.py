from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...graph import link_new_entry, sync_frontmatter_links
from ..journal.api import get_store as get_journal_store
from ..journal.normalize import canonicalize_name
from ..kb.store import KBStore
from ..people.api import get_store as get_people_store
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
    exp_id = f"experience:{folder}/{slug}"

    # Stage 1's materialize-at-write-time fix for /graph — same note/journal
    # pool it used to fuzzy-match against on every read, resolved once here
    # instead. `KBStore(...)` is constructed directly (not via kb.api) to
    # avoid a kb.api <-> travel.api import cycle — cheap, stateless, just a
    # path wrapper, same root kb/api.py's own singleton points at.
    kb_store = KBStore(get_store().kb_root)
    note_id_by_title = {n["title"]: f"note:{n['folder']}/{n['slug']}" for n in kb_store.notes_index()}
    journal_id_by_date = {d.isoformat(): f"journal:{d.isoformat()}" for d in get_journal_store().list_dates()}
    experience_id_by_name = {e["name"]: f"experience:{e['folder']}/{e['slug']}" for e in get_store().all()}
    title_lookup = {**note_id_by_title, **journal_id_by_date, **experience_id_by_name}
    resolved_titles = [canonicalize_name(t, list(title_lookup)) for t in body.links]
    sync_frontmatter_links(exp_id, resolved_titles, title_lookup)

    # The concrete retrofit from docs/graph-model.md: an experience and a
    # person detected from the same drop (api.py's propose_drop) used to be
    # created side by side with no connection at all. Now that the person's
    # name is a stated `links` hint (see propose_drop), this deterministic
    # keyword match reliably finds it and creates a real typed edge.
    person_candidates = [
        {"id": f"note:{p['folder']}/profile", "type": "person", "title": p["name"]} for p in get_people_store().all()
    ]
    text = f"{name}\n{body.notes}\n{' '.join(body.links)}"
    link_new_entry(exp_id, "experience", text, person_candidates, source_of_edge="structural")

    return {"name": name, "slug": slug, "folder": folder}


@router.get("/experiences")
def list_experiences(city: str | None = None) -> list[dict]:
    store = get_store()
    return store.by_city(city) if city else store.all()
