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
| GET | `/kb/recent` | `?limit&since` | *(added 2026-11-03)* Newest-indexed nodes first (`RetrievalIndex.recent`; `updated_at` = last save) — the overview's Recent strip | RetrievalIndex |
| GET | `/kb/recent-graph` | `?since&limit` | *(added 2026-11-03)* Nodes saved since `since` + their 1-hop neighbors and the edges between them; transcripts excluded — the overview's mini graph | RetrievalIndex + GraphEdgeStore |
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

> *Added 2026-11-05 (unified Finances page; see [finance.md](finance.md)):
> 5 routes on `finance_router` — manually-recorded account balances.*

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/finance/accounts` | — | Every account + full balance history, bucket totals, net worth (incl. uncovered stock-ledger holdings), net-worth history | AccountStore + StocksRepository (read) |
| POST | `/finance/accounts` | `{name, account_type, institution?, notes?, balance?, as_of?}` | Upsert descriptive fields by name; a supplied `balance` is APPENDED as a snapshot; 400 on unknown type | AccountStore |
| POST | `/finance/accounts/{slug}/balance` | `{balance, as_of?, note?}` | Append one dated snapshot (never overwrites); 404 unknown account | AccountStore |
| DELETE | `/finance/accounts/{slug}/balance/{index}` | — | Remove one snapshot (index into the date-sorted list) — the undo | AccountStore |
| DELETE | `/finance/accounts/{slug}` | — | Delete the account file | AccountStore |

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


## 2026-11-05 additions — the private note flag

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/kb/entry/private` | `{folder, slug, private}` | Set/clear a note's `private` flag; touches only that frontmatter key (no `edited` restamp); 404 when missing | KBStore |

Changed: `POST /kb/entries` (+`private: bool`), `POST /kb/entries/with-asset`
(+`private` form field; a private photo note skips the auto-journal),
`POST /drop` (+`private_skip_ai` form field — zero model calls, one private
kb_entry proposal), `POST /kb/chat` (messages may carry `private_notes`;
response adds `private_notes` / `private_stripped` when non-empty),
`POST /kb/sort` (private target → local only; cloud 400),
`POST /kb/record-that` (private turns/target → local only). Every suggester
fed a notes index (`/kb/sort`, `/kb/drop`, `/kb/batch-drop`, `/drop`,
record-that) now gets `public_notes_index` — no private titles.

## Career updaters (`/career`, `nodes/career/api.py`) — 12

*Added 2026-11-05 (worktree agent).* Full semantics in
[career-updates.md](career-updates.md). The two `run` endpoints write
nothing; only `record/save`, `record/import`, `hubs` (PUT), `settings`
(PUT), `website/reject` and `website/generate` write.

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/career/settings` | — | Record note location + website repo/content dir | CareerState |
| PUT | `/career/settings` | `{record_folder?, record_title?}` | Override where the record note lives | CareerState |
| GET | `/career/record` | — | Exists/private, `covered_through` watermark, period sections 3–7 + entries | KBStore |
| POST | `/career/record/import` | `{content}` | First-time import of the master record as a KB note; 409 if one exists | KBStore + GraphEdgeStore + RetrievalIndex |
| POST | `/career/record/run` | `{start?, include_today?, provider?}` | Collect work logs after the watermark, group by hub, map to entries, draft + fact-check bullets. No write | KBStore + GraphEdgeStore + llm_dispatch |
| POST | `/career/record/save` | `{through, base_hash?, bullets[], new_entries[], mappings[]}` | Append-only write of reviewed bullets, move the watermark, remember hub→entry picks; 409 if the record changed since the run | KBStore + RetrievalIndex |
| GET | `/career/hubs` | — | Career/Projects hubs with alias fields + deterministic entry mapping | KBStore |
| PUT | `/career/hubs` | `{folder, slug, record_entry?, public?, public_name?, public_repo?, public_slug?}` | Edit one hub's alias/mapping fields (no `edited` restamp) | KBStore |
| GET | `/career/website` | — | Website watermark, last run, last result, repo path | CareerState |
| POST | `/career/website/run` | `{provider?}` | Candidates (notes edited since the watermark + changed public record entries) with an advisory AI suggest/reason. No write | KBStore + llm_dispatch |
| POST | `/career/website/reject` | `{id, stamp}` | Remember a rejection until the note/entry changes | CareerState |
| POST | `/career/website/generate` | `{through, items[{id, category?, summary?}]}` | Render approved items, commit onto a new `quintacle/content-YYYY-MM-DD` branch (409 on a dirty tree, nothing written), move the watermark | website git repo + CareerState |
| GET | `/career/timeline` | — | *(2026-11-05, Career page)* Every `Career/**` folder hub as a tree (org → roles; contracts; education): parsed date range + `present`, fields, work-log day count / last 5 dates / 12-month sparkline, mapped record entry bullets, files in the folder. Zero model calls | KBStore + GraphEdgeStore |
| POST | `/career/hubs` | `{type, name, org?, role?, start?, end?, location?, summary?, bullets?, record_entry?, public?, public_name?, order?}` | *(2026-11-05)* Create `Career/<Name>`, `Career/<Org>/<Name>` (role; `org` = parent hub folder) or `Career/Contracts/<Name>`; 409 if it exists, 400 on an unreadable date | KBStore + GraphEdgeStore + RetrievalIndex |
| PUT | `/career/hubs/{folder}/fields` | any subset of the create fields minus `name`/`org` | *(2026-11-05)* Edit a timeline hub's fields (`""`/`[]` clears; no body change, no `edited` restamp) | KBStore |

## 2026-11-05 additions — Projects page (`/projects`, `nodes/projects/api.py`) — 4

*Added 2026-11-05 (worktree agent).* Deterministic view over the KB's
`Projects/<Name>/` folders (hub note slug = folder slug). The GETs are
read-only. The PUT writes hub `fields` without restamping `edited`, the same
rule as `PUT /career/hubs`, and shares its `public*` fields. Details are in
[frontend.md](frontend.md) (2026-11-05 Projects page).

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/projects` | — | Every project, sorted by status (doing, planned, done) then most recently touched: `status`, `repo`, `summary`, `stack`, `start`/`end`, `public*`, counts (notes, files by kind, work-log days), `card` (STL or image for the card) | KBStore + GraphEdgeStore |
| GET | `/projects/{slug}` | — | One project: the above plus the hub `body`, every `notes[]` with content, `files[]` (paths relative to the project folder, readable with `/kb/asset`), `worklogs[]` and graph `related[]`. 404 if not found | KBStore + GraphEdgeStore |
| PUT | `/projects/{slug}/fields` | `{status?, repo?, summary?, stack?, start?, end?, cover?, public?, public_name?, public_repo?}` | Owner edit: only sent keys change, and `""`/`[]` clears a key. If the folder has no hub yet, this creates it | KBStore (+ RetrievalIndex/graph when it creates a hub) |
| POST | `/projects` | `{name, description?, ...fields}` | New project: creates `Projects/<Name>/` and its hub note, with status defaulting to doing. 409 if the slug exists, 400 if the name is empty | KBStore + GraphEdgeStore + RetrievalIndex |

## 2026-11-05 additions — Travel states: Planned + Bucket list (`/travel`, `nodes/travel/api.py`) — 6

*Added 2026-11-05 (worktree agent).* Travel now has three states:
Experiences (unchanged, `experience:` entities), **Planned** (trip notes
under `Fun/Travel/Planned/**`) and **Bucket list** (one note per place under
`Fun/Travel/Bucket List`). Logic lives in `nodes/travel/states.py`. It is all
deterministic, with no model calls. `about-*` charter notes are skipped
everywhere. `ExperienceStore.all()` now ignores the `planned/`,
`bucket-list/` and `assets/` dirs, so these notes never read as experiences.

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/travel/planned` | — | `[{folder, slug, title, group, start, end, destinations, status, edited}]` for every note under `fun/travel/planned` (recursive). `group` = first subfolder or `""`. The four trip fields come from frontmatter `fields` (string or null). Sorted by start (nulls last), then title | KBStore |
| GET | `/travel/unsorted` | — | Same shape (`group: ""`) for notes sitting directly in `fun/travel`, so the UI can offer to move them | KBStore |
| POST | `/travel/planned/move` | `{folder, slug, group?}` | Move a note into `Fun/Travel/Planned[/<group>]` with the `assets/<file>` files it references. An asset a sibling note also uses is copied; a name clash gets a `-2` name and the reference is rewritten. 409 if the target note exists, 404 if the source is missing. Graph edges are re-pointed to the new node id and the retrieval index is re-keyed. Returns `{folder, slug}` | KBStore + GraphEdgeStore + RetrievalIndex |
| POST | `/travel/planned/backfill-photos` | query `dry_run` (default `true`) | 2026-11-05 (`trip_photos.py`): link every dated photo to the planned trip(s) it was taken during (`during_trip` edge photo → plan: capture day in start..end AND no destinations or city/state/country/continent match). Deterministic, idempotent, drops stale/orphan edges. Returns `{dry_run, plans, photos_scanned, created, removed, per_plan, sample}`. 2026-11-05: `GET /travel/planned` rows also carry `photo_count` and `photos: [{folder, slug, asset}]` (first 6) | KBStore + GraphEdgeStore |
| GET | `/travel/bucket` | — | `[{folder, slug, place, notes, added, visited, visited_on, experience_ids}]`. `visited` is computed in code: an experience's city matches the place as a whole word in either direction (`"Kyoto, Japan"` ~ `Kyoto`; `Rome` never ~ `Romeoville`), or the experience name appears whole inside the place. `visited_on` = the earliest matching `visited_date` | KBStore + ExperienceStore |
| POST | `/travel/bucket` | `{place, notes?}` | Create the place note (stamps `fields.added`), then run the same graph/retrieval hooks as `POST /kb/entries`. 409 if it already exists. Returns the row | KBStore + GraphEdgeStore + RetrievalIndex |
| DELETE | `/travel/bucket/{slug}` | — | Delete the place note and drop its graph edges and retrieval row. 404 if missing | KBStore + GraphEdgeStore + RetrievalIndex |

Sorter: `SEED_FOLDERS` now includes `Fun/Travel/Planned` and
`Fun/Travel/Bucket List`. The placement, entry and batch prompts share one
folder bullet (`_FOLDER_RULE` in `nodes/kb/llm.py`). It allows a new
subfolder under the best existing folder for a distinct group, and says to
reuse a matching `Planned/<X>` first. It also carries the travel rule:
future-trip docs go to `Fun/Travel/Planned/<Region or Trip>`, and someday
places go to `Fun/Travel/Bucket List`.

## 2026-11-05 additions — photo place baked into the body

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/kb/photos/backfill-place` | query `dry_run` (default `true`) | Walk every KB note with image assets (or frontmatter `location`), add/refresh its `📍 … <!-- place -->` body line + `place` frontmatter, re-index each. Dry run only reports `{dry_run, count, changes: [{folder, slug, line, place, location}]}` (geocode results are still cached, so the apply run is free). Private notes never hit the cloud geocoder | KBStore + RetrievalIndex |
| POST | `/kb/graph/backfill-places` | query `dry_run` (default `true`) | 2026-11-05 (`place_graph.py`): link every photo (frontmatter `place`), Fun/Travel/Planned trip (`fields.destinations`) and experience (city) into the place hierarchy — `located_in` → city, `part_of` city → country → continent — and index the place nodes. Deterministic, idempotent. Returns `{dry_run, counts: {photos, plans, experiences}, edges, located_in, part_of, places, sample: [{source, target, kind}]}` | KBStore + ExperienceStore + GraphEdgeStore + RetrievalIndex |

## 2026-11-05 additions — file metadata

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| POST | `/kb/files/backfill-meta` | query `dry_run` (default `true`) | Walk every KB note with `[asset](…)` files and re-extract metadata from the stored bytes (PDF/Office/image/MP4, no model call). Adds or refreshes the `🗂 … <!-- filemeta -->` body line(s) and `file_meta` frontmatter, links an `on_day` edge to the created day's journal when that day exists, and re-indexes. Returns `{dry_run, count, changes: [{folder, slug, lines, days, new_edges}]}`. A dry run writes nothing | KBStore + GraphEdgeStore + RetrievalIndex |

`/drop`, `/kb/drop` and `/kb/batch-drop` proposals now carry `file_meta: [{…, line}]` for display. Save re-extracts it from the stored file.

Changed: `POST /kb/entries/with-asset`, `POST /kb/entry/asset` (now also
re-indexes when an image is attached) and the MCP `kb_attach_file` tool all
bake the place line for image files. See `drop-pipeline.md` (2026-11-05
photo place section).

## 2026-11-05 additions — Knowledge page (`/knowledge`, `nodes/knowledge/`) — 2

*Added 2026-11-05 (worktree agent).* Read-only and deterministic, with no
model calls. Everything is derived from `kb/knowledge/**` at request time.
`assets/` and `_*` dirs are skipped. `about-*` charter notes are never
listed; a charter's `summary` (or first paragraph) becomes its folder's
topic `description`. Private notes ARE listed, with `private: true`,
because this is an owner surface.

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/knowledge` | query `q?`, `topic?` (`tech-notes` or `knowledge/tech-notes/graphs`; matches the subtree), `tag?` (case-insensitive; also matches hub labels) | Returns `{topics, tags, notes, total, root_count, charter}`. `topics` is a tree of `{topic, name, label "Tech Notes › Graphs", folder, count (subtree), direct_count, description, children}`. `tags` is `[{tag, count, kind: tag\|place\|project}]`: frontmatter `tags`/`category`/`categories` (top level or in `fields`), grouped case-insensitively, plus graph-linked `note:places/*`, `place:*` and `note:projects/*` hubs (one edges query). `notes` is `[{id, folder, slug, title, topic, topic_label, tags, hubs, summary, edited, has_assets, private}]`, sorted by `edited` desc (file mtime in ET when there is no stamp). `summary` is frontmatter `summary`, else the retrieval summary, else the first meaningful paragraph. `topics`, `tags` and `total` always describe the whole tree; only `notes` is filtered. `q` lists retrieval hits (FTS5 + vectors) restricted to knowledge notes first, then a substring pass over title, summary, tags and body | KBStore + GraphEdgeStore + RetrievalIndex |
| GET | `/knowledge/note` | query `folder`, `slug` | Returns `read_full` plus `{id, topic, topic_label, tags, edited, private, related: [{id, title, edge_type, folder, slug, knowledge}]}`. `related` = 1-hop graph neighbours (`retrieval.neighbor_labels`). 404 if missing | KBStore + GraphEdgeStore |

## 2026-11-05 additions — Business Ideas board (`/business`, `nodes/business/api.py`) — 4

An idea is `Business Ideas/<Idea>/` (on disk `kb/business-ideas/<idea>/`)
with a hub note whose slug equals the folder slug. Every file anywhere under
the idea's folder belongs to it. Hub `fields`: `status` (`idea | exploring |
validating | building | parked | dropped`; anything else reads as `idea`),
`summary`, `market`, `tags` (list), `created`. No model is called.

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/business/ideas` | — | `{statuses, ideas: [{slug, folder, title, has_hub, private, status, summary, market, tags, created, file_counts, file_total, last_edited}]}`. A folder with no hub is listed with `has_hub: false`. `file_counts` is by kind (`markdown, image, video, pdf, doc, spreadsheet, model, link, other`), hub excluded, `_`/`.` plumbing skipped. `last_edited` = latest of the hub's `edited` and every file's mtime (ET). Newest first | KBStore root (read-only walk) |
| GET | `/business/ideas/{slug}` | — | The card fields plus `body` (hub body, title line stripped), `files` grouped by kind (`{name, path, kind, size, modified}`; markdown adds `folder, slug, title, content, private`; `.url`/`.webloc` add `url`), and `links` (http(s) URLs found in the hub and notes). `path` is relative to the idea folder, so `/kb/asset?folder=<folder>&path=<path>` serves it. 404 if missing | KBStore root |
| POST | `/business/ideas` | `{title, summary?, status?, market?, tags?, body?}` | Create the hub (`fields.created` = today ET), then the same graph-link + retrieval hooks as `POST /kb/entries`. A hub-less folder is adopted. 409 if the hub exists, 400 on a bad status or a title with no letters/digits. Returns the detail | KBStore + GraphEdgeStore + RetrievalIndex |
| PUT | `/business/ideas/{slug}/fields` | any of `{status, summary, market, tags}` | Merge hub fields via `KBStore.set_fields` (no `edited` restamp, body untouched). Only sent keys change; `""` / `[]` removes the field. 400 on a bad status, 404 if there's no hub. Returns the detail | KBStore |

The sorter now offers `Business Ideas` as a seed folder, and `_FOLDER_RULE`
(`nodes/kb/llm.py`) routes business/startup/product ideas to
`Business Ideas/<Idea>`. Tests: `core/tests/test_business_ideas.py`.

## 2026-11-05 additions — Nutrition / USDA FoodData Central (`/nutrition`, `nodes/logs/nutrition_api.py`) — 9

*Added 2026-11-05 (worktree agent).* Every number comes from stored presets
or the offline USDA db (`nutrition_db/`). The only model involvement is the
optional index-only candidate pick. Details: `nutrition.md`.

| Method | Path | Input | Purpose | Store |
|---|---|---|---|---|
| GET | `/nutrition/db/status` | — | `{installed, path, summary{foods, size_bytes, built_at, flavonoids, source_urls}, approx_download_mb, job{state, step, error}}` | usda.db |
| POST | `/nutrition/db/install` | — | Starts the background download + build (`fetch.install`); `{started}` (false if one is already running). Poll status | usda.db |
| GET | `/nutrition/match` | query `q`, `pick?=true` | Ranked candidates `[{fdc_id, description, category, source, score}]` (top 8) plus `pick` (confident top, or a model's index-only choice) | usda.db |
| GET | `/nutrition/food/{fdc_id}` | query `grams?=100` | Ingredient-preset-shaped fields for that amount: macros, `micros[{nutrient, amount, unit, source:"usda", approx?}]`, `fdc_id`, `usda_description`. 404 if unknown | usda.db |
| POST | `/nutrition/breakdown` | `{components:[{name?, quantity_g, ingredient_id? \| fdc_id? \| inline macros+micros, source?}]}` | Full grouped panel for a draft (composer / preset card) | ingredients + usda.db |
| GET | `/nutrition/ingredient/{id}` | query `grams?` | Panel for one ingredient preset (+ `source`, `fdc_id`, `usda_description`) | ingredients |
| GET | `/nutrition/meal/{meal_id}` | query `servings?=1` | Panel for a meal; composed meals break down per ingredient | meals + meal_ingredients |
| GET | `/nutrition/day/{date}` | — | Panel for the day's food log, flattened to ingredients (contributions name foods) | food_log + presets |
| POST | `/logs/ingredients/backfill-usda` | query `dry_run?=true` | Re-source existing presets (estimated/legacy → USDA, label → gaps filled). Returns `{changes[{id, name, from_source, to_source, fdc_id, usda_description, score, kcal_before, kcal_after, …}], skipped, meals_recomputed}`. Apply recomputes affected composed meals | ingredients + usda.db |

Changed: `POST /logs/ingredients` takes `source` (`usda | label | estimated |
manual | ""`), `fdc_id` and `auto_match`. With `source: "usda"` the numbers
are re-read from the db, ignoring the client's values. With `label`, the
client's values win and gaps are filled from `fdc_id`. The response echoes
what was stored. `MealComponentInput` (`POST /logs/meals/from-ingredients`)
takes `fdc_id`/`source`. `POST /logs/meals/suggest-composition` components
carry `source`, `fdc_id`, `usda_description` and `usda_candidates`.
`/drop` ingredient proposals carry the same fields. `/logs/nutrition/{date}`
now also lists ALA (omega-3) against its AI.

**2026-11-06 — local-first images.** `POST /drop`'s `provider` form field
now also pins the IMAGE calls (`perception/image_policy.py`; default
`QUINTACLE_IMAGE_PROVIDER=local`). The response gains `pipeline`
(`"ocr+parser" | "ocr+local-llm" | "yolo+local-vlm" | "yolo" | "cloud" | null`),
also set on each of the branch's own proposals. When the local stack can't
read the photo: HTTP 200 `{entries: [], provider_used: "local", pipeline:
null, local_unavailable: "<reason> — Redo with cloud?"}`; re-send the same
drop with `provider=cloud`. Any other endpoint that hits an unreadable image
(`/kb/drop`, `/kb/asset/describe`, …) returns 422 `{detail,
local_unavailable: true}`; `/kb/batch-drop` keeps going and files that one
file by name. `/kb/asset/describe` on a private note's asset is pinned
local. Ingredient proposals from a label photo add `field_confidence`,
`label_dv`, `serving_size_text`, `servings_per_container`, `per_100g`.
