from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

_HOME = "Fun/Travel"  # 2026-10-20 taxonomy: Planning root retired, travel experiences live under Fun


def _kind_folder_name(kind: str) -> str:
    """Folder name for a kind of experience — "restaurant" -> "Restaurants",
    "bar" -> "Bars", "ice skating" -> "Ice Skatings" (simple heuristic
    pluralization; good enough for a folder name, not linguistically
    perfect — kind itself, stored verbatim in frontmatter, is what's
    actually queried/filtered on)."""
    kind = kind.strip()
    if not kind:
        return "Experiences"
    return kind.title() if kind.lower().endswith("s") else f"{kind.title()}s"


class ExperienceStore:
    """One markdown file per experience — a restaurant, bar, activity,
    touristy spot, whatever — nested Planning/Travel/<City>/<Kind>/. A real
    structured store (rating, would-return), not just a KB note — but the
    actual photo is NEVER duplicated here: it stays in its one canonical
    Media/Photos home (see kb/photo_organizer.py) and this just links to it
    by title, same links mechanism every other domain already uses."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self, city: str, kind: str) -> Path:
        path = resolve_nested(self.kb_root, f"{_HOME}/{city}/{_kind_folder_name(kind)}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        name: str,
        city: str,
        kind: str,
        rating: str = "",
        would_return: bool | None = None,
        visited_date: str | None = None,
        notes: str = "",
        links: list[str] | None = None,
    ) -> tuple[str, str]:
        slug = slugify(name)
        post = frontmatter.Post(notes)
        post["name"] = name
        post["city"] = city
        post["kind"] = kind
        post["rating"] = rating
        post["would_return"] = would_return
        post["visited_date"] = visited_date
        post["links"] = links or []
        city_dir = self._dir(city, kind)
        (city_dir / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        folder = str(city_dir.relative_to(self.kb_root)).replace("\\", "/")
        return folder, slug

    def all(self) -> list[dict]:
        home_dir = resolve_nested(self.kb_root, _HOME)
        if not home_dir.exists():
            return []
        results = []
        for city_dir in sorted(home_dir.iterdir()):
            if not city_dir.is_dir():
                continue
            for kind_dir in sorted(city_dir.iterdir()):
                if not kind_dir.is_dir():
                    continue
                for p in sorted(kind_dir.glob("*.md")):
                    post = frontmatter.loads(p.read_text(encoding="utf-8"))
                    folder = str(kind_dir.relative_to(self.kb_root)).replace("\\", "/")
                    metadata = safe_metadata(post, p.stem, {"city": city_dir.name.replace("-", " ").title(), "kind": kind_dir.name})
                    results.append({**metadata, "notes": post.content, "slug": p.stem, "folder": folder})
        return results

    def by_city(self, city: str) -> list[dict]:
        return [e for e in self.all() if e.get("city") == city]
