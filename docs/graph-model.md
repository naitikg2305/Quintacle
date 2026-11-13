# Quintacle — Graph Model (foundational)

## The reframe

This isn't a set of separate domain folders that occasionally reference each
other — the whole app is a **graph**. Obsidian-like (notes + links + a graph
view), but multi-modal and code-driven:

- **Multi-modal nodes.** Not just markdown text — photos, videos, STL files (3D
  printing), documents, and more are all first-class nodes in the graph, same as
  a text note would be.
- **Code-computed edges, not manual links.** Obsidian relies on hand-typed
  `[[wikilinks]]`. Here, code (and models like YOLO/VLM where relevant) establish
  the connections — e.g. a photo from a given day auto-links to that day's journal
  entry; a ledger purchase auto-links to the grocery list it fulfilled; an outfit
  photo auto-links to the calendar event it was worn to.
- **The end goal, stated directly:** the graph, in its totality, is meant to be
  "a snapshot of my brain."

## Two levels of "node" — reconciling this with `architecture.md`

Everything discussed so far (Journal, Ledger, Schemes, Outfits, Apartment, Car,
Routines, Vault, etc.) was "node" at the **domain level** — 12 macro subsystems.
This reframe adds a second, finer level underneath:

1. **Domain nodes (macro)** — the 12 subsystems already documented, each owning
   its own folder/schema.
2. **Item nodes (micro)** — every individual artifact inside those domains (one
   markdown note, one photo, one STL file, one video) is itself a graph node,
   and it can link to other item nodes *across* domains, not just within its own.

`architecture.md`'s core principle — deterministic code fetches exact data, AI
only narrates/parses at the edges — still holds. The graph is the *shape* of the
data being fetched; deterministic traversal (not semantic RAG search) is still
how a query walks from node to node.

## Relationship to Obsidian, precisely

| | Obsidian | Quintacle |
|---|---|---|
| Node types | markdown notes only | markdown, photos, videos, STL, docs, etc. |
| Edges | manual `[[wikilink]]`, typed by hand | code-computed, often automatic |
| Graph view | visual, for browsing | **yes, planned** — a literal visual graph, not just an internal data model |

## The access layer sits on top of the graph

The graph itself is inert — just structured data. On top of it sits a control
layer that decides *how* any given request actually reaches into the graph:
which nodes to touch, which edges to walk, what to fetch. That layer is a
combination of two things working together, not one or the other alone:

- **Naitik's own code, fully designed** — the deterministic traversal logic:
  given a query shape, know exactly where in the graph to go (this is the
  concrete mechanism behind `architecture.md`'s "deterministic fetch" principle).
- **An LLM** — sitting alongside that code, presumably for the parts that aren't
  purely deterministic (interpreting an ambiguous request, deciding *which* deterministic
  path applies, or the narration step already described in `architecture.md`).

So the full picture is three layers stacked:

```
graph (item nodes + domain nodes, code-computed edges)   <- graph-model.md
        ^
access/control layer (his own code + an LLM, deciding how to reach in)
        ^
whichever surface asks the question (phone app / computer app)
```

This is consistent with `architecture.md` and `deployment-and-privacy.md` — it
just names the middle layer explicitly, instead of leaving "deterministic fetch"
and "the LLM" as separate ideas without a shared home.

## Shape vs. engine (2026-10-13)

> *2026-10-15: the "Quintacle has none of this" below was true when written
> and isn't anymore — the engine plan's Stages 1–3 were built on 2026-10-13
> (`core/quintacle_core/graph.py`). See the status update under the plan
> heading below, and `reference/graph-engine.md` for the as-built detail.*

Worth being precise about what exists today, because "graph" overloads two
different things:

- **Graph shape** — nodes + edges as data. Quintacle has this: KB notes
  carry a `links: [...]` frontmatter field, code auto-links across domains
  (a photo to its day's journal entry, an expense to the KB note it came
  from), and `GET /graph` / `/kb/graph` (`api.py`) walk those fields at read
  time into a node/edge list for the graph view. This is exactly Obsidian's
  model — `[[wikilinks]]` as plain references in files — except code sets
  the links instead of a human typing them.
- **Graph engine** — a query layer like Neo4j/Cypher that indexes edges and
  can do a multi-hop query or a cascading update (`MATCH ... SET`) touching
  every matching node in one atomic operation. Quintacle has **none** of
  this. "Update multiple things" today means Python explicitly calling
  several stores' `.write()` methods — deterministic and enumerated, never
  an open-ended query walking the graph on its own.

This isn't a gap to rush to close — `architecture.md`'s thesis is deliberately
against an open-ended query engine deciding what to touch. The one place a
multi-write "one query" shape is actually wanted is the MCP approval queue
([[mcp-angle.md]]): one proposal can legitimately bundle several store
writes (add a note, link it to N existing ones, update a day's journal
link), and the human approves the bundle in one tap. That's graph-shaped
writing without a general graph engine underneath it.

If multi-hop queries or bulk relink-on-rename are ever actually needed, the
cheapest next step is edge rows in SQLite (already in the stack, already
indexed) before reaching for a dedicated graph database — see the open
question below on what an edge technically is.

## The graph engine plan — future-proofing (2026-10-13)

Status: **plan, not started.** Nothing here needs building yet — today's flat
recompute-on-read `/graph` is fine at current scale. This is the staged path
to reach for *when* it stops being fine, written down now so there's
somewhere to go instead of a rewrite under pressure later. Each stage is
independently useful — none of them requires committing to the next.

> **Status update 2026-10-15: Stages 1–3 are BUILT** (2026-10-13,
> `core/quintacle_core/graph.py`): edge files under
> `~/.quintacle/graph/edges/` as truth, the `edges` SQLite table as the
> derived index with startup backfill, typed edges, and
> `neighborhood()`/`reverse_lookup()` via recursive SQL — `/graph` reads the
> table now. The two deterministic MCP↔graph rules below are wired on the
> write side: every MCP write auto-links via `mcp_server/graph_link.py`, and
> undoing a push removes its edges. The graph *view* also got pan /
> wheel-zoom / auto-fit (2026-10-15), so a real-sized graph is actually
> navigable. Stage 4 (a dedicated graph database) remains correctly not
> built — no trigger condition has been hit. As-built reference:
> `reference/graph-engine.md`.

### Stage 1 — materialize edges as a folder, mirrored into SQLite

Today `/graph` (`api.py`) recomputes the entire graph on every request: walk
every note's `links`, fuzzy-match each title, rebuild the whole node/edge
list from scratch. Fine now; won't stay fine once the KB has thousands of
entries, since it's an `O(notes × links)` walk with a fuzzy-match per edge.
There's also nowhere today that holds "here are all the connections" as its
own thing — it's entirely implicit, scattered across each entry's own
`links` field, recomputed on demand.

**The fix is two things working together, each doing a different job:**

1. **A folder of individual edge files — the real data.**
   `~/.quintacle/graph/edges/<timestamp>-<short-id>.md`, one file per edge,
   markdown + frontmatter (`source`, `target`, `kind`, `source_of_edge`,
   `created_at`), no body needed. This is the actual source for the graph,
   following the same pattern as every other piece of data in Quintacle —
   every KB note, every wardrobe item, every grooming item is already its
   own file; an edge being its own file keeps that consistent instead of
   being the one exception living as a line inside some shared growing log.
   It also makes undo trivial: creating an edge is undone by deleting its
   file, the same simple mechanism already used for undoing a new note or
   item — no need to find-and-strip a line out of a combined file, which is
   exactly the complexity the journal-append case already had to solve for.
2. **A SQLite table — a derived, fast-query cache, not a second source of
   truth:**
   ```
   edges(id, source_type, source_id, target_type, target_id, kind, source_of_edge, created_at)
   ```
   Same relationship `log_store.py`'s `rebuild_sqlite_index` already has to
   the markdown activity logs — this is not a new pattern, it's the second
   time this codebase does exactly this. `source_id`/`target_id` reuse the
   exact ID scheme `/graph` already produces (`note:folder/slug`,
   `journal:date`, `experience:folder/slug`) — no new identity system.

**Frontmatter `links` on an entry itself stays how a human or an LLM states a
connection** (nothing about authoring changes); writing one also creates (or
removes) the matching file in `graph/edges/`, and the SQLite table is rebuilt
from that folder incrementally — when an edge file appears or disappears,
update its one row. No background job, no staleness window, and nothing any
write path has to remember as a separate step (see the two rules below).

**What this buys immediately:** `/graph` becomes one indexed query instead of
a full walk — scales into the thousands with no further work. It also
unlocks cheap, deterministic queries nothing else in the app can do yet:
"what links to X" (reverse edges, currently not computable at all without a
full scan) and "everything within N hops" via SQLite's `WITH RECURSIVE` —
still deterministic code deciding what to fetch, per `architecture.md`, not
an open-ended graph query engine wandering on its own. The folder itself is
also the human-readable overview — open it, `grep` it, no tooling required —
the same way the rest of Quintacle's data already works.

### Stage 2 — typed edges

Right now every edge is one of exactly two kinds: `on_day` or a catch-all
`related`. That's the concrete limitation flagged in the New York /
experience-and-person conversation: an edge can't say *how* two things are
connected. With `kind` already a column from Stage 1, this is just
populating it meaningfully — `mentions_person`, `at_location`, `documents`,
`replaces_part`, `has_asset`, `on_day` — assigned by whichever code or LLM
step creates the edge. Additive, no schema change.

**Payoff:** a filterable graph view ("show only the people I've dated," "only
car-maintenance edges"), and MCP read tools that can actually answer "who
have I mentioned at work vs. on dates" instead of returning an undifferentiated
pile of "related" notes.

### Stage 3 — multi-hop queries as a real capability

Once edges are indexed, "everything within 2 hops of the car folder" is a
`WITH RECURSIVE` query or an in-process BFS over the adjacency Stage 1
already built — no new infrastructure. Worth exposing as:
- a backend function / `GET /graph/neighborhood?node=...&hops=2`,
- a graph-view "focus on this node's neighborhood" mode,
- an MCP read tool, once MCP exists.

This is the point where "a brain linked across all these nodes" starts to be
real for retrieval — while staying deterministic traversal code, not an LLM
freely walking the graph on its own.

### Stage 4 — a dedicated graph database (only if actually triggered)

Not a default, and specifically **not Neo4j** unless genuinely forced to it —
Neo4j wants a running server process, which fights the local-first,
no-port, stdio-only story already settled for MCP and for offline use
(`self-hosting.md`, `deployment-and-privacy.md`). If this stage is ever
needed, an **embedded** graph engine (e.g. Kùzu — no server, a library like
SQLite) fits the actual constraints; Neo4j-the-product is the wrong shape for
this project even if "Neo4j" is the mental model that prompted the question.

Concrete trigger conditions, not a timeline:
- SQLite recursive queries become an actual measured bottleneck at a scale
  actually reached (tens of thousands of nodes/edges, deep multi-hop queries
  run often) — not reached today, not close.
- A need for real graph algorithms SQL can't reasonably express — community
  detection, weighted shortest path, "who's my most-connected person" style
  centrality ranking, full Cypher-style pattern matching.

If triggered, it stays a **read replica fed from the same canonical sources**
(frontmatter `links`, Stage 1's SQLite edges) — never the source of truth.
Same independence property MCP already has from the frontend: nothing about
how entries are authored needs to change underneath it.

### This is, honestly, a small bespoke graph system — scoped deliberately (2026-10-13)

Worth naming plainly rather than dancing around it: Stages 1-3 together *are*
a purpose-built graph system — a store for typed nodes and typed
relationships, plus traversal queries over them. Not Neo4j-the-product, but
the same category of thing. Worth being precise about how much smaller a
claim that actually is than it sounds:

**Deliberately not building:** a query language (a handful of specific
functions — neighborhood, reverse-lookup — not a general Cypher-equivalent),
a transaction/concurrency engine (single process, single user, no concurrent
writers to referee), a general graph-algorithm library (no built-in
centrality/community-detection — Stage 4 territory, only if ever actually
needed), ACID guarantees beyond what SQLite and plain files already give for
free. Real graph databases spend most of their engineering on exactly those
problems; skipping them is correct here, not corner-cutting, because the
problem genuinely doesn't need them at this scale with one writer.

**What's actually being built:** a folder of small files following a pattern
already used everywhere else in this codebase, a SQLite table following a
caching pattern already used once already (`log_store.py`), and a few
specific traversal queries. Closer to "a few hundred lines extending an
existing pattern" than "build a database." Also not an unusual choice —
other personal-knowledge tools with a graph view (Obsidian, Roam, Foam) do
exactly this: a bespoke lightweight graph layer over plain files, not an
embedded graph database. Reaching for a real graph engine would be the
*less* common choice at this scale, not the default.

### The two deterministic rules governing MCP ↔ graph interaction (2026-10-13)

Once MCP exists, every read and every write it does should relate to the
graph the same two ways, always — not case-by-case, which is exactly how the
current experience↔person linking gap happened (some write paths set
`links`, one doesn't, because each one decided separately whether to
bother).

**Write rule: every MCP write always attempts to link what it just wrote
into the graph.** Per `mcp-angle.md`'s settled design every write (add, edit,
delete) auto-commits, no approval — so this is one shared step that runs
after any of them, looking at what was just written and proposing edges for
it into `graph/edges/`. Uniform, not duplicated per code path. "Always
attempts" does not mean "always produces an edge" — some entries genuinely
are standalone, and the step shouldn't invent a connection just to have one.
An edit or delete that changes what something links to is itself just
another write the same staged-snapshot-and-undo mechanism already covers —
undoing it restores the edge files too, not only the primary content.

**Read rule: every MCP read that isn't a direct, single-store lookup starts
at the graph to find what's relevant, before fetching the actual content.**
"What's my checking balance," "log this expense" — direct lookups in a
known store, no graph hop needed. "Who have I been seeing," "what do I know
about my car," "what's connected to this lecture" — exploratory or
cross-entity, so the graph is consulted first to resolve *what's relevant*,
then the actual entries get fetched for the model to read or narrate from.
This isn't a new shape for this codebase — `drop_router.py` already does the
equivalent on the write side: try the direct, deterministic match first (a
known prefix), only fall through to something broader (AI classification)
when there isn't one. The read rule is the same two-tier idea, applied to
retrieval instead of classification.

Together these two rules are what actually make "the AI knows where to
look" true, instead of depending on any one tool remembering to check.

### Integration points worth remembering when this gets built

- **MCP undo** (`mcp-angle.md`'s 2026-10-13 update): a write that creates or
  changes edges needs those edges captured in the same staged snapshot as the
  rest of the write, so undoing a push also undoes whatever edges it created
  — not just the primary file or row.
- **AI-managed pages** (`ai-managed-pages.md`): once a drop extracts
  structured fields (e.g. a car entry's `part: "sway bar end links"`), those
  field values are candidate edge targets too, not just the entry's `links`
  list — e.g. linking a `part` value across entries that mention the same
  part. Stretch idea, not required for Stage 1-3 to be worth doing.

### Why this gets the LLM to the same place Neo4j would (2026-10-13)

Worth being precise about, since it's the reason the staged plan above is
enough and a dedicated graph database isn't needed to get "the AI draws
conclusions across my drops/people/finances/experiences":

**The graph answers "what's connected." It doesn't draw the conclusion —
something else does, on top of it.** Whether that engine is Neo4j or our
SQLite edges table, querying it only ever returns "Person X, these 4 linked
expenses, these 2 linked experiences." Turning that into "you spend more on
weeks you see them" takes one more step: either plain code aggregating the
linked numbers (a SQL `SUM ... GROUP BY week`, once the edges exist), or an
LLM reading the retrieved facts and narrating. Neither of those is the graph
itself, and neither cares which database produced the facts it's working
from.

**So the data an LLM sees is engine-agnostic.** A read tool that returns
"Person X's neighborhood: these typed edges, these linked entries" as JSON
looks identical to the model whether a SQLite recursive query or a Cypher
query produced it. Data *shape* — typed nodes, typed edges, N hops of
traversal — is what the model reasons over; the engine underneath is
invisible to it. This is exactly why Stage 1+2 (materialize the edges, type
them) is the thing that actually matters here, not which storage engine
backs them.

**The one real condition: the edges have to actually exist and be correctly
typed first.** No model, and no graph engine, can draw a conclusion from a
connection nobody made — this is the same experience↔person gap already
flagged above, generalized: the plan only pays off once the linking logic
that creates edges is actually built and actually fires.

**For anything arithmetic, compute it in code and hand the model the
finished number** — don't make it add up a list of linked records itself.
Same split `architecture.md` already commits to everywhere else: deterministic
fetch, LLM only narrates at the edge. This is also somewhere our plan is a
better fit than "just point an LLM at Neo4j," since the aggregation belongs
in SQL either way, and ours is already sitting in the same database file the
aggregation needs to run against.

**Where Neo4j would still go further, to keep this honest:** its built-in
graph algorithms (centrality, community detection) can surface a pattern
*nobody asked for* — "this person is unusually central," "these three things
cluster" — automatically, as a property of the engine, not as an answer to a
specific query. That's compute the engine does for free; a crude version
(edge-count per node as a centrality proxy) is cheap to replicate in SQL, but
real community detection or weighted shortest-path isn't a one-line query
either way — it'd be custom code on top of the edges table, same effort it'd
take on top of Neo4j's query results, just without Neo4j's library of
algorithms to lean on.

## Open questions (not decided yet)

- ~~What an edge technically *is*~~ — **settled 2026-10-13**: an entry's own
  `links` frontmatter is how a connection gets stated; a matching file in
  `graph/edges/` is the materialized record of it; a SQLite table is the
  derived fast-query cache of that folder. See the graph engine plan above.
- How a non-text artifact (photo/video/STL) carries graph metadata if it has no
  natural place for frontmatter — a companion sidecar file per artifact?
- How this interacts with the sync mechanic in `deployment-and-privacy.md` — if
  edges live in per-item metadata, do they sync the same line-diff way as content?

## Folder tree + exact typed links (2026-11-13, owner decisions)

Owner rule: the graph must have no gaps for AI navigation, fully automatic —
the owner never creates links or parent nodes by hand. Two changes; nothing
above is rewritten.

**1. Every KB folder is a graph node.** Before this, a folder only showed up
through its optional `about-<folder>.md` charter note (`folder_hub` edges,
2026-11-11), and only notes *directly* in that folder linked to it — no chain
upward, and folders without a charter note were invisible. Now
(`core/quintacle_core/graph_capture.py`, "folder tree" section):

- Node id `folder:<folder slug path>` (e.g. `folder:fun/travel/planned/europe-2027`),
  virtual like `place:` ids — no file. Label = the last segment humanized
  ("Europe 2027"); it is indexed into retrieval as type `folder` (summary =
  breadcrumb "Fun › Travel › Planned › Europe 2027") the first time it appears.
- Edges, provenance `folder_tree`: every note → `part_of` → its own folder;
  every folder → `part_of` → its parent, up to the top-level folder; a
  folder's charter note (the same `_folder_hub_slug` rule) additionally →
  `describes` → its folder. Two trips in `Fun/Travel/Planned/…` and
  `Fun/Travel/Done/…` meet at `folder:fun/travel`.
- Experience files (ExperienceStore reads every note at
  `Fun/Travel/<City>/<Kind>/` as an experience, and `/graph` draws them under
  their `experience:` id) get the membership edge under that id.
- A folder with no note anywhere beneath it (the empty scaffolding dirs stores
  `mkdir` at init) gets no node — nothing in it to navigate to.
- Hooked into every save: `graph_capture.entry_graph_links` for `note:` ids
  (which covers POST /kb/entries, /kb/entries/with-asset, /kb/record-that/save,
  bucket create, project/career hub create, business ideas, work-log import,
  wardrobe/grooming/document/home item saves, MCP `kb_create_entry`), plus
  POST /people, POST /travel/experiences, emergent Places notes, and
  POST /travel/planned/move (re-sync after re-keying, so the moved note loses
  its old folder edge — `folder_tree_links` removes any outgoing
  `folder_tree` edge that no longer matches). The startup
  `run_graph_capture_backfill` walks every note (idempotent).
- `maintenance.py` judges `folder:` ids: stale once `kb/<path>/` is gone.
- Privacy: a folder node is never private (`privacy.is_private_node` only
  judges `note:` ids). Its private member notes are filtered out of cloud
  neighbor labels by the usual `exclude` hook (`privacy.private_filter`).
  The vault lives outside `kb/` and `conversations/` is refused by
  `retrieval.is_excluded`, so neither gets a folder node.
- MCP undo: every folder edge a push created (membership AND any folder →
  parent edge it was first to need) is staged like any other edge, so undo
  stays exact. Known small gap: undoing the push that first filled a folder
  removes that folder's chain edge while later notes still sit in it; the
  next save in that folder or the startup backfill restores it.
- `place_graph._parent_of` now ignores `folder:` targets — `part_of` is shared
  with the place hierarchy, and a Places note is also a member of
  `folder:places`.
- `folder_hub` (note → about note) is kept: knowledge pages and existing
  tests use it, and it is the direct note-to-charter hop. It now re-syncs too,
  so a moved note's stale hub edge goes.

**2. Typed links are exact and instant.** A note's `links:` titles (typed by
the owner) used to resolve with `journal.normalize.canonicalize_name`
(difflib, cutoff 0.8) at write time and in the startup catch-up — so
"Travels" could silently snap to "Travel". Now `graph.resolve_typed_link`
(inside `sync_frontmatter_links`) uses exact, trimmed, case-insensitive title
equality (`graph.typed_link_key`): "travel" = "Travel", "Travels" ≠ "Travel".
`canonicalize_name` itself and its people/meal/routine users are unchanged.
`drop_fixups.existing_links_only` (the filter on AI-*suggested* links in a
drop proposal) uses the same key. Pending links resolve immediately:
`graph_capture.resolve_pending_typed_links` (mirrors `backlink_new_target`)
runs on every note / journal day / experience / person save and links every
existing note or experience whose `links:` already names the new title.
Journal dates and experience names stay valid targets.
