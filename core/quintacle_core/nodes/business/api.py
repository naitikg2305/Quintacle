"""/business — the Business Ideas board (docs/reference/frontend.md, 2026-11-05).

Deterministic reads over `Business Ideas/<Idea>/` (see ideas.py) plus two
direct-edit writes that are the owner's own explicit clicks on their own
notes (the form IS the review, same contract as Browse's field editor):
  POST /business/ideas            create a hub note (title, summary, status)
  PUT  /business/ideas/{slug}/fields   merge hub fields, no `edited` restamp
No model is called anywhere here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import clock
from ...markdown_paths import slugify
from ...retrieval import safe_index_note
from . import ideas

router = APIRouter(prefix="/business", tags=["business"])


def _kb():
    from ..kb.api import get_store  # lazy: kb.api pulls in half the app

    return get_store()


@router.get("/ideas")
def list_ideas() -> dict:
    return {"statuses": list(ideas.STATUSES), "ideas": ideas.list_ideas(_kb().root)}


@router.get("/ideas/{slug}")
def read_idea(slug: str) -> dict:
    idea = ideas.read_idea(_kb().root, slug)
    if idea is None:
        raise HTTPException(404, "idea not found")
    return idea


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = ""
    status: str = ideas.DEFAULT_STATUS
    market: str = ""
    tags: list[str] | str | None = None
    body: str = ""


@router.post("/ideas")
def create_idea(body: IdeaCreate) -> dict:
    title = body.title.strip()
    if not any(c.isascii() and c.isalnum() for c in title):
        raise HTTPException(400, "title needs at least one letter or digit")
    status = body.status.strip().lower()
    if status not in ideas.STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(ideas.STATUSES)}")
    kb = _kb()
    slug = slugify(title)
    folder = ideas.idea_dir(kb.root, slug)
    if (folder / f"{slug}.md").exists():
        raise HTTPException(409, "an idea with that name already exists")
    fields: dict = {"status": status, "created": clock.today().isoformat()}
    if body.summary.strip():
        fields["summary"] = body.summary.strip()
    if body.market.strip():
        fields["market"] = body.market.strip()
    tags = ideas.normalize_tags(body.tags)
    if tags:
        fields["tags"] = tags
    # Folder and hub share one slug -> the folder-hub pattern. An existing
    # hub-less folder (files sorted in first) is adopted, never renamed.
    folder_slug, entry_slug = kb.write(f"{ideas.ROOT_FOLDER}/{title}", title, body.body.strip(), fields=fields)
    text = "\n".join(x for x in (body.summary.strip(), body.body.strip()) if x)
    try:
        from ..kb.api import _sync_note_graph_links  # lazy, same reason as _kb()

        _sync_note_graph_links(f"note:{folder_slug}/{entry_slug}", title, text, [])
    except RuntimeError:
        pass  # a store not initialized (bare router in a test) — graph is additive
    safe_index_note(folder_slug, entry_slug, title, text)  # failure-isolated
    return ideas.read_idea(kb.root, entry_slug)


class FieldsUpdate(BaseModel):
    status: str | None = None
    summary: str | None = None
    market: str | None = None
    tags: list[str] | str | None = None


@router.put("/ideas/{slug}/fields")
def update_fields(slug: str, body: FieldsUpdate) -> dict:
    """Only keys present in the request change; an empty string (or empty
    tag list) removes that field."""
    kb = _kb()
    folder = ideas.idea_dir(kb.root, slug)
    hub_slug = folder.name
    sent = body.model_dump(exclude_unset=True)
    updates: dict = {}
    if "status" in sent:
        status = (sent["status"] or "").strip().lower()
        if status not in ideas.STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(ideas.STATUSES)}")
        updates["status"] = status
    for key in ("summary", "market"):
        if key in sent:
            value = (sent[key] or "").strip()
            updates[key] = value or None
    if "tags" in sent:
        tags = ideas.normalize_tags(sent["tags"])
        updates["tags"] = tags or None
    if not kb.set_fields(f"{ideas.ROOT_SLUG}/{hub_slug}", hub_slug, updates):
        raise HTTPException(404, "idea hub not found — create the idea first")
    return ideas.read_idea(kb.root, hub_slug)
