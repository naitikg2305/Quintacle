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

**Decisions (2026-10-19):**
1. **Spend analysis: ALL views, yes** — monthly totals by kind over time,
   month-vs-last-month deltas, merchant rollups. Placement (Claude's call,
   standing unless overridden): a new **Insights** tab on the Finance page
   (money reads together), while budget lines surface on the **Dashboard**
   automatically (they ride the habit engine, which already lives there).
   Deterministic SQL only — zero model calls anywhere in analysis.
2. **Budgets: named custom lines from day one**, not just the 7 kinds —
   "winery $50 this weekend", "one 222 + one date a week", "creatine +
   alcohol monthly". Design: extend the habit/quota engine — spend metric
   gains a matcher (kind, and/or whole-word text match on
   merchant/category/notes, reusing THE matcher), habit name = the line's
   name. Per-kind lines are just the simplest case of this.
3. **Income: in scope.** New income entries (date, amount, source, kind:
   salary/other) — separate table, own `income:` drop prefix (deterministic
   routing), savings rate = income − spend per window on Insights/Dashboard.
   Paycheck PDFs themselves stay Documents/vault territory — the tracked
   number and the sensitive document are different objects.

**Deferred (consciously, not forgotten):**
- Accumulation goals ("save $5k by March") — becomes a view over
  income/spend aggregates once 1–3 exist.
- Subscription intelligence (recurrence detection, renewal alerts, monthly
  burn rollup) — a view + a scheduled check over existing kind=subscription
  rows.
- Points earning/burning over time; statement import.

---

## 2. Stocks — records vs reasoning (two different animals, deliberately)

**His words:** "wanna add say stocks — which ones I bought etc. But also
then, the planning of stocks is different af: talking about specific
companies and the reasoning to invest in said companies."

**Exists today:** InvestmentStore — one static record per holding (name,
symbol, shares, cost_basis, account, purchase_date). No transactions, no
sells, no prices, no P&L. Research-wise: nothing stock-specific — but the
KB + research chat + graph is exactly the "researched choices" machinery
(watches/headphones pattern) waiting to be pointed at companies.

**The two layers, as he framed them:**
- **Records (what I own):** the ledger of buys (and sells?) over time.
- **Reasoning (why I own it):** per-company research — chats, theses,
  arguments for/against — captured as KB notes, graph-linked to the actual
  holding, so the buy decision's full trail is one node-walk from the
  position. This is the store-once thesis applied to investing: research a
  company ONCE with a strong model, store the thesis, retrieve it at every
  review instead of re-researching.

**Open questions (hashing):**
- Transactions vs static holdings: multiple buys of the same ticker, sells,
  realized P&L?
- Prices: auto-fetch (external market API — note: prices are PUBLIC data,
  so this is a privacy-clean exception to local-first, but a new
  external-dependency class — decide deliberately) vs manual snapshots?
- Research home: one folder per company (e.g. `Organisation/Finance/Stocks
  Research/<TICKER>/`) with graph edge thesis ↔ holding? (Recommended.)

**Decisions (2026-10-19):**
- **Prices: auto-fetch, in.** Free sources are sufficient for personal use —
  yfinance (no key, de-facto standard, unofficial) with Stooq EOD / keyed
  free tiers (Finnhub, Alpha Vantage) as fallbacks. End-of-day is enough.
  Each fetch stored as a snapshot row → portfolio-value-over-time history
  falls out for free. Public data = the explicit privacy-clean exception to
  local-first. Graceful offline (stale snapshot shown with its date).

---

## 2b. Bank accounts & card statements — the import lane

**His ask:** "can we also do the same with bank account APIs and credit
card statement pulls?"

**Honest landscape (2026):** live US bank/card feeds all transit an
aggregator (Plaid/Finicity/MX...). Plaid isn't meaningfully free for live
data and routes credentials + every transaction through their cloud —
counter to Quintacle's whole posture. SimpleFIN Bridge (~$1.5/mo) is the
privacy-respecting aggregator if live feeds are ever truly wanted.

**Decision (2026-10-19): statement DROPS, not live APIs.**
- User downloads CSV/OFX (deterministic parse — no model, no third party,
  no credentials, free forever) or PDF (existing vision pipeline) from the
  bank and drops it; transactions land as expense rows with kinds,
  graph-wired, event-grouped per statement.
- Bonus unlock: with statements in, **subscription detection becomes
  deterministic** (same merchant + similar amount recurring ≈ monthly —
  arithmetic, not AI), un-deferring that item.
- Aggregator lane: DEFERRED indefinitely, documented tradeoff; revisit only
  if statement drops prove too much friction in practice.

---

## 3. Retrieval — "the LLM knows exactly what to retrieve and get"

**His words:** "like ChatGPT or Claude — it has a good idea of the question
I'm asking, referencing from docs internally. I want Quintacle to do that.
That's why we had the graph and the folder structure with small heading
notes in each node. Do we have that at least?"

**Verified state (2026-10-19):** the index data EXISTS (`notes_index()` —
title per node; /graph labels everything incl. log rows) but no
question-answering surface uses it. The in-app KB chat brute-force dumps
EVERY note's full content into the prompt (`_kb_context`) — works at 45
notes, dies at 1,000. `neighborhood()`/`reverse_lookup()` exist but are
exposed to no model surface (only the person-appearances page). MCP has
kb_search (crude substring), folders, get, day_recall — a client model can
orchestrate, but has no index tool, no graph walk, no ranked search.

**The plan (hashing):**
- **Tier A — deterministic retrieval loop (the real unlock, no new deps):**
  expose to MCP + chat: (1) `index` — every node in one cheap list (id,
  type, title, one-liner) spanning notes/people/places/events/labeled log
  rows; (2) `graph_neighborhood(node, hops)`; (3) **FTS5** ranked full-text
  search (SQLite built-in). Loop: question → scan index / search → pick ids
  → get exactly those → answer. Small local models can run this loop.
- **Tier B — semantic recall (the 2026-09-30 amendment, still unbuilt):**
  sqlite-vec + a LOCAL embedding model (EmbeddingGemma-class per
  on-device-s25u.md) for fuzzy prose recall. Optional layer on A.

**Open (owner to decide):**
- Opening `chat.py`'s context logic (historically protected; currently open
  for providers only) so the in-app chat does index→select→fetch instead of
  dump-everything.
- Tier A now with B later, or both in one wave?
- Confirm the index spans everything, not just notes. (Recommended: yes.)

**Decisions:**
- (hashing in progress)

---

## 4. (next topic as it comes to mind)

