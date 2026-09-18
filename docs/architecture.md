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

## Open questions (not decided yet)

- What the per-domain folder schemas actually look like beyond `schedules/` + `media/`
- Where ingestion pipelines (YOLO, EXIF extraction, etc.) run and how often
- How nodes cross-reference each other concretely (shared date/id keys? explicit
  links stored in each node's records?)
