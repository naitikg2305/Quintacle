# Next wave — the hash-out doc

Status: **planning, live document, started 2026-10-19.** Naitik's post-build
wants, captured as they come to mind, hashed out section by section in
conversation, then promoted to builds. Same spirit as
`test-plan-and-wishlist.md` was for the first wave. Each section carries:
what exists today (code-verified), the want in his words, the decisions made
while hashing, and what's deliberately deferred.

Rule for this doc: nothing here is committed-to until its "Decisions"
subsection says so.

---

## 1. Finance — spend categories, goals, and "how have I been spending"

**His words:** "I wanna see if I'm hitting my financial goals… it's all
random rn… I do want categories of spend and how I have been spending
money."

**Exists today (verified 2026-10-19):**
- Expense capture with 7 AI-classified kinds (subscription / food / alcohol
  / experience / shopping / big_purchase / regular) + free-text category +
  merchant, via Drop/Journal/Finance-page/MCP; graph- and day-wired.
- Finance page = a ledger viewer (7 kind tabs over 2 years). Cards and
  investments = static reference records (manual points balance, cost
  basis; no prices).
- ONE goal mechanism: habit quotas with metric=spend — **total** spend ≤ $X
  per week/month, dashboard progress + history. Totals only; the engine
  ignores kind/category even though activity quotas already do per-category
  matching.

**The gaps this section is about:**
1. **Per-kind budgets** — "food ≤ $X/wk", "alcohol ≤ $Y/mo",
   "subscriptions ≤ $Z/mo" as dashboard lines with history. (Cheapest
   build: the spend metric honoring match_category like activities do.)
2. **Spend analysis / retrospective** — "how have I been spending": by
   kind over time, month vs month, merchant rollups, biggest movers.
   Deterministic SQL, zero models. Where does it live — Finance page tab,
   Dashboard section, or its own view?
3. **Income side** — without it there's no savings rate or spent-vs-earned.
   Track it or stay expense-only?
4. **Accumulation goals** — "save $5k by March" (habits are rate caps, not
   targets). Wanted now or later?
5. **Subscription intelligence** — recurrence detection, monthly burn
   total, renewal awareness (kind=subscription exists; intelligence
   doesn't).
6. **Points / cards usage** — earning/burning over time vs the static
   balance field.
7. **Investments** — live-ish valuation? (external price data = a new
   dependency class; decide deliberately).

**Decisions (hashing in progress):**
- (none yet)

**Deferred:**
- (none yet)

---

## 2. (next topic as it comes to mind)

