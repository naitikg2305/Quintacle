# Quintacle — Statement of Work (technical reference, as built)

Derived from code at commit `884d057` on 2026-10-15.

This folder (`docs/reference/`) is the systematic technical reference for
Quintacle: how the system actually works, derived entirely from reading the
source. The rest of `docs/` is design/decision history — the *why*. When the
two disagree, these files describe the code and flag the discrepancy.

## What Quintacle is

Quintacle is a local-first personal operating system: one person's journal,
todos, food/exercise/substance/spending logs, knowledge base, wardrobe,
grooming, home inventory, documents, people, travel experiences, finance
holdings, and secrets — all stored as plain files (markdown with YAML
frontmatter) plus one SQLite file under `~/.quintacle/`, served by a single
FastAPI process ([core/quintacle_core/api.py](../../core/quintacle_core/api.py))
and a Next.js frontend ([frontend/](../../frontend/)).

Five properties define it:

1. **Deterministic core, LLM only at the edges.** Storage, retrieval,
   ranking, calendars, quotas, nutrition math, graph traversal, and sync are
   all plain code. LLM calls happen only at well-defined seams — classifying
   a raw drop, extracting fields from a photo, grounding a chat — and every
   AI output is a *proposal* the user reviews before anything is written
   (except MCP writes, which commit immediately but are fully undoable).
   See [architecture.md](architecture.md) for the call-site census.
2. **Files are the record; SQLite is a disposable index.** Every dense log
   table in `quintacle.db` can be wiped and rebuilt from the markdown
   (`POST /logs/rebuild-index`, `graph.rebuild_from_folder`). See
   [data-and-db.md](data-and-db.md).
3. **Graph-linked knowledge.** Notes, journal days, experiences, and people
   are connected by typed edges, each edge its own markdown file under
   `graph/edges/` mirrored into an SQLite `edges` table. Edges are created
   at write time by a deterministic keyword matcher — no AI call. See
   [graph-engine.md](graph-engine.md).
4. **An MCP door.** A separate stdio MCP server
   (`python -m quintacle_core.mcp_server`) exposes 14 tools over the same
   stores, with auto-committing writes backed by a human-readable ledger and
   exact undo. See [mcp-server.md](mcp-server.md).
5. **Structural privacy for secrets, manual LAN sync for devices.** The
   encrypted Vault lives *outside* the `kb/` tree every model-facing surface
   walks ([vault.md](vault.md)); two devices sync by an explicit pull over
   the LAN with union-merged journals and snapshot-protected LWW
   ([sync.md](sync.md)).

No auth anywhere: the process binds to localhost/LAN and "the LAN is the
auth" (see `docs/self-hosting.md` for the eventual Tailscale answer).

## Feature inventory, as built today

### Domains (backend nodes under `core/quintacle_core/nodes/`)

| Domain | Storage | What it does |
|---|---|---|
| schedule | `schedule/todos/*.md` (one file per todo) | Todos with priority/due date/time window; deterministic ranking and calendar (`ranking.py`) |
| journal | `journal/YYYY-MM-DD.md` (append-only day files) | Narrative daily record; AI parse into structured log proposals; MCP appends are marker-tagged for exact undo |
| logs | markdown log files under `kb/` + SQLite index | Activities, food, exercise sets, substances, body stats, expenses; meal + ingredient preset libraries; composed meals with deterministic totals; habits/quotas; nutrition vs. real sex/age RDA tables |
| kb | `kb/` tree, one `.md` per entry + `assets/` | Nested-folder knowledge base; AI sort/placement/update; folder views (list/gallery/cards/table, inferred or saved `_view.json`); full-text substring search; spreadsheet asset editing; multi-model KB-grounded chat with web search; image generation (OpenAI); photo gallery |
| profile | `profile.json` | Height/sex/birthdate/activity level/home countries; Mifflin-St Jeor kcal + protein targets |
| wardrobe | `kb/Personal Development/Physical/Style & Dressing/{items,outfits}/` | Clothing items (photo-described) and outfits (composed from items or a saved full-look photo) |
| grooming | `kb/Personal Development/Physical/Grooming/{items,routines}/` | Grooming products and ordered routines |
| documents | `kb/Organisation/Document Vault/` | Formal documents (lease, ID, insurance) with typed fields, multi-page scans, auto-created renewal todo on expiry date |
| home | `kb/Organisation/Home/<City>/<Residence>/` | Residences over time + per-residence item inventory |
| travel | `kb/Planning/Travel/<City>/<Kind>/` | Experiences (restaurant/bar/club/activity/historic) with rating/would-return |
| people | `kb/People/<Name>/profile.md` | Relationship tracker; mentions filed as KB notes in the person's own folder |
| finance | `kb/Organisation/Finance/{Credit Cards,Stocks & Investments}/` | Credit cards and investment holdings, upsert-by-name with merge-on-partial-update |
| vault | `vault/` (sibling of `kb/`) | Scrypt+Fernet encrypted secrets store (passwords, API keys) with memory-only key and 300 s auto-lock |
| drop_router | (no storage) | Deterministic prefix routing + the three vision/text classification calls behind `/drop` |

Cross-node features in `api.py` itself: `/day/{date}` (everything that
happened on a date, deterministically), `/day/counts` (calendar badges),
`/drop` (the one general capture endpoint), `/graph` (full graph view data).
`sync.py` adds the manual LAN sync. `graph.py` is the edge engine.

### Frontend pages (`frontend/app/`)

Drop, Chat (KB chat with model picker), Browse (+ per-folder page with
scoped chat), Dashboard (habits + nutrition trends), Calendar (day view),
Journal, Todos, Documents, Wardrobe, Home, Travel, Finance (tabs + cards +
investments), People, Gallery, Profile, Batch import, Graph (d3-force),
Vault, Sync. Full map in [frontend.md](frontend.md).

### MCP tools (`core/quintacle_core/mcp_server/server.py`)

14 tools: `journal_append`, `journal_get`, `kb_list_folders`,
`kb_create_entry`, `kb_get_entry`, `kb_search_entries`, `log_expense`,
`expenses_in_range`, `todo_create`, `todo_update`, `todo_delete`,
`todo_list`, `list_recent_writes`, `undo_write`. Details, ledger format and
undo mechanics in [mcp-server.md](mcp-server.md).

### REST surface

114 routes across `api.py`, `sync.py`, and every `nodes/*/api.py` — the
complete inventory is [endpoints.md](endpoints.md).

### Tests

33 test modules under [core/tests/](../../core/tests/) covering stores,
ranking, quotas, nutrition targets, normalize, the drop router, graph,
experience/person linking, MCP server + undo, sync, vault, and every
structured domain.

## What is explicitly NOT built yet

Enumerated from the design docs' own follow-up sections, cross-checked
against the code:

- **Most of the MCP tool surface.** `docs/mcp-angle.md`'s full per-domain
  table (meals, ingredients, routines, food/substance/exercise/activity/
  body-stat logs, habits, cards/investments, documents, people, travel,
  wardrobe, grooming, home, profile, graph read tools, convenience
  drop/batch-drop tools) — only journal/KB/expenses/todos/ledger exist
  today. Binary asset transfer over MCP is an open question. The KB chat is
  deliberately excluded, permanently.
- **The "recent writes" frontend page and the 24 h undo-offer window.** The
  ledger and `undo_write` exist and work indefinitely; the UI that renders
  the ledger tail and stops *offering* undo past 24 h does not exist.
- **Remote MCP transport.** stdio only; no HTTP/SSE transport, no remote
  client story (ties into `docs/self-hosting.md`, all parked).
- **A compiled, installed APK.** The Capacitor project, static-export build,
  network security config, and Termux backend scripts all exist, but no
  `gradlew assembleDebug` has been run and nothing has been verified on a
  real device. See [android.md](android.md) for the exact remaining steps.
- **Deletion-propagating sync (tombstones).** Sync is additive-only v1:
  a file deleted on one device comes back on the next two-way sync.
- **Graph Stage 4** (a real graph database) and smarter-than-keyword link
  matching — `graph.py` is deliberately the Stage 1–3 bespoke system.
- **Hybrid FTS5 + sqlite-vec search.** `KBStore.search()` is a plain
  case-insensitive substring scan; the `architecture.md` amendment is the
  planned replacement.
- **Encrypted handling for vault-shaped documents.** Passports/licenses
  live in the Documents node under `kb/`, unencrypted and model-visible —
  `docs/vault.md`'s original security-first document store is NOT what got
  built (the built Vault is a secrets store instead). Flagged in
  `docs/mcp-angle.md` as a held-back decision.
- **On-device SLM / NPU inference, desktop pywebview shell, Chaquopy shell,
  self-hosting, multi-user** — all research/parked docs, zero code.
- **LLM narration of a day** ("what was I doing on X" as prose) — `/day/X`
  returns the structured data; nothing narrates it.
- The `_trash` top-level data-dir folder is reserved in sync's exclusion
  list but nothing in the codebase creates or uses it yet.

## Tech stack with versions

**Backend** (`core/requirements.txt` — mostly unpinned, latest-at-install):
Python 3.14 · FastAPI · uvicorn · pydantic · python-frontmatter · pytest ·
anthropic · python-dotenv · python-docx · python-multipart · Pillow ·
openpyxl · opencv-python-headless · openai · `mcp==1.30.0` ·
`cryptography==50.0.2`.

LLM models (`core/quintacle_core/llm_config.py`): `claude-haiku-4-5` default
for routine structured tasks (`QUINTACLE_LLM_MODEL`), `claude-sonnet-5` for
research-grade chat (`QUINTACLE_LLM_RESEARCH_MODEL`). Chat model picker also
offers `claude-opus-5`, `gpt-4o-mini`, `gpt-5-nano`, `gpt-5-mini`
(`nodes/kb/chat.py`); image generation uses `gpt-image-1-mini`.

**Frontend** (`frontend/package.json`): Next.js 16.3.4 · React 19.2.8 ·
Tailwind CSS 4 (+typography) · TypeScript 5 · lucide-react · react-markdown
(+remark-gfm, rehype-highlight) · d3-force · three / @react-three/fiber /
@react-three/drei (STL viewer) · mammoth (DOCX viewer) · Capacitor 8.5.3
(core/cli/android).

**Data**: markdown + YAML frontmatter (python-frontmatter), one SQLite file
(WAL mode), Fernet-encrypted blobs for vault entries.

## Map of this reference folder

| File | Covers |
|---|---|
| [architecture.md](architecture.md) | Processes, startup sequence, data directory layout, where LLM calls live, the Eastern-time clock |
| [endpoints.md](endpoints.md) | Every REST route (114), by domain |
| [data-and-db.md](data-and-db.md) | Markdown/frontmatter conventions, full SQLite schema, the two rebuild mechanisms |
| [graph-engine.md](graph-engine.md) | Edge files, the `edges` table, ID scheme, edge kinds, `link_new_entry`, re-sync, queries, consumers |
| [mcp-server.md](mcp-server.md) | Running/registering the server, all 14 tools, the ledger, undo, WriteSession, the structured-input rule |
| [vault.md](vault.md) | Crypto as implemented, lock lifecycle, API, the per-surface invisibility argument |
| [sync.md](sync.md) | Manifest/file/pull, exclusions, journal union-merge, LWW+snapshots, push-back, limitations |
| [drop-pipeline.md](drop-pipeline.md) | Prefix table, image/file classification, additive checks, batch drop, Drop-page session |
| [frontend.md](frontend.md) | Page map, `lib/api.ts`, `commitEntry`, UI kit, HUD theme, nav, date helpers |
| [android.md](android.md) | Capacitor project, Termux scripts, verified vs. unverified, remaining steps to an APK |
