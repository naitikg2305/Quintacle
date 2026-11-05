# Chat context — index→select→fetch over the retrieval engine

Code-derived 2026-10-19 from `core/quintacle_core/nodes/kb/chat.py`
(`_system_text`, `_kb_context`, `_topic_context`), `core/quintacle_core/nodes/kb/api.py`
(the `/kb/chat` + `/kb/record-that*` endpoints) and `frontend/app/kb/page.tsx`.
Restamp if regenerated. Decision log: `docs/next-wave-plan.md` §3 (decision 2,
opened by the owner 2026-10-19) and §4.

The KB chat no longer dumps every note into the prompt. Context is assembled
deterministically per turn by `_system_text(store, use_kb, folder, slug,
messages)` — the same assembly for every provider, so escalating to a cloud
model transfers the identical context.

## Assembly order (extended 2026-10-20 — next-wave-plan §10)

Code-derived from `chat._system_text` + the new
`core/quintacle_core/nodes/kb/day_context.py`. The system text is now, in
order:

1. **The Now line** — `Now: Tuesday 2026-10-20, 7:45 PM (America/New_York).`
   (`chat._now_line`, Eastern via clock.py). ALWAYS first, for every
   provider; with `use_kb=false` it's the entire system text (chat knows now
   even with the KB off — `_system_text` no longer returns None).
2. **`## About the user`** — `day_context.me_context(store)`: every note in
   the KB folder `Me` (capped ~3,000 chars) + live facts computed from SQL
   at ask-time (strength PRs from `exercise_sets.sets_json` via `json_each`,
   this month's income/spend/savings rate from `income_log`/`expense_log`,
   latest `body_stats` per metric), each with an as-of date and a
   never-recalculate instruction line. Present in ALL scopes (the Me lane is
   §10's "chat always hydrates it" decision); both halves empty → the block
   is omitted entirely. Never stored — recomputed per turn.
3. **The scope's KB block** — unchanged mechanics (retrieval / topic
   hydration / folder dump, see below), with `_LINK_RULES` now appended to
   the grounding rules: the model links notes as
   `[Title](/kb/browse?path=<folder>&open=<slug>)` and file assets as
   `[name](/kb/asset?folder=<folder>&path=<asset path>)` — the frontend's
   real routes (browse deep-link params; `kbAssetUrl` shape), only for
   ids/paths already present in context.
4. **Day bundles** — when `day_context.detect_dates` finds date words in the
   newest user message (explicit forms + relative words, year inference =
   most recent past occurrence, `today = clock.today()`), up to 3 dates each
   hydrate `## <date> — that day's record`: the journal (incl. auto
   photo-journal who-with lines), every SQLite log row as its
   already-computed one-liner (`retrieval.log_row_title_and_summary`), todos
   due/completed, and the day's events + 1-hop people/place edge labels —
   capped ~6,000 chars/day, truncated last-section-first. Pure code, zero
   model calls. Unscoped + note-scoped chats only; the folder-only scope
   keeps its "can't cite outside the folder" contract (no bundles there).

Every §10 addition degrades silently (stores not wired / SQL error → the
section drops), never a 500. Tests: `core/tests/test_day_context.py`.

## The three scopes

| Scope | Context |
|---|---|
| none (the main chat page) | retrieval hits for the latest question |
| `folder` + `slug` (chat continued ON a note) | topic hydration block, then retrieval hits (topic excluded) |
| `folder` only (the per-folder chat) | **unchanged** — exactly that folder's entries, no global retrieval (its contract: an answer can't come from somewhere it can't cite) |

`use_kb=false` → no KB block at all, same as before.

## The retrieval path (`_kb_context`)

1. **Query** = the newest user turn's typed text (`_last_user_text`; text
   blocks only — attachment placeholders never pollute the FTS query).
2. **Select**: `RetrievalIndex.retrieve(query, k=8)` — FTS5 + optional
   vectors, RRF-fused, graph-expanded (`docs/reference/retrieval.md`). Order
   is retrieve()'s own: score desc, id tiebreak. No model call anywhere.
3. **Fetch** per hit (`_hit_section`):
   - **Prose hits** (`note`/`place`/`person`/`journal_day`) get their FULL
     current content — notes via `KBStore.read` (+ freeform `fields`, title
     heading stripped since the section header already carries it), journal
     days via the journal store — capped at **4,000 chars** each.
   - **Structured hits** (expense/food/exercise/meal/routine/todo/event/…)
     enter as their already-computed one-line summary from `nodes_index`,
     as-is — finished numbers from SQLite; the system text explicitly tells
     the model to never recalculate them.
   - Each section ends with the hit's 1-hop neighbor labels:
     `Connected: <title> (<edge_type>, id: <id>); …`. The chat loop is
     single-shot (no tool turns), so the model is instructed to ASK the user
     to bring a neighbor up rather than pretending it can fetch it.
4. **Budget**: sections accumulate under a **24,000-char** total cap; a hit
   whose full body would blow the budget degrades to its summary-line form
   (order never reshuffles — deterministic given the same store state).
5. Zero hits on a populated index → a literal "nothing in the knowledge base
   matched this question" line (the model says so instead of guessing).

## Topic hydration (`_topic_context`)

`## Current topic: <title> [note:<folder>/<slug>]` + the note's fields +
full body (capped at **8,000** chars) + its `Connected:` neighborhood line
(`retrieval.neighbor_labels()` — degrades to nothing). Retrieval hits for
the latest question follow under `## Retrieved for the latest question`,
with the topic's own id excluded. **No transcript is ever loaded
automatically** — transcripts are second-tier by decision (§4).

The frontend's existing "continue in chat" affordance now sends the note's
folder+slug on `/kb/chat` (`slug` is the new request field); `Escalate ↗`
re-sends the same scope.

## Degradation ladder (never a 500)

1. Retrieval up → the path above.
2. Retrieval singleton uninitialized, index EMPTY (never backfilled), or any
   retrieval error → caught in `_system_text`:
   - unscoped chat → `_kb_context_everything` — the ORIGINAL dump-everything
     context, kept verbatim as the fallback;
   - note-scoped chat → the topic block still hydrates (plain store reads),
     with the folder's entries standing in for retrieval.
3. Folder-only chat never touches retrieval in the first place.

An empty-but-initialized index deliberately falls back to the dump rather
than answering "nothing matched" — a fresh process over an old store that
was never backfilled must not look like an empty KB.

## Transcripts: the explicit lane

A `FileSearch` button on the chat input row calls `GET /transcripts/search`
with the typed text and appends the hits (topic, date, snippet) to the log
as a deterministic assistant-side message (`model: "transcripts"`, zero
model calls) — so they're in context for the next turn. That button is the
ONLY way transcript content reaches a chat; the archive stays excluded from
the retrieval index (`is_excluded`) and from every default surface.

## "Record that" — explicit consolidation, gated

Propose→review→Save, same contract as `/kb/sort` + `/kb/entries`:

1. **Propose** — `POST /kb/record-that {messages, folder?, slug?, provider?}`
   (the chat-header button). Distills the conversation into bullet points
   via `llm.suggest_record_fold` (scoped: points only) or
   `suggest_record_fold_new` (unscoped: also proposes folder + title against
   the real folder list / notes index) — `llm_dispatch.parse_structured`,
   so the normal local-first routing and the `provider` step-back apply. The
   date header is computed IN CODE (`clock.today()`, Eastern):
   `### <date> — from chat`. **Writes nothing.** 400 on readable model
   failures, 404 when the scoped note is gone, 400 on an empty conversation.
2. **Review** — the proposal opens in a panel on the scratchpad side:
   folder, note title, and the dated entry are all editable (folder/title
   prefilled from the scoped topic, or model-proposed when unscoped — the
   user picks/confirms there).
3. **Save** — `POST /kb/record-that/save {folder, title, append}` (the
   "Append to note" button). Reads the existing note (title is slugified,
   same as `write`), carries its body through **verbatim in code**, and
   appends the dated block — history is never rewritten, per the
   docs-are-decision-logs principle. No matching note → a new one is created
   from the dated entry. The write runs the existing machinery:
   `KBStore.write` (frontmatter links/fields preserved),
   `_sync_note_graph_links`, `safe_index_note`.

## Tests

`core/tests/test_chat_context.py` — preset-seeded sandbox (meals, routine,
person, experience, notes, expense row per CLAUDE.md's seeding rule), all
provider runners stubbed: selection vs dump, finished summary lines,
neighbor labels, every fallback rung, topic hydration, folder-scope
invariance, transcripts staying out of default context, escalation context
equality, and the full record-that flow (propose writes nothing; save
appends without rewriting; new-note creation; 400/404 edges).


## 2026-11-05 — the private note flag (code-derived)

Owner rule: a KB note with `private: true` frontmatter never reaches a cloud
model. One definition, `core/quintacle_core/nodes/kb/privacy.py`
(`is_private_meta`, `is_private_node`, `private_filter`, `PrivacyGate`,
`strip_private_turns`, `public_notes_index`, `private_manual_entry`).

- **Context assembly.** `run_kb_chat` builds a `PrivacyGate(store,
  allow_private = provider == "local")` and threads it through
  `_build_context` → `_me_block` (`day_context.me_context` /
  `_curated_me_notes`), `_kb_context` (retrieval's `exclude` hook, applied
  BEFORE the k cut, plus every neighbor label), `_topic_context` (a private
  topic note does not hydrate a cloud turn), `_kb_context_for_folder`,
  `_kb_context_everything` (legacy fallback) and `_day_blocks`
  (`day_context.day_bundle` / `_connections_section`: neighbor labels and
  event members). Omitting the gate = the cloud-safe default. Prompting,
  ordering, budgets and session logic are unchanged — this is the minimal
  filter the owner explicitly opened chat.py for.
- **Which notes a reply used.** The gate records every private note that
  entered context (content OR a neighbor title); `/kb/chat` returns them as
  `private_notes` (local only; key omitted when empty). The frontend keeps
  the list on the assistant message (`ChatMessage.private_notes`).
- **Cloud handoff.** For any non-`local:` model, `/kb/chat` runs
  `strip_private_turns` first: every assistant turn carrying
  `private_notes` is dropped together with the user turn that prompted it
  (the newest message always stays), the marker key is removed from every
  message, and `private_stripped` (distinct notes left out) comes back —
  the UI shows "N private notes were left out of the cloud handoff."
  (Chat page and the overview Assist panel). Escalate ↗ goes through the
  same endpoint, so it is covered.
- **Record that.** A conversation with any marked turn, or a private
  target note, distills on `provider="local"` only (explicit cloud → 400);
  the new-note fold sees `public_notes_index` titles.
- **Transcripts.** `TranscriptStore.archive` keeps private-context turns in
  the verbatim file (frontmatter `private_turns: N`) but leaves them out of
  the FTS row — the only read lane (recent-chats recall, transcript search).

Tests: `core/tests/test_private_notes.py`.


## 2026-11-05 — the web lane for models without native search (code-derived)

Cloud Claude (`web_search` server tool), GPT (Responses `web_search`) and
Max (`WebSearch`/`WebFetch`) search natively and are untouched. Local
(Ollama) and Bedrock models have no search, so for them **code** searches
and fetches and the model only reads (`core/quintacle_core/web_search.py`).

- **When:** `ChatRequest.web` — `null` (default) = auto, `true`/`false` =
  forced. Auto (`needs_web`) is a deterministic regex: on for external cues
  (latest, today, news, price of, opening hours, how do I, visa,
  requirements, weather, near me, an explicit URL...), but **off** when the
  message is about the owner's own data (my / I / our...) unless the cue
  is strong (URL, weather, visa, news, near me...). Auto never fires in
  serious mode. An explicit `web: true` does work there, and a non-empty
  web block counts as something to ground on (no zero-match short-circuit).
- **What:** `build_query` strips filler from the newest user message.
  Search runs on DuckDuckGo's HTML endpoint (stdlib `html.parser`), or on
  SearXNG JSON when `QUINTACLE_SEARXNG_URL` is set. URLs in the message are
  fetched directly as the first sources. The top 3 pages are fetched in
  parallel threads (8 s each, about 20 s total). Scripts, styles, nav,
  header and footer are stripped, and each page is capped at about 3k
  chars.
- **Where:** a `## Web results (fetched just now) — search query: "…"`
  block with numbered `[n] title — url` sources is appended after the
  assembled KB context. It tells the model to cite `[1]`, `[2]`, to list
  the sources as markdown links, and to say plainly when the results don't
  answer the question. `run_kb_chat` adds it in one call to
  `chat_web_block(provider, web, last_user_text, mode)`.
- **Privacy:** the ONLY thing that leaves the machine is the search query,
  and it is built purely from the user's newest typed text. KB context,
  note bodies, private notes and earlier turns are never part of it.
  (Fetching a result URL also tells that site you visited it, the same as
  opening the link.) Test:
  `test_web_search.py::test_no_native_search_providers_get_web_block`.
- **Failure:** every error (timeout, DNS, parse) degrades to no block, so
  chat proceeds as before. `QUINTACLE_WEB_SEARCH=off` is a global kill
  switch, and the test suite sets it in `conftest.py`.
- **UI:** a "Web: auto / on / off" chip next to the Mode chip on `/kb`.
  Its tooltip notes that cloud models search natively. AssistPanel sends
  auto.

## 2026-11-05 — the owner's own photos inline (code-derived)

`core/quintacle_core/nodes/kb/my_photos.py`, wired from `chat.py` in three
small places (`_kb_context(photos=)`, `_build_context(photos=)`, and the
reply post-pass in `run_kb_chat`).

- **Handles.** `run_kb_chat` makes one `PhotoRegistry` per request. After
  `_kb_context` assembles its sections, `PhotoRegistry.collect` walks the
  hits and their neighbors in retrieval order. That includes the place
  hierarchy's `located_in` members, so "photos from Europe" reaches photos in
  Vienna. A `note:` node counts as a photo when its frontmatter
  `assets`/`asset`/`asset2` or a body `[asset](…)` line names an existing
  jpg/jpeg/png/webp/gif/avif. Each photo gets `P1`, `P2`… (at most 24 per
  turn). One block, `## Your photos in this context`, lists
  `[photo:Pn] title · City, Country · YYYY-MM-DD · first prose line (id: …)`.
  The block carries the rule, so every provider gets it, and only when a
  photo is present: write `{{myphoto:Pn}}` on its own line to show it.
- **Rendering.** `render_my_photos` runs before `_resolve_photo_tags` and
  `validate_reply_links`. Each tag becomes
  `![City, Country · date](/kb/asset?folder=…&path=…&open=<slug>)`, and a
  handle that isn't in the map is dropped silently. `validate_reply_links`
  already checks that `/kb/asset` route exists. `open` is ignored by the
  backend, and ChatLog uses it for the Browse link.
- **Fallback for weak models.** If the user's message asks for photos
  (photo/pic/picture/image/snap/selfie) and the reply showed none, code
  appends `Your photos:` plus up to 6 handles. They are ranked by how many of
  the query's content words appear in each photo's line, and ties keep
  retrieval order.
- **Privacy.** Every node passes through the request's `PrivacyGate.admit`
  before it registers. For cloud, retrieval's exclude hook has already
  dropped private nodes, and the gate refuses them again. So a cloud
  context, and therefore a cloud reply, never holds a private photo. Local
  requests may show them, and those photos land in `gate.used` like any
  other private note.
- **Frontend.** `ChatLog.tsx` renders `MarkdownImage` and
  `MarkdownParagraph`. A `/kb/asset?` image becomes a square tile with its
  src resolved against `API_BASE`; clicking it opens the note in Browse. A
  paragraph made only of such tiles becomes a 2-column grid (3 columns from
  `sm`). Transcripts keep the markdown as-is.
- Tests: `core/tests/test_chat_my_photos.py`.
