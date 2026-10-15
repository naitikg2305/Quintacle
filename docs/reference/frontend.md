# The frontend

Derived from code at commit `884d057` on 2026-10-15.

Next.js 16 (App Router, all pages `"use client"`), React 19, Tailwind 4.
Everything lives under [frontend/](../../frontend/): `app/` (pages),
`lib/` (API client + shared logic), `components/` (shared views + UI kit).
Mid-redesign note: the HUD restyle (branch `redone-UI`) was paused
mid-Phase C — theme tokens and AppShell are done; not every page is
restyled yet (the `globals.css` base rules deliberately make unstyled pages
read correctly on the dark background).

## Page map (`frontend/app/`)

| Route | One line |
|---|---|
| `/` | Landing: the five core surfaces as glowing cards + quick links |
| `/kb/drop` | **Drop** — the one capture box: text (prefix-routed), up to two photos/files, review/edit proposed entries, commit; "Still going" session keeps extending the last note ([drop-pipeline.md](drop-pipeline.md)) |
| `/kb` | **Chat** — KB-grounded chat: model picker (`/kb/models`), whole-KB or KB-off, photo/PDF attachments, saved scratch sessions, generate-image, push-to-KB via `/kb/sort` |
| `/kb/browse` | **Browse** — folder tree, entry reading/editing, per-folder views (list/gallery/cards/table), asset viewers (image lightbox, DOCX, STL, spreadsheet editor), search |
| `/kb/folder` | A single folder's page with its folder-scoped chat (`?folder=` param; chat context limited to that subtree) |
| `/kb/batch` | **Batch import** — multi-file drop, review AI-proposed buckets, reassign/edit, commit per file |
| `/kb/graph` | **Graph** — d3-force rendering of `/graph` (typed node colors, drag/zoom) |
| `/habits` | **Dashboard** — habit/quota progress + history bars, nutrition trend (kcal/protein vs. `/profile/targets`) |
| `/day` | **Calendar** — month view with Regular (todos due) / Action (logged-entry counts) badges; a day expands to the full `/day/{date}` detail |
| `/journal` | The nightly dump: save verbatim, optionally parse into structured entries, review and commit (per-entry `entry_date` wins over the page date) |
| `/todos` | Ranked todo list + add/complete/delete |
| `/documents` | Document Vault: typed documents, expiry countdowns, multi-page scans |
| `/wardrobe` | Items + outfits, photos, suggest-outfit composer |
| `/home` | Residences + per-residence item inventory |
| `/travel` | Experiences by city/kind with rating/would-return |
| `/finance` | Spending by `kind` tabs (Subscriptions/Food/Alcohol/…) over `/logs/expenses` |
| `/finance/cards` | Credit cards (upsert forms) |
| `/finance/investments` | Investment holdings |
| `/people` | Friends and Dating as two separate rosters (others collapsed), person folders link into Browse |
| `/gallery` | `Media/Photos` grid from `/kb/photos`, grouped by year/month |
| `/profile` | Height/sex/birthdate/activity level/home countries + computed targets |
| `/vault` | Vault: init/unlock/lock, entry list (no secrets), per-entry reveal/edit/delete, auto-lock countdown |
| `/sync` | Peer address, Pull / Two-way buttons, readable sync report |

## `lib/api.ts` — the single API surface

Every backend call in the app goes through this one file (~1100 lines): a
typed function per endpoint plus the shared TypeScript types (`Todo`,
`ParsedEntry` union of all 22 entry types, `KBEntryFull`, `GraphNode`,
`SyncReport`, …). `API_BASE = NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"`.
The generic `request<T>()` helper does JSON + error-text propagation;
multipart uploads (drops, item/document/outfit creation, asset attach/
replace) bypass it with raw `fetch` so the browser sets its own multipart
boundary. Also here: `buildChatMessage` (file → Anthropic content blocks,
images + PDF only), `chatMessageText`, `formatSets`, `base64ToFile`.

No component fetches directly; pages import from `lib/api.ts` only — which
is also why the endpoint inventory in [endpoints.md](endpoints.md) and this
file agree one-to-one.

## `lib/entries.ts` — `commitEntry` dispatch

The shared commit layer for Journal parse and Drop (both produce the same
`ParsedEntry` union): `commitEntry(date, entry, assets)` switches on
`entry.type` and calls the right create/log function — activities/food/
exercise/substances/body-stats/expenses (with `entry.entry_date ?? date`,
so a multi-day dump splits across the right days), todos, KB entries
(`pushKBEntry` or `pushKBEntryWithAsset` when files ride along),
ingredient presets, composed meals (new ingredients created first),
routines, wardrobe/grooming items (+photos), outfit/grooming compositions
(new components created first so names match), outfit photos (photo IS the
record), documents (every scanned page attached), home items, residences,
experiences, people, credit cards, investments. `BLANK` provides an empty
template per type for the "add one manually" flows.

## UI kit (`components/ui/`)

Five primitives, HUD-styled: `Panel` (bordered surface with mono uppercase
title), `Button` (variants incl. `primary` accent glow), `Field`
(label+input), `Segmented` (tab strip), `BottomSheet` (phone modal). Shared
feature components in `components/`: `AppShell`, `EntryCard` (review/edit a
ParsedEntry), `ChatLog`/`ReadOnlyChat`, `FolderView`, `ImageLightbox`,
`DocxViewer` (mammoth), `STLViewer` (three.js), `SpreadsheetEditor`,
`MealCompositionEditor`, `OutfitEditor`, `GroomingRoutineEditor`,
`ScribblePad`.

## HUD theme conventions (`app/globals.css`)

Dark-only "HUD" look. Tokens are Tailwind-4 `@theme` variables consumed as
utilities: `bg-background` `#05080f`, `bg-surface` `#0a111d` /
`bg-surface-2`, `text-foreground` `#dbe6f5`, `text-muted` `#8aa0ba`,
accent cyan `#22d3ee` (`text-accent`, `border-line` = cyan at 16 % /
`line-strong` at 38 %), status colors `ok` `#34d399` / `warn` `#fbbf24` /
`danger` `#f87171`, plus `shadow-glow` and `shadow-panel`. Base layer
overrides Tailwind's default `currentColor` borders to the HUD line color
(instant facelift for unrestyled pages), pins the `dark:` variant to an
always-on class, and paints two fixed radial glows on the body. Idiom
throughout: mono, uppercase, letter-spaced micro-labels
(`font-mono text-[10px] uppercase tracking-…`) for section headers and
status readouts.

## AppShell navigation (`components/AppShell.tsx`)

Three groups: **Core** (Drop, Chat, Browse, Dashboard, Calendar — "the five
surfaces the app is built around"), **Life** (Journal, Todos, Documents,
Wardrobe, Home, Travel, Finance, People, Gallery, Profile), **Tools**
(Batch import, Graph, Vault, Sync). Desktop: fixed left sidebar with the
grouped nav and a status readout (backend heartbeat — pings `/kb/models`
every 30 s — plus a clock). Phone: slim top strip + a bottom tab bar of the
five Core items and a More button opening a BottomSheet grid of Life+Tools.
Active state = accent tint + inset bar/glow.

## Eastern-time date helpers (`lib/date.ts`)

`TIME_ZONE = "America/New_York"`; `todayIso()` via
`Intl.DateTimeFormat("en-CA", {timeZone})` (never `toISOString()`, which is
UTC and rolled "today" to tomorrow after ~8 pm ET); `yearsAgoIso`,
`calendarIso` (reads local fields of calendar-constructed Dates),
`currentMonthStart`. Mirrors the backend's `clock.py`
([architecture.md](architecture.md)).
