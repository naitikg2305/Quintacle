from __future__ import annotations

import json
import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from .llm import resolve_outfit, suggest_outfit
from .store import OutfitStore, WardrobeItemStore

router = APIRouter(prefix="/wardrobe", tags=["wardrobe"])
_item_store: WardrobeItemStore | None = None
_outfit_store: OutfitStore | None = None


def init_store(kb_root) -> None:
    global _item_store, _outfit_store
    _item_store = WardrobeItemStore(kb_root)
    _outfit_store = OutfitStore(kb_root)


def get_item_store() -> WardrobeItemStore:
    if _item_store is None:
        raise RuntimeError("wardrobe store not initialized — call init_store() first")
    return _item_store


def get_outfit_store() -> OutfitStore:
    if _outfit_store is None:
        raise RuntimeError("wardrobe store not initialized — call init_store() first")
    return _outfit_store


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


@router.post("/outfits")
async def create_outfit(
    name: str = Form(...),
    items: str = Form("[]"),  # JSON-encoded list[str] — items may be empty for a full-outfit photo saved as is
    file: UploadFile | None = File(None),
) -> dict:
    known_names = [o["name"] for o in get_outfit_store().all()]
    resolved_name = canonicalize_name(name, known_names)
    known_item_names = [i["name"] for i in get_item_store().all()]
    resolved_items = [canonicalize_name(i, known_item_names) for i in json.loads(items)]
    asset_path = None
    if file is not None:
        data = await file.read()
        asset_path = get_outfit_store().save_asset(file.filename or "outfit", data)
    get_outfit_store().write(resolved_name, resolved_items, asset_path)
    return {"name": resolved_name, "items": resolved_items, "asset": asset_path}


@router.get("/outfits")
def list_outfits() -> list[dict]:
    return get_outfit_store().all()


@router.get("/outfits/asset")
def get_outfit_asset(path: str) -> Response:
    data = get_outfit_store().read_asset(path)
    if data is None:
        raise HTTPException(404, "asset not found")
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime_type or "application/octet-stream")


class SuggestOutfitRequest(BaseModel):
    description: str


@router.post("/outfits/suggest")
def suggest_outfit_endpoint(body: SuggestOutfitRequest) -> dict:
    """AI proposes items for an outfit from a freeform description; resolve_outfit()
    then deterministically matches each against the real item library. Never writes."""
    known = get_item_store().all()
    suggestion = suggest_outfit(body.description, known)
    return resolve_outfit(suggestion, known)
