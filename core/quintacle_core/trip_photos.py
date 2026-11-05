"""Trip ↔ photos (2026-11-05): photos taken during a planned trip attach to
that trip automatically. Deterministic, no model call anywhere.

## The rule

A photo note belongs to a trip plan P (a KB note under Fun/Travel/Planned/**)
when BOTH hold:

1. its capture DAY is inside [P.start, P.end] (inclusive), and
2. P has no destinations, OR one of P's destination tokens equals the
   photo's city / state / country / continent (case- and accent-
   insensitive, compared as place_slug()s) — so "Austria" catches a
   Salzburg photo whose `place.country` is Austria.

Edge: `note:<photo> --during_trip--> note:<plan>`, source_of_edge
`trip_photos`. Idempotent (GraphEdgeStore.create_edge) and re-synced in
both directions: a photo save recomputes the photo's outgoing edges, a plan
save recomputes the plan's incoming ones — stale edges from THIS module are
removed, nobody else's.

## Where the inputs come from (code, never a model)

- Photo capture day: `file_meta[].taken` of an image asset (EXIF, already
  ET-normalized by file_meta._iso when the timestamp is tz-aware), else the
  `taken YYYY-MM-DD` on the 📍 place line photo_place bakes. No capture
  date → never linked (the save date says nothing about when it was taken).
- Photo place: frontmatter `place: {city, state, country, continent}`.
- Plan window: `fields.start` / `fields.end`; when missing (plans dropped
  via AI often lack them) a small regex set over the BODY — explicit ranges
  first ("2027-05-12 – 2027-05-21", "May 12 – May 21, 2027", "May 12–21,
  2027", "12–21 May 2027"), else the min..max of standalone full dates when
  they span ≤ 60 days. A lone end/start falls back to the other.
- Plan destinations: `fields.destinations` (comma list). With none, the body
  is checked ONLY against city names that already exist as place nodes
  (place_graph's virtual `place:*/*/<city>` ids + real `places/**` notes) —
  a city nobody has a node for is never guessed out of prose.

Hook: place_graph.link_note_places calls link_note_trip_photos at the end of
every non-dry-run save, so every path that links places (POST /kb/entries,
/kb/entries/with-asset, /kb/entry/asset, /travel/planned/move, MCP writes
inside their staged session) also syncs trip photos.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

KIND = "during_trip"
SOURCE_OF_EDGE = "trip_photos"
MAX_FALLBACK_SPAN_DAYS = 60

_ASSET_LINE_RE = re.compile(r"^\[asset\]\(([^)]+)\)\s*$")
_PLACE_TAKEN_RE = re.compile(r"taken (\d{4}-\d{2}-\d{2})")

# --------------------------------------------------------------- dates

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MON = r"(?P<{n}>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(?P<{n}>\d{{1,2}})(?:st|nd|rd|th)?"
_YEAR = r"(?P<{n}>\d{{4}})"
_SEP = r"\s*(?:–|—|-|to|through|thru|until)\s*"
_ISO = r"(?P<{n}>\d{{4}}-\d{{2}}-\d{{2}})"


def _p(template: str, **names: str) -> str:
    return template.format(**names)


_RANGE_RES = [
    # 2027-05-12 – 2027-05-21
    re.compile(_p(_ISO, n="a") + _SEP + _p(_ISO, n="b")),
    # May 12[, 2027] – May 21, 2027
    re.compile(
        r"\b" + _p(_MON, n="m1") + r"\s+" + _p(_DAY, n="d1") + r"(?:,?\s+" + _p(_YEAR, n="y1") + r")?"
        + _SEP + _p(_MON, n="m2") + r"\s+" + _p(_DAY, n="d2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b",
        re.IGNORECASE,
    ),
    # May 12–21, 2027
    re.compile(
        r"\b" + _p(_MON, n="m1") + r"\s+" + _p(_DAY, n="d1") + _SEP + _p(_DAY, n="d2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b",
        re.IGNORECASE,
    ),
    # 12 May [2027] – 21 May 2027
    re.compile(
        r"\b" + _p(_DAY, n="d1") + r"\s+" + _p(_MON, n="m1") + r"(?:,?\s+" + _p(_YEAR, n="y1") + r")?"
        + _SEP + _p(_DAY, n="d2") + r"\s+" + _p(_MON, n="m2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b",
        re.IGNORECASE,
    ),
    # 12–21 May 2027
    re.compile(
        r"\b" + _p(_DAY, n="d1") + _SEP + _p(_DAY, n="d2") + r"\s+" + _p(_MON, n="m2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b",
        re.IGNORECASE,
    ),
]

_SINGLE_RES = [
    re.compile(r"(?<!\d)" + _p(_ISO, n="a") + r"(?!\d)"),
    re.compile(r"\b" + _p(_MON, n="m2") + r"\s+" + _p(_DAY, n="d2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b", re.IGNORECASE),
    re.compile(r"\b" + _p(_DAY, n="d2") + r"\s+" + _p(_MON, n="m2") + r",?\s+" + _p(_YEAR, n="y2") + r"\b", re.IGNORECASE),
]


def _iso(s) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except (ValueError, TypeError):
        return None


def _mdy(month: str | None, day: str | None, year: int | None) -> date | None:
    if not month or not day or year is None:
        return None
    try:
        return date(year, _MONTHS[month.lower().rstrip(".")], int(day))
    except (KeyError, ValueError):
        return None


def _range_from_match(m: re.Match) -> tuple[date, date] | None:
    g = m.groupdict()
    if g.get("a"):
        start, end = _iso(g["a"]), _iso(g.get("b"))
    else:
        y2 = int(g["y2"])
        m2 = g.get("m2") or g.get("m1")
        m1 = g.get("m1") or m2
        end = _mdy(m2, g["d2"], y2)
        y1 = int(g["y1"]) if g.get("y1") else y2
        start = _mdy(m1, g["d1"], y1)
        if start and end and start > end and not g.get("y1"):
            start = _mdy(m1, g["d1"], y2 - 1)  # "Dec 28 – Jan 3, 2028"
    if start and end and start <= end:
        return start, end
    return None


def parse_body_dates(text: str) -> tuple[date | None, date | None]:
    """A trip's (start, end) from free text. Explicit ranges win (the first
    one found); else every standalone full date, min..max, when the span
    is ≤ MAX_FALLBACK_SPAN_DAYS. (None, None) when nothing usable."""
    text = text or ""
    for rx in _RANGE_RES:
        for m in rx.finditer(text):
            r = _range_from_match(m)
            if r:
                return r
    found: list[date] = []
    for rx in _SINGLE_RES:
        for m in rx.finditer(text):
            g = m.groupdict()
            d = _iso(g["a"]) if g.get("a") else _mdy(g.get("m2"), g.get("d2"), int(g["y2"]))
            if d:
                found.append(d)
    if found and (max(found) - min(found)) <= timedelta(days=MAX_FALLBACK_SPAN_DAYS):
        return min(found), max(found)
    return None, None


def plan_window(meta: dict, body: str) -> tuple[date | None, date | None]:
    fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
    start, end = _iso(fields.get("start")) if fields.get("start") else None, _iso(fields.get("end")) if fields.get("end") else None
    if start is None or end is None:
        b_start, b_end = parse_body_dates(body)
        start = start or b_start
        end = end or b_end
        start = start or end
        end = end or start
    if start and end and start > end:
        return None, None
    return start, end


# --------------------------------------------------------------- places


def _slug(name) -> str:
    from .place_graph import place_slug

    return place_slug(str(name or ""))


def _dest_tokens(raw) -> list[str]:
    from .place_graph import _SPLIT_RE

    if isinstance(raw, (list, tuple)):
        raw = ",".join(str(d) for d in raw)
    return [s for s in (_slug(t) for t in _SPLIT_RE.split(str(raw or ""))) if s]


def _known_city_names(gs, store) -> dict[str, str]:
    """slug → display name for every city that already exists as a place
    node (virtual place_graph city ids + real `places/**` notes)."""
    names: dict[str, str] = {}
    try:
        rows = gs.conn.execute(
            "SELECT source_id AS id FROM edges WHERE source_id LIKE 'place:%' "
            "UNION SELECT target_id FROM edges WHERE target_id LIKE 'place:%'"
        ).fetchall()
        for r in rows:
            parts = r["id"].partition(":")[2].split("/")
            if len(parts) == 3 and parts[2] and parts[2] != "_":
                names.setdefault(parts[2], " ".join(w.capitalize() for w in parts[2].split("-")))
    except Exception:
        pass
    try:
        for n in store.notes_index():
            folder = n["folder"]
            if folder == "places" or folder.startswith("places/"):
                s = _slug(n["title"])
                if s:
                    names[s] = n["title"]
    except Exception:
        pass
    return names


def plan_destinations(meta: dict, body: str, known_cities: dict[str, str] | None) -> list[str]:
    fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
    tokens = _dest_tokens(fields.get("destinations"))
    if tokens or not known_cities:
        return tokens
    from .graph import title_mentioned

    return sorted(s for s, name in known_cities.items() if title_mentioned(name, body))


# --------------------------------------------------------------- notes


def _image_assets(content: str) -> list[str]:
    from .nodes.kb.photo_place import is_image_name

    return [m.group(1) for line in content.splitlines() if (m := _ASSET_LINE_RE.match(line.strip())) and is_image_name(m.group(1))]


def photo_info(meta: dict, content: str) -> dict | None:
    """{day, slugs, asset} for a photo note, or None (not a photo / no
    capture date)."""
    images = _image_assets(content)
    place = meta.get("place") if isinstance(meta.get("place"), dict) else None
    if not images and place is None:
        return None
    day: date | None = None
    for m in meta.get("file_meta") or []:
        if isinstance(m, dict) and m.get("kind") == "image" and m.get("taken"):
            day = _iso(m["taken"])
            if day:
                break
    if day is None:
        for line in content.splitlines():
            if "<!-- place -->" in line and (mt := _PLACE_TAKEN_RE.search(line)):
                day = _iso(mt.group(1))
                break
    if day is None:
        return None
    slugs = {_slug(place.get(k)) for k in ("city", "state", "country", "continent")} - {""} if place else set()
    return {"day": day, "slugs": slugs, "asset": images[0] if images else None}


def matches(photo: dict, plan: dict) -> bool:
    if not plan["start"] or not plan["end"] or not (plan["start"] <= photo["day"] <= plan["end"]):
        return False
    return not plan["dests"] or bool(set(plan["dests"]) & photo["slugs"])


def _read(path: Path) -> frontmatter.Post | None:
    try:
        return frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _note_id(store, path: Path) -> str:
    folder = str(path.parent.relative_to(store.root)).replace("\\", "/")
    return f"note:{folder}/{path.stem}"


def _is_plan_path(store, path: Path) -> bool:
    from .place_graph import is_planned_folder

    folder = str(path.parent.relative_to(store.root)).replace("\\", "/")
    if not is_planned_folder(folder):
        return False
    parts = folder.split("/")
    return "assets" not in parts and not path.stem.startswith("about-") and not path.name.startswith("_")


def _plan_from(store, path: Path, post: frontmatter.Post, known: dict[str, str] | None) -> dict:
    start, end = plan_window(dict(post.metadata), post.content)
    return {
        "id": _note_id(store, path),
        "start": start,
        "end": end,
        "dests": plan_destinations(dict(post.metadata), post.content, known),
    }


def _all_plans(store, known: dict[str, str] | None) -> list[dict]:
    from .markdown_paths import resolve_nested
    from .nodes.travel.states import PLANNED

    base = resolve_nested(store.root, PLANNED)
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.rglob("*.md")):
        if not _is_plan_path(store, path):
            continue
        post = _read(path)
        if post is not None:
            out.append(_plan_from(store, path, post, known))
    return out


def _all_photos(store) -> list[tuple[str, dict]]:
    out = []
    for path in sorted(Path(store.root).rglob("*.md")):
        rel = path.relative_to(store.root).parts
        if "assets" in rel[:-1] or any(p.startswith(".") for p in rel):
            continue
        if _is_plan_path(store, path):
            continue
        post = _read(path)
        if post is None:
            continue
        info = photo_info(dict(post.metadata), post.content)
        if info:
            out.append((_note_id(store, path), info))
    return out


# --------------------------------------------------------------- edges


def _graph_store():
    from .graph import get_graph_store

    return get_graph_store()


def _sync(gs, current: list, wanted: set[tuple[str, str]], dry_run: bool) -> tuple[list[dict], list[dict]]:
    created, removed = [], []
    have = {(r["source_id"], r["target_id"]) for r in current}
    for r in current:
        if (r["source_id"], r["target_id"]) not in wanted:
            removed.append({"source": r["source_id"], "target": r["target_id"]})
            if not dry_run:
                gs.remove_edge(r["id"])
    for s, t in sorted(wanted - have):
        if gs._existing_edge_id(s, t, KIND) is not None:
            continue
        created.append({"source": s, "target": t})
        if not dry_run:
            gs.create_edge(s, t, KIND, SOURCE_OF_EDGE)
    return created, removed


def _edges_where(gs, column: str, node_id: str) -> list:
    return gs.conn.execute(
        f"SELECT id, source_id, target_id FROM edges WHERE kind = ? AND source_of_edge = ? AND {column} = ?",
        (KIND, SOURCE_OF_EDGE, node_id),
    ).fetchall()


def sync_photo(store, path: Path, gs, *, dry_run: bool = False) -> tuple[list[dict], list[dict]]:
    photo_id = _note_id(store, path)
    post = _read(path)
    info = photo_info(dict(post.metadata), post.content) if post is not None else None
    wanted: set[tuple[str, str]] = set()
    if info:
        known = _known_city_names(gs, store)
        wanted = {(photo_id, p["id"]) for p in _all_plans(store, known) if matches(info, p)}
    return _sync(gs, _edges_where(gs, "source_id", photo_id), wanted, dry_run)


def sync_plan(store, path: Path, gs, *, dry_run: bool = False) -> tuple[list[dict], list[dict]]:
    post = _read(path)
    plan = _plan_from(store, path, post, _known_city_names(gs, store)) if post is not None else None
    plan_id = _note_id(store, path)
    wanted: set[tuple[str, str]] = set()
    if plan and plan["start"]:
        wanted = {(pid, plan_id) for pid, info in _all_photos(store) if matches(info, plan)}
    return _sync(gs, _edges_where(gs, "target_id", plan_id), wanted, dry_run)


def link_note_trip_photos(store, folder_slug: str, slug: str, *, graph_store=None) -> list[dict]:
    """THE save hook: a Planned note pulls in every matching photo; any
    other note (re-)syncs its own during_trip edges (none when it isn't a
    dated photo). Returns created edges. Never raises."""
    try:
        gs = graph_store or _graph_store()
        path = store.entry_path(folder_slug, slug)
        if not path.is_file():
            return []
        if _is_plan_path(store, path):
            return sync_plan(store, path, gs)[0]
        return sync_photo(store, path, gs)[0]
    except Exception as exc:
        logger.warning("trip-photo linking failed for %s/%s: %s", folder_slug, slug, exc)
        return []


def backfill_trip_photos(store, *, dry_run: bool = True, graph_store=None) -> dict:
    """Re-sync every plan's photos in one pass (photos scanned once), and
    drop trip_photos edges whose plan no longer exists."""
    gs = graph_store or _graph_store()
    known = _known_city_names(gs, store)
    plans = _all_plans(store, known)
    photos = _all_photos(store)
    plan_ids = {p["id"] for p in plans}
    created: list[dict] = []
    removed: list[dict] = []
    per_plan: dict[str, int] = {}
    for plan in plans:
        wanted = {(pid, plan["id"]) for pid, info in photos if matches(info, plan)} if plan["start"] else set()
        per_plan[plan["id"]] = len(wanted)
        c, r = _sync(gs, _edges_where(gs, "target_id", plan["id"]), wanted, dry_run)
        created += c
        removed += r
    orphans = [
        r for r in gs.conn.execute(
            "SELECT id, source_id, target_id FROM edges WHERE kind = ? AND source_of_edge = ?", (KIND, SOURCE_OF_EDGE)
        ).fetchall()
        if r["target_id"] not in plan_ids
    ]
    c, r = _sync(gs, orphans, set(), dry_run)
    removed += r
    return {
        "dry_run": dry_run,
        "plans": len(plans),
        "photos_scanned": len(photos),
        "created": len(created),
        "removed": len(removed),
        "per_plan": per_plan,
        "sample": created[:20],
    }


def photos_for_plan(store, folder_slug: str, slug: str, *, limit: int = 6, graph_store=None) -> tuple[int, list[dict]]:
    """(count, first `limit` photos as {folder, slug, asset}) for a plan —
    straight off the during_trip edges, skipping notes that vanished."""
    try:
        gs = graph_store or _graph_store()
        rows = gs.conn.execute(
            "SELECT source_id FROM edges WHERE kind = ? AND target_id = ? ORDER BY source_id",
            (KIND, f"note:{folder_slug}/{slug}"),
        ).fetchall()
    except Exception:
        return 0, []
    count, photos = 0, []
    for r in rows:
        folder, _, s = r["source_id"].removeprefix("note:").rpartition("/")
        path = store.entry_path(folder, s)
        if not path.is_file():
            continue
        count += 1
        if len(photos) < limit:
            post = _read(path)
            images = _image_assets(post.content) if post is not None else []
            photos.append({"folder": folder, "slug": s, "asset": images[0] if images else None})
    return count, photos
