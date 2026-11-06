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
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .graph_capture import log_row_label
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


def _member_label(member_id: str, conn: sqlite3.Connection, kb_store: KBStore, todo_store: TodoStore) -> str:
    """One member's display label, resolved from whichever store owns it —
    log rows via graph_capture.log_row_label (the same labels /graph emits),
    note/experience ids via their KB file's title, todos via their own store.
    Deterministic, and a stale/unknown id degrades to the id itself (recall
    must list the member, not 500 on it)."""
    label = log_row_label(conn, member_id)
    if label is not None:
        return label
    node_type, _, rest = member_id.partition(":")
    if node_type in ("note", "experience"):
        folder, _, slug = rest.rpartition("/")
        entry = kb_store.read_full(folder, slug)
        if entry is not None:
            return entry["title"]
    elif node_type == "todo":
        try:
            return todo_store.load(rest).title
        except FileNotFoundError:
            pass
    elif node_type == "journal":
        return rest
    return member_id


def day_events(
    for_date: date, edges_conn: sqlite3.Connection, kb_store: KBStore, todo_store: TodoStore
) -> list[dict]:
    """Every same-event grouping linked to this day (graph_capture.link_event
    minted it at batch-Save time), each with its member ids + labels — so
    day_recall hands any LLM the day's events pre-grouped ("$14.50 Chipotle"
    the expense and the food row it was born with, together) instead of
    leaving it to re-infer which rows belong together. Two indexed edge
    queries per day/event, members sorted by id — fully deterministic."""
    event_rows = edges_conn.execute(
        "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = 'on_day' AND source_type = 'event'",
        (f"journal:{for_date.isoformat()}",),
    ).fetchall()
    events: list[dict] = []
    for event_id in sorted(row["source_id"] for row in event_rows):
        member_rows = edges_conn.execute(
            "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = 'part_of'", (event_id,)
        ).fetchall()
        events.append(
            {
                "event_id": event_id,
                "members": [
                    {"id": member_id, "label": _member_label(member_id, edges_conn, kb_store, todo_store)}
                    for member_id in sorted(row["source_id"] for row in member_rows)
                ],
            }
        )
    return events


# --- 2026-11-05: the rest of the day -----------------------------------------
# A day is assembled on demand (no per-day folder — one item can belong to a
# day, a trip and a project without being copied). These four close the gaps:
# the day's work log, income next to spending, notes saved that day (titles
# only — light), and that day's chats (topic + first line only).

WORK_LOG_FOLDER = "daily-log/work-logs"


def day_work_log(for_date: date, kb_store: KBStore) -> dict | None:
    entry = kb_store.read_full(WORK_LOG_FOLDER, f"work-log-{for_date.isoformat()}")
    if entry is None:
        return None
    return {"folder": WORK_LOG_FOLDER, "slug": f"work-log-{for_date.isoformat()}", "title": entry["title"],
            "content": _description_of(entry["content"])}


def day_notes_saved(for_date: date, kb_store: KBStore, exclude: set[tuple[str, str]]) -> list[dict]:
    """Notes whose real `edited` stamp (ET, written on every save) falls on
    this date. File mtime is a cheap pre-filter (a note edited that day has
    an mtime on/after it), so a big KB isn't fully parsed per request.
    Charters, work logs and notes already listed elsewhere are skipped."""
    day = for_date.isoformat()
    start_ts = datetime.combine(for_date, datetime.min.time()).timestamp() - 86400  # tz slack
    out: list[dict] = []
    for n in kb_store.notes_index():
        folder, slug = n["folder"], n["slug"]
        if (folder, slug) in exclude or slug.startswith("about-") or folder.startswith(WORK_LOG_FOLDER):
            continue
        try:
            if os.path.getmtime(kb_store.entry_path(folder, slug)) < start_ts:
                continue
        except OSError:
            continue
        meta = kb_store.read_meta(folder, slug) if hasattr(kb_store, "read_meta") else {}
        if str((meta or {}).get("edited", ""))[:10] != day:
            continue
        out.append({"folder": folder, "slug": slug, "title": n.get("title") or slug,
                    "private": bool((meta or {}).get("private"))})
    return sorted(out, key=lambda x: x["title"].lower())


def day_chats(for_date: date, conversations_root: Path | None) -> list[dict]:
    """Archived chats started that day: topic + the first thing you asked.
    Transcript files are named <topic>/<YYYY-MM-DD-HHMM>.md."""
    if conversations_root is None or not conversations_root.exists():
        return []
    day = for_date.isoformat()
    out = []
    for f in sorted(conversations_root.glob(f"*/{day}-*.md")):
        first = ""
        try:
            text = f.read_text(encoding="utf-8")
            body = text.split("---", 2)[-1] if text.startswith("---") else text
            m = body.split("### You", 1)
            if len(m) == 2:
                first = next((ln.strip() for ln in m[1].splitlines() if ln.strip()), "")
                first = first.lstrip("·•*-–\t ").strip()  # pasted bullets
        except OSError:
            pass
        out.append({"topic": f.parent.name.replace("-", " "), "time": f.stem[11:15], "first_message": first[:160],
                    "path": f"{f.parent.name}/{f.name}"})
    return out


def build_day_bundle(
    for_date: date,
    *,
    journal_store: JournalStore,
    todo_store: TodoStore,
    logs_repo: LogsRepository,
    kb_store: KBStore,
    edges_conn: sqlite3.Connection,
    conversations_root: Path | None = None,
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
    photos = day_photos(for_date, kb_store, edges_conn)
    income = [dict(row) for row in logs_repo.income_between(for_date, for_date)]
    earned = sum(float(r.get("amount") or 0) for r in income)
    spent = sum(float(dict(r).get("amount") or 0) for r in logs_repo.expenses_for_date(for_date))
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
        "income": income,
        "money": {"spent": round(spent, 2), "earned": round(earned, 2), "net": round(earned - spent, 2)},
        "photos": photos,
        "events": day_events(for_date, edges_conn, kb_store, todo_store),
        "work_log": day_work_log(for_date, kb_store),
        "notes_saved": day_notes_saved(for_date, kb_store, {(p["folder"], p["slug"]) for p in photos}),
        "chats": day_chats(for_date, conversations_root),
    }
