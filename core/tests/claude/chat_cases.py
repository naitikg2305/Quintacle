"""KB chat checks — written once, run by BOTH live suites (local qwen via
Ollama, and Claude via Max). provider is "local" or "cloud", same convention
as sort_cases; it picks the chat model id from /kb/models.

Expectations are the CORRECT product behaviour, fixed up front:
- chat answers from the user's notes (a seeded fact comes back);
- a `private: true` note MAY ground a local answer, but its content (and
  title) NEVER reaches a cloud model — not via retrieval, and not via a
  local->cloud handoff of an earlier turn that used it (privacy.py);
- the transcript autosave keeps ONE file per chat session (transcripts.py).
Model answers get substring checks only."""
import json

from quintacle_core import max_backend

CHAT_MODEL = {"local": "local:qwen3:8b", "cloud": "max:haiku"}

# Seeds use folders no other suite writes to, and titles unique to this file.
FACT_FOLDER = "Knowledge/Chat Live Facts"
FACT_TITLE = "Gold's Gym membership details"
FACT_BODY = "My locker code at Gold's Gym is 4417. I go on weekday mornings."
FACT_CODE = "4417"

PRIVATE_FOLDER = "Personal/Chat Live Private"
# The title carries a unique marker word: titles must not reach cloud either.
PRIVATE_TITLE = "Quillfeather storage unit gate"
PRIVATE_MARKER_WORD = "Quillfeather"
PRIVATE_BODY = "The gate code for my storage unit at Extra Space on Route 1 is 59173."
PRIVATE_SECRET = "59173"
PRIVATE_QUESTION = "What's the gate code for my storage unit?"

TRANSCRIPT_SUBJECT = "chat live transcript autosave check"


def _model(c, provider):
    model = CHAT_MODEL[provider]
    r = c.get("/kb/models")
    assert r.status_code == 200, r.text
    assert model in {m["id"] for m in r.json()}, f"{model} missing from /kb/models"
    return model


def _chat(c, provider, messages, **kw):
    body = {"messages": messages, "model": _model(c, provider), "web": False, **kw}
    if provider != "cloud":
        r = c.post("/kb/chat", json=body)
    else:
        # chat._run_max falls back to the metered API through a direct
        # anthropic.Anthropic() call that harness._max_only doesn't cover —
        # block it here so a Max failure fails the test instead of spending.
        from quintacle_core.nodes.kb import chat as kb_chat

        real_api = kb_chat._run_anthropic

        def no_api(*a, **k):
            raise AssertionError("Max failed and chat fell back to the metered API (blocked in tests)")

        kb_chat._run_anthropic = no_api
        try:
            r = c.post("/kb/chat", json=body)
        finally:
            kb_chat._run_anthropic = real_api
    assert r.status_code == 200, f"/kb/chat {r.status_code}: {r.text[:400]}"
    out = r.json()
    assert isinstance(out.get("reply"), str) and out["reply"].strip(), out
    return out


_SEEDED: dict[tuple[int, str], str] = {}


def _seed(c, folder, title, content, private=False):
    """POST a seed note once per client (session) and return its note id."""
    key = (id(c), title)
    if key not in _SEEDED:
        r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": content, "private": private})
        assert r.status_code == 200, r.text
        j = r.json()
        _SEEDED[key] = f"note:{j['folder']}/{j['slug']}"
    return _SEEDED[key]


def _fact_note(c):
    return _seed(c, FACT_FOLDER, FACT_TITLE, FACT_BODY)


def _private_note(c):
    return _seed(c, PRIVATE_FOLDER, PRIVATE_TITLE, PRIVATE_BODY, private=True)


class _CaptureMax:
    """Wraps max_backend.run (chat imports it at call time) and records the
    system text + messages actually handed to Claude."""

    def __enter__(self):
        self.sent: list[str] = []
        self._real = max_backend.run

        def spy(system, messages, *a, **k):
            self.sent.append(json.dumps({"system": system, "messages": messages}, default=str))
            return self._real(system, messages, *a, **k)

        max_backend.run = spy
        return self

    def __exit__(self, *exc):
        max_backend.run = self._real
        return False

    def text(self) -> str:
        return "\n".join(self.sent)


def check_fact_recall(c, provider):
    """A fact written in the user's own note must come back when asked — that is chat-over-KB's whole job."""
    _fact_note(c)
    out = _chat(c, provider, [{"role": "user", "content": "What's my locker code at Gold's Gym?"}])
    assert FACT_CODE in out["reply"], out["reply"][:600]


def check_private_note(c, provider):
    """Private notes are an AI-visibility boundary: local may answer from one (and says so via private_notes); cloud never receives it."""
    note_id = _private_note(c)
    msgs = [{"role": "user", "content": PRIVATE_QUESTION}]
    if provider == "local":
        out = _chat(c, provider, msgs)
        assert PRIVATE_SECRET in out["reply"], out["reply"][:600]
        assert note_id in out.get("private_notes", []), out.get("private_notes")
        return
    with _CaptureMax() as cap:
        out = _chat(c, provider, msgs)
    assert cap.sent, "Claude (Max) was never called"
    assert PRIVATE_SECRET not in cap.text(), "private note content was sent to Claude"
    assert PRIVATE_MARKER_WORD not in cap.text(), "private note title was sent to Claude"
    assert PRIVATE_SECRET not in out["reply"], out["reply"][:600]
    assert not out.get("private_notes"), out.get("private_notes")


def check_private_handoff(c, provider):
    """Escalating a chat whose earlier local reply used a private note: cloud gets that turn stripped (counted), local keeps it."""
    note_id = _private_note(c)
    msgs = [
        {"role": "user", "content": PRIVATE_QUESTION},
        {"role": "assistant", "content": f"Your storage unit gate code is {PRIVATE_SECRET}.", "private_notes": [note_id]},
        {"role": "user", "content": "Thanks. And what's my locker code at Gold's Gym?"},
    ]
    _fact_note(c)
    if provider == "local":
        out = _chat(c, provider, msgs)
        assert not out.get("private_stripped"), out
        return
    with _CaptureMax() as cap:
        out = _chat(c, provider, msgs)
    assert cap.sent, "Claude (Max) was never called"
    assert PRIVATE_SECRET not in cap.text(), "the private turn rode along in the cloud handoff"
    assert PRIVATE_MARKER_WORD not in cap.text(), "private note title was sent to Claude"
    assert PRIVATE_SECRET not in out["reply"], out["reply"][:600]
    assert out.get("private_stripped") == 1, out


def check_transcript_autosave(c, provider):
    """Per-reply autosave with one session_id must keep exactly ONE transcript file, rewritten in place, never a pile of copies."""
    from quintacle_core.nodes.kb.transcripts import get_transcript_store

    root = get_transcript_store().root
    count = lambda: len(list(root.glob("**/*.md")))  # noqa: E731
    session = "chat-live-autosave-session-1"
    turn1 = [{"role": "user", "content": "When does my apartment lease renew?"}]
    reply1 = _chat(c, provider, turn1)["reply"]
    convo = turn1 + [{"role": "assistant", "content": reply1}]

    before = count()
    r = c.post("/transcripts/archive", json={"messages": convo, "subject": TRANSCRIPT_SUBJECT, "session_id": session, "final": False})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["archived"] and first["created"] is True, first
    assert count() == before + 1, "first autosave must create exactly one file"

    convo = convo + [{"role": "user", "content": "And where did I go in Lisbon?"}]
    reply2 = _chat(c, provider, convo)["reply"]
    convo = convo + [{"role": "assistant", "content": reply2}]
    r = c.post("/transcripts/archive", json={"messages": convo, "subject": TRANSCRIPT_SUBJECT, "session_id": session, "final": False})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["archived"] and second["created"] is False, second
    assert second["path"] == first["path"], (first["path"], second["path"])
    assert second["message_count"] == 4, second
    assert count() == before + 1, "second autosave of the same session must rewrite, not add a file"
    files = list((root / first["topic"]).glob("*.md"))
    assert len(files) == 1, files
    body = files[0].read_text(encoding="utf-8")
    assert "And where did I go in Lisbon?" in body and reply2.strip()[:80] in body


ALL = [check_fact_recall, check_private_note, check_private_handoff, check_transcript_autosave]
