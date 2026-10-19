# Retrieval — the universal triple-hybrid index

Derived from code at the retrieval wave (2026-10-19). Source:
[core/quintacle_core/retrieval.py](../../core/quintacle_core/retrieval.py),
[core/quintacle_core/retrieval_backfill.py](../../core/quintacle_core/retrieval_backfill.py).
Decision log: `docs/next-wave-plan.md` §3 (decided 2026-10-19).

One ranked search surface over EVERY node type in the store — notes, journal
days, people, places, experiences, todos, every SQLite log row, meal/
ingredient/routine presets, event nodes — exposed as `GET /retrieve` and the
read-only MCP tool `search_index`. This is the foundation the conversational
wave (§4) rebuilds chat on; chat itself is untouched in this wave.

## Schema (two tables + one optional, all in `quintacle.db`)

```sql
CREATE TABLE nodes_index (
    id TEXT PRIMARY KEY,      -- EXACTLY graph.py's id scheme, never a parallel one
    type TEXT NOT NULL,       -- note|place|person|journal_day|todo|experience|expense|
                              -- food|exercise|activity|substance|body_stat|meal|
                              -- ingredient|routine|event
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',   -- the one-liner per node
    updated_at TEXT NOT NULL            -- Eastern Time (clock.now)
);
CREATE VIRTUAL TABLE nodes_fts USING fts5(id UNINDEXED, title, summary, body);
-- optional, created lazily on the first successful embedding (dim = model's):
CREATE VIRTUAL TABLE nodes_vec USING vec0(id TEXT PRIMARY KEY,
                                          embedding float[N] distance_metric=cosine);
```

Id notes: a person has NO `person:` prefix — their id is their profile note's
id (`note:people/<slug>/profile`) with `type = "person"`, exactly how
`/graph` labels that node (see graph.py's module docstring). Emergent
`Places/` notes index as `type = "place"` under their `note:places/<slug>` id.

## Summaries — deterministic core, models at the edges

- **Structured rows** (`log_row_title_and_summary` + the `safe_index_*`
  builders): computed IN CODE from the real SQLite row / model fields, e.g.
  `Chipotle — $14.50 — food — 2026-10-12`. Any arithmetic (kcal × servings)
  is done in SQL. Never a model call.
- **Prose nodes** (KB notes, journal days — `prose_summary`): ONE local-model
  line via `llm_dispatch.parse_structured(provider="local")` — provider is
  pinned to local; a summary never bills a silent cloud call. ANY failure
  falls back to `deterministic_prose_summary` (first non-empty content line,
  headings/`[asset]`/marker comments skipped, ~120 chars), so a write is
  never blocked on a model. `QUINTACLE_SUMMARY_PROVIDER=off` forces the
  deterministic path — `tests/conftest.py` sets it for the whole suite.

## retrieve(query, k, types) — the flow (no model anywhere in this path)

1. **FTS5 lane**: query tokens double-quoted and OR-joined (operators
   neutralized), `bm25(nodes_fts, 0, 5, 2, 1)` — title weighted over summary
   over body. Pool = max(5k, 25).
2. **Vector lane** (when up): query embedded via the local Ollama
   `/api/embed`, `nodes_vec` KNN by cosine distance.
3. **Fusion**: reciprocal-rank fusion in code — `score = Σ 1/(60 + rank)`
   per lane, deterministic id tiebreak (`rrf_merge`).
4. **Type filter + hydrate** from `nodes_index` (a lane row with no index row
   is stale and skipped).
5. **Graph expansion**: per hit, `graph.neighborhood(id, 1)` → up to 10
   `{id, title, edge_type}` labels; neighbor titles resolve from the index,
   else the id's rest.

Result shape: `{id, type, title, summary, score, neighbors: [...]}`.

## Write-path hooks (failure-isolated, never fail the user's write)

`safe_index_*` helpers — no-ops when retrieval was never initialized in the
process; any exception is logged and swallowed (same contract as
`graph_capture.safe_entry_graph_links`):

| Write path | Hook |
|---|---|
| REST `POST /kb/entries`, `/kb/entries/with-asset`; MCP `kb_create_entry` | `safe_index_note` |
| REST `POST /journal/{date}`; MCP `journal_append` | `safe_index_journal` (whole day re-indexed) |
| REST `/logs/{expenses,food,substances,activities,exercise,body-stats}`; MCP `log_expense` | `safe_index_log_row` |
| REST `/logs/meals`, `/logs/meals/from-ingredients`, `/logs/ingredients` | `safe_index_log_row` (`meal:`/`ingredient:`) |
| REST `/logs/routines` | `safe_index_routine` |
| REST `/schedule/todos` create/update/delete; MCP `todo_create/update/delete` | `safe_index_todo` / `safe_remove_node` |
| REST `POST /people` | `safe_index_person` |
| REST `POST /travel/experiences` | `safe_index_experience` |
| `graph_capture.link_event` (both doors: REST `/graph/event`, MCP `link_event`) | `safe_index_event` |
| `graph_capture._emerge_places` (emergent place notes) | `safe_index_note` (type `place`) |

Known gaps (deliberate, repairable by the backfill): MCP `undo_write`
doesn't un-index; item-shaped stores (wardrobe/grooming/home/documents) and
the photo auto-journal's marker appends aren't hooked — the idempotent
backfill picks all of these up.

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `QUINTACLE_EMBED_MODEL` | `embeddinggemma` | Ollama embedding model for the vector lane |
| `QUINTACLE_SUMMARY_PROVIDER` | `local` | `local` = try the local model for prose one-liners (deterministic fallback on any failure); `off` = deterministic only |
| `QUINTACLE_OLLAMA_HOST` / `OLLAMA_HOST` | `http://127.0.0.1:11434` | same host resolution as the `local:` chat provider |

`sqlite-vec` lives in `core/requirements-retrieval.txt` (lazy import);
`core/requirements.txt` stays phone/Termux-safe.

## Degradation ladder

1. **Everything installed, Ollama up**: FTS5 + vectors + graph, prose
   summaries written by the local model.
2. **sqlite-vec installed, Ollama down**: first embedding failure logs once
   and flips the vector lane off for the process (no per-write retry storm);
   FTS5 + graph serve; prose summaries use the deterministic fallback.
3. **No sqlite-vec** (phone/Termux, the bare test venv): the lazy import
   fails quietly; FTS5 + graph serve. The FULL test suite passes in this
   state — verified in both states 2 and 3.
4. **No graph store initialized** (bare unit tests): `neighbors` degrades to
   `[]`; FTS5 alone serves.

## Exclusions (hard rules)

- **The Vault is structurally invisible**: it lives OUTSIDE `kb/`, so no
  walker here can reach it, AND `is_excluded()` refuses any vault-prefixed
  id at the single `index_node` chokepoint (`organisation/document-vault`,
  a real KB folder, is NOT matched).
- **`conversations/` excluded by prefix** — the transcript archive the next
  wave builds (next-wave-plan §4) must never enter the default index. The
  backfill also skips the folder; `index_node` enforces it again.
- Log/preset markdown mirrors under `*/logs/`, `Nutrition/presets|ingredients/`,
  `Fitness/routines/` are skipped by the backfill — those rows index under
  their canonical SQLite ids (reference, never duplicate).

## Backfill

```
QUINTACLE_DATA_DIR=... python -m quintacle_core.retrieval_backfill
```

Idempotent upsert over the whole store; prints per-type counts. Never run it
against the real `~/.quintacle` while experimenting — sandbox with
`QUINTACLE_DATA_DIR`.

## Exposure

- `GET /retrieve?q=...&k=10&types=note,person` → `{query, results: [...]}`
  ([core/quintacle_core/api.py](../../core/quintacle_core/api.py)).
- MCP `search_index(query, k, types)` — read-only, deterministic, no ledger
  entry (tool count now 18;
  [core/quintacle_core/mcp_server/server.py](../../core/quintacle_core/mcp_server/server.py)).
