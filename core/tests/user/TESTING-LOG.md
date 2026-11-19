# Owner testing log (master)

One entry per thing the owner tried, in order. Each entry records:
- the input (file or prompt, copied into `files/`);
- what local produced, then what Claude produced ("Redo with cloud");
- what the owner expected;
- the test that pins it down.

Results are pasted from the app as-is. Expectations are the owner's words. Where Claude proposes one, it is
marked *(draft, owner to confirm)*.

Store state at the start (2026-11-13): food and travel data wiped. Backup:
`~/.quintacle-backup-20261113-before-wipe/`. Notes, work logs and journal kept.

---

## T1. Austria itinerary PDF drop (#1 Travel itinerary) · 2026-11-13

**Input:** `files/travel/Austria_drop.pdf`. Owner's testing folder `Travel Files/Austria_drop.pdf`; 4 pages,
a 10-day Budapest → Vienna → Salzburg → Prague plan, May 12–21 2027. Dropped as a file with no text, then
**Sort with AI**.

### Local (qwen3:8b; backend log shows no cloud fallback)

Screenshot: `files/travel/austria_drop-local-2026-11-13.png`

| Field | Got |
|---|---|
| Type | KB entry (not a vault document ✓) |
| Folder | `Fun/Travel/Planned/Europe` |
| Title | `Central Europe 2027 Itinerary` |
| Private | off |
| File info | PDF · "Central Europe \| 10-Day Trip Plan" · 4 pages · created 2026-11-05 by ChatGPT · 77 KB |
| Content | The PDF's extracted text |
| Links | `About Travel` |
| Destinations | `Budapest, Hungary; Vienna, Salzburg, Hallstatt, Linz, Austria; Prague, Czechia; Frankfurt, Germany` |

**Findings (Claude, for the owner to confirm):**
1. **Destinations include places that aren't destinations.**
   - Hallstatt is one optional excursion.
   - Linz is a train change.
   - Frankfurt is a flight layover.

   The list comes from *code*, not the model: `place_graph.derive_destinations` takes every gazetteer city
   named anywhere in the text. So the same list will appear on the cloud result.
2. **`About Travel` link.** No `about-travel` note exists under Fun/Travel right now, so this link would point
   at nothing. To check after Save.

### Claude (Redo with cloud)

Screenshot: shared in chat (not saved; no file path).

| Field | Got |
|---|---|
| Type | KB entry, badge "read via cloud" ✓ |
| Folder | `Fun/Travel/Planned/Central E…` (cut off in the screenshot) |
| Title | `Central Europe Trip Plan 2027` |
| Content | **A summary, not the PDF text** (see the quote below) |
| Links | empty |
| Destinations | `Budapest, Hungary; Vienna, Salzburg, Austria; Prague, Czechia` ✓ |

Content Claude wrote:
> This is a planning document for a 10-day Central Europe trip from May 12 to 21, 2027, covering Budapest,
> Vienna, Salzburg, and Prague, with rail between cities and a open-jaw flight from Washington Dulles (IAD)
> into Budapest (BUD) and out of Prague (PRG). It includes a day-by-day itinerary, four selected 4-star
> hotels, transport durations, and an illustrative solo budget of roughly $2,340–4,010 excluding visas.
> Nothing is booked yet: flights, hotels, and train times are marked as unverified, and the sources were
> checked on November 5, 2026. The document also flags entry requirements (Schengen travel permission and
> the traveler's F-1/STEM OPT and US re-entry documents) and recommends a booking order that starts with
> confirming work leave and visa timing.

**Local vs Claude:**
- **Destinations.** Claude's list was right only because the code read its *summary*, which never mentions
  Frankfurt or Linz. The same code over local's full text picked up the layover. The layover fix below makes
  them agree.
- **Content.** Local keeps the full PDF text; Claude writes a summary. Which one the note should hold is an
  open question for the owner.
- **Title.** Claude puts the year in the title (owner would like the year in the folder too, fixed at
  review).

### Expected (owner, 2026-11-13)

- A KB entry under `Fun/Travel/Planned/…`, never the Document Vault.
- Destinations include Budapest, Vienna, Salzburg and Prague.
- The optional excursion (Hallstatt) is fine.
- The flight layover (Frankfurt) must not be listed.
- Linz (train change) is treated like a layover *(draft, owner to confirm)*.
- The year in the folder is fixed at review, so it is not tested.

### Fix

`gazetteer.find_places` skips a city mentioned only in passing ("via Linz", "1 change, often Linz",
"layover in", the middle of a "(PRG) to Frankfurt (FRA) to" flight chain). A city named any other way still
counts. Faked tests: `existing/test_gazetteer_transit.py`. Not live in the running backend until restart.

**Test:** `test_t01_austria_drop.py`. Local: failed on Frankfurt and Linz before the fix, 3/3 pass after.
Cloud: not run yet.

### T1 rerun, 2026-11-13: after the folder tree and exact typed links

- Merged: the folder tree (every folder is a graph node, chained to its parent) and exact,
  capitalization-insensitive, instant typed links.
- The test now also saves the entry the way the app's Save does, then checks the graph:
  - the folder chain: trip → Europe 2027 → Planned → Travel → Fun;
  - each city → its country → Europe;
  - no Frankfurt or Linz;
  - no vault.
- **Local 8/8 pass. Claude 8/8 pass.** Faked suite 1,529 pass, tsc 0.
- The backend was restarted. Startup built 107 folder-tree edges on the owner's store.

---

## T2. NYC 2028 trip: chat, then drop (#1 Travel itinerary) · 2026-11-13

**Order (owner):**
1. local chat;
2. local drop of the answer saved as `local_itinerary`;
3. Claude drop (Redo with cloud);
4. Claude chat;
5. then local and Claude drops of the Claude answer.

**Prompt (chat, local):** `plan a trip to new york city in 2028 5 days?`

### Chat, local (07:05)

Transcript: `files/travel/nyc-2028/chat-local-2026-11-13.md` (copied from the store as-is).

**Findings (Claude, for the owner to confirm):**
1. **"All five boroughs" wasn't asked.** An earlier chat ("plan a new york trip 2027 5 days all 5 boroughs")
   seems to have carried over.
2. **The day count doesn't add up.** Day 4 already returns to DC; Day 5 "departure from DC"; the budget says 5
   nights. Dates May 15–19.
3. **Wrong boroughs:**
   - The Bowery Hotel and Hotel Gansevoort are in Manhattan, not Brooklyn or the Bronx.
   - The William Vale is in Brooklyn, not Queens.
   - Tompkins Square Park is in Manhattan, not Staten Island.
4. **Wrong facts:**
   - The River Café isn't Italian at $45.
   - It says to book flights via Expedia on a train trip.
   - It suggests checking the Thanksgiving Parade for a May trip.
5. **It says "links in Quintacle note."** No such note exists. This is the likely source of the "Quintacle"
   tag the owner saw: hub names are linked when named.
6. **Empty images:** some image slots render as empty `()`.

**Owner noted:** after the local push, the only tag created was "Quintacle", and the link wasn't under a
folder. The store shows no write since 04:35, so to check after the next Save.

### A. Drop of the local chat answer, local (07:35)

**How it was dropped:** the chat's send-to-Drop button, which makes `chat-draft.md` from the whole answer
(`ChatLog.tsx` `messageToFile`).

**Input:** `files/travel/nyc-2028/local_itinerary.md`. This is the answer text from the transcript, 5.2 KB,
the same size as on the card.

Screenshot: `files/travel/nyc-2028/drop-local-of-local-chat-2026-11-13.png`

| Field | Got |
|---|---|
| Type | KB entry ✓ |
| Folder | `Fun/Travel/Planned/New Yor…` (cut off; year not visible) |
| Title | `2028 NYC 5-Day Trip Itinerary` |
| File info | MD · chat-draft.md · 5.2 KB |
| Content | The answer's full text |
| Links | `Quintacle` ✗ |
| Destinations | `New York, United States` ✓ (no Washington DC ✓) |

**Findings (Claude, for the owner to confirm):**
1. **`Quintacle` link.** The answer says "links in Quintacle note". A Quintacle note does exist (the project
   hub), so the existing-links check keeps it. The trip has nothing to do with the project.
2. **Folder.** Is the year there? The body has dates 2028-05-15 to 05-19, so the expected folder is
   `Fun/Travel/Planned/New York 2028`. To confirm the full value.

**A was saved by the owner,** with the title edited to `2028 NYC 5-Day Trip Itinerary(local+local)` and the
Quintacle link kept. Checked in the store, read-only:
- Folder: `fun/travel/planned/new-york-2028` ✓. The year was added by code.
- Graph:
  - note → `folder:…/new-york-2028` → planned → travel → fun ✓
  - note → `place:…/new-york` → united-states → north-america ✓
  - note → `note:projects/quintacle/quintacle` (`frontmatter_links`, the kept chip) ✗ wrong link
  - note → an event of its own (`same_event`, one member)
- Assets: the Wikipedia thumbnails in the answer were downloaded into `assets/` on Save, and the stored
  `chat-draft.md` is 3,115 bytes, not 5.2 KB.

### B. Same drop, Redo with cloud (07:38)

Screenshot: `files/travel/nyc-2028/drop-cloud-of-local-chat-2026-11-13.png`

| Field | Got |
|---|---|
| Folder | `fun/travel/planned/new-york` (slug style; cut off? year not visible) |
| Title | `2028 NYC Five-Borough Itinerary` + owner's `(local+claude)` |
| Content | Starts with the answer's own text ("I'll plan a 5-day trip…"), not a summary as in T1 |
| Links | owner typed `2028 NYC 5-Day Trip Itinerary(local+local)` (the A note) |
| Destinations | `New York, United States` ✓ |
| Quintacle link | not suggested ✓ |

**B was saved by the owner** as `2028 NYC Five-Borough Itinerary(local+claude)`, in the same
`new-york-2028` folder (so the full folder did carry the year ✓). Graph:
- B → A via the typed link (`frontmatter_links`) ✓
- B → the folder chain ✓
- B → New York ✓
- B → `projects/quintacle/quintacle` via **`ai_link`** ✗. There was no chip: the code name-matcher
  (`graph_capture.entry_graph_links`) linked it because the text says "Quintacle note". So deleting the chip
  does NOT stop it. A has no `ai_link` edge only because its chip edge was already there.

### C. Chat escalated to Claude, same session (07:40)

Transcript (local answer + Claude answer): `files/travel/nyc-2028/chat-local-then-claude-2026-11-13.md`.
Claude's answer alone: `files/travel/nyc-2028/claude_itinerary.md` (6.8 KB).

**What Claude did:**
- Found both saved notes, A and B, in the knowledge base and linked them.
- Called them duplicates.
- Listed the local draft's errors: the same six the log found under the local chat, plus "MetroCard is gone (OMNY)".
- Rebuilt the plan:
  - kept the draft's dates, May 15–19 2028 (correct: Mon–Fri);
  - one hotel, all five boroughs, a coherent Day 5 return;
  - a budget table, and booking timing instead of fake booking IDs.
- Offered to "Record this as a corrected version and delete one of the duplicate notes."

**Note:** it carried over "all five boroughs" from the local draft, which was itself the carry-over noted
above.

**Finding: Claude offered an action chat cannot take ("delete one of the duplicate notes").**
- Chat is read-only. It's single-shot with no tool turns (`chat.py`); web search is its only tool.
- "Record that" (`nodes/kb/api.py` `/record-that`) only proposes a dated append, reviewed and saved by the
  owner. It never deletes or rewrites.
- So "yes" just gets more text. Deletes happen only by the owner's hand in the app, or through MCP (undoable).
- The fix would be in chat's prompt, which is off-limits (`chat.py` prompting stays untouched). Owner to
  decide.

**Finding: a drop that saves with the same folder and title as an existing note silently replaces it.**
- `KBStore.write` keys the file by folder + slugified title. It replaces the body and keeps the old metadata.
- There's no warning and no append (`nodes/kb/api.py` `create_entry`).
- Here, A and B differed only because the owner edited the titles.
- Owner to decide: today drop has only "new note". Offering "append to / replace <existing note>" on the
  card would be a new feature.

### D and E. Drops of Claude's chat answer, local (D) and cloud (E) · 07:48 / 07:51

**Input:** `files/travel/nyc-2028/claude_itinerary.md`. The owner sent it from chat with send-to-Drop.
Screenshot (E): `files/travel/nyc-2028/drop-cloud-of-claude-chat-2026-11-13.png`.

| | D: local | E: Claude |
|---|---|---|
| Title (owner-edited) | `2028 NYC 5-Day Trip Itinerary(claude+local)` | `NYC, 5 days in 2028: a new plan(calude+claude)` |
| Folder | `new-york-2028` ✓ | `new-york-2028` ✓ |
| Links | none ✓ | none ✓ |
| Destinations | `New York, United States; Italy` ✗ | `New York, United States; Italy` ✗ |

**Italy:** from "the Bronx's real Little Italy". It's code (`gazetteer.find_places`), so local and Claude
agree. A fix was written before asking. The owner OK'd it after the fact; it's uncommitted and not run.

### All four saved notes, in the store (read-only, after "pushed all")

| Note | Folder chain | New York | Wrong links |
|---|---|---|---|
| A local+local | ✓ | ✓ | Quintacle (chip) |
| B local+claude | ✓ | ✓ | Quintacle (`ai_link`, no chip) |
| D claude+local | ✓ | ✓ | `place:europe/italy` |
| E claude+claude | ✓ | ✓ | `place:europe/italy` |

**Other links and side effects:**
- B → A (typed link) ✓.
- D and E link to A and B only as `/kb/browse` URLs in the body, not as graph edges.
- Saving D created a new `place:europe/italy` → `place:europe` node.
- D and E also have a second New York edge (`known_place`): New York had become a known place after three
  notes.
- Each note got its own one-member event.
- No overwrite happened: all four titles were distinct.
- D and E keep the chat's "delete one of the duplicate notes?" line in their body.

**Expected (owner, to confirm in the test):**
- Every NYC drop lands in `Fun/Travel/Planned/New York 2028`.
- Destinations are only New York. No Washington DC (the origin), no Italy.
- No Quintacle link (chip or `ai_link`).
- Each saved note sits in the folder chain and links to New York → US → North America.

### T2 test: `test_t02_nyc_2028_chat.py` (written, not run)

**Redoes the session in order:**
1. local chat;
2. drop the answer locally, Save A;
3. Redo with cloud, Save B with a typed link to A;
4. escalate the chat to Claude;
5. drop Claude's answer locally, Save D;
6. Redo with cloud, Save E.

**Sandbox:** a copy of the real store without today's NYC folder and chat, so the knowledge base is as it was
before step 1.

**Owner confirmed (2026-11-13):** "all five boroughs" when not asked, and offering to delete, both count as
failures.

**Correction to the C entry above:** escalating does NOT send the local answer. `page.tsx` `escalate` re-sends
`chatLog.slice(0, i)`, which is only the question. Claude knew the local plan's errors from notes A and B in
the knowledge base, not from the chat.

### Fix (owner-requested, 2026-11-13): a drop never silently overwrites a note

**Owner's ask:** if a drop is the same note, by name or because the AI thinks so, choose append or replace.
Otherwise make a new note, and the AI suggests a nearby name, not "(2)".

**At drop time** (`drop_existing.py`):
- **Same name** (code): the card's title switches to the AI's nearby name.
- **AI pick:** the model sees the notes in the folder. Code keeps the pick only if that note exists.
- **Card:** says which note matched and offers Keep both (default) / Append to it / Replace its text.
- **Private cards** get the same-name check only, with no model call.

**Save** (`on_conflict`):
- **new:** refuses to overwrite (409), before any asset is written.
- **append:** adds a dated "## Added" section; keeps the note's text, links and fields.
- **replace:** replaces the text; keeps links and fields.
- **No on_conflict sent** (Browse edit): the old in-place save.

**Tests:** faked `existing/test_drop_existing.py` (15). T1 and T2 now save with `on_conflict=new`. Not run
yet.

### Cleanup and asset fix (owner-requested, 2026-11-13)

**Deleted B, D and E from the real store** (the owner asked to keep only A):
- Backup: `~/.quintacle-backup-20261113-before-nyc-delete/`.
- Removed their edges, index rows, the 7 images only D and E used, and `place:europe/italy`.

**Bug: all four notes shared one `assets/chat-draft.md`.** `KBStore.save_asset` wrote over a same-named file,
so A's file held E's text.

**Fix:**
- `save_asset` now picks a free name (`-2`, …) via `free_asset_path`.
- Deliberate overwrite stays `replace_asset`.
- Faked test: `test_each_note_keeps_its_own_attached_file`.

**A's file restored:** rebuilt from `local_itinerary.md` with images pointed at their local copies, 3,115
bytes, the same as the first save.

## Bug B1. Browse: going back up a folder shows the opened note everywhere, plus a fetch error · 2026-11-13

**Owner:** opened a note, went back up a folder, got a fetch error, and the opened file appeared in every
directory.

**Backend log:**
1. The note `europe-2026/northstar-travel-demo-flight-itinerary` was opened.
2. After going back up, `GET /kb/entry?folder=fun/travel/planned&slug=northstar-…` returned 404.
3. Its PDF was requested from `fun/travel/planned` and `fun/travel`, also 404.

**Cause:** `browse/page.tsx` loads a folder's lists in the background. A late answer for the folder just left
overwrote the new folder's lists, and a late-opened note re-appeared after leaving. Clicking a stale tile
fetched it with the current folder (404).

**Fix (frontend only):**
- A folder's lists are cleared on navigation.
- Answers for a folder you've left are ignored.
- A note opens only if you're still in its folder.

tsc 0; eslint no new errors (the same 3 pre-existing set-state-in-effect errors).

**B1 correction (owner):** the trigger is clicking a breadcrumb **folder name** while a note or PDF is open. It
wasn't the Back button, and nothing had moved.

**Two problems:**
1. For one render the open PDF's preview pointed at the clicked folder. The iframe fetched it there: the 404
   fetch errors.
2. Clicking the folder already shown changed nothing, so the file stayed open: stuck.

**Fix:** breadcrumb, root and folder-tile clicks go through `goTo()`. It closes the open file in the same click
as the folder change, and it works on the current folder too. tsc 0; eslint the same 3 pre-existing errors.

**B1, round 3 (owner, 10:55):** with a PDF open, clicking a breadcrumb folder still showed 4 "Failed to fetch"
errors: listKBEntries, listKBFiles, listKBEntriesMeta, getKBView.
- **Backend log:** all 4 requests arrived and returned 200. So the browser cut them off; they didn't fail.
- **Likely cause:** they start in the same click that removes the PDF viewer iframe, and Chrome drops them.
  Not reproduced here (no browser automation).
- **Fix:**
  1. With a file open, `goTo` closes it first and changes folder about 50 ms later.
  2. Each folder load retries once after 300 ms.
  3. A real failure shows in the status line instead of an unhandled-rejection overlay.

tsc 0; eslint the same 3 pre-existing errors.

### B1, round 4 (2026-11-13): the real cause was CORS
- Owner's console: `Access-Control-Allow-Origin` was `http://localhost:8000`, not the page's `localhost:3000`; requests reached the backend (200) and Chrome blocked the replies. After a PDF iframe (origin :8000) was open, Chrome stamped folder fetches with Origin :8000; the backend (credentials on) echoed it back.
- Fix (owner OK'd): `api.py` CORS `allow_credentials=False` -> plain `*` (no client sends cookies). Round 3's 50 ms delay + retry removed (wrong cause). Backend restarted; `curl` with Origin :8000 now gets `*`. tsc 0.

### B1, round 5 (2026-11-13): not a Quintacle bug
- After the CORS change the backend sends `*` to every origin (curl-verified), yet Chrome still reported `Access-Control-Allow-Origin: http://localhost:8000` -> a browser extension in the owner's normal profile rewrites the header (it takes the PDF iframe's :8000 as the tab origin). **Incognito: works.** Closed.
- Owner kept the `allow_credentials=False` change (harmless; nothing sends credentials).

## T3 — DC → Vienna flight ticket 2027 (2026-11-13)
- Owner dropped `sample_dc_europe_flight_2027.pdf` (IAD → VIE 15–25 May 2027, via Frankfurt both ways), Sort with AI, Save. It filed itself into the EXISTING `fun/travel/planned/europe-2027` (T1's trip folder) as "2027 Europe Travel Itinerary (Sample)", destinations Vienna, Austria, linked to "2027 Central Europe 10-Day Trip Itinerary".
- Graph after Save (real store): frontmatter link → itinerary note; Vienna (known_place + place_graph); folder tree; one event.
- Test: `core/tests/user/travel/test_t03_europe_2027_flight.py` (file copied to `files/travel/`). Sandbox = real store minus the owner's saved note (files, edges, index). Not run yet.
- Draft expectation for the owner: the ticket is NOT offered as a version of the itinerary (no Append/Replace choice).

## Brazil chat → drop: wrong destinations (2026-11-13)
- Owner sent a Claude chat answer (Brazil plan) to Drop; the card's destinations read "Rio de Janeiro, Brazil; Miami, Atlanta, New York, United States; Budapest, Hungary". Destinations are code-derived (`place_graph.derive_destinations` → `gazetteer.find_places`). The text did name them: "connect once in the US (Miami, Atlanta, Houston or New York)" and "nightlife (like Budapest)".
- Fix (owner OK'd, chose the BROAD comparison rule): `gazetteer.py`
  - connection lists: a city after via/connect/layover/stopover/change planes in the same sentence (`;` or `.` ends it) is skipped unless a to/into/then comes between;
  - comparisons: a place right after like / such as / similar to / compared to is skipped (owner accepted "beach towns like Paraty" drops Paraty).
- Checked T1–T3 texts: only "…via OBB; compare Salzburg-Prague…" was in reach, kept by the `;` stop.
- Faked tests added to `test_gazetteer_transit.py`. Not run yet.

## Run 2026-11-13 (after the drop-existing, asset, CORS and gazetteer changes)
- Faked suite: 1559 passed.
- T1 local 8/8, T1 Claude (Max) 8/8.
- T3 Claude 10/10. T3 local 8/10: the local model proposed NO links, so the ticket isn't linked to the itinerary (card + graph). Everything else passed (existing folder, Vienna only, no version match, folder tree).
- T2 37/38: Claude's chat answer said "a tighter version with … all five boroughs" (the expectation the owner set: no all/every five boroughs). Model output; chat prompting is off-limits.

## Trip-folder link fix + rerun (2026-11-13)
- Fix (owner OK'd): `drop_fixups.trip_folder_links` — a note proposed into Fun/Travel/Planned/<trip> links to the notes already in that folder (code, max 10). Faked: 1561 passed.
- Rerun: T3 local 10/10 (link fixed), T1 local 8/8, T1 Claude 8/8.
- T3 Claude 8/10: Claude itself wrote "Vienna, Austria; Frankfurt, Germany" as destinations (the code filter only fills destinations when the model gives none; on this text the code gives Vienna only). Passed in the run before — model variance.
- T2 33/38: all four cards came back as folder "Fun/Travel/Planned" with no trip subfolder (both local and Claude sorts), so the year can't be added; plus the local chat answer said "All five boroughs". Reproduced directly: the sort model returns 'Fun/Travel/Planned' itself; no code changed its prompt or input (nodes/kb/llm.py untouched, real store unchanged since run 1, which passed these). Open for the owner: code fixes for both (see session).

## T4: full-day meal plan chat (2026-11-17, in progress)

Owner asked the local chat for a full-day plan (180-200 g protein, under 2,500 kcal, all micros/macros),
dropped the answer (local+local, local+claude, not saved), then escalated to Claude. Files:
`files/food/meal-plan-2026-11-17/`. Test: `test_t04_full_day_meal_plan_chat.py` (DRAFT expectations
need the owner's yes).

- **Chat comparison (owner's own answers):** similarity 0.85; local fact accuracy 53% (6 correct,
  9 partly, 5 wrong). Wrong: 1 oz almonds "15 g protein" (~6), 150 g salmon "50 g" (~30), 1/2 cup lentils
  "18 g" (~9), breakfast "450 kcal" (~950), day "2,400 kcal" (~3,000+, over his limit). Section totals add
  to 221 g, not the stated 180. Report: `reports/T4-owner-session-2026-11-17-1602.md`.
- **local+local:** 3 notes (plan + repeated tips + the closing question) in a new `Nutrition/Meal_Plans`;
  meal = breakfast with both options merged; eggs "2 g"; yogurt 125 g for 1 cup; spinach 80 g for 1 cup.
- **local+claude:** 1 clean note in a new `Health/Nutrition`; meal = dinner stew, amounts right; lamb got
  no USDA match (AI estimate 30 g protein / 280 kcal for 150 g cooked, low).
- **Known limit:** a drop proposes one meal (`api.py` `_propose_preset_entry`). Owner to decide.
- **Follow-up** "okay give me a list of ingredients for an entire day" (picker on local, then escalated):
  local re-listed ITS OWN plan meal by meal with the same wrong numbers, plus Claude's 3 weak-spot items
  (10 g almonds, iodized salt, D3) and a harmful "15 g iodized salt". Claude gave one combined list for
  its 2,255 kcal plan (lamb-for-chicken swap, oil 10+5 g). Comparison: similarity 0.80, local 47%
  (`reports/T4-followup-owner-session-2026-11-17-1609.md`). The judge now gets the earlier turns
  (`chat_compare.compare(context=...)`): without them it wrongly called local's own plan "made up".
  Added to T4 as steps 7-9; DRAFT checks (combined list, no salt over 5 g) fail on local and pass on
  Claude for the owner's answers.
- **To recreate T4 by hand** (exact order, exact text; the full chat is `files/food/meal-plan-2026-11-17/chat.md`):
  1. New chat, picker on local (qwen3:8b). Ask:
     `alright so i want to design a meal thats covers all the nutrients for me in the day. this includes 180-200 g of protein, keeping it under 2500 kcals and all micros and macros.`
  2. Send the local answer to Drop -> Sort with AI (local). Review, don't save. Then Redo with cloud. Don't save.
  3. Escalate that local answer to Claude (Max, Opus).
  4. (Not done by the owner; the test does it) Send Claude's answer to Drop -> local, then Redo with cloud.
  5. Picker still on local. Ask: `okay give me a list of ingredients for an entire day`
  6. Escalate that answer to Claude.
  7. Compare local vs Claude for both questions (`chat_compare.py`, report in `reports/`).
  Automated: `cd core && .venv/bin/python -m pytest tests/user/food/test_t04_full_day_meal_plan_chat.py -q -s`

## T5: lamb label photo -> ingredient (2026-11-17, local done, Claude pending)

Owner dropped `files/food/lamb-label-2026-11-17/13455__2.jpg` (AVIF with a .jpg name; Halal Ground Lamb 85/15,
4 oz = 112 g: 210 kcal, 22 g protein, 13 g fat), Sort with AI (local), renamed it "Costco Lean Lamb", saved.
Next: build a breakfast meal that reuses it. Test: `test_t05_lamb_label_ingredient.py`.

- **Local card** (`drop_local.md`): macros exactly right, 9 printed values from the label. Wrong:
  - named "Safe Handling Instructions" (a heading on the label) instead of lamb;
  - gaps filled from USDA **beef** (round, tip round) instead of lamb, so B12, zinc, etc. are beef's;
  - vitamin D 0.4 mcg (printed) missing;
  - poly 0.5 g / mono 5 g came from USDA (0.52 / 5.6), not the label: the label parser has no rule for them.
- Saved row: "Costco Lean Lamb", fdc_id 169525 (the beef match). Note in Nutrition/Ingredients.

## T6: Greek yogurt label photo, local vs Claude (2026-11-17)

Kirkland plain nonfat Greek yogurt, 2/3 cup = 170 g: 100 kcal, 18 g protein, 7 g carbs, 0 fat; sugars 4, added 0,
chol 10, sodium 65, vit D 0, calcium 220, iron 0, potassium 270. Cards: `files/food/greek-yogurt-label-2026-11-17/`.
Test: `test_t06_greek_yogurt_label.py` (photo: `greek_yogurt_label.jpg`, from Desktop Food recipe/20260908_203808.jpg).

- **Local:** name "Greek yogurt", macros exact, 8 printed values. Missed: potassium (took USDA 240, label 270),
  added sugars.
- **Claude:** name "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)", macros exact, potassium 270, added
  sugars 0. But "30 printed values": **22 nutrients tagged "label" that are not on the label** (vitamin A, B
  vitamins, biotin, choline, magnesium, zinc, selenium, phosphorus, copper, iodine, manganese, molybdenum,
  chloride). Sugars came from USDA (5.56) instead of the printed 4 g; trans fat from USDA (0.0085).
- On this photo local was MORE accurate: Claude's extra values look complete but are invented and mislabeled.

## T7: breakfast chat with his saved lamb (2026-11-17)

Prompt: "okay so planning the balanced day m,eal. breakfast. I have 230 grams of costco lamb, 70 grams of atlantic
salmon, 2 eggs and 50 grams of uncooked rice." Local, then escalated. Chat: `files/food/breakfast-chat-2026-11-17/chat.md`.
Comparison: similarity 0.885, local 50% (`reports/T7-owner-session-2026-11-17-1627.md`). Test: `test_t07_breakfast_chat.py`.

- **Claude:** used the code's USDA numbers for salmon/eggs/rice (421 kcal, 29.7 g protein) and his lamb's 210 kcal/112 g
  -> ~850 kcal, correct. But said the lamb preset "lists no protein or micronutrients" and refused to guess protein.
- **Local:** invented totals (966 kcal, 69.9 g protein, "B12 351%"), salmon omega-3 as ALA, wrong add-ons (1/4 cup
  almonds "70 kcal" ~200; 1 cup cooked spinach "100 kcal" ~41), "Use Quintacle to log".
- **Cause (code, not the models):**
  1. The chat nutrition lane (`nutrition_db/chat_lane.py`) only looks foods up in USDA, never in his saved
     ingredients. "costco lamb" has no USDA match -> no lamb numbers.
  2. A saved ingredient's search-index entry is only "Costco Lean Lamb — 210 kcal / 112 g — ingredient preset",
     so chat sees calories but not protein, fat or micros (the preset has 22 g protein, label + USDA micros).
  Real breakfast: lamb 230 g = 431 kcal / 45 g protein -> ~852 kcal, ~75 g protein.
- The judge got the app name wrong ("made-up app Quintacle"): its prompt now says the app is Quintacle.
- Side note: he saved Claude's yogurt card as "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)".
- **Drops of the LOCAL answer** (`drop_local_local.md`, `drop_local_claude.md`; not saved). Both meals reused his saved
  Costco Lean Lamb (230 g = 45.2 g protein, 431 kcal): the drop's meal composer does read his ingredient library
  (the chat lane doesn't). Both also proposed a breakfast food log with no date and the chat's made-up 966 kcal.
  - local+local: meal "Power Breakfast Boost" also packed in the chat's suggested chicken, sweet potato, oil, spinach,
    almonds (1,282 kcal); eggs "2 g" again; rice an AI estimate (195 kcal, 12 g carbs, no USDA); plus a KB note in a
    new `Nutrition/Meal_Planning`.
  - local+claude: only lamb, salmon (farmed), 2 eggs = 100 g, rice: better. But "basmati rice, cooked" 50 g (65 kcal):
    he has 50 g UNCOOKED rice (~180 kcal). Total 785 kcal / 73.4 g (real ~900 / ~76).
  Added to T7 as step 4 with DRAFT checks.

- 2026-11-17: owner confirmed T7 "right meal" includes amounts (eggs ~100 g, rice uncooked); T3 "not offered as a version of the itinerary" check removed ("never happens dont need to check").
- 2026-11-17: owner confirmed T1: the Linz train change must not show up as a destination.

## Test setup fix (2026-11-17, owner: "I thought sandboxing was doing that")

An independent review found the sandboxes weren't "his data as it was": they copied the whole chat archive
(transcripts.db + soft facts, e.g. "Preparing a balanced meal with 230 grams of Costco lamb" fed into T7's own
replay) and data saved after the test (T1 had its own saved trip; T4 had the lamb/yogurt saved later).
Now every test uses `harness.sandbox_before(chats_from=..., leave_out=..., leave_out_ingredients=...)`:

| Test | Done by hand | Left out |
|---|---|---|
| T1 | 11-13 ~03:30 (after the 03:19 wipe) | all of Planned (Europe 2027/2026, NYC 2028), lamb, yogurt, chats from 03:00 |
| T2 | 11-13 07:05 | NYC 2028, Europe 2026, the T3 ticket + PDF, lamb, yogurt, chats from 07:05 |
| T3 | 11-13 17:40 | the ticket + PDF, lamb, yogurt, chats from 17:40 |
| T4 | 11-17 15:49 | lamb, yogurt, chats from 15:49 |
| T5 | 11-17 before 16:16 | lamb, yogurt, chats from 16:14 |
| T6 | 11-17 before 16:21 | yogurt, chats from 16:18 |
| T7 | 11-17 16:23 | chats from 16:23 |

Leaving out a chat removes its file, its search rows and the soft facts it created. Also: the pass/fail drops in
T2, T4 and T7 now drop HIS saved answers from that day (fresh chat answers are only compared), and T5 saves
under his rename "Costco Lean Lamb".

## Unconfirmed checks are report-only (2026-11-17, owner asked before signing off)

Marked `xfail(strict=False)` = they run and show as XFAIL (not met) / XPASS (met) but never fail the run, until the
owner says yes: T1 "links only name existing notes"; T2 New-York-only destination, no Quintacle link, folder tree,
NY -> USA -> North America chain, no Italy/Washington/Quintacle after Save, typed B -> A link; T4 drops of Claude's
answer (he never did those); T5 save checks. Kept pass/fail because he said so: T1 graph checks ("our test also needs
to include checking the graph updates"), T2 year in folder ("yeah i want the year"), T2 four distinct notes (his
requested no-overwrite fix).
- Owner, same night: "Yes to all this seems obvious". All 10 report-only checks above are pass/fail again (confirmed 2026-11-17).

## Full run 2026-11-17 night (corrected setup, all checks confirmed)

| Test | Local | Claude |
|---|---|---|
| T1 Austria | 8/8 | 8/8 |
| T3 ticket | 9/9 | 9/9 |
| T5 lamb | 5/5 | 5/5 |
| T6 yogurt | 3/3 | 3/3 |
| T2 NYC (both models, one run) | 24/28 | |
| T4 meal plan (both models, one run) | 8/10 | |
| T7 breakfast (both models, one run) | 5/7 | |

Failures (all real, none from the test setup):
- **T2, 2 runs out of 2:** with only Europe 2027 on disk (as at 07:05 on 11-13), the local sort filed the NYC plan into
  `Planned/Europe-2027`; trip_folder_links then linked it to the Europe itinerary. Both sorts of the local answer
  (A, B) also linked "Quintacle". Fix proposed: code checks the trip folder matches the plan's places.
- **T4:** no meal from his local answer (local + claude+local sorts). Cause, reproduced: the local meal call is capped
  at 1,024 output tokens; on a full-day plan qwen3:8b's JSON gets cut off -> LocalParseError -> swallowed, no card.
- **T7:** his real cards' two misses again: local+local eggs "2 g"; local+claude "basmati rice, cooked".
- T3 Claude passed this time (Frankfurt was listed in the run before: model variance; fix #6 still open).

## Owner live drops, 2026-11-18 morning (not saved yet; no pytest test written)

- **Thailand trip** (chat -> scratchpad -> Sort with AI): owner: "it does planned correctly".
- **London + Paris, 3 days, 2028** (local chat 07:50, `conversations/plan-a-trip-to-london-paris-in-2028-for-3-days/`,
  pushed into the scratchpad, Sort with AI): proposed `Fun/Travel/Planned/Europe 2028`. On disk at the time:
  Europe 2026, Europe 2027, New York 2028, so **it formed a new folder** instead of dumping the trip into an existing
  one. The name follows the plain-Planned trip rule (two countries, one continent -> "Europe", + the year from the text).
- Why T2 still fails sometimes: T2 starts from 11-13 07:05, when Europe 2027 was the ONLY trip folder, and the local
  model then sometimes picks it for the NYC plan (passed 28/28 in one run, 24/28 in the next two). The code fix only
  steps in when the model leaves plain `Fun/Travel/Planned`; when the model names an existing trip folder, code trusts
  it. Proposed fix d (not approved yet): check an existing trip folder's places against the plan's places.
- Chat notes (compare-only): opened with "tailored to your past preferences" (a mild hint, within rule B);
  day 3 returns to London in the afternoon but has a Seine cruise in the evening; it invented "Travelers: 1" and a budget.

## Fixes applied 2026-11-18 (owner: "yes to everything else"; g = "keep, tighten the rule"; h = "standard and mine")

| Fix | What changed (code) |
|---|---|
| a eggs by count | `meal_composer.apply_stated_amounts`: "2 eggs" sized as a count's worth of grams -> 2 x 50 g (macros scaled) |
| b uncooked -> raw | same pass: a food the text states uncooked/dry/raw is named "..., raw", never "cooked"; prompt example no longer says "cooked" |
| c his lamb | real store, backup in `~/.quintacle/backups/2026-11-18-before-lamb-rematch/`: "Costco Lean Lamb" re-saved via POST /logs/ingredients with only the 12 printed label values (now incl. vitamin D 0.4 mcg); gaps from USDA 172617 "Lamb, New Zealand, imported, ground lamb, raw" (was beef 169525) |
| d trip folder = this trip | `drop_fixups.trip_folder_matches_plan`: an existing Planned trip folder is kept only if its year matches and >= half the plan's places lie inside the folder's places; else the folder comes from the plan's places + year |
| e meal limit | meal composer 1,024 -> 4,096 output tokens; a failed extra suggestion returns `warnings`, shown in the drop status line |
| f layovers | `gazetteer.find_places`: "X (FRA) layover", "X - 1h 35m connection", "X airport", and a coded stop mid-route ("IAD → X (FRA) → VIE") are not destinations; each mention judged on its own |
| g past chats | LOCAL chat turns: code removes every number from the "From recent chats" block (topics stay); cloud unchanged |
| h nutrition shape | the USDA chat block requires a summary of protein, carbs, fat, fiber, omega-3 (EPA+DHA, 6:3 ratio), iron, calcium, vitamin D, B12, potassium, magnesium, zinc, sodium with % of target; missing = "no USDA value" |
| i Browse | already shows "couldn't load this folder: ..." (no change) |
| j labels | "VitaminD0.4mog" now reads 0.4 mcg; panel headings ("Safe Handling Instructions") are never the name (lamb label -> "Spring Lamb"); USDA-filled rows from the card are no longer saved as "label" |
| k run script | Claude-only user tests run in parallel; local ones one at a time |

Faked suite: 1,609 passed (new: `tests/claude/existing/test_fixes_2026_11_18.py`). Frontend tsc: 0 errors.

## T8 — usual breakfast, after the fixes (2026-11-18 08:15, owner by hand)

Chat (local, then escalated): "okay this is what I normally have for breakfast. 230 grams of the lamb(costco),
70 grams atlantic salmon, 2 eggs and 50 grams of uncooked rice." Each answer dropped as text, sorted local and Claude,
all four saved as meals. Test: `food/test_t08_usual_breakfast.py` (T7's confirmed checks; extras ignored).

Saved (real store, read-only check): all four meals = lamb 230 g (his "Costco Lean Lamb", now USDA lamb), egg 100 g,
rice 50 g "Rice, white, short-grain, raw", salmon 70 g: 75.1 g protein, 40.3 g carbs, 39.1 g fat, 837 kcal.
Fixes a, b, c held on every card. The first save created new ingredients Salmon / Egg / Rice; the later three cards
reused them from his library, which is why all four are identical.
- **Miss:** the salmon ingredient is "Salmon" -> USDA "Fish, salmon, chum, raw" (173689). He said Atlantic; the chat
  used "Fish, salmon, Atlantic, wild, raw" (173686). The drop dropped the word "Atlantic". Not fixed yet.
- Chat, local: full panel incl. all h nutrients; no past-chat numbers (fix g held). Said "Protein 74.9 g (112% of
  target)" although no protein target is set, and "Fiber 0 g (no USDA value)" (it is 0 g).
- Chat, Claude: the h summary table in order; one line asking whether the past-chat 200 g / 2,400 kcal still holds.
- Owner: Claude creates fewer extra KB cards than local. He deletes extras before saving; tests ignore extras.
- Harness: `OWNER_SAVES` (harness.py) lists his hand saves with times; every sandbox leaves out the ones saved at or
  after its start, so T4-T7 don't see today's salmon/egg/rice or meals.

- 2026-11-18-0830: owner asked to delete the 3 extra test meals. Kept one as "High-Protein Breakfast with Lamb, Salmon, and Eggs" (new id 5, same 4 ingredients); deleted meals 1-4 with their preset notes, graph edges and search rows. Backup: `~/.quintacle/backups/2026-11-18-before-meal-cleanup/`.

## Label photos, saved look-alikes, typed qualifiers (2026-11-18, owner: "fix all yes", "similar to travel")

| Change | What it does |
|---|---|
| Label photo = one product | The INGREDIENTS line's food word ("LAMB") limits the USDA candidates; the label's numbers pick among them. If that pick disagrees with the printed numbers (yogurt line says "milk"), the old path decides. Claude's image schema now returns the printed `ingredients` line; local reads it from OCR. |
| Naming | A name with no food word is renamed from the match: junk -> head ("Safe Handling Instructions" -> "Lamb"); brand -> "Chobani (Greek yogurt)"; food names stay. |
| Saved look-alike (owner: "similar to travel") | Same name / same USDA food / same numbers per 100 g (kcal ±5%, protein/fat/carbs ±1.5 g) -> card shows "Update <name>" (default) / "Save as new". Save as new never overwrites (same name gets " (2)"). |
| Typed qualifiers | Meal drops keep the word typed before a food: "70 grams atlantic salmon" -> "Atlantic salmon", USDA Atlantic, not chum. |

- **Real store (owner yes):** saved "Salmon" (USDA chum 173689) replaced by "Atlantic salmon" (USDA 173686 "Fish, salmon,
  Atlantic, wild, raw", the app's own pick and the one the chat used; farmed is in the picker). The kept breakfast meal
  now uses it: 74.9 g protein, 40.9 g fat, 853 kcal (matches the chat). Old ingredient row, micros, note and index
  removed. Backup: `~/.quintacle/backups/2026-11-18-before-salmon-rematch/`. `harness.OWNER_SAVES` updated.
- New offline tests added in `core/tests/claude/existing/test_fixes_2026_11_18.py`, **NOT run** (owner: "do not run the
  tests. ill do the drop and see it meself. then have you write a test for the same").
- Next: owner drops label photos / a meal by hand; tests written from his cards after.

## T9 — the yogurt label again, already saved (2026-11-18 08:50, owner by hand, local)

Dropped the T6 Greek yogurt label photo with that yogurt saved. Card: "Same USDA food as your saved: Kirkland Signature
Plain Nonfat Greek Yogurt (2/3 cup)", Update chosen by default, Save as new offered; per 170 g protein 18, carbs 7,
fat 0, fiber 0, kcal 100 (label); gaps from USDA "Yogurt, Greek, plain, nonfat"; name on the card "Greek yogurt"
(Update keeps his saved name). Owner: "make this a test" -> `food/test_t09_yogurt_already_saved.py` (those checks;
the card name is not checked). Screenshot: `files/food/greek-yogurt-again-2026-11-18/card_local.png`. Not run.

## T10 (in progress) — lamb smash-burger recipe, chat iterations then drop (2026-11-18 09:20, owner by hand)

Chat (`files/food/lamb-burger-recipe-2026-11-18/chat.md`), local qwen3:8b for turns 1-3, then escalated to Claude:
1. "lets write a recipe having ingredients lamb salmon and rest carbs ... I want to make smash burgers ... costco buns.
   that are 300 kcals" -> local: lamb AND salmon smash-burger variants, 112 g patty, 100 g salmon, "~600-700 kcal".
2. "I want lamb burgers and we can add salmon in or on the side( 1 egg goes in each sandwiich ...) and salmon can also be
   separate" -> local: still 112 g / 100 g, "~86 g protein", "travel context", made-up Wikipedia "photo tags".
3. "but its 230 grams of lamb, 115 for each" -> local: 2 x 115 g but "115g ground lamb (210 kcal)", still 100 g salmon,
   "~1,313 kcal", protein 77.5 g; no fix-h nutrient summary.
4. Escalated (Claude): right portions (2 x 115 g, 2 eggs, 70 g salmon - from his saved breakfast, not said in this chat;
   buns replace the rice), real steps, fix-h table for the lamb only (the chat's nutrition lane only computes foods named
   in the newest message: "230 grams of lamb"), corrected its own earlier numbers, asked whether 300 kcal is per bun.
Owner: "im satisfied mostly". Procedures belong in the Nutrition folder as notes, not presets (owner 2026-11-18).

Drop of local answer 3, Sort with AI (local) (`drop_local_local_1.png`): 4 KB notes under Personal Development/Physi...
("Lamb and Salmon Burger Recipe", "Nutritional Breakdown ...", "Photo Tags ...", "Tips for Travel & Meal Planning") and a
WORKOUT ROUTINE "Lamb & Salmon Power Meal" with Barbell Squat. Owner: "lot of adhoc ... make a note in the tests that
local + local will adhoc"; he deletes extras. Found: the deterministic gate `looks_like_preset` returns
"workout_routine" for this answer (answers 1, 2, 4 -> meal_composition) - a gate bug, being investigated (no fix yet).
Next: owner redoes with cloud, then drops Claude's final answer local + cloud; screenshots -> T10.
- T10 drop 2: the same local answer 3, Redo with cloud (`drop_local_claude.png`): ONE KB note "Lamb Smash Burger with
  Salmon and Egg" under Personal Development/Physi... (cut off), content "# Lamb Smash Burger with Salmon and Egg /
  **Serves:** 2 (230g lamb total, 115g per patty) / ## Ingredients ..."; no workout routine, no meal preset, no extras.
  Owner: "claude has less adhoc ofc. only 1 good entry". Owner on the chat: "the local answer did better" (vs the
  escalated Claude answer); the test must compare the two chat answers anyway (report only).
- T10 turn 4 "include all ingredients for this recipe": local answer made up a "Total for the Meal" table (lamb-only
  numbers credited to buns: calcium/vitamin D "from buns", carbs "60g" guessed from kcal); Claude gave a full ingredient
  list, no nutrient table, and asked again whether 300 kcal is per bun. Cause: the chat nutrition lane only computes
  foods named in the NEWEST message; this one names none. Found, not fixed (owner to decide).
- Owner: "local chat is better claude sort is better". Test written: `food/test_t10_lamb_burger_recipe.py`
  (chat turns 3 and 4 compared, report only; drops of his local answer 3, local + Claude sort: recipe note in his
  Nutrition folder, no workout routine card; extras printed, not judged). Not run.
- T10 drop 3 (09:55): Claude's turn-4 answer (full ingredient list), Sort with AI (local) (`drop_claude_local.png`).
  3 KB notes: "Lamb Smash Burgers Full Ingredient List" (good) + 2 junk notes made from its closing questions
  ("Lamb Smash Burger Calorie Question", "Recipe Recording Request"). Meal card "Lamb Smash Burgers with Fried Egg and
  Side Salmon": his saved Costco Lean Lamb 230 g (label), Egg 100 g, Atlantic salmon 70 g (fixes a/c/3 held: saved
  ingredients reused, eggs by count, Atlantic kept) + "Costco per burger bun" 120 g, AI estimate 10p/58c/6f/320 kcal
  (no USDA match; he said 300 kcal per bun, 2 buns -> the card has one bun's worth). Totals 81.6p/58.7c/46.6f, 994 kcal.
- Why "local" became Claude: ingest provider "auto" (the default, llm_dispatch): the local meal step's JSON didn't fit
  the meal schema ("1 validation error") 4 times today, so it retried with Claude on its own (Max first, paid API only
  if Max fails). Also found: while a local sort runs the whole backend stops answering (the /drop handler blocks);
  the owner's page showed fetch errors (plus a network change, ERR_NETWORK_CHANGED). Both found, not fixed.
- T10 test: added the C4 drop ("claude4+local") with the same two checks.
- T10 drop 3 redone 2026-11-19 16:18, fully local this time (no fallback in the backend log) (`drop_claude_local.png`;
  the 11-18 auto-cloud card kept as `drop_claude_local_auto_cloud.png`). 2 notes: "Lamb Smash Burgers Full Ingredient
  List" (Personal Development/Physi..., owner: "the folder selection is actually pretty great") + junk "Lamb Smash
  Burger Calories Question". Meal card "Lamb Smash Burgers with Salmon Yogurt Sauce": saved lamb 230 g, egg 100 g,
  Atlantic salmon 70 g (reused) + new: "Costco buns" 200 g 130 kcal (AI estimate; 2 buns x 300 kcal = 600), "Kirkland
  Plain Nonfat" 170 g USDA Greek nonfat (his saved "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)" NOT reused,
  and the recipe says 2-3 tbsp, not 170 g), lemon 30 g, dill 5 g, salt 1 g, "Black nd pepper" 0.5 g (odd name).
  Next: owner's Redo with cloud on the same drop.
- T10 drop 4 (2026-11-19 16:20): same C4 drop, Redo with cloud (`drop_claude_claude.png`). Owner: "cleaner ofc".
  ONE card: meal "Lamb Smash Burger with Fried Egg and Salmon Yogurt Sauce", ONE burger: saved lamb 115 g, egg 50 g,
  Atlantic salmon 70 g (the whole 70 g on one burger), his saved Kirkland yogurt 30 g (reused, label), "Costco bun"
  90 g / 250 kcal (AI estimate); totals 54.9p/46.6c/28.5f, 654 kcal. No recipe note -> T10's "recipe note in his
  Nutrition folder" check would fail for this card set; owner to decide (question asked).
- Found in drop 3: "Black nd pepper" = bug in the 2026-11-18 name rule (the "a" inside "salt and pepper" read as an
  amount "a"); fix proposed (word boundary), not applied.

## Fixes applied 2026-11-19 (owner: list 1-9; 2 deferred, 8 dropped; "can't auto switch to cloud"; 4 = "fix for all")

| # | Fix | Where |
|---|---|---|
| 1 | "Black nd pepper": amount words must be whole words | `meal_composer._AMOUNT` |
| 3 | saved ingredient reused when the model shortens its name ("Kirkland Plain Nonfat" -> his Kirkland yogurt), only when exactly one saved one fits | `meal_composer.saved_ingredient_match` |
| 4 | every chat lookup (notes, past chats, web, photos, nutrition) uses the newest message + the previous 1-2; nutrition collects every food HE gave an amount for in the chat (later amount wins) | `kb/chat.py _lookup_query/_web_query/_photo_query`, `chat_lane.conversation_items` |
| 5 | "auto" never switches to cloud by itself; a failed local sort returns "local couldn't sort this" + Redo with cloud; a failed meal/routine/ingredient card is a warning + Redo. Cause of the meal failures (diagnosed with 6 local calls): qwen3:8b looped the component list (equipment, toppings) to the 4,096-token cap -> cut-off JSON. Fix: "foods only, each once" prompt line + max 20 components; a cut-off now says "ran out of tokens" | `llm_dispatch.parse_structured/_parse_local`, `api._ollama_error_handler`, `meal_composer` |
| 6 | blocking upload endpoints (/drop, /kb/drop, batch-drop, KB assets, wardrobe, grooming, documents, home) run in the threadpool: the app keeps answering during a sort | api.py, nodes/*/api.py |
| 7 | a pasted chat answer's closing lines to him ("Do you want me to record...?", "is 300 kcal per bun...?") are cut before sorting (unchanged if short or >40% would go) | `drop_fixups.strip_chat_closing`, /drop plain-text branch |
| 9 | chat answers stream (`POST /kb/chat/stream`, SSE): local token by token, Max token by token, metered APIs as one piece; the page and the Assist panel show it live, fall back to /kb/chat on any failure | `kb/chat_stream.py`, `max_backend.run_stream`, `frontend/lib/api.ts streamChatWithKB`, `ChatLog`, `kb/page.tsx`, `AssistPanel` |

Deferred: 2 ("Split into two patties" read as a workout). Dropped: 8 (Redo after a mixed sort; 5 removes mixed sorts).
New faked tests written, NOT run: test_meal_reuse_2026_11_19, test_drop_closing_questions_2026_11_19, test_gazetteer_airports_2026_11_18,
test_meal_names_2026_11_18; updated test_llm_dispatch (auto never goes to cloud). py_compile clean, tsc 0. Backend restarted 2026-11-19.

## T11 — pull day, chat then drop (2026-11-19 17:09, owner by hand)

Chat (`files/workout/pull-day-2026-11-19/chat.md`): "okay lets plan a workout routine. starting with pull workout. I do a
pull workout usually 3 sets each. deadlifts, weighted pullups weighted chinups. barbell rows. bicep curls. facepulls and
supportive back exercizes like cable pull aparts and facepulls". Local: all 7 exercises with rep ranges, tips, closing
question. Claude (escalated): 7 exercises in a table with sets x reps and rest, noticed face pulls listed twice, said his
notes have no workouts/PRs/injuries, asked about split/goal/injuries/current weights before building push and legs.
Drops of the LOCAL answer:
- local + local (`drop_local_local.md`, his screenshot file was gone from /tmp): 7 exercise LOG cards (no date, weight 0,
  reps from the answer's ranges e.g. curls 10/12/10, a stray "10" in distance) + routine "Pull Day" with his 7 exercises.
  Owner: "it includes all so im not super worried persay. tho its logging it in before its even a route".
- local + claude (`drop_local_claude.png`): KB note "Pull Workout Routine (3 Sets Each)" in a NEW top folder
  "Fitness/Routines" (his folder: Personal Development/Physical/Fitness/Routines) + routine "Pull Day", same 7.
  Owner: "local + claude is definitely nicer".
Where the exercises come from: his own message (all 7 he named; face pulls once). The exercise LOG cards come from the
main classifier reading the answer's "3x10-12" rep ranges as sets he did (a plan, like the meal case, shouldn't log).
Test: `workout/test_t11_pull_day_chat.py` (chat compared, report only; pass/fail: a routine with all 7 of his exercises;
log cards and the folder only printed until he confirms). Not run.
- T11 drops of CLAUDE's answer (17:14-17:15): Sort with AI (local) (`drop_claude_local.md`, screenshot file gone): exercise LOG cards from the
  table's rep ranges (Deadlift 3/5/3, Weighted pull-ups 5/8, ...) + junk ACTIVITY "productivity - Review and organize
  workout plan for pull day 0.5". The KB note "Pull Workout Routine (3 Sets Each)" (Fitness/Routines) and routine
  "Pull Day" ("Face Pulls (Cable or Band)" = the LOCAL answer's wording) at the top of that screenshot are most likely
  the previous drop's cards: a new Sort with AI APPENDS to the pending cards (page.tsx setEntries(prev => [...prev, ...])).
  Redo with cloud (`drop_claude_claude.png`): only routine "Pull Day" with his 7 exercises (no note, no logs).
  T11 now drops both answers with both sorts (4 card sets).

## Drop + save log (2026-11-19, owner: "lets have a save log this way we can test better")

Every Sort with AI / Redo with cloud appends a "drop" line to `~/.quintacle/drop-log/YYYY-MM-DD.jsonl` (input text, file
names/sizes, provider asked/used, warnings, local_unavailable, every proposed card, a `drop_id`); every Save on the
scratchpad appends a "save" line (drop_id, cards as saved after his edits, cards he deleted with x). Private drops/cards
are logged as type-only placeholders. Read back: GET /drop-log/recent?limit=N. Code: `quintacle_core/drop_log.py`,
api.py (/drop wrapper, /drop-log/save, /drop-log/recent), frontend kb/page.tsx + lib/api.ts. Faked test written, not
run: test_drop_log_2026_11_19.py. Backend restarted. From now on tests are written from the log, not screenshots.
