# Quintacle — Ledger (Node)

## What it captures

Every purchase logs in as it happens: groceries, drinks, paying for someone else, etc.

## Monthly reconciliation

At the end of each month, upload the statement for each credit card. The system
tallies things like how much was made/spent per card that month.

## Why it's its own node

Financial data has its own shape (amounts, dates, categories, per-card statements)
and its own cadence (log-as-you-go + monthly rollup) — separate from the journal
node, but the numbers here are what actually validate progress against the savings
targets in `schemes.md` (e.g. the base plan's "save 80 grand in a year").

## Open questions (not decided yet)

- Purchase categorization scheme (groceries vs. drinks vs. paying-for-a-friend, etc.)
- How statement upload/parsing works (manual paste, PDF/CSV import, bank API?)
- How ledger data feeds into `schemes.md` progress tracking (automatic tie-in, or
  a separate manual check-in?)
