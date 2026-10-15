"""The "what was I doing that day" bundle — one deterministic read pulling
everything recorded on a date from every node that touches it, including the
photo notes whose EXIF date linked them to that day's journal node.

Shared by `GET /day/{for_date}` (api.py) and the MCP `day_recall` tool
(mcp_server/server.py) so both surfaces assemble the exact same bundle from
one code path. Deliberately no LLM calls anywhere in here — the calling
model (or the Day page) does the narrating, per docs/architecture.md.

Takes its stores as explicit arguments rather than reaching for any module's
globals, because the two callers initialize their stores differently (FastAPI
init_* registries vs. the MCP server's module-level stores).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from .nodes.journal.store import JournalStore
from .nodes.kb.store import KBStore, _ASSET_LINES_RE
from .nodes.logs.repository import LogsRepository
from .nodes.schedule.store import TodoStore


def entry_assets(entry: dict) -> list[str]:
    """EVERY asset path a read_full() entry carries — the frontmatter
    `assets` list (structured stores) plus the body's trailing
    [asset](...) lines (drop-written photo notes), de-duplicated in order.
    Same union list_entries_meta() builds for thumbnails."""
    body_assets = _ASSET_LINES_RE.findall(entry["content"])
    return [*entry["assets"], *(a for a in body_assets if a not in entry["assets"])]


def _description_of(content: str) -> str:
    """A note's body as recall text: the drop-time vision description —
    minus the [asset](...) plumbing lines and the leading `# title` heading
    (the title travels as its own field)."""
    lines = [l for l in content.split("\n") if not _ASSET_LINES_RE.match(l.strip())]
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def day_photos(for_date: date, kb_store: KBStore, edges_conn: sqlite3.Connection) -> list[dict]:
    """Every KB note linked to `journal:<date>` — one indexed query on the
    materialized `edges` table (idx_edges_target_id; see graph.py), never a
    KB walk. A linked note with no image assets still counts (a text note
    about the day is relevant recall); `assets` just accurately reflects
    what's there."""
    rows = edges_conn.execute(
        "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = 'on_day' AND source_type = 'note'",
        (f"journal:{for_date.isoformat()}",),
    ).fetchall()
    photos: list[dict] = []
    for note_id in sorted(row["source_id"] for row in rows):
        folder, _, slug = note_id.partition(":")[2].rpartition("/")
        entry = kb_store.read_full(folder, slug)
        if entry is None:
            continue  # a stale edge whose note was deleted — skip, don't 500
        photos.append(
            {
                "folder": folder,
                "slug": slug,
                "title": entry["title"],
                "description": _description_of(entry["content"]),
                "assets": entry_assets(entry),
            }
        )
    return photos


def build_day_bundle(
    for_date: date,
    *,
    journal_store: JournalStore,
    todo_store: TodoStore,
    logs_repo: LogsRepository,
    kb_store: KBStore,
    edges_conn: sqlite3.Connection,
) -> dict:
    """Calendar B: what actually happened on a given date, pulled
    deterministically from every node that touches it — architecture.md's
    March-13 example, generalized — plus the day's linked photo notes."""
    todos = todo_store.list()
    todos_due = [t for t in todos if t.due_date == for_date]
    # Completed on THIS day (completed_at, not due_date) — the Action view's
    # record of what actually got done; see schedule/models.py.
    todos_completed = sorted(
        (t for t in todos if t.done and t.completed_at and t.completed_at.date() == for_date),
        key=lambda t: t.completed_at,
    )
    return {
        "date": for_date.isoformat(),
        "journal": journal_store.load(for_date),
        "todos_due": [t.model_dump(mode="json") for t in todos_due],
        "todos_completed": [t.model_dump(mode="json") for t in todos_completed],
        "activities": [dict(row) for row in logs_repo.activities_for_date(for_date)],
        "exercise": [
            {**dict(row), "sets": json.loads(row["sets_json"] or "[]")}
            for row in logs_repo.exercise_for_date(for_date)
        ],
        "food": {
            "entries": [dict(row) for row in logs_repo.food_log_for_date(for_date)],
            "totals": dict(logs_repo.daily_totals(for_date)),
        },
        "body_stats": [dict(row) for row in logs_repo.body_stats_for_date(for_date)],
        "substances": [dict(row) for row in logs_repo.substances_for_date(for_date)],
        "expenses": [dict(row) for row in logs_repo.expenses_for_date(for_date)],
        "photos": day_photos(for_date, kb_store, edges_conn),
    }
