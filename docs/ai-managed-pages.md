# AI-managed generic pages

Status: **idea, discussion only, not started.** Conversation on 2026-10-13.
Naitik is going to expand on this — treat what's below as the opening frame,
not the final shape.

## The problem this is answering

From `usecases.md`'s generic-vs-bespoke question, pushed further: Naitik
doesn't want to ever pick "this needs a Car node" and wait for someone to
hand-code it. He wants to just talk about the thing — a repair, a mileage
reading, a Carfax report — and have the AI build and keep growing whatever
structure that thing deserves. In his words: "best is literally a generic
page that AI can manage and create."

**The worked example:** a car. He wants to talk about replacing sway bar
links at 184k miles, drop a Carfax PDF, mention an oil change — and end up
with something that *looks* like a dedicated car page: a photo of the car up
top, a maintenance table (mileage, part, cost, date), and ideally something
that tells him what's coming due given his current mileage. Not a pile of
loose notes that happen to mention a car.

## What already exists that's closer to this than it looks

Checked against the actual code on 2026-10-13, not assumed:

- **KB entries already support an open `fields` dict**, separate from title/
  content/links (`nodes/kb/store.py`, `_INTERNAL_META`; `POST /kb/entry`
  already accepts `fields` in the request body). This is exactly the "AI
  decides the schema per entry" storage shape — it's built and basically
  unused.
- **Phase E's view inference already turns shared fields into a table with
  zero code per domain** (`nodes/kb/view.py: infer_view`): if entries in a
  folder share 3+ scalar fields, it's a table, picking the 4 most common as
  columns; if most entries carry a photo, it's a gallery; otherwise cards or
  a list. A car folder with the right frontmatter would already render as a
  table today.
- **What's missing is earlier in the pipeline**: the KB drop classifier
  (`nodes/kb/llm.py: suggest_kb_entry` / `KBSuggestion`) only ever proposes
  `folder`, `title`, `content` (prose), `links`. It never proposes `fields`.
  So "replaced sway bar links at 184k, $220, DIY" becomes a paragraph, not
  `{mileage: 184000, part: "sway bar end links", cost: 220, type: "DIY"}`.
  The storage and rendering are ready; the authoring step isn't.

## What graph + MCP would and wouldn't buy

Direct answer to "would building the graph and the MCP make a lot of this
possible": partly, but not as the primary mechanism.

- **MCP is the door**, not the structure. It's what lets "I was just talking
  about my car in this chat" become a write at all, from wherever he
  actually is, gated by the approval queue already designed in
  `mcp-angle.md`. It doesn't decide what fields a car page needs.
- **The graph (the `links` field, [[graph-model.md]]) is the connective
  tissue** — tying a Carfax PDF, a repair receipt, and the matching finance
  expense entry to the same car folder. Real, and already half-built; this
  use case would exercise it for the first time.
- **The piece that actually gets you the car-page feel is neither of
  those**: a smarter authoring step that extracts structured fields from a
  drop instead of just filing it as prose, plus a small generic computation
  layer on top of folders that have the right shape.

## What would actually need building, roughly in order

1. **Structured-field extraction in the drop classifier.** Given a drop that
   looks like a data point about an existing folder/entity (not just a
   thought), propose `fields: {...}` the way it already proposes `links`.
   Open schema — the model picks the keys, same spirit as the rest of
   Quintacle's "AI only at the edges."
2. **Field-name canonicalization per folder.** Without this, "mileage" /
   "odometer" / "miles" fragment into separate columns across entries and
   Phase E's table inference falls apart. Same problem
   `nodes/journal/normalize.py` already solved for exercise/activity names —
   reconcile new field names against what a folder's existing entries
   already use, deterministically, before the entry is saved.
3. **A cover-photo convention per folder**, so a folder with a hero image
   renders as a page header rather than just another gallery item. Small
   addition to `view.py` / `FolderView.tsx`.
4. **A generic "what's coming due" computation.** Not car-specific: any
   folder where entries carry a numeric progression field (mileage, hours
   used, whatever) plus a type/category, work out what's next and how close
   it is. Same mechanism class as `logs/quotas.py`'s generic goal engine,
   applied to KB folders instead of the activity log.
5. **MCP as the interface** that lets step 1 get triggered from any chat
   (Claude, GPT, whatever), with the approval queue from `mcp-angle.md`
   gating the write.

## The honest tradeoff

This leans the generic-vs-bespoke call (`usecases.md`) hard toward generic:
no more hand-built nodes for new life domains, ever — the AI grows the
schema as he adds more. That's viable with what's already in the codebase.
The risk it trades in return is #2 above: an AI inventing slightly different
field names every time is the actual failure mode to watch for once this is
testable, not "the node didn't exist."

## Open questions (Naitik to expand)

- How aggressive should field extraction be — only when a drop clearly reads
  as a data point (a number, a date, a specific part/amount), or always
  attempt it and let a thin fallback keep pure KB notes pure?
- Does the "what's due" computation need a place to store the *schedule*
  itself (e.g. "oil change every 5k miles") as its own structured fact, or
  can it be inferred from the history of entries alone?
- Does this replace or sit alongside the existing bespoke nodes (wardrobe,
  grooming, finance, etc.), or do some of those eventually collapse into
  generic folders too?
- Where does the "page" live in the UI — is Browse's FolderView the car
  page, or does this want its own presentation once a folder has a cover
  photo and a schedule?
