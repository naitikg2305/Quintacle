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

## Soft record
`<data_dir>/conversations/soft_record.db`, table `soft_facts(id INTEGER PK, date
TEXT ET, text TEXT, transcript TEXT, UNIQUE(date,text))`. Outside `kb/`; not in
the retrieval index, graph, /kb/*, or MCP.
- Written by `extract_and_store` as a FastAPI background task after
  `POST /transcripts/archive` (keep=true, not incognito, non-empty). One
  `llm_dispatch.parse_structured(..., provider="local")` over the user's turns only;
  any failure -> nothing written; archive never affected.
  `QUINTACLE_SOFT_RECORD_PROVIDER=off` disables.
- `soft_facts_added` in the archive response is always 0 (deferred);
  `soft_facts_pending: true` means a job was queued. Dedup: same text same date.
- `GET /soft-record` -> `[{id, date, text, transcript}]` newest first;
  `DELETE /soft-record/{id}` -> `{deleted: id}` (404 if absent).
- `keep=false` or `incognito=true`: nothing archived, extractor never called.

## Leak guard
`transcript:` ids are skipped in `retrieval._neighbors` (hence `/retrieve` and
`neighbor_labels`) and in chat's `_neighbor_line`. `/graph` never draws them.
