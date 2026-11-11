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

import hashlib
import logging
import sqlite3
from datetime import date
from typing import Iterable

from .graph import create_edge, get_graph_store, link_new_entry, proper_name_mentioned, title_mentioned
from .markdown_paths import slugify
from .place_graph import place_slug
from .retrieval import safe_index_event, safe_index_note
from .nodes.documents.store import DocumentStore
from .nodes.finance.accounts import ACCOUNTS_HOME, AccountStore
from .nodes.grooming.store import GroomingItemStore
from .nodes.home.store import HomeItemStore, ResidenceStore
from .nodes.journal.store import JournalStore
from .nodes.kb.store import KBStore
from .nodes.logs.worklog import entity_notes
from .nodes.people.store import PersonStore, unique_first_names
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
SAME_EVENT = "same_event"  # link_event: records born from one capture/Save
BACKLINK = "backlink"  # a just-created person/hub scanning content that already named it
KNOWN_PLACE = "known_place"  # a text naming a city that is already a place node
FOLDER_HUB = "folder_hub"  # a note -> its folder's about-<folder> charter hub
VISITED_DAY = "visited_day"  # an experience -> its visited_date's journal day

# Edge kinds for the 2026-11-11 candidate types. Project/company hubs and
# finance accounts use the default `related` — the same kind the work-log
# importer's hub links already carry, so "what links to Minfy" is one kind.
# A note's folder-charter hub gets `part_of` (membership, like event/place
# part_of): the member points at its collection.
HUB_KIND = "related"
FOLDER_HUB_KIND = "part_of"

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
        self.accounts = AccountStore(kb_root)


def mention_candidates(
    people: list[dict],
    experiences: list[dict],
    hubs: list[dict] | None = None,
    accounts: list[dict] | None = None,
) -> list[dict]:
    """The one candidate list every keyword-link call uses: every known
    person (-> mentions_person; a first name only ONE tracked person has is
    an alias — people/store.unique_first_names, the drop detector's rule)
    and experience (-> at_location), plus — when the caller passes them —
    Career/Projects entity hubs and finance accounts (-> related, matched as
    proper nouns). Kept as a function of plain store rows so callers that
    already loaded them don't re-read disk."""
    unique_full_names = set(unique_first_names([p["name"] for p in people]).values())
    out = []
    for p in people:
        cand = {"id": f"note:{p['folder']}/profile", "type": "person", "title": p["name"]}
        if p["name"] in unique_full_names:
            cand["aliases"] = [p["name"].split()[0]]
        out.append(cand)
    out += [
        {"id": f"experience:{e['folder']}/{e['slug']}", "type": "experience", "title": e["name"]} for e in experiences
    ]
    out += hubs or []
    out += accounts or []
    return out


def _is_entity_hub(folder: str, slug: str) -> bool:
    """career/hubs.py's hub rule, at any depth: a note directly in an entity
    root, or the folder-hub (slug == its folder's last segment —
    projects/quintacle/quintacle, career/contracts/acme/acme). Deeper notes
    ("Design", "Notes") are NOT hubs: as candidates they'd link every note
    using the word."""
    parts = folder.split("/")
    return not slug.startswith("about-") and (len(parts) == 1 or parts[-1] == slug)


def entity_hub_candidates(kb) -> list[dict]:
    """Career/Projects hubs as link candidates, discovered exactly the way
    the work-log importer does (logs/worklog.entity_notes)."""
    return [
        {"id": f"note:{n['folder']}/{n['slug']}", "type": "hub", "title": n["title"], "kind": HUB_KIND, "proper": True}
        for n in entity_notes(kb)
        if len(n["title"]) >= 3 and _is_entity_hub(n["folder"], n["slug"])
    ]


ACCOUNTS_FOLDER = "/".join(slugify(p) for p in ACCOUNTS_HOME.split("/"))


def account_candidates(accounts: list[dict]) -> list[dict]:
    """Finance accounts (finance/accounts.py, one KB note each under
    Organisation/Finance/Accounts) as link candidates — "grow Ally Savings
    to $20k" -> the Ally Savings account note."""
    return [
        {"id": f"note:{ACCOUNTS_FOLDER}/{a['slug']}", "type": "account", "title": a["name"], "kind": HUB_KIND, "proper": True}
        for a in accounts
        if len((a.get("name") or "").strip()) >= 3
    ]


def _all_candidates(stores: "_Stores", people: list[dict], experiences: list[dict]) -> list[dict]:
    try:
        accounts = stores.accounts.all()
    except Exception:
        accounts = []
    return mention_candidates(people, experiences, entity_hub_candidates(stores.kb), account_candidates(accounts))


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
            body = f"Emergent place — first seen across {len(matching)} entries."
            place_folder, place_slug = stores.kb.write(
                PLACES_FOLDER,
                name,
                body,
                links=[],
                fields={"kind": "place", "city": name},
            )
            # Retrieval index (retrieval.py): place notes are written here,
            # not through kb/api — failure-isolated, never blocks emergence.
            safe_index_note(place_folder, place_slug, name, body)
            emerged.append(name)
        for sid in matching:
            created.append(create_edge(sid, target, "at_location", EMERGENT_PLACE))
    return created, emerged


def entry_graph_links(entry_id: str, entry_type: str, text: str, *, source_of_edge: str = "ai_link") -> list[dict]:
    """The write-rule call for anything note-shaped: keyword-link `text`
    against every known person (full name or unique first name),
    experience, Career/Projects hub and finance account; link any place
    node the graph ALREADY has that the text names (known_place_links — the
    emergence threshold only governs CREATING a place); link a note to its
    folder's charter hub; a journal day to the experiences visited that day;
    then run the incremental place-emergence check for any lexicon place
    this text mentions (a write that pushes a place over the threshold
    emerges it right then, not at the next restart)."""
    stores = _Stores()
    people, experiences = stores.people.all(), stores.travel.all()
    created = link_new_entry(
        entry_id, entry_type, text or "", _all_candidates(stores, people, experiences), source_of_edge=source_of_edge
    )
    created += known_place_links(entry_id, text or "", stores=stores)
    if entry_id.startswith("note:"):
        created += folder_hub_links(stores, entry_id)
    if entry_id.startswith("journal:"):
        created += visited_day_links_for_day(stores, entry_id.removeprefix("journal:"), experiences)
    residences = stores.residences.all()
    mentioned = {n.lower() for n in place_lexicon(experiences, residences) if title_mentioned(n, text or "")}
    if mentioned:
        place_edges, _ = _emerge_places(stores, _mention_sources(stores, experiences), experiences, residences, only=mentioned)
        created += place_edges
    return created


# --- known places (2026-11-11) ---------------------------------------------


def known_city_places(conn) -> dict[str, str]:
    """place_slug(city) -> node id for every CITY the graph already has: a
    real Places note (note:places/<slug>) wins over a virtual
    place:<continent>/<country>/<city> node, and a hierarchical virtual node
    wins over an unknown-country place:_/_/<city>. One SQL pass over edge
    endpoints — a place exists in the graph iff some edge touches it."""
    found: dict[str, str] = {}
    rank: dict[str, int] = {}
    rows = conn.execute(
        "SELECT source_id AS id FROM edges WHERE source_id LIKE 'place:%' OR source_id LIKE 'note:places/%' "
        "UNION SELECT target_id FROM edges WHERE target_id LIKE 'place:%' OR target_id LIKE 'note:places/%'"
    ).fetchall()
    for r in sorted(row["id"] for row in rows):
        if r.startswith("note:places/"):
            slug, score = r.rsplit("/", 1)[-1], 3
        else:
            parts = r.partition(":")[2].split("/")
            if len(parts) != 3 or not parts[2]:
                continue  # continents / countries aren't "a city named in text"
            slug, score = parts[2], 1 if "_" in parts[:2] else 2
        if score > rank.get(slug, 0):
            found[slug], rank[slug] = r, score
    return found


def known_place_links(entry_id: str, text: str, *, source_of_edge: str = KNOWN_PLACE, stores: "_Stores | None" = None) -> list[dict]:
    """A text naming a city that ALREADY exists as a place node links to it
    now (`at_location`, the mention kind emergent places use) — the
    PLACE_EMERGENCE_THRESHOLD only governs creating a NEW place. Names are
    the node's slug titlecased plus any place-lexicon spelling with the same
    slug ("Washington DC"), matched as proper nouns ("nice", "reading" as
    plain words don't count). Skips a target the entry already has any edge
    to (a trip plan's place_graph located_in) and the entry's own node."""
    store = get_graph_store()
    places = known_city_places(store.conn)
    if not places or not (text or "").strip():
        return []
    names: dict[str, set[str]] = {slug: {" ".join(w.capitalize() for w in slug.split("-"))} for slug in places}
    stores = stores or _Stores()
    for name in place_lexicon(stores.travel.all(), stores.residences.all()):
        if place_slug(name) in names:
            names[place_slug(name)].add(name)
    created = []
    for slug, target in sorted(places.items()):
        if target == entry_id or len(slug) < 3:
            continue
        if not any(proper_name_mentioned(n, text) for n in names[slug]):
            continue
        if store.conn.execute(
            "SELECT 1 FROM edges WHERE source_id = ? AND target_id = ? LIMIT 1", (entry_id, target)
        ).fetchone():
            continue
        created.append(create_edge(entry_id, target, "at_location", source_of_edge))
    return created


# --- folder charter hubs (2026-11-11) ---------------------------------------


def _folder_hub_slug(stores: "_Stores", folder: str) -> str | None:
    """The folder's charter hub: `about-<folder's last segment>.md`, else the
    only about-*.md in it (the knowledge/travel pages' charter rule)."""
    entries = stores.kb.list_entries(folder)
    exact = f"about-{folder.rsplit('/', 1)[-1]}"
    if exact in entries:
        return exact
    abouts = [e for e in entries if e.startswith("about-")]
    return abouts[0] if len(abouts) == 1 else None


def folder_hub_links(stores: "_Stores", note_id: str, *, source_of_edge: str = FOLDER_HUB) -> list[dict]:
    """Structural: every note directly in a folder is `part_of` that
    folder's charter hub. Saving a member links it to the hub; saving the
    hub itself links every existing member (one folder listing — cheap)."""
    folder, _, slug = note_id.removeprefix("note:").rpartition("/")
    if not folder:
        return []
    hub = _folder_hub_slug(stores, folder)
    if hub is None:
        return []
    hub_id = f"note:{folder}/{hub}"
    if slug != hub:
        return [create_edge(note_id, hub_id, FOLDER_HUB_KIND, source_of_edge)]
    return [
        create_edge(f"note:{folder}/{member}", hub_id, FOLDER_HUB_KIND, source_of_edge)
        for member in stores.kb.list_entries(folder)
        if member != hub
    ]


# --- experience -> its visited day (2026-11-11) -----------------------------


def _iso(value) -> str | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def visited_day_link(experience_id: str, visited_date, *, source_of_edge: str = VISITED_DAY) -> list[dict]:
    """experience -> journal:<visited_date> `on_day`, only when the
    experience has a visited_date AND that journal day exists (link_event's
    existence gate — no dangling day nodes). The journal save closes the
    other order (visited_day_links_for_day)."""
    iso = _iso(visited_date)
    if iso is None:
        return []
    store = get_graph_store()
    if JournalStore(store.data_dir / "journal").load(date.fromisoformat(iso)) is None:
        return []
    return [create_edge(experience_id, f"journal:{iso}", "on_day", source_of_edge)]


def visited_day_links_for_day(stores: "_Stores", iso: str, experiences: list[dict]) -> list[dict]:
    """A journal day just written: every experience visited that day gets
    its on_day edge (the experience may have been saved first)."""
    day = _iso(iso)
    if day is None or stores.journal.load(date.fromisoformat(day)) is None:
        return []
    return [
        create_edge(f"experience:{e['folder']}/{e['slug']}", f"journal:{day}", "on_day", VISITED_DAY)
        for e in experiences
        if _iso(e.get("visited_date")) == day
    ]


# --- back-links for a just-created target (2026-11-11) -----------------------


def backlink_new_target(target_id: str) -> list[dict]:
    """A person/hub/account just created: every EXISTING source that names
    it (the startup backfill's sources — journal days + activity prose, KB
    notes, experiences, item descriptions) links to it now, not at the next
    restart. Exactly the backfill's scan restricted to the one new
    candidate: one pass over the store, run on create only."""
    stores = _Stores()
    people, experiences = stores.people.all(), stores.travel.all()
    candidate = [c for c in _all_candidates(stores, people, experiences) if c["id"] == target_id]
    if not candidate:
        return []
    created = []
    for sid, stype, text in _mention_sources(stores, experiences):
        created += link_new_entry(sid, stype, text, candidate, source_of_edge=BACKLINK)
    for sid, text in _item_description_sources(stores, stores.residences.all()):
        created += link_new_entry(sid, "note", text, candidate, source_of_edge=BACKLINK)
    return created


def safe_backlink_new_target(target_id: str) -> list[dict]:
    """backlink_new_target that never fails the create it follows (logged)."""
    try:
        return backlink_new_target(target_id)
    except Exception:
        logging.getLogger(__name__).exception("back-link scan failed for %s (write itself succeeded)", target_id)
        return []


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
    candidates = _all_candidates(stores, people, experiences)
    sources = _mention_sources(stores, experiences)

    mention_edges = 0
    for sid, stype, text in sources:
        mention_edges += len(link_new_entry(sid, stype, text, candidates, source_of_edge=MENTION_BACKFILL))
    for sid, text in _item_description_sources(stores, residences):
        mention_edges += len(link_new_entry(sid, "note", text, candidates, source_of_edge=MENTION_BACKFILL))

    structural_edges = 0
    for e in experiences:  # experience -> its visited day
        structural_edges += len(visited_day_link(f"experience:{e['folder']}/{e['slug']}", e.get("visited_date")))
    for folder in stores.kb.list_folders():  # note -> its folder's charter hub
        hub = _folder_hub_slug(stores, folder)
        if hub is not None:
            structural_edges += len(folder_hub_links(stores, f"note:{folder}/{hub}"))

    place_edges, emerged = _emerge_places(stores, sources, experiences, residences)
    # Known places AFTER emergence: a source naming a city that is (now) a
    # place node links to it even below the creation threshold.
    for sid, _stype, text in sources:
        place_edges += known_place_links(sid, text, source_of_edge=MENTION_BACKFILL)
    return {
        "mention_edges": mention_edges,
        "structural_edges": structural_edges,
        "place_edges": len(place_edges),
        "places_emerged": emerged,
    }


# --- Same-event provenance (link_event) ---
#
# A batch of entries committed from ONE capture — one Drop sort, one journal
# parse, one photo commit — is one real-world event ("chipotle 14.50" is
# correctly both a food row and an expense row; those twins must know each
# other). The connection is by CONSTRUCTION (they share the same Save), never
# by keyword inference, so this deliberately bypasses the mention matcher:
# the caller hands over the member ids its commits just returned, and every
# member gets a `part_of` edge to one freshly-derived event:<hash> node.


def event_id_for(members: list[str], for_date: date | None) -> str:
    """Deterministic event id: a hash of the sorted member ids + date. The
    dedupe mechanism — re-posting the same batch (a retried Save, a re-run
    client) derives the SAME id, and create_edge's (source, target, kind)
    idempotence then makes the whole call a no-op instead of double-minting
    a second event over identical members."""
    basis = "\n".join(sorted(members)) + "\n" + (for_date.isoformat() if for_date else "")
    return "event:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def _valid_member_id(member: object) -> str | None:
    """A member must already be a full "<type>:<rest>" graph id (graph.py's
    module docstring is the scheme) — non-strings and malformed ids are the
    caller's bug, reported back in `skipped` rather than silently linked."""
    if not isinstance(member, str):
        return None
    candidate = member.strip()
    node_type, sep, rest = candidate.partition(":")
    if not sep or not node_type or not rest.strip() or any(c.isspace() for c in node_type):
        return None
    return candidate


def link_event(members: list[str], for_date: date | None = None) -> dict:
    """THE one implementation behind both doors (REST POST /graph/event and
    the MCP link_event tool): mints `event:<hash>` and creates `part_of`
    edges member→event (source_of_edge "same_event") for every valid member,
    plus an `on_day` edge event→journal:<date> when a date is given AND that
    journal day actually exists (same existence gate the photo-drop journal
    links use). Guards:

    - fewer than 2 valid members → no-op (a single entry isn't an "event
      grouping", it's noise) — returns event_id None, creates nothing.
    - malformed/duplicate ids are skipped and reported in `skipped`; member
      EXISTENCE is deliberately not checked, same as every other edge write
      (graph.py never validates ids).
    - idempotent: the deterministic event id (see event_id_for) plus
      create_edge's dedupe mean a re-save creates 0 new edges.

    Returns {"event_id", "edges_created", "skipped"} — edges_created counts
    only genuinely NEW edges, so callers/tests can see a re-save was a no-op.
    """
    store = get_graph_store()
    valid: list[str] = []
    skipped: list[str] = []
    for member in members:
        candidate = _valid_member_id(member)
        if candidate is None:
            skipped.append(str(member))
        elif candidate not in valid:
            valid.append(candidate)
    if len(valid) < 2:
        return {"event_id": None, "edges_created": 0, "skipped": skipped}

    event_id = event_id_for(valid, for_date)
    before = {
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM edges WHERE source_id = ? OR target_id = ?", (event_id, event_id)
        )
    }
    for member in valid:
        create_edge(member, event_id, "part_of", SAME_EVENT)
    if for_date is not None and JournalStore(store.data_dir / "journal").load(for_date) is not None:
        create_edge(event_id, f"journal:{for_date.isoformat()}", "on_day", SAME_EVENT)
    after = {
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM edges WHERE source_id = ? OR target_id = ?", (event_id, event_id)
        )
    }
    # Retrieval index (retrieval.py): the ONE shared implementation behind
    # both doors (REST /graph/event, MCP link_event) also indexes the event
    # node it just minted — failure-isolated, never fails the link.
    safe_index_event(event_id, len(valid), for_date)
    return {"event_id": event_id, "edges_created": len(after - before), "skipped": skipped}


# How to label a numeric log row when the graph/day views must emit it as a
# node: (table, row -> label). One definition so /graph and the day bundle
# can never drift apart on what an "expense:12" is called.
_LOG_ROW_LABELS: dict[str, tuple[str, object]] = {
    "expense": ("expense_log", lambda r: f"${r['amount']:.2f} {r['merchant']}".strip()),
    "income": ("income_log", lambda r: f"${r['amount']:.2f} {r['source']}".strip()),
    "food": (
        "food_log",
        lambda r: r["notes"] or r["meal_name"] or r["meal_type"],
    ),
    "exercise": ("exercise_sets", lambda r: r["exercise_name"]),
    "activity": ("activity_log", lambda r: r["description"]),
    "substance": ("substance_log", lambda r: r["substance"]),
    "body_stat": ("body_stats", lambda r: f"{r['metric']} {r['value']:g} {r['unit']}".strip()),
}


def log_row_label(conn: sqlite3.Connection, member_id: str) -> str | None:
    """Label for a "<kind>:<int>" log-row id, straight from its SQLite row —
    expense → "$14.50 Chipotle", food → its description (notes, else the
    meal preset's name), exercise → its name. None when the id isn't a known
    log kind, isn't numeric, or the row is gone (stale edge) — callers emit
    nothing rather than a blank node."""
    node_type, _, rest = member_id.partition(":")
    spec = _LOG_ROW_LABELS.get(node_type)
    if spec is None or not rest.isdigit():
        return None
    table, labeler = spec
    if node_type == "food":
        row = conn.execute(
            "SELECT f.*, m.name AS meal_name FROM food_log f LEFT JOIN meals m ON f.meal_id = m.id WHERE f.id = ?",
            (int(rest),),
        ).fetchone()
    else:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (int(rest),)).fetchone()  # noqa: S608 — table from the fixed map above
    if row is None:
        return None
    return str(labeler(row))
