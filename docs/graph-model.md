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

## Open questions (not decided yet)

- What an edge technically *is* — a reference field in each item's own metadata
  (e.g. frontmatter), or a separate graph-index the code maintains and queries?
- How a non-text artifact (photo/video/STL) carries graph metadata if it has no
  natural place for frontmatter — a companion sidecar file per artifact?
- How this interacts with the sync mechanic in `deployment-and-privacy.md` — if
  edges live in per-item metadata, do they sync the same line-diff way as content?
