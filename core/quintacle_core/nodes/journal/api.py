from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, HTTPException

from ... import llm_dispatch
from ...graph_capture import safe_journal_graph_links
from ...retrieval import safe_index_journal
from ...nodes.kb.chat import OllamaError
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
    # The write rule (docs/graph-model.md), previously missing here entirely:
    # journal text saved through the app (or Drop's "save to journal") now
    # creates the same mentions_person/at_location edges — and the same
    # place-emergence check — as MCP journal_append, via the one shared
    # helper. Additive, never blocking: a linking failure can't lose the save.
    safe_journal_graph_links(for_date, content)
    # Retrieval index (retrieval.py): re-index the WHOLE day (appends stack),
    # failure-isolated — an indexing error never loses the save.
    safe_index_journal(for_date, get_store().load(for_date) or "")
    return {"date": for_date.isoformat(), "saved": True}


@router.get("/{for_date}")
def get_journal(for_date: date) -> dict:
    return {"date": for_date.isoformat(), "content": get_store().load(for_date)}


@router.post("/{for_date}/parse")
def parse_journal(for_date: date, content: str = Body(..., media_type="text/plain"), provider: str | None = None) -> dict:
    """Proposes activity-log entries from a raw dump — never writes them.
    The frontend shows these for review/edit; committing them is a separate
    call to POST /logs/activities per entry (see Approval before write).
    `provider` (local|cloud|auto) overrides the ingest default for this one
    parse — the frontend's "redo with cloud" re-sends the SAME raw text with
    provider=cloud (a step back, never re-prompting over local output).
    `provider_used` in the response is who actually answered ("mixed" when
    auto fell back mid-request)."""
    used = llm_dispatch.collect_providers()
    known_meals = [dict(row) for row in get_logs_repo().list_meals()]
    known_routines = get_logs_repo().list_routines()
    try:
        entries = [
            e.model_dump()
            for e in parse_journal_dump(
                content, known_meals, reference_date=for_date, known_routines=known_routines, provider=provider
            )
        ]
    except (OllamaError, ValueError) as e:
        # provider=local with the daemon down / model missing / schema-invalid
        # output, or a bogus provider value — readable, not a 500.
        raise HTTPException(400, str(e))

    # Deterministic pass, not AI: correct case/hyphen/spacing drift against
    # names already established in the logs, so "pull-ups" and "Pull Ups"
    # don't fragment into separate things trend tracking can't reconcile.
    canonicalize_entries(entries, get_log_store())

    try:
        return {"entries": _additive_checks(entries, content, for_date, provider), "provider_used": llm_dispatch.summarize_providers(used)}
    except OllamaError as e:
        raise HTTPException(400, str(e))


def _additive_checks(entries: list[dict], content: str, for_date: date, provider: str | None) -> list[dict]:
    # Same "propose everything plausible" additive checks /drop runs — a
    # journal entry is free text, never a file, so this is the lean
    # text-only version (no photo-archival branch, that's Drop-specific).
    # A journal dump is exactly where "dinner with Laura, she's got a big
    # trip coming up" naturally gets written, so this can't be dropped just
    # because Journal is its own page again.
    exp_estimate = maybe_structure_experience(content, provider=provider)
    exp_links: list[str] = []
    if exp_estimate is not None:
        entries.append({"type": "experience_entry", **exp_estimate.model_dump(exclude={"is_experience"}), "links": exp_links})

    known_people = [p["name"] for p in get_people_store().all()]
    person_estimate = maybe_structure_person_mention(content, known_people, for_date, provider=provider)
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
                # Same cross-reference as /drop's propose_drop — the real
                # typed edge (kind="mentions_person") is created at commit
                # time by graph.link_new_entry once both sides have a real id.
                if exp_estimate is not None:
                    exp_links.append(matched_name)
                entries.append(
                    {
                        "type": "kb_entry",
                        "folder": f"{resolved['folder']}/Mentions",
                        "title": f"{matched_name} — {for_date.isoformat()}",
                        "content": person_estimate.notes,
                        "links": [exp_estimate.suggested_name] if exp_estimate is not None else [],
                    }
                )

    return entries
