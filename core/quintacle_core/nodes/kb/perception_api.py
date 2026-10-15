"""The "who is this?" tag flow endpoint. A committed photo's unknown faces
ride back on the /kb/entries/with-asset response; the Drop page offers each
one a name (an existing person or a new one) and posts it here. Tagging is
always optional — skipping/dismissing in the UI simply never calls this.

Everything else (enrollment seam, person creation, edges, journal-line
update) lives in nodes/kb/auto_journal.tag_unknown_face — this module is
only the HTTP shape."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .auto_journal import tag_unknown_face

router = APIRouter(prefix="/perception", tags=["perception"])


class TagPhoto(BaseModel):
    folder: str
    slug: str


class TagRequest(BaseModel):
    embedding_id: str
    person_name: str
    photo: TagPhoto


@router.post("/tag")
def tag_face(body: TagRequest) -> dict:
    name = body.person_name.strip()
    if not name:
        raise HTTPException(400, "person_name is required")
    try:
        return tag_unknown_face(body.embedding_id, name, body.photo.folder, body.photo.slug)
    except LookupError:
        raise HTTPException(404, "photo entry not found")
