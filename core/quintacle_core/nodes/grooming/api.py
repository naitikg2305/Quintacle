from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from ...graph_capture import grooming_item_note_id, safe_entry_graph_links
from ..journal.normalize import canonicalize_name
from .llm import resolve_grooming_routine, suggest_grooming_routine
from .store import GroomingItemStore, GroomingRoutineStore

router = APIRouter(prefix="/grooming", tags=["grooming"])
_item_store: GroomingItemStore | None = None
_routine_store: GroomingRoutineStore | None = None


def init_store(kb_root) -> None:
    global _item_store, _routine_store
    _item_store = GroomingItemStore(kb_root)
    _routine_store = GroomingRoutineStore(kb_root)


def get_item_store() -> GroomingItemStore:
    if _item_store is None:
        raise RuntimeError("grooming store not initialized — call init_store() first")
    return _item_store


def get_routine_store() -> GroomingRoutineStore:
    if _routine_store is None:
        raise RuntimeError("grooming store not initialized — call init_store() first")
    return _routine_store


@router.post("/items")
async def create_item(
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    known_names = [i["name"] for i in get_item_store().all()]
    resolved_name = canonicalize_name(name, known_names)
    asset_paths = []
    for f in files:
        data = await f.read()
        asset_paths.append(get_item_store().save_asset(f.filename or "item", data))
    slug = get_item_store().write(resolved_name, category, description, asset_paths)
    # Write rule (graph_capture): same deal as wardrobe items — the
    # description is prose that can genuinely name a person/experience, so it
    # gets the keyword linker; routine->item steps stay structural.
    safe_entry_graph_links(grooming_item_note_id(resolved_name), "note", f"{resolved_name}\n{description}")
    return {
        "name": resolved_name,
        "slug": slug,
        "category": category,
        "description": description,
        "assets": asset_paths,
    }


@router.get("/items")
def list_items() -> list[dict]:
    return get_item_store().all()


@router.get("/asset")
def get_item_asset(path: str) -> Response:
    data = get_item_store().read_asset(path)
    if data is None:
        raise HTTPException(404, "asset not found")
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime_type or "application/octet-stream")


class RoutineCreate(BaseModel):
    name: str
    steps: list[str]


@router.post("/routines")
def create_routine(body: RoutineCreate) -> dict:
    known_names = [r["name"] for r in get_routine_store().all()]
    name = canonicalize_name(body.name, known_names)
    known_item_names = [i["name"] for i in get_item_store().all()]
    steps = [canonicalize_name(s, known_item_names) for s in body.steps]
    get_routine_store().write(name, steps)
    return {"name": name, "steps": steps}


@router.get("/routines")
def list_routines() -> list[dict]:
    return get_routine_store().all()


class SuggestRoutineRequest(BaseModel):
    description: str


@router.post("/routines/suggest")
def suggest_routine_endpoint(body: SuggestRoutineRequest) -> dict:
    """AI proposes ordered steps for a routine from a freeform description;
    resolve_grooming_routine() then deterministically matches each against
    the real product library. Never writes."""
    known = get_item_store().all()
    suggestion = suggest_grooming_routine(body.description, known)
    return resolve_grooming_routine(suggestion, known)
