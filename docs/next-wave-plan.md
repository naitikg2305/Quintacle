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

**BUILT (2026-10-19):** decisions 1–3 are code. Insights tab on the Finance
page (`/finance/insights/{monthly,merchants,movers,subscriptions}` —
deterministic SQL/arithmetic in `core/quintacle_core/nodes/finance/insights.py`,
zero model calls): monthly totals by kind + month-over-month deltas + income/
savings rate, merchant rollups, biggest movers, and recurring-charge detection
(un-deferred via §2b's bonus — cadence arithmetic, surfaced with monthly burn).
Budget lines ride the habit engine exactly as decided: the spend metric now
takes `match_kind` (one of the 7 kinds) and/or whole-word `match_category`
terms over merchant/category/notes via THE matcher (`graph.title_mentioned`),
OR-combined so "creatine + alcohol" is one line; matcher-less spend quotas
keep their original total-spend meaning, and progress carries a time-prorated
target (Dashboard shows even-spend pace). Income: `income_log` (SQLite) +
markdown logs under Organisation/Finance, the deterministic `income:` /
`paycheck:` drop prefix (regex parse, no model), `/logs/income`, and savings
rate = income − spend per month on Insights. Still deferred: accumulation
goals, renewal ALERTS (detection + next-expected date exist; no scheduled
notification), points-over-time. Reference: `docs/reference/finance.md`.

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
- **Transaction ledger: yes.** Buys AND sells per ticker over time; cost
  basis and realized P&L computed, never hand-maintained. The static
  one-record holding becomes a derived view over transactions.
- **Research: yes** — folder per company, thesis ↔ holding graph edges, and
  theses are kept for companies researched-but-passed ("looked, passed,
  here's why" is half the value at re-evaluation).
- **Prices: auto-fetch, in.** Free sources are sufficient for personal use —
  yfinance (no key, de-facto standard, unofficial) with Stooq EOD / keyed
  free tiers (Finnhub, Alpha Vantage) as fallbacks. End-of-day is enough.
  Each fetch stored as a snapshot row → portfolio-value-over-time history
  falls out for free. Public data = the explicit privacy-clean exception to
  local-first. Graceful offline (stale snapshot shown with its date).

**BUILT (2026-10-19)** — all three recorded decisions above are code:
- **Ledger**: `core/quintacle_core/nodes/stocks/` — buy/sell/dividend rows,
  markdown source of truth under `Organisation/Finance/Stocks &
  Investments/transactions/` with a rebuildable `stock_transactions` SQLite
  index (also rebuilt on sync pull). Positions / FIFO cost basis / realized
  P&L on partial sells / dividends computed in `positions.py` on every read —
  nothing aggregated is stored, nothing is model-derived. In-app writes are
  the form's review→Save; MCP got `log_stock_transaction` (ledger entry +
  staged-snapshot undo) and read-only `stock_positions`.
- **Prices**: implementation detail refined at build time — Stooq's plain-
  HTTP CSV is the DEFAULT source (stdlib-only, keeps `core/requirements.txt`
  Termux-safe); yfinance became the *optional* lane (`core/
  stocks-requirements.txt`, lazy import, `QUINTACLE_PRICE_SOURCE=yfinance`)
  rather than the default, since it drags in pandas. Append-only
  `stock_prices` rows (one per symbol+trading day), explicit
  `POST /stocks/prices/refresh` only — no daemons; per-symbol failures
  degrade to the last snapshot shown with its date. Keyed fallbacks
  (Finnhub/Alpha Vantage) not built — add only if Stooq+yfinance both prove
  inadequate in practice.
- **Research**: one KB folder per company under `Organisation/Finance/Stocks
  Research/<TICKER>/`, thesis note with status owned/watching/passed
  (passed theses kept and marked, per the decision), `thesis_for` edge to a
  new `holding:<TICKER>` graph id — ticker-keyed so it survives index
  rebuilds and exists for never-bought companies.
- Frontend: `/stocks` page (positions table, snapshot date + refresh,
  ledger, research links). The static InvestmentStore page stays as-is for
  now — retiring it in favor of the derived view is a merge-time cleanup.
  Detail: `docs/reference/stocks.md`.

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

**BUILT (2026-10-19):** the statement-drop lane is live. CSV/OFX/QFX files
dropped on the Drop page route deterministically by extension (no model);
CSV goes through a stdlib parser with a header-guessed, user-correctable
column mapping (re-parse in the review card), OFX/QFX through a hand-rolled
reader for the minimal SGML/XML `<STMTTRN>` subset — no new dependency in
`core/requirements.txt`. PDF/photo statements use the explicit `statement:`
prefix and the existing cloud vision lane (same pattern as receipt
extraction; the model only transcribes rows, code validates every one).
Every path lands in the SAME review gate: per-row keep/edit before Save,
rows already in the ledger (same date+amount+merchant) flagged and unchecked
by default, re-checked again at write time (`/finance/statement/import`),
and the written rows event-grouped per statement. Subscription detection
un-deferred as §1 notes. Aggregators remain out, as decided.

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

**Decisions (2026-10-19):**
1. **Tier A AND Tier B in one wave** — owner: "I want B as well; that's why
   we have the graph for retrieval." The full triple-hybrid retrieval
   system: **graph** for relational questions (walks no text search can do),
   **FTS5** for exact-word ranked search, **vectors** (sqlite-vec + a LOCAL
   embedding model, EmbeddingGemma-class per on-device-s25u.md) for
   meaning-match when wording differs. One unified surface over all three.
2. **chat.py context logic: opened by the owner for this build** — the
   dump-everything `_kb_context` is replaced by the index→select→fetch loop.
   (KB chat's prompting/session machinery otherwise still protected.)
3. **The index spans everything** — notes, people, places, events,
   experiences, journal days, labeled log rows.
4. **`summary` one-liner per node** — written once at ingest by the local
   model (reviewable, frontmatter), deterministic fallback title+first-line,
   backfill pass for existing nodes. The owner's original "small heading
   notes in each node", made real. Embeddings computed at ingest too (and
   backfilled) — capture-time work, free retrieval forever.

**BUILT 2026-10-19** — the retrieval engine half of this section is real
code: `core/quintacle_core/retrieval.py` (nodes_index + FTS5 + optional
sqlite-vec/`QUINTACLE_EMBED_MODEL` lane, RRF fusion, 1-hop graph expansion),
hooks on every write path (REST + MCP, failure-isolated), summaries
(structured = computed in code; prose = local model with deterministic
fallback — one deviation from decision 4's sketch: the one-liner lives in
the `nodes_index` SQLite row, not note frontmatter, keeping files untouched),
`python -m quintacle_core.retrieval_backfill`, `GET /retrieve`, MCP
`search_index` (tool 18). Transcripts' `conversations/` prefix is already
excluded from the default index per §4. Reference:
`docs/reference/retrieval.md`. NOT built here (next wave): chat.py's
index→select→fetch loop over this engine (decision 2 stays pending).

**BUILT 2026-10-19 (chat-context wave)** — decision 2 is now code: chat.py's
`_kb_context` is the index→select→fetch loop over this engine.
`retrieve(latest user message, k=8)` selects; full content is fetched ONLY
for the selected prose hits (notes/places/people/journal days, per-hit char
cap); structured rows enter as their already-computed one-line summaries
(finished numbers — the model never re-derives them); each hit carries its
1-hop neighbor labels as plain context lines (the chat loop is single-shot,
no tool turns — a wanted neighbor is something the model asks the user to
bring up). Deterministic assembly in RRF order under a 24k-char budget.
Retrieval uninitialized/empty/erroring falls back to the ORIGINAL
dump-everything context (kept as `_kb_context_everything`) — degraded, never
a 500. The folder-only scoped chat is deliberately unchanged (its "can't see
what it can't cite" contract would break under global retrieval). Reference:
`docs/reference/chat-context.md`.

---

## 4. Conversational ideology — "continue any topic like a human"

**The frame (agreed 2026-10-19):** conversations are working memory, the KB
is long-term memory, and consolidation is the bridge. A topic is a node
(e.g. a schemes.md-style plan note). Opening a chat about a topic hydrates
from retrieval (§3) — the node's current state plus its graph neighborhood
— not from any saved transcript. The manual prototype is this very doc:
yap in chat, and only what's worth keeping gets pushed into the pad and
committed.

**Decisions (2026-10-19):**
- **Chat is read-only by default.** Hydrate via retrieval, yap freely,
  close — nothing written anywhere. Folding is the exception, not the rule.
- **Consolidation is explicit only.** No session-end or idle-timeout
  auto-fold. The owner says "record that" (the model may *offer* when it
  notices a decision landed); the write goes through the normal gated path.
- **Folded shape = the pad pattern:** dated appends to the topic's note
  (decisions with dates, open questions, superseded items get correction
  notes) — never rewriting history, per the docs-are-decision-logs
  principle.
- **Transcripts: second-tier archive** (amended same day — was "fully
  ephemeral"; "only preserve what's necessary" still governs the *index*).
  On close, the raw transcript drops verbatim into
  `conversations/<topic>/<date>.md` with a `transcript_of` edge — a file
  write, zero model calls. **Excluded from the default retrieval index**;
  reachable only when the owner explicitly asks to dive deeper / refer to
  transcripts (own FTS table, scoped to the topic). Anything worth
  promoting goes through "record that" into the real note.
- **The chat page itself stays fresh.** No accumulating thread list, no
  session log in the UI: "talk yap add and delete — always keep the chat
  page fresh and neat." Continuity comes from the KB via retrieval, not
  from reopening old chats.

**Status (2026-10-19): transcript-archive + fresh-page bullets BUILT.**
`core/quintacle_core/nodes/kb/transcripts.py` — archive-on-close writes the
verbatim transcript to `<data_dir>/conversations/<topic-slug>/<stamp>.md`
(outside `kb/`, invisible to every KB/MCP/model surface; zero model calls),
with its own FTS5 index (`conversations/transcripts.db`) behind the explicit
`GET /transcripts/search` lane and a `transcript_of` edge when the subject
confidently names a real node. Chat page: thread list removed, "New chat"
archives-then-clears, per-chat "Don't keep" toggle (default keep). The
optional local-model nicer-slug was deliberately skipped (zero-model hot
path; deterministic slug is mandatory anyway). Hydration-from-retrieval and
explicit "record that" folding belong to §3's engine / the chat-context
wave, not built here. Details: `docs/reference/transcripts.md`.

**BUILT 2026-10-19 (chat-context wave)** — the remaining §4 bullets are code:

- **Topic hydration**: a chat continued ON a note (the existing "continue in
  chat" affordance now sends folder+slug) prepends that node's full current
  content + fields + its graph-neighborhood labels, then retrieval hits for
  the latest question — continuity from the KB, never from a transcript.
- **"Record that", explicit only**: a chat-header button. `POST
  /kb/record-that` distills the conversation into a DATED append proposal
  (date computed in code via clock.today — Eastern; the model writes only
  the bullets, local-first via parse_structured's normal routing) and writes
  NOTHING; the review panel lets the owner edit folder/note/text (folder is
  the scoped topic's, or model-proposed + user-picked when unscoped); only
  `POST /kb/record-that/save` writes — append-only onto the note's existing
  body (pad pattern, history never rewritten), through the existing write
  machinery (store.write + graph sync + retrieval index). No auto-fold
  anywhere; the model-may-offer nicety was deliberately skipped (prompting
  stays conservative this wave).
- **Transcripts stay second-tier**: the deep-search lane is an explicit
  button on the chat input (uses the typed text as the query, zero model
  calls) surfacing `GET /transcripts/search` hits (topic, date, snippet) as
  a deterministic message in the log — in context for the next turn, never
  automatic.

## 5. Generic pages (the car vision) — ai-managed-pages, now cheap

**State:** every prerequisite built (open fields dict, Phase E views, graph,
local structured-parse dispatch, perception photos); the feature itself —
field extraction at ingest, per-folder field-name canonicalization, cover
photo header, "what's due" + health bars — in no wave yet. Local models
make extraction ~free; review gate makes it safe.

**Decisions (2026-10-19):**
- **Extraction mode: attempt on every drop, conservatively.** The local
  model tries fields on everything, but "not going crazy for no reason" —
  emit only values the text explicitly states (a number, a date, a named
  quantity), never inferred or padded fields; silence is the correct output
  for prose with nothing structured in it. Review gate prunes the rest.
- **Born generic from day one.** No Car-specific code anywhere — any folder
  can grow fields; the Car is just the first folder it gets used on, not a
  hand-coded pilot. Per-folder field-name canonicalization (the model sees
  the folder's existing field names and reuses them) is what keeps a
  generic system coherent.
- Intervals/thresholds ("oil every 5k mi") stated once by the owner as
  fields; what's-due is then arithmetic, not model judgment.

## 6. Backup

**Decision (2026-10-19): manual pendrive lane, scripted + encrypted.** One
command (`backup-to-drive`) writing an encrypted snapshot of ~/.quintacle
(+ ~/work-logs) to whatever drive is mounted — ten seconds, owner-run.
Tradeoffs stated and accepted: habit-dependent, same-location risk,
offsite (restic→S3/B2 per self-hosting.md) consciously deferred.

**BUILT 2026-10-19:** `scripts/backup-to-drive` — tar+openssl AES-256
(PBKDF2, prompted passphrase), snapshots `~/.quintacle` + `~/work-logs`
to the mounted drive (auto-detects a single /run/media mount), with a
`restore` mode; round-trip + wrong-passphrase tested in a sandbox.

## 7. Dispositions (2026-10-19)

- **Proactivity** (triggers/notifications/routines engine): owner doesn't
  care for now — consciously OUT of plan.
- **Voice** (the Ideal's mic): real but easy — deferred to the post-testing
  UI-tweaks pass, likely local Whisper-class STT.
- **Work logs live in Quintacle now** — all ~/work-logs days backfilled via
  MCP into Nerd Folder/Projects/Quintacle Work Logs (2026-10-19); every
  future session entry mirrors in as standard practice (file remains too,
  per the global rule).

---

## 8. Chat–drop parity, versioned goals, the goals calendar (2026-10-20)

First prod-testing session surfaced these; all decided same day:

- **Chat scratchpad = full drop parity.** The scratchpad's "Sort with AI"
  stops being KB-note-only and routes through THE SAME `/drop` text lane —
  every type drop handles, same review gate, same commit endpoints.
  Chat messages themselves are never scanned ("only the scratchpad").
  - **BUILT 2026-10-20** (worktree agent, scratchpad-parity lane). The Drop
    page's review orchestration is extracted into shared
    `frontend/components/DropReview.tsx` (`useParsedEntries()` hook +
    `<EntryReviewList>`, moved verbatim — both generic over the whole
    ParsedEntry union, so new drop types are additive) and
    `lib/entries.ts#commitTextEntries` (the text-only commit loop: per-entry
    `commitEntry` + `graphIdFor` + `linkBatchAsEvent`; Drop's own saveAll
    untouched). Untargeted scratchpad "Sort with AI" calls `proposeDrop`
    (text-only) with a reference-date input, renders the same review cards
    in the scratchpad column, and "Save N entries" commits through the same
    endpoints with same-event linking; provider chip + step-back "Redo with
    cloud ↻" copied from Drop. Kept as-is by decision: target-note
    Update-with-AI (sortKBEntry merge), the meal/outfit/grooming/workout
    suggesters, record-that, and generate-image (stays exclusively on the
    sortKBEntry → push() lane, which also still serves a pending generated
    image without a target so push() can attach it). A single kb_entry
    proposal from /drop renders as a normal review card; the old KB
    suggestion panel serves the target-note path only.
- **Stock ledger from both surfaces**: `stock:` prefix (and cheap natural
  parse) proposes a real ledger transaction (review → POST
  /stocks/transactions); the old static investment-entry lane retires.
- **Budget lines / habits / goals set by drop or chat** (`budget:`,
  `habit:`, `goal:` + classification): "eating out $200/month" parses into
  the habit shape, review-gated.
- **Versioned habits.** Habits/budget lines become effective-dated
  versions: an edit takes effect NEXT week (Monday-anchored; current week
  finishes under the old target); past weeks are always judged against the
  version in force then; delete = end-date, history preserved.
- **Goals calendar (third calendar view).** Habits render like recurring
  weekly meetings: grid colored met/missed/in-progress, week click drills
  into per-habit target-in-force vs actual vs pace. All arithmetic in code.
- **The separate Habits page retires** — "we don't even need the goals page
  separately... it reduces a page." Define/update via drop/chat; track via
  the calendar; small edit/end affordances live in the week drill-in.

## 9. (next topic as it comes to mind)

