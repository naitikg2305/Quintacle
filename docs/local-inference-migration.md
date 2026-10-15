# Local YOLO + Local LLM migration (S25 Ultra)

Status: **idea, not started.** No code written. To be tried on a **separate
git branch**, never merged into `main` until proven working end-to-end —
today's cloud-API build (Claude Haiku 4.5 for everything, via `llm_config.py`)
stays the working, deployed version throughout.

> *Status update, later 2026-10-15 (code at `1a46c92`): the "Decided
> 2026-10-15" section at the bottom is now **BUILT** — and NOT on a separate
> branch as this header planned. The auto-fallback dispatch
> (`core/quintacle_core/llm_dispatch.py`: local Ollama first, cloud on any
> local failure, `provider_used` surfaced, review-gated redo-with-cloud)
> made the separate-branch safety net unnecessary: the cloud path stays one
> env var / one click away, so it ships on the main dev branch
> (`redone-UI`). The vision slice (`QUINTACLE_VISION` + `local_vlm/`, now
> with an llamacpp backend) and the fully-local perception lane landed in
> the same wave. Still cloud on purpose: vision+schema sites and geocoding.
> As-built detail: `reference/local-models.md`. The desktop-hardware
> analysis above remains accurate history.*

## Why

Every AI call in Quintacle today (`nodes/*/llm.py` across journal, kb, logs,
wardrobe, grooming, documents, drop_router) goes to the Claude API. That's
correct for now — it's what's actually built and tested — but it's also the
real recurring cost driver as usage grows (flagged directly: "holy its
expensive"). The phone-local tier of the architecture already planned in
`deployment-and-privacy.md` (four-tier LLM routing) is the answer, and the
device to build/test it on already exists: a **Samsung Galaxy S25 Ultra**.

## What doesn't change

- **Deterministic-first stays deterministic-first.** `parse_prefix()`,
  `canonicalize_name()`, `compute_photo_folder()`'s date math, EXIF
  extraction — none of this involves a model, local or cloud, and none of it
  changes.
- **The markdown-is-source-of-truth architecture stays exactly as-is.** Local
  inference only changes *which model* answers an AI call, not where data
  lives or how it's stored.
- **The KB chat is explicitly out of scope for this migration** (per the
  standing "don't mess with the chat" instruction) — whatever changes here
  should not touch `nodes/kb/chat.py`'s behavior first.
- **Approval-before-write stays.** A local model's proposal gets reviewed and
  pushed exactly like a cloud model's does today — this migration is about
  *which model answers*, not the write-safety contract around it.

## What would actually change

Per `stack.md`'s existing call: real on-device NPU inference needs a native
runtime, not just `pip install`-able Python — `sentence-transformers` +
`torch` have no real Android wheels and wouldn't hit the Hexagon NPU even if
they ran. The real options, already scoped in `stack.md`:

- **ONNX Runtime + QNN execution provider** (Qualcomm's official NPU backend), or
- **Google AI Edge / MediaPipe LLM Inference** (first-class Android support).

Local YOLO (or a modern equivalent — see open question below) would run via
TFLite/LiteRT + NNAPI on the S25 Ultra's NPU, per
`deployment-and-privacy.md`'s phone-local tier. Python still orchestrates —
this is another edge-call per `architecture.md`'s "LLM only at the edges"
principle, invoked via subprocess/JNI, same shape as every other AI call in
this app today, just pointed at a local runtime instead of `anthropic.Anthropic()`.

Concretely, the functions that would need a local-model code path (in
addition to, not instead of, their existing Claude-based implementation):

- `nodes/journal/llm.py` — `parse_journal_dump()` (the single biggest, most
  complex schema in the app — see the `SkipJsonSchema` / grammar-size fix
  from this session; a local model's structured-output support may have
  *different* limits, not necessarily the same ones)
- `nodes/kb/llm.py` — `suggest_kb_entry()`, `suggest_kb_batch()`, link suggestion
- `nodes/kb/drop.py` — vision captioning (image → description) — this is the
  literal YOLO/VLM use case
- `nodes/logs/nutrition_llm.py`, `nodes/logs/meal_composer.py` — nutrition
  estimation, both text and vision
- `nodes/wardrobe/llm.py`, `nodes/grooming/llm.py` — item captioning + composition
- `nodes/documents/llm.py` — document structuring
- `nodes/drop_router.py` — `classify_image_type()`, receipt extraction,
  geocoding (`nodes/kb/photo_organizer.py`'s `geocode()`)

## Branch strategy

- New branch off `main`, e.g. `local-inference`.
- `llm_config.py` already centralizes model selection (`DEFAULT_MODEL`,
  `RESEARCH_MODEL`) — the natural seam for a third mode. A local-inference
  branch likely adds a `LOCAL_MODE` switch there rather than touching every
  call site's model string individually, matching the existing pattern.
- Test against real data on the S25 Ultra itself, not just a dev machine —
  the whole point is proving the on-device NPU path actually works, not just
  that the code compiles.
- Only merges to `main` once a local call site is proven at least as
  reliable as its cloud equivalent on real usage — no partial swap that
  silently degrades accuracy.

## Open questions (from `deployment-and-privacy.md`, still unresolved)

- **Which specific local VLM/YOLO/LLM models to run — not decided yet.**
  This is the one real gap between "hardware confirmed" and "buildable."
- Conflict resolution if the same line changes differently on two devices
  before they next sync (phone/computer sync, separate from this migration
  but adjacent).
- Phone <-> computer pairing/discovery mechanism on the local network.

## Next step, when this is picked back up

Pick ONE call site to prove the pattern on first — `classify_image_type()`
is the smallest, cheapest schema in the app (a single `Literal` field) and is
the most literally YOLO-shaped task, making it the natural first target
rather than starting with `parse_journal_dump()`'s much larger schema.


## Decided 2026-10-15 — local-first ingest with cloud override, push-gated

The owner's routing rule for the easy sorting tasks (Drop classification,
journal-dump parsing, and similar `DEFAULT_MODEL` ingest seams):

1. **Local first.** Once the `local:` Ollama provider lands, these seams run
   on a local small model by default — they're easy tasks, and the existing
   propose→review→Save flow catches any local mistake at zero cost.
2. **Cloud override goes a step back, not forward.** If a local proposal is
   unsatisfying, the review card offers "redo with cloud API" — re-running
   the classification from the ORIGINAL input (the raw dropped text/photo),
   never re-prompting over the local model's output.
3. **Nothing commits until the user says push.** The override loop lives
   entirely inside the existing review step; Save stays the only write.

Build prerequisites (in flight as of this note): the `local:` provider, the
narration-edge inventory of which call sites are local-routable, and a
provider-aware dispatch for the ingest `anthropic.Anthropic()` call sites.
Implementation wave follows immediately after those land.
