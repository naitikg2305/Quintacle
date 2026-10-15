"""The chat model registry and provider routing — the pure selection/dispatch
logic only. No live API calls: the provider runners are monkeypatched, the
same style as the rest of the suite."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quintacle_core.llm_config import DEFAULT_MODEL, RESEARCH_MODEL
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import chat
from quintacle_core.nodes.kb.chat import (
    BEDROCK_PREFIX,
    CHAT_MODELS,
    BedrockError,
    UnknownModelError,
    bedrock_region,
    resolve_model,
    run_kb_chat,
)
from quintacle_core.nodes.kb.store import KBStore


def make_store(tmp_path) -> KBStore:
    return KBStore(tmp_path / "kb")


# --- registry invariants ---


def test_registry_ids_are_unique():
    ids = [m["id"] for m in CHAT_MODELS]
    assert len(ids) == len(set(ids))


def test_registry_providers_are_known():
    assert {m["provider"] for m in CHAT_MODELS} <= {"anthropic", "openai", "bedrock"}


def test_every_anthropic_model_has_a_search_tool_variant():
    # _run_anthropic indexes this dict directly — a missing entry is a KeyError
    # at chat time, so catch it here instead.
    for m in CHAT_MODELS:
        if m["provider"] == "anthropic":
            assert m["id"] in chat._ANTHROPIC_SEARCH_TYPE


def test_bedrock_entries_use_the_prefix_convention():
    for m in CHAT_MODELS:
        if m["provider"] == "bedrock":
            assert m["id"].startswith(BEDROCK_PREFIX)


def test_defaults_still_resolve():
    # The folder chat / read-only chat never send a model — the env-config
    # defaults must stay resolvable or those chats break.
    assert resolve_model(None, research=False)["id"] == DEFAULT_MODEL
    assert resolve_model(None, research=True)["id"] == RESEARCH_MODEL


# --- resolve_model ---


def test_picker_choice_wins_over_research_flag():
    assert resolve_model("gpt-5-nano", research=True)["id"] == "gpt-5-nano"


def test_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        resolve_model("not-a-model", research=False)


def test_freeform_bedrock_id_resolves():
    entry = resolve_model("bedrock:us.meta.llama3-3-70b-instruct-v1:0", research=False)
    assert entry["provider"] == "bedrock"
    assert entry["id"] == "bedrock:us.meta.llama3-3-70b-instruct-v1:0"


def test_empty_bedrock_id_raises():
    with pytest.raises(UnknownModelError):
        resolve_model("bedrock:", research=False)
    with pytest.raises(UnknownModelError):
        resolve_model("bedrock:   ", research=False)


def test_curated_bedrock_entry_resolves():
    entry = resolve_model("bedrock:anthropic.claude-sonnet-5-5", research=False)
    assert entry["provider"] == "bedrock"


# --- run_kb_chat dispatch ---


def _capture_runners(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(chat, "_run_anthropic", lambda m, msgs, kb: calls.append(("anthropic", m)) or "a-reply")
    monkeypatch.setattr(chat, "_run_openai", lambda m, msgs, kb: calls.append(("openai", m)) or "o-reply")
    monkeypatch.setattr(chat, "_run_bedrock", lambda m, msgs, kb: calls.append(("bedrock", m)) or "b-reply")
    return calls


def test_dispatch_by_provider(tmp_path, monkeypatch):
    calls = _capture_runners(monkeypatch)
    store = make_store(tmp_path)
    msgs = [{"role": "user", "content": "hi"}]

    assert run_kb_chat(store, msgs, use_kb=False, research=False, model="claude-sonnet-5-5") == "a-reply"
    assert run_kb_chat(store, msgs, use_kb=False, research=False, model="gpt-4o-mini") == "o-reply"
    assert run_kb_chat(store, msgs, use_kb=False, research=False, model="bedrock:whatever.model-v1:0") == "b-reply"
    assert calls == [
        ("anthropic", "claude-sonnet-5-5"),
        ("openai", "gpt-4o-mini"),
        ("bedrock", "bedrock:whatever.model-v1:0"),
    ]


def test_dispatch_honors_the_selected_model_not_the_default(tmp_path, monkeypatch):
    calls = _capture_runners(monkeypatch)
    store = make_store(tmp_path)
    run_kb_chat(store, [{"role": "user", "content": "hi"}], use_kb=False, research=False, model="claude-opus-5-5")
    assert calls == [("anthropic", "claude-opus-5-5")]
    assert calls[0][1] != DEFAULT_MODEL


# --- bedrock internals ---


def test_bedrock_routes_claude_ids_to_anthropic_client(monkeypatch):
    seen = {}
    monkeypatch.setattr(chat, "_run_bedrock_anthropic", lambda raw, msgs, kb: seen.setdefault("anthropic", raw) or "x")
    monkeypatch.setattr(chat, "_run_bedrock_converse", lambda raw, msgs, kb: seen.setdefault("converse", raw) or "x")

    chat._run_bedrock("bedrock:anthropic.claude-sonnet-5-5", [], None)
    chat._run_bedrock("bedrock:us.amazon.nova-lite-v1:0", [], None)
    # The prefix is stripped before the raw ID reaches AWS.
    assert seen == {"anthropic": "anthropic.claude-sonnet-5-5", "converse": "us.amazon.nova-lite-v1:0"}


def test_bedrock_region_resolution(monkeypatch):
    for var in ("QUINTACLE_BEDROCK_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    assert bedrock_region() == "us-east-1"
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert bedrock_region() == "eu-west-1"
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    assert bedrock_region() == "us-west-2"
    monkeypatch.setenv("QUINTACLE_BEDROCK_REGION", "ap-south-1")
    assert bedrock_region() == "ap-south-1"


def test_to_converse_messages_conversion():
    img = base64.b64encode(b"img-bytes").decode()
    pdf = base64.b64encode(b"pdf-bytes").decode()
    messages = [
        {"role": "user", "content": "plain text"},
        {"role": "assistant", "content": [{"type": "text", "text": "reply"}]},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpg", "data": img}},
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
            ],
        },
    ]
    out = chat._to_converse_messages(messages)
    assert out[0] == {"role": "user", "content": [{"text": "plain text"}]}
    assert out[1] == {"role": "assistant", "content": [{"text": "reply"}]}
    assert out[2]["content"][0] == {"text": "look at this"}
    assert out[2]["content"][1] == {"image": {"format": "jpeg", "source": {"bytes": b"img-bytes"}}}
    assert out[2]["content"][2] == {"document": {"format": "pdf", "name": "document", "source": {"bytes": b"pdf-bytes"}}}


# --- error degradation at the API layer ---


def make_client(tmp_path) -> TestClient:
    app = FastAPI()
    kb_api.init_store(tmp_path / "kb")
    kb_api.init_chat_store(tmp_path / "chats")
    app.include_router(kb_api.router)
    return TestClient(app)


def test_bedrock_failure_is_a_readable_400_not_a_500(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise BedrockError("AWS credentials problem: token expired — configure AWS credentials to use Bedrock models")

    monkeypatch.setattr(kb_api, "run_kb_chat", boom)
    client = make_client(tmp_path)
    res = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "hi"}], "model": "bedrock:x.y-v1:0"})
    assert res.status_code == 400
    assert "AWS credentials" in res.json()["detail"]


def test_unknown_model_is_a_readable_400(tmp_path):
    client = make_client(tmp_path)
    res = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "hi"}], "model": "nope"})
    assert res.status_code == 400
    assert "unknown chat model" in res.json()["detail"]
