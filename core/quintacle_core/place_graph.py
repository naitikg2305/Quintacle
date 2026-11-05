"""The place hierarchy in the graph (2026-11-05) — "link everything on the
graph so weak AIs can answer stuff", baked at save time.

Deterministic, no model call anywhere. Every photo / experience / trip plan
that names a city gets a `located_in` edge to that city, and the city chains
up with `part_of` edges: city → country → continent. A weak model asked
"photos from Europe" then only has to land on the Europe node — retrieval's
graph lane (retrieval.RetrievalIndex._neighbors) walks the part_of tree down
and hands it every photo/experience/plan located anywhere inside.

## Node ids (graph-only, no files written)

    place:<continent>                       e.g. place:europe
    place:<continent>/<country>             e.g. place:europe/austria
    place:<continent>/<country>/<city>      e.g. place:europe/austria/vienna

Each segment is `place_slug()`-ed; an unknown part is `_` — a city whose
country nobody knows (an experience only carries a city) is
`place:_/_/<city>`, and the moment some later save learns the country
(a geocoded photo from the same city) every edge on the `_/_` node is
re-pointed to the real hierarchical id. A `_` continent/country node is never
created itself. The level is the id's depth (1/2/3 segments).

A REAL Places note (KB `places/**`, the emergent ones graph_capture writes)
whose title matches the place name case-insensitively is used INSTEAD of the
virtual node: the link goes to `note:places/...`, and that note gets the
part_of edge to its country.

Display names live in the retrieval index (title of the place node, with a
one-line summary like "City in Austria, Europe — 3 photos, 1 experience") —
no registry file; /graph reads the label back from there and falls back to a
title-cased slug.

Edges are idempotent (GraphEdgeStore.create_edge) and a source's
`located_in` edges re-sync on every save (stale ones from THIS module — tag
`source_of_edge="place_graph"` — removed); `part_of` edges are never removed
(they're facts about geography, not about one note).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import frontmatter

logger = logging.getLogger(__name__)

LOCATED_IN = "located_in"
PART_OF = "part_of"
SOURCE_OF_EDGE = "place_graph"
UNKNOWN = "_"
LEVELS = {1: "continent", 2: "country", 3: "city"}

PLANNED_PREFIX = "fun/travel/planned"
_PLACES_FOLDER = "places"


def place_slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def is_place_id(node_id: str) -> bool:
    return node_id.startswith("place:")


def level_of(place_id: str) -> str | None:
    if not is_place_id(place_id):
        return None
    return LEVELS.get(len(place_id.partition(":")[2].split("/")))


def _title_from_slug(place_id: str) -> str:
    last = place_id.partition(":")[2].rsplit("/", 1)[-1]
    return " ".join(w.capitalize() for w in last.split("-")) or place_id


def is_planned_folder(folder_slug: str) -> bool:
    f = (folder_slug or "").strip("/").lower()
    return f == PLANNED_PREFIX or f.startswith(PLANNED_PREFIX + "/")


# --------------------------------------------------------------- resolution


@dataclass
class _Ref:
    id: str
    name: str
    level: str
    virtual: bool


class _Ctx:
    """Per-call state: the graph store, the KB store (for real Places notes
    + privacy) and a cache of what's been resolved."""

    def __init__(self, store, graph_store, dry_run: bool = False):
        self.store = store
        self.gs = graph_store
        self.dry_run = dry_run
        self._real: dict[str, str] | None = None
        self.touched: set[str] = set()
        self.names: dict[str, str] = {}
        self.planned_edges: set[tuple[str, str, str]] = set()

    def real_places(self) -> dict[str, str]:
        if self._real is None:
            self._real = {}
            if self.store is not None:
                try:
                    for n in self.store.notes_index():
                        folder = n["folder"]
                        if folder == _PLACES_FOLDER or folder.startswith(_PLACES_FOLDER + "/"):
                            self._real.setdefault((n["title"] or "").strip().lower(), f"note:{folder}/{n['slug']}")
                except Exception:
                    pass
        return self._real

    def edge_exists(self, source: str, target: str, kind: str) -> bool:
        if (source, target, kind) in self.planned_edges:
            return True
        return self.gs._existing_edge_id(source, target, kind) is not None


def _real_or_virtual(ctx: _Ctx, name: str, virtual_id: str, level: str) -> _Ref:
    real = ctx.real_places().get(name.strip().lower())
    if real:
        return _Ref(real, name, level, False)
    return _Ref(virtual_id, name, level, True)


def _known_city_id(ctx: _Ctx, city_slug: str) -> str | None:
    """A hierarchical city node (country known) already in the graph with
    this slug — how an experience (city only) finds its country without
    any model call."""
    rows = ctx.gs.conn.execute(
        "SELECT DISTINCT source_id FROM edges WHERE kind = ? AND source_id LIKE ?",
        (PART_OF, f"place:%/{city_slug}"),
    ).fetchall()
    for r in sorted(r["source_id"] for r in rows):
        parts = r.partition(":")[2].split("/")
        if len(parts) == 3 and parts[2] == city_slug and UNKNOWN not in parts[:2]:
            return r
    for (s, t, k) in sorted(ctx.planned_edges):
        if k == PART_OF and s.startswith("place:") and s.endswith("/" + city_slug):
            parts = s.partition(":")[2].split("/")
            if len(parts) == 3 and UNKNOWN not in parts[:2]:
                return s
    return None


def _parent_of(ctx: _Ctx, node_id: str) -> str | None:
    row = ctx.gs.conn.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND kind = ? ORDER BY created_at LIMIT 1", (node_id, PART_OF)
    ).fetchone()
    return row["target_id"] if row else None


def resolve_chain(ctx: _Ctx, city: str | None, country: str | None, continent: str | None = None) -> list[_Ref]:
    """[city?, country?, continent?] refs (most specific first) for these
    names. Deterministic: the continent comes from photo_place's table; an
    unknown country for a city is borrowed from an existing city node with
    the same name, else the city stays `place:_/_/<city>`."""
    from .nodes.kb.photo_place import continent_for

    city = (city or "").strip()
    country = (country or "").strip()
    continent = (continent or "").strip() or (continent_for(country) if country else None) or ""
    chain: list[_Ref] = []
    cont_slug = place_slug(continent) if continent else UNKNOWN
    country_slug = place_slug(country) if country else UNKNOWN

    if city:
        cslug = place_slug(city)
        if not cslug:
            city = ""
        elif country:
            chain.append(_real_or_virtual(ctx, city, f"place:{cont_slug}/{country_slug}/{cslug}", "city"))
        else:
            real = ctx.real_places().get(city.lower())
            known = None if real else _known_city_id(ctx, cslug)
            if real:
                chain.append(_Ref(real, city, "city", False))
            elif known:
                chain.append(_Ref(known, city, "city", True))
                parts = known.partition(":")[2].split("/")
                cont_slug, country_slug = parts[0], parts[1]
                country_id = f"place:{cont_slug}/{country_slug}"
                chain.append(_Ref(country_id, ctx.names.get(country_id) or _index_title(country_id), "country", True))
                cont_id = f"place:{cont_slug}"
                chain.append(_Ref(cont_id, ctx.names.get(cont_id) or _index_title(cont_id), "continent", True))
                return chain
            else:
                chain.append(_Ref(f"place:{UNKNOWN}/{UNKNOWN}/{cslug}", city, "city", True))
    if country and country_slug:
        chain.append(_real_or_virtual(ctx, country, f"place:{cont_slug}/{country_slug}", "country"))
    if continent and cont_slug != UNKNOWN:
        chain.append(_real_or_virtual(ctx, continent, f"place:{cont_slug}", "continent"))
    return chain


def _index_title(node_id: str) -> str:
    try:
        from .retrieval import get_retrieval_index

        row = get_retrieval_index().get_node(node_id)
        if row and row.get("title"):
            return row["title"]
    except Exception:
        pass
    return _title_from_slug(node_id)


# --------------------------------------------------------------- writing


def _create(ctx: _Ctx, source: str, target: str, kind: str, out: list[dict]) -> None:
    if source == target or ctx.edge_exists(source, target, kind):
        return
    if ctx.dry_run:
        ctx.planned_edges.add((source, target, kind))
    else:
        ctx.gs.create_edge(source, target, kind, SOURCE_OF_EDGE)
    out.append({"source": source, "target": target, "kind": kind})


def _rekey_unknown_city(ctx: _Ctx, city_ref: _Ref) -> None:
    """A `place:_/_/<city>` node becomes the real hierarchical city id once
    some save knows the country — every edge re-pointed, index row moved."""
    if ctx.dry_run or not city_ref.id.startswith("place:"):
        return
    slug = city_ref.id.rsplit("/", 1)[-1]
    old = f"place:{UNKNOWN}/{UNKNOWN}/{slug}"
    if old == city_ref.id:
        return
    rows = ctx.gs.conn.execute("SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (old, old)).fetchall()
    if not rows:
        return
    for row in rows:
        source = city_ref.id if row["source_id"] == old else row["source_id"]
        target = city_ref.id if row["target_id"] == old else row["target_id"]
        ctx.gs.remove_edge(row["id"])
        ctx.gs.create_edge(source, target, row["kind"], row["source_of_edge"])
    try:
        from .retrieval import safe_remove_node

        safe_remove_node(old)
    except Exception:
        pass


def _link_chain(ctx: _Ctx, source: str | None, chain: list[_Ref], out: list[dict]) -> str | None:
    """located_in from `source` to the most specific ref, part_of up the rest.
    Returns the target linked to."""
    if not chain:
        return None
    for ref in chain:
        ctx.names.setdefault(ref.id, ref.name)
        ctx.touched.add(ref.id)
    if chain[0].level == "city":
        _rekey_unknown_city(ctx, chain[0])
    for child, parent in zip(chain, chain[1:]):
        if child.level == "city" and not child.virtual:
            # A real Places note keeps at most one country parent.
            existing = _parent_of(ctx, child.id)
            if existing and existing != parent.id:
                break
        _create(ctx, child.id, parent.id, PART_OF, out)
    if source is not None:
        _create(ctx, source, chain[0].id, LOCATED_IN, out)
    return chain[0].id


def _sync_source(ctx: _Ctx, source: str, chains: list[list[_Ref]]) -> list[dict]:
    out: list[dict] = []
    targets = set()
    for chain in chains:
        t = _link_chain(ctx, source, chain, out)
        if t:
            targets.add(t)
    # Re-sync: this module's located_in edges from `source` that no longer apply.
    stale = ctx.gs.conn.execute(
        "SELECT id, target_id FROM edges WHERE source_id = ? AND kind = ? AND source_of_edge = ?",
        (source, LOCATED_IN, SOURCE_OF_EDGE),
    ).fetchall()
    for row in stale:
        if row["target_id"] not in targets:
            if not ctx.dry_run:
                ctx.gs.remove_edge(row["id"])
            ctx.touched.add(row["target_id"])
    return out


# --------------------------------------------------------------- inputs


_SPLIT_RE = re.compile(r"\s*(?:[,;|/\n]|→|->)\s*")


def _continent_name(token: str) -> str | None:
    from .nodes.kb.photo_place import _CONTINENTS

    t = token.strip().lower()
    for name in _CONTINENTS:
        if name.lower() == t:
            return name
    return None


def destination_chains(ctx: _Ctx, destinations) -> list[list[_Ref]]:
    """`fields.destinations` ("Vienna, Salzburg, Austria" / a list) → chains.
    A token that IS a country (photo_place's table) becomes the country of
    the cities listed before it; a lone country / continent links directly."""
    from .nodes.kb.photo_place import continent_for

    if isinstance(destinations, (list, tuple)):
        raw = ",".join(str(d) for d in destinations)
    else:
        raw = str(destinations or "")
    tokens = [t.strip() for t in _SPLIT_RE.split(raw) if t and t.strip()]
    chains: list[list[_Ref]] = []
    pending: list[str] = []
    for tok in tokens:
        if continent_for(tok):
            if pending:
                chains.extend(resolve_chain(ctx, c, tok) for c in pending)
                pending = []
            else:
                chains.append(resolve_chain(ctx, None, tok))
        elif _continent_name(tok):
            chains.extend(resolve_chain(ctx, c, None) for c in pending)
            pending = []
            chains.append(resolve_chain(ctx, None, None, _continent_name(tok)))
        else:
            pending.append(tok)
    chains.extend(resolve_chain(ctx, c, None) for c in pending)
    return [c for c in chains if c]


def _note_chains(ctx: _Ctx, folder_slug: str, meta: dict) -> list[list[_Ref]]:
    chains: list[list[_Ref]] = []
    place = meta.get("place")
    if isinstance(place, dict) and (place.get("city") or place.get("country")):
        chain = resolve_chain(ctx, place.get("city"), place.get("country"), place.get("continent"))
        if chain:
            chains.append(chain)
    if is_planned_folder(folder_slug):
        fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
        if fields.get("destinations"):
            chains.extend(destination_chains(ctx, fields.get("destinations")))
    return chains


# --------------------------------------------------------------- summaries / index


def members_of(conn, place_id: str) -> list[dict]:
    """Every `located_in` edge into `place_id` or any place under it (walking
    part_of children down) — what "photos from Europe" actually means."""
    rows = conn.execute(
        """
        WITH RECURSIVE sub(id) AS (
            SELECT ?
            UNION
            SELECT e.source_id FROM edges e JOIN sub ON e.target_id = sub.id WHERE e.kind = ?
        )
        SELECT e.source_id, e.target_id FROM edges e
        WHERE e.kind = ? AND e.target_id IN (SELECT id FROM sub)
        ORDER BY e.created_at, e.source_id
        """,
        (place_id, PART_OF, LOCATED_IN),
    ).fetchall()
    return [{"source_id": r["source_id"], "target_id": r["target_id"]} for r in rows]


def _member_kind(member_id: str) -> str:
    if member_id.startswith("experience:"):
        return "experience"
    if member_id.startswith("note:"):
        folder = member_id[5:].rsplit("/", 1)[0]
        return "trip plan" if is_planned_folder(folder) else "photo"
    return "entry"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def place_summary(ctx: _Ctx, place_id: str) -> str:
    level = level_of(place_id) or "place"
    parents: list[str] = []
    cur = place_id
    for _ in range(3):
        p = _parent_of(ctx, cur)
        if not p:
            break
        parents.append(ctx.names.get(p) or _index_title(p))
        cur = p
    head = f"{level.capitalize()} in {', '.join(parents)}" if parents else level.capitalize()
    children = [
        r["source_id"]
        for r in ctx.gs.conn.execute(
            "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = ?", (place_id, PART_OF)
        ).fetchall()
    ]
    parts = [head]
    if children:
        names = sorted({ctx.names.get(c) or _index_title(c) for c in children})
        parts.append(("cities: " if level == "country" else "countries: " if level == "continent" else "includes: ") + ", ".join(names[:12]))
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for m in members_of(ctx.gs.conn, place_id):
        src = m["source_id"]
        if src in seen:
            continue
        seen.add(src)
        if src.startswith("note:") and ctx.store is not None:
            from .nodes.kb.privacy import is_private_node

            if is_private_node(ctx.store, src):
                continue  # a private photo never counts toward a model-visible line
        k = _member_kind(src)
        counts[k] = counts.get(k, 0) + 1
    if counts:
        parts.append(", ".join(_plural(counts[k], k) for k in ("photo", "experience", "trip plan", "entry") if k in counts))
    return " — ".join(parts)


def _reindex(ctx: _Ctx) -> None:
    """Index every touched VIRTUAL place node (plus its ancestors, whose
    counts changed) — real Places notes index themselves as notes."""
    if ctx.dry_run:
        return
    from .retrieval import safe_index_node

    ids = set(ctx.touched)
    for pid in list(ids):
        cur = pid
        for _ in range(3):
            p = _parent_of(ctx, cur)
            if not p:
                break
            ids.add(p)
            cur = p
    for pid in sorted(ids, key=lambda i: -len(i)):
        if not is_place_id(pid):
            continue
        name = ctx.names.get(pid) or _index_title(pid)
        safe_index_node(pid, "place", name, place_summary(ctx, pid), "")


# --------------------------------------------------------------- public API


def _graph_store():
    from .graph import get_graph_store

    return get_graph_store()


def link_note_places(store, folder_slug: str, slug: str, *, dry_run: bool = False, graph_store=None) -> list[dict]:
    """THE save-time hook for a KB note: photo `place` frontmatter → its
    city; a Fun/Travel/Planned note's `fields.destinations` → each city.
    Re-syncs this note's located_in edges, then (not dry_run) its
    trip_photos `during_trip` edges. Never raises (returns [])."""
    try:
        gs = graph_store or _graph_store()
        path = store.entry_path(folder_slug, slug)
        if not path.is_file():
            return []
        folder_slug = str(path.parent.relative_to(store.root)).replace("\\", "/")
        note_id = f"note:{folder_slug}/{path.stem}"
        meta = frontmatter.loads(path.read_text(encoding="utf-8")).metadata
        ctx = _Ctx(store, gs, dry_run)
        out = _sync_source(ctx, note_id, _note_chains(ctx, folder_slug, meta))
        _reindex(ctx)
    except Exception as exc:
        logger.warning("place linking failed for %s/%s: %s", folder_slug, slug, exc)
        return []
    if not dry_run:
        # 2026-11-05 (trip_photos.py): same save points — a photo joins the
        # planned trip it was taken during; a plan pulls in its photos.
        from .trip_photos import link_note_trip_photos

        link_note_trip_photos(store, folder_slug, path.stem, graph_store=gs)
    return out


def link_experience_places(store, experience: dict, *, dry_run: bool = False, graph_store=None) -> list[dict]:
    """An experience → its city (country borrowed deterministically from an
    existing city node / real Places note, else city-only)."""
    try:
        gs = graph_store or _graph_store()
        exp_id = f"experience:{experience['folder']}/{experience['slug']}"
        ctx = _Ctx(store, gs, dry_run)
        city = (experience.get("city") or "").strip()
        chains = [resolve_chain(ctx, city, experience.get("country"))] if city else []
        out = _sync_source(ctx, exp_id, [c for c in chains if c])
        _reindex(ctx)
        return out
    except Exception as exc:
        logger.warning("place linking failed for experience %s: %s", experience.get("name"), exc)
        return []


def backfill_places(store, experiences: list[dict], *, dry_run: bool = True, graph_store=None) -> dict:
    """Photos (frontmatter `place`), trip plans (Planned `destinations`) and
    experiences — photos first so their countries are known when the
    city-only experiences/plans resolve. Returns counts + sample edges."""
    gs = graph_store or _graph_store()
    ctx = _Ctx(store, gs, dry_run)
    created: list[dict] = []
    counts = {"photos": 0, "plans": 0, "experiences": 0}
    exp_paths = {(e["folder"], e["slug"]) for e in experiences}
    photo_notes, plan_notes = [], []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            if (folder, slug) in exp_paths:
                continue
            try:
                meta = frontmatter.loads(store.entry_path(folder, slug).read_text(encoding="utf-8")).metadata
            except Exception:
                continue
            if isinstance(meta.get("place"), dict):
                photo_notes.append((folder, slug, meta))
            elif is_planned_folder(folder) and isinstance(meta.get("fields"), dict) and meta["fields"].get("destinations"):
                plan_notes.append((folder, slug, meta))
    for key, rows in (("photos", photo_notes), ("plans", plan_notes)):
        for folder, slug, meta in rows:
            try:
                out = _sync_source(ctx, f"note:{folder}/{slug}", _note_chains(ctx, folder, meta))
            except Exception as exc:
                logger.warning("place backfill failed for %s/%s: %s", folder, slug, exc)
                continue
            if out:
                counts[key] += 1
                created.extend(out)
    for e in experiences:
        city = (e.get("city") or "").strip()
        if not city:
            continue
        try:
            out = _sync_source(ctx, f"experience:{e['folder']}/{e['slug']}", [resolve_chain(ctx, city, e.get("country"))])
        except Exception as exc:
            logger.warning("place backfill failed for experience %s: %s", e.get("name"), exc)
            continue
        if out:
            counts["experiences"] += 1
            created.extend(out)
    _reindex(ctx)
    return {
        "dry_run": dry_run,
        "counts": counts,
        "edges": len(created),
        "located_in": sum(1 for e in created if e["kind"] == LOCATED_IN),
        "part_of": sum(1 for e in created if e["kind"] == PART_OF),
        "places": len({e["target"] for e in created if is_place_id(e["target"])}),
        "sample": created[:20],
    }


def graph_place_nodes(stored_edges: list[dict]) -> list[dict]:
    """/graph's virtual place nodes: every `place:` id the edges table
    references, labelled from the retrieval index, with its level."""
    ids = sorted(
        {endpoint for e in stored_edges for endpoint in (e["source_id"], e["target_id"]) if is_place_id(endpoint)}
    )
    return [{"id": pid, "type": "place", "label": _index_title(pid), "level": level_of(pid) or "city"} for pid in ids]
