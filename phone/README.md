# phone/ — Quintacle's on-device stack

This folder is everything that makes Quintacle run *on the phone itself* —
scripts, env profiles, boot snippets and playbooks layered on top of the
existing Termux backend bootstrap (`scripts/termux/`, documented in
`docs/termux-backend-setup.md`). The target device is the owner's Galaxy S25
Ultra (12 GB RAM — hardware facts and measured numbers in
`docs/on-device-s25u.md`); nothing here is S25U-*only*, but model-size
recommendations assume that class of phone.

Design rule for the whole folder: **zero changes to `core/quintacle_core/`.**
The core already exposes every knob these tiers need (env vars, the `local:`
chat provider, the `QUINTACLE_VISION` dispatch); `phone/` only installs
runtimes, sets env vars, and documents the device-side steps.

## The three tiers

Each tier gets its own subfolder with its own README and owner; they build on
each other but land independently.

1. **`tier1-local-llm/` — local LLM chat (Termux + Ollama, CPU).**
   "Runtime 1" from `docs/local-llm-phone-plan.md`: `pkg install ollama`, a
   1–2B model, and the chat's existing `local:` provider pointed at
   localhost. Zero code, works the day the Termux backend runs. This is the
   tier maintained in this folder level — see `tier1-local-llm/README.md`
   for the ordered playbook.
2. **`tier2-*` — faster local inference.** The speed/battery step beyond
   CPU-only Ollama ("runtime 2" in the plan doc: llama.cpp-class runtimes
   using the Adreno GPU, OpenAI-compatible serving). Owned and documented
   separately in its own subfolder.
3. **`tier3-*` — local vision / perception on-device.** Moves the
   `QUINTACLE_VISION=local` path (VLM captioning via `local_vlm/`, plus the
   perception core) onto the phone. Owned and documented separately in its
   own subfolder. Until it lands, Tier 1 ships `QUINTACLE_VISION=auto`, so
   photo drops fall back to the cloud caption gracefully.

## Verified vs. device-pending — read this before trusting anything here

**No real Android device has been touched by the machine that wrote Tier 1.**
What that means concretely for `tier1-local-llm/`:

Verified on desktop Linux (2026-10-15):

- All scripts pass `bash -n`; the env profile sources cleanly and exports
  the documented values.
- The exact `ollama serve` / `ollama pull` / `ollama list` / `ollama ps`
  invocations match a real ollama CLI (tested against ollama 0.34.2).
- The three model tags (`qwen2.5:1.5b`, `llama3.2:1b`, `qwen3:4b`) exist in
  the Ollama registry (manifest HTTP 200s).
- An `ollama` package exists in the Termux **main** repo package pool
  (0.40.3, aarch64 — checked at packages.termux.dev), so
  `pkg install ollama` is a real command, as `docs/local-llm-phone-plan.md`
  also states.

Device-pending (unconfirmed until someone runs this on the phone):

- That `pkg install ollama` succeeds end-to-end on *this* phone's Termux and
  the binary runs on its Android build.
- Actual tok/s, battery drain, and thermal behavior — every number quoted in
  the tier READMEs is a cited estimate from `docs/on-device-s25u.md`, not a
  measurement from this device.
- The full Termux:Boot chain (boot snippets firing, wake locks holding
  through Android's battery management).

When a step gets confirmed on the device, update the relevant tier README —
same convention as `docs/on-device-s25u.md`'s "replace the caveats with real
numbers" rule.
