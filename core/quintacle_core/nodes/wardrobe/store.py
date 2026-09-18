from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

# Nested under the same Style & Dressing folder already seeded in
# kb/llm.py's SEED_FOLDERS — items/outfits live alongside any KB notes about
# style, same "copy the folder, it's self-contained" pattern as elsewhere.
_HOME = "Personal Development/Physical/Style & Dressing"


class WardrobeItemStore:
    """One markdown file per clothing/accessory item — the reusable library
    outfits are composed from. Markdown-only, no SQLite mirror: nothing else
    holds a foreign key into an item (same reasoning as RoutineStore)."""

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
            # Items written before `assets` existed only have the old fixed
            # `asset`/`asset2` pair — fall back to those so nothing already
            # on disk goes invisible.
            metadata["assets"] = metadata.get("assets") or [a for a in (metadata.get("asset"), metadata.get("asset2")) if a]
            results.append(metadata)
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()

    def save_asset(self, filename: str, data: bytes) -> str:
        """Unlike ingredient/nutrition-label photos (irrelevant once macros
        are extracted), a wardrobe item's photo stays useful — "what does
        this actually look like" — so it's kept, not discarded."""
        assets_dir = self._dir() / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stem, _, ext = filename.rpartition(".")
        safe_name = f"{slugify(stem or filename)}.{ext.lower()}" if ext else slugify(filename)
        (assets_dir / safe_name).write_bytes(data)
        return f"assets/{safe_name}"

    def read_asset(self, asset_path: str) -> bytes | None:
        path = self._dir() / asset_path
        return path.read_bytes() if path.exists() else None


class OutfitStore:
    """One markdown file per composed outfit — just a name + the item names
    it's made of. Presets only, no wear-log (per explicit direction)."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _HOME) / "outfits"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, items: list[str], asset: str | None = None) -> str:
        """items may be empty — a full-outfit photo (a mirror selfie, an
        OOTD shot) is saved AS IS, the photo itself being the record,
        without forcing AI to decompose it into individually-matched
        wardrobe items first."""
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        post["items"] = items
        if asset:
            post["asset"] = asset
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(safe_metadata(post, p.stem, {"items": []}))
        return results

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

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()
