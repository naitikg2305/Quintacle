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

2026-11-07: the match is by slug (title OR file name), and when a city
resolves to a Places note, any virtual city node with the same slug
(`place:_/_/<city>` from a plan/experience saved before the note existed,
or a hierarchical one from an earlier photo) is merged into the note —
`_merge_virtual_into_note`; the backfill re-links every source, so
existing orphans merge too.

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
BUCKET_PREFIX = "fun/travel/bucket-list"
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


def is_bucket_folder(folder_slug: str) -> bool:
    f = (folder_slug or "").strip("/").lower()
    return f == BUCKET_PREFIX or f.startswith(BUCKET_PREFIX + "/")


def is_travel_place_folder(folder_slug: str) -> bool:
    """The KB folders whose notes are ABOUT places (a trip plan, a someday
    wish) and so get destinations derived from their folder + text."""
    return is_planned_folder(folder_slug) or is_bucket_folder(folder_slug)


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
                            note_id = f"note:{folder}/{n['slug']}"
                            # 2026-11-07: keyed by the SLUG of the title AND of the
                            # file name — "Vienna", "vienna", "Zürich"/"zurich" and an
                            # emergent note whose body's first line isn't its name all
                            # resolve; one rule for photos, plans and experiences.
                            for key in (place_slug(n["title"] or ""), place_slug(n["slug"] or "")):
                                if key:
                                    self._real.setdefault(key, note_id)
                except Exception:
                    pass
        return self._real

    def edge_exists(self, source: str, target: str, kind: str) -> bool:
        if (source, target, kind) in self.planned_edges:
            return True
        return self.gs._existing_edge_id(source, target, kind) is not None


def _real_or_virtual(ctx: _Ctx, name: str, virtual_id: str, level: str) -> _Ref:
    real = ctx.real_places().get(place_slug(name))
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
        "SELECT target_id FROM edges WHERE source_id = ? AND kind = ? AND target_id NOT LIKE 'folder:%' "
        "ORDER BY created_at LIMIT 1",
        (node_id, PART_OF),
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
            real = ctx.real_places().get(cslug)
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


def _merge_virtual_into_note(ctx: _Ctx, note_ref: _Ref) -> None:
    """2026-11-07 place-graph gap: a real Places note is THE city node, but
    virtual city nodes with the same slug can predate it — `place:_/_/<city>`
    from an experience / plan saved before the note emerged, or a
    hierarchical `place:<cont>/<country>/<city>` from an earlier photo.
    Every edge on such a node is re-pointed to the note (its part_of
    becomes the note's country link unless the note already has a
    DIFFERENT country — then that virtual city is another place with the
    same name and is left alone), and the virtual node leaves the index.
    Runs on every save that resolves a city to a note, and in the backfill."""
    if ctx.dry_run or not note_ref.id.startswith("note:"):
        return
    slug = place_slug(note_ref.name) or note_ref.id.rsplit("/", 1)[-1]
    rows = ctx.gs.conn.execute(
        "SELECT DISTINCT source_id AS id FROM edges WHERE source_id LIKE ? "
        "UNION SELECT target_id FROM edges WHERE target_id LIKE ?",
        (f"place:%/{slug}", f"place:%/{slug}"),
    ).fetchall()
    note_parent = _parent_of(ctx, note_ref.id)
    for old in sorted(r["id"] for r in rows):
        parts = old.partition(":")[2].split("/")
        if len(parts) != 3 or parts[2] != slug:
            continue
        old_parent = _parent_of(ctx, old)
        if UNKNOWN not in parts[:2] and note_parent and old_parent and old_parent != note_parent:
            continue  # same city name, different country — not this note's city
        for row in ctx.gs.conn.execute("SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (old, old)).fetchall():
            source = note_ref.id if row["source_id"] == old else row["source_id"]
            target = note_ref.id if row["target_id"] == old else row["target_id"]
            ctx.gs.remove_edge(row["id"])
            if source == target:
                continue
            if row["kind"] == PART_OF and source == note_ref.id:
                current = _parent_of(ctx, note_ref.id)
                if current and current != target:
                    continue  # the note keeps at most one country parent
            ctx.gs.create_edge(source, target, row["kind"], row["source_of_edge"])
            ctx.touched.add(target if source == note_ref.id else source)
        note_parent = _parent_of(ctx, note_ref.id)
        ctx.touched.discard(old)
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
        if chain[0].virtual:
            _rekey_unknown_city(ctx, chain[0])
        else:
            _merge_virtual_into_note(ctx, chain[0])
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


# 2026-11-11: derived destinations. A plan saved straight from a drop has no
# `fields.destinations` (the kb_entry proposal never had fields), so it used
# to get zero place edges — "trips in Austria" couldn't find a Vienna plan
# filed under Fun/Travel/Planned/Austria. When Destinations is empty, the
# places come from (1) the folder segments under Planned / Bucket List
# ("Planned/Europe/Austria" → Austria, Europe) and (2) the cities / countries
# NAMED in the title + body (gazetteer.find_places — whole capitalised words,
# departure points skipped). Code only; a hand-typed Destinations always wins.

# Body lines that are plumbing, not prose: asset links, the 📍 place line,
# 🗂 file-metadata lines, bare URLs.
_NON_PROSE_RE = re.compile(r"^\s*(?:!?\[[^\]]*\]\([^)]*\)\s*|📍.*|🗂.*|https?://\S+\s*)$")


def _prose(content: str) -> str:
    lines = [ln for ln in (content or "").splitlines() if not _NON_PROSE_RE.match(ln)]
    return re.sub(r"https?://\S+", " ", "\n".join(lines))


def _folder_mentions(folder_slug: str) -> list:
    """Folder segments under Planned / Bucket List that ARE places (a
    continent, a country, a gazetteer city); anything else ("2027",
    "summer-ideas") is ignored."""
    from .gazetteer import CITIES, PlaceMention, canonical_city, canonical_country, continent_name
    from .nodes.kb.photo_place import _CONTINENTS, continent_for

    f = (folder_slug or "").strip("/").lower()
    base = PLANNED_PREFIX if is_planned_folder(f) else BUCKET_PREFIX if is_bucket_folder(f) else None
    if base is None:
        return []
    by_slug: dict = {}
    for cont in _CONTINENTS:
        by_slug.setdefault(place_slug(cont), PlaceMention(None, None, continent_name(cont)))
    for names in _CONTINENTS.values():
        for n in names:
            c = canonical_country(n) or n
            by_slug.setdefault(place_slug(n), PlaceMention(None, c, continent_for(c)))
    for city in CITIES:
        canon, country = canonical_city(city)
        by_slug.setdefault(place_slug(city), PlaceMention(canon, country, continent_for(country)))
    out = []
    for seg in f[len(base):].strip("/").split("/"):
        m = by_slug.get(seg) if seg else None
        if m is not None:
            out.append(m)
    return out


def derive_destinations(folder_slug: str, content: str) -> list:
    """Folder segments + places named in the text → PlaceMentions, most
    specific kept: a country is dropped when a named city already carries
    it, a continent when a named country/city is inside it."""
    from .gazetteer import find_places

    mentions = _folder_mentions(folder_slug) + find_places(_prose(content))
    cities = [m for m in mentions if m.city]
    countries = [m for m in mentions if not m.city and m.country]
    continents = [m for m in mentions if not m.city and not m.country and m.continent]
    covered_countries = {m.country for m in cities}
    covered_continents = {m.continent for m in cities + countries}
    out, seen = [], set()
    for m in (
        cities
        + [c for c in countries if c.country not in covered_countries]
        + [c for c in continents if c.continent not in covered_continents]
    ):
        key = (m.city, m.country, m.continent)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def destinations_text(mentions) -> str:
    """PlaceMentions → a `fields.destinations` string destination_chains
    parses back to the same places ("Vienna, Salzburg, Austria; Japan")."""
    groups: dict[tuple, list[str]] = {}
    for m in mentions:
        cities = groups.setdefault((m.country or "", m.continent or ""), [])
        if m.city:
            cities.append(m.city)
    parts = []
    for (country, continent), cities in groups.items():
        parts.append(", ".join([*cities, country] if country else cities) or continent)
    return "; ".join(p for p in parts if p)


def proposal_destinations(folder: str, title: str, content: str) -> str:
    """The `fields.destinations` a drop's kb_entry proposal carries when
    it's headed for Planned / Bucket List ("" otherwise, or when nothing is
    named) — the same derivation Save runs, shown on the review card."""
    from .markdown_paths import slugify

    folder_slug = "/".join(slugify(s) for s in (folder or "").split("/") if s.strip())
    if not is_travel_place_folder(folder_slug):
        return ""
    return destinations_text(derive_destinations(folder_slug, f"# {title}\n\n{content}"))


def _note_chains(ctx: _Ctx, folder_slug: str, meta: dict, content: str = "", slug: str = "") -> list[list[_Ref]]:
    chains: list[list[_Ref]] = []
    place = meta.get("place")
    if isinstance(place, dict) and (place.get("city") or place.get("country")):
        chain = resolve_chain(ctx, place.get("city"), place.get("country"), place.get("continent"))
        if chain:
            chains.append(chain)
    if is_travel_place_folder(folder_slug):
        fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
        if fields.get("destinations"):
            chains.extend(destination_chains(ctx, fields.get("destinations")))
        elif not (slug.startswith("about-") or slug.startswith("_")):  # folder charters aren't trips
            for m in derive_destinations(folder_slug, content):
                chain = resolve_chain(ctx, m.city, m.country, m.continent)
                if chain:
                    chains.append(chain)
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
        if is_planned_folder(folder):
            return "trip plan"
        return "bucket-list place" if is_bucket_folder(folder) else "photo"
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
        parts.append(", ".join(_plural(counts[k], k) for k in ("photo", "experience", "trip plan", "bucket-list place", "entry") if k in counts))
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
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        ctx = _Ctx(store, gs, dry_run)
        out = _sync_source(ctx, note_id, _note_chains(ctx, folder_slug, post.metadata, post.content, path.stem))
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
    counts = {"photos": 0, "plans": 0, "bucket_list": 0, "experiences": 0}
    exp_paths = {(e["folder"], e["slug"]) for e in experiences}
    photo_notes, plan_notes, bucket_notes = [], [], []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            if (folder, slug) in exp_paths:
                continue
            try:
                post = frontmatter.loads(store.entry_path(folder, slug).read_text(encoding="utf-8"))
            except Exception:
                continue
            meta = post.metadata
            if isinstance(meta.get("place"), dict):
                photo_notes.append((folder, slug, meta, post.content))
            elif is_planned_folder(folder):
                # 2026-11-11: every plan, Destinations typed or not —
                # derive_destinations covers the drop-saved ones.
                plan_notes.append((folder, slug, meta, post.content))
            elif is_bucket_folder(folder):
                bucket_notes.append((folder, slug, meta, post.content))
    for key, rows in (("photos", photo_notes), ("plans", plan_notes), ("bucket_list", bucket_notes)):
        for folder, slug, meta, content in rows:
            try:
                out = _sync_source(ctx, f"note:{folder}/{slug}", _note_chains(ctx, folder, meta, content, slug))
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
