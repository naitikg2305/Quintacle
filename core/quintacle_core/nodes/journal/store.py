from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


class JournalStore:
    """One markdown file per day — the narrative record (Productive/Fun/Emotional/
    To Do Tomorrow). Structured hours/categories extracted from it are logged
    separately into the SQLite activity_log, keyed by the same date."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, entry_date: date) -> Path:
        return self.root / f"{entry_date.isoformat()}.md"

    def save(self, entry_date: date, content: str) -> None:
        """Appends a dump to the day's file — never overwrites. A morning
        check-in and an evening one are both real dumps; a second save on the
        same day used to silently destroy the first one's raw text."""
        path = self._path(entry_date)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        stamp = datetime.now().strftime("%H:%M")
        entry = f"### {stamp}\n{content}"
        combined = f"{existing}\n\n---\n\n{entry}" if existing.strip() else entry
        path.write_text(combined, encoding="utf-8")

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
