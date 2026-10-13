# Quintacle — Real-use test plan + wishlist dump (2026-10-07)

Status: **captured, not run.** Naitik's own flows and use cases, dumped in one
go and organized here. Two jobs: (1) the reference for testing Quintacle
end to end before it goes on the phone ("ready for prod"), and (2) a todo and
wishlist of where it should go next. Builds on `usecases.md` (UC1–UC8) and
`mcp-angle.md`. More is still incoming.

## The direction, in his words

> An MCP where, say, I'm in a lecture or a learning workshop. I have a chat
> (GPT or Claude), I'm uploading photos and talking, then I use an MCP
> endpoint saying "send it into the knowledge base". Retrieve from the
> knowledge base, etc. All my schemes and plans, including talking to my
> boss or whatever.

- **MCP is the main interface.** As he works and learns, he keeps logging what
  he's doing for Minfy, and his finances and financial plans, through the MCP.
  Every Claude session and project he works on gets tracked into the
  knowledge app through it.
- **Read and write both**, not read-only.
- **Two ways in:** just the MCP, working through chat, with the UI there if he
  chooses to open it; or a key and the app itself.
- **"Here it is, here's the confirmation":** whatever gets logged (e.g. car
  spending) has to come back with proof of what was written, so he can check
  it himself. Generic nodes are fine ("we never know" what shape a thing has),
  but writes must be verifiable.
- **Refer back, then discuss:** "refer to what I did (via MCP), then discuss
  further" in chat.
- **Hosting and offline both.** Personal AWS is on the list (see
  `self-hosting.md`), and so is a local LLM in a harness ("Claude Plus or an
  LLM in harness, local"; see `on-device-s25u.md`).
- Open question he raised: **MCP → agentic chat?** One agentic chat as the
  realistic version of the ideal.

## Architecture as he sees it

- **Ideal:** one page with a mic (speech to text) and a camera, like Jarvis,
  that does everything without fail; another page to actually go into the
  knowledge base.
- **What exists now (the core idea):** Dropper (mic + camera page), Chat
  (discuss, scratch, add), Browse, Calendar (see what's up), Dashboard (am I
  meeting weekly goals).
- **Realistic:** one agentic chat that delivers the ideal by routing into the
  core pages and stores.
- **Eventual:** as deterministic as possible, to keep API costs down.

## Test flows (the test folder maps onto these)

He's building one folder of photos and files that should let him test the
whole app and call it ready for his phone.

### Recorded real flows
- Picked photos from the gallery by hand, uploaded them all, asked about a
  dating app.
- Food place: took photos, wants to rate it.
- Houston planning chat: asked about bars close to each other.
- Techniques ("pulling the chair", that kind of thing).

### Journal (nightly dump, see UC2)
- **Fitness:** sets and reps; running.
- **Food:** junk food; pre-made meals; drinks, alcohol included.
- **Productivity:**
  - Minfy work: what he did. Adds to the company and the career. Going to an
    event also adds to the company.
  - A specific project; working on the car; fixing or assembling something.
- **Social:** a date, or a phone call with a friend (both add to People); a
  beer chase with friends.
- **Activities / hobbies:** guitar, sailing, golf.
- **Finance:** money spent.

### Batch drop
- A bunch of knowledge files at once.
- A bunch of videos at once.

### Simple drop
- An experience.
- A clothing item: does it just register?
- A watch. Sunglasses.
- A home organization item.
- An important document.
- Notes.
- A lecture with photos, then more photos added to the same lecture folder
  one at a time.
- Project-specific files: STL, DOCX, PDF, Excel, video.

### Knowledge chat
- Plan a trip.
- House plans, including scratch files and PDFs.
- Financial plans.
- A research topic.
- Plan a meal. Plan a fitness plan.
- Plan a new schedule: does it become the weekly goals?
- Girl game.

## Wishlist and todo dump

**Work / career (Minfy)**
- Log Minfy work continuously via MCP: SOWs, sales calls, other projects,
  talks with the boss.
- Resume use case: does what's logged line up so a resume can be pulled out
  of it?

**Money**
- Flow of money / cash tracking (ideas from Michael, Thea and Alex).
- Weekly budget system: e.g. a weekend plan (winery, $50) vs. what going out
  actually ends up costing. One "222" and one date a week, budgeted.
- Monthly consumables: creatine, alcohol.
- Points, miles and similar rewards ("I wanna be better now").
- Spending per thing, e.g. the car.

**Bookmarks and apps**
- Bookmarks: Keka, Rippling.
- Apps: CPU-Z, FurMark, Steam, Spotify, etc.
- Reservations: Resy etc. Use whatever app fits.

**Fitness and food**
- Goal: flexible, fast, boxing, running, sprinting, calisthenics.
- Plan good meals.

**"Perfection in life": researched choices**
- Interests like watches and sunglasses.
- Comparing and choosing the best, and recording why: fitness trackers;
  niches like audiophile headphones; keyboards.

**Car**
- Track each car's health over time: brake pads, maintenance.
- AI-driven UI, Jarvis-style slides of the CX-5 with health bars.

**Learning**
- Lectures with chat or Claude: photos, talking, notes, all into the KB.

**Misc**
- Dust protection for the laptop.
- Track everything done so far, docs included.

## Everyday-use test flows, by domain (2026-10-13)

A second pass, organized by life domain rather than by app surface. Each
domain lists what should work through **Drop** vs. through **Chat** — this is
the file/photo set to build per domain for the test folder, and doubles as the
acceptance list for "does this domain actually work."

### Food
- **Chat:** plan a new meal; ideas for ingredients/spices; turn a plan into a
  recipe and store its macros; swap macros (e.g. swap a carb source and keep
  calories the same).
- **Drop:** a recipe and the steps used to make it; what was just eaten, logged
  as a calorie entry if it's a known item in the database.

### Fitness
- **Drop:** sets and reps as they're done; track weight and what was done that
  specific week/day (calories burned, etc.) — entered per set, appending as you
  go through a workout.
- **Chat:** plan a workout or a program; plan running/stretching; a workout
  plan with dates attached.

### Finances
- **Drop:** a credit card statement — should auto-detect subscriptions and
  recurring payments; a monthly budget for a category (e.g. housing); credit
  card points updates and what they're worth (flights, hotels); a specific
  card's benefits and how much of them have been used; everyday spending,
  logged as it happens; stocks invested in.
- **Chat:** plan financial future at current salary, at an ideal salary, or
  matching salary to financial goals; plan buying a house (payments etc.) or a
  specific car; discuss stocks and investing knowledge in general.

### Documents
- **Drop:** driver's license, paychecks, W2, tax docs, passport, car
  docs/receipts/mail.

### Career
- **Drop:** specific resumes; job applications actually submitted; Minfy sales
  and related work; what was done on a specific day for the company
  (knowledge, KPIs).
- **Chat:** discuss company politics/conversations, tied to people; discuss
  emails/messages to plan next steps; make company-specific folders; discuss
  sales work, write and drop SOWs, and log client interactions/notes as they
  happen.

### Organisation (home)
- **Drop:** a catalog of where things are kept (which drawers hold what, how
  furniture is arranged); rough apartment blueprints/drawings; what was bought
  and what was on the list for it.
- **Chat:** discuss Sunday chores/cleaning; discuss meal prepping for the days
  ahead.

### Schedule
- **Chat:** the schedule actually followed; what needs doing in a given week
  (hours-based, so it's generic); how many days drinking vs. days left in a
  limit; how many days of golf or guitar; whether 10 job applications got sent.

### Travel / experience / date / fun / journal
- **Drop:** things already done (e.g. a New York trip), pulled from a chat or
  Claude photos; photos tied to a past experience; journal entries linked to
  specific people; dating playbooks/tricks that worked; general philosophy
  learned about people.
- **Chat:** plan trips, dates, or general life-planning days; tactics for
  approaching/dating people.

### People
- Most of the above should link back to People — folders per person tying
  experiences to them (dates, friends, family). Needs to be filterable, e.g.
  by date.

### Organisation (tech)
- Specific apps used; bookmarks/links; specific websites/tools and what each
  is for; passwords for specific things; phone apps and the reasoning for
  having each.

### Knowledge
- General notes on specific niche topics (e.g. physics, whatever comes up).

## How to use this

1. Build the test folder grouped by the sections above.
2. Run each flow against the app as it is. Record ✓ / ~ / ✗ / — like
   `usecases.md` does.
3. Build the MCP (read + write) and re-run the flows through a Claude chat.
4. Check that each write comes back with a confirmation and is visible in the
   UI.
