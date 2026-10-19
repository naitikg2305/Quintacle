from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...graph import link_new_entry, reverse_lookup
from ...graph_capture import mention_candidates
from ...retrieval import safe_index_person
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

    # Retrieval index (retrieval.py) — failure-isolated, never fails the save.
    safe_index_person(resolved_name, folder, body.category, body.how_met, body.notes)

    return {"name": resolved_name, "slug": slug, "folder": folder}


@router.get("")
def list_people() -> list[dict]:
    return get_store().all()


@router.get("/{name}/appearances")
def person_appearances(name: str) -> dict:
    """Where this person appears in photos — COMPUTED from the graph
    (reverse_lookup on their profile id, pictured_with edges only), never
    written into their file. That's the no-duplication contract: the photo
    note and the journal line are the only records; the person page (and
    any LLM walking the graph) derives appearances from the edges."""
    person = get_store().find(name)
    if person is None:
        raise HTTPException(404, "person not found")
    person_id = f"note:{person['folder']}/profile"

    photos: list[dict] = []
    dates: set[str] = set()
    seen_notes: set[str] = set()
    for edge in reverse_lookup(person_id):
        if edge["kind"] != "pictured_with":
            continue
        source = edge["source_id"]
        if source.startswith("journal:"):
            dates.add(source.removeprefix("journal:"))
        elif source.startswith("note:") and source not in seen_notes:
            seen_notes.add(source)
            folder, _, slug = source.removeprefix("note:").rpartition("/")
            photos.append({"folder": folder, "slug": slug, "created_at": edge["created_at"]})

    # Titles read lazily from the KB (runtime import — kb.api imports this
    # module at load time, so a top-level import here would be circular).
    from ..kb.api import get_store as get_kb_store

    try:
        kb = get_kb_store()
    except RuntimeError:
        kb = None
    for photo in photos:
        content = kb.read(photo["folder"], photo["slug"]) if kb is not None else None
        photo["title"] = (content.split("\n", 1)[0].lstrip("# ").strip() if content else "") or photo["slug"]

    return {"name": person["name"], "photos": photos, "dates": sorted(dates)}
