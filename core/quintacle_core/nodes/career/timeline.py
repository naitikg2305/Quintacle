"""The Career page's read model (docs/reference/career-updates.md, 2026-11-05):
every `Career/**` folder hub as a timeline — orgs, the roles inside them,
contracts, education — with dates, work-log activity, the mapped master-
record entry's bullets and the files sitting in each hub folder.

Deterministic, zero model calls. Everything here is computed from what the
KB and the graph already know: date ranges are parsed in code, day counts
and the monthly sparkline are counted in code, and the record bullets come
from record.py's parser.

A timeline hub is a note whose slug equals its folder's last segment, at
ANY depth under `career/` (`career/minfy/minfy.md`, `career/minfy/sales/
sales.md`, `career/contracts/acme/acme.md`). This is deliberately wider
than hubs.py's updater rule (depth <= 2) — the updaters keep their own
alias table untouched. The record note is never a hub.

Hub `fields` read here (all optional):

  type         employer | role | contract | education | other
               (absent: role when nested under another hub, contract under
               career/contracts/, else employer)
  title / role the position name shown under the org ("AI Engineer")
  start, end   "2026-01", "2026-01-15", "Jan 2026", "2026"; end may be
               "present" (or absent with a start = ongoing)
  location, summary, bullets (list of str), order (int, tie-break)
  public, public_name, record_entry   the career-updates alias fields
"""
from __future__ import annotations

import re
from datetime import date

from ...graph import get_graph_store
from ...markdown_paths import slugify
from ..kb.privacy import is_private_meta
from ..logs.worklog import WORKLOG_FOLDER
from . import record as rec_mod
from .hubs import Hub, map_hub
from .worklogs import _note_date

ROOT = "career"
CONTRACTS = "contracts"
TYPES = ("employer", "role", "contract", "education", "other")
TEXT_FIELDS = ("title", "role", "start", "end", "location", "summary", "public_name", "record_entry")
EDITABLE_FIELDS = (*TEXT_FIELDS, "type", "bullets", "public", "order")
PRESENT_WORDS = {"present", "current", "now", "ongoing"}
SPARK_MONTHS = 12
LAST_DATES = 5
MAX_RECORD_BULLETS = 12

_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_ISO_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_WORDY_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$")


def parse_when(raw) -> tuple[date | None, str]:
    """(date, precision) where precision is day|month|year|present|"" —
    a month/year collapses to its first day for sorting."""
    if raw is None or raw == "":
        return None, ""
    if isinstance(raw, date):
        return raw, "day"
    text = str(raw).strip()
    if text.lower() in PRESENT_WORDS:
        return None, "present"
    if m := _ISO_RE.match(text):
        y, mo, d = int(m.group(1)), m.group(2), m.group(3)
        try:
            if d:
                return date(y, int(mo), int(d)), "day"
            if mo:
                return date(y, int(mo), 1), "month"
            return date(y, 1, 1), "year"
        except ValueError:
            return None, ""
    if m := _WORDY_RE.match(text):
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            return date(int(m.group(2)), mo, 1), "month"
    return None, ""


def _label(d: date | None, precision: str) -> str:
    if precision == "present":
        return "Present"
    if d is None:
        return ""
    if precision == "year":
        return str(d.year)
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def date_range(start_raw, end_raw) -> dict:
    """Display string + sort keys, all decided here (the page never does
    date math): an end of "present" — or a start with no end — is ongoing."""
    start, sp = parse_when(start_raw)
    end, ep = parse_when(end_raw)
    present = ep == "present" or (start is not None and end is None and ep == "")
    s_label = _label(start, sp)
    e_label = "Present" if present else _label(end, ep)
    if s_label and e_label and s_label != e_label:
        display = f"{s_label} – {e_label}"
    else:
        display = s_label or e_label
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end and not present else None,
        "present": present,
        "display": display,
    }


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "on"} if value is not None else False


def _bullets(value) -> list[str]:
    if isinstance(value, list):
        return [str(b).strip() for b in value if str(b).strip()]
    if isinstance(value, str) and value.strip():
        return [ln.strip().lstrip("-*• ").strip() for ln in value.split("\n") if ln.strip()]
    return []


def is_timeline_hub(folder: str, slug: str) -> bool:
    parts = folder.split("/")
    return parts[0] == ROOT and len(parts) >= 2 and parts[-1] == slug


def _worklog_folder() -> str:
    return "/".join(slugify(p) for p in WORKLOG_FOLDER.split("/"))


def _worklog_links(kb, hubs: dict[str, dict]) -> dict[str, set[date]]:
    """hub id -> set of work-log days that link to it (frontmatter `links`
    by title, or a materialized graph edge). Private logs never count."""
    by_title: dict[str, set[str]] = {}
    for hid, h in hubs.items():
        by_title.setdefault(h["title"], set()).add(hid)
    days: dict[str, set[date]] = {hid: set() for hid in hubs}
    folder = _worklog_folder()
    try:
        graph = get_graph_store()
    except RuntimeError:
        graph = None
    for slug in kb.list_entries(folder):
        meta = kb.read_meta(folder, slug) or {}
        if is_private_meta(meta):
            continue
        d = _note_date(meta, slug)
        if d is None:
            continue
        linked: set[str] = set()
        for t in meta.get("links") or []:
            linked |= by_title.get(str(t), set())
        if graph is not None:
            linked |= {e["target_id"] for e in graph.edges_from(f"note:{folder}/{slug}") if e["target_id"] in hubs}
        for hid in linked:
            days[hid].add(d)
    return days


def _activity(dates: set[date], today: date) -> dict:
    ordered = sorted(dates, reverse=True)
    months = []
    y, m = today.year, today.month
    for _ in range(SPARK_MONTHS):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    counts = {k: 0 for k in months}
    for d in dates:
        if (d.year, d.month) in counts:
            counts[(d.year, d.month)] += 1
    return {
        "days": len(dates),
        "last": [d.isoformat() for d in ordered[:LAST_DATES]],
        "spark": [{"month": f"{y:04d}-{m:02d}", "days": counts[(y, m)]} for y, m in months],
    }


def _files(kb, folder: str, slug: str, child_folders: set[str]) -> list[dict]:
    """What sits in the hub folder besides the hub note: other notes, raw
    files (PDFs, offer letters), `assets/` contents, and non-hub subfolders."""
    out: list[dict] = []
    for s in kb.list_entries(folder):
        if s == slug:
            continue
        meta = kb.read_meta(folder, s) or {}
        content = kb.read(folder, s) or ""
        title = content.split("\n", 1)[0].lstrip("# ").strip() or s
        out.append({"kind": "note", "name": title, "folder": folder, "slug": s, "private": is_private_meta(meta)})
    for name in kb.list_files(folder):
        out.append({"kind": "file", "name": name, "folder": folder, "path": name})
    assets = f"{folder}/assets"
    for name in kb.list_files(assets):
        out.append({"kind": "file", "name": name, "folder": folder, "path": f"assets/{name}"})
    prefix = folder + "/"
    for f in kb.list_folders():
        if not f.startswith(prefix) or "/" in f[len(prefix):]:
            continue
        if f in child_folders or f == assets:
            continue
        out.append({"kind": "folder", "name": f[len(prefix):], "folder": f})
    return out


def _sort_key(node: dict):
    # current first, then most recent end, then most recent start; `order` breaks ties
    r = node["range"]
    order = node.get("order")
    order = order if isinstance(order, int) else 0
    return (
        0 if r["present"] else 1,
        -(date.fromisoformat(r["end"]).toordinal()) if r["end"] else 0,
        -(date.fromisoformat(r["start"]).toordinal()) if r["start"] else 0,
        order,
        node["title"].lower(),
    )


def build_timeline(kb, rec, record_location: tuple[str, str] | None, today: date) -> dict:
    hubs: dict[str, dict] = {}
    for n in kb.notes_index():
        folder, slug = n["folder"], n["slug"]
        if not is_timeline_hub(folder, slug):
            continue
        if record_location and (folder, slug) == record_location:
            continue
        meta = kb.read_meta(folder, slug) or {}
        fields = meta.get("fields") or {}
        hubs[f"note:{folder}/{slug}"] = {
            "id": f"note:{folder}/{slug}",
            "folder": folder,
            "slug": slug,
            "title": n["title"],
            "private": is_private_meta(meta),
            "fields": fields,
        }

    folder_to_id = {h["folder"]: hid for hid, h in hubs.items()}

    def parent_of(folder: str) -> str | None:
        parts = folder.split("/")
        for i in range(len(parts) - 1, 1, -1):
            hid = folder_to_id.get("/".join(parts[:i]))
            if hid:
                return hid
        return None

    worklog_days = _worklog_links(kb, hubs)
    nodes: dict[str, dict] = {}
    for hid, h in hubs.items():
        f = h["fields"]
        parent = parent_of(h["folder"])
        raw_type = str(f.get("type") or "").strip().lower()
        if raw_type in TYPES:
            kind = raw_type
        elif parent:
            kind = "role"
        elif h["folder"].split("/")[1:2] == [CONTRACTS]:
            kind = "contract"
        else:
            kind = "employer"
        order = f.get("order")
        try:
            order = int(order) if order not in (None, "") else None
        except (TypeError, ValueError):
            order = None
        nodes[hid] = {
            "id": hid,
            "folder": h["folder"],
            "slug": h["slug"],
            "title": h["title"],
            "type": kind,
            "role": str(f.get("role") or f.get("title") or "").strip(),
            "location": str(f.get("location") or "").strip(),
            "summary": str(f.get("summary") or "").strip(),
            "bullets": _bullets(f.get("bullets")),
            "start_raw": "" if f.get("start") is None else str(f.get("start")),
            "end_raw": "" if f.get("end") is None else str(f.get("end")),
            "range": date_range(f.get("start"), f.get("end")),
            "order": order,
            "private": h["private"],
            "public": _truthy(f.get("public")),
            "public_name": str(f.get("public_name") or "").strip(),
            "record_entry_field": str(f.get("record_entry") or "").strip(),
            "parent": parent,
            "children": [],
        }

    # Roles only count a day when the log ALSO links the parent org: a role
    # titled "Sales" would otherwise collect every log that says "sales".
    own_days: dict[str, set[date]] = {}
    for hid, node in nodes.items():
        days = worklog_days.get(hid, set())
        if node["parent"]:
            days = days & worklog_days.get(node["parent"], set())
        own_days[hid] = days

    for hid, node in nodes.items():
        hub = Hub(
            folder=node["folder"], slug=node["slug"], title=node["title"], kind=ROOT, private=node["private"],
            record_entry=node["record_entry_field"] or None, public=node["public"],
            public_name=node["public_name"] or node["title"], public_repo="", public_slug="",
        )
        mapping = map_hub(hub, rec)
        entry = None
        if mapping.get("entry_id") and rec is not None:
            e = rec.entry(mapping["entry_id"])
            bullets = [b for b in rec_mod.entry_bullets(rec, e.id) if b["kind"] != "other"] or rec_mod.entry_bullets(rec, e.id)
            entry = {
                "id": e.id,
                "title": e.title,
                "how": mapping["how"],
                "tech": e.tech,
                "bullets": [{"text": b["text"], "kind": b["kind"]} for b in bullets[:MAX_RECORD_BULLETS]],
            }
        node["record"] = entry
        node["record_candidates"] = mapping.get("candidates", [])[:8]

    child_folders: dict[str, set[str]] = {hid: set() for hid in nodes}
    for hid, node in nodes.items():
        if node["parent"]:
            nodes[node["parent"]]["children"].append(node)
            # The nearest hub ancestor owns the role folder (and any plain
            # folders between them are NOT listed as files twice).
            parent_folder = nodes[node["parent"]]["folder"]
            rel = node["folder"][len(parent_folder) + 1 :].split("/")[0]
            child_folders[node["parent"]].add(f"{parent_folder}/{rel}")

    def finish(node: dict) -> set[date]:
        days = set(own_days[node["id"]])
        for c in node["children"]:
            days |= finish(c)
        node["children"].sort(key=_sort_key)
        node["activity"] = _activity(days, today)
        node["own_days"] = len(own_days[node["id"]])
        node["files"] = _files(kb, node["folder"], node["slug"], child_folders[node["id"]])
        node["file_count"] = len(node["files"]) + sum(c["file_count"] for c in node["children"])
        # An org without its own dates spans its roles'.
        if not node["range"]["display"] and node["children"]:
            starts = [c["range"]["start"] for c in node["children"] if c["range"]["start"]]
            ends = [c["range"]["end"] for c in node["children"] if c["range"]["end"]]
            present = any(c["range"]["present"] for c in node["children"])
            s = min(starts) if starts else None
            e = None if present else (max(ends) if ends else None)
            node["range"] = date_range(s[:7] if s else None, "present" if present else (e[:7] if e else None))
            node["range"]["derived"] = True
        return days

    top = [n for n in nodes.values() if not n["parent"]]
    for n in top:
        finish(n)
    top.sort(key=_sort_key)
    for n in nodes.values():
        n.pop("parent", None)
    counts = {t: sum(1 for n in top if n["type"] == t) for t in TYPES}
    return {"today": today.isoformat(), "items": top, "counts": counts, "record_present": rec is not None}


def find_hub_note(kb, folder: str) -> tuple[str, str] | None:
    """(folder_slug, slug) of the timeline hub living in `folder`."""
    folder_slug = "/".join(slugify(p) for p in folder.split("/") if p.strip())
    slug = folder_slug.rsplit("/", 1)[-1]
    if not is_timeline_hub(folder_slug, slug) or kb.read_meta(folder_slug, slug) is None:
        return None
    return folder_slug, slug


def clean_updates(sent: dict) -> dict:
    """Request fields -> set_fields updates: an empty string / empty list
    clears that key (None = remove), bullets trimmed, type validated."""
    out: dict = {}
    for key, value in sent.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key == "type":
            v = (value or "").strip().lower() if isinstance(value, str) else value
            if v in (None, ""):
                out[key] = None
                continue
            if v not in TYPES:
                raise ValueError(f"type must be one of {', '.join(TYPES)}")
            out[key] = v
        elif key == "bullets":
            b = _bullets(value) if value is not None else []
            out[key] = b or None
        elif key == "public":
            out[key] = None if value is None else bool(value)
        elif key == "order":
            out[key] = None if value in (None, "") else int(value)
        else:
            v = "" if value is None else str(value).strip()
            if key in ("start", "end") and v and parse_when(v)[1] == "":
                raise ValueError(f"{key}: can't read {v!r} as a date (try 2026-01, Jan 2026 or present)")
            out[key] = v or None
    return out
