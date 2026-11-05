"""Projects page (2026-11-05) — every project the owner has done, is doing or
has planned, read straight off the KB. Deterministic, zero model calls.

A project is a top-level folder under the KB's `Projects/` root
(`projects/<slug>/`). Its hub note is the note whose slug equals the folder
slug (`projects/quintacle/quintacle.md` — the same folder-hub rule
career/hubs.py uses). Everything else in that folder and its subfolders
belongs to the project: markdown notes, STL/3MF models, images, PDFs and
documents, videos. A note sitting directly in `projects/` (an older single-
note hub) is a project too, with only the assets it references. A folder
with files but no hub note yet still lists, and the first field edit creates
its hub.

Hub `fields` this page reads (all optional; frontmatter `fields`, written
with KBStore.set_fields so an edit never restamps `edited`):

  status    done | doing | planned   (default doing; synonyms normalized)
  repo      GitHub (or any) repo URL
  summary   one-liner for the card (default: the hub body's first line)
  stack     list or comma string     (falls back to `tags`)
  start/end free-text dates
  cover     asset path relative to the project folder
  public / public_name / public_repo — the career alias table's fields,
            shared on purpose (career/hubs.py HUB_FIELDS), never duplicated.

Related work logs come from the graph: edges from `note:daily-log/work-logs/*`
into the hub (the work-log importer creates them) plus work logs whose
frontmatter `links` name the hub title — the same two sources
career/worklogs.py trusts.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...markdown_paths import resolve_nested, slugify
from ..kb.privacy import is_private_meta
from ..logs.worklog import WORKLOG_FOLDER

router = APIRouter(prefix="/projects", tags=["projects"])

ROOT = "projects"
STATUSES = ("doing", "planned", "done")
_STATUS_SYNONYMS = {
    "doing": "doing", "active": "doing", "in progress": "doing", "in-progress": "doing", "ongoing": "doing",
    "current": "doing", "wip": "doing",
    "planned": "planned", "plan": "planned", "idea": "planned", "todo": "planned", "next": "planned",
    "backlog": "planned", "someday": "planned",
    "done": "done", "complete": "done", "completed": "done", "finished": "done", "shipped": "done",
    "archived": "done",
}
# Subfolders of projects/ that are plumbing, not projects (root-note assets).
_NOT_PROJECTS = {"assets", "logs"}

_KINDS = {
    "model": {"stl", "3mf", "obj", "step", "stp", "f3d", "scad", "gcode"},
    "image": {"jpg", "jpeg", "png", "gif", "webp", "svg", "avif"},
    "pdf": {"pdf"},
    "doc": {"docx", "doc", "pptx", "ppt", "xlsx", "xlsm", "xls", "csv", "txt", "rtf", "odt", "json", "yaml", "yml"},
    "video": {"mp4", "webm", "mov", "m4v"},
}
FILE_KINDS = (*_KINDS.keys(), "other")
_COVER_STEMS = ("cover", "image", "card", "banner", "thumbnail")
_ASSET_LINE_RE = re.compile(r"^\[asset\]\(([^)]+)\)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _kb():
    from ..kb.api import get_store  # lazy: kb.api pulls in half the app

    return get_store()


def file_kind(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for kind, exts in _KINDS.items():
        if ext in exts:
            return kind
    return "other"


def normalize_status(value) -> str:
    return _STATUS_SYNONYMS.get(str(value or "").strip().lower(), "doing")


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _humanize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w) or slug


def _split_body(content: str) -> tuple[str, str]:
    """(title, body) — KBStore writes `# Title` as the body's first line."""
    first, _, rest = content.partition("\n")
    if first.lstrip().startswith("#"):
        return first.lstrip("# ").strip(), rest.lstrip("\n")
    return "", content


def _first_line(body: str) -> str:
    for line in body.split("\n"):
        s = line.strip()
        if s and not s.startswith("#") and not _ASSET_LINE_RE.match(s) and s != "---" and not s.endswith("<!-- filemeta -->"):
            return re.sub(r"[*_`]", "", s)[:200]
    return ""


# --- discovery ----------------------------------------------------------------


def _locate(kb) -> dict[str, dict]:
    """slug -> {slug, folder, hub: (folder, slug) | None}. Folder projects
    win over a same-slug root note, unless the folder has no hub of its own
    (then the root note is its hub)."""
    found: dict[str, dict] = {}
    root_notes = set(kb.list_entries(ROOT))
    all_folders = kb.list_folders()
    for f in all_folders:
        parts = f.split("/")
        if len(parts) != 2 or parts[0] != ROOT or parts[1] in _NOT_PROJECTS:
            continue
        slug = parts[1]
        if slug in kb.list_entries(f):
            hub = (f, slug)
        elif slug in root_notes:
            hub = (ROOT, slug)
        else:
            hub = None
        tree = [x for x in all_folders if x == f or x.startswith(f + "/")]
        found[slug] = {"slug": slug, "folder": f, "hub": hub, "tree": tree}
    for slug in root_notes:
        if slug not in found:
            found[slug] = {"slug": slug, "folder": ROOT, "hub": (ROOT, slug), "tree": []}
    return found


def _files(kb, loc: dict) -> list[dict]:
    """Every non-markdown file belonging to the project, paths relative to
    the project folder (so `/kb/asset?folder=<folder>&path=<path>` reads it)."""
    folder = loc["folder"]
    out = []
    if folder == ROOT:
        # A root-level single-note project owns only the assets it references.
        hub_folder, hub_slug = loc["hub"]
        full = kb.read_full(hub_folder, hub_slug) or {}
        refs = [*(full.get("assets") or []), *_ASSET_LINE_RE.findall(full.get("content") or "")]
        for rel in dict.fromkeys(refs):
            if kb.asset_exists(folder, rel):
                out.append(_file_row(kb, folder, rel))
        return out
    for f in loc["tree"]:
        prefix = f[len(folder) + 1 :] if f != folder else ""
        for name in kb.list_files(f):
            out.append(_file_row(kb, folder, f"{prefix}/{name}" if prefix else name))
    return sorted(out, key=lambda r: r["path"].lower())


def _file_row(kb, folder: str, rel: str) -> dict:
    name = rel.rsplit("/", 1)[-1]
    try:
        size = (resolve_nested(kb.root, folder) / rel).stat().st_size
    except OSError:
        size = None
    return {"folder": folder, "path": rel, "name": name, "kind": file_kind(name), "size": size}


def _notes(kb, loc: dict, *, with_content: bool) -> list[dict]:
    """Every markdown note in the project folder tree except the hub."""
    folder = loc["folder"]
    if folder == ROOT:
        return []
    out = []
    for f in loc["tree"]:
        for slug in kb.list_entries(f):
            if (f, slug) == loc["hub"]:
                continue
            full = kb.read_full(f, slug)
            if full is None:
                continue
            meta = kb.read_meta(f, slug) or {}
            title, body = _split_body(full.get("content") or "")
            row = {
                "folder": f,
                "slug": slug,
                "title": full.get("title") or title or slug,
                "subfolder": f[len(folder) + 1 :] if f != folder else "",
                "snippet": _first_line(body)[:140],
                "private": is_private_meta(meta),
                "edited": str(meta.get("edited") or "") or None,
            }
            if with_content:
                row["content"] = body
            out.append(row)
    return sorted(out, key=lambda r: (r["subfolder"], r["title"].lower()))


def _worklog_folder() -> str:
    return "/".join(slugify(p) for p in WORKLOG_FOLDER.split("/"))


def _worklog_links(kb) -> dict[str, list[str]]:
    """work-log slug -> its frontmatter `links` titles (read once per request)."""
    wl = _worklog_folder()
    return {slug: kb.read_links(wl, slug) for slug in kb.list_entries(wl)}


def _worklogs(kb, hub: tuple[str, str] | None, title: str, wl_links: dict[str, list[str]]) -> list[dict]:
    if hub is None:
        return []
    wl = _worklog_folder()
    prefix = f"note:{wl}/"
    slugs = {s for s, links in wl_links.items() if title in links}
    try:
        from ...graph import get_graph_store

        for e in get_graph_store().reverse_edges(f"note:{hub[0]}/{hub[1]}"):
            if e["source_id"].startswith(prefix):
                slugs.add(e["source_id"][len(prefix) :])
    except RuntimeError:
        pass  # graph store not initialized (pure unit use)
    rows = []
    for slug in slugs:
        if slug not in wl_links:
            continue  # an edge to a deleted log
        m = _DATE_RE.search(slug)
        rows.append({"folder": wl, "slug": slug, "date": m.group(1) if m else None, "title": f"Work log - {m.group(1)}" if m else slug})
    return sorted(rows, key=lambda r: r["date"] or "", reverse=True)


def _related(kb, hub: tuple[str, str] | None, project_folder: str) -> list[dict]:
    """Graph neighbors of the hub (either direction) that aren't work logs
    or the project's own notes — people, places, experiences, other notes."""
    if hub is None:
        return []
    try:
        from ...graph import get_graph_store

        store = get_graph_store()
    except RuntimeError:
        return []
    hub_id = f"note:{hub[0]}/{hub[1]}"
    ids = {e["target_id"] for e in store.edges_from(hub_id)} | {e["source_id"] for e in store.reverse_edges(hub_id)}
    skip = (f"note:{_worklog_folder()}/", f"note:{project_folder}/")
    out = []
    for nid in sorted(ids):
        if nid == hub_id or (project_folder != ROOT and nid.startswith(skip[1])) or nid.startswith(skip[0]):
            continue
        kind, _, rest = nid.partition(":")
        row = {"id": nid, "type": kind, "title": rest.rsplit("/", 1)[-1], "folder": None, "slug": None}
        if kind == "note" and "/" in rest:
            folder, slug = rest.rsplit("/", 1)
            full = kb.read_full(folder, slug)
            if full is None:
                continue
            if is_private_meta(kb.read_meta(folder, slug)):
                continue
            row.update(title=full.get("title") or slug, folder=folder, slug=slug)
            if slug == "profile":
                row["type"] = "person"
        out.append(row)
    return out


def _card(fields: dict, files: list[dict]) -> dict | None:
    """What the card shows: the `cover` field, else a `card.stl` (the
    website's convention), else a cover-ish image, else any image, else any
    STL."""
    by_path = {f["path"]: f for f in files}
    cover = str(fields.get("cover") or "").strip()
    if cover in by_path and by_path[cover]["kind"] in ("image", "model"):
        f = by_path[cover]
        return {"kind": "stl" if f["name"].lower().endswith(".stl") else "image", "folder": f["folder"], "path": f["path"]}
    stls = [f for f in files if f["name"].lower().endswith(".stl")]
    images = [f for f in files if f["kind"] == "image"]
    card_stl = next((f for f in stls if f["name"].lower() == "card.stl"), None)
    if card_stl:
        return {"kind": "stl", "folder": card_stl["folder"], "path": card_stl["path"]}
    named = next((f for f in images if f["name"].rsplit(".", 1)[0].lower() in _COVER_STEMS), None)
    pick = named or (images[0] if images else None)
    if pick:
        return {"kind": "image", "folder": pick["folder"], "path": pick["path"]}
    if stls:
        return {"kind": "stl", "folder": stls[0]["folder"], "path": stls[0]["path"]}
    return None


def _project(kb, loc: dict, wl_links: dict[str, list[str]], *, detail: bool) -> dict:
    hub = loc["hub"]
    meta, full = {}, None
    if hub is not None:
        meta = kb.read_meta(*hub) or {}
        full = kb.read_full(*hub)
    fields = meta.get("fields") or {}

    def get(key):
        v = fields.get(key, meta.get(key))
        return v if v not in ("", None) else None

    hub_title, body = _split_body((full or {}).get("content") or "")
    title = (full or {}).get("title") or hub_title or _humanize(loc["slug"])
    files = _files(kb, loc)
    notes = _notes(kb, loc, with_content=detail)
    worklogs = _worklogs(kb, hub, title, wl_links)
    counts = {k: 0 for k in FILE_KINDS}
    for f in files:
        counts[f["kind"]] += 1
    out = {
        "slug": loc["slug"],
        "title": title,
        "folder": loc["folder"],
        "hub": {"folder": hub[0], "slug": hub[1]} if hub else None,
        "status": normalize_status(get("status")),
        "repo": str(get("repo") or get("github") or "").strip() or None,
        "summary": str(get("summary") or "").strip() or _first_line(body),
        "stack": _as_list(get("stack")) or _as_list(get("tags")),
        "start": str(get("start")) if get("start") else None,
        "end": str(get("end")) if get("end") else None,
        "cover": str(get("cover")) if get("cover") else None,
        "public": str(get("public")).lower() in ("true", "yes", "1", "on") if get("public") is not None else False,
        "public_name": str(get("public_name") or "").strip() or None,
        "public_repo": str(get("public_repo") or "").strip() or None,
        "private": is_private_meta(meta),
        "edited": str(meta.get("edited") or "") or None,
        "counts": {"notes": len(notes), **counts, "worklogs": len(worklogs)},
        "last_worklog": worklogs[0]["date"] if worklogs else None,
        "card": _card(fields, files),
    }
    if detail:
        out["body"] = body
        out["notes"] = notes
        out["files"] = files
        out["worklogs"] = worklogs
        out["related"] = _related(kb, hub, loc["folder"])
    return out


_STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}


@router.get("")
def list_projects() -> list[dict]:
    kb = _kb()
    wl_links = _worklog_links(kb)
    rows = [_project(kb, loc, wl_links, detail=False) for loc in _locate(kb).values()]
    # Most recently touched first within a status: last work log, else hub edit.
    rows.sort(key=lambda p: p["last_worklog"] or (p["edited"] or "")[:10], reverse=True)
    rows.sort(key=lambda p: _STATUS_ORDER[p["status"]])
    return rows


def _find(kb, slug: str) -> dict:
    loc = _locate(kb).get(slugify(slug))
    if loc is None:
        raise HTTPException(404, f"no project {slug!r}")
    return loc


@router.get("/{slug}")
def get_project(slug: str) -> dict:
    kb = _kb()
    return _project(kb, _find(kb, slug), _worklog_links(kb), detail=True)


# --- owner edits (direct, like the career alias table) ---------------------------


class ProjectFields(BaseModel):
    status: Literal["doing", "planned", "done"] | None = None
    repo: str | None = None
    summary: str | None = None
    stack: list[str] | str | None = None
    start: str | None = None
    end: str | None = None
    cover: str | None = None
    public: bool | None = None
    public_name: str | None = None
    public_repo: str | None = None


def _clean_updates(body: ProjectFields) -> dict:
    """Only fields present in the request change; "" / [] clears a field."""
    updates = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "stack":
            value = _as_list(value) or None
        elif isinstance(value, str):
            value = value.strip() or None
        updates[key] = value
    return updates


def _index_new_note(folder: str, slug: str, title: str, content: str) -> None:
    """Same post-write hooks POST /kb/entries runs, so a hub created here is
    searchable and graph-linked like any other note."""
    from ...retrieval import safe_index_note
    from ..kb.api import _sync_note_graph_links

    _sync_note_graph_links(f"note:{folder}/{slug}", title, content, None)
    safe_index_note(folder, slug, title, content)


@router.put("/{slug}/fields")
def put_project_fields(slug: str, body: ProjectFields) -> dict:
    kb = _kb()
    loc = _find(kb, slug)
    updates = _clean_updates(body)
    if loc["hub"] is None:
        # A folder of files with no hub yet: the first edit creates the hub
        # (slug == folder slug, so it IS the folder hub from now on).
        title = _humanize(loc["slug"])
        fields = {k: v for k, v in updates.items() if v is not None}
        folder, note = kb.write(loc["folder"], title, "", fields=fields)
        _index_new_note(folder, note, title, "")
        loc = _find(kb, slug)
    else:
        kb.set_fields(*loc["hub"], updates)
    return _project(kb, loc, _worklog_links(kb), detail=True)


class ProjectCreate(ProjectFields):
    name: str
    description: str = ""


@router.post("")
def create_project(body: ProjectCreate) -> dict:
    kb = _kb()
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    slug = slugify(name)
    if slug in _NOT_PROJECTS or slug in _locate(kb):
        raise HTTPException(409, f"a project {slug!r} already exists")
    updates = _clean_updates(ProjectFields(**body.model_dump(exclude_unset=True, exclude={"name", "description"})))
    fields = {k: v for k, v in updates.items() if v is not None}
    fields.setdefault("status", "doing")
    folder, note = kb.write(f"Projects/{name}", name, body.description.strip(), fields=fields)
    _index_new_note(folder, note, name, body.description.strip())
    return _project(kb, _find(kb, slug), _worklog_links(kb), detail=True)
