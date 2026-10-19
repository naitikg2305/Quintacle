"""One idempotent pass that indexes everything already in the store —
`python -m quintacle_core.retrieval_backfill` (QUINTACLE_DATA_DIR decides
the tree, same convention as api.py; sandbox it for experiments).

Walks: KB notes (person profiles indexed as `person`, Places/ notes as
`place`, experience files under their `experience:` id, `conversations/`
skipped by prefix), journal days, todos, every SQLite log table (expenses,
food, exercise, activities, substances, body stats), the meal/ingredient/
routine preset libraries, and event nodes referenced by the edges table.
The Vault is never touched — it lives outside kb/ and nothing here walks
anything but kb/, journal/, schedule/ and quintacle.db.

Summaries: structured rows are computed in code; prose nodes go through
retrieval.prose_summary (LOCAL model when reachable, deterministic first-
line fallback otherwise — never cloud, never blocking). Embeddings are
attempted per node by the index itself and silently skipped when the
optional vector lane (sqlite-vec + Ollama) is unavailable.

Idempotent: index_node is an upsert keyed on the graph id, so re-running
converges instead of duplicating. Prints per-type counts when run as a
module."""
from __future__ import annotations

import os
from pathlib import Path

from . import db
from .graph import init_graph_store
from .markdown_paths import slugify
from .nodes.journal.store import JournalStore
from .nodes.kb.store import KBStore
from .nodes.logs.log_store import LOG_HOMES, LogFileStore
from .nodes.logs.repository import LogsRepository
from .nodes.people.store import PersonStore
from .nodes.schedule.store import TodoStore
from .nodes.travel.store import ExperienceStore
from .retrieval import (
    init_retrieval_index,
    safe_index_event,
    safe_index_journal,
    safe_index_log_row,
    safe_index_note,
    safe_index_person,
    safe_index_routine,
    safe_index_todo,
    safe_index_experience,
)

def _slug_path(folder: str) -> str:
    return "/".join(slugify(seg) for seg in folder.split("/"))


def _log_mirror_folders() -> set[str]:
    """The slugified KB folders that are really log/preset MIRRORS of SQLite
    rows (log_store.py) — those rows are indexed under their canonical ids
    (expense:<int>, meal:<int>, routine:<name>, ...), so indexing the
    markdown twins as note: ids would duplicate them (reference, never
    duplicate)."""
    skip = {f"{_slug_path(home)}/logs" for home in LOG_HOMES.values()}
    skip.add(f"{_slug_path(LOG_HOMES['food'])}/presets")
    skip.add(f"{_slug_path(LOG_HOMES['food'])}/ingredients")
    skip.add(f"{_slug_path(LOG_HOMES['exercise'])}/routines")
    return skip


# kind prefix -> its SQLite table (ids are the table's integer PKs).
_LOG_TABLES = {
    "expense": "expense_log",
    "food": "food_log",
    "exercise": "exercise_sets",
    "activity": "activity_log",
    "substance": "substance_log",
    "body_stat": "body_stats",
    "meal": "meals",
    "ingredient": "ingredients",
    "income": "income_log",
}


def run_backfill(data_dir: Path) -> dict[str, int]:
    """Indexes the whole store under `data_dir`; returns per-type counts
    (the index's own totals, since the pass is an upsert)."""
    data_dir = Path(data_dir)
    kb_root = data_dir / "kb"
    conn = db.connect(data_dir / "quintacle.db")
    init_graph_store(data_dir, conn)  # events + the retrieve-time neighbor labels read the edges table
    index = init_retrieval_index(conn)

    kb = KBStore(kb_root)
    people = PersonStore(kb_root).all()
    experiences = ExperienceStore(kb_root).all()
    experience_paths = {(e["folder"], e["slug"]) for e in experiences}
    person_folders = {p["folder"] for p in people}

    # KB notes — skipping files that are really something else: experience
    # files (indexed under experience: below), person profiles (indexed as
    # person below, same note: id), log/preset markdown mirrors of SQLite
    # rows (indexed under their canonical row ids below), and
    # conversations/ by prefix (also enforced again inside index_node —
    # defense in depth).
    mirror_folders = _log_mirror_folders()
    for n in kb.graph_entries():
        folder, slug = n["folder"], n["slug"]
        if folder == "conversations" or folder.startswith("conversations/"):
            continue
        if any(folder == m or folder.startswith(m + "/") for m in mirror_folders):
            continue
        if (folder, slug) in experience_paths:
            continue
        if slug == "profile" and folder in person_folders:
            continue
        safe_index_note(folder, slug, n["title"], kb.read(folder, slug) or "")

    journal = JournalStore(data_dir / "journal")
    for d in journal.list_dates():
        safe_index_journal(d, journal.load(d) or "")

    for todo in TodoStore(data_dir / "schedule" / "todos").list():
        safe_index_todo(todo)

    for p in people:
        safe_index_person(p["name"], p["folder"], p.get("category") or "", p.get("how_met") or "", p.get("notes") or "")

    for e in experiences:
        safe_index_experience(
            e["name"], e["folder"], e["slug"], e.get("city") or "", e.get("kind") or "", str(e.get("rating") or ""), e.get("notes") or ""
        )

    for kind, table in _LOG_TABLES.items():
        for row in conn.execute(f"SELECT id FROM {table}"):  # noqa: S608 — table names from the fixed map above
            safe_index_log_row(f"{kind}:{row['id']}")

    repo = LogsRepository(conn, LogFileStore(kb_root))
    for routine in repo.list_routines():
        safe_index_routine(routine["name"], routine.get("exercises") or [])

    # Event nodes exist only as edge endpoints (graph_capture.link_event) —
    # recover each one's member count and linked day from the edges table.
    event_members = {
        row["target_id"]: row["n"]
        for row in conn.execute(
            "SELECT target_id, COUNT(*) AS n FROM edges WHERE kind = 'part_of' AND target_id LIKE 'event:%' GROUP BY target_id"
        )
    }
    event_dates = {
        row["source_id"]: row["target_id"].partition(":")[2]
        for row in conn.execute(
            "SELECT source_id, target_id FROM edges WHERE kind = 'on_day' AND source_id LIKE 'event:%'"
        )
    }
    from datetime import date as _date

    for event_id, n in event_members.items():
        iso = event_dates.get(event_id)
        safe_index_event(event_id, n, _date.fromisoformat(iso) if iso else None)

    return index.counts_by_type()


def main() -> None:
    data_dir = Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    print(f"backfilling retrieval index under {data_dir}")
    counts = run_backfill(data_dir)
    for node_type, n in sorted(counts.items()):
        print(f"  {node_type:>12}: {n}")
    print(f"  {'total':>12}: {sum(counts.values())}")


if __name__ == "__main__":
    main()
