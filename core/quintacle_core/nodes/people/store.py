from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

_HOME = "People"


class PersonStore:
    """One folder per person (People/<Name>/), with their profile at
    <folder>/profile.md — deliberately NOT a flat People/<Name>.md file,
    because their folder is also where journal/drop mentions about them get
    filed (as ordinary KBStore entries, via the existing folder-scoped-chat
    mechanism). Putting the profile file INSIDE that same folder means the
    folder-scoped chat sees the profile AND every mention together, with no
    separate wiring — same "return a folder other code nests under" shape as
    ResidenceStore."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self, name: str) -> Path:
        path = resolve_nested(self.kb_root, f"{_HOME}/{name}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        name: str,
        category: str = "",
        how_met: str = "",
        met_date: str | None = None,
        notes: str = "",
        links: list[str] | None = None,
    ) -> tuple[str, str]:
        """Returns (folder, slug) — folder is the exact string a kb_entry
        (a mention filed under People/<Name>/Mentions) or the folder-scoped
        chat should be given. `links` mirrors every other domain's
        frontmatter `links` field — e.g. an experience this person was
        mentioned alongside (see graph.py's sync_frontmatter_links)."""
        person_dir = self._dir(name)
        post = frontmatter.Post(notes)
        post["name"] = name
        post["category"] = category
        post["how_met"] = how_met
        post["met_date"] = met_date
        post["links"] = links or []
        (person_dir / "profile.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        folder = str(person_dir.relative_to(self.kb_root)).replace("\\", "/")
        return folder, slugify(name)

    def all(self) -> list[dict]:
        home_dir = resolve_nested(self.kb_root, _HOME)
        if not home_dir.exists():
            return []
        results = []
        for person_dir in sorted(home_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            profile_path = person_dir / "profile.md"
            if not profile_path.exists():
                continue
            post = frontmatter.loads(profile_path.read_text(encoding="utf-8"))
            folder = str(person_dir.relative_to(self.kb_root)).replace("\\", "/")
            metadata = safe_metadata(post, person_dir.name, {"category": "", "how_met": ""})
            results.append({**metadata, "notes": post.content, "folder": folder})
        return results

    def find(self, name: str) -> dict | None:
        matches = [p for p in self.all() if p["name"].lower() == name.lower()]
        return matches[0] if matches else None
