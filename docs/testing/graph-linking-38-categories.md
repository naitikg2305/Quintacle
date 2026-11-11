# Graph linking: the owner's 38 categories (2026-11-11)

**Status: DRAFT.** Claude wrote these expectations from the product principles ("link everything for weak
AIs", "reference, never duplicate", vault invisible). The owner corrects them on 2026-11-12, while seeding.
Until then the tests built from this file are drafts too.

The list is the owner's handwritten list of what he will actually use Quintacle for (items 1–38, his order).

## How linking works today (code: `graph.py`, `graph_capture.py`)

- **The matcher is deterministic, with no model.** A candidate links when its *full title* appears in the text
  as a whole word.
- **Candidates are:**
  - people → `mentions_person`;
  - experiences → `at_location`;
  - journal days → `on_day`;
  - a note's own `links:` frontmatter → `related` (or `on_day`).
- **One capture is one event:** every record saved from one Drop/Save gets `part_of` → `event:<hash>`.
- **Places:**
  - a trip plan's destinations make a city → country → continent chain (`place_graph.py`);
  - a city named in 3 or more sources becomes a place (emergent places).
- **Numeric logs** (food, exercise, expense, body, substance) are deliberately not keyword-linked. They tie to
  their day by date and to their capture by the event.
- **The vault is never in the graph.**

## Expected links per category

"→" means an edge must exist after saving, either from the new record or to it. "✗" means it must NOT exist.

| # | Category | What gets saved | Must link |
|---|---|---|---|
| 1 | Travel itinerary | Note under Fun/Travel/Planned/<Trip> | → each destination city → its country → continent (place chain); → people named in it; ✗ Documents vault |
| 2 | Journal | Journal day | → people named; → experiences/places named; records parsed from it `part_of` one event |
| 3 | Food, workout set | Food rows + exercise sets | All rows from one drop `part_of` one event; a known meal/routine is matched (meal_id / routine name), not duplicated |
| 4 | Week goals | Note (goals) | → projects/people named in it |
| 5 | Financial goals | Note (finance goals) | → named accounts/people; findable from finance questions |
| 6 | Software engineering knowledge | Knowledge note | → projects it names (e.g. Quintacle); `links:` frontmatter → related |
| 7 | Laptop setup | Note (setup) | → projects named; `links:` → related |
| 8 | Phone setup and apps | Note (setup) | Same as 7 |
| 9 | Grooming plans | Grooming items + routine note | Item notes → people named; the routine references its items by name, not copies |
| 10 | Document drop | Vault document | **✗ any edge, ✗ search index, ✗ graph** (vault invisible) |
| 11 | DC restaurant experience | Experience | → place Washington DC (city stated); → people named (`mentions_person`); → the day (`on_day` / event); ✗ invented city |
| 12 | Experience (generic) | Experience | Same as 11, with no city when none is stated |
| 13 | Date | Activity + experience + person mention | → the person (Mentions note); activity, experience and mention `part_of` one event |
| 14 | Convo with Alfonso | Person mention note under People/Alfonso/Mentions | → Alfonso's profile (`mentions_person`); first-name-only mention still links when he is the only Alfonso |
| 15 | AI setup | Note | Same as 7 |
| 16 | Projects I have done | Project hub notes | → the knowledge/work-log notes that name the project (back-links) |
| 17 | Plan a meal | Meal preset (composition) | → its ingredients (meal_ingredients), saved meals reused, not duplicated |
| 18 | Discuss a show | Chat transcript + extracted facts | Facts → the show's ledger note if it exists |
| 19 | Show ledger | Note(s) per show | → people named; the ledger's own folder hub |
| 20 | Book ledger | Note(s) per book | Same as 19 |
| 21 | Game ledger | Note(s) per game | Same as 19 |
| 22 | Journal & Lore | Journal day + lore note | → people/places named |
| 23 | House plan and catalog | Residence + home items | Items → their residence (folder nesting); → people named |
| 24 | Discuss a financial plan (salaries, savings) | Chat | Answers use **code-computed** income/expense totals; no stored write unless saved |
| 25 | How much I make right now | Income rows | Income `part_of` the event; the same-amount expense removed |
| 26 | Subscriptions | Expense rows (kind subscription) | Date-keyed; `part_of` event |
| 27 | Random expense | Expense row | Date-keyed; `part_of` event |
| 28 | Random food drop → expense + calories | Food row + expense row | **Both `part_of` the same event** |
| 29 | Reflection dashboard | Read-only view | Reads from the graph and logs; nothing written |
| 30 | Docs on IRS, DHS | Vault documents | Same as 10: invisible |
| 31 | CX-5 things (pricing, fixing) | Notes under Organisation/Car + expenses | Car notes → each other via `links:`; repair expenses `part_of` their event |
| 32 | Insta & LinkedIn stuff | Notes | → people named; → projects named |
| 33 | Monthly budgeting | Note / view | Reads code-computed totals |
| 34 | Outfit drop | Wardrobe items / outfit | Item notes → people/experiences named in the description |
| 35 | People | Person profile | → every note/journal/experience naming them (back-links via mention backfill) |
| 36 | Business plans | Note under Business | → people named; → projects named |
| 37 | Contract plans (side hustles) | Notes | → people/companies named (e.g. Minfy); → work logs |
| 38 | Knowledge | Knowledge note | `links:` → related; → people/places named |

## Known gaps found while writing this (2026-11-11)

- The graph matcher needs the **full name**. "coffee with Arjun" makes no `mentions_person` edge to Arjun Mehta,
  the same gap fixed today in drop detection, one layer down.
- Work logs saved from Oct 21 on have `links: []`; earlier ones link Minfy/Quintacle.
- The place backfill was never applied to the real store (0 place nodes).
- Folder "about" hub notes don't link to the notes in their folder.

## Status

The tests are being written (see `core/tests/claude/existing/test_graph_categories_*.py` and
`core/tests/user/`). Add dated results here.

### 2026-11-11 (later): gap fixes, deterministic code only

Status note added after the fact; the gap list above is left as written.

- **First names.** A person's first name now links when exactly one tracked person has it. The rule is the drop
  detector's: `people/store.unique_first_names`, which moved out of `people/llm.py`. The name only counts when it
  is capitalized, so "I will" never links a tracked Will. Code: `graph.candidate_mentioned` and
  `graph.proper_name_mentioned`.
- **Hubs and accounts as candidates.** Career/Projects hub notes and finance accounts are now link candidates, with
  edge kind `related`.
  - Hubs are found the way the work-log importer finds them (`logs/worklog.entity_notes`).
  - Only folder-hub notes count. Deeper notes such as "Design" do not.
  - Code: `graph_capture.entity_hub_candidates` and `graph_capture.account_candidates`.
- **Back-links on create.** Creating a person (`people/api.create_person`) or a hub (`projects/api._index_new_note`,
  `career/api` hub create) now runs the backfill's scan for that one target right away
  (`graph_capture.backlink_new_target`, provenance `backlink`).
- **Known places.** A city that is already a place node links on mention (`at_location`, provenance `known_place`).
  - Place nodes include `place:…/<city>` nodes and `note:places/<slug>`.
  - The 3-source threshold now only decides when a new place is created.
  - Code: `graph_capture.known_place_links`.
- **Experience → day.** An experience gets `on_day` to `journal:<visited_date>` when that day exists. This works
  in either save order. Code: `graph_capture.visited_day_link` and `visited_day_links_for_day`.
- **Folder charter hubs.** Each note in a folder is `part_of` that folder's `about-<folder>` note (provenance
  `folder_hub`). This happens when the note is saved, when the hub is saved (it links the existing notes), and in
  the backfill. Code: `graph_capture.folder_hub_links`.
