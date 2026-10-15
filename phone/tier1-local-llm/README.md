# Tier 1 — local LLM on the phone (Termux + Ollama)

Everything that works on-device the day the Termux backend runs: the KB
chat's `local:` models served by an Ollama daemon on the phone itself, plus
the env wiring and boot persistence around it. This is "runtime 1" from
`docs/local-llm-phone-plan.md` — CPU-only, zero core-code changes, the
prove-the-pipeline tier. Charter and verified-vs-pending status for the whole
`phone/` folder: `../README.md`.

## What Tier 1 delivers

- **Local chat, day one.** The chat picker's `local:` entries
  (`local:qwen2.5:1.5b`, `local:qwen3:4b`, … — curated in
  `core/quintacle_core/nodes/kb/chat.py`, and any other pulled model works
  as free-form `local:<name>`) run against the on-phone daemon. No API key,
  no network, no tokens billed.
- **Local parse — effective once the ingest dispatch merges.**
  *(Update, later 2026-10-15: it merged — `core/quintacle_core/llm_dispatch.py`
  is in this tree, so the two ingest knobs below are live, not forward
  wiring. See `docs/reference/local-models.md`.)* The env
  profile pre-sets `QUINTACLE_LOCAL_PARSE_MODEL` and
  `QUINTACLE_INGEST_PROVIDER`; the core code reading them is landing from a
  parallel workstream, so until that merges these are inert forward wiring
  (nothing breaks, nothing changes).
- **Auto-journal, graph edges, who-is-this tag flow — day one, model-free.**
  These are deterministic core features (no LLM in the loop), so they work
  on the phone as soon as the backend runs, with or without Ollama.
- **Vision keeps working, locally later.** `QUINTACLE_VISION=auto` means
  photo drops try the local VLM and fall back to the cloud caption with a
  log line (`nodes/kb/drop.py`). Local vision on-device is Tier 3's job;
  nothing here blocks on it.

## Playbook — exact order, on the phone

Prerequisites are the existing Termux bootstrap; don't skip them.

1. **Backend bootstrap (existing):** get the repo onto the phone and run
   `bash scripts/termux/setup.sh`, then `cp core/.env.example core/.env`
   (keys in), then migrate data — all per `docs/termux-backend-setup.md`.
   Confirm `bash scripts/termux/start-backend.sh --once` serves on
   `127.0.0.1:8000` before adding this tier.
2. **Install Ollama + pull the model:**
   `bash phone/tier1-local-llm/install-ollama-termux.sh`
   Does, in order: disk-space check (models are ~1–3 GB; wants 4 GiB free),
   `pkg install ollama`, starts `ollama serve` under `termux-wake-lock` with
   a restart-on-crash loop (detached, log in `~/.quintacle-logs/ollama.log`),
   pulls `qwen2.5:1.5b` (~1 GB). Model options:
   - default `qwen2.5:1.5b` — the quality/speed sweet spot the desktop week
     of testing uses (`docs/local-llm-phone-plan.md`);
   - `--model llama3.2:1b` — smallest/fastest, weakest quality;
   - `--model qwen3:4b` — the step-up when 1.5B fails a task; ~2.5 GB,
     comfortable on the S25U's 12 GB RAM (`docs/on-device-s25u.md`), skip on
     low-RAM phones. `--model` is repeatable to pull several.
3. **(Re)start the backend:** `bash scripts/termux/start-backend.sh`.
   It auto-sources `phone/tier1-local-llm/quintacle-phone-env.sh` when the
   file exists — that sets `QUINTACLE_OLLAMA_HOST=http://127.0.0.1:11434`,
   `QUINTACLE_VISION=auto`, and the two forward-wired ingest knobs. Pick
   `local:qwen2.5:1.5b` in the chat; it should answer with no cloud call.
4. **Boot persistence (both daemons):** the existing
   `bash scripts/termux/install-boot-autostart.sh` handles uvicorn; add the
   Ollama half with the `boot-ollama` snippet in this folder:

   ```sh
   mkdir -p ~/.termux/boot
   sed "s|__QUINTACLE_REPO_ROOT__|$PWD|" phone/tier1-local-llm/boot-ollama \
     > ~/.termux/boot/start-quintacle-ollama
   chmod +x ~/.termux/boot/start-quintacle-ollama
   ```

   (run from the repo root, so `$PWD` is the checkout path). The manual
   one-time steps — installing the Termux:Boot app, opening it once,
   exempting Termux from battery optimization — are exactly the ones
   `docs/termux-backend-setup.md` §4 already walks through; they cover both
   boot files at once. Reboot once and check `~/.quintacle-logs/boot.log`,
   `backend.log` and `ollama.log`: both uvicorn and ollama should be up.

## What to expect: speed (cited estimates, NOT measured on this device)

From `docs/on-device-s25u.md` (research 2026-10-07) and
`docs/local-llm-phone-plan.md`; Termux+Ollama is the CPU-only path, so use
the CPU-band numbers:

| Model | Size (Q4-class) | Expected decode on S25U-class silicon |
|---|---|---|
| qwen2.5:1.5b (default) | ~1 GB | ~20–50 tok/s band (Gemma-2B-class CPU decode measured 46.9 tok/s on the one-gen-newer S26U via the LiteRT-LM card; the plan doc pegs 1.5B Q4 at 20–50 on CPU) |
| llama3.2:1b | ~0.8 GB | ~54 tok/s was measured on *NPU* (AI Hub card) — CPU will be lower; fastest of the three regardless |
| qwen3:4b | ~2.5 GB | ~25–30 tok/s band (Llama-3.2-3B measured 26.5 on NPU; CPU somewhat lower) |

Rule of thumb from the plan doc: a 200-token answer at 40 tok/s is ~5 s —
comfortably interactive for narration-length replies. First reply after idle
is slower: Ollama cold-loads ~1–3 GB of weights before the first token
(the chat's client allows 300 s for exactly this reason). Replace this table
with real numbers once measured on the device, per `docs/on-device-s25u.md`'s
own instruction.

**Quality honesty** (`docs/local-llm-phone-plan.md`): 1–2B is good enough for
narration over retrieved facts (the chat's job), NOT for unsupervised
permanent writes — stored-prose jobs stay cloud/approval-gated until a bigger
local model proves out.

## Battery & thermals — what a resident ollama costs

- **The wake lock is the main bill.** `--serve` holds `termux-wake-lock`
  (same as the backend's start script): the CPU never deep-sleeps while
  either daemon is meant to be reachable. That's a deliberate trade the
  Termux backend already makes — Tier 1 adds a second holder of the same
  lock, not a new kind of drain. Release both with `termux-wake-unlock`
  when you want the phone to actually sleep (both daemons stop being
  reachable until restarted).
- **Idle ollama is cheap; loaded ollama costs RAM.** The daemon idles at
  near-zero CPU. After a chat it keeps the model in RAM for ~5 minutes
  (Ollama's default keep-alive) then unloads — `ollama ps` shows what's
  resident right now. A loaded 1.5B is ~1–1.5 GB of the 12 GB.
- **Bursts are negligible, sustained decode heats.** One narration-length
  answer is seconds of CPU; long back-and-forth sessions on CPU will warm
  the phone and throttle (`docs/on-device-s25u.md`'s battery section). The
  doc's pattern holds here: interactive jobs on the small model, batch jobs
  overnight on charge. The GPU/NPU battery fix is Tier 2/3's territory.

## Troubleshooting

- **Chat says "Ollama isn't reachable at http://127.0.0.1:11434 (…) — start
  it with `ollama serve`…"** — that readable 400 is the chat's own error
  path (`chat.py` `_run_local` → `OllamaError` → HTTP 400 in
  `nodes/kb/api.py`) and it names the fix: the daemon is down. Restart it
  with `bash phone/tier1-local-llm/install-ollama-termux.sh --serve` (or
  reboot, if boot persistence is installed) and check
  `~/.quintacle-logs/ollama.log`.
- **Chat says "Ollama doesn't have \"X\" … pull it with `ollama pull X`"** —
  also the chat's own 400; do exactly that (or re-run the install script
  with `--model X`).
- **`pkg install ollama` fails** — `pkg update -y` first, then
  `pkg search ollama`; the package is in the Termux main repo (confirmed
  2026-10-15) but Termux packages do move between repos/names over time.
- **Pull dies mid-download** — re-run the install script; `ollama pull`
  resumes partial downloads.
- **Everything stops when the screen's been off a while** — the wake lock
  isn't being honored: re-check the battery-optimization exemptions in
  `docs/termux-backend-setup.md` §4, and that the Termux:API app (not just
  the `termux-api` package) is installed.
- **Quick health checks:** `curl http://127.0.0.1:11434/api/version`
  (daemon up?), `ollama list` (on disk), `ollama ps` (in RAM),
  `~/.quintacle-logs/ollama.log` (crash loop?).

## Files in this folder

| File | What it is |
|---|---|
| `install-ollama-termux.sh` | Install + model pull + the `--serve` wake-locked restart loop |
| `quintacle-phone-env.sh` | Env profile; auto-sourced by `scripts/termux/start-backend.sh` if present |
| `boot-ollama` | Termux:Boot snippet (copy to `~/.termux/boot/`, placeholder filled) |
