from __future__ import annotations

import base64
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .. import clock
from .ledger import Ledger, LedgerEntry

# Every write tool calls a store method or two directly; this module is the
# one shared mechanism that makes every one of those writes undoable, per
# docs/mcp-angle.md's 2026-10-13 "auto-write everywhere, undo instead of
# approval" design. A write tool builds a WriteSession, stages a snapshot of
# whatever it's about to touch BEFORE touching it (or, for a fresh insert,
# records just enough to find and remove the new thing), then commits one
# ledger entry grouping every staged step — so a multi-part push undoes as a
# single unit, never partially.

# Only tables an undo step is ever allowed to touch — guards the f-string SQL
# below against ever being pointed at an arbitrary table name.
_ALLOWED_TABLES = {
    "edges",
    "expense_log",
    "food_log",
    "substance_log",
    "activity_log",
    "exercise_sets",
    "body_stats",
    "stock_transactions",
}


class Step(Protocol):
    def to_json(self) -> dict[str, Any]: ...
    def undo(self) -> None: ...


@dataclass
class FileStep:
    """A markdown (or any plain-text/binary) file's full bytes right before a
    write touches it. `before=None` means the file didn't exist yet — undo
    deletes it. Covers create (before=None), edit/overwrite (before=old
    bytes), and delete (before=old bytes, since the step is staged right
    before the real delete call)."""

    path: Path
    before: bytes | None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "file",
            "path": str(self.path),
            "before_b64": base64.b64encode(self.before).decode("ascii") if self.before is not None else None,
        }

    def undo(self) -> None:
        if self.before is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(self.before)

    @staticmethod
    def from_json(data: dict[str, Any]) -> "FileStep":
        before = base64.b64decode(data["before_b64"]) if data.get("before_b64") is not None else None
        return FileStep(Path(data["path"]), before)


@dataclass
class JournalAppendStep:
    """A single MCP journal append, identified by its unique marker rather
    than a before/after snapshot — see JournalStore.save()/strip_marked_append().
    This is the precise "exact span of text" case docs/mcp-angle.md calls out:
    undoing it must not clobber any other append (MCP or not) in the same
    day's file, before or after it."""

    root: Path
    entry_date: date
    marker: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "journal_append",
            "root": str(self.root),
            "entry_date": self.entry_date.isoformat(),
            "marker": self.marker,
        }

    def undo(self) -> None:
        from ..nodes.journal.store import JournalStore

        JournalStore(self.root).strip_marked_append(self.entry_date, self.marker)

    @staticmethod
    def from_json(data: dict[str, Any]) -> "JournalAppendStep":
        return JournalAppendStep(Path(data["root"]), date.fromisoformat(data["entry_date"]), data["marker"])


@dataclass
class SqliteRowStep:
    """One row's full prior state. `before=None` means the row didn't exist
    (this step stages a fresh INSERT) — undo deletes it by primary key.
    Otherwise `before` is the complete row as it was right before an
    update/delete — undo restores it exactly via INSERT OR REPLACE."""

    db_path: Path
    table: str
    pk_column: str
    pk_value: Any
    before: dict[str, Any] | None

    def __post_init__(self) -> None:
        if self.table not in _ALLOWED_TABLES:
            raise ValueError(f"undo not wired up for table {self.table!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "sqlite_row",
            "db_path": str(self.db_path),
            "table": self.table,
            "pk_column": self.pk_column,
            "pk_value": self.pk_value,
            "before": self.before,
        }

    def undo(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            if self.before is None:
                conn.execute(f"DELETE FROM {self.table} WHERE {self.pk_column} = ?", (self.pk_value,))
            else:
                columns = list(self.before.keys())
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT OR REPLACE INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [self.before[c] for c in columns],
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def from_json(data: dict[str, Any]) -> "SqliteRowStep":
        return SqliteRowStep(Path(data["db_path"]), data["table"], data["pk_column"], data["pk_value"], data["before"])


_STEP_TYPES = {
    "file": FileStep,
    "journal_append": JournalAppendStep,
    "sqlite_row": SqliteRowStep,
}


def _step_from_json(data: dict[str, Any]) -> Step:
    cls = _STEP_TYPES.get(data["kind"])
    if cls is None:
        raise ValueError(f"unknown undo step kind {data['kind']!r}")
    return cls.from_json(data)


class WriteSession:
    """One MCP write-tool call's staging area. A tool builds one of these,
    calls the appropriate stage_*() helper for each real thing it's about to
    change (or just did, for a fresh insert — see stage_new_file/
    stage_sqlite_insert), then commit() once at the end, after all the real
    writes happened, to record one grouped ledger entry."""

    def __init__(self, ledger: Ledger, tool: str, client: str, summary: str):
        self.ledger = ledger
        self.tool = tool
        self.client = client
        self.summary = summary
        self.steps: list[Step] = []

    def stage_file(self, path: Path) -> None:
        """Call BEFORE a write/edit/delete touches `path` — snapshots
        whatever is there right now (or its absence)."""
        before = path.read_bytes() if path.exists() else None
        self.steps.append(FileStep(path, before))

    def stage_new_file(self, path: Path) -> None:
        """Call AFTER a write created `path` for the first time — equivalent
        to stage_file() called beforehand when the file is known not to have
        existed, for call sites where the exact path is only known once the
        store has chosen it (e.g. a generated filename)."""
        self.steps.append(FileStep(path, before=None))

    def stage_journal_append(self, root: Path, entry_date: date, marker: str) -> None:
        self.steps.append(JournalAppendStep(root, entry_date, marker))

    def stage_sqlite_insert(self, db_path: Path, table: str, pk_column: str, pk_value: Any) -> None:
        """Call AFTER the INSERT, once the new row's primary key is known."""
        self.steps.append(SqliteRowStep(db_path, table, pk_column, pk_value, before=None))

    def stage_sqlite_row(self, conn: sqlite3.Connection, db_path: Path, table: str, pk_column: str, pk_value: Any) -> None:
        """Call BEFORE an UPDATE/DELETE — snapshots the row's current values."""
        row = conn.execute(f"SELECT * FROM {table} WHERE {pk_column} = ?", (pk_value,)).fetchone()
        before = dict(row) if row is not None else None
        self.steps.append(SqliteRowStep(db_path, table, pk_column, pk_value, before))

    def commit(self, result: dict[str, Any] | None = None) -> str:
        entry_id = uuid.uuid4().hex[:10]
        entry = LedgerEntry(
            id=entry_id,
            timestamp=clock.now(),
            client=self.client,
            tool=self.tool,
            summary=self.summary,
            steps=[s.to_json() for s in self.steps],
            result=result or {},
        )
        self.ledger.append(entry)
        return entry_id


def undo(ledger: Ledger, entry_id: str) -> LedgerEntry:
    """Replays a ledger entry's staged steps backward, last-applied first (so
    a multi-part push unwinds in the reverse order it was built), then marks
    the entry undone. No 24h cutoff here — that's a UI-layer policy per
    docs/mcp-angle.md; this layer just keeps every snapshot available and
    working indefinitely."""
    entry = ledger.find(entry_id)
    if entry is None:
        raise KeyError(f"no ledger entry {entry_id!r}")
    if entry.undone_at is not None:
        raise ValueError(f"ledger entry {entry_id!r} was already undone at {entry.undone_at.isoformat()}")
    for step_json in reversed(entry.steps):
        _step_from_json(step_json).undo()
    return ledger.mark_undone(entry_id, clock.now())
