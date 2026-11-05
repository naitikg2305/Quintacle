# Career updates — the two on-demand updaters

Derived from code on 2026-11-05 (worktree agent, branch off `redone-UI`
`ec70fb6`). Code: `core/quintacle_core/nodes/career/` (`api.py` router
`/career`, `record.py`, `worklogs.py`, `hubs.py`, `draft.py`,
`validate.py`, `website.py`, `state.py`); page `frontend/app/career/page.tsx`
("Career updates", Productivity group). Tests:
`core/tests/test_career_updates.py`. Endpoint rows: [endpoints.md](endpoints.md).

Both updaters run only when the owner clicks, and both are
propose → review → Save: the `run` endpoints never write.

## Shared rules

- **Private notes are never used** (`nodes/kb/privacy.py`): private work
  logs are skipped before any prompt, private hubs never group or publish,
  private knowledge notes are never candidates, never ranked, and are
  re-checked at generate time. A private record note makes both updaters
  refuse (409) / ignore it.
- **"Changed since"** keys off frontmatter `edited` (stamped by every
  `KBStore.write`), never the retrieval index's `updated_at`. Notes older
  than the stamp fall back to file mtime.
- **Models are advisory and local-first** (`llm_dispatch.parse_structured`,
  `provider` = auto/local/cloud from the UI). Every model failure is
  isolated: a hub's draft shows an error, a ranking batch shows
  "AI ranking unavailable" — the run still completes.
- New KBStore helpers: `read_meta` (raw frontmatter incl. `edited`) and
  `set_fields` (merge into `fields` without touching the body or
  restamping `edited`, like `set_private`).

## Hubs and the alias table (`hubs.py`)

A **hub** is a KB note directly in `career/` or `projects/`, or the
folder-hub pattern one level down (`projects/quintacle/quintacle.md`).
Deeper documents are not hubs; the record note is never a hub. Hub fields
live in the note's `fields` (also read from top-level frontmatter):

| field | meaning |
|---|---|
| `record_entry` | explicit record entry ("7.7") this hub's logs fold into |
| `public` | only `true` hubs may appear on the website (absent = false — company work defaults to not public) |
| `public_name` | name the site uses (default: hub title) |
| `public_repo` | repo URL the site may show (project `github:` field) |
| `public_slug` | website file slug (default `slugify(public_name)`; an existing site file at the plain title slug also wins) |

**Hub → entry mapping** (deterministic, `map_hub`): 1) `record_entry` if
it names an existing entry; 2) the single entry whose title mentions the
hub title (`graph.title_mentioned`); 3) otherwise *candidates* — entries
whose titles mention it, else every entry of the period sections whose
heading mentions it (Minfy → all of §7). Against the real record: Zillion
→ 5.3, NaviGatr → 5.6, PeopleLens → 7.8 map by title; Quintacle (5.1, 7.7)
and Minfy (§7) need an owner pick, which Save then remembers as
`record_entry`.

## Build A — Update career record

**Record note**: default `Career / Master Career Record`; configurable via
`PUT /career/settings` (stored in `<data_dir>/career/settings.json`) or env
`QUINTACLE_CAREER_RECORD_FOLDER` / `QUINTACLE_CAREER_RECORD_TITLE`. The
page offers a one-time file import (`POST /career/record/import`, refuses
if the note exists). Format = TailorCV's (`## N.` periods, `### N.M`
entries, `**What I did**` / `**Resume phrasing bank**` / `**Tech.**`,
backticked tags, `[?]` unverified) — the output stays parseable by
`~/code/TailorCV/backend/tailorcv/record.py` (checked in a read-only dry run).

**Watermark marker**: a line `_Covered through: YYYY-MM-DD_`. Work logs
dated on or before it are folded in; the next run starts the day after.
Absent = never run: the UI requires a start date (inclusive). Save
replaces the line in place (the last one wins if a hand edit left two) or
appends it at the end.

**Run** (`POST /career/record/run`):
1. *Collect* (`worklogs.py`, no model): notes in `Daily Log/Work Logs`
   with `fields.date` in (`watermark`, `until`] — `until` = yesterday by
   default (a still-running day would otherwise be marked covered too
   early), today with "include today". Private notes skipped. Hook
   placeholder lines (`session ended without a log entry`) are dropped;
   a log with nothing else is skipped as placeholder-only.
2. Split into `## Session` blocks; each block goes to the hubs it mentions
   by title, among the hubs the note links to (frontmatter `links` or graph
   edges). Blocks mentioning no hub are counted, not used.
3. *Map* each hub (above).
4. *Draft* (`draft.py`, one `parse_structured` call per hub): numbered
   source lines + the entry's existing text → bullets with `section`
   (phrasing|detail) and cited line numbers. The `[WL YYYY-MM-DD]` date is
   computed in code = the newest cited log date.
5. *Validate* (`validate.py`, code): a bullet is rejected (shown greyed,
   with reasons) if it cites no line, repeats an existing bullet, or has a
   number / number word / month / known employer (Career hub titles + names
   the record states) / job-title word / degree word that is not in the
   cited group's source lines or the target entry's text. Limitation: an
   organisation the record has never mentioned can't be detected without
   NER — the reviewer is the last gate.

`through` = the latest work-log date in the window (skipped days count as
covered). `base_hash` = hash of the record body at run time.

**Save** (`POST /career/record/save`): 409 if the record body changed
since the run. Appends each bullet as `- text `[WL YYYY-MM-DD]`` after the
last bullet of the entry's LAST matching labelled list (`**Resume phrasing
bank**` / `**What I…**`); an entry without that label gets a new labelled
block at its end. New entries become `### N.M Title `[WL]`` at the end of a
period section (3–7 only, TailorCV's range), numbered max+1. Append-only:
every pre-existing line survives in order (tested). Then the watermark moves
to `through` and picked mappings are written to the hubs' `record_entry`.
Owner-edited bullet text is accepted as-is (the owner is the authority).

## Build B — Update website

**State**: `<data_dir>/career/website.json` — `watermark` (ET ISO), `last_run`,
`rejected` ({candidate id: stamp}), `entry_hashes` (record entry text hash at
last publish), `last_result`. Outside `kb/` so no model surface walks it.

**Repo**: env `QUINTACLE_WEBSITE_REPO` (default `~/code/PersonalWebsite`),
content dir env `QUINTACLE_WEBSITE_CONTENT_DIR` (default
`frontend/public/content`). Deliberately not settable from the UI.

**Run** (`POST /career/website/run`), candidates:
- *knowledge*: notes with `edited` after the watermark, excluding private,
  hubs, the record note, work logs / structured rows (`type` frontmatter),
  folders with a `logs`/`presets`/`assets`/`transactions` segment, and the
  prefixes `daily-log, journal, me, people, places, organisation, finance,
  vault, stocks-investments, personal-development/{health,mind,physical/grooming,physical/style-dressing},
  fun/dates, fun/travel` (+ `QUINTACLE_WEBSITE_EXCLUDE=a/b,c`). Documents
  under a hub folder count only when that hub is public. Oldest first,
  capped at 40 (`through` = the last shown note's `edited`, so the rest come
  next run).
- *project / employment*: public hubs whose mapped record entry's text hash
  differs from the last published hash.
- A remembered rejection hides a candidate until its stamp (`edited` / entry
  hash) changes.
- *AI suggests, owner confirms*: knowledge candidates (never private, never
  blocked ones) go to the local model in batches of 10 for
  `website: bool` + a one-line reason; the UI pre-ticks suggested ones.

**Alias gating** (code, `alias_text`): a candidate mentioning a non-public
(or private) hub is blocked; public hubs are renamed to `public_name`.
Entry bullets that name a non-public hub are dropped; `[?]` bullets and
provenance tags never reach the site.

**Generate** (`POST /career/website/generate`): re-renders each approved id
fresh from the store, then:
1. refuses (409, nothing written) if the repo is missing, not git, or
   `git status --porcelain` is non-empty — the owner's work is never
   stashed or discarded;
2. commits onto a NEW branch `quintacle/content-YYYY-MM-DD` (`-2`, `-3`…
   if taken) off the current HEAD using plumbing (temporary
   `GIT_INDEX_FILE`, `hash-object`, `write-tree`, `commit-tree`,
   `update-ref`) — the checkout, index and current branch are untouched;
   nothing is pushed or merged;
3. returns the diff summary (`--name-status` + `--numstat`) shown in the UI,
   moves the watermark to `through`, stores published entry hashes.
Zero approved items = just move the watermark ("Finish run").

**Output formats** (matched to `PersonalWebsite/frontend/src/lib/get*.ts` /
`read*.ts`):
- `knowledge/<slug>.md` — frontmatter `title, category, slug, summary`
  (category/summary editable in the UI; defaults: folder name, first
  sentence) + the note body (asset lines stripped, `[[links]]` and in-app
  links flattened to text).
- `projects/{Software|Featured}/<slug>/index.md` — existing page: a managed
  block between `<!-- quintacle:highlights:start/end -->` (`## Highlights`
  from the entry's publishable phrasing bullets) is replaced or appended;
  the hand-written page is otherwise untouched. New page: frontmatter
  `title, category: software, order: 999, date, tags (entry Tech), summary,
  github (public_repo)`.
- `employment/<slug>.md` — existing file: `[WL]`-tagged bullets not already
  present are appended to `positions[0].bullets` as `{main}` (or to
  `summaryPoints` without positions). New file: `title, order, company
  (public_name), dates, location, slug, summaryPoints`. Note: re-dumping the
  YAML can change quoting style on the branch (visible in the diff).
