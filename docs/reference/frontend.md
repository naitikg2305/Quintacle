# The frontend

Derived from code at commit `884d057` on 2026-10-15.

> **Correction (2026-10-20, next-wave §9 — chat absorbs drop):** `/kb/drop`
> is a redirect stub to `/kb` now; the chat page IS the drop surface (file
> tray + previews, statement correction flow, unknown-faces panel, "Still
> going" session, manual type grid, journal append — all on the scratchpad
> side, extracted into `components/DropAttachments.tsx`,
> `UnknownFacesPanel.tsx`, `StillGoingPanel.tsx`, `ManualAddGrid.tsx`, with
> Drop's full save semantics shared via `lib/entries.ts#commitDropEntries`).
> Core nav is four surfaces (Chat, Browse, Dashboard, Calendar); the page
> map and AppShell sections below describe the pre-§9 layout.

> **Correction (2026-11-03, overview + nav rename):** `/` is now the
> **overview** (Home), replacing the link-grid landing: Today row (todos due,
> habits on pace, food vs. `/profile/targets`, spend), a deterministic
> **Brief** (due/overdue todos, habits behind/over pace, empty journal — code,
> no model), **Recent** (`/kb/recent`), **This week** (hours from activities,
> spend, budget left from at-most spend habits, goals met) with a mini radial
> graph of the last 7 days (`/kb/recent-graph`, `components/overview/WeekGraph.tsx`),
> and a right column `components/overview/AssistPanel.tsx` — compact chat on
> `/kb/chat` (same sticky §12 mode, same saved model; archives its transcript
> on leave like Chat's New) plus a Capture box that hands text to the Chat
> scratchpad via `/kb?draft=` (review before save). Nav: Core = Home, Chat,
> Browse, Calendar (also the phone tabs); `/habits` is labelled **Habits**
> (was Dashboard) and sits in Life; `/home` is labelled **Household** (was
> Home). The Calendar's Habits toggle (week grid) is unchanged.

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


## 2026-11-05 — the private note flag in the UI

- **Review card** (`components/EntryCard.tsx`, kb_entry): a **Private**
  checkbox (Save → `private: true` via `/kb/entries` or
  `/kb/entries/with-asset`) and a folder input with existing folders as
  suggestions (`components/KBFolderInput.tsx`).
- **Scratchpad** (`app/kb/page.tsx`): **Private, skip AI** toggle — Sort
  sends `/drop` with `private_skip_ai=true`, which makes zero model calls
  and returns one private kb_entry (empty folder, first-line title) to file
  by hand. **Redo with cloud ↻** is disabled (tooltip says why) while any
  pending kb_entry is ticked Private.
- **Chat** (`app/kb/page.tsx`, `components/overview/AssistPanel.tsx`):
  assistant messages keep `private_notes` from `/kb/chat`; `ChatLog` tags
  them "private · stays local"; a cloud reply's `private_stripped` shows
  "N private notes were left out of the cloud handoff."
- **Browse** (`app/kb/browse/page.tsx`): a Private badge on the note view
  and a Make private / Make public button (`POST /kb/entry/private`); the
  raw `private` key is hidden from the meta field list.

## 2026-11-05 — correction: nav is a rail + ⊞ Apps drawer; "/" is the dashboard

Supersedes the "AppShell navigation" section above (kept as history).

- **One app registry** — `frontend/lib/apps.ts` `APPS`: every page with
  `id/href/label/icon/group/tint/match/keywords`. Groups: `core` (Chat
  `/kb`, Browse `/kb/browse`, Calendar `/day`, Graph `/kb/graph`), then
  `life`, `productivity`, `fun`, `tools` (Batch import, Vault, Sync).
  Adding a page = one entry. `appForPath` picks the most specific match.
- **No Home tab.** `/` is the dashboard; the logo (phone) / "Q" tile (desktop
  rail) links there.
- **Desktop**: an 80px icon rail (Q → `/`, the four core items, a compact
  heartbeat + clock, and a glowing ⊞ Apps button at the bottom). `main` is
  `md:ml-20`.
- **Phone**: a 5-slot bottom bar — Chat · Browse · ⊞ Apps (raised glowing
  circle) · Calendar · Graph. The top strip is unchanged.
- **App drawer** (`components/AppDrawer.tsx`, the same component on phone
  and desktop): a bottom sheet on phone, a centered panel on md+. It has a
  search box (label + keywords + group, Enter opens the first hit), a
  **Recent** row (the last 4 non-core apps visited, tracked by AppShell on
  route change in localStorage `quintacle.recentApps` with try/catch), then
  round tinted bubbles grouped Life / Productivity / Fun / Tools. Esc or a
  backdrop click closes it, Tab is trapped, the search box gets focus on
  open, focus returns to the opener on close, and body scroll is locked.
  Motion (`qa-pop` / `qa-bubble` stagger / `qa-glow` in `globals.css`) turns
  off under `prefers-reduced-motion`.
- **Dashboard** (`app/page.tsx`). Same load pattern as before: one
  `Promise.all` of `soft()` calls, so a failing endpoint blanks only its own
  widget. After load, a null field shows "Couldn't load" instead of
  "Loading…" forever. Habit progress is fetched one habit at a time (see
  the session log about the shared-connection race). Widgets, in phone
  order:
  **Today**: up to 4 due/overdue todos (overdue first, then by start time),
  plus today's activities, exercise and photos from `GET /day/{today}`, plus
  a journal nudge. Every row is a link.
  **Goals this period**: a ring per active habit (current/target) with a
  tick at `prorated_target`, colored on-pace / behind / over.
  **Productivity**: this week's hours as Mon–Sun stacked columns by activity
  category (dark categorical palette, up to 7 categories then "Other"),
  with a total and a change against the same elapsed days of last week.
  **Weight · 60 days**: a sparkline with a hover readout, the latest value,
  the change since the first reading in the window, and the change against
  a week ago. Mixed kg/lb readings are converted to the latest reading's
  unit.
  **Food today** (kcal / protein meters against Profile targets) and
  **Spend · week** (total, today, per-day mini bars, budget left from
  at_most spend habits).
  **Connections · last 7 days** (WeekGraph), **Recent**, then the
  Assist + Capture column (right column on lg, last on phone).
  Charts are plain SVG/HTML in `components/overview/charts.tsx` (`Ring`,
  `Meter`, `Sparkline`, `StackedColumns`, plus the `SERIES` palette).
- **New backend read** for the weight widget: `GET /logs/body-stats?start&end&metric=weight`
  (`LogsRepository.body_stats_between`), oldest first and read-only, with
  the metric lowercased. Client: `listBodyStats` in `lib/api.ts`.
  Tests: `core/tests/test_body_stats_read.py`.

## 2026-11-05 — Knowledge page (`app/knowledge/page.tsx`)

*Added 2026-11-05 (worktree agent).* A website-style index over the KB's
`Knowledge/**` tree, modelled on the PersonalWebsite's `/knowledge` page
(title + summary grouped by category) but in the HUD theme and with a
filter bar. Route `/knowledge`. It is not in `lib/apps.ts` yet; the
integrator adds the drawer entry.

- **Data**: one `GET /knowledge` on load (`lib/knowledgeApi.ts`, a separate
  file from `lib/api.ts`). The topic and tag filters are applied
  client-side. Search debounces 250 ms and calls `GET /knowledge?q=`, which
  returns ranked ids. Topic/tag narrowing still applies on top of that
  ranking.
- **Filters are dynamic**: topic chips come from the folder tree (a new
  folder such as `Knowledge/Planes` shows up on the next load). Clicking a
  top-level chip opens a drill row with a breadcrumb and child chips
  ("Tech Notes › Graphs"), and shows the folder's `about-*` charter as its
  description. Tag chips come from frontmatter `tags`/`category` plus
  graph-linked place/project hubs (pin/folder icons). Up to 14 are shown,
  then "+N more".
- **Grid** (`components/knowledge/NoteCard.tsx`): each card has a topic
  chip (click to filter), a lock badge for private notes, a paperclip when
  the note has assets, the title, a 3-line summary, the edited date and
  tags. Sort options are Recent (server order, `edited` desc), A–Z, and By
  topic, which groups cards under section headers the way the website
  does. Columns: 1 at 390px, 2 from `sm`, 3 from `xl`.
- **Reading view**: `?n=<folder>/<slug>`, a query param rather than a
  dynamic route so it works in the static export
  (`components/knowledge/NoteReader.tsx`). The body renders with
  ReactMarkdown + remark-gfm + rehype-highlight (same stack as Browse).
  Relative URLs inside markdown (`![](assets/x.png)`) are rewritten to
  `kbAssetUrl`. Trailing `[asset]` lines and frontmatter assets render
  inline: images in a lightbox, PDFs in an iframe, video in a player,
  anything else as a link. Buttons: "Open in Browse"
  (`/kb/browse?path=&open=`) and "Chat about this"
  (`/kb?continueFolder=&continueSlug=`, same as Browse). The Related panel
  lists 1-hop graph neighbours: knowledge notes open in place, other notes
  link to Browse.
- Private notes are shown, with a lock. This is an owner surface; nothing
  on it feeds a model.

## 2026-11-05 — Business Ideas page (`app/business/page.tsx`)

- **Route** `/business`. Not yet in `lib/apps.ts` (parallel page builds own
  that file). Add it there to put the page in the ⊞ Apps drawer.
- **Board.** Ideas grouped by status: Idea · Exploring · Validating ·
  Building · Parked/Dropped. These are five columns at `lg`. On a phone
  they are stacked sections, and empty sections are hidden. A card shows
  the title, summary, tags, file-kind icons with counts
  (`components/business/fileKinds.tsx`), and the last-touched date. It also
  shows a "no hub note" badge for a folder that the sorter filled before a
  hub existed.
- **Detail** is `?i=<slug>` (a query param, so it works with static
  export). It shows a status picker (one click = `PUT …/fields`) and an
  Edit form for summary, market and tags. The hub body is rendered as
  markdown. Below that, every file in the folder is grouped by kind
  (`components/business/IdeaFiles.tsx`):
  - Notes are rendered inline as markdown. Relative `assets/…` links resolve
    through `/kb/asset` against the note's own folder, and `[asset]` lines
    are stripped.
  - Images are a grid with `ImageLightbox`. Videos play inline. STLs use
    `STLViewer`, loaded with `dynamic`, `ssr: false`.
  - PDFs, docs and spreadsheets have Open and Save actions, plus an
    on-demand Preview: an iframe for PDF, `DocxViewer` for docx, and
    `SpreadsheetEditor` for xlsx/xlsm.
  - `.url`/`.webloc` files are shown as link chips. Anything else is a
    download chip. URLs found in the notes are collected in "Links in
    notes".
  - A hub-less folder shows a "Create the hub note" form instead of the
    overview.
- **New idea**: a quick form (title, summary, status, tags) that calls
  `POST /business/ideas` and then opens the new idea. A hint explains that
  dropping files with Sort with AI files them into `Business Ideas/<Idea>`.
- **Client**: `lib/businessApi.ts`. It is kept separate from `lib/api.ts`
  and reuses `API_BASE` and `kbAssetUrl`.

## 2026-11-05 — Career page at `/career`; updaters moved to `/career/updates`

- **Route move.** The "Career updates" page (record + website updaters)
  moved unchanged from `app/career/page.tsx` to
  `app/career/updates/page.tsx`. Nothing in the frontend linked to `/career`
  except the `lib/apps.ts` drawer entry, which the main session repoints
  (`Career` → `/career`, `Career updates` → `/career/updates`).
- **Career page** (`app/career/page.tsx`). It copies the PersonalWebsite's
  experience page (`app/experience`, `WorkExperienceSection`,
  `CareerTimeline`) in the HUD theme: a `$ git log --oneline career/`
  prompt chip, then a vertical timeline line with glowing dots (green on
  current entries), newest first. Each hub is a dark panel with the org
  name, "dates • location" in italics, a `present` badge, and its
  positions as "Role — dates" with `·` bullets (roles nested under the
  org, e.g. Minfy → Engineering, Sales). Current entries open expanded;
  the chevron toggles the rest. Each card shows a 12-month work-log
  sparkline, the log-day count with the last date, and a file count.
  Filter chips (`Segmented`): All · Employment · Contracts · Education.
  "Add role / contract" opens the create form; "Career updates →" links
  to the updaters.
- **Detail** is `/career?hub=<folder>` (a query param, so it works with
  static export; wrapped in `Suspense` for `useSearchParams`). It shows the
  full fields and bullets, Edit fields, Add role (orgs), the roles list,
  the last 5 work-log days (each links to `/kb/browse` on that log), files
  in the folder (notes → Browse, raw/`assets/` files → `kbAssetUrl`,
  subfolders → Browse), and the mapped master-record entry's bullets, or
  its candidates when none is mapped.
- Code: `components/careerpage/{CareerTimeline,HubDetail,HubForm,Sparkline}.tsx`,
  client `lib/careerPageApi.ts` (kept out of `lib/api.ts`). Backend +
  semantics: [career-updates.md](career-updates.md) (2026-11-05 section).
  Layout uses `min-w-0`/`break-words`/`flex-wrap` throughout and is
  built to work at 390px.

## 2026-11-05 — Projects page (`/projects`)

The owner asked for this to look like the PersonalWebsite's `/projects`
page. It shows projects done, doing and planned, along with their GitHub
repos, STL files and markdown notes.

- **Data model.** A project is a top-level KB folder `projects/<slug>/`. Its
  hub is the note whose slug equals the folder slug (the career/hubs.py
  rule). Everything else in that folder tree belongs to the project. An
  older single note directly in `projects/` also counts as a project, and it
  owns only the assets it references. A folder with files but no hub still
  shows up (badge "no hub note"), and the first field edit creates its hub.
  The hub's `fields` hold `status` (done | doing | planned; doing by
  default; synonyms like finished or idea are normalized), `repo` (or
  `github`), `summary` (falls back to the body's first line), `stack` (list
  or comma string, falls back to `tags`), `start`/`end`, and `cover` (asset
  path relative to the project folder). `public`, `public_name` and
  `public_repo` are the same keys the Career alias table uses. They are
  shared, not copied.
- **Card visual**, deterministic. Uses the `cover` field if set, otherwise
  `card.stl` (the website's convention), otherwise an image named
  cover/image/card/banner/thumbnail, otherwise the first image, otherwise
  the first STL. A project with no visual gets the website's terminal title
  bar (`~/projects/<slug>`).
- **Work logs** come from graph edges from `note:daily-log/work-logs/*` into
  the hub (the work-log importer creates these), plus work logs whose
  frontmatter `links` name the hub title. These are the same two sources
  `career/worklogs.py` trusts. Other graph neighbors (people, places,
  notes) are listed under "Connected". Private neighbors are skipped.
- **Page.** `app/projects/page.tsx` has sections Doing, Planned and Done in
  the website's centered-section style, a status filter
  (`?status=doing|planned|done`) and a name/stack filter. The detail view is
  `/projects?p=<slug>`, a query param because the phone build is a static
  export. The detail view shows the header with a status badge and dates, a
  cover banner or a 400px orbit STL viewer, the summary, stack chips, "View
  on GitHub" and "Public repo" buttons, the About section (hub body), 3D
  models, images (lightbox grid), PDFs and docs (inline PDF iframe or DOCX
  viewer), videos, notes (collapsible, markdown rendered), other files,
  work-log day chips and Connected. Only one STL canvas is live at a time:
  you pick a model file to view it, because several WebGL contexts on a
  phone run out. Edit fields and New project open in a `BottomSheet` form.
  Edits send only the keys that changed.
- **Files.** Components live in `components/projects/`: `ProjectCard`
  (ported from the website's ProjectCard + SoftwareProjectCard),
  `ProjectDetailView`, `ProjectForm`, `ProjectMarkdown` (Browse's
  react-markdown + GFM + highlight; relative image and link targets resolve
  through `/kb/asset`; `[asset]` and `<!-- filemeta -->` plumbing lines are
  hidden) and `GithubIcon` (lucide 1.x has no brand marks). The client
  lives in `lib/projectsApi.ts`, a new file kept out of `lib/api.ts` so
  parallel page builds don't collide there. `request` is now exported from
  `lib/api.ts` for it. Endpoint rows are in [endpoints.md](endpoints.md).
  Tests: `core/tests/test_projects_page.py`.
- **Not done here:** the Apps-drawer entry (`lib/apps.ts`), which the main
  session adds.

