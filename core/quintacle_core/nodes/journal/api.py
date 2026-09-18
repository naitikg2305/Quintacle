from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body

from ..logs.api import get_log_store, get_repo as get_logs_repo
from ..people.api import get_store as get_people_store
from ..people.llm import maybe_structure_person_mention
from ..travel.llm import maybe_structure_experience
from .llm import parse_journal_dump
from .normalize import canonicalize_entries, canonicalize_name
from .store import JournalStore

router = APIRouter(prefix="/journal", tags=["journal"])
_store: JournalStore | None = None


def init_store(root) -> None:
    global _store
    _store = JournalStore(root)


def get_store() -> JournalStore:
    if _store is None:
        raise RuntimeError("journal store not initialized — call init_store() first")
    return _store


@router.post("/{for_date}")
def save_journal(for_date: date, content: str = Body(..., media_type="text/plain")) -> dict:
    get_store().save(for_date, content)
    return {"date": for_date.isoformat(), "saved": True}


@router.get("/{for_date}")
def get_journal(for_date: date) -> dict:
    return {"date": for_date.isoformat(), "content": get_store().load(for_date)}


@router.post("/{for_date}/parse")
def parse_journal(for_date: date, content: str = Body(..., media_type="text/plain")) -> list[dict]:
    """Proposes activity-log entries from a raw dump — never writes them.
    The frontend shows these for review/edit; committing them is a separate
    call to POST /logs/activities per entry (see Approval before write)."""
    known_meals = [dict(row) for row in get_logs_repo().list_meals()]
    known_routines = get_logs_repo().list_routines()
    entries = [
        e.model_dump()
        for e in parse_journal_dump(content, known_meals, reference_date=for_date, known_routines=known_routines)
    ]

    # Deterministic pass, not AI: correct case/hyphen/spacing drift against
    # names already established in the logs, so "pull-ups" and "Pull Ups"
    # don't fragment into separate things trend tracking can't reconcile.
    canonicalize_entries(entries, get_log_store())

    # Same "propose everything plausible" additive checks /drop runs — a
    # journal entry is free text, never a file, so this is the lean
    # text-only version (no photo-archival branch, that's Drop-specific).
    # A journal dump is exactly where "dinner with Laura, she's got a big
    # trip coming up" naturally gets written, so this can't be dropped just
    # because Journal is its own page again.
    exp_estimate = maybe_structure_experience(content)
    if exp_estimate is not None:
        entries.append({"type": "experience_entry", **exp_estimate.model_dump(exclude={"is_experience"}), "links": []})

    known_people = [p["name"] for p in get_people_store().all()]
    person_estimate = maybe_structure_person_mention(content, known_people, for_date)
    if person_estimate is not None:
        if person_estimate.is_new_person:
            entries.append(
                {
                    "type": "person_entry",
                    "suggested_name": person_estimate.person_name,
                    "category": person_estimate.category,
                    "how_met": person_estimate.how_met,
                    "met_date": person_estimate.met_date,
                    "notes": person_estimate.notes,
                }
            )
        else:
            matched_name = canonicalize_name(person_estimate.person_name, known_people)
            resolved = get_people_store().find(matched_name)
            if resolved is not None:
                entries.append(
                    {
                        "type": "kb_entry",
                        "folder": f"{resolved['folder']}/Mentions",
                        "title": f"{matched_name} — {for_date.isoformat()}",
                        "content": person_estimate.notes,
                        "links": [],
                    }
                )

    return entries
