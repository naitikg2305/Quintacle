from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ... import clock

# Wraps an MCP-originated append so undo can strip exactly that span later —
# see mcp_server/undo.py's JournalAppendStep. A normal (non-MCP) save() call
# passes no marker and is untagged, same as before this existed.
_MARKER_OPEN = "<!-- mcp-append:{marker} -->"
_MARKER_CLOSE = "<!-- /mcp-append:{marker} -->"
_SEPARATOR = "\n\n---\n\n"


class JournalStore:
    """One markdown file per day — the narrative record (Productive/Fun/Emotional/
    To Do Tomorrow). Structured hours/categories extracted from it are logged
    separately into the SQLite activity_log, keyed by the same date."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, entry_date: date) -> Path:
        return self.root / f"{entry_date.isoformat()}.md"

    def path_for(self, entry_date: date) -> Path:
        """Public accessor for the day's file path — used by the MCP undo
        layer, which needs it without reaching into a private method."""
        return self._path(entry_date)

    def save(self, entry_date: date, content: str, marker: str | None = None) -> None:
        """Appends a dump to the day's file — never overwrites. A morning
        check-in and an evening one are both real dumps; a second save on the
        same day used to silently destroy the first one's raw text.

        `marker` tags this specific append (e.g. an MCP `journal_append` tool
        call) with a unique id wrapped in HTML comments, so
        strip_marked_append() can later remove exactly this span — and only
        this span — even if other appends (MCP or not) land in the same file
        before or after it."""
        path = self._path(entry_date)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        stamp = clock.now().strftime("%H:%M")
        body = f"{_MARKER_OPEN.format(marker=marker)}\n{content}\n{_MARKER_CLOSE.format(marker=marker)}" if marker else content
        entry = f"### {stamp}\n{body}"
        combined = f"{existing}{_SEPARATOR}{entry}" if existing.strip() else entry
        path.write_text(combined, encoding="utf-8")

    def strip_marked_append(self, entry_date: date, marker: str) -> bool:
        """Undo for a save(..., marker=...) call — removes exactly the block
        wrapped by that marker, plus whichever single `---` separator belongs
        to it (the one before it, unless it was the first entry in the file,
        in which case the one after it), leaving any other entry in the file
        — appended earlier or later, MCP or not — untouched. Returns False if
        the file or the marker's block no longer exists (already undone, or
        the file was hand-edited since)."""
        path = self._path(entry_date)
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(
            r"### \d{2}:\d{2}\n"
            + re.escape(_MARKER_OPEN.format(marker=marker))
            + r"\n.*?\n"
            + re.escape(_MARKER_CLOSE.format(marker=marker)),
            re.DOTALL,
        )
        match = pattern.search(text)
        if match is None:
            return False
        start, end = match.start(), match.end()
        if text[:start].endswith(_SEPARATOR):
            start -= len(_SEPARATOR)
        elif text[end : end + len(_SEPARATOR)] == _SEPARATOR:
            end += len(_SEPARATOR)
        remainder = text[:start] + text[end:]
        if remainder.strip():
            path.write_text(remainder, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return True

    def load(self, entry_date: date) -> str | None:
        path = self._path(entry_date)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def list_dates(self) -> list[date]:
        """Every day that actually has a journal entry — used by the graph
        view to know which day-nodes exist to connect photos to."""
        dates = []
        for p in self.root.glob("*.md"):
            try:
                dates.append(date.fromisoformat(p.stem))
            except ValueError:
                continue
        return sorted(dates)
