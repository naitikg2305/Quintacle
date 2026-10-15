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

## Tagline candidates

- *Your life, indexed. Your models, local. Your cloud bill, optional.*
- *Search once. Store forever. Retrieve for free.*
- *A database for your life — and models small enough to trust with it.*
- *The expensive thinking happens once. Everything after is memory.*
