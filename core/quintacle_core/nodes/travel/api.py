from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...graph import get_graph_store, link_new_entry, sync_frontmatter_links
from ...graph_capture import emerge_places_for_text, mention_candidates
from ...markdown_paths import resolve_nested, slugify
from ...place_graph import link_experience_places, link_note_places
from ...retrieval import safe_index_experience, safe_index_note, safe_remove_node
from . import states as travel_states
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
    candidates = mention_candidates(get_people_store().all(), get_store().all())
    text = f"{name}\n{body.notes}\n{' '.join(body.links)}"
    link_new_entry(exp_id, "experience", text, candidates, source_of_edge="structural")

    # This experience's city just joined (or reinforced) the place lexicon
    # (graph_capture) — and the experience itself counts as a mention of its
    # own city, so this may be the write that pushes the city over
    # PLACE_EMERGENCE_THRESHOLD. Additive, never blocking.
    try:
        emerge_places_for_text(body.city)
    except Exception:
        pass

    # Retrieval index (retrieval.py) — failure-isolated, never fails the save.
    safe_index_experience(name, folder, slug, body.city, body.kind, body.rating, body.notes)
    # 2026-11-05 (place_graph.py): experience → its city (→ country → continent).
    link_experience_places(kb_store, {"name": name, "folder": folder, "slug": slug, "city": body.city})

    return {"name": name, "slug": slug, "folder": folder}


@router.get("/experiences")
def list_experiences(city: str | None = None) -> list[dict]:
    store = get_store()
    return store.by_city(city) if city else store.all()


# --- 2026-11-05: Planned trips + Bucket list (nodes/travel/states.py) -------
# Both are plain KB notes; these routes only read/move/create/delete files
# and keep the retrieval index + graph node ids in step, the way kb/api.py's
# own writes do. Direct user actions from a form (like create_experience) —
# no propose/review step.


def _kb() -> KBStore:
    return KBStore(get_store().kb_root)


def _rekey_graph(old_id: str, new_id: str) -> None:
    """A moved note's node id changes (note:<folder>/<slug>) — re-point every
    edge touching it, keeping kind/source_of_edge. Never fails the move."""
    try:
        gs = get_graph_store()
        rows = gs.conn.execute(
            "SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (old_id, old_id)
        ).fetchall()
        for row in rows:
            source = new_id if row["source_id"] == old_id else row["source_id"]
            target = new_id if row["target_id"] == old_id else row["target_id"]
            gs.remove_edge(row["id"])
            gs.create_edge(source, target, row["kind"], row["source_of_edge"])
    except Exception:
        pass


def _drop_graph_node(node_id: str) -> None:
    try:
        get_graph_store().remove_edges_for(node_id)
    except Exception:
        pass


@router.get("/planned")
def list_planned() -> list[dict]:
    return travel_states.list_planned(_kb())


@router.get("/unsorted")
def list_unsorted() -> list[dict]:
    return travel_states.list_unsorted(_kb())


class PlannedMove(BaseModel):
    folder: str
    slug: str
    group: str = ""


@router.post("/planned/move")
def move_planned(body: PlannedMove) -> dict:
    kb = _kb()
    try:
        folder, slug = travel_states.move_note(kb, body.folder, body.slug, body.group or "")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except travel_states.MoveConflict as exc:
        raise HTTPException(409, str(exc))
    old_folder = str(resolve_nested(kb.root, body.folder).relative_to(kb.root)).replace("\\", "/")
    old_id, new_id = f"note:{old_folder}/{slugify(body.slug)}", f"note:{folder}/{slug}"
    if old_id != new_id:
        _rekey_graph(old_id, new_id)
        safe_remove_node(old_id)
        full = kb.read_full(folder, slug) or {}
        safe_index_note(folder, slug, full.get("title") or slug, full.get("content") or "")
    # 2026-11-05 (place_graph.py): a trip now in Planned links to its destinations.
    link_note_places(kb, folder, slug)
    return {"folder": folder, "slug": slug}


@router.get("/bucket")
def list_bucket() -> list[dict]:
    return travel_states.list_bucket(_kb(), get_store().all())


class BucketCreate(BaseModel):
    place: str
    notes: str = ""


@router.post("/bucket")
def create_bucket(body: BucketCreate) -> dict:
    place = body.place.strip()
    if not place:
        raise HTTPException(400, "place is required")
    kb = _kb()
    if travel_states.bucket_exists(kb, place):
        raise HTTPException(409, f"{place!r} is already on the bucket list")
    notes = body.notes or ""
    folder, slug = travel_states.create_bucket(kb, place, notes)
    # Same post-write hooks as POST /kb/entries — graph links + retrieval
    # index, both failure-isolated. Lazy import: kb.api imports this module.
    try:
        from ..kb.api import _sync_note_graph_links

        _sync_note_graph_links(f"note:{folder}/{slug}", place, notes, None)
    except Exception:
        pass
    safe_index_note(folder, slug, place, notes)
    return travel_states.bucket_row(kb, slug, get_store().all())


@router.delete("/bucket/{slug}")
def delete_bucket(slug: str) -> dict:
    kb = _kb()
    path = kb.entry_path(travel_states.BUCKET, slug)
    if not path.exists():
        raise HTTPException(404, f"no bucket-list place {slug!r}")
    folder = str(path.parent.relative_to(kb.root)).replace("\\", "/")
    path.unlink()
    node_id = f"note:{folder}/{path.stem}"
    _drop_graph_node(node_id)
    safe_remove_node(node_id)
    return {"deleted": path.stem}
