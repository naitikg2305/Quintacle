# The MCP angle

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
