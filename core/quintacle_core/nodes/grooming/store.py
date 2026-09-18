from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

# Nested under the same Grooming folder already seeded in kb/llm.py's
# SEED_FOLDERS — items/routines live alongside any KB notes about grooming,
# same "copy the folder, it's self-contained" pattern as Wardrobe.
_HOME = "Personal Development/Physical/Grooming"


class GroomingItemStore:
    """One markdown file per grooming product — the reusable library routines
    are composed from. Markdown-only, no SQLite mirror. Unlike ingredient/
    nutrition-label photos (irrelevant once macros are extracted), a
    product's photo stays useful — "what does this bottle actually look
    like" — so it's kept, not discarded."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _HOME) / "items"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, category: str, description: str = "", assets: list[str] | None = None) -> str:
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        post["category"] = category
        post["description"] = description
        if assets:
            post["assets"] = assets
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            metadata = safe_metadata(post, p.stem, {"category": "", "description": ""})
            metadata["assets"] = metadata.get("assets") or [a for a in (metadata.get("asset"), metadata.get("asset2")) if a]
            results.append(metadata)
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()

    def save_asset(self, filename: str, data: bytes) -> str:
        assets_dir = self._dir() / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stem, _, ext = filename.rpartition(".")
        safe_name = f"{slugify(stem or filename)}.{ext.lower()}" if ext else slugify(filename)
        (assets_dir / safe_name).write_bytes(data)
        return f"assets/{safe_name}"

    def read_asset(self, asset_path: str) -> bytes | None:
        path = self._dir() / asset_path
        return path.read_bytes() if path.exists() else None


class GroomingRoutineStore:
    """One markdown file per named routine (AM routine, PM routine, weekly,
    etc.) — just a name + the ordered product names it's made of. Presets
    only, no log — "did I do it today" is a Habit, not a bespoke log table
    (same reasoning as Outfit: this is a template, not a dated record)."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _HOME) / "routines"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, steps: list[str]) -> str:
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        post["steps"] = steps
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(safe_metadata(post, p.stem, {"steps": []}))
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()
