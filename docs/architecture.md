# Quintacle — Core Architecture Idea

## The problem with the obvious approach

A chat model doing RAG over one big mono folder of journal/notes/media **gets lost**
as it grows — semantic search over an undifferentiated blob degrades.

## The fix: structure replaces search

If the data store is **super structured** (folders/schema known in advance), you
barely need AI to find things. Code can walk straight to the right place
deterministically. AI only enters at the very end, to turn already-correct facts
into natural language.

This is the "deterministic agent" idea from `intro.md`, made concrete:

```
query
  -> deterministic code navigates known folder structure, fetches exact data
  -> (no AI needed for this step)
  -> assembled facts handed to an LLM (even a small/local one is enough)
  -> LLM's only job: phrase it like a human, not find it
```

## Worked example: "What was I doing on March 13?"

Structure:

```
schedules/
  2026-03-13/
    journal.md          # the day's entry
media/
  2026-03-13/
    *.jpg / *.mp4        # that day's important photos/videos
```

Pipeline (runs at capture/ingest time, ahead of any query):

1. Run YOLO (or similar) over that day's photos/videos -> who/what is in frame
2. Pull photo/video metadata -> GPS/location, timestamp, device, other EXIF artifacts
3. Write all of that into `journal.md` for that day, so the journal entry ends up
   enriched with structured facts, not just raw media sitting next to it

At query time:

1. Code resolves "March 13" -> `schedules/2026-03-13/journal.md` (already enriched)
2. Facts get handed to an LLM
3. LLM answers in plain language: where he was, who was around, roughly what he
   was doing — based on real detected/extracted facts, not a guess

## Why this matters

- Retrieval accuracy doesn't depend on embeddings/RAG quality — it depends on the
  folder structure being right, which is something Naitik controls completely.
- The LLM's job shrinks to narration. That means a small/cheap/local model can
  handle the final step; the expensive-feeling "AI does everything" approach isn't
  needed for correctness.
- This generalizes past the March-13 example to every domain in `intro.md`
  (schedule, finance, dressing, apartment, car, social/dating journal) as long as
  each domain gets its own well-defined structure instead of dumping into one blob.

## Correction: nodes are separate, not merged

The March-13 media-analysis pipeline (YOLO + metadata extraction) is its **own
node/function** — not the same thing as the journal. Earlier phrasing in this doc
implied the media pipeline writes directly into `journal.md`; that's wrong. They're
separate components that can cross-reference each other (by date/id) but each owns
its own store and logic.

Quintacle is shaping up as a set of independent **nodes**, each internally following
the same deterministic-fetch / LLM-only-at-the-edges pattern, rather than one merged
store. Nodes identified so far:

- **Journal** — nightly voice/text check-in (`habits-and-checkin.md`)
- **Media-analysis** — YOLO/metadata pipeline over photos/videos (this doc's original example)
- **Habits/quotas** — golf, guitar, workout, running, drinking/smoking/vaping (`habits-and-checkin.md`)
- **Ledger** — purchases, monthly credit card statements (`ledger.md`)
- **Schemes** — business/life plans, base plan / side hustle / business ideas (`schemes.md`)
- **Outfits** — clothing/accessories planning (`outfits.md`)
- **Diet** — meal/macro/grocery planning (`diet.md`)
- **Apartment** — home organization (`apartment.md`)
- **Car** — car organization/maintenance (`car.md`)
- **Routines** — recurring cadence-triggered checklists whose items are actions in
  *other* nodes, e.g. the Sunday Reset (`routines.md`) — this is the clearest
  concrete example of nodes being interconnected rather than isolated
- **Vault** — secure document storage: license, passport, visas, OPT, lease docs
  (`vault.md`) — the one node where security is a first-class constraint, not an
  afterthought, unlike every lifestyle-data node above
- **Schedule/Todo** — calendar populated from prioritized todo items, plus
  due-date-driven self-generation (`schedule.md`) — the deferred "scheduling"
  domain from `intro.md`

Each node gets its own folder/schema. A query that spans nodes (e.g. "what was I
doing on March 13" pulling both journal and media-analysis for that date) is still
handled by deterministic code that knows how to reach into each relevant node by
date/id — not by merging the nodes' stores together.

## Amendment 2026-09-30: "structure replaces search" was too absolute

The original claim above — retrieval accuracy doesn't depend on embeddings,
only on folder structure — holds for **typed, dated data** (logs, nutrition,
finance, body stats, todos). Those are SQL queries and must never go near a
vector index.

It does **not** hold for **prose recall** across the KB and journal once
they're large. Today: 44 KB files, 416KB; `kb/api.py`'s `/search` is a
case-insensitive substring scan that re-reads every file per query, and
`kb/chat.py`'s `_kb_context()` concatenates the *entire* KB into the prompt
on every message. Both are fine at 44. Both are dead at thousands, which is
where this is headed:

- Context stuffing: thousands of notes × 1–2KB = millions of characters. No
  window holds it; paying for the whole KB per message is absurd anyway.
  Chat grounding has to become retrieval.
- Substring search: misses synonyms ("shoulder pinch" vs. a note that says
  "rotator cuff"). The more captured over years, the more the user's own
  vocabulary drifts. That's the abyss problem reappearing at the read side —
  captured but not retrievable.

The doc's warning that RAG over an undifferentiated blob gets lost is still
true. The cause is the *undifferentiated* part, which the node/folder
structure already solves. Semantic search **inside** a known folder or type
is a different thing from RAG over one's whole life.

### Decision: hybrid search inside the existing SQLite, not a vector DB

**Not** a separate vector service (Pinecone/Chroma/Weaviate). Thousands of
entries is tiny by vector standards; brute-force cosine over ~5k × 768-dim
vectors in `sqlite-vec` is a few ms. No ANN index needed until ~100k chunks,
a lifetime away for personal notes. Everything stays in `quintacle.db`: one
process, offline, backed up with everything else.

Design, to build **before the KB crosses a few hundred entries** — don't wait
for the usability tests to prove the need; use them to shape the tool:

- **Hybrid from day one.** SQLite FTS5 (exact/phrase, stemming, ranking) +
  `sqlite-vec` (semantic), merged with reciprocal rank fusion. Each covers
  the other's blind spots; building both is barely more work than one.
- **Embed at ingest.** The drop pipeline is already the single write path —
  embed there, once, when a note lands. Edits re-embed. No batch job, no
  stale index.
- **Chunk, don't embed whole notes.** A 10-line writeup is 3–4 chunks, each
  pointing back to `(folder, slug, line range)`. Retrieval returns the
  passage with a citation, not the file.
- **Scope by structure.** Every chunk carries its folder and type. Searches
  can be scoped to one folder, KB-only, or journal prose. This is where the
  thesis and vectors reconcile: structure narrows candidates, embeddings rank
  them.
- **Typed data stays out.** Only prose enters the index.
- **Local embedding model** (nomic-embed-text, bge-small class) on CPU.
  Milliseconds per chunk, data never leaves the box. Cloud embeddings would
  ship every note off-box just to index it — no, per
  `deployment-and-privacy.md`.

### Constraints this creates

- **Android can't embed.** `stack.md` already notes sentence-transformers has
  no real Android wheels under Chaquopy. So either the phone calls a cloud
  embedding API (privacy no) or embedding runs on the always-on home box and
  the phone only queries. Another argument for the home server in
  `self-hosting.md` — it becomes the indexer as well as the host.
- **The chat's `_kb_context()` must change** from concatenate-all to
  retrieve-top-k. Standing instruction is not to mess with the chat; this is
  the one change it will eventually need, and it's a grounding change, not a
  UI/behavior change.

### Relationship to MCP

The `search` tool becomes the most important tool in the MCP set
(`mcp-angle.md`). "What do I know about shoulder warmups" → five ranked
passages with citations in one call, instead of walking the folder tree
with `list_folders` → `list_entries` → `read_entry`. Exactly "code fetches,
model narrates" — just with a better fetch.

## Open questions (not decided yet)

- What the per-domain folder schemas actually look like beyond `schedules/` + `media/`
- Where ingestion pipelines (YOLO, EXIF extraction, etc.) run and how often
- How nodes cross-reference each other concretely (shared date/id keys? explicit
  links stored in each node's records?)

## Amendment 2026-10-15 — Quintacle is local-first, on computer AND phone

Decided explicitly by Naitik, mid-build of the perception/local-model wave.
This sits alongside (not replacing) the core principle above: deterministic
code still fetches and decides; this amendment is about WHICH model runs at
the edges when a model is needed at all.

1. **Easy tasks run on local models, both devices.** Perception (YOLO tags,
   face matching, scene basics) is local by construction — those aren't even
   LLM tasks. The easy LLM tasks — Drop classification, journal-dump
   parsing, prose polish of auto-composed lines — default to a local small
   model (Ollama-class on the computer; 1-2B on the phone's NPU once that
   stack lands). These were never Opus/Sonnet tasks — the swap is
   Haiku→local, and the review step catches local mistakes for free.
2. **Cloud is an escalation the user chooses, never a default.**
   - *Ingest:* a proposal the user dislikes gets "redo with cloud" — which
     re-runs from the ORIGINAL input (a step back), never re-prompts over
     the local output. Nothing commits until the user pushes (the existing
     review→Save gate).
   - *Chat:* the chat runs local by default; if an answer isn't good enough,
     the user escalates that conversation to a real API model BY CHOICE —
     the chat context transfers into the cloud call so nothing is retyped.
3. **Cloud keeps two jobs on the happy path:** research-grade questions the
   user explicitly routes there, and (for now) structured parsing where
   schema fidelity matters more than tokens — shrinking as local models
   prove seams during the testing period.
4. **Why this is cheap here:** capture-time work (perception + deterministic
   journal lines + graph edges) means answers are mostly retrieval; a small
   local model narrating retrieved facts is easy mode. The token meter runs
   only when the user deliberately reaches for a big model.

Where the pieces live: `docs/local-inference-migration.md` (the decided
routing rule + build status), `docs/reference/` (as-built internals),
`docs/seamless-mode.md` (how auto-mode later leans on seams local models
have proven). The full as-built inventory — which is now genuinely too big
to hold in one head — is `docs/reference/00-statement-of-work.md`.

> *Status note, later 2026-10-15 (code at `1a46c92`): points 1–2 above are
> now BUILT and live on the desktop. Perception (YOLO tags, face matching,
> scene basics) runs locally with no LLM at all
> (`core/quintacle_core/perception/`); the easy ingest seams default to a
> local model with cloud auto-fallback
> (`QUINTACLE_INGEST_PROVIDER=auto`, `llm_dispatch.py`) and every parse
> response carries `provider_used` so the review card can offer the
> step-back "Redo with cloud ↻"; the KB chat defaults to `local:qwen3:8b`
> with a per-reply "Escalate ↗" that transfers the conversation to a cloud
> model by choice. Verified live: real journal parses answering with
> `provider_used: local`. Full as-built detail and the env-knob table:
> `reference/local-models.md`. Point 3 stands as written (vision+schema and
> research-grade work stay cloud); the phone halves are scripted in
> `phone/` and still device-pending.*
