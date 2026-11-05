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

## Sprint 1 — in progress

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

## Open (carry to sprint 2)

- Trip ↔ photos link (photos taken during a plan's dates/destinations attach to it).
- Chat shows your own photos inline (today it only shows Wikipedia images).
- Push `redone-UI` to GitHub (needed before the phone can pull); merge TailorCV
  `record-sync`; install JDK 21 + Android SDK for the APK.
- Phone install → sync test → wipe store → redo for real (back up `~/.quintacle` first).

## To do later

- **Feature list.** A single map of every feature: where it lives, what it links to,
  tested or not. Build from the code + `docs/reference/` once testing settles.
