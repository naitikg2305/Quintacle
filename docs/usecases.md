# Quintacle — Usability test: use cases

Status: **test protocol, not results yet.** Written 2026-09-29. The point is
to run a handful of real scenarios through what's *already built*, watch how
it acts and reacts, and write down where it did what was wanted vs. where it
didn't. The results feed one decision:

> **Generic or bespoke?** Make Quintacle as generic as possible (a
> folder-is-a-page, type-agnostic store any model can plug into — the
> `mcp-angle.md` direction pushed to its limit), or code every node exactly
> the way Naitik wants it coded (the current ~15 hand-built entry types,
> each with its own schema, prompt, and UI).

Don't decide before running these. Fill in the **Observed** blocks as you
go; the **Wanted** blocks are the bar it's being held to — edit them if the
bar was wrong.

## How to run

```bash
# backend
cd core && .venv/bin/uvicorn quintacle_core.api:app --port 8000
# frontend
cd frontend && npm run dev
```

Data lands in `~/.quintacle/` (markdown + `quintacle.db`). Inspect after each
case with `sqlite3 ~/.quintacle/quintacle.db` or `ls ~/.quintacle/kb`.

Legend for the verdict field: **✓ as wanted** · **~ close, friction** ·
**✗ wrong** · **— not possible today**.

---

## UC1 — Capture a thing I just learned, mid-flow

**Scenario.** Between sets at the gym. Just figured out from an AI chat that
you should warm up rotator cuffs before pressing. Want it captured and gone
from your head in under 15 seconds.

**Input.** Drop page (`/kb/drop`), text only:
```
note: warm up rotator cuffs with band external rotations before any pressing — 2x15 light, prevents the shoulder pinch
```
Then the same thing again **without** the `note:` prefix.

**Wanted.**
- Prefixed: zero AI wait, lands as a KB entry, proposes a folder that makes
  sense (or asks), one tap to confirm.
- Unprefixed: classifies as a KB note (not a todo, not an exercise log),
  same folder proposal.
- Total interaction: type → glance at proposal → confirm. Nothing to edit.
- Findable later by searching "rotator" or "shoulder".

**Observed.**
- Prefixed:
- Unprefixed:
- Folder proposed:
- Taps to confirm:
- Search finds it:
- Verdict:

---

## UC2 — The nightly dump

**Scenario.** End of day, one paragraph, several kinds of things mixed
together.

**Input.** Journal page (`/journal`), today's date, then parse:
```
gym at 7, did pull day — pullups 3x8, rows 3x10 at 135, lat pulldown 3x12 at 120. lunch was the usual chicken rice bowl. spent 14.50 on chipotle for dinner. need to call the landlord tomorrow about the lease. felt pretty scattered today, maybe 3 hours of actual focused work. weight 172.
```

**Wanted.**
- One parse → separate proposed entries: exercise (3 exercises with sets),
  food ×2 (lunch matched to a known meal if one exists, dinner estimated),
  finance ($14.50 Chipotle), todo (call landlord, due tomorrow), activity
  (productivity, 3h), body stat (172 lb).
- "The usual chicken rice bowl" → matches an existing meal preset if there is
  one, otherwise proposes creating one.
- "Pull day" → matches the existing routine if one exists.
- "tomorrow" resolves to the right date.
- Nothing silently dropped. Nothing hallucinated (no invented kcal precision,
  no made-up merchant category).
- Each proposed entry editable before commit; commit writes to the right
  stores; Day page (`/day`) shows all of it.

**Observed.**
- Entries proposed (count/types):
- Anything missed:
- Anything invented:
- Meal/routine matching:
- Date resolution:
- Day page after commit:
- Verdict:

---

## UC3 — Photo drop with no explanation

**Scenario.** Took a photo of a receipt. Took a photo of a nutrition label.
Took a mirror selfie in an outfit. Drop each with **no text**.

**Input.** Drop page, file only, three separate drops.

**Wanted.**
- Receipt → finance entry with amount + merchant + date read off the receipt
  itself (not today's date).
- Nutrition label → ingredient preset with macros read off the label.
- Outfit selfie → outfit photo, saved as-is, not decomposed into items.
- Each classification correct on the first try, no prompt asking "what is
  this?".
- If the vision call misclassifies, the fix is one dropdown change on the
  proposal, not a re-drop.

**Observed.**
- Receipt:
- Label:
- Selfie:
- Misclassification recovery:
- Verdict:

---

## UC4 — Ask it something about my own past

**Scenario.** "What did I eat last Tuesday and how did it compare to my
targets?" This is the narration edge — the thing `architecture.md` says is
the LLM's only real job.

**Input.** Two attempts:
1. Day page (`/day`) for that date, read it off manually.
2. KB chat (`/kb`) with KB context on, ask the question in natural language.

**Wanted.**
- (1) Everything is *there* and readable in one screen: food, nutrition vs.
  targets, exercise, activities, expenses, journal text.
- (2) Ideally: a correct answer from the real data. Realistically: this
  probably **can't** work today — the KB chat is grounded on KB markdown, not
  on the SQLite logs. Write down whether it answers, hallucinates, or says
  it doesn't know. This is the case that most directly motivates MCP.

**Observed.**
- Day page completeness:
- Chat answer:
- Did it hallucinate:
- Verdict:

---

## UC5 — A learned "skill" that doesn't fit any node

**Scenario.** The car-buying knowledge from `intro.md`: how to help someone
buy a used car — inspection checklist, negotiation points, what paperwork.
It's not a todo, a log, a finance entry, or a person. It's reference
knowledge.

**Input.** Drop page, a real ~10-line writeup as text, no prefix. Then try
the same via Browse (`/kb/browse`) creating a folder/page by hand.

**Wanted.**
- Drop: classifies as KB, proposes a sensible folder (new one if needed —
  something like `skills/` or `reference/`), doesn't try to turn it into
  structured fields it doesn't have.
- Browse: making a new folder and page by hand is as fast as the drop, and
  the result is indistinguishable from a dropped one.
- Later, the "folder = page" Browse view (Phase E) renders it as a proper
  page, not a raw file list.

**Observed.**
- Drop classification/folder:
- Hand-made via Browse:
- Rendering:
- Verdict:

---

## UC6 — Something it has no type for

**Scenario.** Deliberately out of distribution. E.g. "car: oil change done at
84,200 miles, next at 89k" — there's a `car.md` planning doc but **no car
node**, no `car:` prefix, no maintenance store.

**Input.** Drop page, that text, no prefix and then with `car:`.

**Wanted (this is the real question).**
- Does it degrade gracefully into a KB note in a `car/` folder (generic
  behavior, still useful, findable)?
- Or does it force-fit into a wrong type (finance? todo?) because the
  classifier has to pick from a fixed set?
- The answer to *this* case is most of the generic-vs-bespoke decision. If
  the fallback is good, generic wins a lot of ground. If the fallback is bad,
  every domain needs bespoke code before it's usable.

**Observed.**
- Unprefixed → type chosen:
- `car:` prefix → behavior:
- Was the result findable/useful anyway:
- Verdict:

---

## UC7 — Fix a mistake

**Scenario.** UC2 logged the Chipotle expense to the wrong category, and the
rotator cuff note from UC1 went into the wrong folder.

**Input.** Finance page (`/finance`) → find the entry → change category.
Browse → find the note → move it.

**Wanted.**
- Both fixable in the UI without touching files or SQLite directly.
- Under 30 seconds each.
- Moving a KB entry doesn't break its links/assets.

**Observed.**
- Finance edit:
- KB move:
- Verdict:

---

## UC8 — Phone

**Scenario.** Repeat UC1 and UC3 on the phone over LAN (frontend pointed at
the desktop's IP).

**Wanted.**
- Drop is thumb-reachable, one-handed.
- Photo drop goes straight to camera.
- Proposal review readable without zooming; confirm is one tap.
- Bottom-sheet / full-screen patterns from the UI redo actually help here.

**Observed.**
- UC1 on phone:
- UC3 on phone:
- Verdict:

---

## Scoring the generic-vs-bespoke call

After running the above, sort every friction point into one of these:

| Bucket | Meaning | Pushes toward |
|---|---|---|
| **A. Wrong type / forced fit** | The fixed type set made a bad choice (UC6, unprefixed UC1/UC5) | Generic — a looser store + model-side interpretation would have been fine |
| **B. Missing structure** | It landed as a blob when a typed record was wanted (UC2 macros, UC3 receipt date) | Bespoke — the value *was* the schema |
| **C. Prompt/UI friction** | Right type, right data, annoying to get there (taps, edits, layout) | Neither — just polish |
| **D. Not possible** | UC4-style: the capability doesn't exist yet | MCP / narration work, orthogonal to the decision |

Rough rule: if **A** dominates, go generic and let the model (via MCP)
interpret structure at read time. If **B** dominates, the bespoke types are
earning their keep — keep building them, and make MCP a thin door onto them.
If it's mostly **C**, the architecture is fine and this is a UI redo
question. If **D** is loud, build MCP first and re-run these.

Likely outcome to watch for: **both A and B are real**, in which case the
answer is a hybrid — a small set of dense, typed nodes where structure is the
whole point (logs, nutrition, finance) sitting next to a generic KB where
everything else lands as a page in a folder. That's roughly what exists now,
and the test is whether the *boundary* is in the right place.

## Results

(fill in after running — date, overall verdict, decision, what to change)
