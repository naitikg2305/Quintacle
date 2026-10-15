from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from .. import db
from ..day_bundle import build_day_bundle, entry_assets
from ..markdown_paths import resolve_nested, slugify
from ..nodes.journal.store import JournalStore
from ..nodes.kb.drop import _IMAGE_MIME, describe_images
from ..nodes.kb.store import KBStore
from ..nodes.logs.log_store import LogFileStore, home_for
from ..nodes.logs.repository import LogsRepository
from ..nodes.schedule.models import Priority, Todo, apply_todo_updates
from ..nodes.schedule.ranking import rank_todos
from ..nodes.schedule.store import TodoStore
from .graph_link import configure as configure_graph_link, link_new_entry
from .ledger import Ledger
from .undo import WriteSession, undo as undo_ledger_entry

# Lets a host pass something more specific than "unknown-mcp-client" into the
# ledger (e.g. "claude-code", "claude-desktop") without needing a protocol
# feature for it — MCP's `initialize` handshake carries a client name in
# some SDKs/versions but not reliably across all of them yet.
CLIENT_NAME = os.environ.get("QUINTACLE_MCP_CLIENT", "unknown-mcp-client")

DATA_DIR: Path
_db_path: Path
journal_store: JournalStore
kb_store: KBStore
todo_store: TodoStore
log_file_store: LogFileStore
logs_repo: LogsRepository
ledger: Ledger
db_conn: sqlite3.Connection

mcp = FastMCP("quintacle")


def init(data_dir: Path | None = None) -> None:
    """(Re)points every store at `data_dir` (default: same QUINTACLE_DATA_DIR
    convention as quintacle_core/api.py — this process imports the real store
    classes directly rather than talking to the FastAPI app over HTTP, per
    docs/mcp-angle.md). Called once at import time for real use; tests call
    it again with a tmp_path to get a fully isolated set of stores, since the
    @mcp.tool()-decorated functions below look up these names from the
    module's globals at call time, not at decoration time."""
    global DATA_DIR, _db_path, journal_store, kb_store, todo_store, log_file_store, logs_repo, ledger, db_conn
    DATA_DIR = Path(data_dir) if data_dir is not None else Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    kb_root = DATA_DIR / "kb"
    _db_path = DATA_DIR / "quintacle.db"
    journal_store = JournalStore(DATA_DIR / "journal")
    kb_store = KBStore(kb_root)
    todo_store = TodoStore(DATA_DIR / "schedule" / "todos")
    log_file_store = LogFileStore(kb_root)
    conn = db.connect(_db_path)
    db_conn = conn
    logs_repo = LogsRepository(conn, log_file_store)
    ledger = Ledger(DATA_DIR / "mcp-log.md")
    # Same connection the logs repo uses — the graph's edges table lives in
    # the same quintacle.db (docs/graph-model.md Stage 1).
    configure_graph_link(DATA_DIR, conn, journal_store=journal_store, kb_store=kb_store)


init()


def _session(tool: str, summary: str) -> WriteSession:
    return WriteSession(ledger, tool=tool, client=CLIENT_NAME, summary=summary)


def _stage_new_log_files(session: WriteSession, logs_dir: Path, glob_pattern: str, write) -> Any:
    """LogFileStore.write() picks its own filename (date + an incrementing
    sequence number) — rather than duplicate that private naming logic here,
    snapshot the directory's filenames before/after and stage whatever
    appeared. `write` is a zero-arg callable that performs the real write and
    returns whatever the caller wants back."""
    before = set(p.name for p in logs_dir.glob(glob_pattern)) if logs_dir.exists() else set()
    result = write()
    after = set(p.name for p in logs_dir.glob(glob_pattern))
    for name in after - before:
        session.stage_new_file(logs_dir / name)
    return result


# --- Journal ---


@mcp.tool()
def journal_append(for_date: str, content: str) -> dict:
    """Append already-written text to a day's journal entry. Structured
    write: pass the exact text to add — this never classifies or rewrites it.
    Commits immediately and is independently undoable (see undo_write); use
    `drop` for raw/unstructured capture that should cost Quintacle's own AI
    budget to sort out instead."""
    entry_date = date.fromisoformat(for_date)
    marker = uuid4().hex[:12]
    session = _session("journal.append", f"Appended to journal for {entry_date.isoformat()}")
    journal_store.save(entry_date, content, marker=marker)
    session.stage_journal_append(journal_store.root, entry_date, marker)
    link_new_entry("journal_day", f"journal:{entry_date.isoformat()}", content, session=session)
    ledger_id = session.commit(result={"date": entry_date.isoformat()})
    return {"date": entry_date.isoformat(), "ledger_id": ledger_id}


@mcp.tool()
def journal_get(for_date: str) -> dict:
    """Read a day's full journal content, or null if nothing was written
    that day."""
    entry_date = date.fromisoformat(for_date)
    return {"date": entry_date.isoformat(), "content": journal_store.load(entry_date)}


# --- KB / notes ---


@mcp.tool()
def kb_list_folders() -> list[str]:
    """Every folder in the KB tree, '/'-joined (e.g. "Personal
    Development/Physical/Fitness") — use this to pick (or confirm) a folder
    before kb_create_entry."""
    return kb_store.list_folders()


@mcp.tool()
def kb_create_entry(
    folder: str,
    title: str,
    content: str,
    links: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> dict:
    """Create (or overwrite-by-title) a KB note. Structured write: folder,
    title, content, links and fields must already be decided — this never
    classifies freeform text into a folder/title itself (use `drop` for
    that). `links` are other note titles / journal dates to connect in the
    graph view; `fields` is an open key/value dict for structured data
    (mileage, cost, make/model...) that Phase E's view inference can render
    as a table. Commits immediately, independently undoable."""
    target_path = resolve_nested(kb_store.root, folder) / f"{slugify(title)}.md"
    session = _session("kb.create_entry", f"Created KB entry '{title}' in {folder}")
    session.stage_file(target_path)
    folder_slug, entry_slug = kb_store.write(folder, title, content, links, fields=fields)
    link_new_entry("kb_note", f"note:{folder_slug}/{entry_slug}", f"{title}\n{content}", session=session, links=links or [], folder=folder_slug)
    ledger_id = session.commit(result={"folder": folder_slug, "slug": entry_slug})
    return {"folder": folder_slug, "slug": entry_slug, "ledger_id": ledger_id}


@mcp.tool()
def kb_get_entry(folder: str, slug: str) -> dict:
    """Read a KB entry's full content, fields, and other metadata."""
    entry = kb_store.read_full(folder, slug)
    if entry is None:
        raise ValueError(f"no such entry: {folder}/{slug}")
    return entry


@mcp.tool()
def kb_search_entries(query: str) -> list[dict]:
    """Case-insensitive substring search across every KB entry's filename and
    body, regardless of folder — {folder, slug, snippet} per match."""
    return kb_store.search(query)


# --- Logs: expenses ---


@mcp.tool()
def log_expense(
    for_date: str,
    amount: float,
    merchant: str = "",
    category: str = "",
    notes: str = "",
    kind: str = "regular",
) -> dict:
    """Log an expense on a given date. Structured write: amount/merchant/
    category already decided — this never guesses a category from a receipt
    (that's the `drop` convenience path). Commits immediately, independently
    undoable."""
    entry_date = date.fromisoformat(for_date)
    session = _session("logs.log_expense", f"Logged ${amount:.2f} expense at {merchant or 'unknown merchant'} on {entry_date.isoformat()}")
    logs_dir = resolve_nested(log_file_store.kb_root, home_for("finance")) / "logs"
    expense_id = _stage_new_log_files(
        session,
        logs_dir,
        f"{entry_date.isoformat()}-*.md",
        lambda: logs_repo.log_expense(entry_date, amount, merchant, category, notes, kind),
    )
    session.stage_sqlite_insert(_db_path, "expense_log", "id", expense_id)
    link_new_entry("expense", f"expense:{expense_id}", f"{merchant} {category} {notes}".strip(), session=session, amount=amount, date=entry_date.isoformat())
    ledger_id = session.commit(result={"expense_id": expense_id, "date": entry_date.isoformat()})
    return {"expense_id": expense_id, "date": entry_date.isoformat(), "ledger_id": ledger_id}


@mcp.tool()
def expenses_in_range(start: str, end: str) -> list[dict]:
    """List every logged expense between two dates (inclusive), YYYY-MM-DD."""
    rows = logs_repo.expenses_between(date.fromisoformat(start), date.fromisoformat(end))
    return [dict(row) for row in rows]


# --- Schedule / todos ---


@mcp.tool()
def todo_create(
    title: str,
    category: str = "",
    priority: int = 2,
    due_date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    notes: str = "",
) -> dict:
    """Create a todo. priority: 1=low, 2=medium, 3=high, 4=urgent.
    due_date/start_time/end_time are optional (YYYY-MM-DD / HH:MM 24h).
    Commits immediately, independently undoable."""
    todo = Todo(
        title=title,
        category=category,
        priority=Priority(priority),
        due_date=date.fromisoformat(due_date) if due_date else None,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
    )
    session = _session("schedule.todo_create", f"Created todo '{title}'")
    session.stage_file(todo_store.path_for(todo.id))
    todo_store.save(todo)
    link_new_entry("todo", todo.id, f"{title} {notes}".strip(), session=session, due_date=due_date)
    ledger_id = session.commit(result={"todo": todo.model_dump(mode="json")})
    return {**todo.model_dump(mode="json"), "ledger_id": ledger_id}


@mcp.tool()
def todo_update(
    todo_id: str,
    title: str | None = None,
    priority: int | None = None,
    due_date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    done: bool | None = None,
    category: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update any subset of a todo's fields — only the ones passed change.
    Commits immediately, independently undoable (restores every prior field,
    not just the ones you changed)."""
    session = _session("schedule.todo_update", f"Updated todo {todo_id}")
    session.stage_file(todo_store.path_for(todo_id))
    try:
        todo = todo_store.load(todo_id)
    except FileNotFoundError:
        raise ValueError(f"no such todo: {todo_id}")
    updates = {
        k: v
        for k, v in {
            "title": title,
            "priority": Priority(priority) if priority is not None else None,
            "due_date": date.fromisoformat(due_date) if due_date else None,
            "start_time": start_time,
            "end_time": end_time,
            "done": done,
            "category": category,
            "notes": notes,
        }.items()
        if v is not None
    }
    todo = apply_todo_updates(todo, updates)
    todo_store.save(todo)
    link_new_entry("todo", todo.id, f"{todo.title} {todo.notes}".strip(), session=session)
    ledger_id = session.commit(result={"todo": todo.model_dump(mode="json")})
    return {**todo.model_dump(mode="json"), "ledger_id": ledger_id}


@mcp.tool()
def todo_delete(todo_id: str) -> dict:
    """Delete a todo. Commits immediately, independently undoable (undo
    recreates the exact file that existed before deletion)."""
    session = _session("schedule.todo_delete", f"Deleted todo {todo_id}")
    session.stage_file(todo_store.path_for(todo_id))
    todo_store.delete(todo_id)
    ledger_id = session.commit(result={"deleted": todo_id})
    return {"deleted": todo_id, "ledger_id": ledger_id}


@mcp.tool()
def todo_list(include_done: bool = False) -> list[dict]:
    """List todos. By default, open todos only, ranked the same way the app's
    calendar/list views do (soonest due date first, higher priority breaking
    ties). Pass include_done=True to see everything, unranked."""
    todos = todo_store.list()
    ranked = todos if include_done else rank_todos(todos)
    return [t.model_dump(mode="json") for t in ranked]


# --- Day recall / photos ---


@mcp.tool()
def day_recall(for_date: str) -> dict:
    """Everything recorded on a given day (YYYY-MM-DD), in one bundle: the
    journal text, todos due, activities, exercise, food (entries + totals),
    body stats, substances, expenses, and `photos` — every KB note linked to
    that day (a photo's EXIF date links it at drop time), each with its
    stored drop-time description and asset paths. Deterministic and
    read-only: no AI call, no ledger entry — YOU do the narrating. Same
    assembly the app's own GET /day/{date} uses. Pair with describe_photo
    for a fresh (billed) look at any listed photo."""
    return build_day_bundle(
        date.fromisoformat(for_date),
        journal_store=journal_store,
        todo_store=todo_store,
        logs_repo=logs_repo,
        kb_store=kb_store,
        edges_conn=db_conn,
    )


@mcp.tool()
def describe_photo(folder: str, slug_or_path: str, question: str | None = None) -> dict:
    """Convenience (billed — uses Quintacle's own AI): look at a stored KB
    photo again, NOW. One fresh vision call on Quintacle's own metered
    Anthropic key per call — unlike every other read tool here, which is
    free and deterministic; the stored drop-time description (day_recall /
    kb_get_entry) is the free alternative. Pass a note's slug to describe
    its first image asset, or a direct "assets/..." path within `folder`;
    `question` makes the call answer that question about the photo instead
    of generically describing it. Image bytes never cross MCP — they're
    read and sent to vision server-side; only text comes back. It's a
    read: no ledger entry, nothing to undo."""
    if slug_or_path.startswith("assets/"):
        asset_path = slug_or_path
    else:
        entry = kb_store.read_full(folder, slug_or_path)
        if entry is None:
            raise ValueError(f"no such entry: {folder}/{slug_or_path}")
        asset_path = next(
            (a for a in entry_assets(entry) if a.rsplit(".", 1)[-1].lower() in _IMAGE_MIME),
            None,
        )
        if asset_path is None:
            raise ValueError(f"entry {folder}/{slug_or_path} has no image asset to describe")
    ext = asset_path.rsplit(".", 1)[-1].lower() if "." in asset_path else ""
    mime = _IMAGE_MIME.get(ext)
    if mime is None:
        raise ValueError(f"not an image asset: {asset_path}")
    data = kb_store.read_asset(folder, asset_path)
    if data is None:
        raise ValueError(f"asset not found: {folder}/{asset_path}")
    return {"folder": folder, "path": asset_path, "description": describe_images([(data, mime)], question)}


# --- Local perception (free, on-device) ---


@mcp.tool()
def perceive_photo(folder: str, slug_or_path: str) -> dict:
    """LOCAL & FREE (no AI call, no API spend, fully on-device): run
    Quintacle's perception models over a stored KB photo — YOLO object tags,
    face observations (box + persisted embedding_id + enrolled-person match
    by NAME or null for unknown) and deterministic scene attributes
    (daylight/outdoor hint/brightness). The free counterpart to
    describe_photo (which bills a vision call). Pass a note's slug to
    perceive its first image asset, or a direct "assets/..." path within
    `folder`. Image bytes and face embedding vectors never cross MCP — only
    tags, names and ids come back. It's a read plus local embedding storage:
    no ledger entry, nothing to undo."""
    from ..perception import perceive_photo as run_perception

    if slug_or_path.startswith("assets/"):
        asset_path = slug_or_path
    else:
        entry = kb_store.read_full(folder, slug_or_path)
        if entry is None:
            raise ValueError(f"no such entry: {folder}/{slug_or_path}")
        asset_path = next(
            (a for a in entry_assets(entry) if a.rsplit(".", 1)[-1].lower() in _IMAGE_MIME),
            None,
        )
        if asset_path is None:
            raise ValueError(f"entry {folder}/{slug_or_path} has no image asset to perceive")
    ext = asset_path.rsplit(".", 1)[-1].lower() if "." in asset_path else ""
    mime = _IMAGE_MIME.get(ext)
    if mime is None:
        raise ValueError(f"not an image asset: {asset_path}")
    data = kb_store.read_asset(folder, asset_path)
    if data is None:
        raise ValueError(f"asset not found: {folder}/{asset_path}")
    result = run_perception(data, mime)
    if result is None:
        raise ValueError("perception deps not installed — pip install -r core/perception-requirements.txt")
    return {"folder": folder, "path": asset_path, "perception": result.model_dump()}


# --- Ledger / undo ---


@mcp.tool()
def list_recent_writes(limit: int = 20) -> list[dict]:
    """The most recent MCP writes (newest first) — what, where, which client,
    when, and whether it's already been undone. Read-only."""
    return [e.to_json() for e in ledger.recent(limit)]


@mcp.tool()
def undo_write(ledger_id: str) -> dict:
    """Reverse an MCP write by its ledger id (from a write tool's result, or
    from list_recent_writes) — restores exactly what existed before it, for
    every part of a multi-part push. No time limit enforced here; a future UI
    may stop *offering* this past 24h, but the underlying snapshot and this
    tool keep working indefinitely."""
    entry = undo_ledger_entry(ledger, ledger_id)
    return entry.to_json()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
