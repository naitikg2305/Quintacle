# Sprint 1 — real-use testing fixes (started 2026-11-05)

Owner started hands-on E2E testing on 2026-11-05 (travel itineraries via drop,
in-app Claude chat, in-app local chat, and an MCP push). This file is the running
list of what testing surfaced and what was fixed, one sprint at a time. Later
sprints get their own section below; never rewrite a past sprint's entries.

## Sprint 1 — fixes (from "start testing travel")

- **Browse: "Failed to fetch" opening notes.** A tab opened before backend
  restarts kept failing; reopening the tab fixed it (backend logs showed every
  request succeeding; not reproducible in Chrome). Process fix: Claude warns
  before restarting the backend during testing.
- **MCP not connected.** Quintacle MCP registered for all Claude Code sessions
  (`claude mcp add quintacle -s user`, owner-approved; legacy-mode hold lifted for
  registration only).
- **Sorter wouldn't make subfolders.** An Austria itinerary landed in `Fun/Travel`
  instead of a trip folder. Placement prompts now allow a new subfolder for a
  distinct group, reuse a matching one first, and route future-trip docs
  (itineraries, tickets, bookings) to `Fun/Travel/Planned/<Region>` and "someday"
  places to `Fun/Travel/Bucket List`.
- **Travel tab only showed experiences.** Now three tabs: Experiences / Planned /
  Bucket list. Planned groups itineraries by region with dates + destinations;
  existing itineraries in `Fun/Travel` get a "Move to Planned" action (moves
  attached files too). Bucket-list places tick "Visited" automatically when an
  experience in that city exists.
- **Experiences picked up non-trip folders.** The experience store treated every
  folder under `fun/travel` as a city; now skips `planned`, `bucket-list`, `assets`.
- **Graph labelled PDFs as "Photos".** Attached files are split: images stay under
  Photos, PDFs/documents get a Files hub.
- **Photo location wasn't searchable.** GPS lived only in hidden metadata. Every
  photo save (single drop, batch, MCP attach) now bakes a visible
  `📍 City, Country · Continent · coords · taken …` line into the note, so
  "Vienna" / "Austria" / "Europe" all find it; cached geocoding (one lookup per
  place); private photos never send coordinates to the cloud; backfill endpoint.

## Sprint 1 — round 2 (later on 2026-11-05)

### Fixes
- **Chats weren't saved unless you clicked "New chat".** Leaving, refreshing or a
  backend restart dropped the conversation, so nothing was remembered. Now every chat
  autosaves after each reply into ONE transcript (session id) plus a final save on
  leave; Incognito still saves nothing. Home's Assist panel too.
- **Markdown/text files weren't read at drop** — a chat answer saved as `.md` reached
  the sorter as "no description given". md/txt/csv/json/yaml/html/code are now read.
- **Images in a chat answer saved as an `.md` attachment weren't attached** — web
  pictures are now downloaded and your own photos copied into the note's folder.
- **Browse showed those images as broken** — note-relative `assets/…` paths now load
  from the note's folder (verified 30/30 on the NYC itinerary).
- **Random "couldn't load" on busy pages** — concurrent requests shared one SQLite
  connection and failed (`InterfaceError` / phantom "no habit with id"). Every
  statement is now serialized on that connection.
- **A goal saved with period "weekly" broke forever** — periods are normalized
  (weekly→week, bi-weekly→2weeks…) and invalid ones rejected at save.
- **Local web search silently found nothing** — DuckDuckGo blocks scripted requests.
  Switched to real search APIs (Brave key or self-hosted SearXNG); explicit Web-on with
  no key now says so instead of failing silently.
- **Graph labelled PDFs as "Photos"** (round 1 tail) and **PDF metadata noise** noted.

### Features built during testing
- Place graph: photo/experience/plan → city → country → continent ("photos from Europe").
- File metadata (PDF/Office/video/photo) read deterministically at drop; created date
  links documents to that day's journal.
- Trip ↔ photos: photos taken during a plan's dates + destinations attach to it.
- Chat shows your own photos inline (with a fallback gallery for weak models).
- Local web search lane (🌐 auto/on/off) for local/Bedrock models.
- New navigation: dashboard landing (widgets: today, goal rings, productivity, weight,
  food, spend, connections), core rail (Chat/Browse/Calendar/Graph), ⊞ Apps drawer.
- New pages: Projects, Business ideas, Career (timeline; updaters moved to
  /career/updates), Knowledge (dynamic folder/tag filters), unified Finance (accounts with
  balance history, net worth, investments, budgets, subscriptions, income).
- Patent: invention disclosure draft (`docs/patent/`).
- Real nutrition numbers: an offline USDA FoodData Central db (Foundation + SR Legacy,
  6.7 MB, one-tap install) is now the source for ingredient presets, the meal composer
  and the Day view. A model may only pick which USDA entry a food is, never a number.
  Adds omega-3s (ALA/EPA/DPA/DHA), omega-6, carotenoids, flavonoid classes (when mdbtools
  can read the Access-only flavonoid db), the omega-6:omega-3 ratio and per-ingredient
  contributions. A chat lane hands the model USDA facts for foods named in chat.
  See `docs/reference/nutrition.md`.

### Not code (owner's repos)
- Repo-slimming attempt reverted by owner decision: repos stay as-is (to be stored whole);
  every `main` verified identical to GitHub; local `slim-repo` branches remain unused.

## Sprint 1 — in progress (round 1 — since built)

- **Place hierarchy in the graph.** Photos, experiences and trip plans link to
  city → country → continent nodes, so weak/local models answer "photos from
  Europe" by following links.
- **File metadata baked at drop.** PDF/DOCX/XLSX/PPTX/video/photo metadata (title,
  author, created date, pages, camera, duration…) read deterministically, shown on
  the review card, baked as a searchable `🗂` line; created date links documents to
  that day's journal.

## Built alongside testing (features, not fixes)

- Claude Max subscription as the cloud tier everywhere on the computer (API fallback;
  phone falls back automatically).
- Phone parity: on-device local model (qwen3:4b), face/object models via Termux
  TFLite, update script; APK build pending JDK 21 + Android SDK.
- **2026-11-06 — photos are local-first** (owner: "it should always have been
  local … YOLO plus OCR"). Every image call (photo-kind classification,
  receipts, nutrition labels, wardrobe/grooming/outfit/document photos,
  statement photos, video frames) now runs OCR + deterministic parsers →
  local text model over the OCR text → YOLO + local VLM, and never the cloud
  automatically (`QUINTACLE_IMAGE_PROVIDER=local`). An unreadable photo
  shows "couldn't read locally — Redo with cloud?"; review cards show a
  "read locally" badge. Needs `pip install -r core/requirements-ocr.txt`
  (or tesseract + its English data) on the desktop; phone:
  `setup-perception.sh --ocr`. See `reference/perception-and-autojournal.md`.

## Testing — regression checks from the owner's testing (2026-11-07)

Owner: "what if you add tests according to what I tested". There are now two layers:

- **`core/tests/test_owner_scenarios.py`** replays each journey he verified by hand as one end-to-end test through the real app. It uses synthetic stand-ins: a hand-built PDF, PIL-drawn label and receipt images, and a short markdown chat answer. Local models are stubbed at `llm_dispatch` and the cloud raises.
  - Itinerary PDF drop → travel rule in the sort prompt → `Fun/Travel/Planned/<Region>` → Travel › Planned, with the 🗂 line and the PDF served.
  - Loose itinerary → Move to Planned (the PDF moves with it).
  - MCP create + attach PDF → ledger, 🗂 line, place edge, two-step undo.
  - Chat answer `.md` drop is read, then saved with web and own images, and every path loads via `/kb/asset`. A `.txt` drop is read the same way.
  - Label photo → OCR+parser, exact macros, USDA profile backtrack and USDA backfill.
  - Receipt photo → merchant, date and total from the parser.
  - Trip photo → 📍 line, place hierarchy, and a `during_trip` link to the plan.
  - Chat autosave keeps one transcript per session, and the day bundle shows chats, work log, notes and income.
  - A private itinerary is invisible to MCP.
  - A goal saved as "weekly" is normalized.
  - Already-covered behaviours are referenced in the module docstring, not duplicated.
- **Golden check on his real files** lives outside the repo, in the testing folder (`.tools/golden_run.py`, how-to in that folder's README). It re-drops every real input on a temp data dir as proposals only and compares the result with the recorded `.tools/golden/*.json`. Structural fields are strict (types, pipeline, folder root, parser/USDA numbers). Model wording is shown but never fails. Cloud is blocked unless `--allow-cloud`.

## Open (carry to sprint 2)

- Trip ↔ photos link (photos taken during a plan's dates/destinations attach to it).
- Chat shows your own photos inline (today it only shows Wikipedia images).
- Push `redone-UI` to GitHub (needed before the phone can pull); merge TailorCV
  `record-sync`; install JDK 21 + Android SDK for the APK.
- Phone install → sync test → wipe store → redo for real (back up `~/.quintacle` first).

## To do later

- **Stocks discusser** (owner, 2026-11-05): a page to discuss what's going on with
  stocks he follows (e.g. Rivian) — recorded news, hunches, a watchlist — on top of the
  simplified Investments page (holdings he actually owns). Placeholder card exists.

- **Feature list.** A single map of every feature: where it lives, what it links to,
  tested or not. Build from the code + `docs/reference/` once testing settles.
