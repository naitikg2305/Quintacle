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
  - **BUILT 2026-10-20** (drop-types lane): `stock:`/`invest:` prefixes now
    map to a `stock_transaction` proposal (`nodes/stocks/llm.py`'s
    `structure_stock_transaction` via llm_dispatch — dividend = TOTAL cash
    in `price`, qty 0, matching store.py's row semantics); unprefixed text
    passes `drop_router.looks_like_stock_transaction` (deterministic,
    conservative: trade verb AND share/stock word or `TICKER at/@ price`)
    before any model call, and routes to the same lane — never into
    parse_journal_dump's union (schema-size limit). Frontend: EntryCard
    stock case, commit via `logStockTransaction`, graph id `stock_tx:<id>`.
    The `invest:` prefix folded in here; the /drop `investment_entry` branch
    and api.py's `structure_investment` import are gone. DEFERRED cleanup:
    `InvestmentStore`, `finance/llm.py`'s `structure_investment`, the
    `/investments` endpoints, and the investments page still exist.
- **Budget lines / habits / goals set by drop or chat** (`budget:`,
  `habit:`, `goal:` + classification): "eating out $200/month" parses into
  the habit shape, review-gated.
  - **BUILT 2026-10-20** (drop-types lane): `habit:`/`goal:`/`budget:`
    prefixes → a `habit_entry` proposal (`nodes/logs/habit_llm.py`'s
    `structure_habit`, prompt pinned to the exact shapes the habits page's
    submit() produced: activity_hours/at_least/hrs, food_kcal/at_most/kcal,
    spend/at_most/$ with kind+match-terms, plus the exercise_days count
    metric). Prefix-only — no natural-classification gate; a goal is a
    deliberate statement. Review commits through POST /logs/habits (upsert
    by name per the versioned-habits lane, so the same drop creates AND
    updates). Frontend: EntryCard habit case mirroring the habits-page form
    controls; "Goal / budget" manual button on the drop page.
- **Versioned habits.** Habits/budget lines become effective-dated
  versions: an edit takes effect NEXT week (Monday-anchored; current week
  finishes under the old target); past weeks are always judged against the
  version in force then; delete = end-date, history preserved.

  **BUILT (2026-10-20):** `habits` is identity (id, name, ended_on) +
  `habit_versions` effective-dated by period start; migration backfills one
  '0001-01-01' version per legacy row (pre-versioning weeks judged against
  migration-time targets — the only honest reading). POST /logs/habits
  upserts by name (new = counts this period; existing = version effective at
  the NEXT boundary of the new version's own period — so a week→month edit
  activates on the 1st); PATCH appends a version, DELETE end-dates at the
  current period's last day. Progress/history judge every window by the
  version in force at its start; history steps per era across period
  changes. Bonus while in here: the `exercise_days` metric (distinct gym
  days — "gym 4x/week"). Reference: `docs/reference/habits-versioning.md`.

- **Goals calendar (third calendar view).** Habits render like recurring
  weekly meetings: grid colored met/missed/in-progress, week click drills
  into per-habit target-in-force vs actual vs pace. All arithmetic in code.

  **BUILT (2026-10-20):** the calendar's third Segmented tab, **Habits** —
  one row per Monday-anchored week overlapping the visible month, a status
  chip per habit (word/icon + tone, never color alone); week click opens the
  usual Panel/BottomSheet with target-in-force (its effective date shown
  when it isn't the current version), actual, met/missed, and a pace line
  for the current week. Fed by one `GET /logs/habits/ledger?weeks=N`
  (`quotas.weekly_ledger`) — day-period habits aggregate to days_met/
  days_total per week; the client only formats. The Habits page gained the
  minimal edit/end/pending affordances in the meantime (per the
  page-retires decision below, not gold-plated).
- **The separate Habits page retires** — "we don't even need the goals page
  separately... it reduces a page." Define/update via drop/chat; track via
  the calendar; small edit/end affordances live in the week drill-in.

## 9. Chat absorbs drop — the Seamless face arrives early (2026-10-20)

**Direction agreed** (same idea as seamless-mode.md's Drop+chat single
surface, reached independently during testing): once §8's scratchpad
parity lands, chat IS the drop lane for text — the remaining gap is files.
Follow-up wave moves drop's file affordances onto the scratchpad
(attachments through the same multipart /drop call, EXIF/vision
classification, unknown-faces panel, "Still going" lecture sessions,
statement review), after which **the drop page retires** — one place to
retrieve and drop everything, and the natural mouth for the voice plan.

**Gate (owner's own sequencing):** test drop's file flows for real first
(lecture session, faces, statements) — relocate them knowing what they
feel like, not blind. Fire after §8 merges + that test pass.

**BUILT (2026-10-20, worktree agent):** chat IS the drop surface now; the
Drop page retired — the second page retired today, after Habits. Zero
backend changes (the `/drop` ENDPOINT is the engine and stays; only the
surface moved).

- **Scratchpad = full file lane.** The Drop page's file machinery is
  extracted to `frontend/components/DropAttachments.tsx`
  (`useDropAttachments()` + `<AttachmentTray>`: drag-drop, choose-file,
  scribble pad, image/video previews, unlimited extra attachments) and
  lives under the scratchpad. Untargeted "Sort with AI" sends text + files
  through the SAME multipart `proposeDrop` (file/file2 semantics, keep-as-is
  checkbox, statement CSV/OFX raw_text re-attach for the correction card);
  "Redo with cloud" snapshots the ORIGINAL text+files. Saving uses Drop's
  FULL semantics, now shared: `lib/entries.ts#commitDropEntries` (assets on
  asset-carrying types, statement summary, single-note session detection,
  unknown-faces queueing, same-event linking — extracted verbatim from
  Drop's saveAll); `commitTextEntries` stays as a thin text-only wrapper.
  Journal append rode along too (auto-suggest ≥200 chars, derived — not an
  effect; "Save to journal only" button).
- **Faces + "Still going" moved** into `components/UnknownFacesPanel.tsx`
  and `components/StillGoingPanel.tsx` (verbatim logic, self-contained
  state), rendered in the scratchpad column after saves.
- **Conversation → drop bridges:** a photo/PDF on a chat MESSAGE gets
  "→ add to scratchpad" (ChatLog rebuilds the File from its base64 block);
  a GENERATED image gets "→ add to drop attachments" alongside its existing
  push() lane. Both land in the pending attachments and flow through /drop.
- **Manual grid** (all 23 types) extracted to
  `components/ManualAddGrid.tsx`, collapsible on the scratchpad.
- **Retirement:** Drop removed from nav + home tiles (Chat tile covers it;
  phone bottom bar back to 5 slots); finance's statement link points at
  chat; `/kb/drop` is a client-side redirect stub to `/kb` (client-side so
  the Capacitor static export works — no server to serve a 307). All chat
  behaviors kept: retrieval, escalate, record-that, transcripts
  (archive-on-close), don't-keep, suggesters, target-note lane,
  generate-image, phone pane switcher.


## 10. The final map, Me, and time (2026-10-20, all ordered same day)

**The file map (decided after the PARA talk — his structure, three upgrades):**
roots = Me · Daily Log · Personal Development · Organisation · Career ·
Projects · Knowledge (ex-Nerd Folder) · Fun (new) · People. Planning,
Multimedia, Sports & Activities retire. Career = nouns (one folder per
employer); Projects = verbs (one per endeavor, `idea → active → archived`
as a FIELD — archive is a status, never a file move, because moves break
note ids/edges). Travel splits: planning a trip = a Project; visited
places auto-file `Fun/Travel/<City>/<Kind>/` (code home moved off
Planning/Travel); idea lists = `Fun/Day Trips`/`Things To Do`. Lectures
live by topic (`Knowledge/Lectures`) with `course:`/`semester:` fields
carrying the endeavor dimension.

**Ordered:**
- **Seed** charters incl. entity hubs `Career/Minfy`, `Projects/Quintacle`, `Me/`.
- **Me/ lane**: quick-reference self — curated facts written there (injuries,
  dating, friends, preferences); live numbers (PRs, income, savings rate)
  COMPUTED from SQL at ask-time, never copied; chat always hydrates it.
  - *BUILT 2026-10-20 (chat half)*: `me_context()` in
    `core/quintacle_core/nodes/kb/day_context.py` — every note in the KB
    folder `Me` (capped ~3,000 chars) + live SQL facts computed at ask-time,
    never stored: strength PRs (max weight per exercise via `json_each` over
    `exercise_sets.sets_json`), this month's income/spend totals + savings
    rate (`income_log`/`expense_log` SUMs), latest `body_stats` row per
    metric — all finished one-liners with as-of dates. Prepended to EVERY
    chat context (all providers, all scopes) under `## About the user` with
    a never-recalculate instruction; empty store omits sections silently.
- **Work logs**: all days, one home — `Daily Log/Work Logs` — edges to every
  project/employer mentioned ("what did I do for Minfy this year" = walk edges).
  - **BUILT 2026-10-20** (worktree agent, work-log lane):
    `core/quintacle_core/nodes/logs/worklog.py`. `parse_work_log()` is pure
    and deterministic (zero model calls), grounded against the real
    ~/work-logs variance: `## Session N` blocks (or whole-file when
    unnumbered), header times with `~`/en-dash/hyphen/`→` and past-midnight
    ranges, Where → repos + project. `import_work_log()` writes the verbatim
    note (`Work log - YYYY-MM-DD`, fields `{date, kind: work-log}`,
    overwrite-by-title) through KBStore + the same graph-sync +
    retrieval-index calls as the KB create path; entity edges are
    deterministic — every `Career/*` / `Projects/*` note title mentioned in
    the log (`graph.title_mentioned`) becomes a materialized link. Two
    doors: `POST /logs/worklog/import {date, content}` and the MCP
    `import_work_log(for_date, content)` tool (one staged-undo ledger entry
    per import — note, rows, files, edges undo together).
- **Auto productivity rows**: one activity one-liner per work-log session,
  deterministic (hours from the Session header, description from Summary),
  deduped vs manual rows, backfilled at import.
  - **BUILT 2026-10-20** (same lane): per session with a computable
    start–end, ONE `activity_log` row — category `productivity`, hours
    computed in code (`14:30–18:45` → 4.25; unparseable side → no row,
    never guessed), description = Summary first sentence prefixed with the
    `…/code/<name>` project when Where implies one ("Quintacle: fired five
    build waves"). Dedupe is delete-by-tag, never fuzzy: rows carry
    `source: worklog-auto` in markdown frontmatter AND the new
    `activity_log.source` column (migration; rebuild carries it), so a
    re-import deletes exactly its own prior rows — manual rows (`source=''`)
    are untouchable by construction. Rows index into retrieval
    (`safe_index_log_row`). 18 tests in `core/tests/test_worklog.py`.
- **Time/date always**: chat knows now (ET); date words in questions resolve
  IN CODE to that day's bundle (journal, rows, photo who-with lines, people)
  hydrated into context.
  - *BUILT 2026-10-20*: `_system_text` now opens with a deterministic
    `Now: Tuesday 2026-10-20, 7:45 PM (America/New_York).` line (clock.py,
    every provider — escalation carries it identically, and it's present
    even with the KB toggled off). `detect_dates(text, today)` in
    day_context.py resolves explicit ("April 14", "4/14", "2026-04-14",
    "oct 7th", "14th of April") and relative ("today", "yesterday", "last
    tuesday", "two weeks ago", "last week" → that Mon–Sun) forms, year
    inference = most recent past occurrence; `day_bundle(d)` assembles the
    day's journal + log-row one-liners (`retrieval.log_row_title_and_summary`)
    + todos + events/people/place edge labels, capped ~6,000 chars. Max 3
    dates hydrate per turn as `## <date> — that day's record`, alongside
    normal retrieval (unscoped + note-scoped chats; the folder-only scope
    keeps its can't-cite-outside contract). Zero model calls anywhere.
- **Home-page regroup**: Me · Life (Daily Log, PD, Organisation, People) ·
  Productivity (Career, Projects, Knowledge) · Fun.
  - **BUILT 2026-10-20** (worktree agent, home-regroup lane; `app/page.tsx`
    + `components/AppShell.tsx` only — presentation, no routes changed).
    Home: greeting/stats kept; **Me** = two small pills at top (Me →
    browse-at-`Me/`, Profile); Chat stays above the clusters as the big
    primary tile (2-of-3 cols, Browse beside it); then three Panels —
    **Life** (Journal, Calendar, Todos, Dashboard, Wardrobe, Finance, Home,
    Documents, People), **Productivity** (Career/Projects/Knowledge as
    browse-at-root tiles, Stocks, Goals calendar → `/day` Habits tab),
    **Fun** (Travel, Gallery). Folder tiles reuse the existing
    `/kb/browse?path=` surface — no new pages. Nav mirrored by splitting
    the sidebar's Life group: Core · Life · Productivity (Stocks) · Fun
    (Travel, Gallery) · Tools; phone bottom tabs untouched, the More sheet
    flattens all four groups. Phone: tile grids are `grid-cols-2` (3 cols
    only ≥lg), blurbs hide below `sm`, hero row stacks to one column.
- **Clickable deep links**: chat answers link into notes and their assets.
  - **BUILT 2026-10-20** (chat-frontend lane): `ChatLog.tsx` renders markdown
    links through one `MarkdownLink` component (react-markdown `components`
    override — no raw HTML, no new deps). Root-relative hrefs matching a REAL
    app page (the full `app/**/page.tsx` set, `/vault` deliberately excluded)
    → Next `<Link>` client-side nav; the note shape is
    `/kb/browse?path=<folder>&open=<slug>` (what Browse already reads).
    Backend asset hrefs (`/kb/asset`, `/documents/asset`, `/wardrobe/asset`,
    `/wardrobe/outfits/asset`, `/grooming/asset`, `/home/asset`) → plain
    anchor prefixed with `API_BASE` at render time (Capacitor isn't
    same-origin), target `_blank`. External http(s) → new tab. Everything
    else (javascript:, data:, `//host`, unknown routes) renders as text.
    Applies everywhere ChatLog renders (kb chat, folder chat, ReadOnlyChat).
  - *BUILT 2026-10-20 (system-text half)*: `_LINK_RULES` in chat.py instructs
    the model to emit the app's REAL routes as root-relative markdown links —
    notes: `[Title](/kb/browse?path=<folder>&open=<slug>)` (the browse page's
    own deep-link params), files: `[name](/kb/asset?folder=<folder>&path=<asset
    path>)` (lib/api.ts `kbAssetUrl` shape) — only for ids/paths already in
    context (`note:<folder>/<slug>` carries folder/slug). The frontend render
    half (markdown link → in-app navigation) is the other agent's lane.
- **Add-to-scratchpad on chat TEXT output**: drafted CSVs/itineraries become
  files in the tray — one funnel (images got the button in §9).
  - **BUILT 2026-10-20** (chat-frontend lane): each assistant message gets
    "→ attach as file" beside §9's image button, reusing the SAME
    `onAddAttachmentToDrop` → `addFileToDrop` bridge (tray + pane flip to
    scratch, zero new plumbing in `app/kb/page.tsx`). Whole message →
    `chat-draft.md`; a message that IS one fenced block with a known text
    format (csv/tsv/json/yaml/… map in ChatLog's `LANG_EXT`) → only the
    block's contents as `chat-draft.<ext>`; mixed prose+block messages also
    get a per-block "→ attach .csv block" button (raw-markdown parse — the
    highlighted render tree is never scraped).

**Dumped for now:** STL-grade artifact generation (future agentic-tool wave).

## 11. The seamless agent (2026-10-20, planned — not yet fired)

**The ask:** "I talk to my seamless agent, it does stuff, and I can keep
talking like it never leaves even after navigating me to a certain page."

**Design (agreed):**
- **Resident companion shell**: the conversation lifts out of /kb into the
  AppShell layer — a persistent dock above the router that survives all
  navigation; /kb stays as the full-screen view of the SAME session.
  `navigate(route)` becomes a tool; the agent is told what page the user is
  on. §4 semantics unchanged: alive while in use, archives on close, no
  thread list.
- **Loop runner**: backend agent endpoint — model + tool schemas + capped
  loop (~6 turns); Ollama tool-calling locally, Bedrock/Anthropic tool use
  on escalation (same runner, provider-swapped mid-conversation per the
  context-transfer principle). Every call code-validated before execution;
  every write through the MCP-grade WriteSession (one ledger entry, staged
  undo). Local handles short chains; hard/long chains = user-chosen cloud.
- **Action-chip UX**: each tool action renders in the conversation as a
  chip — "✓ lamb bowl logged (undo)" — wired to its ledger id.
- **Two-class tool contract (the principled line):**
  - *Internal + undoable* (logs, notes, todos, navigation): auto-commit +
    undo chip. The ledger machinery earns auto-commit.
  - *Outward + irreversible* (call, SMS, email — anything leaving the
    machine): agent PREPARES (drafts, resolves the number via the People
    graph — registries, never guessed), then one-tap confirm. The only
    place propose→review survives in seamless mode: the blast radius you
    can't take back.
- **Tool tiers**: v1 internal (retrieve, read note, day bundle, structured
  writes, record-append, navigate, positions, habit status; NEVER vault or
  bulk deletes; statement import keeps its review card) → v2 device layer
  (phone: termux-api — telephony-call/sms-send/contact-list/notification,
  straight from the Termux backend; desktop: KDE Connect bridge + xdg-open)
  → v3 accounts (SMTP send with creds in the Vault — its first real
  consumer; CalDAV calendar; maybe IMAP read) → vN external MCP servers
  (the tool layer doubles as an MCP client). Entire chain can run with
  zero external AI — local Jarvis, literally.

**Open (owner to answer before firing):** dock shape (slim bottom bar —
voice-ready — vs side rail); write contract (pure auto-commit+undo vs a
soft 3-second confirm tier for new notes); sequencing (build dark behind a
toggle now vs after the two-week real-use test, which the owner's own
seamless-mode.md sequencing prefers).

## 12. Serious vs unserious chat, and the soft record (2026-10-27, decided — not yet built)

**Why this amends §4:** §4 made transcripts a second-tier archive that only
an explicit button could search. In use, that loses the "we talked about
this last night" feel that GPT/Claude have. Owner's fix keeps the KB clean:
two layers with different trust, never merged automatically.

**Decisions:**
- **Every chat is recorded** as a transcript (the `conversations/` store
  already does this by default), read as ONE linear, dated timeline — not a
  thread list. The chat page still stays fresh; continuity comes from the
  timeline, not reopened chats.
- **Unserious mode (default)**: the assistant layer. Answers draw on the
  timeline (recent chats + a soft record of straight facts extracted per
  conversation) AND the knowledge base. Assistant-like, knows the user.
- **Serious mode**: strict. Knowledge base + graph + notes ONLY. No
  timeline, no soft record, says "not in your notes" rather than guessing.
  Intended use: switch to serious when unserious hallucinates or when the
  question is knowledge-related.
- **Mode switching is deterministic, not model judgment**: phrase detection
  ("serious mode", "just from my notes", "KB only", …) plus a visible chip
  showing the current mode. Sticky until changed.
- **Soft record**: after each chat a model extracts only straight facts
  into a single running log. Every soft fact carries its date and a link to
  the transcript it came from (checkable, or it is slop). The log is a page
  the owner can read and delete from. It NEVER becomes KB knowledge without
  an explicit Record that.
- **Don't keep** remains the off switch (per-chat, plus an incognito start):
  such a chat is never written, never read for facts.
- **Source labels in answers**: KB facts stated plainly; timeline/soft-record
  material flagged ("we talked about this on the 26th — not in your notes").
- **Transcripts stay off the graph view** (verified: /graph drops edges to
  nodes it doesn't draw). To check at build time: the edges table still holds
  `transcript_of`, so chat context "Connected:" lines may list a transcript.
- **Dates on everything** (retrieved notes carry their date into the model's
  context) and a human recall tone in the chat persona — small prompt and
  formatting change, no new storage.
- **Storage is not a constraint**: roughly 25–110 MB/year of text plus a
  similar FTS index, negligible next to photos.

**BUILT 2026-10-27 (frontend half):** `components/ModeChip.tsx` — chip reads
"Mode: Casual" / "Mode: Serious" (text always, accent border when serious),
click toggles; `chatMode` is sticky page state sent on every `/kb/chat`
(including escalations) and replaced by `response.mode` (missing = keep
current, so older backends work). `mode_switched` shows a transient inline
notice ("Switched to serious mode — answering from your notes only"), kept
out of `chatLog` so it is never sent or archived. Hint under the input:
"Serious: answers only from your knowledge base" / "Casual: draws on your
notes and recent chats". Incognito reuses `keepTranscript` (button now reads
"Incognito" when off; banner "Incognito — this chat won't be kept or learned
from."); `archiveTranscript` passes `incognito: true` in that case. New page
`/soft-record` ("Chat memory", nav under Life, linked from the chat footer,
in ChatLog `APP_ROUTES`) lists `GET /soft-record` with optimistic delete and
rollback + error banner on failure. Not yet done: surfacing `soft_facts_added`.
### BUILT 2026-10-27 — §12 backend (worktree agent, branch `worktree-agent-a8ab428a8c609faed` off `redone-UI` `f57ac31`; frontend half is a parallel agent)

- **Modes** in `nodes/kb/chat.py`: `detect_mode_phrase()` (pure, deterministic,
  whole-phrase, case-insensitive; later phrase wins) + `resolve_mode()`.
  `POST /kb/chat` takes `mode` (default `unserious`), returns `mode` (effective)
  and `mode_switched`. Serious = KB + graph + notes only + a strict "that's not
  in your notes" rule; unserious = today's context plus the headed
  `## From recent chats (not recorded in your notes)` block (30-day soft facts
  <=2,000 chars; <=3 FTS snippets from the last 14 days <=2,500 chars) with an
  instruction to flag it "from a past chat, not in your notes" and offer
  Record that. Block shrinks first under the 24k budget; any failure omits it.
  Folder-only scope never gets the block (its cite-only contract).
- **Dates + persona**: retrieved prose notes carry `— updated YYYY-MM-DD` (ET,
  from the index `updated_at`, now also returned by `retrieve()`); the topic
  header too. Unserious intro rewritten to a "was there for it" tone.
- **Soft record** (`nodes/kb/soft_record.py`): `conversations/soft_record.db`
  (outside `kb/`, off the graph and the main index), `GET /soft-record`,
  `DELETE /soft-record/{id}`. One local-first `parse_structured` call
  (`provider="local"`) over the USER's turns, run as a FastAPI background task
  after a kept archive; dedup on (date, text). `soft_facts_added` is always 0 in
  the archive response (extraction is deferred); `soft_facts_pending` says one
  was queued. `incognito` is an alias of `keep=false` — neither is archived nor
  read for facts. `QUINTACLE_SOFT_RECORD_PROVIDER=off` disables extraction.
- **Connected-lines leak (the open check) CONFIRMED and fixed**: `transcript_of`
  edges did surface `transcript:` ids in `Connected:` lines and `/retrieve`
  neighbors. Filtered in `retrieval._neighbors` (plus `_neighbor_line`);
  `/graph` regression-tested to carry no transcript nodes/edges.
- Tests: `tests/test_chat_modes.py` (63 new); suite 597 passed / 0 skipped.
  Deferred: the linear timeline VIEW page (frontend), a "Record that" shortcut
  from a soft fact, and any retention/pruning of old soft facts.

### CORRECTION 2026-10-27 — live testing showed local serious mode hallucinating; deterministic fixes (worktree agent, off `redone-UI` `69989ea`)

Running the real pipeline in a sandbox with local qwen3:8b: asked "what's been
going on with my throat lately?" in SERIOUS mode with nothing relevant in the
KB, the assembled context was correct (strict rule present, no chat material,
"(nothing in the knowledge base matched this question)") and the model STILL
invented a "Sore Throat Note", ibuprofen, a doctor's appointment and two links
to notes that don't exist. Serious mode is the user's escape hatch from
hallucination, so a prompt-wording fix was rejected — the fixes are code:

- **Zero-match short-circuit** (`chat._build_context` returns
  `nothing_to_ground`; `run_kb_chat` checks it). In serious mode, when the KB
  is on, the scope is not folder-only, there is no topic hydration, retrieval
  RAN and matched nothing, no day bundle hydrated, AND the Me block is empty,
  the model is never called: the reply is the fixed `SERIOUS_NOTHING_REPLY`
  ("That's not in your notes." + one line suggesting casual mode or recording
  it), same `{reply, mode, mode_switched}` shape. Me-only still calls the model
  (a question about the user's own numbers may be answerable from it). The
  retrieval-down legacy fallback counts as material (never short-circuits);
  `use_kb=false` is out of scope. Same rule for every provider, so escalating
  gets the identical deterministic answer.
- **Link post-validation** (`chat.validate_reply_links`, every reply, every mode
  and provider): markdown links/images to `/kb/browse?path=&open=` and
  `/kb/asset?folder=&path=` are checked in code (KBStore.read with its slugify
  normalization after URL-decoding; `KBStore.asset_exists` through the existing
  clamp). Missing -> plain text + " (not found in your notes)". External and
  other links untouched.
- **Soft facts anchor relative dates** (`soft_record.annotate_fact_date`, at
  store time against the CHAT's date, not clock.today()): "since Tuesday" from
  a Tuesday 2026-10-27 chat was later read as 2026-10-27. Now stored as
  "Throat soreness since Tuesday (2026-10-20)". Conservative: only when exactly
  one date resolves; future cues, existing ISO dates and explicit month-days
  are left alone. Bare weekdays only after since / this past / started (on) /
  began (on) — the last two added because the extractor rewords "since Tuesday"
  as "started on Tuesday".
- Frontend: the escalate path now adopts the returned `mode`/`mode_switched`.
- Verified live (sandbox, qwen3:8b): the throat question in serious mode
  returns the fixed reply with 0 model calls; the stored fact carried
  2026-10-20; "just from my notes — when does my Minfy contract renew?"
  switched to serious and answered from the note with a valid link.
  Tests: `tests/test_chat_mode_fixes.py`; suite 653 passed / 0 skipped.
