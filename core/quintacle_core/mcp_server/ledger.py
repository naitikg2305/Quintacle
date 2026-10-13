from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# One JSON object per ledger entry, fenced so the file stays readable as
# markdown while still being trivially machine-parseable (a future "recent
# writes" frontend page just needs to pull these blocks out, not parse prose).
_ENTRY_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)

_HEADER = (
    "# Quintacle MCP write ledger\n\n"
    "Append-only record of every MCP write: what, where, which client, when.\n"
    "Each entry's fenced JSON block carries everything `undo` needs to reverse "
    "it. Don't hand-edit this file — use the `undo_write` MCP tool.\n\n---\n\n"
)


@dataclass
class LedgerEntry:
    id: str
    timestamp: datetime
    client: str
    tool: str
    summary: str
    steps: list[dict[str, Any]]
    result: dict[str, Any] = field(default_factory=dict)
    undone_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "client": self.client,
            "tool": self.tool,
            "summary": self.summary,
            "steps": self.steps,
            "result": self.result,
            "undone_at": self.undone_at.isoformat() if self.undone_at else None,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "LedgerEntry":
        return LedgerEntry(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            client=data["client"],
            tool=data["tool"],
            summary=data["summary"],
            steps=data["steps"],
            result=data.get("result") or {},
            undone_at=datetime.fromisoformat(data["undone_at"]) if data.get("undone_at") else None,
        )

    def render_markdown(self) -> str:
        status = f"undone at {self.undone_at.isoformat()}" if self.undone_at else "active"
        lines = [
            f"## {self.timestamp.isoformat()} · `{self.id}` · {self.tool}",
            f"- client: {self.client}",
            f"- status: {status}",
            f"- summary: {self.summary}",
            "",
            "```json",
            json.dumps(self.to_json(), indent=2),
            "```",
            "",
            "---",
            "",
        ]
        return "\n".join(lines)


class Ledger:
    """The single combined, human-readable, append-only log every MCP write
    goes into — this *is* the future "recent writes" page's data source, per
    docs/mcp-angle.md's 2026-10-13 update. `append()` is the only append-only
    operation; `mark_undone()` rewrites the whole (small, local) file to flip
    one entry's status in place, since plain text has no in-place patch —
    nothing is ever removed, only that one field changes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(_HEADER, encoding="utf-8")

    def append(self, entry: LedgerEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.render_markdown())

    def all(self) -> list[LedgerEntry]:
        text = self.path.read_text(encoding="utf-8")
        return [LedgerEntry.from_json(json.loads(m)) for m in _ENTRY_RE.findall(text)]

    def find(self, entry_id: str) -> LedgerEntry | None:
        for entry in self.all():
            if entry.id == entry_id:
                return entry
        return None

    def recent(self, limit: int = 20) -> list[LedgerEntry]:
        return list(reversed(self.all()[-limit:]))

    def mark_undone(self, entry_id: str, when: datetime) -> LedgerEntry:
        entries = self.all()
        target = next((e for e in entries if e.id == entry_id), None)
        if target is None:
            raise KeyError(f"no ledger entry {entry_id!r}")
        target.undone_at = when
        text = _HEADER + "".join(e.render_markdown() for e in entries)
        self.path.write_text(text, encoding="utf-8")
        return target
