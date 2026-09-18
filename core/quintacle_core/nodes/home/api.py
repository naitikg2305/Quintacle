from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from .store import HomeItemStore, ResidenceStore

router = APIRouter(prefix="/home", tags=["home"])
_residence_store: ResidenceStore | None = None
_item_store: HomeItemStore | None = None


def init_store(kb_root) -> None:
    global _residence_store, _item_store
    _residence_store = ResidenceStore(kb_root)
    _item_store = HomeItemStore(kb_root)


def get_residence_store() -> ResidenceStore:
    if _residence_store is None:
        raise RuntimeError("home store not initialized — call init_store() first")
    return _residence_store


def get_item_store() -> HomeItemStore:
    if _item_store is None:
        raise RuntimeError("home store not initialized — call init_store() first")
    return _item_store


def resolve_residence(residence_name: str) -> dict | None:
    """Deterministic, no AI: matches an explicitly-named residence via the
    same fuzzy-match safety net used everywhere else; falls back to the
    CURRENT residence (no moved_out date) when no name is given — so most
    home-item drops need zero residence bookkeeping day to day."""
    residences = get_residence_store().all()
    if residence_name.strip():
        known_names = [r["name"] for r in residences]
        matched = canonicalize_name(residence_name, known_names)
        found = next((r for r in residences if r["name"] == matched), None)
        if found is not None:
            return found
    active = [r for r in residences if not r.get("moved_out")]
    if active:
        return active[-1]
    return residences[-1] if residences else None


class ResidenceCreate(BaseModel):
    name: str
    city: str
    address: str = ""
    moved_in: str | None = None
    moved_out: str | None = None
    notes: str = ""


@router.post("/residences")
def create_residence(body: ResidenceCreate) -> dict:
    known_names = [r["name"] for r in get_residence_store().all()]
    name = canonicalize_name(body.name, known_names)
    folder, slug = get_residence_store().write(name, body.city, body.address, body.moved_in, body.moved_out, body.notes)
    return {"name": name, "slug": slug, "folder": folder}


@router.get("/residences")
def list_residences() -> list[dict]:
    return get_residence_store().all()


@router.post("/items")
async def create_item(
    name: str = Form(...),
    residence_name: str = Form(""),
    category: str = Form(""),
    location: str = Form(""),
    purchase_price: float | None = Form(None),
    purchase_date: str = Form(""),
    notes: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    residence = resolve_residence(residence_name)
    if residence is None:
        raise HTTPException(400, "no residence exists yet — add one first (POST /home/residences)")

    asset_paths = []
    for f in files:
        data = await f.read()
        asset_paths.append(get_item_store().save_asset(residence["folder"], f.filename or "item", data))

    slug = get_item_store().write(
        residence["folder"],
        name,
        category,
        location,
        purchase_price,
        purchase_date or None,
        notes,
        asset_paths,
    )
    return {"name": name, "slug": slug, "residence": residence["name"], "assets": asset_paths}


@router.get("/items")
def list_items(residence_name: str) -> list[dict]:
    residence = resolve_residence(residence_name)
    if residence is None:
        raise HTTPException(404, "residence not found")
    return get_item_store().all(residence["folder"])


@router.get("/asset")
def get_asset(residence_folder: str, path: str) -> Response:
    data = get_item_store().read_asset(residence_folder, path)
    if data is None:
        raise HTTPException(404, "asset not found")
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime_type or "application/octet-stream")
