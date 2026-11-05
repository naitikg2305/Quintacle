# The Drop pipeline

Derived from code at commit `884d057` on 2026-10-15.

> **Correction (2026-10-20, next-wave §9 — chat absorbs drop):** the Drop
> PAGE retired; the chat page (`frontend/app/kb/page.tsx`) is the drop
> surface now. Everything below about the `/drop` ENDPOINT, the router, the
> describers, and the review/commit semantics is still accurate — only the
> UI moved: the scratchpad carries the file tray
> (`components/DropAttachments.tsx`), the review cards, the manual grid
> (`components/ManualAddGrid.tsx`), the unknown-faces panel
> (`components/UnknownFacesPanel.tsx`) and the "Still going" session
> (`components/StillGoingPanel.tsx`); the full save semantics live in
> `lib/entries.ts#commitDropEntries`. Mentions of
> `frontend/app/kb/drop/page.tsx` below describe the pre-§9 surface (the
> route is now a redirect stub to `/kb`).

Drop is the one general capture endpoint: `POST /drop` in
[core/quintacle_core/api.py](../../core/quintacle_core/api.py) (the
`propose_drop` handler), the deterministic router in
[nodes/drop_router.py](../../core/quintacle_core/nodes/drop_router.py), the
file describers in [nodes/kb/drop.py](../../core/quintacle_core/nodes/kb/drop.py),
and the Drop page at `frontend/app/kb/drop/page.tsx`. It **never writes** —
it returns `{entries: ParsedEntry[]}` for review; the frontend commits each
approved entry through that type's own existing endpoint
(`lib/entries.ts commitEntry`, see [frontend.md](frontend.md)).

Guiding principle (the router's own comment): deterministic-first,
everywhere — a recognized `keyword:` prefix decides the entry TYPE with no
AI call; only when determinism can't decide does classification fall
through to AI.

## Inputs

Multipart form: `text` (may carry a prefix), optional `file` + `file2`
(a second photo of the SAME thing — back/label/another angle — read
together, never a second entry), `keep_as_is` (an already-finished document:
AI only places it, never rewrites), `reference_date` (what
"yesterday"/"last Tuesday" resolve against — the UI's date picker, else
Eastern today). 400 if both text and file are empty.

## Step 1 — deterministic prefix routing: `PREFIX_TYPES`, verbatim

`parse_prefix` matches `^<letters> : <rest>` (case-insensitive keyword;
rest must be non-empty, else fall through to AI):

```python
PREFIX_TYPES = {
    "todo": "todo",
    "task": "todo",
    "food": "food",
    "meal": "food",
    "ate": "food",
    "exercise": "exercise",
    "workout": "exercise",
    "lift": "exercise",
    "routine": "workout_routine",
    "substance": "substance",
    "drink": "substance",
    "activity": "activity",
    "weight": "body_stat",
    "finance": "finance",
    "expense": "finance",
    "spend": "finance",
    "note": "kb_entry",
    "kb": "kb_entry",
    "ingredient": "ingredient_preset",
    "preset": "ingredient_preset",
    "label": "ingredient_preset",
    "recipe": "meal_composition",
    "dish": "meal_composition",
    "item": "wardrobe_item",
    "wardrobe": "wardrobe_item",
    "outfit": "outfit_composition",
    "product": "grooming_item",
    "grooming": "grooming_routine_composition",
    "document": "document_entry",
    "doc": "document_entry",
    "home": "home_item",
    "residence": "residence_entry",
    "apartment": "residence_entry",
    "experience": "experience_entry",
    "visit": "experience_entry",
    "person": "person_entry",
    "friend": "person_entry",
    "creditcard": "credit_card_entry",
    "card": "credit_card_entry",
    "invest": "investment_entry",
    "stock": "investment_entry",
}
```

Also deterministic: `parse_routine_definition` —
`"Pull Day = Pull-ups, Rows, Lat Pulldown"` → (name, exercise list), no AI;
a `routine:` drop in that shape never calls a model (names canonicalized
against existing routines/exercises).

## Step 2 — unprefixed files

- **Unprefixed image** (`IMAGE_MIME_TYPES`: jpg/jpeg/png/gif/webp): ONE
  cheap vision call, `classify_image_type`, over a fixed 7-label set, then
  a fixed mapping:

| ImageKind | entry type |
|---|---|
| nutrition_label | ingredient_preset |
| prepared_meal | ingredient_preset |
| receipt | finance |
| outfit_item | wardrobe_item |
| full_outfit | outfit_photo |
| document | document_entry |
| generic | kb_entry |

- **Unprefixed non-image file** (PDF/DOCX/STL/video…): no vision kind call;
  `describe_drop` extracts real text first (below), then
  `classify_text_file_type` decides document_entry (formal paperwork worth
  an expiry/renewal todo) vs. kb_entry.

**`describe_drop`** (kb/drop.py) builds the one text description every
downstream call sees — same function text drops use, so files are filed by
the same logic: images → a vision caption (both photos together when two);
PDF → native Claude document read; DOCX → paragraph text, falling back to
captioning an embedded image when there's <30 chars of real text (the
scan-pasted-into-Word case); video → 4 evenly-sampled frames captioned
(cv2 imported lazily; missing OpenCV degrades to no description, not a
crash); STL/OBJ/3MF → nothing extracted, the user's words carry it.
User text, when present, is prepended.

## Step 3 — per-type extraction branches

With the type fixed, AI (Haiku) only extracts fields; deterministic safety
nets run after every call:

- `workout_routine` — the `name = a, b, c` parse, or a bare name.
- `wardrobe_item` / `grooming_item` — photo- or text-described;
  `suggested_name` canonicalized against the existing item library.
- `outfit_composition` / `grooming_routine_composition` /
  `meal_composition` — suggest + deterministic resolve against the real
  item/ingredient library (library macros beat model guesses).
- `outfit_photo` — a full look saved AS IS, not decomposed.
- `document_entry`, `residence_entry`, `credit_card_entry`,
  `investment_entry`, `person_entry`, `experience_entry` — one structured
  extraction each (explicit prefixes skip the relevance gates).
- `home_item` — extraction, then **deterministic residence resolution**: a
  named residence fuzzy-matches the list, else the current residence (no
  `moved_out` date).
- `ingredient_preset` — nutrition-label/food-photo vision estimate or text
  estimate; name canonicalized so a second "Lamb" photo updates the
  existing preset.
- `finance` + image — `extract_finance_from_receipt` (reads total,
  merchant, category, the receipt's own printed date, and `kind`).
- `kb_entry` — `suggest_kb_entry` (or `suggest_kb_placement` when
  `keep_as_is` — title/folder/links only, content untouched). A real camera
  photo overrides AI placement: EXIF date (+GPS → `compute_photo_folder`)
  files it under `Media/Photos/<Year>/<Month>/<trip | country/state/city |
  —>`; if that date has a journal entry, the date is added to `links` (the
  future `on_day` edge).
- prefixed todo/food/exercise/substance/activity/body_stat/finance(text) —
  `parse_journal_dump(..., forced_type=...)`: the full parser in
  extract-only mode, one entry of the stated type.
- **No prefix, no file** — the only path that hits full multi-type AI
  classification: `parse_journal_dump` over the 8-type union, with the meal
  and routine libraries in the prompt, a regex-gated second pass for
  per-entry dates, and a kind pass for finance entries. Then
  `canonicalize_entries` fixes exercise/substance name drift.

## Step 4 — the additive experience/person checks

Independent of the primary classification ("AI proposes everything
plausible, I prune"):

- **Experience**: `maybe_structure_experience(experience_check_text)` — a
  free regex pre-filter (`_EXPERIENCE_SIGNAL_RE`: restaurant/bar/museum/
  "went to"/"visited"/trip/…) gates one cheap call that both judges
  relevance (`is_experience`) and extracts fields. Each branch chooses what
  text the check sees (the rich extracted description where one exists;
  nulled for residence/credit-card/investment/experience's own branch).
  When an experience IS detected: a photo that already became its own
  kb_entry gets linked by title; a real EXIF photo that classified as
  something else (a meal, a wardrobe item) is *additionally* proposed as a
  gallery kb_entry so the experience has something real to link to.
- **Person**: `maybe_structure_person_mention` — two free local gates (a
  new-person keyword pattern: "met", "her name is", "first date", …; OR any
  known person's name appearing in the text), then one call. A new person →
  a `person_entry` proposal; a known person → a kb_entry mention filed
  under `People/<Name>/Mentions` with the date-stamped title. When an
  experience and a known person surface from the SAME drop, each gets the
  other's name in `links` — the hint that makes commit-time
  `graph.link_new_entry` create the real `mentions_person`/`at_location`
  edges deterministically. Skipped only for the `person_entry` branch
  itself (no self-duplicate).

`POST /journal/{date}/parse` runs the same two checks on the raw dump (the
lean text-only version — no photo-archival branch).

## Batch drop (`POST /kb/batch-drop`)

Multi-file import: every file is extracted via `describe_drop`, then **one**
AI call (`suggest_kb_batch`) sees all of them and proposes
folder/title/content/links per file — grouped so related files share the
EXACT same folder string instead of drifting into near-duplicates. Files
ride as opaque `file_0…` ids (models reliably echo an opaque token; they
"improve" real filenames — this broke correlation on the first pass, so a
returned unknown id is dropped rather than mis-attributed). Per image,
deterministically: EXIF date (or `manual_date`, which overrides) + EXIF GPS
decide the real photo folder via `compute_photo_folder`;
`manual_trip_name` > AI `trip_name`; a journaled date joins `links`. The
response is `{buckets: [{folder, files}]}`; the frontend reviews per bucket
and commits each file individually through `/kb/entries/with-asset`.

## Multi-attachment commits — `/kb/entries/with-asset`

Takes any number of files. Writes the entry, saves every file under
`<folder>/assets/`, then re-writes the entry with one `[asset](…)` line per
file (write-first so the slugified folder/slug are known); EXIF GPS of the
first photo becomes the `location` frontmatter; links (comma-separated in
the form) are synced into graph edges. The Drop page attaches
`[file, ...extraPhotos]` to asset-keeping types
(`kb_entry, document_entry, wardrobe_item, grooming_item, home_item,
outfit_photo`); ingredient_preset/finance extract data and discard the
image.

### 2026-11-05 — photo place baked into the body

Owner ask: "whenever a photo is uploaded the metadata location gets updated
and baked into the markdown so it can be retrieved". The retrieval index only
sees title + body, so a photo whose AI description never named the place was
unfindable by "Vienna / Austria / Europe". `nodes/kb/photo_place.py` now
writes ONE body line just before the trailing `[asset](…)` lines:

    📍 Vienna, Austria · Europe · 48.2082, 16.3738 · taken 2027-05-14 15:32 <!-- place -->

plus `place: {city, state, country, continent}` frontmatter next to
`location` (hidden from Browse fields like `location`).

- Coords and capture time come from EXIF (`extract_photo_location`,
  `extract_photo_datetime`/`extract_photo_date`). No model is involved.
- City, state and country come from `photo_organizer.geocode`, the one
  cloud call. Results are cached by coords rounded to 3 decimals in
  `<data>/geocode-cache.json`, so a batch from one spot costs one call.
- The continent comes from a country table in code, which includes name
  variants like USA/UK/Czechia.
- **Private** saves never call the geocoder. They get coords + date only
  (a cache hit still fills names, because it sends nothing).
- A geocode error is logged and the line keeps coords + date. The save
  never fails. With no GPS the line has the date only, and with no EXIF
  there is no line.
- The `<!-- place -->` marker makes re-runs replace the line, never add a
  second one. react-markdown drops the comment, and
  `deterministic_prose_summary` skips the line. The FTS body keeps it.
- Hooked into `/kb/entries/with-asset`, which covers single drop and batch
  import, because both commit through it. Also hooked into
  `POST /kb/entry/asset` and MCP `kb_attach_file`. The last two now
  re-index the note when an image is attached. The MCP bake happens inside
  the staged write session, so `undo_write` restores the prior bytes.
  Images only. PDFs and other files are untouched.
- `POST /kb/photos/backfill-place` (dry run by default) fixes notes saved
  before this change.

### 2026-11-05 — file metadata baked at drop and at save

Owner ask: "bake [file metadata] at the drop step that way we always have
data … we need to link everything on that graph so weak ais can answer
stuff". `nodes/kb/file_meta.py` extracts each file's own metadata. It uses
only the stdlib and Pillow, makes no model call and adds no new dependency:

| Type | Fields |
|---|---|
| PDF | title, author, subject, creator, producer, created, modified, pages. Read from the raw Info dict and from Flate object streams via zlib, with an XMP fallback |
| DOCX / XLSX / PPTX | title, subject, author (`dc:creator`), last_modified_by, created, modified from `docProps/core.xml`. pages, slides and words from `app.xml`. sheets is the worksheet count |
| Image | camera_make, camera_model, width, height, taken (EXIF). Place stays with `photo_place` |
| MP4 / MOV / M4V / M4A / 3GP | duration_s, created (`mvhd`, overridden by Apple's `creationdate`), location (`©xyz` / ISO6709), from a small box walker. WebM and MKV get the common fields only |
| Every file | filename (the original upload name), asset, size, mime, ext, kind, day |

Dates are normalized to ISO. PDF `D:YYYYMMDDHHmmSS±HH'mm'` and W3CDTF are
both handled, and timezone-aware values are converted to Eastern. `day` is
the taken or created date, used for the journal link.

- **Body line**: one per asset, just before the `[asset](…)` lines and after
  any 📍 line. Example:
  `🗂 PDF · "Austria itinerary" · 12 pages · created 2026-11-04 by Naitik · austria.pdf (128 KB) <!-- filemeta -->`.
  The `<!-- filemeta -->` marker makes re-runs idempotent.
  `insert_place_line` now treats 🗂 lines as part of the trailing block, so
  📍 always stays first. `deterministic_prose_summary` skips the line, and
  the FTS body keeps it.
- **Frontmatter**: `file_meta: [{…}, …]`, one dict per asset. It is in
  `_INTERNAL_META`, so Browse does not list it as a field.
- **At drop**: `/drop` attaches `file_meta` (a list, with a display `line`)
  to every kb_entry proposal, including "Private, skip AI", which still makes
  zero model calls. `/kb/drop` and `/kb/batch-drop` attach it per file. The
  review card (`EntryCard` kb_entry) and the batch import card show a
  read-only "File info" line.
- **At save**: `apply_file_meta()` re-reads the STORED asset from disk and
  ignores anything the client sent. It is hooked into
  `/kb/entries/with-asset`, `POST /kb/entry/asset` and MCP `kb_attach_file`,
  each time right after the `photo_place` call and before `safe_index_note`.
  The MCP call runs inside the staged session, and new edges are staged
  too, so `undo_write` removes them.
- **Graph**: the note gets an `on_day` edge to `journal:<day>`
  (`source_of_edge: file_meta`) only when that journal day exists, the same
  rule photos follow. The edges are re-synced, so a stale file_meta day edge
  is removed. `day_bundle.day_photos` therefore surfaces a boarding pass
  created on May 12 when asked about May 12. One gap: an MCP re-attach that
  removes a stale edge does not restore it on undo.
- `POST /kb/files/backfill-meta` (dry run by default) covers older notes.

## The Drop page's "Still going" session

Pure orchestration of existing endpoints, no backend feature
(`frontend/app/kb/drop/page.tsx`): when a save produced exactly ONE entry
and it was a `kb_entry`, the page captures the returned `{folder, slug}` as
an active session and shows a "Still going — \<title\>" panel. From there:

- **Add more text** → `POST /kb/sort?target_folder&target_slug` (the
  merge-update variant: AI folds the new text into the existing body) then
  `POST /kb/entries` to commit the merged note.
- **Attach a file** → `POST /kb/entry/asset` (appends an asset line to the
  same entry).

Multi-entry saves don't open a session (no single obvious entry to keep
extending). "Save to journal" additionally appends the raw drop text to the
day's journal via `POST /journal/{date}` before committing entries.
