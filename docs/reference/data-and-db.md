# Data formats and the database

Derived from code at commit `884d057` on 2026-10-15.

Two layers, with an explicit ownership contract repeated throughout the
code: **markdown files are the record; SQLite is a fast, disposable index**
rebuilt from them. The only SQLite-primary data is the preset/log *id*
continuity that other rows reference (handled by upsert-by-name during
rebuilds, below).

## Markdown + frontmatter conventions

All parsing/writing goes through `python-frontmatter`
(`frontmatter.Post`, `frontmatter.dumps/loads`). Files are YAML frontmatter
+ a markdown body.

### Slugs and paths — `markdown_paths.py`

[core/quintacle_core/markdown_paths.py](../../core/quintacle_core/markdown_paths.py):

- `slugify(text)`: lowercase, every non-`[a-z0-9]` run collapsed to `-`,
  trimmed; empty input becomes `"entry"`. Doubles as the path-traversal
  guard for any segment built from AI output or user input.
- `resolve_nested(root, folder)`: a `/`-separated display path
  ("Personal Development/Physical/Fitness") becomes nested directories,
  each segment slugified independently — the join can never escape root.
- `list_folder_tree(root)`: every directory under root as `/`-joined
  relative paths.
- `safe_metadata(post, stem, defaults)`: defensive read for structured
  stores — a stray generic note pushed into a structured folder (this
  happened for real via folder-scoped chat) degrades to "one oddly-empty
  entry" instead of 500-ing the whole list endpoint; `name` falls back to a
  title-cased filename.

### KB notes — `nodes/kb/store.py`

One file per entry: `<kb>/<folder-slugs>/<title-slug>.md`. Body starts with
`# <Title>` (written by `KBStore.write`). Frontmatter keys:

- `links: [titles]` — free-text related-entry titles, as authored; the
  graph engine materializes them into edges. Kept in metadata (never the
  body) so a "keep as-is" document gains connectivity byte-for-byte
  untouched.
- `location: {lat, lon}` — deterministic EXIF GPS, when a photo had one.
- `fields: {key: value}` — open user/AI-defined key/value pairs (the
  generic-page-builder data; rendered as a table).
- `assets: [paths]` — the current list form of frontmatter-attached files;
  older structured entries have a fixed `asset`/`asset2` pair instead, and
  readers fall back to those (`_frontmatter_assets`).

`_INTERNAL_META = {"links", "location", "fields", "assets", "asset",
"asset2"}` — the plumbing keys Browse hides; everything else in frontmatter
surfaces as `meta` (that's where structured stores keep their real fields).

**Merge-safe writes**: `KBStore.write` carries over existing frontmatter and
treats `links`/`location`/`fields = None` as "don't touch" — a plain body
edit can't blank an AI-computed links list.

**Body asset lines**: attached files are referenced by trailing
`[asset](assets/<slugified-name>.<ext>)` lines, one per file
(`_ASSET_LINES_RE` finds all of them; `_ASSET_RE` grabs the last for the
graph's representative asset). Binary files live in `<folder>/assets/`;
`save_asset` slugifies the stem, `read_asset`/`replace_asset` clamp the
resolved path to the KB root (an escaping path reads as 404).

**Folder views**: an optional `_view.json` per folder stores
`{layout, columns, badges, sort_by, sort_dir}` (`ViewConfig`); absent or
invalid, `infer_view` derives a default from the folder's contents (≥half
with assets → gallery; ≥3 common scalar meta keys → table; short
categorical keys → cards; else list).

### Journal days — `nodes/journal/store.py`

`journal/YYYY-MM-DD.md`. Append-only: each save adds a `### HH:MM` block
(Eastern time), blocks separated by `\n\n---\n\n`. An MCP append is wrapped
in `<!-- mcp-append:<12-hex> --> … <!-- /mcp-append:<id> -->` comments so
`strip_marked_append` can later remove exactly that span (plus exactly one
adjacent separator). `load()` strips the marker comments for display;
`list_dates()` globs the filenames.

### Todos — `nodes/schedule/store.py`

`schedule/todos/<id>.md`, id = 12-hex uuid. Frontmatter: `id`, `title`,
`priority` (int 1–4), `due_date`, `start_time`/`end_time` ("HH:MM" or null),
`done`, `created_at`; the body is the todo's free-text `notes`.

### Log entries — `nodes/logs/log_store.py`

One file per log entry, written through by every `/logs` POST:
`<kb>/<LOG_HOME>/logs/<date>-<seq:03d>.md` where `LOG_HOMES` maps each type
into the KB tree it belongs with:

| type (· category) | home folder |
|---|---|
| exercise, body_stat | Personal Development/Physical/Fitness |
| food | Personal Development/Physical/Nutrition |
| substance | Daily Log/Substances |
| finance | Organisation/Finance |
| activity:productivity / social / leisure / yourself / emotional | Daily Log/<Category> |

Frontmatter: `type`, `date`, plus the entry's fields (e.g. `exercise_name`,
`sets` as a real YAML list, `amount`, `merchant`, `kind`…); body = notes.
Exercise and body_stat share a folder, so readers filter on the `type`
field, not the directory.

Preset libraries, same contract (markdown primary, SQLite index):
- Meal presets: `…/Nutrition/presets/<slug>.md` (`name`, macros, `kcal`,
  `notes`, `micros` list; composed meals also carry `components` by
  *ingredient name*, since names are portable and integer ids aren't).
- Ingredient presets: `…/Nutrition/ingredients/<slug>.md` (adds
  `basis_amount_g`).
- Workout routines: `…/Fitness/routines/<slug>.md` (`name`, `exercises`) —
  deliberately no SQLite mirror; nothing foreign-keys a routine.

### Structured domain stores (all under `kb/`)

Each is one markdown file per thing, fields in frontmatter, `notes` in the
body, photos as `assets` lists pointing into a shared `assets/` dir:

- **Wardrobe**: `…/Style & Dressing/items/<slug>.md`,
  `…/outfits/<slug>.md` (`items` name list, optional `asset`).
- **Grooming**: `…/Grooming/items/`, `…/routines/` (`steps`).
- **Documents**: `Organisation/Document Vault/<slug>.md` (`doc_type`,
  `issued_date`, `expiry_date`, `status`, `assets`).
- **Home**: `Organisation/Home/<City>/<Residence>.md`; items in the sibling
  `<City>/<Residence>/items/` (`category`, `location`, `purchase_price`,
  `purchase_date`, `assets`).
- **People**: `People/<Name>/profile.md` (`name`, `category`, `how_met`,
  `met_date`, `links`) — a folder per person so mention notes
  (`People/<Name>/Mentions/…`) and the folder-scoped chat see profile +
  mentions together.
- **Travel**: `Planning/Travel/<City>/<Kind-plural>/<slug>.md` (`city`,
  `kind`, `rating`, `would_return`, `visited_date`, `links`).
- **Finance**: `Organisation/Finance/Credit Cards/<slug>.md` and
  `…/Stocks & Investments/<slug>.md` — upsert-by-name, partial updates
  merged with existing values.

### Other file formats

- `profile.json` — a single Pydantic-serialized `Profile`.
- `kb_chats/<YYYY-MM-DD-HHMMSS-µs>.md` — scratch chat transcripts; a
  photo/PDF attachment persists only as a "(photo attached)" text note,
  never raw base64.
- `graph/edges/*.md` — frontmatter-only edge files
  ([graph-engine.md](graph-engine.md)).
- `vault/meta.json`, `vault/entries/*.enc` — [vault.md](vault.md).
- `mcp-log.md` — the MCP ledger ([mcp-server.md](mcp-server.md)).

## The SQLite schema — `core/quintacle_core/db.py`

One file, `quintacle.db`, WAL mode, `row_factory = sqlite3.Row`.
`db.connect()` runs the full `CREATE TABLE IF NOT EXISTS` script plus a
hand-rolled idempotent migration list (`_MIGRATIONS` — `ALTER TABLE ADD
COLUMN`s whose duplicate-column errors are swallowed).

| Table | Columns | Notes |
|---|---|---|
| `meals` | id PK AI · name TEXT UNIQUE · protein_g/carbs_g/fat_g/fiber_g REAL dflt 0 · kcal REAL · notes TEXT dflt '' | meal preset index (markdown: `presets/`) |
| `meal_micros` | id PK AI · meal_id→meals · nutrient TEXT · amount REAL · unit TEXT | per-meal micronutrients |
| `ingredients` | id PK AI · name TEXT UNIQUE · basis_amount_g REAL dflt 100 · protein_g/carbs_g/fat_g/fiber_g/kcal REAL dflt 0 · notes | ingredient preset index |
| `ingredient_micros` | id PK AI · ingredient_id→ingredients · nutrient · amount · unit | |
| `meal_ingredients` | id PK AI · meal_id→meals · ingredient_id→ingredients · quantity_g REAL | composition of a composed meal; a meal with no rows is a flat preset |
| `food_log` | id PK AI · date TEXT · meal_type TEXT · meal_id→meals NULL · freeform_kcal REAL NULL · servings REAL dflt 1 · notes | preset-referencing or freeform |
| `substance_log` | id PK AI · date · substance · amount REAL · notes | |
| `activity_log` | id PK AI · date · category · description · hours REAL dflt 0 | |
| `exercise_sets` | id PK AI · date · exercise_name · performance_text · sets_json TEXT dflt '[]' · notes dflt '' | one row per exercise instance; sets_json holds the structured sets, performance_text is a readable fallback |
| `body_stats` | id PK AI · date · metric · value REAL · unit dflt '' | |
| `expense_log` | id PK AI · date · amount REAL · merchant dflt '' · category dflt '' · notes dflt '' · kind dflt 'regular' | kind ∈ subscription/food/alcohol/experience/shopping/big_purchase/regular |
| `habits` | id PK AI · name UNIQUE · target_amount REAL · target_period TEXT · match_category TEXT NULL · unit dflt '' · metric dflt 'activity_hours' · direction dflt 'at_least' | quota definitions |
| `edges` | id TEXT PK · source_type · source_id · target_type · target_id · kind · source_of_edge · created_at (all TEXT NOT NULL) | mirror of `graph/edges/*.md`; id = edge filename stem |

Indexes: `idx_edges_source_id ON edges(source_id)`,
`idx_edges_target_id ON edges(target_id)`. (The log tables have no explicit
indexes beyond their integer PKs — fine at current scale.)

Migrations (re-run safely every connect): habits `metric`/`direction`,
meals `fiber_g`, exercise_sets `sets_json`/`notes`, body_stats `unit`,
expense_log `kind`.

**Derived vs. primary**: every table above is rebuildable from markdown
*except* that integer ids must stay stable across rebuilds, because
`food_log.meal_id` and `meal_ingredients.*_id` reference them — hence the
rebuild upserts by name instead of truncating (below). The `habits` table
is the one genuinely SQLite-only store (no markdown behind it).

## The two rebuild mechanisms

1. **`rebuild_sqlite_index(store, conn, preset_store, ingredient_store)`**
   ([nodes/logs/log_store.py](../../core/quintacle_core/nodes/logs/log_store.py)) —
   exposed as `POST /logs/rebuild-index` and run after every sync pull.
   Ingredients and meals upsert by (UNIQUE) name — update in place, delete
   what no longer has a markdown file — so ids survive; micros are
   re-inserted; composed meals' `components` (stored by ingredient *name*
   in markdown) are re-resolved to ids. The pure log tables
   (`activity_log`, `exercise_sets`, `substance_log`, `body_stats`,
   `expense_log`, `food_log`) are truncated and refilled from the log
   files; legacy exercise entries without structured `sets` keep their
   `performance_text`. Returns per-table counts.
2. **`rebuild_from_folder(data_dir, conn)`**
   ([graph.py](../../core/quintacle_core/graph.py)) — truncates `edges` and
   re-inserts one row per `graph/edges/*.md` file (filename stem = id,
   missing `kind` defaults to `related`, missing `source_of_edge` to
   `unknown`). Run after every sync pull. Distinct from `api.py`'s startup
   *backfill*, which reads note/experience frontmatter to create edge files
   that never existed.
