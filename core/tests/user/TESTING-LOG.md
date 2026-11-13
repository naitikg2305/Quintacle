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
