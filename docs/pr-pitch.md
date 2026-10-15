# Quintacle — the pitch

Status: **PR/marketing material, drafted 2026-10-15.** The founder's thesis in
his own words, the one-line engineering truth behind it, and the receipts.
Tone target: honest — every claim below is demonstrated in this repo, not
aspirational. (Deep technical backing: `docs/reference/`, starting with
`00-statement-of-work.md`.)

## The one-liner

**Quintacle's accuracy lives in its registries, not in its models.**

Build the database of your life first. Then even small, free, local models
look brilliant — because they're not guessing, they're *retrieving*.

## The founder's thesis (his words, lightly cleaned)

> Isn't it smart engineering — almost creating a database for your life
> first, and using weak models to just help you with what you already know?
> Strong models to research, of course. But once research is done you don't
> need to repeat it — just store it and get it. Because what people do is
> search the same thing over and over again, and it's unnecessary once
> you've done your search once. Use your storage to just retrieve it.

That's the whole product. Everyone else scales intelligence per query;
Quintacle **amortizes intelligence at capture time** — into typed entries, a
knowledge graph, face enrollments, presets — so that answering becomes
retrieval, and retrieval is nearly free.

## The pillars (all built, all demonstrable)

- **Privacy-first.** Face recognition runs entirely on your own hardware —
  embeddings never leave one directory on your disk, never ride in any API
  call. Secrets live in a passphrase-encrypted vault that is *structurally
  invisible* to every AI surface: no model, local or cloud, can even see
  that it exists. Matching a face to a name happens on-device, always.
- **Local-first.** Photo tagging (YOLO), face identity, scene attributes,
  journal parsing, drop classification, chat, photo description — all run
  on local models by default, on the computer today and the phone next
  (the models are already converted and parity-proven for the phone's NPU).
  The cloud is a button you choose to press, never a default: a "redo with
  cloud" that re-runs from your original input, an "escalate" that carries a
  chat to a big model when you want one.
- **Environment-first, in a way.** The happy path makes zero datacenter
  calls. A day's worth of capture — photos tagged, faces matched, journal
  lines written, graph edges wired — costs no tokens and no cloud energy,
  because the work is done once by tiny models and deterministic code, then
  stored. The expensive model runs only when you deliberately buy deep
  research — and its *output gets stored too*, so you never pay for the
  same thinking twice.
- **Deterministic where it matters.** Whether "pull day" names your workout
  preset, whether a photo belongs to Tuesday, whether an edge connects to a
  real entity — string matching, EXIF, and indexed queries, not model
  vibes. Models get a vote; they never get the pen. Nothing writes without
  either your review or a one-click undo.

## Receipts (from this repo, this week, on real data)

- Enrolled a face **once**; a different day's photo matched at **0.803** —
  on-device, no API.
- A dropped photo auto-wrote `📷 5:09 PM — with Naitik · person (photo:
  Beard day one)` into the right day's journal — zero LLM calls, undoable.
- "did pull day at the gym" → the full preset (deadlift, weighted pull-ups,
  chin-ups, rows, curls) split out by **deterministic code**, parsed by a
  **local** model, token cost **$0**.
- Local photo description in **0.79 s** on the owner's GPU, with exact OCR
  of in-image text.
- Two devices synced over plain wifi — journals merged, an encrypted secret
  unlocked on the peer — no cloud in the loop.

## Why this is the contrarian-but-correct bet

The industry's answer to "the model forgot / hallucinated / costs too much"
is a bigger model and a bigger bill, every single query, forever. Quintacle's
answer is a **memory that compounds**: every capture makes every future
question cheaper, because the hard thinking happened once and became
structure. Weak models + strong structure beats strong models + no
structure — for the questions that make up a life, which are mostly
questions you've already answered.

Honest edges (we keep these in the pitch because credibility is the brand):
the system is only as smart as what you feed it — registries must be seeded,
and capture is a habit; big models still genuinely win at *novel* research
(that's what the escalate button is for); and the phone deployment, while
code-complete and parity-proven, hasn't touched a real device yet.

## The architecture, in the founder's own formulation

> "Graph powered, code powered, ML based, self-learning on your data —
> with an edge of LLM at the end that connects everything."

Five layers, four of them running today:

1. **Graph powered** — the connective substrate. Typed, materialized,
   provenance-tracked edges; events binding cross-type siblings (one dinner
   = journal text + expense + food + place + person, all one node-walk
   apart); people, places and days as addressable nodes.
2. **Code powered** — the deterministic spine. Prefix routing, whole-word
   matching, preset expansion, EXIF dating, arithmetic in SQL. House law:
   *models get a vote, never the pen.* Nothing structural depends on any
   model's judgment.
3. **ML based** — the small-model layer. Object detection, face embeddings,
   scene heuristics, 1-8B local language models for the easy tasks —
   megabytes, milliseconds, zero cloud, already converted and parity-proven
   for a phone NPU.
4. **Self-learning on your data** — and here is the deliberate twist: the
   system learns by **accumulating structure, not by changing weights**.
   Tag a face once → recognized forever (few-shot learning in embedding
   space). Create a preset → every future mention becomes deterministic.
   Approve a person → past and future text lights up with connections. The
   learned state is the registries and the graph — which makes the learning
   *inspectable, undoable, syncable, and immune to catastrophic forgetting*.
   No fine-tuning run offers those properties.
5. **An edge of LLM that connects everything** — narration and proposal at
   the boundary only: it reads what the graph hands it, suggests what the
   user ratifies, and the expensive model is a button, not a dependency.

The roadmap's cleanest next step is already generating its own data: every
"redo with cloud" press and every chat escalation is a labeled correction —
the system can learn *which tasks to trust locally* from usage alone, by
counting, not training.

In a sentence: a **neuro-symbolic personal system** — symbolic structure
holding the truth, neural components at the sensory and language
boundaries — betting against the industry's bigger-model-every-query
default, and winning on the home turf where it matters: the questions that
make up a life, which are finite, repetitive, and already answered by your
own past.

## Tagline candidates

- *Your life, indexed. Your models, local. Your cloud bill, optional.*
- *Search once. Store forever. Retrieve for free.*
- *A database for your life — and models small enough to trust with it.*
- *The expensive thinking happens once. Everything after is memory.*
