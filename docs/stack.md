# Quintacle — Client/Runtime Stack Decision

Resolves the open question in `deployment-and-privacy.md` about what the phone and
computer apps actually *are*. Targets: Windows, Linux, Android (no iOS).

## The split: logic vs. rendering

`PersonalWebsite` (the reference project) is actually two stacks glued together:
Next.js/React frontend (`STLViewer.tsx` via `@react-three/fiber`, `react-markdown`
for content) talking to a Python/FastAPI backend (`backend-chatbot/app.py`).
"Everything on Python" means the **logic/data/AI layer** — matching the
backend-chatbot pattern — not the interactive rendering, which stays web tech
because nothing renders 3D/markdown as well in pure Python.

## Shared core (Python — one codebase, all platforms)

A FastAPI app per the `backend-chatbot/app.py` shape, implementing each node
(scheduler first). Owns all local storage — markdown, photos, docs, SQLite —
read/written directly, matching the local-first design in
`deployment-and-privacy.md`.

Runs everywhere as a local server on `localhost`:
- Windows/Linux: normal Python process.
- Android: embedded via **Chaquopy** (real CPython inside the APK — not a
  rewrite, not a subset).

## Shared UI (one codebase, all platforms)

The existing Next.js components (`STLViewer.tsx`, the `react-markdown` reading
views) get reused/ported in, served by the local FastAPI process. Each platform
is just a window/webview pointed at `localhost`:
- Windows/Linux: **pywebview** (pure Python — no Rust/Tauri toolchain, keeps
  desktop 100% Python outside the web layer itself).
- Android: a thin Kotlin `WebView` Activity (~100 lines, write-once) pointed at
  the Chaquopy-hosted local server. This is the one unavoidable non-Python
  sliver — Android requires a Kotlin/Java host process to embed Chaquopy at all.

## SLM / NPU inference (S25 Ultra) — explicitly NOT "everything Python"

`sentence-transformers` + `torch` (what `backend-chatbot` uses today) have no
real Android wheels and, even if they ran, wouldn't touch the Hexagon NPU.
Real on-device NPU inference needs a native runtime:
- **ONNX Runtime + QNN execution provider** (Qualcomm's official NPU backend), or
- **Google AI Edge / MediaPipe LLM Inference** (has first-class Android support).

> 2026-10-07: researched properly in `on-device-s25u.md` — measured
> numbers, GenieX (Kotlin SDK, NPU) and LiteRT-LM (Gemma 4 + EmbeddingGemma)
> as the two real paths, and a no-code test to run first.

Python still orchestrates — this is just another edge-call per
`architecture.md`'s "LLM only at the edges" principle, invoked via
subprocess/JNI, with the deterministic core untouched. Fully deferred: the
scheduler node needs zero AI (`schedule.md` says so directly), so this doesn't
block anything yet.

## Repo layout

```
quintacle/
  core/       Python — node logic, FastAPI app, local stores (shared by every platform)
  frontend/   Next.js UI, ported from PersonalWebsite's STL/markdown components
  shells/
    desktop/  pywebview launcher (Windows/Linux)
    android/  Chaquopy + WebView shell (Android)
```

## Open questions (not decided yet)

- Chaquopy package compatibility per node as they're built — pure-Python nodes
  (scheduler, ledger, todo) should embed cleanly; anything pulling in
  C-extension-heavy deps needs a per-case check before assuming it'll run on
  Android.
- Exact pywebview vs. running a bare browser tab tradeoff for the desktop shell
  — pywebview chosen for a cleaner "app" feel, revisit if it fights Linux/Wayland.
- Chaquopy + local FastAPI/uvicorn server lifecycle on Android (foreground
  service to survive backgrounding, battery impact) — not yet validated.
