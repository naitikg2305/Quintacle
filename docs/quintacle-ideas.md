# Quintacle — Personal Knowledge Management System

Raw idea dump, consolidated. Built with Claude Code. This doc is meant to be handed to Claude Code as a planning reference — not a spec yet, a map of everything in scope so nothing gets lost while prioritizing v1.

**Core organizing principle:** Everything is tracked on a **daily basis** as the atomic unit. Data flows from daily logs → weekly/period goals → long-term knowledge base. Build order: **manual/physical first, AI retrieval layer on top later.**

---

## Cross-Cutting Principles

- **Manual before AI.** Every pillar below starts as manual input/organization. The "ask a question and it retrieves the right thing" AI layer comes after the base app works.
- **Chat is ephemeral, Knowledge Base is permanent.** The chat model (Claude or GPT API) is a scratchpad for thinking/brainstorming. Nothing is retained there long-term. When something useful comes out of a chat, you manually push it into the relevant Knowledge Base folder. Long-term goal: stop accumulating cluttered chat history in ChatGPT/Claude — push what matters into structured folders, clear the rest, keep the LLM stateless.
- **Folders are user-extensible.** You should be able to create new Knowledge Base folders/categories on the fly, including mid-chat ("push this into a new folder called X").
- **Disaster-recovery mindset.** The system should function as a rebuildable handbook — if you lost your laptop, phone, or apartment burned down, documented processes/decisions should let you recreate your life setup from scratch. This is a requirement across all pillars, not a separate feature.
- **Continuous capture, not batch updates.** Knowledge/logs get added in the moment, primarily from phone — not deferred to a weekly desktop session. The system has to be fast enough to capture on the go or it won't get used that way.
- **Input modalities.** Text and voice are the baseline. The phone (Galaxy S25 Ultra) has a real S-Pen — handwritten/drawn input is a first-class input type from v1, via two paths built together: importing a PDF/image of something drawn elsewhere (e.g. Samsung Notes), and a native in-app drawing/annotation canvas.
- **Approval before write.** Any AI-proposed change to the real store — a folder-sort suggestion, a CSV bank-statement reconciliation diff, anything else the AI layer proposes — is shown as a diff and requires explicit user approval before it touches the actual markdown/DB. The AI layer suggests; it never silently commits.
- **Cross-linking.** Knowledge Base entries can spawn Calendar tasks (e.g., a note like "check portfolio every 2 days" becomes a recurring calendar reminder). Journal entries feed the Daily Tracker. Photos link to Journal entries and to Trip/Project folders. Nothing lives in total isolation.
- **Sync.** Works across phone and laptop, syncing over the same network. Conflict resolution: newest-modified file wins (last-write-wins by timestamp), but if both devices modified a file since the last sync, the losing version is saved as a timestamped `.conflict` copy instead of being silently discarded — cheap safety net against silent data loss.
- **Storage:** Hybrid. Markdown files are the source of truth — human-readable, git-friendly, easy for Claude Code to read/write directly. A generated SQLite/index layer sits on top purely for fast querying (search across years of daily logs, KB entries, etc.) and is disposable — rebuildable from the markdown at any time, never authoritative.

---

## Photo Drop (cross-pillar capture mechanism)

Dropping a photo is a first-class capture action in its own right, not something each pillar reinvents separately. This unifies the scattered "photograph X" mentions across Finances, Nutrition, Wardrobe, Document Vault, Marketplace, etc. into one mechanism:

- A vision model looks at the dropped photo and proposes what it is and what to do with it — using the four-tier vision routing already decided in `deployment-and-privacy.md` (local NPU default → local computer fallback → opt-in cloud vision LLM → code-only floor).
- You always confirm or correct the proposal before anything is logged (see Approval before write, above).
- Type-specific behavior:
  - **Receipt/transaction** — extracts amount/merchant, proposed as a Finances log entry.
  - **Meal/food photo** — vision model estimates kcal/macros, but you must manually confirm or adjust the number before it's logged — food estimates are never auto-committed, only ever suggested.
  - **Clothing/outfit photo** — routes into Wardrobe (Pillar 6): a single new item (e.g. "hey this new jacket") gets added to the inventory catalog; a full-outfit photo gets logged as a complete look in the outfit catalog, not just its component items.
  - **Progress photo** (beard growth, fitness/body transformation, etc.) — tagged into a dedicated time-series album for that specific thing being tracked, viewable as a before/after timeline — distinct from both daily Photo Journal curation and one-off KB drops.
  - **Anything else worth keeping** (an Instagram screenshot, a random photo that made you think, a photographed whiteboard or handwritten note) — gets a caption and a proposed Knowledge Base folder via the same AI-suggest/user-confirm mechanism as Pillar 3's scratchpad; whiteboard/handwritten photos also get vision/OCR text extraction so the content is actually searchable, not just a stored image.
- **Retention:** the dropped photo, its caption, and whatever entry it produced are kept together permanently — an audit trail, not a disposable input (e.g. "why did I log $340 that day" → here's the receipt).
- **Separate from the Photo Journal** (Pillar 4): Photo Journal stays curated daily-memory photos (~10/day, pure narrative). This is a distinct utility inbox for photos that are inputs to something else — most dropped photos wouldn't belong in the curated memory folder.

---

## Pillar 1: Two-Layer Calendar / Daily Tracker

### Layer 1 — Plan
Standard forward-looking calendar. What you intend to do.

### Layer 2 — Reality
What you actually did, logged per day. Originally prototyped in Excel (dates as columns, activities as rows) — the real app has a proper calendar UI, not a spreadsheet.

### The Bridge — Nightly Journal
- One journal entry per day, written/voiced late at night before sleep.
- Free-form dump: "I did this, I did that..."
- Gets parsed/categorized into ledgers: **emotional, productive, social, fitness, work.**
- Categorized entries populate that day's Reality layer.

### Daily Tracker UI (v1 — manual entry)
Single UI, one place to log everything for the day, split into topics:
- **Finances** — photograph receipts/purchases (see Photo Drop, above) or manually log spend as it happens; also covers per-account/per-card organization (bank accounts, credit cards, statement archive) and a reconciliation flow — upload a bank/credit-card CSV export, diff it against what's already logged, and get shown exactly what's missing/different before anything is written (see Approval before write)
- **Nutrition/Calories** — manual entry, recipe/meal presets (see Nutrition below), or a meal photo via Photo Drop (vision-estimated kcal/macros, you confirm or adjust before it's logged)
- **Alcohol** — intake logging
- **Fitness/Gym** — lifts, weights, sets done that day
- **Sleep** — auto-ingested from a fitness tracker (Whoop or Samsung Health — not yet locked in), not manually entered
- **Productivity**
- **Emotions**
- **Journal** — the nightly voice/text dump

*(Future, not v1): a single "common dump" input where you just talk/type and it auto-sorts into the right category, instead of manually picking fields.*

### Nutrition System (detail)
- **Meal presets with known macros** — e.g. "chicken meal" = 1lb chicken + 300 cal rice; "McDonald's Spicy Deluxe" = 2 patties, known calories/protein. Logging a preset is one tap instead of manual entry.
- **Grocery list preplanning** — tied to recipe presets, so shopping lists generate from planned meals.
- **Energy balance tracking** — daily log nets total calories in vs. total calories out (based on that day's runs, lifting sets, etc.) for a full daily in/out ledger.

---

## Pillar 2: Goals Dashboard

- Set goals per period (default: weekly) across categories — e.g. golf 2h, guitar 2h, gym 3h, run 1h, sales work 1h.
- Pulls from the Daily Tracker's logged data to show progress against those targets.
- Gives a "flow" view of how well you're living up to your own standards.
- **Goal types to support:** both time-based (hours per activity) *and* count/amount-based (e.g. "spend under $X this week," "eat under Y calories/day"), from v1.
- **Reusable pattern:** goal-tracking isn't only weekly — it can scope to any bounded event/project. Trip planning (see Travel below) is essentially a goals dashboard scoped to a specific trip instead of a week.

---

## Pillar 3: Knowledge Base (Chat-Driven)

### Mechanism
- A freeform scratchpad, not just a chat window — write, speak, explain, or draw (see Input modalities) with no pressure to organize as you go. A built-in chat model (Claude API or ChatGPT API) is one mode of this scratchpad, for banter/brainstorming/planning.
- Nothing is saved to the Knowledge Base automatically. When you mark a specific entry as important to keep, that's what triggers filing.
- On that trigger, the AI suggests a folder/subfolder based on content, you confirm or override with one tap before it's filed. If the right folder doesn't exist yet, create it on the fly. New top-level folders are always user-initiated (never auto-created without confirmation).

### Structure
One Knowledge Base, with subfolders/categories underneath it (not many separate top-level systems). Domains identified so far:

- **Sports & Activities** — subfolder per activity (e.g. Golf, Sailing), accumulating tricks/tips/lessons learned over time
- **Fitness (deep knowledge, beyond daily numeric logs)** — training philosophy/split (e.g. push/pull/legs Mon–Wed, run Thursday, swim Saturday, fight training Friday and Sunday), technique notes per lift (e.g. deadlift cues/form)
- **Social/Dating** — tactics, approach strategies, what works in different situations (organized conceptually like Barney Stinson's "Playbook" from *How I Met Your Mother* — a personal reference of approaches for different scenarios)
- **Relationships (general)** — lessons on how friends have treated you, interpersonal/philosophical reflections, partly derived from journal entries
- **Mental Models / Personal Philosophy** — the broader self-theory/worldview layer: confidence, stoicism, identity, motivators, notable experiences (good moments, insecurities, lessons learned) — distinct from Relationships, which is specifically about how others have treated you
- **Career & Education** — résumé versions, application pipeline (internships/jobs), academic records, a running skills-to-acquire roadmap
- **Travel** — see Travel section below
- **Projects** — future project ideas, past/completed projects and how they played out, including supporting files (STL files, logs, documentation)
- **Business** — business ideas and execution plans (kept distinct from life plans)
- **Life Planning / Financial Roadmap** — multi-year scenario planning (e.g. Plan A/B/D), income targets by year, investment allocations (e.g. $1,000/month into NASDAQ), major milestones (e.g. $450K townhouse in Virginia by 31), long-term progression (e.g. 3 properties by 50), parallel side-hustle/business track
- **Stocks/Investments** — research sorted by stock/sector; an evolving log of what you're holding and buy/sell reasoning over time (complements brokerage apps, doesn't replace them). Includes auto-reminders (e.g. "check portfolio every 2 days" → creates a recurring Calendar entry)
- **Major Purchases** — e.g. how you helped a friend buy a used car (CARFAX research, red flags, decision process); general pattern for big-ticket decisions
- **Social Media/Profile Planning** — content planning for Instagram, Hinge, LinkedIn; what's posted vs. queued; brainstorming profile/bio strategy via chat, pushing decisions into a folder; pulls from curated Photos
- **Media / Entertainment Log** — books/movies/shows watched and want-to-watch/read, personal summaries and reviews, playlists — a consumption backlog + log, not just a photo/social feed
- **Grooming** — routines by body area: hair (routine exists, specifics TBD — didn't come through clearly), face AM/PM steps (night: retinol + [second product unclear in dictation, confirm] + moisturizer; morning: moisturizer + sunscreen), nails (cut every Sunday)
- **Style & Dressing** — the rules/philosophy layer paired with Pillar 6's inventory: color rules, per-garment styling rules (shoes, suits, pants, t-shirts), dressing-for-your-age, aesthetic references — same split as Fitness above (deep knowledge here, daily logging/inventory lives in its own pillar)

**Aspirational/bucket-list items** (want to learn guitar, adventurous sports to try, car/house dream-planning) don't get a dedicated domain — they're filed as aspirational entries inside whatever domain they naturally belong to (guitar → Sports & Activities, adventurous sports → same, car/house dream-planning → Home Catalog / Life Planning). Confirmed: this is explicitly not part of the Goals Dashboard — it's a wishlist, not something being actively tracked yet.

---

## Pillar 4: Photo Journal / Visual Memory

- Organized hierarchically: **Year → Month → Date**.
- Curated, not a full camera-roll dump — select ~10 good photos per day into that date's folder.
- **Retrieval:** ask "what was I doing March 13th?" → pulls that day's journal entry + photo folder together.
- **Face recognition:** model tags people across photos ("Person A," "Person B") so it can answer "who were you with" (e.g. "you were with Mark on March 13th").
- **Scene/location recognition:** model reads photo content (e.g. detects a beach) and cross-references location metadata to enrich the memory (e.g. "you were in the Bahamas").
- End result: ask about a date, get a fused narrative — journal text + who + where, backed by photos.
- **Trip-specific photo folders** — separate from the daily photo journal, one per trip (e.g. "Bahamas trip"), tying together that trip's journal entries, checklist, and photos into one story.

**Implementation note (2026-09-08):** the foundation for this is now actually built, ahead of the pillar itself. Batch-dropped photos get real EXIF date/GPS extraction (deterministic, no AI) and land in real `Media/Photos/<Year>/<Month>/<Trip Name or Country/State/City>/` folders — full-res, as-is. A photo's date, when it matches a day you journaled, becomes a graph edge (`journal:<date>` node) connecting that photo's note to that day's entry. So "trip-specific photo folders tying together journal entries and photos" already exists at the data layer. **New idea from today's ideation, not yet built:** a "trip recap" generator — pull every journal entry written during a trip's date range plus every photo filed under that trip's folder, and have AI assemble them into one cohesive markdown summary document ("what I did on this trip"), reviewed/edited before saving like everything else in this app. Still open/not built: face recognition, scene recognition (deferred per `deployment-and-privacy.md` — on-device model, not urgent), and a proper photo-gallery browsing UI (see Pillar 9's photo-picker note — same missing piece, two use cases).

---

## Pillar 5: Document Vault

- Stores important documents: lease agreements, driver's license, Social Security, OPT paperwork, etc.
- Tracks not just the document but the *process/history* of obtaining it.
- **Calendar integration:** deadline-based documents (e.g. OPT renewal due December 13th) auto-populate onto the Plan calendar.
- v1: manual upload/organize/retrieve.
- Future: AI retrieval — ask "show me my driver's license" and it's pulled directly.

### Digital/Tech Vault (same pillar — the digital counterpart to the physical documents above)
- **Device setup & recovery** — how to rebuild a laptop or phone from scratch: OS setup steps, app inventories per device, backup process, home-screen/layout setup. This is the concrete version of the disaster-recovery principle for a lost/wiped device.
- **Per-service account/setup notes** — setup notes per website/service (GitHub, LinkedIn, Instagram, dating apps, etc.) — the configuration/process notes, not the login itself.
- **Network config** — home wifi/network setup, so it's reconstructible without asking a roommate/landlord to remind you.
- **Credentials/passwords** — required for full device/account recovery, but too sensitive for the plain markdown tree. Lives in a **separate encrypted vault** (e.g. an age/gpg-encrypted file, or a dedicated tool) just for this one category — outside the regular markdown KB, not synced/read the same way as everything else.

---

## Pillar 6: Wardrobe & Outfit Planner

- Inventory: sunglasses, watches, jackets, jeans, etc. — photographed and logged.
- New item → photo (via Photo Drop) → added to inventory catalog → available for outfit planning.
- Full-outfit photo (via Photo Drop) → logged as a complete look in the outfit catalog, distinct from adding a single item — a reusable "this is an outfit I have" entry, not just a pile of individually-cataloged pieces.
- Outfit planner: plan outfits from logged inventory and/or pull directly from the outfit catalog.
- Style rules/philosophy (color rules, per-garment styling rules, aesthetic references) live in the Knowledge Base's **Style & Dressing** domain, not here — this pillar is the inventory + outfit-building mechanism, KB is the deep reference layer (same split as Fitness).

---

## Pillar 7: Travel

- **Wishlist** — places you want to go.
- **Log** — places you've been.
- **Pre-trip planning** — checklist of things to see/do for a specific trip, built ahead of time, checked off during the trip.
- **Trip-specific photo folder** — tied to that trip's journal/checklist (see Photo Journal above).
- **Packing/preset lists by trip type** — reusable checklists (e.g. "beach trip," "1-day formal trip → 1 dress shirt, 1 suit"), built once and reused.

**Implementation note (2026-09-08):** trip-name detection during batch photo drop (AI sees the whole batch at once, recognizes a shared trip, folders accordingly) and the resulting `Media/Photos/<Year>/<Month>/<Trip Name>/` folder are built — see Pillar 4's note. The trip *recap document* (journal + photos → one markdown story) is still just an idea, not built.

---

## Pillar 8: Home & Belongings Catalog

- Tracks apartments/living spaces over time (e.g. Standard College Park → The Iris DC studio → one-bed).
- Records furniture/decor choices and reasoning per place.
- Closet/storage organization per apartment.
- **Cataloging system:** ask "where's my Halloween decor?" → get a precise answer (e.g. "Iris apartment, closet, box 3").
- Persists as an inventory + location index across moves.
- **Move checklist** — a reusable template (same pattern as Travel's packing lists, built once and reused) of everywhere your address needs to be updated when you move: bank, DMV/state ID, employer/payroll, insurance, subscriptions, voter registration, USPS mail forwarding, etc. Triggered when you log a move; each item can spawn a Calendar task via cross-linking, same as Document Vault's deadline items.

---

## Pillar 9: Marketplace & Social Media Post Archive

Two things that turned out to be the same idea (ideation session, 2026-09-08): curating a
marketplace listing (FB Marketplace — laptops, furniture, etc.) and curating a social post
(Instagram/LinkedIn/dating apps) are both "pick existing photo(s), write/choose a caption or
description (+ price for marketplace), save as a permanent record" — one generalized mechanism,
parameterized by kind, not two separate builds.

**Explicit scope boundary:** this is a curation + archive tool, not a publishing tool. No API
calls to Instagram/LinkedIn/FB/dating apps — confirmed, the user wants this fully manual (pick
photo, finalize caption yourself, post it on the actual platform by hand, this app just keeps
the permanent local record of what was posted/listed). The "in case my Instagram gets bombed"
framing is about not losing your own record, not about automating posting — OAuth/app-review/
rate-limit complexity for each platform is explicitly out of scope.

**What already exists to build this on:** `Multimedia/Social Media Planning` is already a seeded
KB folder; KB entries already support one attached asset + AI-proposed folder/title/content,
exactly the shape of "photo + caption, filed somewhere."

**What's genuinely new and would need building:**
1. **A photo picker/gallery UI** — "choose from photos already in my app" doesn't exist yet.
   `kb/browse` is a topic-tree browser, not a scannable gallery you can multi-select from. This
   is the same missing piece flagged for Year/Month/Day photo browsing (Pillar 4) — one gallery
   view should serve both: browsing your camera roll, and picking photos for a post/listing.
2. **Multi-asset support per entry** — every KB entry currently supports exactly ONE attached
   asset (`[asset](path)`, one regex match). A real Instagram carousel or a marketplace listing
   usually has 2-10 photos. This needs genuine multi-asset support, not just reuse of the
   current single-photo convention.

**Open questions, not yet decided:**
- Captions: AI proposes caption options from the photo (+ your rough notes) that you pick/edit
  from — matching the "AI proposes, you review" pattern everywhere else in this app — or a blank
  box you write yourself? Leaning toward AI-proposed-by-default given the rest of the app, but
  not confirmed.
- Marketplace: real price + sold/active status fields (so "what's still listed" is answerable),
  or a pure archive with no status tracking?
- Should a saved post/listing link back (via the links/graph system) to the photo's original
  source — e.g. a marketplace listing photo that was also filed under a Media/Photos trip
  folder? Feels like a natural yes, not confirmed.

**Deferred:** building this — next priority is the financial layer (CSV import/reconciliation
from Amex/Robinhood etc., already deferred once before this session).

---

## Decisions (resolved 2026-09-04)

1. **Storage backend:** hybrid — markdown as source of truth, generated/disposable index for querying. See Cross-Cutting Principles.
2. **Goal types:** both time-based and count/amount-based, in v1. See Pillar 2.
3. **Folder auto-sorting:** AI-suggested, user-confirmed. New top-level folders always user-initiated. See Pillar 3.
4. **Sync conflict handling:** last-write-wins, with losing version saved as a `.conflict` backup on true conflicts. See Cross-Cutting Principles.
5. **Digital Tech Vault:** folded into the Document Vault pillar, not a separate pillar — device setup/recovery, per-service setup notes, and network config are plain markdown; credentials live in a separate encrypted sub-vault. See Pillar 5.
6. **Bucket-list/aspirational items:** no dedicated KB domain — filed into whichever existing KB domain fits, not part of the Goals Dashboard. See Pillar 3.
7. **S-Pen input:** both an import path (drop in a PDF/image drawn elsewhere) and a native in-app drawing canvas, from v1. See Cross-Cutting Principles.
8. **Data-mutation approval:** every AI-proposed change to the real store (folder-sort, CSV reconciliation diffs, etc.) is shown as a diff and requires explicit user approval before writing — generalizes decision #3 to all mutations, not just KB filing. See Cross-Cutting Principles.
9. **Photo Drop:** a separate utility-inbox pathway from the Photo Journal — every dropped photo is vision-classified, routed with user confirmation, and kept permanently alongside whatever entry it produced. See Photo Drop section.

---

## Suggested Build Order (for discussion, not final)

1. Daily Tracker (manual entry across categories) + basic Plan/Reality calendar
2. Goals Dashboard pulling from Daily Tracker data
3. Knowledge Base with manual folder creation + chat-to-folder push (no AI auto-sort yet)
4. Document Vault (manual)
5. Photo Journal (manual curation first; face/scene recognition later)
6. Everything else (Wardrobe, Travel, Home Catalog, Marketplace, Social Media Planner) as Knowledge Base subfolders, added incrementally
7. AI retrieval layer across all of the above, once the manual base is solid and populated with real data
