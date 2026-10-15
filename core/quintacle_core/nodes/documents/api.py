from __future__ import annotations

from datetime import date
from typing import Callable

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
import mimetypes

from ...graph_capture import document_note_id, safe_entry_graph_links
from ..journal.normalize import canonicalize_name
from ..schedule.models import Todo
from ..schedule.store import TodoStore
from .store import DocumentStore

router = APIRouter(prefix="/documents", tags=["documents"])
_store: DocumentStore | None = None
_get_schedule_store: Callable[[], TodoStore] | None = None


def init_store(kb_root, get_schedule_store: Callable[[], TodoStore]) -> None:
    global _store, _get_schedule_store
    _store = DocumentStore(kb_root)
    _get_schedule_store = get_schedule_store


def get_store() -> DocumentStore:
    if _store is None:
        raise RuntimeError("document store not initialized — call init_store() first")
    return _store


@router.get("")
def list_documents() -> list[dict]:
    return get_store().all()


@router.get("/asset")
def get_asset(path: str) -> Response:
    data = get_store().read_asset(path)
    if data is None:
        raise HTTPException(404, "asset not found")
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime_type or "application/octet-stream")


@router.post("")
async def create_document(
    name: str = Form(...),
    doc_type: str = Form(""),
    issued_date: str = Form(""),
    expiry_date: str = Form(""),
    status: str = Form("active"),
    notes: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """Creates or updates a document. When this is a genuinely NEW document
    (not a redefinition of an existing one) and it has an expiry_date, a
    matching Todo is auto-created — deadline-based documents (a lease
    renewal, OPT renewal) land on your actual calendar, not just sitting in
    a note you might not reread. Only fires on first creation, not on every
    edit, so redefining an existing document never spawns duplicate todos.
    `files` covers a multi-page scan (lease, insurance policy) — every page
    kept, not just a fixed front/back pair."""
    store = get_store()
    known_names = [d["name"] for d in store.all()]
    resolved_name = canonicalize_name(name, known_names)
    is_new = store.get(resolved_name) is None

    asset_paths = []
    for f in files:
        data = await f.read()
        asset_paths.append(store.save_asset(f.filename or "document", data))

    slug = store.write(
        resolved_name,
        doc_type=doc_type,
        issued_date=issued_date or None,
        expiry_date=expiry_date or None,
        status=status,
        notes=notes,
        assets=asset_paths,
    )

    # Write rule (graph_capture): a document's notes can name a person ("lease
    # cosigned with Sam") or an experience — keyword-link them. Dates/status
    # are structured fields and deliberately never keyword-matched.
    safe_entry_graph_links(document_note_id(resolved_name), "note", f"{resolved_name}\n{notes}")

    todo_created = False
    if is_new and expiry_date:
        _get_schedule_store().save(
            Todo(
                title=f"Renew: {resolved_name}",
                due_date=date.fromisoformat(expiry_date),
                notes=f"Auto-created from Document Vault entry: {resolved_name}",
            )
        )
        todo_created = True

    return {"name": resolved_name, "slug": slug, "assets": asset_paths, "todo_created": todo_created}
