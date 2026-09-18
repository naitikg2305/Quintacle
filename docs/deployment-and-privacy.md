# Quintacle — Deployment, Sync & Privacy Architecture

## Two clients, one data store

- Phone app
- Computer app

Both read/write the same underlying markdown-based node stores described in
`architecture.md` and the individual node docs.

## Local AI stack (computer only)

- Local VLM (vision-language model)
- Local YOLO (object/person detection — feeds the media-analysis node)
- Local LLM (narration/parsing at the edges, per `architecture.md`)

All self-hosted on the computer. Data never has to leave the machine when running
in local mode — "my data is safe."

## Offline-first editing + LAN sync

- The phone works standalone anywhere. Changes/new info get written to markdown
  files locally on the phone as they happen.
- Sync requires two things to be true **at the same time**: both the phone app
  and the computer app are actively running, AND they're on the same local
  network (WiFi or Ethernet, doesn't matter which). Same network with the
  computer app closed doesn't sync. Phone app open with the computer on a
  different network doesn't sync either. It's a live handshake between two
  running processes, not a passive background file-share.
- No cloud server required for sync itself; it's direct device-to-device over LAN.

## LLM routing: four tiers, phone-local is now real

Revised from the original two-tier (home-local / away-cloud) plan: the phone
itself can run a real local AI stack on its own NPU (see `stack.md`) — it no
longer needs the computer at all for the common cases.

- **Phone-local (default, always available, no network needed).** Object/scene
  detection and face detection run via TFLite/LiteRT + NNAPI on the phone's
  NPU; narration runs via a small on-device LLM (MediaPipe LLM Inference /
  ONNX Runtime + QNN). Fully private, works anywhere, works with the computer
  off. This covers tagging photos and narrating structured facts — the two
  jobs `architecture.md` actually asks an LLM to do.
- **Home, computer reachable.** Same idea as before — if a task exceeds what
  the phone-sized models can do well (bigger local LLM, heavier
  multi-frame/video analysis), route to the computer's local stack instead.
- **Cloud API, opt-in switch** (see privacy gate below) — OpenAI (ChatGPT/GPT-4.1
  vision) or Anthropic (Claude, vision-capable). Because these models take
  images directly, cloud mode collapses the local chain (detector +
  face-embedder + SLM) into a **single vision-capable chat call** that detects,
  describes, and narrates at once — no need to re-host YOLO server-side for
  this path.
- **Away, not opted in, phone-local stack insufficient for the task** — falls
  back to code-only per the privacy gate below (unchanged from the original
  design).

The phone picks among these via an explicit switch in settings, not just
silent network detection — "run locally," "use ChatGPT," "use Claude" are all
choices the user makes directly, though phone-local stays the default.

### Identity matching is always local, regardless of the switch

Carried over unchanged from the existing `FaceDetect` prototype's own design:
a cloud provider may be used to *detect* that a face is present in a photo,
but matching that face against enrolled profiles always happens on-device
against the local embedding store (SQLite) — enrolled-person embeddings never
get sent to OpenAI or Anthropic, no matter which switch position is active.

## Privacy gate: explicit opt-in required before anything leaves the device

- A switch in the app explicitly grants permission to send data to a chosen
  external API (OpenAI or Anthropic), off by default.
- If that switch is **off** (the default/safe state), the phone runs its local
  stack (phone-local tier above) or, if a task exceeds it, falls back to
  **"code only"** — no external LLM calls at all. The deterministic/code layer
  from `architecture.md` keeps working (capture, structured fetch, quota
  tracking, etc.); it just doesn't get cloud AI narration/parsing until the
  switch is turned on.
- Fail-closed by design: the safe default never leaks data. Cloud AI is opt-in,
  never opt-out.

## Why this fits the existing architecture

`architecture.md` already established that the LLM only matters at the *edges*
(parsing messy input in, narrating structured output out) while the middle stays
deterministic code. This doc is about *where* that edge-step actually executes,
and now also *which provider* handles it:

```
default, anywhere                 -> phone-local NPU stack (detector + face-embedder + SLM)
home, task exceeds phone models   -> computer's local stack
opted in via switch               -> cloud vision LLM (OpenAI or Anthropic) — single call
not opted in, phone stack short   -> no LLM at all — code-only
```

Either way, results land as structured facts in the same metadata store —
downstream queries stay deterministic lookups regardless of which tier
produced the tags.

## Sync mechanic: line-level diff, not whole-file overwrite

Sync (auto when both apps are live on the same network, or triggered manually via
a sync button) works by diffing a shared file — e.g. `md1` existing on both phone
and computer. If the computer sees the phone's copy has 10 new lines it doesn't
have, it pulls just those 10 lines. Not a full-file replace, not last-write-wins.

This works cleanly for **append-only** files (a day's journal entry, a ledger log
— content only ever gets added to the bottom). It's not obviously sufficient for a
file that gets **edited in place** (e.g. rewriting/reordering a line in
`schemes.md`, not just appending to it) — line-addition detection alone won't
catch a changed existing line.

## Open questions (not decided yet)

- Are all node files append-only logs, or do some (schemes, outfits catalog, etc.)
  get edited in place and need real merge/conflict handling beyond
  new-line-detection?
- What "code-only" mode actually looks like on the phone in the moment — does it
  queue captured input for local processing once back home, or run on
  simpler non-AI logic immediately?
- Conflict resolution if the *same* line is changed differently on both devices
  before they next sync
- Which specific local VLM/YOLO/LLM models to run — not decided yet
- Phone <-> computer pairing/discovery mechanism on the local network
