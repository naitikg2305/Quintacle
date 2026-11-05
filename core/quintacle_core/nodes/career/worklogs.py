"""Build A, step 2 — collect what the record hasn't seen yet. Deterministic,
zero model calls.

Work-log notes (`Daily Log/Work Logs`, fields.date) dated AFTER the
watermark (or on/after an owner-picked start when there is none) up to
`until`, split into their `## Session` blocks, each block assigned to the
non-private hubs it mentions by title (graph.title_mentioned — the one
matcher), among the hubs the note is linked to (frontmatter `links` or
materialized graph edges). Skipped, with counts: private notes, hook
placeholder lines/logs ("session ended without a log entry"), sessions that
mention no hub.
"""
from __future__ import annotations

import re
from datetime import date

from ...graph import get_graph_store, title_mentioned
from ...markdown_paths import slugify
from ..kb.privacy import is_private_meta
from ..logs.worklog import WORKLOG_FOLDER
from .hubs import Hub

PLACEHOLDER_RE = re.compile(r"session ended without a log entry", re.IGNORECASE)
_SESSION_RE = re.compile(r"^##\s+Session\b[^\n]*$", re.MULTILINE)
_DATE_IN_TITLE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
MAX_LINES_PER_SESSION = 60
MAX_LINE_CHARS = 400


def _note_date(meta: dict, slug: str) -> date | None:
    raw = (meta.get("fields") or {}).get("date") or meta.get("date")
    for candidate in (raw, slug):
        if candidate is None:
            continue
        if isinstance(candidate, date):
            return candidate
        m = _DATE_IN_TITLE_RE.search(str(candidate))
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                continue
    return None


def _linked_hub_ids(kb, folder: str, slug: str, hubs: list[Hub]) -> set[str]:
    note_id = f"note:{folder}/{slug}"
    by_title = {h.title: h.id for h in hubs}
    linked = {by_title[t] for t in kb.read_links(folder, slug) if t in by_title}
    try:
        hub_ids = {h.id for h in hubs}
        linked |= {e["target_id"] for e in get_graph_store().edges_from(note_id) if e["target_id"] in hub_ids}
    except RuntimeError:
        pass  # graph store not initialized (pure unit use) — frontmatter links suffice
    return linked


def split_sessions(body: str) -> list[tuple[str, str]]:
    """(label, block) per `## Session` heading; one unlabelled block when
    the log has none. Text before the first heading is its own block."""
    heads = list(_SESSION_RE.finditer(body))
    if not heads:
        return [("", body)]
    out = []
    pre = body[: heads[0].start()]
    if pre.strip():
        out.append(("", pre))
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out.append((h.group(0).lstrip("#").strip(), body[h.end() : end]))
    return out


def _source_lines(block: str) -> list[str]:
    lines = []
    for raw in block.split("\n"):
        line = raw.strip()
        if not line or line == "---" or PLACEHOLDER_RE.search(line):
            continue
        if re.match(r"^#\s", line):  # the file's own "# 2026-11-03" title
            continue
        lines.append(line[:MAX_LINE_CHARS])
    return lines[:MAX_LINES_PER_SESSION]


def collect(kb, hubs: list[Hub], *, after: date | None, start: date | None, until: date) -> dict:
    """{groups: {hub_id: {...hub, sessions: [{date, label, lines}]}},
    through, dates, skipped}. `through` = the latest work-log date in the
    window (placeholder-only / unlinked / private days count as covered —
    they were looked at and intentionally contribute nothing)."""
    if after is None and start is None:
        raise ValueError("no watermark yet — pick a start date")
    usable = [h for h in hubs if not h.private]
    folder = "/".join(slugify(p) for p in WORKLOG_FOLDER.split("/"))
    skipped = {"private": [], "placeholder": [], "unlinked_sessions": 0}
    groups: dict[str, dict] = {}
    seen_dates: list[date] = []

    for slug in kb.list_entries(folder):
        meta = kb.read_meta(folder, slug) or {}
        d = _note_date(meta, slug)
        if d is None or d > until:
            continue
        if (after is not None and d <= after) or (after is None and start is not None and d < start):
            continue
        seen_dates.append(d)
        if is_private_meta(meta):
            skipped["private"].append(d.isoformat())
            continue
        body = kb.read(folder, slug) or ""
        body = re.sub(r"^#\s[^\n]*\n", "", body, count=1)  # KBStore's "# Work log - …" title
        sessions = [(label, _source_lines(block)) for label, block in split_sessions(body)]
        sessions = [(label, lines) for label, lines in sessions if lines]
        if not sessions:
            skipped["placeholder"].append(d.isoformat())
            continue
        linked = _linked_hub_ids(kb, folder, slug, usable)
        candidates = [h for h in usable if h.id in linked]
        for label, lines in sessions:
            text = "\n".join([label, *lines])
            hit = [h for h in candidates if title_mentioned(h.title, text)]
            if not hit:
                skipped["unlinked_sessions"] += 1
                continue
            for h in hit:
                g = groups.setdefault(h.id, {"hub": h, "sessions": []})
                g["sessions"].append({"date": d.isoformat(), "label": label, "lines": lines})

    for g in groups.values():
        g["sessions"].sort(key=lambda s: s["date"])
    return {
        "groups": groups,
        "through": max(seen_dates).isoformat() if seen_dates else None,
        "dates": sorted({x.isoformat() for x in seen_dates}),
        "skipped": skipped,
    }
