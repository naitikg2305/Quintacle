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
