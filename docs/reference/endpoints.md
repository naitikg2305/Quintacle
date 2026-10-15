# REST endpoints — the complete route inventory

Derived from code at commit `884d057` on 2026-10-15.

Every route in the FastAPI app, enumerated from the `@app.*`/`@router.*`
decorators in [core/quintacle_core/api.py](../../core/quintacle_core/api.py),
[core/quintacle_core/sync.py](../../core/quintacle_core/sync.py), and every
`nodes/*/api.py`. **114 routes total** (counts per section in headings).

> *Moved since the stamp, later 2026-10-15 (code at `1a46c92`): 4 routes
> added — `POST /kb/asset/describe` (billed re-look at a stored image),
> `POST /kb/asset/perceive` (free local perception), `POST /perception/tag`
> (the unknown-face tag flow, `nodes/kb/perception_api.py`), and
> `GET /people/{name}/appearances` (graph-derived) — so 114 is now **118**.
> `/drop`, `/kb/sort` and `/journal/{date}/parse` additionally take a
> `?provider=local|cloud|auto` query param and return `provider_used`. See
> `reference/perception-and-autojournal.md` and `reference/local-models.md`.*
"Store" names the class(es) the handler touches. Unless noted, request/
response bodies are JSON; "multipart" means `multipart/form-data` (file
uploads); "text" means a raw `text/plain` body.

Conventions that repeat everywhere:
- *Propose vs. commit*: `suggest`/`sort`/`parse`/`estimate`/`drop` endpoints
  call an LLM and **never write** — the frontend reviews, then commits
  through the domain's own create endpoint ("Approval before write").
- *Name canonicalization*: every create endpoint for a named thing runs
  `canonicalize_name` against existing names, so near-duplicate spellings
  update the existing record instead of forking a new one.
- *Folder as query param*: nested KB folders contain `/`, so they ride as
  `?folder=` query params, never path segments.

## Cross-node (`api.py`) — 4

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/day/counts` | `?start&end` (dates) | date → total logged-entry count (activities+food+exercise+substances+expenses) for calendar badges | LogsRepository |
| GET | `/day/{for_date}` | path date | Everything that happened that day: journal text, todos due, activities, exercise (sets parsed from `sets_json`), food entries + daily totals, body stats, substances, expenses | JournalStore, TodoStore, LogsRepository |
| POST | `/drop` | multipart: `text`, `file?`, `file2?`, `keep_as_is`, `reference_date?` | The one general capture endpoint — deterministic prefix routing, then AI classification/extraction; returns `{entries: ParsedEntry[]}`, writes nothing. Full walkthrough in [drop-pipeline.md](drop-pipeline.md) | reads nearly every store |
| GET | `/graph` | — | Full graph-view payload: journal-day/note/asset/experience/ingredient/meal/routine/exercise/item/outfit nodes + edges from the `edges` table and structural relations | JournalStore, KBStore, ExperienceStore, GraphEdgeStore, LogsRepository, Wardrobe stores |

## Schedule (`/schedule`, `nodes/schedule/api.py`) — 5

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/schedule/todos` | — | Open todos, ranked (due date asc, priority desc; undated last) | TodoStore |
| POST | `/schedule/todos` | `{title, priority?, due_date?, start_time?, end_time?, notes?}` | Create a todo (id = 12-hex uuid) | TodoStore |
| PATCH | `/schedule/todos/{todo_id}` | any subset of fields (incl. `done`) | Partial update (`exclude_unset`), 404 if missing | TodoStore |
| DELETE | `/schedule/todos/{todo_id}` | — | Delete the todo file | TodoStore |
| GET | `/schedule/calendar` | — | `{iso-date: [todos]}` for dated, not-done todos, priority-sorted per day | TodoStore |

## Journal (`/journal`, `nodes/journal/api.py`) — 3

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/journal/{for_date}` | text | Append a timestamped (`### HH:MM`) block to the day's file — never overwrites | JournalStore |
| GET | `/journal/{for_date}` | — | The day's content (MCP undo markers stripped), or `null` | JournalStore |
| POST | `/journal/{for_date}/parse` | text | AI-parse the dump into proposed entries (`parse_journal_dump` + `canonicalize_entries`), plus the additive experience/person checks. Never writes | LogsRepository (meal/routine libraries), PersonStore; proposals only |

## Logs (`/logs`, `nodes/logs/api.py`) — 31

Meals / ingredients / routines:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/logs/meals` | `{name, protein_g…, kcal, notes?, micros?}` | Create/upsert a flat meal preset (micros canonicalized to RDA units) | LogsRepository → MealPresetStore + `meals`/`meal_micros` |
| GET | `/logs/meals` | — | All meal presets | `meals` |
| GET | `/logs/meals/{meal_id}/micros` | — | A meal's micronutrients | `meal_micros` |
| POST | `/logs/meals/estimate` | text | AI macro+micro estimate for a described food — never writes | — (LLM only) |
| POST | `/logs/meals/suggest-composition` | `{description}` | AI proposes components; `resolve_composition` deterministically matches the ingredient library (library macros win over guesses). Never writes | `ingredients` (read) |
| POST | `/logs/meals/from-ingredients` | `{name, notes?, components[]}` | Commit a composed meal — unmatched components become new ingredient presets first; totals computed deterministically | LogsRepository → presets + `meals`/`meal_ingredients` |
| GET | `/logs/meals/{meal_id}/components` | — | A composed meal's ingredient rows | `meal_ingredients` |
| POST | `/logs/ingredients` | `{name, basis_amount_g?, macros, kcal, micros?}` | Create/upsert an ingredient preset | IngredientPresetStore + `ingredients` |
| GET | `/logs/ingredients` | — | All ingredient presets | `ingredients` |
| GET | `/logs/ingredients/{ingredient_id}/micros` | — | An ingredient's micronutrients | `ingredient_micros` |
| POST | `/logs/routines` | `{name, exercises[]}` | Create a workout routine (names canonicalized) | RoutineStore (markdown only) |
| GET | `/logs/routines` | — | All routines | RoutineStore |
| POST | `/logs/routines/suggest` | `{description}` | AI proposes an ordered exercise list, resolved against logged exercise names. Never writes | `exercise_sets` (read) |

Daily logs:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/logs/food` | `{date, meal_type, meal_id?/freeform_kcal?, servings?, notes?}` | Log an eating instance (preset-referencing or freeform) | LogFileStore + `food_log` |
| GET | `/logs/food/{for_date}` | — | Day's food entries + macro totals (preset join or freeform kcal) | `food_log`+`meals` |
| POST | `/logs/substances` | `{date, substance, amount, notes?}` | Log a substance | LogFileStore + `substance_log` |
| POST | `/logs/expenses` | `{date, amount, merchant?, category?, notes?, kind?}` | Log an expense | LogFileStore + `expense_log` |
| GET | `/logs/expenses` | `?start&end` | Expenses in a date range | `expense_log` |
| POST | `/logs/activities` | `{date, category, description, hours?}` | Log an activity | LogFileStore + `activity_log` |
| GET | `/logs/activities/{for_date}` | — | Day's activities | `activity_log` |
| GET | `/logs/activities` | `?start&end` | Activities in range | `activity_log` |
| POST | `/logs/exercise` | `{date, exercise_name, sets[], notes?}` | Log an exercise with structured sets | LogFileStore + `exercise_sets` |
| GET | `/logs/exercise-names` | — | Distinct logged exercise names (autocomplete; history IS the preset list) | `exercise_sets` |
| POST | `/logs/body-stats` | `{date, metric, value, unit?}` | Log a body metric | LogFileStore + `body_stats` |

Habits / nutrition / maintenance:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/logs/habits` | `{name, target_amount, target_period, match_category?, unit?, metric?, direction?}` | Create a habit/quota (metrics: activity_hours, food_kcal, spend; direction at_least/at_most) | `habits` |
| GET | `/logs/habits` | — | All habits | `habits` |
| GET | `/logs/habits/{id}/progress` | — | Current-window progress (deterministic window math in `quotas.py`) | `habits` + metric tables |
| GET | `/logs/habits/{id}/history` | `?periods=8` | Last N windows of progress | same |
| POST | `/logs/rebuild-index` | — | Wipe + regenerate every SQLite log table from the markdown files (`rebuild_sqlite_index`) | all log tables |
| GET | `/logs/nutrition/{for_date}` | — | Day's macros + every micronutrient vs. the profile-personalized RDA (0-intake still shown), plus energy balance (kcal in/burned/net) | LogsRepository + ProfileStore |
| GET | `/logs/nutrition-history` | `?days=8` | Last N days of kcal/protein/kcal-burned, oldest first | LogsRepository |

## Knowledge base (`/kb`, `nodes/kb/api.py`) — 28

Browse / read:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/kb/folders` | — | Every folder, `/`-joined, all depths | KBStore |
| GET | `/kb/entries` | `?folder` | Entry slugs in a folder | KBStore |
| GET | `/kb/files` | `?folder` | Non-`.md` files directly under a folder (e.g. an `assets/` dir's contents) | KBStore |
| GET | `/kb/entry` | `?folder&slug` | Full entry: body, `fields`, non-plumbing `meta`, frontmatter `assets` | KBStore |
| GET | `/kb/entries-meta` | `?folder` | One row per entry (title/meta/assets/snippet) for gallery/cards/table layouts | KBStore |
| GET | `/kb/view` | `?folder` | Saved `_view.json` or an inferred default layout (`infer_view`) | KBStore |
| PUT | `/kb/view` | `?folder` + ViewConfig | Save a folder's layout | KBStore |
| GET | `/kb/search` | `?q` | Case-insensitive substring search over every filename+body | KBStore |
| GET | `/kb/photos` | — | Every entry under `media/photos/**` with its assets — the Gallery source | KBStore |
| GET | `/kb/graph` | — | KB-note half of the graph: notes with `links` resolved to edge-table target ids | KBStore + GraphEdgeStore |
| GET | `/kb/asset` | `?folder&path` | Raw asset bytes (path clamped to the KB root) | KBStore |

Propose / write:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/kb/sort` | text + `?target_folder?&target_slug?` | Propose folder/title/content: new entry (no target), folder-scoped (folder only), or merge-update of an existing entry (both). Never writes | KBStore (read) |
| POST | `/kb/entries` | `{folder, title, content, links?, fields?}` | Commit a note: localizes remote markdown images into real assets, writes, then materializes graph edges (`_sync_note_graph_links`) | KBStore + GraphEdgeStore |
| POST | `/kb/drop` | multipart `file`, `description` | Describe one file (vision/PDF/DOCX extraction) and propose placement. Never writes | KBStore (read) |
| POST | `/kb/batch-drop` | multipart `files[]`, `manual_date?`, `manual_trip_name?` | One AI call buckets a pile of files by shared folder; EXIF date/GPS decide photo placement deterministically. Never writes | KBStore, JournalStore, ProfileStore (read) |
| POST | `/kb/entries/with-asset` | multipart: folder/title/content/`files[]`/`links` (comma-sep) | Commit an entry with any number of attached files — one `[asset](…)` body line each; EXIF GPS of the first photo saved as `location`; edges synced | KBStore + GraphEdgeStore |
| POST | `/kb/entry/asset` | multipart folder/slug/file | Attach a new file to an *existing* entry (appends an asset line, preserves frontmatter) | KBStore |
| POST | `/kb/asset/replace` | multipart folder/path/file | Overwrite an asset's bytes in place — the markdown link never changes | KBStore |
| GET | `/kb/asset/spreadsheet` | `?folder&path` | Parse an xlsx asset into plain string grids | KBStore + openpyxl |
| PUT | `/kb/asset/spreadsheet` | `?folder&path` + `{sheets}` | Rebuild the xlsx from grids and replace in place | KBStore + openpyxl |

Chat / generation:

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/kb/models` | — | The chat model picker list (id/label/provider/price) | — |
| POST | `/kb/chat` | `{messages, use_kb, research, folder?, model?}` | KB-grounded chat (whole KB or folder-scoped), Anthropic or OpenAI path, web search, `{{photo:Name}}` → Wikipedia thumbnails. Never writes | KBStore (read) |
| POST | `/kb/generate-image` | `{prompt}` | OpenAI image generation; returns base64 for preview — committed later via `/kb/entries/with-asset` | — |
| GET | `/kb/chats` | — | Scratch chat sessions (id + title) | ChatStore |
| POST | `/kb/chats` | `{title?}` | Create a session (timestamp id) | ChatStore |
| GET | `/kb/chats/{session_id}` | — | Load a transcript (attachments collapsed to text notes) | ChatStore |
| PUT | `/kb/chats/{session_id}` | `{title?, messages}` | Save a transcript | ChatStore |
| DELETE | `/kb/chats/{session_id}` | — | Delete a session | ChatStore |

## Profile (`/profile`, `nodes/profile/api.py`) — 3

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/profile` | — | The profile JSON (height/sex/birthdate/activity level/home countries) | ProfileStore |
| PUT | `/profile` | Profile | Replace the profile | ProfileStore |
| GET | `/profile/targets` | — | Mifflin-St Jeor BMR→TDEE + protein target from profile + latest logged weight; `{error}` if either is missing | ProfileStore + `body_stats` |

## Wardrobe (`/wardrobe`, `nodes/wardrobe/api.py`) — 7

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/wardrobe/items` | multipart name/category/description/`files[]` | Create an item (name canonicalized), photos saved as assets | WardrobeItemStore |
| GET | `/wardrobe/items` | — | All items | WardrobeItemStore |
| GET | `/wardrobe/asset` | `?path` | Item asset bytes | WardrobeItemStore |
| POST | `/wardrobe/outfits` | multipart name/`items` (JSON list)/`file?` | Create an outfit — composed from items, or a full-look photo with an empty item list | OutfitStore |
| GET | `/wardrobe/outfits` | — | All outfits | OutfitStore |
| GET | `/wardrobe/outfits/asset` | `?path` | Outfit photo bytes | OutfitStore |
| POST | `/wardrobe/outfits/suggest` | `{description}` | AI proposes items, deterministically resolved against the real item library. Never writes | WardrobeItemStore (read) |

## Grooming (`/grooming`, `nodes/grooming/api.py`) — 6

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/grooming/items` | multipart name/category/description/`files[]` | Create a product | GroomingItemStore |
| GET | `/grooming/items` | — | All products | GroomingItemStore |
| GET | `/grooming/asset` | `?path` | Product asset bytes | GroomingItemStore |
| POST | `/grooming/routines` | `{name, steps[]}` | Create a routine (steps canonicalized against products) | GroomingRoutineStore |
| GET | `/grooming/routines` | — | All routines | GroomingRoutineStore |
| POST | `/grooming/routines/suggest` | `{description}` | AI proposes ordered steps, resolved against the product library. Never writes | GroomingItemStore (read) |

## Documents (`/documents`, `nodes/documents/api.py`) — 3

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/documents` | — | All documents | DocumentStore |
| GET | `/documents/asset` | `?path` | Scan/photo bytes | DocumentStore |
| POST | `/documents` | multipart name/doc_type/issued_date/expiry_date/status/notes/`files[]` | Create-or-update by canonicalized name; a genuinely NEW document with an expiry date auto-creates a `Renew: <name>` todo (first creation only) | DocumentStore + TodoStore |

## Home (`/home`, `nodes/home/api.py`) — 5

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/home/residences` | `{name, city, address?, moved_in?, moved_out?, notes?}` | Create a residence (`Organisation/Home/<City>/<Name>.md`) | ResidenceStore |
| GET | `/home/residences` | — | All residences | ResidenceStore |
| POST | `/home/items` | multipart name/residence_name?/category/location/purchase_price?/purchase_date?/notes/`files[]` | Create an item under a residence — named residence fuzzy-matched, else the current one (no `moved_out`); 400 if none exists | HomeItemStore (+ResidenceStore) |
| GET | `/home/items` | `?residence_name` | Items for a (resolved) residence | HomeItemStore |
| GET | `/home/asset` | `?residence_folder&path` | Item asset bytes | HomeItemStore |

## Travel (`/travel`, `nodes/travel/api.py`) — 2

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/travel/experiences` | `{name, city, kind, rating?, would_return?, visited_date?, notes?, links?}` | Create an experience, then materialize its `links` into edges and keyword-link known people (`mentions_person`) | ExperienceStore + GraphEdgeStore |
| GET | `/travel/experiences` | `?city?` | All experiences, optionally filtered by city | ExperienceStore |

## People (`/people`, `nodes/people/api.py`) — 2

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/people` | `{name, category?, how_met?, met_date?, notes?, links?}` | Create/update a person (`People/<Name>/profile.md`), then keyword-link known experiences (`structural` edges) | PersonStore + GraphEdgeStore |
| GET | `/people` | — | All people | PersonStore |

## Finance (`/credit-cards`, `/investments`, `nodes/finance/api.py`) — 4

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/credit-cards` | `{name, issuer?, annual_fee?, rewards_summary?, points_balance?, signup_bonus?, notes?}` | Upsert by name; omitted fields keep existing values (merge-on-partial-update) | CreditCardStore |
| GET | `/credit-cards` | — | All cards | CreditCardStore |
| POST | `/investments` | `{name, symbol?, shares?, cost_basis?, account?, purchase_date?, notes?}` | Same upsert/merge contract for holdings | InvestmentStore |
| GET | `/investments` | — | All holdings | InvestmentStore |

## Vault (`/vault`, `nodes/vault/api.py`) — 8

Full semantics in [vault.md](vault.md).

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/vault/status` | — | `{initialized, locked, auto_lock_seconds_remaining}` | VaultStore |
| POST | `/vault/init` | `{passphrase}` | Create salt+verifier, leave unlocked; 409 if already initialized, 400 on empty passphrase | VaultStore |
| POST | `/vault/unlock` | `{passphrase}` | Derive key, verify; 403 wrong passphrase, 409 uninitialized | VaultStore |
| POST | `/vault/lock` | — | Drop the in-memory key immediately | VaultStore |
| GET | `/vault/entries` | — | Entry summaries WITHOUT secrets; 401 when locked | VaultStore |
| GET | `/vault/entries/{slug}` | — | The one place a secret leaves the backend; 401 locked, 404 missing | VaultStore |
| PUT | `/vault/entries/{slug}` | `{name, username?, secret?, url?, notes?}` | Encrypt + write an entry; response is secret-free | VaultStore |
| DELETE | `/vault/entries/{slug}` | — | Delete the `.enc` file; 404 if absent | VaultStore |

## Sync (`/sync`, `sync.py`) — 3

Full semantics in [sync.md](sync.md).

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/sync/manifest` | — | `{rel_path: {mtime, size, sha256}}` for every syncable file | filesystem |
| GET | `/sync/file` | `?path` | Raw bytes of one syncable file; 403 on traversal/excluded paths | filesystem |
| POST | `/sync/pull` | `{peer_url, push_back?, self_url?}` | Pull from the peer (merge/copy/snapshot per the rules), rebuild derived indexes, optionally ask the peer to pull back | filesystem + LogsRepository + GraphEdgeStore |
