# Quintacle: what it can do

A living list of features, written alongside the owner's hands-on testing (2026-11-13 onward). Each section says:
- what you do;
- what the app does;
- what you confirm.

Each tested feature points to its test in `core/tests/user/` and its entry in `core/tests/user/TESTING-LOG.md`.
Internal design and how it works stay in `docs/reference/` and `docs/patent/`; this is the user-facing view.

## The core idea: AI suggests, code decides, you confirm

AI models are probabilistic: the same file can be sorted two ways on two days. Quintacle never lets that
reach your data unchecked.

1. **The AI suggests.** A model reads what you dropped and proposes what it is: a type, a folder, a title and
   content. It runs locally by default; Claude is optional.
2. **Code decides the facts.** Anything that must be right every time is computed by code from the text, not
   guessed by the model, and comes out the same on every run:
   - dates, money and names;
   - cities and countries;
   - links to people, places and projects you already have.
3. **You confirm.** Everything lands on a review card first. You edit any field, delete a suggestion, or
   redo it with Claude. Nothing is saved until you press Save.

That turns a guessing model into a predictable system: the model handles language, code handles facts, and
you have the final say.

## Local first, Claude when you choose

- Sorting runs on local models on your machine (no cost, nothing leaves your computer).
- **Redo with cloud** re-reads the *original* file with Claude, not the local model's answer, so you can
  compare the two and keep the better one.
- **Private (no cloud AI)** on a note or document keeps it away from Claude and every cloud surface. Chat on
  your machine can still use it.
- **A failed extra suggestion is never silent (2026-11-18).** If a drop's extra suggestion fails (for example,
  the meal suggested from a meal plan), the drop's status line shows a ⚠ warning saying so. Before, the card
  just didn't appear.

---

## Travel

### Drop a trip plan *(tested ✅ T1, 2026-11-13)*

**You do:** drop an itinerary (PDF, Word, Markdown or text) and press **Sort with AI**.

**The app suggests a travel-plan note:**
- **Folder:** under `Fun/Travel/Planned/…`. A trip plan is never filed as a vault document, even though it
  mentions flights and bookings.
- **Title**, for example "Central Europe Trip Plan 2027".
- **File info:** file type, document title, page count, creation date and size, read from the file itself.
- **Content:** the plan's text (local) or a summary (Claude).
- **Linked notes:** other notes it relates to, for the graph view.
- **Destinations:** the trip's cities and countries (e.g. "Budapest, Hungary; Vienna, Salzburg, Austria;
  Prague, Czechia"). These come from **code**, not the model:
  - it reads the place names in the text, using a built-in list of cities and countries;
  - it skips where you leave from ("from Dulles");
  - it skips places you only pass through: a flight layover ("Prague (PRG) to Frankfurt (FRA) to Dulles") or
    a train change ("via Linz");
  - an optional day trip (Hallstatt) still counts.

- **The year goes in the folder** when the trip has one, e.g. `Fun/Travel/Planned/Europe 2027`. It is taken
  from the plan's dates, or the title.
- **Suggested links are checked.** A link survives only if it names a note, journal day or experience you
  actually have. A made-up link like "About Travel" is removed before you see the card.

**You confirm:** fix the folder, the title or the destinations if you want, then Save.

#### Tested: T1, Austria itinerary PDF (2026-11-13)

**What Quintacle was given:** a 4-page PDF, *Central Europe | 10-Day Trip Plan*, dropped with no text. It
plans May 12–21 2027 through Budapest → Vienna → Salzburg → Prague, with:
- flights from Dulles via Vienna, and back via Frankfurt;
- trains between the cities, one with a change in Linz;
- an optional day trip to Hallstatt.

**What Quintacle did:**

| | Local (on your machine) | Claude (Redo with cloud) |
|---|---|---|
| Sorted as | A travel plan, not a vault document | Same |
| Folder | Suggested `…/Planned/Europe`; with the fix it gets the year | `…/Planned/Central E…` (cut off in the screenshot) |
| Title | Central Europe 2027 Itinerary | Central Europe Trip Plan 2027 |
| Content | The plan's full text | A one-paragraph summary |
| Destinations | Budapest, Vienna, Salzburg, Prague, plus Hallstatt (layover and train change removed by the fix) | Budapest, Hungary; Vienna, Salzburg, Austria; Prague, Czechia |
| Links | None (made-up ones removed) | None |

**What testing found and fixed:**
- **Destinations listed the Frankfurt layover and the Linz train change.** A city you only pass through no
  longer counts.
- **There was no year in the folder.** The trip's year is now added.
- **Links pointed to "About" notes that don't exist.** Links are now checked against your notes.

**Result:** both local and Claude pass every check:
- sorted as a travel plan;
- the year is in the folder;
- the four trip cities are listed;
- no layover or train change is listed;
- no made-up links.

Test: `core/tests/user/test_t01_austria_drop.py`, run on the exact PDF. Log: `TESTING-LOG.md` T1.

**Still open:** whether the note should keep the full text (local) or a summary (Claude).

### Which trip folder a plan goes into *(2026-11-18)*

**You do:** drop any trip plan, from a file or from a chat answer.

**The app decides the trip folder with code, from the plan's places:**
- **One city:** the city, e.g. `Fun/Travel/Planned/New York 2028`.
- **Several cities in one country:** the country.
- **Several countries on one continent:** the continent, e.g. `Europe 2028`.
- **Plus the year,** from the plan's dates or title.
- **An existing folder with the same name and year is reused.** Otherwise a new one is made next to the others:
  a London + Paris 2028 plan made a new `Europe 2028` beside `Europe 2026` and `Europe 2027` (owner's live
  drop, 2026-11-18).

**If the model picks an existing trip folder, code checks it is this trip:**
- the year must match;
- at least half the plan's places must lie inside the folder's places.

If either fails, the folder comes from the plan's places instead. A New York 2028 plan can no longer land in
`Europe 2027`.

**You confirm:** change the folder on the card if you want, then Save.

### Notes in one trip are linked

- **Same trip folder, linked notes.** A note saved into a trip folder links to the notes already there. A flight
  ticket dropped into `Europe 2027` links to that trip's itinerary (T3).

### A drop never silently overwrites a note *(2026-11-13)*

- **Same note, your choice.** If a drop matches a note you already have, by name or because the AI thinks it is
  the same note, the card says which note and offers **Keep both** (default), **Append** to it, or **Replace**
  its text.
- **Keep both** gets a nearby name the AI suggests, not "(2)".
- **Append** adds a dated section and keeps the note's text, links and fields. **Replace** swaps the text and
  keeps the links and fields.
- Found in T2, where two drops with the same title would have replaced each other.

### Layovers and connections are not destinations *(2026-11-18)*

Destinations come from code. On top of the T1 rules (skip where you leave from, skip "via Linz"):
- "Frankfurt (FRA) layover", "1h 35m connection" and "Frankfurt airport" are not destinations;
- a coded stop mid-route ("IAD → Frankfurt (FRA) → VIE") is not a destination;
- a city after "via" or "connecting through" is not a destination;
- **each mention is judged on its own,** so "two nights in Frankfurt" elsewhere in the plan still counts;
- where you leave from ("from Dulles") is still skipped.

#### Tested: T2, New York 2028 trip, chat then drop (2026-11-13)

**What Quintacle was given:** the owner's local chat "plan a trip to new york city in 2028 5 days?", then that
answer sent to Drop and sorted locally and with Claude. Then the chat was escalated to Claude, and Claude's
answer was dropped both ways too.

**What Quintacle did:**
- All four saved notes landed in `Fun/Travel/Planned/New York 2028` with the year added by code.
- Each sits in the folder chain and links to New York → United States → North America.

**What testing found and fixed:**
- **"Little Italy" added Italy as a destination.** Fixed in the place reader.
- **Two notes with the same title would have silently replaced each other.** The card now offers Keep both /
  Append / Replace (above).
- **All four notes shared one attached file.** Each note now keeps its own.
- **The local sort sometimes filed the NYC plan into `Europe 2027`** (the only trip folder at the time) and
  then linked it to the Europe itinerary. Fixed 2026-11-18: code checks an existing trip folder matches the
  plan's places (above).

**Result:** passes when the sort keeps the right folder (28/28 in one run, 24/28 in two others before the
2026-11-18 folder check). **Still open:** the local chat answer sometimes adds "all five boroughs" when not asked,
and a chat answer saying "Quintacle note" links the trip to the Quintacle project.

Test: `core/tests/user/travel/test_t02_nyc_2028_chat.py`. Log: `TESTING-LOG.md` T2.

#### Tested: T3, DC → Vienna flight ticket 2027 (2026-11-13)

**What Quintacle was given:** a flight ticket PDF, IAD → VIE 15–25 May 2027, via Frankfurt both ways.

**What Quintacle did:** filed it into the existing `Fun/Travel/Planned/Europe 2027` (T1's trip), destination
Vienna, Austria only, linked to the trip's itinerary, in the folder tree.

**What testing found and fixed:**
- **The local sort proposed no links,** so the ticket wasn't linked to the itinerary. Notes in one trip folder
  are now linked by code (above).
- **Claude once listed the Frankfurt layover** as a destination. Layover wording is now skipped (above).

**Result:** local 9/9, Claude 9/9 (full run 2026-11-17).

Test: `core/tests/user/travel/test_t03_europe_2027_flight.py`. Log: `TESTING-LOG.md` T3.

### What saving a trip connects (the graph)

- **The place chain:** each destination city links to its country, and each country to its continent
  (Salzburg → Austria → Europe). Ask "what's planned in Austria?" and the trip shows up.
- **Trip photos:** a photo taken during the trip's dates, in one of its destinations, links to the trip
  automatically. The date comes from the photo's metadata and the place from its GPS. No model is involved.
- **Places that emerge:** a city you mention across 3 or more notes becomes a place page of its own. After
  that, any new mention links to it.
- **Wishes:** "someday I want to see the northern lights in Tromsø" becomes a Bucket List entry, not a planned
  trip.

### Experiences (restaurants, outings)

**You do:** "dinner at Founding Farmers in DC with Arjun, 8/10".

**The app suggests an experience:** the place, its kind, a rating and a city.
- The city and date are kept **only if your text states them**. Code removes any city or date the model made
  up.
- The experience links to the people you named and to that day's journal.

---

## Food

### Photo of a nutrition label → an ingredient *(tested T5, T6)*

**You do:** drop a photo of a product's nutrition label and press **Sort with AI**.

**The app suggests an ingredient:**
- **The label's numbers win.** Every value printed on the label is read from it and marked *label*.
- **The rest comes from USDA** (an offline database on your machine) and is marked *USDA*. A USDA value is never
  relabelled "label".
- **The USDA food is picked by the label's own ingredient.** A label photo is one product:
  - its INGREDIENTS line ("LAMB") limits the choice to foods with that word, and the label's numbers pick among
    them, so lamb can't become beef;
  - if no such food fits the numbers (a yogurt label that says "milk"), the numbers decide (Greek yogurt);
  - a protein mismatch rules out a food with the same name (Greek vs plain yogurt).
- **Any photo works.** AVIF and HEIC photos, even ones named `.jpg`, are converted so Claude can read them.
- **Squashed text is read right:** "VitaminD0.4mog" → vitamin D 0.4 mcg.
- **Name:**
  - a name with no food word in it is renamed from the USDA match: a label heading ("Safe Handling
    Instructions") → "Lamb";
  - a brand gets the food added: "Chobani" → "Chobani (Greek yogurt)";
  - a real food name stays as it is.

**You confirm:** rename it (e.g. "Costco Lean Lamb"), fix any number, then Save.

### An ingredient you already saved *(2026-11-18)*

Works like trip notes: nothing is silently overwritten or silently duplicated.
- If a dropped ingredient has **the same name**, **the same USDA food**, or **the same numbers per 100 g** as one
  you saved, the card says which one.
- It offers **Update <name>** (default; meals that use it update too) or **Save as new**.

### Drop a meal (text) *(tested T4, T7, T8)*

**You do:** drop a meal-shaped text, e.g. a chat answer with a breakfast.

**The app suggests a meal preset:**
- **It's a plan, not a log.** No food-log card, unless the text says you ate it ("I had…").
- **Code checks the amounts and foods:**
  - counts become grams: 2 eggs = 100 g;
  - a food you call uncooked or dry stays raw (USDA raw rice, never cooked);
  - the word you put before a food is kept: "Atlantic salmon" → USDA Atlantic salmon, not chum;
  - your saved ingredients are reused (your "Costco Lean Lamb").
- **Full-day plans fit.** A long meal plan no longer gets cut off; if the meal suggestion still fails, the status
  line says so (⚠) instead of skipping it.
- **Meal-plan notes go to your Nutrition folder** (`Personal Development/Physical/Nutrition/Meal Plans`), not a
  new top folder.

**You confirm:** fix any amount, delete extra cards, then Save.

### Chat about food

**You do:** ask chat to plan a meal or a day, e.g. "I have 230 g of Costco lamb, 70 g Atlantic salmon, 2 eggs
and 50 g uncooked rice".

**The app answers with real numbers:**
- **Numbers come from your saved ingredients first,** else USDA, and the totals are computed by code.
- **Every meal or day plan shows** protein, carbs, fat, fiber, omega-3 (EPA+DHA, and the omega-6:3 ratio),
  iron, calcium, vitamin D, B12, potassium, magnesium, zinc and sodium, each with % of your target. A missing
  value says "no USDA value".
- **Past chats are a mild hint only.** The answer follows what you ask now. A past target is mentioned in one
  line as "from a past chat" and asked about, never built on.
- **On local chat, code removes every number from past-chat material** before the model sees it.

#### Tested: T4–T8 (2026-11-17 and 11-18)

| Test | What Quintacle was given | Result |
|---|---|---|
| T4 | Local chat: a full day, 180–200 g protein, under 2,500 kcal, all micros and macros; then dropped and escalated | **Partial.** Chat (compare only): local's numbers were often wrong (similarity 0.85, local facts 53%). Drop: no meal came from the local answer because it was cut off; **fixed 2026-11-18** (longer limit + ⚠ warning). |
| T5 | Photo of a Halal Ground Lamb 85/15 label (an AVIF named `.jpg`) | **Pass** 5/5 local and Claude. Found and fixed: named "Safe Handling Instructions", gaps filled from USDA beef, vitamin D 0.4 mcg missed. |
| T6 | Photo of a Kirkland nonfat Greek yogurt label | **Pass** 3/3 local and Claude. Found: Claude tagged 22 nutrients "label" that aren't on it; USDA values are no longer saved as "label". |
| T7 | Breakfast chat with his saved lamb, salmon, 2 eggs, 50 g uncooked rice | **Partial** 5/7. Found: chat didn't use his saved lamb's numbers; eggs became "2 g"; rice became cooked. **Fixed 2026-11-18.** |
| T8 | His usual breakfast, after the fixes: chat local then Claude, each dropped both ways, all four saved as meals | **Pass on amounts:** all four meals right (lamb 230 g, egg 100 g, raw rice 50 g, salmon 70 g; 837 kcal, 75 g protein). Miss: salmon became chum, not Atlantic → **fixed 2026-11-18**. Chat showed the full nutrient summary; no past-chat numbers carried over. |

Tests: `core/tests/user/food/` (T4–T8). Log: `TESTING-LOG.md` T4–T8 and "Fixes applied 2026-11-18".

**Still open:** a drop proposes one meal per text; local chat still states some made-up numbers (compare only).

---

## Links: how things connect

Every saved item is a node in your graph. Edges between them are created by code from what you wrote, so the
same text always produces the same links:
- **People:** a person you've saved is linked when named, including by first name alone when only one saved
  person has it ("coffee with Arjun" → Arjun Mehta).
- **Projects, companies and accounts** you have hub pages for (Quintacle, Minfy) are linked when named.
- **Places:** cities that already exist as places.
- **Days:** an entry links to that day's journal.
- **Moments:** everything saved from one drop (a lunch and its $13 expense) is grouped as one moment. A
  single expense is its own moment.
- **Folders:** a note is part of its folder's "About" page.

**Folders, places and typed links (2026-11-13).** Folders form the tree on their own: every note belongs to
its folder, and every folder belongs to the folder above it, all the way up (a plan in Fun/Travel/Planned/Europe
2027 and a trip in Fun/Travel/Done both sit under Travel, then Fun). A folder's "About" note describes that
folder. You never make these links or parent nodes yourself, and moving a note moves it in the tree. Places
cross-connect separately: anything about Vienna links to Vienna, which sits in Austria, which sits in Europe.
Links you type in `links:` are exact and instant: "travel" finds the note "Travel" (capital letters don't
matter), but "Travels" doesn't. If the note doesn't exist yet, the link is kept, and it connects the moment you
create that note.

Person and place pages are built from these links, never copied text. A fact lives in one place and every
page that needs it points to it.

## An operating system for your life

Put together, Quintacle works the way an operating system does:

| An OS has | Quintacle has |
|---|---|
| **A file system:** folders inside folders, every file has one home | **The folder tree:** every note sits in exactly one folder, and every folder sits inside its parent (Fun → Travel → Planned → Europe 2027 → the trip). It's built automatically, so there are no orphans and no gaps. |
| **Shortcuts and tags:** one file reachable from many places | **Cross-links:** places (Vienna → Austria → Europe), people, days, moments and typed links reach a note from every angle, without copying it. |
| **Drivers:** each one turns a device into data the system understands | **Drop:** each reader turns a PDF, photo, receipt or sentence into a structured suggestion (OCR, the local vision model, the local language model). |
| **A kernel:** the code that decides, the same way every time | **Deterministic code:** dates, money, names, places and links are decided by code, never guessed by a model. |
| **Permissions:** who may read what | **Privacy:** a private note never reaches cloud AI; the passwords vault is never seen by any model. |
| **A shell:** how you ask it things | **Chat:** an AI that answers by walking the graph (up to a folder, across to a place, out to a person) instead of guessing. |
| **Undo and logs** | **Review before save, and an undo ledger** for every write made through MCP. |

**Why the folder tree matters for AI:** a small local model can't hold your whole life in its head. It can walk
a clear tree, though: "what's planned in Europe?" means go to Travel, then Planned, then read what's there,
and check the Europe place for anything elsewhere. The graph is built for an AI to navigate, not to look
pretty.

---

## Testing checklist: the owner's 38 uses

The owner's own list of what Quintacle is for, in his order. Each item gets a section above once it is tested,
with what Quintacle was given, what it did, what was fixed, and the result.

**How tests are judged (owner, 2026-11-17):**
- **Chats are compared, never pass/fail.** A chat answer differs every time, so local and Claude are only
  compared: a similarity score plus a report from a Claude judge.
- **Drops are the hard tests.** The review cards must be right.
- **Extras are ignored.** "Extras can be ignored": extra cards the owner would delete before saving don't count.
- **Every expected result is one the owner stated or confirmed.**
- **Each test runs on a copy of his data as it was right before he did it by hand.**

| # | Use | Status |
|---|---|---|
| 1 | Travel itinerary | ✅ Tested (T1–T3) |
| 2 | Journal | Not yet |
| 3 | Food, workout set | Food tested (T4–T8); workout not yet |
| 4 | Week goals | Not yet |
| 5 | Financial goals | Not yet |
| 6 | Software engineering knowledge | Not yet |
| 7 | Laptop setup | Not yet |
| 8 | Phone setup and apps | Not yet |
| 9 | Grooming plans decided | Not yet |
| 10 | Document drop | Not yet |
| 11 | DC restaurant experience | Not yet |
| 12 | Experience | Not yet |
| 13 | Date | Not yet |
| 14 | Convo with Alfonso | Not yet |
| 15 | AI setup | Not yet |
| 16 | Projects I have done | Not yet |
| 17 | Plan a meal | Tested (T4, T7, T8) |
| 18 | Discuss a show | Not yet |
| 19 | Show ledger | Not yet |
| 20 | Book ledger | Not yet |
| 21 | Game ledger | Not yet |
| 22 | Journal & Lore | Not yet |
| 23 | House plan and catalog | Not yet |
| 24 | Discuss a financial plan with salaries: how much you can save | Not yet |
| 25 | How much I make right now | Not yet |
| 26 | Subscriptions | Not yet |
| 27 | Random expense | Not yet |
| 28 | Random food drop → expense, calories | Not yet |
| 29 | Reflection dashboard | Not yet |
| 30 | Docs on IRS, DHS | Not yet |
| 31 | CX-5 things (pricing, fixing) | Not yet |
| 32 | Insta & LinkedIn stuff | Not yet |
| 33 | Monthly budgeting thing | Not yet |
| 34 | Outfit drop | Not yet |
| 35 | People | Not yet |
| 36 | Business plans | Not yet |
| 37 | Contract plans (side hustles going on) | Not yet |
| 38 | Knowledge | Not yet |
