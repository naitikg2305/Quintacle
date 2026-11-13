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

---

## Travel

### Drop a trip plan *(tested: T1, Austria itinerary PDF)*

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

**You confirm:** fix the folder (add the year, for example), the title or the destinations, then Save.

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

---

*More sections get added as each feature is tested: journal, food, finance, documents, people, wardrobe,
chat.*
