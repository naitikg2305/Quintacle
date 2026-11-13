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
- Test: `core/tests/user/test_t03_europe_2027_flight.py` (file copied to `files/travel/`). Sandbox = real store minus the owner's saved note (files, edges, index). Not run yet.
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
