# Local LLM on the phone — how the `local:` provider gets there

Status: **plan, 2026-10-15.** The desktop half is built: the KB chat now has a
`local` provider (`nodes/kb/chat.py` → `_run_local`) that speaks the Ollama
daemon's HTTP API (`/api/chat`, non-streaming) with the same free-form
convention as Bedrock — `local:<any-ollama-model>`. This doc is about moving
that same provider to the S25 Ultra. Hardware facts and tok/s numbers below
come from `on-device-s25u.md` (research, 2026-10-07).

## The key design fact: the provider is just a base URL

`_run_local` talks to whatever answers at `ollama_host()` —
`QUINTACLE_OLLAMA_HOST` / `OLLAMA_HOST`, default `http://127.0.0.1:11434`.
Nothing in it is desktop-specific. On the phone, the backend already runs in
Termux (`termux-backend-setup.md`, `android-apk-migration.md`); anything that
serves an Ollama-compatible `/api/chat` on localhost makes the whole `local:`
tier work unchanged.

## Three runtimes, ranked

1. **Termux + Ollama (first; zero code).** Ollama is in the Termux package
   repo (`pkg install ollama`) and runs the identical API we already target.
   CPU-only — no Hexagon NPU, usually no GPU — so it's the slowest path, but
   a 1–2B model on the S25U's Oryon cores is still interactive (Gemma-2B-class
   CPU decode measured at ~47 tok/s on this silicon tier per the LiteRT-LM
   card in `on-device-s25u.md`; expect 1.5B Q4 in the 20–50 tok/s band).
   Proves the pipeline end-to-end tonight: `OLLAMA_HOST` stays localhost,
   `local:qwen2.5:1.5b` just works.

2. **Termux + llama.cpp `llama-server` (second; small adapter or none).**
   Builds with the Adreno OpenCL backend (GPU, verified on 8 Elite) — a real
   speed/battery step over CPU. `llama-server` speaks the OpenAI-compatible
   API, not Ollama's; either point a thin `_run_local` variant at
   `/v1/chat/completions` (chat.py already has an OpenAI-shaped path to crib
   from) or keep Ollama as the front and only swap when GPU matters. NPU from
   Termux is **not realistic** (needs Hexagon SDK libs an unprivileged shell
   doesn't get).

3. **LiteRT-LM / GenieX in a Kotlin plugin (end state; real APK work).** The
   NPU path from `on-device-s25u.md`: GenieX (llama.cpp or QAIRT inside) or
   LiteRT-LM (Gemma 4 E2B at ~52 tok/s decode, <1 GB RAM, GPU). Not an HTTP
   daemon — the Capacitor plugin exposes `narrate/extract/embed` calls and the
   frontend (or a localhost shim) routes to it. This is where battery and
   sustained use get solved; do it only after 1–2 prove the quality.

## 1–2B model candidates

| Model | Size (Q4) | Expected decode on S25U-class | Notes |
|---|---|---|---|
| **Qwen2.5 1.5B** | ~1 GB | ~40–54 tok/s CPU/NPU band (Llama-3.2-1B measured ~54 on NPU) | The one now curated in the chat picker (`local:qwen2.5:1.5b`) — prove quality on desktop first, same weights on phone |
| Llama 3.2 1B | ~0.8 GB | ~54 tok/s (NPU, AI Hub card) | Fastest; weakest quality of the three |
| Gemma 4 E2B | 676 MB RAM (LiteRT) | ~52 tok/s GPU / ~47 CPU (measured, LiteRT card) | Best measured numbers, but LiteRT path only (runtime 3) |
| Qwen3 4B | ~2.5 GB | ~25–30 tok/s band (3B measured 26.5 NPU) | The step-up if 1.5B fails a task; still fine on 12 GB |

All comfortably interactive for narration-length outputs (a 200-token answer
at 40 tok/s is ~5 s).

## The honest read on 1–2B quality

Today's live desktop test (qwen2.5:1.5b, KB-grounded sleep question through
the real `/kb/chat` endpoint) landed exactly where expected: it correctly
picked up every fact from the retrieved note (bedtime 23:30, 6h40m average,
groggy under 7h) and produced coherent, sensible prose around them — with
mildly generic advice and one slightly muddled clause. That is:

- **Good enough: narration over retrieved facts.** day_recall-style flows
  hand the model the facts; it only has to compose them readably. Reads,
  summaries of composed data, scratch-chat answers — the deterministic layer
  did the hard part, the 1–2B model is a renderer. This is the phone tier.
- **NOT good enough: unsupervised permanent writes.** A 1–2B model inventing
  or muddling a detail that then gets *stored* (journal parses, KB entries,
  finance extraction) is exactly the failure mode the approval-before-write
  contract exists for. Those either stay on the cloud API, keep a human
  approval step, or wait for the UC2 test (`on-device-s25u.md`) to prove a
  bigger local model. Same split the session decided: **deterministic/local
  for reads + composed facts, cloud API for prose that gets stored.**

## Next concrete steps

1. Desktop: use `local:qwen2.5:1.5b` in the chat for a week; note where it
   falls over vs `local:qwen3:8b`.
2. Phone: `pkg install ollama` in Termux, pull the same 1.5B, point the
   Termux backend at it — zero code change, real tok/s numbers for this doc.
3. Only then decide whether runtime 2 (OpenCL) or 3 (NPU/LiteRT) is worth the
   build cost.
