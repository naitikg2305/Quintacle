# Transcript archive — how it works

Code-derived 2026-10-19 from `core/quintacle_core/nodes/kb/transcripts.py`,
`core/quintacle_core/api.py` (wiring), and `frontend/app/kb/page.tsx` /
`frontend/lib/api.ts` (the close hook). Restamp if regenerated.

The second-tier store from `next-wave-plan.md` §4: conversations are working
memory; when a chat closes, its raw transcript is filed verbatim — a plain
file write, **zero model calls** — somewhere no default search or model
surface can see, reachable only when the owner explicitly asks to dive
deeper.

## Where transcripts live

```
<data_dir>/conversations/            # data dir: QUINTACLE_DATA_DIR, else ~/.quintacle
  transcripts.db                     # private FTS5 index (derived, disposable)
  <topic-slug>/
    <YYYY-MM-DD-HHMM>.md             # one verbatim transcript per close
```

`conversations/` sits at the data-dir root, deliberately **outside `kb/`** —
the same structural-invisibility pattern as the vault. Every model-facing
surface (KB listings/search/chat context, MCP tools, drop, the graph page's
note rendering) only ever walks `kb/`, so the archive cannot leak into a
prompt or a default result. `test_transcripts.py` asserts this against the
real REST endpoints and the real MCP tools.

## The file

Frontmatter: `date` (Eastern Time ISO, via `clock.now()`), `topic`
(the slug), `message_count`. Body: the turns verbatim, one `### You` /
`### Assistant` section each (the same heading convention `chat_store.py`
uses). Plain-string turns are character-for-character untouched; attachment
turns keep their text plus a "(photo/PDF attached)" note via the shared
`_as_text` — raw base64 is never archived.

## Topic slug — deterministic, always

- Session has a subject → `markdown_paths.slugify(subject)`
  ("Pull Day Planning" → `pull-day-planning`).
- No subject → a date-time slug (`2026-10-19-1432`).
- Filename stamp is `%Y-%m-%d-%H%M`; a same-minute second close of the same
  topic falls back to second resolution, then a counter — an archive is
  never overwritten.

A local model proposing a nicer slug (via `llm_dispatch`) was considered and
deliberately left out of this wave: the archive's contract is zero model
calls in the hot path, and the deterministic slug is mandatory regardless.

## The graph edge

On archive, one `transcript_of` edge
`transcript:<topic-slug>/<stamp>` → the topic's node is created **only**
when the chat's subject confidently names a real node: `title_mentioned`
(THE matcher, `graph.py`) against every KB note title (people's profiles
included — they are notes) and experience names; among several matches the
longest title wins, ties alphabetical — deterministic. No subject, or no
match: no edge, never a guess. `source_of_edge: "transcript_archive"`. The
edge is additive — a failure there can never fail an archive that already
landed.

## The FTS index — separate on purpose

One FTS5 virtual table (`transcript_fts(path, topic, date, body)`) in its own
sqlite file `conversations/transcripts.db` — not in `quintacle.db`, and fully
separate from the §3 retrieval engine's index. Populated at archive time.
The markdown files are the source of truth; the index is derived and
disposable (delete the .db, re-archive rebuilds rows — same folder-first
contract as the graph's edge files). Queries are sanitized (each token
quoted, scoped to the body column) so FTS5 operator syntax in user text
can't error or widen a search.

## Endpoints — the only two doors

- `POST /transcripts/archive` — body `{messages, subject?, keep=true}`.
  The archive-on-close hook. `keep=false` (the per-chat "don't keep"
  toggle) archives nothing at all; an empty transcript archives nothing.
  Returns `{archived, path, topic, date, stamp, message_count, edge_id}`.
- `GET /transcripts/search?q=...&topic=...` — ranked FTS5 hits
  `{path, topic, date, snippet}`, optionally scoped to one topic. This is
  the explicit "dive deeper / refer to transcripts" lane and the **only**
  surface anywhere that reads the archive.

## The close flow (frontend → endpoint → file)

`frontend/app/kb/page.tsx` keeps the live chat purely in page state — no
thread list, no session reopening ("talk yap add and delete — always keep
the chat page fresh and neat"). The chat's subject is its first message
(sliced to 60 chars), or `Re: <note title>` when continuing on an entry.

1. User clicks **New chat** (the close affordance) or continues onto a note.
2. `closeChat()` → `archiveTranscript(chatLog, subject, keepTranscript)`
   → `POST /transcripts/archive`.
3. `TranscriptStore.archive()` writes the markdown file + the FTS row;
   `link_transcript_topic()` maybe adds the one edge.
4. Page state clears — subject, log, target, attachment, toggle back to
   keep. An unreachable backend still clears the page (never traps the user
   in a stale chat; that transcript is simply not archived).

The **Keep transcript / Don't keep** toggle (default: keep) is per-chat and
resets to keep on every new chat.

The old `/kb/chats` session endpoints and `ChatStore` remain server-side but
the page no longer writes mid-chat sessions. `chat.py`'s KB-context /
prompting logic is untouched — hydration-from-retrieval and explicit
"record that" folding are the chat-context wave's job, over §3's engine.

---

**Correction 2026-10-27 (next-wave-plan §12):** the "explicit-only, nothing else
reads the archive" rule above no longer holds in the default chat mode. In
**unserious** mode (the default) chat's context includes a `## From recent
chats` block: up to 3 FTS snippets from this archive dated within the last 14
days (`TranscriptStore.search(..., since=, limit=, any_term=True)`), plus soft
facts extracted from kept archives (see `chat-modes.md`). **Serious** mode keeps
the original guarantee exactly: the archive never enters context. Everything
else is unchanged: files stay outside `kb/`, off the graph view, and invisible
to /kb/*, MCP and the main retrieval index. `POST /transcripts/archive` also
gains `incognito` (alias of `keep=false`) and returns `soft_facts_added`
(always 0 — extraction is a deferred background task) / `soft_facts_pending`.
`transcript:` ids are now filtered out of every `Connected:` neighbor label and
`/retrieve` neighbor list.
