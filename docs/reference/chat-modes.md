# Chat modes & the soft record (code-derived, 2026-10-27, next-wave-plan §12)

Sources: `core/quintacle_core/nodes/kb/chat.py`, `soft_record.py`,
`transcripts.py`, `kb/api.py`.

## Modes
`POST /kb/chat` request `mode: "serious" | "unserious"` (default `unserious`).
Response: `{reply, mode (effective), mode_switched}`. The frontend keeps the mode
sticky by echoing the returned `mode`. A trigger phrase in the NEWEST user
message overrides the request's mode for that turn (`resolve_mode`);
`mode_switched` is true only when that changed it.

### Phrases (`detect_mode_phrase`, deterministic regex, case-insensitive, whole-phrase, `’`→`'`, flexible whitespace; if both kinds appear the later one wins)
- serious: `serious mode`, `kb only`, `knowledge base only`, `just from my notes`,
  `only from my notes`, `only what i've recorded`, `only what i recorded`,
  `strictly from my notes`, `stick to my notes`
- unserious: `unserious mode`, `casual mode`, `normal mode`, `back to normal`
- no match -> None (request mode kept). "that's a serious injury" does not trigger;
  "unserious mode" is not read as "serious mode".

## Context order (`_system_text`)
Both: (1) `Now:` line, (2) `## About the user` (Me lane).
`use_kb=false`: only the Now line. Folder-only scope: folder entries (no
retrieval, no day bundles, no recent-chats block).

- **Serious** (no scope / note-scoped): intro "answering strictly from ... knowledge
  base" + grounding + link rules + SERIOUS rule ("that's not in your notes", never
  guess) -> [topic hydration] -> `## Retrieved for the latest question` hits
  (each prose note: `— updated YYYY-MM-DD`) -> `## <date> — that day's record`
  bundles. No timeline, no soft record.
- **Unserious**: human-persona intro + grounding + link rules (+ recent-chats rule
  when the block exists) -> same KB material as above -> `## From recent chats
  (not recorded in your notes)`: "Things you told me recently" (soft facts, last 30
  days, newest first, `- [YYYY-MM-DD] text`, <=2,000 chars) then "Excerpts from past
  chats" (<=3 transcript FTS hits, last 14 days, `- [date] …snippet`, <=2,500
  chars). Block gets `24,000 - len(rest)` chars, so it shrinks first; <200 left or
  any error -> omitted.

## Serious-mode zero-match short-circuit (correction 2026-10-27)
`_build_context` returns `(text, nothing_to_ground)`; `_system_text` is its text.
`nothing_to_ground` is True only when: `use_kb` is on, scope is NOT folder-only,
no topic hydration (folder+slug note found), retrieval RAN and returned the
no-match sentinel (retrieval-down -> legacy dump-everything counts as material),
no day bundle, and the Me block is empty. `run_kb_chat` in SERIOUS mode with it
set returns `SERIOUS_NOTHING_REPLY` ("That's not in your notes." + a line
suggesting casual mode / recording it) WITHOUT calling any provider. Response
shape unchanged (`reply`, `mode`, `mode_switched`).

## Link post-validation (every reply, every mode/provider)
`validate_reply_links(reply, store)` runs after photo-tag resolution. Markdown
links and images (`[t](href)`, `![t](href)`, `<...>` hrefs) whose href is:
- `/kb/browse?path=F&open=S` -> valid iff `KBStore.read(F, S)` (values URL-decoded;
  KBStore slugifies each folder segment and the slug, so "Health%20Notes" finds
  `health-notes`); `open` without `path` -> not found;
- `/kb/browse?path=F` -> valid iff the folder exists; bare `/kb/browse` -> valid;
- `/kb/asset?folder=F&path=P` -> valid iff `KBStore.asset_exists` (same clamp
  as `read_asset`; escaping the root = not found); missing `path` -> not found;
- a malformed query on either route -> not found.
Not found -> `text (not found in your notes)` (link text, or the href if empty).
External (scheme/netloc) and any other href are left byte-identical.

## Soft record
`<data_dir>/conversations/soft_record.db`, table `soft_facts(id INTEGER PK, date
TEXT ET, text TEXT, transcript TEXT, UNIQUE(date,text))`. Outside `kb/`; not in
the retrieval index, graph, /kb/*, or MCP.
- Written by `extract_and_store` as a FastAPI background task after
  `POST /transcripts/archive` (keep=true, not incognito, non-empty). One
  `llm_dispatch.parse_structured(..., provider="local")` over the user's turns only;
  any failure -> nothing written; archive never affected.
- Relative dates are anchored at store time (`annotate_fact_date(text, chat_date)`,
  chat_date = the archive's ET date): day_context relative forms (today, tonight,
  yesterday, day before yesterday, last <weekday>, N days/weeks ago, last week)
  resolved via `detect_dates`, plus bare weekdays after `since` / `this past` /
  `started (on)` / `began (on)` -> most recent such weekday strictly BEFORE the chat
  date. `(YYYY-MM-DD)` is inserted after the first relative expression only when
  all dates in the fact collapse to exactly one. Untouched: facts with an ISO date
  already, any future cue (next, coming, upcoming, tomorrow, will, won't, shall,
  going to, gonna, plan(s/ning) to, 'll), explicit month-days alone, bare weekdays.
  `QUINTACLE_SOFT_RECORD_PROVIDER=off` disables.
- `soft_facts_added` in the archive response is always 0 (deferred);
  `soft_facts_pending: true` means a job was queued. Dedup: same text same date.
- `GET /soft-record` -> `[{id, date, text, transcript}]` newest first;
  `DELETE /soft-record/{id}` -> `{deleted: id}` (404 if absent).
- `keep=false` or `incognito=true`: nothing archived, extractor never called.

## Leak guard
`transcript:` ids are skipped in `retrieval._neighbors` (hence `/retrieve` and
`neighbor_labels`) and in chat's `_neighbor_line`. `/graph` never draws them.
