# Quintacle — Schedule / Todo (Node)

The domain named back in `intro.md` as "scheduling" — this is where it actually
lands, and it turns out to be Todo + Calendar as one coupled system rather than
two separate things.

## The loop

- The nightly Journal check-in (`habits-and-checkin.md`) includes a **todo
  section for the next day** — this is one entry point for new todo items.
- Each todo has a **priority** and (at least sometimes) a **due date**.
- Todos **update the calendar automatically, ordered by priority** — the
  calendar isn't a separately-maintained thing, it's populated from the todo
  list.
- The system also **self-generates a todo list based on due dates** — separate
  from what's manually entered, it surfaces/ranks upcoming items as their due
  dates approach.

## Architectural note: the self-generation piece needs no AI

Ranking or surfacing todos by due-date proximity is pure deterministic logic —
sort by date, apply priority as a tiebreaker. This is a clean concrete instance
of `architecture.md`'s core claim that most of the system doesn't need AI at
all; an LLM would only enter here if turning the ranked list into a spoken/narrated
daily briefing, not for the ranking itself.

## Open questions (not decided yet)

- How priority gets set — manually tagged each time, or inferred somehow?
- Does "self-generated todo" mean the system proposes items for review, or does
  it add directly to the live list on its own?
- How one-off todos and `routines.md`'s recurring checklist items (e.g. Sunday
  Reset) share the same calendar surface — same list, different item type? Or
  kept visually/structurally separate?
- Does the calendar hold anything beyond todos (fixed-time appointments, etc.),
  or is it purely todo-driven for now?
