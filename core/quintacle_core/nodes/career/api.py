"""/career — the two on-demand updaters (docs/reference/career-updates.md).

Every write here is gated: Run endpoints only READ and propose; nothing
touches the record note, a hub, or the website repo until the matching
Save / Generate call carries the owner's reviewed choices.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import clock, llm_dispatch
from ...markdown_paths import slugify
from ...retrieval import safe_index_note
from ..kb.privacy import is_private_meta
from . import record as rec_mod
from .draft import draft_group
from .hubs import HUB_FIELDS, Hub, list_hubs, map_hub
from .state import CareerState
from .website import (
    WebsiteRepoError,
    site_path,
    entry_candidates,
    knowledge_candidates,
    parse_stamp,
    rank_candidates,
    render_employment,
    render_knowledge,
    render_project,
    slugify_path,
    write_branch,
)
from .worklogs import collect

router = APIRouter(prefix="/career", tags=["career"])
_state: CareerState | None = None


def init_career(data_dir: Path) -> None:
    global _state
    _state = CareerState(data_dir)


def get_state() -> CareerState:
    if _state is None:
        raise RuntimeError("career state not initialized — call init_career() first")
    return _state


def _kb():
    from ..kb.api import get_store  # lazy: kb.api pulls in half the app

    return get_store()


# --- the record note ----------------------------------------------------------


def _record_location() -> tuple[str, str]:
    s = get_state().settings()
    return slugify_path(s["record_folder"]), slugify(s["record_title"])


def _record_body(kb) -> tuple[str | None, dict | None]:
    """(body without KBStore's '# Title' line, raw meta) or (None, None)."""
    folder, slug = _record_location()
    meta = kb.read_meta(folder, slug)
    if meta is None:
        return None, None
    content = kb.read(folder, slug) or ""
    title = get_state().settings()["record_title"]
    head = f"# {title}"
    if content.startswith(head):
        content = content[len(head) :].lstrip("\n")
    return content, meta


def _load_record(kb):
    body, meta = _record_body(kb)
    if body is None:
        raise HTTPException(404, "no career record note yet — import it first")
    if is_private_meta(meta):
        # Private = never used by either updater (privacy.py).
        raise HTTPException(409, "the career record note is marked private — the updaters can't use it")
    return rec_mod.parse(body), meta


def _body_hash(body: str | None) -> str:
    return hashlib.sha1((body or "").encode("utf-8")).hexdigest()[:16]


def _record_or_none(kb):
    """The parsed record for READ-ONLY context (hub mapping, website entry
    candidates): None when absent or private."""
    body, meta = _record_body(kb)
    if body is None or is_private_meta(meta):
        return None
    return rec_mod.parse(body)


def _hubs(kb) -> list[Hub]:
    return list_hubs(kb, _record_location())


def _employers(hubs: list[Hub], rec) -> set[str]:
    return {h.title for h in hubs if h.kind == "career"} | rec_mod.org_names(rec)


class SettingsUpdate(BaseModel):
    record_folder: str | None = None
    record_title: str | None = None


@router.get("/settings")
def get_settings() -> dict:
    return get_state().settings()


@router.put("/settings")
def put_settings(body: SettingsUpdate) -> dict:
    return get_state().update_settings(body.record_folder, body.record_title)


@router.get("/record")
def record_status() -> dict:
    kb = _kb()
    folder, slug = _record_location()
    body, meta = _record_body(kb)
    if body is None:
        return {"exists": False, "folder": folder, "slug": slug, **get_state().settings()}
    rec = rec_mod.parse(body)
    return {
        "exists": True,
        "folder": folder,
        "slug": slug,
        "private": is_private_meta(meta),
        "edited": meta.get("edited"),
        "covered_through": rec.covered_through.isoformat() if rec.covered_through else None,
        "next_start": (rec.covered_through + timedelta(days=1)).isoformat() if rec.covered_through else None,
        "sections": [{"num": s.num, "title": s.title} for s in rec.sections if s.num in rec_mod.ENTRY_SECTIONS],
        "entries": [{"id": e.id, "title": e.title, "section": e.section} for e in rec.entries if e.section in rec_mod.ENTRY_SECTIONS],
        **get_state().settings(),
    }


class RecordImport(BaseModel):
    content: str


@router.post("/record/import")
def import_record(body: RecordImport) -> dict:
    """First-time move of the master record into Quintacle (the owner picks
    the file in the UI — that click is the Save). Refuses to overwrite an
    existing record note: after this, the note is edited in Browse or by
    the updater's append-only Save."""
    kb = _kb()
    if _record_body(kb)[0] is not None:
        raise HTTPException(409, "a career record note already exists — edit it in Browse instead")
    if not body.content.strip():
        raise HTTPException(400, "empty record")
    from ..kb.api import _sync_note_graph_links

    s = get_state().settings()
    folder_slug, entry_slug = kb.write(s["record_folder"], s["record_title"], body.content.strip(), [])
    _sync_note_graph_links(f"note:{folder_slug}/{entry_slug}", s["record_title"], body.content, [])
    safe_index_note(folder_slug, entry_slug, s["record_title"], body.content)
    return {"folder": folder_slug, "slug": entry_slug}


# --- hubs + alias table ---------------------------------------------------------


@router.get("/hubs")
def get_hubs() -> list[dict]:
    kb = _kb()
    rec = _record_or_none(kb)
    return [{**h.to_dict(), "mapping": map_hub(h, rec)} for h in _hubs(kb)]


class HubUpdate(BaseModel):
    folder: str
    slug: str
    record_entry: str | None = None
    public: bool | None = None
    public_name: str | None = None
    public_repo: str | None = None
    public_slug: str | None = None


@router.put("/hubs")
def put_hub(body: HubUpdate) -> dict:
    """Owner edits one hub's alias/mapping fields. Only fields present in
    the request change; an empty string clears a text field."""
    kb = _kb()
    hub = next((h for h in _hubs(kb) if (h.folder, h.slug) == (body.folder, body.slug)), None)
    if hub is None:
        raise HTTPException(404, "not a Career/Projects hub note")
    sent = body.model_dump(exclude_unset=True)
    updates = {}
    for key in HUB_FIELDS:
        if key not in sent:
            continue
        value = sent[key]
        if isinstance(value, str):
            value = value.strip() or None
        updates[key] = value
    kb.set_fields(hub.folder, hub.slug, updates)
    fresh = next(h for h in _hubs(kb) if (h.folder, h.slug) == (body.folder, body.slug))
    return fresh.to_dict()


# --- Build A: update the career record --------------------------------------------


class RecordRun(BaseModel):
    start: date | None = None  # required only when the record has no watermark
    include_today: bool = False
    provider: Literal["local", "cloud", "auto"] | None = None


@router.post("/record/run")
def run_record(body: RecordRun) -> dict:
    """Collect (deterministic) -> map (deterministic) -> draft (model,
    local-first) -> validate (code). Writes NOTHING; the response is the
    review list the owner edits before /career/record/save."""
    kb = _kb()
    rec, meta = _load_record(kb)
    if rec.covered_through is None and body.start is None:
        raise HTTPException(400, "the record has no `_Covered through:` watermark yet — pick a start date")
    today = clock.today()
    until = today if body.include_today else today - timedelta(days=1)
    hubs = _hubs(kb)
    try:
        found = collect(kb, hubs, after=rec.covered_through, start=body.start, until=until)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    employers = _employers(hubs, rec)
    used: list[str] = []
    groups = []
    for g in found["groups"].values():
        hub: Hub = g["hub"]
        mapping = map_hub(hub, rec)
        entry_id = mapping["entry_id"]
        entry = rec.entry(entry_id) if entry_id else None
        item = {
            "hub": hub.to_dict(),
            "mapping": mapping,
            "entry": {"id": entry.id, "title": entry.title} if entry else None,
            "sessions": g["sessions"],
            "bullets": [],
            "rejected": [],
            "error": None,
        }
        try:
            d = draft_group(
                hub_title=hub.title,
                entry_title=entry.title if entry else None,
                entry_text=rec.entry_text(entry_id) if entry else "",
                existing_bullets=[b["text"] for b in rec_mod.entry_bullets(rec, entry_id)] if entry else [],
                sessions=g["sessions"],
                employers=employers,
                provider=body.provider,
            )
            item["bullets"], item["rejected"] = d["bullets"], d["rejected"]
            if d.get("provider_used"):
                used.append(d["provider_used"])
        except Exception as e:  # one hub's model failure never sinks the run
            item["error"] = str(e)[:300]
        groups.append(item)
    groups.sort(key=lambda x: x["hub"]["title"].lower())
    return {
        "after": rec.covered_through.isoformat() if rec.covered_through else None,
        "start": body.start.isoformat() if body.start else None,
        "until": until.isoformat(),
        "through": found["through"],
        "dates": found["dates"],
        "skipped": found["skipped"],
        "groups": groups,
        "base_hash": _body_hash(_record_body(kb)[0]),
        "provider_used": llm_dispatch.summarize_providers(used),
    }


class SaveBullet(BaseModel):
    entry_id: str
    section: Literal["phrasing", "detail"]
    text: str
    date: date


class NewEntryBullet(BaseModel):
    section: Literal["phrasing", "detail"]
    text: str
    date: date


class NewEntry(BaseModel):
    section: int
    title: str
    hub_folder: str | None = None
    hub_slug: str | None = None
    bullets: list[NewEntryBullet] = Field(default_factory=list)


class HubMapping(BaseModel):
    hub_folder: str
    hub_slug: str
    entry_id: str


class RecordSave(BaseModel):
    through: date
    base_hash: str | None = None
    bullets: list[SaveBullet] = Field(default_factory=list)
    new_entries: list[NewEntry] = Field(default_factory=list)
    mappings: list[HubMapping] = Field(default_factory=list)


@router.post("/record/save")
def save_record(body: RecordSave) -> dict:
    """The one write: appends the reviewed bullets (append-only — existing
    lines are never rewritten), creates any new entries, moves the
    watermark to `through`, and remembers picked hub->entry mappings as the
    hub's `record_entry`. 409 if the record changed since the run."""
    kb = _kb()
    rec, _ = _load_record(kb)
    if body.base_hash is not None and _body_hash(_record_body(kb)[0]) != body.base_hash:
        raise HTTPException(409, "the record was edited since this run — run again")
    if rec.covered_through is not None and body.through < rec.covered_through:
        raise HTTPException(400, "through is before the current watermark")
    if body.through > clock.today():
        raise HTTPException(400, "through is in the future")
    text, _ = _record_body(kb)
    try:
        new_text, created = rec_mod.apply_additions(
            text,
            [b.model_dump(mode="json") for b in body.bullets],
            [ne.model_dump(mode="json") for ne in body.new_entries],
            body.through,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    s = get_state().settings()
    folder_slug, entry_slug = kb.write(s["record_folder"], s["record_title"], new_text)
    safe_index_note(folder_slug, entry_slug, s["record_title"], new_text)

    hubs = {(h.folder, h.slug): h for h in _hubs(kb)}
    remembered = []
    picks = [(m.hub_folder, m.hub_slug, m.entry_id) for m in body.mappings]
    picks += [(ne.hub_folder, ne.hub_slug, eid) for ne, eid in zip(body.new_entries, created) if ne.hub_folder and ne.hub_slug]
    for folder, slug, entry_id in picks:
        if (folder, slug) in hubs:
            kb.set_fields(folder, slug, {"record_entry": entry_id})
            remembered.append({"hub": f"{folder}/{slug}", "entry_id": entry_id})
    return {
        "covered_through": body.through.isoformat(),
        "appended": len([b for b in body.bullets if b.text.strip()]) + sum(len(ne.bullets) for ne in body.new_entries),
        "new_entries": created,
        "mappings_remembered": remembered,
    }


# --- Build B: update the website ------------------------------------------------------


def _mapping(hubs: list[Hub], rec) -> dict:
    return {h.id: map_hub(h, rec)["entry_id"] for h in hubs}


def _repo_paths() -> tuple[Path, str]:
    s = get_state().settings()
    return Path(s["website_repo"]), s["website_content_dir"]


@router.get("/website")
def website_status() -> dict:
    w = get_state().website()
    repo, content_dir = _repo_paths()
    return {
        "watermark": w["watermark"],
        "last_run": w["last_run"],
        "last_result": w["last_result"],
        "rejected_count": len(w["rejected"]),
        "repo": str(repo),
        "content_dir": content_dir,
    }


class WebsiteRun(BaseModel):
    provider: Literal["local", "cloud", "auto"] | None = None


@router.post("/website/run")
def run_website(body: WebsiteRun) -> dict:
    """Candidates (deterministic) + the advisory AI flag per knowledge note.
    Writes nothing."""
    kb = _kb()
    w = get_state().website()
    rec = _record_or_none(kb)
    hubs = _hubs(kb)
    repo, content_dir = _repo_paths()
    notes, more = knowledge_candidates(kb, hubs, w, _record_location())
    entries = entry_candidates(rec, hubs, w, _mapping(hubs, rec) if rec else {}, repo if repo.is_dir() else None, content_dir)
    used = llm_dispatch.collect_providers()
    rank_candidates([c for c in notes if not c["blocked"]], provider=body.provider)
    for c in notes:
        if c["blocked"]:
            c["suggest"] = False
            c["reason"] = f"mentions non-public hub(s): {', '.join(c['blocked'])}"
    through = notes[-1]["edited"] if notes else w["watermark"]
    return {
        "watermark": w["watermark"],
        "through": through,
        "candidates": entries + notes,
        "more": more,
        "provider_used": llm_dispatch.summarize_providers(used),
    }


class WebsiteReject(BaseModel):
    id: str
    stamp: str  # the candidate's `stamp` (note edited time / entry hash)


@router.post("/website/reject")
def reject_candidate(body: WebsiteReject) -> dict:
    """Remembered until the note's `edited` (or the entry's text) changes."""
    st = get_state()
    w = st.website()
    w["rejected"][body.id] = body.stamp
    st.save_website(w)
    return {"rejected": body.id}


class GenerateItem(BaseModel):
    id: str
    category: str | None = None
    summary: str | None = None


class WebsiteGenerate(BaseModel):
    through: str | None = None
    items: list[GenerateItem] = Field(default_factory=list)


@router.post("/website/generate")
def generate_website(body: WebsiteGenerate) -> dict:
    """Renders every approved item FRESH from the store (privacy + alias
    gating re-checked now, never trusted from the run), commits them onto a
    new `quintacle/content-YYYY-MM-DD` branch in the website repo (dirty
    tree -> 409, nothing written), then moves the website watermark to
    `through`. Zero items = just move the watermark (a run where everything
    was rejected)."""
    kb = _kb()
    st = get_state()
    w = st.website()
    repo, content_dir = _repo_paths()
    hubs = _hubs(kb)
    hub_by_id = {h.id: h for h in hubs}
    rec = _record_or_none(kb)
    mapping = _mapping(hubs, rec) if rec else {}

    files: dict[str, str] = {}
    skipped: list[dict] = []
    published_entries: dict[str, str] = {}
    for item in body.items:
        try:
            if item.id.startswith("note:"):
                folder, _, slug = item.id.removeprefix("note:").rpartition("/")
                rel, text = render_knowledge(kb, folder, slug, hubs, category=item.category or "", summary=item.summary or "")
                files[rel] = text
            elif item.id.startswith("entry:"):
                entry_id = item.id.removeprefix("entry:")
                if rec is None or rec.entry(entry_id) is None:
                    raise ValueError("record entry not found")
                hub = next((hub_by_id[hid] for hid, eid in mapping.items() if eid == entry_id and hid in hub_by_id), None)
                if hub is None or not hub.public or hub.private:
                    raise ValueError("no PUBLIC hub maps to this entry")
                rel = site_path(hub, repo if repo.is_dir() else None, content_dir)
                if hub.kind == "projects":
                    text, dropped = render_project(repo, content_dir, rel, hub, rec, entry_id, hubs)
                else:
                    text, dropped = render_employment(repo, content_dir, rel, hub, rec, entry_id, hubs)
                if dropped:
                    skipped.append({"id": item.id, "reason": f"{len(dropped)} bullet(s) dropped — they name a non-public hub"})
                files[rel] = text
                published_entries[entry_id] = rec.entry_hash(entry_id)
            else:
                raise ValueError("unknown candidate id")
        except (ValueError, OSError) as e:
            skipped.append({"id": item.id, "reason": str(e)})

    result = {"branch": None, "commit": None, "files": [], "skipped": skipped}
    if files:
        try:
            out = write_branch(repo, content_dir, files, f"Quintacle: website content update {clock.today().isoformat()}\n\n" + "\n".join(f"- {p}" for p in sorted(files)))
        except WebsiteRepoError as e:
            raise HTTPException(409, str(e)) from e
        result.update(out)

    new_mark, old_mark = parse_stamp(body.through), parse_stamp(w["watermark"])
    if new_mark is not None and (old_mark is None or new_mark > old_mark):
        w["watermark"] = new_mark.isoformat(timespec="seconds")
    w["entry_hashes"].update(published_entries)
    w["last_run"] = clock.now().isoformat(timespec="seconds")
    w["last_result"] = {k: result.get(k) for k in ("branch", "commit", "files", "skipped")}
    st.save_website(w)
    return {**result, "watermark": w["watermark"], "last_run": w["last_run"]}
