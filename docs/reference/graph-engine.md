# The graph engine

Derived from code at commit `884d057` on 2026-10-15.

Implemented in [core/quintacle_core/graph.py](../../core/quintacle_core/graph.py)
(394 lines) — Stages 1–3 of `docs/graph-model.md`'s plan, deliberately a
small bespoke system: a folder of edge files as the record, an SQLite table
as the query cache, a handful of functions instead of a query language.
Stage 4 (a real graph database) is explicitly not built.

## Edge file format

One file per edge: `<data_dir>/graph/edges/<YYYYmmdd-HHMMSS>-<6-hex>.md`
(Eastern-time stamp + `secrets.token_hex(3)`). Frontmatter only, empty body:

```markdown
---
source: note:planning/travel/tokyo-itinerary
target: journal:2026-04-10
kind: on_day
source_of_edge: frontmatter_links
created_at: '2026-04-11T21:03:12.481024-04:00'
---
```

Deleting the file (plus its SQLite row) undoes the edge — the same
file-level undo story every other Quintacle write has.

## The `edges` table

Schema in [db.py](../../core/quintacle_core/db.py) (see
[data-and-db.md](data-and-db.md)): `id` (the filename stem),
`source_type`/`source_id`, `target_type`/`target_id` (type = the prefix
before the id's first `:`), `kind`, `source_of_edge`, `created_at`; indexed
on `source_id` and `target_id`. Always derived — `rebuild_from_folder()`
truncates and refills it from the files (run after every sync pull).

## The ID scheme

Node ids are `"<type>:<rest>"` strings; the module never validates types,
it stores whatever callers use. In use today:

| id | produced for |
|---|---|
| `note:<folder>/<slug>` | any KB entry |
| `note:people/<name>/profile` | a person (their profile IS a KB entry; no dedicated prefix) |
| `journal:<iso-date>` | a journal day |
| `experience:<folder>/<slug>` | a travel experience |
| `asset:<folder>/<slug>` | an entry's representative asset (synthesized in `/graph` only, never stored as an edge endpoint) |
| `todo:<id>`, `expense:<id>` | used by MCP write tools as `link_new_entry` entry ids (edges only materialize if the keyword matcher fires) |
| `ingredient:<id>`, `meal:<id>`, `routine:<name>`, `exercise:<name>`, `item:<name>`, `outfit:<name>` | structural nodes synthesized by `/graph` from SQLite/stores; their edges (`made_of`, `includes`) are computed per request, not stored |

## Edge kinds, and where each is created

| kind | meaning | created by |
|---|---|---|
| `related` | generic frontmatter link | `sync_frontmatter_links` default; `link_new_entry` default for untyped candidates |
| `on_day` | links to a `journal:` day | `sync_frontmatter_links`' default `kind_for_target` |
| `mentions_person` | entry text names a tracked person | `link_new_entry` via `EDGE_KIND_BY_CANDIDATE_TYPE["person"]` — called from `/kb/entries` + `/kb/entries/with-asset` (`_sync_note_graph_links`), `/travel/experiences` (create_experience), and every MCP write via `mcp_server/graph_link.py` |
| `at_location` | entry text names a tracked experience | same mechanism, candidate type `experience` — notably `/people` (create_person) linking a new person to the experience they were met at |
| `has_asset` | note → its asset | synthesized in `/graph` per request (not a stored edge) |
| `made_of`, `includes` | meal→ingredient, routine→exercise, outfit→item | synthesized in `/graph` from `meal_ingredients`, routine files, outfit files |

`source_of_edge` provenance values in use: `frontmatter_links` (stated
links), `ai_link` (keyword-matched from entry text — the default), and
`structural` (the create_experience/create_person retrofit links). The
`exif_day_match` value is named in the docstring as an example but photos'
journal-day links actually travel as `links` hints → `frontmatter_links`.

## `link_new_entry(entry_id, entry_type, text, candidates, *, source_of_edge="ai_link")`

THE write-rule hook — call after persisting anything new. It is **pure
deterministic keyword matching, no AI call**:

1. For each candidate `{id, title, type?, kind?}`: skip if id/title missing
   or candidate is the entry itself.
2. Match: `re.search(r"\b" + re.escape(title) + r"\b", text, IGNORECASE)` —
   the candidate's title must appear in the entry's text as a whole word,
   case-insensitive. Nothing fuzzier.
3. Edge kind: candidate's explicit `kind`, else
   `EDGE_KIND_BY_CANDIDATE_TYPE[type]`
   (person→`mentions_person`, experience→`at_location`,
   journal_day→`on_day`), else `related`.
4. `create_edge` is idempotent — an identical (source, target, kind) edge
   is returned, not duplicated.

The function never queries stores; callers assemble candidates (people +
experiences, typically) and decide what `text` means (usually
title + body + joined links). Zero matches → zero edges, silently.

## `sync_frontmatter_links(entry_id, link_titles, title_lookup, kind_for_target=None, source_of_edge="frontmatter_links")`

Materializes an entry's authored `links` list into edges, with **re-sync
semantics**: it diffs against the entry's existing `frontmatter_links`
edges — any previously-materialized edge whose target is no longer in the
current list is removed, new targets are added, unchanged ones are left
alone. So editing a note's links stays correct instead of accumulating.
Scoped to `source_of_edge="frontmatter_links"` edges *from this entry* only,
so it can't clobber `ai_link`/`structural` edges pointing at the same node.

`title_lookup` maps candidate titles → full ids; callers build it from note
titles + journal ISO dates + experience names and canonicalize drifted
titles with `journal.normalize.canonicalize_name` *before* calling (kept
out of graph.py to avoid a journal dependency). Default `kind_for_target`:
`on_day` for `journal:` targets, else `related`.

Callers: the `api.py` startup backfill, `/kb/entries` and
`/kb/entries/with-asset` (`_sync_note_graph_links` in
[nodes/kb/api.py](../../core/quintacle_core/nodes/kb/api.py)),
`/travel/experiences` ([nodes/travel/api.py](../../core/quintacle_core/nodes/travel/api.py)),
and MCP `kb_create_entry` (via `graph_link.py`).

## Queries

All on `GraphEdgeStore` (singleton via `init_graph_store`/`get_graph_store`):

- `all()` — every edge, ordered by `created_at`.
- `edges_from(node_id)` / `reverse_edges(node_id)` — indexed lookups;
  reverse is the "what links to X" that was previously uncomputable without
  a full scan. Module-level `reverse_lookup()` wraps it.
- `neighborhood(node_id, hops)` — a `WITH RECURSIVE` walk over the
  adjacency in either direction up to `hops`, returning
  `{"nodes": [ids], "edges": [...]}` with every edge *between* the reached
  nodes. Raises on negative hops.
- `remove_edge(edge_id)`, `remove_edges_for(node_id, source_of_edge=None)` —
  file + row deletion; the latter optionally scoped by provenance.

Note: `neighborhood`/`reverse_lookup` are engine capabilities consumed by
tests; no REST route or MCP tool exposes them yet (the MCP design doc lists
them as planned graph read tools).

## The startup backfill

`create_app()` (api.py lines 162–176): builds
`{title → id}` from every note title, journal date, and experience name,
canonicalizes each note's/experience's `links` titles against that pool,
and calls `sync_frontmatter_links` per entry. Purpose: notes written before
the edges table existed get their connections materialized, so `/graph`
reading SQLite doesn't silently blank pre-existing links. This reads
frontmatter — distinct from `rebuild_from_folder`, which only recovers
SQLite from already-written edge files.

## Consumers

- **`GET /graph`** (api.py): emits journal-day, note (+`location`), asset,
  and experience nodes; reads every stored edge from the table verbatim;
  then adds the structural ingredient/meal/routine/exercise/wardrobe nodes
  and their computed `made_of`/`includes`/`has_asset` edges. This replaced
  the old recompute-fuzzy-match-on-every-request walk.
- **`GET /kb/graph`** (nodes/kb/api.py): the KB-note half only — each
  note's `links` field is now the *resolved target ids* from
  `edges_from(note_id)` (deduplicated across kinds), not raw title strings.
- **The Graph page** (`frontend/app/kb/graph/page.tsx`): renders `/graph`
  with d3-force.
- **MCP**: every write tool calls the `graph_link.py` adapter; created edge
  files are staged on the write's undo session so undoing a push removes
  its edges ([mcp-server.md](mcp-server.md)).
