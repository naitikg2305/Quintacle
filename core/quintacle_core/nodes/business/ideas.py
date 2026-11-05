"""Business ideas as the /business page sees them — deterministic reads over
the KB tree, nothing model-decided.

An idea is a folder `Business Ideas/<Idea>/` (on disk `business-ideas/<idea>/`)
with a hub note whose slug equals the folder slug — the same folder-hub
pattern as `projects/quintacle/quintacle.md`. EVERY file anywhere under the
idea's folder belongs to the idea: markdown notes, PDFs, docs, spreadsheets,
images, STLs, videos, `.url` link files. A folder without a hub (files the
sorter filed before anyone created the hub) is still an idea, just one with
`has_hub: false` — creating the hub later adopts the files.

Hub `fields` (written with KBStore.set_fields, no `edited` restamp):
  status   idea | exploring | validating | building | parked | dropped
  summary  one-liner
  market   free text
  tags     list of strings (a comma string is accepted and split)
  created  ISO date (ET), stamped at create
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import frontmatter

from ... import clock
from ...markdown_paths import resolve_nested, slugify
from ..kb.privacy import is_private_meta

ROOT_FOLDER = "Business Ideas"
ROOT_SLUG = slugify(ROOT_FOLDER)  # "business-ideas"
STATUSES = ("idea", "exploring", "validating", "building", "parked", "dropped")
DEFAULT_STATUS = "idea"

# Order is the UI's icon-row order; every unknown extension is "other".
FILE_KINDS: dict[str, tuple[str, ...]] = {
    "markdown": ("md",),
    "image": ("jpg", "jpeg", "png", "gif", "webp", "heic", "svg"),
    "video": ("mp4", "webm", "mov", "m4v"),
    "pdf": ("pdf",),
    "doc": ("docx", "doc", "odt", "rtf", "txt", "pptx", "ppt", "key"),
    "spreadsheet": ("xlsx", "xlsm", "xls", "csv", "ods", "numbers"),
    "model": ("stl", "obj", "3mf", "step", "stp"),
    "link": ("url", "webloc"),
}
_KIND_BY_EXT = {ext: kind for kind, exts in FILE_KINDS.items() for ext in exts}
KIND_ORDER = (*FILE_KINDS, "other")
_URL_RE = re.compile(r"https?://[^\s)\]>\"'<]+")


def kind_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _KIND_BY_EXT.get(ext, "other")


def normalize_status(value) -> str:
    s = str(value or "").strip().lower()
    return s if s in STATUSES else DEFAULT_STATUS


def normalize_tags(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(t).strip() for t in value if str(t).strip()]


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, clock.TIME_ZONE).isoformat(timespec="seconds")


def _title_from_body(content: str, slug: str) -> str:
    first = content.lstrip().split("\n", 1)[0]
    return first.lstrip("# ").strip() if first.startswith("#") else slug.replace("-", " ").title()


def _strip_title(content: str) -> str:
    lines = content.lstrip().split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip("\n")


def root_dir(kb_root: Path) -> Path:
    return resolve_nested(Path(kb_root), ROOT_FOLDER)


def idea_dir(kb_root: Path, slug: str) -> Path:
    return root_dir(kb_root) / slugify(slug)


def _idea_dirs(kb_root: Path) -> list[Path]:
    root = root_dir(kb_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def _walk_files(folder: Path) -> list[Path]:
    """Every file under the idea folder, at any depth (assets/, sub-notes),
    minus dot/underscore plumbing (`_view.json`, `.DS_Store`)."""
    return sorted(
        p
        for p in folder.rglob("*")
        if p.is_file() and not any(part.startswith((".", "_")) for part in p.relative_to(folder).parts)
    )


def _hub_path(folder: Path) -> Path:
    return folder / f"{folder.name}.md"


def _load_hub(folder: Path) -> frontmatter.Post | None:
    path = _hub_path(folder)
    return frontmatter.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _hub_summary(folder: Path, hub: frontmatter.Post | None) -> dict:
    slug = folder.name
    meta = dict(hub.metadata) if hub is not None else {}
    fields = meta.get("fields") or {}
    return {
        "slug": slug,
        "folder": f"{ROOT_SLUG}/{slug}",
        "title": _title_from_body(hub.content, slug) if hub is not None else slug.replace("-", " ").title(),
        "has_hub": hub is not None,
        "private": is_private_meta(meta),
        "status": normalize_status(fields.get("status")),
        "summary": str(fields.get("summary") or "").strip(),
        "market": str(fields.get("market") or "").strip(),
        "tags": normalize_tags(fields.get("tags")),
        "created": str(fields.get("created") or "").strip() or None,
    }


def _last_edited(hub: frontmatter.Post | None, files: list[Path]) -> str | None:
    """Latest of the hub's `edited` stamp and every member file's mtime (ET)."""
    stamps = [_mtime(p) for p in files]
    if hub is not None and hub.metadata.get("edited"):
        stamps.append(str(hub.metadata["edited"]))
    parsed = []
    for s in stamps:
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=clock.TIME_ZONE)
        parsed.append((dt, s))
    return max(parsed)[1] if parsed else None


def _member_files(folder: Path) -> list[Path]:
    hub = _hub_path(folder)
    return [p for p in _walk_files(folder) if p != hub]


def list_ideas(kb_root: Path) -> list[dict]:
    ideas = []
    for folder in _idea_dirs(kb_root):
        hub = _load_hub(folder)
        files = _member_files(folder)
        counts: dict[str, int] = {}
        for p in files:
            k = kind_of(p.name)
            counts[k] = counts.get(k, 0) + 1
        ideas.append(
            {
                **_hub_summary(folder, hub),
                "file_counts": {k: counts[k] for k in KIND_ORDER if k in counts},
                "file_total": len(files),
                "last_edited": _last_edited(hub, files),
            }
        )
    return sorted(ideas, key=lambda i: i["last_edited"] or "", reverse=True)


def read_idea(kb_root: Path, slug: str) -> dict | None:
    folder = idea_dir(kb_root, slug)
    if not folder.is_dir():
        return None
    hub = _load_hub(folder)
    files = _member_files(folder)
    folder_slug = f"{ROOT_SLUG}/{folder.name}"
    groups: dict[str, list[dict]] = {}
    links: list[str] = _URL_RE.findall(hub.content) if hub is not None else []
    for p in files:
        rel = p.relative_to(folder).as_posix()
        k = kind_of(p.name)
        item: dict = {"name": p.name, "path": rel, "kind": k, "size": p.stat().st_size, "modified": _mtime(p)}
        if k == "markdown":
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            sub = rel.rsplit("/", 1)[0] if "/" in rel else ""
            item.update(
                {
                    # (folder, slug) addresses the note for /kb/entry and
                    # /kb/asset, whose paths are relative to the NOTE's folder.
                    "folder": f"{folder_slug}/{sub}" if sub else folder_slug,
                    "slug": p.stem,
                    "title": _title_from_body(post.content, p.stem),
                    "content": _strip_title(post.content),
                    "private": is_private_meta(post.metadata),
                }
            )
            links.extend(_URL_RE.findall(post.content))
        elif k == "link":
            found = _URL_RE.findall(p.read_text(encoding="utf-8", errors="replace"))
            item["url"] = found[0] if found else None
        groups.setdefault(k, []).append(item)
    return {
        **_hub_summary(folder, hub),
        "body": _strip_title(hub.content) if hub is not None else "",
        "files": {k: groups[k] for k in KIND_ORDER if k in groups},
        "file_total": len(files),
        "links": list(dict.fromkeys(u.rstrip(".,;") for u in links)),
        "last_edited": _last_edited(hub, files),
    }
