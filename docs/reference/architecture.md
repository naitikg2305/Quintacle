# Architecture — processes, startup, data layout, LLM seams, clock

Derived from code at commit `884d057` on 2026-10-15.

## Process layout

Three processes, at most, none required by the others:

1. **The FastAPI backend** — `uvicorn quintacle_core.api:app --port 8000`
   from `core/` ([core/quintacle_core/api.py](../../core/quintacle_core/api.py)).
   One process owns everything: every store, the SQLite connection
   (`check_same_thread=False`, WAL mode), the graph engine, and sync. CORS
   is wide open (`allow_origins=["*"]`) — the trust model is "localhost/LAN
   only", there is no auth layer anywhere.
2. **The Next.js frontend** — `npm run dev` (or a static export for
   Android). Talks to the backend at `NEXT_PUBLIC_API_BASE`, default
   `http://localhost:8000` ([frontend/lib/api.ts](../../frontend/lib/api.ts)).
3. **Optionally, the MCP server** — `python -m quintacle_core.mcp_server`,
   stdio transport, spawned by an MCP client (Claude Code etc.). It does
   NOT talk to the FastAPI app over HTTP: it imports the same store classes
   and opens its own connection to the same `quintacle.db`
   ([core/quintacle_core/mcp_server/server.py](../../core/quintacle_core/mcp_server/server.py)).

All three share one data directory:
`QUINTACLE_DATA_DIR`, default `~/.quintacle` (`api.py` line 84; the MCP
server reads the same variable independently).

`core/.env` is loaded by `load_dotenv()` at `api.py` import time, *before*
any module reads `os.environ` — this is where `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `QUINTACLE_LLM_MODEL`, `QUINTACLE_LLM_RESEARCH_MODEL`
live. Each LLM helper constructs `anthropic.Anthropic()` fresh per call and
relies on the env var.

Vision has its own provider switch, read per call (so it also works from
`core/.env`): `QUINTACLE_VISION=cloud|local|auto` (default `cloud`,
unchanged behavior) dispatches every `describe_images()` call — drop-time
descriptions, `/kb/asset/describe`, the MCP `describe_photo` tool — between
the metered Anthropic call and a local VLM served by Ollama on localhost
(`core/quintacle_core/local_vlm/`; model `QUINTACLE_VISION_MODEL`, default
`qwen2.5vl:3b`; daemon URL `QUINTACLE_OLLAMA_URL`, default
`http://localhost:11434`). `auto` tries local and falls back to cloud with
a warning log line; `local` raises rather than silently billing the cloud.

> *Moved since the stamp, later 2026-10-15 (code at `1a46c92`): the env
> surface above is no longer the whole story. The local VLM now has a
> second backend (`QUINTACLE_VISION_BACKEND=ollama|llamacpp`, llama.cpp's
> llama-server at `QUINTACLE_LLAMACPP_URL`); structured ingest got its own
> provider switch (`QUINTACLE_INGEST_PROVIDER=auto|local|cloud`, default
> **auto** — local-first with cloud fallback — plus
> `QUINTACLE_LOCAL_PARSE_MODEL`, default `qwen3:8b`, and
> `QUINTACLE_OLLAMA_HOST` for the daemon address shared with the chat's
> `local:` provider); and the perception lane added
> `QUINTACLE_PERCEPTION_BACKEND`, `QUINTACLE_TFLITE_VARIANT`,
> `QUINTACLE_TFLITE_DELEGATE`, `QUINTACLE_PERCEPTION_MODELS_DIR`,
> `QUINTACLE_FACE_MATCH_THRESHOLD`, `QUINTACLE_AUTOJOURNAL_POLISH`. The
> complete knob table with defaults and reading modules is
> `reference/local-models.md` (and the perception subset in
> `reference/perception-and-autojournal.md`).*

## Startup sequence — `create_app()` top to bottom

Everything is wired once per process, in this exact order (ordering
comments are the code's own):

1. `init_schedule_store(DATA_DIR / "schedule" / "todos")` → `TodoStore`;
   mount `/schedule` router.
2. `conn = db.connect(DATA_DIR / "quintacle.db")` — creates/migrates the
   full schema ([data-and-db.md](data-and-db.md)).
3. `init_graph_store(DATA_DIR, conn)` — the `GraphEdgeStore` (edge files +
   `edges` table) on that same connection.
4. `init_repo(conn, LogFileStore(kb_root))` — the logs repository, writing
   through to markdown log files nested *inside the KB tree* (so copying,
   say, `Personal Development/Physical/Fitness/` carries both notes and the
   numbers); mount `/logs`.
5. `init_journal_store(DATA_DIR / "journal")`; mount `/journal`.
6. `init_kb_store(kb_root)` + `init_chat_store(DATA_DIR / "kb_chats")`;
   mount `/kb`.
7. `init_profile_store(DATA_DIR / "profile.json")`, then
   `init_profile_ref(profile_store)` — hands logs a profile reference for
   %RDA personalization without a `profile.api ↔ logs.api` import cycle;
   mount `/profile`.
8. `init_wardrobe_store(kb_root)`; mount `/wardrobe`.
9. `init_grooming_store(kb_root)`; mount `/grooming`.
10. `init_document_store(kb_root, get_schedule_store)` — documents get a
    schedule-store getter so a new document with an expiry date can
    auto-create a renewal todo; mount `/documents`.
11. `init_home_store(kb_root)`; mount `/home`.
12. `init_travel_store(kb_root)`; mount `/travel`.
13. `init_people_store(kb_root)`; mount `/people`.
14. `init_credit_card_store(kb_root)`; mount `/credit-cards` and
    `/investments` (two routers, one module).
15. `init_vault_store(DATA_DIR / "vault")` — deliberately OUTSIDE
    `kb_root`; mount `/vault`. See [vault.md](vault.md).
16. `init_sync(DATA_DIR)`; mount `/sync`. Must come after logs/graph init
    because a pull rebuilds those stores' SQLite indexes.
17. **Graph backfill** (one-time per process): builds a title→id lookup
    from every KB note title, journal date, and experience name, then for
    every note and every experience resolves its frontmatter `links` titles
    (via `canonicalize_name`) and calls `sync_frontmatter_links(...)` — so
    links authored before the `edges` table existed are materialized into it
    at startup. This reads frontmatter; it is NOT the same as
    `graph.rebuild_from_folder` (which recovers SQLite from already-written
    edge files). O(KB size) once at startup, not per request.
18. Four endpoints defined inline on `app` itself: `GET /day/counts`,
    `GET /day/{for_date}`, `POST /drop`, `GET /graph`.

Module-level `app = create_app()` at the bottom means importing
`quintacle_core.api` builds the whole thing.

## Data directory layout

What the stores actually create under `~/.quintacle/` (nothing is created
until first written, except directories made by store constructors):

```
~/.quintacle/
├── kb/                          # the KB tree — every model-facing surface walks ONLY this
│   ├── <nested folders>/<slug>.md        # KB notes (frontmatter: links/location/fields/assets)
│   ├── <folder>/assets/<file>            # binary assets (photos/PDFs/STL/xlsx)
│   ├── <folder>/_view.json               # saved folder layout (optional)
│   ├── personal-development/physical/fitness/{logs,routines}/
│   ├── personal-development/physical/nutrition/{logs,presets,ingredients}/
│   ├── personal-development/physical/style-dressing/{items,outfits}/
│   ├── personal-development/physical/grooming/{items,routines}/
│   ├── daily-log/{productivity,social,leisure,yourself,emotional,substances}/logs/
│   ├── organisation/finance/logs/        # expense log files
│   ├── organisation/finance/{credit-cards,stocks-investments}/
│   ├── organisation/document-vault/      # documents + assets/
│   ├── organisation/home/<city>/<residence>.md + <residence>/items/
│   ├── people/<name>/profile.md          # + Mentions/ notes beside it
│   ├── planning/travel/<city>/<kind>/<slug>.md
│   └── media/photos/<Year>/<Month>/...   # EXIF-dated photo archive
├── journal/YYYY-MM-DD.md        # one file per day, append-only blocks
├── schedule/todos/<id>.md       # one file per todo
├── graph/edges/<ts>-<hex>.md    # one frontmatter-only file per edge
├── kb_chats/<session-id>.md     # scratch chat transcripts
├── vault/                       # encrypted secrets — sibling of kb/, never inside it
│   ├── meta.json                # salt + verifier
│   └── entries/<slug>.enc       # Fernet blobs
├── profile.json
├── quintacle.db (+ .db-wal, .db-shm)   # derived index, rebuildable
├── mcp-log.md                   # MCP write ledger (device-local)
├── _sync_snapshots/<ts>/<path>  # pre-overwrite copies made by sync pulls
└── _trash/                      # reserved in sync's exclusion list; nothing creates it yet
```

(Folder segments on disk are slugified — lowercase, hyphenated — by
`markdown_paths.resolve_nested`; the display names above map to those slugs.)

## The deterministic-core principle, as implemented

The rule (from `docs/architecture.md`, enforced in code): storage and
retrieval are plain code; the LLM never decides *what to fetch* or *writes
directly* — it proposes, extractions get reviewed, and deterministic safety
nets (regex gates, `canonicalize_name` fuzzy matching, EXIF reads) run
before and after every call.

Census: **35 `anthropic.Anthropic()` call sites** plus **2 `OpenAI()` sites**
(`nodes/kb/chat.py` for GPT chat models, `nodes/kb/image_gen.py` for image
generation — Anthropic has no image model). By seam:

**Ingest classification / field extraction** (Haiku `DEFAULT_MODEL`, all
behind review-before-write):
- `nodes/drop_router.py` — `classify_image_type` (7-label photo kind),
  `classify_text_file_type` (document vs. note), `extract_finance_from_receipt`.
- `nodes/journal/llm.py` — `parse_journal_dump` (the 8-type union), plus two
  deliberately tiny second passes `_resolve_entry_dates` (regex-gated) and
  `_resolve_finance_kinds` — split out because the main union schema sits at
  Anthropic's structured-output grammar-size ceiling.
- `nodes/kb/llm.py` — `suggest_kb_entry`, `suggest_kb_entry_for_folder`,
  `suggest_kb_placement` (keep-as-is), `suggest_kb_batch`, `suggest_kb_update`.
- `nodes/kb/drop.py` — `_describe_image`, `_describe_pdf`, `_describe_video`
  (frame sampling via OpenCV, cv2 imported lazily).
- `nodes/kb/photo_organizer.py` — `geocode` (GPS → place names via Claude's
  own knowledge, no geocoding API).
- `nodes/logs/nutrition_llm.py` — `estimate_nutrition`,
  `estimate_nutrition_from_image`; `nodes/logs/meal_composer.py` —
  `suggest_meal_composition`; `nodes/logs/routine_llm.py` —
  `suggest_workout_routine`.
- Domain extractors: `wardrobe/llm.py` (4 sites), `grooming/llm.py` (3),
  `documents/llm.py` (1), `home/llm.py` (2), `finance/llm.py` (2),
  `people/llm.py` (2), `travel/llm.py` (1).

**Suggestion / additive proposal** (regex-gated so the call usually never
happens): `travel/llm.py maybe_structure_experience` and
`people/llm.py maybe_structure_person_mention` — the "propose everything
plausible, user prunes" checks run by `/drop` and `/journal/{date}/parse`.

**Narration / conversation**: `nodes/kb/chat.py run_kb_chat` — the only
free-form generation seam. Anthropic path uses prompt caching
(`cache_control: ephemeral` on the KB context block) and the server-side
`web_search` tool; Opus adds the server-side-fallback beta. OpenAI path uses
the Responses API with its own `web_search`. Chat *never writes* — pushing a
chat result into the KB goes through `/kb/sort` + `/kb/entries` like any
other proposal.

Deterministic counterweights worth knowing by name:
`journal/normalize.canonicalize_name` (difflib fuzzy-match against
already-established names, applied to exercises, substances, meals,
ingredients, wardrobe/grooming items, people, residences, documents, cards,
routines), `drop_router.parse_prefix` / `parse_routine_definition`,
`kb/drop.extract_photo_date` / `extract_photo_location` (EXIF),
`kb/photo_organizer.compute_photo_folder` (date math), `schedule/ranking.py`,
`logs/quotas.py`, `profile/targets.py` (Mifflin-St Jeor),
`logs/nutrition_targets.py` (static NIH/FDA RDA tables + unit
canonicalization), and `graph.link_new_entry` (whole-word keyword matching).

## The Eastern-time clock convention

Backend: [core/quintacle_core/clock.py](../../core/quintacle_core/clock.py)
pins `TIME_ZONE = ZoneInfo("America/New_York")`; `clock.now()`/
`clock.today()` are used for every timestamp and "today" (journal stamps,
edge ids, ledger entries, vault expiry, quota windows, sync snapshot names).
Rationale in the module docstring: a UTC host would roll the day over at
~8 pm ET and file the nightly journal under tomorrow.

Frontend: [frontend/lib/date.ts](../../frontend/lib/date.ts) mirrors it —
`todayIso()` formats the current instant in `America/New_York` via
`Intl.DateTimeFormat("en-CA", …)` instead of `toISOString()` (which is UTC).
Helpers: `yearsAgoIso`, `calendarIso` (local-field read for calendar-built
Dates), `currentMonthStart`.
