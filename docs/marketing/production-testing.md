# Quintacle — Production Testing

Status: **marketing material, written 2026-11-05.** It covers every feature, every
fix from real-use testing, and how each one was tested. Every claim here traces to the
repo: [`docs/sprint-1-testing-fixes.md`](../sprint-1-testing-fixes.md),
[`docs/session-log.md`](../session-log.md), [`docs/reference/`](../reference/00-statement-of-work.md),
and the owner's hands-on test log. The founder's thesis and pitch live in
[`docs/pr-pitch.md`](../pr-pitch.md); this doc is the evidence behind it.

---

## Your whole life in one private graph. Small models that answer because the facts are already there.

Quintacle is a local-first personal life OS. Journal, todos, food, workouts, spending,
trips, photos, people, documents, projects and career all live as plain markdown files
plus one SQLite file **on your own disk**. Everything links into one knowledge graph.
Facts get written down and linked when you capture them (where a photo was taken, when
a PDF was created, which trip it belongs to). So when you ask a question later, a small
on-device model only has to read the answer back. It doesn't have to work it out.

### The headline numbers

| | |
|---|---|
| **989 automated tests passing** | 79 test modules. Every run uses throwaway data, and every model, web and subscription call is faked. The suite ran in 29 s on 2026-11-05. |
| **31 app pages, 24 apps in the drawer** | Chat, Browse, Calendar, Graph, plus Journal, Todos, Habits, Travel, Finance, Projects, Career, Knowledge, Household, Wardrobe, People, Documents, Gallery, Vault, Sync and more. |
| **Local by default** | Chat runs on Qwen3 8B on the computer and Qwen3 4B on the phone. Ingest parsing tries local first. Face and object recognition run on-device only. Search ranking is done in code (full-text plus optional local embeddings). |
| **Cloud only when you choose it** | One "Escalate ↗" or "Redo with cloud" press. The cloud tier is your Claude Max subscription, with automatic fallback to the API. |
| **24 MCP tools** | Claude (or any MCP client) can read and write your life. Every write is logged in one ledger and can be undone exactly. |
| **Phone parity, in code** | Same app as a static phone export, which builds clean with every page. On-device local model, face/object models, update scripts. *Honest edge: the APK isn't compiled yet and nothing has run on a real device.* |

---

## How we tested it

Quintacle isn't tested on demo data. It's tested the way it will be used.

### 1. Real-use testing on real files (the sprint method)

The owner uses Quintacle on his own files, logs every miss in a master test file, and
we fix the misses in sprints. Each sprint's fixes go in
[`docs/sprint-1-testing-fixes.md`](../sprint-1-testing-fixes.md), and old entries are
never rewritten.

- **Sprint 1, round 1 ("start testing travel").** A real 10-day Central Europe
  itinerary PDF (Budapest, Vienna, Salzburg, Prague) went in two ways: dropped through
  **Sort with AI**, and pushed via **MCP**. The local and cloud summaries were compared
  side by side. Seven issues surfaced and all seven were fixed the same day.
- **Sprint 1, round 2.** The NYC test: the same 5-day, 5-borough trip request went to
  the local model (Qwen3 8B) and to Claude. Then a chat answer was saved as an `.md`
  file with its pictures. Seven more bugs surfaced and were fixed, and nine features
  were built during the round.
- Every input and output is kept on disk for replay: the dropped PDF, the MCP-pushed
  PDF, the local plan with its 9 attached pictures, and the cloud plan with its 16.

### 2. The automated suite: 989 tests, zero real data

`cd core && QUINTACLE_DATA_DIR=$(mktemp -d) .venv/bin/python -m pytest -q` → **989 passed**.

| Rule | How it's enforced |
|---|---|
| **Never touches real data** | Experiments and the suite run against a sandboxed `QUINTACLE_DATA_DIR`. |
| **No real model calls** | `tests/conftest.py` switches off, for every test, local-model summaries, the vector lane, soft-record extraction, Claude Max (so a test never spends subscription usage) and web search (no network). Tests that cover a model seam swap in fakes. |
| **Model output is never evidence** | Model-quality checks have to run on seeded registries (meals, routines, people, places). An unseeded comparison counts as invalid. |
| **Phone-safe** | The full suite must pass without the optional heavy dependencies installed. A phone simulation (numpy/onnx/litert/cv2 blocked) ran green with 9 skips. |

What the 79 modules cover:

| Area | Test modules (examples) |
|---|---|
| Capture & drop | `test_drop.py`, `test_drop_router.py`, `test_drop_presets.py`, `test_drop_stock_habit.py`, `test_file_meta.py`, `test_photo_place.py`, `test_md_attach_images.py`, `test_statements.py` |
| Chat & memory | `test_chat_context.py`, `test_chat_modes.py`, `test_chat_mode_fixes.py`, `test_chat_models.py`, `test_chat_store.py`, `test_chat_my_photos.py`, `test_day_context.py`, `test_transcripts.py`, `test_web_search.py` |
| Graph & search | `test_graph.py`, `test_graph_capture.py`, `test_place_graph.py`, `test_trip_photos.py`, `test_event_links.py`, `test_retrieval.py`, `test_experience_person_linking.py` |
| Privacy | `test_private_notes.py`, `test_vault.py` |
| Local models & cloud tier | `test_llm_dispatch.py`, `test_local_vlm.py`, `test_local_vlm_llamacpp.py`, `test_perception.py`, `test_backend_tflite.py`, `test_max_backend.py` |
| Life domains | journal, logs, habits (versions + period), quotas, nutrition, meals, ingredients, routines, todos, ranking, travel, finance (accounts, insights, budgets, income, cards, stocks), documents, home, wardrobe, grooming, people, projects, business ideas, career, knowledge |
| MCP | `test_mcp_server.py`, `test_mcp_undo.py`, `test_mcp_attach_income.py` |
| Reliability | `test_db_concurrency.py`, `test_sync.py`, `test_normalize.py` |

### 3. Live verification

- **Real browser.** The owner tests in Chrome every day. Bugs he reports get chased
  through backend logs and checked again in Chrome before they're closed.
- **Headless screenshots at phone and desktop widths.** Every new page (dashboard,
  Finance, Projects, Business ideas, Knowledge, Overview) was screenshotted at 390 px
  and at 1400–1440 px against a sandboxed backend. The dashboard was checked for
  horizontal scroll and has none. One phone overflow was caught and fixed.
- **Phone build.** `CAPACITOR_BUILD=true next build` exports every page as static
  files, and `cap sync android` succeeds.
- **Live model checks.** Claude Max answered chat in 1.5 s and a cloud drop in 7 s, with
  zero fallbacks. Earlier live checks: a face enrolled once matched a different day's
  photo at 0.803 similarity, on-device, and a local photo description took 0.79 s.
- **Type safety.** Frontend `tsc` reports 0 errors on every round.

### 4. The honest bits

We write down what failed, because that's why the rest is believable.

- The **local 8B model made up booking IDs** in the NYC test (details in the
  showdown below). That's a model limitation, and it's the reason Quintacle has
  escalation and review-before-save.
- **Claude's corrected note cut off around Day 3**, so its full answer had to be saved
  over it.
- **"Failed to fetch" in Browse couldn't be reproduced.** Backend logs showed every
  request succeeding. The fix is a process fix: warn before restarting the backend
  during testing.
- **3D STL previews rendered black in headless screenshots.** They still need a check in
  a real browser.
- **PDF metadata noise** is logged and still open.
- **Photo descriptions are cloud-by-default**, and so are image classification and
  receipt extraction. Those vision-plus-schema tasks deliberately stay cloud for now.

---

## Feature catalog

Each entry covers what it does, what makes it different, and **Tested by**.

### Capture & sorting

| Feature | What it does | Why it's different | Tested by |
|---|---|---|---|
| **One capture box (Sort with AI)** | Drop text, photos, PDFs or Office files into Chat. Quintacle proposes where each goes and what it is, and nothing saves until you review it. | Prefix routing and preset matching happen in code, so models only propose. Text files (md, txt, csv, json, yaml, html, code) are read at drop. | `test_drop*.py`, `test_drop_router.py`; owner dropped the Central Europe PDF and a chat-answer `.md` |
| **Smart folders** | The sorter reuses a matching folder, or creates a subfolder for a new group. Itineraries, tickets and bookings go to `Fun/Travel/Planned/<Region>`. "Someday" places go to `Fun/Travel/Bucket List`. | Folders grow with your life, so you don't end up with one flat Travel pile. | Owner's Austria itinerary re-drop |
| **File facts written down at drop** | PDF title, author, created date and page count; Office metadata; camera and size; video duration, date and GPS. All read **without a model**, shown on the review card, and written into the note as a searchable line. | The document's created date links it to that day's journal automatically. | `test_file_meta.py` |
| **Photo location you can search** | Every photo save writes a visible 📍 line with city, country, continent, coordinates and capture time. Searching "Vienna", "Austria" or "Europe" all find it. | One cached lookup per place, not one per photo. Private photos never send coordinates to the cloud. | `test_photo_place.py` |
| **Attachments that come along** | Save a chat answer as `.md` and its web pictures are downloaded and your own photos copied into the note's folder. | Notes are self-contained and don't depend on hotlinks. Verified 30/30 images on the NYC itinerary. | `test_md_attach_images.py`; owner's NYC save |
| **Batch import** | Drop many files, review the proposed buckets, reassign them, then commit. | Same review gate as single drops. | No dedicated test module yet; covered by the shared drop/save path |
| **Statement import** | Drop a PDF or photo of a statement to import transactions. | The only model call is the transcription. All the arithmetic is code. | `test_statements.py` |
| **Redo with cloud** | If the local parse is weak, re-run it on a cloud model. | It starts again from your **original input** instead of re-prompting over the local output. | `test_llm_dispatch.py` |

### Chat & memory

| Feature | What it does | Why it's different | Tested by |
|---|---|---|---|
| **Grounded chat** | Ask your life questions. Context is built per turn from search hits, the "About me" block, and full day records when you mention a date. | Live facts (PRs, this month's spend and savings rate, latest body stats) are computed in SQL and given to the model as finished numbers. | `test_chat_context.py`, `test_day_context.py` |
| **Local default, escalate on demand** | Chat defaults to a free local model. "Escalate ↗" re-sends the same conversation to a cloud model. | The context transfers as-is, so you never retype anything. Escalating is always your choice. | `test_chat_models.py` |
| **Chats always save** | Every reply autosaves into one transcript, with a final save when you leave. Incognito saves nothing. | Fixed in round 2. Before that, leaving or refreshing lost the chat. | `test_chat_store.py`, `test_transcripts.py` |
| **Your own photos in chat** | "Show me photos from Vienna" shows **your** photos inline. If a weak model forgets, a fallback gallery appears. | Unknown photo handles get dropped, and cloud models never see private photos. | `test_chat_my_photos.py` |
| **Web lane for local models** | 🌐 auto / on / off. Code searches and fetches the top pages, and the model reads and cites them. | Only the search query leaves your machine. It uses real search APIs (Brave, or self-hosted SearXNG), and if none is configured it says so instead of failing silently. | `test_web_search.py` (no network) |
| **Chat modes + "Record that"** | Casual and serious modes. "Record that" turns a chat fact into a note after you review it. | Links in replies are checked against real notes, and a soft record keeps dated facts. | `test_chat_modes.py`, `test_chat_mode_fixes.py` |
| **Transcript archive** | Raw transcripts are filed verbatim with zero model calls, and default search can't see them. | You only dig into them when you ask to. | `test_transcripts.py` |

### Graph & search

| Feature | What it does | Why it's different | Tested by |
|---|---|---|---|
| **The life graph** | Notes, journal days, people, places, experiences, events, photos and files, connected by typed edges. Shown as a 2D or 3D graph. | Edges come from code, not from a model. Each one is a markdown file you can read and rebuild. | `test_graph.py`, `test_graph_capture.py`, `test_event_links.py` |
| **Place hierarchy** | Photo / experience / trip → city → country → continent. | "Photos from Europe" works by following links, so a weak model can answer it. | `test_place_graph.py` |
| **Trip ↔ photos** | Photos taken during a planned trip's dates and in its destinations attach to the plan automatically. | Matched on EXIF date and place, with no model call. | `test_trip_photos.py` |
| **Files hub** | Attached PDFs and documents get their own hub, separate from Photos. | Fixed in round 1. Before that, PDFs were labelled "Photos". | graph tests |
| **One search over everything** | Ranked search across notes, days, people, places, todos, every log row and every preset. | Full-text plus optional local embeddings, merged in code. No language model in the query path. | `test_retrieval.py` |
| **Day recall** | Everything that happened on a date: journal, logs, todos, events, people, places. | Pure code. Also available over MCP. | `test_day_recall.py` |

### Privacy & local-first

| Feature | What it does | Tested by |
|---|---|---|
| **Private notes** | `private: true` notes never reach a cloud model or MCP. Local chat can use them, and you always see them. | `test_private_notes.py` |
| **Cloud handoff stripping** | When you escalate a chat that used private notes, those turns are removed and you're told how many ("N private notes were left out of the cloud handoff"). | `test_private_notes.py` |
| **Vault** | A passphrase-encrypted secrets store kept outside the knowledge base on purpose, so no AI surface can see it. The key lives only in memory and auto-locks after 300 s. | `test_vault.py` |
| **On-device faces** | Enroll a face once and it's recognized from then on. Embeddings never leave the local perception folder. | `test_perception.py`, `test_auto_journal.py` |
| **Local-first ingest** | Parsing tries the local model first and falls back to cloud only on failure. Search summaries are pinned to local and never make a cloud call behind your back. | `test_llm_dispatch.py`, `test_retrieval.py` |

### Life pages

| Page | What it does | Tested by |
|---|---|---|
| **Dashboard** | Your landing page, built from widgets: Today (due/overdue todos, today's logs), goal rings with pace, productivity hours by category, 60-day weight, food, spend, connections, recent. A deterministic Brief, so no model writes your morning. | `test_body_stats_read.py`, `test_overview_recent.py`; screenshots at 390 / 1400 px |
| **Calendar** | Month view with badges for todos due and entries logged. Any day expands into its full record. | `test_day_recall.py` |
| **Habits & goals** | Weekly targets that repeat until you change them. A change takes effect next period and history is kept. Periods are normalized ("weekly" → week), and invalid ones are rejected. | `test_habit_versions.py`, `test_habit_period.py`, `test_quotas.py` |
| **Journal** | The nightly dump. Saved verbatim, then optionally parsed into structured entries for review. "Did pull day at the gym" expands to your full workout preset in code. Photos write their own journal lines (undoable). | `test_journal_store.py`, `test_routines.py`, `test_auto_journal.py` |
| **Todos** | Ranked list with priority, due date and time window. Ranking is deterministic. | `test_ranking.py`, `test_todo_completion.py` |
| **Travel** | Three tabs. Experiences (rated, would-return). Planned (itineraries grouped by region with dates, destinations and photo thumbnails, plus "Move to Planned" that brings attached files along). Bucket list (ticks "Visited" by itself once you log an experience in that city). | `test_travel.py`, `test_travel_states.py`, `test_trip_photos.py` |
| **Finance** | One page with Overview, Accounts (balance history, net worth with no double counting), Investments, Spend & budgets, Subscriptions and Income. Every number is computed in code. | `test_finance_accounts.py`, `test_finance_insights.py`, `test_budget_lines.py`, `test_income.py`, `test_stocks.py`, `test_credit_cards.py` |
| **Projects** | Doing / Planned / Done cards with cover image or rotating STL, stack chips and GitHub link. The detail view shows models, images, PDFs, videos, notes, work-log days and graph neighbours. | `test_projects_page.py` |
| **Business ideas** | Status board (idea → exploring → validating → building → parked/dropped). Each idea shows every file type: notes, images, video, STL, PDF/Office previews. | `test_business_ideas.py` |
| **Career** | Website-style timeline of orgs, roles, contracts and education, with work-log day counts and 12-month sparklines. **Career updates** drafts record entries from your work logs (local-first), fact-checks numbers, dates and titles in code, then saves after your review. | `test_career_timeline.py`, `test_career_updates.py` |
| **Knowledge** | Card grid with topic and tag filters that update as you add new folders and tags. Nothing is hard-coded. Includes a reader view with related notes from the graph. | `test_knowledge_page.py` |
| **Household** | Residences over time and an item inventory for each one. | `test_home.py` |
| **Wardrobe** | Clothing items described from photos, outfits, and a suggest-outfit composer. Grooming products and routines sit alongside. | `test_wardrobe.py`, `test_grooming.py` |
| **People** | Relationship rosters. Mentions are filed in the person's own folder, and "Appears in" is computed from the graph. | `test_people.py`, `test_experience_person_linking.py` |
| **Documents** | Typed documents (lease, ID, insurance) with multi-page scans and expiry countdowns. A renewal todo is created automatically on the expiry date. | `test_documents.py` |
| **Gallery** | Your photos grouped by year and month. | `test_photo_organizer.py` (photo folder naming) |
| **Food & nutrition** | Meal and ingredient presets, composed meals with totals computed in code, and targets matched to your sex and age. | `test_meal_presets.py`, `test_meal_composer.py`, `test_ingredients.py`, `test_nutrition_targets.py`, `test_profile_targets.py` |

### Integrations

| Integration | What it does | Tested by |
|---|---|---|
| **MCP server (24 tools)** | Claude reads and writes your life: journal, notes, search, file attach, expenses, income, work logs, stock transactions and positions, todos, events, day recall, photo describe/perceive. Writes apply right away, and each push is one ledger entry with **exact undo**. Private notes look missing over MCP. | `test_mcp_server.py`, `test_mcp_undo.py`, `test_mcp_attach_income.py`; owner pushed the Central Europe PDF via MCP |
| **Claude Max** | Your Max subscription is the cloud tier for every cloud call on the computer. Any failure falls back to the API, and the phone falls back automatically. Chat offers Max Haiku / Sonnet / Opus. | `test_max_backend.py` (fake CLI); live: chat 1.5 s, cloud drop 7 s |
| **TailorCV** | Career updates write into the master career record in TailorCV's format. In a read-only dry run, TailorCV still parsed the output. | `test_career_updates.py` |
| **Personal website** | Approved, public-only career and project changes are committed to a new content branch in your website repo. Never pushed, and the working checkout is never touched. | `test_career_updates.py` |
| **Device sync** | Two devices sync over plain wifi: journals merged, snapshots protect overwrites, and no cloud in between. | `test_sync.py` |

### Phone

| What | Status |
|---|---|
| Static export of every page | **Builds clean.** `cap sync android` OK |
| On-device chat | Qwen3 4B via Termux Ollama, with automatic cloud fallback if the daemon is down |
| On-device faces and objects | TFLite runtime in stock Termux, no proot |
| Cloud tier on the phone | Straight to the API (no Claude CLI), no error |
| Update / perception / Max setup scripts | Written (`scripts/termux/`) |
| APK | **Not built yet.** Needs JDK 21 + Android SDK 36. Nothing has run on a device |
| Not on the phone | MCP server, website branch commits, video-frame captioning |

---

## Bugs we caught in production testing

All from Sprint 1 (2026-11-05). The commit is on branch `redone-UI`.

| # | Symptom | Cause | Fix | Status |
|---|---|---|---|---|
| 1 | Browse: "Failed to fetch" opening notes | A tab opened before backend restarts kept failing. Backend logs showed every request succeeding | Reopening the tab fixes it. Process fix: warn before restarting the backend during testing | Not reproducible in Chrome; process fix in place |
| 2 | MCP not connected in Claude Code | The server wasn't registered | Registered for all Claude Code sessions (owner-approved) | Fixed |
| 3 | Sorter wouldn't make subfolders: an Austria itinerary landed in flat `Fun/Travel` | Placement prompts didn't allow new subfolders | Reuse a matching folder first, create one for a new group, route trip docs to `Planned/<Region>` | Fixed (`c154f07`) |
| 4 | Travel tab showed only experiences | No planned or someday states | Experiences / Planned / Bucket list tabs, "Move to Planned", automatic "Visited" | Fixed (`8b83c4a`, `c154f07`) |
| 5 | Experiences listed non-trip folders as cities | Every `fun/travel` folder counted as a city | Skip `planned`, `bucket-list`, `assets` | Fixed (`c154f07`) |
| 6 | Graph labelled PDFs as "Photos" | All attachments were treated as images | Images stay under Photos, documents get a Files hub | Fixed (`31f8f20`) |
| 7 | Photo location wasn't searchable | GPS only lived in hidden metadata | Visible 📍 line written into every photo note, plus a backfill | Fixed (`396092e`) |
| 8 | Chats weren't saved unless you clicked "New chat" | Saving only ran on that button | Autosave after every reply into one transcript, plus a save on leave | Fixed (`91f322f`) |
| 9 | A chat answer saved as `.md` reached the sorter as "no description given" | Text files weren't read at drop | md/txt/csv/json/yaml/html/code now read | Fixed (`5d4bdf0`) |
| 10 | Pictures in a saved chat answer weren't attached | Image links inside the `.md` were ignored | Web pictures downloaded, own photos copied into the note folder | Fixed (`109ebc3`) |
| 11 | Browse showed those pictures as broken | Note-relative `assets/…` paths didn't resolve | Load from the note's own folder. Verified 30/30 on the NYC itinerary | Fixed (`fc771f9`) |
| 12 | Random "couldn't load" on busy pages (phantom "no habit with id") | Concurrent requests shared one SQLite connection | Every statement serialized on that connection | Fixed (`5d4bdf0`) |
| 13 | A goal saved as "weekly" broke every progress read | Only `day/week/2weeks/month` were valid | Periods normalized, invalid ones rejected at save | Fixed (`5d4bdf0`) |
| 14 | Local web search silently found nothing | DuckDuckGo blocks scripted requests | Real search APIs (Brave or self-hosted SearXNG). If none is configured, it says so | Fixed (`27095e7`) |
| 15 | Local model invented booking IDs (NYC test) | An 8B model filling a request it can't actually fulfil | Not a code bug. Escalation + review-before-save; the cloud model flagged and corrected it | By design: escalation |
| 16 | PDF metadata noise | — | Noted | Open |

Earlier rounds (2026-10-27 live re-verification) caught two more: serious-mode's "no
match" short-circuit never fired on real stores, and routine suggestions kept set
schemes in exercise names ("Bench Press 4x8"). Both were fixed.

---

## Local vs cloud: the NYC showdown

**The ask** (verbatim, typed by the owner):

> alright plan a new york trip 2027 5 days all 5 boroughs with hotel recommendations and
> travel from dc what to see everything just plan it attach photos for reference give me
> tickets and booking ids and everything

**The local model (Qwen3 8B, free, on-device)** gave a full 5-day plan in seconds,
covering all five boroughs, with hotels, transport and pictures. It looked great at a
glance. Then:

- It **made up booking IDs** ("ID: 2882120", "ID: 78901", a Delta "flight tracker" ID).
- It put **Coney Island in Queens** and suggested a **train to Staten Island**.

**Claude (cloud, by choice)** got the same question. It noticed the earlier answer was
already in Quintacle, linked both saved notes, and then:

- **Refused to fabricate:** "A confirmation number only exists after you pay, and any
  number I gave you would be made up."
- **Corrected the facts:** Amtrak over flying, one hotel for the stay instead of
  switching daily, the free Staten Island Ferry, and boroughs on the right days.
- Replaced fake IDs with a **"what to book, where, and when"** table.
- Recommended **deleting the bad note**, and pointed out that its own corrected note cut
  off around Day 3.

**Why this matters, and why Quintacle is built the way it is:**

1. **Local is the default, cloud is one press away.** Small models handle the everyday
   stuff for free. When an answer matters, "Escalate ↗" sends the *same* conversation to
   Claude, so the context carries over and nothing is retyped.
2. **Nothing a model writes lands without you.** Every in-app save goes through review,
   so a hallucinated booking ID never quietly becomes "truth" in your life record. MCP
   writes apply right away but can always be undone.
3. **Memory makes the big model better too.** Claude could see the earlier plan because
   Quintacle had saved it, so its answer was a fix of a known note instead of a blind
   redo.
4. **Facts beat model size.** The 8B model failed exactly where it had no stored facts
   (bookings that don't exist). Where Quintacle has the facts written down and linked
   (your photos, your trips, your days), a small model only has to read them back.

---

## Privacy promises (exactly what we promise, nothing more)

**Stays on your machine:**

- All your data: markdown files plus one SQLite file in your data folder. No Quintacle
  account and no hosted server; the backend runs on your own machine.
- Face embeddings, always. Face matching is on-device.
- The Vault: encrypted (scrypt + Fernet), kept outside the knowledge base, and invisible
  to search, the graph, MCP, chat and drop. Its key is held in memory only and it
  auto-locks after 300 s.
- **Private notes** (`private: true`): never sent to a cloud model, never visible over
  MCP, and never geocoded. Local chat may use them.
- Transcripts and the soft record: outside the search index, the graph and MCP.

**What can leave, and when:**

| What | When |
|---|---|
| A cloud model call (Claude Max, or the API as fallback) | When you escalate, choose "Redo with cloud", or pick a cloud model. Local ingest also falls back to cloud if the local model fails. Private notes are stripped first, and you're told how many. |
| Photo descriptions, image classification, receipt extraction | **Cloud by default today** (this vision work hasn't moved local yet). A local vision backend can be switched on. |
| Photo coordinates for place names | One cached lookup per ~100 m spot, for non-private photos only. |
| A web search query | Only when the web lane runs (auto, or you turn it on). Only the query leaves, never your notes. |
| Pictures downloaded for a saved note | When a saved answer links web images. |

**Known gap, stated plainly:** formal documents (ID, lease, insurance) live in the
Documents page inside the knowledge base, not in the encrypted Vault. Mark sensitive
ones private to keep them away from cloud models and MCP.

---

## What's next

From the sprint doc's open list:

- [ ] **Phone install.** Install JDK 21 + Android SDK and build the APK, then install →
      sync test → wipe the store → redo for real (after backing up the real store).
- [ ] **Push `redone-UI` to GitHub** so the phone can pull. Merge TailorCV `record-sync`.
- [ ] **Stocks discusser.** Talk through the stocks you follow (news, hunches, a
      watchlist) on top of the simplified Investments page. The placeholder card exists.
- [ ] **Feature map.** One map of every feature: where it lives, what it links to,
      whether it's tested. This doc is the marketing view of it.
- [ ] **PDF metadata noise** cleanup.
- [ ] **STL previews** checked in a real browser.
- [ ] Sprint 2: the owner keeps testing on real files. Each miss gets logged and fixed,
      and every fix lands with a test.

---

*Search once. Store forever. Retrieve for free.* More voice and the founder's thesis are
in [`docs/pr-pitch.md`](../pr-pitch.md).
