# The MCP angle

> **Status update 2026-10-15: BUILT.** The MCP server exists and is live on
> `redone-UI`: `core/quintacle_core/mcp_server/` (run
> `python -m quintacle_core.mcp_server`, stdio), 16 tools over
> journal/KB/expenses/todos plus `day_recall` and `describe_photo`,
> **auto-write** with the staged-snapshot + combined ledger
> (`~/.quintacle/mcp-log.md`) + 24h-undo design settled in the 2026-10-13
> sections below, and every write auto-linking into the graph. The
> code-derived reference is `reference/mcp-server.md` — read that for what's
> actually there; this doc stays as the decision log. The per-section status
> lines below ("idea, not started", "still not built") are **historical** and
> no longer true.
>
> Genuinely still not built: tools for the remaining ~12 domains in the
> inventory table at the bottom (meals, exercise, habits, finance cards,
> people, wardrobe...), remote/HTTP transport (phone chat apps — still
> stdio-only), binary asset transfer over MCP, and the in-app "recent writes"
> ledger page / 24h-undo-window UI (undo works via the `undo_write` tool; the
> UI surface for it doesn't exist yet).

Status: **idea, not started.** No code written, no decision made. This is a
parking note from a conversation on 2026-09-16 so the thinking isn't lost —
nothing here is committed to.

## What MCP is, mechanically

Model Context Protocol. It's a wire protocol — JSON-RPC 2.0 over stdio or
HTTP — between a **host/client** (Claude Code, Claude Desktop, Cursor, Zed)
and a **tool server** (a separate process you write).

The methods that matter:

| Method | What it does |
|---|---|
| `initialize` | Handshake; server declares what it supports |
| `tools/list` | "What can you do?" → names + JSON Schemas |
| `tools/call` | "Run `get_day` with `{for_date: ...}`" → result |
| `resources/list` / `resources/read` | Expose readable *data* rather than actions |
| `prompts/list` / `prompts/get` | Canned prompt templates offered to the user |

**MCP is not tool calling.** Tool calling already exists and Quintacle-adjacent
code already does it. MCP is the part where a tool stops being locked inside
one process and becomes callable by clients you didn't write.

## What already exists here that's MCP-shaped

`~/code/Local-chat/server.py` (a separate project, not Quintacle) already
implements the whole pattern by hand against Ollama:

- `WEB_TOOLS` — two tool definitions with JSON Schema params
  (`search_web`, `read_web_page`). This is a hardcoded `tools/list` response.
- `execute_tool()` — name → Python dispatcher. This is `tools/call`.
- `agentic_web_generation()` — the agent loop, with `MAX_AGENT_ROUNDS` and
  `MAX_AGENT_TOOL_CALLS` budgets.

Quintacle itself has **no** tool-calling loop. Per `architecture.md` it routes
deterministically and uses an LLM only at the narration edge, which is
deliberate and shouldn't change.

## The three directions, with verdicts

**1. Quintacle as an MCP server — the one worth considering.**

`core/quintacle_core` exposes ~50 REST endpoints over deliberately structured
personal data: `/meals`, `/expenses`, `/habits/{id}/progress`,
`/nutrition-history`, `/day/{for_date}`, `/search`, `/journal/{for_date}`.
Today only the Next.js frontend can reach them. An MCP server over that surface
would let Claude Code (or any MCP client) query the real store directly —
"what did I spend on food in August", "how's the golf habit tracking".

It fits the architecture rather than fighting it: Quintacle's thesis is
deterministic fetch with the LLM only phrasing the result, and MCP is exactly
that split — the server navigates, the model narrates. It's a second, better
narrator over facts the frontend already gets, not AI bolted onto the store.

Scope would be ~a dozen read-oriented tools (`get_day`, `search_journal`,
`nutrition_for_date`, `habit_progress`, `expenses_in_range`), not a mechanical
wrapper of all 50 routes. Tool descriptions are prompt surface; fewer,
well-described tools beat exhaustive coverage.

**2. Local-chat as an MCP client — interesting, lower priority.**

If Local-chat spoke MCP as a *client*, local models could reach any existing
MCP server (filesystem, Postgres, GitHub, Slack) without implementing a single
tool. The bridge is ~100-150 lines where `WEB_TOOLS`/`execute_tool` sit now:
connect → `tools/list` → translate to Ollama's `{"type": "function"}` shape →
route `tool_calls` back to `tools/call`. After that every new tool is a config
entry, not code.

**3. Converting Local-chat's existing web tools to an MCP server — skip.**

Pure overhead. Same behavior, plus a subprocess and JSON-RPC framing. Ollama
doesn't speak MCP, so it'd also need the client half written — *more* code than
the current dispatcher, not less. Only worth it to make those two tools
reachable from Claude Code as well.

## Why it looks like "a thing for other people's editors"

N apps hand-writing integrations to M tools is N×M work; MCP makes it N+M.
With N=1 and M=2 the math doesn't favor us — which is the honest reason nothing
here is urgent. It stops being true as soon as either number grows.

## Constraint to settle before any of this gets built

Quintacle holds journal entries, health and body stats, expenses, and
EXIF-derived location. An MCP server over **stdio to a local client** keeps
that on-device; pointing a **hosted** client at it sends personal data off-box.
Decide which clients are allowed *before* the server exists, and keep write
tools (`POST /drop`, `/expenses`, `/meals`) out of v1 so a bad tool call can't
mutate records. This is the same local-vs-cloud boundary already drawn in
`deployment-and-privacy.md` — it should be answered consistently with the
opt-in privacy checkbox there, not re-litigated.

## Open questions

- Read-only v1 is the obvious start, but is a read-only personal assistant
  actually useful, or does the value only show up once it can log things?
- Does this belong in `core` as another surface over the same stores, or as a
  standalone process that talks to the FastAPI app over HTTP?
- Does it overlap with, or replace, anything the KB chat (`nodes/kb/chat.py`)
  already does? Standing instruction is not to mess with the chat.
- Which node's tools first — schedule/logs (most structured) or journal
  (most narratively interesting)?

## Next step

None scheduled. Pick this up by choosing between direction 1 and 2, then
scoping the tool list.

---

## Update 2026-09-29 — reframed, and now wanted

Status: **still idea, not started, but the verdict changed.** Conversation on
2026-09-29 moved this from "parked, math doesn't favor us" to "this is the
direction." Nothing built yet, per explicit instruction: note only.

### The reframe: Quintacle is a data harness, not a model harness

Looking at the code as it stands (not the plans): ~15 entry types across a
dozen node packages, 101 REST routes, a deterministic drop router that picks
entry type from a keyword prefix before any model is consulted, and thin
`llm.py` adapters that are just a Pydantic schema plus one structured call.
No agent loop anywhere. The model is a pluggable component invoked at exactly
two seams:

1. **Ingest edge** — messy text/image in, validated schema out.
2. **Narration edge** — fetched facts in, prose out.

So the honest definition: *a structured personal operating system with a
deterministic core and LLM sockets at the boundaries.* A data harness that
models plug into, rather than a model harness that tools plug into. The word
"harness" is fine as long as it doesn't tempt an agent loop *into* the core —
Quintacle is the thing orchestrated over, not the orchestrator.

### What MCP changes, and what it doesn't

**It flips who calls whom.** Today Quintacle's Python initiates every LLM
call and the model never knows Quintacle exists. As an MCP server, the model
(inside Claude Code / Codex / any client) reads the tool list and decides on
its own to call `expenses_in_range`, chains two or three calls, and phrases the
answer. The agent loop lives in the *client*, not in our code — which is
exactly where `architecture.md` wants it.

**It doesn't change what Quintacle is.** Same stores, same SQLite, same
markdown, same REST for the frontend. MCP is a second door onto the same
rooms. If the MCP process is never launched, nothing behaves differently.

**Concrete shape in the repo:** one new small Python process using the MCP
SDK, importing the same store classes the routes already use, exposing ~a
dozen tools. Tool descriptions are the new kind of writing — they're the only
thing the model reads to decide when to reach for a tool.

### The use case that made it click

Sit in Claude Code or Codex, have a normal working/learning conversation about
anything, and at the end say "put that in Quintacle." The model writes the
distilled note straight into the store via a tool call. That closes the loop
`intro.md` was written for — "learn something → summarize → push → lands in
the organized database" — without switching apps or breaking flow. The
learning-in-motion that currently "goes into the abyss" gets captured *from
inside the tool where the learning happened.*

This is the strongest argument against the earlier "N=1, M=2, math doesn't
favor us" reasoning: the value isn't integration breadth, it's that the
capture point moves to wherever the user already is.

### Offline / privacy — settled in principle

- The MCP server runs **locally over stdio**: the client spawns it as a
  subprocess and they exchange JSON over pipes. No port, no network, no
  hosted server, no domain, no account. Data stays in `~/.quintacle/`.
- The only cloud hop is the **model**, not Quintacle. With Claude Code as the
  client, whatever a tool returns is sent to Anthropic as context so the model
  can phrase it. That's the same exposure the drop router already accepts
  when it sends a journal dump to Haiku — just in the other direction, and
  chosen by the model rather than by our code.
- **Fully offline is the same server, different client.** MCP is
  client-agnostic; Ollama-backed clients (Continue, various open chat
  frontends, and `~/code/Local-chat` which is already most of a client) can
  drive the identical tool list with a local model. Same tools, pick the
  brain. This maps directly onto the four-tier routing in
  `deployment-and-privacy.md`.

### Revised open questions

- **Write tools are now the point, not a v1 exclusion.** The earlier note
  said keep `POST /drop` etc. out of v1 so a bad tool call can't mutate
  records. The "write directly from Claude Code" use case needs at least one
  write tool. Resolution to consider: expose *exactly one* write tool that
  feeds the existing deterministic drop router (so the router still decides
  type/placement, the model only supplies text), rather than per-type write
  tools. Keeps the model from deciding structure. Still needs deciding.
- Read tools: start with schedule/logs (most structured) or KB/journal (what
  a working conversation would actually want to write into)? The use case
  above points at KB first.
- Standalone process importing stores directly vs. talking to FastAPI over
  HTTP. Direct import is simpler and avoids needing the API up; HTTP keeps
  one code path. Lean: direct import.
- Standing instruction still holds: don't mess with `nodes/kb/chat.py`.

### Next step

Scope the tool list (reads + the single drop-style write) and pick KB vs.
logs for the first slice. Then build. Not before the UI redo lands.

### Does MCP break when Quintacle changes? (2026-09-29)

Mostly no, because of where the coupling sits. Built as leaned above, the
MCP process imports the same store classes the REST routes use and each tool
is a thin wrapper: take arguments → call a store method → return the result.
That's the exact relationship `nodes/kb/api.py` already has to
`nodes/kb/store.py`. So the MCP layer is coupled to the same surface the
frontend's API layer is coupled to — anything that doesn't break REST doesn't
break MCP.

**Keeps working with zero MCP changes:**
- Any frontend change (the whole UI redo). MCP never sees the frontend.
- New entry types / nodes / routes. MCP just doesn't know about them until a
  tool is added. Nothing breaks.
- Storage changes under a store (new SQLite column, different markdown
  layout). The store hides that.
- Prompt/model changes in the `llm.py` files.
- New drop prefixes — if the write tool feeds the drop router, new prefixes
  work through MCP immediately. Nice property; another reason to route writes
  through the router rather than per-type tools.

**Requires touching MCP:**
- Renaming / re-signaturing a store method a tool calls (same as for a route).
- Changing the shape a store returns, if the tool passes it straight through.
  Degrades rather than breaks — the model sees different JSON — but the tool
  description goes stale.
- Wanting a new capability exposed: additive, one new tool function.

**Practical wrinkle:** the client spawns the MCP server as a subprocess at
session start, so a live session holds old code in memory. Edit Quintacle →
restart the server/session to pick it up. Same as restarting uvicorn today.

**Where risk actually concentrates:** the tool *description text*, not the
code. Change what a store does without updating the description and the
model calls it with wrong expectations — and nothing throws. Mitigation: a
small test per tool against the real store (like the existing `test_store.py`
pattern) for the code side; discipline for the description side.

---

## Update 2026-10-07: decided, approval-first writes

Status: **design decision, still not built.** Naitik picked this on
2026-10-07. It answers the "write tools" open question above: the MCP
gets write tools, and *every* write waits for his approval.

### The rule

**Every MCP write goes through an approval queue inside Quintacle.** That
covers adds, edits, moves and deletes. No write tool ever touches a store
directly.

1. A client (Claude, GPT, a local model, any of them, even running on
   full auto) calls a write tool, e.g. `log_expense(...)` or
   `move_kb_entry(...)`.
2. Quintacle records it as a **pending proposal**: what would be written,
   where, and which client asked.
3. He sees it in Quintacle, in an approval inbox in the app and ideally as a
   phone notification, e.g. "Claude wants to log $14.50 at Chipotle →
   Finance": **Approve / Edit / Reject**.
4. Only his action in the app commits it.

Reads need no approval.

### Why the gate lives in Quintacle, not the chat client

- **Approving is never an MCP tool.** The approve/reject action exists only
  in Quintacle's own UI/API, so a model has no tool it could call to approve
  its own write. "Auto mode" in the client can't skip it.
- **It works with any client.** The rule is the same for Claude, GPT and
  local models, because no client is trusted to do the asking.
- **Considered and not used as the gate: MCP elicitation.** That's the server
  asking a yes/no question through the chat client. Clients support it
  unevenly, and a client set to auto-accept could answer yes on his behalf.
  At most a convenience later, never the safety mechanism.
- **It matches how Quintacle already works.** Journal parse and Drop only
  *propose* entries and nothing is written until he reviews them. The MCP is
  another way into that same review step, not a new trust model.

### Confirmation back to the chat

After approval, the tool result says exactly what was written and where,
with a deep link into the app (e.g. `/kb/browse?path=&open=`), so the chat
can show "here it is, check it yourself." Edits applied in the inbox are
reflected in that result, so the model learns what actually landed.

The chat can't wait forever, so a write tool should:
- **wait briefly** (~30–60s) for approval, for when he's holding his phone,
  then return the confirmation; else
- **return "pending #id"** and let the model check later with a read tool
  like `proposal_status(id)`.

### Still to decide (carried over, see superseding update below)

- How this fits the earlier "one drop-style write tool feeding the router"
  idea. Probably the router fills in the write and the ledger records it,
  but edits/deletes need their own tools since the router only creates new
  entries.

---

## Update 2026-10-13 — superseded: auto-write everywhere, undo instead of approval

> *2026-10-15: this design is now built exactly as described — staged
> snapshots, one combined ledger, grouped multi-step undo (`undo.py`,
> `ledger.py`). See `reference/mcp-server.md`. Only the in-app recent-writes
> page is still missing.*

Status: **design decision, still not built.** Settled 2026-10-13, over a
longer conversation working through what undo would actually have to look
like. This replaces the approval-first design directly above — kept in
place rather than deleted, since the reasoning that led to it (and the
reasoning that reversed it) are both worth keeping.

### The reversal, and why it holds up

Approval-before-the-fact and undo-after-the-fact solve the same problem:
catching a bad write before it does damage. If undo is airtight — every
destructive action stages a full, exact snapshot of what existed *before*
it touches the real store — then nothing is actually unrecoverable, which
means the human gate before the fact stops earning its friction.

The other half of why this is safe to do: **Quintacle is single-user.**
Naitik is the only one using this instance (or, for whoever else ever runs
their own copy — see `generic-multi-user-migration.md` — the only one using
theirs). Approval exists to catch *your own* mistake, not to referee between
multiple people's clients writing to shared data. Undo catches the same
mistake, just slightly later, with far less friction for every write that
turns out fine — which is most of them.

### The rule

**Every MCP write commits immediately. Add, edit, delete — no approval,
ever.** The earlier plan (approval gates destructive writes, adds auto-write)
is gone; everything is now the same: auto-write, logged, undoable.

### The mechanism that makes this safe

1. **A staging/shadow folder**, separate from the real stores. Before any
   edit or delete touches real data, the exact prior state is captured
   there first: full file bytes for a markdown file, the full row for a
   SQLite record, or the exact span of text for an append (so undoing an
   append removes only that span, not the whole file — the same precision
   problem flagged in the approval-first design above still applies here,
   just solved after the fact instead of before).
2. **One combined ledger** — a single, human-readable, append-only log of
   every push ever made: what, where, which client, when. This *is* the
   "recent writes" page in the app; it just renders the ledger's tail.
3. **Clicking a ledger entry opens a diff** built from the staged snapshot:
   what text got appended, the before/after for an edit, or the full
   content that existed right before a delete.
4. **"Undo" on an entry replays the snapshot backward** — restores the
   file, reinserts the row, or strips the appended span.
5. **Multi-part pushes** (one MCP call that creates or changes several
   things at once — the car-maintenance-entry case in
   `ai-managed-pages.md`, or a journal parse spawning several entries) are
   grouped as a single ledger entry, so undo reverses the whole group
   together, never partially.

### Retention

The app only *offers* the Undo button for a rolling 24 hours — past that,
undoing something risks surprising whatever's been built on top of it
since. The raw staged snapshots themselves are kept indefinitely regardless
(plain text, storage is a non-concern) — nothing is ever truly gone, just
harder to recover past the window without going to the files directly.

### Left as an open idea, not a requirement

Flagging deletes more visibly in the ledger (bold, a distinct marker, kept
near the top) — since a missed delete is the one case where missing the 24h
window is a real, permanent loss, unlike a stray addition or a bad edit
someone's unlikely to build directly on top of before noticing. Not asked
for; worth considering if deletes end up actually happening often enough to
get lost in the scroll.

### Where approval-first still might matter

Only if Quintacle ever becomes multi-user (`generic-multi-user-migration.md`,
its own branch, not on `main`). A shared instance with several people's
clients writing to shared data is a different trust problem than one person
catching their own mistakes — that's the point at which approval-first (or
per-user visibility) might need to come back for other users' writes, even
if the owner's own instance stays auto-write.

---

## Update 2026-10-13 — structured writes, and the full tool surface

> *2026-10-15: the structured-input rule is built and enforced (every write
> tool takes the final decided shape; `kb_create_entry` takes
> folder/title/content/links/fields). Of the table below, the Journal,
> Schedule/todos, KB and Expenses rows exist, plus `day_recall` and the
> billed `describe_photo` convenience tool. The other ~12 domains' tools are
> still unbuilt, and the exclusions section is unchanged (kb chat untouched,
> vault-shaped docs held back, binary assets unsolved). Inventory of what's
> real: `reference/mcp-server.md`.*

Status: **design decision + inventory, still not built.** Settled over the
same 2026-10-13 conversation as the auto-write/undo reversal above. Two
things: a rule about what a write tool's *input* looks like, and a complete
pass over every domain in the app to make sure none gets left uncovered.

### The structured-input rule, and why it's a real cost decision, not style

Quintacle's own backend already makes its own direct, metered Anthropic API
calls — 35 separate call sites across `core/quintacle_core`, Haiku by
default for routine parsing, Sonnet for heavier work (`llm_config.py`). That
billing is on Naitik's own API key, separate from and unrelated to a Claude
Pro/Max or ChatGPT Plus subscription, which is flat-rate and doesn't carry
API credits.

The use case that makes this concrete: planning a meal, a trip, or just
talking through something in a normal Claude.ai or ChatGPT conversation —
already paid for by the subscription — then saying "push that to Quintacle."
If the write tool's input is raw text that Quintacle's backend then
reclassifies with its own `drop_router.py` / `suggest_kb_entry`-style calls,
the structuring gets paid for *twice*: once implicitly in the subscription
conversation, again literally on the metered API key. If the write tool
instead takes the **already-decided shape** — title, folder, content,
`fields`, `links`, the exact store-specific arguments — Quintacle's backend
just persists it. No second LLM call, no second bill, because the thinking
already happened in the conversation the write tool is being called from.

**Rule: every structured write tool's parameters are the final, decided
shape of the thing being written — never raw text for Quintacle to figure
out.** A small, separate class of "let Quintacle think about it" tools (see
below) exists on purpose for quick, unstructured capture — those are the
one category that still costs Quintacle's own API budget, and should read as
clearly different from the structured tools in how they're described to a
client.

### The full tool surface, by domain

Every domain gets a read tool and a structured write tool, built as a thin
wrapper over the same store classes the existing REST routes already use
(`nodes/<domain>/api.py`) — same relationship MCP already has to the rest of
the app per the "does MCP break when Quintacle changes" section above.
"Convenience" columns are the raw-capture, Quintacle-does-the-thinking
tools — explicitly the ones that still bill the API key.

| Domain | Read tools | Structured write tools | Convenience (billed) tools |
|---|---|---|---|
| Day overview | day detail, day counts | — (derived view) | — |
| Journal | get day's journal | append to journal | parse day's dump into proposed entries |
| Schedule / todos | list todos, calendar | create todo, update todo, delete todo | — |
| KB / notes | list folders, list/search entries, get entry, entries-meta, get/set folder view, list photos | create entry (title, folder, content, fields, links), replace/attach asset, set spreadsheet asset | drop (raw text/photo), batch-drop, auto-sort a folder |
| Graph | neighborhood(node, hops), reverse-links(node) — per `graph-model.md` Stage 3 | (writes happen as a side effect of every other write's link step, not its own tool) | — |
| Meals / ingredients / routines | list meals, meal micros, list ingredients, ingredient micros, meal components, list routines | create meal, create ingredient, create routine, compose meal from ingredients | estimate meal from description/photo, suggest routine, suggest meal composition |
| Food / substances / nutrition | food for date, nutrition for date, nutrition history | log food, log substance | — |
| Exercise / activities / body stats | exercise names, activities for date/range | log exercise, log activity, log body stat | — |
| Expenses | expenses in range | log expense | — |
| Habits | list habits, progress, history | create habit | — |
| Finance (cards / investments) | list cards/investments | create card entry, create investment entry | — |
| Documents | list, get asset | create document entry | — (see caveat below) |
| People | list/search | create person | — |
| Travel / experience | list | create experience | — |
| Wardrobe | list items, list outfits | create item, create outfit | suggest an outfit |
| Grooming | list items, list routines | create item, create routine | suggest a routine |
| Home | list residences, list items | create residence, create item | — |
| Profile | get profile, get targets | update profile | — |

### Explicit exclusions and open gaps — not silently covered

- **`nodes/kb/chat.py` and everything under `/kb/chat*` stay untouched.**
  Standing instruction from earlier in the project, unrelated to MCP — the
  KB chat doesn't get a tool, full stop.
- **Documents that are vault-shaped (license, passport, tax docs, visas) —
  held back, not covered by default.** `vault.md` calls for security-first
  handling these don't have yet; today's `nodes/documents` store treats them
  the same as any other document, which is fine for the app's own UI behind
  normal auth but not obviously fine for "any MCP client I authorize can
  read my passport on request." Needs its own decision before a read/write
  tool goes on top of it, not inherited automatically from this table.
- **Binary asset transfer (photos, PDFs) over MCP is an open question, not
  solved here.** Every domain above has an asset-carrying write path in the
  REST API (`multipart/form-data`); MCP's blob/resource mechanics for this
  haven't been worked out. Flagging it so it isn't assumed solved by being
  in the table.
- **Image generation (`/kb/generate-image`)** isn't knowledge capture or
  retrieval — left out of this pass, revisit only if a concrete use for it
  through MCP shows up.
