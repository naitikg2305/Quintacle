# Invention Disclosure: Deterministic Fact Baking and Privacy-Tiered Graph Retrieval That Let Small On-Device Language Models Answer Over a Personal Knowledge Base

**CONFIDENTIAL — NOT FOR PUBLICATION.** Prepared to support a self-filed US
provisional patent application and a later attorney-drafted non-provisional.
This is not a legal document, and the claim concepts in Section 6 are not
legal claims.

- **Inventor:** Naitik Gupta (sole inventor, to be confirmed; see Section 9)
- **System name:** Quintacle
- **Disclosure date:** 2026-11-05
- **Source of truth:** private git repository `naitikg2305/Quintacle`, branch
  `redone-UI`. File paths below are relative to the repo root. Function names
  are cited so an attorney or examiner can check each statement against the
  code.
- **Drafting note:** an AI coding assistant drafted this disclosure from the
  code and commit history, and the inventor must review it. Every mechanism
  described here exists in code, and Section 7 lists its first commit.

---

## 1. Title (working)

"System and method for answering natural-language questions over a personal
knowledge base with a small local language model, using ingest-time
deterministic fact extraction into a hierarchical knowledge graph, hybrid
retrieval with hierarchy-descending neighbor expansion, and a privacy boundary
enforced across local and cloud model tiers."

Shorter alternatives:
- "Privacy-tiered knowledge-graph retrieval for small on-device language models"
- "Ingest-time fact baking for weak-model question answering over personal data"

---

## 2. Field and Background

### 2.1 Field

Information retrieval and natural-language question answering over personal
data such as photos, documents, journals, logs, and plans, using language
models of different capability and trust levels. The invention applies
especially to models that run on the user's own computer or phone (roughly
1–8 billion parameters), which may optionally escalate to a cloud model.

### 2.2 The problem

1. **Small local models cannot reason over large personal data.** A personal
   archive holds thousands of heterogeneous items. A 4B–8B model has a
   limited context window and weak multi-step reasoning. Suppose you ask it
   "show me my photos from Europe". The photos' own text, such as an AI image
   caption ("coffee on a table"), never says "Europe". The fact that a photo
   is from Europe sits in binary EXIF GPS coordinates, and turning those into
   "Europe" takes three things a small model does badly: reverse geocoding,
   world knowledge about which country belongs to which continent, and
   aggregation across many items.
2. **Privacy versus quality.** Cloud models answer better, but sending
   personal data to them is unacceptable for some items. Existing assistants
   tend to be all-local (lower quality) or all-cloud (no privacy boundary).
   When a user switches models mid-conversation, earlier turns that were
   answered using sensitive context are usually forwarded to the new model
   with the rest of the transcript. That leaks the sensitive content
   indirectly, through the earlier answer text.
3. **Escalation compounds errors.** When a local model's output is poor, a
   naive system asks the stronger model to "fix" it. The stronger model is
   then anchored on the weaker model's mistakes.
4. **Model-driven writes are unsafe.** An external AI agent (for example an
   MCP client) that writes into the knowledge base can corrupt it, and
   per-write human approval breaks the agent's flow.

### 2.3 Existing approaches and their gaps (generic categories)

- **Retrieval-augmented generation (RAG)** with vector search over text
  chunks. It finds only what the text says. Facts held in metadata (GPS,
  capture time, document author) are invisible unless they are
  written into the text, and hierarchical containment ("Vienna is in
  Europe") is not represented.
- **Knowledge-graph-augmented LLM retrieval, for example Microsoft GraphRAG
  (2024).** The LLM builds the graph by extracting entities and summarising
  communities. That makes ingest expensive and non-deterministic, and it
  assumes a capable model at index time. Graph construction is
  model-driven, not deterministic from metadata, and there is no privacy
  tiering across model trust levels.
- **Personal on-device assistants and "recall" products (for example Apple
  Intelligence's on-device and Private Cloud Compute split, Rewind.ai, and
  Microsoft Recall).** They capture personal activity and answer questions
  with local or private-cloud models. Public descriptions centre on
  screen or activity capture plus semantic search, and on a
  device-versus-server compute split. None of them describes (a) per-item
  privacy flags enforced inside the retrieval ranking before the top-k cut,
  (b) removal of earlier conversation turns, by provenance, when a
  conversation crosses from a local to a cloud model, or (c) a
  deterministic place hierarchy baked at ingest.
- **Photo apps with place search (for example Google Photos and Apple
  Photos).** They search by place using server-side or on-device geocoding.
  These are closed search features. They are not an LLM context-assembly
  method, and they do not unify photos, documents, plans, and experiences
  in one graph that a general chat model reads.
- **Hybrid lexical, vector, and graph retrieval with reciprocal-rank fusion
  (RRF).** RRF itself is well-known (Cormack et al., 2009). Its use here is
  not claimed as novel on its own.

The gap this invention fills: **move the reasoning a small model cannot do
out of the model and into deterministic ingest-time code and graph structure.
Enforce privacy at the retrieval and context-assembly layer, keyed to the
trust tier of whichever model will read the context.**

---

## 3. Summary of the Invention

Quintacle is a personal knowledge system. When an item (photo, document,
plan, experience, or log row) is saved, deterministic code extracts the
item's embedded metadata. The code then writes the derived facts in two
forms: as a human-readable line inside the item's searchable text, and as
typed edges in a knowledge graph. Places are linked into a
city → country → continent containment hierarchy whose nodes are virtual
graph-only nodes, or the user's own place notes when those exist. At question
time, retrieval fuses full-text, optional vector, and graph lanes. When a hit
is a place node, retrieval descends the containment hierarchy to attach every
item located anywhere inside that place. As a result, a small model asked
"photos from Europe" receives the actual photos as finished context lines and
has nothing left to infer. Date words in the question are resolved to dates
in code, and the date's records are attached as a finished bundle. Arithmetic
such as totals, rates, and personal records is computed in SQL and handed to
the model as final numbers. Every candidate node passes through a per-request
privacy gate. Its admit-or-deny decision depends on whether the model that
will read the context is local or cloud. Private items are removed before the
retrieval top-k cut, so a cloud model still gets k public results, and
neighbor labels are filtered too. When a conversation escalates from a local
to a cloud model, assistant turns that consumed private context are stripped
together with the user turns that prompted them, and the user sees a count of
private notes left out. Ingest escalation re-runs the cloud model from the
original raw input, never over the local model's output. Writes by external
AI agents are applied immediately, but each tool call stages before-snapshots
of every file and row it touches into one ledger entry, and that entry can be
undone as a unit.

**Key mechanisms**

1. Deterministic ingest-time fact baking into both text and graph (EXIF GPS
   to place line; file metadata to a metadata line and day edges).
2. Place containment hierarchy with virtual nodes, preference for real
   notes, and deferred re-keying.
3. Hybrid retrieval that descends the containment hierarchy for place hits.
4. A privacy gate that depends on the model tier, applied before the top-k
   cut, plus provenance-based turn stripping on a local-to-cloud handoff.
5. Step-back escalation: re-run from the original input with provider
   bookkeeping.
6. Deterministic temporal linking: photos to trip plans by capture day and
   place, and date words to day bundles.
7. A deterministic core with models at the edges: computed facts handed over
   as final values, and a zero-match short-circuit in "serious" mode.
8. Auto-applied agent writes with grouped staged-snapshot undo.
9. Supporting mechanisms: private transcript archive indexing, and a
   provenance-tagged "soft record" of facts the user stated in chat.

---

## 4. Detailed Description

### 4.1 System architecture

```
                         ┌──────────────────────────────────────────────┐
  INGEST (save paths)    │  Drop / editor / MCP write / backfill         │
                         └──────────────┬───────────────────────────────┘
                                        │ raw bytes + text (original kept)
              ┌─────────────────────────┼──────────────────────────────┐
              ▼                         ▼                              ▼
   photo_place.bake_photo_place   file_meta.apply_file_meta   llm_dispatch.parse_structured
   EXIF GPS+time ─► geocode cache  PDF/OOXML/EXIF/MP4 headers   (local first; cloud on
   ─► continent table              ─► 🗂 line + file_meta FM     user "redo" from ORIGINAL)
   ─► 📍 line + place FM           ─► on_day edge → journal:day
              │                         │
              ▼                         ▼
   place_graph.link_note_places ─► located_in / part_of edges ─► trip_photos (during_trip)
              │
              ▼
   ┌───────────────────────────── STORAGE ─────────────────────────────┐
   │ kb/**.md notes (frontmatter + body)   graph/edges/*.md (one/edge) │
   │ SQLite: edges mirror, nodes_index, nodes_fts (FTS5), nodes_vec?   │
   │ conversations/ (outside kb/: transcripts.db, soft_record.db)      │
   │ vault/ (outside kb/, never model-visible)                          │
   └────────────────────────────────────────────────────────────────────┘
              │
  QUERY       ▼
   chat._build_context(gate = PrivacyGate(allow_private = model is local))
     ├─ me_context: computed facts from SQL (PRs, savings rate…)
     ├─ retrieval.retrieve(q, k=8, exclude=gate.exclude_hook())
     │     FTS5 bm25 ⊕ vector (opt.) ─RRF─► filter(exclude) ─► top-k
     │     └─ _neighbors: 1-hop labels + place_graph.members_of descent
     ├─ day_context.detect_dates(q) ─► day_bundle(d, gate)
     └─ my_photos handles (gate-admitted only)
              │ finished-fact context text
              ▼
   local model (Ollama, qwen3:4b/8b)  ──user "Escalate"──►  cloud model
                                          │
                     api.chat_endpoint: strip_private_turns(messages)
                     → private_stripped count shown to user
```

Node identifiers form one namespace shared by the graph, the retrieval
index, and privacy checks (`core/quintacle_core/graph.py` module docstring),
for example `note:<folder>/<slug>`, `journal:<iso-date>`,
`experience:<folder>/<slug>`, `expense:<int>`, and `place:<continent>/<country>/<city>`.
Each edge is stored as a single file (`graph/edges/<ts>-<id>.md`), and a
derived SQLite `edges` table mirrors those files and can be rebuilt from
them with `rebuild_from_folder()`. Because edges are files, the file-snapshot
undo mechanism (4.9) covers graph writes without any extra code.

### 4.2 Mechanism 1: Deterministic ingest-time fact baking ("bake")

**Files:** `core/quintacle_core/nodes/kb/photo_place.py`
(`resolve_photo_place`, `cached_geocode`, `continent_for`,
`compose_place_line`, `insert_place_line`, `bake_photo_place`,
`backfill_photo_places`) and `core/quintacle_core/nodes/kb/file_meta.py`
(`extract_file_meta`, `compose_file_meta_line`, `insert_file_meta_lines`,
`link_file_days`, `apply_file_meta`, `backfill_file_meta`).

**Insight:** the retrieval index sees only title and body text, while key
facts live in binary metadata. Every save path therefore writes those facts
twice: as a visible, marked line in the note body (so FTS and vector lanes
can match them) and as structured frontmatter plus graph edges (so graph
traversal can use them).

**Photo place algorithm**

```
bake_photo_place(note):
  images  ← note's own image assets (re-read from disk, never client metadata)
  private ← note.frontmatter.private
  for each image: location ← EXIF GPS (first found); taken ← EXIF DateTimeOriginal
  if no EXIF location: location ← frontmatter.location (fallback)
  if location:
      key ← f"{lat:.3f},{lon:.3f}"            # ~100 m buckets
      geo ← cache[key] if present
            else (if not private) reverse_geocode(lat,lon) → cache[key]
            else None                          # private: nothing leaves the machine
      place ← {city,state,country} ∪ {continent: TABLE[normalize(country)]}
  line ← "📍 " + join(" · ", [city, state, country (deduped)], continent,
                       "lat, lon" (4 dp), "taken YYYY-MM-DD HH:MM") + " <!-- place -->"
  body ← remove existing place lines; insert line before trailing [asset](…) block
  frontmatter.location ← {lat,lon}; frontmatter.place ← place
  (never raises; save never fails on geocoding)
```

- The continent comes from a static code table of about 250 country-name
  variants (`_CONTINENTS`, `_norm_country`). Unknown countries return
  `None`, so the code never guesses.
- The geocode cache `<data>/geocode-cache.json` sits outside `kb/`, so it is
  never indexed as a note. One photo batch taken at one spot therefore costs
  at most one geocode call.
- The marker comment `<!-- place -->` makes re-runs idempotent: the line is
  replaced, never duplicated. The Markdown renderer hides the comment.
  `retrieval.deterministic_prose_summary` skips the line when it computes
  the one-line summary, but the line stays in the FTS body.

**Worked example:** the user drops `IMG_2041.jpg`. Its EXIF holds GPS
48.20821, 16.37380 and DateTimeOriginal 2027-05-14 15:32. The cache key is
`48.208,16.374`. The cache misses and the note is not private, so the
geocoder returns {Vienna, Vienna, Austria}. The table maps Austria to
Europe. The body gains:

```
📍 Vienna, Austria · Europe · 48.2082, 16.3738 · taken 2027-05-14 15:32 <!-- place -->
```

(The repeated "Vienna" is deduplicated.) Frontmatter gains
`place: {city: Vienna, state: Vienna, country: Austria, continent: Europe}`.
A query for "Austria" now matches through FTS, even though the AI caption
only said "coffee on a table".

**File metadata algorithm (file_meta.py)**

The code re-reads each stored asset from disk. It extracts metadata with
stdlib-only parsers plus Pillow, so it stays phone- and Termux-safe:

- **PDF:** Info dictionary, compressed object streams decoded with zlib, and
  an XMP fallback. Fields: title, author, subject, creator, producer,
  created, modified, pages.
- **OOXML** (docx/xlsx/pptx): `docProps/core.xml` and `app.xml`.
- **Images:** camera make and model, dimensions, and capture time from EXIF.
- **MP4/QuickTime:** a minimal box walker reads `mvhd` duration, Apple
  creationdate, and ©xyz/ISO 6709 GPS.

The code then writes one `🗂 … <!-- filemeta -->` line per asset, for example
`🗂 PDF · "Austria itinerary" · 12 pages · created 2026-11-04 by Naitik · austria.pdf (128 KB)`.
It also stores a structured `file_meta` list. Dates that carry a timezone are
converted to US Eastern (`clock.TIME_ZONE`), so the day a file is linked to
matches the owner's calendar. `link_file_days` creates an
`on_day` edge (with `source_of_edge="file_meta"`) to `journal:<created day>`,
but only when that journal day exists. On each save it removes stale
file_meta day edges.

**What is model-free:** the only model call in these two bake paths is the
cache-missed reverse geocode. Everything else is deterministic parsing and
table lookup. (Section 8 notes that the current geocoder is a cloud LLM
call.)

**Variations and alternative embodiments**
- Reverse geocoding can use an offline gazetteer such as GeoNames or
  OpenStreetMap/Nominatim extracts, a k-d tree over city centroids, an OS
  geocoder (Android `Geocoder`, Apple CLGeocoder), or a small local model.
  The cache key precision can vary (geohash, S2 cells, or H3 cells).
- The containment table can be replaced or extended by ISO 3166 data, a
  geopolitical knowledge base, or user-defined regions ("home region",
  "Schengen").
- Other baked facts work the same way: audio duration, a GPX track's
  bounding place, email headers (sender, date), calendar invitation times,
  and receipt merchant data from OCR.
- The body line can be replaced by any secondary indexed field. What
  matters is that the same derived fact is materialised into both the
  lexical or semantic index and the graph.
- Storage can be a database or object store instead of Markdown files.

### 4.3 Mechanism 2: Place containment hierarchy graph

**File:** `core/quintacle_core/place_graph.py` (`resolve_chain`,
`_real_or_virtual`, `_known_city_id`, `_rekey_unknown_city`, `_link_chain`,
`_sync_source`, `destination_chains`, `members_of`, `place_summary`,
`_reindex`, `link_note_places`, `link_experience_places`, `backfill_places`).

**Data structures**

- **Virtual place node ids:** `place:<continent>`, `place:<continent>/<country>`,
  and `place:<continent>/<country>/<city>`. Each segment is ASCII-folded and
  slugified. The level is the depth of the id. Unknown segments are `_`.
  For example, a city-only experience gets `place:_/_/<city>`. A `_`
  continent or country node is never created.
- **Edges:** `located_in` (item → most specific place) and `part_of`
  (city → country → continent). Both carry `source_of_edge="place_graph"`.
- **Real place notes:** a KB note under `places/**` whose title matches a
  place name case-insensitively is used instead of the virtual node, as in
  `note:places/...`. A real city note keeps at most one country parent.
- **Display labels and summaries** are rows in the retrieval index, so there
  is no registry file. Example: "City in Austria, Europe — 3 photos, 1
  experience". Private photos are left out of these counts (`place_summary`
  checks `is_private_node`).

**Algorithm**

```
link_note_places(note):                  # called on every save path
  chains ← []
  if note.place: chains += resolve_chain(city, country, continent)
  if note in Fun/Travel/Planned and fields.destinations:
      chains += destination_chains(destinations)   # "Vienna, Salzburg, Austria"
  for chain in chains:
      if chain[0] is a city and a place:_/_/<city> node exists:
          re-point every edge of the unknown node to the hierarchical id; drop old index row
      create part_of(child → parent) for consecutive refs (idempotent)
      create located_in(note → chain[0])
  remove this module's located_in edges from note that no longer apply
  reindex touched place nodes + ancestors (summary counts changed)
  link_note_trip_photos(note)                  # Mechanism 6

resolve_chain(city, country, continent):
  continent ← continent or TABLE[country]
  if city and not country:
      country, continent ← borrowed from an existing hierarchical city node
                            with the same slug (no model call), else unknown
  return [city?, country?, continent?] refs, real-note-or-virtual each
```

`destination_chains` tokenises a free-text destination list. A token that
is a known country becomes the country of the cities listed before it. A
lone country or continent links directly.

**Deferred re-keying:** an experience that names only "Graz" is linked to
`place:_/_/graz`. Later a geocoded photo from Graz learns the country.
`_rekey_unknown_city` then moves every edge from `place:_/_/graz` to
`place:europe/austria/graz`, so the earlier experience joins the hierarchy
with no model call and no user action. Test:
`core/tests/test_place_graph.py::test_city_only_experience_is_rekeyed_when_country_learned`.

**Variations:** deeper or different hierarchies (neighbourhood, city,
county, state, country, region, continent; or venue, building, campus);
non-geographic containment hierarchies (project → client → industry;
recipe → cuisine; topic taxonomy); a single directed acyclic graph with
multiple parents (Istanbul in both Europe and Asia); and storage in a graph
database (Neo4j or Kùzu) instead of edge files plus SQLite.

### 4.4 Mechanism 3: Hybrid retrieval with hierarchy-descending neighbor expansion

**File:** `core/quintacle_core/retrieval.py` (`RetrievalIndex.retrieve`,
`_fts_ids`, `_vector_ids`, `_neighbors`, `rrf_merge`, `is_excluded`,
`deterministic_prose_summary`, `prose_summary`).

**Index:** `nodes_index(id, type, title, summary, updated_at)` plus an FTS5
table `nodes_fts(id, title, summary, body)` ranked by bm25 with column
weights title 5, summary 2, body 1. An optional `nodes_vec` lane uses
sqlite-vec and a local embedding model through Ollama. Any failure in the
vector lane, such as a missing package or a stopped daemon, silently
disables that lane.

The summary of a structured row is computed in code (for example "Chipotle —
$14.50 — food — 2026-10-12"). Only prose notes may get a model-written
summary, and only from a model pinned to local, at ingest time. Any failure
falls back to the first content line.

The `retrieve` path calls no model at all.

```
retrieve(query, k, types, exclude):
  pool ← max(5k, 25)
  lanes ← [FTS5 ids (bm25, pool), vector ids (pool) if lane up]
  for (id, score) in RRF(lanes, k_rrf=60), ties broken by id:
      skip if stale / wrong type
      skip if exclude(id)                    # BEFORE the k cut
      hit.neighbors ← _neighbors(id, exclude)
      append; stop at k
_neighbors(id, exclude):
  1-hop edges from graph.neighborhood(id), skipping transcript:* and excluded ids (≤10)
  if id is place:* or note:places/*:
      for m in members_of(id):               # recursive CTE down part_of, then located_in
          skip excluded / transcript; label edge_type "located_in" (≤15)
```

`members_of` is one recursive SQL CTE: it collects the subtree of `part_of`
children under the place, then returns every `located_in` source whose
target is in that subtree.

**Worked example ("photos from Europe"):** a photo note "Quiet Morning" has
the body "Coffee." and `place.country = Austria`. Its text never contains
"Europe". The query "Europe" FTS-matches the virtual node `place:europe`,
whose title is "Europe". `_neighbors(place:europe)` descends to
`place:europe/austria`, then to `place:europe/austria/vienna`, then follows
`located_in` to `note:media/photos/quiet`. The photo then appears in the
context as a labelled neighbor. The chat layer (`nodes/kb/my_photos.py`)
gives each admitted photo a handle `[photo:Pn]`. The model only has to emit
`{{myphoto:Pn}}`, which code turns into an inline image. If the user asked
for photos and the model showed none, code appends a gallery of up to 6
photos ranked against the query. Tests:
`test_place_graph.py::test_retrieval_europe_and_austria_reach_photo_via_place_node`
and `::test_chat_photos_from_europe_surfaces_photo_via_place`.

**Hard structural exclusions:** vault ids and `conversations/` ids are
refused by `is_excluded()` at index-write time. The Vault and the transcript
archive live outside `kb/`, so no indexer ever walks them.

**Variations:** BM25 alone, dense vectors alone, or SPLADE as lanes; other
fusion methods (weighted sum, learned ranker); multi-hop expansion under a
budget; expansion triggered by node type (any containment-typed node, not
only places); on-device vector stores (sqlite-vec, LanceDB, or a phone NPU
embedding runtime such as LiteRT or ExecuTorch).

### 4.5 Mechanism 4: Privacy tiering across the local and cloud model boundary

**Files:** `core/quintacle_core/nodes/kb/privacy.py` (`is_private_meta`,
`is_private_node`, `private_filter`, `without_private_hits`,
`PrivacyGate`, `strip_private_turns`, `private_manual_entry`),
`core/quintacle_core/nodes/kb/chat.py` (`run_kb_chat`, `_build_context`,
`_kb_context`, `_neighbor_line`, `_topic_context`, `_me_block`,
`_day_blocks`), `core/quintacle_core/nodes/kb/api.py` (`chat_endpoint`),
`core/quintacle_core/nodes/kb/transcripts.py`, and
`core/quintacle_core/mcp_server/server.py`.

**Rule:** a note with `private: true` in its frontmatter may enter the context
of a local model. It must never enter the context of a cloud model or an MCP
client, since every MCP client is treated as cloud. The owner still sees the
note everywhere. This is an AI-visibility boundary, not encryption.

**The PrivacyGate** is built once per chat request, as
`PrivacyGate(store, allow_private = resolved_model.provider == "local")`.

```
class PrivacyGate:
  exclude_hook(): None if allow_private else private_predicate   # → retrieval
  admit(node_id):
      if not private(node_id): return True
      if not allow_private:    return False
      used.add(node_id); return True       # provenance: which private notes fed this reply
```

The gate is threaded through every context source: retrieval (as the
exclude hook, applied before the top-k cut), each hit's body, the titles in
neighbor labels ("a private note's title is content too"), the topic note,
the "Me" notes, the day-bundle connections, and photo handles. Each surface
re-checks `admit()` as a second layer of defence.

**Provenance and the handoff strip (`api.chat_endpoint`)**

1. On a local reply, the response includes `private_notes`, the sorted ids
   from `gate.used`. The frontend stores these ids on that assistant
   message.
2. When the user escalates the same conversation to a cloud model, the
   request runs `strip_private_turns(messages)` before anything is sent:

```
strip_private_turns(messages):
  for i, m in messages:
     if m.role == assistant and m.private_notes non-empty:
        drop i; left_out ∪= m.private_notes
        if messages[i-1] is the user turn that prompted it and isn't the newest: drop i-1
  remove marker key from all kept messages (providers reject unknown keys)
  return kept, |left_out|
```

   Removing turns in pairs keeps the user and assistant turns alternating,
   which every provider API requires. The newest user question is always
   kept. The response returns `private_stripped = |distinct private notes|`
   so the UI can show "N private notes left out".
3. All other context transfers in full. Context is assembled the same way
   for every provider, so escalation carries over the full public context.

**Worked example:** a note `health/therapy-notes` is private. With the
local model `local:qwen3:4b`, the user asks "what did my therapist suggest
about sleep?". The gate admits the note, records it in `used`, and the reply
returns `private_notes: ["note:health/therapy-notes"]`. Next the user asks
"what's a good sleep app?" and clicks Escalate to a cloud model. The cloud
request drops the first question and its answer, keeps "what's a good sleep
app?", rebuilds context with the private note excluded before the top-k cut,
and the UI shows "1 private note left out".

**Other surfaces that use the same definition**
- **Transcript archive** (`transcripts.py`): the verbatim file keeps every
  turn as the owner's record. The FTS row, which is the only lane that reads
  the archive and can feed a model, is built without the assistant turns
  that consumed private context. The count is stamped as `private_turns`.
- **MCP server:** a private note reads as "not found", with the same error
  as a missing note (`_refuse_private`), so the agent cannot even learn the
  note exists. Retrieval runs with `exclude=private_filter`, and
  `without_private_hits` filters the results a second time. Day-recall
  bundles drop private photos and private event members. Assets owned by a
  private note are refused.
- **Ingest:** the "Private, skip AI" drop (`private_manual_entry`) makes
  zero model calls. The frontend disables "Redo with cloud" while any
  pending proposal is marked private. Geocoding of a private photo runs
  only on a cache hit, so nothing leaves the machine.
- **Suggesters:** `public_notes_index` keeps private titles out of the
  folder and title lists handed to sorting models that may be cloud.

**Variations:** more than two tiers (on-device NPU, then home server, then
enterprise private cloud, then public cloud), with a clearance level per
item and a trust level per model, where an item is admitted only if
clearance ≤ trust. Tiers can be keyed to attributes other than locality
(jurisdiction, vendor, retention policy). Privacy can be inherited along
graph edges (a photo's privacy spreads to its derived place-count
summaries, which is already done for counts). Instead of stripping, a
private turn can be replaced with a redacted placeholder or a local-model
summary that has been checked to contain no private tokens. The flag can be
set per field rather than per note.

### 4.6 Mechanism 5: Step-back escalation from the original input

**Files:** `core/quintacle_core/llm_dispatch.py` (`parse_structured`,
`_parse_local`, `_parse_cloud`, `collect_providers`,
`summarize_providers`, `ParseResult.provider_used`),
`core/quintacle_core/api.py` (the drop endpoint's `provider` parameter),
`core/quintacle_core/nodes/journal/api.py`, `core/quintacle_core/nodes/kb/api.py`
(`/kb/sort`), `frontend/app/kb/page.tsx` (`redoWithCloud`),
`frontend/app/journal/page.tsx`. Design record: `docs/architecture.md`
("Amendment 2026-10-15") and `docs/local-inference-migration.md`.

**Algorithm**

```
parse_structured(system, input, Schema, provider=None):
  mode ← provider or ENV or "auto"
  if mode in {local, auto}:
     try: out ← Ollama /api/chat with format = Schema.json_schema(), think=false
          validate with Pydantic; return (out, "local")
     except (daemon down | model missing | schema-invalid):
          if mode == local: raise
  return (cloud structured parse, "cloud")
```

A per-request `ContextVar` collector records which provider served each call.
The endpoint reports one value, `provider_used`, which is local, cloud,
mixed, or null (null means fully deterministic handling). The frontend
offers "Redo with cloud ↻" only when local answered. It keeps a snapshot of
the original input (text and files) and re-sends that same snapshot with
`provider=cloud`. The new proposals replace the old ones, and nothing is
committed until the user clicks Save (propose → review → save). The
cloud model never sees the local model's output. Chat escalation works
similarly. The conversation (minus private turns, Mechanism 4) and freshly
assembled context are sent to the cloud model, not a summary written by the
local model.

**Variations:** automatic step-back triggered by a confidence or validation
score instead of a user click; a cascade of more than two levels (1B NPU →
8B desktop → cloud); a re-run with a different local model; keeping both
proposals for comparison.

### 4.7 Mechanism 6: Deterministic temporal linking

**Files:** `core/quintacle_core/trip_photos.py` (`plan_window`,
`parse_body_dates`, `plan_destinations`, `photo_info`, `matches`,
`sync_photo`, `sync_plan`, `link_note_trip_photos`, `backfill_trip_photos`,
`photos_for_plan`), `core/quintacle_core/day_bundle.py`
(`day_photos`, `build_day_bundle`), and
`core/quintacle_core/nodes/kb/day_context.py` (`detect_dates`, `day_bundle`,
`me_context`).

**Photo to trip plan rule:** a photo P belongs to a plan T when both
conditions hold:

```
matches(P, T) := T.start ≤ P.capture_day ≤ T.end
                 ∧ (T.destinations = ∅ ∨ slugs(T.destinations) ∩ slugs({P.city, P.state, P.country, P.continent}) ≠ ∅)
```

The edge created is `note:<photo> --during_trip--> note:<plan>`. The photo's
capture day comes from EXIF via `file_meta[].taken`, or else from the
"taken" field on the 📍 line. A photo with no capture date is never linked,
because the save date says nothing about when a photo was taken. If the plan
lacks structured dates, regex patterns over its body supply the window:
explicit ranges first, then the min..max of standalone dates, but only when
they span 60 days or less. If the plan has no destinations, only city names
that already exist as place nodes are checked against its body, so the code
never pulls a guessed city out of prose. Edges are re-synced in both
directions: saving a photo recomputes its outgoing edges, and saving a plan
recomputes its incoming ones.

**Worked example:** a plan has `fields.start=2027-05-12`,
`end=2027-05-21`, and `destinations="Vienna, Salzburg, Austria"`. A photo
taken 2027-05-14 with `place.country=Austria` is linked. A photo taken
2027-05-14 in Prague, Czechia is not linked. A photo taken 2027-05-25 in
Vienna is not linked.

**Date words resolved in code (`detect_dates`):** explicit forms (ISO,
M/D, "April 14", "14th of April") and relative words ("yesterday", "last
tuesday", "two weeks ago") are resolved against `clock.today()` in Eastern
Time. A month-day without a year resolves to the most recent past
occurrence. `chat._day_blocks` hydrates up to 3 resolved dates per turn into
headed "that day's record" blocks. Each block holds the journal text, every
SQLite log row for the date as its computed one-liner, todos, and events
with 1-hop people and place labels. Photos are found through `on_day`
edges on the materialised edges table, using one indexed query, never a KB
walk. The block is capped at about 6,000 characters and truncated from the
last section backwards, deterministically. The same bundle code serves the
REST `/day/{date}` endpoint and the MCP `day_recall` tool.

**Variations:** other temporal joins (receipts to trips by transaction
date; workouts to travel days; documents created during a project window);
fuzzy windows (± travel day); timezone-of-capture handling derived from GPS.

### 4.8 Mechanism 7: Deterministic core, models at the edges

**Principle** (`CLAUDE.md`, `docs/architecture.md`): code fetches and
decides, and anything arithmetic is computed in code and handed to models as
finished numbers.

**Instances in code**
- `day_context._computed_me_facts`: strength PRs (max weight per exercise),
  this month's income, spend, and savings rate, and latest body stats are
  computed live in SQL at ask time and never stored. They are sent with the
  instruction "these are current and final; use them as-is, never
  recalculate".
- Structured-row summaries in the retrieval index are composed from fields,
  so numbers come from SQL.
- The **serious-mode zero-match short-circuit** (`run_kb_chat`): in
  "serious" mode, if nothing grounds the question, no model is called at
  all, whatever the provider. A fixed deterministic reply is returned, so an
  escalation gets the same answer.
- Mode switching is decided by whole-phrase matching, not model judgment.
- Reply post-validation (`validate_reply_links`) rewrites links the model
  emitted to notes that do not exist.

### 4.9 Mechanism 8: Auto-applied agent writes with grouped staged-snapshot undo

**Files:** `core/quintacle_core/mcp_server/undo.py` (`WriteSession`,
`FileStep`, `JournalAppendStep`, `SqliteRowStep`, `NewDirStep`, `undo`) and
`core/quintacle_core/mcp_server/ledger.py` (`Ledger`, `LedgerEntry`).

```
tool call:
  s ← WriteSession(ledger, tool, client, summary)
  before touching file F:   s.stage_file(F)         # full prior bytes or "absent"
  before UPDATE/DELETE row: s.stage_sqlite_row(...) # full prior row
  after INSERT:             s.stage_sqlite_insert(pk)
  journal append:           s.stage_journal_append(marker)  # exact span, not whole file
  … perform real writes (including edge files created by place_graph/trip_photos) …
  id ← s.commit()   # ONE ledger entry, JSON fenced inside human-readable markdown
undo(id): replay steps in reverse; mark entry undone (never deleted)
```

Undo is allowed to touch only an allow-listed set of tables. Graph edges are
files, so the edges an MCP write creates as a side effect (place and
trip-photo links) are captured as `FileStep`s, and undo removes them too.
Test: `test_place_graph.py::test_mcp_attach_links_and_undo_removes_edges`.
The undo for a journal append removes only its own marked span, so other
appends to the same day survive.

Within the app, model output follows propose → review → Save instead, and
the model never writes directly. The project rule is that no write path may
lack both of these properties.

**Variations:** content-addressed snapshots instead of full bytes;
copy-on-write file systems; time-limited undo windows applied as UI policy;
showing the ledger in a "recent writes" page.

### 4.10 Supporting mechanisms (optional dependent material)

- **Second-tier transcript archive** (`nodes/kb/transcripts.py`): verbatim
  chat files live outside `kb/` with their own FTS database
  (`conversations/transcripts.db`). Only an explicit "deep search" endpoint
  reads them. A per-reply autosave keyed by `session_id` rewrites the same
  file and FTS row. A `transcript_of` graph edge is created only when the
  chat subject confidently names a real node.
- **Soft record** (`nodes/kb/soft_record.py`): straight facts the user
  stated in archived chats, each with its date and source transcript path.
  The facts are extracted after the request has returned by one
  local-pinned model call. They are kept outside the main index and graph,
  and they become KB knowledge only through an explicit "Record that".

---

## 5. Advantages and Technical Effects

1. **The reasoning burden moves from the model to ingest.** "Photos from
   Europe" needs no geocoding, containment reasoning, or aggregation by the
   model. The answer set comes from graph traversal and reaches the model
   as labelled context lines plus handles. This is what makes 4B–8B local
   models workable (the phone default is `local:qwen3:4b` and the desktop
   default `local:qwen3:8b`, per `docs/session-log.md`). **Caveat:** no
   controlled accuracy comparison of 4B with and without baking has been run
   yet. Running one on preset-seeded data, as the project rules require,
   would make this effect measurable before the non-provisional.
2. **Model calls at ingest and retrieval.** EXIF and file-metadata
   extraction, continent mapping, place linking, trip linking, date
   resolution, and the whole `retrieve()` path make zero model calls. The
   only model touchpoints are (a) a reverse geocode on a cache miss, about
   one per 100 m cell, (b) an optional local-only one-line summary for
   prose notes, and (c) classification and parsing at drop.
3. **Determinism and testability.** The tests run with model seams turned
   off (`QUINTACLE_SUMMARY_PROVIDER=off`, `QUINTACLE_SOFT_RECORD_PROVIDER=off`),
   and the outputs are reproducible. Session log, 2026-11-05: 938 tests
   passed. Directly relevant suites include `test_photo_place.py` (15
   tests), `test_file_meta.py` (26), `test_place_graph.py` (17),
   `test_trip_photos.py` (10), `test_retrieval.py` (23),
   `test_day_context.py` (28), `test_llm_dispatch.py` (18),
   `test_mcp_undo.py` (7), `test_private_notes.py`, and `test_transcripts.py`.
4. **The cloud still gets k results.** Because the private filter runs
   before the top-k cut, a cloud request still receives k public results.
   Filtering after the cut would return fewer than k, or none.
5. **Privacy also covers indirect leaks.** Turn stripping by provenance
   removes earlier answer text derived from private context, not only the
   source notes. The user sees a count, so the leak boundary is auditable.
6. **Escalation that is not anchored on local errors.** The cloud model
   starts from the original input.
7. **Agent autonomy without data loss.** Every agent write can be undone as
   one unit, including its side-effect graph edges.
8. **Runs on the phone.** Core extraction uses only the stdlib and Pillow,
   and heavy dependencies (sqlite-vec, perception) are optional lazy
   imports. The full test suite passes without them.

---

## 6. Draft Claim Concepts (for the attorney; not legal claims)

**Concept A (ingest-time fact baking plus containment-descending retrieval for a small model).**
A computer-implemented method comprising:
(a) on storing a content item that has embedded machine-readable metadata
(e.g., geographic coordinates and capture time), deterministically
extracting the metadata;
(b) resolving the coordinates to a place name set through a cached resolver
keyed by quantised coordinates, and deriving at least one higher containment
level (e.g., continent) from a stored lookup table without a language model;
(c) writing a human-readable representation of the derived facts into the
item's indexed text *and* creating graph edges linking the item to a place
node, with the place nodes linked by containment edges into a hierarchy;
(d) on receiving a natural-language query, ranking nodes with at least a
lexical index, and for each top-ranked node that is a containment node,
recursively traversing the containment edges downward and attaching every
item linked to any descendant as context; and
(e) supplying the assembled context to a language model to generate the
response.

*Dependent variations:* idempotent marker-delimited text lines; virtual
place nodes replaced by user-authored place notes when titles match;
placeholder ids for unknown hierarchy levels, re-keyed when a later item
supplies the missing level; reciprocal-rank fusion of lexical and vector
lanes; per-place summaries with computed member counts that exclude
private members; file-metadata (PDF/OOXML/MP4) creation dates linked to
calendar-day nodes; a temporal join of items to plans by
date-window ∩ place match; model-emitted handles converted by code into
rendered media; and a code-appended fallback gallery.

**Concept B (privacy gate tied to the model's trust tier, plus a provenance-based handoff strip).**
A system comprising a plurality of language models of differing trust
tiers (e.g., local and remote), a knowledge store whose items carry a
privacy attribute, and a context assembler configured to:
(a) determine the trust tier of the model selected for a request;
(b) apply an exclusion predicate derived from the privacy attribute and
the trust tier to retrieval candidates *before* selecting the top-k
results, and to every neighbor label and auxiliary context source;
(c) when an item with the privacy attribute is admitted (higher-tier model
only), record its identifier as provenance on the generated response; and
(d) on a later request in the same conversation directed to a lower-trust
model, remove from the conversation history every response carrying such
provenance together with its prompting user turn, while keeping turn
alternation and the current query, and report a count of withheld items to
the user.

*Dependent variations:* agent-protocol (MCP) clients treated as the lower
tier, with private items answered with the same error as nonexistent items;
private-provenance turns kept in the verbatim transcript but excluded from
its search index; zero-model "private" ingest; disabling cloud re-run while
a private proposal is pending; geocoding of private items restricted to the
local cache; N > 2 tiers with clearance ≤ trust.

**Concept C (a local-first ingest and answer pipeline with step-back escalation and undoable agent writes).**
A method comprising:
(a) processing a raw input with a local model under schema-constrained
decoding, validating the output against the schema, and recording which
provider produced each result in a per-request collector;
(b) presenting a proposal for user review without committing it;
(c) on a user escalation, re-sending the *original raw input snapshot*, not
the local output, to a remote model, and replacing the proposal; and
(d) for writes initiated by an external AI agent, staging pre-write
snapshots of every file, database row, and appended text span touched by a
tool call (including derived graph-edge files), committing them as one
ledger entry, and reversing them as a unit on request.

*Dependent variations:* automatic fallback on local failure; arithmetic
facts computed by database queries and handed to the model labelled as
final; date expressions in queries resolved by code to day bundles; a
no-model deterministic reply when no grounding exists in a strict mode.

*Attorney note:* Concepts A and B look like the strongest candidates.
Concept C's parts are each closer to known practice (cascades, undo logs),
so it may work better as dependent matter or a separate application. Think
about subject-matter eligibility (35 U.S.C. §101 / Alice) and frame the
claims around concrete technical effects: fewer model calls, a
context-window budget, enforcing privacy before the top-k cut, and keeping
turn-alternation constraints valid.

---

## 7. Reduction-to-Practice Evidence

All commits are by `naitikg <naitikg2305@gmail.com>` (a personal address) in
the private repo. Times are local, Eastern. The earliest commit is a
snapshot that contains code written before the repo's history began.
Evidence for anything earlier than that snapshot would have to come from
other records.

| # | Mechanism | Key file(s) | First commit | Date (local) |
|---|---|---|---|---|
| — | Repo history begins (snapshot; includes early `on_day` journal edges and chat) | `nodes/kb/chat.py` | `c9cd583` | 2026-09-18 Fri 14:54 |
| 7 | Eastern Time clock (deterministic dates) | `clock.py` | `b29e2f6` | 2026-10-07 Wed 15:16 |
| 8 | MCP staged-snapshot undo + ledger | `mcp_server/undo.py`, `ledger.py` | `9d132ba` | 2026-10-13 Tue 18:33 |
| 2 (base) | Graph engine: edge files + SQLite mirror | `graph.py` | `5db7a4f` | 2026-10-13 Tue 18:38 |
| 6 | Day-recall bundle (photos via `on_day`) | `day_bundle.py` | `cc29b0a` | 2026-10-15 Thu 13:08 |
| 5 | Local-first dispatch, step-back redo, chat escalation | `llm_dispatch.py` | `aeef046` | 2026-10-15 Thu 14:16 |
| 9 | Transcript archive, separate FTS | `nodes/kb/transcripts.py` | `96a1569` | 2026-10-19 Mon 18:02 |
| 3 | Hybrid retrieval (FTS5 + vec + graph, RRF) | `retrieval.py` | `20e08b8` | 2026-10-19 Mon 18:10 |
| 6/7 | `detect_dates`, day bundle in chat, computed Me facts | `nodes/kb/day_context.py` | `5e20a25` | 2026-10-20 Tue 15:19 |
| 7/9 | Serious/unserious modes, zero-match short-circuit, soft record | `nodes/kb/soft_record.py`, `chat.py` | `78b9564` | 2026-10-27 Tue 14:12 |
| 4 (base) | Private-note flag base | `nodes/kb/privacy.py` | `ec70fb6` | 2026-11-05 Thu 00:27 |
| 4 | PrivacyGate, exclude hook before top-k, `strip_private_turns`, transcript private turns, MCP filtering | `privacy.py`, `retrieval.py`, `api.py`, `transcripts.py`, `server.py` | `df4d910` | 2026-11-05 Thu 00:46 |
| 1 | Photo place bake (EXIF → 📍 line + `place`) | `nodes/kb/photo_place.py` | `396092e` | 2026-11-05 Thu 14:02 |
| 2/3 | Place hierarchy + `members_of` descent in retrieval | `place_graph.py`, `retrieval.py` | `1a14e71` | 2026-11-05 Thu 14:14 |
| 1 | File-metadata bake + `on_day` edges | `nodes/kb/file_meta.py` | `79d8426` | 2026-11-05 Thu 14:16 |
| 3 | Owner photos inline in chat (handles + fallback gallery) | `nodes/kb/my_photos.py` | `11d278a` | 2026-11-05 Thu 14:37 |
| 6 | Trip ↔ photos temporal + place join | `trip_photos.py` | `fd19dea` | 2026-11-05 Thu 14:39 |

The design records are dated decision logs in `docs/`:
`docs/architecture.md` ("Amendment 2026-10-15" and "Note 2026-10-15 — the
five-layer formulation"), `docs/local-inference-migration.md`,
`docs/next-wave-plan.md` (§3 retrieval and §10 time grounding, both
2026-10-19/20), and `docs/session-log.md`, whose entries are dated
2026-11-05 for the place, trip, privacy, and photo work.

The owner's statement of conception is quoted in `place_graph.py`'s
docstring: "link everything on the graph so weak AIs can answer stuff". The
owner's thesis is in `docs/pr-pitch.md`, dated 2026-10-15.

To reproduce, run `git log --follow --format='%h %ad %s' --date=short -- <file>`
for each file. Run the tests with `cd core && .venv/bin/python -m pytest -q`.

---

## 8. Prior Art to Check, and How This Differs

| Category / example | What it does | Difference to argue |
|---|---|---|
| Microsoft GraphRAG (2024) and LLM-built KG RAG | An LLM extracts entities and summarises communities at index time | Here the graph comes deterministically from metadata, with no LLM in construction except a cached geocode. Retrieval descends a containment hierarchy, and a privacy tier is enforced before the top-k cut. |
| KG-augmented LLM QA literature (KGQA, "Think-on-Graph", subgraph retrieval) | The LLM traverses or reasons over a graph | Here code traverses the graph and the model only reads the result. The design targets weak local models. |
| Hybrid search with RRF (Cormack 2009; Elastic, Vespa, Weaviate hybrid) | Fuses lexical and vector results | RRF is not novel. The novelty is in combining it with privacy filtering before top-k and containment descent. |
| Apple Intelligence / Private Cloud Compute | Splits compute between device and server, with server-side privacy guarantees | No per-item privacy attribute gating retrieval by model tier is publicly described, and no provenance-based conversation stripping on escalation. Check Apple's patents on on-device and server context partitioning. |
| Rewind.ai / Limitless; Microsoft Recall | Capture screens or activity, then local semantic search plus an LLM | No metadata-to-hierarchy baking and no tiered stripping. Check Recall's filtering of private or sensitive content (it excludes apps and sites at capture, not at retrieval by model tier). |
| Google Photos / Apple Photos place search | Geocode photos and search by place, including country | This is very close prior art for the place-hierarchy part alone. The difference has to rest on unified LLM context assembly across item types, writing into both text and graph, deferred re-keying, and the privacy tier. |
| Mem.ai, Notion AI, Obsidian Smart Connections, Khoj, PrivateGPT, AnythingLLM | Personal or local RAG over notes | Mostly chunk RAG. Check Khoj and PrivateGPT for local and cloud model switching, and for any history filtering. |
| Model cascades and fallbacks (FrugalGPT 2023; router literature) | Escalate to a stronger model on low confidence | The original-input re-run is a possible point of difference. Some cascade papers already re-query from the original prompt, which weakens this. |
| DLP / PII redaction proxies for LLMs (e.g., Nightfall, Private AI, LLM-gateway redaction) | Redact sensitive spans before cloud calls | These redact at the span level by detection. The distinction here is item-level provenance and turn-pair removal. Check for prior "conversation sanitisation on model switch". |
| Database undo logs / event sourcing / agent sandboxes | Undo logs and journalling | Generic undo is well-known, so this is likely weak as an independent claim. |

**Things that weaken novelty (candid)**
1. Place search over geotagged photos, including at country level, is
   widespread (Google Photos, Apple Photos). Mechanisms 1 and 2 alone are
   likely obvious. Their value is in the combination with LLM context
   assembly and the privacy tier.
2. The current reverse geocoder is a cloud LLM call
   (`photo_organizer.geocode`, which `llm_dispatch.py`'s docstring
   documents as an exception). That weakens the "deterministic,
   local-first" framing for ingest. Claim the resolver generically (any
   cached resolver) and list offline gazetteers as an embodiment. Ideally,
   implement an offline geocoder before the non-provisional.
3. In `auto` mode, ingest parsing falls back silently to cloud when local
   fails. That fallback does not consult the privacy flag of the input (an
   unsaved drop has no flag yet). Only the explicit "Private, skip AI" path
   and the disabled redo protect private input. Disclose the fallback
   honestly, and do not claim that ingest never reaches cloud.
4. The privacy boundary is a visibility flag, not cryptographic. A user
   could paste private content into a cloud chat by hand.
5. There is no quantitative evaluation yet of small-model accuracy with and
   without baking (see Section 5, item 1).
6. Much of the novel work (privacy, places, trips, file metadata) was first
   committed on 2026-11-05, the same day as this disclosure. That is fine
   for priority if filed promptly, but it gives little evidence of extended
   reduction to practice.
7. Several mechanisms are ordinary engineering practice (RRF, undo logs,
   schema-constrained decoding, regex date parsing). Claims must rest on
   the combinations, not on these parts alone.

---

## 9. Open Questions for the Attorney

1. **Employer IP assignment (Minfy).** The owner works at Minfy. Review the
   employment agreement's invention-assignment and moonlighting clauses,
   including any "relates to employer's business" scope. Minfy is an AWS
   consulting firm, and this system has a Bedrock provider
   (`chat._run_bedrock`), which may matter. Also check whether any state
   statute applies, such as California Labor Code §2870 or the equivalent
   in the owner's state.
2. **Company time and equipment.** The commit history shows many commits on
   weekday afternoons, roughly 13:00–18:00 Eastern; the most frequent slots
   are Tue/Thu 14:00. Confirm whether those were working hours, and whether
   any company laptop, cloud account, API key, or AWS account (including
   Bedrock credentials) was used. Commits use a personal email address and
   a personal GitHub account.
3. **Inventorship and AI assistance.** Most of the code was written by AI
   coding assistants under the owner's direction; commits carry
   "Co-Authored-By: Claude" trailers. Under USPTO guidance on AI-assisted
   inventions (February 2024), only natural persons who significantly
   contributed to the conception of each claim are inventors. Document
   which concepts the owner originated. Candidates are the "link everything
   on the graph so weak AIs can answer" directive, the local-first
   step-back rule, and the private-note rule with handoff stripping, which
   the code docstrings label as owner rules dated 2026-11-05 and 2026-10-15.
   Separate those from implementation details the AI proposed, and frame
   the claims around the owner-conceived parts. Confirm sole inventorship.
4. **Prior disclosure.** `docs/pr-pitch.md` is "PR/marketing material"
   drafted 2026-10-15. Confirm whether any of it, or any demo, post, or
   talk, has been made public. A public disclosure starts the one-year US
   grace period (35 U.S.C. §102(b)(1)) and may bar foreign filing in
   absolute-novelty jurisdictions.
5. **Scope of the provisional.** Should one provisional cover Concepts A–C,
   to be split later? Include enough embodiments (Sections 4.2–4.7
   variations) to support broader claims later.
6. **Trade secret versus patent.** Some parts (the bake pipeline and the
   prompting) could stay trade secrets if the repo stays private. Decide
   what to disclose.
7. **Open-source plans.** If the owner plans to open-source Quintacle, file
   before publishing, and think about how the licence interacts with any
   patents (for example Apache-2.0's patent grant).

---

*End of disclosure. To revise it, add dated notes rather than rewriting
earlier text, following the project's decision-log convention.*
