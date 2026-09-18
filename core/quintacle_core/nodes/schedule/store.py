from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import frontmatter

from .models import Priority, Todo


class TodoStore:
    """One markdown file per todo (item node), frontmatter metadata + free-text body."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, todo_id: str) -> Path:
        return self.root / f"{todo_id}.md"

    def save(self, todo: Todo) -> None:
        post = frontmatter.Post(todo.notes)
        post["id"] = todo.id
        post["title"] = todo.title
        post["priority"] = int(todo.priority)
        post["due_date"] = todo.due_date.isoformat() if todo.due_date else None
        post["start_time"] = todo.start_time
        post["end_time"] = todo.end_time
        post["done"] = todo.done
        post["created_at"] = todo.created_at.isoformat()
        self._path(todo.id).write_text(frontmatter.dumps(post), encoding="utf-8")

    def load(self, todo_id: str) -> Todo:
        post = frontmatter.loads(self._path(todo_id).read_text(encoding="utf-8"))
        return self._todo_from_post(post)

    def list(self) -> list[Todo]:
        return [
            self._todo_from_post(frontmatter.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.md"))
        ]

    def delete(self, todo_id: str) -> None:
        self._path(todo_id).unlink(missing_ok=True)

    @staticmethod
    def _todo_from_post(post: frontmatter.Post) -> Todo:
        meta = post.metadata
        due = meta.get("due_date")
        return Todo(
            id=meta["id"],
            title=meta["title"],
            priority=Priority(meta.get("priority", Priority.MEDIUM)),
            due_date=date.fromisoformat(due) if due else None,
            start_time=meta.get("start_time"),
            end_time=meta.get("end_time"),
            done=meta.get("done", False),
            created_at=datetime.fromisoformat(meta["created_at"]),
            notes=post.content,
        )
