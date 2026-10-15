# Local models — the three lanes, as built

Derived from code at commit `1a46c92` on 2026-10-15.

The 2026-10-15 local-first decision (`docs/architecture.md` amendment,
routing rule in `docs/local-inference-migration.md` "Decided 2026-10-15")
is now code in three distinct lanes. They share one Ollama daemon on this
machine but are separately switched, separately defaulted, and fail
independently:

| Lane | Entry point | Default | Switch |
|---|---|---|---|
| Chat | `local:<model>` picker values, `nodes/kb/chat.py` | UI defaults to `local:qwen3:8b`; backend has no default (picker-driven) | the model picker itself |
| Ingest (structured parse) | `llm_dispatch.parse_structured`, `core/quintacle_core/llm_dispatch.py` | **`auto` — local first, cloud fallback** | `QUINTACLE_INGEST_PROVIDER` / per-request `?provider=` |
| Vision (photo descriptions) | `local_vlm.describe_images_local`, `core/quintacle_core/local_vlm/` | **`cloud`** | `QUINTACLE_VISION` + `QUINTACLE_VISION_BACKEND` |

(Perception — YOLO/faces/scene — is a fourth local thing but not a *model
lane* with a cloud twin; it is local by construction. See
[perception-and-autojournal.md](perception-and-autojournal.md).)

## Lane 1 — chat provider (`nodes/kb/chat.py`)

`local:<any ollama model>` is a chat provider alongside anthropic / openai /
bedrock: three curated entries (`local:qwen2.5:1.5b`, `local:qwen3:4b`,
`local:qwen3:8b`, all "free") plus free-form `local:<name>` for anything the
daemon has. `_run_local` speaks Ollama's non-streaming `/api/chat` with
stdlib urllib (no new deps), `num_ctx` 8192 (the KB-grounding block alone
overflows Ollama's 4k default), strips inline `<think>` defensively, and
converts failures into a readable `OllamaError` → HTTP 400 that names the
fix ("start it with `ollama serve`" / "pull it with `ollama pull X`").
Vision-named models (llava/vl/vision/…, `_OLLAMA_VISION_HINTS`) get real
base64 `images`; text-only models get an "[image omitted]" placeholder,
never raw base64. Daemon address: `ollama_host()` — `QUINTACLE_OLLAMA_HOST`,
then standard `OLLAMA_HOST`, then `http://127.0.0.1:11434`.

**Local default + choose-to-escalate (frontend):** the KB chat defaults to
`local:qwen3:8b` (`DEFAULT_LOCAL_MODEL`, `frontend/app/kb/page.tsx`), and
every local-answered reply carries an "Escalate ↗" chooser
(`frontend/components/ChatLog.tsx`) that re-sends the same conversation to
a cloud model and appends the labeled answer — context transfers, nothing
is retyped, and escalation is always the user's explicit choice.

## Lane 2 — ingest dispatch (`core/quintacle_core/llm_dispatch.py`)

`parse_structured(system, user_content, output_format, *, provider,
max_tokens)` is the single routed replacement for the ingest seams'
`anthropic.Anthropic().messages.parse` calls:

- **local** — Ollama `/api/chat` with `format: <pydantic JSON schema>`
  (schema-constrained generation) on `QUINTACLE_LOCAL_PARSE_MODEL`
  (default **`qwen3:8b`** — parsing needs more model than chat narration;
  1.5B mangles multi-entry schemas), `num_ctx` 16384 (parse payloads carry
  meal/routine libraries and the notes index), `think: false`, output still
  validated through the real Pydantic model. Daemon down / model missing →
  `OllamaError`; model answered but output fails validation →
  `LocalParseError` (a subclass, still a *local* failure).
- **cloud** — exactly the pre-existing metered structured-parse call on
  `DEFAULT_MODEL`.
- **auto** (the default) — try local; ANY local failure falls back to cloud
  with one warning log. Ingest never crashes because the local model
  fumbled.

Per-call `provider` (from an endpoint's `?provider=`) beats the
`QUINTACLE_INGEST_PROVIDER` env default. A per-request ContextVar collector
(`collect_providers`/`summarize_providers`) gives each endpoint ONE answer
for "who sorted this": `"local"`, `"cloud"`, `"mixed"` (auto fell back
mid-request), or `null` (fully deterministic handling).

### Routed sites (text-only parse seams, the complete list)

- `nodes/journal/llm.py` — `parse_journal_dump`, `_resolve_entry_dates`,
  `_resolve_finance_kinds`
- `nodes/kb/llm.py` — `suggest_kb_entry`, `suggest_kb_entry_for_folder`,
  `suggest_kb_placement`, `suggest_kb_batch`, `suggest_kb_update`
- `nodes/drop_router.py` — `classify_text_file_type`
- `nodes/people/llm.py` — `structure_person`, `maybe_structure_person_mention`
- `nodes/travel/llm.py` — `_call_experience_model` (behind
  `structure_experience` / `maybe_structure_experience`)
- `nodes/finance/llm.py` — `structure_credit_card`, `structure_investment`
- `nodes/home/llm.py` — `structure_home_item`, `structure_residence`

**Deliberately NOT routed (stays cloud, documented in the module
docstring):** vision+schema sites (`classify_image_type`, receipt
extraction, the `describe_*` estimators) until the local vision+schema path
is proven — plain local vision descriptions are lane 3's job; and
geocoding, a world-knowledge task that is a poor fit for a small local
model (named exception).

### Endpoints + UI

`POST /drop`, `POST /kb/sort`, `POST /journal/{date}/parse` all accept
`?provider=local|cloud|auto` and return `provider_used`
(`core/quintacle_core/api.py`, `nodes/kb/api.py`, `nodes/journal/api.py`).
The Drop and Journal pages show a provider badge and a **"Redo with cloud
↻"** button (`frontend/app/kb/drop/page.tsx`,
`frontend/app/journal/page.tsx`) that re-sends a snapshot of the ORIGINAL
input with `provider=cloud` — a step back, never re-prompting over local
output, per the decided routing rule. Nothing commits until the user
pushes; the review gate catches local mistakes at zero cost.

### Seam-audit findings so far (live local-vs-cloud comparisons, 2026-10-15)

- qwen3:8b is at **parity with cloud on todos, date resolution, and
  meal-preset matching**.
- It is **weak on dual-meaning clauses** — a sentence that is both food and
  money ("$14.50 lunch at …") tends to drop the finance entry; a 14B caught
  the expense but still misread "gym pull day" as activity. Exactly the
  failure class the review gate + "Redo with cloud" exists for.
- It was weak on **routine expansion** ("pull day" → the preset's
  exercises) — now moot: that match is string matching, not judgment, and
  moved into deterministic code (below).
- Resource note: qwen3:8b at 16k ctx spills ~29% to CPU on the 12 GB card.

### Deterministic routine expansion (the provider-proofing fix)

`nodes/journal/normalize.py` `expand_routine_mentions(...)` runs after
EVERY journal parse, both providers: a known routine mentioned by name
(`graph.title_mentioned` semantics) expands into one empty-set exercise
entry per preset exercise, never duplicating what the model already
produced (no-op when cloud obeyed the prompt). The caller
(`nodes/journal/llm.py` `parse_journal_dump`) then drops the model's
redundant header entry named after the routine itself — but only when its
sets carry no real performance data — and carries a lone
`calories_burned` estimate from that header onto the first expanded entry
so energy balance survives. Whether "pull day" names a known preset is no
longer a model behavior at all.

## Lane 3 — local vision (`core/quintacle_core/local_vlm/`)

`QUINTACLE_VISION=cloud|local|auto` (default `cloud`, read per call in
`nodes/kb/drop.py` `describe_images`) dispatches every photo-description
call — drop-time descriptions, `POST /kb/asset/describe`, the MCP
`describe_photo` tool — between the metered Anthropic call and
`describe_images_local()`. `local` raises rather than silently billing the
cloud (the strict-privacy mode); `auto` falls back to cloud with a warning
log. Two servers can sit behind the local path, selected by
`QUINTACLE_VISION_BACKEND`:

- **`ollama`** (default) — `local_vlm/ollama.py`, Ollama `/api/chat`,
  default model `qwen2.5vl:3b` (`QUINTACLE_VISION_MODEL`), URL
  `QUINTACLE_OLLAMA_URL` (default `http://localhost:11434`). The desktop
  daemon path.
- **`llamacpp`** — `local_vlm/llamacpp.py`, llama.cpp `llama-server`'s
  OpenAI-compatible `/v1/chat/completions` with data-URL image parts, URL
  `QUINTACLE_LLAMACPP_URL` (default `http://127.0.0.1:8080`; the server
  hosts one GGUF + `--mmproj`, so the URL *is* the model address). The only
  backend that also runs on the phone (Termux — Ollama doesn't exist on
  Android); desktop-proven end-to-end per
  [phone/tier3-vlm/README.md](../../phone/tier3-vlm/README.md) (real
  llama-server + Qwen2.5-VL-3B through `/kb/asset/describe`: CUDA 7.6 s,
  CPU 3m41s — prefill dominates).

Both clients return `None` for any unavailability (fast 2 s connect
timeout, generous 300 s read for cold weight loads), which the
`QUINTACLE_VISION` dispatch turns into fallback (`auto`) or a readable
error (`local`).

## Every QUINTACLE_* local-model knob in one table

| Variable | Values (default first) | Lane / read by |
|---|---|---|
| `QUINTACLE_INGEST_PROVIDER` | `auto` \| `local` \| `cloud` | ingest — `llm_dispatch.py` |
| `QUINTACLE_LOCAL_PARSE_MODEL` | `qwen3:8b` | ingest — local parse model |
| `QUINTACLE_OLLAMA_HOST` | unset → `OLLAMA_HOST` → `http://127.0.0.1:11434` | chat + ingest daemon (`chat.ollama_host()`) |
| `QUINTACLE_VISION` | `cloud` \| `local` \| `auto` | vision — `nodes/kb/drop.py` |
| `QUINTACLE_VISION_BACKEND` | `ollama` \| `llamacpp` | vision — `local_vlm/__init__.py` |
| `QUINTACLE_VISION_MODEL` | `qwen2.5vl:3b` (ollama); advisory for llamacpp | vision — both backends |
| `QUINTACLE_OLLAMA_URL` | `http://localhost:11434` | vision ollama backend only (NOTE: a separate knob from `QUINTACLE_OLLAMA_HOST` — the vision client predates it) |
| `QUINTACLE_LLAMACPP_URL` | `http://127.0.0.1:8080` | vision llamacpp backend |
| `QUINTACLE_PERCEPTION_BACKEND` | `onnx` \| `tflite` | perception runtime (see perception doc) |
| `QUINTACLE_TFLITE_VARIANT` | `float32` \| `dynamic_range_quant` | perception/tflite |
| `QUINTACLE_TFLITE_DELEGATE` | unset \| name/.so | perception/tflite (desktop no-op) |
| `QUINTACLE_PERCEPTION_MODELS_DIR` | `<data dir>/perception/models` | perception weights dir |
| `QUINTACLE_FACE_MATCH_THRESHOLD` | `0.8` | auto-journal assertion floor |
| `QUINTACLE_AUTOJOURNAL_POLISH` | unset \| `1` (billed) | auto-journal optional polish |

(Cloud-side context, unchanged: `QUINTACLE_LLM_MODEL`,
`QUINTACLE_LLM_RESEARCH_MODEL`, `QUINTACLE_BEDROCK_REGION`,
`QUINTACLE_DATA_DIR` — see [architecture.md](architecture.md).)

## Phone tiers

The on-device halves of these lanes live in [phone/](../../phone/) — Tier 1
(Termux + Ollama for lanes 1–2, device-pending), Tier 2 (TFLite perception,
desktop-parity-proven), Tier 3 (llama.cpp VLM for lane 3, client
desktop-proven) — each with its own README; this doc does not duplicate
them.

## Tests

`core/tests/test_llm_dispatch.py` (18), `core/tests/test_chat_models.py`
(local provider), `core/tests/test_local_vlm.py` (both backends). Suite at
this commit: 335 passed / 5 skipped with perception deps (verified in a
fresh venv).
