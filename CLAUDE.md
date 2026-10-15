# Quintacle — standing instructions for Claude

Read `docs/session-log.md` (top entry) and `docs/reference/00-statement-of-work.md`
before assuming anything about what exists — this project moves fast and
memory/docs go stale; code is truth.

## Principles (owner-decided, durable)

- **Local-first, computer AND phone.** Easy model tasks (drop classification,
  journal parsing, prose polish, perception) default to local models; cloud
  is a user-chosen escalation. Ingest escalation re-runs from the ORIGINAL
  input (step back, never re-prompt over local output). Chat escalates by
  user choice, transferring context into the cloud call. Details:
  `docs/architecture.md` (2026-10-15 amendment), `docs/local-inference-migration.md`.
- **Deterministic core, models at the edges.** Code fetches/decides;
  anything arithmetic is computed in code and handed to models as finished
  numbers. Never let a model re-derive what SQLite/the graph already knows.
- **Reference, never duplicate.** Cross-domain knowledge connects via graph
  edges (`core/quintacle_core/graph.py`); person/place pages compute their
  content from `reverse_lookup`, they don't copy text around.
- **Writes are gated or undoable.** In-app: propose→review→Save. MCP:
  auto-write but every push is one ledger entry (`~/.quintacle/mcp-log.md`)
  with staged-snapshot undo. Never add a write path with neither property.
- **Eastern Time everywhere** — `core/quintacle_core/clock.py` /
  `frontend/lib/date.ts`; never `datetime.now()` / `new Date()` date math.
- **Vault stays invisible** to every model-facing surface (search, graph,
  MCP, chat, drop). It lives OUTSIDE `kb/` on purpose; keep it that way.
- **Docs are decision logs**: never rewrite/delete historical reasoning —
  add dated status/correction notes. Deep how-it-works lives in
  `docs/reference/` (code-derived; restamp if regenerated).

## Working conventions

- Heavy/optional deps (perception, desktop) get their own requirements
  files + lazy imports; `core/requirements.txt` stays phone/Termux-safe,
  and the full test suite must pass WITHOUT optional deps installed.
- Tests: `cd core && .venv/bin/python -m pytest -q` (243+ must stay green);
  frontend: `npx tsc --noEmit` → 0 errors; eslint: no NEW errors
  (a few `react-hooks/set-state-in-effect` are pre-existing).
- Run it: backend `cd core && .venv/bin/uvicorn quintacle_core.api:app
  --port 8000` (port 8000 is Quintacle's — matches phone + desktop shells);
  frontend `cd frontend && npm run dev`. Real data: `~/.quintacle/`
  (`QUINTACLE_DATA_DIR` to sandbox — ALWAYS sandbox for experiments).
- `nodes/kb/chat.py`: model-provider/registry changes are allowed (owner
  opened this); the KB-context/prompting/session logic stays untouched.
- Subagent worktrees historically get cut from a stale base — always
  `git reset --hard redone-UI` in a fresh worktree before building.
- Commits end with the session's attribution line; push only to
  `origin redone-UI` with `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_pers -o IdentitiesOnly=yes"`.
