# Chat context — index→select→fetch over the retrieval engine

Code-derived 2026-10-19 from `core/quintacle_core/nodes/kb/chat.py`
(`_system_text`, `_kb_context`, `_topic_context`), `core/quintacle_core/nodes/kb/api.py`
(the `/kb/chat` + `/kb/record-that*` endpoints) and `frontend/app/kb/page.tsx`.
Restamp if regenerated. Decision log: `docs/next-wave-plan.md` §3 (decision 2,
opened by the owner 2026-10-19) and §4.

The KB chat no longer dumps every note into the prompt. Context is assembled
deterministically per turn by `_system_text(store, use_kb, folder, slug,
messages)` — the same assembly for every provider, so escalating to a cloud
model transfers the identical context.

## The three scopes

| Scope | Context |
|---|---|
| none (the main chat page) | retrieval hits for the latest question |
| `folder` + `slug` (chat continued ON a note) | topic hydration block, then retrieval hits (topic excluded) |
| `folder` only (the per-folder chat) | **unchanged** — exactly that folder's entries, no global retrieval (its contract: an answer can't come from somewhere it can't cite) |

`use_kb=false` → no KB block at all, same as before.

## The retrieval path (`_kb_context`)

1. **Query** = the newest user turn's typed text (`_last_user_text`; text
   blocks only — attachment placeholders never pollute the FTS query).
2. **Select**: `RetrievalIndex.retrieve(query, k=8)` — FTS5 + optional
   vectors, RRF-fused, graph-expanded (`docs/reference/retrieval.md`). Order
   is retrieve()'s own: score desc, id tiebreak. No model call anywhere.
3. **Fetch** per hit (`_hit_section`):
   - **Prose hits** (`note`/`place`/`person`/`journal_day`) get their FULL
     current content — notes via `KBStore.read` (+ freeform `fields`, title
     heading stripped since the section header already carries it), journal
     days via the journal store — capped at **4,000 chars** each.
   - **Structured hits** (expense/food/exercise/meal/routine/todo/event/…)
     enter as their already-computed one-line summary from `nodes_index`,
     as-is — finished numbers from SQLite; the system text explicitly tells
     the model to never recalculate them.
   - Each section ends with the hit's 1-hop neighbor labels:
     `Connected: <title> (<edge_type>, id: <id>); …`. The chat loop is
     single-shot (no tool turns), so the model is instructed to ASK the user
     to bring a neighbor up rather than pretending it can fetch it.
4. **Budget**: sections accumulate under a **24,000-char** total cap; a hit
   whose full body would blow the budget degrades to its summary-line form
   (order never reshuffles — deterministic given the same store state).
5. Zero hits on a populated index → a literal "nothing in the knowledge base
   matched this question" line (the model says so instead of guessing).

## Topic hydration (`_topic_context`)

`## Current topic: <title> [note:<folder>/<slug>]` + the note's fields +
full body (capped at **8,000** chars) + its `Connected:` neighborhood line
(`retrieval.neighbor_labels()` — degrades to nothing). Retrieval hits for
the latest question follow under `## Retrieved for the latest question`,
with the topic's own id excluded. **No transcript is ever loaded
automatically** — transcripts are second-tier by decision (§4).

The frontend's existing "continue in chat" affordance now sends the note's
folder+slug on `/kb/chat` (`slug` is the new request field); `Escalate ↗`
re-sends the same scope.

## Degradation ladder (never a 500)

1. Retrieval up → the path above.
2. Retrieval singleton uninitialized, index EMPTY (never backfilled), or any
   retrieval error → caught in `_system_text`:
   - unscoped chat → `_kb_context_everything` — the ORIGINAL dump-everything
     context, kept verbatim as the fallback;
   - note-scoped chat → the topic block still hydrates (plain store reads),
     with the folder's entries standing in for retrieval.
3. Folder-only chat never touches retrieval in the first place.

An empty-but-initialized index deliberately falls back to the dump rather
than answering "nothing matched" — a fresh process over an old store that
was never backfilled must not look like an empty KB.

## Transcripts: the explicit lane

A `FileSearch` button on the chat input row calls `GET /transcripts/search`
with the typed text and appends the hits (topic, date, snippet) to the log
as a deterministic assistant-side message (`model: "transcripts"`, zero
model calls) — so they're in context for the next turn. That button is the
ONLY way transcript content reaches a chat; the archive stays excluded from
the retrieval index (`is_excluded`) and from every default surface.

## "Record that" — explicit consolidation, gated

Propose→review→Save, same contract as `/kb/sort` + `/kb/entries`:

1. **Propose** — `POST /kb/record-that {messages, folder?, slug?, provider?}`
   (the chat-header button). Distills the conversation into bullet points
   via `llm.suggest_record_fold` (scoped: points only) or
   `suggest_record_fold_new` (unscoped: also proposes folder + title against
   the real folder list / notes index) — `llm_dispatch.parse_structured`,
   so the normal local-first routing and the `provider` step-back apply. The
   date header is computed IN CODE (`clock.today()`, Eastern):
   `### <date> — from chat`. **Writes nothing.** 400 on readable model
   failures, 404 when the scoped note is gone, 400 on an empty conversation.
2. **Review** — the proposal opens in a panel on the scratchpad side:
   folder, note title, and the dated entry are all editable (folder/title
   prefilled from the scoped topic, or model-proposed when unscoped — the
   user picks/confirms there).
3. **Save** — `POST /kb/record-that/save {folder, title, append}` (the
   "Append to note" button). Reads the existing note (title is slugified,
   same as `write`), carries its body through **verbatim in code**, and
   appends the dated block — history is never rewritten, per the
   docs-are-decision-logs principle. No matching note → a new one is created
   from the dated entry. The write runs the existing machinery:
   `KBStore.write` (frontmatter links/fields preserved),
   `_sync_note_graph_links`, `safe_index_note`.

## Tests

`core/tests/test_chat_context.py` — preset-seeded sandbox (meals, routine,
person, experience, notes, expense row per CLAUDE.md's seeding rule), all
provider runners stubbed: selection vs dump, finished summary lines,
neighbor labels, every fallback rung, topic hydration, folder-scope
invariance, transcripts staying out of default context, escalation context
equality, and the full record-that flow (propose writes nothing; save
appends without rewriting; new-note creation; 400/404 edges).
