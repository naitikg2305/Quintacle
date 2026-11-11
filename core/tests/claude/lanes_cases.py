"""Background model lanes — written once, run by BOTH live suites (local qwen
via Ollama, and the Max suite). provider is "local" or "cloud", same
convention as chat_cases.

harness._env forces every lane below OFF for the whole live run, so each
check turns ONLY its own lane back on inside a context manager and restores
the previous value afterwards. How each lane reads its switch (checked in
the code, 2026-11-11):
- QUINTACLE_SUMMARY_PROVIDER — read at call time (retrieval.prose_summary).
- QUINTACLE_SOFT_RECORD_PROVIDER — read at call time (soft_record.extract_facts).
- QUINTACLE_WEB_SEARCH — read at call time (web_search.chat_web_block).
- QUINTACLE_VECTOR_LANE — read ONCE per _VectorLane and CACHED in its
  `_available` flag (the seed's first index write already cached False), so
  _vector_lane() also resets that flag on the live index and puts the old
  value back on exit.

Expectations are the CORRECT product behaviour, fixed up front:
- prose_summary: a local-model one-liner (under 20 words) naming the note's
  subject, NOT the deterministic first-line fallback;
- vector lane: a paraphrase with zero shared words still finds the note
  (top 3) — something FTS5 alone cannot do;
- soft record: a closed (final) chat yields the straight fact the user
  stated, and nothing the assistant said;
- web lane: a fresh-fact question with web on gets an answer that cites a
  real source URL. Local chat gets code-fetched results (only a query
  derived from the user's message leaves the machine); Max searches
  natively, so the code lane must never run for it.
- summary / embeddings / soft-record extraction are pinned LOCAL: even in
  the cloud suite they must never make a cloud call.
Model output gets substring checks only."""
import os
import re
from contextlib import contextmanager

import pytest

from quintacle_core import llm_dispatch, max_backend, retrieval, web_search
from tests.claude import chat_cases
from tests.claude.harness import MAX_CALLS, CloudBlocked, missing_requirements, ollama_models

# A folder no other suite writes to.
LANES_FOLDER = "Knowledge/Lanes Live"

# prose_summary: the first line says nothing about the subject, so the
# deterministic fallback (first non-empty line) can't pass the subject check.
SUMMARY_TITLE = "Notes from Saturday"
SUMMARY_BODY = (
    "Quick notes before I forget.\n"
    "Took the Honda Civic to Jiffy Lube for an oil change and tire rotation. "
    "The mechanic said the front brake pads are down to 3mm and need replacing within a month. "
    "Paid $89."
)
# The note is about servicing the car; any of these names that subject.
SUMMARY_SUBJECT = ("brake", "oil change", "oil", "civic", "honda", "car", "tire", "jiffy lube", "mechanic")

# Vector lane: the query shares NO word with the note (checked in-test).
VECTOR_TITLE = "Sourdough starter feeding schedule"
VECTOR_BODY = (
    "Starter gets equal parts flour and water, 50 g each, twice daily at 8 am and 8 pm.\n"
    "Discard half before each feeding. Keep the jar on the counter; it doubles in about 6 hours."
)
VECTOR_QUERY = "how often do I feed my bread yeast culture"

# Soft record: one clear personal fact, plus assistant chatter that must not be stored.
SOFT_USER = "My sister's name is Priya and she lives in Austin."
SOFT_ASSISTANT = "That's lovely! Austin is a great city. Have you visited her there recently?"
SOFT_SESSION = "lanes-live-soft-record-session-1"

# Web lane: a fresh fact no model knows from training alone.
WEB_QUESTION = "What is the latest stable release of the Linux kernel right now?"


# --- lane switches -------------------------------------------------------------


@contextmanager
def _env(var: str, value: str):
    """Set one env var for the duration, then restore it exactly (or unset it)."""
    old = os.environ.get(var)
    os.environ[var] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old


@contextmanager
def _vector_lane():
    """QUINTACLE_VECTOR_LANE on AND the live index's cached probe reset, so
    the next index write re-probes sqlite-vec + Ollama instead of reusing the
    False cached while the harness had the lane off."""
    lane = retrieval.get_retrieval_index().vectors
    old = lane._available
    with _env("QUINTACLE_VECTOR_LANE", "on"):
        lane._available = None
        try:
            yield lane
        finally:
            lane._available = old


class _CloudSpy:
    """Records (and refuses) any cloud call made while active: the metered
    structured parse (llm_dispatch._parse_cloud) and the Max CLI
    (max_backend.run). Pinned-local lanes must leave both lists empty."""

    def __enter__(self):
        self.calls: list[str] = []
        self._parse = llm_dispatch._parse_cloud
        self._run = max_backend.run
        self._max_before = len(MAX_CALLS)

        def parse_cloud(*a, **k):
            self.calls.append("llm_dispatch._parse_cloud")
            raise CloudBlocked("cloud parse attempted by a lane pinned local")

        def max_run(*a, **k):
            self.calls.append("max_backend.run")
            raise CloudBlocked("Max call attempted by a lane pinned local")

        llm_dispatch._parse_cloud = parse_cloud
        max_backend.run = max_run
        return self

    def __exit__(self, *exc):
        llm_dispatch._parse_cloud = self._parse
        max_backend.run = self._run
        return False

    def assert_none(self):
        assert not self.calls, f"a local-pinned lane went to the cloud: {self.calls}"
        assert len(MAX_CALLS) == self._max_before, "a local-pinned lane called Claude (Max)"


def _need_local_parse():
    """Lanes pinned to the local parse model need Ollama + qwen3:8b — the
    Max suite's conftest only checks for the claude CLI."""
    reason = missing_requirements()
    if reason:
        pytest.skip(reason)


def _save_note(c, title, content) -> str:
    r = c.post("/kb/entries", json={"folder": LANES_FOLDER, "title": title, "content": content})
    assert r.status_code == 200, r.text
    j = r.json()
    return f"note:{j['folder']}/{j['slug']}"


def _norm_url(u: str) -> str:
    return u.strip().rstrip("/.,;:)]>").rstrip("/").lower()


def _urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>\]\"']+", text or "")


# --- checks --------------------------------------------------------------------


def check_prose_summary(c, provider):
    """Saving a note with the summary lane on stores a local-model one-liner (<20 words) naming its subject, not the first-line fallback."""
    _need_local_parse()
    with _env(retrieval.SUMMARY_PROVIDER_ENV, "local"), _CloudSpy() as spy:
        note_id = _save_note(c, SUMMARY_TITLE, SUMMARY_BODY)
    spy.assert_none()
    row = retrieval.get_retrieval_index().get_node(note_id)
    assert row is not None, f"{note_id} never reached nodes_index"
    summary = (row["summary"] or "").strip()
    fallback = retrieval.deterministic_prose_summary(SUMMARY_BODY, SUMMARY_TITLE)
    assert summary, "stored summary is empty"
    assert summary != fallback, f"the model never ran — the stored summary is the deterministic fallback: {summary!r}"
    assert "\n" not in summary, summary
    assert len(summary.split()) < 20, f"summary is not under 20 words: {summary!r}"
    low = summary.lower()
    assert any(re.search(rf"\b{re.escape(t)}s?\b", low) for t in SUMMARY_SUBJECT), f"summary doesn't name the subject (car service): {summary!r}"


def check_vector_lane(c, provider):
    """With the vector lane on, a no-shared-words paraphrase finds the sourdough note in the top 3 — FTS5 alone can't; embeddings never go to the cloud."""
    try:
        import sqlite_vec  # noqa: F401 — requirements-retrieval.txt
    except ImportError:
        pytest.skip("sqlite-vec isn't installed (pip install -r core/requirements-retrieval.txt)")
    models = ollama_models()
    if models is None:
        pytest.skip("Ollama isn't running (start it with `ollama serve`)")
    embed = retrieval.embed_model()
    if embed not in models and f"{embed}:latest" not in models:
        pytest.skip(f"Ollama is missing the embedding model {embed} (`ollama pull {embed}`)")

    index = retrieval.get_retrieval_index()
    with _vector_lane() as lane, _CloudSpy() as spy:
        note_id = _save_note(c, VECTOR_TITLE, VECTOR_BODY)
        assert lane._available is True, "vector lane didn't come up (sqlite-vec failed to load or the embedding call failed)"
        # Test-design guard: the paraphrase must be invisible to FTS5, or
        # this wouldn't be measuring the vector lane at all.
        assert note_id not in index._fts_ids(VECTOR_QUERY, 100), "the query shares a word with the note — FTS5 finds it; fix the test inputs"
        r = c.get("/retrieve", params={"q": VECTOR_QUERY, "k": 3})
        assert r.status_code == 200, r.text
    spy.assert_none()
    ids = [h["id"] for h in r.json()["results"]]
    assert note_id in ids, f"{note_id} not in the top 3 for a paraphrase: {ids}"


def check_soft_record(c, provider):
    """Archiving a closed chat (final) records the user's stated fact (sister Priya, lives in Austin) and none of the assistant's chatter."""
    _need_local_parse()
    messages = [
        {"role": "user", "content": SOFT_USER},
        {"role": "assistant", "content": SOFT_ASSISTANT},
    ]
    with _env("QUINTACLE_SOFT_RECORD_PROVIDER", "local"), _CloudSpy() as spy:
        # TestClient runs FastAPI BackgroundTasks before the call returns, so
        # extract_and_store has finished (synchronously) by the next line.
        r = c.post(
            "/transcripts/archive",
            json={"messages": messages, "subject": "family", "session_id": SOFT_SESSION, "final": True},
        )
    spy.assert_none()
    assert r.status_code == 200, r.text
    archived = r.json()
    assert archived["archived"] and archived.get("soft_facts_pending") is True, archived

    r = c.get("/soft-record")
    assert r.status_code == 200, r.text
    facts = [f["text"] for f in r.json() if f["transcript"] == archived["path"]]
    assert facts, f"no soft-record fact extracted from {archived['path']}"
    joined = " ".join(facts).lower()
    assert "priya" in joined, facts
    assert "austin" in joined, facts
    assert "sister" in joined, facts
    assert "great city" not in joined and "visited" not in joined, f"assistant chatter was recorded as a fact: {facts}"


def check_web_lane(c, provider):
    """A fresh-fact question with web on is answered citing a real source URL; local reads code-fetched results (query from the user's words only), Max searches natively and never runs the code lane."""
    searches: list[str] = []
    found: list[dict] = []
    real_search = web_search.search

    if provider == "local":
        if web_search.backend() not in ("searxng", "brave"):
            pytest.skip("no web search backend configured (add a Brave key)")

        def spy(query, *a, **k):
            searches.append(query)
            out = real_search(query, *a, **k)
            found.extend(out)
            return out
    else:

        def spy(query, *a, **k):
            searches.append(query)
            return real_search(query, *a, **k)

    web_search.search = spy  # web_block looks `search` up in the module at call time
    try:
        with _env("QUINTACLE_WEB_SEARCH", "on"):
            before = len(MAX_CALLS)
            out = chat_cases._chat(c, provider, [{"role": "user", "content": WEB_QUESTION}], web=True)
    finally:
        web_search.search = real_search

    reply = out["reply"]
    cited = {_norm_url(u) for u in _urls(reply)}
    assert cited, f"reply cites no URL: {reply[:600]}"
    if provider == "local":
        assert searches, "web lane never searched"
        assert found, f"web search returned nothing for {searches}"
        q_words = set(re.findall(r"\w+", " ".join(searches).lower()))
        msg_words = set(re.findall(r"\w+", WEB_QUESTION.lower()))
        assert q_words <= msg_words, f"search query carried words not in the user's message: {q_words - msg_words}"
        fetched = {_norm_url(r["url"]) for r in found}
        assert cited & fetched, f"reply cites none of the fetched sources.\ncited: {sorted(cited)}\nfetched: {sorted(fetched)}"
    else:
        assert len(MAX_CALLS) > before, "Claude (Max) was never called"
        assert not searches, f"the code web lane ran for Max, which searches natively: {searches}"


ALL = [check_prose_summary, check_vector_lane, check_soft_record, check_web_lane]
