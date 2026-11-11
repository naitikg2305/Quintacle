# Missing use cases: daily model decisions with no live test yet (2026-11-11)

These come from the coverage audit (`model-coverage-2026-11-11.md`). Each one runs every day, involves
a model making a decision, and no live test checked it on 2026-11-11. Each section says:
- what you do;
- what should happen;
- why it matters;
- where the test stands;
- how to check it by hand.

Tests for 1–7 are being written into `core/tests/claude/` and will run after the owner's testing
session. Cases marked **needs your files** go into `core/tests/user/` with you.

---

## 1. People mentioned in a drop or journal entry

**What you do:** "coffee with Arjun at Compass, talked about his startup", or "met a new guy named Theo
Park at the climbing gym".

**What should happen:**
- A person you already have ("Arjun", saved as Arjun Mehta) gets **linked**, not duplicated.
- A new person gets **proposed** as a new person for you to confirm.
- The entry is linked to that person in the graph, so "when did I last see Arjun?" works.

**Why it matters:** people pages and "what did I do with X" depend on it. A duplicate "Arjun" splits
your history in two.

**Test:** being written, using a seeded person plus a new one.

**By hand:** drop a line mentioning someone you've saved, then open their person page.

## 2. Photo object tags and face matching

**What you do:** drop any photo, or a batch.

**What should happen:**
- YOLO tags the objects (person, dog, bicycle…) and scene.
- Faces are matched to your enrolled people.
- This all happens locally. The tags and names get baked into the note, so search ("photos with
  Arjun", "photos with my bike") works for weak local models.

**Why it matters:** photo search and "who was there" depend on it.

**Test:** object tags are being written with a generated image. Face matching **needs your files**:
real photos of enrolled people, in `tests/user`.

**By hand:** drop a photo with a known face, then check the note lists the person.

## 3. A food photo with no label

**What you do:** a photo of a plate, an onion or a bowl of pasta, with no nutrition label.

**What should happen:**
- It's read locally: YOLO plus the local vision model name the food ("Red onion").
- Grams are estimated, and the name is matched to USDA for full macros and micros.
- Cloud is used only if you press "Redo with cloud".

**Why it matters:** this is your food-logging path. The golden check found it slow (50–80 s per photo,
GPU memory contention) and weak on plain items ("bell pepper" not matching USDA).

**Test:** **needs your files.** Synthetic food photos aren't realistic, so this uses your
`Food recipe/inputs/` photos in `tests/user`.

**By hand:** drop 3–4 of those photos and check the names, the USDA match and the time taken.

## 4. One-line summaries for every saved note

**What you do:** save any note, journal entry or drop.

**What should happen:** a local model writes a one-line summary into the search index, so retrieval
and the graph can say what a note is about without reading all of it.

**Why it matters:** weak or local models answer from these summaries. A bad or empty summary makes the
note hard to find.

**Test:** being written. It turns the summary lane on for that one test (it's off in every other test
to keep them fast and deterministic).

**By hand:** save a note, then ask chat something only that note answers, using different words.

## 5. Embeddings: search by meaning, not keywords

**What you do:** search, or ask chat, "how often do I feed my bread yeast culture" when the note says
"sourdough starter feeding schedule".

**What should happen:** the vector lane (embeddinggemma, local) finds the note even though no words
match.

**Why it matters:** keyword search misses whenever you phrase things differently from how you wrote
them, which is most of the time.

**Test:** being written. It skips if sqlite-vec or embeddinggemma isn't installed.

**By hand:** search a paraphrase of a note's topic.

## 6. Facts pulled out of your chats

**What you do:** chat normally and mention a fact in passing ("my sister Priya lives in Austin").

**What should happen:** when the chat ends, a local model extracts lasting facts into your soft record,
so later chats and "what do I know about Priya" can use them.

**Why it matters:** this is how casual chat feeds long-term memory without you writing notes.

**Test:** being written, using a final transcript save plus the extraction.

**By hand:** mention a fact in chat, leave the page, then ask about it in a new chat.

## 7. Web search in chat

**What you do:** ask chat something current ("where's the Centurion Lounge at Heathrow?") with the 🌐
toggle on or auto.

**What should happen:** chat searches the web, answers, and cites the source URL. Local models work
too, including the 1.5B on the phone.

**Why it matters:** your "small cute questions" use case.

**Test:** being written. **It will skip until a search backend is configured:** a free Brave Search key
in `core/.env`, or a SearXNG instance. DuckDuckGo blocks automated searches.

**By hand:** needs the Brave key first.

---

## Status after the run

Add dated results here once the new tests run, as pass/fail per case, and which are moved to
`tests/user`.

### 2026-11-11 run (local and Claude via Max)

First run: 4 failures on each model, the same 4 on both, so they were code or test bugs, not model
bugs.

| Case | Result | What was wrong → fix |
|---|---|---|
| 1. People: full name | **Pass** | Test bug: it looked for the folder `people/arjun mehta` but the folder uses the slug `people/arjun-mehta`. The app was right. |
| 1. People: first name only ("coffee with Arjun") | **Pass** after fix | Code bug: the free pre-check matched full names only, so the model was never asked. Now a first name that only one tracked person has also triggers, and code (not the model) maps "Arjun" → Arjun Mehta. "met a new guy named Arjun" still proposes a new person. |
| 1. People: new person | Pass | — |
| 1. People: journal page | **Pass** after the slug test fix | — |
| 2. Photo object tags | Pass | Face matching skipped: needs real faces → `tests/user`. |
| 3. Food photo | Skipped | Needs your photos → `tests/user`. |
| 4. Note summaries | **Pass** after fix | Code bug: the model overran "under 20 words" and code cut at 120 characters mid-word ("…, cost"). Now code keeps whole words, at most 19, and the prompt asks for 15. |
| 5. Embeddings | Pass | — |
| 6. Chat fact extraction | Pass | — |
| 7. Web search | Skipped locally (no Brave key); Max pass | — |

Final: local **16 pass, 0 fail, 3 skip**; Max **17 pass, 0 fail, 2 skip**. Faked suite 1,328 pass.

Seen but not asserted: on the local model, the experience proposal for "dinner at Compass" invented a
city (San Francisco) and a visit date (2023-10-15). That's the same "local model invents facts" pattern
the home-item guard fixed; worth a code guard (keep only what the text states).

### 2026-11-11 follow-up: no invented city or date on experiences

`guard_experience` (travel/llm.py) keeps a city only when its words are in the text, and a visit date only
when the text states one (a date, or one relative phrase resolved in code). The live full-name people check
now asserts no city/date is invented for "dinner … at Compass".

Full live suites after this: local **80 pass, 0 fail, 4 skip**; Max **78 pass, 0 fail, 3 skip**.
Faked suite 1,331 pass. Skips: outfit photo, faces, food photo (all → `tests/user`), web search locally
(no Brave key).
