from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

_HOME = "Organisation/Home"


class ResidenceStore:
    """One markdown file per residence (e.g. "Standard" in College Park,
    "Iris 307" in DC) — tracks apartments/living spaces over time, not just
    the current one, per the original plan. Nested by city:
    Organisation/Home/<City>/<Residence>.md. Items belonging to a residence
    live in a SIBLING folder, <City>/<Residence>/items/ — see HomeItemStore,
    which takes the residence's folder as an explicit param rather than a
    single fixed home the way Wardrobe/Grooming/Documents have one, since a
    residence's location is inherently dynamic data, not a constant."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def write(
        self,
        name: str,
        city: str,
        address: str = "",
        moved_in: str | None = None,
        moved_out: str | None = None,
        notes: str = "",
    ) -> tuple[str, str]:
        """Returns (residence_folder, slug) — residence_folder is the exact
        string HomeItemStore should be given to nest this residence's items."""
        city_dir = resolve_nested(self.kb_root, f"{_HOME}/{city}")
        city_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(name)
        post = frontmatter.Post(notes)
        post["name"] = name
        post["city"] = city
        post["address"] = address
        post["moved_in"] = moved_in
        post["moved_out"] = moved_out
        (city_dir / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        residence_folder = str((city_dir / slug).relative_to(self.kb_root)).replace("\\", "/")
        return residence_folder, slug

    def all(self) -> list[dict]:
        home_dir = resolve_nested(self.kb_root, _HOME)
        if not home_dir.exists():
            return []
        results = []
        for city_dir in sorted(home_dir.iterdir()):
            if not city_dir.is_dir():
                continue
            for p in sorted(city_dir.glob("*.md")):
                post = frontmatter.loads(p.read_text(encoding="utf-8"))
                folder = str((city_dir / p.stem).relative_to(self.kb_root)).replace("\\", "/")
                metadata = safe_metadata(post, p.stem, {"city": city_dir.name.replace("-", " ").title()})
                results.append({**metadata, "notes": post.content, "slug": p.stem, "folder": folder})
        return results

    def find(self, name: str) -> dict | None:
        matches = [r for r in self.all() if r["name"] == name]
        return matches[0] if matches else None


class HomeItemStore:
    """One markdown file per notable home item — furniture, decor,
    appliances, etc. — nested under its residence's own folder. Keeps the
    photo (same reasoning as Wardrobe/Grooming: what does this actually look
    like stays useful, unlike a nutrition-label photo which is irrelevant
    once macros are extracted)."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self, residence_folder: str) -> Path:
        path = resolve_nested(self.kb_root, residence_folder) / "items"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        residence_folder: str,
        name: str,
        category: str = "",
        location: str = "",
        purchase_price: float | None = None,
        purchase_date: str | None = None,
        notes: str = "",
        assets: list[str] | None = None,
    ) -> str:
        slug = slugify(name)
        post = frontmatter.Post(notes)
        post["name"] = name
        post["category"] = category
        post["location"] = location
        post["purchase_price"] = purchase_price
        post["purchase_date"] = purchase_date
        if assets:
            post["assets"] = assets
        (self._dir(residence_folder) / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self, residence_folder: str) -> list[dict]:
        results = []
        for p in sorted(self._dir(residence_folder).glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            metadata = safe_metadata(post, p.stem, {"category": "", "location": ""})
            metadata["assets"] = metadata.get("assets") or [a for a in (metadata.get("asset"), metadata.get("asset2")) if a]
            results.append({**metadata, "notes": post.content, "slug": p.stem})
        return results

    def save_asset(self, residence_folder: str, filename: str, data: bytes) -> str:
        assets_dir = self._dir(residence_folder) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stem, _, ext = filename.rpartition(".")
        safe_name = f"{slugify(stem or filename)}.{ext.lower()}" if ext else slugify(filename)
        (assets_dir / safe_name).write_bytes(data)
        return f"assets/{safe_name}"

    def read_asset(self, residence_folder: str, asset_path: str) -> bytes | None:
        path = self._dir(residence_folder) / asset_path
        return path.read_bytes() if path.exists() else None
