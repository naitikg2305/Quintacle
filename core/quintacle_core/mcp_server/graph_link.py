from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..graph import init_graph_store, link_new_entry as _engine_link, sync_frontmatter_links
from ..nodes.journal.normalize import canonicalize_name
from ..nodes.journal.store import JournalStore
from ..nodes.kb.store import KBStore
from ..nodes.people.store import PersonStore
from ..nodes.travel.store import ExperienceStore

if TYPE_CHECKING:
    from .undo import WriteSession

# The adapter between the MCP write tools and the graph engine
# (quintacle_core/graph.py). Per graph-model.md's write rule, every MCP write
# calls link_new_entry() after persisting; this module owns the glue the
# engine deliberately doesn't: gathering candidates (people, experiences),
# resolving a note's declared `links` titles the same way /kb's own commit
# path does, and staging whatever edges got created onto the write's undo
# session so undoing a push also removes its edges.

_data_dir: Path | None = None
_db_path: Path | None = None
_people_store: PersonStore | None = None
_travel_store: ExperienceStore | None = None
_journal_store: JournalStore | None = None
_kb_store: KBStore | None = None


def configure(
    data_dir: Path,
    conn: sqlite3.Connection,
    *,
    journal_store: JournalStore,
    kb_store: KBStore,
) -> None:
    """Called from server.init() — points the engine and the candidate
    sources at the same data dir every other store uses."""
    global _data_dir, _db_path, _people_store, _travel_store, _journal_store, _kb_store
    _data_dir = Path(data_dir)
    _db_path = _data_dir / "quintacle.db"
    kb_root = _data_dir / "kb"
    _people_store = PersonStore(kb_root)
    _travel_store = ExperienceStore(kb_root)
    _journal_store = journal_store
    _kb_store = kb_store
    init_graph_store(_data_dir, conn)


def _edges_dir() -> Path:
    assert _data_dir is not None
    return _data_dir / "graph" / "edges"


def link_new_entry(
    entry_type: str,
    entry_id: str,
    text: str,
    *,
    session: "WriteSession | None" = None,
    links: list[str] | None = None,
    **context: Any,
) -> list[str]:
    """Write-rule hook for MCP tools: keyword-link the just-written entry
    against known people/experiences, materialize any declared `links`
    titles into edges, and stage every edge this call created onto
    `session` so the push undoes as one unit. A write must never fail
    because the linking step broke — any error here is swallowed into "no
    edges", same "additive, never blocking" spirit as api.py's
    Experience/Person drop-router checks."""
    if _data_dir is None:
        return []
    try:
        # Dir snapshot, not the engine's return value, decides what gets
        # staged for undo: create_edge() is idempotent and re-returns an
        # existing identical edge — staging that as "new" would wrongly
        # delete a pre-existing edge on undo.
        edges_dir = _edges_dir()
        before = {p.name for p in edges_dir.glob("*.md")} if edges_dir.exists() else set()

        experiences = _travel_store.all() if _travel_store else []
        candidates = [
            {"id": f"note:{p['folder']}/profile", "type": "person", "title": p["name"]}
            for p in (_people_store.all() if _people_store else [])
        ] + [{"id": f"experience:{e['folder']}/{e['slug']}", "type": "experience", "title": e["name"]} for e in experiences]
        created = _engine_link(entry_id, entry_type, text, candidates, source_of_edge="ai_link")

        # A note's declared links (titles the client already decided on) get
        # materialized exactly like /kb/entries' own commit path does.
        if links and entry_id.startswith("note:") and _kb_store and _journal_store:
            note_id_by_title = {n["title"]: f"note:{n['folder']}/{n['slug']}" for n in _kb_store.notes_index()}
            journal_id_by_date = {d.isoformat(): f"journal:{d.isoformat()}" for d in _journal_store.list_dates()}
            experience_id_by_name = {e["name"]: f"experience:{e['folder']}/{e['slug']}" for e in experiences}
            title_lookup = {**note_id_by_title, **journal_id_by_date, **experience_id_by_name}
            resolved = [canonicalize_name(t, list(title_lookup)) for t in links]
            created += sync_frontmatter_links(entry_id, resolved, title_lookup)

        new_names = sorted(({p.name for p in edges_dir.glob("*.md")} if edges_dir.exists() else set()) - before)
        if session is not None and _db_path is not None:
            for name in new_names:
                session.stage_new_file(edges_dir / name)
                session.stage_sqlite_insert(_db_path, "edges", "id", name.removesuffix(".md"))
        return [e["id"] for e in created]
    except Exception:
        return []
