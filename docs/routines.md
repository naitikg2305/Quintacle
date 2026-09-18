# Quintacle — Routines (Node)

## What this is

A routine is a named, recurring checklist tied to a cadence (like the cadences in
`habits-and-checkin.md`), where each item on the checklist is really an action in
a *different* node. This is the clearest concrete example of nodes being
interconnected rather than isolated silos.

## Example: Sunday Reset

Every Sunday:

- Clean the apartment -> `apartment.md`
- Sort finances -> `ledger.md`
- Get groceries -> `diet.md` (the week's grocery list)
- Get gas -> `car.md`
- Update whatever else needs updating (general catch-all maintenance sweep)

## Why this matters architecturally

A routine doesn't own its own data — it's a schedule-triggered pointer into other
nodes' actions. So the system needs a way to say "every Sunday, surface these N
action items, each of which resolves into its own node," rather than treating
Sunday Reset as a flat unrelated to-do list. This is the same "structure over
blob" principle from `architecture.md`, applied to routines: don't store
duplicated logic per routine, reference the real node each item belongs to.

## Open questions (not decided yet)

- Are there other recurring routines besides Sunday Reset? (daily / other weekly ones?)
- Does completing a routine item automatically update the target node (e.g.
  checking off "get groceries" ties back into `diet.md`'s tracking), or is it a
  separate checklist that just reminds him to go do the real thing in each node?
- How this relates to `habits-and-checkin.md`'s quota system — is a routine just
  another kind of cadence-tracked item, or a distinct concept from quotas?
