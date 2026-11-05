"""GET /knowledge + GET /knowledge/note — the owner-facing Knowledge page
(see page.py). Read-only, deterministic, no model calls."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..kb.api import get_store as get_kb_store
from .page import knowledge_note, knowledge_page

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("")
def get_knowledge(q: str | None = None, topic: str | None = None, tag: str | None = None) -> dict:
    return knowledge_page(get_kb_store(), q=q, topic=topic, tag=tag)


@router.get("/note")
def get_knowledge_note(folder: str, slug: str) -> dict:
    note = knowledge_note(get_kb_store(), folder, slug)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note
