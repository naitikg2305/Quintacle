# Live model testing: report (2026-11-11)

Decision log. Don't rewrite this; add dated notes at the bottom.

## Why this exists

During hands-on testing the owner dropped the same Austria itinerary PDF that had sorted well days
earlier. This time it landed in the **Documents vault** as a "document".

- **Cause:** the 2026-11-07 local-PDF change. PDFs used to be sent to Claude, which handed the sorter
  a short summary. Now pypdf extracts the raw text locally, so qwen3:8b got 7,000 characters of
  flights and bookings plus a vague question ("is this formal paperwork… or similar?"), and answered
  yes. The same flaw had earlier turned a flight ticket into a "lease".
- **Why no test caught it:** the 1,150 existing tests replace every model with a fake that returns a
  fixed answer. They test the code *around* the models and can never catch a model making a wrong
  call.
- **Why the golden check didn't catch it either:** it compares each run to *what the app did last
  time*, not to *what is right*. A wrong answer, once recorded, becomes the baseline.

## Testing strategy (owner's design)

| Folder | What runs | Models | Who writes the expectations |
|---|---|---|---|
| `core/tests/claude/existing/` | The original code tests (1,150, now 1,303) | **Faked.** Any network call to Ollama is blocked, so a stray real call fails fast instead of hanging | Claude |
| `core/tests/claude/local/` | Real decisions on **local models** (Ollama: qwen3:8b, qwen2.5vl:3b, RapidOCR, YOLOX) | Real. **Cloud blocked**: a step that only works with Claude fails with "cloud call blocked" | Claude, from product intent |
| `core/tests/claude/subscription_or_api/` | The **same checks** on real **Claude via the Max subscription** (`claude -p`) | Real. **Metered-API fallback blocked** (including chat's own fallback), and each test asserts a Max call happened | Claude, from product intent |
| `core/tests/user/` | The owner's tests, fed by his testing folder (`~/Desktop/Quintacle Product Testing, files and commands/`) | Real | **The owner.** Built with him, one feature at a time. Nothing goes in that he hasn't confirmed |

### Rules

- **Expectations are decided before running, from what the product should do.** A failure is a
  finding about the model or the code, never a reason to loosen the assertion. Loose matching is
  allowed only for free text (titles, descriptions).
- **One input set, two models.** The checks live once in `core/tests/claude/*_cases.py`. The local
  and Max suites both run them with `provider="local"` or `provider="cloud"`. That shows whether a bug
  is in the code (both fail) or in the model (one fails).
- **Each suite runs in a sandbox data dir seeded with presets** (meals, a routine, travel/knowledge
  notes), as CLAUDE.md requires for model-quality tests. The owner's real USDA db and GeoNames data
  are only *read*. `~/.quintacle` is never written.
- **`pytest` alone runs only `existing/`**, because the live suites are slow. Run each suite in its
  own call:
  ```
  cd core
  .venv/bin/python -m pytest -q                                  # faked, ~2 min
  .venv/bin/python -m pytest tests/claude/local -q               # real local models, ~6–17 min
  .venv/bin/python -m pytest tests/claude/subscription_or_api -q # real Claude via Max, ~17 min
  ```
- **Run the live suites before committing any change to drop, sorting, parsing, perception, nutrition
  or chat.** A green faked suite is not enough there.

### How the tests were added

1. The first 9 sorting checks were written by hand around the bug that started this: trip-plan PDF,
   trip-plan .md, e-ticket, passport, insurance policy, lecture notes, journal line, meal plan, and a
   rendered nutrition label.
2. 10 agents each wrote one area's checks in parallel, in separate files: photos, chat + privacy +
   transcripts, nutrition, travel + place graph, journal + day view, finance, files (docx/xlsx/pptx/md
   with images/PDF metadata/scans), MCP tools (including a real `claude -p` end-to-end into a sandbox),
   presets, wardrobe/grooming/home.
   - **They only wrote tests.** One GPU can't run ten model suites at once, so Claude ran every suite
     afterwards, one at a time.
   - Each check carries a one-line docstring saying why its answer is right.
3. Claude ran both suites, sorted each failure into "code bug", "model bug" or "test bug", and sent
   7 fix agents to work in isolated worktrees.
   - Each fix came with faked unit tests in `existing/`.
   - The fixes were merged, the suites rerun, and the cycle repeated until done.
4. A coverage audit (`docs/testing/model-coverage-2026-11-11.md`) lists every place the app makes a
   model decision and which live check covers it, so the gaps are visible.

## Results

| Run | Local (Ollama) | Claude via Max |
|---|---|---|
| Before fixes | 47 pass · 16 fail · 2 skip | 48 pass · 12 fail · 2 skip |
| After the first 4 fix branches | 56 pass · 8 fail · 1 skip | — |
| After all fixes | FINAL_LOCAL | FINAL_MAX |

The faked suite went from 1,150 to 1,303 tests, all passing.

## What was fixed

Each entry is symptom → cause → fix (commit).

1. **The trip-plan PDF and flight ticket were sorted as vault documents.**
   - Cause: raw local PDF text plus a vague classifier question.
   - Fix: code catches itineraries, tickets and bookings first; a precise question with explicit
     negatives; the model sees only the first 3,000 characters (`9c362a1`).
2. **A meal-plan sort took more than 5 minutes locally.**
   - Cause: the model was asked to guess 30 micronutrients for every ingredient, about 4,000 tokens
     thrown away whenever USDA matched.
   - Fix: the model now gives names, grams and macros only. Micros come from USDA, and are estimated
     only for unmatched foods (`77cef1c`).
3. **The faked suite could hang.**
   - Cause: an unstubbed call reached the real Ollama and queued behind the GPU.
   - Fix: any request to Ollama's port is blocked in `existing/` (`77cef1c`).
4. **Excel and PowerPoint drops were never read ("no description").**
   - Fix: stdlib/openpyxl readers for xlsx and pptx, plus a best-effort reader for legacy xls/ppt
     (`5aabaa3`).
5. **A .md with a local image saved a broken link.**
   - Cause: the asset got renamed (`raft_roles.png` → `raft-roles.png`) but the link didn't.
   - Fix: links are rewritten to the saved name (`5aabaa3`).
6. **A trip plan saved from a drop never joined the place graph.**
   - Fix: destinations are derived in code from the folder and from city/country names (a new
     gazetteer of about 300 cities, never reading ambiguous names), at save time and in the backfill.
     The review card shows them for editing (`0bfe0e5`).
7. **"Someday I want to see the northern lights in Tromsø" landed in Travel/Goals or
   Travel/Wishlist.**
   - Fix: a deterministic bucket-wish proposal into Fun/Travel/Bucket List (`0bfe0e5`).
8. **The `ingredient:` and `recipe:` prefixes ignored the local/cloud choice.**
   - Fix: the provider is threaded through every prefix lane (`b7616bb`).
9. **An `ingredient:` name was raw text** ("Fage 0% greek yogurt, per 170g: 90 kcal…").
   - Fix: the food name is cut out in code (`b7616bb`).
10. **A recipe made from saved meals created duplicate ingredients.**
    - Fix: components match saved meals, and saving expands them instead of duplicating (`b7616bb`).
11. **"Got paid $3,200 from Minfy" became an expense or an activity.**
    - Fix: a regex-gated income proposal that removes the same-amount expense (`b7616bb`).
12. **Wardrobe and grooming text drops, and the outfit/routine composers, were cloud-only.**
    - Fix: they go through local-first `parse_structured` (`39d5600`).
13. **"CeraVe Hydrating Cleanser" got merged into the saved "CeraVe Foaming Cleanser".**
    - Fix: stricter item-name matching for the wardrobe and grooming stores (`39d5600`).
14. **Photos with GPS called Claude to geocode, even in local mode.**
    - Fix: an offline GeoNames reverse geocoder. Local mode never calls the cloud; auto mode tries
      offline first (`39d5600`).
    - Data was installed into `~/.quintacle/geonames` and recorded in the libraries Knowledge note.
15. **The local model invented a home item's price, location and exact purchase date.**
    - Fix: a stricter prompt plus a code guard that keeps only what the text states, and keeps the
      warranty (`2b4f06d`).
16. **A passport photo through Claude had no expiry date.**
    - Cause: the vision caption summarised the page and dropped the dates.
    - Fix: document photos are transcribed word for word, and labelled dates are read in code, with
      the passport's machine-readable zone as a fallback (`2b4f06d`).
17. **"Yesterday I spent $15" had no date.**
    - Fix: relative dates are resolved in code after the parse, never trusting the model for
      arithmetic; "8/10" can't be read as a date (`41ea730`).
18. **"chicken rice bowl plus a greek yogurt bowl" linked only one saved meal.**
    - Fix: split into one food entry per saved meal (`41ea730`).
19. **Selenium in lamb had "no published value".**
    - Cause: the Foundation entry has 15 nutrients; its SR Legacy sibling has 46.
    - Fix: missing nutrients are filled from the same food's sibling entry, and the source entry is
      named (`194a25a`).
20. **Bank-statement PDFs needed Claude.**
    - Fix: rows are parsed in code locally, the local model handles only leftover lines, and dates
      are normalised to ISO in code (`194a25a`).
21. **The local model dropped the brand from an item name.**
    - Fix: the typed name wins when the model's name is just a subset of it, adding at most 3 words
      (`6837fd4`, `8d789a8`).
22. **Test bugs, fixed in the tests:**
    - the sleep check didn't accept "slept" (`7ff8efc`);
    - the MCP search check didn't expect the new place nodes to rank above the note (`6837fd4`).

## What was learned

- **Faked tests and live tests answer different questions.** Faked tests prove the code does what it
  should with a given model answer. Only live tests prove the model gives that answer. Every model
  decision point needs a live check through the endpoint the user actually hits.
- **A baseline is not a spec.** "Same as last time" turns past mistakes into requirements. The
  expected result has to be written down from intent, by a person, before the run.
- **Changing a model's input is a model change.** Swapping a cloud summary for raw local text changed
  the behaviour as much as swapping the model would have. Any change to what a model sees needs the
  live suite.
- **Run the same check on both models.** When local and Claude both fail, the bug is in the code. When
  only one fails, it's the model or its prompt. This sorted 28 failures quickly.
- **Move decisions out of the model wherever code can make them.** That covers dates, names, money,
  sibling USDA rows, statement rows, itinerary detection, place names and passport dates. Most fixes
  here were code taking a decision back from a model. Small local models are good at language and bad
  at arithmetic and at not inventing things.
- **Ask the model only for what you'll use.** Guessing 30 micros per ingredient cost minutes and was
  thrown away. Output tokens are the slowest part of local inference.
- **Size local context windows to the job.** Measured on real data, the longest call was about 4.9k
  tokens of input plus output; 16k is reserved for chat. This ties into the GPU memory finding: qwen3:8b
  at 16k plus qwen2.5vl don't both fit in 12 GB.
- **"Local-first" needs enforcing by tests, or it erodes.** The local suite blocks the cloud, and it
  found wardrobe, grooming, geocoding and statements quietly calling Claude.
- **Check the exit code, not just the summary line.** A piped `tail` hid a failing test and let it be
  committed once (fixed in the next commit).
- **Parallel agents work when the boundaries are file-level.** Writers each owned their own files;
  fixers each worked in a worktree on one area. There was one merge conflict in 10 branches (api.py),
  resolved by keeping both sides.

## Open

- [ ] Owner's tests in `core/tests/user/`, built with him from the testing folder, piece by piece.
- [ ] The outfit-photo case (a person wearing an outfit sorted as one item) needs a real photo, so it
      goes in `tests/user`.
- [ ] Close the gaps listed in `docs/testing/model-coverage-2026-11-11.md`.
- [ ] Context sizing (an 8k default, stepping up when needed) to stop VRAM contention between qwen3:8b
      and qwen2.5vl.
- [ ] `place_slug("Tromsø")` gives `troms`; non-ASCII letters (ø, ł, æ) are dropped in place ids.
- [ ] The per-micro `from_fdc_id` from USDA sibling fills isn't persisted; it can be recomputed.
