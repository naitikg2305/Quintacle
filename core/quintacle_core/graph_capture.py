"""The shared half of graph-model.md's write rule — one place that knows how
to turn "something was just persisted" into graph edges, so every write path
(REST handlers, MCP tools, the startup backfill) links identically instead of
each one re-deciding what a candidate is.

graph.py stays the engine (edge files + SQLite + the deterministic matcher);
this module owns the glue the engine deliberately doesn't: gathering
candidates from the real stores, the journal/notes/item write-rule calls, the
one-pass mention backfill over pre-existing content, and the emergent-place
rule. Stores are constructed directly from the graph store's data_dir (the
same cheap, stateless path-wrapper pattern travel/api.py already uses to
avoid api-module import cycles), so this imports node *stores* only — never a
node's api module.

## What links, per write path (the coverage contract)

- journal save (REST POST /journal/{date} AND MCP journal_append):
  `journal_graph_links` — mentions_person / at_location edges FROM the
  journal day, plus an incremental place-emergence check.
- KB notes (REST /kb/entries* AND MCP kb_create_entry): `entry_graph_links`
  via kb/api._sync_note_graph_links / mcp_server/graph_link.py.
- experiences / people: their create endpoints (structural retrofit) — now
  built on the same `mention_candidates`.
- item-shaped stores (wardrobe, grooming, home items, documents): their
  *description/notes text* is keyword-linked to people/experiences from
  `note:<folder>/<slug>` — the KB-note identity those files already have in
  /graph, so the edges render with zero frontend work.
- activity logs: their description is narrative ("Went to Mia Italina
  Kitchen in Alexandria"), so log_activity links it from the day's
  `journal:` node via the same journal helper.
- pure numeric logs (food, exercise, body stats, substances, expenses):
  deliberately NOT keyword-linked — their day-association already lives in
  SQLite rows keyed by date, and merchant/metric strings keyword-matched
  against people names would manufacture noise, not capture ("always
  attempts" never meant "always produces an edge").

## Emergent places

Deterministic, no AI: a place can only emerge from strings the system
already KNOWS are places — the lexicon is city names from travel experiences
(`city` field) plus residences (`city` field; street addresses are skipped,
parsing a city out of one would be guessing). When a lexicon name is
mentioned (graph.title_mentioned semantics) in at least
PLACE_EMERGENCE_THRESHOLD distinct sources — journal days, KB note
title+body, experience name+city+notes (an experience's own city field
counts: being *in* Mumbai is the strongest possible mention of Mumbai) — a
real KB entry appears at Places/<Name>.md (fields: kind=place) and every
mentioning source gets an `at_location` edge to it, provenance
"emergent_place". Re-runs top up missing edges but never rewrite an existing
place note. Frontmatter `description` fields (wardrobe/grooming) are not
mention *sources* — only body text and the stores listed above are, keeping
the source set identical between the backfill and the incremental checks.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from .graph import create_edge, get_graph_store, link_new_entry, title_mentioned
from .markdown_paths import slugify
from .nodes.documents.store import DocumentStore
from .nodes.grooming.store import GroomingItemStore
from .nodes.home.store import HomeItemStore, ResidenceStore
from .nodes.journal.store import JournalStore
from .nodes.kb.store import KBStore
from .nodes.people.store import PersonStore
from .nodes.travel.store import ExperienceStore
from .nodes.wardrobe.store import WardrobeItemStore

# A lexicon place name mentioned in at least this many DISTINCT sources
# becomes a real place node. 3 = "mentioned enough to matter": one mention is
# an anecdote, two a coincidence, three a recurring place in this life.
PLACE_EMERGENCE_THRESHOLD = 3

# Provenance tags (source_of_edge) this module writes, kept distinct so
# `grep graph/edges` always answers "which pass created this edge":
MENTION_BACKFILL = "mention_backfill"  # startup scan of pre-existing content
EMERGENT_PLACE = "emergent_place"  # the place-emergence rule, any trigger

PLACES_FOLDER = "Places"  # KB folder emergent place notes live in ("places" slug)

# The KB-note graph ids of item-shaped entries — the slugified folders their
# stores actually write into (wardrobe/grooming/documents each have one fixed
# home; home items nest under their residence's folder). Defined once here so
# the write-path handlers and the backfill can never drift apart on ids.
WARDROBE_ITEMS_FOLDER = "personal-development/physical/style-dressing/items"
GROOMING_ITEMS_FOLDER = "personal-development/physical/grooming/items"
DOCUMENTS_FOLDER = "organisation/document-vault"


def wardrobe_item_note_id(name: str) -> str:
    return f"note:{WARDROBE_ITEMS_FOLDER}/{slugify(name)}"


def grooming_item_note_id(name: str) -> str:
    return f"note:{GROOMING_ITEMS_FOLDER}/{slugify(name)}"


def document_note_id(name: str) -> str:
    return f"note:{DOCUMENTS_FOLDER}/{slugify(name)}"


def home_item_note_id(residence_folder: str, slug: str) -> str:
    return f"note:{residence_folder}/items/{slug}"


class _Stores:
    """Every store the capture layer reads, built once per call from the
    graph store's own data_dir — guaranteed to be the same tree the engine
    writes edges for, whether the process is the FastAPI app or the MCP
    server."""

    def __init__(self):
        data_dir = get_graph_store().data_dir
        kb_root = data_dir / "kb"
        self.kb = KBStore(kb_root)
        self.journal = JournalStore(data_dir / "journal")
        self.people = PersonStore(kb_root)
        self.travel = ExperienceStore(kb_root)
        self.residences = ResidenceStore(kb_root)
        self.wardrobe_items = WardrobeItemStore(kb_root)
        self.grooming_items = GroomingItemStore(kb_root)
        self.documents = DocumentStore(kb_root)
        self.home_items = HomeItemStore(kb_root)


def mention_candidates(people: list[dict], experiences: list[dict]) -> list[dict]:
    """The one candidate list every keyword-link call uses: every known
    person (-> mentions_person) and experience (-> at_location). Kept as a
    function of plain store rows so callers that already loaded them don't
    re-read disk."""
    return [{"id": f"note:{p['folder']}/profile", "type": "person", "title": p["name"]} for p in people] + [
        {"id": f"experience:{e['folder']}/{e['slug']}", "type": "experience", "title": e["name"]} for e in experiences
    ]


def place_lexicon(experiences: list[dict], residences: list[dict]) -> list[str]:
    """Known-place strings only: city names from experiences + residences.
    Deduped case-insensitively (all-lowercase input gets titlecased, cased
    input like "DC" kept verbatim); empty/1-2-char strings ignored."""
    seen: dict[str, str] = {}
    for raw in [e.get("city") for e in experiences] + [r.get("city") for r in residences]:
        name = (raw or "").strip() if isinstance(raw, str) else ""
        if len(name) <= 2:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = name.title() if name.islower() else name
    return sorted(seen.values())


def place_note_id(name: str) -> str:
    return f"note:places/{slugify(name)}"


def _mention_sources(stores: _Stores, experiences: list[dict]) -> list[tuple[str, str, str]]:
    """Every (source_id, entry_type, text) the mention scans run over —
    journal days (their narrative PLUS that day's activity-log descriptions,
    which are prose like "Went to Mia Italina Kitchen in Alexandria" and
    anchor to the same journal: day id the write path uses), KB notes
    (title + body; experience/place files excluded, they're covered as
    experiences / are the emergence output itself), and experiences
    (name + city + notes). Built once per scan, not per entry."""
    activity_text_by_day: dict[str, list[str]] = {}
    for row in get_graph_store().conn.execute("SELECT date, description FROM activity_log"):
        activity_text_by_day.setdefault(row["date"], []).append(row["description"] or "")

    sources: list[tuple[str, str, str]] = []
    journal_days = {d.isoformat(): stores.journal.load(d) or "" for d in stores.journal.list_dates()}
    for iso in sorted(set(journal_days) | set(activity_text_by_day)):
        text = "\n".join([journal_days.get(iso, ""), *activity_text_by_day.get(iso, [])])
        sources.append((f"journal:{iso}", "journal_day", text))

    experience_paths = {(e["folder"], e["slug"]) for e in experiences}
    for n in stores.kb.graph_entries():
        folder, slug = n["folder"], n["slug"]
        if folder == "places" or folder.startswith("places/"):
            continue  # a place note naming its own city is not a mention
        if (folder, slug) in experience_paths:
            continue  # experience files live in the KB tree; scanned below under their experience: id
        body = stores.kb.read(folder, slug) or ""
        sources.append((f"note:{folder}/{slug}", "note", f"{n['title']}\n{body}"))

    for e in experiences:
        text = f"{e.get('name') or ''}\n{e.get('city') or ''}\n{e.get('notes') or ''}"
        sources.append((f"experience:{e['folder']}/{e['slug']}", "experience", text))
    return sources


def _emerge_places(
    stores: _Stores,
    sources: list[tuple[str, str, str]],
    experiences: list[dict],
    residences: list[dict],
    only: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """The emergence rule. `only` (lowercased names) restricts the scan to
    places a just-written text actually mentioned — the incremental trigger —
    while None means the full backfill pass. Idempotent: an existing
    Places/<Name>.md is never rewritten (no content churn), its edges are
    just topped up; create_edge dedupes on (source, target, kind)."""
    created: list[dict] = []
    emerged: list[str] = []
    for name in place_lexicon(experiences, residences):
        if only is not None and name.lower() not in only:
            continue
        slug = slugify(name)
        target = place_note_id(name)
        matching = [sid for sid, _t, text in sources if sid != target and title_mentioned(name, text)]
        exists = stores.kb.read(PLACES_FOLDER, slug) is not None
        if not exists:
            if len(matching) < PLACE_EMERGENCE_THRESHOLD:
                continue
            stores.kb.write(
                PLACES_FOLDER,
                name,
                f"Emergent place — first seen across {len(matching)} entries.",
                links=[],
                fields={"kind": "place", "city": name},
            )
            emerged.append(name)
        for sid in matching:
            created.append(create_edge(sid, target, "at_location", EMERGENT_PLACE))
    return created, emerged


def entry_graph_links(entry_id: str, entry_type: str, text: str, *, source_of_edge: str = "ai_link") -> list[dict]:
    """The write-rule call for anything note-shaped: keyword-link `text`
    against every known person/experience, then run the incremental
    place-emergence check for any lexicon place this text mentions (a write
    that pushes a place over the threshold emerges it right then, not at the
    next restart)."""
    stores = _Stores()
    people, experiences = stores.people.all(), stores.travel.all()
    created = link_new_entry(
        entry_id, entry_type, text or "", mention_candidates(people, experiences), source_of_edge=source_of_edge
    )
    residences = stores.residences.all()
    mentioned = {n.lower() for n in place_lexicon(experiences, residences) if title_mentioned(n, text or "")}
    if mentioned:
        place_edges, _ = _emerge_places(stores, _mention_sources(stores, experiences), experiences, residences, only=mentioned)
        created += place_edges
    return created


def journal_graph_links(entry_date: date, content: str, *, source_of_edge: str = "ai_link") -> list[dict]:
    """THE shared journal hook — REST POST /journal/{date} and MCP
    journal_append both go through here, so journal text written either way
    creates identical mentions_person/at_location edges FROM the day (and
    the same place-emergence behavior)."""
    return entry_graph_links(f"journal:{entry_date.isoformat()}", "journal_day", content, source_of_edge=source_of_edge)


def safe_entry_graph_links(entry_id: str, entry_type: str, text: str, *, source_of_edge: str = "ai_link") -> list[dict]:
    """entry_graph_links that can never take the write it follows down with
    it — same "additive, never blocking" contract as the MCP graph_link
    adapter. REST commit handlers call this one. The failure is LOGGED, not
    silently dropped — a quietly-dead linker is precisely the class of
    coverage gap this module exists to close."""
    try:
        return entry_graph_links(entry_id, entry_type, text, source_of_edge=source_of_edge)
    except Exception:
        logging.getLogger(__name__).exception("graph capture failed for %s (write itself succeeded)", entry_id)
        return []


def safe_journal_graph_links(entry_date: date, content: str, *, source_of_edge: str = "ai_link") -> list[dict]:
    return safe_entry_graph_links(f"journal:{entry_date.isoformat()}", "journal_day", content, source_of_edge=source_of_edge)


def emerge_places_for_text(text: str) -> list[dict]:
    """Incremental emergence trigger for writes that add to the place
    LEXICON rather than to the mention pool — a new experience or residence
    whose city might already have enough mentions lying around."""
    stores = _Stores()
    experiences, residences = stores.travel.all(), stores.residences.all()
    mentioned = {n.lower() for n in place_lexicon(experiences, residences) if title_mentioned(n, text or "")}
    if not mentioned:
        return []
    created, _ = _emerge_places(stores, _mention_sources(stores, experiences), experiences, residences, only=mentioned)
    return created


def _item_description_sources(stores: _Stores, residences: list[dict]) -> Iterable[tuple[str, str]]:
    """(note_id, text) for every item-shaped entry whose human text lives in
    frontmatter (`description`) or a body the note scan already covers —
    wardrobe items, grooming items, documents, and each residence's home
    items. Ids are their KB-note identity, same as the write-path links."""
    for item in stores.wardrobe_items.all():
        yield wardrobe_item_note_id(item["name"]), f"{item['name']}\n{item.get('description') or ''}"
    for item in stores.grooming_items.all():
        yield grooming_item_note_id(item["name"]), f"{item['name']}\n{item.get('description') or ''}"
    for doc in stores.documents.all():
        yield document_note_id(doc["name"]), f"{doc['name']}\n{doc.get('notes') or ''}"
    for res in residences:
        for item in stores.home_items.all(res["folder"]):
            yield home_item_note_id(res["folder"], item["slug"]), f"{item['name']}\n{item.get('notes') or ''}"


def run_graph_capture_backfill() -> dict:
    """One idempotent pass over everything that already exists — journal
    days, KB notes, experiences, item descriptions — running the same
    deterministic matcher the write paths use, plus the full place-emergence
    scan. Safe on every startup: link_new_entry/create_edge dedupe on
    (source, target, kind), and existing place notes are never rewritten.
    Edges it creates carry source_of_edge="mention_backfill" (mentions) or
    "emergent_place" (places) so provenance stays debuggable. Returns counts
    for logging/tests."""
    stores = _Stores()
    people, experiences, residences = stores.people.all(), stores.travel.all(), stores.residences.all()
    candidates = mention_candidates(people, experiences)
    sources = _mention_sources(stores, experiences)

    mention_edges = 0
    for sid, stype, text in sources:
        mention_edges += len(link_new_entry(sid, stype, text, candidates, source_of_edge=MENTION_BACKFILL))
    for sid, text in _item_description_sources(stores, residences):
        mention_edges += len(link_new_entry(sid, "note", text, candidates, source_of_edge=MENTION_BACKFILL))

    place_edges, emerged = _emerge_places(stores, sources, experiences, residences)
    return {"mention_edges": mention_edges, "place_edges": len(place_edges), "places_emerged": emerged}
