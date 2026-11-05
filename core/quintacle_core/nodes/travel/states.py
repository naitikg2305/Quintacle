"""Travel's three states (2026-11-05): Experiences (places visited — the
structured ExperienceStore, untouched), Planned (trip itineraries = plain KB
notes under Fun/Travel/Planned/**) and Bucket list (one KB note per place
under Fun/Travel/Bucket List). Everything here is deterministic file work
over KBStore — no model calls. `visited` on a bucket row is computed from
the experience registry in code, never guessed."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import frontmatter

from ... import clock
from ...markdown_paths import resolve_nested, slugify
from ..kb.store import KBStore, _frontmatter_assets, _title_of

TRAVEL = "Fun/Travel"
PLANNED = "Fun/Travel/Planned"
BUCKET = "Fun/Travel/Bucket List"

# `assets/<file>` references inside a note — [asset](...) lines, markdown
# images/links, or frontmatter `assets` entries all share this shape.
_ASSET_REF_RE = re.compile(r"assets/[^)\s\"'\]]+")


def _is_charter(slug: str) -> bool:
    return slug.startswith("about-")


def _folder_slug(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _str_or_none(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or None
    return str(value)


def _trip_row(root: Path, path: Path, group: str) -> dict:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    fields = post.metadata.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    edited = post.metadata.get("edited")
    return {
        "folder": _folder_slug(root, path.parent),
        "slug": path.stem,
        "title": _title_of(post, path.stem),
        "group": group,
        "start": _str_or_none(fields.get("start")),
        "end": _str_or_none(fields.get("end")),
        "destinations": _str_or_none(fields.get("destinations")),
        "status": _str_or_none(fields.get("status")),
        "edited": str(edited) if edited else None,
    }


def _sort_trips(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["start"] is None, r["start"] or "", r["title"].lower()))


def list_planned(store: KBStore) -> list[dict]:
    base = resolve_nested(store.root, PLANNED)
    if not base.is_dir():
        return []
    rows = []
    for path in base.rglob("*.md"):
        rel_parts = path.relative_to(base).parts
        if "assets" in rel_parts[:-1] or _is_charter(path.stem) or path.name.startswith("_"):
            continue
        group = rel_parts[0] if len(rel_parts) > 1 else ""
        rows.append(_trip_row(store.root, path, group))
    return _sort_trips(rows)


def list_unsorted(store: KBStore) -> list[dict]:
    base = resolve_nested(store.root, TRAVEL)
    if not base.is_dir():
        return []
    rows = [
        _trip_row(store.root, p, "")
        for p in base.glob("*.md")
        if not _is_charter(p.stem) and not p.name.startswith("_")
    ]
    return _sort_trips(rows)


class MoveConflict(Exception):
    pass


def _asset_refs(post: frontmatter.Post) -> list[str]:
    refs = _ASSET_REF_RE.findall(post.content)
    for a in _frontmatter_assets(dict(post.metadata)):
        if isinstance(a, str) and a.startswith("assets/"):
            refs.append(a)
    seen: list[str] = []
    for r in refs:
        if r not in seen:
            seen.append(r)
    return seen


def move_note(store: KBStore, folder: str, slug: str, group: str = "") -> tuple[str, str]:
    """Moves one note into Fun/Travel/Planned[/<group>], carrying the asset
    files it references (`assets/<file>`, relative to the note's folder).
    An asset another note in the source folder still references is COPIED,
    not moved, so that note keeps working; a name already taken in the
    target assets dir gets a free `-2` name and the reference is rewritten.
    Refuses (MoveConflict) to overwrite an existing note at the target.
    Returns the new (folder_slug, slug). Graph/retrieval re-keying is the
    caller's job (it owns the singletons)."""
    src = store.entry_path(folder, slug)
    if not src.exists():
        raise FileNotFoundError(f"entry not found: {folder}/{slug}")
    target_folder = f"{PLANNED}/{group}" if group.strip() else PLANNED
    target_dir = resolve_nested(store.root, target_folder)
    dst = target_dir / src.name
    if dst.resolve() == src.resolve():
        return _folder_slug(store.root, target_dir), src.stem
    if dst.exists():
        raise MoveConflict(f"a note already exists at {_folder_slug(store.root, target_dir)}/{src.stem}")

    src_dir = src.parent
    post = frontmatter.loads(src.read_text(encoding="utf-8"))
    refs = _asset_refs(post)

    # Which of those refs do sibling notes in the source folder also use?
    shared: set[str] = set()
    for sibling in src_dir.glob("*.md"):
        if sibling == src:
            continue
        try:
            sib_refs = set(_asset_refs(frontmatter.loads(sibling.read_text(encoding="utf-8"))))
        except Exception:
            continue
        shared |= sib_refs & set(refs)

    target_dir.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    renames: dict[str, str] = {}
    root_resolved = store.root.resolve()
    for ref in refs:
        src_asset = (src_dir / ref).resolve()
        if not src_asset.is_relative_to(root_resolved) or not src_asset.is_file():
            continue  # missing/escaping reference — leave the text as-is
        new_ref = ref
        if (target_dir / ref).exists():
            new_ref = store.free_asset_path(_folder_slug(store.root, target_dir), Path(ref).name)
        dst_asset = target_dir / new_ref
        dst_asset.parent.mkdir(parents=True, exist_ok=True)
        if ref in shared:
            shutil.copy2(src_asset, dst_asset)
        else:
            shutil.move(str(src_asset), str(dst_asset))
        if new_ref != ref:
            renames[ref] = new_ref
    for old, new in renames.items():
        text = re.sub(re.escape(old) + r"(?=[)\s\"'\]]|$)", new, text)

    dst.write_text(text, encoding="utf-8")
    src.unlink()
    return _folder_slug(store.root, target_dir), src.stem


# --- Bucket list ------------------------------------------------------------


def _word_in(needle: str, haystack: str) -> bool:
    needle = needle.strip()
    if not needle or not haystack:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack, re.IGNORECASE) is not None


def experience_matches(place: str, experience: dict) -> bool:
    """Deterministic visited check: the experience's city matches the place
    as a whole word in either direction ("Kyoto, Japan" ~ city "Kyoto";
    "Rome" never matches "Romeoville"). The experience's own name only
    counts when it appears whole inside the place (bucket "Eiffel Tower,
    Paris" ~ experience "Eiffel Tower") — not the reverse, so a restaurant
    called "Paris Baguette" in New York doesn't tick off Paris."""
    city = str(experience.get("city") or "")
    name = str(experience.get("name") or "")
    return _word_in(city, place) or _word_in(place, city) or _word_in(name, place)


def _body_notes(content: str) -> str:
    lines = content.strip().split("\n")
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _bucket_row(root: Path, path: Path, experiences: list[dict]) -> dict:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    place = _title_of(post, path.stem)
    fields = post.metadata.get("fields") or {}
    added = (fields.get("added") if isinstance(fields, dict) else None) or post.metadata.get("edited")
    matches = [e for e in experiences if experience_matches(place, e)]
    dates = sorted(str(e["visited_date"]) for e in matches if e.get("visited_date"))
    return {
        "folder": _folder_slug(root, path.parent),
        "slug": path.stem,
        "place": place,
        "notes": _body_notes(post.content),
        "added": str(added)[:10] if added else None,
        "visited": bool(matches),
        "visited_on": dates[0] if dates else None,
        "experience_ids": [f"experience:{e['folder']}/{e['slug']}" for e in matches],
    }


def list_bucket(store: KBStore, experiences: list[dict]) -> list[dict]:
    base = resolve_nested(store.root, BUCKET)
    if not base.is_dir():
        return []
    rows = [
        _bucket_row(store.root, p, experiences)
        for p in sorted(base.glob("*.md"))
        if not _is_charter(p.stem) and not p.name.startswith("_")
    ]
    return sorted(rows, key=lambda r: r["place"].lower())


def bucket_row(store: KBStore, slug: str, experiences: list[dict]) -> dict | None:
    path = store.entry_path(BUCKET, slug)
    return _bucket_row(store.root, path, experiences) if path.exists() else None


def bucket_exists(store: KBStore, place: str) -> bool:
    return store.entry_path(BUCKET, slugify(place)).exists()


def create_bucket(store: KBStore, place: str, notes: str = "") -> tuple[str, str]:
    return store.write(BUCKET, place.strip(), notes.strip(), fields={"added": clock.today().isoformat()})
