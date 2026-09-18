from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _as_text(content) -> str:
    """A turn's content is either a plain string, or — when a photo/PDF was
    attached — a list of Anthropic content blocks (see kb/api.py's
    ChatMessage). This store is scratch/ephemeral by design (its own
    docstring), so a persisted transcript keeps just the text plus a note of
    what was attached, not the raw base64 forever."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block["text"])
        elif block.get("type") == "image":
            parts.append("📎 (photo attached)")
        elif block.get("type") == "document":
            parts.append("📎 (PDF attached)")
    return "\n".join(parts)


class ChatStore:
    """One markdown file per chat session — scratch by design, distinct from
    the permanent Knowledge Base. Meant to be deleted once its useful content
    has been pushed into a real KB entry (Pillar 3's ephemeral-chat /
    permanent-KB principle, now with an actual file to delete)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.md"

    def list_sessions(self) -> list[dict]:
        sessions = []
        for path in sorted(self.root.glob("*.md"), reverse=True):
            first_line = next(iter(path.read_text(encoding="utf-8").splitlines()), "# Chat")
            sessions.append({"id": path.stem, "title": first_line.lstrip("# ").strip() or "Chat"})
        return sessions

    def create(self, title: str = "") -> str:
        # Microsecond resolution — two sessions created back-to-back (as in a
        # fast test, or a quick double-click) must not collide on the same id.
        session_id = datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
        self.save(session_id, title, [])
        return session_id

    def load(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not path.exists():
            return []
        messages: list[dict] = []
        current_role: str | None = None
        current_lines: list[str] = []

        def flush():
            if current_role is not None:
                messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})

        for line in path.read_text(encoding="utf-8").splitlines():
            if line == "### You":
                flush()
                current_role, current_lines = "user", []
            elif line == "### Assistant":
                flush()
                current_role, current_lines = "assistant", []
            elif current_role is None and line.startswith("# "):
                continue  # the session title line, before any message content starts
            else:
                current_lines.append(line)
        flush()
        return messages

    def save(self, session_id: str, title: str, messages: list[dict]) -> None:
        lines = [f"# {title or 'Chat'}", ""]
        for m in messages:
            lines.append("### You" if m["role"] == "user" else "### Assistant")
            lines.append(_as_text(m["content"]))
            lines.append("")
        self._path(session_id).write_text("\n".join(lines), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
