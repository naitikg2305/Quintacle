# Quintacle — Session Log

Running log of what's actually built vs. what's still just planning docs.
Newest session at the top. Read this before picking the project back up.

## 2026-10-15 — The perception wave: local-first ingest, on-device perception, auto photo-journal, the phone/ stack

Seven parallel worktree agents plus the main-thread integration, landed on
`redone-UI` through `1a46c92` (22 commits past the truth-sweep's `884d057`
stamp). This is the wave that made `architecture.md`'s 2026-10-15
local-first amendment real code. Suite: **335 passed / 5 skipped** with
perception deps (331/9 minimal venv), verified in fresh venvs. Full detail:
`~/work-logs/2026-10-15.md` sessions 5–12 and the two new reference docs —
`reference/perception-and-autojournal.md`, `reference/local-models.md`.

### Built this session

- **Local-first ingest dispatch** (`core/quintacle_core/llm_dispatch.py`):
  every easy text-parse seam (journal dump, KB sort/placement/update/batch,
  drop classification, people/travel/finance/home extractors — 16 call
  sites) now routes through `parse_structured`: local Ollama with the
  Pydantic schema as `format` (`QUINTACLE_LOCAL_PARSE_MODEL`, default
  qwen3:8b) first, cloud fallback on ANY local failure
  (`QUINTACLE_INGEST_PROVIDER=auto` default). `/drop`, `/kb/sort`,
  `/journal/{date}/parse` take `?provider=` and return `provider_used`;
  Drop/Journal show a provider badge + **"Redo with cloud ↻"** (re-runs
  from the ORIGINAL input — a step back); the KB chat defaults to
  `local:qwen3:8b` with a per-local-reply **"Escalate ↗"** that transfers
  the conversation to a cloud model. **Live-proven: real journal parses
  answered with `provider_used: local`.** Vision+schema sites and geocoding
  deliberately stay cloud.
- **Perception core** (`core/quintacle_core/perception/`): YOLOX-nano tags +
  SCRFD/ArcFace faces + deterministic scene attributes, onnxruntime CPU, no
  LLM, no cloud; embeddings persist only under `~/.quintacle/perception/`.
  Wired into `/drop` proposals, `POST /kb/asset/perceive`, and a free MCP
  `perceive_photo` tool (count now 17). TFLite/LiteRT backend behind
  `QUINTACLE_PERCEPTION_BACKEND=tflite` for the phone lane.
- **Auto photo-journal + tag flow** (`nodes/kb/auto_journal.py`): on photo
  commit, a deterministic line (`📷 2:14 PM — with Alex at Hermann Park ·
  sunny · dog, frisbee (photo: …)`) lands in the EXIF date's journal under
  an undoable `auto-photo:` marker (dedup-checked), plus
  `pictured_with`/`at_location` edges, `source_of_edge="photo_perception"`.
  Unknown faces flow to the Drop page's "who is this?" panel →
  `POST /perception/tag` enrolls, creates the person, wires edges, and
  edits the photo's ONE journal line in place. `GET
  /people/{name}/appearances` derives appearances purely from the graph.
  **E2E proven on real photos: drop a real selfie → auto-journal line on
  the EXIF day → tag the unknown face → person + edges + in-place line
  update → the same person re-matched at 0.803 cosine on a different
  photo.**
- **Local chat + local vision lanes**: `local:<model>` chat provider
  (`nodes/kb/chat.py`, readable OllamaError 400s); `QUINTACLE_VISION_BACKEND=
  ollama|llamacpp` inside `local_vlm/` — the llama.cpp client is the
  phone-capable one, desktop-proven through `/kb/asset/describe` (CUDA
  7.6 s, CPU 3m41s on a 12MP photo — prefill dominates).
- **`phone/` — the three-tier on-device stack**, each tier with its own
  README: Tier 1 Termux+Ollama scripts (pkg verified real, never run
  on-device), Tier 2 ONNX→TFLite conversion + parity (**11/11
  cross-backend enrollment matches** for f32 AND int8-DRQ; LiteRT ~2.6x
  faster than ORT-CPU on desktop), Tier 3 llama.cpp VLM lane. Charter in
  `phone/README.md`.
- **Deterministic routine expansion** (`nodes/journal/normalize.py`
  `expand_routine_mentions` + the header-drop/kcal-carry in
  `nodes/journal/llm.py`): "pull day" → the preset's exercises is now
  string matching in code, both providers, with the model's redundant
  header entry dropped and its lone calorie estimate carried onto the first
  expanded exercise. Live-proven on the real presets via local parse.

### Decisions

- **Deterministic-over-model for routine matching**: the seam audit showed
  cloud follows the expand-the-routine prompt rule and small local models
  reliably don't — and whether a name matches a preset is string matching,
  not judgment, so the rule moved into code and stopped being a provider
  difference at all.
- **Write-errors-durable split in the dispatch**: daemon-unreachable
  (`OllamaError`) and answered-but-schema-invalid (`LocalParseError`) are
  distinct, both readable 400s in `local` mode, both auto-fallback triggers
  in `auto` — ingest never 500s because the local model fumbled.
- Two face thresholds on purpose: perception labels a match at ≥ 0.55
  cosine; the journal/graph only *assert* a name at ≥ 0.8
  (`QUINTACLE_FACE_MATCH_THRESHOLD`) — in between, the UI offers the name
  as a suggestion without the record ever claiming it.
- Cloud escalation is always a step BACK (redo from original input) or an
  explicit chat choice — never re-prompting over local output, never a
  silent default.

### Gotchas and incidents

- The worktree stale-base gotcha struck AGAIN, repeatedly: agent worktrees
  cut from `c9cd583` instead of `redone-UI`. The standing rule
  (`git reset --hard redone-UI` before starting) held in every session that
  remembered it.
- **qwen3:8b spills ~29% to CPU at 16k ctx** on the 12 GB card — the
  dispatch's `num_ctx: 16384` is needed for parse payloads (meal/routine
  libraries), but it costs; seam-audit latency numbers reflect it.
- **onnx2tf's default `flatbuffer_direct` backend emits broken
  dynamic-range-quant files** (outputs saturated at inf/3.4e38 on all three
  models) — `convert.py` forces the `tf_converter` backend. That backend in
  turn **reattaches ONNX tensor names to the wrong TFLite outputs**
  (observed: a bbox tensor wearing a score head's name), so both the smoke
  check and the runtime adapter map outputs by unique static shape, never
  by name. Also: onnx2tf applies `overwrite_input_shape` by shelling out to
  the `onnxsim` CLI — off PATH, the input silently collapsed to
  `[1,1,1,3]`. All in `phone/tier2-perception-tflite/README.md` and
  `~/work-logs/2026-10-15.md` sessions 11–12.
- Seam audit so far: local 8B at parity on todos/dates/meal-presets; weak
  on dual-meaning food+money clauses (drops the expense) — exactly what the
  review gate + redo-with-cloud cover.

### Still device-pending / not built (honest list)

- **Nothing in `phone/` has touched the real S25U**: no APK build (needs
  JDK/device), no Termux script run, no on-device tok/s, no TFLite
  NNAPI/QNN delegate proof (wired, desktop no-op), no llama.cpp OpenCL run.
- Vision+schema local parsing (receipt extraction, image classification) —
  deliberately still cloud, the named next wave.
- Recent-writes/undo UI, remaining MCP domains, remote transport — still
  open from the previous entries.
- Seamless mode — still sequenced after Naitik's full manual test run,
  which remains the actual gate.

## 2026-10-14/15 — Day recall, Bedrock models, desktop shell, graph view usability, docs/reference, docs truth-sweep

Six commits on `redone-UI` after the 10-13 wave (`884d057..7694ffc`), built
across parallel worktree agents on 10-14/15 and integrated by the main
thread. The 10-13 entry below already covers the Vault + LAN sync builds and
the real two-backend sync verification (journals converged both ways, vault
entries unlocked on the peer) — this entry is what came after. Full detail:
`~/work-logs/2026-10-14.md` and `~/work-logs/2026-10-15.md`.

### Built this session

- **Day recall chain** (`cc29b0a`): one shared, LLM-free bundle builder
  (`core/quintacle_core/day_bundle.py`) behind both `GET /day/{date}` and the
  new MCP `day_recall` tool — journal, logs, todos, and now **photos**,
  resolved through an indexed `edges`-table query (`on_day` → that date's
  journal node), each with its stored drop-time description. On-demand
  (billed) vision: `POST /kb/asset/describe` re-looks at a stored image with
  an optional question, and the MCP `describe_photo` tool wraps it (bytes
  never cross MCP). Day page gets a photos strip with Browse deep links.
  MCP tool count: 16. This closes `usecases.md` UC4 for external clients —
  the in-app chat still can't see the journal.
- **Chat model picker, current-gen + Bedrock** (`1fdd0d8`): the picker's
  plumbing worked but the registry was a closed previous-gen list. Now:
  current Anthropic models added, plus a **`bedrock:<any-id>` provider** —
  Claude-family IDs via the anthropic SDK's Bedrock client, everything else
  via boto3 Converse, so whatever the AWS account can invoke works. AWS
  failures surface as readable 400s. Honesty note: provider runners are
  test-stubbed; a **live Bedrock invoke hasn't been run yet** (pending
  `aws sso login`).
- **Completed todos land on the calendar** (`2de53e7`): marking a todo done
  stamps `completed_at` (real ET) through one shared helper so REST and the
  MCP tool can't drift; todos take an optional category; the Day view's
  Action tab counts and lists completions on the day they *happened*, not
  their due date.
- **Graph view pan/zoom/fit** (`48449a9`): the view was a fixed 900x600
  window zoomed into one corner of a real-sized layout. Now viewBox pan,
  cursor-centered wheel zoom, auto-fit on settle, +/-/FIT controls, constant
  label size at any zoom — the whole graph is reachable. Details panel's
  open-note link now uses Browse's real `?path=&open=` params.
- **Desktop shell** (`7694ffc`, `desktop/`): the pywebview shell from
  `stack.md` is real — a wrapper FastAPI app serving the core API + the
  static UI export on one origin (`127.0.0.1:8000`), opened in a native Qt
  window; PyInstaller onedir bundle (cv2/numpy excluded, video descriptions
  degrade gracefully). **Linux binary built and `--smoke` passed** (headless
  — a GUI-on-a-real-display run is still pending). Windows build only exists
  as `.github/workflows/desktop.yml` (ubuntu+windows matrix) —
  syntax-checked, **never executed**, so the Windows binary is unverified.
- **`docs/reference/`** (`83da764`): eleven docs derived from code at
  `884d057` — statement of work, architecture, all 114 endpoints, data/DB
  formats, graph engine, MCP server, vault, sync, drop pipeline, frontend,
  Android status. The code-derived counterpart to these planning docs.
- **`docs/seamless-mode.md`** (with `2de53e7`): Admin vs. Seamless two-mode
  design + the friction-audit rule, explicitly sequenced after the
  functionality test. Planning only.
- **Docs truth-sweep** (this entry's session, 2026-10-15): dated status
  updates across the planning docs — `mcp-angle.md` / `graph-model.md` /
  `vault.md` / `deployment-and-privacy.md` / `stack.md` /
  `android-apk-migration.md` and the index no longer claim "not started" for
  things that shipped; historical sections kept intact per convention.

### Gotchas and incidents

- **The port-8000 / doc-extractor incident**: a separate side project
  (`~/code/doc-extractor`, 10-13) left its own uvicorn squatting on
  `127.0.0.1:8000`, breaking the assumption that whatever answers on :8000
  is Quintacle. Fix lives in the desktop shell: it **fingerprints** the port
  (probes `/kb/folders` for Quintacle's JSON shape) before reusing a running
  backend, errors readably if a foreign server holds the port, and `--smoke`
  always self-hosts on an ephemeral port so it verifies its own artifact
  rather than whatever happens to be listening.
- **Prod boot on real data**: the backend was booted against the real
  `~/.quintacle` store (not test dirs) and came up clean on the
  post-10-13 codebase — first real-data boot since the build wave.
- The wave-1 worktree gotcha from 10-13 repeated: agent worktrees cut from
  `main`'s stale snapshot (`c9cd583`) instead of `redone-UI`; standing rule
  is `git reset --hard redone-UI` before starting.

### Still planning / not built (so nothing reads as more done than it is)

- Remaining ~12 MCP domains' tools, remote/HTTP transport, binary assets
  over MCP, and the in-app recent-writes / undo-window UI (`mcp-angle.md`).
- The APK itself (needs JDK/SDK or the phone) and any on-device run of the
  Termux backend (`reference/android.md`).
- Windows desktop binary (workflow unexecuted); packaged-app GUI run on a
  real display.
- Live Bedrock invoke (needs `aws sso login`); local-LLM tiers
  (`deployment-and-privacy.md`) untouched.
- The real-use test run (`test-plan-and-wishlist.md`) — next step, and
  Naitik-driven by choice; `seamless-mode.md` comes after it.

## 2026-10-13 — The big one: MCP server, graph engine, Vault, LAN sync, Drop sessions, Android scaffolding

One marathon session (plus its 10-07 prelude) took several of the oldest
"planned, not started" items to built-and-pushed. Everything below is live on
`redone-UI` (pushed through `9baf59a`), 205 backend tests passing, tsc clean.
Full detail: `~/work-logs/2026-10-13.md` sessions 2-4, and the per-feature
design docs named below.

### Built this session

- **MCP server** (`core/quintacle_core/mcp_server/`, run `python -m
  quintacle_core.mcp_server`, stdio): 14 tools over journal/KB/expenses/todos,
  **auto-write with no approval** — safety is a staged-snapshot undo instead:
  every push is one entry in the human-readable ledger `~/.quintacle/mcp-log.md`,
  undoable via `undo_write` (journal appends strip exactly their marked block;
  multi-step pushes undo as a unit). Write tools take final structured input,
  never raw text to reclassify — the cost design in `mcp-angle.md`'s 2026-10-13
  sections, which also list the ~12 domains not yet covered, the exclusions
  (kb chat, vault-shaped docs, binary assets), and the remote-transport open
  question.
- **Graph engine** (`core/quintacle_core/graph.py`, spec in `graph-model.md`):
  edge files under `~/.quintacle/graph/edges/` as truth + an `edges` SQLite
  table as the derived fast index; typed edges (`mentions_person`,
  `at_location`, `on_day`...); `neighborhood()`/`reverse_lookup()` via
  recursive SQL; `/graph` now reads the table instead of re-walking all
  frontmatter per request, with a one-time startup backfill. The
  experience↔person same-drop linking gap is fixed. Every MCP write
  auto-links (`mcp_server/graph_link.py`), and undoing a push removes the
  edges it created.
- **Vault** (`core/quintacle_core/nodes/vault/`, page at `/vault`): encrypted
  secrets — scrypt KDF + Fernet, one `.enc` file per entry, at
  `~/.quintacle/vault/`, deliberately a **sibling of kb/** so search, graph,
  MCP, KB chat, and the drop pipeline structurally never see it. One
  passphrase, memory-only key, 5-minute auto-lock, no recovery flow by
  design. The build's audit also exposed a path-traversal hole in
  `/kb/asset(+/replace)` — now clamped to the KB root.
- **Manual LAN sync** (`core/quintacle_core/sync.py`, page at `/sync`):
  pull/two-way between two devices on shared wifi, manual button only.
  Journal days union-merge (both sides' blocks, byte-exact MCP markers);
  everything else newest-wins with the loser snapshotted to
  `_sync_snapshots/`; additive — **deletions do not propagate** in v1;
  `quintacle.db` and the MCP ledger stay device-local, indexes rebuild after
  a pull. Verified against two live backends over real HTTP: journals
  converged identically both directions, synced vault entries unlock on the
  peer, second pull is a no-op.
- **Drop upgrades**: multi-attachments of any type on one drop (ticket photo
  + PDF + QR → one entry, every file kept), and the "Still going" session
  panel — after a single-note save, keep folding text / attaching photos into
  that same entry (lectures, recipes-in-progress, live trip records).
- **Android scaffolding** (not yet an APK): `frontend/android/` Capacitor
  project + `CAPACITOR_BUILD=true` static export (builds all pages), and
  `scripts/termux/` backend bootstrap + `docs/termux-backend-setup.md`.
  Blocked only on a JDK/Android SDK or the phone itself; cv2 now
  lazy-imports so a phone without opencv still boots the API.
- **Fixes from the 10-07 prelude**: journal page no longer duplicates on
  save; "today" is Eastern Time everywhere (`frontend/lib/date.ts`,
  `core/quintacle_core/clock.py`) instead of UTC/host-local.

### Decisions worth remembering (the why lives in the named docs)

- Approval-first MCP writes were designed, then **superseded the same week**:
  single-user means undo-after equals approve-before at less friction
  (`mcp-angle.md`, both sections kept).
- Graph is a small bespoke engine, deliberately not Neo4j — data an LLM sees
  is engine-agnostic; what matters is edges existing (`graph-model.md`).
- Generic-vs-bespoke is tentatively settled: logs/quotas/schedule stay
  hard-typed (the value is arithmetic), everything item-shaped can go
  generic KB + fields + graph (`ai-managed-pages.md`) — to be confirmed by
  the real-use test run (`test-plan-and-wishlist.md`), which is the next step
  and is Naitik-driven by choice.

### How this was built

Six parallel subagents across two waves, each in an isolated git worktree,
integrated by cherry-pick onto `redone-UI`. Wave-1 gotcha for the record:
worktrees were cut from `main`'s old snapshot, so agents built on the
pre-redesign base and everything needed rebase-style integration; wave 2 was
told to `git reset --hard redone-UI` first and landed clean.

## 2026-09-07 — Goals extended, Journal rebuilt with AI, Knowledge Base built from scratch, full nutrition

Big session. Went from "Daily Tracker v0" to most of Pillars 1–3 actually
working end to end, driven by real Claude API calls. `docs/quintacle-ideas.md`
was also heavily expanded *before* this session's code (new KB domains,
Photo Drop, Digital Tech Vault, cross-cutting principles) — see its own
"Decisions" log for that half. This entry is the code side.

### Goals Dashboard (Pillar 2) — now supports both goal shapes

- `habits` table gained `metric`/`direction` columns (idempotent `ALTER TABLE`
  migration — ran clean against the real db, Golf/Guitar preserved).
- `quotas.py`'s `habit_progress` dispatches on `metric` (`activity_hours` vs
  `food_kcal`) and compares by `direction` (`at_least` vs `at_most`) — the
  extension point for a future `spend`-based metric once a finance log exists.
- `/habits` page: radio toggle between "Time-based (hours)" and "Amount cap
  (kcal)" goals.

### Journal (Pillar 1's Bridge) — rebuilt around a real LLM, taxonomy tightened

- **Category taxonomy changed**: the old `emotional/productive/social/fitness/work`
  became **productivity / social / leisure / yourself / emotional** (5,
  emotional kept as its own category on request). Existing Golf/Guitar habits
  were remapped (`physical`→`yourself`, `social`→`leisure`).
- `nodes/journal/llm.py`: `parse_journal_dump()` calls Claude via
  `client.messages.parse()` with a **discriminated union** schema — one dump
  can produce `activity` / `food` / `exercise` / `substance` entries all at
  once (not just activity-log categories). `POST /journal/{date}/parse`
  proposes, never writes (Approval before write).
- **Meal-preset aware**: the parser is handed the real `meals` library and
  matches "had lamb meal and smoothie" to existing presets by `meal_id`
  instead of re-guessing calories every time — only estimates fresh when
  nothing matches.
- `/journal` page rewritten: one freeform dump box + "Parse with AI" +
  manual "+ Activity / + Food / + Exercise / + Substance" buttons, all
  feeding **one shared entry list** (AI-sourced and hand-typed rows are
  identical once in the list) with a single "Save day" commit.

### Knowledge Base (Pillar 3) — did not exist as code before this session

- New `nodes/kb/` package. `KBStore`: one markdown file per entry, grouped
  into folders on disk (`slugify()` doubles as the path-traversal guard).
- `POST /kb/sort` proposes `{folder, title, content}` from freeform text
  (seeded with the domain list from the planning doc so early pushes land
  somewhere sensible); `POST /kb/entries` is the separate, explicit commit.
- **KB-grounded chat** (`POST /kb/chat`): a "Use Knowledge Base" checkbox
  injects the *entire* KB as context (no embeddings/retrieval yet — fine at
  current KB size, revisit if it ever gets large). A "More power" checkbox
  switches to the research model.
- **Chat has real persistence now** (`chat_store.py`): every session is its
  own markdown file (`# title` / `### You` / `### Assistant`) under
  `~/.quintacle/kb_chats/`, survives reloads, and has an explicit delete —
  matching the "chat is ephemeral, KB is permanent" principle with an actual
  file lifecycle (push the good parts into the KB, then delete the chat).
- `/kb` page: folder/entry browser + viewer, scratchpad→sort→push flow, and
  the chat panel (session picker, new/delete, "→ add to scratchpad" on every
  assistant reply to bridge chat output into the push flow).

### Model tiering — cheap by default, switchable for power

- New `llm_config.py`: `QUINTACLE_LLM_MODEL` (default `claude-haiku-4-5`) for
  routine structured parsing (journal, KB sort); `QUINTACLE_LLM_RESEARCH_MODEL`
  (default `claude-sonnet-5`) reserved for heavier tasks (the KB chat's
  "more power" mode). Both are env-var overridable, no code changes needed.
- `core/.env` holds the real `ANTHROPIC_API_KEY` (gitignored; `.env.example`
  is the committed template). `QUINTACLE_DATA_DIR` also documented there —
  data intentionally stays outside the repo (see Cross-Cutting Principles'
  reasoning: portability + never risking personal data in a `git add .`).

### Full nutrition tracking — macros+fiber+20 micronutrients vs. male RDA

- New `meal_micros` table + `fiber_g` column on `meals`. `nutrition_targets.py`
  has real male RDA values for 20 nutrients (Sodium flagged as a limit, not
  a target).
- `nutrition_llm.py`: `estimate_nutrition()` fills in macros/fiber/all 20
  micros from a description. `POST /logs/meals/estimate` proposes (never
  writes); `POST /logs/meals` accepts the full panel to actually create a
  preset.
- **Bug caught and fixed**: the model returned Copper in mg while the RDA
  reference expects mcg — `pct_of_rda` silently read 0.2% instead of ~80%.
  Fixed at the root (explicit unit per nutrient in the prompt) plus a real
  conversion function as a backend safety net (`to_canonical_unit` — converts
  g/mg/mcg properly, never just relabels). Regression-tested.
- `GET /logs/nutrition/{date}` combines macro totals with all 20 micros'
  %RDA. Surfaced in the `/day` page's expanded Food section (progress bars,
  Sodium's bar goes red past 100% since it's a limit).
- Real data: two actual meal presets exist — **Lamb Meal** and **Smoothie**
  (your real breakfast) — backfilled with AI-estimated fiber/micros through
  the same production path, not hand-typed.

### Calendar (`/day`) fixed to show everything

- New `GET /day/counts` — month-view badges now count activities + food +
  exercise + substances, not just activities.
- Expanded day view now shows journal, activities, food (+ full nutrition),
  exercise, substances, and body stats — previously only showed activities.

### Not started yet

- Raw-ingredient/label-photo capture (photo a nutrition label → precise
  per-100g data → feeds meal calculations) — user is still designing this,
  explicitly parked, not built.
- Unifying Journal Dump and Photo Drop into one text-or-image "Drop" surface
  that routes to *any* pillar (not just the 4 log types) — named as the
  clear next architectural step, not built.
- Desktop/Android shells — still plain dev processes (`uvicorn` + `npm run
  dev`), unchanged from session 1.
- `docs/quintacle-ideas.md` has drifted from the code in a few spots worth
  reconciling next: the taxonomy change (productivity/social/leisure/
  yourself/emotional) isn't reflected there yet, and micronutrient tracking
  + chat persistence aren't mentioned in the doc at all.
- Vault, Wardrobe, Travel, Home Catalog, Marketplace, Career/Style/Media KB
  domains: still just planning, no code.

### How to run it

```bash
# backend
cd core && .venv/bin/uvicorn quintacle_core.api:app --port 8000

# frontend (separate terminal)
cd frontend && npm run dev
```
Data persists at `~/.quintacle/` (markdown + `quintacle.db`, both directly
inspectable — `sqlite3 ~/.quintacle/quintacle.db` works). Needs a real
`ANTHROPIC_API_KEY` in `core/.env` for anything AI-powered (journal parsing,
KB sort/chat, nutrition estimation) — everything else still works without it.

---

## 2026-09-03 — first build session: scheduler + logs + journal + running UI

### What got built (real code, not just docs)

**`core/`** — Python/FastAPI backend, one process, runs identically on
Windows/Linux (normal process) and eventually Android (via Chaquopy — not
built yet, see Not Started below). Local-first: all data lives under
`~/.quintacle/` (override with `QUINTACLE_DATA_DIR`).

- `nodes/schedule/` — Calendar A (forward todo/calendar). One markdown
  frontmatter file per todo under `~/.quintacle/schedule/todos/`. Deterministic
  ranking by due date then priority, calendar view derived from todos, no AI.
- `nodes/logs/` — SQLite (`~/.quintacle/quintacle.db`), for dense tabular
  day-indexed data (this was a real course-correction mid-session — markdown
  was wrong for this, see `stack.md`/decisions below). Tables: `meals`
  (premade meal macro library), `food_log` (references a meal, macros
  auto-computed via join instead of retyped — this was the direct fix for the
  manual `=SUM(...)` pain in the old `InOutTake.xlsx`), `substance_log`,
  `activity_log` (now has an `hours` column — added mid-session for quota
  math), `exercise_sets`, `body_stats`, `habits` (target_amount/target_period/
  match_category — the weekly-goal definitions).
- `nodes/journal/` — one markdown file per day under `~/.quintacle/journal/`,
  the narrative record. No LLM parsing yet (deliberately cut — see decisions).
- `GET /day/{date}` in `api.py` — cross-node endpoint: pulls journal + todos
  due + activities + exercise + food + body stats + substances for one date
  in a single deterministic call. This is `architecture.md`'s March-13 example
  made real.
- Tests: `core/tests/` — ranking, store round-trip, logs (incl. the meal
  macro-autofill behavior), quota window math. All passing as of this session.

**`frontend/`** — Next.js 16 / React / Tailwind, talks to the core API at
`http://localhost:8000`. Pages: `/journal` (nightly dump by subtopic —
Productive/Emotional/Physical/Work/Social — each a text box + hours field,
logs directly to `activity_log` + saves the raw dump to that day's journal
markdown, no LLM), `/habits` (set weekly/monthly hour goals per subtopic,
live progress bars against actual logged hours), `/day` (month calendar,
**Regular**/**Action** tabs — Regular shows todo-due-counts per day, Action
shows logged-activity counts per day; click a day to expand — Action mode
groups the day's entries by category, e.g. Physical/Work/Social, meant to
generalize to Finance/Gym/etc. as more nodes land), `/todos` (Calendar A —
ranked list + add/complete).

Both processes were running live and smoke-tested end to end during this
session (backend on :8000, frontend on :3000, real data in `~/.quintacle`,
not test dirs).

### Real decisions made this session (not obvious from the code alone)

- **Stack**: Python/FastAPI core shared by all platforms; Next.js UI (ported
  from the existing `PersonalWebsite` project's STL/markdown-viewer
  conventions) shown via pywebview on desktop, via Chaquopy+WebView on
  Android. Full reasoning in `stack.md`.
- **Storage split**: markdown-per-item for narrative/reference nodes (todos,
  journal), SQLite for dense tabular day-indexed logs (productivity, exercise,
  diet, substances, body stats). Got this wrong once mid-session (tried
  markdown for the logs too) — user corrected it, SQLite is right for that
  data shape and is *more* Android-safe than markdown anyway (`sqlite3` is
  Python stdlib, no Chaquopy wheel-compatibility risk).
- **AI/vision/SLM**: four-tier routing now written into
  `deployment-and-privacy.md` — phone-local NPU stack (TFLite/NNAPI +
  MediaPipe LLM Inference or ONNX+QNN) is the default and needs no computer
  or network at all; computer's local stack is an optional richer fallback;
  an explicit user-picked switch (OpenAI or Anthropic) covers cloud vision,
  collapsing detect+caption+narrate into one vision-LLM call instead of
  re-hosting YOLO server-side; code-only is the fail-closed floor. Identity
  matching against enrolled face profiles always stays local regardless of
  the switch — carried over unchanged from the existing `FaceDetect`
  prototype's own design.
- **Nightly journal capture doesn't need an LLM.** Original
  `habits-and-checkin.md` plan had an LLM parsing a free-text voice dump into
  structured fields. Replaced with something simpler and already built: a UI
  with one box per subtopic + an hours field, logged directly. The LLM
  narration step (ask "what was I doing that day" and get an answer) is still
  a valid future feature but is fully decoupled from logging — it would read
  the already-structured data, not produce it.
- Use a **personal** Anthropic account for Quintacle, not a work-provisioned
  one — flagged as a real policy/privacy line, not just a technical one,
  especially since Quintacle will hold journal/dating/financial data.

### Not started yet

- Desktop shell (pywebview) and Android shell (Chaquopy + WebView) — right
  now both `core/` and `frontend/` just run as plain local dev processes.
- The dashboard rollup (time-per-category across arbitrary date ranges).
- LLM narration ("what was I doing on date X") — deferred, not blocking.
- On-device YOLO/face-detection/SLM (media-analysis node) — architecture
  decided (`deployment-and-privacy.md`), nothing built.
- Every other planned node beyond schedule/logs/journal: ledger, outfits,
  diet's meal-planning/grocery-list side, apartment, car, routines, vault,
  schemes.
- Phone/computer LAN sync (`deployment-and-privacy.md`'s open questions on
  this are all still open).
- Known small bug: logging a subtopic in the Journal UI with text but no
  hours value can silently save `0.0` hours (seen live: a `work` entry saved
  with `hours: 0.0`) — not yet root-caused as a UI bug vs. empty input.

### How to run it again

```bash
# backend
cd core && .venv/bin/uvicorn quintacle_core.api:app --port 8000

# frontend (separate terminal)
cd frontend && npm run dev
```
Data persists at `~/.quintacle/` (markdown files + `quintacle.db`, both
directly inspectable/editable — `sqlite3 ~/.quintacle/quintacle.db` works).
